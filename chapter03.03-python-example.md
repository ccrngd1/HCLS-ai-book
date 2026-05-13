# Recipe 3.3: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 3.3. It shows one way you could translate the billing-code-anomaly-detection pattern into working Python using pandas and scikit-learn (for the statistics and the Isolation Forest), Amazon DynamoDB (for peer-group statistics and the case registry), Amazon S3 (for feature snapshots, anomaly-signal outputs, and labels), Amazon SageMaker Feature Store (for consistent provider features across scoring and training), Amazon SNS (for analyst notifications), and Amazon Athena (for evidence-claim retrieval). It is not production-ready. There is no real claims warehouse integration, no Glue job wrapping around the aggregation code, no Step Functions orchestration, no SageMaker Processing wrapper around the scorer, no QuickSight dashboards, no subgroup fairness monitoring harness, no case-lineage across periods, no Isolation Forest retraining pipeline, and no analyst UI. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you would wire into a payer's payment-integrity pipeline on Monday morning.
>
> The code maps to the five core pseudocode steps from the main recipe: roll up adjudicated claims into provider-period feature vectors, assign providers to peer groups and compute peer-distribution statistics, score each provider-period across three anomaly signal families (peer z-scores, self-history CUSUM, and multivariate Isolation Forest), consolidate the signals into cases with representative-claim evidence, and capture investigation outcomes so the labels store is populated for eventual supervised retraining. A small `retrain_supervised_quarterly` sketch is included at the end to close the loop. Everything else (monitoring, drift detection, alarm wiring, subgroup fairness dashboards, analyst tooling) is covered in the Gap to Production section.

---

## Setup

You will need the AWS SDK for Python plus scikit-learn, pandas, and numpy for the statistics and the multivariate detector:

```bash
pip install boto3 scikit-learn pandas numpy
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchGetItem` on the `provider-peer-groups`, `peer-group-statistics`, and `case-registry` tables
- `s3:GetObject` and `s3:PutObject` on the features, anomaly-signals, and labels buckets
- `sagemaker-featurestore-runtime:GetRecord`, `sagemaker-featurestore-runtime:BatchGetRecord`, `sagemaker-featurestore-runtime:PutRecord` on the `provider-period-features` feature group (if you use Feature Store as the provider-feature store)
- `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults` for both the period aggregation and the evidence-claim retrieval
- `sns:Publish` on the analyst-notification topic
- `cloudwatch:PutMetricData` for operational metrics
- `events:PutEvents` on the EventBridge bus (for publishing investigation-outcome events from the analyst workstation side)

Scope each role to the specific resource ARNs it touches. The permissions above are fine for learning and will fail any serious IAM review. In production, each component (aggregation Glue job, peer-group assigner, scoring Processing job, case-assembly Lambda, outcome-joiner Lambda, retraining job) gets its own role with the minimum permissions for its job.

A few things worth knowing upfront:

