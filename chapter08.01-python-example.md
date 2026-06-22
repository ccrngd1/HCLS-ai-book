# Recipe 8.1: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 8.1. It shows one way you could translate those concepts into working Python using boto3. It is not production-ready. Think of it as the "napkin sketch" version: useful for understanding the shape of the solution, not something you'd point at a real ED registration workflow tomorrow. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `comprehend:ClassifyDocument` (for the custom classifier endpoint)
- `comprehendmedical:DetectEntitiesV2` (for entity enrichment)
- `dynamodb:GetItem`, `dynamodb:PutItem` (abbreviation table + results table)
- `sqs:SendMessage` (review queue)

You also need a trained Comprehend custom classifier endpoint already deployed. Training that model is a separate process (covered in the main recipe's architecture section). This code assumes the endpoint exists and is ready to receive classification requests.

---

## Config and Constants

Before we get to the steps, here's the configuration that drives the pipeline. The abbreviation map and confidence thresholds live up front because they're operational knobs you'll tune frequently.

```python
import re
import json
import uuid
import logging
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, use JSON formatter for CloudWatch Logs Insights.
# Never log the actual chief complaint text in plain logs (it's PHI).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config: adaptive mode handles Comprehend throttling gracefully.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# --- Clients ---
comprehend_client = boto3.client("comprehend", config=BOTO3_RETRY_CONFIG)
comprehend_medical_client = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb")
sqs_client = boto3.client("sqs", config=BOTO3_RETRY_CONFIG)

# --- Configuration ---
# Replace these with your actual resource identifiers.
CLASSIFIER_ENDPOINT_ARN = "arn:aws:comprehend:us-east-1:123456789012:document-classifier-endpoint/chief-complaint-v1"
ABBREVIATION_TABLE_NAME = "chief-complaint-abbreviations"
RESULTS_TABLE_NAME = "complaint-classifications"
REVIEW_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/complaint-review-queue"

# Confidence gate thresholds. Start conservative, lower as you gain trust.
# 85% means roughly 75-85% of complaints will auto-route (the rest go to humans).
CONFIDENCE_THRESHOLD = 0.85

# If the top two predictions are within 15 percentage points of each other,
# the model is basically undecided. Flag as ambiguous regardless of absolute confidence.
AMBIGUITY_GAP = 0.15

# Inline abbreviation map for preprocessing. In production, this lives in DynamoDB
# so you can update it without redeploying code. We keep a hardcoded fallback here
# for cases where DynamoDB is unreachable (graceful degradation).
FALLBACK_ABBREVIATION_MAP = {
    "cp": "chest pain",
    "sob": "shortness of breath",
    "ha": "headache",
    "n/v": "nausea and vomiting",
    "n/v/d": "nausea vomiting and diarrhea",
    "abd": "abdominal",
    "htn": "hypertension",
    "loc": "loss of consciousness",
    "uti": "urinary tract infection",
    "uri": "upper respiratory infection",
    "lbp": "low back pain",
    "r/o": "rule out",
    "s/p": "status post",
    "fx": "fracture",
    "lac": "laceration",
    "mva": "motor vehicle accident",
    "ams": "altered mental status",
    "etoh": "alcohol",
    "oi": "orthopedic injury",
    "doi": "date of injury",
    "brbpr": "bright red blood per rectum",
    "c/o": "complaining of",
    "w/": "with",
    "w/o": "without",
    "hx": "history",
    "pt": "patient",
    "bil": "bilateral",
    "rt": "right",
    "lt": "left",
}
```

---

## Step 1: Preprocess the Chief Complaint Text

*The pseudocode calls this `preprocess_complaint(raw_text, abbreviation_map)`. It lowercases, strips noise characters, and expands abbreviations so the classifier sees consistent input regardless of how the complaint was originally entered.*

```python
def load_abbreviation_map() -> dict:
    """
    Load the abbreviation expansion map from DynamoDB.

    In production, this table is the single source of truth for abbreviation
    expansions. New abbreviations get added here (not in code) as they're
    discovered from reviewing low-confidence predictions.

    Falls back to the hardcoded map if DynamoDB is unreachable.
    The table schema is simple: partition key "abbrev" (string), attribute
    "expansion" (string).
    """
    try:
        table = dynamodb.Table(ABBREVIATION_TABLE_NAME)
        # Scan is fine here because this table is small (hundreds of items, not millions).
        # For larger lookup tables, you'd cache this in Lambda memory between invocations.
        response = table.scan()
        abbrev_map = {}
        for item in response.get("Items", []):
            abbrev_map[item["abbrev"]] = item["expansion"]
        logger.info("Loaded %d abbreviations from DynamoDB", len(abbrev_map))
        return abbrev_map
    except Exception as e:
        # If DynamoDB is unreachable, fall back to hardcoded map.
        # This is graceful degradation: classification still works, just with
        # a potentially stale abbreviation set.
        logger.warning("Failed to load abbreviations from DynamoDB, using fallback: %s", e)
        return FALLBACK_ABBREVIATION_MAP

def preprocess_complaint(raw_text: str, abbreviation_map: dict) -> str:
    """
    Clean and normalize a raw chief complaint string for classification.

    This step is critical for classifier accuracy. "CP x 2 days" and
    "chest pain x 2 days" are the same clinical concept, but a classifier
    sees them as completely different inputs without preprocessing.

    Args:
        raw_text: The original chief complaint as entered (any case, any format)
        abbreviation_map: Dictionary mapping abbreviation -> expansion

    Returns:
        Cleaned, lowercased, abbreviation-expanded text ready for classification.
    """
    # Lowercase everything. Chief complaints arrive in every case style imaginable.
    text = raw_text.lower().strip()

    # Remove characters that add no clinical meaning.
    # Keep: letters, numbers, spaces, forward slashes (n/v), periods (for decimals).
    # This strips parentheses, brackets, asterisks, and other formatting noise.
    text = re.sub(r"[^a-z0-9\s/.]", " ", text)

    # Collapse multiple spaces into one (left over from character removal).
    text = re.sub(r"\s+", " ", text).strip()

    # Expand abbreviations token by token.
    # Split on whitespace, check each token against the map, replace if found.
    tokens = text.split()
    expanded = []
    for token in tokens:
        if token in abbreviation_map:
            # Replace abbreviation with its full clinical form.
            # "cp" becomes "chest pain" (which is two tokens, and that's fine).
            expanded.append(abbreviation_map[token])
        else:
            expanded.append(token)

    return " ".join(expanded)
```

---

## Step 2: Enrich with Medical Entity Detection

*The pseudocode calls this `enrich_with_entities(preprocessed_text)`. It uses Comprehend Medical to identify clinical entities (symptoms, conditions, anatomy) in the text. This is optional but helpful for ambiguous or very short inputs.*

```python
def enrich_with_entities(preprocessed_text: str) -> list:
    """
    Call Comprehend Medical to detect clinical entities in the preprocessed text.

    This is optional enrichment. For clear, well-formed complaints like
    "chest pain radiating to left arm," the classifier does fine without it.
    For short or ambiguous inputs like "pain" or "sick," entity detection
    adds signal by confirming what type of medical concept is present.

    Args:
        preprocessed_text: The cleaned chief complaint text (from Step 1)

    Returns:
        List of detected entities with type, category, and confidence.
        Empty list if detection fails (graceful degradation).
    """
    try:
        response = comprehend_medical_client.detect_entities_v2(Text=preprocessed_text)

        entities = []
        for entity in response.get("Entities", []):
            entities.append({
                "text": entity["Text"],
                "type": entity["Type"],           # e.g., DX_NAME, SYSTEM_ORGAN_SITE, TEST_NAME
                "category": entity["Category"],   # e.g., MEDICAL_CONDITION, ANATOMY
                "score": entity["Score"],
            })

        logger.info("Detected %d medical entities", len(entities))
        return entities

    except Exception as e:
        # Entity enrichment is optional. If it fails, classification still works.
        # Log the error and continue without enrichment.
        logger.warning("Comprehend Medical entity detection failed: %s", e)
        return []
```

---

## Step 3: Classify the Complaint

*The pseudocode calls this `classify_complaint(preprocessed_text, endpoint_arn)`. It sends the cleaned text to the Comprehend custom classifier endpoint and gets back a ranked list of categories with confidence scores.*

```python
def classify_complaint(preprocessed_text: str) -> dict:
    """
    Classify the preprocessed chief complaint using the Comprehend custom endpoint.

    The endpoint runs a model trained on your institution's historical data:
    tens of thousands of chief complaint entries paired with the category they
    were assigned. Comprehend handles tokenization, feature extraction, and
    inference internally.

    Args:
        preprocessed_text: Cleaned, abbreviation-expanded text (from Step 1)

    Returns:
        Dictionary with top prediction, runner-up, and full ranked class list.
        The confidence scores are floats between 0.0 and 1.0.
    """
    # ClassifyDocument sends text to a deployed real-time endpoint.
    # Response time is typically 50-150ms for short text like chief complaints.
    response = comprehend_client.classify_document(
        Text=preprocessed_text,
        EndpointArn=CLASSIFIER_ENDPOINT_ARN,
    )

    # The response contains a "Classes" list sorted by confidence (highest first).
    # Each entry has "Name" (the category label) and "Score" (confidence 0.0-1.0).
    classes = response.get("Classes", [])

    if len(classes) < 2:
        # Edge case: model returned fewer than 2 classes. Shouldn't happen with
        # a properly trained multi-class model, but handle defensively.
        top = classes[0] if classes else {"Name": "UNKNOWN", "Score": 0.0}
        runner_up = {"Name": "UNKNOWN", "Score": 0.0}
    else:
        top = classes[0]
        runner_up = classes[1]

    prediction = {
        "category": top["Name"],
        "confidence": top["Score"],
        "runner_up": {
            "category": runner_up["Name"],
            "confidence": runner_up["Score"],
        },
        "all_classes": classes,  # full ranked list for analytics
    }

    logger.info(
        "Classification: '%s' (%.1f%%) | runner-up: '%s' (%.1f%%)",
        prediction["category"],
        prediction["confidence"] * 100,
        prediction["runner_up"]["category"],
        prediction["runner_up"]["confidence"] * 100,
    )

    return prediction
```

---

## Step 4: Apply Confidence Gating

*The pseudocode calls this `apply_confidence_gate(prediction)`. It decides whether the prediction is trustworthy enough for automated routing or should go to a human reviewer.*

```python
def apply_confidence_gate(prediction: dict) -> dict:
    """
    Decide whether this classification is confident enough for automated routing.

    Two checks:
    1. Is the top prediction above the confidence threshold?
    2. Is there a clear winner, or are the top two categories too close to call?

    Both checks must pass for auto-routing. Either failing sends the complaint
    to the human review queue.

    Args:
        prediction: Output from classify_complaint (category, confidence, runner_up)

    Returns:
        Dictionary with "action" ("ROUTE" or "REVIEW"), the category,
        confidence, and a reason string if flagged for review.
    """
    # Check 1: absolute confidence threshold.
    if prediction["confidence"] < CONFIDENCE_THRESHOLD:
        return {
            "action": "REVIEW",
            "reason": "low_confidence",
            "category": prediction["category"],
            "confidence": prediction["confidence"],
        }

    # Check 2: gap between top two predictions.
    # Even at 87% confidence, if the runner-up is at 84%, the model is basically
    # saying "I'm not sure which of these two it is."
    gap = prediction["confidence"] - prediction["runner_up"]["confidence"]
    if gap < AMBIGUITY_GAP:
        return {
            "action": "REVIEW",
            "reason": "ambiguous_top_two",
            "category": prediction["category"],
            "confidence": prediction["confidence"],
            "runner_up_category": prediction["runner_up"]["category"],
        }

    # Both checks passed. Safe to auto-route.
    return {
        "action": "ROUTE",
        "reason": None,
        "category": prediction["category"],
        "confidence": prediction["confidence"],
    }
```

---

## Step 5: Store Results and Route

*The pseudocode calls this `store_and_route(original_text, preprocessed_text, prediction, gate_result)`. It persists the classification record to DynamoDB and sends low-confidence predictions to the SQS review queue.*

```python
def store_and_route(
    original_text: str,
    preprocessed_text: str,
    prediction: dict,
    gate_result: dict,
) -> dict:
    """
    Persist the classification result and route it based on the gate decision.

    Every classification gets stored (for audit, analytics, and retraining).
    High-confidence results go directly to downstream systems.
    Low-confidence results additionally get sent to the review queue.

    Args:
        original_text: Raw chief complaint as entered
        preprocessed_text: After cleaning and abbreviation expansion
        prediction: Full classifier output (category, confidence, runner-up)
        gate_result: Output from apply_confidence_gate (action, reason)

    Returns:
        The complete classification record as stored in DynamoDB.
    """
    table = dynamodb.Table(RESULTS_TABLE_NAME)

    # Build the classification record.
    # DynamoDB requires Decimal for numeric values, not float.
    record = {
        "complaint_id": f"cc-{datetime.date.today().isoformat()}-{uuid.uuid4().hex[:8]}",
        "timestamp": datetime.datetime.now(timezone.utc).isoformat(),
        "original_text": original_text,
        "preprocessed": preprocessed_text,
        "predicted_category": prediction["category"],
        "confidence": Decimal(str(round(prediction["confidence"], 4))),
        "runner_up_category": prediction["runner_up"]["category"],
        "runner_up_confidence": Decimal(str(round(prediction["runner_up"]["confidence"], 4))),
        "gate_action": gate_result["action"],
        "gate_reason": gate_result.get("reason", ""),
        "final_category": "",  # populated after human review, if applicable
    }

    # Write to DynamoDB.
    table.put_item(Item=record)
    logger.info("Stored classification record: %s", record["complaint_id"])

    # Route based on gate decision.
    if gate_result["action"] == "REVIEW":
        # Send to SQS review queue for human classification.
        sqs_client.send_message(
            QueueUrl=REVIEW_QUEUE_URL,
            MessageBody=json.dumps({
                "complaint_id": record["complaint_id"],
                "original_text": original_text,
                "top_category": prediction["category"],
                "confidence": float(prediction["confidence"]),
                "runner_up": prediction["runner_up"]["category"],
                "reason": gate_result.get("reason", ""),
            }),
        )
        logger.info("Sent to review queue (reason: %s)", gate_result.get("reason"))

    return record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single callable function. This is what your Lambda handler would invoke after parsing the incoming API Gateway event.

```python
def classify_chief_complaint(raw_text: str, enrich: bool = False) -> dict:
    """
    Run the full chief complaint classification pipeline.

    Args:
        raw_text: The original chief complaint as entered by the clerk/patient/kiosk.
        enrich: Whether to run Comprehend Medical entity detection (adds ~100ms latency
                and ~$0.01 per call). Useful for short/ambiguous inputs.

    Returns:
        The stored classification record with routing decision.
    """
    logger.info("=== Chief Complaint Classification Pipeline ===")

    # Step 1: Load abbreviation map and preprocess.
    logger.info("Step 1: Preprocessing")
    abbreviation_map = load_abbreviation_map()
    preprocessed = preprocess_complaint(raw_text, abbreviation_map)
    logger.info("  Original: '%s'", raw_text)
    logger.info("  Preprocessed: '%s'", preprocessed)

    # Step 2: Optional entity enrichment.
    if enrich:
        logger.info("Step 2: Entity enrichment (enabled)")
        entities = enrich_with_entities(preprocessed)
        logger.info("  Entities found: %d", len(entities))
        # In a more advanced version, you'd append entity types to the classifier
        # input or use them as secondary features. For this example, we log them.
        for ent in entities:
            logger.info("    %s (%s, %.0f%%)", ent["text"], ent["category"], ent["score"] * 100)
    else:
        logger.info("Step 2: Entity enrichment (skipped)")

    # Step 3: Classify.
    logger.info("Step 3: Classification")
    prediction = classify_complaint(preprocessed)

    # Step 4: Confidence gate.
    logger.info("Step 4: Confidence gating")
    gate_result = apply_confidence_gate(prediction)
    logger.info("  Decision: %s (reason: %s)", gate_result["action"], gate_result.get("reason"))

    # Step 5: Store and route.
    logger.info("Step 5: Store and route")
    record = store_and_route(raw_text, preprocessed, prediction, gate_result)

    logger.info("=== Done. ID: %s | Action: %s ===", record["complaint_id"], gate_result["action"])
    return record

# --- Example usage ---
if __name__ == "__main__":
    # Test with a few sample chief complaints to see the pipeline in action.
    test_complaints = [
        "CP x 2 days, worse w/ exertion",
        "sob and cough x 1 week",
        "HA",
        "fell and hit head, small lac on forehead",
        "n/v x 3 days, unable to keep food down",
        "pain",  # intentionally vague, should trigger low confidence
    ]

    for complaint in test_complaints:
        print(f"\n{'=' * 60}")
        print(f"Input: {complaint}")
        print(f"{'=' * 60}")
        result = classify_chief_complaint(complaint, enrich=False)
        print(json.dumps(
            {k: str(v) if isinstance(v, Decimal) else v for k, v in result.items()},
            indent=2,
        ))
```

---

## The Gap Between This and Production

This example gives you the shape of the pipeline. Here's the distance between this code and something you'd deploy in a real ED registration workflow:

**Error handling and resilience.** Every external call (Comprehend, DynamoDB, SQS) can fail. This code lets exceptions propagate. A production system catches specific exceptions (throttling, timeout, service unavailable), retries with backoff, and has a fallback path. If Comprehend is down, you might route all complaints to the human queue rather than failing the registration workflow entirely. The patient shouldn't wait because your ML model is having a bad day.

**Cold start latency.** Lambda cold starts add 1-3 seconds on the first invocation. For an interactive registration workflow where a clerk is waiting for the classification, that's noticeable. Production mitigations: use provisioned concurrency for the Lambda, or cache the abbreviation map in a Lambda layer so you skip the DynamoDB scan on warm invocations.

**Abbreviation map caching.** This code calls DynamoDB on every invocation to load the abbreviation map. In production, cache it in Lambda memory with a TTL (reload every 5 minutes, for example). The map changes infrequently; reading it from DynamoDB on every request adds unnecessary latency and cost.

**Input validation.** This code trusts that `raw_text` is a reasonable string. A production system validates: is it non-empty? Is it under a reasonable length (Comprehend has a 5,000-byte limit per ClassifyDocument call)? Does it contain only expected character sets? Reject or truncate malformed inputs before they hit the classifier.

**PHI handling in logs.** The logger statements here print the original and preprocessed complaint text. In production, chief complaints are PHI. Never log them in plaintext. Log a hash or a complaint_id reference, and store the actual text only in encrypted DynamoDB records where access is audited.

**Classifier endpoint management.** This code assumes the endpoint exists and is healthy. Production needs: health checks on the endpoint, automatic failover if the endpoint becomes unresponsive, and a process for deploying new model versions without downtime (Comprehend supports endpoint updates with new model artifacts).

**Retraining pipeline.** Every human correction in the review queue should feed back as new training data. Production systems have an automated pipeline that periodically retrains the Comprehend model on the accumulated corrections, evaluates the new model against a held-out test set, and promotes it to the endpoint if accuracy improves. Without this loop, the model goes stale.

**Multi-complaint handling.** This code assigns a single category. Real chief complaints often contain multiple issues ("cp and sob," "fall with lac and HA"). A production system either uses Comprehend's multi-label mode or runs a preliminary step that splits multi-complaint entries before classification.

**DynamoDB data types.** All numeric values stored in DynamoDB use `Decimal` (not float). This code handles that correctly, but if you add new numeric fields, remember to wrap them. The `boto3` DynamoDB resource will raise a `TypeError` on raw floats.

**VPC and encryption.** Production Lambda runs in a VPC with private subnets. VPC endpoints for Comprehend, DynamoDB, SQS, and CloudWatch Logs keep all traffic off the public internet. KMS customer-managed keys encrypt both DynamoDB tables and the SQS queue. This code doesn't configure any of that because it's infrastructure, not application logic, but it's required before PHI touches the system.

**Testing.** There are no tests here. A production pipeline has: unit tests for `preprocess_complaint` (with known abbreviation expansions), integration tests against a live Comprehend endpoint with known-good test inputs, accuracy regression tests that run the full pipeline against a labeled evaluation set after each model update, and load tests to verify latency under realistic concurrency.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 8.1](chapter08.01-chief-complaint-classification) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
