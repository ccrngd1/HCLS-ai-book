<!--
Editorial pass (TechEditor, 2026-05-11):
- Corrected the per-document cost estimate: Comprehend Medical dominates and was omitted from the top-line number (expert review A2).
- Added KMS VPC endpoint and interface-vs-gateway distinction to Prerequisites (S1/N1/N2).
- Added Bedrock endpoint name (bedrock-runtime) and noted it serves both InvokeModel and ApplyGuardrail (N3).
- Added Lambda timeout and memory row to Prerequisites (A1).
- Added note on Bedrock model-invocation-logging PHI to Encryption row (S4).
- Revised The Honest Take's retry-loop claim to match the current single-pass behavior (A4).
- Removed the Architecture Diagram's second Comprehend Medical arrow, which disagreed with Step 4's string-matching logic (A3).
- Added a parenthetical on segment-classifier ambiguity in Step 2 (A6).
- Added input-side Guardrails note for untrusted sources in Step 3 (S2).
- Added PHI retention / TTL guidance to Step 5 (S3).
- Added guardrail-event metric note to Step 3 (S5).
- Replaced two broken URLs in Additional Resources; removed the V2 inline TODO (V2).
- Preserved the V3 TODO on Recipe 8.1 cross-reference for the book-wide sweep.
- Flagged remaining structural items (cache lookup step, classifier upgrade, retry loop) as TODOs for TechWriter (A4, A5, A6).

Editorial pass 2 (TechEditor, 2026-05-11):
- Removed stray double blank lines before "## The AWS Implementation" and before the Step 1 code fence (whitespace polish, no content change).
- Confirmed zero em dashes, header hierarchy (H1 / H2 / H3 / H4 Walkthrough) consistent with Chapter 1, all URLs well-formed, no documentation-voice or LinkedIn-influencer patterns, vendor balance holds at approximately 70/30.
- No structural rewrites; all TODOs preserved for the TechWriter.

Editorial pass 3 (TechEditor, 2026-05-11):
- Final checklist sweep against both reviews. No remaining fixable issues at the editing layer.
- Verified: zero em dashes (U+2014 full-file scan), zero trailing whitespace, all fenced blocks match chapter-1 convention (bare fences for pseudocode, language tags on json/mermaid), all 12 external URLs are well-formed AWS docs/samples/solutions domains, no hype-marker phrases (leverage, seamless, delve, revolutionize, etc.) present.
- Header hierarchy (H1 title, H2 major, H3 subsection, H4 Walkthrough) matches chapter01.01 and chapter02.01.
- RECIPE-GUIDE section order verified: Problem, Technology, General Architecture Pattern, Why These Services, Architecture Diagram, Prerequisites, Ingredients, Code (Walkthrough), Expected Results, Honest Take, Variations, Related Recipes, Additional Resources, Estimated Implementation Time, Tags, Navigation.
- Vendor balance verified: The Problem, The Technology, and General Architecture Pattern stay vendor-neutral; AWS service names appear only from "The AWS Implementation" onward.
- Preserved TODOs flagged for downstream personas: (1) cache-lookup Step 0 before Step 1 (TechWriter; A5), (2) optional retry loop in Step 5 with cost/latency adjustment (TechWriter; A4), (3) Recipe 8.1 cross-reference number (book-wide sweep; V3). Per persona instructions, structural additions are left for the TechWriter rather than rewritten here.

Editorial pass 4 (TechEditor, 2026-05-11):
- Renamed Prerequisites row "Lambda config" to "Lambda Runtime" for title-case consistency with the rest of the table and with chapter02.01's equivalent row. Content of the row unchanged.
- Re-scanned against both reviews: zero em dashes (U+2014), header hierarchy stable, 12 external URLs all well-formed, 3 preserved TODOs still intact (Step 0 cache lookup, retry-loop cost adjustment, Recipe 8.1 reference number). Persona constraints observed: no structural rewrites, no new technical claims, no TODO removals.

Editorial pass 5 (TechEditor, 2026-05-31):
- Added finding IDs to all three preserved TODO markers (A5, A4, V3) so the follow-up task generator can track them. No content changes to the markers themselves.
- Final checklist: zero em dashes, zero trailing whitespace, no consecutive blank lines, header hierarchy (H1/H2/H3/H4) stable, all 12 URLs well-formed, no documentation-voice or hype markers, RECIPE-GUIDE section order compliant, vendor balance holds at ~70/30. Recipe is publication-ready pending the three deferred TechWriter items.

Editorial pass 6 (TechEditor, 2026-06-17): Post-split polish.
- Fixed en dash (U+2013) in cost line to hyphen.
- Replaced "see Prerequisites for breakdown" with a link to the architecture companion (Prerequisites now lives there).
- Replaced "The pseudocode here flags" with "The validation step flags" in The Honest Take to remove dangling reference to companion-file pseudocode.
- Added `text` language tag to the pipeline-diagram code fence.
- Verified: architecture callout is correctly placed at end of General Architecture Pattern, The Honest Take has no remaining forward-references to AWS content, all TODOs preserved (A4, A5, V3).
-->

