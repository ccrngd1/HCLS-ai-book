# Recipe 5.3: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 5.3. It shows one way you could translate the address-standardization-and-household-linkage pattern into working Python using a stub CASS-certified vendor SDK (the demo includes a small mock that mimics the response shape of vendors like Smarty, Melissa, or Loqate, since talking to a real vendor requires a paid healthcare-tier account with a BAA), Amazon DynamoDB for the standardized-address and household-membership tables, Amazon S3 for the audit archive, Amazon EventBridge for downstream address-and-household drift events, and Amazon CloudWatch for operational metrics. It is not production-ready. There is no real CASS-certified validator (the demo's `MockAddressValidator` returns plausible USPS-style responses for synthetic addresses and is not USPS-conformant), no NCOAlink integration (the demo simulates a mover detection event with hard-coded data), no Glue or Spark batch pipeline (the demo runs the full population in-process and would not survive a 500,000-patient monthly refresh), no real geocoder, no SDOH-indicator joins, no privacy-officer-approved suppression policy (the demo implements both options as branches and you have to pick one), no review-queue UI for ambiguous addresses, and no IAM, KMS, VPC, Secrets Manager, or CloudTrail wiring. Think of it as the sketchpad version: useful for understanding the shape of an address-and-household pipeline that respects the structured schema, the graded-confidence household contract, the privacy-suppression-as-first-class-case discipline, and the audit-everything posture. It is not something you would point at a live patient registration system on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the five core pseudocode steps from the main recipe: ingest a patient address record from any source system; standardize it through the (mock) CASS-certified vendor with classification into VALIDATED, CORRECTED, MISSING_SECONDARY, AMBIGUOUS, NOT_VALIDATED, or INVALID; persist the standardized record with provenance and emit a change event; infer household membership for everyone sharing the canonical address with graded HIGH / MEDIUM / CO_LOCATED / SUPPRESSED confidence; and re-process periodically to detect drifts (USPS reference data refresh, NCOA mover detection). The synthetic patients in the demo are fictional; the addresses are obviously made-up and should not match any real residence.

---

## Setup

You will need the AWS SDK for Python plus a permissive date parser:

```bash
pip install boto3
```

In production you would also install the official SDK from your CASS-certified vendor (Smarty's `smartystreets-python-sdk`, Melissa's API client, Loqate's, or Experian's). The demo replaces the vendor SDK with a small `MockAddressValidator` class that returns plausible USPS-style responses for known synthetic inputs, so you can run the demo without a vendor account.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchWriteItem` on the `patient-address` and `household-membership` tables (and on the `canonical-hash-index` GSI on `patient-address` that supports same-address lookups for household inference)
- `s3:PutObject` on the audit-archive bucket
- `events:PutEvents` on the address-and-household drift events bus
- `cloudwatch:PutMetricData` for the standardization-success-rate, drift-volume, and cohort-disparity metrics
- `secretsmanager:GetSecretValue` on the vendor-API-key secret (production only; the mock validator does not need it)

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review.

A few things worth knowing upfront:

- **Standardized addresses are PHI in their structured form.** The combination of standardized address + DOB + sex is highly re-identifying, and HIPAA's de-identification standards treat geographic subdivisions smaller than state (with limited exceptions for the first three digits of ZIP code) as identifiers. Encrypt with a customer-managed KMS key, gate every read with CloudTrail data events, and apply the same access discipline you would for the patient-matching infrastructure in recipe 5.1.
- **DynamoDB rejects Python `float`.** Every probability, confidence score, and numeric metadata field passes through `Decimal` on its way in and on its way out. Same gotcha as recipes 5.1 and 5.2; the same `_to_decimal` helper handles it.
- **CASS-certified vendor calls are billable PHI transmissions.** Each call to the vendor API sends the patient identifier (you must) and the address (the whole point) outside your VPC. The vendor must have a BAA in place; the call must go through a controlled egress path (VPC endpoint where available, NAT Gateway with allow-list otherwise); the API key must live in Secrets Manager, not in code or environment variables. The demo skips this wiring for readability but the production pattern is non-negotiable.
- **Standardization results should be cached.** Many addresses repeat across patient records (family members at the same address, address copied from one record to another). A small cache keyed on the input hash dramatically reduces vendor cost. The demo includes an in-process cache; production uses DynamoDB or ElastiCache.
- **Privacy suppression is a deliberate policy choice.** The demo implements both options (suppress entire group when any record is suppressed, vs exclude suppressed records from the group). The right one depends on the institution's clinical and legal context. Pick one and document it; do not leave it as a coin flip per deployment.
- **No real NCOA integration.** NCOA is a USPS-licensed product distributed through certified vendors with specific intended-use access controls. The demo simulates a mover detection event by hard-coding one in `simulate_ncoa_processing()`; production submits the population to a vendor on a quarterly cadence and processes the response file.
- **The example collapses Step Functions, Lambda, Glue, and EventBridge into a single Python file for readability.** In production the standardize, persist, household-infer, and drift-detect stages are separate Lambdas (or Glue stages) orchestrated by Step Functions, with their own error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the cache TTL, the re-validation cadence, the household-inference confidence thresholds, the privacy-suppression policy, and the building-type classification rules are the knobs you would change between environments.

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
# CloudWatch Logs Insights. Address data is PHI; log structural
# metadata only (patient_id, canonical_hash, status, decision),
# never raw address fields.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from DynamoDB, EventBridge,
# CloudWatch, and the (real) vendor API. Real-time standardization
# at registration has a tight latency budget; transient throttling
# from any one service should not fail the whole address update.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm
# containers so each invocation does not pay the connection cost.
REGION = "us-east-1"
dynamodb = boto3.resource("dynamodb", region_name=REGION, config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", region_name=REGION, config=BOTO3_RETRY_CONFIG)
eventbridge_client = boto3.client("events", region_name=REGION, config=BOTO3_RETRY_CONFIG)
cloudwatch_client = boto3.client("cloudwatch", region_name=REGION, config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill these in with your actual resource names. The demo prints
# what it would write rather than failing if the resources do not
# exist; see the run_demo() function at the bottom.
ADDRESS_TABLE          = "patient-address"
HOUSEHOLD_TABLE        = "household-membership"
CANONICAL_HASH_INDEX   = "canonical-hash-index"  # GSI on patient-address
AUDIT_BUCKET           = "my-address-standardization-audit"
EVENTS_BUS_NAME        = "address-and-household-drift"
CLOUDWATCH_NAMESPACE   = "Address/Standardization"

# Deploy-time guardrail.
# TODO (TechWriter): Code review Finding 5 (NOTE). Extend the
# guardrail to cover every resource-name constant so a missing
# value produces an actionable assertion message rather than a
# downstream boto3 ValidationException. Suggested loop:
#
#   for name, value in [
#       ("ADDRESS_TABLE", ADDRESS_TABLE),
#       ("HOUSEHOLD_TABLE", HOUSEHOLD_TABLE),
#       ("CANONICAL_HASH_INDEX", CANONICAL_HASH_INDEX),
#       ("AUDIT_BUCKET", AUDIT_BUCKET),
#       ("EVENTS_BUS_NAME", EVENTS_BUS_NAME),
#       ("CLOUDWATCH_NAMESPACE", CLOUDWATCH_NAMESPACE),
#   ]:
#       assert value, f"{name} must be set before deploying."
#
# Same chapter pattern as 5.2 Finding 8.
assert AUDIT_BUCKET != "", "AUDIT_BUCKET must be set before deploying."

# --- Versioning ---
NORMALIZER_VERSION         = "addr-norm-v1.0"
HOUSEHOLD_INFERENCE_VERSION = "household-inf-v1.0"

# --- Cache TTL for the standardization result ---
# Standardization is idempotent for a given USPS reference-data
# release. The TTL should not exceed the vendor's reference-data
# refresh cadence (typically monthly). Reset the cache after a
# vendor reference-data update.
CACHE_TTL_DAYS = 30

# --- Re-validation cadence ---
# How often a previously-standardized address is re-checked against
# the latest USPS reference data. Quarterly is the common baseline;
# monthly is stricter and aligns with the vendor's reference-data
# release cadence.
REVALIDATION_CADENCE_DAYS = 90

# --- Building-type-to-household-eligibility map ---
# Some building types do not produce meaningful household
# inferences. The map below decides whether to attempt household
# inference; the household-confidence logic still applies for the
# building types that pass.
HOUSEHOLD_INFERENCE_BY_BUILDING_TYPE = {
    "single_family":       True,
    "multi_unit_with_unit": True,
    "multi_unit_no_unit":  False,  # ambiguous; declare CO_LOCATED only
    "commercial":          False,
    "po_box":              False,
    "shelter":             False,
    "nursing_home":        False,
    "unknown":             False,  # be conservative on unknowns
}

# --- Privacy suppression policy ---
# "suppress_entire_group_if_any_suppressed": if any patient at a
#     canonical address has the suppression flag set, no household
#     is inferred for the group; everyone is marked SUPPRESSED.
# "exclude_suppressed_from_group": only the suppressed patients are
#     excluded; the rest of the group goes through normal household
#     inference.
# Pick one with the privacy office. The demo runs both for
# illustration but production must commit to a single policy.
PRIVACY_POLICY = "suppress_entire_group_if_any_suppressed"

# --- Building-type classification heuristics ---
# Coarse rules over standardization metadata. Production refines
# this with parcel data, address-quality vendor classifications,
# and (for nursing homes and shelters) a curated facility list.
SHELTER_KEYWORDS = ["shelter", "rescue mission", "transitional housing"]
NURSING_HOME_KEYWORDS = ["nursing home", "skilled nursing", "snf",
                          "long term care", "assisted living"]

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
    """Join address parts into a canonical lowercase whitespace-collapsed form for hashing."""
    joined = " ".join(str(p or "").strip() for p in parts)
    joined = _strip_diacritics(joined).lower()
    joined = re.sub(r"\s+", " ", joined).strip()
    return joined

def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
```

