# Recipe 1.9: Medical Records Request Extraction: Python Example

<!-- [EDITOR: v3 changes from v2:
  1. Fixed PHI minimization comment in check_authorization_consistency_llm(). The v2 comment said "pass structural information rather than raw PHI where possible," which contradicts the code (full text is necessary for coherence analysis). Replaced with an accurate comment explaining why full-text transmission is required and that it is covered under the BAA. [EDITOR: review fix]
  2. Added _sanitize_for_prompt() helper and regex patterns; called it on full_text before the Bedrock call in check_authorization_consistency_llm(). Authorization text is an untrusted free-text surface (patient/attorney-authored); sanitization moves from Gap to Production into the main code path, matching the pattern in Recipe 1.8 v3. [EDITOR: review fix]
  3. Added REVIEW_QUEUE_URL constant; routed LLM-flagged authorizations to it instead of FULFILLMENT_QUEUES["general"]. The architecture diagram shows a dedicated rr-review queue; the code now matches. [EDITOR: review fix]
  4. Added resolve_review() function stub: DynamoDB status update, audit trail write, and SQS routing for coordinator-approved authorizations. Addresses the audit trail gap for the human review resolution path. [EDITOR: review fix]
  5. Added _validate_no_phi_in_concerns() stub: defense-in-depth check for PHI patterns in LLM concern descriptions before they are written to DynamoDB. [EDITOR: review fix]
] -->

<!-- [EDITOR: v2 changes from v1:
  1. Added one-retry-on-JSON-parse-failure pattern to check_authorization_consistency_llm() and classify_request_type(). This closes the P1 gap flagged in all three prior recipe reviews (1.4, 1.5, 1.6): prose described retry; code did not implement it. The _safe_parse_json() helper is kept but now called inside a try/retry wrapper.
  2. Replaced print() with logger.info() throughout process_records_request() and lambda_handler(). PHI-safe (all prints only logged status metadata) but logger is the right pattern for Lambda. Removed corresponding Gap item since it's now done.
  3. Added explicit comment on overall_coherence="skipped" sentinel value for the deficient path, explaining why it differs from the LLM response schema values.
  4. Added model_id storage in the DynamoDB record for audit reproducibility (mentioned in main recipe's Why This Isn't Production-Ready).
  5. Updated Gap to Production to reflect what v2 now addresses vs. what still remains.
] -->

> **This is an illustrative implementation, not a production-ready deployment.**
> It demonstrates the patterns from the Recipe 1.9 pseudocode using boto3 and real
> AWS API calls. Treat it as a starting point, not a destination. See the
> "Gap to Production" section at the bottom for what you'd need to add before
> deploying this in a real release-of-information pipeline.

---

## Setup

```bash
pip install boto3 python-dateutil
```

Credentials: use an IAM role (not hardcoded keys) with the following permissions:
- `textract:AnalyzeDocument` on the requests S3 bucket
- `s3:GetObject` on `arn:aws:s3:::YOUR-BUCKET/records-requests/*`
- `bedrock:InvokeModel` scoped to the specific model ARNs used here
- `dynamodb:PutItem` on the records-requests table
- `sqs:SendMessage` on each routing queue
- `sns:Publish` on the deficiency and review topics
- `kms:Decrypt` and `kms:GenerateDataKey` for the CMK

**Never** use real PHI in development or testing. Generate synthetic request forms
using the HHS model HIPAA authorization form as a template.

---

## Configuration

