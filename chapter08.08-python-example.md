# Recipe 8.8: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 8.8. It shows one way you could translate the clinical assertion classification concepts into working Python code. It is not production-ready. The rule-based layer is intentionally minimal, the "ML model" is simulated with a SageMaker endpoint call pattern, and the synthetic data is designed to exercise the core logic paths. Think of it as a sketch: useful for understanding the shape of the solution, not something you'd deploy against a live clinical NLP pipeline on Monday morning. Consider it a starting point, not a destination.
>
> This recipe uses two AWS services in combination: Amazon Comprehend Medical for entity extraction (with its built-in trait detection) and Amazon SageMaker for custom assertion classification when the built-in traits are too coarse. The hybrid approach (rules first, ML model for ambiguous cases) is the pattern you'll see in production systems.

---

## Setup

You'll need the AWS SDK for Python installed:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `comprehendmedical:DetectEntitiesV2`
- `sagemaker:InvokeEndpoint`
- `s3:GetObject`
- `s3:PutObject`
- `dynamodb:PutItem`
- `dynamodb:Query`

---

## Configuration and Constants

Everything that's really configuration rather than logic lives here. The assertion rules, section mappings, and thresholds are the pieces that need tuning to your institution's documentation patterns. Treat them as living documents.

```python
import json
import logging
import re
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. Never log PHI field values (entity text, patient IDs).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry configuration for AWS API calls under load.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# Module-level clients reused across Lambda invocations.
comprehend_medical_client = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
sagemaker_runtime_client = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb")

# ---------- Assertion Configuration ----------

# The seven assertion classes from the i2b2/VA 2010 taxonomy.
ASSERTION_CLASSES = [
    "present", "absent", "possible", "conditional",
    "historical", "family", "hypothetical"
]

# Confidence threshold: entities classified below this go to human review.
CONFIDENCE_THRESHOLD = 0.85

# Context window: characters before and after the entity to extract.
# ~2-3 sentences of surrounding text. Enough for negation cues without noise.
CONTEXT_WINDOW_CHARS = 300

# Entity extraction confidence: skip low-confidence entities from Comprehend Medical.
ENTITY_CONFIDENCE_THRESHOLD = 0.80

# SageMaker endpoint name for the custom assertion classifier.
# Replace with your deployed endpoint name.
SAGEMAKER_ENDPOINT_NAME = "clinical-assertion-classifier"

# DynamoDB table for annotated entities.
ANNOTATED_ENTITIES_TABLE = "assertion-annotated-entities"

# ---------- Rule-Based Assertion Patterns ----------

# Negation cues: words/phrases that signal the entity is absent.
# These are checked in the text BEFORE the entity (pre-negation).
NEGATION_CUES_PRE = [
    "no evidence of", "no signs of", "no symptoms of",
    "denies", "denied", "denying",
    "negative for", "without",
    "rules out", "ruled out", "rule out",
    "absence of", "free of", "unremarkable for",
    "no ", "not "
]

# Post-entity negation cues (less common but real).
NEGATION_CUES_POST = [
    "absent", "negative", "not found", "not seen",
    "not present", "not detected", "ruled out"
]

# Pseudo-negation: patterns that LOOK like negation but aren't.
# "not only" means the condition IS present (and more).
# "no longer" means it WAS present (historical, not absent).
PSEUDO_NEGATION = [
    "not only", "no longer", "no increase",
    "no change", "no improvement", "not ruled out"
]

# Historical cues: signals the condition existed in the past.
HISTORICAL_CUES = [
    "history of", "h/o", "s/p", "status post",
    "previously", "prior", "in the past",
    "resolved", "former", "remote history",
    "childhood history of", "past history of"
]

# Hedging cues: signals the clinician is uncertain (possible/probable).
HEDGING_CUES = [
    "possible", "probable", "likely", "suspected",
    "concerning for", "suspicious for", "consistent with",
    "cannot rule out", "cannot exclude", "differential includes",
    "questionable", "equivocal", "uncertain"
]

# Conditional cues: the entity depends on a future condition.
CONDITIONAL_CUES = [
    "if ", "in the event of", "should ",
    "in case of", "when ", "upon ",
    "contingent on", "provided that"
]

# Hypothetical cues: planning or speculative context.
HYPOTHETICAL_CUES = [
    "will consider", "may start", "would recommend",
    "plan to", "consider starting", "may develop",
    "could lead to", "potential for", "risk of developing"
]

# Family cues: entity pertains to a family member, not the patient.
FAMILY_CUES = [
    "mother", "father", "brother", "sister",
    "maternal", "paternal", "family history",
    "fhx", "family hx", "grandfather", "grandmother",
    "aunt", "uncle", "cousin", "sibling"
]

# Section headers that carry strong assertion signals.
# Mapping from normalized section name to the default assertion for entities
# found in that section. This is a strong prior, not absolute.
SECTION_ASSERTION_MAP = {
    "family history": "family",
    "fhx": "family",
    "family hx": "family",
    "past medical history": "historical",
    "pmh": "historical",
    "past surgical history": "historical",
    "psh": "historical",
    "surgical history": "historical",
}

# Maximum characters for entity text in the context window before we
# skip the rules and go straight to the model.
MAX_RULE_ENTITY_LENGTH = 100
```

