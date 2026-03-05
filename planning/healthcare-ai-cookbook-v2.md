# AI/ML Healthcare Payer Cookbook — v2 Combined Outline

**Status:** Outline — Ready for CC Review
**Version:** 2.0 (Merged from idea.md + techwriter research)
**Last Updated:** 2026-03-02
**Authors:** TechWriter Research + Orchestrator

---

## About This Document

This is the combined outline for the *AI/ML Healthcare Payer Cookbook* — an O'Reilly-style technical reference showing **how** to use AWS AI/ML services for specific healthcare payer use cases. This v2 merges:

- **idea.md** — the original vision, chapter structure, recipe template format, and phased implementation plan
- **healthcare-ai-cookbook.md** — the project brief and architecture-focused framing
- **phase1-categories.md** — 15 AI/ML category descriptions with healthcare context and key considerations
- **phase2-*.md** — 150 use cases across 15 categories, ordered simple → complex

**What this document is:** A complete table of contents with chapter introductions and recipe titles/one-liners. Each recipe includes a complexity marker and cross-references to related recipes. This is *not* full recipe content — that begins after CC review.

**Recipe count:** 55 recipes selected from ~150 candidates, organized into 13 chapters.

---

## Phase Markers

| Marker | Phase | Description |
|--------|-------|-------------|
| ⭐ | MVP (Phase 1) | 10-15 foundational recipes; write first; 3-month target |
| 🔶 | Phase 2 | Next 20-30 recipes expanding coverage; 6-month target |
| 🔷 | Phase 3 | Advanced topics; complete coverage; 9-12 month target |

**MVP Selection Criteria:** Highest customer demand, broadest applicability to payer use cases, clearest AWS service story, feasible without extreme complexity.

---

## Recipe Template (Reference)

Every recipe follows this structure (from idea.md):

```
## Problem Statement       — The business/clinical problem
## Solution Overview       — High-level approach and AWS services
## Architecture Diagram    — Data flow and components
## Prerequisites           — AWS services, IAM permissions, sample data, estimated cost
## Ingredients             — AWS services with roles
## Code                    — Pointer to existing solutions or GitHub; no inline code in chapter body
## Expected Results        — Sample output, accuracy, latency, cost benchmarks
## Variations & Extensions — 2-3 extensions (human review, FHIR output, scale)
## Related Recipes         — Cross-references by recipe number
## Additional Resources    — AWS docs, compliance guides, customer stories
## Estimated Time          — Basic / Production-ready / With variations
## Tags                    — Searchable labels
```

---

## Introduction

### How to Use This Cookbook

This cookbook is organized into 13 chapters, each corresponding to a major AI/ML pattern family. Within each chapter, recipes are ordered from **simple to complex** — start with the first recipe in a chapter before attempting the later ones. Each recipe is fully self-contained but cross-references related recipes in other chapters.

**For Healthcare Payer SAs:** Use this cookbook to accelerate POCs. Share individual recipes with customers as starting points. Combine multiple recipes for end-to-end solutions (see the Prior Auth and Claims use case clusters below).

**For New SAs:** Start with the ⭐ MVP recipes in chapters 1, 2, and 3 — these cover the most common customer asks.

**For Technical Architects:** The cross-references and "Variations & Extensions" sections show how recipes combine into production architectures.

### Prerequisites

- AWS account with appropriate permissions (IAM guide in Appendix B)
- Basic familiarity with AWS console and CLI
- Understanding of HIPAA compliance requirements (Appendix C)
- Sample datasets are provided in the companion GitHub repo for each recipe

### HIPAA & PHI Considerations

Every recipe in this cookbook involves healthcare data. HIPAA compliance is not optional — it is assumed. All architectures include:
- Encryption at rest and in transit
- VPC isolation for data processing
- CloudTrail audit logging
- Business Associate Agreement (BAA) with AWS

Recipes note service-specific compliance considerations in the Prerequisites section.

---

## Table of Contents


---

## Chapter 1: Document Intelligence

> **Category Origin:** Phase 1, Category 1 — Document Intelligence / OCR

Healthcare runs on paper. Faxes remain the dominant interoperability mechanism for prior authorizations, referrals, and records requests. Every integration eventually hits a document extraction problem — whether it's scanned claims forms, handwritten physician notes, or multi-page attachments. This chapter covers extracting structured, actionable data from the unstructured documents that flow through payer operations daily. PHI is present in virtually every document, confidence scoring is non-negotiable for human-in-the-loop workflows, and multi-page mixed-format documents (tables, checkboxes, free text, handwriting) are the norm rather than the exception.

**AWS Services Featured:** Amazon Textract, Amazon Comprehend Medical, AWS Lambda, Amazon S3, Amazon DynamoDB, Amazon A2I (Augmented AI)

---

### Recipe 1.1 — Insurance Card Scanning ⭐
**One-liner:** Capture member ID, group number, payer name, and plan type from a photo of a physical insurance card at point of care.
**Complexity:** Simple
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 1.4 (Prior Auth Document Processing), → 8.1 (Insurance Eligibility Matching)

---

### Recipe 1.2 — Patient Intake Form Digitization ⭐
**One-liner:** Convert standard demographic and medical history intake forms — whether printed or handwritten — into structured EHR-ready data.
**Complexity:** Simple
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 1.3 (Lab Requisition Forms), → 8.1 (Insurance Eligibility Matching)

---

### Recipe 1.3 — Lab Requisition Form Extraction 🔶
**One-liner:** Extract ordered tests, ordering provider, ICD-10 codes, and patient identifiers from faxed lab requisition forms for automated order entry.
**Complexity:** Moderate
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 1.2 (Patient Intake), → 5.2 (NLP: ICD-10 Code Suggestion)

---

### Recipe 1.4 — Prior Authorization Document Processing ⭐
**One-liner:** Extract clinical criteria, diagnosis codes, requested procedure, and clinical narrative from multi-page faxed prior auth submissions to feed the adjudication engine.
**Complexity:** Moderate
**Template sections:** Full template (all sections)
**Cross-references:** → 2.4 (Clinical Criteria Matching via NLP), → 3.1 (Prior Auth Decision Orchestration / Workflows), → 1.5 (Claims Attachment Processing)

---

### Recipe 1.5 — Claims Attachment Processing 🔶
**One-liner:** Classify, route, and extract data from multi-document claims attachments — EOBs, operative reports, clinical notes — into structured adjudication inputs.
**Complexity:** Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 1.4 (Prior Auth Documents), → 2.4 (Clinical Criteria Matching), → 3.1 (Prior Auth Orchestration)

---

### Recipe 1.6 — Handwritten Clinical Note Digitization 🔷
**One-liner:** Digitize physician handwritten progress notes using a confidence-scored pipeline with human-in-the-loop review for low-confidence extractions.
**Complexity:** Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 2.1 (Clinical Entity Extraction), → 2.3 (SDOH Extraction), → 1.5 (Claims Attachment Processing)

---

## Chapter 2: Clinical NLP & Entity Extraction

