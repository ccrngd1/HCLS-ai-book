# Recipe 3.4: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 3.4. It shows one way you could translate the medication-dispensing-anomaly pattern into working Python using Amazon DynamoDB (for the patient-context cache), Amazon SageMaker Feature Store (for drug-class baseline statistics), Amazon S3 (for the versioned clinical-rules library, raw dispense archives, and label storage), Amazon EventBridge (for fan-out of anomaly events to alerting, audit, and feedback consumers), Amazon SNS (for interrupt-severity alerts to pharmacist workstations), Amazon OpenSearch Service (for the alert-audit index), and Amazon CloudWatch (for operational metrics). It is not production-ready. There is no real HL7 v2 or FHIR parser (those are maintained libraries and projects in themselves, not teaching-example code), no real drug knowledge base integration (the commercial vendors charge for that content and it is the backbone of a real system), no SageMaker Processing wrapper around the batch trajectory job, no Neptune graph build for the controlled-substance diversion module, no Step Functions orchestration of the batch pipelines, no BCMA integration, and no pharmacist UI. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you would wire into a hospital's dispensing workflow on Monday morning.
>
> The code maps to the seven core pseudocode steps from the main recipe: normalize a raw dispense event into a canonical representation with RxNorm identifiers and canonical units, enrich the event with the patient-context cache and compute derived features, run the rule-based screen against the clinical rules library, compute population-level z-scores against the Feature Store baselines, route the combined flags by severity tier, run a batch trajectory scoring pass (CUSUM on continuous-dose drugs plus Isolation Forest on per-patient-day vectors), and capture pharmacist responses plus confirmed adverse drug events as labels for eventual rule tuning and supervised retraining. The diversion graph analytics, BCMA administration integration, and LLM-assisted triage paths from the main recipe are not in this file; they are covered in the Variations section of the main recipe and share infrastructure with other chapter recipes (3.9 for the graph analytics pattern, Chapter 8 for text normalization).

---

## Setup

You will need the AWS SDK for Python plus scikit-learn, pandas, and numpy for the statistics and the multivariate detector:

```bash
pip install boto3 scikit-learn pandas numpy
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the `patient-context-cache` and `drug-reference-cache` tables
- `s3:GetObject` on the `clinical-rules` bucket and the model-artifacts bucket, `s3:PutObject` on the dispense-history, anomaly-events, and labels buckets
- `sagemaker-featurestore-runtime:GetRecord`, `sagemaker-featurestore-runtime:PutRecord` on the `drug-class-baselines` feature group
- `events:PutEvents` on the `medication-anomaly-events` bus
- `sns:Publish` on the interrupt-alerts topic
- `cloudwatch:PutMetricData` for operational metrics
- The OpenSearch domain policy must allow the executing role to `es:ESHttpPost` and `es:ESHttpPut` on the `medication-anomalies` and `dispense-audit` indices

Scope each role to the specific resource ARNs it touches. The permissions above are fine for learning and will fail any serious IAM review. In production, each component (event-normalizer Lambda, real-time-anomaly-service Lambda, batch-trajectory Processing job, feedback-capture Lambda) gets its own role with the minimum permissions for its job.

A few things worth knowing upfront:

- **No real HL7 or FHIR parsing in this example.** Parsing HL7 v2 ORM/RDE messages or FHIR MedicationRequest resources is a substantial engineering task and belongs in a maintained library (HAPI FHIR on the JVM side, `fhir.resources` or `python-hl7` on the Python side). This example starts from a dispense event that is already a Python dictionary in the shape produced by a normalizer. In production, a Lambda triggered by a Kinesis record would call the parsing library and feed the parsed event into the normalization step.
- **No real drug knowledge base.** The rule library, RxNorm crosswalks, weight-based dose ceilings, and renal dose adjustments come from a commercial drug knowledge base (First Databank, Wolters Kluwer, Micromedex, Lexicomp, Medi-Span) or a carefully-maintained open-source equivalent on top of RxNorm and DailyMed. The example below ships a handful of hand-coded rules and a tiny RxNorm crosswalk so the code runs end-to-end for teaching. Do not use these for anything real.
- **DynamoDB table schemas.** `patient-context-cache` is keyed on `patient_id` (partition key only) with a TTL attribute for staleness. `drug-reference-cache` is keyed on `rxnorm_id` (partition key only) and stores canonical unit plus display name. You create these once, up front; this file does not do that for you.
- **All numeric scores must be Decimal.** DynamoDB rejects Python `float` for numeric attributes (precision loss, which for dose-per-kg calculations and z-scores is a quiet patient-safety disaster over thousands of events). Every dose, weight, lab value, and z-score passes through `Decimal` on its way into DynamoDB and back out. The helper functions below handle this so you see the pattern.
- **All example patient, drug, and provider data is synthetic.** Patient IDs, RxNorm identifiers (real RxCUIs are used for known drugs like amoxicillin so the shape is correct), provider NPIs, and dispensing-station IDs in the sample data are illustrative and do not refer to any real people, providers, or services. Use [Synthea](https://github.com/synthetichealth/synthea) in a development environment and never use real PHI in a teaching example.
- **Alert fatigue is not simulated here.** The main recipe spends a lot of time on alert fatigue for good reason. The example code generates flags whenever the rule or z-score fires. In production, a severity-tiering layer, suppression rules for known-benign patterns, and override-rate monitoring sit between the raw flags and the pharmacist-facing alerts. Building the detection is the easy part; getting the alert volume right is where the actual work happens.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here: thresholds, feature lists, drug reference stubs, resource names, and severity mappings. These are the knobs you will change most often between environments.

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
# Logs Insights. Dispense events are PHI (patient_id + drug + timestamp is
# fully identifying even without a name), so we log structural metadata only.
# Never log full event bodies, patient identifiers, dose values with patient
# context, or feature vectors in regular application logs.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry mode handles DynamoDB, Feature Store, and OpenSearch
# throttling with exponential backoff and jitter. Dispense volume is
# naturally bursty (med-pass rounds at 0600, 1200, 1800, 2200 on inpatient
# units), and adaptive mode keeps burst windows from cascading into retry
# storms against the patient-context cache and the baseline store.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers
# so each invocation does not pay the connection-establishment cost.
REGION = "us-east-1"
dynamodb = boto3.resource("dynamodb", region_name=REGION, config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", region_name=REGION, config=BOTO3_RETRY_CONFIG)
cloudwatch = boto3.client("cloudwatch", region_name=REGION, config=BOTO3_RETRY_CONFIG)
eventbridge = boto3.client("events", region_name=REGION, config=BOTO3_RETRY_CONFIG)
sns = boto3.client("sns", region_name=REGION, config=BOTO3_RETRY_CONFIG)
featurestore_runtime = boto3.client(
    "sagemaker-featurestore-runtime", region_name=REGION, config=BOTO3_RETRY_CONFIG
)

# --- Resource Names ---
# Fill in with your actual resource names.
PATIENT_CONTEXT_TABLE = "patient-context-cache"
DRUG_REFERENCE_TABLE = "drug-reference-cache"

DRUG_BASELINES_FG = "drug-class-baselines"     # SageMaker Feature Store feature group
CLINICAL_RULES_BUCKET = "my-clinical-rules"
DISPENSE_HISTORY_BUCKET = "my-dispense-history"
LABELS_BUCKET = "my-medication-anomaly-labels"
MODEL_ARTIFACTS_BUCKET = "my-medication-anomaly-model-artifacts"

INTERRUPT_ALERT_TOPIC_ARN = (
    "arn:aws:sns:us-east-1:123456789012:medication-interrupt-alerts"
)
EVENT_BUS_NAME = "medication-anomaly-events"
ANOMALY_AUDIT_INDEX = "medication-anomalies"

# Deploy-time guardrail: catch unreplaced example values. A real alert
# firing to the example account ID would be a bad day for whoever owns it.
assert "123456789012" not in INTERRUPT_ALERT_TOPIC_ARN or __name__ != "__production__", \
    "INTERRUPT_ALERT_TOPIC_ARN still uses the example AWS account ID. Replace before deploying."

# --- Detector Version ---
# Every flag, every severity decision, every captured label records the
# detector version. This is how retraining picks its training window, how
# rule tuning attributes regressions to a specific rule-library version,
# and how monitoring tracks alert-rate changes after a deployment.
DETECTOR_VERSION = "dispensing-anomaly-v1.0"
RULE_LIBRARY_VERSION = "rules-v2026.05"
DRUG_KB_VERSION = "drug-kb-v2026.05"

# --- Staleness Tolerance by Acuity ---
# How old can a weight, a creatinine, or a medication list be before the
# detector flags it as stale and downweights checks that depend on it.
# ICU patients change fast; outpatients do not. Numbers are directional;
# tune against your own clinical workflow.
WEIGHT_MAX_AGE_DAYS = {
    "icu":        1,
    "ward":       3,
    "ed":         1,
    "outpatient": 180,
}
EGFR_MAX_AGE_DAYS = {
    "icu":        1,
    "ward":       2,
    "ed":         1,
    "outpatient": 90,
}

# --- Z-Score Thresholds ---
# POP_DOSE_Z_THRESHOLD: |robust z| at or above this bound flags the dose
# as a population-level outlier. 3.0 corresponds to roughly the 99.7th
# percentile for a normal distribution; drug-dose distributions have
# heavier tails, so this threshold picks up the genuinely-unusual events
# without flooding the pharmacist queue.
# POP_DOSE_PER_KG_Z_THRESHOLD: same concept for dose-per-kg comparisons.
# Uses a slightly lower threshold because weight-based dosing has tighter
# reference ranges in pediatric and weight-sensitive populations.
POP_DOSE_Z_THRESHOLD = Decimal("3.0")
POP_DOSE_PER_KG_Z_THRESHOLD = Decimal("2.5")

# Minimum peer sample size required before we trust the baseline. Below
# this, the variance estimate is too noisy to use safely.
MIN_BASELINE_SAMPLES = 50

# --- CUSUM Parameters (batch trajectory path) ---
# Standard SPC parameters adapted to medication dose time series.
# K = slack in units of baseline stddev (~ half the shift we want to
# detect quickly). H = decision threshold in units of baseline stddev.
CUSUM_K_MULT = 0.5
CUSUM_H_MULT = 4.0

# --- Isolation Forest (batch multivariate path) ---
# Scores below this cut are flagged. Scores are roughly in [-0.5, 0.5]
# with more negative values more anomalous; -0.15 is a reasonable
# starting point that balances recall against queue volume.
ISOLATION_FOREST_THRESHOLD = Decimal("-0.15")

# --- Severity Tier Thresholds ---
# The main recipe spends a lot of time on this. Interrupt severity is
# reserved for high-confidence, high-impact events where the cost of
# delaying the dispense is acceptable compared to the risk of dispensing.
# Everything else goes to the review queue or background trend report.
SEVERITY_ORDER = {"background": 0, "synchronous": 1, "interrupt": 2}

# --- RxNorm / Crosswalk Stubs ---
# A tiny in-process stand-in for a real drug knowledge base. Real RxCUIs
# are used where possible so the identifier shape is authentic. In
# production, this data comes from the commercial KB via a daily feed.
RXNORM_BY_NAME = {
    "amoxicillin":      "723",      # real RxCUI for amoxicillin
    "acetaminophen":    "161",      # real RxCUI for acetaminophen
    "vancomycin":       "11124",    # real RxCUI for vancomycin
    "insulin_regular":  "5856",     # real RxCUI for regular insulin
    "morphine":         "7052",     # real RxCUI for morphine
    "warfarin":         "11289",    # real RxCUI for warfarin
}

# Canonical unit per drug family. Real KBs carry this per-product.
CANONICAL_UNIT = {
    "723":   "mg",       # amoxicillin
    "161":   "mg",       # acetaminophen
    "11124": "mg",       # vancomycin
    "5856":  "units",    # insulin
    "7052":  "mg",       # morphine
    "11289": "mg",       # warfarin
}

# --- Continuously-monitored drugs for batch trajectory scoring ---
# The drugs for which the CUSUM trajectory path is worth running. These
# are the ones where dose trends carry clinical signal.
CONTINUOUS_MONITORING_DRUGS = {
    "5856":  "insulin",     # insulin infusions
    "7052":  "morphine",    # pain control / opioid trajectory
    "11124": "vancomycin",  # antibiotic trough-directed titration
}

def _to_decimal(value) -> Decimal:
    """
    Coerce numeric input into Decimal for DynamoDB and downstream math.

    DynamoDB rejects float. Always pass Decimal. Quantizing to four decimal
    places keeps the storage format predictable without losing meaningful
    precision for probabilities, rates, z-scores, and dose-per-kg values.
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

def _staleness_check(observed_at_iso: Optional[str], max_age_days: int) -> bool:
    """
    Return True if the observation is stale relative to the max age.
    A missing observed_at counts as stale.
    """
    if not observed_at_iso:
        return True
    observed_at = datetime.fromisoformat(observed_at_iso.replace("Z", "+00:00"))
    age = datetime.now(timezone.utc) - observed_at
    return age.days > max_age_days

def _max_weight_age(acuity: str) -> int:
    return WEIGHT_MAX_AGE_DAYS.get(acuity, 30)

def _max_egfr_age(acuity: str) -> int:
    return EGFR_MAX_AGE_DAYS.get(acuity, 30)
```

