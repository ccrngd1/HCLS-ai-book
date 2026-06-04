# Recipe 8.7: Adverse Event Detection in Clinical Text - Python Example

> **This is an illustrative implementation, not a production-ready deployment.**
> It demonstrates the patterns from the pseudocode walkthrough using boto3.
> A real deployment needs the additions listed in the "Gap to Production" section at the end.
> Start here to understand the concepts. Don't ship this as-is.

---

## Setup

```bash
pip install boto3
```

You'll also need:
- An AWS account with Amazon Comprehend Medical configured
- A signed AWS BAA covering PHI processing
- IAM permissions: `comprehend-medical:DetectEntitiesV2`, `comprehend-medical:InferRxNorm`,
  `dynamodb:PutItem`, `dynamodb:Query`, `s3:PutObject`, `s3:GetObject`, `sns:Publish`

---

## Configuration

```python
import boto3
import json
import re
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from botocore.config import Config

# -------------------------------------------------------------------------
# Retry configuration
# -------------------------------------------------------------------------
# Comprehend Medical throttles under burst load. Adaptive mode uses exponential
# backoff with jitter automatically. Apply this to every boto3 client.
BOTO3_RETRY_CONFIG = Config(
    retries={
        "max_attempts": 3,
        "mode": "adaptive"
    }
)

# -------------------------------------------------------------------------
# Clients
# -------------------------------------------------------------------------
comprehend_medical = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)
s3 = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
sns = boto3.client("sns", config=BOTO3_RETRY_CONFIG)

# -------------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------------
ADVERSE_EVENTS_TABLE = "adverse-events"
NOTES_BUCKET = "clinical-notes-archive"
SNS_CRITICAL_TOPIC = "arn:aws:sns:us-east-1:123456789012:ae-critical-alerts"

# Minimum combined evidence score to flag a drug-event pair as a potential AE.
AE_EVIDENCE_THRESHOLD = 0.4

# -------------------------------------------------------------------------
# Causal language patterns
# -------------------------------------------------------------------------
# These phrases, when appearing between a medication mention and a clinical
# event, strongly suggest the clinician intended a causal link.
# High precision, moderate recall: they catch explicit attributions but miss
# implicit ones (which are the majority in practice).
CAUSAL_PATTERNS = [
    r"due to",
    r"caused by",
    r"secondary to",
    r"related to",
    r"attributed to",
    r"as a result of",
    r"likely from",
    r"suspect(?:ed)? reaction to",
    r"discontinue.*because",
    r"hold.*due to",
    r"adverse effect of",
    r"side effect",
    r"after starting",
    r"since (?:starting|beginning|initiating)",
]

# -------------------------------------------------------------------------
# Severity indicators
# -------------------------------------------------------------------------
# Ordered from most to least severe. First match wins.
SEVERITY_INDICATORS = {
    "grade_4_life_threatening": [
        "icu", "intubated", "code blue", "life-threatening",
        "anaphylaxis", "cardiac arrest", "emergency", "resuscitat"
    ],
    "grade_3_severe": [
        "admitted", "hospitalized", "transfusion", "surgical intervention",
        "disability", "prolonged hospitalization", "transferred to"
    ],
    "grade_2_moderate": [
        "medication change", "dose reduction", "additional treatment",
        "limits activities", "switched to", "discontinued"
    ],
    "grade_1_mild": [
        "mild", "self-limited", "resolved", "no intervention",
        "tolerable", "asymptomatic", "transient"
    ],
}

# -------------------------------------------------------------------------
# Known adverse drug reactions (simplified lookup)
# -------------------------------------------------------------------------
# In production, this would be a database populated from FDA labels, SIDER,
# or FAERS data. Here we use a small sample for demonstration.
# Keys are RxNorm CUIs. Values are sets of normalized event terms.
KNOWN_ADR_DATABASE = {
    "329526": {"dizziness", "orthostatic hypotension", "edema", "fatigue", "flushing"},   # amlodipine
    "161": {"rash", "diarrhea", "nausea", "allergic reaction", "anaphylaxis"},            # amoxicillin
    "36567": {"myalgia", "rhabdomyolysis", "hepatotoxicity", "muscle weakness"},          # atorvastatin
    "32968": {"nausea", "insomnia", "sexual dysfunction", "weight gain", "serotonin syndrome"},  # sertraline
    "7052": {"gi bleed", "nausea", "renal impairment", "hypertension"},                   # naproxen
}
```

