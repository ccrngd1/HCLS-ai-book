# Recipe 2.6: Clinical Note Summarization

**Complexity:** Medium · **Phase:** MVP → Production · **Estimated Cost:** ~$0.05-$0.25 per patient summary

---

## The Problem

It's 6:45 AM on a Monday. A hospitalist starts her week covering a 22-bed medicine service. Eight of those patients she's never met. Each one has been on the service for somewhere between two and nine days. Each chart has, on average, forty-something notes: admission H&P, daily progress notes from whoever covered the weekend, consult notes from cardiology and nephrology, nursing notes, case management notes, PT/OT notes. She has a 7:00 AM huddle. She has rounds starting at 8:00. She has exactly fifteen minutes to "chart biopsy" eight unfamiliar patients well enough to not embarrass herself in front of the team and, more importantly, well enough to not miss something clinically important.

So she does what everyone does: she scrolls. Open the most recent progress note. Scan the assessment and plan. Open the admission H&P. Read the HPI. Maybe scan through a consult note if the specialist's name catches her eye. The rest? She doesn't read. She can't. There isn't time. By the time she's making a decision about whether to continue diuresis on bed 4, she's working from a mental model built in ninety seconds from three notes out of forty.

This isn't a failure of clinician diligence. It's a structural mismatch between how clinical information is generated (a running log of notes, one per day per service, accumulating forever) and how it needs to be consumed (a concise picture of "where is this patient, and what matters right now"). The system produces prose. The clinician needs a briefing.

