# Recipe 1.10: Historical Chart Migration 🔷

**Complexity:** Complex · **Phase:** Phase 3 · **Estimated Cost:** ~$0.80–8.00 per chart (varies by page count, handwriting density, and model tier distribution)

---

## The Problem

Somewhere in your organization's past, there is a room. Maybe several. It might be a warehouse three states away full of filing cabinets. It might be a vendor's scanning facility in the middle of processing 40,000 charts from a physician group you acquired last year. It might be a PACS server running Windows Server 2008 that nobody touches because the 1.2 terabytes of scanned documents on it are in a format the new EHR team has been avoiding for four years.

Those records are not just legacy data. They are clinical history. A member diagnosed with hypertension in 1998 who managed it quietly through two decades' worth of primary care before landing in your network: that paper chart is the difference between a care manager who knows which medications she tried and one who's starting from scratch. For risk adjustment programs, a diagnosis documented in ink on paper that never made it into an EHR is simply invisible. Invisible revenue. Invisible clinical context.

The regulatory pressure keeps mounting. CMS Interoperability and Patient Access rules require payers to make member data available via FHIR APIs, and "member data" includes longitudinal history. HEDIS and Stars programs reward complete longitudinal records. The HIPAA Right of Access means members can request their complete records, including the ones still sitting in archive boxes. The argument for deferring this work is getting harder to make every year.

And then there is the actual problem. These documents are not clean. A chart from a busy primary care practice spanning 1990 to 2010 might be 300 pages of: handwritten progress notes from three physicians with three different handwriting styles; printed lab results from two different lab information systems with different layouts; thermal fax paper that has degraded to near-illegibility; sticky notes attached to pages with additional observations; forms from a dozen specialists, each designed by a different practice; photocopied records from other facilities with additional generation loss; pages rotated or out of order from the scanning process; sections someone photocopied three times before realizing the original was in another folder.

Every chart is different. Every provider documented differently. Every scanning vendor has slightly different equipment and QC standards. There is no clean version of this problem.

A mid-size payer with ten million historical member-years of records might be looking at 20 million charts, averaging 150 pages each, for a total of three billion pages. At that scale, the choice of tools is not an engineering preference. It is a business viability question.

Here is where cost math becomes the defining constraint. Textract async analysis plus Amazon Comprehend Medical (the traditional approach) runs roughly $0.12 to $0.32 per page once you account for FORMS, TABLES, and clinical entity extraction. For three billion pages, that is $360 million to $960 million. That range is not a typo. The upper bound is real when handwriting density is high and human review rates climb. Nobody approves a chart migration program with a $360 million floor.

The LLM-tiered pipeline in this recipe changes those numbers dramatically. With Amazon Bedrock batch inference (50% off on-demand pricing) and a tiered model strategy (cheap models for classification, capable models only for the hard cases), the OCR and LLM extraction cost across the full three billion pages runs approximately $9 to $10 million. Adding FHIR mapping, code validation, HealthLake ingestion, compute, and storage brings full-program cost to approximately $20 to $25 million -- a figure the pilot data in this recipe validates directly ($1.11 per chart scaled to 20 million charts equals roughly $22 million). Either figure is a 20 to 25 times reduction from the $495 million floor. The difference is not a marginal optimization. It is what makes the project feasible at all. 

This is the capstone recipe of Chapter 1 for a reason. Everything this chapter has taught comes together here: the vision model approach from Recipe 1.6, the document segmentation logic from Recipe 1.5, the model tiering concept introduced in Recipe 1.4, the async extraction patterns from Recipe 1.2. We are going to add two new concepts that only matter at scale: Bedrock batch inference, and prompt caching. We are going to show how LLMs transform the FHIR mapping problem from a rule-based maintenance nightmare into a language understanding task. And we are going to be honest about what this architecture actually costs in practice, and why the model tier routing is not optional.

Let's get into it.

---

## The Technology

### Why Three Decades of Clinical Documentation Is a Different Problem

Every other recipe in this chapter made an implicit assumption: the documents you are processing have a predictable structure. An insurance card always has a member ID field. A prior auth submission follows roughly the same template across payers. A lab requisition has the same fields in predictable locations.

Historical charts discard all of that. In a single 200-page chart, you might encounter:

**Dot-matrix and daisy-wheel printouts from the 1980s and early 1990s.** Characters are formed from dots rather than continuous strokes. Degraded printer ribbons produce faint, gray text. Modern OCR systems treat these as low-confidence and often misread them. The content is structured (SOAP format, lab tables) but the rendering quality is inconsistent in ways that character-level OCR handles poorly.

**Handwritten progress notes from different providers over different decades.** One physician writes tight, precise block capitals. Another scrawls near-illegible cursive. A third dictates and signs with a stylized signature that an OCR engine confidently reads as something unrelated. Recipe 1.6 covered the vision model approach for handwriting in detail. At chart migration scale, that approach needs to run on billions of pages.

**Multi-generation fax artifacts.** A document faxed once is degraded. A document that was received by fax, filed, re-scanned by a different vendor, and re-faxed to the scanning facility has been degraded three or four times. Each transmission adds noise. Lines become broken dashes. Thin characters lose their serifs. Table borders become discontinuous. OCR sees blobs and smears and assigns low confidence scores that correctly signal "something is wrong here" but don't tell you what the original said.

**Forms from dozens of sources.** The same concept (patient name) appears in different positions, different font sizes, different label text across three decades of form design. There is no universal schema. A keyword-based classifier trained on the forms you have seen will fail on the forms from the physician group you acquired six months ago.

**Mixed page orientations.** Landscape pages that should be rotated. Upside-down pages from documents grabbed from the scanner output tray in the wrong orientation. Partially visible pages from documents that slid under another sheet. These are not edge cases. In any bulk scanning operation, they are routine.

The technical term for all of this is content heterogeneity. And heterogeneity is precisely what rule-based systems handle worst and what language models handle best.

### Large Language Models for Document Understanding

The recipes earlier in this chapter showed LLMs handling document classification and clinical reasoning tasks on extracted text. Recipe 1.6 showed vision models reading handwritten images directly. Recipe 1.10 stacks both of those capabilities and adds a new one: using LLMs for FHIR resource generation from unstructured clinical content.

The core insight is that LLMs are good at the things that have been hard for rule-based systems, and rule-based systems remain good at the things where determinism matters. That division drives the architecture.

**Where LLMs win:**
- Classifying a page as a "progress note" even when it uses non-standard header formatting or no header at all
- Extracting clinical concepts from free-text narrative where the concepts are implicit rather than labeled
- Handling document boundaries when the boundary signals are weak or inconsistent
- Reading degraded or handwritten images using visual context that character-level OCR cannot access
- Generating structured FHIR resources from a mix of explicit and inferred clinical information

**Where rule-based systems stay right:**
- Exact medical code lookup (ICD-10, RxNorm, CVX). LLMs can hallucinate codes. Code validation against authoritative reference data is not optional.
- Financial arithmetic. Numeric processing should be deterministic.
- HIPAA authorization checks where the rule criteria are precisely defined

The chart migration pipeline in this recipe delegates the first list to Bedrock models and keeps the second list in deterministic code.

### Model Tiering: The Economics of Billion-Page Processing

This is the architectural concept that makes or breaks a chart migration program at scale. The principle is simple: not every page requires the same level of intelligence, and the price difference between model tiers is enormous.

Concrete numbers from Amazon Bedrock (March 2026, on-demand pricing):

| Model | Input ($/MTok) | Output ($/MTok) | Best For |
|-------|---------------|----------------|---------|
| Amazon Nova Lite | $0.06 | $0.24 | Classification, triage, simple routing |
| Amazon Nova Pro | $0.80 | $3.20 | Standard extraction, structured docs |
| Claude Haiku 4.5 | $1.00 | $5.00 | Fast extraction, moderate complexity |
| Claude Sonnet 4.6 | $3.00 | $15.00 | Complex reasoning, FHIR mapping, clinical narrative |
| Claude Opus 4.6 | $5.00 | $25.00 | Hardest cases, severely degraded docs |

Nova Lite versus Claude Opus for the same task: 83 times cheaper per input token. For a task like "classify this page as one of twelve document types," Nova Lite handles it fine. For a task like "read this severely degraded fax image of a handwritten 1987 discharge summary and extract all diagnoses," you may need Opus.