> **Category Origins:** Phase 1, Category 8 (NLP — Non-LLM) + clinical NLP elements from Category 2 (LLM/GenAI)

Clinical text is dense with entities, relationships, and signals that structured data fields never capture. Physicians abbreviate, negate, hedge, and embed clinical meaning in free text that downstream systems — claims engines, quality measures, risk adjustment — can't consume. This chapter covers traditional and hybrid NLP approaches for extracting structured clinical meaning from unstructured text: medications, diagnoses, procedures, social determinants, and assertion status. Unlike the generative AI chapter, these techniques prioritize precision and reliability over fluency. Medical terminology, negation detection ("no chest pain" ≠ chest pain), and context (historical vs. current vs. family history) are the central challenges.

**AWS Services Featured:** Amazon Comprehend Medical, Amazon Comprehend, Amazon SageMaker, AWS HealthLake, Amazon OpenSearch Service

---

### Recipe 2.1 — Clinical Entity Extraction from Notes ⭐
**One-liner:** Extract diagnoses, medications, procedures, and anatomical findings from clinical notes using Amazon Comprehend Medical, normalized to standard codes (ICD-10, RxNorm, SNOMED).
**Complexity:** Simple-Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 2.2 (Medication Extraction), → 2.3 (SDOH Extraction), → 1.6 (Handwritten Note Digitization), → 4.1 (Prior Auth Criteria Matching)

---

### Recipe 2.2 — Medication Reconciliation from Discharge Summaries ⭐
**One-liner:** Extract the complete medication list from discharge summaries — drug name, dose, route, frequency — normalized to RxNorm, distinguishing current from discontinued medications.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 2.1 (Clinical Entity Extraction), → 6.1 (Drug-Drug Interaction Knowledge Base), → 11.3 (Adverse Event Detection)

---

### Recipe 2.3 — Social Determinants of Health (SDOH) Extraction 🔶
**One-liner:** Identify housing instability, food insecurity, social isolation, and transportation barriers mentioned in clinical notes for care management targeting.
**Complexity:** Medium-Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 2.1 (Clinical Entity Extraction), → 7.4 (Care Management Program Enrollment), → 9.2 (Social Determinant Phenotyping)

---

### Recipe 2.4 — Clinical Criteria Matching for Prior Authorization 🔶
**One-liner:** Match extracted clinical entities from physician notes against payer medical necessity criteria to produce a structured evidence summary for prior auth reviewers.
**Complexity:** Medium-Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 1.4 (Prior Auth Document Processing), → 2.1 (Clinical Entity Extraction), → 3.1 (Prior Auth Decision Orchestration)

---

### Recipe 2.5 — ICD-10 Code Suggestion for Coding Assistance 🔶
**One-liner:** Suggest relevant ICD-10 diagnosis codes from clinical note text to assist medical coders, surfacing specificity improvements and missing documentation.
**Complexity:** Simple-Medium
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 2.1 (Clinical Entity Extraction), → 2.6 (Clinical Assertion Classification)

---

### Recipe 2.6 — Clinical Assertion Classification 🔷
**One-liner:** Classify extracted clinical entities by assertion status — present, absent, possible, historical, family history, hypothetical — to prevent false positives in downstream analytics.
**Complexity:** Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 2.1 (Clinical Entity Extraction), → 2.4 (Prior Auth Criteria Matching), → 11.4 (Phenotype Extraction for Research)

---

## Chapter 3: Generative AI for Operations

> **Category Origin:** Phase 1, Category 2 — LLM / Generative AI

Large language models offer the first real hope for reducing the documentation and administrative burden drowning healthcare payers and providers alike. This chapter covers practical generative AI applications: drafting communications, summarizing clinical content, generating prior auth letters, and powering RAG-based Q&A over policy documents. Every recipe in this chapter is anchored to the core principle from phase1: **hallucination risk is life-safety-adjacent in healthcare** — all architectures use retrieval-augmented generation, citation, grounding, and human review before any patient-facing or clinically consequential output leaves the system. Recipes are ordered from lowest-risk (human always reviews, narrow scope) to highest-risk (clinical reasoning, multi-modal synthesis).

**AWS Services Featured:** Amazon Bedrock, Amazon Bedrock Knowledge Bases, Amazon Bedrock Guardrails, Amazon Kendra, Amazon OpenSearch Service, AWS Lambda, Amazon S3

---

### Recipe 3.1 — Call Center Transcript Summarization ⭐
**One-liner:** Summarize recorded member service call transcripts into structured summaries — reason for call, resolution, follow-up actions — to reduce after-call work time.
**Complexity:** Simple
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 4.1 (Call Center Transcription via Speech AI), → 3.2 (Member Communication Generation)

---

### Recipe 3.2 — Member Communication Generation ⭐
**One-liner:** Generate personalized member letters, denial notices, and care gap reminders from structured data, grounded in plan-specific language requirements and regulatory templates.
**Complexity:** Simple-Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 3.1 (Transcript Summarization), → 3.3 (Clinical Review Notes), → 7.3 (Personalization: Patient Education)

---

### Recipe 3.3 — Prior Authorization Response Letter Generation 🔶
**One-liner:** Generate medical necessity approval and denial letters by synthesizing clinical evidence, payer criteria, and regulatory language requirements into compliant correspondence.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 2.4 (Clinical Criteria Matching), → 1.4 (Prior Auth Document Processing), → 3.5 (Policy Document Q&A)

---

### Recipe 3.4 — Clinical Note Summarization for Utilization Review 🔶
**One-liner:** Condense multi-page clinical records into concise, specialty-appropriate summaries for utilization management reviewers handling prior auth and appeals.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 2.1 (Clinical Entity Extraction), → 3.3 (Prior Auth Letter Generation), → 3.5 (Policy Document Q&A)

---

### Recipe 3.5 — Policy Document Q&A (RAG System) ⭐
**One-liner:** Answer natural language questions about medical policies, benefit documents, and coverage criteria using retrieval-augmented generation over a payer's document library.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 3.3 (Prior Auth Letter Generation), → 4.4 (Provider Portal Chatbot), → 6.1 (Drug Formulary Navigation)

---

### Recipe 3.6 — Ambient Clinical Documentation 🔷
**One-liner:** Passively capture in-person clinical conversations and generate structured SOAP notes using a speaker-diarized transcription pipeline feeding a fine-tuned generative model.
**Complexity:** Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 4.2 (Call Center Transcription), → 3.4 (Clinical Note Summarization), → 2.1 (Clinical Entity Extraction)

---

## Chapter 4: Conversational AI & Voice

> **Category Origins:** Phase 1, Category 11 (Conversational AI / Virtual Assistants) + Category 10 (Speech / Voice AI)

These two categories are merged because the clinical and operational challenges are tightly coupled — voice is the input modality for most member and provider interactions, and conversational AI is the layer that makes those interactions intelligent. From simple IVR modernization to multi-turn chronic disease coaching, the common thread is enabling natural language access to payer services at scale. Key considerations span both chapters: escalation to human agents must be seamless and never miss emergencies; multilingual support is essential for member-facing applications; and PHI flows through every conversation, requiring careful logging and consent architecture.