---

## Synthetic Clinical Notes

```python
# -------------------------------------------------------------------------
# Synthetic test data: clinical notes with planted adverse events
# -------------------------------------------------------------------------
# These are entirely synthetic. They simulate real documentation patterns
# without containing any actual patient information.

SYNTHETIC_NOTES = [
    {
        "note_id": "NOTE-20260304-11422",
        "patient_id": "PAT-882710",
        "note_date": "2026-03-04",
        "note_type": "progress_note",
        "text": (
            "Assessment and Plan:\n"
            "1. Hypertension - Patient started on amlodipine 10mg daily two weeks ago. "
            "Reports orthostatic dizziness every morning since starting medication. "
            "Dizziness is worst upon standing from bed, lasting 30-60 seconds. "
            "No syncope. BP today 128/78 sitting, 110/68 standing. "
            "Likely related to new amlodipine. Will reduce to 5mg and recheck in 2 weeks. "
            "If symptoms persist at lower dose, will switch to ACE inhibitor.\n"
            "2. Diabetes type 2 - A1c stable at 7.1%. Continue metformin 1000mg BID.\n"
            "3. Hyperlipidemia - Continue atorvastatin 40mg. Denies muscle pain."
        ),
    },
    {
        "note_id": "NOTE-20260305-08831",
        "patient_id": "PAT-551203",
        "note_date": "2026-03-05",
        "note_type": "telephone_encounter",
        "text": (
            "Patient called to report rash on trunk and arms, onset 3 days after "
            "starting amoxicillin for sinus infection. Rash is maculopapular, non-pruritic, "
            "no mucosal involvement, no respiratory difficulty. No prior antibiotic allergies. "
            "Suspect drug reaction to amoxicillin. Advised to discontinue amoxicillin immediately. "
            "Switched to azithromycin 250mg. If rash worsens or develops hives, "
            "proceed to emergency department. Follow up in 3 days."
        ),
    },
    {
        "note_id": "NOTE-20260306-14209",
        "patient_id": "PAT-339847",
        "note_date": "2026-03-06",
        "note_type": "progress_note",
        "text": (
            "Follow up visit. Patient doing well on current medications.\n"
            "Medications reviewed: lisinopril 20mg daily, metformin 500mg BID, "
            "aspirin 81mg daily.\n"
            "No new complaints. Denies chest pain, shortness of breath, or dizziness. "
            "No peripheral edema. Labs from last week within normal limits.\n"
            "Continue current regimen. Return in 3 months."
        ),
    },
    {
        "note_id": "NOTE-20260307-09155",
        "patient_id": "PAT-447291",
        "note_date": "2026-03-07",
        "note_type": "progress_note",
        "text": (
            "Patient presents with diffuse muscle aches for the past 10 days. "
            "Started atorvastatin 40mg approximately 3 weeks ago for hyperlipidemia. "
            "Myalgia is bilateral, affecting thighs and calves, worse with exertion. "
            "CK level today: 890 U/L (elevated; normal < 200). "
            "Suspect statin-induced myopathy. Discontinuing atorvastatin. "
            "Will recheck CK in one week. Consider alternative lipid-lowering therapy "
            "once symptoms resolve. Patient advised to report dark urine immediately "
            "as this could indicate rhabdomyolysis requiring hospitalization."
        ),
    },
]
```

---

## Step 1: Archive the Clinical Note

```python
def archive_note(note: dict) -> str:
    """
    Archive raw note to S3 before processing.

    Maps to pseudocode Step 1. Every note gets stored in durable storage before
    we touch it with NLP. This gives us an immutable audit trail and enables
    reprocessing when models improve.
    """
    note_date = note["note_date"]
    year, month, _ = note_date.split("-")
    archive_key = f"notes-archive/{year}/{month}/{note['note_id']}.json"

    archive_record = {
        "note_id": note["note_id"],
        "patient_id": note["patient_id"],
        "note_date": note_date,
        "note_type": note["note_type"],
        "text": note["text"],
        "received_timestamp": datetime.now(timezone.utc).isoformat(),
    }

    s3.put_object(
        Bucket=NOTES_BUCKET,
        Key=archive_key,
        Body=json.dumps(archive_record),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
    )

    return archive_key
```

