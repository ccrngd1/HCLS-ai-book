# Expert Review: Recipe 9.2 - Patient Photo Verification

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-04
**Recipe file:** `chapter09.02-patient-photo-verification.md`
**Python companion:** `chapter09.02-python-example.md`

---

## Overall Assessment

This is a strong recipe. The main recipe file is complete, well-structured, and follows the RECIPE-GUIDE.md spec. The Problem section is compelling, the Technology section teaches face comparison from first principles without vendor names, the AWS implementation is sound, and the Honest Take is genuinely useful. The recipe handles the ethical and bias dimensions with appropriate gravity without becoming preachy. The tiered decision logic ("face comparison is an identity signal, not a gate") is the correct healthcare-specific design principle.

The recipe has no CRITICAL findings and a small number of addressable issues.

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well

- BAA explicitly listed in Prerequisites table with specifics on which services need coverage
- Encryption addressed: S3 SSE-KMS, DynamoDB encryption at rest, TLS in transit, CloudWatch Logs KMS encryption
- CloudTrail enabled for audit trail of all Rekognition and S3 API calls
- Consent requirements called out with state-specific laws (BIPA, CCPA)
- "Never deny care based on a failed face match" is the correct security design principle for healthcare
- Pseudocode explicitly avoids storing live photos in the audit log ("Do NOT store the live photo here. It's PHI.")
- "Why This Isn't Production-Ready" section covers liveness detection, rate limiting, and consent management

### Issue SEC-1: IAM Permissions Listed Without Resource Scoping (MEDIUM)

**Section:** Prerequisites table, "IAM Permissions" row

**Quote:** "`rekognition:CompareFaces`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:GetItem`"

**The problem:** Permissions are listed as actions only, without resource ARN constraints. In a HIPAA environment, `s3:GetObject` on `*` would allow reading any object in any bucket. `s3:PutObject` is listed (for enrollment) alongside `s3:GetObject` (for verification) without noting these should be separate roles. A reader might create a single overly-permissive role.

**Suggested fix:** Add a note to the Prerequisites table: "Scope all permissions to specific resource ARNs. Separate enrollment permissions (`s3:PutObject`, `rekognition:DetectFaces`) from verification permissions (`s3:GetObject`, `rekognition:CompareFaces`) into distinct Lambda execution roles." Even a parenthetical like "(scope to specific bucket/table ARNs)" would help.

### Issue SEC-2: Liveness Detection Treated as Non-Production Enhancement Rather Than Security Requirement (HIGH)

**Section:** "Why This Isn't Production-Ready" section

**Quote:** "The simple CompareFaces API doesn't verify that the live photo is actually live. Someone could hold up a printed photo or display a photo on their phone screen. Production systems need liveness detection..."

**The problem:** Liveness detection is presented in the "Why This Isn't Production-Ready" section, framing it as a production enhancement. For a patient identity verification system, the absence of liveness detection means the system provides no meaningful security against even trivial spoofing attacks (holding up a phone with a photo). This should be acknowledged as a fundamental limitation of the basic architecture, not deferred to a "production-ready" upgrade. The architecture diagram and core flow should at least show where liveness fits, even if the pseudocode omits it for simplicity.

**Suggested fix:** Add liveness detection as a dotted-line step in the architecture diagram (showing it as optional/recommended), and add one sentence to the General Architecture Pattern section: "Production deployments insert a liveness check between capture and comparison to prevent presentation attacks (printed photos, screen displays). This is essential for any deployment where the camera is unsupervised." Keep the detailed discussion in the "Why This Isn't Production-Ready" section, but make the architecture show the complete pipeline.

### Issue SEC-3: No Data Retention or Destruction Policy Guidance (MEDIUM)

**Section:** Enrollment pseudocode (Step 5), Prerequisites table

**The problem:** The enrollment step stores photos in S3 with KMS encryption but provides no guidance on retention or destruction. Biometric data is subject to specific retention requirements under BIPA (must destroy within 3 years of last interaction or when original purpose is fulfilled), CCPA, and other state laws. The consent section mentions revocability but doesn't connect it to the technical mechanism (S3 lifecycle rules, DynamoDB TTL, or manual deletion workflow).

**Suggested fix:** Add one bullet to Prerequisites: "S3 Lifecycle: Configure lifecycle rules aligned with your biometric data retention policy. Include a mechanism to delete photos and DynamoDB records on consent withdrawal." Alternatively, add a brief note in the enrollment pseudocode: "// Production: attach lifecycle policy for max retention (e.g., 3 years per BIPA)."

