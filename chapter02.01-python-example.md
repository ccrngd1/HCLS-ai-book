# Recipe 2.1: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 2.1. It shows one way you could translate those concepts into working Python using boto3 and Amazon Bedrock. It is not production-ready. There's no error handling, no retries beyond the basics, no input validation, and no structured logging. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a clinic on Monday morning. Consider it a starting point, not a destination.

---

## Setup

You'll need the AWS SDK for Python:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:

- `bedrock:InvokeModel` (for the foundation model)
- `bedrock:ApplyGuardrail` (for content safety filtering)
- `s3:GetObject` (for prompt templates)
- `dynamodb:PutItem` and `dynamodb:Query` (for draft storage)

You also need model access enabled in the Bedrock console for your chosen model (this example uses Anthropic Claude 3 Haiku).

---

## Config and Constants

Before the pipeline logic, here's the configuration that drives behavior. Intent patterns, prompt templates, and thresholds all live up top so they're easy to find and tweak.

```python
import json
import logging
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. In production, use JSON-formatted output for
# CloudWatch Logs Insights queries. Never log PHI (patient messages,
# names, medication lists, etc.).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Retry config: adaptive mode uses exponential backoff with jitter.
# Bedrock can throttle under sustained load, especially during peak
# messaging hours (Monday mornings, post-holiday).
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# AWS clients
bedrock_client = boto3.client("bedrock-runtime", config=BOTO3_RETRY_CONFIG)
s3_client = boto3.client("s3", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb", config=BOTO3_RETRY_CONFIG)

# Configuration constants
MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"
# If you get a ValidationException, your region may require a cross-region
# inference profile ID instead (e.g., "us.anthropic.claude-3-haiku-20240307-v1:0").
GUARDRAIL_ID = "your-guardrail-id-here"       # Replace with your Bedrock Guardrail ID
GUARDRAIL_VERSION = "DRAFT"                     # Use "DRAFT" for testing, numbered version for prod
PROMPT_BUCKET = "your-prompt-templates-bucket"  # S3 bucket holding prompt templates
DRAFTS_TABLE = "message-drafts"                 # DynamoDB table for storing generated drafts

# Temperature: lower = more deterministic output. For healthcare communications,
# you want consistency over creativity. 0.3 is a good starting point.
# If drafts feel too repetitive, nudge up to 0.4-0.5. Never go above 0.7
# for patient-facing content.
TEMPERATURE = 0.3
MAX_TOKENS = 300  # Cap response length. Routine messages don't need novels.

# Intent classification patterns.
# Each intent maps to a list of keywords that indicate the patient is asking
# about that topic. Order matters: first match wins. Put more specific intents
# before general ones.
INTENT_PATTERNS = {
    "refill": [
        "refill", "medication", "prescription", "renew", "ran out",
        "running low", "need more", "pills", "pharmacy"
    ],
    "appointment": [
        "appointment", "schedule", "reschedule", "cancel", "when is my",
        "book", "available", "slot", "visit"
    ],
    "test_result": [
        "results", "lab", "blood work", "test", "came back",
        "bloodwork", "a1c", "cholesterol", "panel"
    ],
    "symptom": [
        "pain", "rash", "fever", "feeling", "symptoms", "hurts",
        "swollen", "dizzy", "nausea", "headache", "cough"
    ],
    "billing": [
        "bill", "charge", "insurance", "copay", "payment",
        "cost", "owe", "statement"
    ],
}
```

---

## Step 1: Classify Message Intent

*The pseudocode calls this `classify_message(message_text)`. It determines what the patient is asking about so we know which context to gather and which prompt template to use.*

```python
def classify_message(message_text: str) -> str:
    """
    Classify a patient message into an intent category using keyword matching.

    This is deliberately simple. For routine messages (which are 60-70% of
    portal traffic), keyword matching works surprisingly well. You don't need
    an LLM for this step, and using one would add latency and cost for
    minimal accuracy gain on the easy cases.

    If you find keyword matching isn't cutting it (e.g., too many messages
    landing in "general"), you can upgrade to a lightweight classifier later.
    But start here. Seriously.

    Args:
        message_text: The raw patient message text.

    Returns:
        An intent string: "refill", "appointment", "test_result",
        "symptom", "billing", or "general" (fallback).
    """
    lower_text = message_text.lower()

    for intent, keywords in INTENT_PATTERNS.items():
        for keyword in keywords:
            if keyword in lower_text:
                return intent

    # No keywords matched. This is fine. "General" means the model will
    # work from the message text alone without intent-specific context.
    return "general"
```

