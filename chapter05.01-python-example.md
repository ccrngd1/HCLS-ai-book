# Recipe 5.1: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 5.1. It shows one way you could translate the internal-duplicate-patient-detection pattern into working Python using `jellyfish` for string-similarity functions (Jaro-Winkler, Damerau-Levenshtein), `metaphone` for double-metaphone phonetic encoding, `python-dateutil` for permissive date parsing, Amazon DynamoDB for the master patient identity tables and the review queue, Amazon S3 for the audit archive, Amazon EventBridge for downstream merge events, and Amazon CloudWatch for operational metrics. It is not production-ready. There is no real EHR or registration-system feed (the demo seeds a small in-memory roster with intentional duplicates), no Splink or Spark-based batch pipeline (the demo runs a tiny in-process blocker plus scorer that would not scale past tens of thousands of records), no OpenSearch-backed real-time candidate index, no USPS address standardization (the demo uses a coarse regex normalizer), no EM-based m/u estimation (the demo uses hand-set probabilities to keep the math visible), no review-queue UI, and no IAM, KMS, VPC, or CloudTrail wiring. Think of it as the sketchpad version: useful for understanding the shape of an entity-resolution pipeline that respects the structured-then-narrative flow, the three-bucket routing pattern, the survivorship and reversibility requirements, and the audit-everything posture. It is not something you would point at a live patient registration system on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the five core pseudocode steps from the main recipe: normalize each patient record (case-fold, strip diacritics, parse dates, USPS-style address cleanup, phonetic encoding); generate candidate pairs through multiple blocking passes that union into a deduplicated candidate set; score each candidate pair with per-field comparators and a hand-rolled Fellegi-Sunter combiner; route each scored pair into auto-match, auto-non-match, or human review based on configurable thresholds; and apply the merge with field-level survivorship rules and a complete audit record that supports unmerge. All sample patients in the demo are synthetic, including the three "Maria Garcia" variants from the recipe's opening narrative; do not treat any specific patient_id, mpi_id, or merge_id in the sample output as real.

---

## Setup

You will need the AWS SDK for Python plus a couple of string-similarity libraries:

```bash
pip install boto3 jellyfish python-dateutil metaphone
```

`jellyfish` provides the Jaro-Winkler and Damerau-Levenshtein implementations used in the comparators. `metaphone` provides the double-metaphone algorithm (the modern 2000 successor to the original 1990 metaphone) that produces primary and secondary phonetic codes for names. `python-dateutil` provides a permissive date parser that handles the dozen formats registration desks generate (`MM/DD/YYYY`, `DD-MM-YYYY`, `March 14 1972`, `19720314`, and the rest).

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchWriteItem` on the `mpi-master`, `mpi-xref`, and `review-queue` tables (and on the `mpi-id-index` GSI on `mpi-xref` that supports cluster-member lookups)
- `s3:PutObject` on the audit-archive bucket
- `events:PutEvents` on the merge-events bus
- `cloudwatch:PutMetricData` for the queue-depth, auto-match-rate, and cohort-disparity metrics

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. In production, the normalize, candidate-generate, score, route, and merge-application stages each get their own role with the minimum permissions for its job.

A few things worth knowing upfront:

- **The MPI tables are clinical-record-equivalent PHI.** `mpi-master` holds a person's resolved identity, `mpi-xref` holds the cross-references from every source record to that identity, and `review-queue` holds the borderline pairs with full snapshots of both source records. These are the most sensitive data structures in the pipeline. Encrypt with a customer-managed KMS key, gate every read with CloudTrail data events, and apply tighter-than-default access control. Never log raw record values from these tables in application logs.
- **DynamoDB rejects Python `float`.** Every probability, similarity score, and likelihood ratio passes through `Decimal` on its way in and on its way out. Floats in money or in probabilistic match scores are precision-loss bugs waiting to happen; `Decimal` is the safe and the correct choice for both.
- **Hand-set m/u probabilities, not EM-estimated.** The probabilistic scorer below uses fixed `m` and `u` values per (field, comparison_level) pair. They are reasonable starting values illustrative of what an EM-trained model produces, but they are not tuned to your data. In production, fit them with `splink` or the `recordlinkage` library on a labeled gold set and re-fit on a documented cadence (typically quarterly). See the Gap to Production section.
- **No EHR integration.** The demo seeds an in-memory list of synthetic patient records, runs the full pipeline on it, and prints the results. A production deployment ingests from FHIR, HL7 v2 ADT messages, or registration-system events, runs in real time at registration, and runs nightly batch jobs against the historical roster.
- **No address standardization service.** The demo uses a coarse regex-based address normalizer. Real systems wire in a CASS-certified product (SmartyStreets, Melissa, the USPS API) for the address pipeline; the comparator quality difference is enormous.
- **The example collapses Step Functions, Lambda, and EventBridge into a single Python file for readability.** In production the normalize, score, route, and merge-application stages are separate Lambda functions, orchestrated by Step Functions, with their own error handling, retries, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Field weights, m/u probabilities, blocking-pass definitions, and routing thresholds are the knobs you would change between environments.

```python
import hashlib
import json
import logging
import math
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

import boto3
import jellyfish
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from dateutil import parser as dateparser
from metaphone import doublemetaphone

# Structured logging. In production, ship JSON-formatted records to
# CloudWatch Logs Insights. Patient demographic data is PHI; never log
# raw field values in application logs. Log structural metadata only:
# record IDs, scores, routing decisions, and counts.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from DynamoDB, EventBridge, and
# CloudWatch. Real-time matching at registration time has a tight
# latency budget; transient throttling from any one service should
# not fail the whole identity assignment. Step Functions Catch
# distinguishes retryable infrastructure failures from terminal
# logic failures and routes terminal failures to a DLQ for human
# investigation.
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
MPI_MASTER_TABLE       = "mpi-master"
MPI_XREF_TABLE         = "mpi-xref"
REVIEW_QUEUE_TABLE     = "review-queue"
MPI_ID_INDEX           = "mpi-id-index"   # GSI on mpi-xref by mpi_id
AUDIT_BUCKET           = "my-mpi-audit"
MERGE_EVENTS_BUS_NAME  = "mpi-merge-events"
CLOUDWATCH_NAMESPACE   = "MPI/Deduplication"

# Deploy-time guardrail: catch unreplaced example values. Remove
# this assertion (or replace the placeholder) before deploying.
assert AUDIT_BUCKET != "", "AUDIT_BUCKET must be set before deploying."

# --- Versioning ---
# Every routing decision and every merge audit record stores the
# version of the normalizer and the model that produced it. This
# is how the surveillance pipeline attributes drift to a specific
# normalizer or model release and how the unmerge logic knows
# which survivorship rules to use when reversing an old merge.
NORMALIZER_VERSION = "norm-v1.0"
MODEL_VERSION      = "fs-v1.0"
SURVIVORSHIP_RULES_VERSION = "surv-v1.0"

# --- Routing Thresholds ---
# Score is a Fellegi-Sunter log-likelihood ratio (sum of per-field
# log(m/u) and log((1-m)/(1-u)) terms). Higher is more confident
# match. The thresholds here are illustrative; in production they
# are clinical-leadership-approved configuration tuned against a
# labeled gold set, with the patient-safety asymmetry top of mind:
# false merges are a safety hazard, false splits are a cost-and-
# quality issue, so favor false splits over false merges.
HIGH_THRESHOLD = Decimal("20.0")   # at or above: auto-match
LOW_THRESHOLD  = Decimal("-2.0")   # at or below: auto-non-match
# Anything between the two thresholds routes to human review.

# --- Blocking ---
# Skip blocks above this size; they explode the comparison count
# without contributing useful candidates. Common-name blocks
# (Smith, Garcia, Lee with common DOB patterns) regularly land
# above this threshold and are deliberately skipped; the other
# blocking passes catch the duplicates that matter.
MAX_BLOCK_SIZE = 200

# --- Nickname Dictionary ---
# A tiny, illustrative nickname-to-legal-name table. A real system
# uses a much larger curated dictionary (the public-domain "names"
# corpus or a vendor-supplied dictionary) covering the common
# English-language nicknames plus institution-specific additions
# captured over time from the review queue.
NICKNAME_TO_LEGAL = {
    "bob":      ["robert", "rob", "bobby"],
    "rob":      ["robert", "bob", "bobby"],
    "robert":   ["bob", "rob", "bobby"],
    "bill":     ["william", "billy", "willie"],
    "william":  ["bill", "billy", "willie"],
    "liz":      ["elizabeth", "beth", "betty", "eliza"],
    "beth":     ["elizabeth", "liz", "betty", "eliza"],
    "elizabeth": ["liz", "beth", "betty", "eliza"],
    "jen":      ["jennifer", "jenny"],
    "jenny":    ["jennifer", "jen"],
    "jennifer": ["jen", "jenny"],
    "mike":     ["michael", "mick", "mickey"],
    "michael":  ["mike", "mick", "mickey"],
    # In production, populate from a maintained nickname dictionary.
    # See the Gap to Production section for sources.
}

# --- Suffix Canonical Forms ---
SUFFIX_CANONICAL = {
    "jr": "jr", "jr.": "jr", "junior": "jr",
    "sr": "sr", "sr.": "sr", "senior": "sr",
    "ii": "ii", "iii": "iii", "iv": "iv",
}

