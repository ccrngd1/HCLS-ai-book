# Recipe 8.5: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 8.5. It shows one way you could translate those concepts into working Python code using boto3 and Amazon Comprehend Medical. It is not production-ready. Think of it as a sketchpad: useful for understanding the shape of the solution, not something you'd deploy against real patient notes on Monday morning. A starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `comprehendmedical:DetectEntitiesV2`
- `comprehendmedical:InferICD10CM`
- `comprehendmedical:InferSNOMEDCT`
- `s3:GetObject`, `s3:PutObject`
- `dynamodb:PutItem`, `dynamodb:Query`

---

## Config and Constants

Before we get into logic, here are the configuration values and lookup tables that drive the pipeline. Section classification determines how extracted problems are interpreted downstream. A problem found under "Family History" should never end up on the patient's active problem list, no matter how confidently the NER model extracted it.

```python
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config
from boto3.dynamodb.conditions import Key, Attr

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log PHI field values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles burst throttling from Comprehend Medical.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# AWS clients
comprehend_medical = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# Table and bucket names. Replace with your actual resource names.
RESULTS_BUCKET = "clinical-nlp-results"
RECOMMENDATIONS_TABLE = "problem-list-recommendations"
PROBLEMS_TABLE = "patient-problems"

# Confidence threshold for accepting a problem extraction.
# Below this, we still extract but flag it for human review.
EXTRACTION_CONFIDENCE_THRESHOLD = 0.75

# Section header classifications.
# These determine the default assertion for problems found in each section.
# A problem in "ASSESSMENT" defaults to PRESENT.
# A problem in "FAMILY HISTORY" defaults to FAMILY_HISTORY.
ACTIVE_SECTION_HEADERS = [
    "assessment", "assessment and plan", "a/p", "active problems",
    "problem list", "diagnoses", "impression", "current problems",
    "hospital course", "hpi", "history of present illness"
]

PMH_SECTION_HEADERS = [
    "past medical history", "pmh", "medical history",
    "past history", "prior diagnoses", "significant history"
]

FAMILY_SECTION_HEADERS = [
    "family history", "fh", "family hx", "familial history"
]

RESOLVED_SECTION_HEADERS = [
    "resolved problems", "inactive problems", "past problems",
    "resolved", "inactive"
]

# Resolution markers: words/phrases that suggest a condition is no longer active.
# Used as a heuristic when section context alone is ambiguous.
RESOLUTION_MARKERS = [
    "resolved", "s/p", "status post", "history of", "h/o",
    "previous", "former", "prior", "no longer", "discontinued",
    "in remission", "cured"
]
```

---

## Step 1: Section Detection

*The pseudocode calls this `detect_sections(note_text)`. Clinical notes have internal structure even when they look like a wall of text. Identifying section boundaries gives us critical context for assertion classification downstream.*

