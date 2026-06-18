# Recipe 1.5: Claims Attachment Processing 🔶

**Complexity:** Complex · **Phase:** Phase 2 · **Estimated Cost:** ~$2.20-2.40 per 30-page claims package 

---

## The Problem

Imagine you're a claims examiner. A 38-page PDF lands in your queue. It's a claims attachment package from a provider supporting a surgical claim. You open it.

Page 1 is the last page of an operative report. Page 2 is the beginning of a pathology result, except it doesn't say "PATHOLOGY REPORT" at the top; it just starts with a gross description of the specimen. Pages 3 through 6 are a discharge summary, but pages 4 and 5 are printed sideways. Page 7 is a consent form that has nothing to do with the claim. Pages 8 through 12 are an Explanation of Benefits from the patient's secondary payer, printed from a payer web portal with their specific layout. Pages 13 and 14 are therapy notes from three different visits, all crammed into a continuous print job with no clear breaks. Page 15 is a billing statement, but it's from a different facility than the claim you're looking at.

Nobody assembled this thoughtfully. The provider's billing staff went into their EHR, selected everything that seemed relevant to the claim, hit print, and sent the whole stack through a fax machine. The output is a single PDF that contains somewhere between four and eight distinct logical documents, in no particular order, with no table of contents, and no cover sheet telling you what's in there.

Now the claims examiner has to do the following. Find the operative report. Confirm the CPT code documented in the operative note matches line item 1 on the claim (total knee arthroplasty, 27447). Find the pathology result and confirm there's a specimen consistent with the procedure. Find the EOB and check what the secondary payer paid, to determine coordination of benefits. Look at the therapy notes and verify the dates of service match the claim lines. Cross-reference the billing statement's itemized charges against what the provider billed on the 837 transaction.

This takes 30 to 60 minutes. For a complex surgical claim. And payers process hundreds of thousands of claims attachments annually.

Recipe 1.4 introduced the page classification and fan-out pattern for multi-page documents, along with the LLM reasoning layer that replaced keyword heuristics. That pattern works well when you're dealing with a submission that has a recognizable structure: cover sheet first, then clinical notes, maybe some labs. Prior auth submissions are still constrained. There's usually a cover sheet that anchors the document. The page types are limited. The total page count rarely exceeds 15.

Claims attachments are a different animal. They're larger (15 to 50 pages is typical). The document types are more varied. There's no cover sheet. And most critically: the package contains multiple independent documents that have been physically concatenated into one PDF. The documents have nothing to do with each other structurally. The page numbers in the PDF don't align with the page numbers in the individual documents. The formatting changes abruptly between documents because each was printed from a different source system.

The key capability this recipe builds on top of Recipe 1.4 is **document boundary detection**: figuring out where one logical document ends and the next begins before doing any classification or extraction. Get that wrong and everything downstream breaks. Misidentify a page boundary and you extract a hybrid document that's half operative report and half pathology result; neither extractor knows what to do with it.

And then there's the capstone problem. Claims aren't a single yes/no decision like prior auth. A surgical claim has six or seven line items. Each one needs independent documentation support. The question isn't "is this claim supported?" It's "which specific line items are supported, and which are missing?" For line item 1 (CPT 27447, total knee arthroplasty), does this operative report actually describe a total knee replacement? That question is pure reasoning. No rule-based system answers it reliably. An LLM does.

This is the claims attachment problem. It's harder than prior auth. Here's how LLMs make it tractable.

---

## The Technology

### The Multi-Document Concatenation Problem

When you look at a claims attachment PDF, you're seeing the result of a process that the sending system didn't design for machine readability. The provider's EHR or billing platform prints each document independently, then combines the pages into a single fax job. The resulting PDF has no logical structure that corresponds to the document boundaries. It's a flat page stream.

The technical challenge is that a flat page stream looks identical whether it contains one long document or six short documents back-to-back. The only signals available are what's printed on the pages themselves: headers, title lines, page numbering patterns, date stamps, facility names, and formatting discontinuities.

Document boundary detection is the process of analyzing those signals to infer where boundaries fall. It's probabilistic. It can be wrong. The design goal is not to be right 100% of the time; it's to be right often enough that the downstream classification and extraction pipeline handles the common cases automatically, and the failure modes are identifiable so they can route to human review.

### Signals for Document Boundary Detection

The most reliable signals, roughly ordered from strongest to weakest:

**Document title lines.** Many document types have characteristic title lines that appear at or near the top of the first page: "OPERATIVE REPORT," "PATHOLOGY REPORT," "DISCHARGE SUMMARY," "EXPLANATION OF BENEFITS." When a page has a strong document title in the first few lines, it's almost certainly the start of a new logical document. This is the most reliable single signal, when it's present. It's not always present.

