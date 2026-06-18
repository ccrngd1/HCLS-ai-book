# Recipe 8.7: Adverse Event Detection in Clinical Text

**Complexity:** Medium-Complex · **Phase:** Production · **Estimated Cost:** ~$0.40-1.00 per note

---

## The Problem

A patient receives a new blood pressure medication. Two weeks later, they mention to their cardiologist that they've been dizzy every morning since starting it. The cardiologist documents "patient reports orthostatic dizziness, likely related to new amlodipine" in the progress note. That note lives in the EHR. Nobody extracts it. Nobody routes it to pharmacovigilance. Nobody connects it to the three other patients in the same health system who reported the same symptom on the same medication at the same dose.

Six months later, a patient safety officer pulls charts for a quality review and finds 47 mentions of the same adverse reaction buried across progress notes, nursing assessments, and discharge summaries. The signal was there the entire time. It was documented. It just wasn't surfaced.

This is the baseline state of adverse event (AE) detection in healthcare: voluntary reporting systems that capture maybe 5-10% of actual adverse events. The FDA's MedWatch system depends on clinicians taking the time to fill out a form. Hospital incident reporting systems depend on someone recognizing the event as reportable. Spontaneous reporting has been the backbone of post-market drug safety surveillance for decades, and it consistently misses the majority of events. Studies suggest that voluntary reporting captures between 1% and 13% of actual adverse drug events, depending on the severity and the institution.

The information we need is already being documented in clinical text. Every progress note, every nursing assessment, every discharge summary, every telephone encounter note is a potential source of adverse event signals. A patient who develops a rash after starting a new antibiotic. A post-surgical patient whose wound becomes infected at a higher-than-expected rate. A medication interaction that shows up as unexplained fatigue in a dozen patients. These are all documented. They're just not aggregated, classified, or surfaced to the people who need to act on them.

Building a system that automatically detects adverse event mentions in clinical text transforms passive documentation into active surveillance. Instead of waiting for someone to voluntarily report, you scan every note as it's written. Instead of retrospective chart reviews, you get near-real-time signals. The payoff is faster safety responses, better pharmacovigilance, and potentially catching problems before they become widespread.

Let's talk about why "just search for drug side effects in notes" doesn't actually work.

---

## The Technology: Finding Safety Signals in Clinical Prose

### Why Adverse Event Detection Is Harder Than It Sounds

The naive approach sounds simple: build a dictionary of known adverse events, search clinical notes for mentions, correlate with active medications, report matches. Five minutes on a whiteboard and you'd think this is a solved problem.

It isn't. Here's why.

**Adverse events are often described implicitly.** A clinician rarely writes "adverse drug event: rash from amoxicillin." They write "new maculopapular rash, onset three days after starting amoxicillin, suspect drug reaction." Or they just write "rash, discontinue amoxicillin" and let the temporal proximity imply causation. Or they write "itchy bumps on arms" in a telephone note with no explicit connection to any medication at all. The further you get from explicit documentation, the harder extraction becomes.

**Distinguishing expected from unexpected.** Chemotherapy causes nausea. Opioids cause constipation. Antihypertensives cause dizziness. These are expected, dose-dependent effects that are not safety signals in the traditional sense. A system that flags every mention of nausea in an oncology patient's chart would drown safety teams in noise. The interesting signals are the unexpected events: the antibiotic that causes liver injury, the antidepressant that triggers suicidal ideation, the medical device that fails at a higher rate than its literature suggests. Separating expected from unexpected requires knowing what's expected for each drug or intervention, which means maintaining or accessing a comprehensive knowledge base of known effects.

**Temporal reasoning is essential.** An adverse event implies causation (or at least temporal association) between an intervention and an outcome. "Patient developed rash" is not an adverse event if the rash started two weeks before the medication. "Patient had a fall" is not a medication-related event if the patient has a longstanding gait disorder unrelated to their current drugs. Determining whether the timing supports a causal relationship requires extracting temporal information from text that often uses relative time expressions ("since starting the new medication," "over the past few days," "shortly after the procedure").

**Negation and hypothetical context.** "No signs of hepatotoxicity" is not an adverse event. "If the patient develops a rash, discontinue the medication" is a contingency instruction, not a reported event. "The patient's mother had an allergic reaction to penicillin" is family history, not a patient event. Clinical text is full of negations, hypotheticals, and attributions to other people. A system that doesn't handle these contexts will generate a catastrophic false positive rate.

**Severity matters.** A mild headache that resolves on its own is different from a life-threatening anaphylactic reaction. Safety surveillance systems need to prioritize, and priority depends on severity. Extracting severity from clinical text is itself a complex problem: "mild," "moderate," "severe," "life-threatening," "resolved without intervention," "required hospitalization" are all severity signals, but they appear in varied forms across different documentation styles.

