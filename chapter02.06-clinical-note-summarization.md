# Recipe 2.6: Clinical Note Summarization

**Complexity:** Medium · **Phase:** MVP → Production · **Estimated Cost:** ~$0.05-0.25 per patient summary

---

## The Problem

It's 6:45 AM on a Monday. A hospitalist starts her week covering a 22-bed medicine service. Eight of those patients she's never met. Each one has been on the service for somewhere between two and nine days. Each chart has, on average, forty-something notes: admission H&P, daily progress notes from whoever covered the weekend, consult notes from cardiology and nephrology, nursing notes, case management notes, PT/OT notes. She has a 7:00 AM huddle. She has rounds starting at 8:00. She has exactly fifteen minutes to "chart biopsy" eight unfamiliar patients well enough to not embarrass herself in front of the team and, more importantly, well enough to not miss something clinically important.

So she does what everyone does: she scrolls. Open the most recent progress note. Scan the assessment and plan. Open the admission H&P. Read the HPI. Maybe scan through a consult note if the specialist's name catches her eye. The rest? She doesn't read. She can't. There isn't time. By the time she's making a decision about whether to continue diuresis on bed 4, she's working from a mental model built in ninety seconds from three notes out of forty.

This isn't a failure of clinician diligence. It's a structural mismatch between how clinical information is generated (a running log of notes, one per day per service, accumulating forever) and how it needs to be consumed (a concise picture of "where is this patient, and what matters right now"). The system produces prose. The clinician needs a briefing.

The ICU handoff version of the same problem is sharper. Night shift hands off to day shift. The day attending gets a verbal sign-out in five minutes, then is on the hook for twelve hours of decisions. If the overnight resident forgets to mention that the family has been meeting with palliative care, the day team can spend an hour on aggressive workup for a patient who's already been transitioned to comfort-focused goals. If nobody mentions that the patient self-extubated once already, the day team won't be as cautious on the next extubation attempt. The consequences of a missed detail in handoff are real and documented. <!-- TODO: verify current research on handoff-related adverse events; commonly cited sources include Starmer et al. 2014 NEJM I-PASS trial -->

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

```
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

**Retrieve source documents.** Pull the notes that are in scope. For a current-admission summary, that's the notes from this encounter. For a longitudinal summary, it's a broader pull bounded by the time window the clinician specified. Retrieval should also include structured data relevant to the summary scope: medication lists, problem lists, allergies, recent labs, recent imaging reads. Structured data is easier to summarize faithfully than prose.

**Chunk and preprocess.** Break the input into manageable pieces. Natural chunking boundaries: per-note, per-day, per-service. For each chunk, lightweight preprocessing: remove boilerplate headers and footers, normalize dates, flag negation phrases, tag entities. This preprocessing makes the extraction step more reliable.

**Extract structured facts per chunk.** For each chunk, produce a fielded structured object: what happened, when, who said it, with what certainty. This is where the heavy lifting happens. The extraction prompt is specialty-neutral at this stage; the goal is to capture everything the chunk contains, not to pre-filter for relevance.

**Aggregate and deduplicate facts.** Combine the per-chunk extractions into a single structured object. Deduplicate facts that appear in multiple notes while preserving the original count (a finding mentioned in ten notes is probably important). Resolve conflicting information (one note says the patient is on warfarin, another says apixaban; which is current?). Build a timeline of events.

**Apply must-include checklist.** Check that the aggregated object covers the required categories for this summary type. Allergies present? Active medications present? Code status present if inpatient? Recent critical findings present? Missing categories either get explicitly populated from structured data sources (if available) or flagged as gaps.

**Generate prose by section.** With a clean structured object in hand, produce the readable summary. Use the audience and format parameters from the request to shape the output. Different sections may use different prompts (the narrative section is written differently from the active-problems section). The generation is the last step where new prose is created; everything downstream is validation and rendering.

**Validate against extracted facts.** Check that every specific claim in the generated prose traces back to a fact in the structured object, and through that to a source note. Flag unverified claims. For a clinician-facing tool, unverified claims are typically held for regeneration or explicit clinician review rather than auto-shipped.

**Attach provenance links.** Each section or each fact in the summary gets a link or reference back to the source notes it came from. Clinicians don't trust summaries they can't audit. Good provenance is the difference between "this is a starting point I can verify" and "this is a black box output I can't defend."

**Deliver to requesting clinician.** Render and display the summary in the environment the clinician is working in: the EHR's context-sensitive sidebar, a handoff tool, a separate review UI. Delivery channel affects format (an EHR sidebar is tighter than a full-page review document).

**Log for audit.** Every summary generated, every input set, every version. Clinical summaries that influence care decisions are part of the legal record. You need to be able to reconstruct what a summary said at a specific moment.

---

## The AWS Implementation

### Why These Services

**Amazon Bedrock for LLM inference.** The core summarization work. As with the AVS pipeline (Recipe 2.5), two model tiers earn their place. For per-chunk extraction, a cheaper model (Claude Haiku, Nova Lite, or equivalent) does good work at a fraction of the cost. For the final prose generation where voice and structure matter, a stronger model (Claude Sonnet) produces noticeably better output. Mixing tiers is normal, not exotic.

**Amazon Bedrock Guardrails for safety constraints.** Guardrails give you a policy layer for patient-identifier leakage, off-topic generation, and a contextual grounding check that compares generated content against a reference context. For clinician-facing summaries, the contextual grounding check is the feature that matters most: it scores how well the output stays faithful to the reference context you provide, and it can reject responses that score below a configured threshold.

**Amazon HealthLake for FHIR-based retrieval.** For systems where clinical data is replicated to HealthLake, retrieval is a set of FHIR queries scoped to the patient and time window of interest. DocumentReference for notes, Observation for labs and vitals, Condition for problem lists, MedicationRequest and MedicationStatement for medications, AllergyIntolerance for allergies. The FHIR resource types map cleanly to the summary's must-include categories.

**Amazon Comprehend Medical for negation-aware entity extraction.** This is where Comprehend Medical earns its keep. The service's clinical NLP handles negation ("no evidence of X"), certainty ("possible X"), and temporal relations ("history of X") with reasonable accuracy. For the critical-safety categories (medications, allergies, conditions), running Comprehend Medical alongside or before the LLM extraction provides a cross-check. When the LLM says "no allergies" and Comprehend Medical also says "no allergies," confidence is high. When they disagree, flag for review.

**Amazon OpenSearch (optional) for searchable note indexing.** For very large charts or when summaries are requested across multi-year histories, indexing all notes into OpenSearch lets you retrieve relevant notes by semantic or keyword search rather than pulling everything and chunking. This is a RAG flavor of summarization: retrieve the most relevant chunks first, then summarize the retrieved set. It trades completeness for scalability and can be appropriate for outpatient longitudinal summaries where "relevant to the current question" is a meaningful filter.

<!-- TODO (TechWriter, Expert Review N2, LOW): If OpenSearch is used, deploy the
     domain inside the same VPC with VPC-only access (no public endpoint),
     fine-grained access control enabled, and encryption at rest with a CMK.
     Reads from Lambda require security-group rules that permit the domain's VPC
     endpoint. Call this out here so a reader wiring in OpenSearch doesn't land
     the domain in a public configuration. -->

**AWS Lambda for pipeline steps.** Each stage (retrieve, chunk, extract, aggregate, generate, validate, render) is a Lambda function. Parallelism at the extract stage is often useful: with many chunks, fan out extractions in parallel to keep total latency low.

**AWS Step Functions for orchestration.** The pipeline has branching logic (specialty-specific paths, must-include failure loops, review routing). Step Functions makes the state machine visible and debuggable. For long summaries with many chunks, the parallel Map state is particularly useful for the per-chunk extraction step.

**Amazon S3 for source snapshots and summary archive.** The input note set at the time of summarization, the structured extraction output, the final prose, and any intermediate versions all land in S3 with SSE-KMS encryption. This is the audit trail. A clinician who acted on a summary may need to reference exactly what the summary said two weeks later.

**Amazon DynamoDB for summary metadata and provenance mapping.** One item per generated summary, tracking request parameters, status, and provenance map (which source note contributed which fact). The provenance map is what powers the "where did this come from?" UI feature.

**Amazon EventBridge for trigger patterns.** Summaries may be generated on demand (clinician clicks "summarize") or proactively (every admission gets an on-admission summary; every shift change triggers handoff summaries). EventBridge routes both patterns to the same pipeline.

<!-- TODO (TechWriter, Expert Review A3, HIGH): EventBridge delivery is at-least-once.
     Duplicate ADT replays and shift-change-rule DST overlaps will produce duplicate
     summaries and duplicate LLM spend. Add an idempotency pattern here and in Step 1:
     fingerprint = (encounter_id, admission_event_timestamp) for on-admission;
     (service_id, shift_change_timestamp) for shift-change; conditional DynamoDB
     PutItem with TTL before starting the Step Functions execution. Note on-demand
     requests use a different fingerprint key to allow re-requests after edits. -->

**Amazon API Gateway + Cognito for clinician-facing APIs.** The EHR-side integration calls into API Gateway to request summaries. Cognito (or SAML federation with the EHR's identity provider) handles clinician authentication so that access can be audited at the user level.

**AWS CloudTrail and Amazon CloudWatch for audit and monitoring.** Every Bedrock invocation logged, every S3 access logged, every summary request tied to a clinician identity. CloudWatch tracks latency distributions (summarization of long charts should not block at the terminal), error rates, and per-specialty usage.

### Architecture Diagram

```mermaid
flowchart TB
    A[Clinician Requests Summary<br/>via EHR or Handoff Tool] --> B[Amazon API Gateway<br/>+ Cognito Auth]
    B --> C[Step Functions<br/>Summarization Workflow]

    C -->|Patient + Time Window| D[Amazon HealthLake<br/>Notes, Labs, Meds, Allergies]
    C -->|Patient Preferences & Audience| E[DynamoDB<br/>Summary Request Config]

    D --> F[Lambda<br/>Chunk and Preprocess]
    F --> G[Step Functions Map State<br/>Parallel Chunk Extraction]

    G --> H[Amazon Bedrock<br/>Per-Chunk Extraction<br/>Smaller Model]
    G --> I[Amazon Comprehend Medical<br/>Negation-Aware Entities]

    H --> J[Lambda<br/>Aggregate and Deduplicate]
    I --> J

    J --> K[Lambda<br/>Must-Include Checklist]
    K --> L{All Required<br/>Categories Present?}
    L -->|No| M[Lambda<br/>Targeted Backfill from FHIR]
    M --> K

    L -->|Yes| N[Amazon Bedrock<br/>Section-wise Generation<br/>Stronger Model + Grounding Check]
    N --> O[Lambda<br/>Validate Claims vs Structured Facts]
    O --> P{Validation<br/>Pass?}
    P -->|No| N
    P -->|Yes| Q[Lambda<br/>Attach Provenance Links]

    Q --> R[S3<br/>Summary Archive + Source Snapshot]
    Q --> S[DynamoDB<br/>Provenance Map]
    Q --> T[Return to Clinician via API]

    style H fill:#ff9,stroke:#333
    style N fill:#ff9,stroke:#333
    style K fill:#f99,stroke:#333
    style O fill:#f99,stroke:#333
    style R fill:#f9f,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon Bedrock, Amazon Bedrock Guardrails, Amazon HealthLake, Amazon Comprehend Medical, Amazon S3, AWS Lambda, AWS Step Functions, Amazon DynamoDB, Amazon EventBridge, Amazon API Gateway, Amazon Cognito (or SAML federation), Amazon CloudWatch, AWS CloudTrail, AWS KMS. Amazon OpenSearch is optional for longitudinal summarization at scale. |
