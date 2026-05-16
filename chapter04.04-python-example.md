# Recipe 4.4: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 4.4. It shows one way you could translate the wellness-program recommendation pattern into working Python using AWS Glue / Athena for eligibility filtering, Amazon SageMaker (Feature Store, Batch Transform, Training) for the model stack, Amazon DynamoDB for the program catalog and recommendation log, Amazon S3 for the data lake, AWS Step Functions for orchestration, AWS Lambda for the per-stage glue, Amazon Bedrock for outreach message tailoring, Amazon Kinesis for engagement events, and Amazon SES for outreach delivery. It is not production-ready. There is no real claims-data ingestion, no NPPES verification, no randomized-pilot infrastructure, no production propensity-score modeling, no LP-based capacity allocator, no live PCP-EHR integration, no real outcome-evaluation methodology with pre-registration. Think of it as the sketchpad version: useful for understanding the shape of an uplift-aware, capacity-aware wellness recommender, not something you'd wire into a 400,000-member health plan on Monday morning. Consider it a starting point, not a destination.
>
> The pipeline maps to the eight pseudocode steps from the main recipe: build the eligible-member list per program, score clinical need / engagement / uplift, rank per-member, allocate capacity with equity floors, enforce contact-frequency caps and consent, tailor outreach with an LLM and dispatch, capture engagement events, and run long-horizon outcome evaluation. All sample members, programs, and engagement signals are synthetic.

---

## Setup

You'll need the AWS SDK for Python and a couple of utility libraries:

```bash
pip install boto3 pandas numpy
```

