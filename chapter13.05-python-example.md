# Recipe 13.5: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 13.5. It shows one way you could translate clinical pathway graph modeling into working Python code using boto3, Neptune's openCypher endpoint, and DynamoDB for patient state tracking. It is not production-ready. There's no connection pooling, no retry logic beyond boto3 defaults, no input validation, no proper error handling. Think of it as the sketchpad version: useful for understanding how clinical pathways become traversable graphs and how patient state advances through them, not something you'd deploy to a hospital CDS system on Monday morning. A starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python and a few supporting libraries:

```bash
pip install boto3 requests
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs permissions for Neptune (`neptune-db:ReadDataViaQuery`, `neptune-db:WriteDataViaQuery` scoped to your cluster), DynamoDB (`dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`), S3 (`s3:PutObject` for pathway version storage), and network access to Neptune from within your VPC.

Neptune doesn't use IAM for query authentication by default (it uses VPC-level network isolation). If you've enabled IAM auth on your cluster, you'll need to sign requests with SigV4. This example assumes VPC network access without IAM auth for simplicity.

---

## Config and Constants

Before we get to the steps, here's the configuration that drives the pipeline. These constants define the Neptune endpoint, the pathway graph schema, and the condition evaluation logic that determines when a patient advances along a pathway.

```python
import boto3
import json
import logging
import requests
from datetime import datetime, timezone, timedelta
from decimal import Decimal

# Configure logging. In production, use structured JSON logging
# for CloudWatch Logs Insights queries.
# PHI Safety: Patient pathway state references patient identifiers.
# Never log patient IDs alongside clinical data in the same log entry.
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Neptune cluster endpoint. Use the writer endpoint for loads,
# reader endpoint for queries. In production, separate these.
#
# Neptune runs inside your VPC. This code must execute from within
# the same VPC (Lambda in VPC, EC2, ECS, etc.) to reach it.
NEPTUNE_WRITER_ENDPOINT = "your-neptune-cluster.cluster-xxxxxxxxxxxx.us-east-1.neptune.amazonaws.com"
NEPTUNE_READER_ENDPOINT = "your-neptune-cluster.cluster-ro-xxxxxxxxxxxx.us-east-1.neptune.amazonaws.com"
NEPTUNE_PORT = 8182

# Neptune exposes openCypher queries via HTTPS POST to this path.
NEPTUNE_WRITER_URL = f"https://{NEPTUNE_WRITER_ENDPOINT}:{NEPTUNE_PORT}/openCypher"
NEPTUNE_READER_URL = f"https://{NEPTUNE_READER_ENDPOINT}:{NEPTUNE_PORT}/openCypher"

# DynamoDB table for patient pathway state.
# Partition key: patient_id (String)
# Sort key: pathway_id (String)
PATIENT_STATE_TABLE = "patient-pathway-state"

# S3 bucket for versioned pathway definitions.
PATHWAY_VERSIONS_BUCKET = "clinical-pathways"

# AWS region for all service calls.
AWS_REGION = "us-east-1"

# How often the overdue-check Lambda runs (minutes).
# Used for logging context, not for scheduling (EventBridge handles that).
OVERDUE_CHECK_INTERVAL_MINUTES = 15

# Valid node types in the pathway graph.
# Each type has different semantics for traversal and completion.
NODE_TYPES = [
    "start",                # Entry point. Exactly one per pathway.
    "assessment",           # Clinician evaluates something (e.g., calculate CURB-65).
    "order",               # Place a clinical order (labs, meds, imaging).
    "decision_point",      # Branch based on conditions. Must have 2+ outgoing edges.
    "milestone",           # Marker for progress tracking (no action required).
    "discharge_criterion", # Terminal node. Patient meets discharge criteria.
]

# Valid edge types connecting pathway nodes.
EDGE_TYPES = [
    "sequential",      # Must happen in order. No conditions beyond completion.
    "conditional",     # Taken only if conditions are met. Exclusive with siblings.
    "time_gated",      # Available only after elapsed time threshold.
    "parallel_start",  # Begins a parallel branch (multiple paths active).
    "parallel_join",   # Waits for all parallel branches to complete.
]

# Valid condition types for edge evaluation.
CONDITION_TYPES = [
    "lab_value",            # Compare a lab result against a threshold.
    "vital_sign",           # Compare a vital sign against a threshold.
    "elapsed_time",         # Hours since entering current node.
    "assessment_complete",  # A specific assessment has been documented.
    "order_placed",         # A specific order has been placed.
    "allergy_check",        # Patient has (or doesn't have) a specific allergy.
    "diagnosis_present",    # Patient has a specific diagnosis on their problem list.
]