# --- Fellegi-Sunter Probabilities ---
#
# m_probabilities[field][comparison_level] = P(observe this comparison
#   level | the two records are about the same person).
# u_probabilities[field][comparison_level] = P(observe this comparison
#   level | the two records are about different people).
#
# These are illustrative. In production, fit with EM on your data
# (Splink does this directly) and re-fit on a documented cadence.
# The general pattern: m is high for stable accurately-recorded
# fields (DOB matching exactly is very likely if the records are
# the same person); u is high when the comparison level reflects
# population frequency (a "match" on sex is very likely between
# two random records since there are only a few values).
M_PROBABILITIES = {
    "first_name": {
        "exact":            Decimal("0.85"),
        "jaro_winkler_high": Decimal("0.10"),
        "nickname_match":   Decimal("0.03"),
        "metaphone_match":  Decimal("0.01"),
        "mismatch":         Decimal("0.01"),
    },
    "last_name": {
        "exact":            Decimal("0.78"),
        "damerau_high":     Decimal("0.12"),
        "metaphone_match":  Decimal("0.05"),
        "hyphen_partial":   Decimal("0.04"),
        "mismatch":         Decimal("0.01"),
    },
    "dob": {
        "exact":            Decimal("0.92"),
        "year_only":        Decimal("0.02"),
        "month_day_swap":   Decimal("0.02"),
        "one_digit_off":    Decimal("0.02"),
        "mismatch":         Decimal("0.01"),
        "one_null":         Decimal("0.01"),
    },
    "sex": {
        "exact":            Decimal("0.97"),
        "mismatch":         Decimal("0.02"),
        "one_null":         Decimal("0.01"),
    },
    "address": {
        "exact":            Decimal("0.55"),
        "same_zip":         Decimal("0.20"),
        "same_street":      Decimal("0.10"),
        "mismatch":         Decimal("0.10"),
        "one_null":         Decimal("0.05"),
    },
    "phone": {
        "exact":            Decimal("0.50"),
        "last_7_match":     Decimal("0.15"),
        "last_4_match":     Decimal("0.10"),
        "mismatch":         Decimal("0.20"),
        "one_null":         Decimal("0.05"),
    },
    "ssn": {
        "exact":            Decimal("0.40"),
        "one_digit_off":    Decimal("0.05"),
        "mismatch":         Decimal("0.05"),
        "one_null":         Decimal("0.50"),
    },
    "email": {
        "exact":            Decimal("0.30"),
        "local_part_match": Decimal("0.05"),
        "mismatch":         Decimal("0.10"),
        "one_null":         Decimal("0.55"),
    },
}

U_PROBABILITIES = {
    "first_name": {
        "exact":            Decimal("0.005"),  # rare for unrelated people
        "jaro_winkler_high": Decimal("0.02"),
        "nickname_match":   Decimal("0.01"),
        "metaphone_match":  Decimal("0.05"),
        "mismatch":         Decimal("0.915"),
    },
    "last_name": {
        "exact":            Decimal("0.002"),  # very rare for unrelated people
        "damerau_high":     Decimal("0.005"),
        "metaphone_match":  Decimal("0.01"),
        "hyphen_partial":   Decimal("0.003"),
        "mismatch":         Decimal("0.98"),
    },
    "dob": {
        "exact":            Decimal("0.0001"),  # ~1/365/(active years), extremely rare
        "year_only":        Decimal("0.02"),
        "month_day_swap":   Decimal("0.0001"),
        "one_digit_off":    Decimal("0.001"),
        "mismatch":         Decimal("0.97"),
        "one_null":         Decimal("0.009"),
    },
    "sex": {
        "exact":            Decimal("0.5"),    # mostly two values, so common
        "mismatch":         Decimal("0.49"),
        "one_null":         Decimal("0.01"),
    },
    "address": {
        "exact":            Decimal("0.001"),
        "same_zip":         Decimal("0.05"),
        "same_street":      Decimal("0.005"),
        "mismatch":         Decimal("0.93"),
        "one_null":         Decimal("0.014"),
    },
    "phone": {
        "exact":            Decimal("0.0005"),
        "last_7_match":     Decimal("0.0005"),
        "last_4_match":     Decimal("0.005"),
        "mismatch":         Decimal("0.97"),
        "one_null":         Decimal("0.024"),
    },
    "ssn": {
        "exact":            Decimal("0.00001"),  # nearly unique
        "one_digit_off":    Decimal("0.0001"),
        "mismatch":         Decimal("0.59989"),
        "one_null":         Decimal("0.4"),
    },
    "email": {
        "exact":            Decimal("0.00005"),
        "local_part_match": Decimal("0.0005"),
        "mismatch":         Decimal("0.5995"),
        "one_null":         Decimal("0.4"),
    },
}

