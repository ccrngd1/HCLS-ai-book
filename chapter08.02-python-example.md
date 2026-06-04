# Recipe 8.2: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 8.2. It shows one way you could translate those concepts into working Python code using boto3 and Amazon Comprehend. It is not production-ready. There's no retry logic, no proper error handling, no VPC configuration, and no batch optimization. Think of it as the sketchpad version: useful for understanding how the pieces fit together, not something you'd point at 50,000 real patient surveys. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python installed:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `comprehend:DetectSentiment`
- `comprehend:DetectEntities`
- `comprehend:ClassifyDocument`
- `comprehendmedical:DetectPHI`
- `s3:GetObject`
- `s3:PutObject`
- `dynamodb:PutItem`
- `dynamodb:Query`
- `events:PutEvents`

You also need a trained custom classifier endpoint for aspect detection. Training that classifier is covered in the "Gap to Production" section below. For this example, we simulate aspect classification with a rule-based fallback so you can run the pipeline end-to-end without deploying a custom model first.

---

## Configuration and Constants

These live at the top of the module. The aspect taxonomy and confidence thresholds are configuration, not logic. Edit these as your patient experience team refines what they want to track.

```python
import logging
import json
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, emit JSON for CloudWatch Logs Insights.
# Never log raw patient feedback text (it contains PHI).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles Comprehend throttling gracefully.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# Module-level clients for reuse in warm Lambda containers.
comprehend_client = boto3.client("comprehend", config=BOTO3_RETRY_CONFIG)
comprehend_medical_client = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb")
events_client = boto3.client("events", config=BOTO3_RETRY_CONFIG)

# DynamoDB table for storing analysis results.
RESULTS_TABLE_NAME = "sentiment-results"

# Confidence threshold for accepting aspect classification predictions.
# Below this, the aspect assignment is too uncertain to be useful in dashboards.
# 0.6 is conservative; tune based on your labeled validation set.
ASPECT_CONFIDENCE_THRESHOLD = 0.6

# Confidence threshold for triggering the "needs_attention" alert.
# High-confidence negative sentiment on critical aspects gets routed to humans immediately.
ATTENTION_CONFIDENCE_THRESHOLD = 0.85

# Aspects that trigger immediate attention when negative, regardless of confidence.
# Pain management and care coordination problems can indicate safety concerns.
CRITICAL_ASPECTS = ["pain_management", "care_coordination"]

# The aspect taxonomy. Each entry maps to a category your patient experience team tracks.
# This should match whatever labels you used to train your custom classifier.
ASPECT_TAXONOMY = [
    "wait_time",
    "provider_communication",
    "staff_interaction",
    "facility_environment",
    "billing_insurance",
    "care_coordination",
    "pain_management",
    "discharge_process",
    "access_convenience",
    "overall_experience",
]

# Keyword-based fallback for aspect detection when no custom classifier is deployed.
# In production, replace this with a call to your trained Comprehend custom classifier.
# This exists so you can run the full pipeline during development without the classifier.
ASPECT_KEYWORDS = {
    "wait_time": ["wait", "waited", "waiting", "delayed", "late", "on time", "appointment time", "schedule"],
    "provider_communication": ["doctor", "physician", "provider", "explained", "listened", "thorough", "rushed", "dismissive"],
    "staff_interaction": ["nurse", "staff", "receptionist", "front desk", "friendly", "rude", "helpful"],
    "facility_environment": ["clean", "dirty", "cold", "hot", "parking", "waiting room", "comfortable", "noise"],
    "billing_insurance": ["bill", "billing", "charge", "insurance", "cost", "price", "surprise", "statement", "copay"],
    "care_coordination": ["referral", "follow-up", "follow up", "coordinated", "lost", "fell through", "between doctors"],
    "pain_management": ["pain", "hurt", "medication", "relief", "suffering", "comfortable"],
    "discharge_process": ["discharge", "instructions", "leaving", "sent home", "ready to leave"],
    "access_convenience": ["hours", "location", "telehealth", "virtual", "available", "weekend", "evening"],
    "overall_experience": ["overall", "experience", "recommend", "return", "general"],
}
```

