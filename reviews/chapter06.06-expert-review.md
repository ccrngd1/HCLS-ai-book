# Expert Review: Recipe 6.6 - Patient Similarity for Care Planning

**Reviewed by:** Technical Expert Panel (Security, Architecture, Networking, Voice)
**Date:** 2026-05-31
**Recipe file:** `chapter06.06-patient-similarity-care-planning.md`

---

## Overall Assessment

This is a strong recipe. The problem framing is compelling, the technology section teaches patient similarity from first principles without vendor lock-in, and the "Honest Take" section is genuinely honest about the limitations. The pseudocode is well-commented and accessible to non-developers. The clinical context (feature selection requiring domain expertise, bias amplification risks, explainability requirements) elevates this beyond a generic kNN tutorial.

However: there are meaningful gaps in the security posture around PHI in the similarity results, a missing consent/governance discussion that is critical for this use case, and some architectural choices that need tightening for a healthcare enterprise deployment. The voice is consistent and strong throughout.

**Verdict: PASS**

Priority breakdown: 0 critical, 3 high, 5 medium, 4 low.

---

## Stage 1: Independent Expert Reviews

### Security Expert Review

#### What's Done Well

BAA requirement is explicit. Encryption at rest (SSE-KMS for S3, encryption at rest for DynamoDB) and in transit (TLS) are specified. CloudTrail for audit logging is included. The "never use real PHI in development" warning is present. VPC placement for Lambda and SageMaker endpoint is recommended for production. The separation of feature store (derived data) from raw EHR data is architecturally sound from a PHI minimization perspective.

#### Issue S1: Similarity Results Expose Patient IDs of Other Patients (HIGH)

**Location:** Step 3 pseudocode (`find_similar_patients`), Step 5 (`store_and_present`), and Expected Results JSON

**The problem:** The similarity query for Patient A returns the patient IDs of Patients B, C, D (the similar patients). These IDs are stored in DynamoDB cache and returned to the care planning UI. The sample output shows `"patient_id": "PAT-2024-12091"` in the `top_similar_patients` array. This means querying one patient's similarity reveals the existence and characteristics of other patients in the system.