---

## Step 2: Gather Patient Context

*The pseudocode calls this `gather_context(patient_id, intent)`. Based on the classified intent, it pulls the specific patient data the model needs to generate a grounded response.*

```python
def gather_context(patient_id: str, intent: str) -> dict:
    """
    Assemble relevant patient context based on message intent.

    This is where you'd call your EHR API or FHIR server. In this example,
    we return mock data to show the shape of what each intent needs.

    In production, this function makes real API calls to your clinical data
    systems. The key principle: pull only what's relevant to the specific
    question. A refill request doesn't need the patient's surgical history.
    An appointment question doesn't need their medication list.

    Why targeted retrieval matters:
    - Less irrelevant context = better model output
    - Fewer tokens = lower cost per message
    - Smaller PHI surface area = better security posture

    Args:
        patient_id: The patient's identifier in your system.
        intent: The classified intent from Step 1.

    Returns:
        A dictionary of context relevant to the patient's question.
    """
    # In production, replace these with real EHR/FHIR API calls.
    # Example: requests.get(f"{FHIR_BASE}/Patient/{patient_id}/MedicationRequest")

    # Always include basic info for personalization
    context = {
        "patient_first_name": "Sarah",       # From patient demographics
        "provider_name": "Dr. Martinez",     # Assigned PCP
    }

    if intent == "refill":
        context["current_medications"] = [
            {"name": "Lisinopril 10mg", "frequency": "daily", "last_filled": "2026-03-15"},
            {"name": "Metformin 500mg", "frequency": "twice daily", "last_filled": "2026-04-01"},
        ]
        context["pharmacy_on_file"] = "CVS #4821, 123 Main St"

    elif intent == "appointment":
        context["upcoming_appointments"] = [
            {"date": "2026-05-15", "time": "10:30 AM", "type": "Follow-up", "provider": "Dr. Martinez"},
        ]
        context["next_available"] = "2026-05-12 at 2:00 PM"

    elif intent == "test_result":
        context["recent_results"] = [
            {"test": "Comprehensive Metabolic Panel", "date": "2026-04-28", "status": "Final"},
            {"test": "HbA1c", "date": "2026-04-28", "status": "Final", "value": "6.2%"},
        ]

    elif intent == "symptom":
        context["recent_visits"] = [
            {"date": "2026-04-10", "reason": "Annual physical", "provider": "Dr. Martinez"},
        ]
        context["active_conditions"] = ["Type 2 Diabetes", "Hypertension"]
        context["current_medications"] = [
            {"name": "Lisinopril 10mg", "frequency": "daily"},
            {"name": "Metformin 500mg", "frequency": "twice daily"},
        ]

    else:
        # General: minimal context
        context["recent_visits"] = [
            {"date": "2026-04-10", "reason": "Annual physical", "provider": "Dr. Martinez"},
        ]

    return context
```

---

## Step 3: Build the Prompt

*The pseudocode calls this `build_prompt(message_text, intent, context, provider_preferences)`. It assembles the system prompt (behavior constraints) and user prompt (context + message) that get sent to the model.*

