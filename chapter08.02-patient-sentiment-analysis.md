# Recipe 8.2: Patient Sentiment Analysis

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.01 per feedback item

---

## The Problem

Every healthcare organization collects patient feedback. HCAHPS surveys, Press Ganey scores, post-visit satisfaction questionnaires, patient portal messages, online reviews, complaint hotline transcripts, social media mentions. The volume is enormous and growing. A mid-sized health system might receive 50,000 pieces of written feedback per month across all channels.

Here's the problem: almost nobody reads it all.

Most organizations track the quantitative scores (your "4.2 out of 5" star rating) and call it done. Maybe someone in Patient Experience reads a sample of the verbatim comments. But the text, the actual words patients use to describe their experience, contains information that a number never can. A patient who writes "the nurse was kind but I waited two hours and nobody told me why" is telling you three distinct things: a positive staff interaction, a process failure, and a communication gap. A "3 out of 5" rating flattens all of that into noise.

Sentiment analysis turns that unstructured text into structured signal. Not just "positive or negative" (though that's a start), but which aspects of the experience are driving dissatisfaction, which departments are generating complaints, what themes emerge over time, and where the bright spots are hiding. Done well, it's an early warning system for operational issues and a map of what your patients actually care about.

The stakes are real. CMS ties a portion of hospital reimbursement to patient experience scores through the Hospital Value-Based Purchasing Program. Press Ganey and HCAHPS scores directly affect revenue. And beyond the financial incentive: patients who feel unheard leave. They switch providers, they post negative reviews, they tell their friends. Understanding sentiment at scale is understanding your retention risk.

Let's talk about how the technology works.

---

## The Technology: How Machines Understand Feelings (Sort Of)

### Sentiment Analysis: The Basics

Sentiment analysis is the task of automatically determining the emotional tone of a piece of text. At its simplest, it classifies text as positive, negative, or neutral. At its more useful, it identifies the intensity of sentiment, the specific aspects being discussed, and the emotions expressed.

The field has been around since the early 2000s. Early approaches used hand-crafted word lists: "good" is positive, "terrible" is negative, add up the scores. These lexicon-based methods are fast, interpretable, and surprisingly stubborn in their continued usefulness. But they miss context entirely. "Not bad" has a negative word but positive meaning. "The procedure was painless" has "painless" (negative root) but is expressing relief.

Modern approaches use machine learning. A model trained on thousands of labeled examples learns the relationship between word patterns and sentiment. The dominant architecture for the past few years has been transformer-based models (BERT and its variants), fine-tuned on domain-specific data. These models understand context, handle negation, and capture subtle sentiment signals that word lists miss entirely.

(A quick note: LLMs like GPT-4 can absolutely do sentiment analysis, and often quite well. This recipe focuses on traditional NLP approaches because they're faster, cheaper, more predictable, and perfectly adequate for this use case. You don't need a rocket to deliver a pizza. Recipe 2.1 covers when LLMs make sense for text analysis.)

### Aspect-Based Sentiment: The Real Value

Raw sentiment classification ("this review is negative") tells you almost nothing actionable. You already knew some patients are unhappy. What you need is aspect-based sentiment analysis (ABSA): identifying which specific aspect of the experience the patient is commenting on, and what their sentiment is toward that specific aspect.

Consider: "Dr. Martinez was wonderful but the billing department never answers the phone." That's positive sentiment toward `provider_quality` and negative sentiment toward `billing_communication`. Two distinct signals from one sentence. Aggregate those across 10,000 reviews and you can tell the CFO exactly which operational area is driving dissatisfaction, with evidence.

The aspects you care about in healthcare are fairly consistent:

- Wait time and scheduling
- Provider communication and bedside manner
- Staff friendliness and competence
- Facility cleanliness and environment
- Billing and insurance processes
- Care coordination and follow-up
- Pain management
- Discharge process

ABSA typically works in two stages: first, identify which aspect(s) are mentioned in the text; second, determine the sentiment directed at each one. Some systems do both jointly with a single model. Either way, you need training data that's labeled at the aspect level, which is more expensive to create than simple positive/negative labels.

### Theme Extraction: Discovering What You Didn't Know to Ask About

Beyond predefined aspects, you want the system to surface emergent themes: patterns you didn't anticipate. Maybe there's a cluster of complaints about parking in February (construction project you forgot about). Maybe patients keep mentioning "the lady at the front desk with the red glasses" positively (a staff member creating exceptional experiences that nobody in leadership knows about).

Theme extraction uses topic modeling or clustering techniques to group semantically similar feedback without predefined categories. The classic approach is Latent Dirichlet Allocation (LDA), but newer methods using sentence embeddings and clustering (HDBSCAN, k-means on embeddings) produce more coherent topics and handle short text better.

The output is a set of discovered themes with representative examples. These need human review to name and validate, but they surface blind spots that a predefined aspect taxonomy will miss.

### What Makes Healthcare Sentiment Different

Standard sentiment analysis tooling was built for product reviews and social media. Healthcare feedback has several properties that make it harder:

**Mixed sentiment is the norm, not the exception.** Product reviews tend to be uniformly positive or negative. Patient feedback is almost always a mix: "the surgery went well but recovery was awful." You need aspect-level analysis or you lose the signal entirely.

**Clinical language intersects with emotional language.** "The pain was excruciating" is describing a symptom, not necessarily expressing dissatisfaction with care. "Negative" in "the test came back negative" is good news. Domain-specific context matters enormously.

**Indirectness and understatement.** Patients expressing serious dissatisfaction often hedge: "I'm sure the staff was doing their best, but..." or "I don't want to complain, however..." Lexicon-based systems will score these as positive or neutral because of the hedging language. A healthcare-tuned model needs to recognize that politeness patterns often mask the strongest negative sentiment.

**Cultural and demographic variation.** Sentiment expression varies significantly across age groups, cultural backgrounds, and education levels. Older patients tend to rate everything higher (acquiescence bias). Patients from cultures where direct criticism is impolite will express dissatisfaction through absence of praise rather than explicit negativity. Your model needs to handle this gracefully or you'll systematically undercount dissatisfaction in certain populations.

**PHI contamination.** Patient feedback frequently contains protected health information: names of providers, specific diagnoses, dates of service, medication names. Any system processing this text must handle PHI appropriately. The sentiment analysis itself doesn't need the PHI (you're extracting themes, not re-identifying patients), but the pipeline must protect it.

