# Recipe 1.4: Prior Authorization Document Processing 🔶

**Complexity:** Moderate · **Phase:** MVP · **Estimated Cost:** ~$0.80-1.00 per 10-page submission

---

## The Problem

Here's the thing about prior authorization that makes it uniquely frustrating: everyone involved is working hard, and the outcome is still terrible.

A surgeon's office decides a patient needs a knee replacement. The clinical case is straightforward: the patient has severe osteoarthritis, six months of documented conservative treatment, and an MRI showing bone-on-bone contact. The surgeon knows it. The referring physician knows it. The patient's physical therapist knows it. The payer's own clinical guidelines probably say this case should sail through.

But first, someone in that surgeon's office has to assemble the prior auth submission. They pull the office notes from the last three appointments, the MRI report, the PT records, the lab results showing the inflammatory markers, and the physician's letter explaining why this specific patient needs this specific intervention. They stack it all together, feed it into a fax machine, and send 15 pages to a payer UM department.

On the other end, a clinical reviewer receives that fax. They sort through the pages, hunting for the diagnosis codes on the cover sheet, finding the relevant clinical documentation, checking whether the submitted evidence matches the payer's coverage criteria for total knee arthroplasty. If they find everything, they approve it. If something's missing, they send a denial or a request for additional information. The provider calls the payer. Someone tracks down the missing piece. Another fax goes out. The cycle repeats.

This takes 15 to 45 minutes of a trained clinical reviewer's time for a single case. Payers process millions of these annually. The American Medical Association's prior authorization physician survey consistently finds that more than 90% of physicians report that prior auth causes delays in care, and roughly one in four physicians report that prior auth has led to a serious adverse event for a patient. The delays aren't because anyone is being malicious. They're because the document processing pipeline is manual and slow.

The CMS Interoperability and Prior Authorization Final Rule (CMS-0057-F) is pushing payers hard toward faster, more automated decisions: 72-hour turnaround for standard requests, 24 hours for expedited. State-level prior auth reform is adding more pressure on top of that. The regulatory calendar is not waiting for the technology.

Here's the document processing challenge at the core of all of this. A prior auth submission is not one document type. It's five to seven different document types, faxed together, in no particular order, at whatever quality the originating fax machine produces. Page 1 might be a structured cover sheet you can extract like an insurance card. Page 3 is a clinical office note with free-text diagnosis and treatment history. Page 7 is a printed lab results table. Page 11 is a typed letter from the ordering physician describing why alternative treatments were tried and failed.

Each of these requires a completely different extraction approach. Trying to process them all the same way gets you bad data from most of them. The insight that makes this problem tractable: classify each page first, then route it to the right extractor.

That sounds simple. And for a while, it is. A classifier built on keyword matching and document structure can handle the submissions you've seen before. It handles them reliably and cheaply. For a few months, you feel good about it.

Then you hit the ceiling.

The physician letter from a rural clinic uses "Service Requested Code" where everyone else uses "CPT Code." The cover sheet from a regional plan calls the diagnosis field "Dx Indication." A clinical note includes an embedded lab results grid that flips the classifier toward "lab report," burying the narrative evidence the downstream logic needs. None of these are exotic. They're just variability at healthcare scale, and the keyword-based system has no idea what to do with any of them.

This is where Recipes 1.1 through 1.3 end and Recipe 1.4 begins. The extraction services we've used so far are excellent at what they do. But what this problem now needs isn't more extraction. It needs something that can *read* the page, understand what it's looking at in context, and reason about the content the way a clinical reviewer would. That's where we introduce a large language model as the reasoning layer that sits between the OCR output and the extraction logic. That introduction carries through the rest of the chapter.

---

## The Technology

### What Document Classification Actually Is

Document classification, at its most useful, is the problem of answering one question: what kind of page is this? The answer determines everything you do with the page next.

There are several ways to approach it. The spectrum runs from keyword heuristics on one end to large language models on the other, with trained text classifiers sitting in the middle. Each point on that spectrum represents a different trade-off between simplicity, accuracy, and maintenance burden.

