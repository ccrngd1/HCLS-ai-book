# Recipe 8.5: Problem List Extraction

**Complexity:** Medium · **Phase:** Integration · **Estimated Cost:** ~$0.30-0.80 per note

---

## The Problem

Every patient in your EHR has a problem list. In theory, it's the authoritative summary of active diagnoses and conditions: the single place a clinician can glance to understand what's going on with this patient. In practice, problem lists are one of the most poorly maintained data assets in healthcare.

Here's what actually happens. A patient with diabetes, hypertension, chronic kidney disease, depression, and a resolved pneumonia from last year shows up for an annual visit. The problem list in the EHR might say "HTN" (added by the PCP three years ago), "Type 2 DM" (added during a hospitalization), and nothing else. The CKD was diagnosed six months ago but the nephrologist documented it in a consult note and never updated the problem list. The depression is mentioned in every progress note but nobody added it formally. The pneumonia is still listed as active because nobody marked it resolved.

This is not a rare scenario. Studies consistently show that EHR problem lists are incomplete, with sensitivity for known diagnoses ranging from 40-70% depending on the condition and setting. Chronic conditions are under-represented. Resolved conditions linger. New diagnoses get documented in notes but never propagated to the structured list.

The downstream impact is real. Clinical decision support fires (or doesn't fire) based on the problem list. Quality measures get reported against it. Risk adjustment coding depends on it. Care coordination tools use it to identify patients who need outreach. When the problem list is wrong, all of those downstream systems produce wrong results, silently.

The information exists. It's in progress notes, discharge summaries, consult notes, procedure notes. Clinicians document diagnoses in narrative text all the time. The gap is extracting those mentions, determining which represent active problems versus historical or resolved ones, and reconciling them against the existing problem list. That extraction and classification problem is what we're solving here.

---

## The Technology: Clinical Concept Extraction and Assertion Detection

### What Is Problem List Extraction?

Problem list extraction is a two-stage NLP task. First, you identify mentions of clinical problems (diagnoses, conditions, symptoms) in unstructured text. Second, you classify each mention by its assertion status: is this problem currently active, historically relevant but resolved, negated ("no evidence of diabetes"), related to family history, or hypothetical ("if she develops CKD")?

The first stage is a variant of Named Entity Recognition (NER) focused on clinical conditions. The second stage is assertion classification, sometimes called contextual analysis or negation/temporality detection. Both stages must work together: extracting "diabetes" from a note is useless without knowing whether the patient has diabetes, used to have diabetes, doesn't have diabetes, or has a family history of diabetes.

### Named Entity Recognition for Clinical Problems

Clinical NER for problems targets a broad category. Unlike medication extraction (where you're looking for drug names with well-defined lexical patterns), problem mentions come in many forms:

**Formal diagnoses**: "Type 2 diabetes mellitus," "chronic obstructive pulmonary disease," "major depressive disorder"

**Abbreviations and acronyms**: "HTN," "CHF," "COPD," "DM2," "CKD Stage 3b," "OA," "BPH"

**Descriptive mentions**: "elevated blood pressure," "worsening kidney function," "feeling down and hopeless"

**Eponyms and named conditions**: "Hashimoto's thyroiditis," "Parkinson's disease," "Crohn's"

**Symptom clusters that imply a condition**: "polyuria, polydipsia, and unexplained weight loss" (implying undiagnosed diabetes)

The challenge is that problem mentions don't follow a single lexical pattern. Drug names are at least constrained to a finite (if large) vocabulary. Clinical problems span the entire breadth of medicine, from "headache" to "anti-NMDA receptor encephalitis." A good extraction system needs both dictionary coverage and contextual pattern recognition.

Modern approaches use transformer-based models trained on annotated clinical corpora. The i2b2 2010 challenge established benchmarks for clinical concept extraction, and subsequent datasets (ShARe/CLEF, n2c2) have pushed the field forward. Current state-of-the-art models achieve F1 scores in the 85-92% range for clinical problem extraction, depending on the dataset and entity granularity.

### Assertion Classification: The Hard Part

Extracting a problem mention is step one. Determining what that mention means in context is step two, and it's significantly harder.

Consider these sentences, all from the same progress note:

- "Patient has well-controlled type 2 diabetes." (Active, present)
- "History of pneumonia in 2022, resolved." (Historical, resolved)
- "No evidence of malignancy on imaging." (Negated)
- "Mother and sister both have breast cancer." (Family history)
- "If renal function continues to decline, may need dialysis." (Hypothetical)
- "Rule out pulmonary embolism." (Uncertain/possible)

All six contain clinical problem mentions. Only the first represents something that belongs on the active problem list. The assertion classifier must distinguish these contexts reliably, because putting a negated condition on the active problem list is worse than not extracting it at all.

Assertion classification approaches:

**Rule-based (NegEx, ConText)**: The classic approach. NegEx (2001) uses trigger terms and scope rules to detect negation ("no," "denies," "without," "absent"). ConText extends this to temporality ("history of," "previously") and experiencer ("family history," "mother has"). Simple, fast, interpretable. Still competitive for straightforward patterns. Falls apart on complex sentence structures or implicit negation.

**Statistical/ML models**: CRF or SVM classifiers trained on assertion-annotated corpora. Features include surrounding tokens, dependency parse features, section headers, and trigger term presence. Better than pure rules at handling ambiguous cases.

**Transformer-based models**: Fine-tuned BERT variants that jointly model extraction and assertion. These encode enough context to handle sentences like "She was evaluated for PE but CT was negative" (where "PE" is negated, but the negation signal is several tokens away and syntactically complex). Current best performers.

**Managed NLP services**: Cloud services that return assertion traits (NEGATION, PAST_HISTORY, HYPOTHETICAL, FAMILY_HISTORY) alongside extracted entities. These package trained models behind APIs and handle both extraction and assertion in a single call.

### Negation Detection: Deserves Its Own Discussion

Negation is the single most important assertion type to get right, because a false positive (treating a negated condition as present) directly corrupts the problem list. It's also more nuanced than it appears.

Simple negation: "No diabetes." "Denies chest pain." "Without evidence of CHF." These are handled well by rule-based systems and any trained model.

Distant negation: "The CT scan performed last Thursday to evaluate the patient's persistent cough showed no evidence of malignancy in the right lung." The negation trigger ("no evidence") is 20+ tokens from "malignancy." Scope-based rules struggle here.

Implicit negation: "Blood glucose has been normal on all recent labs." This implies the patient does not have diabetes, but the word "no" or "denies" never appears. Pure trigger-based systems miss this entirely.

Double negation: "Not without risk of cardiac complications." This is technically affirming risk, but pattern matchers that see "not" and "without" might over-negate.

Negation of negation: "Her previous denial of chest pain is inconsistent with the current presentation." The assertion status here is complex and arguably ambiguous.

In practice, you'll get 90-95% of negation right with a good model. The remaining 5-10% is where clinical NLP earns its reputation for difficulty.

### Terminology Normalization: SNOMED CT and ICD-10

Once you've extracted a problem and determined it's active, you need to map it to a standard code. Two coding systems dominate:

**SNOMED CT** (Systematized Nomenclature of Medicine, Clinical Terms): The rich ontological standard. SNOMED has over 350,000 concepts organized in a hierarchy with relationships (is-a, finding-site, associated-morphology). It's the preferred terminology for clinical documentation and problem lists because of its granularity and expressiveness.

**ICD-10-CM** (International Classification of Diseases, 10th Revision, Clinical Modification): The billing and reporting standard. About 70,000 codes. Required for claims and quality reporting. Less granular than SNOMED for clinical documentation but universally understood by administrative systems.

In practice, you often need both: SNOMED for the problem list (because it captures clinical nuance) and ICD-10 for downstream billing and quality workflows. SNOMED-to-ICD-10 maps exist (maintained by NLM and SNOMED International) but are not one-to-one; many SNOMED concepts map to multiple ICD-10 codes depending on context.

The normalization challenge mirrors what we saw with RxNorm in Recipe 8.4: the same condition can be expressed dozens of ways in text, and all of those need to resolve to the same concept code. "CHF," "congestive heart failure," "heart failure with reduced ejection fraction," "systolic heart failure," and "HFrEF" all need to land in the right neighborhood of SNOMED/ICD-10, at the appropriate level of specificity.

### The General Architecture Pattern

```text
[Clinical Note] → [Section Detection] → [Problem NER] → [Assertion Classification] → [Terminology Normalization] → [Problem List Reconciliation] → [Structured Output]
```

**Section Detection**: Identify note sections to provide context. Problem mentions in "Assessment/Plan" are highly likely to be active. Mentions in "Family History" should be tagged as such. Mentions in "Past Medical History" might be either active or resolved depending on additional context.

**Problem NER**: Extract spans of text that represent clinical problems, conditions, diagnoses, or symptoms. Tag each with begin/end offsets and a confidence score.

**Assertion Classification**: For each extracted problem, determine its assertion status: present, absent (negated), possible, conditional, historical, family history, or hypothetical. This is the gate that prevents negated and historical conditions from polluting the active problem list.

**Terminology Normalization**: Map the extracted text to SNOMED CT and/or ICD-10-CM codes. Handle abbreviations, synonyms, and varying levels of specificity. Return ranked candidates with confidence scores.

**Problem List Reconciliation**: Compare extracted active problems against the existing problem list. Identify: (a) problems documented in notes but missing from the list, (b) problems on the list that notes suggest are resolved, (c) problems that might need specificity updates (e.g., "diabetes" on the list but notes consistently say "type 2 diabetes with nephropathy").

**Structured Output**: Produce a machine-readable representation with the problem text, SNOMED code, ICD-10 code, assertion status, source note reference, and confidence scores.

---

## The AWS Implementation

### Why These Services

**Amazon Comprehend Medical for clinical NER and assertion detection.** Comprehend Medical's `DetectEntitiesV2` API extracts medical conditions (category: MEDICAL_CONDITION) with associated traits including NEGATION, SYMPTOM, SIGN, and DIAGNOSIS differentiation. It also returns assertion traits (NEGATION, HYPOTHETICAL) and attributes like ACUITY (chronic vs. acute). For condition-to-code mapping, the `InferICD10CM` and `InferSNOMEDCT` APIs take clinical text and return ranked terminology codes with confidence scores. Together, these three APIs handle extraction, assertion, and normalization as managed services.

**Amazon S3 for note storage and results.** Clinical notes arrive from HL7 feeds, EHR exports, or ADT messages. S3 provides encrypted staging for incoming notes, archival for extraction results, and a trigger mechanism (S3 event notifications) for automated processing.

**AWS Lambda for extraction orchestration.** Each note goes through a stateless pipeline: receive text, detect sections, call Comprehend Medical APIs, assemble structured output. Lambda's request-based scaling handles both real-time single-note processing and burst loads during batch operations.

**Amazon DynamoDB for problem list storage.** Extracted problems need fast lookups by patient ID (for reconciliation views) and by problem code (for population-level queries). DynamoDB supports both with a composite key design: patient ID as partition key, problem code as sort key.

**AWS Step Functions for batch reconciliation.** When running extraction against a historical note corpus to identify problem list gaps across a patient panel, Step Functions coordinates the parallel processing, handles retries on throttling, and tracks completion status.

### Architecture Diagram

<!-- TODO (TechWriter): Expert review A2 (MEDIUM). Add SQS DLQ for Lambda invocation failures and a CloudWatch alarm on DLQ depth. Show in diagram and mention in "Why These Services." -->

```mermaid
flowchart LR
    A[Clinical Note Source\nHL7/EHR/ADT] -->|Store| B[S3 Bucket\nnotes-inbox/]
    B -->|S3 Event| C[Lambda\nproblem-extractor]
    C -->|DetectEntitiesV2| D[Comprehend Medical]
    D -->|Entities + Traits| C
    C -->|InferICD10CM| E[Comprehend Medical\nICD-10]
    C -->|InferSNOMEDCT| F[Comprehend Medical\nSNOMED CT]
    E -->|ICD-10 Codes| C
    F -->|SNOMED Codes| C
    C -->|Reconcile| G[DynamoDB\npatient-problems]
    C -->|Full Results| H[S3\nresults/]

    style B fill:#f9f,stroke:#333
    style D fill:#ff9,stroke:#333
    style E fill:#ff9,stroke:#333
    style F fill:#ff9,stroke:#333
    style G fill:#9ff,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon Comprehend Medical, Amazon S3, AWS Lambda, Amazon DynamoDB, AWS Step Functions (for batch) |
| **IAM Permissions** | `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferICD10CM`, `comprehendmedical:InferSNOMEDCT`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:Query`, `dynamodb:UpdateItem` (used by downstream clinician review workflow to accept/reject recommendations) |
| **BAA** | AWS BAA signed (required: clinical notes contain PHI) |
| **Encryption** | S3: SSE-KMS; DynamoDB: encryption at rest (default); Lambda CloudWatch log groups: KMS encryption (logs may contain extracted clinical data); all API calls over TLS |
| **VPC** | Production: Lambda in VPC with VPC endpoints for S3, DynamoDB, and CloudWatch Logs. Comprehend Medical does not have a VPC endpoint; route through NAT Gateway (traffic is TLS-encrypted in transit). Evaluate whether your compliance posture permits NAT Gateway egress for PHI, or run Lambda outside VPC with resource-based policies on S3 and DynamoDB. |
| **CloudTrail** | Enabled: log all Comprehend Medical and S3 API calls for HIPAA audit trail |
| **Sample Data** | Synthetic clinical notes with problem mentions across sections. MIMIC-III (with DUA) provides realistic note structures. n2c2 datasets offer annotated clinical text for validation. Never use real patient notes in dev without proper IRB/DUA. |
| **Cost Estimate** | Comprehend Medical DetectEntitiesV2: ~$0.01 per 100-character unit (1 unit = 100 chars, minimum 3 units). InferICD10CM and InferSNOMEDCT: same per-unit pricing, called on shorter extracted spans. A typical 3000-character note: ~$0.30 for detection + $0.02-0.10 for normalization (depending on number of extracted problems). Total: ~$0.30-0.80 per note depending on length and problem count. |

### Ingredients

| AWS Service | Role |
|-------------|------|
| **Amazon Comprehend Medical** | NER extraction (DetectEntitiesV2), ICD-10 normalization (InferICD10CM), SNOMED normalization (InferSNOMEDCT) |
| **Amazon S3** | Stores incoming clinical notes and extraction results; encrypted with KMS |
| **AWS Lambda** | Orchestrates extraction pipeline: section detection, API calls, reconciliation logic |
| **Amazon DynamoDB** | Stores patient problem lists with history and provenance |
| **AWS Step Functions** | Coordinates batch processing for historical note backfills |
| **AWS KMS** | Manages encryption keys for S3 and DynamoDB |
| **Amazon CloudWatch** | Logs, metrics, alarms for extraction failures and API throttling |

### Code

> **Reference implementations:** The following AWS sample repos demonstrate patterns used in this recipe:
>
> - [`amazon-comprehend-medical-fhir-integration`](https://github.com/aws-samples/amazon-comprehend-medical-fhir-integration): End-to-end pipeline extracting clinical entities from notes and mapping to FHIR resources
> - [`amazon-comprehend-medical-ICD10-mapping`](https://github.com/aws-samples/amazon-comprehend-medical-ICD10-mapping): ICD-10 inference from clinical text using Comprehend Medical

#### Walkthrough

**Step 1: Section detection.** Clinical notes have structure, even when they look like walls of text. Section headers ("ASSESSMENT:", "PAST MEDICAL HISTORY:", "FAMILY HISTORY:") provide critical context for assertion classification downstream. A problem mentioned under "Family History" should never end up on the patient's active problem list. This step identifies sections and tags them by category so later steps can use that context. Skip this step and you'll extract problems accurately but misclassify their assertion status, which is arguably worse than not extracting them at all.

```pseudocode
FUNCTION detect_sections(note_text):
    // Section header patterns found in common clinical note formats.
    // These categories determine how extracted problems are interpreted downstream.
    ACTIVE_SECTIONS   = ["assessment", "assessment and plan", "a/p", "active problems",
                         "problem list", "diagnoses", "impression", "current problems"]
    PMH_SECTIONS      = ["past medical history", "pmh", "medical history",
                         "past history", "prior diagnoses"]
    FAMILY_SECTIONS   = ["family history", "fh", "family hx"]
    RESOLVED_SECTIONS = ["resolved problems", "inactive problems", "past problems"]
    ALLERGY_SECTIONS  = ["allergies", "drug allergies", "adverse reactions"]

    sections = empty list
    current_section = { category: "UNKNOWN", text: "", start: 0 }

    FOR each line in note_text:
        // Check if this line is a section header.
        // Common patterns: "SECTION NAME:", "** Section Name **", all-caps lines.
        header = extract_header_if_present(line)

        IF header is not null:
            // Save the previous section and start a new one.
            IF current_section.text is not empty:
                append current_section to sections

            // Classify this header into a category for downstream context.
            category = classify_header(header, ACTIVE_SECTIONS, PMH_SECTIONS,
                                       FAMILY_SECTIONS, RESOLVED_SECTIONS, ALLERGY_SECTIONS)
            current_section = { category: category, text: "", start: current_offset }
        ELSE:
            current_section.text += line + newline

    // Don't forget the last section.
    IF current_section.text is not empty:
        append current_section to sections

    RETURN sections
```

**Step 2: Extract clinical problems.** Send each relevant section to the NER service for entity extraction. We're specifically looking for entities of category MEDICAL_CONDITION, which covers diagnoses, symptoms, signs, and disease mentions. The service returns each entity with its text span, confidence score, and traits (like NEGATION or SIGN vs. DIAGNOSIS). We filter to MEDICAL_CONDITION entities and carry forward the section context from Step 1 so we know where each problem was found. Skip this step and you have no raw material for the rest of the pipeline.

<!-- TODO (TechWriter): Expert review A4 (MEDIUM). Add note that Comprehend Medical DetectEntitiesV2 has a 20,000-character limit per request. Sections exceeding this need chunking at sentence boundaries with offset correction. Discharge summaries and operative notes can exceed this. -->

```pseudocode
FUNCTION extract_problems(sections):
    // Process each section through the NER service.
    // We only send sections that could contain relevant problem mentions.
    RELEVANT_CATEGORIES = ["ACTIVE", "PMH", "FAMILY", "RESOLVED", "UNKNOWN"]
    all_problems = empty list

    FOR each section in sections:
        IF section.category not in RELEVANT_CATEGORIES:
            CONTINUE  // skip allergy sections, medication sections, etc.

        // Call the managed NER service on this section's text.
        response = call ComprehendMedical.DetectEntitiesV2 with:
            Text = section.text

        // Filter to MEDICAL_CONDITION entities only.
        // Other entity types (MEDICATION, ANATOMY, TEST_TREATMENT_PROCEDURE)
        // are useful for other recipes but not our target here.
        FOR each entity in response.Entities:
            IF entity.Category == "MEDICAL_CONDITION":
                problem = {
                    text: entity.Text,
                    confidence: entity.Score,
                    begin_offset: entity.BeginOffset + section.start,
                    end_offset: entity.EndOffset + section.start,
                    section: section.category,
                    traits: entity.Traits,      // NEGATION, SIGN, DIAGNOSIS, SYMPTOM
                    attributes: entity.Attributes   // ACUITY, DIRECTION, SYSTEM_ORGAN_SITE
                }
                append problem to all_problems

    RETURN all_problems
```

**Step 3: Classify assertion status.** This is the critical gate. Each extracted problem gets classified as active, negated, historical, family history, hypothetical, or resolved. We combine two signals: (a) the traits returned by the NER service (NEGATION trait, for example) and (b) the section context from Step 1 (a problem found in "Family History" section is family history regardless of what the NER traits say). The section context often overrides or supplements the sentence-level traits. Skip this step and your problem list fills up with negated conditions and family history items that don't belong there.

```pseudocode
FUNCTION classify_assertions(problems):
    // Combine NER-level traits with section-level context for final assertion.
    classified_problems = empty list

    FOR each problem in problems:
        // Start with the section-level context as the baseline assertion.
        assertion = determine_base_assertion(problem.section)
        // "ACTIVE" section -> PRESENT
        // "PMH" section -> HISTORICAL
        // "FAMILY" section -> FAMILY_HISTORY
        // "RESOLVED" section -> RESOLVED
        // "UNKNOWN" section -> PRESENT (default, will be refined by traits)

        // Now refine based on entity-level traits from the NER service.
        FOR each trait in problem.traits:
            IF trait.Name == "NEGATION" AND trait.Score >= 0.80:
                assertion = "NEGATED"
                // Negation overrides section context. "No diabetes" in the Assessment
                // section means the patient does NOT have diabetes.

            IF trait.Name == "HYPOTHETICAL" AND trait.Score >= 0.80:
                assertion = "HYPOTHETICAL"
                // "If she develops renal failure" is not an active problem.

        // Additional heuristic: check for temporal markers in surrounding text.
        // Words like "resolved," "s/p" (status post), "previous," "former" suggest
        // the problem is no longer active even if found in an active section.
        IF contains_resolution_markers(problem.text, surrounding_context):
            IF assertion == "PRESENT":
                assertion = "HISTORICAL"

        classified_problem = problem + { assertion: assertion }
        append classified_problem to classified_problems

    RETURN classified_problems
```

**Step 4: Normalize to standard codes.** Active and historical problems need terminology codes for downstream use: SNOMED CT for clinical problem list maintenance, ICD-10-CM for billing and quality reporting. We call the normalization APIs with the extracted problem text and get back ranked code candidates with confidence scores. The top candidate isn't always right (especially for abbreviations or partial mentions), so we return the top 3 and let downstream consumers apply their own threshold. Skip this step and you have free-text problems that can't be reconciled, deduplicated, or used for clinical decision support.

```pseudocode
FUNCTION normalize_problems(classified_problems):
    // Only normalize problems that might go on the problem list.
    // Negated and hypothetical problems don't need codes.
    NORMALIZE_ASSERTIONS = ["PRESENT", "HISTORICAL", "FAMILY_HISTORY"]
    normalized = empty list

    FOR each problem in classified_problems:
        IF problem.assertion not in NORMALIZE_ASSERTIONS:
            // Still include in output for completeness, just without codes.
            append problem + { icd10: null, snomed: null } to normalized
            CONTINUE

        // Call ICD-10 inference.
        icd10_response = call ComprehendMedical.InferICD10CM with:
            Text = problem.text

        // Call SNOMED CT inference.
        snomed_response = call ComprehendMedical.InferSNOMEDCT with:
            Text = problem.text

        // Take top 3 candidates from each, with scores.
        icd10_codes = top 3 concepts from icd10_response.Entities[0].ICD10CMConcepts
        snomed_codes = top 3 concepts from snomed_response.Entities[0].SNOMEDCTConcepts

        normalized_problem = problem + {
            icd10: icd10_codes,   // [{Code, Description, Score}, ...]
            snomed: snomed_codes   // [{Code, Description, Score}, ...]
        }
        append normalized_problem to normalized

    RETURN normalized
```

**Step 5: Reconcile against existing problem list.** This is where extraction becomes actionable. We compare the extracted active problems against the patient's current problem list in the database. The output is a reconciliation report: new problems to consider adding, existing problems that might be resolved, and existing problems that could use specificity updates. This is always a recommendation, never an automatic update, because problem list maintenance is a clinical act that requires physician review. Skip this step and you have a nice extraction pipeline that produces results nobody acts on.

<!-- TODO (TechWriter): Expert review A5 (MEDIUM). Reconciliation uses only top-1 SNOMED code for matching. Should check all top-3 candidates or use SNOMED hierarchy-aware deduplication to avoid false ADD_CANDIDATE recommendations for problems already on the list under a different code. -->

```pseudocode
FUNCTION reconcile_problems(patient_id, extracted_problems, note_id):
    // Fetch the patient's current problem list from the database.
    current_list = query DynamoDB for patient_id where status == "ACTIVE"

    // Separate extracted problems by assertion for different reconciliation logic.
    active_extracted = filter extracted_problems where assertion == "PRESENT"
    resolved_signals = filter extracted_problems where assertion == "HISTORICAL"
                       OR contains_resolution_markers == true

    recommendations = empty list

    // 1. Find problems mentioned as active in notes but missing from the list.
    FOR each extracted in active_extracted:
        IF extracted.snomed[0].Code not in current_list codes:
            // Potential gap: documented in note but not on problem list.
            append to recommendations: {
                type: "ADD_CANDIDATE",
                problem: extracted.text,
                snomed: extracted.snomed[0],
                icd10: extracted.icd10[0],
                confidence: extracted.confidence,
                source: note_id,
                rationale: "Mentioned as active in " + extracted.section + " section"
            }

    // 2. Find problems on the list that notes suggest are resolved.
    FOR each existing in current_list:
        IF existing.snomed_code appears in resolved_signals codes:
            append to recommendations: {
                type: "RESOLVE_CANDIDATE",
                problem: existing.problem_text,
                snomed: existing.snomed_code,
                confidence: resolved_signal.confidence,
                source: note_id,
                rationale: "Mentioned with resolution markers in recent note"
            }

    // 3. Find specificity upgrades (e.g., "diabetes" -> "type 2 diabetes with CKD").
    FOR each existing in current_list:
        FOR each extracted in active_extracted:
            IF extracted.snomed[0].Code is_child_of existing.snomed_code:
                // More specific code found in notes than what's on the list.
                append to recommendations: {
                    type: "SPECIFICITY_UPGRADE",
                    current: existing.problem_text,
                    suggested: extracted.text,
                    new_snomed: extracted.snomed[0],
                    new_icd10: extracted.icd10[0],
                    source: note_id
                }

    RETURN recommendations
```

**Step 6: Store results and generate reconciliation report.** Write the full extraction results to S3 for audit and reprocessing. Write reconciliation recommendations to DynamoDB where clinician review workflows can surface them. Every recommendation includes its source note, confidence score, and rationale so reviewers have enough context to accept or reject it without re-reading the entire note.

<!-- TODO (TechWriter): Expert review A3 (MEDIUM). Add note about idempotent reprocessing: recommendation_id should be deterministic (note_id + snomed_code + type) with a conditional write to prevent duplicates on reprocessing. -->

```pseudocode
FUNCTION store_results(patient_id, extracted_problems, recommendations, note_id):
    // Store full extraction results in S3 for audit trail and reprocessing.
    write to S3 key "results/{patient_id}/{note_id}.json":
        {
            patient_id: patient_id,
            note_id: note_id,
            extraction_timestamp: current UTC timestamp (ISO 8601),
            problems_extracted: extracted_problems,   // all problems with assertions and codes
            recommendations: recommendations       // reconciliation suggestions
        }

    // Store actionable recommendations in DynamoDB for clinician review.
    FOR each rec in recommendations:
        write to DynamoDB table "problem-list-recommendations":
            patient_id       = patient_id              // partition key
            recommendation_id = generate unique ID     // sort key
            type             = rec.type                // ADD_CANDIDATE, RESOLVE_CANDIDATE, etc.
            problem_text     = rec.problem
            snomed_code      = rec.snomed.Code
            icd10_code       = rec.icd10.Code (if present)
            confidence       = rec.confidence
            source_note      = note_id
            rationale        = rec.rationale
            status           = "PENDING_REVIEW"        // awaiting clinician action
            created_at       = current UTC timestamp
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter08.05-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

### Expected Results

**Sample output for a progress note mentioning several conditions:**

```json
{
  "patient_id": "PAT-2847103",
  "note_id": "NOTE-20260301-0482",
  "extraction_timestamp": "2026-03-01T14:22:08Z",
  "problems_extracted": [
    {
      "text": "type 2 diabetes",
      "assertion": "PRESENT",
      "section": "ACTIVE",
      "confidence": 0.97,
      "snomed": [{"Code": "44054006", "Description": "Type 2 diabetes mellitus", "Score": 0.95}],
      "icd10": [{"Code": "E11.9", "Description": "Type 2 diabetes mellitus without complications", "Score": 0.91}]
    },
    {
      "text": "chronic kidney disease stage 3",
      "assertion": "PRESENT",
      "section": "ACTIVE",
      "confidence": 0.94,
      "snomed": [{"Code": "433144002", "Description": "Chronic kidney disease stage 3", "Score": 0.93}],
      "icd10": [{"Code": "N18.3", "Description": "Chronic kidney disease, stage 3 (moderate)", "Score": 0.90}]
    },
    {
      "text": "pneumonia",
      "assertion": "HISTORICAL",
      "section": "PMH",
      "confidence": 0.89,
      "snomed": [{"Code": "233604007", "Description": "Pneumonia", "Score": 0.88}],
      "icd10": [{"Code": "J18.9", "Description": "Pneumonia, unspecified organism", "Score": 0.85}]
    },
    {
      "text": "chest pain",
      "assertion": "NEGATED",
      "section": "ACTIVE",
      "confidence": 0.92,
      "snomed": null,
      "icd10": null
    }
  ],
  "recommendations": [
    {
      "type": "ADD_CANDIDATE",
      "problem": "chronic kidney disease stage 3",
      "snomed": {"Code": "433144002", "Description": "Chronic kidney disease stage 3"},
      "icd10": {"Code": "N18.3", "Description": "Chronic kidney disease, stage 3 (moderate)"},
      "confidence": 0.94,
      "source": "NOTE-20260301-0482",
      "rationale": "Mentioned as active in ACTIVE section but not on current problem list"
    }
  ]
}
```

**Performance benchmarks:**

| Metric | Typical Value |
|--------|---------------|
| End-to-end latency | 2-5 seconds per note |
| Problem extraction F1 | 85-92% (varies by note type and specialty) |
| Assertion classification accuracy | 88-94% for negation; 80-88% for temporal |
| SNOMED normalization accuracy (top-1) | 75-85% (top-3 reaches 90%+) |
| ICD-10 normalization accuracy (top-1) | 70-82% (top-3 reaches 88%+) |
| Cost per note | ~$0.30-0.80 depending on note length and problem count |
| Throughput | ~30 notes/second (Lambda concurrency limited) |

**Where it struggles:**

- Abbreviations that are ambiguous across specialties ("MS" = multiple sclerosis? morphine sulfate? mitral stenosis?)
- Implicit problems mentioned through symptom clusters rather than named diagnoses
- Distinguishing "chronic stable" conditions from "active and worsening" conditions (both are "present" but have different clinical urgency)
- Very long notes where a problem is mentioned once in passing among thousands of words
- Specialty-specific shorthand (orthopedic notes are particularly terse)
- Combination/compound conditions: "diabetes with nephropathy and retinopathy" is one problem or three?

---

## The Honest Take

Problem list extraction is one of those problems that feels like it should be 90% solved by off-the-shelf NER, and in some sense it is. The extraction piece works well. You'll get most problem mentions out of a note with reasonable accuracy on your first attempt.

The hard part is everything after extraction. Assertion classification is where the pain lives. Getting negation right 95% of the time sounds great until you realize that 5% error rate on a 3000-patient panel means dozens of patients with incorrectly flagged conditions. And the failure mode is asymmetric: a false positive (adding a negated condition to the active list) erodes clinician trust in the system much faster than a false negative (missing a real problem) does.

The reconciliation logic is where the real engineering challenge hides. SNOMED concept hierarchies are complex, and determining whether two codes represent "the same problem at different specificity levels" versus "genuinely different conditions" requires clinical ontology reasoning that's harder than it looks. "Type 2 diabetes" and "Type 2 diabetes with diabetic nephropathy" are in the same hierarchy, but one is a specificity upgrade of the other. "Type 2 diabetes" and "diabetic foot ulcer" are related but are genuinely separate problem list entries.

What surprised me most: the section detection step (which seems like simple string matching) has an outsized impact on overall accuracy. Notes without clear section headers, or with non-standard formatting, degrade assertion classification significantly. The NER engine extracts the condition fine; it's the "does this patient actually have it" determination that suffers when section context is missing.

One more thing. Problem list extraction is inherently a clinician-in-the-loop workflow. You're generating recommendations, not making changes. The moment you auto-add conditions to a problem list without physician review, you've crossed from decision support into autonomous clinical documentation, and that's a different regulatory and liability landscape entirely. Keep the human in the loop. Frame your pipeline as "here are problems you might want to add" not "I've updated the problem list for you."

---

## Variations and Extensions

**Multi-note longitudinal extraction.** Instead of processing one note at a time, aggregate problem mentions across all recent notes for a patient and use frequency/recency signals to strengthen confidence. A problem mentioned in 5 of the last 8 notes is much more likely to be truly active than one mentioned once. This approach also helps detect resolved conditions: if "pneumonia" was mentioned in notes 6 months ago but absent from all recent documentation, it's likely resolved.

**Specialty-adapted assertion models.** Different specialties have different documentation patterns. An orthopedic note uses abbreviations and shorthand that an internal medicine model hasn't seen. Train or fine-tune separate assertion classifiers per specialty, using the note's authoring provider specialty as a routing signal. This adds complexity but can improve assertion accuracy by 5-10% for high-volume specialty note types.

**FHIR Condition resource integration.** Map extracted problems directly to FHIR Condition resources and push them to a FHIR server for interoperability. This enables problem list synchronization across systems that speak FHIR (which is increasingly most of them under ONC Cures Act requirements). The FHIR Condition resource has fields for clinical status (active, recurrence, relapse, inactive, remission, resolved) that map cleanly to the assertion categories in this pipeline.

---

## Related Recipes

- **Recipe 8.4 (Medication Extraction and Normalization):** Uses the same Comprehend Medical extraction pattern but targets medications instead of conditions. Shares section detection and assertion classification concepts.
- **Recipe 8.8 (Clinical Assertion Classification):** Dives deep into assertion detection as a standalone capability. Use that recipe's patterns to build a more sophisticated assertion engine if the built-in traits are insufficient.
- **Recipe 8.3 (ICD-10 Code Suggestion):** Focuses on coding workflow integration. Combine with this recipe to generate ICD-10 suggestions from problem list extractions for HCC coding.
- **Recipe 13.3 (ICD/CPT Hierarchy Navigation):** Provides the ontology navigation needed for the specificity upgrade logic in reconciliation.

---

## Additional Resources

**AWS Documentation:**
- [Amazon Comprehend Medical DetectEntitiesV2 API Reference](https://docs.aws.amazon.com/comprehend-medical/latest/api/API_DetectEntitiesV2.html)
- [Amazon Comprehend Medical InferICD10CM API Reference](https://docs.aws.amazon.com/comprehend-medical/latest/api/API_InferICD10CM.html)
- [Amazon Comprehend Medical InferSNOMEDCT API Reference](https://docs.aws.amazon.com/comprehend-medical/latest/api/API_InferSNOMEDCT.html)
- [Amazon Comprehend Medical Pricing](https://aws.amazon.com/comprehend/medical/pricing/)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Architecting for HIPAA on AWS (Whitepaper)](https://docs.aws.amazon.com/whitepapers/latest/architecting-hipaa-security-and-compliance-on-aws/welcome.html)

**AWS Sample Repos:**
- [`amazon-comprehend-medical-fhir-integration`](https://github.com/aws-samples/amazon-comprehend-medical-fhir-integration): Pipeline extracting clinical entities and mapping to FHIR resources including Condition
- [`amazon-comprehend-medical-ICD10-mapping`](https://github.com/aws-samples/amazon-comprehend-medical-ICD10-mapping): ICD-10 code inference from clinical text

**AWS Solutions and Blogs:**
- [Extracting Medical Information from Clinical Text with Amazon Comprehend Medical](https://aws.amazon.com/blogs/machine-learning/extracting-medical-information-from-clinical-text-using-amazon-comprehend-medical/): Overview of entity extraction patterns for clinical documentation
- [Building a Medical Concept Normalization Pipeline with Amazon Comprehend Medical](https://aws.amazon.com/blogs/machine-learning/building-a-medical-language-processing-pipeline-using-amazon-comprehend-medical/): End-to-end architecture for clinical NLP pipelines

---

## Estimated Implementation Time

| Phase | Duration |
|-------|----------|
| **Basic** (single-note extraction, no reconciliation) | 2-3 weeks |
| **Production-ready** (reconciliation, review workflow, monitoring) | 6-10 weeks |
| **With variations** (multi-note longitudinal, specialty-adapted, FHIR integration) | 12-16 weeks |

---

## Tags

`nlp` · `ner` · `clinical-nlp` · `problem-list` · `comprehend-medical` · `snomed` · `icd-10` · `assertion-detection` · `negation` · `reconciliation` · `medium` · `lambda` · `dynamodb` · `hipaa`

---

*← [Recipe 8.4: Medication Extraction and Normalization](chapter08.04-medication-extraction-normalization) · [Chapter 8 Index](chapter08-index) · [Next: Recipe 8.6: SDOH Extraction →](chapter08.06-sdoh-extraction)*
