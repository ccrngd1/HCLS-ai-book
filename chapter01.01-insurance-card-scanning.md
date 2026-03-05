# Recipe 1.1: Insurance Card Scanning ⭐

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.002 per card

---

## The Problem

Picture the front desk at a primary care clinic on a Monday morning. Six patients are already waiting. The person checking them in is asking each one to hand over their insurance card, typing the member ID by hand into the EHR, squinting at the group number, asking "is that a zero or an O?" The patient behind them is sighing. The phone is ringing.

This is not a rare scenario. It's the default state of healthcare administration in 2026.

Manual transcription of insurance card data is slow, error-prone, and genuinely expensive. A single transposed digit in a member ID cascades into a failed eligibility check, a denied claim, a billing department investigation, and eventually a frustrated patient on the phone asking why they got a bill. Multiply that across millions of check-ins and the operational cost is staggering. The American Medical Association has estimated that administrative waste in healthcare claims processing runs into the hundreds of billions annually. Not all of that is from typos, but a meaningful chunk is.

The information we need is right there on the card: member ID, group number, payer name, plan type, copays, pharmacy benefits. It's printed clearly (usually). Getting a computer to reliably read it has been a hard problem for longer than you'd expect, and the solutions have gotten genuinely good in the last few years.

Let's talk about how this works.

---

## The Technology: How Computers Read Cards

### OCR: The Basics

OCR stands for Optical Character Recognition. At its simplest, it's the process of taking an image of text and turning it into a machine-readable string. The concept goes back to the 1970s, but modern OCR is a completely different beast. Early systems were template-matching engines: they'd compare pixels against stored character shapes. Brittle, font-dependent, and deeply unhappy about anything that wasn't clean laser-printed text in a known typeface.

Modern OCR uses deep learning. A convolutional neural network processes the image, identifies character regions, and classifies each region into a character. The models are trained on millions of document images across languages, fonts, handwriting styles, and image qualities. The result is something that can read a crumpled Post-it note photographed at an angle under fluorescent lighting and get most of it right.