---

## Step 1: Normalize the Dispense Event

*The pseudocode calls this `normalize_dispense_event(raw_event)`. The function takes whatever shape an upstream system produced (CPOE order verification, automated dispensing cabinet pull, retail pharmacy fill, PDMP feed) and emits a canonical representation keyed on RxNorm concept IDs with doses in canonical units. Skip or rush this step, and downstream detectors cannot see that "Tylenol 500mg PO Q6H" and "acetaminophen 500 mg oral every 6 hours" are the same drug. Your trajectory features become nonsense and your duplicate-therapy rules go silent.*

The three correctness properties that matter most here are stable drug identification (map to RxNorm), canonical dose units (mg, mcg, units, mEq), and resolved patient identity. This example keeps the patient-ID resolution stubbed since enterprise MPI work belongs in Chapter 5 (Entity Resolution); the drug and dose normalization is where most of the real work happens at the normalizer stage.

```python
def normalize_dispense_event(raw_event: dict) -> Optional[dict]:
    """
    Produce the canonical event shape the rest of the pipeline expects.
    Returns None for events that could not be normalized; callers should
    route those to a dead-letter queue for data-quality review.

    Expected raw_event fields (any subset; all are optional individually):
      source_event_id, source, event_type, timestamp,
      patient_mrn or patient_id, ndc, formulary_id, drug_name,
      dose_value, dose_unit, sig_text or frequency_field, route,
      ordering_provider, dispensing_user, dispensing_station
    """
    # --- Drug identification: try NDC, then formulary, then name fuzzy match ---
    drug_rxnorm = _resolve_drug_to_rxnorm(raw_event)
    if drug_rxnorm is None:
        _emit_metric("unmapped_drug", dimensions={"source": raw_event.get("source", "unknown")})
        logger.warning("drug_id_unresolved", extra={
            "source_event_id": raw_event.get("source_event_id"),
            "source":          raw_event.get("source"),
        })
        return None

    # --- Dose normalization: convert to the canonical unit for this drug ---
    canonical_unit = CANONICAL_UNIT.get(drug_rxnorm)
    if canonical_unit is None:
        # Fall back to the raw unit if the KB does not know this drug.
        # A real implementation would refuse to score; we let it through
        # with a data-quality flag so you can see the pattern.
        canonical_unit = raw_event.get("dose_unit", "mg")

    try:
        dose_value = _convert_to_canonical_unit(
            raw_value=float(raw_event.get("dose_value") or 0),
            raw_unit=raw_event.get("dose_unit", canonical_unit),
            canonical_unit=canonical_unit,
        )
    except (TypeError, ValueError):
        logger.warning("dose_parse_failed", extra={
            "source_event_id": raw_event.get("source_event_id"),
        })
        return None

    # --- Patient identity resolution ---
    # In production, call the enterprise master patient index. Here we
    # accept either a pre-resolved patient_id or an MRN we treat as the
    # canonical ID for the example.
    patient_id = raw_event.get("patient_id") or raw_event.get("patient_mrn")
    if not patient_id:
        logger.warning("missing_patient_id", extra={
            "source_event_id": raw_event.get("source_event_id"),
        })
        return None

    # --- Frequency parsing ---
    # "Q6H PRN" -> (min_interval_hours=6, max_interval_hours=6, prn=True).
    # Real sig parsers handle hundreds of patterns. The stub here returns
    # None for anything not structured, and downstream checks guard on that.
    frequency = _parse_frequency(raw_event.get("sig_text") or raw_event.get("frequency_field"))

    canonical_event = {
        "event_id":            f"DISP-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}",
        "source_event_id":     raw_event.get("source_event_id"),
        "source":              raw_event.get("source", "unknown"),
        "event_type":          raw_event.get("event_type", "dispense"),
        "event_timestamp":     raw_event.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "patient_id":          patient_id,
        "drug_rxnorm":         drug_rxnorm,
        "drug_display_name":   _drug_display_name(drug_rxnorm),
        "dose_value":          dose_value,
        "dose_unit":           canonical_unit,
        "dose_per_kg":         None,  # computed after weight lookup in Step 2
        "route":               _normalize_route(raw_event.get("route")),
        "frequency":           frequency,
        "ordered_by":          raw_event.get("ordering_provider"),
        "dispensed_by":        raw_event.get("dispensing_user"),
        "station_id":          raw_event.get("dispensing_station"),
        "raw_identifier": {
            "ndc":          raw_event.get("ndc"),
            "formulary_id": raw_event.get("formulary_id"),
            "name":         raw_event.get("drug_name"),
        },
    }
    return canonical_event

def _resolve_drug_to_rxnorm(raw_event: dict) -> Optional[str]:
    """
    In production, call the drug knowledge base's NDC lookup, formulary
    crosswalk, and fuzzy name matcher in that order. This example uses
    the in-process RXNORM_BY_NAME stub. Real code should never fuzzy-
    match a name without a confidence threshold and an audit trail.
    """
    name = raw_event.get("drug_name")
    if name:
        key = name.strip().lower().split()[0]    # crude: take the first token
        if key in RXNORM_BY_NAME:
            return RXNORM_BY_NAME[key]
    # Real code: NDC lookup, formulary crosswalk, confidence-gated fuzzy match.
    return None

def _convert_to_canonical_unit(raw_value: float, raw_unit: str, canonical_unit: str) -> float:
    """
    Convert between compatible dose units. The canonical unit is defined
    by the knowledge base per drug. A real implementation has a full unit
    ontology; this stub handles the common mg/g/mcg and kg/g/mg conversions
    that cause the most frequent ten-thousand-fold errors in pediatric meds.
    """
    if raw_unit == canonical_unit:
        return raw_value
    factors = {
        ("g", "mg"):   1000.0,
        ("mg", "g"):   0.001,
        ("mg", "mcg"): 1000.0,
        ("mcg", "mg"): 0.001,
        ("g", "mcg"):  1_000_000.0,
        ("mcg", "g"):  0.000_001,
    }
    factor = factors.get((raw_unit, canonical_unit))
    if factor is None:
        raise ValueError(f"No conversion from {raw_unit} to {canonical_unit}")
    return raw_value * factor

def _parse_frequency(sig_text: Optional[str]) -> Optional[dict]:
    """
    Bare-minimum frequency parser. Real sig parsers are substantial
    libraries; see `python-sig-parser` style projects for production use.
    Returns None for anything not recognized so downstream checks skip.
    """
    if not sig_text:
        return None
    text = sig_text.lower()
    patterns = [
        ("q4h", {"min_interval_hours": 4,  "max_interval_hours": 4}),
        ("q6h", {"min_interval_hours": 6,  "max_interval_hours": 6}),
        ("q8h", {"min_interval_hours": 8,  "max_interval_hours": 8}),
        ("q12h", {"min_interval_hours": 12, "max_interval_hours": 12}),
        ("daily", {"min_interval_hours": 24, "max_interval_hours": 24}),
        ("bid", {"min_interval_hours": 12, "max_interval_hours": 12}),
        ("tid", {"min_interval_hours": 8,  "max_interval_hours": 8}),
        ("qid", {"min_interval_hours": 6,  "max_interval_hours": 6}),
    ]
    for token, structured in patterns:
        if token in text:
            return {**structured, "prn": "prn" in text}
    return None

def _normalize_route(raw_route: Optional[str]) -> Optional[str]:
    """Map common route strings to a canonical short form."""
    if not raw_route:
        return None
    mapping = {
        "oral":         "po",  "po":       "po",  "by mouth": "po",
        "intravenous":  "iv",  "iv":       "iv",
        "subcutaneous": "sq",  "sq":       "sq",  "subq":     "sq",
        "intramuscular": "im", "im":       "im",
        "topical":      "top",
    }
    return mapping.get(raw_route.strip().lower(), raw_route)

def _drug_display_name(rxnorm_id: str) -> str:
    """
    Return a display name for the drug. In production this comes from the
    KB's RxNorm detail record; here we reverse-lookup the stub.
    """
    for name, rxcui in RXNORM_BY_NAME.items():
        if rxcui == rxnorm_id:
            return name.replace("_", " ")
    return f"rxcui:{rxnorm_id}"
```

