# Recipe 5.7: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 5.7. It shows one way you could translate the longitudinal-patient-matching-across-name-changes pattern into working Python using a small `MockIdentityStore` standing in for the real DynamoDB temporal-identity table and active-search-index, `MockSupportingDocumentStore` standing in for the S3 supporting-document bucket and the audit-archive bucket, `MockReferenceData` standing in for the production nickname dictionaries / surname-change-pattern models / transliteration maps / per-tradition naming-convention rules, `MockPatientPreferences` standing in for the patient-portal preference-capture flow, `MockJurisdictionalOverlays` standing in for the per-state policy overlay, an in-memory event bus standing in for Amazon EventBridge, an in-memory queue standing in for the name-change review queue, and small helpers for the audit-log archive and CloudWatch-style metrics. It is not production-ready. There is no real Splink-or-`recordlinkage` probabilistic-record-linkage core, no real FHIR Patient resource serializer, no real document-extraction pipeline for court orders or marriage certificates, no Glue/Spark periodic-reconciliation pipeline, no Step Functions orchestration, no SageMaker calibration loop, no patient-portal UI, no review-queue UI, no FHIR-native HealthLake integration, and no IAM, KMS, VPC, WAF, or CloudTrail wiring. Think of it as the sketchpad version: useful for understanding the shape of a longitudinal-name-change pipeline that respects the temporal-name-as-event-history posture, the direct-vs-indirect detection split, the source-strength-weighted resolution thresholds, the sensitivity-classification-as-access-control-envelope distinction (the matcher always knows the linkage; the rendering layer decides who sees it), the reversibility-is-the-architecture posture, and the cohort-stratified-equity-monitoring discipline this recipe demands. It is not something you would point at a live MPI on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the six core pseudocode steps from the main recipe: detect a name-change candidate from the trigger event (registration update, payer eligibility refresh, vital-records feed, cross-facility match callback, document upload, patient-portal connection, bulk reconciliation); resolve the candidate against the existing identity record using direct-vs-indirect classification, source-strength weighting, and name-change-specific thresholds; apply the sensitivity-and-consent envelope (general, gender-affirming, protective-custody, intimate-partner-violence, witness-protection, patient-requested-restricted) honoring patient preferences and jurisdictional overlays; persist the resolved name change atomically with the audit log; propagate the resolution to dependent stores (local MPI from recipe 5.1, cross-reference table from recipe 5.4, cross-facility matcher from recipe 5.5, claims-clinical linkage from recipe 5.6, chart-rendering layer, release-of-information workflow, patient-portal services, quality-and-risk-adjustment pipelines, FHIR Patient resource in HealthLake); and react to invalidation events that supersede prior resolutions (correction, reversal, identity merge, identity unmerge, sensitivity-classification update, document-strength upgrade, cross-facility match invalidation). The synthetic patients, name changes, and supporting documents in the demo are fictional; the names, MRNs, court-order references, and document references are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also install a probabilistic-record-linkage library such as [Splink](https://github.com/moj-analytical-services/splink) or [`recordlinkage`](https://github.com/J535D165/recordlinkage) for the candidate-generation and Fellegi-Sunter scoring core, [`jellyfish`](https://github.com/jamesturk/jellyfish) for approximate string matching and phonetic encoding (Soundex, Metaphone, Double Metaphone, Match Rating Approach), a FHIR client library such as `fhir.resources` for the Patient resource serialization (with the HumanName datatype's `use` and `period` fields supporting the time-varying-name model), a document-extraction library or service (Amazon Textract via `boto3`, or a commercial document-AI service) for parsing court orders and marriage certificates, and a Spark client (`pyspark`) for the bulk historical-backfill and periodic-reconciliation pipeline. The demo replaces all of these with small mocks so the focus stays on the temporal-identity, sensitivity-envelope, and invalidation logic rather than on protocol parsing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchGetItem`, `dynamodb:TransactWriteItems` on the `identity-temporal-name` table, the `active-search-index` table, the `identity-event-outbox` table, and the `identity-event-history` table
- `s3:PutObject` on the supporting-documents bucket (where uploaded court orders, marriage certificates, divorce decrees, and license scans land), the audit-archive bucket (Object Lock in Compliance mode), and the derived-snapshot bucket
- `s3:GetObject` on the supporting-documents bucket for the document-strength-promotion path that re-reads a previously-uploaded document
- `sqs:SendMessage` and `sqs:ReceiveMessage` on the name-change-review-queue, the supporting-document-review-queue, the sensitivity-classification-review-queue, and the invalidation-queue
- `events:PutEvents` on the name-change-trigger bus and the name-change-resolved bus
- `cloudwatch:PutMetricData` for the detection-rate, review-queue-depth, time-to-resolve, and cohort-stratified-disparity metrics
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the identity store, the supporting-document bucket, and the audit archive
- `glue:StartJobRun` and `glue:GetJobRun` on the periodic-reconciliation Glue jobs (production only; the demo runs in-process)

Scope each Lambda's IAM role and each Glue job's role to the specific resource ARNs they touch. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The persistence Lambda gets append-only IAM on the identity-event history (no `dynamodb:DeleteItem`, no `dynamodb:UpdateItem` on existing version items) enforced through condition keys plus DynamoDB resource-based policy; the audit-archive bucket is Object-Lock-configured so even an over-privileged role cannot delete archived events.

A few things worth knowing upfront:

