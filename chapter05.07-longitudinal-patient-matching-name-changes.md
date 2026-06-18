# Recipe 5.7: Longitudinal Patient Matching Across Name Changes ⭐⭐⭐⭐

**Complexity:** Complex · **Phase:** Production · **Estimated Cost:** ~$0.0001-0.001 per name-change resolution at population scale, dominated by review tooling and audit infrastructure rather than per-record fees (depends on the institution's name-change rate, the depth of historical retention, and the sensitivity-handling overhead the institution requires)

---

## The Problem

A nurse at the cancer infusion center is preparing a chemotherapy bag for the patient sitting in chair 4. She scans the patient's wristband, the EHR pulls up the chart, and the active medication list shows a regimen the nurse has never seen for this diagnosis. She clicks back through the chart looking for the consult note that started the regimen. The note is not there. She clicks into the imaging history. The most recent CT is from eight months ago. She knows the patient told her she had a CT three weeks ago at the same hospital. She clicks into the labs. The lab trend graph stops at a date six months ago and resumes a month ago, with a six-month gap that does not match what the patient just told her about her treatment. The patient sees the nurse's face and says, *I changed my name in March. I think some things got separated. The other nurse said it would be fine but every time I come in someone has to fix something.*

This is what longitudinal patient matching across name changes is for. The patient is one person. The records are one person's records. The matcher knows it. The historical chart that was created under the patient's prior name is sitting in the same database as the current chart that was created under her current name, and the two are tied together by a cross-reference that has been built precisely to handle this case. The chart-rendering layer in the EHR did not consult the cross-reference, or consulted it and applied it incorrectly, or consulted it and rendered the historical chart under the prior name without surfacing the linkage to the nurse, or consulted it and silently dropped the historical chart entirely because the match logic failed when the prior name was retired. Any of those failure modes is common in production. All of them produce the same outcome: the nurse, the patient, and the safety of the next infusion are at risk because the system that should have presented one continuous record presented a fragmented one.

The clinical-safety scenario is the dramatic one. It is far from the only one. Names change. People get married. People get divorced. People get remarried. People take a hyphenated name and then drop the hyphen. People legally change their name for any number of reasons. People go through gender transition and change their name (and sometimes their sex assigned at birth and their other demographic data) accordingly. People naturalize and change their family name to align with their adopted country's conventions. People with names from naming traditions that English-language registration systems do not handle well (Spanish double surnames, East Asian family-name-first conventions, Arabic patronymics, names with diacritics that the EHR strips on input) accumulate variations across years of registrations as different staff transcribe their names differently. People drop a suffix (Jr, Sr, II) when their parent dies. People reverse a suffix when they become a parent themselves. People who did not previously use a middle name start using one. People drop a previously-recorded middle name in favor of just an initial. People in the same family are co-registered with overlapping data fields and confused for each other in ways that name changes amplify.

Now multiply this across every patient in a population over a multi-decade horizon, and the longitudinal-matching problem looks less like an exception case and more like the operational substrate that the rest of the patient-matching infrastructure depends on. Recipe 5.1 (internal duplicate detection) treats name as one demographic feature among several. Recipe 5.4 (insurance eligibility matching) treats the demographic asymmetry between payer-side and provider-side names as a feature mismatch to be scored. Recipe 5.5 (cross-facility matching) treats the cross-organizational name variation as a tolerance to be calibrated. None of those recipes solves the name-change problem at its root. They handle the name-mismatch artifact with a tolerant matcher and assume the underlying continuous identity is stable. The continuous identity is what this recipe is about.

The harder versions of the question are everywhere:

You are running a women's health clinic that has been in continuous operation for forty years. A substantial fraction of your long-term patients have been seen for thirty or more years, and the lifetime name-change rate among them is over forty percent. <!-- TODO: confirm at time of build; lifetime name-change rates from marriage/divorce/legal-change vary widely by population and by region, with U.S. women historically experiencing markedly higher rates than men, but specific figures are study-dependent. --> You have charts on file from before the EHR was deployed (paper, scanned into PDF, indexed under the name on the chart at the time of scanning), charts created in the original EHR (which had no concept of prior names), charts migrated to the current EHR (which does have a prior-names field, but the migration did not always populate it), and charts created in the current EHR after the prior-names feature went live. The patient sitting in front of you today has charts in all four buckets, under three different names, and you need to be able to surface every relevant document the next time her oncologist queries the system.

You are running gender-affirming care services at an academic medical center. A patient who began care at age fifteen with a name and sex assigned at birth has, by the time she is twenty-two, formally changed her name (with court order), updated her sex on her driver's license and her insurance card, and asked the clinic to retire her prior name from any chart view that her current providers see. She still wants the clinical history (the labs, the imaging, the procedures) preserved and accessible to her current care team, because some of that history is medically relevant to her ongoing care. She does not want a covering provider, a new front-desk staff member, or a member of her family with limited access seeing her prior name unless there is a specific clinical or legal reason. The matching infrastructure has to make her two identities one record for the purposes of clinical continuity and zero records for the purposes of casual disclosure, and the access-control surface has to know which is which.

You are running a public-health agency that maintains a state immunization registry. Patients are submitted to the registry by every provider in the state, with the demographic data the provider had at the time of the visit. A patient who got her childhood vaccinations under her birth name and her adult booster shots under her married name appears as two registry entries under most matching configurations, and her care team gets a fragmented immunization record that may incorrectly suggest she is overdue for a series she has actually completed. The matcher has to recognize the same person across the name change without getting confused by family members (mother and daughter who share a last name and whose first names may be similar) or by other patients (someone with the daughter's first and last name combination who is not related).

You are running an oncology service line where the patient's longitudinal record carries treatment exposure history that affects every subsequent treatment decision. A patient who was treated for breast cancer at age forty-two under her maiden name, then re-presented at fifty-one with a recurrence after a marriage and name change, then re-presented at sixty-three with a metastatic disease workup under her remarried name, has three primary records with three name variants and one continuous treatment trajectory. Total cumulative anthracycline dose, total cumulative chest radiation, history of cardiotoxicity, hormone-receptor status, prior surgical margins. Every one of those data points lives in records that carry one of the three name variants, and missing any of them changes the treatment plan in ways that range from suboptimal to actively dangerous.

You are running insurance verification for an internal medicine practice that participates in a Medicare Advantage plan. A patient whose name on her Medicare card is "Mary Catherine Wilson" has been seeing the practice for fifteen years under "Mary Wilson" and her chart still says so. Her commercial insurance, before she aged into Medicare, was under "Mary C Wilson," and her old payer claims feed (which still drives some retroactive analytics) carries that variant. Her PCP knows her as Mary. The eligibility verification step at every visit has to reconcile the name across her Medicare member ID, her chart, and her active claim feed, and any analytics that combine her pre-Medicare and post-Medicare claims have to recognize the continuous identity across the name format change.

You are running quality measurement for an accountable-care organization. The HEDIS and CMS quality measures depend on a continuous longitudinal record per attributed patient. Patients who change their name between the measurement-year start and end (or who have changed it within the look-back window for measures with multi-year windows) accumulate two records in the underlying matching infrastructure unless the longitudinal matcher recognizes the change. Both records appear in the denominator of some measures and miss the numerator events that happened under the other name; the result is a quality-measurement number that is artificially low (the denominator includes both records, the numerator credits only one). At population scale, the cumulative undercount can move the institution's reported quality enough to affect contract performance.

You are operating a TEFCA QHIN. The query that comes in from a participating organization carries a name-and-DOB-and-address payload. Your matcher evaluates the query against your local population and finds a high-confidence match. The local record carries a prior-names list with three entries. The query payload's name matches one of the prior names but not the current name. The system has to decide whether to release the current data (which is under the current name), what to do about the prior-name match in the response (acknowledge the prior name as part of the match evidence, or filter it out), and how to record the audit trail in a way that respects the patient's autonomy over their own identity history. None of these are technical questions; all of them shape what your matcher and your release pipeline have to do.

You are doing outcomes research on a cohort that was defined in 2018 from claims and clinical data, and you are now refreshing the cohort in 2026 with eight years of additional follow-up. A non-trivial fraction of the original cohort has changed their name in the intervening eight years; some of those name changes were captured by the matchers running in the meantime, some were not. The 2026 refresh has to recognize the same patients across whatever name changes occurred and not double-count them in the cohort. The same is true for the comparison group, which has its own attrition and its own name-change events.

This is the recipe. Longitudinal patient matching across name changes is the entity-resolution problem of "given two records that may have different names but otherwise look like the same person, are they the same person, and if so, how do we represent the time-varying name in a way that preserves clinical continuity, supports the operational queries we need to run, respects the patient's autonomy over how their identity is presented, and survives the multi-decade lifecycle that healthcare data routinely operates over." The matching core is the same probabilistic-record-linkage stack from earlier recipes. Every layer above the core (the data model, the audit posture, the access controls, the review tooling, the operational discipline) is different.

It is in the complex tier because the technical problem is genuinely temporal (a record's name on a date in the past is one fact, a record's name today is a different fact, and the match has to operate over both), the consent-and-sensitivity layer is unavoidable (especially for gender-transition cases), the historical retrofit complexity is large (most institutions have years of data that pre-date their current name-change handling and need to be reconciled retroactively), and the failure modes range from clinical-safety to dignity-of-the-patient in ways that the earlier recipes did not encounter at the same intensity.

Let's get into how you build it.

---

## The Technology: Time-Aware Identity Resolution

### Why Names Are Not What You Think They Are

In recipe 5.1, a record's name is a string. The matcher compares it to another string and produces a similarity score. The score feeds the probabilistic combiner, which produces a match decision. That model works for the case where the two records were created close enough in time that the same name was current for both. The model breaks for the case where the two records were created at different times under different names that both belonged to the same person.

The fix is not a tolerance adjustment. The matcher cannot get smart enough to recognize "Catherine Wilson" and "Catherine Hernandez" as the same person on the basis of demographic data alone, because at the level of the matcher, those are two different names belonging to two people who happen to share other features, and the population is large enough that the matcher will routinely encounter actual pairs of people who match on those other features and have those names. The fix is to represent the patient's name as a time-varying attribute, with a history of name spans that each cover a date range, and to make every comparison aware of which name the patient was using during the interval the comparison record was created.

A patient is one identity. The identity has a current name. The identity has zero or more prior names, each with an effective span (the date range during which the prior name was current). The identity has zero or more aliases (alternative names that were never the legal name but appear in records anyway, like a hyphenated form recorded inconsistently or a nickname that was used in registration). The identity has zero or more sensitivity flags governing how the prior names may be displayed and to whom (the gender-transition case is the most common; the witness-protection case is the most extreme). The identity also has the standard demographic features that the rest of the matching infrastructure already uses: DOB (which is usually stable, with rare exceptions for refugees with reconstructed identities), sex assigned at birth (which is a separate field from current sex / gender, and which may be relevant or irrelevant depending on the use case), addresses (which change for their own reasons and feed recipe 5.3), phone numbers, SSN where collected, prior MRNs from systems the patient was previously in.

The matcher works against this temporal-identity model rather than against a flat name field. A new record arriving with name "Catherine Hernandez" matches against the identity's current name, against each prior name (with the comparison weighted by the temporal proximity of the prior name's span to the new record's encounter date), and against any aliases. The match score combines all of these comparisons, not just the comparison to the current name. A new record arriving with name "Catherine Wilson," dated five years ago, matches against whichever name was current for the identity five years ago (which might be "Wilson" if the change happened four years ago, in which case the comparison is to the current-as-of-then name and is a strong signal; or it might be the current name if the change happened more than five years ago, in which case the comparison is to a now-prior name and is also a strong signal; the temporal alignment is what makes the comparison work).

The model has implications beyond the matcher. The chart-rendering layer has to know which name to display for a historical document (the name the patient had when the document was created, the patient's current name, or both, depending on the audience and the sensitivity flags). The audit log has to record what name was used in what query, and which version of the identity's name history was active when the query was answered. The release-of-information process has to know which names to include when responding to an outside request, which to suppress (because of sensitivity flags or jurisdictional rules), and which to acknowledge in the cover letter without exposing them in the released documents. None of these decisions can be made by the matcher; the matcher produces the linkage, and the rendering, audit, and release layers consume it with awareness of its temporal structure.

### What the Time-Varying Name Model Has to Capture

A working model has at least seven dimensions that a flat name field does not.

**Effective span.** Each name (current or prior) has a from-date and a through-date, in the patient's reference frame. The current name's span is open-ended on the through-date. Prior names have a through-date that corresponds to when the change took effect (legally, administratively, or by patient self-report; the three may differ).

**Source.** The name change was reported by some entity. The patient (verbal or written self-report at registration). The patient's authorizing document (court order, marriage certificate, divorce decree). A payer's enrollment update (the patient updated her name on her insurance and the eligibility-verification step propagated it). A vital-records update (state vital-records data showing a name change event). A driver's-license verification (the new license was scanned and the matcher detected the change). The strength of the source matters for the matcher's confidence and for downstream audit. A self-reported change with no supporting document is weaker than a court order; both are valid; the matcher's behavior may differ.

**Authority and document references.** Where the source is a document, the document itself (or a reference to it) is part of the identity record. The court-order PDF is in the document store; the identity record points at it. The marriage certificate scan is in the document store; the identity record points at it. The audit trail can reach back to the supporting documents; the release-of-information process may need to disclose them or reference them depending on the request.

**Sensitivity classification.** Some name changes carry no special handling beyond audit. Others carry strong privacy preferences. The patient who changed her name through marriage may not care if her prior name is visible in the chart's name-history widget; the patient who changed her name as part of gender transition may have explicit preferences about who can see the prior name and under what circumstances. The model has to capture the patient's explicit preferences (default-display, restricted-display, masked-display, archive-only) and the system has to enforce them through the access-control layer.

**Cross-reference linkages.** The patient's identity may have prior MRNs in legacy systems that retired, prior member IDs at prior payers, prior employee IDs if she works for the institution. Each of those is part of the identity's history. The cross-reference table from recipe 5.4 (MRN to member ID) and the local-MPI from recipe 5.1 carry their own version of this; the longitudinal-name-change recipe coordinates with them so that a name change updates all the references atomically rather than orphaning some of them.

**Sex and gender as separate, time-varying fields.** The sex-assigned-at-birth is a stable biological attribute that does not change. The current sex / gender on the patient's records is administrative and may change. The chart-rendering layer and the matcher both need access to both, with the awareness that they are different things and that the matching uses the historical-as-of value, not the current value, for historical comparisons. <!-- TODO: confirm at time of build; the FHIR US Core implementation guide and various state-level requirements continue to clarify the data-model recommendations for sex-assigned-at-birth, current sex / gender identity, and gender-affirming care administrative needs. -->

<!-- TODO (TechWriter): Expert review A9 (MEDIUM). Architect the four-separate-fields data model from FHIR US Core (sex assigned at birth, current sex / gender identity, pronouns, legal sex on identity documents) as time-varying attributes on the identity record with their own effective-span histories mirroring the time-varying-name model. Specify how the matcher queries the historical-as-of-date value for each field when scoring against historical records; how the chart-rendering layer surfaces the appropriate set of fields for the as-of-date the disclosure is rendering for, with the access-control-envelope evaluation for the as-of-date sensitivity classification; and how a gender-transition name change typically produces a coordinated set of events (name change + current-sex-or-gender-identity update + pronouns update + legal-sex update where applicable + sensitivity-classification setting) processed as a transactional batch through the same TransactWriteItems-plus-outbox pattern as single-event resolutions. -->

**Reversibility and superseding events.** A name-change event can be reversed (a patient who changed her name and then divorced and reverted; a patient whose initial change was recorded incorrectly and was corrected). The model treats name changes as events with their own audit trail rather than as in-place updates to a current-name field. The current name is computed from the event history; superseding events update the computed view without losing the underlying history.

These seven dimensions are not optional. Every production-grade longitudinal-matching system handles all of them, and the gaps in any dimension show up in operational pain over the multi-decade lifecycle of healthcare data.

### Why It Is Harder Than It Sounds

Six structural reasons:

**Historical records often contain only the name that was current at the time, with no link to the present identity.** A chart created in 2009 carries a name that was current in 2009. The system that produced the chart did not know there would be a name change in 2014. The chart sits in the database, indexed under the 2009 name, and the matching infrastructure has to figure out (years later) that this 2009 chart belongs to the patient who is now indexed under the 2024 name. The matcher cannot rely on a forward pointer from the 2009 record to the 2024 identity, because the 2009 record was not aware the 2024 identity existed; it has to discover the linkage by retrospective analysis.

**Supporting documents are unavailable for many name changes.** A patient who self-reports at registration, "I changed my name when I got married, here's my new ID," may not produce the marriage certificate. The receptionist updates the record under the new name and (if the system supports it) records the prior name. The change has no supporting document on file. Years later, the patient appears at a different point in the system under just the new name, and the matcher has to resolve the historical records without a paper trail to confirm the change. The matcher's confidence has to handle the asymmetry between "well-documented change" and "self-reported, undocumented change."

**Family members are a strong confounder, more so than in non-temporal matching.** A name change moves a patient toward (or away from) a family member's name. A daughter who marries and takes her husband's last name now has a different last name from her mother (whom she previously matched closely). A son who is named after his father (Jr) drops the suffix when his father dies and now matches his deceased father's records more closely. A patient who divorces and reverts to her maiden name now has the same last name as her brother and the same first name as her sister-in-law's mother. The matcher has to maintain enough specificity not to merge across family members during these events, which is harder than the static-family-disambiguation case.

**Sensitivity and patient-autonomy considerations are not negotiable.** Gender-transition name changes are the prototypical case but not the only one. Patients in protective custody, patients fleeing intimate-partner violence, patients in witness protection, and patients who simply prefer not to have their prior identity visible all impose constraints on how the prior name may be presented. The architecture has to enforce the constraints at the rendering, audit, and release layers without making the matcher itself unable to find the linkage. The constraint is "the system knows the linkage; specific users may not know the linkage"; that distinction is operationally meaningful and architecturally non-trivial.

**Cross-organizational reach magnifies every failure mode.** Within one organization, a wrong name-change linkage produces an internal data error that the local matcher can review and correct. Across organizations, a wrong linkage propagated through the HIE or through TEFCA produces an exchange artifact that travels into other organizations' charts, and the original organization no longer controls it. Conservative thresholds and explicit reversibility are operationally necessary. The architecture has to be designed for the case where a linkage was wrong and has to be retracted from systems that have already consumed it.

**The retrofit problem is enormous.** Most institutions did not have a working time-varying-name model when they deployed their EHR. The early years of records carry only the name that was current at the time. The middle years may carry a partial prior-names list that was filled in inconsistently. The recent years carry a full history. Standing up the longitudinal-matching pipeline involves a one-time backfill that has to reconcile decades of records under whatever name conventions were in force at each point. The backfill is not a technical project; it is an organizational change-management project with technical scaffolding.

### Where the Field Has Moved

A few practical updates worth knowing:

**Gender-affirming care has become a first-class data-model concern.** Until recently, most EHR vendors treated sex as a single field with a small set of values. The current state-of-practice (and increasingly the regulatory expectation) is that sex assigned at birth, current sex / gender identity, pronouns, and legal sex on identity documents are four separate fields with their own update lifecycles. <!-- TODO: confirm at time of build; the FHIR US Core implementation guide and the ONC USCDI versioning continue to clarify the requirements; major EHR vendors have been updating their data models on a rolling basis. --> The longitudinal-name-change recipe sits adjacent to this evolution: a gender-transition name change is one event that intersects with the broader gender-identity data model, and the architecture has to coordinate.

**FHIR's `Patient.name` is a list, not a string.** The FHIR Patient resource models name as a list of HumanName resources, each of which has its own use code (official, usual, nickname, anonymous, old, maiden), period (effective span), and text-and-component representation. <!-- TODO: confirm at time of build; the FHIR R4 Patient resource is normative and the HumanName datatype has been stable for several versions. --> An institution that lands its data in a FHIR-native data lake gets the time-varying-name structure for free at the schema level; the matcher and the rendering layer still have to use it correctly. Most operational EHRs internally represent names with similar (if vendor-specific) structures, but the externalized representation is often a flat current-name field unless the integration explicitly preserves the history.

**State-level vital-records integration is uneven but growing.** State vital-records agencies maintain authoritative records of legal name changes through marriage, divorce, and court order. In some states the data is available to healthcare organizations through structured feeds (often through the public-health-reporting infrastructure); in others it is not directly available and the institution has to rely on patient self-report and document review. <!-- TODO: confirm at time of build; the state-level landscape varies; most states do not provide direct healthcare-organization access to vital-records-name-change data, but some have piloted programs. --> The recipe is designed to incorporate vital-records feeds where they exist and to operate without them where they do not.

**Information-blocking obligations apply here too.** The 21st Century Cures Act information-blocking provisions require that an institution provide a patient's records on request, regardless of which name the records were created under. Refusing to release records that exist under a prior name (or filtering them out of a release because the request specified the current name) is increasingly characterized as information blocking. The release-of-information process has to recognize the linkage without violating the patient's preferences about how their prior name is referenced; this is operationally subtle. <!-- TODO: confirm at time of build; the information-blocking exceptions and their applicability to name-change scenarios continue to be clarified through enforcement actions and FAQ guidance. -->

**Equity and disparity monitoring is increasingly specified.** Patient-matching equity research has consistently found that name-handling errors are not uniform across demographic groups. Names from naming traditions that English-language registration systems handle poorly (Spanish double surnames, Asian family-name-first conventions, Arabic patronymics, names with diacritics) accumulate variations at higher rates and produce more match errors. Patients who change their name (disproportionately women in many U.S. populations; transgender patients across all populations) experience more match errors than patients with stable names. The cohort-stratified accuracy monitoring that was built for recipes 5.1, 5.4, and 5.5 carries forward here, with name-change-specific cohort axes layered on top. <!-- TODO: confirm at time of build; the Pew, ONC, RAND, and Sequoia Project literature on patient-matching equity continues to expand. -->

**Patient-mediated identity is changing the data sources.** As the CMS Patient Access API and Patient-Facing-App ecosystems mature, the patient is increasingly the connecting tissue between their own records across organizations. A patient who has connected her records to a personal-health-record app under her current name can authorize the app to retrieve records from organizations that knew her under her prior name; the app does the linkage on her behalf, with her authentication serving as the strong identifier that supplements the demographic match. The patient-mediated path is becoming a real architectural pattern, particularly for the cross-organizational long-horizon case. <!-- TODO: confirm at time of build; the Patient Access API ecosystem has expanded substantially since the CMS Interoperability Final Rule went into effect, and patient-mediated linkage is increasingly viable. -->

---

## General Architecture Pattern

The pipeline has six logical stages: ingest the demographic update or new record, detect a candidate name-change event, evaluate the candidate against the patient's existing identity record, persist the temporal-name update with audit and sensitivity metadata, propagate the linkage to dependent stores, and react to events that supersede prior linkages (correction, reversal, identity merge, sensitivity-flag update).

```
┌────────────── INGEST ─────────────────────────────┐
│                                                    │
│  [Trigger sources]                                 │
│   - Registration update at the front desk          │
│     ("I changed my name; here's my new ID")       │
│   - Inbound payer eligibility refresh with        │
│     updated name                                   │
│   - Vital-records feed (where available)          │
│   - Cross-organizational match refresh            │
│     (recipe 5.5) carrying a name discrepancy      │
│   - Document upload: court order, marriage cert,  │
│     divorce decree, driver's license scan         │
│   - Patient-facing app connection (the patient    │
│     authenticated under her current name and      │
│     authorized retrieval from prior records)     │
│   - Bulk historical-records reconciliation         │
│     (one-time backfill or periodic refresh)      │
│           │                                        │
│           ▼                                        │
│  [Land the trigger record:                         │
│   - source_type, source_record_id                 │
│   - asserted_name (the new name in the trigger)   │
│   - asserted_change_date (if known)               │
│   - asserted_prior_name (if the trigger carried   │
│     one)                                          │
│   - supporting_document_reference (if any)       │
│   - patient_self_assertion_flag,                  │
│     authoritative_source_flag,                    │
│     consent_for_change_flag]                      │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── DETECT ─────────────────────────────┐
│                                                    │
│  [Name-change candidate detection:                 │
│   - Direct case: trigger record explicitly         │
│     asserts a name change (the patient said so,   │
│     the document says so, the payer's update      │
│     event says so)                                 │
│   - Indirect case: trigger record has new name +  │
│     existing record has different name + other    │
│     demographics align strongly enough to suggest │
│     same identity                                  │
│   - Detection score combines:                     │
│       - Demographic-feature match strength on     │
│         non-name fields (DOB, address, phone,     │
│         SSN where present)                        │
│       - Name-pair plausibility (the new name      │
│         is a plausible legal-change variant of    │
│         the prior name: surname change with       │
│         shared first/middle, hyphenation, suffix  │
│         drop, transliteration variant)            │
│       - Source strength (a court-order document   │
│         beats a verbal patient assertion)         │
│       - Temporal plausibility (the asserted       │
│         change date is consistent with the        │
│         records' creation timeline)]              │
│           │                                        │
│           ▼                                        │
│  [Output: detection envelope including candidate  │
│   identity, asserted name change, evidence        │
│   summary, detection confidence]                   │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── EVALUATE / RESOLVE ─────────────────┐
│                                                    │
│  [For each candidate identity:                     │
│   - Look up the existing temporal-name record     │
│   - Score the asserted change against:           │
│       - Existing current name and its span        │
│       - Existing prior names and their spans      │
│       - Existing aliases                          │
│       - Demographic features as of the assertion  │
│         date                                       │
│       - Document-source strength of any           │
│         supporting evidence                        │
│   - Apply confidence thresholds calibrated for    │
│     the name-change-specific scoring (separate    │
│     from the demographic-match thresholds in 5.1):│
│     - >= NAME_CHANGE_HIGH: confident name change; │
│       update the identity's temporal-name record │
│       atomically                                  │
│     - >= NAME_CHANGE_MED: probable change;       │
│       record as pending; surface to review        │
│       queue if patient-self-assertion alone      │
│       (no document)                               │
│     - <= NAME_CHANGE_REJECT: not a name change;   │
│       likely a different person matching some    │
│       features                                    │
│     - in between: name-change review queue;       │
│       hold the assertion in pending state]       │
│           │                                        │
│           ▼                                        │
│  [Output: change resolution decision and         │
│   pending-state envelope, with all evidence       │
│   preserved for audit and review]                 │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── SENSITIVITY + CONSENT ──────────────┐
│                                                    │
│  [Apply patient-preference and policy filters:    │
│   - Patient preferences for prior-name display    │
│     (default-display, restricted-display,         │
│     masked-display, archive-only)                 │
│   - Sensitivity classification of the name        │
│     change (gender-affirming, protective-custody, │
│     intimate-partner-violence relocation, none)  │
│   - Default access scope for the prior name      │
│     (treatment, payment, operations, research,    │
│     patient-access-API release; some scopes may  │
│     be blocked entirely for restricted classes)  │
│   - Cohort/jurisdiction policy overlays (state    │
│     law, institutional policy, HIE participation │
│     agreement constraints)]                      │
│           │                                        │
│           ▼                                        │
│  [Output: access-control envelope on the prior    │
│   name and on the linkage itself]                 │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── PERSIST + AUDIT ────────────────────┐
│                                                    │
│  [Identity record:                                  │
│   - identity_id (the institution's stable          │
│     internal patient identifier)                   │
│   - current_name (with effective_from)             │
│   - prior_names (each with effective_from,         │
│     effective_through, source, document_ref,      │
│     sensitivity_class)                             │
│   - aliases (with same metadata)                   │
│   - linked_local_mrns (current and historical)    │
│   - linked_member_ids (current and historical)    │
│   - sex_assigned_at_birth (stable)                 │
│   - current_sex_or_gender (with history)           │
│   - access_control_envelope on each prior name    │
│   - resolved_at, resolved_by, source_record_id]   │
│           │                                        │
│           ▼                                        │
│  [Audit log entry for every change: who/what       │
│   asserted the change, what evidence supported    │
│   it, what threshold tier the decision fell in,   │
│   what prior identity state was superseded]      │
│           │                                        │
│           ▼                                        │
│  [Emit identity_name_change_resolved event for     │
│   downstream consumers]                            │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── PROPAGATE ──────────────────────────┐
│                                                    │
│  [Subscribe consumers update their derived state:  │
│   - Local MPI (recipe 5.1) updates the patient's │
│     master record                                  │
│   - Cross-reference table (recipe 5.4) updates    │
│     MRN-to-member-ID mappings if changed          │
│   - Cross-facility matcher (recipe 5.5) refreshes │
│     prior-name handling for query responses       │
│   - Claims-clinical linkage (recipe 5.6) re-      │
│     evaluates encounter clusters whose patient   │
│     resolution depended on the name              │
│   - Chart-rendering layer refreshes its name-    │
│     display logic                                  │
│   - Release-of-information workflows incorporate  │
│     the updated name history                       │
│   - Quality-measurement and risk-adjustment       │
│     pipelines deduplicate the records under the  │
│     unified identity                              │
│   - Care-coordination and patient-portal          │
│     services pick up the change]                  │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── INVALIDATION / SUPERSEDE ───────────┐
│                                                    │
│  [Subscribe to events that supersede prior        │
│   resolutions:                                     │
│   - Correction event (the change was recorded     │
│     incorrectly; a court order was misread; a    │
│     reviewer overturned an automated decision)   │
│   - Reversal event (the patient changed back; a   │
│     marriage was annulled; an interim change     │
│     was rolled back)                              │
│   - Identity merge from recipe 5.1 (two           │
│     identities are now one; both name histories   │
│     fold into the surviving identity)             │
│   - Identity unmerge (a wrong merge is being     │
│     reversed; name history splits accordingly)   │
│   - Sensitivity-class update (the patient's      │
│     preference for prior-name display has         │
│     changed)                                      │
│   - Document-strength upgrade (a previously      │
│     self-reported change is now backed by a      │
│     supporting document)                           │
│   - Cross-organizational match invalidation      │
│     (recipe 5.5 retracted a linkage that         │
│     affected the prior-name handling)]           │
│           │                                        │
│           ▼                                        │
│  [Re-evaluate the affected identity records;      │
│   emit identity_name_change_invalidated events    │
│   so propagation consumers refresh accordingly]  │
│                                                    │
└────────────────────────────────────────────────────┘
```

**The detection step is the load-bearing addition versus recipe 5.1.** A flat-name matcher does not need a name-change detector because it treats every name as the value-of-the-day. The temporal model needs an explicit detector because the addition of a new name to an existing identity is structurally different from a new record matching an existing identity. The detector handles both the direct case (an explicit assertion of a name change) and the indirect case (a high-demographic-match record arriving with a different name from the matched identity). The indirect case is the dominant operational path and is the one that institutions tend to under-invest in.

**Threshold calibration is name-change-specific.** Re-using the recipe 5.1 thresholds for name-change decisions produces either too many false-merges (the threshold was calibrated for new-record-vs-existing comparisons where the names usually match, and a name-changed comparison fails it) or too many missed name changes (the threshold is loose enough that name changes get accepted, but the matcher then over-merges across family members or across actual different patients with similar features). The right thresholds for name-change events are derived from a separate calibration set that includes confirmed name-change events, near-miss family-disambiguation cases, and known-incorrect linkages. Same chapter pattern as 5.1, 5.4, 5.5; the parameters and the gold-set composition differ.

**Sensitivity classification is set per-event, not per-identity.** A patient may have multiple name changes over a lifetime, with different sensitivity classifications for each. A divorce that reverts to a maiden name may have no special sensitivity, while a subsequent legal name change associated with gender transition has explicit privacy preferences. The model carries the classification at the prior-name level, not at the identity level, because a single identity can have prior names with different sensitivity treatments.

**Access controls operate on the prior name, not on the identity.** The architecture assumes that the system always knows the linkage between current and prior names; specific users may or may not see the prior name based on their role, the sensitivity classification, the access purpose, and the patient's preferences. Hiding the linkage from the system itself defeats the matcher's job; hiding the prior name from the user surface is a presentation-and-access-control concern. The two are distinct. Same chapter pattern as 5.5's sensitivity-filter approach.

**Patient-self-assertion is a valid source but a weaker one.** The matcher accepts patient-self-assertion as a source for name-change events but treats it differently from document-backed assertions. Self-assertion alone may be enough for high-confidence resolution when the demographic features otherwise match strongly and there is no conflicting evidence; it may not be enough when the demographic match is medium-confidence or when there is conflicting evidence (a prior payer record under a different name with no overlap). The architecture supports a pending state for self-asserted changes and a confirmation pathway when supporting documents are eventually provided.

**Document evidence has its own retention.** When a court-order PDF or marriage-certificate scan is provided as supporting evidence for a name change, the document itself goes into the institution's document store with its own retention and access-control posture, and the identity record points at it. The retention floor for these documents is typically the longer of the institution's general medical-records retention and the regulatory floor for identity-related documents. The audit trail on the identity record references the document; the document itself is not duplicated into the identity record.

**Reversibility is not a feature; it is the architecture.** A name-change event can be wrong, and the architecture has to support cleanly retracting it. The temporal-name record carries an event history, not just a current state; superseding events update the computed view without losing the underlying history; downstream consumers receive invalidation events that allow them to refresh derived state. Skip the reversibility pathway and a wrong name change becomes a permanent data corruption that the organization cannot fully clean up. <!-- The reversibility pathway is the same pattern as the audit-and-unmerge pathway in recipe 5.1; the difference here is that name changes are more frequent than full identity merges and the reversibility has to be operational on a routine basis. -->

**Cohort-stratified accuracy monitoring applies here too.** Name-change handling accuracy is not uniform across patient cohorts. Patients with names from non-dominant-culture naming traditions experience more matcher errors. Transgender patients experience higher rates of operational friction that affect care experience even when the matcher itself is technically correct. Per-cohort match-rate, per-cohort error-rate, and per-cohort review-queue-aging are the right metrics; per-cohort thresholds and disparity alarms are the right monitoring.

<!-- TODO (TechWriter): Expert review A1 (HIGH). Promote cohort-stratified accuracy monitoring into a paragraph specifying: cohort axes (name-tradition cohort, transgender-or-gender-diverse cohort with patient-consented self-identification only, name-change-frequency cohort, age-of-name-change cohort); per-cohort metrics and cadence (name-change detection rate weekly, name-change false-acceptance rate weekly, review-queue aging weekly, sampled error rate monthly); disparity calculation as absolute difference between best-rate and worst-rate cohort per metric per cycle; alarm thresholds (detection-rate disparity > 0.05 = MEDIUM, false-acceptance-rate disparity > 0.01 = HIGH); routing to analytics governance committee, equity-monitoring committee, and patient-experience-and-dignity committee with 5-business-day SLA; remediation pathway with explicit dignity-stakes-disparity translation (cohort-disparity metrics in this recipe measure how disparately one cohort's patients experience friction in registration, clinical-record-rendering, and release-of-information workflows). Same chapter pattern as 5.1, 5.4, 5.5 cohort monitoring. -->

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter05.07-architecture). The Python example is linked from there.

## The Honest Take

Longitudinal name-change handling is the recipe in this chapter where the technical complexity is moderate and the human-and-organizational complexity is enormous. The matching techniques are familiar (you have seen the same probabilistic-record-linkage core in every recipe of this chapter, with the time-aware extension that this recipe layers on top). The orchestration is familiar (Lambdas, Glue jobs, Step Functions, EventBridge, the same pattern as the other identity-pipeline recipes). The thing that makes this recipe hard is that names are not just strings; they are part of how a patient is known to herself, to her family, to her providers, and to the systems that record her care. Mishandling a name change is not a data-quality bug; it is a dignity failure that the patient experiences directly, sometimes repeatedly, sometimes for years. The job of the architecture is to produce continuity of clinical record without producing dignity failures, and the discipline that takes is operational and organizational at least as much as it is technical.

The trap most specific to longitudinal name-change handling is treating it as an exception case. Name changes are not exceptional events. In a population of one million patients followed over a multi-decade horizon, the cumulative name-change rate is high enough that an institution that has built its identity infrastructure on the assumption of stable names will, by year ten, have a longitudinal record that is silently fragmented for a substantial fraction of its long-term patients. The fragmentation does not surface in the daily registration workflow; it surfaces when a clinician needs to make a treatment decision based on cumulative history, when an analytics team needs to compute a quality measure with a multi-year lookback, when a research team needs to define a cohort across a follow-up window that spans a name change. By the time the fragmentation surfaces, the institution has decades of records to retrofit. Build the time-varying-name model from the beginning; the retrofit cost is much higher than the up-front cost.

The second trap is over-trusting front-desk-asserted name changes without supporting documents. Front-desk staff, under time pressure, with patients who have varying levels of documentation on hand, are not in a position to verify a name change rigorously. Most front-desk-asserted changes are correct (patients tell the truth about their own names), but the fraction that are not (someone else's insurance card used at registration; a name typed wrong with the typo persisting; a confused patient who reported a name change that did not legally happen) is large enough that auto-accepting all of them produces wrong linkages at scale. The right pattern is to record front-desk assertions, accept them provisionally for the encounter at hand, and require supporting evidence for the linkage to become canonical. The patient-portal upload path makes this workable; without it, the operational burden falls on the medical-records team and the queue ages.

The third trap, related: under-investing in the patient-portal flow for name-change documentation. The asynchronous upload path is the lowest-friction way to get supporting documents on file, and the institutions that build it well have substantially better operational metrics than the institutions that rely on document upload at the front desk. Treat the patient-portal flow as a first-class architectural component, not an afterthought.

The thing that surprises people coming from other identity-pipeline backgrounds is how much of the operational load is in the sensitivity layer rather than in the matcher itself. Recipe 5.1's matcher cares about whether two records refer to the same person; recipe 5.7's matcher cares about that and about whether the two records' name relationship is appropriate to surface to a given user, in a given context, under the patient's expressed preferences. The matcher is not deciding what to display; it is deciding what is true. The display decision lives in the access-control envelope, which is consulted by every consumer that reads the identity record. The split-of-concerns is correct (it lets the matcher do its job without being entangled in display logic), but it requires architectural discipline to maintain. Most teams initially put display logic in the matcher and have to refactor when the sensitivity requirements grow.

The thing about gender-affirming-care patients: their experience of the system is, in most institutions, substantially worse than the experience of cisgender patients with otherwise comparable care needs. The reasons are operational, not algorithmic. The chart-rendering layer surfaces the prior name in places it should not. The release-of-information process includes the prior name in disclosures the patient did not consent to. The provider directory shows the prior name to colleagues who do not need it. Each of those is an architecture-and-process problem, not a matcher problem. Building the longitudinal name-change recipe well requires explicit collaboration with the gender-affirming-care service line (where it exists) or with patient-advocacy groups (where it does not), and treating the sensitivity layer as a load-bearing requirement rather than a checkbox.

The thing about names from non-dominant-culture naming traditions: the matcher's reference data is the dominant source of cohort-disparity. Nickname dictionaries that were compiled from English-language sources do not handle Spanish nicknames, Arabic kunyas, or Chinese pet names. Surname-change-pattern models that were trained on Western European marriage conventions do not handle Spanish double-surname systems, Korean clan-name conventions, or Arabic patronymic structures. Transliteration maps that were built for one script-pair often miss the variations that arise in cross-language registration. The institutions that take cohort equity seriously invest in per-tradition reference data and in collaboration with the communities they serve to maintain it. The institutions that do not invest in this discover the disparity when their cohort-stratified accuracy monitoring surfaces it, which is later than they would have liked.

The thing about historical retrofit: do it deliberately, with patient communication, and with the assumption that some fraction of the candidate linkages are wrong. The backfill is a one-time chance to clean up decades of records, but the backfill operates on records that were created without the time-varying-name model in mind, and the evidence available at backfill time is necessarily thinner than the evidence available at the time of each original name change. Use the patient-portal flow to surface candidate linkages to the patient for confirmation where possible; use conservative thresholds for auto-acceptance during the backfill and route ambiguous cases to review; communicate the back-fill behavior to the analytics consumers who will see their data refresh as the backfill progresses. The first version of the backfill that does not respect any of these will produce a "merge wave" that fragments more than it consolidates and undermines confidence in the longitudinal record for years.

The thing about cross-organizational propagation: most institutions cannot fully solve this on their own. A name change recorded at organization A propagates to organization B only through one of three pathways: the patient updates her record at organization B in person, the cross-facility refresh path detects the discrepancy at query time, or the patient-mediated flow propagates the change through a personal-health-record app. Each pathway has its own latency and its own coverage gaps. The institutions that operate in mature regional HIE ecosystems get the cross-org refresh more reliably than institutions in less-mature regions. The patient-mediated flow is increasing in importance as the Patient Access API ecosystem matures; treat it as a strategic investment rather than a tactical convenience.

The thing about reversibility: the institutions that build the invalidation pipeline first have substantially better operational outcomes than the institutions that build the resolution pipeline first and add invalidation later. The invalidation pipeline forces the architecture to treat name-change events as data with a lifecycle, not as in-place updates. The institutions that skip the invalidation pipeline initially discover, when the first wrong resolution surfaces, that retracting it cleanly is more work than they planned for; the institutions that build invalidation first treat retractions as routine.

The thing I would do differently the second time: invest in the access-control envelope as a versioned, queryable artifact from day one. The first version of the recipe will treat the envelope as a small bag of policy fields attached to each prior-name event. The second version will recognize that the envelope has its own lifecycle (patient-preference updates, jurisdictional-policy changes, sensitivity-class upgrades, audit-rule modifications) and needs versioning, history, and a query API. The envelope is consulted by chart-rendering, release-of-information, patient-portal, audit, and analytics consumers; treating it as an undifferentiated bag of fields produces ad-hoc display logic that is hard to govern. Build the envelope as a first-class concept from the beginning.

<!-- TODO (TechWriter): Expert review A3 (MEDIUM). Promote the access-control envelope to a versioned, queryable artifact in the persistence schema and the architecture pattern. Specify two write paths (per-event envelope assignment from the sensitivity step produces a reference to a versioned envelope; envelope updates produce a new envelope version with a forward-only-disclosure-update framing) and three read paths (chart-rendering reads the envelope-as-of-now for the requesting context; release-of-information reads the envelope-at-disclosure-time for the audit log; patient-portal-audit-summary-delivery reads the envelope-history for the time-window display). The envelope-versioning store is a separate DynamoDB table keyed on `(envelope_id, version)` with the current-version pointer in a GSI; consumers query by envelope_id and consume current or specified historical version. The envelope-update event flows through the same outbox-and-EventBridge-fan-out pattern as the name-change resolution, with the same access-control-aware routing. -->

The thing about audit volume: the audit log for a sensitivity-classified name change is heavier than for a general one, by design. Every disclosure of the prior name is logged. Every query that touches the prior name is logged. The patient may have explicit preferences for monthly summaries delivered to her portal. The audit volume can grow surprisingly fast for restricted-class patients, and the audit-retention costs are non-trivial at population scale. Plan the audit-storage tier explicitly (S3 Glacier Deep Archive after 90 days is typical), the per-class retention floor explicitly, and the audit-query path explicitly so it does not collide with the operational read path. <!-- TODO: confirm at time of build; the per-state and per-jurisdiction audit-retention rules for sensitivity-classified records continue to evolve. -->

Last point, because it is specific to the regulatory context: the information-blocking obligation cuts both ways. The institution is obligated to release a patient's records on request, including records under prior names, but the patient also has the right to constrain how her prior names are referenced in disclosures. The release pipeline has to honor both obligations simultaneously, and the resolution between them is per-patient, per-context, per-disclosure. Build the release pipeline with the access-control envelope in scope from day one, not as a retrofit. The architecture is then load-bearing for compliance and for patient dignity in the same operational layer, which is the right place for both.

---

## Related Recipes

- **Recipe 5.1 (Internal Duplicate Patient Detection):** The local MPI is the canonical patient identity that the longitudinal-name-change recipe maintains. Identity merges from 5.1 propagate through this recipe's invalidation pipeline; name-change resolutions from this recipe propagate to the local MPI's master record.
- **Recipe 5.2 (Provider NPI Matching):** Providers also experience name changes (less frequently than patients, but they happen). The same architectural pattern applies to provider-name handling, with NPI as a stronger anchor that simplifies the matching but does not eliminate the time-varying-name need.
- **Recipe 5.3 (Address Standardization and Household Linkage):** Address consistency is a strong demographic feature in the name-change detector; recipe 5.3's address pipeline supplies the standardized addresses that the detector compares as-of-date. Household-linkage data feeds the family-disambiguation rules variation.
- **Recipe 5.4 (Insurance Eligibility Matching):** Payer eligibility refreshes are one of the most reliable trigger sources for name-change detection (the patient updated her name on her insurance and the eligibility refresh carries the new name). The cross-reference table from recipe 5.4 is updated through the propagation pipeline when a name change resolves.
- **Recipe 5.5 (Cross-Facility Patient Matching):** Cross-organizational queries against an HIE may surface name discrepancies that this recipe's indirect-detection path consumes; cross-facility match invalidation events from 5.5 feed this recipe's invalidation pipeline.
- **Recipe 5.6 (Claims-to-Clinical Data Linkage):** Encounter-cluster-to-clinical-encounter linkages whose patient resolution depended on the prior name need to be re-evaluated when a name change resolves; the propagation queue from this recipe triggers the re-link in 5.6.
- **Recipe 5.8 (Privacy-Preserving Record Linkage):** Tokenization-based linkage produces different tokens for pre-change and post-change records; the token-pair-history layer (a variation above) maintains the longitudinal continuity in the privacy-preserving setting.
- **Recipe 5.9 (National-Scale Patient Matching):** TEFCA-mediated identity resolution at national scale carries the same name-change challenges magnified; the QHIN-to-QHIN exchange of identity-update events is the cross-organizational extension of this recipe at national scale.
- **Recipe 5.10 (Deceased Patient Resolution):** Deceased-patient events from 5.10 may surface previously-unknown name changes (a death record that carries a name different from the institution's current record for the same identity); the recipes coordinate so that the death-record reconciliation does not produce a false-positive name-change resolution.
- **Recipe 1.6 (Handwritten Clinical Note Digitization):** Handwritten notes from prior decades may surface names different from the current canonical name; the recipe's historical-record retrofit consumes the digitized notes as evidence for backfill.
- **Recipe 1.10 (Historical Chart Migration):** Migrating paper or legacy-system charts surfaces records under names that may not be in the current institution's name history; the migration's matcher hands off to this recipe's resolution path.
- **Recipe 2.6 (Clinical Note Summarization):** Notes referencing the patient by name may be regenerated under the current name (or kept under the original name with a sensitivity-aware overlay) depending on the access-control envelope; the summarization service consumes the envelope at render time.
- **Recipe 7.x (Predictive Analytics):** Cohort definitions for risk-scoring depend on the unified longitudinal identity; missed name-change linkages produce fragmented cohorts and biased model training. The longitudinal-name-change recipe is upstream of every multi-year predictive-analytics use case.

---

## Tags

`entity-resolution` · `record-linkage` · `longitudinal-matching` · `name-change` · `temporal-identity` · `time-varying-name` · `master-patient-index` · `mpi` · `empi` · `gender-affirming-care` · `sensitivity-classification` · `access-control-envelope` · `fhir` · `humanname` · `patient-resource` · `dynamodb` · `lambda` · `glue` · `step-functions` · `eventbridge` · `sagemaker` · `healthlake` · `lake-formation` · `event-driven` · `complex` · `production` · `hipaa` · `information-blocking` · `cures-act` · `equity-monitoring` · `cohort-stratified-accuracy` · `vital-records` · `patient-portal` · `audit-archive`

---

*← [Recipe 5.6: Claims-to-Clinical Data Linkage](chapter05.06-claims-to-clinical-data-linkage) · Chapter 5 · [Next: Recipe 5.8 - Privacy-Preserving Record Linkage →](chapter05.08-privacy-preserving-record-linkage)*
