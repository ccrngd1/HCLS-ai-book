# Expert Review: Recipe 6.1 -- Geographic Patient Clustering

**Reviewed by:** Technical Expert Panel (Security / Architecture / Networking / Voice)
**Recipe:** Chapter 6.1 -- Geographic Patient Clustering
**Date:** 2026-05-30
**Severity Legend:** 🔴 Critical · 🟠 High · 🟡 Medium · 🔵 Low · ✅ Praise

---

## Executive Summary

Recipe 6.1 is a well-structured, accessible treatment of geographic patient clustering for healthcare facility planning. The Problem section is compelling and grounded in real operational decisions. The Technology section teaches spatial clustering fundamentals (K-Means, DBSCAN, HDBSCAN) effectively without vendor lock-in. The architecture is appropriate for the stated scale (200K patients), and the Honest Take reflects genuine production experience with geocoding quality and parameter sensitivity.

**Verdict: PASS**

The recipe has no CRITICAL findings and 2 HIGH findings. Both are addressable with targeted additions. The architecture is sound for the stated use case, the HIPAA considerations are mostly well-handled, and the domain treatment is accurate. The geocoding quality discussion and equity considerations are particular strengths.

---

## Stage 1: Independent Expert Reviews

---

## Security Review

### 🟠 SEC-1: Amazon Location Service HIPAA Eligibility Not Verified; BAA Coverage Assertion May Be Incorrect

**Finding:** The recipe states in the "Why These Services" section: "For HIPAA workloads, this matters: you're not sending patient addresses to a third-party API outside your BAA coverage." This implies Amazon Location Service is covered under the AWS BAA. However, Amazon Location Service's HIPAA eligibility status has varied over time. The recipe should explicitly verify this claim rather than asserting it. If Location Service is NOT a HIPAA-eligible service, then sending patient addresses (PHI) to it without a BAA is a HIPAA violation. This is a compliance assertion that must be verified.

**Location:** "Why These Services" section, Amazon Location Service paragraph; also Prerequisites table, "BAA" row.

**Fix:** Add an explicit note: "Verify that Amazon Location Service appears on the current AWS HIPAA Eligible Services list (https://aws.amazon.com/compliance/hipaa-eligible-services-reference/) before sending patient addresses. If it is not listed, geocode using a self-hosted solution (e.g., Pelias or Nominatim on EC2 within your VPC) or use a geocoding provider with whom you have a BAA. The HIPAA-eligible services list is updated periodically; check at implementation time." This transforms a potentially incorrect assertion into actionable guidance.

---

### 🟠 SEC-2: Patient Coordinates Stored in DynamoDB Without Access Control Discussion

**Finding:** Step 6 writes per-patient cluster assignments to DynamoDB including `patient_id`, `latitude`, and `longitude`. Patient coordinates derived from home addresses are PHI. The recipe mentions DynamoDB encryption at rest (default) in the Prerequisites table, but does not discuss: (1) who can query this table, (2) whether fine-grained access control is needed, (3) whether the patient_id is a direct identifier (MRN) or an opaque key. A DynamoDB table containing 200,000 patient home coordinates with direct identifiers is a high-value target. Any application with `dynamodb:Query` permission on this table can enumerate all patient home locations.

**Location:** Step 6 pseudocode, DynamoDB writes; Prerequisites table, "IAM Permissions" row.

**Fix:** Add: "Restrict DynamoDB access to the cluster-results table using IAM policies scoped to specific roles (the pipeline write role and the dashboard read role). Use an opaque patient identifier (not MRN) as the partition key; maintain the mapping in a separate, more tightly controlled identity service. Consider DynamoDB fine-grained access control if multiple downstream consumers need different access levels. The patient-clusters table contains home location data for your entire active population; treat it as a high-sensitivity asset."

---

### 🟡 SEC-3: S3 Parquet Files Contain Full Patient Location Data Without Lifecycle/Retention Discussion

**Finding:** Step 6 writes all patient assignments as Parquet to S3: `cluster-results/{date}/patient-assignments.parquet`. Over time, this accumulates historical snapshots of every patient's home coordinates. The recipe recommends quarterly refresh but does not discuss retention policies. After a year, you have four complete snapshots of 200K patient home locations. There's no discussion of S3 lifecycle policies, object expiration, or whether historical snapshots should be retained or aged out.

**Location:** Step 6 pseudocode, S3 Parquet write; also "The Honest Take" (mentions running quarterly).