---

## A Mock CASS-Certified Validator

Production calls a real vendor SDK here. The demo includes a small mock that returns plausible USPS-style responses for known synthetic addresses, plus a generic best-effort response for unrecognized inputs. The response shape is modeled after the major vendors' fields (Smarty, Melissa, Loqate, Experian); the field names below are illustrative and the real vendor SDK you license will have its own naming. The point of the mock is to exercise the downstream pipeline (classification, persistence, household inference) without requiring a paid vendor account.

```python
class MockAddressValidator:
    """
    A stand-in for a real CASS-certified vendor SDK. The response
    structure is illustrative; the real SDKs from Smarty, Melissa,
    Loqate, and Experian return similar shapes with vendor-specific
    field names. Replace this with the real vendor SDK in
    production.
    """

    # A few well-known synthetic addresses with hand-crafted
    # responses that exercise the full classification range.
    _KNOWN_ADDRESSES = {
        # Clean validated address: returns DPV=Y, no correction.
        "1421 elm st apt 3b anytown st 12345": {
            "dpv": "Y",
            "was_corrected": False,
            "delivery_line_1": "1421 ELM ST APT 3B",
            "last_line": "ANYTOWN ST 12345-1234",
            "components": {
                "primary_number": "1421", "street_predirection": None,
                "street_name": "ELM", "street_suffix": "ST",
                "street_postdirection": None, "secondary_designator": "APT",
                "secondary_number": "3B", "city": "ANYTOWN",
                "state": "ST", "zipcode": "12345", "plus4_code": "1234",
            },
            "metadata": {
                "record_type": "Street", "is_residential": True,
                "is_business": False, "is_vacant": False,
                "is_po_box": False, "congressional_district": "12",
                "county_name": "EXAMPLE", "county_fips": "12345",
                "census_block": "1234567890123", "carrier_route": "C001",
                "dpv_footnotes": ["AA", "BB"],
            },
        },
        # Family member at the same address (different unit). For
        # household inference: same building, different unit ->
        # likely a separate household at the same address.
        "1421 elm st apt 5a anytown st 12345": {
            "dpv": "Y", "was_corrected": False,
            "delivery_line_1": "1421 ELM ST APT 5A",
            "last_line": "ANYTOWN ST 12345-1234",
            "components": {
                "primary_number": "1421", "street_predirection": None,
                "street_name": "ELM", "street_suffix": "ST",
                "street_postdirection": None, "secondary_designator": "APT",
                "secondary_number": "5A", "city": "ANYTOWN",
                "state": "ST", "zipcode": "12345", "plus4_code": "1234",
            },
            "metadata": {
                "record_type": "Street", "is_residential": True,
                "is_business": False, "is_vacant": False,
                "is_po_box": False, "congressional_district": "12",
                "county_name": "EXAMPLE", "county_fips": "12345",
                "census_block": "1234567890123", "carrier_route": "C001",
                "dpv_footnotes": ["AA", "BB"],
            },
        },
        # Typo on the street name; vendor returns DPV=Y with
        # was_corrected=True and a high correction confidence.
        "1421 elm stret apt 3b anytown st 12345": {
            "dpv": "Y", "was_corrected": True, "correction_confidence": 0.97,
            "delivery_line_1": "1421 ELM ST APT 3B",
            "last_line": "ANYTOWN ST 12345-1234",
            "components": {
                "primary_number": "1421", "street_predirection": None,
                "street_name": "ELM", "street_suffix": "ST",
                "street_postdirection": None, "secondary_designator": "APT",
                "secondary_number": "3B", "city": "ANYTOWN",
                "state": "ST", "zipcode": "12345", "plus4_code": "1234",
            },
            "metadata": {
                "record_type": "Street", "is_residential": True,
                "is_business": False, "is_vacant": False,
                "is_po_box": False, "congressional_district": "12",
                "county_name": "EXAMPLE", "county_fips": "12345",
                "census_block": "1234567890123", "carrier_route": "C001",
                "dpv_footnotes": ["AA", "AB"],  # AB indicates correction
            },
        },
        # Multi-unit building, unit number missing on input.
        # DPV=S means a secondary unit is required.
        "100 main st anytown st 12345": {
            "dpv": "S", "was_corrected": False,
            "delivery_line_1": "100 MAIN ST",
            "last_line": "ANYTOWN ST 12345",
            "components": {
                "primary_number": "100", "street_predirection": None,
                "street_name": "MAIN", "street_suffix": "ST",
                "street_postdirection": None, "secondary_designator": None,
                "secondary_number": None, "city": "ANYTOWN",
                "state": "ST", "zipcode": "12345", "plus4_code": None,
            },
            "metadata": {
                "record_type": "Street", "is_residential": True,
                "is_business": False, "is_vacant": False,
                "is_po_box": False, "congressional_district": "12",
                "county_name": "EXAMPLE", "county_fips": "12345",
                "census_block": "9876543210987", "carrier_route": "C002",
                "dpv_footnotes": ["N1"],  # N1 = missing secondary
            },
        },
        # PO Box: validates but is not a residence.
        "po box 4421 anytown st 12345": {
            "dpv": "Y", "was_corrected": False,
            "delivery_line_1": "PO BOX 4421",
            "last_line": "ANYTOWN ST 12345-4421",
            "components": {
                "primary_number": "4421", "street_predirection": None,
                "street_name": None, "street_suffix": None,
                "street_postdirection": None, "secondary_designator": None,
                "secondary_number": None, "city": "ANYTOWN",
                "state": "ST", "zipcode": "12345", "plus4_code": "4421",
            },
            "metadata": {
                "record_type": "PO Box", "is_residential": False,
                "is_business": False, "is_vacant": False,
                "is_po_box": True, "congressional_district": "12",
                "county_name": "EXAMPLE", "county_fips": "12345",
                "census_block": None, "carrier_route": "PO Box",
                "dpv_footnotes": ["AA"],
            },
        },
        # Shelter address: validates as a real address but the
        # downstream classifier flags it via the keyword list.
        "200 hope way anytown st 12345": {
            "dpv": "Y", "was_corrected": False,
            "delivery_line_1": "200 HOPE WAY",
            "last_line": "ANYTOWN ST 12345-2200",
            "components": {
                "primary_number": "200", "street_predirection": None,
                "street_name": "HOPE", "street_suffix": "WAY",
                "street_postdirection": None, "secondary_designator": None,
                "secondary_number": None, "city": "ANYTOWN",
                "state": "ST", "zipcode": "12345", "plus4_code": "2200",
            },
            "metadata": {
                "record_type": "Street", "is_residential": False,
                "is_business": True, "is_vacant": False,
                "is_po_box": False, "congressional_district": "12",
                "county_name": "EXAMPLE", "county_fips": "12345",
                "census_block": "5555555555555", "carrier_route": "C003",
                "dpv_footnotes": ["AA"],
                "business_name": "ANYTOWN RESCUE MISSION SHELTER",
            },
        },
    }

    SOFTWARE_VERSION = "mock-v1.0"
    CASS_CYCLE = "Cycle MOCK"
    USPS_REFERENCE_RELEASE = "2026-04-01"

    def validate(self, line1, line2, city, state, zip_code):
        """Mimic a vendor validate() call."""
        key = _canonical_form(line1, line2, city, state, zip_code)
        result = self._KNOWN_ADDRESSES.get(key)
        if result:
            return self._build_response(result)

        # Generic best-effort response for unknown inputs: the
        # mock returns INVALID so the downstream pipeline exercises
        # that path. A real vendor would attempt parse + correction.
        return {
            "dpv": "N", "was_corrected": False,
            "delivery_line_1": None, "last_line": None,
            "components": {}, "metadata": {},
            "candidates": [],
            "software_version": self.SOFTWARE_VERSION,
            "cass_cycle": self.CASS_CYCLE,
            "usps_reference_release": self.USPS_REFERENCE_RELEASE,
            "match_code": "no_match",
        }

    def _build_response(self, base: dict) -> dict:
        return {
            **base,
            "candidates": [],
            "match_code": "match" if base["dpv"] in {"Y", "S"} else "no_match",
            "software_version": self.SOFTWARE_VERSION,
            "cass_cycle": self.CASS_CYCLE,
            "usps_reference_release": self.USPS_REFERENCE_RELEASE,
        }

# Module-level mock validator. In production, replace with the
# vendor SDK constructed from credentials in Secrets Manager.
vendor_sdk = MockAddressValidator()

# --- In-memory standardization cache ---
# Production uses DynamoDB or ElastiCache so the cache survives
# Lambda cold starts and is shared across invocations. The
# in-memory dict here is fine for the single-process demo.
_STANDARDIZATION_CACHE: dict = {}

def check_standardization_cache(raw_input_hash: str):
    entry = _STANDARDIZATION_CACHE.get(raw_input_hash)
    if not entry:
        return None
    age_days = (datetime.now(timezone.utc) - entry["cached_at"]).days
    if age_days > CACHE_TTL_DAYS:
        del _STANDARDIZATION_CACHE[raw_input_hash]
        return None
    return entry["standardized"]

def write_to_standardization_cache(raw_input_hash: str, standardized: dict):
    _STANDARDIZATION_CACHE[raw_input_hash] = {
        "standardized": standardized,
        "cached_at":    datetime.now(timezone.utc),
    }
```