- **Names are not strings; they are time-varying attributes with effective spans.** Recipe 5.1's matcher compares name strings; recipe 5.7's matcher compares against a name *history* (current name plus zero or more prior names plus zero or more aliases, each with an effective span). A record arriving with a name dated five years ago compares to whichever name was current for the identity five years ago, not just to the current name. The demo's `IdentityRecord` data structure carries this temporal model.
- **Detection comes before resolution.** A flat-name matcher does not need a name-change detector because every name is the value-of-the-day. The temporal model needs an explicit detector because *adding a new name to an existing identity* is structurally different from *a new record matching an existing identity*. The demo separates `detect_name_change_candidate` from `resolve_name_change` for this reason.
- **Direct and indirect changes route differently.** A direct change is an explicit assertion (the patient said so, the document says so, the payer's update event says so). An indirect change is a high-demographic-match record arriving with a different name from the matched identity. Indirect at high confidence is rare and routes more conservatively than direct at the same confidence band.
- **Source strength matters.** A court-order PDF beats a verbal patient assertion; both are valid; the resolver behaves differently for each. The demo encodes source-strength tiers (`STRONG`, `MEDIUM`, `MEDIUM-WEAK`, `WEAK`) and applies them to the threshold logic.
- **The matcher always knows the linkage; specific users may not.** Sensitivity classification and patient preferences live in an `access_control_envelope` attached to each prior-name event. Hiding the linkage from the matcher itself defeats the matcher's job; hiding the prior name from the user surface is a presentation-and-access-control concern. The two are distinct, and the demo makes the distinction explicit.
- **Reversibility is not a feature; it is the architecture.** Name-change events are append-only history; superseding events update the *computed* current state without losing the underlying log. The demo's `invalidate_on_event` handles correction, reversal, identity merge, identity unmerge, sensitivity-class update, and document-strength upgrade as first-class operations.
- **DynamoDB rejects Python `float`.** Every detection score, name-pair-plausibility component, and numeric metadata field passes through `Decimal` on its way in and on its way out. Same gotcha as recipes 5.1 / 5.2 / 5.3 / 5.4 / 5.5 / 5.6; the same `_to_decimal` helper handles it.
- **The example collapses Step Functions, multiple Glue jobs, multiple Lambdas, and the SQS-driven worker pattern into a single Python file for readability.** In production the detect, resolve, sensitivity-envelope, persist, propagate, and invalidate-on-event stages are separate Lambdas (for the operational stream) and Glue jobs (for the periodic-reconciliation and historical-backfill pipelines) orchestrated by Step Functions, each with their own error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the source-strength tiers, the direct-vs-indirect thresholds, the matcher and reference-data versions, and the sensitivity-classification rules are what you would change between environments.

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

# Structured logging. In production, ship JSON-formatted records to
# CloudWatch Logs Insights. Patient identity data is PHI and prior-
# name disclosures may be sensitivity-classified; log structural
# metadata only (identity_id, event_id, resolution status,
# confidence band, sensitivity_class), never raw name strings,
# raw demographics, or supporting-document contents.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from DynamoDB, EventBridge,
# CloudWatch, and SQS. Per-event resolution latencies are not
# real-time critical (registration updates can absorb a few
# seconds), but bulk reconciliation runs are throughput-sensitive
# enough that transient throttling on any one service should not
# fail an entire Glue job. Step Functions Catch states distinguish
# retriable infrastructure failures from terminal logic failures
# and route terminal failures to a DLQ for human investigation.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm
# containers so each invocation does not pay the connection cost.
REGION = "us-east-1"
dynamodb = boto3.resource("dynamodb", region_name=REGION, config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", region_name=REGION, config=BOTO3_RETRY_CONFIG)
sqs_client = boto3.client("sqs", region_name=REGION, config=BOTO3_RETRY_CONFIG)
eventbridge_client = boto3.client("events", region_name=REGION, config=BOTO3_RETRY_CONFIG)
cloudwatch_client = boto3.client("cloudwatch", region_name=REGION, config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill these in with your actual resource names. The demo prints
# what it would write rather than failing if the resources do not
# exist; see run_demo() at the bottom.
IDENTITY_TABLE              = "identity-temporal-name"
SEARCH_INDEX_TABLE          = "active-search-index"
EVENT_OUTBOX_TABLE          = "identity-event-outbox"
EVENT_HISTORY_TABLE         = "identity-event-history"
SUPPORTING_DOCS_BUCKET      = "my-name-change-supporting-documents"
AUDIT_ARCHIVE_BUCKET        = "my-name-change-audit-archive"
DERIVED_SNAPSHOT_BUCKET     = "my-name-change-derived"
NAME_CHANGE_REVIEW_QUEUE_URL    = "https://sqs.us-east-1.amazonaws.com/000000000000/name-change-review-queue"
DOC_REVIEW_QUEUE_URL            = "https://sqs.us-east-1.amazonaws.com/000000000000/supporting-document-review-queue"
SENSITIVITY_REVIEW_QUEUE_URL    = "https://sqs.us-east-1.amazonaws.com/000000000000/sensitivity-classification-review-queue"
INVALIDATION_QUEUE_URL          = "https://sqs.us-east-1.amazonaws.com/000000000000/invalidation-queue"
TRIGGER_EVENT_BUS_NAME      = "name-change-trigger-bus"
RESOLVED_EVENT_BUS_NAME     = "name-change-resolved-bus"
CLOUDWATCH_NAMESPACE        = "LongitudinalNameChange/Resolution"

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("IDENTITY_TABLE",              IDENTITY_TABLE),
    ("SEARCH_INDEX_TABLE",          SEARCH_INDEX_TABLE),
    ("EVENT_OUTBOX_TABLE",          EVENT_OUTBOX_TABLE),
    ("EVENT_HISTORY_TABLE",         EVENT_HISTORY_TABLE),
    ("SUPPORTING_DOCS_BUCKET",      SUPPORTING_DOCS_BUCKET),
    ("AUDIT_ARCHIVE_BUCKET",        AUDIT_ARCHIVE_BUCKET),
    ("DERIVED_SNAPSHOT_BUCKET",     DERIVED_SNAPSHOT_BUCKET),
    ("NAME_CHANGE_REVIEW_QUEUE_URL", NAME_CHANGE_REVIEW_QUEUE_URL),
    ("DOC_REVIEW_QUEUE_URL",        DOC_REVIEW_QUEUE_URL),
    ("SENSITIVITY_REVIEW_QUEUE_URL", SENSITIVITY_REVIEW_QUEUE_URL),
    ("INVALIDATION_QUEUE_URL",      INVALIDATION_QUEUE_URL),
    ("TRIGGER_EVENT_BUS_NAME",      TRIGGER_EVENT_BUS_NAME),
    ("RESOLVED_EVENT_BUS_NAME",     RESOLVED_EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",        CLOUDWATCH_NAMESPACE),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every resolved name-change record stores the matcher and
# reference-data versions active at decision time. This is how a
# future audit reconstructs what thresholds and what nickname /
# surname / transliteration data were active when a particular
# linkage was made.
MATCHER_CONFIG_VERSION = "lncm-v1.7.2"
REFERENCE_DATA_VERSIONS = {
    "nickname_dictionary":     "ndict-2026-q1",
    "surname_change_patterns": "scp-2026-q1",
    "transliteration_maps":    "tmap-2026-q1",
    "naming_tradition_rules":  "ntr-2026-q1",
}

# --- Source-strength tiers ---
# A court-order PDF beats a verbal patient assertion; both are
# valid; the resolver behaves differently for each. Higher tiers
# pass the auto-resolve threshold at lower detection scores than
# lower tiers; the WEAK tier never auto-resolves on its own.
SOURCE_STRENGTH = {
    "court_order":                    "STRONG",
    "marriage_certificate":           "STRONG",
    "divorce_decree":                 "STRONG",
    "vital_records_feed":             "STRONG",
    "drivers_license_scan_verified":  "STRONG",
    "payer_eligibility_update":       "MEDIUM",
    "registration_with_id_check":     "MEDIUM",
    "patient_self_assertion":         "MEDIUM-WEAK",
    "cross_facility_match_callback":  "MEDIUM-WEAK",
    "indirect_detection_only":        "WEAK",
}

# --- Name-change confidence thresholds ---
# Calibrated separately from the demographic-match thresholds in
# recipe 5.1. The cost-benefit profile is different here: false
# acceptances of name changes corrupt the longitudinal record;
# false rejections fragment it. The numbers below are illustrative
# defaults; calibrate against your own gold set with input from
# the institution's analytics governance committee, clinical
# informatics team, and patient-experience-and-dignity committee.
DIRECT_NAME_CHANGE_HIGH_THRESHOLD   = Decimal("0.85")
DIRECT_NAME_CHANGE_MED_THRESHOLD    = Decimal("0.70")
INDIRECT_NAME_CHANGE_HIGH_THRESHOLD = Decimal("0.90")  # tighter
INDIRECT_NAME_CHANGE_MED_THRESHOLD  = Decimal("0.78")
NAME_CHANGE_REJECT_THRESHOLD        = Decimal("0.50")

# --- Per-feature weights for the detection scorer ---
# Demographic match strength dominates because it is the most
# reliable signal that two records refer to the same person.
# Name-pair plausibility (whether the new name is a plausible
# legal-change variant of the prior name) is the next-strongest
# signal. Temporal plausibility (whether the asserted change date
# is consistent with the records' creation timeline) is a softer
# signal. Source strength enters as a separate multiplier.
DETECTION_SCORE_WEIGHTS = {
    "demographic_match_strength": Decimal("0.45"),
    "name_pair_plausibility":     Decimal("0.35"),
    "temporal_plausibility":      Decimal("0.20"),
}
SOURCE_STRENGTH_MULTIPLIER = {
    "STRONG":      Decimal("1.00"),
    "MEDIUM":      Decimal("0.92"),
    "MEDIUM-WEAK": Decimal("0.82"),
    "WEAK":        Decimal("0.70"),
}

# --- Sensitivity classification ---
# Maps a name-change context to a sensitivity class. The class
# (and the patient's expressed preferences) drive the access-
# control envelope. The matcher always knows the linkage; the
# rendering layer decides who sees it.
SENSITIVITY_CLASSES = {
    "GENERAL":                      "no special handling beyond audit",
    "GENDER_AFFIRMING":             "patient-preference rules apply",
    "PROTECTIVE_CUSTODY":           "legal protective measures in effect",
    "IPV_RELOCATION":               "intimate-partner-violence safety",
    "WITNESS_PROTECTION":           "strictest class",
    "PATIENT_REQUESTED_RESTRICTED": "patient-specific restriction",
}

# --- Default permitted display contexts and release scopes ---
# Per sensitivity class, the default access-control envelope when
# the patient has expressed no specific preference. Patient
# preferences override the defaults.
DEFAULT_ENVELOPE_BY_CLASS = {
    "GENERAL": {
        "permitted_display_contexts": ["treatment", "operations"],
        "permitted_release_scopes":   ["patient_access_api",
                                          "treatment_disclosure",
                                          "operations_disclosure"],
        "audit_rules":                {"every_disclosure_logged": False,
                                          "every_query_logged": False},
    },
    "GENDER_AFFIRMING": {
        "permitted_display_contexts": ["treatment_with_clinical_relevance"],
        "permitted_release_scopes":   ["patient_access_api"],
        "audit_rules":                {"every_disclosure_logged": True,
                                          "every_query_logged": True,
                                          "monthly_summary_to_patient_portal": True},
    },
    "PROTECTIVE_CUSTODY": {
        "permitted_display_contexts": ["treatment_with_clinical_relevance"],
        "permitted_release_scopes":   ["patient_access_api"],
        "audit_rules":                {"every_disclosure_logged": True,
                                          "every_query_logged": True},
    },
    "IPV_RELOCATION": {
        "permitted_display_contexts": ["treatment_with_clinical_relevance"],
        "permitted_release_scopes":   ["patient_access_api"],
        "audit_rules":                {"every_disclosure_logged": True,
                                          "every_query_logged": True},
    },
    "WITNESS_PROTECTION": {
        "permitted_display_contexts": ["audit_only"],
        "permitted_release_scopes":   ["patient_access_api"],
        "audit_rules":                {"every_disclosure_logged": True,
                                          "every_query_logged": True,
                                          "weekly_summary_to_compliance": True},
    },
    "PATIENT_REQUESTED_RESTRICTED": {
        "permitted_display_contexts": ["treatment_with_clinical_relevance"],
        "permitted_release_scopes":   ["patient_access_api"],
        "audit_rules":                {"every_disclosure_logged": True,
                                          "every_query_logged": True},
    },
}
```

## Helpers

Same family of small helpers used in recipes 5.1 - 5.6. The `_to_decimal` and `_serialize_for_dynamodb` helpers are the load-bearing ones; DynamoDB rejects Python `float` and the recursive serializer keeps the rest of the code readable.

```python
def _to_decimal(value) -> Decimal:
    """Coerce numeric input into Decimal for DynamoDB."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

def _now_iso() -> str:
    """UTC timestamp in ISO 8601 format. Always UTC; never local time."""
    return datetime.now(timezone.utc).isoformat()

def _strip_diacritics(s: str) -> str:
    """Strip combining diacritical marks for case-insensitive
    matching. Critical for names with accents that the EHR may
    have stripped on input (e.g., Núñez vs Nunez)."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def _canonical_name(*parts) -> str:
    """Normalize a name to canonical lowercase whitespace-collapsed
    form for comparison. Production handles per-tradition rules
    (Spanish double-surname order, East Asian family-name-first
    conventions, Arabic patronymic structures) here too."""
    joined = " ".join(str(p or "").strip() for p in parts)
    joined = _strip_diacritics(joined).lower()
    joined = re.sub(r"[^\w\s'-]", " ", joined)
    joined = re.sub(r"\s+", " ", joined).strip()
    return joined

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _serialize_for_dynamodb(obj):
    """Recursive serialization helper. Same pattern as recipes 5.1 - 5.6."""
    if isinstance(obj, dict):
        return {k: _serialize_for_dynamodb(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_for_dynamodb(v) for v in obj]
    if isinstance(obj, set):
        return [_serialize_for_dynamodb(v) for v in sorted(obj)]
    if isinstance(obj, float):
        return Decimal(str(obj))
    return obj

def _emit_metric(metric_name: str, value: float,
                  dimensions: dict = None) -> None:
    """CloudWatch metric emit. Cohort-bucket dimensions feed the
    cohort-stratified accuracy monitoring; production aggregates
    by CohortBucket and alarms on per-cohort detection-rate or
    false-acceptance-rate disparities."""
    try:
        cloudwatch_client.put_metric_data(
            Namespace=CLOUDWATCH_NAMESPACE,
            MetricData=[{
                "MetricName": metric_name,
                "Value": value,
                "Unit": "Count",
                "Dimensions": [
                    {"Name": k, "Value": v} for k, v in (dimensions or {}).items()
                ],
            }],
        )
    except Exception as exc:
        logger.warning("metric emit failed",
                        extra={"metric": metric_name, "error": str(exc)})

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
        logger.info("archive write skipped (demo mode is fine to ignore)",
                     extra={"bucket": bucket, "key": key, "error": str(exc)})
```

---

## Mock Identity Store, Reference Data, Patient Preferences, and Jurisdictional Overlays

Production reads the identity record from a real DynamoDB temporal-identity table populated by the per-event resolution pipeline plus the historical-backfill Glue job; reads reference data from a versioned reference-data store maintained by the clinical-informatics team or licensed from a commercial provider (Melissa Data, OHDSI vocabulary, in-house); reads patient preferences from a patient-portal preference-capture flow that respects the institution's consent framework; and reads jurisdictional overlays from an institutional policy store maintained by compliance. The demo includes small mocks that exercise the resolution pipeline without requiring those external dependencies.

```python
# --- Synthetic identity store ---
# Each identity carries a current name, a list of prior names
# (each with effective span and source metadata), zero or more
# aliases, demographic features (DOB is stable; address and phone
# may change), and the institution-internal patient ID(s).
SYNTHETIC_IDENTITY_STORE = {
    # Catherine Wilson, age 41, the heart-failure patient from
    # recipe 5.6. Marriage-driven name change incoming.
    "id-internal-00874": {
        "identity_id":         "id-internal-00874",
        "linked_local_mrns":   ["local-patient-internal-00874"],
        "linked_member_ids":   [{"payer_id": "PAYER-01",
                                    "member_id": "MEM-100874-A"}],
        "current_name": {
            "given":          "Catherine",
            "middle":         "Marie",
            "family":         "Wilson",
            "suffix":         None,
            "effective_from": "2018-09-14",
            "effective_to":   None,
            "use":            "official",
            "source":         "registration_with_id_check",
            "event_id":       "evt-name-2018-09-14-initial",
        },
        "prior_names":  [],
        "aliases":      [],
        "dob":          "1985-03-22",
        "sex_assigned_at_birth": "F",
        "current_sex_or_gender": "F",
        "address_history": [
            {"value": "412 Oak St, Springfield, IL 62701",
             "effective_from": "2022-04-01", "effective_to": None},
        ],
        "phone_history": [
            {"value": "+15551234567",
             "effective_from": "2018-09-14", "effective_to": None},
        ],
        "ssn_last4":    "4287",
        "cohort_bucket": "english_traditional",
        "creation_date": "2018-09-14",
        "current_event_version": 1,
    },
    # Maria Garcia, recently hyphenated to Garcia-Lopez (the
    # cluster #3 patient from recipe 5.6). Self-asserted at
    # registration without a court order; the demo's pending-
    # review path.
    "id-internal-03441": {
        "identity_id":         "id-internal-03441",
        "linked_local_mrns":   ["local-patient-internal-03441"],
        "linked_member_ids":   [{"payer_id": "PAYER-03",
                                    "member_id": "MEM-303441-C"}],
        "current_name": {
            "given":          "Maria",
            "middle":         None,
            "family":         "Garcia",
            "suffix":         None,
            "effective_from": "2010-05-12",
            "effective_to":   None,
            "use":            "official",
            "source":         "registration_with_id_check",
            "event_id":       "evt-name-2010-05-12-initial",
        },
        "prior_names":  [],
        "aliases":      [],
        "dob":          "1972-03-14",
        "sex_assigned_at_birth": "F",
        "current_sex_or_gender": "F",
        "address_history": [
            {"value": "8810 Maple Ave, Chicago, IL 60618",
             "effective_from": "2019-01-15", "effective_to": None},
        ],
        "phone_history": [
            {"value": "+15557654321",
             "effective_from": "2019-01-15", "effective_to": None},
        ],
        "ssn_last4":    "1119",
        "cohort_bucket": "spanish_double_surname",
        "creation_date": "2010-05-12",
        "current_event_version": 1,
    },
    # Margaret Chen, payer-update-driven hyphenation. Indirect
    # detection at high confidence (the payer's eligibility
    # refresh carries a new name with strong demographic
    # alignment).
    "id-internal-04412": {
        "identity_id":         "id-internal-04412",
        "linked_local_mrns":   ["local-patient-internal-04412"],
        "linked_member_ids":   [{"payer_id": "PAYER-02",
                                    "member_id": "MEM-440412-D"}],
        "current_name": {
            "given":          "Margaret",
            "middle":         None,
            "family":         "Chen",
            "suffix":         None,
            "effective_from": "2015-07-08",
            "effective_to":   None,
            "use":            "official",
            "source":         "registration_with_id_check",
            "event_id":       "evt-name-2015-07-08-initial",
        },
        "prior_names":  [],
        "aliases":      [],
        "dob":          "1990-11-04",
        "sex_assigned_at_birth": "F",
        "current_sex_or_gender": "F",
        "address_history": [
            {"value": "27 Beacon Hill, Boston, MA 02108",
             "effective_from": "2020-08-20", "effective_to": None},
        ],
        "phone_history": [
            {"value": "+15558889999",
             "effective_from": "2020-08-20", "effective_to": None},
        ],
        "ssn_last4":    "9023",
        "cohort_bucket": "east_asian_traditional",
        "creation_date": "2015-07-08",
        "current_event_version": 1,
    },
    # An identity with sensitivity-classification needs. Court-
    # ordered legal name change with patient preferences for
    # masked prior-name display.
    "id-internal-07331": {
        "identity_id":         "id-internal-07331",
        "linked_local_mrns":   ["local-patient-internal-07331"],
        "linked_member_ids":   [{"payer_id": "PAYER-01",
                                    "member_id": "MEM-733100-X"}],
        "current_name": {
            "given":          "Alex",
            "middle":         None,
            "family":         "Mitchell",
            "suffix":         None,
            "effective_from": "2019-06-15",
            "effective_to":   None,
            "use":            "official",
            "source":         "registration_with_id_check",
            "event_id":       "evt-name-2019-06-15-initial",
        },
        "prior_names":  [],
        "aliases":      [],
        "dob":          "2001-02-18",
        "sex_assigned_at_birth": "M",
        "current_sex_or_gender": "F",
        "address_history": [
            {"value": "1408 Elm St, Portland, OR 97214",
             "effective_from": "2024-01-10", "effective_to": None},
        ],
        "phone_history": [
            {"value": "+15553334444",
             "effective_from": "2024-01-10", "effective_to": None},
        ],
        "ssn_last4":    "5566",
        "cohort_bucket": "english_traditional",
        "creation_date": "2019-06-15",
        "current_event_version": 1,
    },
}

# --- In-memory canonical event log ---
# Append-only list of all name-change events ever written. The
# current state of each identity is computed from the event log
# (in the demo, we keep both: the event log here and the
# computed current state in SYNTHETIC_IDENTITY_STORE). Production
# treats the event log as the source of truth and rebuilds the
# computed view from it on every change.
_IN_MEMORY_EVENT_LOG: list = []
_IN_MEMORY_OUTBOX:   list = []
_IN_MEMORY_REVIEW_QUEUE: list = []

# --- Reference data: nickname dictionary, surname-change
# patterns, transliteration maps, naming-tradition rules ---
class MockReferenceData:
    """Stand-in for the production reference-data store."""

    def __init__(self):
        # Nickname-and-diminutive lookup. One direction shown;
        # production handles bidirectional lookup and per-locale
        # variations.
        self.nicknames = {
            "catherine": {"cathy", "kate", "katie", "cat", "kit"},
            "margaret":  {"meg", "maggie", "peggy", "marge"},
            "maria":     {"mari", "mary"},
            "alex":      {"alexandra", "alexander", "alexis"},
            "william":   {"will", "bill", "billy", "willy"},
        }
        # Surname-change patterns. The most common patterns are
        # maiden-to-married (full replacement), hyphenation
        # (compound), suffix drop (Jr / Sr / II / III), and
        # transliteration variants.
        self.surname_patterns = [
            "maiden_to_married",
            "married_to_maiden",
            "hyphenation_added",
            "hyphenation_dropped",
            "suffix_added",
            "suffix_dropped",
            "transliteration_variant",
            "diacritic_strip",
            "spanish_double_to_single",
            "east_asian_order_swap",
        ]

    def is_known_nickname(self, full_name: str, nickname: str) -> bool:
        full = full_name.lower()
        nick = nickname.lower()
        if full == nick:
            return True
        return nick in self.nicknames.get(full, set())

    def detect_surname_pattern(self, prior_surname: str,
                                  new_surname: str) -> Optional[str]:
        """Return the best-matching surname-change pattern, or
        None if no plausible pattern fits. Production uses a
        learned model with per-pattern confidence."""
        prior = _canonical_name(prior_surname)
        new = _canonical_name(new_surname)
        if not prior or not new:
            return None
        # Hyphenation added: new contains prior as one component.
        if "-" in new and prior in new.split("-"):
            return "hyphenation_added"
        # Hyphenation dropped: prior contained new.
        if "-" in prior and new in prior.split("-"):
            return "hyphenation_dropped"
        # Suffix drop: same root, suffix removed.
        for suffix in [" jr", " sr", " ii", " iii"]:
            if prior.endswith(suffix) and prior[:-len(suffix)] == new:
                return "suffix_dropped"
            if new.endswith(suffix) and new[:-len(suffix)] == prior:
                return "suffix_added"
        # Diacritic / transliteration variant: same when stripped.
        if prior == new:
            return "diacritic_strip"
        # Maiden-to-married and married-to-maiden: full surname
        # replacement; we treat it as plausible if the given /
        # middle / DOB will carry the demographic match.
        return "maiden_to_married_or_replacement"

    def versions_used(self) -> dict:
        return dict(REFERENCE_DATA_VERSIONS)

# --- Patient preferences (output of patient-portal capture) ---
class MockPatientPreferences:
    """In-memory store for patient-expressed preferences for
    prior-name display, sensitivity classification, and audit
    delivery. Production reads from the patient-portal preference
    service; the demo stores them here keyed on identity_id."""

    def __init__(self):
        self._prefs: dict = {}

    def set_for_identity(self, identity_id: str, prefs: dict) -> None:
        self._prefs[identity_id] = prefs

    def get_for_identity(self, identity_id: str) -> dict:
        return self._prefs.get(identity_id, {"display_scope": "default"})

# --- Jurisdictional overlays ---
class MockJurisdictionalOverlays:
    """Stand-in for the institutional policy-overlay store. Real
    deployments encode state law, institutional policy, and HIE
    participation-agreement constraints with attorney-reviewed
    rules. The demo has a small example: a state-level rule that
    increases the audit posture for any GENDER_AFFIRMING change
    in the institution's home state."""

    def applicable_overlays(self, identity: dict, new_event: dict) -> list:
        overlays = []
        # Example: a state-level overlay that requires elevated
        # audit posture for gender-affirming changes regardless
        # of patient preference.
        if new_event.get("sensitivity_class") == "GENDER_AFFIRMING":
            overlays.append({
                "overlay_id":  "state-overlay-elevated-audit-2025",
                "description": "elevated audit posture",
                "applies_to": ["GENDER_AFFIRMING"],
                "constraints": {
                    "every_disclosure_logged": True,
                    "every_query_logged":      True,
                },
            })
        return overlays

# Module-level singletons for the demo.
reference_data           = MockReferenceData()
patient_preferences_db   = MockPatientPreferences()
jurisdictional_overlays  = MockJurisdictionalOverlays()
```

---

## Step 1: Detect a Name-Change Candidate from the Trigger Event

*The pseudocode calls this `detect_name_change_candidate(trigger_event)`. Every operational path that produces a name discrepancy goes through detection first. A registration update with a new name, a payer eligibility refresh with an updated name, a vital-records feed event, a cross-facility match callback that surfaced a different name on the responding side. The detector classifies the trigger as direct (an explicit name-change assertion) or indirect (a high-demographic-match arriving with a different name from the matched identity), pulls the candidate identity record, and produces a detection envelope. Skip the detection step and you treat every name discrepancy as a potential new identity, which over-creates duplicate records and corrupts the longitudinal continuity the recipe is supposed to maintain.*

```python
def _classify_source_strength(source_type: str) -> str:
    """Map a trigger source to its strength tier."""
    return SOURCE_STRENGTH.get(source_type, "WEAK")

def _identity_lookup_by_local_id(local_patient_id: str) -> Optional[dict]:
    """Stand-in for the active-search-index lookup by local MRN."""
    for identity in SYNTHETIC_IDENTITY_STORE.values():
        if local_patient_id in (identity.get("linked_local_mrns") or []):
            return identity
    return None

def _identity_lookup_by_member_id(payer_id: str,
                                      member_id: str) -> Optional[dict]:
    """Stand-in for the cross-reference lookup. Production uses
    the cross-reference table from recipe 5.4."""
    for identity in SYNTHETIC_IDENTITY_STORE.values():
        for link in identity.get("linked_member_ids") or []:
            if (link.get("payer_id") == payer_id
                    and link.get("member_id") == member_id):
                return identity
    return None

def _identity_search_by_name_and_demographics(
        name: dict, demographics: dict,
        as_of_date: str) -> Optional[dict]:
    """Stand-in for a demographic-features search against the
    active-search-index. Production runs a multi-strategy
    blocking-and-scoring pipeline (recipe 5.1 pattern) over the
    full population. The demo iterates and scores; for the demo
    population this is fine."""
    canonical_target_given  = _canonical_name(name.get("given"))
    canonical_target_family = _canonical_name(name.get("family"))
    target_dob              = demographics.get("dob")
    best_identity = None
    best_score    = Decimal("0")
    for identity in SYNTHETIC_IDENTITY_STORE.values():
        # DOB is the strongest stable feature; mismatch hurts.
        if identity.get("dob") != target_dob:
            continue
        # Address as-of-date alignment.
        addr_match = any(
            a["value"] == demographics.get("address")
            and (a.get("effective_to") is None or as_of_date <= a["effective_to"])
            and as_of_date >= a["effective_from"]
            for a in identity.get("address_history") or [])
        # SSN last-4 alignment when both sides carry it.
        ssn_match = (identity.get("ssn_last4") == demographics.get("ssn_last4")
                      if demographics.get("ssn_last4") else False)
        # Name-pair plausibility against current and prior names.
        name_match_score = Decimal("0")
        for candidate_name in [identity["current_name"]] + identity.get("prior_names", []):
            cand_given  = _canonical_name(candidate_name.get("given"))
            cand_family = _canonical_name(candidate_name.get("family"))
            if cand_given == canonical_target_given:
                name_match_score = max(name_match_score, Decimal("0.5"))
            if cand_family == canonical_target_family:
                name_match_score = max(name_match_score, Decimal("0.5"))
            if (cand_given == canonical_target_given
                    and cand_family == canonical_target_family):
                name_match_score = Decimal("1.0")
        score = name_match_score
        if addr_match: score += Decimal("0.3")
        if ssn_match:  score += Decimal("0.4")
        if score > best_score:
            best_score = score
            best_identity = identity
    return best_identity if best_score >= Decimal("0.5") else None

def _name_pair_plausibility(asserted_name: dict,
                                identity: dict) -> Decimal:
    """Score how plausible it is that the asserted name is a
    legal-change variant of one of the identity's known names.
    Combines given/middle preservation, surname-change pattern
    detection, nickname matching, and family-name distance."""
    asserted_given  = _canonical_name(asserted_name.get("given"))
    asserted_middle = _canonical_name(asserted_name.get("middle") or "")
    asserted_family = _canonical_name(asserted_name.get("family"))

    candidates = [identity["current_name"]] + identity.get("prior_names", [])
    best = Decimal("0")
    for cand in candidates:
        cand_given  = _canonical_name(cand.get("given"))
        cand_middle = _canonical_name(cand.get("middle") or "")
        cand_family = _canonical_name(cand.get("family"))

        # Component-level scoring.
        given_score = Decimal("0")
        if cand_given == asserted_given:
            given_score = Decimal("1.0")
        elif (reference_data.is_known_nickname(cand_given, asserted_given)
                or reference_data.is_known_nickname(asserted_given, cand_given)):
            given_score = Decimal("0.85")
        elif cand_given and asserted_given and cand_given[0] == asserted_given[0]:
            given_score = Decimal("0.30")

        middle_score = Decimal("0.5")  # neutral when missing
        if cand_middle and asserted_middle:
            middle_score = (Decimal("1.0") if cand_middle == asserted_middle
                              else Decimal("0.2"))

        family_score = Decimal("0")
        if cand_family == asserted_family:
            family_score = Decimal("1.0")
        else:
            pattern = reference_data.detect_surname_pattern(
                cand_family, asserted_family)
            if pattern in {"hyphenation_added", "hyphenation_dropped",
                              "suffix_added",       "suffix_dropped",
                              "diacritic_strip"}:
                # Mechanical-transformation patterns score high.
                family_score = Decimal("0.9")
            elif pattern is not None:
                # Replacement patterns (maiden-to-married,
                # transliteration variant, double-to-single)
                # score moderate; the demographic features carry
                # the rest of the match.
                family_score = Decimal("0.6")

        # Weighted combination favoring family-name pattern
        # detection (the most common name-change axis) and
        # given-name preservation.
        combined = (Decimal("0.30") * given_score
                       + Decimal("0.10") * middle_score
                       + Decimal("0.60") * family_score)
        best = max(best, combined)
    return best

def _demographic_match_strength(asserted_demographics: dict,
                                    identity: dict, as_of_date: str) -> Decimal:
    """Score non-name demographic alignment. DOB is the dominant
    signal; address-as-of-date and SSN last-4 are supporting."""
    score = Decimal("0")
    weight_total = Decimal("0")

    # DOB is highly stable; very strong signal.
    weight_total += Decimal("0.50")
    if identity.get("dob") == asserted_demographics.get("dob"):
        score += Decimal("0.50")

    # SSN last-4 if both present.
    if (asserted_demographics.get("ssn_last4")
            and identity.get("ssn_last4")):
        weight_total += Decimal("0.25")
        if identity["ssn_last4"] == asserted_demographics["ssn_last4"]:
            score += Decimal("0.25")

    # Address as-of-date alignment.
    if asserted_demographics.get("address"):
        weight_total += Decimal("0.15")
        for addr in identity.get("address_history") or []:
            if (addr["value"] == asserted_demographics["address"]
                    and as_of_date >= addr["effective_from"]
                    and (addr.get("effective_to") is None
                         or as_of_date <= addr["effective_to"])):
                score += Decimal("0.15")
                break

    # Phone match.
    if asserted_demographics.get("phone"):
        weight_total += Decimal("0.10")
        for ph in identity.get("phone_history") or []:
            if (ph["value"] == asserted_demographics["phone"]
                    and as_of_date >= ph["effective_from"]
                    and (ph.get("effective_to") is None
                         or as_of_date <= ph["effective_to"])):
                score += Decimal("0.10")
                break

    return score / weight_total if weight_total > 0 else Decimal("0.5")

def _temporal_plausibility(asserted_change_date: Optional[str],
                              identity: dict) -> Decimal:
    """Score whether the asserted change date is consistent with
    the identity's existing name history. A change dated before
    the identity was created is implausible; a change dated
    inside an existing prior name's span is suspicious; a change
    dated after the current name became effective is plausible."""
    if asserted_change_date is None:
        return Decimal("0.7")  # absence of date is mildly suspect
    if asserted_change_date < identity.get("creation_date", "1900-01-01"):
        return Decimal("0.1")
    current_from = identity["current_name"].get("effective_from")
    if current_from and asserted_change_date < current_from:
        # The assertion claims a change happened before the
        # current name became effective; that conflicts with the
        # existing history.
        return Decimal("0.3")
    return Decimal("1.0")

def _combine_detection_signals(features: dict,
                                  source_strength: str) -> Decimal:
    """Weighted combination of the three detection-signal
    features, then multiplied by the source-strength factor."""
    weighted = sum(DETECTION_SCORE_WEIGHTS[k] * features[k]
                     for k in DETECTION_SCORE_WEIGHTS)
    multiplier = SOURCE_STRENGTH_MULTIPLIER.get(source_strength,
                                                    Decimal("0.7"))
    return weighted * multiplier

def detect_name_change_candidate(trigger_event: dict) -> dict:
    """
    Classify the trigger as direct or indirect, find the
    candidate identity, and produce a detection envelope.
    """
    asserted_name           = trigger_event["asserted_name"]
    asserted_change_date    = trigger_event.get("asserted_change_date")
    asserted_prior_name     = trigger_event.get("asserted_prior_name")
    supporting_document_ref = trigger_event.get("supporting_document_ref")
    source_type             = trigger_event["source_type"]
    source_strength         = _classify_source_strength(source_type)
    as_of_date              = (trigger_event.get("event_date")
                                  or asserted_change_date
                                  or _now_iso()[:10])

    # 1A: identify the candidate identity by walking through the
    # available identifiers in priority order.
    candidate_identity = None
    if trigger_event.get("local_patient_id"):
        candidate_identity = _identity_lookup_by_local_id(
            trigger_event["local_patient_id"])
    if (candidate_identity is None
            and trigger_event.get("payer_id")
            and trigger_event.get("member_id")):
        candidate_identity = _identity_lookup_by_member_id(
            trigger_event["payer_id"], trigger_event["member_id"])
    if candidate_identity is None and asserted_prior_name:
        candidate_identity = _identity_search_by_name_and_demographics(
            asserted_prior_name,
            trigger_event.get("demographics") or {},
            as_of_date)
    if candidate_identity is None:
        # Indirect-detection path: search by the asserted name
        # plus other features. The threshold for accepting an
        # indirect candidate is higher (handled at resolution).
        candidate_identity = _identity_search_by_name_and_demographics(
            asserted_name,
            trigger_event.get("demographics") or {},
            as_of_date)
    if candidate_identity is None:
        # No candidate. This is a new identity, not a name change.
        # Hand off to recipe 5.1's new-record path.
        _emit_metric("DetectionResult", 1.0,
                      dimensions={"Outcome": "no_existing_identity"})
        return {
            "classification":  "NO_EXISTING_IDENTITY",
            "handoff_to":      "new_record_path_recipe_5_1",
            "trigger_event":   trigger_event,
        }

    # 1B: classify direct vs indirect.
    direct_signals = (
        asserted_prior_name is not None
        or asserted_change_date is not None
        or supporting_document_ref is not None
        or source_type in {"vital_records_feed",
                              "court_order",
                              "marriage_certificate",
                              "divorce_decree",
                              "drivers_license_scan_verified"}
    )
    change_type = "DIRECT" if direct_signals else "INDIRECT"

    # 1C: build the detection envelope.
    name_pair_plausibility   = _name_pair_plausibility(
        asserted_name, candidate_identity)
    demographic_strength     = _demographic_match_strength(
        trigger_event.get("demographics") or {},
        candidate_identity, as_of_date)
    temporal_plausibility    = _temporal_plausibility(
        asserted_change_date, candidate_identity)

    detection_score = _combine_detection_signals({
        "name_pair_plausibility":     name_pair_plausibility,
        "demographic_match_strength": demographic_strength,
        "temporal_plausibility":      temporal_plausibility,
    }, source_strength)

    cohort_bucket = candidate_identity.get("cohort_bucket", "unknown")
    _emit_metric("DetectionScore", float(detection_score),
                  dimensions={"CohortBucket":   cohort_bucket,
                                "ChangeType":     change_type,
                                "SourceStrength": source_strength})

    return {
        "classification":           change_type,
        "candidate_identity_id":    candidate_identity["identity_id"],
        "candidate_identity":       candidate_identity,
        "asserted_name":            asserted_name,
        "asserted_prior_name":      asserted_prior_name,
        "asserted_change_date":     asserted_change_date,
        "supporting_document_ref":  supporting_document_ref,
        "source_type":              source_type,
        "source_strength":          source_strength,
        "source_record_id":         trigger_event.get("source_record_id"),
        "detection_score":          detection_score,
        "evidence_summary": {
            "name_pair_plausibility":     name_pair_plausibility,
            "demographic_match_strength": demographic_strength,
            "temporal_plausibility":      temporal_plausibility,
        },
        "reference_data_versions":  reference_data.versions_used(),
        "matcher_config_version":   MATCHER_CONFIG_VERSION,
        "trigger_event_id":         trigger_event.get("event_id"),
        # TODO (TechWriter): Code review Finding 1 (ERROR). The
        # detection envelope must propagate `explicit_sensitivity_class`
        # from the trigger event so `_classify_sensitivity` (which reads
        # `candidate.get("explicit_sensitivity_class")`) can see it.
        # Without this line, Trigger 4's GENDER_AFFIRMING path silently
        # defaults to GENERAL: the envelope's permitted_display_contexts
        # collapses to [] under the patient's masked preference, audit
        # rules retain the GENERAL defaults, and propagate_to_dependents
        # selects the 9-consumer GENERAL fan-out instead of the
        # 6-consumer restricted fan-out. Add:
        #   "explicit_sensitivity_class":
        #       trigger_event.get("explicit_sensitivity_class"),
        # then re-run the demo and verify Trigger 4's printed
        # sensitivity_class is GENDER_AFFIRMING, permitted_display_contexts
        # is ['treatment_with_clinical_relevance'], audit_rules include
        # every_disclosure_logged: True and every_query_logged: True,
        # and the consumer fan-out is the 6-consumer restricted set
        # including audit_summary_to_patient.
        "detected_at":              _now_iso(),
    }
```

---

## Step 2: Resolve the Candidate Against the Existing Identity Record

*The pseudocode calls this `resolve_name_change(detection_envelope, matcher_config)`. The detector produced a candidate; the resolver decides whether to accept it as a name change, hold it for review, or reject it. The resolver consults the identity's existing name history, applies the name-change-specific thresholds, and produces a resolution decision with the evidence preserved for audit. Skip the explicit resolution step and you have a detector that flags candidates without a clear handoff to the persistence layer; the result is name-change events that get partially recorded and then drift out of sync with the rest of the patient record.*

```python
def _classify_sensitivity(candidate: dict, identity: dict) -> str:
    """Default sensitivity classification. Production extends
    this with patient-portal preference capture, gender-affirming-
    care service-line workflow signals, legal-hold tags from the
    institution's risk-management system, and protective-custody
    flags from law-enforcement coordination. The demo's logic is
    deliberately small."""
    # Trigger event may carry an explicit class (set by the
    # gender-affirming-care intake workflow, the patient portal,
    # or a compliance officer).
    explicit = candidate.get("explicit_sensitivity_class")
    if explicit:
        return explicit
    # Default everything else to GENERAL.
    return "GENERAL"

def _infer_effective_date(candidate: dict, identity: dict) -> str:
    """Infer the change-effective date when the assertion did
    not carry one. Use the trigger's event date as a fallback;
    production has more careful logic that reads document
    metadata where available."""
    return (candidate.get("asserted_change_date")
              or candidate.get("detected_at", _now_iso())[:10])

def _compute_updated_identity_state(identity: dict,
                                       new_event: dict) -> dict:
    """Apply the new name event to the computed current state.
    The current name becomes a prior name; the asserted name
    becomes the current name."""
    updated = json.loads(json.dumps(identity, default=str))
    old_current = dict(updated["current_name"])
    old_current["effective_to"] = new_event["change_effective_date"]
    old_current["use"] = "old"
    if "prior_names" not in updated or updated["prior_names"] is None:
        updated["prior_names"] = []
    updated["prior_names"].append(old_current)
    updated["current_name"] = {
        "given":          new_event["new_current_name"]["given"],
        "middle":         new_event["new_current_name"].get("middle"),
        "family":         new_event["new_current_name"]["family"],
        "suffix":         new_event["new_current_name"].get("suffix"),
        "effective_from": new_event["change_effective_date"],
        "effective_to":   None,
        "use":            "official",
        "source":         new_event["source"],
        "event_id":       new_event["event_id"],
    }
    updated["current_event_version"] = (
        identity.get("current_event_version", 0) + 1)
    return updated

def resolve_name_change(detection_envelope: dict) -> dict:
    """
    Apply the name-change-specific thresholds to the detection
    envelope. Produce one of: AUTO_RESOLVE_HIGH,
    AUTO_RESOLVE_MED_DOCUMENTED, AUTO_RESOLVE_INDIRECT_HIGH,
    REVIEW_PENDING_DIRECT, REVIEW_PENDING_INDIRECT,
    REJECT_INSUFFICIENT_EVIDENCE, REJECT_LIKELY_DIFFERENT_PERSON.
    """
    if detection_envelope.get("classification") == "NO_EXISTING_IDENTITY":
        return {"resolution": "HANDOFF_TO_NEW_RECORD_PATH",
                "envelope":   detection_envelope}

    candidate = detection_envelope
    identity  = candidate["candidate_identity"]
    score     = candidate["detection_score"]
    strength  = candidate["source_strength"]

    # 2A: apply thresholds. Direct and indirect are routed
    # differently; indirect at any band requires more demographic
    # alignment than direct at the same band.
    if candidate["classification"] == "DIRECT":
        if score >= DIRECT_NAME_CHANGE_HIGH_THRESHOLD:
            resolution = "AUTO_RESOLVE_HIGH"
        elif score >= DIRECT_NAME_CHANGE_MED_THRESHOLD:
            if strength == "STRONG":
                resolution = "AUTO_RESOLVE_MED_DOCUMENTED"
            else:
                resolution = "REVIEW_PENDING_DIRECT"
        elif score <= NAME_CHANGE_REJECT_THRESHOLD:
            resolution = "REJECT_INSUFFICIENT_EVIDENCE"
        else:
            resolution = "REVIEW_PENDING_DIRECT"
    else:  # INDIRECT
        if score >= INDIRECT_NAME_CHANGE_HIGH_THRESHOLD:
            resolution = "AUTO_RESOLVE_INDIRECT_HIGH"
        elif score >= INDIRECT_NAME_CHANGE_MED_THRESHOLD:
            resolution = "REVIEW_PENDING_INDIRECT"
        elif score <= NAME_CHANGE_REJECT_THRESHOLD:
            resolution = "REJECT_LIKELY_DIFFERENT_PERSON"
        else:
            resolution = "REVIEW_PENDING_INDIRECT"

    cohort_bucket = identity.get("cohort_bucket", "unknown")
    _emit_metric("ResolutionOutcome", 1.0,
                  dimensions={"Outcome":      resolution,
                                "CohortBucket": cohort_bucket,
                                "ChangeType":   candidate["classification"]})

    # 2B: build the resolution payload.
    if resolution in {"AUTO_RESOLVE_HIGH",
                         "AUTO_RESOLVE_MED_DOCUMENTED",
                         "AUTO_RESOLVE_INDIRECT_HIGH"}:
        new_event = {
            "event_id":          f"evt-name-{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H-%M-%S')}-{uuid.uuid4().hex[:6]}",
            "event_type":        "NAME_CHANGE",
            "previous_current_name": dict(identity["current_name"]),
            "new_current_name":  candidate["asserted_name"],
            "change_effective_date":
                _infer_effective_date(candidate, identity),
            "source":             candidate["source_type"],
            "source_strength":    candidate["source_strength"],
            "source_record_id":   candidate.get("source_record_id"),
            "supporting_document_ref":
                candidate.get("supporting_document_ref"),
            "detection_score":    candidate["detection_score"],
            "evidence_summary":   candidate["evidence_summary"],
            "matcher_config_version": MATCHER_CONFIG_VERSION,
            "reference_data_versions":
                candidate["reference_data_versions"],
            "sensitivity_class":  _classify_sensitivity(
                candidate, identity),
            "resolved_at":        _now_iso(),
            "resolved_by":        "automated",
        }
        return {
            "resolution":              resolution,
            "new_event":               new_event,
            "updated_identity_state":  _compute_updated_identity_state(
                identity, new_event),
            "candidate_identity":      identity,
        }

    if resolution in {"REVIEW_PENDING_DIRECT",
                         "REVIEW_PENDING_INDIRECT"}:
        pending_item = {
            "pending_id":             f"pending-{uuid.uuid4().hex[:10]}",
            "candidate_identity_id":  identity["identity_id"],
            "candidate":              candidate,
            "held_at":                _now_iso(),
            "requires": ["human_review"]
                + ([] if candidate["source_strength"] == "STRONG"
                       else ["supporting_document"]),
        }
        try:
            sqs_client.send_message(
                QueueUrl=NAME_CHANGE_REVIEW_QUEUE_URL,
                MessageBody=json.dumps(pending_item, default=str),
            )
        except Exception as exc:
            logger.info("review queue send skipped (demo mode)",
                         extra={"error": str(exc)})
        _IN_MEMORY_REVIEW_QUEUE.append(pending_item)
        return {
            "resolution":              resolution,
            "pending_item":            pending_item,
            "updated_identity_state":  identity,  # unchanged
            "candidate_identity":      identity,
        }

    # REJECT_*
    return {
        "resolution":             resolution,
        "rejected_candidate":     candidate,
        "updated_identity_state": identity,  # unchanged
        "candidate_identity":     identity,
        "rejection_reason":       resolution,
    }
```

---

## Step 3: Apply the Sensitivity and Consent Envelope

*The pseudocode calls this `apply_sensitivity_and_consent_envelope(resolution_envelope, identity, patient_preferences, jurisdictional_overlays)`. A resolved name change carries a sensitivity classification and an access-control envelope. The classification reflects the type of change (general, gender-affirming, protective-custody, intimate-partner-violence, witness-protection, patient-requested-restricted) and the patient's expressed preferences for prior-name display. The envelope encodes the access rules that downstream consumers (chart-rendering, release-of-information, patient-portal) must honor. Skip the sensitivity envelope and the prior name surfaces in places the patient did not consent to, which is a dignity violation and, in some jurisdictions, a regulatory violation.*

```python
def _derive_display_contexts(sensitivity_class: str,
                                patient_pref: dict,
                                overlays: list) -> list:
    """Compose the permitted-display-contexts list. Patient
    preferences may further restrict (but never expand) the
    defaults; jurisdictional overlays may further restrict but
    never expand."""
    base = list(DEFAULT_ENVELOPE_BY_CLASS[sensitivity_class][
        "permitted_display_contexts"])
    pref = (patient_pref or {}).get("display_scope")
    if pref == "treatment_only":
        base = [c for c in base
                  if c.startswith("treatment")]
    elif pref == "masked":
        base = [c for c in base
                  if c == "treatment_with_clinical_relevance"
                     or c == "audit_only"]
    elif pref == "archive_only":
        base = ["audit_only"]
    return base

def _derive_release_scopes(sensitivity_class: str,
                              patient_pref: dict,
                              overlays: list) -> list:
    """Compose the permitted-release-scopes list. Patient-Access
    API release is preserved across all classes (it is the
    information-blocking obligation under the 21st Century Cures
    Act); other scopes may be removed by patient preference or
    by overlays."""
    base = list(DEFAULT_ENVELOPE_BY_CLASS[sensitivity_class][
        "permitted_release_scopes"])
    pref = (patient_pref or {}).get("display_scope")
    if pref in {"treatment_only", "masked", "archive_only"}:
        # Restricted scopes preserve patient_access_api and drop
        # the broader operations and treatment-disclosure scopes.
        base = [s for s in base if s == "patient_access_api"]
    return base

def _derive_audit_rules(sensitivity_class: str,
                          patient_pref: dict,
                          overlays: list) -> dict:
    """Compose the audit-rules object. Higher sensitivity classes
    log more; jurisdictional overlays may add additional logging.
    Patient preferences (audit summaries to portal) layer on top."""
    base = dict(DEFAULT_ENVELOPE_BY_CLASS[sensitivity_class][
        "audit_rules"])
    for overlay in overlays or []:
        constraints = overlay.get("constraints") or {}
        for k, v in constraints.items():
            base[k] = v or base.get(k, False)
    if (patient_pref or {}).get("monthly_summary_to_patient_portal"):
        base["monthly_summary_to_patient_portal"] = True
    return base

def apply_sensitivity_and_consent_envelope(resolution_envelope: dict
                                                ) -> dict:
    """Build the access-control envelope for the resolved event.
    Returns the envelope dict to be attached to the event before
    persistence."""
    if resolution_envelope.get("resolution") not in {
            "AUTO_RESOLVE_HIGH",
            "AUTO_RESOLVE_MED_DOCUMENTED",
            "AUTO_RESOLVE_INDIRECT_HIGH"}:
        # Pending and rejected resolutions don't get an envelope
        # written yet; the envelope is built when the resolution
        # transitions to AUTO_RESOLVE.
        return None

    new_event = resolution_envelope["new_event"]
    identity  = resolution_envelope["candidate_identity"]
    sensitivity_class = new_event["sensitivity_class"]
    patient_pref = patient_preferences_db.get_for_identity(
        identity["identity_id"])
    overlays = jurisdictional_overlays.applicable_overlays(
        identity, new_event)

    envelope = {
        "prior_name_event_id":   new_event["event_id"],
        "sensitivity_class":     sensitivity_class,
        "patient_preference":    patient_pref,
        "jurisdictional_overlays": overlays,
        "permitted_display_contexts":
            _derive_display_contexts(sensitivity_class, patient_pref,
                                          overlays),
        "permitted_release_scopes":
            _derive_release_scopes(sensitivity_class, patient_pref,
                                       overlays),
        "audit_rules":
            _derive_audit_rules(sensitivity_class, patient_pref,
                                    overlays),
        "envelope_version":      1,
        "envelope_built_at":     _now_iso(),
    }
    return envelope
```

---

## Step 4: Persist the Resolved Name Change Atomically with the Audit Log

*The pseudocode calls this `persist_resolved_name_change(resolution_envelope, access_control_envelope)`. The persistence step writes the new event to the identity-temporal-name table, updates the active-search-index, archives the resolution to the audit S3 bucket, and emits the cross-recipe event. Use a transactional write so partial failures do not leave the system in an inconsistent state. Skip the transactional discipline and you produce identity records whose name history disagrees with the search index, which causes the matcher to make decisions on stale data and the analytics layer to deduplicate incorrectly.*

```python
def _build_search_index_entries(updated_identity: dict,
                                    new_event: dict,
                                    envelope: dict) -> list:
    """Build the active-search-index entries for the identity's
    current name and any prior names. Each entry carries the
    sensitivity envelope so the matcher's read path can apply
    the access rules at query time."""
    entries = []
    for name_obj in [updated_identity["current_name"]] + (
            updated_identity.get("prior_names") or []):
        entries.append({
            "search_key":            _canonical_name(
                name_obj.get("given"), name_obj.get("family")),
            "identity_id":           updated_identity["identity_id"],
            "name_use":              name_obj.get("use", "official"),
            "effective_from":        name_obj.get("effective_from"),
            "effective_to":          name_obj.get("effective_to"),
            "event_id":              name_obj.get("event_id"),
            "sensitivity_class":     envelope.get("sensitivity_class")
                                     if envelope else "GENERAL",
            "permitted_display_contexts":
                envelope.get("permitted_display_contexts")
                if envelope
                else DEFAULT_ENVELOPE_BY_CLASS["GENERAL"][
                    "permitted_display_contexts"],
        })
    return entries

def persist_resolved_name_change(resolution_envelope: dict,
                                      access_control_envelope: dict) -> dict:
    """Write the event, update the search index, and write the
    outbox row. Production wraps these in a TransactWriteItems
    call so persistence is atomic; the demo writes to in-memory
    structures with the same shape."""
    if resolution_envelope.get("resolution") not in {
            "AUTO_RESOLVE_HIGH",
            "AUTO_RESOLVE_MED_DOCUMENTED",
            "AUTO_RESOLVE_INDIRECT_HIGH"}:
        # Pending and rejected go through different paths;
        # nothing to persist as a resolved event here.
        return {"persisted": False, "reason": resolution_envelope["resolution"]}

    new_event         = resolution_envelope["new_event"]
    identity          = resolution_envelope["candidate_identity"]
    updated_identity  = resolution_envelope["updated_identity_state"]

    # 4A: build the canonical identity-event record. Append-only
    # event in the identity's history; current state is computed
    # from the event log.
    identity_event_record = _serialize_for_dynamodb({
        "identity_id":            updated_identity["identity_id"],
        "event_version":          updated_identity["current_event_version"],
        "event_id":               new_event["event_id"],
        "event_type":             "NAME_CHANGE",
        "event_payload":          new_event,
        "access_control_envelope": access_control_envelope,
        "emitted_to_eventbus_at": None,
        "archived_to_s3_at":      None,
        "created_at":             _now_iso(),
    })

    # 4B: update the active-search-index with the new name and
    # the demoted prior name.
    search_index_entries = _build_search_index_entries(
        updated_identity, new_event, access_control_envelope)

    # 4C: write event + index update + outbox row in one
    # transaction. Production uses DynamoDB TransactWriteItems
    # with a condition expression on the expected_event_version
    # to prevent concurrent updates from clobbering one another.
    outbox_event_type = ("identity_name_change_resolved_restricted"
                            if access_control_envelope.get("sensitivity_class")
                                != "GENERAL"
                            else "identity_name_change_resolved")
    outbox_row = {
        "outbox_id":  f"ob-{uuid.uuid4().hex}",
        "event_type": outbox_event_type,
        "identity_id": updated_identity["identity_id"],
        "event_id":    new_event["event_id"],
        "payload":     identity_event_record,
        "access_control_envelope": access_control_envelope,
        "emitted_at":  None,
        "archived_at": None,
    }

    try:
        # In production: dynamodb.meta.client.transact_write_items(...).
        # The demo writes per table for readability.
        # TODO (TechWriter): Code review Finding 2 (WARNING). The
        # ConditionExpression below references `expected_event_version`,
        # which is not an attribute on either the new item or any
        # existing item at the same primary key (the actual attribute
        # is `event_version` on the new item, and the IDENTITY_TABLE
        # row carries `current_event_version`). Combined with
        # `attribute_not_exists(event_id) AND ...`, this evaluates to
        # false on every put_item, so production calls would always
        # raise ConditionalCheckFailedException; the bug is masked in
        # the demo by the broad `except Exception` swallow below.
        # Two corrections (pick the intent that matches the
        # architectural design):
        #   (a) For "this (identity_id, event_version) row is new"
        #       on the EVENT_HISTORY_TABLE: use
        #         ConditionExpression="attribute_not_exists(identity_id)"
        #       and drop the ExpressionAttributeValues.
        #   (b) For optimistic concurrency on the IDENTITY_TABLE
        #       computed-current-state row: move the version check
        #       to the IDENTITY_TABLE put with
        #         ConditionExpression="current_event_version = :ev"
        #       (the actual attribute name) and use
        #         attribute_not_exists(identity_id) on the
        #       EVENT_HISTORY_TABLE put for append-only enforcement.
        # Code review Finding 5 (NOTE): the four put_item calls are
        # not atomic; production wraps them in TransactWriteItems so
        # the event log, search index, identity table, and outbox
        # stay consistent on partial failure.
        dynamodb.Table(EVENT_HISTORY_TABLE).put_item(
            Item=identity_event_record,
            ConditionExpression=(
                "attribute_not_exists(event_id) AND "
                "expected_event_version = :ev"),
            ExpressionAttributeValues={
                ":ev": _to_decimal(
                    identity.get("current_event_version", 0))},
        )
        for entry in search_index_entries:
            dynamodb.Table(SEARCH_INDEX_TABLE).put_item(
                Item=_serialize_for_dynamodb(entry))
        dynamodb.Table(IDENTITY_TABLE).put_item(
            Item=_serialize_for_dynamodb(updated_identity))
        dynamodb.Table(EVENT_OUTBOX_TABLE).put_item(
            Item=_serialize_for_dynamodb(outbox_row))
    except Exception as exc:
        logger.info("persist skipped (demo mode is fine to ignore)",
                     extra={"error": str(exc)})

    # In-memory state for the demo's read path.
    SYNTHETIC_IDENTITY_STORE[updated_identity["identity_id"]] = (
        updated_identity)
    _IN_MEMORY_EVENT_LOG.append(identity_event_record)
    _IN_MEMORY_OUTBOX.append(outbox_row)

    # 4D: archive to S3 audit bucket (Object Lock in Compliance
    # mode in production).
    _archive_to_s3(identity_event_record, AUDIT_ARCHIVE_BUCKET,
                     "name-change-events",
                     key_id=new_event["event_id"])

    _emit_metric("EventsPersisted", 1.0,
                  dimensions={
                      "SensitivityClass":
                          access_control_envelope.get(
                              "sensitivity_class", "GENERAL"),
                      "ChangeType": ("DIRECT"
                                       if "DIRECT" in resolution_envelope[
                                              "resolution"]
                                          or resolution_envelope[
                                              "resolution"] in
                                              {"AUTO_RESOLVE_HIGH",
                                               "AUTO_RESOLVE_MED_DOCUMENTED"}
                                       else "INDIRECT"),
                  })
    return {"persisted":          True,
            "identity_event_record": identity_event_record,
            "outbox_row":          outbox_row}
```

---

## Step 5: Propagate the Resolution to Dependent Stores

*The pseudocode calls this `propagate_to_dependents(identity_event_record, access_control_envelope)`. The downstream consumers maintain their own derived state that depends on the identity's name. The local MPI from recipe 5.1 needs the new name in its master record. The cross-reference table from recipe 5.4 may need an update if the eligibility cross-reference was keyed on the prior name in any way. The cross-facility matcher from recipe 5.5 needs to refresh its prior-name handling for query responses. The chart-rendering layer needs the updated name-history view. Skip the propagation step and the downstream consumers continue to operate on stale data, producing decisions and displays that disagree with the canonical identity store.*

```python
def propagate_to_dependents(persistence_result: dict) -> dict:
    """Drain the outbox and emit the cross-recipe event. In
    production this is a separate Lambda or DynamoDB Streams
    consumer that decouples the persistence transaction from the
    event emit. Here we run synchronously."""
    if not persistence_result.get("persisted"):
        return {"propagated": False,
                "reason":     persistence_result.get("reason")}

    record   = persistence_result["identity_event_record"]
    outbox   = persistence_result["outbox_row"]
    envelope = outbox.get("access_control_envelope") or {}

    # 5A: emit the cross-recipe event to the resolved-event bus.
    # EventBridge rules route to the downstream consumers based
    # on detail-type and on the sensitivity class in the
    # envelope. Restricted-class events go to a smaller, more-
    # tightly-controlled set of consumers.
    detail = {
        "identity_id":             record["identity_id"],
        "event_id":                record["event_id"],
        "event_version":           record["event_version"],
        "previous_state": {
            "current_name":
                record["event_payload"]["previous_current_name"],
        },
        "new_state": {
            "current_name":
                record["event_payload"]["new_current_name"],
        },
        "change_effective_date":
            record["event_payload"]["change_effective_date"],
        "sensitivity_class":       envelope.get("sensitivity_class"),
        "matcher_config_version":
            record["event_payload"]["matcher_config_version"],
        "evidence_summary":
            record["event_payload"]["evidence_summary"],
        "access_control_envelope": envelope,
        "detected_at":             record["created_at"],
    }
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "longitudinal-name-change",
            "DetailType":   outbox["event_type"],
            "EventBusName": RESOLVED_EVENT_BUS_NAME,
            "Detail":       json.dumps(detail, default=str),
        }])
    except Exception as exc:
        logger.info("event emit skipped (demo mode is fine to ignore)",
                     extra={"error": str(exc)})

    # 5B: simulate downstream consumer behavior. In production
    # each consumer is its own Lambda subscribed via an
    # EventBridge rule and handles its own idempotency. The demo
    # records the simulated calls so the trace shows the fan-out.
    consumer_calls = []
    if envelope.get("sensitivity_class") == "GENERAL" or not envelope:
        consumer_calls.extend([
            ("local_mpi_recipe_5_1",       "update_master_record"),
            ("eligibility_xref_5_4",       "refresh_demographic_snapshot"),
            ("cross_facility_matcher_5_5", "refresh_mpi_projection"),
            ("claims_clinical_5_6",        "enqueue_relink_for_patient"),
            ("chart_rendering",            "invalidate_render_cache"),
            ("release_of_information",     "invalidate_roi_render_cache"),
            ("patient_portal",             "update_view_and_pref_ui"),
            ("quality_risk_adj",           "enqueue_quality_refresh"),
            ("healthlake_fhir",            "update_patient_name_list"),
        ])
    else:
        # Restricted-class consumers: smaller fan-out, more
        # auditing.
        consumer_calls.extend([
            ("local_mpi_recipe_5_1",       "update_master_record_restricted"),
            ("chart_rendering",            "invalidate_render_cache_restricted"),
            ("release_of_information",     "invalidate_roi_render_cache_restricted"),
            ("patient_portal",             "update_view_and_pref_ui_restricted"),
            ("healthlake_fhir",            "update_patient_name_list_restricted"),
            ("audit_summary_to_patient",   "schedule_per_patient_summary"),
        ])

    # 5C: archive the curated payload to the derived snapshot
    # bucket for analytics consumption.
    _archive_to_s3({
        "identity_id": record["identity_id"],
        "event_id":    record["event_id"],
        "current_name_redacted":
            envelope.get("sensitivity_class") != "GENERAL",
        "envelope_summary": {
            "sensitivity_class": envelope.get("sensitivity_class"),
            "permitted_display_contexts":
                envelope.get("permitted_display_contexts"),
        },
        "change_effective_date":
            record["event_payload"]["change_effective_date"],
    }, DERIVED_SNAPSHOT_BUCKET, "name-change-snapshots",
        key_id=record["event_id"])

    return {
        "propagated":     True,
        "event_emitted":  True,
        "consumer_calls": consumer_calls,
        "envelope_class": envelope.get("sensitivity_class"),
    }
```

---

## Step 6: React to Invalidation Events That Supersede Prior Resolutions

*The pseudocode calls this `invalidate_on_event(invalidation_event)`. A name-change resolution is not permanent. It can be corrected (a wrong assertion was recorded), reversed (the patient changed back), superseded by an identity merge from recipe 5.1, updated by a sensitivity-classification change (the patient has expressed new preferences), upgraded by a document-strength promotion (a previously self-reported change is now backed by a court order). The invalidation pipeline subscribes to these events and selectively re-resolves the affected identities. Skip the invalidation pipeline and the resolved-name-change records drift out of sync with the rest of the institution's identity infrastructure; the drift compounds over time.*

```python
def invalidate_on_event(invalidation_event: dict) -> dict:
    """Re-evaluate linkages affected by an invalidation event.
    Production triggers a Lambda that handles the specific
    superseding-event type and re-runs the resolver on the
    affected identity. The demo records what would be done."""
    source = invalidation_event.get("source")
    summary = {
        "source":               source,
        "event_id":             invalidation_event.get("event_id"),
        "actions":              [],
        "affected_identities":  [],
    }

    if source == "correction":
        identity_id = invalidation_event["identity_id"]
        prior_event_id = invalidation_event["superseded_event_id"]
        summary["affected_identities"] = [identity_id]
        summary["actions"].append(
            f"mark_event_superseded:{prior_event_id}")
        summary["actions"].append("re_resolve_with_correction_payload")

    elif source == "reversal":
        # The patient changed back. Treat as a new name-change
        # event whose "new" name is the previously-prior name.
        identity_id = invalidation_event["identity_id"]
        summary["affected_identities"] = [identity_id]
        summary["actions"].append("emit_reversal_event")
        summary["actions"].append("update_current_name_to_prior")

    elif source == "identity_merge":
        # Recipe 5.1 merged two identities. Both name histories
        # fold into the surviving identity.
        merged_from = invalidation_event["merged_from_identity_id"]
        merged_into = invalidation_event["merged_into_identity_id"]
        summary["affected_identities"] = [merged_from, merged_into]
        summary["actions"].append("fold_name_histories_into_surviving")

    elif source == "identity_unmerge":
        # A prior merge is being reversed. Name histories split
        # back to their pre-merge identities.
        summary["affected_identities"] = [
            invalidation_event["unmerged_to_identity_id_a"],
            invalidation_event["unmerged_to_identity_id_b"],
        ]
        summary["actions"].append("split_name_histories_to_pre_merge")

    elif source == "sensitivity_update":
        # Patient (or authorized representative) updated the
        # sensitivity classification or display preferences for
        # an existing event. Update the access_control_envelope
        # only; do not modify the name event itself.
        identity_id = invalidation_event["identity_id"]
        event_id = invalidation_event["event_id"]
        new_payload = invalidation_event["new_envelope_payload"]
        summary["affected_identities"] = [identity_id]
        summary["actions"].append(
            f"update_envelope_for_event:{event_id}")
        # Update the patient-preferences mock so future events
        # consume the new preference.
        patient_preferences_db.set_for_identity(
            identity_id, new_payload.get("patient_preference") or {})

    elif source == "document_upgrade":
        # A previously self-reported change now has a supporting
        # document. Source-strength is upgraded; resolution may
        # promote from REVIEW_PENDING to AUTO_RESOLVE.
        identity_id = invalidation_event["identity_id"]
        event_id = invalidation_event["event_id"]
        summary["affected_identities"] = [identity_id]
        summary["actions"].append(
            f"upgrade_source_strength_for_event:{event_id}")
        summary["actions"].append(
            "promote_pending_to_resolved_if_eligible")

    elif source == "cross_facility_match_invalidated":
        # Recipe 5.5 retracted a cross-facility linkage that
        # affected this identity's prior-name handling.
        identity_id = invalidation_event.get("identity_id")
        summary["affected_identities"] = [identity_id] if identity_id else []
        summary["actions"].append(
            "re_evaluate_search_index_for_identity")

    else:
        summary["actions"].append("unknown_invalidation_source")

    # Emit the aggregate invalidation event for downstream
    # consumers (chart-rendering, release-of-information,
    # patient-portal, claims-clinical linkage) to refresh.
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "longitudinal-name-change",
            "DetailType":   "identity_name_change_invalidated",
            "EventBusName": RESOLVED_EVENT_BUS_NAME,
            "Detail":       json.dumps({
                "invalidation_source":  source,
                "invalidation_event_id":
                    invalidation_event.get("event_id"),
                "affected_identities":  summary["affected_identities"],
                "invalidated_at":       _now_iso(),
            }, default=str),
        }])
    except Exception as exc:
        logger.info("invalidation event emit skipped (demo mode)",
                     extra={"error": str(exc)})

    _emit_metric("Invalidations", 1.0,
                  dimensions={"Source": source or "unknown"})
    return summary