**Fix:** Add a note in Step 6 or Prerequisites: "Apply S3 lifecycle policies to the cluster-results prefix. Retain the current and previous snapshot for comparison; expire older snapshots after your retention policy period (typically 6-12 months for operational analytics). Each snapshot contains PHI (patient coordinates); minimizing retained copies reduces your exposure surface."

---

### 🟡 SEC-4: IAM Permissions Listed Are Incomplete for the Described Architecture

**Finding:** The Prerequisites table lists `geo:SearchPlaceIndexForText`, `geo:BatchSearchPlaceIndexForText`, `s3:GetObject`, `s3:PutObject`, `dynamodb:PutItem`, `dynamodb:Query`. Missing: `s3:ListBucket` (needed for pipeline orchestration), `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` (Lambda execution), `kms:Decrypt`, `kms:GenerateDataKey` (for SSE-KMS encrypted S3 objects), and SageMaker permissions if using the large-dataset path. More importantly, these are listed as a flat set without per-component role decomposition.

**Location:** Prerequisites table, "IAM Permissions" row.

**Fix:** Decompose into roles: (1) Geocoding Lambda role: `geo:BatchSearchPlaceIndexForText`, `s3:GetObject` (raw-addresses), `s3:PutObject` (geocoded), CloudWatch Logs, KMS; (2) Clustering Lambda/SageMaker role: `s3:GetObject` (geocoded), `s3:PutObject` (cluster-results), `dynamodb:PutItem`, CloudWatch Logs, KMS; (3) Dashboard role: `dynamodb:Query`, `s3:GetObject` (cluster-results). This demonstrates least-privilege.

---

### ✅ SEC-PRAISE: Strong PHI Awareness Throughout

The recipe correctly identifies that patient addresses are PHI, that geocoded coordinates are PHI, and that small clusters could enable re-identification. The Prerequisites table correctly requires BAA, SSE-KMS, TLS in transit, and CloudTrail. The note about never using real patient addresses in dev (with Census TIGER/Line as synthetic alternative) is excellent. The "PHI sensitivity" callout in the Technology section shows genuine HIPAA awareness.

---

## Architecture Review

### 🟡 ARCH-1: Lambda Timeout Risk for 200K Patient Geocoding Batch

**Finding:** The recipe states Lambda handles orchestration and that geocoding 200,000 addresses happens in batches of 50. At 50 addresses per batch, that's 4,000 API calls. Even at 1,000 addresses/second throughput (stated in benchmarks), the geocoding step alone takes ~200 seconds. With Lambda's 15-minute maximum timeout, this is feasible but tight when you add error handling, retries, and S3 writes. The recipe does not discuss what happens if the geocoding step exceeds Lambda timeout, or whether Step Functions should orchestrate the batches.

**Location:** Step 2 pseudocode; "Why These Services" (Lambda section); Performance benchmarks.

**Fix:** Add: "For 200K+ addresses, consider orchestrating geocoding batches with Step Functions (Map state) rather than a single Lambda invocation. Each Map iteration processes a subset (e.g., 10,000 addresses per Lambda), providing automatic parallelism, per-batch error handling, and no timeout risk. A single Lambda can handle ~50K addresses within the 15-minute limit; beyond that, use Step Functions or SageMaker Processing."

---

### 🟡 ARCH-2: No Discussion of Incremental Processing for Ongoing Operations

**Finding:** The recipe mentions "incremental cost for new patients only" in the benchmarks table and "run this quarterly" in the Honest Take, but the architecture and pseudocode describe a full-batch process every time. There's no discussion of how to identify new/changed addresses since the last run, how to merge incremental geocoding results with existing data, or how to handle patients who moved (address changed, old cluster assignment is stale). For a production system running quarterly, incremental processing is essential to avoid re-geocoding 200K addresses every time.

**Location:** Architecture diagram (shows full pipeline); Performance benchmarks ("Incremental cost" row); The Honest Take ("run this quarterly").

**Fix:** Add a paragraph in the architecture or a variation: "For ongoing operations, maintain a change-data-capture feed from your EHR. Track address changes by comparing the current extract against the previous run's input. Only geocode new or changed addresses. Merge incremental results into the existing coordinate dataset before re-running clustering. This reduces geocoding costs from ~$100/run to ~$5-10/run for typical monthly patient churn (2-5% address changes)."

---

### 🟡 ARCH-3: DynamoDB Table Design Not Specified; Access Patterns Unclear