# Comparison operators for conditions.
OPERATORS = ["gt", "gte", "lt", "lte", "eq", "neq", "exists", "not_exists"]
```

---

## Step 1: Model the Pathway as a Graph

*The pseudocode calls this the pathway schema definition. Before any Neptune queries happen, you need a structured representation of a clinical pathway that can be loaded into the graph database. This step defines the data structures and builds a sample pneumonia pathway.*

```python
def build_sample_pneumonia_pathway() -> dict:
    """
    Build a simplified community-acquired pneumonia pathway as a graph structure.

    This is a teaching example. A real pathway would have 30-50 nodes with
    complex branching. This one has 8 nodes to keep the traversal logic clear.

    The pathway models:
    1. Initial assessment and severity scoring
    2. Branching based on severity (mild vs. moderate/severe)
    3. Antibiotic initiation with time constraint
    4. 48-hour reassessment with step-down or escalation branches
    5. Discharge criteria

    Returns:
        A dictionary with 'nodes' and 'edges' lists ready for Neptune loading.
    """

    pathway_id = "community-acquired-pneumonia"
    pathway_version = 3

    nodes = [
        {
            "id": f"{pathway_id}-v{pathway_version}-start",
            "pathway_id": pathway_id,
            "pathway_version": pathway_version,
            "node_type": "start",
            "name": "Patient Presents with Suspected Pneumonia",
            "description": "Patient admitted with respiratory symptoms suggestive of CAP",
            "responsible_role": "physician",
            "expected_duration_hours": None,
            "parallel_group": None,
        },
        {
            "id": f"{pathway_id}-v{pathway_version}-assess-severity",
            "pathway_id": pathway_id,
            "pathway_version": pathway_version,
            "node_type": "assessment",
            "name": "Calculate CURB-65 Score",
            "description": "Assess confusion, urea, respiratory rate, blood pressure, age >= 65",
            "responsible_role": "physician",
            "expected_duration_hours": 1.0,
            "parallel_group": None,
        },
        {
            "id": f"{pathway_id}-v{pathway_version}-decision-severity",
            "pathway_id": pathway_id,
            "pathway_version": pathway_version,
            "node_type": "decision_point",
            "name": "Severity-Based Disposition",
            "description": "Route patient based on CURB-65 score",
            "responsible_role": "physician",
            "expected_duration_hours": None,
            "parallel_group": None,
        },
        {
            "id": f"{pathway_id}-v{pathway_version}-admit-ward",
            "pathway_id": pathway_id,
            "pathway_version": pathway_version,
            "node_type": "milestone",
            "name": "Admit to Ward",
            "description": "CURB-65 score 2: admit to general medical ward",
            "responsible_role": "physician",
            "expected_duration_hours": None,
            "parallel_group": None,
        },
        {
            "id": f"{pathway_id}-v{pathway_version}-start-antibiotics",
            "pathway_id": pathway_id,
            "pathway_version": pathway_version,
            "node_type": "order",
            "name": "Start Empiric Antibiotics",
            "description": "Initiate guideline-concordant antibiotics within 4 hours of presentation",
            "responsible_role": "physician",
            "expected_duration_hours": 4.0,
            "parallel_group": None,
        },
        {
            "id": f"{pathway_id}-v{pathway_version}-reassess-48h",
            "pathway_id": pathway_id,
            "pathway_version": pathway_version,
            "node_type": "assessment",
            "name": "Reassess Clinical Response",
            "description": "Evaluate temperature trend, WBC, respiratory status at 48 hours",
            "responsible_role": "physician",
            "expected_duration_hours": 48.0,
            "parallel_group": None,
        },
        {
            "id": f"{pathway_id}-v{pathway_version}-step-down-oral",
            "pathway_id": pathway_id,
            "pathway_version": pathway_version,
            "node_type": "order",
            "name": "Step Down to Oral Antibiotics",
            "description": "Switch from IV to oral antibiotics if clinical improvement criteria met",
            "responsible_role": "physician",
            "expected_duration_hours": None,
            "parallel_group": None,
        },
        {
            "id": f"{pathway_id}-v{pathway_version}-discharge",
            "pathway_id": pathway_id,
            "pathway_version": pathway_version,
            "node_type": "discharge_criterion",
            "name": "Discharge Criteria Met",
            "description": "Afebrile 24h, tolerating oral meds, O2 sat stable on room air",
            "responsible_role": "physician",
            "expected_duration_hours": 24.0,
            "parallel_group": None,
        },
    ]

    edges = [
        {
            "from_node": f"{pathway_id}-v{pathway_version}-start",
            "to_node": f"{pathway_id}-v{pathway_version}-assess-severity",
            "edge_type": "sequential",
            "conditions": [],
            "priority": 1,
            "max_time_hours": 2.0,  # Severity assessment should happen within 2 hours
        },
        {
            "from_node": f"{pathway_id}-v{pathway_version}-assess-severity",
            "to_node": f"{pathway_id}-v{pathway_version}-decision-severity",
            "edge_type": "sequential",
            "conditions": [
                {"condition_type": "assessment_complete", "parameter": "curb65_score",
                 "operator": "exists", "value": None, "time_window_hours": None}
            ],
            "priority": 1,
            "max_time_hours": None,
        },
        {
            # Moderate severity branch: CURB-65 score >= 2
            "from_node": f"{pathway_id}-v{pathway_version}-decision-severity",
            "to_node": f"{pathway_id}-v{pathway_version}-admit-ward",
            "edge_type": "conditional",
            "conditions": [
                {"condition_type": "lab_value", "parameter": "curb65_score",
                 "operator": "gte", "value": "2", "time_window_hours": 4}
            ],
            "priority": 1,
            "max_time_hours": None,
        },
        {
            "from_node": f"{pathway_id}-v{pathway_version}-admit-ward",
            "to_node": f"{pathway_id}-v{pathway_version}-start-antibiotics",
            "edge_type": "sequential",
            "conditions": [],
            "priority": 1,
            "max_time_hours": 4.0,  # Antibiotics within 4 hours of presentation
        },
        {
            "from_node": f"{pathway_id}-v{pathway_version}-start-antibiotics",
            "to_node": f"{pathway_id}-v{pathway_version}-reassess-48h",
            "edge_type": "time_gated",
            "conditions": [
                {"condition_type": "elapsed_time", "parameter": "hours_since_antibiotics",
                 "operator": "gte", "value": "48", "time_window_hours": None}
            ],
            "priority": 1,
            "max_time_hours": 72.0,  # Overdue if not reassessed by 72 hours
        },
        {
            # Improving: step down to oral
            "from_node": f"{pathway_id}-v{pathway_version}-reassess-48h",
            "to_node": f"{pathway_id}-v{pathway_version}-step-down-oral",
            "edge_type": "conditional",
            "conditions": [
                {"condition_type": "vital_sign", "parameter": "temperature",
                 "operator": "lt", "value": "38.0", "time_window_hours": 24},
                {"condition_type": "lab_value", "parameter": "wbc",
                 "operator": "lt", "value": "12.0", "time_window_hours": 24},
            ],
            "priority": 1,
            "max_time_hours": None,
        },
        {
            "from_node": f"{pathway_id}-v{pathway_version}-step-down-oral",
            "to_node": f"{pathway_id}-v{pathway_version}-discharge",
            "edge_type": "time_gated",
            "conditions": [
                {"condition_type": "vital_sign", "parameter": "temperature",
                 "operator": "lt", "value": "38.0", "time_window_hours": 24},
                {"condition_type": "vital_sign", "parameter": "spo2",
                 "operator": "gte", "value": "92", "time_window_hours": 4},
            ],
            "priority": 1,
            "max_time_hours": None,
        },
    ]

    return {
        "pathway_id": pathway_id,
        "pathway_version": pathway_version,
        "nodes": nodes,
        "edges": edges,
    }