```python
import re

def detect_sections(note_text: str) -> list[dict]:
    """
    Split a clinical note into sections based on header patterns.

    Clinical notes use various header conventions:
    - ALL CAPS followed by colon: "ASSESSMENT:"
    - Title case followed by colon: "Assessment and Plan:"
    - Wrapped in asterisks: "** Family History **"

    Each returned section includes its category (ACTIVE, PMH, FAMILY, etc.)
    and the text content under that header.
    """
    # Pattern matches common clinical note header formats.
    # Looks for lines that are mostly a label followed by a colon,
    # or all-caps lines that serve as section dividers.
    header_pattern = re.compile(
        r"^(?:"
        r"([A-Z][A-Za-z /&]+):[ ]*$"     # "Assessment and Plan:" on its own line
        r"|([A-Z][A-Z /&]{2,}):?"         # "ASSESSMENT:" or "ASSESSMENT" (all caps)
        r"|\*\*\s*(.+?)\s*\*\*"           # "** Family History **"
        r")",
        re.MULTILINE
    )

    sections = []
    last_end = 0
    last_category = "UNKNOWN"

    for match in header_pattern.finditer(note_text):
        # Save the text between the previous header and this one.
        if last_end > 0 or match.start() > 0:
            section_text = note_text[last_end:match.start()].strip()
            if section_text:
                sections.append({
                    "category": last_category,
                    "text": section_text,
                    "start_offset": last_end
                })

        # Determine the header text from whichever capture group matched.
        header_text = match.group(1) or match.group(2) or match.group(3)
        header_text = header_text.strip().lower()

        # Classify this header.
        last_category = classify_section_header(header_text)
        last_end = match.end()

    # Don't forget the final section after the last header.
    remaining = note_text[last_end:].strip()
    if remaining:
        sections.append({
            "category": last_category,
            "text": remaining,
            "start_offset": last_end
        })

    # If no headers were found at all, treat the entire note as UNKNOWN.
    if not sections:
        sections.append({
            "category": "UNKNOWN",
            "text": note_text.strip(),
            "start_offset": 0
        })

    return sections

def classify_section_header(header_lower: str) -> str:
    """
    Map a lowercase header string to a section category.
    The category determines default assertion status for problems found there.
    """
    if header_lower in ACTIVE_SECTION_HEADERS:
        return "ACTIVE"
    elif header_lower in PMH_SECTION_HEADERS:
        return "PMH"
    elif header_lower in FAMILY_SECTION_HEADERS:
        return "FAMILY"
    elif header_lower in RESOLVED_SECTION_HEADERS:
        return "RESOLVED"
    else:
        return "UNKNOWN"
```

---

## Step 2: Extract Clinical Problems

*The pseudocode calls this `extract_problems(sections)`. We send each relevant section to Amazon Comprehend Medical's DetectEntitiesV2 API and filter for MEDICAL_CONDITION entities. The API returns entities with traits (NEGATION, SYMPTOM, SIGN, DIAGNOSIS) that we'll use in the assertion step.*

```python
def extract_problems(sections: list[dict]) -> list[dict]:
    """
    Run NER on each relevant section to extract MEDICAL_CONDITION entities.

    We skip sections like allergies or medications that won't contain
    problem list entries. For each extracted condition, we carry forward
    the section category so assertion classification knows where it came from.
    """
    # We only process sections that might contain problem mentions.
    relevant_categories = {"ACTIVE", "PMH", "FAMILY", "RESOLVED", "UNKNOWN"}
    all_problems = []

    for section in sections:
        if section["category"] not in relevant_categories:
            continue

        # Comprehend Medical has a 20,000 character limit per request.
        # Most clinical note sections are well under this, but we truncate
        # just in case. In production, you'd chunk long sections.
        text = section["text"][:20000]

        if not text.strip():
            continue

        # Call DetectEntitiesV2. This returns all medical entity types:
        # MEDICAL_CONDITION, MEDICATION, ANATOMY, TEST_TREATMENT_PROCEDURE, etc.
        # We only care about MEDICAL_CONDITION for problem list extraction.
        response = comprehend_medical.detect_entities_v2(Text=text)

        for entity in response.get("Entities", []):
            if entity["Category"] != "MEDICAL_CONDITION":
                continue

            # Build our problem record with everything we need downstream.
            problem = {
                "text": entity["Text"],
                "confidence": entity["Score"],
                "begin_offset": entity["BeginOffset"] + section["start_offset"],
                "end_offset": entity["EndOffset"] + section["start_offset"],
                "section": section["category"],
                "traits": entity.get("Traits", []),
                "attributes": entity.get("Attributes", []),
                # entity_type helps distinguish DIAGNOSIS vs SIGN vs SYMPTOM
                "entity_type": next(
                    (t["Name"] for t in entity.get("Traits", [])
                     if t["Name"] in ("DIAGNOSIS", "SIGN", "SYMPTOM")),
                    "DIAGNOSIS"  # default if no type trait present
                )
            }
            all_problems.append(problem)

    logger.info("Extracted %d MEDICAL_CONDITION entities", len(all_problems))
    return all_problems
```