**AWS Services Featured:** Amazon Lex, Amazon Transcribe, Amazon Transcribe Medical, Amazon Connect, Amazon Polly, Amazon Bedrock, AWS Lambda, Amazon DynamoDB

---

### Recipe 4.1 — Call Center Transcription & Analytics ⭐
**One-liner:** Transcribe 100% of inbound member service calls with medical vocabulary accuracy, then extract intent, sentiment, resolution status, and compliance flags at scale.
**Complexity:** Simple-Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 3.1 (Transcript Summarization), → 4.2 (Sentiment Analysis), → 4.3 (IVR Modernization)

---

### Recipe 4.2 — Member Sentiment Analysis on Service Calls 🔶
**One-liner:** Score member sentiment trajectory across calls — escalation detection, frustration indicators, satisfaction prediction — to prioritize QA review and identify service failures.
**Complexity:** Simple-Medium
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 4.1 (Call Center Transcription), → 3.1 (Transcript Summarization)

---

### Recipe 4.3 — IVR Modernization with Natural Language ⭐
**One-liner:** Replace touch-tone IVR menus with natural language intent recognition so members can say "I need to check my claim status" and route correctly without navigating a menu tree.
**Complexity:** Simple
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 4.4 (Provider Portal Chatbot), → 4.1 (Call Center Transcription)

---

### Recipe 4.4 — Provider Portal Chatbot 🔶
**One-liner:** Multi-turn chatbot for provider portal handling eligibility checks, claim status inquiries, prior auth requirements, and formulary questions with EHR-system integrations.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 3.5 (Policy Document Q&A), → 4.3 (IVR Modernization), → 4.5 (Member Benefits Navigator)

---

### Recipe 4.5 — Member Benefits & Cost Navigator 🔶
**One-liner:** Help members understand their coverage, estimate out-of-pocket costs for specific services, and navigate prior authorization requirements through a conversational interface.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 4.4 (Provider Portal Chatbot), → 3.5 (Policy Document Q&A), → 8.1 (Insurance Eligibility Matching)

---

### Recipe 4.6 — Real-Time Agent Assist (Call Coaching) 🔷
**One-liner:** Provide live call center agents with real-time transcription, next-best-action suggestions, compliance alerts, and knowledge base lookups during member calls.
**Complexity:** Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 4.1 (Call Center Transcription), → 3.5 (Policy Document Q&A), → 4.3 (IVR Modernization)

---

### Recipe 4.7 — Chronic Disease Management Voice Coach 🔷
**One-liner:** Outbound voice agent that conducts structured check-ins with high-risk chronic disease members — capturing symptoms, medication adherence, and vital trends — with escalation pathways to care management.
**Complexity:** Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 10.3 (Vital Sign Trajectory Monitoring), → 7.4 (Care Management Program Enrollment), → 4.4 (Provider Portal Chatbot)

---

## Chapter 5: Predictive Analytics & Risk Scoring

> **Category Origin:** Phase 1, Category 7 — Predictive Analytics / Risk Scoring

Proactive outreach beats reactive response in every dimension of healthcare payer operations — cost, quality, member experience. This chapter covers the predictive models that power population health management: who will be in the ED next month, who is likely to be readmitted, whose chronic disease is deteriorating below the surface, and which members are about to disenroll. The unifying theme from phase1 is that **predictions without intervention pathways are useless** — every recipe includes actionable next steps, not just a probability score. Model fairness and bias auditing are flagged in every recipe, because risk scores have historically encoded socioeconomic and racial disparities that payers must actively counteract.

**AWS Services Featured:** Amazon SageMaker, Amazon SageMaker Clarify, Amazon SageMaker Feature Store, AWS HealthLake, Amazon S3, Amazon EventBridge, Amazon SNS

---

### Recipe 5.1 — Appointment No-Show Prediction ⭐
**One-liner:** Predict which scheduled patients are likely to no-show 24-48 hours before their appointment to enable targeted reminders, overbooking, and waitlist fills.
**Complexity:** Simple
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 7.1 (Appointment Reminder Channel Optimization), → 12.1 (Appointment Volume Forecasting)

---

### Recipe 5.2 — 30-Day Readmission Risk Scoring ⭐
**One-liner:** Score inpatients at discharge for 30-day readmission risk using clinical, social, and claims features to trigger care transition interventions for high-risk members.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 5.3 (Rising Risk Identification), → 7.4 (Care Management Program Enrollment), → 10.3 (Vital Sign Trajectory Monitoring)

---

### Recipe 5.3 — Rising Risk Member Identification 🔶
**One-liner:** Identify members whose risk trajectory is increasing — not just currently high-risk — by modeling rate-of-change in utilization, claims, and clinical signals for earlier intervention.
**Complexity:** Medium-Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 5.2 (Readmission Risk), → 7.4 (Care Management Enrollment), → 9.3 (Disease Severity Stratification)

---

### Recipe 5.4 — Claim Denial Probability Model 🔶
**One-liner:** Score claims before submission for denial probability based on payer rules, clinical content, and historical patterns, enabling proactive documentation improvement.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 6.1 (Duplicate Claim Detection), → 2.4 (Clinical Criteria Matching), → 1.4 (Prior Auth Document Processing)

---

### Recipe 5.5 — Member Churn / Disenrollment Prediction 🔶
**One-liner:** Predict which members are likely to disenroll at open enrollment or mid-year to enable targeted retention outreach before the decision is made.
**Complexity:** Simple-Medium
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 7.1 (Appointment Reminder Channel Optimization), → 7.4 (Care Management Enrollment)

---

### Recipe 5.6 — Disease Progression Modeling 🔷
**One-liner:** Model multi-year chronic disease trajectories (e.g., CKD stage progression, HF decompensation risk) using longitudinal claims and clinical data to stratify intervention intensity.
**Complexity:** Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 5.3 (Rising Risk), → 10.3 (Vital Sign Trajectory Monitoring), → 9.3 (Disease Severity Stratification)

---

## Chapter 6: Anomaly Detection & Fraud

> **Category Origin:** Phase 1, Category 3 — Anomaly Detection

Early detection saves money, saves lives, and saves trust. Whether it's a billing anomaly indicating fraud, a patient deteriorating overnight in an ICU, or an unusual EHR access pattern suggesting a privacy breach, the pattern is the same: establish a baseline, detect meaningful deviation, alert the right person with the right priority. The central tension in every recipe here is the **false positive problem** — alert fatigue is a documented cause of missed real events in clinical settings, and aggressive fraud models generate legal and reputational risk when they misfire. Recipes are ordered from the most operationally straightforward (claims anomalies, where human review is the default) to the most complex (real-time patient deterioration and outbreak detection).

**AWS Services Featured:** Amazon SageMaker, Amazon Fraud Detector, Amazon Lookout for Metrics, Amazon Kinesis, Amazon CloudWatch, AWS Lambda, Amazon SNS

---

