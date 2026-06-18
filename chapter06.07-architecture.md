# Recipe 6.7 Architecture and Implementation: Clinical Trial Patient Matching

*Companion to [Recipe 6.7: Clinical Trial Patient Matching](chapter06.07-clinical-trial-patient-matching). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## The AWS Implementation

### Why These Services

**Amazon SageMaker for NLP models.** The clinical NLP pipeline (entity extraction, negation detection, temporal reasoning) requires custom models trained on clinical text. SageMaker gives you the training infrastructure and real-time inference endpoints for those custom models. For organizations without custom models, Amazon Comprehend Medical provides pre-trained clinical NLP as a starting point, though it lacks the trial-specific fine-tuning that improves precision.

**Amazon Comprehend Medical for clinical entity extraction.** Comprehend Medical extracts medical entities (conditions, medications, procedures, lab values) from clinical text with negation and assertion detection built in. It handles the "no history of pancreatitis" problem natively. For many criteria, this is sufficient without custom model training.

**AWS Glue and Amazon Athena for structured pre-screening.** The structured pre-screen is fundamentally a large-scale query against patient data. Glue ETL jobs transform EHR extracts into a queryable format. Athena runs the eligibility queries against the transformed data without requiring a persistent database cluster. For a 180,000-patient registry with 40 structured criteria, Athena can complete the pre-screen in minutes.

**Amazon S3 for data lake storage.** Patient data extracts, clinical notes, trial criteria definitions, and matching results all live in S3. The data lake pattern allows different processing stages to read from and write to a shared storage layer without tight coupling.

**AWS Step Functions for pipeline orchestration.** The multi-stage matching pipeline (pre-screen, NLP, scoring, notification) has dependencies between stages and needs error handling, retries, and monitoring. Step Functions gives you visual workflow orchestration with built-in retry logic and state management.

**Amazon DynamoDB for candidate tracking.** Each candidate's matching status (which criteria passed, which failed, which are pending NLP, overall score) needs fast read/write access. DynamoDB's key-value model fits the per-patient status tracking pattern.

**Amazon EventBridge for trial registry updates.** When new trials open or criteria change, EventBridge triggers re-screening of the patient population. A scheduled Lambda polls the ClinicalTrials.gov API daily for new or amended trials matching your therapeutic areas and publishes events to EventBridge when changes are detected. This keeps the candidate pool current without manual intervention.

### Architecture Diagram

```mermaid
flowchart TD
    A[Trial Registry\nClinicalTrials.gov Feed] -->|New/Updated Trials| B[EventBridge\nTrigger]
    B --> C[Step Functions\nMatching Pipeline]
    
    C --> D[Glue ETL\nCriteria Parser]
    D --> E[S3 Data Lake\nComputable Criteria]
    
    C --> F[Athena\nStructured Pre-Screen]
    F -->|Query| G[S3 Data Lake\nPatient Structured Data]
    F -->|Candidates| H[S3\nPre-Screen Results]
    
    C --> I[SageMaker Endpoint\nClinical NLP]
    I -->|Read Notes| J[S3 Data Lake\nClinical Notes]
    I -->|Entities + Assertions| K[S3\nNLP Results]
    
    C --> L[Lambda\nScoring Engine]
    L --> M[DynamoDB\nCandidate Status]
    
    M --> N[Coordinator Worklist\nUI/API]

    style F fill:#ff9,stroke:#333
    style I fill:#f9f,stroke:#333
    style M fill:#9ff,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| AWS Services | SageMaker, Comprehend Medical, Glue, Athena, S3, Step Functions, DynamoDB, EventBridge, Lambda |
| IAM Permissions | `sagemaker:InvokeEndpoint`, `comprehendmedical:DetectEntitiesV2`, `glue:StartJobRun`, `athena:StartQueryExecution`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:GetItem`, `states:StartExecution`. Scope each action to specific resource ARNs (e.g., `arn:aws:s3:::trial-matching-*` for S3, specific endpoint ARN for SageMaker). In research contexts, consider separate roles for the pre-screen stage (structured data access) and the NLP stage (clinical notes access) to enforce least-privilege separation of access. |
| BAA | Required. All services processing PHI must be covered under your AWS BAA. |
| Encryption | S3 SSE-KMS for all data at rest. DynamoDB encryption at rest. TLS 1.2+ in transit. SageMaker endpoint encryption. |
| VPC | SageMaker endpoints and Glue jobs in private subnets. VPC endpoints for S3, DynamoDB, SageMaker Runtime, and Comprehend Medical (`com.amazonaws.{region}.comprehendmedical`). Consider adding Step Functions and Lambda VPC endpoints if orchestration components are VPC-bound. Restrict security group egress to VPC endpoints only (no internet egress) for Lambda functions and SageMaker endpoints processing clinical notes. Enable VPC Flow Logs to monitor data movement patterns. |
| CloudTrail | Enabled for all API calls. Log who queried which patients and when. |
| Sample Data | Synthetic patient records (Synthea is excellent for this). ClinicalTrials.gov API for real trial criteria. Never use real PHI in development. |
| Cost Estimate | ~$0.20-$0.75 per patient screened (Comprehend Medical: ~$0.01/100 chars; SageMaker inference: ~$0.10/patient for custom NLP; Athena: ~$5/TB scanned). Store structured patient data in Parquet format partitioned by relevant dimensions (e.g., patient cohort, data type) to minimize Athena scan volume. Separate clinical notes from structured data in the S3 layout so the structured pre-screen doesn't scan note text. |

