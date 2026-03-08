# Recipe 1.3: Python Implementation Example

> **Heads up:** This is a deliberately simple, illustrative implementation of the pseudocode walkthrough from Recipe 1.3. It is meant to show one way you could translate those concepts into working Python code. It is not production-ready. Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to a lab's ordering system on Monday morning. Consider it a starting point, not a destination.
>
> This recipe introduces two AWS clients that work together: a Textract client for document structure extraction (the same async pattern from Recipe 1.2) and a Comprehend Medical client for clinical NLP. Steps 1 and 2 follow the Recipe 1.2 pattern exactly. Steps 3 through 8 are new, and that's where the interesting work happens.

---

## Setup

You'll need the AWS SDK for Python installed:

```bash
pip install boto3
```

Your environment needs credentials configured (via environment variables, an instance profile, or `~/.aws/credentials`). The IAM role or user needs:
- `textract:StartDocumentAnalysis`
- `textract:GetDocumentAnalysis`
- `comprehend:DetectEntitiesV2`
- `comprehend:InferICD10CM`
- `s3:GetObject`
- `s3:PutObject`
- `dynamodb:PutItem`
- `iam:PassRole` (so Lambda can pass the Textract service role for SNS notifications)

Note the Comprehend Medical permissions: `DetectEntitiesV2` and `InferICD10CM` are distinct IAM actions. You need both.

---

## Configuration and Constants

Everything that's really configuration rather than logic lives here, at the top of the module. The CPT lookup table and medical necessity map are the most maintenance-intensive parts of this pipeline. They belong in your version control history, not buried inside a function.

```python
# FIELD_MAP: maps canonical field names to the label variants
# you'll actually see on lab requisition forms.
#
# Lab req templates are not standardized. A large reference lab's standard
# form looks different from a hospital system's internal requisition, which
# looks different again from a specialty practice's custom template.
# This map is what makes the output consistent regardless of layout.
# Treat it as a living document.

FIELD_MAP = {
    "patient_name": [
        "patient name", "patient", "name", "patient full name",
        "last name, first name", "patient last name first"
    ],
    "date_of_birth": [
        "date of birth", "dob", "birth date", "birthdate",
        "patient dob", "date of birth (mm/dd/yyyy)"
    ],
    "member_id": [
        "member id", "mem id", "member #", "subscriber id",
        "id number", "member number", "insurance id", "policy number",
        "insurance member id"
    ],
    "account_number": [
        "account number", "account #", "acct #", "lab account",
        "patient account", "lab account number"
    ],
    "provider_name": [
        "ordering provider", "provider", "physician", "ordering physician",
        "requesting physician", "doctor", "dr.", "referring physician",
        "ordering physician name"
    ],
    "npi": [
        "npi", "npi number", "national provider identifier",
        "physician npi", "provider npi"
    ],
    "practice_name": [
        "practice", "practice name", "clinic", "office",
        "facility", "ordering facility"
    ],
}

# TEST_CPT_MAP: normalized test name -> CPT code.
#
# This covers the most common panels and individual tests.
# It is not exhaustive. Tests that don't match produce cpt_mapped=False
# in the output, which is the signal to expand this table.
# Run a weekly query on your cpt_mapped=False records in production.
# They are your roadmap for what to add here.
#
# Keys are lowercase, whitespace-normalized strings.
# The matching logic lowercases and strips the extracted test name before lookup.

TEST_CPT_MAP = {
    "cbc":                             "85025",    # complete blood count with differential
    "cbc with diff":                   "85025",
    "cbc w/diff":                      "85025",
    "cbc w/ diff":                     "85025",
    "complete blood count":            "85025",
    "complete blood count with diff":  "85025",
    "bmp":                             "80048",    # basic metabolic panel
    "basic metabolic panel":           "80048",
    "cmp":                             "80053",    # comprehensive metabolic panel
    "comprehensive metabolic":         "80053",
    "comprehensive metabolic panel":   "80053",
    "lipid panel":                     "80061",    # lipid panel
    "lipid profile":                   "80061",
    "cholesterol panel":               "80061",
    "tsh":                             "84443",    # thyroid stimulating hormone
    "thyroid stimulating hormone":     "84443",
    "hba1c":                           "83036",    # hemoglobin a1c
    "hemoglobin a1c":                  "83036",
    "glycated hemoglobin":             "83036",
    "a1c":                             "83036",    # common shorthand
    "ua":                              "81003",    # urinalysis
    "urinalysis":                      "81003",
    "psa":                             "84153",    # prostate specific antigen
    "prostate specific antigen":       "84153",
    "vitamin d":                       "82306",    # 25-hydroxyvitamin D
    "25-oh vitamin d":                 "82306",
    "25 oh vitamin d":                 "82306",
    "ferritin":                        "82728",
    "b12":                             "82607",    # vitamin b12
    "vitamin b12":                     "82607",
    "folate":                          "82746",
    "uric acid":                       "84550",
    "crp":                             "86140",    # c-reactive protein
    "c-reactive protein":              "86140",
    "esr":                             "85651",    # erythrocyte sedimentation rate
}

# DIAGNOSIS_LABELS: the label variants we look for when extracting
# the diagnosis / ICD-10 field from the key-value pairs.
# Lab req forms are creative with what they call this field.

DIAGNOSIS_LABELS = {
    "diagnosis", "dx", "icd-10", "icd10", "icd codes",
    "clinical diagnosis", "diagnosis code", "clinical indication",
    "indication", "reason for test", "medical necessity"
}

# NOTES_LABELS: secondary free-text fields that sometimes contain
# additional clinical context useful for ICD-10 inference.

NOTES_LABELS = {
    "notes", "clinical notes", "additional information",
    "comments", "special instructions", "clinical history"
}

# MEDICAL_NECESSITY_MAP: ICD-10 code prefix (first 3 chars) -> list of CPT codes
# that are commonly supported by diagnoses in that category.
#
# This is a simplified approximation of CMS LCD policies.
# It is NOT a substitute for a real medical policy rules engine.
# False positives and false negatives will occur. Use this as a
# pre-screening layer, not a final determination.
# The prefixes correspond to ICD-10-CM chapter groupings.

MEDICAL_NECESSITY_MAP = {
    "E11": ["83036", "80053", "80048", "82306"],  # Type 2 diabetes: HbA1c, CMP, BMP, Vit D
    "E10": ["83036", "80053", "80048"],            # Type 1 diabetes
    "E78": ["80061", "80053"],                     # Hyperlipidemia: lipid panel, CMP
    "I10": ["80053", "80048"],                     # Hypertension: CMP, BMP
    "I25": ["80061", "85025"],                     # Chronic ischemic heart disease
    "N18": ["80053", "80048", "84520"],            # CKD: CMP, BMP, BUN
    "K76": ["80076", "80053"],                     # Liver disease: hepatic function panel
    "D50": ["85025", "82728", "82607"],            # Iron deficiency anemia: CBC, ferritin, B12
    "Z00": ["85025", "80053", "81003", "80061"],   # Routine exam: CBC, CMP, UA, lipid panel
}

# OCR confidence threshold: Textract fields below this go to the flagged list.
CONFIDENCE_THRESHOLD = 90.0

# ICD-10 inference threshold: Comprehend Medical scores below this are flagged
# rather than accepted. Note that this is on a different scale than OCR confidence.
# A Comprehend Medical score of 0.70 on a common diagnosis is typically reliable.
# Raise this if inferences feed directly into a billing system.
# Lower it (cautiously) if you're populating a coder review draft.
ICD10_CONFIDENCE_THRESHOLD = 0.70

# Polling configuration for the development script.
# In production, replace the polling loop with SNS-triggered Lambda invocations.
POLL_INTERVAL_SECONDS = 3
MAX_POLL_ATTEMPTS = 20

# DynamoDB table names. Replace with your actual table names.
JOBS_TABLE_NAME = "textract-jobs"       # tracks in-flight Textract jobs
RESULTS_TABLE_NAME = "lab-orders"       # stores completed lab order records
```