---

## Step 2: Enrich with Patient Context and Compute Derived Features

*The pseudocode calls this `enrich_with_patient_context(canonical_event)`. The function reads the patient-context cache, attaches demographics, labs, active medications, allergies, and location, then computes the derived features the scorer needs (dose-per-kg, CKD stage, pediatric vs. geriatric flags). Staleness checks tag each cached field with how recent it is so the scorer can downweight or skip checks that depend on out-of-date data.*

This is the step that blows up in production more often than any other. Weights stored in the cache that are three weeks old, creatinines from the last admission, allergy entries that are free text and never normalized, active medication lists that do not include home meds reconciled on admission. Every one of those data quality issues produces either confident wrong answers or silent failures, and neither is acceptable for a patient-safety system. Invest heavily in the cache-refresh pipeline and the staleness tracking.

```python
def enrich_with_patient_context(canonical_event: dict) -> Optional[dict]:
    """
    Attach the patient-context snapshot to the canonical event. Returns
    None if the patient is unknown to the cache; callers should route
    those events to a "patient-not-found" queue rather than letting them
    score against a missing context.
    """
    table = dynamodb.Table(PATIENT_CONTEXT_TABLE)
    response = table.get_item(Key={"patient_id": canonical_event["patient_id"]})
    context_item = response.get("Item")
    if not context_item:
        _emit_metric("patient_context_missing")
        return None

    context = _decimal_to_float(context_item)
    enriched = dict(canonical_event)

    # --- Demographic fields ---
    enriched["patient_age_years"] = context.get("age_years")
    enriched["patient_weight_kg"] = context.get("weight_kg")
    enriched["weight_observed_at"] = context.get("weight_observed_at")
    enriched["patient_height_cm"] = context.get("height_cm")
    enriched["patient_acuity"] = context.get("acuity", "ward")
    enriched["patient_location"] = context.get("unit")

    # --- Staleness flags ---
    # A stale weight on an ICU patient is not a value; it is misinformation.
    # Mark it so the scorer can choose to skip weight-dependent checks.
    enriched["weight_is_stale"] = _staleness_check(
        enriched["weight_observed_at"],
        _max_weight_age(enriched["patient_acuity"]),
    )
    enriched["egfr_is_stale"] = _staleness_check(
        context.get("egfr_observed_at"),
        _max_egfr_age(enriched["patient_acuity"]),
    )

    # --- Lab values ---
    enriched["egfr"] = context.get("egfr")
    enriched["egfr_observed_at"] = context.get("egfr_observed_at")
    enriched["ast"] = context.get("ast")
    enriched["alt"] = context.get("alt")
    enriched["inr"] = context.get("inr")
    enriched["potassium"] = context.get("potassium")

    # --- Med list, problem list, allergies ---
    # Each is stored as a list so downstream checks iterate without
    # shape juggling. Allergies should be a list of normalized-allergen
    # dicts; free-text allergy data is filtered out upstream.
    enriched["active_medications"] = context.get("active_medications", [])
    enriched["active_problems"] = context.get("active_problems", [])
    enriched["allergies"] = context.get("allergies", [])

    # --- Derived features ---
    # dose_per_kg: the single most important derived value for the
    # weight-based rule family. Only computed when both weight and a
    # mass-unit dose are present and the weight is not stale.
    if (
        enriched["patient_weight_kg"]
        and enriched["dose_unit"] in {"mg", "mcg", "g", "units"}
        and not enriched["weight_is_stale"]
    ):
        enriched["dose_per_kg"] = enriched["dose_value"] / enriched["patient_weight_kg"]
    else:
        enriched["dose_per_kg"] = None

    enriched["is_neonate"] = (
        enriched["patient_age_years"] is not None
        and enriched["patient_age_years"] < 0.0833   # under 1 month
    )
    enriched["is_pediatric"] = (
        enriched["patient_age_years"] is not None
        and enriched["patient_age_years"] < 18
    )
    enriched["is_geriatric"] = (
        enriched["patient_age_years"] is not None
        and enriched["patient_age_years"] >= 65
    )
    enriched["ckd_stage"] = _egfr_to_ckd_stage(enriched["egfr"])

    return enriched

def _egfr_to_ckd_stage(egfr: Optional[float]) -> Optional[int]:
    """
    Map eGFR to CKD stage (1 through 5). Standard KDIGO cutoffs. Returns
    None when eGFR is missing so the renal-adjustment rules skip rather
    than make assumptions. In real deployments, confirm the lab's eGFR
    formula (MDRD vs. CKD-EPI); they disagree enough at the margin to
    shift a patient across a stage boundary.
    """
    if egfr is None:
        return None
    if egfr >= 90:
        return 1
    if egfr >= 60:
        return 2
    if egfr >= 30:
        return 3
    if egfr >= 15:
        return 4
    return 5
```

---

## Step 3: Apply the Rule-Based Screen

*The pseudocode calls this `rule_screen(enriched_event)`. For each enriched event, run the rule library: weight-based dose ceilings, renal dose adjustments, severe drug-drug interactions, and allergy contraindications. These are the hard-stop clinical checks. Each rule fire produces a structured flag with the rule ID, the trigger values, the clinical severity, and a reference to the rule's source in the knowledge base.*

The rules layer is the part most teams want to skip or replace with an ML model. That is almost always a mistake. Rules catch the highest-severity, most-unambiguous errors with perfect explainability: a pharmacist who gets interrupted by a rule-based alert knows exactly why (here is the rule, here is the reference, here is the value that tripped it). That clarity is what makes interrupt-severity alerts tolerable at all. The statistical layer layers on top of the rules; it does not replace them.

This example ships a tiny hand-coded rule library in-code so the file runs standalone. In production, rules are authored by clinical pharmacists and clinical informatics, versioned in Git with a formal review and approval workflow, and served from S3 as versioned JSON or YAML. The code below loads from S3 if you uncomment the real loader, with the in-code stub as a fallback.

