# Category 5: Entity Resolution / Record Linkage

**Healthcare Use Cases — Simple → Complex**

---

## 5.1 Internal Duplicate Patient Detection (Simple)

**What:** Identify potential duplicate patient records within a single healthcare system's database.

**Why simple:** Single data source. Same field formats. Can tune aggressively since merge is manual review. Well-understood problem with established tools.

---

## 5.2 Provider NPI Matching (Simple)

**What:** Match provider records to National Provider Identifier (NPI) registry entries for credentialing and directory accuracy.

**Why simple:** NPI is a reliable anchor. Registry is authoritative and well-structured. Limited field set. Errors are administrative, not clinical.

---

## 5.3 Address Standardization and Household Linkage (Simple-Medium)

**What:** Standardize patient addresses and identify household relationships for coordinated outreach and social determinant analysis.

**Why this complexity:** Address quality varies wildly. Household inference requires assumptions. USPS standardization helps but doesn't solve everything. Privacy considerations in household linking.

---

## 5.4 Insurance Eligibility Matching (Medium)

**What:** Match patient records to payer eligibility files for coverage verification, even when demographic details don't perfectly align.

**Why medium:** No shared identifier across systems. Payer data quality varies. Name/DOB variations common. High volume, real-time needs for eligibility checks.

---

## 5.5 Cross-Facility Patient Matching (HIE) (Medium)

**What:** Match patient records across unaffiliated healthcare facilities for health information exchange and care coordination.

**Why medium:** No shared MPI. Different systems capture demographics differently. Must balance match rate with false positive risk. Consent and governance layers add complexity.

---

## 5.6 Claims-to-Clinical Data Linkage (Medium-Complex)

**What:** Link administrative claims data to clinical EHR data for the same patient/encounter to enable outcomes research and quality measurement.

**Why this complexity:** Different identifiers (member ID vs. MRN). Timing misalignment (claim date vs. service date). Many-to-many relationships (multiple claims per encounter). Data quality issues on both sides.

---

## 5.7 Longitudinal Patient Matching Across Name Changes (Complex)

**What:** Maintain patient identity linkage across name changes (marriage, divorce, legal name change, gender transition) over multi-year timeframes.

**Why complex:** Historical records may have old name only. Supporting documents may be unavailable. Must preserve both identities for record continuity. Sensitivity around identity changes.

---

## 5.8 Privacy-Preserving Record Linkage (Complex)

**What:** Match records across organizations without sharing raw PHI, using techniques like encrypted matching or secure multi-party computation.

**Why complex:** Cryptographic/statistical techniques add overhead. Match quality often lower than direct matching. Regulatory and trust frameworks required. Still emerging technology.

---

## 5.9 National-Scale Patient Matching (TEFCA) (Complex)

**What:** Achieve accurate patient matching across the national health information network with thousands of participants and billions of records.

**Why complex:** Extreme scale. No central authority. Heterogeneous data quality. Must handle edge cases at population scale. Governance across competing organizations. TEFCA framework still maturing.

---

## 5.10 Deceased Patient Resolution and Record Reconciliation (Complex)

**What:** Match death records to patient databases, resolve any remaining duplicate chains, and reconcile longitudinal records post-mortem.

**Why complex:** Death data sources vary (SSA, state vital records, facility records). Timing lags. May surface previously unknown duplicates. Legal/compliance implications. Family notification sensitivities.

---

## Complexity Factors Summary

| Factor | Impact on Complexity |
|--------|---------------------|
| Number of data sources | More sources = more variation |
| Shared identifiers | Lack of common ID is the core problem |
| Data quality | Garbage in, garbage out |
| Scale | National scale has unique challenges |
| Privacy constraints | Limits available matching techniques |
| Governance | Multi-party trust frameworks are hard |

---

*Category 5 complete. Next: Category 6 (Cohort Analysis / Clustering / Similarity)*