```

---

## Full Pipeline

The pipeline assembles the six steps into a single callable function. In production these are separate Lambdas (for the operational stream) and Glue jobs (for periodic reconciliation and historical backfill) orchestrated by Step Functions; here we run them in-process so the trace is easy to follow.

```python
def run_pipeline(trigger_event: dict) -> dict:
    """End-to-end detect -> resolve -> envelope -> persist ->
    propagate pipeline for a single trigger event. Returns the
    full trace (detection envelope, resolution, envelope,
    persistence result, propagation result)."""
    detection = detect_name_change_candidate(trigger_event)
    resolution = resolve_name_change(detection)
    envelope = apply_sensitivity_and_consent_envelope(resolution)
    persistence = persist_resolved_name_change(resolution, envelope)
    propagation = propagate_to_dependents(persistence)
    return {
        "trigger":     trigger_event,
        "detection":   detection,
        "resolution":  resolution,
        "envelope":    envelope,
        "persistence": persistence,
        "propagation": propagation,
    }

def run_demo():
    """Run the full pipeline against four representative trigger
    events covering the auto-resolve, pending-review, indirect-
    detection, and sensitivity-classified paths, then exercise
    the invalidation pipeline."""
    print("=" * 70)
    print("Longitudinal Patient Matching Across Name Changes Demo")
    print("=" * 70)
    print()
    print("All patients, names, and supporting documents in this demo")
    print("are fictional. The mock identity store, reference data,")
    print("patient preferences, and jurisdictional overlays return")
    print("hand-crafted data that exercises the resolution paths;")
    print("do not point this demo at a live MPI.")
    print()
    print(f"Direct thresholds:   HIGH={DIRECT_NAME_CHANGE_HIGH_THRESHOLD}  "
          f"MED={DIRECT_NAME_CHANGE_MED_THRESHOLD}")
    print(f"Indirect thresholds: HIGH={INDIRECT_NAME_CHANGE_HIGH_THRESHOLD} "
          f"MED={INDIRECT_NAME_CHANGE_MED_THRESHOLD}")
    print(f"Reject threshold:    {NAME_CHANGE_REJECT_THRESHOLD}")
    print(f"Matcher version:     {MATCHER_CONFIG_VERSION}")
    print()

    # --- Trigger 1: Catherine Wilson -> Catherine Hernandez ---
    # Court-order-backed direct change. Should auto-resolve at
    # high confidence.
    print("-" * 70)
    print("Trigger 1: court-ordered legal name change")
    print("           (Catherine Marie Wilson -> Catherine Marie Hernandez)")
    print("-" * 70)
    trigger_1 = {
        "event_id":        "trig-2026-04-22-001",
        "source_type":     "court_order",
        "source_record_id": "doc-court-order-2026-04-22-001",
        "local_patient_id": "local-patient-internal-00874",
        "asserted_name": {
            "given":  "Catherine",
            "middle": "Marie",
            "family": "Hernandez",
        },
        "asserted_prior_name": {
            "given":  "Catherine",
            "middle": "Marie",
            "family": "Wilson",
        },
        "asserted_change_date": "2026-04-22",
        "supporting_document_ref":
            "s3://my-name-change-supporting-documents/"
            "id-internal-00874/court-order-2026-04-22-001.pdf",
        "demographics": {
            "dob":       "1985-03-22",
            "address":   "412 Oak St, Springfield, IL 62701",
            "phone":     "+15551234567",
            "ssn_last4": "4287",
        },
        "event_date":  "2026-04-22",
    }
    result_1 = run_pipeline(trigger_1)
    print(f"  detection.classification:  {result_1['detection']['classification']}")
    print(f"  detection_score:           "
          f"{float(result_1['detection']['detection_score']):.3f}")
    print(f"  resolution:                {result_1['resolution']['resolution']}")
    print(f"  sensitivity_class:         "
          f"{result_1['envelope']['sensitivity_class']}")
    print(f"  permitted_display_contexts:"
          f" {result_1['envelope']['permitted_display_contexts']}")
    print(f"  consumers fanned to:       "
          f"{[c[0] for c in result_1['propagation']['consumer_calls']]}")

    # --- Trigger 2: Maria Garcia -> Maria Garcia-Lopez ---
    # Self-asserted at front desk, no supporting document.
    # Should route to REVIEW_PENDING_DIRECT.
    print()
    print("-" * 70)
    print("Trigger 2: front-desk self-assertion (no document)")
    print("           (Maria Garcia -> Maria Garcia-Lopez)")
    print("-" * 70)
    trigger_2 = {
        "event_id":        "trig-2026-04-23-002",
        "source_type":     "patient_self_assertion",
        "source_record_id": "registration-update-2026-04-23-front-desk",
        "local_patient_id": "local-patient-internal-03441",
        "asserted_name": {
            "given":  "Maria",
            "middle": None,
            "family": "Garcia-Lopez",
        },
        "asserted_prior_name": {
            "given":  "Maria",
            "middle": None,
            "family": "Garcia",
        },
        "asserted_change_date": "2026-04-15",
        "supporting_document_ref": None,
        "demographics": {
            "dob":       "1972-03-14",
            "address":   "8810 Maple Ave, Chicago, IL 60618",
            "phone":     "+15557654321",
            "ssn_last4": "1119",
        },
        "event_date":  "2026-04-23",
    }
    result_2 = run_pipeline(trigger_2)
    print(f"  detection.classification:  {result_2['detection']['classification']}")
    print(f"  detection_score:           "
          f"{float(result_2['detection']['detection_score']):.3f}")
    print(f"  resolution:                {result_2['resolution']['resolution']}")
    print(f"  pending_id:                "
          f"{result_2['resolution'].get('pending_item', {}).get('pending_id')}")
    print(f"  requires:                  "
          f"{result_2['resolution'].get('pending_item', {}).get('requires')}")

    # --- Trigger 3: Margaret Chen -> Margaret Chen-Patel ---
    # Payer eligibility refresh carries the new name. Indirect
    # detection: no explicit prior name asserted, but high
    # demographic alignment + plausible hyphenation pattern.
    print()
    print("-" * 70)
    print("Trigger 3: payer eligibility refresh (indirect detection)")
    print("           (Margaret Chen -> Margaret Chen-Patel)")
    print("-" * 70)
    trigger_3 = {
        "event_id":        "trig-2026-04-23-003",
        "source_type":     "payer_eligibility_update",
        "source_record_id": "payer-eligibility-refresh-2026-04-23-001",
        "payer_id":        "PAYER-02",
        "member_id":       "MEM-440412-D",
        "asserted_name": {
            "given":  "Margaret",
            "middle": None,
            "family": "Chen-Patel",
        },
        "asserted_prior_name":   None,
        "asserted_change_date":  None,
        "supporting_document_ref": None,
        "demographics": {
            "dob":       "1990-11-04",
            "address":   "27 Beacon Hill, Boston, MA 02108",
            "phone":     "+15558889999",
            "ssn_last4": "9023",
        },
        "event_date":  "2026-04-23",
    }
    result_3 = run_pipeline(trigger_3)
    print(f"  detection.classification:  {result_3['detection']['classification']}")
    print(f"  detection_score:           "
          f"{float(result_3['detection']['detection_score']):.3f}")
    print(f"  resolution:                {result_3['resolution']['resolution']}")
    if result_3['envelope']:
        print(f"  sensitivity_class:         "
              f"{result_3['envelope']['sensitivity_class']}")
    elif result_3['resolution'].get('pending_item'):
        print(f"  pending_id:                "
              f"{result_3['resolution']['pending_item']['pending_id']}")

    # --- Trigger 4: Alex Mitchell, sensitivity-classified ---
    # Court-order legal name change with patient preferences set
    # for masked prior-name display. Pipeline should auto-resolve
    # but produce a restricted envelope.
    print()
    print("-" * 70)
    print("Trigger 4: court-ordered change with masked-display preference")
    print("           (existing identity-internal-07331)")
    print("-" * 70)
    # Set the patient's preference before the trigger fires.
    patient_preferences_db.set_for_identity("id-internal-07331", {
        "display_scope": "masked",
        "patient_consented_for_audit": True,
        "monthly_summary_to_patient_portal": True,
    })
    trigger_4 = {
        "event_id":        "trig-2026-04-24-004",
        "source_type":     "court_order",
        "source_record_id": "doc-court-order-2026-04-24-002",
        "local_patient_id": "local-patient-internal-07331",
        "asserted_name": {
            "given":  "Avery",
            "middle": None,
            "family": "Mitchell",
        },
        "asserted_prior_name": {
            "given":  "Alex",
            "middle": None,
            "family": "Mitchell",
        },
        "asserted_change_date": "2026-04-24",
        "supporting_document_ref":
            "s3://my-name-change-supporting-documents/"
            "id-internal-07331/court-order-2026-04-24-002.pdf",
        "demographics": {
            "dob":       "2001-02-18",
            "address":   "1408 Elm St, Portland, OR 97214",
            "phone":     "+15553334444",
            "ssn_last4": "5566",
        },
        "event_date":  "2026-04-24",
        # The intake workflow that captured this change knows it
        # is a gender-affirming context; the trigger carries the
        # explicit class. In production the workflow tags this
        # at the registration / patient-portal layer.
        "explicit_sensitivity_class": "GENDER_AFFIRMING",
    }
    result_4 = run_pipeline(trigger_4)
    print(f"  detection.classification:  {result_4['detection']['classification']}")
    print(f"  detection_score:           "
          f"{float(result_4['detection']['detection_score']):.3f}")
    print(f"  resolution:                {result_4['resolution']['resolution']}")
    if result_4['envelope']:
        env = result_4['envelope']
        print(f"  sensitivity_class:         {env['sensitivity_class']}")
        print(f"  permitted_display_contexts:"
              f" {env['permitted_display_contexts']}")
        print(f"  permitted_release_scopes:  "
              f"{env['permitted_release_scopes']}")
        print(f"  audit_rules:               {env['audit_rules']}")
        print(f"  consumers fanned to:       "
              f"{[c[0] for c in result_4['propagation']['consumer_calls']]}")

    # --- Phase 2: invalidation pipeline ---
    print()
    print("-" * 70)
    print("Phase 2: invalidation triggers")
    print("-" * 70)

    inv_1 = invalidate_on_event({
        "source":             "correction",
        "event_id":           "inv-2026-04-30-001",
        "identity_id":        "id-internal-00874",
        "superseded_event_id":
            result_1["persistence"]["identity_event_record"]["event_id"],
        "correction_payload": {"corrected_family_name": "Hernández"},
    })
    print(f"  source={inv_1['source']:<28}"
          f" affected={len(inv_1['affected_identities'])} "
          f"actions={inv_1['actions']}")

    inv_2 = invalidate_on_event({
        "source":      "reversal",
        "event_id":    "inv-2026-04-30-002",
        "identity_id": "id-internal-00874",
        "reversal_payload": {"reverted_to_prior_event_id":
                                 "evt-name-2018-09-14-initial"},
    })
    print(f"  source={inv_2['source']:<28}"
          f" affected={len(inv_2['affected_identities'])} "
          f"actions={inv_2['actions']}")

    inv_3 = invalidate_on_event({
        "source":                  "identity_merge",
        "event_id":                "inv-2026-04-30-003",
        "merged_from_identity_id": "id-internal-99999",
        "merged_into_identity_id": "id-internal-00874",
    })
    print(f"  source={inv_3['source']:<28}"
          f" affected={len(inv_3['affected_identities'])} "
          f"actions={inv_3['actions']}")

    inv_4 = invalidate_on_event({
        "source":      "sensitivity_update",
        "event_id":    "inv-2026-04-30-004",
        "identity_id": "id-internal-07331",
        "event_id_target":
            result_4["persistence"]["identity_event_record"]["event_id"],
        "new_envelope_payload": {
            "patient_preference": {
                "display_scope": "archive_only",
                "patient_consented_for_audit": True,
            },
        },
    })
    print(f"  source={inv_4['source']:<28}"
          f" affected={len(inv_4['affected_identities'])} "
          f"actions={inv_4['actions']}")

    inv_5 = invalidate_on_event({
        "source":      "document_upgrade",
        "event_id":    "inv-2026-04-30-005",
        "identity_id": "id-internal-03441",
        "event_id_target":
            result_2["resolution"].get("pending_item", {}).get("pending_id"),
        "document_ref":
            "s3://my-name-change-supporting-documents/"
            "id-internal-03441/marriage-cert-2026-05-02-001.pdf",
        "document_metadata":
            {"document_type":     "marriage_certificate",
             "legal_change_date": "2026-04-15"},
    })
    print(f"  source={inv_5['source']:<28}"
          f" affected={len(inv_5['affected_identities'])} "
          f"actions={inv_5['actions']}")