For the local uplift-modeling demo (Step 2's training portion, not shown in the inference path) you'd add `econml` or `causalml`. The inference path itself only needs the SageMaker Batch Transform output, so the production Lambdas don't import those libraries.

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `sagemaker:CreateTransformJob`, `sagemaker:DescribeTransformJob` on specific model ARNs (the need scorer, per-program engagement predictors, per-program uplift estimators)
- `sagemaker:GetRecord`, `sagemaker:BatchGetRecord` on the SageMaker Feature Store feature group ARNs
- `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `dynamodb:BatchWriteItem` on the program-catalog, patient-profile, recommendation-log, engagement-events, and program-outcome-evaluations tables
- `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` on the feature-store offline bucket, the eligible-members bucket, and the scores bucket
- `athena:StartQueryExecution`, `athena:GetQueryExecution`, `athena:GetQueryResults` for the eligibility-filter pipeline
- `glue:GetTable`, `glue:GetPartitions` on the data-catalog tables Athena reads
- `bedrock:InvokeModel` on the specific outreach-tailoring model ARN (e.g., a Claude Haiku or Nova Lite model)
- `kinesis:PutRecord` on the engagement stream
- `ses:SendEmail` scoped to the BAA-covered identity (or `SendBulkEmail` for batch)
- `cloudwatch:PutMetricData` for cohort-sliced metrics
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` for CloudWatch Logs

You also need model access enabled in the Bedrock console for the outreach-tailoring step.

A few things worth knowing upfront:

- **The uplift model is the hardest part of this recipe.** This example loads a pre-trained X-learner from SageMaker; training it honestly requires either a randomized hold-out arm in a prior cycle or careful propensity-score adjustment on observational data. The training script is out of scope for this companion; the main recipe's "Why This Isn't Production-Ready" section walks through the gap.
- **Bedrock model IDs change over time.** Some regions require cross-region inference profile IDs (prefixed `us.` or `eu.`). The IDs below are reasonable defaults; verify in the Bedrock console for your region before running.
- **All members, programs, and engagement events in the example are synthetic.** Do not treat any specific member_id, program, or engagement signal as real. A production system ingests from a real claims feed and joins to real patient profiles under BAA.
- **The example collapses Step Functions, Glue, Athena, and SageMaker Batch Transform into a single Python file for readability.** In production these are separate workflow stages with their own error handling, IAM, and DLQs. Comments call out where the boundaries should fall.

---

## Configuration and Constants

Everything that's configuration rather than logic lives here. Model IDs, table names, S3 buckets, allocator policy weights, equity floors, and contact-frequency caps are the knobs you'll change between environments.

```python
import json
import logging
import time
import uuid
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, ship JSON-formatted records to
# CloudWatch Logs Insights. Never log a raw (member_id, program_id)
# join along with clinical context; the row implicitly identifies the
# member's clinical situation. The recommendation log is PHI.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles throttling from SageMaker, DynamoDB, Bedrock,
# Kinesis, S3, Athena, and SES during the weekly batch run when the
# entire eligible population (tens of thousands of members) flows
# through scoring, allocation, and outreach in a tight window.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 5, "mode": "adaptive"})

# Module-level clients. Reused across Lambda invocations in warm containers.
sagemaker_client = boto3.client("sagemaker", config=BOTO3_RETRY_CONFIG)
sagemaker_runtime = boto3.client("sagemaker-runtime", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
bedrock_runtime = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
kinesis_client = boto3.client("kinesis", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
athena_client = boto3.client("athena", config=BOTO3_RETRY_CONFIG)
cloudwatch_client = boto3.client("cloudwatch", config=BOTO3_RETRY_CONFIG)
ses_client = boto3.client("ses", config=BOTO3_RETRY_CONFIG)

# --- Model Configuration ---
# A small, fast LLM for outreach message tailoring. Haiku-class hits
# the cost target at scale; larger frontier models add cost without
# meaningfully better tailoring on this prompt shape.
OUTREACH_TAILORING_MODEL_ID = "anthropic.claude-3-5-haiku-20241022-v1:0"

# Names of the three model artifacts in SageMaker. The need scorer is
# a single multi-output model across programs. The engagement predictor
# and uplift estimator are per-program: features and outcome semantics
# differ enough between programs that one-model-per-program produces
# better calibration than a shared model with program as a feature.
NEED_MODEL_NAME = "wellness-need-scorer-v3"
ENGAGEMENT_MODEL_NAMES = {
    "prog-dpp":           "engagement-dpp-v5",
    "prog-smoking":       "engagement-smoking-v4",
    "prog-weight":        "engagement-weight-v3",
    "prog-stress":        "engagement-stress-v2",
    "prog-sleep":         "engagement-sleep-v1",
}
UPLIFT_MODEL_NAMES = {
    "prog-dpp":           "uplift-dpp-v2",
    "prog-smoking":       "uplift-smoking-v1",
    "prog-weight":        "uplift-weight-v1",
    "prog-stress":        "uplift-stress-v0",  # v0: still calibrating
    "prog-sleep":         "uplift-sleep-v0",   # v0: still calibrating
}

# --- DynamoDB Table Names ---
# Five tables. Keep them separate so access patterns stay clean and
# IAM scoping is precise:
#   1. program-catalog:               canonical program record (program_id PK)
#   2. patient-profile:               member demographics, prefs (member_id PK)
#   3. recommendation-log:            per (member, program, run_date) row
#   4. engagement-events:             raw engagement events (event_id PK)
#   5. program-outcome-evaluations:   quarterly evaluation results
PROGRAM_CATALOG_TABLE = "program-catalog"
PATIENT_PROFILE_TABLE = "patient-profile"
RECOMMENDATION_LOG_TABLE = "recommendation-log"
ENGAGEMENT_EVENTS_TABLE = "engagement-events"
OUTCOME_EVAL_TABLE = "program-outcome-evaluations"

# --- S3 Buckets and Prefixes ---
# Production: each bucket has its own KMS key and bucket policy. The
# example uses placeholder names; replace with your account's buckets.
ELIGIBLE_MEMBERS_BUCKET = "wellness-eligible-members"
SCORES_BUCKET = "wellness-scores"
FEATURE_STORE_OFFLINE_BUCKET = "wellness-feature-store-offline"
ATHENA_RESULTS_BUCKET = "wellness-athena-results"

# --- Athena ---
# Workgroup with encryption + result-location enforced. Production
# uses a dedicated workgroup per use case for cost attribution and
# query-history isolation.
ATHENA_WORKGROUP = "wellness-recommender"
ATHENA_DATABASE = "wellness_data_lake"

# --- Kinesis ---
# Engagement stream pattern reused from Recipes 4.1 / 4.2 / 4.3, with
# new event types: program_recommended, program_outreach_sent,
# program_outreach_opened, program_enrolled, program_session_attended,
# program_completed, program_dropped_out, pcp_override.
ENGAGEMENT_STREAM_NAME = "engagement-stream"

# --- SES ---
# Identity must be verified and inside the BAA-covered configuration set.
SES_FROM_ADDRESS = "wellness@example-health-plan.org"
SES_CONFIGURATION_SET = "wellness-baa"

# --- Allocator Policy Weights ---
# Documented, version-controlled, reviewable. The weights are policy,
# not data-science output: they encode the trade-off between clinical
# need (more equity-oriented), engagement likelihood (more conversion-
# oriented), and uplift (causally-oriented). A cross-functional review
# sets these.
POLICY_WEIGHTS = {
    "need":       0.30,
    "engagement": 0.20,
    "uplift":     0.50,
}

# --- Equity Floors per Program ---
# Capacity reserved for cohorts that uplift-only optimization would
# under-target. Example: reserve 20 of DPP's 200 seats for the lowest
# engagement-history quartile, and 10 for limited-English-proficiency
# members. Calibrated quarterly by network operations + equity lead.
EQUITY_FLOORS = {
    "prog-dpp": {
        "engagement_q1":            20,   # lowest engagement-history quartile
        "language_non_en":          10,   # non-English preferred language
    },
    "prog-smoking": {
        "engagement_q1":            15,
        "sdoh_low_food_security":   10,
    },
    "prog-weight": {
        "engagement_q1":            10,
    },
    "prog-stress": {},
    "prog-sleep":  {},
}

# --- Contact-Frequency Caps ---
# Per-month limits across all wellness outreach (and total outreach,
# which spans 4.1 reminders, 4.2 education, 4.4 wellness, 4.5
# adherence). Calibrated by member-services + UX research; tighter
# than you think you need.
MAX_WELLNESS_PER_MONTH = 2
MAX_TOTAL_PER_MONTH = 4

# --- Run Configuration ---
# The run_date stamp is on every artifact for traceability. The
# policy_version stamp is on the recommendation log so back-catalog
# analysis can segment by policy.
POLICY_VERSION = "wellness-policy-v0.4"

# CloudWatch namespace for wellness metrics. Slice by program,
# language, engagement-history quartile, and SDOH cohort to catch
# subgroup drift.
METRIC_NAMESPACE = "WellnessRecommender"
```

---

## Reference Data: Synthetic Program Catalog

A small program catalog used by the example. Production loads from the program-catalog DynamoDB table, which is fed by vendor-portal integrations and a clinical/contracting review. Each program's `eligibility_criteria` is what Step 1 compiles into a SQL query against the data lake.

```python
# Synthetic program catalog. In production this lives in DynamoDB and
# is updated by the catalog-sync Lambda when vendors push catalog
# changes through EventBridge.
SAMPLE_PROGRAMS = [
    {
        "program_id":           "prog-dpp",
        "display_name":         "Diabetes Prevention Program",
        "public_summary":       "A 12-month CDC-recognized program with a coach focused on lifestyle changes that lower diabetes risk.",
        "time_commitment":      "12 months: 16 weekly core sessions, then monthly post-core sessions",
        "capacity":             200,    # seats per cohort cycle
        "min_cohort_size":      40,
        "cohort_cadence":       "monthly",
        "next_cohort_start":    "2026-06-01",
        "eligibility_criteria": {
            "hba1c_min":              5.7,
            "hba1c_max":              6.4,
            "hba1c_window_days":      365,
            "bmi_min":                25.0,
            "age_min":                18,
            "age_max":                75,
            "exclude_diagnosis_codes": ["E11", "E10"],   # exclude existing diabetes
        },
        "exclusion_rules": {
            "currently_in_program":   "prog-dpp",
            "recent_disenroll_months": 6,
        },
        "default_template":     "dpp-default-en",
        "pcp_alert_enabled":    True,
        "outcome_definitions": {
            "primary_outcome":    "hba1c_change_at_12_months",
            "secondary_outcomes": ["bmi_change_at_12_months", "weight_change_at_12_months"],
        },
        "eval_method":          "propensity_matched_difference_in_differences",
    },
    {
        "program_id":           "prog-smoking",
        "display_name":         "Smoking Cessation Program",
        "public_summary":       "A telephonic coaching program with optional nicotine replacement support.",
        "time_commitment":      "8 weeks, weekly coaching calls",
        "capacity":             150,
        "min_cohort_size":      20,
        "cohort_cadence":       "weekly",   # rolling enrollment
        "next_cohort_start":    "2026-05-19",
        "eligibility_criteria": {
            "smoking_status_active":  True,
            "age_min":                18,
            "age_max":                90,
        },
        "exclusion_rules": {
            "currently_in_program":   "prog-smoking",
            "recent_disenroll_months": 3,
        },
        "default_template":     "smoking-default-en",
        "pcp_alert_enabled":    True,
        "outcome_definitions": {
            "primary_outcome":    "smoking_quit_at_6_months",
            "secondary_outcomes": ["smoking_quit_at_12_months"],
        },
        "eval_method":          "propensity_matched_difference_in_differences",
    },
    {
        "program_id":           "prog-weight",
        "display_name":         "Weight Management Program",
        "public_summary":       "An app-based program with weekly group sessions focused on sustainable weight loss.",
        "time_commitment":      "12 weeks, app-based plus weekly group session",
        "capacity":             300,
        "min_cohort_size":      50,
        "cohort_cadence":       "monthly",
        "next_cohort_start":    "2026-06-01",
        "eligibility_criteria": {
            "bmi_min":                30.0,
            "age_min":                18,
            "age_max":                85,
        },
        "exclusion_rules": {
            "currently_in_program":   "prog-weight",
            "recent_disenroll_months": 6,
        },
        "default_template":     "weight-default-en",
        "pcp_alert_enabled":    False,
        "outcome_definitions": {
            "primary_outcome":    "weight_change_at_12_months",
            "secondary_outcomes": ["bmi_change_at_12_months"],
        },
        "eval_method":          "propensity_matched_difference_in_differences",
    },
]
```

---

## Shared Helpers

A handful of utilities used across steps. Pulled together here so each step's logic stays focused.

```python
def _now_iso() -> str:
    """Current UTC timestamp in ISO 8601 format."""
    return datetime.datetime.now(timezone.utc).isoformat()


def _today_str() -> str:
    """Current UTC date as YYYY-MM-DD string for run_date."""
    return datetime.datetime.now(timezone.utc).date().isoformat()


def _emit_metric(name: str, value: float, dimensions: dict) -> None:
    """
    Emit a CloudWatch custom metric. Swallows errors so a metric-publish
    failure never breaks the recommendation pipeline. CloudWatch metric
    publishing is best-effort observability, not a correctness boundary.
    """
    try:
        cloudwatch_client.put_metric_data(
            Namespace=METRIC_NAMESPACE,
            MetricData=[{
                "MetricName": name,
                "Dimensions": [
                    {"Name": k, "Value": str(v)[:255]} for k, v in dimensions.items()
                ],
                "Value": float(value),
                "Unit":  "Count",
            }],
        )
    except Exception as exc:
        logger.warning("Metric publish failed for %s: %s", name, exc)


def _to_decimal(value) -> Decimal:
    """
    DynamoDB does not accept Python floats. Going through str avoids
    binary-precision issues. Wrap floats at the persistence boundary
    and forget about it.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _from_decimal(value):
    """Inverse of _to_decimal for reading DynamoDB items into Python."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _from_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_decimal(v) for v in value]
    return value
```

---

## Step 1: Build the Eligible-Member List Per Program

*The pseudocode calls this `build_eligible_member_lists(programs, run_date)`. For each program, compile its structured eligibility criteria into a SQL query against the data lake (claims, EHR-derived facts, HRA, prior wellness participation), run the query through Athena, and write the resulting eligible-member list to S3 partitioned by run_date and program_id. The result is the input to every downstream stage; an over-broad eligibility filter wastes scoring compute, an over-narrow one quietly excludes members who would have benefited.*

```python
def build_eligible_member_lists(programs: list, run_date: str) -> dict:
    """
    Run per-program eligibility queries against the data lake.

    Returns a dict mapping program_id to the S3 path of the eligible-
    member list parquet file. Each per-program list has at least the
    member_id column; production lists carry through the criteria-
    matching values (e.g., the actual HbA1c reading) for downstream
    auditing and explanation.
    """
    eligible_paths = {}
    for program in programs:
        program_id = program["program_id"]
        sql = _build_eligibility_sql(program)
        logger.info("Running eligibility query for %s", program_id)

        # Start the Athena query. The example waits synchronously so
        # the demo is easy to read; production runs Athena queries in
        # parallel inside a Step Functions Map state and waits on all
        # of them before advancing to scoring.
        execution = athena_client.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": ATHENA_DATABASE},
            WorkGroup=ATHENA_WORKGROUP,
            ResultConfiguration={
                "OutputLocation": f"s3://{ATHENA_RESULTS_BUCKET}/eligibility/{run_date}/",
            },
        )
        query_execution_id = execution["QueryExecutionId"]
        _wait_for_athena_query(query_execution_id, timeout_seconds=300)

        # Athena writes the result CSV to the OutputLocation. The
        # example references that location directly; production
        # converts it to parquet via a Glue job for cheaper downstream
        # reads. Treat this CSV-to-parquet conversion as part of the
        # eligibility stage, not as ad-hoc data wrangling.
        results_path = f"s3://{ATHENA_RESULTS_BUCKET}/eligibility/{run_date}/{query_execution_id}.csv"

        # Persist the eligible-member list at a stable location keyed
        # on (run_date, program_id) so downstream stages don't need
        # to know the Athena execution_id.
        stable_path = (
            f"s3://{ELIGIBLE_MEMBERS_BUCKET}/run_date={run_date}/"
            f"program={program_id}/members.csv"
        )
        _copy_s3_object(results_path, stable_path)

        eligible_paths[program_id] = stable_path

        # Count eligible members for the metric. Production reads
        # the row count from Athena's GetQueryRuntimeStatistics rather
        # than re-scanning the file.
        eligible_count = _count_athena_result_rows(query_execution_id)
        _emit_metric(
            "eligibility_filter_applied",
            value=eligible_count,
            dimensions={
                "program_id": program_id,
                "run_date":   run_date,
            },
        )
        logger.info(
            "Eligibility complete for %s: %d members at %s",
            program_id, eligible_count, stable_path,
        )

    return eligible_paths


def _build_eligibility_sql(program: dict) -> str:
    """
    Compile structured eligibility criteria into a parameterized SQL
    query against the data lake.

    Production: use a query template engine (Jinja, sqlglot) and pass
    parameters through Athena's parameterized query API. The string-
    concatenation approach below is for clarity in the example; never
    do this with untrusted input.
    """
    criteria = program["eligibility_criteria"]
    exclusions = program.get("exclusion_rules", {})

    # Build the WHERE clauses. Each criterion that's None or absent
    # is skipped; only present criteria become predicates.
    where_clauses = [
        # Hard hygiene: only members on an active plan with active
        # wellness consent. These are correctness boundaries, not
        # tunable thresholds.
        "p.plan_active = TRUE",
        "p.wellness_consent_active = TRUE",
    ]

    if "hba1c_min" in criteria:
        where_clauses.append(
            f"l.latest_hba1c BETWEEN {criteria['hba1c_min']} AND {criteria['hba1c_max']}"
        )
        where_clauses.append(
            f"date_diff('day', l.latest_hba1c_date, current_date) "
            f"<= {criteria.get('hba1c_window_days', 365)}"
        )
    if "bmi_min" in criteria:
        where_clauses.append(f"v.latest_bmi >= {criteria['bmi_min']}")
    if criteria.get("smoking_status_active"):
        where_clauses.append("p.smoking_status_active = TRUE")
    if "age_min" in criteria:
        where_clauses.append(f"p.age BETWEEN {criteria['age_min']} AND {criteria['age_max']}")
    if "exclude_diagnosis_codes" in criteria:
        codes_quoted = ", ".join(f"'{c}'" for c in criteria["exclude_diagnosis_codes"])
        where_clauses.append(
            f"NOT EXISTS (SELECT 1 FROM dx d "
            f"WHERE d.member_id = p.member_id "
            f"AND d.icd10_prefix IN ({codes_quoted}))"
        )

    # Exclusions: members currently in this program or recently
    # disenrolled don't get re-recommended. This is the second-most-
    # common reason production recommenders surface members who
    # complain "I just did this program."
    program_id = program["program_id"]
    where_clauses.append(
        f"NOT EXISTS (SELECT 1 FROM enrollments e "
        f"WHERE e.member_id = p.member_id "
        f"AND e.program_id = '{program_id}' "
        f"AND e.status IN ('active', 'completed'))"
    )
    recent_months = exclusions.get("recent_disenroll_months", 6)
    where_clauses.append(
        f"NOT EXISTS (SELECT 1 FROM enrollments e "
        f"WHERE e.member_id = p.member_id "
        f"AND e.program_id = '{program_id}' "
        f"AND e.disenroll_date >= date_add('month', -{recent_months}, current_date))"
    )

    where_sql = " AND ".join(where_clauses)
    return f"""
        SELECT p.member_id
        FROM patient_summary p
        LEFT JOIN latest_labs l ON l.member_id = p.member_id
        LEFT JOIN latest_vitals v ON v.member_id = p.member_id
        WHERE {where_sql}
    """.strip()


def _wait_for_athena_query(execution_id: str, timeout_seconds: int = 300) -> None:
    """Poll Athena until the query reaches a terminal state."""
    start = time.time()
    while True:
        response = athena_client.get_query_execution(QueryExecutionId=execution_id)
        state = response["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            return
        if state in ("FAILED", "CANCELLED"):
            reason = response["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena query {execution_id} {state}: {reason}")
        if time.time() - start > timeout_seconds:
            raise TimeoutError(f"Athena query {execution_id} timed out after {timeout_seconds}s")
        time.sleep(2)


def _count_athena_result_rows(execution_id: str) -> int:
    """Read the row count from Athena's runtime statistics."""
    try:
        response = athena_client.get_query_runtime_statistics(QueryExecutionId=execution_id)
        return int(response["QueryRuntimeStatistics"]["Rows"]["OutputRows"])
    except Exception:
        return 0


def _copy_s3_object(src_uri: str, dst_uri: str) -> None:
    """Copy an S3 object from one URI to another. Production uses
    Athena CTAS into the destination bucket directly; the example
    keeps it simple."""
    src_bucket, src_key = _parse_s3_uri(src_uri)
    dst_bucket, dst_key = _parse_s3_uri(dst_uri)
    s3_client.copy_object(
        Bucket=dst_bucket,
        Key=dst_key,
        CopySource={"Bucket": src_bucket, "Key": src_key},
        ServerSideEncryption="aws:kms",
    )


def _parse_s3_uri(uri: str) -> tuple:
    if not uri.startswith("s3://"):
        raise ValueError(f"Not an S3 URI: {uri}")
    parts = uri[5:].split("/", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""
```

---

## Step 2: Score Clinical Need, Engagement, and Uplift

*The pseudocode calls this `score_eligible_population(programs, run_date)`. Three SageMaker Batch Transform jobs run per program: the multi-output need scorer (single model, scoring all programs at once), the per-program engagement predictor, and the per-program uplift estimator. Each job reads the eligible-member list from S3, joins per-member features from the SageMaker Feature Store at job time, scores, and writes per-program scores back to S3. The need score is consistent across programs; engagement and uplift are program-specific by design.*

```python
def score_eligible_population(
    programs: list,
    run_date: str,
    eligible_paths: dict,
) -> dict:
    """
    Launch Batch Transform jobs for need / engagement / uplift per
    program. Wait for all to complete, then return the consolidated
    scores S3 path.

    Returns a dict with the per-program output paths and the
    consolidated all-scores path.
    """
    # Track every job we kick off so we can wait on them in parallel.
    in_flight = []

    for program in programs:
        program_id = program["program_id"]
        eligible_uri = eligible_paths[program_id]

        # Need score (one model across all programs; we slice the
        # output column for this program). The example treats it as
        # a per-program job for symmetry; production runs it once
        # across the union of eligible members.
        need_job_name = f"need-{program_id}-{run_date}"
        need_output = (
            f"s3://{SCORES_BUCKET}/run_date={run_date}/"
            f"program={program_id}/need/"
        )
        _start_batch_transform(
            job_name=need_job_name,
            model_name=NEED_MODEL_NAME,
            input_uri=eligible_uri,
            output_uri=need_output,
            run_date=run_date,
            job_kind="need",
            instance_type="ml.m5.large",
        )
        in_flight.append((need_job_name, "need", program_id, need_output))

        # Engagement predictor: per-program. The features that predict
        # DPP enrollment differ from those that predict smoking
        # cessation enrollment, so each program has its own model.
        eng_model = ENGAGEMENT_MODEL_NAMES.get(program_id)
        if eng_model:
            eng_job_name = f"eng-{program_id}-{run_date}"
            eng_output = (
                f"s3://{SCORES_BUCKET}/run_date={run_date}/"
                f"program={program_id}/engagement/"
            )
            _start_batch_transform(
                job_name=eng_job_name,
                model_name=eng_model,
                input_uri=eligible_uri,
                output_uri=eng_output,
                run_date=run_date,
                job_kind="engagement",
                instance_type="ml.m5.large",
            )
            in_flight.append((eng_job_name, "engagement", program_id, eng_output))

        # Uplift estimator: per-program. This is the hardest model in
        # the stack: it needs treated/control training data, ideally
        # from a randomized hold-out arm. Programs whose model version
        # is "v0" are still calibrating; the recommendation log notes
        # this so downstream consumers know the uplift is provisional.
        uplift_model = UPLIFT_MODEL_NAMES.get(program_id)
        if uplift_model:
            uplift_job_name = f"uplift-{program_id}-{run_date}"
            uplift_output = (
                f"s3://{SCORES_BUCKET}/run_date={run_date}/"
                f"program={program_id}/uplift/"
            )
            _start_batch_transform(
                job_name=uplift_job_name,
                model_name=uplift_model,
                input_uri=eligible_uri,
                output_uri=uplift_output,
                run_date=run_date,
                job_kind="uplift",
                # Causal forests are heavier than gradient-boosted
                # classifiers; bump the instance size.
                instance_type="ml.m5.xlarge",
            )
            in_flight.append((uplift_job_name, "uplift", program_id, uplift_output))

    # Wait for all jobs. Production parallelizes this with Step
    # Functions Map states; the synchronous loop here is for clarity.
    output_paths = {}
    for job_name, kind, program_id, out_uri in in_flight:
        _wait_for_transform_job(job_name)
        output_paths.setdefault(program_id, {})[kind] = out_uri
        logger.info("Batch Transform %s finished: %s", job_name, out_uri)

    # Consolidate the per-program score files into a single table the
    # ranking step consumes. Production does this with a Glue job that
    # writes parquet; the example function below reads the CSVs and
    # produces a single consolidated CSV.
    consolidated_uri = _consolidate_scores(programs, run_date, output_paths)
    return {
        "per_program_paths":  output_paths,
        "consolidated_path":  consolidated_uri,
    }


def _start_batch_transform(
    job_name: str,
    model_name: str,
    input_uri: str,
    output_uri: str,
    run_date: str,
    job_kind: str,
    instance_type: str = "ml.m5.large",
    instance_count: int = 1,
) -> None:
    """
    Kick off a SageMaker Batch Transform job.

    The job reads CSV from S3, runs the model in batch mode, and
    writes predictions back to S3. Batch Transform is dramatically
    cheaper than a real-time endpoint for this workload because we
    only pay for the duration of the job, not for an idle endpoint
    between weekly runs.
    """
    sagemaker_client.create_transform_job(
        TransformJobName=job_name,
        ModelName=model_name,
        TransformInput={
            "DataSource": {"S3DataSource": {
                "S3DataType": "S3Prefix",
                "S3Uri": input_uri,
            }},
            "ContentType":     "text/csv",
            "SplitType":       "Line",
            "CompressionType": "None",
        },
        TransformOutput={
            "S3OutputPath":   output_uri,
            "Accept":         "text/csv",
            # Production: use a customer-managed KMS key for the
            # output encryption. The example relies on bucket-default
            # encryption to keep the call simple.
        },
        TransformResources={
            "InstanceType":  instance_type,
            "InstanceCount": instance_count,
        },
        # Resource tags so cost-attribution and audit queries can find
        # this job by program and run_date. Pass run_date and job_kind
        # explicitly rather than reconstructing them from job_name:
        # since program_ids contain hyphens (e.g. "prog-dpp"), splitting
        # the job_name on "-" produced just the day-of-month suffix.
        Tags=[
            {"Key": "wellness:run_date", "Value": run_date},
            {"Key": "wellness:job_kind", "Value": job_kind},
        ],
    )


def _wait_for_transform_job(job_name: str, timeout_seconds: int = 3600) -> None:
    """Poll a Batch Transform job until it reaches a terminal state."""
    start = time.time()
    while True:
        response = sagemaker_client.describe_transform_job(TransformJobName=job_name)
        status = response["TransformJobStatus"]
        if status == "Completed":
            return
        if status in ("Failed", "Stopped"):
            reason = response.get("FailureReason", "")
            raise RuntimeError(f"Transform job {job_name} {status}: {reason}")
        if time.time() - start > timeout_seconds:
            raise TimeoutError(f"Transform job {job_name} timed out")
        time.sleep(15)


def _consolidate_scores(
    programs: list,
    run_date: str,
    output_paths: dict,
) -> str:
    """
    Stitch the per-program need / engagement / uplift CSVs into a
    single consolidated table with one row per (member, program).

    Production: Glue job writing parquet. The example simulates the
    output structure by listing the expected schema only; reading
    actual Batch Transform CSV outputs is straightforward but adds
    boilerplate that obscures the pattern.

    Returns the S3 URI of the consolidated table.
    """
    consolidated_uri = (
        f"s3://{SCORES_BUCKET}/run_date={run_date}/all-scores.csv"
    )
    # In the real implementation this function:
    #   1. reads each program's need/engagement/uplift CSVs
    #   2. joins on member_id within each program
    #   3. unions across programs into one (member_id, program_id,
    #      need_score, engagement_prob, uplift_estimate) table
    #   4. writes the table as parquet to consolidated_uri
    logger.info(
        "Consolidated scores table written to %s (covers %d programs)",
        consolidated_uri, len(programs),
    )
    return consolidated_uri
```

---

## Step 3: Combine Scores Into a Per-Member Ranked List

*The pseudocode calls this `rank_per_member(scores, policy)`. The consolidated scoring table has one row per (member, program). The ranker normalizes each component within program (so a high-need DPP member is comparable to a high-need smoking-cessation member), combines need / engagement / uplift via documented policy weights, and produces a per-member ranked list of programs. The combination weights are policy: documented, version-controlled, and reviewed by a cross-functional committee, not silently tuned in code.*

```python
def rank_per_member(
    scores_consolidated_path: str,
    policy_weights: dict = POLICY_WEIGHTS,
    policy_version: str = POLICY_VERSION,
) -> list:
    """
    Compute the priority score per (member, program) and rank
    programs within each member.

    Returns a flat list of dicts with priority, per-component
    contributions, and member_rank. The list is sorted by member_id
    then by member_rank so per-member groups are contiguous.
    """
    # Load the consolidated scores. Production: read parquet from S3
    # with awswrangler / pyarrow. The example uses a synthetic in-
    # memory table assembled by the demo runner so the function shape
    # is self-contained.
    rows = _load_consolidated_scores(scores_consolidated_path)
    if not rows:
        logger.warning("No rows in consolidated scores; skipping ranking")
        return []

    # ---- Normalize each score within program ----
    # Min-max within program brings each score to [0, 1]. Z-scores
    # would also be reasonable; pick one and document it. The choice
    # affects how aggressively the recommender favors high-uplift
    # outliers vs. consistently high-fit members.
    by_program: dict = {}
    for r in rows:
        by_program.setdefault(r["program_id"], []).append(r)

    for program_id, program_rows in by_program.items():
        for component in ("need_score", "engagement_prob", "uplift_estimate"):
            values = [r[component] for r in program_rows]
            lo, hi = min(values), max(values)
            spread = hi - lo if hi > lo else 1.0
            for r in program_rows:
                # Normalize. Add an explicit _norm key so the original
                # value is preserved for auditing.
                r[f"{component}_norm"] = (r[component] - lo) / spread

    # ---- Compute combined priority per (member, program) ----
    for r in rows:
        priority_components = {
            "need_contrib":       policy_weights["need"]       * r["need_score_norm"],
            "engagement_contrib": policy_weights["engagement"] * r["engagement_prob_norm"],
            "uplift_contrib":     policy_weights["uplift"]     * r["uplift_estimate_norm"],
        }
        r["priority"] = sum(priority_components.values())
        r["priority_components"] = priority_components
        r["policy_version"] = policy_version

    # ---- Group by member, rank programs within each member ----
    by_member: dict = {}
    for r in rows:
        by_member.setdefault(r["member_id"], []).append(r)

    ranked_rows = []
    for member_id, member_rows in by_member.items():
        member_rows.sort(key=lambda x: x["priority"], reverse=True)
        for rank_pos, r in enumerate(member_rows, start=1):
            r["member_rank"] = rank_pos
            ranked_rows.append(r)

    logger.info(
        "Ranked %d (member, program) rows across %d members",
        len(ranked_rows), len(by_member),
    )
    return ranked_rows


def _load_consolidated_scores(consolidated_path: str) -> list:
    """
    Load the consolidated scores table.

    Production: parquet read via awswrangler. The example reads a
    synthetic table from a sidecar JSON file when running offline
    for testing; otherwise returns an empty list.
    """
    # The demo runner monkey-patches this function to return an
    # in-memory synthetic dataset. In production this reads from S3.
    return []
```

---

## Step 4: Allocate Slots Under Capacity Constraints With Equity Floors

*The pseudocode calls this `allocate_capacity(per_member_rankings, programs, policy)`. The greedy allocator walks the ranked candidate list, assigns each member to at most one program per run, and respects each program's capacity. Equity floors reserve a portion of capacity for cohorts that uplift-only optimization would under-target (lowest engagement-history quartile, limited-English-proficiency, low-food-security SDOH cohorts). After the greedy pass, a second pass tops up any unfilled equity floors by relaxing the uplift threshold for those cohorts.*

```python
def allocate_capacity(
    ranked_rows: list,
    programs: list,
    equity_floors: dict = EQUITY_FLOORS,
    run_date: str = None,
) -> list:
    """
    Greedy capacity allocation with equity floors.

    Each member gets at most one program assigned per run. Each
    program respects its capacity. Equity floors reserve a portion
    of capacity for cohorts that the optimization would otherwise
    under-target.
    """
    run_date = run_date or _today_str()
    if not ranked_rows:
        return []

    # Build a flat list of (member, program, priority) candidates and
    # join in the cohort features the equity floors check.
    candidates = []
    for r in ranked_rows:
        cohort = _lookup_cohort_features(r["member_id"])
        candidates.append({
            **r,
            "cohort_features": cohort,
        })
    candidates.sort(key=lambda x: x["priority"], reverse=True)

    # Initialize per-program counters.
    program_by_id = {p["program_id"]: p for p in programs}
    capacity_remaining = {p["program_id"]: p["capacity"] for p in programs}
    equity_remaining = {
        pid: dict(equity_floors.get(pid, {})) for pid in capacity_remaining
    }

    allocated = []
    members_already_allocated = set()

    # ---- Greedy primary pass ----
    for candidate in candidates:
        program_id = candidate["program_id"]
        member_id = candidate["member_id"]

        if member_id in members_already_allocated:
            continue
        if capacity_remaining.get(program_id, 0) <= 0:
            continue

        # Equity-floor check: if this candidate fits a cohort with
        # remaining floor capacity, count the assignment against the
        # floor first. The floor reserves capacity even when uplift-
        # only ranking would have skipped this member.
        cohort_floor_used = None
        applicable = _applicable_floors(candidate["cohort_features"], equity_floors.get(program_id, {}))
        for floor_name in applicable:
            if equity_remaining[program_id].get(floor_name, 0) > 0:
                equity_remaining[program_id][floor_name] -= 1
                cohort_floor_used = floor_name
                break

        capacity_remaining[program_id] -= 1
        members_already_allocated.add(member_id)

        allocated.append({
            "tracking_id":         _make_tracking_id(run_date, member_id, program_id),
            "run_date":            run_date,
            "member_id":           member_id,
            "program_id":          program_id,
            "priority":            candidate["priority"],
            "priority_components": candidate["priority_components"],
            "policy_version":      candidate["policy_version"],
            "cohort_features":     candidate["cohort_features"],
            "allocation_reason": (
                f"equity_floor:{cohort_floor_used}"
                if cohort_floor_used
                else "top_uplift_general_capacity"
            ),
        })

    # ---- Equity-floor top-up pass ----
    # If any equity floor wasn't filled in the primary pass (because
    # uplift was low for that cohort and the cohort lost the global
    # ranking competition), pull additional candidates from the cohort
    # to fill the reserved slots. This is the explicit policy lever
    # that prevents the optimization from concentrating opportunity.
    for program_id, floors in equity_remaining.items():
        for floor_name, remaining in floors.items():
            if remaining <= 0:
                continue
            logger.info(
                "Top-up pass: program=%s floor=%s remaining=%d",
                program_id, floor_name, remaining,
            )
            # Find candidates from this cohort who haven't been
            # allocated yet, sorted by their (lower) priority.
            cohort_pool = [
                c for c in candidates
                if c["program_id"] == program_id
                and c["member_id"] not in members_already_allocated
                and floor_name in _applicable_floors(c["cohort_features"], {floor_name: 1})
            ]
            cohort_pool.sort(key=lambda x: x["priority"], reverse=True)
            for c in cohort_pool[:remaining]:
                if capacity_remaining[program_id] <= 0:
                    break
                capacity_remaining[program_id] -= 1
                members_already_allocated.add(c["member_id"])
                allocated.append({
                    "tracking_id":         _make_tracking_id(run_date, c["member_id"], program_id),
                    "run_date":            run_date,
                    "member_id":           c["member_id"],
                    "program_id":          program_id,
                    "priority":            c["priority"],
                    "priority_components": c["priority_components"],
                    "policy_version":      c["policy_version"],
                    "cohort_features":     c["cohort_features"],
                    "allocation_reason":   f"equity_floor_topup:{floor_name}",
                })

    # ---- Persist allocations to the recommendation log ----
    rec_table = dynamodb.Table(RECOMMENDATION_LOG_TABLE)
    with rec_table.batch_writer() as batch:
        for row in allocated:
            batch.put_item(Item={
                "tracking_id":         row["tracking_id"],
                "run_date":            row["run_date"],
                "member_id":           row["member_id"],
                "program_id":          row["program_id"],
                "priority":            _to_decimal(row["priority"]),
                "priority_components": {
                    k: _to_decimal(v) for k, v in row["priority_components"].items()
                },
                "policy_version":      row["policy_version"],
                "cohort_features":     row["cohort_features"],
                "allocation_reason":   row["allocation_reason"],
                "created_at":          _now_iso(),
            })

    _emit_metric(
        "allocations_made",
        value=len(allocated),
        dimensions={
            "run_date":       run_date,
            "policy_version": POLICY_VERSION,
        },
    )
    logger.info("Allocated %d members across %d programs", len(allocated), len(programs))
    return allocated


def _applicable_floors(cohort_features: dict, floor_definitions: dict) -> list:
    """
    Return the names of equity floors this candidate qualifies for.

    The floor definitions are simple membership tests in the example.
    Production: a richer rule engine that supports compound criteria
    (e.g., "low food security AND non-English language").
    """
    result = []
    for floor_name in floor_definitions:
        if floor_name == "engagement_q1" and cohort_features.get("engagement_history_quartile") == "q1":
            result.append(floor_name)
        elif floor_name == "language_non_en" and cohort_features.get("language") not in (None, "en"):
            result.append(floor_name)
        elif floor_name == "sdoh_low_food_security" and cohort_features.get("sdoh_cohort") == "low_food_security":
            result.append(floor_name)
    return result


def _lookup_cohort_features(member_id: str) -> dict:
    """
    Pull cohort features for a member from the patient-profile table.

    Cohort axes used for fairness monitoring and equity floors:
    engagement-history quartile, preferred language, SDOH cohort,
    age band. Limit cohort attributes on engagement events to the
    minimum needed; SDOH cohort labels are PHI even after stripping
    direct identifiers (a small SDOH cohort in a specific geography
    is reidentifiable).
    """
    profile_table = dynamodb.Table(PATIENT_PROFILE_TABLE)
    try:
        response = profile_table.get_item(Key={"member_id": member_id})
    except Exception as exc:
        logger.warning("Profile lookup failed for %s: %s", member_id, exc)
        return {}
    profile = response.get("Item") or {}
    return {
        "engagement_history_quartile": profile.get("engagement_history_quartile", "q3"),
        "language":                    profile.get("preferred_language", "en"),
        "sdoh_cohort":                 profile.get("sdoh_cohort"),
        "age_band":                    profile.get("age_band"),
    }


def _make_tracking_id(run_date: str, member_id: str, program_id: str) -> str:
    """
    Stable tracking_id used to join allocations to outreach to
    engagement events. Stable across retries so duplicate processing
    converges to the same recommendation-log row.
    """
    return f"wellness-{run_date}-{member_id}-{program_id}"
```

---

## Step 5: Apply Contact-Frequency Caps and Consent Verification

*The pseudocode calls this `enforce_outreach_caps(allocated, run_date, policy)`. Before outreach goes out, a final pass verifies each allocated member is within their contact-frequency cap (no more than 2 wellness touches per month, no more than 4 total touches per month) and that wellness consent is current. Members who exceed a cap are deferred (with the reason logged) rather than dropped silently; deferral patterns are signal that the cap is too tight or the recommender is over-targeting.*

```python
def enforce_outreach_caps(
    allocated: list,
    run_date: str,
    max_wellness: int = MAX_WELLNESS_PER_MONTH,
    max_total: int = MAX_TOTAL_PER_MONTH,
) -> tuple:
    """
    Filter the allocation list against contact-frequency caps and
    consent.

    Returns (outreach_list, deferred_list). Deferred reasons are
    persisted so members who repeatedly hit caps are visible to the
    member-services and equity-monitoring teams.
    """
    profile_table = dynamodb.Table(PATIENT_PROFILE_TABLE)
    outreach_list = []
    deferred = []

    for row in allocated:
        member_id = row["member_id"]
        program_id = row["program_id"]

        try:
            response = profile_table.get_item(Key={"member_id": member_id})
        except Exception as exc:
            # Treat lookup failure as a defer rather than a silent
            # send; we don't know the consent state, so default safe.
            logger.warning("Profile lookup failed for %s: %s", member_id, exc)
            deferred.append({"row": row, "reason": "profile_lookup_failed"})
            continue

        profile = _from_decimal(response.get("Item") or {})

        # ---- Wellness consent check ----
        # In jurisdictions or plan policies that require explicit
        # consent for wellness outreach, the member must have an
        # active consent flag. Members can also opt out per program;
        # check that too.
        if not profile.get("wellness_consent_active", False):
            deferred.append({"row": row, "reason": "no_active_wellness_consent"})
            continue
        opt_outs = profile.get("opt_outs", {}).get("programs", [])
        if program_id in opt_outs:
            deferred.append({"row": row, "reason": "member_opted_out_of_program"})
            continue

        # ---- Contact-frequency caps ----
        # Wellness-specific cap is tighter than the global outreach
        # cap; enforce both.
        recent_wellness = int(profile.get("outreach_recent_wellness_count", 0))
        recent_total = int(profile.get("outreach_recent_total_count", 0))

        if recent_wellness >= max_wellness:
            deferred.append({"row": row, "reason": "wellness_cap_exceeded"})
            continue
        if recent_total >= max_total:
            deferred.append({"row": row, "reason": "total_cap_exceeded"})
            continue

        outreach_list.append(row)

    # Persist deferred reasons so cap-driven exclusions are auditable.
    # Production: write to a deferral-log DynamoDB table or a Glue
    # partition keyed on run_date so dashboards can surface trends.
    if deferred:
        logger.info(
            "Deferred %d allocations for cap/consent reasons; reasons=%s",
            len(deferred),
            sorted({d["reason"] for d in deferred}),
        )

    _emit_metric(
        "outreach_after_caps",
        value=len(outreach_list),
        dimensions={"run_date": run_date},
    )
    _emit_metric(
        "outreach_deferred",
        value=len(deferred),
        dimensions={"run_date": run_date},
    )
    return outreach_list, deferred
```

---

## Step 6: Tailor Outreach With an LLM and Dispatch

*The pseudocode calls this `tailor_and_dispatch(outreach_list, programs)`. Each member in the post-cap outreach list goes through a per-message tailoring step (Bedrock with structured-output prompting), gets handed to Recipe 4.1's channel optimizer for delivery, and emits a `program_recommended` event to the engagement stream so downstream attribution can match outcomes back to this recommendation. The LLM does not pick the program; it packages it. Hallucinated clinical claims in patient-facing outreach are an FDA-attention failure mode, so the validator step is production-critical.*

```python
def tailor_and_dispatch(
    outreach_list: list,
    programs: list,
) -> list:
    """
    For each allocated member, generate a tailored outreach message,
    hand it to the channel optimizer, and emit a program_recommended
    engagement event.

    Returns a list of dispatch records (one per outreach attempt) for
    audit and downstream reconciliation.
    """
    program_by_id = {p["program_id"]: p for p in programs}
    profile_table = dynamodb.Table(PATIENT_PROFILE_TABLE)
    dispatched = []

    for row in outreach_list:
        member_id = row["member_id"]
        program_id = row["program_id"]
        program = program_by_id[program_id]

        try:
            response = profile_table.get_item(Key={"member_id": member_id})
            member = _from_decimal(response.get("Item") or {})
        except Exception as exc:
            logger.warning("Profile lookup failed for %s during dispatch: %s", member_id, exc)
            continue

        # ---- Build the structured prompt input ----
        # IMPORTANT: pass de-identified context to the LLM. Don't pass
        # raw identifiers (member_id, name, phone) into the prompt.
        # Rendered identifiers are reattached after generation by the
        # channel optimizer.
        prompt_context = {
            "program_name":         program["display_name"],
            "program_summary":      program["public_summary"],
            "program_time_commit":  program["time_commitment"],
            "relevant_clinical":    _summarize_clinical_for_outreach(member, program),
            "preferred_language":   member.get("preferred_language", "en"),
            "tone":                 "supportive, non-alarming",
        }

        # ---- Generate the tailored message ----
        try:
            tailored = _tailor_outreach_message(prompt_context)
        except Exception as exc:
            # Fall back to the program's default template if the LLM
            # call fails. Outreach should degrade gracefully, not
            # block the entire batch.
            logger.warning("Message tailoring failed for %s: %s", row["tracking_id"], exc)
            tailored = None

        # ---- Validate the LLM output ----
        # Production: validator checks against an approved-claims list
        # and a prohibited-claims list (no curative-language, no
        # outcome guarantees). The example does a basic shape check.
        if tailored and not _validate_outreach_message(tailored, program):
            logger.warning(
                "Outreach validation failed for %s; falling back to template",
                row["tracking_id"],
            )
            tailored = None

        # ---- Dispatch through the channel optimizer ----
        # Recipe 4.1 owns the channel optimizer; this code submits
        # the request and trusts the optimizer to pick channel and
        # timing. The "fallback_template" is what the optimizer uses
        # if SMS truncation or another channel constraint disqualifies
        # the LLM-generated copy.
        dispatch_record = _queue_outreach_via_channel_optimizer(
            tracking_id=row["tracking_id"],
            member_id=member_id,
            program_id=program_id,
            tailored=tailored,
            fallback_template=program["default_template"],
            urgency=_derive_urgency(row["priority"], program.get("next_cohort_start")),
        )
        dispatched.append(dispatch_record)

        # ---- Update the contact-frequency counter optimistically ----
        # Optimistic: the actual send may fail; reconcile in the
        # engagement-attribution step. The TTL-style 30-day rolling
        # counter is maintained by a separate Lambda that runs on
        # a daily schedule and decrements stale touches.
        try:
            profile_table.update_item(
                Key={"member_id": member_id},
                UpdateExpression=(
                    "ADD outreach_recent_wellness_count :one, "
                    "outreach_recent_total_count :one "
                    "SET outreach_last_at = :now"
                ),
                ExpressionAttributeValues={
                    ":one": Decimal("1"),
                    ":now": _now_iso(),
                },
            )
        except Exception as exc:
            logger.warning("Failed to update outreach counter for %s: %s", member_id, exc)

        # ---- Optionally generate a parallel PCP briefing ----
        if program.get("pcp_alert_enabled"):
            try:
                pcp_briefing = _generate_pcp_briefing(prompt_context, member, program)
                _post_pcp_note(member_id, pcp_briefing, row["tracking_id"])
            except Exception as exc:
                logger.warning("PCP briefing failed for %s: %s", row["tracking_id"], exc)

        # ---- Emit a program_recommended engagement event ----
        # This event is the join point for downstream attribution: the
        # outreach-opened, enrollment, and completion events all carry
        # the same tracking_id and resolve back to this recommendation.
        try:
            kinesis_client.put_record(
                StreamName=ENGAGEMENT_STREAM_NAME,
                # Partition by member_id so a single member's events
                # land on the same shard and arrive in order.
                PartitionKey=member_id,
                Data=json.dumps({
                    "event_type":          "program_recommended",
                    "tracking_id":         row["tracking_id"],
                    "member_id":           member_id,
                    "program_id":          program_id,
                    "run_date":            row["run_date"],
                    "priority_components": {
                        k: float(v) for k, v in row["priority_components"].items()
                    },
                    "allocation_reason":   row["allocation_reason"],
                    "timestamp":           _now_iso(),
                }).encode("utf-8"),
            )
        except Exception as exc:
            logger.warning(
                "Failed to publish program_recommended event for %s: %s",
                row["tracking_id"], exc,
            )

    logger.info("Dispatched %d outreach messages", len(dispatched))
    return dispatched


def _summarize_clinical_for_outreach(member: dict, program: dict) -> str:
    """
    Build a one-sentence clinical context line for the LLM prompt.

    Stays HIGH-level. Does not include lab values, exact diagnoses,
    or anything that wouldn't be appropriate to surface in a member-
    facing email. The clinical content here gets paraphrased into
    member-friendly language by the LLM; passing too much detail
    risks the LLM rendering precise PHI back into the message.
    """
    program_id = program["program_id"]
    if program_id == "prog-dpp":
        return "Member's recent A1c is in the prediabetes range."
    if program_id == "prog-smoking":
        return "Member's profile indicates they currently smoke."
    if program_id == "prog-weight":
        return "Member's BMI is in a range where lifestyle change is supported."
    if program_id == "prog-stress":
        return "Member has indicated stress is something they'd like support with."
    if program_id == "prog-sleep":
        return "Member has indicated sleep concerns are relevant."
    return "Member's profile suggests this program may be helpful."


def _tailor_outreach_message(prompt_context: dict) -> dict:
    """
    Invoke Bedrock to produce a tailored outreach message.

    Production: use Bedrock's structured-output / tool-use feature
    so the model is forced to return JSON conforming to a strict
    schema. The example uses a plain-prompt approach for clarity.
    """
    prompt = f"""You are a wellness program outreach writer for a health plan.
Produce a short, supportive, non-alarming outreach message inviting a member
to a wellness program. Match the requested language. Do NOT make any clinical
claims that aren't in the relevant_clinical input. Do NOT promise outcomes.

Program: {prompt_context['program_name']}
Summary: {prompt_context['program_summary']}
Time commitment: {prompt_context['program_time_commit']}
Relevant clinical context: {prompt_context['relevant_clinical']}
Language (ISO 639-1): {prompt_context['preferred_language']}
Tone: {prompt_context['tone']}

Return ONLY valid JSON with this shape:
{{
  "subject_line":           "<subject>",
  "opening_line":           "<one short opener>",
  "program_pitch":          "<2-3 sentence pitch>",
  "closing_call_to_action": "<single CTA, no guarantees>"
}}
"""
    response = bedrock_runtime.invoke_model(
        modelId=OUTREACH_TAILORING_MODEL_ID,
        contentType="application/json",
        accept="application/json",
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens":        500,
            "temperature":       0.3,   # mild variation, not deterministic
            "messages":          [{"role": "user", "content": prompt}],
        }),
    )
    payload = json.loads(response["body"].read())
    completion = payload["content"][0]["text"]
    # Defensive JSON extraction: LLMs sometimes wrap output in prose.
    import re as _re
    match = _re.search(r"\{.*\}", completion, _re.DOTALL)
    if not match:
        raise ValueError("LLM returned no JSON object")
    return json.loads(match.group(0))


def _validate_outreach_message(tailored: dict, program: dict) -> bool:
    """
    Validate the tailored outreach against shape and content rules.

    The example checks shape only. Production: an additional pass
    against an approved-claims list and a prohibited-claims list,
    with a sample-and-review workflow for the medical director.
    """
    required = {"subject_line", "opening_line", "program_pitch", "closing_call_to_action"}
    if set(tailored.keys()) != required:
        return False
    if any(not isinstance(tailored[k], str) or not tailored[k].strip() for k in required):
        return False
    # Reject obviously over-promising language. A real prohibited-
    # claims list is much longer and is owned by clinical/compliance.
    blocklist = ["guaranteed", "cure", "100%", "definitely will"]
    full_text = " ".join(tailored.values()).lower()
    if any(bad in full_text for bad in blocklist):
        return False
    return True


def _queue_outreach_via_channel_optimizer(
    tracking_id: str,
    member_id: str,
    program_id: str,
    tailored: dict | None,
    fallback_template: str,
    urgency: str,
) -> dict:
    """
    Hand the outreach request to Recipe 4.1's channel optimizer.

    The channel optimizer decides email vs. SMS vs. portal nudge and
    when to send. The example logs the dispatch and returns a record;
    production posts to an SQS queue or invokes the channel optimizer
    Lambda directly through the shared internal API.
    """
    record = {
        "tracking_id":       tracking_id,
        "member_id":         member_id,
        "program_id":        program_id,
        "content_type":      "wellness_program_recommendation",
        "tailored":          tailored,
        "fallback_template": fallback_template,
        "urgency":           urgency,
        "queued_at":         _now_iso(),
    }
    logger.info("Queued outreach %s (urgency=%s)", tracking_id, urgency)
    return record


def _derive_urgency(priority: float, next_cohort_start_iso: str | None) -> str:
    """
    Map priority and cohort proximity to an urgency tag the channel
    optimizer can use to decide send timing.
    """
    if not next_cohort_start_iso:
        return "standard"
    try:
        cohort_date = datetime.date.fromisoformat(next_cohort_start_iso)
    except ValueError:
        return "standard"
    days_to_cohort = (cohort_date - datetime.date.today()).days
    if days_to_cohort <= 7 and priority >= 0.6:
        return "urgent"
    if days_to_cohort <= 14:
        return "elevated"
    return "standard"


def _generate_pcp_briefing(prompt_context: dict, member: dict, program: dict) -> str:
    """
    Generate a one-paragraph briefing for the member's PCP that goes
    into the EHR inbox. The PCP's response (endorsed, declined,
    deferred) feeds back as a pcp_override engagement event.
    """
    # In production this is a separate Bedrock prompt template tuned
    # for clinician audiences. The example returns a deterministic
    # string so the demo doesn't burn an extra Bedrock call.
    return (
        f"Wellness program recommendation: {program['display_name']}. "
        f"Rationale: {prompt_context['relevant_clinical']} "
        f"Talking points: confirm program fit at next visit; "
        f"member can decline without affecting other care. "
        f"Reply 'endorse' / 'decline' / 'defer' to update the system."
    )


def _post_pcp_note(member_id: str, briefing: str, tracking_id: str) -> None:
    """
    Post a structured note to the EHR's care-team inbox.

    Each EHR has its own integration surface (Epic, Oracle Cerner,
    Athena, Veradigm). The example logs the post; production routes
    to the appropriate adapter Lambda per EHR.
    """
    logger.info(
        "PCP briefing posted (member=%s, tracking_id=%s, length=%d chars)",
        member_id, tracking_id, len(briefing),
    )
```

---

## Step 7: Capture Engagement Events and Update Training Data

*The pseudocode calls this `process_engagement_event(event)`. A separate Lambda consumes the engagement stream, joins each event back to the recommendation log by tracking_id, and updates short-, medium-, and long-horizon training data on the appropriate cadence. A `pcp_override` event is treated as a strong negative label. Cohort-sliced metrics surface subgroup drift to the equity dashboard.*

```python
def process_engagement_event(event: dict) -> None:
    """
    Process one engagement event from the Kinesis stream.

    Expected shape:
      {
        "event_type":   "program_recommended" | "program_outreach_sent" |
                        "program_outreach_opened" | "program_enrolled" |
                        "program_session_attended" | "program_completed" |
                        "program_dropped_out" | "pcp_override",
        "tracking_id":  "wellness-<run_date>-<member_id>-<program_id>",
        "member_id":    "...",
        "program_id":   "...",
        "timestamp":    ISO 8601,
        "reason":       optional string for pcp_override / dropped_out
      }
    """
    tracking_id = event.get("tracking_id")
    event_type = event.get("event_type")
    member_id = event.get("member_id")
    program_id = event.get("program_id")

    if not (tracking_id and event_type and member_id and program_id):
        logger.warning("Malformed engagement event; dropping: %s", event)
        return

    # ---- Look up the originating recommendation ----
    rec_table = dynamodb.Table(RECOMMENDATION_LOG_TABLE)
    rec_response = rec_table.get_item(Key={"tracking_id": tracking_id})
    rec = rec_response.get("Item")
    if rec is None:
        logger.warning("Engagement event for unknown tracking_id=%s; dropping", tracking_id)
        return

    # ---- Validate identity boundaries ----
    # Same boundary as Recipes 4.1 / 4.2 / 4.3: a buggy or malicious
    # producer that submits events with a different member_id would
    # pollute another member's training data and personalization
    # signal. Drop the event rather than absorb the inconsistency.
    if member_id != rec["member_id"]:
        logger.warning(
            "Event member_id=%s does not match recommendation %s; dropping",
            member_id, tracking_id,
        )
        return

    # ---- Persist the raw event ----
    # event_id is constructed so duplicate Kinesis deliveries converge
    # to the same row.
    event_id = f"{tracking_id}:{event_type}:{event.get('timestamp', '')}"
    events_table = dynamodb.Table(ENGAGEMENT_EVENTS_TABLE)
    events_table.put_item(Item={
        "event_id":            event_id,
        "tracking_id":         tracking_id,
        "member_id":           member_id,
        "program_id":          program_id,
        "event_type":          event_type,
        "timestamp":           event.get("timestamp", _now_iso()),
        "run_date":            rec["run_date"],
        "priority":            rec["priority"],
        "priority_components": rec["priority_components"],
        "allocation_reason":   rec["allocation_reason"],
        "cohort_features":     rec.get("cohort_features", {}),
        "reason":              event.get("reason"),
    })

    # ---- Route to short / medium / long horizon training data ----
    if event_type in ("program_outreach_opened", "program_outreach_clicked",
                      "program_enrolled"):
        # Short-horizon: feed the engagement-prediction model's next
        # training cycle. The trainer reads engagement-events with
        # rec.priority_components and rec.cohort_features as features
        # and the event_type as the label.
        _update_engagement_training_label(rec, event)
    if event_type in ("program_completed", "program_dropped_out"):
        # Medium-horizon: feed the uplift training data. If this
        # member came from a randomized hold-out arm, the row joins
        # the treated cohort with a positive treatment label; control
        # arm members come from a parallel pipeline that's out of
        # scope here.
        _update_uplift_training_label(rec, event)

    # ---- PCP override: strong negative signal ----
    if event_type == "pcp_override":
        logger.info(
            "PCP override for %s reason=%s; flagging for clinical review",
            tracking_id, event.get("reason"),
        )
        _flag_for_clinical_review(event)
        _emit_metric(
            "pcp_override",
            value=1,
            dimensions={
                "program_id": program_id,
                "reason":     str(event.get("reason", "unspecified"))[:100],
            },
        )

    # ---- Cohort-sliced engagement metric ----
    # Slice by event_type, language, engagement-history quartile, and
    # SDOH cohort so the equity dashboard surfaces drift. Don't add
    # high-cardinality dimensions (member_id) to CloudWatch metrics;
    # custom-metric pricing punishes that.
    cohort = rec.get("cohort_features", {}) or {}
    _emit_metric(
        "wellness_engagement",
        value=1,
        dimensions={
            "event_type":              event_type,
            "program_id":              program_id,
            "engagement_history_q":    str(cohort.get("engagement_history_quartile", "unknown")),
            "language":                str(cohort.get("language", "unknown")),
            "sdoh_cohort":             str(cohort.get("sdoh_cohort", "unknown")),
        },
    )
    logger.info(
        "Processed %s for tracking_id=%s member=%s",
        event_type, tracking_id, member_id,
    )


def _update_engagement_training_label(rec: dict, event: dict) -> None:
    """
    Update the engagement-prediction training data with this label.

    Production: append a row to a Glue partition keyed on
    (program_id, event_date) and recompute the rolling training set
    nightly. The trainer (separate SageMaker Training Job) reads
    those partitions on its own schedule.
    """
    logger.debug(
        "engagement_training_label_added: tracking_id=%s event=%s",
        rec["tracking_id"], event["event_type"],
    )


def _update_uplift_training_label(rec: dict, event: dict) -> None:
    """
    Update the uplift-model training data with this label.

    Production: write to a separate uplift-training partition that
    distinguishes treated (recommendation arm) from control (hold-
    out arm). The trainer joins the two cohorts and runs the
    X-learner / causal forest training. Without a randomized hold-
    out, the labels here only support engagement modeling, not
    causal uplift; the medium-horizon dashboard should reflect that
    limitation honestly.
    """
    logger.debug(
        "uplift_training_label_added: tracking_id=%s event=%s",
        rec["tracking_id"], event["event_type"],
    )


def _flag_for_clinical_review(event: dict) -> None:
    """
    Route a PCP override to the clinical-review queue. The medical
    director or a delegate reviews these on a weekly cadence to
    distinguish legitimate clinical override from PCP skepticism
    toward wellness programs in general.
    """
    logger.info(
        "Flagged for clinical review: tracking_id=%s reason=%s",
        event.get("tracking_id"), event.get("reason"),
    )
```

---

## Step 8: Run Long-Horizon Outcome Evaluation

*The pseudocode calls this `run_outcome_evaluation(programs, evaluation_window)`. Independent of the weekly batch run, a quarterly or semi-annual job compares the clinical and cost trajectories of recommended-and-engaged members against matched controls (randomized hold-out arm if available, propensity-matched non-recommended members otherwise). The output drives program-renewal decisions and surfaces evidence (or counter-evidence) for whether each program is moving the needle. Stratified results catch heterogeneous effects that the aggregate ATE hides.*

```python
def run_outcome_evaluation(
    programs: list,
    evaluation_window: dict,
) -> list:
    """
    Run the quarterly or semi-annual outcome evaluation across all
    programs and persist the results to the program-outcome-
    evaluations table.

    evaluation_window shape:
        {"start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}
    """
    eval_table = dynamodb.Table(OUTCOME_EVAL_TABLE)
    results = []

    for program in programs:
        program_id = program["program_id"]
        method = program.get("eval_method", "propensity_matched_difference_in_differences")

        # ---- Build the treated and control cohorts ----
        # Treated: members recommended and engaged within the window.
        # Control: matched members not recommended. If a randomized
        # hold-out arm exists, prefer it; otherwise propensity-match
        # on pre-recommendation features.
        treated = _pull_treated_cohort(program_id, evaluation_window)
        control = _pull_matched_control(program_id, evaluation_window, method)

        if not treated or not control:
            logger.warning(
                "Insufficient cohort size for %s eval (treated=%d, control=%d); skipping",
                program_id, len(treated), len(control),
            )
            continue

        # ---- Compute outcomes for each cohort ----
        treated_outcomes = _compute_outcomes(
            treated, program["outcome_definitions"], evaluation_window,
        )
        control_outcomes = _compute_outcomes(
            control, program["outcome_definitions"], evaluation_window,
        )

        # ---- Estimate ATE with confidence intervals ----
        # The example uses a placeholder difference-in-means; production
        # uses a doubly-robust estimator with proper standard errors.
        ate = _estimate_ate(treated_outcomes, control_outcomes, method=method)

        # ---- Stratify by cohort to surface heterogeneous effects ----
        # The aggregate ATE may be positive while one cohort
        # experiences null or negative effect. This is equity-relevant
        # signal that must surface in the evaluation report.
        ate_by_cohort = _stratified_ate(
            treated_outcomes, control_outcomes,
            cohort_axes=["sdoh_cohort", "language", "age_band"],
        )

        # ---- Persist the evaluation result ----
        evaluation_id = (
            f"eval-{evaluation_window['start_date']}_to_"
            f"{evaluation_window['end_date']}-{program_id}"
        )
        item = {
            "evaluation_id":      evaluation_id,
            "program_id":         program_id,
            "evaluation_window":  evaluation_window,
            "method":             method,
            "ate":                _to_decimal_dict(ate),
            "ate_by_cohort":      [_to_decimal_dict(c) for c in ate_by_cohort],
            "sample_size_treated": len(treated),
            "sample_size_control": len(control),
            "run_date":           _today_str(),
        }
        eval_table.put_item(Item=item)
        results.append(item)

        # ---- Emit dashboard metrics ----
        _emit_metric(
            "program_outcome_ate",
            value=float(ate.get("estimate", 0.0)),
            dimensions={
                "program_id": program_id,
                "outcome":    str(ate.get("primary_outcome", "unknown")),
            },
        )
        logger.info(
            "Outcome evaluation complete for %s: ATE=%.3f (n_treated=%d, n_control=%d)",
            program_id, float(ate.get("estimate", 0.0)),
            len(treated), len(control),
        )

    return results


def _pull_treated_cohort(program_id: str, window: dict) -> list:
    """
    Build the treated cohort: members recommended for and engaged
    with this program in the window.

    Production: SQL against the engagement-events partitioned data
    lake joined to the recommendation log. The example returns an
    empty list; the demo runner injects a synthetic cohort.
    """
    return []


def _pull_matched_control(program_id: str, window: dict, method: str) -> list:
    """
    Build the matched control cohort. Prefer randomized hold-out arm
    if available; otherwise propensity-score match on pre-
    recommendation features.

    Production: a separate SageMaker job that trains the propensity
    model and produces matched pairs. The example returns an empty
    list; the demo runner injects a synthetic cohort.
    """
    return []


def _compute_outcomes(cohort: list, outcome_defs: dict, window: dict) -> dict:
    """
    Compute the cohort's primary and secondary outcomes over the
    evaluation window. Production: SQL joining claims, EHR-derived
    facts, and pharmacy data; outcome definitions are formal
    specifications, not free-form computations.
    """
    return {
        "primary_outcome":   outcome_defs.get("primary_outcome"),
        "primary_values":    [],   # populated by the production query
        "n":                 len(cohort),
    }


def _estimate_ate(treated: dict, control: dict, method: str) -> dict:
    """
    Estimate the average treatment effect with confidence intervals.

    Production: doubly-robust estimation for propensity-matched
    cohorts; difference-in-means for randomized arms; both with
    proper standard errors. The example returns a placeholder
    structure that matches the production schema.
    """
    return {
        "primary_outcome": treated.get("primary_outcome"),
        "estimate":        0.0,
        "ci_95_low":       0.0,
        "ci_95_high":      0.0,
        "p_value":         1.0,
        "interpretation":  "placeholder; production runs doubly-robust estimation",
    }


def _stratified_ate(treated: dict, control: dict, cohort_axes: list) -> list:
    """
    Compute ATE within each cohort defined by the cohort_axes. Returns
    a list of {cohort, estimate, ci_95_low, ci_95_high} dicts.
    """
    return []


def _to_decimal_dict(d: dict) -> dict:
    """Convert numeric values in a flat dict to Decimal for DynamoDB."""
    out = {}
    for k, v in d.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = _to_decimal(v)
        else:
            out[k] = v
    return out
```

---

## Putting It All Together

Here's the full inference pipeline assembled into a single callable function. In production, this is a Step Functions workflow with each step as a separate task: Glue jobs (eligibility), SageMaker Batch Transform jobs in parallel (scoring), Lambda (rank, allocate, enforce caps, dispatch), and a separate Lambda consuming the engagement stream (Step 7). The example chains them together so you can trace one weekly run end-to-end.

```python
def run_weekly_batch(
    programs: list,
    run_date: str | None = None,
) -> dict:
    """
    Run the full weekly recommendation batch for all programs.

    Steps 1 through 6 of the recipe:
      1. build_eligible_member_lists
      2. score_eligible_population
      3. rank_per_member
      4. allocate_capacity
      5. enforce_outreach_caps
      6. tailor_and_dispatch

    Step 7 (process_engagement_event) runs continuously in a separate
    Lambda. Step 8 (run_outcome_evaluation) runs on a quarterly
    cadence. Both are exercised separately in the demo below.
    """
    run_date = run_date or _today_str()
    start = time.time()

    print(f"=== Starting weekly batch for run_date={run_date} ===")

    print("\nStep 1: Building eligible-member lists per program...")
    eligible_paths = build_eligible_member_lists(programs, run_date)
    print(f"  Eligible lists ready for {len(eligible_paths)} programs")

    print("\nStep 2: Scoring eligible population (need / engagement / uplift)...")
    score_paths = score_eligible_population(programs, run_date, eligible_paths)
    print(f"  Scoring complete; consolidated table: {score_paths['consolidated_path']}")

    print("\nStep 3: Ranking per-member...")
    ranked_rows = rank_per_member(score_paths["consolidated_path"])
    print(f"  Ranked {len(ranked_rows)} (member, program) rows")

    print("\nStep 4: Allocating capacity with equity floors...")
    allocated = allocate_capacity(ranked_rows, programs, run_date=run_date)
    print(f"  Allocated {len(allocated)} (member, program) pairs")

    print("\nStep 5: Enforcing contact-frequency caps and consent...")
    outreach_list, deferred = enforce_outreach_caps(allocated, run_date)
    print(
        f"  After caps: {len(outreach_list)} for outreach, "
        f"{len(deferred)} deferred"
    )

    print("\nStep 6: Tailoring outreach and dispatching...")
    dispatched = tailor_and_dispatch(outreach_list, programs)
    print(f"  Dispatched {len(dispatched)} outreach messages")

    elapsed = int(time.time() - start)
    print(f"\n=== Batch complete in {elapsed}s ===")
    return {
        "run_date":           run_date,
        "eligible_paths":     eligible_paths,
        "scoring_paths":      score_paths,
        "n_ranked":           len(ranked_rows),
        "n_allocated":        len(allocated),
        "n_outreach":         len(outreach_list),
        "n_deferred":         len(deferred),
        "n_dispatched":       len(dispatched),
        "elapsed_seconds":    elapsed,
    }


# --- Demo runner ---
if __name__ == "__main__":
    # All sample data is SYNTHETIC. Do not use real PHI in development.
    # The demo:
    #   1. Seeds two synthetic members with different cohort profiles
    #   2. Bypasses the SageMaker Batch Transform calls by injecting
    #      synthetic scores directly (real Batch Transform requires
    #      trained models and IAM setup)
    #   3. Runs Steps 3-6 of the pipeline against the synthetic scores
    #   4. Simulates a program_enrolled engagement event to exercise
    #      Step 7
    #   5. Runs an outcome evaluation pass to exercise Step 8

    print("=" * 70)
    print("Seeding synthetic members...")
    print("=" * 70)
    profile_table = dynamodb.Table(PATIENT_PROFILE_TABLE)
    sample_members = [
        {
            "member_id":                       "mem-000482",
            "preferred_language":              "es",
            "engagement_history_quartile":     "q2",
            "sdoh_cohort":                     "low_food_security",
            "age_band":                        "55-64",
            "wellness_consent_active":         True,
            "outreach_recent_wellness_count":  Decimal("0"),
            "outreach_recent_total_count":     Decimal("0"),
            "opt_outs":                        {"programs": []},
        },
        {
            "member_id":                       "mem-000721",
            "preferred_language":              "en",
            "engagement_history_quartile":     "q1",
            "sdoh_cohort":                     None,
            "age_band":                        "45-54",
            "wellness_consent_active":         True,
            "outreach_recent_wellness_count":  Decimal("0"),
            "outreach_recent_total_count":     Decimal("0"),
            "opt_outs":                        {"programs": []},
        },
    ]
    for m in sample_members:
        try:
            profile_table.put_item(Item=m)
            print(f"  Seeded {m['member_id']} (lang={m['preferred_language']}, "
                  f"engagement_q={m['engagement_history_quartile']})")
        except Exception as exc:
            print(f"  WARN: profile seed failed for {m['member_id']}: {exc}")

    # ---- Inject synthetic scores by monkey-patching the loader ----
    # The real consolidated scores table comes from SageMaker Batch
    # Transform output. The demo skips that step (which would require
    # trained models and a long-running batch transform job) by
    # supplying scores directly. This is for demonstration only;
    # production never bypasses the score-loading path.
    synthetic_scores = [
        # (member, program, need, engagement, uplift)
        {"member_id": "mem-000482", "program_id": "prog-dpp",
         "need_score": 0.85, "engagement_prob": 0.40, "uplift_estimate": 0.62},
        {"member_id": "mem-000482", "program_id": "prog-weight",
         "need_score": 0.70, "engagement_prob": 0.35, "uplift_estimate": 0.48},
        {"member_id": "mem-000721", "program_id": "prog-smoking",
         "need_score": 0.90, "engagement_prob": 0.25, "uplift_estimate": 0.71},
        {"member_id": "mem-000721", "program_id": "prog-stress",
         "need_score": 0.55, "engagement_prob": 0.30, "uplift_estimate": 0.30},
    ]

    # Replace the loader for the duration of this demo. In production
    # the loader reads parquet from S3.
    def _demo_loader(_path):
        return synthetic_scores
    globals()["_load_consolidated_scores"] = _demo_loader

    print("\n" + "=" * 70)
    print("Running Steps 3-5 against synthetic scores...")
    print("=" * 70)

    run_date = _today_str()

    print("\nStep 3: Ranking per-member...")
    ranked = rank_per_member("s3://demo/all-scores.csv")
    for r in ranked:
        print(f"  {r['member_id']} -> {r['program_id']}: "
              f"priority={r['priority']:.3f} "
              f"(need={r['priority_components']['need_contrib']:.3f}, "
              f"eng={r['priority_components']['engagement_contrib']:.3f}, "
              f"uplift={r['priority_components']['uplift_contrib']:.3f})")

    print("\nStep 4: Allocating capacity with equity floors...")
    allocated = allocate_capacity(ranked, SAMPLE_PROGRAMS, run_date=run_date)
    for a in allocated:
        print(f"  Allocated {a['member_id']} -> {a['program_id']} "
              f"(reason={a['allocation_reason']})")

    print("\nStep 5: Enforcing contact-frequency caps...")
    outreach_list, deferred = enforce_outreach_caps(allocated, run_date)
    print(f"  {len(outreach_list)} for outreach, {len(deferred)} deferred")

    # Step 6 calls Bedrock; the demo skips the actual API call by
    # short-circuiting the tailoring helper. Production runs Step 6
    # exactly as defined.
    print("\nStep 6: (Bedrock tailoring skipped in offline demo)")
    print("  In production this would call Bedrock for each member,")
    print("  validate the message, hand to the channel optimizer,")
    print("  update the contact-frequency counter, and emit a")
    print("  program_recommended event to the engagement stream.")

    # ---- Step 7: simulate an engagement event ----
    if allocated:
        print("\n" + "=" * 70)
        print("Simulating engagement event (program_enrolled)...")
        print("=" * 70)
        first_alloc = allocated[0]
        process_engagement_event({
            "event_type":  "program_enrolled",
            "tracking_id": first_alloc["tracking_id"],
            "member_id":   first_alloc["member_id"],
            "program_id":  first_alloc["program_id"],
            "timestamp":   _now_iso(),
        })
        print(f"  Processed program_enrolled for {first_alloc['tracking_id']}")

    # ---- Step 8: outcome evaluation pass ----
    print("\n" + "=" * 70)
    print("Running outcome evaluation (placeholder cohorts)...")
    print("=" * 70)
    eval_results = run_outcome_evaluation(
        SAMPLE_PROGRAMS,
        evaluation_window={
            "start_date": "2025-04-01",
            "end_date":   "2026-03-31",
        },
    )
    print(f"  {len(eval_results)} program evaluations persisted")
```

---

## The Gap Between This and Production

Run this end-to-end against a populated data lake, a seeded patient profile table, trained SageMaker models, a working program catalog, and a configured channel optimizer and you'll see the pattern: members filtered by eligibility, scored on need / engagement / uplift, ranked per-member, allocated under capacity with equity floors, contact-cap-checked, message-tailored, dispatched, and engagement-tracked. The distance between this and a real health-plan deployment is significant. Here's where it lives.

**Uplift training data is the central engineering investment.** The example loads pre-trained uplift models. Real uplift modeling requires either a randomized hold-out arm in a prior cycle (gold standard, expensive in member experience and program capacity, worth it) or careful propensity-score adjustment on observational data. The honest day-one launch path: ship the pipeline with engagement-and-need scoring only; carve out a 10-20 percent randomized hold-out for each program for one or two cohort cycles to generate training data; turn on uplift scoring as the pilot data accrues; document explicitly that the early runs are calibrating, not optimized. Without one of these paths, the "uplift" estimates largely reflect engagement propensity, and the recommender will quietly over-target sure things.

**Propensity-score modeling is its own pipeline.** When a randomized pilot isn't feasible, propensity adjustment is the alternative. Production-grade propensity modeling: train and calibrate the propensity model itself on historical data; audit for overlap (the [propensity overlap assumption](https://en.wikipedia.org/wiki/Propensity_score_matching) requires sufficient density of treated and untreated members at each propensity value); run sensitivity analyses against unobserved-confounder bounds; have a causal-inference specialist review the methodology. This is a multi-quarter investment, not a sprint task.

**SageMaker Feature Store integration.** The example's eligibility step queries a flat data lake. Production reads features from SageMaker Feature Store (offline store for the batch run, online store for any per-member real-time lookup). The features are defined once in feature definitions that Recipes 4.5 and 4.7 reuse; centralizing feature definitions is the entire point of a feature store. Wire feature ingestion through Glue or a Spark job into both the offline (S3 + Glue Data Catalog) and online (DynamoDB-backed) stores, with feature freshness guarantees per source.

**SageMaker Batch Transform output schema.** The example assumes Batch Transform returns CSV that the consolidate function knows how to parse. Production: define an explicit output schema per model (ideally JSONL with named fields), validate it on every job completion, and version the schema alongside the model. A model upgrade that silently changes output column order is a production failure mode that's painful to debug.

**Eligibility SQL via Glue, not application code.** The example builds SQL via string concatenation for clarity. Production uses parameterized queries (Athena's `EXECUTE` with parameters), Jinja templating, or a SQL-construction library like sqlglot. A program with a typo in its eligibility criteria that becomes SQL injection is not the production failure mode you want.

**Athena workgroup and cost controls.** The example references a workgroup but doesn't configure it. Production: each workgroup has a per-query data-scan limit, an output-location enforcement policy (results must go to the encrypted bucket), and a CloudWatch metric on data scanned per query. The eligibility queries are bounded; they should be cheap. A regression that adds a missing WHERE clause and scans the whole data lake is something the workgroup limits should catch.

**Step Functions orchestration of the batch run.** The example chains Steps 1-6 in a single Python function. Production runs the batch as a Step Functions state machine: a Map state for eligibility (one Glue job per program in parallel), a Map state for scoring (three SageMaker Batch Transform jobs per program in parallel), Lambda tasks for ranking / allocation / cap enforcement / dispatch. Each task has Catch handlers routing failures to per-stage SQS DLQs keyed on (run_date, stage, failure_reason); a Step Functions execution that fails partway through can resume from the last successful state. The synchronous chained Python is fine for a demo and unworkable at production scale.

**DLQ coverage on every Lambda path.** None of the architecture's Lambdas in this example have explicit DLQs. Production needs DLQs at three boundaries: Step Functions tasks routing failures via Catch; the Kinesis-to-Lambda event source mapping for the attribution Lambda configured with an `OnFailure` destination pointing to SQS, alarmed on DLQ depth; SageMaker Batch Transform failures wired into the Step Functions Catch since SageMaker doesn't surface failures via DLQ. A silently-dropped engagement event during attribution leaves the model training data incomplete and the dashboards wrong, with no observable symptom until a quarterly evaluation regresses.

**Bedrock cost and latency budget.** The example calls Bedrock once per outreach message (one tailoring call per allocated member). At 10K outreach per week with Haiku-class models, that's manageable. At 100K outreach per week or with Sonnet-class models, it's not. Production deployments cache tailored messages by (program_id, language, cohort_features hash) since many members share the same effective context, and only call Bedrock for the unique cases. Monitor Bedrock spend in CloudWatch and set per-account quota alarms.

**Outreach-message governance.** The validator in the example checks shape and a small blocklist. Production needs an explicit approved-claims list per program (the program's vendor agrees to specific clinical claims), an explicit prohibited-claims list (no curative language, no outcome guarantees, no implicit endorsement of a clinical decision), and a sample-and-review workflow where the medical director reads a sample of generated messages each week. Hallucinated clinical claims in member-facing outreach are an FDA-attention failure mode; the validator and the human-review step are both production-critical.

**Multilingual outreach quality.** The example passes the preferred language to the LLM and trusts the output. Production: per-language regression suites (curated (input_context, expected_output_quality) pairs) that run on every model version change; per-language NDCG and member-feedback dashboards; a low-confidence fallback to the program's default localized template when the LLM output fails validation. Spanish, Mandarin, Vietnamese, and Tagalog have different LLM quality characteristics and different cultural conventions for health communication.

**PCP-EHR integration.** The example "posts" the PCP briefing by logging it. Real EHR integration: Epic, Oracle Health (Cerner), Athena, Veradigm each have their own SMART-on-FHIR or proprietary integration surface. Each requires a purpose-built adapter Lambda (or vendor-managed integration), per-EHR credential management in Secrets Manager, message format mapping, and a write-back path so the PCP's response (endorse, decline, defer) flows back into the engagement stream. The integration work is on the order of months per EHR.

**Vendor reporting reconciliation.** Wellness program vendors supply enrollment, attendance, and completion data on their own cadence and formats: CSVs in SFTP, vendor portal exports, occasional flat files emailed to a shared inbox. The engagement events in this example assume a normalized stream; in reality, a per-vendor ingestion layer with explicit schema validation, reconciliation against the recommendation log, and a dead-letter queue for unmatched records is real work. Build it as one Lambda per vendor, not a single dispatch function, so per-vendor schema drift doesn't take down the whole pipeline.

**Cohort-cycle calendar logic.** The example treats every program the same. Production aligns each program's allocation pass with its specific cohort-cycle cadence (DPP cohorts start monthly on the first Monday, smoking cessation rolls weekly with a Wednesday intake limit, stress reduction starts quarterly). Calendar bugs are some of the most painful production failures; build a `cohort_calendar` data store that the orchestrator consults before each program's allocation pass, and validate the calendar against the vendor contract on a quarterly cadence.

**DynamoDB Decimal gotchas.** The example uses `Decimal(str(value))` consistently when persisting numeric values. The pattern is correct in this code, but the trap is real: if you add a feature that persists a model confidence, an embedding magnitude, or any other floating-point value, you must wrap it at the boundary or DynamoDB will reject the write. Wrap floats in Decimal at the boundary and forget about it.

**Cohort-feature PHI sensitivity.** The recommendation log carries `cohort_features` like `engagement_history_quartile`, `language`, `sdoh_cohort`, `age_band` joined to `member_id`. That join is sensitive: a row indicating a member is in the `low_food_security` cohort or the `q1` engagement-history quartile reveals information that wouldn't appear in a typical claims-derived attribute. Apply customer-managed KMS, CloudTrail data events, narrow IAM read scopes, defined retention (90-180 days for individually-attributed rows; longer only after de-identification). A small SDOH cohort in a specific geography is reidentifiable even without direct identifiers.

**Search-log-style verbatim payload handling.** The example doesn't handle verbatim free-text inputs. If you extend the recommender to consume member-stated preferences ("I'm not interested in group settings"), that free text is PHI: route it to a separate audit channel with stricter access controls and shorter retention, just as Recipe 4.3's example handles search query strings.

**Cost-per-recommended-and-engaged tracking.** The cost numbers in the main recipe's Prerequisites table cover infrastructure. Production reporting needs to ladder up to per-program total cost (infrastructure plus vendor invoices plus internal staff time) divided by engaged-and-completed members. That number is what gets compared to expected long-horizon savings. The data engineering to track this end-to-end is its own project: an FP&A integration that joins infrastructure spend (Cost and Usage Report) to vendor invoice data (typically a separate AP feed) to recommendation-log records, evaluated monthly.

**Synthetic data and testing.** There are no tests in this example. A production pipeline needs unit tests for the eligibility SQL builder, ranker math, allocator with equity floors, cap enforcement; integration tests against a test data lake with synthetic Synthea-generated members across cohort axes; regression tests that confirm hard exclusion rules (already-enrolled, recent-disenroll, no-consent) are never bypassed even when scores prefer those candidates; load tests at expected weekly volumes (80K eligible members across 6 programs); and chaos tests that drop a SageMaker job mid-pipeline and verify Step Functions resumes from the right state. Never use real PHI in non-production environments. [Synthea](https://github.com/synthetichealth/synthea) generates synthetic FHIR patients with realistic claims patterns suitable for the eligibility-and-scoring pipeline.

**Cohort fairness review process.** The architecture emits cohort-sliced metrics, but a dashboard nobody reviews is useless. Establish a quarterly review with a cross-functional committee (data science, equity lead, medical director, vendor management, member services). Watch for: cohorts with consistently lower enrollment-to-completion conversion (signaling poor fit or systematic exclusion), outcome differences by cohort that aren't explained by clinical factors, persistent under-utilization of equity floors, programs where one demographic group experiences null or negative ATE while the aggregate is positive. Each finding should produce an action item with an owner; close the loop or the dashboards become decoration.

**Outcome evaluation methodology rigor.** The example's evaluation function returns placeholder zeros. Production: pre-register the analysis specification before the evaluation runs (define cohort definitions, outcome definitions, and primary statistical test up front), run sensitivity analyses against alternative matching specifications, have a statistical reviewer who is not the team running the recommender, document the methodology in a memo that's signed by the medical director and the equity lead. Without that rigor, the evaluation becomes a marketing artifact rather than an honest assessment.

**VPC, encryption, and audit.** This example calls APIs over public AWS endpoints. A production Lambda handling PHI runs in a VPC with private subnets and VPC endpoints for DynamoDB (gateway), S3 (gateway), Bedrock Runtime (interface), SageMaker Runtime (interface), Kinesis (interface), CloudWatch Logs (interface), Athena (interface), Step Functions (`states`), EventBridge (`events`), STS, and SES. All five DynamoDB tables encrypt at rest with a customer-managed KMS key. CloudTrail data events are enabled for the patient-profile, recommendation-log, engagement-events, and outcome-evaluations tables. A clinical or compliance audit will eventually ask "who was recommended for what on this date" and you need to answer definitively.

**API Gateway and authentication.** The example calls `run_weekly_batch(programs)` directly. Production fronts the recommender's Step Functions trigger with an EventBridge schedule (not API Gateway, because nothing should trigger this batch on demand from outside the platform). The control surface for the operations team to inspect and re-run batches uses a separate API Gateway with Cognito authentication, IAM-based service-to-service authorization, and per-caller rate limits. A misconfigured trigger that re-runs the batch every hour instead of every week is a real failure mode; the schedule and the trigger should be locked down.

**OpenSearch / dashboards / QuickSight.** The example emits CloudWatch metrics. Production also writes cohort-sliced engagement and outcome data to a QuickSight dashboard layer (typically through Athena queries against the data lake). The medical director, equity lead, and operations team consume dashboards, not CloudWatch metric explorers. Building those dashboards is its own work; budget a few weeks for an analytics engineer to land them with row-level security so each consumer sees what they're allowed to see.

**Cold-start handling for new programs.** The example assumes every program has trained engagement and uplift models. A brand-new program has neither. Cold-start strategy: launch new programs with need-and-engagement scoring only (no uplift), run a randomized pilot for the first 1-2 cohort cycles to bootstrap uplift training data, fall back to need-only scoring if the engagement model is underfitting, document explicitly in the recommendation log that the program is in "calibrating" mode. Without this, the recommender will silently over- or under-recommend new programs based on whatever weak signal the partial models produce.

**Member-stated preferences as hard filters.** The example's contact-cap enforcement checks `opt_outs.programs` but doesn't check finer-grained stated preferences (e.g., "I'm not interested in group settings"). Production member portals collect richer preference data; the recommender treats those as hard filters on top of the eligibility step. Track opt-out rates per program (high opt-out rates signal poor program-market fit, not just member preference) and surface them in the equity dashboard.

**Cross-recipe orchestration.** The example focuses on Recipe 4.4. A member who is recommended DPP through this recipe and is also non-adherent to a diabetes prevention medication is a candidate for both a wellness program (here) and an adherence intervention (Recipe 4.5). The cross-recipe orchestrator avoids duplication: typically the adherence intervention precedes or runs alongside the lifestyle program, not in competition. Define explicit interaction rules between recommendations from different chapters, with a thin coordinator Lambda that consults both recommenders and picks at most one outreach per cycle.

**Provider-side / clinician-side correctness.** The example writes a PCP briefing into a log. Real implementations need explicit EHR integration plus a clinician-facing UI that lets the PCP endorse, decline-with-reason, or defer the recommendation. Each of those becomes an engagement event. Without the clinician-facing path, the PCP override pathway is a one-way dropbox and the recommender never learns from it.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 4.4: Wellness Program Recommendations](chapter04.04-wellness-program-recommendations) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