In a healthcare context, this creates a cross-patient PHI exposure surface. A care manager querying Patient A now has access to the identifiers of Patients B, C, and D, plus implicit knowledge about their conditions (they're similar to Patient A, so they share diagnoses and characteristics). The recipe mentions "de-identified in the UI" in the presentation layer but the underlying data store and API response contain real patient IDs.

**Suggested fix:** Add a section addressing access control for similarity results. Options: (1) return only aggregated outcome statistics without individual patient IDs (sufficient for most care planning use cases), (2) use opaque session-scoped identifiers that cannot be resolved outside the similarity context, (3) require explicit "break the glass" authorization to drill into individual similar patient records. The recipe should take a position on which approach is appropriate and explain the PHI implications of each.

#### Issue S2: DynamoDB Cache TTL Does Not Address PHI Retention (MEDIUM)

**Location:** Step 5 pseudocode, `ttl: current_utc_timestamp() + 86400`

**The problem:** The cache stores similarity results (including patient IDs of similar patients and their outcome summaries) with a 24-hour TTL. DynamoDB TTL deletion is not immediate; items may persist for up to 48 hours after TTL expiration. More importantly, the recipe provides no guidance on data retention policy for these derived PHI records. If the feature store is rebuilt and a patient's data is corrected or deleted (e.g., patient exercises HIPAA right to amendment or accounting of disclosures), stale cache entries may contain outdated or invalid similarity associations.

**Suggested fix:** Add a note that the cache should be treated as a PHI data store subject to the organization's data retention and amendment policies. Recommend a mechanism to invalidate cache entries when source patient data changes (not just on TTL expiry). Mention that DynamoDB TTL is eventually consistent and should not be relied upon as a hard deletion guarantee for compliance purposes.

#### Issue S3: IAM Permissions Are Not Least-Privilege (MEDIUM)

**Location:** Prerequisites table, IAM Permissions row

**The problem:** The permissions listed are action-level (`s3:GetObject`, `s3:PutObject`, `dynamodb:GetItem`, etc.) but not resource-scoped. The recipe doesn't specify that these should be scoped to specific bucket prefixes, table ARNs, or endpoint ARNs. A builder following this literally might grant `s3:GetObject` on `*` rather than on the specific feature store bucket and prefix.

**Suggested fix:** Add resource-scoping guidance: `s3:GetObject` on `arn:aws:s3:::feature-store-bucket/patient-features/*`, `dynamodb:PutItem` on the specific cache table ARN, `sagemaker:InvokeEndpoint` on the specific endpoint ARN. One sentence noting "scope all permissions to specific resource ARNs" would suffice.

#### Issue S4: No Mention of Audit Logging for Similarity Queries (MEDIUM)

**Location:** Prerequisites table (CloudTrail row) and general architecture

**The problem:** CloudTrail is mentioned for "all SageMaker inference calls and S3 access." But the recipe doesn't address application-level audit logging: who queried which patient's similarity, when, and what results were returned. HIPAA's accounting of disclosures requirement means you need to track which care managers accessed which patients' derived data. CloudTrail captures API calls but not the business-level "Care Manager X viewed similarity results for Patient Y" event.

**Suggested fix:** Add a requirement for application-level audit logging in the Lambda orchestrator. Each similarity query should log: requesting user, query patient ID, timestamp, number of results returned, and confidence level. This log should be immutable (CloudWatch Logs with a retention policy, or a dedicated audit table). Reference this as a HIPAA accounting-of-disclosures control.

---

### Architecture Expert Review

#### What's Done Well

The four-component architecture (Feature Store, Similarity Engine, Outcome Aggregation, Care Plan Recommendations) is clean and well-motivated. The progression from brute-force kNN to ANN to learned embeddings is well-paced and gives readers a clear maturity path. The confidence indicator based on cohort size is a genuinely useful pattern that many similarity implementations miss. The caching strategy with TTL tied to feature store refresh is sound. The "Where it struggles" section is honest and specific.

#### Issue A1: No Data Governance or Consent Framework Discussed (HIGH)

**Location:** General architecture and "Why This Isn't Production-Ready"

**The problem:** Patient similarity uses one patient's data to inform another patient's care. This raises a governance question that the recipe never addresses: do patients consent to their historical data being used as comparison cohorts for other patients' care planning? This is not a hypothetical concern. Some health systems require explicit consent for secondary use of clinical data beyond direct care. IRB review may be required depending on whether this is framed as clinical decision support, quality improvement, or research.

The recipe's "Bias amplification" section in "Why This Isn't Production-Ready" touches on fairness but not on the fundamental governance question of whether this use of data is permissible under the organization's data use agreements, patient consent frameworks, and applicable state laws (which vary significantly).

**Suggested fix:** Add a paragraph in "Why This Isn't Production-Ready" or as a standalone subsection addressing data governance: (1) secondary use of clinical data for similarity-based decision support typically falls under "treatment, payment, or healthcare operations" under HIPAA, which does not require individual authorization, but (2) organizational policies, state laws, and data use agreements may impose additional constraints, (3) IRB review may be required if the system is used for research purposes or if outcomes are published, (4) patients should be informed that their de-identified data contributes to care planning tools. This is not a blocker but it's a conversation that must happen before deployment.

#### Issue A2: Feature Store Versioning Strategy Is Underspecified (HIGH)

**Location:** "Feature Store" component description and Step 5 pseudocode

**The problem:** The recipe mentions "versioned Parquet files" in S3 and uses `current_feature_store_version()` in the cache key. But it never explains what a version is, how versions are created, or how the system handles the transition between versions. When the nightly ETL produces a new feature snapshot:
- Is the ANN index rebuilt synchronously before queries resume?
- What happens to in-flight queries during index rebuild?
- Are cached results from the previous version invalidated immediately or allowed to expire naturally?
- If a patient's features change significantly between versions (new diagnosis, new lab values), do their cached similarity results become misleading during the TTL window?

For a system that care managers rely on for clinical decisions, stale or inconsistent results during version transitions are a real concern.

**Suggested fix:** Add a brief discussion of version transition strategy. Options: (1) blue-green index deployment (build new index, swap endpoint, invalidate cache), (2) version-aware caching (cache key includes feature version, old cache entries expire naturally), (3) eventual consistency acceptance (document that results may lag by up to 24 hours after new data arrives). The recipe already uses option 2 in the cache key, which is good. Make this explicit and note the implications: a patient diagnosed with heart failure today won't appear in similarity results for other heart failure patients until the next ETL run plus index rebuild.

#### Issue A3: No Discussion of Minimum Cohort Size for Index Construction (MEDIUM)

**Location:** Step 2 pseudocode (`build_similarity_index`)

**The problem:** The recipe discusses minimum cohort size for outcome aggregation (the confidence indicator in Step 4) but not for index construction. If you're building a condition-specific similarity model for a rare condition with only 50 patients in your system, the ANN index will work mechanically but the results are statistically questionable. The recipe should address: what's the minimum population size for a meaningful similarity index? At what point should you fall back to broader condition groupings or decline to provide similarity results?

**Suggested fix:** Add a note in Step 2 or in the "Where it struggles" section: recommend a minimum cohort of 500-1000 patients for a condition-specific similarity index to provide meaningful diversity of neighbors. Below that threshold, consider broader condition groupings or display a warning that the comparison pool is limited.

#### Issue A4: OpenSearch Alternative Introduced But Not Integrated (LOW)

**Location:** "Why These Services" section, OpenSearch paragraph

**The problem:** OpenSearch is introduced as an alternative to SageMaker for ANN search, but the architecture diagram, prerequisites, ingredients table, and pseudocode all assume SageMaker. A reader who wants to use the OpenSearch path has no guidance on how the architecture changes. This creates a "choose your own adventure" without a map for the second path.

**Suggested fix:** Either remove the OpenSearch mention and keep the recipe focused on SageMaker, or add a brief "OpenSearch variant" callout box showing the architectural differences (index patient vectors in OpenSearch, query via OpenSearch kNN API, no SageMaker endpoint needed). The current half-mention is more confusing than helpful.

---

### Networking Expert Review

#### What's Done Well

VPC placement is recommended for production. VPC endpoints for S3, DynamoDB, and CloudWatch Logs are specified. The architecture keeps PHI within the VPC boundary (Lambda and SageMaker endpoint are VPC-resident). The SageMaker endpoint being VPC-deployed means inference traffic doesn't traverse the public internet.

#### Issue N1: VPC Endpoint for SageMaker Runtime Not Explicitly Listed (MEDIUM)

**Location:** Prerequisites table, VPC row

**The problem:** The prerequisites state "Lambda and SageMaker endpoint in VPC with VPC endpoints for S3, DynamoDB, and CloudWatch Logs." The SageMaker endpoint itself is deployed in the VPC (correct), but the Lambda function calling `sagemaker:InvokeEndpoint` needs a VPC endpoint for SageMaker Runtime (`com.amazonaws.{region}.sagemaker.runtime`) to reach the endpoint without leaving the VPC. This endpoint is not listed. Without it, the Lambda's `InvokeEndpoint` call would need a NAT gateway to reach the SageMaker Runtime API, which means PHI in the inference request transits through the NAT gateway and potentially the public internet (depending on routing).

**Suggested fix:** Add `com.amazonaws.{region}.sagemaker.runtime` to the VPC endpoint list. This ensures the inference call (which carries the patient feature vector, which is derived PHI) stays within the VPC.

#### Issue N2: No Egress Control Discussion for Feature Data (LOW)

**Location:** General architecture

**The problem:** The feature store contains derived PHI (patient feature vectors that, while not containing names or dates, could potentially be re-identified through combination of clinical markers). The recipe doesn't discuss egress controls: security groups on the Lambda and SageMaker endpoint should restrict outbound traffic to only the VPC endpoints needed. Without explicit egress rules, a compromised Lambda could exfiltrate feature data to an external endpoint.

**Suggested fix:** Add one sentence in the VPC prerequisites: "Configure security groups on Lambda and SageMaker endpoint to restrict egress to VPC endpoint ENIs only (no internet egress). Use VPC endpoint policies to restrict which S3 buckets and DynamoDB tables are accessible from within the VPC."

---

### Voice Reviewer

#### What's Done Well

The voice is strong and consistent throughout. The opening scenario (care manager with a newly diagnosed patient) is compelling and human. The "The art is in finding the right features" framing is exactly the right register. The technology section teaches without condescending. Parenthetical asides are used well ("it sounds straightforward. It is not."). The Honest Take section has genuine self-deprecating expertise ("The thing that surprised me most..."). The 70/30 vendor balance is well-maintained: the Technology section is entirely vendor-agnostic, and AWS appears only in the implementation half.

#### Issue V1: One Em Dash Present (LOW)

**Location:** Expected Results section, "Where it struggles" paragraph

**The text:** "Patients early in their disease course (limited outcome data for similar early-stage patients)."

Actually, on re-read this is parentheses, not an em dash. Let me re-scan...

After thorough re-scan: **No em dashes found.** The recipe uses parentheses, periods, colons, and semicolons consistently. Clean pass on this rule.

#### Issue V2: "The Honest Take" Could Be Slightly More Self-Deprecating (LOW)

**Location:** "The Honest Take" section

**The problem:** The section is honest and useful but reads slightly more like "expert advice" than "here's what bit me." The style guide calls for "self-deprecating expertise" as CC's signature. The section starts with "Patient similarity is one of those ideas that sounds obviously useful and is genuinely hard to get right" which is good, but could benefit from one more personal-experience hook ("The first time I built one of these, I spent three weeks on the distance metric before realizing my features were garbage").

**Suggested fix:** Minor. Add one sentence of personal-experience framing to the opening of the Honest Take. This is a polish item, not a structural issue.

#### Issue V3: "Non-Negotiable" Is Slightly Strong for the Register (LOW)

**Location:** Technology section, "Feature Engineering" subsection

**The text:** "This is where clinical expertise is non-negotiable."

**The problem:** "Non-negotiable" has a slightly corporate/LinkedIn tone. The rest of the recipe avoids this register successfully.

**Suggested fix:** Consider "This is where you absolutely need clinical expertise" or "This is where clinical expertise stops being optional." Minor tone adjustment.

---

## Stage 2: Expert Discussion

**Overlap between Security (S1) and Architecture (A1):** Both identify that the system exposes cross-patient data without adequate governance. S1 focuses on the technical PHI exposure (patient IDs in results), A1 focuses on the governance framework (consent for secondary use). These are complementary, not conflicting. Both should be addressed: the governance framework determines what's permissible, and the technical controls enforce it.

**Priority resolution:** A1 (governance) is arguably more fundamental than S1 (technical control) because the governance decision determines what technical controls are needed. If the organization decides aggregated-only results are required, S1's fix is straightforward. If individual patient drill-down is permitted with appropriate authorization, S1 needs a different technical approach. Recommend addressing A1 first, then S1 as the implementation of whatever governance decision is made.

**S4 (audit logging) supports both S1 and A1:** Application-level audit logging is the mechanism that makes both the PHI access control (S1) and the governance framework (A1) enforceable and auditable.

**No conflicts between experts.** All findings are additive.

---

## Stage 3: Synthesized Findings

| ID | Severity | Expert | Location | Finding | Recommended Fix |
|----|----------|--------|----------|---------|-----------------|
| A1 | HIGH | Architecture | General architecture / "Why This Isn't Production-Ready" | No data governance or consent framework discussed for secondary use of patient data in similarity comparisons | Add governance subsection: HIPAA TPO exception, organizational policy requirements, IRB considerations, patient notification |
| S1 | HIGH | Security | Step 3, Step 5, Expected Results | Similarity results expose real patient IDs of other patients, creating cross-patient PHI exposure | Address access control: aggregated-only results vs. opaque IDs vs. break-the-glass authorization for drill-down |
| A2 | HIGH | Architecture | Feature Store description, Step 5 | Feature store versioning strategy underspecified: no guidance on index rebuild transitions, cache invalidation, or consistency during updates | Document version transition strategy; make blue-green or eventual-consistency approach explicit |
| S2 | MEDIUM | Security | Step 5 pseudocode | DynamoDB cache TTL does not address PHI retention policy, amendment rights, or eventual-consistency of TTL deletion | Add data retention and amendment policy guidance; note TTL is not a hard deletion guarantee |
| S3 | MEDIUM | Security | Prerequisites table | IAM permissions listed at action level without resource scoping | Add resource-scoping guidance (specific bucket ARNs, table ARNs, endpoint ARNs) |
| S4 | MEDIUM | Security | Prerequisites / architecture | No application-level audit logging for similarity queries (who queried which patient, when) | Add audit logging requirement in Lambda orchestrator for HIPAA accounting of disclosures |
| N1 | MEDIUM | Networking | Prerequisites, VPC row | SageMaker Runtime VPC endpoint not listed; inference calls carrying PHI may transit NAT/internet | Add `com.amazonaws.{region}.sagemaker.runtime` to VPC endpoint list |
| A3 | MEDIUM | Architecture | Step 2 pseudocode | No minimum cohort size guidance for index construction; rare conditions may produce meaningless results | Add minimum population recommendation (500-1000) and fallback guidance |
| A4 | LOW | Architecture | "Why These Services" | OpenSearch alternative introduced but not integrated into architecture, prerequisites, or pseudocode | Either remove or add a brief variant callout showing architectural differences |
| N2 | LOW | Networking | General architecture | No egress control discussion for Lambda/SageMaker security groups | Add one sentence on restricting egress to VPC endpoint ENIs only |
| V2 | LOW | Voice | "The Honest Take" section | Section is honest but could be slightly more self-deprecating per style guide | Add one personal-experience hook sentence |
| V3 | LOW | Voice | Technology section, "Feature Engineering" | "Non-negotiable" has slightly corporate tone | Rephrase to match conversational register |

---

## Priority Actions Before Publication

1. **Address A1 (HIGH):** Add data governance discussion. This is the most important gap because it's a "should we build this" question that must be answered before "how do we build this." One paragraph in "Why This Isn't Production-Ready" covering HIPAA TPO, organizational policy, and IRB considerations.

2. **Address S1 (HIGH):** Decide on the cross-patient PHI exposure model. The simplest fix: default to aggregated-only results (no individual patient IDs returned to the UI) and note that drill-down requires additional authorization controls.

3. **Address A2 (HIGH):** Make the version transition strategy explicit. The recipe already has the right cache key design; it just needs to document what happens during the transition window and set expectations for data freshness.

4. **Address S4 and N1 (MEDIUM):** Add application-level audit logging requirement and the SageMaker Runtime VPC endpoint. Both are straightforward additions to the prerequisites section.

5. **Remaining MEDIUM and LOW items** are improvements that strengthen the recipe but don't represent gaps that would mislead a builder or create compliance risk.

---

*Review complete. Recipe 6.6 is well-written, clinically grounded, and architecturally sound. The HIGH findings are governance and data exposure concerns specific to the cross-patient nature of similarity systems, not fundamental architectural flaws. The recipe teaches the technology effectively and the voice is consistent. With the governance and PHI exposure gaps addressed, this is ready for publication.*
