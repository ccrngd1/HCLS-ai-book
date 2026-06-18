# Recipe 6.1: Geographic Patient Clustering ⭐

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.10 per 10,000 patients clustered

---

## The Problem

A regional health system with 14 clinics is trying to decide where to open clinic number 15. They have 200,000 patients in their EHR. They know where those patients live (addresses on file). They know which clinic each patient currently visits. But they don't know where the gaps are. They don't know which ZIP codes have patients driving 45 minutes past a closer competitor because there's nothing in between. They don't know which neighborhoods are growing, which are aging, and which are losing population to the suburbs.

This isn't a hypothetical. Every health system with more than a handful of locations faces this question constantly: where are our patients, where should we be, and where are we losing people to distance?

The same geographic clustering problem shows up in community health assessment (which neighborhoods have the worst outcomes and the fewest resources?), mobile health unit routing (where should the van go on Tuesdays?), pandemic response (which areas need testing sites?), and network adequacy reporting (can we prove to CMS that 90% of our members live within 15 miles of a provider?).

The data is sitting right there in the EHR: patient addresses, visit histories, diagnoses. The challenge isn't getting the data. It's turning 200,000 individual addresses into actionable geographic intelligence that a VP of Strategy can use to make a $40 million facility decision.

Here's how you turn 200,000 addresses into something a VP of Strategy can actually use.

---

## The Technology: Spatial Clustering from First Principles

### What Is Geographic Clustering?

At its core, geographic clustering is the process of grouping points on a map into meaningful regions based on proximity and density. You have a set of coordinates (latitude/longitude pairs derived from patient addresses), and you want to find natural groupings: areas where patients concentrate, gaps where they don't, and boundaries that make operational sense.

This sounds trivial. Plot the dots, draw circles around the dense areas, done. In practice, it's more nuanced than that, because "meaningful" depends entirely on what you're trying to do. A cluster that makes sense for facility planning (where should we build?) looks different from one that makes sense for community health (which neighborhoods share risk factors?), which looks different from one that makes sense for network adequacy (can we prove geographic coverage?).

### The Classic Algorithms

**K-Means** is the algorithm most people learn first. You pick K (the number of clusters you want), and the algorithm iteratively assigns each point to its nearest cluster center, then moves the centers to the middle of their assigned points. Repeat until stable. It's fast, intuitive, and works well when your clusters are roughly spherical and roughly the same size.

The problem with K-Means for geographic data: you have to pick K in advance. How many clusters should 200,000 patients form? 10? 50? 200? The answer depends on your use case, and K-Means gives you no guidance. It also assumes clusters are convex (roughly circular), which geographic populations rarely are. People cluster along highways, around town centers, in irregular suburban sprawl patterns.

**DBSCAN** (Density-Based Spatial Clustering of Applications with Noise) takes a different approach. Instead of pre-specifying the number of clusters, you specify two parameters: epsilon (how close points need to be to count as neighbors) and min_samples (how many neighbors a point needs to be considered part of a dense region). DBSCAN finds clusters of arbitrary shape, handles noise (isolated points that don't belong to any cluster), and doesn't require you to guess the number of clusters in advance.

For geographic patient data, DBSCAN is often the better starting point. Patient populations don't form neat circles. They form irregular blobs along transit corridors, around commercial centers, and in residential developments. DBSCAN respects that reality.

**HDBSCAN** (Hierarchical DBSCAN) extends DBSCAN by varying the density threshold and building a hierarchy of clusters. It handles populations with varying density (dense urban core, sparse rural fringe) better than plain DBSCAN, which uses a single density threshold everywhere. If your service area spans both downtown and farmland, HDBSCAN is worth the extra complexity.

### Geocoding: The Unglamorous Foundation

Before you can cluster anything, you need coordinates. Patient records have addresses. Addresses are text strings. Clustering algorithms need numbers (latitude, longitude). The process of converting "123 Main St, Springfield, IL 62701" into (39.7817, -89.6501) is called geocoding.

Geocoding sounds like a solved problem. It mostly is, for well-formed US addresses. But healthcare data is messy:

- PO Boxes don't have a meaningful geographic location (they represent a post office, not where the patient lives)
- Homeless patients may have a shelter address, a last-known address, or no address at all
- Rural addresses sometimes use route-and-box notation that geocoders struggle with
- Apartment numbers don't affect coordinates but do affect density calculations
- Patients move. The address in the EHR might be six months stale.

A geocoding step that silently drops 15% of your patients (the ones with PO Boxes, bad addresses, or missing data) will bias your clusters toward populations with stable housing and well-formed addresses. That's exactly the population you probably don't need to worry about. The patients you're missing are often the ones who need geographic access the most.

### Distance Metrics: Not All Miles Are Equal

When clustering geographic points, the obvious distance metric is "as the crow flies" (Haversine distance between two lat/long pairs). But patients don't fly. They drive. Or take the bus. Or walk.

A patient who lives 3 miles from a clinic but across a river with no bridge is functionally farther away than a patient who lives 8 miles away on a straight highway. Drive-time isochrones (the area reachable within X minutes of driving) are more meaningful than radius circles for healthcare access analysis.

For initial clustering, Haversine distance is fine. It's fast, requires no external API calls, and gives you directionally correct results. But when you're making facility placement decisions, you'll want to validate clusters against actual drive times. A cluster of 5,000 patients that looks compact on a map might actually span a 45-minute drive if there's a mountain or a river in the middle.

### What Makes Healthcare Geographic Clustering Different

Generic geographic clustering (where should we put a Starbucks?) differs from healthcare geographic clustering in a few important ways:

**Regulatory requirements.** CMS network adequacy standards specify maximum distance and drive-time thresholds by specialty type. Your clusters need to map to these thresholds, not arbitrary boundaries. For Medicare Advantage plans, 90% of urban members must live within specific distances of specific provider types. Your clustering needs to prove (or disprove) compliance.

**Equity considerations.** If your clusters reveal that underserved populations are systematically farther from care, that's not just a business insight. It's a health equity finding with regulatory, reputational, and moral implications. Geographic clustering in healthcare is never purely operational.

**PHI sensitivity.** Patient addresses are PHI. The coordinates derived from them are PHI. The clusters themselves, if small enough to be re-identified, are PHI. You can't just dump 200,000 lat/long pairs into a public mapping tool. The entire pipeline needs to operate within your HIPAA boundary.

**Temporal dynamics.** Patient populations shift. New housing developments, highway construction, employer relocations, seasonal residents. A clustering analysis from January may not reflect reality in July. Build for refresh, not one-shot analysis.

### The General Architecture Pattern

```text
[Address Data] → [Geocode] → [Clean/Filter] → [Cluster] → [Enrich] → [Visualize/Analyze]
```

**Address Data.** Extract patient addresses from your source system (EHR, claims, enrollment). Include visit history and demographics if you want to enrich clusters later.

**Geocode.** Convert addresses to latitude/longitude coordinates. Handle failures gracefully (PO Boxes, invalid addresses, missing data). Log what you couldn't geocode so you know your coverage gaps.

**Clean/Filter.** Remove duplicates (same patient, same address counted once). Handle edge cases (coordinates at 0,0 mean geocoding failed, not that your patient lives in the Gulf of Guinea). Apply any geographic bounding box (exclude patients outside your service area).

**Cluster.** Apply your chosen algorithm. For most healthcare use cases, start with DBSCAN or HDBSCAN. Tune parameters based on your operational question: tight clusters for facility micro-siting, loose clusters for regional planning.

**Enrich.** Attach metadata to each cluster: patient count, average age, payer mix, top diagnoses, utilization patterns. A cluster is just a set of coordinates until you attach meaning to it.

**Visualize/Analyze.** Render clusters on a map. Calculate summary statistics. Compare against existing facility locations, competitor locations, and regulatory thresholds. Generate the artifacts that decision-makers need.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter06.01-architecture). The Python example is linked from there.