if __name__ == "__main__":
    run_demo()
```

Expected console output (the SQS / EventBridge / S3 / DynamoDB / CloudWatch warnings appear in demo mode because the resources do not exist; they are harmless):

```
======================================================================
Longitudinal Patient Matching Across Name Changes Demo
======================================================================

All patients, names, and supporting documents in this demo
are fictional. The mock identity store, reference data,
patient preferences, and jurisdictional overlays return
hand-crafted data that exercises the resolution paths;
do not point this demo at a live MPI.

Direct thresholds:   HIGH=0.85  MED=0.70
Indirect thresholds: HIGH=0.90  MED=0.78
Reject threshold:    0.50
Matcher version:     lncm-v1.7.2

----------------------------------------------------------------------
Trigger 1: court-ordered legal name change
           (Catherine Marie Wilson -> Catherine Marie Hernandez)
----------------------------------------------------------------------
  detection.classification:  DIRECT
  detection_score:           0.916
  resolution:                AUTO_RESOLVE_HIGH
  sensitivity_class:         GENERAL
  permitted_display_contexts: ['treatment', 'operations']
  consumers fanned to:       ['local_mpi_recipe_5_1', 'eligibility_xref_5_4', 'cross_facility_matcher_5_5', 'claims_clinical_5_6', 'chart_rendering', 'release_of_information', 'patient_portal', 'quality_risk_adj', 'healthlake_fhir']