### Issue SEC-4: Rate Limiting Mentioned But Not Architected (LOW)

**Section:** "Why This Isn't Production-Ready"

**Quote:** "Without rate limits, someone could attempt repeated verifications against random patient IDs to find exploitable matches."

**The problem:** Rate limiting is identified as needed but no architectural guidance is given (API Gateway throttling, per-patient DynamoDB-based counters, WAF rules). This is fine for a "not production-ready" callout, but a brief pointer would be helpful.

**Suggested fix:** Add one sentence: "API Gateway supports per-client throttling, and you can implement per-patient rate limits using DynamoDB atomic counters." No code needed.

---

## Architecture Expert Review

### What's Done Well

- General Architecture Pattern is clean and vendor-agnostic: `[Enrollment] -> [Store] -> [Verify] -> [Compare] -> [Score] -> [Decision]`
- Three-tier decision logic (VERIFIED / STEP_UP_REQUIRED / MANUAL_REVIEW) is the correct pattern for healthcare
- "Never deny care" principle is architecturally enforced by always having a fallback path
- Cost estimate is realistic ($0.001 per comparison, negligible Lambda/DynamoDB)
- Implementation time tiers (1-2 weeks basic, 6-8 weeks production) are accurate
- The choice of Lambda for orchestration is appropriate for the stateless, short-lived nature of the workflow
- Rekognition CompareFaces with threshold=0 (apply own thresholds) is the correct pattern
- Enrollment quality validation (brightness, sharpness, single face) prevents garbage-in problems

### Issue ARCH-1: No Dead Letter Queue or Error Handling Architecture (MEDIUM)

**Section:** Architecture Diagram, Code walkthrough

**The problem:** The architecture shows a synchronous request-response flow (API Gateway -> Lambda -> Rekognition -> DynamoDB -> response). If Rekognition times out or returns a service error, the Lambda returns an error to the calling system. But what happens to the audit record? If DynamoDB write fails after a successful comparison, the verification is unlogged. The architecture doesn't show: (a) what happens if audit logging fails, (b) retry behavior for transient failures, (c) whether failed attempts are captured anywhere.

**Suggested fix:** Add a brief note in the architecture section: "If the DynamoDB audit write fails, the Lambda should still return the verification result to avoid blocking patient check-in, but publish the failed audit record to an SQS dead letter queue for retry. Never let an audit logging failure block patient access to care."

### Issue ARCH-2: Enrollment and Verification Share a Single Lambda (LOW)

**Section:** Architecture Diagram, "Why These Services"

**The problem:** The architecture diagram shows a single "Lambda verification-handler" but the code includes both enrollment (Step 5) and verification (Steps 1-4) logic. In practice, these should be separate functions: enrollment is a less frequent, higher-privilege operation (writes to S3, calls DetectFaces for quality) while verification is high-frequency and read-heavy (reads from S3, calls CompareFaces). Combining them in one Lambda means the runtime role needs both read and write permissions.

**Suggested fix:** This is a minor architectural note. Add a sentence to the "Why These Services" Lambda section: "In production, separate enrollment and verification into distinct Lambda functions with independent IAM roles (principle of least privilege)."

### Issue ARCH-3: No Mention of Cold Start Impact on Patient Experience (LOW)

**Section:** Expected Results, "End-to-end latency: 0.8-2 seconds"

**The problem:** Lambda cold starts can add 1-3 seconds to the first invocation after a period of inactivity. For a check-in kiosk, this means the first patient of the day (or after a lull) experiences 2-5 second latency. The performance table states 0.8-2 seconds without noting this is for warm invocations.

**Suggested fix:** Add a footnote or parenthetical to the latency row: "0.8-2 seconds (warm Lambda). First invocation after idle may add 1-3 seconds. Use provisioned concurrency for patient-facing workflows if latency consistency matters."

---

## Networking Expert Review

### What's Done Well

- VPC requirement explicitly stated in Prerequisites: "Production: Lambda in VPC with VPC endpoints for S3, Rekognition, DynamoDB, and CloudWatch Logs"
- All four needed VPC endpoints listed (S3, Rekognition, DynamoDB, CloudWatch Logs)
- TLS in transit stated for all API calls
- No egress concerns with the architecture (all data stays within AWS via VPC endpoints)

### Issue NET-1: FIPS Endpoint Not Mentioned for Healthcare Compliance (LOW)

**Section:** Prerequisites table, VPC row