## The Honest Take

Geographic clustering is one of those problems that feels like it should be a weekend project. Plot the dots, find the dense areas, done. And honestly, for a first pass, it kind of is. You can get a useful "here's where our patients are" map in a day.

The complexity creeps in when people start making decisions based on it. The moment someone says "let's build a $40 million clinic based on cluster 7," you need to answer questions like: How stable is this cluster over time? What happens if the new housing development on the east side fills up? Are we counting the nursing home as 400 patients or one location? Did we miss the 15% of patients with PO Boxes who might actually live in the gap between clusters?

The parameter tuning is where I've seen teams get stuck. DBSCAN's epsilon and min_samples feel arbitrary, and they are. There's no objectively correct answer. A 2km epsilon gives you tight neighborhood-level clusters. A 10km epsilon gives you regional market areas. Both are "right" depending on the question. The mistake is picking parameters once and treating the output as ground truth. Run it multiple times with different parameters. Show stakeholders the sensitivity. "At tight clustering, we see 47 micro-clusters. At loose clustering, we see 8 regional markets. Which view is useful for your decision?"

The geocoding quality issue surprised me more than I expected. In one project, 22% of addresses failed to geocode at high confidence. Most were rural routes, PO Boxes, and addresses with typos. That 22% wasn't randomly distributed. It was concentrated in exactly the underserved areas we were trying to analyze. The analysis was systematically blind to the populations that needed it most. We ended up running a separate process to estimate locations for failed geocodes using ZIP code centroids, which is imprecise but better than exclusion.

One more thing: don't forget that clusters change. Run this quarterly, not once. Patient populations shift, new developments open, employers relocate. A cluster analysis from January that drives a facility decision in December is working with stale data. For ongoing operations, maintain a change-data-capture feed from your EHR. Track address changes by comparing the current extract against the previous run's input. Only geocode new or changed addresses. This reduces geocoding costs from ~$100/run to ~$5-10/run for typical monthly patient churn (2-5% address changes).

<!-- TODO (TechWriter): Expert review ARCH-2 (MEDIUM). Consider expanding the incremental processing paragraph above into a more detailed architectural pattern showing how to identify new/changed addresses and merge incremental geocoding results with existing data. -->

---

## Related Recipes

- **Recipe 5.3 (Address Standardization and Household Linkage):** Handles the address normalization and deduplication that feeds clean data into this recipe's geocoding step
- **Recipe 6.2 (Utilization Pattern Segmentation):** Segments patients by behavior; combine with geographic clusters for "where do high-utilizers live?" analysis
- **Recipe 7.1 (Readmission Risk Scoring):** Risk scores can enrich geographic clusters to identify high-risk neighborhoods
- **Recipe 14.3 (Facility Location Optimization):** Uses cluster output as input for mathematical optimization of facility placement

<!-- TODO (TechWriter): Main recipe is missing Tags and Navigation footer sections per RECIPE-GUIDE. Tags are currently only on the architecture companion. Add them here. -->

---