---

## Step 1: PHI Detection and Redaction

*The pseudocode calls this `detect_and_redact_phi(feedback_text)`. This is the mandatory first step: scan the text for protected health information and replace it with type-labeled placeholders. Patient feedback routinely contains provider names, specific diagnoses, medication names, and dates. The redacted version is what flows to all downstream analysis.*

```python
def detect_and_redact_phi(feedback_text: str) -> dict:
    """
    Scan patient feedback for PHI and produce a redacted version.

    Uses Amazon Comprehend Medical's DetectPHI API, which is specifically
    designed to find protected health information in unstructured text.
    This is different from Comprehend's generic PII detection: the medical
    variant understands clinical entity types like PROCEDURE, MEDICATION,
    and DIAGNOSIS that generic PII detection misses.

    The redacted text replaces each PHI entity with a bracketed type label.
    Example: "Dr. Smith prescribed Metformin" becomes
             "[NAME] prescribed [MEDICATION]"

    This preserves sentence structure and sentiment-bearing words while
    removing identifiable information. Sentiment analysis works fine on
    redacted text because the emotional content lives in words like
    "wonderful", "frustrated", "waited" - not in the names and dates.

    Args:
        feedback_text: Raw patient feedback text (may contain PHI).

    Returns:
        Dict with:
        - redacted_text: PHI replaced with type placeholders
        - phi_detected: bool indicating whether any PHI was found
        - entity_count: number of PHI entities detected
    """
    # Comprehend Medical DetectPHI has a 20,000 character limit per call.
    # Patient survey responses rarely exceed this. Call transcripts might.
    # For longer texts, you'd chunk by sentence boundary and reassemble.
    response = comprehend_medical_client.detect_phi(Text=feedback_text)

    entities = response.get("Entities", [])

    # Build the redacted version by replacing entities back-to-front.
    # Processing from the end of the string backward ensures that character
    # offsets for earlier entities remain valid as we modify the string.
    redacted_text = feedback_text

    # Sort by BeginOffset descending so we replace from back to front.
    sorted_entities = sorted(entities, key=lambda e: e["BeginOffset"], reverse=True)

    for entity in sorted_entities:
        begin = entity["BeginOffset"]
        end = entity["EndOffset"]
        entity_type = entity["Type"]
        # Replace the PHI span with a bracketed type label.
        # "[NAME]" instead of "Dr. Smith", "[DATE]" instead of "March 15th"
        redacted_text = redacted_text[:begin] + f"[{entity_type}]" + redacted_text[end:]

    logger.info(
        "PHI detection complete: %d entities found and redacted",
        len(entities),
    )

    return {
        "redacted_text": redacted_text,
        "phi_detected": len(entities) > 0,
        "entity_count": len(entities),
    }
```

---

## Step 2: Sentiment Analysis

*The pseudocode calls this `analyze_sentiment(redacted_text)`. This calls Amazon Comprehend's built-in sentiment detection on the redacted text. The key insight: store the full score distribution (positive, negative, neutral, mixed), not just the top label. A comment that's 55% negative and 40% positive tells a very different story than one that's 95% negative.*

```python
def analyze_sentiment(redacted_text: str) -> dict:
    """
    Run document-level sentiment analysis on the redacted feedback text.

    Returns the overall sentiment label plus the full confidence distribution
    across all four categories. The distribution matters more than the label
    for aggregate analysis: when you average sentiment scores across hundreds
    of feedback items, the nuance in the distribution surfaces trends that
    binary labels miss.

    Comprehend's DetectSentiment supports texts up to 5,000 bytes (UTF-8).
    Average patient survey responses are 200-500 characters, well within limits.

    Args:
        redacted_text: PHI-redacted feedback text from Step 1.

    Returns:
        Dict with:
        - sentiment: top label (POSITIVE, NEGATIVE, NEUTRAL, MIXED)
        - scores: full distribution across all four categories
        - confidence: the highest score (how decisive the classification is)
    """
    response = comprehend_client.detect_sentiment(
        Text=redacted_text,
        LanguageCode="en",  # For multilingual populations, detect language first
    )

    scores = response["SentimentScore"]

    return {
        "sentiment": response["Sentiment"],  # "POSITIVE", "NEGATIVE", "NEUTRAL", "MIXED"
        "scores": {
            "positive": scores["Positive"],
            "negative": scores["Negative"],
            "neutral": scores["Neutral"],
            "mixed": scores["Mixed"],
        },
        # Confidence = how strongly the model believes its top prediction.
        # Low confidence (< 0.5) usually means the text is genuinely mixed.
        "confidence": max(scores["Positive"], scores["Negative"], scores["Neutral"], scores["Mixed"]),
    }
```

