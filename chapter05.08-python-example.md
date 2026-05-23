# Recipe 5.8: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 5.8. It shows one way you could translate the privacy-preserving record linkage (PPRL) pattern into working Python using a small `MockSaltCustody` standing in for AWS CloudHSM and KMS, `MockProtocolParameterizationStore` standing in for the versioned configuration store, `MockParticipantDataSource` standing in for each participant's source data system (EHR, claims, registry), `MockEncodedRecordsBucket` standing in for the cross-account S3 buckets, `MockLinkageCycleStore` standing in for the DynamoDB linkage-cycle-metadata and linkage-results tables, `MockConsentStore` standing in for the per-record consent posture and patient-portal preference capture, `MockJurisdictionalOverlays` standing in for the per-state and per-record-type policy overlay (post-Dobbs reproductive-health-care, 42 CFR Part 2 substance-use-treatment, gender-affirming-care state-law overlays), an in-memory event bus standing in for Amazon EventBridge, an in-memory queue standing in for the linkage-review queue, and small helpers for the audit-log archive and CloudWatch-style metrics. It is not production-ready. There is no real `clkhash` or `anonlink` integration, no real CLK encoding (the demo uses simplified Bloom filters that illustrate the construction without the production-grade defensive measures like random hashing, balanced encoding, or hardening), no real Nitro Enclave attestation, no real cross-account exchange or PrivateLink, no real Glue/Spark population-scale encoding, no Step Functions orchestration, no SageMaker calibration loop, no commercial tokenization vendor integration, no SMPC protocol runner, no homomorphic encryption, and no IAM, KMS, VPC, WAF, or CloudTrail wiring. Think of it as the sketchpad version: useful for understanding the shape of a PPRL pipeline that respects the cryptographic-encoding-before-exchange posture, the parameterization-pinning-and-salt-rotation discipline, the trust-architecture-as-architectural-artifact distinction (the matcher operates on encoded records; the protocol's trust framework decides who has access to what), the disclosure-policy-form-per-use-case discipline (per-record-match-flags vs intersection-count vs k-anonymous-aggregate vs differentially-private-aggregate vs encrypted-match-indicator), the cohort-stratified-accuracy-monitoring-without-demographic-visibility constraint, and the re-encoding-as-the-primary-mitigation posture this recipe demands. It is not something you would point at a live data-sharing collaboration on Monday morning. Consider it a starting point, not a destination.
>
> The code maps to the six core pseudocode steps from the main recipe: standardize and prepare the per-participant demographic-feature set under the protocol's shared schema; apply the cryptographic encoding under the pinned protocol parameterization (CLK Bloom-filter construction with per-feature bit allocation); exchange the encoded records under the trust architecture (in the demo, all participants run in one process; production exchanges across accounts and organizations); match the encoded records using Sørensen-Dice similarity over the CLK plus a Fellegi-Sunter-style probabilistic combiner; apply the disclosure policy and route the linkage results in one of several disclosure forms; and react to invalidation events that supersede prior linkages (salt rotation, parameterization upgrade, consent withdrawal, identity merge from recipe 5.1, name change from recipe 5.7). The synthetic patients and demographics in the demo are fictional; the names, DOBs, addresses, and other identifiers are obviously made-up and should not match anyone real.

---

## Setup

You will need the AWS SDK for Python:

```bash
pip install boto3
```

