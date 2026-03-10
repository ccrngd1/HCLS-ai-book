# Recipe 1.4: Prior Authorization Document Processing: Python Example 

> **Important:** This is an illustrative implementation, not a production-ready deployment. It demonstrates the patterns from the recipe pseudocode using real boto3 API calls, with inline comments explaining what each piece does and why. The "Gap to Production" section at the end describes what you'd need to add before running this in a real environment. Think of this as a detailed starting point, not a finished product.

---

## Setup

```bash
pip install boto3 python-dotenv
```
 

> **Python version note:** This example uses built-in generic type hints (`list[dict]`, `dict[int, dict]`) which require Python 3.9 or later. AWS Lambda supports Python 3.9, 3.10, 3.11, 3.12, and 3.13 runtimes. If you need Python 3.8 compatibility, replace these with `from typing import List, Dict` and use `List[dict]`, `Dict[int, dict]` instead.

You'll need AWS credentials with the following permissions:
- `textract:StartDocumentAnalysis`, `textract:GetDocumentAnalysis`
- `s3:GetObject`, `s3:PutObject`
- `bedrock:InvokeModel` on `us.amazon.nova-lite-v1:0` and `us.anthropic.claude-sonnet-4-6-v1:0`
- `comprehendmedical:InferICD10CM`
- `dynamodb:PutItem`
- `sns:Publish` (for Textract job notifications)
- `states:StartExecution` (if using Step Functions)

Enable Nova Lite and Claude Sonnet 4.6 in your Bedrock console (Model Access) before running this code. Cross-region inference profiles handle regional routing automatically.

---

## Configuration and Constants

These go first because they're really configuration, not logic. If you're deploying this for real, most of these become environment variables or Parameter Store values.

```python
import json
import time
import boto3
import logging
from datetime import datetime, timezone
from decimal import Decimal
from botocore.config import Config  # [EDITOR: review fix P1-4] Added for retry configuration

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry configuration for Bedrock and Comprehend Medical clients.
# ThrottlingException is expected at healthcare volume during peak hours.
# "adaptive" mode implements exponential backoff with jitter, appropriate
# for throttling scenarios. max_attempts=3 covers transient spikes without
# compounding latency excessively.
# ---------------------------------------------------------------------------
# [EDITOR: review fix P1-4] Added retry config. Bedrock ThrottlingException is
# a certainty at 500K submissions/year with burst patterns, not an edge case.
# Both Bedrock runtime and Comprehend Medical clients need this.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 3, "mode": "adaptive"}
)

# ---------------------------------------------------------------------------
# Model configuration
# Use cross-region inference profile IDs, not direct model IDs.
# Cross-region profiles route to the best available region automatically
# and handle regional capacity differences for you.
# ---------------------------------------------------------------------------
CLASSIFICATION_MODEL_ID = "us.amazon.nova-lite-v1:0"
CLINICAL_MODEL_ID = "us.anthropic.claude-sonnet-4-6-v1:0"

# ---------------------------------------------------------------------------
# Confidence thresholds
# These are starting points. Tune them against your actual data.
# ---------------------------------------------------------------------------
CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.60   # below this → human review
PAGE_CONFIDENCE_THRESHOLD = 75.0             # below this → flag page
ICD10_CONFIDENCE_THRESHOLD = 0.70            # below this → flag code

# ---------------------------------------------------------------------------
# Cover sheet field map
# Maps canonical field names to all the label variants we've seen.
# "Service Requested Code" and "Dx Indication" are in here because those
# are real labels used by real payers that would trip up a simple keyword list.
# ---------------------------------------------------------------------------
PA_COVER_FIELD_MAP = {
    "member_name": [
        "member name", "patient name", "subscriber name", "insured name"
    ],
    "member_id": [
        "member id", "subscriber id", "member #", "id number"
    ],
    "member_dob": [
        "date of birth", "dob", "member dob", "patient dob"
    ],
    "requesting_provider": [
        "requesting provider", "ordering physician", "rendering provider",
        "treating physician", "provider name"
    ],
    "provider_npi": [
        "npi", "provider npi", "npi number", "national provider"
    ],
    "requesting_facility": [
        "facility", "practice name", "clinic name", "hospital"
    ],
    "requested_cpt": [
        "cpt code", "procedure code", "procedure", "service code",
        "requested procedure", "service requested code"
    ],
    "diagnosis_code": [
        "diagnosis code", "icd-10", "icd code", "dx", "icd-10-cm",
        "dx indication", "diagnosis indication"
    ],
    "date_of_service": [
        "date of service", "dos", "requested date", "service date"
    ],
    "urgency": [
        "urgency", "urgent", "priority", "expedited", "stat"
    ],
}

# ---------------------------------------------------------------------------
# Lab column map
# Same pattern as the cover sheet field map, applied to lab results tables.
# ---------------------------------------------------------------------------
LAB_COLUMN_MAP = {
    "test_name": ["test", "test name", "analyte", "component", "description"],
    "result": ["result", "value", "result value", "your result"],
    "units": ["units", "unit"],
    "reference_range": [
        "reference range", "normal range", "reference interval",
        "normal values", "expected range"
    ],
    "flag": ["flag", "abnormal flag", "indicator", "h/l"],
}

# ---------------------------------------------------------------------------
# LLM prompts
# These live here as constants so they're easy to find, version, and test.
# In production, consider loading from Parameter Store or S3 so you can
# update prompts without redeploying the Lambda.
# ---------------------------------------------------------------------------
CLASSIFICATION_SYSTEM_PROMPT = """
You are a healthcare document classifier. Your job is to identify what type of document
page you are reading from a prior authorization submission.

Return ONLY a valid JSON object with these fields:
{
  "page_type": "<one of: cover_sheet, clinical_note, physician_letter, lab_results, imaging_report, other>",
  "confidence": <0.0 to 1.0>,
  "reasoning": "<one sentence explaining your classification>"
}

Document types:
- cover_sheet: administrative form with fields like member ID, provider NPI,
  CPT code, date of service. Usually has checkboxes and form fields.
- clinical_note: physician office note with sections like History of Present
  Illness, Assessment, Plan. Written by a treating clinician.
- physician_letter: letter written by a physician explaining medical necessity,
  treatment history, or requesting authorization for a specific procedure.
- lab_results: laboratory test results page with test names, numeric values,
  units, and reference ranges. Usually presented as a table.
- imaging_report: radiology or other imaging report with sections like Findings,
  Impression, and Technique. Written by a radiologist.
- other: anything that does not clearly fit the above categories.

Be conservative with confidence. Only return 0.9 or higher if the classification
is unambiguous. Return 0.7-0.89 for likely classifications. Below 0.7 for uncertain cases.
""".strip()

CLINICAL_EXTRACTION_SYSTEM_PROMPT = """
You are a clinical documentation analyst reviewing pages from prior authorization submissions.
Your job is to extract all clinically relevant information needed to evaluate a prior
authorization request.

Return ONLY a valid JSON object with this structure:
{
  "diagnosis_text": "<the primary diagnosis or diagnoses as written in this document>",
  "conditions": ["<list of medical conditions, diseases, diagnoses mentioned>"],
  "medications": ["<list of medications with dosages if present>"],
  "procedures": ["<list of procedures, treatments, or tests mentioned>"],
  "medical_necessity_evidence": "<free text: evidence supporting medical necessity, including clinical findings, severity indicators, and impact on function>",
  "failed_treatments": ["<list of prior treatments that were tried and failed or were insufficient, with duration if mentioned>"],
  "supporting_findings": "<relevant clinical findings, test results, or imaging findings mentioned in this document>",
  "confidence": <0.0 to 1.0, your confidence in the extraction completeness>
}

Extract only what is explicitly stated in the document. Do not infer or add information
not present in the text. If a field has no relevant content, use an empty list or
empty string. The medical_necessity_evidence and failed_treatments fields are the
most important for prior authorization decisions.
""".strip()
```

