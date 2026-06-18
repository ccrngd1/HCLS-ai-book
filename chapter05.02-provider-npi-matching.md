# Recipe 5.2: Provider NPI Matching ⭐

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.0001-0.001 per provider record matched (depends on whether you query the live registry API or batch-match against the downloadable NPPES file, plus review-queue volume)

---

## The Problem

Open the provider directory of any health plan in the country and look up a primary care doctor in your area. Click the first three results. There is a meaningful chance that one of them retired two years ago, one of them moved offices six months back to a new building, and one of them never practiced at the listed address in the first place. Call the number listed for any of them and you will sometimes get a fax line, a hospital switchboard that has not employed that doctor in five years, or a number that has been disconnected. <!-- TODO: verify provider directory accuracy statistics; CMS Secret Shopper studies and several health plan audits have repeatedly documented inaccuracy rates in the 30-50% range for provider directory entries; specific recent figures vary by year and study. -->

Now imagine you are a member of that plan, you have a chronic condition that just flared, and you need a same-week appointment. You spend forty minutes calling listed providers. Half of them are wrong. The ones you do reach are not taking new patients, or they are an hour away because the listed location is stale, or the office tells you the doctor moved to a competing practice last spring. You give up and go to the emergency department. The plan pays for an ED visit that should have been a primary-care visit. You delay care that could have been resolved in twenty minutes. Multiply this by every member of every plan in the country and you start to understand why provider-directory accuracy is a federally regulated activity with named penalties. The No Surprises Act and the regulations under it require accurate provider directories with specified verification cadences and member-facing remediation. <!-- TODO: verify the current No Surprises Act provider-directory accuracy provisions and CMS sub-regulatory guidance at time of build; the framework imposes specific verification windows (typically every 90 days) and specific remediation pathways. -->

Behind every directory entry is a question that sounds boring and turns out to be hard: *which row in our internal provider database corresponds to which entry in the National Provider Identifier registry?* The NPI is the closest thing American healthcare has to a stable, authoritative identifier for individual practitioners and the organizations they bill from. <!-- TODO: confirm; HIPAA Administrative Simplification mandates the NPI as the standard unique identifier for healthcare providers in HIPAA-covered transactions, issued by NPPES under CMS. --> Every claim filed in the country uses one or more NPIs. Every credentialing file references an NPI. Every payer's network is a list of NPIs. The registry itself (NPPES, the National Plan and Provider Enumeration System) publishes a downloadable extract once a month and exposes a public API for individual lookups. The data is real, the data is free, and the data is updated.

So you would think provider-NPI matching would be a solved problem. You take your internal provider record, you look up the NPI, you write down the answer, and you move on. And for the easy cases, that is exactly what happens. Then you hit the ones that are not easy. Two providers with the same name in the same state. A provider who has both a Type 1 (individual) NPI and is also affiliated with three Type 2 (organizational) NPIs that bill for them. A provider who legally changed their name two years ago and your system still has the old name and the registry has both with a deactivation flag on one. A provider whose office address changed six months ago and your system has the new address but the registry has the old one because the provider has not updated their NPPES entry (which is on the provider, not on you). A provider whose specialty taxonomy in your system is "Family Medicine" and in the registry is "Family Medicine, Adolescent Medicine, Sports Medicine" because the registry stores all taxonomies the provider self-attests, not just the primary one.

Now layer on the operational realities. Your credentialing team has a stack of three hundred new providers being onboarded for an open enrollment that starts in eight weeks. Your network adequacy team has to certify the directory for a state filing and the certification requires NPIs verified against the registry within the last ninety days. Your claims team has a backlog of denied claims because the billing NPI on the claim does not match the credentialed NPI on file, and the difference is a renewal that the provider did not flag to your operations team. Your data analytics team is trying to compute network composition by specialty and the taxonomies in your system do not align with the registry taxonomies, so the report is wrong by some amount that nobody can quantify. Each of these workflows is asking the same underlying question: which internal provider record corresponds to which NPI registry entry, and is the answer still right today?

This is the recipe. It is the second recipe in Chapter 5 because it shares almost all of its infrastructure with Recipe 5.1 (the same blocking, the same comparators, the same review queue, the same audit trail). It is in the Simple tier because the NPI is a real anchor: the registry is authoritative, well-structured, queryable, and free, and most providers have one and only one Type 1 NPI. The work is not in the matching algorithm; the work is in handling the dozen reliable edge cases that come up at scale and in keeping the matches fresh as both sides change.

Let's get into how you build it.

---

## The Technology: Matching Against an Authoritative Registry

### Why This Is Different From Patient Matching

