# Recipe 8.1: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 8.1. It shows one way you could translate those concepts into working Python using boto3. It is not production-ready. There's no error handling, no retry logic, no input validation, no tests. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to an ED triage desk on Monday morning. A starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `comprehend:ClassifyDocument` (for the custom classifier endpoint)
- `comprehend-medical:DetectEntitiesV2` (for entity enrichment)
- `dynamodb:GetItem`, `dynamodb:PutItem` (abbreviation map and results table)
- `sqs:SendMessage` (review queue)

---

## Config and Constants

Before we get to the steps, here are the configuration values and lookup tables the pipeline uses. These live at the top of your module so they're easy to find and tune. The abbreviation map is the piece that will grow the most over time as you encounter institution-specific shorthand.

```python
# ABBREVIATION_MAP: maps lowercase abbreviations to their expanded clinical terms.
#
# This is the single most institution-specific piece of the pipeline.
# Every ED, urgent care, and nurse hotline has its own shorthand.
# Treat this as a living dictionary. When the preprocessing step encounters
# an unknown token that later gets manually classified, add it here.
#
# Start with the common ones and grow from there.

ABBREVIATION_MAP = {
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
    "doi": "date of injury",
    "ams": "altered mental status",
    "etoh": "alcohol",
    "oi": "orthopedic injury",
    "fb": "foreign body",
    "si": "suicidal ideation",
    "chi": "closed head injury",
    "dka": "diabetic ketoacidosis",
    "dvt": "deep vein thrombosis",
    "pe": "pulmonary embolism",
    "mi": "myocardial infarction",
    "cva": "cerebrovascular accident",
    "tia": "transient ischemic attack",
    "rti": "respiratory tract infection",
    "lle": "left lower extremity",
    "rle": "right lower extremity",
    "lue": "left upper extremity",
    "rue": "right upper extremity",
}

# Confidence threshold: predictions below this go to human review.
# Start conservative (85%) and lower as you gain confidence in the model.
CONFIDENCE_THRESHOLD = 0.85

# Ambiguity gap: if the top two predictions are closer than this,
# the model is basically guessing between them. Flag for review.
AMBIGUITY_GAP = 0.15

# ARN of your deployed Comprehend custom classifier endpoint.
# You get this after training and deploying a custom model in Comprehend.
CLASSIFIER_ENDPOINT_ARN = "arn:aws:comprehend:us-east-1:123456789012:document-classifier-endpoint/chief-complaint-v1"

# DynamoDB table names.
RESULTS_TABLE = "complaint-classifications"
ABBREVIATION_TABLE = "abbreviation-map"  # optional: use DynamoDB instead of hardcoded dict

# SQS queue URL for low-confidence review routing.
REVIEW_QUEUE_URL = "https://sqs.us-east-1.amazonaws.com/123456789012/complaint-review-queue"
```

---

## Step 1: Preprocess the Chief Complaint

*The pseudocode calls this `preprocess_complaint(raw_text, abbreviation_map)`. It lowercases the input, strips non-clinical punctuation, and expands known abbreviations into their full clinical terms.*

```python
import re
import logging
import boto3
from botocore.config import Config
from decimal import Decimal
import datetime
from datetime import timezone
import uuid

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights. Never log the actual complaint text in
# production (it's PHI).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config for all AWS clients. Adaptive mode handles throttling
# with exponential backoff and jitter.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})


def preprocess_complaint(raw_text: str) -> str:
    """
    Clean and normalize a raw chief complaint for classification.

    This handles the messiest part of the problem: chief complaints arrive
    in every imaginable format. "CP x 2 days", "CHEST PAIN", "cp w/ sob",
    "Chest pain, worse with exertion." all need to become something the
    classifier can work with consistently.

    Args:
        raw_text: The chief complaint exactly as entered by the clerk,
                  nurse, patient, or kiosk.

    Returns:
        Cleaned, expanded text ready for classification.
    """
    # Lowercase everything. Chief complaints come in ALL CAPS, Title Case,
    # and random mixtures. The classifier shouldn't need to learn that
    # "CHEST PAIN" and "chest pain" are the same thing.
    text = raw_text.lower().strip()

    # Remove characters that add no clinical meaning.
    # Keep: letters, numbers, spaces, and forward slashes (for "n/v", "n/v/d").
    # Drop: periods, commas, parentheses, quotes, etc.
    # The regex keeps [a-z0-9\s/] and removes everything else.
    text = re.sub(r"[^a-z0-9\s/]", "", text)

    # Collapse multiple spaces into one (from removed punctuation).
    text = re.sub(r"\s+", " ", text).strip()

    # Expand abbreviations using the lookup map.
    # Split into tokens, check each against the map, replace if found.
    tokens = text.split()
    expanded = []

    for token in tokens:
        if token in ABBREVIATION_MAP:
            # Replace abbreviation with its full clinical term.
            # "cp" becomes "chest pain" (two words injected, which is fine).
            expanded.append(ABBREVIATION_MAP[token])
        else:
            expanded.append(token)

    return " ".join(expanded)
```

