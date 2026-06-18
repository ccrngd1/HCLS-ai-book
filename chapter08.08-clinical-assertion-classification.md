# Recipe 8.8: Clinical Assertion Classification

**Complexity:** Complex · **Phase:** Advanced NLP Pipeline · **Estimated Cost:** ~$0.02 per note

---

## The Problem

A clinician writes: "Patient denies chest pain. Mother had history of MI at age 52. If symptoms recur, consider starting atorvastatin."

Now ask a computer: does this patient have chest pain? Does this patient have a history of MI? Is atorvastatin part of the treatment plan?

If you just run entity extraction (the thing we covered in earlier recipes), you get back three clean entities: "chest pain," "MI," and "atorvastatin." Extracted. Normalized. Ready for downstream use. And completely, dangerously wrong if you treat them at face value.

The patient does NOT have chest pain. The MI belongs to the patient's mother. And the atorvastatin is hypothetical, contingent on something that hasn't happened yet. Three entities, three different assertion statuses, and a naive system that treats extraction as truth just contaminated a problem list, a risk model, and a medication reconciliation with garbage data.

This is not an edge case. This is the default state of clinical text. Clinicians are trained to document differentials, rule-outs, family history, hypothetical plans, and negated findings. A well-written progress note might mention a condition six times with six different assertion contexts. "No fever" is not the same as "fever resolved" is not the same as "fever if infection present" is not the same as "family history of familial Mediterranean fever." Same entity. Completely different clinical meaning.

The downstream impact is real and measurable. A research team building a diabetes cohort pulls every patient with "diabetes" mentioned in their notes, and half their cohort is contaminated with patients whose notes say "no evidence of diabetes" or "family history of Type 2 DM." A clinical decision support system fires an alert for a drug interaction based on a medication the patient was never actually prescribed (it was mentioned as a hypothetical). A quality measure calculates incorrectly because it counted negated diagnoses as present conditions.

Assertion classification is the layer that turns raw entity extraction from a liability into a reliable signal. Without it, clinical NLP is not just incomplete. It's actively misleading.

---

## The Technology: Teaching Machines to Read Between the Lines

### What Is Assertion Classification?

Assertion classification (sometimes called assertion detection or assertion status modeling) is the task of determining the factual status of a clinical entity in context. Given an entity already identified in text, the system answers: what is the relationship between this entity and the patient, right now?

The standard assertion categories (originally codified by the i2b2/VA 2010 challenge and the SHARP project) are:

- **Present:** The condition/finding currently exists in the patient. ("Patient has type 2 diabetes.")
- **Absent:** The condition/finding is explicitly negated. ("Denies shortness of breath." "No evidence of DVT.")
- **Possible:** The clinician is expressing uncertainty. ("Possible UTI." "Cannot rule out PE.")
- **Conditional:** The entity exists only under certain circumstances. ("If pain worsens, start opioid therapy." "In the event of anaphylaxis, administer epi.")
- **Historical:** The condition existed in the past but is no longer active. ("History of appendectomy in 2008." "Previously treated for H. pylori.")
- **Family History (Associated with Someone Else):** The entity refers to a family member, not the patient. ("Father died of colon cancer at 58." "Mother has rheumatoid arthritis.")
- **Hypothetical:** The entity is mentioned in a planning or speculative context. ("Will consider biologics if DMARDs fail." "May develop neuropathy over time.")

Some systems collapse these into fewer categories (present, absent, possible, associated with someone else) while others expand them further. The right granularity depends on your downstream use case. For problem list management, you mostly care about present vs. absent vs. historical. For pharmacovigilance, the conditional and hypothetical categories become critical.

### Why This Is Hard

On the surface, assertion classification looks like a straightforward text classification problem. You have an entity, you have some surrounding text, and you need to pick a label. A few hundred training examples and a classifier should do the trick, right?

Not quite. Here's why this problem is genuinely difficult:

**Negation is not just the word "no."** Clinical negation comes in dozens of forms: "denies," "without," "negative for," "no evidence of," "rules out," "absence of," "free of," "unremarkable for." Some negations are pre-entity ("no chest pain"), some are post-entity ("chest pain absent"), and some are structural (a section header that says "Pertinent Negatives" implies everything underneath is absent). A simple keyword list misses about 30-40% of negations in real clinical text.

**Scope is the real killer.** "Patient denies chest pain, shortness of breath, and palpitations but reports occasional dizziness." Which entities are negated? "Chest pain," "shortness of breath," and "palpitations." Which is affirmed? "Dizziness." The negation cue "denies" has a scope that extends through the conjunction but terminates at "but." Getting scope boundaries right requires genuine syntactic understanding, not just proximity-based rules.