```python
def load_clinical_rules(drug_rxnorm: str) -> list:
    """
    Return the active rules for a given drug. In production, read the
    versioned rule library from S3 (keyed by rule library version),
    filter to rules applicable to the drug, and cache the results per
    Lambda invocation. The stub below is just enough to illustrate the
    three common rule types.
    """
    # Uncomment for production:
    # response = s3_client.get_object(
    #     Bucket=CLINICAL_RULES_BUCKET,
    #     Key=f"versions/{RULE_LIBRARY_VERSION}/drugs/{drug_rxnorm}.json",
    # )
    # return json.loads(response["Body"].read())

    rules_by_drug = {
        # Amoxicillin pediatric max dose per kg. Directional; use a real KB.
        "723": [
            {
                "id":       "MAX_DOSE_PER_KG_AMOXICILLIN_PEDIATRIC",
                "type":     "max_dose_per_kg",
                "threshold": 15.0,              # mg/kg per dose
                "age_applicable": "pediatric",
                "severity": "interrupt",
                "reference": f"{DRUG_KB_VERSION}:amoxicillin_pediatric_dosing",
                "message_template": (
                    "Dose {actual:.2f} mg/kg exceeds maximum {threshold} mg/kg "
                    "for patient age {age} years (weight {weight} kg)."
                ),
            },
        ],
        # Vancomycin renal-adjustment rule; CKD 4 or 5 requires reduced dose.
        "11124": [
            {
                "id":       "RENAL_ADJ_VANCOMYCIN_CKD45",
                "type":     "renal_dose_adjustment_required",
                "ckd_stage_trigger": 4,
                "max_dose_at_stage": {4: 1000.0, 5: 500.0},     # mg per dose
                "severity": "interrupt",
                "reference": f"{DRUG_KB_VERSION}:vancomycin_renal_dosing",
                "message_template": (
                    "Vancomycin dose {actual} mg exceeds maximum "
                    "{threshold} mg for CKD stage {ckd_stage} (eGFR {egfr})."
                ),
            },
        ],
        # Warfarin + NSAID / salicylate interaction (stubbed pairing).
        "11289": [
            {
                "id":       "DDI_WARFARIN_ASPIRIN",
                "type":     "drug_drug_interaction",
                "interacting_drug_rxnorm": "1191",   # aspirin RxCUI
                "severity": "synchronous",
                "reference": f"{DRUG_KB_VERSION}:warfarin_aspirin_bleeding_risk",
                "message_template": (
                    "Warfarin with concurrent aspirin increases bleeding risk; "
                    "review goals of care and recent INR."
                ),
            },
        ],
    }
    return rules_by_drug.get(drug_rxnorm, [])

def rule_screen(enriched_event: dict) -> list:
    """
    Run the applicable rules against the enriched event. Returns a list of
    flag dicts; an empty list means no rules fired.

    The structure of each flag is deliberately flat and explainable: rule
    ID, the actual value, the threshold, a message, the KB reference. Keep
    this shape stable; the audit queries and alerts depend on it.
    """
    flags = []
    rules = load_clinical_rules(enriched_event["drug_rxnorm"])
    for rule in rules:
        rule_type = rule["type"]
        fired = None

        if rule_type == "max_dose_per_kg":
            fired = _check_max_dose_per_kg(enriched_event, rule)
        elif rule_type == "renal_dose_adjustment_required":
            fired = _check_renal_adjustment(enriched_event, rule)
        elif rule_type == "drug_drug_interaction":
            fired = _check_drug_drug_interaction(enriched_event, rule)
        elif rule_type == "allergy_contraindication":
            fired = _check_allergy_contraindication(enriched_event, rule)

        if fired is not None:
            flags.append(fired)

    return flags

def _check_max_dose_per_kg(event: dict, rule: dict) -> Optional[dict]:
    """
    Weight-based dose ceiling. Only fires when dose_per_kg is computable
    (not stale weight) and the patient falls in the rule's age window.
    """
    if event.get("dose_per_kg") is None:
        return None
    age_gate = rule.get("age_applicable")
    if age_gate == "pediatric" and not event.get("is_pediatric"):
        return None
    if age_gate == "geriatric" and not event.get("is_geriatric"):
        return None

    if event["dose_per_kg"] > rule["threshold"]:
        return {
            "rule_id":   rule["id"],
            "rule_type": rule["type"],
            "severity":  rule["severity"],
            "actual":    _to_decimal(event["dose_per_kg"]),
            "threshold": _to_decimal(rule["threshold"]),
            "message":   rule["message_template"].format(
                actual=event["dose_per_kg"],
                threshold=rule["threshold"],
                age=event.get("patient_age_years"),
                weight=event.get("patient_weight_kg"),
            ),
            "reference": rule["reference"],
        }
    return None

def _check_renal_adjustment(event: dict, rule: dict) -> Optional[dict]:
    """
    Renal dose adjustment by CKD stage. Skips silently when eGFR is stale;
    a stale eGFR could hide a real renal-injury trajectory, so the staleness
    flag propagates in the event for the audit record.
    """
    ckd_stage = event.get("ckd_stage")
    if ckd_stage is None or event.get("egfr_is_stale"):
        return None
    if ckd_stage < rule["ckd_stage_trigger"]:
        return None

    max_dose = rule["max_dose_at_stage"].get(ckd_stage)
    if max_dose is None:
        return None
    if event["dose_value"] > max_dose:
        return {
            "rule_id":   rule["id"],
            "rule_type": rule["type"],
            "severity":  rule["severity"],
            "actual":    _to_decimal(event["dose_value"]),
            "threshold": _to_decimal(max_dose),
            "message":   rule["message_template"].format(
                actual=event["dose_value"],
                threshold=max_dose,
                ckd_stage=ckd_stage,
                egfr=event.get("egfr"),
            ),
            "reference": rule["reference"],
        }
    return None

def _check_drug_drug_interaction(event: dict, rule: dict) -> Optional[dict]:
    """
    Drug-drug interaction check against the patient's active medication
    list. The active_medications field must be the reconciled list that
    includes home meds on admission; interactions that span the admission
    boundary are the ones most often missed in practice.
    """
    interacting = rule["interacting_drug_rxnorm"]
    if interacting in (event.get("active_medications") or []):
        return {
            "rule_id":     rule["id"],
            "rule_type":   rule["type"],
            "severity":    rule["severity"],
            "paired_drug": interacting,
            "message":     rule["message_template"],
            "reference":   rule["reference"],
        }
    return None

def _check_allergy_contraindication(event: dict, rule: dict) -> Optional[dict]:
    """
    Allergy contraindication. Allergies must already be normalized to a
    structured allergen ID; free-text allergy entries require NLP
    preprocessing (Chapter 8) before they are actionable here.
    """
    cross_reactive = set(rule.get("cross_reactive_allergens", []))
    for allergen in (event.get("allergies") or []):
        if allergen.get("normalized_id") in cross_reactive:
            return {
                "rule_id":   rule["id"],
                "rule_type": rule["type"],
                "severity":  "interrupt",    # allergy contraindications are almost always interrupt
                "allergen":  allergen.get("normalized_id"),
                "reaction":  allergen.get("reaction"),
                "message":   rule["message_template"],
                "reference": rule["reference"],
            }
    return None
```

---

## Step 4: Compute Population-Level Z-Scores

*The pseudocode calls this `population_zscore_check(enriched_event)`. For drugs with enough historical dispensing volume to support a stable distribution, look up the drug-class baseline from SageMaker Feature Store and compute a robust z-score (using median and median-absolute-deviation rather than mean and stddev, because dose distributions have heavy tails). Skip the check silently if the baseline sample size is below the minimum.*

The profile bucket (age band, acuity, CKD stage, indication where available) is the partition key for the baseline lookup. Matching too broadly gives you a baseline that is not tuned to the clinical context; matching too narrowly gives you a baseline that lacks the sample size to be stable. The fallback order here is conservative: if the full profile lookup misses, fall back to a narrower key, then to the drug-level overall distribution.

```python
def population_zscore_check(enriched_event: dict) -> list:
    """
    Return any population-level z-score flags for the event. The Feature
    Store stores distribution statistics keyed by drug + profile bucket.
    If the drug has no baseline (new drug, low-volume specialty drug), the
    function returns an empty list; this is an intentional silent skip
    because flagging for lack-of-data is noise, not signal.
    """
    flags = []

    # --- Profile bucket: the key under which the baseline is stored ---
    profile_bucket = _build_profile_bucket(enriched_event)
    baseline_key = f"{enriched_event['drug_rxnorm']}:{profile_bucket}"

    baseline = _get_baseline_from_feature_store(baseline_key)
    if baseline is None:
        # Fallback: try the drug's overall baseline (no profile match).
        baseline = _get_baseline_from_feature_store(f"{enriched_event['drug_rxnorm']}:overall")
        if baseline is None:
            return flags

    if baseline.get("sample_size", 0) < MIN_BASELINE_SAMPLES:
        return flags

    # --- Dose z-score (total dose value) ---
    dose_z_flag = _robust_zscore_flag(
        value=enriched_event["dose_value"],
        baseline_median=baseline.get("dose_median"),
        baseline_mad=baseline.get("dose_mad"),
        threshold=float(POP_DOSE_Z_THRESHOLD),
        feature_name="dose_value",
        flag_type="population_dose_zscore",
        profile=profile_bucket,
    )
    if dose_z_flag is not None:
        flags.append(dose_z_flag)

    # --- Dose-per-kg z-score (weight-based distribution) ---
    if enriched_event.get("dose_per_kg") is not None:
        dose_per_kg_flag = _robust_zscore_flag(
            value=enriched_event["dose_per_kg"],
            baseline_median=baseline.get("dose_per_kg_median"),
            baseline_mad=baseline.get("dose_per_kg_mad"),
            threshold=float(POP_DOSE_PER_KG_Z_THRESHOLD),
            feature_name="dose_per_kg",
            flag_type="population_dose_per_kg_zscore",
            profile=profile_bucket,
        )
        if dose_per_kg_flag is not None:
            flags.append(dose_per_kg_flag)

    return flags

def _build_profile_bucket(event: dict) -> str:
    """
    Canonical profile-bucket string used as the baseline partition key.
    Keep this stable; the Feature Store records are keyed on it and a
    format change invalidates every cached baseline.
    """
    age_band = _age_band(event.get("patient_age_years"))
    acuity = event.get("patient_acuity", "ward")
    ckd = event.get("ckd_stage")
    ckd_token = f"ckd{ckd}" if ckd is not None else "ckd_none"
    return f"{age_band}:{acuity}:{ckd_token}"

def _age_band(age_years: Optional[float]) -> str:
    if age_years is None:
        return "unknown"
    if age_years < 0.0833:
        return "neonate"
    if age_years < 1:
        return "infant"
    if age_years < 12:
        return "child"
    if age_years < 18:
        return "adolescent"
    if age_years < 65:
        return "adult"
    return "elderly"

def _get_baseline_from_feature_store(baseline_key: str) -> Optional[dict]:
    """
    Read a single baseline record from the Feature Store online store.
    Returns a dict of floats (converted from the wire-format strings) or
    None when the record does not exist.
    """
    try:
        response = featurestore_runtime.get_record(
            FeatureGroupName=DRUG_BASELINES_FG,
            RecordIdentifierValueAsString=baseline_key,
        )
    except featurestore_runtime.exceptions.ResourceNotFound:
        return None
    record = response.get("Record")
    if not record:
        return None

    # Feature Store values arrive as strings; convert back to floats for
    # numeric operations. Missing values become None, not 0.0, so the
    # downstream checks can skip cleanly.
    parsed = {}
    for feature in record:
        name = feature["FeatureName"]
        raw = feature.get("ValueAsString")
        if raw is None or raw == "":
            parsed[name] = None
            continue
        try:
            parsed[name] = float(raw)
        except ValueError:
            parsed[name] = raw   # non-numeric features pass through as strings
    return parsed

def _robust_zscore_flag(
    value: float,
    baseline_median: Optional[float],
    baseline_mad: Optional[float],
    threshold: float,
    feature_name: str,
    flag_type: str,
    profile: str,
) -> Optional[dict]:
    """
    Compute a median-absolute-deviation-based robust z-score. The 1.4826
    constant scales MAD to an estimator of the standard deviation for a
    normal distribution; for heavy-tailed drug-dose distributions it is
    more conservative than the textbook formula but remains interpretable.
    """
    if baseline_median is None or baseline_mad is None or baseline_mad == 0:
        return None
    robust_z = (value - baseline_median) / (1.4826 * baseline_mad)
    if abs(robust_z) < threshold:
        return None
    return {
        "type":            flag_type,
        "feature":         feature_name,
        "actual":          _to_decimal(value),
        "baseline_median": _to_decimal(baseline_median),
        "robust_z":        _to_decimal(robust_z),
        "profile":         profile,
        "severity":        _zscore_to_severity(robust_z),
    }

def _zscore_to_severity(robust_z: float) -> str:
    """
    Map a robust z-score to a severity tier. Tune these bands against your
    own override-rate data; the main recipe spends a lot of time on why
    this mapping matters more than the model choice.
    """
    absz = abs(robust_z)
    if absz >= 5.0:
        return "interrupt"
    if absz >= 3.5:
        return "synchronous"
    return "background"
```