---

## General Architecture Pattern

Conceptually, the pipeline looks like this:

```text
[Collect] → [Preprocess] → [Analyze Sentiment] → [Extract Aspects/Themes] → [Aggregate] → [Visualize/Alert]
```

**Collect.** Feedback arrives from multiple channels: survey platforms, patient portals, call transcripts, social media, email. Each has a different format, different metadata, and different response characteristics. You need a unified ingestion layer that normalizes these into a common schema.

**Preprocess.** Clean the text: handle encoding issues, strip HTML, normalize whitespace. For healthcare, add a PHI detection pass: identify and redact or tag any protected information before it flows to downstream analytics. Also detect the language (multilingual patient populations are real) and decide whether to translate or route to a language-specific model.

**Analyze Sentiment.** Run the cleaned text through your sentiment model. For production use, you want both document-level sentiment (overall tone) and sentence-level sentiment (where in the text does sentiment shift?). Capture confidence scores. Low-confidence predictions should be flagged for review rather than treated as truth.

**Extract Aspects/Themes.** Identify which aspects of the experience are mentioned and attach sentiment to each. Separately, run topic modeling or clustering to discover emergent themes that your predefined aspects don't cover.

**Aggregate.** Roll up results by time period, department, provider, facility, service line, and demographic segment. Calculate trend lines. Detect statistically significant shifts (a department's sentiment dropping 15% in two weeks is signal; a 2% fluctuation is noise).

**Visualize/Alert.** Surface insights through dashboards for patient experience teams. Configure alerts for significant negative trends. Generate periodic reports for department leaders. The output should be actionable, not just informational.

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter08.02-architecture). The Python example is linked from there.

---

## The Honest Take

Sentiment analysis is one of those problems where the demo looks amazing and production looks humbling. You'll get the system running in a week, watch it correctly classify 85% of feedback, and feel great. Then you'll look at the 15% it gets wrong and realize those are disproportionately the comments you cared about most.

The hardest cases are the most important cases. A patient who writes a polite, measured paragraph about how they're never coming back (no explicit negative words, no profanity, just quiet disappointment) will probably be classified as neutral. A patient who writes "WORST EXPERIENCE EVER!!!!" is easy for the machine but usually less operationally interesting. The signal-to-noise tradeoff is real.

Aspect extraction requires real investment in labeled data. You need at minimum a few hundred labeled examples per aspect category, reviewed by people who understand both NLP and your patient experience goals. Plan for a 2-4 week labeling sprint before your custom classifier is useful. And plan to refresh that data every 6-12 months as language patterns evolve.

The thing that surprised me most: the aggregate trends are far more valuable than individual predictions. Any single feedback item might be misclassified. But when you aggregate 5,000 items and see that `wait_time` sentiment dropped 20% in the last month for your orthopedics department, that's real signal that survives individual classification errors. Design your system for aggregate intelligence, not individual-comment accuracy.

One more thing: be careful about who sees the raw comments. Patient experience teams need access. But department leaders who see their own negative feedback without context ("why did this patient say I was dismissive?") can react defensively rather than constructively. Present aggregated themes and trends to leadership. Keep individual comment access to the patient experience professionals who are trained to handle it.

---

## Related Recipes

- **Recipe 8.1 (Chief Complaint Classification):** Uses the same text classification foundation but for clinical routing rather than experience analysis
- **Recipe 2.1 (Patient Message Response Drafting):** LLM-based approach to understanding and responding to patient communications
- **Recipe 4.2 (Patient Education Content Matching):** Uses sentiment signals to personalize content delivery to frustrated or confused patients
- **Recipe 10.2 (Voicemail Transcription and Classification):** Converts voice feedback to text that feeds into this sentiment pipeline

---

## Tags

`nlp` · `sentiment-analysis` · `comprehend` · `patient-experience` · `hcahps` · `aspect-extraction` · `simple` · `mvp` · `lambda` · `s3` · `dynamodb` · `quicksight` · `hipaa`

---

*← [Recipe 8.1: Chief Complaint Classification](chapter08.01-chief-complaint-classification) · [Chapter 8 Index](chapter08-preface) · [Next: Recipe 8.3: ICD-10 Code Suggestion →](chapter08.03-icd-10-code-suggestion)*
