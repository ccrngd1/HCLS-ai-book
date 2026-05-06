# Recipe 2.2: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 2.2. It shows one way you could translate those concepts into working Python using boto3, Amazon Bedrock, and Amazon Comprehend Medical. It is not production-ready. There's no error handling beyond the basics, no retries on validation failures, no structured logging, and no integration with a real EHR system. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a patient portal on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a readability scoring library:

```bash
pip install boto3 textstat
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `bedrock:InvokeModel` (for the foundation model)
- `comprehendmedical:DetectEntitiesV2` (for Comprehend Medical entity extraction)
- `dynamodb:PutItem` (for storing results)

You also need model access enabled in the Bedrock console for your chosen model (this example uses Anthropic Claude 3 Haiku).

---

## Config and Constants

Configuration lives at the top of the module. Document type definitions, readability targets, and thresholds are all here so they're easy to find and adjust as you learn what works for your patient population.

```python
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
import textstat
from botocore.config import Config

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log PHI (patient text,
# clinical notes, medication lists, etc.).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config: adaptive mode uses exponential backoff with jitter.
# Bedrock can throttle under sustained load.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# AWS clients. Module-level for reuse across Lambda invocations.
bedrock_client = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
comprehend_medical_client = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# Model configuration.
MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
# If you get a ValidationException about model access, your region may require
# a cross-region inference profile ID instead:
# MODEL_ID = "us.anthropic.claude-3-haiku-20240307-v1:0"

# DynamoDB table for storing simplification results.
RESULTS_TABLE = "simplified-documents"

# Temperature: low for consistency. Medical text simplification needs
# deterministic, accurate output. Not creative writing.
TEMPERATURE = 0.2
MAX_TOKENS = 2048  # Simplified text can be longer than the original (explanations added).

# Document type configurations.
# Each type has indicator keywords, a target reading level, and style guidance.
# The target_grade is the Flesch-Kincaid grade level we're aiming for.
# The style string gets injected into the prompt to guide output structure.
DOCUMENT_TYPES = {
    "discharge_instructions": {
        "indicators": ["discharge", "follow-up", "return to", "activity restrictions"],
        "target_grade": 6,
        "style": "action-oriented, numbered steps, clear timelines",
    },
    "lab_results": {
        "indicators": ["result", "reference range", "normal", "abnormal", "specimen"],
        "target_grade": 7,
        "style": "numerical context, what-it-means explanations, when to worry",
    },
    "procedure_description": {
        "indicators": ["procedure", "performed", "anesthesia", "incision", "catheter"],
        "target_grade": 7,
        "style": "what-happened narrative, anatomical explanations, recovery expectations",
    },
    "medication_instructions": {
        "indicators": ["medication", "dosage", "take", "prescribe", "refill"],
        "target_grade": 5,
        "style": "simple directives, timing, what to avoid, side effects to watch for",
    },
}

# Quality gate thresholds.
# If the simplified text scores more than this many grade levels above target,
# it fails readability and gets retried.
GRADE_TOLERANCE = 2

# Maximum retry attempts for readability failures.
# Accuracy failures never retry (route to human immediately).
MAX_RETRIES = 2
```

---

## Step 1: Classify the Clinical Document Type

*The pseudocode calls this `classify_document(clinical_text)`. Before simplifying, we need to know what kind of clinical text we're dealing with. Different document types need different simplification strategies: discharge instructions are action-oriented, lab results need numerical context, procedure descriptions need anatomical explanations.*

```python
def classify_document(clinical_text: str) -> str:
    """
    Classify clinical text into a document type using keyword matching.

    This is deliberately simple. Clinical documents are structured enough
    that keyword matching works well for categorization. You don't need
    an LLM for this step. The indicators in DOCUMENT_TYPES are tuned for
    common clinical document patterns.

    If a document doesn't match any type, it falls back to "general" which
    uses a balanced simplification approach without type-specific styling.

    Args:
        clinical_text: The raw clinical text to classify.

    Returns:
        A document type string: "discharge_instructions", "lab_results",
        "procedure_description", "medication_instructions", or "general".
    """
    lower_text = clinical_text.lower()
    scores = {}

    for doc_type, config in DOCUMENT_TYPES.items():
        score = sum(1 for indicator in config["indicators"] if indicator in lower_text)
        scores[doc_type] = score

    # Return the type with the highest match count.
    # If nothing matched at all, fall back to "general".
    best_type = max(scores, key=scores.get)
    if scores[best_type] == 0:
        return "general"
    return best_type
```

---

## Step 2: Build the Simplification Prompt

*The pseudocode calls this `build_simplification_prompt(clinical_text, doc_type)`. The prompt is where the real work happens. It tells the model exactly what "simplification" means: target reading level, what to preserve, what to explain, what to avoid. A well-crafted prompt is the difference between genuinely useful patient-friendly text and slightly shorter clinical jargon.*

```python
def build_simplification_prompt(clinical_text: str, doc_type: str) -> tuple[str, str]:
    """
    Assemble the system and user prompts for medical text simplification.

    The system prompt defines the model's role and constraints. The user
    prompt provides the specific clinical text and target parameters.

    The prompt is intentionally verbose about constraints. Every rule exists
    because we saw the model violate it during testing. "Do NOT add medical
    advice not present in the original" is there because the model will
    helpfully suggest "talk to your doctor about..." if you don't tell it not to.

    Args:
        clinical_text: The clinical text to simplify.
        doc_type: The classified document type from Step 1.

    Returns:
        A tuple of (system_prompt, user_prompt).
    """
    # Look up type-specific configuration. Fall back to sensible defaults
    # for the "general" type.
    if doc_type in DOCUMENT_TYPES:
        config = DOCUMENT_TYPES[doc_type]
        target_grade = config["target_grade"]
        style = config["style"]
    else:
        target_grade = 6
        style = "clear, structured, patient-friendly"

    system_prompt = (
        "You are a health literacy specialist. Your job is to rewrite clinical text "
        "into plain language that a patient can understand.\n\n"
        "Rules:\n"
        f"- Target reading level: grade {target_grade} (Flesch-Kincaid)\n"
        "- Preserve ALL medical facts: medications, dosages, timelines, restrictions\n"
        "- Explain medical terms in parentheses on first use, then use the plain version\n"
        "- Use short sentences (under 20 words when possible)\n"
        "- Use active voice (\"Take your medication\" not \"Medication should be taken\")\n"
        "- Include all numbers, dates, and specific instructions exactly as stated\n"
        "- Do NOT add medical advice not present in the original\n"
        "- Do NOT remove any instructions or warnings from the original\n"
        "- Do NOT use the phrase \"consult your doctor\" unless the original says it\n"
        f"- Style: {style}\n\n"
        "Format the output with clear headings and bullet points where appropriate.\n"
        "If the original has numbered steps, keep them numbered."
    )

    user_prompt = (
        "Simplify the following clinical text for a patient:\n\n"
        "---\n"
        f"{clinical_text}\n"
        "---\n\n"
        f"Rewrite this at a grade {target_grade} reading level while preserving "
        "all medical facts, medication names, dosages, and specific instructions."
    )

    return system_prompt, user_prompt
```

---

## Step 3: Generate the Simplified Version

*The pseudocode calls this `generate_simplification(system_prompt, user_prompt, model_id)`. This calls Amazon Bedrock with a low temperature to keep output deterministic and factual. The model processes the clinical text, identifies technical terminology, and regenerates the content in plain language.*

```python
def generate_simplification(system_prompt: str, user_prompt: str) -> str:
    """
    Call Amazon Bedrock to generate the simplified text.

    Uses the Converse API for a unified interface across model providers.
    Low temperature (0.2) keeps output consistent and factual. Higher
    temperatures introduce creativity, which is the opposite of what you
    want when medical accuracy matters.

    Args:
        system_prompt: Behavior constraints and simplification rules.
        user_prompt: The clinical text and target parameters.

    Returns:
        The simplified text string.
    """
    response = bedrock_client.converse(
        modelId=MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [{"text": user_prompt}],
            }
        ],
        system=[{"text": system_prompt}],
        inferenceConfig={
            "maxTokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "topP": 0.9,
        },
    )

    # Extract the generated text from the Converse response.
    output_message = response["output"]["message"]
    simplified_text = output_message["content"][0]["text"]

    return simplified_text