- **No real claims warehouse integration in this example.** The adjudicated-claims source is the long pole in any production deployment, and each payer stores them differently (Redshift, Snowflake, an Athena-over-Parquet lake, or a vendor-provided warehouse). This example starts from a pandas DataFrame that looks like the output of a normalized claims query. In production, a Glue job reads from the warehouse on a monthly cadence and writes Parquet to S3.
- **pandas and scikit-learn here, Glue and SageMaker in production.** The example computes the rollup, the z-scores, the CUSUM, and the Isolation Forest in-process with pandas and scikit-learn. In a real deployment, the rollup runs as a Glue job over the full provider population, the statistical signals run as a SageMaker Processing job, and the Isolation Forest is trained as a SageMaker Training Job and invoked via a Processing job. The underlying math is identical; the infrastructure wrapping is what Glue and SageMaker provide.
- **DynamoDB table schemas.** `provider-peer-groups` is keyed on `provider_id` (partition key only). `peer-group-statistics` uses a composite key: `peer_group_key` (partition) and `feature_name` (sort). `case-registry` is keyed on `case_id` (partition key) with a GSI on `provider_id` so the assembly step can look up prior cases for a given provider. You create these once, up front; this file does not do that for you.
- **All numeric scores must be Decimal.** DynamoDB rejects Python `float` for numeric attributes (precision loss, which for z-scores and severity aggregation is a quiet disaster over thousands of case writes). Every rate, z-score, and probability passes through `Decimal` on its way into DynamoDB and back out. The example code handles this so you see the pattern.
- **All example provider, claim, and patient data is synthetic.** Provider IDs, NPIs, CPT codes, claim IDs, and patient IDs in the sample data and outputs are illustrative and do not refer to any real people, providers, or services. Use [Synthea](https://github.com/synthetichealth/synthea) in a development environment and never use real PHI in a teaching example.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here: thresholds, feature lists, peer-group fallbacks, resource names, and the code families. These are the knobs you will change most often between environments.

```python
import io
import json
import logging
import math
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import boto3
import joblib
import numpy as np
import pandas as pd
from botocore.config import Config
from boto3.dynamodb.conditions import Key
from sklearn.ensemble import IsolationForest

# Structured logging. In production, ship JSON-formatted records to CloudWatch
# Logs Insights. Claim and provider records are PHI-adjacent (an NPI plus a
# date range plus a patient population is re-identifying even without names),
# so we log structural metadata only. Never log full claim bodies, patient
# identifiers, or full feature vectors in regular application logs.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry mode handles DynamoDB, Athena, and SageMaker throttling
# with exponential backoff and jitter. The monthly scoring job is naturally
# bursty (one big batch once a month), and adaptive mode keeps burst windows
# from cascading into retry storms against the feature store and warehouse.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

REGION = "us-east-1"
dynamodb = boto3.resource("dynamodb", region_name=REGION, config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", region_name=REGION, config=BOTO3_RETRY_CONFIG)
cloudwatch = boto3.client("cloudwatch", region_name=REGION, config=BOTO3_RETRY_CONFIG)
athena = boto3.client("athena", region_name=REGION, config=BOTO3_RETRY_CONFIG)
sns = boto3.client("sns", region_name=REGION, config=BOTO3_RETRY_CONFIG)
eventbridge = boto3.client("events", region_name=REGION, config=BOTO3_RETRY_CONFIG)
featurestore_runtime = boto3.client(
    "sagemaker-featurestore-runtime", region_name=REGION, config=BOTO3_RETRY_CONFIG
)

# --- Resource Names ---
# Fill in with your actual resource names.
PROVIDER_PEER_GROUPS_TABLE = "provider-peer-groups"
PEER_GROUP_STATS_TABLE = "peer-group-statistics"
CASE_REGISTRY_TABLE = "case-registry"

PROVIDER_FEATURES_FG = "provider-period-features"    # SageMaker Feature Store feature group
FEATURES_BUCKET = "my-provider-features"
ANOMALY_SIGNALS_BUCKET = "my-anomaly-signals"
LABELS_BUCKET = "my-billing-anomaly-labels"
MODEL_ARTIFACTS_BUCKET = "my-billing-anomaly-model-artifacts"
ATHENA_OUTPUT_LOCATION = "s3://my-athena-results/billing-anomaly/"
ATHENA_DATABASE = "claims_warehouse"
ANALYST_NOTIFICATION_TOPIC_ARN = (
    "arn:aws:sns:us-east-1:123456789012:payment-integrity-new-case"
)
EVENT_BUS_NAME = "payment-integrity-events"

# Deploy-time guardrail: catch unreplaced example values.
assert "123456789012" not in ANALYST_NOTIFICATION_TOPIC_ARN or __name__ != "__production__", \
    "ANALYST_NOTIFICATION_TOPIC_ARN still uses the example AWS account ID. Replace before deploying."

# --- Scorer Version ---
# Every anomaly signal, case record, and captured label records the scorer
# version. This is how retraining picks its training window and how
# monitoring attributes regressions to a specific version of the pipeline.
SCORER_VERSION = "anomaly-v1.0"
LABEL_DERIVATION_VERSION = "label-v1.0"

# --- Minimum Volume Guards ---
# Providers with fewer than MIN_CLAIMS_FOR_STATS claims in a period produce
# unstable aggregate statistics. Peer groups with fewer than
# PEER_GROUP_MIN_SIZE members produce unstable peer statistics. Both guards
# exist to keep the signal-to-noise ratio defensible on the sparse tails.
MIN_CLAIMS_FOR_STATS = 30
MIN_EM_CLAIMS_FOR_DISTRIBUTION = 15
PEER_GROUP_MIN_SIZE = 30

# --- Anomaly Thresholds ---
# Z_SIGNAL_THRESHOLD: flag peer z-scores whose absolute value is at or
# above this bound. 2.5 is a reasonable starting point; lower values create
# more flags (good for recall, bad for analyst workload); higher values
# reduce flag volume but miss the boundary cases.
# CUSUM_H: CUSUM decision boundary in units of the target standard
# deviation. 4.0 is a common default that detects a ~1-sigma sustained
# shift within about 8 observations.
# CUSUM_K: slack parameter; ~half of the shift size you want to detect
# quickly. 0.5 is the standard default.
# ISOLATION_FOREST_THRESHOLD: scores below (more negative than) this cut
# are treated as anomalies. Isolation Forest scores are roughly in
# [-0.5, 0.5] with negative more anomalous; -0.1 is a conservative cut.
Z_SIGNAL_THRESHOLD = Decimal("2.5")
CUSUM_H = 4.0
CUSUM_K = 0.5
ISOLATION_FOREST_THRESHOLD = Decimal("-0.10")

# --- Case Routing Thresholds ---
# Severity bands combine signal count, peak z-score, CUSUM shift magnitude,
# and dollar exposure. The routing layer maps the overall severity band
# and the signal types to one of three queues.
SEVERITY_HIGH_SIGNALS = 3            # 3+ signals is automatically high
SEVERITY_HIGH_ZSCORE = Decimal("4.0")  # any single signal at 4+ sigma is high
HIGH_SEVERITY_EXPOSURE = Decimal("100000")  # dollar exposure that pushes medium to high

# Soft cap on how many new cases land in the payment-integrity queue per
# monthly cycle. Excess high-severity cases go on the watch list with a
# priority flag so nothing falls off the map.
PAYMENT_INTEGRITY_QUEUE_CAPACITY = 40

# --- Features Tracked for Anomaly Scoring ---
# QUANTITATIVE_FEATURES get peer-z-score comparison. CUSUM_TRACKED_FEATURES
# get control-chart comparison against the provider's own recent history.
# The two lists overlap but are not identical: code entropy makes sense
# as a peer comparison but the provider's own entropy time series is where
# the drift signal lives.
QUANTITATIVE_FEATURES = [
    "avg_billed_per_claim",
    "codes_per_claim_mean",
    "code_entropy",
    "em_avg_level",
    "modifier_25_rate",
    "modifier_59_rate",
    "modifier_22_rate",
    "avg_units_per_time_claim",
    "unique_patients_per_claim",
]

CUSUM_TRACKED_FEATURES = [
    "em_avg_level",
    "modifier_25_rate",
    "modifier_59_rate",
    "avg_billed_per_claim",
    "codes_per_claim_mean",
]

# --- E&M Code Set ---
# The main E/M office-or-outpatient code families. Real deployments use a
# much larger crosswalk including hospital, nursing facility, home, and
# specialty E/M ranges. Level (1-5) is derived from the last digit for
# the standard new/established ranges.
EM_CODES = {
    # Office or outpatient, established patient (levels 1-5).
    "99211": 1, "99212": 2, "99213": 3, "99214": 4, "99215": 5,
    # Office or outpatient, new patient (levels 1-5).
    "99201": 1, "99202": 2, "99203": 3, "99204": 4, "99205": 5,
}

# --- Time-based CPT Codes ---
# Codes billed in time units (often 15-minute increments). Used for the
# "unit mode fraction" feature that catches suspicious rounding at an
# exact unit boundary.
TIME_BASED_CODES = {
    "97110", "97112", "97140", "97530",   # PT
    "90832", "90834", "90837",             # Psychotherapy
    "99497", "99498",                      # Advance care planning
    "G0299", "G0300",                      # Home-health skilled nursing
}

# --- Peer Group Fallback Order ---
# Each tuple is an ordered list of attributes to use as the peer-group
# partition key. We try each in turn and use the first one that yields
# a group at least PEER_GROUP_MIN_SIZE in size. A too-narrow key has
# few members (unstable stats); a too-broad key masks specialty-specific
# patterns. Hierarchical fallback is the standard approach.
PEER_GROUP_FALLBACK_ORDER = [
    ("specialty", "subspecialty", "region", "setting"),
    ("specialty", "subspecialty", "region"),
    ("specialty", "region"),
    ("specialty", "setting"),
    ("specialty",),
]


def _to_decimal(value) -> Decimal:
    """
    Coerce numeric input into Decimal for DynamoDB and for downstream math.

    DynamoDB rejects float. Always pass Decimal. Quantizing to four decimal
    places keeps the storage format predictable without losing meaningful
    precision for probabilities, rates, or z-scores.
    """
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0.0000")
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return Decimal("0.0000")
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _decimal_to_float(value):
    """Recursively coerce Decimals to floats for JSON output or ML input."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _decimal_to_float(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decimal_to_float(v) for v in value]
    return value
```

---

## Step 1: Roll Up Claims to Provider-Period Features

*The pseudocode calls this `rollup_provider_period(period_start, period_end)`. The function scans adjudicated claims for a period, groups them by canonical provider ID, and computes a feature vector per provider. The output is written to SageMaker Feature Store so downstream steps can read features consistently, with point-in-time correctness for later training.*

The correctness property that matters most here is **stable provider identity resolution**. A provider who bills under multiple NPIs or tax IDs needs to be resolved to a single canonical entity, otherwise their behavior is split across rows and the anomaly signal dilutes. Recipe 5.x (entity resolution) covers that in depth; for this teaching example we assume the claims frame already carries a `provider_id` column that represents the canonical entity.

Two kinds of problem show up if you skip or misconfigure this step. First, noise from small providers: a practice with 20 claims per month has wild variance in every aggregate, and naive z-scores flag them every cycle. Second, provider fragmentation: a multi-NPI provider's anomalous behavior is split across their NPIs and no single NPI looks clearly off-norm.

```python
def rollup_provider_period(claims_df: pd.DataFrame, period_start: str, period_end: str) -> pd.DataFrame:
    """
    Aggregate adjudicated claims into one feature vector per provider.

    `claims_df` columns required:
      provider_id, claim_id, patient_id, service_date,
      procedure_code, modifiers (list[str]), billed_amount, units,
      place_of_service, diagnosis_codes (list[str])

    Returns a DataFrame with one row per provider_id, ready to be written
    to the Feature Store for the (period_start, period_end) event time.
    """
    if claims_df.empty:
        logger.warning("empty_claims_frame", extra={"period": period_start})
        return pd.DataFrame()

    feature_rows = []

    # Group the claims frame by provider. In production this runs as a
    # Glue Spark job over tens of millions of rows; pandas handles the
    # tens-of-thousands-of-rows teaching case without complaint.
    for provider_id, provider_claims in claims_df.groupby("provider_id"):
        claim_count = len(provider_claims)

        # Guard against low-volume providers. Below the threshold, aggregate
        # stats are too noisy to be useful and the downstream scoring step
        # would flag them constantly on pure variance.
        if claim_count < MIN_CLAIMS_FOR_STATS:
            continue

        features = _compute_provider_features(
            provider_id=provider_id,
            provider_claims=provider_claims,
            period_start=period_start,
            period_end=period_end,
        )
        feature_rows.append(features)

    features_df = pd.DataFrame(feature_rows)
    logger.info("rollup_complete", extra={
        "period": period_start,
        "providers_scored": len(features_df),
        "providers_skipped_low_volume": claims_df["provider_id"].nunique() - len(features_df),
    })
    return features_df


def _compute_provider_features(
    provider_id: str,
    provider_claims: pd.DataFrame,
    period_start: str,
    period_end: str,
) -> dict:
    """
    Compute one provider's feature vector for one period.

    Broken into small helpers so each block can be tested on its own. The
    feature list tracks the QUANTITATIVE_FEATURES constant at the top of
    the module; any new feature needs to be added in both places.
    """
    claim_count = len(provider_claims)

    # --- Code mix features ---
    # A histogram of procedure codes plus an entropy score that captures
    # how "spread out" the provider's code mix is. A sudden drop in entropy
    # (provider narrows to a handful of codes) is a common anomaly shape.
    code_counts = Counter(provider_claims["procedure_code"])
    code_entropy = _shannon_entropy(code_counts)
    top_codes = dict(code_counts.most_common(20))
    top_code_distribution = {
        code: count / claim_count for code, count in top_codes.items()
    }

    # --- E&M level distribution ---
    # For providers who bill E&M, the distribution across levels 1-5 is
    # one of the strongest signals in the entire system. Only compute if
    # the provider has enough E&M claims to produce stable stats.
    em_claims = provider_claims[provider_claims["procedure_code"].isin(EM_CODES.keys())]
    em_distribution = None
    em_avg_level = None
    if len(em_claims) >= MIN_EM_CLAIMS_FOR_DISTRIBUTION:
        em_levels = em_claims["procedure_code"].map(EM_CODES)
        em_distribution = {
            f"level_{level}": (em_levels == level).sum() / len(em_claims)
            for level in range(1, 6)
        }
        em_avg_level = float(em_levels.mean())

    # --- Modifier rates ---
    # "Has modifier X on the claim" is a per-claim binary; we average over
    # all claims to get the per-claim rate. Modifiers 25, 59, and 22 are
    # the most frequently abused and the ones payment integrity teams
    # watch most closely.
    modifier_25_rate = _modifier_rate(provider_claims, "25")
    modifier_59_rate = _modifier_rate(provider_claims, "59")
    modifier_22_rate = _modifier_rate(provider_claims, "22")

    # --- Units for time-based codes ---
    # Codes billed in 15-minute increments should show a natural spread of
    # unit counts if time is being measured. A sharp mode at a single unit
    # value (everyone gets exactly 4 units = 1 hour) is the "unit rounding"
    # signal: the time is being bucketed, not measured.
    time_based_claims = provider_claims[provider_claims["procedure_code"].isin(TIME_BASED_CODES)]
    avg_units_per_time_claim = 0.0
    unit_mode_fraction = 0.0
    if len(time_based_claims) > 0:
        avg_units_per_time_claim = float(time_based_claims["units"].mean())
        unit_counts = Counter(time_based_claims["units"])
        unit_mode_fraction = unit_counts.most_common(1)[0][1] / len(time_based_claims)

    # --- Volume and dollar features ---
    total_billed = float(provider_claims["billed_amount"].sum())
    avg_billed_per_claim = float(provider_claims["billed_amount"].mean())
    unique_patients = provider_claims["patient_id"].nunique()
    unique_patients_per_claim = unique_patients / claim_count

    # codes_per_claim measures how many procedure codes were billed per
    # encounter. For this to be right, you need to know how claims roll up
    # to encounters; a simple proxy is "codes per claim," which for most
    # professional claims is the encounter itself.
    codes_per_claim_mean = float(provider_claims.groupby("claim_id").size().mean())
    codes_per_claim_stddev = float(provider_claims.groupby("claim_id").size().std() or 0.0)

    return {
        "provider_id":                provider_id,
        "period_start":               period_start,
        "period_end":                 period_end,
        "claim_count":                claim_count,
        "unique_patient_count":       unique_patients,
        "total_billed":               total_billed,
        "avg_billed_per_claim":       avg_billed_per_claim,
        "codes_per_claim_mean":       codes_per_claim_mean,
        "codes_per_claim_stddev":     codes_per_claim_stddev,
        "code_entropy":               code_entropy,
        "top_code_distribution":      top_code_distribution,
        "em_distribution":            em_distribution,
        "em_avg_level":               em_avg_level,
        "modifier_25_rate":           modifier_25_rate,
        "modifier_59_rate":           modifier_59_rate,
        "modifier_22_rate":           modifier_22_rate,
        "avg_units_per_time_claim":   avg_units_per_time_claim,
        "unit_mode_fraction":         unit_mode_fraction,
        "unique_patients_per_claim":  unique_patients_per_claim,
    }


def _shannon_entropy(counts: Counter) -> float:
    """
    Shannon entropy of a distribution over code counts. Used as a single-
    number summary of how concentrated a provider's code mix is. Lower
    entropy = more concentrated (one or two codes dominate); higher
    entropy = more diverse code mix.
    """
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return -sum(
        (c / total) * math.log(c / total)
        for c in counts.values()
        if c > 0
    )


def _modifier_rate(claims: pd.DataFrame, modifier: str) -> float:
    """
    Fraction of claims in the frame that carry the given modifier.

    `modifiers` column is a list[str] per row; we check membership, not
    equality. A claim with modifiers [25, 59] counts toward both the
    modifier-25 rate and the modifier-59 rate.
    """
    has_modifier = claims["modifiers"].apply(lambda ms: modifier in (ms or []))
    return float(has_modifier.mean())


def write_features_to_feature_store(features_df: pd.DataFrame) -> None:
    """
    Persist the per-provider-period features to SageMaker Feature Store.
    The online store supports the scoring step's single-record reads; the
    offline store is where the training data comes from when we eventually
    build the supervised classifier.
    """
    if features_df.empty:
        return

    for _, row in features_df.iterrows():
        # Feature Store values are strings over the wire; complex fields
        # (dicts) get JSON-encoded. The scorer decodes them back.
        record = []
        for col, value in row.items():
            if isinstance(value, dict):
                value_str = json.dumps(value)
            elif value is None:
                continue  # null features get skipped; scorer treats missing as default
            else:
                value_str = str(value)
            record.append({"FeatureName": col, "ValueAsString": value_str})

        # The Feature Store expects an event_time; we use the period end
        # as the canonical timestamp for the observation.
        record.append({"FeatureName": "event_time", "ValueAsString": str(row["period_end"])})

        featurestore_runtime.put_record(
            FeatureGroupName=PROVIDER_FEATURES_FG,
            Record=record,
        )
```

---

## Step 2: Assign Peer Groups and Compute Peer Distributions

*The pseudocode calls this `assign_peer_groups()` followed by per-group distribution statistics. This runs quarterly rather than monthly because provider specialty and practice setting change rarely. For each active provider, walk the fallback order until a peer group hits the minimum size, then compute the distribution statistics (mean, stddev, percentiles) for every quantitative feature, leave-one-out.*

The single most consequential design decision in this whole recipe is the peer group definition. Whatever groups you define on day one you will redefine within three months based on what the payment integrity team tells you. Make the fallback order config-driven (the `PEER_GROUP_FALLBACK_ORDER` constant at the top of the module) rather than hard-coded through the logic; you will edit it.

The one subtle bit to get right: leave-one-out. The peer-group statistics used to score provider X must not include provider X in the computation. If you leave them in, an extreme outlier pulls the group mean toward themselves and their own z-score is artificially low. The code below does this by subtracting the provider's own contribution from the pre-computed group mean and variance, which is the standard trick; a simpler but more expensive alternative is to recompute the mean and stddev excluding the provider each time they are scored.

```python
def assign_peer_groups(provider_master_df: pd.DataFrame) -> pd.DataFrame:
    """
    Assign each active provider to a peer group by walking the fallback
    order. Returns a copy of the provider master with a `peer_group_key`
    column populated.

    `provider_master_df` columns required:
      provider_id, specialty, subspecialty, region, setting
    """
    assignments = []
    group_sizes = _count_all_candidate_groups(provider_master_df)

    for _, provider in provider_master_df.iterrows():
        assigned_key = None
        for attribute_order in PEER_GROUP_FALLBACK_ORDER:
            candidate_key = tuple(provider.get(attr) for attr in attribute_order)
            # Any attribute being null drops this candidate; try the next.
            if any(v is None or (isinstance(v, float) and math.isnan(v)) for v in candidate_key):
                continue
            if group_sizes.get((attribute_order, candidate_key), 0) >= PEER_GROUP_MIN_SIZE:
                assigned_key = (attribute_order, candidate_key)
                break

        if assigned_key is None:
            # No fallback level produced a big enough group; flag this
            # provider so the scoring step knows to skip peer comparisons.
            assignments.append({
                "provider_id":       provider["provider_id"],
                "peer_group_attrs":  None,
                "peer_group_key":    None,
                "peer_group_size":   0,
            })
            continue

        attribute_order, key_values = assigned_key
        assignments.append({
            "provider_id":       provider["provider_id"],
            "peer_group_attrs":  list(attribute_order),
            "peer_group_key":    "|".join(str(v) for v in key_values),
            "peer_group_size":   group_sizes[assigned_key],
        })

    assignments_df = pd.DataFrame(assignments)
    merged = provider_master_df.merge(
        assignments_df, on="provider_id", how="left"
    )

    # Write each provider's peer group membership to DynamoDB. The scoring
    # step reads it single-record per provider; we write the whole batch
    # so the state is consistent across the run.
    table = dynamodb.Table(PROVIDER_PEER_GROUPS_TABLE)
    with table.batch_writer() as batch:
        for _, row in merged.iterrows():
            batch.put_item(Item={
                "provider_id":      row["provider_id"],
                "peer_group_attrs": row["peer_group_attrs"] if row["peer_group_attrs"] else None,
                "peer_group_key":   row["peer_group_key"],
                "peer_group_size":  int(row["peer_group_size"]) if row["peer_group_size"] else 0,
                "assigned_at":      datetime.now(timezone.utc).isoformat(),
            })

    return merged


def _count_all_candidate_groups(provider_master: pd.DataFrame) -> dict:
    """
    Pre-compute the size of every candidate peer group across every
    fallback level. Returns a dict keyed on (attribute_order, key_tuple)
    so the main assignment loop can check sizes in O(1).
    """
    sizes = {}
    for attribute_order in PEER_GROUP_FALLBACK_ORDER:
        grouped = provider_master.groupby(list(attribute_order)).size()
        for key_tuple, count in grouped.items():
            if not isinstance(key_tuple, tuple):
                key_tuple = (key_tuple,)   # single-attribute grouping returns scalars
            sizes[(attribute_order, key_tuple)] = count
    return sizes


def compute_peer_group_statistics(features_df: pd.DataFrame, peer_assignments: pd.DataFrame) -> None:
    """
    For each peer group and each quantitative feature, compute the
    distribution statistics (mean, stddev, percentiles) over the group
    members' recent period features. The statistics are what the scoring
    step compares each provider's current value against.

    `features_df` is the output of the last N periods of the rollup,
    concatenated. Using several periods of history rather than just the
    current period means the reference statistics reflect a stable baseline
    rather than the specific period we're scoring against.
    """
    # Attach peer_group_key to every feature row.
    enriched = features_df.merge(
        peer_assignments[["provider_id", "peer_group_key"]],
        on="provider_id",
        how="left",
    )

    # Iterate peer groups. For each group and each feature, compute the
    # stats over the group's last N provider-period observations. The
    # "leave-one-out" correction happens at scoring time by subtracting
    # the target provider's contribution from the pre-computed aggregates.
    table = dynamodb.Table(PEER_GROUP_STATS_TABLE)
    for peer_group_key, group_df in enriched.groupby("peer_group_key"):
        if peer_group_key is None or pd.isna(peer_group_key):
            continue
        if len(group_df) < PEER_GROUP_MIN_SIZE:
            continue

        for feature_name in QUANTITATIVE_FEATURES:
            values = group_df[feature_name].dropna().astype(float)
            if len(values) < PEER_GROUP_MIN_SIZE:
                continue

            stats = {
                "count":  int(len(values)),
                "sum":    float(values.sum()),
                "sumsq":  float((values ** 2).sum()),
                "mean":   float(values.mean()),
                "stddev": float(values.std(ddof=1) or 0.0),
                "p50":    float(values.quantile(0.50)),
                "p90":    float(values.quantile(0.90)),
                "p95":    float(values.quantile(0.95)),
                "p99":    float(values.quantile(0.99)),
            }
            # Decimals for DynamoDB; percentiles get stored so the analyst
            # UI can show "this provider is at P95 of peers" without a
            # recomputation step.
            table.put_item(Item={
                "peer_group_key": peer_group_key,
                "feature_name":   feature_name,
                "stats":          {k: _to_decimal(v) for k, v in stats.items()},
                "computed_at":    datetime.now(timezone.utc).isoformat(),
            })


def _leave_one_out_stats(group_stats: dict, provider_value: float) -> tuple:
    """
    Compute the leave-one-out mean and stddev for a peer group given the
    cached aggregates (count, sum, sumsq) and the provider's current value.
    Standard statistical trick: the group's aggregates are sufficient
    statistics, and removing one observation is an O(1) operation.
    """
    n = int(group_stats["count"])
    if n <= 1:
        return None, None
    s = float(group_stats["sum"]) - provider_value
    ssq = float(group_stats["sumsq"]) - (provider_value ** 2)
    loo_mean = s / (n - 1)
    loo_variance = (ssq - (n - 1) * loo_mean ** 2) / (n - 2) if n > 2 else 0.0
    loo_stddev = math.sqrt(max(loo_variance, 0.0))
    return loo_mean, loo_stddev
```

---

## Step 3: Score Anomalies Across the Three Axes

*The pseudocode calls this `score_anomalies(period_start, period_end)`. For each provider's current-period feature vector, compute signals from three separate families: peer z-scores (against the leave-one-out peer distribution), self-history CUSUM (against the provider's own recent months of the same feature), and a multivariate Isolation Forest score. Each family is scored independently and the signals are stored separately, so the case assembly step can explain which signals fired and why.*

