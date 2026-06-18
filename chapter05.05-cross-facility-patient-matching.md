# Recipe 5.5: Cross-Facility Patient Matching (HIE) ⭐⭐⭐

**Complexity:** Medium · **Phase:** Production · **Estimated Cost:** ~$0.0001-0.001 per query at HIE scale, dominated by infrastructure rather than per-transaction fees (depends on participant volume, query patterns, and the consent-and-audit overhead the framework imposes)

---

## The Problem

A patient gets in a car accident on a Tuesday afternoon. She is unconscious when the ambulance arrives, has no ID on her, and is brought to the nearest emergency department. The trauma team needs to know, very fast, whether she is on blood thinners. Whether she has an allergy to anything they are about to give her. Whether she has a cardiac history that would change how they manage her. Whether she has been seen for similar injuries before in a way that suggests intimate-partner violence. Whether she is pregnant. Whether she has an advance directive on file somewhere.

She has, in fact, been seen at four different healthcare organizations in the last decade: her primary care office (a small independent practice that uses a regional EHR), the academic medical center across the city (where she had her gallbladder out five years ago), the urgent care chain near her job (visited twice last year for sinus infections), and the women's health clinic where her OB/GYN practices (which is part of a different health system). All four organizations have records that, between them, would answer every one of those trauma-team questions in seconds. None of them are connected directly. The trauma team has, today, no way to query all four systems with "who is this patient and what do you know about her" and get back a useful answer in the registration window.

This is what cross-facility patient matching is for. The clinical care use case is the dramatic one, the one that makes the case for funding the infrastructure, but it is far from the only use case. Care coordination across primary care and specialty care for chronic conditions, transitions of care from hospital to skilled nursing facility to home health, public health reporting that needs to deduplicate across submitting organizations, quality measurement that needs to know whether a patient seen at organization A had her required follow-up at organization B, value-based care contracts that pay or penalize based on total cost of care for an attributed patient population that gets care from multiple sources, all of these require the ability to say "the patient seen at organization A is the same person as the patient seen at organization B."

The gap between "should be possible" and "is possible" here is decades wide. Health information exchanges (HIEs), regional and state and increasingly national, exist precisely to bridge this gap. They have been around for over twenty years in various forms. They have functioning patient-matching infrastructure. And yet the typical experience of a clinician in the United States, in the year you are reading this, is still that they do not have a complete view of their patient at the point of care.

Why is it hard? Several reasons that compound:

You are running an HIE that connects forty hospitals, two hundred ambulatory practices, twelve community health centers, and a handful of post-acute facilities in a state. Each of those organizations sends you patient records (admission and discharge notifications, continuity of care documents, FHIR resources) on their own schedule, in their own dialect, with their own demographic conventions. Maria Garcia at the academic medical center is "Maria E. Garcia, DOB 1972-03-14, address on Maple Street." At the urgent care chain she is "Maria Garcia-Lopez, DOB 1972-03-14, address on Maple Street." At the women's health clinic she is "M Garcia, DOB 1972-03-15 (their registration system requires every digit and the staff guessed when she did not have her ID), address last updated when she lived on Oak Street four years ago." At the primary care office she is "Maria Elena Garcia, DOB 1972-03-14, with her current Maple Street address and her old Oak Street address as a secondary." Without an external master patient index that ties these four records together, the trauma team querying you for "Maria Garcia, DOB 1972-03-14" gets back zero, one, two, or all four of these records depending on how confident your matcher is, and you have to be right about the merge in seconds.

You are running clinical IT at one of those forty hospitals, and you receive a Continuity of Care Document (CCD) from the urgent care chain via the HIE for one of your patients. The CCD is for "Maria Garcia-Lopez." Your patient is "Maria E. Garcia." Your EHR's automatic-match-on-incoming-document logic says it is a probable match, so it files the document into your patient's chart automatically. Two months later you discover that "Maria Garcia-Lopez" was a different person entirely (a different Maria, born the same year, same first name, different middle initial), and the urgent care record (which mentioned a positive pregnancy test) is now in your patient's chart, where it has been seen by a covering physician who believed it. The patient is, understandably, upset. The chief medical officer wants to know what happened. The compliance team wants to file a breach notification. The HIE wants to know whether this is a one-off or a systematic matcher problem on either your side or theirs.

You are coordinating care for an oncology patient who is on an active treatment plan at the academic medical center, gets her infusions there, but is being seen for a separate concern by her primary care physician at a different organization. The PCP needs the latest oncology notes; the oncology team needs the PCP's blood pressure trends and recent medication changes. The HIE has the data on both sides. The question is whether the HIE can confidently link the two patient records at query time so that "give me everything you have on this patient" returns the union, not the disjoint subset that each organization can already see locally.

You are running quality measurement for a state Medicaid program. You need to compute, for the attributed population, the percentage of diabetic patients who got an HbA1c test in the last twelve months. The data sources are claims (which see all the tests billed but not the results), the state's largest health system EHR (which has the results for patients seen there), and the regional reference lab (which has the results for tests that were billed by primary care offices using outside labs). You have to match patients across all three sources without double-counting, without missing patients who got their test at a system you do not have feed from, and without crediting the wrong test to the wrong patient.

You are a public health agency receiving immunization records from every provider in the state, plus pharmacies, plus mass vaccination sites during a pandemic. The records are submitted with the demographic data each provider had at the time, which varies in completeness and accuracy. Your immunization information system needs one record per child per vaccine event, properly attributed, even though the submitter may have only the kid's first name and a guessed birth year because the family did not have ID at the pop-up clinic.

