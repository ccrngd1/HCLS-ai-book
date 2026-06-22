# Recipe 8.10: Python Implementation Example

> **Heads up:** This is a deliberately simplified, illustrative implementation of the phenotype extraction pipeline from Recipe 8.10. It shows one way to translate the pseudocode concepts into working Python using boto3 and Amazon Comprehend Medical. It is not production-ready. Phenotype extraction for real research requires extensive validation, IRB-approved data access, and months of iteration on criteria definitions. Think of this as the sketch on the whiteboard, not the system you'd use to build a research cohort next week.

---

## Setup

You'll need the AWS SDK for Python and a few standard libraries:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `comprehend:DetectEntitiesV2`
- `comprehend:InferRxNorm`
- `comprehend:InferICD10CM`
- `s3:GetObject`, `s3:PutObject`
- `dynamodb:PutItem`, `dynamodb:Query`

---

## Config and Constants

Before the processing logic, here are the configuration structures that define the phenotype and drive the extraction. These are really the heart of the system: change these, and the pipeline looks for completely different things.

```python
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, use JSON output for CloudWatch Logs Insights.
# PHI Safety: Never log raw clinical text, patient identifiers, or extracted values.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles Comprehend Medical throttling under burst load.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# AWS clients
comprehend_medical = boto3.client("comprehend-medical", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
s3 = boto3.client("s3", config=BOTO3_RETRY_CONFIG)

# Table and bucket names. Replace with your actual resources.
EVIDENCE_TABLE_NAME = "phenotype-evidence"
RESULTS_BUCKET = "phenotype-results"

# Minimum confidence for an extracted entity to count as evidence.
# Below this, the extraction is too uncertain to use in research classification.
# 0.80 is conservative. Some teams use 0.70 for recall-focused phenotypes.
CONFIDENCE_THRESHOLD = 0.80
```

```python
# The phenotype definition. This is the computable version of the research
# protocol's inclusion criteria. In a real system, this would be loaded from
# a versioned JSON file in S3, not hardcoded. But for illustration, here it is.
#
# This defines "Treatment-Resistant Depression with Inflammatory Markers":
#   C1: Major Depressive Disorder diagnosis
#   C2: Failed at least 2 adequate antidepressant trials
#   C3: Elevated inflammatory biomarkers

PHENOTYPE_DEFINITION = {
    "phenotype_id": "treatment_resistant_depression_v2",
    "phenotype_name": "Treatment-Resistant Depression with Inflammatory Markers",
    "version": "2.1",
    "criteria": [
        {
            "criterion_id": "C1_MDD_DIAGNOSIS",
            "description": "Major Depressive Disorder diagnosis",
            "target_categories": ["MEDICAL_CONDITION"],
            "target_terms": [
                "major depressive disorder", "major depression", "mdd",
                "recurrent depression", "severe depression",
            ],
            "required_assertion": "POSITIVE",
            "exclude_sections": ["FAMILY_HISTORY"],
            "min_evidence_count": 2,
        },
        {
            "criterion_id": "C2_TREATMENT_FAILURE",
            "description": "Failed at least 2 adequate antidepressant trials",
            "target_categories": ["MEDICATION"],
            "target_terms": [
                # Antidepressant names we care about
                "sertraline", "fluoxetine", "paroxetine", "citalopram",
                "escitalopram", "venlafaxine", "duloxetine", "desvenlafaxine",
                "bupropion", "mirtazapine", "amitriptyline", "nortriptyline",
                "imipramine", "phenelzine", "tranylcypromine",
                # Brand names
                "zoloft", "prozac", "paxil", "celexa", "lexapro",
                "effexor", "cymbalta", "pristiq", "wellbutrin", "remeron",
            ],
            "failure_indicators": [
                "failed", "not respond", "non-response", "inadequate response",
                "ineffective", "not helpful", "did not work", "no benefit",
                "discontinued due to lack of efficacy", "switched from",
                "tried without benefit", "no improvement",
            ],
            "required_assertion": "POSITIVE",
            "exclude_sections": ["FAMILY_HISTORY"],
            "min_distinct_medications": 2,
        },
        {
            "criterion_id": "C3_INFLAMMATORY_MARKERS",
            "description": "Elevated inflammatory biomarkers",
            "target_categories": ["TEST_TREATMENT_PROCEDURE"],
            "target_terms": [
                "crp", "c-reactive protein", "hs-crp", "high-sensitivity crp",
                "il-6", "interleukin-6", "esr", "sed rate",
                "erythrocyte sedimentation rate",
            ],
            "value_thresholds": {
                "crp": 3.0,
                "c-reactive protein": 3.0,
                "hs-crp": 3.0,
                "high-sensitivity crp": 3.0,
                "il-6": 7.0,
                "interleukin-6": 7.0,
                "esr": 20.0,
                "sed rate": 20.0,
                "erythrocyte sedimentation rate": 20.0,
            },
            "required_assertion": "POSITIVE",
            "exclude_sections": [],
            "min_evidence_count": 1,
        },
    ],
    "classification_logic": "ALL_CRITERIA_MET",
}
```

