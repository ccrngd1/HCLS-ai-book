# Recipe 1.3: Lab Requisition Form Extraction 🔶

**Complexity:** Moderate · **Phase:** Phase 2 · **Estimated Cost:** ~$0.10-0.15 per form

---

## The Problem

A physician finishes a visit with a patient who has Type 2 diabetes. She orders a hemoglobin A1c, a comprehensive metabolic panel, and a lipid panel. She scribbles the diagnosis on the lab req as "T2DM, HTN" and faxes it to the lab. The lab fax machine spits out a thermal print. Someone scans it. Another person types it into the ordering system. A third person looks up the ICD-10 codes for "T2DM" and "HTN" and keys them in. A fourth person double-checks the test panel codes for billing.

This is the pipeline for a routine lab order in 2026. Not in some underresourced rural practice. In a large integrated health system with dedicated billing staff.

The waste is not just the labor. It's the error chain. "T2DM" gets coded as E11.9 by one coder and E11.65 by another. "HTN" maps to I10, but only if the coder recognizes it as an abbreviation for essential hypertension rather than, say, a note about medication history. An HbA1c ordered without a diabetes diagnosis code gets flagged for medical necessity review and sits in a queue for three days. The lab doesn't run it. The physician gets a call. The patient's medication adjustment is delayed.

Lab requisition forms are a masterclass in how healthcare handles critical clinical information: on paper, abbreviated, handwritten in margins, and faxed at 96 dpi. The information is all there. Getting a computer to turn "T2DM, lipid panel Q3M per Dr. Chen" into machine-actionable structured data, with validated diagnosis codes that justify the ordered tests, is a different problem category from reading an insurance card.

This is where pure document extraction hits its ceiling, and clinical NLP enters the picture.

---

## The Technology

### What Textract Got Us, and Where It Stops

The previous two recipes established a pattern. An image or PDF arrives. Textract reads the layout, identifies key-value pairs, extracts table rows, detects checkbox selections. You get a structured JSON record with field values and confidence scores. It's powerful and it works well.

But Textract is a document structure tool. It can tell you that the field labeled "Diagnosis" contains the text "Type 2 diabetes mellitus with hyperglycemia, hypertension." It cannot tell you that this text maps to ICD-10-CM codes E11.65 and I10, or that E11.65 supports an HbA1c order under Medicare LCD L35166 but not a lipid panel unless hyperlipidemia is also coded.

Knowing what a string of words means in a clinical context is a different kind of problem. That's the domain of clinical natural language processing.

### Clinical NLP: Understanding Medical Text

Natural language processing (NLP) is the branch of machine learning that deals with text. The core tasks relevant to clinical documents are named entity recognition (extracting specific types of information from free text), entity normalization (linking extracted text to standard identifiers in a coding system), and relation extraction (identifying how entities relate to each other).

Clinical NLP adds a specialized dimension to all three. Medical text is not like newspaper text or legal text or customer reviews. It uses abbreviations that would stump any general-purpose model: "s/p CABG c/b afib, on warfarin per cards" reads, to a trained clinical model, as "status post coronary artery bypass graft complicated by atrial fibrillation, on warfarin per cardiology." To a general NLP model, it reads as gibberish. The training data matters enormously.

Clinical NLP systems are trained on medical corpora: physician notes, radiology reports, discharge summaries, clinical trial records. The models learn that "SOB" means shortness of breath, that "h/o" means history of, that "DM2" and "T2DM" and "Type 2 diabetes" are the same concept, and that the sentence context distinguishes a patient with diabetes from a patient whose family member has diabetes. These are not problems you solve with a regex pattern or a lookup table. They require a model that has internalized the implicit structure of clinical language.

The output of clinical NER is a set of entities, each with a category (diagnosis, medication, procedure, anatomy), a text span (the original words from the document), a confidence score, and a set of semantic traits (is this a negation? A historical finding? Something found in a family member rather than the patient?). The traits matter: "no chest pain" and "chest pain" should not both result in a chest pain diagnosis code.

### ICD-10-CM: The Coding System

ICD-10-CM stands for International Classification of Diseases, Tenth Revision, Clinical Modification. It's a hierarchical coding system maintained by the World Health Organization, with the United States version maintained by CMS and the CDC. Every diagnostic concept in medicine has one or more ICD-10-CM codes. There are roughly 70,000 of them.