```

---

## Step 2: Load Pathway into Neptune

*The pseudocode calls this `load_pathway_to_neptune(pathway_definition)`. It takes the structured pathway definition and creates vertices and edges in Neptune using openCypher queries. The loading process validates graph integrity before writing anything.*

```python
def execute_cypher(query: str, parameters: dict = None, use_writer: bool = True) -> dict:
    """
    Execute an openCypher query against Neptune.

    Neptune's openCypher endpoint accepts POST requests with the query
    as form data. Parameters are passed as a JSON-encoded string.

    Args:
        query: The openCypher query string.
        parameters: Optional dict of query parameters (Neptune substitutes these safely).
        use_writer: If True, use the writer endpoint. If False, use the reader.

    Returns:
        The parsed JSON response from Neptune.
    """
    url = NEPTUNE_WRITER_URL if use_writer else NEPTUNE_READER_URL

    payload = {"query": query}
    if parameters:
        payload["parameters"] = json.dumps(parameters)

    response = requests.post(url, data=payload)
    response.raise_for_status()
    return response.json()


def validate_pathway(pathway_def: dict) -> list:
    """
    Validate a pathway definition before loading it into Neptune.

    Catches structural errors here rather than discovering them at query time.
    Returns a list of error strings. Empty list means valid.
    """
    errors = []
    node_ids = {n["id"] for n in pathway_def["nodes"]}
    node_types = {n["id"]: n["node_type"] for n in pathway_def["nodes"]}

    # Check for exactly one start node.
    start_nodes = [n for n in pathway_def["nodes"] if n["node_type"] == "start"]
    if len(start_nodes) != 1:
        errors.append(f"Expected exactly 1 start node, found {len(start_nodes)}")

    # Check for at least one terminal node.
    terminal_nodes = [n for n in pathway_def["nodes"]
                      if n["node_type"] == "discharge_criterion"]
    if len(terminal_nodes) == 0:
        errors.append("No terminal (discharge_criterion) nodes found")

    # Check all edges reference existing nodes.
    for edge in pathway_def["edges"]:
        if edge["from_node"] not in node_ids:
            errors.append(f"Edge references non-existent from_node: {edge['from_node']}")
        if edge["to_node"] not in node_ids:
            errors.append(f"Edge references non-existent to_node: {edge['to_node']}")

    # Check decision points have at least 2 outgoing conditional edges.
    decision_points = [n["id"] for n in pathway_def["nodes"]
                       if n["node_type"] == "decision_point"]
    for dp_id in decision_points:
        outgoing = [e for e in pathway_def["edges"]
                    if e["from_node"] == dp_id and e["edge_type"] == "conditional"]
        if len(outgoing) < 2:
            errors.append(
                f"Decision point {dp_id} has {len(outgoing)} conditional edges (need >= 2)"
            )

    return errors