----------------------------------------------------------------------
Trigger 2: front-desk self-assertion (no document)
           (Maria Garcia -> Maria Garcia-Lopez)
----------------------------------------------------------------------
  detection.classification:  DIRECT
  detection_score:           0.788
  resolution:                REVIEW_PENDING_DIRECT
  pending_id:                pending-XXXXXXXXXX
  requires:                  ['human_review', 'supporting_document']

----------------------------------------------------------------------
Trigger 3: payer eligibility refresh (indirect detection)
           (Margaret Chen -> Margaret Chen-Patel)
----------------------------------------------------------------------
  detection.classification:  INDIRECT
  detection_score:           0.829
  resolution:                REVIEW_PENDING_INDIRECT
  pending_id:                pending-XXXXXXXXXX

----------------------------------------------------------------------
Trigger 4: court-ordered change with masked-display preference
           (existing identity-internal-07331)
----------------------------------------------------------------------
  detection.classification:  DIRECT
  detection_score:           0.909
  resolution:                AUTO_RESOLVE_HIGH
  sensitivity_class:         GENDER_AFFIRMING
  permitted_display_contexts: ['treatment_with_clinical_relevance']
  permitted_release_scopes:  ['patient_access_api']
  audit_rules:               {'every_disclosure_logged': True, 'every_query_logged': True, 'monthly_summary_to_patient_portal': True}
  consumers fanned to:       ['local_mpi_recipe_5_1', 'chart_rendering', 'release_of_information', 'patient_portal', 'healthlake_fhir', 'audit_summary_to_patient']