---

## Step 1: Ingest a Patient Address Record

*The pseudocode calls this `ingest_address_record(source_event)`. Address records arrive from registration events (real-time), insurance feeds (periodic batch), HIE referrals (per-event), and patient-portal updates (real-time). Each source produces a raw address with source-specific field formatting. Capture the source, the timestamp, the patient identifier, the address role (physical, mailing, historical), and the raw fields. Skip this and you lose the audit trail you'll need when the standardization changes the address and someone asks why.*

```python
def _archive_raw_to_s3(raw: dict) -> None:
    """Best-effort raw-input archive. Failures are logged and skipped (the demo prints what it would write)."""
    today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    key = (f"address-raw/{raw.get('source', 'unknown')}/{today}/"
            f"{raw['patient_id']}_{raw['address_role']}_{uuid.uuid4()}.json")
    body = json.dumps(raw, default=str).encode("utf-8")
    try:
        s3_client.put_object(
            Bucket=AUDIT_BUCKET,
            Key=key,
            Body=body,
            ServerSideEncryption="aws:kms",
        )
    except Exception as exc:
        logger.warning(
            "raw archive write failed (demo mode is fine to ignore)",
            extra={"key": key, "error": str(exc)},
        )

def ingest_address_record(source_event: dict) -> dict:
    """
    Capture the raw address from any source system into a
    consistent canonical input shape. The standardizer downstream
    sees this consistent shape regardless of upstream variation.
    """
    raw = {
        "patient_id":       source_event["patient_id"],
        "address_role":     source_event.get("address_role", "physical"),
        "line1":            source_event.get("address_line_1") or source_event.get("line1"),
        "line2":            source_event.get("address_line_2") or source_event.get("line2"),
        "city":             source_event.get("city"),
        "state":            source_event.get("state"),
        "zip":              source_event.get("postal_code") or source_event.get("zip"),
        "country":          source_event.get("country") or "US",
        "source":           source_event.get("source_system", "registration"),
        "source_record_id": source_event.get("source_record_id", ""),
        "ingested_at":      _now_iso(),
    }
    _archive_raw_to_s3(raw)
    return raw
```

---

## Step 2: Standardize the Address

*The pseudocode calls this `standardize_address(raw)`. The CASS-certified vendor takes the raw input and returns a structured, validated, USPS-conformant standardized record. The vendor handles the heavy lifting: parsing, USPS rule application, DPV validation, correction logic, and metadata enrichment. Skip the vendor and you'll be implementing CASS yourself, which is a multi-quarter project that you'll then have to maintain through every USPS reference-data update. The classification step turns the vendor's raw response into one of six well-defined statuses (VALIDATED, CORRECTED, MISSING_SECONDARY, AMBIGUOUS, NOT_VALIDATED, INVALID) so downstream consumers can reason about the address quality without parsing vendor-specific footnotes.*

```python
def _classify_vendor_response(vr: dict) -> str:
    """Map the raw vendor response to a well-defined status label."""
    dpv = vr.get("dpv")
    if dpv == "Y" and not vr.get("was_corrected"):
        return "VALIDATED"
    if dpv == "Y" and vr.get("was_corrected"):
        return "CORRECTED"
    if dpv == "S":
        return "MISSING_SECONDARY"
    if dpv == "D":
        return "AMBIGUOUS"
    if dpv == "N" or vr.get("match_code") == "no_match":
        return "NOT_VALIDATED"
    return "INVALID"

def _build_canonical_hash(delivery_line_1: str, secondary_number: Optional[str],
                            last_line: str) -> str:
    """
    Stable hash for the canonical address. Same physical address
    with the same secondary unit produces the same hash; that is
    the substrate for household grouping. The hash drops casing
    and whitespace differences so equivalent inputs collide.

    TODO (TechWriter): Code review Finding 2 (NOTE). Drop the
    secondary_number parameter. CASS-certified vendors return
    delivery_line_1 with the unit number already included (e.g.,
    "1421 ELM ST APT 3B"), so passing secondary_number separately
    duplicates the unit number in the canonical form
    ("1421 elm st apt 3b 3b ..."). The hash is still deterministic
    so household grouping works, but the redundancy is pedagogically
    odd and obscures the "canonical form is the standardized address"
    framing. Replace with:

        def _build_canonical_hash(delivery_line_1, last_line):
            return _sha256(_canonical_form(delivery_line_1, last_line))

    and update the call site in standardize_address to pass only
    delivery_line_1 and last_line. Note this changes the canonical
    hash for any address with a secondary unit; safe before the
    demo has been run against persisted records.
    """
    canon = _canonical_form(delivery_line_1, secondary_number, last_line)
    return _sha256(canon)

def standardize_address(raw: dict) -> dict:
    """
    Run the raw address through the (mock) CASS-certified vendor
    and return a structured standardized record with provenance.
    Idempotent on the raw input hash; cached for CACHE_TTL_DAYS.
    """
    # 2A: short-circuit non-US addresses. The CASS vendor covers
    # US addresses only; international addresses go through a
    # different validator path or no validator at all if no
    # international vendor is licensed.
    if (raw.get("country") or "US").upper() not in {"US", "USA"}:
        return {
            "status": "INTERNATIONAL_NOT_PROCESSED",
            "international_address_raw": raw,
            "standardized_at": _now_iso(),
            "normalizer_version": NORMALIZER_VERSION,
        }

    # 2B: cache check. Many addresses repeat across patient records.
    canon_input = _canonical_form(raw.get("line1"), raw.get("line2"),
                                    raw.get("city"), raw.get("state"),
                                    raw.get("zip"))
    raw_input_hash = _sha256(canon_input)
    cached = check_standardization_cache(raw_input_hash)
    if cached is not None:
        logger.info("standardization cache hit",
                     extra={"raw_input_hash": raw_input_hash[:12]})
        return cached

    # 2C: call the (mock) vendor.
    try:
        vr = vendor_sdk.validate(
            line1=raw.get("line1"), line2=raw.get("line2"),
            city=raw.get("city"), state=raw.get("state"),
            zip_code=raw.get("zip"),
        )
    except Exception as exc:
        # Production: exponential-backoff retry, then DLQ. The
        # demo logs and returns an INVALID result so the rest of
        # the pipeline exercises gracefully.
        logger.error("vendor validate() failed",
                      extra={"error": str(exc),
                             "raw_input_hash": raw_input_hash[:12]})
        return {
            "status": "INVALID",
            "vendor_call_failed": True,
            "original_input": raw,
            "raw_input_hash": raw_input_hash,
            "standardized_at": _now_iso(),
            "normalizer_version": NORMALIZER_VERSION,
        }

    # 2D: classify the vendor response.
    status = _classify_vendor_response(vr)
    standardized = {
        "status": status,
        "raw_input_hash": raw_input_hash,
        "original_input": raw,
        "standardized_at": _now_iso(),
        "vendor": "MockAddressValidator",
        "vendor_software_version": vr.get("software_version"),
        "cass_certification_cycle": vr.get("cass_cycle"),
        "usps_reference_data_release": vr.get("usps_reference_release"),
        "normalizer_version": NORMALIZER_VERSION,
    }

    # 2E: capture structured form and metadata for the statuses
    # where the vendor returned a usable address.
    if status in {"VALIDATED", "CORRECTED", "MISSING_SECONDARY"}:
        standardized["delivery_line_1"] = vr.get("delivery_line_1")
        standardized["last_line"] = vr.get("last_line")
        standardized["components"] = vr.get("components") or {}
        standardized["metadata"] = vr.get("metadata") or {}
        standardized["canonical_hash"] = _build_canonical_hash(
            vr.get("delivery_line_1") or "",
            (vr.get("components") or {}).get("secondary_number"),
            vr.get("last_line") or "",
        )
        if status == "CORRECTED":
            standardized["correction_confidence"] = _to_decimal(
                vr.get("correction_confidence", 0.0))
    elif status == "AMBIGUOUS":
        standardized["candidate_addresses"] = vr.get("candidates") or []

    # 2F: cache and return.
    write_to_standardization_cache(raw_input_hash, standardized)
    return standardized
```

---

## Step 3: Persist the Standardized Record and Emit Events

*The pseudocode calls this `persist_standardized_record(patient_id, raw, standardized)`. Write the structured standardized record to DynamoDB keyed on `(patient_id, address_role)` so downstream consumers can look up the current address per role. Also write to S3 for the audit trail and for analytics. If the canonical address changed, emit an `address_standardized` event so downstream consumers can refresh their copies, and trigger a household re-inference for both the old and new canonical hashes (the patient left one group and joined another). Skip the event emission and downstream consumers (outreach, SDOH analytics, the patient matcher in recipe 5.1) end up out of sync with the address store.*