---

## Step 3: Aspect Extraction

*The pseudocode calls this `extract_aspects(redacted_text, document_sentiment)`. This is where generic sentiment becomes actionable. We split the text into sentences, classify each sentence's aspect, and capture per-aspect sentiment. In production, you'd use a trained Comprehend custom classifier. This example includes a keyword-based fallback so you can run the pipeline without deploying a model first.*

```python
def split_into_sentences(text: str) -> list:
    """
    Split text into sentences using simple heuristics.

    A proper NLP sentence tokenizer (like spaCy's) handles edge cases better:
    abbreviations ("Dr."), decimal numbers ("3.5mg"), ellipses ("...").
    This naive split works for typical patient feedback but will occasionally
    split mid-sentence on abbreviations.

    For production, use spaCy or NLTK's Punkt tokenizer. We keep this simple
    here to avoid additional dependencies.
    """
    # Split on period, exclamation, or question mark followed by a space or end of string.
    import re
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    # Filter out empty strings and very short fragments (< 10 chars).
    return [s.strip() for s in sentences if len(s.strip()) >= 10]


def classify_aspect_keyword_fallback(sentence: str) -> tuple:
    """
    Fallback aspect classifier using keyword matching.

    This is NOT what you'd use in production. A trained custom classifier
    understands context: "the doctor kept me waiting" is about wait_time,
    not provider_communication, even though "doctor" is present. Keywords
    can't make that distinction.

    This exists so you can run the full pipeline end-to-end during development
    before you've trained and deployed your Comprehend custom classifier.

    Returns:
        Tuple of (aspect_name, confidence_score).
        Confidence is synthetic (0.7 for keyword match, 0.3 for no match).
    """
    sentence_lower = sentence.lower()
    best_aspect = "overall_experience"  # default if no keywords match
    best_score = 0

    for aspect, keywords in ASPECT_KEYWORDS.items():
        matches = sum(1 for kw in keywords if kw in sentence_lower)
        if matches > best_score:
            best_score = matches
            best_aspect = aspect

    # Synthetic confidence: keyword matching is inherently less reliable.
    confidence = 0.7 if best_score > 0 else 0.3
    return best_aspect, confidence


def classify_aspect_with_comprehend(sentence: str, endpoint_arn: str) -> tuple:
    """
    Classify which aspect a sentence discusses using a trained custom classifier.

    This is the production approach. You train a Comprehend custom classifier
    on labeled healthcare feedback (a few hundred examples per aspect category),
    deploy it to a real-time endpoint, and call ClassifyDocument here.

    The endpoint_arn points to your deployed classifier. Training and deployment
    are covered in the Gap to Production section.

    Args:
        sentence: One sentence from the feedback text.
        endpoint_arn: ARN of the deployed custom classifier endpoint.

    Returns:
        Tuple of (aspect_name, confidence_score).
    """
    response = comprehend_client.classify_document(
        Text=sentence,
        EndpointArn=endpoint_arn,
    )

    # ClassifyDocument returns classes sorted by confidence descending.
    top_class = response["Classes"][0]
    return top_class["Name"], top_class["Score"]


def extract_aspects(redacted_text: str, classifier_endpoint_arn: str = None) -> list:
    """
    Extract aspect-level sentiment from the redacted feedback text.

    Splits text into sentences, classifies each sentence's aspect, then runs
    sentence-level sentiment analysis on each. The output is a list of
    (aspect, sentiment, confidence, text) tuples that power the dashboards.

    Args:
        redacted_text: PHI-redacted feedback text.
        classifier_endpoint_arn: Optional ARN of trained custom classifier.
            If None, falls back to keyword-based classification.

    Returns:
        List of dicts, each containing:
        - aspect: which aspect this sentence discusses
        - sentiment: sentiment toward that aspect
        - sentiment_scores: full distribution for that sentence
        - confidence: how confident the aspect classification is
        - text: the source sentence (for drill-down in dashboards)
    """
    sentences = split_into_sentences(redacted_text)
    aspect_results = []

    for sentence in sentences:
        # Classify which aspect this sentence is about.
        if classifier_endpoint_arn:
            aspect, aspect_confidence = classify_aspect_with_comprehend(
                sentence, classifier_endpoint_arn
            )
        else:
            # Development fallback: keyword-based classification.
            aspect, aspect_confidence = classify_aspect_keyword_fallback(sentence)

        # Only accept aspect classifications above the confidence threshold.
        # Low-confidence assignments add noise to aggregate dashboards.
        if aspect_confidence < ASPECT_CONFIDENCE_THRESHOLD:
            continue

        # Get sentence-level sentiment for this specific aspect mention.
        # This is a separate Comprehend call per sentence. At scale, this is
        # the most expensive part of the pipeline. Batch APIs can help (see
        # Gap to Production).
        sentence_sentiment = comprehend_client.detect_sentiment(
            Text=sentence,
            LanguageCode="en",
        )

        scores = sentence_sentiment["SentimentScore"]
        aspect_results.append({
            "aspect": aspect,
            "sentiment": sentence_sentiment["Sentiment"],
            "sentiment_scores": {
                "positive": scores["Positive"],
                "negative": scores["Negative"],
                "neutral": scores["Neutral"],
                "mixed": scores["Mixed"],
            },
            "confidence": aspect_confidence,
            "text": sentence,
        })

    logger.info("Extracted %d aspect-sentiment pairs from %d sentences", len(aspect_results), len(sentences))
    return aspect_results
```