The ICU handoff version of the same problem is sharper. Night shift hands off to day shift. The day attending gets a verbal sign-out in five minutes, then is on the hook for twelve hours of decisions. If the overnight resident forgets to mention that the family has been meeting with palliative care, the day team can spend an hour on aggressive workup for a patient who's already been transitioned to comfort-focused goals. If nobody mentions that the patient self-extubated once already, the day team won't be as cautious on the next extubation attempt. The consequences of a missed detail in handoff are real and documented. The I-PASS multi-center trial ([Starmer AJ et al., "Changes in Medical Errors After Implementation of a Handoff Program," N Engl J Med 2014;371:1803-1812](https://doi.org/10.1056/NEJMsa1405556)) showed a 23% reduction in medical errors and a 30% reduction in preventable adverse events after implementing a structured handoff program.

The readmission version is sharper still. A patient hospitalized at Hospital A in March gets readmitted at Hospital B in May. The ED physician at Hospital B is staring at eighty pages of outside records that arrived by fax. Somewhere in those eighty pages is the detail that matters (the patient was discharged on a new immunosuppressant, had a drug reaction documented on day three, and the reaction is recurring right now). That detail is buried between page forty-three and page forty-five, inside a consult note from a rheumatologist. The ED physician has seven other patients and ninety minutes to disposition this one. Statistically, they're going to miss it.

The hospital course summarization problem is its own beast. A patient spends eleven days in the hospital. Admitted for sepsis, source unclear. Day two: blood cultures grow MRSA. Day three: echo shows a vegetation. Day four: tagged "endocarditis." Day five: consult to cardiothoracic surgery. Day seven: surgery declines, recommends six weeks of IV antibiotics. Day nine: PICC placed. Day eleven: discharged to a skilled nursing facility. The attending who discharges the patient has to write a discharge summary that captures that entire arc in a readable form. If they do it well (pulling threads across eleven notes from four services), it takes forty minutes. If they do it poorly, they copy-paste from the latest progress note and the receiving facility gets a document that says "patient admitted for sepsis, treated, now stable" and nothing useful about the surgical consultation or the antibiotic plan.

The specialty-consultation version. A primary care physician refers a patient to endocrinology. The endocrinologist's referral packet includes: the PCP's last six progress notes, a year of lab results, a hospital discharge summary from nine months ago, and a three-sentence referral letter. The endocrinologist has twenty-five minutes for the new-patient visit. Before the patient walks in, they need to know: what's the patient's diabetes story, what meds have been tried, what has the A1c done, is there any complication history, any kidney involvement. That story is absolutely in the packet. It takes fifteen minutes to construct it by reading. They don't have fifteen minutes.

What all of these scenarios have in common is the same underlying gap: the clinical chart is designed for writing and documentation, not reading. A note is written once, by one person, in one context. It accumulates into a chart. Someone later has to reconstruct a picture of the patient by reading a stack of notes that were never intended to be read as a whole. The reconstruction is cognitively expensive, time-consuming, and error-prone. And the stakes of a missed detail can be substantial.

This is a place where "summarize this for me" is not a luxury. It's an operational necessity that's been on clinicians' wish lists for thirty years. The tooling wasn't there. Now it is, mostly, with caveats that matter.

---

## The Technology: Clinical Summarization Is Not General Summarization

### Why Clinical Summarization Is Its Own Problem

General-purpose summarization, the kind that produces a three-paragraph summary of a news article, has been a solved-ish problem for years. Point a modern LLM at a long document, ask for a summary, and you'll get something coherent and largely faithful to the source. That's impressive. It's also not what clinicians need.

Clinical summarization has constraints that general summarization doesn't:

**Omission is the primary failure mode, not hallucination.** With patient-facing content (Recipe 2.5), the risk is the model saying something that isn't in the source. With clinician-facing summarization, the risk is the model leaving something out. A hospital course summary that reads beautifully but forgets to mention the patient's PICC line is useless, and possibly worse than useless because the clinician reading it thinks they've been briefed when they haven't.

**"Important" is context-dependent.** A patient's cardiology history is front-and-center for a cardiology consult and background for a dermatology consult. A medication allergy is always important. A remote appendectomy is rarely important. The model has to decide what to foreground based on who's reading and why. Generic summarization treats all content as equally eligible for the summary, which is wrong for clinical use.

**Temporal structure matters.** "Patient had a PE in 2012" and "Patient had a PE last week" are radically different clinical facts. A summarization that collapses them into "history of pulmonary embolism" has destroyed the signal. Clinical summarization has to preserve when things happened, not just that they happened.

**Negation is often more important than assertion.** "Ruled out myocardial infarction" is a critical clinical finding. A summarizer that drops negations (either because they feel like less signal, or because they paraphrase around them) can flip the meaning of a workup. The canonical failure mode here: a source note says "no evidence of active bleeding"; the summary says "patient has been bleeding." Same words, inverted meaning, real consequences.

**Quantitative trends beat point values.** A single troponin of 0.04 means one thing. A trend of troponins going 0.04 → 0.08 → 0.12 → 0.31 over four hours means something very different. Clinical summarization has to recognize and preserve trends, not just snapshot values.

**Must-include categories.** Some content categories are never droppable. Allergies. Active problems. Current medications. Code status. DNR/DNI status. Advance directive existence. Key consult recommendations. These are summary-level decisions that aren't the model's call; the architecture has to enforce inclusion.

### Abstractive vs Extractive, and Why You Want Both

There are two classical approaches to automated summarization.

**Extractive summarization** pulls the most important sentences out of the source, in the original wording, and presents them as a summary. Pros: nothing is hallucinated because every sentence is verbatim from the source. Cons: the output reads like a pile of disconnected sentences, redundancy is common (the same fact is often stated in multiple notes), and the summary is only as good as the sentences the algorithm decides are "important."

**Abstractive summarization** generates new prose that captures the meaning of the source. Pros: the output reads naturally, redundancy is eliminated, and the summary can integrate across multiple sources. Cons: this is where hallucination risk lives, because the model is writing sentences it chose rather than quoting sentences it found.

Modern clinical summarization systems are abstractive (because clinicians want readable output), but they use extractive elements as controls: every abstractive claim should trace back to an extractive source. The architecture supports both, even though the default output is abstractive prose. This is essentially the same grounded-generation pattern as the patient-facing recipes, with the difference that the audience can tolerate (and often prefers) clinical terminology.

### The Long-Document Problem

An inpatient stay can easily accumulate 50,000 to 200,000 words of notes. A multi-year chart, many times that. Even modern "long context" LLMs have practical limits: sending 400,000 tokens costs real money, latency is painful, and the model's attention degrades across very long inputs (it can miss content in the middle of a large prompt, a phenomenon that's been studied and confirmed). Feeding the entire chart into a single prompt is a bad strategy at scale.

The architectural pattern that works is hierarchical summarization. Roughly:

1. **Chunk** the input. Chunks can be per-note, per-day, per-service, or some combination.
2. **Summarize each chunk** into a structured representation (key facts, not prose).
3. **Aggregate** the structured representations.
4. **Generate** the final prose summary from the aggregated structure.

This is a map-reduce pattern applied to clinical text. The "map" step extracts facts from each chunk. The "reduce" step combines those facts into a single structured object. The "generate" step produces readable prose from the structured object.

The advantage: the prose-writing step operates on a clean, fielded input that's small enough to fit in any context window. The cost and latency scale with chart size roughly linearly rather than quadratically. And the structured intermediate representation is independently valuable (for downstream analytics, for validation, for keeping the summary updatable as new notes arrive).

### Specialty-Aware Summarization

Summarizing for a nephrologist is different from summarizing for an orthopedic surgeon. The nephrologist wants kidney-specific information front-and-center: baseline creatinine, recent creatinine, fluid status, medications that matter for kidneys, current dialysis status if any. They don't want three paragraphs about the orthopedic surgery unless it caused a kidney complication.

This is handled architecturally through specialty-specific prompt templates or specialty-specific post-processing. The "structured summary" step is specialty-neutral (extract all the relevant facts). The "generate prose" step takes a specialty parameter that changes which facts get foregrounded, how much detail they get, and what ordering the sections use. The alternative, trying to build one prompt that works for all specialties, usually produces summaries that are generic enough to disappoint everyone.

For primary care or general hospitalist use, "no specialty" is itself a specialty: the summary has to be broad, cover active problems comprehensively, and not over-specialize in any one area.

### Risk-Aware Omission Detection

The single most dangerous failure in clinical summarization is a confident, readable summary that silently drops a critical detail. You cannot detect this failure by reading the summary; the summary reads fine. You have to detect it by comparing what's in the source to what's in the summary and flagging categories that went missing.

A practical approach: maintain a checklist of high-risk categories (allergies, active problems, recent critical findings, code status, medications with narrow therapeutic windows, active infections, active devices like lines and tubes, recent procedures). For each category, the system verifies that the summary includes at least one mention if the source contains relevant content. Missing categories are either regenerated or flagged for clinician review.

The model is not trusted to decide what's safe to drop. The checklist enforces what must be present.

### Why LLMs Are the Right Tool Here (Despite the Risks)

Earlier generations of this problem were attacked with rule-based extraction (regex and templates, which produced either sparse or noisy output) and traditional machine learning classification (which required thousands of labeled summaries to train and was brittle to new note styles). Both approaches shipped, both worked partially, neither reached the quality bar clinicians actually needed to trust the output.

Modern LLMs change the math for two reasons. First, they can operate on unlabeled free text with zero training, using prompts alone, which eliminates the data-labeling bottleneck that killed earlier efforts. Second, they understand medical terminology well enough to handle variations in how clinicians write (one physician's "pt c/o CP radiating to L arm" is another's "patient complains of substernal chest pain with radiation to the left arm," and both parse correctly). The combination of zero-shot capability and medical-language fluency is what makes clinical summarization finally viable.

What it doesn't do, and this has to be stated clearly, is remove the need for careful architecture. The model is good. The architecture around the model is what makes the output trustworthy enough to ship to clinicians.

### The Failure Modes You Have to Design Around

**Silent omission of high-risk categories.** Already covered. Architectural mitigation via must-include checklists.

**Fact blending across patients or visits.** The model, summarizing a long document, mixes facts from one encounter into another. "Patient had appendectomy in 2019" becomes "Patient had appendectomy during this admission." Mitigation: chunk by encounter and never let the summarizer cross encounter boundaries during the extraction step.

**Recency collapse.** "Patient was on vancomycin" might be from three years ago or three hours ago. The summary drops the date. Mitigation: force every summarized fact to carry a date or a relative-time qualifier ("this admission," "prior hospitalization," "outpatient history").

**Chief-complaint drift.** The summary focuses on whatever the most recent note focused on, which may not be the actual reason for the admission. A patient admitted for septic shock who then develops acute kidney injury may have summaries that drift into being "about" AKI and downplay the original sepsis. Mitigation: anchor the summary to the admission diagnosis explicitly, and include admission-reason as a required section.

**Consultant silo-ing.** A consulting service's perspective is treated as gospel or as irrelevant, rather than as one opinion in a thread. Mitigation: represent consults as attributed recommendations, not as unattributed facts ("Cardiology recommended X on day 4" rather than "X is recommended").

**Negation errors.** Already covered. Hardest failure mode to catch automatically. Mitigation: negation-aware extraction (Comprehend Medical and similar tools handle this reasonably); explicit preservation of negating language in the structured representation.

**Over-confident language.** The model smooths "possible pulmonary embolism, CT scheduled" into "pulmonary embolism diagnosed." Mitigation: preserve clinical uncertainty language in the extraction step and instruct the generator not to strengthen it.

**De-duplication gone wrong.** A fact mentioned in twenty notes gets deduplicated to one mention, but the repetition was itself the signal (persistent finding, recurring complaint). Mitigation: track mention counts across notes and use frequency as an input to the generator.

**Style mismatch.** The summary reads like a story when the clinician wanted a problem list. Or it reads like a problem list when the clinician wanted a narrative for the discharge summary. Mitigation: multiple output formats driven by use-case parameters, not one-size-fits-all prose.

---

## The General Architecture Pattern

At a high level, the pipeline looks like this:

```text
[Summary Request]
    → [Define Scope & Audience]
    → [Retrieve Source Documents]
    → [Chunk and Preprocess]
    → [Extract Structured Facts Per Chunk]
    → [Aggregate and Deduplicate Facts]
    → [Apply Must-Include Checklist]
    → [Generate Prose by Section]
    → [Validate Against Extracted Facts]
    → [Attach Provenance Links]
    → [Deliver to Requesting Clinician]
    → [Log for Audit]
```
Let's walk through the conceptual stages.

**Summary request.** Someone (or something) asks for a summary. The request specifies who's asking (specialty, role), why (handoff, consult review, pre-admission review, discharge summary drafting), the scope (this admission, last N months, all time), and the desired format (narrative, problem-oriented, SBAR, specialty-focused). These parameters drive downstream decisions. A generic "summarize this patient" is almost always the wrong request; specificity improves output quality dramatically.

**Retrieve source documents.** Pull the notes that are in scope. For a current-admission summary, that's the notes from this encounter. For a longitudinal summary, it's a broader pull bounded by the time window the clinician specified. Retrieval should also include structured data relevant to the summary scope: medication lists, problem lists, allergies, recent labs, recent imaging reads. Structured data is easier to summarize faithfully than prose. Critically, retrieval must filter out notes from restricted data categories (42 CFR Part 2 substance-use-treatment records, HIV-related content, adolescent confidential notes, genetic test results) unless the requesting user has a specific disclosure consent on file. Access control is enforced at the retrieval layer, not bolted on downstream.

**Chunk and preprocess.** Break the input into manageable pieces. Natural chunking boundaries: per-note, per-day, per-service. For each chunk, lightweight preprocessing: remove boilerplate headers and footers, normalize dates, flag negation phrases, tag entities. This preprocessing makes the extraction step more reliable.

**Extract structured facts per chunk.** For each chunk, produce a fielded structured object: what happened, when, who said it, with what certainty. This is where the heavy lifting happens. The extraction prompt is specialty-neutral at this stage; the goal is to capture everything the chunk contains, not to pre-filter for relevance.

**Aggregate and deduplicate facts.** Combine the per-chunk extractions into a single structured object. Deduplicate facts that appear in multiple notes while preserving the original count (a finding mentioned in ten notes is probably important). Resolve conflicting information (one note says the patient is on warfarin, another says apixaban; which is current?). Build a timeline of events.

**Apply must-include checklist.** Check that the aggregated object covers the required categories for this summary type. Allergies present? Active medications present? Code status present if inpatient? Recent critical findings present? Missing categories either get explicitly populated from structured data sources (if available) or flagged as gaps.

**Generate prose by section.** With a clean structured object in hand, produce the readable summary. Use the audience and format parameters from the request to shape the output. Different sections may use different prompts (the narrative section is written differently from the active-problems section). The generation is the last step where new prose is created; everything downstream is validation and rendering.

**Validate against extracted facts.** Check that every specific claim in the generated prose traces back to a fact in the structured object, and through that to a source note. Flag unverified claims. For a clinician-facing tool, unverified claims are typically held for regeneration or explicit clinician review rather than auto-shipped.

**Attach provenance links.** Each section or each fact in the summary gets a link or reference back to the source notes it came from. Clinicians don't trust summaries they can't audit. Good provenance is the difference between "this is a starting point I can verify" and "this is a black box output I can't defend."

**Deliver to requesting clinician.** Render and display the summary in the environment the clinician is working in: the EHR's context-sensitive sidebar, a handoff tool, a separate review UI. Delivery channel affects format (an EHR sidebar is tighter than a full-page review document).

**Log for audit.** Every summary generated, every input set, every version. Clinical summaries that influence care decisions are part of the legal record. You need to be able to reconstruct what a summary said at a specific moment.

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter02.06-architecture). The Python example is linked from there.