### Ingredients

| AWS Service | Role in This Recipe |
|-------------|-------------------|
| Amazon S3 | Data lake for patient data, clinical notes, trial criteria, and intermediate results |
| AWS Glue | ETL for transforming EHR extracts and parsing trial criteria into computable format |
| Amazon Athena | SQL-based structured pre-screening against patient demographics, labs, medications |
| Amazon Comprehend Medical | Extract medical entities from clinical notes with negation detection |
| Amazon SageMaker | Host custom clinical NLP models for trial-specific criteria evaluation |
| AWS Step Functions | Orchestrate the multi-stage matching pipeline with error handling |
| Amazon DynamoDB | Track per-patient matching status and scores |
| AWS Lambda | Scoring logic, result aggregation, notification triggers |
| Amazon EventBridge | Trigger re-screening when new trials open or criteria change |

### Code (Pseudocode Walkthrough)

#### Step 1: Parse Trial Eligibility Criteria

Before you can match patients, you need to decompose the trial's eligibility criteria into computable rules. Each criterion becomes a structured object with a data source, operator, and temporal constraint.

If you skip this step, your matching logic is hardcoded per trial and you'll rewrite it every time a new trial opens. A generic criteria representation lets you add trials without code changes.

```pseudocode
FUNCTION parse_trial_criteria(trial_id):
    // Fetch the raw eligibility text from the trial registry
    raw_criteria = fetch_from_clinicaltrials_gov(trial_id)
    
    parsed_criteria = []
    
    FOR EACH criterion IN raw_criteria.inclusion_criteria:
        rule = {
            criterion_id:   generate_unique_id()
            criterion_type: "INCLUSION"                    // patient MUST meet this
            raw_text:       criterion.text                 // original human-readable text
            data_source:    classify_data_source(criterion) // "STRUCTURED" or "UNSTRUCTURED" or "BOTH"
            logic:          extract_logic(criterion)        // the computable assertion
            temporal:       extract_temporal_constraint(criterion) // recency window, if any
            confidence:     0.0                            // will be filled during matching
        }
        parsed_criteria.append(rule)
    
    FOR EACH criterion IN raw_criteria.exclusion_criteria:
        rule = {
            criterion_id:   generate_unique_id()
            criterion_type: "EXCLUSION"                    // patient must NOT meet this
            raw_text:       criterion.text
            data_source:    classify_data_source(criterion)
            logic:          extract_logic(criterion)
            temporal:       extract_temporal_constraint(criterion)
            confidence:     0.0
        }
        parsed_criteria.append(rule)
    
    // Store the parsed criteria for use by the matching pipeline
    STORE parsed_criteria TO s3://trial-matching/criteria/{trial_id}.json
    
    RETURN parsed_criteria
```

**Example parsed criterion:**

