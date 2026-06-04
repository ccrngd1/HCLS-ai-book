# Recipe 8.3: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 8.3. It shows one way you could translate those concepts into working Python using boto3. It is not production-ready. Think of it as the sketchpad version: useful for understanding how the pieces fit together, not something you'd wire into a CDI workflow on Monday morning. Consider it a starting point, not a destination.
>
> The main recipe describes a Lambda-backed API Gateway architecture. This example implements the same logic as a callable function you can run locally against the Comprehend Medical API. The extraction, filtering, and coding rule logic is identical to what you'd deploy in Lambda. The difference is operational plumbing, not core logic.

---

## Setup

You'll need the AWS SDK for Python:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `comprehend:InferICD10CM`
- `dynamodb:PutItem`
- `dynamodb:GetItem`
- `dynamodb:Query`

No BAA-covered data in development. Use synthetic clinical notes only. The MIMIC-III dataset on PhysioNet provides de-identified clinical text if you need realistic content for testing.

---

## Configuration and Constants

These live at the top of the module. Thresholds, rules, and table names are configuration, not logic. You'll tune these as your coders provide feedback on suggestion quality.

```python
import logging
import json
import datetime
from datetime import timezone
from decimal import Decimal

import boto3
from botocore.config import Config

# Structured logging. Never log PHI (patient names, MRNs, note text).
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Adaptive retry handles Comprehend Medical throttling gracefully.
BOTO3_RETRY_CONFIG = Config(retries={"max_attempts": 3, "mode": "adaptive"})

# boto3 clients at module level for Lambda container reuse.
comprehend_medical = boto3.client("comprehendmedical", config=BOTO3_RETRY_CONFIG)
dynamodb = boto3.resource("dynamodb")

# --- Thresholds ---

# Minimum confidence score to include a code suggestion.
# Low on purpose: we want recall. The coder filters from here.
# If suggestions feel too noisy, raise this to 0.40-0.50.
CONFIDENCE_THRESHOLD = 0.30

# Maximum suggestions to return. Top N by confidence.
MAX_SUGGESTIONS = 15

# Comprehend Medical's per-request character limit.
MAX_TEXT_LENGTH = 20_000

# --- DynamoDB Tables ---

# Stores suggestion results for audit and feedback collection.
SUGGESTIONS_TABLE = "icd10-suggestions"

# Stores coding rules: specificity overrides, combination codes, excludes pairs.
RULES_TABLE = "icd10-coding-rules"

# --- Section Priority ---
# Clinical note sections most relevant for diagnosis coding.
# Assessment/Plan is where physicians state diagnostic conclusions.
# HPI describes the current episode. These drive coding decisions.
PRIORITY_SECTIONS = [
    "assessment and plan",
    "assessment",
    "impression",
    "discharge diagnosis",
    "hospital course",
    "hpi",
    "history of present illness",
]
```

---

## Step 1: Preprocess the Clinical Note

*Maps to the pseudocode's `preprocess_note(raw_note_text)`. Clinical notes have structure: sections with headers. Not all sections are equally useful for coding. Assessment and Plan drives most diagnosis codes. Review of Systems and Past Medical History add noise that dilutes suggestion accuracy. This step segments the note and prioritizes the sections that matter.*

```python
def preprocess_note(raw_note_text: str) -> str:
    """
    Segment a clinical note by section headers and reorder so that
    high-value sections (Assessment/Plan, HPI) appear first.

    Clinical notes typically use ALL CAPS or title-cased lines followed
    by colons as section headers. The exact format varies by EHR vendor
    and documentation template. This parser handles the common patterns.

    Args:
        raw_note_text: Full clinical note text as received from the EHR.

    Returns:
        Reordered note text, truncated to Comprehend Medical's limit.
        Priority sections appear first so they're never lost to truncation.
    """
    # Split on lines that look like section headers.
    # Common patterns: "ASSESSMENT AND PLAN:", "Assessment and Plan:", "A/P:"
    # This is intentionally simple. Production systems use regex or
    # EHR-specific section parsers (many EHRs expose structured sections via FHIR).
    lines = raw_note_text.split("\n")
    sections = {}
    current_section = "preamble"
    current_content = []

    for line in lines:
        stripped = line.strip()
        # Heuristic: a line that's mostly uppercase, ends with colon, or
        # is a known section name is treated as a header.
        if stripped.endswith(":") and len(stripped) < 60 and stripped.upper() == stripped:
            # Save previous section
            if current_content:
                sections[current_section] = "\n".join(current_content)
            current_section = stripped.rstrip(":").lower()
            current_content = []
        else:
            current_content.append(line)

    # Don't forget the last section
    if current_content:
        sections[current_section] = "\n".join(current_content)

    # Build output: priority sections first, then everything else.
    priority_text = []
    remaining_text = []

    for section_name in PRIORITY_SECTIONS:
        if section_name in sections:
            priority_text.append(sections[section_name])

    for section_name, content in sections.items():
        if section_name not in PRIORITY_SECTIONS:
            remaining_text.append(content)

    combined = "\n\n".join(priority_text + remaining_text)

    # Truncate to API limit. Priority content is safe because it's first.
    if len(combined) > MAX_TEXT_LENGTH:
        combined = combined[:MAX_TEXT_LENGTH]
        logger.info("Note truncated from %d to %d characters", len(raw_note_text), MAX_TEXT_LENGTH)

    return combined
```

