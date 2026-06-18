# Recipe 2.5: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 2.5. It shows one way you could translate those after-visit summary generation concepts into working Python using Amazon Bedrock, Amazon Comprehend Medical, and DynamoDB. It is not production-ready. There's no EHR integration, no portal publishing, no clinician review UI, no multi-language translation QA, and no SMS or email delivery. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd wire up to a health system on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline maps to the seven pseudocode steps from the main recipe: receive the note-signed event, pull encounter data, extract the structured summary object, generate the patient-facing draft, validate claims against source, apply a readability check, then render and deliver.

---

## Setup

You'll need the AWS SDK for Python:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `bedrock:InvokeModel` (for extraction and patient-facing generation models)
- `bedrock:ApplyGuardrail` (if you configure a Bedrock Guardrail for patient-facing content, which you should)
- `comprehendmedical:DetectEntitiesV2` (for the optional medication/dose cross-check)
- `s3:GetObject`, `s3:PutObject` (for extracted objects and signed summary archive)
- `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:UpdateItem` (for summary state and patient preferences)
- `healthlake:SearchWithGet`, `healthlake:ReadResource` (if HealthLake is your FHIR store; this example takes encounter data as a parameter to keep the AI pattern clear)
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` (for CloudWatch Logs)

You also need model access enabled in the Bedrock console. This pipeline uses two model tiers: a smaller, cheaper model for the extraction step and a stronger model for the patient-facing prose. The extraction task is well-bounded so a Haiku-class model is usually enough. The generation task cares a lot about tone, reading level, and multilingual quality, so spring for a Sonnet-class model or equivalent. Scope `bedrock:InvokeModel` to specific model ARNs in production, not a wildcard. The tutorial-level permissions below are fine for learning and will fail any serious IAM review.

One thing worth knowing before you start: Bedrock model IDs and inference profile IDs change over time as new versions come out, and the set available in your region depends on your AWS account's access. The IDs below are reasonable defaults at the time of writing. Verify in the Bedrock console and adjust for your region. For cross-region inference, use the inference profile ID (prefixed `us.` or `eu.` for US or EU profiles).

---

## Configuration and Constants

Everything that's configuration rather than logic lives here. Model IDs, reading-level target, validation thresholds, and the S3/DynamoDB resource names are the knobs you'll change most often between environments.

```python
import hashlib
import json
import logging
import math
import re
import time
import uuid
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records to CloudWatch
# Logs Insights for query-friendly analysis. Never log PHI: no patient names,
# no MRNs, no clinical note text, no generated summary bodies. The audit
# trail for the summary itself lives in S3 with access-controlled retrieval.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles Bedrock throttling. AVS generation tends to be bursty
# because clinicians sign notes in waves (end of morning clinic, end of day).
# Adaptive mode uses exponential backoff with jitter so retry storms don't
# pile on during those bursts.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers.
# Two Bedrock endpoints matter for this recipe:
#   bedrock-runtime: model inference (invoke_model). What we use below.
#   bedrock-agent-runtime: knowledge base retrieval. Not used here since
#   AVS generation is encounter-scoped (no external KB).
bedrock_runtime = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
comprehend_medical = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# --- Model Configuration ---
# Two tiers. Extraction is a narrow, well-bounded task where a smaller model
# is usually sufficient. Generation is where reading-level control, tone, and
# (critically) multilingual quality all matter, so use a capable model.
#
# If your region requires cross-region inference, use the inference profile ID:
#   e.g., "us.anthropic.claude-3-5-haiku-20241022-v1:0"
# TODO: verify the exact model IDs available in your region and account.
EXTRACTION_MODEL_ID = "anthropic.claude-3-5-haiku-20241022-v1:0"
GENERATION_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"

# Optional Bedrock Guardrail for patient-facing output. Configure one in the
# Bedrock console with content filters tuned for a patient-facing context and
# PII detection to catch accidental cross-patient disclosure. Leaving as None
# here means no guardrail is applied; set both fields in production.
GUARDRAIL_ID = None        # e.g., "abc123xyz"
GUARDRAIL_VERSION = None   # e.g., "DRAFT" or a numbered version

# --- Storage Configuration ---
# One bucket for extracted summary objects (intermediate, auditable) and
# signed summaries (final, retained per HIPAA). In production these are
# typically separate buckets with different lifecycle policies: drafts
# purged at 30-90 days, finals retained 6+ years per HIPAA requirements.
AVS_BUCKET = "your-avs-bucket"  # Replace with your bucket

# DynamoDB tables. In production, use separate tables for summary state and
# patient preferences, with GSIs for access patterns (by patient, by status).
AVS_SUMMARIES_TABLE = "avs-summaries"       # Partition key: summary_id
PATIENT_PREFERENCES_TABLE = "patient-preferences"  # Partition key: patient_id

# --- Pipeline Tuning ---
# Target reading level when the patient's preference is unknown. The CDC and
# AHRQ both recommend 6-8th grade for general-population patient content.
# Lower is better if you can hit it without losing clinical accuracy.
DEFAULT_READING_LEVEL = 7

# Buffer on the readability check. If the target is grade 7, accept up to 7.5
# before forcing regeneration. The Flesch-Kincaid formula has some noise and
# we don't want to regenerate endlessly over a 0.1 grade difference.
READABILITY_BUFFER = 0.5

# Max attempts at generation + readability loop. If we can't hit the target
# after this many tries, escalate for human editing rather than loop forever.
MAX_GENERATION_ATTEMPTS = 3

# Minimum fraction of factual claims that must trace to the structured
# summary object. Below this, the letter goes to clinician review or
# regeneration rather than direct-to-patient delivery. Don't go below 1.0
# for high-risk visit types (discharges, new cancer diagnoses). Allow
# slightly lower for routine visits only if you have a compensating review.
MIN_VALIDATION_RATE = 1.0