| **IAM Permissions** | `bedrock:InvokeModel`, `bedrock:ApplyGuardrail`, `healthlake:SearchWithGet`, `healthlake:ReadResource`, `comprehendmedical:DetectEntitiesV2`, `comprehendmedical:InferICD10CM`, `s3:GetObject`, `s3:PutObject`, `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:Query`, `states:StartExecution`, `states:SendTaskSuccess`, `states:SendTaskFailure`, `events:PutEvents`, `kms:Decrypt`, `kms:GenerateDataKey`. Every action should be scoped to specific resource ARNs (bucket ARNs, table ARNs, HealthLake datastore ARN, foundation-model ARNs, Guardrail ARN, CMK ARNs). |
| **BAA** | AWS BAA signed. Notes contain PHI. Every service in the pipeline must be HIPAA-eligible and covered. |
| **Bedrock Model Access** | Request access to a capable generation model (Claude Sonnet or equivalent) and a smaller extraction model (Claude Haiku or Nova Lite). Verify model behavior on clinical text with negation and uncertainty language before shipping. |
| **EHR Integration** | Authenticated API from the EHR (context-aware launch, SMART on FHIR is typical). Patient and encounter context passed from the EHR. For handoff or shift-change use cases, event triggers on admission and on shift-change times. <!-- TODO (TechWriter, Expert Review N3, LOW): add a sentence that inbound access from the EHR terminates at API Gateway with connectivity pattern per "Why This Isn't Production-Ready" (Direct Connect or site-to-site VPN for on-prem EHRs; PrivateLink or IP-allowlisted public API Gateway for cloud EHRs). --> |
| **Encryption** | S3: SSE-KMS with customer-managed keys. DynamoDB: encryption at rest with CMK. Bedrock and Comprehend Medical: TLS in transit, encryption at rest. CloudWatch Logs: KMS encryption. If Bedrock model-invocation-logging is enabled for quality monitoring, the logged prompts and responses contain PHI; the log destination must be KMS-encrypted and access-controlled to the same standard as the summary archive. Consider sampling rather than logging every invocation. |
| **VPC** | Production: Lambda in private subnets with interface endpoints for Bedrock, Comprehend Medical, HealthLake, KMS, CloudWatch Logs, Step Functions, and EventBridge. Gateway endpoints for S3 and DynamoDB. Interface endpoints are roughly $7-10/month per AZ per endpoint; reflect this in the cost estimate. <!-- TODO (TechWriter, Expert Review N1, LOW): add `com.amazonaws.{region}.monitoring` (CloudWatch metrics plane, distinct from `logs`) because Step 9 emits custom metrics. Clarify that `com.amazonaws.{region}.execute-api` is required only if the clinician-facing API is a private API (EHR callers inside the same VPC). Add `secretsmanager` if credentials are managed through Secrets Manager. --> |
| **CloudTrail** | Enabled with data events for Bedrock invocations, S3 object access, DynamoDB access, and HealthLake reads. Correlate summary requests to the requesting clinician identity. |
| **Sample Data** | Synthea synthetic FHIR data is fine for shape testing. For realistic long-chart testing, MIMIC-IV (through PhysioNet credentialed access) provides de-identified ICU notes in substantial volumes. <!-- TODO: verify current MIMIC-IV access process and note that it is not PHI but is credentialed data --> Never use real PHI in development or testing. |
| **Cost Estimate** | Per-chunk extraction (Haiku/Nova Lite): roughly $0.002-$0.01 per chunk. A typical inpatient stay has 30-80 chunks. Generation (Sonnet): roughly $0.02-$0.08 per summary. Comprehend Medical: roughly $0.001-$0.01 per chunk. End-to-end: $0.05-$0.25 per patient summary for a typical inpatient chart; longitudinal summaries over multi-year histories can run higher ($0.30-$1.00). At 500 summaries per day, roughly $1,500-$7,500 per month. <!-- TODO: verify Bedrock per-1K-token pricing for current Claude models; pricing changes periodically --> |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon Bedrock** | LLM inference for per-chunk extraction and prose generation |
| **Amazon Bedrock Guardrails** | Contextual grounding check, PII/PHI filters, and content policies for generated text |
| **Amazon HealthLake** | FHIR-native retrieval of notes, labs, medications, allergies, and problem list |
| **Amazon Comprehend Medical** | Negation-aware entity extraction; cross-check for medications, conditions, allergies |
| **Amazon OpenSearch (optional)** | Semantic indexing of notes for retrieval-based longitudinal summarization |
| **Amazon S3** | Source note snapshots, intermediate extractions, final summaries, audit archive |
| **AWS Lambda** | Per-stage pipeline logic, chunking, aggregation, validation, rendering |
| **AWS Step Functions** | Workflow orchestration with parallel Map state for per-chunk extraction |
| **Amazon DynamoDB** | Request parameters, summary state, provenance map (fact-to-source linkage) |
| **Amazon EventBridge** | Triggers for on-admission and shift-change summaries; event fan-out |
| **Amazon API Gateway + Cognito** | Authenticated clinician access from the EHR or handoff tool |
| **AWS KMS** | Encryption key management for PHI stores |
| **Amazon CloudWatch + CloudTrail** | Latency metrics, error rates, per-specialty usage analytics, HIPAA audit logs |

### Code

#### Walkthrough

**Step 1: Receive the summary request and resolve context.** A clinician triggers a summary request from inside the EHR or a handoff tool. The request carries the patient identifier, encounter identifier (or time window), the requesting clinician's identity and specialty, the use case (handoff, consult review, pre-visit prep, discharge summary draft), and any format preferences. This step validates the request, logs the access, and initializes state.

