# Recipe 5.6: Claims-to-Clinical Data Linkage ⭐⭐⭐⭐

**Complexity:** Medium-Complex · **Phase:** Production · **Estimated Cost:** ~$0.0001-0.001 per linked encounter at population scale, dominated by infrastructure and storage rather than per-record fees (depends on linkage strategy, retention windows, and the proportion of encounters that require human review)

---

## The Problem

You are an analyst at a regional health system, and the executive team has asked a question that sounds simple. *For the patients we treated for congestive heart failure last year, what was the readmission rate, and how does it compare to the diabetic patients we treated for the same condition?* You have the EHR. You have the claims feed from the system's accountable care organization. You have, between the two of them, every piece of data you could possibly need to answer the question. The trouble is, the EHR and the claims feed do not, in any direct sense, agree on which encounters are which.

The EHR knows that on a Tuesday in March, an attending physician admitted a 67-year-old patient with shortness of breath and a BNP of 1840, treated her over a four-day stay, and discharged her on the Friday with a diagnosis of acute decompensated heart failure. There is an admission timestamp, a discharge timestamp, a diagnosis-related group, a list of orders, a list of medications administered, the discharge summary the resident wrote at 3 AM the night before discharge, and the lab and imaging results from the stay. Every clinical event is documented somewhere in the chart.

The claims feed knows that, for the same patient, three separate facility claims were submitted. One for the admission day with the room-and-board charge. One spanning the middle of the stay with the ancillary charges (lab, imaging, pharmacy). One for the discharge day with the second room-and-board charge plus a few late-posted line items that did not make it into the prior submission. Each of those claims has its own claim identifier, its own service-from and service-through dates, its own primary and secondary diagnosis codes, and its own list of CPT and HCPCS procedure codes. Then there are seven professional claims (the attending, the cardiology consult, the anesthesiologist for the procedure on day three, the radiologist for the chest CT, the pathologist for the cytology, the hospitalist who covered the weekend, and the inpatient pharmacist who would not normally bill but did because of the medication-reconciliation visit). Several of those professional claims overlap in their service dates with the facility claims and with each other. A few of them have diagnosis codes that do not match the facility's primary diagnosis (the cardiology consultant coded chronic systolic heart failure rather than acute decompensated; the anesthesiologist coded the procedure-specific diagnosis). One of them was originally denied for missing prior authorization, was resubmitted three weeks later with the auth on file, and now has both a denied original claim and a paid resubmission in the dataset.

To answer the executive's question, you need to look at the patients with a heart-failure admission, count the unique admissions, and check whether each patient was readmitted within thirty days. The EHR sees one admission. The claims feed sees thirteen claims (three facility plus seven professional plus the resubmitted three). They are all about the same encounter. The same hospital stay. The same patient. None of them point at each other. The patient's MRN appears on the EHR side; the patient's payer member ID appears on most of the claims (but not all, because the anesthesiology claim came through a different billing entity that did not have the member ID propagated correctly). The diagnosis on the EHR's encounter does not exactly match the primary diagnosis on any of the facility claims (the EHR uses the I-10 code as the working diagnosis at admission; the facility claim uses the I-10 code that came out of coding review three weeks later, which differs because the CDI specialist queried the physician about the level of specificity). The dates *almost* line up except that the discharge claim's service-through date is the day after the EHR's discharge timestamp, because the patient stayed an extra night for transportation reasons that did not get documented in the EHR's discharge note.

This is what claims-to-clinical data linkage is for. The question the executive asked is the simplest possible version of the question. The harder versions are everywhere:

You are running quality measurement for an accountable care organization, and one of your contracted measures is "percentage of diabetic patients with an HbA1c below 9 in the last twelve months." The numerator is "patients with HbA1c < 9 in the last twelve months," which means you need the actual lab result. The denominator is "patients with diabetes who were attributed to the ACO in the measurement period," which means you need the claims-side attribution and the diagnosis history. You have the lab results in the EHR (and in the reference lab's feed for tests done on the patients who got their labs at outside facilities). You have the claims data showing the diabetes diagnoses that drove attribution. You need to link the lab results to the patient's claims-side identity to know whether the test even counts toward the measure for that patient under that contract.

You are doing outcomes research on a new biologic for rheumatoid arthritis, and the executive sponsoring the study wants to know whether patients on the biologic had fewer hospitalizations and ER visits in the year after starting the drug than in the year before. The biologic prescriptions are in the EHR's medication-administration record (for infusions given at the institution) and in the pharmacy claims feed (for self-administered formulations the patients picked up at retail pharmacies). The hospitalizations and ER visits are in the claims feed (with all the cross-payer variability that implies). The clinical outcomes you want as covariates (CRP levels, DAS28 scores, joint counts) are in the EHR. The link between the patient on the biologic, the hospitalizations they had, the ER visits they had, and the inflammation markers they had over time is the link you need to make to even define the study cohort, never mind run the analysis.

You are running risk-adjustment for a Medicare Advantage plan, and the CMS Hierarchical Condition Categories model rewards plans for documenting chronic conditions in a way that affects the next year's capitation. The conditions have to be documented on a face-to-face encounter; the diagnosis codes have to be on a claim that flows back to CMS through the encounter data submission. The patient may have a documented chronic kidney disease in the EHR (with creatinine values to back it up), but if the CKD diagnosis is not on a claim that maps to a face-to-face encounter, it does not count for HCC. You need to link claims to encounters to make sure the conditions on the claims actually correspond to encounters where the conditions were addressed. 

You are building a clinical decision support tool that suggests preventive screenings, and the rule for "due for a colonoscopy" is "no colonoscopy in the last ten years." The colonoscopy may have been done at your institution (in the EHR's procedure history) or at a gastroenterology practice across town (visible only through the patient's claims data). If your tool only sees the EHR, it will tell the patient they are due for a screening they had four years ago at the practice across town, which is annoying for the patient and undermines the tool's credibility.

You are reconciling pharmacy claims to medication-administration records to figure out what the patient is actually taking versus what is on their active medication list. The active medication list in the EHR is what the providers think the patient is on. The pharmacy claims feed shows what the patient has actually filled, and at what frequency. The med-rec list is often wrong (medications are added but not always removed when therapy changes; patients fill prescriptions that providers wrote and then stopped recommending; patients do not fill prescriptions that providers think they are taking). The link between the pharmacy claims (with their NDC codes) and the EHR's medication record (with its RxNorm codes) is the mechanism for figuring out adherence, and it is the mechanism for catching the polypharmacy interaction the providers do not see.

You are coordinating care for a complex patient with multiple chronic conditions who is seen at six different practices across two health systems and gets her medications from a national mail-order pharmacy and her labs from two different reference labs. The longitudinal record assembly that her care manager needs to do her job depends on the ability to link claims (which see every encounter she billed for, regardless of where it happened) to the clinical data from each setting. Without the linkage, the care manager has to manually phone each practice and ask for records that the practice may or may not be willing to share efficiently.

This is the recipe. Claims-to-clinical data linkage is the entity-resolution problem of "given a claim and given a clinical encounter, do they describe the same care event for the same patient, and if so, how do they relate to each other?" The answer requires entity-resolution techniques (which you saw in 5.1, 5.2, 5.3, 5.4, and 5.5), but it adds three things on top: the entities are not just patients (they are also encounters and care events, with their own identifiers and their own lifecycle), the data quality on both sides is poor in different ways than in earlier recipes (claims have administrative biases that clinical data does not, and clinical data has documentation gaps that claims do not), and the linkage is asymmetric in time (claims arrive on a delay of weeks to months after the clinical event, get adjusted, sometimes get denied and resubmitted, and may continue to evolve for months after the encounter is closed).

It is in the medium-complex tier because the matching core is the same probabilistic-and-deterministic stack from earlier recipes, but the linkage is not just patient-to-patient. It is patient-to-patient plus encounter-to-encounter plus care-event-to-care-event, with every level having its own identifier instability, its own timing, and its own data quality issues. The recipes that come after this one (5.7, 5.8, 5.9, 5.10) all assume that the claims-to-clinical link exists in some form; this recipe builds the substrate.

Let's get into how you build it.

---

## The Technology: Linking Two Data Models That Were Designed to Disagree

### Why Claims and Clinical Data Disagree by Design

Claims data and clinical data exist for different purposes. The claims dataset exists so the provider can get paid and the payer can adjudicate. The clinical dataset exists so the care team can deliver care and the chart can support the next visit. Both touch the same encounter, but they represent it through completely different lenses, and the disagreements between them are not bugs in either system; they are features of the role each system plays.

The claims side is structured around the billable transaction. Each transaction has a billing entity (a hospital, a physician practice, a free-standing diagnostic facility), a billed service (a CPT or HCPCS procedure code, a revenue code, a DRG for inpatient stays), a date or date range, a primary diagnosis (what the encounter was for, in ICD-10 terms), zero or more secondary diagnoses, a charge amount, an adjudicated payment, and patient and payer identifiers. The transaction is what gets sent to the payer; the transaction is what shows up in the claims dataset; the transaction is the unit of analysis. A single inpatient stay produces one or more facility transactions and zero-to-many professional transactions; a single outpatient visit usually produces one facility-or-clinic transaction and one professional transaction; a single ER visit produces a particular pattern of facility-and-professional transactions that is structurally similar but timing-wise much tighter. The data model is the X12 837 institutional or professional claim form, the post-adjudication remittance advice (X12 835), and the resulting paid-claim record on the payer side that powers the claims feed. 

The clinical side is structured around the patient and the encounter. An encounter is a discrete care event with an identifier (an EHR-assigned encounter ID, sometimes called a CSN or visit ID), a patient (with the institution's MRN), an attending or rendering provider, a class (inpatient, outpatient, ER, observation, telehealth), a service location, an admission timestamp, a discharge timestamp, a working diagnosis, and a chart that holds the documentation, orders, results, medications, and notes for the encounter. The encounter is the unit of clinical analysis. Inside an encounter, the data model is FHIR resources (Patient, Encounter, Observation, Procedure, MedicationRequest, MedicationAdministration, DiagnosticReport, Condition, Composition, DocumentReference) or the institution-specific equivalent. The encounter has its own lifecycle that is mostly independent of the billing lifecycle. The chart closes when the discharge summary is signed; the billing process for the same encounter may take three weeks to four months to settle.

The two systems describe overlapping but non-identical events:

**Different units of granularity.** One inpatient stay is one encounter on the EHR side and three-to-twenty claims on the claims side. The encounter-to-claim relationship is one-to-many on the facility side, one-to-many on the professional side, and there is no bidirectional pointer that the institution controls. Some institutions construct one through the revenue cycle (the EHR encounter ID is sometimes propagated to the claims as an internal control number), but the propagation is rarely complete and is often lost on the claims feed back from the payer.

**Different time anchors.** The EHR encounter has admission and discharge timestamps in real-clock time. The claims transaction has service-from and service-through dates that are calendar dates, with no time component, and that may be set to the calendar dates of the clinical event or to the calendar dates of the billing posting (depending on the institution's revenue cycle conventions). A discharge at 3 AM on the 14th may appear on the claims as service-through 14th (clinically correct) or service-through 13th (because the patient was admitted on the 13th and the room-and-board billing convention rounds to whole days). Outpatient visits and ER visits are usually a single calendar date and align cleanly. Inpatient stays and observation stays are where the timing gets messy.

**Different diagnosis representations.** The EHR's encounter diagnosis is what the clinician documented at admission, which may evolve over the course of the stay and is finalized in the discharge summary. The claim's diagnosis is what the coder assigned for billing purposes, which is influenced by the documentation, the coding rules, the institution's CDI process, and the financial-incentive structure of the contract under which the institution is being paid. The two diagnoses for the same encounter usually overlap but are rarely identical. Even when both are I-10 codes, they may be at different levels of specificity (CHF unspecified vs acute on chronic systolic CHF), reflect different perspectives (admitting diagnosis vs principal discharge diagnosis), or include conditions that one side recorded and the other did not.

**Different identifier systems.** The EHR uses the institution's MRN. The claims use the payer-issued member ID, possibly with a subscriber-vs-dependent suffix, possibly with a plan-specific prefix, possibly with a member ID that has changed mid-year because of an open-enrollment change. The institution may attempt to maintain a cross-reference between MRN and member ID, but the cross-reference is built on the same demographic-matching infrastructure as recipe 5.1 and inherits its accuracy limits. Across organizations the cross-reference is even thinner: the claims feed for a specialist visit at a different institution has a member ID and demographics, but no MRN that the analyzing institution can use directly.

**Different completeness.** The EHR sees every clinical detail of the encounter at the institution but is largely blind to encounters that happened elsewhere. The claims feed sees every encounter that was billed (regardless of where it happened) but knows almost nothing about the clinical detail of any of them. A patient seen at the institution for primary care, at an outside cardiology practice for a specialist visit, at the local lab for a panel ordered by the cardiologist, and at a retail pharmacy for the prescription the cardiologist wrote, has clinical data at one of those four places (the institution) and claims data covering all four. The claims-to-clinical link is the mechanism that lets the institution see the full picture.

**Different temporal stability.** The EHR encounter's clinical content is stable once the chart is closed (with annotation and addendum exceptions). The claims data for the same encounter continues to evolve: the original claim is submitted, possibly denied, resubmitted, possibly partially adjusted, eventually finalized. The claims feed delivers each version. The matcher has to handle the fact that "the claim for this encounter" is not a single record over time but an evolving set of records, and the linkage has to be resilient to the evolution.

The mismatches are not pathological. They reflect the fact that claims and clinical data were designed for different jobs and were never designed to be linked. The recipe is the architecture for doing the linkage anyway, with awareness of where the disagreements live and how to handle them.

### What a Claims-to-Clinical Link Actually Resolves

The link is layered. It is not a single yes/no.

**Patient-level link.** Is this patient on the claims side the same person as this patient on the clinical side? This is the part most directly analogous to the earlier recipes in this chapter. Within a single institution where you have an MRN-to-member-ID cross-reference, the link is largely deterministic, modulo the cross-reference's accuracy. Across organizations or for claims data covering populations that include patients with no clinical record at the analyzing institution, the link is the cross-organizational match from recipe 5.5 with the additional constraint that it is being done in batch over historical data rather than at query time.

**Encounter-level link.** Is this set of claims for the same care event as this clinical encounter? Given a patient match, this is the harder question. A claim is anchored on a service date or date range, a billing entity, and a billed service. An encounter is anchored on an admission timestamp, a discharge timestamp, an attending provider, an encounter class, and a location. The match has to align the claims dates with the encounter timestamps (with the timing tolerance the institution's data conventions require), align the billing entity with the institution (or with the institution's affiliated entities, which is often a different question), align the billed service with the encounter class (a facility claim with revenue codes for room-and-board belongs to an inpatient encounter; a professional claim with an office-visit CPT belongs to an outpatient encounter), and produce a confident link. The claim-to-encounter link is one-to-one in some encounter classes (a routine outpatient visit with one professional claim) and one-to-many in others (an inpatient stay with several facility and professional claims).

**Care-event-level link.** Within an encounter, is this specific claim line the billing artifact for this specific clinical event? A patient's inpatient stay generates orders for labs, imaging, and medications. The claims for those services may show up as discrete line items on the facility claim or as separate professional claims (the radiologist's professional fee for the CT, the pathologist's fee for the cytology). The link from the line item to the clinical event is what powers detailed cost-and-quality analytics: how much did the heart-failure admission cost broken down by service line, what fraction of the ICU stay was directly attributable to ventilator support, did the patient receive the right diagnostic workup for the suspected sepsis. The care-event link is the most fragile, because the clinical orders and the billing line items use different code systems (CPT/HCPCS on the billing side, internal procedure orders or LOINC on the clinical side) and the mapping is often approximate.

**Diagnostic-attribution link.** A claim's primary diagnosis is the reason for the encounter as the coder represented it. The clinical encounter has its own diagnoses, including admitting, working, and discharge diagnoses. For analytics that depend on accurate diagnosis attribution (HCC risk adjustment, condition-specific quality measures, cohort definition for outcomes research), the linkage must be aware that the diagnoses on the claim and the diagnoses on the chart are not identical and may need reconciliation rather than treating either as authoritative.

The recipe focuses on the patient-level and encounter-level links (where the entity-resolution techniques live), with hooks for the care-event level. The line-item-to-clinical-event mapping is its own subject and is largely vocabulary-mapping work (CPT to internal procedure code, NDC to RxNorm, revenue code to internal cost-center) on top of the encounter-level link.

### Why Linkage Is Harder Than It Sounds (Again)

Six structural reasons:

**Multiple claims per encounter, with no shared encounter identifier.** Even within one institution, the claims for a single encounter rarely point at each other directly. A facility claim and a professional claim for the same inpatient stay may share the patient's member ID and have overlapping service dates, but they have different claim identifiers, different billing entities, different submission dates, and they do not reference each other. The matcher has to group them into encounter clusters based on the timing-and-overlap pattern. Across institutions or in claims feeds from payers, the situation is worse because even the institutional control numbers are stripped out before the payer sends the data back.

**Timing misalignment between clinical event and billing.** Claims arrive on a delay. The institution's own outbound claims show up in the claims warehouse within days of submission, but the inbound claims feed from a payer (showing not just the institution's claims but every claim for the institution's patients across every provider in the payer's network) often lags by weeks or months. Resubmissions, adjustments, and denials further extend the timeline. An analytics pipeline that links yesterday's clinical encounters to yesterday's claims will find very few matches; the matching has to operate over a window that lets the claims catch up.

**Many-to-many relationships at the patient and encounter levels.** A patient may have multiple encounters in the analysis window, several of which produce overlapping claims (a colonoscopy ordered in an outpatient visit, performed at an ambulatory-surgery center, with a pathology read at a separate lab; a hospitalization with a transfer to a different facility mid-stay; a series of related ER visits for the same evolving condition). The matcher has to disambiguate which claims go with which encounter without splitting closely-related claims that legitimately span encounters.

**Diagnosis and procedure code drift.** The EHR records the working diagnosis at the time of the encounter; the claim records the diagnosis the coder assigned weeks later. The codes may differ (different ICD-10 codes for the same condition at different specificity levels), the codes may shift in coding-update cycles (annual ICD-10-CM updates change the available codes; CPT changes annually too), and the codes may reflect different perspectives (the cardiologist's claim has the cardiac diagnosis; the hospitalist's claim has the hospitalist's view of the same patient with possibly different secondary conditions emphasized). Reconciling the two without losing information is its own subproblem.

**Adjustments, denials, and resubmissions.** A single underlying clinical event may produce a sequence of claim records over time: the original submission, a denial, a resubmission with updated documentation, a partial adjustment after audit, a write-off. The matcher has to recognize the sequence as one underlying event rather than counting each record separately, and the analytics pipeline has to know which version of the record to use as authoritative for each kind of question. Some questions want the original (what was the institution's first attempt at characterizing the encounter), some want the final (what did the patient actually owe and what did the payer actually pay), some want all versions (what was the adjudication trajectory over time).

**Cross-payer heterogeneity in claim quality.** The institution's outbound claims are well-formed because the institution controls their generation. The inbound claims feed from a payer aggregates claims from many submitting providers, and the data quality varies. Some payers strip data fields (member-ID-related fields, internal control numbers, secondary identifiers) before forwarding. Some payers normalize the data; some pass it through. Some payers have real-time eligibility-and-claim feeds; some have monthly batch deliveries that have already aged by the time the institution receives them. The matcher has to be tolerant of the heterogeneity and the analytics pipeline has to know the data source for each match decision so that downstream reasoning can apply payer-specific rules.

### Where the Field Has Moved

A few practical updates worth knowing:

**The OMOP Common Data Model has become the de facto research substrate.** OHDSI's Observational Medical Outcomes Partnership Common Data Model (OMOP CDM) provides a target schema and a vocabulary set that normalizes both claims and clinical data into a unified relational structure.  An organization that loads its claims and EHR data into an OMOP instance gets a pre-built person-encounter-care-event hierarchy, with vocabulary mappings between ICD-10 / SNOMED / RxNorm / LOINC / CPT done by the OMOP team rather than by the institution. The link itself is still the institution's responsibility (OMOP does not, by itself, link a particular EHR encounter to a particular claim), but the post-link analytics environment is enormously more productive than rolling your own. Outcomes research and pharmacoepidemiology in particular have largely standardized on OMOP. 

**FHIR is becoming the clinical-side lingua franca.** Where the claims-to-clinical link historically pulled clinical data out of an EHR-specific schema (Epic Clarity / Caboodle, Cerner / Oracle Health, etc.), the FHIR US Core implementation guide and the broader FHIR R4 ecosystem provide a normalized clinical schema that the link can target.  An institution with a FHIR-native data lake can run the linkage against FHIR resources directly, and the linkage code is portable across institutions and EHR vendors. Most production claims-to-clinical pipelines today are hybrid (EHR-native for the high-volume historical extracts, FHIR for the current operational view), but the trajectory is toward FHIR.

**The CMS Blue Button 2.0 and Patient Access APIs surface claims data to patients and apps.** Patients can now authorize a third-party app to receive their Medicare claims through the Blue Button 2.0 API, and most payers offer equivalent FHIR-based Patient Access APIs under the CMS Interoperability Final Rule.  The practical implication for claims-to-clinical linkage is that the patient is increasingly the connecting point: an app that has both the patient's clinical data (from an EHR FHIR endpoint) and the patient's claims data (from a payer FHIR endpoint) can do the link client-side, with the patient's authorization, without going through the institution's data warehouse at all. This is a structural shift; it does not eliminate the institution's need for the link but it adds a new architectural pattern.

**Tokenization-based linkage in claims-to-clinical research.** Vendors like Datavant and HealthVerity offer privacy-preserving tokenization services that produce a deterministic patient token from demographic data using a salted hash. The token is generated identically on the claims side and the clinical side, allowing a link without exchanging raw demographics.  This is operationally important for research datasets that combine claims data from a payer with clinical data from a provider where direct demographic exchange is not legally available; it is increasingly common for de-identified-research-purposes use cases.

**Real-world data quality frameworks have matured.** Industry initiatives (the FDA's Real-World Evidence Program, PCORnet's Common Data Model and data-quality framework, Sentinel's analytic data model) have produced data-quality benchmarks, validation methods, and reporting templates that did not exist a decade ago.  The practical implication for claims-to-clinical linkage is that "what does a good link look like" is becoming a question with documented industry answers (link rate, encounter-coverage rate, diagnosis-concordance rate, with target ranges) rather than a per-organization improvisation.

**Information-blocking rules apply here too.** The 21st Century Cures Act information-blocking provisions cover claims data alongside clinical data in many use cases. An institution that has a claims-to-clinical link infrastructure is increasingly expected to make linked data available to patients on request, to other providers as part of care coordination, and to public-health agencies as part of mandated reporting. The architecture has to support those release patterns; building the linkage as an analytics-only system that is not patient-accessible is increasingly noncompliant. 

---

## General Architecture Pattern

The pipeline has six logical stages: ingest both data streams, resolve patient identity across the streams, group claims into encounter clusters, match those encounter clusters to clinical encounters, attribute care events within the matched encounter, and react to events that invalidate prior linkages (claim adjustments, denials, resubmissions, EHR encounter amendments, patient identity merges).

```text
┌────────────── INGEST ─────────────────────────────┐
│                                                    │
│  [Claims-side sources]                             │
│   - Outbound institutional claims (X12 837I)       │
│   - Outbound professional claims (X12 837P)        │
│   - Inbound payer feeds (X12 835 remits, payer-    │
│     specific claim files, FHIR ExplanationOfBenefit│
│     resources from Patient Access APIs)            │
│   - Pharmacy claims (NCPDP feed)                   │
│                                                    │
│  [Clinical-side sources]                           │
│   - EHR encounter records (admission/discharge,    │
│     class, location, attending, diagnoses)         │
│   - Clinical observations (orders, results, vitals)│
│   - Medication-administration records              │
│   - Procedure events                               │
│   - Discharge summaries and other documents        │
│           │                                        │
│           ▼                                        │
│  [Land in raw zone:                                │
│   - Partition by source, date, encounter_class    │
│   - Preserve original payload byte-for-byte for    │
│     audit and replay]                             │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── NORMALIZE ──────────────────────────┐
│                                                    │
│  [Claims-side normalization:                       │
│   - Parse X12 segments or FHIR resources          │
│   - Standardize identifiers (member_id, claim_id, │
│     billing_provider_npi, rendering_provider_npi) │
│   - Standardize codes (ICD-10, CPT/HCPCS,         │
│     revenue codes, NDC)                           │
│   - Compute derived fields (encounter_class_      │
│     inferred, service_window_days,                 │
│     claim_status_at_snapshot)]                     │
│                                                    │
│  [Clinical-side normalization:                     │
│   - Map EHR-native schemas to FHIR resources or  │
│     OMOP tables                                    │
│   - Standardize identifiers (mrn, encounter_id,  │
│     attending_npi, location_id)                    │
│   - Standardize codes (SNOMED, RxNorm, LOINC,    │
│     internal procedure codes)                      │
│   - Resolve diagnosis lifecycle (admitting,       │
│     working, discharge) into a per-encounter      │
│     diagnosis set]                                │
│                                                    │
│  [Cross-stream:                                    │
│   - Apply institutional MRN-to-member-ID cross-   │
│     reference (output of recipe 5.1's MPI plus   │
│     payer cross-reference table)                  │
│   - Standardize provider identifiers via the NPI  │
│     resolver from recipe 5.2]                     │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── PATIENT-LEVEL LINK ─────────────────┐
│                                                    │
│  [Resolve claims-side member to clinical-side    │
│   patient:                                         │
│   - Deterministic via MRN-to-member-ID cross-     │
│     reference where present                       │
│   - Probabilistic via demographic match (recipe   │
│     5.1 / 5.4 scorer) where the cross-reference  │
│     is missing or stale                            │
│   - Cross-organizational match (recipe 5.5) for   │
│     external claims feeds]                        │
│           │                                        │
│           ▼                                        │
│  [Output: claim record annotated with             │
│   resolved_local_patient_id and                    │
│   patient_link_confidence; claims that fail to    │
│   link are flagged for the patient-link review    │
│   queue with their candidates]                    │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── CLAIM CLUSTERING ───────────────────┐
│                                                    │
│  [Group claims that describe a single underlying   │
│   encounter:                                       │
│   - Same patient                                   │
│   - Overlapping or adjacent service dates within  │
│     a tolerance specific to encounter class       │
│     (inpatient: full-stay window; outpatient:     │
│     same-day; ER: same-shift)                     │
│   - Compatible encounter-class signatures         │
│     derived from revenue codes, place-of-service, │
│     and CPT category]                              │
│           │                                        │
│           ▼                                        │
│  [Detect resubmissions, adjustments, and          │
│   denials within the cluster:                     │
│   - Same-or-related claim_id sequences           │
│   - Same service line on different submission    │
│     dates                                          │
│   - Adjustment indicators in the X12 835 remit]  │
│           │                                        │
│           ▼                                        │
│  [Output: claim clusters keyed on a synthetic     │
│   encounter_cluster_id, with each member claim   │
│   tagged by role (primary, resubmission,          │
│   adjustment, related-professional)]              │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── ENCOUNTER LINK ─────────────────────┐
│                                                    │
│  [Match claim clusters to clinical encounters:    │
│   - Same patient (high confidence required)      │
│   - Date alignment within encounter-class         │
│     tolerance                                      │
│   - Encounter class compatibility (inpatient     │
│     facility cluster matches inpatient EHR        │
│     encounter; outpatient cluster matches         │
│     outpatient encounter)                          │
│   - Provider alignment (the rendering NPI on     │
│     the claim matches an attending or             │
│     consulting provider on the EHR encounter)    │
│   - Diagnosis concordance (overlap between       │
│     claim primary/secondary diagnoses and        │
│     EHR encounter diagnoses; partial overlap     │
│     is normal)]                                   │
│           │                                        │
│           ▼                                        │
│  [Score each candidate (claim cluster, EHR       │
│   encounter) pair using Fellegi-Sunter-style     │
│   weights tuned for the encounter-link problem;  │
│   apply confidence thresholds:                    │
│   - >= AUTO_LINK_HIGH: confident link;           │
│     attribute the cluster to the encounter      │
│   - >= AUTO_LINK_MED: probable link; attribute  │
│     with a confidence flag                       │
│   - <= AUTO_REJECT: no link; cluster goes to    │
│     the unmatched-claims pool                    │
│   - in between: encounter-link review queue]    │
│                                                    │
│  [Special cases:                                  │
│   - Cluster has no candidate encounter           │
│     (encounter happened at an outside facility   │
│     or before the EHR coverage window): tag     │
│     external_encounter and retain               │
│   - Encounter has no candidate cluster (claims  │
│     have not arrived yet, or the encounter was   │
│     not billable): tag awaiting_claims and       │
│     re-evaluate on cluster arrival]              │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── CARE-EVENT ATTRIBUTION ─────────────┐
│                                                    │
│  [For matched (cluster, encounter) pairs,         │
│   attribute claim line items to clinical events:  │
│   - CPT/HCPCS to internal procedure code via     │
│     vocabulary map                                 │
│   - NDC to RxNorm via vocabulary map             │
│   - Revenue code to internal cost-center          │
│   - Date-and-time alignment of claim line to    │
│     order or administration time on the EHR      │
│     side                                           │
│   - Provider attribution (which provider          │
│     ordered, which provider performed)]           │
│           │                                        │
│           ▼                                        │
│  [Output: linked encounter record with the        │
│   joined claim and clinical detail; flag any     │
│   line items that did not attribute to a         │
│   clinical event for the line-item review        │
│   queue]                                           │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── PERSIST + AUDIT ────────────────────┐
│                                                    │
│  [Linkage record:                                  │
│   - encounter_cluster_id and constituent          │
│     claim_ids                                     │
│   - linked_clinical_encounter_id (or              │
│     external_encounter / awaiting_claims tag)    │
│   - link_confidence (per-link, with feature      │
│     breakdown)                                     │
│   - link_method (deterministic via MRN-and-      │
│     dates, probabilistic, manual)                 │
│   - line_item_attribution (per-line-item link    │
│     to clinical events)                          │
│   - linker_configuration_version                 │
│   - resolved_at                                   │
│   - audit log entries for any prior linkage     │
│     state that this record supersedes]           │
│           │                                        │
│           ▼                                        │
│  [Write to the claims-clinical-linkage store as  │
│   the system of record]                           │
│           │                                        │
│           ▼                                        │
│  [Emit claims_clinical_link_resolved event for    │
│   downstream consumers (analytics, quality        │
│   measurement, risk adjustment, longitudinal     │
│   record assembly, care management)]             │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── INVALIDATION / REFRESH ─────────────┐
│                                                    │
│  [Subscribe to events that invalidate prior        │
│   linkages:                                        │
│   - New claim arrives that affects a prior       │
│     cluster (resubmission, adjustment,           │
│     additional professional claim for the         │
│     encounter)                                    │
│   - Claim denial reverses a prior link            │
│   - EHR encounter amendment changes diagnoses,    │
│     timestamps, or attending                      │
│   - Patient identity merge or unmerge (recipe   │
│     5.1) changes the resolved patient on one     │
│     side                                           │
│   - Cross-organizational identity change         │
│     (recipe 5.5)                                  │
│   - Vocabulary map update (annual ICD-10 / CPT  │
│     refresh)]                                     │
│           │                                        │
│           ▼                                        │
│  [Re-evaluate the affected linkages; emit         │
│   claims_clinical_link_invalidated events with   │
│   the prior and new linkage states so downstream │
│   consumers can refresh]                         │
│                                                    │
└────────────────────────────────────────────────────┘
```

**The matcher runs in batch but is event-aware.** Unlike recipe 5.5's query-time matcher, claims-to-clinical linkage runs in batch over a sliding window (typically the past 90 to 180 days, sometimes longer for retrospective research builds). Within the window, the linker re-evaluates as new claims arrive and as EHR encounters get amended. The events drive the re-evaluation; the substrate is batch.

**Cluster-then-link is the right ordering.** The naive approach (match each claim individually to an encounter) loses the structural information that several claims belong to the same encounter cluster, and it produces a brittle matcher that is sensitive to single-claim outliers. Clustering claims into encounter-cluster candidates first, then matching the cluster to the encounter, is more robust. The cluster as a whole carries timing-and-overlap signals that no individual claim has, and the matched cluster gives the analytics pipeline the unit of analysis it actually needs.

**Date tolerance is encounter-class-specific.** Inpatient claims need a date tolerance large enough to cover the entire stay plus the late-billing window (the discharge claim may have a service-through date a day or two after the actual discharge). Outpatient claims need a tight tolerance (claim service date should match the encounter date almost exactly, with single-day slop for after-hours encounters that get billed the next morning). ER claims need a tolerance that handles the same-day-but-overlapping pattern of facility plus several professional claims. The tolerance values live in versioned configuration; calibration against the institution's gold set is an institutional discipline, not a magic number.

**Diagnosis concordance is a soft signal, not a hard one.** The diagnoses on the claim and the diagnoses on the EHR encounter overlap but are rarely identical. Treating "diagnoses match exactly" as a required signal will under-link; treating them as completely irrelevant will over-link patients with multiple encounters in the same window. The right pattern is to score diagnosis overlap as one feature among several (with partial-overlap credit, with hierarchy-aware comparison so that a more-specific code on one side counts as a match for the less-specific code on the other side), and to let the composite score handle it.

**External encounters are first-class outputs.** Many claims will not match any local encounter because the encounter happened at a different institution. These claims are still data; they describe the patient's care trajectory outside the institution. Tag them as external_encounter with their inferred encounter class, the rendering provider's NPI, and the diagnosis-and-procedure summary, and surface them to the longitudinal-record-assembler. The institution learns about its patients' outside care primarily through this path.

**Awaiting-claims is a real state.** Many local encounters will not have a claim cluster at the time of initial linking because the claims have not arrived yet. Tag the encounter as awaiting_claims and re-evaluate on cluster arrival. The awaiting state has its own retention policy (an encounter with no claim cluster after 180 days is probably never going to get one, and gets re-tagged as billed_externally or non_billable).

**Resubmissions and adjustments are tracked at the cluster level.** A cluster's claim list includes the original submission, any resubmissions, and any adjustments. The cluster has a current authoritative claim version and a history. Analytics queries that need the original submission read the original; queries that need the final adjudicated state read the current; queries that need the trajectory read the history. The persistence layer keeps all three accessible.

**The invalidation pipeline is the durability story.** Without invalidation, prior linkages go stale as new claims arrive, EHR amendments happen, and identity merges propagate. The linkage store is event-driven on the maintenance side; every change to a constituent record fires an invalidation event, and the re-evaluation either confirms the prior link, modifies it, or marks it superseded. Skip the invalidation pipeline and you build a linkage table that looks accurate on day one and is silently wrong by day ninety.

**Cohort-stratified accuracy monitoring applies here too.** Linkage rates and accuracy are not uniform across patient cohorts. Patients with primary care concentrated at the institution and minimal outside care will have higher linkage rates than patients whose care is spread across many providers. Patients with stable demographic capture will link better than patients with mid-period name changes or address changes. Per-cohort link rate, per-cohort encounter-coverage rate, and per-cohort diagnosis-concordance rate are the right metrics; per-cohort thresholds and disparity alarms are the right monitoring.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter05.06-architecture). The Python example is linked from there.

## The Honest Take

Claims-to-clinical data linkage is the recipe in this chapter where the technical complexity is moderate and the data-quality complexity is enormous. The matching techniques are familiar (you have seen the same probabilistic-record-linkage core in every recipe of this chapter). The orchestration is familiar (batch ETL jobs, workflow orchestration, event buses, the same pattern as the analytics-grade pipelines you have built before). The thing that makes this recipe hard is that the inputs disagree with each other in ways that are not bugs and cannot be fixed at the source. The claims data and the clinical data describe the same encounters through completely different lenses, with different identifiers, different time conventions, different vocabularies, and different completeness profiles. The job of the linkage pipeline is to produce a useful join despite the disagreements, with awareness that the disagreements are the data, not noise around it.

The trap most specific to claims-to-clinical linkage is treating it as an analytics-only system that runs once and produces a static result. Claims keep arriving. EHR encounters keep getting amended. Patients keep getting their identities merged. Vocabulary maps keep getting updated annually. A linkage table that is correct on the day it is built is silently wrong by the third month if the invalidation pipeline is not running. The institutions that deploy claims-to-clinical linkage well treat it as a continuously-running pipeline with the same operational rigor as a transactional system. The institutions that treat it as a one-time analytics project find that their derived outputs decay in accuracy at a rate that nobody is monitoring, and the decay shows up months later as a quality-measurement number that is too good or a cost-trend that is too bad and nobody can explain why. Build the invalidation pipeline first, before the matcher; the matcher is the easy part.

The second trap is over-trusting the claims data on diagnosis. The diagnosis on a claim is the coder's representation of the encounter, optimized for billing under whatever incentive structure the contract creates. The diagnosis on the EHR encounter is the clinician's representation, optimized for clinical care. Neither is the ground truth on what the patient actually has. For most analytics, you want both, with awareness of which is which. A risk-adjustment program that computes HCC scores from claims-side diagnoses gets one answer; a quality measure that computes denominator membership from EHR-side diagnoses gets a different answer; a research study that wants both perspectives uses them as separate features. The linkage gives you both; the analytics built on top of the linkage need to know that there are two diagnoses for every encounter and they are not the same.

The third trap, related: under-investing in vocabulary maintenance. The vocabulary maps are the lubricant of the entire pipeline. CPT to internal procedure code, NDC to RxNorm, revenue code to internal cost center, ICD-10 hierarchy. When the vocabulary maps are well-maintained, the linkage's attribution coverage is high, the cost rollups are accurate, and the analytics outputs are trustworthy. When the vocabulary maps drift (because the annual coding-update cycle introduced new codes that the institution did not map, or because the institution acquired a new clinical service line that uses procedure codes that were not in the historical map), the attribution coverage drops, the unattributed line items pile up, and the analytics outputs get noisy. Treat vocabulary maintenance as a permanent line item in the analytics budget, not as a one-time setup task.

The thing that surprises people coming from other entity-resolution backgrounds is how much of the matcher's signal comes from non-demographic features. In recipe 5.1, the patient match is dominated by name, DOB, and address. In recipe 5.6, the encounter match is dominated by date, provider, encounter class, and diagnosis. The patient identity is largely settled before the encounter linker even runs (deterministically through the cross-reference table or probabilistically through the patient-link step). The encounter linker's job is to find the right encounter for a known patient, and the signals it uses are operational rather than demographic. This is a different mental model than internal duplicate detection; budget the time to build the encounter-feature scorer with as much care as you would build the demographic scorer.

The thing about late-arriving claims: it is the dominant operational issue in production. Initially, teams build the linkage pipeline to run nightly over the prior day's data and assume that yesterday's claims are now linked. Then they discover that "yesterday's claims" actually means "the institution's outbound claims that were submitted yesterday, not the inbound payer feeds covering yesterday's encounters at outside providers, which will not arrive for another six to eight weeks." The pipeline has to be designed to operate on a sliding window and to re-link as late-arriving claims appear. The first version that does not handle the late-arriving claims will produce a dataset that looks complete on day one, undercounts cross-organizational care for the first eight weeks, and then back-fills into accuracy in a way that confuses everyone using the data. Communicate the back-fill behavior to the analytics consumers explicitly, or you will spend a lot of time explaining why "the readmission rate for January looked different last week than it does this week."

The thing about external encounters: they are usually the highest-value part of the linkage output, even though they are the most awkward to build. The institution's clinical staff already knows about the local encounters (they ran them); the claims-to-clinical link is informative but not transformative for that data. The external encounters are net new information: care that the patient received outside the institution that the institution would not otherwise know about. A care manager who can see "your patient was in a different system's ER three nights ago" can intervene; a quality-measurement program that can see "the patient had their preventive screening at the outside imaging center we send overflow to" gets a more accurate quality measure; a longitudinal-record-assembler can produce a complete view rather than a partial view. The external-encounter pipeline pays for the rest of the linkage infrastructure. Build it with that perspective.

The thing about the encounter-class boundary cases: there are more of them than you expect. Observation-to-inpatient transitions. Outpatient-procedure-to-observation. Same-day-surgery-to-overnight-stay. ED-to-observation-to-inpatient. Each pattern has its own claim sequence and its own EHR encounter sequence, and the institution's revenue-cycle conventions for handling them vary. The first version of the encounter-class compatibility scorer will be too strict and will leave a lot of legitimate matches unlinked; the second version will be too loose and will start scrambling them. The right version comes from working through the institution's specific revenue-cycle conventions with the revenue-cycle team and the clinical-informatics team together, and configuring the class-compatibility matrix to reflect those conventions. Plan for two-to-three iterations on the configuration in the first six months.

The thing I would do differently the second time: invest in the joint-evaluation pattern from day one. The greedy approach (evaluate each cluster against each candidate encounter independently, pick the highest score for each cluster) is simpler to build but produces scrambled assignments when the patient has multiple encounters in the same window with overlapping characteristics. The joint approach (consider all candidate-cluster-to-candidate-encounter pairs for the patient simultaneously and find the assignment that maximizes the global score) is more expensive but is dramatically more accurate for the boundary cases. Most teams build the greedy version first because it is easier; most teams then have to retrofit the joint version when the analytics team flags a quality-measurement number that does not pass smell test. Build the joint version first.

The thing about the OMOP integration: it is a much bigger project than the linkage itself. Standing up an OMOP CDM instance is a significant undertaking (vocabulary alignment, source-to-CDM mapping, data-quality validation, the OHDSI tooling setup). If the institution is going to land its analytics on OMOP, the linkage is a piece of the larger OMOP project, not a standalone deliverable. If the institution already has an OMOP instance, the linkage outputs feed it; the integration is more contained. Either way, scope the linkage and the OMOP work as a coordinated program with clear handoffs.

Last point, because it is specific to the regulatory context: information-blocking applies to claims data in many of the same ways it applies to clinical data. An institution that has built a high-quality claims-to-clinical linkage is in a stronger position to comply with the patient-access and provider-access requirements of the 21st Century Cures Act, because the linked record is what the patient or provider is asking for. An institution that has not built the linkage is more likely to deliver a partial response to a patient-access request and to be characterized as information-blocking when the patient discovers that the institution's response does not include their outside-care visibility from the claims feed. Build the linkage with the patient-access and provider-access use cases in scope, not just the analytics use cases. The architecture is then load-bearing for compliance, not just for internal analytics.

---

## Related Recipes

- **Recipe 5.1 (Internal Duplicate Patient Detection):** The local MPI is the canonical patient identity that the claims-to-clinical link resolves to. Patient-identity merges from 5.1 propagate through the invalidation pipeline to re-link affected encounter clusters.
- **Recipe 5.2 (Provider NPI Matching):** The NPI resolver from 5.2 normalizes provider identifiers on both the claims side (billing and rendering NPIs) and the clinical side (attending and consulting providers); the encounter-link's provider-alignment scorer depends on it.
- **Recipe 5.3 (Address Standardization and Household Linkage):** Address consistency is one demographic feature in the patient-link step for external claims feeds; recipe 5.3's pipeline standardizes addresses identically on both sides.
- **Recipe 5.4 (Insurance Eligibility Matching):** The MRN-to-member-ID cross-reference is built and maintained by the eligibility-matching pipeline; the claims-to-clinical link reads from it for the deterministic patient-link path.
- **Recipe 5.5 (Cross-Facility Patient Matching):** Cross-organizational identity resolution from 5.5 supplies the patient identity for claims covering encounters at other organizations; the cross-facility match output and the claims-to-clinical link both feed the longitudinal-record-assembler.
- **Recipe 5.7 (Longitudinal Patient Matching Across Name Changes):** Name-change patients have demographic asymmetry between claims (which may carry the old name from a prior payer enrollment) and clinical data (which may carry the new name from a recent registration); recipe 5.7's prior-name handling is reused in the patient-link step.
- **Recipe 5.8 (Privacy-Preserving Record Linkage):** Tokenization-based linkage (a variation above) is the operational manifestation of recipe 5.8's techniques in the claims-to-clinical context; relevant for research uses where direct demographic exchange is not legally available.
- **Recipe 5.9 (National-Scale Patient Matching):** TEFCA-mediated identity resolution feeds the patient-link step for claims data that flows through national-scale exchange; the architecture extends to consume the QHIN-mediated identity tokens.
- **Recipe 5.10 (Deceased Patient Resolution):** Deceased-patient events from 5.10 invalidate prior linkages and may trigger reconciliation of post-mortem claims (which can continue to arrive for months after death); the invalidation pipeline handles the propagation.
- **Recipe 1.5 (Claims Attachment Processing):** Claims attachments contain clinical detail that supplements the claim itself; the claims-to-clinical link can incorporate attachment-derived information as additional features.
- **Recipe 1.8 (EOB Processing):** The Explanation of Benefits is the patient-facing version of the X12 835 remittance; the EOB-processing pipeline feeds the patient-mediated linkage variation.
- **Recipe 2.6 (Clinical Note Summarization):** Linked encounters with their constituent claims are richer summarization inputs than encounters alone; the claims context informs the summary's framing for cost-and-quality discussions.
- **Recipe 3.1 (Duplicate Claim Detection):** Duplicate-claim detection runs on the claims side; the linkage's claim-clustering step reuses the same claim-version-and-resubmission logic.
- **Recipe 3.6 (Healthcare Fraud, Waste, and Abuse Detection):** Linked encounters where the claims and clinical data disagree substantially are signals for the fraud-detection pipeline; the link surfaces the candidates for downstream analysis.
- **Recipe 7.x (Predictive Analytics):** Risk-scoring features depend heavily on linked claims-and-clinical data; readmission prediction, total-cost-of-care prediction, and condition-progression models all consume the linkage output.

---

## Tags

`entity-resolution` · `record-linkage` · `claims-to-clinical` · `claims-clinical-linkage` · `omop` · `omop-cdm` · `pcornet` · `sentinel` · `fhir` · `explanationofbenefit` · `x12` · `837` · `835` · `ncpdp` · `vocabulary-mapping` · `cpt` · `hcpcs` · `icd-10` · `ndc` · `rxnorm` · `loinc` · `revenue-codes` · `drg` · `hcc` · `risk-adjustment` · `quality-measurement` · `outcomes-research` · `real-world-evidence` · `glue` · `spark` · `dynamodb` · `athena` · `lake-formation` · `healthlake` · `eventbridge` · `step-functions` · `event-driven` · `medium-complex` · `production` · `hipaa` · `information-blocking` · `cures-act`

---

*← [Recipe 5.5: Cross-Facility Patient Matching (HIE)](chapter05.05-cross-facility-patient-matching) · Chapter 5 · [Next: Recipe 5.7 - Longitudinal Patient Matching Across Name Changes →](chapter05.07-longitudinal-patient-matching-name-changes)*
