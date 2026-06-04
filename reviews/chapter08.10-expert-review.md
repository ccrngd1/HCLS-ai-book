# Expert Review: Recipe 8.10 -- Phenotype Extraction for Research

**Reviewed by:** Technical Expert Panel (Security / Architecture / Networking / Voice)
**Recipe:** Chapter 08.10 -- Phenotype Extraction for Research
**Date:** 2026-06-04
**Severity Legend:** 🔴 Critical · 🟠 High · 🟡 Medium · 🔵 Low · ✅ Praise

---

## Executive Summary

Recipe 8.10 is a capstone-level recipe for Chapter 8, and it earns that status. The problem statement is genuinely compelling: explaining why chart review at scale is intractable, why phenotype definitions are inherently ambiguous, and why inter-rater reliability sets a ceiling on automated performance. The technology section is thorough and vendor-agnostic, covering entity extraction, assertion classification, temporal reasoning, and cross-document aggregation. The five-step pseudocode walkthrough is well-structured and maps cleanly to the architecture diagram.

The recipe has no CRITICAL findings. The security posture is solid (VPC endpoints listed, BAA called out, encryption at rest and in transit, IRB requirement noted). The architecture is sound for the stated scale. The honest take section is one of the best in the chapter: acknowledging that NLP isn't the bottleneck (the phenotype definition is) and calling out the cost trap with Comprehend Medical pricing at scale.

However, several HIGH findings require attention: the cost estimate in the prerequisites contradicts the cost discussed in the Honest Take section (creating reader confusion), the confidence threshold of 0.80 in the criteria evaluator is presented without justification, and the DynamoDB evidence store lacks a TTL or lifecycle discussion for research data retention. The recipe is close to publication-ready with targeted fixes.

**Verdict: PASS** (with required fixes for HIGH findings)

---

## Security Review

### 🟡 SEC-1: IAM Permissions List Includes `sagemaker:InvokeEndpoint` Without Scope Constraint

**Finding:** The prerequisites table lists `sagemaker:InvokeEndpoint` as a required IAM permission. This permission grants the ability to invoke any SageMaker endpoint in the account unless scoped with a resource ARN condition. In a shared research AWS account (common in academic medical centers), an unscoped `InvokeEndpoint` permission allows the phenotyping pipeline's Lambda role to call other teams' model endpoints, potentially exfiltrating PHI through a compromised or misconfigured model.

The recipe marks SageMaker as "(optional)" but includes the permission in the main prerequisites table without the optional qualifier on that specific line.

**Fix:** Add a resource ARN condition to the `sagemaker:InvokeEndpoint` permission: `"Resource": "arn:aws:sagemaker:*:*:endpoint/phenotype-*"` (scoped to endpoints with the phenotype prefix). Mark this permission line explicitly as "(optional, only if custom models are used)" in the prerequisites table. Add a note: "Scope SageMaker endpoint permissions to specific endpoint names or name prefixes. Never grant account-wide InvokeEndpoint in a shared research environment."

---

### 🟡 SEC-2: DynamoDB Evidence Store Contains PHI-Linkable Research Data Without Retention Policy

**Finding:** The DynamoDB evidence store accumulates per-patient, per-criterion evidence items including `patient_id`, `note_id`, `note_date`, `entity_text` (direct PHI such as medication names tied to a patient), and `section` context. For a 50,000-patient candidate pool, this table contains a comprehensive index of clinical assertions linked to patient identifiers.

The recipe does not discuss data retention, TTL policies, or when this evidence should be deleted. Research data governance typically requires that intermediate analysis artifacts be retained for the duration of the study plus a defined retention period (often 7 years for federally funded research), then destroyed. Without a TTL or lifecycle policy, this evidence accumulates indefinitely.

**Fix:** Add a "Data Retention" row to the prerequisites table: "Configure DynamoDB TTL on evidence items aligned with your IRB-approved data retention schedule. For completed studies, export final classifications to S3 (with lifecycle policies) and delete the evidence table. Intermediate NLP extraction results are not study data; they are processing artifacts and should have a shorter retention window than final classifications."

---

### 🟡 SEC-3: CloudTrail Requirement Should Specify Data Events for S3 and DynamoDB

**Finding:** The prerequisites state "Full API logging. Research reproducibility requires knowing exactly what was processed, when, and with what configuration." However, CloudTrail management events alone do not log S3 GetObject/PutObject calls or DynamoDB GetItem/PutItem/Query calls. These are data-plane events that require explicit CloudTrail data event configuration, which has additional cost (CloudTrail data events are priced per 100,000 events).