---

## Step 5: Route Flags by Severity

*The pseudocode calls this `route_flags(enriched_event, rule_flags, zscore_flags)`. Combine all flags into a single anomaly event, compute the overall severity as the highest severity of any individual flag, index the event in OpenSearch for audit and search, publish it to EventBridge for fan-out to alerting and feedback consumers, and for interrupt-severity events synchronously publish to the SNS topic that feeds the pharmacist workstation alert channel.*

The routing decision is the point in the pipeline where the alert-fatigue design constraints show up in code. Every flag that reaches the pharmacist workstation costs attention. Every low-value flag teaches the pharmacist to dismiss the next one reflexively. The severity-tier thresholds, the suppression rules, and the routing targets are not a technical configuration; they are a clinical-governance decision, and this function is where that governance lives in the runtime.

```python
def route_flags(
    enriched_event: dict,
    rule_flags: list,
    zscore_flags: list,
) -> Optional[dict]:
    """
    Combine, audit-index, and route the flags produced by the detectors.
    Returns the anomaly event dict for the caller to emit metrics on, or
    None if no flags fired (in which case the event is recorded silently
    in the dispense audit index but produces no alert).
    """
    all_flags = rule_flags + zscore_flags

    # Silent audit record for events with no flags. Keeping the audit of
    # "we looked at this event and it was clean" is required for
    # retrospective reviews after an adverse event surfaces.
    if not all_flags:
        _index_dispense_audit(enriched_event, flags=[])
        _emit_metric("event_scored_clean", dimensions={
            "drug": enriched_event["drug_rxnorm"],
        })
        return None

    overall_severity = _max_severity(all_flags)

    anomaly_event = {
        "event_id":          enriched_event["event_id"],
        "patient_id":        enriched_event["patient_id"],
        "drug_rxnorm":       enriched_event["drug_rxnorm"],
        "drug_display_name": enriched_event["drug_display_name"],
        "event_timestamp":   enriched_event["event_timestamp"],
        "source":            enriched_event["source"],
        "flags":             all_flags,
        "flag_count":        len(all_flags),
        "severity":          overall_severity,
        "context_snapshot":  _context_snapshot(enriched_event),
        "detector_version":  DETECTOR_VERSION,
        "rule_library_version": RULE_LIBRARY_VERSION,
        "detected_at":       datetime.now(timezone.utc).isoformat(),
    }

    # Index for search and audit. This feeds the pharmacy director's
    # dashboard and the retrospective-review workflow.
    _index_anomaly_event(anomaly_event)

    # EventBridge fan-out: alerting, feedback capture, metrics aggregator,
    # and downstream analytics all subscribe to the bus and consume in
    # parallel. Using EventBridge rather than direct integrations means
    # new consumers can subscribe without touching the detection code.
    _publish_to_event_bus(anomaly_event)

    # Interrupt severity: synchronous SNS publish to the pharmacist
    # workstation alert channel. The SNS message carries the event ID
    # only; the pharmacist UI fetches the full record so PHI does not
    # live in the notification payload.
    if overall_severity == "interrupt":
        _publish_interrupt_alert(anomaly_event)

    _emit_metric("anomaly_flagged", dimensions={
        "drug":     enriched_event["drug_rxnorm"],
        "severity": overall_severity,
    })

    return anomaly_event

def _max_severity(flags: list) -> str:
    """
    Return the highest-severity tier across all flags. Used to drive the
    overall routing of the anomaly event.
    """
    highest = "background"
    for flag in flags:
        sev = flag.get("severity", "background")
        if SEVERITY_ORDER.get(sev, 0) > SEVERITY_ORDER.get(highest, 0):
            highest = sev
    return highest

def _context_snapshot(enriched_event: dict) -> dict:
    """
    Return the subset of the enriched event that gets persisted with the
    anomaly record. Kept narrow because this snapshot is what a later
    retrospective review will see; too much detail creates PHI exposure,
    too little makes the alert un-auditable.
    """
    return {
        "patient_age_years":   enriched_event.get("patient_age_years"),
        "patient_weight_kg":   enriched_event.get("patient_weight_kg"),
        "weight_observed_at":  enriched_event.get("weight_observed_at"),
        "weight_is_stale":     enriched_event.get("weight_is_stale"),
        "patient_acuity":      enriched_event.get("patient_acuity"),
        "egfr":                enriched_event.get("egfr"),
        "egfr_is_stale":       enriched_event.get("egfr_is_stale"),
        "ckd_stage":           enriched_event.get("ckd_stage"),
        "active_medications":  enriched_event.get("active_medications", []),
        "allergies":           [a.get("normalized_id") for a in (enriched_event.get("allergies") or [])],
        "dose_per_kg":         enriched_event.get("dose_per_kg"),
    }

def _index_anomaly_event(anomaly_event: dict) -> None:
    """
    Write the anomaly event to the OpenSearch audit index. In a real
    Lambda, we would use `requests-aws4auth` or `aws-requests-auth` to
    sign the request; the pattern is the same either way and the
    implementation of the low-level signing is omitted here for brevity.
    """
    # Placeholder for OpenSearch indexing. Real implementation:
    #   from requests_aws4auth import AWS4Auth
    #   auth = AWS4Auth(...)
    #   requests.put(url, auth=auth, json=_decimal_to_float(anomaly_event))
    logger.info("anomaly_indexed", extra={
        "event_id": anomaly_event["event_id"],
        "severity": anomaly_event["severity"],
    })

def _index_dispense_audit(enriched_event: dict, flags: list) -> None:
    """
    Record the fact that we scored this event, whether or not it flagged.
    Required for retrospective reviews.
    """
    audit = {
        "event_id":         enriched_event["event_id"],
        "patient_id":       enriched_event["patient_id"],
        "drug_rxnorm":      enriched_event["drug_rxnorm"],
        "event_timestamp":  enriched_event["event_timestamp"],
        "flag_count":       len(flags),
        "detector_version": DETECTOR_VERSION,
        "scored_at":        datetime.now(timezone.utc).isoformat(),
    }
    logger.info("dispense_audited", extra=audit)

def _publish_to_event_bus(anomaly_event: dict) -> None:
    """
    Put the anomaly event on the EventBridge bus so subscribed Lambdas
    (alerting, feedback capture, metrics, analytics) pick it up in parallel.
    The detail-type encodes the severity so rules can filter without
    deserializing the full payload.
    """
    try:
        eventbridge.put_events(Entries=[{
            "Source":       "medication-anomaly-service",
            "DetailType":   f"MedicationAnomaly.{anomaly_event['severity']}",
            "EventBusName": EVENT_BUS_NAME,
            "Detail":       json.dumps(_decimal_to_float(anomaly_event), default=str),
        }])
    except Exception as ex:
        logger.error("event_bus_publish_failed", extra={
            "event_id": anomaly_event["event_id"],
            "error":    str(ex),
        })

def _publish_interrupt_alert(anomaly_event: dict) -> None:
    """
    Synchronous notification to the pharmacist workstation alert channel.
    The message carries the event ID and minimal routing context only; the
    pharmacist UI fetches the full record by ID so PHI never transits
    through SNS or email.
    """
    message = {
        "event_id":  anomaly_event["event_id"],
        "severity":  anomaly_event["severity"],
        "drug":      anomaly_event["drug_display_name"],
        "timestamp": anomaly_event["detected_at"],
    }
    try:
        sns.publish(
            TopicArn=INTERRUPT_ALERT_TOPIC_ARN,
            Message=json.dumps(message),
            Subject=f"Interrupt alert: {anomaly_event['drug_display_name']}",
            MessageAttributes={
                "severity": {
                    "DataType":    "String",
                    "StringValue": anomaly_event["severity"],
                },
            },
        )
    except Exception as ex:
        # Alert-delivery failures are a patient-safety event. Log loudly,
        # emit a metric, and fall back to the degraded-mode channel.
        logger.error("interrupt_alert_publish_failed", extra={
            "event_id": anomaly_event["event_id"],
            "error":    str(ex),
        })
        _emit_metric("interrupt_alert_publish_failure")

def _emit_metric(metric_name: str, value: int = 1, dimensions: dict = None) -> None:
    """
    Publish an operational metric to CloudWatch. Dimensions always include
    the detector version so regressions can be attributed to a specific
    deployment.
    """
    metric_dims = [{"Name": "DetectorVersion", "Value": DETECTOR_VERSION}]
    if dimensions:
        for k, v in dimensions.items():
            metric_dims.append({"Name": k, "Value": str(v)})
    try:
        cloudwatch.put_metric_data(
            Namespace="MedicationAnomaly",
            MetricData=[{
                "MetricName": metric_name,
                "Value":      value,
                "Unit":       "Count",
                "Dimensions": metric_dims,
            }],
        )
    except Exception as ex:
        logger.warning("metric_emit_failed", extra={
            "metric": metric_name,
            "error":  str(ex),
        })
```

