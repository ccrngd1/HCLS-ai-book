# Recipe 3.6: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 3.6. It shows one way you could translate the healthcare-fraud-waste-abuse-detection pattern into working Python using pandas and scikit-learn (for the statistics and the Isolation Forest), NetworkX (as an in-process stand-in for Amazon Neptune so the graph analytics are runnable without a Neptune cluster), Amazon DynamoDB (for the resolved-entity registry, the case state store, and the suppression registry), Amazon S3 (for the claims lake, resolved-entity snapshots, case-outcome labels, model artifacts, and subgraph exports), Amazon SageMaker Feature Store (for per-provider and per-peer-group feature vectors), Amazon EventBridge (for fan-out of flags to the evidence aggregator, notification, audit, and feedback consumers), Amazon OpenSearch Service (for the case index and subgraph search), Amazon Comprehend Medical and Amazon Bedrock (for LLM-assisted documentation review), Amazon SNS (for investigator notifications), and Amazon CloudWatch (for operational metrics). It is not production-ready. There is no real 837/835 parser (those are maintained libraries, not teaching-example code), no real LIS, PBM, or clearinghouse integration, no Neptune cluster, no Neptune ML GNN training, no CLIA/HIPAA-compliant referral packaging to OIG/CMS/state Medicaid Fraud Control Units, no investigator UI, no legal-privilege-isolated environment, and no provider appeals workflow. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you would wire into an SIU's case pipeline on Monday morning.
>
> The code maps to the nine core pseudocode steps from the main recipe: normalize a raw claim into a canonical representation, resolve providers and organizations across claims plus external reference data (NPPES, LEIE, SAM, Sunshine Act), build and refresh the relationship graph (providers, organizations, patients, claims, payments, ownerships, co-location), run the rules layer (CCI edits, MUE, exclusion checks, post-mortem billing, medical necessity gates), run the statistical layer (peer z-scores on E&M distribution and modifier rates, self-history CUSUM, multivariate Isolation Forest on provider feature vectors), run the graph analytics layer (community detection, referral concentration, ownership cascades, embedding-based similarity search), aggregate flags into per-entity case bundles with ranked evidence, run LLM-assisted documentation review, and capture case outcomes as structured labels for the retraining loop. The GNN training path, the Clean Rooms cross-payer path, and the real-time pre-payment integration from the main recipe are not in this file; they are covered in the Variations section of the main recipe and share infrastructure with other chapter recipes (3.1 for claim-level eligibility checks, 3.3 for the billing-code-drift detectors, 5.x for entity resolution, 13.x for the relationship-graph construction, 2.x for the LLM-assisted documentation review).

---

## Setup

You will need the AWS SDK for Python plus scikit-learn, pandas, numpy, and networkx for the statistics, the multivariate detector, and the in-process graph:

```bash
pip install boto3 scikit-learn pandas numpy networkx python-louvain
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchGetItem` on the `resolved-entities` and `case-state` tables
- `s3:GetObject` on the claims-lake, resolved-entities, and model-artifacts buckets, `s3:PutObject` on the case-outcomes and subgraph-artifacts buckets
- `sagemaker-featurestore-runtime:GetRecord`, `sagemaker-featurestore-runtime:BatchGetRecord`, `sagemaker-featurestore-runtime:PutRecord` on the `provider-features` and `peer-group-baselines` feature groups
- `events:PutEvents` on the `fwa-flags` and `fwa-workflow` buses
- `sns:Publish` on the investigator-notification topic
- `cloudwatch:PutMetricData` for operational metrics
- `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferICD10CM`, `comprehendmedical:InferRxNorm` for the documentation-review path
- `bedrock:InvokeModel` on the specific Bedrock model ARN you use (scope tightly; do not use `bedrock:*`)
- The OpenSearch domain policy must allow the executing role to `es:ESHttpPost` and `es:ESHttpPut` on the `fwa-cases` and `provider-embeddings` indices

Scope each role to the specific resource ARNs it touches. The permissions above are fine for learning and will fail any serious IAM review. In production, each component (claim-normalizer Lambda, entity-resolution Glue job, graph-loader EMR step, rules-engine Lambda, statistical-detector Processing job, graph-analytics Processing job, evidence-aggregator Lambda, documentation-assist Lambda, outcome-capture Lambda, retraining Step Functions workflow) gets its own role with the minimum permissions for its job.

A few things worth knowing upfront:

- **No real 837/835 or EDI parsing.** Parsing X12 837 professional/institutional claims, 835 remittance advice, and 270/271 eligibility transactions is a substantial engineering task and belongs in a maintained library (vendor toolkits from Edifecs, Availity, Change Healthcare, or open-source libraries like `pyx12`). This example starts from a claim dict in the shape produced by a normalizer. In production, a Lambda triggered by a Kinesis record or an S3 `ObjectCreated` event on the clearinghouse drop calls the parsing library and feeds the parsed claim into the normalization step.
- **NetworkX instead of Neptune, for teaching only.** The main recipe runs the graph on Amazon Neptune with billions of nodes and edges. That does not fit in a teaching example you can run in a notebook. We use `networkx` in-process so the Louvain community detection and the referral-concentration queries are visible in a handful of lines. In production, every `graph.add_node`, `graph.add_edge`, and traversal call in this file maps to a Gremlin upsert or query against Neptune, usually wrapped in `gremlinpython`. The shape of the data and the queries is identical; only the runtime changes.
- **DynamoDB table schemas.** `resolved-entities` is keyed on `canonical_id` (partition key only). `case-state` uses a composite key: `target_entity_id` (partition) and `case_id` (sort), with a GSI on `status` for the investigator queue. The main recipe also describes a `suppression-registry` table (keyed on `entity_id` partition and `rule_id` sort with TTL on `expires_at`); it is not exercised in this teaching example. You create these once, up front; this file does not do that for you.
- **All numeric values must be Decimal going into DynamoDB.** DynamoDB rejects Python `float` for numeric attributes. A dollar exposure of `287450.00` becomes `Decimal("287450.00")` on the way in and back to float on the way out. The helper functions below handle this so you see the pattern. For a fraud pipeline the precision discipline matters: a dollar exposure stored as `287449.9999999` from float drift, compared against a `100000` high-severity cut, produces the correct routing today and might not tomorrow when the threshold moves.
- **All example claim, provider, patient, and ownership data is synthetic.** NPIs, EINs, patient IDs, claim IDs, and entity IDs in the sample data are illustrative and do not refer to any real entities. CPT codes used (99213/99214/99215 for E&M, 80307 for drug testing, E1390 for oxygen concentrator DME) are real CPT/HCPCS identifiers. Use [CMS SynPUF](https://www.cms.gov/data-research/statistics-trends-and-reports/medicare-claims-synthetic-public-use-files) for synthetic Medicare claims, [Synthea](https://github.com/synthetichealth/synthea) for synthetic patient and provider data, and the public LEIE, SAM, and Open Payments downloads for reference data. Never use real PHI in a teaching example.
- **Legal privilege is not modeled here.** In production, depending on the SIU's organizational structure, the case store and subgraph exports may live in an AWS account isolated from general analytics, with access controlled by general counsel. This example keeps everything in one notional account so the code is readable.
- **LLM-assisted documentation review is a draft-generator, not a decision-maker.** The `assist_documentation_review` function produces a structured finding from Bedrock. A real deployment always routes that finding to a credentialed clinical reviewer (RN, MD, certified coder) for validation. Do not let the LLM output be the case summary that goes to legal.
- **Referral packaging to OIG/CMS/state MFCUs is out of scope.** When a confirmed case is referred to a regulator, the payload is a structured data package that meets the receiving agency's specification (often SFTP with PGP encryption, sometimes a secure web portal). That is a compliance workflow, not an ML pipeline, and this example marks where it plugs in without implementing it.

---

## Configuration and Constants

Everything that is configuration rather than logic lives here: thresholds, code maps, resource names, and lookup tables. These are the knobs that move most often between dev, test, and production, and between SIU playbook revisions. Keep them at the top of the file so a reviewer can see the levers without wading through function bodies.

```python
import hashlib
import hmac
import json
import logging
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import boto3
import networkx as nx
import numpy as np
import pandas as pd
from botocore.config import Config
from boto3.dynamodb.conditions import Key
from sklearn.ensemble import IsolationForest

# Louvain community detection. Import guarded because python-louvain is an
# optional teaching dependency. In production on Neptune, community detection
# runs as a Neptune ML algorithm or a precomputed batch job, not in-process.
try:
    import community as community_louvain  # python-louvain
    HAS_LOUVAIN = True
except ImportError:
    HAS_LOUVAIN = False

# Visible when running this file directly; Lambda configures its own handler
# and this becomes a no-op there.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# Structured logging. Ship JSON records to CloudWatch Logs Insights. Claim,
# provider, and patient data is PHI-adjacent (an NPI plus a date range plus a
# patient population is re-identifying even without names). Log structural
# metadata only. Never log full claim bodies, patient identifiers, ownership
# chains, or raw Comprehend Medical output in application logs.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry mode handles throttling across DynamoDB, OpenSearch,
# SageMaker Feature Store, Comprehend Medical, and Bedrock with exponential
# backoff and jitter. Monthly graph refresh plus daily scoring is naturally
# bursty, and adaptive mode keeps burst windows from cascading into retry
# storms. Setting a higher max on Bedrock specifically would be reasonable,
# since throttles there are model-capacity bound.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

REGION = "us-east-1"
dynamodb = boto3.resource("dynamodb", region_name=REGION, config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", region_name=REGION, config=BOTO3_RETRY_CONFIG)
cloudwatch = boto3.client("cloudwatch", region_name=REGION, config=BOTO3_RETRY_CONFIG)
sns = boto3.client("sns", region_name=REGION, config=BOTO3_RETRY_CONFIG)
eventbridge = boto3.client("events", region_name=REGION, config=BOTO3_RETRY_CONFIG)
featurestore_runtime = boto3.client(
    "sagemaker-featurestore-runtime", region_name=REGION, config=BOTO3_RETRY_CONFIG
)
comprehend_medical = boto3.client("comprehendmedical", region_name=REGION, config=BOTO3_RETRY_CONFIG)
bedrock_runtime = boto3.client("bedrock-runtime", region_name=REGION, config=BOTO3_RETRY_CONFIG)

# --- Resource Names ---
# Fill in with your actual resource names. These are placeholders.
RESOLVED_ENTITIES_TABLE = "resolved-entities"
CASE_STATE_TABLE = "case-state"
# NOTE: The suppression-registry DynamoDB table (described in the main recipe)
# is not exercised in this teaching example. The suppression workflow requires
# the case management UI to capture suppression_requested and suppression_window
# from the investigator at outcome-capture time, plus a per-flag pre-emit check
# in the rules and statistical layers. Both are out of scope for the sketchpad
# version; see the main recipe's Alert Fatigue subsection for the design.

PROVIDER_FEATURES_FG = "provider-features"
PEER_GROUP_BASELINES_FG = "peer-group-baselines"

CLAIMS_LAKE_BUCKET = "my-claims-lake"
RESOLVED_ENTITIES_BUCKET = "my-resolved-entities"
MODEL_ARTIFACTS_BUCKET = "my-fwa-model-artifacts"
CASE_OUTCOMES_BUCKET = "my-fwa-case-outcomes"
SUBGRAPH_ARTIFACTS_BUCKET = "my-fwa-subgraph-exports"

# Customer-managed KMS key ARN for the case-outcomes bucket. Separate key per
# bucket so rotation and grants can be scoped independently. The labels-bucket
# key gets stricter access policy than the general-claims-lake key because
# labels carry adjudication outcomes subject to discovery in FCA proceedings.
CASE_OUTCOMES_CMK_ARN = "arn:aws:kms:us-east-1:123456789012:key/YOUR-KEY-ID-HERE"

# Stable salt for patient-ID hashing in graph nodes. In production, load this
# from Secrets Manager at module init and rotate on a documented schedule
# (annually or per SIU policy). A static placeholder here for teaching only.
PATIENT_HASH_SALT = b"REPLACE-WITH-SECRETS-MANAGER-VALUE"

FWA_FLAGS_BUS = "fwa-flags"
FWA_WORKFLOW_BUS = "fwa-workflow"
INVESTIGATOR_NOTIFICATION_TOPIC_ARN = (
    "arn:aws:sns:us-east-1:123456789012:fwa-investigator-notifications"
)
BEDROCK_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"

# --- Thresholds ---
# These are teaching defaults. Real deployments tune them with SIU leadership
# against a labeled case stream and revisit them quarterly. A threshold too
# tight drops real cases; too loose buries investigators under noise.
PEER_ZSCORE_FLAG = 3.0                  # statistical layer flag threshold
PEER_ZSCORE_HIGH_SEVERITY = 5.0         # push to high-severity queue
CUSUM_H = 5.0                           # CUSUM decision threshold (self-history drift)
CUSUM_K = 0.5                           # CUSUM slack parameter, in standard deviations
ISOLATION_FOREST_CONTAMINATION = 0.02   # expected fraction of outlier providers
REFERRAL_CONCENTRATION_FLAG = 0.35      # > 35% of referrals to one downstream provider
HIGH_SEVERITY_EXPOSURE = Decimal("100000.00")  # dollar exposure cut for high severity
CRITICAL_EXPOSURE = Decimal("500000.00")       # dollar exposure cut for immediate escalation

# --- Code Families ---
# Real CPT/HCPCS code identifiers used illustratively. A production deployment
# loads these from the published CMS files and refreshes quarterly. Code set
# drift (ICD-10-CM annual updates in October, CPT updates in January, HCPCS
# quarterly) will silently invalidate rules that reference retired codes.
EM_OFFICE_VISIT_CODES = {"99202", "99203", "99204", "99205", "99212", "99213", "99214", "99215"}
HIGH_LEVEL_EM_CODES = {"99205", "99215"}          # level 5 E&M codes
DRUG_TEST_CODES = {"80305", "80306", "80307"}     # urine drug test code family
DME_OXYGEN_CODES = {"E1390", "E0431"}             # oxygen equipment HCPCS codes
MODIFIER_25 = "25"                                # "significant separate E&M service" modifier

# CCI (Correct Coding Initiative) edit pairs. Illustrative only. Production
# loads the full CMS NCCI PTP edit file (tens of thousands of pairs) and
# refreshes quarterly.
CCI_EDIT_PAIRS = {
    # (primary_code, secondary_code): (edit_type, default_allowed)
    ("99213", "99214"): ("mutually_exclusive", False),
    ("36415", "36416"): ("mutually_exclusive", False),
}

# MUE (Medically Unlikely Edit) thresholds per code per date of service.
# Illustrative; production loads from the CMS MUE files.
MUE_THRESHOLDS = {
    "E1390": 1,   # one oxygen concentrator per day is already generous
    "80307": 1,   # one drug screen per day
    "99213": 1,   # one level-3 E&M per patient per day
}
```

A quick note on the thresholds block. The values above are defaults chosen to make the teaching example work with a small synthetic dataset. A real deployment tunes them against a labeled backtest. The right z-score cutoff depends on the distribution of the underlying feature, and the right exposure cut depends on the SIU's investigator capacity. These are dials, not physical constants.

---

## Step 1: Normalize a Raw Claim

Claims arrive from clearinghouses in X12 837 format or from internal adjudication in proprietary formats. Before any rule or model runs, every claim is converted into a canonical representation with consistent field names and types. This step is boring and absolutely critical. If the code set version is wrong, if the modifier is a string in one feed and a list in another, or if the provider identifier is the billing NPI in one source and the rendering NPI in another, every downstream step produces garbage at scale.

```python
def _to_decimal(value, precision="0.01"):
    """Convert numeric input to Decimal for DynamoDB storage.

    DynamoDB rejects Python float for numeric attributes because float
    arithmetic introduces rounding drift that makes threshold comparisons
    unreliable over time. Always pass dollar amounts, rates, and z-scores
    through Decimal on the way in and back out.
    """
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal(precision))

def _floats_to_decimal(obj):
    """Recursively convert Python floats in a dict/list tree to Decimal.

    DynamoDB rejects Python float for numeric attributes; the resource-API
    serializer raises TypeError at put time. Apply this to any structured
    payload at the put-item boundary so flag dicts produced by sklearn or
    by Python ratio math can be persisted without per-call-site coercion.
    """
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _floats_to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_floats_to_decimal(v) for v in obj]
    return obj

def _hash_patient_id(patient_id, salt=None):
    """Stable HMAC-SHA256 hash for patient identifiers used as graph node IDs.

    The FWA graph crosses provider, payment, and ownership data with patient
    connections. An investigator (or a downstream system, or a subpoena
    response) traversing the graph should see the structural relationship,
    not a re-identifiable patient pointer. The hash is one-way for the
    pipeline's purposes; a downstream system that needs to look up the
    underlying patient (the case management UI surfacing the patient's full
    record to an investigator with appropriate access) does the reverse
    lookup through the patient master, not by reversing the hash.

    The salt must be stable across runs so the same patient produces the same
    node ID across batches; rotate on a long cadence (annually or per SIU
    policy), not per-run.
    """
    if salt is None:
        salt = PATIENT_HASH_SALT
    return hmac.new(salt, patient_id.encode("utf-8"),
                    hashlib.sha256).hexdigest()[:16]

def _redact_for_logs(canonical_claim):
    """Produce a log-safe structural summary of a claim.

    Keeps claim_id, provider_id, service_date, and CPT set. Drops patient
    identifiers, billed amounts, and diagnosis codes to minimize PHI in
    CloudWatch Logs. Full claim bodies stay in S3 under the claims lake.
    """
    return {
        "claim_id": canonical_claim.get("claim_id"),
        "rendering_provider": canonical_claim.get("rendering_provider_npi"),
        "service_date": canonical_claim.get("service_date"),
        "num_lines": len(canonical_claim.get("lines", [])),
    }

def normalize_claim(raw_claim):
    """Convert a raw payer/clearinghouse claim into the canonical shape used
    by every downstream step.

    In production, the raw_claim argument is the output of an X12 837 parser
    (for payer claims) or a native EHR/adjudication-system export. This
    example accepts a dict in the approximate shape that parser output takes
    so you can see the normalization logic without also reading a 600-page
    X12 specification.
    """
    # Normalize the service date. Timezones are the first silent bug class in
    # claims pipelines: claims span a whole day, so service_date should always
    # be a date (no time, no tz). Billing jurisdictions with business-day
    # nuances (nursing homes, inpatient) need separate handling outside scope.
    raw_date = raw_claim.get("service_date")
    if isinstance(raw_date, str):
        service_date = datetime.strptime(raw_date, "%Y-%m-%d").date().isoformat()
    elif hasattr(raw_date, "isoformat"):
        service_date = raw_date.isoformat()
    else:
        raise ValueError(f"Unparseable service_date on claim {raw_claim.get('claim_id')}")

    # Normalize line items. Each line is one procedure code plus modifiers
    # plus billed amount. The main source of error here is splitting versus
    # collapsing lines that share a code but differ in modifier, site of
    # service, or units.
    lines = []
    for raw_line in raw_claim.get("lines", []):
        code = (raw_line.get("cpt") or raw_line.get("hcpcs") or "").strip().upper()
        modifiers = raw_line.get("modifiers") or []
        if isinstance(modifiers, str):
            modifiers = [m.strip() for m in modifiers.split(",") if m.strip()]
        lines.append({
            "line_number": raw_line.get("line_number"),
            "code": code,
            "modifiers": [m.strip().upper() for m in modifiers],
            "units": int(raw_line.get("units", 1)),
            "billed_amount": _to_decimal(raw_line.get("billed_amount", 0)),
            "diagnosis_pointers": raw_line.get("diagnosis_pointers", []),
            "place_of_service": raw_line.get("place_of_service"),
        })

    canonical = {
        "claim_id": raw_claim["claim_id"],
        "claim_type": raw_claim.get("claim_type", "professional"),
        "service_date": service_date,
        "submission_date": raw_claim.get("submission_date"),
        "patient_id": raw_claim.get("patient_id"),             # internal patient ID
        "rendering_provider_npi": raw_claim.get("rendering_provider_npi"),
        "billing_provider_npi": raw_claim.get("billing_provider_npi"),
        "referring_provider_npi": raw_claim.get("referring_provider_npi"),
        "facility_npi": raw_claim.get("facility_npi"),
        "diagnosis_codes": [d.strip().upper() for d in raw_claim.get("diagnosis_codes", [])],
        "lines": lines,
        "billed_amount_total": _to_decimal(
            raw_claim.get("billed_amount_total")
            or sum((line["billed_amount"] or Decimal("0")) for line in lines)
        ),
        "paid_amount": _to_decimal(raw_claim.get("paid_amount", 0)),
        "status": raw_claim.get("status", "adjudicated"),      # adjudicated | denied | pending
        "source_system": raw_claim.get("source_system"),       # provenance for audit
        "ingestion_timestamp": datetime.now(timezone.utc).isoformat(),
    }

    logger.info(
        "claim normalized",
        extra={"event": "normalize_claim", **_redact_for_logs(canonical)},
    )
    return canonical
```

In a real deployment, `normalize_claim` runs as a Lambda triggered by S3 `ObjectCreated` events on the clearinghouse drop or Kinesis records from the internal adjudication feed. The output is written to Parquet in the canonical-claims prefix of the claims lake, and a metric is emitted for every claim type, source system, and day so data engineers see ingestion lag, parser failure rate, and silent schema drift early.

---

## Step 2: Resolve Providers and Organizations

A single physician may appear under a practice NPI at one payer, a hospital employment NPI at another, and a locum tenens arrangement at a third. Organizations show up under different EINs across state lines. Entity resolution produces a canonical ID per real-world entity so that the rest of the pipeline sees a unified provider graph rather than fragmented stub records.

```python
def _load_external_reference_data():
    """Load NPPES, LEIE, SAM, and Sunshine Act reference data.

    In production, these are downloaded monthly (NPPES and LEIE are monthly
    files; SAM is weekly; Open Payments/Sunshine Act is annual with quarterly
    refinements). A Glue job parses each file into Parquet and writes to the
    reference-data prefix of the entity-resolution pipeline's S3 bucket.

    This example returns a tiny in-memory dict so the resolve step runs.
    """
    return {
        "nppes": {
            # canonical public provider registry, keyed by NPI
            "1234567890": {
                "npi": "1234567890",
                "entity_type": "individual",
                "full_name": "Smith, John",
                "credentials": "MD",
                "primary_specialty": "Internal Medicine",
                "practice_address": "123 Main St, Austin, TX 78701",
            },
        },
        "leie": set(),  # NPIs on the HHS-OIG exclusion list
        "sam": set(),   # entity IDs debarred from federal contracting
        "sunshine_act": defaultdict(list),  # NPI -> list of industry payments
    }

def resolve_providers(claims_batch, external_reference):
    """Produce a canonical provider ID for each NPI referenced in the batch.

    This example uses a simple NPI-based lookup. A production pipeline runs a
    probabilistic match across name, address, DOB, degree, and specialty from
    NPPES plus internal provider-master records (see Recipe 5.x for the full
    matching pattern). The output is written both to a DynamoDB lookup table
    (so the online path can cache canonical IDs) and to Parquet in S3 (so
    downstream Spark jobs can join by canonical ID).
    """
    table = dynamodb.Table(RESOLVED_ENTITIES_TABLE)
    canonical_ids = {}
    exclusion_flags = []

    # Collect the unique NPIs from this batch. Rendering, billing, referring,
    # and facility NPIs all need resolution; the graph wires them with
    # different edge types.
    npis_in_batch = set()
    for claim in claims_batch:
        for role in ["rendering_provider_npi", "billing_provider_npi",
                     "referring_provider_npi", "facility_npi"]:
            if claim.get(role):
                npis_in_batch.add(claim[role])

    for npi in npis_in_batch:
        # Check the canonical cache first. In production this is either a
        # DynamoDB read (for the online path) or a broadcast join in Spark
        # (for the batch path).
        response = table.get_item(Key={"canonical_id": f"NPI:{npi}"})
        if "Item" in response:
            canonical_ids[npi] = response["Item"]["canonical_id"]
        else:
            # Not in cache. Attempt resolution against NPPES.
            nppes_record = external_reference["nppes"].get(npi)
            if nppes_record:
                canonical_id = f"NPI:{npi}"   # NPIs are globally unique, use directly
                table.put_item(Item={
                    "canonical_id": canonical_id,
                    "npi": npi,
                    "source_records": [{"source": "nppes", "record": nppes_record}],
                    "resolved_at": datetime.now(timezone.utc).isoformat(),
                })
                canonical_ids[npi] = canonical_id
            else:
                # NPI not found in NPPES. Two possibilities: the NPI is
                # invalid (typo, test data) or the NPPES refresh is stale.
                # Emit a metric and route to the entity-resolution DLQ.
                logger.warning("npi not found in nppes", extra={"npi_prefix": npi[:4]})
                canonical_ids[npi] = f"UNRESOLVED:{npi}"

        # Exclusion checks fire unconditionally. The LEIE match is a trump
        # card: any claim touching an excluded provider is invalid, period.
        if npi in external_reference["leie"]:
            exclusion_flags.append({
                "canonical_id": canonical_ids[npi],
                "exclusion_source": "LEIE",
                "severity": "critical",
            })
        if npi in external_reference["sam"]:
            exclusion_flags.append({
                "canonical_id": canonical_ids[npi],
                "exclusion_source": "SAM",
                "severity": "high",
            })

    return canonical_ids, exclusion_flags
```

The LEIE exclusion check is the simplest, highest-value rule in the entire pipeline. If a provider is on the HHS-OIG exclusion list, the provider cannot be paid by any federal program, period. A single month of paid claims to an excluded provider is a False Claims Act exposure in the millions. Treat the LEIE check as a pre-payment gate, not a post-payment detector, whenever the pipeline allows it.

---

## Step 3: Build and Refresh the Relationship Graph

The graph is the secret sauce. Rules catch individual claims and statistics catch outlier individuals; the graph catches coordinated schemes where each actor looks ordinary alone but the network between them is impossible under legitimate practice. In production this runs on Amazon Neptune. For teaching, we use NetworkX in-process.

```python
def refresh_graph(resolved_entities, claims_batch, ownership_edges=None):
    """Build or refresh the provider/patient/claim relationship graph.

    Nodes: providers, organizations, patients, claims, payments.
    Edges: rendered_by, billed_by, referred_by, rendered_at, patient_of,
           payment_for, owns (for organizational ownership), co_located_at.

    In production on Neptune, each add_node and add_edge call below maps to a
    Gremlin upsert (`.g.V().has('id', ...).fold().coalesce(...)` style) or a
    Cypher MERGE, and traversals run as long-lived gremlin or openCypher
    queries. The shape of the data and the query patterns is identical here;
    only the runtime and the scale change.
    """
    graph = nx.MultiDiGraph()

    # Provider nodes. Type annotations on nodes are essential for later
    # filtering in community detection and referral-concentration queries.
    for original_npi, canonical_id in resolved_entities.items():
        graph.add_node(canonical_id, node_type="provider", npi=original_npi)

    # Claim nodes plus the edges that link them to providers and patients.
    # Patients are a separate node type because the ownership graph does not
    # include them (patient-level privacy separation is important for legal
    # review) but the care graph does.
    for claim in claims_batch:
        claim_node = f"CLAIM:{claim['claim_id']}"
        graph.add_node(
            claim_node, node_type="claim",
            service_date=claim["service_date"],
            billed=float(claim["billed_amount_total"] or 0),
        )

        if claim.get("patient_id"):
            patient_node = f"PATIENT:{_hash_patient_id(claim['patient_id'])}"
            graph.add_node(patient_node, node_type="patient")
            graph.add_edge(patient_node, claim_node, edge_type="patient_of",
                           service_date=claim["service_date"])

        rendering = resolved_entities.get(claim.get("rendering_provider_npi"))
        if rendering:
            graph.add_edge(rendering, claim_node, edge_type="rendered_by")

        billing = resolved_entities.get(claim.get("billing_provider_npi"))
        if billing:
            graph.add_edge(billing, claim_node, edge_type="billed_by")

        referring = resolved_entities.get(claim.get("referring_provider_npi"))
        if referring and rendering and referring != rendering:
            # Referral edges are the substrate for referral-concentration
            # analytics in Step 6. Self-referrals are excluded here because
            # they look like data-entry errors more than scheme signal.
            graph.add_edge(referring, rendering, edge_type="referred_to",
                           service_date=claim["service_date"])

    # Ownership edges. In production these come from state filings, Sunshine
    # Act data, and corporate registry feeds. They are the edges that expose
    # common-ownership cascades (one LLC owning ten clinics that all refer
    # to the same DME supplier, for example).
    for edge in (ownership_edges or []):
        parent_id = edge["parent"]
        child_id = edge["child"]
        # Create endpoint nodes with node_type="organization" so the
        # OWNERSHIP_CASCADE detector in Step 6 can find them. In production,
        # entity resolution (Step 2) writes organization nodes alongside
        # providers; this branch is the teaching-example shortcut.
        if parent_id not in graph:
            graph.add_node(parent_id, node_type="organization")
        if child_id not in graph:
            graph.add_node(child_id, node_type="organization")
        graph.add_edge(parent_id, child_id, edge_type="owns",
                       percentage=edge.get("percentage"))

    logger.info("graph refreshed", extra={
        "event": "refresh_graph",
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
    })
    return graph
```

The Neptune production deployment swaps `nx.MultiDiGraph` for `GremlinClient` calls, but every function that uses the graph downstream takes `graph` as an argument, so the interface is unchanged. Writing the graph code this way (graph object in, flags out) is how you keep the teaching example portable to production without rewriting the analytics.

---

## Step 4: Run the Rules Layer

Rules catch the obvious things: CCI edit violations, medically unlikely units, post-mortem billing, services on an impossible date. Every rule carries its ID, its threshold, and the values that fired it so an investigator can defend the flag in a dispute. Rules are boring and they are the highest-precision layer of the pipeline; never skip them because ML is more exciting.

```python
def run_rules_on_claim(canonical_claim, resolved_entities, patient_vital_status=None):
    """Evaluate the rules layer against a single canonical claim.

    Returns a list of flag dicts. Each flag is explainable: rule_id, the
    values that triggered it, and a severity tier. The rule catalog grows
    with the SIU's experience; this function is a teaching subset (CCI edit,
    MUE, exclusion check, post-mortem billing, and a medical-necessity gate
    for DME). A production deployment has hundreds of rules partitioned by
    claim type and jurisdiction.
    """
    flags = []
    claim_id = canonical_claim["claim_id"]
    service_date = canonical_claim["service_date"]

    # Gather codes on this claim for CCI and MUE evaluation. A claim with
    # multiple lines of the same code is collapsed for CCI (which looks at
    # pairs) but preserved for MUE (which looks at total units).
    codes_on_claim = [line["code"] for line in canonical_claim["lines"]]
    code_counter = Counter()
    for line in canonical_claim["lines"]:
        code_counter[line["code"]] += line["units"]

    # Rule 1: CCI edits. If two mutually-exclusive codes appear on the same
    # claim without a modifier that documents the override, flag it.
    for (code_a, code_b), (edit_type, default_allowed) in CCI_EDIT_PAIRS.items():
        if code_a in codes_on_claim and code_b in codes_on_claim and not default_allowed:
            flags.append({
                "rule_id": "CCI_EDIT_MX",
                "claim_id": claim_id,
                "severity": "high",
                "details": {
                    "pair": [code_a, code_b],
                    "edit_type": edit_type,
                },
                "explain": (
                    f"Codes {code_a} and {code_b} are flagged as {edit_type} "
                    "by CMS CCI PTP edits; no overriding modifier present."
                ),
            })

    # Rule 2: Medically Unlikely Edit. If units for a code exceed the CMS MUE
    # threshold for that code, flag it. The MUE file is a hard ceiling; units
    # above the MUE are almost always data-entry errors or upcoding.
    for code, total_units in code_counter.items():
        mue = MUE_THRESHOLDS.get(code)
        if mue is not None and total_units > mue:
            flags.append({
                "rule_id": "MUE_EXCEEDED",
                "claim_id": claim_id,
                "severity": "high",
                "details": {"code": code, "units": total_units, "threshold": mue},
                "explain": (
                    f"Code {code} billed with {total_units} units on a single date of "
                    f"service (MUE threshold: {mue})."
                ),
            })

    # Rule 3: Unresolved provider role. The actual LEIE/SAM exclusion check
    # ran in Step 2 (resolve_providers returns exclusion_flags); the pipeline
    # driver concatenates those into rule_flags. Here we surface the
    # data-quality flag for any provider role that fell through entity
    # resolution, which is worth investigating separately (missing from NPPES
    # can indicate credential issues, practice closure, or data-entry errors).
    for role in ["rendering_provider_npi", "billing_provider_npi",
                 "referring_provider_npi", "facility_npi"]:
        npi = canonical_claim.get(role)
        if npi and resolved_entities.get(npi, "").startswith("UNRESOLVED:"):
            flags.append({
                "rule_id": "UNRESOLVED_PROVIDER",
                "claim_id": claim_id,
                "severity": "medium",
                "details": {"role": role, "npi_prefix": npi[:4]},
                "explain": f"Provider role {role} could not be resolved to NPPES.",
            })

    # Rule 4: Post-mortem billing. Services billed after a patient's date of
    # death are never legitimate. The date-of-death lookup comes from a
    # vital-status feed (state death-record integrations, CMS 20% sample for
    # Medicare, internal mortality data). Not every payer has this, and
    # without it this rule simply does not fire.
    if patient_vital_status and canonical_claim.get("patient_id"):
        dod = patient_vital_status.get(canonical_claim["patient_id"])
        if dod and service_date > dod:
            flags.append({
                "rule_id": "POST_MORTEM_BILLING",
                "claim_id": claim_id,
                "severity": "critical",
                "details": {"service_date": service_date, "date_of_death": dod},
                "explain": (
                    f"Service date {service_date} is after recorded date of death "
                    f"{dod}. This claim should not have been paid."
                ),
            })

    # Rule 5: Medical-necessity gate for DME oxygen (E1390/E0431). Oxygen is
    # only covered with a documented hypoxemia diagnosis. If the claim has no
    # supporting diagnosis code, flag for medical-necessity review.
    dme_oxygen_lines = [line for line in canonical_claim["lines"]
                        if line["code"] in DME_OXYGEN_CODES]
    if dme_oxygen_lines:
        hypoxemia_dx_prefix = ("J96", "J44", "J95", "R09")   # illustrative subset
        has_supporting_dx = any(
            any(dx.startswith(p) for p in hypoxemia_dx_prefix)
            for dx in canonical_claim.get("diagnosis_codes", [])
        )
        if not has_supporting_dx:
            flags.append({
                "rule_id": "MEDNEC_DME_OXYGEN",
                "claim_id": claim_id,
                "severity": "high",
                "details": {"codes": [line["code"] for line in dme_oxygen_lines]},
                "explain": (
                    "Oxygen DME billed without a documented hypoxemia diagnosis. "
                    "Requires medical-necessity review."
                ),
            })

    return flags
```

Rules are cheap to write and expensive to maintain. Every rule needs an owner, a quarterly review, and a backtest against a labeled case stream so a rule that stops catching anything (because the scheme it targeted died out) can be retired rather than firing on legitimate care and burning investigator time.

---

## Step 5: Statistical Layer

The statistical layer compares each provider to peer groups and to their own history. Peer z-scores surface providers whose coding distribution is far from specialty-and-region-matched peers. Self-history CUSUM catches a provider whose own billing pattern drifts suddenly. Isolation Forest finds multivariate outliers that no single z-score would catch.

```python
def _safe_zscore(value, peer_mean, peer_std, floor_std=0.01):
    """Compute a z-score with a floor on the standard deviation.

    Protects against divide-by-zero when a peer group is homogeneous, which
    otherwise produces spurious infinite z-scores for any nonzero deviation.
    """
    denom = max(peer_std or 0, floor_std)
    return (value - peer_mean) / denom

def _cusum(series, k, h):
    """Classic one-sided upper CUSUM.

    Returns the first index where the cumulative positive deviation from the
    reference mean exceeds h standard deviations. None if no detection.
    Tracks when a provider's own rate started drifting upward (level-5 E&M
    rate creeping up, drug-test units per patient climbing, and so on).

    NOTE: This teaching implementation uses the full series mean as the
    reference value. Production CUSUM uses an explicit baseline window (e.g.,
    the first half of the series) or a target mean from the SIU's process
    spec. The full-series-mean approach is structurally less sensitive to
    shifts because the shift itself pulls the reference up. See Recipe 3.3
    for the billing-code-drift detection pattern with an explicit baseline.
    """
    mean = np.mean(series)
    std = np.std(series) or 1.0
    c = 0.0
    for i, x in enumerate(series):
        c = max(0, c + (x - mean - k * std))
        if c > h * std:
            return i
    return None

def score_provider_statistics(provider_id, provider_features, peer_baselines):
    """Score a provider's monthly feature vector against peer baselines and
    self-history.

    Arguments:
      provider_features: dict with keys like 'level5_em_rate', 'modifier_25_rate',
                         'drug_test_units_per_patient', 'unique_patients',
                         plus 12 months of each as 'history_level5_em_rate' list.
      peer_baselines:    dict keyed by peer_group_feature_name, with 'mean' and
                         'std' entries. Loaded from Feature Store or DynamoDB.
    """
    flags = []
    peer_key = provider_features["peer_group_key"]

    # Peer z-scores across the features that matter for fraud detection.
    # These feature names are illustrative; a real production pipeline has
    # dozens of features per provider per period.
    for feature in ["level5_em_rate", "modifier_25_rate", "drug_test_units_per_patient"]:
        baseline = peer_baselines.get(f"{peer_key}:{feature}")
        if not baseline:
            continue
        z = _safe_zscore(
            provider_features[feature],
            float(baseline["mean"]),
            float(baseline["std"]),
        )
        if abs(z) >= PEER_ZSCORE_FLAG:
            severity = "high" if abs(z) >= PEER_ZSCORE_HIGH_SEVERITY else "medium"
            flags.append({
                "rule_id": f"PEER_ZSCORE_{feature.upper()}",
                "provider_id": provider_id,
                "severity": severity,
                "details": {
                    "feature": feature,
                    "value": provider_features[feature],
                    "peer_mean": float(baseline["mean"]),
                    "peer_std": float(baseline["std"]),
                    "z_score": round(z, 2),
                    "peer_group": peer_key,
                },
                "explain": (
                    f"Provider's {feature} is {round(z, 2)} standard deviations "
                    f"from peer mean in {peer_key}."
                ),
            })

    # Self-history CUSUM. Catches upward drift from the provider's own
    # baseline, which is different from being an outlier against peers
    # (a provider whose peers all upcode at the same rate as they do).
    for history_feature in ["history_level5_em_rate", "history_modifier_25_rate"]:
        series = provider_features.get(history_feature, [])
        if len(series) >= 6:
            drift_index = _cusum(series, k=CUSUM_K, h=CUSUM_H)
            if drift_index is not None:
                flags.append({
                    "rule_id": f"CUSUM_{history_feature.upper()}",
                    "provider_id": provider_id,
                    "severity": "medium",
                    "details": {
                        "feature": history_feature,
                        "drift_start_period": drift_index,
                        "series_length": len(series),
                    },
                    "explain": (
                        f"Provider's own {history_feature} began drifting upward "
                        f"at period index {drift_index}."
                    ),
                })

    return flags

def train_isolation_forest(feature_matrix):
    """Train a multivariate Isolation Forest on provider-period feature vectors.

    The training matrix contains features per provider per month: level-5 E&M
    rate, modifier-25 rate, units per patient by code family, diagnosis-code
    entropy, billed-amount per patient, and so on. In production, this is a
    SageMaker Training Job; joblib.dump the model to S3, tag the model version
    in the Model Registry, and run quarterly.
    """
    model = IsolationForest(
        n_estimators=200,
        contamination=ISOLATION_FOREST_CONTAMINATION,
        random_state=42,
    )
    model.fit(feature_matrix)
    return model

def score_isolation_forest(model, feature_matrix, provider_ids):
    """Score a batch of providers against the trained Isolation Forest.

    Returns a list of flags for providers the model identifies as outliers.
    """
    scores = model.decision_function(feature_matrix)   # higher = more normal
    predictions = model.predict(feature_matrix)        # -1 = anomaly

    flags = []
    for provider_id, score, prediction in zip(provider_ids, scores, predictions):
        if prediction == -1:
            flags.append({
                "rule_id": "ISOLATION_FOREST_OUTLIER",
                "provider_id": provider_id,
                "severity": "medium" if score > -0.1 else "high",
                "details": {"isolation_score": round(float(score), 4)},
                "explain": (
                    "Provider's multivariate feature vector is flagged as an "
                    "outlier by the Isolation Forest model. No single feature "
                    "is extreme; the combination is unusual relative to peers."
                ),
            })
    return flags
```

The Isolation Forest is intentionally the second-line detector. The z-scores are interpretable (explain to an investigator why a provider was flagged), while the Isolation Forest is opaque (a combination of features). Use the z-scores for the case summary and the Isolation Forest as a tie-breaker and a cold-start mechanism for schemes that do not show up on any single z-score.

---

## Step 6: Graph Analytics Layer

The graph layer looks for coordinated schemes: dense communities of providers who only bill to each other, referral networks with extreme concentration to a single downstream beneficiary, ownership cascades that tie ostensibly independent clinics to a common parent, and embedding-based similarity to known bad actors.

```python
def run_graph_analytics(graph):
    """Run the graph-analytics detectors against the refreshed graph.

    On Neptune, each of these is a Gremlin query or a Neptune ML graph
    algorithm invocation. Here we use NetworkX's in-memory equivalents so the
    teaching example runs in a notebook. Output shape is identical.
    """
    flags = []

    # Detector 1: Louvain community detection. Communities are dense
    # subgraphs of providers who bill, refer, and render together more than
    # the network average would predict. High-risk communities share patients
    # heavily, cross-refer in tight loops, and have elevated per-patient
    # exposure. A community alone is not fraud; a community with elevated
    # exposure against peer benchmarks is worth investigating.
    if HAS_LOUVAIN:
        provider_subgraph = graph.subgraph([
            n for n, d in graph.nodes(data=True) if d.get("node_type") == "provider"
        ]).to_undirected()
        if provider_subgraph.number_of_nodes() >= 3:
            partition = community_louvain.best_partition(provider_subgraph)
            community_sizes = Counter(partition.values())
            for community_id, size in community_sizes.items():
                if size >= 5:
                    members = [n for n, c in partition.items() if c == community_id]
                    flags.append({
                        "rule_id": "COMMUNITY_CLUSTER",
                        "severity": "medium",
                        "details": {
                            "community_id": community_id,
                            "size": size,
                            "members_sample": members[:10],
                        },
                        "explain": (
                            f"Provider community of size {size} detected by Louvain "
                            "community detection; warrants referral-pattern review."
                        ),
                    })

    # Detector 2: Referral concentration. If more than 35% of a provider's
    # outbound referrals go to a single downstream provider, flag it. Some
    # specialties legitimately have concentrated referral networks (a small-
    # town PCP with one local specialist), so this is a flag not a rule;
    # investigators validate with the local-market context.
    for provider in [n for n, d in graph.nodes(data=True) if d.get("node_type") == "provider"]:
        outbound_referrals = Counter()
        for _, target, edge_data in graph.out_edges(provider, data=True):
            if edge_data.get("edge_type") == "referred_to":
                outbound_referrals[target] += 1
        total = sum(outbound_referrals.values())
        if total >= 20:
            top_target, top_count = outbound_referrals.most_common(1)[0]
            concentration = top_count / total
            if concentration >= REFERRAL_CONCENTRATION_FLAG:
                flags.append({
                    "rule_id": "REFERRAL_CONCENTRATION",
                    "provider_id": provider,
                    "severity": "medium",
                    "details": {
                        "top_target": top_target,
                        "concentration": round(concentration, 3),
                        "total_referrals": total,
                    },
                    "explain": (
                        f"Provider sends {round(concentration*100, 1)}% of referrals "
                        f"to a single downstream provider; review for common ownership."
                    ),
                })

    # Detector 3: Ownership cascade. If a single owner controls organizations
    # that together exceed a concentration threshold in a tight referral
    # network, escalate. Computed by walking `owns` edges and aggregating
    # downstream claim exposure.
    owners = [n for n, d in graph.nodes(data=True) if d.get("node_type") == "organization"]
    for owner in owners:
        owned = [t for _, t, d in graph.out_edges(owner, data=True)
                 if d.get("edge_type") == "owns"]
        if len(owned) >= 5:
            flags.append({
                "rule_id": "OWNERSHIP_CASCADE",
                "organization_id": owner,
                "severity": "high",
                "details": {"owned_count": len(owned), "owned_sample": owned[:5]},
                "explain": (
                    f"Organization owns {len(owned)} downstream entities; "
                    "aggregate exposure review recommended."
                ),
            })

    return flags
```

On a real billion-edge graph, the Louvain partition runs as a batch Neptune ML job (not in-process) and the referral-concentration scan runs as a Gremlin query with a provider allowlist; this in-process version is a teaching surface only. The flag shape is identical between the in-process and the Neptune versions, so downstream aggregation and case assembly need no changes.

---

## Step 7: Aggregate Flags Into Cases

A case is one investigable unit of work for an SIU investigator. It bundles every flag touching a single entity (provider, organization, patient, or network) with ranked evidence, dollar exposure, and routing metadata. Without this aggregation step the investigator sees a flat list of fifty flags and has no idea which ones relate; with it they see a case that says "this provider has three statistical flags, two rules flags, and one graph flag, with $X exposure across Y claims."

```python
def _overall_severity(flag_severities):
    """Fold individual flag severities into a case-level severity.

    Critical wins. Otherwise, three or more high flags promote to critical.
    One high or any combination below that is high. Otherwise medium.
    """
    if "critical" in flag_severities:
        return "critical"
    if flag_severities.count("high") >= 3:
        return "critical"
    if "high" in flag_severities:
        return "high"
    return "medium"

def _determine_routing(severity, exposure):
    """Routing policy by case severity and dollar exposure.

    Critical cases go to the lead investigator and legal immediately.
    High-severity plus high-exposure cases go to the priority queue.
    Everything else lands in the standard queue.
    """
    if severity == "critical" or exposure >= CRITICAL_EXPOSURE:
        return {"queue": "priority", "notify": ["lead-investigator", "legal"]}
    if severity == "high" and exposure >= HIGH_SEVERITY_EXPOSURE:
        return {"queue": "priority", "notify": ["lead-investigator"]}
    return {"queue": "standard", "notify": []}

def _derive_case_id(entity_id, rule_ids, window_key):
    """Deterministic case_id so retries collapse to the same record.

    window_key is a coarse bucket like 'year=2026/week=20'. It collapses
    retries within a detection window to a single case while letting a
    week-over-week recurrence open a new case.
    """
    key_material = "|".join([
        entity_id,
        ",".join(sorted(set(rule_ids))),
        window_key,
    ])
    digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    return f"CASE:{digest[:24]}"

def aggregate_flags_to_cases(all_flags, claim_exposure_by_entity):
    """Group flags by target entity, compute case severity and exposure,
    and write case records to DynamoDB.

    all_flags: list of flag dicts from rules, stats, and graph layers.
               Each flag has an implicit or explicit target entity
               (provider_id, organization_id, or claim_id which maps back
               to a rendering provider).
    claim_exposure_by_entity: dict {entity_id -> Decimal dollar exposure}.
    """
    table = dynamodb.Table(CASE_STATE_TABLE)
    flags_by_entity = defaultdict(list)

    # Group flags by the target entity the investigator will open. Most flags
    # hang off a provider_id; some hang off an organization_id (ownership
    # cascade) or a claim_id (which we roll up to the rendering provider).
    for flag in all_flags:
        if flag.get("provider_id"):
            entity_id = flag["provider_id"]
        elif flag.get("organization_id"):
            entity_id = flag["organization_id"]
        elif flag.get("claim_id"):
            # Map the claim back to its rendering provider for case grouping.
            # In production, the flag is enriched with the rendering provider
            # canonical ID at rule-firing time so this lookup is not needed.
            entity_id = flag.get("rendering_provider_canonical_id", flag["claim_id"])
        else:
            continue
        flags_by_entity[entity_id].append(flag)

    cases_written = []
    for entity_id, flags in flags_by_entity.items():
        severities = [f["severity"] for f in flags]
        overall = _overall_severity(severities)
        exposure = claim_exposure_by_entity.get(entity_id, Decimal("0"))
        routing = _determine_routing(overall, exposure)

        # Deterministic case_id derived from entity, rules, and time window.
        # On retry (Step Functions retries a transient DynamoDB throttle), the
        # function produces the same case_id, and the ConditionExpression
        # below catches the duplicate write. This is real retry idempotency,
        # not the uuid-per-call pattern that silently creates duplicates.
        window_key = datetime.now(timezone.utc).strftime("year=%Y/week=%V")
        case_id = _derive_case_id(
            entity_id=entity_id,
            rule_ids=[f["rule_id"] for f in flags],
            window_key=window_key,
        )

        # DynamoDB rejects Python float for numeric attributes; the
        # resource-API serializer raises TypeError at put time. Coerce
        # numeric fields to Decimal at the type boundary for nested payloads
        # like evidence_summary (which contains z-scores, isolation scores,
        # and referral concentrations from sklearn and Python ratio math).
        case_record = {
            "target_entity_id": entity_id,
            "case_id": case_id,
            "status": "open",
            "severity": overall,
            "exposure_amount": _to_decimal(exposure),
            "num_flags": len(flags),
            "flag_types": sorted(set(f["rule_id"] for f in flags)),
            "evidence_summary": _floats_to_decimal(flags[:20]),
            "routing_queue": routing["queue"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "case_bundle_s3_uri": (
                f"s3://{SUBGRAPH_ARTIFACTS_BUCKET}/cases/{case_id}/bundle.json"
            ),
        }

        # ConditionExpression with a deterministic case_id means retries
        # hit the condition and fail closed. Catch the exception and treat
        # as success: the case is already there from the first attempt.
        try:
            table.put_item(
                Item=_floats_to_decimal(case_record),
                ConditionExpression="attribute_not_exists(case_id)",
            )
        except table.meta.client.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
                logger.info("case already exists; idempotent retry",
                            extra={"case_id": case_id, "entity_id": entity_id})
                continue
            raise
        cases_written.append(case_record)

        # Publish to the flags EventBridge bus so the evidence-aggregator,
        # notifier, and audit consumers can fan out without this function
        # knowing about them.
        eventbridge.put_events(Entries=[{
            "Source": "fwa.detection",
            "DetailType": "CaseCreated",
            "Detail": json.dumps({
                "case_id": case_id,
                "entity_id": entity_id,
                "severity": overall,
                "exposure_amount": str(exposure),
                "routing_queue": routing["queue"],
            }),
            "EventBusName": FWA_FLAGS_BUS,
        }])

        # High-priority cases also page the lead investigator through SNS.
        if routing["queue"] == "priority":
            sns.publish(
                TopicArn=INVESTIGATOR_NOTIFICATION_TOPIC_ARN,
                Subject=f"[{overall.upper()}] FWA Case Opened: {entity_id}",
                Message=json.dumps({
                    "case_id": case_id,
                    "entity_id": entity_id,
                    "exposure": str(exposure),
                    "flag_types": case_record["flag_types"],
                }),
            )

    _emit_metric("CasesCreated", len(cases_written))
    return cases_written

def _emit_metric(metric_name, value, unit="Count"):
    """Emit a CloudWatch metric."""
    cloudwatch.put_metric_data(
        Namespace="FWA/Detection",
        MetricData=[{
            "MetricName": metric_name,
            "Value": float(value),
            "Unit": unit,
            "Timestamp": datetime.now(timezone.utc),
        }],
    )
```

The routing function is deliberately simple. Any real SIU has a policy matrix with dozens of rules (service-line carve-outs, jurisdictional escalation paths, vendor-recovery-pool routing by payer, clinical-review branches for medical-necessity flags, and so on). Factor those into a pure function like `_determine_routing` so the policy is testable separately from the database writes and can be revised without redeploying the aggregator.

---

## Step 8: LLM-Assisted Documentation Review

For a subset of flags, an investigator benefits from a structured summary of whether the clinical documentation supports the billed services. This is a draft-generator, not a decision-maker: the LLM output goes to a credentialed clinical reviewer (RN, MD, certified coder) who decides whether the documentation actually supports the codes.

```python
def assist_documentation_review(case_id, clinical_note_text, billed_codes):
    """Produce a structured documentation-review finding for a case.

    Uses Comprehend Medical to extract entities (pre-processing, privacy-
    bounded) and Bedrock with a constrained prompt to produce the reviewer
    draft. The output is never the final case summary. It is an input to a
    human reviewer.
    """
    # Step 8a: Extract clinical entities with Comprehend Medical. This step
    # is partly privacy hygiene (we want to log what entities the LLM saw
    # without passing raw text to logs) and partly feature extraction (the
    # LLM works better when pointed at specific findings).
    entities_response = comprehend_medical.detect_entities_v2(Text=clinical_note_text)
    entities = entities_response.get("Entities", [])
    key_findings = [
        {"category": e["Category"], "type": e["Type"], "text": e["Text"]}
        for e in entities
        if e["Score"] >= 0.8
    ]

    # Step 8b: Invoke Bedrock with a constrained prompt. The system prompt
    # anchors the model to a structured output and prohibits clinical
    # recommendations. Output is a finding object, not free-text opinion.
    prompt = (
        "You are reviewing whether clinical documentation supports a set of "
        "billed procedure codes. You are not making a clinical judgment. You "
        "are identifying whether the documentation, as written, contains the "
        "elements that each code requires. Produce a JSON object with keys: "
        "\"supported_codes\" (list), \"unsupported_codes\" (list), "
        "\"ambiguous_codes\" (list), \"missing_elements\" (dict of code -> "
        "list of missing documentation elements).\n\n"
        f"Billed codes: {billed_codes}\n\n"
        f"Clinical documentation:\n{clinical_note_text}"
    )

    bedrock_response = bedrock_runtime.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2048,
            "temperature": 0.1,   # low temperature, we want structured output
            "messages": [{"role": "user", "content": prompt}],
        }),
    )

    bedrock_body = json.loads(bedrock_response["body"].read())
    model_output = bedrock_body["content"][0]["text"]

    # Attempt to parse the JSON out of the model output. Bedrock may wrap
    # the JSON in prose or code fences; defend against both.
    try:
        # Extract content between the first and last brace if prose is present.
        first = model_output.find("{")
        last = model_output.rfind("}")
        parsed = json.loads(model_output[first:last + 1]) if first >= 0 and last >= 0 else {}
    except json.JSONDecodeError:
        parsed = {"parse_error": True, "raw_output_length": len(model_output)}

    finding = {
        "case_id": case_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "key_findings_count": len(key_findings),
        "billed_codes": billed_codes,
        "reviewer_draft": parsed,
        "needs_human_review": True,   # always. never auto-close on LLM output.
    }

    logger.info("documentation review draft generated", extra={
        "event": "assist_documentation_review",
        "case_id": case_id,
        "supported_count": len(parsed.get("supported_codes", [])),
        "unsupported_count": len(parsed.get("unsupported_codes", [])),
    })
    return finding
```

Two critical design points. First, `needs_human_review` is always True; do not let a review pipeline quietly start auto-closing cases on LLM output. Second, the prompt constrains the model to a specific structured output and explicitly does not ask for a clinical judgment. The model is a documentation-element checker; the credentialed reviewer is the judge.

---

## Step 9: Capture Case Outcomes

When an investigator closes a case (confirmed, cleared, or pursued for recovery), the outcome becomes a labeled example for the retraining loop. Without this feedback, the detection models drift and the SIU's ground truth lives only in a spreadsheet somewhere.

```python
def capture_case_outcome(case_id, entity_id, outcome, recovery_amount=None, notes=None):
    """Update a case with its investigation outcome and write the label to S3
    for the retraining pipeline.

    outcome must be one of: CONFIRMED, CLEARED, PENDING_PAYER_RECOVERY,
    REFERRED_TO_REGULATOR, DUPLICATE_OF_EARLIER_CASE.
    """
    valid_outcomes = {
        "CONFIRMED", "CLEARED", "PENDING_PAYER_RECOVERY",
        "REFERRED_TO_REGULATOR", "DUPLICATE_OF_EARLIER_CASE",
    }
    if outcome not in valid_outcomes:
        raise ValueError(f"invalid outcome: {outcome}")

    # Input validation: catch obvious bad inputs before any side effects.
    if recovery_amount is not None and recovery_amount < 0:
        raise ValueError(f"recovery_amount must be non-negative; got {recovery_amount}")
    if not case_id or not case_id.startswith("CASE:"):
        raise ValueError(f"case_id must be a CASE: prefixed identifier; got {case_id!r}")
    if not entity_id:
        raise ValueError("entity_id is required")

    table = dynamodb.Table(CASE_STATE_TABLE)

    # Atomic write counter for audit. The version attribute increments on
    # every outcome write so retroactive review can tell whether the outcome
    # was overwritten and how many times. ConditionExpression ensures we never
    # write to a case that has been deleted. EventBridge at-least-once
    # delivery is fine here because outcome writes are terminal and
    # idempotent; if a real concurrent-writer scenario emerges, switch to
    # read-modify-write with a version check on the ConditionExpression.
    table.update_item(
        Key={"target_entity_id": entity_id, "case_id": case_id},
        UpdateExpression=(
            "SET #status = :status, outcome = :outcome, recovery_amount = :recovery, "
            "investigator_notes = :notes, outcome_captured_at = :ts "
            "ADD version :one"
        ),
        ExpressionAttributeNames={"#status": "status"},
        ExpressionAttributeValues={
            ":status": "closed",
            ":outcome": outcome,
            ":recovery": _to_decimal(recovery_amount or 0),
            ":notes": notes or "",
            ":ts": datetime.now(timezone.utc).isoformat(),
            ":one": 1,
        },
        ConditionExpression="attribute_exists(case_id)",
    )

    # Derive and store the label for the retraining pipeline. One label row
    # per case, with its feature-snapshot key so the training job can join
    # the label back to the exact feature vector that was scored at case
    # creation. The label derivation is organization-specific; revisit the
    # mapping with SIU leadership quarterly.
    # Date-partitioned key so Athena and Glue can prune at the partition level
    # when reading labels for retraining; case_id uniqueness inside the
    # partition is preserved by the deterministic case_id.
    decision_dt = datetime.now(timezone.utc)
    label_key = (
        f"labels/year={decision_dt.year:04d}/"
        f"month={decision_dt.month:02d}/"
        f"day={decision_dt.day:02d}/"
        f"{case_id.replace(':', '-')}.json"
    )
    label_record = {
        "case_id": case_id,
        "entity_id": entity_id,
        "label": 1 if outcome in {"CONFIRMED", "PENDING_PAYER_RECOVERY",
                                  "REFERRED_TO_REGULATOR"} else 0,
        "outcome_raw": outcome,
        "recovery_amount": str(_to_decimal(recovery_amount or 0)),
        "labeled_at": decision_dt.isoformat(),
    }
    s3_client.put_object(
        Bucket=CASE_OUTCOMES_BUCKET,
        Key=label_key,
        Body=json.dumps(label_record).encode("utf-8"),
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=CASE_OUTCOMES_CMK_ARN,
    )

    # Publish the outcome to the workflow bus. Consumers include the
    # retraining trigger, the SIU dashboard updater, and the legal-packaging
    # path for REFERRED_TO_REGULATOR.
    eventbridge.put_events(Entries=[{
        "Source": "fwa.workflow",
        "DetailType": "CaseClosed",
        "Detail": json.dumps(label_record),
        "EventBusName": FWA_WORKFLOW_BUS,
    }])

    _emit_metric("CasesClosed", 1)
    _emit_metric(f"Outcome_{outcome}", 1)
    return label_record
```

The label derivation (CONFIRMED/PENDING_PAYER_RECOVERY/REFERRED_TO_REGULATOR as positive; CLEARED/DUPLICATE as negative) is the single most important piece of business logic in the retraining loop. If the SIU changes its closure codes, the label mapping has to change with them. Audit the label distribution monthly and ask the lead investigator whether a random sample of labeled cases matches their expectation.

---

## Full Pipeline

Now string the pieces together. In production, this function does not exist as a single callable; each step runs in its own compute container, orchestrated by Step Functions with EventBridge fan-out between stages. The single-function version here makes the data flow visible for teaching.

```python
def run_fwa_pipeline(
    raw_claims_batch,
    ownership_edges=None,
    patient_vital_status=None,
    peer_baselines=None,
    isolation_forest_model=None,
):
    """End-to-end FWA detection pipeline against a batch of raw claims.

    Returns (cases_written, all_flags). Prints per-step progress so readers
    can trace the data flow.
    """
    print(f"[1/9] normalizing {len(raw_claims_batch)} claims")
    canonical_claims = [normalize_claim(raw) for raw in raw_claims_batch]

    print("[2/9] resolving providers")
    external_ref = _load_external_reference_data()
    resolved, exclusion_flags = resolve_providers(canonical_claims, external_ref)

    print("[3/9] refreshing graph")
    graph = refresh_graph(resolved, canonical_claims, ownership_edges)

    print("[4/9] running rules layer")
    rule_flags = []
    for claim in canonical_claims:
        rule_flags.extend(run_rules_on_claim(claim, resolved, patient_vital_status))
    rule_flags.extend(exclusion_flags)

    print("[5/9] running statistical layer")
    stat_flags = []
    if peer_baselines:
        # Build a per-provider monthly feature frame from the claims batch.
        # In production this is a separate Glue job; we inline a tiny version
        # for the teaching example.
        per_provider = _build_provider_features(canonical_claims)
        provider_ids = sorted(per_provider.keys())
        for pid in provider_ids:
            stat_flags.extend(score_provider_statistics(pid, per_provider[pid], peer_baselines))

        # Isolation Forest scoring if a model is loaded. In production you
        # would load this from S3 via joblib at job start.
        if isolation_forest_model is not None:
            feature_columns = ["level5_em_rate", "modifier_25_rate",
                               "drug_test_units_per_patient"]
            matrix = np.array([
                [per_provider[pid][c] for c in feature_columns]
                for pid in provider_ids
            ])
            stat_flags.extend(score_isolation_forest(isolation_forest_model, matrix, provider_ids))

    print("[6/9] running graph analytics")
    graph_flags = run_graph_analytics(graph)

    print("[7/9] aggregating flags into cases")
    all_flags = rule_flags + stat_flags + graph_flags
    exposure_by_entity = _compute_exposure(canonical_claims, resolved)
    cases = aggregate_flags_to_cases(all_flags, exposure_by_entity)

    # Steps 8 and 9 are event-triggered in production (LLM review fires from
    # the CaseCreated event; outcome capture fires from the investigator UI).
    # They are shown here as explicit calls for clarity.
    print(f"[8/9] LLM-assisted documentation review is event-triggered; "
          f"{len(cases)} cases will fan out through EventBridge")
    print("[9/9] outcome capture fires from the investigator UI; "
          "call capture_case_outcome when a case is closed")

    return cases, all_flags

def _build_provider_features(canonical_claims):
    """Compute a tiny subset of per-provider features from the claims batch.

    Real implementation uses a Glue job reading the full claims warehouse
    plus the patient master; this inline version is enough to show the
    shape.
    """
    by_provider = defaultdict(lambda: {
        "level5_claims": 0, "em_claims": 0,
        "mod25_claims": 0, "drug_test_units": 0,
        "unique_patients": set(), "peer_group_key": "internal_medicine:southwest",
        "history_level5_em_rate": [], "history_modifier_25_rate": [],
    })
    for claim in canonical_claims:
        pid = claim.get("rendering_provider_npi")
        if not pid:
            continue
        agg = by_provider[pid]
        if claim.get("patient_id"):
            agg["unique_patients"].add(claim["patient_id"])
        for line in claim["lines"]:
            if line["code"] in EM_OFFICE_VISIT_CODES:
                agg["em_claims"] += 1
                if line["code"] in HIGH_LEVEL_EM_CODES:
                    agg["level5_claims"] += 1
                if MODIFIER_25 in line["modifiers"]:
                    agg["mod25_claims"] += 1
            if line["code"] in DRUG_TEST_CODES:
                agg["drug_test_units"] += line["units"]

    for pid, agg in by_provider.items():
        em_total = max(agg["em_claims"], 1)
        agg["level5_em_rate"] = agg["level5_claims"] / em_total
        agg["modifier_25_rate"] = agg["mod25_claims"] / em_total
        agg["drug_test_units_per_patient"] = (
            agg["drug_test_units"] / max(len(agg["unique_patients"]), 1)
        )
        agg["unique_patients"] = len(agg["unique_patients"])
    return dict(by_provider)

def _compute_exposure(canonical_claims, resolved_entities):
    """Sum billed amounts by rendering-provider canonical ID for exposure."""
    exposure = defaultdict(lambda: Decimal("0"))
    for claim in canonical_claims:
        provider = resolved_entities.get(claim.get("rendering_provider_npi"))
        if provider:
            exposure[provider] += (claim.get("billed_amount_total") or Decimal("0"))
    return dict(exposure)
```

Run this end-to-end against synthetic claims from SynPUF or Synthea and you will see the full shape of the pipeline in your console. The output is a handful of cases in DynamoDB, a set of events on the flags bus, and a few metrics in CloudWatch. In production the volume is orders of magnitude larger and the compute is orders of magnitude more distributed, but the function boundaries do not change.

---

## Gap to Production

Several things would need to change before you would deploy any of this against a live claims stream.

**Real X12 837 and 835 parsing.** The example starts from a canonical claim dict. In production, the upstream integration parses X12 837 (professional and institutional claim submissions), 835 (remittance advice), and 270/271 (eligibility) messages from the clearinghouse. Use a maintained library (Edifecs, Availity, Change Healthcare vendor toolkits, or the open-source `pyx12`) rather than writing your own parser; the spec is large, the edge cases are many, and the consequences of a parser bug are silent data corruption months downstream.

**Neptune instead of NetworkX.** The graph analytics layer runs in-memory here with NetworkX, which tops out around a few million nodes on a single machine. Production on Neptune handles billions of nodes and edges, persists the graph across refresh cycles, and supports Gremlin and openCypher queries. Migrate incrementally: keep the analytic function signatures (graph in, flags out) and swap the graph backend.

**Entity resolution is a separate pipeline.** The `resolve_providers` function here does a simple NPI lookup. Real entity resolution is a probabilistic matching pipeline (Recipe 5.x) that uses name, address, DOB, credential, specialty, and historical claim patterns. A poorly-resolved provider graph dilutes every downstream signal, creates spurious ownership cascades, and produces cases against stub entities that investigators cannot actually act on. Budget this as a separate project, not a helper function.

**Idempotency everywhere.** Case creation, outcome capture, and event publishing all need to handle duplicate delivery. Use DynamoDB `ConditionExpression` with `attribute_not_exists(case_id)` on case writes (treat `ConditionalCheckFailedException` as success); use version counters plus ConditionExpression on outcome updates; deduplicate events on the consumer side using a recent-events cache keyed by event ID.

**IAM scoping.** Each pipeline component (claim-normalizer Lambda, entity-resolution Glue job, graph-loader, rules-engine, statistical-detector, graph-analytics, evidence-aggregator, documentation-assist, outcome-capture, retraining) gets its own role with minimum permissions. The documentation-assist role needs Bedrock InvokeModel on the specific model ARN; it does not need DynamoDB write access to the case table. The outcome-capture role does not need Bedrock access. Scope tightly and review roles annually; the default example-permissions list from the Setup section is for learning, not for production.

**VPC deployment.** Lambdas, Glue jobs, SageMaker Processing, and the graph-loader EMR steps run inside a VPC with VPC endpoints for DynamoDB, S3, SageMaker, Feature Store, Neptune, OpenSearch, Bedrock, Comprehend Medical, EventBridge, and KMS. SNS is an edge service that does not run inside a VPC; ensure the notification payload is minimal (case ID, severity, queue) rather than the full evidence bundle.

**KMS customer-managed keys.** Every data-at-rest store (claims lake, resolved-entities table, case-state table, feature store offline/online, case-outcomes bucket, subgraph artifacts, CloudWatch Logs, OpenSearch indices, Neptune cluster storage) is encrypted with customer-managed KMS keys scoped by role. Key policies restrict usage to the specific roles that need each key; CloudTrail data events audit the usage.

**Legal-privilege isolation.** Depending on SIU organizational structure, the case store and subgraph artifacts may need to live in an AWS account isolated from the rest of analytics, with access controlled by general counsel and audit trails separate from routine data-engineering observability. The teaching example flattens everything into one notional account; do not ship this to production without an architect conversation with legal.

**Referral packaging to regulators.** When a confirmed case is referred to OIG, CMS, or a state Medicaid Fraud Control Unit, the payload is a structured data package that meets the receiving agency's specification (often SFTP with PGP encryption, sometimes a secure web portal). Build this as a distinct workflow gated by dual approval; do not put the CaseReferred consumer directly on the workflow bus without an approval step. Getting this wrong has compliance consequences.

**LLM-assisted review is a draft, never a decision.** The `assist_documentation_review` output feeds a credentialed clinical reviewer. Enforce this at the process level (the case state machine has an explicit "clinical review" step that a reviewer signs off on) and at the UI level (the reviewer draft is labeled as such, with the reviewer's name and sign-off captured). Do not wire the LLM output directly into an auto-close path.

**Bedrock input and output handling.** Log the model ID, the prompt fingerprint (a hash of the prompt template, not the prompt itself), and the response length. Never log the full prompt (contains clinical documentation) or the full response. Add a PHI scanner on the output path to catch accidental patient-identifier leakage if the LLM hallucinates; do not trust the model to be clean every time.

**Comprehend Medical is PHI processing.** Comprehend Medical requires a HIPAA BAA with AWS (HIPAA eligibility is granted by default for Comprehend Medical; confirm your account configuration). Treat the entity output as PHI-adjacent (same sensitivity as the source text) and store it under the same KMS keys and retention policies as the claims lake itself.

**Subgroup fairness monitoring.** Build dashboards that show the case rate, confirmation rate, and dollar-recovery rate by provider specialty, region, and patient-population-served. If the pipeline disproportionately flags providers serving Medicaid or rural populations, or if confirmation rates vary systematically across specialty, that is a signal of bias in the features or the thresholds and warrants investigation before scale-out. The health equity team reviews these dashboards quarterly.

**Feedback loop hygiene.** The outcome-capture path writes labels. The retraining job reads them. Retraining can drift badly if labels are wrong, so audit quality monthly: sample 25 closed cases, ask the lead investigator whether the outcome code matches their memory of the case, and track the disagreement rate. Over 10% disagreement and the label schema needs revisiting before the next retrain cycle.

**Monitoring and alarms.** Wire CloudWatch alarms on: case-queue depth outside target range, confirmation rate drifting beyond historical bounds, subgroup case-rate ratios above fairness thresholds, Bedrock throttle rate above baseline, Neptune query latency outside service-level targets, DynamoDB consumed capacity nearing provisioned, EventBridge delivery failures. Page the on-call data-engineering team and the SIU lead when critical alarms fire.

**Retention and legal hold.** Case records, subgraph exports, label files, and raw claims all carry PHI-adjacent data. Retain for the HIPAA baseline (6 years) plus any anti-fraud retention requirements (often 7-10 years in some jurisdictions). Use S3 Object Lock in COMPLIANCE mode for the case-outcomes and subgraph-artifacts buckets in production; GOVERNANCE is fine for dev and test.

**Testing.** Table-driven unit tests on `_overall_severity`, `_determine_routing`, `_cusum`, `_safe_zscore`, and the rule functions; integration tests against DynamoDB Local and moto mocks for the full aggregation flow; golden-path regression tests on a labeled claims set run on every retrain so a model that breaks a subgroup does not slip through. The rule functions in particular are the ones that evolve fastest and benefit most from the tests.

**Cost awareness.** Neptune, Bedrock, OpenSearch, and SageMaker are the major line items. Track cost-per-confirmed-case (total monthly infrastructure cost divided by confirmed cases) alongside dollar-recovered-per-case, and watch the ratio over time. If cost-per-confirmed-case is rising faster than dollar-recovered-per-case, the model has drifted or the scheme population has changed and the detection thresholds need re-tuning. Feed this back into the routing thresholds so operations can re-balance without a code change.

None of this is unique to FWA detection. It is the cost of running any PHI-adjacent prediction service at scale. The good news is that the infrastructure (entity resolution, graph store, feature store, rules engine, case registry, event bus, human-review gate) amortizes across Recipe 3.1 (duplicate claims), 3.3 (billing-code anomalies), 3.4 (medication dispensing), 5.x (entity resolution), and the rest of the payment-integrity family. Build it once carefully, reuse it everywhere.

---

*← [Main Recipe 3.6](chapter03.06-healthcare-fraud-waste-abuse-detection) · [Chapter 3 Preface](chapter03-preface)*