```python
import boto3
import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from botocore.config import Config

# ---
# Logging setup
# ---
# Log at INFO level. Never log patient names, member IDs, authorization text,
# or any other PHI. Log document keys, status outcomes, and metadata only.
# Lambda CloudWatch log groups should be encrypted with KMS (not automatic).
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---
# AWS clients
# ---
# The retry configuration handles Bedrock ThrottlingException and
# ServiceUnavailableException with exponential backoff and jitter.
# At healthcare volume, throttling is expected behavior, not an edge case.
# Without this, Lambda invocations fail silently under load.
_retry_config = Config(
    retries={"max_attempts": 3, "mode": "adaptive"}
)

REGION = "us-east-1"

textract = boto3.client("textract", region_name=REGION, config=_retry_config)
bedrock  = boto3.client("bedrock-runtime", region_name=REGION, config=_retry_config)
dynamo   = boto3.resource("dynamodb", region_name=REGION, config=_retry_config)
sqs      = boto3.client("sqs", region_name=REGION, config=_retry_config)
sns      = boto3.client("sns", region_name=REGION, config=_retry_config)


# ---
# Model IDs
# ---
# These are cross-region inference profile IDs that provide regional failover
# across us-east-1, us-east-2, and us-west-2. For strict version pinning
# in production (recommended), replace with full foundation model ARNs:
#   Sonnet: arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-6-20240229-v1:0
#   Nova Pro: arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0
# See: https://docs.aws.amazon.com/bedrock/latest/userguide/model-ids.html
#
# Store the model ID used for each LLM call in the DynamoDB record alongside
# the findings. This lets you reproduce the inference configuration for audit
# purposes if a compliance review requires explaining a specific validation decision.
SONNET_MODEL_ID   = "us.anthropic.claude-sonnet-4-6-v1"   # HIPAA consistency check
NOVA_PRO_MODEL_ID = "us.amazon.nova-pro-v1:0"             # Request classification


# ---
# Pipeline configuration (environment variables in Lambda)
# ---
# In Lambda, load these from os.environ. Hardcoded here for clarity.
DYNAMO_TABLE_NAME        = "records-requests"
DEFICIENCY_TOPIC_ARN     = "arn:aws:sns:us-east-1:123456789012:rr-deficiency"
REVIEW_TOPIC_ARN         = "arn:aws:sns:us-east-1:123456789012:rr-review"
CARE_COORD_QUEUE_URL     = "https://sqs.us-east-1.amazonaws.com/123456789012/cc-fulfillment"
LEGAL_QUEUE_URL          = "https://sqs.us-east-1.amazonaws.com/123456789012/legal-fulfillment"
UNDERWRITING_QUEUE_URL   = "https://sqs.us-east-1.amazonaws.com/123456789012/underwriting-fulfillment"
UR_QUEUE_URL             = "https://sqs.us-east-1.amazonaws.com/123456789012/ur-fulfillment"
PATIENT_ACCESS_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/patient-access-fulfillment"
GENERAL_REVIEW_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/general-review"

# Dedicated queue for LLM-flagged authorization review.
# Distinct from GENERAL_REVIEW_QUEUE_URL: "LLM flagged a coherence concern" and
# "unclear request category" are different work items with different SLAs.
# Matches the rr-review queue in the architecture diagram. [EDITOR: review fix]
REVIEW_QUEUE_URL         = "https://sqs.us-east-1.amazonaws.com/123456789012/rr-auth-review"

FULFILLMENT_QUEUES = {
    "care_coordination":  CARE_COORD_QUEUE_URL,
    "legal":              LEGAL_QUEUE_URL,
    "underwriting":       UNDERWRITING_QUEUE_URL,
    "utilization_review": UR_QUEUE_URL,
    "patient_access":     PATIENT_ACCESS_QUEUE_URL,
    "general":            GENERAL_REVIEW_QUEUE_URL,
}

# Minimum confidence for Textract SIGNATURE blocks to count as a detected signature.
# 70.0 is reasonable for fax-quality forms.
# Your compliance team should validate this threshold before production.
SIGNATURE_CONFIDENCE_THRESHOLD = 70.0


# ---
# HIPAA required element definitions
# ---
REQUIRED_ELEMENTS = {
    "patient_or_rep_signature": (
        "Signature of patient or authorized representative (45 CFR § 164.508(c)(1)(vi))"
    ),
    "authorization_date": (
        "Date the authorization was signed (45 CFR § 164.508(c)(1)(vi))"
    ),
    "records_requested": (
        "Description of information to be used or disclosed (45 CFR § 164.508(c)(1)(i))"
    ),
    "purpose": (
        "Purpose of the requested disclosure (45 CFR § 164.508(c)(1)(iv))"
    ),
    "expiration_date": (
        "Expiration date or event (45 CFR § 164.508(c)(1)(v))"
    ),
}


# ---
# Field map: canonical name -> label variants seen on real request forms
# ---
REQUEST_FIELD_MAP = {
    "patient_name": [
        "patient name", "member name", "name of individual",
        "name of patient", "patient",
    ],
    "patient_dob": [
        "date of birth", "dob", "birth date", "patient dob", "member dob",
    ],
    "patient_id": [
        "medical record number", "medical record #", "mrn",
        "member id", "patient id", "patient number",
    ],
    "requestor_name": [
        "requesting party", "requestor", "requested by", "authorized by",
        "name of requestor", "name of authorized representative",
    ],
    "requestor_org": [
        "organization", "facility name", "practice name", "firm name",
        "organization name",
    ],
    "requestor_fax": [
        "fax", "fax number", "fax #", "fax no",
    ],
    "records_requested": [
        "records requested", "information requested", "type of records",
        "specific information to be disclosed", "records needed",
        "description of information", "what records",
    ],
    "date_range": [
        "date range", "dates of treatment", "dates of service",
        "from", "period of treatment", "treatment dates",
    ],
    "purpose": [
        "purpose", "purpose of disclosure", "reason for request",
        "reason", "intended use",
    ],
    "authorization_date": [
        "date signed", "authorization date", "signature date",
        "date of signature", "date", "signed on",
    ],
    "expiration_date": [
        "expiration date", "expiration", "this authorization expires",
        "authorization expires on", "expires", "valid through",
    ],
    "requestor_npi": [
        "npi", "national provider identifier", "provider npi",
    ],
}


# ---
# LLM system prompts
# ---
VALIDATION_SYSTEM_PROMPT = """You are a healthcare compliance specialist reviewing HIPAA authorization forms.
Your role is to identify logical inconsistencies and potential coherence issues in authorization documents.
You are NOT making a legal determination of validity. You are flagging concerns for human review.

Return a JSON object with this exact schema:
{
  "concerns": [
    {
      "type": "date_conflict | scope_ambiguity | missing_element | other",
      "severity": "high | medium | low",
      "description": "Brief description of the concern. Do not include patient names, member IDs, or other PHI."
    }
  ],
  "overall_coherence": "no_concerns | minor_concerns | significant_concerns",
  "review_recommended": true or false
}

Return only valid JSON. No markdown code fences. No text outside the JSON object."""

CLASSIFICATION_SYSTEM_PROMPT = """You are a medical records routing specialist.
Classify the medical records request into exactly one of these categories:
- care_coordination: treating physician requesting for continuity of care
- legal: attorney, law firm, litigation, subpoena
- underwriting: life insurance, disability insurance, financial underwriting
- utilization_review: utilization management, case management, IME
- patient_access: patient or personal representative requesting own records
- general: unclear purpose or does not fit other categories

Return a JSON object:
{
  "request_type": "<one of the categories above>",
  "confidence": <float between 0.0 and 1.0>,
  "reasoning": "Brief explanation. Do not include PHI."
}

Return only valid JSON. No markdown, no text outside the JSON object."""

# Appended to user message on retry when the first LLM call returns non-JSON output.
# The model returned something it shouldn't have (markdown fences, preamble text);
# this suffix reinforces the JSON-only requirement before the second attempt.
_JSON_RETRY_SUFFIX = "\n\nYou MUST return only valid JSON. No markdown. No explanatory text. Only the JSON object."

# ---
# Prompt sanitization patterns
# ---
# Authorization text is untrusted free-text authored by patients, attorneys, and
# providers. Strip control characters and obvious injection patterns before
# including any extracted text in a Bedrock prompt.
# Same pattern as Recipe 1.8 v3 _sanitize_for_prompt().
# [EDITOR: review fix]
_INJECTION_PATTERNS = re.compile(
    r"(ignore\s+previous|system:|assistant:|<\|im_start\|>|<\|im_end\|>)",
    re.IGNORECASE,
)
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\x80-\x9f]")
```

---

## Step 1: Textract Extraction

```python
def extract_request_document(bucket: str, document_key: str) -> dict:
    """
    Call Textract AnalyzeDocument with FORMS and SIGNATURES.
    Returns separated block lists and a block map for field parsing.

    The synchronous API handles 1-2 page forms with one call.
    No job tracking or polling required at this document size.
    """
    response = textract.analyze_document(
        Document={"S3Object": {"Bucket": bucket, "Name": document_key}},
        FeatureTypes=["FORMS", "SIGNATURES"],
    )

    all_blocks = response["Blocks"]

    kv_blocks   = [b for b in all_blocks if b["BlockType"] == "KEY_VALUE_SET"]
    sig_blocks  = [b for b in all_blocks if b["BlockType"] == "SIGNATURE"]
    line_blocks = [b for b in all_blocks if b["BlockType"] == "LINE"]
    block_map   = {b["Id"]: b for b in all_blocks}

    logger.info(
        "Textract complete for %s: %d KV pairs, %d signature blocks, %d lines",
        document_key,
        len(kv_blocks) // 2,  # KEY_VALUE_SET blocks come in pairs
        len(sig_blocks),
        len(line_blocks),
    )
    return {
        "kv_blocks":   kv_blocks,
        "sig_blocks":  sig_blocks,
        "line_blocks": line_blocks,
        "block_map":   block_map,
    }
```

---

## Step 2: Field Normalization