```python
# Synthetic clinical notes for demonstration.
# In a real system, these come from S3 (de-identified EHR exports).
# These are entirely fictional patients with fictional clinical narratives.

SYNTHETIC_NOTES = [
    {
        "note_id": "note-2024-03-15-psych",
        "note_date": "2024-03-15",
        "note_type": "Psychiatry Consult",
        "text": (
            "Patient is a 42-year-old female with a history of major depressive "
            "disorder, recurrent, severe. She has been struggling with persistent "
            "depressive symptoms for the past 3 years despite multiple medication "
            "trials. She initially tried sertraline titrated to 200mg daily for "
            "12 weeks without adequate response. Subsequently switched to "
            "venlafaxine extended-release, titrated to 225mg daily for 10 weeks, "
            "also without significant improvement in PHQ-9 scores. Current PHQ-9 "
            "remains 18, indicating moderately severe depression. No suicidal "
            "ideation. Patient denies any family history of bipolar disorder. "
            "Assessment: Treatment-resistant major depressive disorder. Plan: "
            "Consider augmentation strategy with aripiprazole or lithium."
        ),
    },
    {
        "note_id": "note-2024-06-22-pcp",
        "note_date": "2024-06-22",
        "note_type": "Primary Care Visit",
        "text": (
            "Follow-up visit. Patient continues to endorse low mood, anhedonia, "
            "and poor sleep despite trials of two antidepressants (sertraline and "
            "Effexor) at therapeutic doses. She was recently started on bupropion "
            "300mg daily as augmentation by her psychiatrist. Labs from last month "
            "show elevated CRP at 4.8 mg/L (reference range less than 3.0 mg/L). "
            "BMI 28. No acute infections to explain the elevation. Patient has no "
            "history of autoimmune disease. Repeat hs-CRP ordered to confirm. "
            "Assessment: MDD with inadequate response to first-line agents. "
            "Incidental finding of systemic inflammation. Will monitor."
        ),
    },
    {
        "note_id": "note-2024-09-10-lab",
        "note_date": "2024-09-10",
        "note_type": "Lab Results Note",
        "text": (
            "Lab results reviewed. hs-CRP: 5.1 mg/L (elevated, reference less "
            "than 3.0). CBC within normal limits. TSH 2.1 (normal). Vitamin D "
            "slightly low at 22 ng/mL. IL-6 not ordered this visit. The "
            "persistent CRP elevation in the absence of infection or autoimmune "
            "disease suggests chronic low-grade inflammation. Discussed with "
            "psychiatry team regarding potential relevance to treatment-resistant "
            "depression phenotype."
        ),
    },
]
```

---

## Step 1: Extract Entities from a Clinical Note

*The pseudocode calls this `process_note`. We send each note through Comprehend Medical's DetectEntitiesV2 API to get medical entities with their assertions, attributes, and confidence scores.*