Patient matching (recipe 5.1) is hard because there is no authoritative registry. You have a database of patient records and you are trying to figure out which ones go together based on noisy demographic data alone. Provider matching has a structurally easier problem: there is an authoritative registry, the NPPES, and the question is "which entry in the registry corresponds to this internal record." The registry is, for most providers, the truth. Your job is to find the truth and connect it to your record, then keep that connection up to date as both sides drift.

This changes the architecture in important ways. You are not doing pairwise comparison across your own database. You are doing one-sided lookup against an external authoritative source. Your blocking and comparator infrastructure is similar (same string-similarity functions, same probabilistic combiner, same review queue), but the data flow is different and the failure modes are different. Most of the headaches in provider matching come from edge cases in the registry itself, from drift between your record and the registry record, and from the operational rhythm of keeping the matches fresh on a regulated cadence.

### What the NPI Actually Is

A National Provider Identifier is a ten-digit numeric identifier assigned by the NPPES to a healthcare provider. There are two types: Type 1 NPIs are issued to individual practitioners (a doctor, a nurse practitioner, a physical therapist), and Type 2 NPIs are issued to organizations that provide healthcare (a clinic, a hospital, a group practice, a billing entity). A given individual provider has exactly one Type 1 NPI for life. They do not get a new one when they change practices, change names, or move to a different state. The Type 1 NPI is stable. <!-- TODO: confirm at time of build; the NPI Final Rule (45 CFR 162.404) and CMS guidance establish the lifelong-stable Type 1 design. --> A given organization has one Type 2 NPI per business entity, with new NPIs issued when subparts (specific clinic locations or service lines) are enumerated separately for billing reasons. The same individual provider can be associated with several Type 2 NPIs at the same time: their solo practice's Type 2, the hospital they are credentialed at, the academic medical center group they bill under for some of their work, and so on.

The NPPES record for a given NPI carries a defined set of fields. For a Type 1 NPI: legal first name, middle name, last name, name suffix, credential string (MD, DO, NP, PA, RN), other names (previous names with the type of name change documented), gender, primary practice address (the location where the provider primarily practices, intended to be where members can find them), mailing address (often a billing or back-office address, not the practice address), phone, fax, license numbers and states, taxonomy codes (specialty designations from the NUCC Health Care Provider Taxonomy code set, with one designated as primary), the enumeration date, the last update date, and a deactivation status with reason code if the NPI has been deactivated. For a Type 2 NPI: legal business name, doing-business-as name, authorized official name and credentials, organization type, the same address fields as Type 1, and the same taxonomy and license fields. <!-- TODO: verify the precise NPPES public-data field set at time of build; the schema is documented in the NPPES Data Dissemination File specification published by CMS and is updated periodically. -->

Critically, NPPES is **self-attested**. Providers update their own records. The NPPES does not actively verify that the practice address is current, that the phone number rings the right office, that the listed taxonomies are still being practiced, or that the provider is still alive. The registry has a "deactivation" flag for NPIs whose holders have notified the NPPES of retirement or death, but the lag between when a provider stops practicing and when the registry reflects it can be substantial. The address fields in particular are widely known to be stale; CMS and other regulators have repeatedly flagged this as a directory-accuracy concern. <!-- TODO: verify; CMS Provider Directory Accuracy reports and OIG audits have documented address staleness in NPPES. -->

This matters for your matching system because it shapes what fields you can rely on. The NPI itself, once known, is a strong anchor (it does not change). The legal name on the record is generally accurate, with two known patterns of staleness (legal name changes that have not been propagated, and name spellings that differ from your internal source). License numbers and license states are accurate when present (the provider had to provide them to get the NPI). The primary practice address is a soft signal. The taxonomy codes are a soft signal. Deactivation flags are accurate when present and silent when not (so the absence of a deactivation flag does not mean the provider is actively practicing).

### The Two Sources of NPPES Data

NPPES exposes its data two ways. Pick the right one for the workload.

**The NPPES Downloadable File.** A monthly bulk export of every NPI in the country, published as a CSV file with hundreds of millions of rows across all NPIs ever issued (including deactivated ones). <!-- TODO: confirm the current NPPES Downloadable File schema and update cadence; CMS publishes a monthly full file plus weekly incremental updates. The full file is large (multiple GB compressed) and contains every active and historical NPI. --> This is the right substrate for batch matching workflows: monthly refresh of your internal provider directory against the registry, network-adequacy reporting, claims-NPI validation against credentialed-NPI files, and any analytics that needs a complete picture of the provider population. The file is free to download, no API key, no rate limit. The data is the same data the API serves but with the convenience of being able to scan, join, and compute on the whole thing in your own infrastructure.