---

## Step 2: Call Comprehend Medical InferICD10CM

*Maps to the pseudocode's `get_icd10_suggestions(clinical_text)`. This is the core extraction call. InferICD10CM takes clinical text and returns medical condition entities, each with ranked ICD-10-CM code candidates and confidence scores. It handles negation detection, contextual inference, and multi-entity extraction in a single API call. One call does the work of an entire NLP pipeline: entity detection, assertion classification, and code mapping.*

```python
def get_icd10_suggestions(clinical_text: str) -> list:
    """
    Call Amazon Comprehend Medical's InferICD10CM API.

    The API returns a list of medical condition entities found in the text.
    Each entity includes:
      - Text: the span that triggered detection ("Type 2 diabetes")
      - Category: always MEDICAL_CONDITION for this API
      - Traits: list of attributes (NEGATION, DIAGNOSIS, SIGN, SYMPTOM, etc.)
      - ICD10CMConcepts: ranked list of code suggestions with confidence scores

    The API handles negation internally. "Patient denies chest pain" will still
    return an entity for "chest pain" but it will have the NEGATION trait, which
    we filter on in Step 3.

    Args:
        clinical_text: Preprocessed note text (output of preprocess_note).

    Returns:
        List of entity dicts from the API response.
    """
    response = comprehend_medical.infer_icd10_cm(Text=clinical_text)

    # Response structure:
    # {
    #   "Entities": [
    #     {
    #       "Id": 0,
    #       "Text": "Type 2 diabetes",
    #       "Category": "MEDICAL_CONDITION",
    #       "Type": "DX_NAME",
    #       "Score": 0.95,
    #       "BeginOffset": 142,
    #       "EndOffset": 158,
    #       "Traits": [{"Name": "DIAGNOSIS", "Score": 0.93}],
    #       "ICD10CMConcepts": [
    #         {"Code": "E11.9", "Description": "Type 2 diabetes mellitus without complications", "Score": 0.82},
    #         {"Code": "E11.65", "Description": "Type 2 diabetes mellitus with hyperglycemia", "Score": 0.71},
    #         ...
    #       ]
    #     },
    #     ...
    #   ]
    # }

    entities = response.get("Entities", [])
    logger.info("InferICD10CM returned %d entities", len(entities))
    return entities
```

---

## Step 3: Filter and Score Suggestions

*Maps to the pseudocode's `filter_and_score(entities)`. Not every entity should become a suggestion. Negated conditions (documented as absent), hypothetical mentions, and family history references need to be excluded or handled separately. This step applies clinical logic to transform raw API output into a clean suggestion list.*