---

## Step 2: Extract Medical Entities

```python
def extract_entities(note_text: str) -> dict:
    """
    Call Comprehend Medical DetectEntitiesV2 to extract medications, conditions,
    and temporal expressions.

    Maps to pseudocode Step 2. Comprehend Medical handles the biomedical NER:
    drug names, symptoms, diagnoses, and time references. Each entity comes back
    with confidence scores and trait attributes (negation, hypothetical, etc.)
    that we use in the assertion filtering step.
    """
    # Comprehend Medical has a 20,000 character limit per call.
    # Most progress notes are well under this. Truncate if needed.
    truncated_text = note_text[:20000]

    response = comprehend_medical.detect_entities_v2(Text=truncated_text)

    medications = []
    conditions = []
    temporals = []

    for entity in response["Entities"]:
        base = {
            "text": entity["Text"],
            "type": entity["Type"],
            "score": entity["Score"],
            "begin_offset": entity["BeginOffset"],
            "end_offset": entity["EndOffset"],
            "traits": entity.get("Traits", []),
            "attributes": entity.get("Attributes", []),
        }

        if entity["Category"] == "MEDICATION":
            medications.append(base)
        elif entity["Category"] == "MEDICAL_CONDITION":
            conditions.append(base)
        elif entity["Category"] == "TIME_EXPRESSION":
            temporals.append(base)

    # Normalize medication names to RxNorm codes.
    # This enables cross-note aggregation: "amlodipine" and "Norvasc" map to the same CUI.
    for med in medications:
        rxnorm_response = comprehend_medical.infer_rx_norm(Text=med["text"])
        concepts = rxnorm_response.get("Entities", [])
        if concepts:
            top_concept = concepts[0].get("RxNormConcepts", [])
            if top_concept and top_concept[0]["Score"] > 0.7:
                med["rxnorm_code"] = top_concept[0]["Code"]
                med["rxnorm_description"] = top_concept[0]["Description"]

    return {
        "medications": medications,
        "conditions": conditions,
        "temporals": temporals,
    }
```

---

## Step 3: Filter by Assertion Status

```python
def filter_active_conditions(conditions: list) -> list:
    """
    Remove negated, hypothetical, and family-history conditions.

    Maps to pseudocode Step 3. Comprehend Medical attaches Traits to each entity
    that indicate context. "Denies chest pain" gets a NEGATION trait. "If rash
    develops" gets a HYPOTHETICAL trait (when supported by the model).

    This single step typically removes 30-50% of extracted conditions, dramatically
    cutting false positives downstream.
    """
    active = []

    for condition in conditions:
        trait_names = {t["Name"] for t in condition["traits"]}

        # Skip negated conditions: "denies dizziness", "no rash"
        if "NEGATION" in trait_names:
            continue

        # Skip hypothetical/conditional: "if patient develops rash"
        # Note: Comprehend Medical uses "HYPOTHETICAL" for conditional mentions
        if "HYPOTHETICAL" in trait_names:
            continue

        # Keep everything else. Comprehend Medical does not currently expose a
        # dedicated "FAMILY_HISTORY" trait on MEDICAL_CONDITION entities, so we
        # rely on section detection or manual rules for that in production.
        # TODO: verify trait coverage in latest Comprehend Medical API version
        active.append(condition)

    return active
```

---

## Step 4: Detect Adverse Event Relationships