The design choice that matters most here is to not collapse the signals into a single score prematurely. Analysts need to see "this provider fired on peer comparison, not on self-drift" differently from "this provider drifted from their own history but is still within peer range." A single composite score hides that distinction and makes cases harder to triage.

The Isolation Forest model is trained once per quarter on a population sample of provider-period vectors (see the retraining sketch at the end). Here we just score the current period against the loaded model.

```python
# Module-level Isolation Forest handle. Loaded once per process from S3 so
# subsequent calls reuse the deserialized estimator. In a SageMaker
# Processing job, this lives outside the main loop so the model load cost
# is paid once per job.
_ISOLATION_FOREST = None
_ISOLATION_FOREST_META = None


def _load_isolation_forest(model_key: str = "current/isolation_forest.joblib") -> None:
    """
    Download the current Isolation Forest artifact from S3 and deserialize
    it. The artifact is produced by a quarterly training job; see the
    sketch at the end of this file.
    """
    global _ISOLATION_FOREST, _ISOLATION_FOREST_META
    response = s3_client.get_object(Bucket=MODEL_ARTIFACTS_BUCKET, Key=model_key)
    payload = joblib.load(io.BytesIO(response["Body"].read()))
    _ISOLATION_FOREST = payload["model"]
    _ISOLATION_FOREST_META = payload["meta"]
    logger.info("isolation_forest_loaded", extra={"version": _ISOLATION_FOREST_META.get("version")})


def score_anomalies(
    features_df: pd.DataFrame,
    history_df: pd.DataFrame,
    peer_assignments: pd.DataFrame,
    period_start: str,
    period_end: str,
) -> list:
    """
    Run the three anomaly-signal families against a period's features.

    `features_df` is the current period's provider features (output of the
    rollup). `history_df` is the last N months of the same features, used
    for the CUSUM self-comparison. `peer_assignments` is the output of
    Step 2.

    Returns a list of per-provider signal dicts. Each dict gets written
    to S3 as a JSON file so case assembly can pick them up.
    """
    if _ISOLATION_FOREST is None:
        try:
            _load_isolation_forest()
        except Exception as ex:
            logger.warning("isolation_forest_not_available", extra={"error": str(ex)})
            # Continue without the multivariate signal; the statistical
            # signals still run.

    # Index helpers so the per-provider lookups are O(1) instead of
    # scanning the frame in every iteration.
    history_by_provider = {
        pid: group.sort_values("period_start")
        for pid, group in history_df.groupby("provider_id")
    }
    peer_key_by_provider = dict(
        zip(peer_assignments["provider_id"], peer_assignments["peer_group_key"])
    )

    all_signals = []
    peer_stats_table = dynamodb.Table(PEER_GROUP_STATS_TABLE)

    for _, record in features_df.iterrows():
        provider_id = record["provider_id"]
        peer_key = peer_key_by_provider.get(provider_id)

        signals = []

        # --- Signal family 1: Peer z-scores ---
        if peer_key:
            signals.extend(_score_peer_zscores(record, peer_key, peer_stats_table))

        # --- Signal family 2: Self-history CUSUM ---
        provider_history = history_by_provider.get(provider_id)
        if provider_history is not None and len(provider_history) >= 6:
            signals.extend(_score_self_cusum(record, provider_history))

        # --- Signal family 3: Multivariate Isolation Forest ---
        if _ISOLATION_FOREST is not None:
            if_signal = _score_isolation_forest(record)
            if if_signal is not None:
                signals.append(if_signal)

        if signals:
            payload = {
                "provider_id":  provider_id,
                "period_start": period_start,
                "period_end":   period_end,
                "peer_group":   peer_key,
                "signals":      signals,
                "scorer_version": SCORER_VERSION,
                "scored_at":    datetime.now(timezone.utc).isoformat(),
            }
            all_signals.append(payload)
            _write_signal_payload(payload)

    logger.info("scoring_complete", extra={
        "period": period_start,
        "providers_with_signals": len(all_signals),
    })
    return all_signals


def _score_peer_zscores(record: pd.Series, peer_key: str, peer_stats_table) -> list:
    """
    Compute leave-one-out z-scores for each quantitative feature against
    the provider's peer group. Returns signal dicts for any feature whose
    |z| clears Z_SIGNAL_THRESHOLD.
    """
    fired = []
    for feature_name in QUANTITATIVE_FEATURES:
        provider_value = record.get(feature_name)
        if provider_value is None or pd.isna(provider_value):
            continue

        response = peer_stats_table.get_item(Key={
            "peer_group_key": peer_key,
            "feature_name":   feature_name,
        })
        cached = response.get("Item")
        if not cached:
            continue

        raw_stats = _decimal_to_float(cached["stats"])
        loo_mean, loo_stddev = _leave_one_out_stats(raw_stats, float(provider_value))
        if loo_stddev is None or loo_stddev == 0.0:
            continue

        z = (float(provider_value) - loo_mean) / loo_stddev
        if abs(z) >= float(Z_SIGNAL_THRESHOLD):
            fired.append({
                "type":        "peer_zscore",
                "feature":     feature_name,
                "value":       _to_decimal(provider_value),
                "peer_mean":   _to_decimal(loo_mean),
                "peer_stddev": _to_decimal(loo_stddev),
                "zscore":      _to_decimal(z),
                "severity":    _zscore_to_severity(z),
            })
    return fired


def _score_self_cusum(record: pd.Series, provider_history: pd.DataFrame) -> list:
    """
    Two-sided CUSUM on each CUSUM-tracked feature against the provider's
    own rolling baseline. The target value is the mean of the first half
    of the history (pre-change reference); the shift we watch for is
    anything that accumulates to outside the control band.

    Classic SPC adapted to a monthly-period setup. Slack (K) and decision
    boundary (H) are tuned from the constants at the top of the module.
    """
    fired = []
    for feature_name in CUSUM_TRACKED_FEATURES:
        series = provider_history[feature_name].dropna().astype(float).tolist()
        if len(series) < 6:
            continue

        # Use the first half as the reference baseline.
        split = len(series) // 2
        baseline = series[:split]
        baseline_mean = sum(baseline) / len(baseline)
        baseline_stddev = pd.Series(baseline).std(ddof=1) or 1.0

        k = CUSUM_K * baseline_stddev
        h = CUSUM_H * baseline_stddev

        cusum_pos = 0.0
        cusum_neg = 0.0
        signal_period = None
        for i, value in enumerate(series):
            cusum_pos = max(0.0, cusum_pos + (value - baseline_mean) - k)
            cusum_neg = min(0.0, cusum_neg + (value - baseline_mean) + k)
            if cusum_pos > h or cusum_neg < -h:
                signal_period = i
                break

        if signal_period is not None:
            # The change point is the last period before accumulation crossed.
            post_change = series[signal_period:]
            post_mean = sum(post_change) / len(post_change)
            shift = post_mean - baseline_mean
            fired.append({
                "type":              "self_cusum",
                "feature":           feature_name,
                "change_point_idx":  signal_period,
                "pre_change_mean":   _to_decimal(baseline_mean),
                "post_change_mean":  _to_decimal(post_mean),
                "shift_magnitude":   _to_decimal(shift),
                "baseline_stddev":   _to_decimal(baseline_stddev),
                "severity":          _shift_to_severity(shift, baseline_stddev),
            })
    return fired


def _score_isolation_forest(record: pd.Series) -> Optional[dict]:
    """
    Multivariate Isolation Forest score for the current period vector.
    Returns a signal dict if the score clears the anomaly cut.

    Isolation Forest's raw scores are in roughly [-0.5, 0.5] with negative
    values indicating anomalies. We compute a lightweight per-feature
    contribution by z-scoring each input against the model's training-time
    mean and stddev; for real SHAP-style explanations, use the shap library
    on top of scikit-learn's decision_function outputs.
    """
    # Build the feature vector in the order the model was trained with.
    feature_names = _ISOLATION_FOREST_META["feature_names"]
    feature_vector = np.array([
        float(record.get(name, 0.0) or 0.0) for name in feature_names
    ]).reshape(1, -1)

    score = float(_ISOLATION_FOREST.score_samples(feature_vector)[0])
    if score > float(ISOLATION_FOREST_THRESHOLD):
        return None

    # Lightweight contribution: z-score each feature against its training-
    # time distribution and return the top-k most extreme ones. This is a
    # proxy for real SHAP contributions but is cheap and interpretable.
    training_means = _ISOLATION_FOREST_META["training_means"]
    training_stds = _ISOLATION_FOREST_META["training_stds"]
    contributions = []
    for i, name in enumerate(feature_names):
        std = training_stds[i]
        if std > 0:
            z = (feature_vector[0, i] - training_means[i]) / std
            contributions.append({
                "feature":      name,
                "value":        _to_decimal(feature_vector[0, i]),
                "training_mean": _to_decimal(training_means[i]),
                "zscore":       _to_decimal(z),
            })
    contributions.sort(key=lambda c: abs(float(c["zscore"])), reverse=True)

    return {
        "type":             "isolation_forest",
        "anomaly_score":    _to_decimal(score),
        "top_contributors": contributions[:5],
        "severity":         _if_score_to_severity(score),
    }


def _zscore_to_severity(z: float) -> str:
    absz = abs(z)
    if absz >= 4.0:
        return "high"
    if absz >= 3.0:
        return "medium"
    return "low"


def _shift_to_severity(shift: float, baseline_stddev: float) -> str:
    if baseline_stddev == 0:
        return "low"
    ratio = abs(shift) / baseline_stddev
    if ratio >= 2.0:
        return "high"
    if ratio >= 1.0:
        return "medium"
    return "low"


def _if_score_to_severity(score: float) -> str:
    # More negative = more anomalous.
    if score <= -0.25:
        return "high"
    if score <= -0.15:
        return "medium"
    return "low"


def _write_signal_payload(payload: dict) -> None:
    """
    Write one provider's signals to S3. The case-assembly step reads these
    files as its input. Partitioned by period for predictable retrieval.
    """
    period = payload["period_start"]
    key = f"period={period}/{payload['provider_id']}.json"
    s3_client.put_object(
        Bucket=ANOMALY_SIGNALS_BUCKET,
        Key=key,
        Body=json.dumps(_decimal_to_float(payload), default=str).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )
```