```python
def extract_entities_from_note(note: dict) -> dict:
    """
    Send a single clinical note through Comprehend Medical and return
    structured entity extractions.

    Comprehend Medical returns entities in several categories:
    - MEDICAL_CONDITION: diagnoses, symptoms, signs
    - MEDICATION: drug names with dose/frequency/route attributes
    - TEST_TREATMENT_PROCEDURE: labs, tests, procedures
    - ANATOMY: body parts, organ systems
    - TIME_EXPRESSION: temporal references

    Each entity includes Traits (like NEGATION, DIAGNOSIS) and linked
    Attributes (like DOSAGE, DURATION for medications).

    Args:
        note: Dict with keys "note_id", "note_date", "text"

    Returns:
        Dict with note metadata and a list of processed entities.
    """
    note_text = note["text"]

    # Comprehend Medical has a 20,000 character limit per call.
    # For notes exceeding this, split at sentence boundaries before 18,000 chars,
    # process each chunk independently, then merge and deduplicate results.
    # Most clinical notes are well under the limit, so chunking rarely fires.
    chunks = _chunk_note_text(note_text, max_chars=18000)

    all_entities = []
    all_rx_lookup = {}

    for chunk_text, chunk_offset in chunks:
        # Call DetectEntitiesV2 on this chunk.
        response = comprehend_medical.detect_entities_v2(Text=chunk_text)

        # Also call InferRxNorm for normalized medication codes.
        rx_response = comprehend_medical.infer_rx_norm(Text=chunk_text)

        # Process entities and adjust offsets back to original document coordinates.
        for entity in response.get("Entities", []):
            assertion = "POSITIVE"
            traits = [t["Name"] for t in entity.get("Traits", [])]
            if "NEGATION" in traits:
                assertion = "NEGATIVE"

            attributes = []
            for attr in entity.get("Attributes", []):
                attributes.append({
                    "type": attr["Type"],
                    "text": attr["Text"],
                    "score": attr["Score"],
                })

            all_entities.append({
                "text": entity["Text"],
                "category": entity["Category"],
                "type": entity["Type"],
                "assertion": assertion,
                "confidence": entity["Score"],
                "traits": traits,
                "attributes": attributes,
                "begin_offset": entity["BeginOffset"] + chunk_offset,
                "end_offset": entity["EndOffset"] + chunk_offset,
            })

        # Build medication normalization lookup from InferRxNorm results.
        for rx_entity in rx_response.get("Entities", []):
            if rx_entity.get("RxNormConcepts"):
                top_concept = rx_entity["RxNormConcepts"][0]
                all_rx_lookup[rx_entity["Text"].lower()] = {
                    "code": top_concept["Code"],
                    "description": top_concept["Description"],
                    "score": top_concept["Score"],
                }

    return {
        "note_id": note["note_id"],
        "note_date": note["note_date"],
        "entities": all_entities,
        "rx_normalization": all_rx_lookup,
        "entity_count": len(all_entities),
    }


def _chunk_note_text(text: str, max_chars: int = 18000) -> list[tuple[str, int]]:
    """
    Split text into chunks that fit within Comprehend Medical's 20K limit.
    Splits at the last sentence-ending punctuation before max_chars.
    Returns list of (chunk_text, start_offset) tuples.

    Most notes are under 18K and return as a single chunk with offset 0.
    """
    if len(text) <= max_chars:
        return [(text, 0)]

    chunks = []
    start = 0
    while start < len(text):
        end = start + max_chars
        if end >= len(text):
            chunks.append((text[start:], start))
            break
        # Find last sentence boundary before the limit
        boundary = text.rfind(". ", start, end)
        if boundary == -1 or boundary <= start:
            # No sentence boundary found; fall back to whitespace
            boundary = text.rfind(" ", start, end)
        if boundary == -1 or boundary <= start:
            boundary = end  # Hard cut as last resort
        else:
            boundary += 1  # Include the period/space

        chunks.append((text[start:boundary], start))
        start = boundary

    return chunks
```

---

## Step 2: Evaluate Note Against Phenotype Criteria

*The pseudocode calls this `evaluate_against_criteria`. For each criterion in our phenotype definition, we check whether this note's entities provide supporting evidence.*