```
FUNCTION receive_summary_request(request):
    // request.patient_id:         FHIR Patient ID
    // request.scope:              "current_encounter" | "last_6_months" | "all_time" | custom window
    // request.encounter_id:       present if scope is current_encounter
    // request.requesting_user:    user identity from the calling application
    // request.specialty:          "hospitalist" | "cardiology" | "nephrology" | ... | "general"
    // request.use_case:           "handoff" | "consult" | "pre_visit" | "discharge_summary"
    // request.format:             "narrative" | "problem_oriented" | "sbar" | "ap_only"

    // Generate an ID that tracks this specific summary through the pipeline
    summary_id = generate UUID

    // Authorization check: does this user have access to this patient?
    // Pull from the EHR's authorization context or from an internal ACL.
    IF NOT user_has_access(request.requesting_user, request.patient_id):
        RETURN { status: "FORBIDDEN" }

    // Record the access. This is audit-relevant.
    write to DynamoDB table "summary-requests":
        summary_id          = summary_id
        status              = "INITIATED"
        patient_id          = request.patient_id
        scope               = request.scope
        encounter_id        = request.encounter_id if present
        requesting_user     = request.requesting_user
        requesting_specialty = request.specialty
        use_case            = request.use_case
        format              = request.format
        requested_at        = current UTC timestamp

    // Kick off the Step Functions workflow
    start Step Functions execution:
        state_machine = "ClinicalNoteSummarizationWorkflow"
        input         = { summary_id: summary_id }

    RETURN { summary_id: summary_id, status: "STARTED" }
```

**Step 2: Retrieve source documents.** Pull the notes and structured data that fall inside the request's scope. Scope matters: a handoff summary should look at the current encounter; a pre-visit summary for a new specialty consult may want to look at the entire relevant history. Structured data (allergies, active problems, current medications) is pulled even when scope is narrow, because those categories belong in every summary regardless of the time window.

<!-- TODO (TechWriter, Expert Review S1, HIGH): this step pulls every note in scope
     without filtering for restricted categories. 42 CFR Part 2 substance-use-treatment
     notes, HIV-related content, adolescent confidential notes, and genetic test
     results all have specific disclosure rules. The prose in "Why This Isn't
     Production-Ready" correctly says "Access control has to be enforced at the
     retrieval layer, not bolted on downstream." Add a consent-filter step in the
     pseudocode before returning: use FHIR DocumentReference.securityLabel when
     available, or a local policy engine keyed on note.type + practitioner specialty.
     Without this, the default teaches "pull everything and let downstream sort
     it out," which is a federal-law compliance gap. -->

```
FUNCTION retrieve_source_documents(patient_id, scope, encounter_id):
    // Pull notes based on scope
    IF scope == "current_encounter":
        note_filter = { subject: patient_id, encounter: encounter_id }
    ELSE IF scope == "last_6_months":
        cutoff = current date minus 6 months
        note_filter = { subject: patient_id, date: ">= " + cutoff }
    ELSE:
        note_filter = { subject: patient_id }

    notes = call HealthLake.SearchResources with:
        resource_type = "DocumentReference"
        filters       = note_filter + { status: "current" }
        sort          = "date:desc"

    // Pull always-needed structured data, regardless of scope
    // These categories belong in every summary
    allergies = call HealthLake.SearchResources with:
        resource_type = "AllergyIntolerance"
        filters       = { patient: patient_id, clinical-status: "active" }

    active_problems = call HealthLake.SearchResources with:
        resource_type = "Condition"
        filters       = { patient: patient_id, clinical-status: "active" }

    current_meds = call HealthLake.SearchResources with:
        resource_type = "MedicationRequest"
        filters       = { patient: patient_id, status: "active" }

    // For inpatient handoff or discharge: pull active orders, lines, code status
    code_status = call HealthLake.SearchResources with:
        resource_type = "Observation"
        filters       = { patient: patient_id, code: "code-status-finding" }

    // Snapshot everything so we can reconstruct what the summary was based on
    write to S3: "source-snapshots/{summary_id}/notes.json" = notes
    write to S3: "source-snapshots/{summary_id}/structured.json" = {
        allergies, active_problems, current_meds, code_status
    }

    RETURN {
        notes:           notes,
        allergies:       allergies,
        active_problems: active_problems,
        current_meds:    current_meds,
        code_status:     code_status
    }
```

**Step 3: Chunk and preprocess notes.** Turn the flat list of notes into processable chunks. A single note is often a reasonable chunk; very long notes (an H&P or a multi-page consult) may need sub-chunking. Preprocessing removes boilerplate (EHR-generated headers and footers, standard signatures, macro text) and normalizes dates. This step also tags notes with their service and author so the extraction can attribute content correctly.

<!-- TODO (TechWriter, Expert Review A5, MEDIUM): encounter-boundary enforcement is
     named as the mitigation for the "fact blending across patients or visits"
     failure mode (see "The Failure Modes You Have to Design Around") but the
     pseudocode does not carry encounter_id through chunk metadata or enforce it
     during sub-chunking. A long H&P that references prior admissions, or a
     consult note citing historical context, can feed the extraction with
     mixed-encounter content. Add encounter_id to chunk_metadata, keep sub-chunks
     from crossing encounter boundaries, and (in Step 4) add a hard rule to the
     extraction prompt that facts not tied to this chunk's encounter go into a
     separate `historical_context` field. Aggregation in Step 5 then indexes by
     encounter_id so historical context is preserved but separated. -->

```
FUNCTION chunk_and_preprocess(notes):
    chunks = empty list

    FOR each note in notes:
        text = extract_text_from_document_reference(note)

        // Strip boilerplate and macros
        text = remove_boilerplate(text)

        // Tag with metadata that will travel with the chunk
        chunk_metadata = {
            note_id:      note.id,
            note_date:    note.date,
            note_type:    note.type.display,         // e.g., "Progress Note", "H&P", "Discharge Summary"
            author:       note.author[0].display,
            service:      extract_service_from_note(note)    // e.g., "Hospitalist", "Cardiology", "Nephrology"
        }

        // If the note is very long, sub-chunk it.
        // Target around 2000-4000 tokens per chunk to stay efficient per-call.
        IF token_count(text) > 4000:
            sub_chunks = split_by_headers_then_length(text, target_tokens=3000)
            FOR each sub_chunk in sub_chunks:
                append { text: sub_chunk, metadata: chunk_metadata } to chunks
        ELSE:
            append { text: text, metadata: chunk_metadata } to chunks

    RETURN chunks
```

**Step 4: Extract structured facts per chunk (parallel).** Each chunk goes through an extraction step that produces a structured object: what this chunk contains in categorized, attributed form. Parallel execution (via Step Functions Map state) keeps total latency manageable for long charts. Comprehend Medical runs alongside the LLM extraction for the categories where negation-aware NLP adds the most value: medications, conditions, allergies.

```
FUNCTION extract_chunk_facts(chunk):
    // Prompt the LLM to extract into a fielded schema.
    // The prompt is specialty-neutral; filtering for specialty happens later.

    extraction_prompt = """
    You are extracting clinical facts from a single clinical note. Produce a structured JSON object
    with the fields below. Use ONLY what is explicitly documented in the note. If a field is not
    documented in THIS note, return an empty list or null. Do not infer across visits or dates.

    Preserve negation language exactly. "No evidence of X" must not become "X." "Rule out X" must
    not become "has X." Preserve uncertainty language ("possible," "probable," "rule out").

    Return JSON with these fields:
    - active_problems:        list of {name, icd10_if_known, certainty, is_new_in_this_note}
    - medications_mentioned:  list of {name, dose_if_stated, route_if_stated, action: "continued" | "started" | "stopped" | "dose_changed" | "discussed"}
    - allergies_mentioned:    list of {substance, reaction_if_stated, severity_if_stated}
    - key_findings:           list of clinically significant findings from this note, with exact wording preserved
    - negative_findings:      list of explicit negatives (ruled out, no evidence of, denied)
    - procedures_performed:   list of {name, date_if_stated}
    - labs_imaging_mentioned: list of {test, result_summary, date_if_stated, is_critical}
    - consults_or_recs:       list of {specialty, recommendation, date_if_stated}
    - follow_up_plan:         text as written, or null
    - code_status_mentioned:  exact text if present, or null
    - devices_or_lines:       list of active lines, tubes, drains, implants mentioned
    - critical_events:        list of any adverse events, rapid responses, code blue, etc.

    CLINICAL NOTE:
    Note date: {chunk.metadata.note_date}
    Note type: {chunk.metadata.note_type}
    Service:   {chunk.metadata.service}
    Author:    {chunk.metadata.author}

    {chunk.text}
    """

    // Note on model IDs: Bedrock model IDs are versioned and, in most regions,
    // now require a regional inference-profile prefix (e.g. "us.anthropic...").
    // The family-style IDs used in this pseudocode are illustrative.
    llm_response = call Bedrock.InvokeModel with:
        model_id    = "anthropic.claude-haiku-4"
        prompt      = extraction_prompt
        max_tokens  = 2048
        temperature = 0.0

    extracted = parse JSON from llm_response

    // Cross-check clinical entity extraction with Comprehend Medical.
    // Comprehend Medical is particularly strong at negation and temporal modifiers.
    // Note: the Comprehend Medical text size limit is enforced in bytes, not characters.
    // For multilingual content, encode to utf-8 and slice bytes before calling.
    cm_response = call ComprehendMedical.DetectEntitiesV2 with:
        text = chunk.text

    cm_entities = parse entities from cm_response

    // Add CM findings as a parallel entity list; aggregation step resolves conflicts.
    structured_chunk = {
        chunk_id:             generate UUID,
        note_id:              chunk.metadata.note_id,
        note_date:            chunk.metadata.note_date,
        note_type:            chunk.metadata.note_type,
        service:              chunk.metadata.service,
        author:               chunk.metadata.author,
        llm_extracted:        extracted,
        cm_entities:          cm_entities
    }

    write to S3: "extractions/{summary_id}/{chunk_id}.json" = structured_chunk

    RETURN structured_chunk
```