In production you would also install [`clkhash`](https://github.com/data61/clkhash) for the CLK encoding (production-grade Bloom-filter construction with the defensive measures the academic literature recommends), [`anonlink`](https://github.com/data61/anonlink) for the matching layer (efficient candidate generation and Sørensen-Dice scoring at population scale), [Splink](https://github.com/moj-analytical-services/splink) or [`recordlinkage`](https://github.com/J535D165/recordlinkage) for the Fellegi-Sunter probabilistic-combiner core (the same machinery used in recipes 5.1, 5.4, 5.5, 5.6, 5.7), [`jellyfish`](https://github.com/jamesturk/jellyfish) for approximate string matching during pilot calibration with full demographic visibility, [OpenMined PSI](https://github.com/OpenMined/PSI) for the private-set-intersection family of protocols, [Microsoft SEAL](https://github.com/microsoft/SEAL) Python bindings for the homomorphic-encryption family, a Spark client (`pyspark`) for the bulk-encoding and matcher-execution pipelines, and the AWS Nitro Enclaves SDK for the TEE-based variant. The demo replaces all of these with small mocks so the focus stays on the encoding-exchange-match-disclose-invalidate logic rather than on the cryptographic primitive details.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchGetItem`, `dynamodb:TransactWriteItems` on the `linkage-cycle-metadata`, `linkage-results-store`, `protocol-parameterization-config`, and per-participant local-mapping tables
- `s3:PutObject` on the per-participant encoded-records buckets (with cross-account access policies enumerating the matcher's role), the audit-archive bucket (Object Lock in Compliance mode), and the derived-snapshot bucket
- `s3:GetObject` on the encoded-records buckets for the matcher's read path (cross-account)
- `sqs:SendMessage` and `sqs:ReceiveMessage` on the linkage-review-queue, the salt-rotation-review-queue, the consent-withdrawal-review-queue, and the propagation-queue
- `events:PutEvents` on the pprl-events bus
- `cloudwatch:PutMetricData` for the encoding-rate, linkage-rate, cohort-stratified-disparity, salt-rotation-backlog, and re-encoding-coverage metrics
- `kms:Decrypt` and `kms:GenerateDataKey` on the customer-managed keys protecting the encoded-records buckets, the linkage-cycle-metadata table, the linkage-results store, and the audit archive
- `kms:Sign` (or the equivalent CloudHSM operation) on the per-cycle salt-key version pinned for the current linkage cycle. Critically, the encoding role gets permissions on *only* the salt-key version pinned for the current cycle, not any prior or future version
- `glue:StartJobRun` and `glue:GetJobRun` on the per-participant bulk-encoding Glue jobs and the matcher-execution Glue job (production only; the demo runs in-process)
- For the TEE-based variant: `ec2:DescribeInstances`, `ec2:RunInstances` with the Nitro Enclaves enabled flag, `ec2:TerminateInstances`, and the attestation-document-verification permissions on the parent EC2 instance

Scope each Lambda's IAM role and each Glue job's role to the specific resource ARNs they touch. The tutorial-level permissions above are fine for learning and will fail any serious IAM review. The encoding role is per-cycle bound through Step Functions and has time-bound access to the salt-key version only during the cycle's active execution window; the matcher role has read access to all participants' encoded-records buckets through cross-account bucket policies but never has access to any participant's source data.

A few things worth knowing upfront:

- **The encoding step happens before any exchange.** Recipe 5.5's matcher operates on plaintext demographic features that flow through the HIE's matching layer; recipe 5.8's matcher operates on cryptographically-encoded representations that are produced *before* any cross-organizational exchange. The encoding step is per-participant and parameterization-pinned: every participating organization runs the same encoding under the same parameterization to produce comparable encoded records. Mis-coordinated encoding produces silent linkage failures where the matcher returns zero matches because the encoded representations are not comparable.
- **The cryptographic salt is the protocol's root-of-trust.** If the salt is compromised, retroactively the privacy guarantee of every encoded record under that salt is broken. Salt rotation invalidates all previously-encoded data and requires the participating organizations to re-encode their populations under the new salt. Salt custody is a hardware-security-module concern; salt rotation is a coordinated multi-organization ceremony with explicit dual-control approval.
- **The matcher operates on similarity over Bloom filters, not over strings.** The Sørensen-Dice coefficient between two CLKs is monotonically related to the underlying string-edit-distance similarity, but the absolute scale is different. The encoded-data thresholds (ENCODED_MATCH_HIGH, ENCODED_MATCH_MED, ENCODED_REJECT) are calibrated separately from the conventional thresholds because the encoded scoring function is different. Re-using recipe 5.5's thresholds for PPRL produces silent linkage failures.
- **The disclosure form constrains what the consumer learns.** Per-record-match-flags reveals which specific records intersected; intersection-count reveals only the size of the intersection; k-anonymous-aggregate reveals only cohort-level aggregates with small-cell suppression; differentially-private-aggregate reveals aggregates with calibrated noise; encrypted-match-indicator reveals matches only to a designated decryption key holder. The disclosure form is a privacy property of the protocol, not a presentation choice.
- **Cohort-stratified accuracy monitoring works without demographic visibility.** Each participant computes its own cohort-axis values locally (using its own demographic visibility) and contributes the *hashes* of those values in the encoded-record envelope. The matcher receives the hashes (not the values) and can stratify accuracy metrics by hash without learning the underlying axis values.
- **Re-encoding is the primary mitigation, not retraction.** A linkage that was wrong cannot be retracted from a counterparty that has already consumed it; the only mitigation is to re-encode under a new parameterization, re-run the linkage, and disclose the corrected result with explicit communication that the prior result is superseded.
- **DynamoDB rejects Python `float`.** Every detection score, similarity score, and numeric metadata field passes through `Decimal` on its way in and on its way out. Same gotcha as recipes 5.1 / 5.2 / 5.3 / 5.4 / 5.5 / 5.6 / 5.7; the same `_to_decimal` helper handles it.
- **The example collapses Step Functions, multiple Glue jobs, multiple Lambdas, the Nitro Enclave matcher path, the cross-account exchange, and the SQS-driven worker pattern into a single Python file for readability.** In production the standardize, encode, exchange, match, disclose, persist, and invalidate-on-event stages are separate Lambdas (for the operational stream) and Glue jobs (for the population-scale encoding and matching) orchestrated by Step Functions, each with their own error handling, retries, and DLQs, running in separate AWS accounts under cross-account access policies. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here. Resource names, the protocol parameterization (salt-key version, n-gram size, Bloom-filter size, hash-function count, per-feature bit allocation), the encoded-data thresholds, the per-feature weights, and the disclosure-policy templates are what you would change between environments.

```python
import hashlib
import hmac
import json
import logging
import math
import re
import secrets
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records
# to CloudWatch Logs Insights. Encoded records are not PHI by
# themselves (the cryptographic transform is the privacy claim),
# but the per-record consent posture, the cohort-axis hashes, and
# the source-record identifiers (retained locally at each
# participant) all carry information that should not leak through
# logs. Log structural metadata only (cycle_id, encoded_record_id,
# parameterization_version, salt_key_version, decision band),
# never CLK payloads, never raw demographics, never source-record
# identifiers from cross-participant context.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from DynamoDB, EventBridge,
# CloudWatch, S3, and SQS. Per-cycle linkage latencies are not
# real-time critical (research collaborations and public-health
# surveillance run on cycle cadences of weekly to quarterly), but
# bulk encoding runs are throughput-sensitive enough that
# transient throttling on any one service should not fail an
# entire Glue job. Step Functions Catch states distinguish
# retriable infrastructure failures from terminal logic failures
# and route terminal failures to a DLQ for human investigation.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm
# containers so each invocation does not pay the connection cost.
REGION = "us-east-1"
dynamodb           = boto3.resource("dynamodb", region_name=REGION, config=BOTO3_RETRY_CONFIG)
s3_client          = boto3.client("s3",          region_name=REGION, config=BOTO3_RETRY_CONFIG)
sqs_client         = boto3.client("sqs",         region_name=REGION, config=BOTO3_RETRY_CONFIG)
eventbridge_client = boto3.client("events",      region_name=REGION, config=BOTO3_RETRY_CONFIG)
cloudwatch_client  = boto3.client("cloudwatch",  region_name=REGION, config=BOTO3_RETRY_CONFIG)
kms_client         = boto3.client("kms",         region_name=REGION, config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill these in with your actual resource names. The demo prints
# what it would write rather than failing if the resources do not
# exist; see run_demo() at the bottom.
LINKAGE_CYCLE_TABLE         = "linkage-cycle-metadata"
LINKAGE_RESULTS_TABLE       = "linkage-results-store"
PROTOCOL_CONFIG_TABLE       = "protocol-parameterization-config"
PARTICIPANT_LOCAL_MAP_TABLE = "participant-local-mapping"
PARTICIPANT_A_BUCKET        = "participant-a-encoded-records"
PARTICIPANT_B_BUCKET        = "participant-b-encoded-records"
AUDIT_ARCHIVE_BUCKET        = "pprl-audit-archive"
DERIVED_SNAPSHOT_BUCKET     = "pprl-derived-snapshots"
LINKAGE_REVIEW_QUEUE_URL    = "https://sqs.us-east-1.amazonaws.com/000000000000/pprl-linkage-review-queue"
SALT_ROTATION_QUEUE_URL     = "https://sqs.us-east-1.amazonaws.com/000000000000/pprl-salt-rotation-queue"
CONSENT_WITHDRAWAL_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/000000000000/pprl-consent-withdrawal-queue"
PROPAGATION_QUEUE_URL       = "https://sqs.us-east-1.amazonaws.com/000000000000/pprl-propagation-queue"
PPRL_EVENT_BUS_NAME         = "pprl-events-bus"
CLOUDWATCH_NAMESPACE        = "PrivacyPreservingRecordLinkage/Cycle"

# Deploy-time guardrail. Any blank resource name is a deploy-time
# bug, not a runtime surprise.
for _name, _value in [
    ("LINKAGE_CYCLE_TABLE",         LINKAGE_CYCLE_TABLE),
    ("LINKAGE_RESULTS_TABLE",       LINKAGE_RESULTS_TABLE),
    ("PROTOCOL_CONFIG_TABLE",       PROTOCOL_CONFIG_TABLE),
    ("PARTICIPANT_LOCAL_MAP_TABLE", PARTICIPANT_LOCAL_MAP_TABLE),
    ("PARTICIPANT_A_BUCKET",        PARTICIPANT_A_BUCKET),
    ("PARTICIPANT_B_BUCKET",        PARTICIPANT_B_BUCKET),
    ("AUDIT_ARCHIVE_BUCKET",        AUDIT_ARCHIVE_BUCKET),
    ("DERIVED_SNAPSHOT_BUCKET",     DERIVED_SNAPSHOT_BUCKET),
    ("LINKAGE_REVIEW_QUEUE_URL",    LINKAGE_REVIEW_QUEUE_URL),
    ("SALT_ROTATION_QUEUE_URL",     SALT_ROTATION_QUEUE_URL),
    ("CONSENT_WITHDRAWAL_QUEUE_URL", CONSENT_WITHDRAWAL_QUEUE_URL),
    ("PROPAGATION_QUEUE_URL",       PROPAGATION_QUEUE_URL),
    ("PPRL_EVENT_BUS_NAME",         PPRL_EVENT_BUS_NAME),
    ("CLOUDWATCH_NAMESPACE",        CLOUDWATCH_NAMESPACE),
]:
    assert _value, f"{_name} must be set before deploying."

# --- Versioning ---
# Every encoded record and every linkage-cycle metadata row
# carries the parameterization version and the salt-key version
# active at decision time. This is how a future audit
# reconstructs which cryptographic primitives were active when a
# particular linkage was made, and how the invalidation pipeline
# knows which records to re-encode when the salt rotates.
PROTOCOL_PARAMETERIZATION_VERSION = "pprl-clk-v2.3.1"
MATCHER_CONFIG_VERSION            = "pprl-fs-v1.4.2"

# --- Protocol parameterization (CLK Bloom-filter encoding) ---
# These parameters control the cryptographic encoding. They are
# negotiated cross-participant before any encoding happens and
# pinned per cycle. Mis-coordinated parameters (one party uses
# n=2, the other uses n=3; one party uses k=30, the other uses
# k=20; one party uses a 1024-bit filter, the other uses 2048)
# produce encoded records that are not comparable, and the
# matcher silently returns zero matches.
PROTOCOL_PARAMETERIZATION = {
    "parameterization_version": PROTOCOL_PARAMETERIZATION_VERSION,
    "n_gram_size":              2,       # bigrams
    "bloom_filter_size":        1024,    # total bits
    "hash_function_count":      30,      # k value
    "per_feature_bit_allocation": {
        # Each feature gets a share of the total filter. Names
        # get more bits because they're the most discriminating
        # feature; DOB and SSN-last-4 are tokenized (set-bit-
        # exact) rather than n-gram-encoded so they don't need
        # a wide allocation.
        "given_name":   200,
        "middle_name":  100,
        "family_name":  300,
        "dob":          150,
        "address_line": 150,
        "zip_code":     50,
        "phone":        50,
        "ssn_last_4":   24,
    },
    "defensive_measures": {
        # Production CLK encoders apply random hashing (varies
        # the hash-function-to-bit-position mapping per record),
        # balanced encoding (ensures each filter has a similar
        # number of set bits to defeat frequency analysis), and
        # hardening (deliberate noise injection that defeats
        # specific known attacks). The demo's defensive measures
        # are deliberately simple; production uses clkhash which
        # implements current-best-practice variants.
        "random_hashing_enabled":   False,
        "balanced_encoding_enabled": False,
        "hardening_enabled":         False,
    },
}

# --- Encoded-data thresholds ---
# Calibrated SEPARATELY from the conventional matcher's
# thresholds in recipe 5.1 / 5.5. The encoded-data scoring
# function is different (Sørensen-Dice over Bloom filters
# combined Fellegi-Sunter-style) and the absolute scale of
# similarity scores is different. Re-using the recipe 5.5
# thresholds for PPRL produces silent linkage failures.
# Calibrate against a known-overlap pilot population encoded
# under the production parameterization, with input from the
# institution's analytics governance committee, the privacy
# team, and the cohort-equity-monitoring committee.
ENCODED_MATCH_HIGH_THRESHOLD = Decimal("0.85")
ENCODED_MATCH_MED_THRESHOLD  = Decimal("0.72")
ENCODED_REJECT_THRESHOLD     = Decimal("0.50")

# --- Per-feature weights for the Fellegi-Sunter combiner ---
# Same probabilistic-record-linkage core as recipes 5.1 / 5.5.
# The weights reflect the relative discriminating power of each
# feature plus the encoded-data noise level (more noise = less
# weight). DOB carries less weight here than in plaintext
# matching because the encoded-data matcher is comparing token-
# level set-membership rather than exact string match, so the
# feature is more vulnerable to encoding noise.
FEATURE_WEIGHTS = {
    "given_name":   Decimal("0.18"),
    "middle_name":  Decimal("0.08"),
    "family_name":  Decimal("0.22"),
    "dob":          Decimal("0.20"),
    "address_line": Decimal("0.10"),
    "zip_code":     Decimal("0.05"),
    "phone":        Decimal("0.07"),
    "ssn_last_4":   Decimal("0.10"),
}

# --- Disclosure forms ---
# Each form has its own privacy properties. The protocol's trust
# framework specifies which form(s) a particular linkage is
# authorized to produce. Some research collaborations authorize
# only intersection_count; others authorize per_record_match_flags
# for each participant restricted to its own records; others
# authorize differentially_private_aggregate for cross-cohort
# analytic queries.
DISCLOSURE_FORMS = {
    "per_record_match_flags",          # per-record yes/no flags
    "intersection_count",              # size only
    "k_anonymous_aggregate",           # cohort aggregates with suppression
    "differentially_private_aggregate", # aggregates with DP noise
    "encrypted_match_indicator",       # encrypted under consumer key
}

# --- Default k-anonymity and differential-privacy parameters ---
# The disclosure-policy specifies these per use case. Values
# below are illustrative defaults; institutional privacy team
# owns the per-use-case parameters.
DEFAULT_K_ANONYMITY        = 11
DEFAULT_SUPPRESSION_THRESHOLD = 5
DEFAULT_DP_EPSILON         = Decimal("1.0")
DEFAULT_DP_DELTA           = Decimal("0.000001")  # 1e-6

# --- Cohort axes ---
# Each participant computes its own cohort-axis values locally
# (using its own demographic visibility) and contributes the
# *hashes* of those values in the encoded-record envelope. The
# matcher receives the hashes (not the values) and can stratify
# accuracy metrics by hash without learning the underlying axis
# values. Production includes additional axes specific to the
# institution's equity-monitoring program; the demo's three are
# illustrative.
COHORT_AXES = ["name_tradition", "age_decade", "sex_or_gender"]
```

## Helpers

Same family of small helpers used in recipes 5.1 - 5.7. The `_to_decimal`, `_serialize_for_dynamodb`, and `_canonical_name` helpers are the load-bearing ones. The encoding-specific helpers (`_produce_n_grams`, `_compute_per_feature_size`, `_set_bit`, `_count_set_bits`, `_sorensen_dice_coefficient`) implement the CLK Bloom-filter primitives.

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
    """Strip combining diacritical marks for cross-participant
    canonicalization. Critical for names with accents that one
    participant's EHR may have stripped on input while another
    participant's preserved them. If the canonicalization differs
    cross-participant, the encoded records will not match even
    when they refer to the same person."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _canonical_name(*parts) -> str:
    """Normalize a name to canonical lowercase whitespace-collapsed
    form for encoding. Production handles per-tradition rules
    (Spanish double-surname order, East Asian family-name-first
    conventions, Arabic patronymic structures) here too. The
    canonicalization spec is part of the protocol parameterization
    and is the same across all participants."""
    joined = " ".join(str(p or "").strip() for p in parts)
    joined = _strip_diacritics(joined).lower()
    joined = re.sub(r"[^\w\s'-]", " ", joined)
    joined = re.sub(r"\s+", " ", joined).strip()
    return joined


def _produce_n_grams(value: str, n: int = 2,
                       include_markers: bool = True) -> list:
    """Tokenize a string into n-grams. Underscores serve as
    start-and-end markers that improve robustness on short
    strings (the underscore counts as the start-of-string token
    so 'Bob' becomes ['_B', 'Bo', 'ob', 'b_'] rather than just
    ['Bo', 'ob'])."""
    if not value:
        return []
    if include_markers:
        value = "_" + value + "_"
    return [value[i:i + n] for i in range(len(value) - n + 1)]


def _compute_per_feature_size(parameterization: dict,
                                feature_name: str) -> int:
    """Look up the feature's bit allocation from the protocol
    parameterization."""
    return parameterization["per_feature_bit_allocation"].get(
        feature_name, 0)


def _hmac_sha_256(key: bytes, message: bytes) -> bytes:
    """HMAC-SHA-256 keyed hash. The salt is the HMAC key; varying
    the key per hash-function-index gives k independent hash
    functions. Production uses HSM-backed HMAC where the key
    plaintext never leaves the hardware-security-module; the
    demo uses a simple hmac.new() for readability."""
    return hmac.new(key, message, hashlib.sha256).digest()


def _hash_to_bit_position(salt: bytes, k_index: int, n_gram: str,
                              modulus: int) -> int:
    """Produce a bit position by HMAC'ing the n-gram under a
    salt-derived key for the given hash-function index. Modulo
    the bit array size to land in range."""
    # Derive the per-k-index key from the salt by HMAC'ing the
    # k_index. Production uses a more robust key-derivation
    # scheme (HKDF with explicit info parameter); the demo's
    # simple HMAC suffices for illustration.
    per_k_key = _hmac_sha_256(salt, k_index.to_bytes(4, "big"))
    h = _hmac_sha_256(per_k_key, n_gram.encode("utf-8"))
    # Take first 8 bytes as a 64-bit integer; mod into the bit array.
    return int.from_bytes(h[:8], "big") % modulus


def _bit_array(size: int) -> bytearray:
    """Initialize an empty bit array of the given size in bits."""
    return bytearray((size + 7) // 8)


def _set_bit(bits: bytearray, position: int) -> None:
    """Set the bit at the given position in the bit array."""
    bits[position // 8] |= (1 << (position % 8))


def _is_bit_set(bits: bytearray, position: int) -> bool:
    """Test whether the bit at the given position is set."""
    return bool(bits[position // 8] & (1 << (position % 8)))


def _count_set_bits(bits: bytearray) -> int:
    """Population count over the bit array. Used for the
    Sørensen-Dice denominator and for balanced-encoding
    diagnostics."""
    return sum(bin(b).count("1") for b in bits)


def _bitwise_and_count(bits_a: bytearray, bits_b: bytearray) -> int:
    """Count of bits set in the bitwise AND of two filters; the
    Sørensen-Dice numerator's intersection size."""
    if len(bits_a) != len(bits_b):
        raise ValueError(
            "Bloom filter size mismatch (parameterization "
            "mis-coordination). This is the classic silent-failure "
            "mode for PPRL: encoded records produced under "
            "different parameterization versions are not "
            "comparable. The cycle's parameterization version "
            "should have been validated at exchange time.")
    return sum(bin(a & b).count("1") for a, b in zip(bits_a, bits_b))


def _sorensen_dice_coefficient(bits_a: bytearray,
                                  bits_b: bytearray) -> Decimal:
    """Sørensen-Dice over two Bloom filters: 2 * |A AND B| /
    (|A| + |B|). Equivalent to F1 of bit-set-membership across
    the two filters; ranges 0.0 (no shared bits) to 1.0
    (identical filters)."""
    set_a = _count_set_bits(bits_a)
    set_b = _count_set_bits(bits_b)
    if set_a + set_b == 0:
        return Decimal("0")
    intersection = _bitwise_and_count(bits_a, bits_b)
    return Decimal("2") * Decimal(intersection) / Decimal(set_a + set_b)


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _serialize_for_dynamodb(obj):
    """Recursive serialization helper. Same pattern as recipes
    5.1 - 5.7."""
    if isinstance(obj, dict):
        return {k: _serialize_for_dynamodb(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_for_dynamodb(v) for v in obj]
    if isinstance(obj, set):
        return [_serialize_for_dynamodb(v) for v in sorted(obj)]
    if isinstance(obj, (bytes, bytearray)):
        # Bit arrays serialize to base64 for DynamoDB / S3.
        import base64
        return base64.b64encode(bytes(obj)).decode("ascii")
    if isinstance(obj, float):
        return Decimal(str(obj))
    return obj


def _emit_metric(metric_name: str, value: float,
                  dimensions: dict = None) -> None:
    """CloudWatch metric emit. Cohort-bucket-hash dimensions feed
    the cohort-stratified accuracy monitoring; production
    aggregates by CohortBucketHash and alarms on per-cohort
    linkage-rate or false-acceptance-rate disparities."""
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

## Mock Salt Custody, Protocol Parameterization Store, Participant Data Sources, and Governance Layers

Production custodies the salt in CloudHSM (or KMS with customer-managed keys for the lower-assurance pattern) with multi-party generation ceremony, dual-control rotation approval, and audit-logged access. Production reads the protocol parameterization from a versioned configuration store maintained by the multi-party trust framework's governance committee. Production reads source data from each participant's EHR, claims system, or registry under their own access controls. Production reads consent posture and jurisdictional overlays from per-participant policy stores. The demo includes small mocks that exercise the encoding-and-matching pipeline without requiring those external dependencies.

```python
# --- Mock salt custody ---
class MockSaltCustody:
    """Stand-in for AWS CloudHSM (high-assurance) or KMS with
    customer-managed keys (lower-assurance) salt custody. The
    salt is the cryptographic root-of-trust for the protocol;
    the plaintext salt is never exposed to the encoding process
    in production (HMAC operations call into the HSM context).
    The demo uses an in-memory salt for readability; a production
    deployment would never have plaintext salt visible to Python
    application code."""

    def __init__(self):
        # Per-cycle salt-key versions. The active cycle uses the
        # most recent rotation. Prior versions are retained for
        # the catch-up window (where the prior salt remains valid
        # for read-only operations during a coordinated rotation
        # cutover) and then decommissioned.
        self._salt_keys = {
            "salt-2026-q2-rotation-001": secrets.token_bytes(32),
        }
        self._active_version = "salt-2026-q2-rotation-001"
        self._access_log: list = []

    def get_salt(self, salt_key_version: str,
                  caller_role: str, cycle_id: str) -> bytes:
        """Acquire the salt for the given version. Production's
        equivalent never returns plaintext; it returns an HSM
        context that the encoder calls into for HMAC operations."""
        # Dual-control approval would be enforced here in
        # production; the demo logs but does not enforce.
        self._access_log.append({
            "salt_key_version": salt_key_version,
            "caller_role":      caller_role,
            "cycle_id":         cycle_id,
            "operation":        "get_salt",
            "timestamp":        _now_iso(),
        })
        if salt_key_version not in self._salt_keys:
            raise KeyError(
                f"salt_key_version {salt_key_version} not found "
                f"or expired (the cycle's parameterization "
                f"version may reference a salt that has been "
                f"decommissioned; re-encode under the current "
                f"salt and re-run the cycle)")
        return self._salt_keys[salt_key_version]

    def rotate_salt(self, new_version: str,
                     dual_control_approvers: list) -> None:
        """Rotation ceremony. Production requires dual-control
        approval (two HSM operators from non-overlapping
        organizations); rotation is audit-logged with both
        operator identities."""
        if len(dual_control_approvers) < 2:
            raise ValueError(
                "salt rotation requires dual-control approval "
                "(at least two approvers from non-overlapping "
                "organizations)")
        self._salt_keys[new_version] = secrets.token_bytes(32)
        prior_active = self._active_version
        self._active_version = new_version
        self._access_log.append({
            "operation":        "rotate_salt",
            "new_version":      new_version,
            "prior_active":     prior_active,
            "approvers":        dual_control_approvers,
            "timestamp":        _now_iso(),
        })
        # Production keeps the prior salt available for the
        # catch-up window, then decommissions; the demo retains
        # all versions for inspection.

    def get_active_version(self) -> str:
        return self._active_version

    def get_access_log(self) -> list:
        return list(self._access_log)


# --- Mock protocol parameterization store ---
class MockProtocolParameterizationStore:
    """Stand-in for the versioned configuration store. Production
    reads from a DynamoDB table maintained by the multi-party
    trust framework's governance committee. Each linkage cycle
    pins the parameterization version active at the cycle's start
    and references that version throughout. Updates require
    governance approval and trigger coordinated re-encoding."""

    def __init__(self):
        self._configs = {
            PROTOCOL_PARAMETERIZATION_VERSION: dict(PROTOCOL_PARAMETERIZATION),
        }

    def load_parameterization(self, version: str) -> dict:
        if version not in self._configs:
            raise KeyError(
                f"parameterization version {version} not found")
        return dict(self._configs[version])

    def publish_new_version(self, version: str,
                              parameterization: dict) -> None:
        """A new parameterization version goes through governance
        approval before publish. The demo just stores it."""
        self._configs[version] = dict(parameterization)


# --- Mock participant data sources ---
# Each participant's source data is a list of records with
# standardized demographic features, per-record consent posture,
# and (cohort-axis values used for the cohort-axis-hash
# computation). The Catherine / Maria / Margaret patients
# overlap across participants so the matcher has something to
# find; a few non-overlapping records exercise the no-match path.
SYNTHETIC_PARTICIPANT_A_RECORDS = [
    {
        "source_record_id": "academic-mc-mrn-00284271",
        "given_name":   "Catherine",
        "middle_name":  "Marie",
        "family_name":  "Hernandez",
        "dob":          "1985-03-22",
        "address_line": "412 Oak St",
        "zip_code":     "62701",
        "phone":        "+15551234567",
        "ssn_last_4":   "4287",
        "consent_posture": {
            "consent_for_research_linkage":             True,
            "consent_for_outcomes_research_purpose":    True,
            "jurisdictional_overlay_applied":           "post_dobbs_state_overlay_v1",
            "consent_recorded_at":                      "2026-01-15T10:34:22Z",
        },
        "cohort_values": {
            "name_tradition":  "spanish_double_surname",
            "age_decade":      "40s",
            "sex_or_gender":   "F",
        },
    },
    {
        "source_record_id": "academic-mc-mrn-00891344",
        "given_name":   "Maria",
        "middle_name":  None,
        "family_name":  "Garcia-Lopez",
        "dob":          "1972-03-14",
        "address_line": "8810 Maple Ave",
        "zip_code":     "60618",
        "phone":        "+15557654321",
        "ssn_last_4":   "1119",
        "consent_posture": {
            "consent_for_research_linkage":             True,
            "consent_for_outcomes_research_purpose":    True,
            "jurisdictional_overlay_applied":           None,
            "consent_recorded_at":                      "2025-11-04T08:12:11Z",
        },
        "cohort_values": {
            "name_tradition":  "spanish_double_surname",
            "age_decade":      "50s",
            "sex_or_gender":   "F",
        },
    },
    {
        "source_record_id": "academic-mc-mrn-00733215",
        "given_name":   "Margaret",
        "middle_name":  None,
        "family_name":  "Chen-Patel",
        "dob":          "1990-11-04",
        "address_line": "27 Beacon Hill",
        "zip_code":     "02108",
        "phone":        "+15558889999",
        "ssn_last_4":   "9023",
        "consent_posture": {
            "consent_for_research_linkage":             True,
            "consent_for_outcomes_research_purpose":    True,
            "jurisdictional_overlay_applied":           None,
            "consent_recorded_at":                      "2025-10-22T14:55:09Z",
        },
        "cohort_values": {
            "name_tradition":  "east_asian_traditional",
            "age_decade":      "30s",
            "sex_or_gender":   "F",
        },
    },
    {
        "source_record_id": "academic-mc-mrn-00499812",
        "given_name":   "Theodore",
        "middle_name":  "James",
        "family_name":  "Williamson",
        "dob":          "1956-07-29",
        "address_line": "5532 Birch Ln",
        "zip_code":     "02115",
        "phone":        "+15554443333",
        "ssn_last_4":   "2244",
        "consent_posture": {
            "consent_for_research_linkage":             True,
            "consent_for_outcomes_research_purpose":    True,
            "jurisdictional_overlay_applied":           None,
            "consent_recorded_at":                      "2025-09-02T11:20:00Z",
        },
        "cohort_values": {
            "name_tradition":  "english_traditional",
            "age_decade":      "60s",
            "sex_or_gender":   "M",
        },
    },
    {
        "source_record_id": "academic-mc-mrn-00622441",
        # This record has consent withdrawn for research linkage;
        # the encoding step filters it out at standardize time.
        "given_name":   "Patricia",
        "middle_name":  "Anne",
        "family_name":  "Murphy",
        "dob":          "1968-12-15",
        "address_line": "204 Spruce St",
        "zip_code":     "62704",
        "phone":        "+15552223333",
        "ssn_last_4":   "8801",
        "consent_posture": {
            "consent_for_research_linkage":             False,  # withdrawn
            "consent_for_outcomes_research_purpose":    False,
            "jurisdictional_overlay_applied":           None,
            "consent_recorded_at":                      "2025-12-01T16:30:00Z",
        },
        "cohort_values": {
            "name_tradition":  "irish_traditional",
            "age_decade":      "50s",
            "sex_or_gender":   "F",
        },
    },
]

SYNTHETIC_PARTICIPANT_B_RECORDS = [
    {
        # Catherine: matches Participant A's first record. Slight
        # address variation (St. vs Street) tests the encoding's
        # robustness to legitimate-noise variation.
        "source_record_id": "regional-payer-member-MEM-100874-A",
        "given_name":   "Catherine",
        "middle_name":  "Marie",
        "family_name":  "Hernandez",
        "dob":          "1985-03-22",
        "address_line": "412 Oak Street",  # "Street" vs "St"
        "zip_code":     "62701",
        "phone":        "+15551234567",
        "ssn_last_4":   "4287",
        "consent_posture": {
            "consent_for_research_linkage":             True,
            "consent_for_outcomes_research_purpose":    True,
            "jurisdictional_overlay_applied":           "post_dobbs_state_overlay_v1",
            "consent_recorded_at":                      "2026-01-22T09:18:44Z",
        },
        "cohort_values": {
            "name_tradition":  "spanish_double_surname",
            "age_decade":      "40s",
            "sex_or_gender":   "F",
        },
    },
    {
        # Maria: matches Participant A's second record exactly.
        "source_record_id": "regional-payer-member-MEM-303441-C",
        "given_name":   "Maria",
        "middle_name":  None,
        "family_name":  "Garcia-Lopez",
        "dob":          "1972-03-14",
        "address_line": "8810 Maple Ave",
        "zip_code":     "60618",
        "phone":        "+15557654321",
        "ssn_last_4":   "1119",
        "consent_posture": {
            "consent_for_research_linkage":             True,
            "consent_for_outcomes_research_purpose":    True,
            "jurisdictional_overlay_applied":           None,
            "consent_recorded_at":                      "2025-11-15T14:00:00Z",
        },
        "cohort_values": {
            "name_tradition":  "spanish_double_surname",
            "age_decade":      "50s",
            "sex_or_gender":   "F",
        },
    },
    {
        # Margaret: matches Participant A's third record, with a
        # phone-number variation that tests the matcher's
        # robustness to feature-level noise.
        "source_record_id": "regional-payer-member-MEM-440412-D",
        "given_name":   "Margaret",
        "middle_name":  None,
        "family_name":  "Chen-Patel",
        "dob":          "1990-11-04",
        "address_line": "27 Beacon Hill",
        "zip_code":     "02108",
        "phone":        "+15558880000",  # phone differs
        "ssn_last_4":   "9023",
        "consent_posture": {
            "consent_for_research_linkage":             True,
            "consent_for_outcomes_research_purpose":    True,
            "jurisdictional_overlay_applied":           None,
            "consent_recorded_at":                      "2025-11-08T10:45:30Z",
        },
        "cohort_values": {
            "name_tradition":  "east_asian_traditional",
            "age_decade":      "30s",
            "sex_or_gender":   "F",
        },
    },
    {
        # Non-overlapping member: no match in Participant A.
        "source_record_id": "regional-payer-member-MEM-521098-X",
        "given_name":   "Robert",
        "middle_name":  None,
        "family_name":  "Andersen",
        "dob":          "1948-05-30",
        "address_line": "11 Pine St",
        "zip_code":     "10025",
        "phone":        "+15556667777",
        "ssn_last_4":   "0066",
        "consent_posture": {
            "consent_for_research_linkage":             True,
            "consent_for_outcomes_research_purpose":    True,
            "jurisdictional_overlay_applied":           None,
            "consent_recorded_at":                      "2025-08-15T13:00:00Z",
        },
        "cohort_values": {
            "name_tradition":  "scandinavian_traditional",
            "age_decade":      "70s",
            "sex_or_gender":   "M",
        },
    },
]


# --- Mock consent and jurisdictional-overlay store ---
class MockConsentStore:
    """Stand-in for the institutional consent-management workflow.
    Per-record consent posture is captured at intake and updated
    over time; the encoding step's standardize-and-prepare phase
    consults this store to filter out records the patient has
    not consented to include in this specific linkage."""

    def __init__(self):
        self._withdrawals: dict = {}  # source_record_id -> withdrawn_at

    def is_consent_active(self, record: dict, purpose: str) -> bool:
        """Return whether the record's consent posture permits
        inclusion for the specified purpose. The demo's logic is
        simple; production has a structured policy engine."""
        sid = record.get("source_record_id")
        if sid in self._withdrawals:
            return False
        consent = record.get("consent_posture") or {}
        if purpose == "research_linkage":
            return bool(consent.get("consent_for_research_linkage"))
        if purpose == "outcomes_research":
            return bool(consent.get("consent_for_outcomes_research_purpose"))
        return False

    def withdraw_consent(self, source_record_id: str) -> None:
        """Patient withdraws consent. Forward-only: future cycles
        exclude the record; prior cycles' results remain in the
        consumer's possession."""
        self._withdrawals[source_record_id] = _now_iso()


class MockJurisdictionalOverlays:
    """Stand-in for the institutional policy-overlay store.
    Real deployments encode state law (post-Dobbs reproductive-
    health-care state laws, 42 CFR Part 2 substance-use-treatment
    rules, gender-affirming-care state-law overlays, HIV-and-
    genetic-information rules), institutional policy, and trust-
    framework constraints with attorney-reviewed rules."""

    def applicable_overlays(self, record: dict, purpose: str) -> list:
        overlays = []
        consent = record.get("consent_posture") or {}
        applied = consent.get("jurisdictional_overlay_applied")
        if applied:
            overlays.append({
                "overlay_id":  applied,
                "applies_to":  purpose,
                "constraints": {
                    "audit_every_disclosure": True,
                    "audit_every_query":      True,
                },
            })
        return overlays


# --- Module-level singletons for the demo ---
salt_custody                 = MockSaltCustody()
protocol_config_store        = MockProtocolParameterizationStore()
consent_store                = MockConsentStore()
jurisdictional_overlays_db   = MockJurisdictionalOverlays()
_IN_MEMORY_OUTBOX:           list = []
_IN_MEMORY_REVIEW_QUEUE:     list = []
_IN_MEMORY_LINKAGE_RESULTS:  list = []
_IN_MEMORY_PARTICIPANT_LOCAL_MAPPINGS: dict = {}
# Cohort-axis hash key. Production loads this from Secrets
# Manager and rotates separately from the salt; the demo uses a
# fixed value for reproducibility.
_COHORT_AXIS_HASH_KEY = b"demo-cohort-axis-hash-key-not-for-production"
```

---

## Step 1: Standardize and Prepare the Per-Participant Demographic-Feature Set

*The pseudocode calls this `standardize_and_prepare(source_record_batch, participant_id, consent_filter_policy, cohort_axis_specification)`. Every participating organization standardizes its demographic features under the same schema before encoding. The standardization is the same work that a conventional matcher does (case-folding, whitespace stripping, USPS address standardization, diacritic folding) but it has to be deterministic and cross-participant-compatible because any divergence in standardization produces encoded records that the matcher cannot reliably compare. Skip the standardization step and the encoding produces records whose Bloom filters carry the institution's idiosyncratic demographic-feature representation rather than the cross-participant-compatible representation, and the linkage rate drops substantially.*

```python
def _normalize_address(address: str) -> str:
    """USPS-style standardization (light version). Production uses
    a real USPS-CASS-certified standardizer; the demo handles a
    few common variants. The address standardization spec is part
    of the protocol parameterization and is identical across all
    participants."""
    if not address:
        return ""
    s = address.strip()
    # Common abbreviation expansions (standardize TO the
    # abbreviated form so participants converge on the same
    # representation; production picks one canonical form).
    replacements = [
        (r"\bStreet\b",  "St"),
        (r"\bAvenue\b",  "Ave"),
        (r"\bBoulevard\b", "Blvd"),
        (r"\bDrive\b",   "Dr"),
        (r"\bLane\b",    "Ln"),
        (r"\bRoad\b",    "Rd"),
        (r"\bCourt\b",   "Ct"),
        (r"\bApartment\b", "Apt"),
        (r"\bSuite\b",   "Ste"),
    ]
    for pattern, repl in replacements:
        s = re.sub(pattern, repl, s, flags=re.IGNORECASE)
    return _canonical_name(s)


def _normalize_phone(phone: str) -> str:
    """Strip non-digit characters and (for the demo) keep the
    last 10 digits. Production handles country codes, extensions,
    and the e164 canonical form."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    return digits[-10:] if len(digits) >= 10 else digits


def _compute_cohort_axis_hashes(record: dict,
                                  cohort_axes: list,
                                  hash_key: bytes) -> dict:
    """Each participant computes its own cohort-axis values
    locally and contributes the hashes (not the values) in the
    encoded payload. The matcher receives the hashes and can
    stratify accuracy metrics by hash without learning the
    underlying axis values."""
    cohort_values = record.get("cohort_values") or {}
    hashes = {}
    for axis in cohort_axes:
        value = cohort_values.get(axis, "unknown")
        # HMAC the axis-name + value under the hash key so the
        # cohort-axis-hash space is per-axis disjoint (a
        # 'name_tradition' hash cannot collide with a 'sex_or_gender'
        # hash for the same value).
        h = _hmac_sha_256(hash_key,
                            f"{axis}:{value}".encode("utf-8"))
        hashes[f"{axis}_hash"] = h.hex()[:16]
    return hashes


def standardize_and_prepare(source_record_batch: list,
                              participant_id: str,
                              purpose: str,
                              parameterization: dict) -> list:
    """
    Apply the protocol's shared schema to each source record.
    Filter out records whose consent posture does not permit
    inclusion. Compute cohort-axis hashes locally. Return the
    standardized batch ready for encoding.
    """
    standardized = []
    filtered_count = 0

    for source_record in source_record_batch:
        # 1A: apply the consent and purpose-of-use filter.
        if not consent_store.is_consent_active(source_record, purpose):
            filtered_count += 1
            continue

        # 1B: standardize each demographic feature under the
        # protocol's shared schema. Every participant runs this
        # exact same canonicalization; any divergence produces
        # encoded records that the matcher cannot reliably
        # compare.
        normalized = {
            "given_name":   _canonical_name(
                source_record.get("given_name")),
            "middle_name":  _canonical_name(
                source_record.get("middle_name") or ""),
            "family_name":  _canonical_name(
                source_record.get("family_name")),
            "dob":          (source_record.get("dob") or "").strip(),
            "address_line": _normalize_address(
                source_record.get("address_line") or ""),
            "zip_code":     re.sub(
                r"\D", "",
                source_record.get("zip_code") or "")[:5],
            "phone":        _normalize_phone(
                source_record.get("phone") or ""),
            "ssn_last_4":   re.sub(
                r"\D", "",
                source_record.get("ssn_last_4") or "")[-4:],
        }

        # 1C: compute cohort-axis hashes locally.
        cohort_axis_hashes = _compute_cohort_axis_hashes(
            source_record, COHORT_AXES, _COHORT_AXIS_HASH_KEY)

        # 1D: tag with metadata. The source_record_id is retained
        # locally at the participant; it is NOT included in the
        # encoded payload that gets exchanged.
        prepared_record = {
            "participant_id":      participant_id,
            "source_record_id":    source_record["source_record_id"],
            "normalized_features": normalized,
            "consent_posture":     dict(source_record.get(
                                        "consent_posture") or {}),
            "cohort_axis_hashes":  cohort_axis_hashes,
            "applicable_overlays": jurisdictional_overlays_db
                                     .applicable_overlays(
                                         source_record, purpose),
            "prepared_at":         _now_iso(),
        }
        standardized.append(prepared_record)

    _emit_metric("StandardizeAndPrepare.Filtered",
                  float(filtered_count),
                  dimensions={"ParticipantId": participant_id,
                                "Purpose":      purpose})
    _emit_metric("StandardizeAndPrepare.Prepared",
                  float(len(standardized)),
                  dimensions={"ParticipantId": participant_id,
                                "Purpose":      purpose})
    return standardized
```

---

## Step 2: Apply the Cryptographic Encoding Under the Pinned Protocol Parameterization

*The pseudocode calls this `encode_record(prepared_record, parameterization_version)`. The encoding step is per-participant; it transforms the standardized record into a Cryptographic-Long-Term-Key (CLK) encoded form. The CLK is a single Bloom filter that combines the per-feature Bloom filters under the per-feature bit allocation. The matcher consumes the CLK without seeing the underlying demographic features. Skip the parameterization-version pinning and you produce encoded records that are not comparable to the counterparty's records produced under a different parameterization version, and the linkage silently fails.*

```python
def _encode_per_feature_bloom_filter(value: str,
                                          feature_name: str,
                                          parameterization: dict,
                                          salt: bytes) -> bytearray:
    """Produce a per-feature Bloom filter for a single
    demographic feature value. The per-feature filter size is
    derived from the parameterization's per-feature bit
    allocation; n-grams are tokenized; each n-gram is hashed by
    k cryptographic hash functions parameterized by the salt;
    the resulting bit positions are set in the filter."""
    per_feature_size = _compute_per_feature_size(
        parameterization, feature_name)
    if per_feature_size == 0:
        return bytearray(0)

    feature_filter = _bit_array(per_feature_size)

    if not value:
        # Missing feature gets an empty filter; the matcher's
        # Fellegi-Sunter combiner handles missing-feature cases
        # under specific weights. Production has explicit
        # missing-feature sentinel handling; the demo uses an
        # empty filter as the simplest stand-in.
        return feature_filter

    # Tokenize into n-grams.
    n_grams = _produce_n_grams(
        value, n=parameterization["n_gram_size"],
        include_markers=True)

    # Hash each n-gram by k functions and set the bit positions.
    k = parameterization["hash_function_count"]
    for n_gram in n_grams:
        for k_index in range(k):
            position = _hash_to_bit_position(
                salt, k_index, n_gram, per_feature_size)
            _set_bit(feature_filter, position)

    return feature_filter


def _combine_per_feature_filters(per_feature_filters: dict,
                                      parameterization: dict) -> bytearray:
    """Combine the per-feature filters into the record-level
    CLK by concatenation in a fixed order. Production uses a more
    sophisticated combination scheme (interleaving with random
    hashing) that the simple concatenation in the demo
    illustrates the structure of."""
    total_size = parameterization["bloom_filter_size"]
    clk = _bit_array(total_size)
    cursor = 0
    # Iterate features in a deterministic order so all participants
    # produce comparable CLKs.
    for feature_name in sorted(parameterization[
                                    "per_feature_bit_allocation"].keys()):
        feature_size = _compute_per_feature_size(
            parameterization, feature_name)
        feature_filter = per_feature_filters.get(
            feature_name, _bit_array(feature_size))
        # Copy the feature filter's bits into the CLK at cursor.
        for i in range(feature_size):
            if cursor + i >= total_size:
                break
            if _is_bit_set(feature_filter, i):
                _set_bit(clk, cursor + i)
        cursor += feature_size
    return clk


def encode_record(prepared_record: dict,
                     parameterization_version: str,
                     salt_key_version: str,
                     cycle_id: str) -> dict:
    """
    Produce the encoded-record envelope. The envelope carries
    the CLK plus the metadata the matcher needs (participant_id,
    encoded_record_id, consent_posture, cohort_axis_hashes,
    parameterization_version) but does not carry the normalized
    demographics or the source-record identifier.
    """
    # 2A: load the pinned parameterization.
    parameterization = protocol_config_store.load_parameterization(
        parameterization_version)

    # 2B: load the salt key for this cycle. Production's
    # equivalent never returns plaintext; it returns an HSM
    # context that the encoder calls into for HMAC operations.
    salt = salt_custody.get_salt(
        salt_key_version, caller_role="encoder", cycle_id=cycle_id)

    # 2C: produce the per-feature Bloom filters.
    per_feature_filters = {}
    normalized = prepared_record["normalized_features"]
    for feature_name in parameterization[
                            "per_feature_bit_allocation"].keys():
        value = normalized.get(feature_name, "")
        per_feature_filters[feature_name] = (
            _encode_per_feature_bloom_filter(
                value, feature_name, parameterization, salt))

    # 2D: combine into the record-level CLK.
    clk = _combine_per_feature_filters(
        per_feature_filters, parameterization)

    # 2E: build the encoded-record envelope. Generate a per-cycle
    # pseudonym for the encoded_record_id so it cannot be
    # correlated across cycles by an observer; the participant
    # retains the source_record_id-to-encoded_record_id mapping
    # locally for its own lookups.
    encoded_record_id = (
        f"enc-{cycle_id}-"
        f"{prepared_record['participant_id'][:1]}-"
        f"{uuid.uuid4().hex[:12]}")

    encoded_record_envelope = {
        "participant_id":          prepared_record["participant_id"],
        "encoded_record_id":       encoded_record_id,
        "clk_payload":             bytes(clk),  # serialized as base64 in DDB/S3
        "per_feature_filters":     {  # retained for per-feature scoring
            f: bytes(filt) for f, filt in per_feature_filters.items()
        },
        "consent_posture":         prepared_record["consent_posture"],
        "cohort_axis_hashes":      prepared_record["cohort_axis_hashes"],
        "applicable_overlays":     prepared_record["applicable_overlays"],
        "parameterization_version": parameterization_version,
        "salt_key_version":        salt_key_version,
        "cycle_id":                cycle_id,
        "encoded_at":              _now_iso(),
    }

    # 2F: persist the per-cycle local mapping from the
    # encoded_record_id to the source_record_id. The mapping is
    # retained at the participant only; it is never included in
    # the encoded-record envelope or the cross-participant
    # exchange. The mapping enables the participant to later
    # resolve match results back to the source records under its
    # own access controls.
    _IN_MEMORY_PARTICIPANT_LOCAL_MAPPINGS.setdefault(
        prepared_record["participant_id"], {}
    )[encoded_record_id] = {
        "cycle_id":          cycle_id,
        "source_record_id":  prepared_record["source_record_id"],
        "encoded_at":        encoded_record_envelope["encoded_at"],
    }

    return encoded_record_envelope


def encode_batch(prepared_records: list,
                   parameterization_version: str,
                   salt_key_version: str,
                   cycle_id: str) -> list:
    """Bulk-encode a batch of prepared records. Production runs
    this in a Glue job with Spark partitioning; the demo iterates
    in-process."""
    encoded = [encode_record(r, parameterization_version,
                              salt_key_version, cycle_id)
                for r in prepared_records]
    _emit_metric("EncodedRecords", float(len(encoded)),
                  dimensions={"ParticipantId":
                                  prepared_records[0]["participant_id"]
                                  if prepared_records else "unknown",
                                "CycleId": cycle_id})
    return encoded
```

---

## Step 3: Exchange the Encoded Records Under the Trust Architecture

*The pseudocode calls this `exchange_encoded_records(encoded_record_envelopes, trust_architecture_config, cycle_id)`. The participating organizations deliver their encoded payloads to the linkage-execution endpoint. The exchange is the trust-architecture-defining step; the choice of transport, authentication, and audit posture reflects the protocol's specific privacy claims. Skip the exchange-time auditing and the protocol's audit posture is broken: a counterparty that uploaded an encoded payload cannot prove what it uploaded if the linkage's results are later disputed.*

```python
def exchange_encoded_records(encoded_record_envelopes: list,
                                  participant_id: str,
                                  cycle_id: str,
                                  trust_architecture: str = "linkage_broker_model"
                                  ) -> dict:
    """
    Validate that every envelope in the batch was produced under
    the parameterization and salt-key versions pinned for this
    cycle. Route to the linkage-execution endpoint per the trust
    architecture. Log the exchange to the participant's audit
    store.

    The demo runs all participants in one process so the
    "exchange" is logically rather than physically separate;
    production exchanges across AWS accounts and (often)
    organizational boundaries with cross-account bucket policies,
    PrivateLink, and mTLS.
    """
    # 3A: validate that every envelope's parameterization and
    # salt-key version match the cycle's pinned versions.
    # Mis-coordinated versions are the most common operational
    # failure mode for PPRL; catch them at exchange time before
    # the matcher silently returns zero matches.
    cycle_metadata = _IN_MEMORY_CYCLE_METADATA.get(cycle_id)
    if not cycle_metadata:
        raise RuntimeError(
            f"cycle metadata for {cycle_id} not found; "
            f"cycle must be initialized before exchange")

    expected_param_version = cycle_metadata["parameterization_version"]
    expected_salt_version  = cycle_metadata["salt_key_version"]

    for envelope in encoded_record_envelopes:
        if envelope["parameterization_version"] != expected_param_version:
            raise ValueError(
                f"parameterization mismatch for "
                f"{envelope['encoded_record_id']}: envelope "
                f"version {envelope['parameterization_version']} "
                f"does not match cycle's pinned version "
                f"{expected_param_version}. This is the silent-"
                f"failure mode the version-pinning is designed "
                f"to catch; do not proceed.")
        if envelope["salt_key_version"] != expected_salt_version:
            raise ValueError(
                f"salt-key mismatch for "
                f"{envelope['encoded_record_id']}: envelope "
                f"version {envelope['salt_key_version']} "
                f"does not match cycle's pinned version "
                f"{expected_salt_version}. The cycle's salt-key "
                f"version may have rotated mid-cycle; re-encode "
                f"under the active salt and re-run the cycle.")

    # 3B: route the envelopes to the linkage-execution endpoint
    # per the trust architecture. The demo's
    # _IN_MEMORY_EXCHANGE_BUCKET stands in for the cross-account
    # S3 buckets in the linkage-broker model, the tokenizer
    # ingestion endpoint in the tokenizer model, the Nitro
    # Enclave attested endpoint in the TEE model, or the SMPC
    # protocol runner in the SMPC model.
    bucket_for_participant = {
        "participant-A": PARTICIPANT_A_BUCKET,
        "participant-B": PARTICIPANT_B_BUCKET,
    }.get(participant_id, "unknown-bucket")

    transport_metadata = {
        "trust_architecture":  trust_architecture,
        "destination_bucket":  bucket_for_participant,
        "envelope_count":      len(encoded_record_envelopes),
    }

    # In production, upload to S3 with mTLS-and-cross-account
    # bucket policies. The demo just appends to the in-memory
    # exchange bucket.
    _IN_MEMORY_EXCHANGE_BUCKET[cycle_id].setdefault(
        participant_id, []).extend(encoded_record_envelopes)

    # 3C: log the exchange to the participant's audit store.
    audit_log_entry = {
        "event_type":              "PPRL_EXCHANGE",
        "cycle_id":                cycle_id,
        "participant_id":          participant_id,
        "parameterization_version": expected_param_version,
        "salt_key_version":        expected_salt_version,
        "record_count":            len(encoded_record_envelopes),
        "trust_architecture":      trust_architecture,
        "destination":             bucket_for_participant,
        "exchanged_at":            _now_iso(),
    }
    _archive_to_s3(audit_log_entry, AUDIT_ARCHIVE_BUCKET,
                     f"exchange-events/{cycle_id}",
                     key_id=f"{participant_id}-exchange")

    _emit_metric("ExchangeCompleted", 1.0,
                  dimensions={"ParticipantId":     participant_id,
                                "CycleId":           cycle_id,
                                "TrustArchitecture": trust_architecture})

    return transport_metadata


# In-memory exchange surface. Production replaces with cross-
# account S3 buckets behind PrivateLink endpoints.
_IN_MEMORY_EXCHANGE_BUCKET: dict = {}
_IN_MEMORY_CYCLE_METADATA:  dict = {}
```

---

## Step 4: Match the Encoded Records Under the Protocol's Matching Function

*The pseudocode calls this `match_encoded_records(encoded_record_sets, parameterization, threshold_calibration, cohort_axis_specification)`. The matcher operates on the encoded data without ever seeing the underlying demographics. The matching function is protocol-specific: Sørensen-Dice for Bloom filters, equality for tokenized data, the SMPC primitives for the SMPC family. The thresholds are calibrated separately from the conventional matcher's thresholds because the encoded scoring function is different. Skip the encoded-data threshold calibration and you re-use the conventional thresholds, which produces silent linkage failures because the encoded similarity scores are systematically lower for the same underlying record pair.*

```python
def _candidate_pairs(encoded_records_a: list,
                       encoded_records_b: list) -> list:
    """Generate candidate pairs for matching. Production uses
    locality-sensitive hashing on the CLK to reduce O(n*m) to a
    tractable subset; the demo iterates the full Cartesian
    product because the demo population is small."""
    return [(a, b) for a in encoded_records_a
                    for b in encoded_records_b]


def _per_feature_bloom_filter_from_envelope(envelope: dict,
                                                  feature_name: str
                                                  ) -> bytearray:
    """Pull the per-feature filter from the encoded envelope.
    Production stores the per-feature filters separately so the
    matcher can do per-feature similarity scoring; the demo
    keeps them on the envelope."""
    raw = envelope["per_feature_filters"].get(feature_name)
    return bytearray(raw) if raw else bytearray(0)


def _compute_per_feature_similarities(envelope_a: dict,
                                          envelope_b: dict,
                                          parameterization: dict
                                          ) -> dict:
    """Per-feature Sørensen-Dice similarity. Each feature's
    Bloom filter is compared independently; the Fellegi-Sunter
    combiner then weights them."""
    similarities = {}
    for feature_name in parameterization[
                              "per_feature_bit_allocation"].keys():
        filter_a = _per_feature_bloom_filter_from_envelope(
            envelope_a, feature_name)
        filter_b = _per_feature_bloom_filter_from_envelope(
            envelope_b, feature_name)
        if len(filter_a) == 0 and len(filter_b) == 0:
            similarities[feature_name] = Decimal("0.5")  # missing both
        elif len(filter_a) == 0 or len(filter_b) == 0:
            similarities[feature_name] = Decimal("0.0")  # one missing
        else:
            similarities[feature_name] = _sorensen_dice_coefficient(
                filter_a, filter_b)
    return similarities


def _combine_with_fellegi_sunter(per_feature_similarities: dict,
                                      feature_weights: dict) -> Decimal:
    """Weighted sum across per-feature similarities. The
    production Fellegi-Sunter implementation uses log-likelihood
    ratios with EM-trained per-feature m-and-u parameters; the
    demo uses a simpler weighted-average that illustrates the
    structure without the parameter-estimation complexity."""
    total_weight = Decimal("0")
    weighted_sum = Decimal("0")
    for feature_name, similarity in per_feature_similarities.items():
        weight = feature_weights.get(feature_name, Decimal("0"))
        weighted_sum += weight * similarity
        total_weight += weight
    if total_weight == 0:
        return Decimal("0")
    return weighted_sum / total_weight


def match_encoded_records(encoded_records_a: list,
                              encoded_records_b: list,
                              cycle_id: str,
                              parameterization_version: str
                              ) -> list:
    """
    Compute pairwise similarity between encoded records under
    the protocol's matching function. Apply the encoded-data
    thresholds. Return the list of match decisions.
    """
    parameterization = protocol_config_store.load_parameterization(
        parameterization_version)

    # 4A: candidate generation.
    candidates = _candidate_pairs(encoded_records_a, encoded_records_b)

    match_results = []
    for record_a, record_b in candidates:
        # 4B: per-feature similarity.
        per_feature_similarities = _compute_per_feature_similarities(
            record_a, record_b, parameterization)

        # 4C: Fellegi-Sunter combination.
        match_score = _combine_with_fellegi_sunter(
            per_feature_similarities, FEATURE_WEIGHTS)

        # 4D: apply encoded-data thresholds.
        if match_score >= ENCODED_MATCH_HIGH_THRESHOLD:
            decision = "MATCH_HIGH"
        elif match_score >= ENCODED_MATCH_MED_THRESHOLD:
            decision = "MATCH_MED_REVIEW"
        elif match_score <= ENCODED_REJECT_THRESHOLD:
            decision = "REJECT"
        else:
            decision = "REVIEW"

        # 4E: build the per-pair result with evidence summary
        # and cohort-axis hashes for downstream cohort-stratified-
        # accuracy monitoring. Note: the result carries no
        # demographic features; just the encoded_record_ids and
        # the cohort-axis hashes.
        match_result = {
            "cycle_id":               cycle_id,
            "match_id":               f"match-{cycle_id}-"
                                       f"{uuid.uuid4().hex[:12]}",
            "participant_a_id":       record_a["participant_id"],
            "participant_b_id":       record_b["participant_id"],
            "encoded_record_a_id":    record_a["encoded_record_id"],
            "encoded_record_b_id":    record_b["encoded_record_id"],
            "match_score":            match_score,
            "decision":               decision,
            "evidence_summary": {
                "per_feature_similarities":  per_feature_similarities,
                "feature_weights_version":   MATCHER_CONFIG_VERSION,
            },
            "cohort_axis_hashes_a":   record_a["cohort_axis_hashes"],
            "cohort_axis_hashes_b":   record_b["cohort_axis_hashes"],
            "consent_posture_a":      record_a["consent_posture"],
            "consent_posture_b":      record_b["consent_posture"],
            "applicable_overlays_a":  record_a.get("applicable_overlays") or [],
            "applicable_overlays_b":  record_b.get("applicable_overlays") or [],
            "parameterization_version": parameterization_version,
            "matched_at":             _now_iso(),
        }
        match_results.append(match_result)

        # Cohort-stratified metric emit. The CohortBucketHash
        # dimension is what makes per-cohort linkage-rate
        # disparity monitoring possible without the matcher
        # learning the underlying axis values.
        cohort_hash = record_a["cohort_axis_hashes"].get(
            "name_tradition_hash", "unknown")
        _emit_metric("MatchDecision", 1.0,
                      dimensions={"Decision":         decision,
                                    "CohortBucketHash": cohort_hash[:8],
                                    "CycleId":          cycle_id})

    return match_results
```

---

## Step 5: Apply the Disclosure Policy and Route the Linkage Results

*The pseudocode calls this `disclose_linkage_results(match_results, disclosure_policy, cycle_id)`. The matcher produces match decisions; the disclosure step transforms the decisions into the form the protocol authorizes for delivery to the consumer. The disclosure form is protocol-specific: per-record yes/no flags, intersection counts, encrypted match indicators, k-anonymous summaries, differentially-private aggregates. Skip the disclosure-policy step and you deliver the per-record matches to a consumer that the protocol authorized only for aggregate-level disclosure, which is a privacy violation that the audit cannot retract.*

```python
def _filter_by_consent(match_results: list, purpose: str) -> list:
    """Drop matches whose consent posture does not permit
    inclusion in this disclosure. Records that the patient has
    not consented to include in this specific use case are
    excluded from the disclosure even if the matcher scored a
    match."""
    filtered = []
    for match_result in match_results:
        consent_a = match_result.get("consent_posture_a") or {}
        consent_b = match_result.get("consent_posture_b") or {}
        if purpose == "research_linkage":
            if (consent_a.get("consent_for_research_linkage")
                    and consent_b.get("consent_for_research_linkage")):
                filtered.append(match_result)
        elif purpose == "outcomes_research":
            if (consent_a.get("consent_for_outcomes_research_purpose")
                    and consent_b.get("consent_for_outcomes_research_purpose")):
                filtered.append(match_result)
        else:
            filtered.append(match_result)
    return filtered


def _build_per_record_match_flags(matches: list,
                                       target_consumer: str) -> dict:
    """Per-record disclosure form: each consumer receives the
    match flags for its own records. The consumer is a
    participating organization and can only see matches
    involving its own records; this filter is enforced here."""
    if target_consumer == "participant-A":
        a_side_matches = [
            {
                "encoded_record_a_id":     m["encoded_record_a_id"],
                "matched_with_participant_id": m["participant_b_id"],
                "match_decision":          m["decision"],
                "match_score":             m["match_score"],
            }
            for m in matches
            if m["decision"] in {"MATCH_HIGH", "MATCH_MED_REVIEW"}
                and m["participant_a_id"] == "participant-A"
        ]
        return {
            "matches":                       a_side_matches,
            "total_records_contributed_by_a":
                len(set(m["encoded_record_a_id"] for m in matches
                          if m["participant_a_id"] == "participant-A")),
            "total_matches_for_a":           len(a_side_matches),
        }
    if target_consumer == "participant-B":
        b_side_matches = [
            {
                "encoded_record_b_id":     m["encoded_record_b_id"],
                "matched_with_participant_id": m["participant_a_id"],
                "match_decision":          m["decision"],
                "match_score":             m["match_score"],
            }
            for m in matches
            if m["decision"] in {"MATCH_HIGH", "MATCH_MED_REVIEW"}
                and m["participant_b_id"] == "participant-B"
        ]
        return {
            "matches":                       b_side_matches,
            "total_records_contributed_by_b":
                len(set(m["encoded_record_b_id"] for m in matches
                          if m["participant_b_id"] == "participant-B")),
            "total_matches_for_b":           len(b_side_matches),
        }
    return {"matches": [], "note": "unknown target consumer"}


def _build_intersection_count(matches: list) -> dict:
    """Intersection-count disclosure form: only the size of the
    intersection (no per-record detail). Used when the protocol
    authorizes only the count, e.g., for public-health
    surveillance scenarios where the analytic question is
    'how many people are in both populations?' rather than
    'which specific people?'"""
    confirmed_matches = [m for m in matches
                          if m["decision"] == "MATCH_HIGH"]
    a_count = len(set(m["encoded_record_a_id"]
                        for m in confirmed_matches))
    b_count = len(set(m["encoded_record_b_id"]
                        for m in confirmed_matches))
    return {
        "intersection_count":  len(confirmed_matches),
        "participant_a_total": len(set(m["encoded_record_a_id"]
                                          for m in matches)),
        "participant_b_total": len(set(m["encoded_record_b_id"]
                                          for m in matches)),
        "match_rate_lower_bound":
            float(Decimal(a_count)
                    / Decimal(max(len(set(m["encoded_record_a_id"]
                                            for m in matches)), 1))),
        "match_rate_upper_bound":
            float(Decimal(b_count)
                    / Decimal(max(len(set(m["encoded_record_b_id"]
                                            for m in matches)), 1))),
    }


def _build_k_anonymous_aggregate(matches: list,
                                      k_parameter: int,
                                      suppression_threshold: int
                                      ) -> dict:
    """K-anonymous aggregate disclosure form: cohort-level
    aggregates with small-cell suppression. Used when the
    protocol authorizes only cohort summaries, e.g., for ACO
    out-of-network ED visit reporting where the consumer needs
    cohort-stratified visit counts but not per-patient detail."""
    confirmed_matches = [m for m in matches
                          if m["decision"] == "MATCH_HIGH"]

    # Aggregate by cohort axis hash (not the underlying values;
    # the matcher does not have visibility into them).
    by_cohort: dict = {}
    for match_result in confirmed_matches:
        bucket_hash = match_result["cohort_axis_hashes_a"].get(
            "name_tradition_hash", "unknown")[:8]
        by_cohort.setdefault(bucket_hash, 0)
        by_cohort[bucket_hash] += 1

    aggregates = []
    for bucket_hash, count in sorted(by_cohort.items()):
        if count < suppression_threshold:
            aggregates.append({
                "cohort_axis_hash_prefix": bucket_hash,
                "patient_count_aggregate": "[suppressed: cell size below threshold]",
            })
        else:
            aggregates.append({
                "cohort_axis_hash_prefix": bucket_hash,
                "patient_count_aggregate": count,
            })
    return {
        "k_anonymity_parameter":  k_parameter,
        "suppression_threshold":  suppression_threshold,
        "cohort_aggregates":      aggregates,
    }


def disclose_linkage_results(match_results: list,
                                  cycle_id: str,
                                  disclosure_form: str,
                                  target_consumer: str,
                                  purpose: str = "research_linkage",
                                  k_parameter: int = DEFAULT_K_ANONYMITY,
                                  suppression_threshold: int = DEFAULT_SUPPRESSION_THRESHOLD
                                  ) -> dict:
    """
    Apply the disclosure-policy form and route the linkage
    results to the target consumer. Emit the cycle-completion
    event for cross-recipe consumers.
    """
    # 5A: filter by consent posture.
    consent_filtered = _filter_by_consent(match_results, purpose)
    consent_filtered_count = len(consent_filtered)
    consent_dropped = len(match_results) - consent_filtered_count

    # 5B: apply the disclosure-form transformation.
    if disclosure_form == "per_record_match_flags":
        envelope_payload = _build_per_record_match_flags(
            consent_filtered, target_consumer)
    elif disclosure_form == "intersection_count":
        envelope_payload = _build_intersection_count(consent_filtered)
    elif disclosure_form == "k_anonymous_aggregate":
        envelope_payload = _build_k_anonymous_aggregate(
            consent_filtered, k_parameter, suppression_threshold)
    elif disclosure_form not in DISCLOSURE_FORMS:
        raise ValueError(
            f"unknown disclosure_form {disclosure_form}; "
            f"authorized forms: {sorted(DISCLOSURE_FORMS)}")
    else:
        envelope_payload = {
            "note": f"disclosure_form {disclosure_form} not "
                     f"implemented in demo; production uses real "
                     f"DP / encryption primitives"
        }

    disclosure_envelope = {
        "cycle_id":          cycle_id,
        "disclosure_form":   disclosure_form,
        "target_consumer":   target_consumer,
        "purpose":           purpose,
        "envelope_payload":  envelope_payload,
        "consent_dropped":   consent_dropped,
        "disclosed_at":      _now_iso(),
    }

    # 5C: route to the target consumer. Production uses signed
    # envelopes with mTLS; the demo logs the routing.
    logger.info("disclosure routed",
                  extra={"target_consumer": target_consumer,
                          "disclosure_form": disclosure_form})

    # 5D: emit the cycle-completion event for cross-recipe
    # consumers.
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "privacy-preserving-record-linkage",
            "DetailType":   "pprl_linkage_cycle_completed",
            "EventBusName": PPRL_EVENT_BUS_NAME,
            "Detail": json.dumps({
                "cycle_id":          cycle_id,
                "disclosure_form":   disclosure_form,
                "target_consumer":   target_consumer,
                "matched_pair_count":
                    len([m for m in consent_filtered
                          if m["decision"] == "MATCH_HIGH"]),
                "review_pair_count":
                    len([m for m in consent_filtered
                          if m["decision"] == "MATCH_MED_REVIEW"]),
                "disclosed_at":      _now_iso(),
            }, default=str),
        }])
    except Exception as exc:
        logger.info("event emit skipped (demo mode is fine to ignore)",
                     extra={"error": str(exc)})

    # 5E: log the disclosure to the audit archive. The audit log
    # captures the disclosure-form, the target-consumer, the
    # per-record count, and the cohort-stratified-accuracy
    # summary, but does NOT log the actual disclosure payload
    # (which would duplicate the consumer's copy).
    audit_entry = {
        "event_type":        "PPRL_DISCLOSURE",
        "cycle_id":          cycle_id,
        "disclosure_form":   disclosure_form,
        "target_consumer":   target_consumer,
        "purpose":           purpose,
        "record_count":      consent_filtered_count,
        "consent_dropped":   consent_dropped,
        "disclosed_at":      _now_iso(),
    }
    _archive_to_s3(audit_entry, AUDIT_ARCHIVE_BUCKET,
                     f"disclosure-events/{cycle_id}",
                     key_id=f"{target_consumer}-disclosure")

    _emit_metric("DisclosureCompleted", 1.0,
                  dimensions={"DisclosureForm":  disclosure_form,
                                "TargetConsumer":  target_consumer,
                                "CycleId":         cycle_id})
    return disclosure_envelope
```

---

## Step 6: React to Invalidation Events That Supersede Prior Linkages

*The pseudocode calls this `invalidate_on_event(invalidation_event)`. A linkage that was wrong, a salt that has rotated, a parameterization that has been upgraded, a consent that has been withdrawn, an underlying identity-merge or name-change reversal from recipes 5.1 or 5.7 all invalidate the prior linkage in different ways. The invalidation pipeline subscribes to these events and triggers the appropriate response (re-encode the affected records, re-run the matcher, communicate the superseded result to the consumer, route the affected records out of future cycles). Skip the invalidation pipeline and the prior linkage results drift out of sync with the underlying identity infrastructure; the drift compounds over time and undermines trust in every subsequent cycle.*

```python
def invalidate_on_event(invalidation_event: dict) -> dict:
    """Re-evaluate linkages affected by an invalidation event.
    Production triggers a Step Functions workflow that handles
    the specific superseding-event type and re-runs the affected
    portions of the cycle. The demo records what would be done."""
    source = invalidation_event.get("source")
    summary = {
        "source":              source,
        "event_id":            invalidation_event.get("event_id"),
        "actions":             [],
        "affected_cycle_ids":  [],
        "affected_participants": [],
    }

    if source == "salt_rotation":
        # The salt has rotated. All encoded data under the prior
        # salt is invalidated. Schedule a coordinated re-encoding
        # cycle with all participants. Notify downstream consumers
        # that the prior cycle's results are superseded by the
        # next cycle's.
        prior_salt = invalidation_event.get("prior_salt_key_version")
        new_salt = invalidation_event.get("new_salt_key_version")
        approvers = invalidation_event.get("dual_control_approvers", [])

        try:
            salt_custody.rotate_salt(new_salt, approvers)
        except ValueError as exc:
            summary["actions"].append(f"rotation_blocked: {exc}")
            return summary

        affected = [cid for cid, meta in _IN_MEMORY_CYCLE_METADATA.items()
                     if meta.get("salt_key_version") == prior_salt]
        summary["affected_cycle_ids"] = affected
        summary["actions"].append(
            f"rotate_salt_to:{new_salt}")
        summary["actions"].append(
            f"schedule_coordinated_re_encoding:{len(affected)}_cycles")
        summary["actions"].append(
            "notify_downstream_consumers_of_supersession")

    elif source == "parameterization_upgrade":
        # The parameterization has been upgraded. Schedule a
        # coordinated re-encoding under the new parameterization.
        # Existing cycles' results remain valid for the use cases
        # the prior parameterization supported, but new cycles
        # use the new parameterization.
        new_version = invalidation_event.get("new_parameterization_version")
        new_config = invalidation_event.get("new_parameterization")
        if new_version and new_config:
            protocol_config_store.publish_new_version(
                new_version, new_config)
        summary["actions"].append(
            f"publish_new_parameterization:{new_version}")
        summary["actions"].append(
            "schedule_coordinated_re_encoding")

    elif source == "consent_withdrawal":
        # A patient has withdrawn consent for inclusion in the
        # linkage. The participating organization removes the
        # patient from future encoding. Prior linkages remain in
        # the consumer's possession; the participating
        # organization communicates the withdrawal to the
        # consumer per the protocol's policy on retroactive
        # handling.
        sid = invalidation_event.get("source_record_id")
        participant = invalidation_event.get("participant_id")
        consent_store.withdraw_consent(sid)
        summary["affected_participants"] = [participant]
        summary["actions"].append(
            f"mark_consent_withdrawn:{sid}")
        summary["actions"].append(
            "notify_downstream_consumers_of_withdrawal")
        summary["actions"].append(
            "exclude_from_future_cycles")

    elif source == "identity_merge_recipe_5_1":
        # Recipe 5.1 merged two identities at the participating
        # organization. The prior encoded records under the
        # merged-from identity are invalidated; the next cycle
        # re-encodes the surviving identity.
        participant = invalidation_event.get("participant_id")
        merged_from_ids = invalidation_event.get(
            "merged_from_source_record_ids", [])
        summary["affected_participants"] = [participant]
        summary["actions"].append(
            f"queue_re_encode_for_merged_identities:"
            f"{len(merged_from_ids)}_records")

    elif source == "name_change_recipe_5_7":
        # Recipe 5.7 resolved a name change. The encoded records
        # under the prior name are invalidated; the next cycle
        # re-encodes under the current name (and may carry a
        # prior-name encoding for the cycles that need
        # historical-name matching).
        participant = invalidation_event.get("participant_id")
        sid = invalidation_event.get("source_record_id")
        summary["affected_participants"] = [participant]
        summary["actions"].append(
            f"queue_re_encode_for_name_change:{sid}")

    elif source == "re_identification_risk_model_update":
        # The institutional privacy team has updated the
        # re-identification-risk model. The parameterization may
        # need re-tuning; defensive measures may need to be
        # strengthened. Schedule a coordinated parameterization
        # upgrade and re-encoding cycle.
        summary["actions"].append(
            "schedule_parameterization_upgrade")
        summary["actions"].append(
            "schedule_coordinated_re_encoding")

    else:
        summary["actions"].append(
            f"unknown_invalidation_source:{source}")

    # Emit the invalidation event for downstream consumers.
    try:
        eventbridge_client.put_events(Entries=[{
            "Source":       "privacy-preserving-record-linkage",
            "DetailType":   "pprl_linkage_invalidated",
            "EventBusName": PPRL_EVENT_BUS_NAME,
            "Detail": json.dumps({
                "invalidation_source":       source,
                "invalidation_event_id":     invalidation_event.get("event_id"),
                "affected_cycle_ids":        summary["affected_cycle_ids"],
                "affected_participant_ids":  summary["affected_participants"],
                "invalidated_at":            _now_iso(),
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

The pipeline assembles the six steps into a single callable function. In production these are separate Lambdas (for the operational stream) and Glue jobs (for the bulk encoding and the matcher execution) orchestrated by Step Functions, each running in separate AWS accounts under cross-account access policies; here we run them in-process so the trace is easy to follow.

```python
def initialize_cycle(cycle_id: str,
                       parameterization_version: str = None,
                       salt_key_version: str = None) -> dict:
    """Set up the linkage cycle metadata. Each cycle pins the
    parameterization version and the salt-key version active at
    the cycle's start; mismatched versions at exchange time
    trigger the silent-failure-prevention check from Step 3."""
    parameterization_version = (parameterization_version
                                  or PROTOCOL_PARAMETERIZATION_VERSION)
    salt_key_version = (salt_key_version
                         or salt_custody.get_active_version())
    cycle_metadata = {
        "cycle_id":                cycle_id,
        "parameterization_version": parameterization_version,
        "salt_key_version":        salt_key_version,
        "started_at":              _now_iso(),
        "participants":            ["participant-A", "participant-B"],
    }
    _IN_MEMORY_CYCLE_METADATA[cycle_id] = cycle_metadata
    _IN_MEMORY_EXCHANGE_BUCKET.setdefault(cycle_id, {})
    return cycle_metadata


def run_cycle(cycle_id: str,
                participant_a_records: list,
                participant_b_records: list,
                disclosure_form: str = "per_record_match_flags",
                target_consumer: str = "participant-A",
                purpose: str = "research_linkage") -> dict:
    """End-to-end standardize -> encode -> exchange -> match ->
    disclose pipeline for a single linkage cycle. Returns the
    full trace."""
    cycle_metadata = initialize_cycle(cycle_id)
    parameterization_version = cycle_metadata["parameterization_version"]
    salt_key_version = cycle_metadata["salt_key_version"]

    # Per-participant standardize-and-encode-and-exchange. In
    # production each participant runs this independently in its
    # own AWS account; the demo runs both sequentially in one
    # process.
    prepared_a = standardize_and_prepare(
        participant_a_records, "participant-A",
        purpose, PROTOCOL_PARAMETERIZATION)
    encoded_a = encode_batch(prepared_a, parameterization_version,
                              salt_key_version, cycle_id)
    exchange_meta_a = exchange_encoded_records(
        encoded_a, "participant-A", cycle_id)

    prepared_b = standardize_and_prepare(
        participant_b_records, "participant-B",
        purpose, PROTOCOL_PARAMETERIZATION)
    encoded_b = encode_batch(prepared_b, parameterization_version,
                              salt_key_version, cycle_id)
    exchange_meta_b = exchange_encoded_records(
        encoded_b, "participant-B", cycle_id)

    # Match. In production this runs in the linkage-execution
    # endpoint's account (a Nitro Enclave for TEE-based protocols
    # or a Glue job for the linkage-broker model).
    match_results = match_encoded_records(
        encoded_a, encoded_b, cycle_id, parameterization_version)
    _IN_MEMORY_LINKAGE_RESULTS.extend(match_results)

    # Disclose. The disclosure form is specified per use case;
    # the demo varies it across cycles.
    disclosure_envelope = disclose_linkage_results(
        match_results, cycle_id, disclosure_form,
        target_consumer, purpose)

    return {
        "cycle_metadata":     cycle_metadata,
        "encoded_a_count":    len(encoded_a),
        "encoded_b_count":    len(encoded_b),
        "match_results":      match_results,
        "disclosure_envelope": disclosure_envelope,
    }


def run_demo():
    """Run three representative linkage cycles covering the
    per-record-match-flags, intersection-count, and k-anonymous-
    aggregate disclosure forms. Then exercise the invalidation
    pipeline."""
    print("=" * 72)
    print("Privacy-Preserving Record Linkage Demo")
    print("=" * 72)
    print()
    print("All patients, demographics, and consent records in this demo are")
    print("fictional. The mock salt custody, protocol parameterization store,")
    print("participant data sources, consent store, and jurisdictional")
    print("overlays return hand-crafted data that exercises the encoding,")
    print("matching, and disclosure paths; do not point this demo at a live")
    print("data-sharing collaboration.")
    print()
    print(f"Active parameterization: {PROTOCOL_PARAMETERIZATION_VERSION}")
    print(f"Active salt key:         {salt_custody.get_active_version()}")
    print(f"Bloom filter size:       "
          f"{PROTOCOL_PARAMETERIZATION['bloom_filter_size']} bits")
    print(f"Hash function count:     "
          f"{PROTOCOL_PARAMETERIZATION['hash_function_count']}")
    print(f"N-gram size:             "
          f"{PROTOCOL_PARAMETERIZATION['n_gram_size']}")
    print(f"Encoded thresholds:      "
          f"HIGH={ENCODED_MATCH_HIGH_THRESHOLD}  "
          f"MED={ENCODED_MATCH_MED_THRESHOLD}  "
          f"REJECT={ENCODED_REJECT_THRESHOLD}")
    print()

    # --- Cycle 1: per_record_match_flags to participant A ---
    print("-" * 72)
    print("Cycle 1: research linkage, per_record_match_flags to participant A")
    print("-" * 72)
    cycle_1 = run_cycle(
        cycle_id="cycle-2026-q2-research-001",
        participant_a_records=SYNTHETIC_PARTICIPANT_A_RECORDS,
        participant_b_records=SYNTHETIC_PARTICIPANT_B_RECORDS,
        disclosure_form="per_record_match_flags",
        target_consumer="participant-A",
        purpose="research_linkage",
    )
    print(f"  participants:         participant-A ({cycle_1['encoded_a_count']} encoded), "
          f"participant-B ({cycle_1['encoded_b_count']} encoded)")
    confirmed = [m for m in cycle_1["match_results"]
                  if m["decision"] == "MATCH_HIGH"]
    review = [m for m in cycle_1["match_results"]
                  if m["decision"] == "MATCH_MED_REVIEW"]
    print(f"  match_high pairs:     {len(confirmed)}")
    print(f"  review pairs:         {len(review)}")
    print(f"  disclosure_form:      {cycle_1['disclosure_envelope']['disclosure_form']}")
    print(f"  target_consumer:      {cycle_1['disclosure_envelope']['target_consumer']}")
    print(f"  consent_dropped:      {cycle_1['disclosure_envelope']['consent_dropped']}")
    payload = cycle_1["disclosure_envelope"]["envelope_payload"]
    print(f"  total_records_for_a:  {payload.get('total_records_contributed_by_a')}")
    print(f"  total_matches_for_a:  {payload.get('total_matches_for_a')}")

    # Show a sample match result with evidence summary so the
    # reader can see what the per-feature similarity scores look
    # like under encoded comparison.
    if confirmed:
        sample = confirmed[0]
        print(f"  sample MATCH_HIGH:")
        print(f"    encoded_record_a_id: {sample['encoded_record_a_id']}")
        print(f"    encoded_record_b_id: {sample['encoded_record_b_id']}")
        print(f"    match_score:         {float(sample['match_score']):.3f}")
        print(f"    per_feature_similarities (excerpt):")
        for fname in ["given_name", "family_name", "dob", "address_line"]:
            sim = sample["evidence_summary"][
                "per_feature_similarities"].get(fname)
            if sim is not None:
                print(f"      {fname:<14}: {float(sim):.3f}")

    # --- Cycle 2: intersection_count to a public-health consumer ---
    print()
    print("-" * 72)
    print("Cycle 2: public-health surveillance, intersection_count")
    print("-" * 72)
    cycle_2 = run_cycle(
        cycle_id="cycle-2026-q2-surveillance-002",
        participant_a_records=SYNTHETIC_PARTICIPANT_A_RECORDS,
        participant_b_records=SYNTHETIC_PARTICIPANT_B_RECORDS,
        disclosure_form="intersection_count",
        target_consumer="state-public-health-department",
        purpose="research_linkage",
    )
    payload_2 = cycle_2["disclosure_envelope"]["envelope_payload"]
    print(f"  intersection_count:        {payload_2.get('intersection_count')}")
    print(f"  participant_a_total:       {payload_2.get('participant_a_total')}")
    print(f"  participant_b_total:       {payload_2.get('participant_b_total')}")
    print(f"  match_rate_lower_bound:    "
          f"{payload_2.get('match_rate_lower_bound'):.3f}")
    print(f"  match_rate_upper_bound:    "
          f"{payload_2.get('match_rate_upper_bound'):.3f}")
    print(f"  consent_dropped:           "
          f"{cycle_2['disclosure_envelope']['consent_dropped']}")

    # --- Cycle 3: k_anonymous_aggregate ---
    print()
    print("-" * 72)
    print("Cycle 3: ACO out-of-network analytics, k_anonymous_aggregate")
    print("-" * 72)
    cycle_3 = run_cycle(
        cycle_id="cycle-2026-q2-aco-003",
        participant_a_records=SYNTHETIC_PARTICIPANT_A_RECORDS,
        participant_b_records=SYNTHETIC_PARTICIPANT_B_RECORDS,
        disclosure_form="k_anonymous_aggregate",
        target_consumer="aco-analytics-team",
        purpose="research_linkage",
    )
    payload_3 = cycle_3["disclosure_envelope"]["envelope_payload"]
    print(f"  k_anonymity_parameter:     {payload_3.get('k_anonymity_parameter')}")
    print(f"  suppression_threshold:     {payload_3.get('suppression_threshold')}")
    print(f"  cohort_aggregates:")
    for agg in payload_3.get("cohort_aggregates", []):
        print(f"    cohort_axis_hash_prefix={agg['cohort_axis_hash_prefix']}: "
              f"{agg['patient_count_aggregate']}")

    # --- Phase 2: invalidation pipeline ---
    print()
    print("-" * 72)
    print("Phase 2: invalidation triggers")
    print("-" * 72)

    # Salt rotation. Requires dual-control approval.
    inv_1 = invalidate_on_event({
        "source":                  "salt_rotation",
        "event_id":                "inv-2026-04-30-001",
        "prior_salt_key_version":  "salt-2026-q2-rotation-001",
        "new_salt_key_version":    "salt-2026-q3-rotation-001",
        "dual_control_approvers": [
            "alice@participant-A.org",
            "bob@participant-B.org",
        ],
    })
    print(f"  source={inv_1['source']:<35}"
          f" affected={len(inv_1['affected_cycle_ids'])} cycles")
    for action in inv_1['actions']:
        print(f"    action: {action}")

    # Salt rotation without dual control should fail.
    inv_2 = invalidate_on_event({
        "source":                  "salt_rotation",
        "event_id":                "inv-2026-04-30-002",
        "prior_salt_key_version":  "salt-2026-q3-rotation-001",
        "new_salt_key_version":    "salt-2026-q4-rotation-001",
        "dual_control_approvers": ["alice@participant-A.org"],  # only one
    })
    print(f"  source={inv_2['source']:<35} "
          f"actions={inv_2['actions']}")

    # Parameterization upgrade.
    new_param_config = dict(PROTOCOL_PARAMETERIZATION)
    new_param_config["parameterization_version"] = "pprl-clk-v2.4.0"
    new_param_config["defensive_measures"]["random_hashing_enabled"] = True
    inv_3 = invalidate_on_event({
        "source":                       "parameterization_upgrade",
        "event_id":                     "inv-2026-04-30-003",
        "new_parameterization_version": "pprl-clk-v2.4.0",
        "new_parameterization":         new_param_config,
    })
    print(f"  source={inv_3['source']:<35} "
          f"actions={inv_3['actions']}")

    # Consent withdrawal.
    inv_4 = invalidate_on_event({
        "source":           "consent_withdrawal",
        "event_id":         "inv-2026-04-30-004",
        "participant_id":   "participant-A",
        "source_record_id": "academic-mc-mrn-00284271",
    })
    print(f"  source={inv_4['source']:<35} "
          f"actions={inv_4['actions']}")

    # Identity merge from recipe 5.1.
    inv_5 = invalidate_on_event({
        "source":         "identity_merge_recipe_5_1",
        "event_id":       "inv-2026-04-30-005",
        "participant_id": "participant-A",
        "merged_from_source_record_ids": [
            "academic-mc-mrn-99999-old",
            "academic-mc-mrn-88888-old",
        ],
    })
    print(f"  source={inv_5['source']:<35} "
          f"actions={inv_5['actions']}")

    # Name change from recipe 5.7.
    inv_6 = invalidate_on_event({
        "source":           "name_change_recipe_5_7",
        "event_id":         "inv-2026-04-30-006",
        "participant_id":   "participant-A",
        "source_record_id": "academic-mc-mrn-00284271",
    })
    print(f"  source={inv_6['source']:<35} "
          f"actions={inv_6['actions']}")


if __name__ == "__main__":
    run_demo()
```

---

Expected console output (the SQS / EventBridge / S3 / DynamoDB / CloudWatch warnings appear in demo mode because the resources do not exist; they are harmless):

```
========================================================================
Privacy-Preserving Record Linkage Demo
========================================================================

All patients, demographics, and consent records in this demo are
fictional. The mock salt custody, protocol parameterization store,
participant data sources, consent store, and jurisdictional
overlays return hand-crafted data that exercises the encoding,
matching, and disclosure paths; do not point this demo at a live
data-sharing collaboration.

Active parameterization: pprl-clk-v2.3.1
Active salt key:         salt-2026-q2-rotation-001
Bloom filter size:       1024 bits
Hash function count:     30
N-gram size:             2
Encoded thresholds:      HIGH=0.85  MED=0.72  REJECT=0.50

------------------------------------------------------------------------
Cycle 1: research linkage, per_record_match_flags to participant A
------------------------------------------------------------------------
  participants:         participant-A (4 encoded), participant-B (4 encoded)
  match_high pairs:     3
  review pairs:         13
  disclosure_form:      per_record_match_flags
  target_consumer:      participant-A
  consent_dropped:      0
  total_records_for_a:  4
  total_matches_for_a:  16
  sample MATCH_HIGH:
    encoded_record_a_id: enc-cycle-2026-q2-research-001-p-XXXXXXXXXXXX
    encoded_record_b_id: enc-cycle-2026-q2-research-001-p-XXXXXXXXXXXX
    match_score:         1.000
    per_feature_similarities (excerpt):
      given_name    : 1.000
      family_name   : 1.000
      dob           : 1.000
      address_line  : 1.000

------------------------------------------------------------------------
Cycle 2: public-health surveillance, intersection_count
------------------------------------------------------------------------
  intersection_count:        3
  participant_a_total:       4
  participant_b_total:       4
  match_rate_lower_bound:    0.750
  match_rate_upper_bound:    0.750
  consent_dropped:           0

------------------------------------------------------------------------
Cycle 3: ACO out-of-network analytics, k_anonymous_aggregate
------------------------------------------------------------------------
  k_anonymity_parameter:     11
  suppression_threshold:     5
  cohort_aggregates:
    cohort_axis_hash_prefix=XXXXXXXX: [suppressed: cell size below threshold]
    cohort_axis_hash_prefix=XXXXXXXX: [suppressed: cell size below threshold]

------------------------------------------------------------------------
Phase 2: invalidation triggers
------------------------------------------------------------------------
  source=salt_rotation                       affected=3 cycles
    action: rotate_salt_to:salt-2026-q3-rotation-001
    action: schedule_coordinated_re_encoding:3_cycles
    action: notify_downstream_consumers_of_supersession
  source=salt_rotation                        actions=['rotation_blocked: salt rotation requires dual-control approval (at least two approvers from non-overlapping organizations)']
  source=parameterization_upgrade             actions=['publish_new_parameterization:pprl-clk-v2.4.0', 'schedule_coordinated_re_encoding']
  source=consent_withdrawal                   actions=['mark_consent_withdrawn:academic-mc-mrn-00284271', 'notify_downstream_consumers_of_withdrawal', 'exclude_from_future_cycles']
  source=identity_merge_recipe_5_1            actions=['queue_re_encode_for_merged_identities:2_records']
  source=name_change_recipe_5_7               actions=['queue_re_encode_for_name_change:academic-mc-mrn-00284271']
```

(The encoded_record_id suffixes include random UUID hex so the actual `XXXXXXXXXXXX` portions will differ from run to run; the cohort_axis_hash_prefix values include HMAC-derived hex so they will also differ. Exact match-score values depend on the canonical-form details of the demo's address normalization and on the simple Bloom-filter implementation; production CLK encoders with `clkhash` produce different absolute scores.)

Several patterns to notice:

- **Cycle 1 demonstrates the canonical research-linkage path.** Three of the four participant-A records (Catherine, Maria, Margaret) have matching counterparts in participant-B; Theodore Williamson is a participant-A-only record; Patricia Murphy was filtered out at standardize time because her consent was withdrawn. Robert Andersen is a participant-B-only record. The matcher produces three MATCH_HIGH pairs. The thirteen MATCH_MED_REVIEW pairs are an artifact of the toy Bloom-filter implementation: with the demo's small bit-allocation per feature and no defensive measures, even unrelated record pairs accumulate enough coincidental bit overlap to land above the REJECT threshold. Production CLK encoders with `clkhash` and proper defensive measures (random hashing, balanced encoding, hardening) produce a much sharper match-vs-non-match separation; calibration against a real pilot population sets the REJECT threshold high enough that unrelated pairs are correctly rejected. The demo's behavior is itself a useful teaching point: PPRL thresholds are not the same as plaintext-matching thresholds, and the calibration discipline is non-optional. Because the disclosure form is `per_record_match_flags` to participant-A, the consumer receives match flags for both MATCH_HIGH and MATCH_MED_REVIEW pairs (production typically restricts to MATCH_HIGH only and routes MATCH_MED_REVIEW to a separate review queue); the demo's wider disclosure makes the threshold-band behavior visible to the reader.
- **Cycle 2 demonstrates the intersection-count form.** The same population, the same matches, but the consumer (a state public-health department) receives only the intersection size and the per-participant totals. The match_rate_lower_bound and match_rate_upper_bound are derived from the intersection size relative to each participant's total; the consumer can compute the population-level match rate but cannot identify which specific records intersected.
- **Cycle 3 demonstrates the k-anonymous-aggregate form.** The ACO analytics team receives cohort-level aggregates with small-cell suppression at the threshold (5 in the demo). All cohort cells in the demo are below 5 (the demo population is tiny), so all are suppressed; production with population-scale data sees most cells reported with the count and only the smallest cohorts suppressed.
- **The cohort-axis hashes flow through the disclosure step.** Each participant computed its own cohort-axis hashes locally at encoding time; the matcher receives the hashes and stratifies the disclosure aggregates by them. The matcher never sees the underlying axis values (name_tradition, age_decade, sex_or_gender), but the cohort-stratified aggregates in the disclosure are still meaningful because the hash collisions are deterministic across participants for the same axis values.
- **Cycle 1's consent_dropped is 0 because Patricia was dropped earlier.** The standardize-and-prepare step filters at intake based on consent posture; the matcher never sees Patricia's encoded record, so the disclosure-time consent filter has nothing additional to drop. Production should still run the disclosure-time consent filter as a defense-in-depth check; the standardize-time filter is the primary enforcement point.
- **The salt-rotation invalidation demonstrates the dual-control requirement.** The first rotation succeeds because two approvers from non-overlapping organizations were named; the second rotation is blocked because only one approver was named. Production enforces this through HSM-level dual control (the rotation operation literally cannot proceed until two HSM operators have approved it); the demo's check is at the application layer for illustration.
- **Parameterization upgrade publishes a new version with random-hashing enabled.** The defensive-measures upgrade illustrates the re-identification-risk-model update path: a new attack is published, the privacy team recommends a defensive-measure update, the new parameterization is published with governance approval, all participants schedule a coordinated re-encoding under the new parameterization. Cycles previously executed under the old parameterization remain valid for their original use cases (the disclosed results have already been delivered) but new cycles use the new parameterization.
- **Consent withdrawal is forward-only.** Patricia's withdrawal in this run was set up at the synthetic-data layer; the invalidation demo's consent_withdrawal trigger illustrates the operational flow: when a patient withdraws consent through the patient portal or another channel, the invalidation pipeline marks the source record as withdrawn in the consent store and notifies downstream consumers. Future cycles exclude the record; prior cycles' results remain in the consumer's possession.
- **The cross-recipe invalidations (identity_merge_recipe_5_1, name_change_recipe_5_7) demonstrate the upstream-event consumption pattern.** Recipe 5.1 merging two identities or recipe 5.7 resolving a name change invalidates the encoded records under the prior identity state. The invalidation pipeline queues the affected records for re-encoding in the next cycle.

---

## Gap to Production

What the demo intentionally skips, and what you would add for a real deployment:

**Replace the toy Bloom-filter implementation with `clkhash` and `anonlink`.** The demo's encoding is a deliberately simple stand-in that illustrates the construction without the production-grade defensive measures. Production uses [`clkhash`](https://github.com/data61/clkhash) for the CLK encoding (random hashing, balanced encoding, hardening, all current-best-practice defensive measures) and [`anonlink`](https://github.com/data61/anonlink) for the matching layer (efficient candidate generation with locality-sensitive hashing on the CLK, optimized Sørensen-Dice scoring at population scale, parallelization). Both libraries are maintained by CSIRO's Data61 / the Confidential Computing Consortium. Replace the demo's `_encode_per_feature_bloom_filter`, `_combine_per_feature_filters`, and `_sorensen_dice_coefficient` with `clkhash` and `anonlink` calls.

**Real Splink-or-`recordlinkage` and `jellyfish` for the calibration path.** The demo's `_combine_with_fellegi_sunter` is a toy weighted-average. Production wraps Splink (or `recordlinkage`) with proper EM-trained per-feature m-and-u parameters calibrated against a known-overlap pilot population encoded under the production parameterization. The pilot calibration is itself a separately authorized data-sharing event with its own data-use agreement, separate AWS account, separate access controls, separate audit posture; the calibration outputs (the ENCODED_MATCH thresholds, the per-feature weights, the missing-feature weights) survive the pilot but the underlying pilot data is deleted at the end of the calibration project per the agreement.

**HSM-backed salt custody with dual-control rotation ceremony.** The demo's `MockSaltCustody` returns the plaintext salt to Python application code; production never does this. The shared cryptographic salt is custodied in AWS CloudHSM (high-assurance) or AWS KMS with customer-managed keys (lower-assurance). The encoder's HMAC-SHA-256 operations call into the HSM context where the plaintext salt never leaves the hardware. Salt generation is a multi-party ceremony with explicit dual-control approval (two HSM operators from non-overlapping organizations). Salt rotation is a coordinated multi-organization event with a published cadence (quarterly to annually depending on protocol) and a catch-up window. Salt-related audit logging captures every access with the calling principal, the operation, the timestamp, and the cycle context. Build the salt-management capability as a deliberate operational program with named owners, named processes, and named review committees.

**Real DynamoDB schema with the four primary tables.** The `linkage-cycle-metadata` table holds per-cycle metadata (partition key: `cycle_id`). The `linkage-results-store` holds per-pair linkage decisions (partition key: `cycle_id`, sort key: `match_id`). The `protocol-parameterization-config` holds versioned parameterization configurations (partition key: `parameterization_version`). The `participant-local-mapping` (per participant, in their own AWS account) holds the encoded_record_id-to-source_record_id mapping (partition key: `cycle_id`, sort key: `encoded_record_id`). Provision with on-demand capacity. Customer-managed KMS keys at rest. Point-in-time recovery for the linkage-cycle-metadata and linkage-results tables. DynamoDB Streams on the linkage-cycle-metadata table to drive the cross-recipe event fan-out.

**TransactWriteItems for atomic cycle-completion writes.** The demo writes the cycle metadata, the linkage results, the disclosure envelope, and the audit log entries in separate calls; partial-failure scenarios could leave the cycle's state inconsistent. Production wraps cycle-completion writes in `TransactWriteItems` so the cycle's state is atomic across the four tables.

**Real cross-account S3 buckets with PrivateLink for the encoded-data exchange.** The demo's `_IN_MEMORY_EXCHANGE_BUCKET` runs all participants in one process; production exchanges across AWS accounts and (often) organizational boundaries. Per-participant encoded-records buckets with cross-account access policies that enumerate the matcher role; SSE-KMS encryption with customer-managed keys; bucket-level keys; restricted access policy. Object Lock in Compliance mode protects the audit-archive bucket. PrivateLink endpoints between participant VPCs and the linkage-execution endpoint VPC where the protocol prohibits exchange through publicly-routable endpoints. Cross-account replication propagates encoded payloads to the linkage-execution endpoint's account where the matcher consumes them.

**Nitro Enclaves for the TEE-based variant.** Where the protocol benefits from a hardware-attested isolated execution environment, the matcher runs inside a Nitro Enclave. Each participant verifies the enclave's attestation document before contributing its encoded data; the attestation proves the enclave is running the agreed measurement and the parent EC2 instance cannot read the enclave's memory. The enclave's vsock interface is the only network path; no persistent storage, no operator visibility. Per-cycle enclave instantiation and teardown; the enclave is destroyed at the cycle's end with no residual state. Build the attestation flow as a first-class architectural component with explicit measurement registration and verification logic at each participant.

**Real EventBridge bus with cross-recipe consumer subscriptions.** The demo emits events but they go nowhere because the bus does not exist in demo mode. Production deploys a dedicated `pprl-events-bus` with EventBridge rules routing the cycle-completion, salt-rotation, parameterization-upgrade, consent-withdrawal, and re-encoding-required events to the appropriate consumers (recipe 5.5 cross-facility matcher for upstream identity events, recipe 5.6 claims-clinical-linkage for downstream cohort updates, recipe 5.7 longitudinal-name-change for name-change-driven re-encoding triggers, the participating organizations' operational systems for cycle status, the analytic consumers for delivered linkage results). DLQs on every consumer; CloudWatch alarms on DLQ depth surface stuck consumers.

**Step Functions orchestration for the full cycle.** The demo's `run_cycle` runs the six steps sequentially in one process; production orchestrates them through Step Functions with per-stage retries, error routing to DLQs, parallel execution across participants where the protocol allows, and explicit synchronization barriers where the protocol requires (the matcher cannot start until every participant has contributed; the disclosure cannot occur until the matcher has completed and the disclosure-policy validation has passed). Each Lambda and Glue job has a dedicated DLQ; Step Functions Catch states distinguish retriable infrastructure failures from terminal logic failures.

**Glue and Spark for the population-scale encoding and matching.** The demo iterates in-process for a handful of records; production runs the bulk encoding as a Glue job per participant (each in its own AWS account) operating over Parquet partitions of the participant's source data. The matcher itself runs as a Glue job in the linkage-execution endpoint's account, consuming the encoded data from each participant's exchange bucket and producing the per-pair linkage decisions. For population-scale linkages (hundreds of thousands to tens of millions of records per participant), Spark partitioning and the `anonlink` library's optimized matching primitives are essential.

**Idempotency keys on every write.** The demo's idempotency is implicit; production extends explicitly. Standardize at `(participant_id, source_record_id, cycle_id)`; encode at `(participant_id, source_record_id, cycle_id, parameterization_version, salt_key_version)`; exchange at `(participant_id, cycle_id, batch_id)`; match at `(cycle_id, encoded_record_a_id, encoded_record_b_id)`; disclose at `(cycle_id, target_consumer, disclosure_form)`; invalidate-on-event at `invalidation_event_id`. Duplicate-event delivery from EventBridge or duplicate-invocation from Step Functions retries is routine; the pipeline must handle it without producing duplicate encoded records, duplicate match results, or duplicate disclosures.

**Threshold calibration and approval governance.** The ENCODED_MATCH_HIGH, ENCODED_MATCH_MED, ENCODED_REJECT thresholds, the per-feature weights, and the missing-feature weights are calibrated against a known-overlap pilot population encoded under the production parameterization. Re-calibration runs periodically and on detection of cohort-stratified disparity above the institutional threshold. Each linkage cycle references the configuration version active at decision time. Promote candidate thresholds through institutional review (analytics governance committee, compliance, clinical informatics, privacy team, equity-monitoring committee) before going live.

**Cohort-stratified accuracy monitoring with disparity alarms.** The demo emits the `CohortBucketHash` dimension on `MatchDecision` but does not aggregate or alarm. Production computes per-cohort linkage rate weekly, per-cohort false-acceptance rate weekly, per-cohort review-queue aging weekly, per-cohort sampled error rate monthly. Disparity (best-rate minus worst-rate) thresholds: linkage-rate > 0.05 = MEDIUM alarm; false-acceptance-rate > 0.01 = HIGH (false acceptances under PPRL produce wrong-record disclosures that the consumer cannot retract); review-queue-aging disparity > 5 business days = MEDIUM. The privacy team is an explicit reviewer in addition to the standard analytics-governance committee, because cohort-stratified disparities in PPRL are also re-identification-risk indicators (cohorts with anomalously low linkage rates may be over-encoded with defensive noise; cohorts with anomalously high linkage rates may be under-encoded relative to the parameterization's defensive design).

**Re-identification-risk review on a periodic cadence.** The institutional privacy team owns the re-identification-risk model and reviews it on a periodic cadence (every 12-18 months is typical, with off-cycle review when new attacks are published). The review evaluates the parameterization against published attacks (the Vatsalan-Christen frequency analysis, the Kuzu-et-al attack on small populations, the Christen et al. 2017 cryptanalysis, and any subsequent academic publications), identifies necessary defensive-measure updates, and produces a recommendation that the trust-framework governance process consumes. Stay current with the academic literature through the privacy team; the institutions that operate parameterizations the published literature has identified as vulnerable have an audit-posture gap that the audit cannot detect because the audit is on the operational behavior, not on the cryptographic-state-of-the-art.

**Three review queues with cohort-and-cycle-aware tooling.** The demo routes review-band cases nowhere; production builds three workflow tools. The linkage-review tool surfaces medium-confidence pairs with the encoded-record IDs (not the demographics), the per-feature similarity scores, the cohort-axis hashes, and (under appropriate authorization at each participant) the source records under each participant's own access controls. The salt-rotation review queue surfaces re-encoding completion status per participant for verification before the prior salt is decommissioned (dual-controlled at this approval point). The consent-withdrawal review queue surfaces patient-initiated withdrawals for verification (especially when delivered through a non-standard channel like a phone call to medical records or a patient portal). Each tool emits the reviewer's decision back into the matcher's training signal for periodic threshold re-calibration. Reviewer-identity authentication is two-factor; reviewer-action is dual-controlled for the salt-rotation review queue.

**Patient-consent capture and withdrawal pathways.** The PPRL deployment assumes that the patient has been asked (and has consented or declined) for inclusion in the linkage. The mechanism for asking is not the matcher's job; it is the registration workflow's, the patient-portal app's, and (for clinical-care contexts) the institutional consent-management workflow's. Build the consent-capture and withdrawal-pathway as a deliberate workflow with appropriate framing, training for the staff who solicit the information, and patient-facing communication about what the linkage does and what consent withdrawal means (forward-only retraction; prior cycles' results remain in the consumer's possession). The demo's `MockConsentStore` is a placeholder; real consent capture is a substantial UX-and-policy engagement.

**Information-blocking compliance posture.** The 21st Century Cures Act information-blocking provisions apply to PPRL in non-obvious ways: a patient who has authorized an external research consortium to access her records has, by extension, authorized the PPRL linkage that the consortium uses; a patient whose records are excluded from the linkage because of a consent-withdrawal or a jurisdictional overlay should be able to receive an explanation of why the records were excluded. Build the patient-access-API release path with explicit awareness of the PPRL exclusion reasons.

**Cross-jurisdictional overlay automation.** The demo's `MockJurisdictionalOverlays` handles a single example overlay. Production has an overlay-rules engine that consumes the patient's residence jurisdiction, the use case's authorization scope, the record-type sensitivity classification (post-Dobbs reproductive-health-care state laws, 42 CFR Part 2 substance-use-treatment record provisions, state-level HIV-and-genetic-information rules, gender-affirming-care state-law overlays, patient-protective-custody scenarios), and the participating organizations' jurisdictional postures, and produces a per-record consent-posture decision. The overlay rules are versioned and reviewed on a regulatory-monitoring cadence (post-legislative-session is the typical trigger).

**KMS-encrypted everything.** Customer-managed keys for the encoded-records buckets, the linkage-cycle-metadata table, the linkage-results store, the participant-local-mapping tables, the audit-archive bucket, the SQS queues, the Lambda log groups, the Glue temp storage, the salt custody (CloudHSM or KMS), and the cohort-axis-hash key (Secrets Manager). Per-service KMS configuration is omitted for readability but is non-negotiable for the institution's standard PHI-handling posture.

**VPC + VPC endpoints + PrivateLink.** Production runs Glue jobs and Lambdas in VPC with VPC endpoints for S3 (gateway), DynamoDB (gateway), KMS, Secrets Manager, CloudWatch Logs, EventBridge, SQS, Step Functions, Glue, Athena, STS, and SageMaker. PrivateLink for the cross-participant encoded-data exchange where the protocol prohibits exchange through publicly-routable endpoints. NAT Gateway only for the linkage-execution endpoint's egress (where applicable); restrict egress with security groups and an outbound proxy with an allow-list. Per-participant-rate-limited cross-account access with explicit time-bound permissions for the matcher role during the cycle's active execution window.

**CloudTrail data events on every salt-related operation, every encoded-records bucket access, every linkage-cycle metadata access, and every linkage-result disclosure.** The data-events feature is not enabled by default and is the right level of granularity for this substrate. Audit logs in a dedicated S3 bucket with Object Lock in Compliance mode for immutability; lifecycle policy transitioning to S3 Glacier Deep Archive after 90 days; retention floor enforced at the bucket-policy and Object-Lock-configuration level. Forward CloudTrail data events to a dedicated audit AWS account in the institution's organization. Many PPRL trust frameworks specify a longer audit retention than the regulatory minimum because the linkage's privacy claim depends on retrospective audit.

**Lake Formation column-level and row-level access control on the analytics surface.** Different audiences need different views of the linkage cycle metadata and the cohort-stratified-accuracy reports. Treatment-context users (for clinical-care PPRL deployments) see only the linkage results for their own institution's patients. Research-context users see the cohort-stratified-accuracy metrics. Audit-and-compliance users see the full audit-event log. The institutional governance committee sees the cycle-level metadata for review.

**Trust-framework artifact and operational governance rhythm.** The multi-party trust framework is the load-bearing artifact for any PPRL deployment, and it is not a technical artifact. It is a contract that enumerates the participants, the protocol parameterization, the salt-management ceremony, the linkage-result-disclosure policy, the audit posture, the re-identification-risk model, the dispute-resolution mechanism, the consent-and-purpose-of-use governance, the cross-jurisdictional overlay handling, and the operational rhythms (salt-rotation cadence, parameterization-upgrade cadence, periodic re-identification-risk review cadence). Plan the trust-framework negotiation as a project with its own timeline, its own staffing, and its own iteration discipline; the engineering work serves the trust framework rather than the trust framework adapting to the engineering work after the fact.

**Compliance and operational ownership.** PPRL sits at the intersection of analytics, research, compliance, privacy, security, and IT. Establish clear operational ownership: who tunes the thresholds, who reviews the cohort-disparity reports, who owns the parameterization-version updates, who handles the salt-rotation ceremonies, who responds to consent withdrawals, who negotiates trust-framework changes. The pipeline works only when the operational ownership is clear and funded across the participating organizations, not just within one of them.

The pipeline is the easy part. The operational discipline (trust-framework as a first-class artifact with versioning and change control, salt-management as a deliberate operational program with HSM-based custody and dual-control rotation, threshold calibration with pilot-data infrastructure as a separately governed substrate, cohort-stratified equity monitoring with the privacy team as an explicit reviewer, re-identification-risk review on a regulatory-monitoring cadence, three-queue review tooling with cohort-and-cycle-aware oversight, consent-capture and withdrawal pathways with patient-facing communication, cross-jurisdictional overlay automation with regulatory-monitoring triggers, ongoing operational ownership with named contacts and SLAs across all participating organizations) is what makes a PPRL system produce useful linkages without undermining the privacy guarantee that justified using PPRL in the first place. Build for that.

---

*← [Recipe 5.8: Privacy-Preserving Record Linkage](chapter05.08-privacy-preserving-record-linkage)*