```python
def filter_and_score(entities: list) -> list:
    """
    Filter Comprehend Medical entities and build a ranked suggestion list.

    Filtering logic:
      - Exclude entities with NEGATION trait (documented as absent)
      - Exclude entities below the confidence threshold
      - Deduplicate codes (keep highest confidence instance)
      - Sort by confidence descending

    Args:
        entities: Raw entity list from get_icd10_suggestions.

    Returns:
        List of suggestion dicts, each with:
          code, description, score, source_text, traits
    """
    suggestions = []

    for entity in entities:
        # Check traits for negation. Comprehend Medical tags negated conditions
        # (like "denies chest pain") with a NEGATION trait. These should not
        # generate code suggestions for the negated condition.
        trait_names = [t["Name"] for t in entity.get("Traits", [])]

        if "NEGATION" in trait_names:
            logger.debug("Skipping negated entity: %s", entity.get("Text", ""))
            continue

        # Process each ICD-10 code candidate for this entity.
        # A single entity like "diabetes with kidney disease" might map to
        # multiple codes: E11.22 (combination), E11.9 (general), N18.9 (CKD alone).
        for concept in entity.get("ICD10CMConcepts", []):
            score = concept.get("Score", 0.0)

            if score < CONFIDENCE_THRESHOLD:
                continue

            suggestions.append({
                "code": concept["Code"],
                "description": concept["Description"],
                "score": score,
                "source_text": entity.get("Text", ""),
                "traits": trait_names,
            })

    # Deduplicate: same code can appear from multiple text spans.
    # Keep the instance with the highest confidence score.
    seen_codes = {}
    for s in suggestions:
        code = s["code"]
        if code not in seen_codes or s["score"] > seen_codes[code]["score"]:
            seen_codes[code] = s

    deduped = sorted(seen_codes.values(), key=lambda x: x["score"], reverse=True)
    logger.info("Filtered to %d unique code suggestions", len(deduped))
    return deduped
```

---

## Step 4: Apply Coding Rules and Specificity Logic

*Maps to the pseudocode's `apply_coding_rules(suggestions, rules_table)`. Raw ML output doesn't understand ICD-10 coding guidelines. This step enforces specificity (suppress unspecified codes when a more specific code is present), checks for combination code opportunities, and flags excludes conflicts for human review. In production, these rules are maintained by your coding compliance team in DynamoDB. Here we use a static dictionary for illustration.*

```python
# Static coding rules for demonstration. In production, load these from DynamoDB
# so your compliance team can update them without code deployments.
SPECIFICITY_RULES = {
    # If a more specific code from this family is present, suppress the general one.
    # Format: general_code -> list of codes that supersede it.
    "E11.9": ["E11.65", "E11.22", "E11.21", "E11.311", "E11.319", "E11.40", "E11.41"],
    "I10": ["I11.0", "I11.9", "I12.0", "I12.9", "I13.0", "I13.10"],
    "N18.9": ["N18.1", "N18.2", "N18.3", "N18.4", "N18.5", "N18.6"],
}

COMBINATION_CODES = [
    # When both component conditions are documented, suggest the combination code.
    # Format: (condition_a_pattern, condition_b_pattern, combined_code, description)
    (
        "E11",   # diabetes type 2 (any specificity)
        "N18",   # chronic kidney disease (any specificity)
        "E11.22",
        "Type 2 diabetes mellitus with diabetic chronic kidney disease",
    ),
    (
        "I11",   # hypertensive heart disease
        "N18",   # chronic kidney disease
        "I13.10",
        "Hypertensive heart and chronic kidney disease without heart failure, with CKD stage 1-4",
    ),
]


def apply_coding_rules(suggestions: list) -> list:
    """
    Apply ICD-10 coding guidelines to the suggestion list.

    This enforces three types of rules:
      1. Specificity: suppress general codes when specific alternatives are present
      2. Combination codes: suggest combined codes when component conditions coexist
      3. Excludes flags: mark code pairs that can't coexist (for human review)

    Args:
        suggestions: Deduplicated, sorted suggestion list from filter_and_score.

    Returns:
        Refined suggestion list with suppressed codes removed and flags added.
    """
    active_codes = {s["code"] for s in suggestions}

    # --- Specificity suppression ---
    suppressed = set()
    for general_code, specific_codes in SPECIFICITY_RULES.items():
        if general_code in active_codes:
            # Check if any more specific sibling is also present
            for specific in specific_codes:
                if specific in active_codes:
                    suppressed.add(general_code)
                    logger.info(
                        "Suppressing %s (less specific than %s)", general_code, specific
                    )
                    break

    # --- Combination codes ---
    combo_additions = []
    for pattern_a, pattern_b, combo_code, combo_desc in COMBINATION_CODES:
        has_a = any(c.startswith(pattern_a) for c in active_codes)
        has_b = any(c.startswith(pattern_b) for c in active_codes)

        if has_a and has_b and combo_code not in active_codes:
            combo_additions.append({
                "code": combo_code,
                "description": combo_desc,
                "score": 0.75,  # synthetic confidence for rule-derived suggestions
                "source_text": "(combination code: coding guideline)",
                "traits": ["DIAGNOSIS"],
                "flags": ["combination_code"],
            })
            logger.info("Added combination code %s", combo_code)

    # Build final list: remove suppressed, add combos, preserve order.
    filtered = [s for s in suggestions if s["code"] not in suppressed]

    # Add flags field to existing suggestions if not present
    for s in filtered:
        if "flags" not in s:
            s["flags"] = []

    filtered.extend(combo_additions)

    # Re-sort by score and trim to max
    filtered.sort(key=lambda x: x["score"], reverse=True)
    return filtered[:MAX_SUGGESTIONS]
```