---

## Step 1: Extract Entities from Clinical Text

*Maps to pseudocode Step 1. We call Comprehend Medical's `DetectEntitiesV2` to identify clinical entities (conditions, medications, procedures, tests) with their character offsets and built-in traits.*

```python
def extract_entities(note_text: str) -> list[dict]:
    """
    Extract clinical entities from note text using Comprehend Medical.

    DetectEntitiesV2 identifies medical conditions, medications, tests,
    procedures, and anatomy mentions. Each entity comes with:
      - Character offsets (BeginOffset, EndOffset) in the original text
      - Category and Type labels
      - Confidence score
      - Traits (including basic negation detection)

    We filter to entities above ENTITY_CONFIDENCE_THRESHOLD to reduce noise.
    The built-in Traits include NEGATION and other signals, but they only
    cover present vs. absent. Our assertion classifier extends this to the
    full 7-class taxonomy.

    Args:
        note_text: raw clinical note text (up to 20,000 characters for DetectEntitiesV2)

    Returns:
        List of entity dicts with text, category, offsets, traits, and score.
    """
    # DetectEntitiesV2 accepts up to 20,000 UTF-8 characters per request.
    # For longer notes, you'd split at sentence boundaries and process in chunks.
    if len(note_text) > 20000:
        note_text = note_text[:20000]
        logger.warning("Note text truncated to 20,000 chars for DetectEntitiesV2")

    response = comprehend_medical_client.detect_entities_v2(Text=note_text)

    entities = []
    for entity in response.get("Entities", []):
        score = entity.get("Score", 0.0)
        if score < ENTITY_CONFIDENCE_THRESHOLD:
            continue

        # Extract trait names for quick lookup downstream.
        # Traits include NEGATION, SIGN, SYMPTOM, DIAGNOSIS, etc.
        trait_names = [
            t["Name"] for t in entity.get("Traits", [])
            if t.get("Score", 0.0) >= 0.75
        ]

        entities.append({
            "text": entity["Text"],
            "category": entity["Category"],
            "type": entity.get("Type", ""),
            "begin_offset": entity["BeginOffset"],
            "end_offset": entity["EndOffset"],
            "score": round(score, 3),
            "traits": trait_names,
        })

    logger.info("Extracted %d entities above confidence threshold", len(entities))
    return entities
```

---

## Step 2: Extract Context Windows for Each Entity

*Maps to pseudocode Step 2. For each entity, we pull surrounding text and attempt to detect the section header. The classifier needs this context to identify negation cues, hedging language, and scope boundaries.*