---

## Step 2: Enrich with Medical Entity Detection

*The pseudocode calls this `enrich_with_entities(preprocessed_text)`. It uses Amazon Comprehend Medical to detect clinical entities in the text, confirming whether terms are symptoms, conditions, or body parts. This step is optional but helps with ambiguous short inputs.*

```python
# Comprehend Medical client for entity detection.
comprehend_medical_client = boto3.client(
    "comprehendmedical", config=BOTO3_RETRY_CONFIG
)


def enrich_with_entities(preprocessed_text: str) -> list:
    """
    Use Comprehend Medical to detect clinical entities in the complaint.

    This is optional enrichment. For clear, well-expanded complaints like
    "chest pain worse with exertion," the classifier will do fine without it.
    For ambiguous inputs like "pain" or "sick," entity detection provides
    additional signal by confirming what type of clinical concept the text contains.

    In a production system, you'd call this selectively (only for short or
    low-confidence inputs) to save cost. Comprehend Medical charges per
    character, so running it on every complaint adds up.

    Args:
        preprocessed_text: Cleaned complaint text from Step 1.

    Returns:
        List of detected entities with their types and confidence scores.
    """
    # Call the DetectEntitiesV2 API. The "V2" version is the current one;
    # the original DetectEntities is deprecated.
    response = comprehend_medical_client.detect_entities_v2(
        Text=preprocessed_text
    )

    # Extract the entities Comprehend Medical found.
    # Each entity has: Text, Category, Type, Score, Traits, Attributes.
    # We care about Category (MEDICAL_CONDITION, ANATOMY, etc.) and Score.
    entities = []
    for entity in response.get("Entities", []):
        entities.append({
            "text": entity["Text"],
            "category": entity["Category"],
            "type": entity["Type"],
            "score": entity["Score"],
            # Traits tell us about negation, uncertainty, etc.
            # "chest pain" with a NEGATION trait means "denies chest pain."
            "traits": [t["Name"] for t in entity.get("Traits", [])],
        })

    return entities
```

---

## Step 3: Classify the Complaint

*The pseudocode calls this `classify_complaint(preprocessed_text, endpoint_arn)`. This is the core step: send the cleaned text to the Comprehend custom classifier endpoint and get back a ranked list of categories with confidence scores.*

```python
# Comprehend client for custom classification.
comprehend_client = boto3.client("comprehend", config=BOTO3_RETRY_CONFIG)


def classify_complaint(preprocessed_text: str) -> dict:
    """
    Classify the preprocessed complaint into a clinical category.

    The custom classifier endpoint was trained on your institution's historical
    chief complaints paired with the categories they were ultimately routed to.
    It returns a ranked list of categories sorted by confidence.

    Args:
        preprocessed_text: Cleaned, expanded complaint text from Step 1.

    Returns:
        Dictionary with the top prediction, runner-up, and full ranked list.
    """
    # Call the ClassifyDocument API against our custom endpoint.
    # The endpoint hosts the model trained on our labeled data.
    response = comprehend_client.classify_document(
        Text=preprocessed_text,
        EndpointArn=CLASSIFIER_ENDPOINT_ARN,
    )

    # The response contains a "Classes" list sorted by confidence (highest first).
    # Each class has a "Name" (the category label) and "Score" (0.0 to 1.0).
    classes = response.get("Classes", [])

    if len(classes) < 2:
        # Edge case: if somehow fewer than 2 classes returned.
        # In practice this shouldn't happen with a properly trained model.
        top = classes[0] if classes else {"Name": "UNKNOWN", "Score": 0.0}
        runner_up = {"Name": "UNKNOWN", "Score": 0.0}
    else:
        top = classes[0]
        runner_up = classes[1]

    return {
        "category": top["Name"],
        "confidence": top["Score"],
        "runner_up": {
            "category": runner_up["Name"],
            "confidence": runner_up["Score"],
        },
        "all_predictions": [
            {"category": c["Name"], "confidence": c["Score"]}
            for c in classes
        ],
    }
```