---

## Step 5: Store Results and Build Response

*Maps to the pseudocode's `store_and_respond(encounter_id, suggestions, original_note_length)`. The final step persists suggestions for audit trail and feedback collection, then returns the ranked list to the caller. Every suggestion includes its source text so the coder can see exactly what triggered it. DynamoDB requires Decimal for numbers (not float), which is why we wrap scores here.*

```python
def store_and_respond(encounter_id: str, suggestions: list, note_char_count: int) -> dict:
    """
    Persist suggestion results to DynamoDB and build the API response.

    Storing results serves three purposes:
      1. Audit trail: HIPAA requires you can show what the system suggested
      2. Feedback loop: coders accept/reject codes, creating training labels
      3. Analytics: track suggestion accuracy over time by encounter type

    Args:
        encounter_id: Unique identifier for the clinical encounter.
        suggestions: Final ranked suggestion list from apply_coding_rules.
        note_char_count: Character count of the original (pre-processed) note.

    Returns:
        Response dict matching the API Gateway response format.
    """
    timestamp = datetime.datetime.now(timezone.utc).isoformat()

    response_payload = {
        "encounter_id": encounter_id,
        "timestamp": timestamp,
        "note_char_count": note_char_count,
        "suggestion_count": len(suggestions),
        "suggestions": suggestions,
    }

    # Write to DynamoDB. Scores must be Decimal, not float.
    # boto3 raises TypeError on plain Python floats in DynamoDB items.
    table = dynamodb.Table(SUGGESTIONS_TABLE)

    dynamo_item = {
        "encounter_id": encounter_id,
        "timestamp": timestamp,
        "note_char_count": note_char_count,
        "suggestion_count": len(suggestions),
        "suggestions": json.loads(
            json.dumps(suggestions), parse_float=Decimal
        ),
        # TTL: retain for 90 days for feedback collection, then auto-expire.
        "ttl": int(
            (datetime.datetime.now(timezone.utc) + datetime.timedelta(days=90)).timestamp()
        ),
    }

    table.put_item(Item=dynamo_item)
    logger.info(
        "Stored %d suggestions for encounter %s", len(suggestions), encounter_id
    )

    return response_payload
```

---

## Full Pipeline: Putting It All Together

This assembles all steps into a single callable function. In a Lambda deployment, this is your handler's core logic. The Lambda receives the encounter ID and note text from API Gateway, runs the pipeline, and returns the suggestion JSON.