```python
def normalize_medication_name(text: str, rx_lookup: dict) -> str:
    """
    Normalize a medication mention to its generic name using RxNorm.
    Falls back to lowercase text if no normalization is available.

    This is critical for criterion C2: "sertraline" and "Zoloft" must be
    recognized as the same medication, not counted as two distinct failures.
    """
    lower_text = text.lower().strip()
    if lower_text in rx_lookup:
        # Use the RxNorm normalized description (always generic name)
        return rx_lookup[lower_text]["description"].lower()
    return lower_text

def text_matches_terms(entity_text: str, target_terms: list) -> bool:
    """
    Check if an entity's text matches any of the target terms.
    Uses case-insensitive substring matching.

    This is deliberately permissive. In production you'd add fuzzy matching
    or embedding-based similarity for terms that vary in spelling.
    """
    lower_text = entity_text.lower().strip()
    for term in target_terms:
        if term in lower_text or lower_text in term:
            return True
    return False

def check_failure_context(entity: dict, note_text: str, failure_indicators: list) -> bool:
    """
    Check whether a medication mention appears in a context indicating
    treatment failure. We look at the surrounding text for failure language.

    This is a simplified heuristic. A production system would use a trained
    classifier for treatment outcome assertions, not substring matching.
    But this demonstrates the concept.
    """
    # Look at a window around the medication mention for failure language.
    start = max(0, entity["begin_offset"] - 200)
    end = min(len(note_text), entity["end_offset"] + 200)
    context_window = note_text[start:end].lower()

    for indicator in failure_indicators:
        if indicator in context_window:
            return True
    return False

def extract_numeric_value(entity: dict) -> float | None:
    """
    Try to extract a numeric value from a test/lab entity's attributes.
    Comprehend Medical sometimes returns test values as linked attributes.
    If not available from attributes, try to parse from nearby text.
    """
    for attr in entity.get("attributes", []):
        if attr["type"] == "TEST_VALUE":
            # Try to parse the numeric part from the value text
            value_text = attr["text"].strip()
            # Remove common units and comparison operators
            for remove in ["mg/l", "pg/ml", "mm/hr", "mg/dl", "<", ">", "="]:
                value_text = value_text.lower().replace(remove, "").strip()
            try:
                return float(value_text)
            except ValueError:
                continue
    return None

def evaluate_note_against_criteria(
    extraction_result: dict,
    phenotype_def: dict,
    note_text: str,
) -> list:
    """
    Check which phenotype criteria this note provides evidence for.

    For each criterion, we filter the extracted entities to those that:
    1. Match the target category (MEDICAL_CONDITION, MEDICATION, etc.)
    2. Match the target terms (condition names, drug names, lab names)
    3. Have the required assertion (POSITIVE, not negated)
    4. Meet the confidence threshold
    5. Aren't from an excluded section

    Returns a list of evidence items, each linking an entity to a criterion.
    """
    evidence_items = []
    entities = extraction_result["entities"]
    rx_lookup = extraction_result["rx_normalization"]

    for criterion in phenotype_def["criteria"]:
        criterion_id = criterion["criterion_id"]
        target_categories = criterion["target_categories"]
        target_terms = criterion["target_terms"]
        required_assertion = criterion["required_assertion"]

        for entity in entities:
            # Category filter
            if entity["category"] not in target_categories:
                continue

            # Assertion filter: skip negated mentions when we need positive
            if required_assertion == "POSITIVE" and entity["assertion"] != "POSITIVE":
                continue

            # Confidence filter
            if entity["confidence"] < CONFIDENCE_THRESHOLD:
                continue

            # Term matching
            if not text_matches_terms(entity["text"], target_terms):
                continue

            # Criterion-specific logic
            evidence_item = {
                "criterion_id": criterion_id,
                "note_id": extraction_result["note_id"],
                "note_date": extraction_result["note_date"],
                "entity_text": entity["text"],
                "assertion": entity["assertion"],
                "confidence": entity["confidence"],
                "evidence_type": "NLP_EXTRACTION",
            }

            # For treatment failure criterion: check failure context
            if criterion_id == "C2_TREATMENT_FAILURE":
                failure_indicators = criterion.get("failure_indicators", [])
                if not check_failure_context(entity, note_text, failure_indicators):
                    continue  # Medication mentioned but no failure context
                # Normalize the medication name for deduplication
                evidence_item["normalized_medication"] = normalize_medication_name(
                    entity["text"], rx_lookup
                )

            # For inflammatory markers: check if value exceeds threshold
            if criterion_id == "C3_INFLAMMATORY_MARKERS":
                numeric_val = extract_numeric_value(entity)
                thresholds = criterion.get("value_thresholds", {})
                entity_lower = entity["text"].lower().strip()
                if entity_lower in thresholds and numeric_val is not None:
                    if numeric_val < thresholds[entity_lower]:
                        continue  # Value below threshold, not evidence
                    evidence_item["numeric_value"] = numeric_val
                    evidence_item["threshold"] = thresholds[entity_lower]

            evidence_items.append(evidence_item)

    return evidence_items
```

