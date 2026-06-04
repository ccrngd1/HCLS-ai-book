# Recipe 8.6: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 8.6. It shows one way you could translate those concepts into working Python code using boto3, Amazon Comprehend Medical, and Amazon Comprehend custom classification. It is not production-ready. Think of it as a sketchpad: useful for understanding the shape of the solution, not something you'd deploy against real patient notes on Monday morning. A starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `comprehendmedical:DetectEntitiesV2`
- `comprehend:ClassifyDocument`
- `s3:GetObject`, `s3:PutObject`
- `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:GetItem`
- `sqs:ReceiveMessage`, `sqs:DeleteMessage`

---

## Config and Constants

Before we get into the logic, here are the configuration values and lookup tables that drive the pipeline. The SDOH keyword list determines which notes get full NLP processing (and which ones we skip to save cost). The domain code map connects extracted categories to standard terminology for downstream interoperability.

```python
import json
import logging
import re
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log PHI field values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles burst throttling from Comprehend Medical.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# AWS clients
comprehend_medical = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
comprehend = boto3.client("comprehend", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# Table name. Replace with your actual DynamoDB table name.
SDOH_PROFILES_TABLE = "sdoh-profiles"

# The ARN of your trained Comprehend custom classifier endpoint.
# You must train and deploy this before running the pipeline.
# See the main recipe for training data requirements.
SDOH_CLASSIFIER_ENDPOINT_ARN = "arn:aws:comprehend:us-east-1:123456789012:document-classifier-endpoint/sdoh-classifier"

# Confidence threshold for accepting an SDOH classification.
# Below this, we still extract but flag for human review.
CONFIDENCE_THRESHOLD = 0.75

# SDOH relevance keywords: terms that suggest a note may contain
# social determinant information. This is a high-recall filter.
# False positives are cheap (we just run NLP on a note that turns out
# to have nothing). False negatives are expensive (we miss a real need).
SDOH_KEYWORDS = [
    "housing", "homeless", "unhoused", "shelter", "evict",
    "food", "hungry", "meal", "nutrition", "food bank", "snap",
    "transportation", "ride", "bus", "car",
    "employ", "job", "unemploy", "income", "afford", "financial",
    "isolat", "alone", "support", "caregiver",
    "utility", "electric", "heat", "water",
    "safe", "violence", "abuse",
    "education", "literacy", "language barrier",
    "incarcerat", "legal", "immigration",
]

# Section header patterns for clinical notes. These help us identify
# which part of the note a sentence came from, which affects interpretation.
# A mention in "social history" is more likely an active patient need
# than one in "family history."
SECTION_PATTERNS = {
    "social_history": [
        "social history", "social hx", "shx", "psychosocial",
        "social assessment", "social work",
    ],
    "assessment_plan": [
        "assessment", "plan", "a/p", "assessment and plan",
    ],
    "family_history": [
        "family history", "family hx", "fhx",
    ],
    "discharge": [
        "discharge", "disposition", "discharge plan",
    ],
    "nursing_intake": [
        "intake", "admission screening", "social screening",
        "sdoh screening",
    ],
}

# Sections where SDOH mentions are most clinically relevant.
HIGH_PRIORITY_SECTIONS = [
    "social_history", "assessment_plan", "nursing_intake", "discharge",
]

# Standard code mappings for SDOH domains.
# Based on the Gravity Project taxonomy and ICD-10-CM Z-codes.
SDOH_CODE_MAP = {
    "housing_instability": {
        "icd10": ["Z59.0", "Z59.1", "Z59.8"],
        "loinc": ["71802-3"],
        "snomed": ["32911000"],
        "display": "Problems related to housing and economic circumstances",
    },
    "food_insecurity": {
        "icd10": ["Z59.4", "Z59.48"],
        "loinc": ["88122-7"],
        "snomed": ["733423003"],
        "display": "Lack of adequate food and safe drinking water",
    },
    "transportation_barrier": {
        "icd10": ["Z59.82"],
        "loinc": ["93031-3"],
        "snomed": ["160695008"],
        "display": "Transportation insecurity",
    },
    "financial_strain": {
        "icd10": ["Z59.5", "Z59.6", "Z59.7", "Z56.0"],
        "loinc": ["76513-1"],
        "snomed": ["454061000124102"],
        "display": "Financial strain and employment problems",
    },
    "social_isolation": {
        "icd10": ["Z60.2", "Z60.4"],
        "loinc": ["76506-5"],
        "snomed": ["422587007"],
        "display": "Social isolation and inadequate social support",
    },
    "interpersonal_safety": {
        "icd10": ["Z63.0", "T74", "T76"],
        "loinc": ["76501-6"],
        "snomed": ["706893006"],
        "display": "Interpersonal violence and safety concerns",
    },
    "education_literacy": {
        "icd10": ["Z55.0", "Z55.9"],
        "loinc": ["82589-3"],
        "snomed": ["105421008"],
        "display": "Problems related to education and literacy",
    },
    "utility_insecurity": {
        "icd10": ["Z59.81"],
        "loinc": ["93033-9"],
        "snomed": [],
        "display": "Utility insecurity",
    },
}
```