You are TEFCA's national-network operator and you are wiring up the inter-network exchange of patient records between Qualified Health Information Networks (QHINs). The patient matching at this layer happens between organizations that may have never exchanged data with each other before, may have very different population demographics, may use different matching technologies internally, and have to produce a confident match decision through query-and-respond protocols that were designed before the volume and the stakes got this high. <!-- TODO: confirm at time of build; TEFCA's QHIN-to-QHIN exchange and the underlying patient-matching protocols continue to evolve. -->

This is the recipe. Cross-facility patient matching is the entity-resolution problem of "is the patient described in this query the same person as the patient on record at our organization, and if so, with what confidence and what data are we willing to release?" The answer requires entity-resolution techniques (which you saw in 5.1, 5.2, 5.3, and 5.4), but it adds three things on top: privacy-and-consent governance is not optional and it shapes the architecture, the match has to work against records you did not control the creation of and probably never will, and the cost of getting it wrong is borne by the patient in clinical-safety terms in addition to the administrative and financial terms from the earlier recipes.

It is in the medium-complexity tier because the matching core is the same probabilistic-and-deterministic stack from earlier recipes, but the surrounding cross-organizational coordination, the consent layers, the audit posture, and the trust frameworks add an order of magnitude of operational and governance complexity. National-scale matching across the entire TEFCA framework is in recipe 5.9 and is genuinely complex; the regional and HIE-scale matching covered here is the on-ramp.

Let's get into how you build it.

---

## The Technology: Cross-Organizational Entity Resolution Without a Shared Identifier

### Why This Is Different From Internal Matching

You have already seen the basic toolkit. Recipes 5.1 (internal duplicate detection), 5.2 (provider NPI matching), 5.3 (address standardization and household linkage), and 5.4 (insurance eligibility matching) all draw from the same core: deterministic matching for the easy cases, probabilistic scoring with Fellegi-Sunter weights for the medium cases, ML re-ranking where it earns its keep, and human review for the rest. That toolkit applies here. What changes is the surrounding context.

In recipe 5.1, both records are yours. You can normalize the data on both sides. You can re-run the matcher when the threshold changes. You can merge and unmerge with full audit. You can fix the registration UI to capture cleaner data going forward.

In recipe 5.5, the records on the other side belong to a different organization. You cannot clean their data. You cannot change how they collect it. You cannot see their full record (only the demographics and the explicitly-shared clinical data). You may not even know what their internal patient ID looks like. The matcher has to work across organizations that share a thin slice of demographics and (usually) nothing else.

A second difference: the consent layer is in the request path. In recipe 5.1, your patient consented to be in your records when they registered with your organization. In recipe 5.5, the question is whether they have consented (explicitly or by operation of law) to having their records exchanged with another organization for this specific purpose. The answer is encoded in a consent registry, and the matcher has to consult the registry before releasing any data. The architecture treats consent as a first-class input to the match-and-release decision, not as a checkbox on a downstream form.

A third difference: the trust model is multilateral. In recipe 5.4, you trusted the payer to have authoritative member data; the trust direction was clear. In recipe 5.5, two or more organizations are exchanging data peer-to-peer (or through an HIE intermediary), and each has to trust that the others are matching responsibly, not over-merging or under-merging in ways that produce unsafe data sharing. The trust framework is an explicit document (Data Use and Reciprocal Support Agreement, Common Agreement, HIE participation agreement) that constrains what each party may do with the data they receive.

A fourth difference: the failure modes have a clinical-safety dimension that the earlier recipes did not have at the same intensity. A wrong eligibility match (recipe 5.4) produces a billing error. A wrong cross-facility match produces, potentially, a misfiled clinical document, a missed allergy, a wrong-patient overlay in the receiving organization's chart, and harm to the patient. The matcher's tolerance for false positives is therefore lower than in any of the earlier recipes, and the architecture has to make the tolerance explicit and tunable.

### The Cross-Facility Match: What It Actually Resolves

Two distinct operations live under the umbrella of "cross-facility patient matching," and the architecture treats them differently:

**Query-time match.** A clinician at organization A queries the HIE (or directly queries organization B) for "patient X." The system has to identify, with high confidence, which of organization B's patient records (if any) is the same person, and return only those records. This is a synchronous, latency-sensitive operation; the clinician cannot wait. The match runs against the requesting organization's demographic submission and organization B's master patient index. The output is a match decision and (if matched and consent permits) the requested clinical data.