# Visit types that always require clinician review regardless of validation.
# These are the cases where a fabricated or misremembered detail is most
# likely to cause real harm.
HIGH_RISK_VISIT_TYPES = {
    "hospital_discharge",
    "ed_discharge",
    "new_cancer_diagnosis",
    "anticoagulation_initiation",
    "pediatric_discharge",
}
```

---

## Step 1: Receive the Note-Signed Event and Initialize State

*The pseudocode calls this `receive_note_signed_event(event)`. In production, an EHR integration publishes a note-signed event to EventBridge when a clinician signs an outpatient visit note or a discharge summary. For this example, we accept the event as a dict and write the initial state to DynamoDB before kicking off the rest of the pipeline.*

```python
def receive_note_signed_event(event: dict) -> str:
    """
    Initialize a new AVS case and return the summary_id for downstream processing.

    The event is the trigger for the entire pipeline. Because EventBridge
    delivers at-least-once, we first check idempotency using a fingerprint
    derived from encounter_id and signed_at. If a prior execution already
    handled this event, we return the existing summary_id without re-processing.

    Args:
        event: Dict with note-signed details from the EHR. Expected keys:
               - encounter_id: FHIR Encounter ID
               - patient_id:   FHIR Patient ID
               - provider_id:  signing provider
               - signed_at:    timestamp of note signature (ISO-8601)
               - visit_type:   outpatient, hospital_discharge, ed_discharge,
                               telehealth, etc.

    Returns:
        The generated summary_id (a UUID string).
    """
    # Idempotency gate: derive a deterministic fingerprint from encounter_id
    # and signed_at. A conditional write to DynamoDB prevents duplicate
    # processing from at-least-once delivery.
    fingerprint = hashlib.sha256(
        f"{event['encounter_id']}|{event.get('signed_at', '')}".encode()
    ).hexdigest()

    idempotency_table = dynamodb.Table("avs-idempotency")
    try:
        idempotency_table.put_item(
            Item={
                "fingerprint": fingerprint,
                "created_at": datetime.datetime.now(timezone.utc).isoformat(),
            },
            ConditionExpression="attribute_not_exists(fingerprint)",
        )
    except idempotency_table.meta.client.exceptions.ConditionalCheckFailedException:
        # Duplicate event. Retrieve and return existing summary_id.
        existing = idempotency_table.get_item(Key={"fingerprint": fingerprint})
        existing_id = existing.get("Item", {}).get("summary_id", "UNKNOWN")
        logger.info("Duplicate event for fingerprint=%s, returning existing %s", fingerprint, existing_id)
        return existing_id

    summary_id = str(uuid.uuid4())
    now = datetime.datetime.now(timezone.utc)

    # Store summary_id back on idempotency record for future duplicate lookups
    idempotency_table.update_item(
        Key={"fingerprint": fingerprint},
        UpdateExpression="SET summary_id = :sid",
        ExpressionAttributeValues={":sid": summary_id},
    )

    summary_record = {
        "summary_id": summary_id,
        "status": "INITIATED",
        "encounter_id": event["encounter_id"],
        "patient_id": event["patient_id"],
        "provider_id": event["provider_id"],
        "visit_type": event.get("visit_type", "outpatient"),
        "signed_at": event.get("signed_at", now.isoformat()),
        "created_at": now.isoformat(),
    }

    summaries_table = dynamodb.Table(AVS_SUMMARIES_TABLE)
    summaries_table.put_item(Item=summary_record)

    # In production, this is where you'd kick off a Step Functions execution.
    # That gives you per-step retries, observability into stuck cases, and
    # a clean state machine for the regeneration loop and review branching.
    # Keeping it sequential here for clarity.
    #
    # stepfunctions_client = boto3.client("stepfunctions")
    # stepfunctions_client.start_execution(
    #     stateMachineArn=AVS_STATE_MACHINE_ARN,
    #     name=f"avs-{summary_id}",
    #     input=json.dumps({"summary_id": summary_id}),
    # )

    logger.info(
        "Initialized AVS case %s for encounter=%s visit_type=%s",
        summary_id, event["encounter_id"], event.get("visit_type", "outpatient"),
    )
    return summary_id
```

---

## Step 2: Pull Encounter Data and Patient Preferences

*The pseudocode calls this `pull_encounter_data(patient_id, encounter_id)`. In production, this retrieves FHIR resources scoped to the encounter (Encounter, DocumentReference, MedicationRequest, ServiceRequest, Appointment, Condition) from HealthLake or the EHR's FHIR API. For this example, we accept the clinical data as a parameter to keep the focus on the AI pattern, and we pull patient preferences from DynamoDB.*

```python
def pull_encounter_data(
    patient_id: str,
    encounter_id: str,
    encounter_clinical_data: dict,
) -> dict:
    """
    Gather everything needed to generate an AVS for this encounter.

    In a real deployment, encounter_clinical_data comes from HealthLake or
    the EHR's FHIR API. The scope is intentionally narrow: today's encounter,
    not the patient's full chart. Narrow scope keeps latency low, cost down,
    and satisfies HIPAA's minimum-necessary principle.

    Args:
        patient_id:              The patient's FHIR ID.
        encounter_id:            The encounter's FHIR ID.
        encounter_clinical_data: Dict with encounter-scoped FHIR resources.
                                 Expected keys: encounter, medications (list),
                                 orders (list), referrals (list),
                                 appointments (list), conditions (list),
                                 note_text (concatenated note content).

    Returns:
        Dict with the clinical data plus patient preferences applied.
    """
    # Fetch patient preferences. Language, target reading level, delivery
    # channel, accommodations. In production these come from the EHR's
    # patient registration or from a dedicated preferences service. Fall
    # back to sensible defaults if the record is missing.
    prefs_table = dynamodb.Table(PATIENT_PREFERENCES_TABLE)
    prefs_response = prefs_table.get_item(Key={"patient_id": patient_id})
    patient_prefs = prefs_response.get("Item") or {}

    # Default preferences if none are on file. English at default reading
    # level, portal delivery, no special accommodations.
    defaults = {
        "language": "en",
        "reading_level": DEFAULT_READING_LEVEL,
        "delivery_channels": ["portal"],
        "accommodations": [],
        "preferred_name": None,
    }
    for key, default_value in defaults.items():
        patient_prefs.setdefault(key, default_value)

    # DynamoDB returns Decimal for numerics; convert to int for the
    # generation prompt so we don't get "Decimal('7')" in the prompt text.
    if isinstance(patient_prefs["reading_level"], Decimal):
        patient_prefs["reading_level"] = int(patient_prefs["reading_level"])

    logger.info(
        "Loaded preferences for patient=%s: lang=%s reading_level=%s channels=%s",
        patient_id, patient_prefs["language"], patient_prefs["reading_level"],
        patient_prefs["delivery_channels"],
    )

    return {
        "encounter": encounter_clinical_data.get("encounter", {}),
        "medications": encounter_clinical_data.get("medications", []),
        "orders": encounter_clinical_data.get("orders", []),
        "referrals": encounter_clinical_data.get("referrals", []),
        "appointments": encounter_clinical_data.get("appointments", []),
        "conditions": encounter_clinical_data.get("conditions", []),
        "note_text": encounter_clinical_data.get("note_text", ""),
        "patient_prefs": patient_prefs,
    }