---

## Step 1: Submit Textract Async Job

This matches the async Textract pattern from Recipe 1.2. LAYOUT is the addition here; it gives us structural signals about each page that feed into the LLM classification prompt.

```python
def start_textract_job(
    s3_bucket: str,
    s3_key: str,
    sns_topic_arn: str,
    sns_role_arn: str,
    region: str = "us-east-1"
) -> str:
    """
    Submit a prior auth PDF to Textract for async analysis.
    Returns the Textract job ID. The Lambda that calls this can exit
    immediately; the SNS notification will trigger the next Lambda when done.
    """
    textract = boto3.client("textract", region_name=region)

    response = textract.start_document_analysis(
        DocumentLocation={
            "S3Object": {
                "Bucket": s3_bucket,
                "Name": s3_key,
            }
        },
        # FORMS: key-value pairs (cover sheet fields)
        # TABLES: tabular data (lab results)
        # LAYOUT: high-level page structure (helps the LLM classification prompt)
        FeatureTypes=["FORMS", "TABLES", "LAYOUT"],
        NotificationChannel={
            "SNSTopicArn": sns_topic_arn,
            "RoleArn": sns_role_arn,
        },
        # Store raw Textract output in S3 alongside the source document.
        # This is useful for debugging and avoids the 256KB Step Functions payload limit.
        OutputConfig={
            "S3Bucket": s3_bucket,
            "S3Prefix": "textract-outputs/",
        },
    )

    job_id = response["JobId"]
    logger.info(f"Started Textract job {job_id} for {s3_key}")
    return job_id
```

---

## Step 2: Retrieve Textract Results

Fires on the SNS completion notification. Retrieves all result pages via paginated `GetDocumentAnalysis`.

```python
def retrieve_textract_blocks(
    job_id: str,
    region: str = "us-east-1"
) -> list[dict]:
    """
    Retrieve all Textract blocks for a completed job.
    GetDocumentAnalysis is paginated; most multi-page documents produce multiple
    pages of results. This loops until NextToken is absent, collecting all blocks.
    """
    # [EDITOR: Removed em dash from docstring. Original: "is paginated — most
    # multi-page documents have multiple pages of results." Changed to semicolon.]
    textract = boto3.client("textract", region_name=region)
    all_blocks = []
    next_token = None

    while True:
        kwargs = {"JobId": job_id}
        if next_token:
            kwargs["NextToken"] = next_token

        response = textract.get_document_analysis(**kwargs)

        # Verify the job actually succeeded before processing
        job_status = response["JobStatus"]
        if job_status == "FAILED":
            error_message = response.get("StatusMessage", "Unknown error")
            raise RuntimeError(f"Textract job {job_id} failed: {error_message}")
        if job_status != "SUCCEEDED":
            raise RuntimeError(
                f"Textract job {job_id} has unexpected status: {job_status}"
            )

        all_blocks.extend(response.get("Blocks", []))

        next_token = response.get("NextToken")
        if not next_token:
            break

    logger.info(f"Retrieved {len(all_blocks)} blocks from Textract job {job_id}")
    return all_blocks
```

---

## Step 3: Group Blocks by Page

Takes the flat list of Textract blocks and organizes them by page number. Also extracts structural signals per page (has_tables, has_forms) for the classification prompt.

```python
def group_blocks_by_page(all_blocks: list[dict]) -> dict[int, dict]:
    """
    Group Textract blocks by page number and extract page-level signals.

    Returns a dict of page_num -> {
        blocks: list of all blocks on this page,
        text: concatenated LINE block text (full page text for LLM),
        has_tables: bool (TABLE blocks present),
        has_forms: bool (KEY_VALUE_SET blocks present),
        layout_blocks: list of LAYOUT_* blocks,
        line_confidences: list of per-LINE confidence scores
    }
    """
    pages = {}

    for block in all_blocks:
        page_num = block.get("Page", 1)  # Textract page numbers are 1-indexed

        if page_num not in pages:
            pages[page_num] = {
                "blocks": [],
                "text": "",
                "has_tables": False,
                "has_forms": False,
                "layout_blocks": [],
                "line_confidences": [],
            }

        pages[page_num]["blocks"].append(block)
        block_type = block.get("BlockType", "")

        if block_type == "LINE":
            # Accumulate the full page text for the LLM.
            # LINE blocks give us clean, reading-order text without the noise
            # of individual WORD blocks.
            pages[page_num]["text"] += block.get("Text", "") + "\n"
            confidence = block.get("Confidence", 0.0)
            pages[page_num]["line_confidences"].append(confidence)

        elif block_type == "TABLE":
            pages[page_num]["has_tables"] = True

        elif block_type == "KEY_VALUE_SET":
            pages[page_num]["has_forms"] = True

        elif block_type.startswith("LAYOUT_"):
            pages[page_num]["layout_blocks"].append(block)

    return pages
```