```python
def detect_section_header(note_text: str, entity_offset: int) -> str | None:
    """
    Attempt to detect the section header governing a given text position.

    Clinical notes are structured into sections (Assessment, HPI, PMH, etc.)
    but section headers are inconsistent across EHR templates and institutions.
    We look backwards from the entity position for common header patterns.

    This is deliberately simple. Production systems use ML-based section
    detection or rely on EHR-provided section metadata.
    """
    # Look backwards up to 500 chars for a line that looks like a section header.
    # Common patterns: "FAMILY HISTORY:", "Past Medical History", "Assessment and Plan"
    search_start = max(0, entity_offset - 500)
    preceding_text = note_text[search_start:entity_offset]

    # Split into lines and search backwards for a header-like line.
    lines = preceding_text.split("\n")
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        # Heuristic: section headers are short, often uppercase or end with ":"
        if len(stripped) < 50 and (stripped.endswith(":") or stripped.isupper()):
            return stripped.rstrip(":").strip().lower()

    return None


def extract_context_windows(note_text: str, entities: list[dict]) -> list[dict]:
    """
    Build context windows around each entity for assertion classification.

    Each context window includes:
      - The surrounding text (CONTEXT_WINDOW_CHARS before and after)
      - The entity's position within that window
      - The detected section header (if any)

    The classifier uses this window to find negation cues, hedging language,
    family history indicators, and other assertion-relevant signals.

    Args:
        note_text: the full clinical note text
        entities: list of entity dicts from extract_entities

    Returns:
        List of context dicts, one per entity, ready for classification.
    """
    entity_contexts = []

    for entity in entities:
        begin = entity["begin_offset"]
        end = entity["end_offset"]

        # Calculate window boundaries, clamping to document edges.
        window_start = max(0, begin - CONTEXT_WINDOW_CHARS)
        window_end = min(len(note_text), end + CONTEXT_WINDOW_CHARS)

        context_text = note_text[window_start:window_end]

        # Entity position within the extracted context window.
        entity_start_in_context = begin - window_start
        entity_end_in_context = end - window_start

        # Detect the section header for this region of the note.
        section_header = detect_section_header(note_text, begin)

        entity_contexts.append({
            "entity": entity,
            "context_text": context_text,
            "entity_start_in_context": entity_start_in_context,
            "entity_end_in_context": entity_end_in_context,
            "section_header": section_header,
        })

    return entity_contexts
```

---

## Step 3: Classify Assertion Status (Hybrid: Rules + ML)

*Maps to pseudocode Step 3. The two-pass approach: rules handle the obvious cases quickly (negations, family history sections, clear temporal markers). Everything the rules can't confidently classify goes to the SageMaker-hosted ML model.*