----------------------------------------------------------------------
Phase 2: invalidation triggers
----------------------------------------------------------------------
  source=correction                   affected=1 actions=['mark_event_superseded:evt-name-...', 're_resolve_with_correction_payload']
  source=reversal                     affected=1 actions=['emit_reversal_event', 'update_current_name_to_prior']
  source=identity_merge               affected=2 actions=['fold_name_histories_into_surviving']
  source=sensitivity_update           affected=1 actions=['update_envelope_for_event:evt-name-...']
  source=document_upgrade             affected=1 actions=['upgrade_source_strength_for_event:pending-...', 'promote_pending_to_resolved_if_eligible']
```

(Detection scores include the source-strength multiplier, so a court-order trigger scores higher than the same demographic-and-name-pair signals would score with a self-assertion source. Pending IDs include a random suffix so the actual `XXXXXXXXXX` portion will differ from run to run; the four-trigger shape and the five invalidation outcomes are stable across runs.)

Several patterns to notice:

- **Trigger 1 is the textbook auto-resolve case.** A court-order document is the strongest source. The patient's DOB, address, phone, and SSN-last-4 all match the existing identity exactly; the prior name is asserted explicitly; the surname change is a clean maiden-to-married replacement; the asserted change date is consistent with the identity's history. The detection score lands above the DIRECT_NAME_CHANGE_HIGH threshold, the resolver auto-resolves, the envelope defaults to GENERAL because no patient preferences were captured for this identity, and the propagation step fans out to all nine standard consumers (local MPI, cross-reference, cross-facility matcher, claims-clinical, chart-rendering, release-of-information, patient-portal, quality, HealthLake).
- **Trigger 2 demonstrates the pending-review path.** A front-desk self-assertion with a plausible hyphenation pattern (Garcia -> Garcia-Lopez) and good demographic match. The detection score is solid (~0.79 after the MEDIUM-WEAK source-strength multiplier), but it falls below the DIRECT_NAME_CHANGE_HIGH threshold and the source is not STRONG, so the resolver routes to REVIEW_PENDING_DIRECT. The pending item lands in the review queue with a `requires: ['human_review', 'supporting_document']` flag; production surfaces it to the medical-records review staff. Trigger 5 in the invalidation phase upgrades this case with a marriage certificate.
- **Trigger 3 is the indirect-detection path.** A payer eligibility refresh carries a new name (Chen-Patel) without any explicit prior-name assertion; the demographic match against the existing identity (Margaret Chen) is strong. The detection score is high enough to clear the INDIRECT_NAME_CHANGE_MED threshold but not the INDIRECT_NAME_CHANGE_HIGH threshold (which is tighter than the direct equivalent), so the resolver routes to REVIEW_PENDING_INDIRECT. Production handles indirect cases more conservatively because there was no explicit assertion that a name change occurred; the cost of an auto-acceptance error is higher.
- **Trigger 4 is the sensitivity-classified case.** Court-order direct change for an identity with masked-display patient preferences set, and an explicit GENDER_AFFIRMING class on the trigger. The detection auto-resolves (high source strength + strong demographics + plausible name pair); the envelope honors the patient's masked preference by restricting display contexts to `treatment_with_clinical_relevance`, restricting release scopes to `patient_access_api` only (preserving the information-blocking obligation under the 21st Century Cures Act), and elevating the audit posture to log every disclosure and every query plus delivering a monthly summary to the patient's portal. The propagation fans out to a smaller, more-tightly-controlled set of consumers and includes the per-patient-summary scheduler that the GENERAL path skipped.
- **The five invalidation triggers cover the operational lifecycle.** A correction overrides a previously-resolved event with a corrected payload (in the demo, recording an accent on the family name that the original assertion missed). A reversal turns a previously-prior name back into the current name. An identity merge folds two identities together. A sensitivity update changes the access-control envelope for an existing event without modifying the event itself (the patient escalated her preference from `masked` to `archive_only`). A document upgrade promotes a previously-self-asserted change with a marriage-certificate scan, which moves the resolution from REVIEW_PENDING to AUTO_RESOLVE-equivalent. Each emits the aggregate `identity_name_change_invalidated` event so downstream consumers refresh their derived state.

The cohort-bucket dimension on the `DetectionScore` and `ResolutionOutcome` metrics is the substrate for the cohort-stratified accuracy monitoring discussed in the main recipe. Production aggregates by `CohortBucket` and alarms on per-cohort detection-rate disparities (typical: > 0.05 for routine monitoring, > 0.05 for HIGH-priority alarm on detection-rate; > 0.01 for HIGH-priority alarm on false-acceptance-rate due to clinical-safety implications). The two cohort buckets that show in the demo (`english_traditional`, `spanish_double_surname`, `east_asian_traditional`) are illustrative; production cohort axes also include name-change-frequency, transgender-or-gender-diverse (with patient-consented self-identification only), and age-of-name-change.

---

## Gap to Production

What the demo intentionally skips, and what you would add for a real deployment:

**Replace the in-memory mocks with real Splink-or-`recordlinkage` and `jellyfish`.** The probabilistic-record-linkage core (Fellegi-Sunter scoring, expectation-maximization-trained per-feature m-and-u parameters, blocking strategies) is the same machinery used in recipes 5.1, 5.4, and 5.5. The demo's `_demographic_match_strength` and `_name_pair_plausibility` are toy stand-ins; production wraps Splink (or the equivalent) with name-change-aware comparators (Soundex, Metaphone, Double Metaphone, Match Rating Approach via `jellyfish`) and per-cohort-tuned weights. The reference-data store (nickname dictionaries, surname-change-pattern models, transliteration maps, naming-tradition rules) drives the cohort accuracy; invest in it as an ongoing program with versioning and regression-testing against gold-set name changes.

**Real DynamoDB schema with the four tables.** The `identity-temporal-name` table holds the computed current state per identity (partition key: `identity_id`). The `identity-event-history` table holds the append-only event log (partition key: `identity_id`, sort key: `event_version`); the current state is rebuilt from this log on demand and on every change. The `active-search-index` table holds the search-index entries (partition key: `search_key`, with a global secondary index on `identity_id`). The `identity-event-outbox` table holds events pending emit (partition key: `outbox_id`, with a sparse index on `emitted_at`). Provision all four with on-demand capacity to handle the bursty pattern of registration-update spikes and bulk reconciliation runs.

**TransactWriteItems for atomic event-and-search-index writes.** The demo writes the event record, the search-index entries, the identity record, and the outbox row in separate calls; a partial-failure scenario could leave the search index inconsistent with the event log. Production wraps all of these in a `TransactWriteItems` call so persistence is atomic. A separate Lambda or DynamoDB Streams consumer reads the outbox and emits the EventBridge event, marking `emitted_at` on success. This pattern keeps the operational store, the audit archive, and the event stream consistent even on partial failure.

**Append-only IAM on the event-history table.** The persistence Lambda's IAM role gets append-only permissions on the `identity-event-history` table: `dynamodb:PutItem` only, no `dynamodb:DeleteItem`, no `dynamodb:UpdateItem` on existing version items. Enforce through IAM condition keys (`dynamodb:Attributes`, `dynamodb:LeadingKeys`) plus DynamoDB resource-based policy with explicit deny on UpdateItem and DeleteItem actions. This is the architectural enforcement of the reversibility-via-superseding-events discipline; you cannot accidentally rewrite history because IAM does not allow it.

**Real S3 supporting-document and audit-archive buckets.** The supporting-document bucket holds court orders, marriage certificates, divorce decrees, and license scans uploaded by patients (through the patient portal) or staff (at the front desk). SSE-KMS with a customer-managed key, lifecycle-managed retention. The audit-archive bucket is Object Lock in Compliance mode with retention floor at the longer of HIPAA records-retention, state medical-records-retention, identity-document retention, and any research IRB retention. Lifecycle to S3 Glacier Deep Archive after 90 days. Forward audit data events to a dedicated audit AWS account.

**Glue and Spark for the periodic-reconciliation pipeline.** The demo runs in-process for a handful of trigger events; production runs the periodic-reconciliation pipeline as a Glue job over Parquet partitions in S3, sweeping the population for name-change candidates that the per-event flow missed. The historical-backfill Glue job retroactively reconciles pre-existing records against whatever name-change evidence is available; this is a one-time multi-week project for most institutions, with cohort-stratified accuracy monitoring during the backfill and suppression of routine event emission (downstream consumers refresh from a single `name_change_backfill_complete` marker rather than millions of individual events).

**Step Functions orchestration with retry, timeout, and DLQ.** Three workflows: a per-event resolution workflow (detect, evaluate, persist, propagate), a periodic reconciliation workflow (sweep the population looking for indirect name-change candidates), and an invalidation workflow (subscribe to superseding events and selectively re-resolve). Each Lambda and Glue job has a dedicated DLQ; Step Functions Catch states route terminal failures to the DLQ; CloudWatch alarms on DLQ depth surface stuck workflows.

**Idempotency keys on every write.** The demo uses `event_id` for event-level idempotency. Production extends this: detect at `(source_record_id, source_type)`; resolve at `(candidate_identity_id, asserted_change_date, asserted_name_canonical)`; persist at `(identity_id, event_id, event_version)`; propagate at `(event_id, consumer_id)`; invalidate-on-event at `invalidation_event_id`. Duplicate-event delivery from EventBridge or duplicate-invocation from Step Functions retries is routine; the pipeline must handle it without producing duplicate writes, duplicate name-change events, or inconsistent state.

**Threshold calibration and approval governance.** The DIRECT and INDIRECT thresholds, the source-strength multipliers, the per-feature weights, and the sensitivity-classification rules are calibrated against an institutional gold set with input from analytics governance, clinical informatics, compliance, and the patient-experience-and-dignity committee. Re-calibration runs periodically and on detection of cohort-stratified disparity above the institutional threshold. Each resolved event references the configuration version active at decision time. Promote candidate thresholds through institutional review (analytics governance committee, compliance, clinical informatics, patient-experience-and-dignity committee, equity-monitoring committee) before going live.

**Cohort-stratified accuracy monitoring with disparity alarms.** The demo emits the `CohortBucket` dimension on `DetectionScore` and `ResolutionOutcome` but does not aggregate or alarm. Production computes per-cohort detection rate weekly, per-cohort name-change false-acceptance rate weekly, per-cohort review-queue aging weekly, per-cohort sampled error rate monthly. Disparity (best-rate minus worst-rate) thresholds: detection-rate > 0.05 = MEDIUM alarm; false-acceptance-rate > 0.01 = HIGH (clinical safety implications); review-queue-aging disparity > 5 business days = MEDIUM. Remediation (per-cohort threshold tuning, reference-data gap analysis, per-cohort review-queue prioritization) is documented in a cohort-disparity ledger and reviewed quarterly by the equity-monitoring committee and the patient-experience-and-dignity committee.

**Three review queues with sensitivity-aware tooling.** The demo routes review-band cases to a single SQS queue but does not provide a UI. Production builds three workflow tools. The name-change review tool surfaces pending-direct and pending-indirect cases with the asserted name, the candidate identity, the demographic comparison, the name-pair plausibility breakdown, and any available supporting documents. The supporting-document review tool surfaces uploaded documents for verification and metadata extraction (document type, legal-change date, jurisdictional issuer); reviewers verify and link the document to the pending event. The sensitivity-classification review tool surfaces patient-preference updates for verification (especially when the update arrives through a non-standard channel like a phone call to medical records). Each tool emits the reviewer's decision back into the matcher's training signal for periodic threshold re-calibration. Reviewer-identity authentication, decision logging, conflict-of-interest checks against an institutional registry, and patient-experience-and-dignity-committee oversight on the sensitivity-classification queue are all production requirements.

**Patient-portal upload flow for supporting documents.** The asynchronous-upload path through the patient portal is the lowest-friction way to get supporting documents on file and is a strategic investment, not a tactical convenience. Build it as a first-class architectural component: Cognito-federated patient authentication, a document-upload UI with guidance on accepted document types, virus scanning before write to the supporting-document bucket, automatic metadata extraction (Amazon Textract or a commercial document-AI service), routing to the supporting-document review queue with a notification back to the patient when the document is verified and the pending change is promoted to AUTO_RESOLVE. Skip this and the operational burden falls on front-desk staff and medical-records review, and the review queue ages.

**Patient-preference UI and consent capture.** The sensitivity classification and patient-preference fields in the identity record assume the patient has been asked. The mechanism for asking is not the matcher's job; it is the registration workflow's, the patient-portal app's, and (for clinical-care contexts) the gender-affirming-care intake workflow's. Build the patient-preference capture as a deliberate workflow with appropriate framing, training for the staff who solicit the information, and mechanisms for the patient to update preferences over time. The demo's `MockPatientPreferences` is a placeholder; real preference capture is a substantial UX-and-policy engagement.

**Information-blocking-compliant patient-access read path.** Under the 21st Century Cures Act information-blocking provisions, the institution is obligated to release a patient's records on request, including records under prior names. The release pipeline has to recognize the linkage (the matcher's job) and apply the patient's explicit preferences for prior-name display in the released documents (the access-control envelope's job). Build the patient-access-API release path as a deliberate workflow that consults both the linkage and the envelope, with audit logging on every release. API Gateway with the institution's patient-portal authentication; a Lambda authorizer binds the requesting principal to the patient_id; the Lambda handler retrieves the linked records, applies the access_control_envelope, returns the response with explicit handling of prior-name disclosures; the audit log records every patient-access read with the envelope state at the time. Compliance with information-blocking is enforced at this read path.

**Cross-organizational propagation policy.** Name-change events resolved at the institution may need to propagate to other organizations the patient has authorized for cross-facility data exchange. The policy is governed by HIE participation agreements, patient consent, and the trust frameworks the institution operates under. Some HIE frameworks support push notifications for identity updates; others rely on pull-time refresh during query response. Coordinate with recipe 5.5's cross-facility matcher; the propagation queue here is the institution-internal portion of the broader cross-org flow.

**Vital-records integration where available.** Where the state's vital-records agency provides a feed for legal name changes (currently limited to a small number of states, but expanding), the integration is its own subproject: partner-agreement, network connectivity, data-format normalization, privacy-and-purpose-of-use constraints, audit requirements. Add a Lambda that consumes the vital-records feed, matches each event to the institution's identity records using the state's identifier or via demographic matching where the state-issued identifier is not available, and triggers a high-confidence resolution path. The integration is constrained by the state's data-use agreement; typically the data is permitted only for identity-resolution and patient-matching purposes, not redistributable.

**FHIR-native HealthLake integration.** Where the institution stores clinical resources in HealthLake, the resolved name change updates the FHIR Patient resource's `name` list: the new name is added with `use=official` and `period.start=change_effective_date`; the prior name is demoted to `use=old` with `period.end=change_effective_date`. The HumanName datatype's `use` and `period` fields support the time-varying-name model directly. Restricted-class events update the resource with appropriate `meta.security` tags and (where the institution's policy requires) suppression of the prior `HumanName` entry from the default rendering, with the linkage preserved in a custom extension that the access-controlled rendering layer can read.

**KMS-encrypted everything.** Customer-managed keys for the identity table, the search-index table, the event-history table, the outbox table, the supporting-document bucket, the audit-archive bucket, the SQS queues, the Lambda log groups, the Glue temp storage, and the Secrets Manager partner-credential entries. Per-service KMS configuration is omitted for readability but is non-negotiable for the institution's standard PHI-handling posture.

**VPC + VPC endpoints.** Production runs Glue jobs and Lambdas in VPC with VPC endpoints for S3 (gateway), DynamoDB (gateway), KMS, Secrets Manager, CloudWatch Logs, EventBridge, SQS, Step Functions, Glue, Athena, and STS. NAT Gateway only for the vital-records-partner egress (where applicable); restrict egress with security groups and an outbound proxy with an allow-list of partner endpoints. PrivateLink where the partner offers it. Per-source-system rate limits below the partner's published rate limits.

**CloudTrail data events.** Every read of the identity-temporal-name table is auditable activity; the data-events feature is not enabled by default and is the right level of granularity for this substrate. Audit logs in a dedicated S3 bucket with Object Lock in Compliance mode for immutability; lifecycle policy transitioning to S3 Glacier Deep Archive after 90 days; retention floor enforced at the bucket-policy and Object-Lock-configuration level. Forward CloudTrail data events to a dedicated audit AWS account in the institution's organization.

**Lake Formation column-level and row-level access control on the analytics surface.** Different audiences need different views of the resolved name-change history. Treatment-context users see the current name with prior-name display governed by the sensitivity classification. Operations users see the linkage but a constrained view of the prior names. Research users (for de-identified analytics) see the linked identity with no name detail at all. Lake Formation grants enforce the row-and-column distinctions; Athena query paths use the same grants.

**Per-event consent metadata captured at intake.** The trigger event needs to carry: patient-consent-for-change scope (the patient consented to the change being recorded); patient-consent-for-prior-name-display scope (the patient's preferences for who may see the prior name and under what circumstances); jurisdictional overlays (state law on prior-name disclosure, particularly post-Dobbs reproductive-health-care state laws and post-Bostock employment-context implications). The demo's intake path is a single dict; production has a structured consent payload signed by the producer and validated at the matcher's ingestion layer.

**Producer-signed envelope on the patient-self-assertion path.** The patient-self-assertion intake path (registration desk, patient portal) needs producer-signed envelopes (`source_system`, `source_record_id`, `event_id`, `signed_payload`, `signature`) tied to per-source-system allow-lists. This is how the matcher distinguishes a legitimate registration update from a spoofed event. Cognito-federated authentication for the patient-portal-app trigger source.

**Compliance and operational ownership.** Longitudinal name-change handling sits at the intersection of registration, clinical informatics, compliance, patient experience, equity monitoring, and IT. Establish clear operational ownership: who tunes the thresholds, who reviews the cohort-disparity reports, who owns the reference-data maintenance, who handles the patient-preference UI, who responds to invalidation backlogs, who owns the relationship with the patient-experience-and-dignity committee. The pipeline works only when the operational ownership is clear and funded.

The pipeline is the easy part. The operational discipline (patient-preference UI and consent capture as deliberate workflow, reference-data sourcing and maintenance as ongoing program, threshold calibration and approval governance, three-queue review tooling with sensitivity-aware oversight, information-blocking-compliant patient-access read path, cross-organizational propagation policy aligned with HIE agreements, historical-backfill plan with patient-facing communication, cohort-stratified equity monitoring discipline, ongoing operational ownership with patient-experience-and-dignity committee engagement) is what makes a longitudinal name-change system produce continuity of clinical record without producing dignity failures. Build for that.

---

*← [Recipe 5.7: Longitudinal Patient Matching Across Name Changes](chapter05.07-longitudinal-patient-matching-name-changes)*