---

## Step 3: Aggregate Evidence Across All Notes

*The pseudocode calls this `aggregate_patient_evidence`. After processing all notes, we combine per-note evidence into a patient-level summary for each criterion.*

```python
def aggregate_evidence(all_evidence: list, phenotype_def: dict) -> dict:
    """
    Combine evidence from all notes into per-criterion summaries.

    This is where the longitudinal view comes together. A single note might
    mention one failed medication. Another note mentions a second. Only by
    aggregating across the full record do we see that the patient meets the
    "2 distinct medication failures" threshold.

    Args:
        all_evidence: Flat list of evidence items from all notes.
        phenotype_def: The phenotype definition with threshold requirements.

    Returns:
        Dict mapping criterion_id to an aggregation result with:
        - met: bool (does evidence meet the threshold?)
        - confidence: float (average confidence of supporting evidence)
        - evidence_count: int
        - supporting_notes: list of note_ids
        - details: criterion-specific details (e.g., distinct medications)
    """
    # Group evidence by criterion
    by_criterion = {}
    for item in all_evidence:
        cid = item["criterion_id"]
        if cid not in by_criterion:
            by_criterion[cid] = []
        by_criterion[cid].append(item)

    results = {}

    for criterion in phenotype_def["criteria"]:
        cid = criterion["criterion_id"]
        criterion_evidence = by_criterion.get(cid, [])

        if cid == "C2_TREATMENT_FAILURE":
            # Special aggregation: count DISTINCT failed medications
            distinct_meds = set()
            for ev in criterion_evidence:
                med_name = ev.get("normalized_medication", ev["entity_text"].lower())
                distinct_meds.add(med_name)

            min_required = criterion.get("min_distinct_medications", 2)
            results[cid] = {
                "met": len(distinct_meds) >= min_required,
                "confidence": (
                    sum(e["confidence"] for e in criterion_evidence) / len(criterion_evidence)
                    if criterion_evidence else 0.0
                ),
                "evidence_count": len(criterion_evidence),
                "supporting_notes": list(set(e["note_id"] for e in criterion_evidence)),
                "details": {
                    "distinct_failed_medications": sorted(distinct_meds),
                    "required": min_required,
                },
            }
        else:
            # Standard aggregation: count evidence instances, with temporal
            # conflict resolution when both positive and negative evidence exist.
            # "current-status" (default): most recent note wins.
            # "ever-had": any positive evidence suffices regardless of negations.
            positive_evidence = [e for e in criterion_evidence if e.get("assertion") == "POSITIVE"]
            negative_evidence = [e for e in criterion_evidence if e.get("assertion") == "NEGATIVE"]

            temporal_mode = criterion.get("temporal_semantics", "current-status")
            if positive_evidence and negative_evidence:
                if temporal_mode == "current-status":
                    latest_negative_date = max(e["note_date"] for e in negative_evidence)
                    positive_evidence = [
                        e for e in positive_evidence if e["note_date"] > latest_negative_date
                    ]
                # "ever-had": keep all positive evidence unchanged

            min_required = criterion.get("min_evidence_count", 1)
            results[cid] = {
                "met": len(positive_evidence) >= min_required,
                "confidence": (
                    sum(e["confidence"] for e in positive_evidence) / len(positive_evidence)
                    if positive_evidence else 0.0
                ),
                "evidence_count": len(positive_evidence),
                "supporting_notes": list(set(e["note_id"] for e in positive_evidence)),
                "details": {
                    "matched_terms": list(set(e["entity_text"] for e in positive_evidence)),
                },
            }

    return results
```

---

## Step 4: Classify the Patient

*The pseudocode calls this `classify_patient`. Apply the phenotype logic to determine whether the patient qualifies: DEFINITE, PROBABLE, EXCLUDED, or INSUFFICIENT_DATA.*