A typical chart page is roughly 500 to 1,000 input tokens. Here is what each tier costs per page (input plus output combined, approximate):

| Tier | Model | Cost per Page (on-demand) | Cost per Page (batch, 50% off) |
|------|-------|--------------------------|-------------------------------|
| Classification | Nova Lite | ~$0.0001 | ~$0.00005 |
| Standard extraction | Nova Pro | ~$0.0015 | ~$0.00075 |
| Complex extraction | Sonnet | ~$0.006 | ~$0.003 |
| Hardest cases | Opus | ~$0.015 | ~$0.0075 |

Now apply those tiers to three billion pages, assuming: 100% of pages go through Nova Lite classification, 70% through Nova Pro standard extraction, 25% through Sonnet complex extraction, and 5% through Opus for the hardest cases:

| Stage | Pages | Model | Batch Cost/Page | Subtotal |
|-------|-------|-------|-----------------|---------|
| Textract text detection (base OCR) | 3B (100%) | Textract DetectDocumentText | $0.0015 | $4.5M |
| Nova Lite classification | 3B (100%) | Nova Lite | $0.00005 | $150K |
| Nova Pro standard extraction | 2.1B (70%) | Nova Pro | $0.00075 | $1.6M |
| Sonnet complex extraction + FHIR | 750M (25%) | Sonnet | $0.003 | $2.25M |
| Opus hardest cases | 150M (5%) | Opus | $0.0075 | $1.1M |
| **Extraction subtotal** | 3B | Mixed | **~$0.003 blended** | **~$9.6M** | 

> **Extraction cost vs. full-program cost:** The table above covers the core transformation work: OCR and LLM extraction. Full-program cost adds FHIR mapping (Sonnet batch, ~$2.9M at scale), Comprehend Medical code validation (~$1.8M), HealthLake ingestion (~$362K), AWS Batch compute (~$1.1M), and S3 storage and transfer (~$640K). At 20 million charts, those additions bring the total to approximately $16 to $22 million. The pilot data in this recipe provides the most authoritative anchor: $1.11 per chart × 20 million charts equals approximately $22 million for the full program. Use the $9.6M extraction figure when comparing like-for-like against the legacy approach's extraction components. Use the $20 to $22 million figure in executive briefings. Both numbers represent the same 20 to 25 times improvement over the $495 million legacy floor.

Compare to the conventional Textract FORMS+TABLES plus Comprehend Medical approach:
- Textract FORMS+TABLES: $0.065/page × 3B = $195M
- Comprehend Medical (clinical entity extraction, ICD-10): ~$0.10/page average × 3B = $300M
- Old total: ~$495M, floor. Higher with human review.

The tiered LLM extraction pipeline is roughly 50 times cheaper for the same extraction coverage. Full-program cost at approximately $20 to $22 million is still 22 times cheaper than the $495 million legacy floor. That is not a precision claim: it is an order-of-magnitude illustration. Your actual numbers will depend on handwriting density, document quality, and how aggressively you tune the tier routing thresholds. But the direction is not ambiguous.

The conclusion: model tiering is not an optimization. It is the architecture that makes chart migration at scale a viable program.

### Batch Inference: How You Actually Process Billions of Pages

The Bedrock Converse API is a synchronous request-response interface. You send a message, you wait up to 30 seconds, you get an answer. For millions of daily API calls with a real-time SLA, that model works. For a chart migration running over six to twelve months with no real-time requirements, it is the expensive and slow path.

Bedrock Batch Inference is the right tool for this workload. It works like this:

1. Assemble a JSONL file in S3. Each line is a self-contained inference request: model ID, messages, system prompt, parameters.
2. Submit a batch inference job pointing to your input prefix. Bedrock processes the requests asynchronously across available capacity.
3. Bedrock writes result JSONL to your output S3 prefix, typically within 24 hours.
4. Your pipeline reads the results and continues processing.

The economics: batch inference runs at 50% of on-demand pricing. For the cost model above, this is already factored in. Every LLM call in this recipe runs through batch inference, not synchronous API calls. This is the single most important cost decision in the architecture.