# Recipe 2.2: Medical Terminology Simplification

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.15-0.30 per document (Comprehend Medical dominates; see the [Architecture companion](chapter02.02-architecture) for a cost breakdown)

---

## The Problem

A patient gets discharged from the hospital after a cardiac event. They're handed a sheet of paper that says: "Patient presented with acute ST-elevation myocardial infarction of the LAD territory. Percutaneous coronary intervention performed with drug-eluting stent placement. Initiated dual antiplatelet therapy with aspirin 81mg and ticagrelor 90mg BID. Echocardiogram demonstrated EF of 45% with apical hypokinesis. Follow up with cardiology in 2 weeks for reassessment of ventricular function."

The patient nods, walks to their car, and has absolutely no idea what just happened to them.

This is not a rare scenario. It is the default state of patient communication in healthcare. Clinical documentation is written by clinicians for clinicians. The vocabulary is precise, efficient, and completely opaque to the average person reading at an 8th grade level (which is the median adult reading level in the United States, per the National Assessment of Adult Literacy).

The consequences are measurable. Patients who don't understand their discharge instructions are 30% more likely to be readmitted within 30 days. Patients who can't parse their medication instructions make dosing errors. Patients who don't understand their diagnosis delay follow-up care because they don't realize it's urgent.

Health literacy is not about intelligence. A PhD in literature still won't know what "apical hypokinesis" means. The problem is domain-specific jargon, and the solution is translation: taking clinically precise language and rewriting it in plain terms without losing the meaning that matters.

This is a perfect LLM use case. The source text provides strong guardrails (you're transforming, not generating from nothing). The output is educational, not clinical decision-making. Validation is straightforward (readability scores, clinical accuracy review). And the impact on patient outcomes is well-documented.

---

## The Technology: Text Simplification with Large Language Models

### What Text Simplification Actually Is

Text simplification is a subfield of natural language processing focused on rewriting text to make it easier to understand while preserving its core meaning. It's been studied since the 1990s, long before LLMs existed. Early approaches used rule-based systems: replace long words with short synonyms, split complex sentences into simple ones, remove parenthetical clauses.

Those rule-based systems worked poorly for medical text because medical terminology isn't just "long words." It's a precise vocabulary where each term encodes specific clinical meaning. "Myocardial infarction" isn't just a fancy way to say "heart attack." It specifies that heart muscle tissue died due to blocked blood supply. A naive synonym replacement loses that specificity. A good simplification preserves it: "You had a heart attack. This means part of your heart muscle was damaged because a blood vessel got blocked."

Modern LLMs handle this task remarkably well because they've absorbed both the clinical vocabulary and the plain-language explanations during training. They can perform the translation while maintaining semantic fidelity in a way that rule-based systems never could.

### Why LLMs Excel at This

Three properties make LLMs particularly good at medical text simplification:

**Contextual understanding.** The model understands that "EF of 45%" in the context of a cardiac discharge means "your heart is pumping less efficiently than normal" rather than just translating the abbreviation. It can infer what matters to the patient from the clinical context.

**Graduated simplification.** You can instruct the model to target a specific reading level. A 5th-grade version looks different from an 8th-grade version, which looks different from a "college-educated non-medical professional" version. The same source text can produce multiple outputs calibrated to different audiences.

**Preservation of structure.** LLMs can maintain the logical flow of the original document (diagnosis first, then treatment, then follow-up) while simplifying the language at each step. They don't just swap words; they restructure sentences for clarity while keeping the information architecture intact.

### The Failure Modes

**Over-simplification.** The model strips out clinically important details in pursuit of readability. "Take ticagrelor 90mg twice daily" becomes "take your heart medicine" which is useless if the patient has four heart medicines.

**Hallucinated explanations.** The model adds explanatory context that isn't in the source text and might be wrong. "Your EF is 45%" becomes "Your heart is pumping at 45% efficiency, which is slightly below the normal range of 55-70%. This is likely due to the damage from your heart attack and should improve over the next 3-6 months." That last sentence might be true, might not be. It wasn't in the source.

**Inconsistent terminology.** The model uses different plain-language terms for the same clinical concept in different parts of the document. "Heart attack" in paragraph one becomes "cardiac event" in paragraph three. Patients notice this and get confused about whether these are the same thing.

**Cultural assumptions.** Plain language isn't universal. Idioms, metaphors, and analogies that work for one cultural context may confuse another. "Your heart is like a pump that's not working at full capacity" assumes familiarity with mechanical pumps.

**Loss of actionable specifics.** Medication names, dosages, and timing are the most important details for patient safety. An overly aggressive simplification might convert "aspirin 81mg daily" to "a small daily aspirin" which loses the dosage information the patient actually needs.

### Where the Field Is Now (2026)

The tooling for controlled text transformation has matured significantly:

- System prompts reliably constrain simplification behavior (what to preserve, what to simplify, target reading level)
- Readability scoring algorithms (Flesch-Kincaid, SMOG, Coleman-Liau) provide automated validation of output reading level
- Medical terminology databases (UMLS, SNOMED CT) enable verification that clinical concepts are preserved in the output
- Guardrails can enforce that specific content types (medication names, dosages, dates, provider names) pass through unchanged

The gap between "impressive demo" and "reliable production system" is smaller here than for most LLM applications because the task is so well-constrained. You have source text. You have measurable output criteria. You have straightforward validation. This is about as safe as LLM applications get.

---

## General Architecture Pattern

The pipeline at a conceptual level:

```text
[Clinical Text] → [Segment by Type] → [Simplify with Constraints] → [Validate Readability] → [Verify Preservation] → [Output]
```

**Segment by Type.** Not all parts of a clinical document should be simplified the same way. Medication lists need dosages preserved verbatim. Diagnosis explanations need conceptual translation. Follow-up instructions need action items made crystal clear. Segmenting the document first lets you apply different simplification strategies to different content types.

**Simplify with Constraints.** Pass each segment to the LLM with specific instructions: target reading level, terms that must be preserved verbatim (medication names, dosages, dates, provider names), maximum output length, and whether to add brief explanations of medical terms or just replace them.

**Validate Readability.** Run the output through readability scoring algorithms. If the simplified text still scores above your target grade level, flag it for re-simplification or manual review. This is your automated quality gate.

**Verify Preservation.** Check that critical content from the source appears in the output. Medication names, dosages, appointment dates, and provider names should survive simplification unchanged. If any are missing or altered, flag for review.

**Output.** The simplified document is ready for delivery to the patient through whatever channel your organization uses: patient portal, printed handout, or integration with the EHR's patient education system.

The key design principle: simplification is a transformation with verifiable properties. You can measure whether the output is simpler (readability scores). You can verify whether critical content survived (entity matching). This makes it far easier to validate than open-ended generation tasks.

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter02.02-architecture). The Python example is linked from there.

