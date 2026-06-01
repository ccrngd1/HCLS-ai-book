# Expert Review: Recipe 9.7 - Radiology AI Triage (Multi-Modality)

**Reviewer:** Technical Expert Panel (Security · Architecture · Networking · Voice)
**Date:** 2026-05-31
**Verdict:** PASS
**Blocking Issues:** 0
**Advisory Issues:** 7

---

## Executive Summary

Recipe 9.7 is one of the strongest recipes in the cookbook. The problem statement is visceral and clinically accurate. The technology section teaches multi-modality inference orchestration from first principles without vendor lock-in. The architecture is sound for the stated scale, the FDA regulatory context is correctly framed, and the "Honest Take" section demonstrates genuine domain expertise (false positive trust erosion, PACS vendor integration as the real bottleneck). No blocking issues were found. Seven advisory items should be addressed or explicitly accepted as known gaps.

---

## Security Review

### Advisory S-1: IAM Permissions Use Wildcard for HealthImaging

**Finding:** The Prerequisites table lists `medical-imaging:*` as the required IAM permission. This violates least-privilege. HealthImaging supports granular actions: `medical-imaging:GetImageFrame`, `medical-imaging:SearchImageSets`, `medical-imaging:GetImageSet`, `medical-imaging:GetImageSetMetadata`, and `medical-imaging:CreateDatastore` / `medical-imaging:StartDICOMImportJob` for ingestion. The triage pipeline's inference path only needs read access to pixel data and metadata; it should not have `DeleteImageSet` or `DeleteDatastore` permissions.

**Location:** Prerequisites table, "IAM Permissions" row.

**Fix:** Replace `medical-imaging:*` with the specific actions needed:

```
medical-imaging:GetImageFrame, medical-imaging:GetImageSet,
medical-imaging:GetImageSetMetadata, medical-imaging:SearchImageSets,
medical-imaging:StartDICOMImportJob (for the ingestion path only)
```

Add a note that the DICOM receiver component needs write permissions (`StartDICOMImportJob`) while the inference pipeline needs only read permissions, and these should be separate IAM roles.

---

### Advisory S-2: SageMaker Endpoint IAM Role Not Scoped

**Finding:** The recipe mentions `sagemaker:InvokeEndpoint` but does not specify resource-level scoping. In a multi-model deployment with 4+ endpoints (ICH, CXR, PE, Spine), the Lambda orchestrator's IAM policy should scope `InvokeEndpoint` to the specific endpoint ARNs, not `*`. Without resource scoping, a compromised Lambda could invoke any SageMaker endpoint in the account, including non-radiology models that may have different data access patterns.

**Location:** Prerequisites table, "IAM Permissions" row.

**Fix:** Add a note: "Scope `sagemaker:InvokeEndpoint` to specific endpoint ARNs using resource conditions. Each model endpoint should have its own resource entry in the policy."

---

### Advisory S-3: Model Version Audit Trail Incomplete

**Finding:** The recipe correctly logs `model_versions` in the audit event (Step 5) and shows it in the expected output. However, the audit log does not capture the preprocessing pipeline version. If a preprocessing bug is discovered (e.g., incorrect windowing that caused false negatives for a period), you need to trace which preprocessing version was active for each inference. FDA 21 CFR Part 11 and the SaMD guidance expect full traceability of the software version that produced a clinical output, which includes preprocessing.

**Location:** Step 5 pseudocode, `log_audit_event` call.

**Fix:** Add `preprocessing_versions` to the audit event alongside `model_versions`. This can be a simple version string per model's preprocessing pipeline (e.g., `{"ich_preprocessing": "v1.2.0", "cxr_preprocessing": "v1.0.3"}`).

---

## Architecture Review

### Advisory A-1: Study Completion Detection Strategy Needs Failure Mode Discussion

**Finding:** Step 1 describes the study completion detection problem well and proposes a 60-second timeout. The pseudocode comment mentions an alternative (comparing received count against expected count). However, neither approach handles the failure mode where a scanner drops connection mid-transfer. A CT head that should have 200 slices but only 150 arrive before the scanner crashes will trigger the 60-second timeout and proceed to inference on an incomplete volume. The ICH model may produce a false negative because the hemorrhage was in slices 160-180 (never received).