```python
def _get_kv_text(block: dict, block_map: dict) -> str:
    """Extract the text value from a KEY_VALUE_SET VALUE block."""
    for rel in block.get("Relationships", []):
        if rel["Type"] == "VALUE":
            for child_id in rel["Ids"]:
                child = block_map.get(child_id, {})
                # VALUE blocks contain WORD children with the actual text
                words = []
                for word_rel in child.get("Relationships", []):
                    if word_rel["Type"] == "CHILD":
                        for word_id in word_rel["Ids"]:
                            word_block = block_map.get(word_id, {})
                            if word_block.get("BlockType") == "WORD":
                                words.append(word_block.get("Text", ""))
                if words:
                    return " ".join(words)
    return ""


def parse_and_normalize_fields(kv_blocks: list, block_map: dict) -> dict:
    """
    Extract raw key-value pairs from Textract output and normalize
    them against REQUEST_FIELD_MAP to produce canonical field names.

    Returns: {canonical_name: {"value": str, "confidence": float}}
    """
    raw_kv = {}

    # KEY_VALUE_SET KEY blocks have EntityTypes: ["KEY"]
    # They reference VALUE blocks through RELATIONSHIPS
    for block in kv_blocks:
        if block.get("EntityTypes", []) == ["KEY"]:
            key_words = []
            for rel in block.get("Relationships", []):
                if rel["Type"] == "CHILD":
                    for child_id in rel["Ids"]:
                        child = block_map.get(child_id, {})
                        if child.get("BlockType") == "WORD":
                            key_words.append(child.get("Text", ""))

            if not key_words:
                continue

            key_text = " ".join(key_words).strip()
            value_text = _get_kv_text(block, block_map)
            confidence = block.get("Confidence", 0.0)

            raw_kv[key_text] = {"value": value_text, "confidence": confidence}

    # Normalize against the field map
    normalized = {}
    for canonical_name, variants in REQUEST_FIELD_MAP.items():
        for label in variants:
            # Case-insensitive substring match
            matches = [
                k for k in raw_kv
                if label in k.lower()
            ]
            if matches:
                # Take the match with the highest Textract confidence
                best = max(matches, key=lambda k: raw_kv[k]["confidence"])
                normalized[canonical_name] = raw_kv[best]
                break  # Found this canonical field; move on

    logger.info(
        "Field normalization complete. Extracted %d/%d canonical fields.",
        len(normalized),
        len(REQUEST_FIELD_MAP),
    )
    return normalized
```

---

## Step 3: Signature Extraction

```python
def extract_signatures(sig_blocks: list) -> list:
    """
    Extract SIGNATURE blocks into a sorted list of signature dicts.
    Sorted by page then vertical position (document reading order).
    """
    signatures = []

    for block in sig_blocks:
        geo = block.get("Geometry", {}).get("BoundingBox", {})
        signatures.append({
            "confidence":   block.get("Confidence", 0.0),
            "page":         block.get("Page", 1),
            "bounding_box": {
                "top":    geo.get("Top", 0.0),
                "left":   geo.get("Left", 0.0),
                "width":  geo.get("Width", 0.0),
                "height": geo.get("Height", 0.0),
            },
        })

    # Sort into reading order
    signatures.sort(key=lambda s: (s["page"], s["bounding_box"]["top"]))

    logger.info(
        "Signatures detected: %d (max confidence: %.1f%%)",
        len(signatures),
        max((s["confidence"] for s in signatures), default=0.0),
    )
    return signatures
```

---

## Step 4: Rule-Based HIPAA Element Validation

```python
def _parse_date_string(value: str):
    """
    Try to parse a date string in common formats.
    Returns a date object or None if unparseable.
    """
    from dateutil import parser as dateutil_parser
    try:
        return dateutil_parser.parse(value, fuzzy=False).date()
    except (ValueError, OverflowError):
        return None


def validate_elements_rule_based(normalized_fields: dict, signatures: list) -> dict:
    """
    Deterministic, rule-based check for required HIPAA authorization elements.
    This is the authoritative compliance gate. Results are the audit trail.

    If this check fails, the authorization is deficient. The LLM step does not run.
    Returns a dict describing which elements were present, what was missing,
    and whether the authorization was expired.
    """
    result = {
        "passed":           True,
        "elements":         {},
        "missing":          [],      # regulatory citations for missing/failed elements
        "expired":          False,
        "event_expiration": False,   # True when expiration is a non-date event string
    }

    # --- Signature check ---
    high_conf = [s for s in signatures if s["confidence"] >= SIGNATURE_CONFIDENCE_THRESHOLD]
    has_sig   = len(high_conf) > 0
    result["elements"]["patient_or_rep_signature"] = has_sig

    if not has_sig:
        result["passed"] = False
        if not signatures:
            result["missing"].append(REQUIRED_ELEMENTS["patient_or_rep_signature"])
        else:
            max_conf = max(s["confidence"] for s in signatures)
            result["missing"].append(
                REQUIRED_ELEMENTS["patient_or_rep_signature"]
                + f" (detected at {max_conf:.1f}% confidence; below {SIGNATURE_CONFIDENCE_THRESHOLD}% threshold)"
            )

    # --- Signing date ---
    auth_date_entry = normalized_fields.get("authorization_date", {})
    has_auth_date   = bool(auth_date_entry.get("value", "").strip())
    result["elements"]["authorization_date"] = has_auth_date
    if not has_auth_date:
        result["passed"] = False
        result["missing"].append(REQUIRED_ELEMENTS["authorization_date"])

    # --- Records description ---
    records_entry = normalized_fields.get("records_requested", {})
    has_records   = bool(records_entry.get("value", "").strip())
    result["elements"]["records_requested"] = has_records
    if not has_records:
        result["passed"] = False
        result["missing"].append(REQUIRED_ELEMENTS["records_requested"])

    # --- Purpose ---
    purpose_entry = normalized_fields.get("purpose", {})
    has_purpose   = bool(purpose_entry.get("value", "").strip())
    result["elements"]["purpose"] = has_purpose
    if not has_purpose:
        result["passed"] = False
        result["missing"].append(REQUIRED_ELEMENTS["purpose"])

    # --- Expiration ---
    exp_entry = normalized_fields.get("expiration_date", {})
    exp_value = exp_entry.get("value", "").strip()
    has_exp   = bool(exp_value)
    result["elements"]["expiration_date"] = has_exp

    if not has_exp:
        result["passed"] = False
        result["missing"].append(REQUIRED_ELEMENTS["expiration_date"])
    else:
        exp_date = _parse_date_string(exp_value)
        if exp_date is not None:
            if exp_date < date.today():
                result["passed"]  = False
                result["expired"] = True
                result["missing"].append(
                    f"Authorization expired {exp_date.isoformat()}. A current authorization is required."
                )
        else:
            # Non-date expiration string: event-based expiration.
            # Valid under HIPAA but requires human judgment to evaluate.
            # Not a rule-based failure; flagged for LLM and human review.
            result["event_expiration"] = True

    logger.info(
        "Rule-based validation: passed=%s, missing=%d elements, expired=%s",
        result["passed"],
        len(result["missing"]),
        result["expired"],
    )
    return result
```