Let's walk through them in order. Not because the last one is obviously right for every situation, but because understanding why the simpler approaches work and where they fail is what makes the LLM approach legible. You'll make better decisions about model selection when you understand what problem each approach is actually solving.

### Keyword Heuristics: Simple, Surprisingly Effective, Inevitably Brittle

The simplest classification approach: look for words that tend to appear on specific page types.

A page containing "HISTORY OF PRESENT ILLNESS" and "ASSESSMENT AND PLAN" is almost certainly a clinical note. A page containing "FINDINGS" and "IMPRESSION" and "TECHNIQUE" is probably an imaging report. A page with "MEMBER ID," "REQUESTING PROVIDER," and "CPT CODE" in close proximity is likely a cover sheet.

This sounds unsophisticated. It works well. Prior auth submissions are not written to confuse classifiers. They follow recognizable templates. A keyword-based classifier built on 20 to 30 carefully chosen signatures per page type can achieve high accuracy on real-world prior auth submissions without training a single model.

You can also layer in structural signals. Modern document analysis systems return not just text, but metadata: where text blocks are positioned on the page, whether the page contains form fields and key-value pairs, whether there are tables, whether the text runs in multi-column layout. A cover sheet has form fields. A clinical note is primarily flowing prose. A lab results page has tables with numeric values and reference ranges. These structural signatures, combined with keyword signals, push accuracy toward the upper end of that range.

So why not stop here? Why does this recipe exist?

### Where Heuristics Break Down

Because misclassification rate is impactful in healthcare, especially at scale.

At 500,000 submissions per year, averaging 8 pages each, you have 4 million pages going through the classifier. At 10% misclassification, 400,000 pages per year get routed to the wrong extractor. Most of those fail gracefully: a clinical note page routed to the lab results extractor finds no tables and returns an empty result. But some produce confident-looking wrong output that the assembler happily incorporates into the structured record.

The failure modes cluster into three categories.

**Ambiguous pages.** A physician letter that opens with a demographic table looks like a cover sheet until you read the first paragraph. A clinical note that includes an embedded lab results grid reads as "lab results" to a keyword classifier, even though the clinical narrative is the relevant content. Keywords can't see context. They see the presence or absence of specific strings.

**Blended document types.** Templates evolve. A payer updates their cover sheet to include a short clinical summary section. Now the cover sheet has clinical keywords ("diagnosis," "treatment history") alongside administrative ones. The classifier scores it as ambiguous and may pick wrong. You update your keyword list. Six months later, a different payer makes a different change and you're back at the whiteboard.

**Unusual templates from unusual sources.** Your keyword list is calibrated to the 20 payers who send you the most volume. Then a small regional plan sends a submission where the cover sheet calls the diagnosis field "Dx Indication" and the CPT field "Service Requested Code." Both are reasonable labels. Neither is in your dictionary. Classification fails.

The underlying problem: keyword heuristics encode your assumptions about what documents look like. They match the templates you've seen before. They fall apart against templates you haven't.

### Trained Text Classifiers: Better Accuracy, New Maintenance Burden

The natural next step is to train a proper text classifier on labeled examples. You collect a few thousand pages from real prior auth submissions, label each one by hand, and train a model: logistic regression, a gradient boosted tree, or a fine-tuned language model. The model learns statistical patterns from the labeled data that go beyond the keyword dictionary you wrote by hand.

This works significantly better. A well-trained classifier typically reaches 93 to 97% accuracy on held-out test data, handling the ambiguous cases that keyword matching fails on. It learns that "Dx Indication" and "Diagnosis Code" are the same concept because both appear on similar pages with similar surrounding context. It generalizes across formatting variations it's seen during training.

Two new problems arrive with it.

First: you need labeled training data, and you need more of it every time the distribution shifts. Every time a major payer updates their cover sheet template, you need to re-label examples and retrain. The maintenance burden shifts from "keep the keyword dictionary current" to "keep the training data current." Same problem, different form.

Second: trained classifiers still fail systematically on truly unseen templates. A model trained on 50 payer templates does well on those 50 payers. The 51st payer, whose documents look nothing like the training distribution, still gets misclassified. The model just fails with higher confidence.

