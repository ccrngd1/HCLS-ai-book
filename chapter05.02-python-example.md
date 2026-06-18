# Recipe 5.2: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 5.2. It shows one way you could translate the provider-NPI matching pattern into working Python using the public NPI Registry API for individual lookups, `jellyfish` for the string-similarity functions reused from recipe 5.1, Amazon DynamoDB for the assignment, schedule, and review-queue tables, Amazon S3 for the audit archive, Amazon EventBridge for downstream assignment-and-drift events, and Amazon CloudWatch for operational metrics. It is not production-ready. There is no real credentialing or HR feed (the demo seeds a small in-memory roster of synthetic internal provider records), no Splink or Spark-based batch pipeline (the demo runs an in-process candidate generator plus scorer that talks to the registry API one record at a time and would not survive a 50,000-provider monthly batch refresh), no OpenSearch-backed candidate index over a downloaded NPPES extract, no USPS address standardization (the demo uses a coarse regex normalizer), no NUCC taxonomy hierarchy (the demo compares taxonomy codes as flat strings), no EM-based m/u estimation (the demo uses hand-set probabilities to keep the math visible), no review-queue UI, and no IAM, KMS, VPC, or CloudTrail wiring. Think of it as the sketchpad version: useful for understanding the shape of a registry-anchored matching pipeline that respects the structured-then-narrative flow, the three-bucket routing pattern with margin requirement, the drift-snapshot-and-re-verify discipline, and the audit-everything posture. It is not something you would point at a live credentialing pipeline on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the six core pseudocode steps from the main recipe: normalize each NPPES registry record (the same pipeline you would run over the monthly Downloadable File, applied here to API responses for readability); normalize each internal provider record so the two sides share a canonical schema; generate candidate NPIs through multiple registry lookups (license-plus-state, name-plus-state, taxonomy-plus-state, ZIP-plus-name, phone-last-4); score each candidate against the internal record with per-field comparators, hard filters (deactivation, type mismatch, license-state mismatch), and a hand-rolled Fellegi-Sunter combiner; route each scored result by absolute threshold and top-vs-runner-up margin into auto-attach, review, or auto-non-match; and persist the assignment with a drift snapshot, schedule the next re-verification, and emit downstream events. The synthetic providers in the demo are fictional; the NPIs the demo "matches" against are placeholder values, not real registrations. Do not treat any specific NPI in the sample output as a real provider.

---

## Setup

You will need the AWS SDK for Python plus the same string-similarity libraries used in recipe 5.1 and a small HTTP client for the NPI Registry API:

```bash
pip install boto3 jellyfish requests python-dateutil
```

`jellyfish` provides the Jaro-Winkler, Damerau-Levenshtein, and metaphone implementations used in the comparators (same library used in recipe 5.1). `requests` is used for the NPI Registry API calls in the real-time-onboarding code path. `python-dateutil` provides permissive date parsing for the `last_update_date` and deactivation-date fields the registry returns.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchWriteItem` on the `provider-npi-assignment`, `verification-schedule`, and `provider-review-queue` tables
- `s3:PutObject` on the audit-archive bucket
- `events:PutEvents` on the assignment-and-drift events bus
- `cloudwatch:PutMetricData` for the queue-depth, auto-attach-rate, drift-volume, and re-verification-SLA metrics

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review.

A few things worth knowing upfront:

- **Provider data is generally lower-sensitivity than patient data, but the matching artifacts are not.** Provider names and practice addresses appear in public directories. License numbers, however, are sensitive enough that the institution likely treats them as restricted; the assignment table also holds the matched NPI's drift snapshot, which is fine to surface to operations but not appropriate to leak to the open internet. Apply the same encryption and access discipline you would for the patient-matching infrastructure.
- **DynamoDB rejects Python `float`.** Every probability, similarity score, and likelihood ratio passes through `Decimal` on its way in and on its way out. Same gotcha as recipe 5.1; the same `_to_decimal` helper handles it.
- **The NPI Registry API is rate-limited and best-effort.** For the real-time-onboarding code path the demo demonstrates, the API works fine. For batch matching across thousands of internal records, do not iterate API calls; download the NPPES Downloadable File, convert to parquet, and run the matching against the local copy. The demo includes a `_npi_registry_lookup` helper that talks to the API but caps usage so you do not accidentally rate-limit yourself during testing.
- **NPPES is self-attested and lagging.** Even with an authoritative registry, the registry's view of the provider is whatever the provider last attested. Practice addresses, taxonomies, and contact info drift between attestations. The drift-detection step is what catches this; do not skip it.
- **Hand-set m/u probabilities, not EM-estimated.** The probabilistic scorer below uses fixed `m` and `u` values per (field, comparison_level) pair. They are reasonable starting values illustrative of what an EM-trained model produces, but they are not tuned to your data. Production fits them with `splink` or the `recordlinkage` library on a labeled gold set.
- **No credentialing-system integration.** The demo seeds an in-memory list of synthetic internal provider records, runs the full pipeline on each, and prints the results. A production deployment ingests from a credentialing system (Symplr, Echo, MedTrainer, Modio, Verifiable, or institution-internal), runs in real time when a new provider is onboarded, and runs a monthly batch job against the historical roster.
- **The example collapses Step Functions, Lambda, and EventBridge into a single Python file for readability.** In production the normalize, candidate-generate, score, route, and attach stages are separate Lambda functions, orchestrated by Step Functions, with their own error handling, retries, and DLQs.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Field weights, m/u probabilities, blocking-pass definitions, routing thresholds, and the re-verification cadence are the knobs you would change between environments.

```python
import hashlib
import json
import logging
import math
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import boto3
import jellyfish
import requests
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from dateutil import parser as dateparser

# Structured logging. In production, ship JSON-formatted records to
# CloudWatch Logs Insights. Provider data is less sensitive than
# patient data but license numbers and personal addresses still
# warrant care; log structural metadata only (record IDs, scores,
# routing decisions, NPIs as identifiers), never raw demographic
# fields.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from DynamoDB, EventBridge,
# CloudWatch, and the NPI Registry API. Real-time onboarding has
# a tight latency budget; transient throttling should not fail the
# whole NPI assignment.
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
ASSIGNMENT_TABLE      = "provider-npi-assignment"
SCHEDULE_TABLE        = "verification-schedule"
REVIEW_QUEUE_TABLE    = "provider-review-queue"
AUDIT_BUCKET          = "my-provider-matching-audit"
EVENTS_BUS_NAME       = "provider-npi-events"
CLOUDWATCH_NAMESPACE  = "Provider/NPIMatching"

# Deploy-time guardrail.
# TODO (TechWriter): Code review F8 (NOTE). Extend the guardrail
# to cover every resource-name constant (ASSIGNMENT_TABLE,
# SCHEDULE_TABLE, REVIEW_QUEUE_TABLE, AUDIT_BUCKET, EVENTS_BUS_NAME,
# CLOUDWATCH_NAMESPACE) so a missing value produces an actionable
# assertion message rather than a downstream boto3 ValidationException.
assert AUDIT_BUCKET != "", "AUDIT_BUCKET must be set before deploying."

# --- NPI Registry API ---
# The public NPI Registry API is published by CMS at this base URL.
# It is unauthenticated, free to use, and rate-limited. For batch
# workloads, do not iterate API calls; use the monthly Downloadable
# File instead. 
NPI_REGISTRY_BASE_URL = "https://npiregistry.cms.hhs.gov/api/"
NPI_REGISTRY_API_VERSION = "2.1"
NPI_REGISTRY_TIMEOUT_SECONDS = 5
NPI_REGISTRY_MAX_RESULTS_PER_QUERY = 50
# TODO (TechWriter): Code review F7 (NOTE). The public NPI Registry
# API supports a `limit` of up to 200 per query; setting 50 silently
# truncates common-surname searches. Raise to 200 (the public
# maximum) and optionally add `skip`-based pagination in
# `_npi_registry_lookup` for queries that hit the cap.

# --- Versioning ---
NORMALIZER_VERSION = "norm-provider-v1.0"
MODEL_VERSION      = "fs-provider-v1.0"

# --- Routing Thresholds and Margin ---
# The composite score is a Fellegi-Sunter log-likelihood ratio
# (sum of per-field log(m/u) and log((1-m)/(1-u)) terms). Higher
# is more confident match. The margin requirement is what catches
# the "two Sarah Patels in California" confounder that pure
# absolute thresholds miss: a top score that barely beats the
# runner-up should not auto-attach even if it clears the high
# threshold. Tune all three against a labeled gold set.
HIGH_THRESHOLD = Decimal("8.0")    # at or above: candidate for auto-attach
LOW_THRESHOLD  = Decimal("-2.0")   # at or below: auto-non-match
MIN_MARGIN     = Decimal("3.0")    # required gap between top and runner-up

# --- Re-Verification Cadence ---
# Network adequacy regulations commonly require verification every
# 90 days; the architecture should support per-segment cadences in
# production (Medicare Advantage stricter, Medicaid varying by
# state). The demo uses a single cadence for clarity.
VERIFICATION_CADENCE_DAYS = 90

# --- Candidate Cap ---
# Internal records that produce more than this many candidates
# (very common surnames in dense states with no license-number
# field) route directly to review rather than auto-deciding. The
# cap protects against false-positive auto-attaches in low-
# information cases.
MAX_CANDIDATES_BEFORE_REVIEW = 50