```

---

## Step 3: Extract the Structured Summary Object

*The pseudocode calls this `extract_summary_object(encounter_data)`. This is the step that turns messy clinical content into a fielded object. Structured data (medication orders, appointments) gets copied through directly. Unstructured note content (warning signs discussed, education topics, return instructions) gets pulled out by the LLM. Comprehend Medical runs as an optional cross-check on medications since that's the highest-risk category.*

```python
def extract_summary_object(
    summary_id: str,
    encounter_data: dict,
) -> dict:
    """
    Build a structured summary object that drives patient-facing generation.

    The object has discrete fields for each category of content a patient
    might need: diagnoses, medications, tests, referrals, follow-up, warning
    signs, education topics, lifestyle instructions. Structured EHR data
    flows in directly; note prose is extracted by the LLM with a strict
    "use only what's documented" instruction.

    Args:
        summary_id:     The summary identifier (for audit logging).
        encounter_data: Output of pull_encounter_data.

    Returns:
        Dict with the structured summary object, persisted to S3 for audit.
    """
    # --- Medications: start from structured FHIR MedicationRequest data ---
    # The structured data is authoritative for drug names, doses, and change
    # type. Note-based extraction can complement but not override this.
    medications = []
    for med_req in encounter_data["medications"]:
        # Filter to meds that were actually changed today. Adjust this logic
        # based on your EHR's representation of "med changes at this encounter."
        if not med_req.get("changed_today"):
            continue
        medications.append({
            "name": med_req.get("name"),
            "dose": med_req.get("dose"),
            "frequency": med_req.get("frequency"),
            "change_type": med_req.get("change_type"),  # new, dose_changed, discontinued
            "reason": med_req.get("reason", ""),
            "source_id": med_req.get("id"),
        })

    # --- Comprehend Medical: cross-check medications in the note text ---
    # This is the optional belt-and-suspenders for the highest-risk category.
    # If Comprehend Medical finds a dose in the note that doesn't match any
    # structured order, flag it for review. Don't silently trust the model.
    med_entities_from_note = []
    note_text = encounter_data.get("note_text", "")
    if note_text:
        # Comprehend Medical has a per-call character limit (~20KB). For
        # longer notes, you'd chunk and merge results. Keeping it simple here.
        try:
            cm_response = comprehend_medical.detect_entities_v2(
                Text=note_text[:20000]
            )
            for entity in cm_response.get("Entities", []):
                if entity.get("Category") == "MEDICATION":
                    med_entities_from_note.append({
                        "text": entity.get("Text"),
                        "attributes": [
                            {"type": a.get("Type"), "text": a.get("Text")}
                            for a in entity.get("Attributes", [])
                        ],
                    })
        except comprehend_medical.exceptions.ClientError as exc:
            # Comprehend Medical failure shouldn't block the whole pipeline.
            # Log and continue; the structured EHR data is still the source
            # of truth for medication facts.
            logger.warning("Comprehend Medical call failed: %s", exc)

    # --- LLM extraction of unstructured note content ---
    # Warning signs, education topics, return instructions: these typically
    # live in prose, not structured fields. Use the cheaper extraction model
    # here; the task is well-bounded and doesn't need the generation model's
    # nuance.
    extraction_system = """You are extracting structured fields from a clinical visit note for use in an after-visit summary.

Return ONLY valid JSON in this exact structure:
{
  "diagnoses_discussed": [
    {"name": "plain-language diagnosis name", "is_new_today": true}
  ],
  "warning_signs_given": [
    "specific warning sign or 'call if' instruction, copied from the note"
  ],
  "education_topics": ["topic discussed during counseling"],
  "lifestyle_instructions": ["specific lifestyle recommendation given"],
  "return_instructions": "text explaining when to come back or call",
  "follow_up_plan_note_text": "what the note says about follow-up (may be blank if structured Appointment resource has this)"
}

STRICT RULES:
- Extract ONLY information explicitly documented in the note.
- Do NOT infer warning signs from diagnoses. If the note does not list 'call if fever over 101', do not add it.
- If a field has no content in the note, return an empty list or empty string.
- Do NOT add general medical advice, even when it seems helpful."""

    extraction_user = f"CLINICAL NOTE:\n\n{note_text}\n\nExtract the structured fields as JSON."

    extraction_body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2048,
        "temperature": 0.0,  # Deterministic extraction
        "system": extraction_system,
        "messages": [{"role": "user", "content": extraction_user}],
    })

    extraction_response = bedrock_runtime.invoke_model(
        modelId=EXTRACTION_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=extraction_body,
    )
    extraction_payload = json.loads(extraction_response["body"].read())
    extracted = _parse_json_response(extraction_payload["content"][0]["text"])

    # --- Follow-up: prefer structured Appointment over note text ---
    # Appointments have concrete dates; note text has "follow up in 2 weeks".
    # When both exist, structured wins.
    follow_up_appointment = None
    future_appointments = [
        a for a in encounter_data["appointments"]
        if a.get("status") in ("booked", "pending")
    ]
    if future_appointments:
        # Take the soonest future appointment as the primary follow-up
        follow_up_appointment = sorted(
            future_appointments,
            key=lambda a: a.get("start", "9999-12-31"),
        )[0]

    # --- Orders and referrals: straight pass-through from structured data ---
    orders = [
        {
            "name": o.get("name"),
            "instructions": o.get("instructions", ""),
            "when_expected": o.get("when_expected", ""),
            "source_id": o.get("id"),
        }
        for o in encounter_data["orders"]
    ]
    referrals = [
        {
            "specialty": r.get("specialty"),
            "reason": r.get("reason", ""),
            "how_to_schedule": r.get("how_to_schedule", ""),
            "source_id": r.get("id"),
        }
        for r in encounter_data["referrals"]
    ]

    # --- Assemble the final summary object ---
    encounter_date = encounter_data["encounter"].get("start", "")
    summary_object = {
        "summary_id": summary_id,
        "encounter_date": encounter_date,
        "visit_type": encounter_data["encounter"].get("type", ""),
        "diagnoses": extracted.get("diagnoses_discussed", []),
        "medications": medications,
        "medications_cross_check_from_note": med_entities_from_note,
        "orders": orders,
        "referrals": referrals,
        "follow_up_appointment": follow_up_appointment,
        "follow_up_plan_note_text": extracted.get("follow_up_plan_note_text", ""),
        "warning_signs": extracted.get("warning_signs_given", []),
        "education_topics": extracted.get("education_topics", []),
        "lifestyle_instructions": extracted.get("lifestyle_instructions", []),
        "return_instructions": extracted.get("return_instructions", ""),
    }

    # Persist for auditability. Every generated summary should be traceable
    # back to the exact structured object that drove generation.
    s3_client.put_object(
        Bucket=AVS_BUCKET,
        Key=f"summary-extractions/{summary_id}/extracted.json",
        Body=json.dumps(summary_object, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
        # ServerSideEncryption is assumed to be bucket-default SSE-KMS with a
        # customer-managed key. If not, set explicitly:
        # ServerSideEncryption="aws:kms",
        # SSEKMSKeyId="your-cmk-arn",
    )

    logger.info(
        "Extracted summary object for %s: %d meds, %d orders, %d warning signs",
        summary_id, len(medications), len(orders),
        len(summary_object["warning_signs"]),
    )
    return summary_object

def _parse_json_response(raw_text: str) -> dict:
    """
    Parse JSON from the model's response, stripping common markdown wrappers.

    Claude sometimes wraps JSON in markdown code fences even when instructed
    not to. This helper is defensive so the pipeline doesn't crash on that.
    """
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    return json.loads(cleaned.strip())
```

---

## Step 4: Generate the Patient-Facing Summary

*The pseudocode calls this `generate_summary(summary_object, patient_prefs)`. This is the writing step. The model gets the structured object and the patient's preferences, and produces prose at the target reading level in the target language. Every factual claim the model produces must reference a source field in the structured object, so downstream validation can verify nothing was fabricated.*

```python
def generate_summary(
    summary_object: dict,
    patient_prefs: dict,
    regeneration_hint: str = "",
) -> dict:
    """
    Generate the patient-facing after-visit summary narrative with provenance.

    The prompt enforces four things: language, reading level, structure, and
    grounding. The model is a writer, not a decision maker. Every specific
    claim (dose, date, test name, warning sign) has to come from a field in
    the structured summary object.

    Args:
        summary_object:    Structured summary from Step 3.
        patient_prefs:     Language, reading level, preferred name, accommodations.
        regeneration_hint: Extra instruction for retries. Populated by the
                           readability loop when the first draft reads too
                           high, or by validation failures.

    Returns:
        Dict with the generated summary text and provenance (factual claims
        mapped to source fields in the summary object).
    """
    language = patient_prefs.get("language", "en")
    reading_level = patient_prefs.get("reading_level", DEFAULT_READING_LEVEL)
    preferred_name = patient_prefs.get("preferred_name") or ""
    accommodations = patient_prefs.get("accommodations", [])

    # Language-aware phrasing. For languages where direct generation is
    # reliable (Spanish, French, Mandarin, Japanese, German, Portuguese),
    # tell the model to write in the target language. For less-supported
    # languages, the safer path is to generate in English and post-process
    # through Amazon Translate. The boundary is fuzzy and should be
    # validated per language with native speakers.
    # Note: these instruction strings must be saved as UTF-8 (no BOM).
    # Mojibake in prompts is a silent failure mode, not an obvious crash.
    language_instruction = {
        "en": "Write the entire summary in English.",
        "es": "Escribe todo el resumen en español. Usa un tono natural y respetuoso.",
        "zh": "用中文简体写整个摘要。语气自然、尊重患者。",
        "vi": "Viết toàn bộ bản tóm tắt bằng tiếng Việt. Giữ giọng văn tự nhiên, tôn trọng.",
    }.get(language, f"Write the entire summary in the language with ISO code '{language}'.") 

    generation_system = f"""You are drafting a patient-facing after-visit summary. Your reader is a patient who just finished a medical appointment. They may be tired, anxious, or distracted.

LANGUAGE: {language_instruction}

READING LEVEL: Target {reading_level}th-grade reading level. Short sentences (average under 15 words). Common words. When a medical term is unavoidable, follow it with a plain-language explanation in parentheses on first use. Active voice. Concrete instructions.

TONE: Calm, direct, and respectful. Never alarmist. Never condescending. Never overly casual.

GROUNDING RULES:
1. Use ONLY information in the structured summary object provided. Do NOT add diagnoses, medications, dosages, dates, warning signs, follow-up details, or education content that are not in the input.
2. Every specific claim (medication dose, follow-up date, test name, warning sign, provider name) must trace to a field in the input.
3. If the input lacks information the reader needs, write "Talk to your doctor's office if you have questions" rather than inventing content.
4. If a structured field is empty, omit the corresponding section. Do not fabricate content to fill a section.

STRUCTURE: Use these section headers in this order, omitting sections that have no content in the input:
1. "What we talked about today"   (diagnoses and key discussion points)
2. "Changes to your medications"  (new meds, dose changes, stopped meds)
3. "Tests you need"                (orders with instructions)
4. "People to see"                 (referrals)
5. "Your next visit"               (follow-up appointment details)
6. "Watch for these"               (warning signs; when to call or go to ER)
7. "Things to do at home"          (lifestyle instructions)
8. "Questions?"                    (how to contact the practice)

ACCOMMODATIONS: {accommodations if accommodations else "None specified"}

OUTPUT FORMAT: Return ONLY valid JSON in this exact structure:
{{
  "summary_markdown": "the full summary as a single string with markdown headers and bullet lists",
  "provenance": {{
    "factual_claims": [
      {{
        "claim": "the specific factual assertion in the summary text",
        "source_field": "JSON path into the input, e.g. 'medications[0].dose'",
        "asserted_value": "the specific value claimed in the summary"
      }}
    ]
  }}
}}"""

    user_message_parts = [
        f"STRUCTURED SUMMARY OBJECT:\n{json.dumps(summary_object, indent=2, default=str)}",
        f"PATIENT PREFERRED NAME: {preferred_name or '(none on file; use generic address)'}",
    ]
    if regeneration_hint:
        user_message_parts.append(f"REGENERATION HINT: {regeneration_hint}")
    user_message_parts.append("Generate the after-visit summary as JSON.")
    user_message = "\n\n".join(user_message_parts)

    # Slightly higher temperature than extraction because we want natural
    # prose variation. Too low and the summary reads as mechanical. Too high
    # and the model drifts from the grounding constraints.
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4000,
        "temperature": 0.3,
        "system": generation_system,
        "messages": [{"role": "user", "content": user_message}],
    }

    # Apply the Bedrock Guardrail if configured. The guardrail is a safety
    # net; it does not replace the validation step. For patient-facing
    # content, configure the guardrail with PII detection (catches accidental
    # cross-patient leakage) and content filters tuned for patient context.
    invoke_kwargs = {
        "modelId": GENERATION_MODEL_ID,
        "contentType": "application/json",
        "accept": "application/json",
        "body": json.dumps(request_body),
    }
    if GUARDRAIL_ID and GUARDRAIL_VERSION:
        invoke_kwargs["guardrailIdentifier"] = GUARDRAIL_ID
        invoke_kwargs["guardrailVersion"] = GUARDRAIL_VERSION

    response = bedrock_runtime.invoke_model(**invoke_kwargs)
    response_payload = json.loads(response["body"].read())
    raw_text = response_payload["content"][0]["text"]
    result = _parse_json_response(raw_text)

    logger.info(
        "Generated summary (%d chars, %d factual claims)",
        len(result.get("summary_markdown", "")),
        len(result.get("provenance", {}).get("factual_claims", [])),
    )
    return {
        "summary_markdown": result.get("summary_markdown", ""),
        "provenance": result.get("provenance", {"factual_claims": []}),
    }
