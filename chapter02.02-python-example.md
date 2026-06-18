# Recipe 2.2: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 2.2. It shows one way you could translate those concepts into working Python using boto3, Amazon Bedrock, and Amazon Comprehend Medical. It is not production-ready. Error handling is minimal, there's no retry-on-validation-failure loop, and there's no real integration with an EHR or patient portal. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a discharge workflow on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a readability scoring library:

```bash
pip install boto3 textstat
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `bedrock:InvokeModel` (for the foundation model)
- `bedrock:ApplyGuardrail` (for content safety filtering)
- `comprehendmedical:DetectEntitiesV2` (for medical entity extraction)
- `dynamodb:PutItem` (for storing simplified documents)

You also need model access enabled in the Bedrock console for your chosen model (this example uses Anthropic Claude 3 Haiku) and a configured Bedrock Guardrail for terminology simplification.

---

## Config and Constants

The segment type keywords, type-specific prompts, and reading level targets all live at the top of the module. This mirrors the pseudocode structure: the data that drives behavior sits above the functions that use it, so it's easy to tune as you learn what works for your documents.

```python
import hashlib
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
import textstat
from botocore.config import Config

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log PHI (clinical text,
# patient names, medication lists, etc.).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config: adaptive mode uses exponential backoff with jitter.
# Bedrock can throttle under sustained load; Comprehend Medical is
# generally well-behaved but benefits from the same retry posture.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# AWS clients. Module-level so they're reused across Lambda invocations.
bedrock_client = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
comprehend_medical_client = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# Model configuration.
MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
# If you get a ValidationException about model access, your region may
# require a cross-region inference profile ID instead:
# MODEL_ID = "us.anthropic.claude-3-haiku-20240307-v1:0"

# Guardrail configuration. Replace with your actual guardrail.
GUARDRAIL_ID = "your-guardrail-id-here"
GUARDRAIL_VERSION = "DRAFT"  # Use "DRAFT" for testing, numbered version for prod

# DynamoDB table for storing simplified documents.
RESULTS_TABLE = "simplified-documents"

# Target reading level for simplified output (Flesch-Kincaid grade level).
# 6th grade is a common target for patient-facing health materials because
# the median US adult reading level sits around 8th grade and health
# literacy research recommends aiming below the median.
TARGET_GRADE = 6

# Allow simplified text to come in up to this many grades above target
# before we flag it. Models drift upward; perfect grade-level targeting
# is hard.
GRADE_TOLERANCE = 2

# Low temperature keeps output consistent and factual. Not creative writing.
TEMPERATURE = 0.2

# Max tokens: simplified text can be longer than the source because
# plain-language explanations get added. 2x source length is usually enough.
MAX_TOKENS_MULTIPLIER = 2

# Segment type classification keywords. Order matters: first match wins
# when a section could fit multiple types. Keep medications first so
# medication-heavy sections get the strictest preservation rules.
# TODO (TechWriter): The "aspirin" keyword under "medications" is fragile:
# specific drug names won't generalize. Consider replacing with structural
# markers (section headers, list patterns) or a small classifier model.
SEGMENT_TYPES = {
    "medications": ["medication", "prescription", "drug", "dose", "mg", "tablet", "aspirin"],
    "diagnosis":   ["diagnosis", "assessment", "impression", "condition"],
    "instructions": ["follow up", "follow-up", "return", "call if", "go to", "schedule"],
    "results":     ["result", "lab", "level", "value", "range", "normal", "abnormal"],
}

# Type-specific system prompts. Each tells the model what to preserve
# verbatim, what to translate, and what to avoid. These exist separately
# because uniform simplification produces uniformly mediocre output.
# See The Honest Take in the main recipe for why.
SIMPLIFICATION_PROMPTS = {
    "medications": (
        "Rewrite this medication information for a patient reading at a {level} level.\n"
        "RULES:\n"
        "- Keep all medication names exactly as written (do not rename drugs)\n"
        "- Keep all dosages exactly as written (do not change numbers or units)\n"
        "- Keep all frequency instructions exactly as written\n"
        "- Add a brief plain-language explanation of what each medication does\n"
        "- Use short sentences\n"
        "- Do not add warnings or side effects not mentioned in the source"
    ),
    "diagnosis": (
        "Rewrite this diagnosis information for a patient reading at a {level} level.\n"
        "RULES:\n"
        "- Translate medical terms into everyday language\n"
        "- After using a plain term, include the medical term in parentheses once\n"
        "- Explain what the condition means for the patient in practical terms\n"
        "- Do not add prognosis information not stated in the source\n"
        "- Do not minimize or dramatize the condition\n"
        "- Use short sentences"
    ),
    "instructions": (
        "Rewrite these follow-up instructions for a patient reading at a {level} level.\n"
        "RULES:\n"
        "- Convert to clear action items (what to do, when to do it, who to contact)\n"
        "- Keep all dates, times, and provider names exactly as written\n"
        "- Keep all phone numbers exactly as written\n"
        "- Use numbered steps where appropriate\n"
        "- Highlight urgency cues (\"call immediately if...\") clearly\n"
        "- Use short sentences"
    ),
    "results": (
        "Rewrite these test results for a patient reading at a {level} level.\n"
        "RULES:\n"
        "- Keep all numbers and units exactly as written\n"
        "- Explain what each test measures in plain language\n"
        "- Explain whether results are normal, high, or low if stated in the source\n"
        "- Do not interpret results beyond what the source states\n"
        "- Use short sentences"
    ),
    "narrative": (
        "Rewrite this clinical text for a patient reading at a {level} level.\n"
        "RULES:\n"
        "- Translate medical terms into everyday language\n"
        "- Keep all names, dates, and numbers exactly as written\n"
        "- Use short sentences\n"
        "- Do not add information not in the source"
    ),
}
```

---

## Step 1: Extract Critical Medical Entities

*The pseudocode calls this `extract_critical_entities(clinical_text)`. Before we simplify anything, we need to know which clinical concepts must survive the transformation. Medication names, dosages, conditions, procedures: non-negotiable. This function calls Comprehend Medical and builds a preservation checklist that Step 4 will verify against the simplified output.*

```python
def extract_critical_entities(clinical_text: str) -> list[dict]:
    """
    Extract medical entities from clinical text and build a preservation list.

    Comprehend Medical returns structured entities with categories
    (MEDICATION, MEDICAL_CONDITION, TEST_TREATMENT_PROCEDURE, etc.) and,
    for medications, attributes like DOSAGE and FREQUENCY. We unpack these
    into a flat "must preserve" list with a flag indicating whether the
    term must appear verbatim in the simplified output (true for drug
    names and dosages, false for conditions and procedures that can be
    translated to plain language).

    Note: Comprehend Medical has a 20,000-character limit per request.
    Longer documents need chunking at sentence boundaries before calling
    this. Most discharge summaries fit comfortably below that limit.

    Args:
        clinical_text: The source clinical text.

    Returns:
        A list of preservation entries, each with keys:
          - text: the entity string
          - category: MEDICATION, CONDITION, PROCEDURE, or DOSAGE_FREQ
          - preserve_verbatim: bool; true means exact match required
    """
    response = comprehend_medical_client.detect_entities_v2(Text=clinical_text)

    must_preserve = []

    for entity in response["Entities"]:
        category = entity["Category"]

        if category == "MEDICATION":
            # Medication names always verbatim: patients need to verify
            # their prescription at the pharmacy, which requires the
            # exact drug name.
            must_preserve.append({
                "text": entity["Text"],
                "category": "MEDICATION",
                "preserve_verbatim": True,
            })

            # Comprehend Medical returns dosage and frequency as attributes
            # of medication entities, not separate top-level entities.
            # Unpack them so Step 4 can check each one individually.
            for attr in entity.get("Attributes", []):
                attr_type = attr.get("Type", "")
                if attr_type in ("DOSAGE", "FREQUENCY", "STRENGTH", "ROUTE_OR_MODE"):
                    must_preserve.append({
                        "text": attr["Text"],
                        "category": "DOSAGE_FREQ",
                        "preserve_verbatim": True,
                    })

        elif category == "MEDICAL_CONDITION":
            # Conditions can be translated ("myocardial infarction" ->
            # "heart attack"), but must be mentioned in some form.
            must_preserve.append({
                "text": entity["Text"],
                "category": "CONDITION",
                "preserve_verbatim": False,
            })

        elif category == "TEST_TREATMENT_PROCEDURE":
            # Procedures can be explained in plain language, but must
            # be referenced in the output.
            must_preserve.append({
                "text": entity["Text"],
                "category": "PROCEDURE",
                "preserve_verbatim": False,
            })

    logger.info("Extracted %d critical entities for preservation", len(must_preserve))
    return must_preserve
```

---

## Step 2: Segment the Clinical Document

*The pseudocode calls this `segment_document(clinical_text)`. Different parts of a clinical document need different simplification strategies. Medications need drug names preserved. Follow-up instructions need clear action items. Segmenting first lets us apply type-specific prompts in Step 3 instead of hoping one prompt handles everything. Without this step, you get uniformly mediocre output.*

```python
def segment_document(clinical_text: str) -> list[dict]:
    """
    Split clinical text into logical sections and classify each one.

    Segmentation here is deliberately simple: split on blank lines and
    classify each chunk by keyword matching against SEGMENT_TYPES.
    Clinical documents are structured enough that keyword matching works
    well; upgrading to a classifier model rarely justifies the added
    latency and cost.

    Sections that don't match any type fall back to "narrative", which
    uses a balanced general-purpose prompt.

    Args:
        clinical_text: The source clinical text.

    Returns:
        A list of segment dicts, each with:
          - text: the segment content
          - type: one of "medications", "diagnosis", "instructions",
                  "results", or "narrative"
          - index: 0-based position, used to reassemble in Step 5
    """
    # Split on blank lines. Many clinical documents use double newlines
    # between sections; single-paragraph documents become one segment.
    raw_sections = [s.strip() for s in clinical_text.split("\n\n") if s.strip()]

    # If the document has no blank-line breaks, treat the whole thing
    # as one segment. It still gets classified and simplified.
    if len(raw_sections) == 0:
        raw_sections = [clinical_text.strip()]

    segments = []

    for index, section in enumerate(raw_sections):
        section_lower = section.lower()
        matched_type = "narrative"  # default fallback

        # First match wins. Order in SEGMENT_TYPES reflects priority.
        for seg_type, keywords in SEGMENT_TYPES.items():
            if any(keyword in section_lower for keyword in keywords):
                matched_type = seg_type
                break

        segments.append({
            "text": section,
            "type": matched_type,
            "index": index,
        })

    logger.info(
        "Segmented document into %d sections: %s",
        len(segments),
        [s["type"] for s in segments],
    )
    return segments
```

---

## Step 3: Simplify Each Segment with Type-Specific Constraints

*The pseudocode calls this `simplify_segment(segment, must_preserve, reading_level)`. This is the core transformation. Each segment gets a prompt tailored to its content type, with the preserve-verbatim list appended so the model knows which strings are untouchable. Guardrails wrap the call to catch outputs that add clinical advice or drop safety information.*

```python
def simplify_segment(segment: dict, must_preserve: list[dict], reading_level: int = TARGET_GRADE) -> dict:
    """
    Simplify a single segment using a type-specific prompt and Bedrock.

    The prompt template is selected based on segment type. The preserve-
    verbatim list (from Step 1) is appended so the model sees exactly
    which drug names, dosages, dates, and frequencies must survive
    unchanged. Temperature is low because this is transformation, not
    creative writing.

    If the guardrail intervenes, we return the source text unchanged
    with a flag rather than silently using whatever the guardrail
    produced. Downstream code decides whether to retry or flag for
    human review.

    Args:
        segment: Dict from segment_document with text, type, index.
        must_preserve: Preservation list from extract_critical_entities.
        reading_level: Target Flesch-Kincaid grade level.

    Returns:
        A dict with:
          - text: simplified text (or source if guardrail blocked)
          - type: segment type, passed through
          - index: position, passed through
          - simplified: bool, true if transformation happened
          - reason: optional explanation when simplified=false
    """
    seg_type = segment["type"]
    prompt_template = SIMPLIFICATION_PROMPTS.get(seg_type, SIMPLIFICATION_PROMPTS["narrative"])
    system_prompt = prompt_template.format(level=f"{reading_level}th grade")

    # Append the verbatim preservation list. This is the single most
    # effective guardrail against the model "simplifying" "ticagrelor
    # 90mg" to "your blood thinner." Give the model explicit targets
    # it's not allowed to touch.
    verbatim_terms = [e["text"] for e in must_preserve if e["preserve_verbatim"]]
    if verbatim_terms:
        system_prompt += (
            "\n\nThe following terms MUST appear in your output exactly as written, "
            "with identical spelling, numbers, and units: "
            + ", ".join(verbatim_terms)
        )

    # Estimate max tokens: roughly 1.3 tokens per word, doubled to allow
    # for added plain-language explanations.
    approx_words = len(segment["text"].split())
    max_tokens = max(300, int(approx_words * 1.3 * MAX_TOKENS_MULTIPLIER))

    # Build the guardrail config only if a real guardrail ID is set.
    # This lets the example run during development without a configured
    # guardrail. In production, guardrails should always be on for
    # patient-facing output.
    converse_kwargs = {
        "modelId": MODEL_ID,
        "messages": [{"role": "user", "content": [{"text": segment["text"]}]}],
        "system": [{"text": system_prompt}],
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": TEMPERATURE,
            "topP": 0.9,
        },
    }
    if GUARDRAIL_ID and GUARDRAIL_ID != "your-guardrail-id-here":
        converse_kwargs["guardrailConfig"] = {
            "guardrailIdentifier": GUARDRAIL_ID,
            "guardrailVersion": GUARDRAIL_VERSION,
            "trace": "enabled",
        }

    response = bedrock_client.converse(**converse_kwargs)

    # Check for guardrail intervention. When the guardrail blocks, we
    # return the source segment unchanged and flag the segment for
    # review. Do not use whatever truncated/redacted text the guardrail
    # emitted; it's not safe to assume that output is a valid simplification.
    if response.get("stopReason") == "guardrail_intervened":
        logger.warning("Guardrail intervened on segment %d (type=%s)", segment["index"], seg_type)
        return {
            "text": segment["text"],
            "type": seg_type,
            "index": segment["index"],
            "simplified": False,
            "reason": "guardrail_intervened",
        }

    simplified_text = response["output"]["message"]["content"][0]["text"]

    return {
        "text": simplified_text,
        "type": seg_type,
        "index": segment["index"],
        "simplified": True,
    }