**Step 5: Aggregate and deduplicate.** Combine the per-chunk structured objects into a single patient-level structured object. De-duplicate facts that appear across multiple notes, but keep the mention count and the date range over which the fact appeared (a fact mentioned in 12 of 15 progress notes is more likely to still be true than a fact mentioned once). Reconcile conflicts where possible, flag them where not.

```
FUNCTION aggregate_facts(structured_chunks, retrieved_structured_data):
    aggregated = {
        active_problems:       empty dict,     // keyed by normalized problem name
        medications:           empty dict,     // keyed by normalized drug name
        allergies:             empty list,
        key_findings_timeline: empty list,
        negative_findings:     empty list,
        procedures:            empty list,
        labs_imaging:          empty list,
        consult_recs:          empty list,
        code_status:           null,
        devices_lines:         empty dict,
        critical_events:       empty list,
        conflicts:             empty list
    }

    // Start with always-present structured data (allergies, active problems, current meds)
    // These are ground truth from the EHR's structured tables; LLM extractions supplement.
    FOR each allergy in retrieved_structured_data.allergies:
        append { substance: allergy.code.display, reaction: allergy.reaction,
                 source: "fhir_allergyintolerance" } to aggregated.allergies

    FOR each problem in retrieved_structured_data.active_problems:
        problem_key = normalize(problem.code.display)
        aggregated.active_problems[problem_key] = {
            name:            problem.code.display,
            icd10:           problem.code.coding[0].code if icd10,
            first_recorded:  problem.recordedDate,
            source:          "fhir_condition",
            mentions:        0   // will increment as we find mentions in notes
        }

    FOR each med in retrieved_structured_data.current_meds:
        med_key = normalize(med.medication.display)
        aggregated.medications[med_key] = {
            name:            med.medication.display,
            dose:            med.dosageInstruction[0].text,
            source:          "fhir_medicationrequest",
            most_recent_action: "active_per_fhir",
            mention_dates:   empty list
        }

    // Now merge in the per-chunk LLM extractions
    FOR each chunk in structured_chunks sorted by note_date ascending:
        extracted = chunk.llm_extracted

        // Active problems from notes
        FOR each problem in extracted.active_problems:
            problem_key = normalize(problem.name)
            IF problem_key exists in aggregated.active_problems:
                aggregated.active_problems[problem_key].mentions += 1
                append chunk.note_date to aggregated.active_problems[problem_key].mention_dates
            ELSE:
                aggregated.active_problems[problem_key] = {
                    name:           problem.name,
                    first_mention:  chunk.note_date,
                    last_mention:   chunk.note_date,
                    mention_count:  1,
                    certainty:      problem.certainty,
                    source:         "note:" + chunk.note_id
                }

        // Medications: track actions over time (started, stopped, dose-changed)
        FOR each med_mention in extracted.medications_mentioned:
            med_key = normalize(med_mention.name)
            IF med_key not in aggregated.medications:
                aggregated.medications[med_key] = {
                    name:            med_mention.name,
                    mention_dates:   empty list,
                    actions:         empty list
                }
            append {date: chunk.note_date, action: med_mention.action,
                    dose: med_mention.dose_if_stated} to aggregated.medications[med_key].actions
            append chunk.note_date to aggregated.medications[med_key].mention_dates

        // Key findings become a timeline
        FOR each finding in extracted.key_findings:
            append {date: chunk.note_date, text: finding,
                    source_note_id: chunk.note_id, service: chunk.service} to aggregated.key_findings_timeline

        // Negative findings preserved verbatim
        FOR each neg in extracted.negative_findings:
            append {date: chunk.note_date, text: neg,
                    source_note_id: chunk.note_id} to aggregated.negative_findings

        // Code status: use the most recent mention
        IF extracted.code_status_mentioned is not null:
            IF aggregated.code_status is null OR chunk.note_date > aggregated.code_status.date:
                aggregated.code_status = { text: extracted.code_status_mentioned,
                                           date: chunk.note_date,
                                           source_note_id: chunk.note_id }

        // Devices and lines: track if added or removed
        FOR each device in extracted.devices_or_lines:
            device_key = normalize(device)
            aggregated.devices_lines[device_key] = {
                device: device,
                last_mentioned: chunk.note_date,
                source_note_id: chunk.note_id
            }

        // Critical events preserved individually
        FOR each event in extracted.critical_events:
            append {date: chunk.note_date, text: event,
                    source_note_id: chunk.note_id} to aggregated.critical_events

    // Conflict detection: e.g., Cardiology recommends X on day 3, Hospitalist still has Y on day 5
    aggregated.conflicts = detect_conflicts(aggregated)
    // TODO (TechWriter, Expert Review A1, HIGH): aggregated.conflicts is built here
    // but never referenced by Step 7's generation prompt. The generator will
    // default to smoothing disagreements into single recommendations, which is
    // the specific clinical-safety failure mode this section of the recipe
    // identifies ("Contradictions across services"). Thread conflicts into
    // Step 7: (a) add "Active Disagreements Between Services" to the use-case
    // section list, (b) add an explicit CONFLICT HANDLING block to the
    // generation prompt that renders each conflict attributed by service
    // without reconciling to a single recommendation.


    write to S3: "aggregations/{summary_id}/aggregated.json" = aggregated

    RETURN aggregated
```

**Step 6: Apply the must-include checklist.** Before generation, verify that the aggregated object covers every required category for this summary type. If allergies are empty but the retrieved structured data had allergies, something went wrong in aggregation. If active problems is empty but the patient has an active chart, something went wrong in aggregation. Missing categories either get backfilled from structured data or get flagged as gaps that the generated prose must acknowledge.

```
FUNCTION apply_must_include_checklist(aggregated, use_case, retrieved_structured_data):
    checklist = required_categories_for_use_case(use_case)
    // For "handoff": [allergies, active_problems, current_medications, code_status,
    //                 recent_critical_events, active_devices_lines, consult_recs]
    // For "consult": [allergies, active_problems, current_medications,
    //                 relevant_history_for_consult_reason]
    // For "pre_visit": [allergies, active_problems, current_medications, recent_labs]
    // For "discharge_summary": [admission_reason, hospital_course, discharge_meds,
    //                           discharge_instructions, follow_up]

    gaps = empty list

    FOR each required_category in checklist:
        IF category_is_empty(aggregated, required_category):
            // Try to backfill from retrieved_structured_data
            backfill_result = attempt_backfill(aggregated, required_category, retrieved_structured_data)
            IF NOT backfill_result.success:
                append required_category to gaps

    // If the source truly has no data for a category, that's a valid state; record it
    // explicitly so the generator includes an "Allergies: none recorded" statement
    // rather than silently omitting the section.
    FOR each category in checklist:
        IF category_is_empty_after_backfill(aggregated, category):
            aggregated.explicit_empties = aggregated.explicit_empties + [category]

    IF length of gaps > 0:
        // Gap means: the category is required AND the source has data AND the aggregation missed it.
        // This is a pipeline failure, not a content absence. Re-run aggregation or escalate.
        RETURN { status: "AGGREGATION_GAP", gaps: gaps }

    RETURN { status: "READY_FOR_GENERATION", aggregated: aggregated }
```

**Step 7: Generate the summary prose.** Now the writing step. The aggregated structured object is the input; the prompt takes the specialty, use case, and format parameters; the output is a section-wise prose summary with explicit section headers. The generation uses Bedrock Guardrails' contextual grounding check with the aggregated object as the reference context, which rejects responses that score below a configured grounding threshold.

