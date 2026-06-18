# Recipe 8.3: ICD-10 Code Suggestion

**Complexity:** Simple-Medium · **Phase:** Phase 1-2 · **Estimated Cost:** ~$0.05-$0.15 per note (section-targeted)

<!-- TODO (TechWriter): Confirm cost estimate. Body text says $0.05-$0.15 section-targeted, $0.40-$1.00 full text. Original header had $0.01-$0.05 which understates. -->

---

## The Problem

A medical coder opens her queue at 7 AM. There are 147 encounters from yesterday waiting for diagnosis coding. She opens the first one: a progress note from a primary care visit. The patient has Type 2 diabetes with peripheral neuropathy, essential hypertension, chronic kidney disease stage 3, and was seen today for a medication adjustment after their A1c came back at 8.2. The coder reads the entire note. She identifies the relevant diagnoses. She navigates the ICD-10-CM code tree. She considers whether E11.40 (Type 2 diabetes with diabetic neuropathy, unspecified) or E11.42 (Type 2 diabetes with diabetic polyneuropathy) is more appropriate given the documentation. She checks whether the CKD stage is explicitly documented (it is: N18.3). She picks I10 for the hypertension. She submits and moves to the next encounter.

Average time per encounter: 8-12 minutes for a moderately complex visit. She'll code maybe 50-60 encounters today if nothing gets complicated. The queue will grow faster than she can clear it.

Medical coding is one of the largest labor bottlenecks in the revenue cycle. The U.S. healthcare system processes billions of encounters annually, and every single one needs ICD-10 codes assigned before a claim can be submitted. The coding workforce is aging, the training pipeline takes years, and the demand outstrips supply at most organizations. Coders are expensive, they're burned out, and they're coding the same common diagnoses hundreds of times per week while spending their real expertise on the genuinely difficult cases.

Here's the thing: for 60-70% of encounters, the relevant ICD-10 codes are fairly obvious from the clinical text. When the note says "Type 2 diabetes mellitus with peripheral neuropathy," a trained model can suggest E11.40 or E11.42 with reasonable confidence. It can't replace the coder's judgment on which is more appropriate. But it can present a ranked list of candidates so the coder is selecting from a pre-screened set rather than navigating the entire 70,000-code taxonomy from scratch.

This is the ICD-10 code suggestion problem: given clinical text, suggest a ranked list of diagnosis codes that a human coder can review, accept, modify, or reject. It's not auto-coding. It's not replacing the coder. It's presenting an intelligent starting point that turns an 8-minute recall-and-search task into a 3-minute verify-and-confirm task.

The distinction between "suggestion" and "auto-coding" is not semantic. It's regulatory, it's legal, and it's practical. Auto-coding implies the system assigns codes without human review. That creates liability, audit risk, and compliance concerns that most organizations are nowhere near ready to accept. Suggestion means a human is always in the loop. The system accelerates their work. It doesn't replace their judgment.

---

## The Technology: Clinical Text Classification Meets Medical Ontology

### How ICD-10 Inference Works

ICD-10 code suggestion is fundamentally a multi-label classification problem with an extraordinarily large label space. You have input text (a clinical note, a progress note, a discharge summary) and you need to output one or more codes from a vocabulary of roughly 70,000 ICD-10-CM codes. But it's not a typical classification problem, because the labels have hierarchical structure, the input can map to multiple labels simultaneously, and the specificity of the correct label depends on the detail in the source text.

The approaches fall into three broad categories:

**Rule-based systems** use dictionaries, pattern matching, and hand-crafted logic to map clinical phrases to codes. "Hypertension" maps to I10. "Type 2 diabetes" maps to E11.9 (unspecified) unless additional qualifiers push it to a more specific code. These systems are transparent and auditable, but they're brittle. They can't handle the infinite variation in how clinicians describe the same condition, and they require continuous manual maintenance as the code set evolves (ICD-10-CM updates annually).

**Traditional ML approaches** treat it as a text classification problem. Extract features from the clinical text (bag of words, TF-IDF, n-grams, clinical embeddings), then train a classifier that predicts codes. The challenge is the label space: with 70,000 possible codes, you need massive training datasets and clever architecture to avoid the model simply memorizing the top 200 codes and ignoring everything else. Hierarchical classifiers (predict the chapter first, then the category, then the specific code) help manage the label space.

**Neural approaches** use deep learning models (convolutional networks, recurrent networks, transformers) trained on large corpora of coded clinical documents. These models learn to map the distributional patterns in clinical text directly to code probabilities. They handle paraphrasing, abbreviations, and implicit context better than rule-based systems. But they require substantial training data (hundreds of thousands of coded encounters), significant compute for training, and they're less interpretable than rule-based approaches.