---

## Step 4: Assemble Cases and Attach Evidence

*The pseudocode calls this `assemble_cases(period_start)`. Read every anomaly-signal file for the period, consolidate multiple signals per provider into a single case record, pull representative claims from the warehouse as evidence, compute financial exposure, determine severity and routing, then write the case to the registry and notify the payment integrity team about anything that lands in the high-severity queue.*

This step is where most first-time builders under-invest. The raw scoring output is tens of thousands of individual signals per period. The operations team can work tens of cases per analyst per month. Case assembly is the step that translates "pile of signals" into "prioritized queue of provider-level narratives with evidence attached," which is the unit of work the analyst actually needs.

Evidence retrieval is the piece that takes real wall-clock time in production. For each flagged provider, the assembly step needs to pull a handful of representative claims from the warehouse that illustrate the pattern. The Athena query below is a simple `SELECT ... LIMIT` for teaching; a real implementation picks claims that are specifically illustrative of each signal (claims at the highest billed amount, claims with the flagged modifier, claims carrying the anomalous CPT code).

```python
def assemble_cases(period_start: str, period_end: str) -> list:
    """
    Consolidate per-provider signals into case records, attach evidence
    claims, rank by severity and exposure, and write to the case registry.

    Returns the list of created case records for downstream metric emission.
    """
    signal_payloads = _list_signal_payloads(period_start)
    if not signal_payloads:
        logger.info("no_signals_for_period", extra={"period": period_start})
        return []

    cases = []
    for payload in signal_payloads:
        case = _assemble_one_case(payload, period_start, period_end)
        if case is not None:
            cases.append(case)

    # Rank by overall severity and exposure so the capacity cap hits the
    # weakest cases first, not the strongest.
    cases.sort(
        key=lambda c: (
            _severity_rank(c["overall_severity"]),
            float(c["exposure_dollars"]),
        ),
        reverse=True,
    )

    # Apply the payment-integrity queue capacity cap. Overflow cases
    # still get created and routed, but to the watch list with a flag
    # that the analyst UI renders differently.
    pi_count = 0
    case_table = dynamodb.Table(CASE_REGISTRY_TABLE)
    for case in cases:
        if case["routing"] == "payment_integrity":
            if pi_count >= PAYMENT_INTEGRITY_QUEUE_CAPACITY:
                case["routing"] = "watch_list"
                case["routing_reason"] = "capacity_bump"
            else:
                pi_count += 1

        case_table.put_item(Item=_case_for_dynamo(case))

        if case["routing"] in ("payment_integrity", "clinical_review"):
            _notify_analysts(case)

        _emit_metric("case_created", dimensions={
            "routing":  case["routing"],
            "severity": case["overall_severity"],
        })

    logger.info("cases_assembled", extra={
        "period": period_start,
        "total_cases": len(cases),
        "payment_integrity": pi_count,
    })
    return cases


def _list_signal_payloads(period_start: str) -> list:
    """
    Enumerate all signal files for the period and load them as Python dicts.
    """
    prefix = f"period={period_start}/"
    paginator = s3_client.get_paginator("list_objects_v2")
    payloads = []
    for page in paginator.paginate(Bucket=ANOMALY_SIGNALS_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            response = s3_client.get_object(Bucket=ANOMALY_SIGNALS_BUCKET, Key=obj["Key"])
            payloads.append(json.loads(response["Body"].read()))
    return payloads


def _assemble_one_case(payload: dict, period_start: str, period_end: str) -> Optional[dict]:
    """
    Build a single case record from a provider's signal payload.
    """
    provider_id = payload["provider_id"]
    signals = payload["signals"]
    if not signals:
        return None

    # --- Persistence: how many prior consecutive periods were flagged? ---
    prior_cases = _query_prior_cases(provider_id, lookback_months=3)
    persistence = _count_consecutive_periods(prior_cases, ending_period=period_start)

    # --- Evidence: pull representative claims for the period ---
    evidence_claims = _pull_evidence_claims(
        provider_id=provider_id,
        period_start=period_start,
        period_end=period_end,
        signals=signals,
    )

    # --- Exposure: sum of billed amounts on the evidence claims ---
    exposure = sum(c.get("billed_amount", 0.0) for c in evidence_claims)

    # --- Severity: combine signal strength, persistence, and exposure ---
    overall_severity = _overall_severity(signals, persistence, exposure)
    routing = _determine_routing(overall_severity, signals)

    # --- Narrative summary ---
    narrative = _build_narrative(signals, persistence, exposure)

    return {
        "case_id":            f"CASE-{period_start.replace('-', '')}-{uuid.uuid4().hex[:8]}",
        "provider_id":        provider_id,
        "period_start":       period_start,
        "period_end":         period_end,
        "peer_group":         payload.get("peer_group"),
        "signals":            signals,
        "signal_count":       len(signals),
        "persistence":        persistence,
        "exposure_dollars":   exposure,
        "overall_severity":   overall_severity,
        "routing":            routing,
        "routing_reason":     "signal_severity",
        "evidence_claims":    [c["claim_id"] for c in evidence_claims],
        "narrative_summary":  narrative,
        "status":             "new",
        "assigned_analyst":   None,
        "scorer_version":     payload["scorer_version"],
        "created_at":         datetime.now(timezone.utc).isoformat(),
    }


def _query_prior_cases(provider_id: str, lookback_months: int) -> list:
    """
    Query the case-registry GSI on provider_id to find recent cases for
    this provider. Used to compute persistence across consecutive periods.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_months * 31)).date().isoformat()
    table = dynamodb.Table(CASE_REGISTRY_TABLE)
    response = table.query(
        IndexName="provider_id_index",
        KeyConditionExpression=Key("provider_id").eq(provider_id),
        FilterExpression=Key("period_start").gte(cutoff),
    )
    return response.get("Items", [])


def _count_consecutive_periods(prior_cases: list, ending_period: str) -> int:
    """
    Given a list of prior case records and the period we are currently
    assembling, count how many consecutive prior periods had a case for
    this provider. Persistence is one of the strongest indicators of a
    real anomaly versus a transient.
    """
    if not prior_cases:
        return 1

    # Parse the periods, sort descending, count consecutive-month streak.
    periods = sorted(
        [datetime.fromisoformat(c["period_start"]) for c in prior_cases],
        reverse=True,
    )
    cur = datetime.fromisoformat(ending_period)
    streak = 1
    for prev in periods:
        gap_days = (cur - prev).days
        # "Consecutive" allows some slack because periods are monthly
        # and months are uneven.
        if 20 <= gap_days <= 45:
            streak += 1
            cur = prev
        else:
            break
    return streak


def _pull_evidence_claims(
    provider_id: str,
    period_start: str,
    period_end: str,
    signals: list,
) -> list:
    """
    Query Athena for a handful of claims that illustrate the provider's
    behavior during the period. A real implementation picks claims
    targeted to each signal; this version pulls the five highest-dollar
    claims plus up to five claims carrying whichever modifier or code
    was called out by any signal.

    Returns a list of dicts with claim_id, service_date, procedure_code,
    billed_amount, modifiers.
    """
    query = f"""
        SELECT claim_id, service_date, procedure_code, billed_amount, modifiers
        FROM {ATHENA_DATABASE}.adjudicated_claims
        WHERE provider_id = '{_sql_escape(provider_id)}'
          AND service_date BETWEEN DATE '{period_start}' AND DATE '{period_end}'
        ORDER BY billed_amount DESC
        LIMIT 10
    """
    # In production, use parameterized queries with Athena's named
    # parameters. Inline string formatting is fine for a teaching example
    # because the parameter values come from our own system, not user
    # input; do not copy this pattern for any external-input code path.

    execution = athena.start_query_execution(
        QueryString=query,
        QueryExecutionContext={"Database": ATHENA_DATABASE},
        ResultConfiguration={"OutputLocation": ATHENA_OUTPUT_LOCATION},
    )
    execution_id = execution["QueryExecutionId"]

    # Poll for completion. Real deployments drive this via Step Functions
    # so the polling is framework-managed; here we loop for illustration.
    while True:
        state = athena.get_query_execution(QueryExecutionId=execution_id)
        status = state["QueryExecution"]["Status"]["State"]
        if status in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
    if status != "SUCCEEDED":
        logger.warning("evidence_query_failed", extra={
            "provider_id": provider_id,
            "status": status,
        })
        return []

    results = athena.get_query_results(QueryExecutionId=execution_id)
    rows = results.get("ResultSet", {}).get("Rows", [])
    if len(rows) < 2:
        return []

    header = [col["VarCharValue"] for col in rows[0]["Data"]]
    claims = []
    for row in rows[1:]:
        values = [col.get("VarCharValue", "") for col in row["Data"]]
        record = dict(zip(header, values))
        claims.append({
            "claim_id":       record.get("claim_id"),
            "service_date":   record.get("service_date"),
            "procedure_code": record.get("procedure_code"),
            "billed_amount":  float(record.get("billed_amount") or 0.0),
            "modifiers":      record.get("modifiers"),
        })
    return claims


def _sql_escape(value: str) -> str:
    """Minimal SQL string escape for our internal provider IDs."""
    return value.replace("'", "''")


def _overall_severity(signals: list, persistence: int, exposure: float) -> str:
    """
    Blend signal strength, persistence, and exposure into a single band.
    Tuning this function is where payment integrity teams spend a lot of
    their early-program effort; keep the rules here simple and explainable.
    """
    # Highest individual z-score across peer signals.
    peak_z = 0.0
    for s in signals:
        if s["type"] == "peer_zscore":
            peak_z = max(peak_z, abs(float(s["zscore"])))

    if len(signals) >= SEVERITY_HIGH_SIGNALS:
        return "high"
    if peak_z >= float(SEVERITY_HIGH_ZSCORE):
        return "high"
    if exposure >= float(HIGH_SEVERITY_EXPOSURE) and persistence >= 2:
        return "high"
    if persistence >= 3:
        return "high"
    if any(s["severity"] == "high" for s in signals):
        return "medium"
    if any(s["severity"] == "medium" for s in signals):
        return "medium"
    return "low"


def _determine_routing(severity: str, signals: list) -> str:
    """
    Map severity and signal types to one of three queues. Specialty-atypical
    (Isolation Forest primary) signals prefer clinical review; sustained
    drift (CUSUM + peer z-score together) prefers payment integrity.
    """
    if severity == "high":
        has_statistical = any(s["type"] in ("peer_zscore", "self_cusum") for s in signals)
        has_multivariate = any(s["type"] == "isolation_forest" for s in signals)
        if has_statistical and not has_multivariate:
            return "payment_integrity"
        if has_multivariate and not has_statistical:
            return "clinical_review"
        return "payment_integrity"
    if severity == "medium":
        if any(s["type"] == "isolation_forest" for s in signals):
            return "clinical_review"
        return "watch_list"
    return "watch_list"


def _severity_rank(severity: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(severity, 0)


def _build_narrative(signals: list, persistence: int, exposure: float) -> str:
    """
    Template-driven narrative summary for the analyst UI. Keep this
    deterministic and explainable rather than LLM-generated; an analyst
    who scans twenty cases an hour needs consistent phrasing.
    """
    parts = []

    peer_features = [s["feature"] for s in signals if s["type"] == "peer_zscore"]
    if peer_features:
        parts.append(
            f"Peer-group z-score signals fired on {len(peer_features)} feature(s): "
            f"{', '.join(peer_features)}."
        )

    cusum_features = [s for s in signals if s["type"] == "self_cusum"]
    if cusum_features:
        top = max(cusum_features, key=lambda s: abs(float(s["shift_magnitude"])))
        parts.append(
            f"Self-history CUSUM detected a sustained shift on {top['feature']}; "
            f"pre-change mean {float(top['pre_change_mean']):.3f}, "
            f"post-change mean {float(top['post_change_mean']):.3f}."
        )

    if_signals = [s for s in signals if s["type"] == "isolation_forest"]
    if if_signals:
        contributors = if_signals[0].get("top_contributors", [])[:3]
        names = [c["feature"] for c in contributors]
        parts.append(
            f"Multivariate detector scored this provider-period as an outlier; "
            f"top contributing features: {', '.join(names)}."
        )

    if persistence >= 2:
        parts.append(f"Pattern has persisted for {persistence} consecutive period(s).")
    parts.append(f"Billed-amount exposure on evidence claims: ${exposure:,.2f}.")

    return " ".join(parts)


def _case_for_dynamo(case: dict) -> dict:
    """
    Convert floats in the case record to Decimals for DynamoDB.
    """
    item = dict(case)
    item["exposure_dollars"] = _to_decimal(case["exposure_dollars"])
    item["signals"] = [_signal_for_dynamo(s) for s in case["signals"]]
    return item


def _signal_for_dynamo(signal: dict) -> dict:
    """Recursively coerce numerics in a signal dict to Decimal."""
    out = {}
    for key, value in signal.items():
        if isinstance(value, dict):
            out[key] = _signal_for_dynamo(value)
        elif isinstance(value, list):
            out[key] = [
                _signal_for_dynamo(v) if isinstance(v, dict) else v
                for v in value
            ]
        elif isinstance(value, float):
            out[key] = _to_decimal(value)
        elif isinstance(value, Decimal):
            out[key] = value
        else:
            out[key] = value
    return out


def _notify_analysts(case: dict) -> None:
    """
    Publish a minimal notification to the payment integrity SNS topic.
    The message carries the case id only; the analyst UI fetches the
    full record by id so the notification channel never carries PHI.
    """
    message = {
        "case_id":     case["case_id"],
        "provider_id": case["provider_id"],
        "severity":    case["overall_severity"],
        "routing":     case["routing"],
        "created_at":  case["created_at"],
    }
    sns.publish(
        TopicArn=ANALYST_NOTIFICATION_TOPIC_ARN,
        Message=json.dumps(message),
        Subject=f"New {case['overall_severity']}-severity case: {case['case_id']}",
    )


def _emit_metric(metric_name: str, value: int = 1, dimensions: dict = None) -> None:
    """
    Publish an operational metric to CloudWatch. Includes the scorer
    version as a standard dimension so regressions can be attributed to
    a specific pipeline version.
    """
    metric_dims = [{"Name": "ScorerVersion", "Value": SCORER_VERSION}]
    if dimensions:
        for k, v in dimensions.items():
            metric_dims.append({"Name": k, "Value": str(v)})
    try:
        cloudwatch.put_metric_data(
            Namespace="BillingAnomaly",
            MetricData=[{
                "MetricName": metric_name,
                "Value":      value,
                "Unit":       "Count",
                "Dimensions": metric_dims,
            }],
        )
    except Exception as ex:
        logger.warning("metric_emit_failed", extra={"metric": metric_name, "error": str(ex)})
```