```python
def classify_patient(
    patient_id: str,
    criterion_results: dict,
    phenotype_def: dict,
) -> dict:
    """
    Apply classification logic to produce a final patient-level determination.

    The logic for this phenotype is straightforward: ALL criteria must be met.
    - DEFINITE: all criteria met with average confidence >= 0.85
    - PROBABLE: all criteria met but lower confidence, or partial evidence
    - EXCLUDED: explicit contradictory evidence found
    - INSUFFICIENT_DATA: not enough documentation to determine

    In practice, classification logic can be far more complex (weighted criteria,
    hierarchical logic, time-dependent rules). This example keeps it simple.

    Args:
        patient_id: The patient identifier.
        criterion_results: Output from aggregate_evidence().
        phenotype_def: The phenotype definition.

    Returns:
        Complete classification record with all supporting detail.
    """
    all_criteria_met = True
    has_partial_evidence = False
    min_confidence = 1.0

    for criterion in phenotype_def["criteria"]:
        cid = criterion["criterion_id"]
        result = criterion_results.get(cid, {"met": False, "evidence_count": 0, "confidence": 0.0})

        if not result["met"]:
            all_criteria_met = False
            if result["evidence_count"] > 0:
                has_partial_evidence = True
        else:
            min_confidence = min(min_confidence, result["confidence"])

    # Determine classification
    if all_criteria_met and min_confidence >= 0.85:
        classification = "DEFINITE"
    elif all_criteria_met:
        classification = "PROBABLE"
    elif has_partial_evidence:
        classification = "PROBABLE"
    else:
        classification = "INSUFFICIENT_DATA"

    # Build the output record. This is what gets written to S3 and
    # becomes the authoritative result for this patient.
    record = {
        "patient_id": patient_id,
        "phenotype_id": phenotype_def["phenotype_id"],
        "phenotype_version": phenotype_def["version"],
        "classification": classification,
        "criteria_results": criterion_results,
        "processing_timestamp": datetime.datetime.now(timezone.utc).isoformat(),
        "notes_processed": len(
            set(
                note_id
                for cr in criterion_results.values()
                for note_id in cr.get("supporting_notes", [])
            )
        ),
        "pipeline_version": "example-1.0",
    }

    return record
```

---

## Full Pipeline: Putting It All Together

Here's the complete flow assembled into a single callable function. This processes one patient's notes through the entire phenotype extraction pipeline.

```python
def run_phenotype_extraction(patient_id: str, notes: list, phenotype_def: dict) -> dict:
    """
    Run the full phenotype extraction pipeline for a single patient.

    In production, this would be orchestrated by Step Functions:
    - Fan out across Lambda invocations for per-note processing
    - Accumulate evidence in DynamoDB
    - Run aggregation and classification as a final step

    For this example, we process sequentially in-memory.

    Args:
        patient_id: Unique patient identifier.
        notes: List of note dicts with keys: note_id, note_date, text.
        phenotype_def: The phenotype definition to evaluate against.

    Returns:
        The final classification record.
    """
    print(f"\n{'='*60}")
    print(f"PHENOTYPE EXTRACTION: {phenotype_def['phenotype_name']}")
    print(f"Patient: {patient_id}")
    print(f"Notes to process: {len(notes)}")
    print(f"{'='*60}\n")

    # Step 1 + 2: Process each note and evaluate against criteria
    all_evidence = []

    for i, note in enumerate(notes, 1):
        print(f"[Step 1-2] Processing note {i}/{len(notes)}: {note['note_id']}")
        print(f"           Type: {note.get('note_type', 'Unknown')}, Date: {note['note_date']}")

        # Extract entities using Comprehend Medical
        extraction = extract_entities_from_note(note)
        print(f"           Entities extracted: {extraction['entity_count']}")

        # Evaluate entities against phenotype criteria
        evidence = evaluate_note_against_criteria(extraction, phenotype_def, note["text"])
        print(f"           Evidence items found: {len(evidence)}")

        for ev in evidence:
            print(f"             -> {ev['criterion_id']}: '{ev['entity_text']}' "
                  f"(confidence: {ev['confidence']:.2f})")

        all_evidence.extend(evidence)
        print()

    # Step 3: Aggregate evidence across all notes
    print(f"[Step 3] Aggregating evidence across {len(notes)} notes...")
    criterion_results = aggregate_evidence(all_evidence, phenotype_def)

    for cid, result in criterion_results.items():
        status = "MET" if result["met"] else "NOT MET"
        print(f"         {cid}: {status} "
              f"(evidence: {result['evidence_count']}, confidence: {result['confidence']:.2f})")
        if "details" in result:
            print(f"           Details: {result['details']}")
    print()

    # Step 4: Classify the patient
    print("[Step 4] Classifying patient...")
    classification = classify_patient(patient_id, criterion_results, phenotype_def)
    print(f"         Classification: {classification['classification']}")
    print(f"         Notes processed: {classification['notes_processed']}")
    print()

    return classification

# Run the pipeline on our synthetic patient
if __name__ == "__main__":
    result = run_phenotype_extraction(
        patient_id="SYNTH-0042871",
        notes=SYNTHETIC_NOTES,
        phenotype_def=PHENOTYPE_DEFINITION,
    )

    print("=" * 60)
    print("FINAL RESULT:")
    print("=" * 60)
    print(json.dumps(result, indent=2, default=str))
```