```python
# Default system prompt. In production, load this from S3 so you can update
# it without redeploying code. Stored here for illustration.
DEFAULT_SYSTEM_PROMPT = """You are a drafting assistant for a healthcare provider. You write response drafts to patient portal messages that the provider will review before sending.

Rules you must follow:
- Never diagnose conditions or suggest new treatments
- Never recommend medications not already in the patient's active medication list
- Never promise specific timelines unless confirmed in the provided context
- Keep responses warm, professional, and concise (under 150 words)
- Address the specific question asked; do not volunteer additional medical information
- If the question requires clinical judgment, write that the provider will follow up personally
- Use the patient's first name in the greeting
- Sign off using the provider's name from the context
- Do not include disclaimers about being an AI or about the response being a draft"""


def load_system_prompt(prompt_key: str = "prompts/system-prompt-v2.txt") -> str:
    """
    Load the system prompt template from S3.

    Storing prompts in S3 (versioned bucket) lets you:
    - Update prompts without code deployments
    - A/B test different prompt versions
    - Maintain an audit trail of prompt changes
    - Roll back quickly if a new prompt degrades quality

    Falls back to the hardcoded default if S3 is unavailable.
    """
    try:
        response = s3_client.get_object(Bucket=PROMPT_BUCKET, Key=prompt_key)
        return response["Body"].read().decode("utf-8")
    except Exception:
        # Fall back to default. In production, log this as a warning.
        # Also: distinguish between "bucket doesn't exist" (configuration bug,
        # should crash) and "transient network issue" (should fall back).
        # Catch botocore.exceptions.ClientError and check the error code.
        logger.warning("Failed to load prompt from S3, using default")
        return DEFAULT_SYSTEM_PROMPT


def build_prompt(message_text: str, intent: str, context: dict) -> tuple[str, str]:
    """
    Assemble the system prompt and user prompt for the model.

    The system prompt defines constraints and tone. The user prompt provides
    the specific context and message for this generation.

    The separation matters: the system prompt is stable across messages
    (same rules every time), while the user prompt changes per message
    (different patient, different question, different context).

    Note: The pseudocode also accepts provider_preferences for tone tuning.
    Omitted here for simplicity; see "Gap to Production" section.

    Args:
        message_text: The patient's original message.
        intent: Classified intent from Step 1.
        context: Patient context from Step 2.

    Returns:
        A tuple of (system_prompt, user_prompt).
    """
    system_prompt = load_system_prompt()

    # Format the context into a readable block for the model.
    # The model needs to see this as structured information it can reference,
    # not as a wall of JSON it has to parse.
    context_lines = []
    for key, value in context.items():
        if isinstance(value, list):
            # Format lists readably
            formatted_items = []
            for item in value:
                if isinstance(item, dict):
                    formatted_items.append(
                        ", ".join(f"{k}: {v}" for k, v in item.items())
                    )
                else:
                    formatted_items.append(str(item))
            context_lines.append(f"- {key}: {'; '.join(formatted_items)}")
        else:
            context_lines.append(f"- {key}: {value}")

    context_block = "\n".join(context_lines)

    user_prompt = (
        f"Message intent: {intent}\n\n"
        f"Patient context:\n{context_block}\n\n"
        f"Patient message:\n\"{message_text}\"\n\n"
        f"Draft a response for the provider to review and send."
    )

    return system_prompt, user_prompt
```

---

## Step 4: Generate the Draft

*The pseudocode calls this `generate_draft(system_prompt, user_prompt)`. It calls Amazon Bedrock with the assembled prompt and applies the configured guardrail for safety filtering.*

```python
def generate_draft(system_prompt: str, user_prompt: str) -> dict:
    """
    Call Amazon Bedrock to generate a draft response.

    This uses the Converse API, which provides a unified interface across
    different model providers (Anthropic, Meta, Amazon, etc.). You can swap
    models by changing MODEL_ID without changing the calling code.

    The guardrail is applied inline: Bedrock checks the generated output
    against your configured content policies before returning it. If the
    output violates a policy (e.g., contains a clinical recommendation),
    the guardrail intervenes and the response indicates what happened.

    Args:
        system_prompt: The behavior constraints and tone guidance.
        user_prompt: The patient context and message.

    Returns:
        A dict with "status" ("success" or "blocked") and either
        "draft_text" or "reason".
    """
    # Build the request using Bedrock's Converse API.
    # Converse is the recommended API for text generation. It handles
    # the model-specific request/response format differences for you.
    response = bedrock_client.converse(
        modelId=MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [{"text": user_prompt}],
            }
        ],
        system=[{"text": system_prompt}],
        inferenceConfig={
            "maxTokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "topP": 0.9,
        },
        guardrailConfig={
            "guardrailIdentifier": GUARDRAIL_ID,
            "guardrailVersion": GUARDRAIL_VERSION,
            "trace": "enabled",  # Include guardrail trace in response for debugging
        },
    )

    # Check the stop reason. If the guardrail intervened, the stop reason
    # will be "guardrail_intervened" rather than "end_turn".
    stop_reason = response["stopReason"]

    if stop_reason == "guardrail_intervened":
        # The safety filter caught something problematic. This message
        # needs manual drafting by the provider.
        # In production, log the guardrail trace to understand what triggered it.
        logger.warning("Guardrail intervened on message generation")
        return {
            "status": "blocked",
            "reason": "Guardrail safety filter intervened. Manual drafting required.",
        }

    # Extract the generated text from the response.
    output_message = response["output"]["message"]
    draft_text = output_message["content"][0]["text"]

    return {
        "status": "success",
        "draft_text": draft_text,
    }
```

