# Chapter 8: Clinical NLP & Information Extraction

*Teaching Computers to Read Between the Lines*

Clinical text is a mess. I don't mean that as an insult to clinicians (they're writing under impossible time constraints), I mean it as a technical observation about the nature of the data. A physician writing a note at 2am after a 14-hour shift is not thinking about how easy their text will be for a downstream system to parse. They're thinking about the patient. And that produces prose that is abbreviated, context-dependent, specialty-specific, and absolutely packed with implicit meaning.

Here's a sentence from a real clinical note (de-identified, obviously): "Pt denies CP, no SOB at rest, +DOE with 1 flight of stairs, unchanged from last visit."

If you're a cardiologist, that sentence is crystal clear. If you're an NLP system, you need to figure out: what was denied (chest pain), what was also denied (shortness of breath at rest), what was affirmed (dyspnea on exertion with one flight of stairs), what the temporal context is (unchanged from prior), and how all of that relates to the patient's problem list. That's five distinct pieces of clinical information in 19 words, three of which are abbreviations.

This chapter is about teaching computers to do that kind of reading. Not with large language models (we covered those in Chapter 2), but with the focused, task-specific NLP techniques that have been the workhorses of clinical text processing for over two decades. These are the tools that power your hospital's coding automation, your health system's quality reporting, and the clinical research that identifies new drug safety signals from millions of notes.

---

## Why "Non-LLM" NLP Still Matters

You might reasonably ask: if LLMs can do everything, why do we need a whole chapter on traditional NLP? Three reasons.

**First, precision at scale.** When you're processing 50 million clinical notes to identify every patient with a specific phenotype for a research study, you need reproducible, deterministic, auditable extraction. You need to know exactly what rules triggered a match and why. LLMs are probabilistic; traditional NLP pipelines are (mostly) deterministic. For regulatory submissions, IRB-approved research protocols, and safety surveillance systems, that determinism matters.