**Finding:** Step 6 writes to two DynamoDB tables ("patient-clusters" and "cluster-metadata") but does not specify partition keys, sort keys, or GSIs. The stated access patterns are "which cluster does patient X belong to?" (point lookup by patient_id) and "what are the characteristics of cluster 7?" (point lookup by cluster_id). These are straightforward, but the recipe should specify the key schema to prevent readers from designing an inefficient table (e.g., using cluster_id as partition key for the patient table, which would create hot partitions).

**Location:** Step 6 pseudocode, DynamoDB writes.

**Fix:** Add brief table design: "patient-clusters table: partition key = patient_id (string). cluster-metadata table: partition key = cluster_id (number). No sort keys needed for these access patterns. If you need 'list all patients in cluster X,' add a GSI on cluster_id to the patient-clusters table, but be aware this enables bulk enumeration of patient locations by cluster."

---

### 🟡 ARCH-4: SageMaker Mentioned but Not Integrated into Architecture Diagram

**Finding:** The recipe mentions SageMaker Processing Jobs for datasets over 500K patients, and the architecture diagram includes "Lambda or SageMaker" as the clustering engine. But there's no guidance on when to switch, how SageMaker Processing differs from the Lambda path in terms of setup, or what the SageMaker architecture looks like. It feels like an afterthought rather than a real alternative path.

**Location:** "Why These Services" (SageMaker paragraph); Architecture diagram (node F).

**Fix:** Either remove SageMaker and scope the recipe to Lambda-only (appropriate for the "Simple" complexity rating), or add a brief "scaling up" note: "For datasets exceeding 500K points or requiring GPU-accelerated HDBSCAN, replace the clustering Lambda with a SageMaker Processing Job. The job reads from the same S3 geocoded/ prefix, runs the same algorithm, and writes to the same cluster-results/ prefix. The only difference is compute: SageMaker provides instances with more memory and optional GPU. Use the `sklearn` container or bring your own."

---

### ✅ ARCH-PRAISE: Appropriate Technology Selection for Stated Scale

The choice of DBSCAN over K-Means is well-justified for geographic data. The explanation of why K-Means fails (requires pre-specifying K, assumes convex clusters) and why DBSCAN succeeds (arbitrary shapes, noise handling, no K required) is technically correct and accessible. The progression from DBSCAN to HDBSCAN for varying-density populations is the right recommendation. The overall architecture (geocode -> clean -> cluster -> enrich -> store) is a sound, well-established pattern for batch geospatial analytics.

---

## Networking Review

### 🟡 NET-1: VPC Endpoint for Amazon Location Service Stated as Unavailable Without Mitigation

**Finding:** The Prerequisites table states: "Location Service calls go over the public endpoint (no VPC endpoint available as of early 2026; use a NAT Gateway)." This means patient addresses (PHI) traverse a NAT Gateway to the public internet (TLS-encrypted, but still leaving the VPC). The recipe correctly identifies this limitation but does not discuss the security implications or mitigations beyond "use a NAT Gateway." For a HIPAA workload, sending PHI over the public internet (even encrypted) may require additional risk documentation.

**Location:** Prerequisites table, "VPC" row.

**Fix:** Expand: "Since Location Service lacks a VPC endpoint, geocoding requests traverse the NAT Gateway to the public AWS endpoint. Data is TLS-encrypted in transit. Document this data flow in your HIPAA risk assessment. If your compliance posture requires all PHI to remain within private network paths, consider self-hosted geocoding (Pelias on EC2 within your VPC) as an alternative. Monitor AWS announcements for Location Service VPC endpoint availability."

---

### 🟡 NET-2: No Discussion of S3 Gateway Endpoint vs. Interface Endpoint

**Finding:** The Prerequisites mention "VPC endpoints for S3, DynamoDB, and CloudWatch Logs" but does not specify types. S3 supports both Gateway endpoints (free, route-table based, S3 and DynamoDB only) and Interface endpoints (cost per hour + per GB, PrivateLink-based). For a batch pipeline that reads/writes large Parquet files, the choice matters for cost. Gateway endpoints are free and appropriate here. The recipe should specify this to prevent readers from accidentally provisioning expensive Interface endpoints.

**Location:** Prerequisites table, "VPC" row.