---

## Step 1: Relevance Filtering

*The pseudocode calls this `should_process_note(note_text)`. Before running expensive NLP extraction on every note, apply a quick keyword scan to identify notes worth processing. Most progress notes contain zero SDOH information, and Comprehend Medical charges per character.*

```python
def should_process_note(note_text: str) -> bool:
    """
    Quick keyword scan to decide if a note is worth full SDOH extraction.

    This is intentionally permissive (high recall, lower precision).
    We'd rather spend $0.05 processing an irrelevant note than miss
    a real SDOH mention in a note we skipped.

    Args:
        note_text: The full clinical note text.

    Returns:
        True if the note contains any SDOH-related keywords, False otherwise.
    """
    lower_text = note_text.lower()

    for keyword in SDOH_KEYWORDS:
        if keyword in lower_text:
            return True

    return False
```

---

## Step 2: Section Detection and Sentence Segmentation

*The pseudocode calls this `segment_note(note_text)`. We identify note sections (social history, assessment/plan, etc.) and split into sentences. Section context matters because "patient's mother was homeless" in family history means something different than "patient is homeless" in social history.*

```python
def detect_sections(note_text: str) -> list[dict]:
    """
    Identify sections within a clinical note based on header patterns.

    Clinical notes have implicit structure. Headers like "Social History:"
    or "Assessment and Plan:" divide the note into meaningful segments.
    We detect these headers and tag each chunk of text with its section type.

    Args:
        note_text: The full clinical note text.

    Returns:
        A list of dicts, each with:
        - text: the section content (string)
        - section_type: one of the keys in SECTION_PATTERNS, or "unknown"
    """
    # Build a combined regex that matches any known section header.
    # We look for these at the start of a line, optionally followed by a colon.
    all_patterns = []
    pattern_to_section = {}
    for section_type, headers in SECTION_PATTERNS.items():
        for header in headers:
            all_patterns.append(re.escape(header))
            pattern_to_section[header.lower()] = section_type

    # Match section headers at the start of a line (case-insensitive).
    header_regex = re.compile(
        r"^(" + "|".join(all_patterns) + r")\s*:?\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    # Find all header positions in the note.
    matches = list(header_regex.finditer(note_text))

    if not matches:
        # No recognized headers found. Treat the entire note as one "unknown" section.
        return [{"text": note_text, "section_type": "unknown"}]

    sections = []

    # Add text before the first header as "unknown" section.
    if matches[0].start() > 0:
        pre_text = note_text[: matches[0].start()].strip()
        if pre_text:
            sections.append({"text": pre_text, "section_type": "unknown"})

    # Walk through each header and capture the text until the next header.
    for i, match in enumerate(matches):
        header_text = match.group(1).lower().strip()
        section_type = pattern_to_section.get(header_text, "unknown")

        # Section content runs from end of this header to start of next header
        # (or end of note).
        content_start = match.end()
        content_end = matches[i + 1].start() if i + 1 < len(matches) else len(note_text)
        content = note_text[content_start:content_end].strip()

        if content:
            sections.append({"text": content, "section_type": section_type})

    return sections


def segment_into_sentences(text: str) -> list[str]:
    """
    Split text into sentences using simple heuristics.

    Clinical text doesn't follow standard English sentence rules.
    Abbreviations (Dr., pt., q.d.) create false positive splits.
    This is a "good enough" approach. Production systems use more
    sophisticated sentence boundary detection (spaCy, scispacy, or
    Comprehend Medical's own sentence detection).

    Args:
        text: A block of text (typically one note section).

    Returns:
        A list of sentence strings.
    """
    # Split on period followed by space and uppercase, or on newlines.
    # This is deliberately conservative to avoid splitting on "Dr. Smith"
    # or "q.d. dosing".
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)

    # Also split on newlines (clinical notes often use line breaks as separators).
    expanded = []
    for sent in sentences:
        parts = sent.split("\n")
        expanded.extend([p.strip() for p in parts if p.strip()])

    return expanded


def segment_note(note_text: str) -> list[dict]:
    """
    Full segmentation: detect sections, split into sentences, tag each sentence
    with its section context and priority level.

    Args:
        note_text: The full clinical note text.

    Returns:
        A list of dicts, each representing one sentence with metadata:
        - text: the sentence string
        - section_type: which section it came from
        - is_priority: whether this section is high-priority for SDOH
    """
    sections = detect_sections(note_text)
    segmented = []

    for section in sections:
        sentences = segment_into_sentences(section["text"])
        for sentence in sentences:
            # Skip very short fragments (likely artifacts).
            if len(sentence) < 10:
                continue
            segmented.append({
                "text": sentence,
                "section_type": section["section_type"],
                "is_priority": section["section_type"] in HIGH_PRIORITY_SECTIONS,
            })

    return segmented
```

