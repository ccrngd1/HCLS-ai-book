# Open TODOs — Recipe 10.4: Medical Transcription (Dictation) ⭐⭐

> Auto-extracted 2026-06-18 from inline source comments (34 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter10.04-medical-transcription-dictation.md`

- **L13** — TODO: verify; the most-cited study here is Sinsky et al. 2016 in Annals of Internal Medicine, with various follow-up studies showing the ratio has not improved meaningfully and in some specialties has gotten worse
- **L13** — TODO: verify; physician-burnout literature has strong correlation findings between EHR-documentation burden and burnout, with notable contributors including the National Academy of Medicine, AMA STEPS Forward, and Mayo Clinic Proceedings
- **L19** — TODO: verify; specific U.S. clinician dictation adoption figures continue to evolve and are difficult to pin down precisely; vendor-reported numbers tend to be inflated, but the technology is mainstream in radiology, pathology, surgery, emergency medicine, and large fractions of internal medicine and primary care
- **L27** — TODO: verify; the laterality-mistranscription failure mode is well-documented in radiology informatics literature, with multiple studies showing left-right transcription errors in dictated radiology reports as a persistent quality and patient-safety concern
- **L57** — TODO: verify; medical-domain ASR vendor accuracy claims and independent benchmarks have a wide range; published academic comparisons often show production word error rates in the 4-10% range for clinical dictation depending on speaker, specialty, and acoustic conditions
- **L59** — TODO: verify; clinically-significant-error metrics are emerging in academic and vendor benchmarks but standardization is still in progress; commonly cited frameworks include error categorization by clinical impact tier
- **L75** — TODO: verify; specific Nuance Dragon Medical architecture details are vendor-internal; the hybrid HMM-DNN-with-medical-LM characterization reflects publicly-discussed industry patterns
- **L81** — TODO: verify; cloud-hosted clinical ASR vendor lineup continues to evolve, and feature parity across vendors shifts quarterly
- **L89** — TODO: verify; custom-vocabulary biasing is a well-established feature across cloud ASR providers, with implementation details varying
- **L129** — TODO: verify; LLM-driven post-processing of dictation transcripts is an active product area in 2024-2026 with multiple vendor implementations and ongoing accuracy and faithfulness research
- **L397** — TODO (TechWriter): Expert review A1 (HIGH). Promote critical-error
detection from prose into the architecture pattern. Add an explicit
critical-error-detection stage to the eight-stage decomposition (between
formatting and read-edit-sign, or as a parallel pass invoked from
read-edit-sign). Specify per-specialty high-risk-substitution catalogs
(laterality, negation, drug-name confusables, dose-by-order-of-magnitude)
as version-controlled clinical-safety documents owned by the
clinical-quality officer. Specify detection thresholds, severity tiers,
and the high-severity disposition (explicit clinician confirmation
required before signature). Add an aggregate detection-rate metric to
CloudWatch with named ownership and review cadence. The recipe's own
prose names this as "the single most important production gap"; the
architecture should match the prose.
- **L448** — TODO: verify; the Transcribe Medical specialty list and accuracy characteristics continue to evolve

## architecture — `chapter10.04-architecture.md`

- **L11** — TODO: verify; the Transcribe Medical specialty list and BAA-eligibility coverage may have changed; confirm against the current Transcribe Medical documentation at build time
- **L21** — TODO (TechWriter): Networking review N1 (LOW). Add a WebSocket
Audio Streaming paragraph specifying connection-time authentication
(Lambda authorizer with the clinician's Cognito token), account-level
concurrent-connection limits with quota-increase as a deployment-time
activity, idle-timeout interaction with long-form dictation (consider
extending the idle timeout or implementing a keep-alive ping so a
clinician's pause does not drop the connection mid-dictation), and
the binary-message-type frame format.
- **L30** — TODO (TechWriter): Networking review N3 (LOW). Add a Device-to-
Cloud Transport Posture paragraph for the activation and audio capture
stage: TLS-encrypted WebSocket with institutional certificate pinning,
clinical-device VLAN network segmentation, and device-identity
authentication via mutual TLS or device certificates. Reference
institutional clinical-device-management ownership for per-device-fleet
certificate provisioning.
- **L184** — TODO: verify validation-set sourcing options; commercial dictation vendors typically have proprietary benchmarks, while open-source healthcare-speech datasets remain limited; check current sources at build time
- **L185** — TODO (TechWriter): Expert review S3 (MEDIUM). Specify the orchestrator Lambda's resource-based policy: pin the invoking principal to the production API Gateway stage ARN; reject invocations from any other API Gateway, stage, or principal; add a defense-in-depth event-payload validation that verifies requestContext.apiId against the production constant.
- **L186** — TODO: verify; the AWS HIPAA-eligible services list and the specific Bedrock models covered under BAA continue to evolve
- **L186** — TODO (TechWriter): Expert review A12 (LOW). Add a default-model recommendation for Bedrock (Claude family typical for healthcare due to longer-standing HIPAA-eligible-on-Bedrock track record) with the verify-at-build-time hedge; reference the AWS HIPAA Eligible Services Reference URL.
- **L187** — TODO (TechWriter): Expert review A8 (MEDIUM). Specify the audio-retention configuration mechanism explicitly: retain-briefly with a 7-30-day window (KMS-encrypted, lifecycle-policy-deletion, access-logged through CloudTrail) as the recommended default; discard-immediately as the conservative alternative for institutions with strict PHI-minimization requirements; retain-longer requires explicit clinician consent at onboarding and a documented retention purpose. Reference the audit log (per Finding S1) as the long-term forensic-reconstruction substrate; audio retention is short-term QA-and-adaptation.
- **L188** — TODO (TechWriter): Networking review N2 (LOW). Add PrivateLink-preferred-for-EHR-vendor-APIs framing; egress hierarchy is PrivateLink (preferred where available) > private peering / Direct Connect / Transit Gateway > VPN > public-Internet-with-TLS.
- **L189** — TODO (TechWriter): Expert review S4 (MEDIUM). Name the dictation-specific audit-log retention floor as the longest of HIPAA's six-year minimum, state-specific medical-records-retention rules (which for certain patient populations such as pediatric records can extend to age-of-majority-plus-multiple-years), the EHR vendor's audit-retention floor, the longest-retained signed note's retention period (the audit trail must outlive the signed note it documents), and the institutional regulatory floor.
- **L190** — TODO: verify; public-domain dictated-clinical-text audio corpora are limited; common sources include the MIMIC-III dataset (text only) and select academic datasets, but most production benchmarks use proprietary data
- **L190** — TODO (TechWriter): Expert review S5 (LOW). Add a Voice Biometric Data Governance paragraph specifying clinician consent at onboarding, separation of biometric retention from general dictation retention, per-clinician right-to-deletion, and cross-jurisdictional considerations (BIPA in Illinois, GIPA in Texas, similar state laws). Reference the institutional employment-and-compliance team for the per-jurisdiction policy.
- **L191** — TODO: replace with verified pricing once the implementing team validates against the AWS Pricing Calculator. Specific costs depend on per-minute Transcribe Medical pricing in the chosen region and the chosen Bedrock model
- **L1095** — TODO: replace illustrative figures with measured results from the deployment. The ranges above are typical for medical-dictation deployments but vary substantially with vendor choice, specialty, clinician training, and integration depth
- **L1135** — TODO (TechWriter): Expert review A9 (MEDIUM). Promote disaster
recovery from production-gaps prose into the architecture pattern: a
Disaster Recovery Topology subsection with per-stage failover policy
(Transcribe Medical regional outage with cross-region failover or
batch-mode fallback, Bedrock model unavailability with rule-based
formatter fallback, Comprehend Medical unavailability with manual
structured-field-entry fallback, EHR API unreachable with signed-note-
queue-for-retry that preserves the signed note), failover-detection
and failover-back triggers, and quarterly DR-test cadence.
- **L1165** — TODO (TechWriter): Expert review A10 (MEDIUM). Specify the per-language pipeline pattern as build-for-day-one even when shipping English-first: per-clinician language declared at onboarding; per-language Transcribe Medical configuration and custom vocabulary; per-language LLM-formatter prompts; per-language formatting rules. The configuration scaffolding should not assume a single language at the architecture level.
- **L1213** — TODO: confirm the current names and locations of these repos at time of build; the AWS sample repo organization changes over time
- **L1219** — TODO: replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs
- **L1233** — TODO: confirm specific URL at time of build
- **L1236** — TODO: confirm specific URL at time of build
- **L1237** — TODO: confirm current URL at time of build
- **L1238** — TODO: confirm specific URL at time of build