Cloud-based custom classification services (AWS Comprehend Custom Classification, Google AutoML Text, Azure Custom Text Classification) make it easier to train and deploy these models without infrastructure work. But you're still in the business of maintaining training data. For high-volume deployments with stable payer relationships, trained classifiers earn their cost. For long-tail payers and novel templates, the maintenance burden is relentless.

### The LLM Approach: Understanding, Not Matching

A large language model approaches classification differently. You show it a page and ask: what kind of document is this, and how confident are you? The model doesn't look for specific strings. It doesn't rely on patterns from your labeled training set. It reads and understands the page text in context. It brings a deep prior about what clinical notes look like, what lab reports look like, what administrative forms look like, accumulated from training on an enormous corpus of text that includes medical literature, clinical documentation, and administrative healthcare records.

The practical result: edge cases that would confuse a keyword classifier often don't confuse an LLM. "Dx Indication" is recognizably a diagnosis field to a model that understands medical administrative language. A clinical note with embedded lab values reads as a clinical note because the model understands that prose describing a patient's history is different from a structured lab report, even if both happen to mention lab values.

There's more: no keyword list to maintain. No labeled training data to curate. No re-calibration when a payer updates their template. The model generalizes to unseen formats because it understands language rather than matching strings. The "51st payer" problem largely disappears.

You send the page text (already extracted by OCR) and a classification prompt to the model, with instructions to return a structured response. The model replies with a document type and a confidence score. That's the whole API surface.

This is what the Bedrock Converse API makes straightforward. You pass extracted text to a foundation model with a system prompt describing the task, and you get a structured classification back. The API is the same regardless of whether you're calling Claude, Nova, or any other model available through the service. Your code doesn't change when you switch models. Only the model ID does.

