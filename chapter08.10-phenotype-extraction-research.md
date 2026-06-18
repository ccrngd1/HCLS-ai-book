# Recipe 8.10: Phenotype Extraction for Research

**Complexity:** Complex · **Phase:** Research Infrastructure · **Estimated Cost:** ~$8-15 per patient record set (full NLP processing)

---

## The Problem

A researcher at an academic medical center has a hypothesis: patients with treatment-resistant depression who also have chronic inflammation markers (elevated CRP, IL-6) respond better to a specific adjunctive therapy. To test this hypothesis, they need a cohort of patients who meet three criteria: (1) diagnosed with major depressive disorder, (2) failed at least two adequate antidepressant trials, and (3) have documented inflammatory biomarkers above a specific threshold.

The EHR has structured diagnosis codes and lab values. Easy, right? Not even close.

The diagnosis code (F33.2, "Major depressive disorder, recurrent, severe without psychotic features") gets you a starting pool, but it misses patients coded differently (F32.2 for single episode, or even "adjustment disorder" in early documentation that was later reclassified). The "failed two adequate trials" criterion? That lives exclusively in free text. Progress notes, psychiatry consults, medication reconciliation narratives. A note might say "patient has not responded to adequate trials of sertraline 200mg and venlafaxine 225mg." Or it might say "tried two SSRIs without benefit." Or "Prozac didn't work. Effexor didn't work. Trying Wellbutrin now." Or it might be distributed across three separate visit notes spanning six months, each one mentioning a single failed medication.

This scenario is the norm in clinical research. The information you need to identify a study cohort is scattered across unstructured documentation, encoded in clinical shorthand, distributed across time, and expressed in a hundred different ways by a hundred different clinicians.