---

## Step 4: Classify Pages with Nova Lite

The LLM replaces the keyword classifier. Note the structural metadata in the user message: including whether the page has form fields and tables helps the model on ambiguous pages.

```python
def classify_page(
    page_text: str,
    has_tables: bool,
    has_forms: bool,
    model_id: str = CLASSIFICATION_MODEL_ID,
    region: str = "us-east-1"
) -> dict:
    """
    Classify a single page using a foundation model via the Bedrock Converse API.

    Uses Nova Lite by default: it's the cheapest multimodal model and handles
    classification tasks reliably. Temperature=0 for near-deterministic output.

    Returns a dict with page_type, confidence (0.0-1.0), and reasoning.
    """
    # [EDITOR: Removed em dash from docstring. Original: "by default — it's the
    # cheapest multimodal model". Changed to colon.]
    bedrock = boto3.client("bedrock-runtime", region_name=region, config=BOTO3_RETRY_CONFIG)  # [EDITOR: review fix P1-4] Added retry config to prevent ThrottlingException failures

    # Build structural context to include alongside the page text.
    # This helps the model on pages where text alone is ambiguous.
    structural_parts = []
    if has_forms:
        structural_parts.append("This page contains form fields (key-value pairs).")
    if has_tables:
        structural_parts.append("This page contains one or more tables.")
    if not has_forms and not has_tables:
        structural_parts.append(
            "This page is primarily flowing text with no form fields or tables."
        )

    structural_context = " ".join(structural_parts)
    user_message = f"{structural_context}\n\nPage text:\n{page_text}"

    # Truncate very long pages to avoid hitting token limits.
    # Most clinical pages are well under 4000 chars; very long pages are unusual.
    # If you're seeing truncation frequently, your pages may need chunking.
    if len(user_message) > 4000:
        user_message = user_message[:4000] + "\n\n[Page truncated for classification]"

    try:
        response = bedrock.converse(
            modelId=model_id,
            system=[{"text": CLASSIFICATION_SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": user_message}],
                }
            ],
            inferenceConfig={
                "maxTokens": 256,   # Classification JSON is small
                "temperature": 0,   # Near-deterministic output
            },
        )

        response_text = response["output"]["message"]["content"][0]["text"]

        # The model should return a JSON object. Strip any markdown code fences
        # in case the model wraps it; some models do this despite being told not to.
        # [EDITOR: Removed em dash from inline comment. Original: "wraps it —
        # some models do this". Changed to semicolon.]
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

        result = json.loads(cleaned)

        # Validate required fields are present
        page_type = result.get("page_type", "other")
        confidence = float(result.get("confidence", 0.0))
        reasoning = result.get("reasoning", "")

        # Clamp confidence to [0, 1] in case the model returns something odd
        confidence = max(0.0, min(1.0, confidence))

        logger.info(
            f"Classified page as {page_type} "
            f"(confidence {confidence:.2f}): {reasoning}"
        )

        return {
            "page_type": page_type,
            "confidence": confidence,
            "reasoning": reasoning,
        }

    except json.JSONDecodeError as e:
        # If JSON parsing fails, log it and return a low-confidence "other" result.
        # This routes the page to human review rather than crashing the pipeline.
        # [EDITOR: review fix P1-5] Removed response_text[:200] from log message.
        # LLM output may contain PHI echoed from the input document. Log only
        # structural metadata (response length, error type) — never log model output.
        logger.warning(
            f"Classification response was not valid JSON: {e}. "
            f"Response length: {len(response_text)} chars. "
            f"[LLM response content omitted from logs to prevent PHI exposure]"
        )
        return {
            "page_type": "other",
            "confidence": 0.0,
            "reasoning": "Classification failed: model returned non-JSON response",
        }
    except Exception as e:
        logger.error(f"Classification failed: {e}")
        return {
            "page_type": "other",
            "confidence": 0.0,
            "reasoning": f"Classification failed: {str(e)}",
        }


def classify_all_pages(
    pages: dict[int, dict],
    model_id: str = CLASSIFICATION_MODEL_ID,
    region: str = "us-east-1"
) -> dict[int, dict]:
    """
    Classify all pages in the document.
    In production, Step Functions Map state runs these in parallel.
    This sequential version is appropriate for single-Lambda implementations.
    """
    classifications = {}

    for page_num in sorted(pages.keys()):
        page_data = pages[page_num]
        result = classify_page(
            page_text=page_data["text"],
            has_tables=page_data["has_tables"],
            has_forms=page_data["has_forms"],
            model_id=model_id,
            region=region,
        )
        classifications[page_num] = result

    return classifications
```

---

## Step 5a: Cover Sheet Extractor (Textract FORMS)

Cover sheets are structured forms. Textract handles them better and cheaper than an LLM would.