```

---

## Step 4: Validate Medical Accuracy with Entity Comparison

*The pseudocode calls this `validate_accuracy(original_text, simplified_text)`. This is the safety-critical step. We extract medical entities from both the original and simplified text using Comprehend Medical, then compare them. If the original mentions "clopidogrel 75mg daily" and the simplified version drops the medication name or changes the dose, we catch it here.*

```python
def extract_medical_entities(text: str) -> list[dict]:
    """
    Extract medical entities from text using Amazon Comprehend Medical.

    Comprehend Medical identifies medications, conditions, dosages,
    procedures, and other clinical concepts. We use DetectEntitiesV2
    which returns structured entity data with categories and attributes.

    Note: Comprehend Medical has a 20,000 character limit per request.
    For longer documents, you'd need to chunk the text. Most clinical
    documents (discharge summaries, lab results) fit within this limit.

    Args:
        text: Clinical or simplified text to analyze.

    Returns:
        A list of entity dicts, each with "Text", "Category", "Type",
        "Score", and "Attributes" fields.
    """
    response = comprehend_medical_client.detect_entities_v2(Text=text)
    return response["Entities"]


def validate_accuracy(original_text: str, simplified_text: str) -> dict:
    """
    Compare medical entities between original and simplified text.

    The core idea: every critical medical entity in the original should
    have a corresponding entity in the simplified version. "Critical"
    means medications (with dosages), medical conditions, and procedures.
    We allow different wording (that's the whole point of simplification)
    but the underlying facts must be present.

    This is a proxy for meaning preservation, not a guarantee. Entity
    comparison catches gross errors (dropped medications, changed doses)
    but won't catch subtle meaning drift. For production, supplement with
    periodic human audits.

    Args:
        original_text: The source clinical text.
        simplified_text: The LLM-generated simplified version.

    Returns:
        A dict with "passed" (bool), "missing_entities" (list),
        "altered_entities" (list), and entity counts.
    """
    # Extract entities from both versions.
    original_entities = extract_medical_entities(original_text)
    simplified_entities = extract_medical_entities(simplified_text)

    # Focus on critical categories: medications, conditions, procedures.
    # Other categories (anatomy, time expressions) are less critical for
    # accuracy validation.
    critical_categories = {"MEDICATION", "MEDICAL_CONDITION", "TEST_TREATMENT_PROCEDURE"}

    original_critical = [
        e for e in original_entities if e["Category"] in critical_categories
    ]
    simplified_critical = [
        e for e in simplified_entities if e["Category"] in critical_categories
    ]

    # Build a lookup of simplified entity texts (lowercased) for matching.
    simplified_texts = {e["Text"].lower() for e in simplified_critical}

    # Check each critical entity from the original.
    missing_entities = []
    for entity in original_critical:
        entity_text = entity["Text"].lower()
        # Check for exact match or substring match.
        # Substring handles cases like "aspirin 81mg" matching "aspirin 81mg every day".
        found = any(
            entity_text in s_text or s_text in entity_text
            for s_text in simplified_texts
        )
        if not found:
            missing_entities.append({
                "text": entity["Text"],
                "category": entity["Category"],
                "type": entity.get("Type", ""),
            })

    # For medications specifically, check that dosages are preserved.
    # Comprehend Medical returns dosage as an attribute of medication entities.
    altered_entities = []
    original_meds = [e for e in original_critical if e["Category"] == "MEDICATION"]
    simplified_meds = [e for e in simplified_critical if e["Category"] == "MEDICATION"]

    for orig_med in original_meds:
        # Get dosage attributes from the original medication entity.
        orig_dosages = [
            attr["Text"] for attr in orig_med.get("Attributes", [])
            if attr.get("Type") == "DOSAGE"
        ]
        if not orig_dosages:
            continue

        # Find the matching medication in simplified text.
        matching_simplified = [
            s for s in simplified_meds
            if orig_med["Text"].lower() in s["Text"].lower()
            or s["Text"].lower() in orig_med["Text"].lower()
        ]

        for match in matching_simplified:
            simplified_dosages = [
                attr["Text"] for attr in match.get("Attributes", [])
                if attr.get("Type") == "DOSAGE"
            ]
            # If original had a dosage but simplified doesn't, flag it.
            # Note: Comprehend Medical may include dosage in the entity text
            # itself rather than as a separate Attribute, which can cause
            # false positives here. Production systems need fuzzy matching.
            if orig_dosages and not simplified_dosages:
                altered_entities.append({
                    "medication": orig_med["Text"],
                    "original_dosage": orig_dosages[0],
                    "simplified_dosage": "NOT FOUND",
                })

    passed = len(missing_entities) == 0 and len(altered_entities) == 0

    return {
        "passed": passed,
        "missing_entities": missing_entities,
        "altered_entities": altered_entities,
        "original_entity_count": len(original_critical),
        "simplified_entity_count": len(simplified_critical),
    }