**Linkage-time match.** Records are submitted to a shared MPI (the HIE's, or an inter-organization EMPI) on a continuous or batch basis. Each submission is matched against the existing population to determine whether it is a new identity or an existing one. The output is a stable cross-organizational identifier that ties together the participating organizations' local patient IDs. This is the durable substrate for query-time matches and for any cross-organizational analytics.

The two operations share the underlying matcher but differ in their architecture. Query-time match is real-time and stateless (the match decision is for this query only; the result is not persisted as a permanent linkage). Linkage-time match is asynchronous and state-building (each match decision adds to or modifies the cross-organizational MPI). Both run in production simultaneously; the linkage-time pipeline maintains the substrate that the query-time pipeline reads.

The match output also has more components than in earlier recipes:

**Identity match.** Same probabilistic core as recipes 5.1 and 5.4, with the cross-organizational features. Demographics are the primary signal; cross-organizational identifiers (when present, like a previously-issued HIE patient identifier) are the strongest deterministic signal.

**Consent envelope.** Even when the identity match is high-confidence, the consent registry determines what data may be released. Some organizations operate under opt-in models (patients must explicitly consent to be in the HIE), some under opt-out (patients are in unless they have specifically opted out), some under a mixed model (treatment uses are opt-out, secondary uses are opt-in). The consent envelope constrains the released payload. <!-- TODO: confirm at time of build; the legal landscape for HIE consent varies by state and by data category, and the 21st Century Cures Act information-blocking rules layer additional obligations. -->

**Sensitivity filter.** Some categories of clinical data have additional sharing constraints beyond general HIPAA: substance-use disorder records under 42 CFR Part 2, behavioral health records in some states, HIV and STI status in some jurisdictions, genetic test results, reproductive health information in jurisdictions where it has become legally sensitive. <!-- TODO: confirm at time of build; the legal landscape on sensitive-category sharing is moving, particularly post-Dobbs reproductive-health-information sharing constraints. --> The match-and-release pipeline filters the released data by these categories, and the matcher's audit trail records what was filtered and why.

**Provenance and authority.** When two organizations both have a record for the same patient, which record is authoritative for what? The patient's allergies recorded yesterday at the academic medical center are probably more current than the allergies recorded three years ago at the urgent care chain. The cross-facility match output includes provenance metadata so the consuming organization (or the HIE's longitudinal-record assembler) can apply survivorship rules.

The recipe focuses on the identity-and-consent piece, with hooks for the rest. Sensitivity filtering is its own subject and is largely policy-driven rather than algorithmic; provenance and survivorship are best handled in a downstream record-assembler.

### The Standards Foundation: IHE PIX/PDQ and FHIR Patient $match

Two standards-based mechanisms underlie most production cross-facility patient matching:

**IHE PIX and PDQ.** Integrating the Healthcare Enterprise (IHE) is a standards organization that publishes profiles for healthcare interoperability. The Patient Identifier Cross-reference (PIX) profile defines how to query for "given this patient's local identifier in organization A, what is their local identifier in organization B." The Patient Demographics Query (PDQ) profile defines how to query for "given these demographic search criteria, return matching patient records." Both have HL7 v2-based variants (the original) and FHIR-based variants (PIXm and PDQm, with the m for "mobile" reflecting their RESTful design). <!-- TODO: confirm IHE profile names and current versions at time of build; IHE updates the profiles periodically. --> Most operational HIEs in the United States expose at least PDQ and PIX (or their FHIR equivalents) as the patient-discovery layer.

**FHIR Patient $match operation.** The FHIR specification defines a `$match` operation on the Patient resource that takes a search Patient resource as input and returns a Bundle of candidate Patient resources, each with a search score indicating match confidence. <!-- TODO: confirm at time of build; the FHIR Patient $match operation is defined at hl7.org/fhir/patient-operation-match.html and is a normative part of the spec. --> This is the modern, REST-friendly version of the patient-discovery query. It is what Carequality, CommonWell, and TEFCA QHINs predominantly use for their cross-organization patient-discovery flows. The matcher implementation behind `$match` is left to the responding organization (the standard says how to query, not how to match), so each organization's match quality may differ. The query-time architecture has to handle that variance.

The combination is layered: a query (PIX/PDQ or `$match`) goes from the requesting organization to the responding organization (or to an HIE intermediary that fans out to multiple responders), each responder's matcher evaluates the query against its local MPI, each responder returns a match-or-no-match (with confidence) and (subject to consent) the requested data. The requesting organization aggregates the responses, applies its own match-quality threshold, and presents the result to the clinician.

This is how the trauma-team scenario from the opening actually works in production: the ED registration system queries the HIE (or directly queries known nearby organizations), each responder's matcher evaluates the query against its local MPI and returns matched data, and the ED's longitudinal-record-assembler stitches the responses into a single view for the clinician. When it works, the clinician sees the union of records from all four of Maria Garcia's prior providers within a few seconds of registration. When the matchers disagree about whether the queries refer to the same person, the result is partial.

### What Makes the Cross-Facility Match Hard

Six structural reasons:

**No shared identifier across organizations.** Each organization issues its own MRN. The HIE may issue its own cross-organizational identifier, but it is opaque to the participating organizations and can only be resolved through the HIE. Older infrastructure relied heavily on Social Security Number as a quasi-identifier, but SSN is increasingly excluded from healthcare data flows for privacy reasons (and it has data-quality and entry-error issues even where it is collected). The match runs on demographic data plus whatever cross-references the HIE has previously established.

**Demographic data is asymmetric in different ways than in eligibility matching.** Two providers' registration systems capture demographic data with different conventions, different quality bars, different completeness expectations. The hospital's registration captures a comprehensive set with insurance verification; the urgent care's registration captures minimum-viable demographics under time pressure; the public health pop-up clinic captures whatever the family was willing to give them. The matcher has to be tolerant enough to handle these without becoming so loose that it accepts wrong matches.

**The probability-base-rate is much lower than in single-organization matching.** When you query an HIE for "Maria Garcia, DOB 1972-03-14," you are not asking "is this person already in our database" (the question for recipe 5.1, where the prior probability is "yes, with high probability, because she registered today"). You are asking "is this person in any of the participating organizations' databases" against a population of millions, where the prior probability that any specific other-organization record refers to the same person is small. The Fellegi-Sunter math handles this through the u-probabilities (random-match probabilities), but the practical implication is that the threshold has to be calibrated more conservatively, because the cost of false positives is higher relative to the population base rate.