---

## Step 5: Capture Investigation Outcomes and Close the Loop

*The pseudocode calls this `on_investigation_outcome(event)`. When an analyst resolves a case, the outcome flows through EventBridge to a Lambda. The Lambda updates the case record, derives a supervised training label, writes the label row to S3, and emits metrics. Over months, the labels accumulate into a dataset that feeds the optional supervised classifier.*

The label derivation is where organizations make different choices. The simple mapping below treats SIU referrals and significant adjustments as positives, "no finding" as negatives, and education-only as ambiguous (recorded but not used for supervised training). Revisit this mapping quarterly with the payment integrity team; their interpretation of each disposition evolves over time as their investigation playbook matures.

The trap to avoid here is self-confirming labels. If your existing system flags providers using criteria X, and those providers get investigated and labeled, the label dataset is heavily biased toward criteria X. A supervised model trained on this data re-learns criteria X and misses anything else. The "periodically random-sample unflagged providers for review" discipline in the main recipe is what breaks this loop; implement it in operational practice, not just the model training code.

```python
def on_investigation_outcome(event: dict) -> None:
    """
    Consumer for investigation-outcome events. Updates the case record,
    derives a training label when the outcome is definitive, writes the
    label row for future retraining, and emits metrics.

    Expected event fields:
      case_id, disposition, notes, resolved_at, resolved_by,
      dollars_recovered, referred_to_siu (bool), provider_educated (bool)
    """
    case_id = event["case_id"]
    table = dynamodb.Table(CASE_REGISTRY_TABLE)

    # Pull the case record. Must exist; outcome events for unknown cases
    # are a data error worth logging loudly.
    response = table.get_item(Key={"case_id": case_id})
    case = response.get("Item")
    if not case:
        logger.error("outcome_for_unknown_case", extra={"case_id": case_id})
        return

    # --- Update the case ---
    table.update_item(
        Key={"case_id": case_id},
        UpdateExpression=(
            "SET #status = :status, disposition = :disp, "
            "resolution_notes = :notes, resolved_at = :resolved_at, "
            "resolved_by = :resolved_by, dollars_recovered = :dollars"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status":       "closed",
            ":disp":         event["disposition"],
            ":notes":        event.get("notes", ""),
            ":resolved_at":  event["resolved_at"],
            ":resolved_by":  event["resolved_by"],
            ":dollars":      _to_decimal(event.get("dollars_recovered", 0.0)),
        },
    )

    # --- Derive the training label ---
    label = _derive_label(event["disposition"])

    # Only definitive outcomes become training data. "Ambiguous" labels
    # stay in the case record for reporting but do not feed the supervised
    # classifier because their signal is too noisy.
    if label in ("anomaly_confirmed", "anomaly_rejected"):
        training_row = {
            "case_id":                case["case_id"],
            "provider_id":            case["provider_id"],
            "period_start":           case["period_start"],
            "signals_at_scoring":     _decimal_to_float(case["signals"]),
            "exposure_dollars":       float(case["exposure_dollars"]),
            "persistence":            int(case["persistence"]),
            "overall_severity":       case["overall_severity"],
            "routing":                case["routing"],
            "peer_group":             case.get("peer_group"),
            "label":                  label,
            "label_derivation_version": LABEL_DERIVATION_VERSION,
            "outcome_lag_days":       _outcome_lag_days(case, event),
            "scorer_version":         case["scorer_version"],
            "labeled_at":             event["resolved_at"],
        }
        _write_label_to_s3(training_row, event["resolved_at"])

    # --- Metrics ---
    _emit_metric("case_closed", dimensions={
        "disposition": event["disposition"],
        "label":       label,
    })
    _emit_metric(
        "dollars_recovered",
        value=int(event.get("dollars_recovered", 0.0)),
        dimensions={"severity": case["overall_severity"]},
    )
    _emit_metric("outcome_by_severity", dimensions={
        "severity":    case["overall_severity"],
        "disposition": event["disposition"],
    })


def _derive_label(disposition: str) -> str:
    """
    Map a disposition to a supervised training label. See "The Labeling
    Problem" in the main recipe for the rationale.

    "anomaly_confirmed" and "anomaly_rejected" become supervised training
    rows. "ambiguous" is recorded but excluded from training. Anything
    unexpected gets logged as "unknown" and excluded.
    """
    if disposition in ("fraud_confirmed", "siu_referral", "significant_adjustment"):
        return "anomaly_confirmed"
    if disposition in ("no_finding", "legitimate_practice_variation"):
        return "anomaly_rejected"
    if disposition in ("education_only", "minor_adjustment"):
        return "ambiguous"
    return "unknown"


def _outcome_lag_days(case: dict, event: dict) -> int:
    """Days between case creation and investigation outcome."""
    created = datetime.fromisoformat(case["created_at"])
    resolved = datetime.fromisoformat(event["resolved_at"])
    return (resolved - created).days


def _write_label_to_s3(training_row: dict, resolved_at: str) -> None:
    """
    Append the labeled training row to the labels S3 bucket, partitioned
    by resolution date. In production we write Parquet (columnar access
    for Athena queries during retraining); JSON here for clarity.
    """
    resolved_dt = datetime.fromisoformat(resolved_at)
    key = (
        f"labels/year={resolved_dt.year:04d}/"
        f"month={resolved_dt.month:02d}/"
        f"day={resolved_dt.day:02d}/{uuid.uuid4()}.json"
    )
    s3_client.put_object(
        Bucket=LABELS_BUCKET,
        Key=key,
        Body=json.dumps(training_row, default=str).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )
```

