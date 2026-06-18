# Recipe 11.10 Architecture and Implementation: Clinical Trial Recruitment Conversationalist

*Companion to [Recipe 11.10: Clinical Trial Recruitment Conversationalist](chapter11.10-clinical-trial-recruitment-conversationalist). This page covers the AWS architecture, services, prerequisites, and pseudocode. For the problem framing and the conceptual approach, start with the main recipe.*

---

## The AWS Implementation

### Why These Services

<!-- TODO (TechWriter): Expert review C1 (CRITICAL), A1 (CRITICAL), and S1 (CRITICAL). Author the Why These Services section. Anticipated service rationale: Bedrock Agents for tool-orchestration; Bedrock Knowledge Bases for IRB-approved-content RAG; OpenSearch Serverless for vector and lexical retrieval; DynamoDB for per-trial state, prescreen state, and recruitment-funnel-instrumentation; Step Functions for trial-state-and-amendment workflows; Lambda for the per-stage compute; SQS for the coordinator-handoff queue with throughput control; EventBridge for trial-state-change events; Connect and/or Pinpoint for SMS/voice channels; Comprehend Medical optional for de-identification of free-text patient-reported information; Bedrock Guardrails for recruitment-specific denied topics. Follow the chapter 11 pattern from recipes 11.6 through 11.9. -->

<!-- TODO (TechWriter): Expert review M1 (MEDIUM). Add a sentence naming 21 CFR Part 11 electronic-record-and-signature requirements as applicable to the recruitment-platform's audit trail when the trial is FDA-regulated. Suggested wording: "Where the trial is FDA-regulated, the assistant's recruitment material is part of the IND or IDE record, and the recruitment platform's audit trail is subject to 21 CFR Part 11 electronic-record-and-signature requirements." -->

---

### Architecture Diagram

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Author the Architecture Diagram as a Mermaid flowchart with explicit per-trial-isolation boundaries and the IRB-approved-content corpus as a separately-stored, separately-keyed asset class. -->

---

### Prerequisites

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Author the Prerequisites table: AWS Services, IAM Permissions, BAA, Encryption, VPC, CloudTrail, Sample Data, Cost Estimate. -->

<!-- TODO (TechWriter): Expert review N1 (CRITICAL). VPC topology, VPC-endpoint posture, egress posture, and TLS-in-transit configuration. Anticipated guidance: VPC endpoints for Bedrock, Bedrock Agents, Bedrock Knowledge Bases, S3, DynamoDB, Secrets Manager, Step Functions, KMS, CloudWatch Logs, Comprehend Medical, Connect, Pinpoint; TLS 1.2 minimum (1.3 preferred) at every external boundary; ClinicalTrials.gov integration over public TLS with no PHI on the outbound path; WAF in front of the chat endpoint with managed rule sets for SQL-injection, XSS, prompt-injection-pattern detection, and rate-limiting. -->

---

### Ingredients

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Author the Ingredients table (per-service role). -->

---

### Pseudocode Walkthrough

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Author the Pseudocode Walkthrough. The 10-step decomposition should match the Python companion's existing structure (which already implements all 10 steps end-to-end). -->

<!-- TODO (TechWriter): Expert review S2 (HIGH, anticipated). Follow through on research-data-as-distinct-record-class with separately-keyed buckets for the IRB-approved-content corpus, recruitment-conversation archive, prescreen-result store, coordinator-handoff queue, recruitment-funnel-instrumentation store, and diversity-action-plan-tracking store, with separate IAM principals scoped to research-data access (research-data-officer, sponsor-recruitment-team, IRB-inspector audit-only role, principal-investigator role, coordinator-team role) versus clinical-care principals. Cross-class read paths must be explicitly disallowed at the IAM-policy level. -->

<!-- TODO (TechWriter): Expert review S3 (HIGH, anticipated). Specify Part-11-compliant audit logging, electronic-signature workflows for IRB-approved-content version sign-off, and inspection-ready audit-trail export for FDA-regulated trials. The recruitment platform's audit trail is part of the IND/IDE record under 21 CFR Part 11. -->

<!-- TODO (TechWriter): Expert review M6 (MEDIUM). Explicitly distinguish "interest captured" (allowed; non-consent) from "consent collected" (not allowed; coordinator-only) at the architecture level, following through on the main recipe's correct framing in "It is not the informed consent process". -->

<!-- TODO (TechWriter): Expert review M8 (MEDIUM). Specify recipe-distinct acuity-classifier extensions for recruitment-specific scenarios: prospective participants who surface decompensating symptoms; prospective participants who report a recent condition change during eligibility prescreen; prospective participants whose conversation surfaces psychosocial crisis the recruitment platform is not equipped to handle. -->

<!-- TODO (TechWriter): Expert review M9 (MEDIUM). Specify the out-of-scope routing rules in table form: clinical questions about existing care to patient's care team; requests for medical advice to institutional patient-services line; requests to enroll without prescreen to coordinator team; attempts to recruit in violation of IRB-approved process to research-compliance office; emergencies to 911. -->

<!-- TODO (TechWriter): Expert review V4 (LOW). Make explicit that the IRB-approved disclosure copy itself is authored separately and reviewed by the IRB, not generated by the LLM. The architecture should treat the disclosure surface as IRB-approved content (like the recruitment-FAQ corpus) rather than as LLM-generated text. -->

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter11.10-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

### Expected Results

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Author the Expected Results section with sample JSON output and performance benchmarks table. -->

---

## Why This Isn't Production-Ready

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Author the Why This Isn't Production-Ready section. -->

---

## Variations and Extensions

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Author Variations and Extensions: 2-3 practical extensions (suggested: pediatric-recruitment with assent-and-parental-permission identity model; multilingual recruitment with culturally-appropriate content and community-research-engagement-team review; decentralized-trial recruitment with home-visit-and-telehealth visit-schedule communication). -->

---

## Additional Resources

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Author Additional Resources section. Include: ClinicalTrials.gov, FDA 2022 draft guidance / 2024 final guidance on Diversity Action Plans, FDORA, ICH E6 GCP, 21 CFR Part 11, 21 CFR Part 50, 45 CFR 46, AWS HealthLake, Bedrock, Bedrock Agents, Bedrock Knowledge Bases, AWS HIPAA Eligible Services list, AWS Solutions Library healthcare entries. -->

---

## Estimated Implementation Time

<!-- TODO (TechWriter): Expert review C1 (CRITICAL). Author the Estimated Implementation Time table with Basic / Production-ready / With variations tiers. -->

---

*← [Main Recipe 11.10](chapter11.10-clinical-trial-recruitment-conversationalist) · [Python Example](chapter11.10-python-example) · [Chapter Preface](chapter11-preface)*
