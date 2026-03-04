# Category 8: Natural Language Processing (Non-LLM)

**Healthcare Use Cases — Simple → Complex**

---

## 8.1 Chief Complaint Classification (Simple)

**What:** Classify free-text chief complaints into standardized categories for triage routing and analytics.

**Why simple:** Short text inputs. Finite set of categories. Training data abundant from historical routing. Errors caught at triage. Well-solved problem.

---

## 8.2 Patient Sentiment Analysis (Simple)

**What:** Analyze patient feedback (surveys, reviews, complaints) for sentiment and theme extraction.

**Why simple:** Standard sentiment analysis techniques apply. Output is aggregate insights, not patient-level decisions. Low clinical risk. Easy to validate with human review.

---

## 8.3 ICD-10 Code Suggestion (Simple-Medium)

**What:** Suggest relevant ICD-10 diagnosis codes based on clinical note text to assist coders.

**Why this complexity:** Large code vocabulary (70,000+). Context-dependent specificity. Must handle negation. Suggestions only — human coders decide. Requires integration with coding workflow.

---

## 8.4 Medication Extraction and Normalization (Medium)

**What:** Extract medication mentions from clinical notes and normalize to standard terminology (RxNorm), including dose, route, frequency.

**Why medium:** Drug name variations (brand, generic, abbreviations). Must capture full sig. Distinguish current vs. historical vs. allergies. Active medication list reconciliation.

---

## 8.5 Problem List Extraction (Medium)

**What:** Extract active problems/diagnoses from clinical notes for problem list maintenance and reconciliation.

**Why medium:** Must distinguish active vs. resolved vs. historical vs. family history. Negation detection critical. Acronyms and shorthand vary by specialty. Supports downstream clinical workflows.

---

## 8.6 Social Determinants of Health (SDOH) Extraction (Medium-Complex)

**What:** Extract social determinant information (housing status, food security, employment, social support) from clinical notes and social work documentation.

**Why this complexity:** SDOH mentions are sparse and inconsistent. Language varies by documenter. Must interpret context (risk vs. resource connected). Sensitive data requiring careful handling.

---

## 8.7 Adverse Event Detection in Clinical Text (Medium-Complex)

**What:** Identify mentions of adverse drug events, complications, or safety incidents in clinical documentation for safety surveillance.

**Why this complexity:** Adverse events often documented implicitly. Must distinguish expected vs. unexpected. Temporal reasoning required. Feeds safety/quality workflows. Under-reporting is baseline.

---

## 8.8 Clinical Assertion Classification (Complex)

**What:** Classify extracted clinical entities by assertion status: present, absent, possible, conditional, historical, family history, hypothetical.

**Why complex:** Context windows can be large. Negation and hedging language is subtle. Same entity can have different assertions in same note. Critical for accurate clinical NLP.

---

## 8.9 Temporal Relationship Extraction (Complex)

**What:** Extract temporal relationships between clinical events (before, after, during, overlapping) to construct patient timelines.

**Why complex:** Clinical text rarely uses explicit dates. Must infer from context ("postoperatively," "prior to admission"). Multi-sentence reasoning required. Enables longitudinal clinical reasoning.

---

## 8.10 Phenotype Extraction for Research (Complex)

**What:** Identify patients with specific clinical phenotypes (disease states, risk factors, outcomes) from unstructured text for cohort identification.

**Why complex:** Phenotype definitions are often complex (multiple criteria). Requires high precision for research validity. Must handle note heterogeneity across time/providers. IRB and reproducibility requirements.

---

## Complexity Factors Summary

| Factor | Impact on Complexity |
|--------|---------------------|
| Vocabulary size | More terms = harder normalization |
| Negation/assertion | Context determines meaning |
| Temporal reasoning | Clinical time is often implicit |
| Specialty variation | Each specialty has conventions |
| Downstream use | Research use demands precision |
| Gold standard availability | Annotation is expensive |

---

*Category 8 complete. Next: Category 9 (Computer Vision / Medical Imaging)*
