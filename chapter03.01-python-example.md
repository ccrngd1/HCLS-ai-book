# Recipe 3.1: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 3.1. It shows one way you could translate the duplicate-claim-detection pattern into working Python using Amazon DynamoDB, Amazon SQS, Amazon EventBridge, and Amazon S3. It is not production-ready. There is no real 837 EDI parser here (that's a multi-week project on its own and belongs in a maintained library, not in a teaching example), no SageMaker-hosted learned scorer (the rule-based scorer below is the starting point the main recipe recommends; you graduate to SageMaker once labels accumulate), no OpenSearch fuzzy search integration, no retrospective recovery workflow, no CPT crosswalk or provider-hierarchy lookups, and no examiner UI. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd wire into a payer's adjudication pipeline on Monday morning.
>
> The code maps to the five core pseudocode steps from the main recipe: parse and normalize the claim, find candidates via exact-hash and blocking lookups, score each candidate pair with per-field fuzzy similarity, route the claim based on thresholds, and close the feedback loop when an examiner verdict comes in. Everything else (retraining, monitoring, drift detection, provider communication) is outside the scope of the example but covered in the Gap to Production section.

---

## Setup

You'll need the AWS SDK for Python:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:PutItem`, `dynamodb:Query`, `dynamodb:GetItem` on the `claim-history` and `claim-labels` tables (and on the `content_hash_index` GSI on `claim-history`)
- `s3:GetObject` on the raw 837 bucket, `s3:PutObject` on the normalized-claims and labels buckets
- `sqs:SendMessage` on the review queue ARN
- `events:PutEvents` on the EventBridge bus (for publishing examiner-verdict events from the workstation side)
- `cloudwatch:PutMetricData` for the operational metrics

Scope each Lambda's IAM role to the specific resource ARNs it touches. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. In production, each of the three Lambdas (parser, detector, label-writer) gets its own role with the minimum permissions for its job.

A few things worth knowing upfront:

- **No real 837 parsing in this example.** Parsing EDI transactions is a substantial engineering task and should be done with a maintained library (commercial or well-supported open-source). This example starts from a claim record that's already been parsed into a Python dictionary. In production, a Lambda triggered by an S3 `ObjectCreated` event would call the EDI library and feed the parsed claims into the normalization step.
- **DynamoDB table schemas.** The `claim-history` table uses `blocking_hash` as the partition key and `claim_id` as the sort key. A global secondary index on `content_hash` (with `claim_id` as the sort key) supports the exact-duplicate lookup. The `claim-labels` table uses a composite `pair_key` (`incoming_claim_id#matched_claim_id`) as the partition key. You create these once, up front; this file does not do that for you.
- **Money must be Decimal.** DynamoDB rejects Python `float` for any numeric value (it loses precision, which in a claims context is a compliance disaster). Every billed-amount value passes through `Decimal` on its way in and on its way out. This is a common gotcha that bites every DynamoDB tutorial reader at least once.
- **All example claim data is synthetic.** Member IDs, NPIs, CPT codes in the sample output are illustrative and do not refer to real patients, providers, or services.

---

## Configuration and Constants

Everything that's configuration rather than logic lives here. Weights, thresholds, the date-window for blocking, and the resource names are the knobs you'll change most often between environments.