## The Honest Take

Clinical summarization is one of those problems I've watched teams underestimate repeatedly. The demo is easy: pick a nice-looking inpatient chart, generate a summary, show it to leadership, watch them nod. Of course it works. Modern models are good at this. The demo is not the hard part.

The hard part is everything downstream of the demo. Does it handle the chart with twelve nursing notes full of "patient resting comfortably" and three actually-informative progress notes? Does it handle the consult note that's three pages of copy-pasted history before the one sentence that matters? Does it correctly foreground the DNR status for the patient whose code status changed on hospital day five? Does it distinguish the three different sodium values from three different days? Does it preserve the negation in "ruled out PE" instead of quietly dropping it? Does it flag the disagreement between cardiology and nephrology rather than smoothing it into a single recommendation? Does the clinician reading the summary at 6:45 AM on a Monday actually find it more useful than scrolling the chart themselves?

In my experience, the delta between "this works on our demo chart" and "this works reliably on production charts" is about nine months of engineering and clinical iteration. Not three weeks. Teams that budget three weeks and then try to ship get the pattern I described in the AVS recipe: beautiful summaries on cherry-picked charts, subtle errors in production, clinician trust erodes, project gets paused for rework. Budget the nine months. Build the validation, the must-include checklist, the provenance linking, the feedback loop, and the evaluation methodology as first-class components, not as afterthoughts.