---

## Step 3: Classify Assertion Status

*The pseudocode calls this `classify_assertions(problems)`. This is the critical gate that prevents negated conditions, family history, and hypotheticals from polluting the active problem list. We combine two signals: NER-level traits (NEGATION, HYPOTHETICAL) and section-level context.*

```python
def classify_assertions(problems: list[dict]) -> list[dict]:
    """
    Determine assertion status for each extracted problem.

    Assertion status = is this problem actually active for this patient?
    Possible values: PRESENT, NEGATED, HISTORICAL, FAMILY_HISTORY,
    HYPOTHETICAL, RESOLVED.

    We use a two-layer approach:
    1. Section context sets the baseline (a problem in "Family History" is FAMILY_HISTORY)
    2. Entity-level traits can override (NEGATION trait overrides section context)
    """
    classified = []

    for problem in problems:
        # Layer 1: Section context provides the default assertion.
        assertion = _section_to_assertion(problem["section"])

        # Layer 2: Entity-level traits can override.
        for trait in problem["traits"]:
            trait_name = trait["Name"]
            trait_score = trait["Score"]

            # Only trust high-confidence traits for overrides.
            if trait_score < 0.80:
                continue

            if trait_name == "NEGATION":
                # "No diabetes" in the Assessment section means NOT active.
                # Negation overrides section context.
                assertion = "NEGATED"
                break  # negation is definitive

            if trait_name == "HYPOTHETICAL":
                # "If she develops CKD" is not an active problem.
                assertion = "HYPOTHETICAL"

        # Layer 3: Resolution marker heuristic for ambiguous cases.
        # If the problem text itself contains resolution language and we
        # haven't already classified it as negated/hypothetical, downgrade.
        if assertion == "PRESENT":
            if _has_resolution_markers(problem["text"]):
                assertion = "HISTORICAL"

        problem_with_assertion = {**problem, "assertion": assertion}
        classified.append(problem_with_assertion)

    # Log assertion distribution for monitoring.
    assertion_counts = {}
    for p in classified:
        assertion_counts[p["assertion"]] = assertion_counts.get(p["assertion"], 0) + 1
    logger.info("Assertion distribution: %s", assertion_counts)

    return classified

def _section_to_assertion(section_category: str) -> str:
    """Map section category to default assertion status."""
    mapping = {
        "ACTIVE": "PRESENT",
        "PMH": "HISTORICAL",
        "FAMILY": "FAMILY_HISTORY",
        "RESOLVED": "RESOLVED",
        "UNKNOWN": "PRESENT"  # conservative default: assume active
    }
    return mapping.get(section_category, "PRESENT")

def _has_resolution_markers(text: str) -> bool:
    """Check if the problem text contains language suggesting resolution."""
    # Simple substring matching. Production systems use more sophisticated
    # context-aware resolution detection (e.g., checking whether the marker
    # modifies the condition or describes its current status).
    text_lower = text.lower()
    return any(marker in text_lower for marker in RESOLUTION_MARKERS)
```

---

## Step 4: Normalize to Standard Codes

*The pseudocode calls this `normalize_problems(classified_problems)`. Active and historical problems need SNOMED CT and ICD-10-CM codes for downstream use. We call InferICD10CM and InferSNOMEDCT and keep the top 3 candidates from each.*