```python
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import Optional

import boto3
from botocore.config import Config
from boto3.dynamodb.conditions import Key

# Structured logging. In production, ship JSON-formatted records to CloudWatch
# Logs Insights. Claim records are PHI-adjacent (member ID + NPI + date of
# service is a re-identification risk even without a name), so we log
# structural metadata only. Never log full claim bodies, member IDs, diagnosis
# codes, or similarity score components in regular application logs.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry mode handles DynamoDB and SQS throttling with exponential
# backoff and jitter. Duplicate detection load is naturally bursty (claims
# arrive in batches from clearinghouses), and adaptive mode keeps burst
# windows from cascading into retry storms.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers
# so each invocation doesn't pay the connection-establishment cost.
REGION = "us-east-1"
dynamodb = boto3.resource("dynamodb", region_name=REGION, config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", region_name=REGION, config=BOTO3_RETRY_CONFIG)
sqs_client = boto3.client("sqs", region_name=REGION, config=BOTO3_RETRY_CONFIG)
cloudwatch = boto3.client("cloudwatch", region_name=REGION, config=BOTO3_RETRY_CONFIG)
eventbridge = boto3.client("events", region_name=REGION, config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill these in with your actual resource names.
CLAIM_HISTORY_TABLE = "claim-history"
CLAIM_LABELS_TABLE = "claim-labels"
CONTENT_HASH_INDEX = "content_hash_index"   # GSI on claim-history table
NORMALIZED_CLAIMS_BUCKET = "my-normalized-claims"
LABELS_BUCKET = "my-claim-labels"
REVIEW_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/claim-review-queue"
EVENT_BUS_NAME = "claim-events"

# Deploy-time guardrail: catch unreplaced example values.
assert "123456789012" not in REVIEW_QUEUE_URL, \
    "REVIEW_QUEUE_URL still uses the example AWS account ID. Replace before deploying."

# --- Scorer Version ---
# Every routing decision and every captured label records the scorer version
# that produced the score. This is how retraining picks its training window
# and how monitoring attributes regressions to a specific model.
SCORER_VERSION = "rule-v1.0"

# --- Blocking Configuration ---
# How many days on either side of the incoming claim's date of service count
# as "same block" for fuzzy comparison. 14 is a reasonable default for
# professional claims. Widen for inpatient (same admission may span weeks);
# narrow for lab (same-day only).
MAX_DOS_WINDOW_DAYS = 14

# --- Field Weights for the Rule-Based Scorer ---
# Must sum to 1.0. These are reasonable starting values from the main recipe.
# Tune against your own label distribution once you have one.
FIELD_WEIGHTS = {
    "patient_id":        0.15,
    "billing_npi":       0.10,
    "rendering_npi":     0.10,
    "date_of_service":   0.15,
    "cpt_code":          0.20,
    "modifiers":         0.10,
    "billed_amount":     0.10,
    "diagnosis_codes":   0.05,
    "place_of_service":  0.05,
}

# --- Routing Thresholds ---
# HIGH_THRESHOLD: score at or above this auto-suspends as a duplicate.
# LOW_THRESHOLD: score at or below this auto-accepts (passes through).
# Between the two: human review.
#
# These are placeholders. In production, tune against your ROC curve and
# target review-queue capacity. Make them config-driven so you can adjust
# without a code deploy. A 5-point move in either direction changes the
# review queue size substantially.
HIGH_THRESHOLD = Decimal("0.90")
LOW_THRESHOLD = Decimal("0.55")

# --- CPT Code Family Lookup ---
# A tiny, illustrative code-family table. A real system plugs in a much
# larger table (or a CPT crosswalk service) covering all CPT/HCPCS codes
# you see in production. The family relationship is: different levels of
# the same E/M code set are in the same family; the family match is a
# weaker signal than an exact match but stronger than nothing.
CPT_FAMILIES = {
    # Office or outpatient visit, established patient, levels 2-5.
    "99212": "em_estab_outpatient",
    "99213": "em_estab_outpatient",
    "99214": "em_estab_outpatient",
    "99215": "em_estab_outpatient",
    # Office or outpatient visit, new patient, levels 2-5.
    "99202": "em_new_outpatient",
    "99203": "em_new_outpatient",
    "99204": "em_new_outpatient",
    "99205": "em_new_outpatient",
    # Complete blood count.
    "85025": "cbc",
    "85027": "cbc",
    # Add the codes you care about here. Source from your payer's fee schedule.
}

# --- Deprecated-Code Crosswalk ---
# If a procedure code was deprecated and replaced, the old code and new code
# should be treated as equivalent for duplicate-matching purposes.
# The table below is illustrative; verify current crosswalks against CMS
# or your claims processor's authoritative source before relying on any
# specific entry.
CPT_CROSSWALK = {
    # TODO: populate with verified crosswalks from your claims processor.
    # Example shape only: {"OLD_CODE": "CURRENT_CODE"}.
}

def _to_decimal(value) -> Decimal:
    """
    Coerce numeric input into Decimal for DynamoDB and for downstream math.

    DynamoDB rejects float. Always pass Decimal. Quantizing to four decimal
    places is defensive: some billed amounts carry four-place precision for
    fee-schedule calculations, and rounding earlier would lose information.
    """
    if isinstance(value, Decimal):
        return value
    # str() round-trip preserves whatever precision the input had.
    return Decimal(str(value))
```

---

## Step 1: Parse and Normalize the Claim

*The pseudocode calls this `parse_and_normalize(raw_837_key)`. In production, this Lambda is triggered by an S3 `ObjectCreated` event on the raw 837 bucket, reads the EDI transaction with a maintained parser library, and produces one normalized claim record per claim in the transaction. Here, we skip the EDI parsing and start from a claim dictionary that already has the expected fields.*

The important work in this step is canonicalization and hashing. Canonicalization removes format noise (date styles, ID padding, case differences) that would otherwise cause same-claim comparisons to look like different-claim comparisons. The content hash is what makes exact-duplicate detection free: any two claims with the same content hash are, by definition, identical in their defining fields. The blocking hash is coarser, grouping candidates into buckets small enough for per-pair fuzzy scoring.