```

---

## Step 4: Validate Readability and Preservation

*The pseudocode calls this `validate_output(simplified_segment, must_preserve, target_grade)`. This is the automated quality gate. Two checks: did the reading level actually come down, and did every must-preserve entity survive? Both are deterministic, fast, and run without another LLM call. Segments that fail get flagged for review.*

```python
def calculate_flesch_kincaid_grade(text: str) -> float:
    """
    Compute Flesch-Kincaid grade level using textstat.

    textstat handles syllable counting, sentence splitting, and the
    formula itself. No syllable counter is perfect, but textstat is
    the standard library used in health literacy research.
    """
    # Short text sometimes produces unreliable scores. Treat very short
    # segments as automatically passing readability to avoid noise.
    if len(text.split()) < 10:
        return 0.0
    return textstat.flesch_kincaid_grade(text)

def validate_output(simplified_segment: dict, must_preserve: list[dict], target_grade: int = TARGET_GRADE) -> dict:
    """
    Check a simplified segment against readability and preservation rules.

    Two checks run, independently:

    1. Readability: is the Flesch-Kincaid grade level within tolerance
       of the target? Too far above target = warning or error based
       on how far.

    2. Preservation: do the must-preserve entities appear in the output?
       Verbatim entities (drug names, dosages) must match exactly,
       case-insensitive. Non-verbatim entities (conditions, procedures)
       are checked as informational only since they may have been
       translated to plain language, which is the whole point.

    Args:
        simplified_segment: Output from simplify_segment.
        must_preserve: Preservation list from extract_critical_entities.
        target_grade: Target Flesch-Kincaid grade level.

    Returns:
        A dict with:
          - valid: bool, false if any error-severity issue
          - grade_level: float, the computed Flesch-Kincaid grade
          - issues: list of {type, detail, severity} dicts
    """
    issues = []
    simplified_text = simplified_segment["text"]
    simplified_lower = simplified_text.lower()

    # --- Check 1: Readability ---
    grade_level = calculate_flesch_kincaid_grade(simplified_text)

    if grade_level > target_grade + GRADE_TOLERANCE * 2:
        # Way over target: hard error. Likely not simplified at all.
        issues.append({
            "type": "readability",
            "detail": f"Grade level {grade_level:.1f} far exceeds target {target_grade}",
            "severity": "error",
        })
    elif grade_level > target_grade + GRADE_TOLERANCE:
        # Moderately over: warning. Worth reviewing but probably usable.
        issues.append({
            "type": "readability",
            "detail": f"Grade level {grade_level:.1f} exceeds target {target_grade} + tolerance",
            "severity": "warning",
        })

    # --- Check 2: Entity preservation ---
    for entity in must_preserve:
        entity_lower = entity["text"].lower()
        found = entity_lower in simplified_lower

        if entity["preserve_verbatim"]:
            # Drug names, dosages, frequencies: must be exact match.
            # Missing one of these is always an error. The patient needs
            # to be able to verify "ticagrelor 90mg" at the pharmacy.
            if not found:
                issues.append({
                    "type": "preservation",
                    "detail": f"Missing verbatim entity: {entity['text']}",
                    "severity": "error",
                })
        else:
            # Conditions and procedures: informational check only.
            # A missing verbatim term here likely means it was translated,
            # which is fine. We log it so humans can spot-check.
            if not found:
                issues.append({
                    "type": "preservation",
                    "detail": f"Medical term not verbatim (may be translated): {entity['text']}",
                    "severity": "info",
                })

    has_errors = any(issue["severity"] == "error" for issue in issues)

    return {
        "valid": not has_errors,
        "grade_level": grade_level,
        "issues": issues,
    }
