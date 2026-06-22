# Recipe 8.9: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 8.9. It shows one way you could translate temporal relationship extraction concepts into working Python code. It is not production-ready. The temporal expression parser is rule-based and covers common clinical patterns but not all of them, the relation classifier is simulated via a SageMaker endpoint call pattern, and the graph construction uses basic transitivity without full Allen's interval algebra. Think of it as a sketch: useful for understanding the shape of the solution, not something you'd deploy against a live clinical NLP pipeline on Monday morning. Consider it a starting point, not a destination.
>
> This recipe uses Amazon Comprehend Medical for entity/event detection, a custom SageMaker endpoint for temporal relation classification, and DynamoDB for timeline storage. The pipeline follows the six-step architecture from the main recipe: preprocess, detect temporal entities, generate candidate pairs, classify relations, build graph, and generate timeline.

---

## Setup

You'll need the AWS SDK for Python and a few standard libraries:

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

Everything that's really configuration lives up front. The temporal patterns, signal words, and thresholds are the pieces that change between institutions. Your neurologists write differently than your surgeons, and both write differently than the training corpus that produced these defaults.

```python
import json
import logging
import re
import datetime
from datetime import timezone, timedelta
from decimal import Decimal
from collections import defaultdict

import boto3
from botocore.config import Config

# Structured logging. Never log PHI (entity text, patient IDs, note content).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry configuration for AWS API calls under load.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# Module-level clients reused across Lambda invocations.
comprehend_medical_client = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
sagemaker_runtime_client = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb")

# ---------- Temporal Relationship Labels ----------

# The relation types our classifier predicts.
# In practice most systems collapse the TimeML set into these four plus NONE.
TEMPORAL_RELATIONS = ["BEFORE", "AFTER", "OVERLAP", "CONTAINS", "NONE"]

# ---------- Temporal Expression Patterns ----------

# Clinical-specific temporal patterns that general NLP tools miss.
# Each pattern maps to a function that resolves the match to a date offset.
# These cover the most common clinical temporal conventions.

CLINICAL_TEMPORAL_PATTERNS = [
    # POD#N: Postoperative Day N (e.g., "POD#2", "POD 3", "POD#1")
    (r"POD\s*#?\s*(\d+)", "pod"),
    # HD#N: Hospital Day N (e.g., "HD3", "HD 5", "hospital day 7")
    (r"(?:HD|hospital\s+day)\s*#?\s*(\d+)", "hospital_day"),
    # DOL#N: Day of Life (neonates)
    (r"DOL\s*#?\s*(\d+)", "day_of_life"),
    # T+N: Days post-transplant
    (r"T\s*\+\s*(\d+)", "transplant_day"),
    # "N days/hours/weeks ago" or "N days/hours/weeks later"
    (r"(\d+)\s+(day|hour|week|month)s?\s+(ago|later|after|before|prior)", "relative"),
    # "postoperatively" / "preoperatively"
    (r"(pre|post)\s*-?\s*operatively", "perioperative"),
    # Explicit dates: Month Day, Year or MM/DD/YYYY
    (r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s*(\d{4})?", "month_day"),
    (r"(\d{1,2})/(\d{1,2})/(\d{2,4})", "slash_date"),
]

# Temporal signal words that indicate a relationship between two events.
# These are the lexical cues that make temporal ordering explicit.
TEMPORAL_SIGNALS = {
    "before": "BEFORE",
    "prior to": "BEFORE",
    "preceding": "BEFORE",
    "before the": "BEFORE",
    "after": "AFTER",
    "following": "AFTER",
    "subsequently": "AFTER",
    "then": "AFTER",
    "later": "AFTER",
    "post": "AFTER",
    "during": "OVERLAP",
    "while": "OVERLAP",
    "at the same time": "OVERLAP",
    "concurrent": "OVERLAP",
    "throughout": "CONTAINS",
    "during the course of": "CONTAINS",
}

# ---------- Section Temporal Context ----------

# Clinical note sections carry implicit temporal semantics.
# Events in "Past Medical History" are historical; events in "Assessment" are current.
SECTION_TEMPORAL_CONTEXT = {
    "history of present illness": "NARRATIVE",  # past-to-present story
    "hpi": "NARRATIVE",
    "past medical history": "HISTORICAL",
    "pmh": "HISTORICAL",
    "past surgical history": "HISTORICAL",
    "psh": "HISTORICAL",
    "family history": "HISTORICAL",
    "social history": "HISTORICAL",
    "assessment": "CURRENT",
    "assessment and plan": "CURRENT",
    "plan": "FUTURE",
    "discharge instructions": "FUTURE",
    "hospital course": "NARRATIVE",
}

# ---------- Thresholds ----------

# Relation classification confidence threshold.
# Below this, the relation is excluded from the temporal graph.
RELATION_CONFIDENCE_THRESHOLD = 0.70

# Entity detection confidence threshold.
ENTITY_CONFIDENCE_THRESHOLD = 0.75

# Maximum sentence distance for candidate pair generation.
# Pairs farther apart than this are unlikely to have a direct temporal relationship.
MAX_SENTENCE_DISTANCE = 3

# SageMaker endpoint for temporal relation classification.
SAGEMAKER_ENDPOINT_NAME = "temporal-relation-classifier"

# DynamoDB table for patient timelines.
TIMELINE_TABLE_NAME = "patient-timelines"
```

---

## Synthetic Clinical Note for Testing

Before we get into the pipeline steps, here's a synthetic discharge summary we'll use to exercise the code. This covers the patterns the main recipe discusses: explicit dates, relative expressions, clinical temporal conventions, and implicit ordering.