For a pipeline processing 50,000 patients with 40 notes each (2 million S3 GetObject calls, millions of DynamoDB writes), CloudTrail data events could add significant cost. The recipe should make this trade-off explicit rather than implying that "full API logging" is free or automatic.

**Fix:** Clarify in the prerequisites: "CloudTrail management events are enabled by default. For full research reproducibility audit trails, enable CloudTrail data events on the clinical notes S3 bucket and the DynamoDB evidence table. Note: data events are priced at ~$0.10 per 100,000 events. For a 50,000-patient run with 2M+ S3 reads and millions of DynamoDB writes, budget $200-500 for CloudTrail data event logging. Alternatively, implement application-level audit logging in CloudWatch Logs for per-patient processing records at lower cost."

---

### 🔵 SEC-4: Sample Data Section Should Explicitly Warn Against MIMIC-III/IV in Non-BAA Accounts

**Finding:** The prerequisites list "MIMIC-III/MIMIC-IV discharge summaries (requires PhysioNet credentialed access)" as sample data. While MIMIC data is de-identified under Safe Harbor, the PhysioNet Data Use Agreement restricts where and how the data can be stored and processed. Researchers sometimes assume "de-identified" means "no restrictions," but MIMIC's DUA requires credentialed access, prohibits redistribution, and requires specific institutional approvals.

The recipe correctly notes "Never use real patient data in development" but does not note that MIMIC data, while de-identified, still carries contractual use restrictions that may conflict with processing in some AWS accounts (particularly shared/sandbox accounts without proper DUA tracking).

**Fix:** Add a parenthetical: "MIMIC-III/MIMIC-IV discharge summaries (requires PhysioNet credentialed access and institutional DUA; store only in accounts where the DUA terms can be enforced; do not copy to shared development accounts without verifying DUA compliance)."

---

## Architecture Review

### 🟠 ARC-1: Cost Estimate in Prerequisites Contradicts the Honest Take Section

**Finding:** The prerequisites table states: "Cost Estimate: Comprehend Medical: ~$0.01 per 100 characters (entity detection). A typical 2000-character note = $0.20. Per patient with 40 notes = ~$8.00."

The Honest Take section states: "A single patient with 40 notes averaging 3,000 characters each is 120,000 characters through Comprehend Medical. At $0.01 per 100 characters, that's $12 per patient just for entity extraction."

These numbers are inconsistent. The prerequisites use 2,000-character notes ($8.00/patient), while the Honest Take uses 3,000-character notes ($12/patient). More importantly, the prerequisites understate the real cost because they only account for `DetectEntitiesV2`. The pipeline also calls `InferICD10CM` and `InferRxNorm` per note (as shown in the pseudocode), which are separate billable API calls at their own per-character rates. The true per-patient cost including all three APIs is approximately $16-24 depending on note length.

The header states "~$0.08 per patient record set" which appears to be completely wrong (off by two orders of magnitude from both estimates in the body).

**Fix:** Reconcile the cost estimates. Use consistent note length assumptions (3,000 characters is more realistic for clinical notes). Calculate the full cost including all three Comprehend Medical APIs (DetectEntitiesV2 + InferICD10CM + InferRxNorm). Update the recipe header cost to match. Add a note that the per-patient cost assumes selective processing (not all notes need ICD10/RxNorm inference), and show both "full processing" and "selective processing" cost estimates. Fix the header estimate: "$0.08 per patient record set" should likely be "$8-15 per patient record set" or similar.

---

### 🟠 ARC-2: Confidence Threshold of 0.80 Is Arbitrary and Not Justified

**Finding:** In the `evaluate_against_criteria` pseudocode, the code checks `IF attribute_match AND matched_entity.confidence >= 0.80` before accepting an entity as evidence. This threshold is presented without justification. Comprehend Medical confidence scores are not calibrated probabilities; a 0.80 score does not mean "80% chance of being correct." The optimal threshold depends on the specific entity type, the text style, and the precision/recall trade-off required by the phenotype.

For phenotyping research where positive predictive value (PPV) must exceed 95%, a 0.80 confidence threshold may be too permissive (admitting false positive extractions). For recall-sensitive phenotypes where missing cases is unacceptable, 0.80 may be too strict (dropping correct but lower-confidence extractions). The recipe provides no guidance on how to tune this threshold.

