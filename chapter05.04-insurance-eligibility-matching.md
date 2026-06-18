# Recipe 5.4: Insurance Eligibility Matching ⭐⭐⭐

**Complexity:** Medium · **Phase:** Production · **Estimated Cost:** ~$0.001-0.005 per real-time eligibility match attempt and ~$0.0005 per batch-processed record (depends on payer connectivity model, X12 270/271 transaction fees, and review-queue volume for ambiguous matches)

---

## The Problem

It is 7:42 AM. A patient walks into a busy primary care office for a follow-up visit. The front desk staff scans her insurance card, the practice management system fires off an eligibility verification request to her health plan, and the response comes back in about three seconds: *member not found*.

She has the card in her hand. She paid the premium last month. She knows she has coverage. But the practice management system is telling the front desk that the payer's eligibility file has no record of her. Now what?

Maybe the front desk staff types her name and DOB into the payer's web portal manually, finds her there, and copies the member ID back into the practice management system. Maybe it turns out the card has the wrong member ID printed because the card was issued before a mid-year plan change. Maybe the patient is in a coverage lookup with her maiden name in the payer system but her married name in the practice system. Maybe the patient's DOB was keyed in wrong by the payer when she was first enrolled and has been wrong for years. Maybe the payer's eligibility file is two days behind because their nightly batch job failed and nobody noticed yet. Maybe she has secondary coverage through her spouse and that's the active one today. Maybe a prior authorization issue caused the payer to flag her account for manual review and the eligibility response is technically accurate but the actual coverage status is "yes, but with a hold."

While the front desk is figuring this out, the patient is standing there. The exam room is open. The provider is waiting. The next patient is in the lobby. The whole rhythm of the morning starts breaking down because of one mismatched eligibility lookup that the system should have been able to resolve automatically.

Now multiply this by the volume of patient encounters at any reasonably-sized health system. A medium-sized primary care network does tens of thousands of eligibility verifications a month. A hospital system does hundreds of thousands. A national lab company does tens of millions. A non-trivial fraction of those verifications do not match cleanly on the first attempt, and somebody, somewhere, has to figure out what to do with the ones that don't. <!-- TODO: verify; CAQH CORE and industry literature consistently report that 5-15% of real-time eligibility verifications return a "member not found" or "coverage indeterminate" response, with substantial variation by payer, plan, and patient population. -->

The downstream consequences are not abstract:

You are running revenue cycle for a multi-specialty group, and a meaningful percentage of the claims you submit get denied for "patient ineligible at time of service." You investigate the denials and find that, in most cases, the patient *was* eligible. The eligibility verification at registration just didn't find them, the front desk worked around it (selected the closest-matching record they could find, or skipped the eligibility check entirely under time pressure), and the claim went out with bad coverage data. The denial is reversed on appeal, eventually, but the appeal cycle costs you money and the cash flow hit is real.

You are a hospital running a charity care and financial-assistance program, and one of the eligibility criteria is "no active commercial or government coverage." You need to match each financial-assistance applicant against every payer's active-coverage rolls to confirm they are uninsured. The matching has to be done across multiple payers, none of which use the same demographics format, none of which have a shared identifier with your patient records. A meaningful fraction of applicants fail the initial automated match and have to be reviewed manually. Your eligibility-determination cycle that should take days takes weeks, and patients who should qualify wait longer than they should.

You are a Medicaid managed-care plan and the state requires you to reconcile your member roll against the state's Medicaid Management Information System (MMIS) monthly. The MMIS file is millions of records. Your member file is hundreds of thousands. The match has to handle name variations, address differences, DOB inconsistencies that creep in over enrollment cycles, and the fact that some members have been transferred from one plan to another mid-cycle and are technically yours for part of the period and somebody else's for the rest. You ship the reconciliation report to the state, and the state finds discrepancies that they want explained.

You are a payer running enrollment, and a self-funded employer client just sent you their open-enrollment census file. Forty-thousand subscribers, each with potentially multiple dependents, and the demographics format is roughly what you can work with but not exactly. You need to match the incoming census records against your existing membership to figure out who is staying, who is leaving, who is new, and who has changed their dependent structure. The match quality determines whether you correctly issue ID cards, set up provider directories, and bill premiums for the right people on January 1.

You are a clearinghouse, and you sit in the middle of the X12 270/271 eligibility-verification transaction flow. Providers send you 270 requests, you route them to the right payer, you receive 271 responses, and you forward them back to the provider. <!-- TODO: confirm at time of build; X12 270 (eligibility/benefit inquiry) and X12 271 (eligibility/benefit response) are the HIPAA-mandated standards for electronic eligibility verification, and CAQH CORE publishes operating rules that constrain how they're used. --> Some payers' 271 responses are useful. Some payers come back with so little detail that the provider can't actually tell whether the patient is covered for the specific service they're about to deliver. You are not the payer, and you can't fix the underlying data, but the providers are calling your support line because the eligibility data they're getting from you is not actionable. You need a layer that augments and reconciles 271 responses, applies the rules the payers should have applied, and produces a coverage answer that the front-desk staff can act on.

This is the recipe. Insurance eligibility matching is the entity-resolution problem of "is this person, today, in this payer's coverage population?" with the additional constraints that the answer often needs to come back in real time, the data on both sides is imperfect, the cost of getting it wrong is borne by the patient, and the operational and regulatory rules around insurance data are dense.