---

## Step 5: LLM Authorization Consistency Check

```python
def _sanitize_for_prompt(text: str) -> str:
    """
    Strip control characters and obvious prompt-injection patterns from text
    before including it in a Bedrock prompt.

    Authorization forms are untrusted free-text: patients and attorneys write
    the 'reason for request' and 'records requested' fields. A claimant could
    embed injection instructions in these fields. This is a first-pass defense;
    wire Bedrock Guardrails for production-grade coverage.

    Same pattern as Recipe 1.8 v3 _sanitize_for_prompt(). [EDITOR: review fix]
    """
    cleaned = _CONTROL_CHARS.sub("", text)
    cleaned = _INJECTION_PATTERNS.sub("[REDACTED]", cleaned)
    # Authorization text can be long; preserve up to 4000 chars for coherence analysis.
    return cleaned[:4000].strip()


def _safe_parse_json(text: str, fallback: dict) -> dict:
    """
    Parse JSON from LLM response. Return fallback dict on failure.
    Never log the raw response text; it may contain PHI-derived content.
    """
    # Strip markdown code fences if the model included them despite instructions
    cleaned = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", text, flags=re.DOTALL).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(
            "LLM returned non-JSON output (length=%d). Using fallback.",
            len(text),
            # Do NOT include text[:200] or any response snippet here.
            # LLM output may contain PHI echoed from the authorization text.
        )
        return fallback


def _call_bedrock_with_retry(
    model_id: str,
    system_prompt: str,
    user_message: str,
    inference_config: dict,
    fallback: dict,
) -> tuple[dict, bool]:
    """
    Call Bedrock Converse and parse the JSON response.
    On JSONDecodeError, retry once with a JSON-only suffix appended to the message.
    Returns (parsed_result, used_fallback).

    The retry handles the common case where the model returns markdown fences
    or preamble text despite explicit instructions not to. A second attempt
    with a reinforcing suffix resolves this in most cases without requiring
    a full botocore retry (which handles throttling, not malformed output).

    Do NOT log response content at any point. LLM responses may contain
    PHI-derived content from the document text passed in the prompt.
    """
    # First attempt
    response = bedrock.converse(
        modelId=model_id,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": user_message}]}],
        inferenceConfig=inference_config,
        # guardrailConfig={  # Uncomment and configure for production
        #     "guardrailIdentifier": "your-guardrail-id",
        #     "guardrailVersion":    "DRAFT",
        #     "trace":               "enabled",
        # },
    )
    response_text = response["output"]["message"]["content"][0]["text"]

    cleaned = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", response_text, flags=re.DOTALL).strip()
    try:
        return json.loads(cleaned), False
    except json.JSONDecodeError:
        logger.warning(
            "LLM returned non-JSON on first attempt (model=%s, length=%d). Retrying.",
            model_id,
            len(response_text),
        )

    # Second attempt: reinforce JSON-only requirement
    retry_message = user_message + _JSON_RETRY_SUFFIX
    response = bedrock.converse(
        modelId=model_id,
        system=[{"text": system_prompt}],
        messages=[{"role": "user", "content": [{"text": retry_message}]}],
        inferenceConfig=inference_config,
    )
    response_text = response["output"]["message"]["content"][0]["text"]

    cleaned = re.sub(r"```(?:json)?\s*(.*?)\s*```", r"\1", response_text, flags=re.DOTALL).strip()
    try:
        return json.loads(cleaned), False
    except json.JSONDecodeError:
        logger.error(
            "LLM returned non-JSON on retry (model=%s, length=%d). Using fallback.",
            model_id,
            len(response_text),
        )
        return fallback, True


# [EDITOR: _call_bedrock_with_retry() is new in v2. The v1 had _safe_parse_json()
# which handled parse failure gracefully but did not retry. Prior reviews of
# recipes 1.4, 1.5, and 1.6 all flagged "LLM output retry on parse failure"
# as a P1/P2 gap: the prose described the pattern but the code didn't implement it.
# This helper centralizes the retry logic for both the validation and classification
# steps so neither function duplicates it.]


def check_authorization_consistency_llm(
    normalized_fields: dict,
    signatures: list,
    line_blocks: list,
    event_expiration: bool,
) -> dict:
    """
    Use Claude Sonnet to screen the authorization for coherence issues
    that rule-based validation cannot detect: conflicting dates,
    ambiguous scope language, elements present in text but absent from fields.

    This is a screening layer only. It does NOT override rule-based validation.
    It surfaces observations for human review; it does not make compliance decisions.

    Returns LLM observations. Clearly labeled as non-authoritative in all downstream storage.
    """
    # Build the full document text from LINE blocks (already paid for by Textract)
    full_text = "\n".join(b.get("Text", "") for b in line_blocks)

    # Sanitize before including in the prompt.
    # Authorization text is an untrusted free-text surface: patients, attorneys, and
    # providers all author these documents. Strip control characters and injection
    # patterns before passing to Bedrock. [EDITOR: review fix]
    sanitized_text = _sanitize_for_prompt(full_text)

    # The coherence check requires the full authorization text.
    # The LLM must see all field values (including dates, scope descriptions, and
    # purpose statements) to detect cross-field inconsistencies and elements present
    # in prose but absent from extracted fields. Full-text transmission is necessary
    # for this use case; selective PHI suppression would defeat the coherence analysis.
    # All transmission to Bedrock is covered by the BAA; AWS does not retain this data.
    # The prompt instructs the model not to echo PHI in its response descriptions.
    # [EDITOR: review fix: replaced "pass structural information rather than raw PHI
    # where possible" comment, which contradicted the code. Full-text transmission is
    # intentional and necessary; the prior comment implied it should be avoided.]
    truncated_text = sanitized_text[:3000]
    if len(sanitized_text) > 3000:
        truncated_text += "\n[Document truncated for context window]"

    # Build the user message with extracted field values.
    # Use descriptive placeholders, not raw patient data, where possible.
    signing_date = normalized_fields.get("authorization_date", {}).get("value", "(not extracted)")
    expiration   = normalized_fields.get("expiration_date", {}).get("value", "(not extracted)")
    records      = normalized_fields.get("records_requested", {}).get("value", "(not extracted)")
    purpose      = normalized_fields.get("purpose", {}).get("value", "(not extracted)")
    max_sig_conf = max((s["confidence"] for s in signatures), default=0.0)

    user_message = f"""Review this HIPAA authorization for logical consistency.

Extracted fields:
- Signing date: {signing_date}
- Expiration date/event: {expiration}
- Records requested: {records}
- Purpose of disclosure: {purpose}
- Signature detected: {"Yes" if signatures else "No"} (max confidence: {max_sig_conf:.1f}%)
- Event-based expiration: {"Yes" if event_expiration else "No"}

Full document text:
---
{truncated_text}
---

Check for:
1. Date inconsistencies (signing date vs. expiration date; dates that are logically impossible)
2. Scope ambiguity (records description vague or inconsistent with stated purpose)
3. Required elements that appear in document text but were not captured in extracted fields
4. Any other coherence issues a compliance reviewer would flag

Important: Do not include patient names, member IDs, dates of birth, or other PHI in your descriptions.
Describe structural and logical issues only."""

    fallback = {
        "concerns": [],
        "overall_coherence": "no_concerns",
        "review_recommended": False,
    }

    llm_result, used_fallback = _call_bedrock_with_retry(
        model_id=SONNET_MODEL_ID,
        system_prompt=VALIDATION_SYSTEM_PROMPT,
        user_message=user_message,
        inference_config={"maxTokens": 512, "temperature": 0},
        fallback=fallback,
    )

    if used_fallback:
        # Both attempts failed. Log the failure as a review trigger, not a silent skip.
        # A failed parse means we can't be confident the LLM didn't find concerns.
        # Route to human review as the conservative choice.
        logger.warning(
            "LLM consistency check parse failed after retry for document. "
            "Routing to human review as a precaution."
        )
        return {
            "overall_coherence":  "minor_concerns",
            "concerns":           [{
                "type":        "other",
                "severity":    "low",
                "description": "LLM consistency check could not produce a structured response. Manual review recommended.",
            }],
            "review_recommended": True,
        }

    # Validate and normalize the response structure
    overall = llm_result.get("overall_coherence", "no_concerns")
    if overall not in ("no_concerns", "minor_concerns", "significant_concerns"):
        overall = "no_concerns"

    review_recommended = bool(llm_result.get("review_recommended", False))

    # Normalize concerns list: ensure each entry has the expected keys
    raw_concerns = llm_result.get("concerns", [])
    concerns = []
    for c in raw_concerns:
        if isinstance(c, dict):
            concerns.append({
                "type":        c.get("type", "other"),
                "severity":    c.get("severity", "medium"),
                "description": c.get("description", ""),
            })

    logger.info(
        "LLM consistency check complete: overall=%s, concerns=%d, review_recommended=%s",
        overall,
        len(concerns),
        review_recommended,
    )

    # Defense-in-depth: validate concern descriptions for PHI before returning.
    # The model is instructed not to echo PHI, but instructions alone are not
    # sufficient enforcement. _validate_no_phi_in_concerns() provides a second
    # layer; wire Bedrock Guardrails for production coverage. [EDITOR: review fix]
    concerns = _validate_no_phi_in_concerns(concerns)

    return {
        "overall_coherence":  overall,
        "concerns":           concerns,
        "review_recommended": review_recommended,
    }


def _validate_no_phi_in_concerns(concerns: list) -> list:
    """
    Defense-in-depth check: scan LLM concern descriptions for patterns that
    suggest PHI was echoed in the output despite instructions not to include it.

    The system prompt instructs the model to omit PHI from descriptions. LLM
    instruction compliance is not perfectly reliable. This stub provides a
    second validation layer before concern descriptions are written to DynamoDB,
    where they may surface in coordinator review UIs.

    In production: replace the regex patterns with Bedrock Guardrails PII
    detection applied to the Converse API output. The guardrailConfig stub in
    _call_bedrock_with_retry() is the wiring point. This stub covers cases where
    Guardrails is not yet configured. [EDITOR: review fix]

    Returns the concerns list with any PHI-matching descriptions redacted.
    Similar in structure to the synthetic example validation in Recipe 1.6.
    """
    # Patterns that suggest PHI echoed in an LLM description.
    # These are heuristic; Bedrock Guardrails PII detection is more reliable.
    _PHI_DATE_PATTERN    = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b")
    _MEMBER_ID_PATTERN   = re.compile(r"\b[A-Z]{2,4}\d{6,12}\b")

    validated = []
    for concern in concerns:
        description = concern.get("description", "")
        if _PHI_DATE_PATTERN.search(description) or _MEMBER_ID_PATTERN.search(description):
            logger.warning(
                "Concern description matches PHI pattern; redacting before DynamoDB write. "
                "type=%s severity=%s",
                concern.get("type", "unknown"),
                concern.get("severity", "unknown"),
            )
            concern = {**concern, "description": "[PHI pattern detected in LLM output; description redacted]"}
        validated.append(concern)
    return validated
```

