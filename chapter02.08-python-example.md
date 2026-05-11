<!--
TechEditor pass (2026-05-10): minor edits for clarity and consistency.
  - Clarified the HealthScribe vs Transcribe Medical sentence in Setup.
  - Added a TODO flag for TechCodeReviewer on the HealthLake FHIR resource
    creation pattern in Step 8. The boto3 `healthlake` client does not
    expose a `create_resource` method (the datastore FHIR endpoint is an
    HTTPS API that requires SigV4-signed requests, typically via the
    `requests` library or an FHIR client), so the current snippet always
    raises AttributeError. The `except (ClientError, AttributeError)`
    block hides this but the code is misleading as written.
  - No structural or content rewrites. Voice, order, and technical claims
    preserved as drafted.

TechEditor pass (2026-05-10, iteration 2): additional mechanics pass.
  - Fixed bold-scope inconsistency on the "Equity" entry in the Gap
    section. Previously had two sentences in bold ("**Equity. The failure
    modes are worst for patients who are hardest to serve.**"), which
    broke the pattern used by every other entry in that section (single
    declarative sentence bolded, supporting prose unbolded). Replaced
    with a colon-joined single bold sentence to match the surrounding
    pattern.
  - No other changes. All TODO markers from the prior pass preserved.

TechEditor pass (2026-05-11, iteration 3): code-fence consistency pass.
  - Normalized the Step 5 (`render_institutional_note`) code block from
    four-backtick fences (````python ... ````) to three-backtick fences
    (```python ... ```) to match the other nine Python code blocks in
    the file. The defensive four-backtick wrapping was unnecessary: no
    line inside the block begins with three backticks at column 0
    (the string literals containing "```" in `_parse_json_response` are
    indented and do not terminate a fenced block).
  - No content changes. No structural rewrites. All TODO markers from
    prior passes preserved.
-->

# Recipe 2.8: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 2.8. It shows one way you could translate the ambient-clinical-documentation concepts into working Python using AWS HealthScribe, Amazon Bedrock, Amazon Comprehend Medical, AWS HealthLake, S3, DynamoDB, and Step Functions. It is not production-ready. There is no exam-room audio device integration, no real-time streaming via Kinesis Video Streams, no EHR-embedded clinician UI, no Step Functions orchestration wired up end-to-end (we call the steps sequentially for clarity), no real two-party-consent workflow, no jurisdiction-aware policy engine, and no case-review or quality-evaluation program. Think of it as a sketchpad: useful for understanding the shape of the pipeline, not something you'd deploy on Monday morning.
>
> The pipeline maps to the ten pseudocode steps from the main recipe: start the encounter and capture consent, finalize audio and launch HealthScribe, fetch HealthScribe output, extract transcript entities with Comprehend Medical, render the institutional-template note with Bedrock, validate the note against the transcript, present for clinician review and capture sign-off, write back to the EHR via HealthLake, apply retention policies, and emit quality metrics. Validation failures trigger regeneration up to a cap, then route to human review.
>
> All clinical content in examples below is synthetic. Do not use real patient audio, transcripts, or PHI during development. HealthScribe is HIPAA-eligible under the AWS BAA; Bedrock and Comprehend Medical likewise. Covered under the BAA does not mean "safe to experiment with real patients." Use synthetic mock encounters with actors under research consent until the full compliance, consent, and workflow posture is ready for a supervised pilot.

---

## Setup

You'll need the AWS SDK for Python:

```bash
pip install boto3
```

Your environment needs credentials configured (environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `transcribe:StartMedicalScribeJob`, `transcribe:GetMedicalScribeJob`, `transcribe:ListMedicalScribeJobs` (HealthScribe)
- `bedrock:InvokeModel` (for institutional-template rendering)
- `bedrock:ApplyGuardrail` (for contextual grounding against the transcript; configure a Guardrail in the Bedrock console before enabling)
- `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferRxNorm`, `comprehendmedical:InferICD10CM` (for entity extraction from the transcript)
- `s3:GetObject`, `s3:PutObject`, `s3:PutObjectRetention` (for audio, transcripts, draft and signed notes, with Object Lock for signed notes if compliance requires immutability)
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem` (session and audit state)
- `healthlake:CreateResource`, `healthlake:UpdateResource` (FHIR DocumentReference write-back, if using HealthLake)
- `secretsmanager:GetSecretValue` (EHR integration credentials, if using a vendor-specific integration)
- `kms:Decrypt`, `kms:GenerateDataKey` (customer-managed keys for all PHI at rest)
- `states:SendTaskSuccess`, `states:SendTaskFailure` (if wiring the human-review wait state through Step Functions)
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`, `cloudwatch:PutMetricData` (audit logs and quality metrics)

You also need HealthScribe enabled in your target region; verify regional availability before building. HealthScribe is distinct from Transcribe Medical; the boto3 client name is still `transcribe`, but the operations (`start_medical_scribe_job`, `get_medical_scribe_job`) are HealthScribe-specific. Bedrock model access for a capable generation model (such as Claude Sonnet) has to be requested in the Bedrock console for your account. A no-training option under the AWS BAA is the correct posture for clinical audio; verify the contractual terms before running anything that touches real encounter recordings.

A few things worth knowing upfront:

- **Clinical audio is always PHI.** Voice is biometric; de-identifying a transcript does not de-identify the audio. Treat audio with the same care you'd treat the medical record itself. Encrypt at rest, encrypt in transit, access-log every retrieval, and apply retention policies programmatically.
- **HealthScribe runs asynchronously.** You start a job, it processes the audio (roughly 10-30% of audio duration for typical ambulatory encounters), and you fetch outputs when it completes. A streaming mode exists; this example uses batch processing for clarity. Verify current regional support for streaming before planning a near-real-time rollout.
- **HealthScribe note templates are enumerated.** As of this writing, the supported `NoteTemplate` values include `HISTORY_AND_PHYSICAL`, `GIRPP`, `BIRP`, `SIRP`, `DAP`, `BEHAVIORAL_SOAP`, and `PHYSICAL_SOAP`. Institutional templates that differ from these are rendered in a post-processing step with Bedrock. Check the current SDK for the latest supported values before going to production.
- **Bedrock model IDs change.** The IDs in this example are reasonable defaults at the time of writing. Cross-region inference profile IDs (prefixed `us.` or `eu.`) are increasingly required; verify in the Bedrock console and adjust.
- **DynamoDB does not accept Python floats.** The example routes floats through `Decimal(str(value))`. Skip this and you get `TypeError: Float types are not supported` on your first production put.
- **The clinician is the signer.** The AI drafts; the clinician reviews, edits, and signs. Do not remove the signing step. Do not auto-route drafts to the EHR. Every line of the code below assumes a clinician sits between the draft and the chart.

---

## Configuration and Constants

Everything that's configuration rather than logic lives here. Model IDs, bucket and table names, note templates, retention windows, and validation thresholds are the knobs you'll change most often between environments.

```python
import base64
import datetime
import json
import logging
import re
import time
import uuid
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

# Structured logging. In production, ship JSON-formatted records to
# CloudWatch Logs Insights for query-friendly analysis. The transcript
# and draft note contain PHI; never log them in plain text. The audit
# trail for clinical content lives in S3 and DynamoDB under KMS encryption.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles Bedrock and HealthScribe throttling. Ambient
# documentation workload is naturally bursty (morning clinic sessions,
# afternoon rounds). Adaptive mode applies exponential backoff with jitter.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers.
transcribe = boto3.client("transcribe", config=BOTO3_RETRY_CONFIG)
bedrock_runtime = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
comprehend_medical = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
cloudwatch = boto3.client("cloudwatch", config=BOTO3_RETRY_CONFIG)
# HealthLake and Secrets Manager clients are conditionally created in the
# functions that use them so the example runs without those services
# configured.

# --- Model Configuration ---
# Bedrock model for institutional-template rendering. Template post-processing
# transforms HealthScribe's structured output into the institution's preferred
# format while preserving transcript traceability. Pick a capable model; this
# step produces the content the clinician actually reads.
#
# If your region requires cross-region inference, use the inference profile ID:
#   e.g., "us.anthropic.claude-3-5-sonnet-20241022-v2:0"
# TODO: verify the exact model IDs available in your region and account.
GENERATION_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"

# Optional Bedrock Guardrail for the generation step. Configure a Guardrail
# in the Bedrock console with the contextual grounding check enabled. The
# transcript acts as the grounding source. For clinical documentation, set
# a high grounding threshold (0.85+) to reject responses that drift from
# what was actually said. Leaving these None disables the Guardrail; do not
# ship without one configured.
GUARDRAIL_ID = None        # e.g., "abc123xyz"
GUARDRAIL_VERSION = None   # e.g., "DRAFT" or a numbered version string

# --- Storage Configuration ---
# Separate buckets by data class when you can: audio vs transcript vs note
# archive. Different retention policies and different KMS keys per class
# simplify deletion and auditing. For the example we use one bucket with
# key prefixes for clarity.
AUDIO_BUCKET = "your-ambient-doc-audio-bucket"
HEALTHSCRIBE_OUTPUT_BUCKET = "your-ambient-doc-healthscribe-output"
NOTES_BUCKET = "your-ambient-doc-notes-bucket"

# KMS customer-managed key ARN for HealthScribe output encryption. Audio
# and notes should use their own CMKs (separate blast radius per data class).
HEALTHSCRIBE_OUTPUT_CMK_ARN = "arn:aws:kms:us-east-1:123456789012:key/abcd1234-output"

# IAM role HealthScribe assumes to read audio input and write output to S3.
# The role needs read on the audio bucket, write on the output bucket, and
# use-of-key on both CMKs. Scope its trust policy to the transcribe service.
HEALTHSCRIBE_DATA_ACCESS_ROLE_ARN = (
    "arn:aws:iam::123456789012:role/HealthScribeDataAccess"
)

# DynamoDB table for session state and audit trail. Partition key: session_id.
SESSIONS_TABLE = "documentation-sessions"

# --- HealthScribe Settings ---
# Supported HealthScribe note templates at time of writing. Check the current
# boto3 model for the authoritative list; the enum expands over time.
HEALTHSCRIBE_NOTE_TEMPLATES = {
    "ambulatory_primary_care": "HISTORY_AND_PHYSICAL",
    "ambulatory_specialist": "HISTORY_AND_PHYSICAL",
    "behavioral_health_soap": "BEHAVIORAL_SOAP",
    "behavioral_health_dap": "DAP",
    "behavioral_health_girpp": "GIRPP",
    "behavioral_health_birp": "BIRP",
    "behavioral_health_sirp": "SIRP",
    "physical_therapy_soap": "PHYSICAL_SOAP",
}

# Expected speaker count. Ambulatory encounters are usually 2 (clinician +
# patient); encounters with an interpreter, family member, or trainee may
# have 3 or more. HealthScribe handles up to a configurable maximum.
DEFAULT_MAX_SPEAKER_LABELS = 2

# --- Pipeline Tuning ---
# Max retries for the generation + validation loop. If we can't produce a
# validated draft within this budget, route to human review rather than loop.
MAX_GENERATION_ATTEMPTS = 2

# Comprehend Medical DetectEntitiesV2 has a per-call byte limit (~20,000
# bytes for synchronous calls). Transcripts can exceed that; chunk if needed.
# This example truncates defensively; production should chunk and merge.
COMPREHEND_MEDICAL_MAX_BYTES = 19500

# Polling interval for HealthScribe job completion. HealthScribe jobs take
# roughly 10-30% of audio duration. A 15-minute encounter completes in
# a few minutes. Use EventBridge in production rather than polling.
HEALTHSCRIBE_POLL_SECONDS = 15
HEALTHSCRIBE_MAX_POLL_ATTEMPTS = 60  # 15 minutes max in this example

# --- Retention Policy Defaults ---
# Institution-specific. These are example values; your compliance and legal
# teams own the real numbers. Audio is typically shortest-retention;
# transcripts and notes retained per medical-record rules.
RETENTION_POLICY_DEFAULTS = {
    "audio_retention_days": 14,
    "transcript_retention_days": 2555,   # ~7 years
    "draft_retention_days": 30,
    "signed_note_retention_days": 2555,  # ~7 years; some jurisdictions longer
}

# --- Sensitive Encounter Exclusions ---
# Encounter types that many institutions exclude from ambient recording
# during initial rollout. Policy, not technology; enforced in the consent
# flow before any audio is captured.
SENSITIVE_ENCOUNTER_TYPES = {
    "behavioral_health_crisis",
    "sexual_assault_exam",
    "intimate_partner_violence_disclosure",
    "reproductive_rights_sensitive",
}
```

---

## Shared Helpers

A few utilities used across steps. Keeping them together so each step stays focused on the pattern it's teaching.

```python
def _now_iso() -> str:
    """UTC ISO timestamp for audit fields."""
    return datetime.datetime.now(timezone.utc).isoformat()


def _safe_utf8_truncate(text: str, max_bytes: int) -> str:
    """
    Truncate a string to max_bytes when encoded as utf-8.

    Slicing a string by character count can still blow past a byte limit
    for multi-byte characters. Encode, slice, decode with errors='ignore'
    is the safe pattern. Comprehend Medical's byte-limit errors are opaque
    otherwise.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _parse_json_response(raw_text: str) -> dict:
    """
    Parse JSON from a model response, stripping common markdown wrappers.

    Claude sometimes wraps JSON in markdown code fences even when told not
    to. Defensive parsing keeps the pipeline robust to that.
    """
    cleaned = raw_text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    try:
        return json.loads(cleaned.strip())
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSON response; returning empty dict")
        return {}


def _to_decimal_safe(value):
    """
    Convert a float to Decimal for DynamoDB. Going through str avoids the
    binary-precision issues that Decimal(float_value) introduces.

    DynamoDB raises TypeError on Python floats. This helper is the muscle
    memory that prevents that.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_decimal_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_decimal_safe(v) for v in value]
    return value


def _select_note_template(encounter_type: str, specialty: str) -> str:
    """
    Map institutional encounter type and specialty to a HealthScribe
    template enum. Falls back to HISTORY_AND_PHYSICAL for ambulatory.

    In production, the template-selection logic is typically data-driven:
    a DynamoDB table keyed by (specialty, encounter_type) with the template
    enum plus any Bedrock post-processing prompt version.
    """
    key = f"{encounter_type}_{specialty}".lower()
    # Priority: specialty-specific match, then encounter-type default
    if "behavioral_health" in key or specialty.lower() == "psychiatry":
        return HEALTHSCRIBE_NOTE_TEMPLATES["behavioral_health_soap"]
    if "physical_therapy" in key or specialty.lower() == "physical_therapy":
        return HEALTHSCRIBE_NOTE_TEMPLATES["physical_therapy_soap"]
    return HEALTHSCRIBE_NOTE_TEMPLATES["ambulatory_primary_care"]
```

---

## Step 1: Start the Encounter Session and Capture Consent

*The pseudocode calls this `start_encounter_session(request)`. Before any audio is captured, the clinician's app submits a session request with the patient identifier, encounter type, and the consent attestation. We persist the session immediately because the consent record is the first compliance artifact of the encounter; everything downstream ties back to this record. If consent wasn't given or the encounter type is excluded from ambient recording, the session is rejected and no audio is captured.*

```python
def start_encounter_session(request: dict) -> dict:
    """
    Create a new documentation session record, validate consent, and issue
    the audio-upload target (presigned S3 URL in this example).

    Args:
        request: Dict with:
            - patient_id:              EHR identifier for the patient
            - clinician_id:            Cognito or directory identity of clinician
            - encounter_id:            EHR encounter identifier, if known
            - encounter_type:          ambulatory | inpatient | specialty | etc.
            - specialty:               primary_care | cardiology | psychiatry | etc.
            - consent_given:           bool, clinician's attestation of patient consent
            - consent_method:          verbal | written | electronic
            - consent_form_version:    version tag of the consent form text
            - two_party_jurisdiction:  bool; if true, documented consent required
            - jurisdiction:            state or country code for policy lookup
            - audio_format:            "wav" | "flac" | "mp3" | ...

    Returns:
        Dict with session_id, status, and an audio-upload target (presigned URL).
    """
    # --- Policy gates: refuse to start the session if any rule is violated ---

    if not request.get("consent_given"):
        # The caller must attest that the patient has consented. This is the
        # most important gate in the pipeline. The attestation is captured
        # alongside the session; the compliance trail starts here.
        return {
            "status": "REJECTED",
            "reason": "Patient consent attestation is required before audio capture.",
        }

    if request.get("encounter_type") in SENSITIVE_ENCOUNTER_TYPES:
        # Sensitive encounter types are excluded from ambient recording
        # during rollout. Policy is enforced here, not downstream, because
        # "we'll filter it later" has been the root cause of real incidents.
        return {
            "status": "REJECTED",
            "reason": (
                "Encounter type is excluded from ambient documentation by "
                "institutional policy."
            ),
        }

    if request.get("two_party_jurisdiction") and request.get("consent_method") not in (
        "written",
        "electronic",
    ):
        # Two-party consent jurisdictions (California, Florida, Pennsylvania,
        # and several others in the US; most non-US jurisdictions) typically
        # require documented consent. Verbal-consent-captured-in-the-recording
        # is of questionable sufficiency depending on state interpretation.
        # Default to the stricter posture.
        return {
            "status": "REJECTED",
            "reason": (
                "Documented (written or electronic) consent is required in "
                "this jurisdiction."
            ),
        }

    session_id = str(uuid.uuid4())
    now_iso = _now_iso()

    # Write the session record. This is the first audit entry. The consent
    # fields, the jurisdiction, and the encounter type are all preserved
    # for later compliance review. Note the use of _to_decimal_safe for any
    # float fields (none in this example, but keep the habit).
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    sessions_table.put_item(
        Item=_to_decimal_safe(
            {
                "session_id": session_id,
                "status": "CONSENT_CAPTURED",
                "patient_id": request["patient_id"],
                "clinician_id": request["clinician_id"],
                "encounter_id": request.get("encounter_id", ""),
                "encounter_type": request.get("encounter_type", "ambulatory"),
                "specialty": request.get("specialty", "general"),
                "jurisdiction": request.get("jurisdiction", "UNSPECIFIED"),
                "consent": {
                    "given_at": now_iso,
                    "method": request.get("consent_method", "verbal"),
                    "form_version": request.get("consent_form_version", "unknown"),
                    "two_party_jurisdiction": bool(
                        request.get("two_party_jurisdiction")
                    ),
                },
                "created_at": now_iso,
            }
        )
    )

    # Issue a presigned S3 multipart upload target. Real implementations
    # may use Kinesis Video Streams WebRTC for streaming capture, or an
    # SDK on the exam-room device that streams chunks directly to S3.
    audio_format = request.get("audio_format", "wav")
    audio_s3_key = f"sessions/{session_id}/audio.{audio_format}"
    presigned_url = s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": AUDIO_BUCKET,
            "Key": audio_s3_key,
            # SSE-KMS: the audio bucket should also have a default bucket
            # policy enforcing this; belt and suspenders.
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": HEALTHSCRIBE_OUTPUT_CMK_ARN,  # reuse a CMK or make a separate audio CMK
        },
        ExpiresIn=3600,  # 1 hour; encounters rarely run longer than this
    )

    logger.info("Created session %s for clinician %s", session_id, request["clinician_id"])
    return {
        "status": "READY_FOR_AUDIO",
        "session_id": session_id,
        "audio_upload_url": presigned_url,
        "audio_s3_key": audio_s3_key,
    }
```

---

## Step 2: Finalize Audio and Start the HealthScribe Job

*The pseudocode calls this `finalize_audio_and_start_healthscribe(session_id, audio_s3_key)`. Once the clinician ends the encounter and the audio finishes uploading, the HealthScribe job is started. HealthScribe does ASR with medical vocabulary, speaker diarization with clinician-patient role assignment, clinical entity extraction, and an initial structured note draft. The outputs land back in S3 when the job completes. HealthScribe is asynchronous; the caller gets a job name and polls or waits on an EventBridge event.*

```python
def finalize_audio_and_start_healthscribe(session_id: str, audio_s3_key: str) -> dict:
    """
    Validate the session state, then submit a HealthScribe job for the
    uploaded audio.

    Args:
        session_id:   The encounter session UUID from Step 1.
        audio_s3_key: The S3 key where the audio was uploaded.

    Returns:
        Dict with the HealthScribe job name and job status.
    """
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    session_record = sessions_table.get_item(Key={"session_id": session_id}).get("Item")
    if not session_record:
        return {"status": "ERROR", "reason": "Session not found."}
    if session_record["status"] != "CONSENT_CAPTURED":
        return {
            "status": "ERROR",
            "reason": f"Unexpected session state: {session_record['status']}",
        }

    # HealthScribe job names must be unique per AWS account; using the
    # session id as the suffix keeps collisions from happening across
    # concurrent encounters.
    job_name = f"scribe-{session_id}"

    note_template_enum = _select_note_template(
        session_record.get("encounter_type", "ambulatory"),
        session_record.get("specialty", "general"),
    )

    # Kick off the HealthScribe job. The DataAccessRoleArn is the IAM role
    # HealthScribe assumes to read the audio bucket and write outputs. The
    # role's trust policy must allow transcribe.amazonaws.com.
    try:
        response = transcribe.start_medical_scribe_job(
            MedicalScribeJobName=job_name,
            Media={
                "MediaFileUri": f"s3://{AUDIO_BUCKET}/{audio_s3_key}",
            },
            OutputBucketName=HEALTHSCRIBE_OUTPUT_BUCKET,
            # Output is KMS-encrypted with a customer-managed key. For audio
            # and transcripts, separate CMKs per data class make retention
            # and deletion simpler.
            OutputEncryptionKMSKeyId=HEALTHSCRIBE_OUTPUT_CMK_ARN,
            DataAccessRoleArn=HEALTHSCRIBE_DATA_ACCESS_ROLE_ARN,
            Settings={
                # Speaker labeling is on: HealthScribe assigns roles
                # (CLINICIAN, PATIENT) based on content cues and voice
                # characteristics. For 3+ speakers (interpreter, trainee,
                # family member) raise MaxSpeakerLabels accordingly.
                "ShowSpeakerLabels": True,
                "MaxSpeakerLabels": DEFAULT_MAX_SPEAKER_LABELS,
                "ChannelIdentification": False,
                "ClinicalNoteGenerationSettings": {
                    # HealthScribe's supported template enum values include
                    # HISTORY_AND_PHYSICAL, GIRPP, BIRP, SIRP, DAP,
                    # BEHAVIORAL_SOAP, PHYSICAL_SOAP. Verify the current
                    # supported list in the boto3 docs.
                    "NoteTemplate": note_template_enum,
                },
            },
        )
    except ClientError as exc:
        logger.error("HealthScribe job start failed for %s: %s", session_id, exc)
        sessions_table.update_item(
            Key={"session_id": session_id},
            UpdateExpression="SET #s = :s, failure_reason = :r",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "HEALTHSCRIBE_START_FAILED",
                ":r": str(exc),
            },
        )
        return {"status": "FAILED", "reason": str(exc)}

    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression=(
            "SET #s = :s, audio_s3_key = :k, healthscribe_job_name = :j, "
            "healthscribe_started_at = :t, healthscribe_note_template = :n"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "HEALTHSCRIBE_RUNNING",
            ":k": audio_s3_key,
            ":j": job_name,
            ":t": _now_iso(),
            ":n": note_template_enum,
        },
    )

    logger.info("Started HealthScribe job %s (template=%s)", job_name, note_template_enum)
    return {
        "status": "HEALTHSCRIBE_STARTED",
        "job_name": job_name,
        "api_response_metadata": response.get("ResponseMetadata", {}),
    }
```

---

## Step 3: Poll for HealthScribe Completion and Fetch Outputs

*The pseudocode calls this `fetch_healthscribe_output(session_id, job_name)`. HealthScribe runs asynchronously. In production, an EventBridge rule on the job-status-change event is the right pattern. For the example, we poll. When the job completes, HealthScribe writes two artifacts to S3: the transcript with timestamped segments and speaker roles, and the structured clinical note draft with references back to transcript segments.*

```python
def fetch_healthscribe_output(session_id: str, job_name: str) -> dict:
    """
    Poll the HealthScribe job to completion (for the example). In
    production, replace this with an EventBridge-triggered handler.

    Returns the parsed transcript and structured clinical note on success,
    or an error on failure.
    """
    sessions_table = dynamodb.Table(SESSIONS_TABLE)

    for attempt in range(HEALTHSCRIBE_MAX_POLL_ATTEMPTS):
        try:
            response = transcribe.get_medical_scribe_job(
                MedicalScribeJobName=job_name,
            )
        except ClientError as exc:
            logger.error("GetMedicalScribeJob failed: %s", exc)
            return {"status": "ERROR", "reason": str(exc)}

        job = response.get("MedicalScribeJob", {})
        job_status = job.get("MedicalScribeJobStatus")

        if job_status == "IN_PROGRESS" or job_status == "QUEUED":
            time.sleep(HEALTHSCRIBE_POLL_SECONDS)
            continue

        if job_status == "FAILED":
            failure_reason = job.get("FailureReason", "unknown")
            sessions_table.update_item(
                Key={"session_id": session_id},
                UpdateExpression="SET #s = :s, failure_reason = :r",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":s": "HEALTHSCRIBE_FAILED",
                    ":r": failure_reason,
                },
            )
            logger.error("HealthScribe job %s failed: %s", job_name, failure_reason)
            return {"status": "FAILED", "reason": failure_reason}

        if job_status == "COMPLETED":
            # HealthScribe writes outputs to the configured output bucket.
            # The job response carries the S3 URIs for the transcript and
            # the structured clinical document.
            output = job.get("MedicalScribeOutput", {})
            transcript_uri = output.get("TranscriptFileUri")
            clinical_document_uri = output.get("ClinicalDocumentUri")

            transcript_json = _read_s3_json_by_uri(transcript_uri)
            clinical_document_json = _read_s3_json_by_uri(clinical_document_uri)

            sessions_table.update_item(
                Key={"session_id": session_id},
                UpdateExpression=(
                    "SET #s = :s, transcript_s3_uri = :t, "
                    "healthscribe_note_s3_uri = :n, healthscribe_completed_at = :c"
                ),
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":s": "HEALTHSCRIBE_COMPLETE",
                    ":t": transcript_uri,
                    ":n": clinical_document_uri,
                    ":c": _now_iso(),
                },
            )

            logger.info(
                "HealthScribe job %s complete; transcript at %s",
                job_name,
                transcript_uri,
            )
            return {
                "status": "COMPLETE",
                "transcript": transcript_json,
                "clinical_document": clinical_document_json,
                "transcript_uri": transcript_uri,
                "clinical_document_uri": clinical_document_uri,
            }

        # Unknown status; bail out with the raw status for the caller to log.
        return {"status": "UNKNOWN", "raw_status": job_status}

    # Polling timeout. In production, this is where you'd escalate or
    # surface an operational alert; HealthScribe jobs don't usually take
    # longer than a few minutes for ambulatory audio.
    return {"status": "POLL_TIMEOUT"}


def _read_s3_json_by_uri(s3_uri: str) -> dict:
    """
    Read a JSON object from an s3:// URI. HealthScribe outputs are JSON.

    Production variants should validate content-type, cap object size,
    and fail closed on malformed JSON rather than returning an empty dict.
    """
    if not s3_uri or not s3_uri.startswith("s3://"):
        return {}
    path = s3_uri[5:]
    bucket, _, key = path.partition("/")
    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return json.loads(response["Body"].read())
    except Exception as exc:
        logger.error("Failed to read %s: %s", s3_uri, exc)
        return {}
```

---

## Step 4: Extract Transcript Entities (Must-Include Checklist)

*The pseudocode calls this `extract_transcript_entities(transcript_json)`. Before rendering the institutional-template note, we extract the clinical entities from the transcript with Comprehend Medical. These entities become the "must-include" checklist: if the patient mentioned a medication, symptom, or condition in the conversation, the note should reflect it. Skipping this check is how content gets silently dropped from notes, which is the failure mode clinicians most resent.*

```python
def extract_transcript_entities(transcript_json: dict) -> dict:
    """
    Pull medications, conditions, symptoms, procedures, and numeric values
    from the transcript. Produces a must-include checklist for validation.

    The transcript structure from HealthScribe includes:
      TranscriptSegments: list of { Id, ParticipantRole, Content, Confidence,
                                    BeginAudioTime, EndAudioTime, ... }

    Args:
        transcript_json: The parsed transcript JSON from HealthScribe.

    Returns:
        Dict with entity lists and rxnorm/icd10 mappings.
    """
    segments = transcript_json.get("TranscriptSegments", []) or []

    # Concatenate patient and clinician text separately. Patient statements
    # tend to contain symptoms and self-reported medications; clinician
    # statements contain assessments, plans, and exam narration.
    patient_text_parts = []
    clinician_text_parts = []
    for seg in segments:
        role = (seg.get("ParticipantRole") or "").upper()
        content = seg.get("Content") or ""
        if role == "PATIENT":
            patient_text_parts.append(content)
        elif role == "CLINICIAN":
            clinician_text_parts.append(content)

    combined_text = " ".join(patient_text_parts + clinician_text_parts)
    # Comprehend Medical has a byte limit per call. For transcripts longer
    # than the limit, production systems chunk and merge. This example
    # truncates; flag the truncation in the audit record.
    truncated_text = _safe_utf8_truncate(combined_text, COMPREHEND_MEDICAL_MAX_BYTES)
    truncated = len(truncated_text) < len(combined_text)

    medications = []
    conditions = []
    symptoms = []
    procedures = []
    anatomy = []
    numeric_findings = []

    try:
        entities_response = comprehend_medical.detect_entities_v2(Text=truncated_text)
        for entity in entities_response.get("Entities", []):
            traits = [t.get("Name") for t in entity.get("Traits") or []]
            base = {
                "text": entity.get("Text"),
                "type": entity.get("Type"),
                "score": entity.get("Score"),
                "traits": traits,
                "begin_offset": entity.get("BeginOffset"),
                "end_offset": entity.get("EndOffset"),
            }
            category = entity.get("Category")
            if category == "MEDICATION":
                medications.append(base)
            elif category == "MEDICAL_CONDITION":
                # Respect negation: if the clinician said "no fever," the
                # condition is explicitly ruled out. That's a legitimate
                # pertinent-negative in the note, not a missing positive.
                if "NEGATION" in traits:
                    base["pertinent_negative"] = True
                    conditions.append(base)
                else:
                    conditions.append(base)
            elif category == "TEST_TREATMENT_PROCEDURE":
                procedures.append(base)
            elif category == "ANATOMY":
                anatomy.append(base)

            # Numeric attributes on entities (dose, frequency, duration,
            # test values) are surfaced via entity.Attributes.
            for attr in entity.get("Attributes") or []:
                if attr.get("Type") in (
                    "DOSAGE",
                    "STRENGTH",
                    "DURATION",
                    "FREQUENCY",
                    "TEST_VALUE",
                    "TEST_UNIT",
                ):
                    numeric_findings.append(
                        {
                            "text": attr.get("Text"),
                            "type": attr.get("Type"),
                            "score": attr.get("Score"),
                            "parent_entity": entity.get("Text"),
                        }
                    )
    except ClientError as exc:
        logger.warning("DetectEntitiesV2 failed: %s", exc)

    # Extract patient symptom language from patient-attributed content. The
    # DetectEntitiesV2 above catches coded entities; this pass catches lay
    # descriptions that might matter for the HPI.
    symptoms.extend(_extract_symptom_phrases(patient_text_parts))

    rxnorm_codes = []
    icd10_codes = []
    try:
        rx_response = comprehend_medical.infer_rx_norm(Text=truncated_text)
        for entity in rx_response.get("Entities") or []:
            for concept in entity.get("RxNormConcepts") or []:
                rxnorm_codes.append(
                    {
                        "text": entity.get("Text"),
                        "code": concept.get("Code"),
                        "description": concept.get("Description"),
                        "score": concept.get("Score"),
                    }
                )
    except ClientError as exc:
        logger.warning("InferRxNorm failed: %s", exc)

    try:
        icd_response = comprehend_medical.infer_icd10_cm(Text=truncated_text)
        for entity in icd_response.get("Entities") or []:
            for concept in entity.get("ICD10CMConcepts") or []:
                icd10_codes.append(
                    {
                        "text": entity.get("Text"),
                        "code": concept.get("Code"),
                        "description": concept.get("Description"),
                        "score": concept.get("Score"),
                    }
                )
    except ClientError as exc:
        logger.warning("InferICD10CM failed: %s", exc)

    logger.info(
        "Extracted %d meds, %d conditions, %d procedures, %d numeric findings",
        len(medications),
        len(conditions),
        len(procedures),
        len(numeric_findings),
    )
    return {
        "medications": medications,
        "conditions": conditions,
        "symptoms": symptoms,
        "procedures": procedures,
        "anatomy": anatomy,
        "numeric_findings": numeric_findings,
        "rxnorm_codes": rxnorm_codes,
        "icd10_codes": icd10_codes,
        "transcript_truncated_for_entity_extraction": truncated,
    }


def _extract_symptom_phrases(patient_text_parts: list) -> list:
    """
    Very simple phrase extractor over patient-attributed content to catch
    lay symptom descriptions ("chest tightness," "weird feeling," "pee a lot").

    Production systems typically use a clinical NER fine-tune; this
    placeholder avoids adding a dependency while preserving the pattern.
    """
    return [
        {"text": phrase.strip(), "source": "patient_utterance"}
        for phrase in " ".join(patient_text_parts).split(".")
        if phrase.strip() and len(phrase.strip()) > 5
    ][:20]  # cap so the must-include list doesn't blow up on chatty encounters
```

---

## Step 5: Render the Institutional-Template Note with Bedrock

*The pseudocode calls this `render_institutional_note(...)`. HealthScribe produces a structured note in one of its supported templates (History and Physical, SOAP, DAP, etc.). Institutions almost always want a specific format with their own language conventions, section ordering, and required fields. Bedrock is the post-processor: it takes the HealthScribe structured output plus the raw transcript plus the must-include checklist plus EHR context (meds, allergies, problem list) and produces the final institutional note with transcript-segment traceability.*

```python
def render_institutional_note(
    session_record: dict,
    transcript_json: dict,
    healthscribe_note: dict,
    must_include: dict,
    ehr_context: dict,
    regeneration_hint: str = "",
) -> dict:
    """
    Run the institutional-template rendering pass with Bedrock.

    The generation prompt is strict: the note may only contain content
    supported by the transcript or labeled EHR sources. Every claim
    carries a citation (transcript segment ID or EHR source tag). The
    prompt also enforces preservation of numeric values, negation language,
    and uncertainty language, and explicitly forbids fabricated exam
    findings when the clinician did not narrate the exam.
    """
    segments = transcript_json.get("TranscriptSegments", []) or []
    if not segments:
        return {
            "status": "NO_TRANSCRIPT",
            "sections": {},
            "claims": [],
        }

    # Build the transcript block for the prompt with stable segment IDs and
    # per-segment confidence. The segment IDs flow through into the
    # rendered note's citations, which enables the clinician's traceability
    # UI to link a sentence back to the audio/transcript.
    transcript_lines = []
    for seg in segments:
        seg_id = seg.get("Id", "")
        role = seg.get("ParticipantRole", "UNKNOWN")
        confidence = seg.get("Confidence", "n/a")
        content = (seg.get("Content") or "").replace("\n", " ").strip()
        transcript_lines.append(
            f"[seg_{seg_id}] ({role}, conf={confidence}): {content}"
        )
    transcript_block = "\n".join(transcript_lines)

    # EHR context is structured, not free-text. The prompt treats it as a
    # separate source with its own citation prefix (ehr:meds, ehr:allergies,
    # etc.) so the clinician can tell what came from the chart vs what came
    # from the conversation.
    ehr_block_lines = []
    for key, value in (ehr_context or {}).items():
        ehr_block_lines.append(f"[ehr:{key}] {json.dumps(value)}")
    ehr_block = "\n".join(ehr_block_lines)

    # Compact the must-include checklist for the prompt. Redundancy is fine
    # here; the generator does better with explicit instructions than with
    # implicit ones.
    must_include_summary = {
        "medications": [m.get("text") for m in must_include.get("medications") or []],
        "conditions": [c.get("text") for c in must_include.get("conditions") or []],
        "procedures": [p.get("text") for p in must_include.get("procedures") or []],
        "numeric_findings": [
            f"{n.get('parent_entity', '')}: {n.get('text', '')} ({n.get('type', '')})"
            for n in must_include.get("numeric_findings") or []
        ],
    }

    system_prompt = """You transform a raw encounter transcript and a draft structured clinical note into an institutional-format note.

HARD REQUIREMENTS:
1. Every factual claim must trace to a transcript segment ([seg_ID]) or to an EHR source ([ehr:key]).
2. Do NOT include content that is not supported by a transcript segment or an EHR source.
3. Preserve verbatim numerical values from the transcript (doses, durations, vital signs, lab values). Do NOT paraphrase numbers.
4. Preserve negations and uncertainty language as stated. "Denies shortness of breath" stays as "denies," not "does not have."
5. If the clinician did not narrate a physical exam element in the transcript, do NOT fabricate findings. Use the placeholder "Physical exam not documented in recording. Please complete." for sections without transcript support.
6. Exclude small talk and non-clinical content. The note is clinical documentation, not a recording of the visit.
7. Assessment language comes only from the clinician's spoken assessment. Do not generate clinical impressions the clinician did not express.
8. Include every medication, condition, procedure, and numeric finding from the MUST_INCLUDE checklist in the appropriate section of the note.

OUTPUT FORMAT: Return ONLY a valid JSON object (no markdown code fences) with this structure:
{
  "sections": {
    "chief_complaint": "...",
    "hpi": "...",
    "review_of_systems": "...",
    "medications": "...",
    "allergies": "...",
    "physical_exam": "...",
    "assessment": "...",
    "plan": "..."
  },
  "claims": [
    {
      "claim_text": "verbatim quote of the claim from the note",
      "section": "hpi | assessment | plan | ...",
      "citations": ["seg_3", "ehr:medications", ...],
      "preserves_numerics": true | false,
      "numeric_values_in_claim": ["148/88", "81 mg", ...]
    }
  ]
}"""

    user_prompt = f"""ENCOUNTER CONTEXT:
Session ID: {session_record.get('session_id')}
Encounter type: {session_record.get('encounter_type')}
Specialty: {session_record.get('specialty')}

HEALTHSCRIBE DRAFT (reference, do NOT copy verbatim):
{json.dumps(healthscribe_note, indent=2)[:4000]}

MUST_INCLUDE CHECKLIST (these appeared in the transcript and must be in the note):
{json.dumps(must_include_summary, indent=2)}

EHR CONTEXT (structured; cite as [ehr:key] in claims):
{ehr_block}

TRANSCRIPT (cite segments as [seg_ID] in claims):
{transcript_block}

{('REGENERATION HINT: ' + regeneration_hint) if regeneration_hint else ''}

Produce the institutional-format note now. Output ONLY the JSON object, no prose before or after."""

    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 6000,
        # Low temperature for documentation: we want faithful, predictable
        # rendering, not creative variation.
        "temperature": 0.1,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_prompt}],
    }

    invoke_kwargs = {
        "modelId": GENERATION_MODEL_ID,
        "contentType": "application/json",
        "accept": "application/json",
        "body": json.dumps(request_body),
    }

    # Apply the Bedrock Guardrail if configured. The contextual grounding
    # check uses the transcript as the grounding source. Guardrail
    # intervention is signaled via the `amazon-bedrock-guardrailAction`
    # field on the response, not via stop_reason. Verify your Guardrail
    # setup's response shape and branch accordingly.
    if GUARDRAIL_ID and GUARDRAIL_VERSION:
        invoke_kwargs["guardrailIdentifier"] = GUARDRAIL_ID
        invoke_kwargs["guardrailVersion"] = GUARDRAIL_VERSION

    try:
        response = bedrock_runtime.invoke_model(**invoke_kwargs)
        response_body = json.loads(response["body"].read())
    except ClientError as exc:
        logger.error("Bedrock generation failed: %s", exc)
        return {
            "status": "GENERATION_FAILED",
            "sections": {},
            "claims": [],
            "error": str(exc),
        }

    # Guardrail intervention check. Some Guardrail configurations return
    # the flag on the response body, others on a top-level field. Check
    # both shapes defensively.
    guardrail_action = (
        response_body.get("amazon-bedrock-guardrailAction")
        or response_body.get("stop_reason")
    )
    if guardrail_action == "INTERVENED" or guardrail_action == "guardrail_intervened":
        logger.warning("Guardrail intervened on note rendering")
        return {"status": "GROUNDING_REJECTED", "sections": {}, "claims": []}

    # Parse the model output. The system prompt tells the model to return
    # pure JSON; the defensive parser handles occasional markdown fencing.
    raw_text = response_body["content"][0]["text"]
    parsed = _parse_json_response(raw_text)
    if not parsed:
        return {
            "status": "PARSE_FAILED",
            "sections": {},
            "claims": [],
            "raw_text_snippet": raw_text[:500],
        }

    logger.info(
        "Rendered institutional note: %d sections, %d tracked claims",
        len(parsed.get("sections", {})),
        len(parsed.get("claims", [])),
    )
    return {
        "status": "RENDERED",
        "sections": parsed.get("sections", {}),
        "claims": parsed.get("claims", []),
    }
```

---

## Step 6: Validate the Note Against the Transcript

*The pseudocode calls this `validate_note(...)`. After generation, run a validator. For each claim in the note, confirm it cites a real transcript segment or an EHR source. For claims flagged as preserving numerics, confirm the numeric values appear verbatim in the cited segments. For each entry in the must-include checklist, confirm it appears in the note. Required sections (chief complaint, assessment, plan) must be non-empty. Failures route to regeneration or to human review.*

```python
def validate_note(
    note_sections: dict,
    claims: list,
    transcript_json: dict,
    must_include: dict,
    ehr_context: dict,
    retry_count: int = 0,
) -> dict:
    """
    Verify the generated note against the transcript and must-include checklist.

    Returns:
        Dict with status (VALIDATED | RETRY_NEEDED | REVIEW_REQUIRED),
        issue details, and a suggested regeneration hint if retrying.
    """
    segments = transcript_json.get("TranscriptSegments", []) or []
    segment_map = {f"seg_{s.get('Id')}": s for s in segments}
    ehr_citation_keys = {f"ehr:{k}" for k in (ehr_context or {}).keys()}

    unverified = []

    # --- 1. Every claim must cite a real transcript segment or EHR source ---
    for claim in claims or []:
        claim_text = claim.get("claim_text", "")
        citations = claim.get("citations", []) or []

        valid_citations = 0
        for cit in citations:
            if cit in segment_map or cit in ehr_citation_keys:
                valid_citations += 1
            else:
                unverified.append(
                    {
                        "claim": claim_text,
                        "issue": "citation_not_in_source",
                        "bad_citation": cit,
                        "severity": "HIGH",
                    }
                )

        if valid_citations == 0:
            unverified.append(
                {
                    "claim": claim_text,
                    "issue": "no_valid_citation",
                    "severity": "HIGH",
                }
            )
            continue

        # --- 2. Numeric verification for claims that assert preservation ---
        if claim.get("preserves_numerics"):
            supporting_text = " ".join(
                segment_map[cit].get("Content", "")
                for cit in citations
                if cit in segment_map
            )
            for numeric in claim.get("numeric_values_in_claim", []) or []:
                # Verbatim check first, then a whitespace-normalized check
                # so "148/88" matches "148 / 88".
                if numeric not in supporting_text:
                    if re.sub(r"\s+", "", numeric) not in re.sub(
                        r"\s+", "", supporting_text
                    ):
                        unverified.append(
                            {
                                "claim": claim_text,
                                "issue": "numeric_not_in_source",
                                "missing_numeric": numeric,
                                "severity": "HIGH",
                            }
                        )

    # --- 3. Must-include checklist ---
    note_text_combined = " ".join(str(v) for v in note_sections.values())
    missing_must_include = []
    for med in must_include.get("medications") or []:
        name = (med.get("text") or "").lower()
        if name and name not in note_text_combined.lower():
            missing_must_include.append(
                {"type": "medication", "item": med.get("text"), "severity": "HIGH"}
            )
    for cond in must_include.get("conditions") or []:
        # Skip pertinent negatives; they may or may not appear explicitly
        # in the note text depending on section (ROS handles them).
        if cond.get("pertinent_negative"):
            continue
        name = (cond.get("text") or "").lower()
        if name and name not in note_text_combined.lower():
            missing_must_include.append(
                {"type": "condition", "item": cond.get("text"), "severity": "MEDIUM"}
            )
    for proc in must_include.get("procedures") or []:
        name = (proc.get("text") or "").lower()
        if name and name not in note_text_combined.lower():
            missing_must_include.append(
                {"type": "procedure", "item": proc.get("text"), "severity": "MEDIUM"}
            )

    # --- 4. Required sections non-empty ---
    required_empty = []
    for section in ("chief_complaint", "assessment", "plan"):
        content = note_sections.get(section, "")
        if not content or len(content.strip()) < 10:
            required_empty.append({"section": section, "severity": "HIGH"})

    # --- Decide the outcome ---
    high_issues = [u for u in unverified if u["severity"] == "HIGH"]
    high_missing = [m for m in missing_must_include if m["severity"] == "HIGH"]
    high_count = len(high_issues) + len(high_missing) + len(required_empty)

    if high_count == 0 and len(missing_must_include) <= max(1, len(claims) // 5):
        return {
            "status": "VALIDATED",
            "unverified": unverified,
            "missing_must_include": missing_must_include,
            "required_empty": required_empty,
        }

    if retry_count < MAX_GENERATION_ATTEMPTS - 1:
        hint = _build_validation_hint(
            unverified, missing_must_include, required_empty,
        )
        return {
            "status": "RETRY_NEEDED",
            "unverified": unverified,
            "missing_must_include": missing_must_include,
            "required_empty": required_empty,
            "suggested_prompt_augmentation": hint,
        }

    return {
        "status": "REVIEW_REQUIRED",
        "unverified": unverified,
        "missing_must_include": missing_must_include,
        "required_empty": required_empty,
    }


def _build_validation_hint(
    unverified: list, missing_must_include: list, required_empty: list,
) -> str:
    """Summarize validation failures into a concise instruction for the next attempt."""
    lines = ["The previous draft had issues. Fix these specifically:"]
    issue_keys = set()
    for u in unverified:
        key = u.get("issue")
        if key in issue_keys:
            continue
        issue_keys.add(key)
        if key == "no_valid_citation":
            lines.append(
                "- Some claims had no valid citation. Every claim must "
                "cite at least one transcript segment [seg_ID] or EHR "
                "source [ehr:key]."
            )
        elif key == "citation_not_in_source":
            lines.append(
                "- You cited segment IDs or EHR keys that do not exist. "
                "Only cite segment IDs present in the TRANSCRIPT block "
                "and EHR keys present in the EHR CONTEXT block."
            )
        elif key == "numeric_not_in_source":
            lines.append(
                "- Numeric values (doses, vital signs, lab values) did not "
                "match the source verbatim. Quote numbers exactly as they "
                "appear in the cited segments."
            )
    if missing_must_include:
        sample = ", ".join(
            str(m.get("item")) for m in missing_must_include[:5]
        )
        lines.append(
            f"- The following items from the MUST_INCLUDE checklist are "
            f"missing from the note and must be added: {sample}."
        )
    if required_empty:
        sample = ", ".join(e.get("section") for e in required_empty)
        lines.append(
            f"- The following required sections are empty or too short: "
            f"{sample}. Produce non-empty content for each (or, for "
            f"physical exam, use the 'not documented in recording' "
            f"placeholder if the clinician did not narrate it)."
        )
    return "\n".join(lines)
```

---

## Step 7: Present Draft for Clinician Review and Capture Sign-Off

*The pseudocode splits this into `present_for_review(...)` and `capture_clinician_signoff(...)`. The draft is persisted and the clinician's UI is notified that a note is ready. The clinician reviews, edits, and signs. The signed note is the clinician's legal documentation of record; the AI-drafted version is retained as an audit artifact. The edit distance between draft and signed note is tracked as a quality metric over time.*

```python
def present_for_review(
    session_id: str,
    note_sections: dict,
    claims: list,
    validation_result: dict,
) -> dict:
    """
    Persist the draft note and mark the session as awaiting clinician review.
    In production, this is where the Step Functions workflow would pause
    at a wait-for-task-token state until the clinician signs.
    """
    sessions_table = dynamodb.Table(SESSIONS_TABLE)

    draft_payload = {
        "sections": note_sections,
        "claims": claims,
        "validation": validation_result,
        "rendered_at": _now_iso(),
    }
    draft_key = f"sessions/{session_id}/draft_note.json"

    s3_client.put_object(
        Bucket=NOTES_BUCKET,
        Key=draft_key,
        Body=json.dumps(draft_payload, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=HEALTHSCRIBE_OUTPUT_CMK_ARN,  # or a separate notes CMK
    )

    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression=(
            "SET #s = :s, draft_note_s3_key = :k, draft_rendered_at = :t, "
            "validation_status = :v"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "AWAITING_CLINICIAN_REVIEW",
            ":k": draft_key,
            ":t": _now_iso(),
            ":v": validation_result.get("status", "UNKNOWN"),
        },
    )

    logger.info("Draft ready for session %s; awaiting clinician review", session_id)
    return {
        "status": "AWAITING_CLINICIAN_REVIEW",
        "draft_note_s3_key": draft_key,
    }


def capture_clinician_signoff(
    session_id: str,
    edited_sections: dict,
    clinician_attestation: str,
) -> dict:
    """
    Persist the signed note and compute the edit-distance quality metric.

    Args:
        session_id:             The session being signed.
        edited_sections:        The clinician's edited version of the note sections.
        clinician_attestation:  The attestation text from the sign-off UI
                                 ("I have reviewed this note and it reflects
                                  my encounter with the patient").

    Returns:
        Dict with the signed note key and edit distance.
    """
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    session = sessions_table.get_item(Key={"session_id": session_id}).get("Item")
    if not session or session.get("status") != "AWAITING_CLINICIAN_REVIEW":
        return {"status": "ERROR", "reason": "Session not awaiting review."}

    # Load the draft for edit-distance comparison.
    draft_obj = s3_client.get_object(
        Bucket=NOTES_BUCKET, Key=session["draft_note_s3_key"],
    )
    draft = json.loads(draft_obj["Body"].read())
    draft_sections = draft.get("sections", {})

    edit_distance = _normalized_edit_distance(draft_sections, edited_sections)

    # Persist the signed note. In compliance-sensitive deployments, apply
    # S3 Object Lock to make the signed note immutable for the required
    # retention period. Object Lock requires a bucket-level configuration
    # set at bucket creation time.
    signed_key = f"sessions/{session_id}/signed_note.json"
    signed_payload = {
        "sections": edited_sections,
        "signed_by": session.get("clinician_id"),
        "attestation": clinician_attestation,
        "signed_at": _now_iso(),
        "draft_key": session["draft_note_s3_key"],
        "patient_id": session.get("patient_id"),
        "encounter_id": session.get("encounter_id"),
    }

    s3_client.put_object(
        Bucket=NOTES_BUCKET,
        Key=signed_key,
        Body=json.dumps(signed_payload, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=HEALTHSCRIBE_OUTPUT_CMK_ARN,
    )

    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression=(
            "SET #s = :s, signed_note_s3_key = :k, signed_at = :t, "
            "edit_distance_metric = :e"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "SIGNED",
            ":k": signed_key,
            ":t": _now_iso(),
            ":e": _to_decimal_safe(edit_distance),
        },
    )

    logger.info(
        "Session %s signed by clinician %s (edit_distance=%.3f)",
        session_id, session.get("clinician_id"), edit_distance,
    )
    return {
        "status": "SIGNED",
        "signed_note_s3_key": signed_key,
        "edit_distance": edit_distance,
    }


def _normalized_edit_distance(draft_sections: dict, signed_sections: dict) -> float:
    """
    Compute a simple normalized Levenshtein-like edit-distance estimate
    between the draft and signed note text.

    Production systems use a proper Levenshtein library (python-Levenshtein
    or rapidfuzz). This placeholder uses a token-set overlap as a proxy
    so the example runs without extra dependencies. Swap in a real edit
    distance before shipping; the metric is the canary in the coal mine
    for pipeline quality regressions.
    """
    draft_text = " ".join(str(v) for v in draft_sections.values()).lower()
    signed_text = " ".join(str(v) for v in signed_sections.values()).lower()
    if not draft_text or not signed_text:
        return 1.0
    draft_tokens = set(draft_text.split())
    signed_tokens = set(signed_text.split())
    if not draft_tokens:
        return 1.0
    changed = draft_tokens.symmetric_difference(signed_tokens)
    return len(changed) / (len(draft_tokens) + len(signed_tokens))
```

---

## Step 8: Write the Signed Note Back to the EHR

*The pseudocode calls this `write_to_ehr(session_id, signed_note)`. The signed note becomes a FHIR DocumentReference in HealthLake (if that's the integration) or is submitted via the EHR vendor's native API. Errors here are critical: a signed note that never reaches the chart is a hard failure that needs operational alerting and clinician notification.*

```python
def write_to_ehr(session_id: str) -> dict:
    """
    Write the signed note to HealthLake as a FHIR DocumentReference.

    For EHR vendors that require native API integration (Epic, Oracle Health),
    replace the HealthLake call with the vendor-specific submission. Credentials
    should come from Secrets Manager with rotation enabled where supported.
    """
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    session = sessions_table.get_item(Key={"session_id": session_id}).get("Item")
    if not session or session.get("status") != "SIGNED":
        return {"status": "ERROR", "reason": "Session not in SIGNED state."}

    signed_obj = s3_client.get_object(
        Bucket=NOTES_BUCKET, Key=session["signed_note_s3_key"],
    )
    signed = json.loads(signed_obj["Body"].read())

    # Build the FHIR DocumentReference. LOINC code selection depends on the
    # note type. 34117-2 is "History and physical note"; use the appropriate
    # code for your encounter type. Institutional coding conventions vary.
    loinc_code = _loinc_code_for_encounter(session.get("encounter_type", "ambulatory"))
    note_text = _render_note_as_markdown(signed.get("sections", {}))

    document_reference = {
        "resourceType": "DocumentReference",
        "status": "current",
        "type": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": loinc_code["code"],
                    "display": loinc_code["display"],
                }
            ]
        },
        "subject": {"reference": f"Patient/{session.get('patient_id')}"},
        "date": signed.get("signed_at"),
        "author": [
            {"reference": f"Practitioner/{session.get('clinician_id')}"}
        ],
        "content": [
            {
                "attachment": {
                    "contentType": "text/markdown",
                    "data": base64.b64encode(note_text.encode("utf-8")).decode("ascii"),
                    "title": f"{loinc_code['display']} {session.get('encounter_id', '')}",
                }
            }
        ],
        "context": {
            "encounter": [
                {"reference": f"Encounter/{session.get('encounter_id', '')}"}
            ]
            if session.get("encounter_id")
            else []
        },
    }

    # Submit to HealthLake. Real deployments have a retry policy here; a
    # signed note that doesn't reach the EHR is a priority-1 operational
    # incident, not a dropped write.
    #
    # TODO (TechCodeReviewer / TechWriter): The boto3 `healthlake` client
    # does not expose a `create_resource` method. FHIR resource creation
    # on a HealthLake datastore is done by HTTPS POST to the datastore
    # endpoint with SigV4-signed requests (commonly via the `requests`
    # library plus `botocore.auth.SigV4Auth`, or via an FHIR client). The
    # call below will always raise AttributeError on current boto3
    # versions; the except block masks that. Replace this sketch with the
    # real HTTPS+SigV4 pattern (or mark it clearly as pseudo-boto3 for
    # illustration) before the code review pass.
    healthlake = boto3.client("healthlake", config=BOTO3_RETRY_CONFIG)
    try:
        # HealthLake accepts FHIR over HTTPS; the boto3 client provides a
        # thin wrapper. In production, the FHIR client (e.g., fhirclient)
        # or direct requests to the HealthLake endpoint give more control.
        # The placeholder below sketches the pattern; real integration
        # requires the HealthLake datastore ID and appropriate permissions.
        response = healthlake.create_resource(
            DatastoreId="your-healthlake-datastore-id",  # replace with your datastore ID
            ResourceType="DocumentReference",
            ResourceContent=json.dumps(document_reference),
        )
        fhir_id = response.get("ResourceId")
    except (ClientError, AttributeError) as exc:
        # AttributeError here handles the case where a boto3 version
        # doesn't expose create_resource on healthlake; the real integration
        # uses a different SDK path (SigV4-signed HTTPS). For illustration only.
        logger.error("HealthLake write failed: %s", exc)
        sessions_table.update_item(
            Key={"session_id": session_id},
            UpdateExpression="SET #s = :s, ehr_write_error = :e",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": "EHR_WRITE_FAILED",
                ":e": str(exc),
            },
        )
        # Emit an alarm-worthy metric so operators see the failure promptly.
        try:
            cloudwatch.put_metric_data(
                Namespace="AmbientDocumentation",
                MetricData=[
                    {
                        "MetricName": "EHRWriteFailed",
                        "Value": 1.0,
                        "Unit": "Count",
                    }
                ],
            )
        except ClientError:
            pass
        return {"status": "FAILED", "reason": str(exc)}

    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression=(
            "SET #s = :s, ehr_fhir_id = :f, written_to_ehr_at = :t"
        ),
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":s": "WRITTEN_TO_EHR",
            ":f": fhir_id or "",
            ":t": _now_iso(),
        },
    )

    logger.info("Session %s written to EHR (FHIR id=%s)", session_id, fhir_id)
    return {"status": "WRITTEN", "fhir_id": fhir_id}


def _loinc_code_for_encounter(encounter_type: str) -> dict:
    """Map encounter types to LOINC note-type codes. Expand for your institution."""
    mapping = {
        "ambulatory": {"code": "34117-2", "display": "History and physical note"},
        "inpatient_progress": {
            "code": "11506-3",
            "display": "Progress note",
        },
        "discharge_summary": {
            "code": "18842-5",
            "display": "Discharge summary",
        },
    }
    return mapping.get(encounter_type, mapping["ambulatory"])


def _render_note_as_markdown(sections: dict) -> str:
    """Render note sections as markdown for the DocumentReference attachment."""
    order = [
        ("chief_complaint", "Chief Complaint"),
        ("hpi", "History of Present Illness"),
        ("review_of_systems", "Review of Systems"),
        ("medications", "Medications"),
        ("allergies", "Allergies"),
        ("physical_exam", "Physical Examination"),
        ("assessment", "Assessment"),
        ("plan", "Plan"),
    ]
    parts = []
    for key, heading in order:
        content = sections.get(key)
        if content:
            parts.append(f"## {heading}\n\n{content}\n")
    return "\n".join(parts)
```

---

## Step 9: Apply Retention Policies

*The pseudocode calls this `apply_retention(session_id)`. Audio and transcripts carry PHI. Retention policies are institution-specific but typically short for audio (7-30 days), longer for transcripts and signed notes (medical-record retention rules, often 7-30 years). Lifecycle is enforced programmatically; letting S3 lifecycle rules handle deletion is fine, but the audit trail for "when was the audio deleted" has to be explicit.*

```python
def apply_retention(session_id: str, policy: dict | None = None) -> dict:
    """
    Apply retention metadata to audio, transcripts, and notes.

    This example tags S3 objects with retention-policy tags that a lifecycle
    rule can act on. Production systems often use S3 Object Lock for
    signed notes (immutability) plus lifecycle rules for audio and drafts.

    Args:
        session_id: The session whose artifacts need retention applied.
        policy:     Optional override; defaults to RETENTION_POLICY_DEFAULTS.
    """
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    session = sessions_table.get_item(Key={"session_id": session_id}).get("Item")
    if not session:
        return {"status": "ERROR", "reason": "Session not found."}

    policy = policy or RETENTION_POLICY_DEFAULTS

    def _tag_for_retention(bucket: str, key: str, retention_class: str, days: int):
        if not key:
            return
        try:
            s3_client.put_object_tagging(
                Bucket=bucket,
                Key=key,
                Tagging={
                    "TagSet": [
                        {"Key": "retention_class", "Value": retention_class},
                        {"Key": "retention_days", "Value": str(days)},
                        {"Key": "session_id", "Value": session_id},
                    ]
                },
            )
        except ClientError as exc:
            logger.warning(
                "Failed to tag %s/%s for retention: %s", bucket, key, exc,
            )

    # Audio: shortest retention. In some compliance postures, audio is
    # deleted immediately after successful sign-off; here we keep it for
    # a short operational window to allow debugging of bad notes.
    _tag_for_retention(
        AUDIO_BUCKET,
        session.get("audio_s3_key", ""),
        "audio",
        policy["audio_retention_days"],
    )

    # Transcripts: medium-to-long retention, typically matching the signed
    # note. The HealthScribe output URIs point into the output bucket.
    transcript_uri = session.get("transcript_s3_uri", "")
    if transcript_uri and transcript_uri.startswith("s3://"):
        path = transcript_uri[5:]
        bucket, _, key = path.partition("/")
        _tag_for_retention(
            bucket, key, "transcript", policy["transcript_retention_days"],
        )

    # Draft note: short retention after sign-off; the signed note is the
    # record that matters.
    _tag_for_retention(
        NOTES_BUCKET,
        session.get("draft_note_s3_key", ""),
        "draft",
        policy["draft_retention_days"],
    )

    # Signed note: long retention per medical-record rules. If your bucket
    # has Object Lock configured, apply a legal-hold or retention period
    # here via s3_client.put_object_retention. Object Lock requires the
    # bucket to have been created with lock-enabled set.
    _tag_for_retention(
        NOTES_BUCKET,
        session.get("signed_note_s3_key", ""),
        "signed_note",
        policy["signed_note_retention_days"],
    )

    sessions_table.update_item(
        Key={"session_id": session_id},
        UpdateExpression="SET retention_applied_at = :t",
        ExpressionAttributeValues={":t": _now_iso()},
    )
    logger.info("Retention applied for session %s", session_id)
    return {"status": "APPLIED"}
```

---

## Step 10: Emit Quality Metrics

*The pseudocode calls this `emit_quality_metrics(session)`. Metrics drive the quality program. Turnaround time, edit distance, validation pass rate, and the fraction of sessions routed to human review are the canaries. Regressions here surface before clinicians complain; without these metrics, pipeline drift only becomes visible once trust is already damaged.*

```python
def emit_quality_metrics(session_id: str) -> dict:
    """
    Emit CloudWatch metrics for the just-completed session.

    Dimensions: specialty, encounter type, clinician_id. Use caution with
    high-cardinality dimensions (clinician_id in particular); you may want
    to aggregate at the specialty level for dashboards and keep the
    clinician-level dimension in logs only.
    """
    sessions_table = dynamodb.Table(SESSIONS_TABLE)
    session = sessions_table.get_item(Key={"session_id": session_id}).get("Item")
    if not session:
        return {"status": "ERROR", "reason": "Session not found."}

    specialty = session.get("specialty", "general")
    encounter_type = session.get("encounter_type", "ambulatory")

    metrics = []

    consent_at = session.get("consent", {}).get("given_at")
    signed_at = session.get("signed_at")
    if consent_at and signed_at:
        try:
            consent_dt = datetime.datetime.fromisoformat(consent_at)
            signed_dt = datetime.datetime.fromisoformat(signed_at)
            turnaround = (signed_dt - consent_dt).total_seconds()
            metrics.append(
                {
                    "MetricName": "DocumentationTurnaroundSeconds",
                    "Dimensions": [
                        {"Name": "Specialty", "Value": specialty},
                        {"Name": "EncounterType", "Value": encounter_type},
                    ],
                    "Value": float(turnaround),
                    "Unit": "Seconds",
                }
            )
        except (ValueError, TypeError):
            pass

    edit_distance = session.get("edit_distance_metric")
    if edit_distance is not None:
        metrics.append(
            {
                "MetricName": "EditDistance",
                "Dimensions": [
                    {"Name": "Specialty", "Value": specialty},
                    {"Name": "EncounterType", "Value": encounter_type},
                ],
                "Value": float(edit_distance),
                "Unit": "None",
            }
        )

    validation_status = session.get("validation_status", "UNKNOWN")
    metrics.append(
        {
            "MetricName": "ValidationPassedFirstAttempt",
            "Dimensions": [
                {"Name": "Specialty", "Value": specialty},
                {"Name": "EncounterType", "Value": encounter_type},
            ],
            "Value": 1.0 if validation_status == "VALIDATED" else 0.0,
            "Unit": "Count",
        }
    )

    if metrics:
        try:
            cloudwatch.put_metric_data(
                Namespace="AmbientDocumentation", MetricData=metrics,
            )
        except ClientError as exc:
            logger.warning("Failed to emit metrics: %s", exc)

    logger.info("Emitted %d metrics for session %s", len(metrics), session_id)
    return {"status": "EMITTED", "metric_count": len(metrics)}
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable function. Runs all ten steps sequentially for one encounter. In production, each step is a Step Functions state with its own retry policy; Step 3's HealthScribe wait is an EventBridge-triggered resumption; Step 7's wait for clinician sign-off is a wait-for-task-token state. The sequential version below is fine for understanding the flow.

```python
def run_ambient_documentation_pipeline(request: dict) -> dict:
    """
    Run the full ambient documentation pipeline for one encounter.

    In this example we assume the caller:
      1. Calls start_encounter_session(request)
      2. Uploads audio to the returned presigned URL out-of-band
      3. Calls this function with the session_id and the known audio_s3_key,
         the EHR context, and the clinician's edits + attestation (for demo
         convenience). A real deployment orchestrates these asynchronously.

    Args:
        request: Dict with:
            - session_id:          From start_encounter_session
            - audio_s3_key:        Where the audio was uploaded
            - ehr_context:         Structured EHR data for the encounter
            - clinician_edits:     The clinician's edits applied to the draft
                                   (for the example; real UI handles this)
            - clinician_attestation: Text of the sign-off attestation

    Returns:
        Dict with pipeline status and resulting artifact keys.
    """
    session_id = request["session_id"]
    start = time.time()

    # Step 2
    print(f"Step 2: Starting HealthScribe job for session {session_id}...")
    s2 = finalize_audio_and_start_healthscribe(session_id, request["audio_s3_key"])
    if s2.get("status") != "HEALTHSCRIBE_STARTED":
        return {"status": "FAILED", "stage": "step_2", "detail": s2}
    job_name = s2["job_name"]

    # Step 3
    print(f"Step 3: Waiting for HealthScribe job {job_name}...")
    s3 = fetch_healthscribe_output(session_id, job_name)
    if s3.get("status") != "COMPLETE":
        return {"status": "FAILED", "stage": "step_3", "detail": s3}
    transcript_json = s3["transcript"]
    clinical_document_json = s3["clinical_document"]

    # Step 4
    print("Step 4: Extracting must-include entities from transcript...")
    must_include = extract_transcript_entities(transcript_json)

    # Load session for template rendering
    session_record = dynamodb.Table(SESSIONS_TABLE).get_item(
        Key={"session_id": session_id}
    ).get("Item", {})

    # Steps 5-6 loop: render + validate, retry on RETRY_NEEDED
    regeneration_hint = ""
    note_sections = {}
    claims = []
    validation_result = {"status": "NOT_RUN"}
    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        print(f"Step 5 (attempt {attempt}): Rendering institutional note...")
        render_result = render_institutional_note(
            session_record=session_record,
            transcript_json=transcript_json,
            healthscribe_note=clinical_document_json,
            must_include=must_include,
            ehr_context=request.get("ehr_context", {}),
            regeneration_hint=regeneration_hint,
        )
        if render_result.get("status") not in ("RENDERED",):
            # Grounding rejection or parse failure; try once more then bail
            if attempt < MAX_GENERATION_ATTEMPTS:
                regeneration_hint = (
                    "The previous draft was rejected. Produce a note that "
                    "strictly cites transcript segments and EHR sources "
                    "only. Do not include any claim that isn't grounded."
                )
                continue
            return {"status": "FAILED", "stage": "step_5", "detail": render_result}

        note_sections = render_result["sections"]
        claims = render_result["claims"]

        print(f"Step 6 (attempt {attempt}): Validating claims...")
        validation_result = validate_note(
            note_sections=note_sections,
            claims=claims,
            transcript_json=transcript_json,
            must_include=must_include,
            ehr_context=request.get("ehr_context", {}),
            retry_count=attempt - 1,
        )
        if validation_result["status"] == "VALIDATED":
            break
        if validation_result["status"] == "REVIEW_REQUIRED":
            break
        regeneration_hint = validation_result.get("suggested_prompt_augmentation", "")

    # Step 7a: Present for review
    print("Step 7: Presenting draft for clinician review...")
    present_for_review(session_id, note_sections, claims, validation_result)

    # Step 7b: Simulate clinician edits + sign-off (in a real system, the
    # clinician UI drives this via SendTaskSuccess against a Step Functions
    # wait-for-task-token state).
    print("Step 7: Capturing clinician sign-off...")
    edited_sections = request.get("clinician_edits") or note_sections
    signoff = capture_clinician_signoff(
        session_id=session_id,
        edited_sections=edited_sections,
        clinician_attestation=request.get(
            "clinician_attestation",
            "I have reviewed this note and attest it reflects the encounter.",
        ),
    )
    if signoff.get("status") != "SIGNED":
        return {"status": "FAILED", "stage": "step_7_signoff", "detail": signoff}

    # Step 8
    print("Step 8: Writing signed note to EHR...")
    ehr_result = write_to_ehr(session_id)
    # EHR write failure is operationally critical but not a pipeline abort;
    # the signed note is persisted and the retry queue picks it up.

    # Step 9
    print("Step 9: Applying retention policy...")
    apply_retention(session_id)

    # Step 10
    print("Step 10: Emitting quality metrics...")
    emit_quality_metrics(session_id)

    elapsed_ms = int((time.time() - start) * 1000)
    print(f"\nPipeline completed in {elapsed_ms} ms")

    return {
        "status": "COMPLETE",
        "session_id": session_id,
        "signed_note_s3_key": signoff.get("signed_note_s3_key"),
        "edit_distance": signoff.get("edit_distance"),
        "validation_status": validation_result["status"],
        "ehr_write_status": ehr_result.get("status"),
        "processing_time_ms": elapsed_ms,
    }


# --- Example usage ---
if __name__ == "__main__":
    # All clinical content is SYNTHETIC. Do not use real patient audio,
    # PHI, or EHR data in development or testing. This example assumes:
    #   - An AUDIO_BUCKET, HEALTHSCRIBE_OUTPUT_BUCKET, and NOTES_BUCKET exist
    #     with appropriate encryption and Object Lock configuration
    #   - A DynamoDB table named documentation-sessions exists (partition
    #     key: session_id)
    #   - HealthScribe is available in your region and your account has
    #     access to it
    #   - A test audio file has been uploaded to the session's audio S3 key
    #
    # Running without these preconditions will fail at the first AWS call.

    # Step 1: consent capture + session start
    session_response = start_encounter_session(
        {
            "patient_id": "PT-ILLUSTRATIVE-58701",
            "clinician_id": "CLN-FMED-042",
            "encounter_id": "ENC-2026-05-10-00621",
            "encounter_type": "ambulatory",
            "specialty": "family_medicine",
            "jurisdiction": "NY",
            "consent_given": True,
            "consent_method": "verbal",
            "consent_form_version": "v2.3",
            "two_party_jurisdiction": False,
            "audio_format": "wav",
        }
    )
    print("Session start response:", json.dumps(session_response, indent=2, default=str))

    if session_response.get("status") != "READY_FOR_AUDIO":
        raise SystemExit("Session could not be started; stopping example.")

    # In a real run, the clinician's app would now upload audio to the
    # presigned URL. For this example, we assume an uploaded file exists
    # at the audio_s3_key.
    pipeline_result = run_ambient_documentation_pipeline(
        {
            "session_id": session_response["session_id"],
            "audio_s3_key": session_response["audio_s3_key"],
            "ehr_context": {
                "medications": [
                    "metformin 1000 mg twice daily",
                    "lisinopril 20 mg daily",
                    "atorvastatin 40 mg nightly",
                ],
                "allergies": ["no known drug allergies"],
                "problems": ["type 2 diabetes mellitus", "essential hypertension"],
            },
            # Simulate the clinician's edits by passing back the same
            # sections the model generated (edit_distance will be ~0).
            "clinician_edits": None,
            "clinician_attestation": (
                "I have reviewed this AI-drafted note, edited where needed, "
                "and it reflects my encounter with the patient."
            ),
        }
    )

    print("\n" + "=" * 60)
    print("PIPELINE RESULT:")
    print("=" * 60)
    print(json.dumps(pipeline_result, indent=2, default=str))
```

---

## The Gap Between This and Production

Run this end-to-end against a HealthScribe-eligible AWS account with a test audio file uploaded, and you'll see the shape: session started with consent, HealthScribe processes the audio, transcript entities extracted, institutional note rendered, validation run, draft presented, sign-off captured, FHIR write-back attempted, retention applied, metrics emitted. The distance between this and a real health-system deployment is substantial. Here's where the gap lives.

**Consent management is far more than a boolean.** The example has a single `consent_given` attestation. Real consent workflows track patient-level preferences (some patients want to opt out permanently, some for specific encounter types), support mid-encounter withdrawal (patient says "can we stop recording this part"), handle jurisdiction-specific rules (two-party consent in California, Florida, Pennsylvania, and most of the world outside the US), manage minor-patient consent and guardianship, and produce documented consent artifacts that satisfy legal review. Build a patient-preference record that travels with the chart. Enforce it before every session starts. Treat consent as a product, not a checkbox.

**Exam-room audio capture is the unsolved operational problem.** The example assumes audio lands in S3 somehow. In reality, the audio pathway is where ambient documentation rollouts stumble: which device, which microphone, how many mics per room, how to handle the room acoustics, how to stop recording reliably when the encounter ends, how to deal with the clinician forgetting to start recording. Budget serious audio-engineering work per clinic room during rollout. A pilot that works in a quiet demo setting routinely fails in the actual clinic environment.

**Streaming vs batch is an architectural decision with workflow consequences.** This example uses batch HealthScribe processing. Near-real-time streaming is available and is the right choice if your clinician workflow wants the draft ready within a minute of encounter end. Streaming adds complexity (Kinesis Video Streams with WebRTC, streaming ASR consumers, progressive note generation), but it closes the feedback loop at a key point: the clinician reviews and signs before they've moved to the next patient, which materially improves the odds of a high-quality review.

**Step Functions orchestration is non-optional at scale.** The sequential Python in this example is a learning artifact. A production pipeline runs each step as a Step Functions state: the HealthScribe wait is an EventBridge-triggered resumption, the human-in-the-loop step uses a wait-for-task-token pattern, validation retries are a proper state-machine loop with a bounded counter, error handling branches into operational queues, and the state machine itself is the audit trail. Build this early; retrofitting Step Functions onto a working-but-tangled Python orchestration is a rewrite.

**Bedrock Guardrails contextual grounding is a safety net you should not ship without.** The example sets `GUARDRAIL_ID = None`. For production, configure a Guardrail with contextual grounding enabled against the transcript as the source. Set the threshold strict (0.85+). The Guardrail catches blatant hallucination and grounding drift; the validator in Step 6 catches precise citation and numeric mismatches. Running both is the right defense in depth.

**The validator is a token-overlap approximation; upgrade before shipping.** Token presence in the transcript is a coarse signal. A claim about "significant improvement" may appear verbatim in the transcript while being the clinician quoting what the patient hoped would happen, not what was clinically documented. Production validators combine verbatim matching for numerics, embedding-based semantic similarity for non-numeric claims, speaker-role checks (is the claimed source attributed to the right speaker), and a clinical-NER pass over the final note to make sure the coded entities match the transcript's coded entities.

**Template drift is a real operational problem.** The institutional note template evolves over time: a section gets added, terminology gets updated, a new specialty is onboarded. Every prompt change affects output. Version control the template and prompt, stamp the note with the version that produced it, and build a regression test suite of representative encounters you replay through each new version before rolling out. Template drift that goes unmonitored shows up downstream as coding and billing issues, not as "bad notes."

**HealthScribe template enums are limited.** The supported `NoteTemplate` values at time of writing include `HISTORY_AND_PHYSICAL`, `GIRPP`, `BIRP`, `SIRP`, `DAP`, `BEHAVIORAL_SOAP`, and `PHYSICAL_SOAP`. Institutional specialty templates that don't match these are rendered by the Bedrock post-processing step. This is fine, but plan for prompts-and-templates to be a first-class, versioned artifact per specialty. Clinical leadership should own the templates and sign off on changes. Verify the current supported list in the boto3 model before production; the enum grows over time.

**Speaker diarization complexity grows with speaker count.** The example uses `MaxSpeakerLabels=2`. Real encounters frequently have three or more (family member, interpreter, trainee, caregiver). Raise the cap accordingly, and account for the accuracy degradation; diarization gets harder as speaker count grows. Role assignment also gets harder: a trainee asking a clinician-style question sounds like a second clinician voice. Include diarization accuracy in your quality metrics, track it by encounter complexity, and have a path to human correction when it's wrong.

**Sensitive encounter exclusions need real policy.** The example has a static set of excluded encounter types. Real institutions have nuanced rules (mental health is often excluded during rollout, but some psychiatrists opt in for medication-management visits; reproductive-health encounters vary by state law and institutional policy). Build this as a data-driven policy engine that clinical leadership and legal/compliance maintain together, not as a hard-coded set of strings.

**EHR write-back is a full integration project.** The example sketches a HealthLake `CreateResource` call for a FHIR DocumentReference. Real EHR integrations involve the EHR vendor's specific APIs (Epic, Oracle Health, others), each with its own auth, credential rotation, throttling, duplicate-detection, and delivery confirmation patterns. Build the integration as a dedicated service with its own retry queue, its own operational dashboard, and its own alerting. A signed note that doesn't reach the chart is a critical incident; you need to know within minutes, not hours.

**LOINC coding is institution-specific.** The example picks a LOINC code based on a simple encounter-type mapping. Real institutions have coding conventions that pair LOINC with local document types, specialty-specific codes for specialty notes, and often a revenue-cycle review of how notes are coded. Work with the coding and revenue-cycle teams before finalizing the mapping.

**Retention policies need jurisdiction awareness.** The example has a single `RETENTION_POLICY_DEFAULTS` dict. Real systems vary by encounter type (minor records retained longer than adult records in most US states; obstetric records have extended retention for the child's lifetime), by jurisdiction, by content class (behavioral health has stricter rules), and by legal-hold status (discoverability during litigation may require preserving material past the standard window). Build the policy as a lookup on (jurisdiction, encounter_type, content_class, legal_hold_flag), audit the lookup quarterly, and document the rationale.

**Audio retention is the most scrutinized policy.** The example retains audio for 14 days. Many institutions land at 7 days post-signing or immediate deletion after sign-off; others retain audio for months for quality auditing. Every choice has trade-offs (auditability vs privacy posture vs storage cost). Document the rationale, enforce it programmatically via S3 Object Lifecycle and CloudTrail verification, and audit it.

**S3 Object Lock for signed-note immutability.** Object Lock requires the bucket to have lock-enabled configured at creation. Retrofit is not possible; you have to create a new bucket with lock enabled and migrate. Plan this early. For signed clinical notes, Governance or Compliance mode Object Lock with a retention period equal to your longest applicable medical-record retention is typical; any exceptions (litigation, legal hold) are handled as legal-hold overrides rather than mode changes.

**CloudTrail data events are not free but are required.** Track every S3 object access for audio, transcript, and note buckets; every DynamoDB read and write on the sessions table; every Secrets Manager access for EHR credentials. The storage and retention cost is meaningful at volume; the audit requirement is non-negotiable for compliance. Configure CloudTrail to ship to a separate audit account with Object Lock on the CloudTrail bucket for immutability.

**Testing with synthetic data.** There are no tests in this example. A production pipeline has unit tests for JSON parsing, normalization, entity extraction, and numeric-value verification; integration tests against test HealthScribe jobs with known-good audio; regression tests holding known-good note outputs stable through prompt and template changes; and end-to-end tests of the consent-to-EHR-write flow. Never use real clinical audio, transcripts, or PHI in development or test environments. Synthetic encounters with actors under research consent are the correct source of test audio.

**Observability and SLOs matter more than dashboards.** Reasonable targets for production: 95th-percentile draft-ready time under 3 minutes after encounter end, validation pass rate above 85% first-attempt, edit-distance median under 0.20 for well-performing specialties, fraction of sessions routed to review below 5%, and EHR write success above 99.9%. Publish these as CloudWatch SLOs, alert on drift, and close the loop back to pipeline improvements. Without SLOs, problems surface as clinician complaints, and by then the trust is already damaged.

**PHI minimization in prompts.** The prompts in this example include the full transcript and the EHR context. Bedrock under BAA is HIPAA-eligible so this is compliant, but the minimum-necessary principle argues for sending less where feasible. Redact direct identifiers (patient name, MRN) before sending to the model, substitute back during rendering, and narrow the blast radius if Bedrock invocation logging is enabled for quality monitoring. Model-invocation logs will capture the transcript; configure log destination KMS-encryption and retention to match the note archive.

**Cost controls and runaway loops.** `MAX_GENERATION_ATTEMPTS` caps the Bedrock retry loop in code. Add API Gateway rate limits per clinician to prevent a misconfigured client from burning through budget. Track cost per specialty, per encounter-type, and per day; outliers will surprise you. A typical ambulatory encounter runs $0.40-$2.50 end-to-end; a runaway loop with 5 regenerations can cost 5x that for no value.

**DynamoDB Decimal gotcha.** The example's `_to_decimal_safe` helper routes floats through `Decimal(str(value))`. This is muscle memory worth developing: every `put_item` and `update_item` with numeric fields should go through it. Going through `str` avoids the binary-precision issues that `Decimal(float_value)` introduces. The first time you forget this, DynamoDB will raise `TypeError: Float types are not supported`. Adding `_to_decimal_safe` at every persistence call from the start saves that debugging session.

**JSON parsing resilience.** The `_parse_json_response` helper strips markdown fences. In production, when parsing fails entirely, the correct fallback is to send the raw output back to the model with a "fix the JSON structure; preserve content" instruction. Models are usually good at self-correcting structural errors, and this saves a full regeneration cycle for recoverable formatting issues.

**Clinician review UX is the product.** The API surface in this example produces a JSON note with a `claims` list; the UI has to render that into a clinician-usable review experience. Inline citations (`[seg_3]`) have to be clickable and show the transcript snippet. Low-confidence ASR segments have to be visually distinguished. Drug names and doses have to be highlighted for review attention. "Must-complete" placeholders for un-narrated exam sections need to stand out. The review UI is at least as much engineering as the pipeline, and it is where adoption lives or dies. Shallow integrations fail; deep integrations with the EHR (launched from the encounter, signed back into the encounter) are what clinicians tolerate.

**Change management is half the rollout.** A technically-correct pipeline fails if clinicians don't adopt it. Budget significant change-management effort: training on how to talk during encounters with ambient documentation active (narrate the exam, speak clearly, be aware what's being captured), support during the first weeks (a human support channel, not just documentation), and feedback loops that visibly close (clinician complaints become template or prompt changes). This is not optional.

**Case review is the quality program.** Sample signed notes weekly with a clinical reviewer. Look at what the AI got right, what it got wrong, and what clinicians edited. The patterns feed directly into prompt iteration, template changes, and training content. Budget clinical-reviewer time as an ongoing cost. Skip this and the pipeline silently degrades; the metrics look fine until they don't.

**Equity: the failure modes are worst for patients who are hardest to serve.** Non-native English speakers, patients with heavy accents, patients with impaired speech, patients from demographic groups underrepresented in ASR training data all get worse pipeline performance. Measure this explicitly. Track validation-pass rate, edit-distance, and clinician-reported issues by patient language, accent indicators where known, and demographic bucket. Address gaps explicitly, don't assume the system serves everyone equally until you've verified it does.

**The clinician is still the signer.** The AI drafts; the clinician reviews; the clinician signs. Never auto-route a draft to the chart. Never remove the signing step. This is the single most important workflow invariant in the whole architecture. Every line of this code assumes it; every deployment should enforce it.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 2.8: Ambient Clinical Documentation](chapter02.08-ambient-clinical-documentation) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
