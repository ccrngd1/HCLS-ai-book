# Recipe 3.10: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 3.10. It shows one way you could translate the epidemic / outbreak detection pattern into working Python using Amazon Kinesis (for the canonical surveillance-event stream), Amazon DynamoDB (for the cell-state, cluster-state, address-geocode-cache, and suppression-rule stores), Amazon Aurora PostgreSQL with PostGIS (for geographic reference data and point-in-polygon assignment; here represented by a tiny in-process Shapely lookup so the demo runs without a database), Amazon Timestream (for per-cell time-series counts; here represented by a small in-memory store), Amazon Comprehend Medical (for free-text chief-complaint NLP), Amazon SageMaker (for the syndrome-classifier endpoint and the regression-detector processing job), Amazon Bedrock (for cluster-narrative generation), Amazon EventBridge (for cluster fan-out), Amazon OpenSearch Service (for the line-list search and cluster index), Amazon S3 (for the raw-event lake, baseline store, and training labels), Amazon Location Service (for address geocoding), and Amazon CloudWatch (for operational metrics). It is not production-ready. There is no real EHR audit-feed connector, no HL7 v2 ADT or ORU parser, no FHIR Encounter or Observation ingestion, no NWSS wastewater feed integration, no eCR / NEDSS / NHSN / NORS / NMI reporting connector, no SaTScan invocation (the spatial-scan detector is sketched as a stub), no real PostGIS database, and no surveillance-team UI integration (Protenus, Maven, Trisano, ESSENCE through NSSP, or a custom AppSync front end). Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you would wire into a state public health surveillance program next week.
>
> The code maps to the nine core pseudocode steps from the main recipe: ingest a clinical encounter and produce a canonical event, geocode the encounter and assign it to multi-resolution geographies, classify the encounter into syndromic categories using NLP plus structured-data rules, update per-cell counters across the geography x demographic x syndrome x time grid, compute baseline expected counts per cell with seasonality and trend, run the detector bank (control charts, regression-based aberration, spatial scan), run auxiliary-source detectors and fuse signals, build cluster candidates with line lists and Bedrock narratives, and capture investigation outcomes for the retraining loop. The wastewater integration, the genomic-cluster detector, the wearable-aggregate signal path, and the LLM-assisted investigator copilot variant are not in this file; they are covered in the Variations and Why-This-Isn't-Production-Ready sections of the main recipe and share infrastructure with several other chapter recipes (3.6 for case-management patterns, 3.7 for calibration and tier mapping, 3.8 for engagement-decay and outcome-capture patterns, 3.9 for cluster-builder and Bedrock-narrative patterns, 12.x for time-series forecasting, 13.x for knowledge-graph foundations).

---

## Setup

You will need the AWS SDK for Python plus scikit-learn, pandas, numpy, statsmodels, and Shapely for the local demonstration:

```bash
pip install boto3 scikit-learn pandas numpy statsmodels shapely
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query` on the `cell-state`, `cluster-state`, `address-geocode-cache`, and `suppression-rules` tables
- `kinesis:PutRecord`, `kinesis:PutRecords`, `kinesis:GetRecords`, `kinesis:GetShardIterator` on the `surveillance-events` stream
- `timestream:WriteRecords` on the `surveillance` database, `timestream:Select` on the `cell_time_series` table
- `s3:GetObject` on the model-artifacts and baseline-store buckets; `s3:PutObject` on the raw-events lake, baseline store, and training-labels buckets
- `comprehendmedical:DetectEntitiesV2` for chief-complaint NLP (no resource ARN; service-level)
- `sagemaker-runtime:InvokeEndpoint` on the syndrome-classifier endpoint ARN
- `sagemaker:CreateProcessingJob` on the Farrington-Flexible processing-job definition (when wired to SageMaker Processing)
- `bedrock:InvokeModel` on the specific Bedrock model ARN you use (scope tightly; do not use `bedrock:*`)
- `events:PutEvents` on the `surveillance-events` bus
- `cloudwatch:PutMetricData` for operational metrics
- `geo:SearchPlaceIndexForText` on the Amazon Location Service place index ARN
- The OpenSearch domain policy must allow the executing role to `es:ESHttpPost` and `es:ESHttpPut` on the `cluster-index`, `line-list-search`, and `detector-results` indices

Scope each role to the specific resource ARNs it touches. The permissions above are fine for learning and will fail any serious IAM review. In production, each component (encounter-ingest Lambda, lab-ingest Lambda, wastewater-ingest Lambda, pharmacy-ingest Lambda, absenteeism-ingest Lambda, eCR-ingest Lambda, event-normalizer Lambda, geocoding Lambda, syndrome-classifier Lambda, baseline-computer Lambda, control-chart-detector Lambda, SaTScan-runner AWS Batch job, regression-detector SageMaker Processing job, multi-source-fusion Lambda, cluster-aggregator Lambda, cluster-builder Lambda, outcome-capture Lambda, retraining Step Functions workflow) gets its own role with the minimum permissions for its job. Surveillance is one of the more sensitive PHI-handling pipelines you'll build (it touches encounter detail across the entire population of a state), and the IAM model has to reflect that.

A few things worth knowing upfront:

- **No real HL7 v2 or FHIR ingestion.** Production parses HL7 v2 ADT and ORU messages from EDs, urgent care, and hospital labs (typically routed through a state-aggregator like the state public health department's HIE), and FHIR Encounter and Observation resources from facilities with modern integrations. Each source has its own latency, schema, and completeness characteristics. Use a maintained library (`hl7apy` or `python-hl7` for HL7 v2; `fhir.resources` for FHIR) and a real integration engine (Mirth, Rhapsody, Cloverleaf, or a vendor-supplied platform) rather than hand-rolling parsers. Plan 3-9 months of integration work per source class. The teaching example accepts a pre-shaped event dict.
- **No real NWSS wastewater feed.** Production pulls SARS-CoV-2, polio, influenza, and mpox concentrations from CDC NWSS plus direct-source feeds from sample-processing labs. Each lab and each pathogen has its own quality-control conventions, normalization conventions (against PMMoV, against population estimates, against sewershed flow rates), and reporting cadence. The teaching example pre-loads tiny synthetic concentration records.
- **No real eCR / NEDSS / NHSN / NORS / NMI integration.** Production wires bidirectional integrations with the federal and state surveillance infrastructure: eCR through the AIMS platform, NEDSS through NBS or a commercial product (Maven, Trisano), NHSN for HAI surveillance, NORS for waterborne and foodborne outbreaks, NMI for nationally notifiable conditions. Each has its own protocol, data format, and reporting cadence. The teaching example writes cluster records to DynamoDB and OpenSearch and stops.
- **No real Aurora PostGIS database.** Production hosts the geography hierarchy (census tracts, ZCTAs, counties, school districts, sewersheds, hospital service areas) in Aurora PostgreSQL with PostGIS, with continuous updates from TIGER/Line refreshes and operational geography sources. The teaching example uses an in-process Shapely lookup against a tiny synthetic geography to make point-in-polygon assignment runnable without a database. The `query_postgis_for_admin_geographies` function shows the production-shape SQL call you would use.
- **No real Timestream cell time-series.** Production stores per-cell daily counts in Amazon Timestream with multi-year retention. The teaching example uses an in-memory dict so the baseline computation runs without a Timestream database. The `query_timestream_for_history` function shows the production-shape Timestream query.
- **No real SaTScan invocation.** Production runs SaTScan as a containerized AWS Batch job (the SaTScan binary is a compiled tool from Martin Kulldorff's group at Harvard / Information Management Services). The teaching example provides a tiny scan-statistic stub that flags clusters above a synthetic threshold; real SaTScan integration involves staging input files, invoking the binary, and parsing output files. Use SaTScan in production; do not use the demo stub.
- **All numeric values must be Decimal going into DynamoDB.** DynamoDB rejects Python `float` for numeric attributes. A baseline expected count of `4.7` becomes `Decimal("4.7")` on the way in and back to float on the way out. The helper functions below handle this so you see the pattern. For an outbreak-detection pipeline this matters operationally: a baseline upper-99 of `5.9999999999` from float drift, compared against an observed count of `6` for a tier-1 cut, produces inconsistent flagging today and might produce different results tomorrow if the threshold moves. The kind of bug that the surveillance team will track down for two days during their next rounding-mismatch crisis.
- **All example facility, patient, and encounter data is synthetic.** Patient identifiers, facility identifiers, ZIP codes, census tracts, sewersheds, school districts, addresses, and chief-complaint text in the sample data are illustrative and do not refer to any real people, providers, or facilities. Never use real PHI in a teaching example.
- **The model in this example is a tiny in-process scikit-learn model.** Real deployments host the syndrome classifier behind a SageMaker real-time endpoint plus the regression-based detector as a SageMaker Processing job (daily cadence). We train a logistic regression on a small synthetic feature matrix at the bottom of the file so the scoring path runs end-to-end without a deployed endpoint. The `score_via_sagemaker_endpoint` function shows the production-shape boto3 call.
- **Public health authority is not simulated here.** The main recipe spends a lot of time on the explicit legal authority the surveillance program operates under (state public health statutes, institutional privacy authority, intergovernmental agreements). The example code generates cluster candidates without checking authority because the authority is established outside the technology layer. In production, the surveillance program must operate under a documented and current legal authority before the technology runs against PHI; coordinate with the state public health legal team before deployment.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here: thresholds, syndrome taxonomy, geography hierarchy, baseline-window sizes, resource names, and routing tables. These are the knobs that move most often between dev, test, and production, and between surveillance-team threshold reviews. Keep them at the top of the file so a reviewer can see the levers without wading through function bodies.

```python
import io
import json
import logging
import math
import uuid
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
from typing import Optional

import boto3
import numpy as np
import pandas as pd
from botocore.config import Config
from boto3.dynamodb.conditions import Key, Attr
from shapely.geometry import Point, Polygon
from sklearn.linear_model import LogisticRegression
from sklearn.isotonic import IsotonicRegression

# Structured logging. Ship JSON records to CloudWatch Logs Insights.
# Encounter payloads, chief-complaint text, line lists, lab results,
# and Bedrock prompts contain PHI. Log structural metadata only. Never
# log full encounter payloads with patient identifiers, full chief-
# complaint text, full line lists, or Bedrock prompts in application
# logs. The line-list search index (OpenSearch) and the cluster-state
# store (DynamoDB) are the right home for full payloads, behind KMS
# and CloudTrail data events.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling across DynamoDB, Timestream, Kinesis,
# Comprehend Medical, SageMaker, and Bedrock with exponential backoff
# and jitter. Encounter ingest is bursty (EDs flush large batches at
# top-of-hour boundaries; lab results spike during morning rounds), and
# adaptive mode keeps burst windows from cascading into retry storms
# against Comprehend Medical and the syndrome classifier endpoint.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

REGION = "us-east-1"
dynamodb = boto3.resource("dynamodb", region_name=REGION, config=BOTO3_RETRY_CONFIG)
kinesis = boto3.client("kinesis", region_name=REGION, config=BOTO3_RETRY_CONFIG)
timestream_write = boto3.client("timestream-write", region_name=REGION, config=BOTO3_RETRY_CONFIG)
timestream_query = boto3.client("timestream-query", region_name=REGION, config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", region_name=REGION, config=BOTO3_RETRY_CONFIG)
cloudwatch = boto3.client("cloudwatch", region_name=REGION, config=BOTO3_RETRY_CONFIG)
eventbridge = boto3.client("events", region_name=REGION, config=BOTO3_RETRY_CONFIG)
comprehend_medical = boto3.client(
    "comprehendmedical", region_name=REGION, config=BOTO3_RETRY_CONFIG
)
sagemaker_runtime = boto3.client("sagemaker-runtime", region_name=REGION, config=BOTO3_RETRY_CONFIG)
bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION, config=BOTO3_RETRY_CONFIG)
location = boto3.client("location", region_name=REGION, config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill in with your actual resource names. These are placeholders.
CELL_STATE_TABLE             = "cell-state"
CLUSTER_STATE_TABLE          = "cluster-state"
GEOCODE_CACHE_TABLE          = "address-geocode-cache"
SUPPRESSION_RULES_TABLE      = "suppression-rules"

SURVEILLANCE_EVENTS_STREAM   = "surveillance-events"
TIMESTREAM_DATABASE          = "surveillance"
TIMESTREAM_CELL_TABLE        = "cell_time_series"

RAW_EVENTS_BUCKET            = "my-surveillance-raw-events"
BASELINE_STORE_BUCKET        = "my-surveillance-baseline-store"
TRAINING_LABELS_BUCKET       = "my-surveillance-training-labels"

CLUSTER_BUS                  = "surveillance-events"
SYNDROME_CLASSIFIER_ENDPOINT = "syndrome-classifier-v3"
BEDROCK_MODEL_ID             = "anthropic.claude-3-sonnet-20240229-v1:0"
LOCATION_PLACE_INDEX         = "surveillance-place-index"

# --- Syndromic Categories ---
# NSSP's standard syndromic categories form the baseline taxonomy.
# Production loads the full taxonomy from a versioned reference table
# the surveillance team owns. The teaching example uses a small subset.
SYNDROMIC_CATEGORIES = {
    "fever_respiratory",   # fever + cough or shortness of breath
    "ili",                 # influenza-like illness (fever + cough/sore throat)
    "gi",                  # gastrointestinal: vomiting, diarrhea, abdominal pain
    "rash",                # rash with or without fever
    "neuro",               # altered mental status, seizure, meningitis-like
    "sepsis",              # sepsis indicators
    "asthma_copd",         # asthma / COPD exacerbation
}

# ICD-10 to syndrome mapping (small subset). Production uses NSSP's
# official chief-complaint-and-discharge-diagnosis (CCDD) syndrome
# definitions plus organization-specific extensions. The CCDD library
# is regularly updated; mirror it in a versioned reference table.
ICD_TO_SYNDROME_RULES = [
    {"pattern": r"^J0[6-9]",           "syndrome": "fever_respiratory"},  # acute upper respiratory
    {"pattern": r"^J1[0-8]",           "syndrome": "ili"},                # influenza, pneumonia
    {"pattern": r"^J2[0-2]",           "syndrome": "fever_respiratory"},  # bronchitis, bronchiolitis
    {"pattern": r"^J45",               "syndrome": "asthma_copd"},        # asthma
    {"pattern": r"^J44",               "syndrome": "asthma_copd"},        # COPD
    {"pattern": r"^A0[0-9]",           "syndrome": "gi"},                  # cholera, salmonella
    {"pattern": r"^A09",               "syndrome": "gi"},                  # gastroenteritis
    {"pattern": r"^K5[0-2]",           "syndrome": "gi"},                  # IBD, gastritis
    {"pattern": r"^B0[0-9]",           "syndrome": "rash"},                # viral exanthems
    {"pattern": r"^L5[0-9]",           "syndrome": "rash"},                # urticaria, dermatitis
    {"pattern": r"^G0[0-3]",           "syndrome": "neuro"},               # meningitis
    {"pattern": r"^R56",               "syndrome": "neuro"},               # convulsions
    {"pattern": r"^A41",               "syndrome": "sepsis"},              # septicemia
    {"pattern": r"^R65",               "syndrome": "sepsis"},              # SIRS / sepsis
]

# Comprehend-Medical-detected entity to syndrome mapping. Production
# uses a richer ontology mapping (UMLS-codes-to-syndrome) plus a
# trained classifier; the teaching example uses keyword-matching on
# the entity text.
ENTITY_TO_SYNDROME_RULES = [
    {"keywords": ["cough", "shortness of breath", "wheezing"], "syndrome": "fever_respiratory"},
    {"keywords": ["influenza", "flu", "ili"],                    "syndrome": "ili"},
    {"keywords": ["fever"],                                       "syndrome": "fever_respiratory"},
    {"keywords": ["vomiting", "diarrhea", "abdominal pain"],     "syndrome": "gi"},
    {"keywords": ["rash"],                                        "syndrome": "rash"},
    {"keywords": ["seizure", "altered mental status", "confusion"], "syndrome": "neuro"},
    {"keywords": ["sepsis", "septic shock"],                      "syndrome": "sepsis"},
    {"keywords": ["asthma", "copd", "wheezing"],                 "syndrome": "asthma_copd"},
]

# Lab-positive pathogen to syndrome promotion. A positive flu PCR
# promotes the encounter to ILI. A positive Salmonella culture promotes
# to GI. Production uses LOINC plus organism-specific maps; the demo
# uses a small dict.
PATHOGEN_TO_SYNDROME_RULES = [
    {"pathogens": ["influenza_a", "influenza_b"],                  "syndrome": "ili"},
    {"pathogens": ["sars_cov_2"],                                   "syndrome": "fever_respiratory"},
    {"pathogens": ["rsv"],                                          "syndrome": "fever_respiratory"},
    {"pathogens": ["salmonella", "shigella", "campylobacter"],     "syndrome": "gi"},
    {"pathogens": ["norovirus"],                                    "syndrome": "gi"},
    {"pathogens": ["measles", "rubella", "varicella"],             "syndrome": "rash"},
    {"pathogens": ["neisseria_meningitidis"],                       "syndrome": "neuro"},
]

SYNDROME_CONFIDENCE_THRESHOLD = 0.65

# --- Detector Thresholds ---
# Tunable per cohort and per syndrome in production. Loaded from a
# versioned governance-approved table so the surveillance team can
# update without a code deploy.
CUSUM_REFERENCE_K        = 0.5     # reference value: half a SD shift
CUSUM_DECISION_H         = 4.0     # decision interval: ~4 SD cumulative
EWMA_LAMBDA              = 0.4     # smoothing factor
EWMA_CONTROL_LIMIT       = 3.0     # in standard deviations
SCAN_PVALUE_THRESHOLD    = 0.01    # spatiotemporal scan significance
CROSS_SYNDROME_THRESHOLD = 0.7

WW_ANOMALY_THRESHOLD       = 2.0    # standardized anomaly score
RX_SPIKE_THRESHOLD         = 2.5
ABSENTEEISM_THRESHOLD      = 2.0

# Multi-source fusion weights. Concordance-bonus rewards multiple
# sources moving together. Calibrated separately per syndrome class
# in production.
FUSION_WEIGHTS = {
    "clinical":    0.50,
    "wastewater":  0.20,
    "pharmacy":    0.15,
    "absenteeism": 0.15,
}
CONCORDANCE_SIGNAL_THRESHOLD = 0.5
CONCORDANCE_BONUS_PER_SOURCE = 0.05

# --- Tier Thresholds ---
# Tier-1 clusters get same-day surveillance team review. Tier-2 within
# 24 hours. Tier-3 next business day. Tunable per syndrome class in
# production.
TIER_THRESHOLDS = {
    "DEFAULT": {"tier_1": 0.85, "tier_2": 0.65, "tier_3": 0.45},
}

# --- Window Sizes ---
BASELINE_LOOKBACK_YEARS    = 5
MIN_HISTORY_DAYS           = 365
MIN_HISTORY_COUNT          = 100
CLUSTER_TEMPORAL_WINDOW    = 14   # days; group flagged cells within this
DISMISSAL_VALIDITY_PERIOD_DAYS = 21

# --- Aggregation Windows ---
# Multiple windows in parallel catch outbreaks at different temporal
# scales. Daily for fast-moving, 7-day for smoothing, 14-day and 28-day
# for slower-burn detection.
AGGREGATION_WINDOW_DAYS = [1, 7, 14, 28]
```

A quick note on the thresholds block. The values above are defaults chosen to make the teaching example produce a sensible mix of tier-1, tier-2, and tier-3 clusters on a small synthetic dataset. A real deployment tunes them against a labeled backtest of historical outbreak adjudications, then validates them prospectively in shadow mode for several seasons before any cluster routes to a surveillance epidemiologist. The right cuts depend on the jurisdiction's confirmed-outbreak base rate, the surveillance team's daily review capacity, the alert-fatigue budget, and the joint clinical-and-public-health governance committee's risk tolerance. These are dials, not physical constants, and the surveillance program owns them.

---

## Step 1: Ingest a Clinical Encounter and Produce a Canonical Event

Source feeds arrive in vendor-specific formats. The ingester translates each into a canonical surveillance event with consistent fields and identifier semantics. Every downstream component consumes the canonical shape; the source-specific differences live only in the parsers.

```python
def _to_decimal(value, precision="0.0001"):
    """Convert numeric input to Decimal for DynamoDB storage.

    DynamoDB rejects Python float for numeric attributes because float
    arithmetic introduces rounding drift that makes threshold comparisons
    unreliable over time. Always pass baseline expected counts, deviation
    z-scores, p-values, and composite scores through Decimal on the way
    in and back out.
    """
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal(precision))


def _decimalize(obj):
    """Recursively convert floats to Decimals for DynamoDB write."""
    if isinstance(obj, float):
        return _to_decimal(obj)
    if isinstance(obj, dict):
        return {k: _decimalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decimalize(v) for v in obj]
    return obj


def _undecimalize(obj):
    """Inverse of _decimalize for read-side conversion to Python-native types."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _undecimalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_undecimalize(v) for v in obj]
    return obj


def generate_event_id():
    """Generate a surveillance event identifier."""
    return f"EV-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:10]}"


def pseudonymize(patient_identifier):
    """Replace a clinical patient identifier with a surveillance pseudonym.

    Production maintains a separate, access-controlled mapping service
    that holds the clinical-to-surveillance mapping. The analytic
    pipeline operates on the pseudonym only; investigators access the
    case detail (with the clinical identifier) under specific authority
    through a separately controlled service.

    The teaching example uses a deterministic hash so the same patient
    always maps to the same pseudonym across encounters; production uses
    a keyed HMAC with the key stored in KMS / Secrets Manager.
    """
    import hashlib
    return "SP-" + hashlib.sha256(patient_identifier.encode("utf-8")).hexdigest()[:12]


def bucket_age(age_years):
    """Bucket continuous age into surveillance age groups."""
    if age_years is None:
        return "unknown"
    if age_years < 5:
        return "under_5"
    if age_years < 18:
        return "5_17"
    if age_years < 50:
        return "18_49"
    if age_years < 65:
        return "50_64"
    return "65_plus"


def parse_by_source(raw_message, source_id):
    """Parse a source-specific message into a normalized intermediate dict.

    Production has per-source parsers: HL7 v2 ADT (hl7apy), HL7 v2 ORU,
    FHIR Encounter and Observation (fhir.resources), eCR documents, NWSS
    wastewater records, NHSN HAI reports. Each has its own schema and
    quirks. The teaching example treats raw_message as a pre-shaped dict
    so the demo runs without a real parser stack.
    """
    return raw_message


def ingest_encounter(raw_message, source_id):
    """Receive an encounter event, normalize, and put on the event stream.

    Production wires this as a Lambda triggered by the encounter-feed
    connector for each source class. The Lambda parses the source-
    specific payload, performs identifier resolution, builds the
    canonical event, and writes to Kinesis. The downstream geocoding
    Lambda picks it up.
    """
    parsed = parse_by_source(raw_message, source_id)

    # Build the canonical surveillance event. Note the deliberate
    # separation: the analytic event uses surveillance_pid (pseudonym),
    # not the clinical patient identifier. The clinical identifier
    # stays in the case-detail store, accessed only when an
    # investigator opens a cluster under appropriate authority.
    canonical = {
        "event_id":           generate_event_id(),
        "source_id":          source_id,
        "source_event_id":    parsed.get("encounter_id"),
        "observed_at":        parsed["arrival_at"],
        "ingested_at":        datetime.now(timezone.utc).isoformat(),
        "encounter_type":     parsed.get("encounter_type"),
        "facility_id":        parsed.get("facility_id"),
        "surveillance_pid":   pseudonymize(parsed["patient_identifier"]),
        "chief_complaint":    parsed.get("chief_complaint_text"),
        "triage_note":        parsed.get("triage_note_text"),
        "diagnoses_admit":    parsed.get("diagnosis_codes_admit", []),
        "diagnoses_final":    parsed.get("diagnosis_codes_final", []),
        "age_years":          parsed.get("age_years"),
        "age_group":          bucket_age(parsed.get("age_years")),
        "sex":                parsed.get("sex"),
        "race_ethnicity":     parsed.get("race_ethnicity"),
        "residence_address":  parsed.get("patient_address", {}),
        "residence_zip":      parsed.get("patient_address", {}).get("zip"),
    }

    # Append to the canonical surveillance-event stream. Partition by
    # surveillance_pid so repeat encounters from the same patient
    # arrive in order to the same shard.
    kinesis.put_record(
        StreamName=SURVEILLANCE_EVENTS_STREAM,
        Data=json.dumps(canonical, default=str).encode("utf-8"),
        PartitionKey=canonical["surveillance_pid"],
    )

    # Persist the raw event in the lake for replay and audit. The raw
    # event still contains the clinical patient identifier; it lives
    # behind KMS in S3 and is accessed only by authorized roles for
    # retrospective analysis and outbreak investigation.
    obs_at = canonical["observed_at"]
    s3_client.put_object(
        Bucket=RAW_EVENTS_BUCKET,
        Key=(
            f"source={source_id}/year={obs_at[:4]}/"
            f"month={obs_at[5:7]}/day={obs_at[8:10]}/"
            f"{canonical['event_id']}.json"
        ),
        Body=json.dumps(parsed, default=str).encode("utf-8"),
        ServerSideEncryption="aws:kms",
    )

    return {"statusCode": 200, "event_id": canonical["event_id"], "canonical": canonical}
```

Two things worth noting on this step. First, the pseudonymization-at-ingest pattern matters for the privacy-by-design architecture the recipe describes. The analytic pipeline (counts per cell, baseline computation, detector bank) operates on the surveillance pseudonym; the line list and case detail live in a separately controlled store. Production implementations sometimes blur this line and let clinical identifiers leak into the analytic stores, which makes the access-control model harder to defend and easier to break. Set the boundary early. Second, the partition-key choice (`surveillance_pid`) preserves ordering for repeat encounters from the same patient, which matters for the syndrome classifier when it considers recent prior diagnoses; partitioning by `event_id` would parallelize better but breaks the within-patient ordering assumption.

---

## Step 2: Geocode the Encounter and Assign It to Multi-Resolution Geographies

Patient residence is geocoded once (cached on subsequent visits) and assigned to the relevant administrative geographies. Multi-resolution geocoding lets the detectors run at different scales in parallel: detection at the census-tract level catches small clusters, detection at the county level catches population-wide shifts, detection at the sewershed level aligns with wastewater surveillance.

```python
# Synthetic geography reference for the demo. Production stores the
# full geography hierarchy in Aurora PostgreSQL with PostGIS, with
# annual refreshes from TIGER/Line and operational geography updates.
_DEMO_GEOGRAPHY = {
    "census_tracts": [
        {"id": "36055-001100", "polygon": Polygon([(-77.65, 43.10), (-77.60, 43.10),
                                                    (-77.60, 43.15), (-77.65, 43.15)]),
         "zcta": "14620", "county": "36055", "school_district": "ROC-CITY",
         "sewershed": "ROC-CENTRAL", "hospital_service_area": "HSA-ROC-1"},
        {"id": "36055-001200", "polygon": Polygon([(-77.60, 43.10), (-77.55, 43.10),
                                                    (-77.55, 43.15), (-77.60, 43.15)]),
         "zcta": "14620", "county": "36055", "school_district": "ROC-CITY",
         "sewershed": "ROC-CENTRAL", "hospital_service_area": "HSA-ROC-1"},
        {"id": "36055-001300", "polygon": Polygon([(-77.65, 43.05), (-77.60, 43.05),
                                                    (-77.60, 43.10), (-77.65, 43.10)]),
         "zcta": "14620", "county": "36055", "school_district": "ROC-CITY",
         "sewershed": "ROC-CENTRAL", "hospital_service_area": "HSA-ROC-1"},
        {"id": "36055-001400", "polygon": Polygon([(-77.60, 43.05), (-77.55, 43.05),
                                                    (-77.55, 43.10), (-77.60, 43.10)]),
         "zcta": "14620", "county": "36055", "school_district": "ROC-CITY",
         "sewershed": "ROC-CENTRAL", "hospital_service_area": "HSA-ROC-1"},
        {"id": "36055-002100", "polygon": Polygon([(-77.50, 43.10), (-77.45, 43.10),
                                                    (-77.45, 43.15), (-77.50, 43.15)]),
         "zcta": "14622", "county": "36055", "school_district": "ROC-EAST",
         "sewershed": "ROC-EAST", "hospital_service_area": "HSA-ROC-2"},
    ],
}


def format_address(address):
    """Format an address dict as a single string for the geocoder."""
    parts = [
        address.get("street", ""),
        address.get("city", ""),
        address.get("state", ""),
        address.get("zip", ""),
    ]
    return ", ".join(p for p in parts if p)


def geocode_with_amazon_location(address):
    """Geocode an address using Amazon Location Service.

    Production calls Amazon Location's place-index search. The teaching
    example returns a stubbed coordinate based on the ZIP code so the
    demo runs without provisioning a place index.
    """
    # Production:
    # response = location.search_place_index_for_text(
    #     IndexName=LOCATION_PLACE_INDEX,
    #     Text=format_address(address),
    #     MaxResults=1,
    # )
    # if response["Results"]:
    #     coords = response["Results"][0]["Place"]["Geometry"]["Point"]
    #     return {"lon": coords[0], "lat": coords[1]}
    # return None
    zip_to_coords = {
        "14620": {"lon": -77.625, "lat": 43.125},
        "14622": {"lon": -77.475, "lat": 43.125},
        "10001": {"lon": -73.997, "lat": 40.751},
        "94110": {"lon": -122.418, "lat": 37.748},
    }
    return zip_to_coords.get(address.get("zip"), {"lon": -77.625, "lat": 43.125})


def query_postgis_for_admin_geographies(coords):
    """Spatial join: find every administrative geography that contains the point.

    Production runs SQL like:
        SELECT
          t.id   AS census_tract,
          t.zcta AS zcta,
          t.county AS county,
          t.school_district AS school_district,
          t.sewershed AS sewershed,
          t.hospital_service_area AS hospital_service_area
        FROM   census_tracts t
        WHERE  ST_Contains(t.geometry, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))

    Against an Aurora PostgreSQL with PostGIS database. The teaching
    example walks the in-process Shapely polygons.
    """
    point = Point(coords["lon"], coords["lat"])
    for tract in _DEMO_GEOGRAPHY["census_tracts"]:
        if tract["polygon"].contains(point):
            return {
                "census_tract":           tract["id"],
                "zcta":                   tract["zcta"],
                "county":                 tract["county"],
                "school_district":        tract["school_district"],
                "sewershed":              tract["sewershed"],
                "hospital_service_area":  tract["hospital_service_area"],
            }
    return {
        "census_tract":           None,
        "zcta":                   None,
        "county":                 None,
        "school_district":        None,
        "sewershed":              None,
        "hospital_service_area":  None,
    }


def hash_address(address):
    """Compute a stable hash key for the geocode cache."""
    import hashlib
    canonical = format_address(address).lower().strip()
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def geocode_and_stratify(canonical_event):
    """Attach geographic stratification to a canonical event.

    Production caches the geocode-and-spatial-join result keyed on a
    stable address hash so repeat encounters from the same patient
    don't re-geocode unnecessarily. The cache lives in DynamoDB; entries
    expire after a configurable TTL to handle address changes and
    boundary refreshes.
    """
    if not canonical_event.get("residence_address"):
        # No address. Some encounters arrive without one (homeless
        # patients, data-entry omissions, walk-in encounters with
        # incomplete registration). Production routes these to a
        # facility-only geographic assignment as a fallback; the
        # teaching example sets all geographies to None.
        canonical_event.update({
            "coords":                None,
            "census_tract":          None,
            "zcta":                  canonical_event.get("residence_zip"),
            "county":                None,
            "school_district":       None,
            "sewershed":             None,
            "hospital_service_area": None,
        })
        return canonical_event

    cache_table = dynamodb.Table(GEOCODE_CACHE_TABLE)
    address_hash = hash_address(canonical_event["residence_address"])

    cached_response = cache_table.get_item(Key={"address_hash": address_hash})
    cached = _undecimalize(cached_response.get("Item"))

    if cached:
        coords = cached["coords"]
        admin_geographies = cached["admin_geographies"]
    else:
        coords = geocode_with_amazon_location(canonical_event["residence_address"])
        if coords is None:
            # Geocode failure (ungeocodable address, service error). Fall
            # back to ZCTA-level assignment based on the residence ZIP.
            admin_geographies = {
                "census_tract":          None,
                "zcta":                  canonical_event.get("residence_zip"),
                "county":                None,
                "school_district":       None,
                "sewershed":             None,
                "hospital_service_area": None,
            }
        else:
            admin_geographies = query_postgis_for_admin_geographies(coords)

        cache_table.put_item(Item=_decimalize({
            "address_hash":      address_hash,
            "coords":            coords,
            "admin_geographies": admin_geographies,
            "geocoded_at":       datetime.now(timezone.utc).isoformat(),
        }))

    canonical_event["coords"]                = coords
    canonical_event.update(admin_geographies)
    return canonical_event
```

A note on the geocode cache and its lifecycle. Patient addresses change. Census tract boundaries change at the decennial census and occasionally between censuses. Sewershed boundaries shift when wastewater treatment districts reorganize. School district boundaries shift with redistricting. The cache is therefore not "set once and forget"; entries should expire on a configurable TTL (typical: 90-180 days) and the system should handle the case where a patient's residence has moved between encounters. Production tracks geocode-cache hit rate and unmatched-address rate as operational metrics; a sustained drop in hit rate often indicates a TIGER/Line refresh rolled out and the cache is correctly invalidating, but a sustained increase in unmatched-address rate often indicates the source-feed address completeness regressed and warrants investigation.

---

## Step 3: Classify the Encounter into Syndromic Categories

Structured-data rules plus NLP on the chief complaint and triage note produce a multi-label syndromic classification. NSSP's syndromic categories are the standard target taxonomy. A single encounter often maps to multiple categories: a patient with fever, cough, and vomiting hits both fever_respiratory and gi.

```python
import re


def apply_icd_rules(diagnosis_codes, syndromes_set):
    """Apply ICD-10-pattern-to-syndrome rules to a list of diagnosis codes."""
    for code in diagnosis_codes or []:
        for rule in ICD_TO_SYNDROME_RULES:
            if re.match(rule["pattern"], code or ""):
                syndromes_set.add(rule["syndrome"])
    return syndromes_set


def call_comprehend_medical(text):
    """Call Amazon Comprehend Medical for entity extraction.

    Comprehend Medical extracts conditions, anatomy, medications, and
    signs/symptoms from unstructured clinical text. The teaching
    example wraps the call in a try/except so the demo can run without
    a live API call (returns an empty entity list on failure).
    """
    if not text or not text.strip():
        return []
    try:
        response = comprehend_medical.detect_entities_v2(Text=text)
        return response.get("Entities", [])
    except Exception as e:
        logger.warning("comprehend medical call failed", extra={"error": str(e)})
        _emit_metric("ComprehendMedicalFailed", 1)
        return []


def apply_entity_rules(entities, syndromes_set):
    """Map Comprehend-Medical-detected entities to syndromic categories."""
    for entity in entities or []:
        category = entity.get("Category", "").upper()
        if category not in {"MEDICAL_CONDITION", "SIGN_SYMPTOM", "DX_NAME"}:
            continue
        text = entity.get("Text", "").lower()
        for rule in ENTITY_TO_SYNDROME_RULES:
            for keyword in rule["keywords"]:
                if keyword in text:
                    syndromes_set.add(rule["syndrome"])
                    break
    return syndromes_set


def score_via_syndrome_classifier(text, age_group):
    """Invoke the deployed SageMaker syndrome-classifier endpoint.

    Production hosts a fine-tuned transformer (or a similar text
    classifier) on a SageMaker endpoint. The teaching example returns
    a small synthetic prediction list so the path runs without a
    deployed endpoint.
    """
    if not text or not text.strip():
        return []
    try:
        payload = json.dumps({"text": text, "age_group": age_group})
        response = sagemaker_runtime.invoke_endpoint(
            EndpointName=SYNDROME_CLASSIFIER_ENDPOINT,
            ContentType="application/json",
            Body=payload.encode("utf-8"),
        )
        body = json.loads(response["Body"].read().decode("utf-8"))
        return body.get("predictions", [])
    except Exception as e:
        # In the demo, fall back to a tiny heuristic so the path runs.
        logger.debug("syndrome classifier endpoint unavailable; using fallback",
                     extra={"error": str(e)})
        text_lower = text.lower()
        predictions = []
        if "fever" in text_lower and ("cough" in text_lower or "respiratory" in text_lower):
            predictions.append({"syndrome": "fever_respiratory", "confidence": 0.85})
        if "vomit" in text_lower or "diarrhea" in text_lower:
            predictions.append({"syndrome": "gi", "confidence": 0.82})
        if "rash" in text_lower:
            predictions.append({"syndrome": "rash", "confidence": 0.78})
        if "seizure" in text_lower or "altered mental" in text_lower:
            predictions.append({"syndrome": "neuro", "confidence": 0.80})
        return predictions


def lookup_recent_lab_results(surveillance_pid, window_days=14):
    """Look up recent lab results for the patient.

    Production queries the lab-event store (a separate stream and
    OpenSearch index for lab data). The teaching example returns an
    empty list; the lab integration path is documented but not
    exercised in the demo.
    """
    return []


def apply_lab_rules(lab_results, syndromes_set):
    """Promote encounters to pathogen-specific syndromic categories."""
    for lab in lab_results or []:
        if not lab.get("result_positive"):
            continue
        for rule in PATHOGEN_TO_SYNDROME_RULES:
            if lab.get("pathogen") in rule["pathogens"]:
                syndromes_set.add(rule["syndrome"])
    return syndromes_set


def classify_syndrome(canonical_event):
    """Classify an encounter into one or more syndromic categories.

    Returns the event with a `syndromes` list attached. Multi-label
    classification is intentional: a single encounter often hits
    multiple syndromic categories, and the surveillance system runs
    detectors against each category independently.
    """
    syndromes = set()

    # Structured-data rules first. Cheap, deterministic, high-precision
    # for the patterns they cover.
    apply_icd_rules(canonical_event.get("diagnoses_admit", []), syndromes)
    apply_icd_rules(canonical_event.get("diagnoses_final", []), syndromes)

    # Free-text NLP. The bulk of real-time signal lives here because
    # final diagnoses arrive hours or days after the encounter.
    free_text_parts = [
        canonical_event.get("chief_complaint") or "",
        canonical_event.get("triage_note") or "",
    ]
    free_text = " ".join(p for p in free_text_parts if p).strip()

    if free_text:
        entities = call_comprehend_medical(free_text)
        apply_entity_rules(entities, syndromes)

        # Custom syndrome classifier handles patterns the rule library
        # misses. Fine-tuned periodically on adjudicated cases.
        predictions = score_via_syndrome_classifier(
            free_text, canonical_event.get("age_group")
        )
        for prediction in predictions:
            if prediction.get("confidence", 0.0) > SYNDROME_CONFIDENCE_THRESHOLD:
                syndromes.add(prediction["syndrome"])

    # Lab-confirmed pathogens promote the encounter to specific
    # syndromic categories. Lab events arrive on a separate stream;
    # this is the encounter-side hook that joins recent lab results
    # to the encounter.
    lab_results = lookup_recent_lab_results(
        canonical_event["surveillance_pid"], window_days=14
    )
    apply_lab_rules(lab_results, syndromes)

    canonical_event["syndromes"] = sorted(syndromes)
    return canonical_event
```

The classification step is one of the highest-leverage operational components. NLP errors here propagate through every detector downstream: misclassifying a viral-respiratory encounter as a GI encounter, or missing a meningitis-like presentation in the neuro syndrome, distorts the per-cell counts that the baseline and detection layers depend on. Programs that don't validate the classifier quarterly against a held-out labeled set discover the drift only when the surveillance team starts seeing puzzling signals weeks or months later. Build the validation cadence into the program from the start; treat the syndrome taxonomy as a versioned reference and the classifier as a versioned model with formal change control.

---

## Step 4: Update Per-Cell Counters Across the Geography x Demographic x Syndrome x Time Grid

Each event increments the relevant cell counters, which are the substrate for aberration detection. A single event participates in many cells: every geography level it falls into, every demographic stratification, every syndromic category it was classified into, every temporal window. The combinatorics expand quickly and the cell-counter table is one of the largest by volume in the system.

```python
def stratifications_for(canonical_event):
    """Return the demographic stratifications the event participates in.

    Multiple stratifications in parallel let the detector catch
    subgroup signals (age-skewed pediatric outbreaks, sex-skewed
    foodborne clusters) that population-wide aggregation misses.
    Multiple-comparison handling is the cost; pay it explicitly.
    """
    strats = ["all_ages"]
    if canonical_event.get("age_group") and canonical_event["age_group"] != "unknown":
        strats.append(f"age_{canonical_event['age_group']}")
    if canonical_event.get("sex") in ("male", "female"):
        strats.append(f"sex_{canonical_event['sex']}")
    return strats


def cell_keys_for(canonical_event):
    """Build the cell key set this event participates in.

    A single event might update dozens of cells. The cardinality is:
    geographies (5-6) x stratifications (3-4) x syndromes (1-3) x
    temporal windows (4). Production keeps the cell-counter table
    sized for the resulting volume; daily writes can run into hundreds
    of millions per state-level program.
    """
    geographies = []
    for geo_type, geo_id in [
        ("census_tract",          canonical_event.get("census_tract")),
        ("zcta",                  canonical_event.get("zcta")),
        ("county",                canonical_event.get("county")),
        ("school_district",       canonical_event.get("school_district")),
        ("sewershed",             canonical_event.get("sewershed")),
        ("hospital_service_area", canonical_event.get("hospital_service_area")),
    ]:
        if geo_id:
            geographies.append((geo_type, geo_id))

    cell_keys = []
    for geo_type, geo_id in geographies:
        for strat in stratifications_for(canonical_event):
            for syndrome in canonical_event.get("syndromes", []):
                for window_days in AGGREGATION_WINDOW_DAYS:
                    cell_keys.append({
                        "geo_type":  geo_type,
                        "geo_id":    geo_id,
                        "strat":     strat,
                        "syndrome":  syndrome,
                        "window":    f"{window_days}d",
                    })
    return cell_keys


def cell_partition_key(cell_key):
    """Render a cell key as a single DynamoDB partition key string."""
    return (
        f"{cell_key['geo_type']}|{cell_key['geo_id']}|"
        f"{cell_key['strat']}|{cell_key['syndrome']}|{cell_key['window']}"
    )


def increment_cell(cell_key, observed_at):
    """Atomically increment a cell's count and update last-event timestamp."""
    cell_table = dynamodb.Table(CELL_STATE_TABLE)
    cell_table.update_item(
        Key={"cell_id": cell_partition_key(cell_key)},
        UpdateExpression=(
            "ADD #c :one "
            "SET last_event_at = :now, "
            "    geo_type = if_not_exists(geo_type, :gt), "
            "    geo_id   = if_not_exists(geo_id, :gi), "
            "    strat    = if_not_exists(strat, :s), "
            "    syndrome = if_not_exists(syndrome, :sy), "
            "    #w       = if_not_exists(#w, :win)"
        ),
        ExpressionAttributeNames={"#c": "count", "#w": "window"},
        ExpressionAttributeValues={
            ":one": 1,
            ":now": observed_at,
            ":gt":  cell_key["geo_type"],
            ":gi":  cell_key["geo_id"],
            ":s":   cell_key["strat"],
            ":sy":  cell_key["syndrome"],
            ":win": cell_key["window"],
        },
    )


def write_to_timestream(cell_key, observed_at):
    """Append a per-cell increment to the Timestream cell-time-series table.

    Production writes one record per increment to Timestream with
    cell-key dimensions and a count_increment measure. Baseline
    computation reads multi-year history from Timestream. The teaching
    example wraps the call in try/except so the path runs without a
    Timestream database; an in-memory store handles the demo flow
    (see _IN_MEMORY_TIMESTREAM below).
    """
    record = {
        "Dimensions": [
            {"Name": "geo_type", "Value": cell_key["geo_type"]},
            {"Name": "geo_id",   "Value": cell_key["geo_id"]},
            {"Name": "strat",    "Value": cell_key["strat"]},
            {"Name": "syndrome", "Value": cell_key["syndrome"]},
            {"Name": "window",   "Value": cell_key["window"]},
        ],
        "MeasureName":      "count_increment",
        "MeasureValue":     "1",
        "MeasureValueType": "BIGINT",
        "Time":             str(int(datetime.fromisoformat(
                                 observed_at.replace("Z", "+00:00")
                             ).timestamp() * 1000)),
        "TimeUnit":         "MILLISECONDS",
    }
    try:
        timestream_write.write_records(
            DatabaseName=TIMESTREAM_DATABASE,
            TableName=TIMESTREAM_CELL_TABLE,
            Records=[record],
        )
    except Exception as e:
        logger.debug("timestream write fallback to in-memory store",
                     extra={"error": str(e)})
        _in_memory_timestream_append(cell_key, observed_at)


# In-memory Timestream stand-in for the demo. Production reads from
# real Timestream; the demo populates and reads this dict.
_IN_MEMORY_TIMESTREAM = defaultdict(list)


def _in_memory_timestream_append(cell_key, observed_at):
    pk = cell_partition_key(cell_key)
    _IN_MEMORY_TIMESTREAM[pk].append(observed_at)


def update_cell_counters(canonical_event):
    """Increment every cell the event participates in."""
    cell_keys = cell_keys_for(canonical_event)
    for cell_key in cell_keys:
        increment_cell(cell_key, canonical_event["observed_at"])
        write_to_timestream(cell_key, canonical_event["observed_at"])
    return cell_keys
```

The cardinality of the cell-counter table is one of the more easily underestimated capacity concerns. A statewide program tracking 50 syndromes across 5 geography levels (let's say 1,500 census tracts, 300 ZCTAs, 60 counties, 600 school districts, 80 sewersheds), 4 stratifications, and 4 temporal windows is, in the worst case, on the order of millions of cells. Most cells are sparse (most census-tract-syndrome-stratification combinations have zero or near-zero counts most days), so the storage isn't as bad as the cardinality suggests, but the DynamoDB write rate during ingest peaks can be substantial. Production tunes write capacity and considers DynamoDB's adaptive capacity behavior; alternatively, some programs aggregate cells in a streaming layer (Kinesis Data Analytics, Apache Flink) before writing per-cell totals to DynamoDB on a 1-minute or 5-minute cadence.

---

## Step 5: Compute Baseline Expected Counts Per Cell

Daily (or weekly) job that recomputes per-cell baselines using historical data with seasonal, trend, and day-of-week terms. Hierarchical pooling stabilizes small cells where the per-cell history is too sparse to fit reliably. The baseline is the substrate for every aberration detector downstream; getting it right matters more than the detector choice.

```python
def query_timestream_for_history(cell_key, lookback_years):
    """Query Timestream for multi-year per-day count history.

    Production runs SQL like:
        SELECT bin(time, 1d) AS day, sum(measure_value) AS count
        FROM   surveillance.cell_time_series
        WHERE  geo_type = '<geo_type>' AND geo_id = '<geo_id>'
          AND  strat = '<strat>' AND syndrome = '<syndrome>'
          AND  window = '1d'
          AND  time BETWEEN ago(5y) AND now()
        GROUP BY bin(time, 1d)

    The teaching example reads from the in-memory store and synthesizes
    a per-day count series. Production reads from real Timestream.
    """
    pk = cell_partition_key(cell_key)
    timestamps = _IN_MEMORY_TIMESTREAM.get(pk, [])
    if not timestamps:
        return pd.DataFrame(columns=["day", "count"])

    days = [datetime.fromisoformat(t.replace("Z", "+00:00")).date()
            for t in timestamps]
    series = pd.Series(days).value_counts().sort_index()
    df = pd.DataFrame({"day": series.index, "count": series.values})
    df["day"] = pd.to_datetime(df["day"])
    return df


def known_outbreak_dates(cell_key):
    """Return historical outbreak windows to exclude from baseline fitting.

    Baseline contamination is a real problem: if last winter's flu
    season is in the training window, the baseline absorbs it and the
    detector under-flags the next flu season. Production maintains a
    known-outbreak registry (curated by the surveillance team) and
    excludes those date windows during baseline fitting. The teaching
    example returns an empty list.
    """
    return []


def fit_negative_binomial_glm(history_df, exclude_dates=None):
    """Fit a seasonal-and-trend GLM to per-day count history.

    Negative binomial regression handles the overdispersion that
    surveillance count data typically exhibits. Annual harmonics
    capture seasonal patterns; weekly harmonics capture day-of-week
    effects; a linear trend term captures secular drift.

    Production uses statsmodels' GLM with NegativeBinomial family or
    the equivalent in R's surveillance package. The teaching example
    fits a small Poisson GLM as a stand-in (negative binomial
    convergence is unreliable on tiny synthetic datasets).
    """
    if len(history_df) < 30:
        # Insufficient data; return a constant-mean baseline.
        mean_count = max(history_df["count"].mean(), 0.5)
        return {
            "model_type":      "constant_mean_fallback",
            "mean_count":      float(mean_count),
            "std_count":       float(max(history_df["count"].std() or 1.0, 1.0)),
        }

    df = history_df.copy()
    if exclude_dates:
        df = df[~df["day"].isin(pd.to_datetime(exclude_dates))]
    df = df.sort_values("day").reset_index(drop=True)

    # Build features: linear trend, annual harmonics, weekly harmonics.
    df["t"] = (df["day"] - df["day"].min()).dt.days.astype(float)
    df["annual_sin"] = np.sin(2 * np.pi * df["t"] / 365.25)
    df["annual_cos"] = np.cos(2 * np.pi * df["t"] / 365.25)
    df["weekly_sin"] = np.sin(2 * np.pi * df["t"] / 7.0)
    df["weekly_cos"] = np.cos(2 * np.pi * df["t"] / 7.0)
    df["dow"] = df["day"].dt.dayofweek

    # statsmodels Poisson GLM as a robust stand-in. Production uses
    # NegativeBinomial.
    try:
        import statsmodels.api as sm
        feature_cols = ["t", "annual_sin", "annual_cos", "weekly_sin", "weekly_cos"]
        X = sm.add_constant(df[feature_cols])
        y = df["count"]
        glm = sm.GLM(y, X, family=sm.families.Poisson()).fit()
        predicted = glm.predict(X)
        residuals = y - predicted
        std_resid = float(np.std(residuals)) or 1.0
        return {
            "model_type":         "poisson_glm",
            "feature_cols":       feature_cols,
            "params":             glm.params.to_dict(),
            "first_day":          df["day"].min().isoformat(),
            "predicted_per_day":  predicted.tolist(),
            "actual_per_day":     y.tolist(),
            "residual_std":       std_resid,
        }
    except Exception as e:
        logger.warning("GLM fit failed; using constant-mean fallback",
                       extra={"error": str(e)})
        return {
            "model_type":  "constant_mean_fallback",
            "mean_count":  float(history_df["count"].mean()),
            "std_count":   float(max(history_df["count"].std() or 1.0, 1.0)),
        }


def predict_baseline_for_date(model_summary, target_date):
    """Predict expected count and prediction intervals for a target date."""
    if model_summary["model_type"] == "constant_mean_fallback":
        mean = model_summary["mean_count"]
        std  = model_summary["std_count"]
        return {
            "expected": mean,
            "upper_95": mean + 1.96 * std,
            "upper_99": mean + 2.58 * std,
            "std":      std,
        }

    first_day = datetime.fromisoformat(model_summary["first_day"]).date()
    t = (target_date - first_day).days

    annual_sin = math.sin(2 * math.pi * t / 365.25)
    annual_cos = math.cos(2 * math.pi * t / 365.25)
    weekly_sin = math.sin(2 * math.pi * t / 7.0)
    weekly_cos = math.cos(2 * math.pi * t / 7.0)

    p = model_summary["params"]
    log_mu = (
        p.get("const", 0.0)
      + p.get("t", 0.0)            * t
      + p.get("annual_sin", 0.0)   * annual_sin
      + p.get("annual_cos", 0.0)   * annual_cos
      + p.get("weekly_sin", 0.0)   * weekly_sin
      + p.get("weekly_cos", 0.0)   * weekly_cos
    )
    expected = math.exp(log_mu)
    std      = max(model_summary["residual_std"], 1.0)

    return {
        "expected": expected,
        "upper_95": expected + 1.96 * std,
        "upper_99": expected + 2.58 * std,
        "std":      std,
    }


def downscale_parent(parent_model, cell):
    """Use the parent geography's model with a cell-specific offset.

    Hierarchical pooling: when a cell has insufficient history, fall back
    to the parent geography's baseline scaled by the cell's population
    fraction. Production runs this through a hierarchical Bayesian model
    (INLA, brms, or a custom Stan model). The teaching example just
    halves the parent's expected count as a placeholder.
    """
    parent_summary = parent_model
    if parent_summary["model_type"] == "constant_mean_fallback":
        return {
            "model_type": "constant_mean_fallback",
            "mean_count": parent_summary["mean_count"] * 0.5,
            "std_count":  max(parent_summary["std_count"] * 0.7, 1.0),
        }
    return parent_summary


def get_parent_baseline_model(cell_key):
    """Return the baseline model for the cell's parent geography.

    Census tract -> ZCTA -> county -> state. The teaching example just
    returns a constant-mean fallback so the path runs.
    """
    return {
        "model_type":  "constant_mean_fallback",
        "mean_count":  3.0,
        "std_count":   1.5,
    }


def enumerate_active_cells():
    """Return all currently-active cells in the system.

    Production iterates the cell-state table (or a derived index of
    active cells) so every cell with recent activity gets a baseline
    refresh. The teaching example walks the in-memory Timestream
    store.
    """
    cells = []
    for pk in _IN_MEMORY_TIMESTREAM.keys():
        parts = pk.split("|")
        if len(parts) == 5:
            cells.append({
                "geo_type":  parts[0],
                "geo_id":    parts[1],
                "strat":     parts[2],
                "syndrome":  parts[3],
                "window":    parts[4],
            })
    return cells


def compute_baselines(reference_date):
    """Recompute baselines for every active cell.

    Production runs this as a daily Step Functions workflow that fans
    out across active cells using AWS Batch or SageMaker Processing.
    Each cell's baseline is persisted to S3 (versioned per
    reference_date) and the per-day prediction is updated in DynamoDB
    cell-state for fast scoring.
    """
    cells = enumerate_active_cells()
    if not cells:
        return []

    baselines = []
    for cell in cells:
        # Only compute for the daily-window cells; the 7d/14d/28d
        # baselines are derived from the 1d series.
        if cell["window"] != "1d":
            continue

        history = query_timestream_for_history(cell, BASELINE_LOOKBACK_YEARS)
        excluded = known_outbreak_dates(cell)

        if (len(history) < MIN_HISTORY_DAYS
                or history["count"].sum() < MIN_HISTORY_COUNT):
            parent_model = get_parent_baseline_model(cell)
            cell_baseline = downscale_parent(parent_model, cell)
            baseline_source = "parent_pooled"
        else:
            cell_baseline = fit_negative_binomial_glm(
                history, exclude_dates=excluded
            )
            baseline_source = "cell_specific"

        prediction = predict_baseline_for_date(cell_baseline, reference_date)

        # Persist to S3 (versioned baseline store).
        baseline_record = {
            "cell":             cell,
            "expected":         prediction["expected"],
            "upper_95":         prediction["upper_95"],
            "upper_99":         prediction["upper_99"],
            "std":              prediction["std"],
            "model_summary":    cell_baseline,
            "source":           baseline_source,
            "reference_date":   reference_date.isoformat(),
            "computed_at":      datetime.now(timezone.utc).isoformat(),
        }

        try:
            s3_client.put_object(
                Bucket=BASELINE_STORE_BUCKET,
                Key=(
                    f"baseline/{cell['geo_type']}/{cell['geo_id']}/"
                    f"{cell['strat']}/{cell['syndrome']}/"
                    f"{reference_date.isoformat()}.json"
                ),
                Body=json.dumps(baseline_record, default=str).encode("utf-8"),
                ServerSideEncryption="aws:kms",
            )
        except Exception as e:
            logger.debug("baseline S3 write skipped",
                         extra={"error": str(e)})

        # Update cell-state with the latest expected and intervals.
        cell_table = dynamodb.Table(CELL_STATE_TABLE)
        cell_table.update_item(
            Key={"cell_id": cell_partition_key(cell)},
            UpdateExpression=(
                "SET expected = :e, upper_95 = :u95, upper_99 = :u99, "
                "    baseline_source = :src, baseline_at = :t"
            ),
            ExpressionAttributeValues={
                ":e":   _to_decimal(prediction["expected"]),
                ":u95": _to_decimal(prediction["upper_95"]),
                ":u99": _to_decimal(prediction["upper_99"]),
                ":src": baseline_source,
                ":t":   datetime.now(timezone.utc).isoformat(),
            },
        )

        baselines.append(baseline_record)

    return baselines
```

A note on baseline contamination. The single biggest source of detection failure I've seen is leaving last year's outbreak in the baseline window. The detector then absorbs the prior outbreak as "normal" and under-flags the next one. Production maintains a known-outbreak registry that the surveillance team curates: every confirmed outbreak gets a date-window entry that gets excluded during baseline fitting for the affected cells. The exclusion logic isn't trivial because outbreaks have soft edges (when did the outbreak start? when did it really end?) and because some patterns recur seasonally in ways that should be captured by the seasonal terms, not excluded. The right operational answer is to maintain the registry, exclude the explicit windows, and validate baselines after fitting against the surveillance team's intuition for each major cell. Programs that skip this step quietly degrade detection performance over multiple seasons.

---

## Step 6: Run the Detector Bank

Multiple detectors run in parallel against the cell time series. Each produces per-cell or per-cluster scores. The detectors complement each other: control charts catch fast shifts, regression-based methods catch deviations from seasonal expectations, spatial scan statistics catch geographic clustering, cross-syndrome correlation catches multi-pathogen signals. The composite scoring layer combines them.

```python
def get_recent_counts(cell_key, days=60):
    """Return the recent daily count series for a cell."""
    history = query_timestream_for_history(cell_key, lookback_years=1)
    if history.empty:
        return pd.DataFrame(columns=["day", "count"])
    cutoff = pd.Timestamp(datetime.now(timezone.utc).date() - timedelta(days=days))
    return history[history["day"] >= cutoff].copy()


def load_baseline_for_cell(cell_key, reference_date):
    """Load the baseline record persisted for the cell on this reference date."""
    cell_table = dynamodb.Table(CELL_STATE_TABLE)
    response = cell_table.get_item(Key={"cell_id": cell_partition_key(cell_key)})
    item = _undecimalize(response.get("Item")) or {}
    return {
        "expected":  item.get("expected", 1.0),
        "upper_95":  item.get("upper_95", 5.0),
        "upper_99":  item.get("upper_99", 7.0),
        "std":       max(item.get("upper_95", 5.0) - item.get("expected", 1.0), 1.0) / 1.96,
    }


def compute_cusum(observed, expected, sigma, k, h):
    """Compute a CUSUM control chart on the observed series.

    CUSUM (Cumulative Sum) accumulates standardized deviations above
    the expected level and signals when the running sum exceeds the
    decision threshold h. The reference value k is the size of shift
    (in standard deviations) the chart is tuned to detect quickly.

    Returns the most recent CUSUM value and a boolean flag.
    """
    if len(observed) == 0:
        return {"cusum_value": 0.0, "signal": False}
    z = (observed - expected) / max(sigma, 1e-6)
    cumsum = 0.0
    history = []
    for zi in z:
        cumsum = max(0.0, cumsum + zi - k)
        history.append(cumsum)
    return {
        "cusum_value":  history[-1],
        "signal":       history[-1] > h,
        "history":      history,
    }


def compute_ewma(observed, expected, sigma, lambda_val, limit):
    """Compute an EWMA control chart on the observed series.

    EWMA (Exponentially Weighted Moving Average) smooths the standardized
    deviations and flags when the smoothed value exceeds the control
    limit (in standard deviations of the smoothed series).
    """
    if len(observed) == 0:
        return {"ewma_value": 0.0, "signal": False}
    z = (observed - expected) / max(sigma, 1e-6)
    ewma_value = 0.0
    history = []
    for zi in z:
        ewma_value = lambda_val * zi + (1 - lambda_val) * ewma_value
        history.append(ewma_value)
    # The EWMA's standard deviation is sigma * sqrt(lambda / (2 - lambda)).
    ewma_sigma = math.sqrt(lambda_val / (2 - lambda_val))
    return {
        "ewma_value":   history[-1],
        "signal":       abs(history[-1]) > limit * ewma_sigma,
        "history":      history,
    }


def run_control_chart_detectors(reference_date):
    """Run CUSUM and EWMA per active cell."""
    results = []
    for cell in enumerate_active_cells():
        if cell["window"] != "1d":
            continue
        recent = get_recent_counts(cell, days=60)
        if recent.empty:
            continue
        baseline = load_baseline_for_cell(cell, reference_date)
        cusum_result = compute_cusum(
            recent["count"].values,
            baseline["expected"],
            baseline["std"],
            CUSUM_REFERENCE_K,
            CUSUM_DECISION_H,
        )
        ewma_result = compute_ewma(
            recent["count"].values,
            baseline["expected"],
            baseline["std"],
            EWMA_LAMBDA,
            EWMA_CONTROL_LIMIT,
        )
        flagged = bool(cusum_result["signal"] or ewma_result["signal"])
        results.append({
            "detector":        "control_chart",
            "cell":            cell,
            "cusum_value":     float(cusum_result["cusum_value"]),
            "ewma_value":      float(ewma_result["ewma_value"]),
            "flagged":         flagged,
            "reference_date":  reference_date.isoformat(),
        })
    return results


def run_farrington_flexible_detector(reference_date):
    """Run the Farrington Flexible regression-based detector per cell.

    Production runs this as a SageMaker Processing job per cell (or
    batched across cells), using the R `surveillance` package or a
    Python port. The teaching example computes a tail-probability
    score against the Poisson GLM baseline.
    """
    results = []
    for cell in enumerate_active_cells():
        if cell["window"] != "1d":
            continue
        baseline = load_baseline_for_cell(cell, reference_date)
        recent = get_recent_counts(cell, days=7)
        if recent.empty:
            continue
        observed_today = recent["count"].iloc[-1] if len(recent) else 0
        expected = baseline["expected"]
        upper_99 = baseline["upper_99"]

        # Standardized exceedance score: (observed - expected) / std.
        std = baseline["std"]
        exceedance = (observed_today - expected) / max(std, 1e-6)
        flagged = observed_today > upper_99

        results.append({
            "detector":        "farrington_flexible",
            "cell":            cell,
            "observed":        float(observed_today),
            "expected":        float(expected),
            "upper_99":        float(upper_99),
            "exceedance":      float(exceedance),
            "flagged":         bool(flagged),
            "reference_date":  reference_date.isoformat(),
        })
    return results


def submit_satscan_batch_job(scan_geography, reference_date, method,
                              max_window_pct=25, max_temporal_window_days=14):
    """Submit a SaTScan run as an AWS Batch job.

    Production stages a case file, a population file, and a parameter
    file into S3, then submits an AWS Batch job that runs the SaTScan
    binary in a container against the staged inputs. The job parses the
    output and writes significant clusters back to a results store.

    The teaching example replaces this with a tiny stub that flags
    cells where today's count substantially exceeds the upper-99
    interval and groups geographically adjacent flagged cells into
    a synthetic cluster. Use real SaTScan in production; this stub
    exists only so the path is exercised.
    """
    # Stub: scan all daily-window cells and group adjacent flagged cells.
    flagged_cells = []
    for cell in enumerate_active_cells():
        if cell["window"] != "1d" or cell["geo_type"] != "census_tract":
            continue
        baseline = load_baseline_for_cell(cell, reference_date)
        recent = get_recent_counts(cell, days=1)
        if recent.empty:
            continue
        observed_today = recent["count"].iloc[-1]
        if observed_today > baseline["upper_99"]:
            flagged_cells.append({
                "cell":       cell,
                "observed":   float(observed_today),
                "expected":   float(baseline["expected"]),
                "upper_99":   float(baseline["upper_99"]),
            })

    if len(flagged_cells) < 2:
        return {"significant_clusters": []}

    # Group flagged cells into a single cluster (the demo doesn't
    # actually do spatial proximity testing; real SaTScan does).
    cluster = {
        "geographies":     [c["cell"]["geo_id"] for c in flagged_cells],
        "syndromes":       list({c["cell"]["syndrome"] for c in flagged_cells}),
        "observed":        sum(c["observed"] for c in flagged_cells),
        "expected":        sum(c["expected"] for c in flagged_cells),
        "p_value":         0.005,    # synthetic; real SaTScan computes via permutation
        "relative_risk":   sum(c["observed"] for c in flagged_cells)
                            / max(sum(c["expected"] for c in flagged_cells), 1.0),
        "method":          method,
        "reference_date":  reference_date.isoformat(),
    }
    return {"significant_clusters": [cluster]}


def run_satscan_detectors(reference_date):
    """Run spatial and spatiotemporal scan statistics."""
    results = []
    spatial = submit_satscan_batch_job(
        "county_zcta", reference_date, "poisson", max_window_pct=25
    )
    for cluster in spatial["significant_clusters"]:
        if cluster["p_value"] < SCAN_PVALUE_THRESHOLD:
            results.append({
                "detector":        "satscan_spatial",
                "cluster":         cluster,
                "p_value":         cluster["p_value"],
                "relative_risk":   cluster["relative_risk"],
                "flagged":         True,
                "reference_date":  reference_date.isoformat(),
            })

    spacetime = submit_satscan_batch_job(
        "county_zcta", reference_date, "space_time_permutation",
        max_temporal_window_days=14,
    )
    for cluster in spacetime["significant_clusters"]:
        if cluster["p_value"] < SCAN_PVALUE_THRESHOLD:
            results.append({
                "detector":        "satscan_spacetime",
                "cluster":         cluster,
                "p_value":         cluster["p_value"],
                "relative_risk":   cluster["relative_risk"],
                "flagged":         True,
                "reference_date":  reference_date.isoformat(),
            })
    return results


def run_detector_bank(reference_date):
    """Run all detectors and return the combined result list."""
    all_results = []
    all_results.extend(run_control_chart_detectors(reference_date))
    all_results.extend(run_farrington_flexible_detector(reference_date))
    all_results.extend(run_satscan_detectors(reference_date))

    # Persist to OpenSearch and EventBridge for the cluster builder
    # and the audit archive.
    for result in all_results:
        try:
            eventbridge.put_events(Entries=[{
                "Source":      "surveillance.detector-bank",
                "DetailType":  "DetectorResult",
                "Detail":      json.dumps(result, default=str),
                "EventBusName": CLUSTER_BUS,
            }])
        except Exception as e:
            logger.debug("detector result event publish failed",
                         extra={"error": str(e)})
    return all_results
```

The detector-bank pattern (multiple detectors in parallel, fused later) is what the academic literature calls "ensemble surveillance," and it's the right approach for the same reason ensembles are right elsewhere: each detector has its own failure modes, and combining them recovers signal that any single detector would miss. CUSUM is fast at catching shifts but slow at catching gradual drifts; EWMA does the opposite. Farrington Flexible handles seasonality well but assumes the seasonal model is correct. SaTScan handles spatial clustering but ignores temporal nuance unless you use the space-time variant. Run them all, weight them appropriately, and let the fusion layer decide. The cost is engineering complexity; the benefit is robustness across the heterogeneous outbreak shapes the real world produces.

---

## Step 7: Run Auxiliary-Source Detectors and Fuse Signals

Wastewater, pharmacy, school absenteeism, and other auxiliary sources have their own detectors. The fusion layer combines signals from multiple sources into per-cluster composite scores. Concordance across sources elevates the composite; the operational pattern in mature programs is decision-level fusion with each source's detector tuned independently.

```python
# Synthetic auxiliary-data store for the demo. Production reads from
# real source feeds (NWSS for wastewater, retail-pharmacy partnerships
# for pharmacy, state-DOE feeds for school absenteeism).
_DEMO_WASTEWATER = {
    "ROC-CENTRAL": {
        "sars_cov_2": [
            {"date": "2026-10-13", "concentration": 1.2e6},
            {"date": "2026-10-15", "concentration": 1.4e6},
            {"date": "2026-10-17", "concentration": 2.1e6},
            {"date": "2026-10-19", "concentration": 2.6e6},
            {"date": "2026-10-21", "concentration": 3.0e6},
            {"date": "2026-10-23", "concentration": 3.4e6},
        ],
    },
}

_DEMO_ABSENTEEISM = {
    "ROC-CITY": [
        {"date": "2026-10-15", "rate": 0.075},
        {"date": "2026-10-16", "rate": 0.080},
        {"date": "2026-10-19", "rate": 0.110},
        {"date": "2026-10-20", "rate": 0.140},
        {"date": "2026-10-21", "rate": 0.165},
        {"date": "2026-10-22", "rate": 0.180},
    ],
}


def load_ww_concentration_history(sewershed, pathogen):
    """Load wastewater concentration history for a sewershed and pathogen."""
    return _DEMO_WASTEWATER.get(sewershed, {}).get(pathogen, [])


def fit_ww_baseline(history):
    """Fit a simple baseline mean and std on log-transformed concentrations.

    Production normalizes against PMMoV (a viral indicator that controls
    for sample dilution) or against sewershed flow rate, fits a seasonal
    baseline, and applies pathogen-specific quality-control rules. The
    teaching example is a stand-in.
    """
    if not history:
        return {"mean": 1.0, "std": 1.0}
    values = np.array([math.log10(max(h["concentration"], 1.0)) for h in history[:-3]])
    if len(values) == 0:
        return {"mean": 1.0, "std": 1.0}
    return {"mean": float(values.mean()),
            "std":  float(max(values.std(), 0.1))}


def current_ww_concentration(sewershed, pathogen, reference_date):
    """Return the most recent wastewater concentration for the sewershed."""
    history = _DEMO_WASTEWATER.get(sewershed, {}).get(pathogen, [])
    if not history:
        return None
    return history[-1]["concentration"]


def run_wastewater_detector(reference_date):
    """Detect wastewater pathogen-concentration anomalies."""
    results = []
    for sewershed, pathogens in _DEMO_WASTEWATER.items():
        for pathogen, _ in pathogens.items():
            history = load_ww_concentration_history(sewershed, pathogen)
            if len(history) < 3:
                continue
            baseline = fit_ww_baseline(history)
            current_raw = current_ww_concentration(sewershed, pathogen, reference_date)
            if current_raw is None:
                continue
            current_log = math.log10(max(current_raw, 1.0))
            ww_score = (current_log - baseline["mean"]) / max(baseline["std"], 1e-6)
            if ww_score > WW_ANOMALY_THRESHOLD:
                results.append({
                    "detector":        "wastewater",
                    "sewershed":       sewershed,
                    "pathogen":        pathogen,
                    "anomaly_score":   float(ww_score),
                    "current_value":   float(current_raw),
                    "flagged":         True,
                    "reference_date":  reference_date.isoformat(),
                })
    return results


def run_absenteeism_detector(reference_date):
    """Detect school absenteeism spikes."""
    results = []
    for district, history in _DEMO_ABSENTEEISM.items():
        if len(history) < 5:
            continue
        baseline_values = np.array([h["rate"] for h in history[:-3]])
        baseline_mean = baseline_values.mean()
        baseline_std  = max(baseline_values.std(), 0.001)
        current_rate = history[-1]["rate"]
        score = (current_rate - baseline_mean) / baseline_std
        if score > ABSENTEEISM_THRESHOLD:
            results.append({
                "detector":        "school_absenteeism",
                "district":        district,
                "current_rate":    float(current_rate),
                "baseline_rate":   float(baseline_mean),
                "score":           float(score),
                "flagged":         True,
                "reference_date":  reference_date.isoformat(),
            })
    return results


def run_pharmacy_detector(reference_date):
    """Detect pharmacy-volume spikes (placeholder; demo returns empty).

    Production wires retail-pharmacy partnerships for OTC product sales
    and prescription-fill data. The teaching example skips this path.
    """
    return []


def candidate_geo_windows(clinical_results, auxiliary_results):
    """Build the set of geography-window candidates from detector outputs.

    Each detector flags either cells (clinical) or higher-level
    geographies (sewersheds for wastewater, school districts for
    absenteeism). The fusion layer aligns these to a common geography
    (typically the ZCTA or census-tract level) and combines signals
    that overlap.
    """
    candidates = {}

    # Clinical signals: extract per-syndrome geographies.
    for result in clinical_results:
        if not result.get("flagged"):
            continue
        cell = result.get("cell")
        if cell:
            key = (cell["geo_type"], cell["geo_id"], cell["syndrome"])
            candidates.setdefault(key, {
                "geo_type":     cell["geo_type"],
                "geo_id":       cell["geo_id"],
                "syndrome":     cell["syndrome"],
                "syndrome_class": classify_syndrome_class(cell["syndrome"]),
                "geo_class":    classify_geo_class(cell["geo_type"]),
            })

    # Wastewater signals: associate with the sewershed and the
    # respiratory-or-GI syndrome class implied by the pathogen.
    pathogen_to_syndrome = {
        "sars_cov_2":   "fever_respiratory",
        "influenza_a":  "ili",
        "influenza_b":  "ili",
        "rsv":          "fever_respiratory",
        "norovirus":    "gi",
    }
    for result in auxiliary_results:
        if result.get("detector") == "wastewater":
            syndrome = pathogen_to_syndrome.get(result.get("pathogen"), "fever_respiratory")
            key = ("sewershed", result["sewershed"], syndrome)
            candidates.setdefault(key, {
                "geo_type":     "sewershed",
                "geo_id":       result["sewershed"],
                "syndrome":     syndrome,
                "syndrome_class": classify_syndrome_class(syndrome),
                "geo_class":    "sewershed",
            })
        elif result.get("detector") == "school_absenteeism":
            key = ("school_district", result["district"], "ili")
            candidates.setdefault(key, {
                "geo_type":     "school_district",
                "geo_id":       result["district"],
                "syndrome":     "ili",
                "syndrome_class": "respiratory",
                "geo_class":    "school_district",
            })

    return list(candidates.values())


def classify_syndrome_class(syndrome):
    """Group syndromes into broader classes for fusion calibration."""
    if syndrome in {"fever_respiratory", "ili", "asthma_copd"}:
        return "respiratory"
    if syndrome == "gi":
        return "gi"
    if syndrome == "rash":
        return "rash"
    if syndrome == "neuro":
        return "neuro"
    if syndrome == "sepsis":
        return "sepsis"
    return "other"


def classify_geo_class(geo_type):
    """Group geography types into broader classes for fusion calibration."""
    if geo_type in {"census_tract", "zcta"}:
        return "neighborhood"
    if geo_type == "county":
        return "county"
    return geo_type


def max_score_for(results, candidate, detector=None):
    """Return the maximum score for the candidate from results."""
    max_score = 0.0
    for result in results:
        if detector and result.get("detector") != detector:
            continue
        if not result.get("flagged"):
            continue
        # Match by geography overlap.
        cell = result.get("cell")
        if cell and cell.get("geo_id") == candidate["geo_id"]:
            score = abs(result.get("exceedance",
                                    result.get("ewma_value",
                                              result.get("cusum_value", 0.0))))
            max_score = max(max_score, min(score / 5.0, 1.0))
        elif result.get("sewershed") == candidate["geo_id"]:
            max_score = max(max_score,
                            min(result.get("anomaly_score", 0.0) / 5.0, 1.0))
        elif result.get("district") == candidate["geo_id"]:
            max_score = max(max_score,
                            min(result.get("score", 0.0) / 5.0, 1.0))
    return max_score


def count_concordant_sources(*signals, threshold):
    """Count how many signal scores exceed the concordance threshold."""
    return sum(1 for s in signals if s and s > threshold)


def apply_fusion_calibration(score, cohort, calibration):
    """Apply a per-cohort calibration mapping to the fused score.

    Production maintains per-cohort calibration curves fit on labeled
    historical adjudications. The teaching example clips to [0, 1].
    """
    return min(max(score, 0.0), 1.0)


def run_auxiliary_and_fuse(reference_date, clinical_results):
    """Run auxiliary detectors and fuse with clinical signals."""
    auxiliary_results = []
    auxiliary_results.extend(run_wastewater_detector(reference_date))
    auxiliary_results.extend(run_absenteeism_detector(reference_date))
    auxiliary_results.extend(run_pharmacy_detector(reference_date))

    fused_signals = []
    for candidate in candidate_geo_windows(clinical_results, auxiliary_results):
        clinical_signal     = max_score_for(clinical_results, candidate)
        wastewater_signal   = max_score_for(auxiliary_results, candidate, "wastewater")
        pharmacy_signal     = max_score_for(auxiliary_results, candidate, "pharmacy_spike")
        absenteeism_signal  = max_score_for(auxiliary_results, candidate, "school_absenteeism")

        composite = (
            FUSION_WEIGHTS["clinical"]    * clinical_signal
          + FUSION_WEIGHTS["wastewater"]  * wastewater_signal
          + FUSION_WEIGHTS["pharmacy"]    * pharmacy_signal
          + FUSION_WEIGHTS["absenteeism"] * absenteeism_signal
        )
        concordance_bonus = (
            count_concordant_sources(
                clinical_signal, wastewater_signal,
                pharmacy_signal, absenteeism_signal,
                threshold=CONCORDANCE_SIGNAL_THRESHOLD,
            )
            * CONCORDANCE_BONUS_PER_SOURCE
        )
        composite_with_concordance = composite + concordance_bonus
        calibrated = apply_fusion_calibration(
            composite_with_concordance,
            cohort=(candidate["geo_class"], candidate["syndrome_class"]),
            calibration=None,
        )

        fused_signals.append({
            "candidate":             candidate,
            "clinical_signal":       float(clinical_signal),
            "wastewater_signal":     float(wastewater_signal),
            "pharmacy_signal":       float(pharmacy_signal),
            "absenteeism_signal":    float(absenteeism_signal),
            "composite_raw":         float(composite),
            "concordance_bonus":     float(concordance_bonus),
            "composite_calibrated":  float(calibrated),
            "concordant_source_count": count_concordant_sources(
                clinical_signal, wastewater_signal,
                pharmacy_signal, absenteeism_signal,
                threshold=CONCORDANCE_SIGNAL_THRESHOLD,
            ),
            "reference_date":        reference_date.isoformat(),
        })

    return fused_signals
```

The fusion layer is the biggest leverage point in the whole pipeline. Single-source detectors are noisy; multi-source concordance compresses noise and elevates real signals. The COVID-19 pandemic demonstrated this at scale: programs that had integrated wastewater plus clinical surveillance plus genomic surveillance had a much clearer view than programs running each in isolation. The engineering challenge is that each auxiliary integration is a multi-quarter project (NWSS access, retail-pharmacy partnerships, school district data-sharing agreements), and the value compounds only after multiple sources are wired up. Plan the integration roadmap in priority order: clinical syndromic first, wastewater second (highest marginal value once the pipeline exists), then auxiliary sources as bandwidth permits.

---

## Step 8: Build Cluster Candidates from Fused Signals

The cluster builder groups geographically and temporally adjacent flagged cells into cluster candidates, attaches the line list and supporting evidence, generates the LLM narrative, and applies suppression rules against open and recently-resolved clusters. This is the actual product. A perfect score with no cluster package and no narrative is no use to a surveillance epidemiologist.

```python
def aggregate_adjacent_flags(signals, temporal_window_days):
    """Group geographically and temporally adjacent flagged signals.

    Production runs spatial proximity testing in PostGIS to identify
    cells whose geographies share boundaries or are within a distance
    threshold. The teaching example groups by syndrome and county; a
    real spatial proximity check is what scales.
    """
    groups = defaultdict(list)
    for signal in signals:
        candidate = signal["candidate"]
        # Group key: (county-equivalent, syndrome). For the demo, we
        # use the geography ID prefix as a proxy for county.
        county_key = (candidate["geo_id"][:5]
                      if candidate["geo_type"] == "census_tract"
                      else candidate["geo_id"])
        group_key = (county_key, candidate["syndrome"])
        groups[group_key].append(signal)

    proto_clusters = []
    for (county, syndrome), group_signals in groups.items():
        if not group_signals:
            continue
        # Proto-cluster aggregates the flagged geographies, the
        # window, and the strongest signal across sources.
        geographies = list({(s["candidate"]["geo_type"], s["candidate"]["geo_id"])
                            for s in group_signals})
        composite = max(s["composite_calibrated"] for s in group_signals)
        signal_summary = {
            "clinical_signal":         max(s["clinical_signal"] for s in group_signals),
            "wastewater_signal":       max(s["wastewater_signal"] for s in group_signals),
            "pharmacy_signal":         max(s["pharmacy_signal"] for s in group_signals),
            "absenteeism_signal":      max(s["absenteeism_signal"] for s in group_signals),
            "concordant_source_count": max(s["concordant_source_count"]
                                            for s in group_signals),
        }

        ref_date = datetime.fromisoformat(group_signals[0]["reference_date"]).date()
        proto_clusters.append({
            "geographies":           [{"type": gt, "id": gi} for gt, gi in geographies],
            "syndromes":             [syndrome],
            "window_start":          (ref_date - timedelta(days=temporal_window_days)).isoformat(),
            "window_end":            ref_date.isoformat(),
            "composite_calibrated":  composite,
            "signal_summary":        signal_summary,
        })
    return proto_clusters


def find_existing_open_cluster(proto):
    """Search for an open cluster covering the same geography and syndrome."""
    cluster_table = dynamodb.Table(CLUSTER_STATE_TABLE)
    geo_ids = sorted([g["id"] for g in proto["geographies"]])
    syndromes = sorted(proto["syndromes"])

    response = cluster_table.scan(
        FilterExpression=Attr("status").eq("open_for_review"),
    )
    for item in response.get("Items", []):
        existing = _undecimalize(item)
        existing_geo_ids = sorted([g["id"] for g in existing.get("geographies", [])])
        existing_syndromes = sorted(existing.get("syndromes", []))
        if (existing_geo_ids == geo_ids
                and existing_syndromes == syndromes):
            return existing
    return None


def update_existing_cluster(existing_cluster, proto):
    """Append the new signal to an existing open cluster."""
    cluster_table = dynamodb.Table(CLUSTER_STATE_TABLE)
    composite = max(existing_cluster.get("composite_score", 0.0),
                    proto["composite_calibrated"])
    cluster_table.update_item(
        Key={"cluster_id": existing_cluster["cluster_id"]},
        UpdateExpression="SET composite_score = :c, updated_at = :t",
        ExpressionAttributeValues={
            ":c": _to_decimal(composite),
            ":t": datetime.now(timezone.utc).isoformat(),
        },
    )


def check_recent_dismissal(proto, reason_class):
    """Was this same pattern recently dismissed for the relevant geographies?"""
    suppression_table = dynamodb.Table(SUPPRESSION_RULES_TABLE)
    geo_ids = {g["id"] for g in proto["geographies"]}
    syndromes = set(proto["syndromes"])
    now_iso = datetime.now(timezone.utc).isoformat()

    response = suppression_table.scan()
    for item in response.get("Items", []):
        rule = _undecimalize(item)
        if rule.get("valid_until", "") < now_iso:
            continue
        if rule.get("reason_class") != reason_class:
            continue
        rule_geo_ids = set(rule.get("geographies", []))
        rule_syndromes = set(rule.get("syndromes", []))
        if rule_geo_ids & geo_ids and rule_syndromes & syndromes:
            return True
    return False


def log_suppression(proto, reason):
    """Log that a proto-cluster was suppressed."""
    logger.info("cluster suppressed",
                extra={"reason": reason,
                       "geographies": [g["id"] for g in proto["geographies"]],
                       "syndromes": proto["syndromes"]})
    _emit_metric(f"Suppressed_{reason}", 1)


def line_list_build(geographies, syndromes, window_start, window_end):
    """Build the line list for a cluster.

    Production queries the case-detail store (a separate, access-
    controlled service) for encounters matching the cluster's
    geography x syndrome x time window. Investigators access the line
    list under specific authority. The teaching example returns a
    synthetic line list summary.
    """
    geo_ids = {g["id"] for g in geographies}
    line_list = []
    # In the demo, we return a small synthetic line list keyed off
    # the geographies and syndromes; production runs a real query.
    for i, geo_id in enumerate(geo_ids):
        for syndrome in syndromes:
            for j in range(3):
                line_list.append({
                    "case_index":   i * 10 + j,
                    "encounter_id": f"DEMO-{geo_id}-{syndrome}-{j}",
                    "syndrome":     syndrome,
                    "geo_id":       geo_id,
                    "age_group":    "5_17" if j < 2 else "18_49",
                    "sex":          "male" if j % 2 else "female",
                    "observed_at":  window_end,
                })
    return line_list


def line_list_summary(line_list):
    """Return a de-identified summary of the line list for case display."""
    if not line_list:
        return {}
    return {
        "case_count":     len(line_list),
        "syndromes":      sorted(list({c["syndrome"] for c in line_list})),
        "geographies":    sorted(list({c["geo_id"] for c in line_list})),
        "age_distribution": dict(Counter(c["age_group"] for c in line_list)),
    }


def persist_line_list(line_list):
    """Persist the line list (with case-detail authority required to read).

    Production writes to OpenSearch with field-level access controls
    so only authorized investigators can retrieve the full line list.
    The teaching example just returns a placeholder pointer.
    """
    line_list_id = f"LL-{uuid.uuid4().hex[:12]}"
    return line_list_id


def sum_of_expected_for(geographies, syndromes, window_start, window_end):
    """Sum the baseline expected counts across the cluster's cells and window."""
    expected = 0.0
    days = max((datetime.fromisoformat(window_end)
                - datetime.fromisoformat(window_start)).days, 1)
    for geo in geographies:
        for syndrome in syndromes:
            cell_key = {
                "geo_type":  geo["type"],
                "geo_id":    geo["id"],
                "strat":     "all_ages",
                "syndrome":  syndrome,
                "window":    "1d",
            }
            baseline = load_baseline_for_cell(cell_key,
                                               datetime.fromisoformat(window_end).date())
            expected += baseline["expected"] * days
    return expected


def summarize_demographics(line_list):
    """Compute a demographic distribution summary for the line list."""
    if not line_list:
        return {}
    return {
        "age_groups":  dict(Counter(c.get("age_group") for c in line_list)),
        "sex":         dict(Counter(c.get("sex") for c in line_list)),
    }


def build_geo_payload(line_list_coords, heatmap_resolution="h3_level_8"):
    """Build a geography visualization payload for the surveillance UI.

    Production returns H3-cell counts at the configured resolution; the
    teaching example returns a placeholder.
    """
    return {"resolution": heatmap_resolution, "cell_count": len(line_list_coords)}


def lookup_lab_results_for_cases(line_list, days):
    """Look up lab results associated with cases in the line list."""
    return {
        "respiratory_panels_run":      0,
        "respiratory_panels_positive": 0,
        "panels_pending":              0,
        "novel_pathogen_signals":      0,
    }


def lookup_genomic_clusters(lab_context):
    """Look up genomic-cluster context for the cases."""
    return {
        "sequencing_in_progress":  False,
        "preliminary_clusters":    [],
        "alerting_signal":         "no_genomic_data",
    }


def build_cluster_narrative_prompt(structured_evidence):
    """Build the Bedrock prompt for cluster-narrative generation.

    Constrained: cite the structured evidence, describe the cluster,
    never assert intent or recommend an outcome. The LLM produces
    investigator-readable narrative; investigator judgment makes the
    decisions.
    """
    geos = ", ".join(f"{g['type']}={g['id']}" for g in structured_evidence["geographies"])
    syndromes = ", ".join(structured_evidence["syndromes"])
    window = (f"{structured_evidence['window'][0]} through "
              f"{structured_evidence['window'][1]}")
    obs_exp = (
        f"observed={structured_evidence['observed']:.0f}, "
        f"expected={structured_evidence['expected']:.1f}, "
        f"relative_risk={structured_evidence['relative_risk']:.2f}"
    )
    demo = json.dumps(structured_evidence["demographic_breakdown"])
    concordance = structured_evidence["multi_source_concordance"]
    concordance_text = (
        f"clinical={concordance.get('clinical_signal', 0):.2f}, "
        f"wastewater={concordance.get('wastewater_signal', 0):.2f}, "
        f"absenteeism={concordance.get('absenteeism_signal', 0):.2f}, "
        f"concordant_sources={concordance.get('concordant_source_count', 0)}"
    )

    return (
        "You are summarizing a public health outbreak-detection cluster "
        "for a surveillance epidemiologist. You are not making an "
        "outbreak determination and you are not asserting a specific "
        "pathogen. You are translating the structured evidence into a "
        "3-5 sentence investigator-readable narrative that cites the "
        "evidence and describes the spatiotemporal pattern. End with "
        "the phrase 'This is decision support; investigator judgment "
        "governs the public health response.'\n\n"
        f"Geographies: {geos}\n"
        f"Syndromes: {syndromes}\n"
        f"Window: {window}\n"
        f"Counts: {obs_exp}\n"
        f"Demographics: {demo}\n"
        f"Multi-source concordance: {concordance_text}\n\n"
        "Produce 3-5 sentences of plain narrative. No bullet points. "
        "No assertions of specific pathogens beyond what the lab and "
        "genomic context indicates. No recommended public health "
        "actions. End with the required closing phrase."
    )


def parse_bedrock_response(response):
    """Parse a Bedrock InvokeModel response into the narrative text."""
    body = json.loads(response["body"].read())
    return body["content"][0]["text"].strip()


def invoke_bedrock_narrative(structured_evidence):
    """Generate the surveillance-team-facing cluster narrative via Bedrock."""
    prompt = build_cluster_narrative_prompt(structured_evidence)
    try:
        response = bedrock_runtime.invoke_model(
            modelId=BEDROCK_MODEL_ID,
            body=json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens":        800,
                "temperature":       0.0,
                "messages":          [{"role": "user", "content": prompt}],
            }),
        )
        return parse_bedrock_response(response)
    except Exception as e:
        logger.warning("bedrock invocation failed", extra={"error": str(e)})
        _emit_metric("BedrockNarrativeFailed", 1)
        # Fall back to a structured-only summary so cluster-builder
        # doesn't fail when Bedrock is unavailable.
        return (
            f"Cluster of {structured_evidence['observed']:.0f} cases of "
            f"{', '.join(structured_evidence['syndromes'])} across "
            f"{len(structured_evidence['geographies'])} geographies "
            f"between {structured_evidence['window'][0]} and "
            f"{structured_evidence['window'][1]}. "
            f"Observed exceeds expected by a factor of "
            f"{structured_evidence['relative_risk']:.2f}. "
            "This is decision support; investigator judgment governs "
            "the public health response."
        )


def _emit_metric(metric_name, value, unit="Count"):
    """Emit a CloudWatch metric for operational monitoring."""
    try:
        cloudwatch.put_metric_data(
            Namespace="Surveillance/ClusterBuilder",
            MetricData=[{
                "MetricName": metric_name,
                "Value":      float(value),
                "Unit":       unit,
                "Timestamp":  datetime.now(timezone.utc),
            }],
        )
    except Exception as e:
        logger.debug("metric emit failed",
                     extra={"metric": metric_name, "error": str(e)})


def generate_cluster_id():
    """Generate a cluster identifier."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return f"CL-{today}-{uuid.uuid4().hex[:8]}"


def tier_from_composite(composite_score, cohort="DEFAULT"):
    """Map a composite score to a surveillance-team tier."""
    thresholds = TIER_THRESHOLDS.get(cohort, TIER_THRESHOLDS["DEFAULT"])
    if composite_score >= thresholds["tier_1"]:
        return "tier_1"
    if composite_score >= thresholds["tier_2"]:
        return "tier_2"
    if composite_score >= thresholds["tier_3"]:
        return "tier_3"
    return "below_threshold"


def build_clusters(fused_signals, reference_date):
    """Build cluster candidates, attach evidence, and persist to cluster-state."""
    proto_clusters = aggregate_adjacent_flags(
        fused_signals, temporal_window_days=CLUSTER_TEMPORAL_WINDOW
    )

    cluster_candidates = []
    for proto in proto_clusters:
        existing = find_existing_open_cluster(proto)
        if existing:
            update_existing_cluster(existing, proto)
            continue

        if check_recent_dismissal(proto, reason_class="false_alarm"):
            log_suppression(proto, reason="matches_recent_dismissal")
            continue

        line_list = line_list_build(
            proto["geographies"], proto["syndromes"],
            proto["window_start"], proto["window_end"],
        )

        observed = len(line_list)
        expected = sum_of_expected_for(
            proto["geographies"], proto["syndromes"],
            proto["window_start"], proto["window_end"],
        )
        relative_risk = observed / max(expected, 1.0)
        excess = max(0, observed - expected)

        demographic_breakdown = summarize_demographics(line_list)
        geo_visualization = build_geo_payload(
            [], heatmap_resolution="h3_level_8",
        )
        lab_context = lookup_lab_results_for_cases(line_list, days=14)
        genomic_context = lookup_genomic_clusters(lab_context)

        structured_evidence = {
            "geographies":              proto["geographies"],
            "syndromes":                proto["syndromes"],
            "window":                    (proto["window_start"], proto["window_end"]),
            "observed":                 observed,
            "expected":                 expected,
            "relative_risk":            relative_risk,
            "demographic_breakdown":    demographic_breakdown,
            "lab_context":              lab_context,
            "genomic_context":          genomic_context,
            "multi_source_concordance":  proto["signal_summary"],
        }
        narrative = invoke_bedrock_narrative(structured_evidence)
        composite_tier = tier_from_composite(proto["composite_calibrated"])

        if composite_tier == "below_threshold":
            continue

        cluster = {
            "cluster_id":             generate_cluster_id(),
            "opened_at":              datetime.now(timezone.utc).isoformat(),
            "reference_date":         reference_date.isoformat(),
            "geographies":            proto["geographies"],
            "syndromes":              proto["syndromes"],
            "window_start":           proto["window_start"],
            "window_end":             proto["window_end"],
            "observed":               observed,
            "expected":               expected,
            "relative_risk":          relative_risk,
            "excess":                 excess,
            "composite_score":        float(proto["composite_calibrated"]),
            "multi_source_concordance": proto["signal_summary"],
            "line_list_summary":      line_list_summary(line_list),
            "line_list_pointer":      persist_line_list(line_list),
            "demographic_breakdown":  demographic_breakdown,
            "geo_visualization":      geo_visualization,
            "lab_context":            lab_context,
            "genomic_context":        genomic_context,
            "narrative":              narrative,
            "tier":                   composite_tier,
            "status":                  "open_for_review",
            "assigned_to":             None,
            "outcome":                  None,
        }

        cluster_table = dynamodb.Table(CLUSTER_STATE_TABLE)
        cluster_table.put_item(Item=_decimalize(cluster))

        try:
            eventbridge.put_events(Entries=[{
                "Source":      "surveillance.cluster-builder",
                "DetailType":  "ClusterOpened",
                "Detail":      json.dumps({
                    "cluster_id":      cluster["cluster_id"],
                    "tier":            cluster["tier"],
                    "composite_score": cluster["composite_score"],
                    "geographies":     cluster["geographies"],
                    "syndromes":       cluster["syndromes"],
                }, default=str),
                "EventBusName": CLUSTER_BUS,
            }])
        except Exception as e:
            logger.debug("cluster event publish failed",
                         extra={"error": str(e)})

        _emit_metric(f"ClustersOpened_{cluster['tier']}", 1)
        cluster_candidates.append(cluster)

    return cluster_candidates
```

The cluster-grouping window (14 days by default) and the suppression-rule lifecycle are two of the more easily-undertuned operational pieces. Set the window too short and the same outbreak fragments into many clusters across days, and the surveillance team sees disconnected evidence. Set it too long and a new outbreak silently appends to an aging cluster instead of opening as a fresh investigation. Suppression rules accumulate over years; without a periodic review and renewal process the rule store either over-suppresses (concealing real signals) or under-suppresses (re-flagging known patterns). Build the audit-and-renewal process into the program from the start.

---

## Step 9: Capture Investigation Outcomes and Feed the Learning Loop

Public health epidemiologists adjudicate clusters in the surveillance UI. Outcomes flow back to update suppression rules, recalibrate fusion weights, and (when enough labels accumulate) retrain syndrome classifiers and detection models. Without this loop, the model drifts and the surveillance team eventually stops trusting the cluster queue.

```python
VALID_OUTCOMES = {
    "confirmed_outbreak",
    "false_alarm",
    "indeterminate",
    "continuing_investigation",
    "hai_cluster",
    "foodborne_cluster",
    "respiratory_pathogen",
    "sti_cluster",
    "environmental_exposure",
}

# Conditions that trigger external reporting on confirmation.
NOTIFIABLE_CONDITIONS = {
    "salmonella", "shigella", "e_coli_o157", "campylobacter", "listeria",
    "measles", "rubella", "varicella", "pertussis", "neisseria_meningitidis",
    "tuberculosis", "novel_influenza_a", "sars_cov_2_variant_of_concern",
    "hepatitis_a", "hepatitis_b_acute", "hepatitis_c_acute",
    "polio", "smallpox", "anthrax", "botulism", "tularemia", "plague",
    "viral_hemorrhagic_fever", "yellow_fever", "rabies",
}


def initiate_external_reporting(cluster):
    """Trigger external reporting (NEDSS, eCR, NORS, NHSN, NMI) for a confirmed cluster.

    Production publishes to specific EventBridge rules per reporting
    target, each with its own connector Lambda that handles the target
    system's protocol and data format. The teaching example just emits
    a generic event.
    """
    eventbridge.put_events(Entries=[{
        "Source":      "surveillance.outcome-capture",
        "DetailType":  "ExternalReportingTriggered",
        "Detail":      json.dumps({
            "cluster_id":   cluster["cluster_id"],
            "geographies":  cluster["geographies"],
            "syndromes":    cluster["syndromes"],
            "outcome":      cluster["outcome"],
            "subtype":      cluster.get("outcome_subtype"),
            "triggered_at": datetime.now(timezone.utc).isoformat(),
        }, default=str),
        "EventBusName": CLUSTER_BUS,
    }])


def notify_neighboring_jurisdictions(cluster):
    """Notify cross-jurisdictional partners about a confirmed cluster.

    Production publishes to a federated notification bus with appropriate
    data-sharing constraints based on the receiving jurisdiction's data
    use agreement. The teaching example emits a generic event.
    """
    eventbridge.put_events(Entries=[{
        "Source":      "surveillance.outcome-capture",
        "DetailType":  "CrossJurisdictionalNotification",
        "Detail":      json.dumps({
            "cluster_id":   cluster["cluster_id"],
            "geographies":  cluster["geographies"],
            "notified_at":  datetime.now(timezone.utc).isoformat(),
        }, default=str),
        "EventBusName": CLUSTER_BUS,
    }])


def initiate_response_coordination(cluster):
    """Hand off a confirmed outbreak to the response coordination workflow."""
    eventbridge.put_events(Entries=[{
        "Source":      "surveillance.outcome-capture",
        "DetailType":  "ResponseCoordinationInitiated",
        "Detail":      json.dumps({
            "cluster_id":   cluster["cluster_id"],
            "outcome":      cluster["outcome"],
            "subtype":      cluster.get("outcome_subtype"),
            "tier":         cluster["tier"],
            "started_at":   datetime.now(timezone.utc).isoformat(),
        }, default=str),
        "EventBusName": CLUSTER_BUS,
    }])


def add_suppression_rule(geographies, syndromes, reason, valid_for_days,
                          reason_class="false_alarm"):
    """Add a suppression rule so a recently-dismissed pattern doesn't re-flag."""
    suppression_table = dynamodb.Table(SUPPRESSION_RULES_TABLE)
    valid_until_dt = datetime.now(timezone.utc) + timedelta(days=valid_for_days)
    rule = {
        "rule_id":        str(uuid.uuid4()),
        "geographies":    [g["id"] for g in geographies],
        "syndromes":      list(syndromes),
        "reason":         reason,
        "reason_class":   reason_class,
        "added_at":       datetime.now(timezone.utc).isoformat(),
        "valid_until":    valid_until_dt.isoformat(),
        "ttl":            int(valid_until_dt.timestamp()),  # DynamoDB TTL
    }
    suppression_table.put_item(Item=_decimalize(rule))


def cluster_feature_snapshot(cluster):
    """Build a feature snapshot for retraining."""
    return {
        "geographies":              cluster.get("geographies"),
        "syndromes":                cluster.get("syndromes"),
        "observed":                 cluster.get("observed"),
        "expected":                 cluster.get("expected"),
        "relative_risk":            cluster.get("relative_risk"),
        "composite_score":          cluster.get("composite_score"),
        "multi_source_concordance": cluster.get("multi_source_concordance"),
        "demographic_breakdown":    cluster.get("demographic_breakdown"),
    }


def on_investigator_action(action):
    """Record an investigator's adjudication and feed the learning loop.

    action keys:
      cluster_id, outcome, outcome_subtype, notes, investigator_id,
      dismissal_reason (when outcome is false_alarm), condition (when
      outcome is confirmed_outbreak with a notifiable condition),
      crosses_jurisdictions (bool)
    """
    if action["outcome"] not in VALID_OUTCOMES:
        raise ValueError(f"invalid outcome: {action['outcome']}")

    cluster_table = dynamodb.Table(CLUSTER_STATE_TABLE)
    response = cluster_table.get_item(Key={"cluster_id": action["cluster_id"]})
    cluster = _undecimalize(response.get("Item"))
    if cluster is None:
        logger.warning("outcome for unknown cluster",
                       extra={"cluster_id": action["cluster_id"]})
        return None

    cluster["outcome"]          = action["outcome"]
    cluster["outcome_subtype"]  = action.get("outcome_subtype")
    cluster["outcome_notes"]    = action.get("notes")
    cluster["outcome_at"]       = datetime.now(timezone.utc).isoformat()
    cluster["assigned_to"]      = action["investigator_id"]
    cluster["status"] = ("active_investigation"
                          if action["outcome"] == "continuing_investigation"
                          else "closed")
    cluster["condition"] = action.get("condition")
    cluster["crosses_jurisdictions"] = action.get("crosses_jurisdictions", False)

    if action["outcome"] == "confirmed_outbreak":
        if action.get("condition") in NOTIFIABLE_CONDITIONS:
            initiate_external_reporting(cluster)
        if cluster.get("crosses_jurisdictions"):
            notify_neighboring_jurisdictions(cluster)
        initiate_response_coordination(cluster)

    if action["outcome"] == "false_alarm":
        add_suppression_rule(
            geographies=cluster.get("geographies", []),
            syndromes=cluster.get("syndromes", []),
            reason=action.get("dismissal_reason", "investigator_cleared"),
            valid_for_days=DISMISSAL_VALIDITY_PERIOD_DAYS,
            reason_class="false_alarm",
        )

    cluster_table.put_item(Item=_decimalize(cluster))

    label_record = {
        "label_id":               str(uuid.uuid4()),
        "cluster_id":             cluster["cluster_id"],
        "feature_snapshot":       cluster_feature_snapshot(cluster),
        "composite_score":        float(cluster.get("composite_score", 0.0)),
        "tier":                   cluster["tier"],
        "outcome":                cluster["outcome"],
        "outcome_subtype":        cluster.get("outcome_subtype"),
        "outcome_at":             cluster["outcome_at"],
        "time_to_adjudication_seconds": (
            (datetime.fromisoformat(cluster["outcome_at"].replace("Z", "+00:00"))
             - datetime.fromisoformat(cluster["opened_at"].replace("Z", "+00:00")))
            .total_seconds()
        ),
        "label":                  1 if cluster["outcome"] == "confirmed_outbreak" else 0,
        "investigator_id":        cluster["assigned_to"],
    }

    try:
        s3_client.put_object(
            Bucket=TRAINING_LABELS_BUCKET,
            Key=(
                f"outcomes/year={cluster['outcome_at'][:4]}/"
                f"month={cluster['outcome_at'][5:7]}/"
                f"{label_record['label_id']}.json"
            ),
            Body=json.dumps(label_record, default=str).encode("utf-8"),
            ServerSideEncryption="aws:kms",
        )
    except Exception as e:
        logger.debug("training label S3 write skipped",
                     extra={"error": str(e)})

    try:
        eventbridge.put_events(Entries=[{
            "Source":      "surveillance.outcome-capture",
            "DetailType":  "ClusterClosed",
            "Detail":      json.dumps(label_record, default=str),
            "EventBusName": CLUSTER_BUS,
        }])
    except Exception as e:
        logger.debug("cluster-closed event publish skipped",
                     extra={"error": str(e)})

    _emit_metric(f"Outcome_{cluster['outcome']}", 1)
    return label_record
```

A note on the label-derivation choice. "Confirmed_outbreak" as the positive class and everything else as negative is the simplest schema, but it hides nuance. "Indeterminate" cases are not the same as "false_alarm" cases: indeterminate means the investigator could not determine whether an outbreak occurred, which is a noisy negative for retraining. Some surveillance programs use a three-class label (positive / negative / indeterminate) and exclude indeterminate cases from the supervised retraining set. The right answer depends on the program's adjudication discipline and the volume of indeterminate cases; programs where indeterminate is a frequent verdict need to handle it explicitly rather than treating it as a negative.

---

## Full Pipeline

Now string the pieces together. In production this function does not exist as a single callable; each step runs in its own compute container, orchestrated by EventBridge fan-out for the per-event path and Step Functions for the daily detector run. The single-function version here makes the data flow visible for teaching.

```python
def seed_demo_history():
    """Pre-populate the in-memory Timestream store with synthetic baseline history.

    Production reads multi-year history from Timestream. The teaching
    example seeds a synthetic baseline (~3 cases per day with a small
    seasonal swing) so the baseline computation has something to fit.
    """
    today = datetime.now(timezone.utc).date()
    np_rng = np.random.default_rng(42)
    geo_ids = ["36055-001100", "36055-001200", "36055-001300", "36055-001400"]
    strats = ["all_ages", "age_5_17", "age_18_49"]
    syndromes = ["fever_respiratory", "ili", "gi"]
    for geo_id in geo_ids:
        for strat in strats:
            for syndrome in syndromes:
                cell = {"geo_type": "census_tract", "geo_id": geo_id,
                        "strat": strat, "syndrome": syndrome, "window": "1d"}
                pk = cell_partition_key(cell)
                # 400 days of synthetic counts: small Poisson with mild
                # weekly seasonality.
                for d in range(400, 0, -1):
                    target = today - timedelta(days=d)
                    weekly = 0.5 + 0.3 * math.sin(2 * math.pi * d / 7)
                    expected = max(2.0 + weekly, 0.5)
                    count = int(np_rng.poisson(expected))
                    for _ in range(count):
                        _IN_MEMORY_TIMESTREAM[pk].append(
                            f"{target.isoformat()}T12:00:00Z"
                        )


def seed_demo_cluster_state_tables():
    """No-op for the demo; production would create DynamoDB tables once.

    The teaching example assumes the DynamoDB tables exist and the
    in-memory stand-ins are used when the boto3 calls fail (per the
    fallback patterns earlier in this file).
    """
    pass


def run_outbreak_detection_pipeline(audit_events, reference_date):
    """End-to-end pipeline against a batch of clinical encounters.

    Returns the list of opened cluster IDs plus the per-event canonical
    records.
    """
    canonical_events = []

    print(f"[1-4/9] processing {len(audit_events)} encounters through "
          "ingest, geocode, classify, and cell-counter update")
    for raw_event in audit_events:
        ingest_result = ingest_encounter(raw_event, source_id="ed_hl7v2")
        if ingest_result.get("statusCode") != 200:
            continue

        canonical = ingest_result["canonical"]
        canonical = geocode_and_stratify(canonical)
        canonical = classify_syndrome(canonical)
        update_cell_counters(canonical)
        canonical_events.append(canonical)

    print(f"[5/9] computing per-cell baselines for reference_date={reference_date}")
    baselines = compute_baselines(reference_date)
    print(f"   computed {len(baselines)} baseline records")

    print(f"[6/9] running detector bank")
    clinical_results = run_detector_bank(reference_date)
    flagged_clinical = [r for r in clinical_results if r.get("flagged")]
    print(f"   {len(flagged_clinical)} clinical detector flags out of "
          f"{len(clinical_results)} cell-detector evaluations")

    print(f"[7/9] running auxiliary detectors and fusing signals")
    fused_signals = run_auxiliary_and_fuse(reference_date, clinical_results)
    print(f"   {len(fused_signals)} fused signal candidates")

    print(f"[8/9] building cluster candidates")
    clusters = build_clusters(fused_signals, reference_date)
    cluster_ids = [c["cluster_id"] for c in clusters]
    print(f"   {len(clusters)} clusters opened")

    print(f"[9/9] outcome capture is event-triggered; call "
          "on_investigator_action from the surveillance UI handler")

    return cluster_ids, canonical_events


if __name__ == "__main__":
    # Seed demo history so baseline fitting has data to work with.
    seed_demo_history()

    # A small batch of synthetic encounters representing the same
    # spatiotemporal cluster the recipe's sample case describes:
    # pediatric fever-respiratory cases concentrated in census tracts
    # 36055-001100 through 36055-001400 over the past few days.
    today = datetime.now(timezone.utc)
    today_iso = today.isoformat()
    encounters = []
    for i, geo in enumerate(["36055-001100", "36055-001200",
                              "36055-001300", "36055-001400"]):
        # Spike ~6 pediatric fever-respiratory encounters per tract.
        for j in range(6):
            encounters.append({
                "encounter_id":         f"ENC-{geo}-{j}",
                "patient_identifier":   f"DEMO-PT-{geo}-{j}",
                "encounter_type":       "ED",
                "facility_id":          "FAC-ROC-PEDS-1",
                "arrival_at":           today_iso,
                "chief_complaint_text": "fever and cough for 3 days, fatigue",
                "triage_note_text":      "5yo with fever 102F, persistent cough",
                "diagnosis_codes_admit": ["J06.9"],
                "diagnosis_codes_final": [],
                "age_years":             5 + j,
                "sex":                    "male" if j % 2 else "female",
                "race_ethnicity":         "unspecified",
                "patient_address":        {
                    "street": f"{100 + j} Demo St",
                    "city":   "Rochester",
                    "state":  "NY",
                    "zip":    "14620",
                },
            })

    cluster_ids, canonical = run_outbreak_detection_pipeline(
        encounters, reference_date=today.date()
    )
    print(f"\nOpened {len(cluster_ids)} cluster(s): {cluster_ids}")
    print(f"Processed {len(canonical)} canonical event(s)")
```

The output illustrates the contrast between routine activity and a flagged spatiotemporal cluster. Real workloads run thousands of encounters per minute across the state; production uses Kinesis fan-out with multiple shards rather than a Python for-loop. The function boundaries, however, do not change: ingest, geocode, classify, count, baseline, detect, fuse, cluster, capture-outcome remains the operational shape.

---

## Gap to Production

Several things would need to change before you would deploy any of this against a live public health surveillance program.

**Real HL7 v2 and FHIR ingestion.** The teaching example accepts a pre-shaped event dict. Production parses HL7 v2 ADT and ORU messages from EDs, urgent care, and hospital labs, and FHIR Encounter and Observation resources from facilities with modern integrations. Each source has its own latency, schema, and completeness characteristics. Use a maintained library (`hl7apy` or `python-hl7` for HL7 v2; `fhir.resources` for FHIR) and a real integration engine (Mirth, Rhapsody, Cloverleaf, or a vendor-supplied platform) rather than hand-rolling parsers. Plan 3-9 months of integration work per source class plus ongoing maintenance as upstream systems upgrade. Test the integration's completeness: missing encounter types, sampled feeds (some configurations sample rather than send everything), latency variability, and identifier-stability issues are common gotchas.

**Real eCR / NEDSS / NHSN / NORS / NMI integration.** Production wires bidirectional integrations with the federal and state surveillance infrastructure: eCR through the AIMS platform, NEDSS through NBS or a commercial product (Maven, Trisano), NHSN for HAI surveillance, NORS for waterborne and foodborne outbreaks, NMI for nationally notifiable conditions. Each has its own protocol, data format, and reporting cadence. Decide explicitly which cluster classes go to which target and integrate accordingly. Each integration is its own engineering project.

**Real NWSS wastewater integration.** Production pulls SARS-CoV-2, polio, influenza, and mpox concentrations from CDC NWSS plus direct-source feeds from sample-processing labs. Each lab has its own quality-control conventions; each pathogen has its own normalization conventions (against PMMoV, against population estimates, against sewershed flow rates); reporting cadence varies by program. The conversion from raw concentration to a usable surveillance signal is non-trivial; budget for the analytic work, not just the integration plumbing.

**Real Aurora PostGIS database.** Production hosts the geography hierarchy in Aurora PostgreSQL with PostGIS, with continuous updates from TIGER/Line, school-district boundary files, sewershed maps, and operational geography sources. Build the refresh pipeline; reconcile against historical baselines when boundaries change (a redrawn census tract invalidates the per-tract baseline for the affected area). The refresh cadence for boundary data is annual at minimum, more frequent for operational geographies.

**Real Timestream cell time-series.** Production stores per-cell daily counts in Amazon Timestream with multi-year retention. Tune memory-tier and magnetic-tier settings for your usage pattern: recent cell counts (last 30-60 days) need fast access for the detector bank; historical baselines (multi-year) only need to be readable during the daily baseline computation. Check the current HIPAA-eligibility status of Timestream against the AWS BAA at deployment time; some surveillance programs host the time-series in OpenSearch or Athena-over-S3 instead.

**Real SaTScan invocation.** Production runs SaTScan as a containerized AWS Batch job: stage case files and population files into S3, submit the job, parse the output. SaTScan is a compiled tool from Martin Kulldorff's group; the binary and parameter files are well-documented. Use real SaTScan for spatial and spatiotemporal scan statistics; the demo stub in this file produces simplistic clusters that miss the multiplicity-correction the real method provides.

**Real Farrington Flexible.** Production runs Farrington Flexible (Noufaily et al., 2013) using the R `surveillance` package or a Python port. The teaching example uses a simpler Poisson-GLM tail-probability stand-in. The real algorithm handles trend, seasonality, and historical-outbreak masking with more nuance than the demo.

**Real syndrome-classifier endpoint.** Production hosts a fine-tuned transformer or similar text classifier on a SageMaker real-time endpoint, with training data that includes labeled chief complaints from the local jurisdiction's EHR feeds. NSSP's syndromic categories are the starting taxonomy; organization-specific extensions (sentinel-event triggers, jurisdiction-specific concerns) add precision. Validate quarterly against a held-out labeled set; retrain on a regular cadence.

**Real Comprehend Medical NLP.** The teaching example wraps the Comprehend Medical call in a try/except and falls back to keyword matching when the API is unavailable. Production runs every encounter's chief complaint and triage note through Comprehend Medical and uses the structured entity output as input to the syndromic classifier. Confirm Comprehend Medical's HIPAA eligibility under your BAA before deployment.

**SageMaker Feature Store with point-in-time correctness.** The example does not exercise Feature Store at all. A real deployment writes feature snapshots so historical cluster rows can be reproduced exactly, which is an audit and clinical-governance requirement. Time-aware joins prevent feature leakage during retraining.

**SageMaker Model Monitor for drift and calibration tracking.** Production runs Model Monitor on the syndrome-classifier endpoint with baseline statistics from training data. Data drift (chief-complaint distribution shifts after an EHR upgrade), prediction drift (the classifier's syndrome distribution shifts even when inputs do not), and quality drift (when adjudicated outcomes catch up) all produce CloudWatch alarms that the model team triages. Calibration drift is the one that bites quietly and matters most for operational threshold tuning.

**Surveillance team UI integration.** The teaching example writes clusters to DynamoDB and OpenSearch and stops. Production publishes to ESSENCE (through NSSP/BioSense), commercial NEDSS-compatible products (Maven, Trisano), or a custom surveillance UI built on AppSync / API Gateway. Each platform has its own data model and configuration constraints. Many programs run a hybrid: ESSENCE for the bulk of standard syndromic surveillance plus AWS-native components for organization-specific patterns.

**Public health authority must be explicit.** The surveillance program must operate under a defined legal authority: state public health statute, institutional privacy authority, intergovernmental agreement, or some combination. Operating without that authority is both legally risky and operationally fragile. Coordinate with the state public health legal team before going live. For institutional surveillance (HAI cluster detection inside a hospital), the authority typically derives from the institution's privacy policy and the joint clinical-and-infection-prevention governance committee's charter.

**Cross-jurisdictional coordination must be tested before it's needed.** When an outbreak crosses jurisdictional lines, the detection system, the case-management workflow, and the public messaging all have to span jurisdictions. Tabletop the cross-jurisdictional protocols quarterly. The first time you exercise them shouldn't be the first time you need them.

**Geographic reference data is its own data engineering project.** Census tract boundaries shift with the decennial census; school district boundaries change with redistricting; sewershed boundaries are operational rather than administrative; hospital service areas evolve with merger activity. Maintain a versioned geographic-reference dataset, refresh annually, and reconcile against historical baselines when boundaries change.

**Syndrome taxonomy must be governed.** NSSP's syndromic categories are a starting point, not an end-state. Organization-specific categories (sentinel-event triggers, jurisdiction-specific concerns, emerging-pathogen categories) need explicit definition, versioning, and validation. Changes to the syndrome taxonomy invalidate historical baselines for the changed categories; plan for the recomputation cost and the operational disruption.

**Idempotency on every write.** Source feeds retry on network errors. Kinesis is at-least-once. The surveillance UI sometimes double-submits adjudications. Use `ConditionExpression` with `attribute_not_exists` on cluster creation, version counters on cluster-state updates that should overwrite by sequence, and event-id deduplication caches keyed on `event_id`. The teaching example does not handle these; production must.

**IAM scoping per component.** The encounter-ingest Lambda needs Kinesis put on the surveillance-events stream and Secrets Manager read on the source-feed credentials; it does not need Bedrock. The cluster-builder Lambda needs DynamoDB read/write on cluster-state and Bedrock invoke on the narrative model; it does not need Timestream write. Each role gets the minimum permissions for its job. Annual access review is the floor. Surveillance touches the entire population's health data; the IAM model has to reflect that.

**VPC deployment.** Lambdas, SageMaker endpoints, Bedrock invocations, Comprehend Medical calls, and Timestream queries run inside a VPC with VPC endpoints for DynamoDB, S3, Kinesis, Timestream, SageMaker Runtime, Bedrock, EventBridge, Comprehend Medical, and KMS. Source-feed integrations typically use site-to-site VPN or AWS Direct Connect; the topology depends on the source's deployment.

**KMS customer-managed keys.** Every data-at-rest store (raw events lake, cell-state table, cluster-state table, geocode-cache table, suppression-rules table, training labels bucket, OpenSearch line-list and cluster index, Timestream database, baseline store, CloudWatch Logs) is encrypted with customer-managed KMS keys scoped by role. Key policies restrict usage to the specific roles that need each key; CloudTrail data events audit the usage. Encounter payloads include PHI (patient identifiers, demographics, addresses, clinical data); all must be protected.

**Suppressed-cell rules at the publication layer.** Public-facing dashboards must not publish counts below the jurisdiction's suppression threshold (typically 5 or 10) at fine geographies, to avoid re-identification risk. The internal surveillance team has full detail; the public dashboards aggregate or suppress as required. Build suppression into the publication layer from the start; retrofitting it is painful and prone to leakage.

**Public health governance is the program.** The detection pipeline is roughly 25% of the work. The public health authority, the investigation procedures, the laboratory coordination, the cross-jurisdictional protocols, the response planning, and the public communication infrastructure are the other 75%. A pipeline without an active surveillance program, a defined investigation methodology, and a clear response chain will produce alerts that don't lead to outcomes. Build the program before the technology.

**Capacity-bounded prioritization.** The teaching example produces a cluster for every above-threshold fused signal. Production caps the daily cluster queue to the surveillance team's actual review capacity, with the next-N rows held in a backlog list that gets re-evaluated tomorrow. The metric that matters most is "the surveillance team can review the surfaced clusters without falling behind." Threshold tuning should match the team's actual throughput.

**Equity and subgroup performance audits.** Build dashboards that show flag rates, cluster-confirmation rates, and time-to-investigation by demographic group, geography, language, insurance category, and rurality. Wide variation warrants investigation. Surveillance systems that flag clusters disproportionately in some communities or under-flag in others reproduce existing inequities in care access and outbreak response. The joint governance committee reviews these monthly.

**Local validation before deployment.** Before any cluster routes to a surveillance epidemiologist, run the model in shadow mode for several weeks: scoring events, generating clusters, but not routing them to humans. Shadow clusters get reviewed retrospectively by the surveillance team lead to confirm the right clusters are being surfaced. This catches feature-pipeline bugs, calibration issues that did not show up in retrospective validation, and operational integration problems. Shadow review is also when cluster volume gets calibrated to operational capacity.

**Bedrock input and output handling.** Log the model ID, the prompt template version, and the response length. Never log the full prompt (contains structured cluster evidence with patient demographics) or the full response. Add a PHI scanner on the output path to catch accidental patient-identifier leakage if the LLM produces unexpected text; do not trust the model to be clean every time.

**Feedback loop hygiene.** The outcome-capture path writes labels. The retraining job reads them. Retraining can drift badly if labels are wrong, so audit quality monthly: sample 25 outcome events, ask the surveillance team lead whether the outcome type and the dismissal reason match their reading of the cluster, and track the disagreement rate. Over 10% disagreement and the label schema needs revisiting before the next retrain cycle.

**Monitoring and alarms.** Wire CloudWatch alarms on: end-to-end pipeline latency (encounter ingest to cluster open) p95 above target, cluster volume per investigator outside target range, dismissal rate drifting, subgroup cluster-rate ratios above fairness thresholds, Bedrock throttle rate above baseline, SageMaker endpoint p95 latency outside service-level targets, DynamoDB consumed capacity nearing provisioned, EventBridge delivery failures, and Comprehend Medical throttle rate. Page the on-call data-engineering team and the model team's lead when critical alarms fire. Page the surveillance program lead when public-health-relevant alarms fire (cluster volume crashes to zero, calibration drift above threshold, end-to-end latency way above target, source-feed completeness drops).

**Records retention and legal hold.** Surveillance data, case data, and outbreak investigation records must be retained per applicable retention policies, and may be subject to legal hold during active investigations or litigation. Public health investigation records often have multi-year retention requirements. Build retention and legal-hold capabilities into the storage layer from the start; retrofitting them later is painful. Use S3 Object Lock in COMPLIANCE mode for the surveillance archive in production; GOVERNANCE is fine for dev and test.

**Multi-AZ and disaster recovery.** Surveillance is operationally important even when not time-critical. Endpoints run multi-AZ. State tables replicate across AZs by default. The fallback during system outage is the legacy NSSP/ESSENCE process plus weekly aggregate reports from facilities. Both should be documented and exercised, because the system will be down sometime and outbreak risk doesn't pause.

**Self-monitoring of the surveillance system.** The surveillance system itself contains highly sensitive data: encounter detail, line lists, investigation histories, demographic distributions. Access to the surveillance system must be tightly controlled, fully audited, and regularly reviewed. The system should monitor itself: an investigator's access to case detail is itself an audit event, and access patterns within the surveillance system warrant the same scrutiny applied to clinical EHRs.

**Decommissioning criteria.** A model can stop working. Performance can degrade enough that it should be turned off. Decommissioning criteria (calibration drift above X, subgroup cluster-confirmation rate below Y, dismissal rate above Z) should be defined and pre-approved by the joint governance committee before deployment. Without pre-approved criteria, decommissioning becomes a political conversation rather than a public-health-effectiveness decision.

**Testing.** Table-driven unit tests on `bucket_age`, `classify_syndrome_class`, `tier_from_composite`, `compute_cusum`, `compute_ewma`, `apply_icd_rules`, `apply_entity_rules`, and `apply_lab_rules`; integration tests against DynamoDB Local and moto for the full ingest-geocode-classify-count-baseline-detect-fuse-cluster flow; golden-path regression tests on a small labeled dataset run on every retrain so a model that breaks a subgroup does not slip through.

**Cost awareness.** Kinesis ingest, Lambda compute, DynamoDB capacity, Aurora PostGIS hosting, Timestream storage, OpenSearch line-list and cluster indexes, SageMaker endpoint hosting, AWS Batch for SaTScan, Comprehend Medical calls, and Bedrock invocations are the major line items. Track cost-per-confirmed-outbreak and (where measurable) cost-per-prevented-spread alongside the public-health-cost metrics. Public health staffing (epidemiologists, investigators, communications) is the dominant program cost; one experienced epidemiologist's loaded cost can equal several months of infrastructure. The infrastructure pays for itself by detecting one or two outbreaks earlier; the cost of a delayed response (extended community spread, healthcare strain, mortality) substantially exceeds typical surveillance infrastructure costs.

None of this is unique to outbreak detection. It is the cost of running any PHI-handling, public-health-informing prediction service that influences public health decisions and breach-notification timelines at scale. The good news is that the infrastructure (event normalization, geocoding, syndromic classification, time-series feature engine, scoring endpoint, calibration layer, explanation builder, cluster builder, audit index) amortizes across Recipe 3.6 (fraud-and-abuse), 3.7 (deterioration warning), 3.8 (readmission risk), 3.9 (access anomaly), and 13.x (knowledge graphs). Build it once carefully, reuse it everywhere. The hard part is not the model. The hard part is the workflow integration, the public health governance, the surveillance team staffing, the cross-jurisdictional coordination, and the public communication infrastructure, and that part starts on day one, not after the model passes validation.

---

*← [Main Recipe 3.10](chapter03.10-epidemic-outbreak-detection) · [Chapter 3 Preface](chapter03-preface)*