---

## Step 4: Result Assembly and Storage

*The pseudocode calls this `store_analysis_result(source_metadata, sentiment, aspects)`. Combines all outputs into a single DynamoDB record and decides whether this feedback needs immediate human attention. The `needs_attention` flag routes urgent items to the patient experience team in near-real-time rather than waiting for monthly reports.*

```python
def determine_needs_attention(document_sentiment: dict, aspects: list) -> bool:
    """
    Decide whether this feedback item needs immediate human review.

    Criteria:
    1. Overall sentiment is NEGATIVE with high confidence (>= 0.85)
    2. OR any critical aspect (pain_management, care_coordination) has
       negative sentiment, regardless of confidence

    The second criterion catches safety-related concerns even when the overall
    document sentiment is mixed. A patient who says "everyone was nice but my
    pain was never addressed" might score MIXED overall, but the pain_management
    aspect being negative is an actionable signal.
    """
    # Check overall sentiment.
    if (
        document_sentiment["sentiment"] == "NEGATIVE"
        and document_sentiment["confidence"] >= ATTENTION_CONFIDENCE_THRESHOLD
    ):
        return True

    # Check critical aspects.
    for aspect_result in aspects:
        if (
            aspect_result["aspect"] in CRITICAL_ASPECTS
            and aspect_result["sentiment"] == "NEGATIVE"
        ):
            return True

    return False


def store_analysis_result(
    source_metadata: dict,
    phi_result: dict,
    sentiment: dict,
    aspects: list,
) -> dict:
    """
    Assemble the complete analysis record and write it to DynamoDB.

    The record links back to the source feedback item and includes the full
    analysis: document-level sentiment, aspect-level sentiments, and processing
    metadata. DynamoDB table design supports queries by date range, department,
    facility, and sentiment for dashboard access patterns.

    Args:
        source_metadata: Dict with feedback_id, channel, department, facility,
                         submitted_date.
        phi_result: Output from detect_and_redact_phi (phi_detected, entity_count).
        sentiment: Output from analyze_sentiment (sentiment, scores, confidence).
        aspects: Output from extract_aspects (list of aspect-sentiment pairs).

    Returns:
        The full record that was written to DynamoDB.
    """
    needs_attention = determine_needs_attention(sentiment, aspects)

    # Assemble the record. DynamoDB requires Decimal for numeric values.
    record = {
        "feedback_id": source_metadata["feedback_id"],
        "source_channel": source_metadata.get("channel", "unknown"),
        "department": source_metadata.get("department", "unknown"),
        "facility": source_metadata.get("facility", "unknown"),
        "analysis_date": datetime.datetime.now(timezone.utc).isoformat(),
        "feedback_date": source_metadata.get("submitted_date", ""),
        "document_sentiment": {
            "sentiment": sentiment["sentiment"],
            "scores": {
                k: Decimal(str(round(v, 4)))
                for k, v in sentiment["scores"].items()
            },
            "confidence": Decimal(str(round(sentiment["confidence"], 4))),
        },
        "aspects": [
            {
                "aspect": a["aspect"],
                "sentiment": a["sentiment"],
                "confidence": Decimal(str(round(a["confidence"], 4))),
                "text": a["text"],
            }
            for a in aspects
        ],
        "phi_detected": phi_result["phi_detected"],
        "needs_attention": needs_attention,
    }

    # Write to DynamoDB.
    results_table = dynamodb.Table(RESULTS_TABLE_NAME)
    results_table.put_item(Item=record)

    # If this needs attention, emit an EventBridge event for alerting.
    if needs_attention:
        # Find the most negative aspect to include in the alert detail.
        negative_aspects = [a for a in aspects if a["sentiment"] == "NEGATIVE"]
        top_negative = negative_aspects[0]["aspect"] if negative_aspects else "overall"

        events_client.put_events(
            Entries=[
                {
                    "Source": "patient-sentiment-pipeline",
                    "DetailType": "NegativeSentimentAlert",
                    "Detail": json.dumps({
                        "feedback_id": source_metadata["feedback_id"],
                        "department": source_metadata.get("department"),
                        "facility": source_metadata.get("facility"),
                        "top_negative_aspect": top_negative,
                        "confidence": sentiment["confidence"],
                    }),
                }
            ]
        )
        logger.info(
            "Alert emitted for feedback_id=%s (aspect: %s)",
            source_metadata["feedback_id"],
            top_negative,
        )

    return record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function with synthetic test data so you can run it end-to-end.

```python
# Synthetic patient feedback for testing.
# These are fabricated examples that demonstrate different sentiment patterns.
# Never use real patient feedback in development environments.
SYNTHETIC_FEEDBACK = [
    {
        "feedback_id": "survey-2026-03-15-00847",
        "channel": "post_visit_survey",
        "department": "internal_medicine",
        "facility": "main_campus",
        "submitted_date": "2026-03-15T14:30:00Z",
        "text": (
            "The doctor was very thorough and explained everything clearly. "
            "But I waited 45 minutes past my appointment time and nobody told me why. "
            "The waiting room was freezing cold. "
            "Then billing sent me a surprise charge three weeks later that nobody mentioned during the visit."
        ),
    },
    {
        "feedback_id": "survey-2026-03-15-00848",
        "channel": "post_visit_survey",
        "department": "orthopedics",
        "facility": "main_campus",
        "submitted_date": "2026-03-15T16:45:00Z",
        "text": (
            "My knee surgery went perfectly and Dr. Martinez was excellent. "
            "The nursing staff checked on me regularly and always responded quickly when I called. "
            "I would absolutely recommend this practice to anyone needing orthopedic care."
        ),
    },
    {
        "feedback_id": "survey-2026-03-16-00102",
        "channel": "complaint_hotline",
        "department": "emergency",
        "facility": "west_campus",
        "submitted_date": "2026-03-16T08:12:00Z",
        "text": (
            "I came in with severe chest pain and waited over an hour before anyone saw me. "
            "When they finally did an EKG, nobody explained the results. "
            "I was terrified and felt completely ignored. "
            "My pain was never adequately addressed during the entire four hour visit."
        ),
    },
]