```

---

## Step 5: Validate Claims Against the Source

*The pseudocode calls this `validate_summary(summary_text, provenance, summary_object)`. Every specific claim in the generated summary has to trace back to a field in the structured object. Dose values must match. Dates must match. Warning signs must appear in the input. Claims that don't match either trigger regeneration or escalate to clinician review depending on severity.*

```python
def validate_summary(
    provenance: dict,
    summary_object: dict,
) -> dict:
    """
    Verify each factual claim against the structured summary object.

    Numeric claims (doses, counts, dates) require exact match after
    normalization. Text claims (warning signs, diagnoses) pass if the
    claimed content substantively overlaps the source value. The overlap
    check here uses simple substring matching. Production systems often
    layer on semantic similarity (embedding-based) for a more forgiving
    but still grounded check.

    Args:
        provenance:     The factual_claims map from the generation step.
        summary_object: The structured object the model was supposed to use.

    Returns:
        Dict with validation status, per-claim results, and the overall
        validation rate.
    """
    claims = provenance.get("factual_claims", [])
    if not claims:
        # A summary with zero tracked claims is either empty or the model
        # ignored the provenance instruction. Either way, don't deliver it.
        return {
            "status": "REQUIRES_REGENERATION",
            "validation_rate": 0.0,
            "unverified_claims": [],
            "reason": "no_claims_tracked",
        }

    unverified = []

    for claim in claims:
        source_field = claim.get("source_field", "")
        asserted_value = (claim.get("asserted_value") or "").strip()

        # Walk the source_field JSON path into the summary_object. The path
        # uses dot notation with optional [N] list indexing, e.g.
        # "medications[0].dose" or "follow_up_appointment.start".
        source_value = _resolve_json_path(summary_object, source_field)

        if source_value is None:
            unverified.append({
                "claim": claim.get("claim"),
                "source_field": source_field,
                "asserted_value": asserted_value,
                "issue": "source_field_not_in_input",
                "severity": "HIGH",
            })
            continue

        # Normalize both sides for comparison. Strip whitespace, lowercase,
        # collapse spaces. This handles common phrasing differences while
        # still flagging substantive mismatches.
        asserted_norm = _normalize_for_match(asserted_value)
        source_norm = _normalize_for_match(str(source_value))

        if not asserted_norm or not source_norm:
            # One side is empty. Flag for review.
            unverified.append({
                "claim": claim.get("claim"),
                "source_field": source_field,
                "asserted_value": asserted_value,
                "source_value": str(source_value),
                "issue": "empty_value",
                "severity": "MEDIUM",
            })
            continue

        # Bidirectional substring check: asserted must appear in source
        # or source must appear in asserted. This is forgiving (it accepts
        # "5 mg" claimed against a source "warfarin 5 mg once daily") but
        # will reject a dose mismatch ("10 mg" vs source "5 mg").
        if asserted_norm in source_norm or source_norm in asserted_norm:
            continue  # verified

        unverified.append({
            "claim": claim.get("claim"),
            "source_field": source_field,
            "asserted_value": asserted_value,
            "source_value": str(source_value),
            "issue": "value_mismatch",
            "severity": "HIGH",
        })

    total = len(claims)
    verified = total - len(unverified)
    validation_rate = verified / total if total else 0.0

    high_severity_count = sum(1 for u in unverified if u["severity"] == "HIGH")

    if high_severity_count > 0:
        status = "REQUIRES_REGENERATION"
    elif validation_rate >= MIN_VALIDATION_RATE:
        status = "VALIDATED"
    else:
        status = "NEEDS_CLINICIAN_REVIEW"

    logger.info(
        "Validation: %d/%d claims verified (rate=%.2f), status=%s",
        verified, total, validation_rate, status,
    )
    return {
        "status": status,
        "validation_rate": validation_rate,
        "unverified_claims": unverified,
    }