---

## Step 6: LLM Request Classification

```python
def classify_request_type(normalized_fields: dict, line_blocks: list) -> dict:
    """
    Use Nova Pro to classify the request into a routing category.
    Returns the request type, confidence, and LLM reasoning.

    The reasoning is stored in the routing record to give fulfillment
    specialists context for ambiguous cases. It is labeled as LLM inference,
    not as a statement of fact about the document.
    """
    full_text    = "\n".join(b.get("Text", "") for b in line_blocks)
    truncated    = full_text[:2000]
    purpose_text = normalized_fields.get("purpose", {}).get("value", "(not provided)")
    requestor    = (
        normalized_fields.get("requestor_org", {}).get("value")
        or normalized_fields.get("requestor_name", {}).get("value")
        or "(not extracted)"
    )

    user_message = f"""Classify this medical records request.

Requestor: {requestor}
Purpose field: {purpose_text}

Full request text:
---
{truncated}
---"""

    fallback = {
        "request_type": "general",
        "confidence":   0.5,
        "reasoning":    "(classification reasoning unavailable)",
    }

    result, used_fallback = _call_bedrock_with_retry(
        model_id=NOVA_PRO_MODEL_ID,
        system_prompt=CLASSIFICATION_SYSTEM_PROMPT,
        user_message=user_message,
        inference_config={"maxTokens": 256, "temperature": 0},
        fallback=fallback,
    )

    if used_fallback:
        logger.warning(
            "Classification parse failed after retry. Routing to general queue."
        )

    valid_types = {
        "care_coordination", "legal", "underwriting",
        "utilization_review", "patient_access", "general",
    }
    request_type = result.get("request_type", "general")
    if request_type not in valid_types:
        request_type = "general"

    # Clamp confidence to [0.0, 1.0] and ensure it's float-compatible
    raw_conf   = result.get("confidence", 0.5)
    confidence = max(0.0, min(1.0, float(raw_conf) if isinstance(raw_conf, (int, float)) else 0.5))

    logger.info(
        "Request classified: type=%s, confidence=%.2f",
        request_type,
        confidence,
    )

    return {
        "request_type": request_type,
        "confidence":   confidence,
        "reasoning":    result.get("reasoning", "(not provided)"),
    }
```