---

## Step 4: Apply Confidence Gating

*The pseudocode calls this `apply_confidence_gate(prediction)`. It checks whether the prediction is confident enough for automated routing, or whether a human should review it.*

```python
def apply_confidence_gate(prediction: dict) -> dict:
    """
    Decide whether this prediction is trustworthy enough to route automatically.

    Two checks:
    1. Is the top prediction above the confidence threshold?
    2. Is there enough gap between the top two predictions?

    If either check fails, the complaint goes to human review rather than
    being routed automatically. In healthcare, a wrong routing decision has
    real consequences (a cardiac chest pain patient sent to a non-urgent track),
    so we err on the side of human review for borderline cases.

    Args:
        prediction: Output from classify_complaint() with category, confidence,
                    and runner_up fields.

    Returns:
        Dictionary with action ("ROUTE" or "REVIEW") and supporting metadata.
    """
    # Check 1: Is the top prediction confident enough on its own?
    if prediction["confidence"] < CONFIDENCE_THRESHOLD:
        return {
            "action": "REVIEW",
            "reason": "low_confidence",
            "category": prediction["category"],
            "confidence": prediction["confidence"],
        }

    # Check 2: Is the gap between top and runner-up large enough?
    # A 87% prediction with an 84% runner-up means the model is basically
    # flipping a coin between two categories. That's not safe to automate.
    gap = prediction["confidence"] - prediction["runner_up"]["confidence"]
    if gap < AMBIGUITY_GAP:
        return {
            "action": "REVIEW",
            "reason": "ambiguous_top_two",
            "category": prediction["category"],
            "confidence": prediction["confidence"],
            "runner_up_category": prediction["runner_up"]["category"],
            "runner_up_confidence": prediction["runner_up"]["confidence"],
        }

    # Both checks passed. Safe to route automatically.
    return {
        "action": "ROUTE",
        "reason": None,
        "category": prediction["category"],
        "confidence": prediction["confidence"],
    }
```

---

## Step 5: Store Results and Route

*The pseudocode calls this `store_and_route(original_text, preprocessed_text, prediction, gate_result)`. It writes the classification record to DynamoDB and routes to either the downstream system or the human review queue.*