**Second, cost and latency.** Running an LLM inference on every clinical note in a health system generates enormous compute costs. A well-tuned rule-based or classical ML pipeline processes notes in single-digit milliseconds at a fraction of the cost. When you need to process notes in real-time (say, flagging adverse events as they're documented), the economics of LLMs don't work. Traditional NLP does.

**Third, interpretability.** When a clinical assertion classifier marks "diabetes" as "historical" rather than "active," you can trace exactly which linguistic features drove that decision. The negation cue "history of" triggered a specific rule. The assertion model weighted specific contextual tokens. You can explain this to a clinician, a regulator, or a safety officer. Try explaining why GPT-4 classified something a particular way. You'll get a plausible-sounding explanation that may or may not reflect what actually happened inside the model.

None of this means LLMs are bad. They're genuinely transformative for certain tasks (see Chapter 2). But the vast majority of clinical NLP in production today uses the techniques in this chapter, and that's not going to change overnight. These approaches are battle-tested, well-understood, and importantly, already validated in clinical contexts where "move fast and break things" gets people hurt.

---

## The Core Techniques

Let me give you a quick map of the algorithmic approaches we'll use across these recipes, so you have the vocabulary before we dive in.

### Tokenization and Sentence Splitting

Breaking text into meaningful units. Sounds trivial until you encounter "Dr. Smith prescribed 2.5mg q.d. for 30d" and need to figure out where the sentences end without treating every period as a sentence boundary. Clinical text has its own punctuation conventions that break general-purpose tokenizers.

### Named Entity Recognition (NER)

Identifying mentions of specific entity types in text: medications, diagnoses, procedures, anatomy, lab values. The classic approach uses Conditional Random Fields (CRFs) or BiLSTM-CRF architectures trained on annotated clinical text. More recent approaches use transformer-based models fine-tuned on clinical corpora, but the task formulation is the same: given a sequence of tokens, label each one with its entity type (or "not an entity").

### Negation and Assertion Detection

The single most important piece of clinical NLP that people outside the field don't think about. "Patient denies chest pain" and "patient reports chest pain" contain the same clinical entity (chest pain) with completely opposite meanings. Getting assertion status wrong doesn't just reduce accuracy; it produces clinically dangerous misinformation. Systems like NegEx, ConText, and their modern neural successors exist specifically to solve this problem.

### Relationship Extraction

Connecting entities to each other. "Metformin 500mg twice daily for diabetes" contains a medication entity, a dose, a frequency, and a condition, and they're all related to each other. Extracting each entity independently is only half the job; you need to link them into structured relationships.

### Text Classification

Assigning categories to text spans. This ranges from simple (classifying a chief complaint into one of 50 categories) to complex (classifying the assertion status of a clinical entity into one of seven categories based on surrounding context). The model architectures range from logistic regression and SVMs for simple tasks to fine-tuned BERT variants for complex ones.

### Concept Normalization

Mapping extracted text mentions to standard terminologies. "Heart attack," "MI," "myocardial infarction," and "STEMI" all need to map to the appropriate SNOMED CT or ICD-10 code. This is essentially an entity linking problem, and in healthcare the target ontologies (SNOMED, ICD-10, RxNorm, LOINC) are massive, hierarchical, and sometimes inconsistent with each other.

---

## The Tooling Landscape

A few tools and resources show up repeatedly across these recipes, so let me introduce them here.

**spaCy** is the general-purpose NLP framework we lean on most heavily. Fast, production-oriented, with a clean pipeline architecture. Its clinical extensions (like scispaCy and medspaCy) add biomedical models and clinical-specific components.

**UMLS (Unified Medical Language System)** is the meta-thesaurus that maps between clinical terminologies. If you need to know that "heart attack" and ICD-10 code I21.9 refer to the same concept, UMLS is where that knowledge lives. It requires a free license from the National Library of Medicine.

**Clinical NLP corpora** for training and evaluation: i2b2/n2c2 shared task datasets have been the gold standard for clinical NLP research for over 15 years. MIMIC-III/IV provides real (de-identified) clinical notes for development and testing. These resources are invaluable, but access requires data use agreements and institutional review.

On the AWS side, Amazon Comprehend Medical provides pre-built clinical NLP capabilities (entity extraction, relationship detection, assertion classification) as a managed service. Several of our recipes use it as an accelerator, but we always teach the underlying concepts first so you understand what the service is doing and where its limitations lie.

---

## How the Recipes Progress

We start simple and build complexity deliberately.

**Recipes 8.1-8.2** are classification tasks on short text. Chief complaint classification (8.1) takes a brief free-text string and assigns it to a category. Patient sentiment analysis (8.2) classifies feedback text by tone and theme. These are well-understood problems with abundant training data and low clinical risk. If you've never built clinical NLP before, start here.

**Recipes 8.3-8.5** introduce entity extraction and normalization. ICD-10 code suggestion (8.3) extracts diagnostic concepts and maps them to a massive code vocabulary. Medication extraction (8.4) pulls out drug mentions with their full sig (dose, route, frequency) and normalizes to RxNorm. Problem list extraction (8.5) identifies active diagnoses, which requires understanding the difference between "patient has diabetes" and "patient's father had diabetes."

**Recipes 8.6-8.7** tackle harder extraction problems where the signal is sparse and implicit. SDOH extraction (8.6) finds social determinant mentions that clinicians document inconsistently and in varied language. Adverse event detection (8.7) identifies safety signals that are often documented obliquely ("patient developed rash, medication discontinued" rather than "adverse drug reaction to amoxicillin").

**Recipes 8.8-8.10** are the deep end. Clinical assertion classification (8.8) determines whether an extracted entity is present, absent, possible, historical, or hypothetical, which requires understanding complex linguistic context. Temporal relationship extraction (8.9) figures out the order of clinical events when explicit dates are rarely given. Phenotype extraction (8.10) combines multiple NLP components into complex patient identification algorithms for research, where precision requirements are extreme and reproducibility is non-negotiable.

---

## A Word About the LLM Elephant in the Room

Every technique in this chapter predates the current LLM wave. Some of these approaches are 20+ years old. That might make them sound outdated. They're not.

Here's the honest assessment: LLMs will eventually handle many of these tasks well. Some of them, they already handle well in research settings. But "handles well in research" and "deployable in a regulated clinical environment at scale" are separated by a chasm of validation, regulatory approval, cost optimization, and operational maturity that takes years to cross. The techniques in this chapter have already crossed that chasm. They're in production. They work. They're validated. They have published performance characteristics that you can cite in a regulatory submission.

Build with what works today. Keep an eye on what's coming. That's the pragmatic engineering approach.

Let's start with the simplest pattern: taking a short text string and putting it in a bucket.

---

*-> [Recipe 8.1: Chief Complaint Classification](chapter08.01-chief-complaint-classification)*

## Further Reading

- [Clinical Natural Language Processing for Radiology: Exploiting the Text](https://pubmed.ncbi.nlm.nih.gov/26133894/) - foundational survey of clinical NLP techniques and their applications
- [spaCy](https://spacy.io/) - the production NLP framework used throughout this chapter
- [scispaCy](https://allenai.github.io/scispacy/) - biomedical NLP models built on spaCy
- [medspaCy](https://github.com/medspacy/medspacy) - clinical text processing toolkit extending spaCy with assertion detection, context analysis, and section tagging
- [UMLS (Unified Medical Language System)](https://www.nlm.nih.gov/research/umls/index.html) - the NLM meta-thesaurus referenced throughout this chapter
- [i2b2/n2c2 NLP Research Data Sets](https://www.i2b2.org/NLP/DataSets/) - clinical NLP challenge datasets for training and benchmarking