**Names are not stable across organizations and time.** A patient who was seen at organization A under her maiden name and at organization B under her married name produces records that the matcher has to recognize as the same person without conflating them with a different patient who has the maiden name as her birth name. This is the cross-facility version of the longitudinal-name-change problem (recipe 5.7), and it is harder here because organization A may not know about the marriage at all.

**Privacy and consent are first-class inputs, not constraints.** A high-confidence identity match does not authorize data release. The consent registry has to be consulted, the sensitivity filter has to be applied, and the audit trail has to record what was queried, what was returned, what was filtered, and why. The query-and-release pipeline carries the consent metadata through every stage. Skip this and the architecture is unsafe at production scale, regardless of how well the matcher itself performs.

**Trust in the responder's match quality is bounded.** When organization B's matcher returns "match, confidence 0.96, here are the records," organization A has to decide whether to trust that confidence value. Organization B's confidence is calibrated against organization B's gold set, against organization B's population, with organization B's threshold. Organization A has its own population and its own risk tolerance. The aggregating side typically applies its own confidence threshold to the responder's score, treating the responder's match decision as one signal among several. This is increasingly being formalized in HIE policy as "minimum acceptable matcher quality" requirements rather than left to ad-hoc per-querier reinterpretation.

### Where the Field Has Moved

A few practical updates worth knowing:

**TEFCA went operational, slowly.** The Trusted Exchange Framework and Common Agreement is now in production, with multiple QHINs designated and inter-network exchange happening at increasing volume. <!-- TODO: confirm operational status and QHIN list at time of build; TEFCA QHIN designations and operational rollout continue to expand. --> The patient-matching standards within TEFCA are still maturing; recipe 5.9 covers the national-scale dimension. For regional and HIE-scale matching, TEFCA's emergence is changing the operational reality (organizations that previously connected only through their regional HIE now have a national reach) but is not changing the underlying matching techniques. The same probabilistic-and-deterministic core works.

**FHIR-native query is becoming the dominant pattern.** Newer HIE deployments and the TEFCA QHIN-to-QHIN exchange use FHIR Patient `$match` and FHIR R4 (or higher) data resources rather than the older HL7 v2 Continuity of Care Document and IHE XDS infrastructure. <!-- TODO: confirm at time of build; FHIR R5 has been published but R4 remains the broadly-deployed baseline. --> The transition is still in progress (most operational HIEs have hybrid v2-and-FHIR connectivity), and FHIR is rapidly becoming the assumed substrate for new development.

**Patient-mediated identity, not just provider-mediated.** The CMS Patient Access API and the broader push for patient-controlled health data are introducing a new identity-resolution path: the patient authenticates to a payer or to an aggregator, authorizes a connection to a third-party app, and the app pulls records on the patient's behalf. The patient's cryptographic identity (typically through OAuth or OIDC against a known identity provider) becomes a strong identifier that supplements demographic matching. <!-- TODO: confirm at time of build; the CMS Interoperability and Patient Access Final Rule and its successor regulations are evolving, and patient-mediated identity is increasingly relevant. --> This is most directly relevant for patient-facing apps but is starting to feed into provider-facing record location too.

**Cohort-stratified accuracy monitoring is required by regulation in some contexts.** ONC's certification criteria, TEFCA's QHIN requirements, and various state HIE rules increasingly include obligations around match-quality monitoring and disparate-impact analysis. <!-- TODO: confirm at time of build; the regulatory landscape is moving toward more explicit equity-monitoring requirements. --> This is the same equity concern as in recipes 5.1 and 5.4, applied to the cross-organizational layer where the disparities can be larger because the matching is harder.

**Privacy-preserving record linkage is moving from research to production.** Bloom-filter-based and hash-based matching protocols (recipe 5.8 covers the techniques in detail) are increasingly available as alternatives to direct demographic exchange, particularly for analytics use cases where the full record does not need to be revealed. For clinical-care use cases the demographic exchange remains dominant, because the privacy-preserving methods have lower match accuracy and are harder to audit. <!-- TODO: confirm at time of build; deployment of privacy-preserving linkage in operational HIEs has increased but is still uncommon for clinical-care queries. -->