---

## Step 3: Medical Context Extraction with Comprehend Medical

*The pseudocode calls this `extract_medical_context(note_text)`. We pass the note through Comprehend Medical to get negation detection and entity context. The main value here is the negation map: "patient denies food insecurity" should not be flagged as an active need.*

```python
def extract_medical_context(note_text: str) -> dict:
    """
    Call Comprehend Medical to get foundational NLP context.

    We primarily care about negation detection here. Comprehend Medical
    identifies which entities in the text are negated ("denies," "no history of,"
    "patient does not have"). We use this to override assertion classification
    in the next step.

    Comprehend Medical's DetectEntitiesV2 handles up to 20,000 UTF-8 characters.
    For longer notes, you'd need to chunk the text (maintaining sentence boundaries)
    and merge results.

    Args:
        note_text: The full clinical note text (max 20,000 characters).

    Returns:
        A dict with:
        - entities: the full list of detected entities
        - negation_spans: list of (begin, end) tuples for negated text spans
    """
    # Truncate to API limit if needed. In production, chunk properly.
    text_to_process = note_text[:20000]

    response = comprehend_medical.detect_entities_v2(Text=text_to_process)

    entities = response.get("Entities", [])

    # Build negation map: character spans where Comprehend Medical detected negation.
    # "Patient denies food insecurity" would mark "food insecurity" as negated.
    negation_spans = []
    for entity in entities:
        traits = entity.get("Traits", [])
        for trait in traits:
            if trait.get("Name") == "NEGATION":
                negation_spans.append(
                    (entity["BeginOffset"], entity["EndOffset"])
                )

    return {
        "entities": entities,
        "negation_spans": negation_spans,
    }
```

---

## Step 4: SDOH Sentence Classification

*The pseudocode calls this `classify_sdoh_sentences(segmented_sentences, negation_spans)`. This is the core extraction step. For each sentence, we call the custom Comprehend classifier to determine whether it contains SDOH information and, if so, which domain it belongs to.*