```python
# DynamoDB resource for storing classification results.
dynamodb = boto3.resource("dynamodb")

# SQS client for the review queue.
sqs_client = boto3.client("sqs", config=BOTO3_RETRY_CONFIG)


def store_and_route(
    original_text: str,
    preprocessed_text: str,
    prediction: dict,
    gate_result: dict,
) -> dict:
    """
    Persist the classification result and route it appropriately.

    Every classification gets stored in DynamoDB regardless of routing decision.
    This creates:
    - The HIPAA audit trail (who classified what, when, with what confidence)
    - Retraining data (especially the human-corrected low-confidence ones)
    - Analytics data (complaint volume by category over time)

    High-confidence predictions go directly to downstream consumers.
    Low-confidence predictions go to SQS for human review.

    Args:
        original_text: What the user actually typed.
        preprocessed_text: After abbreviation expansion and cleaning.
        prediction: Full classifier output from Step 3.
        gate_result: Routing decision from Step 4.

    Returns:
        The complete classification record as stored.
    """
    table = dynamodb.Table(RESULTS_TABLE)

    # Generate a unique ID for this classification event.
    complaint_id = f"cc-{datetime.date.today().isoformat()}-{uuid.uuid4().hex[:8]}"

    # Build the record. DynamoDB requires Decimal for numeric values,
    # not Python floats. Wrap all scores in Decimal via str() to avoid
    # floating-point precision artifacts.
    record = {
        "complaint_id": complaint_id,
        "timestamp": datetime.datetime.now(timezone.utc).isoformat(),
        "original_text": original_text,
        "preprocessed": preprocessed_text,
        "predicted_category": prediction["category"],
        "confidence": Decimal(str(round(prediction["confidence"], 4))),
        "runner_up_category": prediction["runner_up"]["category"],
        "runner_up_confidence": Decimal(
            str(round(prediction["runner_up"]["confidence"], 4))
        ),
        "gate_action": gate_result["action"],
        "gate_reason": gate_result.get("reason", "none"),
        # final_category is populated later by human reviewers (if applicable).
        "final_category": None,
    }

    # Write to DynamoDB.
    table.put_item(Item=record)

    # Route based on the gate decision.
    if gate_result["action"] == "REVIEW":
        # Low confidence or ambiguous. Send to the review queue.
        sqs_client.send_message(
            QueueUrl=REVIEW_QUEUE_URL,
            MessageBody=str({
                "complaint_id": complaint_id,
                "original_text": original_text,
                "top_category": prediction["category"],
                "confidence": prediction["confidence"],
                "runner_up": prediction["runner_up"]["category"],
                "reason": gate_result["reason"],
            }),
            # Group by category so reviewers can batch similar complaints.
            MessageGroupId=prediction["category"].replace(" ", "-").lower()
            if REVIEW_QUEUE_URL.endswith(".fifo")
            else None,
        )

    return record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. In a Lambda deployment, your handler would extract the complaint text from the incoming event and call this.

```python
def classify_chief_complaint(raw_text: str, enrich: bool = False) -> dict:
    """
    Run the full chief complaint classification pipeline.

    Args:
        raw_text: The chief complaint as entered by the user/clerk/kiosk.
        enrich: Whether to call Comprehend Medical for entity enrichment.
                  Set to True for short or ambiguous inputs; False for clear ones.

    Returns:
        The stored classification record with routing decision.
    """
    # Step 1: Clean and expand abbreviations.
    logger.info("Step 1: Preprocessing complaint")
    preprocessed = preprocess_complaint(raw_text)
    logger.info("  Original: [PHI redacted, %d chars]", len(raw_text))
    logger.info("  Preprocessed: [PHI redacted, %d chars]", len(preprocessed))

    # Step 2 (optional): Enrich with medical entity detection.
    if enrich:
        logger.info("Step 2: Enriching with Comprehend Medical entities")
        entities = enrich_with_entities(preprocessed)
        logger.info("  Detected %d entities", len(entities))
        # In a more sophisticated version, you'd append entity types
        # to the classifier input. For this example, we log them for
        # analytics but classify on the preprocessed text alone.
    else:
        logger.info("Step 2: Skipping entity enrichment (enrich=False)")

    # Step 3: Classify using the Comprehend custom endpoint.
    logger.info("Step 3: Classifying complaint")
    prediction = classify_complaint(preprocessed)
    logger.info(
        "  Top: %s (%.1f%%), Runner-up: %s (%.1f%%)",
        prediction["category"],
        prediction["confidence"] * 100,
        prediction["runner_up"]["category"],
        prediction["runner_up"]["confidence"] * 100,
    )

    # Step 4: Apply confidence gating.
    logger.info("Step 4: Applying confidence gate")
    gate_result = apply_confidence_gate(prediction)
    logger.info("  Decision: %s (reason: %s)", gate_result["action"], gate_result.get("reason"))

    # Step 5: Store and route.
    logger.info("Step 5: Storing result and routing")
    record = store_and_route(raw_text, preprocessed, prediction, gate_result)
    logger.info("  Stored as %s, action=%s", record["complaint_id"], gate_result["action"])

    return record


# --- Example usage with synthetic data ---

if __name__ == "__main__":
    import json

    # Synthetic chief complaints for testing.
    # These are made-up examples, not real patient data.
    test_complaints = [
        "CP x 2 days, worse w/ exertion",
        "sob and cough x 1 week",
        "HA since yesterday, no fever",
        "abd pain n/v",
        "lac to left hand from knife",
        "mva, neck pain",
        "feeling dizzy and lightheaded",
        "uti symptoms burning with urination",
        "twisted ankle playing basketball",
        "chest tightness and sweating",
    ]

    print("=" * 70)
    print("Chief Complaint Classification Pipeline")
    print("=" * 70)

    for complaint in test_complaints:
        print(f"\nInput: {complaint}")
        result = classify_chief_complaint(complaint, enrich=False)
        print(f"  Category: {result['predicted_category']}")
        print(f"  Confidence: {result['confidence']}")
        print(f"  Action: {result['gate_action']}")
        print(f"  ID: {result['complaint_id']}")

    print("\n" + "=" * 70)
    print("Done. Check DynamoDB and SQS for stored results.")
