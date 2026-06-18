# Open TODOs — Recipe 2.5: After-Visit Summary Generation

> Auto-extracted 2026-06-18 from inline source comments (24 items; S2 resolved 2026-06-18). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## main — `chapter02.05-after-visit-summary-generation.md`

- **L21** — TODO: verify specific percentages against current health literacy literature (Kessels 2003 is commonly cited but somewhat dated)
- **L21** — TODO (EXPERT REVIEW - LOW, Finding V3): The "8th-grade level" shorthand traces back to NAAL 2003. Consider softening to AHRQ/CDC guidance targeting 6th-to-8th-grade for patient materials, without the "average" framing.
- **L25** — TODO: verify current CMS readmission statistics
- **L202** — TODO: verify recipe number once Chapter 11 is drafted

## architecture — `chapter02.05-architecture.md`

- **L30** — TODO (EXPERT REVIEW - MEDIUM, Finding A4): The parenthetical example above is
     incorrect. "Denied topics" in Bedrock Guardrails are defined by natural-language
     topic descriptions and blocklist phrases; they cannot detect content that
     contradicts a source note. The feature to reference is Bedrock Guardrails'
     "contextual grounding check," which compares model output against a reference
     context provided at invocation time and rejects ungrounded or off-topic outputs
     below configurable thresholds. Please rewrite the paragraph to distinguish
     contextual grounding checks (the grounding tool), denied topics (blocking
     off-policy content), PII detection, and content filters. See review Finding A4.
- **L52** — TODO (EXPERT REVIEW - MEDIUM, Finding A2): For the clinician-review branch,
     specify the Step Functions waitForTaskToken callback pattern. The Lambda that
     completes generation hands off a task token when it routes to review; the review
     UI calls SendTaskSuccess with the signed summary (or SendTaskFailure if rejected).
     This avoids polling and supports extended review SLAs. See Finding A2.
- **L60** — TODO (EXPERT REVIEW - MEDIUM, Finding A3 / LOW A6): EventBridge delivery is
     at-least-once. Add idempotency guidance at Step 1 using a deterministic fingerprint
     of (encounter_id, note_version_or_signed_at) and a DynamoDB conditional write
     (attribute_not_exists) to prevent duplicate executions, duplicate summaries, and
     duplicate patient deliveries. See Findings A3 and A6.
- **L70** — TODO (EXPERT REVIEW - CRITICAL, Finding S1): SMS of clinical content (medication
     names, doses, warning signs, follow-up instructions) constitutes PHI transmission
     over an unencrypted channel. HIPAA requires documented patient consent after
     disclosure of security risks. Recommend pivoting the default SMS pattern to
     "notification-plus-portal-link" (no clinical content in the SMS body). If
     direct-to-SMS clinical content is retained as an option, add a consent gate and
     a dedicated "SMS and PHI" subsection in "Why This Isn't Production-Ready" that
     names the consent requirement, content-minimization practice, and jurisdiction-
     specific overlays (California, Texas, Washington MHMDA). See Finding S1.
- **L80** — TODO (EXPERT REVIEW - LOW, Finding N3): SES direct-to-personal-mailbox delivery of
     PDF-attachment AVS is secure only if both mail servers enforce TLS (not guaranteed).
     Production deployments typically use a HIPAA-grade secure email gateway or a
     notification-plus-portal-link pattern. Add a one-line note here or in the SES
     row of the Ingredients table.
- **L138** — TODO (EXPERT REVIEW - HIGH, Finding S3): Scope every action to specific resource ARNs (S3 bucket ARNs, DynamoDB table ARNs, specific foundation-model ARNs, Guardrail ARN, HealthLake datastore ARN, SES verified-identity ARNs). Add kms:Decrypt and kms:GenerateDataKey scoped to the PHI CMKs. Recurring Chapter 2 pattern (2.2, 2.3, 2.4, 2.5) - consider chapter-level appendix. See Finding S3.
- **L143** — TODO (EXPERT REVIEW - HIGH, Finding S4): If Bedrock model-invocation-logging is enabled for quality monitoring or drift detection, the logged prompts and responses contain PHI (structured clinical facts, patient identifiers, medication details). The log-destination S3 bucket or CloudWatch log group must be KMS-encrypted with the same CMK posture as other PHI stores, access-controlled equivalently, and retention-matched. Consider sampling rather than logging every invocation. See Finding S4.
- **L144** — TODO (EXPERT REVIEW - HIGH, Finding N1): Endpoint list is incomplete for the services this recipe uses. Add interface endpoints for kms, logs, states, events, monitoring, translate (if used), email-smtp (if SES used), and sms-voice (if SMS used). Keep S3 and DynamoDB as gateway endpoints. Without kms and logs endpoints, Lambda in a private subnet cannot decrypt or log. Without states endpoint, waitForTaskToken callbacks fail from within the VPC. Interface endpoints are ~$7-10/month per AZ; reflect this in the cost estimate. See Finding N1.
- **L174** — TODO (EXPERT REVIEW - MEDIUM, Finding A3): EventBridge delivers at-least-once.
     Add an idempotency check before starting the Step Functions execution: derive a
     fingerprint from (encounter_id, note_version_or_signed_at), attempt a DynamoDB
     conditional write with attribute_not_exists(fingerprint), and if the fingerprint
     already exists return the existing summary_id and skip. Otherwise duplicate
     note-signed events produce duplicate summaries, duplicate LLM charges, and
     duplicate patient deliveries. See Finding A3.