```python
def is_within_negation(sentence_text: str, note_text: str, negation_spans: list) -> bool:
    """
    Check whether a sentence overlaps with any negated span from Comprehend Medical.

    This is a simplified check: we find the sentence's position in the full note
    and check if any negation span overlaps with it. In production, you'd use
    character offsets tracked from segmentation.

    Args:
        sentence_text: The sentence to check.
        note_text: The full note text (for finding position).
        negation_spans: List of (begin, end) tuples from Step 3.

    Returns:
        True if the sentence overlaps a negated span, False otherwise.
    """
    # Find where this sentence appears in the original note.
    pos = note_text.find(sentence_text)
    if pos == -1:
        return False

    sent_begin = pos
    sent_end = pos + len(sentence_text)

    # Check overlap with any negation span.
    for neg_begin, neg_end in negation_spans:
        # Overlap exists if spans intersect.
        if sent_begin < neg_end and sent_end > neg_begin:
            return True

    return False


def classify_sdoh_sentences(
    segmented_sentences: list[dict],
    negation_spans: list,
    note_text: str,
) -> list[dict]:
    """
    Classify each sentence for SDOH domain and assertion status.

    For each sentence from Step 2, call the Comprehend custom classifier
    to determine: (a) whether it contains SDOH content, and (b) which domain
    it belongs to (housing, food, transportation, etc.).

    Then cross-reference with negation spans from Step 3 to determine
    assertion status. Negated mentions get marked "absent" rather than
    "active_need."

    Args:
        segmented_sentences: Output of segment_note() (list of sentence dicts).
        negation_spans: Negation spans from extract_medical_context().
        note_text: The full original note text.

    Returns:
        A list of SDOH findings, each with domain, assertion, confidence,
        and source text.
    """
    findings = []

    for sentence_data in segmented_sentences:
        sentence_text = sentence_data["text"]

        # Call the custom classifier endpoint.
        # The response includes a list of classes sorted by confidence score.
        try:
            response = comprehend.classify_document(
                Text=sentence_text,
                EndpointArn=SDOH_CLASSIFIER_ENDPOINT_ARN,
            )
        except Exception as e:
            # Log but don't crash the whole pipeline for one sentence.
            logger.warning("Classification failed for sentence: %s", str(e))
            continue

        classes = response.get("Classes", [])
        if not classes:
            continue

        # The top class is the most likely domain.
        top_class = classes[0]
        domain = top_class["Name"]
        confidence = top_class["Score"]

        # Skip sentences classified as "none" (no SDOH content).
        if domain.lower() == "none":
            continue

        # Skip low-confidence classifications.
        if confidence < CONFIDENCE_THRESHOLD:
            continue

        # Determine assertion: is this an active need or a negated one?
        if is_within_negation(sentence_text, note_text, negation_spans):
            assertion = "absent"
        else:
            # Simple heuristic for assertion beyond negation:
            # - Past tense markers suggest "resolved"
            # - "referred to" or "connected with" suggest "resource_connected"
            # - Everything else defaults to "active_need"
            assertion = determine_assertion(sentence_text)

        findings.append({
            "text": sentence_text,
            "domain": domain,
            "confidence": confidence,
            "assertion": assertion,
            "section": sentence_data["section_type"],
            "is_priority": sentence_data["is_priority"],
        })

    return findings


def determine_assertion(sentence_text: str) -> str:
    """
    Simple rule-based assertion classification for SDOH mentions.

    In production, this would be a second classifier or a more sophisticated
    model. Here we use keyword heuristics to distinguish active needs from
    resolved ones or connected resources.

    Args:
        sentence_text: The sentence containing the SDOH mention.

    Returns:
        One of: "active_need", "resolved", "at_risk", "resource_connected"
    """
    lower = sentence_text.lower()

    # Resource-connected indicators.
    resource_patterns = [
        "referred to", "connected with", "enrolled in",
        "receiving services", "food bank providing", "voucher",
        "approved for", "started receiving",
    ]
    for pattern in resource_patterns:
        if pattern in lower:
            return "resource_connected"

    # Resolved indicators.
    resolved_patterns = [
        "no longer", "resolved", "now has stable",
        "secured housing", "found employment", "obtained",
    ]
    for pattern in resolved_patterns:
        if pattern in lower:
            return "resolved"

    # At-risk indicators (not yet a need, but heading that direction).
    risk_patterns = [
        "at risk", "may lose", "lease expir", "worried about",
        "concerned about", "might not be able",
    ]
    for pattern in risk_patterns:
        if pattern in lower:
            return "at_risk"

    # Default: active need.
    return "active_need"
```

---

## Step 5: Code Normalization

*The pseudocode calls this `normalize_to_codes(sdoh_findings, code_map)`. We map each classified finding to standard terminology codes (ICD-10 Z-codes, LOINC, SNOMED) for downstream interoperability.*

```python
def normalize_to_codes(findings: list[dict]) -> list[dict]:
    """
    Attach standard terminology codes to each SDOH finding.

    This enables extraction results to flow into EHR structured fields,
    quality dashboards, and population health platforms without custom
    integration per consumer. The codes come from the Gravity Project
    value sets.

    Args:
        findings: Output of classify_sdoh_sentences().

    Returns:
        The same findings list, enriched with icd10_codes, loinc_codes,
        snomed_codes, and display text for each domain.
    """
    normalized = []

    for finding in findings:
        domain = finding["domain"]

        if domain not in SDOH_CODE_MAP:
            # Unknown domain from classifier. Log and skip normalization
            # but still include the finding.
            logger.warning("No code mapping for domain: %s", domain)
            finding["icd10_codes"] = []
            finding["loinc_codes"] = []
            finding["snomed_codes"] = []
            finding["display"] = domain
            normalized.append(finding)
            continue

        codes = SDOH_CODE_MAP[domain]
        finding["icd10_codes"] = codes["icd10"]
        finding["loinc_codes"] = codes["loinc"]
        finding["snomed_codes"] = codes["snomed"]
        finding["display"] = codes["display"]
        normalized.append(finding)

    return normalized
```