def load_pathway_to_neptune(pathway_def: dict) -> dict:
    """
    Load a validated pathway definition into Neptune as a property graph.

    Creates one vertex per pathway node and one edge per transition.
    Conditions are stored as JSON-serialized properties on edges.

    Args:
        pathway_def: The pathway definition dict from build_sample_pneumonia_pathway().

    Returns:
        A summary dict with counts of nodes and edges created.
    """
    # Validate first. Refuse to load a broken graph.
    errors = validate_pathway(pathway_def)
    if errors:
        raise ValueError(f"Pathway validation failed: {errors}")

    nodes_created = 0
    edges_created = 0

    # Create vertices for each pathway node.
    # MERGE is idempotent: if the node already exists (same id), it updates properties
    # rather than creating a duplicate. Safe for re-loading updated pathways.
    for node in pathway_def["nodes"]:
        query = """
        MERGE (n:PathwayNode {id: $id})
        SET n.pathway_id = $pathway_id,
            n.pathway_version = $pathway_version,
            n.node_type = $node_type,
            n.name = $name,
            n.description = $description,
            n.responsible_role = $responsible_role,
            n.expected_duration_hours = $expected_duration_hours,
            n.parallel_group = $parallel_group
        RETURN n.id
        """
        params = {
            "id": node["id"],
            "pathway_id": node["pathway_id"],
            "pathway_version": node["pathway_version"],
            "node_type": node["node_type"],
            "name": node["name"],
            "description": node["description"],
            "responsible_role": node["responsible_role"],
            "expected_duration_hours": node["expected_duration_hours"],
            "parallel_group": node["parallel_group"],
        }
        execute_cypher(query, params)
        nodes_created += 1

    # Create edges for each transition.
    # Conditions are serialized as JSON strings on the edge property.
    # Neptune doesn't support nested objects as properties natively,
    # so JSON serialization is the standard workaround.
    for edge in pathway_def["edges"]:
        query = """
        MATCH (from:PathwayNode {id: $from_id})
        MATCH (to:PathwayNode {id: $to_id})
        MERGE (from)-[e:TRANSITION {from_id: $from_id, to_id: $to_id}]->(to)
        SET e.edge_type = $edge_type,
            e.conditions = $conditions,
            e.priority = $priority,
            e.max_time_hours = $max_time_hours
        RETURN e.edge_type
        """
        params = {
            "from_id": edge["from_node"],
            "to_id": edge["to_node"],
            "edge_type": edge["edge_type"],
            "conditions": json.dumps(edge["conditions"]),
            "priority": edge["priority"],
            "max_time_hours": edge["max_time_hours"],
        }
        execute_cypher(query, params)
        edges_created += 1

    logger.info(
        "Loaded pathway %s v%d: %d nodes, %d edges",
        pathway_def["pathway_id"], pathway_def["pathway_version"],
        nodes_created, edges_created
    )

    return {"nodes_created": nodes_created, "edges_created": edges_created}
```

---

## Step 3: Initialize Patient on Pathway

*The pseudocode calls this `initialize_patient_on_pathway(patient_id, pathway_id, pathway_version)`. When a patient is enrolled on a pathway (manually or triggered by admission diagnosis), this creates their state record in DynamoDB tracking their current position.*

```python
# Create a DynamoDB resource. boto3 will use your configured credentials.
dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
patient_state_table = dynamodb.Table(PATIENT_STATE_TABLE)


def get_start_node_id(pathway_id: str, pathway_version: int) -> str:
    """
    Query Neptune for the start node of a specific pathway version.

    Every pathway has exactly one start node (validated during loading).
    """
    query = """
    MATCH (n:PathwayNode {pathway_id: $pathway_id, pathway_version: $version, node_type: 'start'})
    RETURN n.id AS start_id
    """
    result = execute_cypher(query, {"pathway_id": pathway_id, "version": pathway_version},
                            use_writer=False)

    # Neptune returns results in a 'results' list with column bindings.
    rows = result.get("results", [])
    if not rows:
        raise ValueError(f"No start node found for {pathway_id} v{pathway_version}")

    return rows[0]["start_id"]


def initialize_patient_on_pathway(patient_id: str, pathway_id: str,
                                   pathway_version: int) -> dict:
    """
    Enroll a patient on a clinical pathway by creating their state record.

    The patient starts at the pathway's start node. Their state record tracks:
    - Which nodes are currently active (they can be at multiple nodes in parallel branches)
    - When they entered each active node (for elapsed time calculations)
    - Which nodes and edges they've completed (for compliance tracking)

    Args:
        patient_id: Unique patient identifier (e.g., MRN or encounter ID).
        pathway_id: Which pathway to enroll on.
        pathway_version: Which version of the pathway (patients stay on their enrolled version).

    Returns:
        The created state record.
    """
    start_node_id = get_start_node_id(pathway_id, pathway_version)
    now = datetime.now(timezone.utc).isoformat()

    state_record = {
        "patient_id": patient_id,
        "pathway_id": pathway_id,
        "pathway_version": pathway_version,
        "enrolled_at": now,
        "active_nodes": [start_node_id],
        "node_entry_times": {start_node_id: now},
        "completed_nodes": [],
        "completed_edges": [],
        "status": "active",
    }

    # Write to DynamoDB. put_item creates or overwrites.
    # In production, add a ConditionExpression to prevent accidental re-enrollment.
    patient_state_table.put_item(Item=state_record)

    logger.info(
        "Enrolled patient %s on pathway %s v%d at node %s",
        patient_id, pathway_id, pathway_version, start_node_id
    )

    return state_record
