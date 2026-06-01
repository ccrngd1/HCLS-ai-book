# Recipe 13.6: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 13.6. It shows one way you could translate the care gap reasoning concepts into working Python code using Amazon Neptune (via SPARQL) and boto3. It is not production-ready. The ontology here covers a handful of guidelines to demonstrate the pattern. A real deployment would have hundreds of measures, complex exclusion logic, and significantly more robust error handling. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a SPARQL client:

```bash
pip install boto3 requests
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs access to your Neptune cluster (via VPC networking, not IAM auth for SPARQL), `dynamodb:PutItem`, `dynamodb:Query`, and `s3:GetObject`.

Neptune doesn't use IAM-based authentication for SPARQL by default. Your Lambda or compute instance must be in the same VPC as the Neptune cluster, with security groups allowing port 8182 access. If you've enabled IAM auth on Neptune, you'll need to sign requests with SigV4 (the `amazon-neptune-sigv4-signer` library handles this).

---

## Config and Constants

Before the logic, here's the configuration that drives the reasoning engine. These constants define the guideline rules, condition hierarchies, and scoring parameters. In production, this knowledge lives in the Neptune graph itself. Here we define it both as Python constants (for loading into Neptune) and as reference for the scoring logic.

```python
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal
from typing import Optional

import boto3
import requests
from botocore.config import Config

# Structured logging. Never log PHI field values (patient names, IDs in
# combination with conditions, etc.)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Neptune SPARQL endpoint. This is the cluster endpoint, accessible only
# from within the VPC. Replace with your actual Neptune cluster endpoint.
NEPTUNE_ENDPOINT = "https://your-neptune-cluster.us-east-1.neptune.amazonaws.com:8182/sparql"

# DynamoDB table for storing care gap results.
RESULTS_TABLE = "care-gap-results"

# Retry config for boto3 calls (DynamoDB, S3).
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# Priority scoring thresholds
HIGH_PRIORITY_THRESHOLD = 7.0

# The ontology namespace for our guideline graph.
# All our custom classes and properties live under this prefix.
ONTOLOGY_NS = "http://healthcare-cookbook.example.org/ontology#"