```

---

## Step 5: Score Readability

*The pseudocode calls this `score_readability(text)`. We run the simplified text through established readability formulas to verify it actually hit the target grade level. This is a computational check, not an LLM call: fast and deterministic.*

```python
def score_readability(text: str) -> dict:
    """
    Calculate readability scores for the simplified text.

    Uses the textstat library which implements Flesch-Kincaid, Flesch Reading
    Ease, SMOG, and other standard readability formulas. These measure surface
    complexity (word length, sentence length, syllable count) but not conceptual
    complexity. Use them as a necessary-but-not-sufficient quality check.

    Flesch-Kincaid Grade Level is the primary metric. A score of 6.0 means
    a typical 6th grader could understand it. Most clinical text scores 12-16.
    Your target is 5-8 depending on document type.

    Args:
        text: The simplified text to score.

    Returns:
        A dict with readability metrics: flesch_kincaid_grade,
        flesch_reading_ease, smog_index, word_count, avg_sentence_length.
    """
    # textstat handles the syllable counting, sentence splitting, and formula
    # application. It's not perfect (no syllable counter is), but it's the
    # standard library used in health literacy research.
    fk_grade = textstat.flesch_kincaid_grade(text)
    fk_ease = textstat.flesch_reading_ease(text)
    smog = textstat.smog_index(text)
    word_count = textstat.lexicon_count(text, removepunct=True)
    sentence_count = textstat.sentence_count(text)

    avg_sentence_length = round(word_count / max(sentence_count, 1), 1)

    return {
        "flesch_kincaid_grade": round(fk_grade, 1),
        "flesch_reading_ease": round(fk_ease, 1),
        "smog_index": round(smog, 1),
        "word_count": word_count,
        "sentence_count": sentence_count,
        "avg_sentence_length": avg_sentence_length,
    }