---

## Step 6: Store Patient-Level SDOH Profile

*The pseudocode calls this `store_sdoh_profile(patient_id, note_id, note_date, findings)`. We write each finding to DynamoDB with provenance (which note, which date) so care managers can trace back to the source.*

```python
def store_sdoh_profile(
    patient_id: str,
    note_id: str,
    note_date: str,
    findings: list[dict],
) -> list[dict]:
    """
    Write SDOH findings to the patient's profile in DynamoDB.

    Each finding becomes a separate item, partitioned by patient_id and
    sorted by domain + note_date. This schema supports queries like:
    - "All SDOH findings for patient X" (query on partition key)
    - "All housing findings for patient X" (query with sort key prefix)
    - "All findings from the last 6 months" (query with date range)

    Args:
        patient_id: The patient's unique identifier.
        note_id: The source note's identifier (for traceability).
        note_date: When the note was written (ISO date string).
        findings: Normalized findings from Step 5.

    Returns:
        The list of records written to DynamoDB.
    """
    table = dynamodb.Table(SDOH_PROFILES_TABLE)
    records_written = []

    for finding in findings:
        # Sort key combines domain and date for efficient range queries.
        sort_key = f"{finding['domain']}#{note_date}"

        record = {
            "patient_id": patient_id,
            "sort_key": sort_key,
            "domain": finding["domain"],
            "assertion": finding["assertion"],
            "confidence": Decimal(str(round(finding["confidence"], 4))),
            # DynamoDB does not accept Python floats. Wrap in Decimal()
            # via str() to avoid floating-point artifacts.
            "source_text": finding["text"],
            "source_note": note_id,
            "note_date": note_date,
            "extraction_ts": datetime.datetime.now(timezone.utc).isoformat(),
            "icd10_codes": finding.get("icd10_codes", []),
            "loinc_codes": finding.get("loinc_codes", []),
            "snomed_codes": finding.get("snomed_codes", []),
            "display": finding.get("display", ""),
            "section": finding["section"],
            "reviewed": False,
        }

        table.put_item(Item=record)
        records_written.append(record)

    return records_written
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what your Lambda handler would call when a note arrives via SQS.

```python
def process_note_for_sdoh(
    patient_id: str,
    note_id: str,
    note_date: str,
    note_text: str,
) -> dict:
    """
    Run the full SDOH extraction pipeline for one clinical note.

    This is the main entry point. In a Lambda deployment, your handler
    would parse the SQS message (which contains the note metadata and text),
    and call this function.

    Args:
        patient_id: The patient's unique identifier.
        note_id: The note's unique identifier (for audit trail).
        note_date: When the note was written (YYYY-MM-DD).
        note_text: The full clinical note text.

    Returns:
        A summary dict with extraction results and metadata.
    """
    # Step 1: Quick relevance check. Skip notes with no SDOH keywords.
    logger.info("Step 1: Relevance filtering for note %s", note_id)
    if not should_process_note(note_text):
        logger.info("  No SDOH keywords found. Skipping full extraction.")
        return {
            "patient_id": patient_id,
            "note_id": note_id,
            "skipped": True,
            "reason": "no_sdoh_keywords",
            "findings": [],
        }

    # Step 2: Section detection and sentence segmentation.
    logger.info("Step 2: Segmenting note into sections and sentences")
    segmented = segment_note(note_text)
    logger.info("  Found %d sentences across sections", len(segmented))

    # Step 3: Get negation context from Comprehend Medical.
    logger.info("Step 3: Extracting medical context (negation detection)")
    medical_context = extract_medical_context(note_text)
    negation_spans = medical_context["negation_spans"]
    logger.info("  Found %d negation spans", len(negation_spans))

    # Step 4: Classify each sentence for SDOH content.
    logger.info("Step 4: Classifying sentences for SDOH domains")
    findings = classify_sdoh_sentences(segmented, negation_spans, note_text)
    logger.info("  Found %d SDOH findings above threshold", len(findings))

    # Step 5: Normalize findings to standard codes.
    logger.info("Step 5: Normalizing to ICD-10/LOINC/SNOMED codes")
    normalized = normalize_to_codes(findings)

    # Step 6: Store in patient profile.
    logger.info("Step 6: Storing SDOH profile in DynamoDB")
    stored = store_sdoh_profile(patient_id, note_id, note_date, normalized)
    logger.info("  Wrote %d records to DynamoDB", len(stored))

    result = {
        "patient_id": patient_id,
        "note_id": note_id,
        "note_date": note_date,
        "extraction_timestamp": datetime.datetime.now(timezone.utc).isoformat(),
        "skipped": False,
        "sentences_evaluated": len(segmented),
        "sdoh_findings_count": len(normalized),
        "findings": [
            {
                "domain": f["domain"],
                "assertion": f["assertion"],
                "confidence": f["confidence"],
                "source_text": f["text"],
                "icd10_codes": f.get("icd10_codes", []),
                "display": f.get("display", ""),
            }
            for f in normalized
        ],
    }

    logger.info("Done. Found %d SDOH findings.", len(normalized))
    return result