---

## Step 7: Assemble and Route

```python
def _to_decimal(value) -> Decimal:
    """
    Convert float to Decimal for DynamoDB storage.
    DynamoDB raises TypeError on Python floats; all numeric values must be Decimal.
    This helper handles int, float, and already-Decimal inputs.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    return Decimal("0")


def _floats_to_decimal(obj):
    """
    Recursively convert all floats in a nested dict/list structure to Decimal.
    Required because DynamoDB's boto3 resource does not accept Python floats.
    Apply this to the full record before put_item(), including all nested lists
    (e.g., llm_consistency_findings.concerns[*]).
    """
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(item) for item in obj]
    return obj


def _determine_status(rule_validation: dict, llm_consistency: dict) -> str:
    if not rule_validation["passed"]:
        return "deficient"
    if llm_consistency["review_recommended"]:
        return "pending_llm_review"
    return "routed"


def assemble_and_route(
    document_key: str,
    normalized_fields: dict,
    signatures: list,
    rule_validation: dict,
    llm_consistency: dict,
    classification: dict,
) -> dict:
    """
    Build the structured request record, write to DynamoDB, and route to
    the appropriate SQS queue based on validation and classification results.

    The DynamoDB record separates rule-based validation results
    (authoritative audit trail) from LLM observations (non-authoritative
    screening layer). These must remain distinct in any downstream UI or report.
    """
    sig_confidences = [s["confidence"] for s in signatures]

    record = {
        "document_key":  document_key,
        "processed_at":  datetime.utcnow().isoformat() + "Z",

        # Store the model IDs used for each LLM call.
        # Required for audit reproducibility: if a compliance review asks why
        # a specific validation decision was made, you need to know which model
        # version produced the assessment. Model behavior can shift across updates.
        "model_versions": {
            "consistency_check": SONNET_MODEL_ID,
            "classification":    NOVA_PRO_MODEL_ID,
        },

        "patient": {
            "name":      normalized_fields.get("patient_name", {}).get("value"),
            "dob":       normalized_fields.get("patient_dob", {}).get("value"),
            "member_id": normalized_fields.get("patient_id", {}).get("value"),
        },

        "requestor": {
            "name":         normalized_fields.get("requestor_name", {}).get("value"),
            "organization": normalized_fields.get("requestor_org", {}).get("value"),
            "fax":          normalized_fields.get("requestor_fax", {}).get("value"),
            "npi":          normalized_fields.get("requestor_npi", {}).get("value"),
        },

        "request_details": {
            "records_requested": normalized_fields.get("records_requested", {}).get("value"),
            "date_range":        normalized_fields.get("date_range", {}).get("value"),
            "purpose":           normalized_fields.get("purpose", {}).get("value"),
        },

        # Rule-based validation: the authoritative audit trail.
        # This section is what you point to in a HIPAA compliance audit.
        "authorization_rule_check": {
            "passed":             rule_validation["passed"],
            "elements_present":   rule_validation["elements"],
            "deficiency_reasons": rule_validation["missing"],
            "expired":            rule_validation["expired"],
            "event_expiration":   rule_validation["event_expiration"],
            "signature_detected": len(signatures),
            "signature_max_confidence": _to_decimal(max(sig_confidences, default=0.0)),
            "signing_date":   normalized_fields.get("authorization_date", {}).get("value"),
            "expiration_date": normalized_fields.get("expiration_date", {}).get("value"),
        },

        # LLM consistency findings: non-authoritative screening layer.
        # Label these clearly in any UI that surfaces them.
        # They are model observations, not regulatory findings.
        #
        # Note on overall_coherence values:
        #   "no_concerns" | "minor_concerns" | "significant_concerns" = LLM ran and assessed
        #   "skipped" = LLM did not run (authorization was deficient by rules; LLM not invoked)
        # "skipped" is a pipeline sentinel, not an LLM response value.
        "llm_consistency_findings": {
            "note":              "LLM model observations. Not a regulatory determination.",
            "overall_coherence": llm_consistency["overall_coherence"],
            "review_recommended": llm_consistency["review_recommended"],
            "concerns":          llm_consistency["concerns"],
        },

        "classification": {
            "request_type":  classification["request_type"],
            "confidence":    _to_decimal(classification["confidence"]),
            # Clearly labeled as LLM inference, not a statement of fact.
            "llm_reasoning": classification["reasoning"],
        },

        "status": _determine_status(rule_validation, llm_consistency),
    }

    # Convert all floats to Decimal before DynamoDB write.
    # DynamoDB raises TypeError on Python floats. This applies recursively
    # to nested structures including llm_consistency.concerns[*] entries.
    dynamo_record = _floats_to_decimal(record)

    table = dynamo.Table(DYNAMO_TABLE_NAME)
    try:
        table.put_item(
            Item=dynamo_record,
            # Idempotency guard: fail if a record for this document already exists.
            # Prevents double-processing if the S3 event fires more than once.
            ConditionExpression="attribute_not_exists(document_key)",
        )
        logger.info("Record written to DynamoDB: %s", document_key)
    except dynamo.meta.client.exceptions.ConditionalCheckFailedException:
        logger.warning("Duplicate event: record already exists for %s. Skipping write.", document_key)
        return record

    # --- Routing ---

    if not rule_validation["passed"]:
        # Rules failed: notify deficiency workflow. Do not route to fulfillment.
        sns.publish(
            TopicArn=DEFICIENCY_TOPIC_ARN,
            Message=json.dumps({
                "document_key":     document_key,
                "missing_elements": rule_validation["missing"],
                "expired":          rule_validation["expired"],
            }),
            Subject="Records Request Authorization Deficiency",
        )
        logger.info(
            "Authorization deficient for %s. Rule failures: %s",
            document_key,
            "; ".join(rule_validation["missing"]),
        )
        return record

    if llm_consistency["review_recommended"]:
        # Rules passed but LLM flagged concerns. Route to human review queue.
        # The fulfillment specialist will make the final determination.
        sns.publish(
            TopicArn=REVIEW_TOPIC_ARN,
            Message=json.dumps({
                "document_key":    document_key,
                "concerns":        llm_consistency["concerns"],
                "overall_coherence": llm_consistency["overall_coherence"],
            }),
            Subject="Records Request Auth Needs Human Review",
        )
        sqs.send_message(
            QueueUrl=REVIEW_QUEUE_URL,  # [EDITOR: review fix: was FULFILLMENT_QUEUES["general"]; rr-review is a dedicated queue for LLM-flagged authorizations, not a general routing fallback]
            MessageBody=json.dumps({
                "document_key":    document_key,
                "review_reason":   "llm_consistency_concerns",
                "concern_count":   len(llm_consistency["concerns"]),
                "overall_coherence": llm_consistency["overall_coherence"],
            }),
        )
        logger.info(
            "LLM flagged %d concern(s) for %s. Routing to review queue.",
            len(llm_consistency["concerns"]),
            document_key,
        )
        return record

    # Both validation layers passed: route to type-specific fulfillment queue.
    request_type = classification["request_type"]
    queue_url    = FULFILLMENT_QUEUES.get(request_type, FULFILLMENT_QUEUES["general"])

    sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({
            "document_key":      document_key,
            "request_type":      request_type,
            "records_requested": record["request_details"]["records_requested"],
        }),
    )
    logger.info("Request %s routed to %s queue.", document_key, request_type)
    return record
```