---

## Step 1: Submit the Async Textract Job

*The pseudocode notes that Steps 1 and 2 are identical to Recipe 1.2. They're included here for completeness so this file stands on its own. If you've already worked through Recipe 1.2, this is familiar ground.*

```python
import boto3
import datetime
from datetime import timezone
from decimal import Decimal  # DynamoDB requires Decimal for any numeric value

# Module-level clients. Creating these once at module scope means they're
# reused across invocations inside a warm Lambda container.
textract_client = boto3.client("textract")
comprehend_medical_client = boto3.client("comprehendmedical")
dynamodb = boto3.resource("dynamodb")


def submit_extraction_job(
    bucket: str,
    key: str,
    sns_topic_arn: str,
    textract_role_arn: str,
) -> str:
    """
    Submit a lab requisition PDF from S3 to Textract for async multi-page analysis.

    This is what the first Lambda runs when an S3 upload event fires.
    The call returns immediately with a job ID. The actual extraction
    work happens in the background. Everything else waits for the
    SNS completion notification.

    Args:
        bucket:             S3 bucket where the faxed lab req PDF lives
        key:                S3 object key (path to the PDF)
        sns_topic_arn:      ARN of the SNS topic for job completion notifications
        textract_role_arn:  ARN of the IAM role Textract can assume to publish to SNS
                            (separate from the Lambda execution role; see Prerequisites)

    Returns:
        The Textract job ID. Save this: it's how you retrieve results later.
    """

    # StartDocumentAnalysis handles multi-page PDFs stored in S3.
    # We request both FORMS and TABLES:
    #   FORMS:  gives us labeled key-value pairs AND checkbox selection elements
    #   TABLES: gives us structured grids (test panels listed as tables on some forms)
    # You can't add feature types after job submission, so request both upfront.
    response = textract_client.start_document_analysis(
        DocumentLocation={
            "S3Object": {
                "Bucket": bucket,
                "Name": key,
            }
        },
        FeatureTypes=["FORMS", "TABLES"],
        NotificationChannel={
            # Textract will publish a message here when the job finishes.
            # The message includes the job ID and status (SUCCEEDED or FAILED).
            "SNSTopicArn": sns_topic_arn,
            # Textract needs its own IAM role to publish to SNS.
            # It cannot assume the Lambda execution role.
            # If the second Lambda never fires, check this role first.
            "RoleArn": textract_role_arn,
        },
    )

    job_id = response["JobId"]

    # Record the job context so the second Lambda can look up the source document
    # when the SNS notification arrives. The SNS message contains only the job ID,
    # not the original S3 path.
    jobs_table = dynamodb.Table(JOBS_TABLE_NAME)
    jobs_table.put_item(
        Item={
            "job_id": job_id,
            "bucket": bucket,
            "key": key,
            "submitted_at": datetime.datetime.now(timezone.utc).isoformat(),
            "status": "PENDING",
        }
    )

    print(f"Submitted Textract job {job_id} for s3://{bucket}/{key}")
    return job_id
```

---

## Step 2: Retrieve All Result Pages

*Textract paginates results for multi-page documents. This step collects every block from every result page before any parsing begins. Stopping at the first page gives you a partial document and you won't know it.*

```python
def retrieve_all_blocks(job_id: str) -> tuple[list, dict]:
    """
    Wait for a Textract async job to complete and retrieve all extracted blocks.

    Textract returns results in pages of up to 1,000 blocks each.
    A multi-page lab requisition can produce many blocks across several result pages.
    We collect everything before we start parsing.

    In production, skip the polling loop entirely: call this function only
    after the SNS notification confirms the job succeeded. The parsing logic
    is the same either way.

    Args:
        job_id: The Textract job ID from submit_extraction_job.

    Returns:
        A tuple of (all_blocks, block_map):
        - all_blocks: flat list of every block Textract extracted
        - block_map:  dict of block ID -> block, for O(1) lookups by ID
    """
    import time

    # Poll until the job completes (for development scripts without SNS).
    job_status = "IN_PROGRESS"
    attempts = 0

    while job_status == "IN_PROGRESS" and attempts < MAX_POLL_ATTEMPTS:
        attempts += 1
        status_response = textract_client.get_document_analysis(JobId=job_id)
        job_status = status_response["JobStatus"]

        if job_status == "IN_PROGRESS":
            print(f"  Job {job_id} still running (attempt {attempts}/{MAX_POLL_ATTEMPTS})...")
            time.sleep(POLL_INTERVAL_SECONDS)
        elif job_status == "FAILED":
            raise RuntimeError(
                f"Textract job {job_id} failed. "
                f"StatusMessage: {status_response.get('StatusMessage', 'no message')}"
            )

    if job_status != "SUCCEEDED":
        raise TimeoutError(f"Textract job {job_id} did not complete in time. Last status: {job_status}")

    # Collect all result pages via the pagination cursor.
    all_blocks = []
    next_token = None

    while True:
        params = {"JobId": job_id}
        if next_token is not None:
            params["NextToken"] = next_token

        response = textract_client.get_document_analysis(**params)
        all_blocks.extend(response.get("Blocks", []))

        next_token = response.get("NextToken")
        if next_token is None:
            break

    print(f"  Retrieved {len(all_blocks)} total blocks")

    # Build a lookup index. Parsing depends heavily on following cross-references
    # between blocks by ID. O(1) dict lookup beats scanning the flat list.
    block_map = {block["Id"]: block for block in all_blocks}

    return all_blocks, block_map
```