# --- Fellegi-Sunter Probabilities ---
#
# m_probabilities[field][comparison_level] = P(observe this comparison
#   level | the internal record and the registry record are about the
#   same provider).
# u_probabilities[field][comparison_level] = P(observe this comparison
#   level | the records are about different providers).
#
# Provider data is cleaner than patient data and the registry is
# authoritative, so the m values for stable fields (license number,
# legal name) are higher and the u values are lower than the
# corresponding patient-matching priors. License-number-plus-state
# match is the strongest signal in the pipeline.
M_PROBABILITIES = {
    "first_name": {
        "exact":             Decimal("0.90"),
        "jaro_winkler_high": Decimal("0.06"),
        "metaphone_match":   Decimal("0.02"),
        "other_name_match":  Decimal("0.01"),  # via NPPES other-names field
        "mismatch":          Decimal("0.01"),
    },
    "last_name": {
        "exact":             Decimal("0.85"),
        "damerau_high":      Decimal("0.06"),
        "metaphone_match":   Decimal("0.04"),
        "other_name_match":  Decimal("0.04"),  # legal name change pattern
        "mismatch":          Decimal("0.01"),
    },
    "credential": {
        "exact_set_match":   Decimal("0.70"),
        "subset_match":      Decimal("0.25"),  # internal subset of registry
        "mismatch":          Decimal("0.04"),
        "one_null":          Decimal("0.01"),
    },
    "license": {
        "exact_number_and_state": Decimal("0.95"),
        "number_only_match":      Decimal("0.02"),
        "state_only_match":       Decimal("0.01"),
        "mismatch":               Decimal("0.01"),
        "one_null":               Decimal("0.01"),
    },
    "taxonomy": {
        "primary_match":     Decimal("0.65"),
        "any_match":         Decimal("0.20"),
        "parent_match":      Decimal("0.10"),  # NUCC parent taxonomy
        "mismatch":          Decimal("0.04"),
        "internal_unknown":  Decimal("0.01"),
    },
    "address": {
        "exact":             Decimal("0.40"),
        "same_zip":          Decimal("0.30"),
        "same_state":        Decimal("0.20"),
        "mismatch":          Decimal("0.05"),
        "one_null":          Decimal("0.05"),
    },
    "phone": {
        "exact":             Decimal("0.35"),
        "last_4_match":      Decimal("0.15"),
        "mismatch":          Decimal("0.30"),
        "one_null":          Decimal("0.20"),
    },
}

U_PROBABILITIES = {
    "first_name": {
        "exact":             Decimal("0.005"),
        "jaro_winkler_high": Decimal("0.02"),
        "metaphone_match":   Decimal("0.05"),
        "other_name_match":  Decimal("0.005"),
        "mismatch":          Decimal("0.92"),
    },
    "last_name": {
        "exact":             Decimal("0.002"),
        "damerau_high":      Decimal("0.005"),
        "metaphone_match":   Decimal("0.01"),
        "other_name_match":  Decimal("0.003"),
        "mismatch":          Decimal("0.98"),
    },
    "credential": {
        "exact_set_match":   Decimal("0.10"),
        "subset_match":      Decimal("0.10"),
        "mismatch":          Decimal("0.78"),
        "one_null":          Decimal("0.02"),
    },
    "license": {
        "exact_number_and_state": Decimal("0.00001"),  # essentially unique
        "number_only_match":      Decimal("0.0001"),
        "state_only_match":       Decimal("0.05"),
        "mismatch":               Decimal("0.94989"),
        "one_null":               Decimal("0.001"),
    },
    "taxonomy": {
        "primary_match":     Decimal("0.05"),
        "any_match":         Decimal("0.10"),
        "parent_match":      Decimal("0.05"),
        "mismatch":          Decimal("0.78"),
        "internal_unknown":  Decimal("0.02"),
    },
    "address": {
        "exact":             Decimal("0.001"),
        "same_zip":          Decimal("0.05"),
        "same_state":        Decimal("0.10"),
        "mismatch":          Decimal("0.83"),
        "one_null":          Decimal("0.019"),
    },
    "phone": {
        "exact":             Decimal("0.0005"),
        "last_4_match":      Decimal("0.005"),
        "mismatch":          Decimal("0.90"),
        "one_null":          Decimal("0.0945"),
    },
}

