# Recipe 3.5: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 3.5. It shows one way you could translate the lab-result-outlier-detection pattern into working Python using Amazon DynamoDB (for the patient-context cache and the reference-range library), Amazon SageMaker Feature Store (for analyte-cohort baseline statistics), Amazon S3 (for the versioned clinical-rules library, model artifacts, and label storage), Amazon EventBridge (for fan-out of outlier events to callback, tech review, autoverify, audit, and feedback consumers), Amazon SNS (for critical-value callback notifications to the pharmacist and clinician paging channels), Amazon OpenSearch Service (for the outlier audit index), and Amazon CloudWatch (for operational metrics). It is not production-ready. There is no real HL7 v2 or FHIR parser (those are maintained libraries and projects in themselves, not teaching-example code), no real LIS middleware integration, no CLIA-compliant callback workflow with timing and read-back tracking, no Step Functions orchestration of the batch pipelines, no POCT data manager ingress, and no pathologist or lab tech UI. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you would wire into a hospital's result-release pipeline on Monday morning.
>
> The code maps to the eight core pseudocode steps from the main recipe: normalize a raw result into a canonical representation with LOINC identifiers and canonical units, enrich the result with the patient-context cache including recent history, run the rule-based screen (critical values, reference range, specimen-quality gates, collection-site gates), compute delta checks and patient-history robust z-scores, compute cohort z-scores against the Feature Store baselines, route the combined flags by severity tier, run batch panel-level Isolation Forest and patient-trajectory CUSUM, and capture tech review decisions plus recollect outcomes as labels for eventual rule tuning and supervised retraining. The LLM-assisted interpretation path, the blood bank extension, and the POCT-specific logic from the main recipe are not in this file; they are covered in the Variations section of the main recipe and share infrastructure with other chapter recipes (3.4 for the per-event real-time path, Chapter 8 for text normalization of clinical notes).

---

## Setup

You will need the AWS SDK for Python plus scikit-learn, pandas, and numpy for the statistics and the multivariate detector:

```bash
pip install boto3 scikit-learn pandas numpy
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the `patient-context-cache` and `reference-range-library` tables
- `s3:GetObject` on the `lab-rules` bucket and the model-artifacts bucket, `s3:PutObject` on the result-archive and labels buckets
- `sagemaker-featurestore-runtime:GetRecord`, `sagemaker-featurestore-runtime:PutRecord` on the `analyte-cohort-baselines` feature group
- `events:PutEvents` on the `lab-outlier-events` bus
- `sns:Publish` on the critical-value callback topic
- `cloudwatch:PutMetricData` for operational metrics
- The OpenSearch domain policy must allow the executing role to `es:ESHttpPost` and `es:ESHttpPut` on the `lab-outliers` and `result-audit` indices

Scope each role to the specific resource ARNs it touches. The permissions above are fine for learning and will fail any serious IAM review. In production, each component (result-normalizer Lambda, real-time-outlier-service Lambda, batch-pattern Processing job, callback Lambda, feedback-capture Lambda) gets its own role with the minimum permissions for its job.

A few things worth knowing upfront:

- **No real HL7 or FHIR parsing in this example.** Parsing HL7 v2 ORU messages or FHIR Observation and DiagnosticReport resources is a substantial engineering task and belongs in a maintained library (HAPI FHIR on the JVM side, `fhir.resources` or `python-hl7` on the Python side). This example starts from a result event that is already a Python dictionary in the shape produced by a normalizer. In production, a Lambda triggered by a Kinesis record would call the parsing library and feed the parsed result into the normalization step.
- **No real LIS middleware integration.** Real deployments talk to a middleware product (Data Innovations Instrument Manager, Beckman Remisol, Sysmex Caresphere) that aggregates analyzer output and forwards to the LIS. That middleware is where specimen quality indices are typically captured in a consistent format. Below we assume those indices arrive in the raw event already; in production you build the middleware hook carefully and validate per-analyzer that the indices are populated on every result.
- **DynamoDB table schemas.** `patient-context-cache` is keyed on `patient_id` (partition key only). `reference-range-library` uses a composite key: `loinc_code` (partition) and a sort key combining method, sex, and age-band (e.g., `roche-cobas:F:adult`). You create these once, up front; this file does not do that for you.
- **All numeric values must be Decimal going into DynamoDB.** DynamoDB rejects Python `float` for numeric attributes. A potassium of 4.2 becomes `Decimal("4.2")` on the way in and back to float on the way out. The helper functions below handle this so you see the pattern. For a lab system the precision discipline matters: a hemoglobin stored as `13.599999` from float drift, compared against a delta threshold of 2.0, silently produces a different decision than `13.6`.
- **All example patient and result data is synthetic.** Patient IDs, accession numbers, and provider identifiers in the sample data are illustrative. LOINC codes used (2823-3 for potassium, 718-7 for hemoglobin, 2345-7 for glucose) are real LOINC concept identifiers. Use [Synthea](https://github.com/synthetichealth/synthea) for synthetic lab data in a development environment, and never use real PHI in a teaching example.
- **Critical-value callback is not CLIA-compliant in this file.** The callback path here publishes to SNS and moves on. A real callback workflow tracks callback timing (against the CLIA-mandated window), recipient, read-back confirmation, and closure. That state machine is its own service; this example marks where it plugs in.
- **Alert fatigue is not simulated here.** The main recipe spends a lot of time on alert fatigue and autoverification rate for good reason. The example code generates flags whenever the rule or z-score fires. In production, severity-tiering logic, suppression rules for known-benign patterns (dialysis patients' creatinine, chronic anemia patients' hemoglobin), and override-rate monitoring sit between the raw flags and the tech-review or clinician-facing alerts.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here: thresholds, feature lists, reference-data stubs, resource names, and severity mappings. These are the knobs you will change most often between environments.

```python
import io
import json
import logging
import math
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import median
from typing import Optional

import boto3
import joblib
import numpy as np
import pandas as pd
from botocore.config import Config
from sklearn.ensemble import IsolationForest

# Structured logging. In production, ship JSON-formatted records to CloudWatch
# Logs Insights. Result events are PHI (patient_id + analyte + value + timestamp
# is fully identifying even without a name), so we log structural metadata only.
# Never log full result bodies, patient identifiers, result values tied to a
# patient context, or cohort feature vectors in regular application logs.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry mode handles DynamoDB, Feature Store, and OpenSearch
# throttling with exponential backoff and jitter. Result volume is bursty
# (analyzer runs, batched reference-lab feeds, POCT bursts during med-pass),
# and adaptive mode keeps burst windows from cascading into retry storms
# against the patient-context cache and the baseline store.
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
REFERENCE_RANGE_TABLE = "reference-range-library"

COHORT_BASELINES_FG = "analyte-cohort-baselines"   # SageMaker Feature Store feature group
LAB_RULES_BUCKET = "my-lab-rules"
RESULT_ARCHIVE_BUCKET = "my-lab-result-archive"
LABELS_BUCKET = "my-lab-outlier-labels"
MODEL_ARTIFACTS_BUCKET = "my-lab-outlier-model-artifacts"

CRITICAL_CALLBACK_TOPIC_ARN = (
    "arn:aws:sns:us-east-1:123456789012:critical-value-callback"
)
EVENT_BUS_NAME = "lab-outlier-events"
OUTLIER_AUDIT_INDEX = "lab-outliers"

# Deploy-time guardrail: catch unreplaced example values. A real callback
# firing to the example account ID would be a bad day for whoever owns it.
assert "123456789012" not in CRITICAL_CALLBACK_TOPIC_ARN or __name__ != "__production__", \
    "CRITICAL_CALLBACK_TOPIC_ARN still uses the example AWS account ID. Replace before deploying."

# --- Detector Version ---
# Every flag, every severity decision, every captured label records the
# detector version. This is how retraining picks its training window, how
# rule tuning attributes regressions to a specific rule-library version,
# and how monitoring tracks alert-rate changes after a deployment.
DETECTOR_VERSION = "lab-outlier-detector-v1.0"
RULE_LIBRARY_VERSION = "rules-v2026.05"
REFERENCE_RANGE_VERSION = "ref-ranges-v2026.05"

# --- Z-Score Thresholds ---
# Patient-history robust z-score: flag when the patient's own value sits
# more than this many MAD-scaled units from their median. 3.0 is the common
# starting point (~ 99.7% under a normal, more permissive under heavy tails).
# Cohort robust z-score: broader population comparison, same threshold shape.
PATIENT_ZSCORE_THRESHOLD = Decimal("3.0")
COHORT_ZSCORE_THRESHOLD = Decimal("3.0")

# Minimum history required before the patient-baseline path is trusted.
# Below this, the MAD estimate is too noisy to flag reliably, and we fall
# back to the cohort baseline for z-score comparisons.
MIN_HISTORY_FOR_BASELINE = 5

# Minimum cohort sample size required before a cohort baseline is trusted.
# Below this, the baseline is too unstable to use; the pipeline skips
# silently rather than flag on an underpowered reference.
MIN_COHORT_SIZE = 100

# --- Severity Tier Ordering ---
# Higher-severity flags override lower ones when aggregating. Critical
# callback is the only tier that fires the CLIA-regulated callback workflow.
SEVERITY_ORDER = {
    "informational":     0,   # below/above reference range, purely descriptive
    "synchronous":       1,   # delta check or z-score flag, chart-visible
    "tech_review_hold":  2,   # hold result from release until a tech reviews
    "recollect_requested": 3, # tech review + new specimen requested
    "critical_callback": 4,   # CLIA-regulated critical-value callback
}

# --- Isolation Forest (panel multivariate path) ---
# Scores below this cut are flagged. Isolation Forest scores roughly sit in
# [-0.5, 0.5] with more negative values more anomalous; -0.15 is a reasonable
# starting point that balances recall against tech-review queue volume.
PANEL_ISOLATION_FOREST_THRESHOLD = Decimal("-0.15")

# --- CUSUM Parameters (patient trajectory path) ---
# Slack (K) and decision threshold (H) in units of baseline stddev.
# Tuned per-analyte in production; starting points here for teaching.
CUSUM_K_MULT = 0.5
CUSUM_H_MULT = 4.0