```

---

## The Gap Between This and Production

This example demonstrates the shape of the solution. Run it against a deployed Comprehend endpoint with a trained model and it will classify chief complaints into categories. But here's the distance between this and something you'd put in front of real triage workflows:

**Error handling.** If Comprehend returns an error (throttling, endpoint not found, model not ready), this code crashes. A production system catches specific exceptions (`ThrottlingException`, `ResourceNotFoundException`, `InternalServerException`), handles each appropriately (retry, alert, degrade gracefully), and never loses a complaint silently. A failed classification should default to human routing, not to an unhandled exception.

**Retries and backoff.** The `BOTO3_RETRY_CONFIG` handles some retries at the SDK level, but Comprehend endpoints under load can return transient errors that need application-level retry logic. For a classification that sits in the patient registration workflow, you need to either succeed or fail fast (under 2 seconds). A retry with 1-second backoff that fails after 3 attempts should route to human review with an "automated classification unavailable" flag.

**Input validation.** This code sends whatever text it receives to Comprehend. A production system validates: Is the text non-empty? Is it under Comprehend's character limit (5,000 for ClassifyDocument)? Does it contain enough signal to classify (rejecting single-character inputs)? Is it in the expected language? Garbage in produces garbage out, and a classifier will happily return a 60% confidence prediction for "asdfghjkl" rather than telling you it's nonsense.

**Structured logging.** The `logger.info()` calls here are illustrative. A production system uses structured JSON logging (AWS Lambda Powertools is excellent for this) with consistent fields: `complaint_id`, `latency_ms`, `confidence`, `action`, `error_type`. This is what your on-call engineer queries at 3am when the review queue is backing up.

**PHI safety.** This example logs the original complaint text in the `__main__` block. In production, never log complaint text to CloudWatch. Chief complaints are PHI. Log the complaint ID, character count, predicted category, and confidence. If you need the text for debugging, look it up in DynamoDB (which is encrypted and access-controlled).

**IAM least-privilege.** The Lambda running this pipeline needs exactly: `comprehend:ClassifyDocument` scoped to the specific endpoint ARN, `comprehend-medical:DetectEntitiesV2`, `dynamodb:PutItem` scoped to the results table, `sqs:SendMessage` scoped to the review queue URL, and `logs:CreateLogGroup/PutLogEvents` for CloudWatch. Not `comprehend:*`. Not `dynamodb:*`. Scope everything.

**VPC configuration.** Chief complaints are PHI. In production, this Lambda runs in a VPC with private subnets. VPC endpoints for Comprehend, Comprehend Medical, DynamoDB, SQS, and CloudWatch keep all traffic on the AWS backbone. No PHI traverses the public internet.

**KMS encryption.** This example uses default encryption. Production uses customer-managed KMS keys for the DynamoDB table and SQS queue, with key rotation enabled and CloudTrail logging every key usage event. The S3 bucket holding training data also uses a CMK.

**DynamoDB Decimal handling.** This example already wraps confidence scores in `Decimal(str(...))` (Step 5), which is required because DynamoDB's boto3 resource layer rejects Python floats. Any numeric field you add later must follow the same pattern. The `boto3` DynamoDB resource will raise `TypeError: Float types are not supported` on raw floats.

**The abbreviation map lifecycle.** The hardcoded `ABBREVIATION_MAP` works for development. In production, store it in DynamoDB (or Parameter Store) so you can update it without redeploying the Lambda. Build a simple admin interface that surfaces unknown tokens from preprocessing (tokens not in the map and not in a standard medical dictionary). When a reviewer manually classifies a complaint, check whether it contained unknown abbreviations and prompt for additions.

**Model retraining.** Every human correction to a low-confidence prediction is a labeled training example. Build automation that periodically exports corrected records from DynamoDB, formats them as Comprehend training data (CSV with text and label columns), and triggers a new training job. Quarterly retraining at minimum; monthly is better. Track model accuracy on a held-out test set after each retraining to confirm the new model is better than the old one before swapping endpoints.

**Testing.** This example has no tests. A production pipeline has: unit tests for `preprocess_complaint` (with known abbreviations and edge cases), unit tests for `apply_confidence_gate` (boundary conditions around thresholds), integration tests against a deployed Comprehend endpoint with known test complaints, and a regression test suite of complaints that previously caused errors. Never use real patient complaints in test fixtures; generate synthetic ones that cover the same patterns.

**Multi-complaint handling.** This example classifies to a single category. Real complaints often contain multiple concerns ("chest pain and shortness of breath"). A production system either uses multi-label classification (Comprehend supports this mode) or splits multi-complaint entries before classification. Recipe 8.1 discusses this in the Variations section.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 8.1](chapter08.01-chief-complaint-classification) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