```

---

## Step 4: Evaluate Transitions on Clinical Events

*The pseudocode calls this `on_clinical_event(event)` and `evaluate_conditions(conditions, patient_id, node_entry_time)`. This is the core reasoning step: when a clinical event occurs, check whether any transitions from the patient's current nodes are now satisfiable.*

```python
def get_outgoing_edges(node_id: str) -> list:
    """
    Query Neptune for all outgoing transitions from a given node,
    ordered by priority (lower number = evaluated first).
    """
    query = """
    MATCH (from:PathwayNode {id: $node_id})-[e:TRANSITION]->(to:PathwayNode)
    RETURN e.edge_type AS edge_type,
           e.conditions AS conditions,
           e.priority AS priority,
           e.max_time_hours AS max_time_hours,
           to.id AS to_node_id,
           to.name AS to_node_name,
           to.node_type AS to_node_type
    ORDER BY e.priority ASC
    """
    result = execute_cypher(query, {"node_id": node_id}, use_writer=False)
    return result.get("results", [])


def get_patient_clinical_data(patient_id: str) -> dict:
    """
    Fetch current clinical data for a patient.

    In a real system, this calls the EHR's FHIR API or reads from a
    clinical data cache. For this example, we return mock data that
    demonstrates the condition evaluation logic.

    Returns a dict with keys like:
        "labs": {"wbc": {"value": 9.2, "timestamp": "..."}, ...}
        "vitals": {"temperature": {"value": 37.1, "timestamp": "..."}, ...}
        "assessments": {"curb65_score": {"value": 2, "timestamp": "..."}, ...}
        "allergies": ["penicillin", ...]
        "diagnoses": ["J18.9", ...]
    """
    # TODO: Replace with actual EHR integration (FHIR R4 API call or clinical data cache).
    # This mock data represents a patient who is improving at 48 hours.
    return {
        "labs": {
            "wbc": {"value": 9.2, "timestamp": datetime.now(timezone.utc).isoformat()},
            "creatinine": {"value": 1.1, "timestamp": datetime.now(timezone.utc).isoformat()},
        },
        "vitals": {
            "temperature": {"value": 37.1, "timestamp": datetime.now(timezone.utc).isoformat()},
            "spo2": {"value": 95, "timestamp": datetime.now(timezone.utc).isoformat()},
            "respiratory_rate": {"value": 18, "timestamp": datetime.now(timezone.utc).isoformat()},
        },
        "assessments": {
            "curb65_score": {"value": 2, "timestamp": datetime.now(timezone.utc).isoformat()},
        },
        "allergies": [],
        "diagnoses": ["J18.9"],  # Community-acquired pneumonia, unspecified organism
    }


def compare_values(actual, operator: str, threshold) -> bool:
    """
    Apply a comparison operator between an actual value and a threshold.

    Both values are coerced to float for numeric comparisons.
    For 'exists'/'not_exists', only the presence of actual matters.
    """
    if operator == "exists":
        return actual is not None
    if operator == "not_exists":
        return actual is None

    # Coerce to float for numeric comparison.
    try:
        actual_num = float(actual)
        threshold_num = float(threshold)
    except (TypeError, ValueError):
        return False

    if operator == "gt":
        return actual_num > threshold_num
    elif operator == "gte":
        return actual_num >= threshold_num
    elif operator == "lt":
        return actual_num < threshold_num
    elif operator == "lte":
        return actual_num <= threshold_num
    elif operator == "eq":
        return actual_num == threshold_num
    elif operator == "neq":
        return actual_num != threshold_num

    return False


def evaluate_conditions(conditions: list, patient_id: str,
                        node_entry_time: str) -> bool:
    """
    Evaluate all conditions on an edge against current patient data.

    ALL conditions must be true for the transition to fire (AND logic).
    If any condition fails, the transition is not available.

    Args:
        conditions: List of condition dicts from the edge properties.
        patient_id: The patient to evaluate for.
        node_entry_time: ISO timestamp of when the patient entered the current node.

    Returns:
        True if all conditions are satisfied, False otherwise.
    """
    if not conditions:
        # No conditions means unconditional transition (sequential edges).
        return True

    clinical_data = get_patient_clinical_data(patient_id)

    for condition in conditions:
        ctype = condition["condition_type"]
        param = condition["parameter"]
        operator = condition["operator"]
        value = condition.get("value")

        if ctype == "lab_value":
            # Check if the lab value meets the threshold.
            lab = clinical_data.get("labs", {}).get(param)
            # Also check assessments (CURB-65 is stored there in our mock).
            if lab is None:
                lab = clinical_data.get("assessments", {}).get(param)
            if lab is None:
                return False
            if not compare_values(lab["value"], operator, value):
                return False

        elif ctype == "vital_sign":
            vital = clinical_data.get("vitals", {}).get(param)
            if vital is None:
                return False
            if not compare_values(vital["value"], operator, value):
                return False

        elif ctype == "elapsed_time":
            # Calculate hours since entering the current node.
            entry = datetime.fromisoformat(node_entry_time)
            elapsed_hours = (datetime.now(timezone.utc) - entry).total_seconds() / 3600
            if not compare_values(elapsed_hours, operator, value):
                return False

        elif ctype == "assessment_complete":
            assessment = clinical_data.get("assessments", {}).get(param)
            if operator == "exists" and assessment is None:
                return False
            if operator == "not_exists" and assessment is not None:
                return False

        elif ctype == "allergy_check":
            allergies = clinical_data.get("allergies", [])
            has_allergy = param.lower() in [a.lower() for a in allergies]
            if operator == "exists" and not has_allergy:
                return False
            if operator == "not_exists" and has_allergy:
                return False

        elif ctype == "diagnosis_present":
            diagnoses = clinical_data.get("diagnoses", [])
            has_dx = param in diagnoses
            if operator == "exists" and not has_dx:
                return False
            if operator == "not_exists" and has_dx:
                return False

        elif ctype == "order_placed":
            # TODO: Integrate with order status API.
            pass

    return True