def analyze_feedback_item(
    feedback_item: dict,
    classifier_endpoint_arn: str = None,
) -> dict:
    """
    Run the complete sentiment analysis pipeline on a single feedback item.

    This implements Steps 1 through 4 in sequence:
    1. PHI detection and redaction
    2. Document-level sentiment analysis
    3. Aspect extraction with per-aspect sentiment
    4. Result assembly, storage, and alerting

    Args:
        feedback_item: Dict with feedback_id, channel, department, facility,
                       submitted_date, and text fields.
        classifier_endpoint_arn: Optional ARN of trained aspect classifier.
            Pass None to use the keyword-based fallback during development.

    Returns:
        The stored analysis record from DynamoDB.
    """
    feedback_text = feedback_item["text"]
    feedback_id = feedback_item["feedback_id"]

    logger.info("Processing feedback_id=%s", feedback_id)

    # Step 1: PHI detection and redaction.
    logger.info("  Step 1: Detecting and redacting PHI...")
    phi_result = detect_and_redact_phi(feedback_text)
    redacted_text = phi_result["redacted_text"]
    logger.info("  PHI entities found: %d", phi_result["entity_count"])

    # Step 2: Document-level sentiment analysis.
    logger.info("  Step 2: Analyzing document-level sentiment...")
    sentiment = analyze_sentiment(redacted_text)
    logger.info(
        "  Sentiment: %s (confidence: %.2f)",
        sentiment["sentiment"],
        sentiment["confidence"],
    )

    # Step 3: Aspect extraction.
    logger.info("  Step 3: Extracting aspects...")
    aspects = extract_aspects(redacted_text, classifier_endpoint_arn)
    logger.info("  Aspects found: %d", len(aspects))

    # Step 4: Store results and alert if needed.
    logger.info("  Step 4: Storing results...")
    source_metadata = {
        "feedback_id": feedback_id,
        "channel": feedback_item.get("channel"),
        "department": feedback_item.get("department"),
        "facility": feedback_item.get("facility"),
        "submitted_date": feedback_item.get("submitted_date"),
    }
    record = store_analysis_result(source_metadata, phi_result, sentiment, aspects)
    logger.info(
        "  Done. needs_attention=%s",
        record["needs_attention"],
    )

    return record