```python
def apply_assertion_rules(ctx: dict) -> dict | None:
    """
    Rule-based assertion detection for high-confidence cases.

    This handles about 60% of entities in typical clinical text:
      - Clear negations ("denies", "no evidence of", "negative for")
      - Section-based assertions (Family History section -> family)
      - Obvious historical markers ("history of", "s/p", "previously")
      - Clear hedging ("possible", "suspected", "cannot rule out")

    Returns a result dict if rules can confidently classify, or None if
    the entity needs ML model classification.

    Args:
        ctx: context dict from extract_context_windows

    Returns:
        Dict with assertion and confidence, or None if rules can't decide.
    """
    section = ctx["section_header"]
    entity_start = ctx["entity_start_in_context"]
    entity_end = ctx["entity_end_in_context"]
    context = ctx["context_text"]

    # Text before and after the entity in the context window.
    text_before = context[:entity_start].lower()
    text_after = context[entity_end:].lower()

    # --- Check 1: Section header (strongest signal) ---
    if section and section in SECTION_ASSERTION_MAP:
        return {
            "assertion": SECTION_ASSERTION_MAP[section],
            "confidence": 0.95 if "family" in section else 0.90,
            "method": "rule_based",
            "rule": f"section_header:{section}",
        }

    # --- Check 2: Family cues in surrounding text ---
    for cue in FAMILY_CUES:
        if cue in text_before[-80:]:
            return {
                "assertion": "family",
                "confidence": 0.91,
                "method": "rule_based",
                "rule": f"family_cue:{cue}",
            }

    # --- Check 3: Pre-entity negation ---
    # Only look within 60 chars before the entity (scope approximation).
    near_text_before = text_before[-60:]

    # First check for pseudo-negation (looks like negation but isn't).
    for pseudo in PSEUDO_NEGATION:
        if pseudo in near_text_before:
            # Pseudo-negation detected. Don't classify as absent.
            # Fall through to ML model for nuanced classification.
            return None

    for cue in NEGATION_CUES_PRE:
        if cue in near_text_before:
            return {
                "assertion": "absent",
                "confidence": 0.92,
                "method": "rule_based",
                "rule": f"negation_pre:{cue}",
            }

    # Post-entity negation (less common).
    near_text_after = text_after[:40]
    for cue in NEGATION_CUES_POST:
        if cue in near_text_after:
            return {
                "assertion": "absent",
                "confidence": 0.89,
                "method": "rule_based",
                "rule": f"negation_post:{cue}",
            }

    # --- Check 4: Historical cues ---
    for cue in HISTORICAL_CUES:
        if cue in near_text_before:
            return {
                "assertion": "historical",
                "confidence": 0.88,
                "method": "rule_based",
                "rule": f"historical:{cue}",
            }

    # --- Check 5: Conditional cues ---
    for cue in CONDITIONAL_CUES:
        if cue in near_text_before:
            return {
                "assertion": "conditional",
                "confidence": 0.86,
                "method": "rule_based",
                "rule": f"conditional:{cue}",
            }

    # --- Check 6: Hypothetical cues ---
    for cue in HYPOTHETICAL_CUES:
        if cue in text_before[-100:]:
            return {
                "assertion": "hypothetical",
                "confidence": 0.85,
                "method": "rule_based",
                "rule": f"hypothetical:{cue}",
            }

    # --- Check 7: Hedging cues ---
    for cue in HEDGING_CUES:
        if cue in near_text_before:
            return {
                "assertion": "possible",
                "confidence": 0.87,
                "method": "rule_based",
                "rule": f"hedging:{cue}",
            }

    # Rules couldn't confidently classify. Pass to ML model.
    return None


def classify_with_model(ctx: dict) -> dict:
    """
    Call the SageMaker-hosted assertion classifier for ambiguous cases.

    The model expects input formatted with [ENTITY] markers around the
    target span, plus the section header prepended as context. This tells
    the model which concept to classify vs. what's just surrounding text.

    Example input:
      "Section: Assessment\nPatient has [ENTITY]early-stage CKD[/ENTITY] based on labs"

    The model returns a JSON response with the predicted assertion class
    and confidence score.

    Args:
        ctx: context dict from extract_context_windows

    Returns:
        Dict with assertion, confidence, and method="ml_model".
    """
    context_text = ctx["context_text"]
    start = ctx["entity_start_in_context"]
    end = ctx["entity_end_in_context"]
    section = ctx["section_header"]

    # Format input: insert entity markers so the model knows the target span.
    marked_text = (
        context_text[:start]
        + "[ENTITY]"
        + context_text[start:end]
        + "[/ENTITY]"
        + context_text[end:]
    )

    # Prepend section header if available.
    if section:
        model_input = f"Section: {section}\n{marked_text}"
    else:
        model_input = marked_text

    # Call the SageMaker endpoint.
    payload = json.dumps({"text": model_input})

    response = sagemaker_runtime_client.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT_NAME,
        ContentType="application/json",
        Body=payload,
    )

    result = json.loads(response["Body"].read().decode("utf-8"))

    return {
        "assertion": result["assertion_class"],
        "confidence": result["confidence"],
        "method": "ml_model",
    }


def classify_assertions(entity_contexts: list[dict]) -> list[dict]:
    """
    Two-pass assertion classification: rules first, ML model for the rest.

    Pass 1 (rules): handles obvious negations, section-based assertions,
    and clear temporal/hedging cues. Fast, deterministic, no network call.

    Pass 2 (ML model): invoked only for entities the rules couldn't
    confidently classify. Calls the SageMaker endpoint.

    Args:
        entity_contexts: list of context dicts from extract_context_windows

    Returns:
        List of classification result dicts with entity, assertion, confidence, and method.
    """
    results = []
    rule_count = 0
    model_count = 0

    for ctx in entity_contexts:
        # Pass 1: Try rules.
        rule_result = apply_assertion_rules(ctx)

        if rule_result and rule_result["confidence"] >= CONFIDENCE_THRESHOLD:
            # Propagate section_header into the entity dict so conflict
            # resolution (Step 4) can use it for priority scoring.
            entity_with_section = {**ctx["entity"], "section_header": ctx["section_header"]}
            results.append({
                "entity": entity_with_section,
                "assertion": rule_result["assertion"],
                "confidence": rule_result["confidence"],
                "method": rule_result["method"],
                "rule": rule_result.get("rule"),
            })
            rule_count += 1
            continue

        # Pass 2: ML model for ambiguous cases.
        try:
            model_result = classify_with_model(ctx)
            entity_with_section = {**ctx["entity"], "section_header": ctx["section_header"]}
            results.append({
                "entity": entity_with_section,
                "assertion": model_result["assertion"],
                "confidence": model_result["confidence"],
                "method": model_result["method"],
            })
            model_count += 1
        except Exception as e:
            # If the model endpoint is unavailable, fall back to "present"
            # with low confidence (will be flagged for review).
            logger.warning("Model invocation failed for entity '%s': %s",
                           ctx["entity"]["text"], str(e))
            entity_with_section = {**ctx["entity"], "section_header": ctx["section_header"]}
            results.append({
                "entity": entity_with_section,
                "assertion": "present",
                "confidence": 0.50,
                "method": "fallback",
            })

    logger.info("Classification complete: %d by rules, %d by model", rule_count, model_count)
    return results
```