---

## Coordinator Resolution

```python
def resolve_review(
    document_key: str,
    reviewer_id: str,
    determination: str,   # "approved" | "returned_deficient"
    reviewer_note: str,
) -> dict:
    """
    Stub: coordinator resolution for LLM-flagged authorizations.

    When a coordinator reviews a pending_llm_review record and reaches a
    determination, this function:
      1. Updates the DynamoDB record status and writes the coordinator decision
         to the audit trail (who reviewed, what they concluded, when).
      2. Routes approved requests to the appropriate fulfillment queue based on
         the stored classification.
      3. Publishes a deficiency notification for returned-deficient cases.

    This resolution step closes the audit trail gap: a record that moves from
    pending_llm_review to a final status without a documented coordinator
    decision is incomplete for HIPAA compliance purposes. The Recipe 1.6 A2I
    wait-for-callback pattern is directly applicable for triggering this
    function from a coordinator review UI. [EDITOR: review fix]

    Trigger: coordinator review UI calls this endpoint (API Gateway + Lambda)
    after the coordinator submits their decision.
    """
    table = dynamo.Table(DYNAMO_TABLE_NAME)

    # Step 1: Read the existing record to get the stored classification.
    response = table.get_item(Key={"document_key": document_key})
    existing = response.get("Item", {})
    request_type = existing.get("classification", {}).get("request_type", "general")

    # Step 2: Write the coordinator resolution to the DynamoDB record.
    # This is the audit trail entry for the human review closure.
    table.update_item(
        Key={"document_key": document_key},
        UpdateExpression=(
            "SET #status = :status, "
            "human_review = :review"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": determination,
            ":review": {
                "reviewer_id":    reviewer_id,
                "determination":  determination,
                "note":           reviewer_note,
                "reviewed_at":    datetime.utcnow().isoformat() + "Z",
            },
        },
    )
    logger.info(
        "Coordinator resolved %s: determination=%s, reviewer=%s",
        document_key, determination, reviewer_id,
    )

    # Step 3: Route based on determination.
    if determination == "approved":
        queue_url = FULFILLMENT_QUEUES.get(request_type, FULFILLMENT_QUEUES["general"])
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({
                "document_key": document_key,
                "request_type": request_type,
                "routed_by":    "coordinator_resolution",
            }),
        )
        logger.info("Coordinator-approved %s routed to %s.", document_key, request_type)
    elif determination == "returned_deficient":
        sns.publish(
            TopicArn=DEFICIENCY_TOPIC_ARN,
            Message=json.dumps({
                "document_key":  document_key,
                "deficient_by":  "coordinator_review",
                "reviewer_note": reviewer_note,
            }),
            Subject="Records Request Returned Deficient by Coordinator",
        )

    return {"document_key": document_key, "status": determination}
```

---

## Full Pipeline

```python
def process_records_request(bucket: str, document_key: str) -> dict:
    """
    End-to-end pipeline for a single medical records request form.

    Steps:
    1. Textract extraction (FORMS + SIGNATURES)
    2. Field normalization
    3. Signature extraction
    4. Rule-based HIPAA element validation (authoritative)
    5. LLM authorization consistency check (screening layer, runs only if rules pass)
    6. LLM request classification (runs only if both validation layers pass/resolve)
    7. Assemble record, write to DynamoDB, route to SQS
    """
    logger.info("Processing: %s", document_key)

    # Step 1: Extract
    logger.info("  Step 1: Textract extraction")
    textract_output = extract_request_document(bucket, document_key)

    # Step 2: Normalize fields
    logger.info("  Step 2: Field normalization")
    normalized_fields = parse_and_normalize_fields(
        textract_output["kv_blocks"],
        textract_output["block_map"],
    )

    # Step 3: Extract signature data
    logger.info("  Step 3: Signature extraction")
    signatures = extract_signatures(textract_output["sig_blocks"])

    # Step 4: Rule-based validation (always runs, always authoritative)
    logger.info("  Step 4: Rule-based HIPAA validation")
    rule_validation = validate_elements_rule_based(normalized_fields, signatures)
    logger.info("    Rules passed: %s", rule_validation["passed"])
    if not rule_validation["passed"]:
        logger.info("    Missing elements: %d", len(rule_validation["missing"]))

    # Step 5: LLM consistency check (only if rules passed)
    if rule_validation["passed"]:
        logger.info("  Step 5: LLM consistency check (Sonnet)")
        llm_consistency = check_authorization_consistency_llm(
            normalized_fields,
            signatures,
            textract_output["line_blocks"],
            rule_validation["event_expiration"],
        )
        logger.info(
            "    Coherence: %s, review recommended: %s",
            llm_consistency["overall_coherence"],
            llm_consistency["review_recommended"],
        )
    else:
        # Skip LLM check for deficient authorizations.
        # overall_coherence="skipped" is a pipeline sentinel value indicating
        # the LLM was not invoked (not an LLM response). This differs from
        # the LLM's own response schema values (no_concerns / minor_concerns /
        # significant_concerns). Downstream systems should treat "skipped" as
        # "LLM assessment not applicable" for this record.
        llm_consistency = {
            "overall_coherence":  "skipped",
            "concerns":           [],
            "review_recommended": False,
        }
        logger.info("  Step 5: LLM check skipped (authorization deficient by rules)")

    # Step 6: Classification (only if we're routing to fulfillment or review)
    if rule_validation["passed"]:
        logger.info("  Step 6: Request classification (Nova Pro)")
        classification = classify_request_type(
            normalized_fields,
            textract_output["line_blocks"],
        )
        logger.info(
            "    Type: %s (confidence: %.2f)",
            classification["request_type"],
            classification["confidence"],
        )
    else:
        classification = {
            "request_type": "unclassified",
            "confidence":   0.0,
            "reasoning":    "(not classified; authorization deficient)",
        }

    # Step 7: Assemble and route
    logger.info("  Step 7: Assembling record and routing")
    record = assemble_and_route(
        document_key,
        normalized_fields,
        signatures,
        rule_validation,
        llm_consistency,
        classification,
    )
    logger.info("  Done. Status: %s", record["status"])
    return record


# [EDITOR: Replaced all print() calls with logger.info() in process_records_request().
# The v1 used print() which goes to stdout and then to CloudWatch Logs in Lambda,
# same as logger, but print() bypasses the logging level configuration and doesn't
# produce structured log entries. None of these log lines contained PHI (they log
# document keys and metadata counts, not patient data), but logger is the correct
# pattern for Lambda. The corresponding Gap item ("Replace print() with structured
# JSON logging") has been removed from Gap to Production below since it's addressed.]


# Lambda entry point
def lambda_handler(event, context):
    """
    Lambda entry point for S3 event triggers.
    The S3 event fires when a new PDF lands in the records-requests/ prefix.
    """
    for record in event.get("Records", []):
        bucket       = record["s3"]["bucket"]["name"]
        document_key = record["s3"]["object"]["key"]
        try:
            result = process_records_request(bucket, document_key)
            logger.info(
                "Pipeline complete for %s: status=%s",
                document_key,
                result["status"],
            )
        except Exception as e:
            logger.error("Pipeline failed for %s: %s", document_key, type(e).__name__)
            # Do NOT log str(e). Exception messages can contain PHI from API responses.
            raise  # Re-raise to trigger Lambda retry and eventually DLQ
```