The second thing I'd emphasize: specialty is not optional. The teams that try to build "one summarizer for all clinicians" produce summaries that are generic enough to disappoint everyone. A nephrologist reading a generic summary still has to read the notes to find the kidney stuff. An oncologist reading a generic summary still has to read the notes to find the treatment history. The generic summary saves them five minutes; reading for the missing stuff costs them ten. Net negative. Specialty-specific templates from day one, with the specialty's clinical leadership involved in defining priorities, produce tools that actually save time.

The third thing: provenance is not a nice-to-have. It's the feature that makes the tool defensible. Without provenance, a clinician who acts on the summary and then has something go wrong cannot explain their decision except as "I read the AI summary." That's a weak defense clinically and a terrible one legally. With provenance, the clinician can say "I read the summary, verified the specific claim that informed my decision against the source note, and documented my independent assessment." That's the defensible workflow, and it only works if provenance is present, accurate, and easy to click through.

Fourth: listen to the clinicians who don't use the tool. The clinicians who adopt it early and love it will tell you what's working. The clinicians who try it once and never come back are telling you something at least as important. Set up a process to interview the non-adopters. What made them stop? Was it a specific error? A UI friction point? A trust concern? A performance issue? Usually it's one or two specific issues that are fixable; you just have to know what they are.

