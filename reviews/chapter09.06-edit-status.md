# Edit Status: Recipe 9.6 - Diabetic Retinopathy Screening

**Editor:** TechEditor
**Date:** 2026-05-31
**Verdict:** COMPLETE

---

## Changes Applied

### From Expert Review (HIGH findings - all addressed inline)

1. **S1 (IAM Permissions):** Split into three distinct roles: Lambda execution role, Step Functions execution role (`lambda:InvokeFunction` scoped to ARNs), and EventBridge rule role (`states:StartExecution`). Clarified trigger mechanism.

2. **A1 (Cost Estimate):** Added guidance for low-volume deployments: SageMaker Async/Serverless Inference for <50 images/day, with note that always-on endpoint becomes cost-effective above ~200 images/day.

3. **N1 (VPC Endpoint):** Added Step Functions to the VPC endpoints list. Added NAT Gateway note for outbound EHR integration.

### From Expert Review (MEDIUM findings)

4. **S2 (DynamoDB Encryption):** Changed to "encryption at rest with customer-managed KMS key (CMK)" for consistency with S3 and SageMaker.

5. **A2 (SNS DLQ):** Added DLQ guidance to the SNS "Why These Services" paragraph, including CloudWatch alarm on urgent-referral DLQ.

6. **A3 (Lambda Config):** Added memory (2048MB) and timeout (30s) specification to the Lambda "Why These Services" paragraph, plus provisioned concurrency note.

7. **V1 (TODO URLs):** Preserved as TODO markers for TechWriter. Cannot verify URLs from editor role.

### From Expert Review (LOW findings)

8. **S3 (Bucket Policy):** Added bucket policy note to S3 "Why These Services" paragraph.

9. **N2 (NAT Gateway):** Added to VPC prerequisites row.

10. **V2 (Ingredients voice):** No action per reviewer recommendation (table format constrains voice).

### From Code Review (WARNINGs - both fixed)

1. **C1 (scipy dependency):** Added `scipy` to pip install line and updated the description paragraph.

2. **C2 (image_key not passed):** Added `image_key` parameter to `trigger_downstream_action` function signature and updated the caller.

### From Code Review (NOTEs - addressed)

3. **C3 (screening_id format):** Fixed date format from `'%Y-%m%d'` to `'%Y%m%d'` for consistency.

4. **C4 (DynamoDB key comment):** Added comment above `put_item` noting partition/sort key schema.

---

## Deferred Items

| Finding | Marker Location | Reason |
|---------|----------------|--------|
| V1 (MEDIUM) | Additional Resources section | URLs require verification by TechWriter; editor cannot confirm external links |

---

## Editorial Checklist

- [x] Grammar and mechanics: Clean
- [x] Code formatting: All fenced blocks have language tags, inline code for service names
- [x] Link verification: AWS doc links are well-formed; clinical/dataset URLs deferred (TODO markers)
- [x] Header hierarchy: H1 title, H2 major sections, H3 subsections, no skipped levels
- [x] Readability: Short paragraphs, active voice, no run-on sentences
- [x] Voice drift: No documentation-voice, no em dashes, no LinkedIn tone
- [x] RECIPE-GUIDE compliance: All required sections present in correct order
- [x] Vendor balance: ~70/30 general vs AWS-specific maintained