---

## The Full Monthly Pipeline

Here is the end-to-end `run_monthly_pipeline` function that wires all five steps together. In production this is the body of a Step Functions state machine with each stage as a separate task; the Python version collapses them into a single driver for teaching.

```python
def run_monthly_pipeline(
    claims_df: pd.DataFrame,
    history_df: pd.DataFrame,
    provider_master_df: pd.DataFrame,
    period_start: str,
    period_end: str,
) -> list:
    """
    Orchestrate the full monthly pipeline against an in-memory claims frame.

    In production:
      - claims_df comes from a Glue job reading the claims warehouse
      - history_df comes from Feature Store's offline store
      - provider_master_df comes from the provider MDM system
      - each stage runs as a separate Step Functions task

    Returns the list of cases assembled for the period.
    """
    print(f"[1/4] Rolling up provider-period features for {period_start} to {period_end}...")
    features_df = rollup_provider_period(claims_df, period_start, period_end)
    if features_df.empty:
        print("       No features generated. Exiting.")
        return []
    write_features_to_feature_store(features_df)
    print(f"       {len(features_df)} providers passed the volume guard.")

    print("[2/4] Assigning peer groups and computing peer statistics...")
    peer_assignments = assign_peer_groups(provider_master_df)
    # Concatenate current features with history for the peer-stats computation.
    combined_for_stats = pd.concat([history_df, features_df], ignore_index=True)
    compute_peer_group_statistics(combined_for_stats, peer_assignments)
    assigned = peer_assignments["peer_group_key"].notna().sum()
    print(f"       {assigned}/{len(peer_assignments)} providers assigned to peer groups.")

    print("[3/4] Scoring anomalies across peer z-score, self CUSUM, and Isolation Forest...")
    signals = score_anomalies(features_df, history_df, peer_assignments, period_start, period_end)
    print(f"       {len(signals)} providers produced at least one signal.")

    print("[4/4] Assembling cases and notifying analysts...")
    cases = assemble_cases(period_start, period_end)
    print(f"       {len(cases)} cases created.")

    counts = Counter(c["routing"] for c in cases)
    for routing, count in counts.items():
        print(f"       routing={routing}: {count}")

    return cases


# --- Example usage ---
#
# A minimal example that exercises the pipeline with a small synthetic
# claims frame. Values are synthetic and do not refer to any real people,
# providers, or services. Use Synthea in a development environment; never
# use real PHI in a teaching example.
if __name__ == "__main__":
    # Synthetic claims. In a real run, load from the warehouse.
    sample_claims = pd.DataFrame([
        # --- An internist who shifted E&M distribution upward ---
        {"provider_id": "PRV-0044721", "claim_id": f"CLM-A-{i:04d}",
         "patient_id": f"PAT-A-{i % 40:03d}", "service_date": "2026-05-10",
         "procedure_code": "99214" if i < 60 else "99213",
         "modifiers": ["25"] if i % 3 == 0 else [],
         "billed_amount": 180.0, "units": 1, "place_of_service": "11",
         "diagnosis_codes": ["E11.9"]}
        for i in range(80)
    ] + [
        # --- A dermatology solo practice also billing PT codes (atypical) ---
        {"provider_id": "PRV-0062104", "claim_id": f"CLM-B-{i:04d}",
         "patient_id": f"PAT-B-{i % 30:03d}", "service_date": "2026-05-14",
         "procedure_code": ["17110", "97110", "97112"][i % 3],
         "modifiers": ["59"] if i % 4 == 0 else [],
         "billed_amount": 220.0, "units": 1, "place_of_service": "11",
         "diagnosis_codes": ["L70.0"]}
        for i in range(60)
    ])

    sample_history = pd.DataFrame()   # empty history for the example
    sample_provider_master = pd.DataFrame([
        {"provider_id": "PRV-0044721", "specialty": "internal_medicine",
         "subspecialty": "general", "region": "metro_5", "setting": "group"},
        {"provider_id": "PRV-0062104", "specialty": "dermatology",
         "subspecialty": "general", "region": "state_wide", "setting": "solo"},
    ])

    cases = run_monthly_pipeline(
        claims_df=sample_claims,
        history_df=sample_history,
        provider_master_df=sample_provider_master,
        period_start="2026-05-01",
        period_end="2026-05-31",
    )

    print()
    print("=== CASES ===")
    print(json.dumps(
        [{
            "case_id":          c["case_id"],
            "provider_id":      c["provider_id"],
            "signal_count":     c["signal_count"],
            "persistence":      c["persistence"],
            "exposure":         f"${c['exposure_dollars']:,.2f}",
            "overall_severity": c["overall_severity"],
            "routing":          c["routing"],
            "narrative":        c["narrative_summary"],
        } for c in cases],
        indent=2,
    ))
```