def _resolve_json_path(obj: dict, path: str):
    """
    Walk a dot-notation path with optional list indexing into a dict.

    Supports paths like "medications[0].dose" and "follow_up_appointment.start".
    Returns None for any path that doesn't exist.
    """
    if not path:
        return None
    current = obj
    # Split on dots, then handle [N] indexing within each segment.
    for segment in path.split("."):
        match = re.match(r"^([^\[]+)(?:\[(\d+)\])?$", segment)
        if not match:
            return None
        key, idx = match.group(1), match.group(2)
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
        if idx is not None:
            idx_int = int(idx)
            if not isinstance(current, list) or idx_int >= len(current):
                return None
            current = current[idx_int]
    return current

def _normalize_for_match(text: str) -> str:
    """Lowercase, strip, and collapse whitespace for tolerant comparison."""
    return re.sub(r"\s+", " ", text.strip().lower())
```

---

## Step 6: Check Readability and Loop if Needed

*The pseudocode calls this `check_readability(summary_text, target_grade_level)`. Even with a grade-level instruction in the prompt, LLMs drift upward. A Flesch-Kincaid check closes the loop: compute the grade level, and if it exceeds the patient's target, regenerate with a stronger simplification hint. This is cheap (arithmetic) and catches reading-level failures the model wouldn't notice.*

```python
def check_readability(summary_text: str, target_grade_level: int) -> dict:
    """
    Compute Flesch-Kincaid Grade Level on the generated summary.

    The formula:
      FKGL = 0.39 * (words / sentences) + 11.8 * (syllables / words) - 15.59

    This is English-language specific. For Spanish, use INFLESZ or
    Fernández Huerta. For Mandarin, grade-level formulas don't translate
    directly; use character-count heuristics or trained readability models.
    A production pipeline should swap validators per language.

    Args:
        summary_text:       The markdown summary body.
        target_grade_level: The patient's target reading level.

    Returns:
        Dict with pass/fail, computed grade, and remediation hint.
    """
    # Strip markdown syntax that shouldn't affect readability scoring.
    # Remove headers, bullet markers, bold/italic markers.
    plain_text = re.sub(r"^#+\s*", "", summary_text, flags=re.MULTILINE)
    plain_text = re.sub(r"^\s*[-*]\s*", "", plain_text, flags=re.MULTILINE)
    plain_text = re.sub(r"\*\*|__", "", plain_text)

    # Sentence count: end-of-sentence punctuation. Not perfect (abbreviations,
    # colons in structured text) but good enough for a first-cut score.
    sentences = re.split(r"[.!?]+\s+", plain_text.strip())
    sentences = [s for s in sentences if s.strip()]
    sentence_count = max(len(sentences), 1)

    # Word count: whitespace-separated tokens with at least one letter.
    words = re.findall(r"\b[a-zA-Z]+\b", plain_text)
    word_count = max(len(words), 1)

    # Syllable count: approximation. For each word, count vowel groupings.
    # Standard heuristic: vowel runs count as one syllable each, subtract one
    # for silent trailing 'e', minimum of one syllable per word. Good enough
    # for a Flesch-Kincaid approximation; in production, use a library like
    # pyphen or textstat for a more accurate count.
    syllable_count = 0
    for word in words:
        syllable_count += _approximate_syllables(word)
    syllable_count = max(syllable_count, word_count)  # floor at one per word

    fk_grade = (
        0.39 * (word_count / sentence_count)
        + 11.8 * (syllable_count / word_count)
        - 15.59
    )

    target_with_buffer = target_grade_level + READABILITY_BUFFER
    passed = fk_grade <= target_with_buffer

    hint = ""
    if not passed:
        hint = (
            f"The previous draft read at approximately grade {fk_grade:.1f}. "
            f"Rewrite at grade {target_grade_level}. Use shorter sentences "
            f"(under 12 words), simpler words, and avoid multi-syllable "
            f"clinical terminology. Break long sentences into two shorter ones."
        )

    logger.info(
        "Readability check: computed grade %.1f (target %d, buffer %.1f), pass=%s",
        fk_grade, target_grade_level, READABILITY_BUFFER, passed,
    )
    return {
        "pass": passed,
        "fk_grade": round(fk_grade, 2),
        "target_grade_level": target_grade_level,
        "word_count": word_count,
        "sentence_count": sentence_count,
        "hint": hint,
    }

def _approximate_syllables(word: str) -> int:
    """Cheap syllable estimator based on vowel groupings."""
    word = word.lower()
    if not word:
        return 0
    vowels = "aeiouy"
    count = 0
    prev_was_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_was_vowel:
            count += 1
        prev_was_vowel = is_vowel
    # Silent trailing 'e'
    if word.endswith("e") and count > 1:
        count -= 1
    return max(count, 1)
