# Expert Review: Recipe 14.2 - Patient-Provider Assignment

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-06-01
**Recipe file:** `chapter14.02-patient-provider-assignment.md` (MISSING)
**Python companion:** `chapter14.02-python-example.md` (exists)

---

## Overall Assessment

The main recipe file (`chapter14.02-patient-provider-assignment.md`) does not exist. The sidebar references it, the Python companion references it, and the code review references pseudocode steps from it, but the file has not been written. This is a CRITICAL finding: the expert review cannot assess the recipe's architecture section, problem statement, technology explanation, vendor balance, prerequisites, or honest take because they do not exist.

The Python companion is well-written and was already code-reviewed. Based on the companion's content and the code review, I can assess certain architectural and security aspects of the implied design. However, this review is necessarily incomplete without the main recipe.

---

## Stage 1: Independent Expert Reviews

---

## Security Expert Review

### What's Done Well (in Python companion)

The companion correctly uses Decimal conversion for DynamoDB floats. The boto3 retry config uses adaptive mode. The "Gap to Production" section explicitly calls out IAM least-privilege, VPC + VPC endpoints, KMS CMKs, and the fact that assignment rationale text (mentioning patient conditions) is PHI. The DynamoDB item schema uses a `status: "proposed"` field indicating human review before EHR write-back.

### Issue S1: Main Recipe Missing Prevents Security Assessment (CRITICAL)

**Location:** Entire recipe

**The problem:** Without the main recipe, there is no Prerequisites table specifying IAM permissions, BAA requirements, encryption configuration, VPC setup, or CloudTrail requirements. The Python companion's "Gap to Production" section mentions these concerns in prose, but the structured security specification that readers rely on (the Prerequisites table) does not exist.

**Suggested fix:** Write the main recipe file.

### Issue S2: Patient Conditions Stored in Rationale Text Without Encryption Discussion (HIGH)

**Location:** Python companion, Step 4 `store_assignments()`, the `rationale` field

**The problem:** The rationale field contains strings like "Complex patient matched to internist" and the scoring function references `patient["conditions"]` (diabetes, hypertension, CKD, CHF, COPD, depression). While the stored rationale doesn't directly list conditions, the `patient_complexity` field is stored alongside the assignment. More importantly, the companion's "Gap to Production" section acknowledges "The assignment rationale text (which mentions patient conditions) is also PHI" but the actual code stores `patient_complexity: record["patient_complexity"]` in DynamoDB without any discussion of field-level encryption or access controls on this PHI element.

In the main recipe (when written), the architecture must specify that the DynamoDB table uses KMS encryption at rest and that the rationale/complexity fields are treated as PHI with appropriate access controls.

**Suggested fix:** When the main recipe is written, ensure the Prerequisites table specifies KMS CMK encryption for the DynamoDB table and that access to the assignments table is restricted to the panel management team's IAM roles.

### Issue S3: No Authentication on the "Review Dashboard" (MEDIUM)

**Location:** Python companion, "Gap to Production" section and Step 4

**The problem:** The companion references a "panel management team reviews these in a dashboard" workflow but provides no guidance on how that dashboard authenticates users or authorizes access. The DynamoDB items contain PHI (patient IDs, complexity levels, provider assignments). The dashboard must enforce role-based access so that only authorized panel managers can view and approve assignments.

**Suggested fix:** When the main recipe is written, include a note that the review dashboard requires authentication (Cognito or enterprise SSO) and that access is scoped to the user's department/practice.

---

## Architecture Expert Review

### What's Done Well (in Python companion)

The optimization formulation is structurally correct: binary integer program with linear objective and linear constraints. The choice of PuLP with CBC solver is appropriate for the problem scale (hundreds of patients, dozens of providers). The multi-factor scoring function (language, gender preference, complexity, panel balance, continuity) reflects real clinical panel management priorities. The batch-then-review workflow (optimize, validate, store as "proposed," human approves) is the right pattern for this domain.