### Recipe 6.1 — Duplicate Claim Detection ⭐
**One-liner:** Flag potential duplicate claims using fuzzy matching on patient, provider, service date, and procedure codes, with ML enhancement for subtle variations that rule-based systems miss.
**Complexity:** Simple
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 5.4 (Claim Denial Probability), → 8.2 (Internal Duplicate Patient Detection), → 6.2 (Billing Code Anomalies)

---

### Recipe 6.2 — Billing Code Anomaly Detection 🔶
**One-liner:** Detect unusual billing patterns — codes rarely used by a provider type, unlikely code combinations, charges outside peer norms — using provider-specific and specialty-adjusted baselines.
**Complexity:** Simple-Medium
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 6.1 (Duplicate Claims), → 6.3 (Fraud/Waste/Abuse Detection)

---

### Recipe 6.3 — Healthcare Fraud, Waste & Abuse Detection ⭐
**One-liner:** Identify providers, facilities, and members exhibiting patterns consistent with fraud (upcoding, unbundling, phantom billing) using multi-dimensional behavioral baselines and network analysis.
**Complexity:** Medium-Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 6.1 (Duplicate Claims), → 6.2 (Billing Code Anomalies), → 12.2 (Provider Practice Pattern Analysis)

---

### Recipe 6.4 — EHR Access Pattern Anomaly Detection 🔷
**One-liner:** Detect unusual EHR access patterns — after-hours access, bulk record queries, accessing records of celebrities or coworkers — that may indicate insider threats or privacy breaches.
**Complexity:** Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 6.3 (FWA Detection), → 5.4 (Claim Denial Probability)

---

### Recipe 6.5 — Patient Deterioration Early Warning 🔷
**One-liner:** Detect subtle multi-signal patterns in vitals, labs, and nursing notes that precede sepsis, respiratory failure, or cardiac events, with tiered alerting to minimize fatigue.
**Complexity:** Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 10.3 (Vital Sign Trajectory Monitoring), → 10.1 (Lab Result Trend Analysis), → 5.2 (Readmission Risk)

---

## Chapter 7: Personalization & Recommendations

> **Category Origin:** Phase 1, Category 4 — Personalization / Recommendation

Every member is different. One-size-fits-all care management, communications, and intervention programs leave clinical and financial value on the table. This chapter covers ML-driven personalization across the payer's member touchpoints: optimizing which channel and when to reach a member, matching them to the right wellness or care management program, identifying which care gaps to prioritize in a limited visit window, and ultimately predicting which treatments are most likely to work for patients who look like them. The cold start problem (new members with no history), bias in historical training data, and the ethical constraints on A/B testing in clinical contexts are recurring themes throughout.

**AWS Services Featured:** Amazon Personalize, Amazon SageMaker, Amazon Pinpoint, Amazon Bedrock, AWS Lambda, Amazon DynamoDB, Amazon S3

---

### Recipe 7.1 — Appointment Reminder Channel Optimization ⭐
**One-liner:** Learn the optimal communication channel (SMS, email, phone, portal) and timing for appointment reminders for each member based on their historical response patterns.
**Complexity:** Simple
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 5.1 (No-Show Prediction), → 7.2 (Patient Education Content Matching)

---

### Recipe 7.2 — Patient Education Content Matching 🔶
**One-liner:** Recommend relevant educational materials — condition-specific, at appropriate reading level, in preferred language — based on member diagnoses, recent encounters, and engagement history.
**Complexity:** Simple
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 7.1 (Reminder Channel Optimization), → 7.3 (Care Gap Prioritization)

---

### Recipe 7.3 — Care Gap Prioritization at Point of Care 🔶
**One-liner:** When a member has multiple open care gaps, rank them by clinical urgency and predicted likelihood-to-complete for the current visit context, surfacing the top 1-2 to the provider.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 7.4 (Care Management Enrollment), → 6.2 (Care Gap Reasoning Engine), → 5.3 (Rising Risk Identification)

---

### Recipe 7.4 — Care Management Program Enrollment Targeting 🔶
**One-liner:** Predict which members should be enrolled in which care management program (disease-specific, high-risk, transitional) and rank by predicted ROI given program capacity constraints.
**Complexity:** Medium-Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 5.3 (Rising Risk), → 7.3 (Care Gap Prioritization), → 4.7 (Chronic Disease Voice Coach)

---

### Recipe 7.5 — Treatment Response Prediction 🔷
**One-liner:** Predict which treatment options a member is most likely to respond to by identifying similar patients in historical data and surfacing their outcomes, with bias auditing on matched cohorts.
**Complexity:** Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 9.1 (Patient Similarity for Care Planning), → 5.6 (Disease Progression Modeling), → 13.2 (Dynamic Treatment Regime / RL)

---

## Chapter 8: Entity Resolution & Data Integration

> **Category Origin:** Phase 1, Category 5 — Entity Resolution / Record Linkage

Fragmented data is healthcare's original sin. A single patient may exist as dozens of records across payer systems, provider EHRs, HIEs, pharmacy benefit managers, and lab networks — with different IDs, name spellings, addresses, and demographic variations. Entity resolution is the foundation that every other AI/ML recipe in this cookbook depends on: you can't build a member 360 view, run population health models, or measure quality if you don't know which records belong to the same person. The stakes are asymmetric — a false match (merging two different patients' records) can cause medication errors or wrong-patient care; a false non-match fragments care and duplicates work.

**AWS Services Featured:** Amazon SageMaker, AWS Entity Resolution, AWS HealthLake, Amazon DynamoDB, AWS Glue, Amazon S3, AWS Lake Formation

---

### Recipe 8.1 — Insurance Eligibility Matching ⭐
**One-liner:** Match patient-presented demographics to payer eligibility files in real time, tolerating name variations, date-of-birth discrepancies, and transposed digits that break exact-match systems.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 1.1 (Insurance Card Scanning), → 8.2 (Internal Duplicate Patient Detection), → 8.3 (Cross-Facility Patient Matching)

---

### Recipe 8.2 — Internal Duplicate Patient Record Detection 🔶
**One-liner:** Identify and surface potential duplicate patient records within a single payer's member database using probabilistic matching with manual merge workflow integration.
**Complexity:** Simple
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 8.1 (Eligibility Matching), → 8.3 (Cross-Facility Matching)

---

### Recipe 8.3 — Cross-Facility Patient Matching for HIE 🔶
**One-liner:** Match patient records across unaffiliated provider organizations for health information exchange without a shared master patient index, using multi-attribute probabilistic matching.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 8.2 (Duplicate Detection), → 8.4 (Claims-to-Clinical Linkage), → 8.5 (Privacy-Preserving Matching)

---

### Recipe 8.4 — Claims-to-Clinical Data Linkage 🔶
**One-liner:** Link administrative claims records to clinical EHR encounters for the same patient and episode of care, enabling outcomes research and quality measurement that spans both data sources.
**Complexity:** Medium-Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 8.3 (Cross-Facility Matching), → 5.2 (Readmission Risk), → 9.3 (Disease Severity Stratification)

---