(We'll cover the specific API calls in the AWS implementation section. For now: the concept is simple. Send text, get structured classification. Temperature set to zero for near-deterministic output. Move on.)

### The LLM as the Reasoning Layer

Classification is only half of what the LLM brings to this pipeline. The other half is clinical reasoning on narrative pages.

In a pure Comprehend Medical pipeline, a clinical note produces a list of entities: conditions, medications, procedures, anatomy. What it doesn't produce is the *relationship* between them or the clinical narrative that connects them. Comprehend Medical will tell you that "physical therapy," "naproxen," and "corticosteroid injection" all appear in a document. It won't tell you that all three were tried, failed over a documented time period, and that failure is the basis for the medical necessity argument the physician is making.

An LLM reads the page the way a clinical reviewer would. It extracts not just the entities but the evidence structure: what condition is being treated, what was tried, why it wasn't sufficient, what findings support the requested intervention. It produces a clinical summary that a downstream criteria-matching system can actually reason against.

This is the shift: Textract is still the best tool for extracting structure from documents. Comprehend Medical is still the best tool for high-confidence ICD-10 and RxNorm code mapping. But the LLM becomes the brain that sits on top of extraction, reading what Textract extracted and producing the clinical reasoning that makes those raw entities useful.

### The Model Tiering Concept

Here's something worth pausing on, because it's a principle that carries through the rest of this chapter.

Not all classification and extraction tasks are equally hard. "What type of page is this?" is a relatively simple task. "Extract the clinical evidence supporting medical necessity for this procedure, including failed prior treatments, relevant diagnostic findings, and the physician's reasoning" is a complex reasoning task. Routing a simple task through a powerful, expensive model is wasteful. Routing a complex reasoning task through a cheap, limited model gets you wrong answers.

The right approach is tiered: use the cheapest model that handles each task reliably. 

**Tier 1 (cheap, fast):** Page classification, document triage, simple presence/absence judgments. Amazon Nova Lite at $0.06 per million input tokens is appropriate here. The classification question is well-defined. The page text gives you plenty of signal. You don't need a frontier model.

**Tier 2 (mid-range):** Standard structured extraction from moderately complex documents. Nova Pro at $0.80 per million input tokens or Claude Haiku 4.5 at $1.00 per million. Good accuracy on extraction tasks at reasonable volume cost.

**Tier 3 (capable, higher cost):** Clinical reasoning, medical necessity analysis, extracting context-dependent evidence from narrative text. Claude Sonnet 4.6 at $3.00 per million input tokens. This tier handles the tasks where the model needs to understand clinical context, not just locate and copy fields.

**Tier 4 (maximum capability):** Degraded documents, highly ambiguous content, complex multi-step reasoning. Claude Opus 4.6 at $5.00 per million input tokens. Reserve for cases where everything else fails, or route directly to human review.

The decision is straightforward once you've internalized it:

- Simple classification? Use Tier 1.
- Structured extraction from clean, predictable content? Use Tier 2.
- Clinical context and reasoning? Use Tier 3.
- Degraded or deeply ambiguous document? Use Tier 4, or send to human review.

This recipe introduces the concept. The remaining Chapter 1 recipes build on it.

### The New Fan-Out: Two Paths, Not Four

In a pure keyword-classifier architecture, the fan-out after classification sends each page type to a specialized extractor: a forms extractor for cover sheets, a clinical NLP pipeline for clinical notes, a table parser for lab results, an entity extractor for imaging reports. Four distinct paths, each optimized for its specific input type.

With an LLM in the picture, the fan-out simplifies. The LLM handles extraction and reasoning in a single call for most page types. You don't need a separate extractor for each page type because the LLM understands all of them.

The result is two main paths:

**Path 1: Textract forms extraction.** Cover sheets are structured forms with clear field-value pairs. Textract is purpose-built for exactly this. It's fast, cheap, highly accurate on clean printed forms, and returns field-level confidence scores. Don't replace a specialized tool that does its job well.

**Path 2: LLM extraction and reasoning.** Clinical notes, physician letters, imaging reports, and anything else with narrative content goes to the LLM. A single call extracts clinical entities, diagnosis, medical necessity evidence, failed treatments, and supporting findings in a structured JSON response. One call, one response, no separate NLP pipeline to orchestrate.

Textract still runs first on the entire document, providing OCR and structure data for all pages. Comprehend Medical's full document entity extraction moves out of the main path. Instead, Comprehend Medical appears at the end as a validation step for the clinical concepts the LLM extracted.

### The Hybrid Architecture: Textract + LLM + Comprehend Medical

This is the architecture the rest of this recipe implements:

**Textract for OCR and structure.** Textract is still the best tool for extracting text from documents. It handles multi-page PDFs, returns structured blocks (text, tables, form fields, layout), provides per-field confidence scores, and operates at scale through its async API. Nothing about that changes.

**LLM for classification and clinical reasoning.** After Textract extracts the text, the LLM classifies each page and extracts the clinically relevant content from narrative pages. The LLM's strength is understanding: reading the text the way a human would, extracting meaning rather than pattern-matching against templates.

**Comprehend Medical for code validation.** LLMs are good at extracting clinical concepts ("severe osteoarthritis of the right knee," "failed conservative management"). They're less reliable for mapping those concepts to exact ICD-10 or RxNorm codes required for downstream processing. A model might produce "M17.11" from one run and "M17.1" from another, depending on how the text was phrased.

Comprehend Medical, by contrast, is purpose-built for this mapping. Run `InferICD10CM` on the diagnosis text the LLM extracted, and you get high-confidence code inferences with confidence scores. This hybrid approach gets you the LLM's contextual understanding for extraction and Comprehend Medical's precision for coding. Each service does what it was designed for.

### Cost vs. Capability: The Real Numbers

Let's put real numbers on this, because "LLMs cost more" is too vague to act on.

For a typical 10-page prior auth submission with 4 clinical pages: 

| Component | Old Approach | New Approach |
|-----------|-------------|--------------|
| Textract (FORMS+TABLES+LAYOUT) | ~$0.70 | ~$0.70 (unchanged) |
| Classification | ~$0.01 (keyword logic, negligible) | ~$0.002 (Nova Lite, negligible) |
| Clinical extraction (Comprehend Medical) | ~$0.10-0.25 per clinical page | N/A |
| Clinical reasoning (Sonnet 4.6) | N/A | ~$0.012-0.015 per clinical page |
| ICD-10 code validation | Included above | ~$0.02 (Comprehend Medical, shorter inputs) |
| **Total per submission** | **~$0.85-1.25** | **~$0.80-1.00** |

The total is comparable. But the composition tells a different story. The expensive Comprehend Medical per-character billing gives way to Sonnet per-token billing, which is cheaper per unit and produces richer, more structured output. Nova Lite classification is effectively free at any submission volume.

Here's where the cost shock actually comes from. Suppose you're new to LLM pricing and reach for Sonnet on every page, not just the clinical ones: 10 pages × $0.015/page = $0.15/submission × 500,000 submissions = $75,000/year just for the LLM step. That's real money and a noticeable increase over the old approach.

Model tiering is the resolution. Apply Nova Lite to classification (10 pages) and Sonnet only to clinical pages (3-4 pages). Total LLM cost drops to roughly $0.05-$0.07 per submission. The Textract cost dominates the total, as it should.

At 500,000 submissions per year: the LLM line item is $25,000-$35,000 annually. The Textract line item is roughly $280,000 (based on an 8-page average submission; for 10-page average, closer to $350,000). The whole pipeline runs for approximately $375,000-$450,000 per year, including Step Functions, Lambda, DynamoDB, and Comprehend Medical validation costs. That looks very different from the "AI is expensive" narrative once you've done the math.

One more lever: prompt caching. When classifying thousands of pages with the same system prompt, Bedrock's prompt caching cuts input token costs by up to 90% on cache hits. At volume, that brings the LLM line item to under $10,000 per year.

### Deterministic vs. Probabilistic: When It Matters

A keyword classifier gives you the same answer every time for the same input. An LLM might not. The same page text, run twice, usually produces the same classification at temperature=0, but not always.

For classification, near-determinism is achievable with temperature=0. At temperature zero, most models produce consistent output for consistent input. "Consistent" is not the same as "identical in every edge case," but it's close enough for page classification where the stakes of an individual misclassification are low (the page goes to human review).

For clinical reasoning extraction, perfect determinism is less achievable and arguably less important. Two runs of the same clinical note extraction might produce slightly different phrasings of the same evidence. The downstream criteria-matching system cares about the substantive content, not the exact phrasing.

Where determinism genuinely matters: financial calculations, HIPAA compliance checklists, anywhere the output feeds an audit trail that may be reviewed by regulators. In those cases, keep deterministic logic for the deterministic parts and use the LLM only where reasoning and flexibility add value.

For page classification and clinical evidence extraction in a prior auth pipeline, the LLM's probabilistic nature is an acceptable trade-off. You have a human review queue for low-confidence cases. The LLM handles the majority correctly. The edge cases it fumbles are at least *different* from the edge cases that keyword heuristics fumble.

### The General Architecture Pattern

```text
[Submission Arrives] → [Full Document Extraction (OCR + Structure)]
                                        ↓
                              [Group Pages by Number]
                                        ↓
                     [LLM Classification: What Type Is Each Page?]
                       (cheap model, temperature=0, structured response)
                                        ↓
                    ┌──────────────────────────────────────────┐
                    ↓                                          ↓
             [Cover Sheet                        [All Narrative Pages]
              → Forms Extraction]                Clinical Notes,
                    ↓                             Physician Letters,
                    └──────────┐                  Imaging Reports
                               │                        ↓
                               │    [LLM Extraction + Clinical Reasoning]
                               │    (capable model, structured JSON output)
                               │                        ↓
                               │    [Code Validation]
                               │    Authoritative ICD-10 mapping on
                               │    LLM-extracted clinical concepts
                               │                        ↓
                               └──────── [Assembler] ───┘
                                                ↓
                               [Structured Prior Auth Record]
                                                ↓
              ┌─────────────────────────────────────────────────────┐
              ↓                                                     ↓
      [Downstream:                                         [Low-Confidence Pages:
    Clinical Criteria                                        Human Review Queue]
       Matching]
```

The fan-out collapses from four specialized extractors to two main paths. The classification step moves from keyword matching to LLM inference. Code mapping moves from the extraction step to a validation step. Everything else remains structurally the same.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter01.04-architecture). The Python example is linked from there.