```json
{
  "criterion_id": "crit-0042",
  "criterion_type": "INCLUSION",
  "raw_text": "A1C between 7.5% and 10.5% within the past 90 days",
  "data_source": "STRUCTURED",
  "logic": {
    "field": "lab_result",
    "loinc_code": "4548-4",
    "operator": "BETWEEN",
    "value_low": 7.5,
    "value_high": 10.5
  },
  "temporal": {
    "recency_days": 90,
    "reference_point": "screening_date"
  }
}
```

#### Step 2: Structured Pre-Screen

Run all structured criteria against the patient population using SQL. This eliminates the majority of patients quickly and cheaply.

If you skip this step and run NLP on every patient, you'll spend 100x more on compute and wait hours instead of minutes. The structured pre-screen is your cost control mechanism.

```pseudocode
FUNCTION structured_prescreen(trial_id, patient_population):
    criteria = LOAD FROM s3://trial-matching/criteria/{trial_id}.json
    structured_criteria = FILTER criteria WHERE data_source = "STRUCTURED"
    
    // Build a SQL query that applies all structured criteria simultaneously
    // Each criterion becomes a WHERE clause condition
    sql_query = "SELECT patient_id, "
    
    FOR EACH criterion IN structured_criteria:
        // Add a column that evaluates this criterion (TRUE/FALSE/NULL)
        sql_query += build_criterion_clause(criterion)
    
    sql_query += " FROM patient_data"
    sql_query += " WHERE " + build_inclusion_filter(structured_criteria)
    sql_query += " AND NOT " + build_exclusion_filter(structured_criteria)
    
    // Execute against the patient data lake
    results = execute_athena_query(sql_query, output_location="s3://trial-matching/prescreen/")
    
    candidates = []
    FOR EACH row IN results:
        candidate = {
            patient_id:          row.patient_id
            structured_pass:     TRUE                    // they passed all structured criteria
            criteria_results:    extract_per_criterion_results(row)
            needs_nlp_screen:    has_unstructured_criteria(criteria)
        }
        candidates.append(candidate)
    
    STORE candidates TO s3://trial-matching/candidates/{trial_id}/prescreen.json
    RETURN candidates
```

#### Step 3: NLP Deep Screen on Clinical Notes

For candidates that passed structured pre-screening, evaluate criteria that require clinical note analysis. This is where you catch exclusions like "no history of pancreatitis" that might only be documented in free text.

If you skip this step, you'll send coordinators candidates who are clearly ineligible based on information in their notes. That wastes coordinator time and erodes trust in the system.

```pseudocode
FUNCTION nlp_deep_screen(trial_id, candidates):
    criteria = LOAD FROM s3://trial-matching/criteria/{trial_id}.json
    nlp_criteria = FILTER criteria WHERE data_source IN ("UNSTRUCTURED", "BOTH")
    
    screened_candidates = []
    
    FOR EACH candidate IN candidates:
        // Retrieve relevant clinical notes for this patient
        // Limit to notes within the temporal window relevant to the criteria
        notes = fetch_clinical_notes(
            patient_id = candidate.patient_id,
            date_range = calculate_relevant_window(nlp_criteria)
        )
        
        // Run clinical NLP to extract entities with negation and temporality
        nlp_results = []
        FOR EACH note IN notes:
            entities = call_comprehend_medical(note.text)
            // entities include: conditions, medications, procedures
            // each with: text, category, type, negation flag, temporal info
            nlp_results.append({
                note_date:  note.date,
                note_type:  note.type,
                entities:   entities
            })
        
        // Evaluate each NLP criterion against extracted entities
        criterion_results = []
        FOR EACH criterion IN nlp_criteria:
            result = evaluate_criterion_against_entities(
                criterion = criterion,
                entities  = nlp_results,
                logic     = criterion.logic
            )
            // result includes: PASS, FAIL, UNCERTAIN, and confidence score
            criterion_results.append(result)
        
        // Determine overall NLP screen result
        any_definite_fail = ANY(result.status = "FAIL" AND result.confidence > 0.9 
                               FOR result IN criterion_results)
        
        IF NOT any_definite_fail:
            candidate.nlp_results = criterion_results
            candidate.nlp_pass = TRUE
            screened_candidates.append(candidate)
    
    STORE screened_candidates TO s3://trial-matching/candidates/{trial_id}/nlp_screened.json
    RETURN screened_candidates
```