**Fix:** Replace the hardcoded 0.80 with a configurable parameter in the phenotype definition (e.g., `"min_confidence": 0.80` per criterion). Add a paragraph explaining: "The confidence threshold should be tuned per phenotype during the validation phase. Start with 0.70 to maximize recall, then increase incrementally while monitoring PPV on your validation set. Different criteria may require different thresholds: medication names (typically high confidence from Comprehend Medical) can use 0.85+, while complex multi-word conditions (where confidence is more variable) may need 0.70-0.75 to avoid missing valid extractions."

---

### 🟠 ARC-3: Step Functions Throughput Estimate of 200 Patients/Hour Is Unrealistically Low

**Finding:** The Expected Results table states "Throughput: ~200 patients/hour (conservative Step Functions throttling)." This implies severe throttling, but Step Functions Standard Workflows support 1,300 state transitions per second per account (default quota). A per-patient pipeline with ~10 state transitions (start, document retrieval, per-note processing, aggregation, classification, output) would support 130 patients per second at quota, not 200 per hour.

The actual bottleneck is Comprehend Medical API throughput (100 TPS default for DetectEntitiesV2), not Step Functions. With 40 notes per patient and 1 CM call per note, processing one patient requires 40 CM calls. At 100 TPS, you can process ~2.5 patients per second, or ~9,000 patients per hour. Even with the three-API pattern (DetectEntitiesV2 + InferICD10CM + InferRxNorm = 120 calls per patient), throughput is ~3,000 patients per hour at default quotas.

200 patients/hour is achievable only if you're running a single-threaded sequential pipeline with no parallelism, which contradicts the Lambda fan-out architecture shown in the diagram.

**Fix:** Revise the throughput estimate. With the described Lambda fan-out architecture, realistic throughput at default Comprehend Medical quotas is 1,000-3,000 patients/hour (depending on how many CM APIs are called per note and whether notes within a patient are parallelized). At increased quotas (500 TPS), throughput can reach 10,000+ patients/hour. Present throughput as a function of the Comprehend Medical quota: "Throughput is bottlenecked by Comprehend Medical API quotas, not Step Functions. At default 100 TPS: ~1,500 patients/hour. At 500 TPS (quota increase): ~7,500 patients/hour. Request quota increases proportional to your candidate pool size and timeline."

---

### 🟡 ARC-4: No Discussion of Comprehend Medical Character Limit Per API Call

**Finding:** Comprehend Medical's `DetectEntitiesV2` API has a maximum input size of 20,000 characters (UTF-8 encoded). Clinical notes, particularly discharge summaries and H&P notes, can exceed 20,000 characters. The pseudocode in Step 2 sends `note_text` directly to Comprehend Medical without any chunking logic.

If a note exceeds 20,000 characters, the API call fails with `TextSizeLimitExceededException`. The recipe's error handling section does not mention this failure mode. For a 50,000-patient pipeline, even 1% of notes exceeding the limit means hundreds of failed extractions.

**Fix:** Add chunking logic to the pseudocode in Step 2: "Notes exceeding 20,000 characters must be split at sentence boundaries (not mid-word or mid-entity). Process each chunk independently and merge results, deduplicating entities that span chunk boundaries. A typical chunking strategy: split at the last sentence boundary before 18,000 characters (leaving headroom for UTF-8 encoding differences)." Reference the character limit in the technology section or prerequisites.

---

### 🟡 ARC-5: Evidence Aggregation Does Not Handle Conflicting Evidence Across Notes

**Finding:** The aggregation pseudocode in Step 4 counts positive evidence and checks thresholds, but it does not explicitly handle a common real-world scenario: one note says "patient has major depressive disorder" (positive evidence for C1) and a later note says "depression resolved, patient in remission" (negative evidence for C1, or at minimum, a change in clinical status).

The recipe's problem statement mentions conflicting evidence ("one says 'depression,' another says 'adjustment disorder'") and the Expected Results section lists "Conflicting evidence across providers" as a failure mode. But the aggregation logic as written would still classify the patient as meeting C1 if there are 2+ positive mentions, regardless of whether a more recent note contradicts the diagnosis.

**Fix:** Add a temporal conflict resolution step in the aggregation function: "When evidence items for the same criterion include both POSITIVE and NEGATIVE assertions, apply temporal precedence: the most recent note's assertion takes priority for determining current status. For historical phenotypes (where 'ever had this condition' is the criterion), any positive assertion is sufficient regardless of later negation. Document which interpretation your phenotype uses (point-in-time vs. ever-had) in the phenotype definition."