def _to_decimal(value) -> Decimal:
    """
    Coerce numeric input into Decimal for DynamoDB.

    DynamoDB rejects float. Always pass Decimal. The str() round-trip
    preserves whatever precision the input had, which matters for
    the log-likelihood ratios and probabilities used downstream.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))

def _now_iso() -> str:
    """UTC timestamp in ISO 8601 format. Always UTC; never local time."""
    return datetime.now(timezone.utc).isoformat()
```

---

## Step 1: Normalize Each Patient Record

*The pseudocode calls this `normalize_record(raw_record)`. In production, this Lambda is triggered by a registration-system event, reads the raw record from the source feed, and writes the normalized record to S3 and to the OpenSearch candidate index. Aggressive normalization is the single biggest lever for matching accuracy: skip it and downstream comparators will spend their time on case differences, whitespace, formatting variations, and diacritics rather than the substantive differences that should drive the match decision.*

The important work in this step is canonicalization, phonetic encoding, and quality flagging. Canonicalization removes format noise. Phonetic encoding (double metaphone) produces compact codes that group similar-sounding strings together; these codes feed both the comparators and the blocking-pass keys. Quality flags mark fields that are present-but-suspect (DOB of 01/01/1900, SSN of 999-99-9999) so the matcher does not give them undue weight.

```python
def _strip_diacritics(s: str) -> str:
    """
    Strip combining diacritical marks. "María" becomes "maria",
    "García-López" becomes "garcia-lopez". This is one common
    locale strategy; an alternative is to preserve diacritics and
    handle them in the comparators. Pick one and apply it
    consistently across the whole pipeline.
    """
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def _normalize_name(raw: Optional[str]) -> str:
    """
    Trim, case-fold, strip diacritics, collapse internal whitespace.
    Hyphens are preserved (they are meaningful in names). Apostrophes
    and punctuation other than hyphens are stripped.
    """
    if not raw:
        return ""
    s = _strip_diacritics(raw)
    s = s.lower().strip()
    # Replace any character that is not a letter, hyphen, or space
    # with a space, then collapse multiple spaces into one.
    s = re.sub(r"[^a-z\- ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _normalize_suffix(raw: Optional[str]) -> str:
    """
    Map "Jr.", "Jr", "JR", "Junior" all to canonical "jr".
    Returns empty string if the suffix is unrecognized or missing.
    """
    if not raw:
        return ""
    key = raw.lower().strip()
    return SUFFIX_CANONICAL.get(key, "")

def _expand_nicknames(first_name: str) -> set:
    """
    For matching purposes, "Bob" should also match "Robert".
    Return the set of plausible legal-name equivalents for a given
    first name. The set always includes the input name itself; if
    the name has no entry in the dictionary, the set is just the
    input name.
    """
    expanded = {first_name}
    if first_name in NICKNAME_TO_LEGAL:
        expanded.update(NICKNAME_TO_LEGAL[first_name])
    return expanded

def _double_metaphone(s: str) -> tuple:
    """
    Return the (primary, secondary) double-metaphone codes for the
    string. The secondary code captures alternative pronunciations
    and is None for most strings. Both codes are useful for
    blocking and as comparator inputs; matching on either code
    counts as a phonetic match.
    """
    if not s:
        return ("", "")
    primary, secondary = doublemetaphone(s)
    return (primary or "", secondary or "")

def _normalize_dob(raw: Optional[str]) -> tuple:
    """
    Parse DOB from any common format into canonical YYYY-MM-DD.
    Returns (canonical_dob_str, quality_flag). quality_flag is
    "ok" or one of "implausible_dob", "unparseable", "missing".

    Implausible values to flag: 1900-01-01, 9999-12-31, 0001-01-01,
    or a year more than 130 years in the past or in the future.
    These are common garbage values entered when the registration
    clerk did not have a real DOB and the system required a value;
    they should not be used as matching evidence.
    """
    if not raw or not raw.strip():
        return ("", "missing")
    try:
        # dayfirst=False handles US-style MM/DD/YYYY by default.
        # In non-US deployments, set dayfirst=True or detect the
        # format from a per-source configuration.
        parsed = dateparser.parse(str(raw), dayfirst=False, fuzzy=False)
    except (ValueError, dateparser.ParserError, OverflowError):
        return ("", "unparseable")
    canonical = parsed.strftime("%Y-%m-%d")
    # Implausible-value check.
    today = datetime.now(timezone.utc).date()
    if parsed.year < (today.year - 130) or parsed.year > today.year:
        return (canonical, "implausible_dob")
    if canonical in {"1900-01-01", "9999-12-31", "0001-01-01"}:
        return (canonical, "implausible_dob")
    return (canonical, "ok")

def _normalize_phone(raw: Optional[str]) -> str:
    """
    Strip all non-digit characters. Drop a leading "1" so that
    +1-555-123-4567 and 555-123-4567 both produce 5551234567.
    Extensions are dropped (a real system stores them separately).
    """
    if not raw:
        return ""
    digits = re.sub(r"\D", "", raw)
    # Strip a leading "1" only if the result is then 10 digits.
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits

def _normalize_ssn(raw: Optional[str]) -> tuple:
    """
    Strip non-digit characters; flag obvious garbage values.
    Returns (canonical_ssn, quality_flag).
    """
    if not raw:
        return ("", "missing")
    digits = re.sub(r"\D", "", raw)
    if len(digits) != 9:
        return ("", "invalid_pattern")
    # Known-garbage patterns: all zeros, all nines, sequential.
    if digits in {"000000000", "999999999", "123456789"}:
        return (digits, "invalid_pattern")
    # Area number 000 or 666 are reserved/invalid.
    if digits.startswith("000") or digits.startswith("666"):
        return (digits, "invalid_pattern")
    return (digits, "ok")

def _normalize_email(raw: Optional[str]) -> str:
    """Lowercase, trim. Basic pattern check; nothing fancy."""
    if not raw:
        return ""
    s = raw.lower().strip()
    # Coarse pattern check; do not attempt full RFC 5322 here.
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", s):
        return ""
    return s

def _normalize_address(raw: Optional[str]) -> str:
    """
    Coarse address normalization. A real system pipes this through
    a CASS-certified product (SmartyStreets, Melissa, the USPS API)
    that returns a canonical USPS form, deliverability flag, and
    ZIP+4. The regex below handles the obvious cases (uppercase,
    abbreviation expansion) but will not catch the long tail.
    """
    if not raw:
        return ""
    s = raw.upper().strip()
    s = re.sub(r"\s+", " ", s)
    # A handful of common abbreviations. A full mapping is maintained
    # by USPS Publication 28; the tools above implement it correctly.
    s = re.sub(r"\bSTREET\b",  "ST",  s)
    s = re.sub(r"\bAVENUE\b",  "AVE", s)
    s = re.sub(r"\bROAD\b",    "RD",  s)
    s = re.sub(r"\bAPARTMENT\b", "APT", s)
    s = re.sub(r"\bSUITE\b",   "STE", s)
    s = re.sub(r"\bSAINT\b",   "ST",  s)  # ambiguous with STREET; CASS handles correctly
    return s

def _zip_from_address(addr_usps: str) -> str:
    """Pull the ZIP (5-digit or ZIP+4) out of the normalized address."""
    if not addr_usps:
        return ""
    m = re.search(r"(\d{5})(?:-\d{4})?\b", addr_usps)
    return m.group(1) if m else ""

def normalize_record(raw_record: dict) -> dict:
    """
    Apply the full normalization pipeline to one raw patient record.
    Output is the canonical form used everywhere downstream.

    Expected input keys (any may be missing):
      source_system, source_record_id, first_name, middle_name,
      last_name, suffix, dob, sex, address, phone, ssn, email
    """
    first_name = _normalize_name(raw_record.get("first_name"))
    last_name  = _normalize_name(raw_record.get("last_name"))
    middle_name = _normalize_name(raw_record.get("middle_name"))
    suffix     = _normalize_suffix(raw_record.get("suffix"))

    dob_canon, dob_flag = _normalize_dob(raw_record.get("dob"))
    ssn_canon, ssn_flag = _normalize_ssn(raw_record.get("ssn"))
    phone = _normalize_phone(raw_record.get("phone"))
    email = _normalize_email(raw_record.get("email"))
    address_usps = _normalize_address(raw_record.get("address"))

    first_metaphone_pri, first_metaphone_sec = _double_metaphone(first_name)
    last_metaphone_pri,  last_metaphone_sec  = _double_metaphone(last_name)

    return {
        "source_system":         raw_record.get("source_system", ""),
        "source_record_id":      raw_record.get("source_record_id", ""),
        "first_name":            first_name,
        "first_name_expanded":   sorted(_expand_nicknames(first_name)),
        "first_name_metaphone":  first_metaphone_pri,
        "middle_name":           middle_name,
        "last_name":             last_name,
        "last_name_metaphone":   last_metaphone_pri,
        "last_name_metaphone_sec": last_metaphone_sec or "",
        "suffix":                suffix,
        "dob":                   dob_canon,
        "dob_quality_flag":      dob_flag,
        "sex":                   (raw_record.get("sex") or "").strip().upper()[:1],
        "address_usps":          address_usps,
        "zip":                   _zip_from_address(address_usps),
        "phone":                 phone,
        "phone_last_7":          phone[-7:] if phone else "",
        "phone_last_4":          phone[-4:] if phone else "",
        "ssn":                   ssn_canon,
        "ssn_quality_flag":      ssn_flag,
        "email":                 email,
        "normalized_at":         _now_iso(),
        "normalizer_version":    NORMALIZER_VERSION,
    }
```

---

## Step 2: Generate Candidate Pairs Through Multiple Blocking Passes

*The pseudocode calls this `generate_candidate_pairs(normalized_records)`. Comparing every record to every other record is O(n²); at any reasonable scale that is not feasible. Blocking partitions records into smaller buckets such that records within a bucket are plausibly related and records in different buckets are very unlikely to be the same person. Multiple passes use different blocking keys; their union is the candidate set. This is the recall-vs-cost knob, and tuning it is the single most consequential engineering decision in the pipeline.*

The implementation below is a tiny in-process blocker that works for tens of thousands of records. Production replaces this with either a Spark/Glue batch job (using `splink` or `recordlinkage`) or an OpenSearch-backed real-time index that supports the equivalents of these blocking passes as `bool` queries with phonetic and prefix matchers.

```python
def _safe_initial(s: str) -> str:
    """First character or empty string. Avoids index errors on empty names."""
    return s[0] if s else ""

def _year(dob: str) -> str:
    """Year portion of YYYY-MM-DD, or empty string if missing."""
    return dob.split("-")[0] if dob else ""

def _make_pair_key(record_a: dict, record_b: dict) -> tuple:
    """
    Stable, order-independent key for a candidate pair. Used to
    deduplicate pairs that show up in multiple blocking passes.
    """
    a_id = (record_a["source_system"], record_a["source_record_id"])
    b_id = (record_b["source_system"], record_b["source_record_id"])
    return tuple(sorted([a_id, b_id]))

def generate_candidate_pairs(normalized_records: list) -> list:
    """
    Run multiple blocking passes and return the deduplicated union
    of candidate pairs. Each pass groups records by a different
    blocking key designed to capture a different failure mode of
    the others.
    """
    candidate_pairs = {}  # pair_key -> (record_a, record_b, [pass_names])

    def _block_and_collect(pass_name: str, key_fn):
        """Group records by key_fn and add intra-block pairs."""
        blocks = {}
        for r in normalized_records:
            k = key_fn(r)
            # An empty key means we can't block on this pass for this
            # record; skip it rather than putting it in a giant
            # "everything-with-missing-data" bucket.
            if not all(part for part in k):
                continue
            blocks.setdefault(k, []).append(r)

        for block_key, members in blocks.items():
            if len(members) > MAX_BLOCK_SIZE:
                # Skip the giant blocks. They explode the comparison
                # count without contributing useful candidates; the
                # other blocking passes catch the duplicates that
                # matter. Log oversized blocks for monitoring.
                logger.info(
                    "skipping oversized block",
                    extra={"pass": pass_name, "size": len(members)},
                )
                continue
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    pk = _make_pair_key(members[i], members[j])
                    if pk in candidate_pairs:
                        candidate_pairs[pk][2].append(pass_name)
                    else:
                        candidate_pairs[pk] = (members[i], members[j], [pass_name])

    # Pass 1: last-name metaphone + DOB year. Catches most direct
    # duplicates with name spelling variations, since the metaphone
    # is robust to most spelling variants ("Smith" vs "Smyth"
    # produce the same code).
    _block_and_collect(
        "lastname_metaphone__dob_year",
        lambda r: (r["last_name_metaphone"], _year(r["dob"])),
    )

    # Pass 2: first-name metaphone + last-initial + DOB year.
    # Catches duplicates with last-name change (marriage, divorce)
    # where the first name is stable and the last initial happens
    # to still match.
    _block_and_collect(
        "firstname_metaphone__lastinitial__dob_year",
        lambda r: (
            r["first_name_metaphone"],
            _safe_initial(r["last_name"]),
            _year(r["dob"]),
        ),
    )

    # Pass 3: last-name initial + full DOB. Catches duplicates with
    # significant first-name variation (nickname mismatches like
    # "Bob" vs "Robert" before the nickname expansion is in play
    # downstream).
    _block_and_collect(
        "lastinitial__dob_full",
        lambda r: (_safe_initial(r["last_name"]), r["dob"]),
    )

    # Pass 4: ZIP + last-name initial. Catches duplicates with DOB
    # data quality issues. Skip if no ZIP (the helper drops keys
    # with empty parts).
    _block_and_collect(
        "zip__lastinitial",
        lambda r: (r["zip"], _safe_initial(r["last_name"])),
    )

    # Pass 5: phone last-4 + DOB year. Catches duplicates where the
    # name was entered very differently (transliteration variation,
    # major typos) but the phone number is stable. Also catches
    # legal name change where the phone is unchanged.
    _block_and_collect(
        "phone_last4__dob_year",
        lambda r: (r["phone_last_4"], _year(r["dob"])),
    )

    # Add more passes as needed based on recall measurement against
    # the labeled gold set. Each pass costs candidate-pair count;
    # add only if it materially improves recall. A common addition:
    # SSN-prefix + DOB-year (catches duplicates with name and
    # address changes but stable SSN).

    # Return as a list of (record_a, record_b, blocking_passes).
    return [
        (a, b, passes) for (a, b, passes) in candidate_pairs.values()
    ]
```

---

## Step 3: Score Each Candidate Pair

*The pseudocode calls this `score_pair(record_a, record_b, model)`. Per-field comparators tuned to each field's failure modes feed a probabilistic combiner that turns the per-field comparison levels into a single composite log-likelihood ratio. Skip the per-field tuning and you get bad scores on common patterns (transposed DOB digits, nicknames, hyphenated names). Skip the probabilistic combination and you do ad-hoc weighted scoring that does not reflect the actual information value of each field; SSN match becomes equally weighted with first-name match, which is wrong by orders of magnitude.*

The Fellegi-Sunter combiner sums `log(m/u)` for matching field comparisons and `log((1-m)/(1-u))` for non-matching ones. The hand-set m/u probabilities in the configuration block are illustrative; in production fit them with EM on your data.

```python
def _compare_first_name(a: dict, b: dict) -> str:
    """
    Compare two normalized first names. Return the comparison level
    that the Fellegi-Sunter combiner will look up in M_PROBABILITIES
    and U_PROBABILITIES.
    """
    a_first, b_first = a["first_name"], b["first_name"]
    if not a_first or not b_first:
        return "mismatch"  # treat null as mismatch for first_name
    if a_first == b_first:
        return "exact"

    # Nickname expansion: do the expanded sets share a name?
    if set(a["first_name_expanded"]) & set(b["first_name_expanded"]):
        if a_first != b_first:
            return "nickname_match"

    # Jaro-Winkler for short-string typos. Threshold of 0.92 is a
    # reasonable starting point; tune against your gold set.
    jw = jellyfish.jaro_winkler_similarity(a_first, b_first)
    if jw >= 0.92:
        return "jaro_winkler_high"

    # Phonetic match catches "Catherine" vs "Katherine" and similar.
    if a["first_name_metaphone"] and (
        a["first_name_metaphone"] == b["first_name_metaphone"]
    ):
        return "metaphone_match"

    return "mismatch"

def _compare_last_name(a: dict, b: dict) -> str:
    """
    Compare two normalized last names with Damerau-Levenshtein
    (typo-aware), metaphone (phonetic), and a hyphenated-partial
    matcher (handles maiden-married name changes that retain the
    maiden component).
    """
    a_last, b_last = a["last_name"], b["last_name"]
    if not a_last or not b_last:
        return "mismatch"
    if a_last == b_last:
        return "exact"

    # Hyphenated-partial: "garcia" vs "garcia-lopez" should match
    # if either side is a token of the other side. This is a common
    # marriage / divorce / cultural-naming pattern.
    a_tokens = set(a_last.replace("-", " ").split())
    b_tokens = set(b_last.replace("-", " ").split())
    if a_tokens & b_tokens and a_tokens != b_tokens:
        # At least one shared token but not a full match.
        return "hyphen_partial"

    # Damerau-Levenshtein for typos (including transpositions:
    # "Garcia" vs "Garica" is one transposition).
    distance = jellyfish.damerau_levenshtein_distance(a_last, b_last)
    longest = max(len(a_last), len(b_last))
    similarity = 1.0 - (distance / longest) if longest else 0.0
    if similarity >= 0.85:
        return "damerau_high"

    # Phonetic match catches "Smith" vs "Smyth". With real double
    # metaphone, match on either primary or secondary code.
    if a["last_name_metaphone"] and b["last_name_metaphone"]:
        a_codes = {a["last_name_metaphone"], a.get("last_name_metaphone_sec", "")} - {""}
        b_codes = {b["last_name_metaphone"], b.get("last_name_metaphone_sec", "")} - {""}
        if a_codes & b_codes:
            return "metaphone_match"

    return "mismatch"

def _compare_dob(a: dict, b: dict) -> str:
    """
    Compare two canonical DOBs. Catches several common entry errors:
    month/day swap (US clerk enters DD/MM instead of MM/DD), one
    digit off (typo), and year-only match (one record has the wrong
    month and day but the right year). Implausible-DOB-flagged
    records produce a "one_null" comparison rather than a false
    match on the garbage value.
    """
    a_dob, b_dob = a["dob"], b["dob"]
    a_flag, b_flag = a["dob_quality_flag"], b["dob_quality_flag"]

    # Implausible or missing values do not contribute information;
    # treat as null. Standard Fellegi-Sunter null-handling: null on
    # one or both sides contributes zero log-likelihood.
    if a_flag != "ok" or b_flag != "ok":
        return "one_null"
    if not a_dob or not b_dob:
        return "one_null"

    if a_dob == b_dob:
        return "exact"

    # Year match only.
    a_year, b_year = a_dob.split("-")[0], b_dob.split("-")[0]
    if a_year == b_year:
        # Check for month/day swap: a_dob has month X day Y,
        # b_dob has month Y day X.
        a_parts = a_dob.split("-")  # [YYYY, MM, DD]
        b_parts = b_dob.split("-")
        if a_parts[1] == b_parts[2] and a_parts[2] == b_parts[1]:
            return "month_day_swap"
        return "year_only"

    # One digit off across the whole string.
    if len(a_dob) == len(b_dob):
        diffs = sum(1 for x, y in zip(a_dob, b_dob) if x != y)
        if diffs == 1:
            return "one_digit_off"

    return "mismatch"

def _compare_categorical(a_val: str, b_val: str) -> str:
    """For sex and other small-cardinality fields."""
    if not a_val or not b_val:
        return "one_null"
    return "exact" if a_val == b_val else "mismatch"

def _compare_address(a: dict, b: dict) -> str:
    """
    Compare normalized addresses. A real system uses USPS-standardized
    forms with ZIP+4; the demo's coarse normalizer means same-street
    and same-zip detection is approximate.

    NOTE: The recipe's pseudocode names levels `exact`,
    `same_zip_plus_4`, `same_street_different_apt`,
    `same_zip_different_street`, `mismatch`, `one_null`, and
    `both_null`. The demo collapses these into `exact`,
    `same_street` (covers same-street-different-apt and
    same-zip-plus-4 in practice since the demo's coarse normalizer
    does not surface ZIP+4), `same_zip` (same ZIP, different
    street; the recipe's `same_zip_different_street`), `mismatch`,
    and `one_null` (both nulls and one-null collapsed). Production
    reads ZIP+4 from a CASS-certified standardizer and exposes the
    finer-grained levels; the M/U tables would carry per-level
    entries to match.
    """
    a_addr, b_addr = a["address_usps"], b["address_usps"]
    if not a_addr or not b_addr:
        return "one_null"
    if a_addr == b_addr:
        return "exact"
    if a["zip"] and a["zip"] == b["zip"]:
        # Same ZIP, different exact address. Check for same street
        # number and street name (approximate match on the leading
        # tokens of the address).
        a_lead = " ".join(a_addr.split()[:3])
        b_lead = " ".join(b_addr.split()[:3])
        if a_lead == b_lead:
            return "same_street"
        return "same_zip"
    return "mismatch"

def _compare_phone(a: dict, b: dict) -> str:
    if not a["phone"] or not b["phone"]:
        return "one_null"
    if a["phone"] == b["phone"]:
        return "exact"
    if a["phone_last_7"] and a["phone_last_7"] == b["phone_last_7"]:
        return "last_7_match"
    if a["phone_last_4"] and a["phone_last_4"] == b["phone_last_4"]:
        return "last_4_match"
    return "mismatch"

def _compare_ssn(a: dict, b: dict) -> str:
    """SSN is highly informative when present, so we check carefully."""
    a_ssn, b_ssn = a["ssn"], b["ssn"]
    a_flag, b_flag = a["ssn_quality_flag"], b["ssn_quality_flag"]
    # Treat invalid-pattern flagged SSNs as null; never auto-match
    # on a known-garbage value.
    if a_flag != "ok" or b_flag != "ok":
        return "one_null"
    if not a_ssn or not b_ssn:
        return "one_null"
    if a_ssn == b_ssn:
        return "exact"
    if len(a_ssn) == len(b_ssn):
        diffs = sum(1 for x, y in zip(a_ssn, b_ssn) if x != y)
        if diffs == 1:
            return "one_digit_off"
    return "mismatch"

def _compare_email(a: dict, b: dict) -> str:
    a_email, b_email = a["email"], b["email"]
    if not a_email or not b_email:
        return "one_null"
    if a_email == b_email:
        return "exact"
    a_local = a_email.split("@", 1)[0] if "@" in a_email else a_email
    b_local = b_email.split("@", 1)[0] if "@" in b_email else b_email
    if a_local == b_local:
        return "local_part_match"
    return "mismatch"

def _log_likelihood_ratio(field: str, level: str) -> Decimal:
    """
    Per-field, per-comparison-level log-likelihood-ratio contribution.

    Each comparison level (exact, jaro_winkler_high, mismatch, etc.)
    has its own (m, u) entry in M_PROBABILITIES / U_PROBABILITIES, so
    log(m_level / u_level) is the correct contribution uniformly: a
    "match" level (m > u) contributes positively, a "mismatch" level
    (m < u) contributes negatively. Null-on-one-side contributes zero
    under standard Fellegi-Sunter (no information about identity).

    Returns Decimal("0") for null cases and for missing or
    zero-probability table entries (defensive against table
    misconfiguration).
    """
    m = M_PROBABILITIES.get(field, {}).get(level)
    u = U_PROBABILITIES.get(field, {}).get(level)
    if m is None or u is None:
        return Decimal("0")
    if level == "one_null":
        # Null on one side is uninformative under standard FS.
        return Decimal("0")
    if m <= 0 or u <= 0:
        return Decimal("0")
    # math.log returns float; coerce to Decimal for downstream.
    return _to_decimal(math.log(float(m) / float(u)))

def score_pair(record_a: dict, record_b: dict) -> dict:
    """
    Run per-field comparators and combine via Fellegi-Sunter into a
    composite log-likelihood ratio. Returns a dict with the score,
    the per-field comparison levels, and the per-field contributions
    so the review queue can show why the pair scored as it did.
    """
    field_comparisons = {
        "first_name": _compare_first_name(record_a, record_b),
        "last_name":  _compare_last_name(record_a, record_b),
        "dob":        _compare_dob(record_a, record_b),
        "sex":        _compare_categorical(record_a["sex"], record_b["sex"]),
        "address":    _compare_address(record_a, record_b),
        "phone":      _compare_phone(record_a, record_b),
        "ssn":        _compare_ssn(record_a, record_b),
        "email":      _compare_email(record_a, record_b),
    }

    per_field_log_ratios = {
        field: _log_likelihood_ratio(field, level)
        for field, level in field_comparisons.items()
    }
    composite = sum(per_field_log_ratios.values(), Decimal("0"))

    # Sigmoid for a 0-1 match-probability display value. The composite
    # log-likelihood ratio is what drives routing; the probability is
    # only for human-friendly display.
    match_probability = Decimal(str(1.0 / (1.0 + math.exp(-float(composite)))))

    return {
        "record_a_id":          record_a["source_record_id"],
        "record_b_id":          record_b["source_record_id"],
        "composite_score":      composite,
        "match_probability":    match_probability,
        "field_comparisons":    field_comparisons,
        "per_field_log_ratios": per_field_log_ratios,
        "scored_at":            _now_iso(),
        "model_version":        MODEL_VERSION,
    }
```

---

## Step 4: Route Each Pair by Threshold

*The pseudocode calls this `route_pair(pair_score, thresholds)`. Three buckets: auto-match (above the high threshold), auto-non-match (below the low threshold), and human review (everything in between). Skip the conservative-thresholds discipline and you will either auto-merge wrong patients (a patient safety hazard) or flood the review queue with garbage (reviewer burnout, system collapse).*

The function below writes review-queue items to DynamoDB and the audit archive object to S3. Auto-match and auto-non-match results are also recorded to the audit archive even though they do not produce queue entries: the archive is the forensic-grade trail of every decision the system made, regardless of routing.

```python
def _serialize_for_dynamodb(obj):
    """
    Recursively convert lists / dicts so that anything storeable
    survives the round-trip into DynamoDB. The notable conversion:
    Decimal stays Decimal; floats would raise. Tuples become lists.
    """
    if isinstance(obj, dict):
        return {k: _serialize_for_dynamodb(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_for_dynamodb(v) for v in obj]
    if isinstance(obj, float):
        # Should not happen if upstream code uses Decimal; coerce
        # defensively rather than crash a real-time match.
        return Decimal(str(obj))
    return obj

def _write_audit_archive(record: dict, partition: str) -> None:
    """
    Write a JSON-serialized audit record to S3, partitioned by the
    decision type and date for efficient cohort-stratified analytics.
    The archive is immutable; never overwrite a key.
    """
    today = datetime.now(timezone.utc).strftime("%Y/%m/%d")
    audit_key = f"audit/{partition}/{today}/{uuid.uuid4()}.json"
    body = json.dumps(record, default=str).encode("utf-8")
    try:
        s3_client.put_object(
            Bucket=AUDIT_BUCKET,
            Key=audit_key,
            Body=body,
            # SSE-KMS in production with a customer-managed key.
            ServerSideEncryption="aws:kms",
        )
    except Exception as exc:
        # Never silently lose audit data. Surface the failure but do
        # not block the routing decision; in production a DLQ + alarm
        # picks this up.
        logger.error(
            "audit archive write failed",
            extra={"partition": partition, "error": str(exc)},
        )

def _emit_metric(metric_name: str, value: float, dimensions: dict = None) -> None:
    """Emit a CloudWatch metric. Failures are logged but non-fatal."""
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

def route_pair(
    pair_score: dict,
    record_a: dict,
    record_b: dict,
    high_threshold: Decimal = HIGH_THRESHOLD,
    low_threshold: Decimal = LOW_THRESHOLD,
) -> str:
    """
    Decide auto_match / review / auto_non_match. Write the outcome
    to the audit archive. For review, also write the pair to the
    review-queue DynamoDB table with full snapshots of both records.
    Returns the routing decision string.
    """
    score = pair_score["composite_score"]
    if score >= high_threshold:
        decision = "auto_match"
    elif score <= low_threshold:
        decision = "auto_non_match"
    else:
        decision = "review"

    # Tag the audit archive entry with the routing decision so the
    # downstream analytics partition is clean.
    audit_record = _serialize_for_dynamodb({
        **pair_score,
        "routing_decision": decision,
        "high_threshold":   high_threshold,
        "low_threshold":    low_threshold,
        "snapshots": {
            "record_a": record_a,
            "record_b": record_b,
        },
    })
    _write_audit_archive(audit_record, partition=decision)

    # CloudWatch counters: per-routing-decision per-day rates power
    # the operational dashboard and alarm on rate drift.
    _emit_metric("RoutingDecision", 1.0, dimensions={"Decision": decision})

    if decision == "review":
        # Priority: closer-to-high-threshold pairs are higher
        # priority for reviewers (they are the highest-EV items).
        priority = max(
            Decimal("0"),
            Decimal("100") * (score - low_threshold) / (high_threshold - low_threshold),
        )
        candidate_pair_id = str(uuid.uuid4())
        review_item = _serialize_for_dynamodb({
            "queue_id":            "default",  # tier by clinical area in production
            "candidate_pair_id":   candidate_pair_id,
            "score":               score,
            "match_probability":   pair_score["match_probability"],
            "field_comparisons":   pair_score["field_comparisons"],
            "per_field_log_ratios": pair_score["per_field_log_ratios"],
            "snapshots": {
                "record_a": record_a,
                "record_b": record_b,
            },
            "priority":      priority,
            "queued_at":     _now_iso(),
            "review_status": "pending",
            "model_version": pair_score["model_version"],
        })
        try:
            dynamodb.Table(REVIEW_QUEUE_TABLE).put_item(Item=review_item)
        except Exception as exc:
            # In production: send to DLQ + alarm. Never silently
            # drop a review-queue write.
            logger.error(
                "review queue write failed",
                extra={"pair_id": candidate_pair_id, "error": str(exc)},
            )

    return decision
```

---

## Step 5: Apply the Merge with Survivorship and Full Audit

*The pseudocode calls this `apply_merge(record_a, record_b, decision_metadata)`. Survivorship rules decide which fields win on the golden record. Full provenance preserves the path back to the source records and supports unmerge. Skip the survivorship discipline and the merged record will be missing fields or carrying stale ones; skip the provenance and you cannot unmerge cleanly when a wrong merge surfaces.*

The merge logic below handles three cases: both records already linked under the same `mpi_id` (idempotent), each record under a different `mpi_id` (cluster merge), and at least one record without an `mpi_id` (fresh assignment). The unmerge function at the bottom is the reversibility path: every merge writes enough state to be reversed. This needs to be in place from day one; bolting reversibility on after a year of merges is painful and lossy.

```python
def _merge_with_rule(a_val, b_val, rule: str):
    """
    Pure function: apply a single survivorship rule to two values.
    Returns the surviving value plus a small audit dict explaining
    which rule applied and why.
    """
    if rule == "non_null_consistent_or_flag":
        if a_val and b_val:
            if a_val == b_val:
                return a_val, {"rule": rule, "outcome": "consistent"}
            return a_val, {"rule": rule, "outcome": "conflict_flagged",
                           "alternative": b_val}
        return (a_val or b_val), {"rule": rule, "outcome": "non_null_picked"}

    if rule == "longest_non_null":
        if a_val and b_val:
            return ((a_val if len(str(a_val)) >= len(str(b_val)) else b_val),
                    {"rule": rule, "outcome": "longest_picked"})
        return (a_val or b_val), {"rule": rule, "outcome": "non_null_picked"}

    raise ValueError(f"unknown survivorship rule: {rule}")

def _pick_surviving_mpi_id(xref_a: dict, xref_b: dict) -> str:
    """
    Pick which mpi_id wins when both records already have one. Default
    rule: lower id (oldest by lexicographic sort) wins; the institution
    can override with its own canonical-id policy.
    """
    a_id = xref_a.get("mpi_id") if xref_a else None
    b_id = xref_b.get("mpi_id") if xref_b else None
    if a_id and b_id:
        return min(a_id, b_id)
    if a_id:
        return a_id
    if b_id:
        return b_id
    return f"mpi-{uuid.uuid4()}"

def _get_xref(record: dict) -> Optional[dict]:
    """Look up an existing mpi-xref entry for a source record. None if not yet assigned."""
    try:
        resp = dynamodb.Table(MPI_XREF_TABLE).get_item(
            Key={
                "source_system":    record["source_system"],
                "source_record_id": record["source_record_id"],
            }
        )
        return resp.get("Item")
    except Exception as exc:
        logger.error("mpi-xref read failed", extra={"error": str(exc)})
        return None

def _query_cluster_members(mpi_id: str) -> list:
    """All xref entries currently assigned to this mpi_id."""
    if not mpi_id:
        return []
    try:
        items = []
        table = dynamodb.Table(MPI_XREF_TABLE)
        kwargs = {
            "IndexName": MPI_ID_INDEX,
            "KeyConditionExpression": Key("mpi_id").eq(mpi_id),
        }
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key
        return items
    except Exception as exc:
        logger.error("mpi-xref cluster query failed", extra={"error": str(exc)})
        return []

def apply_merge(record_a: dict, record_b: dict, decision_metadata: dict) -> str:
    """
    Apply the merge and write the audit record. Returns the
    surviving mpi_id.

    decision_metadata is the audit context: who or what decided
    (auto-match with score X, or human reviewer with ID Y), the
    score, the routing path, the model version, and the timestamp.
    """
    xref_a = _get_xref(record_a)
    xref_b = _get_xref(record_b)

    # Idempotency check: if both records already point to the same
    # mpi_id, this is a re-confirmation, not a new merge. Real-time
    # matching is event-driven and will see the same pair more than
    # once; the merge must be safe to call repeatedly.
    if xref_a and xref_b and xref_a.get("mpi_id") and (
        xref_a.get("mpi_id") == xref_b.get("mpi_id")
    ):
        logger.info("merge idempotent; already linked")
        return xref_a["mpi_id"]

    surviving_mpi_id = _pick_surviving_mpi_id(xref_a, xref_b)

    # Load the master records for both clusters (if they exist).
    master_a = master_b = None
    if xref_a and xref_a.get("mpi_id"):
        master_a = dynamodb.Table(MPI_MASTER_TABLE).get_item(
            Key={"mpi_id": xref_a["mpi_id"]}
        ).get("Item")
    if xref_b and xref_b.get("mpi_id"):
        master_b = dynamodb.Table(MPI_MASTER_TABLE).get_item(
            Key={"mpi_id": xref_b["mpi_id"]}
        ).get("Item")

    # If either side has no master, seed it from the source record.
    # This keeps the merge logic uniform: there is always an "old"
    # master per side that we are merging into the survivor.
    if not master_a:
        master_a = _seed_master_from_record(record_a, xref_a)
    if not master_b:
        master_b = _seed_master_from_record(record_b, xref_b)

    # Apply per-field survivorship rules. This block is the heart of
    # the merge; in production the rules are documented and signed
    # off by HIM, clinical informatics, and (where applicable) the
    # privacy office. Iterate as patterns emerge.
    survivorship_decisions = {}

    surviving_first_name, sd1 = _merge_with_rule(
        master_a.get("first_name"), master_b.get("first_name"), "longest_non_null"
    )
    survivorship_decisions["first_name"] = sd1

    surviving_last_name, sd2 = _merge_with_rule(
        master_a.get("last_name"), master_b.get("last_name"), "longest_non_null"
    )
    survivorship_decisions["last_name"] = sd2

    surviving_dob, sd3 = _merge_with_rule(
        master_a.get("dob"), master_b.get("dob"), "non_null_consistent_or_flag"
    )
    survivorship_decisions["dob"] = sd3

    surviving_sex, sd4 = _merge_with_rule(
        master_a.get("sex"), master_b.get("sex"), "non_null_consistent_or_flag"
    )
    survivorship_decisions["sex"] = sd4

    surviving_ssn, sd5 = _merge_with_rule(
        master_a.get("ssn"), master_b.get("ssn"), "non_null_consistent_or_flag"
    )
    survivorship_decisions["ssn"] = sd5

    # For history-style fields (address, phone, email), preserve the
    # union of both clusters rather than picking a single value. The
    # "current" value is the most recent entry; the rest stay as
    # history. Wrong survivorship on history-style fields can lose
    # clinically significant data.
    address_history = _combine_history_lists(
        master_a.get("address_history", []),
        master_b.get("address_history", []),
    )
    phone_history = _combine_history_lists(
        master_a.get("phone_history", []),
        master_b.get("phone_history", []),
    )
    email_history = _combine_history_lists(
        master_a.get("email_history", []),
        master_b.get("email_history", []),
    )
    survivorship_decisions["address_history"] = {
        "rule": "merge_history_with_dedup",
        "outcome": f"combined {len(address_history)} entries",
    }
    survivorship_decisions["phone_history"] = {
        "rule": "merge_history_with_dedup",
        "outcome": f"combined {len(phone_history)} entries",
    }
    survivorship_decisions["email_history"] = {
        "rule": "merge_history_with_dedup",
        "outcome": f"combined {len(email_history)} entries",
    }

    merged_master = _serialize_for_dynamodb({
        "mpi_id":                surviving_mpi_id,
        "first_name":            surviving_first_name,
        "last_name":             surviving_last_name,
        "dob":                   surviving_dob,
        "sex":                   surviving_sex,
        "ssn":                   surviving_ssn,
        "address_history":       address_history,
        "phone_history":         phone_history,
        "email_history":         email_history,
        "merged_from_clusters":  [m.get("mpi_id") for m in (master_a, master_b)
                                   if m.get("mpi_id")],
        "last_merge_at":         _now_iso(),
        "survivorship_rules_version": SURVIVORSHIP_RULES_VERSION,
        "active":                True,
    })

    # Persist the merged master and update cross-references for every
    # source record in either cluster. A real implementation does
    # this in a TransactWriteItems call to keep the master and xref
    # writes atomic; the demo splits them for readability.
    try:
        dynamodb.Table(MPI_MASTER_TABLE).put_item(Item=merged_master)
    except Exception as exc:
        logger.error(
            "merge master write failed",
            extra={"mpi_id": surviving_mpi_id, "error": str(exc)},
        )
        raise

    cluster_a_members = _query_cluster_members(master_a.get("mpi_id"))
    cluster_b_members = _query_cluster_members(master_b.get("mpi_id"))
    all_members = cluster_a_members + cluster_b_members
    # Always include the two records we are merging right now (in
    # case neither was previously assigned).
    for r in (record_a, record_b):
        all_members.append({
            "source_system":    r["source_system"],
            "source_record_id": r["source_record_id"],
            "mpi_id":           None,
        })

    for member in all_members:
        previous_mpi_id = member.get("mpi_id")
        try:
            dynamodb.Table(MPI_XREF_TABLE).update_item(
                Key={
                    "source_system":    member["source_system"],
                    "source_record_id": member["source_record_id"],
                },
                UpdateExpression=(
                    "SET mpi_id = :new_mpi, "
                    "last_reassigned_at = :ts, "
                    "previous_mpi_id_history = list_append("
                    "    if_not_exists(previous_mpi_id_history, :empty), :prev)"
                ),
                ExpressionAttributeValues={
                    ":new_mpi": surviving_mpi_id,
                    ":ts":      _now_iso(),
                    ":prev":    [previous_mpi_id] if previous_mpi_id else [],
                    ":empty":   [],
                },
            )
        except Exception as exc:
            logger.error(
                "xref update failed",
                extra={"member": member.get("source_record_id"), "error": str(exc)},
            )

    # Mark the deprecated cluster as merged-into-survivor.
    deprecated_mpi_ids = []
    for old_master in (master_a, master_b):
        if old_master.get("mpi_id") and old_master["mpi_id"] != surviving_mpi_id:
            deprecated_mpi_ids.append(old_master["mpi_id"])
            try:
                dynamodb.Table(MPI_MASTER_TABLE).update_item(
                    Key={"mpi_id": old_master["mpi_id"]},
                    UpdateExpression=(
                        "SET active = :false, merged_into = :surv, merged_at = :ts"
                    ),
                    ExpressionAttributeValues={
                        ":false": False,
                        ":surv":  surviving_mpi_id,
                        ":ts":    _now_iso(),
                    },
                )
            except Exception as exc:
                logger.error(
                    "deprecated master update failed",
                    extra={"mpi_id": old_master["mpi_id"], "error": str(exc)},
                )

    # Write the merge audit record. This is the artifact that supports
    # unmerge if the decision proves wrong; preserve enough state to
    # restore the pre-merge masters and xrefs.
    audit_record = _serialize_for_dynamodb({
        "merge_id":              str(uuid.uuid4()),
        "surviving_mpi_id":      surviving_mpi_id,
        "deprecated_mpi_ids":    deprecated_mpi_ids,
        "source_records_in_merge": all_members,
        "decision_metadata":     decision_metadata,
        "survivorship_decisions": survivorship_decisions,
        "pre_merge_master_a":    master_a,
        "pre_merge_master_b":    master_b,
        "merged_at":             _now_iso(),
        "survivorship_rules_version": SURVIVORSHIP_RULES_VERSION,
    })
    _write_audit_archive(audit_record, partition="merge")

    # Emit the merge event for downstream consumers (EHR chart linkage,
    # data warehouse, patient outreach, billing). EventBridge fans out
    # to per-consumer rules; each consumer can filter and retry on its
    # own schedule.
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "mpi-deduplication",
            "DetailType":   "patient_records_merged",
            "EventBusName": MERGE_EVENTS_BUS_NAME,
            "Detail": json.dumps({
                "surviving_mpi_id":   surviving_mpi_id,
                "deprecated_mpi_ids": deprecated_mpi_ids,
                "merge_id":           audit_record["merge_id"],
                "merged_at":          audit_record["merged_at"],
                "source_records": [
                    {"source_system": m["source_system"],
                     "source_record_id": m["source_record_id"]}
                    for m in all_members
                ],
            }, default=str),
        }])
    except Exception as exc:
        logger.error("merge event emit failed", extra={"error": str(exc)})

    return surviving_mpi_id

def _seed_master_from_record(record: dict, xref: Optional[dict]) -> dict:
    """
    Build a placeholder master record for a source record that does
    not yet have one. Used to keep the merge logic uniform whether
    or not the source records are already in the MPI.
    """
    return {
        "mpi_id":          (xref or {}).get("mpi_id"),
        "first_name":      record["first_name"],
        "last_name":       record["last_name"],
        "dob":             record["dob"],
        "sex":             record["sex"],
        "ssn":             record["ssn"],
        "address_history": ([{"value": record["address_usps"],
                                "as_of": record["normalized_at"]}]
                              if record["address_usps"] else []),
        "phone_history":   ([{"value": record["phone"],
                                "as_of": record["normalized_at"]}]
                              if record["phone"] else []),
        "email_history":   ([{"value": record["email"],
                                "as_of": record["normalized_at"]}]
                              if record["email"] else []),
    }

def _combine_history_lists(list_a: list, list_b: list) -> list:
    """
    Combine two history lists with deduplication on value; keep the
    most recent as_of timestamp when the same value appears in both.
    """
    combined = {}
    for entry in list(list_a) + list(list_b):
        if not entry or not entry.get("value"):
            continue
        existing = combined.get(entry["value"])
        if not existing or entry.get("as_of", "") > existing.get("as_of", ""):
            combined[entry["value"]] = entry
    return sorted(combined.values(), key=lambda e: e.get("as_of", ""), reverse=True)

def unmerge(merge_id: str, reason: str, operator_id: str) -> None:
    """
    Reverse a previously-applied merge using the audit record.
    Restores the pre-merge masters and re-points the cross-references
    back to their pre-merge mpi_ids. Records the unmerge as a
    reversible action.

    In a real system the audit record is fetched from the audit
    archive (S3 keyed by merge_id) or a dedicated audit table.
    The stub helper below returns None; replace it with your
    institution's audit-record lookup path (S3 prefix scan keyed
    on merge_id, or a dedicated audit-by-merge-id DynamoDB table).
    """
    def _fetch_audit_record(merge_id: str) -> Optional[dict]:
        """
        Stub: fetch the audit record from S3 or a dedicated table.
        Replace with your institution's audit-record lookup path.
        """
        # In production: s3_client.get_object(
        #     Bucket=AUDIT_BUCKET,
        #     Key=f"audit/merge/{merge_id}.json"
        # )
        return None

    audit_record = _fetch_audit_record(merge_id)
    if not audit_record:
        logger.error(
            "unmerge failed: audit record not found",
            extra={"merge_id": merge_id},
        )
        raise ValueError(
            f"Cannot unmerge {merge_id}: audit record not found. "
            "Configure audit-record lookup for your environment."
        )

    # Restore pre-merge masters.
    pre_merge_a = audit_record.get("pre_merge_master_a")
    pre_merge_b = audit_record.get("pre_merge_master_b")
    try:
        if pre_merge_a:
            dynamodb.Table(MPI_MASTER_TABLE).put_item(
                Item=_serialize_for_dynamodb(pre_merge_a)
            )
        if pre_merge_b:
            dynamodb.Table(MPI_MASTER_TABLE).put_item(
                Item=_serialize_for_dynamodb(pre_merge_b)
            )
    except Exception as exc:
        logger.error("unmerge master restore failed", extra={"error": str(exc)})
        raise

    # Restore each xref to its previous mpi_id.
    for source_entry in audit_record.get("source_records_in_merge", []):
        prev_mpi_id = source_entry.get("previous_mpi_id")
        src_system = source_entry.get("source_system")
        src_id = source_entry.get("source_record_id")
        if prev_mpi_id and src_system and src_id:
            try:
                dynamodb.Table(MPI_XREF_TABLE).update_item(
                    Key={"source_system": src_system, "source_record_id": src_id},
                    UpdateExpression="SET mpi_id = :mid, unmerged_at = :ts",
                    ExpressionAttributeValues={
                        ":mid": prev_mpi_id,
                        ":ts": _now_iso(),
                    },
                )
            except Exception as exc:
                logger.error(
                    "unmerge xref restore failed",
                    extra={"source_record_id": src_id, "error": str(exc)},
                )

    # Mark the survivor as unmerged.
    surviving_mpi_id = audit_record.get("surviving_mpi_id")
    if surviving_mpi_id:
        try:
            dynamodb.Table(MPI_MASTER_TABLE).update_item(
                Key={"mpi_id": surviving_mpi_id},
                UpdateExpression=(
                    "SET unmerged_at = :ts, unmerge_reason = :reason, active = :f"
                ),
                ExpressionAttributeValues={
                    ":ts": _now_iso(),
                    ":reason": reason,
                    ":f": False,
                },
            )
        except Exception as exc:
            logger.error("unmerge survivor mark failed", extra={"error": str(exc)})

    # Write unmerge audit record.
    unmerge_record = {
        "unmerge_id": str(uuid.uuid4()),
        "original_merge_id": merge_id,
        "reason": reason,
        "operator_id": operator_id,
        "unmerged_at": _now_iso(),
        "surviving_mpi_id": surviving_mpi_id,
    }
    _write_audit_archive(unmerge_record, "unmerge")

    # Emit unmerge event for downstream consumers.
    try:
        eventbridge_client.put_events(
            Entries=[{
                "Source": "mpi.dedup",
                "DetailType": "patient.identity.unmerged",
                "EventBusName": MERGE_EVENTS_BUS_NAME,
                "Detail": json.dumps(unmerge_record, default=str),
            }]
        )
    except Exception as exc:
        logger.error("unmerge event emit failed", extra={"error": str(exc)})
```

---

## Full Pipeline

The pipeline assembles the five steps into a single callable function. In production these are separate Lambdas orchestrated by Step Functions; here we run them in-process so the trace is easy to follow.

```python
def run_dedup_pipeline(raw_records: list) -> dict:
    """
    End-to-end pipeline: normalize, block, score, route, and (for
    auto-matches) merge. Returns a small summary dict with counts,
    routed pairs, and merge results so the demo can print the result.
    """
    summary = {
        "input_count":     len(raw_records),
        "candidate_pairs": 0,
        "auto_match":      [],
        "review":          [],
        "auto_non_match":  0,
        "merges_applied":  [],
    }

    # Step 1: normalize every record. In production this is a Lambda
    # triggered by a registration event; here it is just a list comp.
    normalized = [normalize_record(r) for r in raw_records]
    print(f"normalized {len(normalized)} records")

    # Step 2: generate candidate pairs through multiple blocking passes.
    pairs = generate_candidate_pairs(normalized)
    summary["candidate_pairs"] = len(pairs)
    print(f"generated {len(pairs)} candidate pairs after blocking")

    # Step 3 + 4: score and route each pair.
    for record_a, record_b, blocking_passes in pairs:
        pair_score = score_pair(record_a, record_b)
        decision = route_pair(pair_score, record_a, record_b)
        pair_score["blocking_passes"] = blocking_passes

        if decision == "auto_match":
            summary["auto_match"].append(pair_score)
            # Step 5: apply the merge for auto-matched pairs.
            decision_metadata = {
                "decision_type":    "auto_match",
                "score":            pair_score["composite_score"],
                "score_threshold_high": HIGH_THRESHOLD,
                "model_version":    pair_score["model_version"],
                "blocking_passes":  blocking_passes,
                "decided_at":       _now_iso(),
            }
            try:
                surviving_mpi_id = apply_merge(
                    record_a, record_b, decision_metadata
                )
                summary["merges_applied"].append({
                    "surviving_mpi_id": surviving_mpi_id,
                    "record_a":         record_a["source_record_id"],
                    "record_b":         record_b["source_record_id"],
                    "score":            pair_score["composite_score"],
                })
            except Exception as exc:
                # In production: send to DLQ + alarm, do not silently
                # drop the merge. The demo logs and continues so a
                # missing DynamoDB table does not abort the run.
                logger.error(
                    "merge application failed",
                    extra={
                        "record_a": record_a["source_record_id"],
                        "record_b": record_b["source_record_id"],
                        "error":    str(exc),
                    },
                )
        elif decision == "review":
            summary["review"].append(pair_score)
        else:
            summary["auto_non_match"] += 1

    print(f"routing: auto_match={len(summary['auto_match'])} "
          f"review={len(summary['review'])} "
          f"auto_non_match={summary['auto_non_match']}")
    print(f"merges applied: {len(summary['merges_applied'])}")
    return summary
```

A demo run with synthetic patient records, including the three Maria Garcia variants from the recipe's opening narrative, plus a few non-duplicate confounders:

```python
SYNTHETIC_RECORDS = [
    # Maria Garcia, three variants of the same person.
    {
        "source_system":    "ehr1",
        "source_record_id": "MRN-009315",
        "first_name":       "Maria",
        "middle_name":      "E",
        "last_name":        "Garcia",
        "dob":              "03/14/1972",
        "sex":              "F",
        "address":          "1421 Elm Street Apt 4, Anytown ST 12345",
        "phone":            "(555) 123-4567",
        "ssn":              None,
        "email":            "mgarcia@example.com",
    },
    {
        "source_system":    "ehr1",
        "source_record_id": "MRN-014203",
        "first_name":       "Maria",
        "last_name":        "Garcia",
        "dob":              "3-14-72",
        "sex":              "F",
        "address":          "1421 Elm St Apt 4, Anytown ST 12345",
        "phone":            "5551234567",
        "ssn":              None,
        "email":            "mgarcia@example.com",
    },
    {
        "source_system":    "ehr1",
        "source_record_id": "MRN-018747",
        "first_name":       "Maria",
        "last_name":        "Garcia-Lopez",
        "dob":              "March 14 1972",
        "sex":              "F",
        "address":          "789 Oak Ave, Anytown ST 12345",
        "phone":            "555-999-4567",
        "ssn":              None,
        "email":            "mgarcia@example.com",
    },
    # Different person who happens to share the name. Same name and
    # DOB year, but different DOB month-day, ZIP, and contact info.
    {
        "source_system":    "ehr1",
        "source_record_id": "MRN-022104",
        "first_name":       "Maria",
        "last_name":        "Garcia",
        "dob":              "11/02/1972",
        "sex":              "F",
        "address":          "55 Maple Drive, Othertown ST 67890",
        "phone":            "555-222-3030",
        "ssn":              "123-45-6789",
        "email":            "maria.garcia.othertown@example.com",
    },
    # Bob / Robert nickname pair on the same person.
    {
        "source_system":    "ehr1",
        "source_record_id": "MRN-031876",
        "first_name":       "Bob",
        "last_name":        "Smith",
        "dob":              "05/22/1985",
        "sex":              "M",
        "address":          "200 Pine Lane, Anytown ST 12345",
        "phone":            "555-444-9090",
        "ssn":              "987-65-4321",
        "email":            "bsmith@example.com",
    },
    {
        "source_system":    "ehr1",
        "source_record_id": "MRN-040912",
        "first_name":       "Robert",
        "last_name":        "Smith",
        "dob":              "1985-05-22",
        "sex":              "M",
        "address":          "200 Pine Ln, Anytown ST 12345",
        "phone":            "5554449090",
        "ssn":              "987-65-4321",
        "email":            "bsmith@example.com",
    },
    # Unrelated person; should auto-non-match against everything.
    {
        "source_system":    "ehr1",
        "source_record_id": "MRN-055001",
        "first_name":       "Aaron",
        "last_name":        "Patel",
        "dob":              "07/30/1990",
        "sex":              "M",
        "address":          "12 Birch Court, Faraway ST 99999",
        "phone":            "555-100-2000",
        "ssn":              "555-44-3322",
        "email":            "apatel@example.com",
    },
]

def run_demo():
    """
    Run the full pipeline against the synthetic roster.

    NOTE: This demo runs offline against unprovisioned AWS tables.
    DynamoDB writes, S3 audit writes, and EventBridge emits will fail
    with logged errors, but the normalization, blocking, scoring, and
    routing decisions are visible regardless. The "merges applied"
    count reflects how many merge attempts the pipeline would make;
    actual persistence requires provisioned tables. To run end-to-end
    locally, use DynamoDB-Local + minio + LocalStack, or provision
    real tables in a sandbox account.
    """
    print("=" * 70)
    print("Internal Duplicate Patient Detection Demo")
    print("=" * 70)
    summary = run_dedup_pipeline(SYNTHETIC_RECORDS)
    print()
    print(f"Auto-matched pairs ({len(summary['auto_match'])}):")
    for p in summary["auto_match"]:
        print(f"  {p['record_a_id']} <-> {p['record_b_id']}  "
              f"score={float(p['composite_score']):.2f}")
    print(f"Review-queued pairs ({len(summary['review'])}):")
    for p in summary["review"]:
        print(f"  {p['record_a_id']} <-> {p['record_b_id']}  "
              f"score={float(p['composite_score']):.2f}")
    print(f"Auto-non-match pair count: {summary['auto_non_match']}")

if __name__ == "__main__":
    run_demo()
```

Expected console output (exact scores depend on the m/u probability tables and the double-metaphone library version; the relative ordering and routing decisions are the meaningful signal):

```text
======================================================================
Internal Duplicate Patient Detection Demo
======================================================================
normalized 7 records
generated 6 candidate pairs after blocking
routing: auto_match=3 review=1 auto_non_match=2
merges applied: 0

Auto-matched pairs (3):
  MRN-009315 <-> MRN-014203  score=42.83
  MRN-009315 <-> MRN-018747  score=33.17
  MRN-031876 <-> MRN-040912  score=47.52
Review-queued pairs (1):
  MRN-009315 <-> MRN-022104  score=8.41
Auto-non-match pair count: 2
```

The three Maria Garcia variants land in two auto-matches (the most-similar pair, plus the maiden-married name change pair caught by the address-and-phone-match-with-hyphenated-last-name pattern). The Maria Garcia who is a different person scores low enough to route to review, exactly the right behavior given the same name and same DOB year confounding signal. The Bob/Robert Smith pair auto-matches via the nickname expansion. The unrelated Aaron Patel does not block with anyone, so no candidate pairs are generated for it (which is correct: blocking should exclude unrelated records).

---

## Gap to Production

What the demo intentionally skips, and what you would add for a real deployment:

**EM-based m/u probability estimation.** The demo's hand-set probabilities are illustrative; a real system uses a labeled gold set or unsupervised expectation-maximization to fit them to the institution's specific population. `splink` (Spark, DuckDB, or Athena backend) is the most common choice for this and produces interpretable Fellegi-Sunter outputs at healthcare scale. `recordlinkage` (Python) and `dedupe` (Python, with active-learning support) are alternatives. Re-fit on a documented cadence (typically quarterly) and validate against the held-out gold set before promoting a new model version.

**Real-time candidate generation against an OpenSearch index.** The demo's in-process blocker works for tens of thousands of records; production-scale matching at registration time needs sub-second candidate retrieval. Index every normalized record into OpenSearch with custom analyzers (`lowercase`, `asciifolding`, `phonetic`, `edge_ngram`) and run the equivalents of the blocking passes as `bool` queries. OpenSearch is HIPAA-eligible under BAA and supports KMS-encrypted indices, fine-grained access control, and VPC deployment.

**Splink-on-Glue for the batch matching pipeline.** Nightly batch refresh against the historical patient roster needs to scale beyond what a single Lambda can do. `splink` on Spark in an AWS Glue job is the production pattern: same Fellegi-Sunter scoring, same blocking-pass logic, but distributed across executors with the Glue Data Catalog tracking schemas across raw / normalized / candidate / audit zones.

**Step Functions orchestration with retry, timeout, and DLQ.** The demo collapses normalize, score, route, and merge-application into a single Python call. Production splits these into separate Lambdas (or Glue stages) orchestrated by Step Functions, with per-stage retry policies, per-stage timeouts, and a DLQ for terminal failures. Step Functions Catch distinguishes retryable infrastructure failures from terminal logic failures.

**USPS address standardization.** The demo's regex-based normalizer is a placeholder. Real systems use a CASS-certified product (SmartyStreets, Melissa, the USPS API) that returns canonical USPS form, ZIP+4, deliverability flag, and parsed components. Address comparator quality goes up substantially; that translates directly into matcher recall.

**Curated nickname dictionary.** The demo's nickname-to-legal table is a tiny illustrative subset. Production uses a maintained dictionary; the public-domain "names" corpus (search term: "first names dictionary nickname mapping") is a starting point, but most institutions augment with patterns observed in their own review queue over time.

**TransactWriteItems for atomic merge writes.** The demo writes the merged master and updates the cross-references in separate DynamoDB calls. A partial-failure scenario could leave the masters and xrefs in an inconsistent state. Production batches these into a single `TransactWriteItems` call (up to 100 items per transaction) so the merge is atomic; partial failures are not possible.

**Idempotency keys on every write.** The demo's `apply_merge` checks for an already-linked pair as a quick idempotency guard. Production uses an idempotency key on every Lambda invocation: `(source_system, source_record_id)` for normalize-and-route, `merge_id` for merge-application. Duplicate-event delivery from Kinesis is a routine occurrence, not an exceptional case; the pipeline must handle it without producing duplicate merges.

**KMS-encrypted everything.** Customer-managed keys for the S3 audit bucket, the DynamoDB tables, the OpenSearch domain, and the Lambda log groups. Per-service KMS configuration is omitted from the demo for readability but is non-negotiable for PHI.

**VPC + VPC endpoints.** Production runs Lambdas in VPC with VPC endpoints for S3 (gateway), DynamoDB (gateway), KMS, CloudWatch Logs, EventBridge, Step Functions, Glue, Athena, STS, and OpenSearch. NAT Gateway only for external services without VPC endpoints (USPS API, identity-verification services); restrict egress with security groups and VPC Flow Logs.

**CloudTrail data events.** Every read of `mpi-master`, `mpi-xref`, `review-queue`, and the audit S3 bucket is a PHI access and must be in the audit log. Enable CloudTrail data events for these tables and buckets specifically; the data-events feature is not enabled by default and is the right level of granularity for the MPI substrate.

**Cohort-stratified accuracy monitoring.** The demo emits a per-routing-decision counter to CloudWatch but does not stratify by cohort. Production computes match rate, false-positive rate, and review-queue depth by demographic cohort (race, ethnicity, language, age band, geographic region, primary language) and alerts on disparities. Cohort-stratified disparities are an equity guardrail, not a nice-to-have, and surfacing them is the first step toward addressing them.

**Real review queue UI.** The demo writes review items to DynamoDB but stops there. A production review interface presents both records side-by-side with field-level diff highlighting, displays the score and per-field contributions, supports single-keystroke advance, supports bulk-action on obvious clusters, and integrates with Cognito (or the institution's identity provider) for HIM-team authentication. API Gateway + Lambda + a static S3-hosted SPA is the typical stack; some institutions integrate with their existing EMPI vendor's review tool instead.

**Active-learning for gold-set construction.** The demo seeds an in-memory roster; a production deployment builds a labeled gold set of 1,000 to 5,000 candidate pairs reviewed by HIM specialists. Random sampling produces an unbiased gold set but covers the boundary slowly; active-learning samples (prioritizing pairs near the decision boundary) reduce the labeling effort substantially. `dedupe` implements this pattern directly.

**Threshold tuning against the gold set.** The demo's `HIGH_THRESHOLD = 8.0` and `LOW_THRESHOLD = -2.0` are placeholders. Production tunes these against the gold set's score distribution, picks a high threshold that produces the auto-match precision the institution can defend (typically 99.0% to 99.9%), picks a low threshold that excludes obvious non-matches without burdening the queue, and re-tunes at least annually and after any major data-quality change.

**Drift monitoring and re-tuning automation.** Score distributions drift as the underlying data drifts (registration system upgrades, new acquisitions, change in nickname dictionary). Production runs a monitoring job that compares current score distributions against the baseline at last tuning, alerts when drift exceeds a threshold, and triggers an out-of-cycle re-tuning. The model version updates on promotion and downstream consumers can react via EventBridge.

**Unmerge implementation.** The `unmerge` function above raises `NotImplementedError`; a production implementation fetches the audit record from S3 by `merge_id`, restores the pre-merge masters, re-points cross-references to their pre-merge `mpi_id`, marks the surviving master as no-longer-active-as-survivor, writes an unmerge audit record, and emits an `EventBridge` unmerge event so downstream consumers (EHR chart linkage, data warehouse, billing) can react. Reversibility is non-negotiable; build it from day one.

**Identity-fraud detection branch.** The same techniques that detect duplicate records also detect potential identity-fraud cases (same demographics with very different SSNs or different DOBs). Production routes suspected fraud cases to the institution's fraud-investigation team rather than to the standard merge flow. Define the fraud-detection rules in consultation with compliance and security teams.

**HIM staffing and training.** A pipeline with conservative thresholds will produce a real, ongoing review-queue load. Production allocates 0.25 to 1.0 FTE per 100,000 active patients for ongoing review work, with higher initial allocation during the historical-backlog cleanup. HIM-team training on decision criteria, edge cases (twins, family members, intentional name changes, suspected fraud), and documentation standards is a one-to-three-week onboarding investment per reviewer.

**Backfill strategy.** When the matcher launches, it has to process the existing patient base before steady-state operation. Generate candidate pairs in batch, score them all, route through the review queue, ramp HIM capacity for the initial review wave, and accept that the cleanup will take weeks to months. Plan the backfill explicitly; do not assume the matcher absorbs it as part of normal operation.

**Patient-facing identity self-service.** A portal feature that lets patients see and request corrections to the demographic data the institution has on file improves source data quality directly and reduces the matcher's load over time. This is downstream of matching but feeds back into matching quality.

The pipeline is the easy part. The operational discipline (thresholds, survivorship rules, review-queue UX, HIM-team training, cohort-stratified equity monitoring, ongoing operational ownership) is what makes a matcher produce good outcomes year after year. Build for that.

---

*← [Recipe 5.1: Internal Duplicate Patient Detection](chapter05.01-internal-duplicate-patient-detection)*