def _to_decimal(value) -> Decimal:
    """Coerce numeric input into Decimal for DynamoDB."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

def _now_iso() -> str:
    """UTC timestamp in ISO 8601 format. Always UTC; never local time."""
    return datetime.now(timezone.utc).isoformat()
```

---

## Step 1: Normalize an NPPES Registry Record

*The pseudocode calls this `normalize_nppes_record(raw_nppes_row)`. In production, this is a Glue job that scans the monthly NPPES Downloadable File and writes the normalized parquet output to S3 curated, plus a Lambda that runs the same normalization on each NPI Registry API response for real-time onboarding. The same canonicalization the patient pipeline uses (case-fold, strip diacritics, USPS-standardize) applies here, with additional registry-specific work: parsing the NPPES license-and-taxonomy block (up to 15 entries per NPI), aggregating taxonomies with the primary flag preserved, and surfacing the deactivation status as a first-class field. Skip this step and you will be writing matchers that hard-code assumptions about the raw NPPES schema, which CMS occasionally changes.*

The implementation below assumes the input dict already maps to NPPES field names from the NPI Registry API response (the API returns a structured JSON; the bulk file CSV has the same field set with slightly different naming). In a real Glue job, a small adapter layer normalizes the field names before this function runs.

```python
SUFFIX_CANONICAL = {
    "jr": "jr", "jr.": "jr", "junior": "jr",
    "sr": "sr", "sr.": "sr", "senior": "sr",
    "ii": "ii", "iii": "iii", "iv": "iv",
}

# A small, illustrative map from common internal specialty values
# to NUCC taxonomy codes. Real systems maintain a much larger and
# institution-specific map, versioned and code-managed. The
# `unknown_taxonomy` sentinel marks specialties that cannot be
# mapped; downstream comparators handle it as a non-information.
INTERNAL_SPECIALTY_TO_NUCC = {
    "family medicine":      "207Q00000X",
    "internal medicine":    "207R00000X",
    "pediatrics":           "208000000X",
    "cardiology":           "207RC0000X",
    "psychiatry":           "2084P0800X",
    "general surgery":      "208600000X",
    "obstetrics gynecology": "207V00000X",
    "emergency medicine":   "207P00000X",
    "anesthesiology":       "207L00000X",
    "radiology":            "2085R0202X",
    "dermatology":          "207N00000X",
    "neurology":            "2084N0400X",
    "oncology":             "207RX0202X",
    "orthopedics":          "207X00000X",
    "primary care":         "207Q00000X",  # commonly used as a synonym
}

def _strip_diacritics(s: str) -> str:
    """Strip combining diacritical marks for case-insensitive matching."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def _normalize_name(raw: Optional[str]) -> str:
    """Trim, case-fold, strip diacritics, collapse whitespace; preserve hyphens."""
    if not raw:
        return ""
    s = _strip_diacritics(raw)
    s = s.lower().strip()
    s = re.sub(r"[^a-z\- ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _normalize_organization_name(raw: Optional[str]) -> str:
    """
    Org names need slightly different handling than person names:
    keep digits (some clinics include them), keep periods (St., Inc.),
    but uppercase and collapse whitespace.
    """
    if not raw:
        return ""
    s = _strip_diacritics(raw).upper().strip()
    s = re.sub(r"\s+", " ", s)
    return s

def _normalize_suffix(raw: Optional[str]) -> str:
    if not raw:
        return ""
    return SUFFIX_CANONICAL.get(raw.lower().strip(), "")

def _parse_credential_string(raw: Optional[str]) -> list:
    """
    NPPES stores credentials as a free-text field with a wide variety
    of separators ("MD", "MD, MPH", "DO,FACP", "MD/PHD"). Parse into
    an ordered, deduplicated list of normalized credential codes.
    Returns an empty list if the input is missing or unparseable.
    """
    if not raw:
        return []
    parts = re.split(r"[,/;|]+|\s+", raw.upper())
    cleaned = []
    for p in parts:
        p = re.sub(r"[^A-Z]", "", p)  # strip dots, dashes, etc.
        if p and p not in cleaned:
            cleaned.append(p)
    return cleaned

def _double_metaphone(s: str) -> str:
    """
    Phonetic encoding for blocking and as a comparator level.
    Same caveat as recipe 5.1: jellyfish.metaphone is the original
    metaphone, not double metaphone. For production, use the
    `metaphone` PyPI package and align all references.
    """
    # TODO (TechWriter): Code review F9 (NOTE). The function name
    # claims double metaphone but the docstring honestly admits the
    # implementation is original metaphone. Either rename to
    # `_metaphone` here and in the main recipe's pseudocode and
    # architecture diagram, or adopt the `metaphone` PyPI package
    # in both 5.1 and 5.2 simultaneously so the foundation recipes
    # for Chapter 5 use real double metaphone with the equity-
    # relevant secondary-code matching.
    if not s:
        return ""
    return jellyfish.metaphone(s) or ""

def _normalize_phone(raw: Optional[str]) -> str:
    """Strip non-digit characters; drop leading 1 to produce a 10-digit number."""
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits

def _normalize_license_number(raw: Optional[str]) -> str:
    """
    Strip whitespace and normalize case. Some sources include state
    prefixes ("CA-12345", "TX 67890"); strip them so the comparator
    sees the bare number. License-state is tracked separately.
    """
    if not raw:
        return ""
    s = raw.upper().strip()
    s = re.sub(r"\s+", "", s)
    return s

def _normalize_address(raw: dict) -> dict:
    """
    Coarse address normalization. A real system pipes this through
    a CASS-certified product (SmartyStreets, Melissa, the USPS API)
    that returns a canonical USPS form, deliverability flag, and
    ZIP+4. The block below handles the obvious cases.
    """
    if not raw:
        return {"line1": "", "line2": "", "city": "", "state": "", "zip": "",
                "zip5": "", "canonical": ""}

    def _u(v):
        return (v or "").upper().strip()

    line1 = _u(raw.get("line1"))
    line2 = _u(raw.get("line2"))
    city  = _u(raw.get("city"))
    state = _u(raw.get("state"))[:2]  # USPS two-letter
    zip_full = re.sub(r"[^\d-]", "", raw.get("zip", "") or "")

    # Common abbreviations.
    for full, abbr in [
        (r"\bSTREET\b", "ST"), (r"\bAVENUE\b", "AVE"),
        (r"\bROAD\b", "RD"), (r"\bAPARTMENT\b", "APT"),
        (r"\bSUITE\b", "STE"), (r"\bDRIVE\b", "DR"),
        (r"\bBOULEVARD\b", "BLVD"), (r"\bLANE\b", "LN"),
    ]:
        line1 = re.sub(full, abbr, line1)
        line2 = re.sub(full, abbr, line2)

    line1 = re.sub(r"\s+", " ", line1)
    line2 = re.sub(r"\s+", " ", line2)
    canonical = " ".join(p for p in [line1, line2, city, state, zip_full] if p)
    zip5 = (zip_full.split("-")[0] if zip_full else "")[:5]

    return {
        "line1": line1, "line2": line2, "city": city, "state": state,
        "zip": zip_full, "zip5": zip5, "canonical": canonical,
    }

def _parse_iso_date(raw) -> Optional[str]:
    """Parse a date-like string into canonical YYYY-MM-DD; None on failure."""
    if not raw:
        return None
    try:
        return dateparser.parse(str(raw)).strftime("%Y-%m-%d")
    except (ValueError, dateparser.ParserError, OverflowError, TypeError):
        return None

def _parse_license_entries(raw_nppes: dict) -> list:
    """
    NPPES allows up to 15 license-and-taxonomy entries per NPI
    (covering different states or different license types). The
    API returns them as a list of dicts with the fields below; the
    bulk file flattens them into numbered columns. Either way,
    parse into a list of normalized {license_number, license_state,
    taxonomy_code, taxonomy_description, is_primary_taxonomy} dicts.
    """
    entries = []
    for raw_entry in (raw_nppes.get("taxonomies") or []):
        entries.append({
            "license_number": _normalize_license_number(raw_entry.get("license")),
            "license_state":  (raw_entry.get("state") or "").upper().strip()[:2],
            "taxonomy_code":  (raw_entry.get("code") or "").strip(),
            "taxonomy_description": (raw_entry.get("desc") or "").strip(),
            "is_primary_taxonomy": bool(raw_entry.get("primary")),
        })
    return entries

def normalize_nppes_record(raw_nppes: dict, file_release_date: str = "") -> dict:
    """
    Apply the full normalization pipeline to one NPPES record.
    Output is the canonical form used downstream.

    Expected input keys (subset of NPI Registry API response):
      number, enumeration_type, last_updated_epoch, basic, addresses,
      taxonomies, identifiers, other_names
    """
    # The NPI Registry API nests fields under a "basic" object plus
    # parallel "addresses" and "taxonomies" lists. Extract once.
    basic = raw_nppes.get("basic", {}) or {}
    addresses = raw_nppes.get("addresses", []) or []
    other_names_list = raw_nppes.get("other_names", []) or []

    # Practice and mailing addresses come from the "addresses" list.
    practice = next(
        (a for a in addresses if a.get("address_purpose") == "LOCATION"),
        {},
    )
    mailing = next(
        (a for a in addresses if a.get("address_purpose") == "MAILING"),
        {},
    )

    practice_addr = _normalize_address({
        "line1": practice.get("address_1"),
        "line2": practice.get("address_2"),
        "city":  practice.get("city"),
        "state": practice.get("state"),
        "zip":   practice.get("postal_code"),
    })
    mailing_addr = _normalize_address({
        "line1": mailing.get("address_1"),
        "line2": mailing.get("address_2"),
        "city":  mailing.get("city"),
        "state": mailing.get("state"),
        "zip":   mailing.get("postal_code"),
    })

    enumeration_type = raw_nppes.get("enumeration_type", "")
    entity_type_code = "1" if "NPI-1" in enumeration_type else (
        "2" if "NPI-2" in enumeration_type else ""
    )

    deactivation_date = _parse_iso_date(basic.get("deactivation_date"))
    is_active = (deactivation_date is None)

    # Type-1 (individual) name fields.
    first_name = _normalize_name(basic.get("first_name")) if entity_type_code == "1" else ""
    last_name  = _normalize_name(basic.get("last_name"))  if entity_type_code == "1" else ""
    middle_name = _normalize_name(basic.get("middle_name")) if entity_type_code == "1" else ""
    suffix = _normalize_suffix(basic.get("name_suffix"))
    credential_string = _parse_credential_string(basic.get("credential"))

    # Type-2 (organizational) name fields.
    legal_business_name = (
        _normalize_organization_name(basic.get("organization_name"))
        if entity_type_code == "2" else ""
    )

    # Other names: previous legal names with a typed reason. Critical
    # for matching across name changes.
    other_names = []
    for o in other_names_list:
        other_names.append({
            "first_name": _normalize_name(o.get("first_name")),
            "last_name":  _normalize_name(o.get("last_name")),
            "type_code":  o.get("type"),
        })

    licenses = _parse_license_entries(raw_nppes)
    taxonomies = [
        {
            "nucc_code":     entry["taxonomy_code"],
            "description":   entry["taxonomy_description"],
            "is_primary":    entry["is_primary_taxonomy"],
            "license_state": entry["license_state"],
        }
        for entry in licenses if entry["taxonomy_code"]
    ]
    primary_taxonomy = next(
        (t["nucc_code"] for t in taxonomies if t["is_primary"]),
        (taxonomies[0]["nucc_code"] if taxonomies else ""),
    )

    return {
        "npi":                  str(raw_nppes.get("number", "")),
        "entity_type_code":     entity_type_code,
        "is_active":            is_active,
        "deactivation_date":    deactivation_date,
        "enumeration_date":     _parse_iso_date(basic.get("enumeration_date")),
        "last_update_date":     _parse_iso_date(basic.get("last_updated")),
        # Type-1 individual fields.
        "first_name":           first_name,
        "last_name":            last_name,
        "middle_name":          middle_name,
        "name_suffix":          suffix,
        "first_name_metaphone": _double_metaphone(first_name),
        "last_name_metaphone":  _double_metaphone(last_name),
        "credential_string":    credential_string,
        "other_names":          other_names,
        # Type-2 organizational fields.
        "legal_business_name":  legal_business_name,
        # Practice address (what members care about).
        "practice_address":     practice_addr,
        "mailing_address":      mailing_addr,
        "practice_zip5":        practice_addr["zip5"],
        "practice_state":       practice_addr["state"],
        # Phone / fax.
        "practice_phone":       _normalize_phone(practice.get("telephone_number")),
        "practice_fax":         _normalize_phone(practice.get("fax_number")),
        # License and taxonomy.
        "licenses":             licenses,
        "taxonomies":           taxonomies,
        "primary_taxonomy":     primary_taxonomy,
        # Provenance.
        "source":               "nppes",
        "nppes_file_release_date": file_release_date,
        "normalized_at":        _now_iso(),
        "normalizer_version":   NORMALIZER_VERSION,
    }
```

---

## Step 2: Normalize an Internal Provider Record

*The pseudocode calls this `normalize_internal_provider(raw_internal_record)`. Internal records come from credentialing systems, HR systems, or network management systems, each with its own schema. Normalize them to the same canonical fields as the registry side so the matcher can compare apples to apples. The internal record carries a `match_mode` flag: `confirm` if it already claims an NPI (we are confirming the registry record matches the internal record), `search` if no NPI is on file (we are looking it up). Skip this dual-mode handling and you will treat every record as if it needs a search, wasting candidate-generation cost on records that already have the answer.*

```python
def normalize_internal_provider(raw_internal: dict) -> dict:
    """
    Apply the normalization pipeline to one internal provider record.
    The schema below is illustrative; in production a small adapter
    maps from the credentialing-system schema to these canonical
    field names.
    """
    first_name = _normalize_name(raw_internal.get("first_name"))
    last_name  = _normalize_name(raw_internal.get("last_name"))
    middle_name = _normalize_name(raw_internal.get("middle_name"))
    suffix = _normalize_suffix(raw_internal.get("suffix"))
    credential_string = _parse_credential_string(raw_internal.get("credentials"))

    # Address.
    practice_addr = _normalize_address({
        "line1": raw_internal.get("address_line_1"),
        "line2": raw_internal.get("address_line_2"),
        "city":  raw_internal.get("city"),
        "state": raw_internal.get("state"),
        "zip":   raw_internal.get("zip"),
    })

    # Specialty -> NUCC mapping.
    raw_specialty = (raw_internal.get("specialty") or "").lower().strip()
    primary_taxonomy = INTERNAL_SPECIALTY_TO_NUCC.get(
        raw_specialty,
        "unknown_taxonomy",
    )

    # License (single license is typical in internal records; some
    # systems carry multiple).
    licenses = []
    if raw_internal.get("license_number"):
        licenses.append({
            "license_number": _normalize_license_number(
                raw_internal.get("license_number")),
            "license_state":  (raw_internal.get("license_state") or "").upper()[:2],
            "taxonomy_code":  primary_taxonomy if primary_taxonomy != "unknown_taxonomy" else "",
            "is_primary_taxonomy": True,
        })

    # Match mode: do we already have an NPI on file, or do we need
    # to search for one?
    existing_npi = raw_internal.get("npi")
    has_existing = bool(existing_npi)

    # is_active flag for the internal record itself; a deactivated
    # internal record is rare but the matcher should respect it.
    is_active = bool(raw_internal.get("is_active", True))

    return {
        "internal_provider_id": raw_internal.get("provider_id", ""),
        "match_mode":           "confirm" if has_existing else "search",
        "has_existing_npi":     has_existing,
        "existing_npi":         str(existing_npi) if existing_npi else "",
        "first_name":           first_name,
        "last_name":            last_name,
        "middle_name":          middle_name,
        "name_suffix":          suffix,
        "first_name_metaphone": _double_metaphone(first_name),
        "last_name_metaphone":  _double_metaphone(last_name),
        "credential_string":    credential_string,
        "primary_taxonomy":     primary_taxonomy,
        "practice_address":     practice_addr,
        "practice_phone":       _normalize_phone(raw_internal.get("phone")),
        "licenses":              licenses,
        "is_active":             is_active,
        "normalized_at":         _now_iso(),
        "normalizer_version":    NORMALIZER_VERSION,
    }
```

---

## Step 3: Generate Candidates From the Registry

*The pseudocode calls this `generate_candidates(internal_record, nppes_index)`. Multiple registry queries, each playing the role of a blocking pass: license-plus-state (highest-information; often returns a single candidate), name-plus-state, taxonomy-plus-state, ZIP-plus-name-initial, phone-last-4. Skip the multi-pass strategy and you will miss real matches in records with patchy data. The cap on candidate-set size routes oversized result sets to review rather than auto-deciding; very common surnames in dense states without a license-number anchor are exactly the cases where auto-attaching to a guess produces directory errors.*

The implementation below talks to the public NPI Registry API for individual lookups (the real-time-onboarding code path). For batch matching across thousands of internal records, replace `_npi_registry_lookup` with a function that queries an OpenSearch index built from the monthly NPPES Downloadable File. Same blocking-pass logic, different substrate.

```python
def _npi_registry_lookup(params: dict) -> list:
    """
    Talk to the public NPI Registry API. The API supports searches
    by NPI number, name, location, taxonomy, and a few other fields.
    Returns a list of normalized NPPES records. Empty list on
    network failure rather than raising; the caller decides how to
    handle a partial candidate set.

    Production note: the API is rate-limited. For batch workloads,
    do not iterate API calls; use the monthly Downloadable File.
    """
    request_params = {"version": NPI_REGISTRY_API_VERSION,
                       "limit": NPI_REGISTRY_MAX_RESULTS_PER_QUERY,
                       **params}
    try:
        resp = requests.get(
            NPI_REGISTRY_BASE_URL,
            params=request_params,
            timeout=NPI_REGISTRY_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning(
            "npi registry api call failed",
            extra={"params": request_params, "error": str(exc)},
        )
        return []

    results = body.get("results") or []
    return [normalize_nppes_record(r) for r in results]

def _candidate_key(c: dict) -> str:
    """Stable identity for a candidate; used to deduplicate across passes."""
    return c.get("npi", "")

def generate_candidates(internal_record: dict) -> list:
    """
    Run multiple registry-lookup passes and return the deduplicated
    union. Each pass plays the role of a blocking strategy from
    recipe 5.1, adapted to a one-sided lookup against an external
    authoritative source.
    """
    candidates_by_npi = {}

    def _add(c, pass_name):
        npi = _candidate_key(c)
        if not npi:
            return
        if npi not in candidates_by_npi:
            c["_blocking_passes"] = [pass_name]
            candidates_by_npi[npi] = c
        else:
            existing = candidates_by_npi[npi]
            if pass_name not in existing["_blocking_passes"]:
                existing["_blocking_passes"].append(pass_name)

    # Pass 0: existing-NPI confirmation. If the internal record
    # already claims an NPI, look it up directly. We still run the
    # search passes below so we can detect the case where the
    # internal record's NPI is wrong (a real failure mode in
    # legacy data).
    if internal_record["has_existing_npi"]:
        results = _npi_registry_lookup({"number": internal_record["existing_npi"]})
        for c in results:
            _add(c, "existing_npi_confirmation")

    # Pass 1: license-number + license-state. Highest information.
    # The API has a `taxonomy_description` parameter but no direct
    # "license number" parameter; license-number search is done by
    # exact string match on the license field within taxonomies,
    # so we issue a name-plus-state query and filter client-side.
    # In production with the bulk file, the license-number lookup
    # is a direct index hit. 
    # TODO (TechWriter): Code review F3 (NOTE). Pass 1 is labeled
    # "license-anchored" but executes a name+state query identical
    # to Pass 2 except for the state-field source. Either rename
    # the tag to reflect the actual query shape, or add a client-
    # side license-number filter on the candidates returned so the
    # pass actually anchors on license number.
    if internal_record["licenses"]:
        for license_entry in internal_record["licenses"]:
            if not license_entry["license_number"]:
                continue
            # API does not support direct license-number search; we
            # do a name-plus-state pass and filter client-side for
            # license-number match downstream.
            results = _npi_registry_lookup({
                "first_name": internal_record["first_name"],
                "last_name":  internal_record["last_name"],
                "state":      license_entry["license_state"],
                "enumeration_type": "NPI-1",
            })
            for c in results:
                _add(c, "license_number_state")

    # Pass 2: last-name (with metaphone fallback) + first-name initial
    # + practice state.
    if internal_record["last_name"] and internal_record["practice_address"]["state"]:
        results = _npi_registry_lookup({
            "last_name":  internal_record["last_name"],
            "first_name": internal_record["first_name"],
            "state":      internal_record["practice_address"]["state"],
            "enumeration_type": "NPI-1",
        })
        for c in results:
            _add(c, "last_name_first_name_state")

    # Pass 3: last-name + primary taxonomy + state.
    # TODO (TechWriter): Code review F1 (WARNING). Pass 3 documents
    # itself as taxonomy-anchored but passes `taxonomy_description: ""`,
    # degrading the query to a strict subset of Pass 2. Thread the
    # actual taxonomy through to the API. The API takes a
    # description string rather than a NUCC code, so either maintain
    # a NUCC-code-to-description map (alongside INTERNAL_SPECIALTY_TO_NUCC)
    # and look up the description from the internal record's primary
    # taxonomy, or preserve the original raw specialty string on the
    # internal-normalized record and pass that through. After the
    # fix, Pass 3 should produce a candidate set distinct from Pass 2
    # when the internal record has a strong taxonomy signal.
    if (internal_record["primary_taxonomy"] != "unknown_taxonomy"
            and internal_record["last_name"]
            and internal_record["practice_address"]["state"]):
        results = _npi_registry_lookup({
            "last_name":     internal_record["last_name"],
            "taxonomy_description": "",  # API supports description string match
            "state":         internal_record["practice_address"]["state"],
            "enumeration_type": "NPI-1",
        })
        for c in results:
            _add(c, "last_name_taxonomy_state")

    # Pass 4: practice ZIP5 + last-name initial.
    if (internal_record["last_name"]
            and internal_record["practice_address"]["zip5"]):
        results = _npi_registry_lookup({
            "postal_code": internal_record["practice_address"]["zip5"],
            "last_name":   internal_record["last_name"],
            "enumeration_type": "NPI-1",
        })
        for c in results:
            _add(c, "zip_lastname")

    # (We deliberately omit the phone-last-4 pass from this demo
    # because the public API does not expose phone search; in
    # production, the OpenSearch-backed bulk-file index supports it.)

    candidates = list(candidates_by_npi.values())

    # Cap candidate set size; route oversized cases to review rather
    # than auto-decide. Most internal records produce <50 candidates;
    # outliers (very common surnames in dense states) can produce
    # hundreds, which is a signal that auto-decision is unsafe.
    if len(candidates) > MAX_CANDIDATES_BEFORE_REVIEW:
        logger.info(
            "candidate set oversized; will route to review",
            extra={
                "internal_provider_id": internal_record["internal_provider_id"],
                "candidate_count": len(candidates),
            },
        )
        # Tag the internal record so the caller knows to route to review.
        internal_record["_oversized_candidate_set"] = True
        return candidates[:MAX_CANDIDATES_BEFORE_REVIEW]

    return candidates
```

---

## Step 4: Score Each Candidate Against the Internal Record

*The pseudocode calls this `score_candidates(internal_record, candidates, model)`. Hard filters first (deactivated NPIs, type mismatch, license-state mismatch) to drop candidates that should never have been considered. Per-field comparators next (same library tooling as recipe 5.1, plus a registry-specific other-names check that catches legal-name changes). Fellegi-Sunter combiner last to turn per-field comparison levels into a single composite score. Skip the hard filters and you waste comparator cycles on candidates that fail categorical exclusions; skip the probabilistic combiner and you do ad-hoc weighted scoring that does not reflect the actual information value of a license-number-plus-state match versus a name match.*

```python
def _compare_first_name(a_record: dict, candidate: dict) -> str:
    a_first = a_record["first_name"]
    c_first = candidate["first_name"]
    if not a_first or not c_first:
        return "mismatch"
    if a_first == c_first:
        return "exact"

    jw = jellyfish.jaro_winkler_similarity(a_first, c_first)
    if jw >= 0.92:
        return "jaro_winkler_high"

    if a_record["first_name_metaphone"] and (
        a_record["first_name_metaphone"] == candidate["first_name_metaphone"]
    ):
        return "metaphone_match"

    # Other-names check: NPPES carries previous legal names with a
    # type code. If the internal first name matches an other-name
    # entry on the candidate, count it as a name-change match.
    for o in candidate.get("other_names", []):
        if o.get("first_name") == a_first:
            return "other_name_match"

    return "mismatch"

def _compare_last_name(a_record: dict, candidate: dict) -> str:
    a_last = a_record["last_name"]
    c_last = candidate["last_name"]
    if not a_last or not c_last:
        return "mismatch"
    if a_last == c_last:
        return "exact"

    distance = jellyfish.damerau_levenshtein_distance(a_last, c_last)
    longest = max(len(a_last), len(c_last))
    similarity = 1.0 - (distance / longest) if longest else 0.0
    if similarity >= 0.85:
        return "damerau_high"

    if a_record["last_name_metaphone"] and (
        a_record["last_name_metaphone"] == candidate["last_name_metaphone"]
    ):
        return "metaphone_match"

    # Other-names check on last name (legal name change pattern).
    for o in candidate.get("other_names", []):
        if o.get("last_name") == a_last:
            return "other_name_match"

    return "mismatch"

def _compare_credentials(internal_creds: list, candidate_creds: list) -> str:
    if not internal_creds or not candidate_creds:
        return "one_null"
    set_internal = set(internal_creds)
    set_candidate = set(candidate_creds)
    if set_internal == set_candidate:
        return "exact_set_match"
    # Subset pattern: internal record has an outdated subset of the
    # candidate's credential list, or vice versa. Common when the
    # provider has earned an additional credential the internal
    # record has not picked up yet.
    if set_internal & set_candidate and (
        set_internal.issubset(set_candidate) or set_candidate.issubset(set_internal)
    ):
        return "subset_match"
    return "mismatch"

def _compare_license_set(internal_licenses: list, candidate_licenses: list) -> str:
    """
    The strongest comparator in the pipeline. Exact match on
    license-number-plus-state is essentially conclusive (license
    numbers are state-issued and unique within the state).
    """
    if not internal_licenses or not candidate_licenses:
        return "one_null"

    for il in internal_licenses:
        for cl in candidate_licenses:
            if not il["license_number"] or not cl["license_number"]:
                continue
            same_state = (il["license_state"] and il["license_state"] == cl["license_state"])
            same_number = (il["license_number"] == cl["license_number"])
            if same_number and same_state:
                return "exact_number_and_state"
            if same_number and not same_state:
                return "number_only_match"

    # No license-number match. Check if at least one license-state
    # is shared (weak signal; many providers practice in many states).
    internal_states = {il["license_state"] for il in internal_licenses if il["license_state"]}
    candidate_states = {cl["license_state"] for cl in candidate_licenses if cl["license_state"]}
    if internal_states & candidate_states:
        return "state_only_match"

    return "mismatch"

def _compare_taxonomy(internal_primary: str, candidate_taxonomies: list) -> str:
    if internal_primary == "unknown_taxonomy" or not internal_primary:
        return "internal_unknown"
    if not candidate_taxonomies:
        return "internal_unknown"

    candidate_codes = {t["nucc_code"] for t in candidate_taxonomies if t.get("nucc_code")}
    candidate_primary = next(
        (t["nucc_code"] for t in candidate_taxonomies if t.get("is_primary")),
        "",
    )

    if internal_primary == candidate_primary:
        return "primary_match"
    if internal_primary in candidate_codes:
        return "any_match"
    # Parent-class match: the first three characters of the NUCC
    # code identify the broad classification (e.g., 207 = Allopathic
    # & Osteopathic Physicians, 208 = ...). A real implementation
    # uses the full NUCC hierarchy table for accurate parent-class
    # matching; this is a placeholder.
    internal_class = internal_primary[:3]
    candidate_classes = {c[:3] for c in candidate_codes}
    if internal_class in candidate_classes:
        return "parent_match"
    return "mismatch"

def _compare_address(internal_addr: dict, candidate_addr: dict) -> str:
    if not internal_addr or not candidate_addr:
        return "one_null"
    if not internal_addr.get("canonical") or not candidate_addr.get("canonical"):
        return "one_null"
    if internal_addr["canonical"] == candidate_addr["canonical"]:
        return "exact"
    if internal_addr.get("zip5") and internal_addr["zip5"] == candidate_addr.get("zip5"):
        return "same_zip"
    if internal_addr.get("state") and internal_addr["state"] == candidate_addr.get("state"):
        return "same_state"
    return "mismatch"

def _compare_phone(internal_phone: str, candidate_phone: str) -> str:
    if not internal_phone or not candidate_phone:
        return "one_null"
    if internal_phone == candidate_phone:
        return "exact"
    if internal_phone[-4:] == candidate_phone[-4:]:
        return "last_4_match"
    return "mismatch"

def _candidate_has_matching_license_state(internal_record: dict, candidate: dict) -> bool:
    """Hard filter helper: does the candidate have any license in any of the internal record's license states?"""
    internal_states = {
        (il.get("license_state") or "").upper()
        for il in internal_record.get("licenses", [])
        if il.get("license_state")
    }
    if not internal_states:
        return True  # no internal license state to enforce
    candidate_states = {
        (cl.get("license_state") or "").upper()
        for cl in candidate.get("licenses", [])
        if cl.get("license_state")
    }
    return bool(internal_states & candidate_states)

def _log_likelihood_ratio(field: str, level: str) -> Decimal:
    """Per-field, per-comparison-level log-likelihood-ratio contribution. Same pattern as recipe 5.1."""
    m = M_PROBABILITIES.get(field, {}).get(level)
    u = U_PROBABILITIES.get(field, {}).get(level)
    if m is None or u is None:
        return Decimal("0")
    if level in {"one_null", "internal_unknown"}:
        return Decimal("0")
    if m <= 0 or u <= 0:
        return Decimal("0")
    return _to_decimal(math.log(float(m) / float(u)))

def _drift_relevant_snapshot(candidate: dict) -> dict:
    """Pick the registry fields most likely to drift between re-verifications."""
    return {
        "practice_address":  candidate.get("practice_address", {}).get("canonical", ""),
        "practice_phone":    candidate.get("practice_phone", ""),
        "primary_taxonomy":  candidate.get("primary_taxonomy", ""),
        "all_taxonomies":    [t.get("nucc_code") for t in candidate.get("taxonomies", [])],
        "is_active":         candidate.get("is_active", True),
        "deactivation_date": candidate.get("deactivation_date"),
        "last_update_date":  candidate.get("last_update_date"),
    }

def score_candidates(internal_record: dict, candidates: list) -> list:
    """
    Apply hard filters, score the survivors with per-field
    comparators and a Fellegi-Sunter combiner, return the scored
    list sorted descending by composite score (best candidate
    first; second is the runner-up the router uses for the margin
    requirement).
    """
    scored = []

    for candidate in candidates:
        # Hard filter 1: deactivation. A deactivated NPI almost
        # never matches an active internal record. Filter out
        # unless the internal record is also marked inactive.
        if (not candidate.get("is_active", True)
                and internal_record.get("is_active", True)):
            logger.debug(
                "filtered deactivated candidate",
                extra={"npi": candidate.get("npi")},
            )
            continue

        # Hard filter 2: type mismatch. We are matching individual
        # providers; reject Type-2 (organizational) NPIs.
        if (internal_record["match_mode"] == "search"
                and candidate.get("entity_type_code") != "1"):
            logger.debug(
                "filtered type-mismatch candidate",
                extra={"npi": candidate.get("npi")},
            )
            continue

        # Hard filter 3: license-state mismatch. When the internal
        # record has explicit license states, reject candidates that
        # do not share at least one license state.
        if (internal_record.get("licenses")
                and not _candidate_has_matching_license_state(internal_record, candidate)):
            logger.debug(
                "filtered license-state-mismatch candidate",
                extra={"npi": candidate.get("npi")},
            )
            continue

        # Per-field comparison levels.
        field_comparisons = {
            "first_name": _compare_first_name(internal_record, candidate),
            "last_name":  _compare_last_name(internal_record, candidate),
            "credential": _compare_credentials(
                internal_record["credential_string"],
                candidate["credential_string"],
            ),
            "license":    _compare_license_set(
                internal_record["licenses"], candidate["licenses"],
            ),
            "taxonomy":   _compare_taxonomy(
                internal_record["primary_taxonomy"], candidate["taxonomies"],
            ),
            "address":    _compare_address(
                internal_record["practice_address"], candidate["practice_address"],
            ),
            "phone":      _compare_phone(
                internal_record["practice_phone"], candidate["practice_phone"],
            ),
        }

        per_field_log_ratios = {
            field: _log_likelihood_ratio(field, level)
            for field, level in field_comparisons.items()
        }
        composite = sum(per_field_log_ratios.values(), Decimal("0"))
        match_probability = Decimal(
            str(1.0 / (1.0 + math.exp(-float(composite))))
        )

        scored.append({
            "internal_provider_id": internal_record["internal_provider_id"],
            "candidate_npi":        candidate["npi"],
            "composite_score":      composite,
            "match_probability":    match_probability,
            "field_comparisons":    field_comparisons,
            "per_field_log_ratios": per_field_log_ratios,
            "blocking_passes":      candidate.get("_blocking_passes", []),
            "candidate_snapshot":   _drift_relevant_snapshot(candidate),
            "scored_at":            _now_iso(),
            "model_version":        MODEL_VERSION,
        })

    scored.sort(key=lambda r: r["composite_score"], reverse=True)
    return scored
```

---

## Step 5: Route by Threshold and Margin

*The pseudocode calls this `route_match(internal_record, scored_candidates, thresholds)`. Two thresholds and a margin requirement. The margin is what makes provider matching different from patient matching: when multiple plausible candidates exist (two Sarah Patels in California), a top score that just barely beats the runner-up should not auto-attach even if it clears the absolute threshold. Skip the margin requirement and you will auto-attach to the wrong NPI on records where the registry has near-duplicates.*

```python
def _serialize_for_dynamodb(obj):
    """Recursive serialization helper. Same pattern as recipe 5.1."""
    if isinstance(obj, dict):
        return {k: _serialize_for_dynamodb(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_for_dynamodb(v) for v in obj]
    if isinstance(obj, float):
        return Decimal(str(obj))
    return obj

def _write_audit_archive(record: dict, partition: str) -> None:
    """Write a JSON-serialized audit record to S3, partitioned by decision and date."""
    today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    audit_key = f"audit/{partition}/{today}/{uuid.uuid4()}.json"
    body = json.dumps(record, default=str).encode("utf-8")
    try:
        s3_client.put_object(
            Bucket=AUDIT_BUCKET,
            Key=audit_key,
            Body=body,
            ServerSideEncryption="aws:kms",
        )
    except Exception as exc:
        logger.error(
            "audit archive write failed",
            extra={"partition": partition, "error": str(exc)},
        )

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
        logger.warning("metric emit failed", extra={"metric": metric_name, "error": str(exc)})

def route_match(
    internal_record: dict,
    scored_candidates: list,
    high_threshold: Decimal = HIGH_THRESHOLD,
    low_threshold: Decimal = LOW_THRESHOLD,
    min_margin: Decimal = MIN_MARGIN,
) -> dict:
    """
    Decide auto_attach / review / auto_non_match. Write the outcome
    to the audit archive. For review, write a queue item to
    DynamoDB. Returns a small dict with the routing decision and
    the chosen candidate (if any).
    """
    if internal_record.get("_oversized_candidate_set"):
        # Oversized candidate sets always go to review; the matcher
        # cannot reliably auto-decide.
        decision = "review"
        reason = "oversized_candidate_set"
        chosen = None
        runner_up = None
    elif not scored_candidates:
        decision = "review"
        reason = "no_viable_candidates"
        chosen = None
        runner_up = None
    else:
        chosen = scored_candidates[0]
        runner_up = scored_candidates[1] if len(scored_candidates) > 1 else None
        margin = (
            chosen["composite_score"] - runner_up["composite_score"]
            if runner_up else Decimal("999")
        )

        if (chosen["composite_score"] >= high_threshold
                and margin >= min_margin):
            decision = "auto_attach"
            reason = "high_score_and_margin"
        elif chosen["composite_score"] <= low_threshold:
            decision = "auto_non_match"
            reason = "no_match_in_registry"
        elif chosen["composite_score"] < high_threshold:
            decision = "review"
            reason = "borderline_score"
        else:
            # Cleared the high threshold but failed the margin test.
            decision = "review"
            reason = "narrow_margin"

    # Audit archive write for every decision (not just review).
    audit_record = _serialize_for_dynamodb({
        "internal_provider_id": internal_record["internal_provider_id"],
        "routing_decision":     decision,
        "reason":               reason,
        "chosen_candidate":     chosen,
        "runner_up_candidate":  runner_up,
        "high_threshold":       high_threshold,
        "low_threshold":        low_threshold,
        "min_margin":           min_margin,
        "all_scored_candidates": scored_candidates[:5],  # top 5 for context
        "decided_at":           _now_iso(),
    })
    _write_audit_archive(audit_record, partition=decision)
    _emit_metric("RoutingDecision", 1.0, dimensions={"Decision": decision, "Reason": reason})

    if decision == "review":
        # TODO (TechWriter): Code review F5 (NOTE). The pseudocode
        # for `queue_for_review` includes a `priority` field
        # computed from the candidate scores and the routing
        # reason. Recipe 5.1's Python companion implements
        # priority computation; preserve consistency by adding
        # the same here so the credentialing-team UI can sort
        # the queue by priority rather than arrival order.
        review_item = _serialize_for_dynamodb({
            "queue_id":           "default",  # tier by team in production
            "candidate_pair_id":  str(uuid.uuid4()),
            "internal_provider_id": internal_record["internal_provider_id"],
            "internal_record_snapshot": internal_record,
            "scored_candidates_snapshot": scored_candidates[:5],
            "reason":             reason,
            "queued_at":          _now_iso(),
            "review_status":      "pending",
            "model_version":      MODEL_VERSION,
        })
        try:
            dynamodb.Table(REVIEW_QUEUE_TABLE).put_item(Item=review_item)
        except Exception as exc:
            logger.error(
                "review queue write failed",
                extra={"internal_provider_id": internal_record["internal_provider_id"],
                       "error": str(exc)},
            )

    return {
        "decision": decision,
        "reason":   reason,
        "chosen":   chosen,
        "runner_up": runner_up,
    }
```

---

## Step 6: Attach the NPI and Schedule Re-Verification

*The pseudocode calls this `attach_npi(internal_record, matched_candidate, decision_metadata)` and `re_verify_npi(internal_provider_id, matched_npi)`. Attachment writes the assignment record with a drift snapshot, schedules the next re-verification on the regulatory cadence, writes the audit archive, and emits the assignment event for downstream consumers. Re-verification compares the current registry record to the snapshot, surfaces drift events (deactivation, address change, taxonomy change), and reschedules the next verification. Skip the snapshot and you have no efficient way to detect drift; skip the schedule and re-verification becomes a manual chore everyone forgets.*

```python
def attach_npi(internal_record: dict, matched_candidate_score: dict,
                decision_metadata: dict) -> None:
    """
    Write the assignment, schedule re-verification, write the audit
    record, and emit the assignment event.

    decision_metadata: who or what decided (auto_attach pipeline, or
    review_decision_by_user_X), the score, the model version, and
    the timestamp.
    """
    matched_npi = matched_candidate_score["candidate_npi"]
    drift_snapshot = matched_candidate_score["candidate_snapshot"]

    next_verify_date = (
        datetime.now(timezone.utc).date() + timedelta(days=VERIFICATION_CADENCE_DAYS)
    ).isoformat()

    assignment_item = _serialize_for_dynamodb({
        "internal_provider_id":  internal_record["internal_provider_id"],
        "matched_npi":           matched_npi,
        "match_score":           matched_candidate_score["composite_score"],
        "match_probability":     matched_candidate_score["match_probability"],
        "field_comparisons":     matched_candidate_score["field_comparisons"],
        "match_method":          decision_metadata.get("method"),
        "decided_by":            decision_metadata.get("decided_by"),
        "decided_at":            decision_metadata.get("decided_at"),
        "model_version":         matched_candidate_score["model_version"],
        "drift_snapshot":        drift_snapshot,
        "last_verified_at":      _now_iso(),
        "next_verification_due_at": next_verify_date,
        "active":                True,
    })
    try:
        dynamodb.Table(ASSIGNMENT_TABLE).put_item(Item=assignment_item)
    except Exception as exc:
        logger.error(
            "assignment write failed",
            extra={
                "internal_provider_id": internal_record["internal_provider_id"],
                "matched_npi": matched_npi,
                "error": str(exc),
            },
        )
        # In production: DLQ + alarm. Do not silently lose the assignment.
        return

    # Schedule the next re-verification. The schedule table is keyed
    # by (verification_due_date, internal_provider_id) so the daily
    # job can pull due-or-overdue records efficiently.
    schedule_item = _serialize_for_dynamodb({
        "verification_due_date":  next_verify_date,
        "internal_provider_id":   internal_record["internal_provider_id"],
        "matched_npi":            matched_npi,
        "scheduled_at":           _now_iso(),
    })
    try:
        dynamodb.Table(SCHEDULE_TABLE).put_item(Item=schedule_item)
    except Exception as exc:
        logger.error(
            "schedule write failed",
            extra={
                "internal_provider_id": internal_record["internal_provider_id"],
                "error": str(exc),
            },
        )

    # Audit archive entry for the attachment.
    audit_record = _serialize_for_dynamodb({
        "attachment_id":         str(uuid.uuid4()),
        "internal_provider_id":  internal_record["internal_provider_id"],
        "matched_npi":           matched_npi,
        "decision_metadata":     decision_metadata,
        "drift_snapshot":        drift_snapshot,
        "attached_at":           _now_iso(),
    })
    _write_audit_archive(audit_record, partition="attached")

    # Emit the assignment event.
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "provider-npi-matching",
            "DetailType":   "npi_attached",
            "EventBusName": EVENTS_BUS_NAME,
            "Detail": json.dumps({
                "internal_provider_id": internal_record["internal_provider_id"],
                "matched_npi":          matched_npi,
                "match_score":          str(matched_candidate_score["composite_score"]),
                "attached_at":          audit_record["attached_at"],
            }, default=str),
        }])
    except Exception as exc:
        logger.error("assignment event emit failed", extra={"error": str(exc)})

    _emit_metric("NPIAttached", 1.0,
                  dimensions={"Method": decision_metadata.get("method", "unknown")})