```


---

## Step 6: Quality Gate and Retry Logic

*The pseudocode calls this `quality_gate(original_text, simplified_text, doc_type, attempt_number)`. This combines the validation result and readability score to make a pass/fail decision. Accuracy failures route to human review immediately (no retry). Readability failures get retried with a more aggressive prompt.*

```python
def quality_gate(
    original_text: str,
    simplified_text: str,
    doc_type: str,
    attempt_number: int,
) -> dict:
    """
    Evaluate whether the simplified text passes quality checks.

    Two checks run in sequence:
    1. Medical accuracy (entity comparison): Did we preserve all critical facts?
    2. Readability (grade level): Did we actually simplify enough?

    If accuracy fails, we route to human review immediately. The model made
    a factual error and retrying might produce the same error. If readability
    fails but accuracy passes, we retry with a more aggressive prompt (up to
    MAX_RETRIES attempts).

    Args:
        original_text: The source clinical text.
        simplified_text: The generated simplified version.
        doc_type: Document type for target grade lookup.
        attempt_number: Current attempt (0-indexed). Used to decide retry vs accept.

    Returns:
        A dict with "status" (PASSED, RETRY, FAILED_ACCURACY, ACCEPTED_WITH_FLAG),
        plus relevant details for each status.
    """
    # Run accuracy validation.
    validation = validate_accuracy(original_text, simplified_text)

    # Run readability scoring.
    readability = score_readability(simplified_text)

    # Look up the target grade for this document type.
    if doc_type in DOCUMENT_TYPES:
        target_grade = DOCUMENT_TYPES[doc_type]["target_grade"]
    else:
        target_grade = 6

    # Decision logic: accuracy first, then readability.
    if not validation["passed"]:
        # Medical accuracy failure. Do not retry. Route to human.
        return {
            "status": "FAILED_ACCURACY",
            "route_to": "human_review",
            "reason": "Missing or altered medical entities",
            "validation": validation,
            "readability": readability,
        }

    if readability["flesch_kincaid_grade"] > (target_grade + GRADE_TOLERANCE):
        # Too complex. Retry if we haven't exceeded max attempts.
        if attempt_number < MAX_RETRIES:
            return {
                "status": "RETRY",
                "reason": "Reading level too high",
                "current_grade": readability["flesch_kincaid_grade"],
                "target_grade": target_grade,
                "readability": readability,
            }
        else:
            # Max retries exceeded. Accept with a flag for review.
            return {
                "status": "ACCEPTED_WITH_FLAG",
                "flag": "readability_above_target",
                "readability": readability,
                "validation": validation,
            }

    # Both checks passed.
    return {
        "status": "PASSED",
        "readability": readability,
        "validation": validation,
    }