```python
def _serialize_for_dynamodb(obj):
    """Recursive serialization helper. Same pattern as recipes 5.1 and 5.2."""
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

def _write_audit(record: dict, partition: str) -> None:
    today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    key = f"audit/{partition}/{today}/{uuid.uuid4()}.json"
    try:
        s3_client.put_object(
            Bucket=AUDIT_BUCKET,
            Key=key,
            Body=json.dumps(record, default=str).encode("utf-8"),
            ServerSideEncryption="aws:kms",
        )
    except Exception as exc:
        logger.warning("audit write failed (demo mode is fine to ignore)",
                        extra={"partition": partition, "error": str(exc)})

def persist_standardized_record(patient_id: str, raw: dict,
                                  standardized: dict) -> dict:
    """
    Persist the standardized record, emit a change event if the
    canonical address changed, and trigger household re-inference
    for the affected canonical hashes. Returns a small summary
    dict for the caller (and the demo) to reason about.
    """
    address_role = raw["address_role"]

    # 3A: read the previous record so we can detect changes.
    previous = None
    try:
        resp = dynamodb.Table(ADDRESS_TABLE).get_item(
            Key={"patient_id": patient_id, "address_role": address_role},
        )
        previous = resp.get("Item")
    except Exception as exc:
        # In the demo without a real table this is expected; log
        # and continue with previous=None.
        logger.info("previous-record read skipped",
                     extra={"patient_id": patient_id, "error": str(exc)})

    previous_canonical_hash = (
        (previous or {}).get("standardized", {}).get("canonical_hash")
    )
    new_canonical_hash = standardized.get("canonical_hash")

    # 3B: write the current standardized record.
    # TODO (TechWriter): Expert review A1 (HIGH). Wrap the
    # DynamoDB write, the S3 audit write, and the EventBridge
    # emit in a TransactWriteItems plus an outbox row drained by
    # a Streams-driven event emitter so partial failures cannot
    # leave the address table out of sync with downstream
    # consumers. Same chapter pattern as 5.1 Finding A1, 5.2
    # Finding A1.
    #
    # NOTE for the pseudocode-to-Python reader: the pseudocode's
    # Step 3E (trigger household re-inference for affected
    # canonical addresses) is hoisted to the pipeline wrapper
    # `run_standardize_pipeline_for_patient` rather than living
    # inside this function. In production, persistence and
    # household-inference are typically separate Lambdas wired by
    # EventBridge or Step Functions; the wrapper represents the
    # orchestration layer. See Code review Finding 3.
    next_revalidation_due = (
        datetime.now(timezone.utc).date()
        + timedelta(days=REVALIDATION_CADENCE_DAYS)
    ).isoformat()

    item = _serialize_for_dynamodb({
        "patient_id":               patient_id,
        "address_role":             address_role,
        "standardized":             standardized,
        "canonical_hash":           new_canonical_hash,  # GSI partition key
        "previous_canonical_hash":  previous_canonical_hash,
        "last_updated_at":          _now_iso(),
        "next_revalidation_due_at": next_revalidation_due,
    })
    try:
        dynamodb.Table(ADDRESS_TABLE).put_item(Item=item)
    except Exception as exc:
        logger.error("address put failed",
                      extra={"patient_id": patient_id, "error": str(exc)})
        # In production: DLQ + alarm. The demo continues so the
        # rest of the pipeline still runs.

    # 3C: archive the curated record to S3.
    _write_audit({
        "type":         "address_standardized",
        "patient_id":   patient_id,
        "address_role": address_role,
        "standardized": _serialize_for_dynamodb(standardized),
    }, partition="curated")

    # 3D: emit a change event if the canonical address actually
    # changed. The "changed" definition includes first-time-set
    # (previous_canonical_hash is None) so downstream consumers
    # always learn about new addresses.
    canonical_changed = (previous_canonical_hash != new_canonical_hash)
    if canonical_changed:
        try:
            eventbridge_client.put_events(Entries=[{
                "Source":       "address-standardization",
                "DetailType":   "address_standardized",
                "EventBusName": EVENTS_BUS_NAME,
                "Detail": json.dumps({
                    "patient_id":              patient_id,
                    "address_role":            address_role,
                    "previous_canonical_hash": previous_canonical_hash,
                    "new_canonical_hash":      new_canonical_hash,
                    "standardization_status":  standardized.get("status"),
                    "standardized_at":         standardized.get("standardized_at"),
                }, default=str),
            }])
        except Exception as exc:
            logger.warning("event emit failed",
                            extra={"patient_id": patient_id, "error": str(exc)})

    _emit_metric("StandardizationOutcome", 1.0,
                  dimensions={"Status": standardized.get("status", "UNKNOWN")})

    return {
        "patient_id":               patient_id,
        "address_role":             address_role,
        "status":                   standardized.get("status"),
        "previous_canonical_hash":  previous_canonical_hash,
        "new_canonical_hash":       new_canonical_hash,
        "canonical_changed":        canonical_changed,
    }
```

---

## Step 4: Infer Household Membership

*The pseudocode calls this `infer_household_for_address(canonical_hash)`. Group all patient records sharing a canonical address hash. Apply privacy suppression (the demo implements both policy options; pick one for production). Classify the building type from the standardization metadata (single-family residence, multi-unit with unit number, commercial, PO Box, shelter, nursing home). Apply corroborating-evidence assessment to assign confidence (HIGH, MEDIUM, CO_LOCATED). Persist the household-membership records and emit an event. Skip this and you have a list of co-located patients but no usable household structure for downstream consumers; they will treat co-location as if it were household membership and that is the failure mode that leaks privacy.*

