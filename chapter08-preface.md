# Chapter 8 Preface: Teaching Computers to Read Between the Lines

Here's a confession: when most people hear "NLP in healthcare," they immediately think of large language models. ChatGPT writing clinical notes. GPT-4 summarizing patient charts. That's Chapter 2. This chapter is about something older, more battle-tested, and in many ways more interesting: the traditional NLP techniques that have been grinding through clinical text for over two decades, and that still power the majority of production healthcare text processing today.

I want to make a case for these techniques. Not because they're better than LLMs (for some tasks, they're definitively worse), but because they have properties that matter enormously in healthcare: they're deterministic, they're fast, they're explainable, and they fail in predictable ways. When a regex-based medication extractor misses a drug mention, you can look at the pattern and understand exactly why. When a CRF-based assertion classifier marks something as "negated," you can trace that decision back through the feature weights. Try doing that with a 70-billion-parameter model.

The other reason these techniques matter: they run at scale without GPU clusters. They process thousands of documents per second on commodity hardware. They don't hallucinate. And for the specific, well-defined extraction tasks that make up most of clinical NLP, they work really, really well.

---

## What "Traditional NLP" Actually Means

Let me draw a boundary. When I say "non-LLM NLP" in this chapter, I mean techniques that don't rely on massive pretrained language models as their core mechanism. That includes:

**Rule-based and pattern-matching approaches.** Regular expressions, dictionary lookups, hand-crafted grammars. The oldest tools in the toolbox. Sounds primitive until you realize that a well-tuned regex for extracting medication dosages from clinical text can achieve 95%+ precision with zero training data and sub-millisecond latency. These aren't going away.

**Classical machine learning classifiers.** Support vector machines, random forests, logistic regression, naive Bayes. Feed them engineered features (bag-of-words, n-grams, linguistic features) and they learn to categorize text. Still the backbone of most production text classification in healthcare.

**Sequence labeling models.** Conditional Random Fields (CRFs) and their variants. These are the workhorses of clinical named entity recognition. They understand that tokens in a sequence influence each other, that "500mg" after "metformin" means dosage, not a lab value. CRFs dominated clinical NLP for the better part of a decade, and many systems still use them because they're fast and well-understood.

**Lightweight neural models.** BiLSTMs, CNNs for text, word2vec/GloVe embeddings. These sit in an interesting middle ground. They're neural, but they're not the kind of massive pretrained transformers we associate with the LLM era. A BiLSTM-CRF for clinical NER might have a few million parameters. That's a rounding error compared to GPT-4. These models learn task-specific representations from your annotated clinical data, not from the entire internet.

**Clinical NLP pipelines.** Systems like cTAKES (Apache), MetaMap (NLM), MedSpaCy, and SciSpaCy that bundle multiple techniques into cohesive clinical text processing frameworks. These are purpose-built for healthcare text, with components for sentence detection, tokenization, section parsing, negation detection, and concept normalization all tuned for clinical language.

---

## Why Clinical Text Is a Special Kind of Hard

General-purpose NLP tools trained on news articles and Wikipedia break in fascinating ways when you point them at clinical notes. Here's why:

**Clinical language is aggressively abbreviated.** Physicians write "pt" for patient, "hx" for history, "sx" for symptoms, "dx" for diagnosis, "tx" for treatment. They write "SOB" for shortness of breath (which means something very different in casual English). They write "NAD" for no acute distress and "WNL" for within normal limits. Every specialty has its own abbreviation set, and they overlap in ambiguous ways.

**Negation is everywhere and it's subtle.** A clinical note saying "patient denies chest pain" means the patient does NOT have chest pain. "No evidence of malignancy" means no cancer found. "Family history of diabetes" means the patient's family has it, not the patient. "Ruled out PE" means pulmonary embolism was considered and dismissed. Understanding what's present versus absent versus hypothetical versus someone else's problem is not optional in clinical NLP. Get it wrong and you've just told the system a patient has cancer when they don't.

**Sentences aren't really sentences.** Clinical notes are full of fragments, lists, shorthand, and structures that would make a grammar checker weep. "A&O x3. HEENT: NCAT. Lungs CTA bilat. Heart RRR, no m/r/g." That's a perfectly normal physical exam section. Good luck parsing it with a model trained on well-formed English.

**Context changes the meaning of everything.** The word "discharge" means something completely different in "discharge from the hospital" versus "wound discharge" versus "vaginal discharge." "Positive" in "positive for influenza" is bad news; "positive" in "responding positively to treatment" is good news. Clinical NLP has to be deeply context-aware, and that context often spans multiple sentences or sections.

**Section structure matters but isn't standardized.** Clinical notes have logical sections (Chief Complaint, History of Present Illness, Assessment and Plan) but the headers, ordering, and formatting vary by EHR, provider, and specialty. A medication mention in the "Allergies" section has a completely different meaning than the same mention in "Current Medications." Knowing where you are in the document is critical for correct interpretation.

---

## The Foundational Techniques

Before diving into recipes, it helps to understand the core algorithmic approaches you'll see repeated throughout this chapter:

### Tokenization and Sentence Splitting

This sounds trivial until you try it on clinical text. Standard sentence splitters break on periods, but "Dr. Smith" has a period that isn't a sentence boundary. "3.5mg" has a period that isn't a sentence boundary. "Pt seen by Dr. Jones at 3 p.m. for f/u." has multiple periods and only one is a sentence boundary. Clinical tokenizers like those in MedSpaCy handle these cases through specialized rules and contextual heuristics.

### Named Entity Recognition (NER)