```python
def suggest_icd10_codes(encounter_id: str, clinical_note: str) -> dict:
    """
    End-to-end ICD-10 code suggestion pipeline.

    Takes a raw clinical note and returns ranked ICD-10-CM code suggestions.
    This is what your Lambda handler calls after extracting parameters from
    the API Gateway event.

    Args:
        encounter_id: Unique encounter identifier (from the EHR system).
        clinical_note: Raw clinical note text.

    Returns:
        Dict with encounter metadata and ranked code suggestions.
    """
    print(f"[1/5] Preprocessing note for encounter {encounter_id}...")
    print(f"       Original length: {len(clinical_note)} characters")
    processed_text = preprocess_note(clinical_note)
    print(f"       Processed length: {len(processed_text)} characters")

    print(f"[2/5] Calling Comprehend Medical InferICD10CM...")
    entities = get_icd10_suggestions(processed_text)
    print(f"       Received {len(entities)} entities")

    print(f"[3/5] Filtering and scoring suggestions...")
    suggestions = filter_and_score(entities)
    print(f"       {len(suggestions)} candidates after filtering")

    print(f"[4/5] Applying coding rules...")
    refined = apply_coding_rules(suggestions)
    print(f"       {len(refined)} suggestions after rules")

    print(f"[5/5] Storing results...")
    result = store_and_respond(encounter_id, refined, len(clinical_note))
    print(f"       Done. {result['suggestion_count']} suggestions returned.")

    return result


# --- Example usage with synthetic data ---

if __name__ == "__main__":
    # Synthetic clinical note. This is NOT real patient data.
    # It demonstrates the kind of text the system processes:
    # an endocrinology follow-up with multiple active conditions.
    SAMPLE_NOTE = """
CHIEF COMPLAINT:
Follow-up for diabetes management.

HISTORY OF PRESENT ILLNESS:
62-year-old male with Type 2 diabetes, hypertension, and chronic kidney disease
presenting for routine follow-up. Patient reports increased thirst and urination
over the past 2 weeks. Denies chest pain, shortness of breath, or visual changes.
No hypoglycemic episodes. Adherent to metformin and lisinopril.

REVIEW OF SYSTEMS:
Constitutional: No fever, no weight loss.
Cardiovascular: No chest pain, no palpitations.
Respiratory: No shortness of breath, no cough.
Endocrine: Increased thirst and polyuria as noted.

PHYSICAL EXAM:
Vitals: BP 138/82, HR 76, BMI 31.2
General: Well-appearing, no acute distress.
Extremities: No edema. Monofilament testing intact bilaterally.

LABS:
A1C: 9.2% (up from 7.8% three months ago)
eGFR: 42 mL/min (stable, CKD stage 3b)
Creatinine: 1.8 mg/dL
Microalbumin/creatinine ratio: 180 mg/g (elevated)

ASSESSMENT AND PLAN:
1. Type 2 diabetes with hyperglycemia - A1C significantly above goal.
   Increase metformin to 1000mg BID. Add empagliflozin 10mg daily
   (renal benefit plus glycemic control). Recheck A1C in 3 months.
2. CKD stage 3b, likely diabetic nephropathy given albuminuria.
   Continue ACE inhibitor. Empagliflozin provides additional renal
   protection. Nephrology referral if eGFR declines further.
3. Hypertension - borderline at today's visit. Continue lisinopril 20mg.
   Goal BP <130/80 given CKD and diabetes.
4. Obesity - BMI 31.2. Discussed dietary modifications. Empagliflozin
   may provide modest weight benefit.

Patient to return in 3 months. Sooner if symptoms worsen.
"""

    result = suggest_icd10_codes(
        encounter_id="ENC-DEMO-20260315",
        clinical_note=SAMPLE_NOTE,
    )

    print("\n" + "=" * 60)
    print("SUGGESTION RESULTS")
    print("=" * 60)
    print(json.dumps(result, indent=2, default=str))
```

---

## Expected Output

Running the example above against Comprehend Medical produces output like this (actual scores vary slightly per API call):

```json
{
  "encounter_id": "ENC-DEMO-20260315",
  "timestamp": "2026-03-15T14:22:08.441Z",
  "note_char_count": 1642,
  "suggestion_count": 7,
  "suggestions": [
    {
      "code": "E11.65",
      "description": "Type 2 diabetes mellitus with hyperglycemia",
      "score": 0.92,
      "source_text": "Type 2 diabetes with hyperglycemia",
      "traits": ["DIAGNOSIS"],
      "flags": []
    },
    {
      "code": "E11.22",
      "description": "Type 2 diabetes mellitus with diabetic chronic kidney disease",
      "score": 0.87,
      "source_text": "diabetic nephropathy",
      "traits": ["DIAGNOSIS"],
      "flags": ["combination_code"]
    },
    {
      "code": "N18.3",
      "description": "Chronic kidney disease, stage 3 (moderate)",
      "score": 0.84,
      "source_text": "CKD stage 3b",
      "traits": ["DIAGNOSIS"],
      "flags": []
    },
    {
      "code": "I10",
      "description": "Essential (primary) hypertension",
      "score": 0.78,
      "source_text": "Hypertension",
      "traits": ["DIAGNOSIS"],
      "flags": []
    },
    {
      "code": "E66.9",
      "description": "Obesity, unspecified",
      "score": 0.62,
      "source_text": "Obesity",
      "traits": ["DIAGNOSIS"],
      "flags": []
    },
    {
      "code": "R35.1",
      "description": "Nocturnal polyuria",
      "score": 0.45,
      "source_text": "polyuria",
      "traits": ["SIGN"],
      "flags": []
    },
    {
      "code": "Z79.84",
      "description": "Long term (current) use of oral hypoglycemic drugs",
      "score": 0.41,
      "source_text": "metformin",
      "traits": ["DIAGNOSIS"],
      "flags": []
    }
  ]
}
```