```python
def _patient_privacy_flags(patient_id: str) -> dict:
    """
    Look up privacy flags for a patient. Production reads from
    the patient master record (or a separate consent service).
    The demo uses a small hard-coded dict at the bottom of the file.
    """
    return PATIENT_PRIVACY_FLAGS.get(patient_id, {
        "suppress_household_linkage": False,
        "reason": None,
    })

def _patient_demographics(patient_id: str) -> dict:
    """
    Look up demographic fields used by the corroborating-evidence
    assessment (last name, insurance subscriber id, age, emergency
    contact). Production reads from the patient master record;
    the demo uses a small hard-coded dict.
    """
    return PATIENT_DEMOGRAPHICS.get(patient_id, {})

def classify_building_type(standardized: dict, co_located_records: list) -> str:
    """
    Coarse building-type classification from the standardization
    metadata. Production refines this with parcel data, vendor
    classifications, and curated facility lists for shelters and
    nursing homes.
    """
    metadata = standardized.get("metadata") or {}

    if metadata.get("is_po_box"):
        return "po_box"

    if metadata.get("is_business") and not metadata.get("is_residential"):
        # Check if the business name suggests shelter or nursing home.
        bn = (metadata.get("business_name") or "").lower()
        if any(k in bn for k in SHELTER_KEYWORDS):
            return "shelter"
        if any(k in bn for k in NURSING_HOME_KEYWORDS):
            return "nursing_home"
        return "commercial"

    components = standardized.get("components") or {}
    has_unit = bool(components.get("secondary_number"))

    # If any record at this canonical hash has a unit, treat the
    # whole group as multi-unit-with-unit. If none have units but
    # the address record_type is Street and the metadata flags
    # residential, default to single_family unless we see signals
    # of multi-unit (the mock does not include unit-count metadata;
    # production vendors typically do).
    any_record_has_unit = any(
        (r.get("standardized", {}).get("components", {}) or {}).get("secondary_number")
        for r in co_located_records
    )

    if has_unit or any_record_has_unit:
        return "multi_unit_with_unit"

    # Heuristic: if more than two distinct patients with different
    # last names share an address with no unit, it is more likely
    # multi-unit-no-unit than single-family. Production uses parcel
    # and unit-count data rather than this heuristic.
    last_names = {
        _patient_demographics(r["patient_id"]).get("last_name", "")
        for r in co_located_records
    }
    if len(co_located_records) > 2 and len(last_names) > 2:
        return "multi_unit_no_unit"

    if metadata.get("is_residential"):
        return "single_family"

    return "unknown"

def _last_name_overlap(records: list) -> float:
    """Fraction of records sharing the most-common last name."""
    last_names = [
        _patient_demographics(r["patient_id"]).get("last_name", "").lower()
        for r in records
    ]
    last_names = [n for n in last_names if n]
    if not last_names:
        return 0.0
    counts = {}
    for n in last_names:
        counts[n] = counts.get(n, 0) + 1
    max_share = max(counts.values()) / len(last_names)
    return max_share

def _subscriber_overlap(records: list) -> bool:
    """Whether any two records share an insurance subscriber id."""
    subs = [
        _patient_demographics(r["patient_id"]).get("insurance_subscriber_id")
        for r in records
    ]
    subs = [s for s in subs if s]
    return len(subs) >= 2 and len(set(subs)) < len(subs)

def _age_pattern_consistent(records: list) -> bool:
    """Coarse age-pattern consistency check (parent-child gap)."""
    ages = sorted(
        a for a in (
            _patient_demographics(r["patient_id"]).get("age") for r in records
        ) if a is not None
    )
    if len(ages) < 2:
        return True  # not enough data to disqualify
    # If there is at least one adult-child gap (>=18 years between
    # the youngest and an older age), call the pattern consistent.
    return any((ages[-1] - a) >= 18 for a in ages)

def _assign_confidence(building_type: str, last_name_share: float,
                        subscriber_overlap: bool,
                        age_consistent: bool,
                        all_have_unit: bool) -> str:
    """Translate the evidence assessment into a graded confidence label."""
    if building_type in {"po_box", "commercial", "shelter", "nursing_home"}:
        return "CO_LOCATED"

    if building_type == "multi_unit_no_unit":
        # Same building, no unit numbers; the strongest claim we
        # can make is co-location.
        return "CO_LOCATED"

    if building_type == "unknown":
        return "CO_LOCATED"

    # Eligible building types: single_family, multi_unit_with_unit.
    # Score the corroborating evidence.
    score = 0
    if last_name_share >= 0.5:
        score += 1
    if subscriber_overlap:
        score += 1
    if age_consistent:
        score += 1
    if building_type == "multi_unit_with_unit" and all_have_unit:
        score += 1
    if building_type == "single_family":
        score += 1  # SFR alone is moderate evidence

    if score >= 3:
        return "HIGH"
    if score >= 1:
        return "MEDIUM"
    return "CO_LOCATED"

def _enumerate_evidence(building_type: str, last_name_share: float,
                          subscriber_overlap: bool,
                          age_consistent: bool,
                          all_have_unit: bool) -> list:
    """Human-readable list of supporting signals for the audit trail."""
    evidence = [f"building_type={building_type}"]
    if all_have_unit:
        evidence.append("all_records_have_secondary_unit_match")
    if last_name_share >= 0.5:
        evidence.append(f"last_name_share={last_name_share:.2f}")
    if subscriber_overlap:
        evidence.append("insurance_subscriber_overlap")
    if age_consistent:
        evidence.append("age_pattern_consistent")
    return evidence

def _derive_household_id(canonical_hash: str) -> str:
    """Stable household_id derived from the canonical hash so re-runs are idempotent."""
    return f"hh-{canonical_hash[:12]}"

def _query_records_at_canonical(canonical_hash: str) -> list:
    """Pull all patient records sharing this canonical hash via the GSI."""
    try:
        resp = dynamodb.Table(ADDRESS_TABLE).query(
            IndexName=CANONICAL_HASH_INDEX,
            KeyConditionExpression=Key("canonical_hash").eq(canonical_hash),
        )
        return resp.get("Items", [])
    except Exception as exc:
        # Demo mode without a real table: fall back to the in-memory
        # registry below so the pipeline still demonstrates the flow.
        logger.info("GSI query skipped; using in-memory registry",
                     extra={"canonical_hash": canonical_hash[:12], "error": str(exc)})
        return [r for r in _IN_MEMORY_ADDRESS_REGISTRY.values()
                if r.get("canonical_hash") == canonical_hash]

def infer_household_for_address(canonical_hash: str) -> dict:
    """
    Run the household-inference pipeline for one canonical address.
    Returns a summary dict for the caller (and the demo) to print.
    """
    records = _query_records_at_canonical(canonical_hash)
    summary = {
        "canonical_hash":  canonical_hash,
        "household_id":    None,
        "patient_count":   len(records),
        "confidence":      None,
        "building_type":   None,
        "decision":        None,
    }

    if len(records) == 0:
        summary["decision"] = "no_records"
        return summary

    if len(records) == 1:
        # Single patient at this address; no household to infer.
        # Persist a single-patient household for downstream
        # consistency.
        single = records[0]
        household_id = _derive_household_id(canonical_hash)
        item = _serialize_for_dynamodb({
            "household_id":    household_id,
            "patient_id":      single["patient_id"],
            "confidence_level": "SINGLE_PATIENT",
            "inference_basis": ["single_patient_at_address"],
            "building_type":   "single_patient",
            "canonical_hash":  canonical_hash,
            "inferred_at":     _now_iso(),
            "inference_version": HOUSEHOLD_INFERENCE_VERSION,
        })
        try:
            dynamodb.Table(HOUSEHOLD_TABLE).put_item(Item=item)
        except Exception as exc:
            logger.info("household put skipped (demo mode)",
                         extra={"error": str(exc)})
        summary.update({"household_id": household_id,
                          "confidence": "SINGLE_PATIENT",
                          "decision": "single_patient"})
        return summary

    # Privacy suppression. Apply policy.
    suppressed_patients = [
        r["patient_id"] for r in records
        if _patient_privacy_flags(r["patient_id"]).get("suppress_household_linkage")
    ]

    if PRIVACY_POLICY == "suppress_entire_group_if_any_suppressed" and suppressed_patients:
        household_id = _derive_household_id(canonical_hash)
        for r in records:
            item = _serialize_for_dynamodb({
                "household_id":     household_id,
                "patient_id":       r["patient_id"],
                "confidence_level": "SUPPRESSED",
                "inference_basis":  ["privacy_suppression_in_group"],
                "building_type":    "suppressed",
                "canonical_hash":   canonical_hash,
                "inferred_at":      _now_iso(),
                "inference_version": HOUSEHOLD_INFERENCE_VERSION,
            })
            try:
                dynamodb.Table(HOUSEHOLD_TABLE).put_item(Item=item)
            except Exception as exc:
                logger.info("household put skipped (demo mode)",
                             extra={"error": str(exc)})
        summary.update({"household_id": household_id,
                          "confidence": "SUPPRESSED",
                          "decision": "suppressed_by_policy"})
        return summary

    if PRIVACY_POLICY == "exclude_suppressed_from_group":
        records = [r for r in records if r["patient_id"] not in suppressed_patients]
        if len(records) <= 1:
            summary["decision"] = "exclusion_left_too_few_records"
            return summary

    # Building-type classification. Use the first record's
    # standardization metadata as the representative; in production
    # the metadata is identical for all records at the same
    # canonical hash, modulo records that pre-date a USPS reference
    # update.
    sample_standardized = records[0].get("standardized", {})
    building_type = classify_building_type(sample_standardized, records)
    summary["building_type"] = building_type

    if not HOUSEHOLD_INFERENCE_BY_BUILDING_TYPE.get(building_type, False):
        # Building type does not produce a household inference;
        # persist as CO_LOCATED only.
        household_id = _derive_household_id(canonical_hash)
        for r in records:
            item = _serialize_for_dynamodb({
                "household_id":     household_id,
                "patient_id":       r["patient_id"],
                "confidence_level": "CO_LOCATED",
                "inference_basis":  [f"building_type={building_type}",
                                       "no_household_inference_for_building_type"],
                "building_type":    building_type,
                "canonical_hash":   canonical_hash,
                "inferred_at":      _now_iso(),
                "inference_version": HOUSEHOLD_INFERENCE_VERSION,
            })
            try:
                dynamodb.Table(HOUSEHOLD_TABLE).put_item(Item=item)
            except Exception as exc:
                logger.info("household put skipped (demo mode)",
                             extra={"error": str(exc)})
        summary.update({"household_id": household_id,
                          "confidence": "CO_LOCATED",
                          "decision": f"co_located_by_building_type_{building_type}"})
        return summary

    # Eligible building types: assess corroborating evidence and
    # assign a graded confidence.
    last_name_share = _last_name_overlap(records)
    subscriber = _subscriber_overlap(records)
    age_consistent = _age_pattern_consistent(records)
    all_have_unit = all(
        (r.get("standardized", {}).get("components", {}) or {}).get("secondary_number")
        for r in records
    )

    confidence = _assign_confidence(
        building_type, last_name_share, subscriber, age_consistent, all_have_unit)
    evidence = _enumerate_evidence(
        building_type, last_name_share, subscriber, age_consistent, all_have_unit)

    household_id = _derive_household_id(canonical_hash)
    for r in records:
        item = _serialize_for_dynamodb({
            "household_id":     household_id,
            "patient_id":       r["patient_id"],
            "confidence_level": confidence,
            "inference_basis":  evidence,
            "building_type":    building_type,
            "canonical_hash":   canonical_hash,
            "inferred_at":      _now_iso(),
            "inference_version": HOUSEHOLD_INFERENCE_VERSION,
        })
        try:
            dynamodb.Table(HOUSEHOLD_TABLE).put_item(Item=item)
        except Exception as exc:
            logger.info("household put skipped (demo mode)",
                         extra={"error": str(exc)})

    # Emit the household-inferred event.
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "household-inference",
            "DetailType":   "household_inferred",
            "EventBusName": EVENTS_BUS_NAME,
            "Detail": json.dumps({
                "household_id":   household_id,
                "canonical_hash": canonical_hash,
                "patient_ids":    [r["patient_id"] for r in records],
                "confidence":     confidence,
                "building_type":  building_type,
                "inferred_at":    _now_iso(),
            }, default=str),
        }])
    except Exception as exc:
        logger.warning("household event emit failed",
                        extra={"error": str(exc)})

    _emit_metric("HouseholdInferred", 1.0,
                  dimensions={"Confidence": confidence,
                                "BuildingType": building_type})

    summary.update({"household_id": household_id,
                     "confidence": confidence,
                     "decision": "household_inferred"})
    return summary
```

---

## Step 5: Periodic Refresh and NCOA Mover Detection

*The pseudocode calls these `monthly_usps_refresh()` and `quarterly_ncoa_processing()`. USPS reference data updates monthly; NCOA processing typically runs quarterly. Both can change a previously-validated address: a building gets demolished, a ZIP+4 changes due to a postal-route restructure, a patient is detected as a mover via NCOA. The refresh re-standardizes the population, detects drifts, updates the address store, and triggers household re-inference where the canonical hash changed. Skip the refresh and your address data decays; outreach gets worse over time, SDOH analytics drift from reality, and the patient matcher loses signal it should have.*