Fifth: this use case has a stealth benefit that's worth naming. The structured extraction step, properly designed, produces a clean, fielded representation of a patient's clinical state. That representation is independently valuable. It can power population health dashboards that today rely on brittle parsing of structured problem lists. It can power quality-measure reporting that today requires manual chart review. It can feed longitudinal analytics that today are blocked because the content lives in free text. Teams that build the summarization pipeline well tend to discover six months later that they built a clinical-data asset they didn't originally plan for. Design the extraction schema with that downstream use in mind and the ROI is substantially better than the summarization use case alone would suggest.

Finally: the bar for "useful" here is lower than teams often assume. Clinicians are not expecting the summary to replace reading the chart. They're expecting it to give them enough of a picture to know which notes to read carefully and which to skim. That's a reachable bar. You don't need perfect summaries. You need summaries that are good enough to orient the reader, honest about their gaps, and fast enough to use in the fifteen-minute window before rounds. Build for that bar, not for the imaginary bar where the summary replaces the chart entirely.

---

## Related Recipes

- **Recipe 2.2 (Medical Terminology Simplification):** Where clinical summarization targets clinicians (and keeps clinical terminology), simplification targets patients. Same source material, different audience, different constraints.
- **Recipe 2.3 (Clinical Documentation Improvement):** CDI looks at notes to suggest improvements for coding and billing. The structured extraction techniques used here are closely related to what CDI tools need, and the two pipelines can share extraction infrastructure.
- **Recipe 2.4 (Prior Authorization Letter Generation):** Another grounded-generation use case. The aggregation and validation patterns transfer; the output format differs substantially.
- **Recipe 2.5 (After-Visit Summary Generation):** Patient-facing version of the summarization problem. Shares the grounded-generation architecture, the validation discipline, and the must-include checklist concept; differs in audience, tone, and reading level.
- **Recipe 2.8 (Ambient Clinical Documentation):** When ambient documentation is producing the notes that get summarized, the input quality is higher and more consistent, which improves downstream summarization quality.
- **Recipe 2.9 (Clinical Decision Support Synthesis):** Summarization and decision support sit on a continuum. Pure summarization stays descriptive; decision support adds recommendations. The regulatory posture differs; the architectural patterns overlap.
- **Recipe 7.5 (30-Day Readmission Risk):** Structured extractions produced by the summarization pipeline can feed risk models. The same normalized problem list, medication list, and finding timeline that drive the discharge summary can drive downstream readmission-risk predictions.

---

## Tags

`llm` · `generative-ai` · `bedrock` · `healthlake` · `comprehend-medical` · `clinical-summarization` · `clinician-facing` · `grounded-generation` · `provenance` · `handoff` · `hospital-course` · `specialty-aware` · `map-reduce` · `hierarchical-summarization` · `must-include-checklist` · `guardrails-contextual-grounding` · `medium-complexity` · `hipaa` · `fhir` · `smart-on-fhir`

---

*← [Recipe 2.5: After-Visit Summary Generation](chapter02.05-after-visit-summary-generation) · [Chapter 2 Index](chapter02-preface) · [Next: Recipe 2.7 - Literature Search and Evidence Synthesis →](chapter02.07-literature-search-evidence-synthesis)*