```python
def normalize_problems(classified_problems: list[dict]) -> list[dict]:
    """
    Map extracted problem text to SNOMED CT and ICD-10-CM codes.

    We only normalize problems that might go on the problem list.
    Negated and hypothetical problems don't need codes (they won't be added
    to any structured list), but we still include them in the output for
    completeness and auditability.
    """
    # Only these assertion types get normalized.
    normalize_assertions = {"PRESENT", "HISTORICAL", "FAMILY_HISTORY"}
    normalized = []

    for problem in classified_problems:
        if problem["assertion"] not in normalize_assertions:
            # Still include in output, just without codes.
            normalized.append({**problem, "icd10": None, "snomed": None})
            continue

        # The text we send for normalization. Comprehend Medical's inference
        # APIs work best with the exact extracted span plus a bit of context,
        # but even just the entity text produces reasonable results.
        text_for_inference = problem["text"]

        # Call ICD-10-CM inference.
        icd10_codes = _infer_icd10(text_for_inference)

        # Call SNOMED CT inference.
        snomed_codes = _infer_snomed(text_for_inference)

        normalized.append({
            **problem,
            "icd10": icd10_codes,
            "snomed": snomed_codes
        })

    return normalized

def _infer_icd10(text: str) -> list[dict]:
    """
    Call InferICD10CM and return top 3 candidates.

    The API returns entities with ICD10CMConcepts ranked by confidence.
    We take the top 3 because the top-1 isn't always correct, especially
    for abbreviations or partial mentions.
    """
    response = comprehend_medical.infer_icd10_cm(Text=text)

    # InferICD10CM returns entities, each with a list of ICD10CMConcepts.
    # We want the concepts from the first (most relevant) entity.
    entities = response.get("Entities", [])
    if not entities:
        return []

    concepts = entities[0].get("ICD10CMConcepts", [])
    # Return top 3, with the fields downstream needs.
    return [
        {
            "Code": c["Code"],
            "Description": c["Description"],
            "Score": round(c["Score"], 3)
        }
        for c in concepts[:3]
    ]

def _infer_snomed(text: str) -> list[dict]:
    """
    Call InferSNOMEDCT and return top 3 candidates.

    Same pattern as ICD-10 inference. SNOMED codes are preferred for
    clinical problem lists because SNOMED has richer hierarchy and
    more clinical granularity than ICD-10.
    """
    response = comprehend_medical.infer_snomedct(Text=text)

    entities = response.get("Entities", [])
    if not entities:
        return []

    concepts = entities[0].get("SNOMEDCTConcepts", [])
    return [
        {
            "Code": c["Code"],
            "Description": c["Description"],
            "Score": round(c["Score"], 3)
        }
        for c in concepts[:3]
    ]
```

---

## Step 5: Reconcile Against Existing Problem List

*The pseudocode calls this `reconcile_problems(patient_id, extracted_problems, note_id)`. We compare active extracted problems against the patient's current problem list and produce recommendations: problems to add, problems to resolve, and specificity upgrades.*

```python
def reconcile_problems(
    patient_id: str,
    extracted_problems: list[dict],
    note_id: str
) -> list[dict]:
    """
    Compare extracted active problems against the existing problem list.

    This produces RECOMMENDATIONS, not changes. Problem list maintenance
    is a clinical act that requires physician review. We're surfacing
    candidates, not making decisions.
    """
    # Fetch the patient's current active problem list from DynamoDB.
    current_list = _get_current_problem_list(patient_id)
    current_codes = {p["snomed_code"] for p in current_list}

    # Separate extracted problems by assertion type.
    active_extracted = [
        p for p in extracted_problems
        if p["assertion"] == "PRESENT" and p["snomed"]
    ]
    resolved_signals = [
        p for p in extracted_problems
        if p["assertion"] in ("HISTORICAL", "RESOLVED") and p["snomed"]
    ]

    recommendations = []

    # 1. Find problems active in notes but missing from the problem list.
    for problem in active_extracted:
        top_snomed = problem["snomed"][0]["Code"]
        if top_snomed not in current_codes:
            recommendations.append({
                "type": "ADD_CANDIDATE",
                "problem_text": problem["text"],
                "snomed": problem["snomed"][0],
                "icd10": problem["icd10"][0] if problem["icd10"] else None,
                "confidence": problem["confidence"],
                "source_note": note_id,
                "rationale": (
                    f"Mentioned as active in {problem['section']} section "
                    f"but not on current problem list"
                )
            })

    # 2. Find problems on the list that notes suggest are resolved.
    resolved_codes = {
        p["snomed"][0]["Code"] for p in resolved_signals
    }
    for existing in current_list:
        if existing["snomed_code"] in resolved_codes:
            recommendations.append({
                "type": "RESOLVE_CANDIDATE",
                "problem_text": existing["problem_text"],
                "snomed": {"Code": existing["snomed_code"]},
                "source_note": note_id,
                "rationale": "Mentioned with resolution markers in recent note"
            })

    # Note: The main recipe's pseudocode also includes specificity upgrade detection
    # (checking SNOMED hierarchy relationships with is_child_of). That requires a
    # SNOMED ontology service or lookup table, which is beyond the scope of this example.

    logger.info(
        "Reconciliation: %d recommendations for patient %s",
        len(recommendations), patient_id
    )
    return recommendations

def _get_current_problem_list(patient_id: str) -> list[dict]:
    """
    Query DynamoDB for the patient's active problems.

    In production, you'd have a properly designed table with patient_id
    as partition key and problem entries as items. This is a simplified
    query pattern.
    """
    table = dynamodb.Table(PROBLEMS_TABLE)

    response = table.query(
        KeyConditionExpression=Key("patient_id").eq(patient_id),
        FilterExpression=Attr("status").eq("ACTIVE")
    )

    return response.get("Items", [])
```