**Location:** Step 1 pseudocode and surrounding explanation.

**Fix:** Add a brief note on the incomplete study failure mode: "If the received instance count is significantly below the expected count for the study type (e.g., a CT head with fewer than 100 slices when 150-300 is typical), flag the study as potentially incomplete and either skip inference or run with a lowered confidence threshold. Log incomplete studies for manual review." This does not need to be a full implementation; a callout noting the risk is sufficient.

---

### Advisory A-2: Multi-Model Endpoint vs. Dedicated Endpoint Tradeoff Not Discussed

**Finding:** The "Why These Services" section mentions both multi-model endpoints and dedicated endpoints but does not recommend one over the other or explain the tradeoff. For a safety-critical triage system, this matters: multi-model endpoints share GPU memory and can have cold-start latency when switching between models. A CT head arriving when the endpoint has the PE model loaded requires a model swap, adding 10-30 seconds of latency. For a system targeting sub-2-minute latency on critical findings, this cold-start penalty could be the difference between meeting and missing the SLA.

**Location:** "Why These Services" section, SageMaker paragraph.

**Fix:** Add a sentence: "For production triage systems with strict latency SLAs, use dedicated endpoints per model (one endpoint per modality/finding type). Multi-model endpoints reduce cost but introduce model-loading latency that is unacceptable for safety-critical triage. The cost estimate in this recipe assumes dedicated always-on endpoints."

---

### Advisory A-3: No Dead Letter Queue or Error Handling in Step Functions

**Finding:** The recipe uses Step Functions for orchestration and mentions "built-in retry logic, error handling, and execution history." However, the pseudocode and architecture do not show what happens when inference fails (SageMaker endpoint timeout, model error, preprocessing crash). A failed triage means the study stays at default priority in the worklist. This is the safe failure mode (no false elevation), but it should be explicitly stated and monitored. If the system silently fails on 5% of studies, those studies get no triage benefit and nobody knows.

**Location:** Architecture description and Step 5.

**Fix:** Add a brief note: "Configure Step Functions error handling to catch inference failures and write a 'TRIAGE_FAILED' status to DynamoDB. Monitor the failure rate via CloudWatch. A study that fails triage remains at routine priority (safe default), but persistent failures indicate a system health issue that requires investigation. Consider an SNS alert if the triage failure rate exceeds 1% over a rolling window."

---

## Networking Review

### Advisory N-1: DICOM Receiver Network Architecture Underspecified

**Finding:** The Prerequisites table states "DICOM receiver in private subnet with NLB for scanner connectivity." This is correct but incomplete. DICOM C-STORE from scanners typically uses port 104 or 11112. Scanners on the hospital network need a route to the NLB. In most healthcare environments, scanners are on a segmented VLAN that does not have direct internet or VPC connectivity. The connection path is typically: Scanner VLAN → hospital firewall → site-to-site VPN or Direct Connect → VPC private subnet → NLB → DICOM receiver EC2. This network path introduces latency and requires firewall rules that hospital IT must configure. The recipe should acknowledge this as an integration dependency.

**Location:** Prerequisites table, "VPC" row.

**Fix:** Add a note: "Scanner connectivity requires a network path from the hospital imaging VLAN to the VPC private subnet. This is typically achieved via AWS Direct Connect or site-to-site VPN. Coordinate with hospital network engineering for firewall rules allowing DICOM traffic (TCP port 104 or 11112) from scanner IPs to the NLB. This network setup is a common source of deployment delays; budget 2-4 weeks for network provisioning at each site."

---

## Voice Review

### Findings

**Em dashes:** Zero found. Compliant.

**Vendor balance:** The recipe maintains strong vendor-agnostic teaching in "The Problem" and "The Technology" sections. AWS services appear only in "The AWS Implementation" section. The 70/30 split is well-maintained. The technology section is substantial (covering CNNs, multi-model orchestration, DICOM ecosystem, and integration challenges) before any AWS service is mentioned.

