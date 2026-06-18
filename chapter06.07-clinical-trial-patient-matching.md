# Recipe 6.7: Clinical Trial Patient Matching

**Complexity:** Medium-Complex · **Phase:** Growth · **Estimated Cost:** ~$0.20–$0.75 per patient screened (depending on criteria complexity and NLP requirements)

---

## The Problem

There's a clinical trial for a promising new GLP-1 receptor agonist combination therapy. It's recruiting at your health system. The inclusion criteria specify: adults 30-65 with Type 2 diabetes, A1C between 7.5 and 10.5, on metformin monotherapy for at least 90 days, BMI over 27, no history of pancreatitis, no eGFR below 45, no active cancer diagnosis in the past 5 years, and willing to discontinue any SGLT2 inhibitors.

The research coordinator has a list of 180,000 patients in the health system's diabetes registry. She needs to find the ones who might qualify. Today, that means manually reviewing charts. One by one. Checking labs, medication lists, problem lists, procedure histories. A good coordinator can screen maybe 20 charts per hour. At that rate, screening the full registry would take over a year. The trial closes enrollment in four months.

This is not an edge case. This is the default state of clinical trial recruitment in 2026. The Tufts Center for the Study of Drug Development has reported that 80% of clinical trials fail to meet enrollment timelines. Not because eligible patients don't exist, but because finding them is a manual, exhausting process that doesn't scale. Sites leave money on the table. Patients who could benefit from experimental therapies never hear about them. Trials take longer, cost more, and sometimes fail entirely because they can't recruit fast enough.

The information needed to determine eligibility is already in the EHR. Lab results, medication lists, diagnosis codes, procedure histories, clinical notes. It's all there. The problem is that eligibility criteria are expressed in clinical language ("no history of pancreatitis") while the data lives in structured codes (ICD-10: K85.x, K86.1) and unstructured notes ("Patient reports episode of acute pancreatitis in 2019"). Bridging that gap at scale is the core technical challenge.

When this works, a research coordinator starts her day with a pre-screened list of 200 likely-eligible patients instead of a registry of 180,000. She spends her time on the nuanced judgment calls (is this patient actually willing to participate? does their schedule allow weekly visits?) rather than on mechanical chart review. Enrollment timelines compress. More patients get access to experimental therapies. Trials complete faster.

---

## The Technology: How Automated Trial Matching Works

### The Eligibility Criteria Problem

Clinical trial eligibility criteria are deceptively complex. A typical Phase III trial has 30-50 individual criteria, split between inclusion (must have) and exclusion (must not have). Each criterion maps to one or more data elements in the patient record, and the mapping is rarely straightforward.

Consider a single exclusion criterion: "No history of cardiovascular event within the past 12 months." To evaluate this computationally, you need to:

1. Define what counts as a "cardiovascular event" (MI, stroke, TIA, unstable angina, heart failure hospitalization, PCI, CABG?)
2. Map each of those to the relevant ICD-10, CPT, and SNOMED codes
3. Search the patient's problem list, encounter diagnoses, and procedure history
4. Apply the temporal constraint (within 12 months of what? screening date? enrollment date?)
5. Handle negation in clinical notes ("no history of MI" should not trigger a match)
6. Handle uncertainty ("possible TIA in 2023, workup inconclusive")

Multiply that by 40 criteria and you start to see why this is hard. Each criterion is a mini-NLP and data integration problem.

### Structured vs. Unstructured Data

Patient eligibility information lives in two places, and you need both.

**Structured data** includes diagnosis codes (ICD-10), procedure codes (CPT, HCPCS), medication lists (RxNorm), lab results (LOINC), vital signs, and demographics. This is the easy part. You can write deterministic rules: "A1C between 7.5 and 10.5" maps directly to a LOINC code and a value range. "On metformin for at least 90 days" maps to an active medication with a start date.

**Unstructured data** includes clinical notes, discharge summaries, pathology reports, and radiology reports. This is where the hard cases live. "No history of pancreatitis" might only be documented in a note from three years ago. "Willing to discontinue SGLT2 inhibitors" is a patient preference that exists nowhere in structured data until someone asks. Allergies, surgical history, social history, and family history are often documented in free text even when structured fields exist.