---

## Step 6: Store Results

*The pseudocode calls this `store_results(patient_id, extracted_problems, recommendations, note_id)`. We write full extraction results to S3 for audit and reprocessing, and write actionable recommendations to DynamoDB for clinician review workflows.*

```python
import uuid

def store_results(
    patient_id: str,
    extracted_problems: list[dict],
    recommendations: list[dict],
    note_id: str
) -> dict:
    """
    Persist extraction results and recommendations.

    Two destinations:
    - S3: Full extraction record for audit trail and reprocessing
    - DynamoDB: Actionable recommendations for clinician review queue
    """
    timestamp = datetime.datetime.now(timezone.utc).isoformat()

    # Build the full results record.
    results_record = {
        "patient_id": patient_id,
        "note_id": note_id,
        "extraction_timestamp": timestamp,
        "problems_extracted": _serialize_problems(extracted_problems),
        "recommendations": recommendations
    }

    # Write to S3 for audit trail.
    s3_key = f"results/{patient_id}/{note_id}.json"
    s3_client.put_object(
        Bucket=RESULTS_BUCKET,
        Key=s3_key,
        Body=json.dumps(results_record, default=str),
        ContentType="application/json",
        ServerSideEncryption="aws:kms"
        # In production, also specify SSEKMSKeyId with your CMK ARN.
    )
    logger.info("Stored extraction results to s3://%s/%s", RESULTS_BUCKET, s3_key)

    # Write recommendations to DynamoDB for clinician review.
    if recommendations:
        rec_table = dynamodb.Table(RECOMMENDATIONS_TABLE)
        for rec in recommendations:
            rec_table.put_item(Item={
                "patient_id": patient_id,
                "recommendation_id": str(uuid.uuid4()),
                "type": rec["type"],
                "problem_text": rec["problem_text"],
                "snomed_code": rec["snomed"]["Code"],
                "icd10_code": rec.get("icd10", {}).get("Code", "N/A") if rec.get("icd10") else "N/A",
                "confidence": Decimal(str(round(rec.get("confidence", 0.0), 3))),
                "source_note": note_id,
                "rationale": rec["rationale"],
                "status": "PENDING_REVIEW",
                "created_at": timestamp
            })
        logger.info("Stored %d recommendations to DynamoDB", len(recommendations))

    return results_record

def _serialize_problems(problems: list[dict]) -> list[dict]:
    """
    Prepare problem records for JSON serialization.

    Strips internal fields (traits, attributes) that are useful during
    processing but noisy in the final output. Keeps what a reviewer needs.
    """
    serialized = []
    for p in problems:
        serialized.append({
            "text": p["text"],
            "assertion": p["assertion"],
            "section": p["section"],
            "confidence": round(p["confidence"], 3),
            "snomed": p.get("snomed"),
            "icd10": p.get("icd10")
        })
    return serialized
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. In a Lambda deployment, your handler would parse the incoming event (S3 notification or API Gateway request), extract the patient ID and note text, and call this function.

```python
def process_note_for_problems(
    patient_id: str,
    note_text: str,
    note_id: str
) -> dict:
    """
    Run the full problem list extraction pipeline on a single clinical note.

    This is the main entry point. The pipeline:
    1. Detects sections in the note
    2. Extracts MEDICAL_CONDITION entities from relevant sections
    3. Classifies assertion status (active, negated, historical, etc.)
    4. Normalizes active problems to SNOMED CT and ICD-10 codes
    5. Reconciles against the existing problem list
    6. Stores results and generates recommendations

    Returns the full extraction record with recommendations.
    """
    logger.info("Processing note %s for patient %s", note_id, patient_id)

    # Step 1: Split note into sections.
    logger.info("Step 1: Detecting sections")
    sections = detect_sections(note_text)
    logger.info("  Found %d sections", len(sections))

    # Step 2: Extract clinical problems from each relevant section.
    logger.info("Step 2: Extracting clinical problems")
    raw_problems = extract_problems(sections)
    logger.info("  Extracted %d problem mentions", len(raw_problems))

    # Step 3: Classify assertion status for each problem.
    logger.info("Step 3: Classifying assertions")
    classified = classify_assertions(raw_problems)

    # Step 4: Normalize active/historical problems to standard codes.
    logger.info("Step 4: Normalizing to SNOMED CT and ICD-10")
    normalized = normalize_problems(classified)

    # Step 5: Reconcile against existing problem list.
    logger.info("Step 5: Reconciling against current problem list")
    recommendations = reconcile_problems(patient_id, normalized, note_id)

    # Step 6: Store everything.
    logger.info("Step 6: Storing results")
    result = store_results(patient_id, normalized, recommendations, note_id)

    logger.info(
        "Done. Extracted %d problems, %d active, %d recommendations.",
        len(normalized),
        sum(1 for p in normalized if p["assertion"] == "PRESENT"),
        len(recommendations)
    )
    return result