```python
def parse_key_value_pairs(blocks: list[dict], block_map: dict) -> list[dict]:
    """
    Extract key-value pairs from Textract KEY_VALUE_SET blocks.
    Returns a list of {key, value, key_confidence, value_confidence} dicts.
    """
    kvs = []

    for block in blocks:
        if block.get("BlockType") != "KEY_VALUE_SET":
            continue
        entity_types = block.get("EntityTypes", [])
        if "KEY" not in entity_types:
            continue  # Only process KEY blocks; VALUE blocks are linked from KEYs

        key_text = ""
        key_confidence = 0.0
        value_text = ""
        value_confidence = 0.0

        # Build key text from child WORD blocks
        for rel in block.get("Relationships", []):
            if rel["Type"] == "CHILD":
                for child_id in rel["Ids"]:
                    child = block_map.get(child_id, {})
                    if child.get("BlockType") == "WORD":
                        key_text += child.get("Text", "") + " "
                        key_confidence = max(
                            key_confidence, child.get("Confidence", 0.0)
                        )

            elif rel["Type"] == "VALUE":
                # Follow VALUE relationship to get the value block
                for value_id in rel["Ids"]:
                    value_block = block_map.get(value_id, {})
                    for value_rel in value_block.get("Relationships", []):
                        if value_rel["Type"] == "CHILD":
                            for word_id in value_rel["Ids"]:
                                word = block_map.get(word_id, {})
                                if word.get("BlockType") == "WORD":
                                    value_text += word.get("Text", "") + " "
                                    value_confidence = max(
                                        value_confidence,
                                        word.get("Confidence", 0.0),
                                    )

        key_text = key_text.strip().lower()
        value_text = value_text.strip()

        if key_text:
            kvs.append({
                "key": key_text,
                "value": value_text,
                "key_confidence": key_confidence,
                "value_confidence": value_confidence,
            })

    return kvs


def normalize_cover_fields(raw_kvs: list[dict]) -> tuple[dict, list[str]]:
    """
    Map raw key-value pairs to canonical field names using PA_COVER_FIELD_MAP.
    Returns (normalized_fields, flagged_fields).

    Flagged fields are ones where confidence fell below the threshold.
    """
    normalized = {}
    flagged = []

    for kv in raw_kvs:
        key = kv["key"].lower().strip()
        value = kv["value"]
        confidence = kv.get("value_confidence", 100.0)

        # Find the canonical name for this key label
        canonical = None
        for canonical_name, variants in PA_COVER_FIELD_MAP.items():
            if key in variants:
                canonical = canonical_name
                break

        if canonical:
            # Keep the highest-confidence value if the same field appears twice
            if canonical not in normalized or confidence > normalized[canonical]["confidence"]:
                normalized[canonical] = {
                    "value": value,
                    "confidence": confidence,
                }

            if confidence < 85.0:
                flagged.append(f"{canonical}:low_confidence:{confidence:.1f}")

    # Flatten to {field: value} for the assembled record
    result = {k: v["value"] for k, v in normalized.items()}
    return result, flagged


def extract_cover_sheet(page_data: dict, block_map: dict, _model_id: str) -> dict:
    """
    Extract cover sheet fields using Textract key-value pairs.
    model_id is unused here; cover sheets don't need LLM reasoning.
    """
    # [EDITOR: Removed em dash from docstring. Original: "unused here —
    # cover sheets don't need LLM reasoning." Changed to semicolon.]
    raw_kvs = parse_key_value_pairs(page_data["blocks"], block_map)
    fields, flagged = normalize_cover_fields(raw_kvs)

    # Page confidence: average of all KEY_VALUE confidence scores
    confidences = [
        kv.get("value_confidence", 0.0) for kv in raw_kvs if kv.get("value")
    ]
    avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

    return {
        "confidence": avg_confidence,
        "data": fields,
        "flagged": flagged,
    }
```

---

## Step 5b: Clinical Page Extractor (Bedrock Sonnet 4.6 + Comprehend Medical)

Clinical notes, physician letters, and imaging reports go through Sonnet 4.6 for reasoning, then Comprehend Medical for ICD-10 code validation.