Notice what the system did well: it caught the hyperglycemia specificity (E11.65 instead of the generic E11.9), identified the combination diabetes-CKD code (E11.22), correctly excluded chest pain and shortness of breath (those were negated in the note), and picked up the hypertension. A human coder would review this list and likely accept 5 of the 7, reject or modify 1-2, and potentially add a code the system missed.

---

## The Gap Between This and Production

This example works: point it at a clinical note and it returns ranked ICD-10 suggestions. But the distance between "works in a notebook" and "coders trust it in their workflow" is where the real engineering lives.

**Real-time latency requirements.** Comprehend Medical InferICD10CM typically responds in 1-3 seconds for notes under 5,000 characters. Longer notes (10,000+ characters) can take 3-5 seconds. If your CDI workflow needs sub-second response, you'll need to either truncate more aggressively or cache results for notes that haven't changed since the last suggestion run. Lambda cold starts add 1-2 seconds on the first invocation; provisioned concurrency eliminates this.

**Error handling.** Every API call here can fail. Comprehend Medical throttles at sustained high volume (default is 10 TPS for InferICD10CM; request an increase for production). The DynamoDB write can fail if the table doesn't exist or the item exceeds 400KB. A production system wraps each call in try/except with specific handling: retry on throttling, dead-letter queue for persistent failures, structured error logging that doesn't include PHI from the note text.

**Section parsing robustness.** The section segmentation in Step 1 uses a simple heuristic (all-caps lines ending in colons). Real clinical notes are messier: some EHRs use bold formatting markers, some use numbered headers, some have no consistent section structure at all. A production implementation either uses the EHR's structured section data (available via FHIR DocumentReference resources in modern systems) or a more sophisticated section classifier trained on your specific note templates.

**The coding rules table.** This example uses a hardcoded dictionary for specificity and combination rules. Production systems load these from DynamoDB so your coding compliance team can update them without deploying code. The ICD-10 guidelines update annually (October 1st each fiscal year). New codes are added, old codes are retired, and combination rules change. Your rules table needs a versioning mechanism and an effective-date field.

**Feedback loop infrastructure.** The stored suggestions have a TTL of 90 days. During that window, your CDI application should record which codes the coder accepted, rejected, or modified. That feedback is gold: it becomes labeled training data for a custom SageMaker model. Without the feedback loop, accuracy stays static at whatever Comprehend Medical provides out of the box. With it, you can fine-tune a model that learns your organization's documentation patterns, specialty-specific conventions, and individual provider tendencies.

**Negation edge cases.** Comprehend Medical handles most negation patterns well ("denies", "no evidence of", "without"). It's less reliable with implicit negation ("patient's diabetes is well-controlled" does not mean diabetes is absent, but "resolved pneumonia" should use a different code than "active pneumonia"). A production system adds a post-processing layer that checks for resolution language, "history of" patterns, and conditional statements that the API may not handle perfectly.

**VPC and network isolation.** This example makes API calls over the public internet. A production Lambda handling PHI runs inside a VPC with private subnets. You'll need VPC endpoints for Comprehend Medical (`com.amazonaws.{region}.comprehendmedical`), DynamoDB (`com.amazonaws.{region}.dynamodb`), and CloudWatch Logs. Without VPC endpoints, Lambda in a private subnet can't reach these services.

**DynamoDB Decimal requirement.** This example already handles the Decimal conversion (see Step 5's `json.loads(..., parse_float=Decimal)` pattern). If you add numeric fields to the DynamoDB item later, remember: raw Python floats will throw `TypeError` at write time. Always serialize through the `parse_float=Decimal` trick or wrap explicitly.

**Cost at scale.** Comprehend Medical InferICD10CM costs approximately $0.01 per 100 characters. A 2,500-character note costs about $0.025. At 10,000 encounters per day, that's $250/day in API costs alone. If cost is a concern, consider batching suggestions (run once when the note is signed rather than on every edit), caching results for unchanged notes, or training a custom model on SageMaker that you host at a fixed monthly cost regardless of volume.

**Testing without real PHI.** Never use real patient notes in development or test environments. Synthetic notes (like the example above) cover the common patterns. For systematic testing, generate a corpus of synthetic notes covering different specialties, documentation styles, and code distributions. The MIMIC-III dataset provides de-identified text for research purposes (requires PhysioNet credentialing). Your test suite should include notes with heavy negation, sparse documentation, and rare conditions to exercise edge cases.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 8.3: ICD-10 Code Suggestion](chapter08.03-icd-10-code-suggestion) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