```

---

## Step 7: Render for Delivery Channel and Archive

*The pseudocode calls this `render_and_deliver(summary_id, summary_text, patient_prefs)`. Same content, different rendering. Portal HTML, PDF for print, structured SMS. This example focuses on the archive write and shows where the per-channel rendering and delivery hooks plug in, without implementing actual portal, email, or SMS integrations.*

```python
def render_and_deliver(
    summary_id: str,
    summary_markdown: str,
    patient_prefs: dict,
    validation_status: str,
    requires_clinician_review: bool,
) -> dict:
    """
    Archive the finalized summary and route for delivery.

    This example writes the final summary to S3 and updates the DynamoDB
    record. Real portal, SMS, and email integrations are stubbed as comments
    because each has its own setup (EHR portal API, Pinpoint SMS channel,
    SES verified domains) that isn't useful to demo here.

    Args:
        summary_id:                The summary identifier.
        summary_markdown:          The generated summary text.
        patient_prefs:             Preferences dict with delivery_channels.
        validation_status:         VALIDATED / NEEDS_CLINICIAN_REVIEW.
        requires_clinician_review: True if visit_type is high risk or
                                   validation flagged items.

    Returns:
        Dict with delivery status and the channels that were attempted.
    """
    delivered_channels = []

    # Always archive the final markdown. This is the authoritative record of
    # what was sent to the patient. HIPAA retention (typically 6+ years)
    # applies. Use SSE-KMS encryption with a customer-managed key; bucket
    # defaults should enforce this, but set explicitly if in doubt.
    final_key = f"final-summaries/{summary_id}/summary.md"
    s3_client.put_object(
        Bucket=AVS_BUCKET,
        Key=final_key,
        Body=summary_markdown.encode("utf-8"),
        ContentType="text/markdown; charset=utf-8",
    )

    # --- Delivery routing ---
    # In a real system, each channel has its own rendering and delivery call.
    # Stubbed here to keep the example focused on the AI pattern.
    channels = patient_prefs.get("delivery_channels", ["portal"])

    if requires_clinician_review:
        # Hold for clinician review; don't auto-deliver.
        logger.info(
            "Summary %s held for clinician review (not delivered to patient)",
            summary_id,
        )
        final_status = "PENDING_CLINICIAN_REVIEW"
    else:
        for channel in channels:
            if channel == "portal":
                # Stub: in production, call the EHR's portal document API
                # (Epic's MyChart, Oracle Health, athenahealth) to publish
                # the HTML-rendered summary.
                #
                # portal_html = _render_markdown_to_html(summary_markdown)
                # ehr_portal_api.publish_document(
                #     patient_id=patient_prefs["patient_id"],
                #     document_type="after_visit_summary",
                #     content=portal_html,
                # )
                delivered_channels.append("portal")

            elif channel == "email":
                # Stub: SES sends secure email with PDF attachment. Requires
                # SES verified sending domain, and PHI-appropriate delivery
                # (typically a portal link rather than PHI in the email body).
                #
                # pdf_bytes = _render_markdown_to_pdf(
                #     summary_markdown,
                #     large_print="large_print" in patient_prefs.get("accommodations", []),
                # )
                # ses_client.send_raw_email(...)
                delivered_channels.append("email")

            elif channel == "sms":
                # Stub: SMS must NOT contain clinical content (medications,
                # doses, warning signs). Default to notification-plus-portal-link:
                # "Your after-visit summary is ready. View it in the patient
                # portal: [link]." Only send clinical content if the patient
                # has granted explicit sms_phi_consent after risk disclosure.
                #
                # if patient_prefs.get("sms_phi_consent") == "granted":
                #     sms_body = _extract_action_items_only(summary_markdown)
                # else:
                #     sms_body = "Your after-visit summary is ready. View it in the patient portal."
                # pinpoint_client.send_messages(...)
                delivered_channels.append("sms")

            else:
                logger.warning("Unknown delivery channel %s for %s", channel, summary_id)

        final_status = "DELIVERED" if delivered_channels else "DELIVERY_FAILED"

    # Update the summary record. DynamoDB requires Decimal for numerics,
    # but the fields here are all strings and lists, so no conversion needed.
    summaries_table = dynamodb.Table(AVS_SUMMARIES_TABLE)
    summaries_table.update_item(
        Key={"summary_id": summary_id},
        UpdateExpression=(
            "SET #status = :status, "
            "validation_status = :vs, "
            "final_key = :fk, "
            "delivered_channels = :dc, "
            "delivered_at = :da"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": final_status,
            ":vs": validation_status,
            ":fk": final_key,
            ":dc": delivered_channels,
            ":da": datetime.datetime.now(timezone.utc).isoformat(),
        },
    )

    logger.info(
        "Summary %s status=%s delivered_channels=%s",
        summary_id, final_status, delivered_channels,
    )
    return {
        "status": final_status,
        "final_key": final_key,
        "delivered_channels": delivered_channels,
    }
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This runs all seven steps sequentially for one encounter. In production, each step becomes a Step Functions state with its own retry policy and error handling, and the regeneration loop is a proper state-machine loop rather than a Python `for` loop.