```python
def infer_icd10_codes(
    diagnosis_text: str,
    confidence_threshold: float = ICD10_CONFIDENCE_THRESHOLD,
    region: str = "us-east-1"
) -> tuple[list[dict], list[dict]]:
    """
    Use Comprehend Medical InferICD10CM to map clinical text to ICD-10 codes.
    Returns (accepted, flagged) where flagged = codes below the confidence threshold.

    Important: InferICD10CM expects natural language ("severe osteoarthritis right knee"),
    NOT code strings ("M17.11"). If the LLM extracted a raw code string, this will
    produce poor results. The LLM should always extract the clinical concept text.
    """
    comprehend_medical = boto3.client("comprehendmedical", region_name=region, config=BOTO3_RETRY_CONFIG)  # [EDITOR: review fix P1-4] Added retry config; Comprehend Medical also throttles at volume

    # Comprehend Medical has a 20,000 character input limit.
    # Truncate if needed; the diagnosis text from LLM extraction is usually short.
    truncated_text = diagnosis_text[:20000]

    response = comprehend_medical.infer_icd10_cm(Text=truncated_text)

    accepted = []
    flagged = []

    for entity in response.get("Entities", []):
        # Each entity may have multiple candidate ICD-10 codes.
        # Concepts are sorted by score descending; take the top match.
        # [EDITOR: Removed em dash from comment. Original: "score descending —
        # take the top match". Changed to semicolon.]
        icd10_concepts = entity.get("ICD10CMConcepts", [])
        if not icd10_concepts:
            continue

        best = icd10_concepts[0]
        entry = {
            "text": entity.get("Text", ""),
            "icd10_code": best.get("Code", ""),
            "description": best.get("Description", ""),
            "confidence": round(best.get("Score", 0.0), 4),
        }

        if best.get("Score", 0.0) >= confidence_threshold:
            accepted.append(entry)
        else:
            flagged.append(entry)

    return accepted, flagged


def extract_clinical_page(
    page_data: dict,
    block_map: dict,
    clinical_model_id: str = CLINICAL_MODEL_ID,
    region: str = "us-east-1"
) -> dict:
    """
    Extract clinical evidence from a narrative page using Bedrock Sonnet 4.6.

    This replaces the Comprehend Medical DetectEntitiesV2 approach with a single
    LLM call that extracts structured clinical evidence including:
    - Medical necessity evidence (free text narrative)
    - Failed prior treatments (crucial for authorization decisions)
    - Supporting clinical findings

    After LLM extraction, Comprehend Medical validates the ICD-10 codes.
    """
    bedrock = boto3.client("bedrock-runtime", region_name=region, config=BOTO3_RETRY_CONFIG)  # [EDITOR: review fix P1-4] Added retry config for Bedrock throttling
    page_text = page_data["text"]

    if not page_text.strip():
        return {
            "confidence": 0.0,
            "data": {
                "diagnosis_text": "",
                "conditions": [],
                "medications": [],
                "procedures": [],
                "medical_necessity_evidence": "",
                "failed_treatments": [],
                "supporting_findings": "",
                "icd10_codes": [],
            },
            "flagged": {"reason": "empty_page_text"},
        }

    user_content = (
        "Extract clinical information from this document page:\n\n" + page_text
    )

    llm_extraction = None
    response_text = ""

    try:
        response = bedrock.converse(
            modelId=clinical_model_id,
            system=[{"text": CLINICAL_EXTRACTION_SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": user_content}],
                }
            ],
            inferenceConfig={
                "maxTokens": 1024,  # More than classification; clinical notes are dense
                "temperature": 0,
            },
        )
        # [EDITOR: Removed em dash from inline comment. Original:
        # "More than classification — clinical notes are dense". Changed to semicolon.]

        response_text = response["output"]["message"]["content"][0]["text"]

        # Strip markdown code fences if present
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        cleaned = cleaned.strip()

        llm_extraction = json.loads(cleaned)

    except json.JSONDecodeError as e:
        # [EDITOR: review fix P1-5] Removed response_text[:200] from log message.
        # The first 200 chars of a clinical extraction response can contain patient
        # names, diagnoses, or other PHI echoed from the input. Log only structural
        # metadata (response length, error type) — never log raw model output.
        logger.warning(
            f"Clinical extraction response was not valid JSON: {e}. "
            f"Response length: {len(response_text)} chars. "
            f"[LLM response content omitted from logs to prevent PHI exposure]"
        )
        # Return empty extraction rather than crashing; this page goes to review
        return {
            "confidence": 0.0,
            "data": {
                "diagnosis_text": "",
                "conditions": [],
                "medications": [],
                "procedures": [],
                "medical_necessity_evidence": "",
                "failed_treatments": [],
                "supporting_findings": "",
                "icd10_codes": [],
            },
            "flagged": {"reason": "llm_json_parse_error"},
        }
    except Exception as e:
        logger.error(f"Clinical extraction failed: {e}")
        raise

    # ICD-10 code validation via Comprehend Medical.
    # The LLM extracted the clinical concept text; Comprehend maps it to codes.
    # This hybrid gets us contextual extraction AND purpose-built code lookup.
    icd10_accepted = []
    icd10_flagged = []

    diagnosis_text = llm_extraction.get("diagnosis_text", "")
    if diagnosis_text:
        try:
            icd10_accepted, icd10_flagged = infer_icd10_codes(diagnosis_text, region=region)
        except Exception as e:
            logger.warning(f"ICD-10 inference failed: {e}. Continuing without codes.")
            icd10_flagged = [{"reason": f"comprehend_medical_error: {str(e)}"}]

    # Effective page confidence: LLM's self-reported confidence, capped by OCR quality.
    # A high-confidence LLM extraction on a low-quality OCR page isn't reliable.
    line_confidences = page_data.get("line_confidences", [])
    if line_confidences:
        textract_avg = sum(line_confidences) / len(line_confidences)
    else:
        textract_avg = 100.0  # No LINE blocks = structural page, not a problem

    llm_confidence = float(llm_extraction.get("confidence", 0.0))
    effective_confidence = min(llm_confidence, textract_avg / 100.0) * 100.0

    return {
        "confidence": effective_confidence,
        "data": {
            "diagnosis_text": llm_extraction.get("diagnosis_text", ""),
            "conditions": llm_extraction.get("conditions", []),
            "medications": llm_extraction.get("medications", []),
            "procedures": llm_extraction.get("procedures", []),
            "medical_necessity_evidence": llm_extraction.get(
                "medical_necessity_evidence", ""
            ),
            "failed_treatments": llm_extraction.get("failed_treatments", []),
            "supporting_findings": llm_extraction.get("supporting_findings", ""),
            "icd10_codes": icd10_accepted,
        },
        "flagged": {
            "icd10_uncertain": icd10_flagged,
        },
    }
```

---

## Step 5c: Lab Results Extractor (Textract TABLES)

Lab results pages are structured tables. Textract handles these better and cheaper than an LLM would. No need to bring Bedrock into this path. 

```python
def normalize_lab_columns(headers: list[str]) -> dict[int, str]:
    """
    Map column header text to canonical lab field names using LAB_COLUMN_MAP.
    Returns {col_index: canonical_name} for matched columns.
    """
    mapping = {}
    for col_idx, header in enumerate(headers):
        header_lower = header.lower().strip()
        for canonical_name, variants in LAB_COLUMN_MAP.items():
            if header_lower in variants:
                mapping[col_idx] = canonical_name
                break
    return mapping


def parse_tables_from_blocks(
    blocks: list[dict],
    block_map: dict
) -> list[list[list[str]]]:
    """
    Extract tables from Textract TABLE blocks.
    Returns a list of tables, where each table is a list of rows,
    and each row is a list of cell text strings.
    """
    tables = []

    for block in blocks:
        if block.get("BlockType") != "TABLE":
            continue

        # Find the max row and column count
        cells = []
        for rel in block.get("Relationships", []):
            if rel["Type"] == "CHILD":
                for cell_id in rel["Ids"]:
                    cell_block = block_map.get(cell_id, {})
                    if cell_block.get("BlockType") == "CELL":
                        row_idx = cell_block.get("RowIndex", 1) - 1
                        col_idx = cell_block.get("ColumnIndex", 1) - 1

                        # Get cell text from child WORD blocks
                        cell_text = ""
                        for cell_rel in cell_block.get("Relationships", []):
                            if cell_rel["Type"] == "CHILD":
                                for word_id in cell_rel["Ids"]:
                                    word = block_map.get(word_id, {})
                                    if word.get("BlockType") == "WORD":
                                        cell_text += word.get("Text", "") + " "

                        cells.append((row_idx, col_idx, cell_text.strip()))

        if not cells:
            continue

        # Build the 2D grid
        max_row = max(r for r, _, _ in cells) + 1
        max_col = max(c for _, c, _ in cells) + 1
        grid = [[""] * max_col for _ in range(max_row)]
        for row_idx, col_idx, text in cells:
            grid[row_idx][col_idx] = text

        tables.append(grid)

    return tables


def extract_lab_page(
    page_data: dict,
    block_map: dict,
    _model_id: str  # Unused; lab pages don't need LLM
) -> dict:
    """
    Extract lab results from Textract TABLE blocks.
    """
    tables = parse_tables_from_blocks(page_data["blocks"], block_map)
    lab_values = []

    for table in tables:
        if len(table) < 2:
            continue  # Header-only or empty table; skip

        headers = table[0]
        col_mapping = normalize_lab_columns(headers)

        for row in table[1:]:
            entry = {}
            for col_idx, canonical_name in col_mapping.items():
                if col_idx < len(row):
                    entry[canonical_name] = row[col_idx].strip()

            # Only include rows that have at least a test name and result
            if "test_name" in entry and "result" in entry:
                lab_values.append(entry)

    # Table cell confidence: average TABLE block confidence from Textract
    table_confidences = [
        block.get("Confidence", 0.0)
        for block in page_data["blocks"]
        if block.get("BlockType") == "TABLE"
    ]
    avg_confidence = (
        sum(table_confidences) / len(table_confidences)
        if table_confidences
        else 75.0  # Default if no TABLE blocks
    )

    return {
        "confidence": avg_confidence,
        "data": {"lab_values": lab_values},
        "flagged": [],
    }
```