# --- Analyte Metadata Stubs ---
# A tiny in-process stand-in for a real clinical analyte metadata table.
# Real LOINC codes are used so the identifier shape is authentic. In
# production this table is maintained by clinical chemistry jointly with
# the analytics team and versioned with the rest of the rule library.
ANALYTE_METADATA = {
    # LOINC 2823-3: Potassium [Moles/volume] in Serum or Plasma
    "2823-3": {
        "display_name":       "Potassium, serum",
        "canonical_unit":     "mEq/L",
        "delta_window_hours": 48,       # delta checks meaningful within 48h
        "delta_abs_threshold": 1.0,     # 1.0 mEq/L absolute delta
        "delta_pct_threshold": 25.0,    # 25% percentage delta
        "hemolysis_sensitive": True,    # hemolysis inflates potassium
    },
    # LOINC 718-7: Hemoglobin [Mass/volume] in Blood
    "718-7": {
        "display_name":       "Hemoglobin",
        "canonical_unit":     "g/dL",
        "delta_window_hours": 72,
        "delta_abs_threshold": 2.0,     # 2 g/dL drop or rise flags
        "delta_pct_threshold": 20.0,
        "hemolysis_sensitive": False,
    },
    # LOINC 2345-7: Glucose [Mass/volume] in Serum or Plasma
    "2345-7": {
        "display_name":       "Glucose, serum",
        "canonical_unit":     "mg/dL",
        "delta_window_hours": 24,
        "delta_abs_threshold": 100.0,   # 100 mg/dL shift flags
        "delta_pct_threshold": 50.0,
        "hemolysis_sensitive": False,
    },
    # LOINC 2160-0: Creatinine [Mass/volume] in Serum or Plasma
    "2160-0": {
        "display_name":       "Creatinine, serum",
        "canonical_unit":     "mg/dL",
        "delta_window_hours": 72,
        "delta_abs_threshold": 0.5,
        "delta_pct_threshold": 50.0,
        "hemolysis_sensitive": False,
    },
    # LOINC 2951-2: Sodium [Moles/volume] in Serum or Plasma
    "2951-2": {
        "display_name":       "Sodium, serum",
        "canonical_unit":     "mEq/L",
        "delta_window_hours": 48,
        "delta_abs_threshold": 10.0,
        "delta_pct_threshold": 7.5,
        "hemolysis_sensitive": False,
    },
}

# Critical-value thresholds (the CLIA callback floor). Defined values that
# map to clinical danger regardless of patient context. Real labs maintain
# a larger list; this is a teaching subset.
CRITICAL_VALUE_RULES = {
    "2823-3": {"low": 2.5,  "high": 6.5,  "message": "Potassium critical"},
    "718-7":  {"low": 6.0,  "high": 20.0, "message": "Hemoglobin critical"},
    "2345-7": {"low": 40.0, "high": 500.0, "message": "Glucose critical"},
    "2160-0": {"low": None, "high": 7.0,  "message": "Creatinine critical"},
    "2951-2": {"low": 120.0, "high": 160.0, "message": "Sodium critical"},
}

# Specimen-quality gates. Results with hemolysis above this index on a
# hemolysis-sensitive analyte get held for tech review regardless of value.
HEMOLYSIS_GATE_INDEX = 3     # hemolysis index >= 3 invalidates potassium
ICTERUS_GATE_INDEX = 4
LIPEMIA_GATE_INDEX = 4