---

## Step 3: Parse Structured Fields and Ordered Tests

*The pseudocode calls this `parse_forms_and_checkboxes(all_blocks, block_map)`. This step handles both the patient and provider key-value fields and the test checkbox grid. For every checked test, we attempt an immediate CPT lookup before moving on.*

```python
def get_text_from_block(block: dict, block_map: dict) -> str:
    """
    Helper: assemble the full text of a block by following its CHILD WORD blocks.

    Textract stores actual text in a hierarchy. A KEY or VALUE block does not
    directly contain text: it has CHILD relationships pointing to individual
    WORD blocks. We follow those links and concatenate the words.

    This helper is reused across Steps 3 and 4 wherever we need to read
    text out of a Textract block.
    """
    text = ""

    if "Relationships" not in block:
        return text

    for relationship in block["Relationships"]:
        if relationship["Type"] == "CHILD":
            for child_id in relationship["Ids"]:
                child_block = block_map.get(child_id, {})
                # Only WORD blocks contain text. SELECTION_ELEMENT blocks
                # (checkboxes) are handled separately below.
                if child_block.get("BlockType") == "WORD":
                    text += child_block.get("Text", "") + " "

    return text.strip()


def parse_forms_and_checkboxes(
    all_blocks: list,
    block_map: dict,
) -> tuple[dict, list]:
    """
    Extract key-value text fields and checkbox test selections from the form.

    For text fields (patient demographics, provider info), we build a raw
    label-to-value map for normalization in the next step.

    For checkboxes (the ordered test grid), we immediately attempt a CPT
    code lookup on each selected test. Tests that don't match the lookup
    table are flagged with cpt_mapped=False rather than silently discarded.

    Args:
        all_blocks: flat block list from retrieve_all_blocks
        block_map:  block ID lookup dict from retrieve_all_blocks

    Returns:
        A tuple of (text_key_values, ordered_tests):
        - text_key_values: raw label -> {"value": str, "confidence": float}
        - ordered_tests:   list of {"test_name": str, "cpt_code": str|None, "cpt_mapped": bool}
    """
    text_key_values = {}
    ordered_tests = []

    for block in all_blocks:

        if block.get("BlockType") != "KEY_VALUE_SET":
            continue

        entity_types = block.get("EntityTypes", [])
        if "KEY" not in entity_types:
            continue   # skip VALUE blocks; we'll reach them via the KEY

        key_text = get_text_from_block(block, block_map)
        if not key_text:
            continue

        # Follow the VALUE relationship to find the paired VALUE block.
        value_block = None
        for relationship in block.get("Relationships", []):
            if relationship["Type"] == "VALUE":
                value_id = relationship["Ids"][0]
                value_block = block_map.get(value_id)
                break

        if value_block is None:
            continue

        # Determine whether this is a checkbox or a text field.
        # A checkbox VALUE block has a SELECTION_ELEMENT child.
        # A text VALUE block has WORD children.
        selection_child = None
        for relationship in value_block.get("Relationships", []):
            if relationship["Type"] == "CHILD":
                for child_id in relationship["Ids"]:
                    child_block = block_map.get(child_id, {})
                    if child_block.get("BlockType") == "SELECTION_ELEMENT":
                        selection_child = child_block
                        break
            if selection_child:
                break

        if selection_child is not None:
            # This is a checkbox. Only add it to ordered_tests if it's selected.
            is_selected = selection_child.get("SelectionStatus") == "SELECTED"

            if is_selected:
                # Normalize the label before CPT lookup: lowercase, strip whitespace.
                normalized_name = key_text.lower().strip()
                cpt_code = TEST_CPT_MAP.get(normalized_name)

                ordered_tests.append({
                    "test_name": key_text.strip(),   # original label as it appears on the form
                    "cpt_code": cpt_code,            # None if not in our lookup table
                    "cpt_mapped": cpt_code is not None,  # flag unmapped tests explicitly
                })

        else:
            # Regular text field: store for normalization in the next step.
            value_text = get_text_from_block(value_block, block_map)
            key_confidence = block.get("Confidence", 0.0)
            value_confidence = value_block.get("Confidence", 0.0)
            confidence = min(key_confidence, value_confidence)

            text_key_values[key_text] = {
                "value": value_text,
                "confidence": confidence,
            }

    print(f"  Found {len(text_key_values)} text fields, {len(ordered_tests)} selected tests")
    return text_key_values, ordered_tests
```

---

## Step 4: Extract Diagnosis Text

*The pseudocode calls this `extract_clinical_text(text_key_values)`. Lab requisitions have a diagnosis field, but it's filled with free text: formal diagnosis names, ICD-10 codes written by hand, abbreviations, or some mix of all three. This step locates that field and prepares the text for Comprehend Medical.*