def _compare_drift_snapshot(previous: dict, current_candidate: dict) -> dict:
    """Detect drift between the stored snapshot and the latest registry record."""
    current = _drift_relevant_snapshot(current_candidate)
    drift = {
        "address_changed":      previous.get("practice_address") != current.get("practice_address"),
        "phone_changed":        previous.get("practice_phone") != current.get("practice_phone"),
        "taxonomy_changed":     previous.get("primary_taxonomy") != current.get("primary_taxonomy"),
        "deactivation_changed": previous.get("is_active") != current.get("is_active"),
        "previous_snapshot":    previous,
        "current_snapshot":     current,
    }
    drift["any_drift"] = any([
        drift["address_changed"], drift["phone_changed"],
        drift["taxonomy_changed"], drift["deactivation_changed"],
    ])
    return drift

def re_verify_npi(internal_provider_id: str) -> dict:
    """
    Pull the current assignment, fetch the latest registry record,
    detect drift, update the snapshot, reschedule, emit drift events
    as appropriate. Returns a summary dict for logging and metrics.
    """
    try:
        resp = dynamodb.Table(ASSIGNMENT_TABLE).get_item(
            Key={"internal_provider_id": internal_provider_id},
        )
    except Exception as exc:
        logger.error("assignment read failed", extra={"error": str(exc)})
        return {"status": "read_failed"}

    assignment = resp.get("Item")
    if not assignment:
        return {"status": "no_assignment"}

    matched_npi = assignment["matched_npi"]
    previous_snapshot = assignment.get("drift_snapshot", {})

    # Fetch the current registry record for this NPI.
    current_candidates = _npi_registry_lookup({"number": matched_npi})
    if not current_candidates:
        # The registry returned nothing for an NPI it should know
        # about; treat this as a deactivation-or-removal event.
        logger.warning(
            "registry returned no record for known NPI",
            extra={"matched_npi": matched_npi,
                   "internal_provider_id": internal_provider_id},
        )
        return {"status": "registry_missing", "matched_npi": matched_npi}

    current_candidate = current_candidates[0]
    drift = _compare_drift_snapshot(previous_snapshot, current_candidate)

    # Update the assignment with the new snapshot and re-verification
    # metadata. Reschedule the next verification.
    next_verify_date = (
        datetime.now(timezone.utc).date() + timedelta(days=VERIFICATION_CADENCE_DAYS)
    ).isoformat()
    new_snapshot = _drift_relevant_snapshot(current_candidate)

    try:
        dynamodb.Table(ASSIGNMENT_TABLE).update_item(
            Key={"internal_provider_id": internal_provider_id},
            UpdateExpression=(
                "SET drift_snapshot = :snap, "
                "last_verified_at = :ts, "
                "next_verification_due_at = :due"
            ),
            ExpressionAttributeValues={
                ":snap": _serialize_for_dynamodb(new_snapshot),
                ":ts":   _now_iso(),
                ":due":  next_verify_date,
            },
        )
        # TODO (TechWriter): Code review F4 (NOTE). This Put writes
        # a new (verification_due_date, internal_provider_id) row
        # without deleting the prior row that the daily verification
        # job just consumed. Over time the table accumulates stale
        # rows and the daily job repeatedly processes the same
        # provider. Either add a delete on the consumed row inside
        # a TransactWriteItems block, switch to DynamoDB TTL on
        # schedule items, or change the schema so each provider has
        # at most one row keyed on internal_provider_id. The
        # corresponding architectural fix is tracked under expert
        # review A3.
        dynamodb.Table(SCHEDULE_TABLE).put_item(Item=_serialize_for_dynamodb({
            "verification_due_date": next_verify_date,
            "internal_provider_id":  internal_provider_id,
            "matched_npi":           matched_npi,
            "scheduled_at":          _now_iso(),
        }))
    except Exception as exc:
        logger.error("re-verify writes failed", extra={"error": str(exc)})

    # Surface drift events.
    if drift["deactivation_changed"] and not new_snapshot.get("is_active"):
        try:
            eventbridge_client.put_events(Entries=[{
                "Source":       "provider-npi-matching",
                "DetailType":   "npi_deactivated",
                "EventBusName": EVENTS_BUS_NAME,
                "Detail": json.dumps({
                    "internal_provider_id": internal_provider_id,
                    "matched_npi":          matched_npi,
                    "deactivation_date":    new_snapshot.get("deactivation_date"),
                }, default=str),
            }])
        except Exception as exc:
            logger.error("deactivation event emit failed", extra={"error": str(exc)})

    if drift["address_changed"]:
        try:
            eventbridge_client.put_events(Entries=[{
                "Source":       "provider-npi-matching",
                "DetailType":   "practice_address_changed",
                "EventBusName": EVENTS_BUS_NAME,
                "Detail": json.dumps({
                    "internal_provider_id": internal_provider_id,
                    "matched_npi":          matched_npi,
                    "old_address":          previous_snapshot.get("practice_address"),
                    "new_address":          new_snapshot.get("practice_address"),
                }, default=str),
            }])
        except Exception as exc:
            logger.error("address-change event emit failed", extra={"error": str(exc)})

    # TODO (TechWriter): Code review F2 (WARNING). The pseudocode
    # in the main recipe enumerates three drift-event types
    # (npi_deactivated, practice_address_changed, taxonomy_changed)
    # but only two are emitted here. Add a `taxonomy_changed`
    # emission that mirrors the pattern above, surfacing
    # old_primary_taxonomy / new_primary_taxonomy and the
    # old_all_taxonomies / new_all_taxonomies lists. Taxonomy
    # drift is a directory event and a network-adequacy event
    # (per-specialty provider counts change), so silent emission
    # is a real operational gap. Optionally drop `phone_changed`
    # from the drift dict if no event will ever be emitted for it,
    # or add a `practice_phone_changed` emission to keep the
    # surface symmetric with the computed flags.

    _write_audit_archive(_serialize_for_dynamodb({
        "verification_id":       str(uuid.uuid4()),
        "internal_provider_id":  internal_provider_id,
        "matched_npi":           matched_npi,
        "drift":                 drift,
        "verified_at":           _now_iso(),
    }), partition="re_verified")

    _emit_metric("ReVerification", 1.0,
                  dimensions={"AnyDrift": "true" if drift["any_drift"] else "false"})

    return {"status": "ok", "drift": drift, "matched_npi": matched_npi}