```
FUNCTION generate_summary_prose(aggregated, request_params):
    // Build a prompt that enforces:
    // - Section structure appropriate for the use case
    // - Specialty-specific emphasis (nephrology-forward, cardiology-forward, general hospitalist, etc.)
    // - Grounded generation: only use facts in the aggregated object
    // - Preservation of negations, uncertainty, and temporal qualifiers
    // - Explicit handling of empty categories ("Allergies: none documented")

    sections = sections_for_use_case(request_params.use_case, request_params.format)
    // Example for "handoff":
    // ["one_liner", "active_issues", "medications", "allergies", "code_status",
    //  "recent_significant_events", "pending_workup", "consults_and_recs",
    //  "devices_and_lines", "disposition_plan"]

    generation_prompt = """
    You are drafting a clinician-facing summary for a {request_params.specialty} {request_params.use_case} review.
    The reader is a busy clinician who needs to make decisions in minutes.

    HARD REQUIREMENTS:
    - Use ONLY the facts in the structured summary object provided below. Do not add diagnoses,
      medications, findings, or dates that are not in the input.
    - Preserve negation language exactly. If the input says "no evidence of PE," the summary must
      also say "no evidence of PE" or equivalent preserved negation. Never drop negations.
    - Preserve uncertainty language. "Possible sepsis" is not "sepsis." "Rule out PE" is not "PE."
    - Preserve temporal qualifiers. "History of" stays "history of." "This admission" stays "this admission."
    - When a required section has no content, say so explicitly ("Allergies: none documented")
      rather than omitting the section.
    - Attribute consultant recommendations to the consulting service.
    - Keep to {request_params.format} format. Use the section headers listed below.

    SPECIALTY EMPHASIS FOR {request_params.specialty}:
    {specialty_emphasis_instructions(request_params.specialty)}
    // For nephrology: foreground baseline and current creatinine, fluid status, nephrotoxic meds,
    //                 renal dosing notes, dialysis status. Background: other specialty content.
    // For cardiology: foreground cardiac history, current rhythm, troponins, BNP trend, ejection
    //                 fraction if recent, anticoagulation status.
    // For hospitalist (general): balance all active issues; no particular specialty dominance.

    STRUCTURE:
    Use the following section headers, in this order:
    {sections as ordered list}

    STRUCTURED SUMMARY OBJECT (your only source of facts):
    {aggregated as JSON}

    OUTPUT:
    Produce the summary as plain markdown with the section headers above. After the summary,
    output a JSON block listing every specific claim (date, dose, specific finding, specific
    recommendation) with the source_note_id it came from, so claims can be verified.
    """

    response = call Bedrock.InvokeModel with:
        model_id          = "anthropic.claude-sonnet-4"
        prompt            = generation_prompt
        max_tokens        = 6000
        temperature       = 0.2
        guardrail_id      = CLINICAL_SUMMARIZATION_GUARDRAIL_ID
        // The guardrail is configured with:
        // - Contextual grounding check: reference context = aggregated (JSON),
        //   threshold tuned for clinical fidelity (typically 0.85+)
        // - PII detection disabled or configured to permit PHI (this is clinician-facing)
        // - Content filters on harmful content
        //
        // TODO (TechWriter, Expert Review A4, MEDIUM): two corrections required.
        // (1) The contextual grounding check does not compare against the whole
        //     prompt; it compares against text explicitly tagged as grounding
        //     source. Using the Converse API, wrap the aggregated JSON in a
        //     `guardContent` block; using InvokeModel, supply the grounding
        //     source via the Guardrails policy configuration. Without the
        //     tagging, the check returns SAFE regardless of fidelity.
        // (2) Guardrail intervention is signaled on the response body via
        //     `amazon-bedrock-guardrailAction == "INTERVENED"`, not via
        //     `stop_reason`. Branch on that field, not on stop_reason.
        // The Python companion has the matching bug (Code Review Findings 2 and 4);
        // fix them together.
        //
        // TODO (TechWriter, Expert Review S2, MEDIUM): minimum-necessary applies
        // to prompts. The generation step does not need MRN, DOB, phone, address,
        // or insurance identifiers. Redact non-clinical PHI from the aggregated
        // object before the generation call. The preferred name is an exception
        // if the summary references the patient by name; strip everything else.
        // Call this out here and echo it in the Bedrock-logging note in the
        // Encryption row of Prerequisites.

    summary_text = parse summary content from response
    provenance   = parse provenance JSON from response

    // If Guardrails rejected for grounding-check failure, the pipeline loops back
    // to regenerate with a stronger grounding instruction (capped at 2-3 attempts).
    IF response.was_intervened_by_guardrail:
        RETURN { status: "GROUNDING_REJECTED", response: response }

    RETURN { status: "GENERATED", summary_text: summary_text, provenance: provenance }
```

<!-- TODO (TechWriter, Expert Review A2, HIGH): define the fallback for retry
     exhaustion. The prose says "capped at 2-3 attempts" and Step 8 mentions
     "held for regeneration or explicit clinician review," but neither the
     pseudocode nor the architecture diagram defines what happens after the
     cap. Specify a three-attempt ladder (original prompt at T=0.2; stronger
     grounding prompt that names the unverified claims; deterministic T=0.0)
     and a terminal state that routes to a clinician_review_queue or a
     hold-with-alert. Track the terminal state in DynamoDB as
     status = "VALIDATION_EXHAUSTED_ROUTED_TO_REVIEW" and emit a CloudWatch
     metric "ValidationExhausted" with specialty and use_case dimensions.
     Mirror the exhausted-retry exit edge in the architecture diagram so it
     terminates at a review node rather than looping back to the generator.
     The Python companion has the matching auto-deliver bug (Code Review
     Finding 3); fix together. -->

**Step 8: Validate claims and attach provenance.** Belt-and-suspenders alongside the Guardrails grounding check. Parse the generated prose, identify specific claims (dates, doses, named findings, named recommendations), and verify each one against the structured object. Attach source-note links so the clinician can click into any claim to see the note it came from. This is the feature that turns "a summary I have to trust" into "a summary I can verify."

```
FUNCTION validate_and_attach_provenance(summary_text, provenance, aggregated):
    unverified = empty list
    provenance_map = empty dict    // maps (section, claim_text) -> source_note_id

    FOR each claim in provenance.factual_claims:
        // claim has: text, source_note_id (as reported by the model)

        // Verify the source_note_id actually exists in the aggregated input
        IF claim.source_note_id NOT in note_ids_in(aggregated):
            append {claim: claim, reason: "source_not_in_input"} to unverified
            CONTINUE

        // For specific types of claims, do a stronger check:
        IF claim is a dose or quantity:
            actual_source_value = lookup_in_aggregated(aggregated, claim.source_note_id, claim.category)
            IF normalize(claim.asserted_value) != normalize(actual_source_value):
                append {claim: claim, reason: "value_mismatch",
                        asserted: claim.asserted_value, actual: actual_source_value} to unverified

        // For semantic claims (findings, recommendations), check semantic similarity
        ELSE:
            source_text = get_source_text_for_claim(aggregated, claim.source_note_id, claim.category)
            IF semantic_similarity(claim.text, source_text) < 0.7:
                append {claim: claim, reason: "semantic_drift"} to unverified

        // Record provenance for the UI
        provenance_map[claim.text] = claim.source_note_id

    IF length of unverified > 0:
        RETURN { status: "VALIDATION_FAILED", unverified: unverified }

    // Persist provenance map so the UI can render links
    write to DynamoDB table "summary-provenance":
        summary_id     = summary_id
        provenance_map = provenance_map
        verified_at    = current UTC timestamp

    RETURN { status: "VALIDATED", provenance_map: provenance_map }
```

**Step 9: Render and deliver.** The content is clinician-facing markdown. Rendering differs by destination. An EHR sidebar wants compact markdown. A handoff tool may want structured sections with collapsible detail. A PDF for printed handoff wants a different layout. The archive in S3 always keeps both the raw markdown and the structured provenance so the summary can be re-rendered later in any format.