Running this against empty peer-group and history tables means the peer z-score and CUSUM paths stay silent (not enough data to produce stable stats), and the pipeline exercises mostly the Isolation Forest and case-assembly code paths. After a few months of accumulating history, all three signal families activate. A realistic dev-loop pattern is to seed 6-12 months of synthetic history with Synthea before turning the pipeline loose; the example above is intentionally minimal so the teaching concepts stay visible.

---

## A Sketch of the Quarterly Isolation Forest Retraining

The main recipe's `score_anomalies` step assumes a pre-trained Isolation Forest loaded from S3. That artifact is produced by a quarterly training job. What follows is the shape of the job so you can see what the scoring step is loading.

```python
def retrain_isolation_forest_quarterly(history_window_months: int = 6) -> dict:
    """
    Train a fresh Isolation Forest on the population of provider-period
    feature vectors from the last N months. The artifact goes to the model
    artifacts bucket under a versioned key and is then promoted to the
    'current' pointer.

    This function is in-process for the teaching example. In production,
    the same logic runs as a SageMaker Training Job with the feature
    store offline store as the input channel and a model-approval step
    before the 'current' pointer is updated.
    """
    # 1. Pull the training window from the feature store offline store.
    #    In production, this is an Athena query against the offline store's
    #    Parquet snapshot with partition pruning on event_time.
    training_df = _load_training_window(history_window_months)
    if len(training_df) < 500:
        logger.info("insufficient_data_for_retraining", extra={"rows": len(training_df)})
        return {"trained": False, "reason": "insufficient_data"}

    # 2. Build the input matrix in the canonical feature order. Fill
    #    missing values with the feature's median so a sparse column does
    #    not dominate the splits.
    feature_names = QUANTITATIVE_FEATURES
    X = training_df[feature_names].copy()
    medians = X.median()
    X = X.fillna(medians).astype(float)

    # 3. Standardize the training-time mean and stddev so the scoring step
    #    can compute z-style contributions against the same reference.
    training_means = X.mean().tolist()
    training_stds = X.std(ddof=0).replace(0, 1.0).tolist()

    # 4. Fit the Isolation Forest. contamination is a floor, not a target;
    #    setting it too high results in legitimate providers being flagged
    #    as the "nominal" anomaly rate. 0.02 is a conservative starting
    #    point; tune against your ground-truth investigation rate.
    model = IsolationForest(
        n_estimators=200,
        max_samples=min(256, len(X)),
        contamination=0.02,
        random_state=42,
    )
    model.fit(X)

    # 5. Serialize artifact and push to S3.
    buf = io.BytesIO()
    joblib.dump({
        "model": model,
        "meta": {
            "version":        f"iforest-{datetime.now(timezone.utc).strftime('%Y%m%d')}",
            "trained_at":     datetime.now(timezone.utc).isoformat(),
            "feature_names":  feature_names,
            "training_means": training_means,
            "training_stds":  training_stds,
            "training_rows":  int(len(X)),
            "contamination":  0.02,
        },
    }, buf)
    buf.seek(0)

    version_key = f"versions/iforest-{datetime.now(timezone.utc).strftime('%Y%m%d')}.joblib"
    s3_client.put_object(
        Bucket=MODEL_ARTIFACTS_BUCKET,
        Key=version_key,
        Body=buf.read(),
        ServerSideEncryption="aws:kms",
    )

    # 6. Update the 'current' pointer. In production, register in the
    #    SageMaker Model Registry and promote via a deployment pipeline
    #    rather than copying over 'current' directly.
    s3_client.copy_object(
        Bucket=MODEL_ARTIFACTS_BUCKET,
        Key="current/isolation_forest.joblib",
        CopySource={"Bucket": MODEL_ARTIFACTS_BUCKET, "Key": version_key},
        ServerSideEncryption="aws:kms",
    )

    return {"trained": True, "version_key": version_key, "rows": int(len(X))}


def _load_training_window(months: int) -> pd.DataFrame:
    """
    Load provider-period features for the training window. Placeholder;
    in production, run an Athena query against the Feature Store offline
    store with partition pruning on event_time.
    """
    # TODO: replace with Athena query against the offline store.
    return pd.DataFrame()
```