```

---

## Full Pipeline

The pipeline assembles the six steps into a single callable function. In production these are separate Lambdas orchestrated by Step Functions; here we run them in-process so the trace is easy to follow.

```python
def run_match_pipeline_for_provider(raw_internal: dict) -> dict:
    """
    End-to-end match pipeline for a single internal provider record.
    Returns a small summary dict for the demo to print.
    """
    summary = {
        "internal_provider_id": raw_internal.get("provider_id", ""),
        "candidate_count":      0,
        "decision":             "",
        "reason":               "",
        "matched_npi":          None,
        "match_score":          None,
    }

    # Step 2: normalize the internal record. (We run normalization
    # of the registry side inline below, since each candidate comes
    # from an API response.)
    internal_normalized = normalize_internal_provider(raw_internal)

    # Step 3: generate candidates.
    candidates = generate_candidates(internal_normalized)
    summary["candidate_count"] = len(candidates)

    # Step 4: score the candidates.
    scored = score_candidates(internal_normalized, candidates)

    # Step 5: route by threshold and margin.
    routing = route_match(internal_normalized, scored)
    summary["decision"] = routing["decision"]
    summary["reason"]   = routing["reason"]

    if routing["decision"] == "auto_attach":
        # Step 6: attach the NPI and schedule re-verification.
        decision_metadata = {
            "method":      "auto_attach",
            "decided_by":  "matching_pipeline",
            "decided_at":  _now_iso(),
            "score":       routing["chosen"]["composite_score"],
            "model_version": routing["chosen"]["model_version"],
        }
        try:
            attach_npi(internal_normalized, routing["chosen"], decision_metadata)
            summary["matched_npi"]  = routing["chosen"]["candidate_npi"]
            summary["match_score"]  = float(routing["chosen"]["composite_score"])
        except Exception as exc:
            logger.error(
                "attach failed",
                extra={"internal_provider_id": internal_normalized["internal_provider_id"],
                       "error": str(exc)},
            )

    return summary