```python
def extract_clinical_text(text_key_values: dict) -> tuple[str | None, str | None, str]:
    """
    Find and extract the diagnosis and clinical notes fields from the form.

    The diagnosis field is the bridge between structural extraction and
    clinical NLP. Its label varies across form templates (see DIAGNOSIS_LABELS),
    and its content varies even more: "T2DM, HTN" and "Type 2 diabetes mellitus
    with hyperglycemia, essential hypertension" are both valid entries that
    a physician might write for the same patient.

    We also extract any clinical notes field, which sometimes contains context
    that improves ICD-10 inference quality.

    Args:
        text_key_values: raw label -> {"value": str, "confidence": float}
                         from parse_forms_and_checkboxes

    Returns:
        A tuple of (diagnosis_text, notes_text, combined_text):
        - diagnosis_text: raw text from the diagnosis field (None if not found)
        - notes_text:     raw text from the clinical notes field (None if not found)
        - combined_text:  diagnosis + notes joined for Comprehend Medical input,
                          clipped to stay within the 10,000-character InferICD10CM API limit
    """
    diagnosis_text = None
    notes_text = None

    for raw_label, data in text_key_values.items():
        normalized_label = raw_label.lower().strip()

        if normalized_label in DIAGNOSIS_LABELS:
            # Take the last match if there are multiple diagnosis-type fields.
            # Some forms have separate "Primary Dx" and "Secondary Dx" fields.
            # Joining them here is a simplification; see the Gap to Production section.
            if diagnosis_text:
                diagnosis_text = diagnosis_text + ". " + data["value"].strip()
            else:
                diagnosis_text = data["value"].strip()

        elif normalized_label in NOTES_LABELS:
            notes_text = data["value"].strip()

    # Combine for Comprehend Medical. The character limit for InferICD10CM
    # InferICD10CM accepts 10,000 characters and DetectEntitiesV2 accepts 20,000 characters per request. We clip well
    # below that to leave margin and avoid silent truncation.
    parts = [p for p in [diagnosis_text, notes_text] if p]
    combined = ". ".join(parts)

    if len(combined) > 9800:
        # Clip at a safe limit. In production, split at sentence boundaries
        # and process in chunks rather than truncating. Medical content you
        # silently drop is worse than content you process in two API calls.
        combined = combined[:9800]

    return diagnosis_text, notes_text, combined
```

---

## Step 5: Infer ICD-10 Codes with Comprehend Medical

*The pseudocode calls this `infer_icd10_codes(diagnosis_text)`. This is where the raw diagnosis text becomes actual ICD-10-CM codes. Comprehend Medical's `InferICD10CM` API is specifically trained for this mapping problem.*

```python
def infer_icd10_codes(diagnosis_text: str | None) -> tuple[list, list]:
    """
    Use Comprehend Medical to map diagnosis free text to ICD-10-CM codes.

    InferICD10CM is a specialized inference model: it was trained on clinical
    text with the explicit goal of mapping clinical language to the ICD-10-CM
    hierarchy. It returns a ranked list of code candidates for each entity it
    detects in the input text.

    We split the results at ICD10_CONFIDENCE_THRESHOLD. Codes above the
    threshold go into the accepted list and are used downstream. Codes below
    it go into the flagged list for human review: we preserve the top candidate
    so a reviewer can confirm or replace it, but we don't propagate it
    automatically.

    Args:
        diagnosis_text: raw text from the diagnosis field, or None if not found

    Returns:
        A tuple of (accepted, flagged):
        - accepted: list of dicts with evidence_text, icd10_code, description, confidence
        - flagged:  list of dicts with evidence_text and the top candidate (for review)
    """
    if not diagnosis_text:
        # No diagnosis text on this form. Unusual but not impossible:
        # some labs accept verbal orders or have the diagnosis come through
        # a separate system. Return empty lists; the caller handles the absence.
        return [], []

    # Call Comprehend Medical's ICD-10-CM inference API.
    # The response contains an Entities list. Each entity represents a clinical
    # concept detected in the input text, with a ranked list of ICD-10-CM
    # code candidates sorted by confidence (highest first).
    response = comprehend_medical_client.infer_icd10_cm(Text=diagnosis_text)

    accepted = []   # codes we trust enough to use directly
    flagged = []    # codes below threshold, preserved for human review

    for entity in response.get("Entities", []):

        # entity["Text"] is the exact text span that triggered this entity.
        # For example: "Type 2 diabetes" or "hypertension" or "T2DM".
        evidence_text = entity.get("Text", "")

        # ICD10CMConcepts is the ranked list of candidate codes for this entity.
        # Index 0 is always the highest-confidence candidate.
        concepts = entity.get("ICD10CMConcepts", [])
        if not concepts:
            # Comprehend Medical detected a clinical entity but couldn't map
            # it to any ICD-10-CM code. This happens for very rare diagnoses
            # or unusual abbreviations. Log this in production for review.
            continue

        top_concept = concepts[0]
        score = top_concept.get("Score", 0.0)

        if score >= ICD10_CONFIDENCE_THRESHOLD:
            accepted.append({
                "evidence_text": evidence_text,
                "icd10_code":    top_concept["Code"],          # e.g., "E11.9"
                "description":   top_concept["Description"],   # e.g., "Type 2 diabetes mellitus without complications"
                "confidence":    Decimal(str(round(score, 3))),
            })
        else:
            # Below threshold. Preserve the top candidate so a reviewer
            # knows what the model guessed, but don't use it automatically.
            flagged.append({
                "evidence_text": evidence_text,
                "top_candidate": {
                    "icd10_code":  top_concept["Code"],
                    "description": top_concept["Description"],
                    "confidence":  Decimal(str(round(score, 3))),
                },
            })

    print(f"  ICD-10 inference: {len(accepted)} accepted, {len(flagged)} flagged")
    return accepted, flagged
```

---

## Step 6: Extract Clinical Entities

*The pseudocode calls this `detect_clinical_entities(text)`. While `InferICD10CM` focuses on diagnosis-to-code mapping, `DetectEntitiesV2` gives us a broader view of everything clinically relevant in the free text: medications, procedures, provider names, and importantly, the semantic traits that modify how each entity should be interpreted.*

