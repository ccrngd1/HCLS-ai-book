# Recipe 13.9: Literature-Derived Knowledge Graph

**Complexity:** Complex · **Phase:** Research/Production Hybrid · **Estimated Cost:** ~$2,000–8,000/month depending on ingestion volume

---

## The Problem

Medical knowledge doubles roughly every 73 days. That's not a typo. The volume of published biomedical literature is growing so fast that no human, no team of humans, and no department of humans can keep up. PubMed alone indexes over 1.5 million new articles per year. Each one potentially contains a new drug-disease relationship, a newly discovered gene-phenotype association, a risk factor that changes clinical guidance, or an interaction that invalidates an existing treatment protocol.

Now picture a precision medicine team at an academic medical center. A patient presents with a rare genetic variant. The oncologist needs to know: has anyone published evidence linking this variant to a specific drug response? The answer might exist in a paper published three weeks ago in a journal nobody on the team reads. It might be buried in the supplementary materials of a genomics study. It might be stated as a secondary finding in a paragraph about something else entirely.

The traditional approach is manual curation. Organizations like PharmGKB, ClinGen, and OMIM employ teams of PhD-level curators who read papers, extract relationships, grade evidence, and enter them into structured databases. This works. It's also expensive, slow, and perpetually behind. PharmGKB, one of the best-funded pharmacogenomics databases, covers roughly 700 genes. The human genome has over 20,000 protein-coding genes. The gap between what's published and what's curated is enormous and growing.

