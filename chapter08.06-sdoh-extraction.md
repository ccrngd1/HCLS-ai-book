# Recipe 8.6: Social Determinants of Health (SDOH) Extraction

**Complexity:** Medium-Complex · **Phase:** Production · **Estimated Cost:** ~$0.02-0.08 per note

---

## The Problem

A 62-year-old patient with poorly controlled diabetes shows up to their endocrinologist every three months, gets their A1c checked, gets a medication adjustment, and goes home. The A1c never improves. The care team adjusts insulin, adds a GLP-1, tries a CGM. Nothing sticks. What nobody has surfaced from the chart is a social worker note from eight months ago mentioning the patient lives alone, lost their job, and has been skipping meals because they can't afford food consistently.

This isn't a rare scenario. It's the default state of clinical documentation. Social determinants of health (SDOH), the non-medical factors that influence health outcomes (housing, food security, employment, transportation, social isolation, financial strain), are buried in free-text notes across the chart. They show up in social work assessments, nursing intake notes, discharge summaries, and sometimes as a single sentence in a progress note: "Patient reports difficulty affording medications." That sentence is clinically explosive. It explains treatment failure, predicts readmission risk, and should trigger a resource referral. But it sits in paragraph four of a seven-page note, invisible to the prescribing physician, the care manager, and the risk stratification algorithm.

The structured data problem is clear: SDOH information lives in free text because there hasn't been a standard way to capture it structurally until recently. ICD-10 introduced Z-codes for SDOH (Z55-Z65 range: education, employment, housing, economic circumstances, social environment), but they're massively under-coded. Studies consistently show that fewer than 2% of encounters that document social needs in notes have corresponding Z-codes on the claim. The information exists. It's just trapped in prose.

Extracting SDOH from clinical text means building a system that can read thousands of notes, find the sparse mentions of social factors, classify them into meaningful categories, determine whether they represent an active need or a resolved one, and surface that information where it can drive interventions. The payoff is enormous: population health programs can target outreach, care managers can prioritize caseloads, and risk models can incorporate the single strongest predictor of health outcomes that most systems currently ignore.

Let's talk about why this is harder than it sounds.

---

## The Technology: Extracting Social Context from Clinical Language

### What Makes SDOH Different from Medical NLP

Most clinical NLP focuses on extracting medical concepts: diagnoses, medications, procedures, lab values. These have well-defined terminologies (ICD-10, RxNorm, CPT, LOINC), relatively consistent phrasing, and decades of annotated training data. "The patient has type 2 diabetes" is easy to detect. The concept is explicit, the terminology is standardized, and the assertion is clear.

SDOH extraction is fundamentally different, and it's harder for several reasons that compound each other.

**Sparse mentions.** In a typical clinical note, medical concepts appear densely. A single progress note might mention five diagnoses, three medications, and two procedures. SDOH mentions are sparse: maybe one sentence in a five-page note, or maybe nothing at all. Most notes contain zero SDOH information. Your system will process thousands of notes to find hundreds of relevant mentions. The signal-to-noise ratio is brutal.

**Inconsistent language.** There's no standard way to document homelessness. A social worker might write "patient is currently unhoused," while a physician writes "lives in shelter," a nurse writes "no stable housing," and a discharge planner writes "disposition complicated by housing instability." All mean the same thing. Unlike medication names (which have finite brand/generic mappings), social determinant language is open-ended natural language with no controlled vocabulary in practice.

**Implicit mentions.** The hardest SDOH information isn't stated directly. "Patient missed three appointments last month" doesn't say "transportation barrier," but transportation is a common reason. "Patient reports not filling prescription" doesn't say "financial hardship," but cost is the most common barrier. Extracting these implicit mentions requires inference, and inference means either very sophisticated models or accepting that you'll miss a significant portion of cases.

**Context sensitivity.** "Patient lives with daughter" is positive social support. "Patient lives with daughter who is also disabled" is a different story entirely. "Patient was homeless" (past tense) is very different from "patient is homeless" (active need). The same phrase in a family history section means something different than in the social history section. Context determines meaning, and context in clinical text is often ambiguous.