---

### 🟡 ARC-6: Classification Logic Has a Bug in the "Partial Evidence" Path

**Finding:** In the `classify_patient` pseudocode (Step 5), the variable `partial_evidence` is set to `FALSE` in the first branch (`evidence_count == 0`) and `TRUE` in the second branch (`evidence_count > 0 but threshold not met`). However, if criterion C1 has zero evidence (sets `partial_evidence = FALSE`) and then criterion C2 has some evidence but not enough (sets `partial_evidence = TRUE`), the final value of `partial_evidence` depends on iteration order.

More critically: if C1 has partial evidence (`partial_evidence = TRUE`) but then C3 has zero evidence, `partial_evidence` is reset to `FALSE`. This means a patient with partial evidence for two criteria but zero evidence for a third is classified as "INSUFFICIENT_DATA" rather than "PROBABLE" (which seems wrong for a patient with substantial but incomplete evidence).

The logic conflates "any criterion has partial evidence" with "the most recently evaluated criterion has partial evidence."

**Fix:** Change `partial_evidence` from a simple boolean to a counter or use a separate flag: `any_partial_evidence = FALSE` that is set to `TRUE` whenever any criterion has evidence_count > 0 but doesn't meet threshold, and is never reset to FALSE. The classification logic should then use `any_partial_evidence` for the PROBABLE branch. The current code should also distinguish between "all criteria have zero evidence" (truly INSUFFICIENT_DATA) and "some criteria met, some have partial evidence" (PROBABLE).

---

### 🔵 ARC-7: TODO in Additional Resources Should Be Resolved

**Finding:** The Additional Resources section contains: "TODO: Verify availability of MIMIC-IV clinical notes for phenotyping benchmarks at PhysioNet." A TODO in a published recipe is unprofessional and signals incomplete work.