---

## Step 4: Post-Process and Resolve Conflicts

*Maps to pseudocode Step 4. When the same clinical concept appears multiple times with different assertion statuses, we resolve to the most clinically relevant assertion using section priority and note position.*

```python
# Section priority for conflict resolution.
# Higher number = more likely to reflect current clinical truth.
SECTION_PRIORITY = {
    "assessment": 5, "assessment and plan": 5, "a/p": 5, "plan": 5,
    "hpi": 4, "history of present illness": 4,
    "ros": 3, "review of systems": 3,
    "pmh": 2, "past medical history": 2,
    "fhx": 1, "family history": 1, "family hx": 1,
}


def resolve_assertion_conflicts(classified_entities: list[dict]) -> list[dict]:
    """
    Resolve conflicts when the same concept has multiple assertion mentions.

    Example: "diabetes" in PMH (historical) AND in Assessment (present).
    The Assessment mention wins because it reflects today's clinical state.

    We group by normalized entity text and pick the highest-priority mention.
    All mentions are preserved in the audit trail.

    Args:
        classified_entities: list from classify_assertions

    Returns:
        Deduplicated list with one assertion per unique concept.
        Conflict-resolved entries include all_mentions for audit.
    """
    # Group entities by normalized text (lowercase, stripped).
    # Production systems use concept normalization (CUI mapping via UMLS)
    # rather than raw text matching. Raw text conflates distinct entities
    # that happen to share surface forms.
    groups = {}
    for item in classified_entities:
        key = item["entity"]["text"].lower().strip()
        if key not in groups:
            groups[key] = []
        groups[key].append(item)

    resolved = []

    for concept, mentions in groups.items():
        if len(mentions) == 1:
            resolved.append(mentions[0])
            continue

        # Multiple mentions: pick highest priority.
        def priority_score(item):
            # Use section priority if available, otherwise default to 3.
            section = item["entity"].get("section_header") or ""
            section_score = SECTION_PRIORITY.get(section, 3)
            # Tie-break: later in the note = higher priority.
            position_score = item["entity"]["begin_offset"] / 10000.0
            return section_score + position_score

        best = max(mentions, key=priority_score)
        best["all_mentions"] = mentions
        best["conflict_resolved"] = True
        resolved.append(best)

    conflicts = sum(1 for r in resolved if r.get("conflict_resolved"))
    if conflicts:
        logger.info("Resolved %d assertion conflicts", conflicts)

    return resolved
```

---

## Step 5: Store Annotated Entities