#### Step 4: Score and Rank Candidates

Assign each candidate a composite eligibility score based on how confidently they meet each criterion. Higher scores mean more likely to be truly eligible.

If you skip scoring and just present an unranked list, coordinators waste time on borderline cases when clear matches are available. Ranking focuses their effort where it's most likely to result in enrollment.

```pseudocode
FUNCTION score_candidates(trial_id, candidates):
    criteria = LOAD FROM s3://trial-matching/criteria/{trial_id}.json
    
    scored_candidates = []
    
    FOR EACH candidate IN candidates:
        total_score = 0.0
        max_possible_score = 0.0
        criterion_details = []
        
        FOR EACH criterion IN criteria:
            weight = get_criterion_weight(criterion)  // some criteria matter more than others
            max_possible_score += weight
            
            // Find this criterion's result from structured or NLP screening
            result = find_criterion_result(candidate, criterion)
            
            IF result.status = "PASS":
                criterion_score = weight * result.confidence
            ELSE IF result.status = "UNCERTAIN":
                criterion_score = weight * 0.5 * result.confidence
            ELSE:
                criterion_score = 0.0
            
            total_score += criterion_score
            criterion_details.append({
                criterion_id:   criterion.criterion_id
                raw_text:       criterion.raw_text
                status:         result.status
                confidence:     result.confidence
                evidence:       result.evidence        // what data supported this determination
                data_source:    result.source          // "structured" or "note from 2025-11-03"
            })
        
        candidate.eligibility_score = total_score / max_possible_score  // normalize to 0-1
        candidate.criterion_details = criterion_details
        candidate.uncertain_count = COUNT(d FOR d IN criterion_details WHERE d.status = "UNCERTAIN")
        
        scored_candidates.append(candidate)
    
    // Sort by score descending
    scored_candidates = SORT scored_candidates BY eligibility_score DESCENDING
    
    // Store to DynamoDB for coordinator access
    FOR EACH candidate IN scored_candidates:
        WRITE TO dynamodb table "trial-candidates":
            partition_key = trial_id
            sort_key      = candidate.patient_id
            score         = candidate.eligibility_score
            details       = candidate.criterion_details
            status        = "PENDING_REVIEW"
            timestamp     = current UTC time
    
    RETURN scored_candidates
```

#### Step 5: Generate Coordinator Worklist

Present the ranked candidates to research coordinators with actionable evidence for each criterion. The coordinator needs to see why the system thinks this patient qualifies, not just that it does.