**The NPI Registry API.** A REST endpoint that returns NPI records for individual lookups, with parameters for searching by NPI number, name, location, taxonomy, and a few other fields. <!-- TODO: confirm the current NPI Registry API endpoint, parameters, and rate limits at time of build; the public API is at npiregistry.cms.hhs.gov with documented query parameters and is rate-limited. --> Lower latency for individual lookups, useful for real-time workflows like onboarding a new provider where you need an answer in seconds, and useful for spot-checking specific providers between batch refreshes. Less suitable for bulk operations because of rate limits and the cost in time of round-tripping a million records through individual API calls.

Most production matching pipelines use both. The downloadable file is the primary substrate for batch refresh, network-adequacy analytics, and the search index for candidate generation. The API is the path for real-time individual lookups during onboarding and for spot-checking ambiguous matches.

### The Match Problem

Your internal provider table has a row for "Sarah J Patel, MD, Family Medicine, 1421 Elm Street, Anytown, ST 12345, license MD-87543, primary care." The registry has thousands of rows for "Sarah Patel" across the country. Your job is to find the row in the registry that corresponds to this person, attach the NPI to your internal record, and recompute the match periodically as the registry updates and as your internal data updates.

If you are lucky, the row in your internal record already has the NPI (because the provider supplied it during onboarding, or because you imported it from a credentialing file that already had it). In that case the match is trivial: look up the NPI in the registry and confirm the registry record is consistent with your internal record. This happens for most newly-onboarded providers in well-run organizations and for providers whose data lineage is recent.

If you are not lucky, the internal record has no NPI (because the provider was onboarded years ago before NPI capture was required, or because the data came from a source that does not include NPI, or because the NPI was supposed to be captured but the field was left blank). Now you have to find it. The fields you have to match on, in roughly decreasing order of information value:

- **License number plus state.** A medical license is state-issued and the combination of license number and license state is unique within that state. Providers self-attest their licenses on the NPPES, so the registry has them. If your internal record has a license number and state, it is almost always sufficient as a single-field match. The NPI Registry API supports license-based search.
- **Legal name plus state.** First name and last name plus the state where the provider primarily practices is sufficient to narrow most lookups to a small set. If the name is unusual (low population frequency), a state lookup is often a single-row result.
- **Legal name plus taxonomy.** First and last name plus a primary specialty taxonomy code narrows further. Useful when the name is more common.
- **Practice address.** The street address of the primary practice location, particularly the ZIP code. Usable as a candidate-generation key, less reliable as a discriminator because addresses drift.
- **Phone number.** Unreliable in NPPES (the listed phone is often a fax or a back-office number, not the practice phone). Worth comparing as a tiebreaker but not as a primary key.
- **Other names.** The NPPES "other names" field carries previous legal names with a typed reason. If your internal record has the previous name and the registry has the current name, the other-names field is the linkage.

You do not match on all of these at once. You design a small number of blocking passes that pull plausible candidates and a per-pair scoring step that decides which candidate is the right one.

### Where Provider Matching Differs From Patient Matching

The string-similarity and probabilistic-linkage techniques from recipe 5.1 carry over directly. Jaro-Winkler on first names. Damerau-Levenshtein on last names. Phonetic encoders for blocking. Fellegi-Sunter for combining field scores. The same library tooling (Splink, dedupe, recordlinkage) works. The same review-queue patterns work. Several details are different enough to call out:

**Provider data quality is generally better than patient data quality.** Providers are professionally registered. They have credentials they care about. They have license numbers they have to keep current. They do not get registered by harried front-desk staff in five-minute windows. The data has fewer missing fields, fewer typos, and more stable identifiers. Many provider matches that are hard in the patient context are easy in the provider context.

**The taxonomy code is a powerful field.** The NUCC taxonomy code set is a hierarchical classification of provider specialties. It is more granular than the free-text specialty fields most internal systems carry. Mapping your internal "Family Medicine" to the corresponding NUCC code (207Q00000X) and the registry's primary taxonomy lets you compare at the structured level. Mismatches are still common (your internal record says "Pediatrics" and the registry primary is "Pediatric Cardiology" because the provider self-attested both and listed the subspecialty primary), but they are richer signals than free-text comparison would be.

**The "one and only one Type 1 NPI" rule simplifies merge logic.** Each individual provider has exactly one Type 1 NPI in the registry. There is no equivalent of "duplicate Type 1 NPIs for the same person." If you find two candidate Type 1 NPI matches for the same internal record, at most one of them is correct, and the others are either different people or you are looking at deactivated-and-re-issued situations (which the registry generally prevents but which can show up in legacy data). Your matching system can use this rule as a hard constraint: a single internal record gets at most one Type 1 NPI.