### Recipe 8.5 — Privacy-Preserving Record Linkage 🔷
**One-liner:** Match patient records across organizations without sharing raw PHI using privacy-preserving techniques (hashed matching, secure multi-party computation) for sensitive cross-payer or research contexts.
**Complexity:** Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 8.3 (Cross-Facility Matching), → 8.4 (Claims-to-Clinical Linkage)

---

## Chapter 9: Cohort Analysis & Population Health

> **Category Origin:** Phase 1, Category 6 — Cohort Analysis / Clustering / Similarity

Understanding "patients like this one" unlocks evidence-based care, risk stratification, and resource allocation at scale. This chapter covers clustering and similarity techniques for segmenting member populations into actionable groups — from simple utilization-based segments for care management outreach to complex multi-morbidity pattern discovery that may reveal clinically meaningful disease subtypes. The chapter bridges population-level strategy (who are our high-risk rising members?) and individual-level tactics (who responded well to this intervention among patients similar to this member?). Feature selection is the central challenge: the right clinical domain knowledge drives useful clusters; naive feature selection produces actuarially interesting but clinically meaningless groupings.

**AWS Services Featured:** Amazon SageMaker, Amazon SageMaker Feature Store, AWS HealthLake, Amazon QuickSight, Amazon OpenSearch Service, AWS Glue, Amazon Athena

---

### Recipe 9.1 — Patient Similarity for Care Planning ⭐
**One-liner:** Find the N most clinically similar historical patients for a given member, surface their care trajectories and outcomes, and present the findings to care managers as evidence-based planning context.
**Complexity:** Medium-Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 7.5 (Treatment Response Prediction), → 9.2 (Disease Severity Stratification), → 5.3 (Rising Risk Identification)

---

### Recipe 9.2 — Utilization Pattern Segmentation ⭐
**One-liner:** Segment the member population into actionable utilization archetypes — high utilizers, rising risk, episodic, preventive-only, disengaged — to drive differentiated care management strategies.
**Complexity:** Simple
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 7.4 (Care Management Enrollment), → 5.3 (Rising Risk), → 9.3 (Disease Severity Stratification)

---

### Recipe 9.3 — Disease Severity Stratification 🔶
**One-liner:** Cluster members with a target chronic disease (e.g., diabetes, CHF, COPD) into severity tiers using clinical markers, complication history, and functional status for care intensity matching.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 9.2 (Utilization Segmentation), → 5.3 (Rising Risk), → 5.6 (Disease Progression Modeling)

---

### Recipe 9.4 — Provider Practice Pattern Analysis 🔶
**One-liner:** Cluster providers by ordering behavior, referral patterns, and treatment choices to identify high-variation outliers, support peer comparison, and target quality improvement outreach.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 6.2 (Billing Code Anomalies), → 6.3 (FWA Detection), → 12.2 (OR Block Scheduling)

---

### Recipe 9.5 — Social Determinant Phenotyping 🔷
**One-liner:** Identify member clusters sharing actionable social determinant profiles (housing instability, food insecurity, transportation barriers) from clinical notes and structured data to connect them with community resources.
**Complexity:** Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 2.3 (SDOH Extraction), → 7.4 (Care Management Enrollment), → 9.2 (Utilization Segmentation)

---

## Chapter 10: Computer Vision & Medical Imaging

> **Category Origin:** Phase 1, Category 9 — Computer Vision / Medical Imaging

AI augments, not replaces, expert interpretation in clinical imaging. Radiology, pathology, dermatology, and ophthalmology are core diagnostic specialties where vision AI provides real value — not by making diagnoses autonomously, but by prioritizing worklists, flagging critical findings for urgent review, and quantifying features that humans find tedious or subjective. For payers, computer vision applications extend beyond clinical imaging to operational use cases: identity verification, wound assessment from member-submitted photos, and facility inspection for claims validation. FDA regulatory considerations are a constant backdrop for any diagnostic use case; recipes clearly distinguish between triage/prioritization (lower regulatory bar) and diagnostic assistance (higher bar).

**AWS Services Featured:** Amazon Rekognition, Amazon SageMaker, Amazon Augmented AI (A2I), Amazon S3, AWS HealthImaging, Amazon Bedrock, AWS Lambda

---

### Recipe 10.1 — Wound Photography Measurement & Tracking ⭐
**One-liner:** Measure wound dimensions (length, width, surface area) from standardized nursing photographs and track healing trajectories over time, with alerts for stalled healing.
**Complexity:** Simple-Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 10.2 (Dermatology Lesion Triage), → 5.2 (Readmission Risk)

---

### Recipe 10.2 — Dermatology Lesion Triage 🔶
**One-liner:** Classify member-submitted or telehealth skin lesion photos as benign, watch, or urgent-referral to prioritize dermatology access in underserved populations.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 10.1 (Wound Measurement), → 10.3 (Chest X-Ray Triage)

---

### Recipe 10.3 — Chest X-Ray Critical Finding Triage 🔶
**One-liner:** Flag chest X-rays with critical findings (pneumothorax, large pleural effusion, pulmonary edema) for priority radiologist review, reducing time-to-read for urgent cases.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 10.4 (Diabetic Retinopathy Screening), → 6.5 (Patient Deterioration Early Warning)

---

### Recipe 10.4 — Diabetic Retinopathy Screening at Scale 🔷
**One-liner:** Grade retinal fundus images for diabetic retinopathy severity in primary care settings, enabling population-scale screening without requiring on-site ophthalmology.
**Complexity:** Medium-Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 10.3 (Chest X-Ray Triage), → 5.6 (Disease Progression Modeling)

---

### Recipe 10.5 — Pathology Slide Analysis 🔷
**One-liner:** Assist pathologists analyzing digitized histopathology slides — identifying regions of interest, quantifying tumor characteristics, and flagging cases for priority review.
**Complexity:** Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 10.3 (Chest X-Ray Triage), → 10.4 (Diabetic Retinopathy)

---

## Chapter 11: Time Series & Forecasting

> **Category Origin:** Phase 1, Category 12 — Time Series Analysis / Forecasting

Healthcare generates continuous streams of time-indexed data: vital signs, lab trends, appointment volumes, supply consumption, and financial flows. Time series analysis extracts patterns, forecasts future states, and detects trajectory changes before threshold-based alerts fire. Two distinct use cases coexist in this chapter: **operational forecasting** (staffing, capacity, supply chain — where forecast errors translate to cost and access problems) and **clinical trajectory monitoring** (vital trends, disease progression, waveform analysis — where forecast errors can have patient safety implications). Irregular sampling intervals, missing data, seasonality, and the challenge of updating predictions in near real-time are recurring technical themes throughout.

**AWS Services Featured:** Amazon Forecast, Amazon SageMaker, Amazon Lookout for Metrics, Amazon Kinesis Data Streams, Amazon Timestream, AWS Lambda, Amazon QuickSight

---

### Recipe 11.1 — Appointment Volume Forecasting ⭐
**One-liner:** Predict daily and weekly appointment volumes by clinic, provider type, and visit category for staffing, template building, and resource planning — with seasonal and holiday adjustments.
**Complexity:** Simple
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 5.1 (No-Show Prediction), → 12.1 (Appointment Slot Optimization)