def advance_patient_state(patient_id: str, pathway_id: str,
                          completed_node_id: str, next_node_id: str) -> None:
    """
    Atomically advance a patient from one pathway node to the next.

    Uses DynamoDB update expressions to ensure atomic state transitions.
    In production, add a ConditionExpression to prevent race conditions
    (two events trying to advance the same node simultaneously).
    """
    now = datetime.now(timezone.utc).isoformat()

    # Read current state to manipulate lists.
    # (In production, use update expressions with list_append and list_remove
    # for true atomicity. This read-modify-write is simpler to understand.)
    response = patient_state_table.get_item(
        Key={"patient_id": patient_id, "pathway_id": pathway_id}
    )
    state = response["Item"]

    # Move from completed node to next node.
    active_nodes = state["active_nodes"]
    if completed_node_id in active_nodes:
        active_nodes.remove(completed_node_id)
    active_nodes.append(next_node_id)

    # Track completion.
    completed_nodes = state.get("completed_nodes", [])
    completed_nodes.append(completed_node_id)

    completed_edges = state.get("completed_edges", [])
    completed_edges.append({
        "from": completed_node_id,
        "to": next_node_id,
        "at": now,
    })

    # Update entry times.
    node_entry_times = state.get("node_entry_times", {})
    node_entry_times[next_node_id] = now

    # Write back.
    patient_state_table.update_item(
        Key={"patient_id": patient_id, "pathway_id": pathway_id},
        UpdateExpression=(
            "SET active_nodes = :active, completed_nodes = :completed, "
            "completed_edges = :edges, node_entry_times = :times"
        ),
        ExpressionAttributeValues={
            ":active": active_nodes,
            ":completed": completed_nodes,
            ":edges": completed_edges,
            ":times": node_entry_times,
        },
    )

    logger.info(
        "Advanced patient %s on %s: %s -> %s",
        patient_id, pathway_id, completed_node_id, next_node_id
    )


def on_clinical_event(event: dict) -> list:
    """
    Process a clinical event and advance patient pathway state if transitions are satisfied.

    Called by EventBridge when a lab result posts, an order completes,
    or an assessment is documented.

    Args:
        event: Dict with at least 'patient_id' and 'event_type'.

    Returns:
        List of transitions that fired (for logging/alerting).
    """
    patient_id = event["patient_id"]
    transitions_fired = []

    # Get all active pathway enrollments for this patient.
    response = patient_state_table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("patient_id").eq(patient_id),
        FilterExpression=boto3.dynamodb.conditions.Attr("status").eq("active"),
    )

    for state in response.get("Items", []):
        pathway_id = state["pathway_id"]

        for active_node_id in list(state["active_nodes"]):
            # Get outgoing edges from this node.
            outgoing = get_outgoing_edges(active_node_id)
            node_entry_time = state["node_entry_times"].get(active_node_id, state["enrolled_at"])

            for edge in outgoing:
                conditions = json.loads(edge["conditions"]) if edge["conditions"] else []

                conditions_met = evaluate_conditions(
                    conditions, patient_id, node_entry_time
                )

                if conditions_met:
                    advance_patient_state(
                        patient_id, pathway_id,
                        active_node_id, edge["to_node_id"]
                    )
                    transitions_fired.append({
                        "pathway_id": pathway_id,
                        "from_node": active_node_id,
                        "to_node": edge["to_node_id"],
                        "to_node_name": edge["to_node_name"],
                        "edge_type": edge["edge_type"],
                    })

                    # For conditional edges (exclusive branches), stop after first match.
                    if edge["edge_type"] == "conditional":
                        break

    return transitions_fired
```

---

## Step 5: Detect Overdue Transitions

*The pseudocode calls this `check_overdue_transitions()`. A scheduled Lambda runs every 15 minutes to find patients who should have advanced but haven't. This catches the absence of events, which event-driven processing can't detect.*

```python
def check_overdue_transitions() -> list:
    """
    Scan all active patient pathway states for overdue steps.

    A step is overdue when the patient has been at a node longer than
    the max_time_hours specified on any outgoing edge from that node.

    This runs on a schedule (EventBridge rule, every 15 minutes).
    It does NOT advance patients; it generates alerts for clinical staff.

    Returns:
        List of overdue alert dicts.
    """
    alerts = []

    # Scan for all active pathway states.
    # In production with thousands of patients, use a GSI on status
    # or partition the scan across multiple Lambda invocations.
    response = patient_state_table.scan(
        FilterExpression=boto3.dynamodb.conditions.Attr("status").eq("active")
    )

    for state in response.get("Items", []):
        patient_id = state["patient_id"]
        pathway_id = state["pathway_id"]

        for active_node_id in state["active_nodes"]:
            node_entry_time = state["node_entry_times"].get(
                active_node_id, state["enrolled_at"]
            )
            entry = datetime.fromisoformat(node_entry_time)
            elapsed_hours = (datetime.now(timezone.utc) - entry).total_seconds() / 3600

            # Check outgoing edges for time constraints.
            outgoing = get_outgoing_edges(active_node_id)

            for edge in outgoing:
                max_hours = edge.get("max_time_hours")
                if max_hours is not None and elapsed_hours > float(max_hours):
                    alerts.append({
                        "type": "overdue_pathway_step",
                        "patient_id": patient_id,
                        "pathway_id": pathway_id,
                        "node_id": active_node_id,
                        "expected_next": edge["to_node_name"],
                        "hours_overdue": round(elapsed_hours - float(max_hours), 1),
                        "detected_at": datetime.now(timezone.utc).isoformat(),
                    })

    logger.info("Overdue check complete: %d alerts generated", len(alerts))
    return alerts