The practical split varies by criterion type. Demographics and labs are almost always structured. Medication history is mostly structured (but "patient reports taking herbal supplements" is not). Diagnosis history is partially structured (coded diagnoses) and partially unstructured (mentioned in notes but never formally coded). Exclusion criteria based on patient willingness, lifestyle factors, or nuanced clinical history almost always require NLP on notes.

### NLP for Criteria Extraction

Two NLP tasks dominate clinical trial matching:

**Criteria parsing:** Taking the eligibility criteria text (often written in semi-structured clinical language) and decomposing it into computable assertions. "Adults aged 30-65 with Type 2 diabetes" becomes three assertions: age >= 30, age <= 65, has_diagnosis(E11.x). This can be done with rule-based parsers for well-structured criteria, or with LLMs for more complex natural language criteria.

**Clinical note mining:** Extracting relevant clinical facts from patient notes to evaluate criteria that can't be resolved from structured data alone. This includes entity extraction (finding mentions of conditions, medications, procedures), negation detection ("denies history of pancreatitis"), temporal reasoning ("diagnosed in 2019"), and assertion classification (is this a confirmed finding, a suspected finding, or a family history?).

Negation detection deserves special attention. Clinical notes are full of negated findings: "no chest pain," "denies shortness of breath," "no family history of colon cancer." A naive keyword search for "pancreatitis" in notes will match "no history of pancreatitis" and incorrectly exclude the patient. Negation-aware NLP (algorithms like NegEx, or transformer-based models trained on clinical text) is essential.

### The Matching Architecture

At a conceptual level, trial matching is a multi-stage filter:

**Stage 1: Structured pre-screen.** Apply all criteria that can be evaluated from structured data alone. This is fast, deterministic, and eliminates the bulk of the population. If a trial requires A1C > 7.5 and 85% of your diabetes registry has A1C below that threshold, you've just reduced your candidate pool by 85% before touching a single clinical note.

**Stage 2: NLP-based deep screen.** For candidates that pass the structured pre-screen, apply NLP to clinical notes to evaluate criteria that require unstructured data. This is slower and more expensive per patient, but you're only running it on the pre-screened subset.

**Stage 3: Scoring and ranking.** Not all candidates are equally likely to be eligible. Some meet every structured criterion clearly. Others are borderline (A1C of 7.4 when the threshold is 7.5, but the lab is from 3 months ago and might have drifted). Score candidates by confidence of eligibility and surface the highest-confidence matches first.

**Stage 4: Human review.** A research coordinator reviews the top candidates, confirms eligibility through chart review, and initiates outreach. The system doesn't replace the coordinator; it focuses their attention on the most promising candidates.

This staged approach is critical for cost and performance. Running full NLP on 180,000 patients is expensive and slow. Running it on the 2,000 who pass structured pre-screening is manageable.

### Similarity-Based Approaches

Beyond rule-based matching, there's a complementary approach: find patients who are similar to previously enrolled patients. If you have data from patients who successfully enrolled in similar trials, you can build a similarity model that identifies new candidates based on their resemblance to past enrollees.

This works particularly well for:
- Trials with complex, multi-dimensional criteria that are hard to decompose into individual rules
- Identifying patients who are "close" to eligibility (might qualify with a medication washout or after a lab recheck)
- Prioritizing outreach when you have more candidates than you can contact

The similarity approach complements rule-based matching rather than replacing it. Rules give you precision (definitive yes/no on specific criteria). Similarity gives you recall (finding candidates you might have missed because a criterion was ambiguously documented).

### Temporal Reasoning

Clinical trial criteria are deeply temporal. "On metformin for at least 90 days" requires knowing when the medication was started. "No cardiovascular event in the past 12 months" requires knowing when events occurred relative to the screening date. "A1C between 7.5 and 10.5" implicitly means a recent A1C (a value from 2 years ago is clinically irrelevant).

Temporal reasoning in healthcare data is harder than it looks:

- Medication start dates are often approximate (the prescription was written on date X, but when did the patient actually start taking it?)
- Diagnosis dates may reflect when the code was entered, not when the condition began
- Lab values have a "freshness" window that varies by analyte (A1C is stable for ~3 months; potassium changes daily)
- "History of" is ambiguous (does it mean ever, or within some implied window?)

Your matching system needs explicit temporal logic: what's the acceptable recency window for each data element? How do you handle missing dates? What's the default assumption when timing is ambiguous?

---

## General Architecture Pattern