**Type 2 NPIs are many-to-many with people.** A provider who works at a solo practice, two hospital systems, and a billing service might be associated with four different Type 2 NPIs. None of those Type 2s "is" the provider; they are the billing entities the provider works under. Your internal record might be tracking the provider's individual identity (Type 1) or one of their billing relationships (Type 2). The matching system needs to know which it is asking about. Some operational workflows (credentialing) care about Type 1. Some (claims, network adequacy) care about both.

<!-- TODO (TechWriter): Expert review A5 (MEDIUM). Diagnose the Type 2 persistence model in the architecture: the assignment record should carry the matched Type 1 NPI plus a list of current Type 2 affiliations (each with affiliated organization, effective date range, primary-billing flag); drift detection should surface `type2_affiliation_added` and `type2_affiliation_removed` as separate events from Type 1 drift, with downstream consumers (claims validation, network-adequacy reporting) subscribing to the events relevant to their workflow. -->


**Deactivation status matters.** A deactivated NPI in the registry means the provider has retired, died, or otherwise notified NPPES that they are no longer practicing. Your matching system should fetch and consider the deactivation flag at every match: matching to a deactivated NPI is almost always wrong (the provider in your record cannot be a deactivated provider unless your record itself is also deactivated), and matching to a deactivated NPI without surfacing the deactivation status to operations is a directory-accuracy failure waiting to happen.

**The match needs to be refreshed on a cadence.** Patient matching is mostly "match once, hold forever, unmerge if wrong." Provider matching is "match once, then re-verify regularly because the registry data drifts." Network adequacy regulations typically require the verification to happen on a defined cadence (every ninety days is common). The architecture has to schedule, execute, and audit those re-verifications, and surface drifts (address change, taxonomy change, deactivation) to operations promptly.

**The volume is much lower than patient matching.** A health plan covering a million members might have a provider network of a hundred thousand NPIs. A health system might credential a few thousand individual providers. The cardinality is two to three orders of magnitude smaller than patient deduplication. This makes some operational choices easier (you can afford to query the API for everyone monthly if you want) and some harder (the per-match cost of error is higher because each match represents many member-facing or claim-affecting decisions).

### The Three-Bucket Output, Familiar From 5.1

A provider matching system has the same three-bucket output as a patient matcher: auto-match (high confidence, attach the NPI to the internal record automatically), human review (medium confidence, queue for credentialing or operations review), and auto-non-match (low confidence, no action). The thresholds are set by operations leadership, typically on the conservative side because the cost of a wrong NPI on a credentialed-provider record propagates into claims processing, network adequacy reporting, and member-facing directories. Because the volumes are lower than patient matching, the review queue is much smaller, and the team that staffs it is typically the credentialing or provider-data-management team rather than a dedicated HIM function.

### Where the Field Has Moved

A few practical updates worth knowing:

- **Provider directory accuracy regulations have tightened.** The No Surprises Act and CMS sub-regulatory guidance impose specific verification cadences, member-facing remediation pathways, and penalties for chronic inaccuracy. Multiple state-level rules layer on top. The matching system is now subject to specific compliance requirements, not just operational ones. <!-- TODO: verify current No Surprises Act provider-directory provisions and any CMS rule updates at time of build. -->
- **Provider Data Service vendors have proliferated.** Companies like LexisNexis Provider Data Solutions, Symplr, Kyruus, Verisys, BetterDoctor (now Quest Analytics), and others sell provider data services that wrap the NPPES with additional verification (license-board scraping, sanction-list cross-referencing, periodic outreach to the provider for confirmation). <!-- TODO: verify current vendor landscape at time of build; the market consolidates and new entrants emerge. --> They are reasonable build-vs-buy candidates for organizations that do not want to operate the matching pipeline. The architecture in this recipe applies whether you build or integrate; if you integrate, the matching service replaces the registry-direct path but the review queue, audit trail, and operations workflow remain.
- **NPPES is increasingly being supplemented by other sources.** State medical board websites for license verification. The OIG List of Excluded Individuals/Entities (LEIE) for sanction status. The Death Master File (where access is permitted) for deceased-provider detection. The matching pipeline is becoming a multi-source verification pipeline, not a single-source-lookup pipeline.
- **Endpoints / FHIR Practitioner resources are increasingly shared.** Some health information exchanges and trust-framework participants now publish FHIR Practitioner resources that include the NPI alongside the structured demographic and credentialing data. <!-- TODO: confirm; FHIR US Core profiles for Practitioner and PractitionerRole are referenced in TEFCA exchange and in CMS interoperability rules. --> Where these exist, they are an additional substrate for matching.