---

## Step 5d: Route and Extract

Dispatches each page to the right extractor based on classification results.

```python
# The routing table. Each extractor has the same signature:
# (page_data, block_map, model_id) -> {confidence, data, flagged}
EXTRACTION_ROUTER = {
    "cover_sheet": extract_cover_sheet,
    "clinical_note": extract_clinical_page,
    "physician_letter": extract_clinical_page,
    "imaging_report": extract_clinical_page,
    "lab_results": extract_lab_page,
    "other": None,  # Pass-through; raw text only
}


def route_and_extract(
    page_num: int,
    classification: dict,
    page_data: dict,
    block_map: dict,
    clinical_model_id: str = CLINICAL_MODEL_ID,
    region: str = "us-east-1",
) -> dict:
    """
    Route a page to the appropriate extractor and return the result.

    Low-confidence classifications go straight to human review rather than
    extraction. A wrong classification followed by wrong extraction is worse
    than sending the page to review directly.
    """
    # [EDITOR: Removed em dash from docstring. Original: "rather than extraction —
    # a wrong classification followed by wrong extraction is worse". Restructured
    # to two sentences.]
    confidence = classification["confidence"]
    page_type = classification["page_type"]

    if confidence < CLASSIFICATION_CONFIDENCE_THRESHOLD:
        return {
            "page_num": page_num,
            "page_type": "uncertain",
            "confidence": confidence * 100,
            "data": {"raw_text": page_data["text"]},
            "flagged": ["low_classification_confidence"],
        }

    extractor = EXTRACTION_ROUTER.get(page_type)

    if extractor is None:
        # "other" pages: preserve raw text and flag for review
        return {
            "page_num": page_num,
            "page_type": "other",
            "confidence": confidence * 100,
            "data": {"raw_text": page_data["text"]},
            "flagged": ["unrecognized_page_type"],
        }

    result = extractor(page_data, block_map, clinical_model_id)

    return {
        "page_num": page_num,
        "page_type": page_type,
        "confidence": result["confidence"],
        "data": result["data"],
        "flagged": result.get("flagged", []),
    }
```

---

## Step 6: Assemble the Structured Prior Auth Record

Merges all page extraction results into a single coherent record.

```python
def assemble_prior_auth_record(
    document_key: str,
    page_count: int,
    page_extractions: dict[int, dict],
) -> dict:
    """
    Assemble extraction results from all pages into a structured prior auth record.

    The medical_necessity_evidence and failed_treatments fields are accumulated
    across all clinical pages because different pages may contribute different
    pieces of the clinical argument.
    """
    record = {
        "document_key": document_key,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "page_count": page_count,
        "needs_review": False,
        "page_classifications": {},
        "demographics": {
            "member_name": None,
            "member_id": None,
            "member_dob": None,
        },
        "requested_service": {
            "cpt_code": None,
            "procedure": None,
            "date_of_service": None,
            "urgency": "routine",
        },
        "requesting_provider": {
            "name": None,
            "npi": None,
            "facility": None,
        },
        "clinical_evidence": {
            "icd10_codes": [],
            "conditions": [],
            "medications": [],
            "procedures": [],
            "medical_necessity_evidence": "",
            "failed_treatments": [],
            "supporting_findings": "",
            "lab_values": [],
        },
        "page_confidence": {},
        "flagged_pages": [],
        "flagged_fields": {},
    }

    # Deduplication trackers
    seen_icd10_codes = {}   # code -> entry (keep highest confidence)
    seen_conditions = set()
    seen_medications = set()
    seen_procedures = set()

    for page_num in sorted(page_extractions.keys()):
        extraction = page_extractions[page_num]
        page_type = extraction["page_type"]
        confidence = extraction["confidence"]
        data = extraction["data"]

        record["page_classifications"][str(page_num)] = page_type
        record["page_confidence"][str(page_num)] = round(confidence, 1)

        if confidence < PAGE_CONFIDENCE_THRESHOLD:
            record["flagged_pages"].append(page_num)
            record["needs_review"] = True

        flagged = extraction.get("flagged", [])
        if flagged:
            record["flagged_fields"][str(page_num)] = flagged
            record["needs_review"] = True

        if page_type == "cover_sheet":
            # Use the first cover sheet for administrative fields.
            # Some submissions include a second cover sheet (duplicate); skip it.
            if record["demographics"]["member_id"] is None:
                record["demographics"]["member_name"] = data.get("member_name")
                record["demographics"]["member_id"] = data.get("member_id")
                record["demographics"]["member_dob"] = data.get("member_dob")

            if record["requested_service"]["cpt_code"] is None:
                record["requested_service"]["cpt_code"] = data.get("requested_cpt")
                record["requested_service"]["date_of_service"] = data.get(
                    "date_of_service"
                )
                urgency_val = (data.get("urgency") or "").lower()
                if "urgent" in urgency_val or "stat" in urgency_val:
                    record["requested_service"]["urgency"] = "urgent"

            if record["requesting_provider"]["npi"] is None:
                record["requesting_provider"]["name"] = data.get("requesting_provider")
                record["requesting_provider"]["npi"] = data.get("provider_npi")
                record["requesting_provider"]["facility"] = data.get(
                    "requesting_facility"
                )

        elif page_type in ("clinical_note", "physician_letter", "imaging_report"):
            # ICD-10 deduplication: keep highest confidence per code
            for code_entry in data.get("icd10_codes", []):
                code = code_entry.get("icd10_code", "")
                if not code:
                    continue
                existing = seen_icd10_codes.get(code)
                if existing is None or code_entry["confidence"] > existing["confidence"]:
                    seen_icd10_codes[code] = code_entry

            # Clinical entity deduplication
            for item in data.get("conditions", []):
                key = item.lower().strip()
                if key not in seen_conditions:
                    seen_conditions.add(key)
                    record["clinical_evidence"]["conditions"].append(item)

            for item in data.get("medications", []):
                key = item.lower().strip()
                if key not in seen_medications:
                    seen_medications.add(key)
                    record["clinical_evidence"]["medications"].append(item)

            for item in data.get("procedures", []):
                key = item.lower().strip()
                if key not in seen_procedures:
                    seen_procedures.add(key)
                    record["clinical_evidence"]["procedures"].append(item)

            # Accumulate failed treatments; different pages may add different episodes
            for treatment in data.get("failed_treatments", []):
                if treatment not in record["clinical_evidence"]["failed_treatments"]:
                    record["clinical_evidence"]["failed_treatments"].append(treatment)

            # Concatenate medical necessity evidence across pages
            mne = data.get("medical_necessity_evidence", "")
            if mne:
                existing_mne = record["clinical_evidence"]["medical_necessity_evidence"]
                if existing_mne:
                    record["clinical_evidence"]["medical_necessity_evidence"] = (
                        existing_mne + "\n\n" + mne
                    )
                else:
                    record["clinical_evidence"]["medical_necessity_evidence"] = mne

            sf = data.get("supporting_findings", "")
            if sf:
                existing_sf = record["clinical_evidence"]["supporting_findings"]
                if existing_sf:
                    record["clinical_evidence"]["supporting_findings"] = (
                        existing_sf + "\n\n" + sf
                    )
                else:
                    record["clinical_evidence"]["supporting_findings"] = sf

        elif page_type == "lab_results":
            record["clinical_evidence"]["lab_values"].extend(
                data.get("lab_values", [])
            )

    # Sort ICD-10 codes by confidence descending
    record["clinical_evidence"]["icd10_codes"] = sorted(
        seen_icd10_codes.values(),
        key=lambda x: x["confidence"],
        reverse=True,
    )

    # Flag submissions missing the minimum required fields for downstream processing
    if (
        record["demographics"]["member_id"] is None
        or record["requested_service"]["cpt_code"] is None
    ):
        record["needs_review"] = True

    return record
```