```

---

## Step 7: Store Results

*The pseudocode calls this `store_result(...)`. Write the complete record to DynamoDB: original text, simplified version, all scores, validation details, and processing metadata. This audit trail is essential for compliance and continuous improvement.*

```python
def store_result(
    document_id: str,
    original_text: str,
    simplified_text: str,
    doc_type: str,
    quality_result: dict,
    readability: dict,
) -> dict:
    """
    Write the simplification record to DynamoDB.

    The record includes everything needed for audit, quality monitoring,
    and continuous improvement: the original text, simplified version,
    all quality scores, and processing metadata.

    Why store the original alongside the simplified version? Three reasons:
    1. Audit trail: regulators can verify what was transformed
    2. Quality review: humans can compare side-by-side
    3. Reprocessing: if you improve your prompt, you can re-simplify old documents

    Args:
        document_id: Unique identifier for this document.
        original_text: The source clinical text.
        simplified_text: The generated simplified version.
        doc_type: Classified document type.
        quality_result: Output from quality_gate.
        readability: Readability scores dict.

    Returns:
        The complete record written to DynamoDB.
    """
    table = dynamodb.Table(RESULTS_TABLE)

    record = {
        "document_id": document_id,
        "timestamp": datetime.datetime.now(timezone.utc).isoformat(),
        "doc_type": doc_type,
        "original_text": original_text,
        "simplified_text": simplified_text,
        "status": quality_result["status"],
        "needs_review": quality_result["status"] != "PASSED",
        "readability_scores": {
            "flesch_kincaid_grade": Decimal(str(readability["flesch_kincaid_grade"])),
            "flesch_reading_ease": Decimal(str(readability["flesch_reading_ease"])),
            "smog_index": Decimal(str(readability["smog_index"])),
            "word_count": readability["word_count"],
            "avg_sentence_length": Decimal(str(readability["avg_sentence_length"])),
        },
        "validation_result": {
            "passed": quality_result.get("validation", {}).get("passed", False),
            "missing_entity_count": len(
                quality_result.get("validation", {}).get("missing_entities", [])
            ),
            "altered_entity_count": len(
                quality_result.get("validation", {}).get("altered_entities", [])
            ),
        },
        "model_id": MODEL_ID,
        "temperature": Decimal(str(TEMPERATURE)),
        "prompt_version": "v1",
    }

    # DynamoDB put_item creates or replaces the item.
    # In production, add a ConditionExpression if you need to protect
    # existing records from accidental overwrites.
    table.put_item(Item=record)

    return record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function with the retry loop for readability failures.

