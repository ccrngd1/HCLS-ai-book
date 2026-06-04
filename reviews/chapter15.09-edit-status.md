# Edit Status: Recipe 15.9 - Radiation Therapy Adaptive Planning

**Editor:** TechEditor
**Date:** 2026-06-04
**Status:** COMPLETE (Publication-Ready)

---

## Changes Applied

### From Expert Review

| Finding | Severity | Action |
|---------|----------|--------|
| A1: Safety constraint formulation | CRITICAL | Fixed. Added two-layer safety architecture paragraph in Technology section. Clarified soft vs. hard constraints with explicit statement that both layers are required. Updated pseudocode Step 2 comment to emphasize hard constraint role. Renamed parameter to `safety_shaping_penalties` in Step 5 with explanatory comment. |
| A2: Offline evaluation methodology | HIGH | Fixed. Added paragraph before benchmarks table explaining simulator-based evaluation approach, its limitations, and that real-world validation requires prospective trials. |
| A3: Simulator calibration | HIGH | Fixed. Added "Calibrating the simulator" paragraph in "Simulation for Data Augmentation" section covering calibration approach, validation metrics, monitoring, and failure modes. |
| N1: VPC endpoint list | HIGH | Fixed. Expanded VPC row in Prerequisites table with complete endpoint list (S3 gateway, DynamoDB gateway, SageMaker API/Runtime, Step Functions, CloudWatch Logs, CloudWatch Monitoring, KMS). Added cost estimate. |
| R1: FDA regulatory pathway | HIGH | Fixed. Replaced single sentence with full paragraph covering CDS exemption under 21st Century Cures Act, De Novo classification, PCCP framework, and recommendation to consult regulatory counsel early. |
| V2: TODO placeholders | MEDIUM | Preserved. These are for TechWriter to resolve (citation verification). |
| A4: Lambda cold start | MEDIUM | Fixed. Updated Lambda description and benchmarks table to acknowledge cold start (1-3 seconds) as typical. Added provisioned concurrency option with cost. |
| A5: Drift detection | MEDIUM | Fixed. Added concrete drift detection specifics to CloudWatch description (KL divergence on input features, acceptance rate threshold, predicted vs. actual trajectory comparison). |
| S1: IAM permissions | MEDIUM | Fixed. Added `kms:Decrypt`, `kms:GenerateDataKey` (scoped to CMK ARN), `states:DescribeExecution`, `cloudwatch:PutMetricData`, `logs:CreateLogGroup`, `logs:PutLogEvents`. Added note to scope to specific resource ARNs. |
| S2: Model versioning | MEDIUM | Fixed. Added model versioning strategy as comments in Step 5 pseudocode (S3 versioning, current model pointer, rollback procedure, version ID in recommendations). |
| N2: TPS network path | MEDIUM | Fixed. Added network connectivity options to Clinical Integration prerequisite (Direct Connect, Site-to-Site VPN, API gateway with mTLS). |
| V3: Patient consent | LOW | Fixed. Added paragraph in "The Honest Take" about informed consent for AI-assisted treatment planning. |
| V4: Documentation-voice | LOW | Fixed. Changed "At a conceptual level, the system has two phases" to "The system splits cleanly into two phases: training (offline, periodic) and inference (daily, at the treatment machine)." |
| S3: DynamoDB TTL | LOW | Fixed. Added TTL/retention note to DynamoDB service description (archive to S3, delete after 90 days post-treatment). |

### From Code Review

| Finding | Severity | Action |
|---------|----------|--------|
| Issue 1: Confidence 0.0 semantics | WARNING | Noted. The main recipe already explains the pattern in Step 2 pseudocode comment. No change needed in main recipe. |
| Issue 2: SHAP vs perturbation | WARNING | No change needed in main recipe (pseudocode correctly uses SHAP; Python companion uses perturbation as a simpler alternative). |
| Issue 3: Missing similar_cases | WARNING | No change needed in main recipe (pseudocode includes `find_similar_historical`). |
| Issues 4-6 | NOTE | Python companion issues; no changes needed in main recipe. |

---

## Editorial Checklist

- [x] Grammar and mechanics: Clean
- [x] Code formatting: All blocks have language tags (text, pseudocode, mermaid, json)
- [x] Link verification: All URLs are well-formed AWS documentation links
- [x] Header hierarchy: H1 title, H2 major sections, H3 subsections, no skipped levels
- [x] Readability: Short paragraphs, active voice, no run-on sentences
- [x] Voice drift check: No documentation-voice, no em dashes, no feature-list formatting
- [x] Code block language tags: All 10 opening blocks have tags
- [x] RECIPE-GUIDE compliance: All required sections present in correct order
- [x] Vendor balance: Technology section entirely vendor-agnostic; AWS enters only in implementation section

---

## Deferred Items (TODO markers preserved)

5 TODO markers preserved for TechWriter to verify citations and add links:
- Offline RL in radiation therapy paper citations
- CQL paper citation (Kumar et al., NeurIPS 2020)
- BCQ paper citation (Fujimoto et al., ICML 2019)
- AAPM Task Group reports link
- ASTRO guidelines link