```python
def generate_after_visit_summary(
    event: dict,
    encounter_clinical_data: dict,
) -> dict:
    """
    Run the full AVS generation pipeline for one encounter.

    Steps (matching the Recipe 2.5 pseudocode):
      1. Receive and initialize the case from a note-signed event
      2. Pull encounter data and patient preferences
      3. Extract the structured summary object
      4. Generate the patient-facing narrative
      5. Validate claims against the source object
      6. Apply a readability check (with regeneration loop)
      7. Render and deliver (or route for clinician review)

    Args:
        event:                   Note-signed event dict from the EHR.
        encounter_clinical_data: Encounter-scoped clinical data.
                                 In production, fetched from HealthLake/FHIR;
                                 passed in here to keep the example focused.

    Returns:
        Dict with summary_id, status, and the final summary text.
    """
    start = time.time()

    # Step 1
    print(f"Step 1: Receiving note-signed event for encounter {event['encounter_id']}...")
    summary_id = receive_note_signed_event(event)
    print(f"  summary_id: {summary_id}")

    # Step 2
    print("Step 2: Pulling encounter data and patient preferences...")
    encounter_data = pull_encounter_data(
        patient_id=event["patient_id"],
        encounter_id=event["encounter_id"],
        encounter_clinical_data=encounter_clinical_data,
    )
    print(f"  {len(encounter_data['medications'])} meds, "
          f"{len(encounter_data['orders'])} orders, "
          f"lang={encounter_data['patient_prefs']['language']}")

    # Step 3
    print("Step 3: Extracting structured summary object...")
    summary_object = extract_summary_object(summary_id, encounter_data)
    print(f"  Extracted {len(summary_object['warning_signs'])} warning signs, "
          f"{len(summary_object['education_topics'])} education topics")

    # Steps 4-6: generation + validation + readability loop
    patient_prefs = encounter_data["patient_prefs"]
    visit_type = event.get("visit_type", "outpatient")

    summary_result = None
    validation = None
    readability = None
    regeneration_hint = ""

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        print(f"Step 4 (attempt {attempt}): Generating patient-facing summary...")
        summary_result = generate_summary(
            summary_object=summary_object,
            patient_prefs=patient_prefs,
            regeneration_hint=regeneration_hint,
        )
        print(f"  Generated {len(summary_result['summary_markdown'])} chars")

        print("Step 5: Validating claims against source...")
        validation = validate_summary(
            provenance=summary_result["provenance"],
            summary_object=summary_object,
        )
        print(f"  status={validation['status']} "
              f"rate={validation['validation_rate']:.2f}")

        if validation["status"] == "REQUIRES_REGENERATION":
            # Build a hint for the next attempt that points at the specific
            # problems. Giving the model concrete feedback beats a generic
            # "try again" instruction.
            issues = "; ".join(
                f"{u.get('issue')}: claimed '{u.get('asserted_value')}' "
                f"for field {u.get('source_field')}"
                for u in validation["unverified_claims"][:3]
            )
            regeneration_hint = (
                f"The previous draft had validation failures: {issues}. "
                f"Stick strictly to the structured summary object values."
            )
            continue

        print(f"Step 6: Readability check (target grade {patient_prefs['reading_level']})...")
        readability = check_readability(
            summary_text=summary_result["summary_markdown"],
            target_grade_level=patient_prefs["reading_level"],
        )
        print(f"  fk_grade={readability['fk_grade']} pass={readability['pass']}")

        if readability["pass"]:
            break  # validation passed AND readability passed

        # Readability failed; loop with a hint. Validation was fine, so we
        # don't want to lose that. The hint focuses on simplification.
        regeneration_hint = readability["hint"]
    else:
        # Exhausted attempts. Fall through with whatever we have and route
        # for clinician review.
        print(f"  Gave up after {MAX_GENERATION_ATTEMPTS} attempts; will route to review")

    # Step 7
    # Require clinician review for high-risk visits, validation flags,
    # or readability-loop failures. If all generation attempts exhausted
    # without passing validation, route to review rather than auto-delivering
    # an unvalidated summary.
    requires_review = (
        visit_type in HIGH_RISK_VISIT_TYPES
        or (validation and validation["status"] in ("NEEDS_CLINICIAN_REVIEW", "REQUIRES_REGENERATION"))
        or (readability and not readability["pass"])
        or readability is None  # loop exhausted before readability was checked
    )

    print(f"Step 7: Rendering and routing (clinician_review={requires_review})...")
    delivery = render_and_deliver(
        summary_id=summary_id,
        summary_markdown=summary_result["summary_markdown"],
        patient_prefs=patient_prefs,
        validation_status=validation["status"],
        requires_clinician_review=requires_review,
    )

    elapsed_ms = int((time.time() - start) * 1000)
    print(f"\nDone. Processing time: {elapsed_ms}ms")

    return {
        "summary_id": summary_id,
        "status": delivery["status"],
        "summary_markdown": summary_result["summary_markdown"],
        "validation_rate": validation["validation_rate"],
        "fk_grade": readability["fk_grade"] if readability else None,
        "delivered_channels": delivery["delivered_channels"],
        "final_key": delivery["final_key"],
        "processing_time_ms": elapsed_ms,
    }

# --- Example usage ---
if __name__ == "__main__":
    # All data below is SYNTHETIC. Do not use real patient data in development.
    # Any resemblance to real patients, providers, or payers is coincidental.

    sample_event = {
        "encounter_id": "ENC-SYNTH-00812",
        "patient_id": "PAT-SYNTH-00042",
        "provider_id": "PRV-00891",
        "signed_at": "2026-05-07T16:30:00Z",
        "visit_type": "outpatient",
    }

    # In production this comes from HealthLake / EHR FHIR queries. Structured
    # data plus the signed clinical note text, all scoped to this encounter.
    sample_clinical_data = {
        "encounter": {
            "id": "ENC-SYNTH-00812",
            "type": "Outpatient cardiology follow-up",
            "start": "2026-05-07T15:00:00Z",
            "end": "2026-05-07T16:00:00Z",
        },
        "medications": [
            {
                "id": "MED-NEW-001",
                "name": "warfarin",
                "dose": "5 mg",
                "frequency": "once daily in the evening",
                "change_type": "new",
                "reason": "stroke prevention in atrial fibrillation",
                "changed_today": True,
            }
        ],
        "orders": [
            {
                "id": "ORD-001",
                "name": "INR (prothrombin time)",
                "instructions": "Draw in 3 days at any in-network lab, then on a regular schedule",
                "when_expected": "Results within 2 business days",
            }
        ],
        "referrals": [],
        "appointments": [
            {
                "id": "APPT-NEXT",
                "practitioner": "Dr. Nguyen",
                "start": "2026-05-21T14:00:00Z",
                "status": "booked",
                "reason": "Follow-up on new anticoagulation",
            }
        ],
        "conditions": [
            {
                "code": "I48.91",
                "display": "Atrial fibrillation, unspecified",
                "is_new_today": True,
            }
        ],
        "note_text": (
            "Patient is a 68-year-old with new-onset atrial fibrillation "
            "diagnosed on today's ECG. Counseled at length on stroke risk "
            "and anticoagulation rationale. Started warfarin 5 mg once "
            "daily in the evening. Counseled to keep dietary vitamin K "
            "(leafy green vegetables) intake consistent from week to week. "
            "Discussed red-flag symptoms: the patient should call "
            "911 for sudden severe headache, one-sided weakness, trouble "
            "speaking, chest pain, or bleeding that will not stop. Call "
            "the office during business hours for easy bruising, nose "
            "bleeds, blood in urine or stool, or dizziness. Lifestyle "
            "counseling included avoiding contact sports and notifying "
            "all providers of anticoagulation before any procedure. "
            "Return for follow-up in 2 weeks (scheduled). INR ordered "
            "for day 3, then on a regular monitoring schedule."
        ),
    }

    result = generate_after_visit_summary(
        event=sample_event,
        encounter_clinical_data=sample_clinical_data,
    )

    print("\n" + "=" * 60)
    print("RESULT SUMMARY:")
    print("=" * 60)
    print(json.dumps(
        {
            "summary_id": result["summary_id"],
            "status": result["status"],
            "validation_rate": result["validation_rate"],
            "fk_grade": result["fk_grade"],
            "delivered_channels": result["delivered_channels"],
            "processing_time_ms": result["processing_time_ms"],
        },
        indent=2,
        default=str,
    ))
    print("\n" + "-" * 60)
    print("GENERATED SUMMARY:")
    print("-" * 60)
    print(result["summary_markdown"])
```

---

## The Gap Between This and Production

Run this end-to-end against a synthetic encounter and you'll see the full pattern: structured object extracted, patient-facing prose generated, claims validated, readability checked, summary archived. The distance between this and a real deployment is large. Here's where the gap lives.

**EHR integration is where most of the real work is.** This example takes `encounter_clinical_data` as a parameter. In reality, getting structured data out of Epic, Oracle Health, athenahealth, Meditech, or any other EHR in real time involves FHIR R4 APIs with vendor-specific quirks, inconsistent resource support, and authentication flows that differ per vendor. Triggering on note signature requires either a webhook integration, an HL7 v2 message feed, or a FHIR Subscription, each with its own reliability trade-offs. SMART on FHIR helps for embedded workflows. Budget 40-60% of your implementation timeline on EHR integration alone. A clean AI pipeline with no data in front of it is useless.

**Portal delivery is a second integration project.** Publishing the finalized AVS to the patient portal is distinct from the FHIR read side. Each EHR's portal API (MyChart, HealtheLife, athenaCommunicator) has its own document publishing model, metadata requirements, and sometimes certification process for third-party content. Expect two to four weeks per portal, more if the vendor requires formal integration review.