**Documentation variation by role.** Social workers write detailed assessments of housing, food access, and support systems. Physicians often compress the same information into a single line: "Social: lives alone, retired." Nursing intake forms ask structured screening questions. Each documentation style requires different extraction approaches.

### The NLP Pipeline for SDOH

The extraction pipeline has several stages, each with its own challenges:

**Section detection.** Clinical notes have implicit structure: social history, family history, review of systems, assessment and plan. SDOH information concentrates in the social history section (if one exists), but also appears in assessment/plan sections ("refer to food bank"), discharge summaries ("patient needs home health due to lack of caregiver"), and nursing notes. Section detection helps you focus attention but must not become a filter that drops relevant mentions in unexpected locations.

**Named entity recognition (NER) for social concepts.** This is the core extraction step: identifying spans of text that describe social determinants. Unlike medical NER (where you're looking for drug names or diagnosis codes), SDOH NER must recognize longer, more complex phrases. "Lives in a shelter" is a housing entity. "Can't afford insulin" is a financial strain entity. "No family nearby" is a social isolation entity. The entity boundaries are less crisp than medical entities, and the variety of surface forms is much larger.

**Category classification.** Once you've identified an SDOH mention, you need to classify it into a domain. The most common taxonomies draw from the Gravity Project's SDOH Clinical Care standards or the National Academy of Medicine's categories:

- Housing instability and homelessness
- Food insecurity
- Transportation barriers
- Financial strain and employment
- Social isolation and support
- Education and health literacy
- Interpersonal safety (domestic violence, elder abuse)
- Utility insecurity

Each domain has its own vocabulary patterns and contextual cues.

**Assertion classification.** Is this an active need, a resolved one, a risk factor, or a resource that's already connected? "Patient was referred to food bank last month and reports adequate intake now" contains both a historical need (food insecurity) and a current resolution. This temporal and status reasoning is critical for operationalizing the output. Surfacing a "resolved" need as "active" wastes care manager time and erodes trust in the system.

**Normalization.** Mapping extracted mentions to standard codes (ICD-10 Z-codes, LOINC social determinant panels, SNOMED social context concepts) enables interoperability and population-level analytics. This step bridges the gap between free-text extraction and structured data that EHRs and analytics platforms can consume.

### The State of the Art

SDOH NLP has matured significantly since 2020. Several approaches coexist:

**Rule-based systems.** Pattern matching with dictionaries of SDOH-related terms. Fast, interpretable, and surprisingly effective for high-prevalence categories like housing and food. Brittle on implicit mentions and novel phrasing. Good for a first pass; insufficient alone.

**Traditional ML classifiers.** Train a classifier (logistic regression, SVM, or gradient-boosted trees) on labeled sentences or note sections. Features include bag-of-words, word embeddings, and section headers. Requires annotated training data, which is expensive to create for SDOH because the mention density is so low (annotators read many pages to label a few sentences).

**Pre-trained clinical language models.** Fine-tune models like ClinicalBERT, BioBERT, or PubMedBERT on SDOH-annotated data. These models understand clinical language structure and can generalize better from smaller training sets. The current best-performing approach for research benchmarks.

**Hybrid systems.** Combine rule-based high-precision extraction (for common, explicit patterns) with ML-based extraction (for implicit and unusual mentions). The rules catch "patient is homeless" reliably; the model catches "patient has been staying with friends since the eviction."

The honest reality: even the best systems achieve 70-85% F1 scores on SDOH extraction, depending on the category and dataset. Housing and food are easier (more explicit language). Transportation and social isolation are harder (more implicit). Financial strain falls somewhere in between. These numbers matter because they set expectations for what your production system will actually deliver.

### The General Architecture Pattern

```text
[Clinical Notes] → [Section Detection] → [SDOH Entity Recognition] → [Category + Assertion Classification] → [Code Normalization] → [Structured Store] → [Downstream Consumers]
```

**Clinical notes ingestion.** Notes arrive from the EHR, either in real-time (via HL7/FHIR event streams) or in batch (nightly extracts). The system must handle multiple note types: social work assessments, progress notes, nursing intake, discharge summaries. Each type has different SDOH density and documentation patterns.

**Section detection.** Identify the note structure and tag sections. Weight processing toward social history and assessment/plan sections, but don't exclude other sections entirely. Some systems apply a quick "relevance filter" (does this note even mention social concepts?) before full extraction, to reduce processing volume.

**Entity recognition.** Identify text spans that describe social determinants. This is the core NLP step. Output: a list of text spans with start/end positions, each flagged as a potential SDOH mention.

**Classification.** For each identified mention, classify the domain (housing, food, transportation, etc.) and the assertion status (active need, resolved, at risk, resource connected). Some systems merge entity recognition and classification into a single model pass; others separate them for interpretability.

**Normalization.** Map each classified mention to standard terminology codes. This enables structured queries ("show me all patients with active food insecurity") and populates structured data fields that EHR systems and analytics platforms can consume.

**Storage and indexing.** Structured extraction results go into a patient-level store, indexed by patient, date, category, and status. This store feeds downstream consumers: care management platforms, risk stratification engines, population health dashboards, and quality reporting systems.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter08.06-architecture). The Python example is linked from there.