```python
def normalize_claim(raw_claim: dict) -> dict:
    """
    Canonicalize a parsed claim dictionary and compute the two hashes used
    downstream: content_hash for exact-duplicate detection and blocking_hash
    for the fuzzy-comparison candidate lookup.

    Expected input keys:
      claim_id, patient_id, subscriber_id, billing_npi, rendering_npi,
      date_of_service, place_of_service, cpt_code, modifiers,
      diagnosis_codes, billed_amount, submission_source
    """
    # Canonicalize each field. The exact rules here matter more than they
    # look like they should: a single unnormalized source field can break
    # the blocking step and cause duplicates to be missed.
    normalized = {
        "claim_id":         (raw_claim["claim_id"] or "").strip().upper(),
        # Member IDs vary wildly across payers. Leading-zero pad to a common
        # width, strip whitespace, and uppercase. If your patient ID format
        # is different from 10 digits, adjust.
        "patient_id":       (raw_claim["patient_id"] or "").strip().zfill(10),
        "subscriber_id":    (raw_claim.get("subscriber_id") or "").strip().zfill(10),
        # NPIs are 10 digits. Strip non-digit characters (hyphens, spaces)
        # and reject anything that doesn't validate. A real system would
        # verify the NPI check digit here.
        "billing_npi":      re.sub(r"\D", "", raw_claim.get("billing_npi") or ""),
        "rendering_npi":    re.sub(r"\D", "", raw_claim.get("rendering_npi") or ""),
        # Dates are always ISO 8601 (YYYY-MM-DD) inside the pipeline. The
        # input may be any of the common formats; parse and reformat.
        "date_of_service":  _normalize_date(raw_claim["date_of_service"]),
        # Place of service is two digits. Pad if needed.
        "place_of_service": (raw_claim.get("place_of_service") or "").zfill(2),
        # CPT/HCPCS codes are uppercase, whitespace-stripped.
        "cpt_code":         (raw_claim.get("cpt_code") or "").strip().upper(),
        # Modifier and diagnosis lists are sorted so the hash is stable
        # regardless of the order they appeared in the source transaction.
        "modifiers":        sorted(_strip_empty(raw_claim.get("modifiers") or [])),
        "diagnosis_codes":  sorted(_strip_empty(raw_claim.get("diagnosis_codes") or [])),
        # Billed amount must be Decimal, not float (DynamoDB and money
        # precision both demand it).
        "billed_amount":    _to_decimal(raw_claim["billed_amount"]),
        "submission_source": (raw_claim.get("submission_source") or "").strip(),
        # Ingestion timestamp, useful for label-writer and retraining windows.
        "received_at":      datetime.now(timezone.utc).isoformat(),
    }

    # Content hash: the fields that define "same claim" in the strictest
    # sense. Two claims with the same content_hash are exact duplicates.
    # Sort the modifier/diagnosis lists before hashing so the hash is
    # stable across input orderings.
    content_hash = _sha256_of_parts([
        normalized["patient_id"],
        normalized["billing_npi"],
        normalized["date_of_service"],
        normalized["cpt_code"],
        ",".join(normalized["modifiers"]),
        str(normalized["billed_amount"]),
    ])

    # Blocking hash: coarser than the content hash. The goal is to group
    # claims into small buckets such that any two claims in the same bucket
    # are plausibly duplicates. The date is rounded to YYYY-MM so nearby-
    # date claims land in the same block; date proximity is scored later.
    # The billing NPI is truncated to its first four digits so claims from
    # the same billing organization land together even if the individual
    # rendering NPI shifts between submissions.
    blocking_hash = _sha256_of_parts([
        normalized["patient_id"],
        normalized["billing_npi"][:4],
        normalized["date_of_service"][:7],  # YYYY-MM
    ])

    normalized["content_hash"] = content_hash
    normalized["blocking_hash"] = blocking_hash

    return normalized

def _normalize_date(value) -> str:
    """
    Accept a datetime, date, or one of several common string formats and
    return the canonical ISO 8601 date (YYYY-MM-DD).

    Two claims that should compare as same-day will only do so if their
    dates are canonicalized. This is one of the commonest sources of
    silent blocking failures.
    """
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    # Try the common formats we see from clearinghouses. Extend this list
    # as you encounter new ones in production.
    candidate_formats = [
        "%Y-%m-%d",     # 2026-03-15
        "%Y%m%d",       # 20260315
        "%m/%d/%Y",     # 03/15/2026
        "%m-%d-%Y",     # 03-15-2026
        "%d/%m/%Y",     # 15/03/2026 (rare but seen)
    ]
    for fmt in candidate_formats:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date format: {text!r}")

def _strip_empty(values: list) -> list:
    """Filter out empty/None entries from a list of codes."""
    return [v.strip().upper() for v in values if v and str(v).strip()]

def _sha256_of_parts(parts: list) -> str:
    """
    Hash a pipe-joined concatenation of the parts. The pipe is a separator
    that's unlikely to appear in any of the field values we hash.
    """
    joined = "|".join(parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()

def persist_normalized_claim(normalized: dict) -> None:
    """
    Write the normalized claim to DynamoDB (hot store for blocking lookups)
    and to S3 (archive used by the Athena-based retraining path).

    In production, these writes happen in parallel and are wrapped in
    retries. We keep it simple here.
    """
    # DynamoDB write. Partition key is blocking_hash; sort key is claim_id.
    # The content_hash attribute is the key for the GSI used by the exact-
    # duplicate lookup in Step 2.
    table = dynamodb.Table(CLAIM_HISTORY_TABLE)
    # DynamoDB doesn't accept Python native sets with mixed types; keep
    # lists as lists of strings.
    table.put_item(Item={
        "blocking_hash":    normalized["blocking_hash"],
        "claim_id":         normalized["claim_id"],
        "content_hash":     normalized["content_hash"],
        "patient_id":       normalized["patient_id"],
        "subscriber_id":    normalized["subscriber_id"],
        "billing_npi":      normalized["billing_npi"],
        "rendering_npi":    normalized["rendering_npi"],
        "date_of_service":  normalized["date_of_service"],
        "place_of_service": normalized["place_of_service"],
        "cpt_code":         normalized["cpt_code"],
        "modifiers":        normalized["modifiers"],
        "diagnosis_codes":  normalized["diagnosis_codes"],
        "billed_amount":    normalized["billed_amount"],
        "submission_source": normalized["submission_source"],
        "received_at":      normalized["received_at"],
    })

    # S3 archive. Partition by received-at date for efficient Athena
    # queries later. Use JSON here for clarity; in production you'd write
    # Parquet (better compression, columnar access for Athena).
    received_dt = datetime.fromisoformat(normalized["received_at"])
    archive_key = (
        f"normalized-claims/year={received_dt.year:04d}/"
        f"month={received_dt.month:02d}/day={received_dt.day:02d}/"
        f"{normalized['claim_id']}.json"
    )
    s3_client.put_object(
        Bucket=NORMALIZED_CLAIMS_BUCKET,
        Key=archive_key,
        Body=json.dumps(normalized, default=str).encode("utf-8"),
        ContentType="application/json",
        # PHI is in this payload; require customer-managed KMS encryption.
        # Enforce it at the bucket policy level as well; don't rely on the
        # per-PutObject flag alone.
        ServerSideEncryption="aws:kms",
    )

    logger.info(
        "persisted_claim",
        extra={
            "claim_id":      normalized["claim_id"],
            "blocking_hash": normalized["blocking_hash"][:12],  # prefix only
        },
    )
```

---

## Step 2: Find Candidate Duplicates

*The pseudocode calls this `find_candidates(incoming_claim)`. It runs two lookups: first the exact-duplicate check on the GSI keyed by `content_hash`, and then, if no exact match is found, the blocking lookup that returns all claims in the same block for fuzzy comparison.*

The structure of this step matters more than it looks like it should. The exact check is a cheap O(1) lookup that catches the easy cases for free; skipping it would send obviously-duplicate claims through the expensive fuzzy scoring path for no reason. The blocking lookup's output shape (typically 0 to a few dozen candidates) is what keeps the overall pipeline tractable at scale.

