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

```text
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


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter05.09-architecture). The Python example is linked from there.

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

## Tags

`entity-resolution` · `record-linkage` · `national-scale-matching` · `tefca` · `qhin` · `common-agreement` · `qtf` · `cross-organizational-matching` · `federation` · `cross-network-routing` · `ihe` · `xcpd` · `xca` · `fhir` · `patient-match` · `bulk-fhir` · `patient-access-api` · `individual-access-services` · `cross-jurisdictional-overlay` · `post-dobbs` · `gender-affirming-care` · `42-cfr-part-2` · `information-blocking` · `cures-act` · `patient-mediated-access` · `cross-qhin-coordination` · `dispute-resolution` · `audit-attribution` · `consent-management` · `multi-organization-governance` · `api-gateway` · `lambda` · `dynamodb` · `aurora-postgresql` · `elasticache` · `step-functions` · `eventbridge` · `cognito` · `secrets-manager` · `kms` · `cloudhsm` · `lake-formation` · `event-driven` · `complex` · `production` · `hipaa` · `equity-monitoring` · `responder-quality` · `federated-analytics`

---

*← [Recipe 5.8: Privacy-Preserving Record Linkage](chapter05.08-privacy-preserving-record-linkage) · Chapter 5 · [Next: Recipe 5.10 - Deceased Patient Resolution and Record Reconciliation →](chapter05.10-deceased-patient-resolution-reconciliation)*