def _to_decimal(value) -> Decimal:
    """
    Coerce numeric input into Decimal for DynamoDB and downstream math.

    DynamoDB rejects float. Always pass Decimal. Quantizing to four decimal
    places keeps the storage format predictable without losing meaningful
    precision for lab values, deltas, and z-scores.
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


def _hours_between(t1_iso: str, t2_iso: str) -> float:
    """Return hours between two ISO-8601 timestamps (t2 - t1)."""
    t1 = datetime.fromisoformat(t1_iso.replace("Z", "+00:00"))
    t2 = datetime.fromisoformat(t2_iso.replace("Z", "+00:00"))
    return (t2 - t1).total_seconds() / 3600.0


def _age_band(age_years: Optional[float]) -> str:
    """
    Map age in years to a cohort age band. Reference-range selection uses
    the same bands, so the keys must stay stable across deployments.
    """
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
```

---

## Step 1: Normalize the Incoming Result

*The pseudocode calls this `normalize_result(raw_result)`. The function takes whatever shape an upstream system produced (LIS ORU message, POCT data manager JSON, reference-lab batch file row) and emits a canonical representation keyed on LOINC with doses in canonical units and specimen-quality indices attached. Skip or rush this step, and downstream detectors treat "glucose 110 mg/dL" and "glucose 6.1 mmol/L" as different analytes. Your delta checks misfire and your patient-history baselines get polluted.*

The three correctness properties that matter most here are stable analyte identification (map to LOINC), canonical result units (mg/dL vs mmol/L is a real problem, not a hypothetical one), and resolved patient identity. This example keeps the patient-ID resolution stubbed since enterprise MPI work belongs in Chapter 5 (Entity Resolution); the LOINC mapping and unit harmonization is where most of the real work happens at the normalizer stage.

```python
def normalize_result(raw_result: dict) -> Optional[dict]:
    """
    Produce the canonical result shape the rest of the pipeline expects.
    Returns None for results that could not be normalized; callers should
    route those to a dead-letter queue for data-quality review.

    Expected raw_result fields (any subset; all are optional individually):
      source_event_id, source, analyzer, method, timestamp,
      patient_mrn or patient_id, loinc_code or lis_test_code,
      value, unit, reference_range (optional),
      hemolysis_index, icterus_index, lipemia_index, clot_detected,
      qns_flag, short_sample, collection_site, collected_at, resulted_at,
      accession
    """
    # --- LOINC identification: prefer explicit LOINC; fall back to crosswalk ---
    loinc_code = raw_result.get("loinc_code")
    if not loinc_code and raw_result.get("lis_test_code"):
        # In production, call an LIS-test-code to LOINC crosswalk maintained
        # by the lab informatics team. Unknown codes go to a dead-letter
        # queue for curation rather than being silently dropped.
        loinc_code = _lis_to_loinc_crosswalk(
            raw_result["lis_test_code"],
            analyzer=raw_result.get("analyzer"),
        )

    if not loinc_code:
        _emit_metric("unmapped_test", dimensions={
            "analyzer": raw_result.get("analyzer", "unknown"),
        })
        logger.warning("loinc_unresolved", extra={
            "source_event_id": raw_result.get("source_event_id"),
            "lis_test_code":   raw_result.get("lis_test_code"),
        })
        return None

    analyte_meta = ANALYTE_METADATA.get(loinc_code)
    if analyte_meta is None:
        # Unknown to the analyte metadata. Route to DLQ; a real pipeline
        # supports every test in the lab's formulary, not a subset.
        _emit_metric("unknown_analyte", dimensions={"loinc": loinc_code})
        return None

    # --- Unit harmonization to the canonical unit for this analyte ---
    try:
        canonical_value = _convert_to_canonical_unit(
            raw_value=float(raw_result.get("value") or 0),
            raw_unit=raw_result.get("unit", analyte_meta["canonical_unit"]),
            canonical_unit=analyte_meta["canonical_unit"],
            loinc_code=loinc_code,
        )
    except (TypeError, ValueError):
        logger.warning("unit_parse_failed", extra={
            "source_event_id": raw_result.get("source_event_id"),
            "loinc":           loinc_code,
        })
        return None

    # --- Specimen quality indices ---
    # These are the indicators that make many apparent outliers explainable.
    # Hemolysis, icterus, and lipemia indices are produced by modern chemistry
    # analyzers alongside the result. A missing index is stored as None (not
    # 0) so downstream logic can distinguish "analyzer reported no hemolysis"
    # from "analyzer did not report a hemolysis index."
    specimen_quality = {
        "hemolysis_index":         raw_result.get("hemolysis_index"),
        "icterus_index":           raw_result.get("icterus_index"),
        "lipemia_index":           raw_result.get("lipemia_index"),
        "clot_detected":           raw_result.get("clot_detected", False),
        "qns_flag":                raw_result.get("qns_flag", False),
        "short_sample":            raw_result.get("short_sample", False),
        "collection_site":         raw_result.get("collection_site"),
        "transport_delay_minutes": raw_result.get("transport_delay_minutes"),
    }

    # --- Patient identity resolution ---
    # In production, call the enterprise master patient index. Here we
    # accept either a pre-resolved patient_id or an MRN we treat as the
    # canonical ID for the example.
    patient_id = raw_result.get("patient_id") or raw_result.get("patient_mrn")
    if not patient_id:
        logger.warning("missing_patient_id", extra={
            "source_event_id": raw_result.get("source_event_id"),
        })
        return None

    # --- Reference range attachment ---
    # Pulled from the reference-range-library table. If the raw result
    # already includes a range (some analyzers emit one), we still replace
    # with the validated range from the library so the pipeline has a
    # single source of truth tied to a version.
    reference_range = _lookup_reference_range(
        loinc_code=loinc_code,
        method=raw_result.get("method"),
        analyzer=raw_result.get("analyzer"),
        patient_attributes=_range_selection_attrs(raw_result, patient_id),
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    canonical_result = {
        "event_id":          f"LAB-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}",
        "source_event_id":   raw_result.get("source_event_id"),
        "source":            raw_result.get("source", "lis"),
        "analyzer":          raw_result.get("analyzer"),
        "method":            raw_result.get("method"),
        "patient_id":        patient_id,
        "loinc_code":        loinc_code,
        "loinc_display":     analyte_meta["display_name"],
        "value":             canonical_value,
        "unit":              analyte_meta["canonical_unit"],
        "reference_range":   reference_range,
        "reference_range_version": REFERENCE_RANGE_VERSION,
        "specimen_quality":  specimen_quality,
        "collected_at":      raw_result.get("collected_at"),
        "resulted_at":       raw_result.get("resulted_at") or now_iso,
        "accession":         raw_result.get("accession"),
        "raw": {
            "reported_value": raw_result.get("value"),
            "reported_unit":  raw_result.get("unit"),
            "test_code":      raw_result.get("lis_test_code"),
        },
    }
    return canonical_result


def _lis_to_loinc_crosswalk(lis_test_code: str, analyzer: Optional[str]) -> Optional[str]:
    """
    Tiny in-process crosswalk for teaching. In production this is a managed
    reference table keyed on (analyzer, lis_test_code) because the same
    internal code can mean different tests on different analyzers.
    """
    stub = {
        "K+":      "2823-3",
        "HGB":     "718-7",
        "GLUC":    "2345-7",
        "CREAT":   "2160-0",
        "NA+":     "2951-2",
    }
    return stub.get(lis_test_code.upper()) if lis_test_code else None


def _convert_to_canonical_unit(
    raw_value: float,
    raw_unit: str,
    canonical_unit: str,
    loinc_code: str,
) -> float:
    """
    Convert between compatible result units. This stub handles the common
    mass-volume and molarity conversions that cause the most frequent
    interpretation errors (mg/dL vs mmol/L for glucose is a classic source
    of ten-fold dosing and interpretation mistakes). Real implementations
    use a full unit ontology with analyte-specific molecular weights.
    """
    if raw_unit == canonical_unit or raw_unit is None:
        return raw_value

    # Generic mass conversions.
    mass_factors = {
        ("g/dL", "mg/dL"):    1000.0,
        ("mg/dL", "g/dL"):    0.001,
        ("mg/L", "mg/dL"):    0.1,
        ("mg/dL", "mg/L"):    10.0,
    }
    if (raw_unit, canonical_unit) in mass_factors:
        return raw_value * mass_factors[(raw_unit, canonical_unit)]

    # Analyte-specific mg/dL <-> mmol/L conversions (molecular weights).
    # These are constants; documented in any clinical chemistry reference.
    mmol_factors = {
        "2345-7": 18.0156,   # glucose: mg/dL -> mmol/L divide by 18.0156
        "2160-0": 88.4,      # creatinine: mg/dL -> micromol/L multiply by 88.4
    }
    if raw_unit == "mmol/L" and canonical_unit == "mg/dL" and loinc_code in mmol_factors:
        return raw_value * mmol_factors[loinc_code]
    if raw_unit == "mg/dL" and canonical_unit == "mmol/L" and loinc_code in mmol_factors:
        return raw_value / mmol_factors[loinc_code]

    # Molarity conversions: mEq/L and mmol/L are identical for monovalent
    # ions (Na+, K+, Cl-) but not for divalent (Ca++, Mg++). Analyte-aware
    # table would live here; stub passes through for the teaching case.
    if raw_unit == "mmol/L" and canonical_unit == "mEq/L":
        return raw_value   # true for monovalent electrolytes

    raise ValueError(f"No conversion from {raw_unit} to {canonical_unit} for {loinc_code}")


def _range_selection_attrs(raw_result: dict, patient_id: str) -> dict:
    """
    Gather the patient attributes needed for reference-range selection.
    In a real pipeline this reads from the patient-context cache (same
    source as Step 2); the split here keeps the normalizer narrow so it
    can run in a different Lambda from the enricher.
    """
    # Minimal version: pass through whatever the raw event carried. The
    # enricher in Step 2 will do the full patient-context resolution.
    return {
        "age_years":        raw_result.get("patient_age_years"),
        "sex":              raw_result.get("patient_sex"),
        "pregnancy_status": raw_result.get("patient_pregnancy_status"),
    }


def _lookup_reference_range(
    loinc_code: str,
    method: Optional[str],
    analyzer: Optional[str],
    patient_attributes: dict,
) -> dict:
    """
    Resolve the applicable reference range from the DynamoDB library. The
    sort key combines method and patient attributes so the same analyte
    can carry multiple ranges (pregnancy-specific, pediatric age bands,
    method-specific). If no match is found, fall back to a safe default
    that carries a flag so downstream logic knows the range is generic.
    """
    age_band = _age_band(patient_attributes.get("age_years"))
    sex = patient_attributes.get("sex") or "U"
    pregnancy = "pregnant" if patient_attributes.get("pregnancy_status") == "pregnant" else "npg"
    method_key = method or "default"

    sort_key = f"{method_key}:{sex}:{age_band}:{pregnancy}"
    try:
        table = dynamodb.Table(REFERENCE_RANGE_TABLE)
        response = table.get_item(Key={"loinc_code": loinc_code, "range_key": sort_key})
        item = response.get("Item")
    except Exception as ex:
        logger.warning("reference_range_lookup_failed", extra={
            "loinc": loinc_code, "error": str(ex),
        })
        item = None

    if item:
        return {
            "low":    float(item["low"]),
            "high":   float(item["high"]),
            "source": item.get("source", "library"),
            "version": REFERENCE_RANGE_VERSION,
            "key":    sort_key,
        }

    # Fallback to a generic adult range. Flag it so downstream knows the
    # range is not patient-specific. Real labs have tighter fallback rules.
    fallback = {
        "2823-3": {"low": 3.5, "high": 5.1},
        "718-7":  {"low": 11.5 if sex == "F" else 13.0, "high": 15.5 if sex == "F" else 17.0},
        "2345-7": {"low": 70.0, "high": 99.0},
        "2160-0": {"low": 0.6, "high": 1.3},
        "2951-2": {"low": 135.0, "high": 145.0},
    }
    generic = fallback.get(loinc_code, {"low": None, "high": None})
    return {
        **generic,
        "source": "generic_fallback",
        "version": REFERENCE_RANGE_VERSION,
        "key":    sort_key,
    }
```

---

## Step 2: Enrich with Patient Context and Recent History

*The pseudocode calls this `enrich_with_patient_context(canonical_result)`. The function reads the patient-context cache, attaches demographics and active problems and active medications, pulls the patient's recent results for this analyte, computes the most-recent-prior-result for delta check input, and derives rolling baseline statistics (median, MAD, trend) when enough history exists.*

This is the step that blows up in production more often than any other. Active problem lists and medication lists that are free-text rather than coded; pregnancy flags that are missing or stale; recent-result caches that lag the LIS by hours; age values that are computed from a date-of-birth field that was parsed inconsistently. Every one of those data-quality issues produces either confident wrong answers or silent failures. Invest heavily in the cache-refresh pipeline and keep the staleness tracking visible to the scorer.

```python
def enrich_with_patient_context(canonical_result: dict) -> Optional[dict]:
    """
    Attach the patient-context snapshot and recent-history slice to the
    canonical result. Returns None if the patient is unknown to the cache;
    callers should route those events to a "patient-not-found" queue
    rather than let them score against a missing context.
    """
    table = dynamodb.Table(PATIENT_CONTEXT_TABLE)
    response = table.get_item(Key={"patient_id": canonical_result["patient_id"]})
    context_item = response.get("Item")
    if not context_item:
        _emit_metric("patient_context_missing")
        return None

    context = _decimal_to_float(context_item)
    enriched = dict(canonical_result)

    # --- Demographics and clinical attributes ---
    enriched["patient_attributes"] = {
        "age_years":          context.get("age_years"),
        "sex":                context.get("sex"),
        "pregnancy_status":   context.get("pregnancy_status"),
        "acuity":             context.get("acuity", "ward"),
        "location":           context.get("unit"),
        "active_problems":    context.get("active_problems", []),
        "active_medications": context.get("active_medications", []),
        "on_dialysis":        bool(context.get("is_on_dialysis", False)),
    }

    # --- Recent results for this analyte ---
    # The cache stores a rolling window per analyte. Acute-care analytes
    # keep ~30 days of history; chronic markers like A1C keep longer.
    # In production, if the cache does not have this analyte's history,
    # fall back to a bounded LIS query rather than failing closed.
    recent_results_by_loinc = context.get("recent_results", {})
    recent = recent_results_by_loinc.get(canonical_result["loinc_code"], [])

    # Defensive sort so the "most recent prior" is actually the most recent.
    # Upstream feeds occasionally deliver out-of-order updates.
    recent_sorted = sorted(
        recent,
        key=lambda r: r.get("resulted_at", ""),
        reverse=True,
    )
    enriched["recent_results"] = recent_sorted

    # --- Most recent prior result: input for the delta check ---
    previous_result = None
    for r in recent_sorted:
        if r.get("resulted_at") and r["resulted_at"] < canonical_result["resulted_at"]:
            previous_result = r
            break
    enriched["previous_result"] = previous_result

    # --- Rolling baseline statistics from the patient's own history ---
    # Use median and median-absolute-deviation (MAD) rather than mean and
    # stddev. Lab values have heavy tails and occasional extreme outliers
    # (the same artifactual values we are trying to detect); MAD ignores
    # them when summarizing the baseline.
    values = [
        float(r["value"]) for r in recent_sorted
        if r.get("value") is not None
    ]
    baseline_stats = None
    if len(values) >= MIN_HISTORY_FOR_BASELINE:
        med = median(values)
        mad = median([abs(v - med) for v in values])
        baseline_stats = {
            "median":       med,
            "mad":          mad,
            "min":          min(values),
            "max":          max(values),
            "sample_size":  len(values),
            "earliest_observed_at": recent_sorted[-1].get("resulted_at"),
            "latest_observed_at":   recent_sorted[0].get("resulted_at"),
        }
    enriched["baseline_stats"] = baseline_stats

    return enriched
```

---

## Step 3: Rule-Based Screen (Critical, Reference Range, Specimen Quality)

*The pseudocode calls this `rule_screen(enriched_result)`. For each enriched result, run the rule library: hard critical-value thresholds (the CLIA regulatory floor), reference-range abnormal flags, specimen-quality gates for hemolysis/icterus/lipemia/clot on sensitive analytes, and collection-site gates for tests that should not be drawn from lines running incompatible fluids.*

Critical value rules are the non-negotiable layer. They always fire when threshold is crossed, regardless of patient context, because the regulatory and clinical stakes are too high to risk missing them. What the rest of the pipeline adds is context (hemolysis on a critical potassium, for example) that rides alongside the callback so a clinician can disposition faster. It never suppresses the callback itself.

```python
def rule_screen(enriched_result: dict) -> list:
    """
    Run the applicable rules against the enriched result. Returns a list
    of flag dicts; an empty list means every rule passed. The structure
    of each flag is deliberately flat and explainable: rule type, the
    triggering value, the threshold or reference, a severity tier, and
    a human-readable message.
    """
    flags = []
    loinc = enriched_result["loinc_code"]
    value = enriched_result["value"]

    # --- Critical-value rules (always fire; CLIA callback floor) ---
    crit = CRITICAL_VALUE_RULES.get(loinc)
    if crit is not None:
        if crit["high"] is not None and value >= crit["high"]:
            flags.append({
                "rule_id":    f"CRITICAL_{loinc}_HIGH",
                "rule_type":  "critical_value_high",
                "severity":   "critical_callback",
                "value":      _to_decimal(value),
                "threshold":  _to_decimal(crit["high"]),
                "message":    f"{crit['message']} high: {value} {enriched_result['unit']} >= {crit['high']}",
                "reference":  f"{RULE_LIBRARY_VERSION}:critical_values",
            })
        if crit["low"] is not None and value <= crit["low"]:
            flags.append({
                "rule_id":    f"CRITICAL_{loinc}_LOW",
                "rule_type":  "critical_value_low",
                "severity":   "critical_callback",
                "value":      _to_decimal(value),
                "threshold":  _to_decimal(crit["low"]),
                "message":    f"{crit['message']} low: {value} {enriched_result['unit']} <= {crit['low']}",
                "reference":  f"{RULE_LIBRARY_VERSION}:critical_values",
            })

    # --- Reference range (informational; chart-visible low/high flag) ---
    ref = enriched_result.get("reference_range") or {}
    if ref.get("low") is not None and value < ref["low"]:
        flags.append({
            "rule_type":  "below_reference_range",
            "severity":   "informational",
            "value":      _to_decimal(value),
            "range_low":  _to_decimal(ref["low"]),
            "range_high": _to_decimal(ref["high"]) if ref.get("high") is not None else None,
            "message":    f"Value {value} below reference range ({ref.get('low')}-{ref.get('high')})",
        })
    elif ref.get("high") is not None and value > ref["high"]:
        flags.append({
            "rule_type":  "above_reference_range",
            "severity":   "informational",
            "value":      _to_decimal(value),
            "range_low":  _to_decimal(ref["low"]) if ref.get("low") is not None else None,
            "range_high": _to_decimal(ref["high"]),
            "message":    f"Value {value} above reference range ({ref.get('low')}-{ref.get('high')})",
        })

    # --- Specimen-quality gates ---
    # The textbook case: hemolysis inflates potassium. Hemolysis index at
    # or above the analyte-specific threshold holds the result for tech
    # review rather than releasing it, regardless of how dramatic the
    # value looks. The tech either accepts (if the history and clinical
    # picture support the value) or requests a recollect.
    analyte_meta = ANALYTE_METADATA.get(loinc, {})
    sq = enriched_result.get("specimen_quality", {})

    hemolysis = sq.get("hemolysis_index")
    if analyte_meta.get("hemolysis_sensitive") and hemolysis is not None and hemolysis >= HEMOLYSIS_GATE_INDEX:
        flags.append({
            "rule_id":       f"HEMOLYSIS_GATE_{loinc}",
            "rule_type":     "specimen_quality_invalidating",
            "severity":      "tech_review_hold",
            "quality_index": "hemolysis_index",
            "quality_value": int(hemolysis),
            "threshold":     HEMOLYSIS_GATE_INDEX,
            "message": (
                f"Hemolysis index {hemolysis} at or above {HEMOLYSIS_GATE_INDEX} "
                f"for {analyte_meta.get('display_name', loinc)}; result likely artifactual."
            ),
            "recommended_action": "recollect",
        })

    # Icterus and lipemia interference: applied across many analytes in a
    # real library. Teaching stub applies a simple gate.
    icterus = sq.get("icterus_index")
    if icterus is not None and icterus >= ICTERUS_GATE_INDEX:
        flags.append({
            "rule_id":       f"ICTERUS_GATE_{loinc}",
            "rule_type":     "specimen_quality_invalidating",
            "severity":      "tech_review_hold",
            "quality_index": "icterus_index",
            "quality_value": int(icterus),
            "threshold":     ICTERUS_GATE_INDEX,
            "message":       f"Icterus index {icterus} may interfere with {loinc}",
            "recommended_action": "method_suppress_or_recollect",
        })

    lipemia = sq.get("lipemia_index")
    if lipemia is not None and lipemia >= LIPEMIA_GATE_INDEX:
        flags.append({
            "rule_id":       f"LIPEMIA_GATE_{loinc}",
            "rule_type":     "specimen_quality_invalidating",
            "severity":      "tech_review_hold",
            "quality_index": "lipemia_index",
            "quality_value": int(lipemia),
            "threshold":     LIPEMIA_GATE_INDEX,
            "message":       f"Lipemia index {lipemia} may interfere with {loinc}",
            "recommended_action": "method_suppress_or_recollect",
        })

    if sq.get("clot_detected"):
        flags.append({
            "rule_type":  "specimen_quality_invalidating",
            "severity":   "tech_review_hold",
            "message":    "Clot detected on specimen; result held for review.",
            "recommended_action": "recollect",
        })

    if sq.get("qns_flag"):
        flags.append({
            "rule_type":  "specimen_quality_invalidating",
            "severity":   "tech_review_hold",
            "message":    "Quantity not sufficient; result held.",
            "recommended_action": "recollect",
        })

    return flags
```

---

## Step 4: Delta Check and Patient-History Robust Z-Score

*The pseudocode calls this `patient_baseline_checks(enriched_result)`. These are the patient-specific statistical detectors: a delta check against the most recent prior result within the analyte's window, and a robust z-score against the patient's own historical distribution when enough history exists. These catch real clinical changes and specimen-misidentification patterns that population-level checks cannot see.*

Delta checks do more work than any other single component of the pipeline. Most clinical changes that matter are visible as a departure from the patient's own recent value, and most specimen-identification errors show up as absurd departures from the patient's own recent value (if the last hemoglobin was 14 and the current one is 7, either something acute happened or the tube has the wrong patient's label). This is also the layer most undertuned in production because the default thresholds from the LIS vendor rarely match the actual lab's population.

```python
def patient_baseline_checks(enriched_result: dict) -> list:
    """
    Return any patient-specific flags: delta-check failures and robust
    z-score against the patient's own history. Silent skip when input
    data is insufficient (no prior result within window, or history too
    thin for a stable MAD estimate).
    """
    flags = []
    loinc = enriched_result["loinc_code"]
    analyte_meta = ANALYTE_METADATA.get(loinc, {})
    current_value = enriched_result["value"]

    # --- Delta check ---
    previous = enriched_result.get("previous_result")
    if previous is not None and previous.get("resulted_at") and enriched_result.get("resulted_at"):
        delta_hours = _hours_between(previous["resulted_at"], enriched_result["resulted_at"])
        window_hours = analyte_meta.get("delta_window_hours", 48)

        if delta_hours <= window_hours:
            prev_value = float(previous["value"])
            absolute_delta = current_value - prev_value
            percent_delta = (absolute_delta / prev_value * 100.0) if prev_value != 0 else None

            abs_threshold = analyte_meta.get("delta_abs_threshold", 0.0)
            pct_threshold = analyte_meta.get("delta_pct_threshold", 0.0)
            triggered = (
                abs(absolute_delta) >= abs_threshold
                or (percent_delta is not None and abs(percent_delta) >= pct_threshold)
            )

            if triggered:
                # Severity escalates for very large percent deltas on
                # short intervals. Tune against the lab's override data.
                severity = "synchronous"
                if percent_delta is not None and abs(percent_delta) >= pct_threshold * 2:
                    severity = "tech_review_hold"

                flags.append({
                    "rule_type":            "delta_check_failure",
                    "severity":             severity,
                    "absolute_delta":       _to_decimal(absolute_delta),
                    "percent_delta":        _to_decimal(percent_delta) if percent_delta is not None else None,
                    "previous_value":       _to_decimal(prev_value),
                    "previous_resulted_at": previous["resulted_at"],
                    "hours_between_results": _to_decimal(delta_hours),
                    "message": (
                        f"{analyte_meta.get('display_name', loinc)} shifted from {prev_value} "
                        f"to {current_value} {enriched_result['unit']} in {delta_hours:.1f} hours."
                    ),
                })

    # --- Patient-history robust z-score ---
    baseline = enriched_result.get("baseline_stats")
    if baseline is not None and baseline["mad"] > 0:
        # MAD scaled by 1.4826 estimates stddev under a normal distribution.
        # The factor is conservative for the heavy-tailed lab distributions
        # we actually see, which is exactly the property we want: a more
        # permissive threshold reduces false positives on naturally variable
        # analytes like random glucose.
        robust_z = (current_value - baseline["median"]) / (1.4826 * baseline["mad"])
        if abs(robust_z) >= float(PATIENT_ZSCORE_THRESHOLD):
            flags.append({
                "rule_type":     "patient_history_zscore",
                "severity":      "synchronous" if abs(robust_z) < 5.0 else "tech_review_hold",
                "robust_z":      _to_decimal(robust_z),
                "patient_median": _to_decimal(baseline["median"]),
                "patient_mad":   _to_decimal(baseline["mad"]),
                "history_size":  baseline["sample_size"],
                "message": (
                    f"Value {current_value} is {robust_z:+.2f} MAD-scaled units from this "
                    f"patient's historical median of {baseline['median']:.2f}."
                ),
            })

    return flags
```

---

## Step 5: Cohort Population Z-Score

*The pseudocode calls this `cohort_zscore_check(enriched_result)`. For patients without enough history to support the patient-baseline path, compare against the population cohort baseline from SageMaker Feature Store. The cohort partition is a composite key of analyte + age band + sex + pregnancy status + dialysis status; broader partitions give you sample size at the cost of specificity, narrower partitions give you specificity at the cost of sample size.*

This path is the fallback, not the default. Patient-baseline comparisons (when history exists) are almost always more useful than cohort comparisons. But for a new admission, an ED walk-in, or a patient moving between facilities without linked history, the cohort baseline is the only statistical comparator available, and it needs to work safely.

```python
def cohort_zscore_check(enriched_result: dict) -> list:
    """
    Return a cohort-level z-score flag if one fires. The baseline record
    is keyed in the Feature Store by the analyte + profile-bucket string.
    Silent skip when the baseline is missing or has too few samples; the
    pipeline prefers "no flag" over "flag with insufficient confidence".
    """
    flags = []
    loinc = enriched_result["loinc_code"]
    attrs = enriched_result.get("patient_attributes", {})

    profile_bucket = _build_cohort_key(attrs)
    record_id = f"{loinc}:{profile_bucket}"

    baseline = _get_cohort_baseline(record_id)
    if baseline is None:
        # Fallback to the analyte's overall baseline across all demographics.
        baseline = _get_cohort_baseline(f"{loinc}:overall")
        if baseline is None:
            return flags

    sample_size = baseline.get("sample_size") or 0
    if sample_size < MIN_COHORT_SIZE:
        return flags

    median_val = baseline.get("median")
    mad_val = baseline.get("mad")
    if median_val is None or mad_val is None or mad_val == 0:
        return flags

    robust_z = (enriched_result["value"] - median_val) / (1.4826 * mad_val)
    if abs(robust_z) >= float(COHORT_ZSCORE_THRESHOLD):
        flags.append({
            "rule_type":        "cohort_zscore",
            "severity":         "synchronous" if abs(robust_z) < 5.0 else "tech_review_hold",
            "robust_z":         _to_decimal(robust_z),
            "cohort_key":       profile_bucket,
            "cohort_median":    _to_decimal(median_val),
            "cohort_mad":       _to_decimal(mad_val),
            "cohort_sample_size": sample_size,
            "message": (
                f"Value {enriched_result['value']} is {robust_z:+.2f} MAD-scaled units "
                f"from the {profile_bucket} cohort median of {median_val:.2f}."
            ),
        })
    return flags


def _build_cohort_key(patient_attributes: dict) -> str:
    """
    Canonical cohort-key string used as the Feature Store partition. Keep
    this stable; baseline records are keyed on it and a format change
    invalidates every cached baseline.
    """
    age_band = _age_band(patient_attributes.get("age_years"))
    sex = patient_attributes.get("sex") or "U"
    pregnancy = "pregnant" if patient_attributes.get("pregnancy_status") == "pregnant" else "npg"
    dialysis = "hd" if patient_attributes.get("on_dialysis") else "nohd"
    return f"{age_band}:{sex}:{pregnancy}:{dialysis}"


def _get_cohort_baseline(record_id: str) -> Optional[dict]:
    """
    Read a single baseline record from the Feature Store online store.
    Returns a dict of floats (converted from the wire-format strings) or
    None when the record does not exist.
    """
    try:
        response = featurestore_runtime.get_record(
            FeatureGroupName=COHORT_BASELINES_FG,
            RecordIdentifierValueAsString=record_id,
        )
    except featurestore_runtime.exceptions.ResourceNotFound:
        return None
    record = response.get("Record")
    if not record:
        return None

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
            parsed[name] = raw
    return parsed
```

---

## Step 6: Aggregate Flags, Determine Severity, and Route

*The pseudocode calls this `route_result(enriched_result, all_flags)`. Combine flags from all detectors, determine overall routing (autoverify, autoverify-with-flag, tech-review-hold, recollect-requested, critical-callback), publish the outlier event to EventBridge for fan-out to the callback service, tech-review queue, autoverify release service, audit index, and feedback capture. Critical callback flags also publish synchronously to the SNS topic that feeds the paging and messaging platform.*

The routing decision is the point in the pipeline where clinical governance meets code. Every flag that reaches a clinician costs attention; every low-value flag trains the clinician to dismiss the next one reflexively. The severity-tier thresholds, the suppression rules, and the callback payloads are not technical configuration; they are clinical decisions owned by the laboratory director and clinical leadership. This function is where those decisions live in the runtime.

```python
def route_result(enriched_result: dict, all_flags: list) -> Optional[dict]:
    """
    Combine, audit-index, and route the flags produced by the detectors.
    Returns the outlier event dict for the caller to emit metrics on, or
    None if no flags fired (in which case the result autoverifies and a
    silent audit record is written).
    """
    if not all_flags:
        # Clean result: autoverify and release. Write an audit record so
        # retrospective reviews after a downstream incident can confirm
        # the pipeline looked at this result and found nothing notable.
        _autoverify_release(enriched_result, chart_flag=None)
        _index_dispense_audit(enriched_result, flags=[])
        _emit_metric("result_scored_clean", dimensions={
            "loinc": enriched_result["loinc_code"],
        })
        return None

    overall_severity = _max_severity(all_flags)
    routing = _severity_to_routing(overall_severity, all_flags)

    outlier_event = {
        "event_id":         enriched_result["event_id"],
        "patient_id":       enriched_result["patient_id"],
        "loinc_code":       enriched_result["loinc_code"],
        "loinc_display":    enriched_result["loinc_display"],
        "value":            _to_decimal(enriched_result["value"]),
        "unit":             enriched_result["unit"],
        "resulted_at":      enriched_result["resulted_at"],
        "accession":        enriched_result.get("accession"),
        "flags":            all_flags,
        "flag_count":       len(all_flags),
        "severity":         overall_severity,
        "routing":          routing,
        "specimen_quality": enriched_result.get("specimen_quality"),
        "patient_context_summary": _context_snapshot(enriched_result),
        "previous_result":  enriched_result.get("previous_result"),
        "reference_range":  enriched_result.get("reference_range"),
        "reference_range_version": enriched_result.get("reference_range_version"),
        "detector_version": DETECTOR_VERSION,
        "rule_library_version": RULE_LIBRARY_VERSION,
        "detected_at":      datetime.now(timezone.utc).isoformat(),
    }

    # Audit index: every flagged event is searchable by the pathologist
    # and lab director dashboards and the retrospective-review workflow.
    _index_outlier_event(outlier_event)

    # EventBridge fan-out: callback service, tech-review queue, autoverify
    # release service, metrics aggregator, feedback capture all subscribe
    # to the bus and consume in parallel. The detail-type encodes the
    # routing so consumers can filter without deserializing the payload.
    _publish_to_event_bus(outlier_event)

    # Routing-specific synchronous actions.
    if routing == "critical_callback":
        # Critical values are released to the chart AND fire the CLIA
        # callback workflow. The callback is a separate, regulated workflow
        # with timing and read-back requirements; we kick it off here.
        _publish_critical_callback(outlier_event)
        _autoverify_release(enriched_result, chart_flag="critical_value")
    elif routing == "tech_review_hold":
        _hold_for_tech_review(enriched_result, outlier_event, request_recollect=False)
    elif routing == "recollect_requested":
        _hold_for_tech_review(enriched_result, outlier_event, request_recollect=True)
    elif routing == "autoverify_with_flag":
        chart_flag = _choose_chart_flag(all_flags)
        _autoverify_release(enriched_result, chart_flag=chart_flag)

    _emit_metric("outlier_flagged", dimensions={
        "loinc":    enriched_result["loinc_code"],
        "routing":  routing,
        "severity": overall_severity,
    })

    return outlier_event


def _max_severity(flags: list) -> str:
    """Return the highest-severity tier across all flags."""
    highest = "informational"
    for flag in flags:
        sev = flag.get("severity", "informational")
        if SEVERITY_ORDER.get(sev, 0) > SEVERITY_ORDER.get(highest, 0):
            highest = sev
    return highest


def _severity_to_routing(overall_severity: str, flags: list) -> str:
    """
    Map the aggregated severity to a routing action. Critical callback
    wins over everything; a specimen-quality-invalidating flag on a
    critical value still fires the callback but the tech-review hold is
    tracked so the tech can disposition quickly after the callback is made.
    """
    if overall_severity == "critical_callback":
        return "critical_callback"
    if any(f.get("recommended_action") == "recollect" for f in flags):
        return "recollect_requested"
    if overall_severity == "tech_review_hold":
        return "tech_review_hold"
    return "autoverify_with_flag"


def _choose_chart_flag(flags: list) -> Optional[str]:
    """
    Select the chart-visible flag text for autoverify-with-flag routing.
    The chart surface is compact; one concise flag per result is the
    operating convention. Delta-check flags win over reference-range
    flags because they carry more clinical signal.
    """
    delta_flag = next((f for f in flags if f.get("rule_type") == "delta_check_failure"), None)
    if delta_flag is not None:
        return "delta_abnormal"
    ref_high = next((f for f in flags if f.get("rule_type") == "above_reference_range"), None)
    ref_low = next((f for f in flags if f.get("rule_type") == "below_reference_range"), None)
    if ref_high:
        return "H"
    if ref_low:
        return "L"
    return None


def _context_snapshot(enriched_result: dict) -> dict:
    """
    Return the subset of the enriched result that gets persisted with the
    outlier record. Kept narrow because this snapshot is what a later
    retrospective review will see; too much detail creates PHI exposure,
    too little makes the alert un-auditable.
    """
    attrs = enriched_result.get("patient_attributes", {})
    return {
        "age_years":          attrs.get("age_years"),
        "sex":                attrs.get("sex"),
        "pregnancy_status":   attrs.get("pregnancy_status"),
        "acuity":             attrs.get("acuity"),
        "on_dialysis":        attrs.get("on_dialysis"),
        "active_problems":    attrs.get("active_problems", []),
        "history_size":       len(enriched_result.get("recent_results", [])),
    }


def _index_outlier_event(outlier_event: dict) -> None:
    """
    Write the outlier event to the OpenSearch audit index. In a real
    Lambda, we would use `requests-aws4auth` to sign the request; the
    low-level signing implementation is omitted here for brevity.
    """
    # Placeholder for OpenSearch indexing.
    logger.info("outlier_indexed", extra={
        "event_id": outlier_event["event_id"],
        "routing":  outlier_event["routing"],
        "severity": outlier_event["severity"],
    })


def _index_dispense_audit(enriched_result: dict, flags: list) -> None:
    """
    Record the fact that we scored this result, whether or not it flagged.
    Required for retrospective reviews after a downstream incident.
    """
    audit = {
        "event_id":         enriched_result["event_id"],
        "patient_id":       enriched_result["patient_id"],
        "loinc_code":       enriched_result["loinc_code"],
        "resulted_at":      enriched_result["resulted_at"],
        "flag_count":       len(flags),
        "detector_version": DETECTOR_VERSION,
        "scored_at":        datetime.now(timezone.utc).isoformat(),
    }
    logger.info("result_audited", extra=audit)


def _publish_to_event_bus(outlier_event: dict) -> None:
    """
    Put the outlier event on the EventBridge bus so subscribed Lambdas
    pick it up in parallel. The detail-type encodes the routing so rules
    can filter without deserializing the full payload.
    """
    try:
        eventbridge.put_events(Entries=[{
            "Source":       "lab-outlier-service",
            "DetailType":   f"LabOutlier.{outlier_event['routing']}",
            "EventBusName": EVENT_BUS_NAME,
            "Detail":       json.dumps(_decimal_to_float(outlier_event), default=str),
        }])
    except Exception as ex:
        logger.error("event_bus_publish_failed", extra={
            "event_id": outlier_event["event_id"],
            "error":    str(ex),
        })


def _publish_critical_callback(outlier_event: dict) -> None:
    """
    Fire the critical-value callback notification. The SNS payload carries
    the event ID and minimal routing context; the callback service fetches
    the full record by ID so PHI does not flow through SNS or downstream
    paging providers beyond what their BAAs cover.

    This is where the CLIA-regulated callback state machine plugs in. The
    real implementation tracks callback timing against the mandated window,
    records recipient, read-back confirmation, and closure, and escalates
    when the primary target does not acknowledge within a defined time.
    """
    message = {
        "event_id":       outlier_event["event_id"],
        "loinc_code":     outlier_event["loinc_code"],
        "loinc_display":  outlier_event["loinc_display"],
        "severity":       outlier_event["severity"],
        "resulted_at":    outlier_event["resulted_at"],
        "detected_at":    outlier_event["detected_at"],
    }
    try:
        sns.publish(
            TopicArn=CRITICAL_CALLBACK_TOPIC_ARN,
            Message=json.dumps(message),
            Subject=f"Critical value: {outlier_event['loinc_display']}",
            MessageAttributes={
                "severity": {
                    "DataType":    "String",
                    "StringValue": outlier_event["severity"],
                },
            },
        )
    except Exception as ex:
        # Callback-delivery failures are a patient-safety event. Log loudly,
        # emit a metric, and rely on the fallback channel defined by the
        # callback service (a human phone call is the ultimate fallback).
        logger.error("critical_callback_publish_failed", extra={
            "event_id": outlier_event["event_id"],
            "error":    str(ex),
        })
        _emit_metric("critical_callback_publish_failure")


def _autoverify_release(enriched_result: dict, chart_flag: Optional[str]) -> None:
    """
    Placeholder for the autoverify release service. In production, the
    release Lambda publishes the result back to the LIS-to-EHR bridge
    (often an HL7 v2 ORU acknowledgment path) with the chart flag attached.
    """
    logger.info("autoverify_released", extra={
        "event_id":   enriched_result["event_id"],
        "loinc":      enriched_result["loinc_code"],
        "chart_flag": chart_flag,
    })


def _hold_for_tech_review(
    enriched_result: dict,
    outlier_event: dict,
    request_recollect: bool,
) -> None:
    """
    Placeholder for the tech-review queue service. Writes a review task
    into the review workqueue (backed by DynamoDB in the real pipeline)
    and does not release the result to the chart until the tech
    dispositions. If request_recollect, also notify the collection team.
    """
    logger.info("held_for_tech_review", extra={
        "event_id":          enriched_result["event_id"],
        "routing":           outlier_event["routing"],
        "request_recollect": request_recollect,
    })


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
            Namespace="LabOutlier",
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

## Step 7: Batch Panel Multivariate and Patient Trajectory Scoring

*The pseudocode calls these `panel_multivariate_check(panel)` and `patient_trajectory_scoring(as_of_timestamp)`. The panel-level check runs an Isolation Forest over complete panels (e.g., basic metabolic panel with Na/K/Cl/CO2/BUN/creatinine/glucose/Ca) to catch combinations that are multivariate outliers even when no single component crosses a threshold. The trajectory check runs CUSUM on per-analyte patient time series to catch sustained shifts that no single-event delta check would flag.*

The per-event path in Steps 1 through 6 catches anomalies visible in the individual result. The batch path catches two classes of anomaly that single-event checks cannot see: unusual combinations of otherwise-normal values (the multivariate case) and gradual drift where each step is within range but the trend is clinically significant (the trajectory case). Each has its own teaching-stubbed implementation below; in production both run as SageMaker Processing jobs on a schedule appropriate to the clinical setting (every 15 minutes for ICU analytes, hourly for ward, daily for ambulatory).

```python
def panel_multivariate_check(
    panel_df: pd.DataFrame,
    as_of_timestamp: datetime,
) -> list:
    """
    Score panel-level feature vectors against the Isolation Forest loaded
    from S3. `panel_df` has one row per completed panel with columns for
    each panel component (e.g., sodium, potassium, chloride, bicarbonate,
    bun, creatinine, glucose, calcium) plus a patient_id and accession.

    Returns a list of panel-level outlier events. Silent skip when the
    model artifact is missing; a missing model is a pipeline issue, not
    a patient-safety one.
    """
    if panel_df.empty:
        return []

    model_payload = _load_isolation_forest("current/panel_isolation_forest.joblib")
    if model_payload is None:
        logger.warning("panel_isolation_forest_unavailable")
        return []

    model = model_payload["model"]
    feature_names = model_payload["meta"]["feature_names"]
    X = panel_df[feature_names].fillna(0.0).astype(float).values

    scores = model.score_samples(X)
    events = []
    for i, score in enumerate(scores):
        if score > float(PANEL_ISOLATION_FOREST_THRESHOLD):
            continue
        row = panel_df.iloc[i]
        # Top contributing features: signed distance from the panel-wise
        # median in stddev units. Real deployments use SHAP or a similar
        # per-prediction explainer, but this rank-order fallback carries
        # the same clinical intent: "which components of the panel are
        # most responsible for this looking unusual together."
        feature_medians = panel_df[feature_names].median().astype(float)
        feature_stds = panel_df[feature_names].std(ddof=1).replace(0, 1.0).astype(float)
        contributions = []
        for fname in feature_names:
            z = (float(row[fname]) - feature_medians[fname]) / feature_stds[fname]
            contributions.append((fname, float(z)))
        contributions.sort(key=lambda x: abs(x[1]), reverse=True)

        events.append({
            "type":             "panel_multivariate_outlier",
            "event_id":         f"PANEL-{uuid.uuid4().hex[:10]}",
            "patient_id":       row["patient_id"],
            "accession":        row.get("accession"),
            "as_of":            as_of_timestamp.isoformat(),
            "anomaly_score":    _to_decimal(float(score)),
            "top_contributors": [
                {"feature": f, "z": _to_decimal(z)}
                for f, z in contributions[:5]
            ],
            "severity":         "tech_review_hold",
            "detector_version": DETECTOR_VERSION,
            "detected_at":      as_of_timestamp.isoformat(),
            "message":          "Panel combination is a multivariate outlier; review top contributors.",
        })
    return events


def patient_trajectory_cusum(
    patient_series: pd.DataFrame,
    loinc_code: str,
    as_of_timestamp: datetime,
) -> Optional[dict]:
    """
    Two-sided CUSUM on a patient's time series for a single analyte.
    `patient_series` columns: patient_id, loinc_code, value, resulted_at.
    Splits the series in half, uses the first half as baseline, accumulates
    deviations scaled by the analyte's natural variability, and flags if
    the accumulation crosses the decision boundary.

    Returns a trajectory flag dict, or None if the series has too few
    points or no change-point is detected.
    """
    series = patient_series.sort_values("resulted_at")
    values = series["value"].astype(float).tolist()
    if len(values) < 10:
        return None

    split = len(values) // 2
    baseline = values[:split]
    if len(baseline) < 3:
        return None

    baseline_mean = sum(baseline) / len(baseline)
    baseline_std = pd.Series(baseline).std(ddof=1) or 1.0
    k = CUSUM_K_MULT * baseline_std
    h = CUSUM_H_MULT * baseline_std

    cusum_pos = 0.0
    cusum_neg = 0.0
    change_index = None
    for i, value in enumerate(values):
        cusum_pos = max(0.0, cusum_pos + (value - baseline_mean) - k)
        cusum_neg = min(0.0, cusum_neg + (value - baseline_mean) + k)
        if cusum_pos > h or cusum_neg < -h:
            change_index = i
            break

    if change_index is None:
        return None

    post = values[change_index:]
    post_mean = sum(post) / len(post)
    shift = post_mean - baseline_mean
    change_point_ts = series.iloc[change_index]["resulted_at"]

    # Severity escalates when the shift is large relative to the baseline
    # stddev. A creatinine climb of 0.3 mg/dL is noteworthy in a patient
    # whose history has held at 0.9 with stddev 0.05; the same climb in a
    # patient whose stddev is 0.3 is noise.
    severity = "synchronous"
    if baseline_std > 0 and abs(shift) / baseline_std >= 3.0:
        severity = "tech_review_hold"

    return {
        "type":             "patient_trajectory_cusum",
        "event_id":         f"TRAJ-{uuid.uuid4().hex[:10]}",
        "patient_id":       series.iloc[0]["patient_id"],
        "loinc_code":       loinc_code,
        "change_point":     change_point_ts,
        "pre_change_mean":  _to_decimal(baseline_mean),
        "post_change_mean": _to_decimal(post_mean),
        "shift_magnitude":  _to_decimal(shift),
        "baseline_stddev":  _to_decimal(baseline_std),
        "severity":         severity,
        "detector_version": DETECTOR_VERSION,
        "detected_at":      as_of_timestamp.isoformat(),
        "message": (
            f"{ANALYTE_METADATA.get(loinc_code, {}).get('display_name', loinc_code)} "
            f"shifted from {baseline_mean:.2f} to {post_mean:.2f} after {change_point_ts}."
        ),
    }


def run_batch_trajectory_scoring(
    recent_results_df: pd.DataFrame,
    as_of_timestamp: datetime,
) -> list:
    """
    Driver for the trajectory path: group by patient + analyte, run CUSUM
    on each group, publish every fired flag to the same EventBridge bus
    used by the per-event path. In production this is the body of a
    SageMaker Processing job scheduled by EventBridge Scheduler.
    """
    if recent_results_df.empty:
        return []

    events = []
    for (patient_id, loinc_code), group in recent_results_df.groupby(["patient_id", "loinc_code"]):
        traj_event = patient_trajectory_cusum(group, loinc_code, as_of_timestamp)
        if traj_event is not None:
            events.append(traj_event)
            # Publish to the same EventBridge bus as per-event outliers.
            # Downstream consumers (tech review queue, audit index) treat
            # trajectory flags the same as event-level flags by default.
            try:
                eventbridge.put_events(Entries=[{
                    "Source":       "lab-outlier-service",
                    "DetailType":   f"LabOutlier.trajectory.{traj_event['severity']}",
                    "EventBusName": EVENT_BUS_NAME,
                    "Detail":       json.dumps(_decimal_to_float(traj_event), default=str),
                }])
            except Exception as ex:
                logger.error("trajectory_publish_failed", extra={
                    "event_id": traj_event["event_id"],
                    "error":    str(ex),
                })

    logger.info("batch_trajectory_complete", extra={
        "as_of":          as_of_timestamp.isoformat(),
        "trajectory_events": len(events),
    })
    return events


def _load_isolation_forest(key: str) -> Optional[dict]:
    """
    Load a trained Isolation Forest artifact from S3 and deserialize.
    Module-level cache so a warm container (or a long-running Processing
    job) pays the load cost once.
    """
    cache_attr = f"_CACHED_IFOREST_{key.replace('/', '_').replace('.', '_')}"
    cached = globals().get(cache_attr)
    if cached is not None:
        return cached
    try:
        response = s3_client.get_object(Bucket=MODEL_ARTIFACTS_BUCKET, Key=key)
        payload = joblib.load(io.BytesIO(response["Body"].read()))
    except Exception as ex:
        logger.warning("iforest_load_failed", extra={"key": key, "error": str(ex)})
        return None
    globals()[cache_attr] = payload
    return payload
```

---

## Step 8: Capture Feedback and Close the Loop

*The pseudocode calls these `on_tech_review_decision(decision_event)` and `on_recollect_result(original_event_id, recollect_result)`. Every tech-review decision (released as-is, recollected, method-suppressed) gets logged and linked back to the original flag. Every recollected specimen produces either "confirmed artifact" (the initial flag was correct, the value was not real) or "confirmed real" (the initial value was real). Confirmed-artifact events are the highest-quality training labels the pipeline produces, and they are the ones that drive rule tuning and supervised model retraining.*

The equivalent of the "missed adverse event" signal from the medication-dispensing pipeline (Recipe 3.4) shows up here as a "missed critical value" signal: a downstream incident or chart-review process identifies a clinically meaningful value that the detector did not flag. Those missed events are much rarer in lab than in medication dispensing (the critical-value layer catches most of the high-stakes cases), but they are the failure mode that matters for patient safety. Route them to the same label store so the false-negative rate per rule becomes measurable.

```python
def on_tech_review_decision(decision_event: dict) -> None:
    """
    Consumer for tech-review-decision events from the review workstation.
    Updates the outlier record with the decision, feeds override-rate
    metrics to CloudWatch, and for dispositions that imply "the flag was
    correct" (recollected, method-suppressed) writes a training-label row
    to the labels bucket for eventual rule tuning and supervised retraining.

    Expected decision_event fields:
      outlier_event_id, decision (released_as_is | recollected |
      method_suppressed | manual_verify), decision_reason, decided_at,
      deciding_tech, recollect_accession
    """
    logger.info("tech_review_decision", extra={
        "outlier_event_id": decision_event["outlier_event_id"],
        "decision":         decision_event["decision"],
    })

    _emit_metric("tech_review_decision", dimensions={
        "decision": decision_event["decision"],
    })

    # Dispositions that imply the flag was correct (a recollect or a
    # method suppression was needed) train the next iteration.
    if decision_event["decision"] in {"recollected", "method_suppressed"}:
        _write_label_to_s3({
            "outlier_event_id": decision_event["outlier_event_id"],
            "label":            "flag_actioned",
            "label_source":     "tech_review",
            "decision":         decision_event["decision"],
            "decision_reason":  decision_event.get("decision_reason"),
            "labeled_at":       decision_event["decided_at"],
            "detector_version": DETECTOR_VERSION,
        }, partition_date=decision_event["decided_at"])

    # "Released as is" dispositions are also useful: they label the flag
    # as a false positive (from the tech's perspective), which feeds the
    # override-rate monitoring for rule tuning.
    if decision_event["decision"] == "released_as_is":
        _write_label_to_s3({
            "outlier_event_id": decision_event["outlier_event_id"],
            "label":            "flag_overridden",
            "label_source":     "tech_review",
            "decision_reason":  decision_event.get("decision_reason"),
            "labeled_at":       decision_event["decided_at"],
            "detector_version": DETECTOR_VERSION,
        }, partition_date=decision_event["decided_at"])


def on_recollect_result(
    original_outlier_event_id: str,
    original_outlier: dict,
    recollect_result: dict,
) -> None:
    """
    Consumer for recollect-result events. When a recollect comes back,
    compare to the original. A clinically significant difference labels
    the original as a confirmed artifact; a non-significant difference
    labels it as confirmed real. Both are valuable.

    Expected recollect_result fields:
      loinc_code, value, resulted_at, accession
    """
    loinc = original_outlier["loinc_code"]
    analyte_meta = ANALYTE_METADATA.get(loinc, {})

    original_value = float(original_outlier["value"]) if not isinstance(
        original_outlier["value"], (int, float)
    ) else original_outlier["value"]
    recollect_value = float(recollect_result["value"])

    absolute_diff = abs(original_value - recollect_value)
    percent_diff = (
        (absolute_diff / abs(original_value) * 100.0)
        if original_value != 0 else None
    )

    # Clinically significant is analyte-specific. The delta-check thresholds
    # are a reasonable proxy: if the recollect differs from the original by
    # at least the delta-check threshold, treat the original as artifactual.
    abs_thresh = analyte_meta.get("delta_abs_threshold", 0.0)
    pct_thresh = analyte_meta.get("delta_pct_threshold", 0.0)
    clinically_significant = (
        absolute_diff >= abs_thresh
        or (percent_diff is not None and percent_diff >= pct_thresh)
    )

    label_row = {
        "original_event_id":   original_outlier_event_id,
        "loinc_code":          loinc,
        "original_value":      _to_decimal(original_value),
        "recollect_value":     _to_decimal(recollect_value),
        "absolute_difference": _to_decimal(absolute_diff),
        "percent_difference":  _to_decimal(percent_diff) if percent_diff is not None else None,
        "flags_that_fired":    original_outlier.get("flags"),
        "specimen_quality":    original_outlier.get("specimen_quality"),
        "label":               "confirmed_artifact" if clinically_significant else "confirmed_real",
        "label_source":        "recollect_outcome",
        "labeled_at":          recollect_result.get("resulted_at")
                               or datetime.now(timezone.utc).isoformat(),
        "detector_version":    DETECTOR_VERSION,
    }
    _write_label_to_s3(label_row, partition_date=label_row["labeled_at"])

    if clinically_significant:
        _emit_metric("confirmed_artifact", dimensions={"loinc": loinc})
    else:
        _emit_metric("confirmed_real", dimensions={"loinc": loinc})


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
    try:
        s3_client.put_object(
            Bucket=LABELS_BUCKET,
            Key=key,
            Body=json.dumps(_decimal_to_float(label_row), default=str).encode("utf-8"),
            ContentType="application/json",
            ServerSideEncryption="aws:kms",
        )
    except Exception as ex:
        logger.error("label_write_failed", extra={
            "error": str(ex),
        })
```

---

## The Full Real-Time Pipeline

Here is the end-to-end `score_one_result` function that wires Steps 1 through 6 together. In production this is the body of the `real-time-outlier-service` Lambda triggered by Kinesis records; the Python version collapses it into a single driver for teaching.

```python
def score_one_result(raw_result: dict) -> Optional[dict]:
    """
    End-to-end real-time scoring for a single lab result. In production
    this runs inside a Lambda triggered by Kinesis records; here it is a
    plain function so you can step through it in a notebook.

    Returns the outlier event if any flags fired, None otherwise.
    """
    # --- Step 1: normalize ---
    canonical = normalize_result(raw_result)
    if canonical is None:
        return None

    # --- Step 2: enrich with patient context and recent history ---
    enriched = enrich_with_patient_context(canonical)
    if enriched is None:
        return None

    # --- Step 3: rule screen ---
    rule_flags = rule_screen(enriched)

    # --- Step 4: delta check and patient-history robust z-score ---
    patient_flags = patient_baseline_checks(enriched)

    # --- Step 5: cohort z-score ---
    cohort_flags = cohort_zscore_check(enriched)

    all_flags = rule_flags + patient_flags + cohort_flags

    # --- Step 6: aggregate and route ---
    return route_result(enriched, all_flags)


# --- Example usage ---
#
# Minimal end-to-end example that exercises the real-time path with a
# synthetic critical potassium result (the recipe's opening scenario).
# The patient context and reference ranges are stubbed in-process; in a
# real run these come from DynamoDB, populated by the EHR and lab feeds.
if __name__ == "__main__":
    # Seed a synthetic patient into the context cache for the example.
    # In a real deployment, the ADT feed and the lab and medication feeds
    # populate the cache; you do not stub it here.
    try:
        dynamodb.Table(PATIENT_CONTEXT_TABLE).put_item(Item={
            "patient_id":          "PT-EXAMPLE-0044221",
            "age_years":           _to_decimal(74),
            "sex":                 "M",
            "pregnancy_status":    None,
            "acuity":              "ward",
            "unit":                "medsurg_2east",
            "is_on_dialysis":      False,
            "active_problems":     ["J18.9", "I10"],
            "active_medications":  [],
            "recent_results": {
                "2823-3": [
                    {"value": _to_decimal(4.2), "resulted_at": "2026-05-11T06:15:00Z"},
                    {"value": _to_decimal(4.0), "resulted_at": "2026-05-10T06:20:00Z"},
                    {"value": _to_decimal(4.3), "resulted_at": "2026-05-09T06:10:00Z"},
                    {"value": _to_decimal(4.1), "resulted_at": "2026-05-08T06:30:00Z"},
                    {"value": _to_decimal(4.4), "resulted_at": "2026-05-07T06:25:00Z"},
                    {"value": _to_decimal(4.2), "resulted_at": "2026-05-06T06:15:00Z"},
                ],
            },
        })
    except Exception as ex:
        print(f"[setup] Could not seed patient cache (ok if table not present): {ex}")

    # The textbook pseudohyperkalemia scenario: a serum potassium of 7.8
    # from a hemolyzed specimen drawn peripherally with a long transport
    # delay. The pipeline fires the critical-value callback AND a
    # specimen-quality hold that tells the tech this is likely artifact.
    raw_event = {
        "source_event_id":         "LIS-ORU-771244",
        "source":                  "lis",
        "analyzer":                "roche-cobas-8000",
        "method":                  "ISE_indirect",
        "timestamp":               "2026-05-12T06:42:11Z",
        "patient_id":              "PT-EXAMPLE-0044221",
        "patient_age_years":       74,
        "patient_sex":             "M",
        "loinc_code":              "2823-3",
        "value":                   7.8,
        "unit":                    "mEq/L",
        "hemolysis_index":         4,
        "icterus_index":           1,
        "lipemia_index":           1,
        "clot_detected":           False,
        "qns_flag":                False,
        "short_sample":            False,
        "collection_site":         "peripheral",
        "transport_delay_minutes": 92,
        "collected_at":            "2026-05-12T05:15:00Z",
        "resulted_at":             "2026-05-12T06:42:11Z",
        "accession":               "CHEM-2026-128821",
    }

    print("[1/1] Scoring synthetic potassium result with hemolysis 4+...")
    result = score_one_result(raw_event)
    print()
    if result is None:
        print("No flags fired.")
    else:
        print("=== OUTLIER EVENT ===")
        print(json.dumps(_decimal_to_float(result), indent=2, default=str))
```

Running this against a fresh DynamoDB context cache with the synthetic patient produces a critical-callback routing decision (potassium 7.8 crosses the 6.5 high threshold), a specimen-quality-invalidating flag (hemolysis index 4 at or above the gate of 3 for potassium), a delta-check flag (potassium shifted from 4.2 to 7.8 in about 24.5 hours, well past the 1.0 mEq/L absolute and 25% percentage thresholds), and a patient-history z-score flag (the patient's history sits tightly around 4.2, so 7.8 is many MAD-scaled units away). Exactly the pattern the main recipe opens with, and exactly the clinical disposition the lab tech needs: the callback fires (CLIA-required), the callback payload carries the hemolysis context so the clinical team can pause before treating, and the tech-review hold captures the artifact signal for recollection.

The cohort z-score path stays silent because there is no Feature Store baseline populated; the panel and trajectory paths do not run at all on the real-time path. After a few days of accumulated history and populated baselines, all the statistical paths activate.

A realistic dev-loop pattern is to seed a few weeks of synthetic lab history with Synthea, seed the Feature Store baselines from that history, and only then turn the pipeline loose. The example above is intentionally minimal so the rule-fire shape stays visible without the surrounding machinery.

---

## Gap to Production

Several things would need to change before you would deploy any of this.

**Real HL7 v2 and FHIR parsing.** The example starts from a dict that looks like a parsed result. In production, the result-normalizer Lambda invokes a maintained parsing library (HAPI FHIR via a Java runtime, or `fhir.resources` plus `python-hl7` on Python) to convert ORU_R01 messages, MSH/PID/OBR/OBX segments, and FHIR Observation or DiagnosticReport resources into the canonical shape. HL7 v2 oddities (unterminated segments, embedded delimiters, vendor-specific Z-segments, time zones in timestamps, preliminary-then-final-then-corrected flows) are the ones that bite. Budget weeks for this integration, not days, especially for the corrected-result flow that has to retract prior flags cleanly.

**Real LIS middleware and specimen-quality capture.** Specimen quality indices (hemolysis, icterus, lipemia) travel with the result from the analyzer through the middleware to the LIS. Each middleware product emits them in a slightly different format; some LIS implementations strip them on the way to the EHR. Validate on every analyzer that every reportable result carries the expected quality fields, and alarm if a field stops arriving (a firmware upgrade on the analyzer can silently break the feed).

**Reference-range library with versioning.** The example uses an in-process fallback plus a DynamoDB lookup. In production, reference ranges are versioned (a range change requires validation and lab director sign-off) and every range application on a historical result has to be reproducible against the range that was in force at the time, not the current range. A good implementation stores ranges with effective-date windows and queries "the range in effect at resulted_at" rather than "the current range." Getting this wrong invalidates audit trails.

**Patient-context cache freshness.** The example seeds a single patient row directly. In production, a separate Lambda (or a Kinesis consumer) processes ADT, ORU (lab), RDE (med list), problem-list, allergy, and pregnancy-status feed events and keeps the `patient-context-cache` table current. Each cached field carries an observed_at timestamp; downstream logic uses that timestamp to decide whether to apply the field. A stale pregnancy flag that never updates to "not pregnant" after delivery will flood the chart with false positives when the ranges snap back; a stale dialysis flag will overhold chronic-kidney-disease patients' creatinine results forever. Design the refresh pipeline carefully, audit it continuously, and alarm on stale-field rates.

**Recent-history caching strategy.** The example stores recent results inline on the patient-context item. That works for a few analytes and a short window, but it does not scale to a full recent-history store. Production architectures usually split this: a separate DynamoDB table (or a DAX-cached view, or a Redis ElastiCache layer) for recent results per analyte per patient, keyed on (patient_id, loinc_code) with a TTL-driven window. Fall-through to a bounded LIS query when the cache misses, with rate-limiting so a cache-outage does not stampede the LIS.

**Enterprise patient ID resolution.** The example accepts whatever `patient_id` the raw event provides. In production, an enterprise master patient index resolves MRNs across source systems into a canonical enterprise ID. Recipe 5.x (Entity Resolution) covers the pattern; plug the resolver in at the top of `normalize_result` and never let unresolved MRNs through.

**Feature Store baseline population.** The example assumes the `analyte-cohort-baselines` feature group exists with records keyed by analyte + profile bucket. In production, a scheduled SageMaker Processing job reads several months of historical result data from S3, computes the median and MAD per analyte-profile bucket, and writes records to the online feature store for the real-time path plus the offline store for retraining. Refresh monthly; keep old baselines as versioned history so alert tuning can be audited. Refuse to auto-update a baseline when the underlying method changes (method changes require a validation step, not a silent recompute).

**OpenSearch integration and authentication.** The `_index_outlier_event` and `_index_dispense_audit` functions are placeholders. In production, use AWS4Auth-signed HTTPS requests against the OpenSearch domain with fine-grained access control that separates laboratory leadership, pathology, compliance, and IT security into different roles. The index template needs alias management, retention lifecycle policies, and the detector-version field as a keyword for clean aggregation.

**CLIA-compliant critical-value callback workflow.** The example publishes a critical value to an SNS topic and returns. A real callback is a state machine: dispatch the page, await acknowledgment from the ordering provider, capture read-back of the value, escalate to a covering provider when the primary target does not acknowledge within a defined time, fall back to a lab-supervisor-dispatched phone call when automated channels fail, and close the callback with documented timestamps and recipient identity. Callback timing is measured and reported against the CLIA and state-licensure windows; every step of the workflow is audit-logged and retained for the regulatory minimum. This is its own service; this example marks where it plugs in.

**Autoverification release integration.** The `_autoverify_release` placeholder does not actually release to the LIS or the EHR. In production, the release Lambda publishes back to the LIS bridge as an HL7 ORU message (or FHIR Observation update) with the chart flag attached, handles the LIS acknowledgment, and retries with idempotency keys on transient failures. Tech-review-hold and recollect-requested paths require the complementary "do not release" semantics in the LIS; that integration is LIS-vendor-specific.

**Idempotency.** Kinesis delivers at-least-once. EventBridge delivers at-least-once. The real-time Lambda may process the same result twice, and the feedback-capture Lambda may receive the same tech-review-decision event twice. Use conditional writes (`ConditionExpression`) on every DynamoDB put or update, handle `ConditionalCheckFailedException` as "already processed," and make S3 label writes idempotent by deriving the key deterministically from the event ID.

**Corrections and retractions.** Lab results change: a preliminary result is corrected after a manual review; a culture result is updated with final sensitivities; an autoverified result is retracted after a pathologist review finds the method was miscalibrated. The pipeline has to handle corrections cleanly: fire a "correction" outlier event that links to the original, retract prior flags if they are no longer applicable, and (critically) retract a prior critical-value callback if the corrected value is no longer critical. Missing this produces two kinds of incidents: phantom critical values that were never real, and critical values that were retracted but never followed up.

**Method-change awareness.** Analyzer method changes, reagent lot changes, and calibration events shift analyte distributions. The pipeline needs a method-change registry: when a method change occurs, delta checks across the method boundary are suppressed for a configurable window (days to weeks), cohort baselines are re-validated before being used, and the reference range in force may update. This data lives in the QC program rather than the rule library; integrating the two is nontrivial.

**Error handling.** The example has minimal error handling. In production, wrap every external call in try/except with structured logging, emit a failure metric, and route affected events to a dead-letter queue. Distinguish patient-context-missing (data quality) from patient-context-timeout (infrastructure) because the correct response is different: the first routes to a human review queue; the second retries with backoff, then falls back to a degraded-mode scoring path that runs only the rules that do not depend on patient-specific context.

**Graceful degradation.** The lab does not stop running results because AWS has an issue. Design the pipeline's failure modes explicitly: if the patient-context cache is unavailable, fall back to rules-only (critical values, reference range, specimen quality) and log the gap. If the Feature Store is unavailable, skip the cohort z-score path silently. If EventBridge is unavailable, drop the event into an S3 "pending" prefix that a replay worker picks up once the bus recovers. Document, drill, and test these paths; they will be exercised under real operational stress.

**Structured logging with PHI discipline.** The `logger.info` calls above log structural metadata only. In production, use a JSON log formatter, ship logs to CloudWatch Logs with a log group encrypted by a customer-managed KMS key, and audit log content for unexpected PHI patterns (patient IDs tied to values, full context snapshots, full recent-results arrays). A single `logger.info("enriched: %s", enriched)` during debugging creates a PHI disclosure that survives in CloudWatch until retention clears it.

**IAM scoping.** Production roles are scoped tightly. The result-normalizer Lambda's role needs no SNS permissions. The real-time-outlier-service Lambda's role needs no label-write permissions. The feedback-capture Lambda's role needs no EventBridge-bus write permissions beyond the specific detail-type it produces. Scope to specific resource ARNs and review roles annually. No wildcards in production.

**VPC deployment.** In production, all Lambdas and SageMaker Processing jobs run inside a VPC with VPC endpoints for DynamoDB, S3, Kinesis, SageMaker Runtime, Feature Store Runtime, EventBridge, KMS, CloudWatch Logs, and OpenSearch. SNS is a managed edge service and does not run in a VPC; keep SNS messages narrow (event ID and minimal routing) so PHI does not flow through the notification channel.

**KMS customer-managed keys.** All data at rest (DynamoDB tables, S3 buckets, Kinesis streams, Feature Store online and offline stores, OpenSearch domain, CloudWatch Logs) is encrypted with customer-managed KMS keys. Key policies restrict usage to the specific roles that need it. Audit via CloudTrail data events on every PHI-bearing resource.

**SageMaker wrapping for the batch paths.** The `panel_multivariate_check` and `run_batch_trajectory_scoring` functions run in-process for teaching. In production, wrap the same math in SageMaker Processing jobs with the result archive S3 bucket as the input channel and the EventBridge publish step as the final stage of the container script. Schedule the jobs via EventBridge Scheduler on the cadence appropriate to each clinical setting (every 15 minutes for ICU analytes, hourly for ward, daily for ambulatory). Model version tagging lives in the SageMaker Model Registry.

**Isolation Forest training pipeline.** The `_load_isolation_forest` helper assumes a pre-trained artifact. Producing that artifact is a separate SageMaker Training Job that reads historical panel-level feature vectors from the Feature Store offline store, fits the model, registers it in the Model Registry, and after a human approval step copies the artifact to `s3://MODEL_ARTIFACTS_BUCKET/current/panel_isolation_forest.joblib`. Retrain quarterly; sample the current-model flag distribution on a rolling basis to detect drift before it harms alert quality.

**CLIA autoverification validation.** Autoverification algorithms require documented validation per CLSI AUTO10 before production deployment, and substantive algorithm changes trigger revalidation. CAP and other accreditation bodies inspect this during surveys. The validation workflow is a lab-quality program, not a code deliverable; engineering supports it but does not own it. Build the infrastructure that lets the lab director's team define, validate, version, and deploy rules; do not write rules unilaterally.

**Alert-fatigue monitoring.** Every flag type has a rolling override-rate metric: if the rate on a rule exceeds a configured threshold, an alert goes to the laboratory director and clinical leadership for review and possible retirement or re-thresholding. Without this loop, rules accumulate and alert volume slowly climbs back to "everyone overrides everything" within six months of deployment. Autoverification rate, critical-callback timeliness, delta-check override rate, and tech-review queue depth are the core monitoring metrics; dashboards and alarms on each are part of the minimum deployment.

**Subgroup and fairness monitoring.** Reference ranges derived from historical populations can encode bias (the creatinine-GFR race coefficient discussion being the canonical example). Cohort z-scores can flag legitimately-different values for populations underrepresented in the training data. Build subgroup dashboards (by patient race, ethnicity, language, insurance status) from day one, with thresholds that escalate to the health-equity team when a subgroup's flag or override rate diverges significantly from the overall population. Reference range validation should include representative population sampling. These are ongoing concerns, not check-the-box items.

**POCT integration path.** Point-of-care test results flow through a POCT data manager rather than the central-lab LIS. They have different quality control architecture, different reference ranges, and are operated by nurses or respiratory therapists rather than trained techs. A pipeline that treats POCT data the same as central-lab data will miss POCT-specific artifact patterns (bedside glucose drawn from a hand with D50W on it, iSTAT cartridge out of temperature spec). Build a POCT-aware variant of the normalizer and the rule set; share the downstream routing infrastructure.

**Retention and legal hold.** Lab records have CLIA (2 years minimum for most records), state-board, and accreditation retention requirements that often exceed the HIPAA 6-year baseline. Blood bank records typically have 10+ year retention; pathology reports often 20+ years. Apply S3 Object Lock in COMPLIANCE mode for the labels and audit buckets in production. GOVERNANCE mode is fine for dev/test so cleanup stays possible. Confirm retention schedules with legal and compliance before any production deployment.

**Testing.** A real codebase has unit tests for every derivation function (unit conversion, age-band bucketing, staleness checks, MAD calculation, severity-tier escalation, routing decisions), integration tests against DynamoDB Local and moto mocks for DynamoDB, Feature Store, and EventBridge, and golden-path regression tests that run on every rule-library update so a subtle rule change that silently suppresses critical-callback flags is caught before deployment. The `rule_screen`, `_max_severity`, and `_severity_to_routing` functions in particular benefit from table-driven tests because their rules evolve with clinical governance decisions.

**Clinical governance.** Severity-tier thresholds, rule library, suppression rules, override-rate targets, autoverification rate targets, callback protocols: all are clinical and operational decisions owned by the laboratory director and clinical leadership in conjunction with pathology, not by the engineering team. Wire the governance in: rule changes require lab director review, reference-range updates require validation, severity reclassifications require re-approval, new detectors require a pilot-then-general-availability rollout. The engineering pipeline supports the governance; it does not replace it.

None of this is unique to lab-result outlier detection. It is the cost of running any CLIA-adjacent patient-safety service in production. The good news: once you have the patient-context cache, the EventBridge fan-out, the feedback capture, and the SageMaker training machinery in place for one clinical monitoring recipe (medication dispensing, lab outliers, deterioration early warning, or EHR access anomalies), the same infrastructure supports all of them. Recipe 3.4 (Medication Dispensing Anomalies) shares nearly the entire architectural footprint; so do Recipes 3.7 and 3.9.

---

*← [Main Recipe 3.5](chapter03.05-lab-result-outlier-detection) · [Chapter 3 Preface](chapter03-preface)*