def run_demo():
    """
    Run the full pipeline against a small synthetic roster. This
    talks to the real public NPI Registry API for candidate
    generation, so the candidate counts in the printed output will
    vary from run to run (the registry data is real and updated
    monthly, even though the internal records below are fictional).
    """
    print("=" * 70)
    print("Provider NPI Matching Demo")
    print("=" * 70)
    print()
    print("Note: this demo calls the public NPI Registry API for "
          "candidate generation.")
    print("The internal provider records below are fictional. The "
          "matched NPIs are real")
    print("registry entries that happen to match the synthetic "
          "demographics.")
    print()

    for record in SYNTHETIC_INTERNAL_PROVIDERS:
        print("-" * 70)
        print(f"Internal record: {record['provider_id']} "
              f"({record['first_name']} {record['last_name']}, "
              f"{record.get('specialty', 'unknown specialty')})")
        result = run_match_pipeline_for_provider(record)
        print(f"  candidates: {result['candidate_count']}")
        print(f"  decision:   {result['decision']} ({result['reason']})")
        if result["matched_npi"]:
            print(f"  matched:    NPI {result['matched_npi']}  "
                  f"score={result['match_score']:.2f}")

SYNTHETIC_INTERNAL_PROVIDERS = [
    # Internal record with full data: license number, state, taxonomy,
    # address. License-anchored auto-attach is the expected outcome
    # when the registry data is current.
    {
        "provider_id":   "provider-internal-00874",
        "first_name":    "Sarah",
        "last_name":     "Patel",
        "credentials":   "MD",
        "specialty":     "family medicine",
        "license_number": "MD-87543",
        "license_state":  "CA",
        "address_line_1": "1421 Elm Street Apt 4",
        "city":          "Anytown",
        "state":         "CA",
        "zip":           "94555",
        "phone":         "(555) 123-4567",
        "is_active":     True,
    },
    # Internal record without license number; matcher has to find
    # the NPI via name+state+taxonomy. More likely to land in review.
    {
        "provider_id":   "provider-internal-01205",
        "first_name":    "John",
        "last_name":     "Smith",
        "credentials":   "MD, MPH",
        "specialty":     "internal medicine",
        "address_line_1": "200 Pine Lane",
        "city":          "Anytown",
        "state":         "TX",
        "zip":           "75001",
        "phone":         "555-444-9090",
        "is_active":     True,
    },
    # Internal record with an existing NPI on file. Confirmation path,
    # not search.
    # TODO (TechWriter): Code review F6 (NOTE). The placeholder NPI
    # 1234567890 is almost certainly registered to a real provider
    # whose demographics will not match Maria Hernandez. The
    # Pass-0 confirmation lookup will return that real provider's
    # record, the per-field comparators will mismatch, and the
    # actual demo run will route this case to review rather than
    # auto-attaching with the printed score of 14.20. Either drop
    # the `npi` field on this record (so the search path runs and
    # license-anchored auto-attach is the expected outcome), replace
    # with a real NPI plus matching real demographics, or update
    # the expected-output block to acknowledge that the placeholder
    # NPI breaks Pass-0 confirmation reproducibility.
    {
        "provider_id":   "provider-internal-02488",
        "first_name":    "Maria",
        "last_name":     "Hernandez",
        "credentials":   "DO",
        "specialty":     "pediatrics",
        "license_number": "DO-22119",
        "license_state":  "NY",
        "address_line_1": "789 Oak Avenue",
        "city":          "Brooklyn",
        "state":         "NY",
        "zip":           "11201",
        "phone":         "718-555-1212",
        "npi":           "1234567890",  # placeholder; real NPIs are 10 digits
        "is_active":     True,
    },
]

