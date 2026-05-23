# Recipe 5.9: National-Scale Patient Matching (TEFCA) ⭐⭐⭐⭐

**Complexity:** Complex · **Phase:** Production · **Estimated Cost:** ~$0.0001-0.001 per cross-network identity-resolution decision at national scale, dominated by the federation-routing infrastructure, the cross-network audit-and-attribution overhead, and the multi-organization-governance program rather than per-record matching fees (depends on the institution's role in the network, the volume of cross-network queries the institution participates in, the depth of the institution's cross-network audit retention, and the maturity of the federation framework the institution operates under)

---

## The Problem

It is a Tuesday afternoon in a regional emergency department, and the patient on the gurney in bay 4 was in a single-vehicle accident on a state highway forty miles east of here. She is unconscious. The paramedics found a driver's license with a name and a date of birth and an address that turns out to be three states away. The ED attending wants to know whether this woman has any relevant medical history: a known cardiac condition that would change the trauma workup, an allergy to a contrast agent the radiology team is about to administer, an anticoagulant on her active medication list, a recent surgery whose post-operative course is still unfolding, a pre-existing condition that the trauma team has to factor into the resuscitation. The ED attending types her name and date of birth into the hospital's EHR. The local record store returns nothing. He clicks the button labeled "Search the Network" and waits while the system queries the national health-information exchange for any record that might be the same patient.

What happens behind that button is the recipe. The query goes out from the local hospital's EHR through a federation gateway to a national identity-resolution service that does not itself hold any patient records. The service routes the query, in parallel, to the federated participants that operate at national scale: the regional health-information exchanges in the patient's state of residence and the patient's state of treatment, the federally-operated networks for veterans' care and for federal-employee care if those apply, the national pharmacy data network that holds her dispensing history, the academic-medical-center network that her state's university health system runs, and any of several thousand other participating organizations whose records might cover her past care. Each participant runs the federated query against its own master patient index, returns a candidate list of records that might be the same person, and the federation routes the candidate lists back to the original requester for resolution and presentation. The ED attending sees a unified longitudinal record assembled from twelve facilities across four states, including the cardiology consult at the academic medical center where she was last seen for her atrial fibrillation, the warfarin prescription she is still actively filling at her local pharmacy, and the contrast-allergy note from a CT three years ago at a radiology center she visited once while traveling. The contrast-allergy note is the one that matters for the next ten minutes of her care. Without it, the radiology team gives her contrast and she has the reaction that her record warned about. With it, the team uses an alternative protocol and the workup proceeds without the complication.

This is national-scale patient matching, and the gap between the version that works and the version that does not is the difference between the EDs that can answer the contrast-allergy question and the EDs that cannot. As of writing, both versions are operating in the same country, sometimes in the same metropolitan area, with the same patients moving between them. <!-- TODO: confirm at time of build; the operational maturity of the U.S. national health-information exchange continues to evolve as the Trusted Exchange Framework and Common Agreement (TEFCA) program rolls out and as more participants achieve QHIN designation. -->

The harder versions of the question are everywhere:

You are operating a Qualified Health Information Network (QHIN) under TEFCA. You have signed the Common Agreement, completed the QHIN designation process, and are now responsible for routing patient-discovery and document-query traffic among your participants and across to other QHINs. The query that just came in to your QHIN is for a patient whose demographics do not match cleanly against any single participant's master patient index, but whose demographics combined across participants suggest the patient is in your network under multiple identifiers at multiple participating organizations. The participating organizations have inconsistent positions on which records to release for which use cases under which authorization, and your QHIN's job is to mediate the inconsistencies without introducing new errors and without exposing any participant's authorization posture to any other participant. <!-- TODO: confirm at time of build; the QHIN designation process and the operational specifics of QHIN-to-QHIN routing continue to be defined through the Common Agreement and through the Recognized Coordinating Entity (RCE) at the Sequoia Project. -->

You are running a regional health-information exchange that has historically operated as a state-level utility for hospital and clinic interoperability. The state legislature passed a statute four years ago that authorized your HIE to operate as a TEFCA participant; you have been working through the technical and governance changes that the QHIN framework requires. The Common Agreement specifies how you have to handle cross-QHIN queries (with attribution back to the originating participant, with the appropriate authorization context, with the appropriate audit trail). The state-level governance specifies additional rules that may be more or less restrictive than the federal framework on specific record types. The participating organizations that have been with you since before TEFCA have legacy data-sharing agreements that need to be reconciled with the new framework. The participating organizations that are joining now want to participate in the federal framework directly without the state-level overlay. You are the layer that holds all of this together at the technical level, and the governance overhead exceeds the engineering overhead by a factor that you did not anticipate when you scoped the program.

You are operating a national pharmacy data network whose primary product is real-time dispensing history for clinical-decision-support and prescription-drug-monitoring use cases. Your network has been operational for two decades and has well-established data-use agreements with the dispensing pharmacies that contribute to it. TEFCA has created a new use case for your data: federated identity resolution at population scale, where your dispensing history feeds the cross-network candidate-discovery process for patients whose dispensing record is the strongest signal of their identity (because the dispenser captures more verified demographic data than many other touchpoints, and because dispensing events occur at a regular cadence that produces a richer time-series than most clinical encounters). The new use case requires changes to your matching infrastructure, your audit posture, your authorization framework, and your downstream participant-attribution pipeline. The use case also creates new revenue, but the revenue is back-loaded behind the operational changes that the use case requires.

You are running the master patient index at an integrated delivery network with twenty-three hospitals across six states. Your IDN's MPI has been the load-bearing identity infrastructure for your enterprise data warehouse, your population-health analytics, and your value-based-care contracts. TEFCA participation requires your MPI to be queryable from outside your network through a QHIN intermediary, with the QHIN's authentication and authorization framework rather than your IDN's internal one. The query traffic from outside your network is unbounded; the matching tolerance the QHIN expects (high recall on plausible matches even when the query demographic data is incomplete) is looser than the matching tolerance your internal applications have been calibrated to. Your MPI's responses have to satisfy both audiences, and the operational discipline of running a single matching infrastructure for both internal and external query traffic is more demanding than running two infrastructures, but the cost-and-quality tradeoff that two infrastructures imposes is also non-trivial.

You are operating a national-scale federated research network (a TriNetX, an All of Us, a PCORnet variant) whose participants contribute longitudinal cohort data for research queries. Your network does not exchange identifying data with the participants; the queries are federated and the responses are aggregated. As TEFCA matures, your participants are increasingly under operational pressure to also participate in federated treatment-and-payment-and-operations queries, and the question is whether your research-network infrastructure can be extended to support both use cases under the same governance framework or whether the institutional separation should be preserved. The legal-and-compliance teams at your participants have different opinions about this, the technical capability is roughly the same in both cases, and the governance complexity of running both use cases on the same substrate is the load-bearing question.

You are advising a state Medicaid agency on its TEFCA participation strategy. Medicaid's data-sharing posture is governed by the federal-state-managed-care framework, by the state's specific Medicaid disclosure rules, and by the agency's own administrative posture. TEFCA participation would let the state's Medicaid records flow to clinical-care contexts under the treatment-and-payment-and-operations framework that TEFCA's exchange purposes specify. The state's eligibility-determination workflow could query TEFCA for cross-state coverage information for a Medicaid applicant who recently moved into the state. The state's quality-measurement program could query TEFCA for the longitudinal record of a Medicaid beneficiary across the state's borders. The federal-state-managed-care framework constrains some of these uses; the state's Medicaid disclosure rules constrain others; the agency's administrative posture is still being determined for the rest. You are mapping the use cases to the regulatory framework while the regulatory framework itself is still evolving. <!-- TODO: confirm at time of build; state Medicaid agencies' TEFCA participation strategies continue to develop, with specific use cases authorized through state-level rule-making and through CMS guidance. -->

You are operating a vendor-mediated EHR interoperability service that has been the de facto national network for a particular EHR vendor's customers for years. Your service operates at population scale and handles a substantial fraction of all U.S. patient-record exchange traffic. TEFCA participation positions your service as a QHIN candidate, and the operational integration with the QHIN framework is technically feasible but requires architectural changes that affect every customer. Your vendor's product roadmap, the QHIN framework's evolving requirements, and the customer base's varying readiness all move in different directions, and the program management of the transition is the dominant work for your team for the next several quarters. <!-- TODO: confirm at time of build; the specific commercial-vendor QHIN designations and their operational scope continue to evolve. -->

You are running a national-scale veterans-health-information network whose data spans every U.S. veteran's medical record. The network's participation in TEFCA is governed by federal law that constrains how veteran data may be exchanged and by intra-agency policy that constrains specific record types (mental-health records, substance-use-treatment records under 42 CFR Part 2, certain combat-and-deployment-related records). The QHIN framework's general posture has to be overlaid with the federal-veteran-data-exchange constraints, and the resulting record-release posture is more restrictive in some directions and broader in others than the QHIN framework's default. The institution's information-sharing decisions are made by a multi-disciplinary governance committee with representation from clinical, legal, privacy, security, and veteran-advocacy stakeholders.

You are a patient who has been in three states' health systems over the past decade. Your records exist across more than a dozen facilities. Your TEFCA-mediated longitudinal record query, executed through a personal-health-record app that has been authorized to act on your behalf, returns three different versions of your medical history depending on which QHIN's federation routes the query, with overlapping but non-identical record sets. The three versions are not in conflict (they show the same procedures, the same diagnoses, the same medications) but they are not the same: each QHIN's federation surfaced records the others did not, because the participating-organization composition of each QHIN is different. The patient-experience question is whether you, the patient, should see one unified record or three federation-specific views, and the architectural question is what mechanism reconciles them. As of writing, the answer is not standardized; the leading personal-health-record apps each handle this differently. <!-- TODO: confirm at time of build; the patient-mediated TEFCA experience continues to evolve as the personal-health-record vendor ecosystem matures. -->

This is the recipe. National-scale patient matching is the entity-resolution problem of "given that the patient is somewhere in a national federation of thousands of organizations whose records cover overlapping fragments of the patient's medical history, and given that the federation has no central master patient index, no central authority over the constituent organizations, and a heterogeneous mix of data quality, governance posture, and operational maturity across the participants, produce the cross-organizational identity resolution that supports the legitimate exchange purposes (treatment, payment, healthcare operations, public health, research, individual access services, government benefits determination) without producing operationally untenable false-positive matches and without compromising the trust framework that holds the federation together." The matching core is the same probabilistic-record-linkage core you have seen throughout the chapter, with the twist that the matching happens distributively across a federation of thousands of participants under a national framework that is still maturing as you read this. The accuracy ceiling is fundamentally constrained by the data quality of the constituent records (which, at national scale, includes the worst data quality of any single participant); the operational complexity is bounded only by the participant count, the volume of query traffic, and the governance overhead of operating across thousands of independent organizations.

It is in the complex tier because the scale is genuinely national (thousands of participants, hundreds of millions of patients, billions of records, hundreds of millions of cross-network queries per year), the federation has no central authority that can dictate technical standards or governance posture, the participants are heterogeneous in every dimension that matters (data quality, technical maturity, governance posture, regulatory framework), the trust framework is maturing as the participants are operating under it, and the operational discipline required to run a participant well in this environment is non-trivial and outside the scope of any single technical team. Most institutions that operate as TEFCA participants experience the participation as a multi-year program rather than a project; the program's outputs are a series of operational capabilities (federated query handling, federated audit, federated authorization, federated identity resolution, cross-QHIN coordination) that the institution adds to its existing infrastructure. This recipe is the architecture-level scaffolding for the participant side of that program.

Let's get into how you build it.

---

## The Technology: Federated Identity Resolution at National Scale

### What Federation Means at National Scale

In recipe 5.5, the cross-facility matcher operates against a federated architecture: each facility has its own MPI; queries route through an HIE that maintains a cross-facility index; the index is built from the demographic features each facility chose to disclose under the HIE's data-use agreement. The federation is a single HIE with a manageable participant count (tens to low hundreds of facilities), a single governance framework (the HIE's data-use agreement, signed by every participant), and a centralized cross-facility index that the matcher consults for cross-organizational identity resolution. The federation is small enough that the HIE can operate as the practical authority over the technical and governance specifications that the participants comply with.

National-scale federation removes the assumption of a single central authority and an enumerable participant set. The federation is a federation of federations: multiple QHINs, each with its own participants, each with its own cross-QHIN-routing infrastructure, each with its own subsidiary federations (state HIEs, regional HIEs, vendor-mediated networks, integrated-delivery-network MPIs, federal networks). The total participant count is in the thousands and rising. The total patient count is in the hundreds of millions. The query volume is hundreds of millions of cross-network queries per year and rising. The governance authority is split across the Recognized Coordinating Entity (the Sequoia Project) for the QHIN framework, ONC for the regulatory baseline, the participating QHINs for their own subsidiary federations, the participating organizations for their own internal posture, and the federal-and-state regulatory frameworks for the cross-cutting constraints (HIPAA, 42 CFR Part 2, post-Dobbs state laws, gender-affirming-care state laws, the 21st Century Cures Act information-blocking provisions, and the various sector-specific frameworks that apply to particular record types).

The matcher in this environment does not have a single index to consult. The matcher has to formulate a query that the federation's routing layer can deliver to the relevant participants, has to consume the heterogeneous responses each participant returns, has to consolidate the responses into a candidate-resolution view that the requesting application can present to the user, and has to do all of this with attribution back to the participants whose responses contributed to the consolidated view, with the appropriate authorization context maintained at every hop, and with the appropriate audit trail at every participant.

The architectural shift is fundamental. Recipe 5.5's matcher is a service running against a single index that the matcher's engineering team operates. Recipe 5.9's matcher is a federation participant that originates queries against a query-routing layer it does not operate, consumes responses from participants whose matchers it does not operate, and contributes responses to queries originated by participants whose query-formulation logic it does not operate. The matcher's job at recipe 5.9's scale is much more about being a good federation citizen than about being a good local matcher; the local matching is necessary but is not where the engineering effort concentrates.

### TEFCA, the Common Agreement, and the QHIN Framework

The Trusted Exchange Framework and Common Agreement (TEFCA) is the U.S. national framework for governing nationwide exchange of electronic health information. TEFCA was authorized by the 21st Century Cures Act of 2016 and operationalized through ONC's publication of the Trusted Exchange Framework and Common Agreement. The Recognized Coordinating Entity (the Sequoia Project) administers the QHIN designation process and operates the operational infrastructure for cross-QHIN exchange. <!-- TODO: confirm at time of build; the TEFCA program has rolled out QHIN designations on an ongoing basis, with the first QHINs designated in late 2023 and additional QHINs in subsequent rounds; the program continues to evolve. -->

The framework's core elements include:

**The Trusted Exchange Framework (TEF) baseline principles.** A high-level policy document that establishes the framework's trust principles: standardization, openness and transparency, cooperation and non-discrimination, privacy and security, and access. The TEF is the policy spine that the Common Agreement implements.

**The Common Agreement (CA).** The legal contract that QHINs sign with the RCE and with each other. The Common Agreement specifies the operational rules for cross-QHIN exchange: the exchange purposes (treatment, payment, healthcare operations, public health, government benefits determination, individual access services, and several others as the framework evolves), the technical requirements (standardized FHIR-based and IHE-based query patterns, cryptographic authentication, audit logging), the governance requirements (QHIN designation, participant onboarding, dispute resolution, suspension-and-termination procedures), and the operational requirements (uptime, response-time, reliability, capacity).

**QHIN-Technical-Framework (QTF).** The technical specification that QHINs implement to achieve cross-QHIN interoperability. The QTF specifies the FHIR-based and IHE-based message formats, the authentication and authorization protocols, the audit-and-attribution requirements, and the record-content specifications for each exchange purpose.

**Standard Operating Procedures (SOPs).** The operational documents that elaborate the Common Agreement and the QTF for specific scenarios. The SOPs cover the patient-discovery process (the cross-QHIN identity-resolution flow), the document-query process (the cross-QHIN content-retrieval flow), the individual-access-services process (the patient-mediated record-retrieval flow), and various administrative scenarios.

The institutional question for any participant is what role the institution plays in the framework. The roles are:

**QHIN.** A federated network of networks that participates in cross-QHIN exchange under the Common Agreement. QHIN designation is a non-trivial process (technical certification, governance review, financial-stability review, operational-capacity review) and requires ongoing operational discipline. As of writing, fewer than a dozen QHINs are designated. <!-- TODO: confirm at time of build; the QHIN designation count continues to evolve. -->

**Participant.** An organization that participates in a QHIN's federation and exchanges through the QHIN. Participants include hospital networks, health-information exchanges (some of which themselves are QHINs), payer organizations, pharmacy networks, vendor-mediated networks, public-health agencies, federal networks. A single organization may be a participant in multiple QHINs.

**Sub-participant.** An organization that participates through another participant's federation. The sub-participant relationship is recursive (a QHIN may have participants that themselves have sub-participants, and so on); the cross-QHIN exchange routes through the chain of relationships back to the originating sub-participant for attribution and audit.

**Individual user (patient).** A patient who exercises individual access services through a personal-health-record app or other patient-facing mechanism. The patient's authentication-and-authorization framework operates at the participant or sub-participant level (the individual is not directly a TEFCA participant), but the framework explicitly accommodates patient-mediated access.

The institutional decision about which role to play is non-obvious. Some institutions become QHINs because the operational scale, the existing customer base, and the strategic posture justify the investment; some institutions become QHIN participants because that is the right role for their scope and capability; some institutions remain outside TEFCA because the value proposition for their use case is not yet established. The recipe assumes the institution is operating as a participant or sub-participant in a QHIN; the QHIN-operator perspective is a related but distinct operational architecture, and the recipe notes the QHIN-side concerns where they are visible from the participant's vantage point.

### The Federated Patient-Discovery Flow

The federated patient-discovery flow is the architectural mechanism that produces cross-network identity resolution. Walk through it because it is the dominant flow in the recipe and the dominant operational concern for a participant.

A clinical user at a participating organization wants to retrieve a longitudinal record for the patient currently in front of them. The user's EHR has a search interface that, in addition to the local-record search, offers a cross-network search. The user selects the cross-network search, types in the patient's demographics (name, DOB, sex, address as much as is available), and submits the query. The EHR's TEFCA gateway formulates a patient-discovery query message in the QTF-specified format and submits it to the participant's QHIN.

The QHIN receives the patient-discovery query and identifies the routing destinations. The routing decision is informed by the query's exchange purpose (treatment, in this case), the participant's authorization scope (the participant is authorized to query for treatment), the patient's demographic features (which suggest geographic routing hints, like the state of the patient's address), and the QHIN's federation membership (which other QHINs the participant's QHIN has reciprocal exchange relationships with). The QHIN routes the query in parallel to its own participants and to the other QHINs in the federation. Each downstream QHIN routes the query to its own participants in turn.

Each receiving participant runs the patient-discovery query against its own master patient index. The participant's local matcher evaluates the query's demographic features against the participant's local patient population, applies the participant's local matching tolerance for cross-network queries, and produces a candidate list of records that may be the same patient. The candidate list includes per-record demographic data (the matching version of the demographic features that the participant is willing to disclose for cross-network discovery), the participant's local record identifier (an opaque token that the participant uses for subsequent document-query operations), the source-organization attribution (which sub-participant or facility the record comes from), and the match confidence (how strong the participant's local matcher considers the match).