In practice, production ICD-10 suggestion systems almost always combine approaches. A neural model handles the broad-strokes prediction (identifying which diagnostic concepts are present). A rule-based post-processor handles specificity refinement (choosing between E11.40 and E11.42 based on explicit documentation of neuropathy type). And a medical ontology layer ensures the suggested codes are valid, current, and properly hierarchically related.

### The ICD-10-CM Hierarchy: Why It Matters for Prediction

ICD-10-CM isn't a flat list. It's a tree. Understanding the tree structure is essential for building a useful suggestion system:

- **Chapters** (21 total): Broad disease categories. Chapter 4 is endocrine/metabolic diseases.
- **Blocks**: Groups within chapters. E08-E13 covers diabetes mellitus.
- **Categories** (3 characters): E11 is Type 2 diabetes mellitus.
- **Subcategories** (4-5 characters): E11.4 is Type 2 diabetes with neurological complications.
- **Full codes** (up to 7 characters): E11.40 is Type 2 diabetes with diabetic neuropathy, unspecified.

This hierarchy is exploitable for prediction. If your model is 95% confident the text describes Type 2 diabetes with a neurological complication (E11.4x), but only 60% confident about the specific neuropathy type, you can suggest E11.4 at high confidence and present the specific options (E11.40, E11.41, E11.42, E11.43, E11.44) as sub-choices for the coder. This is substantially more useful than either suggesting nothing (because the model isn't confident enough at the leaf level) or suggesting only E11.9 (the unspecified code that's technically always safe but reduces documentation quality).

### Negation, Assertion, and Context: The Real Challenge

The hardest part of ICD-10 suggestion from clinical text isn't identifying that the word "diabetes" appears. It's understanding the assertion context around it:

- "Patient has diabetes" = code it.
- "No diabetes" = do not code it.
- "Family history of diabetes" = code Z83.3 (family history), not E11.x.
- "Rule out diabetes" = do not code it (it's a working hypothesis, not a confirmed diagnosis).
- "Diabetes resolved" = may or may not be coded depending on whether it's considered a chronic condition.
- "History of gestational diabetes" = Z86.32, not a current diabetes code.

A model that ignores assertion context will over-suggest codes for conditions the patient doesn't have. This is worse than suggesting nothing, because a coder who trusts the suggestions will spend time verifying and rejecting false positives, which is slower than just reading the note themselves.

Clinical assertion detection is a well-studied NLP problem. The key insight is that negation in clinical text follows predictable patterns. ConText (a rule-based algorithm), NegEx (its predecessor), and more recent neural approaches all exploit the fact that clinical negation uses a limited set of trigger phrases: "no," "denies," "negative for," "without," "ruled out," "unlikely." These triggers have scope (they negate the next few clinical concepts, not the entire note) and direction (they typically apply forward in the sentence, not backward).

A robust ICD-10 suggestion system runs assertion detection as a preprocessing step. Every extracted clinical concept gets tagged with its assertion status (present, absent, possible, family history, historical) before any code mapping happens. Only concepts with "present" assertions proceed to code suggestion.

### Training Data: The Gold Standard Problem

Training an ICD-10 suggestion model requires labeled data: clinical text paired with the correct codes. The obvious source is your existing coded encounters. Your coders have been assigning codes to notes for years. That's your training set.

Except there are problems with this obvious approach:

**Coder variability.** Different coders assign different codes to the same note. Studies show inter-coder agreement rates of 60-80% at the full code level for complex encounters. Your training data contains noise from this variability.

**Upcoding and undercoding bias.** Some organizations systematically upcode (assign more specific or higher-severity codes than documented). Others undercode (use unspecified codes when specificity is available). Your model learns whatever bias exists in your historical data.

**Code version drift.** ICD-10-CM updates annually. Codes are added, deleted, and revised. Training data from 2020 may include codes that no longer exist or miss codes that were introduced in 2023.

**Documentation quality variation.** A note that says "Type 2 diabetes with peripheral neuropathy" is easy to code. A note that buries the same information across three paragraphs, refers to neuropathy as "tingling in feet," and mentions the diabetes diagnosis only in the medication list is much harder. Your model needs exposure to both documentation styles.

The practical approach is to use your coded encounter data as the training foundation, but apply several corrections: filter to encounters coded by your most experienced coders (or coded consistently by multiple coders), restrict to the most recent 2-3 fiscal years to avoid code version drift, and augment with synthetic examples for rare codes using the code descriptions themselves as pseudo-clinical text.

### The General Architecture Pattern

```text
[Clinical Note] → [Text Preprocessing] → [Section Segmentation] → [Concept Extraction]
                                                                          ↓
                                                                   [Assertion Detection]
                                                                          ↓
                                                              [Filter: Present Only]
                                                                          ↓
                                                              [Code Candidate Generation]
                                                                          ↓
                                                              [Hierarchical Ranking]
                                                                          ↓
                                                              [Confidence Scoring]
                                                                          ↓
                                                         [Suggestion List for Coder]
```

**Text Preprocessing:** Clean the input. Expand abbreviations. Handle section headers (HPI, Assessment, Plan each have different relevance for coding). Remove boilerplate template text that adds noise.

**Section Segmentation:** Clinical notes have structure. The Assessment and Plan section is the richest source of codable diagnoses. The Problem List section often lists active conditions explicitly. The HPI provides context. Segment the note and weight sections appropriately.

**Concept Extraction:** Identify clinical concepts (diagnoses, conditions, symptoms) in the text. This is named entity recognition specialized for clinical content.

**Assertion Detection:** Classify each extracted concept by assertion status. Filter to concepts that are asserted as present in the patient.

**Code Candidate Generation:** Map each present clinical concept to candidate ICD-10-CM codes. Generate multiple candidates at different specificity levels.

**Hierarchical Ranking:** Rank candidates by confidence, preferring the most specific code that's well-supported by the documentation. Use the ICD-10 tree structure to group related codes.

**Confidence Scoring:** Assign a composite confidence score reflecting both extraction confidence and code mapping confidence.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter08.03-architecture). The Python example is linked from there.