---

## General Architecture Pattern

The pipeline has six logical stages: ingest the internal provider records and the registry data, normalize both sides, generate candidate matches through blocking, score the candidates, route by threshold to auto-attach or review, and persist the resolved NPI assignments with a re-verification schedule.

```text
┌────────────── INGEST AND NORMALIZE ───────────────┐
│                                                    │
│  [Internal Provider Records]   [NPPES Registry]    │
│  (credentialing system,         (monthly download   │
│   HR system, network             plus on-demand     │
│   management system)             API for individual │
│                                  lookups)           │
│           │                              │          │
│           ▼                              ▼          │
│  [Field-level normalization (both sides)]          │
│   - Names: case-fold, trim, strip diacritics       │
│   - Credentials: parse credential strings           │
│     (MD, DO, NP, PA-C, etc.)                       │
│   - License numbers: strip formatting               │
│   - Addresses: USPS-standardize                     │
│   - Phones: strip formatting to E.164              │
│   - Taxonomy codes: map free-text specialty         │
│     to NUCC codes where possible                    │
│           │                              │          │
│           ▼                              ▼          │
│  [Phonetic encoding (double metaphone) for         │
│   first and last name; use as blocking keys]       │
│           │                              │          │
│           ▼                              ▼          │
│  [Persist normalized records with provenance]      │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── BLOCKING / CANDIDATE GENERATION ─────┐
│                                                    │
│  [Internal record needing NPI]                     │
│           │                                        │
│           ▼                                        │
│  [Multiple blocking passes against registry:       │
│   pass 1: license_number + license_state           │
│           (highest information; often single hit)  │
│   pass 2: last_name_metaphone + first_initial      │
│           + state                                  │
│   pass 3: last_name_metaphone + taxonomy_primary   │
│           + state                                  │
│   pass 4: address_zip + last_name_initial          │
│   pass 5: phone_last_4 + last_name_initial         │
│           (low yield, useful for tiebreakers)      │
│   ...add passes only if recall measurement         │
│   shows they are needed]                           │
│           │                                        │
│           ▼                                        │
│  [Candidate set = union across passes;             │
│   typically 1-50 candidates per internal record]   │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── SCORE CANDIDATE PAIRS ──────────────┐
│                                                    │
│  [Candidate (internal_record, registry_record)]    │
│           │                                        │
│           ▼                                        │
│  [Per-field comparison:                            │
│   - first_name: Jaro-Winkler                       │
│   - last_name: Damerau-Levenshtein + metaphone     │
│   - credential: parsed-credential overlap          │
│     (MD vs MD, DO vs DO, NP vs NP)                 │
│   - license_number + state: exact                  │
│   - taxonomy: NUCC code match (primary/any)        │
│   - practice_address: token + USPS standardized    │
│   - phone: weak signal, tiebreaker only            │
│   - other_names: registry "previous name" match]   │
│           │                                        │
│           ▼                                        │
│  [Probabilistic combiner (Fellegi-Sunter):         │
│   - Per-field m and u from EM on internal-vs-      │
│     registry labeled set (or use sensible          │
│     default priors initially)                      │
│   - Sum log-likelihood ratios                      │
│   - Output: composite match score]                 │
│           │                                        │
│           ▼                                        │
│  [Hard filters:                                    │
│   - registry record deactivation status            │
│     (deactivated NPIs auto-fail the match)         │
│   - Type 1 vs Type 2 type-mismatch fail            │
│   - State-license-mismatch hard fail when          │
│     internal record has explicit license state]    │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── ROUTE BY THRESHOLD ─────────────────┐
│                                                    │
│  [Per-candidate composite score]                   │
│           │                                        │
│           ▼                                        │
│  [Pick highest-scoring candidate as proposed       │
│   match, second-highest as runner-up]              │
│           │                                        │
│           ▼                                        │
│  [Top score >= HIGH_THRESHOLD AND                  │
│   margin(top, runner-up) >= MIN_MARGIN ?]          │
│      ├── Yes → AUTO-ATTACH path                    │
│      └── No                                        │
│            │                                       │
│            ▼                                       │
│      [Top score <= LOW_THRESHOLD?]                 │
│          ├── Yes → AUTO-NON-MATCH (no action)     │
│          └── No → REVIEW QUEUE                    │
│                     │                              │
│                     ▼                              │
│             [Credentialing / provider-data         │
│              specialist review:                    │
│              attach / not-this-NPI / unknown]      │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── PERSIST AND SCHEDULE RE-VERIFY ─────┐
│                                                    │
│  [Match decision (auto or human)]                  │
│           │                                        │
│           ▼                                        │
│  [Write to provider-NPI assignment table:          │
│   - internal_provider_id                           │
│   - matched_npi (Type 1 and any Type 2 list)       │
│   - match_score, match_method, decided_by,         │
│     decided_at                                     │
│   - source registry version (NPPES file date)      │
│   - drift fields snapshot (address, taxonomy,      │
│     deactivation status at time of match)]         │
│           │                                        │
│           ▼                                        │
│  [Schedule re-verification per regulatory          │
│   cadence (typically 90 days);                     │
│   refresh from latest NPPES on each cycle]         │
│           │                                        │
│           ▼                                        │
│  [Drift detection: compare current registry        │
│   record to drift snapshot; surface changes        │
│   (address, taxonomy, deactivation) to ops]        │
│           │                                        │
│           ▼                                        │
│  [Emit assignment-and-drift events to              │
│   downstream consumers (credentialing,             │
│   directory, claims processing, network            │
│   adequacy reporting)]                             │
│                                                    │
└────────────────────────────────────────────────────┘
```