The candidate lists flow back through the QHIN federation to the originating participant's QHIN. Each hop in the routing layer adds attribution metadata that lets the originating participant trace which QHIN, which sub-participant, and which source organization contributed each candidate. The originating participant's QHIN consolidates the candidate lists into a federated-discovery response and returns it to the originating participant.

The originating participant's TEFCA gateway receives the federated-discovery response and presents it to the user. The presentation typically shows the candidate records grouped by the patient identity they appear to refer to (a "this is the same person" grouping), with the per-source attribution and per-source match confidence. The user reviews the candidates, selects the ones that the user believes refer to the patient in front of them, and submits a follow-up document-query request to retrieve the actual clinical content from the selected sources.

The document-query request flows through the same federation routing layer to the selected sources. Each source returns the requested documents under the appropriate authorization framework (the patient's authorization for individual access services, the treatment-purpose authorization for clinical-care queries, the operational authorization for healthcare-operations queries, and so on). The originating participant's TEFCA gateway consolidates the documents into the user's view.

The flow has several properties that distinguish it from the recipe-5.5 cross-facility flow.

**No central index.** The matcher consults the federation rather than a central index. The federation routes the query in parallel to many participants, each of whom runs its own matcher against its own local index. The federation's response is the union of the local-matcher responses, not a single answer from a central authority.

**Participant heterogeneity is fundamental.** The participants have different matching tolerances, different demographic-feature coverage, different data quality, different governance posture. The federation's response reflects this heterogeneity (some participants return more candidates than others; some participants' candidates are higher confidence than others; some participants do not respond at all in the response window). The originating participant's user-facing presentation has to make sense of the heterogeneity.