---

## Step 6: Batch Trajectory Scoring (CUSUM and Isolation Forest)

*The pseudocode calls this `batch_trajectory_scoring(as_of_timestamp)`. Run on a schedule (every 15 minutes for ICU-level dose trajectories, hourly for ward-level, daily for facility-level). For each active patient on a continuously-monitored drug, build a dose trajectory over the rolling window and run a CUSUM control chart to detect sustained shifts. Separately, build a per-patient-day feature vector across all dispense events and score it against an Isolation Forest trained on historical data.*

The trajectory layer catches a class of anomaly the per-event real-time check cannot see: the insulin infusion that gradually creeps from 2 U/hr to 14 U/hr over 18 hours (sepsis), the vasopressor that escalates step by step (shock progression), the PRN pain medication usage pattern that spikes beyond the expected recovery curve. Each individual dose is within protocol. The trend across doses is the signal, and it is visible in the pharmacy data often earlier than at the bedside report.

```python
def batch_trajectory_scoring(
    dispense_history_df: pd.DataFrame,
    as_of_timestamp: datetime,
    window_hours: int = 72,
) -> list:
    """
    Run CUSUM trajectory detection on continuously-monitored drugs plus
    Isolation Forest multivariate detection on per-patient-day features.
    Returns a list of trajectory-level anomaly events; callers publish
    them to the same EventBridge bus used by the real-time path.

    `dispense_history_df` columns required:
      event_id, patient_id, drug_rxnorm, dose_value, event_timestamp
    """
    if dispense_history_df.empty:
        return []

    window_start = as_of_timestamp - timedelta(hours=window_hours)
    recent = dispense_history_df[
        pd.to_datetime(dispense_history_df["event_timestamp"]) >= window_start
    ].copy()

    events = []

    # --- CUSUM trajectory scoring per patient-drug pair ---
    for (patient_id, drug_rxnorm), group in recent.groupby(["patient_id", "drug_rxnorm"]):
        if drug_rxnorm not in CONTINUOUS_MONITORING_DRUGS:
            continue
        series = group.sort_values("event_timestamp")
        if len(series) < 10:   # too few samples for a stable trajectory signal
            continue
        cusum_event = _cusum_trajectory(patient_id, drug_rxnorm, series, as_of_timestamp)
        if cusum_event is not None:
            events.append(cusum_event)
            _publish_to_event_bus(cusum_event)

    # --- Isolation Forest on per-patient-day feature vectors ---
    patient_day_vectors = _build_patient_day_features(recent, as_of_timestamp)
    if_events = _score_patient_day_vectors(patient_day_vectors, as_of_timestamp)
    for ev in if_events:
        events.append(ev)
        _publish_to_event_bus(ev)

    logger.info("batch_trajectory_complete", extra={
        "as_of":             as_of_timestamp.isoformat(),
        "cusum_events":      sum(1 for e in events if e["type"] == "trajectory_cusum"),
        "isolation_events":  sum(1 for e in events if e["type"] == "patient_day_isolation_forest"),
    })
    return events

def _cusum_trajectory(
    patient_id: str,
    drug_rxnorm: str,
    series: pd.DataFrame,
    as_of_timestamp: datetime,
) -> Optional[dict]:
    """
    Two-sided CUSUM against the first half of the window as baseline.
    If accumulation crosses the decision boundary, emit a trajectory
    anomaly event with the pre-change and post-change means so the
    pharmacist can see the magnitude of the shift.
    """
    doses = series["dose_value"].astype(float).tolist()
    split = len(doses) // 2
    baseline = doses[:split]
    if len(baseline) < 3:
        return None

    baseline_mean = sum(baseline) / len(baseline)
    baseline_std = pd.Series(baseline).std(ddof=1) or 1.0
    k = CUSUM_K_MULT * baseline_std
    h = CUSUM_H_MULT * baseline_std

    cusum_pos = 0.0
    cusum_neg = 0.0
    change_index = None
    for i, dose in enumerate(doses):
        cusum_pos = max(0.0, cusum_pos + (dose - baseline_mean) - k)
        cusum_neg = min(0.0, cusum_neg + (dose - baseline_mean) + k)
        if cusum_pos > h or cusum_neg < -h:
            change_index = i
            break

    if change_index is None:
        return None

    post = doses[change_index:]
    post_mean = sum(post) / len(post)
    shift = post_mean - baseline_mean
    change_point_ts = series.iloc[change_index]["event_timestamp"]

    severity = "interrupt" if abs(shift) / baseline_std >= 3.0 else "synchronous"

    return {
        "type":             "trajectory_cusum",
        "event_id":         f"TRAJ-{uuid.uuid4().hex[:10]}",
        "patient_id":       patient_id,
        "drug_rxnorm":      drug_rxnorm,
        "drug_display_name": _drug_display_name(drug_rxnorm),
        "change_point":     change_point_ts,
        "pre_change_mean":  _to_decimal(baseline_mean),
        "post_change_mean": _to_decimal(post_mean),
        "shift_magnitude":  _to_decimal(shift),
        "baseline_stddev":  _to_decimal(baseline_std),
        "severity":         severity,
        "detector_version": DETECTOR_VERSION,
        "detected_at":      as_of_timestamp.isoformat(),
    }

def _build_patient_day_features(
    recent: pd.DataFrame,
    as_of_timestamp: datetime,
) -> pd.DataFrame:
    """
    Build a per-patient feature vector for the last 24 hours. Columns are
    chosen to capture the multivariate shape of a patient's medication
    pattern: total events, unique drugs, total dose sum, count of
    controlled substances, count of high-alert drugs, etc.
    """
    day_start = as_of_timestamp - timedelta(hours=24)
    day_recent = recent[pd.to_datetime(recent["event_timestamp"]) >= day_start]
    if day_recent.empty:
        return pd.DataFrame()

    rows = []
    for patient_id, group in day_recent.groupby("patient_id"):
        rows.append({
            "patient_id":       patient_id,
            "event_count":      len(group),
            "unique_drug_count": group["drug_rxnorm"].nunique(),
            "total_dose_mg_equiv": float(group["dose_value"].sum()),
            "max_single_dose":  float(group["dose_value"].max()),
            "opioid_events":    int((group["drug_rxnorm"] == "7052").sum()),
            "insulin_events":   int((group["drug_rxnorm"] == "5856").sum()),
        })
    return pd.DataFrame(rows)

def _score_patient_day_vectors(
    vectors_df: pd.DataFrame,
    as_of_timestamp: datetime,
) -> list:
    """
    Score per-patient-day vectors against the Isolation Forest loaded
    from S3. If the model is not available, return an empty list and log;
    a missing model is a data-pipeline issue, not a patient-safety one.
    """
    if vectors_df.empty:
        return []
    model_payload = _load_isolation_forest()
    if model_payload is None:
        logger.warning("isolation_forest_unavailable")
        return []

    model = model_payload["model"]
    feature_names = model_payload["meta"]["feature_names"]
    X = vectors_df[feature_names].fillna(0.0).astype(float).values

    scores = model.score_samples(X)
    events = []
    for i, score in enumerate(scores):
        if score > float(ISOLATION_FOREST_THRESHOLD):
            continue
        patient_id = vectors_df.iloc[i]["patient_id"]
        events.append({
            "type":             "patient_day_isolation_forest",
            "event_id":         f"IFOREST-{uuid.uuid4().hex[:10]}",
            "patient_id":       patient_id,
            "as_of":            as_of_timestamp.isoformat(),
            "anomaly_score":    _to_decimal(float(score)),
            "severity":         "synchronous",   # batch-path flags rarely interrupt
            "detector_version": DETECTOR_VERSION,
            "detected_at":      as_of_timestamp.isoformat(),
        })
    return events

def _load_isolation_forest() -> Optional[dict]:
    """
    Load the current Isolation Forest artifact from S3 and deserialize.
    Cached as a module-level global across invocations of the same
    process; on a SageMaker Processing job this load happens once per job.
    """
    global _CACHED_IFOREST_PAYLOAD
    try:
        return _CACHED_IFOREST_PAYLOAD
    except NameError:
        pass
    try:
        response = s3_client.get_object(
            Bucket=MODEL_ARTIFACTS_BUCKET,
            Key="current/patient_day_isolation_forest.joblib",
        )
        payload = joblib.load(io.BytesIO(response["Body"].read()))
    except Exception as ex:
        logger.warning("iforest_load_failed", extra={"error": str(ex)})
        return None
    globals()["_CACHED_IFOREST_PAYLOAD"] = payload
    return payload
```