# Prefixes used in SPARQL queries. Defining them once keeps queries readable.
SPARQL_PREFIXES = """
PREFIX ont: <http://healthcare-cookbook.example.org/ontology#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""

# Quality measure weights for priority scoring.
# Higher weight = more impact on Star Ratings or quality bonuses.
# These are illustrative. Real weights come from CMS measure specifications.
MEASURE_WEIGHTS = {
    "HEDIS-CDC-HbA1c": 1.5,       # Diabetes: HbA1c control (triple-weighted in Stars)
    "HEDIS-CDC-Eye": 1.2,          # Diabetes: eye exam
    "HEDIS-SPC": 1.3,              # Statin therapy for cardiovascular
    "HEDIS-BCS": 1.4,              # Breast cancer screening
    "HEDIS-COL": 1.3,              # Colorectal cancer screening
    "HEDIS-CCS": 1.0,              # Cervical cancer screening
    "HEDIS-CBP": 1.2,              # Controlling blood pressure
}

# Default weight for measures not in the lookup table.
DEFAULT_MEASURE_WEIGHT = 1.0
```

---

## Step 1: Load the Guideline Ontology into Neptune

*The main recipe's Step 1 defines the guideline ontology as classes and relationships. Here we load a small set of guidelines into Neptune as RDF triples using the SPARQL UPDATE endpoint. In production, you'd load a full OWL file from S3 using Neptune's bulk loader. This inline approach is for demonstration.*

```python
def load_guideline_ontology(neptune_endpoint: str) -> dict:
    """
    Load a small guideline ontology into Neptune via SPARQL UPDATE.

    This creates the condition hierarchy, recommendation nodes, and the
    relationships between them. In production, you'd use Neptune's bulk
    loader to load a full OWL/RDF file from S3. This inline approach
    demonstrates the structure.

    Returns:
        A dict with status and the number of triples inserted.
    """

    # The ontology defines:
    # 1. Condition class hierarchy (ICD-10 codes -> condition groups)
    # 2. Recommendation nodes with preconditions, actions, and frequencies
    # 3. Action nodes with CPT/LOINC codes that satisfy them

    insert_query = SPARQL_PREFIXES + """
    INSERT DATA {
        # --- Condition Hierarchy ---
        # This is where ontological reasoning pays off. By defining
        # Type2Diabetes as a subclass of DiabetesMellitus, any guideline
        # that applies to DiabetesMellitus automatically applies to
        # Type2Diabetes patients. No explicit rule needed.

        ont:ChronicCondition rdf:type owl:Class .
        ont:DiabetesMellitus rdf:type owl:Class ;
            rdfs:subClassOf ont:ChronicCondition .
        ont:Type2Diabetes rdf:type owl:Class ;
            rdfs:subClassOf ont:DiabetesMellitus ;
            ont:icd10Code "E11" .
        ont:Hypertension rdf:type owl:Class ;
            rdfs:subClassOf ont:ChronicCondition ;
            ont:icd10Code "I10" .
        ont:CardiovascularDisease rdf:type owl:Class ;
            rdfs:subClassOf ont:ChronicCondition .
        ont:CoronaryArteryDisease rdf:type owl:Class ;
            rdfs:subClassOf ont:CardiovascularDisease ;
            ont:icd10Code "I25" .

        # Exclusion conditions
        ont:Hospice rdf:type owl:Class ;
            ont:icd10Code "Z51.5" .
        ont:TerminalIllness rdf:type owl:Class .
        ont:Pregnancy rdf:type owl:Class ;
            ont:icd10Code "Z33" .

        # --- Actions (what should be done) ---
        ont:HbA1cTest rdf:type ont:Action ;
            ont:actionType "lab" ;
            ont:cptCode "83036" ;
            ont:loincCode "4548-4" ;
            ont:description "HbA1c Lab Test" .

        ont:RetinalExam rdf:type ont:Action ;
            ont:actionType "procedure" ;
            ont:cptCode "92004" ;
            ont:description "Dilated Retinal Exam" .

        ont:StatinTherapy rdf:type ont:Action ;
            ont:actionType "medication" ;
            ont:drugClass "statin" ;
            ont:description "Statin Therapy Initiation" .

        ont:BloodPressureCheck rdf:type ont:Action ;
            ont:actionType "procedure" ;
            ont:cptCode "99213" ;
            ont:loincCode "85354-9" ;
            ont:description "Blood Pressure Measurement" .

        # --- Recommendations (the guideline rules) ---
        # Each recommendation links preconditions to an action with a frequency.

        ont:RecDiabetesHbA1c rdf:type ont:Recommendation ;
            ont:recommendationId "rec-diabetes-hba1c" ;
            ont:appliesWhen ont:DiabetesMellitus ;
            ont:recommendedAction ont:HbA1cTest ;
            ont:frequencyMonths 6 ;
            ont:excludedBy ont:Hospice ;
            ont:excludedBy ont:TerminalIllness ;
            ont:measureId "HEDIS-CDC-HbA1c" ;
            ont:priority "high" .

        ont:RecDiabetesRetinal rdf:type ont:Recommendation ;
            ont:recommendationId "rec-diabetes-retinal" ;
            ont:appliesWhen ont:DiabetesMellitus ;
            ont:recommendedAction ont:RetinalExam ;
            ont:frequencyMonths 12 ;
            ont:excludedBy ont:Hospice ;
            ont:measureId "HEDIS-CDC-Eye" ;
            ont:priority "medium" .

        ont:RecASCVDStatin rdf:type ont:Recommendation ;
            ont:recommendationId "rec-ascvd-statin" ;
            ont:appliesWhen ont:DiabetesMellitus ;
            ont:appliesWhen ont:Hypertension ;
            ont:recommendedAction ont:StatinTherapy ;
            ont:frequencyMonths 0 ;
            ont:ageMinimum 40 ;
            ont:excludedBy ont:Pregnancy ;
            ont:measureId "HEDIS-SPC" ;
            ont:priority "high" .

        ont:RecHypertensionBP rdf:type ont:Recommendation ;
            ont:recommendationId "rec-hypertension-bp" ;
            ont:appliesWhen ont:Hypertension ;
            ont:recommendedAction ont:BloodPressureCheck ;
            ont:frequencyMonths 6 ;
            ont:excludedBy ont:Hospice ;
            ont:measureId "HEDIS-CBP" ;
            ont:priority "medium" .
    }
    """

    # Send the SPARQL UPDATE to Neptune.
    response = requests.post(
        neptune_endpoint,
        data={"update": insert_query},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if response.status_code == 200:
        logger.info("Ontology loaded successfully into Neptune")
        return {"status": "success", "triples_loaded": "~50"}
    else:
        logger.error("Failed to load ontology: %s %s", response.status_code, response.text)
        return {"status": "error", "detail": response.text}
```

---

## Step 2: Assemble Patient Facts

*The main recipe's Step 2 gathers the patient's clinical state from multiple data sources. Here we simulate that assembly. In production, this would query claims databases, EHR extracts, and lab feeds via AWS Glue or direct database connections.*

```python
def assemble_patient_facts(patient_id: str) -> dict:
    """
    Assemble a patient's clinical fact set for reasoning.

    In production, this queries multiple data sources:
    - Claims DB for diagnoses and procedures
    - EHR extract for problem lists
    - Lab feeds for recent results
    - Pharmacy data for medications

    Here we return a synthetic patient to demonstrate the pattern.
    The structure is what matters: conditions as ICD-10 codes, services
    with dates and CPT/LOINC codes, medications with fill dates.

    Returns:
        A dict representing the patient's current clinical state.
    """

    # Synthetic patient: 62-year-old male with Type 2 Diabetes and Hypertension.
    # Last HbA1c was 14 months ago. No retinal exam in 18 months.
    # No statin on medication list despite meeting criteria.
    # This patient should trigger 3 care gaps.

    if patient_id == "PAT-2026-00482":
        return {
            "patient_id": "PAT-2026-00482",
            "demographics": {
                "age": 62,
                "sex": "M",
                "enrollment_status": "active",
            },
            "conditions": [
                {"icd10_code": "E11.9", "description": "Type 2 Diabetes without complications"},
                {"icd10_code": "I10", "description": "Essential hypertension"},
            ],
            "recent_services": [
                # HbA1c done 14 months ago (outside the 6-month window)
                {"cpt_code": "83036", "loinc_code": "4548-4", "service_date": "2025-03-10"},
                # Blood pressure check 2 months ago (within 6-month window)
                {"cpt_code": "99213", "loinc_code": "85354-9", "service_date": "2026-03-20"},
                # Retinal exam 18 months ago (outside the 12-month window)
                {"cpt_code": "92004", "loinc_code": None, "service_date": "2024-11-20"},
            ],
            "medications": [
                {"drug_name": "Metformin", "drug_class": "biguanide", "fill_date": "2026-04-15"},
                {"drug_name": "Lisinopril", "drug_class": "ace_inhibitor", "fill_date": "2026-04-15"},
                # Note: no statin in the medication list
            ],
        }

    # Default: empty patient (no data found)
    return {
        "patient_id": patient_id,
        "demographics": {"age": 0, "sex": "unknown", "enrollment_status": "unknown"},
        "conditions": [],
        "recent_services": [],
        "medications": [],
    }
```

---

## Step 3: Query Neptune for Applicable Recommendations

*The main recipe's Step 3 uses ontological reasoning to determine which guidelines apply to a patient. This is where the knowledge graph earns its keep. The SPARQL query leverages rdfs:subClassOf inference so that a patient with E11.9 (Type 2 Diabetes) matches guidelines that apply to DiabetesMellitus (the parent class).*

```python
def find_applicable_recommendations(
    patient_facts: dict, neptune_endpoint: str
) -> list:
    """
    Query Neptune to find all guideline recommendations that apply to this patient.

    The SPARQL query uses ontological reasoning: if the patient has a condition
    that is a subclass of a condition referenced by a recommendation, the
    recommendation applies. This is the core value of the knowledge graph
    approach over flat rule tables.

    We also check:
    - Age constraints (if the recommendation has age_minimum/age_maximum)
    - Exclusion conditions (if the patient has any, skip the recommendation)

    Args:
        patient_facts: The patient's assembled clinical state.
        neptune_endpoint: The Neptune SPARQL endpoint URL.

    Returns:
        A list of applicable recommendations with their metadata.
    """

    # Extract the patient's ICD-10 code prefixes. We use prefixes because
    # ICD-10 codes have varying specificity (E11 vs E11.9 vs E11.65).
    # Our ontology maps at the 3-character level (E11 -> Type2Diabetes).
    patient_condition_codes = [
        c["icd10_code"][:3] for c in patient_facts["conditions"]
    ]

    if not patient_condition_codes:
        logger.info("Patient has no conditions. No recommendations apply.")
        return []

    patient_age = patient_facts["demographics"]["age"]

    # Build a SPARQL query that finds recommendations whose preconditions
    # are satisfied by this patient's conditions.
    #
    # The key insight: we use rdfs:subClassOf* (the transitive closure)
    # so that E11 (Type2Diabetes) matches guidelines targeting DiabetesMellitus.
    # Neptune's reasoner handles this traversal automatically.

    # Build a VALUES clause for the patient's condition codes.
    values_clause = " ".join(f'"{code}"' for code in patient_condition_codes)

    query = SPARQL_PREFIXES + f"""
    SELECT ?rec ?recId ?actionDesc ?freqMonths ?measureId ?priority ?condCode ?excludedByCode
    WHERE {{
        # Find recommendations
        ?rec rdf:type ont:Recommendation ;
             ont:recommendationId ?recId ;
             ont:recommendedAction ?action ;
             ont:frequencyMonths ?freqMonths ;
             ont:measureId ?measureId ;
             ont:priority ?priority ;
             ont:appliesWhen ?appliesCondition .

        ?action ont:description ?actionDesc .

        # Match patient conditions using subclass reasoning.
        # ?appliesCondition is the condition class the recommendation targets.
        # ?patientCondClass is the specific condition class matching the patient's code.
        # rdfs:subClassOf* means "is the same class or a subclass of."
        ?patientCondClass rdfs:subClassOf* ?appliesCondition ;
                          ont:icd10Code ?condCode .

        # Filter to only this patient's conditions
        VALUES ?condCode {{ {values_clause} }}

        # Age check (optional properties)
        OPTIONAL {{ ?rec ont:ageMinimum ?ageMin . }}
        FILTER (!BOUND(?ageMin) || {patient_age} >= ?ageMin)

        OPTIONAL {{ ?rec ont:ageMaximum ?ageMax . }}
        FILTER (!BOUND(?ageMax) || {patient_age} <= ?ageMax)

        # Get exclusion conditions (we'll check these in Python)
        OPTIONAL {{
            ?rec ont:excludedBy ?excludedClass .
            ?excludedClass ont:icd10Code ?excludedByCode .
        }}
    }}
    """

    # Execute the SPARQL query against Neptune.
    response = requests.post(
        neptune_endpoint,
        data={"query": query},
        headers={"Accept": "application/sparql-results+json"},
    )

    if response.status_code != 200:
        logger.error("Neptune query failed: %s", response.text)
        return []

    results = response.json().get("results", {}).get("bindings", [])

    # Process results: group by recommendation and check exclusions.
    recommendations = {}
    exclusions_by_rec = {}

    for row in results:
        rec_id = row["recId"]["value"]

        # Collect exclusion codes for each recommendation
        if "excludedByCode" in row and row["excludedByCode"]["value"]:
            exclusions_by_rec.setdefault(rec_id, set()).add(
                row["excludedByCode"]["value"]
            )

        # Store recommendation details (dedup by rec_id)
        if rec_id not in recommendations:
            recommendations[rec_id] = {
                "recommendation_id": rec_id,
                "action_needed": row["actionDesc"]["value"],
                "frequency_months": int(row["freqMonths"]["value"]),
                "measure_id": row["measureId"]["value"],
                "priority": row["priority"]["value"],
                "triggered_by_code": row["condCode"]["value"],
            }

    # Now check exclusions: if the patient has any excluded condition, remove
    # that recommendation from the applicable list.
    patient_code_prefixes = set(patient_condition_codes)

    applicable = []
    for rec_id, rec in recommendations.items():
        excluded_codes = exclusions_by_rec.get(rec_id, set())
        # Check if any of the patient's conditions match an exclusion
        if excluded_codes & patient_code_prefixes:
            logger.info(
                "Recommendation %s excluded: patient has %s",
                rec_id,
                excluded_codes & patient_code_prefixes,
            )
            continue
        applicable.append(rec)

    logger.info("Found %d applicable recommendations for patient", len(applicable))
    return applicable
```

---

## Step 4: Identify Care Gaps

*The main recipe's Step 4 checks whether each applicable recommendation has been satisfied within the required timeframe. A gap exists when the recommended action hasn't been completed recently enough.*

```python
def identify_gaps(
    applicable_recommendations: list,
    patient_facts: dict,
    evaluation_date: Optional[str] = None,
) -> list:
    """
    For each applicable recommendation, check if the action has been completed
    within the required frequency window. If not, it's a care gap.

    Args:
        applicable_recommendations: Output from find_applicable_recommendations.
        patient_facts: The patient's clinical fact set.
        evaluation_date: ISO date string (YYYY-MM-DD). Defaults to today.

    Returns:
        A list of care gap dicts, each describing a missing action.
    """

    if evaluation_date is None:
        eval_date = datetime.date.today()
    else:
        eval_date = datetime.date.fromisoformat(evaluation_date)

    gaps = []

    for rec in applicable_recommendations:
        freq_months = rec["frequency_months"]

        # frequency_months == 0 means "ongoing" (e.g., should be on a medication).
        # For medication-type actions, we check the medication list instead of services.
        if freq_months == 0:
            # Check if the patient is currently on the recommended medication class.
            # "Currently on" = filled within the last 90 days (approximate).
            action_desc = rec["action_needed"].lower()
            if "statin" in action_desc:
                has_med = any(
                    m["drug_class"] == "statin" for m in patient_facts["medications"]
                )
                if not has_med:
                    gaps.append({
                        "recommendation_id": rec["recommendation_id"],
                        "measure_id": rec["measure_id"],
                        "action_needed": rec["action_needed"],
                        "priority": rec["priority"],
                        "frequency": "ongoing",
                        "last_completed": "never",
                        "days_overdue": None,
                        "justification": [
                            f"Active condition: {rec['triggered_by_code']}"
                        ],
                    })
            continue

        # For time-based recommendations, calculate the cutoff date.
        # Any matching service after this date means the gap is closed.
        cutoff_date = eval_date - datetime.timedelta(days=freq_months * 30)

        # Find services that satisfy this recommendation.
        # Match by CPT code or LOINC code from the recommendation's action.
        # (In production, you'd query the action node in Neptune for its codes.
        # Here we use a simplified lookup.)
        action_codes = _get_action_codes(rec["action_needed"])

        matching_services = [
            s
            for s in patient_facts["recent_services"]
            if (
                s.get("cpt_code") in action_codes.get("cpt", [])
                or s.get("loinc_code") in action_codes.get("loinc", [])
            )
            and datetime.date.fromisoformat(s["service_date"]) >= cutoff_date
        ]

        if not matching_services:
            # Gap found. Find the most recent matching service ever (for context).
            all_matching = [
                s
                for s in patient_facts["recent_services"]
                if (
                    s.get("cpt_code") in action_codes.get("cpt", [])
                    or s.get("loinc_code") in action_codes.get("loinc", [])
                )
            ]

            last_completed = "never"
            days_overdue = None
            if all_matching:
                # Sort by date descending, take the most recent
                most_recent = max(all_matching, key=lambda s: s["service_date"])
                last_completed = most_recent["service_date"]
                last_date = datetime.date.fromisoformat(last_completed)
                days_overdue = (eval_date - cutoff_date).days

            gaps.append({
                "recommendation_id": rec["recommendation_id"],
                "measure_id": rec["measure_id"],
                "action_needed": rec["action_needed"],
                "priority": rec["priority"],
                "frequency": f"{freq_months} months",
                "last_completed": last_completed,
                "days_overdue": days_overdue,
                "justification": [
                    f"Active condition: {rec['triggered_by_code']}"
                ],
            })

    logger.info("Identified %d care gaps", len(gaps))
    return gaps


def _get_action_codes(action_description: str) -> dict:
    """
    Map an action description to its CPT and LOINC codes.

    In production, this information lives in the Neptune graph on the Action
    nodes. Here we use a simple lookup for the demo actions.
    """
    # This is the kind of thing that belongs in the graph, not in code.
    # We're doing it here to keep the example self-contained.
    lookup = {
        "HbA1c Lab Test": {"cpt": ["83036"], "loinc": ["4548-4"]},
        "Dilated Retinal Exam": {"cpt": ["92004", "92014"], "loinc": []},
        "Blood Pressure Measurement": {"cpt": ["99213"], "loinc": ["85354-9"]},
        "Statin Therapy Initiation": {"cpt": [], "loinc": []},
    }
    return lookup.get(action_description, {"cpt": [], "loinc": []})
```

---

## Step 5: Score and Prioritize Gaps

*The main recipe's Step 5 assigns composite priority scores so care managers focus on the highest-impact gaps first.*

```python
def score_gaps(gaps: list, patient_facts: dict) -> list:
    """
    Assign a composite priority score to each gap for outreach prioritization.

    The score combines:
    - Base priority from the guideline (high=3, medium=2, low=1)
    - How overdue the action is (longer overdue = more urgent)
    - Patient comorbidity count (more conditions = higher risk)
    - Quality measure weight (some measures impact Star Ratings more)

    Args:
        gaps: List of care gap dicts from identify_gaps.
        patient_facts: Patient's clinical state (for comorbidity count).

    Returns:
        The same gaps list, sorted by composite_score descending, with
        composite_score added to each gap dict.
    """

    priority_map = {"high": 3, "medium": 2, "low": 1}
    comorbidity_count = len(patient_facts["conditions"])

    for gap in gaps:
        base_score = priority_map.get(gap["priority"], 1)

        # Overdue factor: cap at 2.0 to prevent extreme outliers
        if gap["days_overdue"] is not None and gap["days_overdue"] > 0:
            overdue_factor = min(gap["days_overdue"] / 90.0, 2.0)
        else:
            overdue_factor = 1.0  # "ongoing" gaps (like missing medication)

        # Risk factor based on comorbidity burden
        risk_factor = min(comorbidity_count / 3.0, 2.0)

        # Quality measure weight from our lookup table
        measure_weight = MEASURE_WEIGHTS.get(
            gap["measure_id"], DEFAULT_MEASURE_WEIGHT
        )

        # Composite score formula
        composite = (
            base_score * (1 + overdue_factor) * (1 + risk_factor * 0.3) * measure_weight
        )

        gap["composite_score"] = round(composite, 1)

    # Sort by composite score descending (most urgent first)
    gaps.sort(key=lambda g: g["composite_score"], reverse=True)

    return gaps
```

---

## Step 6: Store Results in DynamoDB

*The main recipe's Step 6 persists the evaluation results for downstream consumption by care management platforms, patient portals, and quality reporting dashboards.*

```python
# Create DynamoDB resource
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)


def store_gap_results(
    patient_id: str,
    evaluation_date: str,
    scored_gaps: list,
    ontology_version: str = "guidelines-2026-v2.1",
) -> dict:
    """
    Write the care gap evaluation results to DynamoDB.

    The record is keyed by patient_id (partition key) and evaluation_date
    (sort key). This supports both point lookups ("what are patient X's
    current gaps?") and range queries ("show me all evaluations for patient X
    over the last year to track gap closure").

    Args:
        patient_id: The patient identifier.
        evaluation_date: ISO date string for this evaluation.
        scored_gaps: The scored and sorted gap list.
        ontology_version: Which guideline version was used (for audit).

    Returns:
        The full record that was written.
    """

    table = dynamodb.Table(RESULTS_TABLE)

    # Convert floats to Decimal for DynamoDB.
    # DynamoDB's SDK rejects Python floats. You must use Decimal for all
    # numeric values. This is a common gotcha that causes TypeError at runtime.
    dynamodb_gaps = []
    for gap in scored_gaps:
        ddb_gap = {k: v for k, v in gap.items()}
        if ddb_gap.get("composite_score") is not None:
            ddb_gap["composite_score"] = Decimal(str(ddb_gap["composite_score"]))
        if ddb_gap.get("days_overdue") is not None:
            ddb_gap["days_overdue"] = Decimal(str(ddb_gap["days_overdue"]))
        dynamodb_gaps.append(ddb_gap)

    record = {
        "patient_id": patient_id,
        "evaluation_date": evaluation_date,
        "gap_count": len(scored_gaps),
        "gaps": dynamodb_gaps,
        "evaluated_at": datetime.datetime.now(timezone.utc).isoformat(),
        "ontology_version": ontology_version,
    }

    table.put_item(Item=record)

    logger.info(
        "Stored %d gaps for patient %s (eval date: %s)",
        len(scored_gaps),
        patient_id,
        evaluation_date,
    )

    return record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what your Lambda handler would call for each patient in a batch evaluation.

```python
def evaluate_patient(patient_id: str, evaluation_date: Optional[str] = None) -> dict:
    """
    Run the full care gap reasoning pipeline for one patient.

    This is the main entry point. In a batch deployment, Step Functions
    would fan out Lambda invocations, each calling this function for a
    different patient.

    Args:
        patient_id: The patient to evaluate.
        evaluation_date: ISO date string. Defaults to today.

    Returns:
        The stored evaluation record with all identified gaps.
    """

    if evaluation_date is None:
        evaluation_date = datetime.date.today().isoformat()

    # Step 2: Assemble patient facts from data sources.
    print(f"Step 2: Assembling facts for patient {patient_id}")
    patient_facts = assemble_patient_facts(patient_id)
    print(f"  Conditions: {len(patient_facts['conditions'])}")
    print(f"  Recent services: {len(patient_facts['recent_services'])}")
    print(f"  Medications: {len(patient_facts['medications'])}")

    # Step 3: Query Neptune for applicable recommendations.
    print("Step 3: Querying Neptune for applicable recommendations")
    applicable = find_applicable_recommendations(patient_facts, NEPTUNE_ENDPOINT)
    print(f"  Found {len(applicable)} applicable recommendations")

    # Step 4: Identify which recommendations are not satisfied (gaps).
    print("Step 4: Identifying care gaps")
    gaps = identify_gaps(applicable, patient_facts, evaluation_date)
    print(f"  Identified {len(gaps)} care gaps")

    # Step 5: Score and prioritize gaps.
    print("Step 5: Scoring and prioritizing gaps")
    scored_gaps = score_gaps(gaps, patient_facts)
    for gap in scored_gaps:
        print(f"  [{gap['composite_score']}] {gap['action_needed']} ({gap['priority']})")

    # Step 6: Store results in DynamoDB.
    print("Step 6: Storing results in DynamoDB")
    result = store_gap_results(patient_id, evaluation_date, scored_gaps)
    print(f"  Stored {result['gap_count']} gaps")

    return result


# Example: evaluate our synthetic patient.
if __name__ == "__main__":
    # Note: This requires Neptune to be running and the ontology loaded (Step 1).
    # For local testing without Neptune, you can mock find_applicable_recommendations
    # to return a static list.

    result = evaluate_patient(
        patient_id="PAT-2026-00482",
        evaluation_date="2026-05-15",
    )

    print("\n--- Final Result ---")
    print(json.dumps(result, indent=2, default=str))
```

---

## The Gap Between This and Production

This example demonstrates the reasoning pattern. Run it against a Neptune cluster with the ontology loaded and it will identify care gaps for the synthetic patient. But there's a meaningful distance between "works with one patient" and "evaluates 50,000 patients nightly for a health plan." Here's where that gap lives:

**Neptune connection management.** This code creates a new HTTP connection for every SPARQL query. A production system uses connection pooling and keep-alive connections. For Lambda, consider initializing the connection outside the handler function so it persists across warm invocations. Neptune also has connection limits per instance type; you'll need to size your cluster for concurrent Lambda invocations.

**Ontology completeness.** We loaded 4 recommendations covering 3 conditions. A real HEDIS measure set has 40+ measures, each with multiple inclusion criteria, exclusion criteria, and value sets (lists of valid CPT/LOINC codes). Building and maintaining the full ontology is a clinical informatics project, not a coding task. Budget 4-8 weeks for initial ontology development with a clinical informaticist.

**Error handling.** If Neptune is unreachable, this code crashes. A production system retries with backoff, falls back gracefully (maybe returning "evaluation incomplete" rather than failing silently), and alerts on repeated failures. Neptune maintenance windows are a real thing; your batch jobs need to handle them.

**Claims data lag.** We used hardcoded service dates. In reality, claims data arrives 30-90 days after the service. A gap identified today might already be closed by a service performed last week. Track your false positive rate and consider supplementing claims with real-time ADT feeds or EHR integrations.

**Batch orchestration.** Evaluating one patient is straightforward. Evaluating 50,000 requires Step Functions to partition the patient list, fan out Lambda invocations (100 concurrent is a reasonable starting point), handle partial failures, and produce summary reports. The Step Functions Map state handles this pattern well.

**IAM and VPC.** The Lambda needs to be in the same VPC as Neptune (Neptune has no public endpoint). It also needs VPC endpoints for DynamoDB and CloudWatch Logs to avoid routing traffic through a NAT gateway. The IAM role should be scoped to exactly the Neptune cluster ARN, the specific DynamoDB table, and the specific S3 bucket for ontology files.

**Ontology versioning.** When guidelines update (annually for HEDIS), you need to load the new ontology version, validate it against test patients with known expected gaps, and then swap it into production. Keep the old version available for audit queries ("what gaps did we identify under the 2025 guidelines?"). S3 versioning on the ontology files plus a version tag in the Neptune graph handles this.

**DynamoDB data types.** This example already wraps numeric values in `Decimal` (see Step 6), but be aware that any new numeric fields you add must also use `Decimal`. The boto3 DynamoDB resource layer raises a `TypeError` on raw floats in `put_item` calls. The `json.dumps(default=str)` pattern in the main block is a convenience for printing, not for DynamoDB writes.

**Testing.** There are no tests here. A production pipeline has unit tests for the scoring logic, integration tests against Neptune with a known ontology and synthetic patients with expected gap counts, and regression tests that run whenever the ontology is updated. Use Synthea or CMS Synthetic Medicare data for test populations. Never use real PHI in test environments.

**SPARQL query optimization.** The query in Step 3 works but isn't optimized for large ontologies. Neptune's query optimizer handles most cases well, but for complex ontologies with deep hierarchies, you may need to materialize inferred triples (pre-compute the subclass relationships) rather than relying on runtime reasoning. Neptune's DFE (Data Flow Engine) mode helps with this.

**Exclusion completeness.** We check exclusions by ICD-10 code prefix. Real exclusion logic is more nuanced: "patient declined" is often documented in free text, not coded. "Hospice" might be an encounter type rather than a diagnosis code. Some exclusions are temporary (pregnancy) and need date-aware logic. Start with the exclusions that are reliably coded and accept that some will require manual review.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 13.6](chapter13.06-care-gap-reasoning-engine) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