---

## Step 7: Store to DynamoDB

```python
def store_prior_auth_record(
    record: dict,
    table_name: str = "prior-auth-records",
    region: str = "us-east-1"
) -> None:
    """
    Write the assembled prior auth record to DynamoDB.

    DynamoDB gotcha: it doesn't accept Python float values. All floating-point
    numbers must be converted to Decimal. The helper below handles this recursively.
    This is a known boto3 limitation; you'll hit it the first time you try to
    store a record with confidence scores.
    """
    # [EDITOR: Removed em dash from docstring. Original: "known boto3 limitation —
    # you'll hit it the first time...". Changed to semicolon.]
    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    def floats_to_decimal(obj):
        """Recursively convert floats to Decimal for DynamoDB compatibility."""
        if isinstance(obj, float):
            return Decimal(str(obj))
        elif isinstance(obj, dict):
            return {k: floats_to_decimal(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [floats_to_decimal(i) for i in obj]
        return obj

    record_for_dynamo = floats_to_decimal(record)

    table.put_item(
        Item=record_for_dynamo,
        # Conditional write: only insert if this document_key doesn't already exist.
        # This is the idempotency guard: S3 events and SNS both have at-least-once
        # delivery semantics, so the pipeline may be triggered more than once for
        # the same document.
        # [EDITOR: Removed em dash from comment. Original: "idempotency guard —
        # S3 events and SNS both have at-least-once delivery semantics". Changed
        # to colon.]
        ConditionExpression="attribute_not_exists(document_key)",
    )

    logger.info(
        f"Stored prior auth record for {record['document_key']} "
        f"(needs_review={record['needs_review']})"
    )
```

---

## Full Pipeline Function

Assembles all steps into a single callable function. The print statements let you trace execution when running locally.

```python
def process_prior_auth_submission(
    s3_bucket: str,
    document_key: str,
    textract_job_id: str,
    dynamodb_table_name: str = "prior-auth-records",
    classification_model_id: str = CLASSIFICATION_MODEL_ID,
    clinical_model_id: str = CLINICAL_MODEL_ID,
    region: str = "us-east-1",
) -> dict:
    """
    Process a prior auth submission from Textract output to structured DynamoDB record.

    This function is called by the Step Functions pa-retrieve Lambda after the
    Textract job completes. The textract_job_id and document_key come from the
    SNS notification payload.

    In production, the Textract retrieval and Step Functions handoff are separate
    Lambda functions. This single function version is useful for local testing.
    """
    print(f"\n{'='*60}")
    print(f"Processing: {document_key}")
    print(f"Textract job: {textract_job_id}")
    print(f"{'='*60}\n")

    # Step 2: Retrieve Textract results
    print("[1/5] Retrieving Textract results...")
    all_blocks = retrieve_textract_blocks(textract_job_id, region=region)
    print(f"      Retrieved {len(all_blocks)} blocks")

    # Build a block ID lookup map for O(1) access during KV and table parsing
    block_map = {block["Id"]: block for block in all_blocks}

    # Step 3: Group blocks by page
    print("[2/5] Grouping blocks by page...")
    pages = group_blocks_by_page(all_blocks)
    page_count = len(pages)
    print(f"      Found {page_count} pages")

    # Step 4: Classify pages with Nova Lite
    print("[3/5] Classifying pages...")
    classifications = classify_all_pages(
        pages,
        model_id=classification_model_id,
        region=region,
    )
    for page_num, cls in sorted(classifications.items()):
        print(
            f"      Page {page_num}: {cls['page_type']} "
            f"(confidence {cls['confidence']:.2f})"
        )

    # Step 5: Fan out to extractors
    print("[4/5] Extracting content from each page...")
    page_extractions = {}

    for page_num in sorted(pages.keys()):
        page_data = pages[page_num]
        classification = classifications[page_num]

        print(f"      Extracting page {page_num} ({classification['page_type']})...")

        extraction = route_and_extract(
            page_num=page_num,
            classification=classification,
            page_data=page_data,
            block_map=block_map,
            clinical_model_id=clinical_model_id,
            region=region,
        )
        page_extractions[page_num] = extraction

    # Step 6: Assemble
    print("[5/5] Assembling record...")
    record = assemble_prior_auth_record(
        document_key=document_key,
        page_count=page_count,
        page_extractions=page_extractions,
    )

    # Store to DynamoDB
    store_prior_auth_record(record, table_name=dynamodb_table_name, region=region)

    print(f"\nDone. needs_review={record['needs_review']}")
    if record["flagged_pages"]:
        print(f"Flagged pages: {record['flagged_pages']}")
    print(f"ICD-10 codes found: {len(record['clinical_evidence']['icd10_codes'])}")
    print(
        f"Medical necessity evidence: "
        f"{'present' if record['clinical_evidence']['medical_necessity_evidence'] else 'absent'}"
    )
    print(
        f"Failed treatments documented: "
        f"{len(record['clinical_evidence']['failed_treatments'])}"
    )

    return record
```

