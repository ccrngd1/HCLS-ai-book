# Recipe 8.4: Medication Extraction and Normalization

**Complexity:** Medium · **Phase:** Integration · **Estimated Cost:** ~$0.20-0.50 per note (varies by note length and medication count)

---

## The Problem

A hospitalist is admitting a patient at 2 AM. The patient's medication list in the EHR says "lisinopril 10mg daily." The patient says they take "that blood pressure pill, the small white one, and also something for my cholesterol." The nursing home transfer summary mentions "Zestril 20mg PO QD" and "atorvastatin calcium 40mg QHS." The discharge summary from three months ago at a different facility lists "HCTZ/lisinopril 12.5/20" and "Lipitor 40."

Same patient. Same medications. Five different representations. And right now, at 2 AM, the hospitalist needs an accurate, reconciled medication list to avoid prescribing something that interacts with what the patient is already taking.

This isn't a rare scenario. It's the default state of medication documentation in healthcare. Clinicians write medications in every possible format: brand names, generic names, abbreviations, shorthand sig codes, partial descriptions, and sometimes just the drug class ("on a statin"). The same medication appears differently in progress notes versus discharge summaries versus nursing assessments versus pharmacy records. A single clinical note might mention "metformin 500 BID," "glucophage," and "her diabetes medication" all referring to the same drug.

The consequences of getting this wrong are not abstract. Adverse drug events from medication errors injure over a million people annually in the US alone. A significant portion of those stem from incomplete or inaccurate medication lists during transitions of care: admission, discharge, transfer, handoff. The Joint Commission has identified medication reconciliation as a National Patient Safety Goal for over a decade, and yet the problem persists because the underlying data problem (medications documented in unstructured text with infinite variation) hasn't been solved at the extraction layer.

The information is there, buried in clinical notes. Extracting it reliably, normalizing it to a standard terminology so that "Zestril 20mg PO QD" and "lisinopril 20mg by mouth daily" are understood as the same thing, and structuring the dose, route, and frequency into machine-readable fields: that's the problem we're solving here.

---

## The Technology: Named Entity Recognition for Medications

### What Is Medical NER?

Named Entity Recognition (NER) is the NLP task of identifying specific types of entities in unstructured text and classifying them into predefined categories. In general NLP, those categories might be "person," "organization," "location." In clinical NLP, the categories that matter are "medication," "dosage," "route," "frequency," "duration," "condition," and "reason."

Medical NER is a specialized variant trained on clinical text rather than news articles or web pages. This distinction matters enormously because clinical language is nothing like general English. Physicians write in a compressed, abbreviated style full of domain jargon: "ASA 325 PO QD for afib" is a perfectly normal sentence in a clinical note. A general-purpose NER system would struggle with every token in that phrase.

The core approach to NER has evolved through several generations:

**Rule-based systems** (1990s-2000s): Dictionary lookups and pattern matching. You build a list of known drug names and scan for them. Works decently for exact matches. Falls apart on abbreviations, misspellings, and novel formulations. Still useful as a preprocessing step.

**Statistical models** (2000s-2010s): Conditional Random Fields (CRFs) and similar sequence labeling models trained on annotated clinical text. These learn patterns from context (what words typically surround a dosage? what follows a drug name?). The i2b2 shared tasks from 2009-2010 established benchmarks here.

**Deep learning models** (2015-present): BiLSTM-CRF architectures and then transformer-based models (BioBERT, ClinicalBERT, PubMedBERT) fine-tuned on clinical NER datasets. These represent the current state of the art. They handle context, abbreviations, and novel formulations much better than earlier approaches because they learn distributed representations of clinical language.

**Pre-trained medical NLP services** (2018-present): Cloud-managed services that package trained clinical NER models behind an API. You send text, you get back structured entities. No model training, no GPU infrastructure, no annotation pipeline. The accuracy is competitive with custom-trained models for common entity types (medications, conditions, anatomy) and dramatically easier to deploy.

### The Normalization Problem

Extracting "lisinopril 20mg PO QD" from a note is only half the battle. The harder half is normalization: mapping that extraction to a standard code in a recognized terminology so that different systems can agree on what medication is being referenced.

The standard terminology for medications in the US is **RxNorm**, maintained by the National Library of Medicine. RxNorm assigns unique concept identifiers (RxCUIs) to clinical drugs at various levels of specificity:

- **Ingredient**: lisinopril (RxCUI: 29046)
- **Semantic Clinical Drug**: lisinopril 20 MG Oral Tablet (RxCUI: 314077)
- **Semantic Branded Drug**: Zestril 20 MG Oral Tablet (RxCUI: 104377)

Normalization means taking the raw extracted text and resolving it to the appropriate RxCUI. This is what enables a system to understand that "Zestril 20mg," "lisinopril 20 mg tab," and "Prinivil 20" all refer to the same clinical drug concept.

The challenges are substantial:

**Brand vs. generic**: There are often dozens of brand names for a single generic ingredient. Atorvastatin alone has brand names including Lipitor, Sortis, Tulip, and Torvast (varying by country).

**Combination drugs**: "HCTZ/lisinopril" or "Zestoretic" refers to a fixed-dose combination. The extraction system needs to identify both ingredients and their respective doses.

**Abbreviations and shorthand**: "ASA" (aspirin), "MOM" (milk of magnesia), "APAP" (acetaminophen), "MTX" (methotrexate). These aren't in consumer dictionaries. Some are ambiguous: "MS" could be morphine sulfate or magnesium sulfate, and confusing them is a known cause of medication errors.

**Dose form variations**: "lisinopril 20" might mean 20mg tablet or 20mg/5mL solution. Context (patient population, route) disambiguates, but it's not always explicit.