```python
def find_candidates(incoming: dict) -> dict:
    """
    Return a dict describing the candidate set for this incoming claim.

    Output shape:
      { "match_type": "exact", "candidates": [...] }    # exact duplicate found
      { "match_type": "fuzzy", "candidates": [...] }    # fuzzy candidates from blocking
      { "match_type": "none",  "candidates": []  }      # block was empty
    """
    table = dynamodb.Table(CLAIM_HISTORY_TABLE)

    # --- Exact-duplicate check ---
    # Query the GSI keyed by content_hash. A match here means the incoming
    # claim is identical to an existing claim in every field that defines
    # "same claim" for strict-duplicate purposes. This is the cheap win.
    exact_response = table.query(
        IndexName=CONTENT_HASH_INDEX,
        KeyConditionExpression=Key("content_hash").eq(incoming["content_hash"]),
        # Defensive limit: a healthy pipeline never has a large number of
        # exact duplicates per content_hash, but the limit protects against
        # runaway cases.
        Limit=25,
    )
    exact_matches = [
        c for c in exact_response.get("Items", [])
        if c["claim_id"] != incoming["claim_id"]
    ]
    if exact_matches:
        return {"match_type": "exact", "candidates": exact_matches}

    # --- Blocking lookup ---
    # Query by the blocking_hash partition key. DynamoDB returns every
    # claim in this block. In production, pagination is required if
    # blocks grow large; we keep it simple here.
    blocking_response = table.query(
        KeyConditionExpression=Key("blocking_hash").eq(incoming["blocking_hash"]),
    )
    block_items = [
        c for c in blocking_response.get("Items", [])
        if c["claim_id"] != incoming["claim_id"]
    ]

    # Filter by date-of-service window. The blocking hash uses YYYY-MM,
    # which means a claim on the 1st and a claim on the 28th fall in the
    # same block. We narrow to the configured DOS window here so the
    # scorer only sees plausibly-same-service pairs.
    incoming_dos = datetime.fromisoformat(incoming["date_of_service"]).date()
    candidates = []
    for item in block_items:
        candidate_dos = datetime.fromisoformat(item["date_of_service"]).date()
        if abs((candidate_dos - incoming_dos).days) <= MAX_DOS_WINDOW_DAYS:
            candidates.append(item)

    if not candidates:
        return {"match_type": "none", "candidates": []}

    return {"match_type": "fuzzy", "candidates": candidates}
```

---

## Step 3: Score Each Candidate Pair

*The pseudocode calls this `score_pair(incoming, candidate)`. Per-field fuzzy similarity functions generate a score in [0, 1] for each field. The total score is the weighted sum of per-field similarities.*

The field-specific comparison functions are where the real engineering thought lives. The point is not to use a single "fuzzy match" library for everything; it's to choose a comparison that matches what each field represents. A one-character typo in a patient ID is a strong duplicate signal; a one-character difference between CPT codes 99213 and 99214 is not (those are genuinely different services). The per-field functions below encode those distinctions.

```python
def score_pair(incoming: dict, candidate: dict) -> dict:
    """
    Compute the per-field similarities and the total weighted score for
    an (incoming, candidate) claim pair. Returns both the total and the
    per-field components; the components drive examiner-facing explanations
    in the review queue.
    """
    components = {}
    total = Decimal("0.0")

    for field_name, weight in FIELD_WEIGHTS.items():
        sim = _field_similarity(field_name, incoming.get(field_name), candidate.get(field_name))
        components[field_name] = sim
        total += _to_decimal(weight) * sim

    # Cap at 1.0 defensively against floating-point wobble (unlikely with
    # Decimal, but cheap insurance).
    if total > Decimal("1.0"):
        total = Decimal("1.0")

    return {
        "score":      total.quantize(Decimal("0.0001")),
        "components": {k: v.quantize(Decimal("0.0001")) for k, v in components.items()},
    }

def _field_similarity(field_name: str, a, b) -> Decimal:
    """
    Per-field similarity. The function picks a comparison appropriate to
    what the field represents. Returns a Decimal in [0, 1].

    For fields the scorer doesn't know about, return 0.0 rather than crash;
    the downstream total will simply not benefit from that field, which
    is a safer failure mode than dropping the whole claim.
    """
    if a is None or b is None:
        return Decimal("0.0")

    if field_name in ("patient_id", "billing_npi", "rendering_npi"):
        # System-generated identifiers: tight edit distance with a high bar.
        # An exact match is the strongest signal; a one-character difference
        # on a long ID is suggestive (data entry typos happen); larger
        # differences are treated as "different entity."
        dist = _levenshtein(str(a), str(b))
        if dist == 0:
            return Decimal("1.0")
        if dist == 1 and len(str(a)) >= 8 and len(str(b)) >= 8:
            return Decimal("0.85")
        return Decimal("0.0")

    if field_name == "date_of_service":
        # Day-level proximity. Same day: full signal. Next day: still strong
        # (a clinical encounter can legitimately straddle midnight). Up to
        # a week: weaker. Further than that: the blocking filter should
        # have dropped it, but we return a small value defensively.
        days = abs((datetime.fromisoformat(str(a)).date() - datetime.fromisoformat(str(b)).date()).days)
        if days == 0:
            return Decimal("1.0")
        if days <= 1:
            return Decimal("0.9")
        if days <= 7:
            return Decimal("0.6")
        return Decimal("0.0")

    if field_name == "cpt_code":
        # CPT comparison uses domain knowledge, not string distance.
        # Identical codes: full signal. Same code family (different levels
        # of the same E/M visit, for example): partial signal. Known
        # crosswalked codes: partial signal. Otherwise: no signal.
        a_code, b_code = str(a).upper(), str(b).upper()
        if a_code == b_code:
            return Decimal("1.0")
        if (a_code in CPT_FAMILIES and b_code in CPT_FAMILIES
                and CPT_FAMILIES[a_code] == CPT_FAMILIES[b_code]):
            return Decimal("0.7")
        if CPT_CROSSWALK.get(a_code) == b_code or CPT_CROSSWALK.get(b_code) == a_code:
            return Decimal("0.6")
        return Decimal("0.0")

    if field_name in ("modifiers", "diagnosis_codes"):
        # Set similarity via Jaccard. Empty-on-both returns 1.0 (trivially
        # equal); empty-on-one returns 0.0 (one side has information the
        # other lacks, which is worth distinguishing).
        return _jaccard(a, b)

    if field_name == "billed_amount":
        # Relative difference with a tolerance band. A fraction-of-a-percent
        # discrepancy is common rounding across fee-schedule versions and
        # shouldn't move the score much. A larger discrepancy is probably
        # a legitimate adjustment, not a duplicate.
        a_amt, b_amt = _to_decimal(a), _to_decimal(b)
        max_amt = max(a_amt, b_amt, Decimal("1.0"))
        rel_diff = abs(a_amt - b_amt) / max_amt
        if rel_diff < Decimal("0.01"):
            return Decimal("1.0")
        if rel_diff < Decimal("0.05"):
            return Decimal("0.8")
        if rel_diff < Decimal("0.20"):
            return Decimal("0.4")
        return Decimal("0.0")

    if field_name == "place_of_service":
        return Decimal("1.0") if str(a) == str(b) else Decimal("0.0")

    # Unknown field: be conservative.
    return Decimal("0.0")

def _levenshtein(a: str, b: str) -> int:
    """
    Classic Levenshtein edit distance. For teaching purposes the naive
    dynamic-programming version is fine; for production volumes consider
    the C-backed `rapidfuzz` library, which is an order of magnitude
    faster and supports additional metrics out of the box.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    # One row at a time: O(min(len(a), len(b))) memory.
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            current.append(min(
                previous[j] + 1,         # deletion
                current[j - 1] + 1,      # insertion
                previous[j - 1] + cost,  # substitution
            ))
        previous = current
    return previous[-1]

def _jaccard(a, b) -> Decimal:
    """
    Jaccard similarity on two iterables treated as sets.
    Returns 1.0 when both are empty, 0.0 when exactly one is empty.
    """
    set_a = set(a) if a else set()
    set_b = set(b) if b else set()
    if not set_a and not set_b:
        return Decimal("1.0")
    if not set_a or not set_b:
        return Decimal("0.0")
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return (_to_decimal(intersection) / _to_decimal(union)).quantize(Decimal("0.0001"))
```