The operational model: chart migration is not a real-time workload. Nobody is waiting at a desk for a 1988 progress note. You submit a batch job at the end of the day, and you have results the next morning. Across a six-month migration program running six to twelve hours of batch jobs per day, you process the full inventory on schedule.

The other advantage of batch inference: it is dramatically simpler to handle at quota limits. Synchronous calls have per-minute token limits. Batch jobs bypass real-time TPM limits entirely. At three billion pages, the throughput advantage is as important as the cost advantage.

### Prompt Caching: The Other Cost Lever

Every page that goes through Nova Lite classification uses the same system prompt. The same prompt that defines what "progress note," "lab result," and "operative report" mean. The same formatting instructions. The same JSON schema for the response. For three billion pages, you are sending that same system prompt three billion times.

Prompt caching stores the processed representation of your system prompt on Bedrock's servers, keyed to the content hash. Subsequent calls with the same system prompt pay a cache-hit rate (10% of the standard input price) instead of the full input price. Cache writes are priced at 125% to 200% of the standard rate (depending on TTL), but the reads make it up quickly. At scale, you are paying roughly 10% of the baseline cost for the system prompt on 90%+ of calls.

For a three billion page classification job with a 500-token system prompt:

- Without caching: 3B calls × 500 tokens × $0.06/MTok × 50% batch = $45K
- With caching (90% hit rate, 5-min TTL write cost): (10% × 1.25 + 90% × 0.1) × $45K ≈ $9.7K

A roughly $35,000 savings from a 90-second configuration change. At the scale of a full chart migration, prompt caching on the classification stage alone saves six figures. Enable it on every repeated prompt in the pipeline.

Prompt caching in the Bedrock Converse API is opt-in: you mark the content you want cached using a `cachePoint` parameter in your message structure. The cache TTL is five minutes by default, or one hour for explicit long-TTL caching. For batch inference jobs that run for hours against the same system prompt, the one-hour TTL is the right choice.

### Vision Models for Degraded Documents

Recipes 1.4 and 1.5 sent extracted text to LLMs. Recipe 1.6 introduced sending page images to vision models and showed why the image-first approach outperforms the text-first approach for handwriting. Those same advantages apply at chart migration scale, with one addition: degraded document types that are specific to historical charts.

Fax artifacts at third or fourth generation. Dot-matrix printouts from the late 1980s. Photocopied documents with increased grain and reduced contrast. These pages produce low Textract confidence scores, and those scores are an accurate signal: the text extraction is unreliable. Sending the low-confidence extracted text to a language model for FHIR mapping would propagate the error. Sending the page image to a vision model gives the model access to the visual context that OCR cannot recover: the overall page structure, the relative spacing of characters, the letterforms in the context of surrounding words.

The practical threshold: pages where Textract's average word confidence falls below 0.65 route to the vision path. Above 0.65, the extracted text is reliable enough to use as input. At the boundary, you use Textract's word-level confidence to identify the specific regions with low-quality OCR, and you send only those regions to the vision model for targeted re-extraction.

Vision model calls are significantly more expensive than text calls (images consume more tokens: roughly 1,000 to 2,000 tokens per page image). Reserve vision for the pages that actually need it. For a typical archive, 15 to 25% of pages have quality issues that justify the vision path. For archives with heavy fax content or significant historical degradation, that fraction climbs.

### FHIR Mapping: Where LLMs Transform the Problem

The goal of chart migration is not a pile of extracted text. It is structured clinical records that downstream systems can consume. FHIR R4 (Fast Healthcare Interoperability Resources, Release 4) is the target format: the current standard for healthcare data exchange, required by CMS Interoperability rules, supported by every major EHR, and the native format of Amazon HealthLake.

The mapping problem is where rule-based approaches genuinely fail. Raw OCR text might say "hypertension, essential" in a 1998 progress note. A FHIR `Condition` resource requires: a patient reference, a verification status, a code (ICD-10-CM or SNOMED CT), an onset or recorded date. Getting from the OCR string to the FHIR resource requires:

1. Understanding that "hypertension, essential" describes a chronic condition
2. Mapping it to ICD-10-CM I10 (Essential hypertension)
3. Inferring the recorded date from the document's header date, since no explicit date appears in the clinical text
4. Setting verification status to `unconfirmed` because this is an OCR-derived record, not a clinician-confirmed entry in the EHR