**The problem:** Healthcare organizations subject to FedRAMP or operating in GovCloud regions need FIPS 140-2 validated endpoints. Rekognition offers a FIPS endpoint (`com.amazonaws.{region}.rekognition-fips`). The recipe doesn't mention this, which is fine for most commercial deployments but would be relevant for government healthcare (VA, DoD health systems, state Medicaid agencies).

**Suggested fix:** Optional. A brief note in Prerequisites or Additional Resources: "For FedRAMP or GovCloud deployments, use the FIPS-validated Rekognition endpoint." This is low priority since the recipe targets general healthcare, not government-specific.

### Issue NET-2: No Guidance on Photo Upload Path from Point-of-Care Device (LOW)

**Section:** Architecture Diagram

**The problem:** The diagram shows "Kiosk / App / Telehealth" sending a "Verify Request with live photo" to API Gateway. For kiosks, the photo (biometric PHI) travels from the device to API Gateway. The recipe doesn't address how this segment is secured. Options: the photo is base64-encoded in the HTTPS request body (simple but limited to ~6MB payload with API Gateway), or uploaded to S3 via pre-signed URL first (better for large images). The HTTPS layer provides encryption in transit, which is sufficient, but the payload size consideration is worth noting.

**Suggested fix:** Add one sentence to the Code Step 1 or Prerequisites: "The live photo is included in the API request body (base64-encoded, under API Gateway's 10MB payload limit). For higher-resolution images, consider pre-signed S3 upload URLs with short expiration." Very minor.

---

## Voice Reviewer

### What's Done Well

- The Problem section is outstanding. "Medical identity fraud costs the U.S. healthcare system an estimated $80 billion annually. But the numbers don't capture the real risk..." builds emotional stakes perfectly before revealing the real danger (patient safety).
- Technology section teaches face comparison without a single vendor name. A reader on Azure or GCP learns just as much.
- Parenthetical asides land well: "(ok, this is a gross oversimplification, but stay with me)" energy throughout
- The Honest Take is genuinely useful and self-deprecating: "If this were a consumer app, you'd ship it in a week."
- "The enrollment photo quality matters more than the verification photo quality" is the kind of hard-won insight that makes the cookbook valuable
- The bias discussion is handled with appropriate gravity without becoming preachy or performative

### Issue VOICE-1: Em Dash Check (PASS)

Full scan of the recipe. Zero em dashes detected. Colons, periods, and parentheses used throughout instead.

### Issue VOICE-2: Vendor Balance Assessment (PASS)

Approximate split: The Problem (~500 words, 0% AWS), The Technology (~1800 words, 0% AWS), General Architecture Pattern (~300 words, 0% AWS), The Honest Take (~400 words, 0% AWS), Variations (~250 words, 0% AWS). Total vendor-agnostic: ~3250 words. AWS Implementation section: ~1400 words. Ratio approximately 70/30. Passes.

### Issue VOICE-3: Minor Doc-Voice Creep (LOW)

**Section:** Prerequisites table header

**Quote:** "Prerequisites" as a section header following "Architecture Diagram" is standard recipe structure, not doc-voice. However, one small instance: "Encryption | S3: SSE-KMS; DynamoDB: encryption at rest enabled; Lambda CloudWatch log groups: KMS encryption (logs may contain patient identifiers); all API calls over TLS"

This reads slightly like a compliance checklist rather than an engineer explaining the setup. It's in a table, so it's fine, but the parenthetical "(logs may contain patient identifiers)" is the kind of thoughtful explanation that keeps it from feeling like a template fill-in. No change needed.

**Verdict:** PASS. Voice is consistent throughout and matches the style guide.

---

## Stage 2: Expert Discussion

### Conflicts and Overlaps

**SEC-2 (liveness as security requirement) vs. recipe structure:** The Security expert rates liveness detection absence as HIGH because it makes the system trivially spoofable. The Architecture expert notes the recipe correctly calls this out in "Why This Isn't Production-Ready" and the Variations section mentions it. The tension: should the basic architecture include liveness, or is it acceptable to present the simpler pipeline first and note liveness as a production upgrade?

**Resolution:** The recipe's approach (teach the simple pattern, then call out what's needed for production) is pedagogically correct for a cookbook. The issue is framing: "Why This Isn't Production-Ready" implies liveness is one of several nice-to-haves, when it's actually the single most important security upgrade. The fix is a minor reframing, not a restructuring.