**The same entity can have multiple assertions in one note.** "Patient has history of DVT (2019). Currently no symptoms of DVT. Family history significant for recurrent DVT." One entity, three mentions, three different assertion statuses: historical, absent, family. Your system needs to classify each mention independently based on its local context.

**Section context matters enormously.** The sentence "Type 2 diabetes" means something different in a "Past Medical History" section versus an "Assessment and Plan" section versus a "Family History" section. Some systems use section headers as features. This helps but is fragile because section naming is inconsistent across institutions, templates, and EHR systems.

**Hedging language is subtle.** Clinicians express uncertainty in dozens of ways: "likely," "probable," "concerning for," "suspicious for," "consistent with," "cannot exclude," "differential includes." Some of these push toward "possible," others toward "present with low confidence." The line between "the clinician is uncertain" and "the clinician is fairly confident but being appropriately cautious in their documentation" is genuinely fuzzy.

**Abbreviations and implicit context.** "s/p appendectomy" means status-post (historical). "r/o PE" means rule-out (possible or under investigation). These are assertion cues, but they look like entity modifiers to a naive system. Domain knowledge is not optional.

### How Assertion Classification Works

There are three main approaches, each with meaningful tradeoffs:

**Rule-based systems.** The classic approach. NegEx (2001) and its successor ConText (2009) use regular expression patterns and trigger terms to identify negation, temporality, and experiencer (patient vs. family). They define trigger terms ("denies," "no," "family history of"), pseudo-triggers that look like negation but aren't ("not only"), and scope termination patterns ("but," "however," period/newline). NegEx works surprisingly well for simple negation (around 80-90% accuracy on present/absent classification). It falls apart on scope ambiguity, hedging language, and complex conditional structures. The advantage: completely deterministic, fully explainable, no training data required, runs in microseconds. Still widely deployed in production today as a first-pass filter.

**Machine learning classifiers.** Treat assertion as a multi-class classification problem. Extract features from the entity and its surrounding context (bag of words, n-grams, section headers, syntactic parse features, distance to negation cues) and train a classifier (SVM, random forest, CRF). The 2010 i2b2/VA shared task established benchmarks for this approach. Top systems achieved F1 scores around 0.93 for assertion classification on their test set. The disadvantage: requires annotated training data specific to your institution's documentation patterns, and performance degrades on out-of-distribution text.

**Deep learning and transformers.** Fine-tune a clinical language model (ClinicalBERT, BioBERT, PubMedBERT, or a general BERT/RoBERTa model fine-tuned on clinical text) on assertion-labeled examples. The entity is marked in the input sequence (using special tokens or entity position embeddings), and the model predicts the assertion class. This is the current state of the art, achieving F1 scores above 0.95 on benchmark datasets. The model learns implicit scope rules, hedging patterns, and section-level context from data rather than hand-coded rules. Disadvantage: needs GPU for training, requires hundreds to thousands of labeled examples, and the model is a black box (harder to debug when it gets an assertion wrong).

**Hybrid approaches** (the most common in production) combine rule-based negation detection with ML-based classification for the harder cases. NegEx handles the obvious negations quickly and cheaply. Everything NegEx can't confidently classify gets passed to a trained model. This layered approach gives you speed on the easy cases and accuracy on the hard ones.

### Where the Field Is Today

Ok, so where does all this actually stand in 2026? Four things have changed since the i2b2 2010 days that make assertion classification meaningfully more practical than it was a decade ago:

**Pre-trained clinical language models** have meaningfully improved performance, especially on subtle hedging and conditional assertions. Models trained on large clinical text corpora understand the implicit conventions of medical documentation in ways that general-purpose models do not.

**Transfer learning** has reduced the annotation burden. You can fine-tune a clinical language model on a relatively small labeled dataset (500-1000 examples) and achieve performance that previously required thousands of annotations. This makes it practical for individual institutions to build custom assertion classifiers tuned to their documentation patterns.

**Span-level classification** (rather than sentence-level) is becoming standard. Instead of classifying a whole sentence, systems identify the exact span of text that is the entity and classify just that mention's assertion status. This handles the common case where multiple entities in one sentence have different assertion statuses.

**Integration with entity extraction** is tightening. Modern clinical NLP pipelines run extraction and assertion jointly rather than as separate sequential steps. Joint models can use assertion-relevant features during extraction and vice versa. This reduces error propagation.

The main gap: generalizability. A model trained on one institution's notes (with their templates, their abbreviation conventions, their section naming) may underperform at another institution. Cross-institutional validation is still the exception rather than the norm.

---

