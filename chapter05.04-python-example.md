# Recipe 5.4: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 5.4. It shows one way you could translate the insurance-eligibility-matching pattern into working Python using a mock clearinghouse SDK (the demo includes a small `MockClearinghouse` class that mimics the response shape of vendors like Availity, Change Healthcare/Optum, and Waystar, since talking to a real clearinghouse requires a paid trading-partner agreement, BAA, and per-payer onboarding), Amazon DynamoDB for the eligibility-match store and the per-payer configuration, an in-process dict standing in for an Amazon ElastiCache Redis cluster, Amazon SQS for the inquiry queues, Amazon S3 for the audit archive, Amazon EventBridge for the eligibility-resolved and eligibility-invalidated events, and Amazon CloudWatch for operational metrics. It is not production-ready. There is no real X12 270/271 parser (the demo represents the inquiry and response as Python dicts that mirror the X12 segment shape), no real CAQH CORE Phase II compliance harness, no clearinghouse credentials in Secrets Manager, no Step Functions orchestration, no Glue/Spark batch reconciliation, no FHIR-based connectivity for payers offering it, no review-queue UI, no COB resolution module, no real cohort-stratified disparity dashboard, and no IAM, KMS, VPC, or CloudTrail wiring. Think of it as the sketchpad version: useful for understanding the shape of an eligibility-matching pipeline that respects the primary-key-vs-search-match distinction, the graded-confidence threshold-and-review-queue discipline, the cache-with-TTL freshness regime, and the audit-everything posture. It is not something you would point at a live registration system on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the six core pseudocode steps from the main recipe: ingest an eligibility-verification trigger from any source (registration event, scheduled pre-warm, batch reconciliation, charity-care screening, refresh-on-coverage-change); normalize the patient demographics for the target payer using payer-specific rules; submit the inquiry through the configured connectivity channel with retry and idempotency; evaluate the response and resolve identity using the same probabilistic-record-linkage scorer pattern from recipe 5.1, with confidence thresholds that route to AUTO_ACCEPT, AUTO_REJECT, or REVIEW_REQUIRED; persist the match outcome with provenance to DynamoDB and the cache and emit an `eligibility_resolved` event; and react to coverage-change signals by invalidating cached entries and queuing re-inquiries. The synthetic patients, payers, and member records in the demo are fictional; the addresses, member IDs, and DOBs are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also install the official SDK from your clearinghouse (Availity, Change Healthcare/Optum, Waystar, or equivalent), plus a real X12 parsing library such as [`pyx12`](https://github.com/azoner/pyx12) for the parsing piece even when transmission is delegated to the clearinghouse SDK. The demo replaces both with a small `MockClearinghouse` class that returns plausible 271-shaped responses for known synthetic inputs, so you can run the demo without a clearinghouse account.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the `eligibility-match` and `payer-config` tables (and on the `member-id-index` GSI on `eligibility-match` that supports the reverse-lookup-by-member-id pattern)
- `s3:PutObject` on the audit-archive bucket (for both the raw 270/271 payloads and the curated match outcomes)
- `sqs:SendMessage` and `sqs:ReceiveMessage` on the realtime-inquiry-queue, prewarm-inquiry-queue, and eligibility-review-queue
- `events:PutEvents` on the eligibility-events bus
- `cloudwatch:PutMetricData` for the match-outcome, per-payer-error, review-queue-depth, and cohort-disparity metrics
- `secretsmanager:GetSecretValue` on the clearinghouse and direct-payer credential secrets (production only; the mock clearinghouse does not need them)

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review.

A few things worth knowing upfront:

- **Eligibility data is PHI.** The 270 inquiry contains the patient's full demographics. The 271 response contains the patient's coverage detail and (often) financial-responsibility detail down to the dollar. Both are PHI and both are sensitive in different ways. Encrypt at rest with a customer-managed KMS key, encrypt in transit with TLS 1.2 or higher, and apply the same access discipline you would for the patient-matching infrastructure in recipe 5.1.
- **The clearinghouse is a Business Associate.** Each call sends PHI outside your VPC. The clearinghouse must have a BAA in place; the call must go through a controlled egress path (VPC endpoint where available, NAT Gateway with allow-list otherwise); the credentials must live in Secrets Manager, not in code or environment variables. The demo skips this wiring for readability but the production pattern is non-negotiable.
- **DynamoDB rejects Python `float`.** Every confidence score, copay amount, deductible balance, and numeric metadata field passes through `Decimal` on its way in and on its way out. Same gotcha as recipes 5.1 / 5.2 / 5.3; the same `_to_decimal` helper handles it.
- **Clearinghouse transactions are billable.** Each real-time inquiry costs roughly $0.05-0.25 depending on volume tier. The cache-and-pre-warm architecture exists to reduce the per-registration cost; if a downstream system loops or a configuration change re-inquires already-fresh entries, the bill spikes fast. Tag every inquiry with its originating workflow so cost anomalies are traceable.
- **Real-time eligibility is latency-sensitive.** The registration-flow target is sub-second cache-hit and a few hundred milliseconds for cache-miss. The CAQH CORE Phase II SLA is 20 seconds for the underlying X12 271, so cache-misses-that-trigger-async-resolution use a fail-open pattern: return "verification pending" to the registration UI immediately, complete the round-trip in the background, update the cache when the answer arrives. The demo implements the resolution synchronously for readability.
- **The example collapses Step Functions, multiple Lambdas, and the SQS-driven worker pattern into a single Python file for readability.** In production the normalize, submit, evaluate, persist, and invalidate stages are separate Lambdas orchestrated by Step Functions, each with their own error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the cache TTL policy, the auto-accept and auto-reject thresholds, the per-feature score weights, and the connectivity-channel selection are the knobs you would change between environments.

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
# CloudWatch Logs Insights. Eligibility data is PHI; log structural
# metadata only (patient_id, payer_id, inquiry_hash, status,
# decision), never raw demographics or member IDs.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from DynamoDB, EventBridge,
# CloudWatch, SQS, and the (real) clearinghouse API. Real-time
# inquiry has a tight latency budget; transient throttling from
# any one service should not fail the whole verification.
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
ELIGIBILITY_MATCH_TABLE  = "eligibility-match"
PAYER_CONFIG_TABLE       = "payer-config"
MEMBER_ID_INDEX          = "member-id-index"  # GSI on eligibility-match
AUDIT_BUCKET             = "my-eligibility-audit"
REALTIME_QUEUE_URL       = "https://sqs.us-east-1.amazonaws.com/000000000000/realtime-inquiry-queue"
PREWARM_QUEUE_URL        = "https://sqs.us-east-1.amazonaws.com/000000000000/prewarm-inquiry-queue"
REVIEW_QUEUE_URL         = "https://sqs.us-east-1.amazonaws.com/000000000000/eligibility-review-queue"
EVENTS_BUS_NAME          = "eligibility-events"
CLOUDWATCH_NAMESPACE     = "Eligibility/Matching"

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("ELIGIBILITY_MATCH_TABLE", ELIGIBILITY_MATCH_TABLE),
    ("PAYER_CONFIG_TABLE",      PAYER_CONFIG_TABLE),
    ("MEMBER_ID_INDEX",         MEMBER_ID_INDEX),
    ("AUDIT_BUCKET",            AUDIT_BUCKET),
    ("REALTIME_QUEUE_URL",      REALTIME_QUEUE_URL),
    ("PREWARM_QUEUE_URL",       PREWARM_QUEUE_URL),
    ("REVIEW_QUEUE_URL",        REVIEW_QUEUE_URL),
    ("EVENTS_BUS_NAME",         EVENTS_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",    CLOUDWATCH_NAMESPACE),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
NORMALIZER_VERSION = "elig-norm-v1.0"
SCORER_VERSION     = "elig-scorer-v1.0"
THRESHOLDS_VERSION = "elig-thresholds-v1.0"

# --- Confidence thresholds ---
# Calibrated against a labeled gold set in production. The numbers
# below are illustrative defaults; do not adopt them without
# calibration against your own population. Each match outcome
# records THRESHOLDS_VERSION so a future audit can reconstruct
# what cutoffs were active at the time of the decision.
AUTO_ACCEPT_THRESHOLD = Decimal("0.90")
AUTO_REJECT_THRESHOLD = Decimal("0.55")

# --- Per-feature score weights ---
# Composite score = weighted sum of feature scores, normalized to
# [0, 1]. Member-ID exact match dominates because the member ID
# is, when present and correct, the strongest signal the payer
# returned the right person. Name and DOB are the workhorses for
# search-match cases. Address and SSN are tie-breakers where
# present.
SCORE_WEIGHTS = {
    "member_id":     Decimal("0.40"),
    "first_name":    Decimal("0.10"),
    "last_name":     Decimal("0.15"),
    "dob":           Decimal("0.20"),
    "sex":           Decimal("0.05"),
    "address":       Decimal("0.05"),
    "ssn":           Decimal("0.05"),
}

# --- Cache TTL policy (in seconds) ---
# Service-date in the past is essentially settled (the payer's
# answer for a service that already happened doesn't change
# except in rare retroactive corrections). Service-date in the
# future is volatile (mid-month enrollment changes, plan changes,
# qualifying-event additions). The two regimes get very different
# TTLs.
CACHE_TTL_PAST_SECONDS   = 365 * 24 * 60 * 60  # ~ 1 year
CACHE_TTL_FUTURE_SECONDS = 24 * 60 * 60        # 24 hours

# --- Real-time inquiry timeout and retry ---
# Real-time gets a tight timeout and one retry; the registration
# flow cannot wait. Batch gets longer timeouts and gentler retry.
REALTIME_TIMEOUT_MS = 6000
BATCH_TIMEOUT_MS    = 20000
REALTIME_MAX_RETRIES = 1
BATCH_MAX_RETRIES    = 3


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
    """Recursive serialization helper. Same pattern as recipes 5.1, 5.2, 5.3."""
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

## A Mock Clearinghouse and Per-Payer Configuration

Production calls a real clearinghouse SDK here. The demo includes a small mock that returns plausible 271-shaped responses for known synthetic addresses, plus a generic best-effort response for unrecognized inputs. The response structure is modeled after the major clearinghouses' parsed-271 fields; the field names below are illustrative and the real clearinghouse SDK you license will have its own naming. The point of the mock is to exercise the downstream pipeline (classification, scoring, persistence, cache, events) without requiring a paid clearinghouse account.

The per-payer configuration table is also stubbed out as an in-memory dict for the demo. Each payer has subtly different formatting expectations for the 270 inquiry: name with or without suffix, member ID with or without dashes, dependent handling rules, supported service-type codes. In production these rules live in DynamoDB so they can be adjusted without a deploy and so changes can be governed and audited.

```python
# --- Synthetic per-payer configuration ---
# In production this lives in DynamoDB and is read at the start of
# each inquiry. The demo bakes a small registry of payers that
# exercise the variety of rules: a commercial PPO that supports
# primary-key match, a Medicaid plan that requires search match,
# and a self-funded TPA with strict dependent-handling rules.
SYNTHETIC_PAYER_CONFIG = {
    "payer-CIGNA-COMMERCIAL": {
        "payer_id":             "payer-CIGNA-COMMERCIAL",
        "display_name":         "Cigna Commercial PPO",
        "connectivity_model":   "x12_270_271",
        "channel":              "clearinghouse_primary",
        "expects_ssn":          False,
        "requires_person_code": False,
        "name_format":          "no_suffix",
        "date_format":          "YYYYMMDD",
        "member_id_format":     "no_dashes",
        "supported_service_types": ["30", "1", "98", "88"],
        "supports_primary_key_match": True,
        "supports_search_match":      True,
    },
    "payer-MEDICAID-STATE-X": {
        "payer_id":             "payer-MEDICAID-STATE-X",
        "display_name":         "State X Medicaid",
        "connectivity_model":   "x12_270_271",
        "channel":              "clearinghouse_primary",
        "expects_ssn":          True,
        "requires_person_code": False,
        "name_format":          "with_suffix",
        "date_format":          "YYYYMMDD",
        "member_id_format":     "raw",
        "supported_service_types": ["30", "1"],
        "supports_primary_key_match": False,  # search match only
        "supports_search_match":      True,
    },
    "payer-SELFFUNDED-TPA-Y": {
        "payer_id":             "payer-SELFFUNDED-TPA-Y",
        "display_name":         "Self-Funded Employer Plan via TPA Y",
        "connectivity_model":   "x12_270_271",
        "channel":              "clearinghouse_primary",
        "expects_ssn":          False,
        "requires_person_code": True,  # dependents need person code
        "name_format":          "no_suffix",
        "date_format":          "YYYYMMDD",
        "member_id_format":     "raw",
        "supported_service_types": ["30", "1", "98"],
        "supports_primary_key_match": True,
        "supports_search_match":      True,
    },
}


def _get_payer_config(payer_id: str) -> dict:
    """
    Read the per-payer config. Production reads from DynamoDB; the
    demo reads from the in-memory registry above and falls back to
    a permissive default for unknown payers.
    """
    cfg = SYNTHETIC_PAYER_CONFIG.get(payer_id)
    if cfg is not None:
        return cfg
    logger.warning("payer not in config; using clearinghouse default",
                    extra={"payer_id": payer_id})
    return {
        "payer_id":             payer_id,
        "display_name":         payer_id,
        "connectivity_model":   "x12_270_271",
        "channel":              "clearinghouse_primary",
        "expects_ssn":          False,
        "requires_person_code": False,
        "name_format":          "no_suffix",
        "date_format":          "YYYYMMDD",
        "member_id_format":     "raw",
        "supported_service_types": ["30"],
        "supports_primary_key_match": True,
        "supports_search_match":      True,
    }


class MockClearinghouse:
    """
    A stand-in for a real clearinghouse SDK. The response structure
    mimics what a parsed 271 looks like once the clearinghouse SDK
    has done the X12-to-Python conversion; you do not parse raw EDI
    here. Replace this with the real clearinghouse SDK in production.

    The mock recognizes a small set of synthetic member records
    keyed on (payer_id, member_id_or_search_key), and returns
    canned responses that exercise the full classification range:
    primary-key match, search match with single candidate, search
    match with multiple candidates, not found, partial response.
    """

    SOFTWARE_VERSION       = "mock-clearinghouse-v1.0"
    OPERATING_RULES_LEVEL  = "CAQH CORE Phase II"

    # Synthetic member roll. Production has nothing like this; the
    # payer's own member roll is in their system, and the
    # clearinghouse just routes the inquiry. The mock simulates
    # the payer-side roll for demo purposes.
    _MEMBER_ROLL = {
        # Cigna commercial: clean primary-key match.
        ("payer-CIGNA-COMMERCIAL", "U1234567890-01"): {
            "first_name": "JANE", "last_name": "DOE", "dob": "19800615",
            "sex": "F", "address_line_1": "1421 ELM ST APT 3B",
            "city": "ANYTOWN", "state": "ST", "zip": "12345",
            "ssn_last4": None,
            "subscriber_relationship": "self",
            "active": True, "plan_name": "Open Access PPO",
            "plan_id": "OAPPO-001",
            "effective_date": "20260101", "termination_date": None,
            "primary_care_copay": 25, "specialist_copay": 50,
            "deductible_individual": 1500,
            "deductible_individual_remaining": 875,
            "out_of_pocket_max_individual": 6000,
            "coinsurance_percent": 20,
            "is_primary": True,
            "provider_in_network": True,
        },
        # Cigna commercial: same patient with stale member ID
        # (mid-year plan change generated a new ID).
        ("payer-CIGNA-COMMERCIAL", "U9999000111-01"): {
            "first_name": "JANE", "last_name": "DOE", "dob": "19800615",
            "sex": "F", "address_line_1": "1421 ELM ST APT 3B",
            "city": "ANYTOWN", "state": "ST", "zip": "12345",
            "ssn_last4": None,
            "subscriber_relationship": "self",
            "active": True, "plan_name": "Open Access PPO 2025",
            "plan_id": "OAPPO-001-2025",
            "effective_date": "20250101", "termination_date": "20251231",
            "primary_care_copay": 25, "specialist_copay": 50,
            "deductible_individual": 1500, "deductible_individual_remaining": 0,
            "out_of_pocket_max_individual": 6000,
            "coinsurance_percent": 20,
            "is_primary": True, "provider_in_network": True,
        },
        # Self-funded TPA Y: subscriber.
        ("payer-SELFFUNDED-TPA-Y", "TPA-Y-1001-00"): {
            "first_name": "JOHN", "last_name": "SMITH", "dob": "19750322",
            "sex": "M", "address_line_1": "55 OAK AVE",
            "city": "ANYTOWN", "state": "ST", "zip": "12345",
            "ssn_last4": None,
            "subscriber_relationship": "self",
            "active": True, "plan_name": "Acme Corp Employee Plan",
            "plan_id": "ACME-EE-2026",
            "effective_date": "20260101", "termination_date": None,
            "primary_care_copay": 30, "specialist_copay": 60,
            "deductible_individual": 2000, "deductible_individual_remaining": 1500,
            "out_of_pocket_max_individual": 7500,
            "coinsurance_percent": 20,
            "is_primary": True, "provider_in_network": True,
        },
        # Self-funded TPA Y: dependent (requires person code in inquiry).
        ("payer-SELFFUNDED-TPA-Y", "TPA-Y-1001-01"): {
            "first_name": "EMILY", "last_name": "SMITH", "dob": "20100918",
            "sex": "F", "address_line_1": "55 OAK AVE",
            "city": "ANYTOWN", "state": "ST", "zip": "12345",
            "ssn_last4": None,
            "subscriber_relationship": "child",
            "subscriber_member_id": "TPA-Y-1001-00",
            "active": True, "plan_name": "Acme Corp Family Plan",
            "plan_id": "ACME-FAM-2026",
            "effective_date": "20260101", "termination_date": None,
            "primary_care_copay": 30, "specialist_copay": 60,
            "deductible_family": 4000, "deductible_individual_remaining": 4000,
            "out_of_pocket_max_family": 15000,
            "coinsurance_percent": 20,
            "is_primary": True, "provider_in_network": True,
        },
    }

    def submit_270(self, inquiry_payload: dict, timeout_ms: int = 6000,
                    idempotency_key: str = None) -> dict:
        """
        Mimic a clearinghouse submit() call. The inquiry_payload
        is the structured 270 we built upstream; the response
        mimics a parsed 271 with the matched member's coverage
        detail.
        """
        payer_id = inquiry_payload["payer_id"]
        member_id_to_query = inquiry_payload.get("member_id_to_query")
        first_name = (inquiry_payload.get("first_name") or "").upper()
        last_name = (inquiry_payload.get("last_name") or "").upper()
        dob = inquiry_payload.get("dob")

        # 1. Primary-key match path. If a member_id was supplied
        # and the payer has it on file, return the matched record.
        if member_id_to_query:
            member = self._MEMBER_ROLL.get((payer_id, member_id_to_query))
            if member:
                return self._build_271(payer_id, member, member_id_to_query,
                                         match_type="primary_key")
            # Member ID supplied but not found. Fall through to
            # search match if the demographics match anyone on file.

        # 2. Search-match path. Walk the member roll for this
        # payer and find candidates whose name and DOB roughly
        # agree.
        candidates = []
        for (roll_payer_id, roll_member_id), roll_member in self._MEMBER_ROLL.items():
            if roll_payer_id != payer_id:
                continue
            # Loose match: same DOB and last name initial agree.
            if (dob == roll_member["dob"]
                    and roll_member["last_name"][:1] == last_name[:1]
                    and (roll_member["first_name"][:1] == first_name[:1]
                         or first_name == "")):
                candidates.append((roll_member_id, roll_member))

        if len(candidates) == 0:
            return self._build_271_not_found(payer_id, member_id_to_query)

        if len(candidates) == 1:
            return self._build_271(payer_id, candidates[0][1], candidates[0][0],
                                     match_type="search_single")

        # Multiple candidates returned. The clearinghouse may
        # return them all and let the requester decide; some
        # payers pick a "best" and return only that.
        return self._build_271_multiple(payer_id, candidates)

    def _build_271(self, payer_id: str, member: dict, member_id: str,
                    match_type: str) -> dict:
        return {
            "status": "MATCHED",
            "payer_id": payer_id,
            "match_type": match_type,
            "matched_members": [{
                "member_id":  member_id,
                "first_name": member["first_name"],
                "last_name":  member["last_name"],
                "dob":        member["dob"],
                "sex":        member["sex"],
                "address": {
                    "line1": member.get("address_line_1"),
                    "city":  member.get("city"),
                    "state": member.get("state"),
                    "zip":   member.get("zip"),
                },
                "ssn_last4": member.get("ssn_last4"),
                "subscriber_relationship": member.get("subscriber_relationship"),
                "subscriber_member_id":   member.get("subscriber_member_id"),
                "active": member.get("active"),
                "plan_name": member.get("plan_name"),
                "plan_id":   member.get("plan_id"),
                "effective_date":   member.get("effective_date"),
                "termination_date": member.get("termination_date"),
                "financial_responsibility": {
                    "primary_care_copay":  member.get("primary_care_copay"),
                    "specialist_copay":    member.get("specialist_copay"),
                    "deductible_individual": member.get("deductible_individual"),
                    "deductible_individual_remaining":
                        member.get("deductible_individual_remaining"),
                    "deductible_family":   member.get("deductible_family"),
                    "out_of_pocket_max_individual":
                        member.get("out_of_pocket_max_individual"),
                    "out_of_pocket_max_family":
                        member.get("out_of_pocket_max_family"),
                    "coinsurance_percent": member.get("coinsurance_percent"),
                },
                "is_primary":            member.get("is_primary"),
                "provider_in_network":   member.get("provider_in_network"),
            }],
            "aaa_codes":           [],
            "rejection_codes":     [],
            "operating_rules_level": self.OPERATING_RULES_LEVEL,
            "software_version":    self.SOFTWARE_VERSION,
        }

    def _build_271_not_found(self, payer_id: str,
                                member_id_supplied: Optional[str]) -> dict:
        return {
            "status": "NOT_FOUND",
            "payer_id": payer_id,
            "match_type": "none",
            "matched_members": [],
            "aaa_codes": ["72"] if member_id_supplied else ["73"],
                # X12 271 AAA codes: 72 = invalid/missing subscriber
                # ID, 73 = invalid/missing subscriber name.
            "rejection_codes": [],
            "operating_rules_level": self.OPERATING_RULES_LEVEL,
            "software_version": self.SOFTWARE_VERSION,
        }

    def _build_271_multiple(self, payer_id: str, candidates: list) -> dict:
        """Return all candidates and let the requester decide."""
        members_block = []
        for (member_id, member) in candidates:
            members_block.append({
                "member_id":  member_id,
                "first_name": member["first_name"],
                "last_name":  member["last_name"],
                "dob":        member["dob"],
                "sex":        member["sex"],
                "address": {
                    "line1": member.get("address_line_1"),
                    "city":  member.get("city"),
                    "state": member.get("state"),
                    "zip":   member.get("zip"),
                },
                "ssn_last4": member.get("ssn_last4"),
                "subscriber_relationship": member.get("subscriber_relationship"),
                "active": member.get("active"),
                "plan_name": member.get("plan_name"),
                "plan_id":   member.get("plan_id"),
                "effective_date":   member.get("effective_date"),
                "termination_date": member.get("termination_date"),
            })
        return {
            "status": "MATCHED",
            "payer_id": payer_id,
            "match_type": "search_multiple",
            "matched_members": members_block,
            "aaa_codes": [],
            "rejection_codes": [],
            "operating_rules_level": self.OPERATING_RULES_LEVEL,
            "software_version": self.SOFTWARE_VERSION,
        }


# Module-level mock clearinghouse. In production, replace with
# the clearinghouse SDK constructed from credentials in
# Secrets Manager.
clearinghouse_sdk = MockClearinghouse()


# --- In-memory cache stand-in for ElastiCache Redis ---
# Keyed on (patient_id, payer_id, service_date). Holds the
# parsed match outcome with TTL so cache-hits skip DynamoDB.
# Production replaces this with ElastiCache; the dict here
# survives only as long as the Python process.
_REDIS_CACHE: dict = {}


def cache_get(patient_id: str, payer_id: str, service_date: str):
    key = f"{patient_id}#{payer_id}#{service_date}"
    entry = _REDIS_CACHE.get(key)
    if not entry:
        return None
    if datetime.now(timezone.utc) > entry["expires_at"]:
        del _REDIS_CACHE[key]
        return None
    return entry["item"]


def cache_set(patient_id: str, payer_id: str, service_date: str,
                item: dict, ttl_seconds: int) -> None:
    key = f"{patient_id}#{payer_id}#{service_date}"
    _REDIS_CACHE[key] = {
        "item": item,
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
    }


def cache_delete(patient_id: str, payer_id: str, service_date: str) -> None:
    key = f"{patient_id}#{payer_id}#{service_date}"
    _REDIS_CACHE.pop(key, None)


# --- In-memory eligibility-match registry stand-in for DynamoDB ---
# Keyed on (patient_id, payer_id, service_date). The demo
# populates this during the persist step and queries it during
# the read path; production uses the real eligibility-match
# DynamoDB table.
_IN_MEMORY_ELIGIBILITY: dict = {}
```

---

## Step 1: Ingest the Eligibility-Verification Trigger

*The pseudocode calls this `ingest_eligibility_trigger(trigger_event)`. Triggers come from registration events (real-time, latency-critical), scheduled pre-warm jobs (run nightly across tomorrow's appointments), batch reconciliation (monthly payer roster), charity-care screening, and refresh-on-coverage-change events. Each trigger produces a structured inquiry record with the patient, the payer, the service date, the requesting provider, the service-type codes, and the trigger metadata. Skip the trigger metadata and you lose the audit trail that lets you explain later why a particular inquiry was made and which workflow paid the clearinghouse fee.*

```python
def _archive_raw_to_s3(payload: dict, partition: str) -> None:
    """Best-effort archive to S3. Failures are logged and skipped (the demo prints what it would write)."""
    today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    key = (f"{partition}/{payload.get('payer_id', 'unknown')}/{today}/"
            f"{payload.get('inquiry_hash', uuid.uuid4().hex)}.json")
    body = json.dumps(payload, default=str).encode("utf-8")
    try:
        s3_client.put_object(
            Bucket=AUDIT_BUCKET,
            Key=key,
            Body=body,
            ServerSideEncryption="aws:kms",
        )
    except Exception as exc:
        logger.info("archive write skipped (demo mode is fine to ignore)",
                     extra={"key": key, "error": str(exc)})


def _derive_priority(trigger_event: dict) -> str:
    """Derive priority from the trigger reason if not explicitly set."""
    reason = trigger_event.get("reason", "")
    if reason == "registration":
        return "real_time"
    if reason in {"refresh_on_coverage_change", "charity_care_screening"}:
        return "high"
    if reason == "scheduled_prewarm":
        return "standard"
    return "standard"


def ingest_eligibility_trigger(trigger_event: dict) -> dict:
    """
    Capture the trigger into a consistent inquiry record and queue
    it for processing on the appropriate priority queue. The
    inquiry_hash is the idempotency key downstream; a second
    trigger for the same (patient, payer, service_date) within a
    short window dedupes against this hash.
    """
    inquiry = {
        "inquiry_id":   str(uuid.uuid4()),
        "patient_id":   trigger_event["patient_id"],
        "payer_id":     trigger_event["payer_id"],
        "service_date": trigger_event["service_date"],
        "service_type_codes": trigger_event.get("service_type_codes",
                                                  ["30"]),
            # X12 EQ01 codes; "30" = Health Benefit Plan Coverage
            # is the safe generic ask. "1" = Medical Care, "98" =
            # Professional Physician Visit, "88" = Pharmacy.
        "requesting_provider_npi": trigger_event.get("provider_npi",
                                                      "1234567890"),
            # Production looks up the institutional default NPI by
            # facility_id when the trigger does not supply one.
        "priority": (trigger_event.get("priority")
                       or _derive_priority(trigger_event)),
        "trigger_reason":          trigger_event.get("reason", "registration"),
        "trigger_source_record_id": trigger_event.get("source_record_id", ""),
        "triggered_at": _now_iso(),
    }

    # Idempotency hash. A second trigger for the same logical
    # inquiry within the deduplication window hits the same hash
    # and is dropped by the SQS deduplication layer in production
    # (FIFO queue with content-based deduplication, or explicit
    # MessageDeduplicationId).
    canon = _canonical_form(inquiry["patient_id"],
                              inquiry["payer_id"],
                              inquiry["service_date"],
                              "|".join(sorted(inquiry["service_type_codes"])))
    inquiry["inquiry_hash"] = _sha256(canon)

    # Archive the trigger record so we have provenance even if
    # the downstream pipeline is in flight when a question comes up.
    _archive_raw_to_s3({"trigger": trigger_event, "inquiry": inquiry},
                        partition="trigger-raw")

    # Route to the appropriate SQS queue. The realtime queue has
    # short visibility timeout and aggressive retry; the prewarm
    # queue is gentler. The demo logs the routing rather than
    # sending to a real queue.
    queue_url = (REALTIME_QUEUE_URL if inquiry["priority"] == "real_time"
                  else PREWARM_QUEUE_URL)
    try:
        sqs_client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(inquiry, default=str),
            MessageAttributes={
                "inquiry_hash": {
                    "DataType":    "String",
                    "StringValue": inquiry["inquiry_hash"],
                },
                "priority": {
                    "DataType":    "String",
                    "StringValue": inquiry["priority"],
                },
            },
        )
    except Exception as exc:
        logger.info("SQS send skipped (demo mode is fine to ignore)",
                     extra={"queue": queue_url, "error": str(exc)})

    _emit_metric("InquiryTriggered", 1.0,
                  dimensions={"Priority": inquiry["priority"],
                                "TriggerReason": inquiry["trigger_reason"]})

    return inquiry
```

---

## Step 2: Normalize the Patient Demographics for This Payer

*The pseudocode calls this `normalize_inquiry(inquiry)`. Each payer has slightly different formatting expectations: name with or without suffix, member ID with or without dashes, dependent-handling rules, supported service-type codes. The normalization layer applies payer-specific rules from the per-payer config table. Skip this and you get more "member not found" responses than necessary because the payer's matcher could not parse what you sent. Note that this is one of the few places where a small configuration error produces a silent quality regression rather than an outright failure: the inquiry succeeds, but the payer's match logic does not, and the patient ends up routed to the manual review path that the front desk has to staff.*

```python
def _format_name(name: str, name_format: str, suffix: Optional[str] = None) -> str:
    """Apply the payer's name-format rule."""
    if not name:
        return ""
    if name_format == "with_suffix" and suffix:
        return f"{name.upper()} {suffix.upper()}"
    return name.upper()


def _format_date(value: str, fmt: str) -> str:
    """Apply the payer's date-format rule. Input expected ISO-like."""
    if not value:
        return ""
    digits = re.sub(r"[^0-9]", "", value)[:8]
    if fmt == "YYYYMMDD":
        return digits
    if fmt == "YYYY-MM-DD" and len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return digits


def _format_member_id(member_id: Optional[str], fmt: str) -> Optional[str]:
    """Apply the payer's member-ID-format rule."""
    if not member_id:
        return None
    if fmt == "no_dashes":
        return member_id.replace("-", "")
    return member_id


def _select_member_id(coverage_history: list,
                        provided_member_id: Optional[str],
                        cfg: dict) -> Optional[str]:
    """
    Pick the best member ID to query. If the patient produced a
    card today (provided_member_id), prefer that. Otherwise use
    the most recent on-file member ID. If the payer does not
    support primary-key match, return None to force search match.
    """
    if not cfg["supports_primary_key_match"]:
        return None
    if provided_member_id:
        return provided_member_id
    if coverage_history:
        most_recent = sorted(coverage_history,
                              key=lambda c: c.get("captured_at", ""),
                              reverse=True)[0]
        return most_recent.get("member_id")
    return None


def _filter_service_types(requested: list, supported: list) -> list:
    """Strip unsupported service-type codes; substitute the closest supported."""
    out = [c for c in requested if c in supported]
    if not out:
        out = ["30"] if "30" in supported else (supported[:1] or ["30"])
    return out


def normalize_inquiry(inquiry: dict, patient_record: dict,
                       coverage_history: list,
                       provided_member_id: Optional[str] = None) -> dict:
    """
    Build the structured 270 inquiry payload tailored to the
    target payer's expectations. Returns the inquiry dict
    augmented with a `normalized` block and a `request_payload`
    suitable for the clearinghouse SDK.
    """
    cfg = _get_payer_config(inquiry["payer_id"])

    # 2A: derive the subscriber-vs-dependent relationship.
    is_dependent = bool(patient_record.get("subscriber_member_id"))
    relationship = "dependent" if is_dependent else "subscriber"

    # 2B: select the member ID to query.
    member_id_to_query = _select_member_id(coverage_history,
                                              provided_member_id, cfg)
    member_id_to_query = _format_member_id(member_id_to_query,
                                              cfg["member_id_format"])

    # 2C: build the normalized payload.
    normalized = {
        "subscriber_or_dependent":  relationship,
        "member_id_to_query":       member_id_to_query,
        "first_name":               _format_name(patient_record.get("first_name"),
                                                   cfg["name_format"]),
        "last_name":                _format_name(patient_record.get("last_name"),
                                                   cfg["name_format"],
                                                   patient_record.get("suffix")),
        "dob":                      _format_date(patient_record.get("dob"),
                                                   cfg["date_format"]),
        "sex":                      (patient_record.get("sex") or "").upper(),
        "address": {
            "line1": (patient_record.get("standardized_address") or {}).get("line1"),
            "city":  (patient_record.get("standardized_address") or {}).get("city"),
            "state": (patient_record.get("standardized_address") or {}).get("state"),
            "zip":   (patient_record.get("standardized_address") or {}).get("zip"),
        },
        "ssn":                      (patient_record.get("ssn")
                                       if cfg["expects_ssn"]
                                          and patient_record.get("ssn") else None),
        "subscriber_member_id":     (patient_record.get("subscriber_member_id")
                                       if is_dependent else None),
        "person_code":              (patient_record.get("person_code")
                                       if cfg["requires_person_code"]
                                          and is_dependent else None),
        "service_date":             _format_date(inquiry["service_date"],
                                                   cfg["date_format"]),
        "service_type_codes":       _filter_service_types(
                                          inquiry["service_type_codes"],
                                          cfg["supported_service_types"]),
        "provider_npi":             inquiry["requesting_provider_npi"],
        "connectivity_model":       cfg["connectivity_model"],
        "channel":                  cfg["channel"],
        "normalizer_version":       NORMALIZER_VERSION,
    }

    # 2D: build the request payload that goes to the
    # clearinghouse. Production builds an actual X12 270 envelope
    # via pyx12 or the clearinghouse SDK; the demo passes a dict
    # that the MockClearinghouse understands.
    request_payload = {
        "payer_id":            inquiry["payer_id"],
        "first_name":          normalized["first_name"],
        "last_name":           normalized["last_name"],
        "dob":                 normalized["dob"],
        "sex":                 normalized["sex"],
        "member_id_to_query":  normalized["member_id_to_query"],
        "service_date":        normalized["service_date"],
        "service_type_codes":  normalized["service_type_codes"],
        "provider_npi":        normalized["provider_npi"],
        "address":             normalized["address"],
        "ssn_last4":           (normalized["ssn"][-4:]
                                  if normalized["ssn"] else None),
    }

    # 2E: archive the normalized inquiry for audit. This is the
    # artifact that lets you reconstruct what you submitted to
    # the payer when a question comes up later.
    _archive_raw_to_s3({
        "inquiry_hash":      inquiry["inquiry_hash"],
        "payer_id":          inquiry["payer_id"],
        "normalized":        normalized,
        "request_payload":   request_payload,
    }, partition="inquiry-curated")

    inquiry["normalized"] = normalized
    inquiry["request_payload"] = request_payload
    return inquiry
```

---

## Step 3: Submit the Inquiry Through the Connectivity Layer

*The pseudocode calls this `submit_inquiry(inquiry)`. Real-time inquiries call the clearinghouse or direct-payer API and wait for the synchronous 271 response. The connectivity layer handles authentication, retries with exponential backoff, timeout (calibrated to the response-time SLA), and idempotency on the inquiry hash. Skip retry-and-idempotency and you get duplicate transactions on transient failures, which clearinghouses charge for and which can produce confusing duplicate match outcomes.*

```python
def submit_inquiry(inquiry: dict) -> dict:
    """
    Submit through the (mock) clearinghouse with timeout and
    bounded retry. The raw response is archived to S3 and the
    parsed response is attached to the inquiry for the next
    stage.
    """
    is_realtime = inquiry["priority"] == "real_time"
    timeout_ms = REALTIME_TIMEOUT_MS if is_realtime else BATCH_TIMEOUT_MS
    max_retries = REALTIME_MAX_RETRIES if is_realtime else BATCH_MAX_RETRIES

    response = None
    last_error = None
    for attempt in range(1, max_retries + 2):
        try:
            response = clearinghouse_sdk.submit_270(
                inquiry_payload=inquiry["request_payload"],
                timeout_ms=timeout_ms,
                idempotency_key=inquiry["inquiry_hash"],
            )
            break  # success
        except TimeoutError as exc:
            last_error = ("TIMEOUT", str(exc))
            logger.warning("inquiry timeout",
                            extra={"inquiry_id": inquiry["inquiry_id"],
                                   "attempt": attempt})
        except Exception as exc:
            # Protocol-level error: do not retry. Production
            # distinguishes retriable transport errors from
            # non-retriable protocol errors more carefully.
            last_error = ("PROTOCOL_ERROR", str(exc))
            logger.warning("inquiry protocol error",
                            extra={"inquiry_id": inquiry["inquiry_id"],
                                   "attempt": attempt,
                                   "error": str(exc)})
            break

    if response is None:
        response = {"status": last_error[0] if last_error else "TIMEOUT",
                     "error": last_error[1] if last_error else "no response"}

    # Archive the raw response. The 271 is the legal record of
    # what the payer told you; preserve it exactly as received.
    _archive_raw_to_s3({
        "inquiry_hash": inquiry["inquiry_hash"],
        "payer_id":     inquiry["payer_id"],
        "request":      inquiry["request_payload"],
        "response":     response,
    }, partition="270-271-raw")

    inquiry["response"] = response
    return inquiry
```

---

## Step 4: Evaluate the Response and Resolve Identity

*The pseudocode calls this `evaluate_response(inquiry)`. The 271 response comes back with one of several outcomes: primary-key matched, search match returned, search match with multiple candidates, not found, rejected, or partial. The evaluator parses the response, runs the probabilistic-record-linkage scorer against the candidate(s), and applies confidence thresholds. Skip this and you trust the payer's match decision blindly, which is wrong about a measurable fraction of the time. In particular, search-match candidates need scoring on your side too because the payer's matcher does not see the same demographic context yours does (you have the standardized address from recipe 5.3, the prior-name signal from recipe 5.7, the SSN where collected; the payer often does not).*

```python
def _jaro_winkler(a: str, b: str) -> float:
    """
    Lightweight Jaro-Winkler implementation. Production uses a
    well-tested library (rapidfuzz, jellyfish) so the algorithm
    is the reference implementation rather than this sketch.
    """
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Jaro distance
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
            if s2_matches[j]:
                continue
            if s2[j] != c:
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
    # Winkler boost on common prefix, capped at 4.
    prefix = 0
    for i in range(min(4, len1, len2)):
        if s1[i] == s2[i]:
            prefix += 1
        else:
            break
    return jaro + (prefix * 0.1 * (1 - jaro))


def _name_similarity(query: str, candidate: str) -> Decimal:
    """Wrapper around Jaro-Winkler that returns Decimal in [0, 1]."""
    return _to_decimal(_jaro_winkler((query or "").upper(),
                                       (candidate or "").upper()))


def _dob_match(query_dob: str, candidate_dob: str) -> Decimal:
    """Grade DOB match: exact / year-month / year / mismatch."""
    q = re.sub(r"[^0-9]", "", query_dob or "")[:8]
    c = re.sub(r"[^0-9]", "", candidate_dob or "")[:8]
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
    """Sex match: exact, unknown-on-either-side neutral, mismatch."""
    if not q or not c:
        return Decimal("0.5")
    return Decimal("1.0") if q.upper() == c.upper() else Decimal("0.0")


def _address_similarity(query_addr: dict, candidate_addr: dict) -> Decimal:
    """Coarse address similarity: ZIP match + street similarity."""
    if not query_addr or not candidate_addr:
        return Decimal("0.5")  # neutral when one side is missing
    q_zip = (query_addr.get("zip") or "")[:5]
    c_zip = (candidate_addr.get("zip") or "")[:5]
    zip_match = Decimal("1.0") if q_zip and q_zip == c_zip else Decimal("0.0")
    q_street = (query_addr.get("line1") or "").upper()
    c_street = (candidate_addr.get("line1") or "").upper()
    street_sim = _to_decimal(_jaro_winkler(q_street, c_street))
    return (zip_match * Decimal("0.5")) + (street_sim * Decimal("0.5"))


def _ssn_match(q: Optional[str], c_last4: Optional[str]) -> Decimal:
    """SSN match comparing the candidate's last-4 against ours."""
    if not q or not c_last4:
        return Decimal("0.5")  # neutral when one side is missing
    q_last4 = re.sub(r"[^0-9]", "", q)[-4:]
    return Decimal("1.0") if q_last4 == c_last4 else Decimal("0.0")


def _member_id_match(query_member_id: Optional[str],
                       candidate_member_id: str,
                       coverage_history: list) -> Decimal:
    """
    Member-ID match grade: exact (current) / partial (suffix
    differs) / historical (matches a prior on-file ID) / mismatch.
    Member IDs change at plan changes; matching against the
    historical list catches cases where the practice's records
    are one plan-cycle behind.
    """
    if not query_member_id or not candidate_member_id:
        return Decimal("0.0") if query_member_id != candidate_member_id else Decimal("0.5")
    q = query_member_id.upper().replace("-", "")
    c = candidate_member_id.upper().replace("-", "")
    if q == c:
        return Decimal("1.0")
    # Partial match: same first 8-10 chars (suffix differs)
    if len(q) >= 8 and len(c) >= 8 and q[:8] == c[:8]:
        return Decimal("0.7")
    # Historical: does it match anything in coverage_history?
    for hist in coverage_history or []:
        hist_id = (hist.get("member_id") or "").upper().replace("-", "")
        if hist_id and hist_id == c:
            return Decimal("0.6")
    return Decimal("0.0")


def _composite_score(features: dict) -> Decimal:
    """Weighted sum of feature scores, normalized to [0, 1]."""
    total_weight = sum(SCORE_WEIGHTS.values())
    weighted = sum(SCORE_WEIGHTS[k] * features[k] for k in SCORE_WEIGHTS)
    return weighted / total_weight


def _interpret_not_found(parsed: dict, inquiry: dict) -> str:
    """Best-effort interpretation of why the payer said not-found."""
    aaa_codes = parsed.get("aaa_codes", [])
    member_id_supplied = bool(inquiry["normalized"].get("member_id_to_query"))
    if "72" in aaa_codes:
        return ("wrong_member_id_supplied" if member_id_supplied
                 else "indeterminate_no_id_supplied")
    if "73" in aaa_codes:
        return "wrong_or_unmatched_demographics"
    if "75" in aaa_codes:
        return "wrong_dob"
    return "indeterminate"


def evaluate_response(inquiry: dict, patient_record: dict,
                       coverage_history: list) -> dict:
    """
    Evaluate the parsed 271 response, score candidates, apply
    confidence thresholds, and return a structured match outcome.
    """
    response = inquiry["response"]

    # 4A: handle protocol-level outcomes that don't need
    # identity resolution.
    if response.get("status") in {"TIMEOUT", "PROTOCOL_ERROR"}:
        return {
            "status":          "INQUIRY_FAILED",
            "failure_reason":  response.get("status"),
            "requires_retry":  True,
            "scorer_version":  SCORER_VERSION,
            "thresholds_version": THRESHOLDS_VERSION,
        }

    # 4B: branch by response type.
    if response.get("status") == "NOT_FOUND":
        return {
            "status":              "NOT_FOUND",
            "payer_response_code": response.get("aaa_codes"),
            "interpretation":      _interpret_not_found(response, inquiry),
            "scorer_version":      SCORER_VERSION,
            "thresholds_version":  THRESHOLDS_VERSION,
        }

    if response.get("rejection_codes"):
        return {
            "status":           "REJECTED",
            "rejection_reason": response.get("rejection_codes"),
            "requires_review":  True,
            "scorer_version":   SCORER_VERSION,
            "thresholds_version": THRESHOLDS_VERSION,
        }

    candidates = response.get("matched_members", [])
    if not candidates:
        return {
            "status":         "NOT_FOUND",
            "interpretation": "indeterminate",
            "scorer_version": SCORER_VERSION,
            "thresholds_version": THRESHOLDS_VERSION,
        }

    # 4C: score each candidate using the same probabilistic-record-
    # linkage core as recipe 5.1, with eligibility-specific feature
    # weights.
    normalized = inquiry["normalized"]
    scored = []
    for cand in candidates:
        features = {
            "first_name": _name_similarity(normalized["first_name"],
                                              cand.get("first_name")),
            "last_name":  _name_similarity(normalized["last_name"],
                                              cand.get("last_name")),
            "dob":        _dob_match(normalized["dob"], cand.get("dob")),
            "sex":        _sex_match(normalized["sex"], cand.get("sex")),
            "address":    _address_similarity(normalized["address"],
                                                 cand.get("address")),
            "ssn":        _ssn_match(normalized.get("ssn"),
                                       cand.get("ssn_last4")),
            "member_id":  _member_id_match(normalized["member_id_to_query"],
                                              cand.get("member_id"),
                                              coverage_history),
        }
        composite = _composite_score(features)
        scored.append({
            "candidate":  cand,
            "features":   features,
            "composite":  composite,
        })

    # 4D: pick the best candidate.
    best = max(scored, key=lambda s: s["composite"])

    # 4E: cohort-stratified telemetry. Every match outcome
    # contributes to the per-cohort metrics. The cohort label is
    # a bucketed non-reversible label, not a raw demographic
    # attribute (see expert review guidance in the main recipe).
    cohort_bucket = patient_record.get("cohort_bucket", "unknown")
    _emit_metric("EligibilityMatchScore", float(best["composite"]),
                  dimensions={"PayerId": inquiry["payer_id"],
                                "CohortBucket": cohort_bucket})

    # 4F: apply confidence thresholds.
    if best["composite"] >= AUTO_ACCEPT_THRESHOLD:
        # Decide match_method label based on response shape.
        if response.get("match_type") == "primary_key":
            method = "primary_key"
        elif response.get("match_type") == "search_single":
            method = "search_high_confidence"
        else:
            method = "search_returned_multiple_best_picked"
        outcome = {
            "status":              "MATCHED",
            "matched_member_id":   best["candidate"]["member_id"],
            "match_confidence":    best["composite"],
            "match_method":        method,
            "matched_member":      best["candidate"],
            "feature_scores":      best["features"],
            "scorer_version":      SCORER_VERSION,
            "thresholds_version":  THRESHOLDS_VERSION,
        }
    elif best["composite"] <= AUTO_REJECT_THRESHOLD:
        outcome = {
            "status":              "NOT_MATCHED_AUTO",
            "best_candidate":      best["candidate"],
            "best_candidate_score": best["composite"],
            "interpretation": "payer_returned_record_but_does_not_match",
            "scorer_version":      SCORER_VERSION,
            "thresholds_version":  THRESHOLDS_VERSION,
        }
    else:
        outcome = {
            "status":              "REVIEW_REQUIRED",
            "best_candidate":      best["candidate"],
            "best_candidate_score": best["composite"],
            "other_candidates":    [s["candidate"] for s in scored
                                       if s is not best],
            "review_reason":       _characterize_uncertainty(best["features"]),
            "scorer_version":      SCORER_VERSION,
            "thresholds_version":  THRESHOLDS_VERSION,
        }

    _emit_metric("EligibilityMatchOutcome", 1.0,
                  dimensions={"Status": outcome["status"],
                                "PayerId": inquiry["payer_id"],
                                "CohortBucket": cohort_bucket})
    return outcome


def _characterize_uncertainty(features: dict) -> str:
    """Human-readable hint about why a match landed in the review band."""
    if features["dob"] < Decimal("0.7"):
        return "dob_off_or_missing"
    if features["last_name"] < Decimal("0.7"):
        return "last_name_off"
    if features["address"] < Decimal("0.5"):
        return "address_off"
    return "name_similar_but_not_strong"
```

---

## Step 5: Persist the Match Outcome and Propagate

*The pseudocode calls this `persist_and_propagate(inquiry, match_outcome)`. Write the match outcome to DynamoDB (and the cache), archive to S3, emit an EventBridge event if the outcome changed. Downstream consumers (practice management, revenue cycle, charity-care, care management, patient portal) pick up the event and update their views. Skip the event emission and downstream consumers either pull on a stale cache or block on the eligibility lookup, defeating the purpose of the asynchronous pipeline.*

```python
def _derive_cache_ttl(service_date: str) -> int:
    """Pick the cache TTL based on whether the service date is past or future."""
    try:
        digits = re.sub(r"[^0-9]", "", service_date)[:8]
        sd = datetime.strptime(digits, "%Y%m%d").date()
    except Exception:
        return CACHE_TTL_FUTURE_SECONDS  # safe default
    today = datetime.now(timezone.utc).date()
    return (CACHE_TTL_PAST_SECONDS if sd < today
              else CACHE_TTL_FUTURE_SECONDS)


def persist_and_propagate(inquiry: dict, match_outcome: dict) -> dict:
    """
    Persist the match outcome to DynamoDB (or the in-memory
    fallback in the demo), write to the cache, archive to S3,
    emit the eligibility_resolved event when the outcome
    changed, and route to the review queue if applicable.
    """
    patient_id   = inquiry["patient_id"]
    payer_id     = inquiry["payer_id"]
    service_date = inquiry["service_date"]
    sort_key     = f"{payer_id}#{service_date}"

    # 5A: read the previous outcome so we can detect changes.
    previous = None
    try:
        resp = dynamodb.Table(ELIGIBILITY_MATCH_TABLE).get_item(
            Key={"patient_id": patient_id,
                  "payer_payer_service_date_sort": sort_key},
        )
        previous = resp.get("Item")
    except Exception as exc:
        # In demo mode without a real table: fall back to the
        # in-memory registry.
        logger.info("previous read skipped (demo mode)",
                     extra={"error": str(exc)})
        previous = _IN_MEMORY_ELIGIBILITY.get((patient_id, payer_id, service_date))

    previous_status = ((previous or {}).get("match_outcome") or {}).get("status")
    previous_member_id = ((previous or {}).get("match_outcome") or {}).get("matched_member_id")

    # TODO (TechWriter): Expert review A1 (HIGH). Wrap the
    # DynamoDB write, the cache write, the S3 audit write, and
    # the EventBridge emit in a TransactWriteItems plus an
    # outbox row drained by a separate Lambda or DynamoDB
    # Streams consumer so partial failures cannot leave the
    # eligibility store out of sync with downstream consumers.
    # Same chapter pattern as 5.1 / 5.2 / 5.3 Finding A1; the
    # consequence here is sharper because the eligibility
    # outcome directly drives revenue cycle, charity-care, and
    # patient financial responsibility.

    # 5B: write the current match outcome.
    cache_ttl = _derive_cache_ttl(service_date)
    item = _serialize_for_dynamodb({
        "patient_id":                      patient_id,
        "payer_payer_service_date_sort":   sort_key,
        "payer_id":                        payer_id,
        "service_date":                    service_date,
        "match_outcome":                   match_outcome,
        "inquiry_hash":                    inquiry["inquiry_hash"],
        "inquiry_id":                      inquiry["inquiry_id"],
        "previous_status":                 previous_status,
        "resolved_at":                     _now_iso(),
        "cache_ttl":                       cache_ttl,
    })
    try:
        dynamodb.Table(ELIGIBILITY_MATCH_TABLE).put_item(Item=item)
    except Exception as exc:
        logger.info("eligibility put skipped (demo mode)",
                     extra={"error": str(exc)})
    # In-memory fallback so the demo's read path still works.
    _IN_MEMORY_ELIGIBILITY[(patient_id, payer_id, service_date)] = item

    # 5C: write to cache.
    cache_set(patient_id, payer_id, service_date, item, ttl_seconds=cache_ttl)

    # 5D: archive to S3.
    _archive_raw_to_s3({
        "type":           "match_outcome",
        "patient_id":     patient_id,
        "payer_id":       payer_id,
        "service_date":   service_date,
        "inquiry_hash":   inquiry["inquiry_hash"],
        "match_outcome":  _serialize_for_dynamodb(match_outcome),
    }, partition="match-curated")

    # 5E: emit eligibility_resolved when the outcome changed.
    new_status = match_outcome.get("status")
    new_member_id = match_outcome.get("matched_member_id")
    outcome_changed = (previous_status != new_status
                         or previous_member_id != new_member_id)
    if outcome_changed:
        try:
            eventbridge_client.put_events(Entries=[{
                "Source":       "eligibility-matching",
                "DetailType":   "eligibility_resolved",
                "EventBusName": EVENTS_BUS_NAME,
                "Detail": json.dumps({
                    "patient_id":            patient_id,
                    "payer_id":              payer_id,
                    "service_date":          service_date,
                    "inquiry_id":            inquiry["inquiry_id"],
                    "outcome_status":        new_status,
                    "matched_member_id":     new_member_id,
                    "match_confidence":      str(match_outcome.get(
                                                  "match_confidence", "")),
                    "previous_outcome_status": previous_status,
                    "resolved_at":           _now_iso(),
                }, default=str),
            }])
        except Exception as exc:
            logger.info("event emit skipped (demo mode)",
                         extra={"error": str(exc)})

    # 5F: route to the review queue if required.
    if new_status == "REVIEW_REQUIRED":
        review_priority = ("high" if inquiry["priority"] == "real_time"
                              else "standard")
        try:
            sqs_client.send_message(
                QueueUrl=REVIEW_QUEUE_URL,
                MessageBody=json.dumps({
                    "patient_id":           patient_id,
                    "payer_id":             payer_id,
                    "service_date":         service_date,
                    "inquiry_id":           inquiry["inquiry_id"],
                    "best_candidate_score": str(match_outcome.get(
                                                  "best_candidate_score", "")),
                    "review_reason":        match_outcome.get("review_reason"),
                    "priority":             review_priority,
                }, default=str),
            )
        except Exception as exc:
            logger.info("review queue send skipped (demo mode)",
                         extra={"error": str(exc)})

    return item
```

---

## Step 6: React to Coverage-Change Signals and Invalidate Cached Eligibility

*The pseudocode calls this `invalidate_on_coverage_change(change_event)`. Eligibility data changes constantly: monthly payer roster deltas, 277/277CA claim status responses indicating eligibility issues, 834 enrollment files, patient-side events from recipes 5.1 (merge) and 5.3 (address change). The system subscribes to these signals and invalidates affected cache entries, then re-queues the inquiry for asynchronous re-resolution. Skip the invalidation pipeline and the cache slowly fills up with stale answers; revenue cycle starts seeing claim denials for coverage that the cache thought was active.*

```python
def invalidate_on_coverage_change(change_event: dict) -> dict:
    """
    Process a coverage-change signal, invalidate affected cache
    entries, and re-queue the inquiry for asynchronous
    re-resolution. Returns a small summary dict.
    """
    affected = []
    source = change_event.get("source")

    today_iso = datetime.now(timezone.utc).date().isoformat()

    if source == "payer-roster-delta":
        # Monthly roster comparison surfaced a member who is no
        # longer in the roster (or whose coverage dates changed).
        # Invalidate any cached match for future service dates.
        affected.append({
            "patient_id":           change_event["affected_patient_id"],
            "payer_id":             change_event["payer_id"],
            "service_date_filter":  "future",
        })
    elif source == "claim-status-277":
        # A 277CA claim-status response indicated an eligibility
        # issue. Invalidate the cache and force re-inquiry. Past
        # service dates also re-inquire because the claim denial
        # says the prior match outcome was wrong.
        affected.append({
            "patient_id":           change_event["affected_patient_id"],
            "payer_id":             change_event["payer_id"],
            "service_date_filter":  "all",
        })
    elif source == "834-enrollment-file":
        affected.append({
            "patient_id":           change_event["affected_patient_id"],
            "payer_id":             change_event["payer_id"],
            "service_date_filter":  "future",
        })
        for dep_id in change_event.get("affected_dependent_ids", []):
            affected.append({
                "patient_id":           dep_id,
                "payer_id":             change_event["payer_id"],
                "service_date_filter":  "future",
            })
    elif source == "patient-merge-event":
        # Recipe 5.1 merged two patient records; eligibility may
        # be cached under the old patient_id. Invalidate both.
        affected.append({
            "patient_id":            change_event["merged_into_patient_id"],
            "payer_id":              "*",
            "service_date_filter":   "all",
            "also_invalidate_patient_id":
                change_event["merged_from_patient_id"],
        })
    elif source == "address-change":
        # Recipe 5.3 address change. The matcher used the old
        # address as a signal; if the change indicates the
        # patient moved states, the network-status answer may
        # have changed.
        affected.append({
            "patient_id":           change_event["patient_id"],
            "payer_id":             "*",
            "service_date_filter":  "future",
        })

    invalidated_count = 0
    requeued_count = 0
    for key in affected:
        # Walk the in-memory eligibility registry to enumerate
        # the (patient_id, payer_id, service_date) entries that
        # match the filter. Production runs a DynamoDB Query
        # plus a service_date predicate.
        for (pid, payer, sdate), entry in list(_IN_MEMORY_ELIGIBILITY.items()):
            if pid != key["patient_id"] and pid != key.get(
                    "also_invalidate_patient_id"):
                continue
            if key["payer_id"] != "*" and payer != key["payer_id"]:
                continue
            if key["service_date_filter"] == "future" and sdate < today_iso:
                continue
            cache_delete(pid, payer, sdate)
            invalidated_count += 1

            # Mark the registry entry for re-inquiry. Production
            # sets requires_reinquiry=True via DynamoDB
            # UpdateItem; the read path checks the flag and
            # serves a "verification pending" response while
            # the re-inquiry runs.
            entry["requires_reinquiry"] = True

            # Re-queue the affected (patient, payer, service_date)
            # for async re-resolution on the prewarm queue.
            re_inquiry_trigger = {
                "patient_id":         pid,
                "payer_id":           payer,
                "service_date":       sdate,
                "service_type_codes": ["30"],
                "reason":              "refresh_on_coverage_change",
                "source_record_id":    f"{source}#{change_event.get('event_id', '')}",
                "priority":            "high",
            }
            try:
                ingest_eligibility_trigger(re_inquiry_trigger)
                requeued_count += 1
            except Exception as exc:
                logger.warning("re-queue failed",
                                extra={"error": str(exc)})

    # Emit eligibility_invalidated for downstream awareness.
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "eligibility-matching",
            "DetailType":   "eligibility_invalidated",
            "EventBusName": EVENTS_BUS_NAME,
            "Detail": json.dumps({
                "change_event_source": source,
                "change_event_id":     change_event.get("event_id"),
                "affected_keys":       affected,
                "invalidated_count":   invalidated_count,
                "requeued_count":      requeued_count,
                "invalidated_at":      _now_iso(),
            }, default=str),
        }])
    except Exception as exc:
        logger.info("invalidation event emit skipped (demo mode)",
                     extra={"error": str(exc)})

    _emit_metric("EligibilityCacheInvalidations", invalidated_count,
                  dimensions={"Source": source or "unknown"})

    return {
        "source":             source,
        "affected_keys":      affected,
        "invalidated_count":  invalidated_count,
        "requeued_count":     requeued_count,
    }
```

---

## Full Pipeline

The pipeline assembles the six steps into a single callable function. In production these are separate Lambdas (and Glue stages for batch reconciliation) orchestrated by Step Functions; here we run them in-process so the trace is easy to follow. The full demo also seeds a small in-memory patient registry so the normalization, scoring, and persist steps have realistic data to work with.

```python
# Synthetic patient master records keyed by patient_id. Production
# reads from the MPI / active registration record. The records
# below are obviously fictional.
PATIENT_MASTER = {
    "patient-internal-00874": {
        "patient_id": "patient-internal-00874",
        "first_name": "Jane", "last_name": "Doe", "suffix": None,
        "dob": "1980-06-15", "sex": "F",
        "ssn": "123-45-6789",
        "standardized_address": {
            "line1": "1421 ELM ST APT 3B", "city": "ANYTOWN",
            "state": "ST", "zip": "12345",
        },
        "cohort_bucket": "A",
    },
    # Same patient with stale on-file member ID (mid-year plan
    # change generated a new ID; demonstrates the historical-ID
    # match path).
    "patient-internal-00875": {
        "patient_id": "patient-internal-00875",
        "first_name": "Jane", "last_name": "Doe", "suffix": None,
        "dob": "1980-06-15", "sex": "F",
        "ssn": "123-45-6789",
        "standardized_address": {
            "line1": "1421 ELM ST APT 3B", "city": "ANYTOWN",
            "state": "ST", "zip": "12345",
        },
        "cohort_bucket": "A",
    },
    # Self-funded TPA dependent. Person-code required.
    "patient-internal-01001": {
        "patient_id": "patient-internal-01001",
        "first_name": "Emily", "last_name": "Smith", "suffix": None,
        "dob": "2010-09-18", "sex": "F",
        "ssn": None,
        "subscriber_member_id": "TPA-Y-1001-00",
        "person_code": "01",
        "standardized_address": {
            "line1": "55 OAK AVE", "city": "ANYTOWN",
            "state": "ST", "zip": "12345",
        },
        "cohort_bucket": "B",
    },
    # Medicaid patient with non-dominant-culture name; demonstrates
    # the search-match fallback because the demo's mock Medicaid
    # payer does not have this exact synthetic record on file.
    "patient-internal-02100": {
        "patient_id": "patient-internal-02100",
        "first_name": "Maria", "last_name": "Garcia-Lopez",
        "suffix": None,
        "dob": "1972-03-14", "sex": "F",
        "ssn": "987-65-4321",
        "standardized_address": {
            "line1": "1421 ELM ST APT 3B", "city": "ANYTOWN",
            "state": "ST", "zip": "12345",
        },
        "cohort_bucket": "C",
    },
}

# Synthetic coverage-history per (patient_id, payer_id), simulating
# the on-file member-ID list with capture timestamps.
COVERAGE_HISTORY = {
    ("patient-internal-00874", "payer-CIGNA-COMMERCIAL"): [
        {"member_id": "U1234567890-01", "captured_at": "2026-01-15"},
    ],
    ("patient-internal-00875", "payer-CIGNA-COMMERCIAL"): [
        # Stale member ID; current ID is U1234567890-01 in the
        # mock roll. Member-ID match scores against the
        # historical fall-through.
        {"member_id": "U9999000111-01", "captured_at": "2025-08-12"},
    ],
    ("patient-internal-01001", "payer-SELFFUNDED-TPA-Y"): [
        {"member_id": "TPA-Y-1001-01", "captured_at": "2026-01-15"},
    ],
}


def run_pipeline(trigger_event: dict,
                  provided_member_id: Optional[str] = None) -> dict:
    """
    End-to-end ingest -> normalize -> submit -> evaluate ->
    persist pipeline for one trigger. Returns a small summary
    dict for the caller (and the demo) to print.
    """
    # Cache check first (the registration-flow optimization).
    cached = cache_get(trigger_event["patient_id"],
                        trigger_event["payer_id"],
                        trigger_event["service_date"])
    if cached is not None:
        return {
            "patient_id":   trigger_event["patient_id"],
            "payer_id":     trigger_event["payer_id"],
            "service_date": trigger_event["service_date"],
            "status":       (cached.get("match_outcome") or {}).get("status"),
            "source":       "cache",
        }

    # Step 1: ingest the trigger.
    inquiry = ingest_eligibility_trigger(trigger_event)

    # Step 2: normalize.
    patient_record = PATIENT_MASTER.get(inquiry["patient_id"])
    if patient_record is None:
        return {
            "patient_id":   inquiry["patient_id"],
            "payer_id":     inquiry["payer_id"],
            "service_date": inquiry["service_date"],
            "status":       "PATIENT_NOT_IN_MPI",
            "source":       "pipeline",
        }
    coverage_history = COVERAGE_HISTORY.get(
        (inquiry["patient_id"], inquiry["payer_id"]), [])
    inquiry = normalize_inquiry(inquiry, patient_record,
                                  coverage_history,
                                  provided_member_id=provided_member_id)

    # Step 3: submit.
    inquiry = submit_inquiry(inquiry)

    # Step 4: evaluate.
    match_outcome = evaluate_response(inquiry, patient_record,
                                         coverage_history)

    # Step 5: persist + propagate.
    persisted = persist_and_propagate(inquiry, match_outcome)

    return {
        "patient_id":         inquiry["patient_id"],
        "payer_id":           inquiry["payer_id"],
        "service_date":       inquiry["service_date"],
        "status":             match_outcome.get("status"),
        "matched_member_id":  match_outcome.get("matched_member_id"),
        "match_confidence":   match_outcome.get("match_confidence"),
        "match_method":       match_outcome.get("match_method"),
        "review_reason":      match_outcome.get("review_reason"),
        "source":             "pipeline",
    }


def run_demo():
    """
    Run the full pipeline against a small set of synthetic
    triggers exercising the major paths.
    """
    print("=" * 70)
    print("Insurance Eligibility Matching Demo")
    print("=" * 70)
    print()
    print("All patients, payers, and member records in this demo are")
    print("fictional. The mock clearinghouse returns hand-crafted")
    print("responses that exercise the full classification range; do")
    print("not point this demo at a live registration system.")
    print()
    print(f"AUTO_ACCEPT_THRESHOLD={AUTO_ACCEPT_THRESHOLD}, "
          f"AUTO_REJECT_THRESHOLD={AUTO_REJECT_THRESHOLD}")
    print()

    triggers = [
        # 1. Clean primary-key match: patient produces card with
        # current member ID; the payer has it on file.
        {
            "label":        "primary-key match (clean)",
            "patient_id":   "patient-internal-00874",
            "payer_id":     "payer-CIGNA-COMMERCIAL",
            "service_date": "2026-05-22",
            "service_type_codes": ["30", "98"],
            "reason":       "registration",
            "provided_member_id": "U1234567890-01",
        },
        # 2. Stale member ID, falls through to search match against
        # demographics; the demo's mock returns the current record
        # via search.
        {
            "label":        "stale member ID -> search fallback",
            "patient_id":   "patient-internal-00875",
            "payer_id":     "payer-CIGNA-COMMERCIAL",
            "service_date": "2026-05-22",
            "service_type_codes": ["30"],
            "reason":       "registration",
            "provided_member_id": None,  # use the stale on-file ID
        },
        # 3. Self-funded TPA dependent; primary-key match with
        # person code required.
        {
            "label":        "TPA dependent (primary-key)",
            "patient_id":   "patient-internal-01001",
            "payer_id":     "payer-SELFFUNDED-TPA-Y",
            "service_date": "2026-05-22",
            "service_type_codes": ["30", "1"],
            "reason":       "scheduled_prewarm",
            "provided_member_id": "TPA-Y-1001-01",
        },
        # 4. Medicaid not-found case (synthetic patient is not on
        # the mock state Medicaid roll).
        {
            "label":        "Medicaid not-found",
            "patient_id":   "patient-internal-02100",
            "payer_id":     "payer-MEDICAID-STATE-X",
            "service_date": "2026-05-22",
            "service_type_codes": ["30"],
            "reason":       "registration",
        },
        # 5. Cache hit: re-run the same trigger as #1 to
        # demonstrate the cache short-circuit.
        {
            "label":        "cache hit on re-run",
            "patient_id":   "patient-internal-00874",
            "payer_id":     "payer-CIGNA-COMMERCIAL",
            "service_date": "2026-05-22",
            "service_type_codes": ["30", "98"],
            "reason":       "registration",
            "provided_member_id": "U1234567890-01",
        },
    ]

    # Phase 1: walk the triggers.
    print("-" * 70)
    print("Phase 1: process triggers")
    print("-" * 70)
    for t in triggers:
        label = t.pop("label")
        provided_member_id = t.pop("provided_member_id", None)
        result = run_pipeline(t, provided_member_id=provided_member_id)
        confidence = result.get("match_confidence")
        confidence_str = (f"{confidence:.2f}"
                            if isinstance(confidence, Decimal)
                            else str(confidence) if confidence else "n/a")
        print(f"  {label:<40} status={result['status']:<18} "
              f"member_id={result.get('matched_member_id') or 'n/a':<20} "
              f"conf={confidence_str:<6} via={result['source']}")

    # Phase 2: simulate a coverage-change event that invalidates
    # cached entries and re-queues the inquiry.
    print()
    print("-" * 70)
    print("Phase 2: simulate a coverage-change invalidation")
    print("-" * 70)
    invalidation_summary = invalidate_on_coverage_change({
        "source":               "claim-status-277",
        "event_id":             "evt-2026-05-22-000123",
        "affected_patient_id":  "patient-internal-00874",
        "payer_id":             "payer-CIGNA-COMMERCIAL",
    })
    print(f"  invalidation: source={invalidation_summary['source']} "
          f"invalidated_count={invalidation_summary['invalidated_count']} "
          f"requeued_count={invalidation_summary['requeued_count']}")

    # Phase 3: re-run the registration trigger that was just
    # invalidated; demonstrates that cache miss + DynamoDB
    # re-inquiry produces a fresh match outcome.
    print()
    print("-" * 70)
    print("Phase 3: re-run after invalidation")
    print("-" * 70)
    refreshed = run_pipeline({
        "patient_id":   "patient-internal-00874",
        "payer_id":     "payer-CIGNA-COMMERCIAL",
        "service_date": "2026-05-22",
        "service_type_codes": ["30", "98"],
        "reason":       "registration",
    }, provided_member_id="U1234567890-01")
    rconf = refreshed.get("match_confidence")
    rconf_str = (f"{rconf:.2f}" if isinstance(rconf, Decimal)
                   else str(rconf) if rconf else "n/a")
    print(f"  re-run: status={refreshed['status']:<18} "
          f"conf={rconf_str:<6} via={refreshed['source']}")


if __name__ == "__main__":
    run_demo()
```

Expected console output (the SQS / EventBridge / S3 / CloudWatch warnings appear in demo mode because the resources do not exist; they are harmless):

```
======================================================================
Insurance Eligibility Matching Demo
======================================================================

All patients, payers, and member records in this demo are
fictional. The mock clearinghouse returns hand-crafted
responses that exercise the full classification range; do
not point this demo at a live registration system.

AUTO_ACCEPT_THRESHOLD=0.90, AUTO_REJECT_THRESHOLD=0.55

----------------------------------------------------------------------
Phase 1: process triggers
----------------------------------------------------------------------
  primary-key match (clean)                status=MATCHED            member_id=U1234567890-01     conf=0.98   via=pipeline
  stale member ID -> search fallback       status=MATCHED            member_id=U9999000111-01     conf=0.98   via=pipeline
  TPA dependent (primary-key)              status=MATCHED            member_id=TPA-Y-1001-01      conf=0.98   via=pipeline
  Medicaid not-found                       status=NOT_FOUND          member_id=n/a                conf=n/a    via=pipeline
  cache hit on re-run                      status=MATCHED            member_id=n/a                conf=n/a    via=cache

----------------------------------------------------------------------
Phase 2: simulate a coverage-change invalidation
----------------------------------------------------------------------
  invalidation: source=claim-status-277 invalidated_count=1 requeued_count=1

----------------------------------------------------------------------
Phase 3: re-run after invalidation
----------------------------------------------------------------------
  re-run: status=MATCHED            conf=0.98   via=pipeline
```

Several patterns to notice:

- **Trigger #1 is the registration-flow happy path.** The patient produces a card with the current member ID, the payer has it on file, the inquiry returns `match_type=primary_key`, every feature scores high, and the composite score lands above `AUTO_ACCEPT_THRESHOLD`. The cache and DynamoDB are populated; downstream consumers receive the `eligibility_resolved` event.
- **Trigger #2 demonstrates a stale-member-ID gotcha.** The on-file member ID `U9999000111-01` was issued for the patient's 2025 plan; that plan terminated 2025-12-31 and the patient's 2026 plan has a new member ID `U1234567890-01` that the practice has not captured yet. The mock clearinghouse still has the 2025 record on its roll (payers commonly keep terminated members visible for a year or more for claims-runout purposes), so the primary-key lookup succeeds against the stale ID and returns coverage detail showing `termination_date=2025-12-31`. Match confidence is high (the demographics agree), but a downstream consumer that looks at the termination date will correctly conclude that this coverage is not active for the 2026-05-22 service date. The mitigation in production is to surface the termination date prominently in the registration UI and prompt the patient for an updated card.
- **Trigger #3 exercises the dependent-with-person-code path.** The TPA's per-payer config requires `requires_person_code=True`; the normalizer attaches the person code; the mock clearinghouse returns the dependent record (Emily, child of John); the match succeeds.
- **Trigger #4 exercises the not-found path.** The synthetic Medicaid payer is configured for search match only, but the demo does not have this patient on the mock state Medicaid roll, so the response is NOT_FOUND. In production this is the case where the front-desk staff has documented next-step procedures (re-verify in 48 hours, check the state Medicaid portal directly, schedule a financial counseling session).
- **Trigger #5 demonstrates the cache short-circuit.** Same trigger as #1 re-run; the cache returns the already-resolved match outcome in microseconds without calling the clearinghouse. This is the latency win that keeps the registration flow under the front-desk-experience target. The cache entry's `match_outcome` is the persisted form (the values like `match_confidence` and `matched_member_id` live nested inside it), which is why the simple summary print shows `n/a` for those fields on the cache hit path; production read APIs unwrap the nested fields before returning.
- **Phase 2 simulates a 277CA claim-status response indicating an eligibility issue.** The pipeline invalidates the cached match outcome and re-queues the inquiry. In production the re-inquiry runs asynchronously on the prewarm queue; the demo runs `ingest_eligibility_trigger` synchronously and the in-memory queue stand-in just logs the routing.
- **Phase 3 shows the post-invalidation re-resolution path.** Cache miss this time (because Phase 2 deleted the entry), so the pipeline re-runs through the normalize-submit-evaluate flow and produces a fresh match. In production the registration UI would have already received a "verification pending" response and would update when the asynchronous resolution completes.

The cohort-bucket dimension on the CloudWatch metric is the substrate for the per-cohort accuracy monitoring discussed in the main recipe; production aggregates on `CohortBucket` and alarms on per-cohort disparities exceeding the institutional threshold.

---

## Gap to Production

What the demo intentionally skips, and what you would add for a real deployment:

**Replace `MockClearinghouse` with a real clearinghouse SDK.** Availity, Change Healthcare/Optum, Waystar, or whichever clearinghouse you license. Construct the SDK from credentials in Secrets Manager, route the call through a VPC endpoint or NAT Gateway with an outbound allow-list, and respect the published rate limits. The clearinghouse must have a BAA in place because each call sends PHI (full demographics paired with the patient identifier and the requesting provider's NPI). The `_classify_vendor_response` mapping needs adapting to the clearinghouse's specific response codes; X12 271 AAA codes are standardized but each clearinghouse has its own quirks in how it surfaces partial responses, payer-specific error messages, and CAQH-CORE-noncompliance situations.

**Real X12 270/271 generation and parsing.** The demo passes a Python dict that the MockClearinghouse understands. Production builds an actual X12 270 envelope (via [`pyx12`](https://github.com/azoner/pyx12), the clearinghouse SDK, or [`bots`](https://github.com/bots-edi/bots)), submits the envelope, and parses the X12 271 response back into a structured form. The X12 standard is dense and unforgiving; do not roll your own parser unless you intend to maintain it through every X12 version transition.

**FHIR-based eligibility for payers offering it.** Some payers expose CMS Patient Access APIs or Da Vinci Coverage Requirements Discovery endpoints. Build a parallel connectivity path that uses FHIR `CoverageEligibilityRequest` and `CoverageEligibilityResponse` resources. The matching logic carries over with adjustments to the parsing layer; the response shape is FHIR-native rather than X12 271. Maintain both paths because the X12 ecosystem will be load-bearing in US healthcare for at least the next decade.

**Real DynamoDB schema with the member-id-index GSI.** The `eligibility-match` table is keyed on `(patient_id, payer_payer_service_date_sort)` for the per-(patient, payer, date) lookup; the `member-id-index` GSI on `(matched_member_id, payer_id)` supports the reverse-lookup (given a payer-side member ID, which patient records have matched against it). The `payer-config` table is keyed on `payer_id` and read at the start of every inquiry. Provision both with on-demand capacity to handle the bursty pattern of morning registration peaks plus the steady volume of scheduled pre-warm.

**Real ElastiCache for Redis.** The demo uses an in-process dict; production runs ElastiCache for Redis with in-transit and at-rest encryption (KMS). Cache hit returns in well under 5ms and skips DynamoDB entirely; cache miss falls through to DynamoDB, then to a re-inquiry. Configure the cluster in VPC subnet groups with security groups restricting access to the eligibility Lambdas only.

**TransactWriteItems for atomic writes.** The demo writes the eligibility-match item, the cache, the audit archive, and the EventBridge event in separate calls. A partial-failure scenario could leave the eligibility table updated without a corresponding event, which means downstream consumers (revenue cycle, charity-care, patient portal) never refresh. Production batches the eligibility-match `PutItem` and an outbox-row `PutItem` into a single `TransactWriteItems` call, with a Streams-driven consumer draining the outbox to EventBridge so the persistence is atomic with the eventual emit. The consequence here is sharper than in earlier chapter-5 recipes because the eligibility outcome directly drives revenue cycle (claim with wrong coverage = denial), charity-care (false-negative coverage = wrongful eligibility denial), and patient financial responsibility.

**Step Functions orchestration with retry, timeout, and DLQ.** Three workflows: real-time inquiry (normalize, submit, evaluate, persist, propagate; calibrated to the registration-flow latency budget), scheduled pre-warm (run nightly across tomorrow's appointments, queue the inquiries for off-peak processing, populate the cache by morning), batch reconciliation (run monthly to compare the payer roster against the institution's match store). Each Lambda has a dedicated DLQ; Step Functions Catch states route terminal failures to the DLQ; CloudWatch alarms on DLQ depth surface stuck workflows.

**Idempotency keys on every write.** The demo uses `inquiry_hash` for inquiry-level idempotency; production extends this: normalize at `inquiry_hash`, submit at `inquiry_hash + clearinghouse_idempotency_key`, evaluate at `(inquiry_id, response_payload_hash)`, persist at `(patient_id, payer_id, service_date, resolved_at_minute_bucket)`, invalidate at `(change_event_source, change_event_id)`. Duplicate-event delivery from EventBridge or duplicate-invocation from Step Functions retries is routine; the pipeline must handle it without producing duplicate writes, duplicate clearinghouse charges, or inconsistent state.

**Per-payer config governance.** The demo bakes the per-payer config into a Python dict. Production stores it in DynamoDB with versioning, governs changes through a code-review process (a normalization rule change can break the eligibility-verification flow for tens of thousands of patients on a single payer), and emits CloudWatch metrics on per-payer match-success rates so a config change that degrades quality produces an alarm before it produces a denial spike.

**Threshold calibration and approval governance.** The auto-accept and auto-reject thresholds are calibrated against a labeled gold set that reflects the institution's cohort distribution. Re-calibration runs annually or on detection of cohort-stratified disparity above the institutional threshold. Each match outcome records `THRESHOLDS_VERSION` so a future audit can reconstruct what cutoffs were active at the time of the decision. Promote candidate thresholds through institutional review (revenue-cycle leadership, compliance, equity-monitoring committee) before they go live.

**Cohort-stratified accuracy monitoring.** The demo emits a per-cohort dimension on the `EligibilityMatchOutcome` and `EligibilityMatchScore` metrics but does not aggregate or alarm on disparities. Production computes per-cohort match-success rate, per-cohort review-queue rate, and per-cohort downstream claim-denial rate weekly; alarms fire when absolute disparity between best-rate and worst-rate cohort exceeds the institutional threshold (typical: 0.05 for match success and review-queue, 0.03 for downstream denials). Remediation (per-cohort threshold tuning, payer-specific normalization rules, registration-staff training on data capture for affected cohorts) is documented in a cohort-disparity ledger and reviewed quarterly.

**Review queue tooling.** The demo routes `REVIEW_REQUIRED` outcomes to an SQS queue but does not provide a UI. Production builds a workflow tool that surfaces the inquiry, the candidate(s), the score breakdown, the supporting demographic context, and the decision options (accept the match, reject the match, escalate, request additional information from the patient). The tool emits the reviewer's decision back into the matcher's training signal for periodic threshold re-calibration, and records the reviewer's identity, decision, stated reason, timestamp, and the configuration version active at the time for audit. Same pattern as 5.1 / 5.2 / 5.3 review-queue tooling.

**Coordination of benefits resolution.** The demo records the `is_primary` indicator from the 271 response but does not attempt cross-payer COB resolution. Production builds a downstream COB module that consumes multiple match outcomes for the same patient and service date and applies the institution's COB rules (state-specific Medicaid/Medicare hierarchy, the "birthday rule" for pediatric coverage, contractual rules for value-based-care patients) to produce a primary-secondary-tertiary determination that the revenue-cycle workflow consumes.

**Network-status reconciliation.** The demo passes through the payer's `provider_in_network` indicator. Production reconciles this against the institution's own provider-network table, which may have updates the payer does not yet reflect (a provider contracted directly through a value-based-care arrangement, for example). Surface conflicts to revenue cycle.

**Real cohort-stratified backfill.** When the eligibility-matching pipeline launches against an existing patient population at scale, run a one-time pass populating the cache for all upcoming appointments. Negotiate a one-time bulk pricing tier with the clearinghouse (typical batch transaction pricing is 5-10x cheaper than real-time). Run the backfill as a Glue job with controlled concurrency to stay below the clearinghouse's rate limit. Suppress the `eligibility_resolved` event emission during backfill (downstream consumers refresh from a single `eligibility_backfill_complete` marker rather than 100K individual events). Plan the backfill timeline in coordination with downstream consumers so the change in eligibility-data quality lands in their workflows on a known date.

**Patient-portal coverage self-service.** Surface the on-file standardized coverage back to the patient on portal login ("Is your insurance still ABC Health Plan, member ID U1234567890? Yes / Update") and accept updated card images via OCR (recipe 1.1) for member-ID extraction. Capture the patient's confirmation timestamp as a freshness signal. Patients who confirm are a higher-trust source than registration-clerk keystrokes; the data quality improvement is meaningful and the implementation cost is small.

**KMS-encrypted everything.** Customer-managed keys for the S3 audit bucket, the DynamoDB tables, the ElastiCache cluster, the SQS queues, the Lambda log groups, and the Secrets Manager clearinghouse-credential entry. Per-service KMS configuration is omitted for readability but is non-negotiable for the institution's standard PHI-handling posture.

**VPC + VPC endpoints.** Production runs Lambdas in VPC with VPC endpoints for S3 (gateway), DynamoDB (gateway), KMS, Secrets Manager, CloudWatch Logs, EventBridge, SQS, Step Functions, Glue, Athena, and STS. NAT Gateway only for the clearinghouse and direct-payer egress; restrict egress with security groups and an outbound proxy with an allow-list of partner endpoints. Evaluate AWS PrivateLink endpoints where the clearinghouse or large-volume payer offers them.

**CloudTrail data events on the eligibility-match table and the audit S3 buckets.** Every read of `eligibility-match` is auditable activity; the data-events feature is not enabled by default and is the right level of granularity for the eligibility substrate. CloudTrail logs themselves are KMS-encrypted, retained per the longer of 7 years (HIPAA records-retention minimum), 10 years (Medicare claims retention where applicable), the institution's documented eligibility-data retention policy, the value-based-care contract retention requirement, and any state-specific Medicaid retention requirement, with Object Lock in Compliance mode and a lifecycle policy transitioning to S3 Glacier Deep Archive after 90 days. Forward CloudTrail data events to a dedicated audit AWS account in the institution's organization.

**Clearinghouse cost monitoring.** Clearinghouse transaction fees are the dominant cost. Tag every inquiry with the workflow that originated it (registration, pre-warm, batch, charity-care, refresh-on-coverage-change). Aggregate the inquiries per workflow per month. Detect cost anomalies (a runaway pre-warm job, a cache-invalidation storm forcing re-inquiries, a configuration change that increases the percentage of search-match inquiries because primary-key match dropped). Alert on cost thresholds. The clearinghouse cost can spiral fast if a downstream system starts looping.

**Real cache freshness signals.** The demo subscribes to claim-status-277, payer-roster-delta, 834-enrollment-file, patient-merge, and address-change events conceptually but does not actually wire them. Production consumes the 277CA stream from each clearinghouse, the monthly roster files from each payer, 834 enrollment files where received, and the merge / address-change events from recipes 5.1 and 5.3 via EventBridge. Each invalidation event must include enough context (`event_id`, `source`, affected identifiers) for the invalidation pipeline to scope the affected cache entries narrowly; over-broad invalidation produces re-inquiry storms.

**Compliance and operational ownership.** Eligibility matching sits at the intersection of revenue cycle, registration, compliance, and IT. Establish clear operational ownership: who tunes the thresholds, who reviews the cohort-disparity reports, who handles the per-payer config updates, who responds to clearinghouse incidents, who owns the relationship with each direct-payer connection. The pipeline works only when the operational ownership is clear and funded.

The pipeline is the easy part. The operational discipline (clearinghouse selection and trading-partner agreements, per-payer config governance, threshold calibration and approval workflow, cohort-stratified equity monitoring, review-queue tooling and reviewer auditing, COB resolution rules, registration-time correction UX, patient-portal self-service, ongoing operational ownership) is what makes an eligibility-matching system produce accurate, fresh, usable eligibility data year after year. Build for that.

---

*← [Recipe 5.4: Insurance Eligibility Matching](chapter05.04-insurance-eligibility-matching)*
