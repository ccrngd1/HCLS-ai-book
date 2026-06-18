# Recipe 8.9: Temporal Relationship Extraction

**Complexity:** Complex · **Phase:** Advanced NLP Pipeline · **Estimated Cost:** ~$0.03 per note

---

## The Problem

A discharge summary reads: "Patient admitted on March 3 with acute cholecystitis. Started on IV antibiotics. Pain improved after 48 hours. Laparoscopic cholecystectomy performed on March 6. Discharged home on postoperative day 1 in stable condition."

A human reads this and immediately constructs a timeline: admission, then antibiotics, pain improvement two days later, surgery on day four, discharge the next day. Five events, an unambiguous temporal ordering, and a clear story of clinical progression.

Now try to get a computer to build that timeline.

The text gives you one explicit date (March 3), one derived date (March 6), one relative time expression ("after 48 hours"), one domain-specific temporal anchor ("postoperative day 1"), and one completely implicit ordering (antibiotics started sometime between admission and pain improvement, probably within hours, but that's your clinical inference talking, not anything stated in the text). Oh, and the discharge date? Nowhere explicitly. You have to calculate it: March 6 surgery + 1 day = March 7. A computer that just extracts dates misses most of the temporal structure.

This is the default state of clinical documentation. Clinicians write narratives, not timelines. They assume the reader has enough medical context to infer temporal ordering from clinical logic. "Started antibiotics. Cultures grew E. coli at 72 hours." No reader wonders which came first. But a machine parsing that text sees two events with no explicit temporal connective between them.

The impact of getting temporal relationships wrong propagates everywhere:

A medication reconciliation system needs to know whether "metoprolol 50mg" was the dose before or after the dose change documented in the same note. A clinical trial screening system needs to know if the patient's cancer diagnosis preceded or followed their kidney transplant (different eligibility criteria). A pharmacovigilance system needs to know if the adverse event happened before or after the suspect medication was administered (the entire causality assessment depends on this temporal ordering). A care timeline displayed to a covering physician at 2 AM needs events in the right order, or clinical decisions get made on scrambled information.

Without temporal relationship extraction, you have a bag of clinical events floating in time with no anchoring, no ordering, and no duration. You have facts without a story. And in medicine, the story is the diagnosis.

---

## The Technology: Teaching Machines to Understand Clinical Time

### What Is Temporal Relationship Extraction?

Temporal relationship extraction (sometimes called temporal relation classification or temporal ordering) is the task of identifying how events and time expressions relate to each other in time. Given two items (events, dates, durations, or temporal markers), the system determines whether one is before, after, overlapping, contained within, or simultaneous with the other.

The standard temporal relationships (formalized by TimeML and adopted by the clinical NLP community through the i2b2 2012 shared task and THYME corpus) are:

- **BEFORE:** Event A happened before Event B. ("Diagnosed with diabetes. Later developed neuropathy.")
- **AFTER:** Event A happened after Event B. (Inverse of BEFORE.)
- **OVERLAP:** Events A and B were happening at the same time, at least partially. ("While on chemotherapy, patient developed neutropenia.")
- **BEGINS-ON:** Event A starts at the same time as Event B. ("Surgery commenced at the same time as anesthesia induction.")
- **ENDS-ON:** Event A ends at the same time as Event B.
- **CONTAINS:** Event A's duration entirely includes Event B. ("During the hospitalization, patient developed C. diff.")
- **SIMULTANEOUS:** Events A and B happened at the same point in time.
- **BEFORE-OVERLAP:** Event A begins before Event B but overlaps with it.

In practice, most clinical systems collapse these into a smaller set: BEFORE, AFTER, OVERLAP, and CONTAINS. The fine-grained distinctions (BEGINS-ON, ENDS-ON) are rarely annotated consistently enough to train on.

The task has three sub-components:

1. **Temporal expression recognition:** Find time expressions in text ("March 3," "48 hours later," "postoperatively," "two weeks ago").
2. **Event identification:** Find clinical events (typically already done by entity extraction from prior recipes, but temporal systems need to recognize event-like concepts beyond standard medical entities).
3. **Relation classification:** For each pair of temporal entities (event-event, event-time, time-time), classify the temporal relationship.

### Why This Is Genuinely Hard

Temporal relationship extraction is considered one of the hardest tasks in clinical NLP. Here's why, and I'm not exaggerating the difficulty.

**Clinical text rarely uses explicit dates.** A study of discharge summaries found that fewer than 20% of temporal relationships are anchored to absolute dates. The rest use relative expressions ("two days later," "prior to admission"), domain-specific conventions ("POD#1," "HD3"), section-based implicit ordering (events listed in a section appear in the order they happened, usually), or no temporal cue at all (the reader is expected to infer ordering from clinical logic).

**Temporal reasoning is multi-hop.** "Started metformin on Monday. Blood glucose normalized after one week. Dose reduced the following visit." To place "dose reduced" on a timeline, you need: Monday + 1 week = the following Monday for glucose normalization, then "following visit" which is contextually the next scheduled appointment, which could be days or weeks later. Each step depends on resolving the previous one. Errors compound.

**Vague and underspecified expressions are the norm.** "Recently," "a few days ago," "in the past," "chronic," "acute onset." These are clinically meaningful (they convey urgency, chronicity, and relevance) but temporally imprecise. The system must represent this imprecision rather than forcing a specific date.

**Section structure creates implicit temporal context.** "History of Present Illness" describes events leading up to now. "Past Medical History" is everything before the current episode. "Assessment and Plan" is present and future. The same event mentioned in different sections carries different temporal anchoring. A system that ignores section boundaries will conflate historical and current events.

**Negated and hypothetical events still have temporal properties.** "If fever recurs after discharge, start antibiotics." This hypothetical event (fever recurrence) has a temporal anchor (after discharge) and a temporal relationship with another hypothetical event (starting antibiotics). Whether to include hypothetical temporal relationships in your timeline depends on your downstream use case, but the system needs to at least recognize them.

**Document creation time vs. event time.** The note was written today, but describes events from the past week. "Yesterday the patient reported..." means a different date depending on when the note was authored. Clinical notes are frequently authored hours or days after the events they describe (batch charting is endemic). Your system needs a reliable document timestamp as an anchor, and needs to know that temporal expressions are relative to that anchor, not to processing time.

**Cross-document temporal reasoning.** A patient's timeline spans hundreds of documents across years. An event in today's note ("recurrence of left knee pain, last seen in 2019") creates a temporal link back to a note from seven years ago. Building a longitudinal timeline requires cross-document coreference resolution (recognizing that "the knee pain" in multiple notes refers to the same episode) combined with temporal anchoring. This is arguably a separate (even harder) problem, but it's where the real clinical value lives.

### How Temporal Relationship Extraction Works

The technical approaches, from simplest to most sophisticated:

**Rule-based temporal parsing.** Libraries like HeidelTime and SUTime use hand-crafted rules and regular expressions to identify temporal expressions and normalize them to calendar dates. They handle the standard patterns well ("March 3, 2024," "two weeks ago," "last Tuesday") and produce ISO 8601 normalized values. For clinical text, domain-specific extensions add patterns like "POD#2" (postoperative day 2), "HD5" (hospital day 5), "T+3" (transplant day 3). Rule-based parsers are fast, deterministic, and easy to debug, but they only handle the explicit temporal expressions. They don't classify relationships between events.

**Feature-engineered classifiers.** The classic ML approach: extract features from two candidate entities and their surrounding context (distance between them in the text, section headers, tense markers, temporal signal words like "before," "after," "during," "then"), and train a multi-class classifier (SVM, random forest, or CRF). The 2012 i2b2 shared task established benchmarks for this approach, with top systems achieving F1 around 0.69 for temporal relation classification. The relatively low F1 reflects the genuine difficulty of the task, not poor engineering.

**Neural approaches and transformers.** Fine-tune a pre-trained language model on temporal relation classification. The two entities are marked in the input sequence (using special tokens), and the model predicts the temporal relation class. Clinical transformer models (ClinicalBERT, BioBERT) provide better initialization than general-purpose models because they've seen the temporal conventions of medical text. State-of-the-art systems on the THYME corpus achieve F1 around 0.75-0.80 for temporal relation classification. Still far from solved.

**Graph-based and constraint-based approaches.** Temporal relations form a graph: if A is BEFORE B, and B is BEFORE C, then A must be BEFORE C (transitivity). Constraint-based systems exploit this structure to infer relations not directly stated in text. If the classifier is confident that A BEFORE B and B BEFORE C, it can infer A BEFORE C even if the text never explicitly states the relationship between A and C. Allen's interval algebra provides the formal framework. This approach dramatically increases coverage (the number of entity pairs with assigned relations) but can propagate errors if the initial classifications are wrong.

**Hybrid pipelines** (the production reality): rule-based temporal expression recognition (HeidelTime or custom rules for clinical patterns) combined with ML-based event detection and neural relation classification, post-processed with temporal constraint propagation. Each component handles what it's best at.

### Clinical Temporal Vocabulary

Clinical text uses temporal language that doesn't appear in general-domain training data. Your system needs to handle:

| Pattern | Meaning | Example |
|---------|---------|---------|
| POD#N | Postoperative Day N | "POD#2: drains removed" |
| HD#N | Hospital Day N | "HD3: patient afebrile" |
| T+N | Days after transplant | "T+14: engraftment confirmed" |
| DOL#N | Day of Life (neonates) | "DOL3: bilirubin rising" |
| PMA | Postmenstrual Age (NICU) | "PMA 34 weeks" |
| s/p | Status post (after) | "s/p CABG x3 (2019)" |
| p/w | Presents with (current) | "p/w acute chest pain" |
| Pre-op / Post-op | Before/after surgery | "Pre-op labs normal" |
| Cycle N Day D | Chemotherapy timing | "Cycle 3 Day 1: started" |
| Gestational age | Pregnancy timing | "GA 28+3 weeks" |

These patterns are nearly universal in clinical text and completely absent from general NLP training corpora. If your temporal parser can't handle them, it's missing a significant fraction of the temporal structure.

### Where the Field Is Today

Temporal relationship extraction remains one of the hardest benchmarks in clinical NLP. A few honest observations:

**The 2012 i2b2 task remains the primary benchmark.** Top-performing systems on the THYME (Temporal Histories of Your Medical Events) corpus, which extended the i2b2 work, achieve F1 around 0.75-0.80 on temporal relation classification. For context, the simpler task of temporal expression recognition is largely solved (F1 > 0.90). It's the relation classification, especially between events with no explicit temporal cue, that remains hard.

**Transfer learning helps but doesn't solve the problem.** Pre-trained clinical language models improve performance by 5-10 F1 points over non-clinical models, but the task remains far from saturated. The fundamental challenge is that temporal reasoning often requires world knowledge (antibiotics come before cultures result, discharge happens after the treating condition resolves) that even clinical language models don't reliably capture.

**Annotation is expensive.** Temporal relation annotation requires clinical expertise and takes 5-10x longer than entity annotation. Inter-annotator agreement on temporal relations is lower than on entity extraction (Cohen's kappa around 0.7-0.8 vs. 0.85+ for entities). This limits the size of available training corpora.

**Clinical utility is high but deployment is rare.** Despite a decade of research, production temporal relationship extraction systems are uncommon outside major academic medical centers. The complexity of the problem, the annotation cost, and the difficulty of integration with existing clinical workflows have slowed adoption.

---

## General Architecture Pattern

The temporal relationship extraction pipeline at a conceptual level:

```text
[Clinical Text] → [Preprocessing] → [Temporal Expression Recognition] → [Event Detection] → [Candidate Pair Generation] → [Relation Classification] → [Temporal Graph Construction] → [Timeline Output]
```

**Preprocessing.** Section segmentation (identifying HPI, PMH, Assessment sections), sentence splitting (clinical text has non-standard sentence boundaries), and document metadata extraction (author, date created, encounter type). The document creation timestamp is critical because relative temporal expressions anchor to it.

**Temporal Expression Recognition.** Identify and normalize time expressions: absolute dates ("March 3, 2024"), relative expressions ("two days ago," "last week"), durations ("for 3 months"), frequencies ("twice daily"), and domain-specific patterns ("POD#2," "HD5"). Normalize each to a standard representation (ISO 8601 where possible, or a relative offset from the document timestamp).

**Event Detection.** Identify clinical events that have temporal properties. This extends beyond standard medical entity recognition: events include procedures, symptoms onset, medication starts/stops, hospitalizations, test orders, and result availability. Each event gets annotated with attributes: type (clinical event, test, treatment), polarity (positive, negated), modality (actual, hypothetical, conditional).

**Candidate Pair Generation.** Not every pair of entities needs a temporal relationship. With N entities in a note, there are N*(N-1)/2 possible pairs. At 50 entities per note, that's 1,225 pairs. Most are irrelevant. Candidate pair generation uses heuristics to filter: same-sentence pairs, adjacent-sentence pairs, pairs sharing a temporal signal word, and pairs within the same section. This reduces the classification workload by 80-90% without meaningful recall loss.

**Relation Classification.** For each candidate pair, classify the temporal relationship: BEFORE, AFTER, OVERLAP, CONTAINS, or NONE (no temporal relationship). This is the hardest step. The classifier uses features from both entities, their surrounding context, section membership, temporal signal words between them, and any temporal expressions anchoring either entity.

**Temporal Graph Construction.** Assemble all classified relations into a directed graph. Nodes are events and time expressions. Edges are temporal relations. Apply temporal constraint propagation: if A BEFORE B and B BEFORE C, infer A BEFORE C. Detect and resolve inconsistencies (if the classifier says both A BEFORE B and B BEFORE A, something is wrong). The graph is the complete temporal structure of the document.

**Timeline Output.** Flatten the temporal graph into a linear timeline for consumption by downstream systems. Assign absolute timestamps where possible (using normalized temporal expressions as anchors and propagating through the graph). Where absolute times are unavailable, maintain relative ordering. The output is a sequence of events with timestamps (exact or approximate) and confidence scores.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter08.09-architecture). The Python example is linked from there.

## The Honest Take

Temporal relationship extraction is one of those problems where the research papers report 0.75 F1 and you think "that's not great but it's something." Then you deploy it and realize that 0.75 F1 on curated benchmark data translates to maybe 0.60 on your institution's actual clinical notes, because your neurologists write differently than the training corpus, your EHR templates create weird formatting artifacts, and half your notes have batch-charted timestamps that don't match the event times.

The thing that surprised me most: the temporal expression recognition part is basically solved. HeidelTime and similar tools handle 90%+ of temporal expressions correctly. The hard part, the thing that makes this a "complex" recipe, is the relationship classification between events. Specifically, the implicit temporal relationships where there's no explicit signal word and the ordering relies on clinical reasoning ("antibiotics started, then cultures resulted" implies BEFORE because that's how clinical practice works, not because the text says "before").