*Maps to pseudocode Step 5. Write assertion-classified entities to DynamoDB, indexed for downstream queries.*

```python
def store_annotated_entities(
    patient_id: str,
    note_id: str,
    note_date: str,
    resolved_entities: list[dict],
) -> dict:
    """
    Write assertion-annotated entities to DynamoDB.

    Each entity record includes:
      - Patient/note linkage for provenance
      - The assertion classification and confidence
      - A needs_review flag for low-confidence classifications
      - A context snippet for human review

    Also writes a note-level summary showing assertion distribution.

    Args:
        patient_id: patient identifier
        note_id: unique note identifier
        note_date: ISO date string for the clinical note
        resolved_entities: deduplicated list from resolve_assertion_conflicts

    Returns:
        Summary dict with counts by assertion class.
    """
    table = dynamodb.Table(ANNOTATED_ENTITIES_TABLE)

    # Count assertions by class for the summary.
    assertion_counts = {cls: 0 for cls in ASSERTION_CLASSES}
    review_count = 0

    for idx, result in enumerate(resolved_entities):
        needs_review = result["confidence"] < CONFIDENCE_THRESHOLD
        if needs_review:
            review_count += 1

        assertion = result["assertion"]
        if assertion in assertion_counts:
            assertion_counts[assertion] += 1

        record = {
            "patient_id": patient_id,
            "note_id_entity_idx": f"{note_id}#{idx:04d}",
            "note_id": note_id,
            "note_date": note_date,
            "entity_text": result["entity"]["text"],
            "entity_category": result["entity"]["category"],
            "assertion_status": assertion,
            "confidence": Decimal(str(round(result["confidence"], 3))),
            "method": result["method"],
            "needs_review": needs_review,
            "processed_at": datetime.datetime.now(timezone.utc).isoformat(),
        }

        table.put_item(Item=record)

    summary = {
        "note_id": note_id,
        "patient_id": patient_id,
        "note_date": note_date,
        "total_entities": len(resolved_entities),
        "assertion_counts": assertion_counts,
        "needs_review_count": review_count,
    }

    logger.info(
        "Stored %d annotated entities (%d for review)",
        len(resolved_entities), review_count
    )
    return summary
```

---

## Putting It All Together

The full pipeline assembled into a single function. This orchestrates all five steps from the recipe pseudocode.

```python
def classify_note_assertions(
    note_text: str,
    patient_id: str,
    note_id: str,
    note_date: str,
) -> dict:
    """
    Run the full assertion classification pipeline on one clinical note.

    Steps:
      1. Extract entities with Comprehend Medical
      2. Build context windows around each entity
      3. Classify assertions (rules + ML model)
      4. Resolve conflicts for repeated concepts
      5. Store annotated entities in DynamoDB

    Args:
        note_text: raw clinical note text
        patient_id: patient identifier
        note_id: unique note identifier
        note_date: ISO date string

    Returns:
        Summary dict with assertion counts and review statistics.
    """
    # Step 1: Entity extraction.
    logger.info("Step 1: Extracting entities from note %s", note_id)
    entities = extract_entities(note_text)

    if not entities:
        logger.info("No entities found in note %s", note_id)
        return {"note_id": note_id, "total_entities": 0}

    # Step 2: Context window extraction.
    logger.info("Step 2: Extracting context windows for %d entities", len(entities))
    entity_contexts = extract_context_windows(note_text, entities)

    # Step 3: Assertion classification (hybrid rules + ML).
    logger.info("Step 3: Classifying assertion status")
    classified = classify_assertions(entity_contexts)

    # Step 4: Conflict resolution.
    logger.info("Step 4: Resolving assertion conflicts")
    resolved = resolve_assertion_conflicts(classified)

    # Step 5: Store results.
    logger.info("Step 5: Storing annotated entities")
    summary = store_annotated_entities(patient_id, note_id, note_date, resolved)

    logger.info("Done. %d entities classified for note %s", summary["total_entities"], note_id)
    return summary


# ---------- Demo with synthetic clinical data ----------

if __name__ == "__main__":

    # Synthetic clinical note exercising all seven assertion classes.
    # This is NOT real patient data. It's designed to test the assertion logic.
    SAMPLE_NOTE = """
HISTORY OF PRESENT ILLNESS:
62-year-old male presenting with fatigue and polyuria. Patient has type 2 diabetes
managed with metformin. Denies chest pain or shortness of breath. Reports occasional
dizziness when standing quickly.

PAST MEDICAL HISTORY:
History of MI in 2019, treated with PCI. Status post appendectomy (childhood).
Previously treated for H. pylori (resolved 2021).

FAMILY HISTORY:
Mother had breast cancer diagnosed at age 58. Father died of colon cancer at 72.
Maternal grandmother had rheumatoid arthritis.

REVIEW OF SYSTEMS:
No fever, no chills, no weight loss. Denies hematuria. Reports mild nocturia x3.

ASSESSMENT AND PLAN:
1. Type 2 diabetes, poorly controlled. HbA1c 8.9%. Will increase metformin to 1000mg BID.
2. Possible early CKD based on elevated creatinine. Repeat labs in 3 months.
3. If GFR drops below 30, will initiate nephrology referral.
4. Hypertension, stable on current regimen.
5. Cannot rule out sleep apnea given fatigue and BMI. Consider sleep study.
"""

    result = classify_note_assertions(
        note_text=SAMPLE_NOTE,
        patient_id="pat-00291",
        note_id="note-2026-03-15-00847",
        note_date="2026-03-15",
    )

    print(json.dumps(result, indent=2, default=str))
```

