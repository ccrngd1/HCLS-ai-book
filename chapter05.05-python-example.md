# Recipe 5.5: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 5.5. It shows one way you could translate the cross-facility patient matching pattern into working Python using a small `MockPartnerOrg` and `MockHIEIntermediary` that stand in for the real partner organizations and HIE intermediaries you would query (Carequality, CommonWell, your regional HIE, a TEFCA QHIN), plus `MockConsentRegistry` and `MockSensitivityFilter` standing in for the consent-and-sensitivity layers, Amazon DynamoDB for the cross-org MPI table and the audit-log table, an in-process dict standing in for an Amazon ElastiCache Redis cluster (the blocking-index cache), Amazon SQS for the realtime-query, linkage-submission, and deferred-review queues, Amazon S3 for the raw query-and-response archive, Amazon EventBridge for the cross_facility_query_resolved and cross_facility_match_invalidated events, and Amazon CloudWatch for operational metrics. It is not production-ready. There is no real FHIR `$match` operation handler (the demo represents queries and responses as Python dicts that mirror the FHIR Patient resource shape), no real IHE PIX/PDQ v2 parser, no real mTLS validator on the inbound endpoint, no Step Functions orchestration, no Glue/Spark batch reconciliation, no real consent-registry connector, no longitudinal-record-assembler, no patient-access-report generator, no review-queue UI, and no IAM, KMS, VPC, WAF, or CloudTrail wiring. Think of it as the sketchpad version: useful for understanding the shape of a cross-facility matching pipeline that respects the query-vs-linkage distinction, the conservative-threshold-with-graded-confidence routing, the consent-then-sensitivity filter chain, the fail-closed posture on consent-registry unavailability, and the audit-everything-twice posture this category demands. It is not something you would point at a live HIE on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the six core pseudocode steps from the main recipe: ingest a cross-facility query (or a linkage submission) from any source (inbound HIE query, outbound local clinician request, partner-org direct query, linkage submission via CCD or FHIR Bundle); normalize the demographic search criteria with payer-and-org-aware rules and compute the multi-strategy blocking keys; evaluate against the local cross-org MPI using the same probabilistic-record-linkage scorer pattern from recipe 5.1, with thresholds calibrated more conservatively than for internal matching because cost of false positives is higher; apply the consent layer (fail-closed if the registry is unavailable) and the sensitivity-filter policy; persist the audit record and emit the `cross_facility_query_resolved` event; and react to invalidation triggers (consent revocation, local MPI merges, demographic changes from recipes 5.1, 5.3, 5.7, partner-org offboarding) by clearing caches, updating the cross-org MPI, and emitting `cross_facility_match_invalidated` events. The synthetic patients, organizations, and HIE responses in the demo are fictional; the names, MRNs, addresses, and DOBs are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also install a FHIR client library such as `fhir.resources` or `fhirclient` for the FHIR Patient `$match` operation, an HL7 v2 parser such as `hl7` for the legacy PIX/PDQ path, and an OAuth/OIDC validator (such as `python-jose` or `authlib`) for the inbound-query mTLS-or-signed-JWT verification. The demo replaces all of these with small mocks so the focus stays on the matching, consent, and audit pipeline rather than on protocol parsing.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchGetItem` on the `cross-org-mpi` table and the `audit-log` table (and on the secondary index that supports lookup-by-cross-org-id)
- `s3:PutObject` on the raw-queries-and-responses bucket and the match-curated bucket (for both the inbound query payloads and the parsed match outcomes)
- `sqs:SendMessage` and `sqs:ReceiveMessage` on the realtime-query-queue, linkage-submission-queue, and deferred-review-queue
- `events:PutEvents` on the cross-facility-events bus
- `cloudwatch:PutMetricData` for the match-outcome, per-partner-error, deferred-review-depth, and cohort-disparity metrics
- `secretsmanager:GetSecretValue` on the HIE-credentials and partner-org-credentials secrets (production only; the mocks do not need them)

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The audit-log writer Lambda in particular gets append-only IAM (no `dynamodb:DeleteItem`, no `dynamodb:UpdateItem` on existing items) enforced through condition keys plus DynamoDB resource-based policy.

A few things worth knowing upfront:

- **Cross-facility queries and responses are PHI.** The inbound query contains a patient's full demographics. The outbound response contains the patient's match status plus (when consent permits) a slice of their clinical record. Both are PHI; both are sensitive in different ways. Encrypt at rest with a customer-managed KMS key, encrypt in transit with TLS 1.2 or higher (mutual TLS where the partner requires it), and apply tighter access controls than you would for the internal matcher. Never log raw demographics or clinical content; log structural metadata only (query_id, requesting_org, match_status, confidence band, release decision).
- **The audit log is the legal record.** Every query, every match decision, every consent check, every release, every withhold. The patient has a right to see who queried about them and what was released. The audit log is the only artifact that answers that question, and it must be append-only, immutably retained, and replicated to a separate audit AWS account. The demo shows the append discipline; production extends with TransactWriteItems, signature chaining, and Object Lock.
- **DynamoDB rejects Python `float`.** Every confidence score, score-breakdown component, and numeric metadata field passes through `Decimal` on its way in and on its way out. Same gotcha as recipes 5.1 / 5.2 / 5.3 / 5.4; the same `_to_decimal` helper handles it.
- **Consent checks are fail-closed.** If the consent registry is unavailable, the matcher MUST NOT release data. The demo implements this; production extends with high-availability for the registry itself, region-redundant deployment, and an audited grace-period exception for treatment purpose-of-use during demonstrable registry outages (with post-hoc consent verification).
- **Cross-facility match thresholds are calibrated more conservatively than internal-matcher thresholds.** A wrong cross-facility match produces a misfiled clinical document or a wrong-patient overlay in the consuming organization's chart, with clinical-safety consequences. The illustrative thresholds below favor false negatives over false positives; calibrate yours against your own gold set with input from the institution's clinical-safety committee.
- **The example collapses Step Functions, multiple Lambdas, the SQS-driven worker pattern, and the inbound-and-outbound query orchestration into a single Python file for readability.** In production the normalize, evaluate, consent-and-sensitivity, release-and-audit, outbound-submit, aggregate-partner-responses, and invalidate-on-event stages are separate Lambdas orchestrated by Step Functions, each with their own error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the conservative match thresholds, the per-feature weights, the consent and sensitivity policy versions, and the routing knobs are what you would change between environments.

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
# CloudWatch Logs Insights. Cross-facility query data is PHI; log
# structural metadata only (query_id, requesting_org, match_status,
# confidence band, release decision), never raw demographics or
# clinical content.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from DynamoDB, EventBridge,
# CloudWatch, SQS, and the (real) consent registry. Real-time
# inbound queries from clinicians have a tight latency budget;
# transient throttling from any one service should not fail the
# whole query. Step Functions Catch distinguishes retriable
# infrastructure failures from terminal logic failures and routes
# terminal failures to a DLQ for human investigation.
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
CROSS_ORG_MPI_TABLE      = "cross-org-mpi"
AUDIT_LOG_TABLE          = "audit-log"
RAW_BUCKET               = "my-cross-facility-raw"
CURATED_BUCKET           = "my-cross-facility-curated"
REALTIME_QUEUE_URL       = "https://sqs.us-east-1.amazonaws.com/000000000000/realtime-query-queue"
LINKAGE_QUEUE_URL        = "https://sqs.us-east-1.amazonaws.com/000000000000/linkage-submission-queue"
REVIEW_QUEUE_URL         = "https://sqs.us-east-1.amazonaws.com/000000000000/deferred-review-queue"
EVENTS_BUS_NAME          = "cross-facility-events"
CLOUDWATCH_NAMESPACE     = "CrossFacility/Matching"

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("CROSS_ORG_MPI_TABLE", CROSS_ORG_MPI_TABLE),
    ("AUDIT_LOG_TABLE",     AUDIT_LOG_TABLE),
    ("RAW_BUCKET",          RAW_BUCKET),
    ("CURATED_BUCKET",      CURATED_BUCKET),
    ("REALTIME_QUEUE_URL",  REALTIME_QUEUE_URL),
    ("LINKAGE_QUEUE_URL",   LINKAGE_QUEUE_URL),
    ("REVIEW_QUEUE_URL",    REVIEW_QUEUE_URL),
    ("EVENTS_BUS_NAME",     EVENTS_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE", CLOUDWATCH_NAMESPACE),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every match outcome and every audit record stores the version of
# the matcher config and the sensitivity-filter policy that
# produced it. This is how a future audit reconstructs what
# thresholds and what filter rules were active when a particular
# query was decided.
MATCHER_CONFIG_VERSION   = "xfac-matcher-v1.0"
SENSITIVITY_POLICY_VERSION = "xfac-sens-v1.0"
THRESHOLDS_VERSION       = "xfac-thresholds-v1.0"

# --- Conservative confidence thresholds ---
# Cross-facility match thresholds are calibrated more
# conservatively than internal matching because the cost of
# false positives is higher (a misfiled cross-org document or a
# wrong-patient overlay in the consuming organization's chart is
# a clinical-safety event). The numbers below are illustrative
# defaults; do not adopt them without calibration against your
# own gold set with input from the institution's clinical-safety
# committee.
AUTO_ACCEPT_HIGH_THRESHOLD = Decimal("0.92")  # high-confidence match
AUTO_ACCEPT_MED_THRESHOLD  = Decimal("0.80")  # probable match, downgraded scope
AUTO_REJECT_THRESHOLD      = Decimal("0.55")  # below this, no match
# Anything between AUTO_REJECT and AUTO_ACCEPT_MED routes to the
# deferred-review queue (asynchronously; the original query gets
# a NO_MATCH response in real time).

# --- Per-feature score weights for the cross-facility matcher ---
# DOB and last_name dominate because they are the two most stable
# demographics across organizations. Cross-org identifier (when
# present from a prior match) is the strongest deterministic
# signal. Address and SSN are tie-breakers.
SCORE_WEIGHTS = {
    "first_name":         Decimal("0.12"),
    "last_name":          Decimal("0.20"),
    "dob":                Decimal("0.25"),
    "sex":                Decimal("0.05"),
    "address":            Decimal("0.10"),
    "phone":              Decimal("0.05"),
    "ssn":                Decimal("0.08"),
    "prior_cross_org_id": Decimal("0.15"),
}

# --- Latency budgets ---
# Real-time treatment queries get a tight budget; linkage
# submissions can take longer.
REALTIME_LATENCY_BUDGET_MS = 3000
LINKAGE_LATENCY_BUDGET_MS  = 30000

# --- Blocking ---
# Skip blocks above this size to protect against malformed
# queries that would explode the comparison count.
MAX_CANDIDATES_PER_QUERY = 100

# --- Med-confidence release scope ---
# When the match is medium-confidence, release a narrower set of
# data than the high-confidence release would. Same rationale as
# the conservative thresholds: limit the blast radius of a
# possibly-wrong match.
HIGH_VALUE_DATA_AT_MED_CONFIDENCE = {
    "allergies",
    "active_medications",
    "problem_list_active",
    "advance_directives",
}

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
    """Recursive serialization helper. Same pattern as recipes 5.1 - 5.4."""
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

## Mock Consent Registry, Sensitivity Filter, Partner Orgs, and MPI Registry

Production calls a real consent-registry system-of-record, a real sensitivity-filter policy engine, and real partner-organization or HIE-intermediary endpoints. The demo includes small mocks that exercise the downstream pipeline (matching, consent and sensitivity application, persistence, audit, events) without requiring those external dependencies. The point of the mocks is the same as in recipe 5.4: see the shape of the orchestration without standing up the partner ecosystem.

```python
# --- In-memory cross-org MPI ---
# Keyed on local_patient_id. Holds the demographic snapshot used
# at match time, the cross-org identifier (if previously
# resolved), the prior_last_names list (from recipe 5.7), and
# the prior_addresses list (from recipe 5.3).
SYNTHETIC_CROSS_ORG_MPI = {
    "local-patient-internal-00874": {
        "local_patient_id":   "local-patient-internal-00874",
        "cross_org_id":       "xorg-7a3b9c2e-1111",
        "first_name":         "JANE",
        "last_name":          "DOE",
        "prior_last_names":   [],
        "dob":                "19800615",
        "administrative_sex": "F",
        "standardized_address": {
            "line1": "1421 ELM ST APT 3B", "city": "ANYTOWN",
            "state": "ST", "zip": "12345",
        },
        "prior_addresses": [
            {"line1": "200 OAK ST", "city": "ANYTOWN",
             "state": "ST", "zip": "12345"},
        ],
        "phone_history":      ["+15551234567"],
        "ssn_full":           "123-45-6789",
        "ssn_last4":          "6789",
        "cohort_bucket":      "A",
    },
    # Same patient as 00874 with a maiden name; demonstrates
    # recipe 5.7's prior-last-names path catching a name change.
    "local-patient-internal-02100": {
        "local_patient_id":   "local-patient-internal-02100",
        "cross_org_id":       "xorg-7a3b9c2e-2222",
        "first_name":         "MARIA",
        "last_name":          "GARCIA-LOPEZ",
        "prior_last_names":   ["GARCIA"],
        "dob":                "19720314",
        "administrative_sex": "F",
        "standardized_address": {
            "line1": "1421 ELM ST APT 3B", "city": "ANYTOWN",
            "state": "ST", "zip": "12345",
        },
        "prior_addresses": [],
        "phone_history":      ["+15559998888"],
        "ssn_full":           "987-65-4321",
        "ssn_last4":          "4321",
        "cohort_bucket":      "C",
    },
    # An older record that demonstrates the sensitivity-filter
    # path for a patient with a flagged behavioral-health
    # category.
    "local-patient-internal-03050": {
        "local_patient_id":   "local-patient-internal-03050",
        "cross_org_id":       "xorg-7a3b9c2e-3333",
        "first_name":         "ALEX",
        "last_name":          "JOHNSON",
        "prior_last_names":   [],
        "dob":                "19951102",
        "administrative_sex": "M",
        "standardized_address": {
            "line1": "55 OAK AVE", "city": "ANYTOWN",
            "state": "ST", "zip": "12345",
        },
        "prior_addresses": [],
        "phone_history":      ["+15557776666"],
        "ssn_full":           None,
        "ssn_last4":          None,
        "cohort_bucket":      "B",
    },
}

# --- In-memory blocking index ---
# Built lazily from SYNTHETIC_CROSS_ORG_MPI on first read. Maps
# (block_type, block_value) -> list of local_patient_ids. In
# production this lives in ElastiCache for sub-millisecond
# lookup, with DynamoDB as the system-of-record.
_BLOCKING_INDEX: dict = {}

def _build_blocking_index_if_needed():
    if _BLOCKING_INDEX:
        return
    for pid, mpi_record in SYNTHETIC_CROSS_ORG_MPI.items():
        # Block 1: last-name-soundex + year-of-birth.
        # Soundex stub: take first char + remove vowels, first 4.
        ln = (mpi_record.get("last_name") or "").upper()
        if ln:
            ln_soundex = (ln[0] + re.sub(r"[AEIOUYHW]", "", ln[1:]))[:4]
            yob = (mpi_record.get("dob") or "")[:4]
            if yob:
                _BLOCKING_INDEX.setdefault(
                    ("ln_soundex_yob", f"{ln_soundex}#{yob}"), []
                ).append(pid)
        # Block 2: first-letter-of-last-name + first-letter-of-first-name.
        fn = (mpi_record.get("first_name") or "").upper()
        if fn and ln:
            _BLOCKING_INDEX.setdefault(
                ("ln_initial_fn_initial", f"{ln[0]}#{fn[0]}"), []
            ).append(pid)
        # Block 3: ZIP3 + DOB-month-day. Catches name-change patients.
        addr = mpi_record.get("standardized_address") or {}
        zip5 = (addr.get("zip") or "")[:5]
        zip3 = zip5[:3] if zip5 else ""
        dob_md = (mpi_record.get("dob") or "")[4:8]
        if zip3 and dob_md:
            _BLOCKING_INDEX.setdefault(
                ("zip3_dob_md", f"{zip3}#{dob_md}"), []
            ).append(pid)
        # Block 4: prior cross-org identifier (deterministic).
        if mpi_record.get("cross_org_id"):
            _BLOCKING_INDEX.setdefault(
                ("prior_xorg_id", mpi_record["cross_org_id"]), []
            ).append(pid)
        # Block 5: also block on prior_last_names so a query with
        # the maiden name finds the post-marriage record.
        for prior_ln in mpi_record.get("prior_last_names", []):
            prior_ln = prior_ln.upper()
            prior_ln_soundex = (
                prior_ln[0] + re.sub(r"[AEIOUYHW]", "", prior_ln[1:])
            )[:4]
            yob = (mpi_record.get("dob") or "")[:4]
            if prior_ln_soundex and yob:
                _BLOCKING_INDEX.setdefault(
                    ("ln_soundex_yob", f"{prior_ln_soundex}#{yob}"), []
                ).append(pid)

# --- Mock consent registry ---
# Keyed on (patient_local_id, requesting_org_id, purpose_of_use).
# Production reads from a system-of-record (HIE-provided, vendor,
# or institutional) over a real network call; the mock returns
# canned responses that exercise the full range of consent
# states (permitted, expired, revoked, partial-by-data-category,
# discoverability-blocked).
class MockConsentRegistry:
    """Stand-in for the consent-registry system-of-record."""

    def __init__(self):
        # Pre-populated consent state for the synthetic patients.
        # Production has nothing like this; the registry is its
        # own subsystem with its own data model.
        self._consents = {
            # Jane Doe: full treatment consent for any requesting
            # org, expires in 2027.
            ("local-patient-internal-00874", "*", "treatment"): {
                "is_exchange_permitted": True,
                "permitted_data_categories": [
                    "allergies", "medications", "problem_list",
                    "advance_directives", "lab_results_recent",
                    "imaging_reports_recent",
                ],
                "discoverability_permitted": True,
                "expires_at": "2027-01-15T00:00:00Z",
            },
            # Maria Garcia-Lopez: treatment consent permitted,
            # but reproductive-health information is
            # patient-flagged sensitive (post-Dobbs jurisdiction
            # constraint stand-in).
            ("local-patient-internal-02100", "*", "treatment"): {
                "is_exchange_permitted": True,
                "permitted_data_categories": [
                    "allergies", "medications", "problem_list",
                    "advance_directives", "lab_results_recent",
                ],
                "discoverability_permitted": True,
                "expires_at": "2027-06-30T00:00:00Z",
                "patient_flagged_sensitive_categories": [
                    "reproductive_health",
                ],
            },
            # Alex Johnson: treatment consent permitted, but the
            # patient has flagged behavioral-health records as
            # not-shareable. Combined with the institutional
            # 42 CFR Part 2 policy this gets filtered.
            ("local-patient-internal-03050", "*", "treatment"): {
                "is_exchange_permitted": True,
                "permitted_data_categories": [
                    "allergies", "medications", "problem_list",
                    "lab_results_recent",
                ],
                "discoverability_permitted": True,
                "expires_at": "2026-12-31T00:00:00Z",
                "patient_flagged_sensitive_categories": [
                    "behavioral_health",
                ],
            },
        }
        # A flag we toggle in the demo to simulate a registry
        # outage so we can show the fail-closed path.
        self.simulate_outage = False

    def get(self, patient_local_id: str, requesting_org: str,
             purpose_of_use: str, requested_data_categories: list,
             timeout_ms: int = 500) -> dict:
        if self.simulate_outage:
            raise ConsentRegistryUnavailable("simulated outage")

        # Look for an exact-match consent first; fall back to
        # the wildcard-org consent if no exact match.
        consent = (self._consents.get((patient_local_id, requesting_org,
                                          purpose_of_use))
                    or self._consents.get((patient_local_id, "*",
                                              purpose_of_use)))

        if consent is None:
            # No record means no consent in opt-in jurisdictions;
            # default to not-permitted with discoverability-also-
            # not-permitted, which is the safe posture.
            return {
                "is_exchange_permitted": False,
                "permitted_data_categories": [],
                "discoverability_permitted": False,
                "summary": "no_consent_on_file",
            }

        # Check expiration.
        expires_at = consent.get("expires_at")
        if expires_at:
            expires_dt = datetime.fromisoformat(
                expires_at.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > expires_dt:
                return {
                    "is_exchange_permitted": False,
                    "permitted_data_categories": [],
                    "discoverability_permitted":
                        consent.get("discoverability_permitted", False),
                    "summary": "consent_expired",
                    "expires_at": expires_at,
                }

        # Return a structured response. The summary field is what
        # the downstream audit log captures; raw permitted lists
        # are not echoed in the audit log, only the summary.
        return {
            "is_exchange_permitted": consent["is_exchange_permitted"],
            "permitted_data_categories":
                consent.get("permitted_data_categories", []),
            "discoverability_permitted":
                consent.get("discoverability_permitted", False),
            "expires_at": expires_at,
            "patient_flagged_sensitive_categories":
                consent.get("patient_flagged_sensitive_categories", []),
            "summary": "permitted_full"
                          if consent["is_exchange_permitted"]
                          else "not_permitted",
        }

class ConsentRegistryUnavailable(Exception):
    """Raised when the consent registry cannot be reached. Triggers fail-closed."""
    pass

# --- Mock sensitivity filter ---
# Production reads a versioned policy table and applies category-
# specific sharing rules. The mock encodes a small set of rules
# that exercise the major paths.
class MockSensitivityFilter:
    """Stand-in for the institutional sensitivity-filter policy engine."""

    POLICY_VERSION = SENSITIVITY_POLICY_VERSION

    # State-and-federal sharing rules that override patient
    # consent. These are policy-driven, not algorithmic.
    INSTITUTIONAL_RESTRICTED_CATEGORIES = {
        "behavioral_health_notes": "state_specific_sensitivity_rule",
        "substance_use_disorder_records": "42_cfr_part_2",
    }

    def filter(self, patient_id: str, eligible_data_categories: list,
                 purpose_of_use: str, requesting_principal_org: str,
                 patient_flagged_sensitive_categories: list = None) -> dict:
        patient_flagged = patient_flagged_sensitive_categories or []
        released = []
        filtered = []

        for cat in eligible_data_categories:
            # Institutional restriction (policy-level).
            if cat in self.INSTITUTIONAL_RESTRICTED_CATEGORIES:
                filtered.append({
                    "category": cat,
                    "reason": self.INSTITUTIONAL_RESTRICTED_CATEGORIES[cat],
                })
                continue
            # Patient-flagged sensitivity (consent-level).
            if any(cat.startswith(p) for p in patient_flagged):
                filtered.append({
                    "category": cat,
                    "reason": "patient_flagged_sensitive_category",
                })
                continue
            released.append(cat)

        notes = []
        if any(f["reason"] == "42_cfr_part_2" for f in filtered):
            # 42 CFR Part 2 requires a re-disclosure prohibition
            # notice when SUD records are released; we are not
            # releasing SUD records here, but the audit log
            # records that the filter considered them.
            notes.append("42_cfr_part_2_filter_applied")

        return {
            "released_data_categories": released,
            "filtered_data_categories": filtered,
            "additional_notes": notes,
            "policy_version": self.POLICY_VERSION,
        }

    @classmethod
    def current_version(cls):
        return cls.POLICY_VERSION

# --- Mock partner organization (for outbound queries) ---
class MockPartnerOrg:
    """
    Stand-in for a participating organization that the institution
    queries through an HIE intermediary or directly. Returns a
    plausible Patient resource list with a search-score-equivalent
    confidence value.
    """

    SOFTWARE_VERSION = "mock-partner-fhir-v1.0"

    def __init__(self, org_id: str):
        self.org_id = org_id
        # Each partner has its own demographic snapshot that may
        # differ from ours in subtle ways. Production has no such
        # snapshot; the partner's matcher runs against their own
        # MPI and we never see the underlying data.
        self._roll = {
            # Cross-town academic medical center: has Jane Doe
            # under her current name.
            ("partner-org-academic-mc", "PARTNER-AMC-001"): {
                "first_name": "JANE", "last_name": "DOE",
                "dob": "19800615", "sex": "F",
                "address": {"line1": "1421 ELM ST APT 3B",
                              "zip": "12345"},
                "ssn_last4": "6789",
                "partner_search_score": 0.96,
            },
            # Urgent-care chain: has Maria as Garcia-Lopez (married
            # name); we look her up by Garcia (maiden name) so the
            # match-quality matters.
            ("partner-org-urgent-care", "PARTNER-UC-887"): {
                "first_name": "MARIA", "last_name": "GARCIA-LOPEZ",
                "dob": "19720314", "sex": "F",
                "address": {"line1": "1421 ELM ST APT 3B",
                              "zip": "12345"},
                "ssn_last4": "4321",
                "partner_search_score": 0.88,
            },
        }

    def fhir_patient_match(self, search_payload: dict,
                              timeout_ms: int = 5000) -> dict:
        """
        Mimic a FHIR Patient $match call to this partner. Returns
        a Bundle-shaped dict with candidate Patient resources and
        search scores.
        """
        candidates = []
        q_first = (search_payload.get("first_name") or "").upper()
        q_last = (search_payload.get("last_name") or "").upper()
        q_dob = search_payload.get("dob") or ""
        for (org_id, member_id), member in self._roll.items():
            if org_id != self.org_id:
                continue
            # Loose match: same DOB and at least last-name initial.
            if (member["dob"] == q_dob
                    and member["last_name"][:1] == q_last[:1]):
                candidates.append({
                    "partner_member_id":   member_id,
                    "first_name":          member["first_name"],
                    "last_name":           member["last_name"],
                    "dob":                 member["dob"],
                    "sex":                 member["sex"],
                    "address":             member["address"],
                    "ssn_last4":           member["ssn_last4"],
                    "partner_search_score": member["partner_search_score"],
                })

        return {
            "responding_org": self.org_id,
            "match_count":    len(candidates),
            "candidates":     candidates,
            "software_version": self.SOFTWARE_VERSION,
        }

# Module-level singletons. In production replace with real
# clients constructed from credentials in Secrets Manager.
consent_registry = MockConsentRegistry()
sensitivity_filter = MockSensitivityFilter()
partner_orgs = {
    "partner-org-academic-mc": MockPartnerOrg("partner-org-academic-mc"),
    "partner-org-urgent-care": MockPartnerOrg("partner-org-urgent-care"),
}

# --- In-memory ElastiCache stand-in for blocking-index lookups ---
# The blocking index above is the pre-warmed lookup table.
# Production uses ElastiCache with TLS in transit and KMS at rest.

# --- In-memory audit-log registry stand-in for DynamoDB ---
# Append-only. Each entry keyed on (query_id, event_seq).
_IN_MEMORY_AUDIT_LOG: dict = {}

def _archive_raw_to_s3(payload: dict, partition: str,
                         query_id: str = None) -> None:
    """Best-effort archive to S3. Failures logged and skipped (the demo prints what it would write)."""
    today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    qid = query_id or payload.get("query_id") or uuid.uuid4().hex
    key = f"{partition}/{today}/{qid}.json"
    body = json.dumps(payload, default=str).encode("utf-8")
    try:
        s3_client.put_object(
            Bucket=(RAW_BUCKET if partition.startswith("raw")
                       else CURATED_BUCKET),
            Key=key,
            Body=body,
            ServerSideEncryption="aws:kms",
        )
    except Exception as exc:
        logger.info("archive write skipped (demo mode is fine to ignore)",
                     extra={"key": key, "error": str(exc)})
```

---

## Step 1: Ingest the Cross-Facility Query or Linkage Submission

*The pseudocode calls this `ingest_query(inbound)`. Inbound queries arrive from HIE intermediaries, partner organizations, or the local clinician's workflow. Linkage submissions arrive as continuity-of-care documents or FHIR Bundles for ingestion into the cross-org MPI. The ingestion layer authenticates the requesting principal (mTLS or signed JWT in production), verifies the asserted purpose-of-use against the participation agreement, and produces a normalized query record that the downstream pipeline consumes. Skip the authentication and you have an enumeration-attack surface; skip the purpose-of-use check and you release data for purposes the participation agreement does not permit.*

```python
def _verify_requester(inbound: dict) -> dict:
    """
    Stand-in for mTLS / signed-JWT verification. Production
    validates a client certificate against a CA roster, or
    verifies a JWT signature against the HIE's JWKS, or both.
    The mock just trusts the asserted requester identity for
    demo purposes; production must not.
    """
    requesting_org = inbound.get("requesting_org")
    if not requesting_org:
        return None
    return {
        "org_id":         requesting_org,
        "auth_method":    "mock_trusted_assertion",
        "credential_id":  inbound.get("credential_id", "mock-cred-01"),
    }

def _is_purpose_permitted(principal: dict, purpose_of_use: str) -> bool:
    """
    Verify the asserted purpose-of-use against the participation
    agreement. Each requesting organization has a list of
    purposes it has been authorized for. The mock allows
    treatment for everyone and rejects research unless the
    requesting org is the academic medical center.
    """
    if purpose_of_use == "treatment":
        return True
    if purpose_of_use == "payment":
        return True
    if purpose_of_use == "operations":
        return True
    if purpose_of_use == "public_health":
        return principal["org_id"].startswith("public-health-agency-")
    if purpose_of_use == "research":
        return principal["org_id"] == "partner-org-academic-mc"
    return False

def ingest_query(inbound: dict) -> dict:
    """
    Capture the inbound query (or linkage submission) into a
    consistent query record and route to the appropriate SQS
    queue.
    """
    is_linkage = inbound.get("is_linkage_submission", False)

    # Validate the requester unless this is an inbound linkage
    # submission from an authenticated upstream pipeline.
    principal = None
    if not is_linkage:
        principal = _verify_requester(inbound)
        if principal is None:
            _emit_metric("UnauthenticatedRequester", 1.0)
            return {"status": "REJECTED",
                    "reason": "unauthenticated_requester"}

        purpose = inbound.get("purpose_of_use")
        if not _is_purpose_permitted(principal, purpose):
            _emit_metric("PurposeNotPermitted", 1.0,
                          dimensions={"PurposeOfUse": purpose or "unknown",
                                        "RequestingOrg": principal["org_id"]})
            return {"status": "REJECTED",
                    "reason": "purpose_of_use_not_permitted"}

    # Build the normalized query record. This is the record the
    # downstream pipeline operates on; it is also what gets
    # archived to S3 for audit replay.
    query = {
        "query_id":              str(uuid.uuid4()),
        "source":                inbound.get("source", "api_gateway_fhir_match"),
        "is_linkage_submission": is_linkage,
        "requesting_principal":  principal,
        "purpose_of_use":        inbound.get("purpose_of_use"),
        "search_demographics":   inbound.get("search_demographics", {}),
        "requested_data_categories":
            inbound.get("requested_data_categories", ["match_only"]),
        "response_window_ms":
            (LINKAGE_LATENCY_BUDGET_MS if is_linkage
              else REALTIME_LATENCY_BUDGET_MS),
        "received_at":           _now_iso(),
    }

    # Idempotency hash. A second arrival of the same inbound
    # query within the dedup window hits the same hash and is
    # dropped by the SQS deduplication layer in production.
    sd = query["search_demographics"]
    canon = _canonical_form(
        principal["org_id"] if principal else "linkage",
        query["purpose_of_use"] or "",
        sd.get("first_name"), sd.get("last_name"), sd.get("dob"),
    )
    query["query_hash"] = _sha256(canon)

    # Archive the inbound payload exactly as received plus the
    # normalized query record. Both are needed for forensic
    # audit; the inbound payload is the legal record of what
    # the requester actually sent.
    _archive_raw_to_s3({
        "inbound_payload": inbound,
        "query_record":    query,
    }, partition="raw-inbound", query_id=query["query_id"])

    # Route to the right SQS queue. Linkage submissions go to
    # the standard-priority queue; everything else goes to the
    # realtime queue.
    queue_url = (LINKAGE_QUEUE_URL if is_linkage
                  else REALTIME_QUEUE_URL)
    try:
        sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(query, default=str),
            MessageAttributes={
                "query_hash": {
                    "DataType":    "String",
                    "StringValue": query["query_hash"],
                },
            },
        )
    except Exception as exc:
        logger.info("SQS send skipped (demo mode is fine to ignore)",
                     extra={"queue": queue_url, "error": str(exc)})

    _emit_metric("QueryIngested", 1.0,
                  dimensions={
                      "PurposeOfUse": query["purpose_of_use"] or "linkage",
                      "IsLinkage": str(is_linkage),
                  })
    return query
```

---

## Step 2: Normalize the Demographic Search Criteria and Compute Blocking Keys

*The pseudocode calls this `normalize_query(query)`. Apply the same normalization the other recipes use: name case, suffix, hyphenation, transliteration; date format; standardized address (recipe 5.3 supplies this); phone E.164; sex normalization. Then compute the multiple complementary blocking keys that the matcher will union for candidate generation. Skip this and the matcher's accuracy drops on the very queries that most need it (queries with imperfect demographic data are usually for patients who themselves have inconsistent demographic data across organizations).*

```python
def _normalize_name(name: str) -> str:
    if not name:
        return ""
    return _strip_diacritics(name).upper().strip()

def _normalize_dob(dob: str) -> dict:
    """Return structured DOB with precision flag."""
    if not dob:
        return {"value": "", "precision": "none", "is_present": False}
    digits = re.sub(r"[^0-9]", "", dob)
    if len(digits) >= 8:
        return {"value": digits[:8], "precision": "full", "is_present": True}
    if len(digits) >= 6:
        return {"value": digits[:6] + "01", "precision": "year_month",
                "is_present": True}
    if len(digits) >= 4:
        return {"value": digits[:4] + "0101", "precision": "year_only",
                "is_present": True}
    return {"value": "", "precision": "invalid", "is_present": False}

def _normalize_phone(phone: str) -> Optional[str]:
    if not phone:
        return None
    digits = re.sub(r"[^0-9]", "", phone)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits[0] == "1":
        return f"+{digits}"
    return None

def _hyphenation_alternates(last_name: str) -> list:
    """Generate alternates for hyphenated last names: maiden, married, joined."""
    alts = [last_name]
    if "-" in last_name:
        parts = last_name.split("-")
        alts.extend(parts)
        alts.append("".join(parts))
        alts.append(" ".join(parts))
    return list(set(alts))

def _soundex_stub(s: str) -> str:
    """Coarse Soundex stand-in. Production uses a real Soundex / Double-Metaphone library."""
    if not s:
        return ""
    s = s.upper()
    return (s[0] + re.sub(r"[AEIOUYHW]", "", s[1:]))[:4]

def _nickname_alternates(first_name: str) -> list:
    """Coarse nickname expansion. Production uses a curated dictionary."""
    fn = (first_name or "").upper()
    nick_table = {
        "BOB":  ["ROBERT", "ROB", "BOBBY"],
        "ROB":  ["ROBERT", "BOB", "BOBBY"],
        "BILL": ["WILLIAM", "BILLY", "WILLIE"],
        "MARY": ["MARIA", "MARIE"],
        "MARIA": ["MARY", "MARIE"],
        "LIZ":  ["ELIZABETH", "BETH", "BETTY"],
    }
    return [fn] + nick_table.get(fn, [])

def normalize_query(query: dict) -> dict:
    """
    Build the normalized search payload and compute the
    blocking keys the matcher will use for candidate generation.
    """
    raw = query["search_demographics"]

    last_name_normalized = _normalize_name(raw.get("last_name"))
    first_name_normalized = _normalize_name(raw.get("first_name"))
    dob = _normalize_dob(raw.get("dob"))

    normalized = {
        "first_name_normalized":      first_name_normalized,
        "first_name_phonetic":        _soundex_stub(first_name_normalized),
        "first_name_nickname_alternates":
            _nickname_alternates(first_name_normalized),
        "last_name_normalized":       last_name_normalized,
        "last_name_phonetic":         _soundex_stub(last_name_normalized),
        "last_name_alternates":       _hyphenation_alternates(last_name_normalized),
        "dob":                        dob,
        "administrative_sex":         (raw.get("sex") or "").upper(),
        "standardized_address":       raw.get("standardized_address") or {},
        "phone_e164":                 _normalize_phone(raw.get("phone")),
        "ssn_full":                   raw.get("ssn"),
        "ssn_last4":                  (re.sub(r"[^0-9]", "",
                                                 raw.get("ssn") or "")[-4:]
                                          if raw.get("ssn") else None),
        "prior_cross_org_id":         raw.get("prior_cross_org_id"),
    }

    # Compute blocking keys. Multiple complementary keys for
    # blocking-recall; the matcher unions the candidates.
    blocking_keys = []
    if normalized["last_name_phonetic"] and dob["is_present"]:
        blocking_keys.append(
            ("ln_soundex_yob",
             f"{normalized['last_name_phonetic']}#{dob['value'][:4]}")
        )
    if normalized["last_name_normalized"] and normalized["first_name_normalized"]:
        blocking_keys.append(
            ("ln_initial_fn_initial",
             f"{normalized['last_name_normalized'][0]}"
             f"#{normalized['first_name_normalized'][0]}")
        )
    addr = normalized["standardized_address"]
    zip5 = (addr.get("zip") or "")[:5]
    if zip5 and dob["is_present"]:
        blocking_keys.append(
            ("zip3_dob_md", f"{zip5[:3]}#{dob['value'][4:8]}")
        )
    if normalized["prior_cross_org_id"]:
        blocking_keys.append(
            ("prior_xorg_id", normalized["prior_cross_org_id"])
        )

    normalized["blocking_keys"] = blocking_keys
    query["normalized"] = normalized

    # Archive the normalized payload to the curated zone for
    # forensic audit. The raw inbound is in the raw zone; the
    # normalized form is what the matcher actually used.
    _archive_raw_to_s3({
        "query_id":   query["query_id"],
        "normalized": normalized,
    }, partition="curated-normalized", query_id=query["query_id"])

    return query
```

---

## Step 3: Evaluate the Match Against the Local Cross-Org MPI

*The pseudocode calls this `evaluate_match(query)`. Use the blocking keys to retrieve candidate records, score each candidate with the probabilistic-record-linkage scorer, apply confidence thresholds, and produce a match decision. Cross-facility thresholds are calibrated more conservatively than internal thresholds; the cost of false positives is higher because a wrong cross-facility match produces a misfiled clinical document or a wrong-patient overlay in the consuming organization's chart.*

```python
def _jaro_winkler(a: str, b: str) -> float:
    """Lightweight Jaro-Winkler. Production uses a well-tested library."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    s1, s2 = a, b
    len1, len2 = len(s1), len(s2)
    match_distance = max(len1, len2) // 2 - 1
    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    for i, c in enumerate(s1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s2[j] != c:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break
    if matches == 0:
        return 0.0
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
    jaro = ((matches / len1) + (matches / len2)
             + ((matches - transpositions) / matches)) / 3.0
    prefix = 0
    for i in range(min(4, len1, len2)):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break
    return jaro + (prefix * 0.1 * (1 - jaro))

def _nickname_aware_first_name_score(query_fn: str, query_alts: list,
                                       candidate_fn: str) -> Decimal:
    """First-name match with nickname expansion."""
    if not query_fn or not candidate_fn:
        return Decimal("0.5")
    candidate_upper = candidate_fn.upper()
    if candidate_upper == query_fn:
        return Decimal("1.0")
    # Check nickname alternates exact match.
    if candidate_upper in query_alts:
        return Decimal("0.95")
    # Fall through to similarity.
    return _to_decimal(_jaro_winkler(query_fn, candidate_upper))

def _cross_org_last_name_score(query_ln: str, query_alts: list,
                                  candidate_ln: str,
                                  candidate_prior: list) -> Decimal:
    """Last-name match with hyphenation tolerance and prior-name handling."""
    if not query_ln or not candidate_ln:
        return Decimal("0.5")
    candidate_upper = candidate_ln.upper()
    if candidate_upper == query_ln:
        return Decimal("1.0")
    # Check candidate's prior names (recipe 5.7's data).
    for prior in candidate_prior or []:
        if prior.upper() == query_ln:
            return Decimal("0.92")
    # Check query's hyphenation alternates.
    for alt in query_alts:
        if alt.upper() == candidate_upper:
            return Decimal("0.95")
        for prior in candidate_prior or []:
            if alt.upper() == prior.upper():
                return Decimal("0.88")
    # Fall through to similarity.
    return _to_decimal(_jaro_winkler(query_ln, candidate_upper))

def _dob_match_grade(query_dob: dict, candidate_dob: str) -> Decimal:
    """Grade DOB match: exact / year-month / year / mismatch."""
    if not query_dob["is_present"] or not candidate_dob:
        return Decimal("0.0")
    q = query_dob["value"]
    c = re.sub(r"[^0-9]", "", candidate_dob)[:8]
    if not q or not c:
        return Decimal("0.0")
    if q == c:
        return Decimal("1.0")
    if q[:6] == c[:6]:
        return Decimal("0.7")
    if q[:4] == c[:4]:
        return Decimal("0.4")
    return Decimal("0.0")

def _sex_match(q: str, c: str) -> Decimal:
    if not q or not c:
        return Decimal("0.5")
    return Decimal("1.0") if q.upper() == c.upper() else Decimal("0.0")

def _address_similarity(query_addr: dict, candidate_addr: dict,
                          candidate_prior_addrs: list) -> Decimal:
    """Address similarity with prior-address fallback (recipe 5.3 pattern)."""
    if not query_addr or not candidate_addr:
        return Decimal("0.5")
    q_zip = (query_addr.get("zip") or "")[:5]
    c_zip = (candidate_addr.get("zip") or "")[:5]
    q_street = (query_addr.get("line1") or "").upper()
    c_street = (candidate_addr.get("line1") or "").upper()

    zip_match = Decimal("1.0") if q_zip and q_zip == c_zip else Decimal("0.0")
    street_sim = _to_decimal(_jaro_winkler(q_street, c_street))
    primary_score = (zip_match * Decimal("0.5")) + (street_sim * Decimal("0.5"))

    # If the primary address does not match well, check prior
    # addresses (the patient may have moved recently).
    best_prior_score = Decimal("0.0")
    for prior in candidate_prior_addrs or []:
        p_zip = (prior.get("zip") or "")[:5]
        p_street = (prior.get("line1") or "").upper()
        p_zip_match = Decimal("1.0") if q_zip and q_zip == p_zip else Decimal("0.0")
        p_street_sim = _to_decimal(_jaro_winkler(q_street, p_street))
        # TODO (TechWriter): Code review Finding 1 (WARNING).
        # The parentheses below put the 0.9 multiplier only on
        # the street component. Python's operator precedence
        # binds * tighter than +, so the expression evaluates
        # as (p_zip_match * 0.5) + ((p_street_sim * 0.5) * 0.9)
        # rather than ((p_zip_match * 0.5) + (p_street_sim *
        # 0.5)) * 0.9. The 0.9 "matching prior over current"
        # penalty therefore does not apply to the zip_match
        # component and a recently-moved patient who still
        # lives in the same ZIP gets an inflated prior-address
        # score. The demo's expected output is unaffected (no
        # demo trigger exercises the prior-address fallback
        # path), but the fix is one set of parentheses:
        #   prior_score = (
        #       (p_zip_match * Decimal("0.5"))
        #       + (p_street_sim * Decimal("0.5"))
        #   ) * Decimal("0.9")
        prior_score = ((p_zip_match * Decimal("0.5"))
                          + (p_street_sim * Decimal("0.5"))
                          # Slight penalty for matching prior over current.
                          * Decimal("0.9"))
        if prior_score > best_prior_score:
            best_prior_score = prior_score

    return max(primary_score, best_prior_score)

def _phone_match(q: Optional[str], candidate_history: list) -> Decimal:
    if not q or not candidate_history:
        return Decimal("0.5")
    if q in candidate_history:
        return Decimal("1.0")
    # Last 7 digits match (different area code, same phone).
    q_last7 = re.sub(r"[^0-9]", "", q)[-7:]
    for c in candidate_history:
        c_last7 = re.sub(r"[^0-9]", "", c)[-7:]
        if q_last7 == c_last7:
            return Decimal("0.8")
    return Decimal("0.0")

def _ssn_match(q_full: Optional[str], q_last4: Optional[str],
                 c_full: Optional[str], c_last4: Optional[str]) -> Decimal:
    if q_full and c_full:
        if re.sub(r"[^0-9]", "", q_full) == re.sub(r"[^0-9]", "", c_full):
            return Decimal("1.0")
        return Decimal("0.0")
    if q_last4 and c_last4:
        return Decimal("0.7") if q_last4 == c_last4 else Decimal("0.0")
    return Decimal("0.5")

def _prior_cross_org_id_match(q_id: Optional[str],
                                  c_id: Optional[str]) -> Decimal:
    if not q_id or not c_id:
        return Decimal("0.5")
    return Decimal("1.0") if q_id == c_id else Decimal("0.0")

def _composite_score(features: dict) -> Decimal:
    """Weighted sum of feature scores, normalized to [0, 1]."""
    total_weight = sum(SCORE_WEIGHTS.values())
    weighted = sum(SCORE_WEIGHTS[k] * features[k] for k in SCORE_WEIGHTS)
    return weighted / total_weight

def evaluate_match(query: dict) -> dict:
    """
    Block, score, threshold, and produce the match outcome.
    """
    _build_blocking_index_if_needed()
    normalized = query["normalized"]

    # 3A: candidate generation via blocking-key union.
    candidate_ids = set()
    for (block_type, block_value) in normalized["blocking_keys"]:
        for pid in _BLOCKING_INDEX.get((block_type, block_value), []):
            candidate_ids.add(pid)

    if len(candidate_ids) > MAX_CANDIDATES_PER_QUERY:
        # In production, sort by recency or block-strength and
        # keep the top N. The demo just slices.
        candidate_ids = set(list(candidate_ids)[:MAX_CANDIDATES_PER_QUERY])
        _emit_metric("QueryTruncatedCandidates", 1.0)

    # 3B: load each candidate's snapshot from the cross-org MPI.
    candidates_full = [SYNTHETIC_CROSS_ORG_MPI[pid]
                        for pid in candidate_ids
                        if pid in SYNTHETIC_CROSS_ORG_MPI]

    # 3C: score each candidate.
    scored = []
    for cand in candidates_full:
        features = {
            "first_name": _nickname_aware_first_name_score(
                              normalized["first_name_normalized"],
                              normalized["first_name_nickname_alternates"],
                              cand["first_name"]),
            "last_name":  _cross_org_last_name_score(
                              normalized["last_name_normalized"],
                              normalized["last_name_alternates"],
                              cand["last_name"],
                              cand.get("prior_last_names", [])),
            "dob":        _dob_match_grade(normalized["dob"],
                                              cand["dob"]),
            "sex":        _sex_match(normalized["administrative_sex"],
                                        cand["administrative_sex"]),
            "address":    _address_similarity(
                              normalized["standardized_address"],
                              cand["standardized_address"],
                              cand.get("prior_addresses", [])),
            "phone":      _phone_match(normalized["phone_e164"],
                                          cand.get("phone_history", [])),
            "ssn":        _ssn_match(normalized.get("ssn_full"),
                                        normalized.get("ssn_last4"),
                                        cand.get("ssn_full"),
                                        cand.get("ssn_last4")),
            "prior_cross_org_id":
                _prior_cross_org_id_match(
                    normalized.get("prior_cross_org_id"),
                    cand.get("cross_org_id")),
        }
        composite = _composite_score(features)
        scored.append({
            "candidate":  cand,
            "features":   features,
            "composite":  composite,
        })

    # 3D: handle no-candidate case.
    if not scored:
        outcome = {
            "status": "NO_CANDIDATE",
            "interpretation": "no_candidate_in_blocking",
            "matcher_config_version": MATCHER_CONFIG_VERSION,
            "thresholds_version":     THRESHOLDS_VERSION,
        }
        _emit_metric("MatchOutcome", 1.0,
                      dimensions={"Status": outcome["status"]})
        query["match_outcome"] = outcome
        return query

    best = max(scored, key=lambda s: s["composite"])

    # 3E: cohort-stratified telemetry.
    cohort_bucket = best["candidate"].get("cohort_bucket", "unknown")
    _emit_metric("MatchScore", float(best["composite"]),
                  dimensions={"CohortBucket": cohort_bucket})

    # 3F: apply confidence thresholds. Conservative band-routing.
    if best["composite"] >= AUTO_ACCEPT_HIGH_THRESHOLD:
        outcome = {
            "status": "MATCHED_HIGH_CONFIDENCE",
            "matched_local_patient_id":
                best["candidate"]["local_patient_id"],
            "matched_cross_org_id":
                best["candidate"].get("cross_org_id"),
            "match_confidence":  best["composite"],
            "score_breakdown":   best["features"],
            "match_method":      "probabilistic_high_confidence",
            "matcher_config_version": MATCHER_CONFIG_VERSION,
            "thresholds_version":     THRESHOLDS_VERSION,
        }
    elif best["composite"] >= AUTO_ACCEPT_MED_THRESHOLD:
        outcome = {
            "status": "MATCHED_MED_CONFIDENCE",
            "matched_local_patient_id":
                best["candidate"]["local_patient_id"],
            "matched_cross_org_id":
                best["candidate"].get("cross_org_id"),
            "match_confidence":  best["composite"],
            "score_breakdown":   best["features"],
            "match_method":      "probabilistic_med_confidence",
            "release_scope_modifier":
                "downgrade_to_high_value_only",
            "matcher_config_version": MATCHER_CONFIG_VERSION,
            "thresholds_version":     THRESHOLDS_VERSION,
        }
    elif best["composite"] <= AUTO_REJECT_THRESHOLD:
        outcome = {
            "status": "NO_MATCH",
            "best_candidate_score": best["composite"],
            "interpretation": "below_auto_reject_threshold",
            "matcher_config_version": MATCHER_CONFIG_VERSION,
            "thresholds_version":     THRESHOLDS_VERSION,
        }
    else:
        # Review band: query gets NO_MATCH in real time, but
        # the case is queued for asynchronous review.
        outcome = {
            "status": "NO_MATCH_DEFERRED_REVIEW",
            "best_candidate_score": best["composite"],
            "best_candidate_id":
                best["candidate"]["local_patient_id"],
            "queued_for_review": True,
            "matcher_config_version": MATCHER_CONFIG_VERSION,
            "thresholds_version":     THRESHOLDS_VERSION,
        }
        try:
            sqs_client.send_message(
                QueueUrl=REVIEW_QUEUE_URL,
                MessageBody=json.dumps({
                    "query_id":         query["query_id"],
                    "best_candidate":   best["candidate"]["local_patient_id"],
                    "best_score":       str(best["composite"]),
                    "other_candidates": [
                        s["candidate"]["local_patient_id"]
                        for s in scored if s is not best
                    ],
                }, default=str),
            )
        except Exception as exc:
            logger.info("review queue send skipped (demo mode)",
                         extra={"error": str(exc)})

    _emit_metric("MatchOutcome", 1.0,
                  dimensions={"Status": outcome["status"],
                                "CohortBucket": cohort_bucket})
    query["match_outcome"] = outcome
    return query
```

---

## Step 4: Apply Consent and Sensitivity Filters

*The pseudocode calls this `apply_consent_and_sensitivity(query)`. Even when the identity match is high-confidence, the consent registry determines what data may be released, and the sensitivity-filter policy determines what categories must be withheld even within the consented set. This step has to fail closed: if the consent registry is unreachable, withhold release. Skip this and you produce the failure mode that ends an HIE participation: a release that violated the patient's consent or that exposed a sensitive-category record to a requester without legal basis.*

```python
def apply_consent_and_sensitivity(query: dict) -> dict:
    """
    Consult consent, apply sensitivity filter, build release
    decision. Fail-closed if consent registry is unavailable.
    """
    match = query["match_outcome"]

    # 4A: linkage submissions and no-match outcomes do not
    # require consent checks; their audit-only.
    if (query.get("is_linkage_submission")
            or match["status"] in {"NO_MATCH",
                                       "NO_MATCH_DEFERRED_REVIEW",
                                       "NO_CANDIDATE"}):
        query["release_decision"] = {
            "release": False,
            "reason":  "no_match_or_linkage_submission",
        }
        return query

    matched_id = match["matched_local_patient_id"]
    requesting_org = (query["requesting_principal"] or {}).get("org_id", "")
    purpose = query["purpose_of_use"]

    # 4B: read consent state. Fail-closed on registry error.
    try:
        consent_state = consent_registry.get(
            patient_local_id=matched_id,
            requesting_org=requesting_org,
            purpose_of_use=purpose,
            requested_data_categories=query["requested_data_categories"],
            timeout_ms=500,
        )
    except ConsentRegistryUnavailable as exc:
        _emit_metric("ConsentRegistryUnavailable", 1.0)
        query["release_decision"] = {
            "release":      False,
            "reason":       "consent_registry_unavailable",
            "should_retry": True,
        }
        # Audit the registry-unavailable separately so post-hoc
        # consent verification has a complete record.
        _archive_raw_to_s3({
            "query_id":   query["query_id"],
            "type":       "consent_registry_unavailable",
            "matched_id": matched_id,
            "error":      str(exc),
        }, partition="curated-consent-failures",
            query_id=query["query_id"])
        return query

    # 4C: evaluate consent state.
    if not consent_state["is_exchange_permitted"]:
        # Either no consent on file, expired, or revoked.
        query["release_decision"] = {
            "release":     False,
            "reason":      ("consent_expired"
                              if consent_state.get("summary") == "consent_expired"
                              else "consent_does_not_permit"),
            "consent_state_summary": {
                "is_exchange_permitted": False,
                "discoverability_permitted":
                    consent_state["discoverability_permitted"],
                "summary": consent_state["summary"],
            },
        }
        return query

    # 4D: identify the eligible data set under consent.
    eligible_data_categories = list(
        set(consent_state["permitted_data_categories"])
        & set(query["requested_data_categories"])
    )
    # If the requester asked for "match_only" we still pass
    # through the consent gate (because a discoverability
    # decision is part of the response) but the eligible set is
    # empty.
    if "match_only" in query["requested_data_categories"]:
        eligible_data_categories = []

    # 4E: apply the sensitivity filter to the eligible set.
    sensitivity_result = sensitivity_filter.filter(
        patient_id=matched_id,
        eligible_data_categories=eligible_data_categories,
        purpose_of_use=purpose,
        requesting_principal_org=requesting_org,
        patient_flagged_sensitive_categories=
            consent_state.get("patient_flagged_sensitive_categories", []),
    )

    # 4F: apply the release-scope modifier from medium-confidence
    # matches. Med-confidence releases a narrower set than
    # high-confidence.
    if match.get("release_scope_modifier") == "downgrade_to_high_value_only":
        sensitivity_result["released_data_categories"] = [
            c for c in sensitivity_result["released_data_categories"]
            if c in HIGH_VALUE_DATA_AT_MED_CONFIDENCE
        ]

    query["release_decision"] = {
        "release":              True,
        "consent_state_summary": {
            "is_exchange_permitted": True,
            "discoverability_permitted":
                consent_state["discoverability_permitted"],
            "expires_at": consent_state.get("expires_at"),
            "summary":     consent_state["summary"],
        },
        "released_data_categories":
            sensitivity_result["released_data_categories"],
        "filtered_data_categories":
            sensitivity_result["filtered_data_categories"],
        "additional_notes":
            sensitivity_result["additional_notes"],
        "match_confidence":       match["match_confidence"],
        "match_score_breakdown":  match["score_breakdown"],
        "sensitivity_policy_version":
            sensitivity_result["policy_version"],
    }
    return query
```

---

## Step 5: Release, Audit, and Propagate

*The pseudocode calls this `release_and_audit(query)`. Construct the response payload according to the release decision, write the full audit record (append-only), archive raw and curated payloads to S3, and emit the cross-facility event. The audit record is the system of record for what was queried, what was matched, what consent permitted, what was released, and what was withheld. Skip the audit and you cannot answer the patient's right-to-know question, you cannot reconstruct a downstream incident, and you cannot demonstrate compliance with the participation agreement.*

```python
def _build_response_payload(query: dict) -> dict:
    """Construct the response payload according to the release decision."""
    match = query["match_outcome"]
    decision = query["release_decision"]

    if decision["release"]:
        # In production, the longitudinal-record-assembler is
        # called here to actually fetch and assemble the data
        # from the EHR for the released categories. The demo
        # returns a sketch of the payload structure.
        released_data_summary = {
            cat: f"<assembled_clinical_data_for_{cat}>"
            for cat in decision["released_data_categories"]
        }
        return {
            "match_status":         match["status"],
            "match_confidence":     str(match["match_confidence"]),
            "cross_org_identifier": match.get("matched_cross_org_id"),
            "data":                 released_data_summary,
            "withheld_data_summary": {
                "categories": decision["filtered_data_categories"],
                "notes":      decision["additional_notes"],
            },
        }

    # Discoverability check: in some frameworks, even
    # acknowledging the patient is in our system requires
    # consent.
    # TODO (TechWriter): Code review Finding 3 (NOTE). The
    # discoverability-NO_MATCH masking only fires when
    # decision["reason"] == "consent_does_not_permit". The
    # consent_expired and consent_registry_unavailable branches
    # fall through to MATCHED_NOT_RELEASABLE (or
    # TEMPORARY_UNAVAILABLE), which reveals the patient is in
    # our system. Pseudocode's intent (also flagged in expert-
    # review A3) is to apply the discoverability-first masking
    # before checking specific reason codes. Fix:
    #   if not consent_summary.get("discoverability_permitted", False):
    #       return {"match_status": "NO_MATCH"}
    # placed before any of the reason-specific branches, with a
    # fail-closed default (False when the field is absent).
    consent_summary = decision.get("consent_state_summary") or {}
    if (decision["reason"] == "consent_does_not_permit"
            and not consent_summary.get("discoverability_permitted")):
        return {"match_status": "NO_MATCH"}

    if decision["reason"] in {"consent_does_not_permit",
                                  "consent_expired"}:
        return {
            "match_status":   "MATCHED_NOT_RELEASABLE",
            "withhold_reason": decision["reason"],
        }

    if decision["reason"] == "consent_registry_unavailable":
        return {
            "match_status":   "TEMPORARY_UNAVAILABLE",
            "withhold_reason": "consent_registry_unavailable",
            "should_retry":    True,
        }

    return {"match_status": match["status"]}

def release_and_audit(query: dict) -> dict:
    """
    Build the response payload, write the audit record (append-
    only), archive to S3, emit the cross_facility_query_resolved
    event, and return the audit record.
    """
    match = query["match_outcome"]
    decision = query["release_decision"]
    response_payload = _build_response_payload(query)

    # TODO (TechWriter): Expert review A1 (HIGH). Wrap the
    # audit-log put, the S3 audit archive, the EventBridge
    # emit, and the response transmission in a TransactWriteItems
    # plus an outbox row drained by a separate Lambda or
    # DynamoDB Streams consumer so partial failures cannot
    # leave the audit log out of sync with the released
    # response. Same chapter pattern as 5.1, 5.2, 5.3, 5.4
    # Finding A1; the consequence here is sharper because the
    # audit log is the legal record of what was exchanged, and
    # any divergence between what was sent and what the audit
    # log claims was sent is a compliance incident.

    # 5A: write the audit record. Append-only via the
    # condition_expression below; production extends with
    # signature chaining and cross-account replication.
    audit_record = _serialize_for_dynamodb({
        "query_id":            query["query_id"],
        "event_seq":           1,
        "received_at":         query["received_at"],
        "completed_at":        _now_iso(),
        "requesting_org":      (query["requesting_principal"] or {}).get(
                                  "org_id", "linkage"),
        "purpose_of_use":      query["purpose_of_use"],
        "is_linkage_submission": query.get("is_linkage_submission", False),
        "match_outcome":       match,
        "release_decision_summary": {
            "release":         decision["release"],
            "reason":          decision.get("reason"),
            "released_data_categories":
                decision.get("released_data_categories", []),
            "filtered_data_categories":
                decision.get("filtered_data_categories", []),
        },
        "matcher_config_version":
            match.get("matcher_config_version"),
        "thresholds_version": match.get("thresholds_version"),
        "sensitivity_policy_version":
            decision.get("sensitivity_policy_version"),
        "response_correlation_id": str(uuid.uuid4()),
    })

    try:
        dynamodb.Table(AUDIT_LOG_TABLE).put_item(
            Item=audit_record,
            ConditionExpression="attribute_not_exists(query_id)",
        )
    except Exception as exc:
        logger.info("audit-log put skipped (demo mode is fine to ignore)",
                     extra={"error": str(exc)})
    # In-memory fallback so the demo's read path still works.
    _IN_MEMORY_AUDIT_LOG[(query["query_id"], 1)] = audit_record

    # 5B: archive the raw response (the legal record of what we
    # sent back) and the curated audit-record-plus-summary.
    _archive_raw_to_s3({
        "query_id":         query["query_id"],
        "response_payload": response_payload,
    }, partition="raw-outbound", query_id=query["query_id"])
    _archive_raw_to_s3({
        "query_id":          query["query_id"],
        "audit_record":      audit_record,
        "response_summary":  response_payload,
    }, partition="curated-audit", query_id=query["query_id"])

    # 5C: emit the cross_facility_query_resolved event.
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "cross-facility-matching",
            "DetailType":   "cross_facility_query_resolved",
            "EventBusName": EVENTS_BUS_NAME,
            "Detail": json.dumps({
                "query_id":             query["query_id"],
                "patient_local_id":
                    match.get("matched_local_patient_id")
                    if decision["release"] else None,
                "cross_org_id":
                    match.get("matched_cross_org_id")
                    if decision["release"] else None,
                "requesting_org":
                    (query["requesting_principal"] or {}).get("org_id"),
                "purpose_of_use":   query["purpose_of_use"],
                "outcome_status":   match["status"],
                "release_status":   decision["release"],
                "resolved_at":      _now_iso(),
            }, default=str),
        }])
    except Exception as exc:
        logger.info("event emit skipped (demo mode is fine to ignore)",
                     extra={"error": str(exc)})

    # 5D: return the response payload to the caller. In
    # production this is what the API Gateway endpoint
    # transmits back to the requester.
    query["response_payload"] = response_payload
    query["audit_record"] = audit_record
    return query
```

---

## Step 6: React to Invalidation Triggers

*The pseudocode calls this `invalidate_on_event(event)`. Cross-facility match decisions are time-sensitive: a consent revocation, a local MPI merge or unmerge (recipe 5.1), a demographic change (recipes 5.3, 5.7), a participating-org offboarding, all invalidate prior matches in ways the requesting organizations need to know about. Skip the invalidation pipeline and stale match decisions accumulate downstream, producing data flow about patients who have since revoked consent. The fail-closed posture on consent has to extend through the lifecycle, not just the initial release.*

```python
def invalidate_on_event(event: dict) -> dict:
    """
    Process an invalidation trigger. Update the cross-org MPI
    where appropriate, surface any prior queries that need
    refresh-notification, and emit the
    cross_facility_match_invalidated event.
    """
    source = event.get("source")
    summary = {"source": source, "actions": []}

    if source == "consent_revocation":
        # Find prior queries about this patient and emit
        # invalidation events so the requesting organization
        # can refresh its longitudinal record.
        affected = [
            (qid, seq, rec)
            for (qid, seq), rec in _IN_MEMORY_AUDIT_LOG.items()
            if rec.get("match_outcome", {}).get(
                  "matched_local_patient_id") == event["patient_local_id"]
        ]
        summary["affected_query_count"] = len(affected)
        summary["actions"].append("emit_invalidation_per_affected_query")

    elif source == "local_mpi_merge":
        # Recipe 5.1 merged two records. Re-point cross-facility
        # match decisions referencing the merged-from record to
        # the surviving record.
        merged_from = event["merged_from_patient_id"]
        merged_into = event["merged_into_patient_id"]
        # Update the cross-org MPI to redirect.
        if merged_from in SYNTHETIC_CROSS_ORG_MPI:
            SYNTHETIC_CROSS_ORG_MPI[merged_from]["superseded_by"] = merged_into
        summary["merged_from"] = merged_from
        summary["merged_into"] = merged_into
        summary["actions"].append("redirect_superseded_local_id")
        # Recompute the surviving record's cross-org identifier
        # to incorporate any prior cross-org links that the
        # merged-from record had.
        # (Production: walk both records' cross-org-link history
        #  and produce a unified cross_org_id; the demo skips
        #  this complexity.)

    elif source == "name_change_5_7":
        # Recipe 5.7 recorded a patient name change. Update the
        # prior_last_names list so future queries match against
        # both the new and old name.
        pid = event["patient_local_id"]
        if pid in SYNTHETIC_CROSS_ORG_MPI:
            existing = SYNTHETIC_CROSS_ORG_MPI[pid].get("prior_last_names", [])
            existing.append(event["previous_last_name"])
            SYNTHETIC_CROSS_ORG_MPI[pid]["prior_last_names"] = existing
            # Rebuild the blocking index (production does this
            # incrementally rather than rebuilding from scratch).
            _BLOCKING_INDEX.clear()
        summary["actions"].append("append_prior_last_name")

    elif source == "address_change_5_3":
        # Recipe 5.3 detected an address change. Append the
        # prior address so future queries match against both
        # current and prior addresses.
        pid = event["patient_local_id"]
        if pid in SYNTHETIC_CROSS_ORG_MPI:
            existing = SYNTHETIC_CROSS_ORG_MPI[pid].get("prior_addresses", [])
            existing.append(event["previous_address"])
            SYNTHETIC_CROSS_ORG_MPI[pid]["prior_addresses"] = existing
        summary["actions"].append("append_prior_address")

    elif source == "participating_org_offboarded":
        # Production walks the audit log and emits invalidation
        # events for all prior queries involving this org. The
        # demo just records the action.
        summary["org_id"] = event["org_id"]
        summary["actions"].append("invalidate_per_org_audit_history")

    # Emit aggregated invalidation event for downstream
    # consumers to refresh their longitudinal records.
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "cross-facility-matching",
            "DetailType":   "cross_facility_match_invalidated",
            "EventBusName": EVENTS_BUS_NAME,
            "Detail": json.dumps({
                "invalidation_source":     source,
                "invalidation_event_id":   event.get("event_id"),
                "affected_patient_local_id":
                    event.get("patient_local_id")
                    or event.get("merged_from_patient_id"),
                "invalidated_at": _now_iso(),
            }, default=str),
        }])
    except Exception as exc:
        logger.info("invalidation event emit skipped (demo mode)",
                     extra={"error": str(exc)})

    _emit_metric("MatchInvalidations", 1.0,
                  dimensions={"Source": source or "unknown"})
    return summary
```

---

## Full Pipeline

The pipeline assembles the six steps into a single callable function. In production these are separate Lambdas (and Glue stages for batch reconciliation) orchestrated by Step Functions; here we run them in-process so the trace is easy to follow. The full demo also includes a small outbound-query example that fans out to the mock partner organizations to show the inbound-aggregation pattern.

```python
def run_pipeline(inbound: dict) -> dict:
    """
    End-to-end ingest -> normalize -> evaluate -> consent +
    sensitivity -> release + audit pipeline for one inbound
    query or linkage submission. Returns a small summary
    dict for the caller (and the demo) to print.
    """
    # Step 1: ingest.
    query = ingest_query(inbound)
    if query.get("status") == "REJECTED":
        return {
            "query_id": None,
            "status":   "REJECTED",
            "reason":   query["reason"],
        }

    # Step 2: normalize.
    query = normalize_query(query)

    # Step 3: evaluate match.
    query = evaluate_match(query)

    # Step 4: consent + sensitivity.
    query = apply_consent_and_sensitivity(query)

    # Step 5: release + audit.
    query = release_and_audit(query)

    return {
        "query_id":       query["query_id"],
        "match_status":   query["match_outcome"]["status"],
        "match_confidence":
            query["match_outcome"].get("match_confidence"),
        "release":        query["release_decision"]["release"],
        "release_reason": query["release_decision"].get("reason"),
        "released_categories":
            query["release_decision"].get("released_data_categories"),
        "filtered_categories":
            query["release_decision"].get("filtered_data_categories"),
        "response_payload": query["response_payload"],
    }

def fan_out_to_partners(search_payload: dict,
                          partner_org_ids: list) -> list:
    """
    Outbound side: when our local clinician queries the HIE
    for a patient, the HIE typically fans out to multiple
    partner organizations. This function shows the
    aggregate-partner-responses pattern. Production runs each
    partner call in parallel with timeouts and partial-response
    handling; the demo is sequential for readability.
    """
    aggregated = []
    for partner_id in partner_org_ids:
        partner = partner_orgs.get(partner_id)
        if partner is None:
            continue
        try:
            resp = partner.fhir_patient_match(
                search_payload, timeout_ms=2000)
            aggregated.append({
                "partner_org": partner_id,
                "response":    resp,
                "status":      "OK",
            })
        except Exception as exc:
            # Partial response: log the timeout, continue with
            # the partners that did respond. The aggregating
            # layer cannot block on a slow partner.
            aggregated.append({
                "partner_org": partner_id,
                "response":    None,
                "status":      "TIMEOUT_OR_ERROR",
                "error":       str(exc),
            })
    return aggregated

def run_demo():
    """
    Run the full pipeline against a small set of synthetic
    inbound queries that exercise the major paths.
    """
    print("=" * 70)
    print("Cross-Facility Patient Matching Demo (HIE-scale)")
    print("=" * 70)
    print()
    print("All patients, organizations, and HIE responses in this demo")
    print("are fictional. The mock consent registry, sensitivity filter,")
    print("and partner orgs return hand-crafted responses that exercise")
    print("the full classification range; do not point this demo at a")
    print("live HIE.")
    print()
    print(f"Thresholds: HIGH={AUTO_ACCEPT_HIGH_THRESHOLD}, "
          f"MED={AUTO_ACCEPT_MED_THRESHOLD}, "
          f"REJECT={AUTO_REJECT_THRESHOLD}")
    print()

    inbound_queries = [
        # 1. Trauma-team query for Jane Doe with full demographics
        # and high-confidence expected match. Treatment purpose,
        # consent permits.
        {
            "label":          "trauma-team query (high-confidence)",
            "source":         "api_gateway_fhir_match",
            "requesting_org": "regional-hie-trauma-network",
            "credential_id":  "hie-cert-001",
            "purpose_of_use": "treatment",
            "search_demographics": {
                "first_name": "Jane",
                "last_name":  "Doe",
                "dob":        "1980-06-15",
                "sex":        "F",
                "standardized_address": {
                    "line1": "1421 ELM ST APT 3B",
                    "zip":   "12345",
                },
                "phone":      "555-123-4567",
                "ssn":        "123-45-6789",
            },
            "requested_data_categories": [
                "allergies", "medications", "problem_list",
                "advance_directives", "lab_results_recent",
                "imaging_reports_recent",
            ],
        },
        # 2. Maria queried by maiden name (Garcia); cross-org
        # MPI has her as Garcia-Lopez with Garcia in
        # prior_last_names. Tests the recipe 5.7 prior-name
        # match path. Reproductive-health flagged sensitive.
        {
            "label":          "maiden-name query -> prior-name match",
            "source":         "api_gateway_fhir_match",
            "requesting_org": "partner-org-academic-mc",
            "credential_id":  "amc-cert-99",
            "purpose_of_use": "treatment",
            "search_demographics": {
                "first_name": "Maria",
                "last_name":  "Garcia",
                "dob":        "1972-03-14",
                "sex":        "F",
                "standardized_address": {
                    "line1": "1421 ELM ST APT 3B",
                    "zip":   "12345",
                },
                "ssn":        "987-65-4321",
            },
            "requested_data_categories": [
                "allergies", "medications", "problem_list",
                "lab_results_recent", "reproductive_health",
            ],
        },
        # 3. Med-confidence path: Alex Johnson with mismatched
        # address (moved). Sensitivity filter blocks
        # behavioral_health_notes.
        # TODO (TechWriter): Code review Finding 2 (NOTE). This
        # trigger does not actually exercise the med-confidence
        # path. The composite score lands at ~0.78 (between
        # AUTO_REJECT and AUTO_ACCEPT_MED), so the matcher
        # routes the case to NO_MATCH_DEFERRED_REVIEW and
        # apply_consent_and_sensitivity short-circuits before
        # the sensitivity filter ever runs. The closing prose
        # paragraph correctly identifies this as the deferred-
        # review path; the inline comment should match. Either
        # rewrite this comment as a deferred-review trigger,
        # or change the trigger inputs (current address,
        # supplied phone) so the composite lands at MED with
        # behavioral_health_notes in requested categories so
        # the sensitivity-filter block actually fires.
        {
            "label":          "med-confidence + sensitivity-filter path",
            "source":         "api_gateway_fhir_match",
            "requesting_org": "partner-org-urgent-care",
            "credential_id":  "uc-cert-22",
            "purpose_of_use": "treatment",
            "search_demographics": {
                "first_name": "Alex",
                "last_name":  "Johnson",
                "dob":        "1995-11-02",
                "sex":        "M",
                "standardized_address": {
                    "line1": "999 NEW STREET",
                    "zip":   "67890",
                },
            },
            "requested_data_categories": [
                "allergies", "medications", "problem_list",
                "behavioral_health_notes",
            ],
        },
        # 4. Unauthorized purpose-of-use: research from a
        # non-academic requester. Should be rejected at the
        # ingest layer.
        {
            "label":          "research request from non-academic (rejected)",
            "source":         "api_gateway_fhir_match",
            "requesting_org": "partner-org-urgent-care",
            "credential_id":  "uc-cert-22",
            "purpose_of_use": "research",
            "search_demographics": {
                "first_name": "Jane",
                "last_name":  "Doe",
                "dob":        "1980-06-15",
            },
            "requested_data_categories": ["lab_results_recent"],
        },
        # 5. No-match case: query for a patient not in our MPI.
        {
            "label":          "no-match query",
            "source":         "api_gateway_fhir_match",
            "requesting_org": "regional-hie-trauma-network",
            "credential_id":  "hie-cert-001",
            "purpose_of_use": "treatment",
            "search_demographics": {
                "first_name": "Pat",
                "last_name":  "Nobody",
                "dob":        "1965-04-09",
            },
            "requested_data_categories": ["match_only"],
        },
    ]

    # Phase 1: process inbound queries.
    print("-" * 70)
    print("Phase 1: process inbound queries")
    print("-" * 70)
    for q in inbound_queries:
        label = q.pop("label")
        result = run_pipeline(q)
        if result.get("query_id") is None:
            print(f"  {label:<55} REJECTED reason={result['reason']}")
            continue
        conf = result.get("match_confidence")
        conf_str = (f"{conf:.2f}" if isinstance(conf, Decimal)
                      else str(conf) if conf else "n/a")
        rel = "yes" if result["release"] else "no"
        print(f"  {label:<55} status={result['match_status']:<25} "
              f"conf={conf_str:<6} release={rel}")
        if result.get("filtered_categories"):
            for f in result["filtered_categories"]:
                print(f"      filtered: {f['category']:<30} "
                      f"reason={f['reason']}")

    # Phase 2: simulate a consent-registry outage on one query.
    print()
    print("-" * 70)
    print("Phase 2: simulate a consent-registry outage (fail-closed)")
    print("-" * 70)
    consent_registry.simulate_outage = True
    outage_query = {
        "source":         "api_gateway_fhir_match",
        "requesting_org": "regional-hie-trauma-network",
        "credential_id":  "hie-cert-001",
        "purpose_of_use": "treatment",
        "search_demographics": {
            "first_name": "Jane",
            "last_name":  "Doe",
            "dob":        "1980-06-15",
            "sex":        "F",
            "standardized_address": {
                "line1": "1421 ELM ST APT 3B",
                "zip":   "12345",
            },
        },
        "requested_data_categories": ["allergies", "medications"],
    }
    outage_result = run_pipeline(outage_query)
    consent_registry.simulate_outage = False
    print(f"  fail-closed result: status={outage_result['match_status']:<25} "
          f"release={outage_result['release']} "
          f"reason={outage_result.get('release_reason')}")

    # Phase 3: outbound fan-out to partner orgs.
    print()
    print("-" * 70)
    print("Phase 3: outbound fan-out to partner orgs")
    print("-" * 70)
    fanout_payload = {
        "first_name": "JANE",
        "last_name":  "DOE",
        "dob":        "19800615",
    }
    aggregated = fan_out_to_partners(fanout_payload,
                                       ["partner-org-academic-mc",
                                        "partner-org-urgent-care"])
    for resp in aggregated:
        match_count = ((resp["response"] or {}).get("match_count")
                          if resp["status"] == "OK" else "n/a")
        print(f"  partner={resp['partner_org']:<30} "
              f"status={resp['status']:<10} "
              f"match_count={match_count}")

    # Phase 4: simulate an invalidation trigger.
    print()
    print("-" * 70)
    print("Phase 4: simulate an invalidation trigger (consent revocation)")
    print("-" * 70)
    invalidation = invalidate_on_event({
        "source":             "consent_revocation",
        "event_id":           "evt-2026-05-22-000999",
        "patient_local_id":   "local-patient-internal-00874",
        "consent_change_effective_date": _now_iso(),
    })
    print(f"  source={invalidation['source']} "
          f"affected_query_count={invalidation.get('affected_query_count', 0)}")

    # Phase 5: simulate a name-change event from recipe 5.7.
    print()
    print("-" * 70)
    print("Phase 5: simulate a name-change event from recipe 5.7")
    print("-" * 70)
    name_change = invalidate_on_event({
        "source":             "name_change_5_7",
        "event_id":           "evt-2026-05-22-001000",
        "patient_local_id":   "local-patient-internal-00874",
        "previous_last_name": "SMITH",
    })
    print(f"  source={name_change['source']} "
          f"actions={name_change['actions']}")

if __name__ == "__main__":
    run_demo()
```

Expected console output (the SQS / EventBridge / S3 / CloudWatch warnings appear in demo mode because the resources do not exist; they are harmless):

```
======================================================================
Cross-Facility Patient Matching Demo (HIE-scale)
======================================================================

All patients, organizations, and HIE responses in this demo
are fictional. The mock consent registry, sensitivity filter,
and partner orgs return hand-crafted responses that exercise
the full classification range; do not point this demo at a
live HIE.

Thresholds: HIGH=0.92, MED=0.80, REJECT=0.55

----------------------------------------------------------------------
Phase 1: process inbound queries
----------------------------------------------------------------------
  trauma-team query (high-confidence)                     status=MATCHED_HIGH_CONFIDENCE   conf=0.92   release=yes
  maiden-name query -> prior-name match                   status=MATCHED_MED_CONFIDENCE    conf=0.88   release=yes
  med-confidence + sensitivity-filter path                status=NO_MATCH_DEFERRED_REVIEW  conf=n/a    release=no
  research request from non-academic (rejected)           REJECTED reason=purpose_of_use_not_permitted
  no-match query                                          status=NO_CANDIDATE              conf=n/a    release=no

----------------------------------------------------------------------
Phase 2: simulate a consent-registry outage (fail-closed)
----------------------------------------------------------------------
  fail-closed result: status=MATCHED_MED_CONFIDENCE    release=False reason=consent_registry_unavailable

----------------------------------------------------------------------
Phase 3: outbound fan-out to partner orgs
----------------------------------------------------------------------
  partner=partner-org-academic-mc        status=OK         match_count=1
  partner=partner-org-urgent-care        status=OK         match_count=0

----------------------------------------------------------------------
Phase 4: simulate an invalidation trigger (consent revocation)
----------------------------------------------------------------------
  source=consent_revocation affected_query_count=2

----------------------------------------------------------------------
Phase 5: simulate a name-change event from recipe 5.7
----------------------------------------------------------------------
  source=name_change_5_7 actions=['append_prior_last_name']
```

Several patterns to notice:

- **Trigger #1 is the trauma-team happy path.** Full demographics agree across every feature; the composite score lands at the `AUTO_ACCEPT_HIGH_THRESHOLD`. Consent permits the requested data categories. The full set of requested categories releases (no sensitive-category filter on the requested list). The audit log records the query, the match decision, the consent check, the release decision, and the configuration version active at the time.
- **Trigger #2 demonstrates the recipe-5.7 prior-name path landing at medium confidence.** The query arrives with `Maria Garcia` (maiden name); the cross-org MPI has her as `Garcia-Lopez` with `Garcia` in `prior_last_names`. The blocking-key for `Garcia` (via the prior-name index) finds her, the last-name comparator scores 0.92 (prior-name match), and the composite score lands at 0.88, between MED and HIGH thresholds. This is the right outcome: a maiden-name match against a married-name record is exactly the case where the conservative cross-facility threshold says "probable match, but downgrade the release scope so a possibly-wrong match has limited blast radius." Consent permits treatment-purpose release; `reproductive_health` was never in the permitted-data-categories list (it is not in this jurisdiction's default category set), so it is dropped at the eligibility step and never reaches the sensitivity filter. The release proceeds with the high-value subset.
- **Trigger #3 demonstrates the deferred-review path.** Alex Johnson queried with a totally different address (the patient moved or the registration captured a wrong address); the address comparator drops to a low value, and the composite score lands between AUTO_REJECT and MED. The matcher returns `NO_MATCH_DEFERRED_REVIEW`, the requester gets a no-match response in real time (we do not block the clinician on human review), and the case is queued to the deferred-review queue for asynchronous resolution. This is the right conservative posture for ambiguous cross-facility matches.
- **Trigger #4 demonstrates the purpose-of-use rejection at ingest.** The urgent-care chain is not authorized for research-purpose queries; the request is rejected at the authentication-and-purpose layer before the matcher even runs. The audit log still records the rejection (production extends with an enumeration-attack-pattern detector that surfaces unusual rejection patterns to the security operations team).
- **Trigger #5 demonstrates the no-match path.** The query is for a patient not in our MPI. No candidates clear blocking, so the response is NO_CANDIDATE and no release occurs.
- **Phase 2 demonstrates the fail-closed posture.** The consent registry is simulated as unavailable. The matcher still runs and produces a (medium-confidence) match against the cached cross-org MPI, but the consent layer raises `ConsentRegistryUnavailable` and the release decision is `release=False, reason=consent_registry_unavailable`. The response back to the requester is a `TEMPORARY_UNAVAILABLE` indicator with `should_retry=True`. The audit log records the registry-unavailable separately so post-hoc consent verification has a complete record.
- **Phase 3 demonstrates the outbound fan-out pattern.** The local clinician's query goes out to two partner organizations; the academic medical center has a record (one match), the urgent-care chain does not (zero matches). The aggregating layer combines responses; in production the longitudinal-record-assembler stitches the matched records into a single clinician-facing view.
- **Phase 4 demonstrates the consent-revocation invalidation.** A patient revokes consent; the system finds the prior queries about that patient in the audit log (`affected_query_count=2` because both Phase 1 trigger #1 and Phase 2 outage query produced audit entries for this patient) and emits invalidation events so the requesting organizations can refresh their longitudinal records. In production the invalidation events feed downstream consumers via EventBridge.
- **Phase 5 demonstrates the recipe-5.7 name-change propagation.** A patient's name change feeds into the cross-org MPI as an append to `prior_last_names`, which the matcher uses to match future queries against both the new name and the old name. Without this propagation, queries with the old name would systematically fail to match the patient.

The cohort-bucket dimension on the CloudWatch metric is the substrate for the per-cohort accuracy monitoring discussed in the main recipe; production aggregates on `CohortBucket` and alarms on per-cohort disparities exceeding the institutional threshold.

---

## Gap to Production

What the demo intentionally skips, and what you would add for a real deployment:

**Replace `MockConsentRegistry` with the real consent-registry connector.** The registry is a major architectural dependency: HIE-provided in many cases, third-party vendor in some, institutional in others. Vet the registry for data-model completeness (purpose-of-use granularity, organization-specific permissions, data-category granularity, time-limited consent), availability (consent-check is on the critical path of every release), audit access, revocation-propagation latency, and patient-access (the patient has a right to see and modify their consent state). Wrap the connector in a circuit-breaker so a registry outage does not cascade into a generalized query-pipeline failure; the fail-closed posture handles each individual query, but the queue depth and Lambda concurrency need protection too.

**Replace `MockSensitivityFilter` with the real policy engine.** The sensitivity-filter policy is authored by compliance and legal teams with input from clinicians and the privacy officer, and it is versioned with deployment governance. The policy table encodes 42 CFR Part 2, state-specific behavioral health rules, HIV/STI sharing constraints, genetic information rules, and reproductive-health constraints in jurisdictions where they apply. Re-authoring is triggered by regulatory changes; deployments go through review, tests against gold cases, and an explicit version stamp that propagates into every audit record.

**Replace `MockPartnerOrg` with real partner connectivity.** Production uses HAPI FHIR or a vendor-supplied SDK to issue FHIR Patient `$match` operations to participating organizations and HIE intermediaries. Mutual TLS (mTLS) certificates from the institution's certificate authority, signed JWTs against the HIE's JWKS, or HIE-issued credentials drive the authentication. Outbound calls go through a NAT Gateway with an allow-list of partner endpoints, with PrivateLink where the partner offers it. Implement timeouts and partial-response handling so a slow partner does not block the aggregating layer.

**Real DynamoDB schema with the audit-log and cross-org-MPI tables.** The `cross-org-mpi` table is keyed on `local_patient_id` with a global secondary index on `cross_org_id` for reverse-lookup. The `audit-log` table is keyed on `(query_id, event_seq)` with an append-only access pattern enforced through IAM (no `dynamodb:DeleteItem`, no `dynamodb:UpdateItem` on existing items) plus DynamoDB resource-based policy. Provision both with on-demand capacity to handle the bursty pattern of clinical-workflow queries plus the steady volume of background linkage submissions.

**Real ElastiCache for Redis blocking-index cache.** The demo uses an in-process dict; production runs ElastiCache for Redis with in-transit encryption (TLS) and at-rest encryption (KMS). The blocking-index cache is loaded from DynamoDB at warm-up and refreshed incrementally as the MPI changes. Configure the cluster in VPC subnet groups with security groups restricting access to the cross-facility Lambdas only.

**FHIR Patient `$match` generation and parsing.** The demo passes Python dicts. Production builds proper FHIR Patient resources, packages them in the `$match` operation envelope, parses the response Bundle resources back into structured form, and handles the variation across FHIR R4 vs R5 vs the IHE PIXm/PDQm profiles. Use a maintained FHIR client library (`fhir.resources`, `fhirclient`) rather than rolling your own.

**IHE PIX/PDQ legacy connectivity for v2-only partners.** Many operational HIEs still have v2 PIX/PDQ as the broad-coverage path. Build a parallel connectivity path that uses HL7 v2 messaging (via Mirth Connect / NextGen Connect or equivalent) for partners that have not migrated to FHIR. The matching logic carries over; only the parsing and serialization layers differ.

**TransactWriteItems for atomic audit-and-release.** The demo writes the audit-log item, the S3 audit archive, the EventBridge event, and the response transmission in separate calls. A partial-failure scenario could leave the audit log out of sync with what was actually released. Production batches the audit-log put and an outbox-row put into a single TransactWriteItems call, with a Streams-driven consumer draining the outbox to EventBridge and to the response-transmission step so persistence is atomic with the eventual emit and release. The consequence here is sharper than in earlier chapter-5 recipes because the audit log is the legal record of cross-organizational data flow.

**Step Functions orchestration with retry, timeout, and DLQ.** Three workflows: query-time match (normalize, evaluate, consent + sensitivity, release + audit; calibrated to the realtime latency budget), linkage submission (parse CCD or FHIR Bundle, normalize, evaluate against MPI, persist match decision, propagate to downstream), and periodic MPI reconciliation (run periodically to compare local MPI against participating-orgs' aggregated demographic snapshots and detect drift). Each Lambda has a dedicated DLQ; Step Functions Catch states route terminal failures to the DLQ; CloudWatch alarms on DLQ depth surface stuck workflows.

**Idempotency keys on every write.** The demo uses `query_id` for query-level idempotency; production extends this: normalize at `query_id`, evaluate at `(query_id, matcher_config_version)`, consent-and-sensitivity at `(query_id, consent_state_etag)`, release-and-audit at `(query_id, event_seq)`, invalidate at `(event_id)`. Duplicate-event delivery from EventBridge or duplicate-invocation from Step Functions retries is routine; the pipeline must handle it without producing duplicate writes, duplicate releases, duplicate audit records, or inconsistent state.

**mTLS and signed-JWT validation on the inbound endpoint.** The demo trusts the asserted requester identity for readability; production validates the client certificate against the HIE's CA roster, or verifies the JWT signature against the HIE's JWKS, or both. AWS API Gateway mutual-TLS is the right substrate; combine with API Gateway resource policies for IP-allow-list and Lambda authorizers for purpose-of-use validation. Add WAF rules for rate-limiting per source IP and per authenticated principal, request-size limiting, and request-pattern analysis for enumeration-attack signatures.

**Threshold calibration and approval governance.** The auto-accept-high, auto-accept-med, and auto-reject thresholds are calibrated against an institutional gold set that reflects the cross-organizational query patterns. Re-calibration runs annually or on detection of cohort-stratified disparity above the institutional threshold (typical: 0.05). Each match outcome records `THRESHOLDS_VERSION` and `MATCHER_CONFIG_VERSION`. Promote candidate thresholds through institutional review (HIE-quality committee, compliance, clinical-safety, equity-monitoring committee) before going live.

**Cohort-stratified accuracy monitoring with disparity alarms.** The demo emits a per-cohort dimension on the metrics but does not aggregate or alarm. Production computes per-cohort match-success rate weekly, per-cohort review-queue rate weekly, per-cohort clinician-reported wrong-patient-retrieval rate monthly, per-cohort document-misfiling rate monthly. Disparity (best-rate minus worst-rate) thresholds: match-success > 0.05 = MEDIUM alarm; review-queue > 0.05 = MEDIUM; downstream wrong-patient > 0.01 = HIGH (clinical safety). Remediation (per-cohort threshold tuning, expanded synonyms and prior-name handling, partner-organization quality scorecards) is documented in a cohort-disparity ledger and reviewed quarterly.

**Deferred-review queue tooling.** The demo routes review-band cases to an SQS queue but does not provide a UI. Production builds a workflow tool that surfaces the query, the candidates, the score breakdown, the demographic context, and the decision options (confirm-match-and-update-MPI, reject-as-different-person, escalate, request-additional-information). The tool emits the reviewer's decision back into the matcher's training signal for periodic threshold re-calibration. Every review decision records the reviewer's identity, decision, stated reason, timestamp, and the configuration version active at the time, supporting forensic reconstruction when a wrong match is later traced back to a reviewer decision.

**Longitudinal-record-assembler integration.** The demo returns placeholder `<assembled_clinical_data_for_X>` strings. Production wires in a longitudinal-record-assembler that consumes the cross-facility match output, applies provenance and survivorship rules across multiple participating-org records, deduplicates clinical concepts, and presents the unified clinician-facing view. The assembler is its own subsystem; recipe 5.5's pipeline supplies the data substrate.

**Patient-access reports.** Patients have a right (under HIPAA, under TEFCA, under various state laws) to see who has queried about them, what was released, and to whom. The audit log is the source; the patient-access-report generator reads from the audit log and produces a patient-readable summary. Build this alongside the audit log as a first-class deliverable, not as a back-of-the-line compliance item; access reports are what makes the system trustworthy to patients.

**Initial backfill and onboarding.** Joining an HIE involves a one-time backfill: every patient in the institution's MPI is matched against the HIE's existing population to establish cross-organizational identifiers. This is a Glue/Spark job at scale, with cohort-stratified accuracy monitoring during the backfill (the backfill is a one-time opportunity to surface cohort issues at scale), suppression of routine event emission during the backfill (downstream consumers refresh from a single `cross_facility_backfill_complete` marker rather than millions of individual events), and governance approval at each stage.

**Real cohort-stratified backfill and bulk match-quality benchmarking.** Sequoia Project, ONC, and AHIMA have published patient-matching test datasets and benchmarking standards. Run periodic match-quality benchmarking against shared gold sets to calibrate against industry norms; participate in cross-organizational match-quality benchmarking with key partner organizations so the institution's matcher quality is known and trusted by partners.

**KMS-encrypted everything.** Customer-managed keys for the S3 buckets (raw-queries-and-responses, match-curated, audit-archive), the DynamoDB tables (cross-org-mpi, audit-log), the ElastiCache cluster, the SQS queues, the Lambda log groups, and the Secrets Manager HIE-and-partner-credential entries. Per-service KMS configuration is omitted for readability but is non-negotiable for the institution's standard PHI-handling posture.

**VPC + VPC endpoints.** Production runs Lambdas in VPC with VPC endpoints for S3 (gateway), DynamoDB (gateway), KMS, Secrets Manager, CloudWatch Logs, EventBridge, SQS, Step Functions, Glue, Athena, and STS. NAT Gateway only for the HIE-and-partner egress; restrict egress with security groups and an outbound proxy with an allow-list of HIE-and-partner endpoints. Evaluate AWS PrivateLink endpoints where the HIE intermediary or large-volume partner offers them.

**CloudTrail data events on the cross-org-MPI table, the audit-log table, and the audit S3 buckets.** Every read of the cross-org MPI is auditable activity; the data-events feature is not enabled by default and is the right level of granularity for the cross-facility substrate. Audit logs in a dedicated S3 bucket with Object Lock in Compliance mode for immutability, lifecycle policy transitioning to S3 Glacier Deep Archive after 90 days, retention floor enforced at the bucket-policy and Object-Lock-configuration level, not at application logic. Forward CloudTrail data events to a dedicated audit AWS account in the institution's organization, isolating the audit substrate from the production data plane. Retention is the longest of 7 years (HIPAA), the HIE's contractual retention, the state's medical-records-retention requirement, the 42 CFR Part 2 retention requirement (where Part 2 data is in scope), and any sensitive-category-specific retention.

**WAF, Shield, and enumeration-attack defense.** Cross-facility query endpoints are public-internet-reachable (or HIE-network-reachable) by definition and are attractive targets for enumeration attacks (an attacker submitting demographic guesses to discover whether a known person has records at the institution). WAF rules limit per-source-IP and per-authenticated-principal query rates; Shield protects against volumetric attacks; the audit log surfaces suspicious patterns; the institutional security operations team responds to suspected enumeration attempts with credential review and incident reporting.

**HIE participation agreement and trust framework operationalization.** The participation agreement is contractually-binding architectural input, not paperwork. Specify in code (or in versioned configuration) the permitted purposes-of-use per requesting organization, the retention obligations, the audit obligations, the minimum-acceptable-matcher-quality clauses, the partner data-handling commitments. Treat the participation agreement as the source of truth for what `_is_purpose_permitted` must allow and forbid.

**Compliance and operational ownership.** Cross-facility matching sits at the intersection of clinical IT, compliance, HIE participation, privacy, information security, and the institutional governance committees that own each. Establish clear operational ownership: who tunes the thresholds, who reviews the cohort-disparity reports, who handles partner-organization quality issues, who responds to consent-registry incidents, who owns the relationship with each partner organization. The pipeline works only when the operational ownership is clear and funded.

The pipeline is the easy part. The operational discipline (HIE participation agreement and trust framework, consent-registry selection and integration, sensitivity-filter policy authoring and governance, threshold calibration and approval governance, cohort-stratified equity monitoring, deferred-review queue tooling and reviewer auditing, longitudinal-record-assembler integration, patient-access-report generation, initial-backfill discipline, ongoing operational ownership) is what makes a cross-facility matching system produce accurate, fresh, usable matches year after year. Build for that.

---

*← [Recipe 5.5: Cross-Facility Patient Matching (HIE)](chapter05.05-cross-facility-patient-matching)*