It is in the medium-complexity tier because it crosses organizational boundaries (no shared identifier, two parties' demographic data must be reconciled), it has real-time performance requirements (eligibility verification at point of service has to fit in the registration flow), it has dense regulatory constraints (HIPAA, state insurance regulations, CAQH CORE operating rules, the No Surprises Act for some downstream uses, ACA requirements for certain market segments), and it has a payer-data-quality dimension that you cannot directly fix and have to architect around. The technique stack is the same probabilistic-and-deterministic core you saw in 5.1 and 5.2, but the operational patterns and the data flows are different enough to deserve their own recipe.

Let's get into how you build it.

---

## The Technology: Eligibility Matching as a Cross-Organization Entity Resolution Problem

### Why Eligibility Matching Is Different From Internal Patient Matching

You have already seen the basic toolkit (recipes 5.1 and 5.2): deterministic matching for the easy cases, probabilistic scoring for the medium cases, ML re-ranking for the hard ones, human review for the borderline ones. The toolkit applies here. What changes is the operational context and the data realities.

In recipe 5.1, the data on both sides of the match is yours. You can clean it. You can normalize it. You can fix the registration UI to capture cleaner data going forward. You can run an analytics pipeline against the entire population on your timeline.

In recipe 5.4, half the data is the payer's. You cannot clean it. You cannot normalize it (in their system). You cannot change how they capture it. You can only see what they choose to expose to you, in the format they choose to expose it, on the cadence they choose to expose it. The match has to work across that asymmetry, and the architecture has to make the asymmetry explicit rather than pretending it does not exist.

A second difference: the match often has to be real-time. When a patient registers at the front desk, the system has 2-5 seconds to come back with an eligibility answer that the staff can act on. <!-- TODO: confirm at time of build; CAQH CORE Phase II operating rules specify response-time SLAs for real-time eligibility verification, with most major payers committing to 20-second worst-case response times for the X12 271 response. The front-desk-experience target of 2-5 seconds is tighter than the X12 SLA, and is achieved through caching, parallel calls, and degraded-but-useful responses. --> That eliminates a lot of the techniques you can use in batch. No expensive ML inference. No multi-step reasoning loops. No human review in the critical path. The real-time path has to be fast and decisive, with the harder cases routed to an asynchronous review queue rather than blocking the registration flow.

A third difference: the data flows are bidirectional and event-driven in ways that an internal patient matcher is not. Eligibility data changes constantly. A patient enrolls in a new plan on the first of the month. A subscriber adds a dependent mid-year after a qualifying event. A patient's COBRA coverage starts because they were laid off last week. A patient ages out of their parents' plan on their 26th birthday. A patient transitions from Medicaid to Medicare. A self-funded employer changes their plan administrator. A payer makes a mid-year benefit change. Each of these events changes the eligibility answer for some set of patients, and the matcher has to either re-evaluate when the events happen or accept that the cached eligibility data goes stale fast.

A fourth difference: the failure modes have direct financial consequences. A wrong "patient is eligible" answer leads to a service delivered without coverage, a claim denial, and either a write-off or a patient bill that may be unexpected. A wrong "patient is not eligible" answer leads to either a service delayed or denied (when the patient actually has coverage) or a self-pay charge that ought to have been billed to insurance. Both directions of error are bad in different ways, and the architecture has to manage the tradeoff explicitly rather than optimizing only for one side.

### What an Eligibility Match Actually Resolves

The match is not a single yes/no. It resolves a structured question: *for this patient, on this date of service, with this procedure or service, with this payer, is there active coverage; and if so, what are the patient's financial responsibilities?* The answer has multiple components:

**Identity match.** Is the patient in our records the same person as the member in the payer's records? This is the part most directly analogous to recipes 5.1 and 5.2: name, DOB, member ID, subscriber relationship, address. The match has to be confident enough that the rest of the response is interpretable as being about *this patient*.

**Coverage status.** Is coverage active on the date of service? This is the active-vs-terminated question. Termination dates, retroactive cancellations, and grace periods all live here. A patient whose coverage terminated yesterday but who is still in the payer's system as "active" until the next file refresh produces a wrong answer.

**Coverage scope.** Is this specific service covered? A primary care visit, a specialist consultation, a behavioral health session, a physical therapy visit, a high-cost imaging study, a prescription drug. The 271 response includes service-type codes that map to coverage. The match has to interpret those codes for the specific service the patient is being registered for, not just confirm that some kind of coverage exists.

**Financial responsibility.** Copay, coinsurance, deductible status, out-of-pocket maximum status. The patient (and the practice management system) needs to know what to collect at the point of service. This is where the 271 response gets dense and where payer-by-payer interpretation rules become important; not every payer populates the financial-responsibility fields the same way, and some payers populate them only for specific service types.

**Coordination of benefits (COB).** Does the patient have other coverage that should bill first? Primary, secondary, tertiary. A patient with both Medicare and a Medicare Advantage plan, a patient with employer coverage and a spousal plan, a patient with Medicaid and another commercial coverage, all have specific rules about which payer is primary on which date for which service. Getting COB wrong sends the claim to the wrong payer, gets it denied, and starts a re-submission cycle.

**Network status.** Is the rendering provider in-network for the patient's specific plan? Plan participation is finer-grained than payer participation; a provider may be in-network for the payer's commercial PPO product but out-of-network for the same payer's Medicare Advantage HMO product. Network match is a separate lookup against the payer's provider directory or against a directory the practice maintains, but operationally it is part of the eligibility-matching workflow because the financial-responsibility answer depends on it.

The recipe focuses on the identity and coverage-status pieces (where the entity-resolution techniques live), with hooks for the rest. Coverage scope, financial responsibility, COB, and network status are downstream of the identity match, and they consume payer-specific interpretation logic that is its own subject.

### The X12 270/271 Foundation

The HIPAA-mandated electronic standard for eligibility verification is the X12 270 (eligibility inquiry) and X12 271 (eligibility response) transaction set. <!-- TODO: confirm at time of build; the HIPAA Administrative Simplification regulations mandate the X12 transaction set; specific version (currently 5010 with industry transition discussion around future versions) is published in the regulation. --> Almost every electronic eligibility verification in US healthcare flows through this standard, either directly between payer and provider, or (more commonly) through a clearinghouse intermediary.

The 270 inquiry contains the patient demographics, the payer identifier, the requesting provider's NPI, the date of service, and (optionally) one or more service-type codes specifying what coverage is being asked about. The 271 response contains the matched member's coverage details: active/inactive flag, coverage start and end dates, plan name and identifier, copay and coinsurance information for the requested service types, deductible status, and any informational segments the payer chooses to include.

The 270 supports two matching modes that drive how identity matching works in this domain:

**Primary key match.** The 270 includes the member ID exactly as printed on the patient's ID card. The payer looks up the member by that ID and returns the corresponding record. When the patient produces the card and the staff scans or types the member ID correctly, this is the deterministic, fast path. It works most of the time.

**Search match.** The 270 omits the member ID and provides patient demographics (name, DOB, sometimes SSN, sometimes address). The payer attempts a probabilistic search against their member rolls and returns the best match (or none). This is the fallback when the patient does not have a card, when the card has the wrong member ID, when the member ID is unknown to the front desk, or when the practice management system is doing a sweep across the population to refresh eligibility data without making the patient produce their card. <!-- TODO: confirm at time of build; CAQH CORE operating rules specify which demographic fields a 270 must include for a search match to be supported, and not every payer supports search match for every product. -->

Both modes need an entity-resolution layer on the requesting side. Even with the primary-key match, you have to decide whether the payer's returned record is for the same person as the patient in your records (their name says "Maria Garcia," your record says "Mary Garcia," same DOB, same member ID; very likely the same person, but you confirm it). With search match, you have to evaluate the candidate the payer returns (or pick from candidates if the payer returns more than one) and decide whether to accept the match.

CAQH CORE (Council for Affordable Quality Healthcare's Committee on Operating Rules for Information Exchange) publishes the operating rules that constrain how 270/271 transactions work in practice. <!-- TODO: confirm at time of build; CAQH CORE Phase I, II, III, and IV operating rules each layer additional requirements on connectivity, response content, response time, and patient-financial-responsibility detail. --> The operating rules specify response-time SLAs (real-time response within 20 seconds, batch response within 24 hours), required fields in the 271 response, error-message standardization, and connectivity standards. They are the de facto baseline for production eligibility verification, and most major payers comply with the current phase. The matcher has to handle responses that conform to the operating rules, but also has to handle the long tail of smaller payers and self-funded plans that do not.

### What Makes the Match Hard

Six structural reasons the match is harder than internal patient matching:

**No shared identifier.** The patient's medical record number (MRN) means nothing to the payer. The payer's member ID is, usually, on the patient's card and in your registration record, but only if it was captured correctly, and member IDs change with plan changes (annual open enrollment, employer plan switches, mid-year qualifying events). The Social Security Number, where collected, is a candidate identifier but is not present in all records and has its own data-quality issues. Most matches end up using a combination of name, DOB, sex, and demographic-derived signals.

**Demographic capture is asymmetric.** Your registration system captures what your front desk types in. The payer's enrollment system captures what the employer or the member typed in at enrollment, possibly years ago, possibly with errors that have never been corrected. The two records may be for the same person but differ in how the name is normalized (full vs nickname, hyphenation, suffix), how the address is structured (current vs at-time-of-enrollment), how the date of birth is formatted, even whether the sex field is captured the same way (M/F vs more granular sex-and-gender fields, with payers historically much slower than providers to expand beyond binary capture). The matcher has to be tolerant of all of these without becoming so loose that it accepts wrong matches.

**Member ID changes over time.** Most payers issue a new member ID at every plan change, and some payers issue new member IDs at every annual renewal even if nothing else changed. A patient whose member ID was last captured eight months ago may have a different member ID today. The historical member ID is still in the matcher's data; the current member ID is what the payer expects. The matcher has to handle both, and the patient's ID card is the most authoritative source for the current member ID at the moment of registration. <!-- TODO: confirm at time of build; member-ID stability practice varies by payer and by product, with Medicaid and Medicare typically more stable than commercial, and self-funded employer plans varying widely. -->

**Subscriber-vs-dependent relationships.** A child on a parent's plan has a different member ID structure than the subscriber. Some payers issue distinct member IDs to dependents; some use the subscriber's member ID with a dependent suffix or a separate "person code." A spouse on the other spouse's plan might be the subscriber on a separate plan and the dependent on this one. The matcher has to know which member it is asking about, with the right relationship code, or the payer returns the wrong record (or no record).

**Eligibility data freshness varies wildly.** A real-time 270/271 transaction returns the payer's current eligibility state, subject to whatever lag the payer has between enrollment events and the eligibility-system update. A payer's overnight roster file may be one or two days behind real-time. Medicaid eligibility data can lag by weeks because state-level enrollment processing is slow. A patient who enrolled yesterday may not appear in any of these data sources today, but will tomorrow. The matcher has to know which source it is reading and how stale it is allowed to be for the use case at hand.

**Self-funded plans and TPAs add a layer.** A self-funded employer plan is administered by a third-party administrator (TPA), which may be a major insurer (running self-funded plans alongside their own products) or a specialized TPA. The provider sends the 270 to a payer ID that maps to the TPA, the TPA looks up the member in the employer's enrollment data, and the response comes back with the employer's plan rules layered on top of the TPA's data infrastructure. Errors and omissions can occur at multiple layers, and the matcher has to handle ambiguity that the standard 270/271 flow does not directly model.

### Where the Field Has Moved

A few practical updates worth knowing:

**FHIR-based eligibility APIs are emerging alongside X12.** The CMS Patient Access API, the CMS Provider Directory API, and the broader Da Vinci Project have produced FHIR-based alternatives to the X12 270/271 flow for some use cases. <!-- TODO: confirm at time of build; the Da Vinci Coverage Requirements Discovery (CRD), Documentation Templates and Rules (DTR), and Prior Authorization Support (PAS) implementation guides specify FHIR alternatives that may carry eligibility-verification semantics. CMS has issued rules requiring payers to support certain FHIR-based APIs for member access. --> The X12 standard is not going away (it is the regulatory baseline and the broad payer infrastructure is built around it), but FHIR-native eligibility verification is starting to appear, particularly for new use cases like payer-to-payer data exchange and patient-facing apps.

**Real-time-vs-batch is collapsing into "always real-time, sometimes async."** The historical model was that practices ran a batch eligibility verification each night or each morning before patient appointments, then did real-time verifications only for walk-ins. The current model is to run real-time at registration for everyone, with caching and asynchronous pre-warming for scheduled appointments to avoid the registration-time latency. CAQH CORE's response-time SLAs make real-time the default; the batch path is supplementary.

**Identity-resolution-as-a-service is becoming a payer offering.** Some payers and clearinghouses now expose APIs that take demographic data and return the matched member ID without going through a full 270/271. This is essentially a search-only eligibility match, packaged as an API call separate from the X12 flow. It is faster and more flexible than the X12 round-trip and is useful when the practice has the patient's demographics but not their card. Operating rules and BAA terms are still required.

**Cohort-stratified eligibility-match accuracy is being scrutinized.** The same equity concerns that show up in patient matching show up in eligibility matching: cohorts with non-dominant-culture naming conventions, cohorts with frequent address changes, cohorts with unstable demographics due to housing or employment instability, all match worse on average than the dominant cohort. The downstream consequences (delayed care, denied care, charity-care eligibility errors) are concrete equity issues. Cohort-stratified accuracy monitoring is becoming an expected operational metric rather than a research curiosity. <!-- TODO: verify; ONC, Pew, and equity-focused research literature have published on disparate impact of patient-matching errors, and the eligibility-matching subset of that literature is growing. -->

**No Surprises Act and price transparency add downstream pressure.** The No Surprises Act (effective 2022) requires good-faith estimates of patient costs in advance of service for self-pay patients and certain insured patients, and it constrains balance billing for out-of-network situations. Both of these depend on accurate eligibility and coverage data being available to the practice before the service. <!-- TODO: confirm at time of build; the NSA implementing rules and enforcement guidance continue to evolve. --> Price transparency rules require payers to expose pricing data to members and providers, again depending on accurate eligibility identification of the member. The eligibility-match infrastructure is now load-bearing for compliance with these regulations, not just for revenue cycle.

**Privacy-preserving eligibility verification is a research topic.** For some cross-organizational eligibility flows (a community service organization wanting to verify a patient's coverage status to determine sliding-scale fees, for example), the standard 270/271 path requires authorization that may not be in place. Bloom-filter-based and hash-based eligibility-verification techniques are starting to appear, similar to the privacy-preserving record linkage in recipe 5.8. Production deployments are still uncommon. <!-- TODO: confirm at time of build; the academic literature on privacy-preserving record linkage has subsections on eligibility-specific use cases. -->

---

## General Architecture Pattern

The pipeline has six logical stages: ingest the eligibility-verification trigger (real-time at registration, scheduled pre-warm, batch reconciliation), normalize the patient demographics on the requesting side, route the inquiry to the right payer, evaluate the response and resolve identity, persist the matched eligibility state with provenance, and react to downstream events that invalidate cached eligibility.

```
┌────────────── INGEST / TRIGGER ───────────────────┐
│                                                    │
│  [Trigger sources]                                 │
│   - Real-time registration event                  │
│   - Scheduled pre-warm (24h before appointment)   │
│   - Batch reconciliation (monthly payer roster)   │
│   - Refresh on coverage-change event              │
│   - Charity-care application screening            │
│           │                                        │
│           ▼                                        │
│  [Inquiry record:                                  │
│   patient_id, payer_id, service_date,             │
│   service_type_codes, requesting_provider_npi,    │
│   priority (real-time / async),                    │
│   trigger_reason]                                  │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── NORMALIZE PATIENT SIDE ─────────────┐
│                                                    │
│  [Pull patient demographics from MPI and the       │
│   active registration record:                      │
│   - Legal name, preferred name, prior names       │
│   - Date of birth                                 │
│   - Sex / gender (where captured)                 │
│   - Standardized address (recipe 5.3)             │
│   - SSN (where collected, with care)              │
│   - Last-known member ID (with stamp date)        │
│   - Subscriber relationship + subscriber ID       │
│     where dependent]                               │
│           │                                        │
│           ▼                                        │
│  [Apply payer-specific normalization rules:        │
│   - Payer X expects last name without suffix      │
│   - Payer Y expects DOB in YYYY-MM-DD             │
│   - Payer Z expects member ID with no dashes      │
│   - Payer W requires subscriber person-code]      │
│           │                                        │
│           ▼                                        │
│  [Build the X12 270 (or FHIR Coverage             │
│   inquiry) for this payer, this patient,          │
│   this service date]                              │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── ROUTE / DELIVER ────────────────────┐
│                                                    │
│  [Connectivity model selection:                    │
│   - Direct connection to large-volume payers     │
│   - Clearinghouse for the long tail              │
│   - Payer-specific portal scrape (deprecated      │
│     fallback for payers without electronic       │
│     standard support)]                            │
│           │                                        │
│           ▼                                        │
│  [Submit 270 / FHIR inquiry through the           │
│   selected channel with retry, timeout,           │
│   idempotency on (patient_id, payer_id,           │
│   service_date, inquiry_hash)]                    │
│           │                                        │
│           ▼                                        │
│  [Receive 271 / FHIR Coverage response]           │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── EVALUATE / RESOLVE IDENTITY ────────┐
│                                                    │
│  [271 response]                                    │
│           │                                        │
│           ▼                                        │
│  [Branch by response type:                         │
│   - PRIMARY_KEY_MATCHED (member ID + DOB         │
│     match): high-confidence match, proceed       │
│   - SEARCH_MATCH_RETURNED (one candidate):       │
│     score against patient record                  │
│   - SEARCH_MATCH_MULTIPLE (>1 candidate):        │
│     score each, pick best, threshold check       │
│   - NOT_FOUND: no member matched                 │
│   - REJECTED: protocol-level error               │
│   - PARTIAL: response received but missing       │
│     required segments]                             │
│           │                                        │
│           ▼                                        │
│  [Score the candidate(s) using the same            │
│   probabilistic-record-linkage core as 5.1:        │
│   - First name (Jaro-Winkler)                    │
│   - Last name (with maiden-name handling)        │
│   - DOB (exact, year-month, year-only)           │
│   - Sex                                           │
│   - Standardized address                         │
│   - SSN (where present on both sides)            │
│   - Member ID (current + historical)             │
│   - Subscriber relationship consistency]          │
│           │                                        │
│           ▼                                        │
│  [Apply confidence thresholds:                     │
│   - >= AUTO_ACCEPT_THRESHOLD: confirm match      │
│   - <= AUTO_REJECT_THRESHOLD: declare no match   │
│   - in between: route to human review]           │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── PERSIST + PROPAGATE ────────────────┐
│                                                    │
│  [Match outcome record:                            │
│   - patient_id, payer_id, service_date          │
│   - matched_member_id (if any)                  │
│   - match_confidence                             │
│   - match_method (primary_key / search /         │
│     reviewed)                                    │
│   - 271 raw payload (audit)                      │
│   - parsed coverage state                        │
│   - parsed financial responsibility              │
│   - inquiry_provenance,                          │
│     normalized_inquiry_payload]                  │
│           │                                        │
│           ▼                                        │
│  [Persist to eligibility-match store keyed on    │
│   (patient_id, payer_id, service_date)]          │
│           │                                        │
│           ▼                                        │
│  [Emit eligibility_resolved event]               │
│           │                                        │
│           ▼                                        │
│  [Downstream consumers:                            │
│   - Practice management (front-desk display)     │
│   - Revenue cycle (claim coverage on file)       │
│   - Charity-care workflow                        │
│   - Care management (high-risk patient outreach) │
│   - Patient portal (member-facing benefits view)]│
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── FRESHNESS / DRIFT ──────────────────┐
│                                                    │
│  [Cache eligibility responses with TTL keyed       │
│   on (patient_id, payer_id, service_date).        │
│   Service-date-future TTL is short                │
│   (hours to a day); service-date-past TTL is      │
│   essentially infinite (the answer is settled)]   │
│           │                                        │
│           ▼                                        │
│  [Subscribe to coverage-change signals:            │
│   - Monthly payer roster delta                   │
│   - 277 / 277CA claim status responses           │
│     indicating eligibility issue                 │
│   - 834 enrollment file (where received)         │
│   - Patient-side events (recipe 5.1 merge,        │
│     recipe 5.3 address change)]                   │
│           │                                        │
│           ▼                                        │
│  [Invalidate cached eligibility for affected      │
│   (patient_id, payer_id, future-service-date)     │
│   entries; emit eligibility_invalidated event]    │
│           │                                        │
│           ▼                                        │
│  [Re-run the inquiry asynchronously and update    │
│   the store; emit eligibility_resolved event      │
│   with the new state]                             │
│                                                    │
└────────────────────────────────────────────────────┘
```

**Trigger sources are heterogeneous.** Real-time registration is the latency-critical path. Scheduled pre-warm is the bulk of the volume (every appointment scheduled for tomorrow gets an eligibility verification today). Batch reconciliation against payer rosters is the cleanup pass. Charity-care screening is a separate, lower-volume but harder-match path because the question is "does this person have coverage anywhere," not "does this person have coverage at this specific payer." The architecture handles all four trigger types through the same downstream pipeline, with the trigger metadata determining the priority and the response-time budget.

**Patient-side normalization is payer-specific.** Each payer has subtly different expectations for how the demographics should be formatted in the 270. Some normalize for you, some don't. Some are strict about field length, some are loose. Some require subscriber person codes for dependent inquiries, some derive them. The normalization layer holds payer-specific rules in a configuration table (not in code), so adjustments don't require deploys, and the rules can be governed and reviewed.

**Connectivity is a hybrid.** Most providers use a clearinghouse for the long tail of payers (hundreds of small payers, self-funded TPAs, regional plans), with direct connections to the highest-volume two or three payers for cost and latency reasons. The architecture treats connectivity as a routing layer above the normalize-and-evaluate layer, so adding a new direct connection or switching clearinghouses does not change the rest of the pipeline.

**Identity resolution lives on the response side, not the inquiry side.** The 270 inquiry contains what the requester thinks is the member's identifying information. The 271 response contains what the payer actually has. The match decision is made on the response: did the payer find the right person, and is the response confident enough to use? This is an entity-resolution decision that is conceptually identical to recipe 5.1's matcher but with a different data shape and different confidence inputs.

**Persistence is keyed on the inquiry, not the response.** Two patients registered on the same day for the same service date with overlapping demographics could produce the same payer-side member; the system keys on the requesting (patient_id, payer_id, service_date) so the eligibility outcome is associated with the patient who triggered the inquiry, not with the payer-side member ID (which may be shared across multiple patient records in pathological cases). The matched_member_id is a value on the record, not a key.

**Freshness has two regimes.** For service dates in the past, the answer is settled and can be cached forever (modulo retroactive cancellations and corrections, which are rare and detected through the freshness pipeline). For service dates in the future, the answer can change, and the cache TTL is short. A typical policy: service-date-past TTL = 1 year (long enough for any retroactive correction to surface, short enough that very-old data eventually re-verifies); service-date-future TTL = 24 hours (balancing freshness against volume).

**Cohort-stratified accuracy monitoring is required here too.** Eligibility-match accuracy is not uniform across patient cohorts. Payers' member rolls have systematic data-quality patterns that disadvantage certain cohorts (Hispanic surname components handled inconsistently, Medicaid populations with higher address change rates, patients with name changes that did not propagate from one system to the other). The downstream consequences (charity-care eligibility errors, claim denials, delayed care) are concrete equity issues. Per-cohort match success rate, per-cohort search-match-vs-primary-key-match distribution, and per-cohort review-queue rate are all metrics worth tracking with disparity thresholds.

<!-- TODO (TechWriter): Expert review A2 (HIGH). Specify the operational thresholds, per-axis aggregation, and disparity-metric definitions for cohort-stratified accuracy monitoring. Use the institutional cohort registry as the source of truth (no ad-hoc enumeration in code). Metrics: per-cohort eligibility-match success rate (percent of inquiries returning AUTO_ACCEPT) weekly; per-cohort review-queue rate (percent routed to human review) weekly; per-cohort claim-denial-for-eligibility rate (downstream metric tying matcher quality to revenue impact) monthly. Disparity calculation: absolute difference between best-rate and worst-rate cohort per metric per cycle. Suggested thresholds: match-success disparity > 0.05 = MEDIUM alarm; review-queue disparity > 0.05 = MEDIUM; downstream denial disparity > 0.03 = HIGH. Alarms route to revenue-cycle and data-quality teams with 5-business-day SLA; remediation (per-cohort threshold tuning, payer-specific normalization rules, registration-staff training on data capture for affected cohorts) documented in cohort-disparity ledger and reviewed quarterly. Reference 5.1 Finding A2, 5.2 Finding A2, 5.3 Finding A2 as chapter pattern. -->

<!-- TODO (TechWriter): Expert review S1 (HIGH). Specify the identity-boundary policy for the inquiry-submission Lambda, the response-evaluation Lambda, the persist_eligibility_match function, and the eligibility-lookup read endpoint. For inquiry submission: caller_context.invocation_source enum (registration_event, scheduled_pre_warm, batch_reconciliation, charity_care_screening, refresh_on_invalidation) with per-source caller-role validation; rate limits per invocation source so a runaway batch job cannot consume the registration-flow capacity. For response evaluation: signature verification on the 271 payload from each clearinghouse / direct-connection partner, with replay-rejection on (control_number, transaction_set_id) to prevent stored-271 replay attacks. For persist_eligibility_match: validate the matched_member_id against the inquiry payload (the response must be for the same payer the inquiry targeted) and reject mismatches with logged metric and DLQ routing. For the eligibility-lookup read endpoint: privacy-suppression-on-read for patients with privacy flags, audit logging on every read, and a separate access-controlled path for displaying the raw 271 audit payload (clinical and revenue-cycle staff need the parsed coverage view; only the payer-relations and audit teams need the raw 271). Reference chapter pattern from 5.1, 5.2, 5.3 Finding S1. -->

<!-- TODO (TechWriter): Expert review A6 (MEDIUM). Specify the cross-recipe orchestration contract for eligibility-related events. The events conform to a chapter-wide schema (source, detail_type, detail.patient_id, detail.event_id, detail.previous_state, detail.new_state, detail.detected_at). Downstream consumers in 5.1 (patient matcher, when an eligibility match surfaces a previously unknown duplicate-patient signal), 5.5 (cross-facility HIE, when eligibility data from one facility's payer affects record reconciliation), 5.6 (claims-to-clinical linkage, where eligibility state at time of service constrains claim-to-encounter joining), plus the revenue-cycle, charity-care, care-management, and patient-portal pipelines, subscribe to specific detail_type values and acknowledge processing via a CloudWatch metric ({consumer}.events_processed). Reference chapter pattern from 5.1, 5.2, 5.3. -->

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter05.04-architecture). The Python example is linked from there.

## The Honest Take

Eligibility matching is the recipe in this chapter that has the most direct line to dollars. Get it right and your claim denial rate drops, your charity-care cycle time drops, your front-desk staff handle more patients per hour without the eligibility-detective work that breaks their rhythm. Get it wrong and every line of that runs the other way. Most healthcare CFOs can quantify the cost of "patient ineligible at time of service" claim denials at their organization down to the dollar; they often cannot quantify the upstream contribution of a poor eligibility-matching infrastructure to that denial rate, but they can tell you very clearly what the denials cost them.

The trap most specific to eligibility matching is treating it as "we already have this, the clearinghouse handles it." Most healthcare organizations do have an eligibility-verification workflow, and most of those workflows do go through a clearinghouse, and most of those clearinghouses do submit X12 270/271 transactions correctly. The piece that is usually missing is the entity-resolution layer on the response side: the scoring of search-match candidates, the threshold-and-review-queue discipline, the cohort-stratified accuracy monitoring, the cache invalidation pipeline. Without those, the eligibility workflow is making lots of inquiries and getting lots of responses, but it is making decisions on those responses without explicit confidence handling, and the decisions it gets wrong are the ones that produce the downstream denials and the equity disparities. Treat the response-side entity resolution as the part of the architecture that needs the most attention; the connectivity layer is largely a solved problem.

A second trap, related: under-investing in the registration-flow latency budget. A real-time eligibility lookup that takes 6 seconds at the front desk has cascading consequences. The registration clerk waits, the patient waits, the next patient backs up in the lobby, the rhythm of the morning breaks, and the staff under pressure starts taking shortcuts (selecting the closest-matching record they can find without confirming the eligibility, skipping the eligibility check entirely "we'll bill them and figure it out later," or using the cached eligibility from the patient's last visit even when the cache is stale). The cache-and-pre-warm architecture exists specifically to keep the registration-flow latency in the tens-of-milliseconds range so the staff is not forced into shortcuts. Build the cache layer first, before optimizing the deeper parts of the matcher; the latency win matters more than the marginal accuracy win in most operational contexts.

The third trap, specific to the equity dimension: under-investing in cohort-stratified accuracy monitoring. The matcher's overall accuracy can look great while certain cohorts (Hispanic surnames, Medicaid populations with frequent coverage churn, patients with name changes that did not propagate from one system to the other) match systematically worse. The downstream consequences of those disparities are concrete equity issues: delayed care for the affected patients, charity-care eligibility errors, claim denials that cascade into patient bills the patients can least afford. Cohort-stratified monitoring catches the disparities; per-cohort threshold tuning, payer-specific normalization rules, and registration-staff training on common cohort-specific patterns close them. Equity in eligibility match is equity in access; the work is mostly operational discipline rather than algorithmic improvement, and it is non-negotiable.

The thing that surprises people coming from a generic data-integration background is how much value the parsed coverage detail produces beyond just the identity match. The 271 response includes the plan name, the effective and termination dates, copays and coinsurance for specific service types, deductible status, out-of-pocket-max status, COB indicators, network indicators. All of that is structured data that downstream systems consume. Revenue cycle uses the coverage detail to set up the claim correctly. The patient portal uses it to display "your benefits at a glance." Care management uses it to identify high-deductible patients who might delay needed care for cost reasons. Patient financial counseling uses it to set up payment plans before the service rather than as a collections issue after. The eligibility-match store is not just an identity layer; it is the substrate for a half-dozen downstream workflows.

The thing about cache freshness: the policy decision is consequential. Too short and you re-inquire constantly, paying clearinghouse fees and slowing everything down. Too long and you serve stale answers that produce the very problems you built the cache to avoid. The 24-hour TTL for future-service-date entries is a reasonable baseline, but the right answer varies by payer and by population. Medicaid populations with high coverage churn need shorter TTLs than commercial populations with stable annual enrollment. Some payers' eligibility data is updated near-real-time and supports shorter TTLs without producing more re-inquiries; some payers' data is updated weekly and tolerates longer TTLs. The right approach is per-payer TTL configuration, calibrated against the per-payer staleness rate observed in the cache-vs-fresh comparison.

The thing about CAQH CORE compliance: it is the floor, not the ceiling. The operating rules specify what payers must do (response-time SLAs, required fields, error-message standardization), but they do not specify everything the provider would benefit from. Some payers go beyond CORE compliance with richer responses (more service-type detail, more network-status detail, more financial-responsibility breakdown). The matcher should consume the richer responses where available and degrade gracefully where not. Treating every payer as if they comply only with the floor leaves value on the table.

The thing I would do differently the second time: invest more heavily in the patient-portal eligibility-self-service flow. The portal can show the patient their on-file insurance, ask them to confirm or update, accept an updated card image, run OCR (recipe 1.1) against the card to extract the new member ID, and trigger a fresh 270/271 to verify. The patient is the authoritative source on their coverage status; getting them into the loop reduces the registration-time eligibility surprises and shifts the data-update work to a moment when the patient is at their computer rather than at the front desk in a hurry. Most institutions either do not have the portal flow at all or have it but do not surface it prominently. The right product design is to surface it on every portal session ("Is your insurance still ABC Health Plan, member ID U1234567890? Yes / Update"), capture the confirmation with a timestamp, and use the timestamp as a freshness signal. Patients largely will confirm if asked simply; the data quality improvement compounds over time.

The thing that has aged surprisingly well is the underlying X12 270/271 standard. It is a 1990s-era EDI standard with all the warts you would expect (segment-and-element formatting that is dense and unforgiving, hierarchy levels, coding lists), but it works, the infrastructure is mature, and the operational ecosystem (clearinghouses, BAAs, trading-partner agreements, CAQH CORE operating rules) is functional. FHIR-based eligibility is a real and welcome evolution, but the X12 baseline is going to be load-bearing in US healthcare for at least the next decade. Build the boring core (X12 270/271 through a clearinghouse with proper response-side entity resolution) first; layer FHIR-based connectivity for payers that offer it as a parallel path rather than a replacement.

Last point, because it is specific to the regulatory context: the No Surprises Act, the price transparency rules, and the broader push toward patient-cost predictability all depend on accurate eligibility-and-coverage data being available in advance of service. <!-- TODO: confirm at time of build; the NSA implementing rules and price-transparency rules continue to evolve. --> The eligibility-match infrastructure is now load-bearing for compliance with these regulations, not just for revenue cycle. Treat the architecture as compliance-relevant, with the audit, retention, and access-control posture that implies. The institutions that win at the price-transparency-era patient experience will be the ones with the most accurate, freshest, most usable eligibility data available across their workflows.

---

## Related Recipes

- **Recipe 5.1 (Internal Duplicate Patient Detection):** The probabilistic-record-linkage scorer used to evaluate 271 search-match candidates is the same scorer used in 5.1; build it once, use it across recipes.
- **Recipe 5.2 (Provider NPI Matching):** The requesting provider's NPI on every 270 must be valid; the NPI-matching layer from 5.2 supplies the canonical NPI value.
- **Recipe 5.3 (Address Standardization and Household Linkage):** Standardized addresses are a comparator in the eligibility-match scorer; the address pipeline from 5.3 directly feeds this matcher's normalization step.
- **Recipe 5.5 (Cross-Facility Patient Matching for HIE):** Eligibility data from one facility's payer is useful context for cross-facility matching at HIE boundaries; the eligibility-match store supplies that context.
- **Recipe 5.6 (Claims-to-Clinical Data Linkage):** Eligibility state at time of service constrains how a claim joins to a clinical encounter; the eligibility-match store is part of the claims-to-clinical reconciliation foundation.
- **Recipe 5.7 (Longitudinal Patient Matching Across Name Changes):** Member-ID continuity across name changes is one of the cases where the eligibility matcher has to handle prior-name lookups; the longitudinal matching layer from 5.7 supplies the prior-name signal.
- **Recipe 5.8 (Privacy-Preserving Record Linkage):** Cross-organization eligibility sharing without revealing full coverage detail uses the same cryptographic foundations.
- **Recipe 1.1 (Insurance Card Scanning):** The patient-portal coverage self-service flow consumes OCR'd card images to extract member IDs that feed this matcher.
- **Recipe 1.8 (EOB Processing):** Explanation of Benefits documents are the downstream artifact of claims that depended on eligibility matches; tying EOB processing back to the originating eligibility match closes the revenue-cycle loop.
- **Recipe 2.4 (Prior Authorization Letter Generation):** Prior-auth workflows depend on accurate eligibility identification of the member.
- **Recipe 3.1 (Duplicate Claim Detection):** Eligibility match outcomes feed claims-side anomaly detection (a claim submitted under a member ID the eligibility matcher rejected is a strong duplicate-or-fraud signal).
- **Recipe 7.x (Predictive Analytics):** Coverage churn and benefit-design features derived from the eligibility-match store contribute to risk-scoring models.

---

## Tags

`entity-resolution` · `record-linkage` · `eligibility-verification` · `x12` · `270-271` · `caqh-core` · `clearinghouse` · `fhir` · `coverage` · `revenue-cycle` · `charity-care` · `dynamodb` · `elasticache` · `lambda` · `step-functions` · `event-driven` · `medium` · `production` · `hipaa` · `no-surprises-act`

---

*← [Recipe 5.3: Address Standardization and Household Linkage](chapter05.03-address-standardization-household-linkage) · Chapter 5 · [Next: Recipe 5.5 - Cross-Facility Patient Matching for HIE →](chapter05.05-cross-facility-patient-matching)*