```
FUNCTION render_and_deliver(summary_id, summary_text, provenance_map, request_params):
    // Archive raw content and provenance
    write to S3: "final-summaries/{summary_id}/summary.md" = summary_text
    write to S3: "final-summaries/{summary_id}/provenance.json" = provenance_map

    // Render for destination
    IF request_params.destination == "ehr_sidebar":
        rendered = render_compact_markdown_with_clickable_provenance(summary_text, provenance_map)
    ELSE IF request_params.destination == "handoff_tool":
        rendered = render_structured_handoff_view(summary_text, provenance_map)
    ELSE IF request_params.destination == "pdf":
        rendered = render_pdf_with_provenance_footnotes(summary_text, provenance_map)

    write to DynamoDB table "summary-requests": update summary_id with
        status       = "DELIVERED"
        delivered_at = current UTC timestamp
        render_type  = request_params.destination

    // Emit a CloudWatch metric: latency, chunk count, specialty, use case
    emit CloudWatch metric:
        namespace    = "ClinicalSummarization"
        metric_name  = "SummariesDelivered"
        dimensions   = { specialty, use_case, render_type }

    RETURN { status: "DELIVERED", rendered: rendered }
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter02.06-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

### Expected Results

**Sample output for a hospitalist handoff summary on a 6-day inpatient admission:**

<!-- Note: all identifiers, dates, and clinician names below are synthetic. Never use
     real patient data in development or test fixtures. -->

<!-- TODO (TechWriter, Expert Review A6, MEDIUM): the generated_summary above
     contains 25+ specific claims (EF, troponin trend, cath date, LAD stenosis,
     BNP values, furosemide doses, HD timing, UF volumes, hematocrit trend,
     atorvastatin dose change, metoprolol home med, etc.) but `factual_claims`
     lists only 7. For a recipe whose teaching pivot is "every specific claim
     must trace to source," the showcase output models a sparse trace. Either
     expand `factual_claims` to 20-40 entries matching the density of the
     summary, or add a one-line note beneath the JSON that the array is
     abbreviated here for readability and a production validator enumerates
     every specific claim. -->
<!-- TODO (TechWriter, Expert Review V4, LOW): the sample uses clinician
     shorthand without expansion (DAPT, PCI, DES to LAD, IJ tunneled, UF, BNP,
     s/p, NSTEMI, "per cards"). Appropriate for a clinician-facing summary,
     but this cookbook has a mixed audience. Either add a brief
     "Reading the Sample: Abbreviations" footnote right before the JSON, or
     preface the JSON with a note that clinician-facing summaries use clinical
     shorthand by design. -->

```json
{
  "summary_id": "CNS-2026-05-10-04129",
  "status": "DELIVERED",
  "specialty": "hospitalist",
  "use_case": "handoff",
  "format": "problem_oriented",
  "scope": "current_encounter",
  "source_note_count": 47,
  "generated_summary": "# Handoff Summary\n\n## One-Liner\n72M with CHF (EF 30%) and ESRD on HD, admitted 5/4 with volume overload and NSTEMI, now hospital day 6, post-cath with DES to LAD on 5/7, currently on heparin drip, cards following.\n\n## Active Issues\n\n**1. NSTEMI, post-PCI (active).** Troponin peaked 4.2 on 5/5, trended down to 0.18 on 5/9. Cardiac cath 5/7: 90% LAD stenosis, DES placed. No complications. On DAPT (aspirin 81 mg, clopidogrel 75 mg) and heparin drip per cards.\n\n**2. Acute on chronic CHF exacerbation (improving).** Admission BNP 3200 (baseline ~800). IV furosemide 80 mg BID x 3 days, transitioned to oral 40 mg daily 5/8. Net -6L since admission. Weights stable x 48 hours. EF 30% (unchanged from prior TTE).\n\n**3. ESRD on hemodialysis (stable).** Dialyzes MWF at outpatient center. Continued in-hospital schedule. Last HD 5/9 with UF 2.5L. Line is right IJ tunneled catheter (dialysis access).\n\n**4. Anemia of CKD (stable).** Hgb 9.4 on admission, nadir 8.6 post-cath (no bleeding identified), currently 9.1. Continuing home darbepoetin.\n\n## Medications\n\n- Aspirin 81 mg daily (started this admission)\n- Clopidogrel 75 mg daily (started this admission)\n- Heparin drip (cards managing, anticipate transition to fondaparinux or discontinuation per cards 5/10 or 5/11)\n- Metoprolol succinate 50 mg daily (home med, continued)\n- Atorvastatin 80 mg nightly (home 40 mg, increased this admission per cards)\n- Furosemide 40 mg PO daily (transitioned from IV 5/8)\n- Darbepoetin per HD protocol\n- Lisinopril HELD (hyperkalemia risk)\n\n## Allergies\n- Sulfa (rash, documented)\n\n## Code Status\nFull code, confirmed with patient and daughter on 5/5.\n\n## Recent Significant Events\n- 5/5 07:12 Troponin peak 4.2, cards consulted\n- 5/7 Cardiac cath with DES to LAD\n- 5/7 Post-cath small groin hematoma, stable, resolved\n- 5/8 Transitioned IV to PO diuretic, weights holding\n\n## Pending\n- Cards to decide on heparin-to-fondaparinux transition vs. discontinuation (expected 5/10-5/11)\n- Nephrology weighing in on contrast exposure impact, no worsening of baseline renal function noted\n- Outpatient cards follow-up to be scheduled for 1 week post-discharge\n\n## Consults and Recommendations\n- **Cardiology (Dr. Patel):** Managing post-PCI anticoagulation. DAPT for 12 months minimum.\n- **Nephrology (Dr. Martinez):** No dose adjustments needed for current regimen; continue HD schedule.\n\n## Lines, Tubes, Drains\n- Right IJ tunneled HD catheter (dialysis access, established prior to admission)\n- Peripheral IV x 1\n\n## Disposition Plan\nAnticipate discharge 5/11 or 5/12 pending cards clearance. Home with outpatient HD continuation. Cards follow-up within 7 days, PCP follow-up within 14 days.",
  "factual_claims": [
    {"claim": "EF 30%", "source_note_id": "note-2026-05-04-echo-impression"},
    {"claim": "Troponin peaked 4.2 on 5/5", "source_note_id": "note-2026-05-05-hospitalist-progress"},
    {"claim": "Cardiac cath 5/7: 90% LAD stenosis, DES placed", "source_note_id": "note-2026-05-07-cath-report"},
    {"claim": "BNP 3200", "source_note_id": "note-2026-05-04-admission-hp"},
    {"claim": "Net -6L since admission", "source_note_id": "note-2026-05-09-hospitalist-progress"},
    {"claim": "Full code, confirmed with patient and daughter on 5/5", "source_note_id": "note-2026-05-05-hospitalist-progress"},
    {"claim": "Sulfa allergy (rash)", "source_note_id": "fhir_allergyintolerance"}
  ],
  "validation_status": "VALIDATED",
  "must_include_categories_covered": [
    "allergies", "active_problems", "current_medications", "code_status",
    "recent_critical_events", "active_devices_lines", "consult_recs"
  ],
  "chunks_processed": 47,
  "processing_time_ms": 28000
}
```

**Performance benchmarks:**

| Metric | Typical Value |
|--------|---------------|
| End-to-end latency, 30-50 chunk chart | 15-40 seconds |
| End-to-end latency, 150+ chunk chart (multi-year longitudinal) | 45-120 seconds |
| Validation pass rate (first generation) | 85-95% for current-encounter summaries; 75-88% for longitudinal |
| Must-include checklist pass rate (after backfill) | 95%+ for inpatient handoff; 90%+ for discharge summaries |
| Clinician override/edit rate when review is enabled | 10-25% minor edits; 3-8% substantive edits |
| Cost per summary | $0.05-$0.25 inpatient; $0.30-$1.00 longitudinal |
| Grounding-check rejection rate (Guardrails) | 2-8% initial; drops to under 2% after prompt iteration |
| Provenance link accuracy | 95%+ when validator is strict; unverified claims are held |

**Where it struggles:**

- **Very long longitudinal charts.** Summarizing ten years of outpatient records produces summaries that are either too long to be useful or too compressed to capture nuance. Retrieval-based (RAG) summarization with scoped queries ("summarize this patient's diabetes history") works better than "summarize everything."
- **Sparse notes.** A chart with six notes, each a single paragraph, doesn't have enough content to fill a structured summary. The output reads thin or repeats the source nearly verbatim.
- **Ambulatory vs inpatient style mismatch.** Ambulatory notes often use problem-oriented structures that map poorly to inpatient handoff formats and vice versa. The format parameter helps but doesn't fully bridge the gap.
- **Outside records.** Faxed records OCR'd into the chart vary dramatically in text quality. A note that came in as a scanned PDF with marginal OCR produces extraction errors that cascade into the summary.
- **Contradictions across services.** When two services disagree (cardiology wants aggressive diuresis, nephrology worries about the kidneys), the summary needs to surface the disagreement rather than picking a side. This takes specific prompt engineering; without it, the model tends to smooth disagreements into single recommendations.
- **Pediatrics and obstetrics.** Specialty-specific prompt templates should exist for these populations; a generic hospitalist template produces summaries that miss population-specific priorities (growth parameters, immunization status, gestational age).
- **Behavioral health integration.** Mental health notes often have restricted access and different disclosure rules (42 CFR Part 2 for substance use treatment records). Summarization pipelines need to respect these boundaries; a summary that pulls content from a Part 2 note without the right consent is a compliance problem, not just a quality problem.
- **Code status history.** Code status changes over the course of a long admission (full code on admission, DNR after day 5 family meeting, then reversed after recovery). A summary that reports only the current status misses the arc; a summary that reports every change clutters. The right balance depends on use case.

---

## Why This Isn't Production-Ready

The pipeline above produces summaries that are structurally sound and clinically usable. Deploying it in a health system requires addressing a longer list.

**Provenance UX is where trust lives or dies.** Clinicians will use a summarization tool if they can verify any claim in one click. They won't use it if they have to hunt through forty notes to check a fact. Provenance isn't a backend concern; it's a UX concern that the rendering layer has to get right. Expect significant iteration on how provenance links are displayed, what happens when a clinician clicks through, and how conflicting provenance (a claim drawn from multiple notes) is represented.

**Specialty template maintenance.** Every specialty has its own idea of what a good summary looks like. Nephrology wants fluid status and creatinine trends foregrounded. Oncology wants treatment history, staging, and response data. Pediatrics wants growth and immunizations. ICU wants ventilator settings and pressor trends. Each specialty template is a living artifact that clinical leadership from that specialty should own and iterate. The engineering team provides the pipeline; the clinical team provides the content priorities.

**Consults as first-class data.** Consult notes are not just more notes; they're attributed opinions that clinicians weight differently. A good summary renders "Cardiology recommends X" as "Cardiology recommends X," not as "X is recommended." This attribution discipline has to be enforced at extraction, preserved through aggregation, and respected in generation. It's easy to get right by accident and easy to get wrong by accident.

**Handling confidential notes and restricted content.** Behavioral health notes, substance use treatment (42 CFR Part 2), HIV-related content, genetic test results, and adolescent confidential information all have specific disclosure rules. A summarization pipeline that pulls from every note in the chart risks disclosing protected content inappropriately. Access control has to be enforced at the retrieval layer, not bolted on downstream.

**Real-time chart changes.** A summary generated at 7:00 AM is stale by 10:00 AM when the cardiology consult note is signed. For inpatient handoff, this is fine (handoff is a point-in-time event). For ongoing rounds use, you need a refresh pattern that either regenerates on significant events (note signed, result available, med change) or shows the clinician when the summary is stale.

**Provider attribution and liability.** A summary that influences clinical decision-making becomes part of the decision record. Legal teams will ask: who authored this? What's the provider attribution? Is it part of the legal medical record or not? These aren't questions the engineering team answers; they're questions the governance structure has to answer before deployment. Start these conversations months in advance.

**FDA and regulatory posture.** Clinical summarization that influences care decisions may fall within FDA's interest in clinical decision support. The current posture (as of this writing) exempts "decision support that allows independent review of the basis" of recommendations. Provenance linking arguably satisfies that criterion. But the boundary is not crisp, and summarization tools that trend toward decision-making (not just summarization) have higher regulatory exposure. Legal and regulatory review is warranted before broad deployment. <!-- TODO: verify current FDA CDS guidance state; this landscape evolves -->

**Clinician training and adoption.** A summary tool dropped into an EHR without training produces one of two failure patterns. Either clinicians don't use it (because they don't know it exists or don't trust it) or they over-trust it (because it's fast and looks polished). Both are bad. Structured training that shows clinicians how to verify provenance, how to read for omissions, and how to report errors is essential. This is change management, not engineering.

**Evaluation methodology.** How do you know the summaries are good? Automated metrics (ROUGE, BLEU) are weakly correlated with clinical usefulness. The real evaluation involves blinded clinician review of summary quality, omission detection, and clinical accuracy. Build this evaluation pipeline before you scale the summarization pipeline, not after. Without it, you're shipping without knowing what you're shipping.

**Feedback loops.** When a clinician finds an error in a summary, how does that error get back to the team? If the answer is "an email to the ML team," the feedback loop will be slow and fragile. Build a one-click "this summary is wrong" feedback mechanism that captures context, the clinician's correction, and routes to a review queue. Use the feedback to iterate on prompts, chunking strategies, and must-include checklists. This is the difference between a tool that gets better over time and one that plateaus.

**Cost at scale.** A hospital generating handoff summaries for every patient twice a day (morning and evening handoff) for a 500-bed facility can rack up meaningful Bedrock spend. Budget modeling should assume steady-state usage patterns including summary regeneration on note events, not just one-per-admission. Cost optimization options: cache the structured extractions (they change only when notes change) and regenerate only the final prose when context shifts; use smaller models for extraction; apply input token reduction through aggressive preprocessing.

**Audit logging and retention.** The clinical summary is PHI. The source snapshot is PHI. The structured extraction is PHI. All three require HIPAA-appropriate retention (6+ years typical), access logging, and encryption at rest and in transit. The provenance map is PHI-adjacent (it references notes that are PHI). Configure retention policies explicitly; don't leave S3 objects lingering without lifecycle rules.

**Network egress for external EHR connectivity.** For health systems with cloud EHRs, summary requests often come in over TLS to vendor public endpoints; manage credentials via Secrets Manager and enforce egress controls. For on-premises EHRs, plan for Direct Connect or site-to-site VPN with FHIR gateways reachable over private IPs. PHI in transit must never traverse the public internet unencrypted.

---

## The Honest Take

Clinical summarization is one of those problems I've watched teams underestimate repeatedly. The demo is easy: pick a nice-looking inpatient chart, generate a summary, show it to leadership, watch them nod. Of course it works. Modern models are good at this. The demo is not the hard part.

The hard part is everything downstream of the demo. Does it handle the chart with twelve nursing notes full of "patient resting comfortably" and three actually-informative progress notes? Does it handle the consult note that's three pages of copy-pasted history before the one sentence that matters? Does it correctly foreground the DNR status for the patient whose code status changed on hospital day five? Does it distinguish the three different sodium values from three different days? Does it preserve the negation in "ruled out PE" instead of quietly dropping it? Does it flag the disagreement between cardiology and nephrology rather than smoothing it into a single recommendation? Does the clinician reading the summary at 6:45 AM on a Monday actually find it more useful than scrolling the chart themselves?

In my experience, the delta between "this works on our demo chart" and "this works reliably on production charts" is about nine months of engineering and clinical iteration. Not three weeks. Teams that budget three weeks and then try to ship get the pattern I described in the AVS recipe: beautiful summaries on cherry-picked charts, subtle errors in production, clinician trust erodes, project gets paused for rework. Budget the nine months. Build the validation, the must-include checklist, the provenance linking, the feedback loop, and the evaluation methodology as first-class components, not as afterthoughts.

The second thing I'd emphasize: specialty is not optional. The teams that try to build "one summarizer for all clinicians" produce summaries that are generic enough to disappoint everyone. A nephrologist reading a generic summary has to still read the notes to find the kidney stuff. An oncologist reading a generic summary has to still read the notes to find the treatment history. The generic summary saves them five minutes; reading for the missing stuff costs them ten. Net negative. Specialty-specific templates from day one, with the specialty's clinical leadership involved in defining priorities, produces tools that actually save time.

The third thing: provenance is not a nice-to-have. It's the feature that makes the tool defensible. Without provenance, a clinician who acts on the summary and then has something go wrong cannot explain their decision except as "I read the AI summary." That's a weak defense clinically and a terrible one legally. With provenance, the clinician can say "I read the summary, verified the specific claim that informed my decision against the source note, and documented my independent assessment." That's the defensible workflow, and it only works if provenance is present, accurate, and easy to click through.

Fourth: listen to the clinicians who don't use the tool. The clinicians who adopt it early and love it will tell you what's working. The clinicians who try it once and never come back are telling you something at least as important. Set up a process to interview the non-adopters. What made them stop? Was it a specific error? A UI friction point? A trust concern? A performance issue? Usually it's one or two specific issues that are fixable; you just have to know what they are.

Fifth: this use case has a stealth benefit that's worth naming. The structured extraction step, properly designed, produces a clean, fielded representation of a patient's clinical state. That representation is independently valuable. It can power population health dashboards that today rely on brittle parsing of structured problem lists. It can power quality-measure reporting that today requires manual chart review. It can feed longitudinal analytics that today are blocked because the content lives in free text. Teams that build the summarization pipeline well tend to discover six months later that they built a clinical-data asset they didn't originally plan for. Design the extraction schema with that downstream use in mind and the ROI is substantially better than the summarization use case alone would suggest.

Finally: the bar for "useful" here is lower than teams often assume. Clinicians are not expecting the summary to replace reading the chart. They're expecting it to give them enough of a picture to know which notes to read carefully and which to skim. That's a reachable bar. You don't need perfect summaries. You need summaries that are good enough to orient the reader, honest about their gaps, and fast enough to use in the fifteen-minute window before rounds. Build for that bar, not for the imaginary bar where the summary replaces the chart entirely.

---

## Variations and Extensions

**Handoff-specific summaries with SBAR format.** The classical Situation-Background-Assessment-Recommendation format is widely used in nursing and interdisciplinary handoffs. An SBAR-formatted summary is a small variation on the pipeline: same extraction, same aggregation, different final generation prompt with SBAR-specific section headers. The content overlaps substantially with the problem-oriented format but the ordering and emphasis differ.

**Specialty-consultation "pre-read" summaries.** When a consulting specialist receives a consult request, they typically need to review the chart before seeing the patient. Extend the pipeline to produce a consult-specific summary that foregrounds the reason for consult, relevant history for the consult question, and recent findings that inform the consult. This is essentially the specialty-aware summarization case applied to a specific workflow. Bonus: the consult note the specialist writes afterward can be auto-compared to the pre-read summary to track whether the summary captured the issues the specialist actually considered.

**Longitudinal disease-specific summaries.** For chronic conditions (diabetes, heart failure, IBD, multiple sclerosis), a disease-specific longitudinal summary pulls across all notes, labs, imaging, and procedures relevant to that condition. "Summarize this patient's diabetes care since 2019." This is a RAG variation: retrieve the subset of notes relevant to the condition, then summarize. Clinicians find these invaluable for specialty-referral preparation and for patients who have seen multiple providers.

**Interval summaries ("what changed since last time I saw this patient").** For providers with long-standing patient relationships, the useful summary is often not "the patient's whole history" but "what changed since I saw them three months ago." This is an interval summary: scope is the time window between visits, structure foregrounds changes (new meds, new diagnoses, interim hospitalizations, significant lab changes). Low overhead extension of the main pipeline; scope just becomes "since last encounter with this provider."

**Audio-rendered handoff.** For providers who prefer audio (during commute, while washing hands between rooms), render the summary through Amazon Polly as a short audio briefing. Polly handles medical pronunciation adequately for many terms; edge cases may need a custom lexicon. The audio is PHI and must be stored with the same encryption, access controls, and retention posture as the text summary.

**Multi-patient rounding summaries.** For a hospitalist rounding on 15 patients, a meta-summary that gives one-liners for each patient on the service, with ability to expand to the full summary per patient, is more useful than 15 separate summaries. The pipeline generates per-patient summaries as before, then a meta-generator produces the rounding list from the set.

**Quality-measure extraction alongside summarization.** Because the structured extraction already identifies medications, conditions, procedures, and findings, it can feed into quality-measure logic with minor additions. Did the patient with CHF get prescribed an ACE/ARB or guideline-directed alternative at discharge? The extracted structure knows. Wiring that logic alongside the summarization pipeline adds measurable value without duplicate extraction work.

---

## Related Recipes

- **Recipe 2.2 (Medical Terminology Simplification):** Where clinical summarization targets clinicians (and keeps clinical terminology), simplification targets patients. Same source material, different audience, different constraints.
- **Recipe 2.3 (Clinical Documentation Improvement):** CDI looks at notes to suggest improvements for coding and billing. The structured extraction techniques used here are closely related to what CDI tools need, and the two pipelines can share extraction infrastructure.
- **Recipe 2.4 (Prior Authorization Letter Generation):** Another grounded-generation use case. The aggregation and validation patterns transfer; the output format differs substantially.
- **Recipe 2.5 (After-Visit Summary Generation):** Patient-facing version of the summarization problem. Shares the grounded-generation architecture, the validation discipline, and the must-include checklist concept; differs in audience, tone, and reading level.
- **Recipe 2.8 (Ambient Clinical Documentation):** When ambient documentation is producing the notes that get summarized, the input quality is higher and more consistent, which improves downstream summarization quality.
- **Recipe 2.9 (Clinical Decision Support Synthesis):** Summarization and decision support sit on a continuum. Pure summarization stays descriptive; decision support adds recommendations. The regulatory posture differs; the architectural patterns overlap.
- **Recipe 7.x (Risk Scoring):** Structured extractions produced by the summarization pipeline can feed risk models. The same normalized problem list, medication list, and finding timeline that drive the summary can drive downstream predictive models. <!-- TODO: verify specific recipe number once Chapter 7 is drafted -->

---

## Additional Resources

**AWS Documentation:**
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [Amazon Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html)
- [Bedrock Guardrails Contextual Grounding Check](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-contextual-grounding-check.html)
- [Amazon HealthLake Developer Guide](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html)
- [Amazon Comprehend Medical Developer Guide](https://docs.aws.amazon.com/comprehend-medical/latest/dev/comprehendmedical-welcome.html)
- [AWS Step Functions Map State](https://docs.aws.amazon.com/step-functions/latest/dg/amazon-states-language-map-state.html)
- [Amazon API Gateway Developer Guide](https://docs.aws.amazon.com/apigateway/latest/developerguide/welcome.html)
- [AWS HIPAA Eligible Services Reference](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)

**AWS Sample Repos:**
- [`amazon-bedrock-samples`](https://github.com/aws-samples/amazon-bedrock-samples): Bedrock usage patterns including grounded generation and Guardrails
- [`aws-healthcare-lifescience-ai-ml-sample-notebooks`](https://github.com/aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks): Healthcare-specific ML patterns including clinical text summarization examples
- [`amazon-comprehend-medical-examples`](https://github.com/aws-samples/amazon-comprehend-medical-examples): Comprehend Medical patterns for clinical entity and relationship extraction

**AWS Solutions and Blogs:**
- [Generative AI on AWS for Healthcare](https://aws.amazon.com/health/generative-ai/): Overview of healthcare LLM applications on AWS
- [AWS for Healthcare Reference Architectures](https://aws.amazon.com/architecture/reference-architecture-diagrams/?solutions-all.sort-by=item.additionalFields.sortDate&solutions-all.sort-order=desc&awsf.content-type=*all&awsf.methodology=*all&awsf.tech-category=tech-category%23ai-ml&awsf.industries=industries%23healthcare): Filter by AI/ML and Healthcare
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/): Search for "clinical summarization," "healthcare summarization," and related terms for current customer case studies

**Industry and Research Resources:**
- [HL7 FHIR DocumentReference Resource](https://www.hl7.org/fhir/documentreference.html): The FHIR model for clinical notes, which drives retrieval patterns
- [I-PASS Handoff Framework](https://www.ipassinstitute.com/): The evidence-based handoff framework that informs handoff-summary structure
- [Joint Commission National Patient Safety Goals](https://www.jointcommission.org/standards/national-patient-safety-goals/): Includes communication-related goals relevant to summarization use cases
- [42 CFR Part 2 (Substance Use Treatment Records)](https://www.ecfr.gov/current/title-42/chapter-I/subchapter-A/part-2): Federal privacy rules for substance use treatment records; affects what can be included in summaries
- [FDA Clinical Decision Support Software Guidance](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software): Current FDA position on CDS, relevant for where summarization crosses into decision support
- [MIMIC-IV Database (PhysioNet)](https://physionet.org/content/mimiciv/): Credentialed-access de-identified ICU data useful for development and evaluation of summarization systems

---

## Estimated Implementation Time

| Tier | Timeline | What You Get |
|------|----------|--------------|
| **Basic (POC)** | 6-8 weeks | Single specialty (general hospitalist), single use case (handoff), narrative format. Per-chunk extraction and aggregation working. Must-include checklist enforced for core categories. Basic provenance links. Demonstrated on synthetic or MIMIC-IV data. |
| **Production-ready** | 20-28 weeks | Multiple specialties (hospitalist, cardiology, nephrology, at minimum). Multiple use cases (handoff, consult pre-read, discharge summary draft). Multiple output formats. EHR-integrated delivery with clickable provenance. Clinician feedback loop. Formal evaluation methodology with blinded review. Full audit trail. Operational dashboards. |
| **With variations** | 36-52 weeks | Six or more specialty templates. Longitudinal disease-specific summarization. Interval summaries. Audio rendering. Multi-patient rounding summaries. Quality-measure extraction alongside summarization. Production-grade feedback loop with automated retraining or prompt iteration. Health system-wide rollout with change management and clinician training. |

---

## Tags

`llm` · `generative-ai` · `bedrock` · `healthlake` · `comprehend-medical` · `clinical-summarization` · `clinician-facing` · `grounded-generation` · `provenance` · `handoff` · `hospital-course` · `specialty-aware` · `map-reduce` · `hierarchical-summarization` · `must-include-checklist` · `guardrails-contextual-grounding` · `medium-complexity` · `hipaa` · `fhir` · `smart-on-fhir`

---

*← [Recipe 2.5: After-Visit Summary Generation](chapter02.05-after-visit-summary-generation) · [Chapter 2 Index](chapter02-index) · [Next: Recipe 2.7 - Literature Search and Evidence Synthesis →](chapter02.07-literature-search-evidence-synthesis)*