The cost of doing this manually is staggering. Chart review (a human reading through every potentially qualifying patient's records) runs about 15-30 minutes per patient. For a study requiring 500 subjects from a pool of 50,000 candidates, that's potentially months of research coordinator time just to identify who qualifies. And the result is still inconsistent: different reviewers apply criteria differently, inter-rater reliability is often below 0.8 kappa, and the process is completely non-reproducible.

Phenotype extraction is the NLP-powered answer to this problem. It's the automated identification of patients who meet a complex clinical definition (a "phenotype") by analyzing both structured data and unstructured text in the EHR. When it works, it takes a process that took months of chart review and compresses it to hours of compute time, with complete reproducibility and explicit documentation of how every patient was classified.

When it doesn't work (and this is the honest part), it fails silently. A missed negation means a patient who was ruled out for a condition gets classified as having it. An ambiguous temporal reference means a patient with a resolved historical condition gets flagged as currently meeting criteria. The research built on a contaminated cohort proceeds to publication, and nobody discovers the problem until a replication attempt fails.

The stakes are real. The difficulty is real. And the need is enormous: observational research, pragmatic trials, quality improvement, precision medicine cohort building, and biobank linkage all depend on reliable phenotype extraction from clinical text.

---

## The Technology: Computational Phenotyping from Unstructured Text

### What Is Phenotype Extraction?

A clinical phenotype, in the research computing sense, is a computable definition of a patient characteristic. It's not just "does this patient have diabetes?" but a precise specification: "Type 2 diabetes, defined as two or more outpatient encounters with ICD-10 codes E11.x, OR one inpatient encounter with E11.x, OR HbA1c >= 6.5% on two measurements at least 90 days apart, OR documented treatment with metformin for glucose management (not PCOS), EXCLUDING patients with cystic fibrosis-related diabetes or steroid-induced hyperglycemia."

That definition mixes structured data (codes, labs) with unstructured text requirements (confirming the metformin indication, excluding specific etiologies). The structured part is a database query. The unstructured part is an NLP problem.

Phenotype extraction is the NLP layer that resolves the unstructured text components of a phenotype definition. It transforms free-text clinical documentation into computable assertions: "this patient has documentation of failing two antidepressant trials," or "this patient's chest pain is described as non-cardiac in origin," or "this patient has family history of early-onset colorectal cancer."

The output feeds into a phenotype algorithm that combines structured and unstructured evidence to produce a final patient classification: phenotype-positive, phenotype-negative, or indeterminate.

### The Components of a Phenotype Extraction Pipeline

Building a phenotype extraction system requires stacking several NLP capabilities together. None of them is individually new (most appear in earlier recipes in this chapter), but the combination and the precision requirements are what make phenotyping complex.

**Named entity recognition (NER).** Identify clinical concepts in text: conditions, medications, procedures, lab values, symptoms. This is the foundation. If you can't find the relevant mentions, nothing downstream works. For phenotyping, you often need entities that go beyond standard medical NER: "adequate trial" (a qualitative assessment), "failed" or "non-response" (treatment outcome assertions), "family history of" (a framing modifier that changes who the entity applies to).

**Assertion classification.** Every extracted entity needs an assertion status. Is this condition present, absent, possible, historical, or attributed to someone else (family history)? Recipe 8.8 covers this in depth. For phenotyping, assertion accuracy is critical: a negated condition ("no evidence of diabetes") getting classified as present creates a false positive in your cohort. At research-grade precision requirements (often 95%+ positive predictive value), even small assertion error rates become unacceptable.

**Attribute extraction.** Beyond recognizing that a medication is mentioned, you need its dose, duration, frequency, and route. Beyond recognizing a lab value, you need the numeric result and the reference range. Beyond recognizing a diagnosis, you need its severity, chronicity, and etiology. These attributes are what distinguish "tried sertraline" from "adequate trial of sertraline 200mg for 8 weeks."

**Temporal anchoring.** When did this happen? Is the documented condition current or historical? Did the two antidepressant failures occur sequentially (required by the phenotype definition) or concurrently? Recipe 8.9 covers temporal extraction. For phenotyping, you need temporal reasoning sufficient to determine whether events meet the time-based criteria of the phenotype definition (e.g., "lab values at least 90 days apart").

**Negation and context detection.** This overlaps with assertion classification but deserves its own mention because it's the single biggest source of phenotyping errors. "Patient denies chest pain." "No history of MI." "Father had colon cancer" (family, not patient). "Ruled out for pulmonary embolism." "Concern for possible lupus" (hedged, not confirmed). Each of these must be handled correctly, or the phenotype classification is wrong.

**Section awareness.** The same phrase means different things in different note sections. "Diabetes" in the Problem List means the patient has it. "Diabetes" in the Family History section means a relative has it. "Diabetes" in the Assessment section might be "we are evaluating for diabetes" (not confirmed). Section-aware processing is non-negotiable for phenotyping accuracy.

**Cross-document aggregation.** A phenotype is rarely determinable from a single note. You might need evidence from across the patient's longitudinal record: a diagnosis confirmed in one note, a medication trial documented in another, a lab value from a third encounter. The aggregation logic (how to combine evidence across documents) is where the phenotype algorithm lives, and it's where most of the domain expertise is encoded.

### Why Phenotyping Is Hard (Beyond the NLP)

<!-- TODO (TechWriter): Expert review VOC-1 (MEDIUM). This subsection partially overlaps with the Problem section (inter-rater reliability, ambiguity). Consider consolidating overlapping points and targeting ~20% reduction. Move unique points (portability, prevalence, reproducibility) into a shorter list. -->

The NLP components above are table stakes. The real difficulty lives in the layers surrounding them:

**Phenotype definitions are ambiguous.** Research protocols define inclusion criteria in clinical language, not computational language. "Adequate trial" of an antidepressant could mean different things: the APA says 4-6 weeks at therapeutic dose, but some researchers use 8 weeks, and "therapeutic dose" varies by medication. Your system needs these definitions operationalized into explicit rules, and different research teams might operationalize them differently.

**Gold standard annotation is expensive and contentious.** To train or validate a phenotype extraction system, you need gold-standard labels: patients who definitely meet the phenotype definition, and patients who definitely don't. Creating these labels requires clinician chart review, and clinicians disagree. Inter-annotator agreement for complex phenotypes is often kappa 0.7-0.85. When your annotators disagree on 15-30% of cases, what is "correct" becomes philosophically murky. Your system is being evaluated against an imperfect standard.

**Phenotype portability.** A phenotype algorithm developed at one institution may not work at another. Different EHR systems, different documentation styles, different provider populations, different patient demographics, different abbreviation conventions. "T2DM" is universal, but "NIDDM" (non-insulin-dependent diabetes mellitus, an older term) might appear in notes from a health system that still has clinicians trained in the 1980s. The eMERGE Network (a multi-site genomics consortium) has documented extensively how phenotype algorithms require site-specific tuning.

**Prevalence and class imbalance.** For rare phenotypes (a specific genetic condition, a particular drug reaction), the vast majority of patients in your candidate pool won't qualify. If 0.5% of your candidates have the phenotype, even a 99% specific system will have a poor positive predictive value. The math is unforgiving for rare phenotypes, and the solution (higher precision at the cost of recall) means you miss real cases.

**Reproducibility requirements.** Research demands reproducibility: another team should be able to take your phenotype algorithm, run it on their data, and get consistent results. This means every decision in the pipeline needs to be documented, deterministic, and versioned. Which NLP models were used? What thresholds were applied? How were conflicts resolved? What was the training data? Phenotyping is as much a data provenance problem as it is an NLP problem.

### Where the Field Is in 2026

The landscape for computational phenotyping has matured significantly:

**Standardized phenotype libraries.** The PheKB (Phenotype Knowledge Base) from eMERGE provides validated, published phenotype algorithms for hundreds of conditions. These are the reference implementations. They mix structured data queries with manual chart review criteria that are candidates for NLP automation.

**Clinical NLP toolkits.** Apache cTAKES, MedSpaCy, and commercial clinical NLP services (including cloud-based offerings) provide the foundational entity extraction, negation detection, and assertion classification needed for phenotyping. None of them solve phenotyping end-to-end, but they provide the building blocks.

**Large language models.** LLMs can now perform zero-shot and few-shot phenotype classification with impressive accuracy on well-defined criteria. For simple phenotypes, you can often describe the criteria in a prompt and get reasonable patient-level classifications from clinical notes. The challenge is that "reasonable" (85-90% accuracy) isn't always "research-grade" (95%+ PPV), and the non-deterministic nature of LLM outputs creates reproducibility concerns.

**Hybrid approaches dominate.** The current best practice is a hybrid: rule-based extraction for structured and well-patterned data, ML-based NLP for unstructured text, and a deterministic combination algorithm that merges evidence using explicit, documented logic. This gives you the reproducibility of rules with the flexibility of ML.

### The General Architecture Pattern

At a conceptual level, phenotype extraction follows this pipeline:

```text
[Phenotype Definition] → [Criteria Decomposition] → [Per-Criterion Extraction] → [Evidence Aggregation] → [Classification] → [Validation]
```

**Phenotype Definition:** The clinical specification of what you're looking for. Usually comes from a research protocol, published algorithm, or clinical expert.

**Criteria Decomposition:** Break the definition into individual, independently evaluable criteria. Each criterion becomes a separate extraction target. Some resolve against structured data (ICD codes, lab values). Others require NLP against unstructured text.

**Per-Criterion Extraction:** For each text-based criterion, run the appropriate NLP pipeline: entity extraction, assertion classification, attribute extraction, temporal reasoning. The output is per-document evidence for or against each criterion.

**Evidence Aggregation:** Combine per-document evidence across the patient's longitudinal record. Apply aggregation rules: how many positive mentions are required? Does a single negation override multiple positives? How do you handle conflicting evidence across notes?

**Classification:** Apply the phenotype algorithm logic to produce a final patient-level classification. Typically three classes: definite (meets all criteria with high confidence), probable (partial evidence), and excluded (evidence against).

**Validation:** Compare automated classifications against manual chart review on a sample. Calculate positive predictive value, sensitivity, specificity. Iterate on extraction rules and thresholds until validation metrics meet research requirements.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter08.10-architecture). The Python example is linked from there.