```

---

## Step 5: Assemble and Store the Simplified Document

*The pseudocode calls this `assemble_and_store(...)`. Reassemble the simplified segments in original order, compute an overall readability score, generate a cache key, and write the result with full audit metadata. The cache key (hash of source + target grade) lets you serve cached results for repeated simplification of the same template.*

```python
def assemble_and_store(
    document_id: str,
    original_text: str,
    simplified_segments: list[dict],
    validation_results: dict,
    must_preserve: list[dict],
    target_grade: int = TARGET_GRADE,
) -> dict:
    """
    Reassemble segments, compute overall metrics, and persist to DynamoDB.

    The stored record includes everything a reviewer or auditor might
    need: the original text, the simplified output, readability scores,
    which entities were supposed to be preserved, and any segments that
    failed validation. Cache key is a SHA-256 hash of (source text +
    target grade) so the same template simplified at the same target
    hits the cache on future calls.

    Args:
        document_id: Unique ID for this document.
        original_text: The source clinical text.
        simplified_segments: List of Step 3 output dicts, in order.
        validation_results: Dict mapping segment index -> Step 4 result.
        must_preserve: Preservation list from Step 1.
        target_grade: Target Flesch-Kincaid grade level.

    Returns:
        The full record written to DynamoDB.
    """
    # Reassemble in original order. Segments are already sorted by index
    # from Step 2, but sort defensively in case callers reorder.
    ordered = sorted(simplified_segments, key=lambda s: s["index"])
    final_document = "\n\n".join(s["text"] for s in ordered)

    # Collect segments that failed validation for human review.
    segments_needing_review = []
    for seg in ordered:
        validation = validation_results.get(seg["index"], {})
        if not validation.get("valid", True):
            segments_needing_review.append({
                "index": seg["index"],
                "type": seg["type"],
                "issues": validation.get("issues", []),
            })

    # Overall readability of the reassembled document.
    overall_grade = calculate_flesch_kincaid_grade(final_document)

    # Cache key: SHA-256 of source + target grade. Stable across runs,
    # safe to use as a DynamoDB sort key or secondary index.
    cache_key = hashlib.sha256(
        f"{original_text}|{target_grade}".encode("utf-8")
    ).hexdigest()

    record = {
        "document_id": document_id,
        "cache_key": cache_key,
        "original_text": original_text,
        "simplified_text": final_document,
        "target_grade": target_grade,
        # DynamoDB requires Decimal for numbers, not float. Convert
        # every float you plan to store or you'll get serialization errors.
        "achieved_grade": Decimal(str(round(overall_grade, 2))),
        "entities_preserved": [
            {
                "text": e["text"],
                "category": e["category"],
                "preserve_verbatim": e["preserve_verbatim"],
            }
            for e in must_preserve
        ],
        "segments_needing_review": segments_needing_review,
        "needs_review": len(segments_needing_review) > 0,
        "segment_count": len(ordered),
        "created_at": datetime.datetime.now(timezone.utc).isoformat(),
        "model_id": MODEL_ID,
        "prompt_version": "v1",
    }

    table = dynamodb.Table(RESULTS_TABLE)
    # put_item creates or overwrites. In production, add a
    # ConditionExpression if you need to protect existing records.
    table.put_item(Item=record)

    return record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. In a Lambda deployment, your handler would parse the incoming event (EHR webhook, S3 upload, API Gateway request), extract the clinical text and document ID, and call this function.