---

## Step 4: Apply Routing Thresholds

*The pseudocode calls this `route_claim`. It applies the HIGH and LOW thresholds to the top-scoring candidate and sends the claim to one of three destinations: auto-suspend, human review, or auto-accept.*

Two notes. First, the "suspension record" is the artifact the adjudication system's denial workflow reads; it needs enough context (score, per-field components, matched claim ID, model version) that the denial can be explained to the provider on the remittance advice. Second, the SQS review-queue message carries the top-N candidates, not just the top one: examiners frequently see that a claim looks like candidate A on most fields but actually lines up better with candidate B once they inspect the details, and forcing them back to the claims UI to re-query defeats the purpose.

```python
# Top-N candidates attached to each review-queue message. More than five
# tends to clutter the examiner's view; fewer loses useful context.
REVIEW_CANDIDATE_LIMIT = 5

def route_claim(incoming: dict, scored_pairs: list, match_type: str) -> dict:
    """
    Apply thresholds and execute the routing action.

    scored_pairs: list of {"candidate": ..., "score": Decimal, "components": {...}}
                  already sorted by score descending.
    match_type:   "exact", "fuzzy", or "none" from find_candidates.

    Returns a decision dict describing what action was taken.
    """
    # Case 1: nothing to compare against. Pass through to adjudication.
    if not scored_pairs:
        _emit_metric("no_candidate_claims", 1)
        return {
            "action":   "auto_accept",
            "reason":   "no_candidates",
            "score":    None,
        }

    top = scored_pairs[0]
    top_score = top["score"]

    # Case 2: exact duplicate. Always auto-suspend regardless of score
    # (exact matches have score 1.0 by construction, but we're explicit
    # here so the audit trail is unambiguous).
    if match_type == "exact":
        _write_suspension_record(incoming, top, match_type="exact")
        _emit_metric("auto_suspended_exact", 1)
        return {
            "action":             "auto_suspend",
            "reason":              "exact_duplicate",
            "matched_claim_id":    top["candidate"]["claim_id"],
            "score":               Decimal("1.0"),
            "components":          top["components"],
        }

    # Case 3: fuzzy score above the high threshold. Auto-suspend.
    if top_score >= HIGH_THRESHOLD:
        _write_suspension_record(incoming, top, match_type="fuzzy")
        _emit_metric("auto_suspended_fuzzy", 1)
        return {
            "action":             "auto_suspend",
            "reason":              "fuzzy_high_score",
            "matched_claim_id":    top["candidate"]["claim_id"],
            "score":               top_score,
            "components":          top["components"],
        }

    # Case 4: mid band. Route to human review.
    if top_score >= LOW_THRESHOLD:
        top_n = scored_pairs[:REVIEW_CANDIDATE_LIMIT]
        message_body = {
            "incoming_claim_id":  incoming["claim_id"],
            "blocking_hash":      incoming["blocking_hash"],
            "enqueued_at":        datetime.now(timezone.utc).isoformat(),
            "scorer_version":     SCORER_VERSION,
            "candidates": [
                {
                    "claim_id":   pair["candidate"]["claim_id"],
                    "score":      str(pair["score"]),
                    "components": {k: str(v) for k, v in pair["components"].items()},
                }
                for pair in top_n
            ],
        }
        sqs_client.send_message(
            QueueUrl=REVIEW_QUEUE_URL,
            MessageBody=json.dumps(message_body),
        )
        _emit_metric("routed_to_review", 1)
        return {
            "action":    "review",
            "reason":    "mid_score_band",
            "top_score": top_score,
            "candidates_in_queue": len(top_n),
        }

    # Case 5: low band. Pass through.
    _emit_metric("auto_accepted", 1)
    return {
        "action":    "auto_accept",
        "reason":    "below_low_threshold",
        "top_score": top_score,
    }

def _write_suspension_record(incoming: dict, top: dict, match_type: str) -> None:
    """
    Persist the auto-suspend decision to DynamoDB. The adjudication system's
    denial workflow reads from this record to generate the provider's
    remittance advice with the correct denial reason and citation.

    A production system typically writes to a dedicated `claim-decisions`
    table (not shown here for brevity); we reuse claim-labels for teaching
    purposes to keep the example to two tables.
    """
    table = dynamodb.Table(CLAIM_LABELS_TABLE)
    record = {
        "pair_key": f"{incoming['claim_id']}#{top['candidate']['claim_id']}",
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "decision_type":     "auto_suspension",
        "match_type":        match_type,   # "exact" or "fuzzy"
        "incoming_claim_id": incoming["claim_id"],
        "matched_claim_id":  top["candidate"]["claim_id"],
        "score":             top["score"],
        "components":        {k: v for k, v in top["components"].items()},
        "scorer_version":    SCORER_VERSION,
    }
    table.put_item(Item=record)

def _emit_metric(metric_name: str, value: int) -> None:
    """
    Write a CloudWatch metric for the detector's operational dashboards.
    In production, batch metrics with `put_metric_data` and a MetricData
    list rather than one-call-per-metric; we keep it simple here.
    """
    try:
        cloudwatch.put_metric_data(
            Namespace="DuplicateDetector",
            MetricData=[{
                "MetricName": metric_name,
                "Value":      value,
                "Unit":       "Count",
                "Dimensions": [{"Name": "ScorerVersion", "Value": SCORER_VERSION}],
            }],
        )
    except Exception as ex:
        # Metric emission failures must not take down the pipeline.
        logger.warning("metric_emit_failed", extra={"metric": metric_name, "error": str(ex)})
```

