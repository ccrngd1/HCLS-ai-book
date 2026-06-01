# Edit Status: Recipe 9.6 — Diabetic Retinopathy Screening

**Editor:** TechEditor
**Date:** 2026-05-31
**Verdict:** COMPLETE (pending URL verification by TechWriter)

---

## Changes Applied

1. **S1 (HIGH) — IAM clarity:** Added explicit note that EventBridge rules execute in the AWS service plane, clarifying why the rule's IAM role (not Lambda) needs `states:StartExecution`.
2. **S2 (MEDIUM) — DynamoDB encryption:** Added "for CloudTrail audit visibility" rationale to the customer-managed KMS key specification.
3. **N1 (HIGH) — VPC endpoint format:** Added explicit endpoint name `(com.amazonaws.{region}.states)` for Step Functions VPC endpoint so builders can copy-paste.
4. **S3 (LOW) — Bucket policy:** Consolidated bucket policy enforcement details into the Encryption row for a single authoritative location.

## Findings Already Addressed in Draft

The following expert review findings were already incorporated before the edit pass:
- A1 (HIGH): Cost guidance for low-volume deployments (async/serverless inference)
- A2 (MEDIUM): DLQ and CloudWatch alarm on SNS topics
- A3 (MEDIUM): Lambda memory (2048MB) and timeout (30s) specification
- N2 (LOW): NAT Gateway note for EHR integration
- S3 (LOW): Bucket policy note in "Why These Services" S3 paragraph

## Deferred to TechWriter

- **V1 (MEDIUM):** Six URL placeholders in Additional Resources require verification. TODO marker preserved at line 418.

## Style Checklist

- [x] No em dashes
- [x] No documentation-voice
- [x] No fabricated URLs
- [x] Header hierarchy correct (H1 → H2 → H3 → H4, no skips)
- [x] 70/30 vendor balance maintained
- [x] All RECIPE-GUIDE sections present in correct order
- [x] Python companion callout present
- [x] Active voice throughout
- [x] Short paragraphs, no run-on sentences