**Tone:** Consistent with the style guide throughout. The opening scenario (study at position 47, neurosurgeon waiting) is exactly the kind of visceral problem statement the guide calls for. Parenthetical asides are used naturally ("(ok, this is a gross oversimplification, but stay with me)" energy is present without being forced). The "Honest Take" reads like genuine field experience, not manufactured humility.

**Documentation-voice creep:** None detected. No "This recipe demonstrates how to leverage..." patterns. No marketing language. The writing reads like an engineer explaining a system they've built and deployed.

**No issues found in voice review.**

---

## Stage 2: Expert Discussion

**Conflict resolution:** No conflicts between expert lenses. The security findings (S-1, S-2) are complementary to the architecture findings (A-1, A-2, A-3). The networking finding (N-1) is independent and additive.

**Priority ordering:** S-1 (IAM wildcard) and A-2 (multi-model endpoint latency) are the most impactful for a reader who takes this recipe to production. S-3 (preprocessing version audit) matters for FDA compliance but is a detail that most teams discover during regulatory submission. A-1 (incomplete study) and A-3 (error handling) are operational concerns that become apparent in the first month of production.

---

## Stage 3: Synthesized Verdict

**VERDICT: PASS**

This recipe is publication-ready with advisory fixes recommended. No blocking issues were found. The clinical accuracy is strong, the architecture is sound for the stated scale, HIPAA/FDA considerations are appropriately addressed, and the writing quality is high. The seven advisory items improve the recipe but their absence does not create safety risks or mislead readers.

---

## Issues Summary

| ID | Severity | Category | Issue |
|---|---|---|---|
| S-1 | MEDIUM | Security | IAM wildcard `medical-imaging:*` violates least-privilege |
| S-2 | LOW | Security | SageMaker InvokeEndpoint not resource-scoped to specific endpoints |
| S-3 | MEDIUM | Security | Preprocessing pipeline version not included in FDA audit trail |
| A-1 | MEDIUM | Architecture | Incomplete study failure mode (partial transfer) not discussed |
| A-2 | MEDIUM | Architecture | Multi-model vs. dedicated endpoint latency tradeoff not stated |
| A-3 | MEDIUM | Architecture | No error handling / DLQ discussion for failed inference |
| N-1 | LOW | Networking | Scanner-to-VPC network path (Direct Connect/VPN) not acknowledged |

---

## What the Recipe Does Well

- The problem statement is clinically accurate and emotionally compelling. The "study at position 47" scenario is real and well-known in radiology operations.
- The technology section is genuinely educational: it teaches CNNs for medical imaging, the multi-model orchestration challenge, DICOM ecosystem complexity, and integration challenges without any vendor names. A reader on any cloud learns something valuable.
- FDA regulatory context is correctly framed: 510(k) pathway, per-indication clearance, 12-18 month timeline. This is accurate and sets realistic expectations.
- The false positive management discussion is the most important operational insight in the recipe. The "15-20% flagged in the first week, ignored by day three" anecdote rings true and will save readers from the most common deployment failure mode.
- PACS vendor integration is correctly identified as the project-killing risk. The 3-6 month per-site estimate and the warning about cross-site variability are accurate.
- The confidence threshold approach (conservative at launch, tune over time) is the correct clinical strategy.
- Cost estimates are reasonable and well-structured (per-study breakdown by modality, monthly infrastructure costs).
- The architecture pattern (DICOM Router → Study Classifier → Model Selector → Inference → Aggregator → Worklist) is clean and correctly separates concerns.
- VPC endpoint guidance is comprehensive and correctly lists all required endpoints for a private subnet deployment.
- BAA requirement is prominently stated.
- The "Where it struggles" section is honest and clinically accurate (subtle findings, motion artifact, post-surgical anatomy, multi-finding masking).
- Related recipes are well-chosen and the connections are clearly explained.
- Implementation timeline estimates (3-4 months basic, 12-18 months production, 18-24 months with variations) are realistic for this domain.

---

*Review completed 2026-05-31. All issues are advisory. Recipe is approved for publication. Advisory items should be addressed in a polish pass or explicitly accepted as known gaps.*
