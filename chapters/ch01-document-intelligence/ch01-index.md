# Chapter 1: Document Intelligence

> Healthcare runs on paper. Faxes remain the dominant interoperability mechanism for prior authorizations, referrals, and records requests. Every integration eventually hits a document extraction problem — whether it's scanned claims forms, handwritten physician notes, or multi-page attachments. This chapter covers extracting structured, actionable data from the unstructured documents that flow through payer operations daily. PHI is present in virtually every document, confidence scoring is non-negotiable for human-in-the-loop workflows, and multi-page mixed-format documents (tables, checkboxes, free text, handwriting) are the norm rather than the exception.

**AWS Services Featured:** Amazon Textract, Amazon Comprehend Medical, AWS Lambda, Amazon S3, Amazon DynamoDB, Amazon A2I (Augmented AI)

---

## What You'll Learn

By the end of this chapter, you'll know how to:

- **Extract structured fields from images** — turning a phone photo of an insurance card into a JSON payload your eligibility system can consume (Recipe 1.1)
- **Digitize multi-section paper forms** — handling tables, checkboxes, and mixed layouts from patient intake forms (Recipe 1.2)
- **Combine OCR with medical NLP** — layering Amazon Comprehend Medical on top of Textract output to pull ICD-10 codes and clinical entities from lab requisitions (Recipe 1.3)
- **Process multi-page clinical documents** — tackling the prior authorization problem: extracting structured data from 5-20 page faxed submissions where every page is different (Recipe 1.4)
- **Build document classification and routing pipelines** — classifying incoming attachments by type, routing each to the right extractor, and merging results into a unified claims record (Recipe 1.5)
- **Handle handwritten text with confidence scoring and human review** — the hardest extraction problem in healthcare, solved with a tiered confidence pipeline and Amazon A2I (Recipe 1.6)
- **Extract medication data from prescription labels** — mapping pharmacy label fields to RxNorm concept IDs for downstream medication reconciliation (Recipe 1.7)
- **Parse Explanation of Benefits documents** — normalizing payer-specific table layouts into a canonical financial schema with math-based validation (Recipe 1.8)
- **Process medical records request forms** — extracting routing identifiers and validating HIPAA authorization elements before records are released (Recipe 1.9)
- **Migrate historical paper charts at scale** — bulk OCR, document segmentation, FHIR R4 mapping, and HealthLake import for legacy chart digitization programs (Recipe 1.10)

## Chapter Prerequisites

Before diving into these recipes, make sure you have:

**AWS Account & Services:**
- An AWS account with a signed [AWS Business Associate Addendum (BAA)](https://aws.amazon.com/compliance/hipaa-compliance/) — non-negotiable for any workload touching PHI
- Amazon Textract, Amazon Comprehend Medical, Amazon S3, AWS Lambda, and Amazon DynamoDB enabled in your target region
- For Recipe 1.6: Amazon A2I (Augmented AI) and an A2I workforce configured

**IAM & Security:**
- An IAM role for Lambda with least-privilege access to Textract, Comprehend Medical, S3, and DynamoDB
- S3 bucket policies enforcing `aws:SecureTransport` (TLS-only) and default SSE-KMS encryption
- VPC endpoints for Textract and S3 if operating in a private subnet (recommended for production)
- CloudTrail enabled for audit logging of all API calls touching PHI

**Sample Data:**
- Each recipe includes notes on synthetic test data. For real-world testing, use de-identified documents or CMS sample forms — never use actual PHI in development environments
- The [CMS Forms Library](https://www.cms.gov/medicare/cms-forms) provides real-world form layouts for testing

**Development Environment:**
- Python 3.9+ with boto3
- AWS CLI configured with appropriate credentials
- Cost estimates in each recipe assume us-east-1 pricing as of early 2026

---

## Recipes

| # | Recipe | Complexity | Phase |
|---|--------|------------|-------|
| 1.1 | [Insurance Card Scanning](recipe-1.1-insurance-card-scanning.md) | Simple | ⭐ MVP |
| 1.2 | [Patient Intake Form Digitization](recipe-1.2-patient-intake-digitization.md) | Simple | ⭐ MVP |
| 1.3 | [Lab Requisition Form Extraction](recipe-1.3-lab-requisition-extraction.md) | Moderate | 🔶 Phase 2 |
| 1.4 | [Prior Authorization Document Processing](recipe-1.4-prior-auth-document-processing.md) | Moderate | ⭐ MVP |
| 1.5 | [Claims Attachment Processing](recipe-1.5-claims-attachment-processing.md) | Complex | 🔶 Phase 2 |
| 1.6 | [Handwritten Clinical Note Digitization](recipe-1.6-handwritten-clinical-note-digitization.md) | Complex | 🔷 Phase 3 |
| 1.7 | [Prescription Label OCR](recipe-1.7-prescription-label-ocr.md) | Simple | 🔶 Phase 2 |
| 1.8 | [EOB Processing](recipe-1.8-eob-processing.md) | Moderate | 🔶 Phase 2 |
| 1.9 | [Medical Records Request Extraction](recipe-1.9-medical-records-request-extraction.md) | Moderate | 🔶 Phase 2 |
| 1.10 | [Historical Chart Migration](recipe-1.10-historical-chart-migration.md) | Complex | 🔷 Phase 3 |

**Reading order:** Recipes build on each other. Start with 1.1 — each successive recipe introduces new concepts while referencing patterns established earlier. If you're only here for one thing, Recipe 1.4 (Prior Auth) is the most common real-world ask and can be read after 1.1-1.2 for context.

---

*Next: [Recipe 1.1 — Insurance Card Scanning →](recipe-1.1-insurance-card-scanning.md)*