**Ingest is dual-source.** Two ingest paths run in parallel: the internal provider data (from credentialing, HR, network management, or however the institution maintains its provider records) and the NPPES extract (from the monthly downloadable file plus on-demand API calls for newly-onboarded providers between batch refreshes). Both sides are normalized to the same canonical field schema before any matching happens. The internal data is usually messier (free-text specialty fields, inconsistent credential strings, sometimes-stale addresses); the registry data is cleaner but has its own quirks (mailing address vs practice address, multiple taxonomies with one designated primary, the periodic deactivation events).

**Blocking is more efficient than in patient matching because the cardinality is lower and the anchor fields are stronger.** Pass one (license number plus state) often returns a single candidate, and that single candidate is almost always the right answer. Pass two (name plus state) handles records without a license-number field. The remaining passes are tighter than the patient-matching equivalents because the registry is smaller (a few million NPIs total versus the population of an entire health system). For a typical internal directory of a few thousand to a hundred thousand providers, the candidate-pair count comes out in the tens of thousands to low millions, all of which is fast.

**Scoring uses the same probabilistic-linkage core as recipe 5.1, with additional hard filters specific to the registry.** A registry record marked deactivated is filtered out of the candidate pool unless your internal record is also marked inactive. A Type 2 NPI candidate is filtered out when the internal record is for an individual provider, and vice versa. State-license mismatch is a hard fail when both sides have explicit license states. These filters do not need to go through the probabilistic combiner; they are categorical exclusions that make the downstream comparator work easier and reduce false positives in low-information cases (a name match in the wrong state, for example, gets excluded before it ever scores).

**Threshold routing adds a margin requirement.** Unlike patient matching, where the typical question is "are these two records the same person," provider matching often has a "best candidate vs runner-up" structure where multiple plausible candidates exist (multiple Sarah Patels in the state, for example). The router should require not just a high absolute score on the top candidate but a meaningful margin between the top candidate and the runner-up. A top score of 9.5 with a runner-up of 9.3 is suspicious; that pair should go to review even though the top candidate cleared the absolute threshold. A top score of 9.5 with a runner-up of 2.1 is unambiguous.

**Persistence captures both the match and a drift snapshot.** The match record stores the matched NPI, the score, the decision metadata, and a snapshot of the registry fields most likely to drift (practice address, taxonomy, deactivation status, license expiration). At each re-verification, the snapshot lets the system detect drift cheaply: compare current registry values to the snapshot, surface differences. Drift events feed the credentialing team's queue and the directory accuracy compliance reporting.

**Re-verification cadence is a first-class scheduling concern.** Network adequacy regulations require periodic verification (commonly every ninety days). The architecture schedules re-verification per regulatory cadence, executes it on the schedule, and surfaces failures (NPI deactivated, address changed, taxonomy changed) to operations. The schedule is per-NPI, not per-batch, so additions to the network start their re-verification timer from their match date rather than from the next batch cycle.

**Cohort-stratified accuracy monitoring is required here too.** Provider-matching errors are not uniformly distributed across cohorts. Providers with names from naming conventions outside the dominant culture, providers with newly-issued NPIs (less drift history, less data to cross-reference), and providers in certain rural states (where multiple providers share addresses or where address standardization is harder) all match at different rates than the dominant cohort. The monitoring patterns from recipe 5.1 carry over directly: per-cohort match rate, per-cohort review-queue depth, per-cohort post-match drift rate, with alert thresholds and a documented remediation pathway when disparities cross threshold.