**Under-documentation is the norm.** Clinicians don't always document adverse events explicitly, especially mild ones. A patient mentions dry mouth as a side effect; the physician notes it mentally, adjusts nothing, and doesn't document it. These undocumented events are invisible to any NLP system. Your system will always undercount. The question is: by how much, and for which severity levels?

### The NLP Architecture for Adverse Event Detection

The pipeline is more complex than standard clinical NER because it requires reasoning about relationships between entities, not just extracting entities in isolation.

**Stage 1: Entity extraction.** Identify three classes of entities in the text:
- **Interventions:** Medications, procedures, devices, vaccines (anything that could cause an adverse event)
- **Clinical events/findings:** Symptoms, signs, diagnoses, lab abnormalities (anything that could be an adverse event)
- **Temporal expressions:** Dates, durations, relative time references ("after starting," "two days later," "since the surgery")

This is relatively standard biomedical NER. Tools like MetaMap, cTAKES, SciSpacy, and cloud-based medical NLP services handle this well for explicit mentions. The challenge is coverage: your entity extraction needs to be comprehensive, because a missed medication mention means a missed adverse event relationship.

**Stage 2: Assertion classification.** For each extracted clinical event, determine its assertion status:
- **Present/Active:** The event is actually happening to this patient right now
- **Absent/Negated:** Explicitly stated as not present ("no rash," "denies dizziness")
- **Hypothetical/Conditional:** Mentioned as a possibility, not a reality ("if rash develops")
- **Historical:** Happened in the past, not currently active
- **Family history:** Happened to a family member, not the patient

Only "present/active" events are candidates for adverse event classification. Everything else is filtered out. Assertion classification is covered in depth in Recipe 8.8, and it's one of the most impactful preprocessing steps for reducing false positives.

**Stage 3: Relation extraction.** This is the core of adverse event detection: determining whether a clinical event is causally or temporally related to an intervention. This goes beyond co-occurrence in the same note. You need:
- **Temporal plausibility:** Did the event occur after the intervention? Within a plausible time window?
- **Explicit attribution:** Did the clinician state or imply a causal relationship? ("likely due to," "suspect drug reaction," "discontinue due to")
- **Proximity signals:** Are the intervention and event mentioned in the same sentence or paragraph? In the same section of the note?

Relation extraction can be approached as a classification problem: given a pair (intervention, event), classify the relationship as "causal," "temporal association," "no relation," or "negated relation." Training data for this task is scarce, which drives many systems toward rule-based or hybrid approaches.

**Stage 4: Severity and outcome classification.** Assign a severity level to each detected adverse event:
- Grade 1: Mild (asymptomatic or mild symptoms, no intervention required)
- Grade 2: Moderate (minimal intervention, limits activities)
- Grade 3: Severe (hospitalization, significant disability)
- Grade 4: Life-threatening (urgent intervention required)
- Grade 5: Death

The Common Terminology Criteria for Adverse Events (CTCAE) provides a standardized grading framework, but clinical text rarely uses CTCAE terminology explicitly. Inferring severity from narrative text ("required admission to ICU," "resolved without treatment," "patient was intubated") requires pattern matching against outcome indicators.

**Stage 5: Aggregation and signal detection.** Individual adverse event mentions become safety signals when aggregated across patients. A single report of dizziness with a new medication is an anecdote. Fifteen reports in two months is a signal. Aggregation requires:
- Normalizing events to standard terminology (MedDRA preferred terms for adverse events)
- Counting unique patients, not just mentions
- Calculating observed-vs-expected ratios (disproportionality analysis)
- Applying statistical methods to separate signal from noise

### Approaches to Relation Extraction

The "is this event caused by this intervention?" question is the hardest piece. Current approaches:

**Rule-based patterns.** Look for explicit causal language: "due to," "caused by," "secondary to," "as a result of," "attributed to," "likely related to," "discontinue [drug] because of [event]." These patterns have very high precision (when they match, they're almost always correct) but limited recall (many adverse events are documented without explicit causal language).

**Co-occurrence with temporal filtering.** If a medication and a clinical event appear in the same note, and the medication start date precedes the event, flag it as a candidate. Simple, but generates high false positive rates (patients on many medications will have many co-occurrences with unrelated events).

**Supervised classification.** Train a model on annotated pairs of (intervention, event) with labels indicating whether a causal relationship exists. Requires substantial annotated data, which is expensive to create for this task. Performance varies significantly by drug class and event type.

**Knowledge-base filtering.** Use a database of known adverse drug reactions (from FDA labels, SIDER, or FAERS data) to filter candidates. If the detected event is a known adverse effect of the detected drug, boost its relevance score. This helps with known reactions but misses novel signals (which are often the most valuable for pharmacovigilance).

**Hybrid approaches.** Combine rule-based detection for explicit mentions, co-occurrence for implicit associations, and knowledge-base filtering for plausibility scoring. This is what most production systems actually use: layers of evidence that each contribute to an overall confidence score.

### The State of the Art

How well does this stuff actually work? Best research systems hit 80-90% F1 on finding medications and 60-75% on connecting them to adverse events. The n2c2 shared tasks and the TAC ADR track are the main benchmarks here. In production at real health systems, you're looking at 70-85% precision. Translation: you'll catch most of the obvious stuff, miss a good chunk of the implicit stuff, and your safety team will still need to review what you flag.

The honest take: extraction of individual entities (drugs, symptoms) is a largely solved problem. The hard part is the relational reasoning, temporal logic, and severity classification that turn entity lists into actionable adverse event signals.

### The General Architecture Pattern

At a conceptual level:

```text
[Clinical Notes] → [Preprocessing/Section Detection]
    → [Entity Extraction: Drugs, Events, Temporal]
    → [Assertion Filtering: Remove negated/historical/hypothetical]
    → [Relation Extraction: Link events to interventions]
    → [Severity Classification]
    → [Normalization to MedDRA/standard codes]
    → [Aggregation and Signal Detection]
    → [Alert/Report Generation]
```

The pipeline is sequential in the sense that each stage depends on the previous one, but within a stage, processing of individual notes is parallelizable. You're typically running this as a batch job over all notes generated in a time window (daily or hourly), with the aggregation step looking across the full result set.

Data flow considerations:
- **Input:** Clinical notes in HL7 FHIR DocumentReference format, CDA documents, or raw text from EHR integration
- **Intermediate:** Structured annotations (entity spans, assertion labels, relation triples)
- **Output:** Adverse event records with severity, causality confidence, and coded terms suitable for reporting to safety databases or feeding into pharmacovigilance dashboards

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter08.07-architecture). The Python example is linked from there.

## The Honest Take

Here's what actually happens when you deploy adverse event detection in a health system.

The first week, the safety team is drowning. Every note that mentions a symptom near a medication gets flagged. Expected side effects dominate the output. Your pharmacovigilance team, who previously reviewed maybe 20 voluntary reports a month, is now looking at 500 automated detections a week. Most are noise.

The fix is iterative tuning of the expected-effects filter. You need a comprehensive "known and expected" database that you maintain by drug class. Statins cause myalgia. SSRIs cause GI upset. Beta-blockers cause fatigue. None of these are novel safety signals. Filter them out of the alert stream (but keep them in the database for aggregation, because a higher-than-expected rate of a "known" effect can still be a signal).

The hardest false negatives to address are the implicit mentions. "Patient feels worse since last visit" is potentially an adverse event if a new medication was started at the last visit. But connecting "feels worse" to a specific drug requires reasoning across notes, not just within a single note. Cross-note reasoning is architecturally expensive and introduces complexity that most first-generation systems skip. Plan for it in your roadmap but don't try to build it first.

The aggregation step is where the real value emerges, and it takes months. You need a critical mass of processed notes before disproportionality analysis becomes meaningful. In a health system processing 10,000 notes per day, you'll start seeing reliable signals after 2-3 months of operation. Smaller systems need longer. This means your stakeholders need patience, which is not a technology problem but is absolutely a deployment challenge.

One thing that surprised me: the highest-value outputs weren't the individual high-severity alerts (those tend to be caught anyway through existing clinical workflows). The highest value was in moderate-severity events that individually seemed unremarkable but in aggregate revealed a real pattern. Fourteen patients with mild dizziness on the same medication formulation, from the same manufacturer, dispensed in the same quarter. That's a signal that no voluntary reporting system would ever surface.

---

## Related Recipes

- **Recipe 8.4 (Medication Extraction and Normalization):** The entity extraction foundation that this recipe builds upon for identifying drug mentions
- **Recipe 8.5 (Problem List Extraction):** Shares the condition extraction and assertion detection pipeline components
- **Recipe 8.8 (Clinical Assertion Classification):** Provides the assertion filtering layer that removes negated, hypothetical, and historical mentions
- **Recipe 8.9 (Temporal Relationship Extraction):** Provides the temporal reasoning capabilities used in the relation extraction stage
- **Recipe 13.4 (Drug-Drug Interaction Knowledge Base):** The knowledge graph structure used for known ADR lookup and plausibility checking

---

## Tags

`nlp`, `adverse-events`, `pharmacovigilance`, `patient-safety`, `relation-extraction`, `clinical-text`, `surveillance`, `drug-safety`

---

| [← 8.6: SDOH Extraction](chapter08.06-sdoh-extraction) | [Chapter 8 Index](chapter08-preface) | [8.8: Clinical Assertion Classification →](chapter08.08-clinical-assertion-classification) |