```python
def detect_adverse_events(
    medications: list,
    active_conditions: list,
    temporals: list,
    note_text: str,
) -> list:
    """
    Core relation extraction: link clinical events to medications using layered evidence.

    Maps to pseudocode Step 4. For each (medication, condition) pair, we accumulate
    evidence from four layers:
      1. Explicit causal language (highest signal)
      2. Temporal plausibility
      3. Text proximity
      4. Known ADR match from knowledge base

    The combined score determines whether we flag the pair.
    """
    detected_events = []

    for condition in active_conditions:
        for medication in medications:
            evidence_score = 0.0
            evidence_reasons = []

            # ----- Layer 1: Explicit causal language -----
            # Extract text between (or near) the two entity mentions and search
            # for phrases that explicitly link them.
            start = min(medication["end_offset"], condition["end_offset"])
            end = max(medication["begin_offset"], condition["begin_offset"])
            # Expand window slightly to catch phrases before/after the entities
            window_start = max(0, min(medication["begin_offset"], condition["begin_offset"]) - 50)
            window_end = min(len(note_text), max(medication["end_offset"], condition["end_offset"]) + 50)
            text_window = note_text[window_start:window_end].lower()

            for pattern in CAUSAL_PATTERNS:
                if re.search(pattern, text_window):
                    evidence_score += 0.6
                    evidence_reasons.append(f"explicit_causal_language: {pattern}")
                    break  # one match is sufficient

            # ----- Layer 2: Temporal plausibility -----
            # Check if any temporal expression near the condition suggests
            # the event followed the medication.
            temporal_keywords = [
                "since starting", "after beginning", "after starting",
                "since initiating", "days after", "weeks after", "onset after"
            ]
            for temporal in temporals:
                temporal_text = temporal["text"].lower()
                for keyword in temporal_keywords:
                    if keyword in temporal_text:
                        evidence_score += 0.3
                        evidence_reasons.append(f"temporal_association: {temporal['text']}")
                        break
                if evidence_score >= 0.3 and "temporal_association" in str(evidence_reasons):
                    break

            # ----- Layer 3: Text proximity -----
            # Entities in the same sentence or adjacent sentences are more likely
            # to be intentionally connected by the documenting clinician.
            char_distance = abs(condition["begin_offset"] - medication["end_offset"])
            if char_distance < 200:
                evidence_score += 0.1
                evidence_reasons.append("text_proximity")

            # ----- Layer 4: Known ADR match -----
            # Check if this drug-event pair appears in our knowledge base.
            rxnorm_code = medication.get("rxnorm_code", "")
            if rxnorm_code in KNOWN_ADR_DATABASE:
                known_events = KNOWN_ADR_DATABASE[rxnorm_code]
                condition_lower = condition["text"].lower()
                for known_event in known_events:
                    if known_event in condition_lower or condition_lower in known_event:
                        evidence_score += 0.2
                        evidence_reasons.append("known_adr_match")
                        break

            # ----- Threshold decision -----
            if evidence_score >= AE_EVIDENCE_THRESHOLD:
                detected_events.append({
                    "medication": medication["text"],
                    "rxnorm_code": rxnorm_code,
                    "rxnorm_description": medication.get("rxnorm_description", ""),
                    "event": condition["text"],
                    "evidence_score": round(evidence_score, 2),
                    "evidence_reasons": evidence_reasons,
                    "medication_offset": (medication["begin_offset"], medication["end_offset"]),
                    "condition_offset": (condition["begin_offset"], condition["end_offset"]),
                })

    return detected_events
```

---

## Step 5: Classify Severity

```python
def classify_severity(detected_event: dict, note_text: str) -> tuple:
    """
    Assign a CTCAE-style severity grade based on contextual clues.

    Maps to pseudocode Step 5. We look at text surrounding the adverse event
    mention for severity indicators. Clinical text rarely uses explicit grades,
    so we infer from outcome language: "hospitalized" implies Grade 3+,
    "self-limited" implies Grade 1.
    """
    # Extract a window around the condition mention for context.
    cond_start, cond_end = detected_event["condition_offset"]
    window_start = max(0, cond_start - 300)
    window_end = min(len(note_text), cond_end + 300)
    context_window = note_text[window_start:window_end].lower()

    # Check from most severe to least. First match wins.
    for grade, indicators in SEVERITY_INDICATORS.items():
        for indicator in indicators:
            if indicator in context_window:
                return grade, indicator

    # Default: if documented at all, assume moderate. Grade 1 events are
    # often not documented. Absence of severity language suggests the clinician
    # found it noteworthy enough to write down.
    return "grade_2_moderate", "default_no_indicators"
```

---

## Step 6: Store and Alert