# --- Example usage with synthetic data ---

if __name__ == "__main__":
    # Synthetic clinical note. This mimics a typical progress note with
    # multiple sections and various assertion types.
    SAMPLE_NOTE = """
HISTORY OF PRESENT ILLNESS:
62-year-old male with type 2 diabetes and hypertension presents for routine
follow-up. Reports good medication adherence. Denies chest pain or shortness
of breath. Blood glucose has been well-controlled per home monitoring.

PAST MEDICAL HISTORY:
Pneumonia (2023, resolved)
Appendectomy (2015)
History of smoking, quit 2018

FAMILY HISTORY:
Mother with breast cancer, diagnosed age 58
Father with coronary artery disease

ASSESSMENT AND PLAN:
1. Type 2 diabetes - well controlled, A1c 6.8%. Continue metformin.
2. Hypertension - at goal on lisinopril 20mg daily.
3. Chronic kidney disease stage 3 - stable, Cr 1.6. Continue monitoring.
4. Depression - started on sertraline 3 months ago, reports improvement.
   PHQ-9 score improved from 14 to 6. Continue current dose.
5. Obesity - BMI 32. Discussed dietary modifications.
"""

    result = process_note_for_problems(
        patient_id="PAT-2847103",
        note_text=SAMPLE_NOTE,
        note_id="NOTE-20260301-0482"
    )

    print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

This example works. Point it at a real Comprehend Medical endpoint with a clinical note and it will extract problems, classify assertions, and produce recommendations. But there's a meaningful distance between "works in a script" and "runs reliably at scale against real patient data." Here's where that gap lives:

**Error handling.** Every Comprehend Medical API call can fail: throttling, service errors, malformed input. This code will crash on the first error. A production system wraps each API call in try/except blocks, distinguishes retryable errors (throttling, transient failures) from permanent ones (invalid text encoding), and handles partial failures gracefully (if SNOMED normalization fails but ICD-10 succeeds, you keep the ICD-10 result).

**Retries and backoff.** The `adaptive` retry mode handles basic throttling, but Comprehend Medical's rate limits are per-region, and a batch job processing thousands of notes will hit them. Production systems implement explicit rate limiting (token bucket or leaky bucket) on top of boto3's built-in retries, with exponential backoff and jitter for burst tolerance.

**Input validation.** This code trusts that the note text is valid UTF-8 under 20,000 characters. Real clinical notes come from HL7 feeds, EHR extracts, and FHIR bundles in various encodings. Production code validates encoding, strips control characters, checks length against Comprehend Medical's limits, and handles the case where a note is too long by intelligently chunking at section boundaries rather than cutting mid-sentence.

**Structured logging.** The `logger.info` calls here are a starting point. Production needs structured JSON logging with consistent fields: patient_id, note_id, step, duration_ms, entity_count, error details. This is what powers your monitoring dashboards and what your on-call engineer queries at 2am when extraction accuracy drops.

**IAM least-privilege.** The IAM role for this Lambda should have exactly: `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferICD10CM`, `comprehendmedical:InferSNOMEDCT` (all resources), `s3:GetObject` and `s3:PutObject` scoped to specific bucket prefixes, `dynamodb:PutItem` and `dynamodb:Query` scoped to specific tables. Not `comprehendmedical:*`. Not `s3:*`.

**VPC and VPC endpoints.** Clinical notes contain PHI. In production, this Lambda runs in a VPC with private subnets and VPC endpoints for S3, DynamoDB, and CloudWatch Logs. Comprehend Medical does not have a VPC endpoint, so traffic to its public endpoint routes through a NAT Gateway (encrypted via TLS in transit). Evaluate whether your compliance posture permits this, or run Lambda outside VPC with resource-based policies on S3 and DynamoDB.

**KMS customer-managed keys.** This example uses `ServerSideEncryption="aws:kms"` but doesn't specify a key ID, which means it uses the AWS-managed key. Production uses a CMK you control, with key rotation enabled, and CloudTrail logging every key usage event.

**DynamoDB Decimal handling.** DynamoDB doesn't accept Python floats. This example already wraps confidence scores in `Decimal(str(...))`. Any new numeric fields must follow the same pattern. If you forget, `put_item` raises a `TypeError` that's not immediately obvious in its error message.

**Section detection robustness.** The regex-based section detection here works for cleanly formatted notes. Real clinical notes are messy: inconsistent casing, missing colons, headers embedded mid-paragraph, numbered lists that look like headers. Production systems use ML-based section detectors trained on diverse note formats, or at minimum a much more comprehensive pattern library.

**Comprehend Medical API limits.** DetectEntitiesV2 accepts up to 20,000 UTF-8 characters per call. Discharge summaries and operative notes routinely exceed this. Production systems chunk long notes at section boundaries and reassemble results with corrected offsets. The chunking strategy matters: splitting mid-sentence can break negation scope.

**Testing.** There are no tests here. Production needs unit tests for section detection (with diverse note formats), integration tests against Comprehend Medical with known test notes, assertion classification tests with manually annotated examples covering negation edge cases, and end-to-end tests that verify the full pipeline produces expected recommendations. Use synthetic notes only. Never put real patient text in your test fixtures.

**Reconciliation complexity.** The reconciliation logic here does simple code matching. Real reconciliation needs SNOMED hierarchy traversal (is "Type 2 diabetes mellitus" a parent of "Type 2 diabetes mellitus with diabetic nephropathy"?), fuzzy concept matching for cases where the extracted text doesn't normalize perfectly, and deduplication logic for when the same problem appears in multiple notes with slightly different wording.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 8.5](chapter08.05-problem-list-extraction) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