## General Architecture Pattern

At a conceptual level, the assertion classification pipeline looks like this:

```text
[Clinical Text] → [Entity Extraction] → [Context Window Extraction] → [Assertion Classification] → [Annotated Entities] → [Downstream Systems]
```

Let's walk through each stage:

**Entity Extraction.** Before you can classify an entity's assertion, you need to identify the entity. This stage runs named entity recognition (NER) over the clinical text to find mentions of diagnoses, symptoms, medications, procedures, and other clinical concepts. Recipes 8.4 (Medication Extraction) and 8.5 (Problem List Extraction) cover this step in detail. The output is a list of entity spans: character offsets marking the start and end of each entity in the text.

**Context Window Extraction.** For each entity, extract the surrounding text that contains assertion-relevant cues. The window size matters. Too narrow (just the immediate sentence) and you miss section-level cues. Too wide (the whole note) and you introduce noise. In practice, a window of 2-3 sentences around the entity, plus the section header, captures the relevant signal for most cases.

**Assertion Classification.** The core model. Takes the entity plus its context window and predicts one of the assertion classes (present, absent, possible, conditional, historical, family, hypothetical). Depending on your approach, this is a rule engine, a trained classifier, or a fine-tuned language model.

**Post-processing and Conflict Resolution.** Handle cases where the same entity appears multiple times with different assertions. Decide on precedence rules: if "diabetes" is mentioned as present in the Assessment and as historical in the Past Medical History, which wins? (Usually: the most recent, most specific mention.)

**Output and Integration.** The final annotated entities (each tagged with its assertion status) flow to downstream systems: problem lists, quality measures, research cohorts, decision support, risk models. The assertion tag determines whether the entity counts as "active" for downstream logic.

The architecture supports two deployment patterns: batch (process notes in bulk for research or quality measurement) and real-time (classify assertions as notes are finalized in the EHR for immediate clinical decision support).

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter08.08-architecture). The Python example is linked from there.

## The Honest Take

Assertion classification is one of those problems that feels solved until you deploy it on real clinical text at scale. The benchmarks look great on clean academic datasets. Then you encounter the emergency department physician who documents in stream-of-consciousness fragments without punctuation, the copy-forward note that contains three years of historical assessments mixed with today's findings, and the templated note where half the "findings" are default text that was never edited.

The rule-based layer (NegEx-style) is genuinely underrated. It handles 60% of cases correctly and instantly. Do not skip it in pursuit of an all-ML solution. The ML model should handle the hard 40%, not the easy 60%.

The assertion taxonomy decision matters more than you'd expect. If your downstream consumers only need present/absent/family, don't build a 7-class system. More classes means more annotation cost, lower inter-annotator agreement, and harder model training. Start with fewer classes and expand only when a downstream system actually needs the granularity.

The part that surprised me: conflict resolution is where the most clinical judgment lives. When a concept is mentioned as "historical" in PMH and "present" in the Assessment, a human knows the clinician is saying "this previously resolved condition has recurred." Getting a rules-based system to make that inference reliably requires clinical knowledge that is hard to encode. In practice, most production systems punt on conflict resolution and return all mentions with their individual assertions, letting the downstream consumer decide.

One more thing: Comprehend Medical's built-in negation detection is better than most people give it credit for. If your use case only needs present vs. absent (which covers a surprising number of use cases: quality measures, problem list maintenance, cohort identification), test Comprehend Medical's native traits before building a custom model. You might not need the custom layer at all.

---

## Related Recipes

- **Recipe 8.4 (Medication Extraction and Normalization):** Provides the entity extraction foundation that assertion classification builds upon
- **Recipe 8.5 (Problem List Extraction):** Uses assertion classification to determine which extracted problems are currently active vs. historical
- **Recipe 8.7 (Adverse Event Detection):** Requires assertion classification to distinguish actual adverse events from negated or hypothetical mentions
- **Recipe 8.9 (Temporal Relationship Extraction):** Extends assertion's "historical" category with specific temporal anchoring
- **Recipe 8.10 (Phenotype Extraction for Research):** Assertion classification is a prerequisite for accurate phenotype identification

---

## Tags

`nlp` · `assertion` · `negation` · `clinical-text` · `comprehend-medical` · `sagemaker` · `complex` · `entity-classification` · `hipaa` · `clinical-decision-support`

---

*← [Recipe 8.7: Adverse Event Detection in Clinical Text](chapter08.07-adverse-event-detection-clinical-text) · [Chapter 8 Index](chapter08-preface) · [Next: Recipe 8.9 - Temporal Relationship Extraction →](chapter08.09-temporal-relationship-extraction)*