**Fix:** Clarify: "Use S3 and DynamoDB Gateway endpoints (free, no per-GB charge). Use Interface endpoints for CloudWatch Logs. Gateway endpoints are sufficient for batch pipeline access patterns and avoid the hourly + data processing charges of Interface endpoints."

---

### ✅ NET-PRAISE: Correct VPC Recommendation for Production

The recipe correctly recommends Lambda in VPC for production with appropriate VPC endpoints. The acknowledgment that Location Service requires NAT Gateway is honest and accurate. The overall network posture (private compute, VPC endpoints where available, NAT for services without endpoints) is the right pattern for HIPAA workloads.

---

## Voice Review

### 🟡 VOICE-1: One Em Dash Detected

**Finding:** Scanning the recipe for em dashes (the style guide mandates zero). Found none using the standard em dash character (—). However, checking for the double-hyphen pattern that sometimes substitutes: none found. Checking for en dashes (–): none found. The recipe is clean on this front.

**Correction:** False alarm. Withdrawing this finding. No em dashes present.

---

### 🔵 VOICE-1: "Let's talk about" Transition Becoming Formulaic

**Finding:** The Problem section ends with "Let's talk about how geographic clustering actually works." This transition appears in multiple recipes across the cookbook and is becoming a recognizable pattern. It works fine in isolation but may feel repetitive to a reader going through chapters sequentially.

**Location:** The Problem, final sentence.

**Fix:** Optional. Could vary with something like "Here's how you turn 200,000 addresses into something a VP of Strategy can actually use." Very minor.

---

### 🔵 VOICE-2: Vendor Balance Is Excellent

**Finding:** The Technology section is entirely vendor-agnostic. No AWS service names appear until "The AWS Implementation" section. The split is approximately 55% vendor-agnostic (Problem + Technology + General Architecture Pattern + Honest Take + Variations) and 45% AWS-specific (the entire implementation section). This is slightly more AWS-heavy than the 70/30 target, but the Technology section is substantial and educational, and the AWS section is appropriately detailed for a "how to build it" guide.

**Location:** Overall recipe structure.

**Fix:** The balance is acceptable given the recipe's "Simple" complexity rating and the depth of the Technology section. No change required, but if tightening is desired, the "Why These Services" section could be condensed slightly.

---

### ✅ VOICE-PRAISE: Strong Engineer Voice Throughout

The Problem section's opening scenario (14 clinics, deciding where to build #15) is immediately relatable and specific. The "$40 million facility decision" stakes are concrete. The Technology section teaches without condescending: the K-Means vs. DBSCAN comparison is accessible to non-technical readers while remaining technically precise. The Honest Take is authentic: "Geographic clustering is one of those problems that feels like it should be a weekend project" and the 22% geocoding failure anecdote are exactly the kind of production insights that make this cookbook valuable. The parenthetical asides ("ok, this is a gross oversimplification" energy) are present without being overused. No documentation-voice detected. No marketing language.

---

## Stage 2: Expert Discussion

**Conflicts identified:** None. The security, architecture, and networking findings are complementary.

**Priority resolution:**
- SEC-1 (Location Service HIPAA eligibility) is HIGH because an incorrect BAA assertion could lead readers to send PHI to a non-covered service. This is a compliance risk that could result in a HIPAA violation.
- SEC-2 (DynamoDB access control for patient coordinates) is HIGH because the table contains home locations for the entire active patient population with no access control guidance. This is a high-value data asset that needs explicit protection discussion.
- The MEDIUM findings are all "add a paragraph or a sentence" improvements that strengthen the recipe without requiring structural changes.
- Voice review found no em dashes and no significant issues. The recipe's voice is strong.

**Cross-cutting observation:** The recipe's equity discussion in the Technology section ("If your clusters reveal that underserved populations are systematically farther from care, that's not just a business insight") and the geocoding bias discussion in the Honest Take (22% failure rate concentrated in underserved areas) demonstrate genuine healthcare domain expertise. These are not findings but strengths worth preserving through editing.

---

## Stage 3: Synthesized Findings