- **L256** — TODO (EXPERT REVIEW - MEDIUM, Finding S5): Apply the minimum-necessary principle
     to prompts. The generation step needs diagnoses, medications, orders, and
     follow-up details. It does not need the patient's MRN, DOB, address, phone
     number, or insurance identifiers. Consider redacting non-clinical PHI from the
     extracted object before the generation call (field allow-list, or Comprehend
     Medical DetectPHI as a pre-flight). Keep the preferred name for salutation.
- **L263** — TODO (CODE REVIEW - WARNING, Finding 4): Comprehend Medical's size limit is
     enforced in bytes, not characters. If the pseudocode shows a character-based
     slice like note_text[:20000], a multilingual note can exceed the byte limit.
     Consider noting the byte-safe pattern (encode to utf-8, slice bytes, decode
     errors=ignore) for multilingual use cases. See Finding 4 in the code review.
- **L416** — TODO (EXPERT REVIEW - MEDIUM, Finding A1): Cap regeneration at 2-3 attempts.
     Vary the strategy on each retry (first retry adds a stronger grounding
     instruction naming the previously-unverified claims; second retry at
     temperature=0 for determinism; third retry falls through to clinician review).
     Track retry count in DynamoDB and emit a CloudWatch metric on exhaustion.
     Never auto-deliver an exhausted-retry summary without clinician sign-off.
     This pairs with CODE REVIEW Finding 3, where the Python orchestrator currently
     auto-delivers when attempts are exhausted on non-high-risk visits.
- **L493** — TODO (EXPERT REVIEW - MEDIUM, Finding A1): Also cap the readability regeneration
     loop (same 2-3 attempts rule as the validation loop in Step 5). Pathological
     inputs can otherwise loop indefinitely at $0.03-$0.10 per attempt.
- **L499** — TODO (EXPERT REVIEW - CRITICAL, Finding S1): The SMS branch below ships clinical
     PHI (medication names, doses, warning signs, follow-up dates) over an
     unencrypted channel with no consent gate. Recommended fix: change the SMS
     pattern to notification-plus-portal-link, for example
     rendered["sms_messages"] = [localize("Your after-visit summary is ready. Open it
     in the patient portal: {portal_link}", patient_prefs.language)] -- no clinical
     content in the SMS body. If direct-to-SMS clinical content is retained as an
     option for practices that use it, add a consent check before dispatch:
     IF "sms" in patient_prefs.delivery_channels AND
        patient_prefs.sms_phi_consent != "granted":
        fall back to notification-plus-link pattern.
     Also add a section in "Why This Isn't Production-Ready" titled "SMS and PHI"
     covering HIPAA consent, content-minimization best practice, lack of SMS
     end-to-end encryption, and jurisdiction-specific overlays. See Finding S1.
- **L577** — TODO (EXPERT REVIEW - MEDIUM, Finding A5): The factual_claims array below lists
     only 5 claims, but the summary text contains 15-25 specific claims (warning
     signs, lifestyle instructions, practice phone, hours, etc.). For a recipe
     whose central teaching is "every specific claim must trace to source," the
     sample should either enumerate the full set of claims with source paths, or
     include a note that the array is abbreviated for readability and a production
     validator tracks 15-30 per AVS. See Finding A5.
- **L585** — TODO (EXPERT REVIEW - LOW, Finding S6): Label the sample as synthetic, e.g.,
     add a one-line comment above the JSON: "All identifiers, dates, and provider
     names below are synthetic. Never use real patient data in development or test
     fixtures."
- **L620** — TODO: verify with published data or customer case studies
- **L647** — TODO (EXPERT REVIEW - MEDIUM, Finding N2): Add a short paragraph here on
     EHR-to-pipeline connectivity. For cloud EHRs, the note-signed event and FHIR
     pull typically cross TLS-encrypted connections to vendor public endpoints with
     egress controls and Secrets Manager-sourced credentials. For on-premises EHRs,
     plan for Direct Connect or site-to-site VPN with the FHIR gateway reachable
     over private IPs only. PHI in transit must never traverse the public internet
     unencrypted; inbound traffic to your VPC should be scoped by source IP or
     PrivateLink. See Finding N2.
- **L674** — TODO (EXPERT REVIEW - LOW, Finding V4): Polly is HIPAA-eligible, but the
     generated audio is PHI and must be stored with the same KMS encryption, access
     controls, and retention as the text AVS archive. Add a one-line note to that
     effect.

## python-example — `chapter02.05-python-example.md`

- **L1306** — TODO (TechWriter): Code review Finding 2 (WARNING). The paragraph below
     claims validation_rate is stored to DynamoDB with Decimal wrapping, but the
     example code never writes validation_rate to DynamoDB. Either update the prose
     to say "if you extend the code to persist validation_rate, wrap it with
     Decimal(str(round(...)))" or add the DynamoDB write to Step 7.