```python
def simplify_clinical_text(document_id: str, clinical_text: str) -> dict:
    """
    Run the full medical terminology simplification pipeline.

    This is the main entry point. In a Lambda deployment, your handler
    would parse the incoming event (from an EHR webhook, S3 upload, or
    API Gateway request), extract the clinical text, and call this function.

    The pipeline:
    1. Classify the document type
    2. Build the simplification prompt
    3. Generate simplified text via Bedrock
    4. Validate medical accuracy via Comprehend Medical
    5. Score readability
    6. Quality gate (retry if readability fails, flag if accuracy fails)
    7. Store the result

    Args:
        document_id: Unique identifier for this document.
        clinical_text: The raw clinical text to simplify.

    Returns:
        The stored result record.
    """
    # Step 1: Classify the document type.
    logger.info("Step 1: Classifying document type")
    doc_type = classify_document(clinical_text)
    logger.info("  Classified as: %s", doc_type)

    # Retry loop: we may need multiple attempts if readability is too high.
    attempt = 0
    simplified_text = None
    quality_result = None

    while attempt <= MAX_RETRIES:
        # Step 2: Build the prompt.
        # On retries, we add extra emphasis on simplification.
        logger.info("Step 2: Building prompt (attempt %d)", attempt + 1)
        system_prompt, user_prompt = build_simplification_prompt(clinical_text, doc_type)

        if attempt > 0:
            # On retry, append extra instructions to push for simpler output.
            user_prompt += (
                "\n\nIMPORTANT: The previous attempt was too complex. "
                "Use even shorter sentences. Replace ALL medical terms with "
                "plain language equivalents. Target a 5th grade reading level. "
                "Every sentence should be under 15 words."
            )

        # Step 3: Generate the simplified version.
        logger.info("Step 3: Generating simplified text via Bedrock")
        simplified_text = generate_simplification(system_prompt, user_prompt)
        logger.info("  Generated %d characters", len(simplified_text))

        # Steps 4-6: Quality gate (includes validation and readability scoring).
        logger.info("Step 4-6: Running quality gate")
        quality_result = quality_gate(clinical_text, simplified_text, doc_type, attempt)
        logger.info("  Quality status: %s", quality_result["status"])

        if quality_result["status"] == "RETRY":
            logger.info(
                "  Grade level %.1f exceeds target. Retrying...",
                quality_result["current_grade"],
            )
            attempt += 1
            continue
        else:
            # Either passed, failed accuracy, or accepted with flag. Stop retrying.
            break

    # Step 7: Store the result.
    logger.info("Step 7: Storing result in DynamoDB")
    readability = quality_result.get("readability", score_readability(simplified_text))
    record = store_result(
        document_id=document_id,
        original_text=clinical_text,
        simplified_text=simplified_text,
        doc_type=doc_type,
        quality_result=quality_result,
        readability=readability,
    )

    logger.info(
        "Done. status=%s, grade_level=%.1f, needs_review=%s",
        record["status"],
        readability["flesch_kincaid_grade"],
        record["needs_review"],
    )
    return record


# Example: run the pipeline against a sample discharge summary.
if __name__ == "__main__":
    sample_clinical_text = (
        "Patient experienced acute ST-elevation myocardial infarction with "
        "subsequent percutaneous coronary intervention via drug-eluting stent "
        "placement in the left anterior descending artery. Continue dual "
        "antiplatelet therapy with aspirin 81mg and clopidogrel 75mg daily "
        "for 12 months. Avoid NSAIDs. Follow up with cardiology in 2 weeks "
        "for post-PCI assessment."
    )

    result = simplify_clinical_text(
        document_id="doc-2026-05-01-discharge-00482",
        clinical_text=sample_clinical_text,
    )

    # Pretty-print the result. DynamoDB Decimal objects aren't JSON-serializable
    # by default, so we convert them to float for display.
    class DecimalEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Decimal):
                return float(obj)
            return super().default(obj)

    print(json.dumps(result, indent=2, cls=DecimalEncoder))
```

---

## The Gap Between This and Production

This example works. Point it at a real Bedrock endpoint and Comprehend Medical, feed it clinical text, and it will produce a simplified version with readability scores and entity validation. But the distance between "works as a script" and "runs at a health system simplifying thousands of documents per day" is significant. Here's where that gap lives.