---

## Step 5: Close the Feedback Loop

*The pseudocode calls this `on_examiner_verdict`. When an examiner resolves a review-queue item, the workstation publishes an event to EventBridge; a Lambda consumer writes the label to the label store. Every label carries the pair IDs, the examiner's verdict, a structured reasoning code, the scorer version that produced the original score, and timing information.*

The thing to understand here is that the label is the unit of progress for the whole system. Without labels, the scorer stays frozen at whatever it looked like on day one. With labels accumulating daily, the retraining pipeline (covered briefly below) has the raw material to improve the scorer over time. Label quality is as important as label quantity: structured reasoning codes from a controlled vocabulary generate a much cleaner training signal than free-text notes alone.

```python
# Structured reasoning codes the examiner workstation UI presents as buttons.
# Keep the vocabulary short; each code is a button in the UI and every
# new code is a new button the examiner has to scan.
VALID_VERDICTS = {"duplicate", "adjustment", "unique", "unclear"}
VALID_REASONING_CODES = {
    # Duplicate reasons
    "dup_exact_resubmission",
    "dup_typo_variant",
    "dup_crosswalked_code",
    "dup_same_service_different_npi",
    # Adjustment reasons
    "adj_corrected_claim",
    "adj_split_billing",
    "adj_frequency_code_7",
    # Unique reasons
    "uniq_different_service",
    "uniq_legitimate_similar",
    # Unclear reasons
    "uncl_insufficient_data",
    "uncl_escalate_to_sme",
}

def on_examiner_verdict(event: dict) -> None:
    """
    Consumer for examiner-verdict events delivered via EventBridge. Writes
    the label to the claim-labels DynamoDB table and appends it to the
    training-data S3 bucket.

    Expected event payload (published by the examiner workstation):
      incoming_claim_id, matched_claim_id, examiner_id, verdict,
      reasoning_code, reasoning_text, scorer_version, score_at_decision,
      components_at_decision, enqueued_at
    """
    _validate_verdict_event(event)

    now = datetime.now(timezone.utc)
    enqueued = datetime.fromisoformat(event["enqueued_at"])
    review_duration_sec = (now - enqueued).total_seconds()

    label = {
        "pair_key": f"{event['incoming_claim_id']}#{event['matched_claim_id']}",
        "resolved_at":              now.isoformat(),
        "decision_type":            "examiner_verdict",
        "incoming_claim_id":        event["incoming_claim_id"],
        "matched_claim_id":         event["matched_claim_id"],
        "examiner_id":              event["examiner_id"],
        "verdict":                  event["verdict"],
        "reasoning_code":           event["reasoning_code"],
        # Free-text reasoning may include PHI references. Encrypt at rest
        # and scope read access tightly. Retention follows your PHI policy.
        "reasoning_text":           event.get("reasoning_text", ""),
        "scorer_version":           event["scorer_version"],
        "score_at_decision":        _to_decimal(event["score_at_decision"]),
        "components_at_decision":   {
            k: _to_decimal(v) for k, v in event.get("components_at_decision", {}).items()
        },
        "enqueued_at":              event["enqueued_at"],
        "review_duration_sec":      _to_decimal(review_duration_sec),
    }

    # DynamoDB for the fast access path (examiner UI lookups, recent-label
    # dashboards, live monitoring).
    table = dynamodb.Table(CLAIM_LABELS_TABLE)
    table.put_item(Item=label)

    # S3 for the bulk access path (periodic retraining, audit export).
    archive_key = (
        f"labels/year={now.year:04d}/month={now.month:02d}/day={now.day:02d}/"
        f"{uuid.uuid4()}.json"
    )
    s3_client.put_object(
        Bucket=LABELS_BUCKET,
        Key=archive_key,
        Body=json.dumps(label, default=str).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )

    # Operational metrics. Verdict distribution over time is an early
    # signal of examiner agreement drift; review-duration distribution
    # signals UI problems or hard-case cohorts in the queue.
    _emit_metric(f"label_{event['verdict']}", 1)
    _emit_metric("review_duration_sec_total", int(review_duration_sec))

    logger.info(
        "label_captured",
        extra={
            "pair_key":       label["pair_key"],
            "verdict":        event["verdict"],
            "reasoning_code": event["reasoning_code"],
            "review_sec":     int(review_duration_sec),
        },
    )

def _validate_verdict_event(event: dict) -> None:
    """
    Minimal validation. A malformed event should fail fast here rather
    than silently write a bad label.
    """
    required = {
        "incoming_claim_id", "matched_claim_id", "examiner_id",
        "verdict", "reasoning_code", "scorer_version",
        "score_at_decision", "enqueued_at",
    }
    missing = required - set(event.keys())
    if missing:
        raise ValueError(f"Verdict event missing required fields: {sorted(missing)}")

    if event["verdict"] not in VALID_VERDICTS:
        raise ValueError(f"Unknown verdict: {event['verdict']!r}. "
                         f"Valid: {sorted(VALID_VERDICTS)}")
    if event["reasoning_code"] not in VALID_REASONING_CODES:
        raise ValueError(f"Unknown reasoning_code: {event['reasoning_code']!r}. "
                         f"Valid: {sorted(VALID_REASONING_CODES)}")
```