```python
def detect_clinical_entities(text: str | None) -> dict:
    """
    Extract clinical entities from the combined diagnosis and notes text.

    DetectEntitiesV2 covers six categories:
      MEDICAL_CONDITION     - diagnoses, symptoms, signs
      MEDICATION            - drug names, dosages, frequencies
      TEST_TREATMENT_PROCEDURE - lab tests, procedures, treatments
      ANATOMY               - body parts, locations
      PROTECTED_HEALTH_INFORMATION - dates, names, IDs (relevant for audit)
      TIME_EXPRESSION       - temporal references

    The semantic traits are the part worth paying attention to.
    An entity with a NEGATION trait means the patient does NOT have
    that condition: "no chest pain" and "chest pain" both produce a
    MEDICAL_CONDITION entity, but only the latter should influence coding.
    PERTAINS_TO_FAMILY means a family member has the condition, not the patient.
    PAST_HISTORY means historical, not current.

    Args:
        text: combined diagnosis and notes text (or None if nothing was found)

    Returns:
        A dict of category -> list of entity records.
        Empty dict if text is None or empty.
    """
    if not text:
        return {}

    # DetectEntitiesV2 is the current version of the entity detection API.
    # Use V2, not the original DetectEntities: V2 returns additional entity types
    # and has improved accuracy on clinical abbreviations.
    response = comprehend_medical_client.detect_entities_v2(Text=text)

    entities_by_category = {}

    for entity in response.get("Entities", []):
        category = entity.get("Category", "UNKNOWN")

        entity_record = {
            "text":       entity.get("Text", ""),          # the original text span
            "type":       entity.get("Type", ""),          # more specific than Category
            "confidence": round(entity.get("Score", 0.0), 3),

            # Filter traits to those with high enough confidence to trust.
            # Trait confidence is separate from entity confidence.
            # A well-detected entity can have uncertain trait attribution.
            "traits": [
                t["Name"]
                for t in entity.get("Traits", [])
                if t.get("Score", 0.0) >= 0.75
            ],
        }

        if category not in entities_by_category:
            entities_by_category[category] = []
        entities_by_category[category].append(entity_record)

    # Log how much we found. Useful for debugging forms where the
    # diagnosis field was blank or Textract misread the field label.
    total = sum(len(v) for v in entities_by_category.values())
    print(f"  Detected {total} clinical entities across {len(entities_by_category)} categories")

    return entities_by_category
```

---

## Step 7: Medical Necessity Check

*The pseudocode calls this `check_medical_necessity(icd10_codes, ordered_tests)`. With CPT codes and ICD-10 codes both in hand, we can run a basic cross-reference before the order goes anywhere downstream. The goal is catching obvious gaps early, not replacing utilization management.*

```python
def check_medical_necessity(icd10_codes: list, ordered_tests: list) -> list:
    """
    Cross-reference ordered tests against accepted ICD-10 diagnosis codes.

    For each ordered test with a CPT code, we check whether any of the
    accepted diagnosis codes support it, using the ICD-10 code prefix
    (first three characters) as the matching key.

    Tests that don't have a supporting diagnosis code are flagged.
    This is not an error: it may mean the physician has a clinically valid
    reason that our simplified mapping table doesn't cover. The flag is a
    signal for review, not a rejection.

    Args:
        icd10_codes:   accepted ICD-10 codes from infer_icd10_codes
        ordered_tests: list from parse_forms_and_checkboxes

    Returns:
        A list of dicts describing tests with no supporting diagnosis code.
        Empty list means all mapped tests had supporting diagnoses (good).
    """
    # Build the set of CPT codes supported by any of the accepted diagnoses.
    supported_cpts = set()

    for diagnosis in icd10_codes:
        # Match on the first three characters of the ICD-10 code.
        # E11.9 -> "E11", I10 -> "I10", etc.
        code_prefix = diagnosis["icd10_code"][:3]
        cpts_for_prefix = MEDICAL_NECESSITY_MAP.get(code_prefix, [])
        supported_cpts.update(cpts_for_prefix)

    # Check each ordered test against the supported CPT set.
    flags = []

    for test in ordered_tests:
        if test["cpt_code"] is None:
            # We couldn't map this test to a CPT code, so we can't check
            # necessity for it either. The cpt_mapped=False flag already
            # marks it for review.
            continue

        if test["cpt_code"] not in supported_cpts:
            flags.append({
                "test_name": test["test_name"],
                "cpt_code":  test["cpt_code"],
                "note": "No supporting diagnosis found in extracted codes. Review for medical necessity.",
            })

    if flags:
        print(f"  Medical necessity: {len(flags)} test(s) flagged for review")
    else:
        print("  Medical necessity: all mapped tests have supporting diagnoses")

    return flags
```

---

## Step 8: Normalize Fields, Apply Confidence Gating, Assemble, and Store

*The pseudocode breaks these into separate concerns. In Python, the normalization and gating are simple enough to handle inline before assembling the final record.*