The hierarchy is meaningful. E11 is the parent code for Type 2 diabetes mellitus. E11.9 is Type 2 diabetes without complications. E11.65 is Type 2 diabetes with hyperglycemia. E11.641 is Type 2 diabetes with hypoglycemia with coma. The specificity increases as the decimal expands. Payers care about this specificity: a diagnosis of E11.9 supports certain lab orders; E11.65 supports a broader set.

Going from free text to ICD-10-CM code is called "ICD-10 inference" or "diagnosis coding." Doing it manually requires a trained medical coder. Doing it automatically requires a model trained on clinical text that has learned the mapping from clinical language to the code hierarchy. The models are good at common diagnoses (diabetes, hypertension, heart failure, asthma) because the training data is dense with those. They are much less reliable on rare or highly specific diagnoses because the training examples are sparse.

Handwritten ICD-10 codes are a specific subproblem worth calling out. Physicians who have been doing this for years often write the code directly: "E11.9, I10." That's actually easier to handle than free text, but only if the OCR reads it correctly. Handwritten ICD-10 codes get confused for other things: "I10" can look like "110" when handwritten at speed. A capital I, a lowercase l, and the numeral 1 are visually very similar in most handwriting. After OCR, "I10" may arrive as "l10" or "110." The clinical NLP step needs to be downstream of a solid OCR pass, and the confidence scores from both steps need to travel together.

### CPT Codes: The Procedure Vocabulary

CPT stands for Current Procedural Terminology. It's the coding system for medical procedures and services, maintained by the American Medical Association. Every lab test has a CPT code. An HbA1c is 83036. A CBC with differential is 85025. A comprehensive metabolic panel is 80053.

On a lab requisition, the ordered tests are usually identified by name or abbreviation, not by code. The lab's ordering system maps the name to the CPT code for billing. That mapping is the CPT lookup table problem, and it's messier than it sounds. "CBC w/ diff," "Complete Blood Count with Differential," "CBC w/differential," and "CBCD" all mean 85025. The alias space is large. The test catalog for a major reference lab like Quest or LabCorp has thousands of entries. The lookup table for the most common 50 tests covers the vast majority of volume, but the long tail is real.

The good news is that CPT mapping, unlike ICD-10 inference, doesn't require a neural network. It's fundamentally a fuzzy matching problem. A well-maintained lookup table with normalized test names and known abbreviations, combined with a low-threshold fuzzy match, handles most cases correctly. What it doesn't handle: new test names the lab introduces after you last updated the table, custom panel names ("cardiometabolic panel" means different things at different labs), and tests written in highly abbreviated form by physicians who assume everyone knows what "homocys" means.

### Medical Necessity: The Cross-Reference Problem

Medical necessity is the requirement that ordered tests be justified by appropriate diagnoses. Payers won't reimburse a PSA test ordered without a prostate-specific diagnosis or screening-appropriate indication. They won't reimburse an HbA1c for a patient with no diabetes-related codes.

Checking medical necessity at the point of extraction, before the order reaches the lab or the payer, is genuinely valuable. It doesn't replace the utilization management system. But it catches obvious gaps early, when a quick phone call to the ordering physician is still possible and the patient hasn't already gone to the lab.

The data structure for medical necessity validation is a mapping from diagnosis code prefixes to the set of CPT codes that are considered appropriate. CMS publishes Local Coverage Determinations (LCDs) that define this mapping for Medicare. Commercial payers publish their own policies. The mapping is large, periodically updated, and payer-specific. A simplified in-recipe version covers common cases. A production version integrates with a medical policy rules engine.

### The Two-Stage Pipeline Pattern

The architecture that emerges from all of this is a two-stage pipeline. The first stage is structural extraction: get the form layout, identify the fields, extract the text. The second stage is semantic interpretation: understand what the extracted text means in clinical terms.

This separation is intentional. Structural extraction and clinical NLP are different problems that require different models trained on different data. Trying to combine them into a single pass produces a system that's mediocre at both. Keeping them separate means each stage can be improved independently, and the boundary between them (the raw extracted text) is a natural checkpoint for debugging and quality monitoring.