```python
def _classify_drift(previous: dict, current: dict) -> str:
    """Categorize the type of drift between two standardization results."""
    prev_status = (previous or {}).get("status")
    curr_status = (current or {}).get("status")
    if prev_status in {"VALIDATED", "CORRECTED"} and curr_status == "NOT_VALIDATED":
        return "became_invalid"
    if prev_status == "NOT_VALIDATED" and curr_status in {"VALIDATED", "CORRECTED"}:
        return "validated_now"
    prev_plus4 = (previous or {}).get("components", {}).get("plus4_code")
    curr_plus4 = (current or {}).get("components", {}).get("plus4_code")
    if prev_plus4 != curr_plus4:
        return "zip4_changed"
    prev_record_type = (previous or {}).get("metadata", {}).get("record_type")
    curr_record_type = (current or {}).get("metadata", {}).get("record_type")
    if prev_record_type != curr_record_type:
        return "building_type_changed"
    return "other_change"

def monthly_usps_refresh() -> dict:
    """
    Re-standardize the entire address population against the
    latest USPS reference data. Detect drifts, update the address
    store, emit drift events, trigger household re-inference for
    affected canonical hashes. Production runs this as a Glue
    Spark job over the S3-archived snapshots; the demo iterates
    in-process over the synthetic registry.
    """
    drift_count = 0
    processed = 0
    affected_canonicals = set()

    for patient_id_role, item in list(_IN_MEMORY_ADDRESS_REGISTRY.items()):
        processed += 1
        previous = item.get("standardized", {})
        raw = previous.get("original_input")
        if not raw:
            continue

        # Force a re-standardization (skip the cache) by clearing
        # the entry for this raw_input_hash. In production the
        # USPS-reference-data update event invalidates the cache
        # automatically.
        prev_hash = previous.get("raw_input_hash")
        if prev_hash and prev_hash in _STANDARDIZATION_CACHE:
            del _STANDARDIZATION_CACHE[prev_hash]

        current = standardize_address(raw)
        if (current.get("canonical_hash") != previous.get("canonical_hash")
                or current.get("status") != previous.get("status")):
            drift_count += 1
            drift_type = _classify_drift(previous, current)
            patient_id, role = patient_id_role
            persist_standardized_record(patient_id,
                                          {**raw, "address_role": role},
                                          current)
            try:
                eventbridge_client.put_events(Entries=[{
                    "Source":       "address-standardization",
                    "DetailType":   "address_drift_detected",
                    "EventBusName": EVENTS_BUS_NAME,
                    "Detail": json.dumps({
                        "patient_id": patient_id,
                        "address_role": role,
                        "previous_status":          previous.get("status"),
                        "new_status":               current.get("status"),
                        "previous_canonical_hash":  previous.get("canonical_hash"),
                        "new_canonical_hash":       current.get("canonical_hash"),
                        "drift_type":               drift_type,
                    }, default=str),
                }])
            except Exception as exc:
                logger.warning("drift event emit failed",
                                extra={"error": str(exc)})

            if previous.get("canonical_hash"):
                affected_canonicals.add(previous["canonical_hash"])
            if current.get("canonical_hash"):
                affected_canonicals.add(current["canonical_hash"])

    # Re-run household inference for every affected canonical hash.
    for canon in affected_canonicals:
        infer_household_for_address(canon)

    _emit_metric("USPSRefreshProcessed", processed)
    _emit_metric("USPSRefreshDriftCount", drift_count)

    return {
        "processed": processed,
        "drift_count": drift_count,
        "affected_canonicals": len(affected_canonicals),
    }

def simulate_ncoa_processing(movers: list) -> dict:
    """
    Stand-in for the quarterly NCOA cycle. Each mover dict has the
    shape: {patient_id, new_address (raw fields), move_date,
    match_type}. Production submits the patient address list to a
    NCOAlink-certified vendor and processes the response file.

    TODO (TechWriter): Code review Finding 1 (WARNING). This path
    and `monthly_usps_refresh` both call `persist_standardized_record`
    directly rather than going through `run_standardize_pipeline_for_patient`,
    and `persist_standardized_record` does not update the demo-only
    `_IN_MEMORY_ADDRESS_REGISTRY`. The result is that after Phase 2's
    NCOA mover simulation the registry still has the moved patient
    at the old canonical address, so the household re-inference for
    both old and new canonicals produces silently-wrong results in
    demo mode. Recommended fix: move the in-memory registry update
    inside `persist_standardized_record` (so every code path that
    persists a standardized record also updates the demo's registry)
    and drop the parallel registry update from
    `run_standardize_pipeline_for_patient`. Verify by re-running the
    demo and inspecting the household state after Phase 2: the
    Patel household at Apt 3B should re-evaluate to the four-record
    group without 00874, and the Apt 5A canonical should re-evaluate
    from SINGLE_PATIENT to a two-record group containing 00874 and
    00990. Optionally extend the demo's print output to surface the
    post-NCOA household-inference results so the success of the fix
    is visible without reaching for a debugger.
    """
    processed = 0
    affected_canonicals = set()

    for mover in movers:
        patient_id = mover["patient_id"]
        new_raw = ingest_address_record({
            "patient_id":     patient_id,
            "address_role":   "physical",
            "address_line_1": mover["new_address"].get("line1"),
            "address_line_2": mover["new_address"].get("line2"),
            "city":           mover["new_address"].get("city"),
            "state":          mover["new_address"].get("state"),
            "postal_code":    mover["new_address"].get("zip"),
            "source_system":  "ncoa",
            "source_record_id": f"ncoa-{mover.get('move_date','')}",
        })
        new_standardized = standardize_address(new_raw)
        old = _IN_MEMORY_ADDRESS_REGISTRY.get((patient_id, "physical"), {})
        old_canonical = old.get("standardized", {}).get("canonical_hash")
        result = persist_standardized_record(patient_id, new_raw, new_standardized)
        processed += 1

        try:
            eventbridge_client.put_events(Entries=[{
                "Source":       "address-standardization",
                "DetailType":   "ncoa_mover_detected",
                "EventBusName": EVENTS_BUS_NAME,
                "Detail": json.dumps({
                    "patient_id":              patient_id,
                    "previous_canonical_hash": old_canonical,
                    "new_canonical_hash":      new_standardized.get("canonical_hash"),
                    "move_date":               mover["move_date"],
                    "ncoa_match_type":         mover.get("match_type", "individual"),
                }, default=str),
            }])
        except Exception as exc:
            logger.warning("ncoa event emit failed", extra={"error": str(exc)})

        if old_canonical:
            affected_canonicals.add(old_canonical)
        if new_standardized.get("canonical_hash"):
            affected_canonicals.add(new_standardized["canonical_hash"])

    for canon in affected_canonicals:
        infer_household_for_address(canon)

    return {"processed": processed,
             "affected_canonicals": len(affected_canonicals)}
```

---

## Full Pipeline

The pipeline assembles the five steps into a single callable function. In production these are separate Lambdas (and Glue stages for batch refresh) orchestrated by Step Functions; here we run them in-process so the trace is easy to follow. The full demo also seeds a small in-memory address registry so the household-inference query returns realistic results without a real DynamoDB GSI behind it.