## The Honest Take

The keyword classifier that shipped with the original version of this recipe worked well. Really, it did. 85 to 92% accuracy on real prior auth submissions is respectable for a few hundred lines of dictionary lookups.

The moment it stopped being good enough was the day someone handed me a prior auth submission from a regional plan whose cover sheet used "Service Requested Code" instead of "CPT Code" and "Dx Indication" instead of "Diagnosis Code." The keyword classifier classified it as "other." The entire submission sat in the review queue. No automation. Manual processing, same as before.

You can fix that specific case by adding those labels to the dictionary. You can fix the next case the same way. Eventually you have a very large dictionary and someone on your team whose near full-time job is maintaining it as payer templates evolve. That's the maintenance burden the LLM eliminates.

The "aha moment" with LLM classification is surprisingly mundane. You send a page to the model, and it just... knows what it is. The physician letter from a small rural clinic using a non-standard template that would have stumped the keyword classifier? "physician_letter, confidence 0.94, reasoning: this page is a formal letter from a treating physician documenting failed conservative treatments and requesting authorization for a specific surgical procedure." No dictionary. No template matching. The model understood what it was reading.

That experience recalibrates your intuition about what's worth automating with an LLM versus a specialized service. Page classification: yes, absolutely. Lab values from a structured table: no, Textract handles that better and cheaper. The model tiering concept is how you apply that intuition systematically rather than making it up case by case.