```python
def simplify_clinical_document(document_id: str, clinical_text: str, target_grade: int = TARGET_GRADE) -> dict:
    """
    Run the full medical terminology simplification pipeline.

    Steps (each maps to the main recipe's pseudocode):
      1. Extract critical medical entities for preservation
      2. Segment the document by content type
      3. Simplify each segment with type-specific prompts
      4. Validate readability and entity preservation per segment
      5. Assemble simplified segments and store the result

    Args:
        document_id: Unique identifier for this document.
        clinical_text: The raw clinical text to simplify.
        target_grade: Target Flesch-Kincaid grade level.

    Returns:
        The stored result record.
    """
    # Step 1: Build the preservation checklist.
    logger.info("Step 1: Extracting critical entities")
    must_preserve = extract_critical_entities(clinical_text)

    # Step 2: Segment the document.
    logger.info("Step 2: Segmenting document")
    segments = segment_document(clinical_text)

    # Step 3: Simplify each segment.
    logger.info("Step 3: Simplifying %d segments", len(segments))
    simplified_segments = []
    for segment in segments:
        result = simplify_segment(segment, must_preserve, target_grade)
        simplified_segments.append(result)
        logger.info(
            "  Segment %d (type=%s): simplified=%s",
            segment["index"],
            segment["type"],
            result["simplified"],
        )

    # Step 4: Validate each simplified segment.
    logger.info("Step 4: Validating segments")
    validation_results = {}
    for simplified in simplified_segments:
        validation = validate_output(simplified, must_preserve, target_grade)
        validation_results[simplified["index"]] = validation
        logger.info(
            "  Segment %d: valid=%s, grade=%.1f, issues=%d",
            simplified["index"],
            validation["valid"],
            validation["grade_level"],
            len(validation["issues"]),
        )

    # Step 5: Assemble and store.
    logger.info("Step 5: Assembling and storing result")
    record = assemble_and_store(
        document_id=document_id,
        original_text=clinical_text,
        simplified_segments=simplified_segments,
        validation_results=validation_results,
        must_preserve=must_preserve,
        target_grade=target_grade,
    )

    logger.info(
        "Done. achieved_grade=%s, needs_review=%s",
        record["achieved_grade"],
        record["needs_review"],
    )
    return record

# Example: simplify a cardiac discharge summary.
if __name__ == "__main__":
    sample_clinical_text = (
        "Diagnosis: Patient presented with acute ST-elevation myocardial "
        "infarction of the LAD territory.\n\n"
        "Procedure: Percutaneous coronary intervention performed with "
        "drug-eluting stent placement.\n\n"
        "Medications: Initiated dual antiplatelet therapy with aspirin 81mg "
        "daily and ticagrelor 90mg twice daily. Continue lisinopril 10mg daily.\n\n"
        "Follow up: Return to cardiology clinic in 2 weeks for reassessment "
        "of ventricular function. Call 555-0100 immediately if chest pain recurs."
    )

    result = simplify_clinical_document(
        document_id="doc-2026-05-01-discharge-00482",
        clinical_text=sample_clinical_text,
    )

    # Pretty-print. DynamoDB Decimal objects aren't JSON-serializable by
    # default, so convert them to float for display only.
    class DecimalEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Decimal):
                return float(obj)
            return super().default(obj)

    print(json.dumps(result, indent=2, cls=DecimalEncoder))
```