Step 1, 3, and 4 are contextual reasoning tasks. LLMs do them well. Step 2 (exact code lookup) is a task where LLMs hallucinate. The hybrid approach: Claude Sonnet for clinical understanding and resource structure, Comprehend Medical's InferICD10CM for ICD-10 code validation, and a CVX lookup table for immunization vaccine codes.

Every FHIR resource generated by this pipeline gets a provenance extension: which chart, which pages, which OCR confidence level, which model generated the extraction. This provenance is both a data quality signal for downstream consumers and a compliance record for audits.

One note on verification status that will save you a debugging session with HealthLake: the FHIR `condition-clinical` ValueSet has no `unknown` code. HealthLake validates this. Use `unconfirmed` for all migrated Condition resources. FHIR R4 does not require `clinicalStatus` at all; omit it rather than guess. This note is in the "Why This Isn't Production-Ready" section too, because teams will hit this and wonder why their FHIR imports are failing.

### The General Architecture Pattern

Chart migration has a two-tier structure.

The outer tier handles scale: ingesting millions of charts, distributing work across a processing fleet, tracking progress, managing the batch inference pipeline. This is a batch compute problem with a work queue at its center. Any batch compute framework handles this tier. What matters at this level is manifest management, worker concurrency, batch job submission, and state tracking.

The inner tier handles per-chart logic: pre-processing, OCR, classification, routing, extraction, FHIR mapping. The inner tier has been taught throughout Chapter 1. Each chart gets its own pipeline execution.

The critical addition at this scale: the inner tier no longer calls Bedrock APIs synchronously. It generates LLM requests, writes them to JSONL files, accumulates those files for batch inference jobs, and processes results asynchronously. The pipeline is now event-driven: Textract completion triggers classification request generation, batch job completion triggers extraction, extraction completion triggers FHIR mapping.

The four LLM model tiers of the pipeline (plus the Textract base layer that feeds them): 

```
[All pages]
     |
     v
[Base Layer: Textract]
OCR + word-level confidence scores + layout
     |
     v
[Tier 1: Nova Lite]
Page classification + quality triage
(prompt caching on system prompt)
(batch inference, ~$0.00005/page)
     |
     v
[Route by quality + content type]
     |          |              |
     v          v              v
[Tier 2:      [Vision        [Skip:
Nova Pro/     Path:           blank/
Haiku]        Sonnet/         cover
Standard      Opus            pages]
extraction]   vision]
(batch)       (degraded/
              handwritten)
     |          |
     v          v
[Tier 3: Sonnet]
FHIR resource mapping
(batch inference)
     |
     v
[Tier 4: Opus]
Hardest cases only
(degraded + complex clinical content)
(batch inference)
```

Nothing in this pattern is vendor-specific. The batch compute framework might be AWS Batch, GCP Cloud Batch, or a Kubernetes job queue. The OCR might be any cloud document extraction service. The LLM tiers might be any model with equivalent capability. The FHIR output might target any FHIR-compliant server. Teams on any cloud follow this same architectural pattern.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter01.10-architecture). The Python example is linked from there.

## The Honest Take

Chart migration is the longest recipe in this chapter because it is genuinely the hardest. Not in any single component: every piece has been covered somewhere earlier. It is hard because it is a systems integration problem at a scale that surfaces every assumption you made when you built the smaller pieces.

The model tier thresholds I gave you (Textract confidence of 0.45 for Opus, 0.65 for Sonnet) are reasonable starting points. They are not your thresholds. Your archive has a specific distribution of image quality, handwriting density, and document type. Run 1,000 charts through the pipeline before setting thresholds for the full program. Look at the cost breakdown and the quality scores. If 18% of pages are reaching Tier 4 (Opus) and your budget assumed 5%, your thresholds need adjustment. The tier distribution CloudWatch metric is your early warning system. Check it daily for the first two weeks.

The FHIR mapping step has a philosophical problem worth naming explicitly. You are converting information of uncertain provenance and uncertain accuracy into structured clinical records. A FHIR Condition resource with `verificationStatus = confirmed` in a clinical system means a physician confirmed this diagnosis. A FHIR Condition generated by a vision model reading a smeared third-generation fax of a 1989 handwritten progress note with a legibility score of 0.61 means something very different. That difference must be encoded: in the `verificationStatus` field (`unconfirmed` for everything), in the `note` field (provenance trail with chart ID, page range, OCR confidence, model tier), and in every downstream system that consumes this data. Do not silently promote migrated records to confirmed status. They are clinical context, not authoritative truth.