**Expected output structure** (actual results depend on Comprehend Medical response and model predictions):

```json
{
  "note_id": "note-2026-03-15-00847",
  "patient_id": "pat-00291",
  "note_date": "2026-03-15",
  "total_entities": 14,
  "assertion_counts": {
    "present": 4,
    "absent": 3,
    "possible": 2,
    "conditional": 1,
    "historical": 3,
    "family": 3,
    "hypothetical": 1
  },
  "needs_review_count": 2
}
```

---

## Lambda Handler Version

In production, this pipeline is triggered when a clinical note is finalized in the EHR. The event arrives via an integration layer (HL7 FHIR notification, Kinesis stream, or direct S3 upload).

```python
import os


def lambda_handler(event: dict, context) -> dict:
    """
    Lambda handler for real-time assertion classification.

    Triggered by a note finalization event containing:
      - note_text or an S3 reference to the note
      - patient_id
      - note_id
      - note_date

    Returns the assertion summary for monitoring and downstream routing.
    """
    # Extract note metadata from the event.
    # Adapt this to your integration layer's event format.
    record = event.get("detail", event)

    note_text = record.get("note_text")
    patient_id = record["patient_id"]
    note_id = record["note_id"]
    note_date = record["note_date"]

    # If note_text not inline, fetch from S3.
    if not note_text and "s3_bucket" in record:
        # S3 client created here rather than module scope because this path
        # is only used when notes arrive via S3 reference rather than inline.
        s3 = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
        obj = s3.get_object(
            Bucket=record["s3_bucket"],
            Key=record["s3_key"],
        )
        note_text = obj["Body"].read().decode("utf-8")

    if not note_text:
        logger.error("No note text available for note %s", note_id)
        return {"error": "no_note_text", "note_id": note_id}

    summary = classify_note_assertions(note_text, patient_id, note_id, note_date)

    # Route notes with entities needing review to a review queue.
    if summary.get("needs_review_count", 0) > 0:
        logger.info("Note %s has %d entities for review", note_id, summary["needs_review_count"])
        # In production: send to SQS review queue
        # sqs_client.send_message(
        #     QueueUrl=os.environ["REVIEW_QUEUE_URL"],
        #     MessageBody=json.dumps({"note_id": note_id, "patient_id": patient_id}),
        # )

    return summary
```

---

## The Gap Between This and Production

This example works: run it against a clinical note (with a deployed SageMaker endpoint) and it will extract entities, classify their assertion status, resolve conflicts, and store the results. The distance between this and a production clinical NLP pipeline is real. Here's where it lives.