---

## The Gap Between This and Production

This example works. Point it at a real Bedrock endpoint with a configured guardrail and Comprehend Medical, feed it clinical text, and it will produce a simplified version with readability scores and entity preservation checks. But the distance between "runs as a script" and "runs at a health system simplifying thousands of documents per day" is substantial. Here's where that gap lives.

**Error handling.** Every external call here can fail. Bedrock throttles under load and returns `ThrottlingException`. Comprehend Medical rejects requests over 20,000 UTF-8 characters with `InvalidRequestException`. DynamoDB rejects items over 400KB. A production system wraps each call in try/except with specific handling, routes failed documents to a dead-letter queue, and alerts when error rates spike.

**Long-document chunking.** `extract_critical_entities` will fail on long hospital course summaries that exceed Comprehend Medical's 20,000-character limit. Production code chunks text at sentence boundaries, calls the API per chunk, and merges the entity lists while deduplicating across chunk boundaries. The simplify step has a similar constraint (Bedrock token limits) and needs the same treatment.

**Readability retry loop.** This implementation runs validation but doesn't retry. When a segment fails the readability check, production systems re-prompt with more aggressive simplification instructions ("Use even shorter sentences. Replace ALL medical terms.") up to a retry limit, then flag for human review. The main recipe's Honest Take calls this out specifically as the loop you'll want.