### Issue A1: Main Recipe Missing Prevents Architecture Assessment (CRITICAL)

**Location:** Entire recipe

**The problem:** Without the main recipe, there is no General Architecture Pattern, no AWS-specific architecture diagram, no discussion of how this fits into the broader EHR ecosystem, no Step Functions orchestration design, and no discussion of batch vs. incremental assignment modes. The Python companion's "Gap to Production" section hints at these concerns but doesn't provide the architectural guidance that the recipe format requires.

**Suggested fix:** Write the main recipe file.

### Issue A2: Capacity Constraint Formulation is Mathematically Incorrect (HIGH)

**Location:** Python companion, Step 2 `solve_assignment()`, Constraint 2

**The problem:** Already identified in the code review (Finding 1), but from an architecture perspective this is more concerning. The capacity constraint uses `remaining_capacity * avg_freq_weight / 4` which is ~2.25x more permissive than intended. For a teaching recipe about optimization, having an incorrect constraint formulation undermines the educational value. A reader implementing this pattern at scale (500 patients from a departing provider's panel across 30 providers) would get assignments that violate panel limits.

The `/4` divisor has no documented rationale. It appears to be a bug rather than a deliberate safety margin.

**Suggested fix:** Fix the constraint to `weighted_load <= remaining_capacity * avg_freq_weight` (or equivalently, `weighted_load / avg_freq_weight <= remaining_capacity`). Add a comment explaining the normalization: "Each patient's frequency weight is measured in annual visits. Remaining capacity is in patient slots. We multiply remaining capacity by the average frequency weight to convert both sides to the same unit."

### Issue A3: No Discussion of Incremental vs. Batch Assignment (MEDIUM)

**Location:** Python companion, "Gap to Production" section

**The problem:** The companion mentions "you need both batch (provider departure, panel rebalancing) and incremental (single new patient calls to schedule)" but doesn't discuss how the architecture handles the incremental case. In practice, the incremental case (new patient calls, needs a PCP assigned immediately) is the more common scenario and has different latency requirements (seconds, not minutes). The batch optimizer can't serve this use case. The main recipe (when written) should discuss both modes and how they coexist.

**Suggested fix:** When the main recipe is written, include a subsection on batch vs. incremental assignment. The incremental case can use a simplified greedy approach (pick the highest-scoring available provider) while the batch case uses the full optimizer. Both should respect the same constraints and scoring logic.

### Issue A4: No Fairness Monitoring Architecture (MEDIUM)

**Location:** Python companion, "Gap to Production" section

**The problem:** The companion mentions "audit the results for unintended bias" and "build dashboards that track assignment patterns by patient demographics" but provides no architectural guidance on how to implement this. For a healthcare optimization system, fairness monitoring is not optional. If the scoring function inadvertently assigns patients of certain demographics to less experienced providers (e.g., because language concordance correlates with provider seniority), the system could perpetuate disparities.

**Suggested fix:** When the main recipe is written, include a "Fairness and Bias" subsection in the Honest Take or Variations section. At minimum: log all assignments with patient demographics, run periodic statistical tests (chi-square on assignment distributions by race/ethnicity/language), and alert if any provider's panel demographics deviate significantly from the practice's overall patient demographics.

---

## Networking Expert Review

### Issue N1: Main Recipe Missing Prevents Networking Assessment (CRITICAL)

**Location:** Entire recipe

**The problem:** Without the main recipe, there is no Prerequisites table specifying VPC configuration, VPC endpoints, security groups, or data-in-transit encryption. The Python companion's "Gap to Production" section mentions "Lambda or SageMaker Processing jobs run in a VPC with no internet access, using VPC endpoints for DynamoDB and S3" but this is prose guidance, not the structured specification the recipe format requires.

**Suggested fix:** Write the main recipe file. When written, ensure VPC endpoints are specified for DynamoDB (gateway), S3 (gateway), and CloudWatch Logs (interface). If using Lambda in VPC, specify that the Lambda security group allows outbound HTTPS to VPC endpoint prefix lists.

---

## Voice Reviewer

### Issue V1: Main Recipe Missing Prevents Voice Assessment (CRITICAL)

**Location:** Entire recipe

**The problem:** Cannot assess voice, tone, vendor balance, or em dash compliance without the main recipe file.

### Issue V2: Python Companion Voice is Strong (PASS)

**Location:** Python companion throughout

**The problem:** N/A. The Python companion maintains the cookbook's conversational voice well. The opening callout ("Think of it as the sketchpad version: useful for understanding the shape of the solution, not something you'd deploy to your panel management system on Monday morning") is on-brand. Comments explain clinical reasoning in accessible language. The "Gap to Production" section is honest and specific.

---

## Stage 2: Expert Discussion

### Core Issue

All four expert lenses converge on the same fundamental problem: the main recipe file does not exist. The Python companion is well-written and the code review passed, but the recipe pipeline requires the main recipe to be written before the expert review can meaningfully assess architecture, security posture, networking configuration, and voice compliance.

### Secondary Concerns

The capacity constraint bug (A2/code review Finding 1) is the most significant technical issue in the existing content. It's a mathematical error that would produce incorrect results at production scale. This should be fixed regardless of the main recipe's status.

The PHI-in-rationale concern (S2) and the missing fairness monitoring (A4) are design-level issues that the main recipe should address when written.

---

## Stage 3: Synthesized Feedback

## Verdict: **FAIL**

The main recipe file (`chapter14.02-patient-provider-assignment.md`) does not exist. The expert review cannot assess the recipe's architecture, security specification, networking configuration, vendor balance, or voice compliance without it. This is a CRITICAL finding that automatically fails the review. The Python companion is well-written but cannot substitute for the main recipe.

---

## Prioritized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| 1 | CRITICAL | All | Entire recipe | Main recipe file `chapter14.02-patient-provider-assignment.md` does not exist. Cannot assess architecture, security, networking, or voice. | Write the main recipe file following RECIPE-GUIDE.md structure |
| 2 | HIGH | Architecture | Python companion, Step 2, Constraint 2 | Capacity constraint uses `remaining_capacity * avg_freq_weight / 4` which is ~2.25x more permissive than intended; `/4` divisor has no documented rationale | Fix to `weighted_load <= remaining_capacity * avg_freq_weight` or document the divisor as intentional safety margin |
| 3 | HIGH | Security | Python companion, Step 4 | Patient complexity (PHI-adjacent) stored in DynamoDB without encryption or access control discussion in a structured Prerequisites table | Main recipe must specify KMS CMK encryption and IAM access controls for the assignments table |
| 4 | MEDIUM | Architecture | Python companion, "Gap to Production" | No architectural guidance on incremental (real-time single-patient) vs. batch assignment; incremental is the more common production scenario | Main recipe should discuss both modes and how they coexist with shared scoring logic |
| 5 | MEDIUM | Architecture | Python companion, "Gap to Production" | No fairness monitoring architecture; optimization could perpetuate demographic disparities in panel composition | Main recipe should include fairness monitoring: log demographics, run periodic statistical tests, alert on skewed distributions |
| 6 | MEDIUM | Security | Python companion, "Gap to Production" | Review dashboard referenced but no authentication/authorization design specified | Main recipe should specify Cognito or enterprise SSO with role-based access scoped to department |

---

## Summary

This review cannot pass because the main recipe file has not been written. The Python companion is solid (the code review passed with minor findings), but the cookbook's pipeline requires the main recipe to exist before expert review can meaningfully assess the design. The capacity constraint bug in the Python companion should be fixed regardless. When the main recipe is written, it should address: structured security prerequisites (encryption, IAM, BAA), VPC and networking configuration, batch vs. incremental assignment modes, fairness monitoring, and the standard recipe voice/vendor balance requirements.

**Action required:** Write `chapter14.02-patient-provider-assignment.md` following RECIPE-GUIDE.md, then re-run expert review.