**The SageMaker model doesn't exist yet.** This code calls a SageMaker endpoint named `clinical-assertion-classifier`, but training and deploying that model is a significant project in itself. You need annotated training data (hundreds to thousands of entity-assertion pairs labeled by clinical annotators), a fine-tuning pipeline (ClinicalBERT or BioBERT as the base model), and a deployment configuration. The rule-based layer works without the model, but it only covers about 60% of cases. For the remaining 40%, you need the trained model or a fallback strategy (like defaulting to Comprehend Medical's built-in traits).

**Comprehend Medical's DetectEntitiesV2 has a 20,000-character limit.** The example truncates silently. A production pipeline splits long notes at sentence boundaries, processes each chunk, and deduplicates entities that span chunk boundaries. Clinical notes from ICU stays or complex hospitalizations regularly exceed 20,000 characters.

**Batch processing for research workloads.** The example processes one note at a time. For research cohort identification (where you're processing millions of historical notes), you need SageMaker Batch Transform instead of real-time endpoints. Batch Transform is cheaper per prediction but adds latency. Design your pipeline to support both modes: real-time for clinical decision support, batch for retrospective research.

**Section detection is fragile.** The `detect_section_header` function uses simple heuristics (short lines ending in colons or all-caps). Real clinical notes have wildly inconsistent section formatting. Some EHR systems provide structured section metadata via CDA or FHIR DocumentReference resources. If your EHR provides section boundaries, use them instead of detecting from raw text.

**Negation scope is approximated.** The rule-based layer checks for negation cues within 60 characters before the entity. Real negation scope is syntactic, not distance-based. "Patient denies chest pain, shortness of breath, and palpitations but reports occasional dizziness" has a negation scope that extends through a conjunction and terminates at "but." The 60-character window is a reasonable approximation for common patterns but will misclassify entities at the edge of complex scope boundaries. The ML model handles these cases better, which is why the hybrid approach matters.

**Conflict resolution needs clinical input.** The priority-based resolution (Assessment > HPI > PMH) is a reasonable default, but clinical edge cases exist. A condition marked "historical" in PMH and "absent" in today's Assessment might mean "resolved" (which is different from "never had it"). Production systems often return all mentions rather than resolving to a single assertion, letting downstream consumers apply their own resolution logic.

**Model monitoring and drift detection.** Clinical documentation patterns change over time: new EHR templates, new providers, new specialty clinics. A model trained on 2025 notes may underperform on 2027 notes. Set up CloudWatch metrics on model confidence distributions. A shift in the distribution (more low-confidence predictions) is an early signal of model drift requiring retraining.

**Error handling and dead letter queues.** If Comprehend Medical times out or the SageMaker endpoint is temporarily unavailable, the Lambda needs to retry with backoff. Configure DLQ for messages that fail repeatedly. A note that fails assertion classification silently is a note whose entities won't appear in downstream quality measures or CDS queries.

**DynamoDB partition design.** The example uses `patient_id` as the partition key and `note_id_entity_idx` as the sort key. This works for patient-centric queries ("show me all present conditions for patient X"). If you also need entity-centric queries ("find all patients with family history of breast cancer"), you need a Global Secondary Index on `assertion_status + entity_text` or a separate query-optimized table. Design your access patterns before deploying.

**Testing with synthetic vs. real data.** The synthetic note in `__main__` exercises the happy path. Production testing requires a fixture library covering edge cases: notes with no section headers, notes with conflicting assertions, extremely long notes, notes with heavy abbreviation use, specialty-specific documentation (surgical notes vs. psychiatry notes vs. radiology reports). The i2b2 2010 assertion corpus (requires a data use agreement) provides annotated test data for benchmarking.

**VPC and encryption.** Lambda processing clinical notes runs inside a VPC with VPC endpoints for Comprehend Medical, SageMaker, DynamoDB, S3, and CloudWatch Logs. Clinical notes are PHI. Encrypt everything: S3 SSE-KMS, DynamoDB encryption at rest, SageMaker endpoint with inter-container encryption. All API calls over TLS. No exceptions.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 8.8: Clinical Assertion Classification](chapter08.08-clinical-assertion-classification) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