**Entity matching sophistication.** `validate_output` uses simple substring matching. This works for exact preservation ("ticagrelor 90mg") but produces false positives when a plain-language translation happens to contain the medical term, or false negatives when punctuation differs. Production adds tokenization, fuzzy matching with a small edit-distance threshold, and an allowlist of known translations (e.g., "myocardial infarction" -> "heart attack") so non-verbatim preservation checks can recognize valid translations.

**Readability formula limitations.** Flesch-Kincaid measures surface complexity (syllables, sentence length) but not conceptual complexity. A sentence using only short words can still confuse a patient if the concept is abstract. Use the score as a floor, not a ceiling. Supplement with periodic human evaluation and tracking of patient-reported comprehension over time.

**Prompt versioning and A/B testing.** Prompts live as Python constants here. Production stores them in S3 (versioned bucket), routes a percentage of traffic to new prompt versions, and tracks readability scores and validation pass rates per version. Promote prompts that improve scores; roll back prompts that degrade them. Store `prompt_version` in every record so you can correlate.

**Caching layer.** The cache_key is computed but never checked. Production looks up the cache before calling Bedrock: if the exact source text at the exact target grade has been simplified before, serve the cached result. For standard discharge templates (knee replacement, cataract surgery), this alone can cut Bedrock spend significantly.