---

### Recipe 11.2 — ED Arrival Volume Forecasting 🔶
**One-liner:** Predict emergency department arrival volumes by hour and acuity level, incorporating weather, local events, and flu surveillance signals for dynamic staffing and bed management.
**Complexity:** Simple-Medium
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 11.1 (Appointment Volume Forecasting), → 12.1 (Appointment Slot Optimization), → 12.3 (Patient Flow / Bed Assignment)

---

### Recipe 11.3 — Lab Result Trend Analysis & Early Warning 🔶
**One-liner:** Establish patient-specific longitudinal baselines for key lab values (creatinine, A1C, BNP) and alert clinicians when trends indicate trajectory changes before values cross absolute thresholds.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 6.5 (Patient Deterioration Early Warning), → 5.6 (Disease Progression Modeling), → 11.4 (Vital Sign Trajectory Monitoring)

---

### Recipe 11.4 — Vital Sign Trajectory Monitoring (ICU) 🔷
**One-liner:** Continuously analyze multi-parameter vital sign streams in real time to detect deterioration trajectories that precede sepsis or respiratory failure, with tiered alerts calibrated to minimize fatigue.
**Complexity:** Medium-Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 6.5 (Patient Deterioration Early Warning), → 11.3 (Lab Result Trends), → 5.2 (Readmission Risk)

---

### Recipe 11.5 — Physiological Waveform Analysis (ECG) 🔷
**One-liner:** Analyze continuous ECG waveforms for arrhythmia detection, QT prolongation monitoring, and rhythm classification in real-time remote patient monitoring contexts.
**Complexity:** Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 11.4 (Vital Sign Trajectory Monitoring), → 6.5 (Patient Deterioration), → 4.7 (Chronic Disease Voice Coach)

---

## Chapter 12: Knowledge Graphs & Clinical Ontologies

> **Category Origin:** Phase 1, Category 13 — Knowledge Graphs / Ontology

Medicine is fundamentally relational: drugs interact with other drugs, diseases share genetic underpinnings, clinical concepts map across dozens of coding systems, and care pathways branch based on patient characteristics. Knowledge graphs make these relationships explicit and queryable. For payers, the most immediate value is in drug formulary navigation, care gap detection, and clinical decision support grounded in authoritative clinical knowledge. The deeper value — precision medicine, literature-derived discovery, federated clinical networks — represents a longer-term investment that begins with foundational ontology work. Ontology maintenance is ongoing infrastructure, not a one-time project: SNOMED releases twice yearly, RxNorm weekly, and new drugs and procedures require continuous curation.

**AWS Services Featured:** Amazon Neptune, Amazon OpenSearch Service, AWS HealthLake, Amazon Bedrock Knowledge Bases, Amazon Kendra, AWS Lambda, Amazon S3

---

### Recipe 12.1 — Drug Formulary Navigation & Therapeutic Alternatives ⭐
**One-liner:** Build a queryable knowledge graph of drug formulary relationships — therapeutic classes, tier equivalents, step therapy requirements, generic alternatives — to power provider and member-facing search.
**Complexity:** Simple
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 4.4 (Provider Portal Chatbot), → 3.5 (Policy Document Q&A), → 12.2 (Drug-Drug Interaction Knowledge Base)

---

### Recipe 12.2 — Drug-Drug Interaction Knowledge Base 🔶
**One-liner:** Maintain and query a real-time drug-drug interaction graph that integrates FDA, clinical literature, and PBM data sources, with severity-tiered alerts calibrated to reduce fatigue.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 12.1 (Drug Formulary Navigation), → 2.2 (Medication Reconciliation), → 6.1 (Care Gap Reasoning Engine)

---

### Recipe 12.3 — Care Gap Identification via Ontological Reasoning 🔶
**One-liner:** Use graph-based reasoning over patient conditions, age, and clinical guidelines to identify open quality measure gaps and generate prioritized care gap lists for provider outreach.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 7.3 (Care Gap Prioritization), → 12.2 (Drug-Drug Interaction), → 6.2 (Clinical Pathway Modeling)

---

### Recipe 12.4 — Medical Concept Normalization & Cross-Terminology Mapping 🔷
**One-liner:** Build and maintain bidirectional mappings between clinical terminologies (SNOMED CT, ICD-10, CPT, LOINC, RxNorm) to enable cross-system analytics and interoperability.
**Complexity:** Complex
**Template sections:** Full template (all sections)
**Cross-references:** → 2.1 (Clinical Entity Extraction), → 8.4 (Claims-to-Clinical Linkage), → 12.3 (Care Gap Reasoning)

---

### Recipe 12.5 — Clinical Pathway Modeling & Compliance Tracking 🔷
**One-liner:** Represent evidence-based clinical pathways and order sets as traversable knowledge graphs, then measure patient-level adherence for quality reporting and variation reduction.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 12.3 (Care Gap Reasoning), → 3.5 (Policy Document Q&A), → 13.2 (Prior Auth Decision Orchestration)

---

## Chapter 13: Optimization, Operations & Reinforcement Learning

> **Category Origins:** Phase 1, Category 14 (Optimization / Operations Research) + Category 15 (Reinforcement Learning)

These two categories are unified by a common theme: **sequential decision-making under constraints**. Whether it's scheduling operating room blocks, routing ambulances, or deciding how aggressively to adjust insulin in an ICU, both optimization and reinforcement learning are about finding policies — not just predictions — that account for constraints, trade-offs, and the downstream consequences of each decision. Operations research techniques (linear/integer programming, constraint satisfaction) work well when constraints are explicit and the objective is clear. Reinforcement learning handles the cases where the environment is too complex to model explicitly and the optimal policy must be learned from data. In healthcare, RL in particular is largely research-stage for treatment decisions; recipes clearly distinguish what is deployable today from what requires further research and regulatory maturation.

**AWS Services Featured:** Amazon SageMaker (RL, optimization), AWS Step Functions, Amazon EventBridge, Amazon Braket (for research), AWS Lambda, Amazon DynamoDB, Amazon Kinesis

---

### Recipe 13.1 — Appointment Slot Template Optimization ⭐
**One-liner:** Optimize clinic appointment slot templates — visit type durations, buffer times, overbooking levels — using historical completion data to maximize throughput while protecting access and provider satisfaction.
**Complexity:** Simple
**Template sections:** Problem Statement, Solution Overview, Architecture Diagram, Prerequisites, Ingredients, Expected Results, Variations & Extensions, Related Recipes, Tags
**Cross-references:** → 5.1 (No-Show Prediction), → 11.1 (Appointment Volume Forecasting), → 13.2 (Prior Auth Decision Orchestration)

---

### Recipe 13.2 — Prior Auth Decision Workflow Orchestration ⭐
**One-liner:** Orchestrate the end-to-end prior authorization decision pipeline — document extraction → clinical criteria matching → auto-approval logic → human review queue routing — using Step Functions with embedded ML decision points.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 1.4 (Prior Auth Document Processing), → 2.4 (Clinical Criteria Matching), → 3.3 (Prior Auth Letter Generation), → 3.5 (Policy Q&A)