```

---

## Step 6: Query for CDS Recommendations

*The pseudocode calls this `get_pathway_recommendations(patient_id, pathway_id)`. This is the real-time query that powers point-of-care decision support. When a clinician opens a patient's chart, this returns what the patient should do next.*

```python
def get_pathway_recommendations(patient_id: str, pathway_id: str) -> dict:
    """
    Get current pathway recommendations for a patient.

    Called at point of care (chart open, order entry screen).
    Must return in < 500ms for CDS integration.

    Returns a structured recommendation object showing:
    - Current position on the pathway
    - Available next transitions (with condition status)
    - Whether any steps are overdue
    - Overall progress through the pathway
    """
    # Read patient state from DynamoDB.
    response = patient_state_table.get_item(
        Key={"patient_id": patient_id, "pathway_id": pathway_id}
    )
    state = response.get("Item")

    if state is None or state["status"] != "active":
        return {"patient_id": patient_id, "pathway_id": pathway_id,
                "status": "not_enrolled", "recommendations": []}

    recommendations = []

    for active_node_id in state["active_nodes"]:
        # Get node details from Neptune.
        node_query = """
        MATCH (n:PathwayNode {id: $node_id})
        RETURN n.name AS name, n.node_type AS node_type,
               n.responsible_role AS responsible_role
        """
        node_result = execute_cypher(node_query, {"node_id": active_node_id}, use_writer=False)
        node_info = node_result["results"][0] if node_result.get("results") else {}

        # Calculate time in current step.
        node_entry_time = state["node_entry_times"].get(active_node_id, state["enrolled_at"])
        entry = datetime.fromisoformat(node_entry_time)
        elapsed_hours = (datetime.now(timezone.utc) - entry).total_seconds() / 3600

        # Get outgoing edges and evaluate conditions.
        outgoing = get_outgoing_edges(active_node_id)
        available_transitions = []
        is_overdue = False

        for edge in outgoing:
            conditions = json.loads(edge["conditions"]) if edge["conditions"] else []
            conditions_met = evaluate_conditions(conditions, patient_id, node_entry_time)

            # Build human-readable condition descriptions.
            condition_descriptions = []
            for c in conditions:
                met_str = "MET" if conditions_met else "NOT MET"
                condition_descriptions.append(
                    f"{c['condition_type']}: {c['parameter']} {c['operator']} {c.get('value', '')} ({met_str})"
                )

            available_transitions.append({
                "target_node": edge["to_node_name"],
                "target_type": edge["to_node_type"],
                "conditions_met": conditions_met,
                "conditions": condition_descriptions,
                "edge_type": edge["edge_type"],
            })

            # Check overdue status.
            max_hours = edge.get("max_time_hours")
            if max_hours is not None and elapsed_hours > float(max_hours):
                is_overdue = True

        recommendations.append({
            "current_step": node_info.get("name", active_node_id),
            "current_step_type": node_info.get("node_type", "unknown"),
            "responsible_role": node_info.get("responsible_role", "unknown"),
            "time_in_step_hours": round(elapsed_hours, 1),
            "is_overdue": is_overdue,
            "available_transitions": available_transitions,
        })

    return {
        "patient_id": patient_id,
        "pathway_id": pathway_id,
        "pathway_version": state["pathway_version"],
        "status": state["status"],
        "recommendations": recommendations,
        "completed_steps": len(state.get("completed_nodes", [])),
    }