```pseudocode
FUNCTION generate_worklist(trial_id, top_n=50):
    // Retrieve top candidates from DynamoDB
    candidates = QUERY dynamodb table "trial-candidates"
        WHERE partition_key = trial_id
        AND status = "PENDING_REVIEW"
        ORDER BY score DESCENDING
        LIMIT top_n
    
    worklist = []
    FOR EACH candidate IN candidates:
        worklist_entry = {
            patient_id:       candidate.patient_id
            score:            candidate.score
            summary:          generate_eligibility_summary(candidate.details)
            uncertain_items:  FILTER candidate.details WHERE status = "UNCERTAIN"
            action_needed:    determine_coordinator_action(candidate)
            // e.g., "Confirm medication washout willingness" or "Verify no pancreatitis history"
        }
        worklist.append(worklist_entry)
    
    RETURN worklist
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter06.07-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

### Expected Results

**Sample output for a single candidate:**

```json
{
  "trial_id": "NCT05891234",
  "patient_id": "PAT-00482931",
  "eligibility_score": 0.92,
  "status": "PENDING_REVIEW",
  "criteria_summary": {
    "total_criteria": 12,
    "definite_pass": 10,
    "uncertain": 2,
    "definite_fail": 0
  },
  "criterion_details": [
    {
      "criterion_id": "crit-0001",
      "raw_text": "Adults aged 30-65",
      "status": "PASS",
      "confidence": 1.0,
      "evidence": "DOB: 1972-03-15, Age: 54",
      "data_source": "structured:demographics"
    },
    {
      "criterion_id": "crit-0007",
      "raw_text": "No history of pancreatitis",
      "status": "PASS",
      "confidence": 0.85,
      "evidence": "No mentions of pancreatitis found in 47 clinical notes spanning 2019-2026",
      "data_source": "nlp:clinical_notes"
    },
    {
      "criterion_id": "crit-0011",
      "raw_text": "Willing to discontinue SGLT2 inhibitors",
      "status": "UNCERTAIN",
      "confidence": 0.5,
      "evidence": "Patient currently on empagliflozin. Willingness not documented.",
      "data_source": "structured:medications + nlp:no_evidence_found"
    }
  ],
  "coordinator_action": "Confirm patient willingness to discontinue empagliflozin. Verify no contraindications in recent cardiology note from 2026-02-14."
}
```

**Performance benchmarks:**

| Metric | Typical Value |
|--------|---------------|
| Structured pre-screen (180K patients) | 2-5 minutes (Athena) |
| NLP deep screen (per patient) | 3-8 seconds (depends on note volume) |
| NLP deep screen (2,000 candidates) | 15-30 minutes (parallelized) |
| End-to-end pipeline (new trial) | 30-60 minutes |
| Precision (candidates who are truly eligible) | 60-75% (before coordinator review) |
| Recall (eligible patients identified) | 80-90% (structured criteria); 65-80% (NLP criteria) |
| Cost per full population screen | ~$150-400 (180K patients, 12 criteria) |

**Where it struggles:**

- Criteria requiring patient willingness or preference (can't be determined from records alone)
- Criteria with ambiguous temporal boundaries ("recent" cardiovascular event)
- Patients with sparse documentation (new to the health system, few notes)
- Negation detection in complex sentence structures ("Patient's sister had pancreatitis but patient has no personal history")
- Criteria that reference external information ("no concurrent enrollment in another trial")

---

## Why This Isn't Production-Ready

**Consent and regulatory compliance.** This system performs automated pre-screening: identifying potentially eligible patients from existing EHR data. It does not constitute screening (which requires patient contact and informed consent). This distinction matters. Most institutions can operate pre-screening under a waiver of consent per 45 CFR 46.116(f) or under HIPAA's preparatory-to-research provision (45 CFR 164.512(i)(1)(ii)), but this requires documented IRB or Privacy Board approval. Some institutions require explicit patient opt-in for any research-related data use; others allow pre-screening under existing data governance frameworks. Your legal and IRB teams need to weigh in before you screen a single patient. Document your institution's determination before deploying. The system's audit trail (CloudTrail logs of which patients were evaluated, when, and for which trial) supports the accountability requirements of both provisions. The technical system is the easy part; the governance framework is harder.

**EHR integration.** This recipe assumes you have patient data in a queryable data lake. Getting it there from your EHR (Epic, Cerner, Meditech) requires an integration layer (FHIR APIs, bulk data exports, or HL7 feeds) that is a project unto itself. The matching logic is downstream of that integration.

**Criteria maintenance.** Trial criteria change. Amendments modify inclusion/exclusion criteria mid-enrollment. Your criteria parser needs to handle updates and trigger re-screening of the candidate pool. A stale criteria set produces stale matches.

**Coordinator workflow integration.** The worklist needs to live where coordinators already work, not in a separate application they have to remember to check. Integration with CTMS (Clinical Trial Management Systems) like OnCore, Velos, or Florence is essential for adoption.

**Data retention and minimization.** Matching results in DynamoDB contain per-criterion evidence strings with derived PHI. Define a retention policy: when a trial closes enrollment, archive or delete candidate records. Consider DynamoDB TTL on the `trial-candidates` table keyed to the trial's expected enrollment close date plus a buffer for audit purposes. Evidence strings containing PHI should be treated with the same retention controls as the source clinical data.

**Error handling in the NLP stage.** The NLP deep screen processes thousands of candidates over 15-30 minutes. A single patient failure (corrupt notes, encoding issues, Comprehend Medical throttling) shouldn't fail the entire pipeline. Use Step Functions Map state with `maxConcurrency` to control parallelism and `toleratedFailurePercentage` to allow completion even if some patients fail. Failed patients should be written to a dead letter queue for retry or manual review. Checkpoint progress so a pipeline restart doesn't reprocess already-screened candidates.

---

## Variations and Extensions

**Real-time alerting on new eligibility.** Instead of batch screening, monitor incoming lab results and new diagnoses in real time. When a patient's A1C crosses a trial threshold, trigger an alert. This catches patients at the moment they become eligible rather than waiting for the next batch run. Requires streaming integration with the EHR (HL7 FHIR subscriptions or ADT feeds).

**Patient-facing trial discovery.** Flip the model: instead of coordinators finding patients, let patients find trials. Build a patient portal feature where patients can see trials they might qualify for, with plain-language explanations of what's involved. This requires careful UX design (don't overwhelm patients with options) and additional consent workflows, but it addresses the "patients never hear about trials" problem directly.

**Multi-site federated matching.** For trials recruiting across multiple health systems, run the matching pipeline at each site without sharing patient data between sites. Each site reports aggregate counts ("we have approximately 45 candidates for this trial") without exposing individual patient records. This supports network-level enrollment planning while preserving data sovereignty. Federated learning techniques can improve model performance across sites without centralizing data.

---

## Additional Resources

**AWS Documentation:**
- [Amazon Comprehend Medical Documentation](https://docs.aws.amazon.com/comprehend-medical/latest/dev/what-is.html)
- [Amazon Comprehend Medical DetectEntitiesV2 API](https://docs.aws.amazon.com/comprehend-medical/latest/dev/API_medical_DetectEntitiesV2.html)
- [Amazon SageMaker Real-Time Inference](https://docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints.html)
- [Amazon Athena User Guide](https://docs.aws.amazon.com/athena/latest/ug/what-is.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Architecting for HIPAA on AWS](https://docs.aws.amazon.com/whitepapers/latest/architecting-hipaa-security-and-compliance-on-aws/welcome.html)

**AWS Sample Repos:**
- [`amazon-comprehend-medical-fhir-integration`](https://github.com/aws-samples/amazon-comprehend-medical-fhir-integration): Demonstrates extracting medical entities from clinical text and mapping to FHIR resources
- [`amazon-sagemaker-examples`](https://github.com/aws/amazon-sagemaker-examples): Includes NLP model training and deployment patterns applicable to clinical text classification
- [`aws-step-functions-data-science-sdk-python`](https://github.com/aws/aws-step-functions-data-science-sdk-python): Building ML pipelines with Step Functions, relevant to orchestrating the matching workflow

**AWS Solutions and Blogs:**
- [Generating Real-World Evidence Using a Scalable Data Science Platform on AWS](https://aws.amazon.com/blogs/industries/generating-real-world-evidence-using-a-scalable-data-science-platform-on-aws/): Architecture patterns for clinical data processing at scale
- [Build a Cognitive Search and Health Knowledge Graph Using AWS AI Services](https://aws.amazon.com/blogs/machine-learning/build-a-cognitive-search-and-a-health-knowledge-graph-using-amazon-healthlake-amazon-neptune-and-amazon-comprehend-medical/): Demonstrates clinical NLP and knowledge graph patterns relevant to criteria matching

**External Resources:**
- [ClinicalTrials.gov API Documentation](https://clinicaltrials.gov/data-api/api): Official API for retrieving trial eligibility criteria programmatically
- [Synthea Patient Generator](https://synthetichealth.github.io/synthea/): Generate realistic synthetic patient data for development and testing

---

## Estimated Implementation Time

| Phase | Duration |
|-------|----------|
| Basic (structured pre-screen only, single trial) | 4-6 weeks |
| Production-ready (NLP deep screen, multi-trial, coordinator UI) | 12-16 weeks |
| With variations (real-time alerting, patient portal, federated) | 20-28 weeks |

---

---

*← [Main Recipe 6.7](chapter06.07-clinical-trial-patient-matching) · [Python Example](chapter06.07-python-example) · [Chapter Preface](chapter06-preface)*