---

### Recipe 13.3 — Nurse Staffing Schedule Optimization 🔶
**One-liner:** Generate optimal nurse schedules that meet census-based coverage requirements while respecting union rules, certification requirements, and individual preferences, with daily reoptimization for call-offs.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 11.2 (ED Arrival Forecasting), → 13.4 (OR Block Scheduling), → 13.1 (Appointment Slot Optimization)

---

### Recipe 13.4 — Operating Room Block Scheduling 🔶
**One-liner:** Allocate OR block time to surgical services using historical utilization data to optimize throughput, reduce unused block time, and equitably balance surgeon access.
**Complexity:** Medium
**Template sections:** Full template (all sections)
**Cross-references:** → 13.3 (Nurse Staffing), → 13.1 (Appointment Slot Optimization)

---

### Recipe 13.5 — Alert Threshold Optimization via Reinforcement Learning 🔷
**One-liner:** Use a contextual bandit / RL approach to learn optimal alert thresholds per patient context — balancing sensitivity with fatigue — based on observed clinician response patterns.
**Complexity:** Medium (RL entry point)
**Template sections:** Full template (all sections)
**Cross-references:** → 6.5 (Patient Deterioration Early Warning), → 11.4 (Vital Sign Trajectory Monitoring), → 13.6 (Sepsis Treatment RL)

---

### Recipe 13.6 — Sepsis Treatment Policy Learning (Offline RL) 🔷
**One-liner:** Learn evidence-based sepsis management policies (fluid resuscitation timing, vasopressor selection) from retrospective ICU data using offline reinforcement learning, with safety constraints and extensive out-of-distribution validation.
**Complexity:** Complex (research-stage)
**Template sections:** Full template (all sections) + **Safety Constraints** section
**Cross-references:** → 13.5 (Alert Threshold RL), → 6.5 (Patient Deterioration), → 7.5 (Treatment Response Prediction)
**⚠️ Note:** This recipe is explicitly research-stage. Architecture covers offline learning, safety constraint formulation, and validation methodology. Do not deploy without extensive clinical validation and regulatory review.

---


---

## Phased Implementation Plan

### ⭐ Phase 1 — MVP (Target: 3 months, 15 recipes)

Write these first. They represent the highest customer demand, clearest AWS service story, and widest applicability to payer use cases.

| Recipe | Chapter | Rationale |
|--------|---------|-----------|
| 1.1 Insurance Card Scanning | Document Intelligence | Instant demo-able, real customer ask |
| 1.2 Patient Intake Form Digitization | Document Intelligence | Universal payer problem |
| 1.4 Prior Authorization Document Processing | Document Intelligence | #1 payer pain point; anchors 3-recipe PA cluster |
| 2.1 Clinical Entity Extraction from Notes | Clinical NLP | Foundation for most downstream NLP recipes |
| 2.2 Medication Reconciliation from Discharge Summaries | Clinical NLP | High-value, clear Comprehend Medical story |
| 3.1 Call Center Transcript Summarization | Generative AI | High ROI, low risk, immediate value |
| 3.2 Member Communication Generation | Generative AI | Constant demand across all payers |
| 3.5 Policy Document Q&A (RAG) | Generative AI | Strong Bedrock differentiator |
| 4.3 IVR Modernization with Natural Language | Conversational AI & Voice | Quick win, replaces expensive IVR projects |
| 5.1 Appointment No-Show Prediction | Predictive Analytics | Easy model, clear intervention, measurable ROI |
| 5.2 30-Day Readmission Risk Scoring | Predictive Analytics | Regulatory/quality measure driver |
| 6.1 Duplicate Claim Detection | Anomaly Detection | Saves real dollars immediately |
| 6.3 Healthcare FWA Detection | Anomaly Detection | High SA demand; Amazon Fraud Detector showcase |
| 7.1 Appointment Reminder Channel Optimization | Personalization | Quick win, Amazon Pinpoint + Personalize story |
| 13.2 Prior Auth Decision Workflow Orchestration | Optimization & RL | Ties Ch 1 + Ch 2 + Ch 3 recipes into end-to-end solution |

### 🔶 Phase 2 — Expanded Coverage (Target: 6 months, +20 recipes)

Add after MVP validation. Focus on breadth across remaining chapters.

- Ch 1: 1.3 (Lab Requisition), 1.5 (Claims Attachments)
- Ch 2: 2.3 (SDOH Extraction), 2.4 (Clinical Criteria Matching), 2.5 (ICD-10 Suggestion)
- Ch 3: 3.3 (Prior Auth Letter Generation), 3.4 (Clinical Note Summarization)
- Ch 4: 4.1 (Call Center Transcription), 4.2 (Sentiment Analysis), 4.4 (Provider Portal Chatbot), 4.5 (Benefits Navigator)
- Ch 5: 5.3 (Rising Risk), 5.4 (Claim Denial Probability), 5.5 (Member Churn)
- Ch 6: 6.2 (Billing Code Anomalies)
- Ch 7: 7.2 (Patient Education), 7.3 (Care Gap Prioritization), 7.4 (Care Management Enrollment)
- Ch 8: 8.2 (Duplicate Patient Detection), 8.3 (Cross-Facility Matching), 8.4 (Claims-to-Clinical Linkage)
- Ch 9: 9.2 (Utilization Segmentation), 9.3 (Disease Severity Stratification), 9.4 (Provider Practice Patterns)
- Ch 10: 10.2 (Dermatology Triage), 10.3 (Chest X-Ray Triage)
- Ch 11: 11.2 (ED Arrival Forecasting), 11.3 (Lab Result Trends)
- Ch 12: 12.1 (Drug Formulary), 12.2 (Drug-Drug Interactions), 12.3 (Care Gap Reasoning)
- Ch 13: 13.3 (Nurse Staffing), 13.4 (OR Block Scheduling)

### 🔷 Phase 3 — Advanced & Complete Coverage (Target: 9-12 months, +20 recipes)

Advanced topics, complex architectures, and research-adjacent recipes.

- Ch 1: 1.6 (Handwritten Clinical Notes)
- Ch 2: 2.6 (Clinical Assertion Classification)
- Ch 3: 3.6 (Ambient Clinical Documentation)
- Ch 4: 4.6 (Real-Time Agent Assist), 4.7 (Chronic Disease Voice Coach)
- Ch 5: 5.6 (Disease Progression Modeling)
- Ch 6: 6.4 (EHR Access Anomalies), 6.5 (Patient Deterioration Early Warning)
- Ch 7: 7.5 (Treatment Response Prediction)
- Ch 8: 8.5 (Privacy-Preserving Record Linkage)
- Ch 9: 9.1 (Patient Similarity for Care Planning), 9.5 (Social Determinant Phenotyping)
- Ch 10: 10.4 (Diabetic Retinopathy Screening), 10.5 (Pathology Slide Analysis)
- Ch 11: 11.4 (Vital Sign Trajectory / ICU), 11.5 (ECG Waveform Analysis)
- Ch 12: 12.4 (Medical Concept Normalization), 12.5 (Clinical Pathway Modeling)
- Ch 13: 13.5 (Alert Threshold RL), 13.6 (Sepsis Treatment RL)