(Most of it. We'll come back to the failure modes.)

The output of an OCR pass is typically raw text: a sequence of detected characters with associated bounding box coordinates. Those coordinates tell you where on the image each character or word lives. This spatial information is more important than it might seem, and we'll use it heavily.

### The Key-Value Problem

Raw text from a card is not useful by itself. We don't want a blob of characters. We want a structured object:

```json
{
  "member_id": "XGP928471003",
  "group_number": "84023",
  "plan_type": "PPO",
  "copay_pcp": "$25"
}
```

Getting from raw OCR output to that structure is called **key-value extraction** (or key-value pair extraction, KVP). The idea is that on a form or card, some text is a label ("Member ID:") and some text is the corresponding value ("XGP928471003"). Associating the right value with the right key is the extraction problem.

Insurance cards are what you'd call semi-structured documents. They have consistent semantic fields (every card has a member ID, a group number, a payer name), but the layout varies wildly across payers. Blue Cross lays it out differently than Aetna. Aetna in 2019 looks different from Aetna in 2024. Regional co-ops look different from everyone. The label text also varies: "Member ID," "Mem ID," "Subscriber #," "ID Number" all mean the same field. There's no standard.

Key-value extraction systems handle this by reasoning about spatial proximity (the value usually appears near its label) and about textual patterns (if something looks like "MBR 928471003," there's a good chance "928471003" is the member ID). Modern systems combine layout-aware models that understand the 2D structure of the document, not just the linear text sequence.

### What Makes This Hard

Here's the honest list of things that will humble you when you first build this:

**Image quality.** A card photographed on a phone is not a scanned document. It might be slightly blurred, slightly rotated, taken in dim light, or shot at a 30-degree angle. Each of those degrades OCR accuracy. Glare on laminated cards is a particular nuisance. Some OCR systems include preprocessing (deskewing, contrast enhancement, noise reduction) to compensate, but there are limits.

**Card wear.** Physical cards get worn, scratched, cracked. Embossed cards (less common now, but still out there) have raised text that photographs strangely. If the member ID has a digit that's worn off, no amount of ML will reconstruct it correctly.

**Non-standard layouts.** You'll build a field mapping for the top 20 payers in your market and feel good about your coverage. Then a patient hands you a card from a small regional plan and none of your labels match. Your normalization logic needs to handle unknown fields gracefully, not crash.

**Handwriting.** Most insurance cards are printed, but the "copay" field is sometimes handwritten by a benefits coordinator. Handwriting recognition is dramatically harder than printed text recognition. The error rates are measurably worse. Plan for it.

**Fields that span multiple lines or sections.** "Blue Cross Blue Shield of North Carolina" might wrap. Copay tiers might be in a table. Front vs. back matters: member information typically lives on the front, pharmacy benefit fields (RX BIN, PCN, Group) on the back. If you only process one side, you're missing half the data.

The good news: for standard, well-photographed printed cards, modern systems achieve 95-99% field accuracy. That's good enough for most healthcare workflows when paired with a confidence score and a human review queue for the uncertain cases.

### The General Architecture Pattern

At a conceptual level, the pipeline looks like this:

```
[Capture] → [OCR / KVP Extraction] → [Normalize Fields] → [Store] → [Expose via API]
```

**Capture:** An image arrives in your system. This might be a mobile app where the patient photographs their own card, a flatbed scanner at a clinic, a fax-to-image conversion, or a camera peripheral at the front desk. The capture mechanism affects quality, and quality affects accuracy. If you control the capture UX, guide the user: "Hold the card flat, in good light, parallel to the camera."

**OCR / KVP Extraction:** The image is passed to an OCR engine or service. For key-value extraction from semi-structured documents, you want more than raw text: you want a system that understands the spatial relationships on the page and can return key-value pairs with confidence scores. There are open-source options (Tesseract for raw OCR, LayoutParser for layout-aware extraction), commercial libraries, and managed cloud services. The managed services have gotten very good and are often the right choice unless you have specific on-premises requirements or cost constraints at very high volume.

**Normalize Fields:** The extracted key-value pairs come back with whatever labels the card happened to use. You need a normalization layer that maps "Mem ID", "Member #", "Subscriber ID", and "ID Number" all to a canonical `member_id` field. This mapping is straightforward to build but requires ongoing maintenance as you encounter new payer layouts. It's not glamorous work. It's necessary work.

**Store:** Structured extraction results need to live somewhere durable and queryable. A document store, relational database, or key-value store all work here. The right choice depends on your access patterns: are you looking up by member ID? By scan date? By payer? In healthcare, you also need to think about encryption at rest and audit logging, because insurance cards contain PHI.

**Expose via API:** Downstream systems (EHRs, eligibility verification services, patient portals) need to consume the structured data. A REST or GraphQL API is the standard interface. Design it around the consuming system's needs: a point-of-care app needs a synchronous response in under 3 seconds; a batch eligibility verification job can tolerate asynchronous processing.

That's the whole concept. Capture, extract, normalize, store, serve. The rest is implementation detail.

---

## The AWS Implementation

Now let's get specific. Here's how I'd build this on AWS, and why each service is the right tool for each job.

### Why These Services

**Amazon Textract for OCR and KVP extraction.** Textract is AWS's managed document extraction service, and it's the obvious choice here because of one feature: the `AnalyzeDocument` API with `FORMS` feature type. Rather than just returning raw text (like basic OCR would), the FORMS feature analyzes the spatial layout of the document and returns explicit key-value pairs. It already understands the relationship between a label and its nearby value. You get back structured data, not a wall of characters you have to parse yourself. For single-page semi-structured documents like insurance cards, it's exactly the right abstraction.

**Amazon S3 for image storage.** You need a durable, encrypted place to receive card images before processing and to retain them afterward (for audit, reprocessing, and human review workflows). S3 with SSE-KMS encryption is the standard choice. The S3 event notification system also gives you a clean trigger for the processing pipeline: image lands in the bucket, Lambda fires automatically.

**AWS Lambda for orchestration.** The card extraction workflow is a short-lived, stateless sequence of API calls: get the image from S3, call Textract, parse the response, normalize the fields, write to DynamoDB. That's a textbook Lambda workload. No persistent servers to manage, automatic scaling with your request volume, and you pay only for execution time. For synchronous point-of-care use, you can put API Gateway in front of Lambda and get a direct REST endpoint.

**Amazon DynamoDB for result storage.** Extraction results are write-once (you scan a card, you store the result) with frequent point lookups by member ID or scan ID. DynamoDB's key-value access model fits perfectly. It's fully managed, scales transparently, and supports encryption at rest by default. For healthcare workloads, it's also on AWS's HIPAA eligible services list.

### Architecture Diagram

```mermaid
flowchart LR
    A[📱 Mobile App / Scanner] -->|Upload| B[S3 Bucket\ncards-inbox/]
    B -->|S3 Event| C[Lambda\ncard-extractor]
    C -->|AnalyzeDocument\nFORMS| D[Amazon Textract]
    D -->|Key-Value Pairs| C
    C -->|Normalize & Store| E[DynamoDB\ncard-extractions]
    C -->|Structured JSON| F[API Response\nto Caller]

    style B fill:#f9f,stroke:#333
    style D fill:#ff9,stroke:#333
    style E fill:#9ff,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon Textract, Amazon S3, AWS Lambda, Amazon DynamoDB |
| **IAM Permissions** | `textract:AnalyzeDocument`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem` |
| **BAA** | AWS BAA signed (required: insurance cards contain PHI) |
| **Encryption** | S3: SSE-KMS; DynamoDB: encryption at rest enabled (default); all API calls over TLS |
| **VPC** | Production: Lambda in VPC with VPC endpoints for S3, Textract, DynamoDB |
| **CloudTrail** | Enabled: log all Textract and S3 API calls for HIPAA audit trail |
| **Sample Data** | Synthetic insurance card images. CMS provides [sample Medicare cards](https://www.cms.gov/medicare/new-medicare-card) for layout reference. Never use real member cards in dev. |
| **Cost Estimate** | Textract AnalyzeDocument (FORMS): ~$1.50 per 1,000 pages. At one page per card, that's $0.0015/card. Lambda and DynamoDB costs are negligible at this scale. |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon Textract** | Extracts key-value pairs (FORMS) from card image |
| **Amazon S3** | Stores incoming card images; encrypted at rest with KMS |
| **AWS Lambda** | Orchestrates the extraction: triggers on S3, calls Textract, normalizes output |
| **Amazon DynamoDB** | Stores structured extraction results for downstream lookup |
| **AWS KMS** | Manages encryption keys for S3 and DynamoDB |
| **Amazon CloudWatch** | Logs, metrics, alarms for extraction failures and latency |

### Code

> **Reference implementations:** The following AWS sample repos demonstrate the patterns used in this recipe:
>
> - [`amazon-textract-code-samples`](https://github.com/aws-samples/amazon-textract-code-samples): General Textract code samples including FORMS extraction for key-value pair documents
> - [`amazon-textract-and-amazon-comprehend-medical-claims-example`](https://github.com/aws-samples/amazon-textract-and-amazon-comprehend-medical-claims-example): Healthcare-specific: extracting and validating medical claims data with Textract and Comprehend Medical
> - [`guidance-for-low-code-intelligent-document-processing-on-aws`](https://github.com/aws-solutions-library-samples/guidance-for-low-code-intelligent-document-processing-on-aws): Full IDP pipeline guidance covering ingestion, extraction, enrichment, and storage

#### Walkthrough

**Step 1: Textract call.** When a card image lands in the storage bucket, the system wakes up automatically and passes it to Amazon Textract for analysis. The key choice is requesting FORMS extraction rather than basic text recognition. FORMS mode is specifically designed for documents where labels and values are paired together ("Member ID: XGP928471003"). Basic text recognition would return a jumble of characters with no structure; FORMS mode returns an organized list of matched label-value pairs. Because insurance cards are single-page, results come back immediately (under 3 seconds in practice). Multi-page documents would require a different, background-processing approach. Skip this step or use basic OCR, and everything downstream breaks: you'd be trying to reconstruct structure from unstructured text, and accuracy would drop significantly.

```
FUNCTION extract_card(bucket, key):
    // Send the card image to Textract for intelligent analysis.
    // "bucket" is the name of the storage container; "key" is the filename/path of the image.
    // Together they tell Textract exactly which image to process.
    response = call Textract.AnalyzeDocument with:
        document  = S3 object at bucket/key   // locate the image in cloud storage
        features  = ["FORMS"]                 // use FORMS mode: extract label-value pairs,
                                              // not just raw text (this is the critical choice)
    RETURN response  // pass the full Textract response back to the next step
```

**Step 2: Parse key-value pairs.** Textract doesn't return a tidy spreadsheet. It returns a list of text building blocks, each one representing a detected region of the image, connected by links that indicate which label belongs with which value. This step walks through that structure and assembles the matched pairs. Think of it as sorting through a pile of index cards where some say "Member ID" and others say "XGP928471003", following the arrows that connect each label to its corresponding answer. The output is a clean map of label text to value text, each accompanied by a confidence score reflecting how clearly Textract was able to read it. Skip this step and you're left with raw building blocks that no downstream system can use.

```
FUNCTION parse_key_value_pairs(textract_response):
    // Pull out the full list of detected text regions ("blocks") from Textract's response.
    // Each block represents one piece of detected content: a word, a label, or a value.
    blocks    = textract_response.Blocks

    // Build a fast lookup index: block ID -> block data.
    // Textract connects blocks by referencing their IDs, so we need this index
    // to follow those links without scanning the entire list every time.
    block_map = build map of block.Id -> block for all blocks

    // This will hold our results: label text -> { value text, confidence score }.
    key_values = empty map

    FOR each block in blocks:
        // Only process blocks that are part of a key-value pair.
        // Textract labels each block as either a KEY (the label, e.g., "Member ID")
        // or a VALUE (the answer, e.g., "XGP928471003"). We start with the KEY side.
        IF block.BlockType == "KEY_VALUE_SET" AND block is a KEY entity:

            // Assemble the full label text by combining this block's child text pieces.
            // Example output: "Member ID" or "Group #"
            key_text    = get concatenated text from block's CHILD blocks in block_map

            // Follow the link from this KEY block to its paired VALUE block.
            // Textract stores this connection as a "VALUE" relationship on the KEY block.
            value_block = follow block's VALUE relationship to find the linked value block

            // Assemble the full value text from the value block's child text pieces.
            // Example output: "XGP928471003" or "84023"
            value_text  = get concatenated text from value_block's CHILD blocks in block_map

            // Record the lower of the two confidence scores (key vs. value).
            // If either side was hard to read, we want to know about it.
            // This score will drive the quality gate in Step 4.
            confidence  = minimum of (block.Confidence, value_block.Confidence)

            // Store the matched pair: label -> { value, confidence }
            key_values[key_text] = { value: value_text, confidence: confidence }

    // Return the complete set of matched pairs ready for normalization.
    RETURN key_values
```

**Step 3: Normalize field names.** Here's the operational reality of insurance cards: every payer uses different label text for the same fields. "Member ID," "Mem ID," "Subscriber #," and "ID Number" all mean the same thing. Without this normalization step, the system would treat each variant as a different field, and downstream systems expecting a standardized `member_id` field would come up empty. This step translates whatever labels Textract found on a given card into a consistent, predictable set of field names, regardless of which payer issued the card. The mapping table (FIELD_MAP) is built from real-world payer layouts and requires ongoing maintenance as new layouts are encountered. Treat it as a living configuration, not a one-time build. Skip this step and you'll have accurate text extraction with no reliable way to put that data to use.

```json
{
  "member_id":        ["member id", "mem id", "member #", "subscriber id", "id number", "member number"],
  "group_number":     ["group #", "group number", "group", "grp #", "grp"],
  "payer_name":       ["insurance company", "plan name", "payer", "carrier"],
  "plan_type":        ["plan type", "plan", "product"],
  "copay_pcp":        ["pcp copay", "office visit", "copay", "pcp"],
  "copay_specialist": ["specialist copay", "specialist"],
  "copay_er":         ["er copay", "emergency room", "er"],
  "rx_bin":           ["rx bin", "bin"],
  "rx_pcn":           ["rx pcn", "pcn"],
  "rx_group":         ["rx group", "rx grp"]
}
```

```
FUNCTION normalize_fields(raw_kv):
    // Start with an empty result set. We'll populate it with standardized field names.
    normalized = empty map

    // Walk through each canonical (standard) field name and its list of known label variants.
    // "canonical" means the consistent name we always use, regardless of what's on the card.
    FOR each canonical_name, variants in FIELD_MAP:

        // For each standard field, check every label Textract found on this card.
        FOR each raw_key, raw_val in raw_kv:

            // Normalize to lowercase with no extra whitespace before comparing.
            // This handles capitalization differences ("MEMBER ID" vs. "Member ID").
            IF lowercase(trim(raw_key)) is in variants:

                // Match found. Store this field under its standard name.
                // trim() removes any stray whitespace Textract may have included.
                normalized[canonical_name] = {
                    value:      trim(raw_val.value),  // the extracted text value, cleaned up
                    confidence: raw_val.confidence    // how confident Textract was (0-100)
                }
                BREAK   // found a match for this field; no need to keep checking variants

    // Return the normalized map: consistent field names ready for the quality gate.
    RETURN normalized
```

**Step 4: Confidence gating.** Not every field Textract reads is equally reliable. Glare across the member ID, a worn digit, a card photographed at a steep angle: all of these reduce confidence in the extracted value. This step applies a quality gate: any field below 90% confidence is held back from automatic processing and routed to a human for verification. This matters both for accuracy and for compliance. A wrong member ID on a claim triggers denied reimbursement, billing investigations, and patient frustration. The cost of a human taking five seconds to confirm a borderline value is far lower than the cost of a wrong value silently becoming a fact in your systems of record. The full human review queue that these flagged fields feed into is built in Recipe 1.6.

```
CONFIDENCE_THRESHOLD = 90.0  // fields below 90% confidence go to human review, not directly to the database

FUNCTION flag_low_confidence(fields):
    // Two buckets: fields we're confident about, and fields that need a human eye.
    clean   = empty map   // high-confidence fields, safe to use immediately
    flagged = empty list  // low-confidence fields, held for review

    FOR each field, data in fields:
        IF data.confidence >= CONFIDENCE_THRESHOLD:
            // Confidence is high enough. Accept this value for downstream use.
            clean[field] = data.value

        ELSE:
            // Confidence is too low to trust automatically.
            // Don't discard the value: record it for a reviewer to confirm or correct.
            // Never let a low-confidence extraction silently become a fact in your database.
            append to flagged: {
                field:           field,            // which field is uncertain (e.g., "member_id")
                extracted_value: data.value,       // what Textract thinks it read (e.g., "XGP92847l003")
                confidence:      data.confidence   // how confident it was (e.g., 78.4%)
            }

    // Return both sets so the caller knows what's ready to use and what needs review.
    RETURN clean, flagged
```

**Step 5: Store results.** The final step writes everything to the database: the high-confidence fields ready for immediate use, the flagged fields awaiting human verification, and a timestamp for the audit trail. Every record includes a `needs_review` flag so downstream systems and review queues can instantly identify cards that require attention. In healthcare, every system touching PHI needs an auditable record: what was processed, when, and what came out. This step creates that record. It also enables reprocessing: if Textract releases a new model version with improved accuracy, you can identify historical scans with low-confidence fields and run them through again.

```
FUNCTION store_result(image_key, fields, flagged):
    // Write a complete, permanent record of this extraction to the database.
    // This record is the authoritative output of the pipeline for this card scan.
    write record to database table "card-extractions":
        image_key            = image_key                          // which image was processed
                                                                  // (links back to the original file in S3)
        extraction_timestamp = current UTC timestamp (ISO 8601)   // when this happened, for audit and compliance reporting
        fields               = fields                             // all high-confidence field values, ready to use
        flagged_fields       = flagged                            // fields held for human review, with their extracted values
        needs_review         = (length of flagged > 0)           // true if ANY field needs review;
                                                                  // downstream systems check this flag to route cards appropriately
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter01.01-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

### Expected Results

**Sample output for a typical BCBS card:**

```json
{
  "image_key": "cards-inbox/2026/03/01/scan-00482.jpg",
  "extraction_timestamp": "2026-03-01T14:22:08Z",
  "fields": {
    "member_id": "XGP928471003",
    "group_number": "84023",
    "payer_name": "Blue Cross Blue Shield of Kentucky",
    "plan_type": "PPO",
    "copay_pcp": "$25",
    "copay_specialist": "$50",
    "copay_er": "$150"
  },
  "flagged_fields": [],
  "needs_review": false
}
```

**Performance benchmarks:**

| Metric | Typical Value |
|--------|---------------|
| End-to-end latency | 1.5–3 seconds |
| Field extraction accuracy | 95–99% for printed cards |
| Confidence score (clean cards) | 95–99.5% per field |
| Cost per card | ~$0.002 (Textract + Lambda + DynamoDB) |
| Throughput | ~50 cards/second (Lambda concurrency limited) |

**Where it struggles:** Cards photographed at steep angles, poor lighting, or heavy glare. Cracked or worn cards with damaged print. Cards from smaller regional payers with non-standard layouts (your FIELD_MAP will need expansion). And handwritten fields, especially copays added after the card was printed.

---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. Deploying this to a clinic requires addressing several gaps that are intentionally outside the scope of a cookbook recipe. These are the ones that will bite you:

**Dead Letter Queue.** Lambda invocations from S3 events are asynchronous. If the function fails (Textract outage, DynamoDB unavailable, uncaught exception), the event retries up to three times and then silently disappears. In a healthcare intake pipeline, a silently lost document means a patient record gap with no visible signal. Configure an SQS dead letter queue on each Lambda and set a CloudWatch alarm on the queue depth.

**CloudWatch Logs VPC endpoint.** The prerequisites recommend VPC endpoints for S3, Textract, and DynamoDB. Missing from that list: `com.amazonaws.region.logs`. A Lambda running in a private subnet with no internet gateway and no CloudWatch Logs endpoint cannot write any log output. Your audit trail, error visibility, and debugging information all silently vanish. Add it.

**IAM resource scoping.** The prerequisites list the right API actions, but most readers will scope them to `*` (all resources). Don't. Restrict `s3:GetObject` to `arn:aws:s3:::cards-inbox/*`, `dynamodb:PutItem` to your specific table ARN, and `kms:Decrypt` to your specific key ARN. Least privilege means least privilege, not "least actions."

**Idempotency.** S3 delivers event notifications at least once, not exactly once. Your Lambda can be invoked twice for the same card image. Without a conditional DynamoDB write (check whether a record with the same `image_key` already exists before writing), you'll create duplicate extraction records or silently overwrite existing ones.

---

## The Honest Take

This recipe is genuinely easy to get to 90% accuracy on. The first few hundred cards will look great. Then you'll start seeing the long tail: the Medicaid card with a layout you've never encountered, the card where the member ID is split across two lines, the card photographed in a car with the window casting a glare stripe directly across the group number.

The field normalization map is the thing that requires the most ongoing attention. Build tooling to log unrecognized keys (keys that didn't match any canonical field) so you can identify new payer layouts as they appear. Treat it as a living config, not a one-time build.

The confidence threshold is where you make your reliability tradeoff. 90% sounds reasonable until you're processing 10,000 cards a day and 1% of them are in your manual review queue: that's 100 reviews a day. Calibrate based on your actual cost-of-error. A wrong member ID on a claim costs more than a human taking five seconds to confirm a value.

The part that surprised me: front-of-card processing gets you maybe 70% of what you need. The pharmacy benefit fields (RX BIN, PCN, Group) almost always live on the back. If your use case touches medication workflows at all, you need both sides.

---

## Variations and Extensions

**Real-time mobile integration.** Instead of S3 trigger to Lambda, expose the extraction via API Gateway for synchronous point-of-care use. Add an image quality check (blur detection, rotation correction) before calling Textract to improve accuracy on mobile camera captures. The quality check is worth the extra latency.

**Front and back extraction.** Accept two images, extract both, and merge into a single unified record. The Rx BIN/PCN/Group fields are almost always on the back. A simple merge strategy: canonical fields from the front win on conflict; pharmacy fields are populated from the back.

**Auto-eligibility verification.** Pipe the extracted member ID and group number directly into a 270/271 eligibility transaction (see Recipe 8.1: Insurance Eligibility Matching). Close the loop from card scan to verified coverage in a single workflow.

---

## Related Recipes

- **Recipe 1.2 (Patient Intake Form Digitization):** Extends this single-image pattern to multi-section forms with tables and checkboxes
- **Recipe 1.4 (Prior Auth Document Processing):** Uses the same Textract FORMS foundation but on multi-page documents
- **Recipe 1.6 (Handwritten Clinical Note Digitization):** Builds the human review queue that confidence flagging in this recipe feeds into
- **Recipe 8.1 (Insurance Eligibility Matching):** Consumes the structured output from this recipe to verify coverage in real time

---

## Additional Resources

**AWS Documentation:**
- [Amazon Textract AnalyzeDocument API Reference](https://docs.aws.amazon.com/textract/latest/dg/API_AnalyzeDocument.html)
- [Amazon Textract FORMS Feature Type](https://docs.aws.amazon.com/textract/latest/dg/how-it-works-kvp.html)
- [Amazon Textract Pricing](https://aws.amazon.com/textract/pricing/)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)
- [Architecting for HIPAA on AWS (Whitepaper)](https://docs.aws.amazon.com/whitepapers/latest/architecting-hipaa-security-and-compliance-on-aws/welcome.html)

**AWS Sample Repos:**
- [`amazon-textract-code-samples`](https://github.com/aws-samples/amazon-textract-code-samples): General Textract examples including FORMS extraction for key-value pair documents
- [`amazon-textract-textractor`](https://github.com/aws-samples/amazon-textract-textractor): Python SDK wrapper for Textract that simplifies calling, parsing, and visualizing results (installable via pip)
- [`amazon-textract-and-amazon-comprehend-medical-claims-example`](https://github.com/aws-samples/amazon-textract-and-amazon-comprehend-medical-claims-example): Healthcare-specific: extracting and validating medical claims data with Textract and Comprehend Medical

**AWS Solutions and Blogs:**
- [Enhanced Document Understanding on AWS](https://aws.amazon.com/solutions/implementations/enhanced-document-understanding-on-aws): Deployable solution for document classification, extraction, and search
- [Automating Paper-to-Electronic Healthcare Claims Processing with AWS](https://aws.amazon.com/blogs/storage/automating-paper-to-electronic-healthcare-claims-processing-with-aws): End-to-end architecture for digitizing paper healthcare claims

---

## Estimated Implementation Time

| Scope | Time |
|-------|------|
| **Basic** (Textract + Lambda + hardcoded field map) | 2–4 hours |
| **Production-ready** (VPC, KMS, CloudTrail, error handling, monitoring) | 1–2 days |
| **With variations** (mobile API, front+back, eligibility integration) | 3–5 days |

---

## Tags

`document-intelligence` · `ocr` · `textract` · `forms` · `insurance-card` · `point-of-care` · `simple` · `mvp` · `lambda` · `s3` · `dynamodb` · `hipaa`

---

*← [Chapter 1 Index](chapter01-index) · [Next: Recipe 1.2 - Patient Intake Form Digitization →](chapter01.02-patient-intake-digitization)*