```python
def store_adverse_event(
    note: dict,
    detected_event: dict,
    severity: str,
    severity_indicator: str,
) -> dict:
    """
    Write detected AE to DynamoDB and alert on high-severity events.

    Maps to pseudocode Step 6. The DynamoDB schema supports three access patterns:
      - By patient (partition key) for clinical review
      - By medication (GSI) for drug-level surveillance
      - By time (sort key) for trend detection
    """
    ae_id = f"ae-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:8]}"

    ae_record = {
        "ae_id": ae_id,
        "patient_id": note["patient_id"],
        "note_id": note["note_id"],
        "note_date": note["note_date"],
        "medication": detected_event["medication"],
        "rxnorm_code": detected_event["rxnorm_code"],
        "event_description": detected_event["event"],
        "severity": severity,
        "severity_indicator": severity_indicator,
        "evidence_score": Decimal(str(detected_event["evidence_score"])),
        "evidence_reasons": detected_event["evidence_reasons"],
        "detection_timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "pending_review",
    }

    # Write to DynamoDB.
    # Partition key: patient_id. Sort key: detection_timestamp.
    # GSI on rxnorm_code + note_date for medication-level queries.
    table = dynamodb.Table(ADVERSE_EVENTS_TABLE)
    table.put_item(Item=ae_record)

    # High-severity: Grade 3+ triggers immediate notification.
    if severity in ("grade_3_severe", "grade_4_life_threatening"):
        sns.publish(
            TopicArn=SNS_CRITICAL_TOPIC,
            Subject=f"High-severity adverse event detected: {severity}",
            Message=json.dumps(
                {k: str(v) for k, v in ae_record.items()},
                indent=2,
            ),
        )
        print(f"  ** ALERT: High-severity event published to SNS **")

    return ae_record
```

---

## Step 7: Aggregate for Signal Detection

```python
def aggregate_signals(time_window_days: int = 30) -> list:
    """
    Query recent AEs and apply basic disproportionality analysis.

    Maps to pseudocode Step 7. This runs as a scheduled batch job (daily or weekly).
    It queries all detected events in a time window, groups by drug-event pair,
    and flags combinations occurring at >2x the expected rate with 3+ patients.

    In production, this would query DynamoDB with a GSI scan or export to Athena
    for efficient aggregation. Here we demonstrate the logic.
    """
    # In a real system, you'd query DynamoDB or export to S3/Athena.
    # This simulates reading recent events from the database.
    table = dynamodb.Table(ADVERSE_EVENTS_TABLE)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=time_window_days)).isoformat()

    # Scan is expensive at scale. In production, use a GSI with detection_timestamp
    # as the sort key, or export to S3 + Athena for analytical queries.
    response = table.scan(
        FilterExpression="detection_timestamp > :cutoff",
        ExpressionAttributeValues={":cutoff": cutoff},
    )
    recent_events = response.get("Items", [])

    # Group by normalized drug-event pair.
    pair_counts = {}
    for event in recent_events:
        pair_key = (event.get("rxnorm_code", "unknown"), event["event_description"].lower())
        if pair_key not in pair_counts:
            pair_counts[pair_key] = {"patients": set(), "total_mentions": 0}
        pair_counts[pair_key]["patients"].add(event["patient_id"])
        pair_counts[pair_key]["total_mentions"] += 1

    # Apply simple disproportionality analysis.
    # Expected rates would come from historical baseline or literature.
    # Here we use a placeholder of 4.0 events per 30-day window.
    DEFAULT_EXPECTED_RATE = 4.0
    signals = []

    for (rxnorm_code, event_term), counts in pair_counts.items():
        unique_patients = len(counts["patients"])
        if unique_patients >= 3:
            ratio = unique_patients / DEFAULT_EXPECTED_RATE
            if ratio > 2.0:
                signals.append({
                    "rxnorm_code": rxnorm_code,
                    "event_term": event_term,
                    "unique_patients": unique_patients,
                    "total_mentions": counts["total_mentions"],
                    "expected_rate": DEFAULT_EXPECTED_RATE,
                    "observed_to_expected_ratio": round(ratio, 2),
                    "time_window_days": time_window_days,
                    "signal_status": "investigation_required",
                })

    return signals
```

---

## Full Pipeline

