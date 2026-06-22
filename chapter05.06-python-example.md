# Recipe 5.6: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 5.6. It shows one way you could translate the claims-to-clinical data linkage pattern into working Python using small `MockClaimsParser` and `MockClinicalParser` stand-ins for the real X12 / FHIR / EHR-extract parsers, `MockVocabularyMap` standing in for the production CPT/HCPCS/NDC/RxNorm vocabulary stores, an in-memory `MockCrossRefTable` standing in for the MRN-to-member-ID DynamoDB cross-reference, an in-process dict standing in for the local MPI's blocking and scoring (delegating to recipe 5.1's pattern), Amazon DynamoDB for the linkage system-of-record and the invalidation index, an in-process dict standing in for the curated-zone Glue/Spark output, Amazon SQS for the encounter-link-review and patient-link-review queues, Amazon S3 for the raw and curated archives, Amazon EventBridge for the `claims_clinical_link_resolved`, `external_encounter_observed`, and `claims_clinical_link_invalidated` events, and Amazon CloudWatch for operational metrics. It is not production-ready. There is no real X12 837/835 parser, no real FHIR ExplanationOfBenefit deserializer, no Glue/Spark batch pipeline, no Step Functions orchestration, no longitudinal-record-assembler, no review-queue UI, no OMOP CDM loader, no HealthLake integration, and no IAM, KMS, VPC, or CloudTrail wiring. Think of it as the sketchpad version: useful for understanding the shape of a claims-to-clinical linkage pipeline that respects the cluster-then-link ordering, the encounter-class-specific date tolerances, the diagnosis-concordance-as-soft-signal posture, the external-encounter-as-first-class-output discipline, and the invalidation-pipeline-is-the-durability-story posture this category demands. It is not something you would point at a live claims warehouse on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the six core pseudocode steps from the main recipe: ingest and normalize the claims and clinical streams (claims arrive as X12 837/835, FHIR ExplanationOfBenefit, NCPDP, or payer flat files; clinical data arrives as EHR extracts or FHIR resources); resolve patient identity across the streams using the MRN-to-member-ID cross-reference (recipe 5.4 output) plus the local MPI (recipe 5.1) plus optional cross-organizational match (recipe 5.5); cluster patient-resolved claims into encounter clusters using encounter-class-specific date windows and resubmission/adjustment chain detection; match each cluster to a clinical encounter using date alignment, provider alignment, encounter-class compatibility, diagnosis concordance, procedure concordance, and DRG concordance; attribute claim line items to clinical events using vocabulary maps (CPT to internal procedure code, NDC to RxNorm); and persist the linkage to DynamoDB, archive to S3, emit cross-recipe events, and react to invalidation triggers (claim adjustments, EHR encounter amendments, identity merges, vocabulary refreshes). The synthetic claims, encounters, and providers in the demo are fictional; the names, MRNs, member IDs, NPIs, claim IDs, and DRG codes are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also install an X12 parser library such as `pyx12` or a commercial equivalent for the 837/835 transaction sets, a FHIR client such as `fhir.resources` for the ExplanationOfBenefit and Encounter resources, a vocabulary-mapping library or a connector to the institution's terminology server (UMLS, OHDSI Athena, or a commercial product), and a Spark client (`pyspark`) for the bulk linkage pipeline. The demo replaces all of these with small mocks so the focus stays on the linkage logic rather than on protocol parsing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchGetItem`, `dynamodb:TransactWriteItems` on the `claims-clinical-linkage` table, the `linkage-outbox` table, the `mrn-member-id-xref` cross-reference table, and the `linkage-invalidation-index` table
- `s3:PutObject` on the raw-claims, raw-clinical, curated, and derived buckets
- `sqs:SendMessage` and `sqs:ReceiveMessage` on the patient-link-review-queue, encounter-link-review-queue, and line-item-review-queue
- `events:PutEvents` on the claims-clinical-events bus
- `cloudwatch:PutMetricData` for the link-rate, cohort-disparity, attribution-coverage, and review-queue-depth metrics
- `glue:StartJobRun` and `glue:GetJobRun` on the bulk-linkage Glue jobs (production only; the demo runs in-process)

Scope each Lambda's IAM role and each Glue job's role to the specific resource ARNs they touch. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The linkage write Lambda gets append-only IAM on the linkage history (no `dynamodb:DeleteItem`, no `dynamodb:UpdateItem` on existing version items) enforced through condition keys plus DynamoDB resource-based policy.

A few things worth knowing upfront:

- **Claims and clinical data describe the same encounter through different lenses.** The claims data is structured around the billable transaction (one inpatient stay produces three to twenty claims). The clinical data is structured around the encounter (one inpatient stay is one encounter). The linkage pipeline's job is to produce a useful join despite the disagreement, not to "fix" either side.
- **The matcher runs in batch but is event-aware.** Unlike recipe 5.5's query-time matcher, claims-to-clinical linkage runs in batch over a sliding window (typically the past 90 to 180 days). Within the window, the linker re-evaluates as new claims arrive and as EHR encounters get amended.
- **Cluster-then-link is the right ordering.** Match each claim individually and you lose the structural information that several claims belong to the same encounter cluster. The demo follows this discipline.
- **Date tolerance is encounter-class-specific.** Inpatient claims need a wide tolerance covering the entire stay plus the late-billing window; outpatient claims need a tight tolerance with single-day slop; ER claims sit between. The demo encodes the per-class windows in configuration.
- **Diagnosis concordance is a soft signal.** The diagnoses on the claim and the diagnoses on the EHR encounter overlap but are rarely identical. Treating "diagnoses match exactly" as a required signal will under-link; treating them as completely irrelevant will over-link. The demo scores diagnosis overlap as one feature among several.
- **External encounters are first-class outputs.** Many claims do not match any local encounter because the encounter happened elsewhere. These claims are still data; they describe the patient's care trajectory outside the institution. The demo tags them as `EXTERNAL_ENCOUNTER` and surfaces them for the longitudinal-record-assembler.
- **DynamoDB rejects Python `float`.** Every confidence score, score-breakdown component, and numeric metadata field passes through `Decimal` on its way in and on its way out. Same gotcha as recipes 5.1 / 5.2 / 5.3 / 5.4 / 5.5; the same `_to_decimal` helper handles it.
- **The example collapses Step Functions, multiple Glue jobs, multiple Lambdas, and the SQS-driven worker pattern into a single Python file for readability.** In production the parse-and-normalize, link-patient, cluster-claims, link-encounter, attribute-care-events, persist-and-emit, and invalidate-on-event stages are separate Glue jobs (for batch) and Lambdas (for event-driven slices) orchestrated by Step Functions, each with their own error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the encounter-class-specific date tolerances, the per-feature weights for the encounter-link scorer, the confidence thresholds, the matcher and vocabulary versions, and the routing knobs are what you would change between environments.

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
# CloudWatch Logs Insights. Linked claims-clinical data is PHI; log
# structural metadata only (cluster_id, encounter_id, link_status,
# confidence band), never raw demographics, raw diagnoses, or raw
# clinical content.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from DynamoDB, EventBridge,
# CloudWatch, and SQS. The bulk linkage pipeline is throughput-
# sensitive; transient throttling on any one service should not
# fail an entire Glue job. Step Functions Catch states distinguish
# retriable infrastructure failures from terminal logic failures
# and route terminal failures to a DLQ for investigation.
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
LINKAGE_TABLE            = "claims-clinical-linkage"
OUTBOX_TABLE             = "linkage-outbox"
XREF_TABLE               = "mrn-member-id-xref"
INVALIDATION_INDEX_TABLE = "linkage-invalidation-index"
RAW_CLAIMS_BUCKET        = "my-claims-clinical-raw-claims"
RAW_CLINICAL_BUCKET      = "my-claims-clinical-raw-clinical"
CURATED_BUCKET           = "my-claims-clinical-curated"
DERIVED_BUCKET           = "my-claims-clinical-derived"
PATIENT_REVIEW_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/000000000000/patient-link-review-queue"
ENCOUNTER_REVIEW_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/000000000000/encounter-link-review-queue"
LINE_ITEM_REVIEW_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/000000000000/line-item-review-queue"
EVENTS_BUS_NAME          = "claims-clinical-events"
CLOUDWATCH_NAMESPACE     = "ClaimsClinical/Linkage"

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("LINKAGE_TABLE",              LINKAGE_TABLE),
    ("OUTBOX_TABLE",               OUTBOX_TABLE),
    ("XREF_TABLE",                 XREF_TABLE),
    ("INVALIDATION_INDEX_TABLE",   INVALIDATION_INDEX_TABLE),
    ("RAW_CLAIMS_BUCKET",          RAW_CLAIMS_BUCKET),
    ("RAW_CLINICAL_BUCKET",        RAW_CLINICAL_BUCKET),
    ("CURATED_BUCKET",             CURATED_BUCKET),
    ("DERIVED_BUCKET",             DERIVED_BUCKET),
    ("PATIENT_REVIEW_QUEUE_URL",   PATIENT_REVIEW_QUEUE_URL),
    ("ENCOUNTER_REVIEW_QUEUE_URL", ENCOUNTER_REVIEW_QUEUE_URL),
    ("LINE_ITEM_REVIEW_QUEUE_URL", LINE_ITEM_REVIEW_QUEUE_URL),
    ("EVENTS_BUS_NAME",            EVENTS_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",       CLOUDWATCH_NAMESPACE),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every linkage record stores the matcher and vocabulary versions
# active at link time. This is how a future audit reconstructs
# what thresholds and what code maps were active when a particular
# linkage was decided.
MATCHER_CONFIG_VERSION  = "linker-v2.4.1"
VOCABULARY_VERSIONS = {
    "icd10cm":                 "2026.10.01",
    "cpt":                     "2026.01.01",
    "rxnorm":                  "2026.04.07",
    "internal_procedure_map":  "imap-v9",
    "revenue_code_map":        "rev-v3",
    "ndc_to_rxnorm":           "ndc-v12",
}

# --- Encounter-link confidence thresholds ---
# Tighter than patient-link thresholds because encounter linkage
# errors compound: a wrong encounter link routes the wrong claims
# to the wrong analytic bucket. The numbers below are illustrative
# defaults; calibrate against your own gold set with input from
# the institution's analytics governance committee and clinical
# informatics team.
ENCOUNTER_LINK_HIGH_THRESHOLD   = Decimal("0.85")
ENCOUNTER_LINK_MED_THRESHOLD    = Decimal("0.70")
ENCOUNTER_LINK_REJECT_THRESHOLD = Decimal("0.45")
# Anything between REJECT and MED routes to the encounter-link
# review queue.

# Patient-link thresholds (mirrored from the eligibility-matching
# pipeline of recipe 5.4 for consistency; the cross-reference is
# the primary path, this is the fallback).
PATIENT_LINK_HIGH_THRESHOLD = Decimal("0.90")
PATIENT_LINK_MED_THRESHOLD  = Decimal("0.75")
PATIENT_LINK_REJECT         = Decimal("0.50")
CROSS_REF_HIGH_CONFIDENCE   = Decimal("0.95")

# --- Per-feature weights for the encounter-link scorer ---
# Date alignment and provider alignment dominate because they are
# the most stable encounter-level signals. Diagnosis concordance
# is a soft signal (partial overlap is normal). DRG concordance
# is decisive when both are present but is often missing.
ENCOUNTER_SCORE_WEIGHTS = {
    "date_alignment":        Decimal("0.30"),
    "provider_alignment":    Decimal("0.20"),
    "class_compatibility":   Decimal("0.15"),
    "diagnosis_concordance": Decimal("0.15"),
    "procedure_concordance": Decimal("0.10"),
    "drg_concordance":       Decimal("0.10"),
}

# --- Encounter-class-specific date tolerances ---
# Inpatient claims may be billed a day or two after discharge;
# outpatient claims usually align on the calendar date with small
# slop for next-morning batch posting. ER claims are tight too
# but with overlap-pattern tolerance for facility-plus-professional
# bundles. Pharmacy claims align by service date.
ENCOUNTER_CLASS_DATE_TOLERANCE_DAYS = {
    "inpatient":   2,
    "outpatient":  1,
    "emergency":   1,
    "observation": 2,
    "telehealth":  1,
    "pharmacy":    0,
}

# --- Line-item attribution date tolerance ---
# Line items often have only a service date (no time); we tolerate
# the entire calendar day for the date-and-time alignment of
# line item to clinical event.
LINE_ITEM_DATE_TOLERANCE_HOURS = 26

# --- Sliding window for the linkage pipeline ---
# Late-arriving claims (especially payer feeds) can lag the
# clinical event by 60+ days. The pipeline runs over a window
# wide enough to catch them.
LINKAGE_WINDOW_DAYS = 180

def _to_decimal(value) -> Decimal:
    """Coerce numeric input into Decimal for DynamoDB."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

def _now_iso() -> str:
    """UTC timestamp in ISO 8601 format. Always UTC; never local time."""
    return datetime.now(timezone.utc).isoformat()

def _strip_diacritics(s: str) -> str:
    """Strip combining diacritical marks for case-insensitive matching."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def _canonical_form(*parts) -> str:
    """Join parts into a canonical lowercase whitespace-collapsed form."""
    joined = " ".join(str(p or "").strip() for p in parts)
    joined = _strip_diacritics(joined).lower()
    joined = re.sub(r"\s+", " ", joined).strip()
    return joined

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _serialize_for_dynamodb(obj):
    """Recursive serialization helper. Same pattern as recipes 5.1 - 5.5."""
    if isinstance(obj, dict):
        return {k: _serialize_for_dynamodb(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_for_dynamodb(v) for v in obj]
    if isinstance(obj, float):
        return Decimal(str(obj))
    return obj

def _emit_metric(metric_name: str, value: float, dimensions: dict = None) -> None:
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
```

---

## Mock Claims Source, Clinical Source, Cross-Reference Table, Vocabulary Map, and MPI

Production reads claims from a real X12 837/835 parser, a real FHIR ExplanationOfBenefit deserializer, or a payer-specific flat-file parser; reads clinical data from an EHR-native schema (Epic Clarity / Caboodle, Cerner / Oracle Health, or equivalent) or from FHIR resources; reads the cross-reference from a real DynamoDB table populated by the eligibility-matching pipeline; reads vocabulary maps from a terminology server (UMLS, OHDSI Athena, or commercial); and reads the local MPI from the matcher of recipe 5.1. The demo includes small mocks that exercise the downstream linkage pipeline without requiring those external dependencies.

```python
# --- In-memory cross-reference table (output of recipe 5.4) ---
# Keyed on (payer_id, member_id). Maps payer-side member identity
# to the institution's local patient ID with a confidence score
# and a validity window.
SYNTHETIC_XREF = {
    ("PAYER-01", "MEM-100874-A"): {
        "local_patient_id":    "local-patient-internal-00874",
        "confidence":          Decimal("0.99"),
        "version":             "xref-v3",
        "valid_from":          "2025-01-01",
        "valid_to":            None,
    },
    ("PAYER-02", "MEM-201927-B"): {
        "local_patient_id":    "local-patient-internal-01927",
        "confidence":          Decimal("0.97"),
        "version":             "xref-v3",
        "valid_from":          "2024-06-01",
        "valid_to":            None,
    },
    ("PAYER-03", "MEM-303441-C"): {
        "local_patient_id":    "local-patient-internal-03441",
        "confidence":          Decimal("0.96"),
        "version":             "xref-v3",
        "valid_from":          "2025-09-01",
        "valid_to":            None,
    },
    # An entry for a patient who has only outside encounters in
    # this demo: the cross-reference resolves the identity but
    # the local clinical extract has no encounters.
    ("PAYER-01", "MEM-500000-Z"): {
        "local_patient_id":    "local-patient-internal-05000",
        "confidence":          Decimal("0.98"),
        "version":             "xref-v3",
        "valid_from":          "2025-01-01",
        "valid_to":            None,
    },
}

# --- In-memory local MPI for fallback patient matching ---
# In production this is the MPI from recipe 5.1; here a tiny
# stand-in so the demo can show the probabilistic-fallback path.
SYNTHETIC_LOCAL_MPI = {
    "local-patient-internal-00874": {
        "first_name": "JANE",  "last_name": "DOE",
        "dob": "19800615",     "administrative_sex": "F",
        "cohort_bucket": "A",
    },
    "local-patient-internal-01927": {
        "first_name": "ALEX",  "last_name": "JOHNSON",
        "dob": "19951102",     "administrative_sex": "M",
        "cohort_bucket": "B",
    },
    "local-patient-internal-03441": {
        "first_name": "MARIA", "last_name": "GARCIA-LOPEZ",
        "dob": "19720314",     "administrative_sex": "F",
        "cohort_bucket": "C",
    },
    "local-patient-internal-05000": {
        "first_name": "SAM",   "last_name": "WILLIAMS",
        "dob": "19661108",     "administrative_sex": "M",
        "cohort_bucket": "A",
    },
}

# --- Synthetic clinical encounters (output of EHR extract) ---
# Keyed on encounter_id. Each encounter has an attending NPI,
# admission/discharge timestamps, an encounter class, a
# location, a diagnosis set (admitting + working + discharge),
# and the procedures and medications administered.
SYNTHETIC_CLINICAL_ENCOUNTERS = {
    # Jane Doe's heart-failure inpatient stay; the recipe's
    # walking example. Three facility claims plus several
    # professional claims will cluster and match against this.
    "ehr-enc-2026-03-14-12-44-32-pt00874": {
        "encounter_id":             "ehr-enc-2026-03-14-12-44-32-pt00874",
        "local_patient_id":         "local-patient-internal-00874",
        "encounter_class":          "inpatient",
        "location_id":              "INST-MAIN-3CARDIAC",
        "attending_provider_npi":   "1234567893",
        "consulting_provider_npis": ["1659473820", "1245678901"],
        "admission_timestamp":      "2026-03-14T12:44:32Z",
        "discharge_timestamp":      "2026-03-18T14:11:08Z",
        "encounter_diagnoses":      ["I50.23", "I50.21", "E11.9", "I10"],
        "procedures_internal":      [
            {"event_id": "proc-001", "code": "INT-CT-CHEST",
             "event_timestamp": "2026-03-15T08:30:00Z",
             "ordered_by_npi":  "1234567893"},
            {"event_id": "proc-002", "code": "INT-CYTO-PATH",
             "event_timestamp": "2026-03-16T10:00:00Z",
             "ordered_by_npi":  "1234567893"},
        ],
        "medications_administered": [
            {"event_id": "med-001",  "code": "RXN-FUROSEMIDE-IV",
             "event_timestamp": "2026-03-14T13:30:00Z"},
        ],
        "drg_code":                 "291",
        "discharge_disposition":    "home_with_health_services",
    },
    # Alex Johnson's ER visit. ER class with a same-day pattern.
    "ehr-enc-2026-04-02-08-22-15-pt01927": {
        "encounter_id":             "ehr-enc-2026-04-02-08-22-15-pt01927",
        "local_patient_id":         "local-patient-internal-01927",
        "encounter_class":          "emergency",
        "location_id":              "INST-MAIN-ED",
        "attending_provider_npi":   "1987654321",
        "consulting_provider_npis": [],
        "admission_timestamp":      "2026-04-02T08:22:15Z",
        "discharge_timestamp":      "2026-04-02T13:48:00Z",
        "encounter_diagnoses":      ["R10.9", "K59.00"],
        "procedures_internal":      [
            {"event_id": "proc-101", "code": "INT-CT-ABDPELVIS",
             "event_timestamp": "2026-04-02T10:15:00Z",
             "ordered_by_npi":  "1987654321"},
        ],
        "medications_administered": [],
        "drg_code":                 None,
        "discharge_disposition":    "home",
    },
    # Maria Garcia-Lopez outpatient visit; one professional claim
    # will match this. Demonstrates the clean outpatient case.
    "ehr-enc-2026-04-15-09-30-12-pt03441": {
        "encounter_id":             "ehr-enc-2026-04-15-09-30-12-pt03441",
        "local_patient_id":         "local-patient-internal-03441",
        "encounter_class":          "outpatient",
        "location_id":              "INST-CLIN-PRIMARY",
        "attending_provider_npi":   "1112223334",
        "consulting_provider_npis": [],
        "admission_timestamp":      "2026-04-15T09:30:12Z",
        "discharge_timestamp":      "2026-04-15T10:05:00Z",
        "encounter_diagnoses":      ["E11.9", "Z00.00"],
        "procedures_internal":      [
            {"event_id": "proc-201", "code": "INT-OFFICEVISIT-EST",
             "event_timestamp": "2026-04-15T09:35:00Z",
             "ordered_by_npi":  "1112223334"},
        ],
        "medications_administered": [],
        "drg_code":                 None,
        "discharge_disposition":    "home",
    },
    # An additional outpatient encounter for Maria on the same
    # day at a different time; demonstrates the multi-encounter-
    # in-window case for the matcher.
    "ehr-enc-2026-04-15-14-15-00-pt03441": {
        "encounter_id":             "ehr-enc-2026-04-15-14-15-00-pt03441",
        "local_patient_id":         "local-patient-internal-03441",
        "encounter_class":          "outpatient",
        "location_id":              "INST-CLIN-LAB",
        "attending_provider_npi":   "1556677889",
        "consulting_provider_npis": [],
        "admission_timestamp":      "2026-04-15T14:15:00Z",
        "discharge_timestamp":      "2026-04-15T14:30:00Z",
        "encounter_diagnoses":      ["Z00.00"],
        "procedures_internal":      [
            {"event_id": "proc-301", "code": "INT-LAB-CMP",
             "event_timestamp": "2026-04-15T14:18:00Z",
             "ordered_by_npi":  "1112223334"},
        ],
        "medications_administered": [],
        "drg_code":                 None,
        "discharge_disposition":    "home",
    },
}

# --- Synthetic claims (already parsed; production parses from
# X12 837/835, FHIR EOB, NCPDP, or payer-specific files) ---
SYNTHETIC_CLAIMS = [
    # Jane Doe's heart-failure stay: three facility claims + four
    # professional claims (one resubmitted). Designed to exercise
    # the cluster-then-link path.
    {
        "claim_id": "fac-claim-2026-03-2841073",
        "payer_id": "PAYER-01",
        "member_id": "MEM-100874-A",
        "claim_type": "facility_inpatient",
        "billing_provider_npi":   "1456789012",
        "rendering_provider_npi": "1456789012",
        "service_from_date":  "2026-03-14",
        "service_through_date": "2026-03-15",
        "primary_diagnosis_icd10": "I50.21",
        "secondary_diagnoses_icd10": ["E11.9"],
        "procedures_cpt_hcpcs": [],
        "revenue_codes": ["0110"],
        "drg_code": "291",
        "place_of_service": "21",
        "claim_status": "paid",
        "adjustment_indicator": False,
        "original_claim_id": None,
        "charge_amount": Decimal("28000.00"),
        "paid_amount":   Decimal("6112.00"),
        "line_items": [
            {"line_item_id": "li-001", "cpt_hcpcs": None,
             "service_date": "2026-03-14",
             "revenue_code": "0110", "charge": Decimal("28000.00")},
        ],
    },
    {
        "claim_id": "fac-claim-2026-03-2841074",
        "payer_id": "PAYER-01",
        "member_id": "MEM-100874-A",
        "claim_type": "facility_inpatient",
        "billing_provider_npi":   "1456789012",
        "rendering_provider_npi": "1456789012",
        "service_from_date":  "2026-03-15",
        "service_through_date": "2026-03-17",
        "primary_diagnosis_icd10": "I50.21",
        "secondary_diagnoses_icd10": ["E11.9"],
        "procedures_cpt_hcpcs": ["71250", "88305"],
        "revenue_codes": ["0300", "0320", "0250"],
        "drg_code": "291",
        "place_of_service": "21",
        "claim_status": "paid",
        "adjustment_indicator": False,
        "original_claim_id": None,
        "charge_amount": Decimal("32000.00"),
        "paid_amount":   Decimal("6900.00"),
        "line_items": [
            {"line_item_id": "li-002", "cpt_hcpcs": "71250",
             "service_date": "2026-03-15",
             "revenue_code": "0320", "charge": Decimal("1800.00")},
            {"line_item_id": "li-003", "cpt_hcpcs": "88305",
             "service_date": "2026-03-16",
             "revenue_code": "0310", "charge": Decimal("450.00")},
        ],
    },
    {
        "claim_id": "fac-claim-2026-04-2904115",
        "payer_id": "PAYER-01",
        "member_id": "MEM-100874-A",
        "claim_type": "facility_inpatient",
        "billing_provider_npi":   "1456789012",
        "rendering_provider_npi": "1456789012",
        "service_from_date":  "2026-03-18",
        "service_through_date": "2026-03-19",
        "primary_diagnosis_icd10": "I50.21",
        "secondary_diagnoses_icd10": [],
        "procedures_cpt_hcpcs": [],
        "revenue_codes": ["0110"],
        "drg_code": "291",
        "place_of_service": "21",
        "claim_status": "paid",
        "adjustment_indicator": False,
        "original_claim_id": None,
        "charge_amount": Decimal("14000.00"),
        "paid_amount":   Decimal("3050.00"),
        "line_items": [
            {"line_item_id": "li-004", "cpt_hcpcs": None,
             "service_date": "2026-03-18",
             "revenue_code": "0110", "charge": Decimal("14000.00")},
        ],
    },
    {
        "claim_id": "prof-claim-2026-03-882441-attending",
        "payer_id": "PAYER-01",
        "member_id": "MEM-100874-A",
        "claim_type": "professional",
        "billing_provider_npi":   "1234567893",
        "rendering_provider_npi": "1234567893",
        "service_from_date":  "2026-03-14",
        "service_through_date": "2026-03-18",
        "primary_diagnosis_icd10": "I50.21",
        "secondary_diagnoses_icd10": [],
        "procedures_cpt_hcpcs": ["99291"],
        "revenue_codes": [],
        "drg_code": None,
        "place_of_service": "21",
        "claim_status": "paid",
        "adjustment_indicator": False,
        "original_claim_id": None,
        "charge_amount": Decimal("4200.00"),
        "paid_amount":   Decimal("1100.00"),
        "line_items": [
            {"line_item_id": "li-005", "cpt_hcpcs": "99291",
             "service_date": "2026-03-14",
             "revenue_code": None, "charge": Decimal("4200.00")},
        ],
    },
    {
        "claim_id": "prof-claim-2026-03-882442-cardiology",
        "payer_id": "PAYER-01",
        "member_id": "MEM-100874-A",
        "claim_type": "professional",
        "billing_provider_npi":   "1659473820",
        "rendering_provider_npi": "1659473820",
        "service_from_date":  "2026-03-14",
        "service_through_date": "2026-03-14",
        "primary_diagnosis_icd10": "I50.23",
        "secondary_diagnoses_icd10": [],
        "procedures_cpt_hcpcs": ["99253"],
        "revenue_codes": [],
        "drg_code": None,
        "place_of_service": "21",
        "claim_status": "denied",
        "adjustment_indicator": False,
        "original_claim_id": None,
        "charge_amount": Decimal("850.00"),
        "paid_amount":   Decimal("0.00"),
        "line_items": [
            {"line_item_id": "li-006", "cpt_hcpcs": "99253",
             "service_date": "2026-03-14",
             "revenue_code": None, "charge": Decimal("850.00")},
        ],
    },
    # Resubmission of the cardiology claim with prior auth on file.
    {
        "claim_id": "prof-claim-2026-04-905712-resubmit-cardiology",
        "payer_id": "PAYER-01",
        "member_id": "MEM-100874-A",
        "claim_type": "professional",
        "billing_provider_npi":   "1659473820",
        "rendering_provider_npi": "1659473820",
        "service_from_date":  "2026-03-14",
        "service_through_date": "2026-03-14",
        "primary_diagnosis_icd10": "I50.23",
        "secondary_diagnoses_icd10": [],
        "procedures_cpt_hcpcs": ["99253"],
        "revenue_codes": [],
        "drg_code": None,
        "place_of_service": "21",
        "claim_status": "paid",
        "adjustment_indicator": True,
        "original_claim_id": "prof-claim-2026-03-882442-cardiology",
        "charge_amount": Decimal("850.00"),
        "paid_amount":   Decimal("220.00"),
        "line_items": [
            {"line_item_id": "li-006r", "cpt_hcpcs": "99253",
             "service_date": "2026-03-14",
             "revenue_code": None, "charge": Decimal("850.00")},
        ],
    },
    {
        "claim_id": "prof-claim-2026-03-882444-radiology",
        "payer_id": "PAYER-01",
        "member_id": "MEM-100874-A",
        "claim_type": "professional",
        "billing_provider_npi":   "1245678901",
        "rendering_provider_npi": "1245678901",
        "service_from_date":  "2026-03-15",
        "service_through_date": "2026-03-15",
        "primary_diagnosis_icd10": "I50.21",
        "secondary_diagnoses_icd10": [],
        "procedures_cpt_hcpcs": ["71250"],
        "revenue_codes": [],
        "drg_code": None,
        "place_of_service": "21",
        "claim_status": "paid",
        "adjustment_indicator": False,
        "original_claim_id": None,
        "charge_amount": Decimal("420.00"),
        "paid_amount":   Decimal("110.00"),
        "line_items": [
            {"line_item_id": "li-007", "cpt_hcpcs": "71250",
             "service_date": "2026-03-15",
             "revenue_code": None, "charge": Decimal("420.00")},
        ],
    },
    # Alex Johnson's ER visit. Single facility claim plus one
    # professional claim, same day, same patient.
    {
        "claim_id": "fac-claim-2026-04-er-1003",
        "payer_id": "PAYER-02",
        "member_id": "MEM-201927-B",
        "claim_type": "facility_er",
        "billing_provider_npi":   "1456789012",
        "rendering_provider_npi": "1456789012",
        "service_from_date":  "2026-04-02",
        "service_through_date": "2026-04-02",
        "primary_diagnosis_icd10": "R10.9",
        "secondary_diagnoses_icd10": [],
        "procedures_cpt_hcpcs": ["74177"],
        "revenue_codes": ["0450", "0320"],
        "drg_code": None,
        "place_of_service": "23",
        "claim_status": "paid",
        "adjustment_indicator": False,
        "original_claim_id": None,
        "charge_amount": Decimal("3200.00"),
        "paid_amount":   Decimal("780.00"),
        "line_items": [
            {"line_item_id": "li-101", "cpt_hcpcs": None,
             "service_date": "2026-04-02",
             "revenue_code": "0450", "charge": Decimal("1800.00")},
            {"line_item_id": "li-102", "cpt_hcpcs": "74177",
             "service_date": "2026-04-02",
             "revenue_code": "0320", "charge": Decimal("1400.00")},
        ],
    },
    {
        "claim_id": "prof-claim-2026-04-er-2003",
        "payer_id": "PAYER-02",
        "member_id": "MEM-201927-B",
        "claim_type": "professional",
        "billing_provider_npi":   "1987654321",
        "rendering_provider_npi": "1987654321",
        "service_from_date":  "2026-04-02",
        "service_through_date": "2026-04-02",
        "primary_diagnosis_icd10": "R10.9",
        "secondary_diagnoses_icd10": [],
        "procedures_cpt_hcpcs": ["99284"],
        "revenue_codes": [],
        "drg_code": None,
        "place_of_service": "23",
        "claim_status": "paid",
        "adjustment_indicator": False,
        "original_claim_id": None,
        "charge_amount": Decimal("680.00"),
        "paid_amount":   Decimal("160.00"),
        "line_items": [
            {"line_item_id": "li-103", "cpt_hcpcs": "99284",
             "service_date": "2026-04-02",
             "revenue_code": None, "charge": Decimal("680.00")},
        ],
    },
    # Maria Garcia-Lopez clean outpatient claim, expected to
    # match the morning encounter on 2026-04-15.
    {
        "claim_id": "prof-claim-2026-04-op-3001",
        "payer_id": "PAYER-03",
        "member_id": "MEM-303441-C",
        "claim_type": "professional",
        "billing_provider_npi":   "1112223334",
        "rendering_provider_npi": "1112223334",
        "service_from_date":  "2026-04-15",
        "service_through_date": "2026-04-15",
        "primary_diagnosis_icd10": "E11.9",
        "secondary_diagnoses_icd10": ["Z00.00"],
        "procedures_cpt_hcpcs": ["99213"],
        "revenue_codes": [],
        "drg_code": None,
        "place_of_service": "11",
        "claim_status": "paid",
        "adjustment_indicator": False,
        "original_claim_id": None,
        "charge_amount": Decimal("180.00"),
        "paid_amount":   Decimal("85.00"),
        "line_items": [
            {"line_item_id": "li-201", "cpt_hcpcs": "99213",
             "service_date": "2026-04-15",
             "revenue_code": None, "charge": Decimal("180.00")},
        ],
    },
    # External encounter case: Sam Williams has a claim from an
    # outside cardiology practice. Patient resolves through
    # cross-reference but no local clinical encounter exists; the
    # cluster gets tagged EXTERNAL_ENCOUNTER.
    {
        "claim_id": "prof-claim-2026-02-712441-outside-cardiology",
        "payer_id": "PAYER-01",
        "member_id": "MEM-500000-Z",
        "claim_type": "professional",
        "billing_provider_npi":   "1659473821",
        "rendering_provider_npi": "1659473821",
        "service_from_date":  "2026-02-08",
        "service_through_date": "2026-02-08",
        "primary_diagnosis_icd10": "I10",
        "secondary_diagnoses_icd10": ["I50.20"],
        "procedures_cpt_hcpcs": ["93000", "93306"],
        "revenue_codes": [],
        "drg_code": None,
        "place_of_service": "11",
        "claim_status": "paid",
        "adjustment_indicator": False,
        "original_claim_id": None,
        "charge_amount": Decimal("520.00"),
        "paid_amount":   Decimal("210.00"),
        "line_items": [
            {"line_item_id": "li-501", "cpt_hcpcs": "93000",
             "service_date": "2026-02-08",
             "revenue_code": None, "charge": Decimal("160.00")},
            {"line_item_id": "li-502", "cpt_hcpcs": "93306",
             "service_date": "2026-02-08",
             "revenue_code": None, "charge": Decimal("360.00")},
        ],
    },
]

# --- Mock vocabulary map ---
# Production wraps the institution's terminology server (UMLS,
# OHDSI Athena, or commercial). The mock includes a small CPT-to-
# internal-procedure-code map and a revenue-code-to-cost-center
# map sufficient for the demo.
class MockVocabularyMap:
    """Stand-in for the institutional vocabulary store."""

    def __init__(self):
        # CPT/HCPCS to internal procedure code. One-to-one for the
        # demo; production handles one-to-many and one-to-zero
        # mappings explicitly.
        self.cpt_to_internal = {
            "71250": ["INT-CT-CHEST"],
            "74177": ["INT-CT-ABDPELVIS"],
            "88305": ["INT-CYTO-PATH"],
            "99213": ["INT-OFFICEVISIT-EST"],
            "99253": ["INT-CONSULT-INPT"],
            "99284": ["INT-ED-VISIT"],
            "99291": ["INT-CRITCARE-INPT"],
            "93000": ["INT-EKG-12LEAD"],
            "93306": ["INT-ECHO-COMPLETE"],
        }
        # Revenue code to internal cost center.
        self.rev_to_cost_center = {
            "0110": "CC-ROOM-AND-BOARD",
            "0250": "CC-PHARMACY",
            "0300": "CC-LAB",
            "0310": "CC-PATHOLOGY",
            "0320": "CC-RADIOLOGY",
            "0450": "CC-EMERGENCY-ROOM",
        }
        # NDC to RxNorm (placeholder; not exercised in the demo).
        self.ndc_to_rxnorm = {}

    def lookup(self, source_system: str, source_code: str,
                target_system: str) -> list:
        if source_system == "cpt_hcpcs" and target_system == "internal_procedure_code":
            return self.cpt_to_internal.get(source_code, [])
        if source_system == "revenue_code" and target_system == "internal_cost_center":
            cc = self.rev_to_cost_center.get(source_code)
            return [cc] if cc else []
        if source_system == "ndc" and target_system == "rxnorm":
            return self.ndc_to_rxnorm.get(source_code, [])
        return []

    def versions_used(self) -> dict:
        return dict(VOCABULARY_VERSIONS)

# Module-level singletons for the demo.
vocabulary_map = MockVocabularyMap()

# --- In-memory linkage system-of-record (DynamoDB stand-in) ---
# Keyed on encounter_cluster_id. Each item is the latest version
# of the linkage; production keeps prior versions in a separate
# history table or as additional items keyed on (cluster_id, version).
_IN_MEMORY_LINKAGE_TABLE: dict = {}
_IN_MEMORY_OUTBOX: list = []

# --- In-memory invalidation index ---
# Keyed on (source_record_type, source_record_id) -> list of
# affected cluster_ids. Production writes this to DynamoDB so
# event-driven invalidation can find the affected linkages with a
# single point lookup.
_IN_MEMORY_INVALIDATION_INDEX: dict = {}

def _archive_to_s3(payload: dict, bucket: str, partition: str,
                     key_id: str = None) -> None:
    """Best-effort archive to S3. Failures logged and skipped (the demo prints what it would write)."""
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

## Step 1: Ingest and Normalize the Claims and Clinical Streams

*The pseudocode calls this `normalize_claims_and_clinical(input_partition_keys)`. The two streams arrive on different cadences in different formats. Claims arrive as X12 837/835 transactions for outbound flows, payer-specific flat files or FHIR ExplanationOfBenefit resources for inbound flows, and NCPDP feeds for pharmacy. Clinical data arrives as EHR-native extracts (Epic Clarity / Caboodle, Cerner / Oracle Health, equivalent) or as FHIR resources from a FHIR-native data lake. Both streams have to land in the raw zone byte-for-byte for audit replay, then get parsed into a normalized representation that the rest of the pipeline can join on. Skip the strict raw-zone preservation and you cannot reconstruct the original payload when a claim is later disputed or when an audit reaches back to a transaction from three years ago.*

```python
def _normalize_encounter_class(claim_type: str,
                                  place_of_service: str = None) -> str:
    """Map claim type (and place_of_service for professionals) to
    encounter class. Production handles more variations and uses
    revenue codes plus CPT category as additional signals."""
    facility_mapping = {
        "facility_inpatient":   "inpatient",
        "facility_outpatient":  "outpatient",
        "facility_er":          "emergency",
        "facility_observation": "observation",
        "pharmacy":             "pharmacy",
    }
    if claim_type in facility_mapping:
        return facility_mapping[claim_type]
    # Professional claims need place_of_service to infer the
    # encounter class. POS 21 = inpatient hospital, 22 = on-
    # campus outpatient, 23 = emergency room, 24 = ambulatory
    # surgical center, 11 = office.
    pos_mapping = {
        "21": "inpatient",
        "22": "outpatient",
        "23": "emergency",
        "24": "outpatient",
        "11": "outpatient",
    }
    return pos_mapping.get(place_of_service or "", "outpatient")

def normalize_claims_and_clinical(claims_input: list,
                                     clinical_input: dict) -> dict:
    """
    Land both streams in the curated zone in normalized form. In
    production this is a Glue/Spark job; in the demo it is an
    in-process pass that produces in-memory normalized records.

    Each stream gets archived to its respective raw S3 zone for
    forensic replay, then parsed into the normalized shape the
    downstream pipeline operates on.
    """
    # 1A: parse and normalize claims-side records.
    parsed_claims = []
    for raw_claim in claims_input:
        # Production calls a real X12, FHIR, or NCPDP parser here.
        # The demo input is already shaped like the parsed output.
        parsed = {
            "claim_id":              raw_claim["claim_id"],
            "payer_id":              raw_claim["payer_id"],
            "claim_type":            raw_claim["claim_type"],
            "billing_provider_npi":  raw_claim["billing_provider_npi"],
            "rendering_provider_npi": (
                raw_claim.get("rendering_provider_npi")
                or raw_claim["billing_provider_npi"]
            ),
            "member_id":             raw_claim["member_id"],
            "service_from_date":     raw_claim["service_from_date"],
            "service_through_date":  raw_claim["service_through_date"],
            "primary_diagnosis_icd10":
                raw_claim["primary_diagnosis_icd10"],
            "secondary_diagnoses_icd10":
                raw_claim.get("secondary_diagnoses_icd10", []),
            "procedures_cpt_hcpcs":
                raw_claim.get("procedures_cpt_hcpcs", []),
            "revenue_codes":         raw_claim.get("revenue_codes", []),
            "drg_code":              raw_claim.get("drg_code"),
            "place_of_service":      raw_claim.get("place_of_service"),
            "claim_status":          raw_claim["claim_status"],
            "adjustment_indicator":  raw_claim.get("adjustment_indicator", False),
            "original_claim_id":     raw_claim.get("original_claim_id"),
            "charge_amount":         _to_decimal(raw_claim.get("charge_amount", 0)),
            "paid_amount":           _to_decimal(raw_claim.get("paid_amount", 0)),
            "line_items":            raw_claim.get("line_items", []),
            "encounter_class_inferred":
                _normalize_encounter_class(raw_claim["claim_type"],
                                              raw_claim.get("place_of_service")),
            "received_at":           _now_iso(),
            "vocabulary_versions_at_parse": vocabulary_map.versions_used(),
        }
        parsed_claims.append(parsed)
        # Archive the raw payload to the raw-claims bucket for audit.
        _archive_to_s3(raw_claim, RAW_CLAIMS_BUCKET, "raw-claims",
                         key_id=raw_claim["claim_id"])

    # 1B: parse and normalize clinical-side records.
    parsed_clinical = []
    for encounter_id, encounter in clinical_input.items():
        # Production calls a real EHR-extract parser or FHIR
        # resource deserializer here. The demo input is already
        # shaped like the parsed output.
        parsed = {
            "encounter_id":             encounter["encounter_id"],
            "local_patient_id":         encounter["local_patient_id"],
            "encounter_class":          encounter["encounter_class"],
            "location_id":              encounter["location_id"],
            "attending_provider_npi":   encounter["attending_provider_npi"],
            "consulting_provider_npis": encounter.get("consulting_provider_npis", []),
            "admission_timestamp":      encounter["admission_timestamp"],
            "discharge_timestamp":      encounter["discharge_timestamp"],
            "encounter_diagnoses":      encounter.get("encounter_diagnoses", []),
            "procedures_internal":      encounter.get("procedures_internal", []),
            "medications_administered": encounter.get("medications_administered", []),
            "drg_code":                 encounter.get("drg_code"),
            "discharge_disposition":    encounter.get("discharge_disposition"),
            "source_extract_timestamp": _now_iso(),
        }
        parsed_clinical.append(parsed)
        _archive_to_s3(encounter, RAW_CLINICAL_BUCKET, "raw-clinical",
                         key_id=encounter_id)

    # 1C: write both normalized sets to the curated zone for
    # downstream stages. Production writes Parquet partitioned by
    # source/date; the demo returns Python dicts.
    _archive_to_s3({"normalized_claims": parsed_claims},
                     CURATED_BUCKET, "curated-claims")
    _archive_to_s3({"normalized_clinical": parsed_clinical},
                     CURATED_BUCKET, "curated-clinical")

    _emit_metric("ClaimsNormalized", float(len(parsed_claims)))
    _emit_metric("EncountersNormalized", float(len(parsed_clinical)))

    return {
        "claims":   parsed_claims,
        "clinical": parsed_clinical,
    }
```

---

## Step 2: Resolve Patient Identity Across the Streams

*The pseudocode calls this `link_patient(claim_record, cross_reference_table, mpi)`. Before any encounter-level linking can happen, the matcher has to know which clinical patient corresponds to which claims-side member. Within a single institution where a maintained MRN-to-member-ID cross-reference exists (built and maintained by the eligibility-matching pipeline from recipe 5.4 and the local MPI from recipe 5.1), this is largely deterministic. For external claims feeds covering populations where the cross-reference is incomplete, the patient link uses the same probabilistic-record-linkage scorer as 5.1 and 5.5 over the demographic fields the claims feed exposes. Skip the patient link or treat it as trivial and you produce encounter linkages that join the right encounters but the wrong patients, which silently corrupts every analytics output downstream.*

```python
def _xref_lookup(payer_id: str, member_id: str,
                  as_of_date: str) -> Optional[dict]:
    """
    Stand-in for a DynamoDB GetItem on the MRN-to-member-ID
    cross-reference table. Production reads from the table
    populated by recipe 5.4's eligibility matcher and maintained
    by recipe 5.1's MPI updates.
    """
    entry = SYNTHETIC_XREF.get((payer_id, member_id))
    if entry is None:
        return None
    # Validate the as_of date is within the cross-reference's
    # validity window. Production handles overlap with prior
    # versions of the cross-reference more carefully.
    valid_from = entry.get("valid_from")
    valid_to = entry.get("valid_to")
    if valid_from and as_of_date < valid_from:
        return None
    if valid_to and as_of_date > valid_to:
        return None
    return entry

def link_patient(claim: dict) -> dict:
    """
    Resolve the claim's payer-side member identity to the
    institution's local patient ID. Returns the resolved id and a
    confidence; on no-match, queues the claim for the patient-
    link review queue and returns a NULL resolution.
    """
    payer_id = claim["payer_id"]
    member_id = claim["member_id"]
    as_of = claim["service_from_date"]

    # 2A: deterministic match via cross-reference.
    xref = _xref_lookup(payer_id, member_id, as_of)
    if xref and xref["confidence"] >= CROSS_REF_HIGH_CONFIDENCE:
        return {
            "resolved_local_patient_id": xref["local_patient_id"],
            "link_method":               "cross_reference_deterministic",
            "link_confidence":           xref["confidence"],
            "cross_ref_version":         xref["version"],
        }

    # 2B: probabilistic fallback. The cross-reference is missing
    # or low-confidence; in production we pull the claim's
    # demographic fields (often from the X12 837's subscriber
    # loop or the FHIR ExplanationOfBenefit's patient reference)
    # and run the recipe 5.1 / 5.4 scorer against the local MPI.
    # The demo simulates a no-candidate case for any claim that
    # missed the cross-reference, which routes it to review.
    _emit_metric("PatientLinkFallback", 1.0)
    try:
        sqs_client.send_message(
            QueueUrl=PATIENT_REVIEW_QUEUE_URL,
            MessageBody=json.dumps({
                "claim_id":   claim["claim_id"],
                "payer_id":   payer_id,
                "member_id":  member_id,
                "as_of_date": as_of,
                "reason":     "cross_reference_miss_no_demographic_match",
            }, default=str),
        )
    except Exception as exc:
        logger.info("review queue send skipped (demo mode)",
                     extra={"error": str(exc)})

    return {
        "resolved_local_patient_id": None,
        "link_method":               "deferred_patient_review",
        "link_confidence":           Decimal("0.0"),
        "queued_for_review":         True,
    }
```

---

## Step 3: Cluster Patient-Resolved Claims into Encounter Clusters

*The pseudocode calls this `cluster_claims_by_encounter(patient_resolved_claims)`. Multiple claims describe a single underlying encounter, and grouping them is the first structural job after the patient link. The cluster-key is patient plus encounter-class plus a service-date range; the date tolerance is encounter-class-specific. The clustering also detects resubmissions and adjustments so the cluster's authoritative version of each claim is the latest valid one. Skip the clustering and you treat thirteen claims for one inpatient stay as thirteen separate encounters, which over-counts admissions, double-counts readmissions, and corrupts every cost-and-quality calculation that depends on encounter-level rollups.*

```python
def _parse_date(d: str) -> datetime:
    """Parse YYYY-MM-DD into a datetime at midnight UTC."""
    return datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc)

def _date_overlap_with_buffer(a_start: str, a_end: str,
                                 b_start: str, b_end: str,
                                 buffer_days: int) -> bool:
    """Two date ranges overlap within the buffer tolerance."""
    a_s = _parse_date(a_start) - timedelta(days=buffer_days)
    a_e = _parse_date(a_end)   + timedelta(days=buffer_days)
    b_s = _parse_date(b_start)
    b_e = _parse_date(b_end)
    return not (a_e < b_s or b_e < a_s)

def _generate_cluster_id(local_patient_id: str, encounter_class: str,
                            anchor_date: str) -> str:
    """Deterministic cluster ID. Production uses a UUID with the
    same fields hashed in for idempotency on re-runs."""
    return f"ec-{anchor_date}-{local_patient_id[-10:]}-{encounter_class}-{uuid.uuid4().hex[:6]}"

def _infer_role(claim: dict, cluster: dict) -> str:
    """Tag the claim's role within the cluster."""
    if claim.get("adjustment_indicator"):
        return "adjustment_or_resubmission"
    if claim["claim_type"] in {"facility_inpatient", "facility_er",
                                  "facility_outpatient",
                                  "facility_observation"}:
        if not any(c["claim_type"].startswith("facility_")
                    for c in cluster["constituent_claims"]):
            return "primary_facility"
        return "additional_facility"
    if claim["claim_type"] == "professional":
        return "professional"
    if claim["claim_type"] == "pharmacy":
        return "pharmacy"
    return "ancillary"

def cluster_claims_by_encounter(patient_resolved_claims: list) -> list:
    """
    Group patient-resolved claims into encounter clusters keyed
    on patient + encounter_class + a service-date range.
    Resubmissions and adjustments are detected and the cluster's
    canonical claim is the latest valid version.
    """
    # 3A: drop claims that did not resolve to a local patient.
    # In production those go through the review queue and re-
    # enter the pipeline once a human resolves the patient ID.
    resolvable = [c for c in patient_resolved_claims
                    if c.get("resolved_local_patient_id")]

    # 3B: detect resubmission/adjustment chains. Claims with the
    # same original_claim_id are versions of the same underlying
    # claim. Within a chain, the latest is the authoritative
    # canonical version; the earlier ones are kept for history.
    chain_to_claims = {}
    standalone = []
    for claim in resolvable:
        if claim.get("original_claim_id"):
            chain_to_claims.setdefault(claim["original_claim_id"], []).append(claim)
        else:
            chain_to_claims.setdefault(claim["claim_id"], []).append(claim)

    canonical_claims = []
    for chain_key, chain_members in chain_to_claims.items():
        # Sort by adjustment_indicator (resubmissions are later)
        # then by service_through_date as a tiebreaker.
        chain_members.sort(
            key=lambda c: (c.get("adjustment_indicator", False),
                              c["service_through_date"]))
        canonical = chain_members[-1]
        canonical["chain_history"] = [
            c["claim_id"] for c in chain_members[:-1]
        ]
        canonical_claims.append(canonical)

    # 3C: group canonical claims into encounter clusters by
    # patient + encounter_class + overlapping date window.
    clusters = []
    canonical_claims.sort(
        key=lambda c: (c["resolved_local_patient_id"],
                          c["service_from_date"]))
    for claim in canonical_claims:
        encounter_class = claim["encounter_class_inferred"]
        buffer_days = ENCOUNTER_CLASS_DATE_TOLERANCE_DAYS.get(encounter_class, 1)

        existing_cluster = None
        for cluster in clusters:
            if (cluster["local_patient_id"] != claim["resolved_local_patient_id"]
                    or cluster["encounter_class"] != encounter_class):
                continue
            if _date_overlap_with_buffer(
                    cluster["cluster_window_start"],
                    cluster["cluster_window_end"],
                    claim["service_from_date"],
                    claim["service_through_date"],
                    buffer_days):
                existing_cluster = cluster
                break

        if existing_cluster is not None:
            existing_cluster["constituent_claims"].append(claim)
            existing_cluster["cluster_window_start"] = min(
                existing_cluster["cluster_window_start"],
                claim["service_from_date"])
            existing_cluster["cluster_window_end"] = max(
                existing_cluster["cluster_window_end"],
                claim["service_through_date"])
            existing_cluster["aggregate_diagnoses"].update(
                [claim["primary_diagnosis_icd10"]]
                + (claim.get("secondary_diagnoses_icd10") or []))
            claim["cluster_role"] = _infer_role(claim, existing_cluster)
        else:
            # Build the cluster shell first, score the role, THEN
            # add the claim so _infer_role's "is any OTHER facility
            # claim already here" check works correctly.
            new_cluster = {
                "encounter_cluster_id": _generate_cluster_id(
                    claim["resolved_local_patient_id"],
                    encounter_class,
                    claim["service_from_date"]),
                "local_patient_id":     claim["resolved_local_patient_id"],
                "encounter_class":      encounter_class,
                "cluster_window_start": claim["service_from_date"],
                "cluster_window_end":   claim["service_through_date"],
                "constituent_claims":   [],
                "aggregate_diagnoses":  set(
                    [claim["primary_diagnosis_icd10"]]
                    + (claim.get("secondary_diagnoses_icd10") or [])),
                "drg_code":             claim.get("drg_code"),
                "primary_facility_npi":
                    claim["billing_provider_npi"]
                    if claim["claim_type"].startswith("facility_") else None,
            }
            claim["cluster_role"] = _infer_role(claim, new_cluster)
            new_cluster["constituent_claims"].append(claim)
            clusters.append(new_cluster)

    # 3D: post-cluster reconciliation. Aggregate the cluster's
    # totals and convert the diagnoses set to a sorted list for
    # deterministic downstream serialization.
    for cluster in clusters:
        cluster["aggregate_diagnoses"] = sorted(cluster["aggregate_diagnoses"])
        cluster["cluster_charge_total"] = sum(
            (c.get("charge_amount") or Decimal("0"))
            for c in cluster["constituent_claims"])
        cluster["cluster_paid_total"] = sum(
            (c.get("paid_amount") or Decimal("0"))
            for c in cluster["constituent_claims"])
        # Adopt the first non-null DRG seen in the cluster (the
        # facility claim usually carries the DRG).
        if cluster["drg_code"] is None:
            for c in cluster["constituent_claims"]:
                if c.get("drg_code"):
                    cluster["drg_code"] = c["drg_code"]
                    break

    _emit_metric("ClustersFormed", float(len(clusters)))
    return clusters
```

---

## Step 4: Match Each Encounter Cluster to a Clinical Encounter

*The pseudocode calls this `link_encounter(cluster, clinical_encounters_for_patient, matcher_config)`. The cluster has a patient, an encounter class, a date window, a set of diagnoses, and a billing provider. The clinical encounter has the same patient, an encounter class, an admission/discharge timestamp, an attending provider, and a diagnosis set. The match scores each (cluster, encounter) candidate pair and applies confidence thresholds. Skip the encounter-level link and you have claim clusters and clinical encounters but no joined unit of analysis, which means every analytics question that needs both administrative and clinical detail at the encounter grain has to be re-derived from raw data.*

```python
def _date_alignment_score(cluster_start: str, cluster_end: str,
                            ehr_admission: str, ehr_discharge: str) -> Decimal:
    """Score date alignment between a cluster window and an EHR
    encounter window. Tight overlap = 1.0; partial = 0.5;
    disjoint = 0.0."""
    cs = _parse_date(cluster_start)
    ce = _parse_date(cluster_end)
    es = datetime.fromisoformat(ehr_admission.replace("Z", "+00:00"))
    ee = datetime.fromisoformat(ehr_discharge.replace("Z", "+00:00"))
    es = es.replace(hour=0, minute=0, second=0, microsecond=0)
    ee = ee.replace(hour=0, minute=0, second=0, microsecond=0)
    if ce < es or ee < cs:
        return Decimal("0.0")
    overlap_start = max(cs, es)
    overlap_end = min(ce, ee)
    overlap_days = (overlap_end - overlap_start).days + 1
    union_start = min(cs, es)
    union_end = max(ce, ee)
    union_days = (union_end - union_start).days + 1
    if union_days <= 0:
        return Decimal("1.0")
    return _to_decimal(max(0.0, min(1.0, overlap_days / union_days)))

def _provider_alignment_score(cluster_claims: list, attending_npi: str,
                                 consulting_npis: list) -> Decimal:
    """Score whether the cluster's rendering NPIs match the EHR
    encounter's attending or consulting providers."""
    if not attending_npi:
        return Decimal("0.5")
    cluster_npis = set()
    for c in cluster_claims:
        if c.get("rendering_provider_npi"):
            cluster_npis.add(c["rendering_provider_npi"])
        if c.get("billing_provider_npi"):
            cluster_npis.add(c["billing_provider_npi"])
    candidate_set = {attending_npi} | set(consulting_npis or [])
    matches = cluster_npis & candidate_set
    if not cluster_npis:
        return Decimal("0.5")
    if attending_npi in cluster_npis:
        return Decimal("1.0")
    if matches:
        return Decimal("0.7")
    return Decimal("0.0")

def _class_compatibility_score(cluster_class: str, ehr_class: str) -> Decimal:
    """Encounter-class compatibility: exact match = 1.0; known
    related pair = 0.7; unrelated = 0.0."""
    if cluster_class == ehr_class:
        return Decimal("1.0")
    related_pairs = {
        ("emergency", "observation"),
        ("observation", "emergency"),
        ("observation", "inpatient"),
        ("inpatient", "observation"),
        ("emergency", "inpatient"),
        ("inpatient", "emergency"),
    }
    if (cluster_class, ehr_class) in related_pairs:
        return Decimal("0.7")
    return Decimal("0.0")

def _diagnosis_concordance_score(cluster_dx: list, ehr_dx: list) -> Decimal:
    """Soft signal: scored as Jaccard overlap with hierarchy-
    aware credit (the demo uses prefix-3 collapse as a stand-in
    for the ICD-10 chapter hierarchy)."""
    if not cluster_dx or not ehr_dx:
        return Decimal("0.5")
    def _hierarchy(codes):
        return {c[:3] for c in codes if c}
    cluster_full = set(cluster_dx)
    ehr_full = set(ehr_dx)
    cluster_hier = _hierarchy(cluster_dx)
    ehr_hier = _hierarchy(ehr_dx)
    exact_overlap = cluster_full & ehr_full
    hier_overlap = cluster_hier & ehr_hier
    if exact_overlap:
        # Exact code match scores higher than chapter-only match,
        # but the score is normalized to stay in [0, 1] for
        # comparability with the other features.
        union = cluster_full | ehr_full
        jaccard = Decimal(len(exact_overlap)) / Decimal(max(1, len(union)))
        return _to_decimal(min(Decimal("1.0"), jaccard + Decimal("0.3")))
    if hier_overlap:
        union = cluster_hier | ehr_hier
        return _to_decimal(0.4 * (len(hier_overlap) / max(1, len(union))))
    return Decimal("0.1")

def _procedure_concordance_score(cluster_claims: list,
                                    ehr_procedures: list) -> Decimal:
    """Score CPT-mapped vs internal-procedure overlap."""
    cluster_internal_codes = set()
    for c in cluster_claims:
        for cpt in c.get("procedures_cpt_hcpcs", []):
            cluster_internal_codes.update(
                vocabulary_map.lookup("cpt_hcpcs", cpt,
                                          "internal_procedure_code"))
    ehr_internal_codes = {p["code"] for p in (ehr_procedures or [])}
    if not cluster_internal_codes and not ehr_internal_codes:
        return Decimal("0.5")
    if not cluster_internal_codes or not ehr_internal_codes:
        return Decimal("0.3")
    overlap = cluster_internal_codes & ehr_internal_codes
    union = cluster_internal_codes | ehr_internal_codes
    return _to_decimal(len(overlap) / len(union))

def _drg_concordance_score(cluster_drg: Optional[str],
                              ehr_drg: Optional[str]) -> Decimal:
    """DRG concordance only applies if both are present."""
    if cluster_drg is None or ehr_drg is None:
        return Decimal("0.5")
    return Decimal("1.0") if cluster_drg == ehr_drg else Decimal("0.0")

def _composite_encounter_score(features: dict) -> Decimal:
    total = sum(ENCOUNTER_SCORE_WEIGHTS.values())
    weighted = sum(ENCOUNTER_SCORE_WEIGHTS[k] * features[k]
                     for k in ENCOUNTER_SCORE_WEIGHTS)
    return weighted / total

def link_encounter(cluster: dict,
                      clinical_encounters_for_patient: list) -> dict:
    """
    Score each candidate clinical encounter against the cluster
    and apply confidence thresholds.
    """
    encounter_class = cluster["encounter_class"]
    tolerance = ENCOUNTER_CLASS_DATE_TOLERANCE_DAYS.get(encounter_class, 1)

    # 4A: filter to candidate encounters by class and date.
    candidates = []
    for enc in clinical_encounters_for_patient:
        # Class compatibility filter (allow related-class pairs
        # through with a downscored class signal).
        if _class_compatibility_score(encounter_class,
                                          enc["encounter_class"]) == Decimal("0.0"):
            continue
        admit_date = enc["admission_timestamp"][:10]
        discharge_date = enc["discharge_timestamp"][:10]
        if not _date_overlap_with_buffer(
                cluster["cluster_window_start"],
                cluster["cluster_window_end"],
                admit_date, discharge_date,
                tolerance):
            continue
        candidates.append(enc)

    # 4B: handle the no-candidate case as EXTERNAL_ENCOUNTER.
    if not candidates:
        return {
            "encounter_cluster_id":     cluster["encounter_cluster_id"],
            "link_status":              "EXTERNAL_ENCOUNTER",
            "inferred_external_npi":    cluster.get("primary_facility_npi"),
            "inferred_external_class":  encounter_class,
            "external_diagnoses":       cluster["aggregate_diagnoses"],
            "link_confidence":          None,
            "link_method":              "no_candidate_in_local_clinical",
        }

    # 4C: score each candidate.
    scored = []
    for enc in candidates:
        features = {
            "date_alignment":
                _date_alignment_score(cluster["cluster_window_start"],
                                          cluster["cluster_window_end"],
                                          enc["admission_timestamp"],
                                          enc["discharge_timestamp"]),
            "provider_alignment":
                _provider_alignment_score(
                    cluster["constituent_claims"],
                    enc["attending_provider_npi"],
                    enc.get("consulting_provider_npis", [])),
            "class_compatibility":
                _class_compatibility_score(encounter_class,
                                              enc["encounter_class"]),
            "diagnosis_concordance":
                _diagnosis_concordance_score(
                    cluster["aggregate_diagnoses"],
                    enc.get("encounter_diagnoses", [])),
            "procedure_concordance":
                _procedure_concordance_score(
                    cluster["constituent_claims"],
                    enc.get("procedures_internal", [])),
            "drg_concordance":
                _drg_concordance_score(cluster.get("drg_code"),
                                          enc.get("drg_code")),
        }
        composite = _composite_encounter_score(features)
        scored.append({"encounter": enc, "features": features,
                          "composite": composite})

    best = max(scored, key=lambda s: s["composite"])

    # 4D: apply thresholds. Conservative band-routing.
    cohort_bucket = SYNTHETIC_LOCAL_MPI.get(
        cluster["local_patient_id"], {}).get("cohort_bucket", "unknown")
    _emit_metric("EncounterMatchScore", float(best["composite"]),
                  dimensions={"CohortBucket": cohort_bucket,
                                "EncounterClass": encounter_class})

    base = {
        "encounter_cluster_id":   cluster["encounter_cluster_id"],
        "score_breakdown":        best["features"],
        "matcher_config_version": MATCHER_CONFIG_VERSION,
    }

    if best["composite"] >= ENCOUNTER_LINK_HIGH_THRESHOLD:
        return {**base,
                "link_status":               "LINKED_HIGH_CONFIDENCE",
                "linked_clinical_encounter_id": best["encounter"]["encounter_id"],
                "link_confidence":           best["composite"],
                "link_method":               "probabilistic_high_confidence",
                "matched_clinical_encounter_diagnoses":
                    best["encounter"].get("encounter_diagnoses", []),
                "matched_clinical_encounter_drg":
                    best["encounter"].get("drg_code")}
    if best["composite"] >= ENCOUNTER_LINK_MED_THRESHOLD:
        return {**base,
                "link_status":               "LINKED_MED_CONFIDENCE",
                "linked_clinical_encounter_id": best["encounter"]["encounter_id"],
                "link_confidence":           best["composite"],
                "link_method":               "probabilistic_med_confidence",
                "usage_caveat":
                    "use_with_confidence_filter_in_quality_measurement",
                "matched_clinical_encounter_diagnoses":
                    best["encounter"].get("encounter_diagnoses", []),
                "matched_clinical_encounter_drg":
                    best["encounter"].get("drg_code")}
    if best["composite"] <= ENCOUNTER_LINK_REJECT_THRESHOLD:
        return {**base,
                "link_status":          "NO_LINK",
                "best_candidate_id":    best["encounter"]["encounter_id"],
                "best_candidate_score": best["composite"],
                "link_confidence":      best["composite"],
                "link_method":          "below_link_threshold"}

    # Review band: queue for human review and persist a
    # tentative link with REVIEW_PENDING status.
    try:
        sqs_client.send_message(
            QueueUrl=ENCOUNTER_REVIEW_QUEUE_URL,
            MessageBody=json.dumps({
                "encounter_cluster_id": cluster["encounter_cluster_id"],
                "scored_candidates": [
                    {"encounter_id": s["encounter"]["encounter_id"],
                     "composite": str(s["composite"])}
                    for s in scored],
            }, default=str),
        )
    except Exception as exc:
        logger.info("review queue send skipped (demo mode)",
                     extra={"error": str(exc)})

    return {**base,
            "link_status":          "REVIEW_PENDING",
            "best_candidate_id":    best["encounter"]["encounter_id"],
            "best_candidate_score": best["composite"],
            "link_confidence":      best["composite"],
            "queued_for_review":    True}
```

---

## Step 5: Attribute Claim Line Items to Clinical Events

*The pseudocode calls this `attribute_care_events(linked_cluster, clinical_encounter, vocabulary_map)`. Once the cluster is linked to a clinical encounter, the line items on the constituent claims need to be attributed to specific clinical events (orders, procedures, medication administrations) inside that encounter. The CPT/HCPCS codes on the claims map to internal procedure codes via the vocabulary map; the NDCs on pharmacy claims map to RxNorm codes that correspond to medication administrations; the date-and-time on the claim line aligns with the clinical event's timestamp. Skip the line-item attribution and the linkage answers "did this encounter happen" but does not answer "what happened during it" at the level of cost-and-quality analytics that the institution typically needs.*

```python
def _date_within_tolerance_hours(claim_service_date: str,
                                    event_timestamp: str,
                                    tolerance_hours: int) -> bool:
    """Date alignment between a line-item service date (which may
    be calendar-only) and a clinical event timestamp."""
    cs = _parse_date(claim_service_date)
    et = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00"))
    delta = abs((et - cs).total_seconds()) / 3600.0
    return delta <= tolerance_hours

def _pick_best_clinical_event_candidate(candidates: list,
                                            line_item: dict) -> dict:
    """Pick the closest-in-time event when several match the
    line item's mapped internal codes."""
    if len(candidates) == 1:
        return candidates[0]
    cs = _parse_date(line_item["service_date"])
    def _delta(ev):
        et = datetime.fromisoformat(
            ev["event_timestamp"].replace("Z", "+00:00"))
        return abs((et - cs).total_seconds())
    return min(candidates, key=_delta)

def attribute_care_events(linked_cluster: dict,
                              clinical_encounter: Optional[dict]) -> dict:
    """
    Attribute each claim line item to a specific clinical event
    on the matched encounter. Skips clusters that did not link.
    """
    cluster_id = linked_cluster["encounter_cluster_id"]
    if linked_cluster["link_status"] not in {"LINKED_HIGH_CONFIDENCE",
                                                  "LINKED_MED_CONFIDENCE"}:
        return {
            "encounter_cluster_id":     cluster_id,
            "line_item_attributions":   [],
            "unattributed_line_items":  [],
            "attribution_coverage":     None,
            "vocabulary_versions":      vocabulary_map.versions_used(),
        }

    if clinical_encounter is None:
        # Defensive guard; should not happen for LINKED status.
        return {
            "encounter_cluster_id":     cluster_id,
            "line_item_attributions":   [],
            "unattributed_line_items":  [],
            "attribution_coverage":     None,
            "vocabulary_versions":      vocabulary_map.versions_used(),
        }

    line_item_attributions = []
    unattributed_line_items = []
    available_events = ((clinical_encounter.get("procedures_internal") or [])
                          + (clinical_encounter.get("medications_administered")
                             or []))

    for claim in linked_cluster["cluster"]["constituent_claims"]:
        for li in claim.get("line_items", []):
            cpt = li.get("cpt_hcpcs")
            if cpt is None:
                # Revenue-code-only line items attribute to a
                # cost center rather than a clinical event.
                rev = li.get("revenue_code")
                if rev:
                    cost_center = vocabulary_map.lookup(
                        "revenue_code", rev, "internal_cost_center")
                    if cost_center:
                        line_item_attributions.append({
                            "claim_id":         claim["claim_id"],
                            "line_item_id":     li["line_item_id"],
                            "source_code":      f"REV:{rev}",
                            "attributed_cost_center": cost_center[0],
                            "attribution_method": "revenue_code_to_cost_center",
                            "attribution_confidence": Decimal("0.9"),
                        })
                        continue
                unattributed_line_items.append({
                    "claim_id":     claim["claim_id"],
                    "line_item_id": li["line_item_id"],
                    "reason":       "no_cpt_no_revenue_code",
                })
                continue

            internal_codes = vocabulary_map.lookup(
                "cpt_hcpcs", cpt, "internal_procedure_code")
            if not internal_codes:
                unattributed_line_items.append({
                    "claim_id":     claim["claim_id"],
                    "line_item_id": li["line_item_id"],
                    "reason":       "no_vocabulary_mapping",
                    "source_code":  cpt,
                })
                # Production sends to the line-item review queue.
                try:
                    sqs_client.send_message(
                        QueueUrl=LINE_ITEM_REVIEW_QUEUE_URL,
                        MessageBody=json.dumps({
                            "claim_id":     claim["claim_id"],
                            "line_item_id": li["line_item_id"],
                            "source_code":  cpt,
                            "reason":       "no_vocabulary_mapping",
                        }, default=str),
                    )
                except Exception as exc:
                    logger.info("line-item review queue send skipped",
                                 extra={"error": str(exc)})
                continue

            event_candidates = [
                ev for ev in available_events
                if ev["code"] in internal_codes
                and _date_within_tolerance_hours(
                       li["service_date"], ev["event_timestamp"],
                       LINE_ITEM_DATE_TOLERANCE_HOURS)
            ]

            if not event_candidates:
                unattributed_line_items.append({
                    "claim_id":     claim["claim_id"],
                    "line_item_id": li["line_item_id"],
                    "reason":       "no_matching_clinical_event",
                    "source_code":  cpt,
                    "mapped_internal_codes": internal_codes,
                })
                continue

            best_event = _pick_best_clinical_event_candidate(
                event_candidates, li)
            line_item_attributions.append({
                "claim_id":         claim["claim_id"],
                "line_item_id":     li["line_item_id"],
                "source_code":      cpt,
                "attributed_clinical_event_id": best_event["event_id"],
                "attribution_confidence":
                    Decimal("0.95")
                    if len(event_candidates) == 1 else Decimal("0.85"),
                "attribution_method": "vocabulary_map_plus_temporal",
            })

    total = len(line_item_attributions) + len(unattributed_line_items)
    coverage = (Decimal(len(line_item_attributions)) / Decimal(total)
                  if total > 0 else None)
    if coverage is not None:
        cohort_bucket = SYNTHETIC_LOCAL_MPI.get(
            linked_cluster.get("cluster", {}).get("local_patient_id", ""),
            {}).get("cohort_bucket", "unknown")
        _emit_metric("AttributionCoverage", float(coverage),
                      dimensions={"CohortBucket": cohort_bucket,
                                    "EncounterClass":
                                        clinical_encounter["encounter_class"]})

    return {
        "encounter_cluster_id":     cluster_id,
        "encounter_id":             clinical_encounter["encounter_id"],
        "line_item_attributions":   line_item_attributions,
        "unattributed_line_items":  unattributed_line_items,
        "attribution_coverage":     coverage,
        "vocabulary_versions":      vocabulary_map.versions_used(),
    }
```

---

## Step 6: Persist, Audit, and React to Invalidation Events

*The pseudocode calls this `persist_and_emit(linkage_decision, attribution_decision)` plus `invalidate_on_event(event)`. Write the linkage to DynamoDB as the system of record, archive the curated linkage record to S3, and emit the cross-recipe event so downstream consumers can refresh. On invalidation events (claim adjustment, EHR amendment, identity merge, vocabulary refresh), re-evaluate selectively rather than recomputing the entire pipeline. Skip the invalidation pipeline and the linkage table is correct on day one and silently wrong by month three.*

```python
def persist_and_emit(linkage_decision: dict,
                       attribution_decision: dict) -> dict:
    """
    Write the linkage record to DynamoDB, archive to S3, and
    emit the cross-recipe event for downstream consumers.
    """
    # 6A: build the linkage record. Each record references the
    # configuration version active at decision time, supporting
    # forensic reconstruction when a future audit asks "what was
    # the matcher doing on day X."
    cluster = linkage_decision["cluster"]
    linkage_record = _serialize_for_dynamodb({
        "encounter_cluster_id":      cluster["encounter_cluster_id"],
        "local_patient_id":          cluster["local_patient_id"],
        "encounter_class":           cluster["encounter_class"],
        "cluster_window_start":      cluster["cluster_window_start"],
        "cluster_window_end":        cluster["cluster_window_end"],
        "constituent_claim_ids":     [c["claim_id"]
                                          for c in cluster["constituent_claims"]],
        "primary_diagnoses_claim":   sorted({
            c["primary_diagnosis_icd10"]
            for c in cluster["constituent_claims"]
            if c.get("primary_diagnosis_icd10")}),
        "secondary_diagnoses_claim": sorted({
            d for c in cluster["constituent_claims"]
            for d in (c.get("secondary_diagnoses_icd10") or [])}),
        "primary_diagnoses_ehr":
            linkage_decision.get("matched_clinical_encounter_diagnoses", []),
        "drg_code_claim":            cluster.get("drg_code"),
        "drg_code_ehr":
            linkage_decision.get("matched_clinical_encounter_drg"),
        "cluster_charge_total":      cluster["cluster_charge_total"],
        "cluster_paid_total":        cluster["cluster_paid_total"],
        "link_status":               linkage_decision["link_status"],
        "linked_clinical_encounter_id":
            linkage_decision.get("linked_clinical_encounter_id"),
        "link_confidence":           linkage_decision.get("link_confidence"),
        "link_method":               linkage_decision.get("link_method"),
        "score_breakdown":           linkage_decision.get("score_breakdown"),
        "inferred_external_npi":
            linkage_decision.get("inferred_external_npi"),
        "external_diagnoses":        linkage_decision.get("external_diagnoses"),
        "line_item_attributions":
            attribution_decision.get("line_item_attributions", []),
        "unattributed_line_items":
            attribution_decision.get("unattributed_line_items", []),
        "attribution_coverage":
            attribution_decision.get("attribution_coverage"),
        "matcher_config_version":    MATCHER_CONFIG_VERSION,
        "vocabulary_versions":       vocabulary_map.versions_used(),
        "resolved_at":               _now_iso(),
        # NOTE: Demo writes one item per cluster keyed on
        # encounter_cluster_id only. The pseudocode's
        # next_version_for(...) pattern requires a composite
        # (encounter_cluster_id, version) key on the production
        # table; the ConditionExpression below would change to
        # attribute_not_exists(version) so re-links after
        # invalidation append rather than fail. Production:
        # extend the table schema to include version as a sort
        # key, replace version=1 with next_version_for(cluster_id),
        # and update the ConditionExpression accordingly.
        "version":                   1,
    })

    # 6B: write linkage record + outbox row in a single
    # transaction. In production this is a TransactWriteItems on
    # DynamoDB; the demo writes to in-memory dicts so the demo's
    # read path works.
    cluster_id = cluster["encounter_cluster_id"]
    event_type_map = {
        "LINKED_HIGH_CONFIDENCE": "claims_clinical_link_resolved",
        "LINKED_MED_CONFIDENCE":  "claims_clinical_link_resolved",
        "EXTERNAL_ENCOUNTER":     "external_encounter_observed",
        "NO_LINK":                "claims_clinical_link_unresolved",
        "REVIEW_PENDING":         "claims_clinical_link_review_pending",
    }
    outbox_row = {
        "outbox_id":    str(uuid.uuid4()),
        "event_type":   event_type_map.get(linkage_decision["link_status"],
                                                "claims_clinical_link_unresolved"),
        "cluster_id":   cluster_id,
        "payload":      linkage_record,
        "emitted_at":   None,
    }
    try:
        # Production: wrap both writes in a TransactWriteItems
        # call so the linkage table and outbox stay consistent on
        # partial failure. The demo uses two separate put_item
        # calls because the in-memory fallback tables do not
        # support transact_write_items. The mechanics:
        #   dynamodb.meta.client.transact_write_items(TransactItems=[
        #       {"Put": {"TableName": LINKAGE_TABLE, "Item": ...,
        #                "ConditionExpression": "..."}},
        #       {"Put": {"TableName": OUTBOX_TABLE, "Item": ...}},
        #   ])
        dynamodb.Table(LINKAGE_TABLE).put_item(
            Item=linkage_record,
            ConditionExpression="attribute_not_exists(encounter_cluster_id)",
        )
        dynamodb.Table(OUTBOX_TABLE).put_item(Item=outbox_row)
    except Exception as exc:
        logger.info("linkage table put skipped (demo mode is fine to ignore)",
                     extra={"error": str(exc)})
    _IN_MEMORY_LINKAGE_TABLE[cluster_id] = linkage_record
    _IN_MEMORY_OUTBOX.append(outbox_row)

    # 6C: maintain the invalidation index. For each constituent
    # claim and the linked encounter, record which cluster
    # depends on it so an invalidation event can find the
    # affected cluster with a single point lookup.
    for claim in cluster["constituent_claims"]:
        _IN_MEMORY_INVALIDATION_INDEX.setdefault(
            ("claim", claim["claim_id"]), []).append(cluster_id)
    if linkage_decision.get("linked_clinical_encounter_id"):
        _IN_MEMORY_INVALIDATION_INDEX.setdefault(
            ("encounter", linkage_decision["linked_clinical_encounter_id"]),
            []).append(cluster_id)
    _IN_MEMORY_INVALIDATION_INDEX.setdefault(
        ("patient", cluster["local_patient_id"]), []).append(cluster_id)

    # 6D: archive curated linkage record to S3 derived zone.
    _archive_to_s3(linkage_record, DERIVED_BUCKET,
                     "encounter-linkages", key_id=cluster_id)

    # 6E: emit the cross-recipe event. Production reads from the
    # outbox in a separate Lambda or DynamoDB Streams consumer to
    # decouple the persistence transaction from the event emit.
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "claims-clinical-linkage",
            "DetailType":   outbox_row["event_type"],
            "EventBusName": EVENTS_BUS_NAME,
            "Detail": json.dumps({
                "encounter_cluster_id":  cluster_id,
                "local_patient_id":      cluster["local_patient_id"],
                "link_status":           linkage_decision["link_status"],
                "linked_clinical_encounter_id":
                    linkage_decision.get("linked_clinical_encounter_id"),
                "resolved_at":           _now_iso(),
            }, default=str),
        }])
    except Exception as exc:
        logger.info("event emit skipped (demo mode is fine to ignore)",
                     extra={"error": str(exc)})

    _emit_metric("LinkageOutcome", 1.0,
                  dimensions={"Status": linkage_decision["link_status"],
                                "EncounterClass": cluster["encounter_class"],
                                "CohortBucket": SYNTHETIC_LOCAL_MPI.get(
                                    cluster["local_patient_id"], {}
                                ).get("cohort_bucket", "unknown")})
    return linkage_record

def invalidate_on_event(event: dict) -> dict:
    """
    Re-evaluate linkages affected by an invalidation event.
    Production triggers a selective Glue job over the affected
    cluster IDs; the demo records what would be re-evaluated.
    """
    source = event.get("source")
    summary = {"source": source, "actions": [], "affected_clusters": []}

    if source == "claim_adjustment" or source == "claim_resubmission":
        affected = _IN_MEMORY_INVALIDATION_INDEX.get(
            ("claim", event["claim_id"]), [])
        summary["affected_clusters"] = list(set(affected))
        summary["actions"].append("re_cluster_and_relink_affected")

    elif source == "claim_denial":
        affected = _IN_MEMORY_INVALIDATION_INDEX.get(
            ("claim", event["claim_id"]), [])
        summary["affected_clusters"] = list(set(affected))
        summary["actions"].append("recompute_paid_totals_and_attribution")

    elif source == "ehr_encounter_amendment":
        affected = _IN_MEMORY_INVALIDATION_INDEX.get(
            ("encounter", event["encounter_id"]), [])
        summary["affected_clusters"] = list(set(affected))
        summary["actions"].append("relink_against_amended_encounter")

    elif source == "patient_identity_merge":
        merged_from = event["merged_from_patient_id"]
        merged_into = event["merged_into_patient_id"]
        affected_from = _IN_MEMORY_INVALIDATION_INDEX.get(
            ("patient", merged_from), [])
        affected_into = _IN_MEMORY_INVALIDATION_INDEX.get(
            ("patient", merged_into), [])
        summary["affected_clusters"] = list(
            set(affected_from) | set(affected_into))
        summary["actions"].append("repoint_clusters_to_surviving_identity")

    elif source == "vocabulary_map_update":
        # Production walks the linkage table for entries whose
        # vocabulary_versions matches the old version. The demo
        # records the action without the walk.
        summary["actions"].append("re_attribute_using_new_vocab_versions")

    elif source == "cross_facility_match_invalidated":
        # Recipe 5.5 invalidation propagates here for clusters
        # whose cross-organizational patient link relied on the
        # invalidated match.
        affected = _IN_MEMORY_INVALIDATION_INDEX.get(
            ("patient", event.get("affected_patient_local_id")), [])
        summary["affected_clusters"] = list(set(affected))
        summary["actions"].append("revalidate_cross_org_patient_link")

    else:
        summary["actions"].append("unknown_invalidation_source")

    # Emit aggregate invalidation event for downstream consumers
    # (longitudinal-record-assembler, quality-measurement engine,
    # HCC processor, care-management workflow) to refresh their
    # derived views.
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "claims-clinical-linkage",
            "DetailType":   "claims_clinical_link_invalidated",
            "EventBusName": EVENTS_BUS_NAME,
            "Detail": json.dumps({
                "invalidation_source": source,
                "invalidation_event_id": event.get("event_id"),
                "affected_cluster_ids": summary["affected_clusters"],
                "invalidated_at":     _now_iso(),
            }, default=str),
        }])
    except Exception as exc:
        logger.info("invalidation event emit skipped (demo mode)",
                     extra={"error": str(exc)})

    _emit_metric("LinkageInvalidations", 1.0,
                  dimensions={"Source": source or "unknown"})
    return summary
```

---

## Full Pipeline

The pipeline assembles the six steps into a single callable function. In production these are separate Glue jobs (for batch) and Lambdas (for event-driven slices) orchestrated by Step Functions; here we run them in-process so the trace is easy to follow.

```python
def run_pipeline(claims_input: list, clinical_input: dict) -> list:
    """
    End-to-end normalize -> patient-link -> cluster -> encounter-
    link -> attribute -> persist pipeline. Returns a list of
    persisted linkage records.
    """
    # Step 1: normalize.
    normalized = normalize_claims_and_clinical(claims_input, clinical_input)

    # Step 2: patient-link each claim.
    for claim in normalized["claims"]:
        link_result = link_patient(claim)
        claim["resolved_local_patient_id"] = link_result.get(
            "resolved_local_patient_id")
        claim["patient_link_method"] = link_result.get("link_method")
        claim["patient_link_confidence"] = link_result.get("link_confidence")

    # Step 3: cluster.
    clusters = cluster_claims_by_encounter(normalized["claims"])

    # Group encounters by patient for cluster-level lookup.
    encounters_by_patient: dict = {}
    for enc in normalized["clinical"]:
        encounters_by_patient.setdefault(
            enc["local_patient_id"], []).append(enc)

    # Steps 4 + 5 + 6: link, attribute, persist for each cluster.
    persisted = []
    for cluster in clusters:
        clinical_for_pt = encounters_by_patient.get(
            cluster["local_patient_id"], [])
        encounter_link_result = link_encounter(cluster, clinical_for_pt)

        # Find the matched clinical encounter object for the
        # attribution step.
        matched_enc = None
        if encounter_link_result.get("linked_clinical_encounter_id"):
            matched_enc = next(
                (e for e in clinical_for_pt
                 if e["encounter_id"] ==
                     encounter_link_result["linked_clinical_encounter_id"]),
                None)

        linked_cluster = {**encounter_link_result, "cluster": cluster}
        attribution = attribute_care_events(linked_cluster, matched_enc)
        record = persist_and_emit(linked_cluster, attribution)
        persisted.append(record)

    return persisted

def run_demo():
    """
    Run the full pipeline against the synthetic claims and
    clinical encounters, then exercise the invalidation pipeline
    on a few sample triggers.
    """
    print("=" * 70)
    print("Claims-to-Clinical Data Linkage Demo")
    print("=" * 70)
    print()
    print("All patients, claims, encounters, and providers in this demo")
    print("are fictional. The mock vocabulary store, cross-reference")
    print("table, and clinical extract return hand-crafted data that")
    print("exercises the full classification range; do not point this")
    print("demo at a live claims warehouse.")
    print()
    print(f"Encounter-link thresholds: HIGH={ENCOUNTER_LINK_HIGH_THRESHOLD}, "
          f"MED={ENCOUNTER_LINK_MED_THRESHOLD}, "
          f"REJECT={ENCOUNTER_LINK_REJECT_THRESHOLD}")
    print(f"Vocabulary versions: {VOCABULARY_VERSIONS['cpt']} CPT, "
          f"{VOCABULARY_VERSIONS['icd10cm']} ICD-10")
    print()

    print("-" * 70)
    print("Phase 1: run end-to-end pipeline over synthetic data")
    print("-" * 70)
    persisted = run_pipeline(SYNTHETIC_CLAIMS, SYNTHETIC_CLINICAL_ENCOUNTERS)
    for record in persisted:
        cid = record["encounter_cluster_id"]
        status = record["link_status"]
        conf = record.get("link_confidence")
        conf_str = (f"{float(conf):.2f}"
                      if isinstance(conf, Decimal) else "n/a")
        n_claims = len(record["constituent_claim_ids"])
        coverage = record.get("attribution_coverage")
        cov_str = (f"{float(coverage):.2f}"
                     if isinstance(coverage, Decimal) else "n/a")
        ehr_id = record.get("linked_clinical_encounter_id") or "(none)"
        print(f"  {cid[:50]:<50}")
        print(f"      status={status:<25} conf={conf_str:<6} "
              f"claims={n_claims} coverage={cov_str}")
        print(f"      ehr_encounter={ehr_id}")
        if record.get("inferred_external_npi"):
            print(f"      external_npi={record['inferred_external_npi']} "
                  f"dx={record.get('external_diagnoses')}")
        if record.get("unattributed_line_items"):
            for u in record["unattributed_line_items"][:2]:
                print(f"      unattributed: line={u['line_item_id']} "
                      f"reason={u['reason']}")

    # Phase 2: exercise the patient-link review path.
    print()
    print("-" * 70)
    print("Phase 2: patient-link review path (claim with no cross-ref)")
    print("-" * 70)
    rogue_claim = {
        "claim_id":   "rogue-claim-2026-99-9999999",
        "payer_id":   "PAYER-XX",
        "member_id":  "MEM-UNKNOWN-9",
        "claim_type": "professional",
        "billing_provider_npi":  "1999999999",
        "service_from_date": "2026-04-20",
        "service_through_date": "2026-04-20",
        "primary_diagnosis_icd10": "Z00.00",
        "secondary_diagnoses_icd10": [],
        "procedures_cpt_hcpcs": ["99213"],
        "claim_status": "paid",
        "charge_amount": 0,
        "paid_amount":   0,
        "line_items": [],
    }
    normalized_rogue = normalize_claims_and_clinical(
        [rogue_claim], {})["claims"][0]
    rogue_link = link_patient(normalized_rogue)
    print(f"  resolved_local_patient_id={rogue_link['resolved_local_patient_id']}")
    print(f"  link_method={rogue_link['link_method']} "
          f"queued={rogue_link.get('queued_for_review', False)}")

    # Phase 3: invalidation triggers.
    print()
    print("-" * 70)
    print("Phase 3: invalidation triggers")
    print("-" * 70)
    inv1 = invalidate_on_event({
        "source":   "claim_adjustment",
        "event_id": "evt-2026-04-30-000001",
        "claim_id": "fac-claim-2026-03-2841073",
    })
    print(f"  source={inv1['source']:<28} "
          f"affected_clusters={len(inv1['affected_clusters'])} "
          f"actions={inv1['actions']}")

    inv2 = invalidate_on_event({
        "source":         "ehr_encounter_amendment",
        "event_id":       "evt-2026-04-30-000002",
        "encounter_id":   "ehr-enc-2026-03-14-12-44-32-pt00874",
    })
    print(f"  source={inv2['source']:<28} "
          f"affected_clusters={len(inv2['affected_clusters'])} "
          f"actions={inv2['actions']}")

    inv3 = invalidate_on_event({
        "source":                "patient_identity_merge",
        "event_id":              "evt-2026-04-30-000003",
        "merged_from_patient_id": "local-patient-internal-99999",
        "merged_into_patient_id": "local-patient-internal-00874",
    })
    print(f"  source={inv3['source']:<28} "
          f"affected_clusters={len(inv3['affected_clusters'])} "
          f"actions={inv3['actions']}")

    inv4 = invalidate_on_event({
        "source":      "vocabulary_map_update",
        "event_id":    "evt-2026-04-30-000004",
        "old_version": "imap-v8",
        "new_version": "imap-v9",
    })
    print(f"  source={inv4['source']:<28} actions={inv4['actions']}")

if __name__ == "__main__":
    run_demo()
```

Expected console output (the SQS / EventBridge / S3 / CloudWatch warnings appear in demo mode because the resources do not exist; they are harmless):

```
======================================================================
Claims-to-Clinical Data Linkage Demo
======================================================================

All patients, claims, encounters, and providers in this demo
are fictional. The mock vocabulary store, cross-reference
table, and clinical extract return hand-crafted data that
exercises the full classification range; do not point this
demo at a live claims warehouse.

Encounter-link thresholds: HIGH=0.85, MED=0.70, REJECT=0.45
Vocabulary versions: 2026.01.01 CPT, 2026.10.01 ICD-10

----------------------------------------------------------------------
Phase 1: run end-to-end pipeline over synthetic data
----------------------------------------------------------------------
  ec-2026-03-14-rnal-00874-inpatient-XXXXXX
      status=LINKED_HIGH_CONFIDENCE    conf=0.91   claims=6 coverage=0.71
      ehr_encounter=ehr-enc-2026-03-14-12-44-32-pt00874
      unattributed: line=li-005 reason=no_matching_clinical_event
      unattributed: line=li-006r reason=no_matching_clinical_event
  ec-2026-04-02-rnal-01927-emergency-XXXXXX
      status=LINKED_HIGH_CONFIDENCE    conf=0.87   claims=2 coverage=0.67
      ehr_encounter=ehr-enc-2026-04-02-08-22-15-pt01927
      unattributed: line=li-103 reason=no_matching_clinical_event
  ec-2026-04-15-rnal-03441-outpatient-XXXXXX
      status=LINKED_HIGH_CONFIDENCE    conf=0.99   claims=1 coverage=1.00
      ehr_encounter=ehr-enc-2026-04-15-09-30-12-pt03441
  ec-2026-02-08-rnal-05000-outpatient-XXXXXX
      status=EXTERNAL_ENCOUNTER        conf=n/a    claims=1 coverage=n/a
      ehr_encounter=(none)
      external_npi=1659473821 dx=['I10', 'I50.20']

----------------------------------------------------------------------
Phase 2: patient-link review path (claim with no cross-ref)
----------------------------------------------------------------------
  resolved_local_patient_id=None
  link_method=deferred_patient_review queued=True

----------------------------------------------------------------------
Phase 3: invalidation triggers
----------------------------------------------------------------------
  source=claim_adjustment             affected_clusters=1 actions=['re_cluster_and_relink_affected']
  source=ehr_encounter_amendment      affected_clusters=1 actions=['relink_against_amended_encounter']
  source=patient_identity_merge       affected_clusters=1 actions=['repoint_clusters_to_surviving_identity']
  source=vocabulary_map_update        actions=['re_attribute_using_new_vocab_versions']
```

(Cluster IDs include a random suffix so the actual `XXXXXX` portion will differ from run to run; the four-cluster shape and the four invalidation outcomes are stable across runs. Maria's outpatient cluster lands at conf=0.99 because every feature aligns: the date is exact, the rendering NPI is the EHR's attending NPI, the encounter class is exact, and the diagnosis-and-procedure concordance is full. The inpatient and ER clusters land lower because the diagnosis sets only partially overlap with the EHR's working diagnoses, which is the realistic claims-to-clinical disagreement the soft-signal scoring is built for.)

Several patterns to notice:

- **Cluster #1 is the heart-failure inpatient stay.** Six claims (three facility, the attending professional, the cardiology resubmission, and the radiology professional) cluster into a single inpatient encounter because the place-of-service `21` on the professional claims maps them into the inpatient class. The original cardiology claim and its resubmission share an `original_claim_id`; the resubmission becomes the canonical version and the original is recorded in `chain_history`. The cluster matches the EHR encounter at high confidence: date alignment is near-perfect, the rendering NPIs include the EHR's attending and consulting providers, the encounter class is exact, and the DRG matches. Diagnosis concordance is partial (the EHR has `I50.23` while the claims have `I50.21`; both are CHF chapter `I50`), which is the normal claims-to-clinical disagreement and is exactly the case the soft-signal scoring is built for. Attribution coverage is below 1.0 because the room-and-board line items have no CPT (revenue codes attribute to cost centers instead), and the evaluation-and-management line items (CPT `99291` and `99253`, mapped to `INT-CRITCARE-INPT` and `INT-CONSULT-INPT`) do not have corresponding entries in the EHR's procedures list. That is realistic: E&M services are usually documented in the encounter's notes and orders rather than as discrete procedure events. The CT and pathology line items attribute cleanly.
- **Cluster #2 is Alex Johnson's ER visit.** Two claims (one facility, one professional) cluster into an emergency-class encounter with a same-day window. The match is high-confidence; the attending NPI matches; the diagnosis chapter aligns. The CT-abdomen-pelvis line item attributes to the ordered CT procedure event in the EHR. The `99284` ER visit code does not have a corresponding EHR procedure event (E&M again), which drops the coverage to 0.67. ER-claims cleanliness is the easy case in this pipeline; inpatient is the hard case.
- **Cluster #3 is the clean outpatient visit for Maria Garcia-Lopez.** One professional claim, one outpatient encounter, exact-day match, attending NPI matches, the `99213` E&M code maps to `INT-OFFICEVISIT-EST` which IS in the EHR's procedures list (because outpatient EHRs commonly do record the office-visit procedure as a discrete event for billing-feed reconciliation). Coverage is 1.0 and confidence is 0.99. There is a second outpatient encounter for the same patient on the same day at a different time (the lab visit), which the candidate-filter would offer as an alternative; the morning-visit encounter wins on attending-NPI alignment because the lab encounter is staffed by a different provider. This demonstrates the candidate-evaluation path; in production with multiple competing candidates per patient per day, the joint-evaluation pattern (mentioned in The Honest Take of the main recipe) is what keeps the assignments from scrambling.
- **Cluster #4 is the external encounter.** Sam Williams's claim from the outside cardiology practice resolves to a known patient through the cross-reference, but no local clinical encounter exists in the analysis window; the cluster is tagged `EXTERNAL_ENCOUNTER` with the rendering NPI and inferred class. This is the high-value output for the longitudinal-record-assembler. The institution learns that the patient had a cardiology visit and an echo at an outside practice, even though the institution never saw the clinical detail directly.
- **Phase 2 demonstrates the patient-link review path.** A claim arrives with a payer-and-member combination that is not in the cross-reference; the matcher routes the claim to the patient-link review queue without attempting encounter-level linking. In production a human reviewer at the eligibility-matching desk resolves the patient identity, the cross-reference table is updated, and the claim re-enters the pipeline.
- **Phase 3 demonstrates the four kinds of invalidation triggers.** A claim adjustment finds the cluster containing the affected claim through the invalidation index. An EHR encounter amendment finds the cluster linked to the amended encounter. A patient identity merge finds clusters under the merged-from and merged-into identities (the demo merges from a non-existent ID, so only the merged-into identity contributes affected clusters). A vocabulary map update applies to all linkages whose `vocabulary_versions` reference the prior version. Each trigger emits a `claims_clinical_link_invalidated` event so downstream consumers (longitudinal-record-assembler, quality-measurement engine, HCC processor, care management) can refresh their derived views.

The cohort-bucket dimension on the `EncounterMatchScore` metric is the substrate for the per-cohort accuracy monitoring discussed in the main recipe; production aggregates on `CohortBucket` and alarms on per-cohort link-rate disparities exceeding the institutional threshold (typical: 0.05 for routine monitoring, 0.07 for HIGH-priority alarm).

---

## Gap to Production

What the demo intentionally skips, and what you would add for a real deployment:

**Replace `MockClaimsParser` with real X12 837/835, FHIR ExplanationOfBenefit, and NCPDP parsers.** The X12 transaction sets are the deployed baseline for institutional billing (837I), professional billing (837P), and remittance advice (835); use a maintained library (`pyx12`, a commercial parser, or your existing revenue-cycle vendor's SDK) rather than rolling your own. FHIR ExplanationOfBenefit is the FHIR-native shape for post-adjudication claims and is the substrate for CMS Patient Access API claim feeds; deserialize with `fhir.resources` or `fhirclient`. Pharmacy claims arrive as NCPDP transactions with their own quirks (NDC packaging, days-supply, refill counts); use a pharmacy-specific parser library or the pharmacy benefit manager's vendor SDK.

**Replace `MockClinicalParser` with real EHR-extract or FHIR ingestion.** Production reads from Epic Clarity / Caboodle, Cerner / Oracle Health, or the equivalent for the high-volume historical extracts; reads FHIR resources (Encounter, Observation, Procedure, MedicationAdministration, Condition, Composition) for the current operational view; and consolidates the two into a unified clinical-encounter representation. Map the EHR-native diagnosis-lifecycle (admitting, working, discharge) into a per-encounter diagnosis set with provenance for each entry. The FHIR Encounter resource has a `period` element with admission/discharge timestamps and a `class` element with the encounter class; map to the linkage's encounter representation directly.

**Replace `MockVocabularyMap` with the production terminology server.** Most institutions either license a commercial vocabulary product (3M, Optum Symedical, IMO) or maintain their own internal map with a clinical-informatics team. The map version drives the line-item attribution; map errors propagate into every analytics output downstream. Connect to the OHDSI Athena vocabulary service, the UMLS Terminology Services, or your institutional terminology platform. Version every lookup result; cache aggressively; refresh on the annual coding-update cycle (ICD-10-CM in October, CPT in January, RxNorm continuously).

**Real DynamoDB schema with the linkage, outbox, cross-reference, and invalidation-index tables.** The `claims-clinical-linkage` table is keyed on `encounter_cluster_id` with a global secondary index on `linked_clinical_encounter_id` for reverse-lookup. The `linkage-outbox` table is keyed on `outbox_id` and is drained by a separate Lambda or DynamoDB Streams consumer. The `mrn-member-id-xref` table is the eligibility-matching pipeline's output (recipe 5.4). The `linkage-invalidation-index` is keyed on `(source_record_type, source_record_id)` and points to affected cluster IDs; it is written-on-link and read-on-invalidation. Provision both with on-demand capacity to handle the bursty pattern of claim-feed deliveries plus the steady volume of EHR-amendment events.

**TransactWriteItems for atomic linkage-and-outbox writes.** The demo writes the linkage record and the outbox row in separate calls; a partial-failure scenario could leave the linkage table updated without the corresponding outbox row, and a downstream consumer would never receive the event. Production wraps both writes in a `TransactWriteItems` call so persistence is atomic. A separate Lambda or DynamoDB Streams consumer reads the outbox and emits the EventBridge event, marking `emitted_at` on success. This pattern keeps the linkage table and the event stream consistent.

**Glue and Spark for the bulk linkage pipeline.** The demo runs in-process for readability; production runs the parse-and-normalize, link-patient, cluster-claims, link-encounter, and attribute-care-events stages as separate Glue jobs over Parquet partitions in S3. Use Spark's join optimization, partition pruning, and columnar processing for the high-volume case. Step Functions orchestrates the daily run; CloudWatch alarms on per-stage error rates and durations surface stuck jobs.

**Step Functions orchestration with retry, timeout, and DLQ.** Three workflows: a daily linkage workflow (parse, normalize, link-patient, cluster, link-encounter, attribute, persist, emit), an invalidation workflow (event-driven from EventBridge into Step Functions, selectively re-evaluating affected clusters), and a vocabulary-refresh workflow (annual ICD-10/CPT/RxNorm refresh triggers a re-attribution of historical linkages). Each Glue job and Lambda has a dedicated DLQ; Step Functions Catch states route terminal failures to the DLQ; CloudWatch alarms on DLQ depth surface stuck workflows.

**Idempotency keys on every write.** The demo uses `encounter_cluster_id` for cluster-level idempotency. Production extends this: parse-and-normalize at `(source_file_key, source_record_offset)`, patient-link at `(claim_id, xref_version)`, cluster at `(local_patient_id, encounter_class, anchor_date)`, encounter-link at `(encounter_cluster_id, matcher_config_version)`, attribute at `(encounter_cluster_id, vocabulary_versions)`, persist at `(encounter_cluster_id, version)`, invalidate at `event_id`. Duplicate-event delivery from EventBridge or duplicate-invocation from Step Functions retries is routine; the pipeline must handle it without producing duplicate writes, duplicate clusters, or inconsistent state.

**Threshold calibration and approval governance.** The encounter-link thresholds, the per-feature weights, and the encounter-class-specific date tolerances are calibrated against an institutional gold set with input from clinical informatics, revenue cycle, and analytics governance. Re-calibration runs annually or on detection of cohort-stratified disparity above the institutional threshold. Each linkage record references the configuration version active at decision time. Promote candidate thresholds through institutional review (analytics governance committee, compliance, clinical informatics, equity-monitoring committee) before going live.

**Cohort-stratified accuracy monitoring with disparity alarms.** The demo emits the `CohortBucket` dimension on the `EncounterMatchScore` metric but does not aggregate or alarm. Production computes per-cohort link rate weekly, per-cohort review-queue rate weekly, per-cohort attribution coverage weekly, per-cohort downstream wrong-encounter-attribution rate monthly. Disparity (best-rate minus worst-rate) thresholds: link-rate > 0.05 = MEDIUM alarm; attribution-coverage > 0.10 = MEDIUM; downstream wrong-attribution > 0.02 = HIGH (analytics integrity). Remediation (per-cohort threshold tuning, vocabulary-map gap analysis, partner-payer quality scorecards) is documented in a cohort-disparity ledger and reviewed quarterly.

**Three-queue review tooling.** The demo routes review-band cases to SQS queues but does not provide a UI. Production builds three workflow tools. The patient-link review tool surfaces candidate patient details with the demographic comparison; the encounter-link review tool surfaces candidate-encounter details with the date, provider, diagnosis, procedure, and DRG comparison; the line-item review tool surfaces unattributed line items with their CPT/HCPCS codes and the available vocabulary mappings (so the reviewer can either add the missing map entry or flag the line for manual handling). Each tool emits the reviewer's decision back into the matcher's training signal for periodic threshold re-calibration.

**Late-arriving claims handling.** The demo runs once over a fixed input; production runs over a sliding window (90 to 180 days typical) and re-evaluates as new claims arrive. Late-arriving claims may need to be added to clusters whose initial linkage was made weeks earlier, or may create new clusters that re-evaluate against encounters from two months ago. The invalidation pipeline catches the re-cluster case; the pipeline's batch cadence handles the new-cluster case. Communicate the back-fill behavior to the analytics consumers explicitly; "the readmission rate for January looked different last week than it does this week" is a feature of the late-arriving-claims dynamic, not a bug.

**Joint-evaluation pattern for multi-encounter windows.** The demo uses the greedy approach: each cluster picks its best candidate independently. When a patient has multiple encounters in the same window with overlapping characteristics (Maria Garcia-Lopez's morning-visit and afternoon-lab pattern, the most common case for outpatient visits), the greedy approach can scramble assignments. Production extends to the joint-evaluation pattern: consider all candidate-cluster-to-candidate-encounter pairs for the patient in the window simultaneously and find the assignment that maximizes the global score. The Hungarian algorithm or a similar bipartite-matching approach is the right substrate. Build the joint version first; retrofitting from greedy is the more painful path.

**External-encounter pipeline with longitudinal-record-assembler integration.** The demo tags external encounters but does not consume them. Production wires the external-encounter event (`external_encounter_observed` from EventBridge) into the longitudinal-record-assembler, which combines them with the local clinical-encounter view to produce a unified per-patient timeline. The assembler also infers a clinical summary (likely chief complaint, likely procedures, likely diagnoses) from the claim's diagnosis-and-procedure codes mapped through the vocabulary store, and presents the inferred summary to the clinician with a confidence flag. Care managers, quality-measurement engines, and HCC risk-adjustment processors all consume the unified view.

**OMOP CDM or alternative target schema.** If the institution's analytics environment is OMOP-based, the linkage outputs feed an OMOP load process that maps the linked encounters to the OMOP `person`, `visit_occurrence`, `condition_occurrence`, `procedure_occurrence`, `drug_exposure`, and `observation` tables. The OMOP load is its own pipeline: vocabulary alignment, terminology mapping, source-to-CDM translation, and OHDSI data-quality validation. Plan the OMOP load alongside the linkage; the two are tightly coupled. Use the OHDSI Athena vocabulary service for the standard-concept mapping; use the OHDSI Data Quality Dashboard tool for ongoing quality validation.

**FHIR-native linkage with HealthLake.** For institutions standardized on FHIR resources, the clinical side of the linkage runs against FHIR `Encounter`, `Observation`, `Procedure`, `MedicationAdministration`, and `Condition` resources stored in Amazon HealthLake. The claims side runs against FHIR `ExplanationOfBenefit` and `Claim` resources. The linkage emits a FHIR-native cross-reference (a `Provenance` resource or an extension on the `Encounter` resource) that downstream FHIR-aware applications consume.

**Initial backfill and onboarding.** Standing up the linkage pipeline involves a one-time backfill: every historical claim and every historical encounter in the analysis window gets linked. This is a Glue/Spark job at scale, with cohort-stratified accuracy monitoring during the backfill (the backfill is a one-time opportunity to surface cohort issues at scale), suppression of routine event emission during the backfill (downstream consumers refresh from a single `claims_clinical_backfill_complete` marker rather than millions of individual events), and governance approval at each stage. Plan onboarding as a project with its own timeline; depending on history depth, several weeks to several months is normal.

**Coding lifecycle and CDI integration.** The institution's coding department produces the final coded claims, often after a CDI (clinical documentation improvement) review cycle that may take days to weeks after discharge. The linkage runs against the post-CDI claims; encounters whose claims are still in coding limbo are linked later when the coded claims arrive. Coordinate the linkage cadence with the coding cycle; expose a CDI-pending tag on encounters whose claim has not yet flowed through coding so analytics consumers know the cost figures are provisional.

**Patient-access reports.** Under HIPAA and the 21st Century Cures Act, patients have a right to see who has accessed their health data. The linkage table holds claims data the institution received from payers; the patient's right to know what data the institution holds about them includes that data. Build the patient-access-report generator from the linkage table and the audit log so the institution can respond to patient requests. Build this as a first-class deliverable, not an afterthought.

**Trading-partner agreements and data-use governance.** Each payer-feed contract has its own data-use clauses: what the institution may use the data for, how long the data may be retained, who else may see it, what the redistribution rights are, what the audit obligations are. These are negotiated by legal and compliance, not engineered around. Treat the trading-partner agreements as architectural input: if a payer's data is contractually limited to operations and quality use cases, the linkage outputs derived from that payer's data have to be tagged with that constraint and the access controls have to enforce it.

**KMS-encrypted everything.** Customer-managed keys for the S3 buckets (raw-claims, raw-clinical, curated, derived, audit-archive), the DynamoDB tables (linkage, outbox, cross-reference, invalidation-index), the SQS queues, the Lambda log groups, the Glue temp storage, and the Secrets Manager partner-credential entries. Per-service KMS configuration is omitted for readability but is non-negotiable for the institution's standard PHI-handling posture.

**VPC + VPC endpoints.** Production runs Glue jobs and Lambdas in VPC with VPC endpoints for S3 (gateway), DynamoDB (gateway), KMS, Secrets Manager, CloudWatch Logs, EventBridge, SQS, Step Functions, Glue, Athena, and STS. NAT Gateway only for the partner-payer egress; restrict egress with security groups and an outbound proxy with an allow-list of partner endpoints. PrivateLink where the partner offers it.

**CloudTrail data events on the linkage table, the cross-reference table, and the audit S3 buckets.** Every read of the linkage table is auditable activity; the data-events feature is not enabled by default and is the right level of granularity for the claims-to-clinical substrate. Audit logs in a dedicated S3 bucket with Object Lock in Compliance mode for immutability; lifecycle policy transitioning to S3 Glacier Deep Archive after 90 days; retention floor enforced at the bucket-policy and Object-Lock-configuration level. Forward CloudTrail data events to a dedicated audit AWS account in the institution's organization.

**Lake Formation column-level and row-level access control.** Different audiences need different views of the linkage outputs. Quality-measurement teams need the encounter-linked aggregate; risk-adjustment teams need the diagnosis-concordance detail; outcomes-research teams need the de-identified longitudinal record. Lake Formation grants enforce the row-and-column distinctions; Athena query paths use the same grants. Build the access matrix with input from compliance and clinical leadership.

**Compliance and operational ownership.** Claims-to-clinical linkage sits at the intersection of revenue cycle, clinical informatics, analytics, compliance, and IT. Establish clear operational ownership: who tunes the thresholds, who reviews the cohort-disparity reports, who handles the payer-feed quality issues, who owns the vocabulary-map updates, who responds to invalidation backlogs, who owns the relationship with each payer. The pipeline works only when the operational ownership is clear and funded.

The pipeline is the easy part. The operational discipline (trading-partner agreements as architectural input, vocabulary-map sourcing and maintenance, threshold calibration and approval governance, cohort-stratified equity monitoring, three-queue review tooling and reviewer auditing, longitudinal-record-assembler integration, OMOP CDM or alternative-target-schema integration, late-arriving-claims handling discipline, initial-backfill discipline, ongoing operational ownership) is what makes a claims-to-clinical linkage system produce accurate, fresh, usable linkages year after year. Build for that.

---

*← [Recipe 5.6: Claims-to-Clinical Data Linkage](chapter05.06-claims-to-clinical-data-linkage)*