The two stages also operate at different speeds and costs. Structural extraction (the Textract job) runs once per document and takes 5 to 15 seconds. Clinical NLP (Comprehend Medical calls) runs on text snippets and is fast enough to do synchronously. The natural implementation is to run the async Textract job, wait for completion, and then make the Comprehend Medical calls within the same processing Lambda.

```text
[Ingest] → [Submit Textract Job] → [Await Completion] → [Parse Structure]
                                                               ↓
                                                    [Extract Diagnosis Text]
                                                               ↓
                                                    [Clinical NLP: ICD-10 Inference]
                                                               ↓
                                                    [Clinical NLP: Entity Extraction]
                                                               ↓
                                                    [CPT Lookup: Ordered Tests]
                                                               ↓
                                                    [Medical Necessity Check]
                                                               ↓
                                                         [Assemble & Store]
```

Both stages produce confidence scores. Both feed into the same confidence gate. A high-confidence Textract extraction of a diagnosis field followed by a low-confidence ICD-10 inference is a different situation than a low-confidence OCR read. The composite confidence score (the minimum of Textract confidence and Comprehend Medical confidence for a given field) is what drives the review queue.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter01.03-architecture). The Python example is linked from there.

## The Honest Take

This recipe is where the cookbook shifts from "impressive party trick" to "genuinely difficult problem."

The Textract pipeline from Recipes 1.1 and 1.2 is almost mechanical to get right once you understand the pattern. The Comprehend Medical layer introduces a different kind of uncertainty. OCR confidence is about whether a character was read correctly. NLP confidence is about whether the model's interpretation of the text is correct. These are different failure modes and they require different review processes. A coder reviewing a low-confidence ICD-10 suggestion needs clinical knowledge, not just good eyesight.

The thing that surprised me most when testing this: the medical necessity check flags more orders than you expect on a first pass. It's not because the orders are clinically inappropriate. It's because the mapping table is incomplete. Physicians often write shorthand diagnoses ("lipids" instead of "hyperlipidemia") that the ICD-10 inference maps to a code prefix not in your table. Before concluding that a medical necessity flag means the order is problematic, audit your table coverage first.

The ICD-10 code specificity issue is a constant low-grade frustration. Getting E11.9 when you need E11.65 doesn't mean the inference is wrong about the diagnosis category. It means the model was appropriately conservative when the clinical text didn't clearly specify complications. In many payer workflows, E11.9 is fine. In some, it kicks off an additional review step. Know your payer's policies before you decide whether to accept top-ranked inferences at face value or route them through coder review regardless of confidence.

The CPT lookup table is honestly the most maintenance-intensive part of this pipeline. It doesn't feel glamorous. It is critical. A missed CPT mapping means a test goes unvalidated, potentially unbilled, potentially uncovered. The mapping table should live in a configuration system with change tracking, not hardcoded in a Lambda function.

---

## Related Recipes

- **Recipe 1.1 (Insurance Card Scanning):** The single-page synchronous OCR foundation. Start here if you're new to Textract.
- **Recipe 1.2 (Patient Intake Form Digitization):** The async multi-page pattern and checkbox parsing this recipe builds on directly. Read it before this one.
- **Recipe 1.6 (Handwritten Clinical Note Digitization):** The tiered confidence pipeline and Amazon A2I human review queue that the flagged fields and low-confidence ICD-10 inferences from this recipe feed into.
- **Recipe 5.2 (NLP: ICD-10 Code Suggestion):** A deep dive on ICD-10 inference for complex, multi-condition clinical text. Goes substantially further than the `InferICD10CM` approach here, including custom model fine-tuning for specific specialties.

---

## Tags

`document-intelligence` · `ocr` · `nlp` · `textract` · `comprehend-medical` · `icd-10` · `cpt` · `lab-requisition` · `clinical-nlp` · `medical-coding` · `medical-necessity` · `two-stage-pipeline` · `moderate` · `phase-2` · `lambda` · `s3` · `dynamodb` · `sns` · `hipaa`

---

*← [Chapter 1 Index](chapter01-preface) · [← Recipe 1.2: Patient Intake Form Digitization](chapter01.02-patient-intake-digitization) · [Next: Recipe 1.4 - Prior Authorization Document Processing →](chapter01.04-prior-auth-document-processing)*