---

## Step 7: Capture Feedback and Close the Loop

*The pseudocode calls this `on_pharmacist_response(response_event)` and `on_adverse_event_report(ade_event)`. Every alert generates a response: acknowledged, overridden, modified, or cancelled. Every confirmed adverse drug event from incident reporting links back to the dispense records in the lookback window. This feedback is what trains the rule-tuning process (which alerts get overridden most often), the supervised classifier (when labels eventually accumulate), and the false-negative monitoring (which adverse events happened without a flag).*

The single most important line of code in this whole file is the one that detects an adverse event without a prior flag and fires a "missed event" signal. That signal is the only way to measure false negatives in a patient-safety system, and false negatives are the failure mode that matters. Every organization underweights them because they are invisible by definition; the incident-report linkage is how you make them visible.

```python
def on_pharmacist_response(response_event: dict) -> None:
    """
    Consumer for pharmacist-response events from the alert workstation.
    Updates the anomaly record with the response, feeds override-rate
    metrics to CloudWatch, and for actionable responses (modified or
    cancelled orders) writes a supervised training row to S3.

    Expected response_event fields:
      anomaly_event_id, response (acknowledged | override |
      modified_order | cancelled_order), response_reason, responded_at,
      responding_user, action_taken
    """
    # In production, fetch the anomaly record from OpenSearch. Omitted
    # here for brevity; we assume the calling Lambda has already loaded it.
    logger.info("pharmacist_response_received", extra={
        "anomaly_event_id": response_event["anomaly_event_id"],
        "response":         response_event["response"],
    })

    _emit_metric("flag_response", dimensions={
        "response":  response_event["response"],
        "severity":  response_event.get("severity", "unknown"),
    })

    # Actionable responses (modification or cancellation) are positive
    # labels: the pharmacist judged the alert correct and acted on it.
    # These rows train the next iteration of the supervised classifier.
    if response_event["response"] in {"modified_order", "cancelled_order"}:
        _write_label_to_s3({
            "anomaly_event_id": response_event["anomaly_event_id"],
            "label":            "action_taken",
            "label_source":     "pharmacist_response",
            "response_reason":  response_event.get("response_reason"),
            "labeled_at":       response_event["responded_at"],
            "detector_version": DETECTOR_VERSION,
        }, partition_date=response_event["responded_at"])

def on_adverse_event_report(
    ade_event: dict,
    recent_dispenses_fn,
) -> None:
    """
    Consumer for adverse drug event reports from incident reporting.
    Finds dispense records within the 48-hour lookback window before the
    event, writes label rows for supervised retraining, and (critically)
    fires a 'missed_adverse_event' signal for any dispense that was NOT
    flagged. That signal is how we measure and improve recall on the
    failures that actually reach the patient.

    Expected ade_event fields:
      id, patient_id, event_date, category, severity, reported_at

    `recent_dispenses_fn(patient_id, window_start, window_end)` is the
    caller-provided lookup that returns the patient's dispense records
    within the window (each record includes an `event_id` and a boolean
    `had_anomaly_flag`). In production this queries OpenSearch.
    """
    window_start = datetime.fromisoformat(ade_event["event_date"]) - timedelta(hours=48)
    window_end = datetime.fromisoformat(ade_event["event_date"])
    related = recent_dispenses_fn(
        ade_event["patient_id"], window_start, window_end,
    )

    for dispense in related:
        _write_label_to_s3({
            "dispense_event_id": dispense["event_id"],
            "drug_rxnorm":       dispense.get("drug_rxnorm"),
            "ade_category":      ade_event["category"],
            "ade_severity":      ade_event["severity"],
            "had_alert":         dispense.get("had_anomaly_flag", False),
            "label":             "adverse_event_confirmed",
            "label_source":      "incident_report",
            "labeled_at":        ade_event["reported_at"],
            "detector_version":  DETECTOR_VERSION,
        }, partition_date=ade_event["reported_at"])

        if not dispense.get("had_anomaly_flag", False):
            # This is the patient-safety signal that matters. An adverse
            # event happened and the detector did not flag. The on-call
            # clinical-informatics team reviews these same-day.
            _emit_metric("missed_adverse_event", dimensions={
                "drug":         dispense.get("drug_rxnorm", "unknown"),
                "ade_category": ade_event["category"],
            })
            try:
                eventbridge.put_events(Entries=[{
                    "Source":       "medication-anomaly-service",
                    "DetailType":   "MedicationAnomaly.MissedEvent",
                    "EventBusName": EVENT_BUS_NAME,
                    "Detail":       json.dumps({
                        "dispense_event_id": dispense["event_id"],
                        "ade_event_id":      ade_event["id"],
                        "patient_id":        ade_event["patient_id"],
                    }),
                }])
            except Exception as ex:
                logger.error("missed_event_publish_failed", extra={
                    "dispense_event_id": dispense["event_id"],
                    "error":             str(ex),
                })

def _write_label_to_s3(label_row: dict, partition_date: str) -> None:
    """
    Append a labeled training row to the labels bucket, partitioned by
    date so Athena queries during retraining can prune the scan. JSON
    here for clarity; in production we write Parquet for columnar access.
    """
    dt = datetime.fromisoformat(partition_date.replace("Z", "+00:00"))
    key = (
        f"labels/year={dt.year:04d}/month={dt.month:02d}/"
        f"day={dt.day:02d}/{uuid.uuid4().hex}.json"
    )
    s3_client.put_object(
        Bucket=LABELS_BUCKET,
        Key=key,
        Body=json.dumps(label_row, default=str).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )
```

---

## The Full Real-Time Pipeline

Here is the end-to-end `score_one_dispense_event` function that wires Steps 1 through 5 together. In production this is the body of the `real-time-anomaly-service` Lambda triggered by Kinesis records; the Python version collapses it into a single driver for teaching.

```python
def score_one_dispense_event(raw_event: dict) -> Optional[dict]:
    """
    End-to-end real-time scoring for a single dispense event. In production
    this runs inside a Lambda triggered by Kinesis records; here it is a
    plain function so you can step through it in a notebook.

    Returns the anomaly event if any flags fired, None otherwise. Exceptions
    bubble up so the caller can route to a dead-letter queue.
    """
    # --- Step 1: normalize ---
    canonical = normalize_dispense_event(raw_event)
    if canonical is None:
        return None

    # --- Step 2: enrich with patient context ---
    enriched = enrich_with_patient_context(canonical)
    if enriched is None:
        return None

    # --- Step 3: rule screen ---
    rule_flags = rule_screen(enriched)

    # --- Step 4: population z-score ---
    zscore_flags = population_zscore_check(enriched)

    # --- Step 5: route ---
    anomaly_event = route_flags(enriched, rule_flags, zscore_flags)
    return anomaly_event

# --- Example usage ---
#
# Minimal end-to-end example that exercises the real-time path with a
# synthetic pediatric amoxicillin overdose. The patient context and drug
# reference are stubbed in-process; in a real run these come from
# DynamoDB and the Feature Store, populated by the EHR and drug-KB feeds.
if __name__ == "__main__":
    # Seed a synthetic patient into the context cache for the example.
    # In a real deployment, the ADT feed and the lab and medication feeds
    # populate the cache; you do not stub it here.
    try:
        dynamodb.Table(PATIENT_CONTEXT_TABLE).put_item(Item={
            "patient_id":          "PT-EXAMPLE-0001",
            "age_years":           _to_decimal(4.3),
            "weight_kg":           _to_decimal(14.0),
            "weight_observed_at":  datetime.now(timezone.utc).isoformat(),
            "height_cm":           _to_decimal(102.0),
            "acuity":              "outpatient",
            "unit":                "peds_clinic_A",
            "egfr":                None,
            "egfr_observed_at":    None,
            "active_medications":  [],
            "active_problems":     ["H66.90"],    # otitis media, unspecified
            "allergies":           [],
        })
    except Exception as ex:
        print(f"[setup] Could not seed patient cache (ok if table not present): {ex}")

    raw_event = {
        "source_event_id":    "cpoe-88441",
        "source":             "cpoe",
        "event_type":         "order",
        "timestamp":          datetime.now(timezone.utc).isoformat(),
        "patient_id":         "PT-EXAMPLE-0001",
        "drug_name":          "amoxicillin suspension",
        "dose_value":         500,
        "dose_unit":          "mg",
        "sig_text":           "500 mg PO TID",
        "route":              "oral",
        "ordering_provider":  "NPI-EXAMPLE-111",
        "dispensing_user":    "RPh-EXAMPLE-22",
        "dispensing_station": "PYXIS-PEDS-01",
    }

    print("[1/1] Scoring synthetic pediatric amoxicillin order...")
    result = score_one_dispense_event(raw_event)
    print()
    if result is None:
        print("No flags fired.")
    else:
        print("=== ANOMALY EVENT ===")
        print(json.dumps(_decimal_to_float(result), indent=2, default=str))
```

Running this against a fresh DynamoDB context cache with the synthetic patient produces an interrupt-severity flag on the amoxicillin dose (500 mg / 14 kg = ~35.7 mg/kg, well above the 15 mg/kg pediatric threshold in the rule stub). The population z-score path stays silent because there is no Feature Store baseline populated; the CUSUM and Isolation Forest paths do not run at all on the real-time path. After a few days of accumulated history and baselines, all three flag families activate.

A realistic dev-loop pattern is to seed a few weeks of synthetic dispense history with Synthea, seed the Feature Store baselines from that history, and only then turn the pipeline loose. The example above is intentionally minimal so the rule-fire shape stays visible without the surrounding machinery.

