# Expert Review: Recipe 6.2 -- Utilization Pattern Segmentation

**Reviewed by:** Technical Expert Panel (Security / Architecture / Networking / Voice)
**Recipe:** Chapter 6.2 -- Utilization Pattern Segmentation
**Date:** 2026-05-30
**Severity Legend:** 🔴 Critical · 🟠 High · 🟡 Medium · 🔵 Low · ✅ Praise

---

## Executive Summary

The main recipe file (`chapter06.02-utilization-pattern-segmentation.md`) does not exist. Only the Python companion (`chapter06.02-python-example.md`) is available for review. This is a CRITICAL finding: the expert review pipeline requires a main recipe to evaluate for clinical accuracy, architectural soundness, vendor balance, and completeness. The Python companion cannot be evaluated against pseudocode consistency, architecture diagrams, or the Problem/Technology/Build structure mandated by RECIPE-GUIDE.md because those sections have not been written.

The Python companion itself (reviewed below as supplementary analysis) is high-quality: well-structured, pedagogically sound, and implements a clean KMeans-based utilization segmentation pipeline with appropriate healthcare context. However, the absence of the main recipe means the full expert review cannot be completed.

**Verdict: FAIL**

The recipe fails due to 1 CRITICAL finding (main recipe file missing) which blocks the entire review process.

---

## Stage 1: Independent Expert Reviews

---

## Security Review (Based on Python Companion Only)

### 🟡 SEC-1: No KMS Customer-Managed Key Specified for S3 Writes

**Finding:** The `store_results()` function uses `ServerSideEncryption="aws:kms"` which defaults to the AWS-managed KMS key. For PHI workloads, organizations typically require a customer-managed key (CMK) for key rotation control, cross-account access policies, and audit trail granularity. The "Gap to Production" section mentions "KMS CMKs" but the code uses the default key.

**Location:** `store_results()`, `s3_client.put_object()` call.

**Fix:** This is acceptable for a teaching example (the Gap section acknowledges it). In the main recipe's Prerequisites table, specify: "Use a customer-managed KMS key (`SSEKMSKeyId` parameter) for production. The AWS-managed key is sufficient for development but does not provide key policy control or cross-account access management."

---

### 🟡 SEC-2: Member IDs in DynamoDB May Be Direct Identifiers

**Finding:** The code writes `member_id` (format: `MBR-000000`) as the DynamoDB partition key alongside utilization metrics (`ed_visits_12m`, `inpatient_admits_12m`, `total_allowed_12m`). If `member_id` maps directly to a health plan member identifier, this table contains individually identifiable utilization data (PHI). The code comments say "Never log member IDs or PHI in production" but the DynamoDB table design stores them without discussing access control.

**Location:** `store_results()`, DynamoDB `batch_writer` loop; Config section `RESULTS_TABLE_NAME`.

**Fix:** The main recipe (when written) should discuss: (1) whether member_id should be an opaque surrogate key, (2) IAM policy scoping for the DynamoDB table, (3) DynamoDB encryption at rest (enabled by default but should be explicitly stated). The Python companion's Gap section partially covers this under "VPC and encryption" but should add access control guidance.

---

### 🟡 SEC-3: No VPC Configuration in Code or Setup Section

**Finding:** The Setup section lists IAM permissions but does not mention VPC requirements. The Gap section states "A production pipeline handling member utilization data (which is PHI under HIPAA) runs inside a VPC with private subnets and VPC endpoints for S3 and DynamoDB." This is correct but the gap between the example (no VPC) and production (VPC required for PHI) should be more prominent.

**Location:** Setup section; Gap to Production section.

**Fix:** Add a callout in the Setup section: "This example runs without VPC configuration for simplicity. For any environment processing real member data, deploy within a VPC with private subnets and VPC endpoints for S3 and DynamoDB. See the main recipe's Prerequisites table for the full network architecture."

---

### ✅ SEC-PRAISE: PHI Awareness in Logging

