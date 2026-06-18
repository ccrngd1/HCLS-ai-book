# Recipe 5.10: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 5.10. It shows one way you could translate the multi-source deceased-patient-resolution pipeline into working Python. The demo uses several `MockDeathEventSource` instances standing in for the SSA Limited Access Death Master File, a state vital-records FHIR feed, a payer death feed, an EHR-recorded-death source, and a family-reported-death intake; a `MockLocalMPI` standing in for the institution's Aurora PostgreSQL master patient index; a `MockDownstreamSystem` family standing in for the appointment scheduling system, the active-prescription system, the billing system, the outreach platform, the patient-portal access controller, and the cross-recipe consumers; an in-memory event bus standing in for Amazon EventBridge; and small helpers for the death-event log, the verification queue, the cascade-acknowledgment store, and CloudWatch-style metrics. It is not production-ready. There is no real LADMF subscription (no certification under the Bipartisan Budget Act of 2013), no real state-vital-records-feed integration (no FHIR VRDR endpoint), no real payer death-feed integration (no CMS Medicare Beneficiary Database connection), no real EHR integration, no Step Functions orchestration, no real DynamoDB or Aurora wiring, no real EventBridge rules with cross-account fan-out, no SageMaker calibration loop, no Glue jobs, no posthumous-protection access-control engine, no personal-representative-portal Cognito integration, and no IAM, KMS, VPC, WAF, or CloudTrail wiring. Think of it as the sketchpad version: useful for understanding the shape of a deceased-patient-resolution pipeline that respects the per-source provenance discipline, the multi-source reconciliation discipline, the premature-death-report verification discipline, the hidden-duplicate-revelation handling, the per-system cascade-propagation discipline, and the family-experience touchpoints this recipe demands. It is not something you would point at the SSA's data exchange on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the six core pseudocode steps from the main recipe: ingest a death event from a source feed with per-event provenance capture; match the event against the local MPI under the per-source matching tolerance and detect hidden-duplicate-revelation cases; reconcile multiple death events for the same matched patient with date-of-death conflict resolution and premature-death-report detection; apply the death-status update to the MPI atomically; propagate the update to downstream operational systems on each system's appropriate cadence; and handle premature-death-report verification and reversal when a death report turns out to be incorrect. The synthetic patients, sources, organizations, and identifiers in the demo are fictional; the names, DOBs, addresses, and other identifiers are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also install [`requests`](https://requests.readthedocs.io/) for the HTTPS calls into the LADMF subscription endpoint and the per-state vital-records FHIR feeds (production typically runs over mTLS where the source supports it), [`fhir.resources`](https://github.com/nazrulworld/fhir.resources) for parsing FHIR-based VRDR death-event payloads from modernized state vital-records feeds, [Splink](https://github.com/moj-analytical-services/splink) or [`recordlinkage`](https://github.com/J535D165/recordlinkage) for the matching core's Fellegi-Sunter probabilistic-combiner (the same machinery used in recipes 5.1, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9), [`jellyfish`](https://github.com/jamesturk/jellyfish) for the approximate string matching the matcher consumes, [`usaddress`](https://github.com/datamade/usaddress) for the USPS-style address standardization that recipe 5.3 produces, and a Spark client (`pyspark`) for the population-scale batch-matching variants. The demo replaces all of these with small mocks so the focus stays on the per-source ingestion, multi-source reconciliation, MPI update, cascade propagation, and reversal logic rather than on the source-integration plumbing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:TransactWriteItems` on the `death-event-log`, `verification-queue`, `cascade-ack-store`, and `personal-representative-authorization` tables
- `s3:PutObject` and `s3:GetObject` on the per-source landing-zone bucket and the audit-archive bucket (Object Lock in Compliance mode), scoped to per-source prefixes for the per-source ingestion Lambdas
- `events:PutEvents` on the `deceased-patient-events-bus`
- `sqs:SendMessage` and `sqs:ReceiveMessage` on the cascade-acknowledgment queue and the verification-review queue
- `cloudwatch:PutMetricData` for the per-source ingestion-rate, mean-time-to-recognize-death, false-positive-death-rate, family-correspondence-after-death-rate, cross-system-propagation-completeness, and premature-death-report-reversal-latency metrics
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the death-event-log, verification-queue, cascade-ack-store, the audit-archive bucket, and the per-source landing-zone bucket
- `secretsmanager:GetSecretValue` on the per-source-credentials and per-jurisdiction-credentials secrets pinned to the current rotation version
- `cognito-idp:AdminGetUser` and the personal-representative-portal IdP-specific permissions on personal-representative authentication flows during the estate-administration period
- For the multi-stage orchestration: `states:StartExecution` and `states:DescribeExecution` on the death-event-resolution state machine

Scope each Lambda's IAM role and each Step Functions execution role to the specific resource ARNs they touch. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The death-event-matcher Lambda has read-only access to the local MPI; mutations to the local MPI happen through the mpi-update-handler Lambda, which has scoped write access to the death-status fields but not to the rest of the MPI's schema. The premature-death-report-verification-router Lambda has scoped access to the verification queue and the audit archive but no write access to the MPI. The per-system-cascade Lambdas have scoped access to the operational systems they operate against and emit acknowledgments to the cascade-ack-store under a separate role.

A few things worth knowing upfront:

- **The per-source provenance is the audit substrate.** Every death event carries per-event provenance (which source reported it, when, with what supporting evidence, with what source-quality classification at ingestion time). The downstream pipeline consumes the provenance at every decision point. Skip the provenance capture and you cannot reverse premature death reports correctly later, because the audit trail no longer reflects which source triggered the resolution.
- **The per-source matching tolerance is calibrated separately per source.** The SSA LADMF has high-quality demographics with SSN-anchored matching; the tolerance can be tighter. The state vital-records FHIR feed carries the death-certificate's authoritative demographics; tolerance similar to LADMF. The family-reported-death intake has variable demographic completeness; the tolerance is looser to accept incomplete data with appropriate confidence weighting. Re-using one tolerance across all sources produces silent matching-quality compromise: family-reported intakes get rejected because the tolerance was tuned for high-quality sources, or LADMF events get accepted at false-positive rates because the tolerance was tuned for the loosest source.
- **Premature death reports are real, and the verification-and-reversal pathway is operationally important.** The SSA LADMF has a small but non-trivial premature-death-report rate (single-digit percentage); the patient experiencing an incorrectly-applied death status has insurance terminated, prescriptions cancelled, appointments cancelled, and patient-portal access suspended within hours. The verification queue surfaces single-source death events that have not been corroborated by other sources; the reversal pathway restores the live-patient state with named operational ownership and dual-control approval. Skip the verification step and you produce the disrupted-patient-experience cases the recipe is for.
- **Hidden-duplicate-revelation is a first-class operational pattern.** Death events frequently match against multiple records in the local MPI that the institution had not previously recognized as the same person. The high-quality demographics of an authoritative death-event source (death-certificate-grade data) are sometimes the strongest matching signal the institution has, and the matching reveals duplicate chains that years of operational matching had missed. The pipeline detects these cases and routes them to the recipe 5.1 duplicate-resolution pipeline atomically with the death-status application.
- **Date-of-death conflicts are routine.** Different sources report different dates for the same patient (the death certificate's date is the legally authoritative one; the SSA's date may be the date the death was reported rather than the date of death itself; the EHR's date is whatever was entered at the time of pronouncement). The reconciliation policy carries per-use-case selected dates (death-certificate-date for legal-and-billing; EHR-recorded-date for clinical-event-timing; earliest-plausible-date for cohort-survival) and flags threshold-exceeded conflicts for human review.
- **The downstream cascade has per-system appropriate cadences.** Appointment cancellation must be near-real-time (an appointment scheduled for tomorrow has its automated reminder going out today, and the family experience of a wrong-patient reminder is acutely negative). Active-prescription review can be slightly slower but still same-business-day (active mail-order packages may need clinical disposition). Billing-system episode closure can be hours to a day. Analytics-platform propagation can be batch (next analytics run picks up the new death status). The cascade Lambdas operate on each system's appropriate cadence with explicit acknowledgment back to the cascade-ack-store.
- **DynamoDB rejects Python `float`.** Every match score, similarity score, and numeric metadata field passes through `Decimal` on its way in and on its way out. Same gotcha as recipes 5.1 / 5.2 / 5.3 / 5.4 / 5.5 / 5.6 / 5.7 / 5.8 / 5.9; the same `_to_decimal` helper handles it.
- **The example collapses Step Functions, multiple Lambdas, the per-source ingestion, the EventBridge fan-out, the SQS-driven cascade workers, and the personal-representative-portal Cognito IdP into a single Python file for readability.** In production the per-source ingestion handlers, the death-event-matcher, the multi-source-reconciler, the premature-death-report-verification-router, the hidden-duplicate-revealer, the mpi-update-handler, the per-system cascade Lambdas, the verification-queue review tooling, the personal-representative-portal Cognito IdP, and the posthumous-protection access-control engine are separate Lambdas (and Step Functions) running in separate AWS accounts under cross-account access policies, each with their own error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the per-source ingestion configuration, the per-source matching tolerance, the date-of-death conflict-resolution policy, the per-cascade-consumer cadence configuration, and the per-feature weights for the matcher are what you would change between environments.

```python
import hashlib
import json
import logging
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records
# to CloudWatch Logs Insights. The deceased-patient-resolution
# pipeline operates on heavily PHI-adjacent data: the death-
# event payload carries the patient's name, DOB, SSN-last-4,
# address, the date and cause of death, and the per-source
# supporting-evidence references all of which should not leak
# through logs. Log structural metadata only (event_id,
# source_id, matched_record_id summary, decision band,
# resolution status), never the actual demographic values, never
# the cause of death, never the supporting-evidence content.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from DynamoDB, EventBridge,
# CloudWatch, S3, SQS, Step Functions, and Secrets Manager. The
# deceased-patient-resolution pipeline has a per-source response-
# window expectation (the appointment-cancellation cascade has a
# strict near-real-time expectation; the analytics-platform
# cascade is batch). Step Functions Catch states distinguish
# retriable infrastructure failures from terminal logic failures
# and route terminal failures to DLQs for human investigation.
BOTO3_RETRY_CONFIG = Config(
    retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm
# containers so each invocation does not pay the connection cost.
REGION = "us-east-1"
dynamodb           = boto3.resource("dynamodb", region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
s3_client          = boto3.client("s3",          region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
sqs_client         = boto3.client("sqs",         region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
eventbridge_client = boto3.client("events",      region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
cloudwatch_client  = boto3.client("cloudwatch",  region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
secrets_client     = boto3.client("secretsmanager", region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
kms_client         = boto3.client("kms",         region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)
sfn_client         = boto3.client("stepfunctions", region_name=REGION,
                                      config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill these in with your actual resource names. The demo prints
# what it would write rather than failing if the resources do
# not exist; see run_demo() at the bottom.
DEATH_EVENT_LOG_TABLE          = "death-event-log"
VERIFICATION_QUEUE_TABLE       = "verification-queue"
CASCADE_ACK_STORE_TABLE        = "cascade-ack-store"
PERSONAL_REP_AUTH_TABLE        = "personal-representative-authorization"
DEATH_SOURCE_LANDING_BUCKET    = "deceased-resolution-landing-zone"
AUDIT_ARCHIVE_BUCKET           = "deceased-resolution-audit-archive"
CASCADE_ACK_QUEUE_URL          = "https://sqs.us-east-1.amazonaws.com/000000000000/cascade-ack-queue"
VERIFICATION_REVIEW_QUEUE_URL  = "https://sqs.us-east-1.amazonaws.com/000000000000/verification-review-queue"
DECEASED_EVENT_BUS_NAME        = "deceased-patient-events-bus"
RESOLUTION_STATE_MACHINE       = "deceased-patient-resolution-orchestrator"
CLOUDWATCH_NAMESPACE           = "DeceasedPatientResolution"

# Deploy-time guardrail. Any blank resource name is a deploy-
# time bug, not a runtime surprise.
for _name, _value in [
    ("DEATH_EVENT_LOG_TABLE",         DEATH_EVENT_LOG_TABLE),
    ("VERIFICATION_QUEUE_TABLE",      VERIFICATION_QUEUE_TABLE),
    ("CASCADE_ACK_STORE_TABLE",       CASCADE_ACK_STORE_TABLE),
    ("PERSONAL_REP_AUTH_TABLE",       PERSONAL_REP_AUTH_TABLE),
    ("DEATH_SOURCE_LANDING_BUCKET",   DEATH_SOURCE_LANDING_BUCKET),
    ("AUDIT_ARCHIVE_BUCKET",          AUDIT_ARCHIVE_BUCKET),
    ("CASCADE_ACK_QUEUE_URL",         CASCADE_ACK_QUEUE_URL),
    ("VERIFICATION_REVIEW_QUEUE_URL", VERIFICATION_REVIEW_QUEUE_URL),
    ("DECEASED_EVENT_BUS_NAME",       DECEASED_EVENT_BUS_NAME),
    ("RESOLUTION_STATE_MACHINE",      RESOLUTION_STATE_MACHINE),
    ("CLOUDWATCH_NAMESPACE",          CLOUDWATCH_NAMESPACE),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every event and every decision carries the matcher-config
# version, the per-source-tolerance version, and the conflict-
# resolution-policy version active at decision time. This is
# how a future audit reconstructs which calibration was active
# when a particular death event was handled.
MATCHER_CONFIG_VERSION              = "deceased-matcher-v1.4.2"
SOURCE_TOLERANCE_VERSION            = "deceased-tolerance-v1.3.0"
CONFLICT_POLICY_VERSION             = "dod-conflict-policy-v1.2.0"
INSTITUTION_ID                      = "academic-medical-center-richmond"
INSTITUTION_JURISDICTION            = "state-of-virginia"

# --- Source-quality classifications ---
# The per-source-quality classifications drive the matching
# tolerance and the verification-routing decisions. The classifi-
# cations are versioned and reviewed periodically as source
# quality drifts (the LADMF's premature-death-report rate has
# shifted historically; per-state vital-records-feed accuracy
# improves as states modernize). Production reads from a config
# store; the demo holds them inline for readability.
SOURCE_QUALITY_CLASSIFICATIONS = {
    "ssa-ladmf": {
        "premature_death_report_rate_baseline": Decimal("0.013"),
        "data_completeness_score":              Decimal("0.78"),
        "matching_anchor_strength_class":       "ssn_strong",
        "supporting_document_certainty":        "ssa_record",
        "authoritative_for_legal_billing":      False,
    },
    "state-vital-records-virginia": {
        "premature_death_report_rate_baseline": Decimal("0.002"),
        "data_completeness_score":              Decimal("0.94"),
        "matching_anchor_strength_class":       "demographics_strong",
        "supporting_document_certainty":        "death_certificate",
        "authoritative_for_legal_billing":      True,
    },
    "payer-cms-mbd": {
        "premature_death_report_rate_baseline": Decimal("0.005"),
        "data_completeness_score":              Decimal("0.88"),
        "matching_anchor_strength_class":       "ssn_strong",
        "supporting_document_certainty":        "cms_enrollment_record",
        "authoritative_for_legal_billing":      False,
    },
    "ehr-internal": {
        "premature_death_report_rate_baseline": Decimal("0.0005"),
        "data_completeness_score":              Decimal("0.99"),
        "matching_anchor_strength_class":       "internal_id_anchor",
        "supporting_document_certainty":        "facility_recorded_death",
        "authoritative_for_legal_billing":      False,
    },
    "family-reported-intake": {
        "premature_death_report_rate_baseline": Decimal("0.020"),
        "data_completeness_score":              Decimal("0.65"),
        "matching_anchor_strength_class":       "demographics_partial",
        "supporting_document_certainty":        "family_attestation",
        "authoritative_for_legal_billing":      False,
    },
    "obituary-aggregator": {
        "premature_death_report_rate_baseline": Decimal("0.030"),
        "data_completeness_score":              Decimal("0.55"),
        "matching_anchor_strength_class":       "demographics_partial",
        "supporting_document_certainty":        "published_obituary",
        "authoritative_for_legal_billing":      False,
    },
}

# --- Per-source matching tolerance ---
# Calibrated separately per source. The SSA LADMF has high-
# quality demographics and SSN-last-4 anchoring; tolerance can
# be tighter (higher acceptance threshold means fewer candidates
# but those candidates are more reliable). Family-reported
# intake has variable completeness; tolerance must be looser
# (lower acceptance threshold) but the resulting candidates
# always route to verification before action because the source
# quality is variable.
SOURCE_MATCHING_TOLERANCE = {
    "ssa-ladmf": {
        "candidate_acceptance_threshold": Decimal("0.70"),
        "high_confidence_threshold":      Decimal("0.88"),
        "max_candidate_count":            5,
    },
    "state-vital-records-virginia": {
        "candidate_acceptance_threshold": Decimal("0.65"),
        "high_confidence_threshold":      Decimal("0.85"),
        "max_candidate_count":            10,
    },
    "payer-cms-mbd": {
        "candidate_acceptance_threshold": Decimal("0.70"),
        "high_confidence_threshold":      Decimal("0.88"),
        "max_candidate_count":            5,
    },
    "ehr-internal": {
        "candidate_acceptance_threshold": Decimal("0.95"),
        "high_confidence_threshold":      Decimal("0.99"),
        "max_candidate_count":            1,
    },
    "family-reported-intake": {
        "candidate_acceptance_threshold": Decimal("0.55"),
        "high_confidence_threshold":      Decimal("0.85"),
        "max_candidate_count":            10,
    },
    "obituary-aggregator": {
        "candidate_acceptance_threshold": Decimal("0.60"),
        "high_confidence_threshold":      Decimal("0.85"),
        "max_candidate_count":            5,
    },
}

# --- Per-feature weights for the matcher ---
# Same Fellegi-Sunter probabilistic-record-linkage core as
# recipes 5.1 / 5.5 / 5.7 / 5.9. The weights reflect the
# relative discriminating power of each feature for deceased-
# patient resolution. SSN-last-4 is heavily weighted when
# present (LADMF and CMS MBD include it); family-name and DOB
# carry strong weight as the universal identifying anchors.
FEATURE_WEIGHTS = {
    "given_name":   Decimal("0.16"),
    "family_name":  Decimal("0.20"),
    "dob":          Decimal("0.25"),
    "address_line": Decimal("0.08"),
    "zip_code":     Decimal("0.04"),
    "ssn_last_4":   Decimal("0.20"),
    "sex":          Decimal("0.07"),
}

# --- Date-of-death conflict resolution policy ---
# Per-use-case date selection. The legal-and-billing date is
# the death-certificate date when available (state vital-records
# is the authoritative source); the clinical-event-timing date
# is the EHR-recorded date when available; the earliest-
# plausible date is the minimum of all reported dates (used for
# right-censoring in cohort-survival analyses).
SOURCE_DATE_AUTHORITY_RANKING = [
    "state-vital-records-virginia",  # death certificate
    "ehr-internal",                  # facility-recorded death
    "ssa-ladmf",                     # SSA record
    "payer-cms-mbd",                 # CMS enrollment record
    "obituary-aggregator",           # published obituary
    "family-reported-intake",        # family attestation
]

# Threshold above which date conflicts route to human review.
# 7 days reflects the typical reporting-lag tolerance; conflicts
# of more than a week usually indicate a real disagreement that
# needs investigation rather than a normal lag.
DATE_CONFLICT_THRESHOLD_DAYS = 7

# --- Premature-death-report verification threshold ---
# When a death event arrives from a source with premature-
# death-report rate above this threshold AND no corroboration
# from other sources, route to the verification queue before
# applying the death status. The threshold balances the
# false-positive impact (incorrectly disrupted patients) against
# the recognition latency (additional days waiting for
# verification).
PREMATURE_DEATH_REPORT_VERIFICATION_THRESHOLD = Decimal("0.010")

# --- Per-cascade-consumer cadence configuration ---
# Each downstream system has its own appropriate-cadence
# configuration. Real-time means the cascade Lambda fires
# immediately on the EventBridge event; batched means the
# cascade waits for the next batch window; on-demand means the
# cascade fires only when the consumer system pulls.
CASCADE_CONSUMER_CONFIG = {
    "appointment-system":       {"cadence": "real_time",
                                  "sla_seconds":   60},
    "prescription-system":      {"cadence": "real_time",
                                  "sla_seconds":  300},
    "outreach-platform":        {"cadence": "real_time",
                                  "sla_seconds":   60},
    "billing-system":           {"cadence": "near_real_time",
                                  "sla_seconds": 3600},
    "patient-portal":           {"cadence": "real_time",
                                  "sla_seconds":  120},
    "care-management":          {"cadence": "near_real_time",
                                  "sla_seconds": 1800},
    "analytics-platform":       {"cadence": "batch",
                                  "sla_seconds": 86400},
    "cross-recipe-5.1":         {"cadence": "real_time",
                                  "sla_seconds":  300},
    "cross-recipe-5.5":         {"cadence": "real_time",
                                  "sla_seconds":  600},
    "cross-recipe-5.7":         {"cadence": "near_real_time",
                                  "sla_seconds": 1800},
    "cross-recipe-5.8":         {"cadence": "near_real_time",
                                  "sla_seconds": 1800},
    "cross-recipe-5.9":         {"cadence": "real_time",
                                  "sla_seconds":  600},
}

# --- Confidence tier classifications ---
HIGH_CONFIDENCE       = "high"
MEDIUM_CONFIDENCE     = "medium"
LOW_CONFIDENCE        = "low"

# --- Resolution status values ---
RES_RECEIVED          = "received"
RES_NO_MATCH          = "no_match"
RES_LOW_CONF_NO_MATCH = "low_confidence_no_match"
RES_QUEUED_FOR_REVIEW = "queued_for_review"
RES_HIDDEN_DUPLICATE  = "hidden_duplicate_candidate"
RES_DATE_CONFLICT     = "date_of_death_conflict_flagged"
RES_PREMATURE_FLAGGED = "premature_death_report_flagged"
RES_APPLIED           = "applied"
RES_REVERSED          = "reversed"
```

---

## Helpers

Same family of small helpers used throughout chapter 5. The `_to_decimal`, `_serialize_for_dynamodb`, and `_canonical_name` helpers are the load-bearing ones. The recipe-5.10-specific helpers (`_parse_iso_date`, `_days_between`, `_summarize_event_for_audit`) handle the date-of-death-arithmetic and audit-summary discipline this recipe needs.

```python
def _to_decimal(value) -> Decimal:
    """Coerce numeric input into Decimal for DynamoDB."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

def _now_iso() -> str:
    """UTC timestamp in ISO 8601 format. Always UTC; never local
    time. Cross-source audit reconstruction joins logs from
    multiple feeds whose timestamps are in different time
    zones; UTC is the only sane lingua franca."""
    return datetime.now(timezone.utc).isoformat()

def _strip_diacritics(s: str) -> str:
    """Strip combining diacritical marks for canonicalization.
    Critical for matching where one source's data may have
    stripped accents on input while another preserved them; if
    the canonicalization differs, the matcher silently misses
    matches that should have succeeded."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def _canonical_name(*parts) -> str:
    """Normalize a name to canonical lowercase whitespace-
    collapsed form. Production handles per-tradition rules
    (Spanish double-surname order, East Asian family-name-first
    conventions, Arabic patronymic structures) here too."""
    joined = " ".join(str(p or "").strip() for p in parts)
    joined = _strip_diacritics(joined).lower()
    joined = re.sub(r"[^\w\s'-]", " ", joined)
    joined = re.sub(r"\s+", " ", joined).strip()
    return joined

def _normalize_address(address: str) -> str:
    """Light USPS-style standardization. Production uses a real
    USPS-CASS-certified standardizer (see recipe 5.3)."""
    if not address:
        return ""
    s = address.strip()
    replacements = [
        (r"\bStreet\b",    "St"),
        (r"\bAvenue\b",    "Ave"),
        (r"\bBoulevard\b", "Blvd"),
        (r"\bDrive\b",     "Dr"),
        (r"\bLane\b",      "Ln"),
        (r"\bRoad\b",      "Rd"),
    ]
    for pattern, repl in replacements:
        s = re.sub(pattern, repl, s, flags=re.IGNORECASE)
    return _canonical_name(s)

def _parse_iso_date(s: str) -> Optional[datetime]:
    """Parse an ISO 8601 date or date-time. Returns None on
    failure. Production carries explicit per-source date
    parsers for source-specific format quirks."""
    if not s:
        return None
    try:
        # Date-only first, then full datetime.
        if "T" not in s and len(s) == 10:
            return datetime.strptime(s, "%Y-%m-%d").replace(
                tzinfo=timezone.utc)
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None

def _days_between(date_a: str, date_b: str) -> Optional[int]:
    """Days between two ISO date strings. Returns None if either
    cannot be parsed."""
    a = _parse_iso_date(date_a)
    b = _parse_iso_date(date_b)
    if a is None or b is None:
        return None
    return abs((a - b).days)

def _jaro_winkler(s1: str, s2: str) -> Decimal:
    """Jaro-Winkler approximate string similarity. Production
    uses jellyfish; the demo provides a hand-rolled version so
    the dependency surface stays small. Range: 0.0 (no
    similarity) to 1.0 (identical)."""
    if not s1 and not s2:
        return Decimal("1.0")
    if not s1 or not s2:
        return Decimal("0.0")
    if s1 == s2:
        return Decimal("1.0")
    len1, len2 = len(s1), len(s2)
    match_window = max(len1, len2) // 2 - 1
    if match_window < 0:
        match_window = 0
    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    for i in range(len1):
        start = max(0, i - match_window)
        end = min(i + match_window + 1, len2)
        for j in range(start, end):
            if s2_matches[j]:
                continue
            if s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break
    if matches == 0:
        return Decimal("0.0")
    transpositions = 0
    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1
    transpositions //= 2
    jaro = (
        Decimal(matches) / Decimal(len1)
        + Decimal(matches) / Decimal(len2)
        + Decimal(matches - transpositions) / Decimal(matches)
    ) / Decimal(3)
    prefix = 0
    for i in range(min(4, len1, len2)):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break
    return jaro + Decimal(prefix) * Decimal("0.1") * (Decimal(1) - jaro)

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _serialize_for_dynamodb(obj):
    """Recursive serialization helper. Same pattern as recipes
    5.1 - 5.9."""
    if isinstance(obj, dict):
        return {k: _serialize_for_dynamodb(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_for_dynamodb(v) for v in obj]
    if isinstance(obj, set):
        return [_serialize_for_dynamodb(v) for v in sorted(obj)]
    if isinstance(obj, float):
        return Decimal(str(obj))
    return obj

def _summarize_event_for_audit(normalized_event: dict) -> dict:
    """Audit-friendly summary of a death-event payload. Records
    WHAT features were present (not their values), the payload's
    structural shape, and a content hash that lets the audit
    reconstruct payload identity for dispute resolution without
    retaining the actual demographic content. The actual feature
    values flow through the matcher and the audit archive (where
    they are encrypted at rest with the audit-archive KMS key);
    the structured logs hold only the summary."""
    features_present = sorted(
        k for k, v in normalized_event.items() if v)
    canonical = json.dumps(
        {k: normalized_event.get(k) for k in features_present},
        sort_keys=True, default=str)
    return {
        "features_present":  features_present,
        "feature_count":     len(features_present),
        "payload_hash":      _sha256(canonical)[:16],
    }

def _emit_metric(metric_name: str, value: float,
                  dimensions: dict = None) -> None:
    """CloudWatch metric emit. Cohort-bucket-hash dimensions
    feed cohort-stratified accuracy monitoring; production
    aggregates by SourceId and CohortBucketHash and alarms on
    per-source-quality drift and per-cohort match-rate
    disparities."""
    try:
        cloudwatch_client.put_metric_data(
            Namespace=CLOUDWATCH_NAMESPACE,
            MetricData=[{
                "MetricName": metric_name,
                "Value": value,
                "Unit": "Count",
                "Dimensions": [
                    {"Name": k, "Value": v}
                    for k, v in (dimensions or {}).items()
                ],
            }],
        )
    except Exception as exc:
        logger.warning("metric emit failed",
                        extra={"metric": metric_name,
                                "error": str(exc)})

def _archive_to_s3(payload: dict, bucket: str, partition: str,
                     key_id: str = None) -> None:
    """Best-effort archive to S3 with KMS encryption. Failures
    logged and skipped (the demo prints what it would write)."""
    today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    kid = key_id or uuid.uuid4().hex
    key = f"{partition}/{today}/{kid}.json"
    body = json.dumps(payload, default=str).encode("utf-8")
    try:
        s3_client.put_object(
            Bucket=bucket, Key=key, Body=body,
            ServerSideEncryption="aws:kms",
        )
    except Exception as exc:
        logger.info("archive write skipped (demo mode is fine)",
                     extra={"bucket": bucket, "key": key,
                              "error": str(exc)})

def _audit_log(event: dict) -> None:
    """Write an audit-event-log row. In production this is a
    DynamoDB PutItem on the audit-event-log table with full
    context. The demo logs and archives best-effort."""
    enriched = dict(event)
    enriched.setdefault("audit_event_id", uuid.uuid4().hex)
    enriched.setdefault("logged_at", _now_iso())
    enriched.setdefault("matcher_config_version", MATCHER_CONFIG_VERSION)
    enriched.setdefault("tolerance_version", SOURCE_TOLERANCE_VERSION)
    enriched.setdefault("conflict_policy_version", CONFLICT_POLICY_VERSION)
    logger.info("audit_event", extra={"event": enriched["event_type"]})
    _archive_to_s3(enriched, AUDIT_ARCHIVE_BUCKET,
                     f"audit-events/{enriched['event_type']}",
                     key_id=enriched["audit_event_id"])

def _summarize_for_audit(identity: dict) -> dict:
    """Identity summary for audit logs. Captures the role and
    the principal_id but never the full credential context."""
    if not identity:
        return {"role": "unknown", "principal_id_hash": "n/a"}
    pid = identity.get("principal_id") or "unknown"
    return {
        "role":              identity.get("role", "unknown"),
        "principal_id_hash": _sha256(pid)[:16],
        "organizational_unit": identity.get("organizational_unit"),
    }
```

---

## Mock Local MPI, Downstream Systems, and In-Memory Stores

Production reads the local MPI from Aurora PostgreSQL. The downstream operational systems are real production systems with real APIs (the appointment-scheduling system's cancellation API, the e-prescribing system's auto-refill-cancellation API, the billing system's episode-closure API, the patient-portal access-controller's account-suspension API). The death-event log and verification queue are DynamoDB tables with KMS encryption and DynamoDB Streams driving the cross-recipe fan-out. The demo includes small mocks that exercise the full multi-source flow without requiring those external dependencies.

```python
# --- Mock local MPI ---
SYNTHETIC_LOCAL_MPI_RECORDS = [
    {
        "local_record_id":      "amc-richmond-mrn-3387221",
        "given_name":           "Robert",
        "middle_name":          "James",
        "family_name":          "Anderson",
        "dob":                  "1942-05-14",
        "sex":                  "M",
        "address_line":         "1247 Oak St",
        "city":                 "Richmond",
        "state":                "VA",
        "zip_code":             "23220",
        "phone":                "+18045551111",
        "ssn_last_4":           "4827",
        "deceased_status":      None,
        "death_event_history":  [],
        "active_appointments":  [
            {"appointment_id": "appt-44211",
             "scheduled_for":   "2026-02-14T10:00:00Z",
             "type":            "cardiology_followup"},
            {"appointment_id": "appt-44885",
             "scheduled_for":   "2026-03-08T14:30:00Z",
             "type":            "primary_care_annual"},
            {"appointment_id": "appt-45102",
             "scheduled_for":   "2026-04-22T09:15:00Z",
             "type":            "lab_draw"},
        ],
        "active_prescriptions": [
            {"prescription_id": "rx-77881",
             "drug_name":       "atorvastatin",
             "auto_refill":     True},
            {"prescription_id": "rx-77882",
             "drug_name":       "lisinopril",
             "auto_refill":     True},
            {"prescription_id": "rx-77883",
             "drug_name":       "warfarin",
             "auto_refill":     True,
             "controlled":      False,
             "requires_review": True},
            {"prescription_id": "rx-77884",
             "drug_name":       "metoprolol",
             "auto_refill":     True},
            {"prescription_id": "rx-77885",
             "drug_name":       "furosemide",
             "auto_refill":     True},
        ],
        "open_billing_episodes": [
            {"episode_id": "epi-99001",
             "type":        "outpatient_cardiology",
             "opened_at":   "2026-01-15T00:00:00Z"},
            {"episode_id": "epi-99002",
             "type":        "outpatient_primary_care",
             "opened_at":   "2026-02-01T00:00:00Z"},
        ],
        "cohort_values": {
            "geographic_region":  "mid_atlantic",
            "age_decade":         "80s",
            "sex":                "M",
        },
    },
    {
        "local_record_id":      "amc-richmond-mrn-5544102",
        "given_name":           "Margaret",
        "family_name":          "Chen",
        "dob":                  "1955-09-22",
        "sex":                  "F",
        "address_line":         "412 Maple Ave",
        "city":                 "Richmond",
        "state":                "VA",
        "zip_code":             "23226",
        "phone":                "+18045552222",
        "ssn_last_4":           "1199",
        "deceased_status":      None,
        "death_event_history":  [],
        "active_appointments":  [],
        "active_prescriptions": [],
        "open_billing_episodes": [],
        "cohort_values": {
            "geographic_region":  "mid_atlantic",
            "age_decade":         "70s",
            "sex":                "F",
        },
    },
    # A duplicate-chain candidate for Robert Anderson: same
    # demographics under a different MRN that the institution's
    # internal matching has not surfaced. The death event from
    # an authoritative source will reveal the duplicate.
    {
        "local_record_id":      "amc-richmond-mrn-7782441",
        "given_name":           "Robert",
        "middle_name":          "J",
        "family_name":          "Anderson",
        "dob":                  "1942-05-14",
        "sex":                  "M",
        "address_line":         "1247 Oak Street",
        "city":                 "Richmond",
        "state":                "VA",
        "zip_code":             "23220",
        "phone":                "+18045551111",
        "ssn_last_4":           "4827",
        "deceased_status":      None,
        "death_event_history":  [],
        "active_appointments":  [
            {"appointment_id": "appt-99001",
             "scheduled_for":   "2026-03-15T11:00:00Z",
             "type":            "specialty_consult"},
        ],
        "active_prescriptions": [],
        "open_billing_episodes": [],
        "cohort_values": {
            "geographic_region":  "mid_atlantic",
            "age_decade":         "80s",
            "sex":                "M",
        },
    },
]

class MockLocalMPI:
    """Stand-in for Aurora PostgreSQL holding the institution's
    canonical patient identity records. Production has indexes
    on the demographic-feature blocking keys, full-text search,
    and per-record sensitivity flags. The deceased-patient-
    resolution pipeline consults this MPI through read access
    in the matcher and writes through the mpi-update-handler
    under a separate scoped role."""

    def __init__(self, records: list):
        self._records = {r["local_record_id"]: dict(r)
                            for r in records}

    def get(self, record_id: str) -> Optional[dict]:
        rec = self._records.get(record_id)
        return dict(rec) if rec else None

    def get_all(self) -> list:
        return [dict(r) for r in self._records.values()]

    def block_candidates(self, normalized_query: dict) -> list:
        """Light blocking-key candidate generation. Production
        uses indexes on (soundex(family_name), substring(dob,
        1, 4)) or similar blocking keys to reduce O(n) scans on
        the full MPI. The demo does a full scan."""
        return list(self._records.values())

    def update_record(self, record_id: str,
                          updates: dict) -> None:
        """Apply the death-status update to the MPI record.
        Production wraps in a transaction with the death-event-
        log write so the MPI's downstream consumers see a
        consistent state."""
        if record_id not in self._records:
            raise KeyError(f"record {record_id} not found")
        self._records[record_id].update(updates)

# --- Mock downstream operational systems ---
class MockDownstreamSystem:
    """Stand-in for an operational system that consumes the
    deceased-patient signal. Real production systems have their
    own APIs, their own audit logs, their own access controls;
    the cascade Lambda for each system handles the per-system
    integration. The mock just records what would have been
    done so the demo can show the cascade behavior."""

    def __init__(self, system_id: str):
        self.system_id = system_id
        self.actions: list = []

    def record_action(self, action: dict) -> None:
        self.actions.append({**action,
                              "applied_at": _now_iso()})

    def get_actions(self) -> list:
        return list(self.actions)

# --- In-memory stores standing in for DynamoDB tables ---
_DEATH_EVENT_LOG: dict = {}
_VERIFICATION_QUEUE: list = []
_CASCADE_ACK_STORE: list = []
_DUAL_CONTROL_APPROVALS: dict = {}

# --- Module-level singletons for the demo ---
local_mpi = MockLocalMPI(SYNTHETIC_LOCAL_MPI_RECORDS)
appointment_system    = MockDownstreamSystem("appointment-system")
prescription_system   = MockDownstreamSystem("prescription-system")
outreach_platform     = MockDownstreamSystem("outreach-platform")
billing_system        = MockDownstreamSystem("billing-system")
patient_portal        = MockDownstreamSystem("patient-portal")
care_management       = MockDownstreamSystem("care-management")
analytics_platform    = MockDownstreamSystem("analytics-platform")
cross_recipe_5_1      = MockDownstreamSystem("cross-recipe-5.1")
cross_recipe_5_5      = MockDownstreamSystem("cross-recipe-5.5")
cross_recipe_5_7      = MockDownstreamSystem("cross-recipe-5.7")
cross_recipe_5_8      = MockDownstreamSystem("cross-recipe-5.8")
cross_recipe_5_9      = MockDownstreamSystem("cross-recipe-5.9")

CASCADE_REGISTRY = {
    "appointment-system":  appointment_system,
    "prescription-system": prescription_system,
    "outreach-platform":   outreach_platform,
    "billing-system":      billing_system,
    "patient-portal":      patient_portal,
    "care-management":     care_management,
    "analytics-platform":  analytics_platform,
    "cross-recipe-5.1":    cross_recipe_5_1,
    "cross-recipe-5.5":    cross_recipe_5_5,
    "cross-recipe-5.7":    cross_recipe_5_7,
    "cross-recipe-5.8":    cross_recipe_5_8,
    "cross-recipe-5.9":    cross_recipe_5_9,
}
```

---

## Step 1: Ingest a Death Event from a Source Feed

*The pseudocode calls this `ingest_death_event_from_source(source_id, source_specific_record)`. A death event arrives from one of the institution's source feeds. The handler normalizes the source-specific format to the common death-event schema, captures the per-event provenance, persists the inbound event into the death-event log, and dispatches the event to the resolution pipeline. Skip the provenance capture and you cannot reverse premature death reports correctly later.*

```python
def ingest_death_event_from_source(
        source_id: str,
        source_specific_record: dict) -> str:
    """
    Normalize a source-specific death event to the common
    schema, capture provenance, persist, and dispatch to the
    matcher. Returns the event_id.
    """
    # Step 1A: load the per-source schema definition. The
    # demo's normalizer dispatches by source_id; production has
    # versioned schema definitions in the Glue Data Catalog.
    if source_id not in SOURCE_QUALITY_CLASSIFICATIONS:
        raise ValueError(
            f"unknown source {source_id}; reject ingestion")

    # Step 1B: normalize the source-specific record to the
    # common death-event schema. Per-source normalizers handle
    # the LADMF's fixed-width format, the per-state vital-
    # records FHIR format, the payer-feed format, the EHR-
    # internal format, and the family-reported intake's call-
    # center capture format.
    normalized_event = _normalize_to_common_schema(
        source_id, source_specific_record)

    # Step 1C: capture the per-event provenance. The provenance
    # carries the source identifier, the source-specific record
    # identifier, the source's submission timestamp, the
    # institution's ingestion timestamp, the source-quality
    # classification at the time of ingestion, and the
    # supporting-evidence reference where the source provides
    # one.
    provenance = {
        "source_id":              source_id,
        "source_record_id":       source_specific_record.get(
                                       "source_record_id"),
        "source_submission_timestamp":
            source_specific_record.get("submission_timestamp"),
        "institution_ingestion_timestamp": _now_iso(),
        "source_quality_classification":
            dict(SOURCE_QUALITY_CLASSIFICATIONS[source_id]),
        "supporting_evidence_reference":
            source_specific_record.get(
                "supporting_evidence_reference"),
    }

    # Step 1D: persist the inbound event into the death-event
    # log with the per-event provenance.
    event_id = f"death-event-{source_id[:8]}-{uuid.uuid4().hex[:12]}"
    _DEATH_EVENT_LOG[event_id] = {
        "event_id":          event_id,
        "normalized_event":  normalized_event,
        "provenance":        provenance,
        "resolution_status": RES_RECEIVED,
        "ingested_at":       _now_iso(),
        "matched_record_id": None,
        "all_matched_record_ids": [],
        "consolidated_view": None,
    }

    _audit_log({
        "event_type": "DEATH_EVENT_INGESTED",
        "event_id":   event_id,
        "source_id":  source_id,
        "demographic_payload_summary":
            _summarize_event_for_audit(normalized_event),
    })
    _emit_metric("DeathEventIngested", 1.0,
                  dimensions={"SourceId": source_id})

    # Step 1E: dispatch to the matcher (Step 2). Production
    # invokes the death-event-matcher Lambda asynchronously;
    # the demo calls the function directly.
    match_death_event_against_mpi(event_id)

    return event_id

def _normalize_to_common_schema(
        source_id: str,
        source_specific_record: dict) -> dict:
    """Per-source normalization. Production has a separate
    normalizer per source format; the demo collapses them into
    one function with source-specific branches."""
    # The source records arrive in source-specific formats; the
    # normalization extracts the common fields. The demo's
    # source records are already mostly normalized for
    # readability; production handles the LADMF's fixed-width
    # parsing, the FHIR VRDR Bundle parsing, the X12 271
    # eligibility-response parsing for payer feeds, and so on.
    normalized = {
        "given_name":   source_specific_record.get("given_name"),
        "middle_name":  source_specific_record.get("middle_name"),
        "family_name":  source_specific_record.get("family_name"),
        "dob":          source_specific_record.get("dob"),
        "sex":          source_specific_record.get("sex"),
        "address_line": source_specific_record.get("address_line"),
        "city":         source_specific_record.get("city"),
        "state":        source_specific_record.get("state"),
        "zip_code":     source_specific_record.get("zip_code"),
        "ssn_last_4":   source_specific_record.get("ssn_last_4"),
        "date_of_death": source_specific_record.get("date_of_death"),
        "state_of_death":
            source_specific_record.get("state_of_death"),
        "cause_of_death_underlying":
            source_specific_record.get("cause_of_death_underlying"),
        "death_certifier_identifier":
            source_specific_record.get("death_certifier_identifier"),
    }
    return normalized
```

---

## Step 2: Match the Death Event Against the MPI

*The pseudocode calls this `match_death_event_against_mpi(event_id)`. The matcher applies the per-source matching tolerance, generates candidates through the MPI's blocking step, scores per candidate, and routes the result based on confidence: high-confidence single match goes to multi-source reconciliation; multiple high-confidence matches indicate hidden-duplicate-revelation; medium-confidence matches go to the verification queue; no-match cases are parked. Skip the per-source tolerance calibration and you treat the SSA LADMF (high-quality demographics) the same as the family-reported intake (variable demographics), with the consequent matching-quality compromise.*

```python
def match_death_event_against_mpi(event_id: str) -> None:
    """
    Match a death event against the local MPI under the per-
    source matching tolerance. Routes the event to the
    appropriate next-stage handler based on confidence.
    """
    death_event = _DEATH_EVENT_LOG.get(event_id)
    if not death_event:
        raise KeyError(f"event {event_id} not found")

    source_id = death_event["provenance"]["source_id"]
    normalized = death_event["normalized_event"]

    # Step 2A: load the per-source matching tolerance.
    tolerance = SOURCE_MATCHING_TOLERANCE.get(
        source_id, SOURCE_MATCHING_TOLERANCE["family-reported-intake"])

    # Step 2B: candidate generation through the MPI's blocking
    # step. Production uses indexed blocking keys; the demo
    # iterates the MPI.
    blocked = local_mpi.block_candidates(normalized)

    # Step 2C: per-candidate scoring with the Fellegi-Sunter
    # combiner over the per-feature similarities.
    scored = []
    for mpi_record in blocked:
        per_feature_similarities = _compute_per_feature_similarities(
            normalized, mpi_record)
        match_score = _combine_with_fellegi_sunter(
            per_feature_similarities, FEATURE_WEIGHTS)
        if match_score >= tolerance["candidate_acceptance_threshold"]:
            confidence_tier = _classify_confidence_tier(
                match_score, tolerance)
            scored.append({
                "candidate_record_id":
                    mpi_record["local_record_id"],
                "match_score":         match_score,
                "match_confidence_tier": confidence_tier,
            })

    # Sort high-to-low so dominant candidate is index 0.
    scored.sort(key=lambda c: c["match_score"], reverse=True)
    scored = scored[:tolerance["max_candidate_count"]]

    # Step 2D: detect hidden-duplicate-revelation. If the match
    # produces multiple high-confidence candidates, the death
    # event has revealed a previously-hidden duplicate chain.
    high_confidence = [c for c in scored
                          if c["match_confidence_tier"]
                          == HIGH_CONFIDENCE]

    if len(high_confidence) > 1:
        # Hidden-duplicate-revelation case: route to the
        # coordinated-resolution pipeline (Step 3 will see the
        # hidden-duplicate flag and coordinate with recipe 5.1).
        duplicate_ids = [c["candidate_record_id"]
                            for c in high_confidence]
        _DEATH_EVENT_LOG[event_id]["resolution_status"] = (
            RES_HIDDEN_DUPLICATE)
        _DEATH_EVENT_LOG[event_id]["all_matched_record_ids"] = (
            duplicate_ids)

        _audit_log({
            "event_type": "HIDDEN_DUPLICATE_REVEALED_BY_DEATH_EVENT",
            "event_id":   event_id,
            "source_id":  source_id,
            "duplicate_candidate_ids": duplicate_ids,
        })
        _emit_metric("HiddenDuplicateRevealed", 1.0,
                      dimensions={"SourceId": source_id})

        # The hidden-duplicate-revealer Lambda runs the
        # coordinated resolution: signal recipe 5.1 to merge the
        # duplicates into a consolidated record, then continue
        # the death-event flow against the consolidated record.
        consolidated_record_id = handle_hidden_duplicate_revelation(
            event_id, duplicate_ids)
        _DEATH_EVENT_LOG[event_id]["matched_record_id"] = (
            consolidated_record_id)
        # Continue to multi-source reconciliation against the
        # consolidated record.
        reconcile_multi_source_death_events(
            event_id, consolidated_record_id)
        return

    # Step 2E: route based on the dominant candidate's
    # confidence.
    if not scored:
        # No-match: park the event for retrospective re-matching.
        _DEATH_EVENT_LOG[event_id]["resolution_status"] = (
            RES_NO_MATCH)
        _audit_log({
            "event_type": "DEATH_EVENT_NO_MATCH",
            "event_id":   event_id,
            "source_id":  source_id,
        })
        _emit_metric("DeathEventNoMatch", 1.0,
                      dimensions={"SourceId": source_id})
        return

    dominant = scored[0]
    _DEATH_EVENT_LOG[event_id]["matched_record_id"] = (
        dominant["candidate_record_id"])

    if dominant["match_confidence_tier"] == HIGH_CONFIDENCE:
        # Auto-resolution path: dispatch to the multi-source
        # reconciler (Step 3).
        reconcile_multi_source_death_events(
            event_id, dominant["candidate_record_id"])

    elif dominant["match_confidence_tier"] == MEDIUM_CONFIDENCE:
        # Verification-queue path: route to the human-review
        # queue.
        _DEATH_EVENT_LOG[event_id]["resolution_status"] = (
            RES_QUEUED_FOR_REVIEW)
        _VERIFICATION_QUEUE.append({
            "queue_event_id": uuid.uuid4().hex,
            "event_id":       event_id,
            "candidate_record_id": dominant["candidate_record_id"],
            "match_score":    dominant["match_score"],
            "verification_reason":
                "medium_confidence_match_review",
            "queued_at":      _now_iso(),
        })
        _audit_log({
            "event_type": "DEATH_EVENT_QUEUED_FOR_MATCH_REVIEW",
            "event_id":   event_id,
            "source_id":  source_id,
            "match_score": str(dominant["match_score"]),
        })
        _emit_metric("DeathEventQueuedForReview", 1.0,
                      dimensions={"SourceId": source_id,
                                    "Reason": "MediumConfidenceMatch"})

    else:
        # Low-confidence: park the event in the no-match
        # archive with the candidate set for audit.
        _DEATH_EVENT_LOG[event_id]["resolution_status"] = (
            RES_LOW_CONF_NO_MATCH)
        _audit_log({
            "event_type": "DEATH_EVENT_LOW_CONFIDENCE_NO_MATCH",
            "event_id":   event_id,
            "source_id":  source_id,
        })

def _compute_per_feature_similarities(query: dict,
                                          mpi_record: dict) -> dict:
    """Per-feature similarity scoring."""
    s = {}
    s["given_name"] = _jaro_winkler(
        _canonical_name(query.get("given_name")),
        _canonical_name(mpi_record.get("given_name")))
    s["family_name"] = _jaro_winkler(
        _canonical_name(query.get("family_name")),
        _canonical_name(mpi_record.get("family_name")))
    s["dob"] = (
        Decimal("1.0") if (query.get("dob")
                              and query.get("dob") ==
                              mpi_record.get("dob"))
        else Decimal("0.0"))
    s["address_line"] = _jaro_winkler(
        _normalize_address(query.get("address_line") or ""),
        _normalize_address(mpi_record.get("address_line") or ""))
    s["zip_code"] = (
        Decimal("1.0") if (query.get("zip_code")
                              and query.get("zip_code") ==
                              mpi_record.get("zip_code"))
        else Decimal("0.0"))
    s["ssn_last_4"] = (
        Decimal("1.0") if (query.get("ssn_last_4")
                              and query.get("ssn_last_4") ==
                              mpi_record.get("ssn_last_4"))
        else Decimal("0.0"))
    s["sex"] = (
        Decimal("1.0") if (query.get("sex")
                              and query.get("sex") ==
                              mpi_record.get("sex"))
        else Decimal("0.0"))
    return s

def _combine_with_fellegi_sunter(per_feature: dict,
                                      weights: dict) -> Decimal:
    """Weighted-sum combination across features. Production
    uses log-likelihood ratios with EM-trained per-feature
    m-and-u parameters."""
    weighted = Decimal("0")
    total = Decimal("0")
    for feature, sim in per_feature.items():
        w = weights.get(feature, Decimal("0"))
        weighted += w * sim
        total += w
    return weighted / total if total > 0 else Decimal("0")

def _classify_confidence_tier(match_score: Decimal,
                                  tolerance: dict) -> str:
    if match_score >= tolerance["high_confidence_threshold"]:
        return HIGH_CONFIDENCE
    if match_score >= tolerance["candidate_acceptance_threshold"]:
        return MEDIUM_CONFIDENCE
    return LOW_CONFIDENCE

def handle_hidden_duplicate_revelation(
        event_id: str, duplicate_ids: list) -> str:
    """
    Coordinate with recipe 5.1's duplicate-resolution pipeline.
    The death event has revealed a duplicate chain in the MPI;
    we merge the chain into a consolidated record before
    applying the death status. Production fires an
    EventBridge event to recipe 5.1's resolver and waits for
    the consolidation acknowledgment; the demo synthesizes the
    consolidation inline.
    """
    # The demo picks the first record as the consolidated
    # target and signals recipe 5.1 to merge the others into
    # it. Production has a deterministic survivor-record
    # selection rule (lowest local_record_id, or the record
    # with the most clinical data, or the institutional rule).
    survivor_id = sorted(duplicate_ids)[0]
    merged_into = [d for d in duplicate_ids if d != survivor_id]

    # Signal recipe 5.1 (the cross-recipe consumer for internal
    # duplicates).
    cross_recipe_5_1.record_action({
        "action":       "merge_duplicate_chain",
        "event_id":     event_id,
        "survivor_record_id": survivor_id,
        "merged_record_ids":  merged_into,
        "reason":       "death_event_revealed_duplicates",
    })

    _audit_log({
        "event_type": "HIDDEN_DUPLICATE_RESOLUTION_COORDINATED",
        "event_id":   event_id,
        "survivor_record_id": survivor_id,
        "merged_record_ids":  merged_into,
    })

    return survivor_id
```

---

## Step 3: Reconcile Multi-Source Death Events

*The pseudocode calls this `reconcile_multi_source_death_events(event_id, matched_record_id)`. The reconciler combines per-source events for the same patient into a consolidated death-event view, applies the date-of-death-conflict-resolution policy, detects premature-death-report candidates (single-source death events without corroboration from sources with non-trivial premature-death-report rates), and produces the consolidated view that the MPI will consume. Skip the multi-source reconciliation and you collapse multiple sources to a single source's view with the consequent quality compromise.*

```python
def reconcile_multi_source_death_events(
        event_id: str, matched_record_id: str) -> None:
    """
    Reconcile the new death event against any prior death
    events for the same matched record. Apply the date-of-death
    conflict policy; detect premature-death-report candidates;
    build the consolidated death-event view; dispatch to the
    MPI-update handler.
    """
    new_event = _DEATH_EVENT_LOG.get(event_id)
    prior_events = _query_prior_events_for_record(
        matched_record_id, exclude_event_id=event_id)
    all_events = prior_events + [new_event]

    # Step 3A: apply the date-of-death-conflict-resolution
    # policy.
    consolidated_dates = _compute_consolidated_dates(all_events)

    # Threshold-exceeded conflicts route to human review.
    if consolidated_dates.get("date_of_death_conflict_flagged"):
        _DEATH_EVENT_LOG[event_id]["resolution_status"] = (
            RES_DATE_CONFLICT)
        _DEATH_EVENT_LOG[event_id]["consolidated_view"] = {
            "consolidated_dates": consolidated_dates}
        _VERIFICATION_QUEUE.append({
            "queue_event_id": uuid.uuid4().hex,
            "event_id":       event_id,
            "matched_record_id": matched_record_id,
            "verification_reason":
                "date_of_death_conflict",
            "consolidated_dates": consolidated_dates,
            "queued_at":      _now_iso(),
        })
        _audit_log({
            "event_type":
                "DEATH_EVENT_DATE_CONFLICT_FLAGGED",
            "event_id":   event_id,
            "matched_record_id": matched_record_id,
            "consolidated_dates_summary":
                _summarize_dates(consolidated_dates),
        })
        _emit_metric("DateOfDeathConflictFlagged", 1.0,
                      dimensions={"SourceId":
                          new_event["provenance"]["source_id"]})
        return

    # Step 3B: premature-death-report detection. If the new
    # event is from a source with a non-trivial premature-
    # death-report rate AND has no corroboration from other
    # sources, route to verification before applying the death
    # status.
    new_source_id = new_event["provenance"]["source_id"]
    new_source_quality = new_event["provenance"][
        "source_quality_classification"]

    is_high_premature_rate = _to_decimal(
        new_source_quality["premature_death_report_rate_baseline"]
    ) > PREMATURE_DEATH_REPORT_VERIFICATION_THRESHOLD
    has_no_corroboration = len(prior_events) == 0

    if is_high_premature_rate and has_no_corroboration:
        _DEATH_EVENT_LOG[event_id]["resolution_status"] = (
            RES_PREMATURE_FLAGGED)
        _VERIFICATION_QUEUE.append({
            "queue_event_id": uuid.uuid4().hex,
            "event_id":       event_id,
            "matched_record_id": matched_record_id,
            "verification_reason":
                "premature_death_report_candidate",
            "queued_at":      _now_iso(),
        })
        _audit_log({
            "event_type":
                "DEATH_EVENT_PREMATURE_REPORT_FLAGGED",
            "event_id":   event_id,
            "source_id":  new_source_id,
            "matched_record_id": matched_record_id,
        })
        _emit_metric("PrematureDeathReportFlagged", 1.0,
                      dimensions={"SourceId": new_source_id})
        return

    # Step 3C: build the consolidated death-event view.
    consolidated_view = {
        "consolidated_dates": consolidated_dates,
        "per_source_provenance": [
            {
                "source_id":
                    e["provenance"]["source_id"],
                "source_record_id":
                    e["provenance"]["source_record_id"],
                "supporting_document_certainty":
                    e["provenance"][
                        "source_quality_classification"][
                        "supporting_document_certainty"],
                "received_at":
                    e["provenance"][
                        "institution_ingestion_timestamp"],
            }
            for e in all_events
        ],
        "consolidated_source_count": len(all_events),
        "premature_death_report_candidate": False,
        "hidden_duplicate_revelation_count": 0,
        "consolidated_at": _now_iso(),
    }

    _DEATH_EVENT_LOG[event_id]["consolidated_view"] = (
        consolidated_view)

    _audit_log({
        "event_type": "DEATH_EVENT_RECONCILED",
        "event_id":   event_id,
        "matched_record_id": matched_record_id,
        "consolidated_source_count": len(all_events),
    })
    _emit_metric("DeathEventReconciled", 1.0,
                  dimensions={"SourceId": new_source_id,
                                "SourceCount": str(len(all_events))})

    # Step 3D: dispatch to the MPI-update handler (Step 4).
    apply_death_status_to_mpi(
        event_id, matched_record_id, consolidated_view)

def _query_prior_events_for_record(matched_record_id: str,
                                          exclude_event_id: str = None
                                          ) -> list:
    """Query prior death events that resolved against the same
    matched record. Production indexes the death-event-log by
    matched_record_id with a GSI; the demo iterates."""
    return [
        e for e in _DEATH_EVENT_LOG.values()
        if e.get("matched_record_id") == matched_record_id
        and e.get("event_id") != exclude_event_id
        and e.get("resolution_status") in (
            RES_APPLIED, RES_RECEIVED)
    ]

def _compute_consolidated_dates(all_events: list) -> dict:
    """Apply the per-use-case date-of-death selection policy."""
    per_source_dates = {}
    valid_dates = []
    for event in all_events:
        sid = event["provenance"]["source_id"]
        dod = event["normalized_event"].get("date_of_death")
        if dod:
            per_source_dates[sid] = dod
            valid_dates.append((sid, dod))

    if not valid_dates:
        return {"date_of_death_conflict_flagged": False,
                "per_source_dates": {}}

    # Default-date selection: pick the source with the highest
    # authority ranking that has a date.
    default_date = None
    for authoritative_source in SOURCE_DATE_AUTHORITY_RANKING:
        if authoritative_source in per_source_dates:
            default_date = per_source_dates[authoritative_source]
            break
    if not default_date:
        default_date = valid_dates[0][1]

    # Legal-billing date: prefer the death-certificate source
    # (state vital records); fall back to default.
    legal_billing_date = None
    for sid, dod in valid_dates:
        if SOURCE_QUALITY_CLASSIFICATIONS[sid].get(
                "authoritative_for_legal_billing"):
            legal_billing_date = dod
            break
    if not legal_billing_date:
        legal_billing_date = default_date

    # Clinical-event-timing: prefer EHR-internal; fall back to
    # default.
    clinical_event_timing_date = per_source_dates.get(
        "ehr-internal", default_date)

    # Earliest-plausible-date: minimum across all sources.
    earliest_plausible_date = min(
        (dod for _, dod in valid_dates),
        key=lambda d: _parse_iso_date(d) or datetime.max.replace(
            tzinfo=timezone.utc))

    # Conflict detection: flag if any pair of dates differs by
    # more than the threshold.
    conflict_flagged = False
    dates_only = [dod for _, dod in valid_dates]
    for i in range(len(dates_only)):
        for j in range(i + 1, len(dates_only)):
            diff = _days_between(dates_only[i], dates_only[j])
            if diff is not None and diff > DATE_CONFLICT_THRESHOLD_DAYS:
                conflict_flagged = True
                break
        if conflict_flagged:
            break

    return {
        "legal_billing_date":         legal_billing_date,
        "clinical_event_timing_date": clinical_event_timing_date,
        "earliest_plausible_date":    earliest_plausible_date,
        "default_date":               default_date,
        "date_of_death_conflict_flagged": conflict_flagged,
        "per_source_dates":           per_source_dates,
    }

def _summarize_dates(consolidated_dates: dict) -> dict:
    return {
        "default_date": consolidated_dates.get("default_date"),
        "source_count":
            len(consolidated_dates.get("per_source_dates") or {}),
        "conflict_flagged":
            consolidated_dates.get("date_of_death_conflict_flagged"),
    }
```

---

## Step 4: Apply the Death-Status Update to the MPI Atomically

*The pseudocode calls this `apply_death_status_to_mpi(event_id, matched_record_id, consolidated_view)`. The handler executes the death-status application as a transactional write that includes the MPI-record update, the death-event-log update, and the audit-event emission. The transaction ensures the MPI's downstream consumers see a consistent state. Skip the transactional discipline and you produce inconsistent operational behavior across systems that consume the MPI's death-status field at slightly different moments. After the MPI update, the EventBridge fan-out triggers Step 5's downstream cascade.*

```python
def apply_death_status_to_mpi(
        event_id: str, matched_record_id: str,
        consolidated_view: dict) -> None:
    """
    Apply the death-status update to the MPI as a transactional
    write. Emit the deceased-patient-event signal to the
    EventBridge fan-out, which drives the downstream cascade.
    """
    current_record = local_mpi.get(matched_record_id)
    if not current_record:
        raise KeyError(
            f"matched record {matched_record_id} not found")

    # Step 4A: build the updated record state. The death-event
    # history list is appended; the computed deceased status is
    # set; per-source provenance is captured.
    new_history_entry = {
        "event_id":          event_id,
        "applied_at":        _now_iso(),
        "consolidated_view": consolidated_view,
    }
    death_event_history = list(
        current_record.get("death_event_history") or [])
    death_event_history.append(new_history_entry)

    deceased_status = {
        "is_deceased":           True,
        "consolidated_dates":
            consolidated_view["consolidated_dates"],
        "per_source_provenance":
            consolidated_view["per_source_provenance"],
        "applied_event_ids":
            [h["event_id"] for h in death_event_history],
        "applied_at":            _now_iso(),
    }

    updates = {
        "deceased_status":      deceased_status,
        "death_event_history":  death_event_history,
    }

    # Step 4B: execute the transactional write. Production wraps
    # the MPI update, the death-event-log status update, and
    # the EventBridge emission in a TransactWriteItems
    # operation. The demo applies them in sequence and rolls
    # back the MPI update if a downstream step fails.
    pre_update_snapshot = dict(current_record)
    try:
        local_mpi.update_record(matched_record_id, updates)
        _DEATH_EVENT_LOG[event_id]["resolution_status"] = (
            RES_APPLIED)
        _DEATH_EVENT_LOG[event_id]["applied_at"] = _now_iso()
    except Exception as exc:
        # Rollback the MPI update; the demo's MockLocalMPI does
        # not actually need this because it raised before the
        # update, but production handles partial failures.
        logger.error("MPI update transaction failed",
                      extra={"event_id": event_id,
                              "error": str(exc)})
        _audit_log({
            "event_type":
                "DEATH_EVENT_TRANSACTION_FAILED",
            "event_id":   event_id,
            "matched_record_id": matched_record_id,
            "error":      str(exc),
        })
        raise

    # Step 4C: emit the deceased-patient-event signal to the
    # EventBridge fan-out. The signal carries the event id, the
    # matched record id, the consolidated date of death, the
    # per-source provenance, and the cross-recipe coordination
    # metadata.
    legal_dod = consolidated_view["consolidated_dates"][
        "legal_billing_date"]
    deceased_event_detail = {
        "event_id":                event_id,
        "matched_record_id":       matched_record_id,
        "consolidated_date_of_death": legal_dod,
        "per_source_provenance":
            consolidated_view["per_source_provenance"],
        "applied_at":              _now_iso(),
        "matcher_config_version":  MATCHER_CONFIG_VERSION,
        "tolerance_version":       SOURCE_TOLERANCE_VERSION,
        "conflict_policy_version": CONFLICT_POLICY_VERSION,
    }

    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "deceased-patient-resolution",
            "DetailType":   "deceased_patient_resolved",
            "EventBusName": DECEASED_EVENT_BUS_NAME,
            "Detail":       json.dumps(
                deceased_event_detail, default=str),
        }])
    except Exception as exc:
        logger.info("event emit skipped (demo mode)",
                     extra={"error": str(exc)})

    _audit_log({
        "event_type": "DEATH_EVENT_APPLIED",
        "event_id":   event_id,
        "matched_record_id": matched_record_id,
        "consolidated_date_of_death": legal_dod,
    })
    _emit_metric("DeathEventApplied", 1.0,
                  dimensions={"SourceId":
                      _DEATH_EVENT_LOG[event_id][
                          "provenance"]["source_id"]})

    # Step 4D: drive the downstream cascade (Step 5).
    # Production: EventBridge rules route the event to each
    # cascade Lambda. Demo: invoke the cascade dispatcher
    # directly so the trace is easy to follow.
    propagate_to_downstream_systems(deceased_event_detail)
```

---

## Step 5: Propagate the Death Status to Downstream Systems

*The pseudocode calls these `cascade_appointment_cancellation`, `cascade_active_prescription_review`, `cascade_communication_path_switch`, `cascade_billing_episode_closure`, `cascade_portal_access_handler`, and the cross-recipe coordination Lambdas. Each cascade Lambda consumes the `deceased_patient_resolved` EventBridge event and applies the system-specific behavior change at the appropriate cadence. Each cascade emits an acknowledgment back to the cascade-ack-store. Skip the per-system cadence configuration and you apply the cascade at the wrong cadence for some systems. The cross-recipe coordination signals (recipes 5.1, 5.5, 5.7, 5.8, 5.9) propagate through the same fan-out so the chapter's recipes maintain consistent deceased-patient handling.*

```python
def propagate_to_downstream_systems(
        deceased_event_detail: dict) -> dict:
    """
    Dispatch each downstream-cascade Lambda. Each Lambda
    applies the per-system behavior change and emits an
    acknowledgment to the cascade-ack-store. Returns the
    cross-system propagation completeness summary.
    """
    event_id = deceased_event_detail["event_id"]
    matched_record_id = deceased_event_detail["matched_record_id"]
    dod = deceased_event_detail["consolidated_date_of_death"]

    cascade_handlers = [
        ("appointment-system",
         cascade_appointment_cancellation),
        ("prescription-system",
         cascade_active_prescription_review),
        ("outreach-platform",
         cascade_communication_path_switch),
        ("billing-system",
         cascade_billing_episode_closure),
        ("patient-portal",
         cascade_portal_access_handler),
        ("care-management",
         cascade_care_management_panel_removal),
        ("analytics-platform",
         cascade_analytics_platform_handler),
        ("cross-recipe-5.5",
         lambda *args: cascade_cross_recipe_signal("5.5", *args)),
        ("cross-recipe-5.7",
         lambda *args: cascade_cross_recipe_signal("5.7", *args)),
        ("cross-recipe-5.8",
         lambda *args: cascade_cross_recipe_signal("5.8", *args)),
        ("cross-recipe-5.9",
         lambda *args: cascade_cross_recipe_signal("5.9", *args)),
    ]

    for consumer_id, handler in cascade_handlers:
        try:
            handler(event_id, matched_record_id, dod)
        except Exception as exc:
            # In production, the cascade Lambda's own DLQ would
            # catch the failure; the demo logs and continues so
            # the trace shows partial completion behavior.
            logger.error("cascade failed",
                          extra={"consumer": consumer_id,
                                  "error": str(exc)})
            _audit_log({
                "event_type": "CASCADE_FAILED",
                "event_id":   event_id,
                "consumer":   consumer_id,
                "error":      str(exc),
            })

    return _summarize_cascade_completeness(event_id)

def cascade_appointment_cancellation(
        event_id: str, matched_record_id: str,
        date_of_death: str) -> None:
    """
    Cancel future appointments and suppress automated reminders.
    Real-time cadence: appointments scheduled for tomorrow have
    their automated reminders going out today, and the family
    experience of a wrong-patient reminder is acutely negative.
    """
    record = local_mpi.get(matched_record_id) or {}
    future_appointments = [
        a for a in (record.get("active_appointments") or [])
        if (_parse_iso_date(a.get("scheduled_for"))
            and _parse_iso_date(a.get("scheduled_for"))
            > (_parse_iso_date(date_of_death) or datetime.now(
                timezone.utc)))
    ]

    for appointment in future_appointments:
        appointment_system.record_action({
            "action":            "cancel_appointment",
            "appointment_id":    appointment["appointment_id"],
            "cancellation_reason": "deceased_patient",
            "matched_record_id": matched_record_id,
            "event_id":          event_id,
        })

    appointment_system.record_action({
        "action":            "suppress_reminders",
        "matched_record_id": matched_record_id,
        "event_id":          event_id,
    })

    _CASCADE_ACK_STORE.append({
        "event_id":           event_id,
        "cascade_consumer":   "appointment-system",
        "completed_at":       _now_iso(),
        "appointments_cancelled":
            len(future_appointments),
    })

    _audit_log({
        "event_type":
            "CASCADE_APPOINTMENT_CANCELLATION_APPLIED",
        "event_id":   event_id,
        "matched_record_id": matched_record_id,
        "appointments_cancelled":
            len(future_appointments),
    })
    _emit_metric("AppointmentsCancelled",
                  float(len(future_appointments)))

def cascade_active_prescription_review(
        event_id: str, matched_record_id: str,
        date_of_death: str) -> None:
    """
    Cancel auto-refill loops and flag prescriptions requiring
    clinical disposition. Some prescription dispositions
    (controlled substances, in-process mail-order packages)
    require explicit clinical sign-off rather than auto-
    cancellation.
    """
    record = local_mpi.get(matched_record_id) or {}
    active_prescriptions = list(
        record.get("active_prescriptions") or [])

    cancelled_count = 0
    flagged_count = 0
    for prescription in active_prescriptions:
        # Cancel the auto-refill loop. New refills are blocked
        # immediately.
        prescription_system.record_action({
            "action":          "cancel_auto_refill",
            "prescription_id": prescription["prescription_id"],
            "drug_name":       prescription.get("drug_name"),
            "cancellation_reason": "deceased_patient",
            "matched_record_id": matched_record_id,
            "event_id":        event_id,
        })
        cancelled_count += 1

        # Flag for clinical review where the prescription
        # requires it.
        if prescription.get("requires_review"):
            prescription_system.record_action({
                "action":          "flag_for_clinical_review",
                "prescription_id": prescription["prescription_id"],
                "drug_name":       prescription.get("drug_name"),
                "review_reason":
                    "deceased_patient_prescription_disposition",
                "event_id":        event_id,
            })
            flagged_count += 1

    _CASCADE_ACK_STORE.append({
        "event_id":           event_id,
        "cascade_consumer":   "prescription-system",
        "completed_at":       _now_iso(),
        "active_prescriptions_processed": cancelled_count,
        "flagged_for_review": flagged_count,
    })

    _audit_log({
        "event_type": "CASCADE_PRESCRIPTION_REVIEW_APPLIED",
        "event_id":   event_id,
        "matched_record_id": matched_record_id,
        "cancelled":  cancelled_count,
        "flagged":    flagged_count,
    })

def cascade_communication_path_switch(
        event_id: str, matched_record_id: str,
        date_of_death: str) -> None:
    """
    Stop default communications and switch to the bereavement-
    aware path. The path is opt-in: the institution does not
    assume bereavement-aware contact authorization without an
    explicit family signal.
    """
    outreach_platform.record_action({
        "action":          "suppress_default_communications",
        "matched_record_id": matched_record_id,
        "event_id":        event_id,
        "suppression_reason": "deceased_patient",
    })

    outreach_platform.record_action({
        "action":          "initialize_bereavement_aware_path",
        "matched_record_id": matched_record_id,
        "event_id":        event_id,
        "date_of_death":   date_of_death,
    })

    _CASCADE_ACK_STORE.append({
        "event_id":         event_id,
        "cascade_consumer": "outreach-platform",
        "completed_at":     _now_iso(),
    })

    _audit_log({
        "event_type": "CASCADE_COMMUNICATION_PATH_SWITCHED",
        "event_id":   event_id,
        "matched_record_id": matched_record_id,
    })

def cascade_billing_episode_closure(
        event_id: str, matched_record_id: str,
        date_of_death: str) -> None:
    """
    Close open episodes-of-care and apply post-death billing
    treatment. Near-real-time cadence (within an hour); not as
    urgent as appointment cancellation.
    """
    record = local_mpi.get(matched_record_id) or {}
    open_episodes = list(
        record.get("open_billing_episodes") or [])

    for episode in open_episodes:
        billing_system.record_action({
            "action":          "close_episode",
            "episode_id":      episode["episode_id"],
            "closure_reason":  "deceased_patient",
            "matched_record_id": matched_record_id,
            "event_id":        event_id,
            "date_of_death":   date_of_death,
        })

    billing_system.record_action({
        "action":          "route_to_estate_administration",
        "matched_record_id": matched_record_id,
        "event_id":        event_id,
    })

    _CASCADE_ACK_STORE.append({
        "event_id":         event_id,
        "cascade_consumer": "billing-system",
        "completed_at":     _now_iso(),
        "open_episodes_closed": len(open_episodes),
    })

def cascade_portal_access_handler(
        event_id: str, matched_record_id: str,
        date_of_death: str) -> None:
    """
    Suspend the patient's own portal account; the personal-
    representative's access is provisioned through the
    institutional release-of-information process (separate
    workflow).
    """
    patient_portal.record_action({
        "action":          "suspend_patient_account",
        "matched_record_id": matched_record_id,
        "event_id":        event_id,
        "suspension_reason": "deceased_patient",
    })

    _CASCADE_ACK_STORE.append({
        "event_id":         event_id,
        "cascade_consumer": "patient-portal",
        "completed_at":     _now_iso(),
    })

def cascade_care_management_panel_removal(
        event_id: str, matched_record_id: str,
        date_of_death: str) -> None:
    """
    Remove the patient from active care-management panels.
    """
    care_management.record_action({
        "action":          "remove_from_active_panels",
        "matched_record_id": matched_record_id,
        "event_id":        event_id,
    })

    _CASCADE_ACK_STORE.append({
        "event_id":         event_id,
        "cascade_consumer": "care-management",
        "completed_at":     _now_iso(),
    })

def cascade_analytics_platform_handler(
        event_id: str, matched_record_id: str,
        date_of_death: str) -> None:
    """
    Mark the record for deceased-patient handling on the next
    analytics run. Batch cadence: the analytics platform
    refreshes nightly and applies the per-measure deceased-
    patient handling at refresh time.
    """
    analytics_platform.record_action({
        "action":          "mark_for_deceased_handling",
        "matched_record_id": matched_record_id,
        "event_id":        event_id,
        "date_of_death":   date_of_death,
    })

    _CASCADE_ACK_STORE.append({
        "event_id":         event_id,
        "cascade_consumer": "analytics-platform",
        "completed_at":     _now_iso(),
    })

def cascade_cross_recipe_signal(
        recipe_number: str, event_id: str,
        matched_record_id: str, date_of_death: str) -> None:
    """
    Signal the cross-recipe consumer with the appropriate
    per-recipe envelope. Each cross-recipe consumer
    (recipes 5.1, 5.5, 5.7, 5.8, 5.9) has its own appropriate
    behavior change on death events.
    """
    consumer_id = f"cross-recipe-{recipe_number}"
    consumer = CASCADE_REGISTRY[consumer_id]
    consumer.record_action({
        "action":          f"deceased_patient_signal_for_recipe_{recipe_number}",
        "matched_record_id": matched_record_id,
        "event_id":        event_id,
        "date_of_death":   date_of_death,
    })

    _CASCADE_ACK_STORE.append({
        "event_id":         event_id,
        "cascade_consumer": consumer_id,
        "completed_at":     _now_iso(),
    })

def _summarize_cascade_completeness(event_id: str) -> dict:
    """Compute the cross-system-propagation-completeness for
    the event. Production tracks expected consumers from the
    cascade-consumer registry; the demo uses CASCADE_REGISTRY
    as the expected set."""
    expected_consumers = set(CASCADE_CONSUMER_CONFIG.keys()) - {
        "cross-recipe-5.1"  # handled in hidden-duplicate flow
    }
    completed = {
        ack["cascade_consumer"]
        for ack in _CASCADE_ACK_STORE
        if ack["event_id"] == event_id
    }
    completeness = (len(completed & expected_consumers)
                       / max(len(expected_consumers), 1))
    return {
        "event_id":            event_id,
        "expected_consumers":  sorted(expected_consumers),
        "completed_consumers": sorted(completed),
        "completeness_pct":    int(completeness * 100),
    }
```

---

## Step 6: Handle Premature-Death-Report Verification and Reversal

*The pseudocode calls this `execute_premature_death_report_reversal(event_id, matched_record_id, verifier_identity, reversal_reason)`. The verification queue surfaces cases where the death status may be wrongly applied. The verifier reviews the case, applies the institutional verification framework, and produces the verification decision. If the death report is verified, the resolution proceeds; if the death report is reversed, the reversal pathway restores the live-patient state with full audit trail and dual-control approval. Skip the verification framework and you produce the disrupted-patient-experience cases the recipe is for.*

```python
def queue_dual_control_approval(
        event_id: str, action_type: str,
        approver_identity: dict) -> None:
    """
    Capture a dual-control approval from one of the two
    operators required to authorize a premature-death-report
    reversal. Production has a separate approval-workflow
    surface; the demo accumulates approvers in memory.
    """
    org_unit = approver_identity.get("organizational_unit")
    if not org_unit:
        raise ValueError(
            "approver must have an organizational_unit")
    key = (event_id, action_type)
    approvers = _DUAL_CONTROL_APPROVALS.setdefault(key, [])
    approvers.append({
        "approver_identity": approver_identity,
        "approved_at":       _now_iso(),
    })

    _audit_log({
        "event_type": "DUAL_CONTROL_APPROVAL_RECORDED",
        "event_id":   event_id,
        "action_type": action_type,
        "approver_identity":
            _summarize_for_audit(approver_identity),
        "approvals_collected": len(approvers),
    })

def _verify_dual_control_approval(
        event_id: str, action_type: str) -> bool:
    """Two operators from non-overlapping organizational units
    must approve."""
    approvers = _DUAL_CONTROL_APPROVALS.get(
        (event_id, action_type), [])
    if len(approvers) < 2:
        return False
    org_units = {
        a["approver_identity"].get("organizational_unit")
        for a in approvers}
    return len(org_units) >= 2

def _validate_verifier_authorization(verifier_identity: dict,
                                          action_type: str) -> bool:
    """The verifier role is institutionally-named and
    specifically-authorized. Production consults the IAM-and-
    role-attribution layer; the demo accepts any role with
    `deceased_patient_resolution_verifier` in the role list."""
    if not verifier_identity:
        return False
    roles = verifier_identity.get("roles") or []
    return "deceased_patient_resolution_verifier" in roles

def execute_premature_death_report_reversal(
        event_id: str, matched_record_id: str,
        verifier_identity: dict,
        reversal_reason: str) -> None:
    """
    Reverse a premature death report. The reversal restores the
    live-patient state but retains the audit history of the
    death-event-application and the reversal. Triggers reversal
    cascades to all downstream consumers that applied the
    deceased status.
    """
    # Step 6A: validate the verifier's authorization.
    if not _validate_verifier_authorization(
            verifier_identity, "premature_death_report_reversal"):
        _audit_log({
            "event_type":
                "REVERSAL_AUTHORIZATION_REJECTED",
            "event_id":   event_id,
            "verifier_identity":
                _summarize_for_audit(verifier_identity),
        })
        raise PermissionError(
            "verifier not authorized for reversal")

    # Step 6B: validate the dual-control approval.
    if not _verify_dual_control_approval(
            event_id, "premature_death_report_reversal"):
        _audit_log({
            "event_type":
                "REVERSAL_DUAL_CONTROL_INCOMPLETE",
            "event_id":   event_id,
        })
        raise PermissionError(
            "dual-control approval incomplete (need two "
            "approvers from non-overlapping organizational "
            "units)")

    # Step 6C: load current MPI record.
    current_record = local_mpi.get(matched_record_id)
    if not current_record:
        raise KeyError(
            f"record {matched_record_id} not found")

    # Step 6D: apply the reversal. The deceased_status field is
    # cleared but the death-event-history retains the original
    # event with a reversal annotation so the audit trail
    # captures the false-positive history.
    history = list(current_record.get("death_event_history")
                       or [])
    if history:
        history[-1] = {
            **history[-1],
            "reversed":      True,
            "reversed_at":   _now_iso(),
            "reversal_reason": reversal_reason,
            "reversed_by":
                _summarize_for_audit(verifier_identity),
        }

    reverted_updates = {
        "deceased_status":     None,
        "death_event_history": history,
    }
    local_mpi.update_record(matched_record_id, reverted_updates)

    _DEATH_EVENT_LOG[event_id]["resolution_status"] = (
        RES_REVERSED)
    _DEATH_EVENT_LOG[event_id]["reversal_reason"] = (
        reversal_reason)
    _DEATH_EVENT_LOG[event_id]["reversed_at"] = _now_iso()

    # Step 6E: emit the reversal event for the cascade-reversal
    # consumers. Each downstream system has its own reversal
    # protocol; the cascade-Lambda fan-out propagates the
    # reversal so the system can re-activate the patient's
    # operational state.
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "deceased-patient-resolution",
            "DetailType":   "deceased_status_reversed",
            "EventBusName": DECEASED_EVENT_BUS_NAME,
            "Detail":       json.dumps({
                "event_id":            event_id,
                "matched_record_id":   matched_record_id,
                "reversal_reason":     reversal_reason,
                "verifier_identity":
                    _summarize_for_audit(verifier_identity),
                "reversed_at":         _now_iso(),
            }, default=str),
        }])
    except Exception as exc:
        logger.info("reversal event emit skipped (demo mode)",
                     extra={"error": str(exc)})

    # Step 6F: propagate the reversal to all downstream
    # consumers that previously received the deceased event.
    propagate_reversal_to_downstream_systems(
        event_id, matched_record_id)

    _audit_log({
        "event_type":     "DEATH_EVENT_REVERSED",
        "event_id":       event_id,
        "matched_record_id": matched_record_id,
        "reversal_reason": reversal_reason,
        "verifier_identity":
            _summarize_for_audit(verifier_identity),
    })
    _emit_metric("DeathEventReversed", 1.0,
                  dimensions={"Reason": reversal_reason})

def propagate_reversal_to_downstream_systems(
        event_id: str, matched_record_id: str) -> None:
    """Each downstream system has a reversal protocol that
    re-activates the patient's operational state. The demo
    records reversal actions on each system."""
    for consumer_id, consumer in CASCADE_REGISTRY.items():
        consumer.record_action({
            "action":          "reverse_deceased_status",
            "matched_record_id": matched_record_id,
            "event_id":        event_id,
            "reversed_at":     _now_iso(),
        })
        _CASCADE_ACK_STORE.append({
            "event_id":         event_id,
            "cascade_consumer": consumer_id,
            "completed_at":     _now_iso(),
            "reversal":         True,
        })
```

---

## Full Pipeline

The pipeline assembles the six steps into representative end-to-end flows. In production these are separate Lambdas and Step Functions running in separate AWS accounts under cross-account access policies; here we run them in-process so the trace is easy to follow.

```python
def run_demo():
    """Run four representative deceased-patient-resolution
    flows: a multi-source-corroborated death (vital records
    arrives first, LADMF arrives later), a hidden-duplicate-
    revelation case (death event matches multiple MPI records),
    a premature-death-report case (single-source LADMF event
    that lacks corroboration), and a reversal of the premature
    death report by the verification operator."""
    global local_mpi
    print("=" * 72)
    print("Deceased Patient Resolution and Record Reconciliation Demo")
    print("=" * 72)
    print()
    print("All patients, demographics, sources, and identifiers in this")
    print("demo are fictional. The mock LADMF, state vital-records feed,")
    print("payer feed, EHR-internal source, and family-reported intake")
    print("return hand-crafted death events that exercise the ingestion,")
    print("matching, reconciliation, MPI-update, cascade, and reversal")
    print("paths; do not point this demo at the SSA's data exchange.")
    print()
    print(f"Institution:           {INSTITUTION_ID}")
    print(f"Institution juris:     {INSTITUTION_JURISDICTION}")
    print(f"Matcher config:        {MATCHER_CONFIG_VERSION}")
    print(f"Tolerance config:      {SOURCE_TOLERANCE_VERSION}")
    print(f"Conflict policy:       {CONFLICT_POLICY_VERSION}")
    print()

    # --- Flow 1: multi-source-corroborated death ---
    print("-" * 72)
    print("Flow 1: state vital-records death event arrives, then LADMF")
    print("        arrives later for the same patient (corroboration)")
    print("-" * 72)

    vrf_event_id = ingest_death_event_from_source(
        source_id="state-vital-records-virginia",
        source_specific_record={
            "source_record_id": "va-dc-2026-02-008-44521",
            "submission_timestamp": "2026-02-15T14:22:00Z",
            "given_name":   "Robert",
            "middle_name":  "James",
            "family_name":  "Anderson",
            "dob":          "1942-05-14",
            "sex":          "M",
            "address_line": "1247 Oak St",
            "city":         "Richmond",
            "state":        "VA",
            "zip_code":     "23220",
            "ssn_last_4":   "4827",
            "date_of_death": "2026-02-08",
            "state_of_death": "VA",
            "cause_of_death_underlying": "I25.10",
            "death_certifier_identifier": "npi-1234567890",
            "supporting_evidence_reference":
                "s3://vital-records-archive/va/2026/02/dc-2026-02-008-44521.pdf",
        })
    print(f"  vrf event_id:      {vrf_event_id}")
    vrf_record = _DEATH_EVENT_LOG[vrf_event_id]
    print(f"  resolution_status: {vrf_record['resolution_status']}")
    print(f"  matched_record_id: {vrf_record['matched_record_id']}")
    if vrf_record["consolidated_view"]:
        cd = vrf_record["consolidated_view"]["consolidated_dates"]
        print(f"  legal_billing_dod: {cd['legal_billing_date']}")
        print(f"  source_count:      "
              f"{vrf_record['consolidated_view']['consolidated_source_count']}")

    # The MPI record now reflects the deceased status.
    after_record = local_mpi.get(vrf_record["matched_record_id"])
    if after_record:
        print(f"  mpi.deceased_status.is_deceased: "
              f"{(after_record.get('deceased_status') or {}).get('is_deceased')}")
    cascade_summary = _summarize_cascade_completeness(vrf_event_id)
    print(f"  cascade completeness: {cascade_summary['completeness_pct']}%")
    print(f"  appointments_cancelled: "
          f"{sum(1 for a in appointment_system.get_actions() if a['action'] == 'cancel_appointment' and a.get('event_id') == vrf_event_id)}")
    print(f"  prescriptions_cancelled: "
          f"{sum(1 for a in prescription_system.get_actions() if a['action'] == 'cancel_auto_refill' and a.get('event_id') == vrf_event_id)}")
    print(f"  billing_episodes_closed: "
          f"{sum(1 for a in billing_system.get_actions() if a['action'] == 'close_episode' and a.get('event_id') == vrf_event_id)}")

    # Now LADMF arrives weeks later for the same patient.
    print()
    print("  LADMF arrives 9 weeks later with the same death event...")
    ladmf_event_id = ingest_death_event_from_source(
        source_id="ssa-ladmf",
        source_specific_record={
            "source_record_id": "ladmf-2026-q1-batch-44912001",
            "submission_timestamp": "2026-04-15T00:00:00Z",
            "given_name":   "ROBERT",
            "middle_name":  "JAMES",
            "family_name":  "ANDERSON",
            "dob":          "1942-05-14",
            "sex":          "M",
            "ssn_last_4":   "4827",
            "date_of_death": "2026-02-08",
        })
    ladmf_record = _DEATH_EVENT_LOG[ladmf_event_id]
    print(f"  ladmf event_id:    {ladmf_event_id}")
    print(f"  resolution_status: {ladmf_record['resolution_status']}")
    if ladmf_record["consolidated_view"]:
        print(f"  source_count:      "
              f"{ladmf_record['consolidated_view']['consolidated_source_count']}")

    # --- Flow 2: hidden-duplicate-revelation ---
    print()
    print("-" * 72)
    print("Flow 2: same patient appears under two MRNs in the MPI;")
    print("        LADMF death event reveals the duplicate chain")
    print("-" * 72)
    # The MPI was set up with mrn-3387221 and mrn-7782441 both
    # for Robert Anderson (same DOB, same address, same SSN-
    # last-4). The first flow's vital-records event already
    # matched and applied to mrn-3387221 (the first one matched
    # in iteration). The second event was applied as
    # corroboration. Both records are now in the MPI but only
    # the survivor mrn-3387221 carries the deceased status. In
    # production, the first death event's hidden-duplicate
    # detection at Step 2D would have surfaced the duplicate
    # chain and routed to recipe 5.1 BEFORE the death status
    # was applied. The demo's MPI iteration order surfaced both
    # candidates; we can show what happens when a duplicate is
    # detected on the SECOND arrival.

    # Reset the demo MPI to set up a clean duplicate-revelation
    # case. Two records, neither marked deceased.
    local_mpi = MockLocalMPI([
        r for r in SYNTHETIC_LOCAL_MPI_RECORDS
        if r["local_record_id"] in (
            "amc-richmond-mrn-3387221",
            "amc-richmond-mrn-7782441")
    ])
    _DEATH_EVENT_LOG.clear()

    duplicate_event_id = ingest_death_event_from_source(
        source_id="state-vital-records-virginia",
        source_specific_record={
            "source_record_id": "va-dc-2026-03-014-77882",
            "submission_timestamp": "2026-03-16T09:00:00Z",
            "given_name":   "Robert",
            "middle_name":  "James",
            "family_name":  "Anderson",
            "dob":          "1942-05-14",
            "sex":          "M",
            "address_line": "1247 Oak St",
            "city":         "Richmond",
            "state":        "VA",
            "zip_code":     "23220",
            "ssn_last_4":   "4827",
            "date_of_death": "2026-03-14",
            "state_of_death": "VA",
            "supporting_evidence_reference":
                "s3://vital-records-archive/va/2026/03/dc-2026-03-014-77882.pdf",
        })
    dup_record = _DEATH_EVENT_LOG[duplicate_event_id]
    print(f"  event_id:          {duplicate_event_id}")
    print(f"  resolution_status: {dup_record['resolution_status']}")
    print(f"  all_matched_ids:   "
          f"{dup_record.get('all_matched_record_ids')}")
    print(f"  consolidated to:   {dup_record.get('matched_record_id')}")
    cross_5_1_actions = [a for a in cross_recipe_5_1.get_actions()
                            if a.get("event_id") == duplicate_event_id]
    if cross_5_1_actions:
        print(f"  cross-recipe-5.1 action: "
              f"{cross_5_1_actions[0]['action']}")
        print(f"  survivor_record_id: "
              f"{cross_5_1_actions[0]['survivor_record_id']}")
        print(f"  merged_record_ids: "
              f"{cross_5_1_actions[0]['merged_record_ids']}")

    # --- Flow 3: premature-death-report case ---
    print()
    print("-" * 72)
    print("Flow 3: LADMF event for a live patient with no")
    print("        corroboration -> routed to verification queue")
    print("-" * 72)
    # Reset MPI to a clean state with a single record.
    local_mpi = MockLocalMPI([
        SYNTHETIC_LOCAL_MPI_RECORDS[1]  # Margaret Chen
    ])
    _DEATH_EVENT_LOG.clear()
    _VERIFICATION_QUEUE.clear()

    premature_event_id = ingest_death_event_from_source(
        source_id="ssa-ladmf",
        source_specific_record={
            "source_record_id": "ladmf-2026-q1-batch-99821",
            "submission_timestamp": "2026-04-01T00:00:00Z",
            "given_name":   "Margaret",
            "family_name":  "Chen",
            "dob":          "1955-09-22",
            "sex":          "F",
            "ssn_last_4":   "1199",
            "date_of_death": "2026-03-10",
        })
    prem_record = _DEATH_EVENT_LOG[premature_event_id]
    print(f"  event_id:          {premature_event_id}")
    print(f"  resolution_status: {prem_record['resolution_status']}")
    print(f"  matched_record_id: {prem_record['matched_record_id']}")
    print(f"  verification_queue_depth: {len(_VERIFICATION_QUEUE)}")
    if _VERIFICATION_QUEUE:
        print(f"  queued_reason:     "
              f"{_VERIFICATION_QUEUE[-1]['verification_reason']}")

    # The patient's MPI record was NOT updated. The deceased
    # status is still None.
    margaret_record = local_mpi.get(prem_record["matched_record_id"])
    if margaret_record:
        print(f"  mpi.deceased_status: "
              f"{margaret_record.get('deceased_status')}")
    print(f"  (the patient is correctly NOT marked deceased; the")
    print(f"   verification queue lets a human review before action)")

    # --- Flow 4: premature-death-report reversal ---
    # In Flow 3 the queue prevented the premature death from
    # being applied. To demonstrate the reversal pathway, we
    # construct a scenario where the deceased status WAS
    # applied (e.g., the verification threshold was relaxed for
    # operational reasons or a verifier mistakenly approved)
    # and now needs to be reversed.
    print()
    print("-" * 72)
    print("Flow 4: premature death-status reversal (live patient")
    print("        was incorrectly marked deceased; reverse it)")
    print("-" * 72)

    # Set up a record that was incorrectly marked deceased.
    local_mpi = MockLocalMPI([
        {
            **SYNTHETIC_LOCAL_MPI_RECORDS[1],
            "deceased_status": {
                "is_deceased": True,
                "consolidated_dates": {
                    "legal_billing_date": "2026-03-10",
                },
                "applied_at": "2026-04-02T08:00:00Z",
            },
            "death_event_history": [{
                "event_id": "death-event-prior-incorrect",
                "applied_at": "2026-04-02T08:00:00Z",
            }],
        }
    ])
    incorrect_event_id = "death-event-prior-incorrect"
    _DEATH_EVENT_LOG[incorrect_event_id] = {
        "event_id":          incorrect_event_id,
        "matched_record_id": "amc-richmond-mrn-5544102",
        "resolution_status": RES_APPLIED,
        "provenance":        {"source_id": "ssa-ladmf"},
    }

    print("  patient: Margaret Chen (mrn-5544102)")
    print("  current state: incorrectly marked deceased")
    print("  family called the institution; the patient is alive")

    # Capture two dual-control approvals from non-overlapping
    # organizational units.
    queue_dual_control_approval(
        event_id=incorrect_event_id,
        action_type="premature_death_report_reversal",
        approver_identity={
            "principal_id": "operator-alice-smith",
            "role":         "deceased_resolution_supervisor",
            "roles":        ["deceased_patient_resolution_verifier"],
            "organizational_unit": "compliance",
        })
    queue_dual_control_approval(
        event_id=incorrect_event_id,
        action_type="premature_death_report_reversal",
        approver_identity={
            "principal_id": "operator-bob-jones",
            "role":         "patient_advocate_lead",
            "roles":        ["deceased_patient_resolution_verifier"],
            "organizational_unit": "patient_advocacy",
        })
    print("  dual-control approvals: 2 (compliance + patient_advocacy)")

    # Execute the reversal under the appropriate verifier.
    execute_premature_death_report_reversal(
        event_id=incorrect_event_id,
        matched_record_id="amc-richmond-mrn-5544102",
        verifier_identity={
            "principal_id": "operator-alice-smith",
            "role":         "deceased_resolution_supervisor",
            "roles":        ["deceased_patient_resolution_verifier"],
            "organizational_unit": "compliance",
        },
        reversal_reason="family_confirmed_patient_alive_dmf_premature_report")

    after_reversal = local_mpi.get("amc-richmond-mrn-5544102")
    print(f"  after reversal: deceased_status={after_reversal.get('deceased_status')}")
    print(f"  history retained: "
          f"{len(after_reversal.get('death_event_history') or [])} entry")
    if after_reversal.get("death_event_history"):
        h = after_reversal["death_event_history"][-1]
        print(f"  history.reversed: {h.get('reversed')}")
        print(f"  history.reversal_reason: {h.get('reversal_reason')}")
    reversal_actions = sum(
        1 for c in CASCADE_REGISTRY.values()
        for a in c.get_actions()
        if a.get("action") == "reverse_deceased_status"
        and a.get("event_id") == incorrect_event_id)
    print(f"  cascade reversal actions: {reversal_actions}")

if __name__ == "__main__":
    run_demo()
```

---

Expected console output (the SQS / EventBridge / S3 / DynamoDB / CloudWatch warnings appear in demo mode because the resources do not exist; they are harmless):

```
========================================================================
Deceased Patient Resolution and Record Reconciliation Demo
========================================================================

All patients, demographics, sources, and identifiers in this
demo are fictional. The mock LADMF, state vital-records feed,
payer feed, EHR-internal source, and family-reported intake
return hand-crafted death events that exercise the ingestion,
matching, reconciliation, MPI-update, cascade, and reversal
paths; do not point this demo at the SSA's data exchange.

Institution:           academic-medical-center-richmond
Institution juris:     state-of-virginia
Matcher config:        deceased-matcher-v1.4.2
Tolerance config:      deceased-tolerance-v1.3.0
Conflict policy:       dod-conflict-policy-v1.2.0

------------------------------------------------------------------------
Flow 1: state vital-records death event arrives, then LADMF
        arrives later for the same patient (corroboration)
------------------------------------------------------------------------
  vrf event_id:      death-event-state-vi-XXXXXXXXXXXX
  resolution_status: applied
  matched_record_id: amc-richmond-mrn-3387221
  legal_billing_dod: 2026-02-08
  source_count:      1
  mpi.deceased_status.is_deceased: True
  cascade completeness: 100%
  appointments_cancelled: 3
  prescriptions_cancelled: 5
  billing_episodes_closed: 2

  LADMF arrives 9 weeks later with the same death event...
  ladmf event_id:    death-event-ssa-ladm-XXXXXXXXXXXX
  resolution_status: applied
  source_count:      2

------------------------------------------------------------------------
Flow 2: same patient appears under two MRNs in the MPI;
        LADMF death event reveals the duplicate chain
------------------------------------------------------------------------
  event_id:          death-event-state-vi-XXXXXXXXXXXX
  resolution_status: applied
  all_matched_ids:   ['amc-richmond-mrn-3387221', 'amc-richmond-mrn-7782441']
  consolidated to:   amc-richmond-mrn-3387221
  cross-recipe-5.1 action: merge_duplicate_chain
  survivor_record_id: amc-richmond-mrn-3387221
  merged_record_ids: ['amc-richmond-mrn-7782441']

------------------------------------------------------------------------
Flow 3: LADMF event for a live patient with no
        corroboration -> routed to verification queue
------------------------------------------------------------------------
  event_id:          death-event-ssa-ladm-XXXXXXXXXXXX
  resolution_status: premature_death_report_flagged
  matched_record_id: amc-richmond-mrn-5544102
  verification_queue_depth: 1
  queued_reason:     premature_death_report_candidate
  mpi.deceased_status: None
  (the patient is correctly NOT marked deceased; the
   verification queue lets a human review before action)

------------------------------------------------------------------------
Flow 4: premature death-status reversal (live patient
        was incorrectly marked deceased; reverse it)
------------------------------------------------------------------------
  patient: Margaret Chen (mrn-5544102)
  current state: incorrectly marked deceased
  family called the institution; the patient is alive
  dual-control approvals: 2 (compliance + patient_advocacy)
  after reversal: deceased_status=None
  history retained: 1 entry
  history.reversed: True
  history.reversal_reason: family_confirmed_patient_alive_dmf_premature_report
  cascade reversal actions: 12
```

(The event_id suffixes include random UUID hex so the actual `XXXXXXXXXXXX` portions will differ from run to run. Production with `jellyfish` and properly EM-trained Fellegi-Sunter weights produces different absolute scores than the demo.)

Several patterns to notice:

- **Flow 1 demonstrates the canonical multi-source-corroborated death.** The state vital-records death event arrives first with high-quality demographics and the death certificate as supporting evidence. The matcher resolves it against Robert Anderson's MPI record at high confidence; the multi-source reconciler builds the consolidated view (one source so far); the MPI-update handler applies the deceased status; the cascade fans out to the appointment-cancellation, prescription-disposition, billing-episode-closure, communication-path-switch, patient-portal-suspension, care-management-removal, analytics-handling, and cross-recipe consumers. The second event (LADMF, 9 weeks later) corroborates the first event without changing the resolution; the consolidated source count grows from 1 to 2.
- **Flow 2 demonstrates the hidden-duplicate-revelation case.** The MPI has two records for the same patient under different MRNs (the institution's internal matching had not surfaced the duplicate). The state vital-records death event matches both records at high confidence; the matcher detects the hidden-duplicate-revelation, routes to the recipe 5.1 cross-recipe consumer for atomic duplicate-resolution, and continues the death-event resolution against the consolidated record. The two MRNs collapse to one survivor record before the deceased status is applied.
- **Flow 3 demonstrates the premature-death-report verification routing.** The LADMF event arrives for Margaret Chen (a live patient) with no corroboration from any other source. The matcher resolves the event against the MPI at high confidence (the demographics match), but the multi-source reconciler detects that LADMF's premature-death-report-rate baseline (1.3%) exceeds the verification threshold and there is no corroboration. The event routes to the verification queue WITHOUT updating the MPI; the patient's deceased status remains None. A human reviewer can then verify against other sources, contact the family, or contact the patient's primary care provider before any action is taken.
- **Flow 4 demonstrates the reversal pathway.** A patient was incorrectly marked deceased (perhaps via a different ingestion path that did not route to the verification queue, or via a manual override). The family calls; the institution must reverse the deceased status. The reversal requires (a) a verifier with the authorized role, (b) two dual-control approvals from non-overlapping organizational units (in the demo, compliance and patient_advocacy), (c) execution of the reversal under the verifier's identity. The reversal restores the deceased_status to None but retains the death-event history with a reversal annotation so the audit trail captures the false-positive history. The cascade-reversal fan-out re-activates the patient's operational state across all downstream systems.
- **The audit log captures every consequential operation.** Every ingestion, every matching decision (no-match, low-confidence, medium-confidence routed to review, hidden-duplicate-revealed, high-confidence auto-resolved), every reconciliation decision (date-conflict-flagged, premature-flagged, reconciled), every MPI update (applied or transaction-failed), every cascade action (per-system completion), every reversal (authorization-rejected, dual-control-incomplete, reversed) is audit-logged with the event_id, source_id, decision band, and matcher/tolerance/conflict-policy versions active at decision time.
- **The DynamoDB log uses `Decimal` for every numeric field.** The match scores, the per-feature similarities, the per-source quality classifications, the matching tolerances all pass through `_to_decimal` on the way in and out so DynamoDB does not reject the writes.
- **The cascade has per-system cadence configuration.** Real-time cadence for appointment cancellation, prescription review, communication-path switch, patient-portal access; near-real-time cadence for billing episode closure, care-management panel removal; batch cadence for analytics platform refresh. The demo runs them all synchronously so the trace is easy to follow; production drives each on its appropriate cadence through EventBridge rules.

---

## Gap to Production

What the demo intentionally skips, and what you would add for a real deployment:

**Real per-source ingestion connectors.** The demo's `MockDeathEventSource` instances are hand-crafted dicts. Production has per-source ingestion Lambdas (or Glue jobs for batch sources): an LADMF subscription handler that reads the fixed-width-format files from the SSA's authorized intermediary or directly under the institution's NTIS certification (the certification is a separate operational program with its own onboarding timeline and ongoing compliance program); per-state vital-records-feed handlers (the modernized states publish FHIR-based VRDR Bundles through OAuth-protected endpoints; the legacy states publish batch CSV or fixed-width files on FTP or SFTP cadences); a payer-death-feed handler for CMS Medicare Beneficiary Database integration (the per-payer integration is a separate data-use-agreement project per payer); an EHR-internal handler that consumes the EHR's death-of-patient event in real-time (the integration depends on the institution's EHR's specific event-streaming capability); a hospice-agency handler for the institution's hospice or referral relationships; a family-reported-death intake handler that captures the family's call to the patient-services line (the intake worker's training, the script's design, and the audit-and-quality posture are all institutional-design choices); a provider-reported-death handler for faxed/mailed/HIE-mediated provider notifications; and an obituary-aggregator handler for the commercial obituary-feed subscription. Each connector is its own Lambda (or Glue job) with its own DLQ and its own audit-logging discipline.

**Real LADMF certification and intermediary subscription.** The demo uses synthetic data; production requires either NTIS certification under the Bipartisan Budget Act of 2013's framework (15 CFR Part 1110) or an authorized-intermediary data-use agreement. The certification process is multi-month with ongoing compliance obligations; the intermediary subscription has commercial terms specific to the intermediary. Many institutions discover, the first time their first wave of premature-death-reports hits, that the LADMF onboarding was non-trivial and the intermediary's terms have specific operational-discipline requirements.

**Real DynamoDB schema with the four primary tables.** The `death-event-log` table holds per-event provenance and resolution state (partition key: `event_id`, with a GSI on `matched_record_id` for the multi-source-reconciler's prior-events query, with a second GSI on `(source_id, ingested_at)` for per-source ingestion-rate reporting). The `verification-queue` table holds pending review cases (partition key: `queue_event_id`, with a GSI on `(verification_reason, queued_at)` for the per-reason queue-aging dashboard). The `cascade-ack-store` table holds per-system acknowledgments (partition key: `event_id`, sort key: `cascade_consumer`). The `personal-representative-authorization` table holds the per-patient personal-representative-access scope (partition key: `local_record_id`, sort key: `auth_event_id`, with a GSI on `personal_representative_id`). Provision with on-demand capacity. Customer-managed KMS keys at rest. Point-in-time recovery for all four tables. DynamoDB Streams on the death-event-log table to drive the cross-recipe event fan-out.

**TransactWriteItems for atomic cross-table writes.** The demo's MPI update, death-event-log status update, and cascade-emission are sequenced. Production wraps them in `TransactWriteItems` so the per-event state is atomic across the tables; partial-failure scenarios cannot leave the MPI updated without the death-event-log reflecting the resolution.

**Real Aurora PostgreSQL local MPI integration.** The demo's `MockLocalMPI` is an in-memory dict. Production has Aurora PostgreSQL (or the institution's existing MPI vendor's product) with indexes on the demographic-feature blocking keys, full-text search, sensitivity-flag enforcement, and recipe 5.1's identity-merge state. The deceased-patient-resolution pipeline consults the MPI under read-only access for matching; mutations to the death-status fields flow through a scoped write path in the mpi-update-handler Lambda.

**Real Step Functions orchestration.** The demo's six steps run synchronously in-process. Production orchestrates the per-event flow through Step Functions with per-step retries, per-step error routing to DLQs, parallel execution where the per-event work permits (the cascade fan-out is parallelized), and explicit synchronization at the cross-recipe-coordination steps. Step Functions provides the audit-and-monitoring substrate for the per-event flow; CloudWatch alarms on stuck workflows surface DLQ depth issues.

**Real EventBridge bus with cross-recipe consumer subscriptions.** The demo emits events but they go nowhere in demo mode. Production deploys a dedicated `deceased-patient-events-bus` with EventBridge rules routing the deceased_patient_resolved, deceased_status_reversed, hidden_duplicate_revealed, personal_representative_authorized, posthumous_access_granted, and cross_source_disagreement_flagged events to the appropriate consumers (the per-cascade Lambdas, the cross-recipe consumers for recipes 5.1, 5.5, 5.7, 5.8, 5.9, the analytics consumers, the operational dashboards). DLQs on every consumer; CloudWatch alarms on DLQ depth surface stuck consumers.

**Real cross-account audit-archive S3 bucket.** Production has a dedicated AWS account for the audit-archive bucket (separate from the operational account for blast-radius isolation). The audit-archive bucket has Object Lock in Compliance mode with retention pinned to the longest of the regulatory floors (HIPAA 50-year posthumous-protection-period as the dominant retention floor, state medical-records-retention, the per-source-data-use-agreement audit-retention floor, and the cross-jurisdictional retention overlay where the institution operates across borders). Lifecycle to S3 Glacier Deep Archive after 90 days. The 50-year retention floor is the longest single retention requirement in the chapter; the institution's audit-archive design has to accommodate the multi-decade horizon.

**Real cascade Lambdas with per-system integration code.** The demo's `MockDownstreamSystem` records actions to a list. Production has per-system cascade Lambdas that call the actual operational system's API: the appointment-scheduling-system's cancellation API, the e-prescribing-system's auto-refill-cancellation API, the billing-system's episode-closure API, the patient-portal access-controller's account-suspension API. Each cascade Lambda has its own IAM role, its own DLQ, its own retry semantics, and its own audit logging. The cascade-ack-store records the per-system completion so the cross-system-propagation-completeness metric is accurate.

**Premature-death-report verification queue review tooling.** The demo's `_VERIFICATION_QUEUE` is an in-memory list. Production has a verification-review tool (a web application or a queue-management dashboard) where the designated verification operators see queued cases, the per-event provenance, the candidate records, the per-source quality classification, and the supporting evidence. The verifier's decision (approve, reject, request additional verification) is captured with the verifier identity, the decision timestamp, the verification-criteria-version active, and any verifier-supplied additional context. The decision drives the death-event-log's resolution_status update and the downstream cascade or the no-action confirmation.

**Dual-control approval workflow for reversals.** The demo's `queue_dual_control_approval` is an in-memory accumulation. Production has a dedicated approval-workflow surface where the two approvers from non-overlapping organizational units (typically compliance and patient-advocacy or compliance and clinical-informatics) sign off on the reversal under their authenticated identities. The dual-control discipline prevents single-operator errors and provides the audit trail that the institutional compliance team needs for the post-incident review.

**Family-reported-death intake operational discipline.** The demo's family-reported source is a synthetic event. Production has a deliberate intake program: trained intake workers with bereavement-aware-communications training, an institutionally-defined intake script, audit-and-quality posture (every family-reported intake is audit-logged with the worker identity, the intake duration, the information-completeness score, and any worker-supplied additional context), periodic quality review surfacing the intakes that may have been mishandled, and downstream-propagation cadence (the family-reported intake event is dispatched to the multi-source-reconciler within minutes of the intake completion). Build the intake as a high-touch institutional moment with named ownership and continuous quality monitoring.

**HIPAA-posthumous-protection-period access-control engine.** The 50-year posthumous-protection period requires access-control enforcement that consults the patient's deceased status, the date of death, the requesting context's authorization framework, and the institutional access-control posture for every read against the deceased-patient record. Production has a versioned rule store, a rule-evaluation Lambda invoked at every read with the requesting context as input, per-request access decisions with explicit authorization-framework attribution, per-decision audit logging, and the multi-decade operational discipline including configuration-store lifecycle management and per-jurisdiction-overlay-rule integration (some states have stricter posthumous-protection requirements than HIPAA's federal floor). The engine is a separate operational program with named ownership, periodic compliance-team review, and explicit institutional review committee.

**Personal-representative-portal authorization-mediation workflow.** The demo does not include the personal-representative-portal. Production has Cognito-based personal-representative authentication during the estate-administration period, the institutional release-of-information system integration with the personal-representative-authentication-and-authorization framework, per-personal-representative authorization-scope binding (which record types the personal representative may access, which time windows the access is authorized for, which use cases the access serves), per-access audit logging with the personal-representative identity and access purpose, and the personal-representative-portal user-experience design (institutional-onboarding flow, institutional-explanation language, institutional-support contact information). The personal-representative experience is one of the family's most-visible institutional touchpoints during a sensitive period.

**Idempotency keys on every write.** Standardize at `(event_id, source_id)` for the death-event-ingestion Lambda; `(event_id, matched_record_id)` for the death-event-matcher Lambda; `(event_id, reconciliation_event_id)` for the multi-source-reconciler Lambda; `(event_id, matched_record_id, application_event_id)` for the mpi-update-handler Lambda; `(event_id, cascade_consumer)` for each cascade Lambda; `(event_id, reversal_event_id)` for the premature-death-report-reversal Lambda. Duplicate-event delivery from EventBridge or duplicate-invocation from Step Functions retries is routine; the pipeline must handle it without producing duplicate audit events, duplicate cascade-acknowledgments, or scrambled per-source provenance.

**Per-source quality-drift monitoring with disparity alarms.** The demo emits CloudWatch metrics but does not configure alarms or aggregations. Production computes per-source ingestion rate weekly, per-source data-completeness score weekly, per-source matching-success rate weekly, per-source premature-death-report rate monthly, per-source cross-source-corroboration rate monthly, all with rolling-window-baseline comparison. Drift exceeding threshold triggers automatic-reclassification with the institutional review committee for confirmation; alert routing surfaces the drift to the deceased-patient-resolution-program steering committee. Per-source-premature-death-report-rate-drift > 50% from baseline = MEDIUM alarm; per-source-data-completeness-score-drift < -10% from baseline = MEDIUM; per-source-matching-success-rate-drift < -15% from baseline = HIGH.

**Cohort-stratified accuracy monitoring.** The demo's cohort-axis hashing is illustrative. Production computes per-cohort match rate weekly, per-cohort false-acceptance rate weekly, per-cohort review-queue aging weekly, per-cohort family-correspondence-after-death rate monthly, all stratified by hashed cohort axes (geographic_region_hash, age_decade_hash, sex_hash, name_tradition_hash). Disparity (best-rate minus worst-rate) thresholds: match-rate > 0.10 = MEDIUM alarm; false-acceptance-rate > 0.02 = HIGH; family-correspondence-after-death-rate disparity > 0.05 = MEDIUM. The privacy team is an explicit reviewer in addition to the standard analytics-governance committee.

**Cross-network deceased-patient-event propagation through TEFCA.** The demo's cross-recipe-5.9 signal is a one-way action record. Production has a TEFCA-mediated deceased-patient-event-propagation pipeline that signals participating organizations of the deceased status with appropriate authorization-framework and audit-and-attribution layer. The TEFCA propagation is operationally important for the cross-organizational deceased-patient-recognition latency reduction.

**KMS-encrypted everything.** Customer-managed keys for the death-event-log table, the verification-queue table, the cascade-ack-store table, the personal-representative-authorization table, the per-source landing-zone bucket, the audit-archive bucket, the SQS queues, the Lambda log groups, the Step Functions execution-context storage, the Secrets Manager secrets, and the local MPI Aurora cluster. CloudHSM where the institutional security posture requires single-tenant HSM-backed key custody. Per-service KMS configuration is omitted for readability in the demo but is non-negotiable for the institution's standard PHI-handling posture.

**VPC + VPC endpoints + PrivateLink.** Production runs all Lambdas in VPC with VPC endpoints for DynamoDB (gateway), S3 (gateway), KMS, Secrets Manager, CloudWatch Logs, EventBridge, SQS, Step Functions, STS, and SageMaker. PrivateLink for the per-source-feed connectivity where the source supports it (CMS's increasing PrivateLink availability for federal data feeds; some commercial-payer-feeds). NAT Gateway only for outbound HTTPS to the per-source feeds where PrivateLink is not used; outbound proxy with per-source allow-list. Aurora PostgreSQL in a private subnet with no public-network reachability; security group enumerates the specific Lambda execution-role-bound ENIs authorized to connect. Personal-representative-portal-network-isolation pattern: the personal-representative-portal Cognito flow operates through a separate API Gateway endpoint with its own WAF rule set, with rate limiting per-personal-representative-session and per-personal-representative-id below the staff-initiated query rate limits.

**CloudTrail data events on every consequential operation.** Data events on the death-event-log, the verification-queue, the cascade-ack-store, and the personal-representative-authorization DynamoDB tables; the audit-archive S3 bucket; the per-source landing-zone S3 bucket; the per-source-credentials Secrets Manager secrets; the customer-managed KMS keys. Lambda invocations logged. Step Functions executions logged. EventBridge events logged. CloudTrail logs encrypted with KMS and retained per the regulatory floor (the 50-year posthumous-protection-period as the dominant retention floor for deceased-patient resolution). Audit logs in a dedicated S3 bucket with Object Lock in Compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days; CloudTrail data events forwarded to a dedicated audit AWS account for blast-radius isolation.

**Lake Formation column-level and row-level access control on the analytics surface.** Different audiences need different views. Treatment-context users see the institution's own portion of the deceased-patient record under the appropriate access-control framework; estate-administration personal-representative users see the records authorized by the personal-representative authorization scope; research users see the de-identified aggregate; audit-and-compliance users see the full audit-event log; the deceased-patient-resolution-program steering committee sees the operational metrics. Lake Formation enforces the per-audience access through column-level and row-level policies on the Athena queries.

**Federation-participation governance program.** Deceased-patient resolution is a multi-decade institutional capability rather than a one-time project. Establish clear operational ownership: who tunes the per-source matching tolerance, who reviews the per-source-quality-drift reports, who owns the LADMF certification or intermediary subscription, who handles the per-jurisdiction vital-records-data-use agreements, who responds to premature-death-report verifications and reversals, who owns the HIPAA-posthumous-protection-period compliance program, who owns the personal-representative-experience program, who handles the family-reported-death intake operations. The program spans compliance, privacy, legal, clinical operations, patient advocacy, security, IT, and analytics with named ownership across the institution.

The pipeline is the easy part. The operational discipline (multi-source integration with per-source onboarding, premature-death-report-verification-and-reversal pathway with named operational ownership, HIPAA-posthumous-protection-period compliance over the 50-year horizon, personal-representative experience design as a key institutional touchpoint during the estate-administration period, family-reported-death intake operations with bereavement-aware-communications training, cross-system-cascade-propagation-discipline with per-system cadence and per-system acknowledgment tracking, family-correspondence-after-death monitoring as the family-visible signal of the program's effectiveness) is what makes a deceased-patient-resolution program operate effectively rather than drifting into producing the wrong-patient correspondence the family experiences as institutional failure. Build for that.

---

*← [Recipe 5.10: Deceased Patient Resolution and Record Reconciliation](chapter05.10-deceased-patient-resolution-reconciliation)*