## The Honest Take

Phenotype extraction is one of those problems that seems like it should be solved by now. The individual NLP components are mature. Entity extraction works. Negation detection works. Assertion classification works. But the moment you string them together into a phenotype algorithm and demand research-grade precision, the error rates compound in ways that are genuinely humbling.

Here's what surprised me: the NLP isn't actually the bottleneck most of the time. The bottleneck is the phenotype definition itself. Researchers often can't precisely articulate what they mean by their inclusion criteria until they see edge cases. "Adequate antidepressant trial" turns out to have five different operational definitions depending on which clinical guideline you follow. Your system can be technically perfect and still produce cohorts that the research team disputes, because the definition was ambiguous from the start.

The validation step is where reality hits. You'll build the pipeline, run it on 1,000 patients, and then a research coordinator manually reviews 100 of them. You'll find that 8 of your "DEFINITE" classifications are actually wrong. Not because the NLP failed, but because the clinical note said "tried sertraline briefly" and your system counted that as an adequate trial because it matched the medication name and a treatment outcome phrase. "Briefly" should have disqualified it. Now you're adding rules for adequacy modifiers, and you realize you need a dozen more.

The thing I'd do differently: invest heavily in the phenotype definition and validation loop before building any infrastructure. Paper-prototype your criteria. Have two clinicians independently classify 50 patients manually. Measure their agreement. If they disagree on 20% of cases, no automated system will do better, because you don't have a clear definition of "correct." Fix the definition first, then automate it.

The cost model also catches people off guard. Cloud NLP services charge per character, and clinical notes are verbose. A single patient with 40 notes averaging 3,000 characters each is 120,000 characters through the entity extraction API. At typical per-character pricing, that's $8-15 per patient just for extraction. For a 50,000-patient candidate pool, you're looking at hundreds of thousands of dollars in NLP costs alone before you've even classified anyone. In practice, you pre-filter heavily using structured data (ICD codes, medication lists) to narrow the candidate pool before running the expensive NLP. That pre-filter step isn't optional at scale.

---

## Related Recipes

- **Recipe 8.5 (Problem List Extraction):** Provides the entity extraction foundation for identifying diagnoses in notes
- **Recipe 8.8 (Clinical Assertion Classification):** Handles the present/absent/possible/family determination critical for phenotype accuracy
- **Recipe 8.9 (Temporal Relationship Extraction):** Enables time-based criteria like "sequential medication trials" or "lab values 90 days apart"
- **Recipe 8.4 (Medication Extraction and Normalization):** Extracts medication mentions with dose and duration attributes needed for treatment adequacy
- **Recipe 6.7 (Clinical Trial Patient Matching):** Downstream consumer of phenotype classifications for trial recruitment

---

## Tags

`nlp` · `phenotyping` · `research` · `cohort-identification` · `comprehend-medical` · `step-functions` · `complex` · `entity-extraction` · `assertion-classification` · `clinical-research` · `hipaa` · `reproducibility`

---

*← [Recipe 8.9: Temporal Relationship Extraction](chapter08.09-temporal-relationship-extraction) · [Chapter 8 Index](chapter08-preface) · [Next: Chapter 9 - Computer Vision →](chapter09-preface)*