---

## The Full Pipeline

Here's the end-to-end `detect_duplicates` function that wires all five steps together. This is what runs per incoming claim in the batch-pre-adjudication mode; in real-time mode the same logic is triggered by an event off a Kinesis stream instead of by a batch driver.

```python
def detect_duplicates(raw_claim: dict) -> dict:
    """
    End-to-end duplicate detection for a single incoming claim.

    Steps:
      1. Normalize and persist the claim.
      2. Find candidate duplicates (exact + blocking).
      3. Score each candidate pair.
      4. Apply thresholds and route.
      5. (Feedback loop runs asynchronously; not in this function.)
    """
    print(f"[1/4] Normalizing claim {raw_claim.get('claim_id')}...")
    normalized = normalize_claim(raw_claim)
    persist_normalized_claim(normalized)

    print(f"[2/4] Finding candidates in block {normalized['blocking_hash'][:12]}...")
    candidate_result = find_candidates(normalized)
    match_type = candidate_result["match_type"]
    candidates = candidate_result["candidates"]
    print(f"       match_type={match_type}, candidate_count={len(candidates)}")

    print("[3/4] Scoring candidate pairs...")
    scored_pairs = []
    for candidate in candidates:
        scored = score_pair(normalized, candidate)
        scored_pairs.append({
            "candidate":  candidate,
            "score":      scored["score"],
            "components": scored["components"],
        })
    # Highest score first.
    scored_pairs.sort(key=lambda p: p["score"], reverse=True)

    print("[4/4] Applying routing thresholds...")
    decision = route_claim(normalized, scored_pairs, match_type)
    print(f"       decision={decision['action']} ({decision.get('reason')})")

    return {
        "normalized_claim": normalized,
        "candidate_result": candidate_result,
        "scored_pairs":     scored_pairs,
        "decision":         decision,
    }

# --- Example usage ---
#
# A minimal example claim shaped like what a parser would produce.
# Values are synthetic and do not refer to any real person, provider, or
# service. Use Synthea or CMS sample 837 transactions in a development
# environment; never use real PHI in a teaching example.
if __name__ == "__main__":
    sample_claim = {
        "claim_id":          "CLM-2026-0487291",
        "patient_id":        "123456",                 # gets zero-padded
        "subscriber_id":     "123456",
        "billing_npi":       "1234567890",
        "rendering_npi":     "1234567890",
        "date_of_service":   "03/15/2026",             # gets reformatted
        "place_of_service":  "11",
        "cpt_code":          "99213",
        "modifiers":         ["25"],
        "diagnosis_codes":   ["J06.9", "R05"],
        "billed_amount":     "250.00",                 # becomes Decimal
        "submission_source": "clearinghouse-A",
    }

    result = detect_duplicates(sample_claim)
    print()
    print("=== DECISION ===")
    print(json.dumps(result["decision"], indent=2, default=str))
```

Running this against an empty `claim-history` table will return an `auto_accept` decision (no candidates to compare against). The interesting paths show up once the table has history: seed it with a near-duplicate variant of the sample claim (change the billed amount by a few percent, or adjust the date by a day) and watch the scorer produce a mid-band score that routes to the review queue.

---

## A Note on Retraining

The main recipe's `retrain_weekly` function is not implemented in this Python example on purpose. Retraining is a SageMaker-hosted training job plus a feature-engineering pipeline plus an endpoint update, and each of those is a multi-hundred-line block of code that isn't teaching anything new about duplicate detection. The shape of the job is covered in the pseudocode; the concrete AWS patterns for it are covered in Recipe 3.5 (Real-Time Model Retraining for Anomaly Detection) when you get there.

What the retraining pipeline needs from the code above is: a steady stream of labels written to the `claim-labels` table and to the labels S3 bucket, a stable pair key that joins labels back to both claim records in the training window, and a scorer version that flows through every record so the training window can be filtered precisely. The current code produces all three. When you're ready to wire up SageMaker, those data structures are what the training script reads.

---

## Gap to Production