<!-- TODO (TechWriter): Expert review A2 (HIGH). Specify the operational thresholds, per-axis aggregation, disparity-metric definitions, and chronic-suppression handling for cohort-stratified accuracy monitoring. Match-rate disparity threshold (suggested 0.10), auto-attach precision disparity threshold (suggested 0.05), review-queue depth-per-FTE disparity (suggested 0.20), post-match drift-rate disparity (suggested 0.05), MIN_COHORT_SAMPLE_SIZE (suggested 100 per measurement window because provider volumes are smaller than patient volumes; document the rationale for the lower floor). Specify per-axis-per-metric override mechanism, cohort-stratified gold-set construction discipline, and the diagnose-and-address workflow that fires on threshold crossings. Inherits the rigor from 5.1's cohort-monitoring framework. -->


---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter05.02-architecture). The Python example is linked from there.

## The Honest Take

Provider-NPI matching is the easiest entity-resolution problem in healthcare and it is still surprisingly under-implemented. The reason it is easy: there is an authoritative public registry, the registry is queryable, the data is generally clean, and the cardinality is two to three orders of magnitude smaller than patient matching. The reason it is under-implemented: most organizations have grown their provider directory organically through credentialing files that were spreadsheets, then a credentialing tool, then the credentialing tool got replaced and the data did not get fully migrated, then the network was acquired and merged, and the resulting provider table has every shape of bad data you can imagine. The infrastructure exists in the credentialing tool. The infrastructure exists in the network management system. Nobody has stitched them together with the registry as the connective tissue. The matcher is the connective tissue.

The trap most specific to this domain is treating it as a credentialing-team problem rather than as a directory-and-claims problem. Credentialing teams care about NPI verification because their compliance posture requires it; they think of the matcher as a credentialing-quality control. Network management teams care about NPI verification because their directory accuracy requires it; they think of the matcher as a directory-quality control. Claims teams care because their claim NPI validation requires it. Network adequacy teams care because their compliance reports require it. Each of these constituencies builds (or buys) their own version of the matcher, with their own thresholds, their own review queues, their own update cadence, and their own audit trail. The matcher gets duplicated three or four times across the organization, and the matches drift relative to each other, and the directory says one thing while the claims-validation system says another and the credentialing system says a third. The pattern that works is to centralize the matcher as a shared service with a single source of truth (the assignment table), and have all the downstream consumers consume from that single source. That is an organizational design decision more than a technical one, and it is the most consequential decision in the project.

A second trap, related: under-investing in the drift-detection pipeline. The match-once-and-forget pattern is the default. NPPES drifts. The provider's address changes. The provider acquires an additional taxonomy. The provider's NPI gets deactivated. Without drift detection, your directory says the provider is at the old address six months after they moved, your claims system rejects valid claims because the credentialed NPI is now deactivated, and your network adequacy report says the network has providers it does not actually have. Drift detection is not a sophisticated piece of engineering; it is a snapshot comparison and an event emit. But it is the difference between a matcher that keeps the directory accurate and a matcher that produces a static snapshot that decays. Build the drift pipeline at the same time as the initial matcher; do not defer it.

The third trap, specific to organizations with multiple lines of business: configuring the re-verification cadence as a global constant rather than per-segment. Medicare Advantage has stricter requirements than commercial. Medicaid has state-by-state variation. Behavioral-health networks have different rules than medical networks. <!-- TODO: confirm specifics; CMS Medicare Advantage Provider Directory rules, NCQA standards, and state Medicaid agency rules each impose distinct verification cadences. --> A global ninety-day cadence might be fine for the largest segment and inadequate for the most-regulated one. Architect for per-segment cadences from the start. The complexity of segment-specific configuration is small; the complexity of retrofitting it after a Medicare Advantage audit is large.

<!-- TODO (TechWriter): Expert review A4 (MEDIUM). Architect the per-segment cadence model. Add a `verification-cadence-config` table keyed on segment_id (medicare_advantage, medicaid_<state>, commercial, behavioral_health, ...) with cadence_days, regulatory_basis, and last_reviewed_at. The `provider-npi-assignment` record carries a provider_segments list; `attach_npi` computes the effective cadence as the minimum across segments. A cadence change for a segment triggers a re-schedule for every provider in that segment. The recipe correctly diagnoses the trap in the Honest Take but the architecture's single VERIFICATION_CADENCE_DAYS constant produces the global-cadence pattern the Honest Take warns against. -->