The supervised-classifier retraining (the `retrain_supervised_quarterly` function referenced in the main recipe) follows the same shape but requires at least a few hundred labeled cases, stratified by provider to avoid leakage, and adds a subgroup-regression gate before promotion. Its structure mirrors the sklearn pipeline from Recipe 3.2 (Patient No-Show Pattern Detection) so closely that it is not repeated here; the two recipes share most of the training-loop code and can share a utility module in a mature codebase.

---

## Gap to Production

Several things would need to change before you would deploy any of this.

**Real claims warehouse integration.** The monthly pipeline starts from a pandas DataFrame. In production, this is a Glue job reading from Redshift, Snowflake, or an Athena-over-Parquet lake, plus the provider master from an MDM system. Timezone handling on service dates and adjudication dates matters; always store UTC and render local time only at display. Budget weeks for this integration, not days.

**Idempotency.** The scoring and outcome-joiner paths write unconditionally. In production, EventBridge may redeliver the same outcome event (at-least-once semantics) and Step Functions tasks retry after transient failures. Use DynamoDB `ConditionExpression` with `attribute_not_exists(case_id)` on case writes, and handle `ConditionalCheckFailedException` as success. Outcome updates need an optimistic-lock attribute (a version counter plus ConditionExpression) so concurrent outcome events do not corrupt the case record.

**Error handling.** The example's error handling is minimal. In production, wrap each external call in try/except with structured logging, emit a failure metric, and route the affected provider to a dead-letter queue for operations review. Do not silently swallow DynamoDB throttling, Athena query failures, or S3 access-denied errors; each is a different class of problem with a different mitigation.

**Structured logging with PHI discipline.** The `logger.info` calls above log structural metadata only (provider IDs, period, signal counts). In production, use a JSON log formatter, ship logs to CloudWatch Logs with a log group encrypted by a customer-managed KMS key, and audit log content for unexpected PHI patterns (patient IDs, claim bodies, full feature vectors). A single accidental `logger.info("features: %s", features)` during debugging creates a PHI disclosure that survives in CloudWatch until the retention policy clears it.

**IAM scoping.** The permissions list in Setup covers what this code does, but production roles are scoped tightly. The aggregation Glue job's role needs no SNS permissions. The scoring Processing job's role needs no label-write permissions. The outreach Lambda's role needs no Feature Store write permissions. Scope to specific resource ARNs and review roles annually.

**VPC deployment.** In production, Glue jobs, SageMaker Processing, and Lambdas run inside a VPC with VPC endpoints for DynamoDB, S3, SageMaker Runtime, Feature Store Runtime, Athena, EventBridge, KMS, and CloudWatch Logs. SNS is a managed edge service and does not run in a VPC; ensure the data flowing to SNS is the minimum needed for the notification (case ID, severity, routing), not the full case record.

**KMS customer-managed keys.** All data at rest (DynamoDB tables, S3 buckets, Feature Store offline and online stores, CloudWatch Logs, Athena results) is encrypted with customer-managed KMS keys. The key policy restricts usage to the specific roles that need it; audit who is using each key via CloudTrail data events.

**SageMaker wrapping for the scorer.** The pandas-and-sklearn in-process scorer is for teaching. Production deployments wrap the same math in a SageMaker Processing job (for the statistical signals) and a Training Job plus Batch Transform (for the Isolation Forest). The model code is identical; the infrastructure wrapping is what SageMaker provides. Model version tagging, artifact tracking in the Model Registry, and Model Monitor drift detection come along for free.

**Athena query safety.** The evidence-claim query above uses string interpolation for the `provider_id`. The provider IDs come from our own system, not user input, so this is fine for a teaching example. In any code path that accepts external input, use parameterized queries with Athena's named parameter feature. Even for internal inputs, prefer parameterized queries to keep the pattern consistent.

**Provider entity resolution, not stubbed.** The rollup assumes `claims_df["provider_id"]` is the canonical entity. Building that canonical ID is a recipe unto itself (Recipe 5.x). In production, an entity-resolution pipeline runs upstream and stamps a canonical provider ID on every claim; if you skip this step or run it poorly, your anomaly signal is diluted across the split entities and cases become less actionable.

**Peer group refresh cadence.** Peer groups are re-computed quarterly here. In production, you also need to handle mid-quarter changes: a provider who joins the network, a provider who switches practice settings, a specialty reclassification. Build a change-data-capture feed from the provider master to DynamoDB so new providers land in the right peer group on their first scored period rather than waiting for the next quarterly refresh.

**Isolation Forest retraining cadence.** The quarterly cadence is a starting point. Retrain more frequently if you see distribution drift in the scoring features; less frequently if the feature distributions are stable. Monitor the fraction of providers scored as anomalous by the Isolation Forest across months. A sudden change in that fraction indicates either a real population-level shift (worth investigating) or a stale model (worth retraining).

**Supervised classifier discipline.** The label derivation mapping is organization-specific and drifts over time as the payment integrity team's investigation playbook evolves. Revisit the mapping quarterly; version it so old labels stay interpretable; evaluate label quality periodically by sampling a handful of closed cases and asking the lead analyst whether they agree with the derived label. Bad labels are worse than no labels.

**Subgroup fairness monitoring is required.** The main recipe is explicit: who is being flagged, by specialty, by region, by patient population served? If the pipeline disproportionately flags providers who serve Medicaid or rural populations, that is a signal of systematic bias, not provider-level fraud. Build the subgroup dashboard into the initial deployment, with thresholds that escalate to the health equity team when a subgroup's flag rate is more than 1.5x the overall rate for more than two consecutive periods.

**Case lineage across periods.** The assembly code here creates a new case every period even if the same provider was flagged last period. In production, maintain a "case lineage" view: if the provider is already in an open case, new signals append to that case rather than creating a new one; the case closes when the analyst closes it. Otherwise the analyst sees the same provider three times and burns capacity on duplicates.

**Analyst tooling.** The case registry in DynamoDB is the backend for a payment integrity analyst UI (case list, case detail, evidence viewer, notes, outcome form, provider contact log). That UI is a separate build, typically a web app that queries the case registry via API Gateway and a Lambda. Some organizations integrate into existing case management (ServiceNow, Salesforce) via event bus. Plan for this explicitly, because the analyst UI drives the shape of the case payload more than any other factor.

**Monitoring and alarms.** The `_emit_metric` function drops metrics into CloudWatch. Production requires CloudWatch alarms on top: case-queue depth outside target range, exposure distribution drift beyond a configurable floor, no metrics emitted for 24 hours, SNS publish failure rate above threshold, subgroup flag rate exceeding the fairness threshold. Wire alarms to SNS topics that page the on-call analyst team and the data engineering team.

**Retention and legal hold.** The case registry, anomaly-signals bucket, and labels bucket all carry PHI-adjacent data. Apply retention policies that match HIPAA baseline (6 years), plus anti-fraud-specific retention requirements (often 7-10 years in some jurisdictions). Use S3 Object Lock in COMPLIANCE mode for the labels bucket in production; GOVERNANCE is fine for dev/test so you can clean up.

**Testing.** A real codebase has unit tests for every derivation function (feature rollup, CUSUM detection, severity computation, routing logic, label derivation, leave-one-out stats), integration tests for the full pipeline against DynamoDB Local and moto mocks, and golden-path regression tests that run on every retrain so a model that silently breaks a subgroup does not slip through. The `_overall_severity` and `_determine_routing` functions in particular benefit from table-driven tests because their rules evolve with the payment integrity team's feedback.

**Decimal serialization.** The example code mixes Decimal and float across boundaries more than is ideal. In production, use a single consistent custom JSON encoder across the codebase so the Python-side math (Decimal) and JSON-side representation (string or float) boundary is explicit. Mixing `default=str` in one place and a custom encoder in another is a subtle source of bugs that show up as rounding drift months later.

**Cost per investigated case.** An experienced payment integrity analyst costs real money per hour. Track both the marginal analyst cost per case and the marginal dollars recovered per case. The break-even threshold (cases that cost more to investigate than they recover) is where the lower routing threshold should be set, and that threshold drifts over time as labor costs and fraud patterns shift. Feed this back into the routing logic as a configurable parameter so operations can re-tune without a code change.

None of this is unique to billing anomaly detection. It is the cost of running any PHI-adjacent prediction service in production. The good news: once you have the infrastructure for one of these pipelines, it amortizes across Recipe 3.1 (duplicate claims), Recipe 3.2 (no-show patterns), Recipe 3.4 (medication dispensing anomalies), Recipe 3.6 (fraud/waste/abuse), and the other payment-integrity and clinical-monitoring recipes that share this architecture.

---

*← [Main Recipe 3.3](chapter03.03-billing-code-anomalies) · [Chapter 3 Preface](chapter03-preface)*