**Match-quality benchmarking and auditing standards are emerging.** Industry initiatives (the Sequoia Project Patient Matching Framework, ONC patient-matching pilot programs, AHIMA's MPI maturity model) are producing benchmarking standards, audit checklists, and recommended practices that did not exist a decade ago. <!-- TODO: confirm at time of build; the patient-matching framework documents are being updated. --> The practical effect is that "what does a good cross-facility matcher look like" is becoming a question with documented industry answers rather than a per-organization improvisation.

---

## General Architecture Pattern

The pipeline has six logical stages: ingest the cross-facility query (or the linkage submission), normalize the demographic search criteria, evaluate against the local MPI (or, for query aggregators, fan out to participating organizations and aggregate the responses), apply the consent and sensitivity filters, persist the match decision with provenance, and react to events that invalidate prior matches (consent revocation, organization onboarding or offboarding, MPI updates).

```text
┌────────────── INGEST ─────────────────────────────┐
│                                                    │
│  [Trigger sources]                                 │
│   - Inbound query (PIX/PDQ, FHIR $match)          │
│     from another organization or HIE             │
│   - Inbound linkage submission (CCD, FHIR Bundle, │
│     ADT message) for ingestion into shared MPI   │
│   - Outbound query from local clinician           │
│     (registration ED workflow, transition-of-care │
│     workflow, public-health reporting)            │
│   - Periodic MPI reconciliation across            │
│     participating organizations                   │
│           │                                        │
│           ▼                                        │
│  [Query / submission record:                       │
│   query_id, requesting_org, target_orgs,          │
│   purpose_of_use, search_demographics,            │
│   requested_data_categories, response_window]     │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── NORMALIZE ──────────────────────────┐
│                                                    │
│  [Apply cross-organizational demographic           │
│   normalization:                                   │
│   - Names: case, suffix, hyphenation,             │
│     transliteration                               │
│   - DOB: format, partial-date handling            │
│   - Sex / gender (where captured)                 │
│   - Standardized address (recipe 5.3)             │
│   - Phone: E.164 with extension stripping         │
│   - Cross-organizational identifier (if present   │
│     from prior match)]                             │
│           │                                        │
│           ▼                                        │
│  [Build the canonical search payload]             │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── EVALUATE / RESOLVE IDENTITY ────────┐
│                                                    │
│  [For local MPI evaluation:]                       │
│   Block on (last-name-soundex, year-of-birth)     │
│   plus secondary blocks for low-recall coverage   │
│   (last-name-metaphone, ZIP3-and-DOB,             │
│   first-name-and-DOB-day-month)                   │
│           │                                        │
│           ▼                                        │
│  [Score each candidate using the same             │
│   probabilistic-record-linkage core as 5.1:        │
│   - First name (Jaro-Winkler with                │
│     nickname-aware comparison)                    │
│   - Last name (with maiden-name handling and      │
│     hyphenation tolerance)                        │
│   - DOB (exact, year-month, year-only)           │
│   - Sex                                           │
│   - Standardized address                         │
│   - SSN (where present, with care)               │
│   - Phone                                         │
│   - Prior cross-org identifier (strong signal)]   │
│           │                                        │
│           ▼                                        │
│  [Apply confidence thresholds calibrated          │
│   against the cross-organizational gold set:      │
│   - >= AUTO_ACCEPT_HIGH: high-confidence match,  │
│     proceed to release                           │
│   - >= AUTO_ACCEPT_MED: probable match,          │
│     proceed with downgraded data scope            │
│   - <= AUTO_REJECT: no match, return null         │
│   - in between: route to deferred-review queue   │
│     (this is not blocking; the original          │
│     query gets a "no match found" response       │
│     and the candidate is reviewed                │
│     asynchronously to inform future matches)]    │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── CONSENT + SENSITIVITY FILTER ───────┐
│                                                    │
│  [Consult consent registry for the matched        │
│   patient:                                         │
│   - Is exchange permitted at all?                 │
│   - Is exchange permitted for this purpose-       │
│     of-use? (treatment, payment, operations,      │
│     research, public-health)                      │
│   - Is exchange permitted with this requesting   │
│     organization?                                  │
│   - Is exchange permitted for this data           │
│     category?                                      │
│   - What is the consent valid-through date?]      │
│           │                                        │
│           ▼                                        │
│  [Apply sensitivity filter to the eligible        │
│   data set:                                        │
│   - 42 CFR Part 2 (substance use disorder)        │
│   - State-specific behavioral health rules        │
│   - HIV / STI status restrictions where          │
│     applicable                                    │
│   - Genetic test results                         │
│   - Reproductive health information where         │
│     legally restricted                            │
│   - Patient-flagged sensitive categories]         │
│           │                                        │
│           ▼                                        │
│  [Construct the response payload:                  │
│   - Match decision and confidence                │
│   - Released data subset                         │
│   - List of filtered / withheld data categories  │
│     (with reason codes; the requester knows      │
│     something was withheld but not specifically   │
│     what or why)]                                  │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── PERSIST + AUDIT ────────────────────┐
│                                                    │
│  [Audit record:                                    │
│   - query_id, requesting_org, target_org         │
│   - matched_local_patient_id (if any)            │
│   - match_confidence, match_method               │
│   - consent_check_result                          │
│   - released_data_summary                         │
│   - filtered_data_categories_with_reason_codes   │
│   - response_timestamp                           │
│   - response_correlation_id                      │
│   - purpose_of_use as asserted by requester]     │
│           │                                        │
│           ▼                                        │
│  [Write to immutable audit log; retain per the    │
│   regulatory retention floor]                     │
│           │                                        │
│           ▼                                        │
│  [Emit cross_facility_query_resolved event for    │
│   downstream analytics, quality monitoring,        │
│   and patient-facing access reports]              │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── INVALIDATION / REFRESH ─────────────┐
│                                                    │
│  [Subscribe to events that invalidate prior        │
│   matches:                                         │
│   - Patient consent revocation or modification    │
│   - Local MPI merge or unmerge (recipe 5.1)       │
│   - Patient demographic change (recipe 5.7        │
│     name change, recipe 5.3 address change)       │
│   - Participating organization onboarding or      │
│     offboarding                                    │
│   - Cross-org identifier reassignment]            │
│           │                                        │
│           ▼                                        │
│  [Invalidate cached cross-facility match           │
│   metadata; emit cross_facility_match_invalidated │
│   event so the requesting organization can        │
│   refresh its longitudinal record assembly]       │
│                                                    │
└────────────────────────────────────────────────────┘
```

**Inbound and outbound flows share the matcher.** The same probabilistic-record-linkage scorer runs on the inbound query (someone is asking us about a patient; do we have them?) and on the outbound query response from a participating organization (they say they have a candidate; is the candidate the same person we asked about?). Build the matcher as a service and call it from both directions, rather than duplicating logic.

**Blocking is the first-order architectural choice.** Cross-facility matchers run at scale (millions of records on each side, sometimes billions in national-scale deployments), and naive O(n²) comparison is impossible. Blocking partitions the candidate set so that comparisons happen only within plausibly-related buckets. The blocking-key design is a tradeoff: too tight and true matches get split across buckets; too loose and the bucket sizes blow up. Standard production blockers use multiple complementary blocking keys (last-name-soundex plus year-of-birth, last-name-metaphone, ZIP3-plus-DOB, first-name-plus-DOB-month-day) and union the candidate sets. The matcher then scores each candidate; the final score is the max across blocks (or a composite if you want the consensus signal).

<!-- TODO (TechWriter): Expert review A12 (LOW). Reconcile the phonetic-encoding naming across the architecture diagram, this prose paragraph, and the Step 2 pseudocode. The diagram and prose alternate "soundex" and "metaphone"; the pseudocode uses double_metaphone() and stores in last_name_phonetic. Suggested fix: add one sentence noting "Production matchers typically use Double Metaphone (more accurate for non-Anglo names) rather than Soundex (the original phonetic encoding); the recipe's pseudocode uses Double Metaphone, but the principle is the same." -->


**The matcher returns more than a match decision.** The query-time response includes the match confidence, the candidate identifier, the categorical reason for the score (which features matched, which did not), and the data-release decision. The requesting organization uses all of this to decide what to do with the response: accept the match and integrate the data, accept the match but flag it for clinician review, reject the match and continue without the data. Cleanly separating "we matched" from "we released" matters for the audit trail and for correctly reporting to the patient what data was exchanged about them.

**Consent is consulted at release time, not at query time.** A legitimate query for a patient who has not consented to data sharing is not blocked at the entry point; the matcher runs, the identity is determined, and the consent check then constrains what (if anything) is released. This pattern lets the matcher's accuracy not be polluted by consent-driven bias (otherwise, patients who opt out of sharing would systematically not appear in match training data, distorting the matcher's calibration), and it lets the audit log accurately record that a query was made and that consent caused the release to be limited. The requester, depending on the framework, may receive a "consent did not permit release" indicator; in some frameworks, even acknowledging that the patient is in the responder's system requires consent.