**Multi-language support.** This produces simplified English only. For limited English proficient populations, chain Amazon Translate after simplification. Simplify first in English, then translate the simplified version. Translating raw clinical English produces worse output than translating already-simplified English.

**Structured logging and metrics.** The `logger.info()` calls are a start. Production emits JSON logs with consistent fields (document_id, doc_type, segment_count, achieved_grade, validation_passed, latency_ms, token_count) and CloudWatch metrics for end-to-end latency (p50/p95/p99), validation pass rate, guardrail intervention rate, and human review rate. Validation pass rate is your north star metric.

**Human review workflow.** Segments that fail validation get flagged in the stored record, but this code doesn't implement the review queue. Production routes flagged documents to an SQS queue feeding a review UI where health literacy specialists can edit, approve, or reject. Track reviewer edit distance over time to identify systemic prompt weaknesses.

**IAM least-privilege.** The Lambda role should have exactly: `bedrock:InvokeModel` scoped to your model ARN, `bedrock:ApplyGuardrail` scoped to your guardrail ARN, `comprehendmedical:DetectEntitiesV2`, and `dynamodb:PutItem` scoped to the table ARN. Not `bedrock:*`. Not `dynamodb:*`.

**VPC and encryption.** In production, the Lambda runs in a VPC with private subnets. VPC endpoints for Bedrock, Comprehend Medical, DynamoDB, CloudWatch Logs, and KMS keep all traffic on the AWS backbone. Use KMS customer-managed keys with rotation enabled for the DynamoDB table and CloudWatch Logs. Clinical text is PHI and should never traverse the public internet.

**Idempotency.** If the same document event fires twice (common with at-least-once delivery), you don't want duplicate simplifications. Add a `ConditionExpression` on the `put_item` call that checks for document_id non-existence, or use the cache_key lookup as a dedupe layer.

**Testing.** There are no tests here. A production pipeline has: unit tests for `segment_document` and `validate_output` with edge cases (empty text, very short segments, Unicode), integration tests against Bedrock and Comprehend Medical with known clinical text samples, and regression tests confirming that degraded simplifications (intentionally dropped medications, altered doses) are caught by `validate_output`. Never use real patient documents in test fixtures. Synthesize clinical text instead.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 2.2: Medical Terminology Simplification](chapter02.02-medical-terminology-simplification) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