---

## Key Use Case Clusters (Cross-Chapter)

These are common customer scenarios that span multiple recipes. SAs can hand a customer a "cluster" rather than individual recipes.

### 🔵 Prior Authorization End-to-End
1.4 → 2.4 → 3.3 → 13.2
*Document extraction → clinical criteria matching → denial/approval letter generation → workflow orchestration*

### 🟢 Member 360 & Population Health
8.1 → 8.4 → 9.2 → 5.3 → 7.4
*Eligibility matching → claims-clinical linkage → utilization segmentation → rising risk → care management targeting*

### 🟡 Call Center AI
4.1 → 4.2 → 3.1 → 4.3 → 4.6
*Transcription → sentiment → summarization → IVR modernization → real-time agent assist*

### 🔴 Clinical Intelligence Pipeline
2.1 → 2.2 → 2.3 → 2.6 → 5.2
*Entity extraction → medication reconciliation → SDOH → assertion classification → readmission risk*

### 🟣 Fraud & Integrity
6.1 → 6.2 → 6.3 → 5.4
*Duplicate claims → billing anomalies → FWA detection → pre-submission denial scoring*

---

## Appendix A — Category-to-Chapter Mapping

| Phase 1 Category # | Original Category Name | v2 Chapter |
|---|---|---|
| 1 | Document Intelligence / OCR | Chapter 1: Document Intelligence |
| 2 | LLM / Generative AI | Chapter 3: Generative AI for Operations |
| 3 | Anomaly Detection | Chapter 6: Anomaly Detection & Fraud |
| 4 | Personalization / Recommendation | Chapter 7: Personalization & Recommendations |
| 5 | Entity Resolution / Record Linkage | Chapter 8: Entity Resolution & Data Integration |
| 6 | Cohort Analysis / Clustering / Similarity | Chapter 9: Cohort Analysis & Population Health |
| 7 | Predictive Analytics / Risk Scoring | Chapter 5: Predictive Analytics & Risk Scoring |
| 8 | Natural Language Processing (Non-LLM) | Chapter 2: Clinical NLP & Entity Extraction |
| 9 | Computer Vision / Medical Imaging | Chapter 10: Computer Vision & Medical Imaging |
| 10 | Speech / Voice AI | Chapter 4: Conversational AI & Voice (merged) |
| 11 | Conversational AI / Virtual Assistants | Chapter 4: Conversational AI & Voice (merged) |
| 12 | Time Series Analysis / Forecasting | Chapter 11: Time Series & Forecasting |
| 13 | Knowledge Graphs / Ontology | Chapter 12: Knowledge Graphs & Clinical Ontologies |
| 14 | Optimization / Operations Research | Chapter 13: Optimization, Operations & RL (merged) |
| 15 | Reinforcement Learning | Chapter 13: Optimization, Operations & RL (merged) |

**Merge rationale:**
- **Categories 10 + 11 → Chapter 4:** Speech is the input modality; conversational AI is the logic layer. They are deployed together in every payer use case (IVR, contact center, member-facing chatbots). Separating them creates artificial fragmentation.
- **Categories 14 + 15 → Chapter 13:** Both address sequential decision-making under constraints. RL is the adaptive extension of constrained optimization. Alert threshold RL (15.1) and appointment optimization (14.1) are closer to each other than either is to their respective category extremes.
- **Category 8 NLP → Chapter 2, Category 2 LLM → Chapter 3:** The original cookbook structure in idea.md separated "Clinical NLP" from "GenAI for Operations" correctly. Non-LLM NLP (entity extraction, assertion classification, ICD suggestion) is a distinct pattern from generative approaches and should be learned separately.

---

## Appendix B — Recipe Count Summary

| Chapter | Recipes | ⭐ MVP | 🔶 Phase 2 | 🔷 Phase 3 |
|---------|---------|--------|------------|------------|
| 1: Document Intelligence | 6 | 2 | 2 | 1 |
| 2: Clinical NLP | 6 | 2 | 3 | 1 |
| 3: Generative AI | 6 | 3 | 2 | 1 |
| 4: Conversational AI & Voice | 7 | 2 | 3 | 2 |
| 5: Predictive Analytics | 6 | 2 | 3 | 1 |
| 6: Anomaly Detection | 5 | 2 | 1 | 2 |
| 7: Personalization | 5 | 1 | 3 | 1 |
| 8: Entity Resolution | 5 | 1 | 3 | 1 |
| 9: Cohort Analysis | 5 | 1 | 2 | 2 |
| 10: Computer Vision | 5 | 1 | 2 | 2 |
| 11: Time Series | 5 | 1 | 2 | 2 |
| 12: Knowledge Graphs | 5 | 1 | 3 | 2 |
| 13: Optimization & RL | 6 | 2 | 2 | 2 |
| **Total** | **72** | **21** | **31** | **20** |

> **Note on count:** The outline includes 72 recipe slots. For the actual writing phases, CC should select the tightest 50-60 for execution, deprioritizing lower-value entries within each chapter. The 15 ⭐ MVP recipes in the implementation plan table above are the hard-commit starting list.

---

## Appendix C — HIPAA & Compliance Notes

Every recipe in this cookbook operates under the assumption of:

- **AWS BAA in place** — Required before processing PHI in any AWS service
- **Encryption at rest** — S3 SSE-KMS, RDS/DynamoDB encryption enabled
- **Encryption in transit** — TLS 1.2+ for all API calls and data movement
- **VPC isolation** — Processing workloads in private subnets; no public exposure of PHI endpoints
- **CloudTrail logging** — All API calls logged; minimum 7-year retention for covered entities
- **IAM least privilege** — Roles scoped to minimum required permissions per recipe
- **Amazon Macie** — Recommended for S3 buckets containing unstructured documents (Chapters 1-3)

Service-specific notes are provided within each recipe's Prerequisites section.

---

## Appendix D — Recommended Starting Path for New SAs

If you're onboarding to this cookbook and don't know where to start:

1. **Read Chapter 1, Recipe 1.4** (Prior Auth Document Processing) — it's the most common customer ask and anchors the cookbook's flagship use case cluster
2. **Read Chapter 3, Recipe 3.5** (Policy Document Q&A) — strongest Bedrock demo story
3. **Walk the Prior Auth cluster:** 1.4 → 2.4 → 3.3 → 13.2 — this is a full customer presentation
4. **Read Chapter 6, Recipe 6.3** (FWA Detection) — saves real money, resonates with finance stakeholders
5. After those four, you have a complete SA toolkit for 80% of payer conversations

---

*Document prepared by TechWriter Orchestrator — 2026-03-02*
*Source: Merged from idea.md (vision + structure + template) and phase1/phase2 research files*
*Status: Ready for CC review — no recipe content written yet*