---

## Gap to Production

This example demonstrates the patterns, but there's meaningful distance between this and something you'd deploy. Here's what you'd need to add:

**Error handling and retries.** The Bedrock runtime and Comprehend Medical clients in this example are configured with `botocore.config.Config(retries={"max_attempts": 3, "mode": "adaptive"})`. This covers the most common production failure mode: `ThrottlingException` during burst submission periods. `adaptive` mode implements exponential backoff with jitter automatically. For more granular retry control (per-operation retry policies, custom delay functions), consider the `tenacity` library as a supplement.

**PHI in log messages.** This example logs only structural metadata (response length, error type) from Bedrock API calls. Never log raw model output, extracted text, or exception strings that may echo clinical content. LLM responses to clinical extraction prompts can contain patient names, diagnoses, and medication lists drawn from the input document. Additionally: configure CloudWatch log groups for all Lambda functions with KMS encryption using a customer-managed key. Lambda does not encrypt log groups by default. Scope CloudWatch log group access to authorized personnel only. 

**LLM output validation.** The JSON parsing above handles the common failure mode (model returns markdown-wrapped JSON or whitespace). But a model can also return structurally valid JSON that's semantically wrong: `confidence` outside [0, 1], `page_type` not in the expected enum, missing required fields. Add a proper validation step before trusting any LLM output. `pydantic` works well for this.

**Prompt injection hardening.** Submitted documents are untrusted input. Sanitize extracted page text before passing it to Bedrock: strip null bytes, Unicode control characters, and anything in the Private Use Area. Add Bedrock Guardrails to the Converse API calls for an additional layer of protection. Treat any LLM response that deviates structurally from the expected schema as potentially adversarial.

**Model version pinning.** The model IDs above reference specific versions (`claude-sonnet-4-6-v1:0`). When AWS releases a new version, don't automatically switch. Run your labeled test set against any new model version before deploying. Put model IDs in environment variables or Parameter Store, not hard-coded constants.

**Input validation.** Validate that `s3_bucket`, `document_key`, and `textract_job_id` are non-empty before calling anything. Validate that the Textract job is for the correct document (compare the S3 key in the job output against `document_key`). Healthcare pipelines are high-stakes; failing loudly on bad inputs is better than silently processing garbage.

**Structured logging.** Replace `print()` calls with a structured logger (e.g., `structlog` or the standard `logging` module with JSON formatter). Lambda log output goes to CloudWatch; structured logs let you query across runs. Log the model ID used for each page, token counts from the Bedrock response, and Textract confidence distributions. These are the signals you'll need for cost monitoring and accuracy tracking.

**IAM least-privilege.** The IAM permissions in the Prerequisites section list the minimum required. In practice, scope `bedrock:InvokeModel` to the specific model ARNs, not `*`. Scope S3 permissions to the specific bucket and key prefixes. Use separate execution roles for each Lambda function rather than one shared role.

**VPC and VPC endpoints.** Production Lambdas should run in a VPC with no internet gateway. Add VPC endpoints for every AWS service this code calls: S3 (gateway endpoint), Textract, DynamoDB, CloudWatch Logs, KMS, Comprehend Medical, and Bedrock. Bedrock requires **two separate interface endpoints**: `com.amazonaws.REGION.bedrock-runtime` (for Converse API calls, which is what this code uses) and `com.amazonaws.REGION.bedrock` (for model management). A VPC with only the management endpoint will silently fail on every `bedrock.converse()` call. This keeps all PHI traffic on the AWS private network.

**KMS encryption.** The DynamoDB writes and S3 puts above don't specify KMS keys. In production, configure your S3 bucket with SSE-KMS using a customer-managed key (CMK), and DynamoDB with AWS-managed or customer-managed encryption. Pass the KMS key ARN through environment variables.

**DynamoDB Decimal gotcha.** This example handles the float-to-Decimal conversion in `store_prior_auth_record`. If you add new numeric fields to the record structure later, make sure they go through `floats_to_decimal` too. A `float` that sneaks through will cause a `TypeError` at write time. This is a known, longstanding boto3 limitation.

**Idempotency at the pipeline level.** The DynamoDB conditional write handles duplicate events at the storage layer. You also want Step Functions execution deduplication at the orchestration layer: use the `document_key` as the Step Functions execution name (with appropriate sanitization for allowed characters). If the same document triggers two pipeline executions, the second one will fail at Step Functions start rather than running a duplicate extraction.

**Textract and Bedrock quota limits.** Textract async has a default limit of 2 concurrent jobs per account (adjustable). Bedrock has TPM limits per model. At high submission volume, implement SQS buffering between the inbound S3 event and the Textract submission Lambda. Monitor queue depth and active job count via CloudWatch; alert before you hit the limits rather than after.

**Cost monitoring.** The model tiering here keeps costs manageable, but you want to verify this in production. Enable Bedrock usage logging (CloudTrail captures model ID and token counts per invocation). Create CloudWatch metrics for total input tokens and total output tokens per model, and alarm if the per-submission cost significantly exceeds the expected range. A misconfiguration that routes all pages through Sonnet instead of Nova Lite would roughly quadruple the LLM line item.

---

*← [Recipe 1.4: Prior Auth Document Processing](chapter01.04-prior-auth-v2) · [Python Example](chapter01.04-prior-auth-python-v2)*