**Fix:** Either verify and add the MIMIC-IV link (it is available: https://physionet.org/content/mimic-iv-note/), or remove the TODO and replace with the verified link. MIMIC-IV-Note contains discharge summaries and radiology reports suitable for phenotyping benchmarks.

---

## Networking Review

### 🟡 NET-1: VPC Endpoint for Comprehend Medical Is Listed But May Not Support All APIs

**Finding:** The prerequisites state "Lambda in VPC with VPC endpoints for S3, DynamoDB, Comprehend Medical, and SageMaker." Amazon Comprehend Medical VPC endpoints (PrivateLink) exist, but the recipe uses three distinct Comprehend Medical APIs: `DetectEntitiesV2`, `InferICD10CM`, and `InferRxNorm`. All three are accessible through the same `com.amazonaws.{region}.comprehendmedical` VPC endpoint. This is correct.

However, the recipe does not specify which VPC endpoint types are needed (Interface vs. Gateway). S3 and DynamoDB support Gateway endpoints (free, no per-hour charge). Comprehend Medical and SageMaker require Interface endpoints (charged per hour per AZ). For a pipeline running for weeks during a large phenotyping run, the Interface endpoint cost (approximately $0.01/hour/AZ * 3 AZs * 24 hours * 30 days = ~$22/month per endpoint) across Comprehend Medical, SageMaker, and Step Functions adds up.

**Fix:** Add a parenthetical in the VPC prerequisites distinguishing Gateway endpoints (S3, DynamoDB: no hourly charge) from Interface endpoints (Comprehend Medical, SageMaker, Step Functions: ~$7.50/month per AZ per endpoint). For a 3-AZ deployment with 4 Interface endpoints, budget approximately $90/month for VPC endpoint charges during active pipeline runs. This is minor but should be in the cost estimate for completeness.

---

### 🔵 NET-2: No Egress Discussion for QuickSight Validation Dashboard

**Finding:** The architecture diagram shows a QuickSight validation dashboard as the final consumer of classification results. QuickSight is a managed service that does not run inside a VPC by default. If QuickSight accesses S3 results directly, it uses the QuickSight service role over the AWS network backbone (no public internet egress). However, if QuickSight connects to DynamoDB for real-time evidence exploration, it requires a VPC connection configured through QuickSight's VPC connectivity feature.

The recipe marks QuickSight as "(optional)" which is appropriate, but if included, the VPC connectivity configuration should be noted.

**Fix:** Add a note: "If using QuickSight to explore evidence in DynamoDB, configure QuickSight VPC connectivity to route queries through your VPC rather than the public internet. For S3-based reporting (reading classification JSONs), no VPC configuration is needed as QuickSight accesses S3 through the AWS backbone."

---

## Voice Review

### 🟡 VOC-1: The Technology Section Is Slightly Overlong and Could Lose Readers

**Finding:** The Technology section runs approximately 3,000+ words before reaching the AWS Implementation. While the content is excellent and vendor-agnostic (matching the 70/30 requirement), the subsections on "Why Phenotyping Is Hard" and "Where the Field Is in 2026" together add ~1,200 words that partially overlap with the Problem section's discussion of difficulty. The Problem section already establishes why this is hard (ambiguous definitions, inter-rater reliability, chart review cost). The Technology section then re-explains some of the same challenges (gold standard annotation, phenotype portability, prevalence).

The voice remains consistent throughout (engineer explaining, not documentation-voice), so this is not a tone issue. It's a structural redundancy that dilutes the momentum of the recipe.

**Fix:** Consider consolidating the "Why Phenotyping Is Hard" subsection by removing points already covered in the Problem section (inter-rater reliability appears in both sections, the ambiguity of definitions is discussed in both). Move unique points (portability across institutions, prevalence and class imbalance, reproducibility requirements) into a shorter "Additional Challenges" list at the end of the Technology section. Target a ~20% reduction in this subsection.

---

### ✅ VOC-2: No Em Dashes Found

Confirmed: zero em dashes in the recipe. Colons, semicolons, parentheses, and periods are used throughout as alternatives.

---

### ✅ VOC-3: Vendor Balance Is Excellent

The recipe maintains a strong 70/30 split. The entire Problem section and Technology section (approximately 4,000+ words) contain zero AWS service mentions. AWS appears only starting at "The AWS Implementation" heading. A reader on GCP or Azure would learn the complete conceptual framework for phenotype extraction from the first half alone.

---

### ✅ VOC-4: Voice Is Consistent and Authentic

The tone matches the style guide throughout. Examples of strong voice moments:
- "Easy, right? Not even close."
- "The math is unforgiving for rare phenotypes"
- "Here's what surprised me: the NLP isn't actually the bottleneck most of the time"
- "Paper-prototype your criteria. Have two clinicians independently classify 50 patients manually. Measure their agreement."

No documentation-voice detected. No marketing language. The engineer-explaining-over-lunch register is maintained even in the dense technical sections.

---

## Stage 2: Expert Discussion

**Conflict between ARC-1 (cost) and the overall quality of the Honest Take:** The Honest Take section is praised for its cost transparency, but it contradicts the prerequisites table. The Honest Take's numbers are more realistic. Resolution: fix the prerequisites to match the Honest Take's more accurate cost analysis.

**Overlap between ARC-5 (conflicting evidence) and the recipe's own "Where it struggles" list:** The recipe already acknowledges "Conflicting evidence across providers" as a failure mode. However, acknowledging a limitation in prose while the pseudocode ignores it creates a gap between what the reader is warned about and what the code demonstrates. Resolution: add conflict resolution logic to the pseudocode (at least a stub showing the pattern) rather than leaving it as a known gap.

**ARC-3 (throughput estimate) vs. the recipe's conservative framing:** The recipe intentionally frames throughput conservatively ("conservative Step Functions throttling"). However, being too conservative misleads readers about timeline planning. A researcher estimating timeline for 50,000 patients at 200/hour budgets 250 hours (~10 days). At the realistic 1,500/hour, it's 33 hours. Resolution: present a range rather than a single conservative number.

---

## Stage 3: Synthesized Findings

| ID | Severity | Expert | Location | Finding |
|----|----------|--------|----------|---------|
| ARC-1 | 🟠 High | Architecture | Prerequisites table + header + Honest Take | Cost estimate contradictions: header says $0.08/patient, prerequisites says $8/patient, Honest Take says $12/patient. All three are inconsistent. |
| ARC-2 | 🟠 High | Architecture | Step 3 pseudocode, `evaluate_against_criteria` | Confidence threshold 0.80 is hardcoded with no justification or tuning guidance |
| ARC-3 | 🟠 High | Architecture | Expected Results table | Throughput estimate of 200 patients/hour is 7-15x lower than realistic for the described architecture |
| SEC-1 | 🟡 Medium | Security | Prerequisites table, IAM Permissions | `sagemaker:InvokeEndpoint` unscoped; risky in shared research accounts |
| SEC-2 | 🟡 Medium | Security | Architecture (DynamoDB evidence store) | No data retention/TTL policy for PHI-linked research processing artifacts |
| SEC-3 | 🟡 Medium | Security | Prerequisites table, CloudTrail row | "Full API logging" claim requires data events, which have significant cost at scale |
| ARC-4 | 🟡 Medium | Architecture | Step 2 pseudocode | No chunking logic for notes exceeding Comprehend Medical's 20,000-character limit |
| ARC-5 | 🟡 Medium | Architecture | Step 4 pseudocode | No conflict resolution when positive and negative evidence exist for same criterion |
| ARC-6 | 🟡 Medium | Architecture | Step 5 pseudocode | `partial_evidence` boolean logic is buggy; resets on later criteria evaluation |
| VOC-1 | 🟡 Medium | Voice | Technology section | Structural redundancy between Problem and Technology sections on "why it's hard" |
| NET-1 | 🟡 Medium | Networking | Prerequisites, VPC section | No distinction between Gateway (free) and Interface (paid) VPC endpoints |
| ARC-7 | 🔵 Low | Architecture | Additional Resources | Unresolved TODO for MIMIC-IV link verification |
| SEC-4 | 🔵 Low | Security | Prerequisites, Sample Data | MIMIC data DUA restrictions not noted for non-BAA accounts |
| NET-2 | 🔵 Low | Networking | Architecture diagram (QuickSight) | QuickSight VPC connectivity not discussed for DynamoDB access |

---

## Verdict: PASS

The recipe has 0 CRITICAL findings and 3 HIGH findings (below the 4+ threshold for FAIL). The HIGH findings are straightforward to fix: reconcile cost numbers, justify/parameterize the confidence threshold, and correct the throughput estimate. The MEDIUM findings improve production-readiness but do not represent misinformation or compliance risk.

---

## Required Fixes Before Publication

1. **ARC-1 (Cost reconciliation):** Fix the recipe header cost ("~$0.08 per patient record set" is wrong by two orders of magnitude). Reconcile prerequisites table cost with the Honest Take's more accurate $12-15/patient estimate. Account for all three Comprehend Medical APIs in the calculation.

2. **ARC-2 (Confidence threshold):** Make the 0.80 threshold a configurable parameter in the phenotype definition JSON. Add guidance on how to tune it during validation (start permissive, tighten based on PPV requirements).

3. **ARC-3 (Throughput):** Replace "~200 patients/hour" with a range showing throughput as a function of Comprehend Medical API quota (e.g., "1,000-3,000 patients/hour at default quotas; 5,000-10,000 with quota increases"). Note that Step Functions is not the bottleneck.

---

## Specific Praise

### ✅ Problem Statement

One of the strongest problem statements in Chapter 8. The treatment-resistant depression example is clinically specific, relatable, and perfectly illustrates why phenotyping requires NLP (the "failed two adequate trials" criterion living exclusively in free text). The cost/time framing (15-30 minutes per patient, months of coordinator time) gives the reader concrete stakes.

### ✅ Phenotype Definition JSON

The structured phenotype definition in Step 1 is exceptionally well-designed. It clearly separates structured-data criteria from text criteria, specifies assertion requirements, defines evidence thresholds in human-readable language, and is version-controlled. This JSON alone could serve as a template for research teams defining new phenotypes.

### ✅ Honest Take Section

The insight that "the NLP isn't the bottleneck, the phenotype definition is" is the most important lesson in this recipe. The practical advice to "have two clinicians independently classify 50 patients manually" before building any infrastructure is genuinely actionable and would save readers months of wasted effort. The cost trap discussion (pre-filtering is "not optional at scale") is equally valuable.

### ✅ IRB and Data Governance Prerequisites

Including IRB approval and data governance framework as prerequisites (not just AWS requirements) demonstrates genuine understanding of the research computing environment. Most technical recipes ignore the institutional and regulatory layer entirely.

### ✅ Cross-Document Aggregation Architecture

Using DynamoDB as the evidence accumulation layer (keyed by patient + criterion) with a separate aggregation Lambda is architecturally clean. It separates the embarrassingly parallel document-level extraction from the patient-level reasoning, allows re-aggregation without re-extraction, and supports incremental evidence accumulation as new notes become available.

---

*Review complete. Recipe 8.10 is architecturally sound, clinically well-informed, and maintains excellent voice throughout. The three HIGH findings are arithmetic/parameterization issues, not fundamental design flaws. Fix those and this recipe is publication-ready.*
