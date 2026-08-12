<!-- Removed from chapter13.08-medical-concept-normalization-mapping.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Building a concept normalization system is one of those projects where the first 80% feels deceptively easy. You load UMLS, wire up a query API, and for common concepts (diabetes, hypertension, the top 100 diagnoses), everything works beautifully. Then you hit the long tail.

The long tail is where you discover that "unspecified" codes in ICD-10 map to dozens of SNOMED concepts and your consumers don't know which one to pick. Where a LOINC code for "hemoglobin" maps differently depending on whether it's a point-of-care test or a lab panel component. Where a drug concept in RxNorm has been split into two concepts in the latest release and your historical mappings are now ambiguous.

The curation interface is the thing that will consume the most ongoing effort. UMLS gets you the bulk of the mappings, but every organization has edge cases specific to their data. A local lab uses non-standard LOINC codes. A legacy system has proprietary internal codes that need mapping. A quality measure references a value set that doesn't align cleanly with your SNOMED hierarchy. These all require human terminologists to create and maintain custom mappings.

Version management is the thing that surprised me most. I initially built this as a "current state" system: load the latest version of everything, done. Then someone asked "why did this patient's risk score change between last month and this month when nothing clinical changed?" The answer was that an ICD-10 annual update reclassified a code, which changed its SNOMED mapping, which changed its HCC category. Without temporal queries, you can't explain that. Retroactive terminology changes are a real operational concern.

The cache invalidation problem is also non-trivial. When you load a new terminology version, which cache entries are stale? The naive answer is "flush everything," but that causes a thundering herd on your graph database. The smart answer is to compute the delta (which concepts changed) and selectively invalidate, but that requires tracking which cache entries depend on which graph nodes.

One more thing: licensing. UMLS requires a free license from NLM. SNOMED CT is free in the US (NLM holds the license). But CPT requires a paid AMA license, and some specialty terminologies have their own licensing terms. Budget for this and track your compliance.

---