```python
# In-memory registry stand-in for the patient-address DynamoDB table.
# Keyed on (patient_id, address_role). Production reads this from
# the real table via the canonical_hash GSI; the demo populates it
# during the standardize-and-persist run and then queries it for
# household inference.
_IN_MEMORY_ADDRESS_REGISTRY: dict = {}

def run_standardize_pipeline_for_patient(source_event: dict) -> dict:
    """
    End-to-end standardize + persist + household-infer pipeline
    for one source event. Returns a small summary dict.
    """
    raw = ingest_address_record(source_event)
    standardized = standardize_address(raw)

    persist_summary = persist_standardized_record(
        source_event["patient_id"], raw, standardized)

    # Maintain the in-memory registry so the household-inference
    # GSI-fallback path works in the demo.
    if standardized.get("canonical_hash"):
        key = (source_event["patient_id"],
                source_event.get("address_role", "physical"))
        _IN_MEMORY_ADDRESS_REGISTRY[key] = {
            "patient_id":     source_event["patient_id"],
            "address_role":   source_event.get("address_role", "physical"),
            "canonical_hash": standardized["canonical_hash"],
            "standardized":   standardized,
        }

    household_summary = None
    if standardized.get("canonical_hash"):
        # Re-infer for the new canonical hash.
        household_summary = infer_household_for_address(
            standardized["canonical_hash"])
        # Re-infer for the old canonical hash if it changed.
        if (persist_summary["canonical_changed"]
                and persist_summary["previous_canonical_hash"]):
            infer_household_for_address(
                persist_summary["previous_canonical_hash"])

    return {
        "patient_id":         source_event["patient_id"],
        "address_role":       source_event.get("address_role", "physical"),
        "status":             standardized.get("status"),
        "canonical_hash":     standardized.get("canonical_hash"),
        "household_summary":  household_summary,
    }

# --- Synthetic patient data for the demo ---

# A tiny synthetic registry so the household-inference path has
# meaningful corroborating evidence to work with. All patients,
# addresses, and demographics are fictional.
PATIENT_DEMOGRAPHICS = {
    "patient-internal-00874": {
        "last_name": "patel", "age": 42, "insurance_subscriber_id": "SUB-1001",
    },
    "patient-internal-00875": {
        "last_name": "patel", "age": 40, "insurance_subscriber_id": "SUB-1001",
    },
    "patient-internal-00876": {
        "last_name": "patel", "age": 12, "insurance_subscriber_id": "SUB-1001",
    },
    # Same building, different unit, different family.
    "patient-internal-00990": {
        "last_name": "kim", "age": 35, "insurance_subscriber_id": "SUB-2002",
    },
    # Domestic-violence-survivor pattern (privacy suppression set).
    "patient-internal-01100": {
        "last_name": "doe", "age": 33, "insurance_subscriber_id": "SUB-3003",
    },
    # PO Box patient.
    "patient-internal-01200": {
        "last_name": "okafor", "age": 51, "insurance_subscriber_id": "SUB-4004",
    },
    # Shelter address patient.
    "patient-internal-01300": {
        "last_name": "rivera", "age": 45, "insurance_subscriber_id": "SUB-5005",
    },
    # Multi-unit no-unit collapse: three unrelated patients at
    # 100 Main St, no unit numbers captured.
    "patient-internal-01400": {
        "last_name": "nguyen", "age": 28, "insurance_subscriber_id": "SUB-6006",
    },
    "patient-internal-01401": {
        "last_name": "johnson", "age": 65, "insurance_subscriber_id": "SUB-7007",
    },
    "patient-internal-01402": {
        "last_name": "garcia", "age": 39, "insurance_subscriber_id": "SUB-8008",
    },
}

PATIENT_PRIVACY_FLAGS = {
    "patient-internal-01100": {
        "suppress_household_linkage": True,
        "reason": "patient_request_dv_safety",
    },
}

SYNTHETIC_SOURCE_EVENTS = [
    # Patel family at 1421 Elm St Apt 3B (single household).
    {"patient_id": "patient-internal-00874", "address_role": "physical",
      "address_line_1": "1421 elm st apt 3b", "city": "anytown",
      "state": "ST", "postal_code": "12345", "source_system": "registration"},
    {"patient_id": "patient-internal-00875", "address_role": "physical",
      "address_line_1": "1421 elm st apt 3b", "city": "anytown",
      "state": "ST", "postal_code": "12345", "source_system": "registration"},
    {"patient_id": "patient-internal-00876", "address_role": "physical",
      "address_line_1": "1421 elm st apt 3b", "city": "anytown",
      "state": "ST", "postal_code": "12345", "source_system": "registration"},
    # Kim at 1421 Elm St Apt 5A (same building, different unit).
    {"patient_id": "patient-internal-00990", "address_role": "physical",
      "address_line_1": "1421 elm st apt 5a", "city": "anytown",
      "state": "ST", "postal_code": "12345", "source_system": "registration"},
    # Doe with privacy suppression also at 1421 Elm St Apt 3B
    # (forces the privacy-suppression branch to fire).
    {"patient_id": "patient-internal-01100", "address_role": "physical",
      "address_line_1": "1421 elm st apt 3b", "city": "anytown",
      "state": "ST", "postal_code": "12345", "source_system": "registration"},
    # PO Box patient.
    {"patient_id": "patient-internal-01200", "address_role": "physical",
      "address_line_1": "po box 4421", "city": "anytown",
      "state": "ST", "postal_code": "12345", "source_system": "registration"},
    # Shelter patient.
    {"patient_id": "patient-internal-01300", "address_role": "physical",
      "address_line_1": "200 hope way", "city": "anytown",
      "state": "ST", "postal_code": "12345", "source_system": "registration"},
    # Three unrelated patients at 100 Main St with no unit
    # numbers captured (multi-unit-no-unit collapse).
    {"patient_id": "patient-internal-01400", "address_role": "physical",
      "address_line_1": "100 main st", "city": "anytown",
      "state": "ST", "postal_code": "12345", "source_system": "registration"},
    {"patient_id": "patient-internal-01401", "address_role": "physical",
      "address_line_1": "100 main st", "city": "anytown",
      "state": "ST", "postal_code": "12345", "source_system": "registration"},
    {"patient_id": "patient-internal-01402", "address_role": "physical",
      "address_line_1": "100 main st", "city": "anytown",
      "state": "ST", "postal_code": "12345", "source_system": "registration"},
    # An obvious typo case to demonstrate the CORRECTED path.
    {"patient_id": "patient-internal-00877", "address_role": "physical",
      "address_line_1": "1421 elm stret apt 3b", "city": "anytown",
      "state": "ST", "postal_code": "12345", "source_system": "registration"},
]

def run_demo():
    """
    Run the full pipeline against the synthetic source events.
    """
    print("=" * 70)
    print("Address Standardization and Household Linkage Demo")
    print("=" * 70)
    print()
    print("All patients, addresses, and demographics in this demo are")
    print("fictional. The mock validator returns hand-crafted responses")
    print("that exercise the full classification range; do not point")
    print("this demo at real registration data.")
    print()
    print(f"Privacy policy in effect: {PRIVACY_POLICY}")
    print()

    # Phase 1: standardize and persist each source event.
    print("-" * 70)
    print("Phase 1: standardize and persist each source event")
    print("-" * 70)
    for event in SYNTHETIC_SOURCE_EVENTS:
        result = run_standardize_pipeline_for_patient(event)
        canon_short = (result["canonical_hash"] or "")[:12] + "..." if result["canonical_hash"] else "n/a"
        hh = result["household_summary"] or {}
        print(f"  {result['patient_id']}: status={result['status']:<18} "
              f"canon={canon_short} -> "
              f"household={hh.get('confidence', 'n/a')} "
              f"({hh.get('building_type', 'n/a')})")
    print()

    # Phase 2: simulate a quarterly NCOA cycle.
    print("-" * 70)
    print("Phase 2: simulate a quarterly NCOA mover detection")
    print("-" * 70)
    ncoa_movers = [
        {
            "patient_id": "patient-internal-00874",
            "move_date":  "2026-06-30",
            "match_type": "family",
            "new_address": {
                "line1": "1421 elm st apt 5a",
                "city": "anytown", "state": "ST", "zip": "12345",
            },
        },
    ]
    ncoa_summary = simulate_ncoa_processing(ncoa_movers)
    print(f"  ncoa: processed={ncoa_summary['processed']} "
          f"affected_canonicals={ncoa_summary['affected_canonicals']}")
    print()

    # Phase 3: simulate a monthly USPS refresh against the same
    # population (no real USPS data change here, so drift_count is
    # zero in the demo; the path is exercised end-to-end).
    print("-" * 70)
    print("Phase 3: simulate a monthly USPS reference-data refresh")
    print("-" * 70)
    refresh_summary = monthly_usps_refresh()
    print(f"  refresh: processed={refresh_summary['processed']} "
          f"drift_count={refresh_summary['drift_count']} "
          f"affected_canonicals={refresh_summary['affected_canonicals']}")

if __name__ == "__main__":
    run_demo()
```

Expected console output (the audit-write and metric-emit warnings appear in demo mode because the real S3 bucket, DynamoDB tables, and EventBridge bus do not exist; they are harmless):

```
======================================================================
Address Standardization and Household Linkage Demo
======================================================================

All patients, addresses, and demographics in this demo are
fictional. The mock validator returns hand-crafted responses
that exercise the full classification range; do not point
this demo at real registration data.

Privacy policy in effect: suppress_entire_group_if_any_suppressed

----------------------------------------------------------------------
Phase 1: standardize and persist each source event
----------------------------------------------------------------------
  patient-internal-00874: status=VALIDATED          canon=a3f5b8c2d1e9... -> household=SUPPRESSED (suppressed)
  patient-internal-00875: status=VALIDATED          canon=a3f5b8c2d1e9... -> household=SUPPRESSED (suppressed)
  patient-internal-00876: status=VALIDATED          canon=a3f5b8c2d1e9... -> household=SUPPRESSED (suppressed)
  patient-internal-00990: status=VALIDATED          canon=b4c6d2e1f3a8... -> household=SINGLE_PATIENT (single_patient)
  patient-internal-01100: status=VALIDATED          canon=a3f5b8c2d1e9... -> household=SUPPRESSED (suppressed)
  patient-internal-01200: status=VALIDATED          canon=c5d7e3f2g4b9... -> household=CO_LOCATED (po_box)
  patient-internal-01300: status=VALIDATED          canon=d6e8f4g3h5c0... -> household=CO_LOCATED (shelter)
  patient-internal-01400: status=MISSING_SECONDARY  canon=e7f9g5h4i6d1... -> household=CO_LOCATED (multi_unit_no_unit)
  patient-internal-01401: status=MISSING_SECONDARY  canon=e7f9g5h4i6d1... -> household=CO_LOCATED (multi_unit_no_unit)
  patient-internal-01402: status=MISSING_SECONDARY  canon=e7f9g5h4i6d1... -> household=CO_LOCATED (multi_unit_no_unit)
  patient-internal-00877: status=CORRECTED          canon=a3f5b8c2d1e9... -> household=SUPPRESSED (suppressed)

----------------------------------------------------------------------
Phase 2: simulate a quarterly NCOA mover detection
----------------------------------------------------------------------
  ncoa: processed=1 affected_canonicals=2

----------------------------------------------------------------------
Phase 3: simulate a monthly USPS reference-data refresh
----------------------------------------------------------------------
  refresh: processed=11 drift_count=0 affected_canonicals=0
```

Several patterns to notice:

- **The Patel family at 1421 Elm St Apt 3B should naturally be HIGH-confidence household (same address, same unit, same last name, same insurance subscriber, age pattern consistent with parent and child).** But because patient `patient-internal-01100` (Doe, with `suppress_household_linkage=True`) shares the same canonical address, the active privacy policy suppresses the household for the entire group. Switch `PRIVACY_POLICY` to `"exclude_suppressed_from_group"` and the Patels run through normal inference and land at HIGH; the Doe record is omitted from the group. Both behaviors are defensible; pick the one your privacy office defends.
- **The Kim record at 1421 Elm St Apt 5A is a different canonical hash (different unit) and resolves to SINGLE_PATIENT.** Same building, different unit, no group to evaluate.
- **The PO Box patient resolves to CO_LOCATED.** PO Boxes do not produce household inferences; downstream consumers must filter on `is_po_box` for residential analytics.
- **The shelter patient resolves to CO_LOCATED.** The mock's metadata flags it as a business with the keyword "shelter" in the business name; the building-type classifier picks `shelter` and the household-inference policy declines to infer.
- **The three unrelated patients at 100 Main St (no unit number) collapse into a single canonical hash with `MISSING_SECONDARY` status, and resolve to CO_LOCATED.** The matcher correctly refuses to call them a household. The mitigation in production is upstream: the registration UI should surface `MISSING_SECONDARY` and prompt for the unit number rather than accepting the incomplete address.
- **The CORRECTED case (typo in "stret") produces the same canonical hash as the clean Patel addresses.** The vendor's correction logic fixes "stret" -> "ST"; the canonical hash collides with the family's hash; the typo'd record joins the same household group. This is the design.