**Error handling.** Every external call here can fail. Bedrock can throttle under load. Comprehend Medical has a 20,000 character limit per request (longer documents need chunking). DynamoDB can reject items over 400KB. A production system wraps each call in try/except with specific handling for `ThrottlingException`, `ValidationException`, and `ServiceUnavailableException`. Failed documents go to a dead-letter queue, not into the void.

**Comprehend Medical character limits.** The `detect_entities_v2` API accepts a maximum of 20,000 UTF-8 characters per request. Most discharge summaries and lab results fit within this, but long hospital course summaries or multi-page documents will exceed it. A production system chunks text at sentence boundaries, processes each chunk separately, and merges the entity lists. Splitting mid-sentence can cause entity detection failures at chunk boundaries.

**Entity matching sophistication.** The `validate_accuracy` function uses simple substring matching to compare entities. This works for exact matches ("aspirin" in both texts) but misses semantic equivalents. The original might say "myocardial infarction" while the simplified version says "heart attack." Both refer to the same condition, but substring matching won't connect them. A production system needs a medical synonym map or a secondary LLM call to verify semantic equivalence.

**Readability scoring limitations.** The `textstat` library measures surface complexity (syllable count, sentence length) but not conceptual complexity. A sentence using only short words can still be confusing if the concept is abstract. "Your blood does not clot well" scores as grade 4 but might confuse a patient who doesn't know what clotting means. Use readability scores as a floor, not a ceiling. Supplement with periodic human evaluation.

**Prompt versioning.** This example uses a hardcoded prompt. A production system stores prompts in S3 (versioned bucket), routes a percentage of traffic to new prompt versions for A/B testing, and tracks readability scores and validation pass rates per prompt version. When a new prompt improves scores, promote it. When it degrades, roll back.

**Batch processing.** This example processes one document at a time. A health system generating hundreds of discharge summaries per day needs batch processing: an SQS queue feeding Lambda invocations, with concurrency limits to avoid Bedrock throttling. Consider Bedrock batch inference for high-volume, non-real-time workloads.

**Caching.** Many clinical documents contain repeated phrases and standard language. "Follow up in 2 weeks" appears in thousands of discharge summaries. A production system can cache simplifications of common phrases to reduce Bedrock calls and improve latency. Use a TTL-based cache (ElastiCache or DynamoDB) keyed on a hash of the input text.

**Multi-language support.** This example produces English simplified text only. For patient populations with limited English proficiency, you'd add a translation step after simplification. Simplify first (in English), then translate. Translating complex clinical English directly produces worse results than translating already-simplified English. Amazon Translate handles the translation step.

**VPC and network isolation.** In production, this Lambda runs in a VPC with private subnets. VPC endpoints for Bedrock, Comprehend Medical, DynamoDB, and CloudWatch keep all traffic on the AWS backbone. Clinical text is PHI. It should never traverse the public internet.

**Encryption.** This example relies on default encryption. Production uses KMS customer-managed keys for the DynamoDB table and CloudWatch Logs. Enable key rotation. Log every key usage via CloudTrail.

**Structured logging and metrics.** The `logger.info()` calls here are a start. Production needs structured JSON logs with consistent fields: document_id, doc_type, model_id, attempt_count, latency_ms, readability_grade, validation_passed. Emit CloudWatch metrics for: simplification latency (p50, p95), readability score distribution, validation pass rate, retry rate, and human review rate. The validation pass rate is your north star metric.

**Human review workflow.** Documents that fail accuracy validation route to "human review," but this example doesn't implement the review queue. In production, failed documents go to an SQS queue that feeds a review UI where health literacy specialists can edit the simplified text, approve it, or flag the original as too complex for automated simplification.

**Testing.** There are no tests here. A production pipeline has: unit tests for `classify_document` with edge cases, integration tests against Bedrock with known clinical text samples, validation tests confirming that intentionally degraded simplifications (dropped medications, changed doses) are caught by `validate_accuracy`, and readability regression tests ensuring prompt changes don't degrade grade level scores. Never use real patient documents in test fixtures. Use synthetic clinical text.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 2.2: Medical Terminology Simplification](chapter02.02-medical-terminology-simplification) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