```python
# A synthetic discharge summary designed to exercise temporal extraction patterns.
# This is NOT real patient data. It contains explicit dates, relative references,
# clinical temporal conventions (POD#1), and implicit ordering.

SAMPLE_NOTE = """
DISCHARGE SUMMARY

Patient: [SYNTHETIC]
Admission Date: March 3, 2024
Discharge Date: March 7, 2024
Attending: Dr. Smith

HISTORY OF PRESENT ILLNESS:
Patient is a 58-year-old male who presented to the ED on March 3 with acute
right upper quadrant pain radiating to the back. Pain began approximately
2 days prior to admission. CT abdomen performed in the ED showed acute
cholecystitis with gallbladder wall thickening. Patient was admitted and
started on IV piperacillin-tazobactam.

HOSPITAL COURSE:
HD1: Patient admitted, NPO, IV antibiotics started. Pain 7/10.
HD2: Pain improved to 4/10. WBC trending down. Surgical consult obtained.
HD3: Pain further improved after 48 hours of antibiotics. Cleared for surgery.
HD4 (March 6): Laparoscopic cholecystectomy performed without complication.
Operative time 45 minutes. EBL minimal.
POD#1: Patient tolerating clear liquids. Pain well controlled with oral
analgesics. Ambulating independently.

DISCHARGE:
Patient discharged home on POD#1 in stable condition. Follow-up with surgery
in 2 weeks.

MEDICATIONS AT DISCHARGE:
1. Acetaminophen 650mg q6h PRN pain
2. Ibuprofen 400mg q8h PRN pain (started postoperatively)

PAST MEDICAL HISTORY:
- Hypertension (diagnosed 2015)
- Type 2 diabetes (diagnosed 2018)
- Appendectomy (2001)
"""

SAMPLE_METADATA = {
    "patient_id": "PAT-SYNTH-88431",
    "document_id": "NOTE-2024-03-07-001",
    "authored_datetime": "2024-03-07T14:30:00Z",
    "encounter_type": "inpatient",
}
```

---

## Step 1: Preprocess and Segment the Clinical Note

*The pseudocode calls this `preprocess_note(note_text, document_metadata)`. It identifies the document timestamp (anchor for relative expressions), segments by section, and splits into sentences. Without this step, "two days ago" has no anchor point and section-based temporal context is lost.*

```python
def parse_doc_time(authored_datetime_str):
    """
    Parse the document authored timestamp into a Python datetime object.
    This is the anchor for all relative temporal expressions in the note.

    Clinical notes are often authored hours after events occur (batch charting).
    The authored timestamp, not the encounter date, is the correct anchor for
    expressions like "yesterday" or "two days ago."
    """
    # Handle ISO 8601 with Z suffix or timezone offset.
    if authored_datetime_str.endswith("Z"):
        authored_datetime_str = authored_datetime_str[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(authored_datetime_str)

def segment_sections(note_text):
    """
    Split a clinical note into sections based on header patterns.

    Clinical section headers are typically: all-caps lines, lines ending with colon,
    or short lines that match known section names. Each section carries implicit
    temporal context (historical vs. current vs. future).
    """
    sections = []
    current_header = "UNKNOWN"
    current_content_lines = []

    for line in note_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        # Detect section headers: all-caps ending with colon, or known header names.
        is_header = False
        if stripped.endswith(":") and len(stripped) < 60:
            # Could be a section header. Check if it's mostly uppercase or a known name.
            header_text = stripped.rstrip(":").strip()
            if header_text.isupper() or header_text.lower() in SECTION_TEMPORAL_CONTEXT:
                is_header = True

        if is_header:
            # Save the previous section if it has content.
            if current_content_lines:
                temporal_ctx = SECTION_TEMPORAL_CONTEXT.get(
                    current_header.lower().rstrip(":"), "UNKNOWN"
                )
                sections.append({
                    "header": current_header,
                    "content": "\n".join(current_content_lines),
                    "temporal_context": temporal_ctx,
                })
            current_header = stripped.rstrip(":")
            current_content_lines = []
        else:
            current_content_lines.append(stripped)

    # Don't forget the last section.
    if current_content_lines:
        temporal_ctx = SECTION_TEMPORAL_CONTEXT.get(
            current_header.lower().rstrip(":"), "UNKNOWN"
        )
        sections.append({
            "header": current_header,
            "content": "\n".join(current_content_lines),
            "temporal_context": temporal_ctx,
        })

    return sections

def split_sentences(text):
    """
    Split clinical text into sentences.

    Clinical text has non-standard sentence boundaries: abbreviations with periods
    (e.g., "pt."), numbered lists, lab values with decimals, and dosages.
    This is a simplified splitter. Production systems use clinical-specific
    sentence tokenizers (like those in spaCy with clinical models).
    """
    # Split on period followed by space and uppercase, or newlines.
    # This is intentionally simple. A real system uses a trained tokenizer.
    sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', text)
    # Also split on newlines that start new thoughts.
    expanded = []
    for sent in sentences:
        sub_sents = [s.strip() for s in sent.split("\n") if s.strip()]
        expanded.extend(sub_sents)
    return expanded

def preprocess_note(note_text, document_metadata):
    """
    Step 1: Preprocess and segment the clinical note.

    Returns structured data needed by all downstream steps:
    the document timestamp, sections with temporal context, and sentence list.
    """
    doc_time = parse_doc_time(document_metadata["authored_datetime"])
    sections = segment_sections(note_text)
    sentences = split_sentences(note_text)

    logger.info("Preprocessed note: %d sections, %d sentences", len(sections), len(sentences))

    return {
        "doc_time": doc_time,
        "sections": sections,
        "sentences": sentences,
        "full_text": note_text,
        "metadata": document_metadata,
    }
```

---

## Step 2: Detect Clinical Events and Temporal Expressions