**Header and footer discontinuity.** Each document typically has its own header: facility name, department, date range, patient name formatted according to that system's template. When the header on page N is materially different from the header on page N-1, a boundary likely exists between them. This requires extracting the header region (roughly the top 15% of each page) and comparing them. The comparison isn't exact string matching: the same facility might print its name with different abbreviations.

**Page number restart.** Many documents include explicit page numbering: "Page 1 of 6," "Page 2 of 6," etc. When a "Page 1" appears after a page that is not the end of a prior sequence, that's a reliable boundary signal. The complication: some documents don't number pages, some number them inconsistently, and some fax servers insert their own page count that overrides the document's.

**Date discontinuity.** Clinical documents are anchored to specific service dates. An operative report from March 15 followed by a discharge summary dated February 20 almost certainly represents a boundary, even if there's no other visual signal. Date discontinuities of more than a few days are worth flagging. This requires date extraction from the page text, which has its own noise: date formats vary, and some pages contain multiple dates.

**Format discontinuity.** An abrupt change in font density, column layout, or the presence/absence of table structure can indicate a boundary. This is the weakest signal but sometimes the only one available.

Here's the thing about building a rule-based system to evaluate all of this: you end up writing separate rules for each signal type, tuning thresholds for each, and dealing with the interactions between them. What happens when a page restart fires but the header didn't change? What happens when the date jumps but the header looks the same? You need a priority ordering. You need override logic. You need to test and re-tune every time a new payer sends a non-standard format.

Or you can send the page pair to a language model and ask it to evaluate all of these signals simultaneously, the same way a human would. A model trained on vast amounts of clinical and administrative text understands what an operative report header looks like versus a pathology report header. It understands that "Page 1 of 4" after a run of numbered pages means something. It can reason about date context in a way that a regex pattern cannot. This is where LLMs genuinely shine: judgment calls that require weighing multiple imperfect signals at once.

### Why Document-Level Classification Beats Page-Level

Recipe 1.4 classifies each page individually, then routes pages to extractors. That works for prior auth submissions because each page in a prior auth is effectively its own document type. An imaging report is usually one or two pages. A clinical note is one page. The page-level is close enough to the document-level.

Claims attachments break this assumption. An operative report is four to eight pages of continuous narrative. A pathology report is two to four pages. A discharge summary is three to six pages. If you classify these page-by-page, you'll correctly classify the first page of each (it has the title line and strong keyword signals) but misclassify the middle and ending pages (they're dense clinical prose without the header signals that make the first page identifiable).

The right unit of classification for claims attachments is the logical document, not the page. Once you've run boundary detection and know that pages 3 through 7 form a single logical document, you can look at all five pages together when classifying. The classifier has the full operative report vocabulary available, not just whatever happened to appear on page 5 in isolation.

This also resolves an LLM-specific advantage: with full document context, the model can recognize not just what type of document this is, but what specific evidence it contains. Knowing that pages 1 to 6 are an operative report for a total knee arthroplasty is more useful than knowing that page 3 is "a clinical page."

### The Document Type Taxonomy

Claims attachments can contain more document types than prior auth submissions. The taxonomy for this recipe covers the most common ones:

**Operative reports.** Structured clinical narrative of a surgical procedure. Sections include preoperative diagnosis, postoperative diagnosis, procedure performed, anesthesia, findings, operative technique, estimated blood loss, specimens sent, and surgeon attestation. The procedure performed section is what links the document to claim line items.

**Pathology and histology reports.** Results of specimen analysis after surgical resection or biopsy. These documents link to surgical claim lines indirectly: they confirm that specimens described in the operative report were sent for analysis and what was found.

**Discharge summaries.** Multi-page clinical narrative covering the full hospital episode: admitting diagnosis, hospital course, consultations, procedures performed, discharge diagnosis, discharge medications, and follow-up instructions. Relevant to DRG-based facility claims and post-acute claims.

**Explanation of Benefits from other payers.** When a patient has coordination of benefits across two payers, the primary payer's EOB becomes a claims attachment for the secondary payer. These documents have table-heavy layouts specific to each payer: service lines, billed amounts, allowed amounts, plan paid amounts, patient responsibility, and denial codes.

**Therapy notes and progress notes.** Visit-level clinical documentation from physical therapy, occupational therapy, speech therapy, or outpatient mental health. A claims attachment package may contain multiple visit notes from different dates with no separator. The claim lines they support are visit-level CPT codes, so the date of service match is critical.

**Billing statements and itemized charges.** Provider-generated financial documents showing the breakdown of charges for the episode. Line items typically include service date, procedure code, revenue code, charge amount, and facility cost center.

**Other.** Consent forms, referral letters, prior auth approvals, face sheets, and other administrative documents that end up in attachment packages by accident.