**The audit log is the system of record for cross-organizational data flow.** Every query, every match decision, every consent check, every release. This is non-negotiable in a cross-organizational setting because the audit log is the only artifact that can answer "who saw what about this patient and when" when the patient asks (which they have a regulatory right to ask) or when a downstream incident requires forensic reconstruction. The retention floor is at least the longest of HIPAA records-retention, the HIE's contractual retention, the state's medical-records-retention requirement, and any sensitive-category-specific retention (Part 2 has its own).

**Cross-organizational match is event-driven on the maintenance side.** When a patient's local MPI changes (a merge in recipe 5.1, an unmerge, a demographic update from recipe 5.7), the cross-organizational matches that depended on the prior state need to be re-evaluated. The architecture subscribes to local MPI events and propagates re-evaluation to the cross-org layer; without this, stale cross-org matches accumulate.

**Cohort-stratified accuracy monitoring applies here too, with cross-organizational variance.** Match accuracy is not uniform across patient cohorts, and cross-facility match accuracy can be worse than intra-organizational match accuracy for the same cohorts because the demographic asymmetries (different organizations capturing different fields differently) compound. Per-cohort match success rate, per-cohort review-queue rate, and per-cohort downstream-error rate (clinician-reported wrong-patient retrieval, mistakenly-filed cross-org documents) all need monitoring with disparity thresholds.

<!-- TODO (TechWriter): Expert review A2 (HIGH). Specify the operational thresholds, per-axis aggregation, and disparity-metric definitions for cohort-stratified accuracy monitoring. Use the institutional cohort registry as the source of truth (no ad-hoc enumeration in code). Metrics: per-cohort cross-facility match success rate weekly; per-cohort review-queue rate weekly; per-cohort clinician-reported wrong-patient-retrieval rate monthly; per-cohort document-misfiling rate monthly. Disparity calculation: absolute difference between best-rate and worst-rate cohort per metric per cycle. Suggested thresholds: match-success disparity > 0.05 = MEDIUM alarm; review-queue disparity > 0.05 = MEDIUM; downstream wrong-patient disparity > 0.01 = HIGH (clinical safety). Reference 5.1, 5.2, 5.3, 5.4 Finding A2 as chapter pattern. -->

<!-- TODO (TechWriter): Expert review S1 (HIGH). Specify the identity-boundary policy for the inbound-query handler, the outbound-query submitter, the consent-and-sensitivity filter, and the audit-log writer. Inbound handler: validate the requesting organization's identity through mTLS or signed JWT, verify the asserted purpose-of-use against the participation agreement, rate-limit per requester to prevent enumeration attacks. Outbound submitter: sign queries with the institutional credential, verify response signatures from participating organizations. Consent-and-sensitivity filter: this is the most security-sensitive component; it must read consent state from the consent-registry-of-record (not from a cache that may be stale on consent revocation) and must fail closed (if the consent registry is unavailable, withhold release rather than release). Audit-log writer: append-only, signature-chained, replicated to a separate audit AWS account; tampering attempts surface immediately. Reference chapter pattern from 5.1, 5.2, 5.3, 5.4 Finding S1. -->