**Sig parsing**: "1 tab PO BID PRN" needs to be decomposed into quantity (1), form (tablet), route (oral), frequency (twice daily), and condition (as needed). Sig codes follow loose conventions but aren't formally standardized across all documentation contexts.

### What Makes This Specifically Hard in Clinical Text

Clinical notes have properties that make NER harder than you'd expect from looking at clean pharmacy records:

**Negation and context**: "Patient denies taking metformin" and "patient takes metformin" both contain the entity "metformin" but have opposite meanings. The extraction system must understand assertion context to build an accurate medication list.

**Historical vs. current**: "Was on lisinopril, switched to losartan last month." Both are medications. Only one is current. The temporal context changes which belongs on the active list.

**Allergies vs. medications**: "Allergic to penicillin. Currently taking amoxicillin." Wait. Both are mentioned. One is an allergy, one is a current medication. (And yes, this contradiction is clinically concerning, but that's a different problem.) The point is: not every medication mention belongs on the medication list.

**Section-dependent meaning**: A medication mentioned in "Past Medical History" has different significance than one in "Medications on Admission." Section headers provide context that affects how extractions should be interpreted.

**Dosage ambiguity**: "Increase metformin to 1000" could mean 1000mg or 1000mcg. Clinical context and the drug's typical dosing range disambiguate, but an NER system needs that knowledge or a validation layer.

### The General Architecture Pattern

At a conceptual level, the pipeline for medication extraction and normalization looks like this:

```text
[Clinical Note] → [Section Detection] → [NER Extraction] → [Attribute Linking] → [RxNorm Normalization] → [Context Classification] → [Structured Output]
```

**Section Detection**: Identify which part of the note you're processing. Medications mentioned in "Assessment/Plan" are handled differently than those in "Allergies" or "Family History." This can be rule-based (look for common section headers) or model-based.

**NER Extraction**: Identify medication entities and their associated attributes (dose, route, frequency, duration, reason). The model labels each token with its entity type using BIO tagging (Beginning, Inside, Outside) or similar schemes.

**Attribute Linking**: Connect extracted attributes to their parent medication. "Lisinopril 20mg PO QD and metformin 500mg BID" has two medications, each with their own dose and frequency. The system needs to correctly associate 20mg/PO/QD with lisinopril, not metformin.

**RxNorm Normalization**: Map the extracted medication text (with dose and form if available) to a standard RxCUI. This typically involves fuzzy matching against the RxNorm database, with disambiguation logic for brand/generic equivalents and combination drugs.

**Context Classification**: Determine the assertion status of each extraction: is this medication currently active, historical, denied, or an allergy? This prevents building a medication list that includes discontinued drugs or allergies.

**Structured Output**: Produce a machine-readable representation with the medication name, RxCUI, dose, route, frequency, status (active/discontinued/allergy), and confidence scores for each field.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter08.04-architecture). The Python example is linked from there.

## The Honest Take

Medication NER is one of those problems that's 85% solved out of the box and then the remaining 15% takes 85% of your effort. The managed services are genuinely good at extracting common medications with standard sig codes. "Metformin 500mg PO BID" is basically a solved problem. It's the edge cases that will consume your time.

The RxNorm normalization step is where I've seen the most production issues. The API returns candidates, but the top candidate isn't always correct. "Calcium 600mg" could normalize to calcium carbonate, calcium citrate, or half a dozen other calcium salts. Without additional context (which the patient was previously prescribed, what the formulary carries), you're guessing. Build your confidence thresholds conservatively and route ambiguous cases to pharmacy review.

The section detection might sound like a trivial preprocessing step, but it's actually load-bearing. I've seen systems that correctly extract "penicillin" as a medication from the allergies section and then add it to the active medication list because they didn't check context. That's not a theoretical concern. It happens, and it's dangerous.

The thing that surprised me most: the volume of medication mentions in a single note can be much higher than you'd expect. A discharge summary might mention 15-20 medications across current, discontinued, and allergy sections. Each one needs independent normalization. At ~$0.01 per InferRxNorm call, that's $0.15-0.20 per note just for normalization. Plan your cost model around notes with many medications, not the average.

One more honest admission: Comprehend Medical's DetectEntitiesV2 API has a 20,000-character limit per call. Most individual notes fit within that. Lengthy operative reports or combined note bundles might not. You'll need chunking logic that respects sentence boundaries, and you'll need to handle medications that span a chunk boundary (rare, but it happens with long sig descriptions).

---

## Related Recipes

- **Recipe 8.3 (ICD-10 Code Suggestion):** Uses similar NER foundations but targets condition entities rather than medications
- **Recipe 8.5 (Problem List Extraction):** Extracts condition/diagnosis entities from the same clinical notes using the same NER infrastructure
- **Recipe 8.8 (Clinical Assertion Classification):** Deep dive on the assertion status problem (present/absent/possible/historical) that this recipe handles at a basic level
- **Recipe 13.4 (Drug-Drug Interaction Knowledge Base):** Consumes the RxCUI output from this recipe to power interaction checking
- **Recipe 5.6 (Claims-to-Clinical Data Linkage):** Uses normalized medication data to link pharmacy claims to clinical documentation

---

## Tags

`nlp` · `ner` · `medications` · `rxnorm` · `comprehend-medical` · `clinical-text` · `normalization` · `medium` · `lambda` · `s3` · `dynamodb` · `hipaa` · `medication-reconciliation`

---

*← [Recipe 8.3: ICD-10 Code Suggestion](chapter08.03-icd-10-code-suggestion) · [Chapter 8 Index](chapter08-preface) · [Next: Recipe 8.5: Problem List Extraction →](chapter08.05-problem-list-extraction)*