```python
def process_note(note: dict) -> list:
    """
    Run the full adverse event detection pipeline on a single clinical note.

    This assembles Steps 1-6 into one callable function. In production, each step
    would be a separate Lambda function orchestrated by Step Functions. Here we
    run them sequentially for clarity.
    """
    print(f"{'='*60}")
    print(f"Processing note: {note['note_id']} ({note['note_type']})")
    print(f"  Patient: {note['patient_id']}")
    print(f"  Date: {note['note_date']}")

    # Step 1: Archive
    print("\n[Step 1] Archiving note to S3...")
    archive_key = archive_note(note)
    print(f"  Archived to: {archive_key}")

    # Step 2: Extract entities
    print("\n[Step 2] Extracting medical entities (Comprehend Medical)...")
    entities = extract_entities(note["text"])
    print(f"  Medications found: {len(entities['medications'])}")
    print(f"  Conditions found: {len(entities['conditions'])}")
    print(f"  Temporal expr: {len(entities['temporals'])}")

    for med in entities["medications"]:
        rxnorm = med.get("rxnorm_code", "N/A")
        print(f"    Med: {med['text']} (RxNorm: {rxnorm}, confidence: {med['score']:.2f})")
    for cond in entities["conditions"]:
        traits = [t["Name"] for t in cond["traits"]]
        print(f"    Condition: {cond['text']} (traits: {traits}, confidence: {cond['score']:.2f})")

    # Step 3: Filter assertions
    print("\n[Step 3] Filtering by assertion status...")
    active_conditions = filter_active_conditions(entities["conditions"])
    filtered_count = len(entities["conditions"]) - len(active_conditions)
    print(f"  Active conditions: {len(active_conditions)} (filtered out {filtered_count} negated/hypothetical)")

    # Step 4: Detect adverse event relationships
    print("\n[Step 4] Detecting adverse event relationships...")
    detected_events = detect_adverse_events(
        entities["medications"],
        active_conditions,
        entities["temporals"],
        note["text"],
    )
    print(f"  Detected AEs: {len(detected_events)}")

    # Steps 5-6: Classify severity and store
    results = []
    for ae in detected_events:
        severity, indicator = classify_severity(ae, note["text"])
        print(f"\n  AE: {ae['medication']} -> {ae['event']}")
        print(f"    Evidence score: {ae['evidence_score']}")
        print(f"    Evidence: {ae['evidence_reasons']}")
        print(f"    Severity: {severity} (indicator: {indicator})")

        # Step 6: Store (in a real run with actual AWS resources)
        # ae_record = store_adverse_event(note, ae, severity, indicator)
        # results.append(ae_record)

        # For demonstration, build the record without writing to DynamoDB
        results.append({
            "ae_id": f"ae-demo-{uuid.uuid4().hex[:8]}",
            "patient_id": note["patient_id"],
            "note_id": note["note_id"],
            "medication": ae["medication"],
            "rxnorm_code": ae["rxnorm_code"],
            "event": ae["event"],
            "severity": severity,
            "evidence_score": ae["evidence_score"],
            "evidence_reasons": ae["evidence_reasons"],
        })

    if not detected_events:
        print("\n  No adverse events detected in this note.")

    print(f"\n{'='*60}")
    return results


def run_demo():
    """
    Process all synthetic notes and display results.

    This simulates what would happen when notes arrive in the SQS queue
    and trigger the Lambda pipeline.
    """
    print("Adverse Event Detection Pipeline - Demo Run")
    print(f"Processing {len(SYNTHETIC_NOTES)} synthetic clinical notes\n")

    all_results = []
    for note in SYNTHETIC_NOTES:
        results = process_note(note)
        all_results.extend(results)

    # Summary
    print("\n" + "=" * 60)
    print("PIPELINE SUMMARY")
    print("=" * 60)
    print(f"Notes processed: {len(SYNTHETIC_NOTES)}")
    print(f"Adverse events detected: {len(all_results)}")

    if all_results:
        print("\nDetected adverse events:")
        for ae in all_results:
            print(f"  - {ae['medication']} -> {ae['event']}")
            print(f"    Patient: {ae['patient_id']}, Severity: {ae['severity']}")
            print(f"    Score: {ae['evidence_score']}, Reasons: {ae['evidence_reasons']}")


if __name__ == "__main__":
    run_demo()
```

---

## Gap to Production

This example demonstrates the core concepts. Here's the distance between this code and something you'd deploy.

**Error handling and retries.** Every Comprehend Medical call needs robust error handling. `ThrottlingException` is expected at batch volumes. The `botocore.config.Config(retries={"max_attempts": 3, "mode": "adaptive"})` shown here is the minimum. Add a dead-letter queue on each Lambda, and implement circuit-breaker patterns for downstream services. A note that fails processing should not disappear silently.