The code includes `# Never log member IDs or PHI in production` and the logger statements only output aggregate counts and metrics, never individual member data. The Gap section explicitly calls out VPC, encryption, and HIPAA context. This demonstrates appropriate security awareness for a teaching example.

---

## Architecture Review (Based on Python Companion Only)

### 🔴 ARCH-CRITICAL: Main Recipe File Does Not Exist

**Finding:** The file `chapter06.02-utilization-pattern-segmentation.md` does not exist in the repository. The Python companion references it in its closing line: "See [Recipe 6.2: Utilization Pattern Segmentation](chapter06.02-utilization-pattern-segmentation) for the full architectural walkthrough, pseudocode, and honest take on where this gets hard." This link is broken. The RECIPE-GUIDE.md mandates a main recipe with: The Problem, The Technology, General Architecture Pattern, Why These Services, Architecture Diagram, Prerequisites, Ingredients, Pseudocode Walkthrough, Expected Results, The Honest Take, Variations, Related Recipes, and Additional Resources. None of these exist.

**Location:** Entire recipe. The main file is missing.

**Fix:** Write the main recipe file before this review can be completed. The Python companion is ready and waiting for its parent recipe.

---

### 🟡 ARCH-1: Fixed K=5 Without Elbow Method or Validation in Code

**Finding:** The code hardcodes `N_CLUSTERS = 5` with a comment "4-6 is typical for utilization segmentation." The Gap section discusses choosing k ("run the elbow method and silhouette analysis across k=3 to k=8") but the code doesn't demonstrate this. For a teaching example, showing how to validate k would be more instructive than hardcoding it.

**Location:** Config section, `N_CLUSTERS`; `cluster_members()` function.

**Fix:** This is acceptable for a teaching example given the Gap section's discussion. The main recipe should include a "Choosing k" subsection in the Technology section explaining the elbow method and silhouette analysis, with guidance on involving clinical stakeholders in the final decision.

---

### 🟡 ARCH-2: No Discussion of Segment Stability Across Runs in Code

**Finding:** The Gap section mentions segment stability ("if 30% of your population changes segments every month, your segments are unstable") but the code doesn't demonstrate any stability tracking. For a population health use case, segment stability is critical because care management programs are built around segments. The main recipe should address this architecturally.

**Location:** Gap to Production section (mentions it); no code implementation.

**Fix:** The main recipe should include segment stability as a first-class architectural concern, not just a production gap. Suggest: track segment transitions in a separate DynamoDB table or S3 dataset; require 2 consecutive qualifying runs before reassignment; alert when transition rates exceed thresholds.

---

### ✅ ARCH-PRAISE: Algorithm Selection Justification Is Excellent

The `cluster_members()` docstring provides a clear, honest justification for KMeans over DBSCAN, Gaussian Mixture, and hierarchical clustering. The tradeoff acknowledgment ("KMeans assumes spherical clusters of similar size. Real utilization data is skewed") is technically accurate and the explanation of why this is acceptable for the use case is well-reasoned.

---

### ✅ ARCH-PRAISE: Synthetic Data Generation Is Clinically Realistic

The population distribution (60% healthy, 20% episodic, 12% chronic, 5% rising risk, 3% high utilizer) aligns with typical commercial health plan populations. The feature correlations within each archetype (e.g., high utilizers have high ED visits AND high Rx fills AND high specialist visits) produce realistic multivariate patterns that will cluster meaningfully.

---

## Networking Review (Based on Python Companion Only)

### 🟡 NET-1: No VPC Endpoint Guidance for S3 and DynamoDB

**Finding:** The code makes direct API calls to S3 and DynamoDB without VPC endpoint configuration. The Gap section mentions "VPC endpoints for S3 and DynamoDB" but doesn't specify Gateway vs. Interface endpoints. For a batch pipeline writing 5,000+ items to DynamoDB and uploading JSON to S3, Gateway endpoints (free) are appropriate and should be specified.

**Location:** Gap to Production section, "VPC and encryption" paragraph.