```python
def normalize_fields(text_key_values: dict) -> tuple[dict, dict, list]:
    """
    Map raw Textract labels to canonical field names and gate by confidence.

    Patient and provider fields are normalized against FIELD_MAP. Fields above
    CONFIDENCE_THRESHOLD go into the clean output maps. Fields below it go
    into the flagged list for human review.

    Args:
        text_key_values: raw label -> {"value": str, "confidence": float}

    Returns:
        A tuple of (patient_fields, provider_fields, flagged_text_fields):
        - patient_fields:  canonical_name -> value string (high-confidence)
        - provider_fields: canonical_name -> value string (high-confidence)
        - flagged_text_fields: list of dicts for fields needing human review
    """
    # Patient and provider field sets for organizing the output.
    PATIENT_FIELDS = {"patient_name", "date_of_birth", "member_id", "account_number"}
    PROVIDER_FIELDS = {"provider_name", "npi", "practice_name"}

    normalized = {}
    flagged_text_fields = []

    for canonical_name, variants in FIELD_MAP.items():
        for raw_label, data in text_key_values.items():
            if raw_label.lower().strip() in variants:

                if data["confidence"] >= CONFIDENCE_THRESHOLD:
                    normalized[canonical_name] = data["value"].strip()
                else:
                    # Confidence too low: hold for review.
                    # Decimal wrapping is required because DynamoDB does not
                    # accept Python floats in put_item calls.
                    flagged_text_fields.append({
                        "field":           canonical_name,
                        "extracted_value": data["value"].strip(),
                        "confidence":      Decimal(str(round(data["confidence"], 2))),
                    })
                break

    # Split into patient and provider maps for the structured output record.
    patient_fields = {k: v for k, v in normalized.items() if k in PATIENT_FIELDS}
    provider_fields = {k: v for k, v in normalized.items() if k in PROVIDER_FIELDS}

    return patient_fields, provider_fields, flagged_text_fields


def assemble_and_store(
    document_key: str,
    patient_fields: dict,
    provider_fields: dict,
    ordered_tests: list,
    icd10_accepted: list,
    icd10_flagged: list,
    clinical_entities: dict,
    necessity_flags: list,
    text_flagged: list,
) -> dict:
    """
    Assemble the structured lab order record and write it to DynamoDB.

    Every confidence score from both Textract and Comprehend Medical travels
    with the record. The needs_review flag is set if any field was flagged
    by either system. The two types of flags are stored separately because
    they require different reviewer actions: a flagged OCR field needs someone
    to read the original form, while a flagged ICD-10 inference needs a coder.

    Args:
        document_key:      S3 key of the source PDF (for audit linkage)
        patient_fields:    high-confidence patient demographic fields
        provider_fields:   high-confidence provider identification fields
        ordered_tests:     CPT-mapped test list from parse_forms_and_checkboxes
        icd10_accepted:    high-confidence ICD-10 inferences from infer_icd10_codes
        icd10_flagged:     low-confidence ICD-10 inferences, held for coder review
        clinical_entities: entity map from detect_clinical_entities
        necessity_flags:   tests without supporting diagnoses from check_medical_necessity
        text_flagged:      low-confidence OCR fields from normalize_fields

    Returns:
        The full record that was written to DynamoDB.
    """
    results_table = dynamodb.Table(RESULTS_TABLE_NAME)

    # A record needs human review if any of three conditions hold:
    # (1) any Textract field was below the OCR confidence threshold
    # (2) any ICD-10 inference was below the NLP confidence threshold
    # (3) any ordered test lacked a supporting diagnosis code
    needs_review = (
        len(text_flagged) > 0
        or len(icd10_flagged) > 0
        or len(necessity_flags) > 0
    )

    # Convert ICD-10 confidence scores to Decimal for DynamoDB.
    # Every float-valued field in the record needs this treatment.
    # A plain Python float in a put_item call raises TypeError at runtime.
    def to_decimal(value: float) -> Decimal:
        return Decimal(str(round(value, 3)))

    accepted_with_decimal = [
        {**d, "confidence": to_decimal(d["confidence"])}
        for d in icd10_accepted
    ]

    entities_with_decimal = {
        category: [
            {**e, "confidence": to_decimal(e["confidence"])}
            for e in entity_list
        ]
        for category, entity_list in clinical_entities.items()
    }

    # Convert ordered_tests: no floats here, but keep the structure clean.
    # Replace None cpt_code with an explicit marker for DynamoDB (it doesn't
    # store Python None in a Map; use a string placeholder instead).
    tests_for_db = [
        {
            "test_name":  t["test_name"],
            "cpt_code":   t["cpt_code"] if t["cpt_code"] is not None else "UNMAPPED",
            "cpt_mapped": t["cpt_mapped"],
        }
        for t in ordered_tests
    ]

    record = {
        "document_key":  document_key,
        "extracted_at":  datetime.datetime.now(timezone.utc).isoformat(),
        "needs_review":  needs_review,

        "patient": {
            "name":           patient_fields.get("patient_name"),
            "date_of_birth":  patient_fields.get("date_of_birth"),
            "member_id":      patient_fields.get("member_id"),
            "account_number": patient_fields.get("account_number"),
        },

        "ordering_provider": {
            "name":     provider_fields.get("provider_name"),
            "npi":      provider_fields.get("npi"),
            "practice": provider_fields.get("practice_name"),
        },

        # The ordered tests, with CPT codes where we could map them.
        "ordered_tests": tests_for_db,

        "diagnoses": {
            # High-confidence ICD-10 inferences: safe to use downstream.
            "accepted": accepted_with_decimal,
            # Low-confidence inferences: preserved for coder review.
            # These are distinct from the text_flagged list: a coder reviews these,
            # not a general data entry reviewer.
            "flagged": icd10_flagged,
        },

        # Entity map from DetectEntitiesV2. Useful for downstream enrichment
        # and for auditing why the NLP produced the ICD-10 codes it did.
        "clinical_entities": entities_with_decimal,

        # Tests without supporting diagnosis codes. Empty list is the happy path.
        "medical_necessity_flags": necessity_flags,

        # Low-confidence Textract fields: the original extracted value is preserved
        # so a reviewer can confirm or correct it.
        "flagged_fields": text_flagged,
    }

    results_table.put_item(Item=record)

    return record
```

---

## Putting It All Together

Here's the full pipeline assembled into a single function. This is the polling-based version for development scripts. Lambda handler versions follow below.