# --- Example execution with synthetic data ---

if __name__ == "__main__":
    # Synthetic social work assessment note.
    # This is completely fabricated. No real patient data.
    SAMPLE_NOTE = """
Social History:
Patient is a 62-year-old male, lives alone in a one-bedroom apartment.
Reports that his lease expires next month and has been unable to find
affordable alternatives in the area. States he has been skipping meals
3-4 times per week due to cost of medications taking priority over groceries.
No family in the immediate area. Spouse passed away 18 months ago.
Patient reports feeling isolated and has not attended church or social
activities since the death. Denies any safety concerns at home.
Previously received SNAP benefits but was discontinued after missing
recertification appointment due to lack of transportation.

Assessment and Plan:
1. Diabetes management: A1c 9.2%, up from 8.4% last visit. Suspect
   non-adherence related to food insecurity and financial constraints.
2. Refer to hospital food pantry program and assist with SNAP re-enrollment.
3. Social work to assess transportation options for medical appointments.
4. Consider referral to grief counseling and senior center for social support.

Family History:
Mother had diabetes. Father was homeless in his later years.
"""

    result = process_note_for_sdoh(
        patient_id="PAT-2026-00847",
        note_id="NOTE-SW-20260215-003",
        note_date="2026-02-15",
        note_text=SAMPLE_NOTE,
    )

    print(json.dumps(result, indent=2, default=str))