**Two-step exchange (discovery, then document-query).** The discovery step returns candidate identifiers; the document-query step retrieves the content. The two-step pattern is the operational discipline that lets the federation maintain the appropriate access controls (each step has its own authorization, its own audit, its own re-confirmation of the user's identity and intent).

**Attribution at every hop.** Every step in the routing layer adds attribution metadata. The originating participant can trace, for any record in the consolidated view, which QHIN routed the query, which sub-participant responded, which source organization the record originated at. The attribution chain is necessary for audit, for dispute resolution, and for downstream operational concerns (rate limiting per source, error attribution per source, governance escalation per source).

**Patient-mediated access is a first-class flow.** The framework explicitly accommodates the case where the patient is the originator of the discovery and the document query, through a personal-health-record app or other patient-facing mechanism. The patient's authentication is performed at the participant level; the framework propagates the authentication context through the routing layer.

### What the National-Scale Matcher Has to Capture

A working national-scale-matching deployment has at least nine dimensions that a single-organization matcher does not.

**A federated-query-formulation discipline.** The query that goes out to the federation is not the same as the query that runs against the local index. The federated query has to balance recall (finding the patient when the patient is present in the federation under any plausible variation of demographics) with precision (not flooding the federation with overly-broad queries that produce too many false-positive candidates). The query's demographic-feature inclusion (which features to send), the demographic-feature normalization (how to standardize each feature for cross-network compatibility), and the demographic-feature suppression (which features to withhold for sensitivity reasons) are all per-query decisions that the local query-formulation logic makes.

**A cross-network matching tolerance per use case.** The matching tolerance for a treatment query (high recall on plausible matches, accepting some false positives because the user can disambiguate at the candidate-presentation step) is different from the matching tolerance for a public-health-surveillance query (high precision, accepting some false negatives because the downstream analytics cannot easily handle false-positive matches) is different from the matching tolerance for an individual-access-services query (highest precision, because the patient is being shown her own records and a wrong-record disclosure is a privacy event). The local matcher has to operate at the use-case-appropriate tolerance and the cross-network responses have to be calibrated to it.

**A federation-routing-aware response-handling discipline.** The federation's responses arrive asynchronously, with varying latencies, with varying response-window expirations, with varying error rates per source. The response-handling logic has to consume the responses as they arrive, present partial results when the user's response-time tolerance is shorter than the longest-tail response, retry or fail-over for the sources that did not respond in time, and explicitly communicate to the user what fraction of the federation has responded (so the user knows the response is partial when it is partial).

**A per-source attribution-and-audit posture.** Every cross-network candidate carries the attribution chain back to the source. The local audit log has to capture the full attribution chain (originating user, originating-participant TEFCA gateway, each routing QHIN, each downstream QHIN, the responding sub-participant, the responding source organization) for every query and every response. The audit logs at each hop also capture their portion of the attribution chain; the federated audit-reconstruction process can stitch them together for dispute resolution.

**A per-exchange-purpose authorization framework.** Every query flows under a specific exchange purpose (treatment, payment, healthcare operations, public health, government benefits determination, individual access services). The local authorization framework has to map the user's request to the appropriate exchange purpose, attach the appropriate authorization context, and route the query under it. The framework also has to honor the receiving participants' authorization framework, which may be more restrictive than the originating participant's for specific record types.

**A per-record-type sensitivity-and-disclosure overlay.** TEFCA's general framework is overlaid with sensitivity-handling rules for specific record types: 42 CFR Part 2 substance-use-treatment records, mental-health records under state-specific rules, HIV-and-genetic-information records under state-specific rules, gender-affirming-care records under jurisdiction-specific rules, post-Dobbs reproductive-health-care records under state-specific rules, juvenile records under state-specific rules. The local query-formulation and response-handling logic has to apply the appropriate overlay rules at the appropriate hop. <!-- TODO: confirm at time of build; the per-record-type sensitivity overlay continues to evolve as state-level rules and federal guidance are issued; the specific applicability is jurisdiction-specific and use-case-specific. -->

**A consent-and-authorization-management discipline.** Some queries require explicit patient consent (individual access services where the patient is acting as the authorized agent; specific record types where consent is the regulatory baseline; certain jurisdictional overlays where consent is required even for treatment purposes). The local consent-management framework has to record the consent state, attach the appropriate consent context to outgoing queries, and honor the consent state on incoming queries. The framework also has to handle consent withdrawal, which has retrospective limits at national scale (records that have already been disclosed cannot be retracted; the local framework records the withdrawal as a forward-looking event with appropriate downstream communication).

**A cross-QHIN-coordination-and-dispute-resolution mechanism.** When something goes wrong (the federation routes a query incorrectly; a participant returns wrong-record candidates; a participant fails to respond consistently; a participant's matching tolerance is mis-calibrated and produces too many false positives or too many false negatives), the dispute-resolution flow goes through the QHIN coordination layer. The local operational team has to know how to escalate, what evidence to collect (the attribution chain, the audit logs, the per-query and per-response artifacts), and what remediation to expect. The dispute-resolution timelines are long (weeks to months for non-trivial disputes); the operational discipline is patience as much as engineering.

**A scale-aware operational posture.** The query volume at national scale exceeds any single participant's internal query volume by orders of magnitude (the federation aggregates the cross-network query traffic across thousands of organizations). The local infrastructure has to handle the cross-network query inflow without compromising the internal query handling, has to rate-limit appropriately when the inflow exceeds capacity, has to scale dynamically as the federation's volume grows, and has to capacity-plan against the federation's projected volume rather than the internal historical volume. The operational discipline is closer to running a public-facing service than running an internal-enterprise service, and many institutions discover the difference when their first capacity event hits.

These nine dimensions are not optional. Every operational TEFCA participant handles them, even if some institutions handle them implicitly through informal norms rather than explicit architecture. The implicit handling tends to fail when the federation's cross-QHIN audit surfaces inconsistencies; the explicit handling is the right design.

### Why It Is Harder Than It Sounds

Seven structural reasons.

**The data-quality floor is the floor of the worst-quality participant.** The federation's matching accuracy is bounded above by the data quality of the constituent records. At national scale, the constituent records include the worst data quality of any participant, and the matcher has to handle the worst case as a normal case. The records returned by a participant whose registration workflow does not capture middle names, whose DOB-validation tolerates "01/01/1900" placeholders, whose address-standardization is inconsistent across facilities, and whose name-change handling is incomplete are returned to the federation alongside the records from participants whose data quality is much higher. The originating participant's matcher consumes both, and the resulting candidate-resolution view is necessarily a heterogeneous mix.

**The governance is multilateral and ongoing rather than bilateral and one-time.** Recipe 5.5 operates against a single HIE's data-use agreement. Recipe 5.9 operates against the Common Agreement plus the participating QHIN's framework plus the participating organizations' agreements plus the patient consent posture plus the jurisdictional overlay rules plus the use-case-specific authorization. Each of these layers is owned by a different governance body, evolves on its own cadence, and has its own dispute-resolution mechanism. The governance overhead per participant is substantial and continuous.

**The trust framework is operational, not just contractual.** The Common Agreement is signed once; the operational trust is maintained continuously. Each query has to be authenticated under the framework's cryptographic authentication; each response has to be authenticated under the responder's cryptographic identity; each audit log has to be retained under the framework's retention requirements; each dispute has to be escalated under the framework's resolution mechanism. The operational discipline of maintaining the trust framework is non-trivial, and a participant that lets the operational discipline lapse can lose its participation status under the framework's governance.

**The scale produces emergent failure modes.** At population scale, the matcher encounters edge cases that are statistically unlikely at any single-institution scale but operationally certain at national scale: identical-twin records that no demographic-feature comparison can disambiguate, family-member records with overlapping demographics that the matcher mis-resolves, patients whose demographics changed across the federation in inconsistent ways (the marriage that was recorded at one organization but not another), patients whose records are deliberately suppressed at one organization (witness protection, gender-transition sensitivity, post-Dobbs reproductive-health-care state-law overlay) but visible at another. The matcher's handling of these emergent cases is the difference between a national-scale matcher that produces operationally usable resolutions and one that produces resolutions the user cannot trust.

**The cross-QHIN routing has its own consistency and ordering concerns.** The federation routes queries in parallel; the responses arrive asynchronously; the query-routing-and-response-consolidation logic has to handle the ordering carefully. A query that routes through QHIN A and returns a candidate with one identifier, then re-routes through QHIN B (because the user clicks "search again") and returns the same candidate with a different identifier (because QHIN B's routing landed at a different sub-participant whose matcher produced a slightly different match), creates a presentation inconsistency that the user has to resolve. The resolution is the originating participant's responsibility, not the federation's.

**The information-blocking compliance posture interacts with the matching infrastructure in non-obvious ways.** The 21st Century Cures Act information-blocking provisions create an obligation to share patient records on request, with specific exceptions defined by the rule. A participant that fails to respond to a federated query may be in violation of the information-blocking rule unless the failure falls under a defined exception. The local matching infrastructure has to handle the information-blocking compliance as an operational concern: queries that the local matcher cannot resolve confidently (because the demographic data is too sparse, because the local population is too small, because the matcher's tolerance is set too tight) cannot simply be silently dropped; they have to be either responded to with appropriate "no-confident-match" indication, escalated to a slower-tier review process that produces a response within the response window, or explicitly handled under an information-blocking exception. <!-- TODO: confirm at time of build; the information-blocking compliance posture continues to evolve through ONC enforcement guidance and through industry interpretation of the rule's exceptions. -->

**The patient-experience layer is uneven and undermines trust.** The patient who exercises individual access services through three different personal-health-record apps, each running through a different QHIN, gets three different views of her record. The views are overlapping but not identical. The patient's mental model is "my record"; the operational reality is "the federation's view through this particular QHIN at this particular time, filtered through this particular app's presentation logic." The gap between the mental model and the operational reality undermines trust, and trust is the load-bearing asset for the framework's long-term viability. The participating organizations cannot fix this individually; the framework as a whole has to evolve toward a more consistent patient-experience layer, and the evolution is in progress.

### Where the Field Has Moved

A few practical updates worth knowing.

**QHIN designations are accumulating.** The first QHIN designations happened in late 2023; additional QHINs have been designated since. As of writing, the designated QHINs include established health-information networks, vendor-mediated networks, and federal networks; additional designations are expected. The operational maturity of the cross-QHIN exchange is improving as more participants come online and as the operational rhythms stabilize. <!-- TODO: confirm at time of build; the QHIN designation list and the operational maturity continue to evolve. -->

**The IHE-and-FHIR convergence is in progress.** TEFCA's QTF supports both IHE-based message formats (the established healthcare-data-exchange standards: XCPD for patient discovery, XCA for cross-community access) and FHIR-based message formats (the emerging healthcare-data-exchange standards: the Patient $match operation, the Bulk FHIR specification for population-scale queries). The QTF specifies both for backward compatibility and forward evolution; the operational reality is that most participants are still primarily IHE-based with FHIR-based exchange growing. The institutional question is how much engineering investment to put into FHIR-based exchange now versus when the FHIR-based traffic dominates. <!-- TODO: confirm at time of build; the IHE-to-FHIR transition continues to evolve, with ONC guidance and with industry adoption following the QTF's specifications. -->

**Patient-mediated access is becoming a first-class flow.** The CMS Patient Access API rule and the ONC information-blocking rule have created regulatory pressure for patient-mediated access, and TEFCA's individual-access-services exchange purpose explicitly accommodates it. The personal-health-record app ecosystem (Apple Health, the various third-party apps that connect through the Patient Access API, the patient-portal apps that the EHR vendors operate) is integrating with TEFCA at varying paces. The patient-mediated flow is now a non-trivial fraction of cross-network query traffic at the QHINs that have integrated it.

**Federated analytics is an emerging extension.** TEFCA's primary focus is record exchange for treatment-and-operational use cases; federated analytics (queries that aggregate across participants without retrieving the individual records) is a natural extension that leverages the same federation routing infrastructure for population-scale queries. Several research networks (PCORnet, All of Us, TriNetX, others) operate federated analytics outside the TEFCA framework; integration with TEFCA's framework is a topic of ongoing discussion. <!-- TODO: confirm at time of build; the federated-analytics integration with TEFCA continues to be discussed at the framework-governance level. -->

**The dispute-resolution and audit-reconstruction mechanisms are maturing.** Early TEFCA participants experienced operational issues (incorrect routing, mis-attributed responses, audit-trail gaps) that required dispute-resolution coordination across QHINs. The dispute-resolution mechanisms have evolved through these early operational events, and the audit-reconstruction tooling has improved. The institutional discipline of operating TEFCA effectively now includes a dispute-resolution playbook that the early participants developed through experience.

**State-level overlays are accumulating.** Post-Dobbs state laws on reproductive-health-care record handling, gender-affirming-care state laws, and other state-specific overlays create heterogeneous constraints across the federation. The operational discipline of honoring the state-specific overlays at every hop in the routing layer is non-trivial, and the participants that manage it well have invested in jurisdictional-overlay-rule engines that the local query-formulation and response-handling logic consults. <!-- TODO: confirm at time of build; the state-level overlay landscape continues to evolve in response to specific legislative and judicial actions. -->

**The framework's compliance posture is being tested through enforcement.** ONC enforcement of the information-blocking rule, RCE enforcement of the Common Agreement's operational requirements, and state-AG enforcement of state-specific overlays are all in early stages but accumulating. The institutional compliance posture has to anticipate the enforcement landscape, not just the rule landscape. The institutions that operate TEFCA compliance well treat the compliance as an operational program with named owners, named processes, and named escalation paths; the institutions that treat it as a contractual checkbox discover, when the first enforcement action lands, that the operational substrate cannot support the compliance defense.

---

## General Architecture Pattern

The pipeline has six logical stages: route incoming federated queries to the local matcher with the appropriate authorization context, run the local matcher against the local MPI under the cross-network tolerance, return federated-discovery responses with the per-record attribution and the per-record sensitivity overlay applied, originate outbound federated queries from local user-driven or patient-driven flows, consume federated-discovery responses and consolidate them into the user-facing presentation, and operate the cross-cutting concerns (audit at every hop, dispute resolution, capacity management, governance evolution).

```
┌────────────── INBOUND-QUERY HANDLING ─────────────┐
│                                                    │
│  [Federated patient-discovery query arrives at the │
│   participant's TEFCA gateway from the QHIN]      │
│   - Authenticate the QHIN's request signature      │
│     against the QHIN's known public key            │
│   - Validate the exchange-purpose claim against    │
│     the participant's authorized exchange purposes │
│   - Validate the requesting-participant attribution│
│     chain (originating user, originating sub-      │
│     participant, originating QHIN) against the     │
│     participant's authorized requester list        │
│   - Apply the per-exchange-purpose authorization   │
│     framework: which records may be considered     │
│     for the response, which sensitivity overlays  │
│     apply, which consent context applies           │
│           │                                        │
│           ▼                                        │
│  [Output: validated query with the authorization  │
│   context attached]                                │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── LOCAL MATCHING ─────────────────────┐
│                                                    │
│  [Run the local matcher against the local MPI    │
│   under the cross-network tolerance]              │
│   - Apply the cross-network matching tolerance    │
│     calibrated for the use case (treatment is the │
│     dominant use case; the tolerance is high-     │
│     recall, accepting some false positives that  │
│     the originating user can disambiguate)        │
│   - Apply the per-record consent and sensitivity  │
│     filters (records the patient has not          │
│     consented to disclose, records under          │
│     jurisdiction-specific suppression, records    │
│     under sensitivity-flag suppression are        │
│     excluded from the candidate set)               │
│   - Produce candidate records with the            │
│     participant's local record identifier (an     │
│     opaque token), the demographic-feature        │
│     subset that the participant is willing to    │
│     disclose for cross-network discovery, the     │
│     source-organization attribution, and the     │
│     match confidence                               │
│           │                                        │
│           ▼                                        │
│  [Output: candidate set with per-candidate        │
│   attribution and per-candidate match confidence] │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── INBOUND-RESPONSE PREPARATION ───────┐
│                                                    │
│  [Apply the per-record-type sensitivity overlay   │
│   and the per-jurisdiction overlay rules to the  │
│   candidate set before disclosure]                │
│   - 42 CFR Part 2 substance-use-treatment record  │
│     filtering (records under Part 2 are excluded  │
│     from the candidate set unless the patient's   │
│     consent posture explicitly authorizes the     │
│     disclosure)                                    │
│   - Mental-health record filtering per state-    │
│     specific rules                                  │
│   - HIV-and-genetic-information record filtering  │
│     per state-specific rules                       │
│   - Gender-affirming-care record filtering per    │
│     jurisdiction-specific rules                   │
│   - Reproductive-health-care record filtering     │
│     per post-Dobbs state-specific rules            │
│   - Juvenile record filtering per state-specific  │
│     rules                                           │
│   - Apply the per-candidate disclosure-form       │
│     decision (full demographic disclosure for     │
│     high-confidence treatment-purpose queries vs  │
│     suppressed-demographic disclosure for         │
│     individual-access-services queries with       │
│     re-identification-risk concerns)              │
│   - Sign and authenticate the response with the   │
│     participant's identity                        │
│   - Audit log the response with the full         │
│     attribution chain                             │
│           │                                        │
│           ▼                                        │
│  [Output: signed response delivered to the        │
│   originating QHIN]                                │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── OUTBOUND-QUERY HANDLING ────────────┐
│                                                    │
│  [Local user or patient initiates a cross-network │
│   query]                                           │
│   - User authentication and authorization through │
│     the participant's local IAM                   │
│   - Patient authentication and authorization      │
│     through the participant's patient-portal IdP  │
│     where the flow is patient-mediated             │
│   - Map the user's request to the appropriate     │
│     exchange purpose and attach the authorization │
│     context                                        │
│   - Formulate the federated patient-discovery     │
│     query: choose the demographic features to     │
│     include, normalize the features for cross-    │
│     network compatibility, apply per-feature      │
│     suppression for sensitivity reasons, attach   │
│     routing hints (geographic hints, sub-network  │
│     hints) to inform the QHIN's routing decision  │
│   - Submit to the participant's QHIN              │
│   - Audit log the query with the user identity,   │
│     the exchange-purpose claim, the demographic-  │
│     feature payload, and the QHIN routing target  │
│           │                                        │
│           ▼                                        │
│  [Output: query submitted to the QHIN with the   │
│   full authorization context]                     │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── OUTBOUND-RESPONSE CONSOLIDATION ────┐
│                                                    │
│  [Consume the federated-discovery responses as    │
│   they arrive]                                     │
│   - Parse each response and validate the          │
│     responder's signature against the responder's │
│     known public key                               │
│   - Validate the per-response attribution chain   │
│     and reconcile it with the originating query   │
│   - Normalize the demographic-feature             │
│     representations across responders (different  │
│     responders may use different normalization;   │
│     the local consolidation step has to bring     │
│     them into a consistent representation)        │
│   - Group the candidates by patient identity:     │
│     candidates that appear to refer to the same   │
│     patient are grouped together; the grouping is │
│     produced by a federated-resolution matcher    │
│     that runs against the candidate set           │
│   - Apply the use-case-specific presentation      │
│     filter: for treatment queries, present all    │
│     candidates with attribution; for individual-  │
│     access-services queries, present only the     │
│     candidates the patient has authorized; for    │
│     public-health-surveillance queries, present   │
│     the aggregated candidate count without        │
│     per-candidate disclosure                       │
│   - Handle response-window expiration: present    │
│     partial results when the user's response-     │
│     time tolerance is shorter than the longest-   │
│     tail response; explicitly indicate to the    │
│     user what fraction of the federation has     │
│     responded                                      │
│           │                                        │
│           ▼                                        │
│  [Output: consolidated candidate-resolution view  │
│   presented to the user]                          │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── DOCUMENT QUERY AND RETRIEVAL ───────┐
│                                                    │
│  [User selects candidates for document retrieval] │
│   - User reviews the consolidated view and        │
│     selects the candidates that the user believes │
│     refer to the patient in front of them         │
│   - For each selected candidate, formulate a      │
│     document-query request to the responding      │
│     source through the QHIN federation            │
│   - Each source returns the requested documents   │
│     under the appropriate authorization framework │
│     (treatment-purpose authorization for clinical │
│     queries, patient-authorization for individual │
│     access services, payment-authorization for    │
│     payer queries, and so on)                     │
│   - Consolidate the documents into the user's    │
│     view with per-document source attribution    │
│   - Audit log the document retrieval with the    │
│     full attribution chain                         │
│           │                                        │
│           ▼                                        │
│  [Output: longitudinal record assembled from      │
│   selected sources, with per-document attribution]│
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── AUDIT, GOVERNANCE, AND DISPUTE ─────┐
│                                                    │
│  [Cross-cutting concerns operating continuously]  │
│   - Audit log every query (inbound and outbound), │
│     every response (inbound and outbound), every  │
│     document retrieval, every authentication      │
│     event, every authorization decision, every    │
│     consent event, every dispute event, with the  │
│     full attribution chain                        │
│   - Capacity monitoring and rate limiting on the  │
│     inbound query handler; per-source rate       │
│     limiting on the outbound query handler;       │
│     federation-wide capacity coordination        │
│     through the QHIN's operational interface      │
│   - Dispute-resolution intake and triage:        │
│     incoming disputes from other participants,   │
│     outgoing disputes to other participants, the │
│     QHIN coordination layer for cross-QHIN       │
│     escalation                                     │
│   - Governance evolution: changes to the          │
│     Common Agreement, changes to the QTF, changes │
│     to the participating QHIN's framework, changes│
│     to the participating organization's posture,  │
│     changes to the jurisdictional overlay rules  │
│           │                                        │
│           ▼                                        │
│  [Operational health maintained continuously]    │
│                                                    │
└────────────────────────────────────────────────────┘
```

**The local-matcher cross-network tolerance is calibrated separately from the internal-matcher tolerance.** The internal matcher (the local MPI used by the institution's own clinical applications) is calibrated for the institution's internal use cases. The cross-network matcher (the same matcher running against cross-network queries) is calibrated for federation use, which typically demands higher recall and accepts more false positives. Re-using the internal calibration for cross-network queries produces silent under-matching: the federation's queries that the institution should respond to with a candidate are silently dropped because the internal tolerance was tighter than the federation expected. The mitigation is explicit dual-calibration with the cross-network tolerance pinned per use case.

**Per-record sensitivity-overlay enforcement is per-hop.** The Common Agreement specifies the framework's general posture; the per-record-type overlay rules are applied at each hop in the routing layer. The originating participant applies its own overlay rules to the outbound query; the responding participant applies its own overlay rules to the candidate set; the QHIN routing layer may apply additional overlay rules (where the QHIN's posture is more restrictive than the participants'). The architecture has to support per-hop enforcement with explicit attribution of which overlay rule was applied at which hop, so that the audit can reconstruct the disclosure decision per-record.

**Cross-network-attribution is the audit substrate.** The audit log captures the full attribution chain (originating user, originating sub-participant, originating QHIN, the routing path, the responding sub-participant, the responding source organization) for every query and every response. The local audit is the institution's portion of the federated audit; the cross-QHIN audit reconstruction joins the local audits across participants for dispute resolution. The audit's data model has to accommodate the full attribution chain at the design stage; bolting it on after the fact is operationally expensive.

**Patient-mediated flows have additional authentication-and-authorization layers.** A query originated by a patient through a personal-health-record app authenticated under the patient's credentials at the participant's patient-portal IdP carries patient-mediated attribution at every subsequent hop. The receiving participants honor the patient's authorization context (the patient is authorized to retrieve her own records under individual access services); the audit log records the patient-mediated attribution explicitly. The patient's authentication has to be re-verifiable through the audit trail, which means the participant's patient-portal IdP has to retain the authentication artifacts (with appropriate retention controls) for the audit-retention floor of the federation.

**Information-blocking compliance is an architectural concern.** The local matcher's response to a federated query has to satisfy both the matching's operational quality (return the right candidates) and the information-blocking compliance (do not silently drop queries the institution should have responded to). The architecture has to handle the information-blocking-relevant cases explicitly: the matcher's confidence is below the use-case-appropriate threshold (return a "no-confident-match" response), the matcher's response is delayed (escalate to a slower-tier review process that produces a response within the response window), the response is denied under a defined exception (return a "denied-under-exception" response with the exception code). Silent drops are operationally non-compliant.

**Cross-QHIN routing has consistency and ordering implications.** A query that is routed through one path and a re-routed query through a different path may produce different candidate sets because the federation's routing landed at different sub-participants. The local consolidation logic has to reconcile the differences when the user re-runs the query and produce a consistent presentation; the audit log has to record both routing paths for dispute reconstruction. The framework does not guarantee path consistency across queries; the participating organizations have to handle the inconsistency at the consolidation layer.

**Capacity is provisioned for the federation's projected volume, not the internal historical volume.** The cross-network query inflow at a participant grows with the federation's overall volume, which grows faster than the institution's internal volume. The local infrastructure has to provision capacity against the projected federation volume (with appropriate rate limiting, with appropriate fail-over, with appropriate scale-up triggers) rather than against the historical internal-only baseline. Many participants discover this when their first capacity event surfaces; the mitigation is explicit federation-aware capacity planning at the program-design stage.

**Governance evolution is operational, not just contractual.** Changes to the Common Agreement, changes to the QTF, changes to the participating QHIN's framework, changes to the participating organization's posture, changes to the jurisdictional overlay rules: each of these is a governance event that the local operational substrate has to accommodate. The participants that operate well have a governance-evolution program that consumes the changes, evaluates the operational impact, plans the technical-and-policy updates, and rolls them out on the framework's specified timeline. The participants that do not have this discover, when the next framework update lands, that their operational substrate cannot accommodate the change in the framework's specified window.

---

## The AWS Implementation

### Why These Services

**Amazon API Gateway plus AWS WAF for the inbound TEFCA gateway.** The TEFCA gateway exposes endpoints for the cross-network patient-discovery and document-query operations. API Gateway with WAF provides the public-facing endpoint with the appropriate authentication (mTLS for QHIN-to-participant authentication, signed-request validation for the QHIN's request signature), the appropriate rate limiting (per-QHIN rate limits to handle the federation's projected inflow), and the appropriate audit logging. The WAF rules block obvious abuse patterns (request-flooding from a single source, malformed request payloads) before the requests reach the application layer.

**AWS Lambda for the per-query handler logic.** Each inbound federated query is handled by a Lambda invocation that authenticates the request, validates the exchange-purpose and authorization context, and dispatches to the local matcher. Each outbound federated query is similarly handled by a Lambda that formulates the query, attaches the authorization context, and submits to the QHIN. The per-Lambda execution role is least-privileged: the inbound handler can read the local MPI but cannot mutate it; the outbound handler can submit to the QHIN through a designated Secrets-Manager-managed credential but cannot access any other federation endpoint.

**Amazon DynamoDB for the federation-attribution and audit metadata.** The full attribution chain (originating user, originating sub-participant, originating QHIN, routing path, responding sub-participant, responding source organization) for every query and every response is stored in DynamoDB with customer-managed KMS encryption, point-in-time recovery, and DynamoDB Streams to drive the cross-recipe event fan-out. The table's keying scheme (`query_id` as partition key, `attribution_event_id` as sort key) supports per-query queries and per-response audit reconstruction.

**Amazon RDS for Aurora PostgreSQL or Amazon Aurora Serverless for the local MPI.** The local MPI is the participant's master patient index that the cross-network matcher consults. The MPI is typically a relational store (the institution's existing MPI vendor's product, an Aurora-backed custom implementation, or an Aurora-fronted view over the participant's existing MPI). The MPI's matching logic is in scope for recipe 5.1; the cross-network-tolerance variant is in scope for this recipe.

**Amazon ElastiCache for Redis for the candidate-set caching.** Cross-network queries have a long tail of repeat queries from the same source against the same patient (the same patient is queried multiple times across her care episode); caching the candidate set in Redis reduces the local-matcher load and improves the response-time consistency. The cache is keyed on the query's normalized demographic-feature payload (with appropriate cryptographic salting to prevent cross-query inference) and is TTL'd to the use-case-appropriate freshness (treatment queries cache for minutes; payment queries cache for hours; population-health queries cache for days).

**AWS Step Functions for the document-query-and-retrieval orchestration.** The document-query-and-retrieval flow is multi-step: receive the candidate selection, formulate document-query requests for each candidate, submit through the QHIN federation, consume the responses, consolidate the documents into the user's view. Step Functions orchestrates the flow with per-step retries, per-step error routing to DLQs, parallel execution across candidates, and explicit synchronization at the consolidation step.

**Amazon S3 for the document-store substrate.** The retrieved documents are persisted to S3 with SSE-KMS encryption, lifecycle to S3 Glacier for the audit-retention floor, and Object Lock in Compliance mode for the audit-archive bucket. The per-document attribution metadata is stored alongside the document (with the originating-source attribution, the retrieval-context attribution, the consent-context attribution).

**Amazon EventBridge for the federation-event fan-out.** When a cross-network query completes, when a dispute is raised, when a governance change is processed, when a consent withdrawal is recorded, an event flows out to the per-participant operational systems, the cross-recipe consumers, and the analytics consumers. EventBridge rules route events to the right consumer with DLQs for failed deliveries.

**Amazon Cognito for the patient-portal authentication on patient-mediated flows.** Where the cross-network query is patient-mediated (the patient is the originator through a personal-health-record app), Cognito provides the patient-portal authentication. The personal-health-record app exchanges the patient's credentials for an OAuth token; the token carries the patient-mediated attribution that subsequent hops in the federation honor.

**AWS Secrets Manager for the QHIN credentials and the cryptographic-signing keys.** The participant's QHIN-facing credentials (mTLS certificates, signing keys, OAuth client credentials) are stored in Secrets Manager with customer-managed KMS encryption and rotation. The signing keys for outbound query signing and inbound response validation are loaded into the Lambda execution context per-invocation; the keys themselves never leave the Secrets Manager context.

**AWS KMS and AWS CloudHSM for the cryptographic-key custody.** Customer-managed KMS keys for the audit metadata, the federation attribution, the document store, and the Secrets Manager secrets. CloudHSM where the institutional security posture or the federation's framework requires single-tenant HSM-backed key custody (some federal participants and some high-assurance state HIEs operate under this requirement).

**Amazon SageMaker for the cross-network-tolerance calibration and the cohort-stratified-accuracy reporting.** The cross-network matching tolerance is calibrated against a curated calibration set (synthetic data plus opt-in pilot data from collaborating participants) using SageMaker training jobs. The cohort-stratified-accuracy reports run as SageMaker Processing jobs against the federated-discovery-response audit data, stratified by the cohort axes (geographic cohort, age cohort, sex/gender cohort, name-tradition cohort, jurisdictional-overlay cohort).

**Amazon Athena, AWS Glue Data Catalog, and AWS Lake Formation for the audit-and-analytics surface.** The federation attribution data, the per-query audit-event log, and the per-participant performance metrics surface through Athena queries with Lake Formation column-level and row-level access controls. Treatment-context users see the institution's own portion of the attribution chain; cross-QHIN-coordination users see the full attribution chain for dispute resolution; audit-and-compliance users see the full audit-event log; the institutional governance committee sees the federation-level metrics.

**AWS PrivateLink for the QHIN-to-participant private network path.** Where the QHIN and the participant operate in the same cloud and the participant's security posture requires private-network exchange, PrivateLink endpoints between the QHIN's VPC and the participant's VPC provide the private network path. The PrivateLink configuration is paired with VPC endpoint policies that enumerate the specific cross-account roles authorized to invoke the endpoint.

**Amazon CloudWatch and AWS CloudTrail.** CloudWatch metrics on per-source query rate, per-source response latency, per-source error rate, per-cohort match-rate disparity, dispute-resolution backlog, capacity-reservation utilization, federation-event throughput. CloudWatch alarms on rate-limit breaches, response-latency breaches, error-rate spikes, capacity-reservation breaches. CloudTrail data events on every audit-event read, every federation-attribution read, every secret-access, every KMS-key-use. Same chapter pattern as 5.1, 5.4, 5.5, 5.6, 5.7, 5.8.

**Amazon QuickSight for operational and quality dashboards.** Per-source query rate, per-source response latency, per-cohort match-rate trend, per-jurisdictional-overlay applicability rate, dispute-resolution-backlog trend, capacity-utilization trend, governance-event-volume trend.

### Architecture Diagram

```mermaid
flowchart LR
    subgraph QHIN_External
      Q1[Other QHIN<br/>Federation Routes]
      Q2[Participant's QHIN<br/>Cross-Network Router]
    end

    subgraph Participant_VPC
      AG1[API Gateway<br/>+ WAF<br/>TEFCA Gateway]
      L1[Lambda<br/>inbound-query-handler]
      L2[Lambda<br/>outbound-query-formulator]
      L3[Lambda<br/>response-consolidator]
      L4[Lambda<br/>sensitivity-overlay-applicator]
      EC1[(ElastiCache Redis<br/>candidate-cache)]
      RDS1[(Aurora PostgreSQL<br/>Local MPI)]
      SF1[Step Functions<br/>document-query-orchestrator]
      L5[Lambda<br/>document-retrieval-handler]
    end

    subgraph Federation_Substrate
      DDB1[(DynamoDB<br/>federation-attribution)]
      DDB2[(DynamoDB<br/>audit-event-log)]
      DDB3[(DynamoDB<br/>jurisdictional-overlay-config)]
      DDB4[(DynamoDB<br/>consent-state)]
      S3D[(S3 document-store<br/>SSE-KMS)]
      S3A[(S3 audit-archive<br/>Object Lock Compliance)]
    end

    subgraph Identity_Substrate
      SM1[(Secrets Manager<br/>QHIN credentials,<br/>signing keys)]
      KMS1[(AWS KMS<br/>customer-managed keys)]
      HSM1[(AWS CloudHSM<br/>high-assurance custody)]
      COG1[Cognito<br/>patient-portal IdP]
    end

    subgraph Operational_Substrate
      EB1[EventBridge<br/>federation-events-bus]
      SQS1[SQS<br/>dispute-queue]
      SQS2[SQS<br/>governance-evolution-queue]
      SM2[SageMaker<br/>cross-network-tolerance<br/>calibration]
      SM3[SageMaker<br/>cohort-stratified-accuracy]
    end

    subgraph Analytics_Substrate
      AT1[Athena]
      LF1[Lake Formation<br/>column-and-row access]
      QS1[QuickSight<br/>operational and quality<br/>dashboards]
      CW1[CloudWatch<br/>metrics and alarms]
      CT1[CloudTrail<br/>audit logs]
    end

    Q1 -->|cross-QHIN routing| Q2
    Q2 -->|inbound query| AG1
    AG1 --> L1
    L1 --> L4
    L4 --> RDS1
    L4 --> EC1
    L4 --> DDB3
    L4 --> DDB4
    L4 --> DDB1
    L4 --> DDB2
    L4 -->|signed response| Q2

    COG1 -->|patient auth| L2
    L2 --> SM1
    L2 -->|outbound query| Q2
    Q2 -->|outbound response| L3
    L3 --> SF1
    SF1 --> L5
    L5 --> S3D
    L5 --> DDB1
    L5 --> DDB2

    SM1 --> KMS1
    HSM1 --> KMS1
    KMS1 --> RDS1
    KMS1 --> DDB1
    KMS1 --> DDB2
    KMS1 --> S3D
    KMS1 --> S3A

    DDB1 --> EB1
    EB1 --> SQS1
    EB1 --> SQS2
    EB1 -->|FanOut| C5[Recipe 5.5<br/>cross-facility matcher]
    EB1 -->|FanOut| C6[Recipe 5.6<br/>claims-clinical linkage]
    EB1 -->|FanOut| C7[Recipe 5.7<br/>longitudinal name-change]
    EB1 -->|FanOut| C8[Recipe 5.8<br/>privacy-preserving linkage]
    EB1 -->|FanOut| C9[Internal operational<br/>systems]

    DDB2 --> AT1
    DDB1 --> AT1
    S3A --> AT1
    AT1 --> LF1
    AT1 --> QS1
    SM2 --> RDS1
    SM3 --> DDB2
    L1 --> CW1
    L2 --> CW1
    L3 --> CW1
    AG1 --> CT1
    L1 --> CT1
    L2 --> CT1

    style RDS1 fill:#9ff,stroke:#333
    style DDB1 fill:#9ff,stroke:#333
    style DDB2 fill:#9ff,stroke:#333
    style DDB3 fill:#9ff,stroke:#333
    style DDB4 fill:#9ff,stroke:#333
    style S3D fill:#cfc,stroke:#333
    style S3A fill:#cfc,stroke:#333
    style SM1 fill:#fc9,stroke:#333
    style HSM1 fill:#fc9,stroke:#333
    style EB1 fill:#f9f,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon API Gateway, AWS WAF, AWS Lambda, Amazon DynamoDB, Amazon RDS for Aurora PostgreSQL (or the participant's existing MPI), Amazon ElastiCache for Redis, AWS Step Functions, Amazon S3, Amazon EventBridge, Amazon SQS, Amazon Cognito, AWS Secrets Manager, AWS KMS, AWS CloudHSM (where the higher-assurance custody is required), Amazon SageMaker, Amazon Athena, AWS Glue Data Catalog, AWS Lake Formation, AWS PrivateLink, Amazon QuickSight, Amazon CloudWatch, AWS CloudTrail. |
| **External Inputs** | The participant's local MPI (the canonical patient identity store from recipe 5.1). The participant's QHIN's operational endpoints (the cross-QHIN router URL, the QHIN's signing certificate, the QHIN-issued participant credentials). The Common Agreement and the QHIN-Technical-Framework specifications. The participant's exchange-purpose authorization scope (which exchange purposes the participant is authorized to operate under). The participant's jurisdictional-overlay configuration (the per-jurisdiction overlay rules the participant honors). The participant's consent-state store (the per-patient consent posture for cross-network disclosure). Cross-recipe dependencies: recipe 5.1 local MPI, recipe 5.3 address standardization, recipe 5.5 cross-facility matching for the within-HIE matching, recipe 5.7 longitudinal-name-change for the time-varying-name handling, recipe 5.8 privacy-preserving linkage for the privacy-preserving-cross-organization use cases. |
| **IAM Permissions** | Per-Lambda least-privilege: scoped `dynamodb:GetItem` / `PutItem` / `Query` on the federation-attribution and audit-event-log tables, `secretsmanager:GetSecretValue` on the QHIN-credentials-and-signing-keys secrets pinned to the current rotation, `kms:Decrypt` on the audit-and-attribution KMS keys, `s3:PutObject` / `GetObject` on the document-store and audit-archive buckets with prefix scoping, `events:PutEvents` on the federation-events bus, `sqs:SendMessage` on the dispute and governance-evolution queues. The inbound-query-handler Lambda has read-only access to the local MPI; mutations to the local MPI are explicitly out of scope for the cross-network handler. The outbound-query-formulator Lambda has signing-credential access through the per-rotation Secrets Manager secret; the credential is rotated on the framework-specified cadence. The patient-portal Cognito-authenticated flow has a separate IAM context that distinguishes patient-mediated queries from staff-initiated queries in the audit log. Per-step-function execution-role binding so Step Functions invokes only the role appropriate for the current document-query stage. Never use `*` actions or `*` resources in production. <!-- TODO (TechWriter): Expert review S1 (HIGH). Specify identity-boundary requirements at the architectural level for every consequential path: (1) the inbound-query-handler Lambda receives a QHIN-signed request envelope (`originating_user_id`, `originating_sub_participant_id`, `originating_qhin_id`, `exchange_purpose`, `signed_payload`, `qhin_signature`) with consumer-side signature validation against the QHIN's known public key rotated on the framework's cadence; (2) the outbound-query-formulator Lambda formulates a request envelope signed under the participant's signing credential and validates the QHIN's response signature against the QHIN's public key; (3) the patient-mediated flow's authentication chain is propagated explicitly through the audit log with the patient's authentication-event-id retained at the participant-level Cognito and the patient-portal session-id retained at the patient-portal app's session store; (4) the QHIN-credential rotation is dual-controlled at the architectural level (two operators from non-overlapping organizational units must approve a rotation operation; the rotation is audit-logged with both operator identities); (5) the cross-recipe EventBridge fan-out validates producer-signed envelopes at consumers and applies access-control-envelope-aware routing so that consumers in different trust tiers receive different event detail levels. The recipe-specific extensions to the chapter pattern are the QHIN-credential rotation's federation-trust-anchor stakes, the patient-mediated-attribution stakes, and the cross-QHIN-dispute-resolution attribution stakes. Same chapter pattern as 5.1, 5.4, 5.5, 5.6, 5.7, 5.8. --> |
| **BAA, Common Agreement, and QHIN Membership** | AWS BAA signed. Common Agreement signed (or, more typically, the participant signs a Participant or Sub-Participant Agreement with a designated QHIN, which has signed the Common Agreement with the RCE). Per-QHIN Participant Agreement that authorizes the participant for specific exchange purposes and specifies the operational requirements (uptime, response-time, capacity, audit retention). Per-jurisdiction overlay-rule agreements where the participant operates across multiple jurisdictions (post-Dobbs state laws, gender-affirming-care state laws, 42 CFR Part 2, HIV-and-genetic-information state-specific rules). Patient consent for cross-network disclosure where the institutional policy or the regulatory framework requires it. <!-- TODO (TechWriter): Expert review A3 (MEDIUM). Specify per-query consent metadata captured at intake and the jurisdictional overlay applicability. Architect the overlay-rules engine (versioned rule store, rule-evaluation Lambda invoked at query-formulation time and at query-handling time with the patient's residence jurisdiction, the requesting-participant's jurisdiction, the use case's authorization scope, the record-type sensitivity classification, and the participating organizations' jurisdictional postures), the regulatory-monitoring function (shared between privacy and compliance teams; legislative-session feeds with explicit per-state subscription, regulatory-bulletin subscriptions, RCE-bulletin subscriptions, court-decision tracking; trigger thresholds with relevance-evaluation criteria), the per-query consent-posture decision audit trail, and the trust-framework-update pathway. --> |
| **Encryption** | API Gateway: TLS 1.2 or higher, mTLS for QHIN-to-participant authentication. Lambda log groups: KMS-encrypted. DynamoDB tables: customer-managed KMS at rest. Aurora PostgreSQL: customer-managed KMS at rest, TLS in transit. ElastiCache Redis: customer-managed KMS at rest, TLS in transit, AUTH-token-protected. S3 buckets: SSE-KMS with customer-managed keys. Audit-archive S3: SSE-KMS with customer-managed keys, Object Lock in Compliance mode. Secrets Manager: KMS-encrypted with the customer-managed key. CloudHSM (where used) for the higher-assurance signing-key custody. KMS key policies enforce least-privilege access; the inbound-query-handler Lambda role can decrypt audit-and-attribution data but cannot decrypt the signing-key material; the outbound-query-formulator Lambda role can use the signing key for signing operations but cannot export the key material. mTLS for QHIN-to-participant transport; mTLS for the cross-recipe EventBridge consumers where the consumer is in a different account. |
| **VPC** | Production: all Lambdas in VPC. API Gateway with VPC endpoint where the participant's QHIN supports PrivateLink. VPC endpoints for DynamoDB, S3, Secrets Manager, KMS, CloudWatch Logs, EventBridge, SQS, Step Functions, Athena, STS, SageMaker. PrivateLink for the QHIN-to-participant exchange where the QHIN supports it. NAT Gateway for outbound HTTPS to the QHIN where PrivateLink is not used; outbound proxy with allow-list. Aurora PostgreSQL in a private subnet with no public-network reachability; security group enumerates the specific Lambda execution-role-bound ENIs authorized to connect. ElastiCache Redis in a private subnet with the same security-group discipline. <!-- TODO (TechWriter): Expert review N1 (LOW). Specify the per-QHIN PrivateLink endpoint configuration, the per-rotation network-policy expiration that aligns with the QHIN-credential rotation, and the audit-and-monitoring discipline on the QHIN-to-participant exchange. Also specify the patient-portal-network-isolation pattern: the patient-portal Cognito flow operates through a separate API Gateway endpoint with its own WAF rule set, with rate limiting per-patient-session and per-patient-id below the staff-initiated query rate limits to prevent abuse. --> |
| **CloudTrail** | Enabled with data events on the federation-attribution and audit-event-log DynamoDB tables, the audit-archive S3 bucket, the document-store S3 bucket, the QHIN-credentials Secrets Manager secrets, the signing-key KMS keys. Lambda invocations logged. Step Functions executions logged. EventBridge events logged. CloudTrail logs encrypted with KMS and retained per the regulatory floor (typically the longest of HIPAA records-retention 7-year minimum, the QHIN's framework-specified audit-retention floor, the state-specific medical-records-retention, and the cross-jurisdictional retention overlay where the participant operates across borders). Audit logs in a dedicated S3 bucket with Object Lock in Compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days; CloudTrail data events forwarded to a dedicated audit AWS account. Same chapter pattern as 5.1, 5.4, 5.5, 5.6, 5.7, 5.8. <!-- TODO (TechWriter): Expert review S2 (MEDIUM). Replace the "per the regulatory retention floor" framing with an explicit floor that names the longest of: HIPAA 7-year minimum, the QHIN's Common Agreement-specified audit-retention floor (the framework specifies a minimum that participants must honor; the specific value is in the QTF), state medical-records-retention, the participant's institutional retention floor, the cross-jurisdictional retention overlay, the cross-recipe coordination retention floor (events that interact with recipes 5.5 / 5.7 / 5.8 may impose a longer floor than the standalone TEFCA framework). For QHIN-credential and signing-key audit events, specify the separately access-controlled bucket with the framework's specified retention floor (typically the longest of the above plus an additional period for post-deployment audit reconstruction). --> |
| **Reference Data and Federation Configuration** | A versioned reference-data store with: the participating QHIN's operational endpoints, the QHIN's public-signing-key version (rotated per framework cadence), the participant's QHIN-issued credentials (rotated per framework cadence), the cross-network-matching-tolerance configuration (per use case: treatment, payment, healthcare operations, public health, individual access services), the per-jurisdiction overlay rules, the participant's exchange-purpose authorization scope. The reference data refreshes on a regular cadence and is versioned so each query references the configuration version active at the query time. |
| **Sample Data** | Synthetic data with modeled cross-organizational and cross-jurisdictional populations. Synthea generates synthetic patient populations; extending Synthea to produce a federation-modeled population (the same synthetic patients appearing across multiple synthetic participants with appropriate demographic-feature variation) is feasible. The RCE may publish reference test data for QHIN designation; the participant's QHIN may have its own onboarding test data. Pilot federation testing against a curated cohort of opt-in patients (with explicit consent for the pilot) provides the operational validation. Never use real PHI in development environments. |
| **Cost Estimate** | At a participant operating at a national-medical-center scale (one million patients in the local MPI, ten thousand cross-network queries per day, integration with two QHINs): API Gateway plus WAF typically $200-800 per month; Lambda invocations typically $100-400 per month at this volume; DynamoDB for federation-attribution and audit typically $300-1,200 per month; Aurora PostgreSQL for the local MPI typically $1,000-3,000 per month (depends on the existing MPI substrate); ElastiCache Redis for candidate caching typically $150-500 per month; S3 storage for documents and audit typically $200-1,000 per month; KMS, Secrets Manager, EventBridge, SQS, Step Functions, SageMaker, Athena, QuickSight in aggregate typically $500-1,500 per month; CloudHSM (where used) typically $1,500-2,500 per month for the dedicated HSM. Total AWS infrastructure typically $3,500-11,000 per month at this scale, dominated by Aurora PostgreSQL and CloudHSM (where used). The QHIN participation fees are separate and are paid to the QHIN under the Participant Agreement; the fees vary by QHIN. <!-- TODO: replace with verified, current pricing once the implementing team validates against the AWS Pricing Calculator. The QHIN participation fees are operational and contractual rather than infrastructure costs. --> |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon API Gateway** | TEFCA gateway endpoint for inbound cross-network queries from the participant's QHIN; outbound query submission endpoint to the QHIN |
| **AWS WAF** | Public-endpoint protection for the TEFCA gateway: rate limiting per-QHIN, malformed-payload blocking, abuse-pattern detection |
| **AWS Lambda** | Per-query handler logic: inbound-query-handler, outbound-query-formulator, response-consolidator, sensitivity-overlay-applicator, document-retrieval-handler, dispute-handler, governance-evolution-handler |
| **Amazon DynamoDB** | Federation-attribution table (per-query attribution chain), audit-event-log table (per-query and per-response audit), jurisdictional-overlay-config table (versioned overlay rules), consent-state table (per-patient consent posture) |
| **Amazon RDS for Aurora PostgreSQL** | Local MPI for the participant; the cross-network matcher consults the MPI under the cross-network tolerance |
| **Amazon ElastiCache for Redis** | Candidate-set cache for repeat queries; TTL'd to the use-case-appropriate freshness |
| **AWS Step Functions** | Document-query-and-retrieval orchestration with per-step retries, error routing to DLQs, parallel execution across candidates |
| **Amazon S3** | Document-store bucket for retrieved documents (SSE-KMS, lifecycle to Glacier); audit-archive bucket (SSE-KMS, Object Lock in Compliance mode, lifecycle to Glacier Deep Archive) |
| **Amazon EventBridge** | Federation-event fan-out: `tefca_query_completed`, `tefca_dispute_raised`, `tefca_dispute_resolved`, `tefca_governance_event_received`, `tefca_consent_withdrawn`, `tefca_credential_rotated` |
| **Amazon SQS** | Dispute queue (incoming and outgoing disputes), governance-evolution queue (Common Agreement updates, QTF updates, QHIN-framework updates) |
| **Amazon Cognito** | Patient-portal authentication for patient-mediated cross-network queries |
| **AWS Secrets Manager** | QHIN-issued credentials, signing keys, OAuth client credentials with rotation per framework cadence |
| **AWS KMS** | Customer-managed encryption keys for the federation-attribution and audit-event-log tables, the local MPI, the candidate-set cache, the document-store and audit-archive buckets, the Secrets Manager secrets |
| **AWS CloudHSM** | Single-tenant hardware-security-module for the high-assurance signing-key custody (where the institutional security posture or the federation's framework requires it) |
| **Amazon SageMaker** | Cross-network-tolerance calibration over the curated calibration set; cohort-stratified-accuracy reports against the federated-discovery-response audit data |
| **Amazon Athena and AWS Glue Data Catalog** | SQL access to the federation attribution, audit event log, and cohort-stratified-accuracy snapshots |
| **AWS Lake Formation** | Column-level and row-level access controls for the differentiated audiences (treatment, cross-QHIN coordination, audit, governance, analytics) |
| **AWS PrivateLink** | Private network path for the QHIN-to-participant exchange where the QHIN supports it |
| **Amazon QuickSight** | Operational and quality dashboards (per-source query rate, per-source response latency, per-cohort match-rate trend, per-jurisdictional-overlay applicability rate, dispute-resolution-backlog trend, capacity-utilization trend, governance-event-volume trend) |
| **Amazon CloudWatch** | Operational metrics and alarms (rate-limit breaches, response-latency breaches, error-rate spikes, capacity-reservation breaches) |
| **AWS CloudTrail** | Audit logging for all API calls on the federation-attribution and audit-event-log tables, the audit-archive and document-store buckets, the QHIN-credentials Secrets Manager secrets, the signing-key KMS keys |

---

### Code

> **Reference implementations:** Useful patterns and reference materials for this recipe:
> - The [Sequoia Project](https://sequoiaproject.org/) operates the Recognized Coordinating Entity for TEFCA and publishes the QHIN-Technical-Framework specifications and the Standard Operating Procedures.
> - [The Office of the National Coordinator for Health Information Technology (ONC)](https://www.healthit.gov/topic/interoperability/policy/trusted-exchange-framework-and-common-agreement-tefca) publishes the Common Agreement and the regulatory baseline that TEFCA operates under.
> - [IHE International](https://www.ihe.net/) publishes the integration profiles (XCPD for cross-community patient discovery, XCA for cross-community access) that the QTF references.
> - [HL7 FHIR](https://www.hl7.org/fhir/) publishes the FHIR specification including the Patient $match operation and the Bulk FHIR specification used in TEFCA's emerging FHIR-based exchange patterns.
> - The [Carequality](https://carequality.org/) framework is a related pre-TEFCA national framework whose patterns inform some of TEFCA's operational specifications. <!-- TODO: confirm at time of build; the Carequality-and-TEFCA relationship continues to evolve as TEFCA matures and as QHIN designations accumulate. -->

#### Walkthrough

**Step 1: Handle the inbound federated patient-discovery query.** A query from the participant's QHIN arrives at the TEFCA gateway. The query carries the originating-attribution chain, the exchange-purpose claim, the demographic-feature payload, and the QHIN's request signature. The gateway authenticates the request, validates the attribution chain, validates the exchange-purpose claim against the participant's authorization scope, and dispatches the query to the local matcher with the appropriate authorization context. Skip the authentication-and-validation step and you accept malformed or unauthorized queries that produce wrong-record disclosures with audit-trail attribution to the QHIN that did not actually originate them.

```
FUNCTION handle_inbound_patient_discovery_query(
    request_payload, request_signature, request_metadata):

    // Step 1A: validate the QHIN's request signature.
    // The signature is verified against the QHIN's
    // current public-signing-key version. Rotation of
    // the signing key is coordinated through the QHIN's
    // operational interface; the participant maintains
    // both the current and the previous public-signing-key
    // version during the rotation window.
    qhin_id = request_metadata.qhin_id
    qhin_public_keys =
        load_qhin_public_keys(qhin_id,
                              include_previous_during_rotation=
                                  TRUE)

    IF NOT verify_signature_against_any(
            request_payload,
            request_signature,
            qhin_public_keys):
        audit_log({
            event_type:
                "TEFCA_INBOUND_QUERY_SIGNATURE_REJECTED",
            qhin_id: qhin_id,
            request_metadata: request_metadata,
            rejected_at: current UTC timestamp
        })
        RAISE InvalidQHINSignatureError()

    // Step 1B: validate the originating-attribution chain.
    // The chain identifies the originating user, the
    // originating sub-participant, the originating QHIN,
    // and the routing path. The participant honors only
    // chains from QHINs the participant has reciprocal
    // exchange relationships with.
    attribution_chain =
        request_payload.originating_attribution_chain

    IF NOT validate_attribution_chain(
            attribution_chain,
            participant_authorized_qhins=
                load_participant_authorized_qhins()):
        audit_log({
            event_type:
                "TEFCA_INBOUND_QUERY_ATTRIBUTION_REJECTED",
            attribution_chain: attribution_chain,
            rejected_at: current UTC timestamp
        })
        RAISE InvalidAttributionChainError()

    // Step 1C: validate the exchange-purpose claim. The
    // participant honors only the exchange purposes the
    // participant has authorized; treatment is the
    // dominant authorization, but other purposes (payment,
    // operations, public health, individual access
    // services, government benefits determination) require
    // explicit authorization.
    exchange_purpose = request_payload.exchange_purpose

    IF exchange_purpose NOT IN
        load_participant_authorized_exchange_purposes():
        audit_log({
            event_type:
                "TEFCA_INBOUND_QUERY_PURPOSE_REJECTED",
            exchange_purpose: exchange_purpose,
            rejected_at: current UTC timestamp
        })
        RETURN build_purpose_denied_response(
            attribution_chain, exchange_purpose)

    // Step 1D: build the authorization context that the
    // local matcher consults. The context combines the
    // exchange-purpose claim, the originating-attribution
    // chain (which sub-participant is requesting and what
    // its authorization is), the patient-mediated flag (if
    // the originating attribution is a patient), and the
    // applicable jurisdictional overlay rules.
    authorization_context = build_authorization_context(
        exchange_purpose=exchange_purpose,
        originating_attribution=attribution_chain,
        is_patient_mediated=
            attribution_chain.is_patient_mediated,
        jurisdictional_overlay_rules=
            load_jurisdictional_overlay_rules(
                requesting_jurisdiction=
                    attribution_chain.requesting_jurisdiction,
                participant_jurisdiction=
                    load_participant_jurisdiction()))

    // Step 1E: log the inbound query with the full
    // attribution chain.
    query_id = generate_query_id()
    audit_log({
        event_type: "TEFCA_INBOUND_QUERY_ACCEPTED",
        query_id: query_id,
        qhin_id: qhin_id,
        attribution_chain: attribution_chain,
        exchange_purpose: exchange_purpose,
        demographic_payload_summary:
            summarize_payload_for_audit(
                request_payload.demographic_features),
        accepted_at: current UTC timestamp
    })

    // Dispatch to the local matcher (Step 2).
    candidate_set = run_local_matcher_under_cross_network_tolerance(
        request_payload.demographic_features,
        authorization_context,
        query_id)

    // Apply the sensitivity overlay (Step 3).
    filtered_candidate_set = apply_sensitivity_overlay(
        candidate_set,
        authorization_context,
        query_id)

    // Build and return the response (Step 4).
    response = build_signed_federation_response(
        candidate_set=filtered_candidate_set,
        query_id=query_id,
        attribution_chain=attribution_chain,
        participant_signing_key=
            load_participant_signing_key())

    audit_log({
        event_type: "TEFCA_INBOUND_RESPONSE_DELIVERED",
        query_id: query_id,
        candidate_count: len(filtered_candidate_set),
        delivered_at: current UTC timestamp
    })

    RETURN response
```

**Step 2: Run the local matcher under the cross-network tolerance.** The local matcher consults the local MPI with a tolerance calibrated for cross-network use cases. The cross-network tolerance is typically higher-recall than the internal-application tolerance: the federation's queries that the participant should respond to are not silently dropped by an over-tight tolerance. Skip the dual-calibration and the federation's queries that the participant should respond to are silently dropped, which is an information-blocking compliance concern.

```
FUNCTION run_local_matcher_under_cross_network_tolerance(
    demographic_features, authorization_context, query_id):

    // Step 2A: load the cross-network matching tolerance
    // for the use case. The tolerance is calibrated
    // separately from the internal-application tolerance.
    matching_tolerance = load_cross_network_tolerance(
        exchange_purpose=
            authorization_context.exchange_purpose)

    // The tolerance includes:
    // - per-feature similarity-score weights
    // - per-feature missing-feature weights
    // - candidate-acceptance threshold (the score above
    //   which a candidate is included in the response)
    // - candidate-confidence threshold (the score above
    //   which a candidate is reported as high-confidence)
    // - max-candidate-count (the maximum number of
    //   candidates to include in the response, to bound
    //   the response size and to defeat deliberate-
    //   over-broadening attacks)

    // Step 2B: normalize the demographic features for
    // matching against the local MPI. The normalization
    // is the same as the internal-application matcher's
    // normalization plus any cross-network-specific
    // standardization (USPS for addresses, e164 for
    // phones, the QTF-specified date format for DOB).
    normalized_features = normalize_for_cross_network(
        demographic_features)

    // Step 2C: candidate-generation step (blocking).
    // The local MPI's blocking key generates candidate
    // identifiers; the matcher then evaluates each
    // candidate against the query.
    candidate_record_ids = local_mpi.block(
        normalized_features,
        matching_tolerance.blocking_strategy)

    // Step 2D: per-candidate scoring under the cross-
    // network tolerance.
    scored_candidates = []
    FOR EACH candidate_id IN candidate_record_ids:
        candidate_record = local_mpi.get(candidate_id)

        // Apply the consent-and-sensitivity filter at
        // candidate-evaluation time. Records the patient
        // has not consented to disclose for this exchange
        // purpose are excluded; records under
        // jurisdiction-specific suppression are excluded;
        // records under sensitivity-flag suppression
        // (gender-affirming-care, witness-protection)
        // are excluded.
        IF NOT consent_and_sensitivity_permits_disclosure(
                candidate_record,
                authorization_context):
            CONTINUE

        per_feature_similarity_scores =
            compute_per_feature_similarities(
                normalized_features,
                candidate_record.normalized_features,
                matching_tolerance)

        match_score = combine_with_fellegi_sunter(
            per_feature_similarity_scores,
            matching_tolerance.feature_weights,
            matching_tolerance.missing_feature_weights)

        IF match_score >= matching_tolerance
                            .candidate_acceptance_threshold:
            // Build the candidate envelope. The envelope
            // carries the demographic-feature subset that
            // the participant is willing to disclose for
            // cross-network discovery (typically a subset
            // of the local record's features), the
            // participant's local record identifier (an
            // opaque token that does not encode the
            // local record_id), the source-organization
            // attribution, and the match confidence.
            candidate_envelope = {
                opaque_record_token:
                    generate_opaque_record_token(
                        candidate_record.local_record_id,
                        query_id),
                disclosable_demographic_features:
                    extract_disclosable_features(
                        candidate_record,
                        authorization_context),
                source_organization_attribution:
                    candidate_record
                      .source_organization_attribution,
                match_score: match_score,
                match_confidence_tier:
                    classify_confidence_tier(
                        match_score, matching_tolerance),
                consent_posture_summary:
                    summarize_consent_for_candidate(
                        candidate_record,
                        authorization_context)
            }

            scored_candidates.append(candidate_envelope)

    // Step 2E: limit the candidate count to the per-query
    // max. If the candidate count exceeds the max, return
    // the highest-confidence subset and emit an audit
    // event indicating the truncation.
    IF len(scored_candidates) >
        matching_tolerance.max_candidate_count:
        scored_candidates = sort_by_confidence_desc(
            scored_candidates)
        scored_candidates = scored_candidates[
            0:matching_tolerance.max_candidate_count]
        audit_log({
            event_type:
                "TEFCA_INBOUND_QUERY_CANDIDATES_TRUNCATED",
            query_id: query_id,
            original_count: original_count,
            returned_count:
                matching_tolerance.max_candidate_count,
            truncated_at: current UTC timestamp
        })

    RETURN scored_candidates
```

**Step 3: Apply the per-record-type sensitivity overlay and the jurisdictional overlay.** The candidate set is filtered through the applicable overlay rules before disclosure. The overlay rules are versioned and per-jurisdiction; the participant's overlay-rule engine consults the patient's residence jurisdiction, the requesting participant's jurisdiction, the use case's authorization scope, and the record-type sensitivity classification to produce a per-candidate disclosure decision. Skip the overlay step and you disclose records that the applicable jurisdictional rule would have suppressed, which is a regulatory violation.

```
FUNCTION apply_sensitivity_overlay(
    candidate_set, authorization_context, query_id):

    // Step 3A: load the applicable overlay rule set. The
    // rule set is the union of rules applicable to:
    // - the patient's residence jurisdiction (which
    //   jurisdictions' overlay rules attach to the
    //   patient's data)
    // - the requesting participant's jurisdiction (which
    //   jurisdictions' overlay rules attach to the
    //   requesting context)
    // - the participant's own jurisdiction (which
    //   jurisdictions' overlay rules attach to the
    //   responding context)
    // - the use case's authorization scope (which
    //   exchange purpose constrains which overlays
    //   apply)
    overlay_rule_set = load_applicable_overlay_rules(
        patient_jurisdiction=
            extract_patient_jurisdiction(candidate_set),
        requesting_jurisdiction=
            authorization_context.requesting_jurisdiction,
        responding_jurisdiction=
            authorization_context.responding_jurisdiction,
        exchange_purpose=
            authorization_context.exchange_purpose,
        rule_version_active_at=
            current UTC timestamp)

    // Step 3B: per-candidate overlay-rule evaluation.
    filtered_candidates = []
    FOR EACH candidate IN candidate_set:
        // Apply the 42 CFR Part 2 substance-use-treatment
        // record overlay. Records under Part 2 are
        // excluded from the candidate set unless the
        // patient's consent posture explicitly authorizes
        // the disclosure for this exchange purpose.
        IF candidate.has_part_2_record AND NOT
            authorization_context.consent_posture
              .permits_part_2_disclosure_for(
                authorization_context.exchange_purpose):
            audit_log({
                event_type:
                    "TEFCA_OVERLAY_PART_2_SUPPRESSED",
                query_id: query_id,
                candidate_token:
                    candidate.opaque_record_token,
                suppressed_at: current UTC timestamp
            })
            CONTINUE

        // Apply the post-Dobbs reproductive-health-care
        // overlay. Records under post-Dobbs state-law
        // overlay are excluded from cross-jurisdiction
        // disclosure where the requesting jurisdiction's
        // posture is incompatible with the patient's
        // residence-jurisdiction overlay.
        IF candidate.has_reproductive_health_record AND
            overlay_rule_set
              .post_dobbs_overlay_applicable(
                authorization_context):
            audit_log({
                event_type:
                    "TEFCA_OVERLAY_POST_DOBBS_SUPPRESSED",
                query_id: query_id,
                candidate_token:
                    candidate.opaque_record_token,
                suppressed_at: current UTC timestamp
            })
            CONTINUE

        // Apply the gender-affirming-care overlay. Records
        // under gender-affirming-care state-law overlay
        // or under sensitivity-flag suppression (recipe
        // 5.7) are excluded per the applicable rule.
        IF candidate.has_gender_affirming_care_record AND
            overlay_rule_set
              .gender_affirming_care_overlay_applicable(
                authorization_context):
            audit_log({
                event_type:
                    "TEFCA_OVERLAY_GENDER_AFFIRMING_CARE_SUPPRESSED",
                query_id: query_id,
                candidate_token:
                    candidate.opaque_record_token,
                suppressed_at: current UTC timestamp
            })
            CONTINUE

        // Apply additional overlays as the rule set
        // specifies (HIV-and-genetic-information,
        // mental-health, juvenile, witness-protection,
        // and others as the jurisdictional overlay
        // landscape evolves).
        FOR EACH additional_overlay IN
            overlay_rule_set.additional_overlays:
            IF additional_overlay.suppresses(
                    candidate, authorization_context):
                audit_log({
                    event_type:
                        "TEFCA_OVERLAY_" +
                        additional_overlay.identifier +
                        "_SUPPRESSED",
                    query_id: query_id,
                    candidate_token:
                        candidate.opaque_record_token,
                    suppressed_at: current UTC timestamp
                })
                CONTINUE_OUTER_LOOP

        // The candidate passes all applicable overlay
        // rules. Apply the per-candidate disclosure-form
        // decision (full demographic disclosure for high-
        // confidence treatment-purpose queries vs
        // suppressed-demographic disclosure for queries
        // with re-identification-risk concerns).
        candidate_with_disclosure_form =
            apply_disclosure_form_decision(
                candidate, authorization_context)

        filtered_candidates.append(
            candidate_with_disclosure_form)

    audit_log({
        event_type: "TEFCA_OVERLAY_APPLIED",
        query_id: query_id,
        original_count: len(candidate_set),
        filtered_count: len(filtered_candidates),
        applied_at: current UTC timestamp
    })

    RETURN filtered_candidates
```

**Step 4: Originate an outbound federated patient-discovery query.** A local user or patient initiates a cross-network query. The query-formulation logic balances recall (sending enough demographic features that the federation can match the patient under plausible variation) with the per-feature suppression-for-sensitivity discipline. The signed query is submitted to the participant's QHIN, which routes it through the federation. Skip the query-formulation discipline and the outbound query produces either insufficient recall (the federation does not match the patient because too few features were sent) or excessive disclosure (the query exposes more demographic data than the use case requires).

```
FUNCTION originate_outbound_patient_discovery_query(
    user_or_patient_identity,
    requested_demographics,
    exchange_purpose,
    use_case_context):

    // Step 4A: authenticate the originator. For staff-
    // initiated queries, authenticate through the
    // institution's IAM. For patient-mediated queries,
    // authenticate through the patient-portal Cognito
    // and validate the patient's authorization scope.
    IF user_or_patient_identity.is_patient_mediated:
        authentication_result =
            authenticate_patient_mediated(
                user_or_patient_identity,
                use_case_context)
    ELSE:
        authentication_result =
            authenticate_staff_initiated(
                user_or_patient_identity,
                use_case_context)

    IF NOT authentication_result.is_authenticated:
        audit_log({
            event_type:
                "TEFCA_OUTBOUND_QUERY_AUTH_REJECTED",
            user_or_patient_identity:
                summarize_for_audit(
                    user_or_patient_identity),
            rejected_at: current UTC timestamp
        })
        RAISE AuthenticationFailedError()

    // Step 4B: map the user's request to the appropriate
    // exchange purpose. The mapping is institutional and
    // explicit; ambiguous mappings are routed to a
    // governance-defined default with the explicit-mapping
    // pattern as the audit-tracked alternative.
    mapped_exchange_purpose = map_to_exchange_purpose(
        exchange_purpose, use_case_context)

    // Step 4C: validate the participant's authorization
    // for the mapped exchange purpose.
    IF mapped_exchange_purpose NOT IN
        load_participant_authorized_exchange_purposes():
        audit_log({
            event_type:
                "TEFCA_OUTBOUND_QUERY_PURPOSE_DENIED",
            mapped_exchange_purpose: mapped_exchange_purpose,
            denied_at: current UTC timestamp
        })
        RAISE ExchangePurposeNotAuthorizedError()

    // Step 4D: formulate the federated query payload.
    // The formulation balances recall and suppression.
    formulated_payload = formulate_federated_query(
        requested_demographics,
        exchange_purpose=mapped_exchange_purpose,
        suppress_features_per_sensitivity=
            apply_sensitivity_suppression(
                requested_demographics,
                use_case_context),
        normalize_features_per_qtf=
            normalize_per_qtf(requested_demographics))

    // Step 4E: build the originating-attribution chain.
    attribution_chain = build_attribution_chain(
        originating_user_or_patient=
            authentication_result.principal_id,
        is_patient_mediated=
            user_or_patient_identity.is_patient_mediated,
        originating_sub_participant=
            load_participant_id(),
        originating_qhin=
            load_participant_qhin_id(),
        requesting_jurisdiction=
            extract_user_jurisdiction(
                authentication_result))

    // Step 4F: sign the query under the participant's
    // signing credential.
    query_id = generate_query_id()
    signed_query = sign_query(
        query_id=query_id,
        formulated_payload=formulated_payload,
        attribution_chain=attribution_chain,
        signing_key=load_participant_signing_key())

    // Step 4G: log the outbound query.
    audit_log({
        event_type: "TEFCA_OUTBOUND_QUERY_SUBMITTED",
        query_id: query_id,
        attribution_chain: attribution_chain,
        exchange_purpose: mapped_exchange_purpose,
        demographic_payload_summary:
            summarize_payload_for_audit(
                formulated_payload),
        submitted_at: current UTC timestamp
    })

    // Step 4H: submit to the QHIN.
    qhin_endpoint = load_participant_qhin_endpoint()
    submission_result = submit_to_qhin(
        signed_query, qhin_endpoint)

    // The submission returns a federation handle that
    // the response-consolidator listens against for
    // incoming responses.
    RETURN submission_result.federation_handle
```

**Step 5: Consume and consolidate the federated-discovery responses.** Responses arrive asynchronously. The consolidation logic validates each response, normalizes the demographic-feature representations across responders, groups candidates by patient identity, applies the use-case-specific presentation filter, and presents the consolidated view to the user. Partial results are presented when the response window expires before all responses have arrived. Skip the per-response signature validation and you accept malformed or unauthorized responses that produce wrong-record disclosures.

```
FUNCTION consume_and_consolidate_responses(
    federation_handle, query_id,
    response_window_seconds, use_case_context):

    // Step 5A: subscribe to the federation handle for
    // incoming responses. The QHIN delivers responses
    // as they arrive from the responding participants.
    received_responses = []
    response_deadline = current UTC timestamp +
        response_window_seconds

    WHILE current UTC timestamp < response_deadline:
        response = receive_next_response_with_timeout(
            federation_handle,
            timeout_seconds=
                min(remaining_window_seconds(), 30))

        IF response IS NULL:
            BREAK

        // Step 5B: validate the responder's signature.
        responder_id = response.responder_id
        responder_public_keys =
            load_responder_public_keys(
                responder_id,
                include_previous_during_rotation=TRUE)

        IF NOT verify_signature_against_any(
                response.payload,
                response.signature,
                responder_public_keys):
            audit_log({
                event_type:
                    "TEFCA_OUTBOUND_RESPONSE_SIGNATURE_REJECTED",
                query_id: query_id,
                responder_id: responder_id,
                rejected_at: current UTC timestamp
            })
            CONTINUE

        // Step 5C: validate the responder's attribution
        // chain (which sub-participant responded, which
        // QHIN routed) and reconcile with the originating
        // query.
        IF NOT validate_response_attribution(
                response.attribution_chain,
                originating_query_id=query_id):
            audit_log({
                event_type:
                    "TEFCA_OUTBOUND_RESPONSE_ATTRIBUTION_REJECTED",
                query_id: query_id,
                responder_id: responder_id,
                rejected_at: current UTC timestamp
            })
            CONTINUE

        // Step 5D: log the received response and add to
        // the consolidation set.
        audit_log({
            event_type:
                "TEFCA_OUTBOUND_RESPONSE_RECEIVED",
            query_id: query_id,
            responder_id: responder_id,
            candidate_count: len(response.candidates),
            received_at: current UTC timestamp
        })

        received_responses.append(response)

    // Step 5E: normalize the candidate-record
    // representations across responders. Different
    // responders may use slightly different demographic-
    // feature normalizations; the consolidation step
    // brings them into a consistent representation.
    normalized_candidates = normalize_candidates_across_responders(
        received_responses)

    // Step 5F: group candidates by patient identity. A
    // federated-resolution matcher runs against the
    // candidate set to identify which candidates appear
    // to refer to the same patient (the candidates that
    // are likely the same person but came from different
    // responders).
    grouped_candidates = federated_resolution_matcher(
        normalized_candidates)

    // Step 5G: apply the use-case-specific presentation
    // filter.
    presentation_view = apply_presentation_filter(
        grouped_candidates,
        use_case_context)

    // Step 5H: indicate response completeness to the
    // presentation layer.
    completeness_indicator = compute_completeness_indicator(
        received_responses,
        expected_responder_count=
            estimate_expected_responder_count_for_query(
                query_id),
        deadline_reached=
            (current UTC timestamp >= response_deadline))

    presentation_view.completeness_indicator =
        completeness_indicator

    audit_log({
        event_type: "TEFCA_OUTBOUND_VIEW_CONSOLIDATED",
        query_id: query_id,
        responder_count: len(received_responses),
        candidate_count: len(normalized_candidates),
        grouped_count: len(grouped_candidates),
        completeness_summary:
            summarize_completeness(completeness_indicator),
        consolidated_at: current UTC timestamp
    })

    RETURN presentation_view
```

**Step 6: Handle document-query and retrieval for selected candidates.** The user reviews the consolidated view and selects candidates for document retrieval. The document-query orchestrator formulates per-candidate document-query requests, routes them through the QHIN federation, consumes the document responses, and consolidates them into the user's longitudinal-record view. Skip the per-document attribution discipline and the consolidated record loses the source attribution that subsequent operational concerns (dispute resolution, downstream analytics, regulatory reporting) depend on.

```
FUNCTION execute_document_query_and_retrieval(
    selected_candidates, user_or_patient_identity,
    use_case_context, query_id):

    // Step 6A: per-candidate document-query formulation.
    // Each selected candidate produces a document-query
    // request that is routed back to the responding
    // source through the QHIN federation. The document-
    // query carries the opaque record token (which the
    // responding source can resolve back to the local
    // record under its own access controls) and the
    // exchange-purpose claim that the original discovery
    // query operated under.
    document_query_requests = []
    FOR EACH candidate IN selected_candidates:
        request = formulate_document_query_request(
            opaque_record_token=
                candidate.opaque_record_token,
            exchange_purpose=
                use_case_context.exchange_purpose,
            requested_document_types=
                use_case_context.requested_document_types,
            attribution_chain=
                build_attribution_chain_for_doc_query(
                    user_or_patient_identity,
                    use_case_context,
                    query_id))

        document_query_requests.append(request)

    // Step 6B: parallel submission to the QHIN federation.
    // The Step Functions orchestrator handles the parallel
    // submissions with per-step retries and per-step
    // error routing.
    document_responses = parallel_submit_to_qhin(
        document_query_requests,
        max_parallel=use_case_context.max_parallel)

    // Step 6C: per-response document-content
    // consolidation.
    consolidated_documents = []
    FOR EACH response IN document_responses:
        // Validate the responder's signature on the
        // document response.
        IF NOT validate_response_signature(response):
            audit_log({
                event_type:
                    "TEFCA_DOC_RESPONSE_SIGNATURE_REJECTED",
                query_id: query_id,
                responder_id: response.responder_id,
                rejected_at: current UTC timestamp
            })
            CONTINUE

        // Persist each document to the document-store
        // S3 bucket with the per-document attribution
        // metadata.
        FOR EACH document IN response.documents:
            persisted_document = persist_to_document_store(
                document=document,
                source_organization_attribution=
                    response.source_organization_attribution,
                retrieval_context_attribution={
                    query_id: query_id,
                    user_or_patient_identity:
                        summarize_for_audit(
                            user_or_patient_identity),
                    exchange_purpose:
                        use_case_context.exchange_purpose,
                    retrieved_at: current UTC timestamp
                },
                consent_context_attribution=
                    response.consent_context_attribution)

            consolidated_documents.append(
                persisted_document)

    // Step 6D: log the document retrieval with the full
    // attribution chain.
    audit_log({
        event_type: "TEFCA_DOCUMENTS_RETRIEVED",
        query_id: query_id,
        candidate_count: len(selected_candidates),
        document_count: len(consolidated_documents),
        retrieved_at: current UTC timestamp
    })

    // Step 6E: emit the cross-recipe event.
    EventBridge.PutEvents([{
        source: "tefca-national-scale-matching",
        detail_type: "tefca_query_completed",
        detail: {
            query_id: query_id,
            candidate_count: len(selected_candidates),
            document_count: len(consolidated_documents),
            user_or_patient_summary:
                summarize_for_audit(
                    user_or_patient_identity),
            exchange_purpose:
                use_case_context.exchange_purpose,
            completed_at: current UTC timestamp
        }
    }])

    RETURN consolidated_documents
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter05.09-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

### Expected Results

**Sample inbound federated patient-discovery query (illustrative; actual payload follows the QTF specification):**

```json
{
  "query_id": "tefca-inbound-2026-q2-3387221",
  "qhin_id": "qhin-example-national-network",
  "request_metadata": {
    "qhin_id": "qhin-example-national-network",
    "request_timestamp": "2026-04-22T14:33:11Z",
    "request_signature": "<base64-encoded-signature>"
  },
  "originating_attribution_chain": {
    "originating_user_id": "user-emergency-department-attending-44211",
    "is_patient_mediated": false,
    "originating_sub_participant_id": "sub-regional-trauma-center-east",
    "originating_qhin_id": "qhin-example-eastern-network",
    "requesting_jurisdiction": "state-of-virginia",
    "routing_path": [
      "qhin-example-eastern-network",
      "qhin-example-national-network"
    ]
  },
  "exchange_purpose": "treatment",
  "demographic_features": {
    "given_name": "Sarah",
    "family_name": "Mitchell",
    "dob": "1984-08-17",
    "sex_or_gender": "F",
    "address_line_1": "1247 Oak Street",
    "city": "Richmond",
    "state": "VA",
    "zip_code": "23220",
    "phone": null,
    "ssn_last_4": null
  }
}
```

**Sample outbound federation response (illustrative):**

```json
{
  "query_id": "tefca-inbound-2026-q2-3387221",
  "responder_id": "participant-academic-medical-center-richmond",
  "response_signature": "<base64-encoded-signature>",
  "candidates": [
    {
      "opaque_record_token": "tok-amc-richmond-2026-q2-08847221",
      "disclosable_demographic_features": {
        "given_name": "Sarah",
        "family_name": "Mitchell",
        "dob": "1984-08-17",
        "sex_or_gender": "F",
        "city": "Richmond",
        "state": "VA",
        "zip_code": "23220"
      },
      "source_organization_attribution": {
        "source_organization_id": "amc-richmond-cardiology-clinic",
        "source_organization_name": "Academic Medical Center Richmond - Cardiology",
        "source_organization_npi": "1234567890"
      },
      "match_score": 0.96,
      "match_confidence_tier": "high",
      "consent_posture_summary": {
        "consent_for_treatment_purpose": true,
        "consent_for_individual_access_services": true,
        "jurisdictional_overlay_applicable": "none"
      }
    }
  ],
  "candidate_count_returned": 1,
  "candidate_count_truncated": false,
  "responded_at": "2026-04-22T14:33:14Z"
}
```

**Sample consolidated cross-network presentation view (after consolidating responses from multiple participants):**

```json
{
  "query_id": "tefca-outbound-2026-q2-9921144",
  "originating_user": "user-emergency-department-attending-44211",
  "exchange_purpose": "treatment",
  "completeness_indicator": {
    "expected_responder_count_estimate": 12,
    "received_responder_count": 9,
    "completeness_pct": 75,
    "deadline_reached": true,
    "longest_tail_responders_pending": [
      "responder-rural-hospital-network",
      "responder-state-immunization-registry",
      "responder-state-prescription-monitoring-program"
    ]
  },
  "candidate_groupings": [
    {
      "grouping_id": "group-2026-q2-9921144-001",
      "consolidated_demographic_view": {
        "given_name": "Sarah",
        "family_name": "Mitchell",
        "dob": "1984-08-17",
        "sex_or_gender": "F",
        "city": "Richmond",
        "state": "VA",
        "zip_code": "23220"
      },
      "candidates_in_grouping": [
        {
          "opaque_record_token": "tok-amc-richmond-2026-q2-08847221",
          "responder_id": "participant-academic-medical-center-richmond",
          "source_organization_id": "amc-richmond-cardiology-clinic",
          "match_confidence_tier": "high"
        },
        {
          "opaque_record_token": "tok-rx-data-2026-q2-44912988",
          "responder_id": "participant-national-pharmacy-data-network",
          "source_organization_id": "regional-pharmacy-chain-mid-atlantic",
          "match_confidence_tier": "high"
        },
        {
          "opaque_record_token": "tok-virginia-hie-2026-q2-77221334",
          "responder_id": "participant-virginia-hie",
          "source_organization_id": "primary-care-clinic-richmond-west",
          "match_confidence_tier": "high"
        }
      ],
      "grouping_match_confidence": "high"
    }
  ]
}
```

**Sample document-retrieval result (illustrative):**

```json
{
  "query_id": "tefca-outbound-2026-q2-9921144",
  "documents_retrieved": [
    {
      "document_id": "doc-amc-cardiology-consult-2025-11-04",
      "document_type": "consultation_note",
      "source_organization_id": "amc-richmond-cardiology-clinic",
      "responder_id": "participant-academic-medical-center-richmond",
      "document_date": "2025-11-04",
      "retrieved_at": "2026-04-22T14:33:18Z"
    },
    {
      "document_id": "doc-rx-warfarin-active-prescription",
      "document_type": "active_medication",
      "source_organization_id": "regional-pharmacy-chain-mid-atlantic",
      "responder_id": "participant-national-pharmacy-data-network",
      "document_date": "2026-03-12",
      "retrieved_at": "2026-04-22T14:33:19Z"
    },
    {
      "document_id": "doc-radiology-contrast-allergy-note-2023-09",
      "document_type": "allergy_note",
      "source_organization_id": "imaging-center-northern-virginia",
      "responder_id": "participant-virginia-hie",
      "document_date": "2023-09-21",
      "retrieved_at": "2026-04-22T14:33:21Z"
    }
  ]
}
```

**Performance benchmarks (illustrative, your mileage varies):**

| Metric | Internal cross-facility (recipe 5.5) | National-scale TEFCA (recipe 5.9) |
|--------|--------------------------------------|------------------------------------|
| Match rate at fixed false-acceptance threshold (FAR=0.005) | 92-96% | 75-92% (varies by responder data quality) |
| End-to-end query latency (median) | 200-800 ms | 2-12 seconds (longest-tail responder dominates) |
| End-to-end query latency (p95) | 1-3 seconds | 8-30 seconds |
| End-to-end query latency (p99) | 3-10 seconds | 15-60 seconds (response-window expirations common) |
| Per-cohort linkage-rate disparity (best vs worst) | 0.05-0.10 | 0.10-0.20 (heterogeneous-participant penalty) |
| Inbound query throughput per participant (sustained) | 100-500 QPS | 50-300 QPS at scale (the participant has to handle the federation's growing inflow) |
| Outbound query response-window completeness | n/a | 70-90% of expected responders within window |
| Audit-event volume per query | 10-30 (per-query audit) | 30-150 (per-hop audit including federation routing) |
| Per-jurisdiction overlay-rule applicability rate | n/a | 5-25% of candidate records (varies by use case and patient population) |
| Cross-QHIN dispute rate | n/a | 0.001-0.01% of queries (highly variable based on participant maturity) |

<!-- TODO: replace illustrative figures with measured results from the deployment. The above are typical ranges from published TEFCA-pilot data and from operational reports of established HIE-to-HIE exchange networks; specific figures vary by participant maturity, by query mix, and by federation density. -->

**Where it struggles:**

- **Heterogeneous responder quality is the dominant accuracy determinant.** The federation's overall match rate is bounded above by the data quality of the constituent records, which at national scale includes the worst-quality participant. The mitigation is per-responder match-quality monitoring with explicit degradation alerts and a cross-QHIN escalation path for chronically-low-quality responders. The participant cannot fix another participant's data quality but can choose to weight the candidates by responder quality in the consolidated view.
- **Response-window expirations produce silent partial-record presentation.** A user who initiates a cross-network query and receives a partial response (because some responders timed out) sees an incomplete longitudinal record without explicit knowledge of what is missing. The presentation layer's completeness indicator is the architectural mitigation; the operational discipline is making sure the user actually sees and understands the indicator. The mitigation includes user-experience-design discipline around the partial-result state and explicit re-query mechanisms when the user needs the missing data.
- **Cross-jurisdictional overlay rules accumulate operational complexity.** Each jurisdiction's overlay rules add a per-record evaluation at every hop in the routing layer. The cumulative overhead grows with the jurisdictional-overlay landscape and with the federation's geographic scope. The mitigation is the versioned overlay-rule engine with explicit rule-evaluation metrics and an institutional regulatory-monitoring function that consumes the rule changes; without it, the rule landscape outpaces the participant's operational capacity to honor the rules.
- **The federation's matching tolerance is the loosest tolerance any participant honors.** The federation operates at the loosest tolerance because participants whose tolerances are tighter silently drop queries the looser-tolerance participants would respond to. The federation's effective tolerance is the loosest, with the consequent false-positive-rate penalty. The mitigation is explicit cross-network-tolerance calibration coordinated through the QHIN's framework and operational-coordination forums, with periodic re-calibration as the federation's overall data quality evolves.
- **Patient-mediated flows have additional authentication complexity that the framework does not fully standardize.** The patient's authentication is performed at the participant's patient-portal IdP; the federation's framework specifies the patient-mediated attribution flow but does not standardize the participant-side authentication mechanisms. Different participants implement patient-mediated authentication differently (different IdP technologies, different multi-factor authentication policies, different authentication-event-retention rules), and the cross-participant audit reconstruction has to handle the heterogeneity. The mitigation is institutional documentation of the participant's patient-mediated authentication mechanism and explicit accommodation in the audit-and-attribution layer.
- **Information-blocking compliance creates response-time pressure.** The information-blocking rule's exception framework has timing requirements that the local matcher's response has to satisfy. A query that the local matcher cannot resolve confidently in the response window has to be either responded to with a "no-confident-match" indication or escalated to a slower-tier review process that produces a response within the rule-specified timeline. Silent drops are operationally non-compliant. The mitigation is the explicit no-confident-match response pattern and the slower-tier review escalation, with operational metrics on both. <!-- TODO: confirm at time of build; the information-blocking rule's specific timing requirements continue to be interpreted through ONC enforcement guidance. -->
- **Cross-QHIN attribution chain reconstruction is operationally non-trivial.** When a dispute requires reconstructing the full attribution chain across multiple QHINs, the audit-log joining has to operate across the participating QHINs' separate audit substrates, each with its own retention policy, its own access controls, and its own attribution-data model. The dispute-resolution timelines are long (weeks to months) because the attribution-chain reconstruction is a coordinated effort across the QHIN's framework. The mitigation is per-query attribution-chain capture in the local audit at the design stage, and operational discipline in maintaining the audit's consistency with the framework's specifications.
- **Capacity events at the federation level cascade to participants.** A capacity event at one QHIN (a high-volume cross-QHIN-query spike, an outage at one participant, a misconfigured retry pattern at one participant that produces a query flood) cascades to other participants whose infrastructure consumes the federation's traffic. The mitigation is per-source rate limiting on the inbound query handler with explicit fail-fast semantics, per-source error-rate monitoring with explicit escalation thresholds, and federation-wide capacity coordination through the QHIN's operational interface.
- **The framework's evolution outpaces the participant's adoption rate.** Changes to the Common Agreement, the QTF, and the SOPs evolve on the framework's cadence; the participant's adoption is bounded by the participant's operational capacity to absorb the changes. The participants that fall behind the framework's evolution can lose their participation status under the framework's governance. The mitigation is the governance-evolution program with named owners, named processes, and explicit timeline-tracking against the framework's mandates.
- **Cross-recipe coordination at the architectural level introduces non-obvious dependencies.** The PPRL flow from recipe 5.8 may use the federation's routing layer; the longitudinal name-change handling from recipe 5.7 affects the cross-network matching tolerance; the claims-clinical linkage from recipe 5.6 may operate through the federation for cross-payer use cases. The mitigation is explicit cross-recipe event handling with the federation-events bus and explicit cross-recipe ownership in the institutional governance.
- **The institutional learning curve is substantial.** Operating a TEFCA participant well requires institutional capabilities (federation-aware engineering, federation-aware compliance, federation-aware operations, federation-aware governance) that most institutions are still building. The institutions that operate TEFCA well have invested in the institutional capabilities deliberately, often through a multi-year program with explicit milestones and explicit named ownership. The institutions that have not made the investment discover, during the first year of operation, that their existing capabilities are not sufficient for the federation's operational demands. The mitigation is treating TEFCA participation as a multi-year program with explicit institutional-capability development.

---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. A production deployment needs to close several gaps that are intentionally out of scope for a recipe.

**QHIN Participant Agreement and operational onboarding.** The institution has to negotiate and sign a Participant Agreement with the QHIN, complete the QHIN's onboarding (technical certification, governance review, operational testing), and operate continuously under the agreement's terms. The Participant Agreement is the load-bearing contractual artifact for the institution's TEFCA participation; the operational onboarding is a multi-month process that the institution has to plan and resource. Plan the QHIN onboarding as a project with its own timeline, its own staffing, and its own iteration discipline. Different QHINs have different onboarding processes; the institution's choice of QHIN affects the onboarding timeline and the operational specifics.

**QHIN-credential and signing-key rotation ceremony.** The participant's QHIN-issued credentials (mTLS certificates, OAuth client credentials) and the participant's signing keys are rotated on the framework's specified cadence (typically annual for credentials, more frequent for signing keys depending on the QHIN's policy). Rotation is a coordinated event between the participant and the QHIN; rotation has explicit dual-control approval, audit logging at every step, and a catch-up window where the prior credentials remain valid for the cutover. Build the rotation capability as a deliberate operational program with named owners, named processes, and named review committees. Skip this and the rotation is custodied informally, the audit trail is inconsistent, and the trust framework's authentication claim is operationally unsupported.

<!-- TODO (TechWriter): Expert review A2 (MEDIUM). Specify the QHIN-credential and signing-key rotation ceremony at the architectural level: the dual-control approval pattern (two operators from non-overlapping organizational units must approve a rotation operation through a separate approval-workflow Lambda; cross-account approval where the institutional security team is in a separate account; rejection semantics for single-actor approvals), the audit-log schema for credential-related operations (calling principal, operation, timestamp, credential-version, dual-control approver identities, post-operation verification status), the catch-up-window policy with an explicit duration and access-control constraint (read-only access bound to the prior credential-version with audit logging on every read), the post-rotation operational-verification SLA per participant (CloudWatch metrics on per-credential-version usage, alarm-on-degradation, response-protocol with explicit catch-up-window-extension authority), and the monitoring of rotation completion against the framework's deadline. -->

**Cross-network-tolerance calibration and approval governance.** The cross-network matching tolerance is calibrated against a curated calibration set (synthetic data plus opt-in pilot data from collaborating participants) using SageMaker training jobs. Re-calibration runs periodically and on detection of cohort-stratified disparity above the institutional threshold. Re-calibration produces a candidate tolerance set; institutional review (analytics governance committee, compliance, clinical informatics, privacy team, equity-monitoring committee) reviews the confusion matrix and the cohort-disparity impact before promoting the candidate to production. Each query references the configuration version active at decision time. Same chapter pattern as 5.1, 5.4, 5.5, 5.6, 5.7, 5.8.

<!-- TODO (TechWriter): Expert review A4 (MEDIUM). Promote the cross-network-tolerance calibration governance into the architecture text. Specify the versioned configuration table holding cross-network-tolerance per use case, per-feature weights, missing-feature weights, per-jurisdiction overlay rules; the SageMaker calibration job that produces the candidate set against the curated calibration data; the per-cohort impact-analysis requirement with explicit cohort-axis enumeration (geographic cohort, age-decade cohort, sex-or-gender cohort, name-tradition cohort, jurisdictional-overlay cohort, patient-consent-for-fairness-monitoring cohort); the privacy-team inclusion in the review committee with explicit re-identification-risk review authority; the linkage-cycle reference to the configuration version active at decision time; and the calibration-data infrastructure as separately-governed substrate (separate AWS account, separate access controls, separate audit posture, separate retention rules). -->

**Three review queues with cohort-and-cycle-aware tooling.** The cross-network-match-review queue surfaces medium-confidence candidates that the federation's response presented for review (the consolidated-presentation view's medium-confidence groupings); reviewers see the consolidated-view candidates with the per-source attribution and (under appropriate authorization) the underlying records at each responder. The dispute-review queue surfaces incoming and outgoing disputes for cross-QHIN coordination; reviewers see the dispute artifacts with the full attribution chain. The governance-evolution queue surfaces framework changes (Common Agreement updates, QTF updates, SOP updates, jurisdictional-overlay-rule updates); reviewers from compliance, privacy, legal, and operations evaluate the operational impact and plan the institutional response. Each review tool emits the reviewer's decision back into the operational training signal.

<!-- TODO (TechWriter): Expert review S3 (MEDIUM). Promote the three review-queue audit posture into the architecture pattern. Specify per-queue audit posture (reviewer identity with appropriate authentication, decision, stated reason, configuration version active at the time, threshold or tolerance version active at the time, any reviewer-supplied additional context). For the dispute-review queue, specify cross-QHIN attribution-chain reconstruction with the full audit-log joining across the participating QHINs' separate audit substrates; per-dispute reviewer training and conflict-of-interest screening. For the governance-evolution queue, specify the multi-disciplinary review with explicit named ownership (compliance, privacy, legal, operations, clinical informatics); per-change operational-impact-analysis with explicit timeline-against-framework-deadline tracking. The reviewer-authentication is two-factor and the reviewer-action is dual-controlled for the dispute-review queue and the governance-evolution queue (two reviewers from non-overlapping organizational units must approve high-impact decisions). -->

**Patient-consent capture and withdrawal pathways.** The TEFCA deployment assumes that the patient has been asked (and has consented or declined) for cross-network disclosure under the applicable jurisdictional and use-case framework. The mechanism for asking is not the matcher's job; it is the registration workflow's, the patient-portal app's, and (for clinical-care contexts) the institutional consent-management workflow's. Build the consent-capture and withdrawal-pathway as a deliberate workflow with appropriate framing, training for the staff who solicit the information, and patient-facing communication about what cross-network disclosure does and what consent withdrawal means at federation scale (the retrospective limits are real; the institution can stop future disclosures but cannot retract records already disclosed to other participants). Skip this and the consent posture is operating on default values that may not match the patient's actual preferences, with predictable trust failures when patients discover their records were disclosed in cross-network queries they did not consent to.

**Information-blocking compliance posture.** The 21st Century Cures Act information-blocking provisions create an obligation to share patient records on request, with specific exceptions defined by the rule. The architecture has to handle the information-blocking compliance as an operational concern: the local matcher's response has to be either a confident match, a no-confident-match indication, or a denied-under-exception response with the exception code; silent drops are operationally non-compliant. Build the information-blocking-compliance pipeline with explicit handling of the rule's exceptions (Privacy Exception, Security Exception, Infeasibility Exception, Health IT Performance Exception, Content and Manner Exception, Fees Exception, Licensing Exception) and explicit operational metrics on each exception's invocation rate. <!-- TODO: confirm at time of build; the information-blocking rule's exceptions continue to be interpreted through ONC enforcement guidance. -->

<!-- TODO (TechWriter): Expert review S6 (LOW). Architect the information-blocking-exception handling pipeline as a per-exception evaluation Lambda invoked at the response-formulation stage. Specify (1) the per-exception evaluation discipline with structured "denied-under-exception" responses carrying the rule-specified exception code, rationale, and timing; (2) the per-exception CloudWatch metric and alarm thresholds (Infeasibility-Exception > 5% = MEDIUM; Privacy-Exception > 10% = MEDIUM; Content-and-Manner-Exception > 1% = HIGH; aggregate > 20% = HIGH); (3) the slower-tier review escalation pathway as a Step Functions workflow with response-window-tracking and rule-specified-timing as the workflow's deadline, producing a structured Health-IT-Performance-Exception response when the timeline cannot be met; (4) audit logging on every exception invocation with the inputs that drove the decision. -->

**Cross-jurisdictional overlay automation.** The per-jurisdiction overlay rules accumulate as the framework's geographic scope grows. The architectural extension is an overlay-rules engine that consumes the patient's residence jurisdiction, the requesting participant's jurisdiction, the responding participant's jurisdiction, the use case's authorization scope, and the record-type sensitivity classification, and produces a per-record disclosure decision. The overlay rules are versioned and reviewed on a regulatory-monitoring cadence (post-legislative-session and post-court-decision are the typical triggers). The pattern is operationally important for participants operating across multiple states with diverging post-Dobbs, post-Bostock, and gender-affirming-care state-law overlays.

<!-- TODO (TechWriter): Expert review A3 (MEDIUM). Promote the overlay-rules engine architecture (versioned rule store in DynamoDB or a dedicated configuration store; rule-evaluation Lambda invoked at query-formulation time and at query-handling time; output disclosure-decision metadata stored on the response envelope), the regulatory-monitoring function (shared between privacy and compliance teams; legislative-session feeds with explicit per-state subscription, RCE-bulletin subscriptions, court-decision tracking; trigger thresholds with relevance-evaluation criteria), the per-query disclosure-decision audit trail (every overlay-rule application audit-logged with inputs, rule version active, output decision), and the framework-update pathway (regulatory-change-detection through the regulatory-monitoring function; framework-update through the institutional governance committee; coordinated re-deployment across the participant's TEFCA gateway; downstream-consumer notification through the EventBridge fan-out) into the architecture pattern. -->

**Idempotency and retry semantics.** The pipeline must handle duplicate-event delivery, partner-side retries, and Lambda re-runs without producing duplicate audit events, duplicate document-store persistences, or scrambled attribution chains. Use the (query_id, hop_id) tuple as the idempotency key for audit-event writes; use (query_id, candidate_token, document_id) for the document-store persistence; use (dispute_id, escalation_event_id) for the dispute-resolution events. Configure DLQs on every Lambda path; Step Functions Catch states route terminal failures to the DLQ so stuck workflows are visible. Same chapter pattern as 5.3, 5.4, 5.5, 5.6, 5.7, 5.8.

<!-- TODO (TechWriter): Expert review A5 (MEDIUM). Promote the idempotency keys into the General Architecture Pattern paragraph with the recipe-specific per-stage keys: inbound-query-handler Lambda `(query_id, hop_id)`; outbound-query-formulator Lambda `(query_id, attribution_chain_hash)`; response-consolidator Lambda `(query_id, responder_id)`; document-retrieval-handler Lambda `(query_id, candidate_token, document_id)`; dispute-handler Lambda `(dispute_id, escalation_event_id)`; governance-evolution-handler Lambda `(governance_change_id, evaluation_event_id)`; QHIN-credential-rotation-coordinator Step Functions `(rotation_id, hop_id)`. Specify the DLQ-per-stage topology and CloudWatch alarms on DLQ depth (typically > 0 records or > 15 minutes for stuck workflows). -->

**Cohort-stratified accuracy monitoring discipline.** The CloudWatch metrics with cohort-axis dimensions, the QuickSight dashboard, the institutional review cadence, and the disparity-alarm thresholds are architecture-level commitments, not bolt-ons. Specify the operational thresholds, the per-axis aggregation, the disparity-metric definitions, and the institutional response protocol. Cohort-stratified match-rate disparity > 0.10 = MEDIUM alarm; cohort-stratified false-acceptance-rate disparity > 0.02 = HIGH (because false acceptances at federation scale produce wrong-record disclosures that the originating participant cannot retract from the consumer). Same chapter pattern as 5.1, 5.4, 5.5, 5.6, 5.7, 5.8. The privacy team is an explicit reviewer for this recipe in addition to the standard analytics-governance committee, because cohort-stratified disparities at federation scale interact with the framework's privacy-and-equity expectations.

<!-- TODO (TechWriter): Expert review A1 (HIGH). Promote the cohort-stratified accuracy thresholds and metric definitions into the General Architecture Pattern. Specify (a) the recipe-specific cohort axis enumeration (inherited from 5.7 and 5.8 plus federation-specific extensions: geographic-region cohort, jurisdictional-overlay cohort, responder-quality-tier cohort, patient-consent-for-fairness-monitoring cohort, cross-jurisdictional-overlay cohort); (b) the disparity-calculation method (absolute difference between highest and lowest cohort, computed per-metric per-cycle); (c) the per-metric emission cadence (match rate weekly, false-acceptance rate weekly, response-time aging weekly, sampled error rate monthly); (d) the privacy-team routing with explicit federation-equity-evaluation authority; (e) the framework-equity translation (cohort disparities at federation scale are simultaneously fairness signals and framework-compliance signals); and (f) the remediation pathway (alert routing, investigation, post-mortem retention with 5-business-day SLA, quarterly review by federation-participation steering committee with privacy-team co-chair). -->

**Compliance and operational ownership.** TEFCA participation sits at the intersection of analytics, clinical operations, compliance, privacy, security, IT, legal, and patient-advocacy. Establish clear operational ownership: who tunes the cross-network tolerance, who reviews the cohort-disparity reports, who owns the QHIN-credential rotations, who handles the dispute-resolution coordination, who responds to consent withdrawals, who negotiates Participant Agreement changes, who owns the framework-evolution program. The pipeline works only when the operational ownership is clear and funded across the institution, not just within the IT or analytics organization.

<!-- TODO (TechWriter): Expert review A6 (MEDIUM). Specify the cross-recipe event contract for the EventBridge fan-out reaching recipes 5.5, 5.6, 5.7, 5.8, and per-participant operational systems. Specify the chapter-wide event schema (`source`, `detail_type`, `detail.query_id`, `detail.event_id`, `detail.attribution_chain`, `detail.exchange_purpose`, `detail.qhin_credential_version`, `detail.responder_quality_tier`, `detail.cohort_stratified_summary`, `detail.consent_posture_summary`, `detail.jurisdictional_overlay_applicability`, `detail.detected_at`), the access-control-envelope-aware routing (standard channel vs restricted channel for differentially-private-aggregate or encrypted-match-indicator disclosure forms), the consumer-side signature validation, the schema-versioning policy, and the per-event-source allow-list (per-event-type allowed producers). -->

<!-- TODO (TechWriter): Expert review A7 (MEDIUM). Promote the patient-mediated TEFCA flow into the architecture pattern. Specify (1) the patient-authentication path through the participant's patient-portal IdP (Cognito federation; per-patient authentication-to-source-record-id binding through Lambda authorizers; abuse-prevention rate-limiting at the API Gateway layer below the staff-initiated query rate limits); (2) the per-patient authorization-to-source-record-id binding (Lambda authorizer consults the participant's local authorization store; rejection on binding-failure); (3) the patient-mediated audit-attribution discipline (patient-mediated queries audit-logged with explicit "patient-mediated" attribution; per-patient audit summary delivery to the patient's chosen channel); (4) the patient-mediated rejection-on-attribution-failure semantics. -->

<!-- TODO (TechWriter): Expert review A8 (MEDIUM). Architect the cross-QHIN attribution-chain reconstruction workflow. Specify (1) the dispute-intake mechanism (dedicated API endpoint with QHIN-credential authentication; dispute-tracking DynamoDB table keyed on (dispute_id, escalation_event_id); audit-archive bucket for dispute artifacts); (2) the cross-QHIN audit-log-export interface (per-dispute access-control envelope with time-bound and scope-bound authorization; per-QHIN audit-log-export Lambda invoked through Step Functions cross-QHIN orchestration; audit logging on every cross-QHIN audit-log-export); (3) the dispute-resolution-outcome propagation (outcome propagated through the EventBridge fan-out with explicit dispute-outcome event-types: "dispute-resolved" / "dispute-held" / "dispute-escalated"). -->

<!-- TODO (TechWriter): Expert review A9 (MEDIUM). Architect the federation-scale capacity coordination. Specify (1) the participant-side capacity-reservation tooling (capacity-coordination event consumer Lambda; per-source rate-limit configuration store in DynamoDB; rate-limit-update Lambda; CloudWatch metrics on per-source rate-limit utilization); (2) the per-source rate-limiting discipline (per-source quota in DynamoDB; rate-limit-evaluation Lambda at inbound-query-handling time; rejection semantics for rate-limit breaches with explicit fail-fast and audit logging); (3) the QHIN operational-interface integration (participant-to-QHIN capacity-status emission per-cycle; QHIN-to-participant capacity-coordination signal consumption; audit-and-monitoring discipline on both directions); (4) the federation-wide capacity-coordination cascade-mitigation (per-source error-rate monitoring with escalation thresholds; per-source automatic-circuit-breaker; priority routing for capacity-coordination events). -->

---

## The Honest Take

National-scale patient matching is the recipe in this chapter where the technical complexity is moderate (the matching core is the same as the other chapter recipes, with the federation-routing extension), the integration complexity is significant (the QTF, the IHE-and-FHIR convergence, the multi-protocol authentication), the operational complexity is high (the federation's response patterns, the capacity dynamics, the cross-QHIN coordination), and the human-and-organizational complexity is the load-bearing concern. The framework is real, the operational rhythms are emerging, and the participants who succeed are the ones who treat TEFCA participation as a multi-year program with explicit institutional-capability investment rather than as a project that ends with the QHIN onboarding.

The trap most specific to TEFCA is treating the QHIN onboarding as the finish line. The onboarding is the starting line. The continuous operational discipline (the credential rotations, the framework-evolution responses, the dispute-resolution coordination, the cross-jurisdictional-overlay updates, the cohort-stratified-accuracy monitoring, the patient-consent-management, the information-blocking-compliance posture, the capacity coordination, the audit-trail maintenance) is what determines whether the participant operates effectively in the federation or drifts into operational inadequacy. The institutions that succeed have an explicit federation-participation program with named ownership, named processes, named milestones, and named review committees; the institutions that treat TEFCA as an IT project with a defined end discover, during the first year of post-onboarding operation, that the operational substrate cannot support the framework's continuous demands.

The second trap is under-investing in the cross-network-tolerance calibration. The institutional matching infrastructure has been calibrated for internal use cases over years of operation. The federation expects a different tolerance, and re-using the internal tolerance silently drops the federation's queries that the participant should respond to. The information-blocking compliance posture compounds this: silent drops are operationally non-compliant, and the participant whose queries are silently dropped at scale can face an enforcement action. The mitigation is explicit dual-calibration with the cross-network tolerance pinned per use case, with regular re-calibration as the federation's data quality and the framework's expectations evolve.

The third trap, related: under-investing in the cross-jurisdictional overlay engine. The post-Dobbs state laws, the gender-affirming-care state laws, the 42 CFR Part 2 substance-use-treatment record handling, the HIV-and-genetic-information state-specific rules, the juvenile-record state-specific rules, and the various other jurisdictional overlays accumulate as the framework's geographic scope grows. Each overlay has to be evaluated at every hop in the routing layer; the cumulative overhead grows non-linearly with the overlay landscape. The institutions that operate the overlay engine well have invested in the versioned overlay-rule engine, the regulatory-monitoring function, and the per-query disclosure-decision audit trail; the institutions that treat the overlay handling as an ad-hoc concern discover, when the next state law lands, that the participant's operational substrate cannot accommodate the new overlay in the framework's specified window.

The thing that surprises people coming from other identity-pipeline backgrounds is how much of the work is in the participant-side operational discipline rather than in the framework itself. The framework specifies the technical interoperability (the QTF, the SOPs, the standard message formats); the framework does not specify the participant-side operational discipline that makes the technical interoperability work in practice. The participant-side discipline includes the calibration of the local matcher to the federation's expectations, the maintenance of the audit-and-attribution layer to the framework's specifications, the negotiation of the cross-jurisdictional-overlay landscape, the management of the patient-consent posture, the coordination with the QHIN's operational interface, the response to the framework's evolution. None of these are framework concerns; all of them are participant concerns, and the participant has to build the institutional capability to handle them.

The thing about the federation's accuracy ceiling: the federation's match accuracy is bounded above by the data quality of the constituent records, which at national scale includes the worst-quality participant. The originating participant's matcher consumes the federation's responses without distinguishing the high-quality responders from the low-quality responders; the consolidated view is necessarily a heterogeneous mix. The mitigation is per-responder match-quality monitoring with explicit degradation alerts and a cross-QHIN escalation path for chronically-low-quality responders; the participant cannot fix another participant's data quality but can choose to weight the candidates by responder quality in the consolidated view, with explicit user-facing communication about the weighting. The framework as a whole has to evolve toward responder-quality discipline, and the evolution is in progress but uneven.

The thing about the patient-experience layer: it is uneven across the framework, and the unevenness undermines patient trust. The patient who exercises individual access services through three different personal-health-record apps gets three different views of her record, none of them complete. The framework's individual-access-services exchange purpose is operationally functional but not yet experientially consistent. The participants that contribute to the experiential consistency (by ensuring their records are reachable through individual access services consistently, by providing patient-facing communication about their cross-network participation, by honoring patient consent withdrawals operationally) are the ones whose patients trust the framework. The participants that treat individual access services as an afterthought discover, when patients begin to compare experiences across QHINs, that the lack of consistency erodes the trust that the framework needs to operate.

The thing about cross-QHIN dispute resolution: it is operationally non-trivial, and it is where the framework's maturity is most visible. A dispute requires reconstructing the full attribution chain across multiple QHINs' audit substrates, coordinating across the participating QHINs' operational interfaces, and resolving the dispute under the framework's governance mechanism. The dispute-resolution timelines are long (weeks to months for non-trivial disputes); the operational discipline is patience as much as engineering. The institutions that handle disputes well have invested in the per-query attribution-chain capture in the local audit at the design stage, the dispute-resolution playbook with named owners and named processes, and the relationships with the QHIN's operational interface that let the institution navigate the dispute mechanism efficiently.

The thing about the framework's evolution: it outpaces the participant's adoption rate. Changes to the Common Agreement, the QTF, the SOPs, the jurisdictional-overlay-rule landscape, and the framework's operational rhythms evolve continuously. The participants that fall behind the framework's evolution can lose their participation status under the framework's governance. The mitigation is the governance-evolution program with named owners, named processes, and explicit timeline-tracking against the framework's mandates; without it, the participant's operational substrate diverges from the framework's expectations and the participant's effective participation degrades.

The thing about the institutional learning curve: it is substantial, and most institutions underestimate it. Operating a TEFCA participant well requires institutional capabilities (federation-aware engineering, federation-aware compliance, federation-aware operations, federation-aware governance) that most institutions are still building. The capabilities take years to develop, with explicit investment in the people, processes, and tooling that make federation participation effective. The institutions that have made the investment deliberately operate the framework well; the institutions that have not made the investment, regardless of how much engineering they put into the technical layer, struggle with the framework's continuous demands.

The thing I would do differently the second time: invest in the federation-participation program at the institutional governance level before scoping the engineering work. The first version will treat the framework as a technical-integration project that the IT or analytics organization can execute. The second version will recognize that the framework is a multi-disciplinary operational program that requires investment from compliance, privacy, legal, clinical operations, patient advocacy, security, IT, and analytics, with explicit coordination across all of them. Fund the program at the institutional level; let the engineering work serve the program's broader institutional capabilities rather than driving them.

The thing about the framework's long-term viability: it depends on the participants' continued investment and on the framework's continued evolution. The framework is real and operational, but it is not yet stable, and the institutions that operate it well are betting on its long-term success. The bet is reasonable (the alternative, an indefinite continuation of the fragmented pre-TEFCA exchange landscape, is worse), but it is a bet that requires patience and continued institutional commitment. The participants that succeed are the ones who treat the framework as infrastructure that the institution invests in continuously, not as a project that delivers a one-time capability and then moves on.

Last point, because it is specific to the use case: TEFCA is the substrate for population-scale exchange that the U.S. has been trying to build for decades. It is finally operational; it is not yet mature; it is moving in the right direction. The institutions that participate in it well are the ones who help shape its evolution through their operational practice, their feedback to the framework's governance, and their continued investment in the institutional capabilities that the framework demands. The framework's future is the cumulative outcome of the participants' practice, not the framework's design alone. Treating the participation as a contribution to the framework's evolution, rather than as a consumption of the framework's services, is the posture that the institutions whose participation is most effective have adopted.

---

## Variations and Extensions

**QHIN-operator architecture.** Rather than operating as a participant in someone else's QHIN, the institution operates its own QHIN, signing the Common Agreement directly and providing federation services to its own participants and to other QHINs. The architectural extension is the cross-QHIN router (the inverse of the participant-side query handler: the router accepts queries from external QHINs and routes them to the QHIN's participants), the QHIN's operational interface (governance and dispute coordination with other QHINs), and the QHIN's participant-onboarding pipeline (each new participant is onboarded with technical certification, governance review, operational testing). The QHIN role is a substantially larger operational program than the participant role; the institutions that succeed as QHINs are typically established health-information networks, vendor-mediated networks, or large integrated-delivery networks with the operational maturity to absorb the role's demands.

**FHIR-based exchange migration.** As the framework's FHIR-based exchange patterns mature, the participant migrates from IHE-based exchange (XCPD for patient discovery, XCA for cross-community access) to FHIR-based exchange (the Patient $match operation, the Bulk FHIR specification for population-scale queries). The architectural extension is a parallel FHIR-based gateway that operates alongside the IHE-based gateway during the migration window, with explicit cross-format compatibility (queries arriving in one format produce responses in either format depending on the responder's capability). The migration is operational rather than just technical: the FHIR-based exchange has different audit-and-attribution conventions, different authentication patterns, different error semantics, and the institution's operational discipline has to span both formats during the migration. <!-- TODO: confirm at time of build; the FHIR-based exchange migration is in progress as the QTF specifies the FHIR-based variants; the migration timeline depends on the QHINs' operational adoption. -->

**Patient-mediated access through the Patient Access API.** The CMS Patient Access API rule and the ONC information-blocking rule have created regulatory pressure for patient-mediated access. The architectural extension is a patient-mediated query path that operates alongside the staff-initiated path: the patient's personal-health-record app authenticates the patient through the participant's patient-portal IdP, the app initiates the cross-network query under the patient's authorization, the federation's responses are consolidated and returned to the app, and the app presents the unified longitudinal view to the patient. The pattern is becoming a non-trivial fraction of cross-network query traffic at the QHINs that have integrated it, and the institutional integration is a separate operational program with its own technical specifications, its own user-experience considerations, and its own audit-and-attribution requirements.

**Federated analytics extension.** TEFCA's primary focus is record exchange for treatment-and-operational use cases; federated analytics (queries that aggregate across participants without retrieving individual records) is a natural extension that leverages the same federation routing infrastructure for population-scale queries. The architectural extension is an analytics-query handler that consumes federated-aggregate queries from research consortia, public-health agencies, or other authorized analytic consumers, runs the aggregate computation against the participant's local data under the appropriate authorization framework, and returns the aggregated results without exposing the individual records. The pattern complements the privacy-preserving record linkage from recipe 5.8 and provides a population-scale analytic substrate that does not require record-level disclosure. <!-- TODO: confirm at time of build; the federated-analytics integration with TEFCA is being discussed at the framework-governance level; the operational specifics continue to evolve. -->

**Privacy-preserving cross-organizational matching through TEFCA's routing layer.** Recipe 5.8's privacy-preserving record linkage operates between two or more participating organizations under a multi-party trust framework. The architectural extension is to leverage TEFCA's routing layer for the cross-organizational exchange portion of the PPRL pipeline: the encoded payloads route through the QHIN's federation rather than through a separate point-to-point exchange. The pattern reduces the operational overhead of bilateral exchange relationships and lets the PPRL pipeline operate at federation scale; the trade-off is that the QHIN's framework's authentication and authorization layer has to accommodate the PPRL-specific data flows (which are not standard TEFCA exchange purposes as of writing). <!-- TODO: confirm at time of build; the PPRL-and-TEFCA integration is an emerging pattern that is not yet standardized; the institutional adoption depends on bilateral trust frameworks negotiated outside the standard TEFCA exchange purposes. -->

**Cross-recipe coordination with longitudinal name-change handling.** Recipe 5.7's longitudinal-name-change handling produces an identity-history representation that the participant maintains for its own MPI. The architectural extension is propagating the identity-history representation into the cross-network matcher's tolerance: a query that arrives under a patient's prior name should match against the identity's prior name (with the appropriate temporal weighting) rather than only against the current name. The cross-network response includes the per-record identity-history attribution where the framework's specifications permit; the federation as a whole evolves toward identity-history-aware matching as the participating MPIs mature.

**Sensitivity-flag coordination across the federation.** Recipe 5.7 introduces sensitivity flags for gender-affirming-care records, witness-protection records, and other sensitivity-classified records. The architectural extension is propagating the sensitivity flags through the cross-network response (the responder indicates the candidate is sensitivity-flagged without exposing the underlying classification reason; the originating participant honors the flag in the consolidated view by suppressing the candidate's demographic features or by routing the candidate to a more-restrictive disclosure form). The framework as a whole evolves toward sensitivity-aware matching, with the per-jurisdiction overlay rules providing the regulatory baseline.

**Information-blocking-exception handling automation.** The information-blocking rule's exceptions (Privacy Exception, Security Exception, Infeasibility Exception, Health IT Performance Exception, Content and Manner Exception, Fees Exception, Licensing Exception) provide structured ways for the participant to decline a query without violating the rule. The architectural extension is an exception-handling pipeline that evaluates each query's circumstances against the applicable exceptions, returns a structured "denied-under-exception" response with the exception code, and audit-logs the denial decision with the inputs that led to the exception's invocation. The pattern is operationally important for participants whose queries cannot be handled in the standard response window or whose policy excludes specific record types from the standard exchange purposes.

**Capacity coordination across QHINs.** The federation-wide capacity dynamics are coordinated through the QHIN's operational interface. The architectural extension is participant-side capacity-reservation tooling that consumes the QHIN's capacity-coordination signals, adjusts the participant's local rate-limiting and capacity-reservation in response, and emits the participant's capacity status back to the QHIN. The pattern is becoming operationally important as the federation's volume grows and as the cascade dynamics of capacity events become more visible.

**Active-learning-driven cross-network-tolerance tuning.** As the cross-network-match-review queue resolves cases, the labels feed a periodic re-training of the cross-network tolerance and the per-feature weights. Active learning concentrates the review effort on the cases that most improve the downstream accuracy and the cohort fairness; over time, the review queue depth decreases as the matcher absorbs the labeled cases. The active-learning pattern is constrained by the cross-network-data limitation (the labels are on the federation's responses, not on the responder's underlying records; the calibration has to be careful about which signals it can extract from the federation's response without overstepping the framework's specifications).

**Audit-summary delivery to the patient.** As part of the patient-experience layer, the patient may opt to receive periodic summaries of how her record has been queried across the federation, with the queries, the requesting participants, the use cases, the disclosure forms, and the responding sources identified. The architectural extension is a patient-portal summary-delivery service that aggregates the per-query inclusion records (filtered to the patient's own data) and delivers them on the patient's chosen cadence. The pattern is becoming an expected disclosure for patients in jurisdictions with strong data-rights regulations and is consistent with the framework's individual-access-services exchange purpose.

**Cross-jurisdictional overlay-rule federation.** Rather than each participant maintaining its own overlay-rule engine independently, a shared overlay-rule federation lets participants subscribe to a common rule store with explicit per-jurisdiction subscriptions. The architectural extension is the rule-federation publisher (which curates the per-jurisdiction overlay rules from the regulatory-monitoring function and publishes them to subscribers), the rule-federation subscriber (which consumes the published rules and integrates them with the participant's local overlay-rule engine), and the rule-version-coordination layer (which ensures the rule versions across the federation are consistent). The pattern reduces the per-participant overhead of maintaining the overlay-rule engine independently and produces a more consistent overlay-rule application across the federation.

---

## Related Recipes

- **Recipe 5.1 (Internal Duplicate Patient Detection):** The local MPI is the canonical patient identity that the cross-network matcher consults under the cross-network tolerance. Identity merges in 5.1 propagate to the cross-network matcher; the cross-network responses reflect the post-merge identity state.
- **Recipe 5.2 (Provider NPI Matching):** Provider attribution in cross-network responses uses NPI as the strong anchor; the cross-network response includes the responding source's NPI, which feeds the per-source attribution chain.
- **Recipe 5.3 (Address Standardization and Household Linkage):** The address-feature normalization in cross-network queries depends on the standardized address from recipe 5.3; the QTF specifies USPS-standardized address formats for the demographic-feature payload.
- **Recipe 5.4 (Insurance Eligibility Matching):** Cross-payer eligibility matching may operate through TEFCA's payment exchange purpose for payers participating in the federation; the cross-payer responses feed the eligibility matching pipeline.
- **Recipe 5.5 (Cross-Facility Patient Matching):** The within-HIE cross-facility matcher is the substrate that the cross-network matcher operates above. The recipes share the cross-organizational matching structure but operate at different scales (HIE-level vs federation-level).
- **Recipe 5.6 (Claims-to-Clinical Data Linkage):** Claims-clinical linkage may operate through TEFCA's payment and operations exchange purposes for cross-organizational use cases; the linkage's payer-side or provider-side records may flow through the federation's routing layer.
- **Recipe 5.7 (Longitudinal Patient Matching Across Name Changes):** The identity-history representation from 5.7 feeds the cross-network matcher's tolerance under the temporal-aware-matching extension. Sensitivity flags from 5.7 propagate through the cross-network response under the sensitivity-aware-matching extension.
- **Recipe 5.8 (Privacy-Preserving Record Linkage):** PPRL may operate through TEFCA's routing layer for cross-organizational use cases where the trust framework prohibits direct exchange. The cross-network matcher's response can be a PPRL-encoded payload rather than a plaintext demographic-feature payload, depending on the use case.
- **Recipe 5.10 (Deceased Patient Resolution):** Deceased-patient events from 5.10 propagate to the cross-network matcher; the cross-network responses suppress deceased-patient candidates per the use-case-appropriate handling.
- **Recipe 7.x (Predictive Analytics):** Cohort definitions for risk-scoring may depend on cross-network linkages; the federated-analytics extension provides the population-scale analytic substrate for predictive analytics.
- **Recipe 8.x (NLP / Traditional NLP):** Cross-organizational text-mining use cases may require the federation's routing layer to retrieve clinical notes from multiple participating organizations.
- **Recipe 13.x (Knowledge Graphs):** Federated knowledge-graph construction across organizations may use TEFCA's routing layer for the entity-linkage step at federation scale.

---

## Additional Resources

**AWS Documentation:**
- [Amazon API Gateway Developer Guide](https://docs.aws.amazon.com/apigateway/latest/developerguide/welcome.html)
- [AWS WAF Developer Guide](https://docs.aws.amazon.com/waf/latest/developerguide/waf-chapter.html)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [Amazon DynamoDB Developer Guide](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html)
- [Amazon RDS for Aurora User Guide](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/CHAP_AuroraOverview.html)
- [Amazon ElastiCache for Redis User Guide](https://docs.aws.amazon.com/AmazonElastiCache/latest/red-ug/WhatIs.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [Amazon S3 User Guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html)
- [Amazon EventBridge User Guide](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html)
- [Amazon Cognito Developer Guide](https://docs.aws.amazon.com/cognito/latest/developerguide/what-is-amazon-cognito.html)
- [AWS Secrets Manager User Guide](https://docs.aws.amazon.com/secretsmanager/latest/userguide/intro.html)
- [AWS Key Management Service Developer Guide](https://docs.aws.amazon.com/kms/latest/developerguide/overview.html)
- [AWS CloudHSM User Guide](https://docs.aws.amazon.com/cloudhsm/latest/userguide/introduction.html)
- [Amazon SageMaker Developer Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html)
- [Amazon Athena User Guide](https://docs.aws.amazon.com/athena/latest/ug/what-is.html)
- [AWS Lake Formation Developer Guide](https://docs.aws.amazon.com/lake-formation/latest/dg/what-is-lake-formation.html)
- [AWS PrivateLink Documentation](https://docs.aws.amazon.com/vpc/latest/privatelink/what-is-privatelink.html)
- [Amazon QuickSight User Guide](https://docs.aws.amazon.com/quicksight/latest/user/welcome.html)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)

**AWS Sample Repos:**
- [`aws-samples/serverless-patterns`](https://github.com/aws-samples/serverless-patterns): API Gateway + Lambda + DynamoDB patterns applicable to the per-query handler logic
- [`aws-samples/aws-secrets-manager-rotation-lambdas`](https://github.com/aws-samples/aws-secrets-manager-rotation-lambdas): Secret rotation patterns applicable to the QHIN-credential and signing-key rotation
<!-- TODO: confirm the current names and locations of these repos at time of build. -->

**AWS Solutions and Blogs:**
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter Healthcare and Life Sciences): browse for healthcare-data-exchange and interoperability reference architectures
- [AWS for Industries: Healthcare and Life Sciences Blog](https://aws.amazon.com/blogs/industries/category/industries/healthcare/): search "TEFCA," "interoperability," "FHIR," "health information exchange" for relevant deep-dives
- [AWS Architecture Blog](https://aws.amazon.com/blogs/architecture/): search "FHIR," "healthcare interoperability," "API Gateway healthcare" for relevant patterns
<!-- TODO: replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs. -->

**External References (Standards and Frameworks):**
- [The Sequoia Project (Recognized Coordinating Entity for TEFCA)](https://sequoiaproject.org/): the operational entity that administers the QHIN designation process and operates the cross-QHIN exchange infrastructure
- [ONC Trusted Exchange Framework and Common Agreement (TEFCA)](https://www.healthit.gov/topic/interoperability/policy/trusted-exchange-framework-and-common-agreement-tefca): the regulatory foundation for TEFCA
- [The Common Agreement](https://rce.sequoiaproject.org/): the legal contract that QHINs sign with the RCE and with each other <!-- TODO: confirm current URL at time of build. -->
- [QHIN Technical Framework (QTF)](https://rce.sequoiaproject.org/): the technical specification for cross-QHIN interoperability <!-- TODO: confirm current URL at time of build. -->
- [21st Century Cures Act Information Blocking Rule](https://www.healthit.gov/topic/information-blocking): the regulatory framework that interacts with TEFCA-mediated exchange
- [HL7 FHIR](https://www.hl7.org/fhir/): the FHIR specification including the Patient $match operation
- [FHIR Patient $match Operation](https://www.hl7.org/fhir/patient-operation-match.html): the FHIR-based patient-discovery operation that the QTF references for FHIR-based exchange
- [IHE International](https://www.ihe.net/): the integration profiles (XCPD for cross-community patient discovery, XCA for cross-community access) that the QTF references for IHE-based exchange
- [HIPAA Privacy Rule](https://www.hhs.gov/hipaa/for-professionals/privacy/index.html): the foundational regulatory framework
- [42 CFR Part 2](https://www.ecfr.gov/current/title-42/chapter-I/subchapter-A/part-2): the substance-use-treatment record disclosure framework that imposes specific constraints on TEFCA-mediated exchange <!-- TODO: confirm current URL at time of build. -->

**External References (Industry):**
- [Carequality](https://carequality.org/): the pre-TEFCA national interoperability framework whose patterns inform some of TEFCA's operational specifications
- [eHealth Exchange](https://ehealthexchange.org/): one of the pre-TEFCA national exchange networks that has transitioned to QHIN designation <!-- TODO: confirm current URL and TEFCA-status at time of build. -->
- [The Office of the National Coordinator for Health Information Technology (ONC)](https://www.healthit.gov/): the federal agency that authorizes the TEFCA framework and operates information-blocking rule enforcement
- [Sequoia Project Patient Matching Framework](https://sequoiaproject.org/): industry-developed framework for patient-matching that informs the cross-network matching expectations <!-- TODO: confirm current URL at time of build. -->
- [HIMSS Interoperability Resources](https://www.himss.org/): industry-association resources on healthcare interoperability including TEFCA implementation guidance <!-- TODO: confirm current URL at time of build. -->

---

## Estimated Implementation Time

| Tier | Scope | Time |
|------|-------|------|
| Basic | Single-QHIN participant integration with one exchange purpose (treatment), IHE-based exchange (XCPD and XCA), basic cross-network-tolerance calibration, standard authentication and authorization, basic audit-and-attribution layer, single-jurisdiction-overlay handling | 9-15 months (including QHIN onboarding) |
| Production-ready | Multi-QHIN participant integration with multiple exchange purposes (treatment, payment, operations, individual access services), IHE-and-FHIR-based exchange with parallel gateway support, dual-calibrated tolerances per use case, full authentication-and-authorization framework with QHIN-credential rotation ceremony, full audit-and-attribution layer with cross-QHIN attribution chain capture, multi-jurisdiction-overlay engine with regulatory-monitoring function, three-queue review tooling (cross-network-match-review, dispute-review, governance-evolution), patient-mediated access through Patient Access API, information-blocking-exception handling, complete CloudTrail and audit-retention posture, consent-capture and consent-withdrawal pathways with patient-facing communication, capacity-coordination tooling | 18-36 months (including QHIN onboarding and federation-participation program ramp) |
| With variations | Add QHIN-operator architecture, FHIR-based exchange migration, federated analytics extension, PPRL-and-TEFCA integration, identity-history-aware cross-network matching, sensitivity-flag coordination, capacity-coordination across QHINs, active-learning-driven tolerance tuning, audit-summary delivery to patient, cross-jurisdictional overlay-rule federation | 12-24 months beyond production-ready |

---

## Tags

`entity-resolution` · `record-linkage` · `national-scale-matching` · `tefca` · `qhin` · `common-agreement` · `qtf` · `cross-organizational-matching` · `federation` · `cross-network-routing` · `ihe` · `xcpd` · `xca` · `fhir` · `patient-match` · `bulk-fhir` · `patient-access-api` · `individual-access-services` · `cross-jurisdictional-overlay` · `post-dobbs` · `gender-affirming-care` · `42-cfr-part-2` · `information-blocking` · `cures-act` · `patient-mediated-access` · `cross-qhin-coordination` · `dispute-resolution` · `audit-attribution` · `consent-management` · `multi-organization-governance` · `api-gateway` · `lambda` · `dynamodb` · `aurora-postgresql` · `elasticache` · `step-functions` · `eventbridge` · `cognito` · `secrets-manager` · `kms` · `cloudhsm` · `lake-formation` · `event-driven` · `complex` · `production` · `hipaa` · `equity-monitoring` · `responder-quality` · `federated-analytics`

---

*← [Recipe 5.8: Privacy-Preserving Record Linkage](chapter05.08-privacy-preserving-record-linkage) · Chapter 5 · [Next: Recipe 5.10 - Deceased Patient Resolution and Record Reconciliation →](chapter05.10-deceased-patient-resolution)*