```
[Trial Registry] → [Criteria Parser] → [Computable Criteria]
                                              ↓
[Patient Data Store] → [Structured Pre-Screen] → [Candidate Pool]
                                                       ↓
[Clinical Notes] → [NLP Pipeline] → [Deep Screen] → [Scored Candidates]
                                                           ↓
                                                    [Coordinator Worklist]
```

**Stage 1: Criteria Ingestion.** Trial eligibility criteria are parsed into a computable representation. Each criterion becomes a rule with a data source (structured or unstructured), a logic operator, and a temporal constraint.

**Stage 2: Structured Pre-Screen.** Query structured patient data (demographics, labs, medications, diagnoses) against all criteria that can be evaluated deterministically. Eliminate patients who definitively fail any inclusion criterion or definitively meet any exclusion criterion.

**Stage 3: NLP Deep Screen.** For remaining candidates, run NLP on clinical notes to evaluate criteria that require unstructured data. Extract relevant entities, detect negation, apply temporal reasoning.

**Stage 4: Scoring and Ranking.** Assign each candidate a confidence score based on how clearly they meet each criterion. Criteria with high-confidence structured data matches score higher than criteria resolved through NLP with moderate confidence.

**Stage 5: Coordinator Worklist.** Present ranked candidates to research coordinators with per-criterion evidence (which data elements matched, from which source, with what confidence). The coordinator makes the final eligibility determination.

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter06.07-architecture). The Python example is linked from there.

## The Honest Take

The structured pre-screen is the part that works reliably. Demographics, labs, medications, diagnosis codes: these are well-defined, queryable, and deterministic. If a patient's A1C is 6.2 and the trial requires > 7.5, that's a definitive exclusion. No ambiguity. You can build this part in a few weeks and it immediately saves coordinator time.

The NLP piece is where things get interesting and frustrating in equal measure. Negation detection has gotten genuinely good (Comprehend Medical handles it well for common patterns), but complex sentence structures still trip it up. "Patient reports that her mother had breast cancer but she herself has never been diagnosed with any malignancy" contains both a family history mention and a personal negation. Getting that right consistently requires either very good models or very careful prompt engineering.

The biggest surprise in production: the criteria that seem simplest are often the hardest. "On metformin monotherapy for at least 90 days" sounds straightforward until you realize that medication lists in EHRs are notoriously unreliable. Medications get added but never removed. Patients stop taking drugs without telling anyone. The "active medication list" is aspirational, not factual. You end up needing pharmacy fill data (which requires a separate integration) to have any confidence in medication duration.

The precision/recall tradeoff is real and you need to make it explicit with your research team. High precision (only surface patients who are almost certainly eligible) means coordinators waste less time but you miss eligible patients. High recall (surface anyone who might be eligible) means more coordinator work but fewer missed opportunities. Most sites start with high recall and tighten over time as they calibrate.

One more thing: the system gets dramatically more useful when you have multiple active trials. Screening for one trial is a project. Screening for 20 trials simultaneously against the same patient population is where the ROI compounds. A patient who doesn't qualify for Trial A might be perfect for Trial B. Build the system to handle multiple concurrent trials from day one.

---

## Related Recipes

- **Recipe 6.6 (Patient Similarity for Care Planning):** Uses the same similarity infrastructure but for care planning rather than trial matching. The feature engineering and distance metric concepts transfer directly.
- **Recipe 5.6 (Claims-to-Clinical Data Linkage):** The data integration challenge of combining structured and unstructured patient data is shared between trial matching and record linkage.
- **Recipe 8.8 (NLP: Clinical Named Entity Recognition):** The clinical NLP pipeline used in the deep screen stage builds on entity extraction techniques covered in the NLP chapter.
- **Recipe 2.7 (Literature Search and Evidence Synthesis):** Trial criteria parsing shares techniques with literature search, particularly around structured query generation from natural language.

---

## Tags

`cohort-analysis` · `clustering` · `clinical-trials` · `patient-matching` · `nlp` · `comprehend-medical` · `sagemaker` · `athena` · `step-functions` · `medium-complex` · `hipaa` · `research`

---

*← [Recipe 6.6: Patient Similarity for Care Planning](chapter06.06-patient-similarity-care-planning) · [Chapter 6 Index](chapter06-preface) · [Next: Recipe 6.8: Disease Subtype Discovery →](chapter06.08-disease-subtype-discovery)*