## The Honest Take

I'll be upfront: ICD-10 code suggestion is one of those problems that's deceptively easy to demo and genuinely hard to deploy well.

The demo is impressive. You feed a clinical note into Comprehend Medical, you get back a list of codes with confidence scores, and 85% of them are right. Executives love it. "We'll cut coding time in half!" And maybe you will. But the gap between "85% of common codes suggested correctly" and "coders trust this enough to change their workflow" is enormous.

Here's what surprised me: coders don't trust the suggestions for about the first two weeks. They verify everything independently, which makes the system slower, not faster. Then they start trusting the high-confidence suggestions for common codes (hypertension, diabetes, hyperlipidemia). Then they gradually extend trust to medium-confidence suggestions. The adoption curve is weeks to months, not days. Plan for it.

The specificity problem is the most persistent frustration. Comprehend Medical will happily suggest E11.9 (Type 2 diabetes, unspecified) when the note clearly documents peripheral neuropathy that should push it to E11.42. The model is being conservative. That's defensible behavior for an AI system in healthcare. But it means the coder still needs to read the note carefully and make the specificity determination themselves. The suggestion saved them the lookup time, but not the clinical judgment time.

The feedback loop is where the real value emerges. When you track which suggestions coders accept, modify, and reject, you build a dataset that tells you exactly where the system fails. After three months of feedback data, you know which code families need supplementary rules, which documentation patterns confuse the model, and which coders disagree with each other (which is a training opportunity, not a system failure). The suggestion system becomes a quality analytics platform almost by accident.

One more thing: don't overlook the cost model. At $0.01 per 100 characters, processing a 3,000-character note costs $0.30 per API call. If you're processing 500 encounters per day, that's $150/day or $4,500/month just for the Comprehend Medical calls. That's cheap compared to a coder's salary, but it's not nothing. The section-targeted approach (processing only the Assessment/Plan rather than the full note) cuts costs by 60-80% with minimal accuracy loss for code suggestion specifically.

---

## Related Recipes

- **Recipe 1.3 (Lab Requisition Form Extraction):** Uses InferICD10CM in a document extraction context rather than a coding workflow. Shows the same API applied to a different use case.
- **Recipe 8.1 (Chief Complaint Classification):** Short-text classification fundamentals. If you're new to clinical NLP, start there.
- **Recipe 8.4 (Medication Extraction and Normalization):** Complementary extraction that often runs alongside ICD-10 suggestion. Medications contextualize diagnoses.
- **Recipe 8.8 (Clinical Assertion Classification):** The assertion detection problem in depth. Understanding negation and context is critical for accurate code suggestion.
- **Recipe 13.3 (ICD/CPT Hierarchy Navigation):** Knowledge graph approach to navigating the ICD-10 code tree. Useful for building the hierarchical selection UI variation.

---

## Tags

`nlp` `icd-10` `medical-coding` `comprehend-medical` `clinical-nlp` `code-suggestion` `revenue-cycle` `classification` `assertion-detection` `negation` `hipaa` `lambda` `dynamodb` `api-gateway` `simple-medium` `phase-1-2`

---

*← [Recipe 8.2: Patient Sentiment Analysis](chapter08.02-patient-sentiment-analysis) · [Chapter 8 Index](chapter08-preface) · [Recipe 8.4: Medication Extraction and Normalization →](chapter08.04-medication-extraction-normalization)*