---

## Storing Evidence in DynamoDB (Production Pattern)

In the full architecture, evidence accumulates in DynamoDB as notes are processed. Here's how you'd write and query evidence in the production pipeline:

```python
def store_evidence_item(patient_id: str, evidence_item: dict) -> None:
    """
    Write a single evidence item to DynamoDB.

    The table uses patient_id as partition key and a composite sort key
    of criterion_id + note_id for efficient per-patient, per-criterion queries.

    DynamoDB gotcha: floats must be wrapped in Decimal. boto3's resource layer
    raises TypeError on raw Python floats.

    TTL policy: intermediate NLP artifacts expire after 90 days. Final
    classifications stored in S3 follow institutional retention (7-10 years).
    """
    table = dynamodb.Table(EVIDENCE_TABLE_NAME)

    # TTL: expire intermediate evidence after 90 days.
    # Records linked to published cohorts should have TTL removed manually
    # or set to match the study's data retention schedule.
    ttl_seconds = 90 * 24 * 60 * 60  # 90 days
    expires_at = int(datetime.datetime.now(timezone.utc).timestamp()) + ttl_seconds

    item = {
        "patient_id": patient_id,
        "sort_key": f"{evidence_item['criterion_id']}#{evidence_item['note_id']}",
        "criterion_id": evidence_item["criterion_id"],
        "note_id": evidence_item["note_id"],
        "note_date": evidence_item["note_date"],
        "entity_text": evidence_item["entity_text"],
        "assertion": evidence_item["assertion"],
        "confidence": Decimal(str(round(evidence_item["confidence"], 4))),
        "evidence_type": evidence_item["evidence_type"],
        "stored_at": datetime.datetime.now(timezone.utc).isoformat(),
        "expires_at": expires_at,  # DynamoDB TTL attribute
    }

    # Add optional fields if present
    if "normalized_medication" in evidence_item:
        item["normalized_medication"] = evidence_item["normalized_medication"]
    if "numeric_value" in evidence_item:
        item["numeric_value"] = Decimal(str(evidence_item["numeric_value"]))

    table.put_item(Item=item)

def query_patient_evidence(patient_id: str) -> list:
    """
    Retrieve all evidence for a patient from DynamoDB.

    Uses a Query (not Scan) against the partition key for O(1) lookup
    regardless of table size. This is what the aggregation Lambda calls
    after all notes have been processed.
    """
    table = dynamodb.Table(EVIDENCE_TABLE_NAME)

    response = table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("patient_id").eq(patient_id)
    )

    return response.get("Items", [])
```

---

## Storing Final Results in S3