## The Honest Take

SDOH extraction is one of those problems that looks tractable until you start counting what you're missing. The explicit mentions (patient reports food insecurity, patient is homeless) are genuinely easy to extract. You'll get 85-90% of those with a well-trained classifier. That's the part that demos well.

The hard part is everything else. The implicit mentions are where the real clinical value lives, and they're where NLP systems struggle most. "Patient didn't fill the prescription" is probably financial strain. "Patient missed follow-up" is probably transportation or childcare. "Patient's A1c worsening despite education" might be food insecurity. These inferences require clinical reasoning that goes beyond text pattern matching, and current systems catch maybe half of them.

The assertion problem is sneakier than you'd expect. "Was referred to food bank" doesn't mean the patient went. "Has housing voucher" doesn't mean they've found housing. "Daughter helps with meals" sounds like resolution until you learn the daughter lives two hours away and visits monthly. The gap between "documented" and "resolved" is where care coordination lives, and it's hard to capture from text alone.

The training data problem is real. Public datasets (MIMIC, i2b2/n2c2 shared tasks) are useful for initial model development, but they don't represent your patient population's documentation patterns. Your social workers document differently than academic medical center social workers. Your community health center notes look different than tertiary care notes. Plan for a local annotation effort: 200-500 notes labeled by clinical staff who understand your documentation conventions. It's expensive and slow, but it's what separates a demo from a system people trust.

One thing that surprised me: the highest-value output isn't the individual extraction. It's the patient-level longitudinal profile. A single mention of food insecurity is a data point. Three mentions across six months, with no "resource connected" mentions in between, is a care gap that demands intervention. Build the profile view early, because that's what care managers actually use.

---

## Related Recipes

- **Recipe 6.9 (Social Determinant Phenotyping):** Uses clustering to identify SDOH phenotype subgroups across populations, consuming this recipe's extraction output as input features
- **Recipe 8.5 (Problem List Extraction):** Shares the section detection and assertion classification patterns; SDOH extraction extends the same pipeline to non-medical concepts
- **Recipe 8.8 (Clinical Assertion Classification):** The assertion classification model (present, absent, possible, historical) is the same technology applied to medical entities
- **Recipe 7.6 (Rising Risk Identification):** SDOH features dramatically improve risk models; this recipe provides the structured SDOH input that risk models consume
- **Recipe 4.6 (Care Gap Prioritization):** Active SDOH needs represent care gaps that personalization engines can prioritize for outreach

---

## Tags

`nlp` · `sdoh` · `social-determinants` · `comprehend-medical` · `comprehend-custom` · `text-classification` · `entity-extraction` · `population-health` · `care-management` · `medium-complex` · `lambda` · `dynamodb` · `sqs` · `hipaa`

---

*← [Recipe 8.5: Problem List Extraction](chapter08.05-problem-list-extraction) · [Chapter 8 Index](chapter08-preface) · [Next: Recipe 8.7: Adverse Event Detection in Clinical Text →](chapter08.07-adverse-event-detection-clinical-text)*