```python
def process_lab_requisition(
    bucket: str,
    key: str,
    sns_topic_arn: str,
    textract_role_arn: str,
) -> dict:
    """
    Run the full lab requisition extraction pipeline for one faxed PDF.

    Covers all eight steps from the Recipe 1.3 pseudocode:
      1. Submit the async Textract job
      2. Retrieve all result pages
      3. Parse structured fields and ordered tests (with CPT lookup)
      4. Extract diagnosis text
      5. Infer ICD-10 codes with Comprehend Medical
      6. Extract clinical entities with Comprehend Medical
      7. Check medical necessity
      8. Normalize, assemble, and store

    In a production two-Lambda deployment, Steps 1 and 2-8 live in separate
    Lambda functions triggered by S3 events and SNS notifications.
    The parsing logic is the same either way.

    Args:
        bucket:             S3 bucket containing the lab requisition PDF
        key:                S3 object key (path to the PDF)
        sns_topic_arn:      SNS topic ARN for Textract completion notifications
        textract_role_arn:  IAM role ARN Textract can assume to publish to SNS

    Returns:
        The stored lab order record from DynamoDB.
    """

    # Step 1: Submit the async Textract job and record the context.
    print(f"Step 1: Submitting Textract job for s3://{bucket}/{key}")
    job_id = submit_extraction_job(bucket, key, sns_topic_arn, textract_role_arn)
    print(f"  Job ID: {job_id}")

    # Step 2: Wait for completion and collect all extracted blocks.
    # In production, the second Lambda is triggered by SNS instead of this loop.
    print("Step 2: Waiting for job completion and retrieving all blocks...")
    all_blocks, block_map = retrieve_all_blocks(job_id)

    # Step 3: Parse text fields and checkboxes. Checked tests get CPT lookup.
    print("Step 3: Parsing forms and checkboxes...")
    text_key_values, ordered_tests = parse_forms_and_checkboxes(all_blocks, block_map)

    # Step 4: Locate the diagnosis field and extract the clinical text for NLP.
    print("Step 4: Extracting diagnosis and clinical notes text...")
    diagnosis_text, notes_text, combined_text = extract_clinical_text(text_key_values)
    if diagnosis_text:
        print(f"  Diagnosis field extracted, length={len(diagnosis_text)}")
    else:
        print("  No diagnosis field found on this form")

    # Step 5: Map diagnosis text to ICD-10-CM codes via Comprehend Medical.
    print("Step 5: Running ICD-10 inference with Comprehend Medical...")
    icd10_accepted, icd10_flagged = infer_icd10_codes(diagnosis_text)

    # Step 6: Extract broader clinical entities from combined text.
    # DetectEntitiesV2 catches medications, procedures, and semantic traits
    # (negations, family history, etc.) that InferICD10CM doesn't surface.
    print("Step 6: Detecting clinical entities with Comprehend Medical...")
    clinical_entities = detect_clinical_entities(combined_text)

    # Step 7: Cross-reference ordered tests against accepted diagnoses.
    # Flag tests with no supporting diagnosis code for review.
    print("Step 7: Checking medical necessity...")
    necessity_flags = check_medical_necessity(icd10_accepted, ordered_tests)

    # Step 8: Normalize field names, gate by confidence, assemble, and store.
    print("Step 8: Normalizing fields and storing record...")
    patient_fields, provider_fields, text_flagged = normalize_fields(text_key_values)

    result = assemble_and_store(
        document_key=key,
        patient_fields=patient_fields,
        provider_fields=provider_fields,
        ordered_tests=ordered_tests,
        icd10_accepted=icd10_accepted,
        icd10_flagged=icd10_flagged,
        clinical_entities=clinical_entities,
        necessity_flags=necessity_flags,
        text_flagged=text_flagged,
    )

    flagged_total = (
        len(result["flagged_fields"])
        + len(result["diagnoses"]["flagged"])
        + len(result["medical_necessity_flags"])
    )
    print(f"Done. needs_review={result['needs_review']}, total flags={flagged_total}")
    return result


# Example: run the pipeline directly against a test lab requisition PDF.
if __name__ == "__main__":
    import json

    result = process_lab_requisition(
        bucket="my-lab-reqs",
        key="lab-reqs/2026/03/05/fax-00184.pdf",
        sns_topic_arn="arn:aws:sns:us-east-1:123456789012:textract-jobs",
        textract_role_arn="arn:aws:iam::123456789012:role/TextractServiceRole",
    )

    # DynamoDB Decimal objects are not JSON-serializable by default.
    # This encoder converts them to float for display purposes only.
    class DecimalEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Decimal):
                return float(obj)
            return super().default(obj)

    print(json.dumps(result, indent=2, cls=DecimalEncoder))
```

---

## Lambda Handler Versions

In a production deployment, the two-Lambda architecture from the recipe looks like this. The parsing logic is unchanged; only the entry points differ.

```python
import json
import os


def lambda_handler_start(event: dict, context) -> None:
    """
    Lambda 1 (lab-req-start): triggered by S3 upload events.

    Its one job: submit the Textract analysis job and record the context.
    Everything else happens in the second Lambda after Textract finishes.
    """
    record = event["Records"][0]
    bucket = record["s3"]["bucket"]["name"]
    key    = record["s3"]["object"]["key"]

    # ARNs come from Lambda environment variables.
    # Never hardcode ARNs in function code.
    sns_topic_arn     = os.environ["TEXTRACT_SNS_TOPIC_ARN"]
    textract_role_arn = os.environ["TEXTRACT_ROLE_ARN"]

    job_id = submit_extraction_job(bucket, key, sns_topic_arn, textract_role_arn)
    print(f"Submitted job {job_id} for s3://{bucket}/{key}")


def lambda_handler_process(event: dict, context) -> None:
    """
    Lambda 2 (lab-req-process): triggered by SNS notifications from Textract.

    Receives the job completion signal, runs Steps 2 through 8, and stores
    the structured lab order record. In production, if the record needs_review,
    forward the document_key to your SQS review queue for Recipe 1.6.
    """
    # The SNS message is JSON-encoded inside the "Message" field of the SNS envelope.
    sns_message = json.loads(event["Records"][0]["Sns"]["Message"])
    job_id     = sns_message["JobId"]
    job_status = sns_message["Status"]   # "SUCCEEDED" or "FAILED"

    if job_status != "SUCCEEDED":
        # A FAILED status means Textract couldn't process the document.
        # Log it and move on. In production, move the source PDF to a
        # failed-documents/ prefix and fire a CloudWatch alarm.
        print(f"Job {job_id} finished with status {job_status}. Skipping processing.")
        return

    # Look up the original document path from the jobs tracking table.
    jobs_table = dynamodb.Table(JOBS_TABLE_NAME)
    response = jobs_table.get_item(Key={"job_id": job_id})
    job_item = response.get("Item", {})

    bucket = job_item.get("bucket")
    key    = job_item.get("key")

    if not bucket or not key:
        print(f"No job context found for job_id={job_id}. Cannot process.")
        return

    print(f"Processing completed job {job_id} for s3://{bucket}/{key}")

    # Steps 2 through 8: retrieve, parse, analyze, and store.
    all_blocks, block_map = retrieve_all_blocks(job_id)

    text_key_values, ordered_tests = parse_forms_and_checkboxes(all_blocks, block_map)

    diagnosis_text, notes_text, combined_text = extract_clinical_text(text_key_values)

    icd10_accepted, icd10_flagged = infer_icd10_codes(diagnosis_text)

    clinical_entities = detect_clinical_entities(combined_text)

    necessity_flags = check_medical_necessity(icd10_accepted, ordered_tests)

    patient_fields, provider_fields, text_flagged = normalize_fields(text_key_values)

    result = assemble_and_store(
        document_key=key,
        patient_fields=patient_fields,
        provider_fields=provider_fields,
        ordered_tests=ordered_tests,
        icd10_accepted=icd10_accepted,
        icd10_flagged=icd10_flagged,
        clinical_entities=clinical_entities,
        necessity_flags=necessity_flags,
        text_flagged=text_flagged,
    )

    print(f"Stored record for {key}. needs_review={result['needs_review']}")

    # Production next step: forward flagged records to the review queue.
    # if result["needs_review"]:
    #     sqs_client.send_message(
    #         QueueUrl=os.environ["REVIEW_QUEUE_URL"],
    #         MessageBody=json.dumps({"document_key": key, "job_id": job_id}),
    #     )
```