**Input validation and text normalization.** Clinical notes arrive in varied encodings, with embedded formatting, control characters, and sometimes corrupted Unicode from legacy EHR systems. Validate and normalize input text before sending to Comprehend Medical. Strip control characters, normalize whitespace, and handle the 20,000-character limit gracefully by chunking long notes with overlap (especially discharge summaries, which routinely exceed 20,000 characters).

**Structured logging.** Replace all `print` statements with structured JSON logging (Python's `logging` module with a JSON formatter, or AWS Lambda Powertools). Every log entry should include note_id, patient_id, step name, and duration. Never log raw note text or extracted clinical content (that's PHI). Log only metadata: entity counts, confidence scores, severity grades, and processing status.

**Expected-effects filtering.** The demo flags all drug-event pairs above the evidence threshold. A production system needs a comprehensive "expected and acceptable" database to filter out known dose-dependent effects that are clinically unremarkable: nausea with SSRIs, constipation with opioids, fatigue with beta-blockers. Without this filter, the safety team drowns in noise within the first week.

**DynamoDB Decimal handling.** DynamoDB requires `Decimal` for numeric values, not `float`. The `store_adverse_event` function converts `evidence_score` using `Decimal(str(value))`. Any additional numeric fields you add (latency metrics, confidence scores from aggregation) must use the same pattern. The `str()` wrapper avoids floating-point representation issues (`Decimal(0.1)` is not the same as `Decimal("0.1")`).

**VPC and VPC endpoints.** All Lambdas should run in a VPC for HIPAA deployments. You need interface VPC endpoints for: Comprehend Medical (`com.amazonaws.REGION.comprehendmedical`), DynamoDB (gateway endpoint), S3 (gateway endpoint), SNS, SQS, and CloudWatch Logs. Without these, Lambda functions in a no-egress VPC cannot reach AWS services. Test connectivity for each endpoint independently during deployment.

**IAM least-privilege.** The example uses broad service permissions for clarity. In production, scope `comprehend-medical:DetectEntitiesV2` and `comprehend-medical:InferRxNorm` to specific resources. Scope DynamoDB permissions to the exact table ARN. Scope S3 permissions to the specific bucket and prefix. Each Lambda in the Step Functions pipeline should have only the permissions needed for its specific step.

**KMS encryption.** Use customer-managed KMS keys (CMKs) for all data stores: S3 bucket encryption, DynamoDB table encryption, SQS queue encryption, SNS topic encryption, and CloudWatch Logs log group encryption. Lambda does not encrypt CloudWatch log groups by default. Create the log group with KMS encryption before the Lambda first writes to it.

**Deduplication and idempotency.** Notes can arrive multiple times (at-least-once delivery from EHR integration feeds). Use conditional DynamoDB writes (`ConditionExpression='attribute_not_exists(ae_id)'`) or build an idempotency key from (note_id, medication, event_description) to prevent duplicate AE records. Duplicate signals in the aggregation layer inflate observed-to-expected ratios and can trigger false alerts.

**Cross-note reasoning.** This example processes each note independently. The highest-value false negatives require connecting information across notes: a medication started in one note and a symptom reported in a subsequent note. Building cross-note reasoning requires maintaining a patient medication timeline (from pharmacy data or previous extraction results) and checking new symptoms against recently started medications. This is architecturally significant and should be a Phase 2 feature.

**Aggregation at scale.** The `aggregate_signals` function uses a DynamoDB Scan, which is expensive and slow at scale. In production, export AE records to S3 on a schedule (DynamoDB Export to S3 feature), then use Athena or Spark for analytical aggregation queries. The disproportionality analysis (PRR, ROR, BCPNN) requires statistical methods beyond the simple ratio shown here.

**Testing.** Build a test suite with annotated clinical notes (synthetic) where you know the ground truth. Measure precision and recall independently. Track these metrics over time as you tune thresholds and add new causal patterns. A regression test suite protects against threshold changes that improve one metric while degrading the other.

---

*[Recipe 8.7: Adverse Event Detection in Clinical Text](chapter08.07-adverse-event-detection-clinical-text) | [Chapter 8 Index](chapter08-preface)*
