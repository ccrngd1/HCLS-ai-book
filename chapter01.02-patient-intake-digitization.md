# Recipe 1.2: Patient Intake Form Digitization ⭐

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.20 per 3-page form

---

## The Problem

You've just done something kind of remarkable in Recipe 1.1: a staff member photographs an insurance card, and seconds later your EHR has a clean, structured JSON record. One image, one page, a handful of fields, result in under three seconds. It almost feels like cheating.

Now the patient says "I filled out my paperwork" and slides a sheaf of five pages across the counter.

This is the intake form. It is a completely different animal. Depending on the practice, you're looking at two to five pages covering: patient demographics, emergency contacts, current medications (often a handwritten list in a printed table), allergy history, past surgical history, review of systems with a grid of checkboxes, insurance information, and consent signatures. The forms vary by specialty. A cardiology practice uses a different template than a pediatrics practice. Patients fill in some fields with neat printed letters and others with a scrawl that would challenge a handwriting analyst. Some fields are answered with an X in a box. Some are answered with "see attached."

Someone has to get all of that into the EHR. In most practices, that someone is a medical assistant or front desk staff who types it in manually. The industry average is 8 to 12 minutes per patient. At 30 patients a day, that's somewhere between four and six hours of data entry. Per clinic. Per day. Multiplied across hundreds of thousands of physician offices in the United States.

The downstream effects are worse than the labor cost. A transposed digit in a date of birth breaks eligibility. A skipped allergy field means the prescribing system doesn't flag the drug interaction. A misread "No" as a "Yes" on the diabetes checkbox shows up in the problem list and follows the patient for years. Paper forms with their ambiguous handwriting, inconsistent layouts, and physical fragility are one of the largest sources of data quality problems in healthcare. Not the most dramatic source, but one of the most pervasive.

We already have the core building block from Recipe 1.1. The question is how far that pattern stretches when the document gets longer, messier, and structurally richer.

Farther than you'd expect, actually. But not without a few important adaptations.

---

## The Technology: Multi-Page Document Extraction

### Why Single-Page Extraction Breaks Down

The synchronous approach from Recipe 1.1 works beautifully for a single card image. You send an image, you get a response. The whole round trip is a few seconds. For a five-page PDF scan of a patient intake form, that model doesn't hold.

The first problem is format. A JPEG photograph of an insurance card is a simple image. Intake forms typically arrive as multi-page PDFs (from document scanners) or multi-page TIFFs (from fax servers). A PDF or TIFF is not a single image. It's a container that holds multiple pages, each of which needs to be extracted independently and then reassembled into a coherent document.

