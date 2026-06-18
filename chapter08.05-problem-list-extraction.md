# Recipe 8.5: Problem List Extraction

**Complexity:** Medium · **Phase:** Integration · **Estimated Cost:** ~$0.30-0.80 per note

---

## The Problem

Every patient in your EHR has a problem list. In theory, it's the authoritative summary of active diagnoses and conditions: the single place a clinician can glance to understand what's going on with this patient. In practice, problem lists are one of the most poorly maintained data assets in healthcare.

Here's what actually happens. A patient with diabetes, hypertension, chronic kidney disease, depression, and a resolved pneumonia from last year shows up for an annual visit. The problem list in the EHR might say "HTN" (added by the PCP three years ago), "Type 2 DM" (added during a hospitalization), and nothing else. The CKD was diagnosed six months ago but the nephrologist documented it in a consult note and never updated the problem list. The depression is mentioned in every progress note but nobody added it formally. The pneumonia is still listed as active because nobody marked it resolved.

This is not a rare scenario. Studies consistently show that EHR problem lists are incomplete, with sensitivity for known diagnoses ranging from 40-70% depending on the condition and setting. Chronic conditions are under-represented. Resolved conditions linger. New diagnoses get documented in notes but never propagated to the structured list.

The downstream impact is real. Clinical decision support fires (or doesn't fire) based on the problem list. Quality measures get reported against it. Risk adjustment coding depends on it. Care coordination tools use it to identify patients who need outreach. When the problem list is wrong, all of those downstream systems produce wrong results, silently.

The information exists. It's in progress notes, discharge summaries, consult notes, procedure notes. Clinicians document diagnoses in narrative text all the time. The gap is extracting those mentions, determining which represent active problems versus historical or resolved ones, and reconciling them against the existing problem list. So that's the gap we're filling.

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

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter08.05-architecture). The Python example is linked from there.

## The Honest Take

Problem list extraction is one of those problems that feels like it should be 90% solved by off-the-shelf NER, and in some sense it is. The extraction piece works well. You'll get most problem mentions out of a note with reasonable accuracy on your first attempt.

The hard part is everything after extraction. Assertion classification is where the pain lives. Getting negation right 95% of the time sounds great until you realize that 5% error rate on a 3000-patient panel means dozens of patients with incorrectly flagged conditions. And the failure mode is asymmetric: a false positive (adding a negated condition to the active list) erodes clinician trust in the system much faster than a false negative (missing a real problem) does.

The reconciliation logic is where the real engineering challenge hides. SNOMED concept hierarchies are complex, and determining whether two codes represent "the same problem at different specificity levels" versus "genuinely different conditions" requires clinical ontology reasoning that's harder than it looks. "Type 2 diabetes" and "Type 2 diabetes with diabetic nephropathy" are in the same hierarchy, but one is a specificity upgrade of the other. "Type 2 diabetes" and "diabetic foot ulcer" are related but are genuinely separate problem list entries.

What surprised me most: the section detection step (which seems like simple string matching) has an outsized impact on overall accuracy. Notes without clear section headers, or with non-standard formatting, degrade assertion classification significantly. The NER engine extracts the condition fine; it's the "does this patient actually have it" determination that suffers when section context is missing.

One more thing. Problem list extraction is inherently a clinician-in-the-loop workflow. You're generating recommendations, not making changes. The moment you auto-add conditions to a problem list without physician review, you've crossed from decision support into autonomous clinical documentation. That's a different regulatory and liability landscape entirely. Keep the human in the loop. Frame your pipeline as "here are problems you might want to add" not "I've updated the problem list for you."

---

## Related Recipes

- **Recipe 8.4 (Medication Extraction and Normalization):** Uses the same Comprehend Medical extraction pattern but targets medications instead of conditions. Shares section detection and assertion classification concepts.
- **Recipe 8.8 (Clinical Assertion Classification):** Dives deep into assertion detection as a standalone capability. Use that recipe's patterns to build a more sophisticated assertion engine if the built-in traits are insufficient.
- **Recipe 8.3 (ICD-10 Code Suggestion):** Focuses on coding workflow integration. Combine with this recipe to generate ICD-10 suggestions from problem list extractions for HCC coding.
- **Recipe 13.3 (ICD/CPT Hierarchy Navigation):** Provides the ontology navigation needed for the specificity upgrade logic in reconciliation.

---

## Tags

`nlp` · `ner` · `clinical-nlp` · `problem-list` · `comprehend-medical` · `snomed` · `icd-10` · `assertion-detection` · `negation` · `reconciliation` · `medium` · `lambda` · `dynamodb` · `hipaa`

---

*← [Recipe 8.4: Medication Extraction and Normalization](chapter08.04-medication-extraction-normalization) · [Chapter 8 Index](chapter08-preface) · [Next: Recipe 8.6: SDOH Extraction →](chapter08.06-sdoh-extraction)*