*The pseudocode calls this `detect_temporal_entities(preprocessed_note)`. This step uses Comprehend Medical for clinical event detection and a rule-based parser for temporal expression recognition. The rule-based parser handles the clinical-specific patterns (POD#2, HD5, relative expressions) that general-purpose temporal parsers miss.*

```python
def detect_events_with_comprehend(note_text):
    """
    Call Amazon Comprehend Medical to detect clinical entities that represent events.

    Events are things that happened at a point in time: diagnoses, procedures,
    medication starts/stops, symptoms, tests. Static attributes (body parts,
    anatomical locations) are not events and get filtered out.

    Comprehend Medical's DetectEntitiesV2 returns entities with categories
    like MEDICAL_CONDITION, MEDICATION, TEST_TREATMENT_PROCEDURE, and attributes
    including temporal traits (PAST_HISTORY, OCCURRENCE).
    """
    # Comprehend Medical has a 20,000 character limit per request.
    # For this example, we truncate. Production systems split at sentence boundaries.
    text_to_analyze = note_text[:20000]

    response = comprehend_medical_client.detect_entities_v2(Text=text_to_analyze)

    events = []
    for entity in response.get("Entities", []):
        # Filter by confidence.
        if entity.get("Score", 0) < ENTITY_CONFIDENCE_THRESHOLD:
            continue

        # Filter to event-like categories.
        # MEDICAL_CONDITION, TEST_TREATMENT_PROCEDURE, and MEDICATION are events.
        # ANATOMY and PROTECTED_HEALTH_INFORMATION are not.
        category = entity.get("Category", "")
        if category not in ("MEDICAL_CONDITION", "TEST_TREATMENT_PROCEDURE", "MEDICATION"):
            continue

        # Extract temporal traits if present.
        # Comprehend Medical detects: PAST_HISTORY, OCCURRENCE, FUTURE, NEGATION.
        traits = [t["Name"] for t in entity.get("Traits", [])]

        events.append({
            "id": f"EVT-{entity['BeginOffset']:05d}",
            "text": entity["Text"],
            "category": category,
            "type": entity.get("Type", "UNKNOWN"),
            "begin_offset": entity["BeginOffset"],
            "end_offset": entity["EndOffset"],
            "confidence": entity["Score"],
            "traits": traits,
            "entity_type": "EVENT",
        })

    logger.info("Detected %d clinical events via Comprehend Medical", len(events))
    return events

def recognize_temporal_expressions(note_text, doc_time):
    """
    Rule-based temporal expression recognition for clinical text.

    This covers the clinical-specific patterns that general NLP tools
    (HeidelTime, SUTime) don't handle out of the box: POD#N, HD#N,
    relative expressions anchored to document time, and perioperative markers.

    Each recognized expression gets normalized to an ISO 8601 date
    (or date range) anchored to the document creation timestamp.
    """
    temporal_exprs = []
    expr_id_counter = 0

    for pattern_str, pattern_type in CLINICAL_TEMPORAL_PATTERNS:
        for match in re.finditer(pattern_str, note_text, re.IGNORECASE):
            expr_id_counter += 1
            raw_text = match.group(0)
            begin_offset = match.start()
            end_offset = match.end()

            # Normalize based on pattern type.
            normalized = normalize_temporal_expression(
                match, pattern_type, doc_time, note_text
            )

            temporal_exprs.append({
                "id": f"TIMEX-{expr_id_counter:03d}",
                "text": raw_text,
                "begin_offset": begin_offset,
                "end_offset": end_offset,
                "pattern_type": pattern_type,
                "normalized": normalized,
                "entity_type": "TEMPORAL_EXPRESSION",
            })

    logger.info("Recognized %d temporal expressions", len(temporal_exprs))
    return temporal_exprs

def normalize_temporal_expression(match, pattern_type, doc_time, full_text):
    """
    Normalize a temporal expression to an ISO 8601 date or date range.

    This is the core of temporal anchoring: turning "2 days ago" or "POD#1"
    into an actual calendar date that can be placed on a timeline.
    """
    try:
        if pattern_type == "month_day":
            month_name = match.group(1)
            day = int(match.group(2))
            year = int(match.group(3)) if match.group(3) else doc_time.year
            month_num = datetime.datetime.strptime(month_name, "%B").month
            return datetime.datetime(year, month_num, day, tzinfo=timezone.utc).isoformat()

        elif pattern_type == "slash_date":
            month = int(match.group(1))
            day = int(match.group(2))
            year = int(match.group(3))
            if year < 100:
                year += 2000
            return datetime.datetime(year, month, day, tzinfo=timezone.utc).isoformat()

        elif pattern_type == "relative":
            quantity = int(match.group(1))
            unit = match.group(2).lower()
            direction = match.group(3).lower()

            delta_map = {
                "day": timedelta(days=quantity),
                "hour": timedelta(hours=quantity),
                "week": timedelta(weeks=quantity),
                "month": timedelta(days=quantity * 30),  # approximate
            }
            delta = delta_map.get(unit, timedelta(days=quantity))

            if direction in ("ago", "before", "prior"):
                resolved = doc_time - delta
            else:
                resolved = doc_time + delta
            return resolved.isoformat()

        elif pattern_type == "pod":
            pod_num = int(match.group(1))
            # POD anchors to a surgery date. In a real system, you'd look up
            # the surgery date from the note. Here we search for it in context.
            surgery_date = find_surgery_date_in_context(full_text, doc_time)
            if surgery_date:
                resolved = surgery_date + timedelta(days=pod_num)
                return resolved.isoformat()
            return f"POD+{pod_num}"  # unresolved, relative only

        elif pattern_type == "hospital_day":
            hd_num = int(match.group(1))
            # Anchor to admission date. Search note for admission date.
            admission_date = find_admission_date_in_context(full_text, doc_time)
            if admission_date:
                resolved = admission_date + timedelta(days=hd_num - 1)
                return resolved.isoformat()
            return f"HD+{hd_num}"

        elif pattern_type == "perioperative":
            prefix = match.group(1).lower()
            # "postoperatively" = after surgery, "preoperatively" = before surgery
            return f"{'POST' if prefix == 'post' else 'PRE'}_SURGERY"

        elif pattern_type == "day_of_life":
            dol = int(match.group(1))
            return f"DOL+{dol}"

        elif pattern_type == "transplant_day":
            t_day = int(match.group(1))
            return f"T+{t_day}"

    except (ValueError, TypeError):
        pass

    return None  # Could not normalize

def find_surgery_date_in_context(note_text, doc_time):
    """
    Search the note for an explicit surgery date to anchor POD references.
    Looks for patterns like "cholecystectomy performed on March 6" or
    "surgery on 3/6/2024".
    """
    # Look for "performed on [date]" or "surgery on [date]"
    date_pattern = r"(?:performed|surgery|operation)\s+(?:on\s+)?(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s*(\d{4})?"
    match = re.search(date_pattern, note_text, re.IGNORECASE)
    if match:
        month_name = match.group(1)
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else doc_time.year
        month_num = datetime.datetime.strptime(month_name, "%B").month
        return datetime.datetime(year, month_num, day, tzinfo=timezone.utc)
    return None

def find_admission_date_in_context(note_text, doc_time):
    """
    Search the note for an explicit admission date to anchor HD references.
    Looks for patterns like "Admission Date: March 3, 2024" or
    "admitted on 3/3/2024".
    """
    # Look for "Admission Date:" header pattern.
    pattern = r"Admission\s+Date:\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),?\s*(\d{4})?"
    match = re.search(pattern, note_text, re.IGNORECASE)
    if match:
        month_name = match.group(1)
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else doc_time.year
        month_num = datetime.datetime.strptime(month_name, "%B").month
        return datetime.datetime(year, month_num, day, tzinfo=timezone.utc)
    return None

def detect_temporal_entities(preprocessed_note):
    """
    Step 2: Detect clinical events and temporal expressions.

    Combines Comprehend Medical entity detection (for clinical events)
    with rule-based temporal expression recognition (for time references).
    """
    events = detect_events_with_comprehend(preprocessed_note["full_text"])
    temporal_expressions = recognize_temporal_expressions(
        preprocessed_note["full_text"],
        preprocessed_note["doc_time"],
    )

    return {
        "events": events,
        "temporal_expressions": temporal_expressions,
    }
```

---

## Step 3: Generate Candidate Pairs

*The pseudocode calls this `generate_candidate_pairs(events, temporal_expressions, sentences)`. With N entities, the full pairwise space is N*(N-1)/2. For a note with 50 entities, that's 1,225 pairs. Most are irrelevant. This step applies heuristics to select only pairs likely to have a meaningful temporal relationship, reducing classification workload by 80-90%.*

```python
def find_sentence_index(offset, sentences, full_text):
    """
    Given a character offset into the full text, find which sentence it belongs to.
    Returns the sentence index (0-based).
    """
    current_pos = 0
    for idx, sent in enumerate(sentences):
        sent_start = full_text.find(sent, current_pos)
        if sent_start == -1:
            continue
        sent_end = sent_start + len(sent)
        if sent_start <= offset < sent_end:
            return idx
        current_pos = sent_end
    return -1

def find_temporal_signal_between(entity_a, entity_b, full_text):
    """
    Check if there's a temporal signal word between two entities.
    If found, return the signal word and its implied relation.
    """
    # Get the text between the two entities.
    start = min(entity_a["end_offset"], entity_b["end_offset"])
    end = max(entity_a["begin_offset"], entity_b["begin_offset"])

    if end <= start:
        return None

    between_text = full_text[start:end].lower()

    for signal, relation in TEMPORAL_SIGNALS.items():
        if signal in between_text:
            return {"signal": signal, "implied_relation": relation}

    return None

def generate_candidate_pairs(entities, sentences, full_text):
    """
    Step 3: Generate candidate entity pairs for temporal relation classification.

    Applies filtering heuristics to reduce the pairwise space:
    1. Same-sentence pairs (highest probability of explicit relationship)
    2. Adjacent-sentence pairs (narrative flow implies ordering)
    3. Pairs with temporal signal words between them
    4. Event-to-nearest-temporal-expression pairs

    Returns a list of candidate pairs with their heuristic source.
    """
    all_entities = entities["events"] + entities["temporal_expressions"]
    candidates = []
    seen_pairs = set()

    # Precompute sentence indices for all entities.
    for ent in all_entities:
        ent["sentence_idx"] = find_sentence_index(
            ent["begin_offset"], sentences, full_text
        )

    for i, entity_a in enumerate(all_entities):
        for j, entity_b in enumerate(all_entities):
            if i >= j:
                continue  # avoid duplicates and self-pairs

            pair_key = (entity_a["id"], entity_b["id"])
            if pair_key in seen_pairs:
                continue

            sent_a = entity_a.get("sentence_idx", -1)
            sent_b = entity_b.get("sentence_idx", -1)
            sentence_distance = abs(sent_a - sent_b) if sent_a >= 0 and sent_b >= 0 else 999

            # Heuristic 1: Same sentence.
            if sentence_distance == 0:
                candidates.append((entity_a, entity_b, "same_sentence"))
                seen_pairs.add(pair_key)
                continue

            # Heuristic 2: Adjacent sentences (within MAX_SENTENCE_DISTANCE).
            if sentence_distance <= MAX_SENTENCE_DISTANCE:
                candidates.append((entity_a, entity_b, "adjacent"))
                seen_pairs.add(pair_key)
                continue

            # Heuristic 3: Temporal signal word between them.
            signal = find_temporal_signal_between(entity_a, entity_b, full_text)
            if signal:
                candidates.append((entity_a, entity_b, "signal_connected"))
                seen_pairs.add(pair_key)
                continue

            # Heuristic 4: Event paired with nearest temporal expression.
            if (entity_a["entity_type"] == "EVENT" and
                entity_b["entity_type"] == "TEMPORAL_EXPRESSION"):
                if sentence_distance <= MAX_SENTENCE_DISTANCE + 1:
                    candidates.append((entity_a, entity_b, "nearest_anchor"))
                    seen_pairs.add(pair_key)
                    continue

            # Heuristic 5: Section-anchored pairs (cross-section relationships).
            # Events in different sections that share a temporal expression or are
            # both anchored to the same clinical episode (e.g., HPI events linked to
            # Hospital Course events in discharge summaries).
            if (entity_a.get("section") and entity_b.get("section") and
                entity_a["section"] != entity_b["section"]):
                if _shared_temporal_anchor(entity_a, entity_b, all_entities, full_text):
                    candidates.append((entity_a, entity_b, "section_anchored"))
                    seen_pairs.add(pair_key)

    logger.info(
        "Generated %d candidate pairs from %d entities",
        len(candidates), len(all_entities)
    )
    return candidates


def _shared_temporal_anchor(entity_a, entity_b, all_entities, full_text):
    """
    Check if two entities from different sections share a temporal anchor.

    Two events share an anchor if they are both within MAX_SENTENCE_DISTANCE
    of the same temporal expression, or if they reference the same clinical
    episode marker (e.g., same admission date, same procedure reference).
    """
    # Find temporal expressions near each entity.
    temporal_exprs = [e for e in all_entities if e["entity_type"] == "TEMPORAL_EXPRESSION"]
    a_offset = entity_a["begin_offset"]
    b_offset = entity_b["begin_offset"]

    for texpr in temporal_exprs:
        t_offset = texpr["begin_offset"]
        # If the temporal expression is within 500 characters of both entities,
        # they likely share a temporal anchor.
        if abs(t_offset - a_offset) < 500 and abs(t_offset - b_offset) < 500:
            return True

    return False
```

---

## Step 4: Classify Temporal Relations

*The pseudocode calls this `classify_relations(candidate_pairs, full_text, sections)`. For each candidate pair, we build a context window and send it to the trained temporal relation classifier. The classifier predicts BEFORE, AFTER, OVERLAP, CONTAINS, or NONE with a confidence score. Low-confidence predictions are excluded from the final graph.*

```python
def build_context_window(entity_a, entity_b, full_text, window_chars=300):
    """
    Build a text context window around an entity pair for classification.

    The context includes the text of both entities, surrounding text, and
    special markers to indicate which spans are the target entities.
    The classifier needs this context to determine the temporal relationship.
    """
    # Find the broader span encompassing both entities.
    start = min(entity_a["begin_offset"], entity_b["begin_offset"])
    end = max(entity_a["end_offset"], entity_b["end_offset"])

    # Expand the window for context.
    context_start = max(0, start - window_chars)
    context_end = min(len(full_text), end + window_chars)

    context = full_text[context_start:context_end]

    # Mark the entities in the context for the classifier.
    # Using the [E1]...[/E1] and [E2]...[/E2] convention from relation extraction literature.
    # Adjust offsets relative to context window.
    a_start_rel = entity_a["begin_offset"] - context_start
    a_end_rel = entity_a["end_offset"] - context_start
    b_start_rel = entity_b["begin_offset"] - context_start
    b_end_rel = entity_b["end_offset"] - context_start

    # Insert markers (order matters: insert from end to start to preserve offsets).
    marked = list(context)
    insertions = sorted([
        (a_start_rel, "[E1]"),
        (a_end_rel, "[/E1]"),
        (b_start_rel, "[E2]"),
        (b_end_rel, "[/E2]"),
    ], key=lambda x: x[0], reverse=True)

    for pos, marker in insertions:
        if 0 <= pos <= len(marked):
            marked.insert(pos, marker)

    return "".join(marked)

def classify_with_sagemaker(formatted_input):
    """
    Call the SageMaker endpoint to classify the temporal relation between two entities.

    The main recipe's architecture section discusses Comprehend Custom Classification
    as one option. This example uses a SageMaker endpoint because temporal relation
    classification requires sequence pair input with entity markers ([E1]...[/E1]),
    which maps more naturally to a custom-hosted transformer model than to
    Comprehend's document classification API. Both approaches are valid.

    The endpoint hosts a fine-tuned model (e.g., ClinicalBERT) trained on temporal
    relation annotated data. It accepts marked-up text and returns a relation
    label with confidence score.
    """
    payload = json.dumps({"text": formatted_input})

    response = sagemaker_runtime_client.invoke_endpoint(
        EndpointName=SAGEMAKER_ENDPOINT_NAME,
        ContentType="application/json",
        Body=payload,
    )

    result = json.loads(response["Body"].read().decode("utf-8"))
    # Expected response: {"label": "BEFORE", "confidence": 0.87}
    return result

def classify_with_rules(entity_a, entity_b, full_text):
    """
    Rule-based temporal relation classification for cases with explicit signals.

    Before calling the ML model, check for obvious cases:
    1. Explicit temporal signal word between entities
    2. Entity anchored to a resolved temporal expression
    3. Narrative ordering within the same section

    Returns a prediction dict or None if rules don't apply.
    """
    # Check for temporal signal words between the entities.
    signal = find_temporal_signal_between(entity_a, entity_b, full_text)
    if signal:
        # Determine direction: is entity_a before or after the signal word?
        if entity_a["begin_offset"] < entity_b["begin_offset"]:
            relation = signal["implied_relation"]
        else:
            # Entities are in reverse order relative to signal.
            # Flip the relation.
            flip = {"BEFORE": "AFTER", "AFTER": "BEFORE",
                    "OVERLAP": "OVERLAP", "CONTAINS": "CONTAINS"}
            relation = flip.get(signal["implied_relation"], signal["implied_relation"])

        return {"label": relation, "confidence": 0.85, "source": "rule_signal"}

    # Check if both entities have resolved temporal expressions we can compare.
    if (entity_a.get("entity_type") == "TEMPORAL_EXPRESSION" and
        entity_b.get("entity_type") == "TEMPORAL_EXPRESSION"):
        norm_a = entity_a.get("normalized")
        norm_b = entity_b.get("normalized")
        if norm_a and norm_b and "T" in str(norm_a) and "T" in str(norm_b):
            try:
                dt_a = datetime.datetime.fromisoformat(norm_a)
                dt_b = datetime.datetime.fromisoformat(norm_b)
                if dt_a < dt_b:
                    return {"label": "BEFORE", "confidence": 0.95, "source": "rule_date"}
                elif dt_a > dt_b:
                    return {"label": "AFTER", "confidence": 0.95, "source": "rule_date"}
                else:
                    return {"label": "OVERLAP", "confidence": 0.90, "source": "rule_date"}
            except (ValueError, TypeError):
                pass

    return None  # No rule applies; defer to ML model.

def classify_relations(candidate_pairs, full_text, sections):
    """
    Step 4: Classify temporal relationships for all candidate pairs.

    Uses a hybrid approach: rule-based classification for obvious cases
    (explicit signal words, resolved dates), ML model for ambiguous cases.
    """
    classified = []

    for entity_a, entity_b, pair_type in candidate_pairs:
        # Try rule-based classification first (fast, high precision).
        rule_result = classify_with_rules(entity_a, entity_b, full_text)

        if rule_result and rule_result["confidence"] >= RELATION_CONFIDENCE_THRESHOLD:
            prediction = rule_result
        else:
            # Fall back to ML model for ambiguous cases.
            context_window = build_context_window(entity_a, entity_b, full_text)
            prediction = classify_with_sagemaker(context_window)
            prediction["source"] = "ml_model"

        # Apply confidence threshold.
        if prediction.get("confidence", 0) >= RELATION_CONFIDENCE_THRESHOLD:
            if prediction["label"] != "NONE":
                classified.append({
                    "entity_a": entity_a,
                    "entity_b": entity_b,
                    "relation": prediction["label"],
                    "confidence": prediction["confidence"],
                    "source": prediction.get("source", "unknown"),
                    "pair_type": pair_type,
                })

    logger.info(
        "Classified %d temporal relations (from %d candidates)",
        len(classified), len(candidate_pairs)
    )
    return classified
```

---

## Step 5: Build the Temporal Graph and Propagate Constraints

*The pseudocode calls this `build_temporal_graph(classified_relations, events, temporal_expressions)`. This step assembles classified relations into a directed graph, applies transitivity to infer additional relations, and detects/resolves inconsistencies (cycles). If A BEFORE B and B BEFORE C, we can infer A BEFORE C without the classifier having to see that pair directly.*

```python
def build_temporal_graph(classified_relations, events, temporal_expressions):
    """
    Step 5: Build a temporal graph from classified relations.

    Nodes are events and temporal expressions.
    Edges are temporal relations with confidence scores.

    After building the initial graph from classifier output, apply:
    1. Transitive closure (if A BEFORE B and B BEFORE C, infer A BEFORE C)
    2. Cycle detection (contradictions in the BEFORE/AFTER subgraph)
    3. Cycle resolution (remove lowest-confidence edge)
    """
    # Build adjacency representation.
    # nodes[id] = entity data
    # edges = list of (from_id, to_id, relation, confidence)
    nodes = {}
    edges = []

    for event in events:
        nodes[event["id"]] = event
    for texpr in temporal_expressions:
        nodes[texpr["id"]] = texpr

    for rel in classified_relations:
        edges.append({
            "from": rel["entity_a"]["id"],
            "to": rel["entity_b"]["id"],
            "relation": rel["relation"],
            "confidence": rel["confidence"],
            "inferred": False,
        })

    # Transitive closure for BEFORE relations.
    # If A BEFORE B and B BEFORE C, add A BEFORE C.
    before_edges = [e for e in edges if e["relation"] == "BEFORE"]
    inferred_edges = []

    # Build a quick adjacency map for BEFORE relations.
    before_map = defaultdict(set)  # from_id -> set of to_ids
    for e in before_edges:
        before_map[e["from"]].add(e["to"])

    # One pass of transitivity (not full closure, but catches immediate chains).
    for a_id, b_ids in before_map.items():
        for b_id in list(b_ids):
            for c_id in before_map.get(b_id, set()):
                if c_id != a_id and c_id not in before_map[a_id]:
                    inferred_edges.append({
                        "from": a_id,
                        "to": c_id,
                        "relation": "BEFORE",
                        "confidence": 0.60,  # lower confidence for inferred relations
                        "inferred": True,
                    })

    edges.extend(inferred_edges)
    logger.info("Inferred %d transitive relations", len(inferred_edges))

    # Cycle detection in the BEFORE/AFTER subgraph.
    # A cycle means contradictory temporal ordering (A before B before C before A).
    removed_edges = detect_and_resolve_cycles(edges)

    # Remove flagged edges.
    edges = [e for e in edges if e not in removed_edges]

    return {
        "nodes": nodes,
        "edges": edges,
        "removed_for_consistency": removed_edges,
    }

def detect_and_resolve_cycles(edges):
    """
    Detect cycles in the BEFORE/AFTER subgraph and remove the weakest edge.

    Uses a simple DFS-based cycle detection. In production, you'd want
    a more sophisticated approach that considers the entire graph structure,
    but this handles the common case of a single contradictory classification.
    """
    # Build directed adjacency for BEFORE relations only.
    # AFTER(A,B) is equivalent to BEFORE(B,A) for cycle detection.
    adj = defaultdict(list)
    edge_lookup = {}

    for edge in edges:
        if edge["relation"] == "BEFORE":
            adj[edge["from"]].append(edge["to"])
            edge_lookup[(edge["from"], edge["to"])] = edge
        elif edge["relation"] == "AFTER":
            adj[edge["to"]].append(edge["from"])
            edge_lookup[(edge["to"], edge["from"])] = edge

    # Simple cycle detection via DFS.
    visited = set()
    in_stack = set()
    removed = []

    def dfs(node, path):
        if node in in_stack:
            # Found a cycle. Remove the lowest-confidence edge in the cycle.
            cycle_start = path.index(node)
            cycle_path = path[cycle_start:]
            cycle_edges = []
            for k in range(len(cycle_path) - 1):
                key = (cycle_path[k], cycle_path[k + 1])
                if key in edge_lookup:
                    cycle_edges.append(edge_lookup[key])
            if cycle_edges:
                weakest = min(cycle_edges, key=lambda e: e["confidence"])
                removed.append(weakest)
                logger.info("Cycle detected, removing edge: %s -> %s (conf %.2f)",
                           weakest["from"], weakest["to"], weakest["confidence"])
            return

        if node in visited:
            return

        visited.add(node)
        in_stack.add(node)
        for neighbor in adj.get(node, []):
            dfs(neighbor, path + [neighbor])
        in_stack.discard(node)

    for node in adj:
        if node not in visited:
            dfs(node, [node])

    return removed
```

---

## Step 6: Generate the Patient Timeline

*The pseudocode calls this `generate_timeline(temporal_graph, doc_time)`. This flattens the temporal graph into a linear timeline. Events anchored to absolute dates get placed precisely. Events with only relative relationships get placed in order relative to their anchors. The output is what downstream systems consume: a chronological sequence of events with timestamps and confidence scores.*

```python
def generate_timeline(temporal_graph, preprocessed_note):
    """
    Step 6: Flatten the temporal graph into a patient timeline.

    Two passes:
    1. Anchor events with absolute timestamps (from resolved temporal expressions)
    2. Propagate timestamps to unanchored events using graph relationships
    """
    nodes = temporal_graph["nodes"]
    edges = temporal_graph["edges"]
    doc_time = preprocessed_note["doc_time"]

    # First pass: assign absolute timestamps where possible.
    # Events linked to resolved temporal expressions get precise timestamps.
    timestamps = {}  # node_id -> datetime
    directly_anchored = set()  # node_ids that got timestamps from resolved expressions

    # Temporal expressions that resolved to ISO dates already have timestamps.
    for node_id, node in nodes.items():
        if node.get("entity_type") == "TEMPORAL_EXPRESSION":
            normalized = node.get("normalized")
            if normalized and "T" in str(normalized):
                try:
                    timestamps[node_id] = datetime.datetime.fromisoformat(normalized)
                    directly_anchored.add(node_id)
                except (ValueError, TypeError):
                    pass

    # Propagate timestamps from temporal expressions to connected events.
    for edge in edges:
        if edge["relation"] in ("OVERLAP", "CONTAINS") and edge["to"] in timestamps:
            if edge["from"] not in timestamps:
                timestamps[edge["from"]] = timestamps[edge["to"]]
                directly_anchored.add(edge["from"])
        if edge["relation"] in ("OVERLAP", "CONTAINS") and edge["from"] in timestamps:
            if edge["to"] not in timestamps:
                timestamps[edge["to"]] = timestamps[edge["from"]]
                directly_anchored.add(edge["to"])

    # Second pass: infer timestamps for unanchored events using BEFORE/AFTER ordering.
    # Simple heuristic: if A BEFORE B and B has a timestamp, A gets timestamp - 12 hours.
    # These get marked INFERRED (not ABSOLUTE) because the timestamp is approximate.
    for edge in sorted(edges, key=lambda e: e["confidence"], reverse=True):
        if edge["relation"] == "BEFORE" and edge["to"] in timestamps:
            if edge["from"] not in timestamps:
                timestamps[edge["from"]] = timestamps[edge["to"]] - timedelta(hours=12)
        elif edge["relation"] == "AFTER" and edge["from"] in timestamps:
            if edge["to"] not in timestamps:
                timestamps[edge["to"]] = timestamps[edge["from"]] + timedelta(hours=12)

    # Build the timeline entries (events only, not raw temporal expressions).
    timeline = []
    for node_id, node in nodes.items():
        if node.get("entity_type") != "EVENT":
            continue

        ts = timestamps.get(node_id)
        if ts and node_id in directly_anchored:
            ts_type = "ABSOLUTE"
        elif ts:
            ts_type = "INFERRED"
        else:
            ts_type = "RELATIVE_ONLY"

        timeline.append({
            "event_id": node_id,
            "event_text": node["text"],
            "event_type": node.get("type", "UNKNOWN"),
            "timestamp": ts.isoformat() if ts else None,
            "timestamp_type": ts_type,
            "confidence": node.get("confidence", 0),
        })

    # Sort: events with timestamps first (chronologically), then unanchored events.
    timeline.sort(key=lambda e: (
        0 if e["timestamp"] else 1,
        e["timestamp"] or "",
    ))

    # Compute summary statistics.
    anchored_count = sum(1 for e in timeline if e["timestamp_type"] == "ABSOLUTE")
    inferred_count = sum(1 for e in timeline if e["timestamp_type"] == "INFERRED")

    result = {
        "patient_id": preprocessed_note["metadata"]["patient_id"],
        "document_id": preprocessed_note["metadata"]["document_id"],
        "doc_time": doc_time.isoformat(),
        "timeline": timeline,
        "event_count": len(timeline),
        "anchored_count": anchored_count,
        "inferred_count": inferred_count,
        "temporal_relations": [
            {
                "from": e["from"],
                "to": e["to"],
                "relation": e["relation"],
                "confidence": e["confidence"],
            }
            for e in edges if not e.get("inferred")
        ],
    }

    logger.info(
        "Generated timeline: %d events (%d anchored, %d inferred)",
        result["event_count"], result["anchored_count"], result["inferred_count"]
    )
    return result
```

---

## Storing the Timeline in DynamoDB

```python
def store_timeline(timeline_result):
    """
    Write the extracted timeline to DynamoDB for downstream consumption.

    Indexed by patient_id (partition key) and document_id (sort key) so you can
    query all timelines for a patient or retrieve a specific document's timeline.
    """
    table = dynamodb.Table(TIMELINE_TABLE_NAME)

    # DynamoDB requires Decimal for numeric values, not float.
    item = {
        "patient_id": timeline_result["patient_id"],
        "document_id": timeline_result["document_id"],
        "doc_time": timeline_result["doc_time"],
        "extraction_timestamp": datetime.datetime.now(timezone.utc).isoformat(),
        "event_count": timeline_result["event_count"],
        "anchored_count": timeline_result["anchored_count"],
        "inferred_count": timeline_result["inferred_count"],
        "timeline": json.loads(
            json.dumps(timeline_result["timeline"]),
        ),
        "temporal_relations": json.loads(
            json.dumps(timeline_result["temporal_relations"]),
        ),
    }

    # Convert any float values to Decimal for DynamoDB compatibility.
    item = convert_floats_to_decimal(item)

    table.put_item(Item=item)
    logger.info("Stored timeline for %s / %s", item["patient_id"], item["document_id"])
    return item

def convert_floats_to_decimal(obj):
    """
    Recursively convert float values to Decimal for DynamoDB.
    DynamoDB's put_item raises TypeError on raw Python floats.
    """
    if isinstance(obj, float):
        return Decimal(str(round(obj, 6)))
    elif isinstance(obj, dict):
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimal(item) for item in obj]
    return obj
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what your Lambda handler (or Step Functions task) would call.

```python
def extract_temporal_relationships(note_text, document_metadata):
    """
    Run the full temporal relationship extraction pipeline for one clinical note.

    This is the main entry point. In a Lambda deployment, your handler would
    parse the incoming event (S3 notification, SQS message, or API call),
    extract the note text and metadata, and call this function.

    Args:
        note_text: The raw clinical note text.
        document_metadata: Dict with patient_id, document_id, authored_datetime.

    Returns:
        The timeline result with events, timestamps, and temporal relations.
    """
    # Step 1: Preprocess and segment.
    logger.info("Step 1: Preprocessing note")
    preprocessed = preprocess_note(note_text, document_metadata)

    # Step 2: Detect clinical events and temporal expressions.
    logger.info("Step 2: Detecting temporal entities")
    entities = detect_temporal_entities(preprocessed)
    logger.info("  Events: %d, Temporal expressions: %d",
               len(entities["events"]), len(entities["temporal_expressions"]))

    # Step 3: Generate candidate pairs using heuristic filtering.
    logger.info("Step 3: Generating candidate pairs")
    candidates = generate_candidate_pairs(
        entities, preprocessed["sentences"], preprocessed["full_text"]
    )

    # Step 4: Classify temporal relations for each candidate pair.
    logger.info("Step 4: Classifying temporal relations")
    classified = classify_relations(
        candidates, preprocessed["full_text"], preprocessed["sections"]
    )

    # Step 5: Build temporal graph with constraint propagation.
    logger.info("Step 5: Building temporal graph")
    graph = build_temporal_graph(
        classified, entities["events"], entities["temporal_expressions"]
    )

    # Step 6: Generate the patient timeline.
    logger.info("Step 6: Generating timeline")
    timeline = generate_timeline(graph, preprocessed)

    # Store the result.
    logger.info("Storing timeline in DynamoDB")
    store_timeline(timeline)

    logger.info("Done. %d events on timeline.", timeline["event_count"])
    return timeline

# Example: run the pipeline against the synthetic note.
if __name__ == "__main__":
    result = extract_temporal_relationships(SAMPLE_NOTE, SAMPLE_METADATA)
    print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

This example works: run it with a deployed SageMaker endpoint and valid Comprehend Medical credentials, and it will extract temporal entities, classify relationships, build a graph, and produce a structured timeline. But there's a meaningful distance between "works in a script" and "runs at scale against a clinical data warehouse." Here's where that gap lives.

**The SageMaker model doesn't exist yet.** This code calls a SageMaker endpoint named `temporal-relation-classifier`, but training and deploying that model is a significant project. You need: (1) annotated training data (the THYME corpus requires a data use agreement from Mayo Clinic/University of Colorado; institution-specific annotations are better but expensive), (2) a fine-tuning pipeline (ClinicalBERT or BioBERT as base, with entity marker tokens added to the vocabulary), and (3) a deployment configuration with auto-scaling. The rule-based layer works without the model but covers only cases with explicit signal words (roughly 30-40% of temporal relationships in a typical note).

**Temporal expression recognition is incomplete.** The regex-based parser here covers the most common clinical patterns (POD#N, HD#N, relative expressions, explicit dates). Production systems need to handle: medication frequencies ("BID," "q4h," which are temporal expressions), fuzzy expressions ("a few weeks ago," "recently"), ranged expressions ("over the past 3-5 days"), and context-dependent expressions ("this morning" depends on when the note was authored, which depends on batch charting lag). HeidelTime with clinical extensions is the standard tool for this, but requires a JVM dependency.

**Comprehend Medical's 20,000-character limit.** The example truncates silently. A production pipeline splits long notes at sentence boundaries, processes each chunk separately, and reconciles entities that might span chunk boundaries. ICU notes and operative reports regularly exceed 20,000 characters.

**Candidate pair generation heuristics need tuning.** The MAX_SENTENCE_DISTANCE of 3 is reasonable for discharge summaries but may be too restrictive for long-form consult notes where temporal relationships span paragraphs. Conversely, it may be too permissive for structured lab reports. Tune these heuristics per document type.

**Graph construction is simplified.** This example does one pass of transitivity. A production system applies full transitive closure (iterating until no new edges are added) and uses Allen's interval algebra for richer constraint propagation. It should also weight inferred edges by the confidence path that generated them (confidence of A BEFORE B * confidence of B BEFORE C = confidence of inferred A BEFORE C).

**Cross-document timeline merging.** This pipeline processes one note at a time. A patient's full timeline spans hundreds of notes. Merging timelines from multiple notes requires: cross-document event coreference resolution (is "the knee pain" in two notes the same episode?), conflict resolution (two notes disagree on when something happened), and incremental graph construction (adding new notes to an existing timeline without reprocessing everything). This is arguably a separate system built on top of single-document extraction.

**Handling contradictory information.** Clinical notes contain corrections, amendments, and outright contradictions. "Patient reports no allergies" in one note and "PCN allergy noted" in another. The timeline system needs to track provenance (which note contributed each temporal fact), handle amendments (later notes override earlier ones for some facts), and flag contradictions for human review.

**Error handling and dead letter queues.** If Comprehend Medical times out, the SageMaker endpoint is cold-starting, or DynamoDB write capacity is throttled, the Lambda needs structured retry logic. Configure SQS dead-letter queues for notes that fail repeatedly. A note that fails silently is a gap in the patient's timeline that nobody knows about until a clinician notices something missing.

**Performance at scale.** The candidate pair generation is O(N^2) in the number of entities. Notes with 100+ entities (complex discharge summaries, multi-day ICU stays) generate thousands of pairs, each requiring a SageMaker call. At ~100ms per call, that's minutes per note. Production systems batch SageMaker calls (using batch transform or multi-record inference), cache rule-based results, and parallelize pair classification across Lambda invocations.

**VPC and encryption requirements.** Lambda processing clinical notes must run inside a VPC with VPC endpoints for Comprehend Medical, SageMaker, DynamoDB, S3, and CloudWatch Logs. Clinical notes are PHI. Encrypt everything: S3 with SSE-KMS, DynamoDB with encryption at rest, SageMaker with inter-container encryption. All API calls over TLS. KMS key rotation enabled. CloudTrail logging every key usage event.

**Monitoring and drift.** Clinical documentation patterns evolve: new EHR templates, new providers, new temporal conventions ("per protocol day" in a new clinical trial). Monitor model confidence distributions over time. A downward shift in mean confidence or an increase in "NONE" predictions signals that the model is encountering patterns it wasn't trained on. Plan for quarterly retraining cycles with fresh annotations.

**Testing with realistic data.** The synthetic note above exercises the happy path with clean formatting and explicit dates. Production testing needs: notes with no section headers, notes entirely lacking explicit dates, notes with heavy abbreviation use, specialty-specific temporal patterns (oncology cycle notation, transplant day conventions, NICU gestational age), and notes written in the telegraphic style of night-shift residents. The THYME corpus (with appropriate data use agreement) provides annotated test data for benchmarking.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 8.9: Temporal Relationship Extraction](chapter08.09-temporal-relationship-extraction) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