The second problem is time. Processing a multi-page document takes longer than processing a single image, sometimes significantly longer. A five-page form might take ten to fifteen seconds. That's acceptable for a background process, but it breaks the synchronous request-response model: you can't hold an HTTP connection open for fifteen seconds waiting for a result. (Well, technically you can. You shouldn't. Your clients will time out, your error rates will spike, and the oncall team will be unhappy.)

The standard solution to both problems is asynchronous job-based processing. Instead of "send document, receive results," the pattern becomes "submit a job, get a job ID, receive a completion notification, then retrieve the results." This is a more complex flow to implement, but it's the right mental model for any processing task that takes more than a few seconds and any input that spans multiple pages.

This isn't an AWS-specific concept. Every managed document processing service worth using has an async mode. The shape of the pattern is consistent: submit, get ID, wait for signal, fetch.

### Tables: The Grid Problem

Simple key-value extraction works on a mental model of "there's a label somewhere near its value." That's sufficient for fields like "First Name: Maria" or "Date of Birth: 04/15/1978."

Tables are different. In a medication table, the structure is:

```text
| Medication Name | Dosage  | Frequency    | Prescribing Physician |
|-----------------|---------|--------------|----------------------|
| Metformin       | 500mg   | Twice daily  | Dr. Chen             |
| Lisinopril      | 10mg    | Once daily   | Dr. Chen             |
| Albuterol       | 90mcg   | As needed    | Dr. Patel            |
```

A naive OCR pass gives you a pile of words: "Metformin 500mg Twice daily Dr. Chen Lisinopril 10mg Once daily Dr. Chen..." You've lost the row structure. You've lost the column headers. You can't reconstruct which dosage belongs to which medication without the grid.

Table detection is a separate problem from text extraction. It works by identifying the visual grid structure (the lines that form rows and columns, or the whitespace patterns that imply grid structure when there are no visible lines) and then mapping each detected cell to a row index and column index. The result is a two-dimensional structure you can actually work with, not a linearized string.

The challenge is that tables in scanned documents aren't always clean. Borderless tables (common in intake forms because they print more cleanly on paper) rely on spatial alignment rather than drawn lines. A slightly skewed scan can shift cell alignment enough that the extraction maps cells to the wrong rows. Tables that span page breaks are particularly tricky: the extraction engine has to understand that the table continues on the next page and that the column structure carries over.

In practice, table extraction from well-formatted printed forms is quite reliable, in the 90 to 96% accuracy range for cleanly scanned documents. It degrades with poor scan quality, borderless tables, very small fonts, and anything handwritten.

### Checkboxes and Selection Elements

Medical history grids are almost universally checkbox-based. "Do you have a history of: Diabetes [ ] Hypertension [ ] Heart Disease [ ] Cancer [ ] Asthma [ ]" is a ubiquitous format. Detecting whether each box is checked or unchecked is a distinct problem from reading text.

Selection element detection works by identifying regions of the document that look like checkbox shapes (squares or circles), then classifying each one as selected or unselected based on the visual content inside the bounding box. A checked box has marks inside it. An unchecked box doesn't. Sounds simple, but the challenge is that "checked" comes in many forms: a filled-in X, a checkmark, a filled solid square, a circle with a dot, or sometimes a patient who circled the entire field instead of putting a mark in the box. Modern selection element detectors are trained on this variety and handle it well for standard printed checkboxes. The accuracy drops significantly when boxes are small, when the scan is degraded, or when a patient used a marking style that doesn't fit the training distribution.

The output of checkbox detection is a map of label-to-boolean: "Diabetes" is true, "Heart Disease" is false. This is the representation your EHR systems actually want.

### The Mixed Layout Problem

Intake forms are simultaneously structured and unstructured. The first half of a typical form is highly structured: fields with clear labels, checkboxes with clear labels, tables with headers. The second half often includes free-text sections: "Please describe any symptoms" or "List any additional concerns." And scattered throughout the structured sections are the handwritten entries: a patient who writes their current medications in the printed table by hand, or who fills in the "other" line of a checkbox group with something the form designer didn't anticipate.

You can't treat an intake form as purely a forms document (just extract key-value pairs) or purely a free-text document (just extract raw text). You need both, applied to the right sections. The general pattern is to run the full extraction (FORMS + TABLES + raw text) and then sort the output into the right buckets: structured fields from key-value extraction, structured rows from table extraction, and flagged free-text blocks for downstream processing.

Handwriting in mixed documents is a real problem, and I want to be direct about it. When a patient prints their name in block letters in a printed form, OCR handles it well. When they write in cursive, accuracy drops meaningfully. When they write in a hurry, which is most of the time, accuracy drops further. Recipe 1.6 addresses handwriting as its own dedicated problem with a tiered confidence pipeline and human review infrastructure. For this recipe, handwritten fields are extracted at best effort, confidence-gated conservatively, and flagged for human verification. That's the honest scope.

### The General Architecture Pattern

At a conceptual level, the multi-page intake form pipeline looks like this:

```text
[Ingest] → [Submit Job] → [Wait for Completion] → [Retrieve Pages] → [Parse & Classify] → [Normalize] → [Store]
```

**Ingest:** The scanned form arrives. This might be from a document scanner in the waiting room, a fax-to-PDF conversion, a patient portal upload, or a staff scan. The format is typically PDF or TIFF.

**Submit Job:** The document is handed to an extraction service with a job request. The service acknowledges receipt and returns a job identifier. This is the async contract: you know the job was accepted, you know where to check on it, and you can go do other work while it runs.

**Wait for Completion:** Rather than polling in a loop (wasteful and janky), well-designed systems use a push notification: the extraction service signals completion via a message queue or topic. Your system listens for that signal and wakes up when the job is done.

**Retrieve Pages:** Job results are paginated. A five-page form might produce hundreds of blocks of extracted content across multiple response pages. You retrieve all of them before processing begins.

**Parse and Classify:** Now the actual intellectual work starts. The raw blocks from extraction are not yet useful. You need to walk through them and classify each one: is this a key-value pair? A table cell? A checkbox result? Raw text? The parser builds the appropriate structure for each type.

**Normalize:** The same normalization work from Recipe 1.1 applies here, and then some. Field names need standardizing across payer layouts for the insurance section. Table headers need interpretation (what does "Rx" mean in context?). Checkbox labels need canonical mapping to medical concepts.

**Store:** Write the assembled, structured record. Flag fields that fell below the confidence threshold for human review. The flagged fields go into a review queue (see Recipe 1.6). The high-confidence fields go directly into downstream systems.

That's the pattern. The async job-based shape is the key conceptual shift from Recipe 1.1. Everything else is incremental complexity.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter01.02-architecture). The Python example is linked from there.

## The Honest Take

The async pattern is architecturally more complex than the synchronous call from Recipe 1.1, but don't let that scare you. The event-driven model is actually quite clean once you've built it: two small functions with one-thing-each responsibility, connected by a notification. It's easier to debug than you might expect because each function has a narrow scope. (For the specific AWS services and their quirks, see the [Architecture companion](chapter01.02-architecture).)

<!-- TODO (TechWriter): The Honest Take paragraph 2 contains AWS-specific implementation detail (Textract service role, IAM PassRole, sns:Publish). Consider generalizing to a vendor-agnostic "service role" gotcha or moving the detail to the architecture companion. -->
The thing that will surprise you is the extraction service role. The document processing service needs its own dedicated role to publish to your notification topic; it can't use your function's execution role. This is easy to miss because it's not how most services work. You'll know you got it wrong when your jobs submit successfully but completion notifications never arrive. Check the role-passing permission on your function and make sure the extraction service role has publish access on your topic.

Table parsing is more reliable than I expected for printed forms. The failure mode isn't random errors in cells; it's structural: entire rows occasionally get merged together, especially when table lines are faint in the scan. The solution is scan quality, not code changes. A decent document scanner at 300 DPI produces much better results than a phone photograph of a paper form.

Checkbox detection is the pleasant surprise. I expected it to be the weakest part of this recipe and it ended up being the most reliable. Modern extraction services correctly classify selected vs. unselected at 97-99% accuracy for standard printed checkboxes. The failure cases are mostly unusual marking styles (patients who put a number rather than an X, or who circled the entire question instead of the box). You'll see these in your flagged fields, which is the right outcome.

The honest scope boundary: this recipe handles printed text well and checkboxes well. It handles tables reasonably well. It handles handwriting with a shrug and an honest confidence score. If your patient population trends toward handwritten completion (older patients in some demographics tend to fill forms in cursive), your flagged field rate will be higher than the benchmarks above. That's not a failure; that's the confidence gating doing its job. Build the review queue from Recipe 1.6 before you go to production.

---

## Related Recipes

- **Recipe 1.1 (Insurance Card Scanning):** The synchronous single-page foundation this recipe builds on. Start there if you haven't yet: the field normalization and confidence gating patterns carry forward directly.
- **Recipe 1.3 (Lab Requisition Form Extraction):** The next step up in complexity. Adds medical NLP on top of the document extraction foundation established here: extracting ICD-10 codes and clinical entities from the free-text sections that this recipe intentionally leaves unparsed.
- **Recipe 1.6 (Handwritten Clinical Note Digitization):** Addresses the handwriting problem this recipe sidesteps. Builds the full tiered confidence pipeline and human review queue that the flagged fields from this recipe feed into.
- **Recipe 8.1 (Insurance Eligibility Matching):** Consumes the member ID and group number from the insurance section of this recipe to verify coverage in real time.

---

## Tags

`document-intelligence` · `ocr` · `textract` · `forms` · `tables` · `checkboxes` · `intake-forms` · `patient-demographics` · `async` · `multi-page` · `simple` · `mvp` · `lambda` · `s3` · `dynamodb` · `sns` · `hipaa`

---

*← [Chapter 1 Index](chapter01-preface) · [← Recipe 1.1: Insurance Card Scanning](chapter01.01-insurance-card-scanning) · [Next: Recipe 1.3 - Lab Requisition Form Extraction →](chapter01.03-lab-requisition-extraction)*