What if you could read every paper automatically, extract the clinical relationships, grade the evidence, resolve conflicts, and maintain a queryable knowledge graph that stays current with the literature? That's what this recipe builds. It won't replace human curation (we'll be honest about why), but it can dramatically accelerate it, surface relationships that curators haven't gotten to yet, and provide a living, queryable representation of what the literature says right now.

---

## The Technology: Extracting Knowledge from Text

### What Is a Literature-Derived Knowledge Graph?

A knowledge graph is a structured representation of entities and the relationships between them. Nodes are things (drugs, diseases, genes, proteins, phenotypes). Edges are relationships between those things ("treats," "causes," "associated_with," "inhibits," "upregulates"). Each edge carries metadata: where the relationship was found, how strong the evidence is, when it was extracted, whether it's been validated.

A literature-derived knowledge graph is one where the source of truth is published text rather than manual curation or structured databases. You're taking unstructured natural language ("In our cohort, patients carrying the CYP2D6*4 allele showed significantly reduced metabolism of codeine") and converting it into structured triples: `(CYP2D6*4, reduces_metabolism_of, codeine)` with provenance pointing back to the source paper, section, and sentence.

### The NLP Pipeline: From Text to Triples

The extraction pipeline has several stages, each with its own failure modes:

**Named Entity Recognition (NER).** First, you identify the biomedical entities in the text. "CYP2D6*4" is a gene variant. "Codeine" is a drug. "Reduced metabolism" is a pharmacokinetic effect. Biomedical NER is harder than general NER because the vocabulary is enormous, entities overlap (is "cold" a disease or a temperature?), and new entity names appear constantly as drugs are developed and genes are characterized. Models trained on biomedical corpora (BioBERT, PubMedBERT, SciBERT) perform significantly better than general-purpose NER models here.

**Relation Extraction (RE).** Once you've identified the entities, you need to determine how they relate to each other within a sentence or passage. Does the text say drug A treats disease B, or does it say drug A was studied in the context of disease B but showed no effect? The distinction matters enormously. Relation extraction models classify the relationship type between entity pairs. This is where most of the errors creep in, because natural language is ambiguous, hedged, and context-dependent. "May be associated with" is not the same as "causes," but a naive model might treat them identically.

**Negation and Speculation Detection.** Medical literature is full of hedging. "We found no significant association between X and Y" contains the entities X and Y and the relationship "association," but the relationship is negated. "Further studies are needed to confirm whether X influences Y" is speculative, not assertive. Missing negation detection is one of the fastest ways to poison your knowledge graph with false positives.

**Entity Normalization.** The same concept appears under many names. "Breast cancer," "breast carcinoma," "mammary neoplasm," and "BRCA" all refer to overlapping (but not identical) concepts. Entity normalization maps extracted mentions to canonical identifiers in standard ontologies: UMLS CUIs, MeSH terms, HGNC gene symbols, RxNorm drug codes. Without normalization, your graph will have dozens of disconnected nodes that should be one.

**Evidence Grading.** Not all papers are equal. A randomized controlled trial with 10,000 patients provides stronger evidence than a case report with one patient. Your extraction pipeline needs to assess (or at least approximate) the strength of evidence behind each extracted relationship. This can be based on study design (RCT > cohort > case report), sample size, journal impact factor, citation count, or a combination. It's imperfect, but it's better than treating all extractions as equally reliable.

**Conflict Resolution.** The literature contradicts itself. Paper A says drug X is effective for disease Y. Paper B says it isn't. Both are published in reputable journals. Your knowledge graph needs a strategy for handling contradictions: store both with their evidence grades, flag the conflict for human review, or apply a voting mechanism weighted by evidence quality. There's no perfect answer here. The important thing is having a strategy rather than letting the last-ingested paper silently overwrite the previous one.

### Why This Is Genuinely Hard

Let me be direct about the failure modes:

**Precision vs. recall tradeoff.** High-precision extraction (only extracting relationships you're very confident about) misses a lot of knowledge. High-recall extraction (extracting everything that might be a relationship) floods your graph with noise. In healthcare, false positives in a knowledge graph can influence clinical decisions. A spurious "drug X treats disease Y" relationship that a clinician trusts is dangerous. Most production systems err heavily toward precision and accept lower recall.

**Context windows and coreference.** A relationship might span multiple sentences or even multiple paragraphs. "We administered metformin to the treatment group. After 12 weeks, HbA1c levels decreased significantly." The relationship (metformin, reduces, HbA1c) requires connecting information across sentences. Coreference resolution ("the treatment group" refers to patients receiving metformin) adds another layer of complexity.

**Scale and freshness.** PubMed adds thousands of articles daily. If your pipeline takes a week to process a batch, you're perpetually behind. If it processes in real-time but makes more errors under speed pressure, you're trading freshness for accuracy. The right balance depends on your use case: a drug safety surveillance system needs near-real-time; a research knowledge base can tolerate weekly updates.

**Evaluation is expensive.** How do you know your extraction pipeline is correct? You need domain experts (MDs, PhDs, pharmacologists) to review extracted triples and judge whether they're accurate. This is slow, expensive, and doesn't scale. Most teams evaluate on a sample and extrapolate, which means errors in the long tail go undetected.

### The General Architecture Pattern

```
[Literature Sources] → [Document Ingestion] → [NLP Pipeline] → [Triple Extraction]
    → [Normalization] → [Evidence Grading] → [Conflict Resolution]
    → [Knowledge Graph Store] → [Query Interface] → [Downstream Applications]
```

**Literature Sources.** PubMed/MEDLINE for abstracts. PubMed Central (PMC) for full text (where available under open access). Preprint servers (bioRxiv, medRxiv) for cutting-edge findings. Clinical trial registries (ClinicalTrials.gov) for study results. Optionally: FDA drug labels, clinical guidelines, and patent filings.

**Document Ingestion.** Fetch new articles on a schedule. Parse XML/JSON formats. Extract title, abstract, full text (if available), metadata (authors, journal, date, MeSH terms, study type). Store raw documents for reprocessing.

**NLP Pipeline.** Sentence segmentation, tokenization, biomedical NER, relation extraction, negation detection, entity normalization. This can be a single large model (end-to-end) or a pipeline of specialized models (modular). The modular approach is easier to debug and improve incrementally.

**Triple Extraction.** Convert NLP output into structured (subject, predicate, object) triples with metadata: source document, sentence, confidence score, extraction timestamp.

**Normalization.** Map entities to canonical ontology identifiers. Merge duplicate nodes. Resolve synonyms.

**Evidence Grading.** Score each triple based on source quality, study design, sample size, replication across papers.

**Conflict Resolution.** Detect contradictory triples. Flag for review or apply automated resolution strategy.

**Knowledge Graph Store.** A graph database (property graph or RDF triple store) that supports efficient traversal queries, full-text search on node/edge properties, and temporal versioning.

**Query Interface.** SPARQL or Cypher queries for structured access. Natural language query interface for clinical users. API for downstream application integration.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter13.09-architecture). The Python example is linked from there.

## The Honest Take

Here's what will surprise you when you build this:

The NLP extraction is not the hardest part. Getting 75% precision on relation extraction is achievable with off-the-shelf models and a week of fine-tuning. The hard parts are everything around the NLP: entity normalization (the long tail of synonyms is endless), evidence grading (how do you automatically distinguish a well-powered RCT from a pilot study?), and conflict resolution (the literature genuinely contradicts itself, and both sides often have reasonable evidence).

Your graph will be noisy. Accept this early. A literature-derived knowledge graph is not a curated database. It's a probabilistic representation of what the literature says, with confidence scores and provenance. The value is in surfacing relationships that human curators haven't gotten to yet, not in replacing curated databases for high-stakes clinical decisions. Frame it as "hypothesis generation" rather than "clinical truth" and you'll set appropriate expectations.

The normalization problem is bottomless. You'll get 90% of entities normalized in the first month. The remaining 10% will take forever because they're novel compounds, non-standard gene nomenclature, or ambiguous abbreviations that could mean three different things depending on context. Build a feedback loop where unmapped entities are periodically reviewed and added to your normalization dictionaries.

Reprocessing is your secret weapon. When you improve your RE model (and you will, continuously), you can re-run the entire pipeline against your document lake. This means your graph quality improves retroactively. Design for this from day one: store raw documents, track which model version produced each extraction, and build the infrastructure to do bulk reprocessing without disrupting live queries.

The comparison to curated databases is unfair but inevitable. Stakeholders will compare your automatically extracted graph to PharmGKB or DrugBank and note the errors. The right framing: curated databases are high-precision, low-recall, and months behind the literature. Your graph is moderate-precision, higher-recall, and days behind the literature. They're complementary, not competing.

---

## Related Recipes

- **Recipe 13.4 (Drug-Drug Interaction Knowledge Base):** Uses curated sources rather than literature extraction; the literature-derived graph can feed new candidate interactions into the curated DDI system
- **Recipe 13.7 (Disease-Gene-Drug Relationship Graph):** Focuses on a specific relationship type that this recipe extracts as part of a broader graph
- **Recipe 13.8 (Medical Concept Normalization and Mapping):** The normalization infrastructure built in 13.8 is directly reusable as the entity normalization layer in this recipe
- **Recipe 8.10 (Phenotype Extraction for Research):** Uses similar NLP techniques for entity extraction from clinical text rather than published literature
- **Recipe 2.7 (Literature Search and Evidence Synthesis):** Complementary approach using LLMs for literature understanding; can consume this recipe's graph as structured context

---

## Tags

`knowledge-graph` · `nlp` · `relation-extraction` · `biomedical-literature` · `neptune` · `comprehend-medical` · `sagemaker` · `evidence-grading` · `entity-normalization` · `pubmed` · `complex` · `research` · `pharmacogenomics` · `drug-discovery`

---

*← [Recipe 13.8: Medical Concept Normalization and Mapping](chapter13.08-medical-concept-normalization-mapping) · [Chapter 13 Index](chapter13-preface) · [Recipe 13.10: Federated Clinical Knowledge Network →](chapter13.10-federated-clinical-knowledge-network)*