Batch inference throughput is excellent for most of the pipeline, but there are two places it breaks down in ways you need to plan for. First: batch jobs have a 24-hour SLA but occasionally take 30 to 36 hours during AWS capacity crunches. Build this slack into your operational calendar. Do not schedule milestone dates that assume 24-hour turnaround is guaranteed. Second: batch inference result JSONL files for large jobs (100,000+ requests) can be multi-gigabyte. The result-processing Lambda needs enough memory and a high enough timeout to handle these. If it runs out of memory or times out mid-processing, you have a partial result with no clean way to resume. Process results in streams rather than loading the entire file into memory. The Python companion shows this pattern.

The Textract quota increase is not optional, and the lead time is real. If you are reading this two weeks before your program launches without having filed a support case, file one today. If you file it today, you may still be waiting when you launch.

One last thing about cost. The blended cost estimate of $1.11 per chart in the sample output above is achievable with a well-tuned tier routing configuration and batch inference on everything. It assumes 68% of pages land in Tier 2 (Nova Pro). If your archive has dense handwriting, expect a higher Tier 3 and Tier 4 fraction, and higher per-chart costs. For charts with extremely high handwriting density (40%+ Tier 3/4), costs in the $3 to $5 range are realistic. That is still dramatically better than the $15 to $50 per chart that the A2I-heavy prior-generation approach produced. But validate your distribution on a pilot before committing to a program-level budget.

---

## Related Recipes

- **Recipe 1.2 (Patient Intake Form Digitization):** The async Textract pattern and SNS notification model used in Step 3. The base OCR architecture comes directly from Recipe 1.2.
- **Recipe 1.4 (Prior Authorization Document Processing):** Introduces Bedrock as the classification and reasoning layer, and the model tiering concept that this recipe extends to four tiers. Read Recipe 1.4 before implementing Steps 4 and 5.
- **Recipe 1.5 (Claims Attachment Processing):** Document boundary detection algorithm used in the segmentation stage, and LLM-based document classification patterns extended here to the full chart taxonomy. Recipe 1.5 is the primary reference for the boundary detection logic.
- **Recipe 1.6 (Handwritten Clinical Note Digitization):** The vision model approach (sending page images directly to multimodal LLMs) used in the Tier 3 and Tier 4 vision paths. Recipe 1.6 covers the confidence tiering and dual-path architecture in detail. This recipe applies the same approach at much larger scale.
- **Recipe 8.3 (Entity Resolution: Member Matching):** Post-migration, links chart records from multiple source systems to current member identities. Essential when charts span multiple acquired organizations or legacy systems with different member ID schemes.
- **Recipe 9.1 (Population Health Analytics):** Consumes the migrated longitudinal FHIR data for cohort analysis, HEDIS gap identification, and risk stratification. The FHIR resource completeness from this recipe directly affects downstream analytics quality.
- **Recipe 12.x (FHIR Integration Patterns):** Deep coverage of HealthLake data modeling, FHIR bulk import, and downstream FHIR API consumption for CMS Interoperability compliance.

---

## Tags

`document-intelligence` · `ocr` · `textract` · `bedrock` · `nova-lite` · `nova-pro` · `claude-haiku` · `claude-sonnet` · `claude-opus` · `vision-models` · `batch-inference` · `prompt-caching` · `comprehend-medical` · `healthlake` · `fhir` · `fhir-r4` · `chart-migration` · `batch-processing` · `aws-batch` · `step-functions` · `model-tiering` · `cost-optimization` · `document-segmentation` · `document-classification` · `s3-glacier` · `complex` · `phase-3` · `hipaa` · `interoperability` · `cms-interoperability-rule`

---

*← [Recipe 1.9: Medical Records Request Extraction](chapter01.09-medical-records-request-extraction) · [↑ Chapter 1 Index](chapter01-preface) · [→ Chapter 2 Preface](chapter02-preface)*