---

## Step 5: Store the Draft

*The pseudocode calls this `store_draft(...)`. It writes the generated draft to DynamoDB with all the metadata a provider needs for review, plus generation metadata for auditing and quality monitoring.*

```python
def store_draft(
    message_id: str,
    patient_id: str,
    provider_id: str,
    original_message: str,
    intent: str,
    context_used: dict,
    draft_result: dict,
) -> dict:
    """
    Write the draft record to DynamoDB for provider review.

    The record includes everything the provider needs to make a quick decision:
    the original message, the generated draft, and the context that informed it.
    It also includes generation metadata for auditing and quality monitoring.

    Why store the context_used? Two reasons:
    1. The provider can see what data the model had access to (transparency)
    2. If a draft is wrong, you can debug whether the issue was bad context
       or bad generation (root cause analysis)

    Args:
        message_id: Unique identifier for the patient message.
        patient_id: Patient identifier (for access control and audit).
        provider_id: Provider identifier (routes to their review queue).
        original_message: The patient's raw message text.
        intent: Classified intent.
        context_used: The patient context that was assembled for generation.
        draft_result: Output from generate_draft (status + draft_text or reason).

    Returns:
        The complete record that was written.
    """
    table = dynamodb.Table(DRAFTS_TABLE)

    # Determine draft status based on generation result
    if draft_result["status"] == "blocked":
        draft_text = None
        draft_status = "needs_manual_draft"
    else:
        draft_text = draft_result["draft_text"]
        draft_status = "pending_review"

    record = {
        "message_id": message_id,
        "patient_id": patient_id,
        "provider_id": provider_id,
        "original_message": original_message,
        "classified_intent": intent,
        "context_used": context_used,
        "draft_text": draft_text,
        "draft_status": draft_status,
        "generation_ts": datetime.datetime.now(timezone.utc).isoformat(),
        "model_id": MODEL_ID,
        "prompt_version": "v2",
        "guardrail_id": GUARDRAIL_ID,
        # DynamoDB requires Decimal for numbers, not float.
        "temperature_used": Decimal(str(TEMPERATURE)),
    }

    # Write to DynamoDB. put_item creates or overwrites.
    # In production, add a ConditionExpression to prevent accidental overwrites
    # if the same message_id could be processed twice (idempotency).
    table.put_item(Item=record)

    return record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is what your Lambda handler would call when a new patient message event arrives.

```python
def process_message(message_id: str, patient_id: str, provider_id: str, message_text: str) -> dict:
    """
    Run the full patient message response drafting pipeline.

    This is the main entry point. In a Lambda deployment, your handler
    would parse the EventBridge event, extract the message details, and
    call this function.

    Args:
        message_id: Unique identifier for this message.
        patient_id: The patient who sent the message.
        provider_id: The provider who should review the draft.
        message_text: The raw message text from the patient.

    Returns:
        The stored draft record.
    """
    # Step 1: Figure out what the patient is asking about.
    logger.info("Step 1: Classifying message intent")
    intent = classify_message(message_text)
    logger.info("  Classified as: %s", intent)

    # Step 2: Pull relevant patient data based on the intent.
    logger.info("Step 2: Gathering patient context for intent '%s'", intent)
    context = gather_context(patient_id, intent)
    logger.info("  Context keys: %s", list(context.keys()))

    # Step 3: Assemble the prompt with constraints and context.
    logger.info("Step 3: Building prompt")
    system_prompt, user_prompt = build_prompt(message_text, intent, context)

    # Step 4: Generate the draft via Bedrock.
    logger.info("Step 4: Generating draft via Bedrock (%s)", MODEL_ID)
    draft_result = generate_draft(system_prompt, user_prompt)
    logger.info("  Generation status: %s", draft_result["status"])

    # Step 5: Store the draft for provider review.
    logger.info("Step 5: Storing draft in DynamoDB")
    record = store_draft(
        message_id=message_id,
        patient_id=patient_id,
        provider_id=provider_id,
        original_message=message_text,
        intent=intent,
        context_used=context,
        draft_result=draft_result,
    )

    logger.info("Done. draft_status=%s", record["draft_status"])
    return record