**Reading level for non-English languages is a separate project per language.** Flesch-Kincaid is English only. Spanish has INFLESZ and Fernández Huerta. Mandarin doesn't use grade levels in a directly comparable way. If you ship multilingual generation, you need per-language readability validators, each calibrated to norms in that language's patient communication literature. Many teams skip this and just trust the model. That mostly works and occasionally produces a Spanish summary written at a university register for a patient with a fourth-grade education, and the patient's trust in the communication erodes quietly.

**Multilingual QA has to be an ongoing program, not a one-time launch.** Generate a hundred summaries in Spanish, have a bilingual community health worker review them, feed the findings back into prompt engineering, repeat quarterly. For Cuban-American vs. Mexican-American vs. Puerto Rican patient populations, regional phrasing preferences differ. This is the work behind "multilingual support" and it's almost never budgeted for at project kickoff.

**Clinician review UI is make-or-break.** The pipeline outputs a summary and a provenance map. A clinician has to review, edit if needed, and approve in the case of high-risk visits or validation failures. If review happens in a separate web app, log-in and context-switch eats the time savings. The review has to be inside the EHR workflow, ideally via SMART on FHIR or an EHR-native extension. Surface the claims next to their source fields so the reviewer can audit quickly. Make sign-off meaningful but not tedious. This is at least as much engineering work as the AI pipeline.

**Step Functions orchestration.** The sequential function shown above is a learning artifact. A real pipeline uses Step Functions: parallel retrievals where independent (encounter data and patient preferences can fetch concurrently), per-step retries with different backoff policies, a pause-for-human-review state, and channel-specific delivery branches. Step Functions also gives you observability; ops staff can see which step a given summary is stuck in. Redrive failed executions without rebuilding state.

**Error handling and dead letter queues.** None of the code here handles partial failures, malformed JSON from the model, or transient Bedrock throttling beyond the adaptive retries. A production pipeline wraps each step in try/except, publishes failures to a DLQ (SQS), and alerts on queue depth. For JSON parsing specifically, build a repair loop: if parsing fails, send the raw output back to the model with "fix this JSON" instructions before giving up. Models are usually good at self-correction on structural errors.

**Validation beyond substring matching.** The validator here catches outright fabrications (claims referencing non-existent fields) and gross mismatches (asserting "10 mg" against a source "5 mg"). It will miss subtle paraphrase drift (claiming "high risk of stroke" when the note said "moderate risk"). For high-stakes visits, layer on a semantic similarity check: embed each factual claim and each source value, compute similarity, flag claims below a threshold for review. This adds latency and cost but catches a category of errors that exact-match misses. Amazon Bedrock Guardrails' contextual-grounding check is a related off-the-shelf option worth evaluating.

**Readability beyond Flesch-Kincaid.** Grade-level formulas are proxies. Patient comprehension is the actual goal. A sentence can score at grade 7 and still be incomprehensible to a specific patient because the concept is unfamiliar or the cultural framing is off. If you want to measure comprehension, build teach-back into the delivery: send an SMS the day after delivery asking the patient to summarize what they need to do, and review the responses for understanding gaps. It's extra work and the signal is noisy, but it beats assuming a grade-7 score means the patient understood.

**Minor patients and caregiver routing.** If the patient is a minor, the AVS goes to a caregiver, not the patient. If the patient is an adult with a designated healthcare proxy on file, the proxy may need the summary too. Multi-parent custody cases require routing decisions. State laws on adolescent confidentiality (sexual health, mental health, substance use) may require redacting specific sections when summaries go to parents. None of this is in the example code. Plan for a consent-and-routing layer that sits between generation and delivery.

**Feedback loops for corrections.** Patients call saying "my summary says X but I remember the doctor saying Y." Sometimes the summary is wrong (extraction missed something). Sometimes the patient's memory is wrong. You need a feedback channel, a review process, and a correction/reissuance workflow. Most teams under-invest in this because it's operations, not code. It's a mistake.

**Cost monitoring.** At ~$0.03-0.10 per summary and a mid-sized practice processing 1,000 visits per day, you're at $900-$3,000 per month in direct model costs. Monitor via CloudWatch billing alarms and per-summary cost tracking in DynamoDB. Watch for runaway regeneration loops (a bug where validation keeps failing can easily 10x your costs overnight). Set a hard cap on regeneration attempts per summary (the `MAX_GENERATION_ATTEMPTS` constant), which the example above enforces.

**PHI minimization in prompts.** The prompts here include names, DOBs, and full clinical data. Bedrock under BAA is HIPAA-eligible so this is compliant, but the minimum-necessary principle argues for sending less. Consider: redact patient names and MRNs before sending to the model, then substitute real values back when rendering the final summary. The model doesn't need the patient's actual name to compose the summary.

**VPC, encryption, and audit.** This example makes API calls without VPC configuration. A production Lambda runs in private subnets with VPC endpoints for S3, Bedrock Runtime, Comprehend Medical, DynamoDB, Step Functions, and CloudWatch Logs. S3 buckets use SSE-KMS with customer-managed keys (bucket defaults should enforce this). DynamoDB uses a CMK for encryption at rest. Every Bedrock invocation and every S3 object access gets logged to CloudTrail with data events enabled, because an audit will eventually ask "what did the model see for summary X on date Y?" and you need to answer that definitively.

**Testing with synthetic cases.** There are no tests in this example. A production pipeline has: unit tests for validation logic (the JSON path resolver and normalization matter), integration tests with synthetic encounters covering your top visit types, regression tests ensuring known-good encounters still produce expected summaries after prompt changes, and load tests validating throughput against realistic burst patterns (end-of-clinic waves when many notes get signed in a short window). Synthea generates synthetic FHIR data so the test corpus never contains real PHI.

**Model-ID lifecycle.** The model IDs in this example will be replaced over time as newer model versions launch. A production pipeline stores model IDs in configuration (SSM Parameter Store or AppConfig), not in code. When you update to a new model version, you rerun your regression suite before flipping the production config. Skipping this is how teams end up discovering at 2 AM that the new model version ignores a critical section of their prompt.

**DynamoDB Decimal gotcha.** DynamoDB doesn't accept Python floats. The example code above does not persist `validation_rate` to DynamoDB, but if you extend it to do so (for example, adding validation metrics to the summary record), wrap it with `Decimal(str(round(validation_rate, 4)))` to avoid the binary-precision pitfall of `Decimal(float_value)`. Always go through `str` first. This applies to any float you store: cost-per-summary, processing-time-seconds, readability scores.

**Observability and SLOs.** The target for AVS delivery is typically "before the patient leaves the parking lot," which means roughly 2-5 minutes from note signature to portal publication. Set CloudWatch SLOs for end-to-end latency at the 95th percentile, regeneration-rate SLO for prompt drift, validation-pass-rate SLO for generation quality, and delivery-success-rate SLO per channel. Alert when any of these drift. Without these, you'll discover problems from patient complaints instead of from dashboards.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 2.5: After-Visit Summary Generation](chapter02.05-after-visit-summary-generation) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