**Fix:** The main recipe's Prerequisites table should specify: "S3 Gateway endpoint (free, route-table based) and DynamoDB Gateway endpoint (free). Interface endpoint for CloudWatch Logs. No Interface endpoints needed for S3/DynamoDB in this batch pattern."

---

### ✅ NET-PRAISE: TLS in Transit Is Implicit

All boto3 calls use HTTPS by default. The code doesn't disable certificate verification or use custom endpoints. This is correct baseline behavior.

---

## Voice Review (Based on Python Companion Only)

### 🟡 VOICE-1: Cannot Evaluate 70/30 Vendor Balance Without Main Recipe

**Finding:** The STYLE-GUIDE.md mandates 70% vendor-agnostic prose and 30% AWS-specific implementation. The Python companion is inherently 100% AWS-specific (it's boto3 code). The vendor balance can only be evaluated against the main recipe, which does not exist.

**Location:** Entire recipe (main file missing).

**Fix:** Write the main recipe with a substantial Technology section covering utilization segmentation concepts, KMeans fundamentals, feature engineering for healthcare claims data, and segment interpretation, all vendor-agnostic. The AWS-specific implementation section should be the minority of the prose.

---

### 🔵 VOICE-2: Python Companion Voice Is Strong

**Finding:** The Python companion's voice is excellent. The opening callout ("Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy against your entire member population on Monday morning") is exactly the right tone. Comments explain "why" not just "what." The Gap section is honest and comprehensive. No em dashes detected. No documentation-voice.

**Location:** Throughout the Python companion.

**Fix:** None needed. Preserve this voice in the main recipe.

---

### ✅ VOICE-PRAISE: Zero Em Dashes

Scanned the entire Python companion for em dashes (U+2014), en dashes (U+2013), and double-hyphen substitutes. None found. The recipe uses colons, semicolons, parentheses, and sentence restructuring throughout. Fully compliant with the style guide.

---

## Stage 2: Expert Discussion

**Primary conflict:** The CRITICAL finding (missing main recipe) renders most expert lenses unable to complete their full evaluation. Security, Architecture, and Networking reviews are limited to what can be inferred from the Python companion and its Gap section. Voice review cannot evaluate vendor balance.

**Resolution:** The CRITICAL finding takes absolute priority. The MEDIUM findings documented above are provisional: they identify concerns that the main recipe MUST address when written, based on what the Python companion reveals about the implementation approach.

**Cross-cutting observation:** The Python companion is unusually well-written for a file that precedes its parent recipe. The Gap section effectively serves as a requirements document for the main recipe's architecture and security sections. When the main recipe is written, it should address every concern raised in the Gap section as first-class architectural guidance, not afterthoughts.

**Bias and equity concern (from Python companion Gap section):** The statement "Members in underserved areas may appear 'healthy' (low utilization) when they're actually unable to access care" is critically important for this use case. The main recipe MUST address this in the Technology section and The Honest Take. Utilization-based segmentation without equity adjustment can systematically under-serve the populations that need the most help. This is both a clinical accuracy concern and an ethical obligation.

---

## Stage 3: Synthesized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| ARCH-CRITICAL | 🔴 CRITICAL | Architecture | Entire recipe | Main recipe file (`chapter06.02-utilization-pattern-segmentation.md`) does not exist. Python companion references it via broken link. Full architectural review impossible. | Write the main recipe following RECIPE-GUIDE.md structure before re-running expert review. |
| SEC-1 | 🟡 MEDIUM | Security | `store_results()`, S3 put_object | Uses AWS-managed KMS key; production requires CMK for PHI | Main recipe Prerequisites should specify CMK requirement |
| SEC-2 | 🟡 MEDIUM | Security | `store_results()`, DynamoDB writes | Member IDs stored without access control discussion | Main recipe should discuss opaque identifiers and IAM scoping |
| SEC-3 | 🟡 MEDIUM | Security | Setup section | No VPC mentioned in setup; gap to production is large | Add VPC callout in Setup; main recipe must specify full network architecture |
| ARCH-1 | 🟡 MEDIUM | Architecture | Config, `N_CLUSTERS` | Fixed k=5 without validation demonstration | Main recipe Technology section should cover k selection methodology |
| ARCH-2 | 🟡 MEDIUM | Architecture | Gap section (mentions stability) | Segment stability not architecturally addressed | Main recipe should treat stability as first-class design concern |
| NET-1 | 🟡 MEDIUM | Networking | Gap section, VPC paragraph | No Gateway vs. Interface endpoint specification | Main recipe Prerequisites should specify endpoint types |
| VOICE-1 | 🟡 MEDIUM | Voice | Entire recipe | Cannot evaluate 70/30 vendor balance without main recipe | Write main recipe with substantial vendor-agnostic Technology section |
| VOICE-2 | 🔵 LOW | Voice | Python companion throughout | Voice is strong; no issues | Preserve this voice in main recipe |

---

## Final Verdict: **FAIL**

The recipe fails due to 1 CRITICAL finding: the main recipe file does not exist. The Python companion is well-written and ready, but the expert review pipeline requires the main recipe (Problem, Technology, Architecture, Prerequisites, Pseudocode, Honest Take) to evaluate clinical accuracy, architectural soundness, vendor balance, and completeness.

**To resolve:** Write `chapter06.02-utilization-pattern-segmentation.md` following RECIPE-GUIDE.md structure, then re-run this expert review. The Python companion's Gap section provides an excellent roadmap for what the main recipe should cover.

---

## Provisional Guidance for Main Recipe (When Written)

Based on the Python companion analysis, the main recipe MUST address:

1. **Equity and bias** (Technology section): Utilization-based segmentation encodes access disparities. Low utilization may indicate barriers, not health. Cross-reference with SDOH data. This is not optional.

2. **Segment stability** (Architecture section): Members shift between segments over time. Define a stability mechanism (2-run qualification, rolling windows, transition tracking). Care managers cannot build programs around unstable segments.

3. **Choosing k** (Technology section): Explain elbow method, silhouette analysis, and clinical validation. The "right" k depends on how many distinct intervention programs the organization can operate.

4. **Feature engineering depth** (Technology section): The Python companion uses 8 raw features. Discuss derived features (ED-to-outpatient ratio, Rx complexity, care fragmentation, trend features) that improve segment separation in production.

5. **VPC and encryption** (Prerequisites): Full network architecture with Gateway endpoints for S3/DynamoDB, private subnets, CMK for S3 encryption, DynamoDB encryption at rest.

6. **Access control** (Prerequisites/Architecture): The segment assignments table contains utilization data for the entire member population. Specify IAM role decomposition, opaque identifiers, and sensitivity classification.

---

## Additional Notes

**Python companion strengths worth preserving:**
- The synthetic data generation with realistic population distributions is excellent teaching material
- The algorithm selection justification (KMeans over alternatives) is clear and honest
- The silhouette score interpretation with healthcare-specific ranges (0.3-0.5 typical) is accurate
- The Gap to Production section is comprehensive and covers the right concerns
- The bias/equity callout is critically important and well-stated
- DynamoDB Decimal handling is correct and the gotcha is documented
- The "sketchpad version" framing in the opening callout sets appropriate expectations

**Domain accuracy validation (Python companion):**
- KMeans for utilization segmentation: Standard and appropriate approach
- 5 segments (Healthy, Episodic, Chronic, Rising Risk, High Utilizer): Matches common population health taxonomy
- Population distribution (60/20/12/5/3): Realistic for commercial health plan
- Feature set (ED visits, inpatient, outpatient, Rx, preventive, specialist, telehealth, cost): Covers the key utilization dimensions
- StandardScaler before KMeans: Correct (prevents cost column from dominating Euclidean distance)
- 99th percentile outlier clipping: Appropriate for healthcare cost data (heavy right tail)
- Silhouette score 0.3-0.5 for utilization data: Accurate expectation
- Cost-based segment ordering: Reasonable heuristic for initial labeling (validated by clinical review in production)