<!-- TODO (TechWriter): Expert review A6 (MEDIUM). Specify the cross-recipe orchestration contract for cross-facility-related events. Schema: source, detail_type, detail.local_patient_id, detail.cross_org_identifier, detail.event_id, detail.previous_state, detail.new_state, detail.detected_at. Downstream consumers in 5.1 (local matcher; cross-facility match may surface a previously-unknown duplicate-patient signal locally), 5.4 (eligibility matcher; cross-facility match data may inform a payer-side identity question), 5.6 (claims-clinical linkage; cross-facility identifier may help bridge claim-vs-clinical join), 5.7 (longitudinal name-change matcher; cross-facility queries are a common surfacing point for prior-name records), 5.8 (privacy-preserving linkage; cross-facility identifier resolution interacts with the privacy-preserving layer), plus the longitudinal-record-assembler, the patient-portal access-report generator, and the consent-management workflow, subscribe to specific detail_type values and acknowledge processing via a CloudWatch metric ({consumer}.events_processed). Reference chapter pattern from 5.1, 5.2, 5.3, 5.4. -->

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter05.05-architecture). The Python example is linked from there.

## The Honest Take

Cross-facility patient matching is the recipe in this chapter where the gap between "we have the technology" and "we have the operational capacity to deploy it well" is the widest. Every piece of the technical architecture above has been built and run in production by some HIE somewhere for over a decade. None of the matching techniques are novel. The standards are mature. The reference implementations exist. And yet most US clinicians, in the year you are reading this, still do not have a complete view of their patient at the point of care. The bottleneck is not the technology; it is the surrounding infrastructure of trust, consent, governance, and operational discipline that the technology depends on. Build the technical pipeline well, and you have done the easier half of the work.

The trap most specific to cross-facility matching is treating the matcher as a stand-alone component. The matcher is one piece of a larger flow that includes the consent registry, the sensitivity-filter policy, the audit log, the longitudinal-record-assembler, the patient-access-report generator, the operational review queue, the cohort-stratified monitoring dashboard, the participation-agreement obligations, the cross-organization quality benchmarking, and the institutional governance committees that own each of those. Each of those components is itself a project. The institutions that deploy cross-facility matching well treat it as a program rather than a system. The institutions that treat it as a system find that the matcher works fine and the surrounding context is what fails them.

A second trap, related: treating the consent layer as compliance overhead rather than as a first-class architectural input. The consent layer is where the system either earns or loses the patient's trust. A patient who discovers that their data flowed to an organization they did not authorize loses trust in the HIE and in every participating organization. That trust is hard to rebuild, and the loss often shows up as patients opting out at higher rates, which degrades the value of the HIE for everyone else. Build the consent layer as if the patient is the actual customer (because, in the end, they are), with attention to the patient-facing access report, the consent-modification workflow, the discoverability semantics, and the audit trail's accessibility to the patient. The compliance benefit is a side effect of doing the right thing for the patient.

The third trap, specific to the equity dimension: under-investing in cohort-stratified accuracy monitoring at the cross-organizational layer. Cross-facility match disparities can be larger than intra-organizational disparities because the demographic asymmetries compound. A patient with a hyphenated last name who is captured with the hyphen at one organization and without at another is at the intersection of two single-organization disparities, and the cross-facility match for them can fail in ways that the single-organization matchers do not. The downstream consequences are concrete equity issues: missed records at the point of care, delayed care for patients whose providers cannot find their history, charity-care eligibility errors that propagate from the eligibility-matching layer (recipe 5.4) into the cross-facility layer, public-health reporting gaps for affected cohorts. Monitor it, measure it, and tune for it.

The thing that surprises people coming from a single-organization-matching background is how much of the architecture is about provenance and audit rather than about matching itself. In recipe 5.1, the audit trail is important but secondary. In recipe 5.5, the audit trail is the system. Every query, every match, every consent check, every release, every withhold, every re-query for the same patient on a different day, all of it lives in the audit log. The audit log is what the patient asks to see when they exercise their right-to-know. The audit log is what compliance reviews when a partner organization's request for an audit comes in. The audit log is what reconstructs the incident when a wrong-patient release surfaces months later. Build the audit log first, before any of the matching logic, because every other piece of the architecture has to write into it.

The thing about the discoverability semantics: it is more nuanced than most teams initially design for. "Patient is in our system" is, itself, sensitive information. A query for "Maria Garcia, DOB 1972-03-14" that returns "no match" tells the requester something different than a query that returns "matched but consent does not permit release." In some frameworks, the difference between those two responses leaks information that the patient did not consent to share (the fact of being seen at this organization, even without the clinical detail). The discoverability flag in the consent registry controls this, and the responder's match-and-release pipeline has to honor it. Most implementations get this wrong on the first pass and discover the issue when the first patient files a complaint about it.