# Run the pipeline against synthetic data.
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    print("=" * 70)
    print("Patient Sentiment Analysis Pipeline")
    print("Running against synthetic feedback data")
    print("=" * 70)

    for item in SYNTHETIC_FEEDBACK:
        print(f"\n{'─' * 70}")
        print(f"Feedback ID: {item['feedback_id']}")
        print(f"Department: {item['department']}")
        print(f"Channel: {item['channel']}")
        print(f"Text: {item['text'][:80]}...")
        print(f"{'─' * 70}")

        result = analyze_feedback_item(item)

        # Display results.
        print(f"\n  Overall Sentiment: {result['document_sentiment']['sentiment']}")
        print(f"  Confidence: {result['document_sentiment']['confidence']}")
        print(f"  Needs Attention: {result['needs_attention']}")
        print(f"  Aspects:")
        for aspect in result["aspects"]:
            print(f"    - {aspect['aspect']}: {aspect['sentiment']} ({aspect['confidence']})")
            print(f"      \"{aspect['text'][:60]}...\"")

    print(f"\n{'=' * 70}")
    print("Pipeline complete.")
```

---

## The Gap Between This and Production

This example works: point it at real Comprehend endpoints with patient feedback text and it will produce structured aspect-level sentiment records. But the distance between "works as a script" and "processes 50,000 feedback items per month at a health system" is significant. Here's where that gap lives.

**The custom classifier.** The keyword-based fallback for aspect detection is a development convenience, not a solution. In production, you need a trained Comprehend custom classifier. The process: (1) Label 200-500 feedback sentences per aspect category, with your patient experience team providing ground truth. (2) Format the labeled data as a CSV with columns `text,label`. (3) Call `CreateDocumentClassifier` to train the model. (4) Deploy with `CreateEndpoint` for real-time inference. Budget 2-4 weeks for the labeling sprint. Refresh labels every 6-12 months as patient language evolves.

**Batch processing.** This example calls DetectSentiment once per sentence. At 50,000 feedback items per month with an average of 4 sentences each, that's 200,000 API calls just for sentence sentiment. Comprehend offers a batch API (`BatchDetectSentiment`) that accepts up to 25 texts per call, cutting your API call volume by 25x. For historical backfills, use Comprehend's async analysis jobs (`StartSentimentDetectionJob`) which process files in S3 directly.

**Error handling.** Every Comprehend call can throttle (ThrottlingException), timeout, or return a service error. A production system wraps each call in try/except with specific handling: retry with backoff on throttling, dead-letter queue for persistent failures, structured error logging that doesn't expose patient text. The DetectPHI call failing is especially critical: if PHI detection fails, the unredacted text must NOT flow to downstream analysis.

**Language detection.** This example assumes English. A health system serving diverse populations will receive feedback in Spanish, Chinese, Vietnamese, and other languages. Add a language detection step (`DetectDominantLanguage`) before sentiment analysis. Non-English text needs either (a) separate language-specific sentiment endpoints or (b) translation via Amazon Translate before analysis. Translation loses nuance, especially for culturally specific expressions of dissatisfaction. Native-language models are better when volume justifies training them.

**PHI redaction failure handling.** If Comprehend Medical's DetectPHI call fails or times out, this code will crash. That's actually the safest behavior: failing open (letting unredacted text through) is worse than failing closed (stopping the pipeline). In production, make this explicit: if PHI detection fails, quarantine the feedback item for manual review rather than passing it unredacted.

**DynamoDB data types.** This example already wraps numeric values in `Decimal(str(value))` for DynamoDB compatibility. If you add any new numeric field (aggregated scores, running averages), remember this requirement. A raw Python float will raise a `TypeError` from boto3 at runtime. The `str()` wrapper avoids floating-point representation artifacts in the Decimal conversion.

**VPC and encryption.** This example makes API calls over the public internet. A production Lambda handling patient feedback (which contains PHI until redacted) runs inside a VPC with private subnets and VPC endpoints for Comprehend, Comprehend Medical, S3, DynamoDB, EventBridge, and CloudWatch Logs. S3 buckets storing raw feedback use SSE-KMS with a customer-managed key. DynamoDB encryption at rest is enabled by default but you should verify it. KMS key rotation should be enabled.

**Sentence splitting.** The naive regex-based sentence splitter will mishandle abbreviations ("Dr. Smith was great" splits on "Dr."), decimal numbers in clinical context, and ellipses. In production, use spaCy's sentence tokenizer or NLTK's Punkt tokenizer, both of which handle these edge cases. Add `spacy` to your Lambda layer or package it as a dependency.

**Deduplication.** Patients sometimes submit the same feedback through multiple channels (portal message AND survey response). Without deduplication, you'll double-count their sentiment in aggregates. Add a content fingerprint (hash of normalized text) and check for duplicates before processing. DynamoDB conditional writes make this straightforward.

**Testing.** There are no tests here. A production pipeline has unit tests for each function with mocked Comprehend responses, integration tests against real Comprehend calls using synthetic data, and validation tests that check sentiment accuracy against a labeled holdout set. Build a fixture library of synthetic feedback items covering each aspect and sentiment combination. Never use real patient feedback in test fixtures.

**Cost management.** At scale, the per-sentence sentiment calls are the biggest cost driver. Consider whether you need sentence-level sentiment for every aspect, or whether document-level sentiment combined with aspect detection (without per-aspect sentiment) is sufficient for your dashboards. The answer depends on how your patient experience team uses the data. Ask them before building.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 8.2: Patient Sentiment Analysis](chapter08.02-patient-sentiment-analysis) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