| # | Severity | Expert | Location | Finding | Fix |
|---|----------|--------|----------|---------|-----|
| SEC-1 | 🟠 HIGH | Security | Why These Services (Location Service); Prerequisites BAA row | Location Service HIPAA eligibility asserted without verification guidance | Add explicit verification step; provide self-hosted alternative if not eligible |
| SEC-2 | 🟠 HIGH | Security | Step 6 (DynamoDB writes); Prerequisites IAM row | 200K patient home coordinates in DynamoDB without access control discussion | Add role scoping, opaque identifiers, and sensitivity classification |
| SEC-3 | 🟡 MEDIUM | Security | Step 6 (S3 Parquet write) | No retention/lifecycle policy for historical PHI snapshots | Add S3 lifecycle policy recommendation |
| SEC-4 | 🟡 MEDIUM | Security | Prerequisites, IAM Permissions | Flat permission list missing KMS, Logs; no role decomposition | Decompose into per-component roles |
| ARCH-1 | 🟡 MEDIUM | Architecture | Step 2; Why These Services (Lambda) | Lambda timeout risk for 200K address geocoding in single invocation | Recommend Step Functions Map state for large batches |
| ARCH-2 | 🟡 MEDIUM | Architecture | Architecture diagram; Honest Take | No incremental processing design for ongoing quarterly runs | Add change-data-capture pattern for address changes |
| ARCH-3 | 🟡 MEDIUM | Architecture | Step 6 (DynamoDB writes) | DynamoDB table key schema not specified | Add partition key / GSI design guidance |
| ARCH-4 | 🟡 MEDIUM | Architecture | Why These Services (SageMaker); Architecture diagram | SageMaker mentioned but not meaningfully integrated | Either remove or add concrete scaling guidance |
| NET-1 | 🟡 MEDIUM | Networking | Prerequisites, VPC row | PHI traversing NAT Gateway to public endpoint without risk discussion | Add HIPAA risk assessment note and self-hosted alternative |
| NET-2 | 🟡 MEDIUM | Networking | Prerequisites, VPC row | S3 endpoint type not specified (Gateway vs Interface cost difference) | Specify Gateway endpoints for S3/DynamoDB |
| VOICE-1 | 🔵 LOW | Voice | The Problem, final sentence | "Let's talk about" transition formulaic across recipes | Optional variation |

---

## Final Verdict: **PASS**

The recipe is technically sound, architecturally appropriate for its stated "Simple" complexity, and demonstrates strong healthcare domain expertise. The 2 HIGH findings are both addressable with brief additions (HIPAA eligibility verification guidance for Location Service, and access control discussion for the patient coordinates table) and do not represent fundamental architectural flaws. The 8 MEDIUM findings are all "add a paragraph" improvements. The voice is excellent with zero em dashes and strong adherence to the cookbook's engineer-explaining-something-cool style. The recipe is ready for the TechEditor stage after addressing the HIGH findings.

---

## Additional Notes

**Strengths worth highlighting:**
- The 14-clinics-deciding-where-to-build-#15 opening is concrete, relatable, and immediately establishes stakes
- The K-Means vs. DBSCAN vs. HDBSCAN comparison is one of the clearest explanations of algorithm selection I've seen in a cookbook format
- The geocoding quality discussion (PO Boxes, homeless patients, rural routes, stale addresses) reflects real-world data quality challenges
- The equity callout ("the patients you're missing are often the ones who need geographic access the most") is important and well-placed
- The Honest Take's 22% geocoding failure anecdote is specific, credible, and actionable
- The parameter sensitivity discussion ("run it multiple times with different parameters, show stakeholders the sensitivity") is excellent practical advice
- The cost estimate ($100-150 per full run) is realistic and well-decomposed
- The "Where it struggles" section (rural areas, PO Boxes, nursing homes, seasonal populations) is honest and comprehensive
- The CMS network adequacy regulatory context is correctly framed and relevant

**Domain accuracy validation:**
- DBSCAN with Haversine metric for geographic clustering: Correct and standard approach
- Epsilon conversion to radians (epsilon_km / 6371.0): Mathematically correct
- Geocoding confidence threshold of 0.85: Reasonable for healthcare applications (balances coverage vs. accuracy)
- Batch geocoding at 50 addresses per call: Consistent with Amazon Location Service batch limits
- 200K patients clustering in 15-45 seconds: Realistic for DBSCAN with scikit-learn on modern hardware
- CMS network adequacy distance thresholds by specialty: Correctly referenced
- Census TIGER/Line files for synthetic data: Appropriate and publicly available
- Drive-time isochrones as superior to radius circles: Correct for healthcare access analysis
- PO Box geocoding to post office location (not patient home): Accurate limitation

**Unresolved reference:**
- "Recipe 14.1 (TODO: confirm recipe number for facility location optimization)" in Related Recipes needs resolution before publication. This is a minor editorial issue, not a review finding.