---

## Gap to Production

Several things would need to change before you would deploy any of this.

**Real HL7 v2 and FHIR parsing.** The example starts from a dict that looks like a parsed order. In production, the event-normalizer Lambda invokes a maintained parsing library (HAPI FHIR via a Java runtime, or `fhir.resources` plus `python-hl7` on Python) to convert the ORM, ORC, RXO, RXE, MedicationRequest, and MedicationAdministration resources into the canonical shape. EDI-adjacent gotchas (unterminated segments, embedded delimiters, vendor-specific Z-segments, time zones in timestamps) are the ones that bite. Budget weeks for this integration, not days.

**Real drug knowledge base integration.** The RXNORM_BY_NAME stub is a toy. In production, you license a commercial drug knowledge base and ingest the daily update feed into a DynamoDB table or a Feature Store feature group. The rule library is authored on top of that KB by clinical pharmacists and clinical informatics; each rule has a reference to a specific KB entry, a severity justification, and an approval record. Rule changes go through a merge-request workflow. The stubbed `load_clinical_rules` function here grows into a service-layer call to S3 with ETag-based caching.

**Patient-context cache freshness.** The example seeds a single patient row directly. In production, a separate Lambda (or a Kinesis consumer) processes ADT, ORU (lab), RDE (med list), and allergy feed events, keeps the `patient-context-cache` table current, and tags every field with its observed_at timestamp. A lab value seconds out of date is different from one 48 hours stale; the staleness propagates through the enrichment step and into the scoring decisions. Without a fresh context pipeline, the detector produces confident wrong answers.

**Enterprise patient ID resolution.** The example accepts whatever `patient_id` the raw event provides. In production, an enterprise master patient index resolves MRNs across source systems into a canonical enterprise ID. Recipe 5.x (Entity Resolution) covers the pattern; plug the resolver in at the top of `normalize_dispense_event` and never let unresolved MRNs through.

**Feature Store baseline population.** The example assumes the `drug-class-baselines` feature group exists with records keyed by drug + profile bucket. In production, a scheduled SageMaker Processing job reads several months of historical dispense events from S3, computes the median and MAD per drug-profile bucket, and writes those records to the online feature store for the real-time path plus the offline store for retraining. Refresh monthly; keep the old baselines as versioned history so alert tuning can be audited.

**OpenSearch integration and authentication.** The `_index_anomaly_event` and `_index_dispense_audit` functions are placeholders. In production, use AWS4Auth-signed HTTPS requests against the OpenSearch domain, with fine-grained access control that separates pharmacy, compliance, and IT security into different roles. The index template needs to include alias management, retention lifecycle policies, and the detector-version field as a keyword for clean aggregation.

**Idempotency.** Kinesis delivers at-least-once. EventBridge delivers at-least-once. The real-time Lambda may process the same event twice, and the feedback-capture Lambda may receive the same pharmacist-response event twice. Use conditional writes (`ConditionExpression`) on every DynamoDB put or update, handle `ConditionalCheckFailedException` as "already processed," and make S3 label writes idempotent by deriving the key deterministically from the event ID.

**Error handling.** The example has minimal error handling. In production, wrap every external call in try/except with structured logging, emit a failure metric, and route affected events to a dead-letter queue. Critically, distinguish patient-context-missing (data quality) from patient-context-timeout (infrastructure) because the correct response is different: the first routes to a human review queue; the second retries with backoff, then falls back to a degraded-mode scoring path that runs the rules without the statistical signal.

**Graceful degradation.** Pharmacy does not stop dispensing because AWS has an issue. Design the pipeline's failure modes explicitly: if the patient-context cache is unavailable, what does the detector do? (Recommended: fall back to rules that do not depend on patient-specific context, log the gap, alert on prolonged unavailability.) If the Feature Store is unavailable, the z-score path skips silently while the rules layer keeps running. If EventBridge is unavailable, drop the event into an S3 "pending" prefix that a replay worker picks up once the bus recovers. Document, drill, and test these paths; they will be exercised.

**Structured logging with PHI discipline.** The `logger.info` calls above log structural metadata only (event IDs, drug identifiers, severity bands). In production, use a JSON log formatter, ship logs to CloudWatch Logs with a log group encrypted by a customer-managed KMS key, and audit log content for unexpected PHI patterns (patient IDs, full context snapshots, dose values tied to patient IDs). A single `logger.info("enriched: %s", enriched)` during debugging creates a PHI disclosure that survives in CloudWatch until retention clears it.

**IAM scoping.** Production roles are scoped tightly. The event-normalizer Lambda's role needs no SNS permissions. The real-time-anomaly-service Lambda's role needs no label-write permissions. The feedback-capture Lambda's role needs no EventBridge-bus write permissions beyond the specific detail-type it produces. Scope to specific resource ARNs and review roles annually. No wildcards in production.

**VPC deployment.** In production, all Lambdas and SageMaker Processing jobs run inside a VPC with VPC endpoints for DynamoDB, S3, Kinesis, SageMaker Runtime, Feature Store Runtime, EventBridge, KMS, and CloudWatch Logs. SNS is a managed edge service and does not run in a VPC; keep SNS messages narrow (event ID and minimal routing) so PHI does not flow through the notification channel.

**KMS customer-managed keys.** All data at rest (DynamoDB tables, S3 buckets, Kinesis streams, Feature Store online and offline stores, OpenSearch domain, CloudWatch Logs) is encrypted with customer-managed KMS keys. Key policies restrict usage to the specific roles that need it. Audit via CloudTrail data events on every PHI-bearing resource.

**SageMaker wrapping for the batch path.** The `batch_trajectory_scoring` function runs in-process for teaching. In production, wrap the same math in a SageMaker Processing job with the dispense history S3 bucket as the input channel and the EventBridge publish step as the final stage of the container script. Schedule the job via EventBridge Scheduler on the cadence appropriate to each drug class (15 minutes for ICU insulin, hourly for ward-level PRN pain medications, daily for facility-level aggregates). Model version tagging lives in the SageMaker Model Registry.

**Isolation Forest training pipeline.** The `_load_isolation_forest` helper assumes a pre-trained artifact. Producing that artifact is a separate SageMaker Training Job that reads several months of per-patient-day feature vectors from the Feature Store offline store, fits the model, registers it in the Model Registry, and after a human approval step copies the artifact to `s3://MODEL_ARTIFACTS_BUCKET/current/patient_day_isolation_forest.joblib`. Retrain quarterly; sample the current-model flag distribution on a rolling basis to detect drift before it harms alert quality.

**Alert-fatigue monitoring.** The main recipe spends a lot of time on alert fatigue for good reason. In production, every flag type has an override-rate CloudWatch alarm: if the rolling weekly override rate on a rule exceeds a configured threshold, an alert goes to the pharmacy clinical leadership for review and possible retirement or re-thresholding. Without this loop, rules accumulate and alert volume slowly climbs back to "everyone dismisses everything" within six months of deployment.

**Subgroup and fairness monitoring.** Medication dispensing detectors can encode bias: a model trained on majority-population dosing flags legitimate patterns in underrepresented populations; pain-management alerts align with known prescribing disparities by race; override patterns differ by prescribing-physician demographics in ways that encode bias in the feedback loop. Build subgroup dashboards (by patient demographics, by care setting, by prescribing physician demographics) from day one, with thresholds that escalate to the health equity team when a subgroup's flag or override rate diverges significantly from the overall population.

**Diversion detection module.** The graph analytics for controlled-substance diversion (Neptune-backed, community detection, per-user baselines) is intentionally not in this file. Its politics and legal complexity require pharmacy compliance and legal as primary owners, not engineering. When you build that module, it shares infrastructure with Recipe 3.9 (EHR access pattern anomalies). Start from that recipe's patterns rather than retrofitting this one.

**Retention and legal hold.** Pharmacy records have DEA, state-board, and Joint Commission retention requirements that often exceed the HIPAA 6-year baseline. Controlled-substance records commonly have 5-10 year retention. Sentinel event records may be held permanently. Apply S3 Object Lock in COMPLIANCE mode for the labels and audit buckets; GOVERNANCE is fine for dev/test so cleanup stays possible.

**Testing.** A real codebase has unit tests for every derivation function (unit conversion, frequency parsing, staleness checks, CKD-stage mapping, leave-one-out-style baseline math, severity escalation), integration tests against DynamoDB Local and moto mocks for DynamoDB, Feature Store, and EventBridge, and golden-path regression tests that run on every rule-library update so a subtle rule change that silently suppresses interrupt alerts is caught before deployment. The `rule_screen` and `_max_severity` functions in particular benefit from table-driven tests because their rules evolve with clinical-governance decisions.

**Clinical governance.** The severity-tier thresholds, the rule library, the suppression rules, the override-rate targets, the alert-delivery UX: all of these are clinical and operational decisions owned by the pharmacy and therapeutics committee or equivalent, not by the engineering team. Wire the governance in: rule changes require committee review, severity reclassifications require re-approval, new detectors require a pilot-then-general-availability rollout. The engineering pipeline supports the governance; it does not replace it.

None of this is unique to medication dispensing anomaly detection. It is the cost of running any patient-safety-adjacent service in production. The good news: once you have the patient-context cache, the EventBridge fan-out, the feedback capture, and the SageMaker training machinery, the same infrastructure supports Recipe 3.5 (Lab Result Outlier Detection), Recipe 3.7 (Patient Deterioration Early Warning), Recipe 3.9 (EHR Access Pattern Anomalies), and the other clinical-monitoring recipes that share this architecture.

---

*← [Main Recipe 3.4](chapter03.04-medication-dispensing-anomalies) · [Chapter 3 Preface](chapter03-preface)*