```

---

## Putting It All Together

Here's the full pipeline assembled into callable functions. This shows the lifecycle: load a pathway, enroll a patient, process events, and query recommendations.

```python
def demo_full_pipeline():
    """
    Demonstrate the full clinical pathway pipeline end-to-end.

    This function:
    1. Builds a sample pneumonia pathway
    2. Loads it into Neptune
    3. Enrolls a test patient
    4. Simulates a clinical event
    5. Queries for recommendations
    """

    # Step 1: Build the pathway definition.
    logger.info("=== Building sample pneumonia pathway ===")
    pathway_def = build_sample_pneumonia_pathway()
    logger.info(
        "  Pathway: %s v%d (%d nodes, %d edges)",
        pathway_def["pathway_id"], pathway_def["pathway_version"],
        len(pathway_def["nodes"]), len(pathway_def["edges"])
    )

    # Step 2: Load into Neptune.
    logger.info("=== Loading pathway into Neptune ===")
    load_result = load_pathway_to_neptune(pathway_def)
    logger.info("  Created %d nodes, %d edges", load_result["nodes_created"],
                load_result["edges_created"])

    # Step 3: Enroll a test patient.
    logger.info("=== Enrolling test patient ===")
    patient_id = "PAT-2026-TEST-001"
    state = initialize_patient_on_pathway(
        patient_id, pathway_def["pathway_id"], pathway_def["pathway_version"]
    )
    logger.info("  Patient at: %s", state["active_nodes"])

    # Step 4: Simulate a clinical event (lab result posted).
    logger.info("=== Processing clinical event ===")
    event = {
        "patient_id": patient_id,
        "event_type": "lab_result",
        "parameter": "curb65_score",
        "value": 2,
    }
    transitions = on_clinical_event(event)
    logger.info("  Transitions fired: %d", len(transitions))
    for t in transitions:
        logger.info("    %s -> %s (%s)", t["from_node"], t["to_node_name"], t["edge_type"])

    # Step 5: Query recommendations.
    logger.info("=== Querying CDS recommendations ===")
    recs = get_pathway_recommendations(patient_id, pathway_def["pathway_id"])
    logger.info("  Status: %s", recs["status"])
    logger.info("  Completed steps: %d", recs["completed_steps"])
    for rec in recs.get("recommendations", []):
        logger.info("  Current step: %s (%.1f hours, overdue=%s)",
                    rec["current_step"], rec["time_in_step_hours"], rec["is_overdue"])
        for trans in rec["available_transitions"]:
            logger.info("    -> %s [%s] conditions_met=%s",
                        trans["target_node"], trans["edge_type"], trans["conditions_met"])

    # Step 6: Check for overdue transitions.
    logger.info("=== Checking overdue transitions ===")
    alerts = check_overdue_transitions()
    logger.info("  Overdue alerts: %d", len(alerts))
    for alert in alerts:
        logger.info("    Patient %s: %s overdue by %.1f hours",
                    alert["patient_id"], alert["expected_next"], alert["hours_overdue"])

    # Print final recommendation as JSON for inspection.
    print("\n=== CDS Recommendation Output ===")
    print(json.dumps(recs, indent=2, default=str))


if __name__ == "__main__":
    demo_full_pipeline()
```

---

## The Gap Between This and Production

This example works conceptually. Run it against a real Neptune cluster with the DynamoDB table created, and it will load a pathway, track patient state, and return recommendations. But there's a meaningful distance between "works in a script" and "runs as a hospital CDS system handling real patient events." Here's where that gap lives:

**Error handling.** Right now, if Neptune returns an error or DynamoDB throttles, the function crashes. A production system wraps every external call in try/except blocks with specific handling for Neptune connection timeouts (common when the cluster is scaling), DynamoDB conditional check failures (race conditions on state updates), and malformed clinical data from EHR integrations.

**Connection management.** Each `execute_cypher` call opens a new HTTPS connection to Neptune. In production, use connection pooling (via `requests.Session()` or a dedicated Neptune client library) to reuse connections. Neptune has connection limits per instance; without pooling, you'll hit them under load.

**Atomic state transitions.** The `advance_patient_state` function does a read-modify-write cycle. Two simultaneous events for the same patient could race. Production uses DynamoDB ConditionExpressions to ensure the state hasn't changed between read and write. If the condition fails, retry with fresh state.

**EHR integration.** The `get_patient_clinical_data` function returns mock data. A real system calls the EHR's FHIR API (or reads from a clinical data cache populated by HL7v2 feeds). That integration is its own project: authentication, rate limiting, data mapping, handling missing data gracefully. Budget significant time for this.

**Condition evaluation performance.** If evaluating conditions requires calling an EHR API for each edge, and a patient has 5 active nodes with 3 outgoing edges each, that's 15 potential API calls per event. Cache patient clinical data aggressively. Pre-fetch when you know a CDS query is coming (patient chart opened event). Accept slightly stale data for non-critical conditions.

**IAM least-privilege.** The IAM role for these Lambda functions should have exactly the permissions needed: `neptune-db:ReadDataViaQuery` and `neptune-db:WriteDataViaQuery` scoped to the specific cluster ARN, DynamoDB actions scoped to the specific table, and no broader access. Neptune IAM auth (SigV4 signing) adds complexity but is recommended for production.

**VPC configuration.** Neptune requires VPC deployment. Lambda functions must be in the same VPC with security groups allowing access to the Neptune port (8182). Add VPC endpoints for DynamoDB, S3, and CloudWatch Logs so those calls don't need NAT gateway traversal. Without VPC endpoints, Lambda functions in private subnets can't reach DynamoDB.

**Pathway versioning.** This example loads one version. Production needs to handle multiple active versions simultaneously (patients enrolled on v2 stay on v2 even after v3 is published). The pathway_version property on every node and edge enables this, but your queries must always filter by the patient's enrolled version.

**Overdue check scaling.** The `check_overdue_transitions` function does a full DynamoDB scan. For a 500-bed hospital with 200 active pathway enrollments, this is fine. For a health system with 50,000 active enrollments, you need a GSI on status with pagination, or partition the work across multiple Lambda invocations using DynamoDB parallel scan.

**Logging and audit.** Every state transition, every recommendation query, and every overdue alert needs structured logging for HIPAA audit requirements. Use AWS Lambda Powertools for structured JSON logging. Never log patient clinical data values in the same log entry as patient identifiers.

**Testing.** There are no tests here. A production system has unit tests for `evaluate_conditions` (with various condition combinations), integration tests against a real Neptune cluster with a test pathway, and end-to-end tests that simulate a patient journey through a complete pathway. Use synthetic patient data; never use real PHI in test fixtures.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 13.5](chapter13.05-clinical-pathway-protocol-modeling.md) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