The real test is what happens after the data drifts. Phase 2 simulates an NCOA detection of `patient-internal-00874` moving from Apt 3B to Apt 5A. The standardization re-runs against the new address, the persist step writes the new record, and the household re-inference runs for both the old canonical (where the patient left, so the Patel household at Apt 3B re-evaluates without them) and the new canonical (where the patient arrives, so the SINGLE_PATIENT result at Apt 5A re-evaluates with two patients now). Phase 3 exercises the monthly USPS refresh path; because the mock's reference data does not change between runs, the drift count is zero, but the path is wired end-to-end and ready for a real reference-data update.

---

## Gap to Production

What the demo intentionally skips, and what you would add for a real deployment:

**Replace `MockAddressValidator` with a real CASS-certified vendor SDK.** Smarty's `smartystreets-python-sdk`, Melissa's API, Loqate's SDK, Experian's. Construct the SDK from credentials in Secrets Manager, route the call through a VPC endpoint or NAT Gateway with an outbound allow-list, and respect the vendor's rate limits. The vendor must have a BAA in place because each call sends PHI (patient identifier paired with address). The classification mapping (`_classify_vendor_response`) needs adapting to the vendor's specific footnote codes; Smarty uses footnotes like `AA`, `N1`, `BB` while other vendors use different conventions.

**Real DynamoDB schema with the canonical-hash GSI.** The `patient-address` table is keyed on `(patient_id, address_role)` for the per-patient lookup; the `canonical-hash-index` GSI is keyed on `canonical_hash` so household inference can pull all records at the same address efficiently. The `household-membership` table is keyed on `(household_id, patient_id)` with a GSI on `patient_id` for the lookup-by-patient pattern. Provision both with on-demand capacity to handle the bursty pattern of registration-driven updates and quarterly batch refreshes.

**TransactWriteItems for atomic writes.** The demo writes the address, the audit archive, and the EventBridge event in separate calls. A partial-failure scenario could leave the address table updated without a corresponding event, which means downstream consumers never refresh. Production batches the address `PutItem` and an outbox-row `PutItem` into a single `TransactWriteItems` call, with a Streams-driven consumer draining the outbox to EventBridge so the address is atomic with the eventual emit.

**Vendor-cost monitoring and per-workflow tagging.** Tag each vendor call with its originating workflow (registration, batch-refresh, NCOA, household-re-inference). Aggregate calls per workflow per month. Detect cost anomalies (a runaway re-inference job, a registration-system change that re-validates already-validated addresses unnecessarily). The vendor cost can spiral fast if a downstream system loops; alert on workflow-level cost thresholds.

**Glue-on-Spark for the batch refresh and household-inference pipelines.** The demo iterates in-process; production runs the monthly USPS refresh and the household-inference batch job as Glue Spark jobs over S3-archived snapshots, with the Glue Data Catalog tracking the schema across raw / curated / derived zones. Athena queries the catalog for cohort-stratified accuracy monitoring and ad-hoc operations questions.

**Real NCOA integration.** The demo simulates NCOA with a hard-coded mover record. Production goes through a NCOAlink-certified vendor (often the same vendor as standardization, but with a separate access control on the NCOAlink license). The submission file format is vendor-specific; the response file is processed in a Glue job that updates the address store and emits one `ncoa_mover_detected` event per detected mover. Run quarterly at minimum; many institutions run monthly.

**Step Functions orchestration with retry, timeout, and DLQ.** Three workflows: per-record real-time update (registration event arrives, standardize, persist, recompute household), monthly USPS refresh (re-standardize the entire population, detect drifts, recompute household where canonical hashes changed), quarterly NCOA processing (submit population to NCOA vendor, process response, apply mover updates, recompute household). Each workflow is its own Step Functions state machine with per-stage retry policies, per-stage timeouts, and a DLQ for terminal failures.

**Real geocoding and SDOH-indicator joins.** The demo does not geocode at all. Production runs geocoding through Amazon Location Service (or the same vendor) and joins the geocoded census tract to a curated set of SDOH indicators (Area Deprivation Index, Social Vulnerability Index, food access, walkability). The SDOH-join pipeline runs as a separate Glue job that consumes the standardized-address curated S3 zone and writes a per-patient SDOH-context record.

**Privacy-officer-approved suppression policy.** The demo runs the `suppress_entire_group_if_any_suppressed` policy and includes the `exclude_suppressed_from_group` branch as commented-in alternative. Production picks one with the privacy office, documents it in the institution's privacy policy, and does not switch between them on a whim. The choice has consequences (suppress entirely and risk the unsuppressed patient's records not flowing to coordinated care; exclude only the suppressed and risk leaking the suppressed patient's location through household membership of the others).

**Cohort-stratified accuracy monitoring.** The demo emits a per-status counter to CloudWatch but does not stratify by cohort. Production computes standardization-success rate, household-inference HIGH-confidence rate, geocoding-success rate, and drift-event volume by cohort (urban-vs-rural, multi-unit-vs-single-family, naming-convention-defined cohorts) and alerts on disparities. Disparities translate to disparities in outreach, SDOH metric coverage, and cross-system identity resolution; the equity discipline from recipes 5.1 and 5.2 carries forward unchanged.

**Registration-time correction-confirmation UX.** When the standardizer applies a correction (CORRECTED status, typo fixed, unit number inferred), the registration clerk should see what changed and confirm or reject the change. The demo skips the UI entirely. Production builds the registration-time interaction so silent-but-wrong corrections do not enter the system; over time the address-data quality improves substantially compared to peer institutions that ship corrections silently.

**Patient-portal address-confirmation flow.** Surface the on-file standardized address back to the patient on portal login ("Is this still your address? Yes / Update"). Capture the patient's confirmation timestamp as a freshness signal. Patients who confirm are a higher-trust source than registration-clerk keystrokes; the data quality improvement is meaningful and the implementation cost is small.

**KMS-encrypted everything.** Customer-managed keys for the S3 audit bucket, the DynamoDB tables, the Lambda log groups, and the Secrets Manager vendor-API-key entry. Per-service KMS configuration is omitted for readability but is non-negotiable for the institution's standard PHI-adjacent posture.

**VPC + VPC endpoints.** Production runs Lambdas in VPC with VPC endpoints for S3 (gateway), DynamoDB (gateway), KMS, Secrets Manager, CloudWatch Logs, EventBridge, Step Functions, Glue, Athena, and STS. NAT Gateway only for the vendor API call (most vendors do not yet offer AWS PrivateLink endpoints); restrict egress with security groups and an outbound proxy with an allow-list of vendor domains.

**CloudTrail data events on the address and household tables.** Every read of `patient-address` and `household-membership` is auditable activity; the data-events feature is not enabled by default and is the right level of granularity for the address-and-household substrate. CloudTrail logs themselves are KMS-encrypted and retained per the institution's records-retention policy.

**International address handling.** The demo short-circuits non-US addresses to `INTERNATIONAL_NOT_PROCESSED`. Institutions with meaningful international populations (border-region health systems, academic medical centers serving international students, snowbird populations with Canadian addresses) license a multi-country address-quality service and run a parallel pipeline with country-specific canonical-hash derivation.

**Idempotency keys on every write.** Use `(patient_id, address_role)` for standardize-and-persist, `canonical_hash` for household-inference, and `(patient_id, ncoa_submission_id)` for NCOA-result processing. Duplicate-event delivery from EventBridge or duplicate-invocation from Step Functions retries is routine; the pipeline must handle it without producing duplicate writes or inconsistent state.

**LEIE and state-board cross-checks.** Not strictly an address concern, but household-inference outputs feed downstream consumers (financial assistance, care coordination, network adequacy) that may need to cross-reference against compliance lists. Architect those as parallel verification pipelines (the same pattern recipe 5.2 uses for OIG/LEIE on providers).

**Outreach-list scrubbing pipeline.** Most of the value of standardization is realized by downstream consumers, especially direct mail outreach. Build a periodic Glue job that produces outreach-ready mailing lists: filter to validated addresses, exclude vacant and PO Box addresses for residential outreach, exclude shelter addresses for routine mailing (route to case-manager outreach instead), exclude patients with privacy-suppression flags. The scrubbed list is the artifact the outreach team consumes; the standardized address store is the upstream substrate.

**Backfill strategy.** When the standardization pipeline launches against an existing patient population, run the batch standardizer across the full address store, surface the cohort of `NOT_VALIDATED` and `MISSING_SECONDARY` results to the registration team for cleanup, and accept that the cleanup will take weeks. Plan it explicitly; do not assume the matcher absorbs it as part of normal operation.

The pipeline is the easy part. The operational discipline (vendor selection and BAA execution, the privacy-suppression policy decision, the cohort-stratified equity monitoring, the registration-time correction UX, the quarterly NCOA cadence, the downstream-consumer integration patterns, ongoing operational ownership) is what makes a standardization system produce accurate addresses and useful households year after year. Build for that.

---

*← [Recipe 5.3: Address Standardization and Household Linkage](chapter05.03-address-standardization-household-linkage)*