Now for the cost shock, because I promised honesty. Go calculate what Sonnet 4.6 costs at 500,000 submissions per year with 4 clinical pages each: 500,000 × 4 × $0.015 per page = $30,000 per year for the Sonnet step alone. That sounds like a lot until you compare it to a single clinical reviewer FTE at $150,000-$200,000 fully loaded. The pipeline is still a bargain. But the number is real, and it will land in your AWS bill.

Model tiering is how you make that number smaller. Nova Lite for classification is effectively free at any realistic volume. Haiku 4.5 instead of Sonnet 4.6 for less complex narrative pages cuts the per-page cost by 70%. Prompt caching on the repeated classification system prompt cuts input costs by 90%. These are not hypothetical optimizations. They are the difference between a $30K/year LLM budget and an $8K/year one.

The architectural principle that carries forward: Textract extracts structure. LLMs reason about it. Comprehend Medical validates codes. Each service does what it was built for. That combination is what the rest of Chapter 1 builds on.

---

## Related Recipes

- **Recipe 1.1 (Insurance Card Scanning):** The OCR and key-value extraction foundation. The cover sheet extractor in this recipe reuses the Recipe 1.1 FIELD_MAP pattern directly.
- **Recipe 1.2 (Patient Intake Form Digitization):** The async multi-page Textract pattern and table extraction logic this recipe reuses for lab results pages.
- **Recipe 1.3 (Lab Requisition Form Extraction):** The Comprehend Medical `InferICD10CM` pattern this recipe uses for ICD-10 code validation.
- **Recipe 1.5 (Claims Attachment Processing):** Extends the LLM classification pattern to document boundary detection and claims-to-procedure matching.
- **Recipe 1.6 (Handwritten Clinical Note Digitization):** Introduces Bedrock vision models for page types where OCR quality is too poor for text-based LLM processing.
- **Recipe 2.4 (Clinical Criteria Matching):** Consumes the `medical_necessity_evidence` and `failed_treatments` fields from this recipe's output to evaluate whether the documentation meets the payer's medical policy criteria.
- **Recipe 3.1 (Prior Auth Decision Orchestration):** The end-to-end workflow that uses this recipe's output as the first stage in an automated prior auth decision pipeline.

---

## Tags

`document-intelligence` · `ocr` · `llm` · `bedrock` · `textract` · `comprehend-medical` · `prior-authorization` · `multi-page` · `page-classification` · `fan-out` · `step-functions` · `icd-10` · `model-tiering` · `nova-lite` · `claude-sonnet` · `moderate` · `mvp` · `hipaa` · `payer` · `utilization-management`

---

*← [Chapter 1 Index](chapter01-preface) · [← Recipe 1.3: Lab Requisition Form Extraction](chapter01.03-lab-requisition-extraction) · [Next: Recipe 1.5 - Claims Attachment Processing →](chapter01.05-claims-attachment-processing)*