**SEC-1 (IAM scoping) and ARCH-2 (single Lambda) overlap:** Both point to the same root issue: the architecture conflates enrollment and verification. Separate functions would naturally have separate, scoped IAM roles. The Architecture expert owns the root cause; the Security expert owns the symptom.

**All NET findings are LOW:** The networking posture is solid. VPC endpoints, TLS, no egress concerns. The FIPS and upload path issues are edge cases that don't affect the recipe's correctness for its stated audience.

### Priority Resolution

1. SEC-2 (liveness framing) is the most impactful finding. It's HIGH but fixable with a small architectural addition.
2. SEC-1 (IAM scoping) and SEC-3 (data retention) are MEDIUM findings that add production-readiness guidance.
3. ARCH-1 (DLQ for failed audits) is MEDIUM and adds resilience thinking.
4. Everything else is LOW and optional.

---

## Stage 3: Synthesized Feedback

### Verdict: **PASS**

The recipe is well-written, architecturally sound, clinically appropriate, and follows the style guide. It has 1 HIGH finding (liveness framing), 3 MEDIUM findings, and 5 LOW findings. No CRITICAL findings. The HIGH finding does not represent a fundamental flaw in the recipe's approach; it's a framing issue where the most important security upgrade should be more prominent in the architecture rather than buried in the "not production-ready" section.

---

### Prioritized Findings

| # | Severity | Expert | Section | Finding | Fix |
|---|----------|--------|---------|---------|-----|
| 1 | HIGH | Security | "Why This Isn't Production-Ready" + Architecture Diagram | Liveness detection framed as a production enhancement rather than a fundamental security requirement. Without it, the system is trivially spoofable. Should be visible in the architecture even if pseudocode omits it. | Add liveness as a dotted-line step in the architecture diagram. Add one sentence to the General Architecture Pattern noting liveness is essential for unsupervised deployments. Keep detailed discussion where it is. |
| 2 | MEDIUM | Security | Prerequisites table, IAM Permissions | IAM permissions listed as actions without resource ARN scoping or separation between enrollment and verification roles. | Add note: "Scope to specific ARNs. Separate enrollment (write) and verification (read) into distinct roles." |
| 3 | MEDIUM | Security | Enrollment pseudocode (Step 5) | No biometric data retention or destruction policy guidance. BIPA requires destruction within 3 years. Consent withdrawal needs a technical deletion mechanism. | Add one bullet to Prerequisites on lifecycle rules for biometric data retention. Brief note in enrollment pseudocode on retention policy. |
| 4 | MEDIUM | Architecture | Architecture Diagram + Code | No error handling for audit logging failures. If DynamoDB write fails after successful comparison, the verification is unlogged. No DLQ or retry shown. | Add note: "If audit write fails, return verification result anyway (don't block care) and publish to SQS DLQ for retry." |
| 5 | LOW | Architecture | Architecture Diagram | Enrollment and verification shown as single Lambda. Should note separation in production for least-privilege. | Add one sentence to "Why These Services" Lambda section noting production separation. |
| 6 | LOW | Architecture | Expected Results, latency row | Latency stated as 0.8-2 seconds without noting cold start impact (first invocation +1-3s). | Add parenthetical: "(warm Lambda; first invocation after idle adds 1-3s)." |
| 7 | LOW | Security | "Why This Isn't Production-Ready" | Rate limiting identified as needed but no architectural pointer given. | Add one sentence pointing to API Gateway throttling + DynamoDB atomic counters. |
| 8 | LOW | Networking | Prerequisites, VPC row | FIPS endpoint for Rekognition not mentioned (relevant for government healthcare). | Optional: add note for FedRAMP/GovCloud deployments. |
| 9 | LOW | Networking | Architecture Diagram | Photo upload path from kiosk to API Gateway not addressed (payload size, transport mechanism). | Add one sentence about base64 in request body vs. pre-signed URL for large images. |

---

### Summary

This is a well-crafted recipe that correctly teaches face comparison concepts, presents an appropriate healthcare architecture (tiered decisions, never-deny-care principle), and handles the ethical dimensions (bias, consent, demographic disparities) with appropriate depth. The voice is consistent, the vendor balance is correct, and the technical accuracy is solid.

The single HIGH finding (liveness detection framing) is the most important improvement: a reader should understand from the architecture diagram that liveness belongs in the pipeline, even though the simplified example omits it. The MEDIUM findings add production-readiness guidance that will make the recipe more actionable for architects moving from concept to deployment.

No structural or fundamental changes needed. This recipe is ready for editing with the above findings incorporated.