Several things would need to change before you'd deploy any of this.

**Real 837 parsing.** The normalization step starts from a parsed claim dictionary. In production, the parser Lambda runs a real EDI library (commercial or well-maintained open source) against the raw 837 transaction sets arriving from your clearinghouses. Budget time to tune parser behavior per trading partner; every clearinghouse has quirks. The parser should handle 837P (professional) and 837I (institutional) at minimum, and 837D (dental) if you're writing dental coverage.

**Idempotency.** The `persist_normalized_claim` function writes unconditionally. In production, S3 events may deliver the same object more than once (at-least-once semantics), and the parser Lambda may retry after a transient failure. Use DynamoDB `ConditionExpression` with `attribute_not_exists(claim_id)` to make the write idempotent, and handle the `ConditionalCheckFailedException` as a success (the claim was already written).

**Pagination.** The blocking `query` in `find_candidates` assumes the block fits in a single response. DynamoDB returns at most 1 MB per Query response, and a hot block (an unusually large patient or organization) can exceed that. Loop with `LastEvaluatedKey` to retrieve the full candidate set, and add a safety limit beyond which you log an alarm and investigate the blocking function (a single block with 10,000 candidates is always a bug).

**Error handling.** The example's error handling is minimal. In production, wrap each external call in try/except with structured logging, emit a failure metric, and route the claim to a dead-letter queue for operations review. Do not silently swallow DynamoDB throttling, SQS send failures, or S3 access-denied errors; each is a different class of problem with a different mitigation.

**Structured logging with PHI discipline.** The `logger.info` calls above log structural metadata only. In production, use a JSON log formatter (not a plain string), ship logs to CloudWatch Logs with a log group encrypted by a customer-managed KMS key, and audit log content with a regular scan for unexpected PHI patterns (member IDs, NPIs, DOB-looking strings). A single accidental `logger.info("claim: %s", claim)` call during debugging can create a PHI disclosure that survives in CloudWatch until your retention policy clears it.

**IAM scoping.** The permissions list in the Setup section covers what this code does, but in production each Lambda role is scoped tightly. The parser's role needs no SQS or CloudWatch permissions. The detector's role needs no S3 write permissions except for the suspension archive. The label-writer's role needs no detector permissions. Scope to specific resource ARNs (`arn:aws:dynamodb:us-east-1:123456789012:table/claim-history` rather than `dynamodb:*`). Review the roles annually.

**VPC deployment.** In production, the Lambdas run inside a VPC with VPC endpoints for DynamoDB, S3, SQS, EventBridge, KMS, and CloudWatch Logs. The SageMaker endpoint (when you add one) runs in the same VPC. VPC Flow Logs are enabled on the subnet. Nothing about claim data traverses the public internet.

**KMS customer-managed keys.** All data at rest (DynamoDB tables, S3 buckets, SQS queue, EventBridge archive, CloudWatch Logs) is encrypted with customer-managed KMS keys. The key policy restricts usage to the specific roles that need it; audit who is using each key via CloudTrail data events.

**Testing.** A real codebase has unit tests for every scoring function (same-day vs. adjacent-day date similarity, Jaccard edge cases, Levenshtein on short identifiers, CPT family matches) and integration tests for the full pipeline against a local DynamoDB (via DynamoDB Local) and a mock SQS. Add property-based tests for the scoring functions; the invariant "score is always in [0, 1]" is easy to break with a weight change and hard to notice until production.

**DynamoDB schema and capacity.** The table design above (blocking_hash partition key, claim_id sort key, GSI on content_hash) handles the detection path. Production tables use on-demand capacity mode for unpredictable claim arrival patterns, or a combination of provisioned capacity with auto-scaling. Review the partition-key distribution; a blocking function that produces very hot partitions (patient IDs that get claims every day) will throttle. Mitigate by further composing the blocking key or by using a write-sharding strategy on the hot partitions.

**Decimal serialization.** The example code serializes `Decimal` to strings for JSON payloads. In production, use a consistent custom JSON encoder across the entire codebase so the boundary between Python-side math (Decimal) and JSON-side representation (string) is explicit. Mixing `default=str` in one place and a custom encoder in another is a subtle source of bugs.

**Monitoring and alarms.** The `_emit_metric` function drops metrics into CloudWatch. Production requires CloudWatch alarms on top of those metrics (auto-suspend rate outside expected range, review-queue depth above target, no metrics emitted for 15 minutes, scorer latency p99 above SLA). Wire alarms to SNS topics that page the on-call.

**Fairness monitoring.** Sample the auto-suspend stream by provider size, geography, and specialty. A disparity between subgroup auto-suspend rates that cannot be explained by the underlying duplicate rate in that subgroup is a fairness signal worth investigating before it becomes a provider-relations problem or, worse, a regulatory one.

**Retention and legal hold.** The `normalized-claims` and `labels` S3 buckets need lifecycle policies that match your retention requirements (CMS: 10 years for Medicare). Use S3 Object Lock in COMPLIANCE mode on the raw-837 and labels buckets in production environments; GOVERNANCE mode is fine for dev/test so you can clean up. Budget for storage; labels and claim archives grow without bound if you don't tier to Glacier or Deep Archive.

**Access pattern for retraining.** The retraining pipeline needs bulk scans, not point lookups. Schedule a DynamoDB export to S3 (the built-in feature, not a custom reader) on the cadence your retraining expects, and register the export as a Glue table so Athena can query it. Do not run full-table scans against the live DynamoDB table; you'll impact the detection path.

None of this is unique to duplicate detection. It's the cost of running any PHI-handling service in production. The good news: once you have the infrastructure for one pattern (this one), it amortizes across every other recipe in the Anomaly Detection chapter.

---

*← [Main Recipe 3.1](chapter03.01-duplicate-claim-detection) · [Chapter 3 Preface](chapter03-preface)*