The thing about the trust-but-verify posture toward partner organizations' matchers: it does not feel collegial in the moment. When a partner returns "match, confidence 0.95," and the local matcher's secondary score is 0.78, you have to make a decision that essentially says "we do not fully trust your match." This is uncomfortable when the partner is the academic medical center across town and you are the community health center, or vice versa. The discomfort is real; the design is correct. The match-quality variance across organizations is a measurable, documented phenomenon, and the aggregating organization's responsibility to its own clinicians and patients does not disappear because the responder's matcher disagreed. Frame it as quality assurance rather than as distrust, and the institutional relationships handle it.

The thing I would do differently the second time: invest more heavily in the patient-facing access reports from day one. Most institutions build the access reports as a back-of-the-line compliance item, after the matcher and the longitudinal-record-assembler are working. The right approach is to build the access report alongside the audit log, as a first-class deliverable. The access report is what makes the rest of the architecture trustworthy, and the institutions that deploy it well find that patient engagement with the HIE goes up rather than down (counter to the intuition that "the more you tell patients about their data flows the more they will opt out"). Patients who can see who is looking at their data and what is being shared are more comfortable with the data flowing, not less. The access report is therefore a feature, not a compliance burden.

The thing that has aged surprisingly well is the IHE PIX/PDQ profile family. Designed in the early 2000s, written for HL7 v2, layered with the IHE testing and certification framework, they are still the operational substrate for most regional HIE patient discovery in the United States. FHIR Patient `$match` is the modern successor and is unambiguously the future, but the v2 PIX/PDQ infrastructure is going to be load-bearing for at least the next several years. Build the FHIR-native path because that is where the field is going; expose the v2 PIX/PDQ path because that is where most of the existing partners still live.

Last point, because it is specific to the regulatory context: the 21st Century Cures Act information-blocking rules have changed the calculus. The default has shifted from "we share when we choose to" to "we share unless an exception applies." The cross-facility match infrastructure is now load-bearing for compliance with information-blocking, not just for patient care. An HIE that has poor matcher quality, that has slow query response times, that has frequent outages, is at risk of being characterized as information-blocking by the regulator. The architecture is therefore not just a clinical-care or operational asset; it is a compliance asset. Treat it accordingly, with the audit, performance, and reliability posture that implies.

---

## Related Recipes

- **Recipe 5.1 (Internal Duplicate Patient Detection):** The probabilistic-record-linkage scorer and the review-queue tooling are reused here. Cross-facility matches sometimes surface previously-unknown internal duplicates as a side effect; the events flow into 5.1's pipeline.
- **Recipe 5.2 (Provider NPI Matching):** Cross-facility queries include the requesting provider's NPI; the NPI-matching layer from 5.2 supplies the canonical NPI value for the audit trail.
- **Recipe 5.3 (Address Standardization and Household Linkage):** Standardized addresses are a comparator in the cross-facility match scorer; the address pipeline from 5.3 directly feeds this matcher's normalization step.
- **Recipe 5.4 (Insurance Eligibility Matching):** Eligibility data informs cross-facility match (a high-confidence eligibility match across organizations is a signal for the patient match), and cross-facility match outcomes feed back into eligibility (a cross-facility match may surface a payer-side identity question).
- **Recipe 5.6 (Claims-to-Clinical Data Linkage):** Cross-facility identifier resolution helps bridge claims-to-clinical joins when claims data sits at one organization and clinical data at another.
- **Recipe 5.7 (Longitudinal Patient Matching Across Name Changes):** The prior-name handling in the cross-facility matcher is the operational manifestation of 5.7's longitudinal matching; the two recipes share data structures and event flows.
- **Recipe 5.8 (Privacy-Preserving Record Linkage):** Privacy-preserving cross-facility matching is the variation for use cases where direct demographic exchange is not available; the techniques layer on top of this recipe's pipeline.
- **Recipe 5.9 (National-Scale Patient Matching - TEFCA):** TEFCA QHIN-to-QHIN exchange is the national-scale extension of the cross-facility patterns covered here; 5.9 covers the additional governance and scale considerations.
- **Recipe 5.10 (Deceased Patient Resolution):** Death data sources reach the cross-facility matcher as a coverage-change-equivalent signal; the matcher invalidates prior matches for deceased patients and emits the appropriate downstream events.
- **Recipe 1.1 (Insurance Card Scanning):** The patient-portal coverage self-service flow can also surface cross-facility consent updates; the OCR and identity-extraction patterns from 1.1 feed both flows.
- **Recipe 1.9 (Medical Records Request Extraction):** Cross-facility patient matching is the foundation that medical-records-request workflows depend on; matching quality directly affects record-request fulfillment.
- **Recipe 2.4 (Prior Authorization Letter Generation):** Cross-facility data on the patient's prior care informs prior-authorization decisions, particularly for specialty-care referrals.
- **Recipe 7.x (Predictive Analytics):** Cross-facility data enriches risk-scoring features (a patient with care patterns across multiple organizations has different risk profile than one with all care concentrated at a single organization).

---

## Tags

`entity-resolution` · `record-linkage` · `cross-facility` · `hie` · `health-information-exchange` · `pix` · `pdq` · `fhir` · `patient-match` · `consent` · `sensitivity-filter` · `audit-log` · `tefca` · `carequality` · `event-driven` · `medium` · `production` · `hipaa` · `42-cfr-part-2` · `information-blocking`

---

*← [Recipe 5.4: Insurance Eligibility Matching](chapter05.04-insurance-eligibility-matching) · Chapter 5 · [Next: Recipe 5.6 - Claims-to-Clinical Data Linkage →](chapter05.06-claims-to-clinical-data-linkage)*