```

**Expected output (approximate, depending on classifier training):**

```json
{
  "patient_id": "PAT-2026-00847",
  "note_id": "NOTE-SW-20260215-003",
  "note_date": "2026-02-15",
  "extraction_timestamp": "2026-02-15T18:44:22Z",
  "skipped": false,
  "sentences_evaluated": 14,
  "sdoh_findings_count": 5,
  "findings": [
    {
      "domain": "housing_instability",
      "assertion": "at_risk",
      "confidence": 0.87,
      "source_text": "Reports that his lease expires next month and has been unable to find affordable alternatives in the area.",
      "icd10_codes": ["Z59.0", "Z59.1", "Z59.8"],
      "display": "Problems related to housing and economic circumstances"
    },
    {
      "domain": "food_insecurity",
      "assertion": "active_need",
      "confidence": 0.94,
      "source_text": "States he has been skipping meals 3-4 times per week due to cost of medications taking priority over groceries.",
      "icd10_codes": ["Z59.4", "Z59.48"],
      "display": "Lack of adequate food and safe drinking water"
    },
    {
      "domain": "social_isolation",
      "assertion": "active_need",
      "confidence": 0.81,
      "source_text": "Patient reports feeling isolated and has not attended church or social activities since the death.",
      "icd10_codes": ["Z60.2", "Z60.4"],
      "display": "Social isolation and inadequate social support"
    },
    {
      "domain": "transportation_barrier",
      "assertion": "active_need",
      "confidence": 0.79,
      "source_text": "Previously received SNAP benefits but was discontinued after missing recertification appointment due to lack of transportation.",
      "icd10_codes": ["Z59.82"],
      "display": "Transportation insecurity"
    },
    {
      "domain": "interpersonal_safety",
      "assertion": "absent",
      "confidence": 0.76,
      "source_text": "Denies any safety concerns at home.",
      "icd10_codes": ["Z63.0", "T74", "T76"],
      "display": "Interpersonal violence and safety concerns"
    }
  ]
}
```

Notice how the "Denies any safety concerns" sentence gets extracted with assertion "absent" because Comprehend Medical detected the negation. And "Father was homeless in his later years" from the family history section would ideally be filtered out (it's about a family member, not the patient). The section context from Step 2 helps downstream consumers decide how to weight findings from different sections.

---

## The Gap Between This and Production

This example works. Run it against a real clinical note (with a trained classifier endpoint) and it will return structured SDOH findings with standard codes. But there's a meaningful distance between "works in a script" and "runs at scale processing thousands of notes daily." Here's where that gap lives:

**Custom classifier training.** This code assumes a trained Comprehend custom classifier endpoint already exists. Training that classifier requires annotated data: at minimum 1,000 labeled sentences across SDOH domains. Use de-identified datasets (MIMIC, i2b2/n2c2 SDOH shared task data) for initial development. Your local documentation patterns will differ from academic medical center notes, so plan for a local annotation round with clinical staff.

**Error handling.** If Comprehend Medical or the custom classifier returns an error, this code logs and skips that sentence. A production system needs circuit breakers (stop calling a failing service), dead letter queues (don't lose notes that failed processing), and alerting (know when extraction is degraded).

**Retries and backoff.** The adaptive retry config handles basic throttling, but at high throughput (thousands of notes per hour), you'll hit Comprehend Medical's transactions-per-second limits. Production systems use SQS with visibility timeout and retry policies to handle sustained load gracefully.

**Input validation.** This code trusts its inputs. A production system validates note length (Comprehend Medical caps at 20,000 characters), handles empty or malformed notes gracefully, and rejects notes without required metadata (patient_id, note_id, note_date).

**Note chunking.** Comprehend Medical has a 20,000 character limit per API call. Many clinical notes (especially H&P or social work assessments) exceed this. Production code splits long notes at sentence boundaries, processes chunks independently, and merges results with proper offset tracking.

**Assertion classification depth.** The `determine_assertion()` function here is a handful of keyword heuristics. A production system would train a second classifier specifically for assertion status, or use temporal reasoning (past tense verbs, date references) to distinguish active from historical needs. The keyword approach misses subtle cases.

**Logging and observability.** The `logger.info()` calls here are placeholders. A real system uses structured JSON logging with consistent fields (patient_id, note_id, step, duration, error) and publishes CloudWatch metrics for extraction rate, SDOH finding rate, classifier confidence distributions, and per-domain recall estimates.

**IAM least-privilege.** The IAM role for this Lambda should have exactly: `comprehendmedical:DetectEntitiesV2` on all resources, `comprehend:ClassifyDocument` scoped to the specific endpoint ARN, `dynamodb:PutItem` scoped to the specific table, and `sqs:ReceiveMessage` + `sqs:DeleteMessage` scoped to the specific queue. Not `comprehend:*`. Not `dynamodb:*`.

**VPC configuration.** Clinical notes contain PHI. In production, this Lambda runs inside a VPC with private subnets and VPC endpoints for Comprehend Medical, Comprehend, DynamoDB, SQS, S3, and CloudWatch Logs. Traffic never traverses the public internet.

**Encryption.** This example relies on default encryption. Production uses KMS customer-managed keys for DynamoDB, SQS, and any S3 buckets holding notes or results. Key rotation should be enabled.

**DynamoDB data types.** This example already wraps confidence scores in `Decimal` (DynamoDB's float requirement). Any new numeric fields you add must also use `Decimal`. The `boto3` DynamoDB resource layer raises a `TypeError` on raw floats in `put_item` calls.

**Human review workflow.** Findings below the confidence threshold are dropped in this example. A production system routes low-confidence findings to a review queue where clinical staff can confirm or reject them. This provides both quality assurance and training data for classifier improvement.

**Feedback loop.** When care managers act on (or dismiss) SDOH findings, that signal should flow back to improve the classifier. "False positive: this wasn't actually food insecurity" is training data. Without this loop, the system never improves beyond its initial training.

**Testing.** There are no tests here. A production pipeline has: unit tests for `determine_assertion()` and `detect_sections()` with known inputs, integration tests against a real Comprehend Medical call with synthetic notes, and an evaluation suite that measures precision/recall against a gold-standard annotated set. Never use real patient notes in test fixtures.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 8.6](chapter08.06-sdoh-extraction.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