---

## The Gap Between This and Production

This example works: run it against a real lab requisition PDF and it will produce a structured JSON record with patient fields, ordered tests with CPT codes, ICD-10 diagnosis codes, clinical entities, and medical necessity flags. The distance between that and a production deployment is real. Here's where it lives.

**Comprehend Medical character limits per request.** `InferICD10CM` accepts up to 10,000 UTF-8 characters per request and `DetectEntitiesV2` accepts up to 20,000. The clipping in `extract_clinical_text` keeps the example safe, but silently truncating a diagnosis field is worse than processing it correctly in two chunks. A production implementation splits at sentence or clause boundaries, processes each chunk, and deduplicates entities by text span and code. Build this before you go live, even if most forms stay well under the limit. The one that doesn't will be the one containing the code you care most about.

**Composite confidence scoring.** This example evaluates OCR confidence and NLP confidence independently. They should be combined: an ICD-10 code inferred from text with 72% OCR confidence is less reliable than the same NLP score applied to text read at 98% confidence. A production system propagates the Textract confidence of the source text through to the ICD-10 inference and uses the composite (minimum) score for gating. Right now, a borderline OCR read can produce a high-confidence-looking ICD-10 code.

**ICD-10 code specificity.** `InferICD10CM` defaults to the least-specific valid code: E11.9 ("without complications") when the clinical text might support E11.65 ("with hyperglycemia"). This is conservative and usually correct, but some payer LCD policies require the more specific code to support a lab order. A production system captures the full ranked candidate list (not just `concepts[0]`), compares it against payer-specific specificity requirements, and routes low-specificity results to coder review when the downstream policy demands it. The example code stops at the top candidate.

**The medical necessity table is a rough approximation.** MEDICAL_NECESSITY_MAP covers the most common cases with a simplified prefix-based match. Real CMS LCDs run to pages of individual ICD-10 codes per covered test, and commercial payer policies diverge from Medicare in unpredictable ways. This table will produce both false positives (flagging tests that are actually justified) and false negatives (missing tests that should be flagged). Use it as a pre-screening layer before utilization management, not as the final word. And audit your false-positive rate during the first weeks of production: if the flags are mostly noise, you'll exhaust your reviewers and they'll stop looking.

**Dead Letter Queues for both Lambdas.** Both Lambdas receive asynchronous invocations. Configure SQS DLQs on both, with CloudWatch alarms on queue depth. A lab order that silently disappears because the processing Lambda failed is a patient care gap, not just a processing metric.

**CPT code table staleness.** The AMA updates CPT codes every January. Tests renumbered or added after your last table update will produce `cpt_mapped: false` silently, and you won't know they're missing unless you're querying for them. Build a weekly report on `cpt_mapped=false` records in production. Use that list to drive table updates. The unmapped test names are your maintenance backlog.

**Textract job failure handling.** The Lambda handler above checks `job_status` and skips processing on failure. That's the right check, but "skip and log" is not enough for production. Move the source PDF to a `failed-documents/` S3 prefix, update the job record in DynamoDB to status `FAILED`, and fire a CloudWatch alarm. Lab requisitions that fail silently are orders the lab may never receive.

**DynamoDB Decimal requirement.** Every numeric value in the record uses `Decimal(str(value))` wrapping. This example already does it: `to_decimal()` handles the ICD-10 confidence scores, and the flagged fields use `Decimal` directly. Any new numeric field you add later must get the same treatment. A raw Python float in a `put_item` call raises `TypeError` at runtime with a message that's less helpful than it should be.

**Multiple diagnosis fields on the same form.** Some lab requisition templates have separate "Primary Diagnosis" and "Secondary Diagnosis" fields. `extract_clinical_text` concatenates them with a period separator, which works reasonably well for most Comprehend Medical inputs. A production implementation detects multiple diagnosis fields, processes them in a single combined string, and maps each accepted ICD-10 code back to the specific field it came from. The provenance matters when a reviewer is deciding whether the code is primary or secondary.

**Negation and family history traits.** `detect_clinical_entities` captures traits like NEGATION and PERTAINS_TO_FAMILY in the entity record. But nothing in the pipeline currently uses those traits to filter or reclassify the ICD-10 inferences from Step 5. In production, if `InferICD10CM` returns a condition that `DetectEntitiesV2` flags with a NEGATION trait (meaning the text said "no diabetes"), that's a signal to route the diagnosis code to human review rather than accepting it automatically. Wiring these two steps together is real work, but it catches a meaningful class of errors.

**VPC and encryption.** This example makes API calls without VPC configuration. A production Lambda handling lab requisitions runs inside a VPC with private subnets and VPC endpoints for S3, Textract, DynamoDB, SNS, and Comprehend Medical. Lab requisitions contain diagnoses, ordered tests, and provider identification: they are PHI-bearing clinical documents. S3 SSE-KMS with a customer-managed key. DynamoDB encryption at rest. All calls over TLS. Add a VPC endpoint for CloudWatch Logs or your Lambda will have no log output inside a private subnet.

**Testing.** There are no tests here. A production pipeline has unit tests for each parsing function with mocked Textract and Comprehend Medical responses, integration tests against real API calls with synthetic lab requisitions, and a fixture library covering the form templates you actually receive. CMS publishes sample ICD-10-CM data. Quest Diagnostics and LabCorp publish provider requisition templates. Use those to build test fixtures. Never use real patient forms in any non-production environment.

---

*Part of the Healthcare AI/ML Cookbook. See [Recipe 1.3: Lab Requisition Form Extraction](chapter01.03-lab-requisition-extraction) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard.*