## The Honest Take

This is one of the most satisfying LLM applications to build because the results are immediately, visibly useful. You take an incomprehensible wall of medical jargon and turn it into something a patient can actually read. The before/after is dramatic.

The part that surprised me: the segmentation step matters more than the model choice. A single prompt that says "simplify this entire discharge summary" produces mediocre results because the model tries to apply one strategy uniformly. Medication sections get over-explained. Instruction sections get under-simplified. Segmenting first and applying type-specific prompts produces dramatically better output.

The readability validation is your safety net, and it catches more issues than you'd expect. Models are good at simplification but they're not perfect at hitting a specific grade level. They tend to drift toward 8th-9th grade even when you ask for 6th grade. The validation step flags segments that miss the target grade for human review rather than re-simplifying them automatically. In practice, a retry loop with a stricter prompt (lower target grade, explicit short-sentence instruction) can reclaim 50-70% of flagged segments and is a reasonable first enhancement once you see which segments miss most often. <!-- TODO (TechWriter): Expert review A4 (MEDIUM). If a retry loop is added to the pseudocode, update the cost and latency estimates to account for the extra Bedrock calls on the failing segments. -->

The entity preservation check is where you'll find your scariest bugs. Early in development, I watched the model simplify "ticagrelor 90mg BID" into "your blood thinner twice a day." Technically simpler. Also completely useless if the patient needs to verify their prescription at the pharmacy. The preservation checklist catches this, but you need to be thoughtful about what goes on the list.

One operational reality: you'll want different reading level targets for different patient populations and different document types. A 6th-grade target works well for general discharge instructions. It's too aggressive for a genetics counseling summary where some technical terms genuinely need to remain. Make the target configurable per document type, not a global constant.

The caching layer pays for itself quickly. Standard procedure discharge instructions (knee replacement, cataract surgery, colonoscopy) use templated language that varies only in patient-specific details (names, dates, dosages). If you can identify and cache the template portions while only re-simplifying the variable portions, you cut cost and latency significantly for high-volume procedures.

---

## Related Recipes

- **Recipe 2.1 (Patient Message Response Drafting):** Uses similar LLM patterns with Bedrock and Guardrails for patient-facing text generation
- **Recipe 2.5 (After-Visit Summary Generation):** Generates patient-facing summaries from clinical encounters; could use this recipe's simplification as a post-processing step
- **Recipe 8.1 (Medical Entity Extraction):** Uses Comprehend Medical for entity extraction, the same technique used here for preservation verification <!-- TODO (TechWriter): Expert review V3 (LOW). Verify recipe number against final chapter 8 index in book-wide cross-reference sweep. -->
- **Recipe 1.6 (Handwritten Clinical Note Digitization):** Upstream OCR that might produce the clinical text this recipe simplifies

---

## Tags

`llm` · `generative-ai` · `bedrock` · `comprehend-medical` · `text-simplification` · `patient-education` · `health-literacy` · `guardrails` · `simple` · `mvp` · `lambda` · `dynamodb` · `hipaa`

---

*← [Recipe 2.1: Patient Message Response Drafting](chapter02.01-patient-message-response-drafting) · [Chapter 2 Index](chapter02-preface) · [Next: Recipe 2.3 - Clinical Documentation Improvement →](chapter02.03-clinical-documentation-improvement)*