```python
def store_classification_result(result: dict) -> str:
    """
    Write the final classification to S3 as a versioned JSON file.

    The S3 key includes the phenotype ID and version so you can track
    how classifications change as the phenotype definition evolves.
    Research reproducibility requires knowing exactly which version of
    the algorithm produced each classification.

    Returns the S3 key where the result was stored.
    """
    patient_id = result["patient_id"]
    phenotype_id = result["phenotype_id"]
    version = result["phenotype_version"]
    timestamp = result["processing_timestamp"].replace(":", "-")

    s3_key = (
        f"classifications/{phenotype_id}/v{version}/"
        f"{patient_id}/{timestamp}.json"
    )

    s3.put_object(
        Bucket=RESULTS_BUCKET,
        Key=s3_key,
        Body=json.dumps(result, indent=2, default=str),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
        # In production, specify your KMS key ID here:
        # SSEKMSKeyId="arn:aws:kms:us-east-1:123456789:key/your-key-id"
    )

    return s3_key
```

---

## The Gap Between This and Production

This example demonstrates the shape of a phenotype extraction pipeline. Here's the meaningful distance between this and something you'd actually use for research:

**Phenotype definition versioning and governance.** In this example, the phenotype definition is a Python dict. In production, it's a versioned artifact in S3 (or a registry service) with formal change control. Changing a criterion definition triggers re-classification of all affected patients and a validation report. You need to know exactly which definition version produced each cohort.

**Validation infrastructure.** The single most important thing missing here is a validation loop. Before you trust any automated phenotype classification, you need: (1) gold-standard annotations from clinician chart reviewers, (2) a validation sample of 100+ patients, (3) calculated PPV, sensitivity, and specificity, and (4) inter-rater reliability scores showing your annotators agree. Without this, your cohort is noise.

**Error handling and fault tolerance.** If Comprehend Medical returns an error on one note out of 40, this example crashes. A production pipeline: retries with backoff, logs the failure, continues processing other notes, and marks the patient's classification as "partial" if too many notes failed. Step Functions provides this orchestration natively.

**Batching and cost control.** This processes notes one at a time. At scale (50,000 patients, 40 notes each = 2 million API calls), you'd batch aggressively, pre-filter patients using structured data queries (only run NLP on patients who pass the ICD-code screen), and use reserved concurrency on Lambda to control costs. The pre-filter step alone can reduce your Comprehend Medical spend by 80-90%.

**Section detection.** The phenotype definition references "exclude_sections" (like FAMILY_HISTORY), but this example doesn't actually detect which section an entity appears in. Production systems use note section parsers (regex-based or ML-based) that identify standard clinical document sections so you can correctly ignore "Father had depression" when looking for patient depression.

**Custom models for complex criteria.** "Adequate antidepressant trial" is a nuanced clinical judgment that substring matching handles poorly. A production system trains a custom classifier (hosted on SageMaker) specifically for treatment adequacy assertions. The training data comes from your validation annotations.

**DynamoDB data types.** Every float that goes into DynamoDB must be wrapped in `Decimal`. This example handles it in the storage functions, but if you add new numeric fields anywhere in the evidence pipeline, remember this constraint. boto3 will raise `TypeError` on raw floats.

**IAM least-privilege.** The IAM role running this pipeline should have exactly: `comprehend:DetectEntitiesV2`, `comprehend:InferRxNorm`, `comprehend:InferICD10CM` on all resources; `s3:GetObject` scoped to the notes bucket; `s3:PutObject` scoped to the results bucket; `dynamodb:PutItem` and `dynamodb:Query` scoped to the evidence table. Not `comprehend:*`. Not `s3:*`.

**VPC and network isolation.** Clinical notes (even de-identified) should never traverse the public internet. Lambda runs in a private VPC with VPC endpoints for Comprehend Medical, S3, and DynamoDB. No internet gateway. No NAT gateway needed for these AWS-to-AWS calls.

**Reproducibility artifacts.** Research requires complete reproducibility documentation: which pipeline version ran, which phenotype definition version was used, which model versions were active, what the confidence thresholds were, and when the processing occurred. Every run produces a manifest alongside the classifications.

**Testing.** You need: unit tests for each extraction and matching function (with mocked Comprehend Medical responses), integration tests against Comprehend Medical with known synthetic notes, and end-to-end tests with a reference patient corpus whose correct classifications are known. Never use real patient data in test fixtures.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 8.10](chapter08.10-phenotype-extraction-research) for the full architectural walkthrough, pseudocode, and honest take on where phenotyping gets hard in practice.*