# Example: run the pipeline against a test message.
if __name__ == "__main__":
    result = process_message(
        message_id="msg-2026-05-01-00482",
        patient_id="pat-928471",
        provider_id="dr-martinez-001",
        message_text="Hi, I'm running low on my lisinopril 10mg. Can I get a refill sent to CVS?",
    )

    # Pretty-print the result (convert Decimals to floats for JSON serialization)
    class DecimalEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Decimal):
                return float(obj)
            return super().default(obj)

    print(json.dumps(result, indent=2, cls=DecimalEncoder))
```

---

## The Gap Between This and Production

This example works. Point it at a real Bedrock endpoint with a configured guardrail and it will generate a draft response. But there's a meaningful distance between "works in a script" and "runs at a health system handling 10,000 messages per day." Here's where that gap lives:

**Error handling.** Right now, if Bedrock returns an error (throttling, model unavailable, malformed response), the whole thing crashes. A production system wraps the Bedrock call in try/except with specific handling for `ThrottlingException`, `ModelTimeoutException`, and `ValidationException`. Failed messages go to a dead-letter queue for retry, not into the void.

**Real EHR integration.** The `gather_context` function returns mock data. In production, this makes authenticated API calls to your EHR system (Epic FHIR, Cerner, etc.). That means handling OAuth token refresh, FHIR pagination, network timeouts, and the inevitable "the EHR is down for maintenance at 2 AM on Sunday" scenario. Consider caching recent patient data with a short TTL to reduce EHR load and improve latency.

**Input validation.** This code trusts its inputs completely. A production system validates that message_text isn't empty, isn't absurdly long (token budget), doesn't contain injection attempts in the message body, and that the patient_id and provider_id actually exist in your system.

**Prompt versioning and A/B testing.** The system prompt is loaded from S3, which is good. But production needs versioned prompts with the ability to route a percentage of traffic to a new prompt version, measure approval rates per version, and roll back if a new prompt degrades quality. Store the prompt version in every draft record so you can correlate.

**Provider-specific tone.** This example uses a single system prompt for all providers. In production, each provider has tone preferences stored alongside their profile: greeting style, sign-off, formality level, whether they use first names. Append these to the system prompt per-generation. This is what pushes approval rates from 50% to 70%+.

**Structured logging.** The `logger.info()` calls here are a start, but production needs structured JSON logs with consistent fields: message_id, patient_id (hashed), intent, model_id, latency_ms, token_count, guardrail_action. This is what powers your monitoring dashboard and what your on-call engineer queries at 2 AM.

**Metrics and monitoring.** Emit CloudWatch metrics for: generation latency (p50, p95, p99), guardrail intervention rate, intent distribution, token usage per message, and (once you have the review UI) approval/edit/rejection rates per provider and per intent. The approval rate is your north star metric.

**IAM least-privilege.** The IAM role for this Lambda should have exactly: `bedrock:InvokeModel` scoped to the specific model ARN, `bedrock:ApplyGuardrail` scoped to the specific guardrail ARN, `s3:GetObject` scoped to the prompt bucket, `dynamodb:PutItem` scoped to the drafts table. Not `bedrock:*`. Not `s3:*`.

**VPC and network isolation.** In production, this Lambda runs in a VPC with private subnets. VPC endpoints for Bedrock, S3, and DynamoDB keep all traffic on the AWS backbone. Patient messages contain PHI. They should never traverse the public internet.

**Encryption.** This example relies on default encryption. Production uses KMS customer-managed keys for the DynamoDB table, the S3 prompt bucket, and CloudWatch Logs. Enable key rotation. Log every key usage via CloudTrail.

**Idempotency.** If the same message event fires twice (EventBridge at-least-once delivery), you don't want to generate and store two drafts. Add a `ConditionExpression` on the DynamoDB `put_item` that checks for key non-existence, or use a deduplication layer upstream.

**Rate limiting and cost controls.** A sudden spike in patient messages (post-holiday Monday, system outage recovery) could generate thousands of Bedrock calls in minutes. Set concurrency limits on the Lambda, configure Bedrock provisioned throughput if needed, and set billing alarms. At $0.01-0.03 per message, 10,000 messages/day is $100-300/day. Know your budget.

**Testing.** There are no tests here. A production pipeline has: unit tests for `classify_message` with edge cases, integration tests against Bedrock with known test messages, guardrail validation tests that confirm blocked content is actually blocked, and end-to-end tests with synthetic patient scenarios. Never use real patient messages in test fixtures.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 2.1](chapter02.01-patient-message-response-drafting) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