Identifying spans of text that represent specific concepts: medications, diseases, procedures, anatomy, lab tests. In clinical NLP, this is typically done with either dictionary-based approaches (matching against UMLS, RxNorm, SNOMED CT) or sequence labeling models (CRF, BiLSTM-CRF) trained on annotated clinical corpora. The critical nuance: detecting the entity is only half the battle. You also need to classify its type, link it to a standard concept, and determine its assertion status.

### Negation and Assertion Detection

The foundational algorithm here is NegEx, published in 2001 and still used (in evolved forms) in most clinical NLP pipelines. The core idea is elegant: maintain lists of negation triggers ("no," "denies," "without," "ruled out") and scope rules (how far the negation extends). If a clinical concept falls within the scope of a negation trigger, mark it as negated. ConText extended this to other assertion types: hypothetical, family history, historical. These rule-based approaches are fast, interpretable, and surprisingly accurate for common patterns. They struggle with unusual phrasing and long-distance negation, which is where ML-based assertion classifiers earn their keep.

### Concept Normalization

Mapping the extracted text span to a standardized code system. "Heart attack" maps to SNOMED CT 22298006, which maps to ICD-10 I21.9. "MI" maps to the same concepts. So does "myocardial infarction," "AMI," and "acute MI." Normalization typically uses a combination of exact dictionary matching, fuzzy string matching, and embedding-based similarity to handle the enormous variation in how clinicians express the same concept.

### Relation Extraction

Determining how extracted entities relate to each other. The medication "lisinopril" was prescribed at dose "10mg" with frequency "daily" for condition "hypertension." Relation extraction connects these pieces into structured tuples. CRF-based and dependency-parse-based approaches are common for clinical relation extraction, though transformer-based models have been gaining ground for complex relationships.

---

## How the Recipes Progress

This chapter is ordered from simple, well-bounded problems to complex, multi-step reasoning tasks:

**Recipes 8.1-8.2** start with text classification. Short inputs, predefined categories, clear evaluation metrics. Chief complaint classification deals with brief, focused text. Patient sentiment analysis works with survey responses. These are approachable entry points where off-the-shelf classifiers perform well with modest training data.

**Recipes 8.3-8.5** move into entity extraction and normalization. ICD-10 code suggestion requires mapping clinical text to a 70,000+ code vocabulary. Medication extraction demands recognizing drug names, doses, routes, and frequencies as a structured unit. Problem list extraction combines NER with assertion detection. These are the bread-and-butter use cases of clinical NLP, where specialized pipelines outperform general-purpose tools.

**Recipes 8.6-8.7** tackle extraction from sparse, inconsistent documentation. Social determinants of health are mentioned irregularly and in varied language. Adverse events are often documented implicitly. Both require models that can operate on subtle linguistic signals rather than explicit structured statements.

**Recipes 8.8-8.10** are the genuinely hard problems. Clinical assertion classification needs to determine whether an entity is present, absent, possible, conditional, historical, or someone else's. Temporal relationship extraction requires reasoning about when clinical events occurred relative to each other, often from implicit clues. Phenotype extraction for research demands high precision across heterogeneous documentation, with reproducibility requirements that go beyond typical clinical NLP.

---

## A Note on the LLM Elephant in the Room

You might be reading this and thinking: "Why wouldn't I just throw GPT-4 at all of these problems?" Fair question. Let me give you the honest answer.

For some of these tasks, particularly the complex reasoning ones in Recipes 8.8-8.10, LLMs do perform impressively in research settings. But in production healthcare NLP, several factors push teams toward traditional approaches:

**Latency and cost.** Processing 10,000 clinical notes through an LLM API costs real money and takes real time. A CRF-based pipeline processes the same volume in minutes on a single server for pennies.

**Determinism.** The same input to a traditional NLP pipeline produces the same output every time. LLMs are stochastic. In healthcare, where decisions are auditable and reproducible, determinism has value.

**PHI handling.** Sending clinical text to an external API raises HIPAA concerns that don't exist with on-premise or VPC-hosted traditional models. Yes, BAAs exist for cloud LLM services, but many organizations prefer to keep clinical text processing entirely within their boundary.

**Explainability.** When a traditional NLP system marks a mention as "negated," you can show exactly which trigger word and scope rule led to that decision. Regulatory and clinical workflows often require this level of traceability.

None of this means LLMs are wrong for clinical NLP. It means there's a legitimate engineering decision to make, and for many production systems today, traditional techniques win on the combination of cost, speed, determinism, and explainability. The recipes in this chapter equip you to build those systems well.

---

Let's start with the simplest pattern: taking a short piece of free text and routing it to the right category. Recipe 8.1 tackles chief complaint classification, and it's a clean example of how a well-scoped NLP problem can deliver real operational value without exotic algorithms.

---

*-> [Recipe 8.1: Chief Complaint Classification](chapter08.01-chief-complaint-classification)*

## Further Reading

- [Apache cTAKES](https://ctakes.apache.org/) - the open-source clinical NLP pipeline from Mayo Clinic that implements many of the techniques discussed in this chapter
- [NegEx Algorithm](https://doi.org/10.1016/S1532-0464(01)00029-6) - Chapman et al.'s foundational 2001 paper on negation detection in clinical text
- [SciSpaCy](https://allenai.github.io/scispacy/) - spaCy models trained on biomedical text, useful for clinical NER and entity linking
- [UMLS (Unified Medical Language System)](https://www.nlm.nih.gov/research/umls/index.html) - the NLM's comprehensive biomedical terminology resource that underpins most clinical concept normalization
- [i2b2/n2c2 NLP Research Datasets](https://portal.dbmi.hms.harvard.edu/projects/n2c2-nlp/) - shared tasks and annotated clinical corpora that have driven clinical NLP research for two decades