### Claim Line Item Matching: The Reasoning Problem

Here's what distinguishes claims attachment processing from prior auth in terms of what the downstream system actually needs. With prior auth, the goal is to produce a single clinical evidence record that supports or doesn't support one requested service. There's one CPT code being evaluated.

Claims have multiple line items. A surgical claim might have six lines: the primary procedure, anesthesia, one or more modifiers for assistant surgeon or bilateral, a pathology code, and a post-operative visit. Each line item needs to be supported by documentation.

Claim line item matching is the process of linking the extracted data from each document back to the relevant claim lines. The rule-based approach to this matching uses a keyword lookup table: a dictionary mapping CPT codes to procedure description variants. CPT 27447 maps to "total knee arthroplasty," "total knee replacement," and "TKA." If any of those strings appear in the operative report's procedure section, the line is considered supported.

That approach works on well-behaved operative reports. It fails on:

- Reports that describe the procedure without using the standard terminology ("replacement of the tibial and femoral articular surfaces with cemented prosthetic components" is 27447, but there's no rule for that)
- Bilateral procedures where one claim line covers both sides
- Compound CPT codes with modifiers that change the documentation requirements
- Unlisted procedure codes where the description is the only guide to what was done

The claim line matching problem is fundamentally a reasoning task. "Does this operative report support CPT code 27447?" is the same question a medical necessity reviewer would ask. You need to understand what 27447 is, read the operative report, and reason about whether what's described matches what was billed.

An LLM with clinical knowledge can do this. You show it the operative report text and the claim line, and ask: does this procedure description support this CPT code? The model reasons from its training on clinical documentation and medical coding to give you an assessment with supporting evidence. No lookup table needed. No edge cases for standard variant descriptions.

### The General Architecture Pattern 

The pipeline has four stages, building directly on Recipe 1.4's hybrid pattern.

**Stage 1: Full-document extraction.** Async OCR and document analysis on the entire PDF produces text, form fields, tables, and layout structure for every page. Same as Recipe 1.4.

**Stage 2: LLM document boundary detection.** The page stream is analyzed for boundaries by feeding consecutive page pairs to a lightweight model. The model evaluates each pair and answers: same document or different? The output is a list of logical document segments.

**Stage 3: LLM document classification and extraction.** Each logical document is classified by sending its full text to a language model. Classified documents fan out to type-specific extractors. Clinical documents go through an LLM for content extraction. Financial documents (EOBs and billing statements) go through structured table parsing.

**Stage 4: LLM claim line matching and assembly.** The extraction results from all segments are matched against the claim's line items using LLM reasoning. The model is asked, per clinical document, which claim lines it supports and why. The final record identifies which lines have documentation support and which don't.

```text
[Claims Attachment Arrives] → [Full Document Extraction (OCR + Structure)]
                                              ↓
                                  [Group Blocks by Page]
                                              ↓
                  [LLM Boundary Detection: Tier 1 LLM per page pair]
                  ("Same document or different? Evaluate all signals.")
                                              ↓
                          [Logical Document Segments]
                          (pages 1-4, pages 5-6, pages 7-12...)
                                              ↓
                  [LLM Document Classification: Tier 1 LLM per segment]
                  (full document context, not single-page snippets)
                                              ↓
     ┌──────────┬──────────┬──────────┬──────────┬──────────┐
     ↓          ↓          ↓          ↓          ↓          ↓
[Clinical    [Clinical  [EOB        [Clinical  [Clinical [Billing
 Document    Document   Extractor:  Document   Document  Statement:
 LLM]        LLM]       Structured  LLM]       LLM]      Structured
                        Table                            Table
                        Parser]                          Parser]
     ↓          ↓          ↓          ↓          ↓          ↓
     └──────────┴──────────┴──────────┴──────────┴──────────┘
                                              ↓
             [LLM Claim Line Matching: Tier 3 LLM per clinical document]
             ("Does this operative report support CPT 27447?")
                                              ↓
                   [Unified Claims Attachment Record]
                                              ↓
          ┌────────────────────────────────────────────┐
          ↓                                            ↓
 [Downstream: Auto-adjudication              [Unmatched / Low-Confidence:
  or Examiner Workstation]                    Human Review Queue]
```

The model tiering is deliberate. Boundary detection is a binary question per page pair: is this a new document or not? A lightweight Tier 1 model handles it reliably and cheaply. Document classification gives the LLM a full document's worth of text; the Tier 1 model works here too. Claim line matching is where complex clinical reasoning happens: understanding what a CPT code means, reading a procedure description, and assessing equivalence across terminology variations. That's a Tier 3 task.

This is the architectural breakthrough in this recipe versus the rule-based approach it replaces: boundary detection by LLM reasoning, classification by LLM reasoning, and claim matching by LLM reasoning. OCR still handles the text extraction. But the intelligence layer is now end-to-end LLM. 

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter01.05-architecture). The Python example is linked from there.