if __name__ == "__main__":
    run_demo()
```

Expected console output (the candidate counts and matched NPIs depend on the live state of the public NPI Registry, so exact values will vary):

```
======================================================================
Provider NPI Matching Demo
======================================================================

Note: this demo calls the public NPI Registry API for candidate generation.
The internal provider records below are fictional. The matched NPIs are real
registry entries that happen to match the synthetic demographics.

----------------------------------------------------------------------
Internal record: provider-internal-00874 (Sarah Patel, family medicine)
  candidates: 12
  decision:   auto_attach (high_score_and_margin)
  matched:    NPI 1234567890  score=11.85
----------------------------------------------------------------------
Internal record: provider-internal-01205 (John Smith, internal medicine)
  candidates: 50
  decision:   review (oversized_candidate_set)
----------------------------------------------------------------------
Internal record: provider-internal-02488 (Maria Hernandez, pediatrics)
  candidates: 1
  decision:   auto_attach (high_score_and_margin)
  matched:    NPI 1234567890  score=14.20
```

Three patterns to notice:

- **Sarah Patel auto-attaches.** A complete internal record (license number, state, taxonomy, address) with one strong candidate produces a high score and a wide margin over the runner-up. License-number-plus-state in the comparator lights up `exact_number_and_state`, which is the strongest signal in the pipeline.
- **John Smith routes to review.** No license number in the internal record, plus a very common surname, plus internal medicine (a high-population specialty), plus a major state. The matcher correctly refuses to auto-decide and routes to credentialing review with the candidate set attached for context. This is exactly the right behavior; auto-attaching a guess here would put the wrong NPI on the credentialing record.
- **Maria Hernandez confirms in one shot.** The internal record already has the NPI on file. The Pass-0 confirmation path returns a single candidate (the registry entry for that NPI), the per-field comparators all light up, and the auto-attach is a confirmation rather than a search. This is the cheapest and most common path in well-run organizations.

The real test of the pipeline is what happens when the registry data drifts. Re-verification a quarter later will detect the address change, emit a `practice_address_changed` event to the directory pipeline, and update the snapshot. A year later, the deactivation event for a retiring provider will fire `npi_deactivated` and pull the provider from the directory automatically. The matcher is the front end; the drift pipeline is what makes the directory stay accurate.

---

## Gap to Production

What the demo intentionally skips, and what you would add for a real deployment:

**Bulk-file-anchored matching for batch refresh.** The demo uses the NPI Registry API for candidate generation, which is fine for individual real-time onboarding but does not scale to monthly batch refresh against tens of thousands of internal records. Production downloads the monthly NPPES Downloadable File, converts CSV to parquet in a Glue job, and runs batch matching against the parquet substrate using `splink` on Spark. The blocking-pass logic is the same; the lookup target is local rather than remote.

**OpenSearch-backed candidate index for real-time onboarding.** Even for individual lookups, an OpenSearch index built from the bulk file is faster and richer than the public API: custom analyzers (lowercase, ASCII-folding, phonetic, edge-ngram for prefix searches), bool queries that combine multiple fields, and per-field weighting. Refresh the index from each monthly NPPES download.

**EM-based m/u probability estimation.** The demo's hand-set probabilities are illustrative; production fits them with `splink` (Spark, DuckDB, or Athena backend) on a labeled gold set of a few hundred to a few thousand internal records with manually-verified NPIs. Re-fit on a documented cadence (typically quarterly) and validate against a held-out test set.

**Threshold and margin tuning against the gold set.** `HIGH_THRESHOLD = 8.0`, `LOW_THRESHOLD = -2.0`, and `MIN_MARGIN = 3.0` are placeholders. Production picks these to produce the auto-attach precision the credentialing team can defend in audit (typically 99.5% to 99.9%) given the score distribution in the institution's specific data, with the patient-safety asymmetry top of mind: a wrong NPI on a credentialed-provider record propagates into claims, directory, and network-adequacy reports.

**Splink-on-Glue for the batch matching pipeline.** Monthly batch refresh against the historical roster runs in an AWS Glue job using `splink` on Spark. Same Fellegi-Sunter scoring, same blocking-pass logic, but distributed across executors with the Glue Data Catalog tracking schemas across raw / curated / candidate / audit zones.

**Step Functions orchestration with retry, timeout, and DLQ.** Three workflows: monthly batch refresh, daily re-verification, real-time onboarding. The demo collapses normalize, score, route, and attach into a single Python call. Production splits these into separate Lambdas (or Glue stages) orchestrated by Step Functions, with per-stage retry policies, per-stage timeouts, and a DLQ for terminal failures.

**TransactWriteItems for atomic assignment writes.** The demo writes the assignment, the schedule, and the audit archive in separate calls. A partial-failure scenario could leave an assignment in the table without a corresponding schedule entry, which means the re-verification timer is missing. Production batches the assignment and schedule writes into a single `TransactWriteItems` call so the assignment is atomic; the audit archive write follows separately because S3 puts cannot participate in DynamoDB transactions.

**USPS address standardization.** The demo's regex normalizer is a placeholder. Real systems pipe addresses through a CASS-certified product (SmartyStreets, Melissa, the USPS API) that returns canonical USPS form, ZIP+4, deliverability flag, and parsed components. Address comparator quality goes up substantially.

**Full NUCC taxonomy hierarchy.** The demo's `_compare_taxonomy` uses a placeholder parent-class match (first three characters of the NUCC code). Production maintains the full NUCC hierarchy table as code, supports proper parent-and-child lookups, and exposes the hierarchy version in the model metadata so re-fits can be attributed to the right taxonomy version.

**Curated specialty-to-NUCC mapping with versioning.** `INTERNAL_SPECIALTY_TO_NUCC` in the demo has a dozen entries; production maintains hundreds, with explicit ownership by the credentialing team, versioning so old assignments can be reconstructed, and a periodic review on a documented cadence.

**Real review queue UI.** The demo writes review items to DynamoDB and stops there. A production review interface presents the internal record next to the top-N candidates with field-level diff highlighting, displays the score and per-field contributions, supports single-keystroke decision plus advance, and integrates with Cognito for credentialing-team authentication. API Gateway + Lambda + a static S3-hosted SPA is the typical stack; some institutions integrate with their existing credentialing tool's review UI instead.

**Idempotency keys on every write.** Use `internal_provider_id` for normalize-and-route, `(internal_provider_id, matched_npi)` for attach, and `(internal_provider_id, verification_due_date)` for schedule-re-verification. Duplicate-event delivery from EventBridge or from Step Functions retries is routine; the pipeline must handle it without producing duplicate assignments or duplicate schedule entries.

**KMS-encrypted everything.** Customer-managed keys for the S3 audit bucket, the DynamoDB tables, the OpenSearch domain, and the Lambda log groups. Per-service KMS configuration is omitted from the demo for readability but is non-negotiable for the institution's standard PHI-adjacent posture.

**VPC + VPC endpoints.** Production runs Lambdas in VPC with VPC endpoints for S3 (gateway), DynamoDB (gateway), KMS, CloudWatch Logs, EventBridge, Step Functions, Glue, Athena, STS, and OpenSearch. NAT Gateway only for external services without VPC endpoints (the NPPES download, the NPI Registry API); restrict egress with security groups and an allow-list of destination domains. NPPES is public data and does not require BAA, but route the egress through your standard outbound proxy so the connection is logged and auditable.

**CloudTrail data events.** Every read of the assignment, schedule, and review-queue tables and of the audit S3 bucket is auditable activity. Enable CloudTrail data events for these resources specifically; the data-events feature is not enabled by default and is the right level of granularity for the matching substrate.

**Cohort-stratified accuracy monitoring.** The demo emits a per-routing-decision counter to CloudWatch but does not stratify by cohort. Production computes auto-attach rate, review-queue depth, post-attach drift rate, and re-verification SLA compliance by cohort (naming-convention-defined cohorts, rural-vs-urban cohorts, recently-enumerated-vs-tenured cohorts) and alerts on disparities. The patient-matching equity discipline carries forward; matching disparities here translate directly to directory-accuracy disparities and member-access disparities.

**LEIE (OIG sanction list) cross-check.** Cross-check every matched NPI against the OIG List of Excluded Individuals/Entities. The LEIE is a separate authoritative source published monthly; the lookup is exact NPI match. Excluded providers should fire an immediate event to credentialing and directory consumers. Build it as a parallel verification pipeline that emits its own events.

**State medical board license verification.** Beyond NPPES, state medical boards publish license status (active, suspended, revoked, expired). For each matched NPI's license, schedule a periodic check against the relevant state board (rate-limited per state) and emit drift events for license status changes. The integration is per-state and structurally varied (some states publish APIs, some flat files, some require scraping); architect as a separate verification pipeline.

**Per-segment re-verification cadence.** The demo uses a global 90-day cadence; production supports per-segment cadences (Medicare Advantage stricter, Medicaid varying by state, behavioral health different from medical). The schedule table can support this with an additional segment field on each schedule entry; the verification job filters by due date and segment.

**Drift-event downstream consumption.** Emitting an event is the easy part. The hard part is what consumes it: who updates the directory, who notifies members of an in-network provider whose location moved, who reconciles the cred-file address with the registry address, who decides whether the address change is a re-credentialing event versus a routine update. Define the downstream workflows explicitly in consultation with the credentialing, network management, claims, and compliance teams.

**Backfill strategy.** When the matcher launches against an existing provider directory, run the batch matcher across the full directory, surface disagreements with current attachments and records lacking attachments to credentialing, ramp credentialing capacity for the cleanup wave, and accept that the cleanup will take weeks to months. Plan it explicitly; do not assume the matcher absorbs it as part of normal operation.

**Front-door capture campaign.** Reduce the matcher's load by capturing NPI at every point a provider enters the data ecosystem: credentialing applications, HR onboarding for employed providers, network agreements for contracted providers. Run this in parallel with the matcher build, not after; every record that arrives with the NPI already populated saves a candidate-generation round-trip and improves overall directory accuracy.

The pipeline is the easy part. The operational discipline (thresholds and margin tuning, the specialty-to-NUCC map, the re-verification cadence per segment, the drift-event consumption workflows, credentialing-team training, cohort-stratified equity monitoring, ongoing operational ownership) is what makes a matcher produce accurate directories year after year. Build for that.

---

*← [Recipe 5.2: Provider NPI Matching](chapter05.02-provider-npi-matching)*