---

## Gap to Production

This example demonstrates the core patterns. Here's what you'd need to add before running this in a real release-of-information operation:

**Retry and throttling.** The `botocore.config.Config(retries={"max_attempts": 3, "mode": "adaptive"})` is in the client setup above. This handles `ThrottlingException` and `ServiceUnavailableException` for Textract and Bedrock. At healthcare scale, throttling is expected, not an edge case. For very high-volume deployments, also request Bedrock quota increases for both Sonnet and Nova Pro before go-live.

**LLM output retry.** The `_call_bedrock_with_retry()` helper above implements a one-retry pattern on `JSONDecodeError`: if the model returns markdown fences or preamble text despite instructions, the second attempt appends a JSON-only reinforcement suffix. This resolves the most common malformed-output failure mode. If both attempts fail, the consistency check conservatively routes to human review (rather than silently passing) and the classification falls back to the `general` queue. Both behaviors are the safe default.

**VPC endpoints.** In a production HIPAA VPC with no internet egress, you need VPC interface endpoints for `bedrock-runtime` (the Converse API) and `bedrock` (model management) separately. They are two different endpoints. `bedrock` alone will not route Converse API calls. You also need endpoints for Textract, SQS, SNS, DynamoDB, KMS, and CloudWatch Logs.

**Lambda timeouts.** The default 3-second Lambda timeout fails on the first Bedrock API call. Configure `rr-validate` at 5 minutes (Sonnet calls can take 2-5 seconds under normal load, 10-15 under high load; leave room for retry backoff, plus the `_call_bedrock_with_retry()` second attempt if needed). `rr-classify` at 3 minutes. `rr-extract` and `rr-route` at 2 minutes.

**PHI-safe logging.** All logger calls in this code log only metadata (document keys, status values, counts, model IDs). Never add debug logging that includes authorization text, patient names, or other PHI. Exception messages can carry PHI if they echo API response content; catch specific exception types rather than logging generic `str(e)`. Configure KMS encryption on all Lambda CloudWatch log groups (not automatic). Enable CloudWatch Log Data Protection on log groups to detect and mask common PHI patterns as a safety net.

**DynamoDB Decimal handling.** The `_to_decimal()` and `_floats_to_decimal()` helpers above convert all floats to Decimal before the DynamoDB write. DynamoDB raises `TypeError: Float types are not supported` on Python floats. `_floats_to_decimal()` is applied to the full record before `put_item()`, covering all nesting levels including the concerns list inside `llm_consistency_findings`.

**Model version storage.** The `model_versions` field in the DynamoDB record captures the Sonnet and Nova Pro model IDs used for each LLM call. This lets you reproduce the inference configuration for audit purposes. The cross-region inference profile IDs used here may be updated by AWS to point to new model versions; for strict version pinning, replace them with full foundation model ARNs (see comments near the model ID constants above).

**Complete HIPAA element validation.** The rule-based check above covers 5 of the 6 elements from 45 CFR § 164.508(c)(1) and does not cover the required statements from 164.508(c)(2). Your compliance team should review the full element list and expand `REQUIRED_ELEMENTS` accordingly before production.

**Authorized representative handling.** The signature check validates presence but does not distinguish patient signatures from authorized representative signatures. A representative's signature requires documentation of legal authority. Your human review workflow should include a step for verifying representative authority when indicated.

**Input validation and prompt injection defense.** The `_sanitize_for_prompt()` function in this example strips null bytes, C0/C1 control characters (except newlines and tabs), and common injection pattern strings from authorization text before including it in the Bedrock prompt. Authorization forms are a higher-risk surface than EOB column headers (Recipe 1.8): patients, attorneys, and law offices author the free-text fields. Wire a Bedrock Guardrail to the Converse API calls using the `guardrailConfig` parameter (the commented-out stub in `_call_bedrock_with_retry()` shows where) for production-grade coverage. [EDITOR: review fix]

**LLM output schema validation.** The response normalization in `check_authorization_consistency_llm()` handles the `overall_coherence` string value and clamps confidence. For stricter validation in production, add Pydantic or jsonschema validation on the full response structure: `review_recommended` as a string `"true"` instead of boolean `True` would evaluate as truthy (non-empty string) in a conditional, but `"false"` also evaluates as truthy. Explicit type coercion prevents this class of bug. The `_validate_no_phi_in_concerns()` function provides a first-pass check for PHI patterns in concern descriptions; wire Bedrock Guardrails PII detection on the Converse API output for production-grade coverage. [EDITOR: review fix]

**Structured logging and metrics.** Replace the `logging.basicConfig()` setup with structured JSON logging (e.g., `python-json-logger`). Emit CloudWatch custom metrics for: `AuthorizationDeficiencyRate`, `LLMReviewFlagRate`, `LLMParseRetryRate`, `RequestClassificationConfidence`, and `SignatureDetectionRate`. These metrics give operational visibility into pipeline behavior and help you tune the signature confidence threshold and LLM consistency prompt over time.

**Duplicate request detection.** The conditional DynamoDB write prevents duplicate records for the same document key. But the same fax arriving twice creates two different S3 keys. Add a pre-write check that compares patient ID, requestor fax, and records description for near-matches to catch re-submissions before writing a second record.

**Provisioned concurrency for cold start reduction.** Lambda cold starts for Python (500ms to 2s) add latency on the first invocation after an idle period. If your operations have predictable daily peaks (Monday morning batch processing is common in release-of-information), configure provisioned concurrency on the extraction and validation Lambda functions to keep them warm during peak hours.