## The Honest Take

The rule-based boundary detection in the original published version of this recipe was more code than it looked. You had the signal extraction for each type (header text parsing, page restart regex, date extraction, fuzzy comparison logic), the signal priority ordering, the tuned thresholds for each signal, and the override rules for when multiple signals fired at once. It worked. On the documents it was calibrated to, it worked well.

Then a provider started sending packages where their EHR printed a running date header on every page, including when the document type changed. Date discontinuity: no signal. Header continuity: strong "same document" signal. The boundary detection missed every transition in that provider's submissions. The fix was another special case in the header comparison logic. And then another provider did something different. The rule list grew.

The LLM approach doesn't eliminate errors. The model still misses boundaries occasionally, particularly on the continuous EHR print job problem I mentioned above. But the failure modes are different. The rule-based system failed systematically on predictable template variations. The LLM fails on genuinely hard cases: pages that really are ambiguous, documents that don't have any of the standard signals, content that would confuse a human reviewer too. That's a better failure distribution.

The claim line matching improvement is the one that genuinely surprised me. I went in expecting the LLM to do marginally better than the lookup table, catching some edge cases that the dictionary missed. What I actually got was a model that could explain its reasoning: "The procedure description says 'right total knee arthroplasty with cemented components,' which is consistent with CPT 27447. The date of service in the document (March 15) matches the claim line." The explanation is what the examiner needs when they're reviewing a claim. Not just a match/no-match flag, but the evidence behind it.

Here's the cost reality, because I promised honesty. The Textract cost hasn't changed: it still dominates the per-package bill at around $2.00 for a 30-page package. The LLM costs are smaller than you might expect. Nova Lite boundary detection on 29 page pairs costs less than a cent. Nova Lite classification on 5 documents costs less than a cent. The Claude Sonnet 4.6 claim matching calls (one per clinical document, 3 to 4 calls per package) run about $0.05 to $0.12 per package. The total per-package cost is actually somewhat lower than a comparable Comprehend Medical per-character billing pipeline, while producing richer output. The math on this one works out in your favor.

The one cost trap to avoid: don't run the full segment text through Claude Sonnet 4.6 for every step. The clinical extraction prompt already summarizes the document; the claim matching step uses that summary, not the raw page text. Keeping the claim matching inputs tight (structured extraction outputs rather than raw document text) is what keeps the per-claim Sonnet spend reasonable.

The path from this recipe to production runs through measurement, feedback loops, and model version management. None of that is glamorous. All of it matters.

---

## Related Recipes

- **Recipe 1.1 (Insurance Card Scanning):** The key-value extraction foundation used in the EOB header field parsing.
- **Recipe 1.2 (Patient Intake Form Digitization):** The async multi-page Textract pattern and table parsing logic reused in the EOB and billing statement extractors.
- **Recipe 1.3 (Lab Requisition Form Extraction):** The Comprehend Medical `InferICD10CM` pattern this recipe uses for ICD-10 code validation on clinical documents.
- **Recipe 1.4 (Prior Authorization Document Processing):** Introduced the Bedrock classification prompt pattern and model tiering concept this recipe extends. Read 1.4 before this one.
- **Recipe 1.6 (Handwritten Clinical Note Digitization):** Handles handwritten therapy notes and physician addenda that appear within claims attachment packages. Low-confidence segments from this recipe's pipeline route to the Recipe 1.6 review workflow.
- **Recipe 1.8 (EOB Processing):** Covers EOB-specific extraction in depth. When your claims portfolio has high EOB volume or unusual payer formats, Recipe 1.8's specialized table normalization is more robust than the general-purpose EOB extractor here.
- **Recipe 2.4 (Clinical Criteria Matching via NLP):** Consumes the aggregated ICD-10 codes and clinical entities from this recipe's output for criteria evaluation on complex surgical claims.

---

## Tags

`document-intelligence` · `ocr` · `llm` · `bedrock` · `textract` · `comprehend-medical` · `claims-attachment` · `document-segmentation` · `document-classification` · `boundary-detection` · `claim-line-matching` · `step-functions` · `multi-document` · `eob` · `operative-report` · `icd-10` · `model-tiering` · `nova-lite` · `claude-sonnet` · `complex` · `phase-2` · `hipaa` · `payer` · `claims-processing`

---

*← [Chapter 1 Index](chapter01-preface) · [← Recipe 1.4: Prior Authorization Document Processing](chapter01.04-prior-auth-document-processing) · [Next: Recipe 1.6 - Handwritten Clinical Note Digitization →](chapter01.06-handwritten-clinical-note-digitization)*