If I were starting over, I'd spend less time on the relation classifier and more time on the candidate pair generation. The truth is that most temporal relationships in a clinical note follow one of a few patterns: events listed in narrative order are chronological, events in the same sentence with a temporal connective have that relationship, and events anchored to the same temporal expression overlap. A rule-based system covering just those patterns gets you 70% of the way there. The ML classifier handles the remaining 30% of ambiguous cases, and honestly gets a meaningful fraction of those wrong.

The other thing: cross-document temporal reasoning (stitching together timelines from multiple notes over months or years) is the real clinical value. But it's 10x harder than single-document extraction because you need coreference resolution (is "the knee pain" in today's note the same episode as "left knee arthralgia" from six months ago?) and you need to handle contradictions between documents. Most production systems punt on cross-document and just do single-document timelines. Reasonable, but it means the longitudinal patient story remains fragmented.

My honest recommendation: if your use case is building a visual timeline for clinician review (where a human verifies and corrects), temporal extraction at 0.70-0.75 accuracy is genuinely useful. It gets the ordering roughly right and the clinician fixes the errors in seconds. If your use case is feeding temporal relationships into an automated system (pharmacovigilance causality assessment, clinical trial eligibility screening), you need higher accuracy than the current state of the art provides, and you should plan for a human-in-the-loop.

