# Recipe 8.2 Architecture and Implementation: Patient Sentiment Analysis

*Companion to [Recipe 8.2: Patient Sentiment Analysis](chapter08.02-patient-sentiment-analysis). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## Why These Services

**Amazon Comprehend for sentiment and entity detection.** Comprehend is AWS's managed NLP service. Its sentiment analysis API classifies text as positive, negative, neutral, or mixed, with confidence scores for each. Crucially for healthcare, it also has a medical variant (Comprehend Medical) that detects PHI entities, which you need for the preprocessing step. You don't need to train, host, or scale any models. The tradeoff: Comprehend's built-in sentiment is document-level and uses generic categories. For aspect-level analysis, you'll need the custom classification feature or a separate model.

**Amazon Comprehend Custom Classification for aspect detection.** Comprehend lets you train custom classifiers on your labeled data. Train one model on your aspect taxonomy (wait_time, provider_communication, billing, etc.) and a second for fine-grained sentiment if the built-in model doesn't capture healthcare-specific nuance well enough. Custom models run on the same managed infrastructure, so you still don't manage servers.

**Amazon S3 for feedback storage.** All incoming feedback lands in S3 as the durable data lake. Organized by source, date, and processing stage. S3 event notifications trigger the analysis pipeline automatically as new feedback arrives.

**AWS Lambda for orchestration.** Each step in the pipeline (PHI detection, sentiment analysis, aspect extraction, result storage) is a short-lived, stateless function. Lambda handles the glue logic: calling Comprehend APIs, parsing responses, routing results. For batch processing of historical feedback, Step Functions coordinates the workflow.

**Amazon DynamoDB for results.** Analyzed results (sentiment scores, aspects, themes, metadata) are stored in DynamoDB for fast lookup by survey ID, date range, or department. The table design supports the access patterns dashboards need: "show me all negative-sentiment feedback for cardiology in the last 30 days."

**Amazon QuickSight for visualization.** QuickSight connects to DynamoDB (via Athena or direct) to power patient experience dashboards. Trend charts, department comparisons, theme word clouds, and drill-down to individual comments. The patient experience team lives in these dashboards.

**Amazon EventBridge for alerting.** When aggregation detects a significant negative trend (configurable thresholds), EventBridge routes an alert to the appropriate team via SNS, Slack, or PagerDuty. Early warning, not just retrospective reporting.

## Architecture Diagram

```mermaid
flowchart LR
    A[📋 Survey Platform\nPatient Portal\nCall Transcripts] -->|Ingest| B[S3 Bucket\nfeedback-raw/]
    B -->|S3 Event| C[Lambda\nphi-detection]
    C -->|Comprehend Medical\nDetectPHI| D[S3\nfeedback-redacted/]
    D -->|S3 Event| E[Lambda\nsentiment-analyzer]
    E -->|Comprehend\nDetectSentiment| F[Lambda\naspect-extractor]
    F -->|Custom Classifier| G[DynamoDB\nsentiment-results]
    G -->|Query| H[QuickSight\nDashboards]
    G -->|Trend Detection| I[EventBridge\nAlerts]

    style B fill:#f9f,stroke:#333
    style D fill:#f9f,stroke:#333
    style G fill:#9ff,stroke:#333
    style H fill:#ff9,stroke:#333
```

## Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon Comprehend, Comprehend Medical, S3, Lambda, DynamoDB, QuickSight, EventBridge, SNS |
| **IAM Permissions** | Each Lambda function needs its own execution role scoped to minimum resources. PHI-detection Lambda: `comprehendmedical:DetectPHI`, `s3:GetObject` on `feedback-raw/*`, `s3:PutObject` on `feedback-redacted/*`. Sentiment Lambda: `comprehend:DetectSentiment`, `s3:GetObject` on `feedback-redacted/*`. Aspect Lambda: `comprehend:ClassifyDocument`, `dynamodb:PutItem` on `sentiment-results` table ARN, `events:PutEvents`. The PHI boundary between raw and redacted buckets is the core security control; IAM must enforce it. |
| **BAA** | Required: patient feedback often contains PHI (names, dates, diagnoses mentioned in free text) |
| **Encryption** | S3: SSE-KMS with customer-managed key; DynamoDB: encryption at rest (default, verify enabled); Lambda logs: KMS-encrypted CloudWatch log groups; all API calls over TLS |
| **VPC** | Production: Lambda in VPC with VPC endpoints for S3 (gateway), DynamoDB (gateway), Comprehend (interface), Comprehend Medical (interface, separate from Comprehend), and CloudWatch Logs (interface). Note: EventBridge does not have a VPC endpoint; the alerting Lambda requires NAT Gateway connectivity or should write alert records to DynamoDB for a non-VPC Lambda to forward. |
| **CloudTrail** | Enabled: log all Comprehend and S3 API calls for audit trail |
| **Data Retention** | Configure S3 lifecycle rules on `feedback-raw/` (contains PHI): transition to Glacier after 30 days, expire per your organization's retention policy (typically 6-7 years for non-clinical operational data, verify with compliance). Enable S3 Object Lock if regulatory hold is required. The `feedback-redacted/` bucket has lower sensitivity but should still have a defined lifecycle. |
| **Training Data** | Custom aspect classifier requires minimum 200 labeled examples per aspect category (10 categories = 2,000+ examples). Format: CSV with text and category columns per Comprehend Custom Classification requirements. Training time: 30-60 minutes. Budget 2-4 weeks for initial labeling by patient experience staff who understand both the aspect taxonomy and clinical context. |
| **Error Handling** | Configure SQS dead-letter queues on each Lambda function. Failed items route to DLQ for investigation and replay. CloudWatch alarm on DLQ message count > 0 alerts operations. Systematic failures (new feedback format causing parse errors) can silently drop thousands of items, creating misleading aggregate trends. |
| **Sample Data** | Synthetic patient feedback. CMS publishes [HCAHPS survey results](https://data.cms.gov/provider-data/topics/hospitals/overall-hospital-quality-star-rating) (aggregate only). Generate synthetic verbatim comments for development. Never use real patient feedback in non-production environments without proper de-identification. |
| **Cost Estimate** | Comprehend DetectSentiment: $0.0001 per unit (100 chars). For average 500-char feedback: ~$0.0005/item. PHI detection adds ~$0.01/item. Custom classification: $0.0005/item. Custom classification endpoint hosting: $0.50/hour per inference unit ($360/month minimum, always-on). At 50,000 items/month: ~$910/month total (including endpoint). For batch processing (non-real-time), use Comprehend async classification jobs instead of a real-time endpoint to eliminate hosting cost. |

## Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon Comprehend** | Sentiment detection (built-in) and custom aspect classification |
| **Amazon Comprehend Medical** | PHI entity detection for preprocessing/redaction |
| **Amazon S3** | Raw and redacted feedback storage; organized by source and date |
| **AWS Lambda** | Orchestration: PHI detection, sentiment analysis, aspect extraction, result assembly |
| **Amazon DynamoDB** | Stores analyzed results for dashboard queries and trend detection |
| **Amazon QuickSight** | Patient experience dashboards and visualizations |
| **Amazon EventBridge** | Routes trend alerts to appropriate teams |
| **AWS KMS** | Encryption key management for all PHI-containing resources |
| **Amazon CloudWatch** | Metrics, logs, and alarms for pipeline health |
| **Amazon SQS** | Dead-letter queues for failed processing items |

## Pseudocode Walkthrough

> **Reference implementations:** The following AWS sample repos demonstrate patterns used in this recipe:
>
> - [`amazon-comprehend-examples`](https://github.com/aws-samples/amazon-comprehend-examples): General Comprehend examples including sentiment analysis, custom classification, and entity detection
> - [`amazon-comprehend-medical-fhir-integration`](https://github.com/aws-samples/amazon-comprehend-medical-fhir-integration): Healthcare-specific: integrating Comprehend Medical with FHIR for clinical NLP pipelines

**Step 1: PHI detection and redaction.** Before any analysis, the system scans incoming feedback for protected health information. Patient comments routinely mention provider names, specific diagnoses, medication names, and dates of service. The PHI detection pass identifies these entities and either redacts them (replaces with placeholder tokens like `[PROVIDER_NAME]`) or tags them for downstream handling. This step is non-negotiable for any pipeline processing patient-generated text. The redacted version is what flows to sentiment analysis, so your sentiment models never need access to identifiable information. Skip this step and you're running PHI through analytics services without proper safeguards.

```pseudocode
FUNCTION detect_and_redact_phi(feedback_text):
    // Call the medical NLP service to identify any PHI in the text.
    // PHI includes: names, dates, phone numbers, medical record numbers,
    // and any other individually identifiable health information.
    phi_entities = call ComprehendMedical.DetectPHI with:
        text = feedback_text

    // Build the redacted version by replacing each detected entity with a placeholder.
    // We preserve the entity type so downstream analysis knows a provider was mentioned
    // even though we've removed the actual name.
    redacted_text = feedback_text
    FOR each entity in phi_entities (sorted by offset, descending):
        // Replace from back to front so character offsets remain valid.
        // Example: "Dr. Smith was kind" becomes "[PROVIDER_NAME] was kind"
        redacted_text = replace characters at entity.BeginOffset..entity.EndOffset
                        with "[" + entity.Type + "]"

    RETURN {
        redacted_text: redacted_text,      // safe for downstream analytics
        phi_detected: length(phi_entities) > 0,  // flag for audit
        entity_count: length(phi_entities)
    }
```

**Step 2: Sentiment analysis.** The redacted text goes to the sentiment analysis service. This returns an overall sentiment label (POSITIVE, NEGATIVE, NEUTRAL, MIXED) along with confidence scores for each category. The confidence distribution is often more informative than the top label. A comment scored 60% negative and 35% positive is qualitatively different from one scored 95% negative. The MIXED category is especially important in healthcare feedback, where patients commonly express both gratitude and frustration in the same response. Store the full score distribution, not just the winning label.

```pseudocode
FUNCTION analyze_sentiment(redacted_text):
    // Call the sentiment detection service.
    // Input must be under 5,000 bytes (UTF-8). Patient feedback typically fits easily.
    // For longer texts (call transcripts), split into paragraphs and analyze each.
    response = call Comprehend.DetectSentiment with:
        text          = redacted_text
        language_code = "en"    // detect language first for multilingual populations

    // Extract the full score distribution, not just the top label.
    // A 55% negative / 40% positive split tells a different story than 95% negative.
    RETURN {
        sentiment: response.Sentiment,           // "POSITIVE", "NEGATIVE", "NEUTRAL", "MIXED"
        scores: {
            positive: response.SentimentScore.Positive,
            negative: response.SentimentScore.Negative,
            neutral: response.SentimentScore.Neutral,
            mixed: response.SentimentScore.Mixed
        },
        confidence: maximum of all four scores    // how decisive the classification is
    }
```

**Step 3: Aspect extraction.** This is where generic sentiment becomes actionable intelligence. The system classifies which aspect(s) of the healthcare experience are mentioned in each piece of feedback. A custom classifier trained on your labeled data maps text segments to your aspect taxonomy. For each detected aspect, the system also captures the sentiment directed specifically at that aspect. One comment might yield: `{wait_time: NEGATIVE, provider_quality: POSITIVE, facility: NEUTRAL}`. That's three distinct operational signals from one piece of text.

```pseudocode
// The aspect taxonomy reflects what patient experience teams actually care about.
// This should be configured, not hardcoded. Add/remove aspects as your organization evolves.
ASPECT_TAXONOMY = [
    "wait_time",              // scheduling delays, in-office wait
    "provider_communication", // bedside manner, explanations, listening
    "staff_interaction",      // nursing, front desk, technicians
    "facility_environment",   // cleanliness, comfort, noise, parking
    "billing_insurance",      // charges, statements, coverage confusion
    "care_coordination",      // referrals, follow-up, transitions
    "pain_management",        // pain control, medication responsiveness
    "discharge_process",      // instructions, timing, readiness
    "access_convenience",     // hours, location, telehealth availability
    "overall_experience"      // general impressions not tied to specific aspect
]

FUNCTION extract_aspects(redacted_text, document_sentiment):
    // Split text into sentences for finer-grained analysis.
    // A single feedback item often covers multiple aspects across sentences.
    // NOTE: Use a proper sentence tokenizer (like spaCy's sentencizer or NLTK's
    // Punkt) that handles abbreviations (Dr., dept., etc.). Simple period-splitting
    // will break on these. For very short feedback (< 2 sentences), classify the
    // entire text as one unit rather than splitting.
    sentences = split_into_sentences(redacted_text)

    aspect_results = empty list

    FOR each sentence in sentences:
        // Classify which aspect this sentence is about.
        // Uses a custom classifier trained on labeled healthcare feedback.
        aspect_response = call Comprehend.ClassifyDocument with:
            text             = sentence
            endpoint_arn     = ASPECT_CLASSIFIER_ENDPOINT

        // Get the top aspect prediction with confidence.
        top_aspect     = aspect_response.Classes[0].Name
        aspect_conf    = aspect_response.Classes[0].Score

        // Only accept aspect classification if confidence is above threshold.
        // Low-confidence aspect assignments add noise to dashboards.
        IF aspect_conf >= 0.6:
            // Get sentence-level sentiment for this specific aspect mention.
            sentence_sentiment = call Comprehend.DetectSentiment with:
                text          = sentence
                language_code = "en"

            append to aspect_results: {
                aspect: top_aspect,
                sentiment: sentence_sentiment.Sentiment,
                confidence: aspect_conf,
                text: sentence   // keep the source text for drill-down
            }

    RETURN aspect_results
```

**Step 4: Result assembly and storage.** The final step combines all analysis outputs into a single record and writes it to the database. Each record links back to the source feedback item and includes the full analysis: document-level sentiment, aspect-level sentiments, metadata about the source channel and department, and processing timestamps. The table design supports the queries that dashboards need: filter by date range, department, sentiment, or aspect. The `needs_attention` flag routes significantly negative items to immediate human review rather than waiting for monthly reports.

```pseudocode
FUNCTION store_analysis_result(source_metadata, sentiment, aspects):
    // Determine if this item needs immediate human attention.
    // Threshold: overall negative sentiment with high confidence,
    // or any critical aspect (safety, pain) with negative sentiment.
    needs_attention = (
        sentiment.sentiment == "NEGATIVE" AND sentiment.confidence >= 0.85
    ) OR any aspect in aspects where (
        aspect.aspect in ["pain_management", "care_coordination"]
        AND aspect.sentiment == "NEGATIVE"
    )

    // Write the complete analysis record.
    write record to database table "sentiment-results":
        feedback_id       = source_metadata.id                    // links to original feedback
        source_channel    = source_metadata.channel               // "survey", "portal", "review", "call"
        department        = source_metadata.department            // for departmental filtering
        facility          = source_metadata.facility              // for multi-site systems
        analysis_date     = current UTC timestamp (ISO 8601)
        document_sentiment = sentiment                            // full score distribution
        aspects           = aspects                               // list of aspect-sentiment pairs
        needs_attention   = needs_attention                       // routes to review queue
        feedback_date     = source_metadata.submitted_date        // when patient submitted

    // If needs_attention, also emit an event for real-time alerting.
    // IMPORTANT: Do not include feedback text in the event payload. The alert
    // routes to external systems (Slack, PagerDuty) that may not be BAA-covered.
    // Include only the feedback_id so reviewers can look up the full text through
    // the authorized dashboard.
    IF needs_attention:
        emit event to EventBridge:
            source     = "patient-sentiment-pipeline"
            detail_type = "NegativeSentimentAlert"
            detail     = { feedback_id, department, facility, top_negative_aspect }
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter08.02-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

## Expected Results

**Sample output for a typical patient survey comment:**

Input: "The doctor was very thorough and explained everything clearly. But I waited 45 minutes past my appointment time and the waiting room was freezing. Billing sent me a surprise charge three weeks later."

```json
{
  "feedback_id": "survey-2026-03-15-00847",
  "source_channel": "post_visit_survey",
  "department": "internal_medicine",
  "facility": "main_campus",
  "analysis_date": "2026-03-16T02:15:33Z",
  "document_sentiment": {
    "sentiment": "MIXED",
    "scores": {
      "positive": 0.32,
      "negative": 0.41,
      "neutral": 0.08,
      "mixed": 0.19
    },
    "confidence": 0.41
  },
  "aspects": [
    {
      "aspect": "provider_communication",
      "sentiment": "POSITIVE",
      "confidence": 0.91,
      "text": "The doctor was very thorough and explained everything clearly."
    },
    {
      "aspect": "wait_time",
      "sentiment": "NEGATIVE",
      "confidence": 0.88,
      "text": "But I waited 45 minutes past my appointment time."
    },
    {
      "aspect": "facility_environment",
      "sentiment": "NEGATIVE",
      "confidence": 0.72,
      "text": "The waiting room was freezing."
    },
    {
      "aspect": "billing_insurance",
      "sentiment": "NEGATIVE",
      "confidence": 0.85,
      "text": "Billing sent me a surprise charge three weeks later."
    }
  ],
  "needs_attention": false,
  "feedback_date": "2026-03-15T14:30:00Z"
}
```

**Performance benchmarks:**

| Metric | Typical Value |
|--------|---------------|
| End-to-end latency | 2-4 seconds per feedback item |
| Document sentiment accuracy | 85-92% (against human labels) |
| Aspect classification accuracy | 78-88% (depends on training data quality) |
| PHI detection recall | 95-99% (high recall critical here) |
| Cost per feedback item | ~$0.01 (PHI detection + sentiment + aspect classification) |
| Throughput (batch) | ~200 items/minute per Lambda instance |

**Where it struggles:** Very short feedback ("fine", "ok", "terrible") provides too little context for aspect extraction. Sarcasm is reliably misclassified ("Oh sure, waiting two hours was GREAT"). Feedback in languages other than English requires separate model endpoints or translation, adding latency and cost. Mixed-sentiment comments where the positive/negative balance is close to 50/50 produce low-confidence labels that aren't actionable without human review.

---

<!-- TODO (TechWriter): RECIPE-GUIDE requires a "Why This Isn't Production-Ready" section between Expected Results and Variations. Add production gap analysis here. -->

## Variations and Extensions

**Trend alerting with statistical significance.** Instead of alerting on any negative feedback, implement a rolling baseline per department/aspect and alert only when current sentiment deviates more than 2 standard deviations from the 90-day average. This filters noise and surfaces genuine shifts. Use a simple CUSUM (cumulative sum) control chart, which is well-suited to detecting small, sustained changes that point-based thresholds miss.

**Competitive sentiment benchmarking.** Scrape publicly available reviews from Google, Healthgrades, and Vitals for your organization and competitors. Run the same sentiment/aspect pipeline on public reviews to benchmark your performance. Requires careful attention to terms of service and a clear internal-only use policy. The aspect-level comparison ("our wait_time sentiment is 15 points below Regional Medical Center") gives strategic planning teams concrete targets.

**Multilingual feedback processing.** For health systems serving diverse populations, add a language detection step before sentiment analysis. Route non-English feedback to Amazon Translate first, then to sentiment analysis. Better yet, train language-specific sentiment models if you have sufficient labeled data. Translation introduces nuance loss, especially for culturally specific expressions of dissatisfaction. A native-language model will always outperform translate-then-analyze.

---

## Additional Resources

**AWS Documentation:**
- [Amazon Comprehend Sentiment Analysis](https://docs.aws.amazon.com/comprehend/latest/dg/how-sentiment.html)
- [Amazon Comprehend Custom Classification](https://docs.aws.amazon.com/comprehend/latest/dg/how-document-classification.html)
- [Amazon Comprehend Medical DetectPHI](https://docs.aws.amazon.com/comprehend-medical/latest/dev/how-medical-phi.html)
- [Amazon Comprehend Pricing](https://aws.amazon.com/comprehend/pricing/)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)

**AWS Sample Repos:**
- [`amazon-comprehend-examples`](https://github.com/aws-samples/amazon-comprehend-examples): Sentiment analysis, custom classification, and entity detection examples
- [`amazon-comprehend-medical-fhir-integration`](https://github.com/aws-samples/amazon-comprehend-medical-fhir-integration): Healthcare NLP pipeline integrating Comprehend Medical with FHIR
- [`amazon-comprehend-custom-entity`](https://github.com/aws-samples/amazon-comprehend-custom-entity): Training custom entity recognizers (applicable to aspect detection)

**AWS Solutions and Blogs:**
- [Analyzing Customer Feedback with Amazon Comprehend](https://aws.amazon.com/blogs/machine-learning/how-to-scale-sentiment-analysis-using-amazon-comprehend-aws-glue-and-amazon-athena/): End-to-end architecture for scaling sentiment analysis with Glue and Athena
- [Building a Medical Language Processing Pipeline](https://aws.amazon.com/blogs/machine-learning/building-a-medical-language-processing-pipeline-using-amazon-comprehend-medical/): Healthcare-specific NLP pipeline patterns

---

## Estimated Implementation Time

| Tier | Timeline | What You Get |
|------|----------|--------------|
| **Basic** | 1-2 weeks | Document-level sentiment on survey text, simple dashboard, no aspect extraction |
| **Production-ready** | 4-6 weeks | PHI redaction, aspect-level analysis with custom classifier, trend dashboards, alerting |
| **With variations** | 8-12 weeks | Multilingual support, competitive benchmarking, statistical trend detection, executive reporting |

---


---

*← [Main Recipe 8.2](chapter08.02-patient-sentiment-analysis) · [Python Example](chapter08.02-python-example) · [Chapter Preface](chapter08-preface)*