The thing that surprises people coming from generic data-integration backgrounds is the centrality of the deactivation flag. In most data-integration problems, the source data is treated as authoritative and stable. NPPES is authoritative but not stable: NPIs get deactivated when providers retire, die, or notify NPPES of a change in status. A matched NPI that becomes deactivated is a critical event for the directory (the provider is no longer in network) and for claims (claims billed under a deactivated NPI may be rejected) and for credentialing (the provider's status needs review). The deactivation flag is the most important field in the drift-detection pipeline, full stop. Do not bury it. Surface it. Alarm on it. Make it the highest-priority drift event.

The thing about the equity dimension: provider-matching disparities are real, smaller in scale than patient-matching disparities (because the data quality is higher and the registry is authoritative), but real nonetheless. Providers with names from naming conventions outside the dominant culture, providers in rural areas where address standardization is harder, providers with newly-issued NPIs (less data to cross-reference), all match at slightly worse rates. Cohort-stratified accuracy monitoring catches this; per-cohort comparator tuning addresses it. The directory consequences of these disparities are concrete: a provider with a slightly-worse-matching name is more likely to have a stale or wrong directory entry, which means members trying to find that provider have a worse experience, which means the provider's patient population is more likely to be inadequately served. Equity in matching is equity in access.

The thing I would do differently the second time: invest more in the front-door capture of NPI at every point a provider enters the data ecosystem. Credentialing applications. HR onboarding for employed providers. Network agreements for contracted providers. Vendor agreements for billing services. Every form that asks for a provider should ask for the NPI. Every system that creates a provider record should require the NPI as a non-null field. The matcher exists because the front-door capture is incomplete; making the front-door capture more complete reduces the load on the matcher and improves the quality of every downstream system. Run the front-door capture project in parallel with the matcher build, not after.

Last point, because it is specific to the regulatory context: provider directory accuracy is now a compliance issue, not just a customer-experience issue. The No Surprises Act, CMS sub-regulatory guidance, and state-level provider-directory rules impose specific verification cadences, specific member-facing remediation pathways, and specific penalties for chronic inaccuracy. <!-- TODO: confirm current penalty structures at time of build; the regulatory framework continues to evolve. --> The matcher is not an optional operational improvement. It is the substrate that makes compliance possible. Build it as compliance infrastructure, with the audit trail, retention discipline, and access control that comes with that designation. The cost of building it well is small relative to the cost of explaining to regulators why the directory was wrong for six months in a row.

---

## Related Recipes

- **Recipe 5.1 (Internal Duplicate Patient Detection):** Sibling Simple-tier recipe; the string-similarity, probabilistic-linkage, blocking, review-queue, and audit infrastructure are shared. The provider-matching pipeline is essentially recipe 5.1's framework reapplied to a different data source with additional drift-detection and re-verification logic.
- **Recipe 5.3 (Address Standardization and Household Linkage):** The USPS-standardization layer used for provider practice addresses is the same layer used for patient addresses and household linkage. Build it once, use it across recipes.
- **Recipe 5.4 (Insurance Eligibility Matching):** Provider-NPI verification is part of insurance eligibility (the eligibility response often references the in-network provider's NPI); the verification pipelines are complementary.
- **Recipe 5.5 (Cross-Facility Patient Matching for HIE):** Provider-NPI assignments are part of the HIE participant data; the matching infrastructure carries forward.
- **Recipe 5.6 (Claims-to-Clinical Data Linkage):** Claims carry billing NPI, rendering NPI, attending NPI, and other provider identifiers; linking those to internal provider records uses the matcher built here.
- **Recipe 4.3 (Provider Directory Search Optimization):** A clean provider-NPI assignment table with current addresses and taxonomies is the foundation for provider-directory search optimization.
- **Recipe 7.x (Predictive Analytics):** Provider-attributed quality measures and risk-adjusted outcomes depend on accurate provider-attribution, which depends on accurate NPI matching.
- **Recipe 13.x (Knowledge Graphs):** A clean provider identity is an anchor in any provider-centric or patient-provider knowledge graph; the matcher's output feeds the entity-resolution layer underneath the graph.

---

## Tags

`entity-resolution` · `record-linkage` · `provider-matching` · `npi` · `nppes` · `credentialing` · `provider-directory` · `network-adequacy` · `fellegi-sunter` · `probabilistic-linkage` · `blocking` · `string-similarity` · `drift-detection` · `re-verification` · `splink` · `simple` · `mvp` · `hipaa` · `no-surprises-act`

---

*← [Recipe 5.1: Internal Duplicate Patient Detection](chapter05.01-internal-duplicate-patient-detection) · Chapter 5 · [Next: Recipe 5.3 - Address Standardization and Household Linkage →](chapter05.03-address-standardization-household-linkage)*