---

## Related Recipes

- **Recipe 8.4 (Medication Extraction and Normalization):** Provides the medication events that temporal extraction places on a timeline
- **Recipe 8.5 (Problem List Extraction):** Provides diagnosis events; temporal extraction determines whether they're current, historical, or resolved
- **Recipe 8.7 (Adverse Event Detection):** Temporal extraction determines whether an adverse event occurred before or after a suspect medication, enabling causality assessment
- **Recipe 8.8 (Clinical Assertion Classification):** Assertion status (present, historical, hypothetical) and temporal relationships are closely related; assertion classification feeds temporal anchoring
- **Recipe 12.8 (Disease Progression Trajectory Modeling):** Consumes structured patient timelines as input features for trajectory prediction
- **Recipe 13.9 (Literature-Derived Knowledge Graph):** Temporal extraction applied to published literature to build evidence timelines

---

## Tags

`nlp` · `temporal-reasoning` · `timeline` · `clinical-events` · `relation-extraction` · `comprehend-medical` · `comprehend-custom` · `neptune` · `complex` · `hipaa` · `research`

---

*← [Recipe 8.8: Clinical Assertion Classification](chapter08.08-clinical-assertion-classification) · [Chapter 8 Index](chapter08-preface) · [Next: Recipe 8.10: Phenotype Extraction for Research →](chapter08.10-phenotype-extraction-research)*
