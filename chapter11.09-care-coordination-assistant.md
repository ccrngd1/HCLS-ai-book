# Recipe 11.9: Care Coordination Assistant

**Complexity:** Complex · **Phase:** Regulated · **Estimated Cost:** ~$3-12 per active member per month (depends on member acuity, channel mix, model choice, RAG depth, referral-tracking integration depth, and clinical-escalation overhead)

---

## The Problem

David is 67. He has heart failure, atrial fibrillation, Type 2 diabetes, chronic kidney disease stage 3b, mild cognitive impairment, and a left hip that has been threatening him for two years. He lives with his wife, who is 65 and herself has osteoarthritis and an anxiety disorder that gets worse when David's health gets worse. David's care, on paper, looks well-organized. He has a primary care physician at one health system, a cardiologist at the same health system, an electrophysiologist at a second health system who manages his AFib (because his original cardiologist retired and the referral landed there), an endocrinologist at the first health system, a nephrologist who is part of a third practice but admits at the second health system, an orthopedic surgeon he saw once at a fourth health system about the hip, a primary pharmacy, a mail-order pharmacy for the medications his insurance routes that way, an at-home anticoagulation service that draws labs every two weeks, a home-health aide three days a week, a Medicare Advantage care manager assigned by his payer, a hospital case manager from the last admission, and a wife who does a great deal of the actual coordination on a paper calendar in their kitchen.

In the eight weeks since David's last hospitalization for fluid overload, the following has happened. The cardiologist titrated up his diuretic. The nephrologist saw the lab result the next week and was concerned about the rising creatinine. The nephrologist's office sent a fax to the cardiologist's office asking about the diuretic change. The fax was either not received or was received and not surfaced to the cardiologist for nine days. In the meantime, David's wife called the cardiologist's office because David was lightheaded; the on-call cardiologist (not David's regular one) reduced the diuretic over the phone. Four days later, the nephrologist's nurse practitioner called David and reduced the diuretic again, not knowing about the on-call adjustment. David, by this point, was on a dose meaningfully different from any of the doses any of his three physicians thought he was on. His wife, who maintains the medication list on the kitchen calendar, was confused. David's home-health aide, who notices things, asked the wife on a Wednesday whether David's ankles seemed more swollen than usual. The wife thought maybe. The wife called the primary care physician's office. The primary care physician's office said the cardiologist would have to handle this. The wife called the cardiologist's office. The cardiologist's office said the next available appointment was three weeks out, but they could put a message in the chart. The home-health aide, who has done this work for fifteen years, called the agency and said something like "this is going to be another admission if somebody doesn't get on this." Two days later, David's ankles were noticeably worse, his shortness of breath when he climbed the four steps to his front porch was noticeably worse, and his wife took him to the emergency department, because she was scared and did not know what else to do. He was admitted. He spent six days in the hospital. He came home on a third diuretic dose, with an updated medication list that nobody outside the hospital had yet, and with a referral to an electrophysiology consult that already existed at the second health system but that the discharging hospitalist did not know about and so duplicated. The cycle started again.

This is the experience of a not-uncommon Medicare patient with multiple chronic conditions in the United States in 2026, and it is one of the larger sources of avoidable cost, avoidable suffering, and avoidable harm in the entire healthcare system. The clinical knowledge for managing David's conditions is well-established. The medications work. The monitoring approaches work. The interventions work. The reason David's outcomes are worse than they should be is not that anyone made a clinical error in isolation; it is that the system that surrounds David has no shared situational awareness of him. Each of his clinicians has a partial picture. Each of his pharmacies has a partial list. Each of his payers has a partial claims view. Each of his health systems has a partial chart. His wife has the most complete picture, and her picture is on a paper calendar, and she is 65 and has her own health concerns, and she is exhausted.

The thing David and his wife would have wanted, if they had been able to articulate it, was a person whose entire job was to keep track of David's care. Not the cardiologist (whose job is cardiology), not the nephrologist (whose job is kidneys), not the primary care physician (whose job is the broad-spectrum work of primary care), not the discharging hospitalist (whose job ended at discharge), not the wife (whose job was supposed to be retirement). A person who would notice, when the cardiologist titrated the diuretic, that the nephrologist would want to know. A person who would notice, when the on-call cardiologist made the over-the-phone adjustment, that the regular cardiologist needed to be looped in. A person who would notice, when the home-health aide raised a concern, that there was a window of forty-eight hours during which an outpatient intervention could prevent the admission. A person who would notice, when the discharging hospitalist wrote a referral, that the patient already had that referral and that the duplicate would just confuse everyone. A person who would maintain the medication list as a single source of truth across pharmacies, who would track every referral from order to completion, who would coordinate the multi-clinician decisions that nobody owned end-to-end, and who would surface the things that were falling through the cracks between the people who were each individually doing their jobs correctly.

Such people exist. They are usually called nurse case managers, care coordinators, or patient navigators. They are concentrated in oncology (where care navigation is sufficiently well-resourced that most patients in cancer programs at academic centers have a dedicated navigator), in transplant programs, in some advanced-illness and palliative-care programs, in care management for high-cost members at risk-bearing payers, and in selected commercial-grade primary care practices. They are expensive, finite, and reserved for the highest-risk slice of any given population. <!-- TODO: verify; care-navigation programs at scale typically reach single-digit-to-low-double-digit percentages of plan or program populations; specific reach figures vary by payer, program, and clinical condition --> David, with five chronic conditions and one comorbid spouse, was just outside the threshold for nurse care management at his payer (he had been close in 2024 but had a quiet 2025 because his wife had been doing extra coordinating). He was just one of tens of millions of patients in the broad middle, where outcomes are determined less by what happens inside any single clinical encounter and more by what happens in the seams between encounters, in the days and weeks after a discharge, in the mismatched fax queues and unreturned phone calls and unreconciled medication lists.

This is the central problem that care coordination as a category exists to solve, and it is one of the largest sources of operational waste and avoidable harm in the U.S. healthcare system. <!-- TODO: verify; published estimates of healthcare costs attributable to coordination failures including avoidable admissions, duplicated services, and adverse events vary by methodology and source, with major reports from the National Academy of Medicine and others documenting substantial preventable cost --> The clinical work the system needs to do for David and millions of patients like him is not new clinical work; it is coordination work. The coordination work is, fundamentally, an information-and-attention problem. Several clinicians, several pharmacies, several payers, and several caregivers each have partial information about David. None of them have the complete picture. Each of them is working as fast as they can in a system that does not give them the time or the tooling to maintain the complete picture. The result is that things fall through the cracks at predictable rates, and the falls are predictable in a way that should embarrass us, because the failure modes have been documented for thirty years and the system has continued to function this way.

The previous generation of digital care-coordination products tried to address this with shared care plans, shared problem lists, shared medication lists, and patient portals. The clinical evidence for these approaches was, broadly, that they helped where the participating providers had aligned incentives and integrated workflows, and they helped less where the participating providers were independent and using different EHRs. <!-- TODO: verify; the literature on digital care-coordination tools includes published evidence of varying strength for shared-care-plan tools, patient portals, health-information-exchange utilization, and integrated-delivery-network coordination programs; effect sizes vary substantially by setting --> The fundamental problem these products had was that they presupposed an integrated care system that, for most U.S. patients, does not exist. David's clinicians are spread across four health systems and three EHR vendors. The payer's care-management system is in a fifth platform. The pharmacy's system is in a sixth. The home-health agency's system is in a seventh. A "shared care plan" requires shared infrastructure, and the infrastructure is not shared.

What changed, around 2023, is that conversational AI got good enough to act, in the right product design, as the connective-tissue layer between systems that do not otherwise talk to each other. A care-coordination assistant cannot magically integrate four EHRs, three pharmacy systems, and five payer platforms; the systems are still not integrated. What the assistant can do is hold the longitudinal model of the patient that the human care manager would have held, ingest information from each connected system as it becomes available (HL7 ADT messages, FHIR observations, claims feeds, pharmacy fills, home-health visit notes, patient messages, caregiver inputs), notice the seams where information from one source has implications for another, surface the implications to the right human at the right moment, and walk the patient and caregiver through the day-to-day work of staying coordinated. The assistant is not a person. The patient and caregiver mostly know that. The patient and caregiver also, in the right product design, talk to it anyway, because the alternative was a paper calendar in the kitchen.

This recipe is about that assistant. The care coordination assistant is the conversational AI use case where the architectural patterns from the previous chapter 11 recipes (FAQ bot, scheduling, refills, intake, benefits navigator, triage, chronic disease coach, mental health support) all converge into a longitudinal, multi-system, multi-stakeholder product, and where several entirely new patterns enter the picture: cross-organizational data integration with FHIR and HL7, referral-lifecycle tracking from order to completion, transition-of-care orchestration across discharge events, multi-provider medication reconciliation, caregiver-as-first-class-participant identity model, gap-and-seam detection over heterogeneous longitudinal data, and a level of system-of-record discipline about provenance that the patient-engagement-only bots do not need.

A few things this recipe is and is not.

It is the assistant that maintains an ongoing coordination relationship with a patient (and, often, a designated caregiver) navigating care across multiple clinicians, multiple organizations, multiple pharmacies, and multiple ancillary services, sending check-in messages around care-event milestones, responding to patient and caregiver questions about the next step, ingesting information from connected clinical and operational systems, tracking referrals and care transitions to closure, surfacing reconciliation gaps to the appropriate human, and escalating when patterns indicate the patient is at risk of falling through a seam.

It is not a clinical-decision tool. The assistant does not make clinical recommendations beyond what the patient's existing clinicians have already prescribed. The assistant does not titrate medications. The assistant does not order tests. The assistant does not adjust the care plan. The clinicians do those things; the assistant tracks the resulting work.

It is not a triage bot. Recipe 11.6 covers acute-symptom triage. The care coordination assistant handles the workflow of established care; when a patient surfaces an acute concern (new chest pain, severe shortness of breath, worsening symptoms suggestive of decompensation), the assistant routes to triage workflows or to direct emergency contacts. The assistant does not try to do triage from scratch.

It is not a chronic disease coach. Recipe 11.7 covers longitudinal chronic-disease management with biometric data, behavior-change support, and condition-specific coaching. The care coordination assistant complements the coach but addresses a different problem: the coach helps the patient manage their conditions; the coordinator helps the patient navigate their providers. The two often coexist in the same patient-facing product.

It is not a mental-health support bot. Recipe 11.8 covers mental-health-specific support with crisis screening and warm handoff. The care coordination assistant escalates mental-health concerns to that pathway rather than handling them in scope.

It is not an EHR replacement. The clinicians' charts remain the system of record for clinical decisions. The assistant maintains its own coordination-state record, distinct from any single EHR, with explicit provenance back to the source systems.

It is not a substitute for the human care team. The assistant extends the care team's reach into the spaces between encounters that the human team cannot afford to staff at population scale. The patient still has their primary care physician, their specialists, their care manager (where one is assigned), and their caregiver. The assistant handles the routine coordination work, freeing the human team to focus on the cases and decisions that require human judgment.

It is not a one-size-fits-all product. A coordination assistant for a Medicare Advantage member with five chronic conditions is different from one for a commercial member after a single elective surgery. A coordination assistant for an oncology patient in active treatment is different from one for a transplant recipient. A coordination assistant for a pediatric complex-care patient is different from one for an adult. Most institutions deploy a multi-population coordination architecture with population-specific protocols layered on a shared coordination core.

It is not a regulatory afterthought. Patient-facing care-coordination software with cross-organization data integration sits at the intersection of HIPAA, the Information Blocking and Interoperability rules, state medical-record regulations, state caregiver-consent rules, and (where the assistant produces clinical recommendations) the FDA Software-as-a-Medical-Device line. <!-- TODO: verify; the regulatory landscape for care-coordination software includes HIPAA, the ONC Information Blocking and Interoperability rules under the 21st Century Cures Act, state medical-record statutes, state caregiver-consent and proxy-access laws, and FDA SaMD framework for software with clinical-decision functionality; specific obligations vary --> The institutional regulatory team is involved from architectural design.

It is not a quick win. The deployment timeline is measured in quarters and years, not sprints. The cross-organizational integration work is multi-quarter, the protocol-content investment is multi-quarter, the workflow-integration work with the human care team is multi-quarter, the regulatory work is multi-quarter, and the outcome demonstration is multi-year. Institutions building this expecting fast time-to-value are usually disappointed.

The thing to understand before building this is that the assistant's value is not in any individual conversation. The value is in the cumulative effect of dozens of small touches per care-event sequence, in the seams it catches that would otherwise have been missed, in the referrals it closes that would otherwise have languished, in the transitions it orchestrates that would otherwise have generated readmissions, and in the relief it provides to caregivers who would otherwise have been the only thread holding the coordination together. An assistant evaluated on per-conversation engagement metrics will be optimized for the wrong thing. An assistant evaluated on coordination outcomes (referral closure rate, transition-of-care completion rate, medication-reconciliation accuracy, caregiver burden, avoidable-utilization rate, patient-and-caregiver-reported coordination experience) is being evaluated correctly, and the architectural decisions follow from there.

Let's get into it.

---

## The Technology: Cross-Organizational Care Coordination Grounded In Longitudinal State, Referral Lifecycles, and Transition-of-Care Protocols

### Why Care Coordination Has Resisted Digital Tools For Twenty Years

Care coordination, as a workflow, has been a phone-fax-and-clipboard problem for several decades. The reason is structural. Care coordination requires asking, repeatedly across encounters and across organizations, "what was supposed to happen, what actually happened, what is supposed to happen next, who needs to know about it, and what falls through if nobody owns it?" The questions are specific to the care event. The questions for a hospital discharge are different from the questions for a specialist referral. The questions for a chemotherapy infusion sequence are different from the questions for a hip-replacement post-op course. The recommendations are also event-specific, are calibrated to the patient's specific care plan, and depend on what just happened across multiple systems that do not natively share information.

The thing nurse case managers and care coordinators do, when they do this well, is hold a longitudinal model of the patient's coordination state in their heads, supplemented by phone calls to the relevant offices, faxes to and from the relevant pharmacies and labs, periodic chart-pulls from the relevant systems, and frequent conversations with the patient and caregiver. The model includes "what is the active care plan," "what referrals are open," "what consultations are pending," "what test results are outstanding," "what medications are in play and which clinician owns each one," "what the patient has been told to do next," "what the caregiver has been told to do next," "what is happening in the patient's life that affects all of this," and "what would happen if I went on vacation for a week." Holding this model is most of the cognitive work of care coordination; the actual phone calls and faxes are the visible part, but the cognitive work of maintaining the longitudinal coordination state is the work that distinguishes a good coordinator from a busy one.

The first generation of digital care-coordination products, roughly the early 2010s through the late 2010s, tried to systematize this with shared care plans inside integrated delivery networks. Where the participating providers were on the same EHR (the major IDN deployments and Kaiser-style integrated systems), the tools sometimes worked well. <!-- TODO: verify; the literature on integrated-delivery-network coordination tools includes published evidence from systems including Kaiser Permanente, Geisinger, Intermountain, and others, with effect sizes varying by program design --> Where the participating providers were spread across organizations and EHRs (the modal U.S. patient experience), the tools largely did not work, because the underlying integration problem was not solved.

The second generation, roughly 2017 to 2022, leveraged FHIR APIs, the ONC Information Blocking and Interoperability rules, health information exchanges, and TEFCA (Trusted Exchange Framework and Common Agreement) infrastructure to make cross-organizational data exchange more feasible. <!-- TODO: verify; the regulatory and infrastructure work supporting cross-organizational health-data exchange has continued to evolve since the 21st Century Cures Act, including the ONC certification program for FHIR APIs, the Information Blocking final rule, and TEFCA implementation through the Recognized Coordinating Entity --> The clinical evidence for these tools is more promising than the first generation, particularly for transitions of care and referral tracking, but the operational reality remains that the data integration is uneven across markets, that the data quality is inconsistent, and that the coordination work itself still requires substantial human attention to translate the integrated data into actionable coordination state.

The thing that changed the workflow shape is, again, large language models that can synthesize heterogeneous, partially-structured, longitudinally-accumulating coordination data into a coherent picture and can engage the patient, caregiver, and care team in plain-language conversations grounded in that picture. The coordination assistant, deployed with careful institutional governance, can hold the longitudinal coordination state the human coordinator would have held, ingest information from each connected system as it becomes available, notice the seams where information from one source has implications for another, surface the implications to the right human at the right moment, walk the patient and caregiver through their part of the work, and escalate to the human team when the situation requires. The LLM is not a coordinator. The LLM is, in the right product design, a tool that lets coordination workflows that have historically required dedicated nurse case management operate at population scale.

The architectural shift is from "shared care plan inside one EHR" to "longitudinal coordination state across heterogeneous sources, surfaced conversationally to patients and caregivers and structurally to the care team." The assistant's value is concentrated in three places: the longitudinal coordination state (turning fragmented signals from multiple systems into a single coherent picture), the seam-detection logic (catching the gaps between systems that human coordinators catch through experience and that the systems themselves do not catch at all), and the operational reach (extending the coordination workforce from the small high-acuity slice it serves today to the broad-middle population that needs it but does not currently get it).

### What a Care Coordination Assistant Actually Does

A care coordination assistant is a tool-using LLM with a system prompt that tells it which assistant it is, the patient's authenticated context (active conditions, current medications across all known pharmacies, open referrals, recent encounters across all known organizations, scheduled future encounters, recent test results, recent care-event milestones, conversation history, stated patient and caregiver preferences), access to a structured library of coordination protocols (transition-of-care protocols, referral-tracking protocols, post-discharge protocols, post-procedure protocols, medication-reconciliation protocols, condition-specific coordination playbooks), and a careful set of tools for retrieving cross-system data, tracking referrals and transitions, surfacing seam-detection events, sending follow-up messages, generating coordination summaries, and escalating to clinical staff or human coordinators.

The conversation surface is not one conversation. It is a stream of conversational episodes, sometimes initiated by the patient, sometimes initiated by the caregiver, sometimes initiated by the assistant on the basis of a care-event trigger (an HL7 ADT discharge message, a referral-order message, a lab-result message, a pharmacy-fill event, a missed-appointment event), and sometimes initiated by a care-team request (the assigned care manager asks the assistant to follow up with the patient on a specific item).

The assistant's task surface decomposes roughly as follows.

**Onboarding and proxy/caregiver setup.** The patient enrolls in the coordination program through their primary care home, their payer, their care-management program, or a dedicated coordination service. The first conversations capture the patient's known clinicians, known pharmacies, known payers, and known caregiver(s); document the patient's preferences (preferred channels, preferred times, things to discuss with the patient versus the caregiver versus both, language preferences); establish proxy access for the caregiver where applicable per state law and institutional policy; and explain what the assistant does and does not do.

**Cross-system data integration with provenance.** The assistant ingests data from connected clinical and operational systems on an ongoing basis: HL7 ADT messages from participating hospitals, FHIR encounter and observation feeds from participating ambulatory practices and HIEs, claims feeds from the payer where applicable, pharmacy fill data from connected pharmacies, home-health visit notes from connected agencies, lab feeds from connected labs, scheduled-appointment feeds from connected scheduling systems, and structured patient-and-caregiver-reported events from the conversation surface itself. Each data point is stored with its source, its timestamp, and its provenance metadata.

**Longitudinal coordination state maintenance.** The assistant maintains a coordination-state record that synthesizes the connected sources into a coherent picture: the active medication list reconciled across pharmacies, the open-referrals registry with status (ordered, scheduled, completed, lost), the upcoming-encounters list with confirmation status, the recent-encounters list with summary and follow-up requirements, the recent-test-results registry with patient-acknowledged status, the active-care-events list (current discharge episode, current procedure recovery, current treatment course), and the seam-flags registry (gaps and inconsistencies the assistant has detected and not yet routed to closure).

**Patient and caregiver conversations within scope.** The patient or caregiver can engage at any time, with questions about the next step ("what is supposed to happen after my hip surgery?"), the medication list ("the new pill from the cardiologist, am I supposed to keep taking the old one or stop?"), the upcoming appointments ("when is my next nephrology appointment, and do I need labs first?"), the referrals ("did I ever go to that ear-nose-and-throat doctor my primary care wanted me to see?"), and the everyday work of coordination. The assistant answers within scope using grounded retrieval over the patient's coordination state and the institution's coordination protocols.

**Care-event-triggered conversations.** When a care event happens (an ADT discharge message arrives, a referral is ordered, a lab result is posted, a medication is filled or refilled or discontinued, an appointment is scheduled or cancelled or missed), the assistant initiates appropriate follow-up: a post-discharge welcome-home conversation within forty-eight hours, a referral-tracking check-in a week after the order if the appointment has not been scheduled, a lab-result acknowledgement once the patient's clinician has reviewed and signed off, a medication-fill check after a new prescription, an appointment-prep nudge a few days ahead of an upcoming visit. The triggers are specified in the coordination protocols, not chosen by the LLM.

**Seam-detection and gap-surfacing.** The assistant runs heuristic and structured checks across the coordination state to catch gaps and inconsistencies: medication discrepancies between pharmacies, referrals that have not been scheduled within the protocol window, test results that have not been acknowledged, follow-up appointments that should have been scheduled per a discharge plan but were not, conflicting orders between clinicians (the cardiologist's diuretic adjustment versus the nephrologist's), care-plan items that have aged out of their expected completion window. Detected gaps are surfaced to the patient or caregiver where the resolution is in their hands and to the appropriate human coordinator or clinician where the resolution requires clinical judgment.

**Transition-of-care orchestration.** When the patient transitions between care settings (hospital to home, hospital to skilled nursing, home to inpatient procedure, primary care to specialist for an active concern), the assistant runs the institution's transition-of-care protocol: validates that the discharge medications match the prior medications plus expected changes, validates that the follow-up appointments are scheduled within the protocol window, validates that the home-health or DME orders have been received by the receiving agencies, walks the patient and caregiver through the discharge instructions in a low-pressure way, and surfaces any items that have not closed.

**Referral lifecycle tracking.** When a referral is ordered, the assistant tracks it: confirms the patient received the referral, walks the patient through the scheduling process if needed, surfaces barriers to scheduling (the specialty practice does not take the patient's insurance; the wait time is six weeks and the patient cannot wait that long), confirms the appointment when scheduled, prepares the patient for the visit, and confirms that the consult note has come back to the ordering clinician. The lifecycle is bounded by the protocol; an unclosed referral that ages out is escalated.

**Medication reconciliation across pharmacies and clinicians.** The assistant maintains the patient's medication list as a single source of truth synthesized from all known pharmacy fills, all known clinician orders, and all patient-reported medications. When a discrepancy is detected (a clinician orders a medication that was already discontinued; two clinicians order interacting medications without coordination; a pharmacy fills a medication the patient says they were told to stop), the assistant flags it for human reconciliation.

**Patient and caregiver education delivered in coordination context.** The assistant delivers institutionally-curated patient-education content at moments when it is contextually relevant (after a discharge, before a procedure, when a new medication is started, when a new condition is added to the problem list). The content is grounded in the institution's reviewed library, calibrated to the patient's stated preferences and language, and delivered in plain language.

**Caregiver-specific support.** Where the patient has designated a caregiver, the assistant supports the caregiver as a first-class participant: separate authentication, separate consent posture, caregiver-specific message templates, caregiver-burden monitoring, and respite-and-support resource surfacing.

**Care-team reporting and coordination summaries.** The care team has visibility into the assistant's activity through structured summaries (real-time alerts for high-priority gaps, weekly digests, monthly summaries, transition-of-care closure reports). The reporting is designed for the care team's workflow and is reviewed by clinical leadership before launch.

**Long-term coordination-relationship maintenance.** The assistant maintains the coordination relationship over months or years. The coordination state accumulates. The patient's and caregiver's preferences are remembered. The patient's stated personal context (their wife's anxiety, their work schedule, their transportation barriers, the things that make coordination harder or easier) is remembered and surfaced when relevant. The assistant is not pretending to be a friend or a clinician; the assistant is acting as a longitudinal coordination record that is accessible during conversations and that flows naturally into the patient's lived context.

### Why a Generic LLM Cannot Run a Care Coordination Assistant

A naive product approach would be: take a generalist LLM, give it a chat surface, paste in some discharge instructions, and have it coordinate the patient's care. This breaks in several specific ways, each of which has clinical and operational consequences.

**The model has no longitudinal coordination state.** Without a structured longitudinal record of referrals, medications, encounters, results, transitions, and seam-flags, the LLM treats every conversation as a fresh start. A coordinator without longitudinal coordination state is, at best, a glorified FAQ bot. The longitudinal coordination state, with provenance back to source systems, is the architectural primitive that distinguishes the assistant from the bots in the previous chapter recipes.

**The model has no view of the cross-organizational data.** The assistant's value depends on synthesizing data from clinicians, pharmacies, payers, and ancillary services that do not natively share information with each other. The integration layer (HL7 message ingestion, FHIR API consumption, claims-feed processing, pharmacy-data integration, HIE integration) is the architectural floor; without it, the assistant has only what the patient and caregiver volunteer, which is incomplete in predictable ways.

**The model hallucinates coordination instructions when grounding is weak.** If the institution's coordination protocols (transition-of-care protocols, referral-tracking protocols, condition-specific coordination playbooks) are not retrieved with strict citation grounding, the LLM produces plausible-sounding coordination instructions that are wrong for the institution's actual processes. Worse, the LLM may produce instructions that contradict the standard of care or that send the patient in the wrong direction. The protocol-corpus RAG with strict citation grounding is non-negotiable.

**The model has no theory of seam detection.** The assistant's distinctive value is in catching the gaps between systems that human coordinators catch through experience and the systems themselves do not catch at all. The seam-detection logic (medication discrepancies, referral non-scheduling, transition-of-care completion gaps, test-result-acknowledgement gaps, conflicting orders) is encoded in deterministic rules and dedicated heuristic models, not left to the LLM's interpretation.

**The model has no theory of referral lifecycles.** A referral has a structured lifecycle (ordered, communicated, scheduled, attended, consult-note-received, closed) with specified time windows for each transition. The LLM does not naturally maintain or reason about this lifecycle. The referral-tracking subsystem maintains the lifecycle state machine; the LLM operates on top of it.

**The model has no theory of transition-of-care protocols.** Each transition (hospital-to-home, hospital-to-SNF, home-to-procedure, ED-to-primary-care follow-up) has a structured protocol with specified items (medication reconciliation, follow-up-appointment scheduling, home-health or DME orders, patient education, red-flag warning instructions). The protocols are institutional content, not LLM creativity.

**The model has clinical-decision-rule arithmetic problems.** Coordination logic includes time-window calculations (was the follow-up scheduled within the seven-day window?), medication-list comparisons (does the discharge list reconcile with the pre-admit list plus the changes?), readmission-risk calculations (is this patient in the elevated-risk window?), and similar structured arithmetic. The LLM does this poorly. The deterministic coordination-rule tools encapsulate the computation.

**The model has no theory of caregiver-versus-patient identity.** Care coordination involves both the patient and (often) one or more caregivers, with separate identities, separate authentication, separate consent posture, and separate state-law access rules. The LLM does not naturally distinguish; the architecture maintains the distinction explicitly.

**The model has no theory of cross-organizational consent.** Patients have consented to information-sharing with each of their organizations separately; the assistant operating across organizations needs an integrated consent posture that respects the patient's preferences. The LLM does not enforce this; the consent layer does.

**The model has no theory of what to do when integration is unavailable.** Real-world integration is patchy. The patient's primary care EHR may be integrated, the cardiology EHR may not be, the second pharmacy may not be, the home-health agency may use a non-FHIR system. The LLM cannot reason about coverage gaps; the architecture explicitly tracks data-source coverage per patient and adjusts the assistant's confidence accordingly.

**The model has compliance implications specific to coordination data.** The conversation contains PHI from multiple organizations, with potential cross-organizational sharing implications, potential implications for the Information Blocking rule, and potential implications for state-specific privacy regulations. The audit, retention, access-control, and downstream-clinical-workflow integration story has to handle each.

**The model has no theory of staying within scope when the patient asks for clinical recommendations.** Patients in coordination relationships frequently bring up clinical questions: a question about whether a symptom is concerning, a question about whether to take a medication when they feel side effects, a question about a specific recommendation a clinician made. The assistant answers within scope (here is what your clinician said; here is the protocol for that situation) and escalates outside scope (this is a clinical question for your care team; here is the route).

**The model has no theory of when to surface a gap to a human versus to the patient.** Some gaps are best resolved by the patient (call the specialty practice and reschedule because they were closed when you tried to schedule). Some gaps are best resolved by the human care team (the cardiologist's diuretic dose conflicts with the nephrologist's recommendation and a clinician needs to reconcile). The routing logic is institutional policy, not LLM judgment.

**The model has no theory of relationship preservation when the assistant is the bearer of bad news.** The assistant frequently surfaces things the patient or caregiver did not know and may not want to hear ("you missed your nephrology appointment two weeks ago"; "the consult note from the orthopedist has been in your chart for a month and you haven't seen it"). The motivational-interviewing patterns and the relationship-quality engineering are part of the architecture.

### What the Coordination Assistant Has To Do That the Previous Bots Did Not

Recipes 11.1 through 11.8 established the patterns this recipe inherits: input safety screening with continuous emergency screening, identity verification, tool-use orchestration, output safety screening, audit logging, per-cohort monitoring, scope discipline, prompt-injection defense, graceful degradation, longitudinal-context loading, citation grounding, behavior-change-stage tracking, crisis-pathway routing. The care coordination assistant adds eight structural commitments those recipes did not have.

**Cross-organizational data integration as architectural primitive.** The assistant's value depends on consuming data from systems outside the operating institution (other hospitals via HIE or TEFCA, other clinics via FHIR APIs, payers via claims feeds, pharmacies via pharmacy-network APIs, ancillary services via vendor integrations). The integration layer is core production scope, not phase-2 enhancement.

**Longitudinal coordination state with provenance discipline.** Every data point in the coordination state has a recorded source, a recorded timestamp, and a recorded provenance chain. When a clinician asks "where did this medication entry come from?" the answer is structurally available, not conjectured.

**Referral and transition-of-care lifecycle tracking as deterministic state machines.** Referrals and transitions move through specified states with specified time windows. The state machines are institutional content, signed off by clinical leadership, version-controlled, and audited.

**Seam-detection logic with deterministic and heuristic components.** Medication-discrepancy detection, referral-non-scheduling detection, transition-of-care-incompleteness detection, test-result-acknowledgement-gap detection, conflicting-order detection, and similar checks are implemented as deterministic rules where possible and heuristic models where probabilistic reasoning is required.

**Caregiver-as-first-class-participant identity model.** Caregivers have separate identities, separate authentication, separate consent posture, separate message templates, separate burden monitoring, and separate state-law access rules. The architecture is designed for the patient-plus-caregiver pattern from day one.

**Cross-organizational consent posture.** Consent is tracked per data source and per sharing relationship, respects patient preferences, accommodates state-specific regulations, and is operationally enforced through the integration and conversation layers.

**Information-blocking-rule and TEFCA-alignment posture.** The assistant's data integration and data sharing operate within the framework of the ONC Information Blocking rule and (where applicable) TEFCA participation; the institutional regulatory team specifies the posture and the architecture enforces it.

**Outcome-correlation against coordination-specific outcomes.** The assistant's performance is measured against outcomes that reflect coordination quality: referral closure rate, transition-of-care completion rate, medication-reconciliation accuracy, avoidable-readmission rate, avoidable-ED-utilization rate, patient-and-caregiver-reported coordination experience.

The rest is largely the same as the previous chapter 11 recipes: tool-surface contract management, identity-assurance lifecycle, conversation logging, scope filtering, per-cohort monitoring, graceful degradation when upstream systems fail.

### The Coordination Reality

A few notes on what makes care coordination specifically harder than the previous patient-facing bot use cases.

**Data integration is uneven and is the largest single engineering investment.** No two patients have the same set of integrated data sources. Some patients are well-instrumented (their primary care home is on a major EHR with a robust FHIR API; their pharmacy is on a major chain with API access; their payer is a value-based-care partner with claims-feed integration; their home-health agency is on the platform's preferred vendor). Some patients are poorly instrumented (their primary care is at a small independent practice with limited APIs; their pharmacy is independent and shares data only via NCPDP; their payer is fee-for-service with no real-time feeds; their home-health is a small agency with paper notes). The assistant has to operate gracefully across this heterogeneity, with explicit per-source coverage tracking and per-patient coverage gap monitoring.

**Provenance and source-of-truth discipline is unusually important.** When a coordination assistant says "your cardiologist increased your diuretic last Tuesday," the patient or care team may need to know how the assistant knows. The provenance chain (source system, message ID, timestamp, ingestion path, transformation history) has to be auditable for every entry in the coordination state.

**The coordination state is distinct from any single EHR's chart.** No single EHR has the full picture; the assistant's coordination state is a synthesis. This means the coordination state is a separate record class, with its own retention policy, its own access controls, its own provenance discipline, and its own update workflows that distinguish "data ingested from a source" from "patient-or-caregiver-reported information not yet validated against a source."

**The seam-detection logic is the distinctive value layer.** Most of the engineering value of a coordination assistant lives in the seam-detection layer, not in the LLM. The LLM is the interface; the deterministic rules and heuristic models are the substance. Investment in seam-detection-rule development with named clinical-leadership ownership per rule is multi-quarter work.

**Caregiver burden is a measurable outcome the assistant can directly affect.** Caregiver burden, well-documented in the literature, contributes to caregiver mental and physical health problems and affects the quality of care the patient receives. <!-- TODO: verify; the literature on caregiver burden including the Zarit Burden Interview and related instruments documents the prevalence and consequences of caregiver burden in chronic illness care --> A coordination assistant that takes routine work off the caregiver's plate (tracking the next appointment, reconciling medications, surfacing gaps for routing) is a coordination assistant that measurably reduces caregiver burden in a way that single-clinical-encounter tools cannot.

**Cross-organizational data sharing has nuanced regulatory exposure.** The 21st Century Cures Act and the Information Blocking rule require certain data sharing; state laws around mental-health records, HIV records, substance-use records (42 CFR Part 2), genetic-test results, and adolescent confidentiality limit it; the institutional posture has to navigate both. <!-- TODO: verify; the data-sharing regulatory landscape includes federal Information Blocking provisions, 42 CFR Part 2 for substance-use treatment records, state-specific mental-health and HIV record protections, and minor-confidentiality protections that vary by state and care category --> The legal team is involved.

**Transition-of-care protocols vary by institution and by destination setting.** A discharge from a hospital to a skilled nursing facility runs a different protocol than a discharge to home with home health. A discharge from an ambulatory surgery center runs a different protocol than a discharge from an inpatient stay. The institution's protocol library has to cover the specific transitions the institution serves, with named clinical-leadership ownership per protocol.

**Referral lifecycles are influenced by external factors the institution does not control.** A specialty practice may have a six-week wait list. A specialty practice may not accept the patient's insurance. A specialty practice may have closed. The assistant has to recognize these external constraints, surface them to the patient and care team, and adapt the lifecycle expectations accordingly.

**Medication reconciliation across pharmacies has well-known data-quality issues.** Pharmacy data feeds carry inconsistent medication-naming, inconsistent dose representation, inconsistent dosing-instruction parsing, and incomplete coverage. Reconciliation logic has to be robust to these issues; the institutional pharmacy informatics team is part of the work.

**Patient-and-caregiver-reported coordination experience is the leading indicator of program effectiveness.** Coordination outcomes that show up in claims data (avoided readmissions, reduced ED utilization) take quarters to materialize. Patient-and-caregiver-reported coordination experience can be measured weekly. Per-cohort monitoring of coordination experience is a launch-gate operational metric.

**Cultural and linguistic considerations are not optional.** Coordination work intersects with the patient's lived context: family structure, caregiver relationships, language preferences, transportation, work schedules, and housing stability. A coordination assistant calibrated only for English-speaking, college-educated, suburban patients with a single caregiver and stable transportation is excluding much of the population it should be serving.

**Social determinants of health are coordination context.** Patients with food insecurity, housing instability, transportation barriers, or financial constraints have coordination needs that intersect with these factors. A patient who cannot get to a follow-up appointment because they have no transportation is a coordination problem, not a clinical one. The assistant integrates with care-navigation and social-services resources where the institution has them.

**The relationship to existing care management programs is structural, not aspirational.** Most institutions already have nurse care managers, complex-case managers, and social workers serving the highest-acuity slice of their population. The assistant does not replace them; the assistant complements them by handling the broad-middle population they cannot reach and by feeding signals to them about cases that should be promoted into their workload. The relationship is designed jointly with care-management leadership; deploying without their involvement produces an assistant care management does not use.

**Outcome demonstration is multi-year work.** The assistant's effect on referral closure rate shows up over weeks to months. The effect on transition-of-care completion rate shows up over weeks to months. The effect on readmission rate and ED-utilization rate shows up over six to twenty-four months. The effect on total-cost-of-care shows up over twelve to thirty-six months. Institutions building this with quarterly-impact expectations will be disappointed; institutions willing to invest at the right time horizon can demonstrate genuinely meaningful outcomes.

### Where the Field Has Moved

A few practical updates worth knowing.

**The Information Blocking and Interoperability rules have made cross-organizational data exchange more feasible than it was five years ago.** ONC certification of FHIR APIs, the Information Blocking final rule, and TEFCA implementation have improved the data-availability picture meaningfully, particularly for ambulatory and inpatient encounter data. <!-- TODO: verify; the regulatory infrastructure under the 21st Century Cures Act has continued to evolve, with the ONC certification of FHIR APIs (USCDI), the Information Blocking final rule, and TEFCA implementation through the Recognized Coordinating Entity providing improved cross-organizational data infrastructure --> Coordination architectures that consume this infrastructure are operating in a more capable environment than equivalent architectures a decade ago.

**FHIR Bulk Data Access supports population-scale coordination workflows.** The FHIR Bulk Data Access specification (also called Flat FHIR) supports population-level data export from EHRs, which is useful for coordination-program-wide analytics and seam-detection. <!-- TODO: verify; FHIR Bulk Data Access is a published specification with implementation across major EHR vendors as part of ONC certification --> Coordination platforms increasingly consume bulk data alongside per-patient APIs.

**Patient-mediated data exchange via SMART on FHIR apps is a complementary integration path.** Where institutional API access is unavailable, patients can authorize access to their data through SMART on FHIR apps using the certified patient-facing APIs from each organization. <!-- TODO: verify; SMART on FHIR is a widely-adopted authorization pattern with patient-facing app authorization required by the ONC certification program --> Coordination architectures use this as a fallback or as a primary integration path for organizations not directly partnered.

**Tool-using LLMs handle coordination conversations well when grounded carefully.** The function-calling pattern from the previous chapter 11 recipes maps to coordination work. The LLM produces tool calls that retrieve coordination state, retrieve specific encounter or referral data, retrieve protocol content, surface seam-flags, schedule follow-up touches, and post events for downstream operations.

**Hybrid AI-plus-human coordination is the dominant production pattern.** Most major deployments run a hybrid model: AI assistant for the broad-middle coordination population, with human care managers for high-risk members, escalation cases, and complex coordination work. The economics work because the AI assistant handles the routine touches while the human care manager focuses where their judgment is most needed.

**Outcome demonstration is mixed but trending positive for hybrid models.** Studies of digital-plus-human coordination programs have shown statistically and clinically meaningful improvements in referral closure rates, transition-of-care completion, medication-reconciliation quality, and (where measurement windows are long enough) readmission and ED-utilization rates. <!-- TODO: verify; the evidence base for hybrid coordination programs includes published studies of programs from major payers, integrated delivery networks, care-coordination platforms, and post-discharge programs; specific outcome figures vary by study --> The ROI demonstrations are stronger when the analysis includes downstream-event reduction (avoided readmissions, avoided ED visits, reduced duplicate services) than when the analysis focuses only on direct engagement metrics.

**Equity and disparity considerations are an active area of attention.** Coordination programs reach disproportionately the patients who are already plugged in to the digital-tool ecosystem. The patients with the highest coordination needs are often the patients with the most limited access to digital tools and the most limited integration with the connected data sources. Per-cohort monitoring is essential.

**Build-vs-buy is mature for some coordination segments.** Several mature commercial vendors offer care-coordination platforms with FHIR integration, claims-feed processing, transition-of-care workflows, and (in some cases) hybrid-coordination workforces. Most major institutions deploying in this space run a hybrid: build a thin-orchestration layer in-house on the institution's preferred infrastructure, partner with vendors for the cross-organizational integration substrate (HIE participation, TEFCA QHIN access, claims-feed plumbing), and integrate with the institution's care-management, telehealth, and clinical-record infrastructure.

---

## General Architecture Pattern

A healthcare care coordination assistant decomposes into ten logical stages: enrollment with caregiver setup, longitudinal-coordination-state initialization, cross-organizational data ingestion, seam-detection and protocol-driven trigger evaluation, channel entry, input safety screening with continuous emergency screening, identity-and-coordination-context loading, conversation handling with protocol-grounded responses, output safety screening, and care-team reporting with outcome correlation. The cross-cutting concerns from recipes 11.1 through 11.8 carry forward; this recipe adds five new ones (cross-organizational data integration with provenance, longitudinal-coordination-state-as-system-of-record, referral-and-transition-of-care state machines, seam-detection rule engine with clinical-leadership ownership, and caregiver-as-first-class-participant identity model).

```
┌────────── ENROLLMENT + CAREGIVER SETUP ──────────────────┐
│                                                           │
│   [Patient enrolls via primary care home, payer,         │
│    care-management program, or coordination service]      │
│    - Documented consent specific to coordination work     │
│      with cross-organizational data integration scope     │
│      explicit                                             │
│    - Caregiver designation captured (zero or more         │
│      caregivers, each with proxy-access scope)            │
│    - Known clinicians captured (each with organization,   │
│      role, primary contact, EHR identifier where known)   │
│    - Known pharmacies captured                            │
│    - Known payers captured                                │
│    - Known ancillary services captured (home health,      │
│      DME, infusion, dialysis, lab, imaging)               │
│    - Patient and caregiver preferences captured           │
│      (channels, quiet hours, language, preferred name,    │
│      what to discuss with whom)                           │
│    - State-specific consent variations enforced for       │
│      sensitive record categories (mental health, HIV,     │
│      substance use under 42 CFR Part 2, genetic test      │
│      results, adolescent confidentiality)                 │
│           │                                               │
│           ▼                                               │
│   [Output: signed consent records; coordination           │
│    enrollment record; caregiver-access records]           │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── LONGITUDINAL COORDINATION STATE INIT ──────────┐
│                                                           │
│   [Patient-coordination longitudinal state]               │
│    - Active conditions registry (synthesized across       │
│      sources)                                             │
│    - Active medication list (synthesized across           │
│      pharmacies and clinicians)                           │
│    - Open-referrals registry with lifecycle state         │
│    - Upcoming-encounters list                             │
│    - Recent-encounters list with summary and follow-up    │
│      requirements                                         │
│    - Recent-test-results registry with acknowledgement    │
│      status                                               │
│    - Active-care-events list (current discharge episode,  │
│      current procedure recovery, current treatment        │
│      course)                                              │
│    - Seam-flags registry                                  │
│    - Provenance metadata for every entry (source,         │
│      timestamp, ingestion path)                           │
│    - Patient and caregiver preferences                    │
│    - Conversation history (initially empty)               │
│    - Consent posture per data source and per sharing      │
│      relationship                                         │
│                                                           │
│   [Storage architecture]                                  │
│    - Structured state: DynamoDB tables with provenance    │
│      indexing                                             │
│    - Conversation transcript: S3 with vector retrieval    │
│    - Recent-context summary: cached, refreshed per        │
│      conversation                                         │
│    - Longitudinal-coordination summary: refreshed         │
│      periodically                                         │
│           │                                               │
│           ▼                                               │
│   [Output: longitudinal coordination state ready]         │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── CROSS-ORGANIZATIONAL DATA INGESTION ───────────┐
│                                                           │
│   [Connected data sources]                                │
│    - HL7 v2 ADT messages from participating hospitals     │
│      (admit, discharge, transfer events)                  │
│    - HL7 v2 ORU messages for lab results                  │
│    - FHIR APIs for ambulatory and inpatient data          │
│      (Patient, Encounter, Condition, MedicationRequest,   │
│      MedicationStatement, Observation, DiagnosticReport,  │
│      ServiceRequest, CarePlan, AllergyIntolerance,        │
│      Immunization)                                        │
│    - HIE feeds and TEFCA QHIN integration where           │
│      participating                                        │
│    - Payer claims feeds (where the institution has a      │
│      claims-data partnership with the payer)              │
│    - Pharmacy data via NCPDP standards or vendor APIs     │
│    - Home-health visit notes via vendor APIs              │
│    - Scheduled-appointment feeds from connected           │
│      scheduling systems                                   │
│    - Patient-and-caregiver-reported events from the       │
│      conversation surface                                 │
│                                                           │
│   [Ingestion pipeline]                                    │
│    - Per-source ingestion adapters (HL7 listener, FHIR    │
│      polling and subscription, claims batch ingestion,    │
│      pharmacy-API ingestion, vendor-API ingestion)        │
│    - Per-source authentication and rate-limit handling    │
│    - Data validation and outlier detection                │
│    - Provenance metadata capture (source system,          │
│      message ID, timestamp, ingestion path)               │
│    - Sensitive-record classification (42 CFR Part 2,      │
│      mental-health, HIV, genetic) with per-class          │
│      handling                                             │
│    - Deduplication and conflict detection                 │
│                                                           │
│   [Coordination-state update]                             │
│    - Append to provenance journal                         │
│    - Reconcile against existing coordination state        │
│    - Surface conflicts to seam-detection layer            │
│    - Update derived views (active medication list,        │
│      open-referrals registry, etc.)                       │
│                                                           │
│   [Event generation]                                      │
│    - Care-event triggers to protocol layer (discharge     │
│      event, referral order event, lab result event,       │
│      etc.)                                                │
│    - Seam-detection triggers                              │
│           │                                               │
│           ▼                                               │
│   [Output: updated coordination state with provenance;    │
│    care-event triggers; seam-detection triggers]          │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── SEAM DETECTION + PROTOCOL TRIGGER EVAL ────────┐
│                                                           │
│   [Seam-detection rule engine]                            │
│    - Medication discrepancy detection (between            │
│      pharmacies, between clinicians, between              │
│      patient-reported and source-recorded)                │
│    - Referral non-scheduling detection (referral          │
│      ordered but not scheduled within protocol window)    │
│    - Transition-of-care incompleteness detection          │
│      (post-discharge follow-up not scheduled within       │
│      protocol window; medication reconciliation not       │
│      completed; home-health orders not received by        │
│      receiving agency)                                    │
│    - Test-result acknowledgement gap detection (result    │
│      posted but not reviewed by ordering clinician        │
│      within protocol window)                              │
│    - Conflicting-order detection (two clinicians          │
│      ordering interacting medications without             │
│      coordination)                                        │
│    - Care-plan-item aging detection (item past expected   │
│      completion window)                                   │
│    - Lapsed-coverage detection (data source has gone      │
│      silent for an extended period)                       │
│    - Confidence-flag generation for heuristic rules       │
│                                                           │
│   [Protocol trigger evaluation]                           │
│    - Care-plan-driven schedules (post-discharge           │
│      follow-up cadence, post-procedure recovery cadence,  │
│      treatment-course milestone cadence)                  │
│    - Referral-lifecycle transitions                       │
│    - Transition-of-care protocol initiation               │
│    - Medication-reconciliation protocol initiation        │
│    - Patient-and-caregiver-preferences-driven             │
│      adjustments                                          │
│                                                           │
│   [Routing]                                               │
│    - Patient-resolvable gaps to engagement scheduler      │
│    - Care-team-resolvable gaps to care-team alert queue   │
│    - Both-resolvable gaps to engagement scheduler with    │
│      care-team copy                                       │
│    - High-acuity events to escalation pathway             │
│           │                                               │
│           ▼                                               │
│   [Output: scheduled engagements; care-team alerts;       │
│    escalation events]                                     │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── CHANNEL ENTRY ─────────────────────────────────┐
│                                                           │
│   [Patient or caregiver-initiated entry]                  │
│    - In-app chat (patient or caregiver)                   │
│    - SMS reply                                            │
│    - Voice channel (where supported)                      │
│    - Web chat                                             │
│    - Caregiver-mediated entry (caregiver responds on      │
│      behalf of patient with appropriate authorization)    │
│                                                           │
│   [Assistant-initiated entry]                             │
│    - Care-event-triggered conversation delivered to       │
│      patient or caregiver                                 │
│    - Patient or caregiver responds, conversation          │
│      continues                                            │
│                                                           │
│   [Conversation session bootstrap]                        │
│    - Generate conversation_session_id                     │
│    - Capture channel, authentication context              │
│    - Identify whether speaker is patient, caregiver, or   │
│      both                                                 │
│    - Determine if continuing existing session or          │
│      starting new                                         │
│           │                                               │
│           ▼                                               │
│   [Output: session_id, channel, auth context, speaker     │
│    role]                                                  │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── INPUT SAFETY + CONTINUOUS EMERGENCY SCREEN ────┐
│                                                           │
│   [Standard input safety primitives from recipe 11.1]     │
│    - Prompt-injection detection                           │
│    - PHI minimization                                     │
│    - Self-harm and crisis classifier                      │
│                                                           │
│   [Coordination-specific continuous emergency screening]  │
│    - Runs on every patient or caregiver utterance         │
│    - Detects acute-emergency presentations (chest pain,   │
│      severe shortness of breath, suspected stroke,        │
│      severe bleeding, suicidal intent)                    │
│    - Detects high-acuity coordination events              │
│      (post-discharge symptoms suggesting decompensation,  │
│      reported missed medications affecting acute          │
│      conditions, reported caregiver crisis)               │
│    - Triggers immediate routing to triage (recipe 11.6),  │
│      mental-health pathway (recipe 11.8), 911, 988, or    │
│      institutional crisis line as appropriate             │
│                                                           │
│   [Coordination-specific sensitive-disclosure detection]  │
│    - Caregiver-burden indicators                          │
│    - Caregiver-abuse indicators (toward patient or        │
│      from patient)                                        │
│    - Elder-abuse indicators                               │
│    - Intimate-partner violence indicators                 │
│    - Financial-exploitation indicators                    │
│    - Substance-use crisis indicators                      │
│    - Food-insecurity, housing-insecurity,                 │
│      transportation-barrier indicators                    │
│           │                                               │
│           ▼                                               │
│   [Output: input passes / input blocked / emergency       │
│    routed / sensitive disclosure flagged]                 │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── IDENTITY + COORDINATION CONTEXT LOADING ───────┐
│                                                           │
│   [Authenticated session]                                 │
│    - Patient or caregiver is logged into the              │
│      institution's app or portal                          │
│    - Session conveys verified identity, role (patient or  │
│      caregiver), and access scope                         │
│    - Caregiver access scope honors the patient's          │
│      proxy-access record and state law                    │
│                                                           │
│   [Coordination-state retrieval]                          │
│    - Active conditions, medications, referrals,           │
│      encounters, results, care events, seam-flags         │
│    - Recent conversation history (90-day window typical)  │
│    - Patient and caregiver preferences                    │
│    - Open follow-up items                                 │
│    - Provenance metadata for relevant entries             │
│                                                           │
│   [Long-term-summary integration]                         │
│    - Periodically-refreshed long-term coordination        │
│      summary                                              │
│    - Reduces token-budget pressure for long histories     │
│                                                           │
│   [Speaker-role-driven scoping]                           │
│    - Patient access to coordination state                 │
│    - Caregiver access to coordination state filtered      │
│      per proxy-access record (some categories may be      │
│      withheld per patient preference or state law)        │
│           │                                               │
│           ▼                                               │
│   [Output: scoped coordination context payload for        │
│    conversation handler]                                  │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── CONVERSATION HANDLING ─────────────────────────┐
│                                                           │
│   [LLM-orchestrated conversation with tool use]           │
│    - System prompt with coordination context, speaker     │
│      role, patient and caregiver preferences              │
│    - User message plus recent-conversation context        │
│    - Tool surface:                                        │
│      - coordination_state_retrieve                        │
│      - referral_lifecycle_retrieve                        │
│      - encounter_retrieve                                 │
│      - medication_list_reconcile                          │
│      - open_followups_retrieve                            │
│      - seam_flags_retrieve                                │
│      - protocol_retrieve (RAG over institution's          │
│        coordination protocol corpus)                      │
│      - patient_education_content_retrieve                 │
│      - care_team_alert_propose                            │
│      - patient_action_propose                             │
│      - follow_up_schedule                                 │
│      - escalation_propose                                 │
│      - provenance_retrieve                                │
│                                                           │
│   [Citation discipline]                                   │
│    - Coordination instructions grounded in cited          │
│      protocol                                             │
│    - Coordination-state assertions grounded in cited      │
│      provenance                                           │
│    - Education content grounded in cited library item     │
│                                                           │
│   [Scope discipline]                                      │
│    - Within-scope: coordination questions, next-step      │
│      guidance, referral status, transition-of-care        │
│      orchestration, medication reconciliation surfacing,  │
│      caregiver support, seam-flag resolution              │
│    - Outside-scope (route appropriately): clinical        │
│      questions requiring care-team judgment, triage of    │
│      new acute symptoms (recipe 11.6), mental-health      │
│      crisis (recipe 11.8), benefits questions             │
│      (recipe 11.5), refills (recipe 11.3), scheduling     │
│      complex slots (recipe 11.2), chronic-disease         │
│      management coaching (recipe 11.7),                   │
│      diagnosis-attempted, prescription-attempted          │
│           │                                               │
│           ▼                                               │
│   [Output: composed response with citations and tool-     │
│    call audit trail]                                      │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── OUTPUT SAFETY + PROTOCOL-FAITHFULNESS VERIFY ──┐
│                                                           │
│   [Standard output safety primitives from recipe 11.1]    │
│    - Scope filter (no diagnosis; no clinical              │
│      recommendations beyond what existing clinicians      │
│      have ordered)                                        │
│    - Vendor-managed guardrail layer                       │
│    - Persona-and-tone check                               │
│                                                           │
│   [Coordination-specific verification]                    │
│    - Coordination-state assertion grounded in cited       │
│      provenance                                           │
│    - Protocol-instruction grounded in cited protocol      │
│    - Provenance-citation chain validated                  │
│    - Speaker-role-appropriate disclosure (e.g., a         │
│      caregiver speaking on behalf of a patient may have   │
│      restricted access to certain categories per the      │
│      patient's preference)                                │
│    - Conservative-bias check: where the response could    │
│      plausibly involve clinical judgment beyond the       │
│      coordination scope, did the response defer to the    │
│      care team?                                           │
│    - Within-scope check                                   │
│           │                                               │
│           ▼                                               │
│   [Output: response cleared for delivery, replaced with   │
│    a safer template, or regenerated with corrections]     │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── CARE-TEAM REPORTING + OUTCOME CORRELATION ─────┐
│                                                           │
│   [Real-time alerts]                                      │
│    - High-acuity gap events (immediate)                   │
│    - Conflicting-order events (within shift)              │
│    - Sensitive-disclosure events (per institutional       │
│      policy)                                              │
│    - Caregiver-burden alerts (within day)                 │
│                                                           │
│   [Periodic reports]                                      │
│    - Weekly digest per patient (coordination metrics,     │
│      open referrals, transition-of-care status, seam-     │
│      flags, key disclosures)                              │
│    - Monthly summary per patient (longitudinal trends,    │
│      open issues, recommendation for care-team action)    │
│    - Transition-of-care closure reports                   │
│    - Quarterly clinical review packets                    │
│                                                           │
│   [Care-team feedback loop]                               │
│    - Care team marks alerts as actioned                   │
│    - Care team updates protocols based on observed        │
│      patterns                                             │
│    - Care team flags inappropriate assistant responses    │
│      for review                                           │
│                                                           │
│   [Outcome correlation pipeline]                          │
│    - Correlate coordination metrics with clinical and     │
│      utilization outcomes (referral closure rate,         │
│      transition-of-care completion rate, medication-      │
│      reconciliation accuracy, readmission rate, ED-       │
│      utilization rate, total cost of care)                │
│    - Per-protocol outcome calculation                     │
│    - Per-cohort outcome calculation                       │
│    - Patient-and-caregiver-reported coordination          │
│      experience tracking                                  │
│           │                                               │
│           ▼                                               │
│   [Output: care-team visibility into assistant            │
│    activities; outcome metrics for clinical and           │
│    operational review]                                    │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── AUDIT, LOG, AND POST-MARKET SURVEILLANCE ──────┐
│                                                           │
│   [Durable conversation record]                           │
│    - User and caregiver utterances with speaker           │
│      identification                                       │
│    - Tool calls with arguments and results                │
│    - Generated assistant responses                        │
│    - Active model and prompt versions                     │
│    - Active protocol-corpus version                       │
│    - Active coordination-state version                    │
│    - Final disposition                                    │
│                                                           │
│   [Coordination-decision-record journal]                  │
│    - Durable, separately-governed record of coordination  │
│      events (seam-flag detections and resolutions, care-  │
│      team alerts generated, escalations, protocol-driven  │
│      actions, patient-and-caregiver-reported context)     │
│    - Retention sized to the longer of HIPAA's six-year    │
│      minimum, state-specific medical-record retention,    │
│      and any FDA SaMD post-market obligations             │
│                                                           │
│   [Provenance journal]                                    │
│    - Per-source data ingestion log with timestamps,       │
│      transformation history, and integrity hashes         │
│    - Per-coordination-state-entry provenance chain        │
│      preserved across the data lifecycle                  │
│                                                           │
│   [Operational telemetry]                                 │
│    - Coordination metrics (referral closure rate,         │
│      transition-of-care completion rate, medication-      │
│      reconciliation accuracy, seam-detection rate,        │
│      seam-resolution rate)                                │
│    - Engagement metrics (response rate, attrition rate,   │
│      patient-and-caregiver-reported satisfaction)         │
│    - Per-cohort metric slices (language, channel,         │
│      condition mix, age cohort, sex, social-determinant   │
│      flags, caregiver presence, integration coverage)     │
│                                                           │
│   [Sampled clinical-quality review]                       │
│    - Random sample plus targeted sample of escalations,   │
│      seam-flag resolutions, and low-confidence cases      │
│    - Reviewers (RNs, care managers, clinical leadership)  │
│      tag failure modes (out-of-scope, off-protocol,       │
│      seam-detection-miss, seam-detection-false-positive,  │
│      provenance-gap, citation-gap, scope-violation)       │
│    - Protocol revisions driven by review findings with    │
│      clinical-leadership sign-off                         │
│           │                                               │
│           ▼                                               │
│   [Output: audit trail, telemetry, learning signals,      │
│    protocol-revision proposals]                           │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

A few cross-cutting design points specific to the care coordination assistant.

**Cross-organizational data integration as production scope, not phase 2.** The assistant cannot deliver coordination value without consuming data from multiple sources. The integration layer (HL7 listeners, FHIR API consumers, claims-feed processors, pharmacy-data integrations, HIE participation, TEFCA participation where applicable) is core production scope, with named operational ownership for each integration.

**Provenance-as-architectural-primitive.** Every entry in the coordination state has a recorded source, timestamp, and provenance chain. Every assertion the assistant makes about the patient's care state cites the provenance. The provenance journal is separately retained and audit-friendly.

**Coordination-state-as-system-of-record (for coordination, not for clinical).** The coordination state is its own record class, distinct from any single EHR's chart. It synthesizes signals from multiple sources, maintains its own update workflows, has its own retention policy, has its own access controls, and has its own provenance discipline. The coordination state is the system of record for coordination state; the EHRs remain the system of record for clinical decisions.

**Referral-and-transition-of-care state machines with deterministic logic.** Referrals and transitions move through specified lifecycle states. The state machines are institutional content, signed off by clinical leadership, version-controlled, and audited. The LLM operates on top of the state machines; it does not invent them.

**Seam-detection rule engine with named clinical-leadership ownership per rule.** Each seam-detection rule has named clinical-leadership ownership (patient safety officer, pharmacy director, care-management director, post-discharge care coordinator director, etc., depending on the rule). Rules have effective dates, version histories, and sign-off records.

**Caregiver-as-first-class-participant identity model.** Caregivers are not patient-pretenders; they have separate identities, separate authentication, separate consent posture, separate message templates, separate burden monitoring, and separate state-law access rules. The identity model is architectural, not bolt-on.

**Cross-organizational consent posture.** Consent is tracked per data source and per sharing relationship. The consent layer is reviewed by legal counsel familiar with the Information Blocking rule, state-specific privacy regulations, and 42 CFR Part 2 where applicable.

**Continuous emergency screening across every utterance.** Same as the previous bots in this chapter. The assistant routes acute emergencies immediately to the triage workflow, mental-health pathway, or direct emergency contacts; the assistant does not try to handle acute emergencies in conversation.

**Citation discipline as architectural primitive.** Every coordination-state assertion cites its provenance. Every protocol instruction cites its protocol source. Every patient-education content delivery cites its library entry. Citations are structured and the audit record preserves the citation trail.

**Care-team reporting as first-class capability.** Real-time alerts, weekly digests, monthly summaries, transition-of-care closure reports, and quarterly clinical-review packets are part of production scope.

**Outcome correlation as core post-launch commitment.** The assistant's coordination performance is bounded above by what can be measured against actual outcomes. The pipeline is multi-quarter post-launch work and is operationally significant.

**Per-cohort monitoring is non-negotiable.** Coordination metrics, engagement metrics, outcome metrics, and patient-and-caregiver experience vary by language, channel, condition mix, age cohort, sex, social-determinant flags, caregiver presence, and integration coverage. Per-cohort dashboards are reviewed by clinical leadership, operations, compliance, and patient-experience teams.

<!-- TODO (TechWriter): Expert review A1 (HIGH). Promote per-cohort monitoring from prose to architectural primitive: add explicit single-axis cohorts (language, channel, condition mix, age cohort, sex, social-determinant flag, caregiver presence, integration coverage), two-axis and three-axis cohorts (language-by-channel, condition-by-integration-coverage, language-by-condition-by-integration-coverage), and per-cohort threshold metrics (referral closure rate target 60-85%, transition-of-care completion rate target 70-90%, medication-reconciliation accuracy, seam-detection precision target 80-95% and recall target 70-90% per rule, citation-coverage rate target 95%+, engagement-attrition rate at 30/90/180 days, caregiver-burden trajectory with attribution caveats, 30-day-readmission-rate change with attribution caveats, equity-disparity flags by sex/race/age/language/social-determinant/integration-coverage with statistical-significance flags). Specify per-cohort minimum sample size with cross-organizational-coverage-disparity minimization framing. Launch gate as institution-wide-average informational only; each cohort meets threshold. Cohort-disabled-feature workflow with named ownership across clinical leadership, operations, data science, compliance, and equity officer. -->

**Multi-asset clinical-policy-as-code governance.** The coordination-protocol corpus, seam-detection rule library, referral-lifecycle state machine, transition-of-care state machines, medication-reconciliation rule library, FDA-strategy artifact, consent language, caregiver-proxy-access policy, cross-organizational-consent policy, and provenance-and-source-of-truth policy each have per-asset semantic versioning, sandbox testing against held-out cases, staged rollout with per-asset canary, rollback-on-regression, named clinical-leadership ownership, annual review cadence with re-sign-off, and per-asset-version stamping on every coordination-decision-record and every seam-flag-event-record and every transition-of-care-closure-record.

<!-- TODO (TechWriter): Expert review S1 (HIGH). Expand the multi-asset clinical-policy-as-code governance treatment: add architectural components for `coordination_protocol_assets`, `patient_education_library_assets`, `seam_detection_rule_assets`, `referral_lifecycle_state_machine_assets`, `transition_of_care_state_machine_assets`, `medication_reconciliation_rule_assets`, `fda_strategy_artifact_assets`, `consent_language_assets`, `caregiver_proxy_access_policy_assets`, `cross_organizational_consent_policy_assets`, `provenance_policy_assets`. Update Step 1F persist_enrollment to reference all asset versions explicitly. Update Step 6E coordination_decision_record to stamp every active asset version. Update Step 3B seam_findings.append to include rule_owner, effective_date, and version history. Add Production-Gaps "Multi-Asset Clinical-Policy-as-Code Governance Operations" subsection naming clinical leadership across primary care, hospital medicine, specialty practice, pharmacy, home health, care management, operations, compliance, regulatory team, legal counsel, malpractice insurer, pharmacy informatics, language-services, patient-experience leadership, and equity officer as canonical owners. -->

**Working-store PHI minimization with archive-reference discipline.** The longitudinal coordination-state store, coordination-decision-record journal, provenance journal, seam-flag store, referral-lifecycle store, transition-of-care store, caregiver store, consent record, and tool-call ledger preserve structural records on the hot path with archive references for full content, where the content archives are separately keyed and separately access-controlled (the provenance archive uses a distinct customer-managed KMS key restricted to audit-and-compliance plus regulatory plus malpractice insurer; the coordination-decision-record archive uses a distinct customer-managed KMS key). Retention reconciles the longest of HIPAA's six-year minimum, state-specific medical-record retention rules, 42 CFR Part 2 retention for substance-use treatment data, state-specific mental-health-record and HIV-record and genetic-test-result protections, pediatric-record retention until age of majority plus state adult retention, FDA SaMD post-market obligations, Information Blocking rule audit-trail obligations, and litigation-hold.

<!-- TODO (TechWriter): Expert review S2 (HIGH). Adopt archive-reference discipline uniformly across the working stores: route Step 1F enrollment full content to per-patient enrollment-archive S3 prefix; route Step 2E provenance full ingestion metadata to separately-keyed provenance-archive S3 prefix with restricted access-control; route Step 2H coordination-state-update full normalized_event to coordination-state-archive S3 prefix; route Step 5B tool-call full content to per-conversation tool-call-archive; route Step 6E composed_response, tool_calls, and citations to decision-record-content-archive with the journal carrying only structural record (decision_id, session_id, patient_id, speaker_role, archive references, version stamps, timestamp). Update architecture diagram to add `enrollment_archive`, `coordination_state_archive`, `provenance_archive` (separately keyed), `tool_call_archive`, `decision_record_content_archive`, `seam_flag_archive`, `referral_lifecycle_archive`, `transition_of_care_archive`, `conversation_transcript_archive`. Add Production-Gaps subsection covering per-record-class retention reconciliation, per-record-class access-control surface, patient-right-of-access-and-deletion workflow with state-specific variations, 42 CFR Part 2 redisclosure-prohibition discipline for cross-organizational sharing, state-specific sensitive-record discipline, cross-organizational consent revocation and data-purge workflow, and conversation-log-as-clinical-record reconciliation. -->

**Disaster-recovery topology.** When the integration layer, the protocol corpus, the coordination-state store, or any escalation pathway is unreachable, the assistant degrades gracefully. The minimum behavior is "I'm having trouble pulling that data right now; for anything urgent please contact your care team at [number]." The graceful-degradation paths are exercised in tabletop drills.

<!-- TODO (TechWriter): Expert review A6 (MEDIUM). Expand disaster-recovery topology with per-stage failover policy: Bedrock LLM outage with degraded-mode response and direct care-team routing; Bedrock Knowledge Bases outage with safe-template fallback; Bedrock Agents outage; Bedrock Guardrails outage with stricter scope enforcement; OpenSearch Serverless outage; DynamoDB outage; S3 outage; HealthLake outage with conservative-no-context fallback; Step Functions outage with manual care-team workflow with audit; MWAA outage with queued-batch-ingestion; Connect outage with direct institutional crisis-line routing; Pinpoint outage with queued proactive-engagement; per-source ingestion outage with in-coverage-gap marking and confidence calibration. Failover-detection thresholds, failover-back triggers, quarterly testing cadence, cross-region failover for Bedrock and the institutional integrations (EHRs, HIE, payer claims, pharmacies, home-health, care-team-workflow). Crisis-pathway integrity preserved across all degraded states. -->

<!-- TODO (TechWriter): Expert review A2 (MEDIUM). Promote tool-surface contract management to architectural primitive: per-tool versioned schemas with semantic versioning across the thirteen-tool surface, per-tool deprecation policy, per-tool backward-compatibility discipline, per-tool change-management process owned jointly by engineering and clinical leadership and compliance, per-tool audit-stamp (extend Step 5B persist_tool_call_ledger to include per-tool version stamps for all thirteen tools), per-tool canary deployment with traffic-shift. -->

<!-- TODO (TechWriter): Expert review A3 (MEDIUM). Add Deployment Pattern subsection covering versioned system prompt, intent-classification prompt, per-handler response prompts, persona, redaction taxonomy, per-language consent-disclosure assets, Bedrock Guardrails policy version, knowledge-base corpus snapshots (coordination protocols, patient education, conversation history), and per-asset versions in version control with commit-SHA-tied builds. Bedrock inference profile for prompt-and-model versioning with rollback-on-regression. Held-out evaluation set covering representative coordination cases per condition, per-language, per-special-population, per-integration-coverage profile, per-transition-of-care destination, per-referral-specialty, per-medication-reconciliation scenario, per-seam-detection scenario, per-companion-pattern adversarial test, per-scope-violation adversarial test. Per-cohort canary deployment with traffic-shift. -->

<!-- TODO (TechWriter): Expert review A5 (MEDIUM). Promote per-event idempotency keys to architectural primitive in the EventBridge integration documentation; the Why-This-Isn't-Production-Ready section already enumerates the suggested keys but the architecture pattern itself does not specify the deduplication store discipline (DynamoDB with TTL) or the at-least-once delivery semantics. -->

<!-- TODO (TechWriter): Expert review A8 (MEDIUM). Add Accessibility Conformance cross-cutting design point: WCAG 2.1 AA conformance with named ownership at accessibility program manager. Per-channel accessibility considerations including SMS-friendly rendering for low-literacy patients, voice-channel availability for patients without smartphones or with disabilities affecting written communication, cognitive-load adaptations for patients with cognitive impairment (relevant to David's mild cognitive impairment in the opening case), screen-reader compatibility, and caregiver-specific accessibility considerations. High-acuity-event integrity preserved across accessibility configurations. Accessibility launch-gate criteria. -->

<!-- TODO (TechWriter): Expert review A9 (MEDIUM). Add "Care-Management Workforce Capacity Sizing as Architectural Primitive" subsection: peak-hour and overnight capacity sizing per patient population, per-state-licensure coverage, per-language coverage, queue-length-aware fallback, time-to-care-manager SLA per priority (high under 4 business hours; medium under 1 business day; low under 3 business days), workforce-capacity-as-launch-gate metric, named operational ownership at care-management workforce manager plus operations plus clinical leadership, hybrid AI-plus-human-care-management-as-dominant-production-pattern framing. -->

<!-- TODO (TechWriter): Expert review A10 (MEDIUM). Add Outcome-Correlation Pipeline subsection: data-integration with subsequent encounter records (institutional plus claims for cross-institution utilization), readmission records, ED-utilization records, duplicate-service detection, total-cost-of-care, clinical-outcome trajectories (HEDIS gap closure), patient-experience trajectories. Multi-window correlation (30-day, 90-day, 6-month, 12-month, 24-month, 36-month). Per-protocol outcome calculation with statistical-significance thresholds. Per-cohort outcome calculation per Finding A1. Protocol-revision feedback loop. Clinical-quality-review cadence. Operational ownership at clinical leadership plus data-science team plus operations plus compliance plus participating payer's analytics and quality teams. Explicit attribution-caveat discipline (observational, not causal; matched-cohort or quasi-experimental analysis where feasible). -->

<!-- TODO (TechWriter): Expert review S3 (MEDIUM). Add prompt-injection mitigation paragraph for the Bedrock Agents tool-orchestration path: delimited-input framing for the agent and per-handler tool-call LLMs (`<patient_utterance>`, `<verified_patient_context>`, `<conversation_history>`, `<coordination_state>`, `<retrieved_protocol>`, `<retrieved_education>`, `<ingested_clinical_data>`, `<provenance_metadata>`, `<tool_results>`), tool-Lambda enforcement of patient_id-cross-check audit logging (good at Step 5B; promote to architectural primitive), proxy-scope-denied audit logging, per-language jailbreak-test corpus including coordination-injection cases (manipulate continuous-emergency-screening, manipulate scope discipline, manipulate medication_list_reconcile to plant fabricated entries, manipulate seam_flags_retrieve to suppress high-priority seams, manipulate proxy-scope to reach restricted records, injection content in HL7/FHIR free-text fields). -->

<!-- TODO (TechWriter): Expert review S4 (MEDIUM). Specify per-claim-class faithfulness verification taxonomy: coordination-state-to-provenance, protocol-to-protocol-id-and-version-and-effective-date, patient-education-to-library-id-and-version, referral-state-to-referral-id-and-lifecycle-state, transition-of-care-to-transition-id-and-execution-id, medication-list-to-synthesized-list-version-and-source-records, seam-flag-to-seam-flag-id-and-rule-version. Add structured-output schema validation, LLM-judge faithfulness scoring as secondary check (independent verifier model protected from prompt injection), rule-based contradiction detection, regenerate-attempt budget, faithfulness-failure-rate as launch-gate metric per Finding A1. -->

<!-- TODO (TechWriter): Expert review S5 (MEDIUM). Expand retention floor specification in Prerequisites BAA / Compliance row to name the longest-of: HIPAA six-year, state-specific medical-record retention rules per state of patient residence (often 7-10+ years for adults; pediatric records often retained until age of majority plus state adult retention period producing 25+ year retention windows), state-specific mental-health-record retention rules where applicable, state-specific HIV-record and genetic-test-result retention rules where applicable, 42 CFR Part 2 retention obligations for substance-use treatment information where applicable, FDA SaMD post-market obligations where applicable, Information Blocking rule audit-trail obligations, per-channel retention obligations (TCPA/10DLC for SMS, voice-channel recording retention rules), per-record-class retention reconciliation, institutional regulatory floor. -->

<!-- TODO (TechWriter): Expert review S6 / A7 (MEDIUM). Specify Lambda invocation authentication pattern: each Lambda's resource-based policy pins invoking principal to production API Gateway stage ARN, Bedrock Agents action-group ARN, EventBridge rule ARN, Step Functions state-machine ARN, MWAA execution ARN, or Connect contact-flow ARN as appropriate. Defense-in-depth event-payload validation at start of each tool-Lambda. Tool-Lambda patient_id-cross-check audit logging (good at Step 5B; promote to architectural primitive with explicit security-event audit). Per-endpoint WAF rate-limit policy. -->

<!-- TODO (TechWriter): Expert review N1 (MEDIUM). Add Per-Channel Authentication and Encryption paragraph: per-channel data-in-transit posture, per-channel session-token TTL, per-channel access-control scope, per-channel BAA scope (institution app vendor BAA must explicitly cover embedded chat surface; caregiver-app under separate BAA scope; SMS under Pinpoint or Connect BAA; voice under Connect BAA), per-channel TCPA/10DLC compliance for SMS, per-channel voice-recording retention compliance, audit-record propagation of per-channel authentication context, high-acuity-event integrity across channels with same audit and routing fidelity, recipe-distinct caregiver-app channel discipline. -->

<!-- TODO (TechWriter): Expert review A4 (MEDIUM). Specify multi-language asset-development pattern: validated coordination-protocol translations as recipe-distinct safety-acute primitive (no ad-hoc machine translation; native-speaker review by clinical leadership for protocol chunks); validated patient-education translations across condition-specific content libraries with cultural-context calibration (help-seeking patterns, family structure, transportation/work/housing context); validated regulatory-disclaimer translations; validated caregiver-as-first-class-participant identity-model translations; per-language tone and persona calibration; per-language cultural-context calibration; per-language asset-versioning per Finding A3; per-language launch-gate per Finding A1. -->

---

## The AWS Implementation

### Why These Services

**Amazon Bedrock for the LLM and embeddings.** Same selection criteria as recipes 11.1 through 11.8. The care coordination assistant specifically benefits from a model with strong instruction-following for scope discipline across many adjacent topics, strong tool-use for orchestrating retrieval across heterogeneous coordination data, citation-grounding discipline for state assertions, and good multilingual support. Claude Sonnet-class models or comparable frontier models for the orchestration; smaller models for intent classification, seam-detection-rule pre-filtering, and routine summarization. Bedrock provides HIPAA-eligible deployment under BAA. The coordination assistant's longitudinal-relationship pattern across months and years places a premium on consistency of voice and on grounded citation behavior, both of which are attributes of the orchestration model selection.

**Amazon Bedrock Knowledge Bases for the coordination-protocol corpus and the patient-education library.** The institution's curated coordination-protocol library (transition-of-care protocols by destination setting, referral-tracking protocols by specialty and urgency, post-discharge protocols by admission type, post-procedure protocols by procedure category, medication-reconciliation protocols, condition-specific coordination playbooks) and the patient-education library are the assistant's grounded retrieval sources. Knowledge Bases provides the managed RAG layer with metadata-filtered retrieval (transition type, specialty, urgency tier, audience, language, reading level, version).

**Amazon Bedrock Agents for tool orchestration.** Same selection rationale as recipes 11.2 through 11.8. The assistant's tools (coordination_state_retrieve, referral_lifecycle_retrieve, encounter_retrieve, medication_list_reconcile, open_followups_retrieve, seam_flags_retrieve, protocol_retrieve, patient_education_content_retrieve, care_team_alert_propose, patient_action_propose, follow_up_schedule, escalation_propose, provenance_retrieve) are defined as Agents action groups with OpenAPI schemas. The Agent's traces preserve tool-call audit trails for the coordination-decision-record journal.

**Amazon Bedrock Guardrails for scope and content filtering.** Configured with denied topics including diagnosis-attempted, prescription-attempted, dose-titration-attempted, treatment-recommendation-beyond-existing-orders, therapy-attempted (which routes to recipe 11.8 pathway), triage-attempted (which routes to recipe 11.6 pathway), benefits-quote-attempted (which routes to recipe 11.5 pathway), and similar scope violations. The coordination assistant's scope discipline is broad because the assistant interacts with adjacent topics constantly and must defer cleanly across them.

**Amazon OpenSearch Serverless for the retrieval indices.** The coordination-protocol corpus, the patient-education library, and the longitudinal conversation history all benefit from vector retrieval with metadata filtering.

**AWS HealthLake for FHIR-native chart-context data.** HealthLake provides a managed FHIR data store the assistant queries for Patient, Encounter, Condition, MedicationRequest, MedicationStatement, Observation, DiagnosticReport, ServiceRequest, CarePlan, AllergyIntolerance, Immunization, Coverage, and related resources. Where the institution's primary EHR exposes a FHIR API directly, the assistant can query it directly; where multiple sources contribute, HealthLake serves as a normalization layer with consistent FHIR semantics across heterogeneous source data.

**AWS HealthLake Imaging and AWS HealthOmics are not in scope** for the coordination assistant; the assistant operates on encounter, medication, and observation data, not on imaging or genomics primary data, though the assistant references imaging and genomic test results at the report level when they are part of the patient's longitudinal record.

**AWS HealthLake Bulk Data Export and FHIR Bulk Data Access for population workflows.** Where the institution's coordination program operates over a population (a Medicare Advantage book of business; a primary-care panel; a transitions-of-care program from a participating hospital), bulk-data flows feed the program-wide analytics and the population-level seam detection.

**Amazon DynamoDB for state, longitudinal store, and provenance journal.** Multiple tables supporting the assistant's longitudinal pattern: `patient-coordination-store` (per-patient stable state including stated preferences, designated caregivers, integration coverage, consent posture), `coordination-state-store` (active conditions, medications, referrals, encounters, results, care events, seam-flags), `referral-lifecycle-store` (per-referral state machine), `transition-of-care-store` (per-transition state machine), `seam-flag-store` (detected gaps with status), `caregiver-store` (per-caregiver identity, proxy-access scope, message preferences), `conversation-state` (per-conversation transient state), `conversation-metadata` (per-conversation turn-by-turn data), `tool-call-ledger` (audited tool invocations), `coordination-decision-record-journal` (durable record of coordination events with citations), `provenance-journal` (per-data-point provenance chain), and `consent-record` (consent posture per data source and per sharing relationship).

**Amazon S3 for the protocol corpus, patient-education library, conversation archive, coordination-decision-record journal, provenance journal, and outcome-correlation data.** Object Lock in compliance mode for the retention window, with retention sized to the longest of HIPAA's six-year minimum, state-specific medical-record retention, and any FDA SaMD post-market obligations.

**AWS Lambda for the conversation handler, ingestion adapters, seam-detection workers, protocol-trigger workers, tool implementations, care-team reporting, and outcome correlation.** Same pattern as the previous chapter 11 recipes, with additional Lambda functions for each ingestion adapter (HL7 listener, FHIR poller, claims-batch processor, pharmacy-API consumer, vendor-API consumer) and each seam-detection rule.

**Amazon API Gateway and AWS WAF for the public chat endpoint.** Same as the other recipes.

**AWS HealthLake plus AWS HealthLake Bulk Data, plus optional integration via AWS Lake Formation for data-sharing across organizations under TEFCA participation.** Cross-organizational data flows operate within the legal framework specified by the regulatory team.

**Amazon EventBridge for the coordination-event bus.** Events including patient_enrolled, caregiver_designated, integration_connected, encounter_ingested, referral_ordered, referral_scheduled, referral_completed, transition_initiated, transition_completed, medication_filled, medication_discontinued, lab_result_posted, seam_flag_raised, seam_flag_resolved, care_team_alert_generated, escalation_routed, coordination_decision_recorded.

**AWS Step Functions for transition-of-care orchestration workflows.** Each transition (hospital-to-home, hospital-to-SNF, ED-to-primary-care follow-up, surgery-to-home, etc.) runs as a Step Functions workflow with states for the protocol-defined steps (medication reconciliation, follow-up-appointment scheduling, home-health or DME orders, patient education, red-flag warning instructions, completion verification). The state machines are version-controlled and audited.

**Amazon MWAA (Managed Workflows for Apache Airflow) or AWS Step Functions for population-scale data ingestion and seam-detection batch jobs.** Where bulk-data ingestion and population-level seam detection run on schedules rather than per-event, MWAA or Step Functions orchestrates the batch workloads.

**Amazon Pinpoint for proactive engagement messaging.** Care-event-triggered messages (post-discharge welcome-home check-in, referral-scheduling reminders, appointment-prep nudges, lab-result acknowledgement prompts, missed-appointment follow-ups) are delivered via Pinpoint with delivery-status tracking, channel-preference enforcement, and quiet-hours discipline.

**Amazon Connect for warm-handoff to human care managers and clinical staff.** When the assistant escalates to a human (high-acuity gap, sensitive disclosure, conflicting-order resolution that requires clinical judgment), Connect routes to the appropriate queue with conversation context attached. Care managers are reachable via Connect's chat and voice queues.

**AWS KMS, AWS Secrets Manager, Amazon CloudWatch, AWS CloudTrail, Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena.** Same operational and audit primitives as the previous recipes, with coordination-specific KMS key separation for the cross-organizational ingestion surface, the provenance journal, and the coordination-decision-record store.

**Amazon QuickSight for clinical, operational, and outcome dashboards.** Per-cohort coordination dashboards (referral closure rate, transition-of-care completion rate, medication-reconciliation accuracy, seam-detection rate, seam-resolution rate, escalation rate, patient-and-caregiver-reported coordination experience), engagement dashboards, and outcome-correlation dashboards.

**Amazon SageMaker (optional) for custom seam-detection model hosting.** Several seam-detection rules (patterns suggestive of decompensation, complex medication-discrepancy cases that require nuanced reasoning, caregiver-burden trajectory) benefit from custom-trained classifiers; SageMaker provides the hosted-inference endpoint where deployed.

**Amazon Comprehend Medical (optional) for medical-named-entity recognition over patient-and-caregiver-reported text.** When the patient or caregiver reports a medication name, a symptom, a clinician name, or a related entity in conversation, Comprehend Medical can extract structured terms for matching against the coordination state.

### Architecture Diagram

```mermaid
flowchart LR
    subgraph Channels
      WEB[Web Chat]
      APP[Institution App]
      SMS[SMS via Pinpoint/Connect]
      VOICE[Voice via Connect]
      CGAPP[Caregiver App]
    end

    subgraph Edge
      WAF[AWS WAF]
      APIGW[API Gateway]
    end

    subgraph Conversation_Core
      L_CHAT[Lambda<br/>chat handler]
      L_INPUT[Lambda<br/>input screening<br/>+ continuous emergency screen]
      L_OUTPUT[Lambda<br/>output safety<br/>+ provenance verify]
      L_IDENTITY[Lambda<br/>identity + role +<br/>coordination context loading]
    end

    subgraph LLM_and_Agent
      AGENT[Bedrock Agents]
      BEDROCK[Bedrock<br/>LLM generation]
      KB_PROTOCOL[Bedrock Knowledge Bases<br/>coordination protocols]
      KB_EDU[Bedrock Knowledge Bases<br/>patient education]
      KB_HIST[Bedrock Knowledge Bases<br/>conversation history]
      GUARDRAILS[Bedrock Guardrails]
      OS[OpenSearch Serverless]
      COMP_MED[Comprehend Medical]
    end

    subgraph Coordination_Tools
      L_STATE[Lambda<br/>coordination_state_retrieve]
      L_REFERRAL[Lambda<br/>referral_lifecycle_retrieve]
      L_ENCOUNTER[Lambda<br/>encounter_retrieve]
      L_MEDREC[Lambda<br/>medication_list_reconcile]
      L_FOLLOWUP[Lambda<br/>open_followups_retrieve]
      L_SEAM[Lambda<br/>seam_flags_retrieve]
      L_PROTOCOL[Lambda<br/>protocol_retrieve]
      L_EDU[Lambda<br/>patient_education_retrieve]
      L_ALERT[Lambda<br/>care_team_alert_propose]
      L_ACTION[Lambda<br/>patient_action_propose]
      L_SCHED[Lambda<br/>follow_up_schedule]
      L_ESC[Lambda<br/>escalation_propose]
      L_PROV[Lambda<br/>provenance_retrieve]
    end

    subgraph Cross_Org_Ingestion
      L_HL7[Lambda<br/>HL7 v2 listener]
      L_FHIR[Lambda<br/>FHIR poller/<br/>subscription]
      L_CLAIMS[Lambda<br/>claims-feed processor]
      L_PHARM[Lambda<br/>pharmacy-API consumer]
      L_HOMEHEALTH[Lambda<br/>home-health vendor]
      L_HIE[Lambda<br/>HIE/TEFCA adapter]
      MWAA[MWAA<br/>batch ingestion]
    end

    subgraph Seam_Detection_and_Triggers
      L_SEAM_ENG[Lambda<br/>seam-detection<br/>rule engine]
      L_TRIGGER[Lambda<br/>protocol-trigger<br/>evaluator]
      SAGEMAKER[SageMaker<br/>custom seam<br/>classifiers]
    end

    subgraph Transition_Orchestration
      SFN[Step Functions<br/>transition-of-care<br/>workflows]
      L_TRANS[Lambda<br/>transition state<br/>machine workers]
    end

    subgraph External_Integrations
      EHRS[(Multiple EHRs<br/>via FHIR)]
      HEALTHLAKE[(AWS HealthLake)]
      HIE[(HIE / TEFCA QHIN)]
      PAYER[(Payer claims feed)]
      PHARM[(Pharmacies<br/>NCPDP / vendor APIs)]
      HOMEHEALTH_EXT[(Home-health<br/>agencies)]
      LAB[(Lab feeds)]
      CARE_TEAM[(Patient's care team<br/>across organizations)]
      CARE_MGMT[(Institutional<br/>care-management)]
      TRIAGE[(Recipe 11.6 triage)]
      MH[(Recipe 11.8 mental<br/>health pathway)]
      EMERG[(911 / 988)]
      NAV[(Care navigation /<br/>social services)]
    end

    subgraph State_and_Audit
      DDB_PT[(DynamoDB<br/>patient coordination<br/>store)]
      DDB_STATE[(DynamoDB<br/>coordination state)]
      DDB_REFERRAL[(DynamoDB<br/>referral lifecycle)]
      DDB_TRANS[(DynamoDB<br/>transition of care)]
      DDB_SEAM[(DynamoDB<br/>seam flags)]
      DDB_CG[(DynamoDB<br/>caregivers)]
      DDB_SESS[(DynamoDB<br/>conversation state)]
      DDB_META[(DynamoDB<br/>conversation<br/>metadata)]
      DDB_TOOL[(DynamoDB<br/>tool-call ledger)]
      DDB_DECISION[(DynamoDB<br/>coordination<br/>decision journal)]
      DDB_PROV[(DynamoDB<br/>provenance journal)]
      DDB_CONSENT[(DynamoDB<br/>consent record)]
      S3_PROTOCOL[(S3<br/>coordination<br/>protocols)]
      S3_EDU[(S3<br/>patient education)]
      S3_AUDIT[(S3<br/>audit archive)]
      S3_DECISION[(S3<br/>decision-record<br/>journal)]
      S3_PROV[(S3<br/>provenance<br/>archive)]
    end

    subgraph Reporting_and_Analytics
      L_REPORT[Lambda<br/>care-team reporting]
      L_OUTCOME[Lambda<br/>outcome correlation]
      EB[EventBridge]
      KIN[Kinesis Firehose]
      ATH[Athena]
      QS[QuickSight]
      CW[CloudWatch]
      CT[CloudTrail]
      PIN[Pinpoint<br/>proactive engagement]
      CONNECT[Amazon Connect<br/>warm handoff]
    end

    subgraph Secrets_and_Keys
      SM_SEC[(Secrets Manager)]
      KMS[(AWS KMS)]
      KMS_PROV[(KMS<br/>provenance key)]
      KMS_DECISION[(KMS<br/>decision-record key)]
    end

    WEB --> WAF
    APP --> WAF
    CGAPP --> WAF
    SMS --> APIGW
    VOICE --> APIGW
    WAF --> APIGW
    APIGW --> L_CHAT

    EHRS --> L_FHIR
    EHRS --> L_HL7
    HIE --> L_HIE
    PAYER --> L_CLAIMS
    PHARM --> L_PHARM
    HOMEHEALTH_EXT --> L_HOMEHEALTH
    LAB --> L_HL7
    L_HL7 --> HEALTHLAKE
    L_FHIR --> HEALTHLAKE
    L_CLAIMS --> DDB_STATE
    L_PHARM --> DDB_STATE
    L_HOMEHEALTH --> DDB_STATE
    L_HIE --> HEALTHLAKE
    MWAA --> L_FHIR
    MWAA --> L_CLAIMS

    L_HL7 --> DDB_PROV
    L_FHIR --> DDB_PROV
    L_CLAIMS --> DDB_PROV
    L_PHARM --> DDB_PROV
    L_HOMEHEALTH --> DDB_PROV
    L_HIE --> DDB_PROV

    L_HL7 --> EB
    L_FHIR --> EB
    L_CLAIMS --> EB
    L_PHARM --> EB
    L_HOMEHEALTH --> EB
    EB --> L_SEAM_ENG
    EB --> L_TRIGGER
    L_SEAM_ENG --> SAGEMAKER
    L_SEAM_ENG --> DDB_SEAM
    L_TRIGGER --> SFN
    SFN --> L_TRANS
    L_TRIGGER --> PIN
    L_TRIGGER --> L_ALERT

    L_CHAT --> L_INPUT
    L_INPUT --> TRIAGE
    L_INPUT --> MH
    L_INPUT --> EMERG
    L_CHAT --> L_IDENTITY
    L_IDENTITY --> DDB_PT
    L_IDENTITY --> DDB_CG
    L_IDENTITY --> DDB_STATE
    L_IDENTITY --> DDB_CONSENT
    L_CHAT --> AGENT
    AGENT --> BEDROCK
    AGENT --> KB_PROTOCOL
    AGENT --> KB_EDU
    AGENT --> KB_HIST
    KB_PROTOCOL --> OS
    KB_EDU --> OS
    KB_HIST --> OS
    AGENT --> GUARDRAILS
    AGENT --> COMP_MED
    AGENT --> L_STATE
    AGENT --> L_REFERRAL
    AGENT --> L_ENCOUNTER
    AGENT --> L_MEDREC
    AGENT --> L_FOLLOWUP
    AGENT --> L_SEAM
    AGENT --> L_PROTOCOL
    AGENT --> L_EDU
    AGENT --> L_ALERT
    AGENT --> L_ACTION
    AGENT --> L_SCHED
    AGENT --> L_ESC
    AGENT --> L_PROV
    L_STATE --> DDB_STATE
    L_REFERRAL --> DDB_REFERRAL
    L_ENCOUNTER --> HEALTHLAKE
    L_MEDREC --> DDB_STATE
    L_FOLLOWUP --> DDB_STATE
    L_SEAM --> DDB_SEAM
    L_PROTOCOL --> KB_PROTOCOL
    L_EDU --> KB_EDU
    L_ALERT --> CONNECT
    L_ALERT --> CARE_MGMT
    L_ESC --> CONNECT
    L_PROV --> DDB_PROV
    L_CHAT --> L_OUTPUT
    L_OUTPUT --> DDB_DECISION
    L_OUTPUT --> S3_DECISION
    AGENT --> DDB_TOOL
    L_CHAT --> DDB_SESS
    L_CHAT --> DDB_META

    L_REPORT --> CARE_TEAM
    L_REPORT --> CARE_MGMT
    L_OUTCOME --> S3_AUDIT
    EB --> KIN
    KIN --> S3_AUDIT
    S3_AUDIT --> ATH
    S3_DECISION --> ATH
    S3_PROV --> ATH
    ATH --> QS
    L_CHAT --> CW
    APIGW --> CT
    L_FHIR --> SM_SEC
    L_CLAIMS --> SM_SEC
    L_PHARM --> SM_SEC
    L_HOMEHEALTH --> SM_SEC
    KMS --> S3_AUDIT
    KMS --> S3_PROTOCOL
    KMS --> S3_EDU
    KMS_DECISION --> S3_DECISION
    KMS_DECISION --> DDB_DECISION
    KMS_PROV --> DDB_PROV
    KMS_PROV --> S3_PROV
    KMS --> DDB_PT
    KMS --> DDB_STATE
    KMS --> DDB_REFERRAL
    KMS --> DDB_TRANS
    KMS --> DDB_SEAM
    KMS --> DDB_CG
    KMS --> DDB_SESS
    KMS --> DDB_META
    KMS --> DDB_TOOL
    KMS --> DDB_CONSENT
    KMS --> SM_SEC

    style AGENT fill:#fcf,stroke:#333
    style BEDROCK fill:#fcf,stroke:#333
    style KB_PROTOCOL fill:#fcf,stroke:#333
    style KB_EDU fill:#fcf,stroke:#333
    style GUARDRAILS fill:#fcf,stroke:#333
    style L_INPUT fill:#fcc,stroke:#900,stroke-width:3px
    style L_OUTPUT fill:#fcc,stroke:#900,stroke-width:3px
    style L_SEAM_ENG fill:#fcc,stroke:#900,stroke-width:3px
    style EHRS fill:#ccf,stroke:#333
    style HIE fill:#ccf,stroke:#333
    style PAYER fill:#ccf,stroke:#333
    style PHARM fill:#ccf,stroke:#333
    style EMERG fill:#ccf,stroke:#900,stroke-width:3px
    style TRIAGE fill:#ccf,stroke:#333
    style MH fill:#ccf,stroke:#333
    style HEALTHLAKE fill:#ccf,stroke:#333
    style CARE_TEAM fill:#ccf,stroke:#333
    style CARE_MGMT fill:#ccf,stroke:#333
    style DDB_STATE fill:#9ff,stroke:#333,stroke-width:3px
    style DDB_PROV fill:#9ff,stroke:#900,stroke-width:3px
    style DDB_DECISION fill:#9ff,stroke:#333
    style DDB_REFERRAL fill:#9ff,stroke:#333
    style DDB_TRANS fill:#9ff,stroke:#333
    style DDB_SEAM fill:#9ff,stroke:#333
    style S3_DECISION fill:#cfc,stroke:#333
    style S3_PROV fill:#cfc,stroke:#900,stroke-width:3px
    style KMS_PROV fill:#fcc,stroke:#900,stroke-width:3px
    style KMS_DECISION fill:#fcc,stroke:#900,stroke-width:3px
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | Amazon Bedrock (Agents, Knowledge Bases, Guardrails, foundation model with strong tool-use, embedding model), Amazon OpenSearch Serverless, AWS HealthLake, AWS Lambda, AWS Step Functions, Amazon MWAA (or AWS Step Functions for batch ingestion), Amazon API Gateway, AWS WAF, Amazon DynamoDB, Amazon S3, AWS KMS (with separate keys for the provenance journal and the coordination-decision-record store), AWS Secrets Manager, Amazon CloudWatch, AWS CloudTrail, Amazon EventBridge, Amazon Kinesis Data Firehose, AWS Glue, Amazon Athena, Amazon Pinpoint, Amazon Connect (warm-handoff to human care managers and clinical staff), Amazon QuickSight (dashboards), Amazon Comprehend Medical (medical NER over patient-and-caregiver-reported text). Optionally: Amazon SageMaker (custom seam-detection classifier hosting). |
| **External Inputs** | Multiple EHRs via FHIR APIs (USCDI v3 or later) for participating organizations (Patient, Encounter, Condition, MedicationRequest, MedicationStatement, Observation, DiagnosticReport, ServiceRequest, CarePlan, AllergyIntolerance, Immunization, Coverage). HL7 v2 ADT and ORU feeds from participating hospitals. HIE and TEFCA QHIN integration where the institution participates. Payer claims feeds where the institution has a claims-data partnership. Pharmacy data via NCPDP standards or vendor APIs (CVS, Walgreens, Walmart, regional chains, mail-order, specialty pharmacies). Home-health vendor APIs from connected agencies. Lab feeds from connected labs (LabCorp, Quest, regional reference labs, hospital labs). Coordination-protocol corpus curated and version-controlled by clinical leadership including transition-of-care protocols (hospital-to-home, hospital-to-SNF, ED-to-primary-care follow-up, surgery-to-home, oncology-treatment cycles), referral-tracking protocols by specialty and urgency, post-discharge protocols, post-procedure protocols, medication-reconciliation protocols, condition-specific coordination playbooks for high-prevalence multi-condition combinations. Patient-education library reviewed by clinical leadership and patient-experience leadership, multilingual and multi-reading-level. Care-management workforce capacity (employed or contracted) sized to expected escalation volume. Identity-and-proxy-access infrastructure with state-specific caregiver-consent compliance. Consent-management infrastructure with per-data-source and per-sharing-relationship tracking. <!-- TODO: verify; specific external inputs vary by institution; the cross-organizational coverage profile is the largest single configuration question --> |
| **IAM Permissions** | Per-Lambda least-privilege roles. The HL7 listener and FHIR poller Lambdas have read access to the connected EHR endpoints with credentials in Secrets Manager. The claims-feed processor has read access to the payer's claims-feed endpoint. The pharmacy-API consumer has read access to connected pharmacy APIs. The home-health vendor Lambda has read access to connected agency APIs. Each ingestion Lambda has write access to the provenance journal and to the relevant coordination-state tables. The seam-detection rule engine has read access to coordination-state tables and write access to the seam-flag store. The coordination-decision-record-recording Lambda has write access to the decision-record store. The escalation Lambda has write access to the Connect queue. None of the assistant's Lambdas have write access to the clinical record except for institutionally-approved coordination-event records (e.g., FHIR Communication resources for the conversation log; FHIR ServiceRequest resources for follow-up scheduling where the institution permits assistant-originated requests; with explicit patient consent and institutional clinical-leadership signoff). Resource-based policies pin invoking principals to the production agent and API Gateway stage ARNs. |
| **BAA and Compliance** | AWS BAA signed. Verify all services in scope are HIPAA-eligible at build time. The assistant is patient-and-caregiver-facing PHI from multiple organizations, with cross-organizational data integration and data-sharing implications. Legal counsel familiar with HIPAA, the Information Blocking and Interoperability rules, TEFCA participation requirements, state-specific medical-record statutes, state-specific caregiver-consent and proxy-access laws, 42 CFR Part 2 (substance-use treatment), state-specific mental-health-record protections, state-specific HIV-record and genetic-test-result protections, state-specific adolescent confidentiality, and (where the assistant produces clinical recommendations) the FDA SaMD framework reviews the data-handling posture. The institutional regulatory team reviews the FDA-strategy positioning before launch and on each material scope change. The institutional malpractice insurer is part of the policy review. State-specific regulations on AI-mediated patient communication, on telehealth, and on care-management may apply. <!-- TODO: verify; coordination-software regulatory landscape includes HIPAA, the ONC Information Blocking and Interoperability rules under the 21st Century Cures Act, state medical-record and caregiver-consent statutes, FDA SaMD framework, and where applicable 42 CFR Part 2 and state-specific sensitive-record protections --> |
| **Encryption** | Coordination-protocol corpus, patient-education library, conversation archive, coordination-decision-record journal: SSE-KMS with customer-managed keys. Provenance journal: SSE-KMS with separately-managed customer key for blast-radius containment and for separate-access-control discipline. Coordination-decision-record journal: SSE-KMS with separately-managed customer key. S3 archives: Object Lock in compliance mode for the retention window. DynamoDB tables: customer-managed KMS at rest, with sensitive tables (provenance journal, coordination-decision-record journal) on separate keys. Lambda environment variables: KMS-encrypted. Secrets Manager: customer-managed KMS. TLS in transit for all AWS API calls and all integrations with external systems including HL7 and FHIR endpoints. |
| **VPC** | Production: ingestion Lambdas (HL7 listener, FHIR poller, claims-feed processor, pharmacy-API consumer, home-health vendor, HIE adapter), tool Lambdas that call EHRs, care-management workflows, escalation pathways, and care-navigation systems run in VPC with controlled egress. PrivateLink to vendor-hosted endpoints where supported; tightly-scoped NAT path with allow-list otherwise. VPC endpoints for DynamoDB, S3, KMS, Secrets Manager, CloudWatch Logs, EventBridge, Bedrock, OpenSearch Serverless, HealthLake, Step Functions, MWAA, Pinpoint, Connect, Comprehend Medical, and SageMaker (where used). The patient-and-caregiver-facing edge is public; the back-office and cross-organizational-integration traffic is private. |
| **CloudTrail** | Enabled with data events on all sensitive S3 buckets (audit-archive, coordination-decision-record-journal, provenance-archive, coordination-protocol corpus, patient-education library) and DynamoDB tables (coordination-state, provenance journal, coordination-decision-record journal, referral-lifecycle, transition-of-care, seam-flag, caregiver, consent record, etc.), Secrets Manager secrets, and customer-managed KMS keys. Bedrock and Bedrock Agents invocations logged. Lambda invocations logged. API Gateway access logs enabled. Step Functions execution logs enabled. MWAA execution logs enabled. Connect interactions logged with appropriate retention. Pinpoint message-status logs preserved. CloudTrail logs in a dedicated S3 bucket with Object Lock in compliance mode. Audit retention sized to the longest of HIPAA's six-year minimum, state-specific medical-record retention rules, FDA SaMD post-market obligations where applicable, and litigation-hold obligations. |
| **Sample Data** | Synthetic patient profiles stratified by chronic-condition mix, by post-discharge episode type, by post-procedure recovery, by oncology-treatment-cycle phase, by caregiver presence, by integration coverage profile (well-instrumented vs. partially-instrumented vs. poorly-instrumented), by language, by socioeconomic context, by social-determinant flags. Synthetic FHIR bundles, HL7 v2 messages, claims feeds, pharmacy fills, and home-health visit notes. Synthetic conversation histories covering enrollment, post-discharge windows, referral-tracking lifecycles, transition-of-care orchestration, medication-reconciliation episodes, caregiver-burden disclosures, and escalation scenarios. Coordination-protocol corpus reviewed by clinical leadership across primary care, hospital medicine, specialty practice, pharmacy, home health, and care management. Patient-education library reviewed by clinical leadership and patient-experience leadership in multiple languages and reading levels. Test EHRs, HIEs, payer claims, pharmacy, home-health, and care-management systems with synthetic data. Test caregiver-proxy-access scenarios across multiple state-law jurisdictions. |
| **Cost Estimate** | At a mid-sized payer or integrated-delivery-network scale (50,000 enrolled members across multiple acuity tiers; average 1-4 conversational engagements per week per active member; average 4-10 turns per engagement; average 2,500 tokens of prompt and 500 tokens of response per turn for the orchestration model plus tool-call overhead; plus ingestion processing across HL7, FHIR, claims, pharmacy, home-health, HIE; plus seam-detection and protocol-trigger evaluation): Bedrock LLM invocations typically $3-8 per active member per month for a Sonnet-class orchestration model, totaling approximately $1.8M-4.8M per year. Bedrock Agents and Knowledge Bases hosting plus the OpenSearch Serverless retrieval indices typically $80,000-300,000 per year. Lambda, API Gateway, WAF, DynamoDB, S3, KMS, Secrets Manager, CloudWatch, CloudTrail, EventBridge, Kinesis Firehose, Glue, Athena, Step Functions, MWAA total approximately $200,000-700,000 per year combined (the cross-organizational ingestion volume is the dominant driver among these). AWS HealthLake typically $80,000-400,000 per year (varies with FHIR-resource volume and population size). Pinpoint typically $30,000-150,000 per year. Connect typically $80,000-400,000 per year. Comprehend Medical typically $20,000-100,000 per year. SageMaker (when used) typically $20,000-80,000 per year. Total AWS infrastructure typically $2.3M-7.0M per year at this scale (approximately $4-12 per active member per month). The care-management workforce cost (employed or contracted nurse case managers, social workers, care coordinators) is typically larger than the AWS infrastructure cost and is the dominant operational expense; a deployment that under-invests in human care-management capacity is a deployment with safety gaps and missed coordination value. <!-- TODO: replace with verified pricing once the implementing team validates against the AWS Pricing Calculator; specific costs depend on Bedrock model choice, conversation volume, ingestion volume across HL7/FHIR/claims/pharmacy/HIE, FHIR-source choice, escalation rate, and channel mix --> |

### Ingredients

| AWS Service | Role |
|------------|------|
| **Amazon Bedrock** | LLM for orchestration and conversational response generation; embedding model for the coordination-protocol corpus, patient-education library, and conversation history |
| **Amazon Bedrock Agents** | Tool orchestration: define coordination tools as action groups, manage the multi-step LLM-and-tool flow |
| **Amazon Bedrock Knowledge Bases** | Managed RAG over (a) coordination protocols, (b) patient-education library, (c) longitudinal conversation history. Metadata-filtered retrieval (transition type, specialty, urgency tier, audience, language, reading level, version) |
| **Amazon OpenSearch Serverless** | Vector and lexical retrieval index backing each Knowledge Base |
| **Amazon Bedrock Guardrails** | Content filtering for diagnosis-attempted, prescription-attempted, dose-titration-attempted, treatment-recommendation-beyond-existing-orders, therapy-attempted (route to recipe 11.8), triage-attempted (route to recipe 11.6), benefits-quote-attempted (route to recipe 11.5) |
| **AWS Lambda** | Chat handler, input/output safety, identity-role-and-coordination-context loading, ingestion adapters (HL7, FHIR, claims, pharmacy, home-health, HIE), seam-detection rule engine, protocol-trigger evaluator, transition-of-care state-machine workers, care-team reporting, outcome correlation, and tool implementations (coordination_state_retrieve, referral_lifecycle_retrieve, encounter_retrieve, medication_list_reconcile, open_followups_retrieve, seam_flags_retrieve, protocol_retrieve, patient_education_content_retrieve, care_team_alert_propose, patient_action_propose, follow_up_schedule, escalation_propose, provenance_retrieve) |
| **AWS Step Functions** | Transition-of-care workflows with states for protocol-defined steps; transition state machines version-controlled and audited |
| **Amazon MWAA** | Population-scale batch ingestion (FHIR Bulk Data exports, claims-feed periodic refresh, population-level seam-detection runs) |
| **Amazon API Gateway** | Public-facing chat endpoint for web, app, SMS, voice, and caregiver-app channels |
| **AWS WAF** | Rate limiting, bot detection, common attack patterns |
| **Amazon DynamoDB** | patient-coordination-store, coordination-state-store, referral-lifecycle-store, transition-of-care-store, seam-flag-store, caregiver-store, conversation-state, conversation-metadata, tool-call-ledger, coordination-decision-record-journal, provenance-journal, consent-record |
| **Amazon S3** | Coordination-protocol corpus, patient-education library, conversation archive, coordination-decision-record journal, provenance archive, outcome-correlation data |
| **AWS HealthLake** | FHIR-native data store normalizing data from multiple EHRs and HIE feeds (Patient, Encounter, Condition, MedicationRequest, MedicationStatement, Observation, DiagnosticReport, ServiceRequest, CarePlan, AllergyIntolerance, Immunization, Coverage) |
| **AWS KMS** | Customer-managed encryption keys per data class, with separate keys for the provenance journal and the coordination-decision-record journal |
| **AWS Secrets Manager** | Credentials for EHRs, HIE/TEFCA endpoints, payer claims feeds, pharmacy APIs, home-health vendor APIs, care-management workflow systems, escalation pathways |
| **Amazon CloudWatch** | Operational metrics (referral closure rate, transition-of-care completion rate, medication-reconciliation accuracy, seam-detection rate, seam-resolution rate, escalation rate, citation-coverage rate, per-cohort slices); alarms |
| **AWS CloudTrail** | API-level audit logging |
| **Amazon EventBridge** | Coordination-event bus (patient_enrolled, caregiver_designated, integration_connected, encounter_ingested, referral_ordered, referral_scheduled, referral_completed, transition_initiated, transition_completed, medication_filled, medication_discontinued, lab_result_posted, seam_flag_raised, seam_flag_resolved, care_team_alert_generated, escalation_routed, coordination_decision_recorded) |
| **Amazon Pinpoint** | Proactive care-event-triggered messaging (post-discharge welcome-home check-in, referral-scheduling reminders, appointment-prep nudges, lab-result acknowledgement prompts, missed-appointment follow-ups) with delivery-status tracking, channel-preference enforcement, and quiet-hours discipline |
| **Amazon Connect** | Warm-handoff queue for human care managers and clinical staff (chat and voice), routing integration with care-management leadership |
| **Amazon Kinesis Data Firehose** | Streaming audit and telemetry delivery |
| **AWS Glue Data Catalog + Amazon Athena** | SQL access to audit, decision-record, provenance, and telemetry data |
| **Amazon Comprehend Medical** | Medical NER over patient-and-caregiver-reported text for matching against the coordination state |
| **Amazon SageMaker (where used)** | Hosted custom seam-detection classifiers (decompensation patterns, complex medication-discrepancy reasoning, caregiver-burden trajectory) |
| **Amazon QuickSight** | Clinical, operational, and outcome dashboards with per-cohort slices |

---

### Code

#### Walkthrough

**Step 1: Enroll the patient and capture cross-organizational consent with caregiver setup.** Enrollment is more involved than for the previous chapter 11 bots because the consent posture covers multiple data sources, multiple sharing relationships, and (often) one or more caregivers with proxy-access scope. The consent flow has been reviewed by legal counsel familiar with HIPAA, the Information Blocking rule, state-specific medical-record statutes, state-specific caregiver-consent rules, and (where applicable) 42 CFR Part 2, state-specific mental-health-record protections, and other sensitive-record rules. Skip this step or treat it as boilerplate, and the deployment's regulatory posture is compromised before the first conversation.

```
ON enroll_patient(patient_id, enrollment_program_id,
                  legal_consent_form_signed,
                  caregiver_designations,
                  state_of_residence):
    // Step 1A: validate the patient is eligible for the
    // institution's deployment scope.
    eligibility = check_eligibility({
        patient_id: patient_id,
        program: enrollment_program_id,
        excluded_populations: INSTITUTION_EXCLUDED_POPULATIONS
            // typically: patients in active hospice (where a
            // hospice-specific coordination tool is more
            // appropriate); patients whose primary coordination
            // is delivered by a contracted external care
            // navigator (where the coordination relationship is
            // already owned by another entity); minors in
            // adult-only deployments; others per institutional
            // clinical-leadership policy
    })

    IF NOT eligibility.eligible:
        return {
            action: "enrollment_declined",
            reason: eligibility.reason,
            referral: eligibility.recommended_alternative
        }

    // Step 1B: capture cross-organizational consent posture.
    // Consent is per data source and per sharing relationship.
    // The consent record is the operational gate the
    // architecture enforces; it is not optional and not
    // bypass-able from the assistant.
    consent_record = capture_consent({
        patient_id: patient_id,
        data_sources: enumerate_known_sources(patient_id),
            // primary care EHR, hospital EHR(s), specialty
            // EHR(s), HIE participation, payer claims feed,
            // pharmacies (each), home-health agency, lab(s)
        sharing_relationships: [
            "with_primary_care",
            "with_specialists",
            "with_care_management",
            "with_designated_caregivers"
        ],
        sensitive_record_categories: [
            // each requires explicit category-specific consent
            // per state and federal rules
            "mental_health_records",
            "substance_use_records_42_cfr_part_2",
            "hiv_records",
            "genetic_test_results",
            "adolescent_confidential_records"
        ],
        revocability: "revocable_at_any_time_per_category",
        state_of_residence: state_of_residence
    })

    // Step 1C: capture caregiver designations.
    // Each caregiver gets a separate identity, separate
    // authentication, separate proxy-access scope, and
    // separate state-law access posture.
    caregiver_records = []
    FOR each cg IN caregiver_designations:
        proxy_scope = capture_proxy_access_scope({
            patient_id: patient_id,
            caregiver_identity: cg,
            access_level: cg.requested_access,
                // values: "full", "scheduling_only",
                // "medications_only", "education_only",
                // "emergency_contact_only"
            sensitive_record_carve_outs: cg.sensitive_carve_outs,
                // patient may withhold mental-health records
                // from a caregiver while granting other access
            state_law_check: check_state_caregiver_law(
                state_of_residence, cg.relationship)
                // some states require notarized HCP/POA
                // documentation, others have specific rules for
                // adolescents and aging adults
        })
        caregiver_records.append(proxy_scope)

    // Step 1D: identify the patient's known clinicians,
    // pharmacies, payers, and ancillary services.
    known_relationships = capture_known_relationships({
        patient_id: patient_id,
        clinicians: enumerate_clinicians(patient_id),
        pharmacies: enumerate_pharmacies(patient_id),
        payers: enumerate_payers(patient_id),
        ancillary_services: enumerate_ancillary(patient_id)
    })

    // Step 1E: capture preferences (channels, quiet hours,
    // language, preferred name, what to discuss with whom).
    preferences = capture_preferences({
        patient_id: patient_id,
        channels: ["app", "sms", "voice", "email"],
        quiet_hours: prompt_for_quiet_hours(),
        language: prompt_for_language(),
        preferred_name: prompt_for_preferred_name(),
        caregiver_routing_preferences:
            prompt_for_caregiver_routing()
    })

    // Step 1F: persist enrollment artifacts.
    persist_enrollment({
        patient_id: patient_id,
        consent_record: consent_record,
        caregiver_records: caregiver_records,
        known_relationships: known_relationships,
        preferences: preferences,
        program: enrollment_program_id,
        state_of_residence: state_of_residence,
        enrollment_timestamp: now(),
        consent_versions: snapshot_consent_versions(),
        enrolling_user: signing_user
    })

    // Step 1G: emit enrollment event for downstream systems.
    emit_event("patient_enrolled", {patient_id, program})
    FOR each cg IN caregiver_records:
        emit_event("caregiver_designated",
                   {patient_id, caregiver_id: cg.id})

    return {
        action: "enrolled",
        patient_id: patient_id,
        coordination_state_initialized: true
    }
```

What can go wrong if you skip or shortcut this: the assistant operates without a defensible consent posture across organizations, the caregiver-access model is ad-hoc, the patient's preferences are not captured, the assistant cannot reason about its own integration coverage, and the regulatory and patient-trust postures are both broken. Investments here pay back across every subsequent conversation.

---

**Step 2: Ingest cross-organizational data with provenance discipline.** The ingestion layer is the architectural floor for the coordination assistant. Every data point ingested is recorded with its source, its timestamp, its ingestion path, and its integrity hash. The ingestion pipeline is composed of per-source adapters; each adapter handles authentication, rate limiting, format translation, sensitive-record classification, and provenance recording.

```
ON ingest_event(source_type, raw_message, ingestion_metadata):
    // Step 2A: route to the appropriate per-source adapter.
    adapter = select_adapter(source_type)
        // values: "hl7_v2_adt", "hl7_v2_oru",
        // "fhir_subscription", "fhir_polling",
        // "claims_batch", "pharmacy_ncpdp",
        // "pharmacy_vendor_api", "home_health_vendor_api",
        // "hie_query", "tefca_query", "patient_reported"

    // Step 2B: validate and parse.
    parsed = adapter.parse(raw_message)
    validation = adapter.validate(parsed)
    IF NOT validation.valid:
        log_failed_ingestion(parsed, validation.errors)
        return {action: "rejected", reason: validation.errors}

    // Step 2C: classify sensitive-record categories.
    // Some categories trigger separate handling per
    // state and federal rules; this is operational, not
    // optional.
    sensitivity = classify_sensitivity(parsed)
        // categories: "general", "mental_health",
        // "substance_use_42_cfr_part_2", "hiv",
        // "genetic", "adolescent_confidential"

    // Step 2D: enforce per-source consent posture.
    // If the patient has not consented to ingestion from
    // this source, or has revoked consent, the data is
    // dropped and the revocation is honored.
    consent_check = verify_consent({
        patient_id: parsed.patient_id,
        source_type: source_type,
        sensitivity_category: sensitivity.category
    })
    IF NOT consent_check.allowed:
        log_consent_denied_ingestion(parsed, consent_check)
        return {action: "consent_denied"}

    // Step 2E: write to the provenance journal.
    // Provenance records are append-only and separately
    // keyed for blast-radius containment.
    provenance_id = write_provenance({
        patient_id: parsed.patient_id,
        source_type: source_type,
        source_message_id: ingestion_metadata.message_id,
        source_timestamp: parsed.source_timestamp,
        ingestion_timestamp: now(),
        ingestion_path: ingestion_metadata.path,
        integrity_hash: hash_message(raw_message),
        sensitivity_category: sensitivity.category,
        adapter_version: adapter.version
    })

    // Step 2F: normalize to the coordination-state schema.
    // For FHIR-native sources, the data lands in HealthLake
    // and the assistant's coordination-state-store has
    // pointers. For HL7 and other non-FHIR sources, the
    // data is mapped to FHIR-aligned shapes for consistency.
    normalized = adapter.normalize(parsed)

    // Step 2G: reconcile against existing coordination state.
    // Reconciliation may detect duplicates, conflicts, or
    // updates to existing entries.
    reconciliation = reconcile_with_state({
        patient_id: parsed.patient_id,
        normalized_event: normalized,
        provenance_id: provenance_id
    })

    // Step 2H: update the coordination-state-store with
    // provenance references preserved.
    update_coordination_state({
        patient_id: parsed.patient_id,
        update_type: reconciliation.update_type,
            // values: "new_entry", "update_existing",
            // "conflict_detected", "duplicate_dropped"
        normalized_event: normalized,
        provenance_id: provenance_id,
        reconciliation_details: reconciliation
    })

    // Step 2I: emit care-event triggers for downstream
    // protocol and seam-detection processing.
    triggers = derive_triggers(normalized, reconciliation)
    FOR each trigger IN triggers:
        emit_event(trigger.type, trigger.payload)
            // common triggers: "encounter_ingested",
            // "referral_ordered", "discharge_event",
            // "lab_result_posted", "medication_filled",
            // "appointment_scheduled", "appointment_missed"

    return {
        action: "ingested",
        provenance_id: provenance_id,
        triggers_emitted: triggers.length
    }
```

What can go wrong if you skip or shortcut this: the assistant has no provenance for its assertions, the consent posture is unenforceable per data source, the sensitive-record categories are mishandled, the reconciliation is ad-hoc, and the seam-detection layer has no signal to operate on. The ingestion layer is multi-quarter engineering work for any institution that takes the assistant seriously.

---

**Step 3: Run the seam-detection rule engine and the protocol-trigger evaluator.** Seam detection is the assistant's distinctive value layer. The rules and the protocols are institutional content with named clinical-leadership ownership; the engine runs them deterministically (or with calibrated heuristic models) and routes detected gaps to the appropriate human or to the patient-and-caregiver engagement scheduler.

```
ON care_event_or_periodic_tick(patient_id, event):
    // Step 3A: load the patient's coordination state and
    // the relevant protocol context.
    state = load_coordination_state(patient_id)
    context = load_protocol_context({
        patient_id: patient_id,
        active_care_events: state.active_care_events
    })

    // Step 3B: run the seam-detection rule set.
    // Each rule is owned by a named clinical leader; rules
    // have effective dates and version histories.
    seam_findings = []
    FOR each rule IN ENABLED_SEAM_RULES:
        IF rule.applies_to(state, event):
            finding = rule.evaluate({
                state: state,
                event: event,
                context: context
            })
            IF finding.detected:
                seam_findings.append({
                    rule_id: rule.id,
                    rule_version: rule.version,
                    rule_owner: rule.owner,
                    finding: finding,
                    confidence: finding.confidence,
                    suggested_resolver:
                        finding.suggested_resolver
                        // values: "patient", "caregiver",
                        // "care_team", "clinician",
                        // "patient_and_care_team"
                })

    // Step 3C: persist seam-flags to the seam-flag-store.
    FOR each finding IN seam_findings:
        seam_flag_id = persist_seam_flag(patient_id, finding)
        emit_event("seam_flag_raised", {
            patient_id: patient_id,
            seam_flag_id: seam_flag_id,
            rule_id: finding.rule_id,
            suggested_resolver: finding.suggested_resolver
        })

    // Step 3D: evaluate protocol triggers.
    // Triggers come from the protocol library, not from LLM
    // judgment. Examples: post-discharge welcome-home
    // conversation within 48 hours; referral-tracking
    // check-in 1 week after order if not scheduled; lab-
    // result acknowledgement after clinician sign-off;
    // medication-fill check after new prescription.
    protocol_triggers = []
    FOR each protocol IN ACTIVE_PROTOCOLS_FOR_PATIENT(state):
        triggered = protocol.evaluate_triggers({
            state: state,
            event: event,
            now: now()
        })
        protocol_triggers.extend(triggered)

    // Step 3E: schedule patient-and-caregiver engagements
    // for resolvable items.
    FOR each trigger IN protocol_triggers:
        IF trigger.action_type == "engage_patient_or_caregiver":
            schedule_engagement({
                patient_id: patient_id,
                trigger: trigger,
                target_role:
                    determine_target_role(trigger, state),
                channel:
                    select_channel(state.preferences, trigger),
                quiet_hours_check:
                    state.preferences.quiet_hours,
                window: trigger.window
            })

    // Step 3F: route care-team-resolvable items to alerts.
    FOR each finding IN seam_findings:
        IF finding.suggested_resolver IN [
            "care_team", "clinician", "patient_and_care_team"]:
            create_care_team_alert({
                patient_id: patient_id,
                finding: finding,
                priority:
                    derive_priority(finding, state),
                routing:
                    determine_routing(finding, state)
            })

    // Step 3G: handle high-acuity events.
    // Some seam findings or protocol triggers are
    // immediately escalation-worthy (e.g., post-discharge
    // symptoms suggestive of decompensation reported by
    // the patient or caregiver; conflicting orders for
    // a high-risk medication class; missed critical
    // medication for an active condition).
    FOR each finding IN seam_findings:
        IF finding.priority == "high_acuity":
            escalate_immediately({
                patient_id: patient_id,
                finding: finding,
                pathway: finding.escalation_pathway
                    // values: "care_management_immediate",
                    // "clinical_callback_within_2_hours",
                    // "triage_pathway", "911_routed"
            })

    return {
        seam_findings: seam_findings.length,
        protocol_triggers: protocol_triggers.length,
        engagements_scheduled: count_scheduled,
        alerts_created: count_alerts,
        escalations: count_escalations
    }
```

What can go wrong if you skip or shortcut this: the assistant cannot detect the gaps that are its distinctive value, the protocol-driven engagement cadence is missing, the care-team feedback loop is broken, and the assistant degrades to a glorified FAQ bot over coordination data. The seam-detection-rule library and the protocol library together are the largest non-LLM engineering investment in the system.



---

**Step 4: Initiate the conversation surface with input safety, identity, and coordination context.** A conversation can be patient-initiated, caregiver-initiated, or assistant-initiated (from a care-event trigger or a protocol-driven engagement). Whichever the entry point, the conversation handler runs the same input-safety pipeline as the previous chapter 11 bots, plus the continuous emergency-screening pass that every patient-or-caregiver utterance receives, plus identity-verification with the speaker-role distinction (patient vs. caregiver), plus the coordination-state context loading.

```
ON conversation_turn(session_id, utterance, channel,
                     auth_context, speaker_role):
    // Step 4A: input safety with continuous emergency screen.
    // Same primitives as recipes 11.1-11.8, with one
    // coordination-specific addition: the continuous
    // emergency screen runs on every utterance regardless
    // of conversation context.
    safety = run_input_safety({
        utterance: utterance,
        channel: channel,
        speaker_role: speaker_role,
        prompt_injection_check: true,
        phi_minimization_check: true,
        crisis_classifier: true,
        coordination_acuity_classifier: true
            // detects post-discharge symptoms suggestive of
            // decompensation, missed critical medications,
            // reported caregiver crisis, etc.
    })

    IF safety.crisis_flag:
        return route_to_crisis_pathway({
            session_id: session_id,
            utterance: utterance,
            crisis_type: safety.crisis_type
                // values: "self_harm_or_suicide" -> 988 + recipe 11.8;
                // "acute_medical" -> 911 + recipe 11.6;
                // "intimate_partner_violence" -> NDV hotline +
                //   institutional pathway;
                // "elder_abuse" -> APS + institutional pathway;
                // "child_abuse" -> mandatory-reporter pathway
        })

    IF safety.coordination_acuity_flag:
        return route_to_acuity_pathway({
            session_id: session_id,
            utterance: utterance,
            acuity_type: safety.acuity_type
        })

    IF NOT safety.passes:
        return safe_template_response(safety.failure_reason)

    // Step 4B: identity-and-role verification.
    // The session conveys the verified identity (patient or
    // caregiver). Caregiver identity carries proxy-access
    // scope.
    identity = verify_identity_and_role(auth_context)
    IF NOT identity.verified:
        return identity_required_response()

    // Step 4C: coordination-context loading scoped by
    // speaker role.
    coordination_context = load_coordination_context({
        patient_id: identity.patient_id,
        speaker_role: identity.role,
            // values: "patient", "caregiver",
            // "caregiver_with_full_proxy",
            // "caregiver_with_scheduling_only_proxy",
            // etc.
        proxy_access_scope: identity.proxy_scope,
        sensitive_record_carve_outs:
            identity.sensitive_carve_outs,
        recent_window_days: 90
            // longitudinal context window; older context is
            // reachable on demand via tools but not pre-loaded
    })

    // Step 4D: assemble the prompt context.
    prompt_context = {
        system_prompt: SYSTEM_PROMPT_VERSION_X,
            // versioned, signed-off by clinical leadership;
            // includes the assistant's role, scope discipline,
            // speaker-role-aware behavior, citation discipline,
            // not-a-clinician disclosure, and protocol
            // citation expectations
        coordination_context: coordination_context,
        recent_conversation_history:
            load_recent_history(session_id, max_turns=20),
        long_term_summary:
            load_long_term_summary(identity.patient_id),
        speaker_role: identity.role,
        utterance: utterance
    }

    // Step 4E: invoke the agent with tool-use.
    // The agent decides which tools to call, in what
    // order, with what arguments. The agent's traces are
    // preserved for the coordination-decision-record
    // journal.
    agent_response = invoke_agent({
        prompt_context: prompt_context,
        tools: COORDINATION_TOOL_SURFACE,
        guardrails_config: GUARDRAILS_VERSION_X,
        knowledge_bases: [
            "coordination_protocols",
            "patient_education",
            "conversation_history"
        ],
        trace: true
    })

    return agent_response
```

What can go wrong if you skip or shortcut this: the assistant treats every conversation as a fresh start, the speaker role is conflated, the proxy-access scope is not enforced, the continuous emergency screen is missed, and the conversation handler degrades to a stateless FAQ bot.

---

**Step 5: Run the agent's tool-use loop with citation discipline.** The agent's job is to take the user's utterance, decide what coordination tools to call, retrieve the necessary state and protocols, and compose a grounded response. Each tool call is recorded in the tool-call ledger; each retrieved citation is preserved in the response trace. The LLM does not fabricate coordination-state assertions; if a tool call returns "unknown" or "not in coordination state," the assistant says so honestly.

```
ON agent_invocation(prompt_context, tools, guardrails, kbs):
    // Step 5A: model produces an initial plan and tool-call
    // sequence. The LLM is instructed to call tools to
    // retrieve coordination state before making any
    // assertion about that state, and to retrieve protocol
    // content before delivering any coordination
    // instruction.
    plan = model.generate_plan({
        system: prompt_context.system_prompt,
        context: prompt_context,
        tools_available: tools.schemas
    })

    tool_results = []
    citations_collected = []

    // Step 5B: execute the tool-call sequence with audit.
    FOR each tool_call IN plan.tool_calls:
        // Validate the tool call is permitted in scope.
        IF NOT scope_validator.permits(tool_call,
                                       prompt_context):
            tool_results.append({
                tool_call: tool_call,
                result: {error: "out_of_scope_tool_call"}
            })
            continue

        // Validate the tool's patient_id argument matches
        // the verified session. Defense-in-depth against
        // prompt-injection attempts to reach other patients'
        // data.
        IF tool_call.args.patient_id !=
                prompt_context.coordination_context.patient_id:
            log_security_event(
                "patient_id_mismatch_tool_call",
                tool_call)
            tool_results.append({
                tool_call: tool_call,
                result: {error: "patient_id_mismatch"}
            })
            continue

        // Validate the tool's access scope honors the
        // speaker-role proxy posture.
        IF NOT proxy_scope_validator.permits(
                tool_call,
                prompt_context.speaker_role,
                prompt_context.coordination_context):
            tool_results.append({
                tool_call: tool_call,
                result: {error: "proxy_scope_denied"}
            })
            continue

        result = execute_tool(tool_call)

        // Persist the tool call in the ledger with audit.
        persist_tool_call_ledger({
            session_id:
                prompt_context.session_id,
            tool: tool_call.name,
            args: tool_call.args,
            result_summary: summarize(result),
            timestamp: now(),
            speaker_role: prompt_context.speaker_role,
            tool_version: tool_call.tool_version
        })

        // Collect citations for grounded assertions.
        IF result.citations:
            citations_collected.extend(result.citations)

        tool_results.append({
            tool_call: tool_call,
            result: result
        })

    // Step 5C: model composes the response grounded in
    // tool results and citations.
    composed_response = model.compose_response({
        prompt_context: prompt_context,
        tool_results: tool_results,
        citations: citations_collected,
        instruction:
            "Compose a response that answers the user's "
            "question or performs the requested coordination "
            "task. Ground every coordination-state assertion "
            "in cited provenance. Ground every protocol "
            "instruction in cited protocol. Where a fact is "
            "not in the coordination state or in cited "
            "protocol, say so honestly. Do not produce "
            "diagnostic or prescriptive recommendations "
            "beyond what the patient's existing clinicians "
            "have ordered. Defer to the care team for any "
            "clinical-judgment question."
    })

    return {
        response: composed_response,
        tool_calls: tool_results,
        citations: citations_collected,
        plan: plan
    }
```

What can go wrong if you skip or shortcut this: the tool-call audit trail is incomplete, the patient_id-cross-check defense-in-depth is missing, the proxy-scope discipline is bypassable, and the citation discipline is unenforced. The agent's reasoning is hard to audit when something goes wrong.

---

**Step 6: Run output safety with protocol-faithfulness verification.** Output safety has the standard primitives from recipe 11.1 (scope filter, vendor-managed guardrail layer, persona-and-tone check). The coordination-specific addition is a faithfulness verifier that confirms the response's coordination-state assertions cite preserved provenance and the response's protocol instructions cite preserved protocol content. A response that asserts coordination facts without citation, or delivers protocol instructions without citation, is regenerated with a stricter constraint or replaced with a safe-fallback template.

```
ON output_safety(composed_response, tool_results, citations,
                 prompt_context):
    // Step 6A: standard output-safety primitives.
    scope_check = scope_filter.evaluate(composed_response)
    IF scope_check.violation:
        return regenerate_with_stricter_scope({
            response: composed_response,
            violation: scope_check.violation
        })

    guardrail_check =
        bedrock_guardrails.evaluate(composed_response)
    IF guardrail_check.blocked:
        return safe_fallback_template(guardrail_check.reason)

    persona_check = persona_and_tone.evaluate(composed_response)
    IF persona_check.violation:
        return regenerate_with_persona_constraint(
            composed_response, persona_check.violation)

    // Step 6B: faithfulness verification (coordination-
    // specific). Validates that every coordination-state
    // assertion in the response is grounded in the
    // tool_results, that every protocol instruction is
    // grounded in cited protocol, and that the citation
    // chain back to provenance is intact.
    faithfulness = verify_faithfulness({
        response: composed_response,
        tool_results: tool_results,
        citations: citations,
        verifier_model: VERIFIER_MODEL_VERSION_X
            // independent verifier model, distinct from the
            // orchestration model, with structured-output
            // schema validation
    })

    IF faithfulness.coordination_state_assertion_unverified:
        // Response asserts something about the patient's
        // coordination state that is not in the retrieved
        // tool results. Regenerate with stricter
        // grounding constraint.
        return regenerate_with_grounding_constraint({
            response: composed_response,
            issue: "coordination_state_assertion_unverified",
            unverified_claims:
                faithfulness.unverified_claims
        })

    IF faithfulness.protocol_instruction_uncited:
        return regenerate_with_grounding_constraint({
            response: composed_response,
            issue: "protocol_instruction_uncited"
        })

    IF faithfulness.provenance_chain_broken:
        return safe_fallback_template(
            "provenance_chain_broken")

    // Step 6C: speaker-role-appropriate disclosure check.
    // A caregiver speaking on behalf of the patient may
    // have restricted access to certain categories per the
    // patient's preference; the response must honor those
    // carve-outs.
    role_check = speaker_role_disclosure_check({
        response: composed_response,
        speaker_role: prompt_context.speaker_role,
        sensitive_carve_outs:
            prompt_context.coordination_context
                .sensitive_record_carve_outs
    })
    IF role_check.violation:
        return regenerate_with_carve_out_constraint(
            composed_response, role_check.violation)

    // Step 6D: conservative-bias check. Where the response
    // could plausibly involve clinical judgment beyond the
    // coordination scope, did the response defer to the
    // care team?
    conservative_check = conservative_bias_check({
        response: composed_response,
        prompt_context: prompt_context
    })
    IF conservative_check.violation:
        return regenerate_with_deference_constraint(
            composed_response,
            conservative_check.violation)

    // Step 6E: persist the coordination-decision-record.
    persist_coordination_decision_record({
        session_id: prompt_context.session_id,
        patient_id:
            prompt_context.coordination_context.patient_id,
        speaker_role: prompt_context.speaker_role,
        utterance: prompt_context.utterance,
        composed_response: composed_response,
        tool_calls: tool_results,
        citations: citations,
        faithfulness_score: faithfulness.score,
        scope_check: scope_check,
        guardrail_check: guardrail_check,
        persona_check: persona_check,
        role_check: role_check,
        conservative_check: conservative_check,
        timestamp: now(),
        model_version: ACTIVE_MODEL_VERSION,
        prompt_version: ACTIVE_PROMPT_VERSION,
        protocol_corpus_version:
            ACTIVE_PROTOCOL_CORPUS_VERSION,
        coordination_state_version:
            ACTIVE_COORDINATION_STATE_VERSION
    })

    return composed_response
```

What can go wrong if you skip or shortcut this: the assistant produces coordination assertions without provenance, delivers protocol instructions without citation, ignores speaker-role carve-outs, drifts out of conservative-bias scope, and the coordination-decision-record journal lacks the structured trace needed for retrospective review.

---

**Step 7: Orchestrate transitions of care with Step Functions.** When a discharge event arrives (the institution's hospital sends an HL7 ADT-A03 discharge message; or the receiving home-health agency confirms admission to home health; or the SNF confirms admission), the assistant initiates the appropriate transition-of-care workflow. The workflow is a Step Functions state machine, version-controlled, signed off by clinical leadership, with deterministic state transitions and explicit completion criteria. The LLM operates on top of the state machine as the conversational interface; the state machine drives the protocol.

```
ON discharge_event(patient_id, discharge_event):
    // Step 7A: identify the appropriate transition protocol
    // based on the discharge destination and the admission
    // type.
    transition_protocol =
        select_transition_protocol({
            patient_id: patient_id,
            admission_type: discharge_event.admission_type,
            discharge_destination:
                discharge_event.destination,
                // values: "home", "home_with_home_health",
                // "snf", "ltac", "rehab",
                // "hospice", "other"
            patient_population:
                derive_population(patient_id),
                // affects protocol calibration; e.g.,
                // post-CABG vs post-CAP vs post-stroke
            insurance_population:
                derive_insurance_population(patient_id)
                // affects benefits-related steps
        })

    // Step 7B: instantiate the transition workflow.
    workflow_execution = step_functions.start_execution({
        state_machine: TRANSITION_OF_CARE_STATE_MACHINE,
        input: {
            patient_id: patient_id,
            discharge_event: discharge_event,
            transition_protocol: transition_protocol,
            instantiated_at: now()
        }
    })

    // The state machine encodes the protocol-defined steps:
    //
    // Step 7B-1: Welcome-home check-in within 48 hours
    //   (step calls Pinpoint to send the message;
    //    schedules a follow-up if no response within
    //    24 hours; escalates if no response within 48
    //    hours)
    //
    // Step 7B-2: Medication reconciliation between the
    //   discharge medication list and the pre-admit list
    //   (step calls medication_list_reconcile; if a
    //    discrepancy is detected, surfaces to seam-flag
    //    queue for clinical review)
    //
    // Step 7B-3: Follow-up appointment validation within
    //   the protocol window (step calls referral_lifecycle
    //   tooling; if the appointment is not scheduled within
    //    the discharge protocol's window, surfaces to
    //    engagement scheduler for patient outreach plus
    //    care-team alert)
    //
    // Step 7B-4: Home-health or DME order validation
    //   (step verifies that the receiving agency has
    //    received and accepted the order)
    //
    // Step 7B-5: Patient and caregiver education delivery
    //   (step calls patient_education content retrieval
    //    grounded in the discharge-instructions and the
    //    institution's reviewed library)
    //
    // Step 7B-6: Red-flag warning instructions
    //   (step delivers the clinically-reviewed warning
    //    instructions for the specific admission type and
    //    discharge destination)
    //
    // Step 7B-7: Symptom-monitoring engagement
    //   (step schedules check-ins per the discharge
    //    protocol's cadence, with escalation thresholds)
    //
    // Step 7B-8: Closure verification
    //   (step verifies all protocol items are satisfied;
    //    if any are open past their windows, escalates to
    //    care-management for resolution; closes the
    //    transition workflow with the closure summary
    //    delivered to the care team)

    return {
        workflow_execution_id:
            workflow_execution.execution_id,
        transition_protocol_version:
            transition_protocol.version,
        expected_completion_window:
            transition_protocol.completion_window
    }
```

What can go wrong if you skip or shortcut this: the discharge-to-home gap (the 48-hour-to-72-hour window where most preventable readmissions originate) is unmanaged, medication reconciliation is left to chance, follow-up appointments are not validated against the protocol window, red-flag warnings are not delivered, and the transition closure is silent. Transitions of care are the single most consequential coordination event class for this assistant, and they are best run through a deterministic state-machine orchestration rather than left to LLM judgment.

---

**Step 8: Track referral lifecycles to closure.** Referrals are first-class coordination objects with a structured lifecycle (ordered, communicated, scheduled, attended, consult-note-received, closed). Each transition has specified time windows. The referral-lifecycle subsystem is a state machine; the LLM operates on top of it.

```
ON referral_event(patient_id, referral_event):
    // Step 8A: classify the event type.
    event_type = classify_referral_event(referral_event)
        // values: "ordered", "communicated_to_patient",
        // "scheduled", "rescheduled", "attended",
        // "no_showed", "cancelled",
        // "consult_note_received", "closed"

    // Step 8B: load the referral's current state.
    referral_state =
        load_referral_state(referral_event.referral_id)

    // Step 8C: validate the state transition.
    transition = referral_state_machine.validate({
        current_state: referral_state.state,
        event: event_type
    })

    IF NOT transition.valid:
        log_invalid_referral_transition(
            referral_event, referral_state, transition)
        return {action: "rejected"}

    // Step 8D: persist the new state with provenance.
    new_state = referral_state_machine.transition({
        current: referral_state,
        event_type: event_type,
        event_payload: referral_event
    })
    persist_referral_state({
        referral_id: referral_event.referral_id,
        new_state: new_state,
        transition_at: now(),
        provenance_id: referral_event.provenance_id
    })

    // Step 8E: emit downstream events.
    emit_event("referral_state_changed", {
        patient_id: patient_id,
        referral_id: referral_event.referral_id,
        previous_state: referral_state.state,
        new_state: new_state.state
    })

    // Step 8F: schedule the next protocol-driven action.
    next_action = referral_protocol.next_action(
        new_state, referral_event)

    IF next_action.type == "engage_patient":
        // E.g., 1 week after order if not yet scheduled,
        // walk the patient through the scheduling step,
        // including known barriers (specialty wait time,
        // insurance acceptance).
        schedule_engagement({
            patient_id: patient_id,
            trigger: next_action,
            channel:
                load_preferences(patient_id).preferred_channel,
            window: next_action.window
        })

    IF next_action.type == "alert_care_team":
        // E.g., referral has aged out of its protocol
        // window; surface for care-management resolution.
        create_care_team_alert({
            patient_id: patient_id,
            alert_type:
                "referral_aged_past_protocol_window",
            referral_id: referral_event.referral_id,
            priority:
                derive_priority_from_referral_urgency(
                    new_state)
        })

    IF next_action.type == "close_referral":
        // Consult note received and ordering clinician has
        // acknowledged; close the referral.
        close_referral(referral_event.referral_id)
        emit_event("referral_closed", {
            patient_id: patient_id,
            referral_id: referral_event.referral_id
        })

    return {
        action: "transitioned",
        new_state: new_state.state,
        next_action: next_action
    }
```

What can go wrong if you skip or shortcut this: referrals stay open indefinitely without resolution, the patient does not get the specialty consult that was ordered, the ordering clinician does not get the consult note feedback that was needed, the referral-closure rate (a leading indicator of coordination quality) collapses, and the most easily-measured coordination outcome is silently degrading.

---

**Step 9: Handle medication-reconciliation seams across pharmacies and clinicians.** Medication reconciliation is one of the most consequential and most data-quality-sensitive coordination tasks. The assistant maintains the patient's medication list as a single source of truth synthesized from all known pharmacy fills, all known clinician orders, and all patient-reported medications. The reconciliation logic is robust to the data-quality issues common in pharmacy and clinician feeds (inconsistent medication-naming, inconsistent dose representation, inconsistent dosing-instruction parsing, incomplete coverage). When a discrepancy is detected, the assistant flags it for human reconciliation rather than attempting clinical judgment.

```
ON medication_event(patient_id, medication_event):
    // Step 9A: classify the source.
    source_type = medication_event.source_type
        // values: "pharmacy_fill", "clinician_order",
        // "patient_reported", "discharge_med_list",
        // "hl7_rde", "fhir_medicationrequest",
        // "fhir_medicationstatement"

    // Step 9B: normalize the medication entry.
    // The normalization layer canonicalizes drug name
    // (RxNorm), dose representation (UCUM), and dosing
    // instructions where possible.
    normalized = normalize_medication({
        raw_event: medication_event,
        rxnorm_lookup: true,
        ucum_normalization: true,
        sig_parser: true
            // best-effort parser for free-text dosing
            // instructions; falls back to preserved
            // free-text when parsing is uncertain
    })

    // Step 9C: load the patient's current synthesized
    // medication list.
    current_med_list =
        load_synthesized_medication_list(patient_id)

    // Step 9D: reconcile.
    reconciliation = reconcile_medication({
        normalized_event: normalized,
        current_med_list: current_med_list,
        rules: MEDICATION_RECONCILIATION_RULES
            // institutional rules signed off by pharmacy
            // informatics; e.g., "if a clinician orders a
            // medication that was previously discontinued
            // by another clinician, surface for clinical
            // review"; "if two clinicians order
            // interacting medications without recorded
            // coordination, surface for clinical review";
            // "if a pharmacy fills a medication the patient
            // says they were told to stop, surface for
            // clinical review"; "if the discharge med list
            // does not reconcile with the pre-admit list
            // plus expected changes, surface for clinical
            // review"
    })

    // Step 9E: update the synthesized medication list with
    // provenance preserved.
    update_synthesized_medication_list({
        patient_id: patient_id,
        update: reconciliation.update,
        provenance_id: medication_event.provenance_id
    })

    // Step 9F: surface seams.
    FOR each seam IN reconciliation.seams:
        seam_flag_id = persist_seam_flag({
            patient_id: patient_id,
            rule_id: seam.rule_id,
            description: seam.description,
            suggested_resolver: seam.suggested_resolver,
            priority: seam.priority,
            confidence: seam.confidence
        })
        emit_event("seam_flag_raised", {
            patient_id: patient_id,
            seam_flag_id: seam_flag_id
        })

    return {
        action: "reconciled",
        seams_raised: reconciliation.seams.length,
        synthesized_list_version:
            current_med_list.version + 1
    }
```

What can go wrong if you skip or shortcut this: the patient's medication list across systems remains contradictory, the assistant's medication assertions are not trustworthy, the seam-detection layer does not catch the discrepancies that lead to medication-related adverse events, and the assistant degrades into a tool that surfaces medication confusion rather than resolving it. The pharmacy-informatics partnership is the operational owner here; the assistant is the surfacing layer, not the reconciler.

---

**Step 10: Generate care-team reporting and outcome correlation.** The care team has visibility into the assistant's activity through structured summaries (real-time alerts for high-priority gaps; weekly digests; monthly summaries; transition-of-care closure reports; quarterly clinical-review packets). The reporting is designed for the care team's workflow and is reviewed by clinical leadership before launch. Outcome-correlation runs against coordination-specific outcomes (referral closure rate, transition-of-care completion rate, medication-reconciliation accuracy, avoidable-readmission rate, avoidable-ED-utilization rate, patient-and-caregiver-reported coordination experience) on multi-quarter windows.

```
ON reporting_tick(reporting_window):
    // Step 10A: real-time alerts (already streamed during
    // operations). This step produces the periodic-summary
    // artifacts.

    // Step 10B: weekly digest per active member.
    FOR each patient IN ACTIVE_PATIENT_COHORT:
        digest = compose_weekly_digest({
            patient_id: patient.id,
            window: last_7_days,
            sections: [
                "open_referrals_status",
                "transition_of_care_status",
                "seam_flag_status",
                "medication_reconciliation_findings",
                "key_disclosures_caregiver_burden_etc",
                "patient_and_caregiver_reported_experience",
                "open_followups",
                "recommended_care_team_actions"
            ]
        })
        deliver_to_care_team({
            patient_id: patient.id,
            digest: digest,
            delivery_channel:
                care_team_workflow.delivery_channel
        })

    // Step 10C: monthly summary with longitudinal trends.
    FOR each patient IN ACTIVE_PATIENT_COHORT:
        summary = compose_monthly_summary({
            patient_id: patient.id,
            window: last_30_days,
            sections: [
                "longitudinal_trends",
                "open_issues",
                "recommendation_for_care_team_action",
                "care_management_promotion_candidate"
                    // patients whose coordination needs
                    // have grown beyond what the assistant
                    // alone can address; promote to nurse
                    // case management or other higher-touch
                    // service
            ]
        })
        deliver_to_care_team({
            patient_id: patient.id,
            summary: summary,
            delivery_channel:
                care_team_workflow.delivery_channel
        })

    // Step 10D: transition-of-care closure reports.
    FOR each completed_transition IN
            transitions_completed_in_window:
        report = compose_transition_closure_report({
            transition_id: completed_transition.id,
            closure_summary:
                completed_transition.closure_summary,
            protocol_compliance:
                completed_transition.protocol_compliance,
            seam_flags_raised_during:
                completed_transition.seams,
            patient_and_caregiver_experience:
                completed_transition.experience_summary
        })
        deliver_to_care_team(report)

    // Step 10E: quarterly clinical-review packets.
    // Clinical leadership reviews assistant performance:
    // sampled conversations, sampled seam-flag resolutions,
    // outcome trends, per-cohort metrics, equity
    // disparities, protocol revisions.
    IF reporting_window.is_quarter_end:
        clinical_review_packet =
            compose_clinical_review_packet({
                quarter: reporting_window.quarter,
                sampled_conversations:
                    sample_conversations(
                        reporting_window, sample_size=200),
                sampled_seam_resolutions:
                    sample_seam_resolutions(
                        reporting_window, sample_size=100),
                outcome_metrics:
                    compute_outcome_metrics(
                        reporting_window),
                per_cohort_metrics:
                    compute_per_cohort_metrics(
                        reporting_window),
                equity_disparity_findings:
                    compute_equity_disparities(
                        reporting_window),
                protocol_revision_proposals:
                    aggregate_revision_proposals(
                        reporting_window)
            })
        deliver_to_clinical_leadership(
            clinical_review_packet)

    // Step 10F: outcome-correlation pipeline.
    // Multi-quarter and multi-year correlation against
    // utilization and clinical outcomes. Results are
    // observational, not causal.
    outcome_correlation = compute_outcome_correlation({
        window: reporting_window,
        outcome_metrics: [
            "referral_closure_rate",
            "transition_of_care_completion_rate",
            "medication_reconciliation_accuracy",
            "avoidable_readmission_rate",
            "avoidable_ed_utilization_rate",
            "duplicate_service_rate",
            "patient_and_caregiver_reported_coordination_experience",
            "caregiver_burden_trajectory",
            "total_cost_of_care_for_engaged_cohort"
        ],
        comparison_cohort:
            propensity_matched_unenrolled_cohort()
                // observational; not a randomized trial
    })
    deliver_outcome_summary(outcome_correlation)

    return {
        digests_delivered: count_digests,
        summaries_delivered: count_summaries,
        closure_reports_delivered: count_closure_reports,
        review_packet_delivered:
            reporting_window.is_quarter_end,
        outcome_correlation_window:
            reporting_window
    }
```

What can go wrong if you skip or shortcut this: the care team has no visibility into the assistant's activity, the assistant operates as a parallel system rather than as an extension of the care team, the outcome-correlation evidence is missing when leadership asks for it, the equity-disparity findings are not surfaced, and the protocol-revision feedback loop does not close. Care-team reporting is not a phase-2 enhancement; it is the operating-room visibility that makes the assistant a tool the care team trusts.


---

### Expected Results

**Sample conversation (illustrative, abbreviated, post-discharge welcome-home check-in):**

```
Bot:     Hi Mr. Chen, this is the coordination tool from
         your primary care home, checking in two days
         after your hospital discharge. I'm a chat tool,
         not a person, and I work alongside your care
         team. How are things at home?

Patient: tired but okay. taking the new pills.

Bot:     Glad you made it home. Quick check on the
         medications: I have, from the discharge list,
         metoprolol 50 mg twice a day, lisinopril 10 mg
         once a day, and the new one, furosemide 40 mg
         once a day in the morning. Does that match what
         you have at home?

Patient: yes those are the bottles i have. but my wife
         says the cardiologist's office told her on the
         phone yesterday to go up to 60 mg of furosemide.

Bot:     Thanks for letting me know. That kind of
         change between the discharge plan and what an
         outside clinician told your wife is exactly the
         kind of thing I should flag for your care team
         to confirm. Two things I'm doing right now:

         1. I'm logging this and sending an alert to
            your primary care nurse so she can call the
            cardiologist's office and confirm the dose
            change. You should hear from her later
            today.

         2. Until your nurse confirms, please stay on
            the dose your wife heard from the
            cardiologist (60 mg) only if your wife has
            written down what they told her, and the
            person on the call was someone from
            Dr. Patel's office. If there is any doubt,
            it is safer to stay on the discharge dose
            (40 mg) until the dose is confirmed. I am
            not making the dose decision; the
            clinicians are. I'm only flagging the
            seam.

         Is your wife around to tell me whether she
         wrote down who she spoke with and what they
         said?

Patient: she's here. she says it was the nurse at
         dr. patel's office, kim, and she wrote it on
         the calendar.

Bot:     Good. I'm noting that. Your nurse will follow
         up. While I have you, let me make sure your
         follow-up cardiology appointment is on the
         calendar. The discharge plan called for a
         follow-up within 7-10 days, which would be by
         next Monday. Has that been scheduled?

Patient: nothing on my calendar.

Bot:     Okay, that one is on me to surface to the
         scheduling team. I'll send a request now to
         have someone call you to set it up. Their
         number for any questions is on the after-visit
         summary the hospital sent home with you. While
         you're recovering, three things to watch for
         that mean call your care team or 911 right
         away:

         - Sudden worsening shortness of breath at rest
         - Weight gain of more than 3 pounds in 24
           hours, or 5 pounds in a week
         - Swelling in your legs or feet getting
           noticeably worse

         If any of those happen, call your care team's
         line or 911. The number for the cardiology
         after-hours line is in your discharge papers.

         How are you feeling otherwise? Any of those
         things going on now?

Patient: no none of those. just tired.

Bot:     Tiredness for a few days after a hospital
         stay is normal, especially with the medication
         changes. I'll check back tomorrow afternoon
         once we've heard from the nurse about the
         dose. Take care.

[Behind the scenes: the assistant has raised a seam-flag
 (medication discrepancy between discharge list and
 reported dose change), routed the seam to the primary
 care nurse with the patient's wife's recollection of the
 source, scheduled a follow-up appointment scheduling
 task for the scheduling team, and recorded the
 conversation in the coordination-decision-record journal
 with full citations to the discharge medication list
 (provenance: hospital EHR), the cardiology referral
 (provenance: primary care EHR), the institution's
 post-discharge protocol for the patient's admission type
 (citation: protocol library v3.2), and the heart-failure
 red-flag warnings (citation: patient-education library
 v8.7). The wife's call recollection is recorded as
 patient-and-caregiver-reported and is not yet validated
 against a source.]
```

**Sample care-team alert (illustrative, generated from the conversation above):**

```
ALERT: Medication discrepancy seam, priority MEDIUM
       (clinical-judgment required)

Patient: Chen, [redacted ID]
Date: [timestamp]
Source of seam: post-discharge welcome-home conversation
Conversation ID: [conv ID]

Description:
Patient (with caregiver present) reports that
cardiology nurse Kim at Dr. Patel's office instructed
the patient's wife by phone yesterday to titrate
furosemide from 40 mg to 60 mg once daily. This
contradicts the discharge medication list (40 mg once
daily, hospital EHR provenance, signed off by
discharging hospitalist Dr. Garcia 2 days ago).

The conversation has been documented; the patient was
told to remain on the discharge dose until the dose is
confirmed, with the alternative path of staying on the
60 mg dose if the wife is confident in the source. The
assistant did not make the dose decision.

Suggested action:
1. Call Dr. Patel's office to confirm the dose change
2. If confirmed, update the discharge medication list
   in the patient's chart and emit a patient-facing
   confirmation
3. If unconfirmed, instruct the patient on the correct
   dose

Provenance chain attached:
- Discharge medication list (hospital EHR, message ID
  ABC-123, ingested 2 days ago)
- Patient and caregiver report (conversation ID
  XYZ-789, captured today)

Care-team owner: assigned to primary care nurse C.
Lopez (queue: PCMH-coordination-medium)
SLA: 4 business hours
```

**Performance benchmarks (illustrative, your mileage varies):**

| Metric | Pre-bot baseline (existing care alone) | Post-bot (engaged members) |
|--------|---------------------------------------|----------------------------|
| Referral closure rate (within protocol window) | 30-55% (varies by specialty and program) | 60-85% (after multi-quarter ramp) |
| Transition-of-care completion rate (per institutional protocol) | 40-65% | 70-90% |
| Medication-reconciliation discrepancy detection rate | Variable, often low | Substantially higher (the assistant's distinctive value) |
| 30-day readmission rate for engaged transitions | Baseline | 5-25% relative reduction (where outcomes mature) |
| Avoidable ED utilization rate | Baseline | 5-20% relative reduction (where outcomes mature) |
| Duplicate-service rate | Variable | Modest reduction in detected duplicates |
| Caregiver-burden trajectory (Zarit Burden Interview or similar) | Variable | Modest improvement in engaged caregivers |
| Patient-and-caregiver-reported coordination experience | Variable | Generally positive, varies by program design |
| Engagement attrition by 6 months | N/A | 25-50% (operational risk, similar to other longitudinal bots) |
| Citation-coverage rate | N/A | 95%+ as launch-gate target |
| Seam-detection precision (sampled review) | N/A | 80-95% target across rules |
| Seam-detection recall (sampled review) | N/A | 70-90% target across rules |
| Per-active-member infrastructure cost | N/A | $4-12 per member per month |
| Per-active-member total cost (including care-management workforce) | N/A | $30-100 per member per month |
| Per-cohort outcome disparity | Often invisible | Monitored explicitly |

<!-- TODO: replace illustrative figures with measured results from the deployment. The ranges above are typical for hybrid AI-plus-human coordination programs but vary substantially with program design, target population, integration coverage, and engagement intensity. Published evidence for hybrid coordination programs includes peer-reviewed studies of programs from major payers, integrated delivery networks, post-discharge transition programs, and care-coordination platforms, with effect sizes varying. -->

**Where it struggles:**

- **Integration coverage gaps.** The assistant operates only as well as its ingestion. Patients whose primary care, hospital, pharmacy, and home-health are all integrated have a different experience than patients with partial coverage. Mitigation: explicit per-source coverage tracking, per-patient confidence calibration, transparent disclosure to the patient and caregiver about what the assistant does and does not know.
- **Provenance gaps.** When the assistant cannot trace an assertion back to a specific source, the assertion is suspect. Mitigation: provenance-as-architectural-primitive; faithfulness verification; safe-fallback templates when provenance is missing.
- **Seam-detection-rule-engine maturity.** The first rules deployed catch the most common, well-understood seams (medication discrepancies, referral non-scheduling, transition-of-care incompleteness). The harder cases (subtle conflicting orders, complex cross-organizational coordination patterns) require multi-quarter rule-development with clinical-leadership ownership.
- **Care-team adoption and trust.** A coordination assistant the care team does not trust or use is a coordination assistant whose value is invisible. Mitigation: clinical-leadership co-design, care-team-workflow integration, sampled-review with care-team feedback, structured failure-mode labeling.
- **Engagement attrition over months.** Patients and caregivers who initially engage may attrit over time as the immediate post-discharge or post-procedure pressure recedes. Mitigation: relationship-quality engineering, low-pressure check-in cadence, caregiver-burden-aware engagement timing, gentle re-engagement after silence, per-cohort attrition monitoring.
- **Cross-organizational consent friction.** Patients enrolling in coordination across organizations encounter consent friction that is genuinely confusing. Mitigation: plain-language consent UX, multilingual consent forms, cohort-specific guidance, opt-in granularity for sensitive categories.
- **Equity gaps in integration coverage.** Patients in well-resourced practices and well-resourced markets are better instrumented than patients in under-resourced practices and markets, who often have greater coordination needs. Mitigation: per-cohort monitoring as launch-gate; targeted integration investment for under-resourced sites; alternative integration paths (patient-mediated SMART on FHIR; HIE participation; payer-provided claims feeds).
- **Outcome attribution.** Engaged patients are not a random sample, and coordination outcomes have many confounders. Mitigation: matched-cohort or quasi-experimental analysis; recognition that observational correlation is suggestive, not causal; long-time-horizon commitment.
- **Caregiver-burden interventions remain limited.** The assistant can take routine work off the caregiver's plate but cannot address the underlying caregiver-burden drivers (financial constraints, social isolation, the caregiver's own health needs). Mitigation: respite-and-support resource surfacing; integration with care-management for high-burden cases; explicit caregiver-burden tracking with care-management routing.
- **Cross-organizational data quality remains uneven.** Pharmacy data feeds carry inconsistent medication-naming and dose representation. FHIR APIs from different EHRs return different shapes for the same clinical concept. Claims feeds lag clinical events by weeks to months. Mitigation: institutional-pharmacy-informatics partnership; FHIR normalization layer; per-source data-quality tracking; transparent disclosure of data-quality limitations.
- **Sensitive-record handling complexity.** 42 CFR Part 2, state-specific mental-health record protections, state-specific HIV-record protections, genetic-test-result protections, and adolescent confidentiality each have category-specific rules. Mitigation: sensitive-record-classification at ingestion; per-category consent enforcement; legal-counsel review of state-specific rules; institutional policy with named ownership.
- **Information Blocking rule navigation.** The Information Blocking rule requires certain data sharing; state-specific privacy regulations may limit it. Mitigation: legal-counsel-reviewed institutional posture; operational enforcement through the consent layer; documented decision rationale for any apparent tension.
- **Adversarial inputs.** Patients (or bad actors) attempting to extract information about other patients, manipulate seam-flag routing, bypass scope discipline, or test the system. Mitigation: input-safety pipeline with prompt-injection detection; output-safety pipeline; tool-Lambda patient_id-cross-check; per-language adversarial test corpus including coordination-specific injection cases.
- **Liability exposure for missed seams or mishandled escalations.** A coordination assistant that fails to detect a seam (e.g., a critical medication conflict; an overlooked discharge follow-up; a miscommunicated dose change) and a patient is subsequently harmed is a foreseeable liability exposure. Mitigation: rigorous seam-detection-rule sign-off; sampled review by clinical leadership; named clinical-leadership ownership per rule; FDA-strategy artifact maintained where applicable; institutional malpractice carrier involvement.
- **Build-vs-buy positioning.** Several mature commercial coordination platforms offer adjacent capabilities. Mitigation: evaluate build-vs-buy explicitly; most major institutions run a hybrid that combines a thin orchestration layer in-house with vendor-supplied integration substrate.
- **Long-term protocol drift.** Over years, coordination protocols evolve as clinical evidence accumulates and institutional practice changes. Mitigation: protocol-as-code with version control; annual review cycles; clinical-leadership signoff; deprecation policy.


---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. A production deployment needs to close several gaps that are intentionally out of scope for a recipe.

**Cross-organizational ingestion layer is multi-quarter engineering work.** The HL7 listener, FHIR poller, claims-feed processor, pharmacy-API consumer, home-health vendor adapter, and HIE/TEFCA adapter are each non-trivial integrations. Each has authentication, rate-limiting, error-handling, idempotency, format-translation, sensitive-record-classification, and provenance-recording. Most institutions discover the integration layer is the largest single engineering investment in the system and is multi-quarter work for any meaningful coverage profile.

**Coordination-protocol corpus is multi-quarter clinical work.** Transition-of-care protocols by destination setting, referral-tracking protocols by specialty and urgency, post-discharge protocols by admission type, post-procedure protocols by procedure category, medication-reconciliation protocols, condition-specific coordination playbooks, each with effective dates, version histories, named clinical-leadership ownership, and annual review cycles. Most institutions discover their coordination-protocol library is implicit in their care-managers' heads and needs substantial work to be made explicit and operational.

**Seam-detection rule library with named clinical-leadership ownership per rule.** The rules that catch the gaps that human coordinators catch through experience are institutional content. Each rule has named ownership (patient safety officer, pharmacy director, care-management director, post-discharge care coordinator director, etc.), an effective date, a version history, sampled review for precision and recall, and clinical-leadership signoff before deployment. Multi-quarter work to mature.

**Caregiver-as-first-class-participant identity model with state-law compliance.** Caregiver designation, proxy-access scope, sensitive-record carve-outs, state-specific consent requirements, and operationally-enforced access scoping. Some states require specific caregiver-consent forms (notarized HCP/POA documentation, institution-specific proxy-access forms), others have specific rules for adolescents and aging adults. Legal counsel reviews state-specific variations.

**Cross-organizational consent posture with regulatory review.** Per-data-source and per-sharing-relationship consent tracking, with state-specific variations enforced for sensitive categories. Legal counsel familiar with HIPAA, the Information Blocking and Interoperability rules, TEFCA, state-specific medical-record statutes, 42 CFR Part 2, state-specific mental-health-record protections, state-specific HIV and genetic-test-result protections, and adolescent confidentiality reviews the consent posture before launch.

**Provenance journal with separate KMS keying and access controls.** Every entry in the coordination state has a recorded source, timestamp, and provenance chain. The provenance journal is separately keyed (KMS), separately retained, and separately access-controlled for blast-radius containment. Audit-friendly retrieval is part of production scope.

**Coordination-decision-record journal with structured retention.** Every assistant-generated decision (response delivered, seam detected, alert created, transition initiated, escalation routed) is recorded in a durable, separately-governed journal. Retention sized to the longest of HIPAA's six-year minimum, state-specific medical-record retention, and any FDA SaMD post-market obligations. Reviewable by clinical leadership, compliance, regulatory, and legal.

**Step Functions transition-of-care state machines version-controlled and audited.** Each transition workflow is a state machine with clinical-leadership signoff, version control, deterministic state transitions, and explicit completion criteria. The state machine is versioned alongside the protocol corpus; updates are reviewed before promotion.

**Referral-lifecycle state machine with deterministic logic.** Referrals move through specified lifecycle states with specified time windows. The state machine is institutional content with clinical-leadership signoff; the LLM operates on top of it and does not invent transitions.

**Medication-reconciliation rules with pharmacy-informatics partnership.** Medication-naming canonicalization (RxNorm), dose representation (UCUM), dosing-instruction parsing, and discrepancy-detection rules are owned by pharmacy informatics and signed off by pharmacy leadership. Multi-quarter work to mature.

**Per-cohort monitoring with launch-gate discipline.** Coordination metrics, engagement metrics, outcome metrics, and patient-and-caregiver experience vary by language, channel, condition mix, age cohort, sex, social-determinant flags, caregiver presence, and integration coverage. Per-cohort dashboards reviewed by clinical leadership, operations, compliance, and patient-experience teams. Single-cohort threshold metrics including referral closure rate, transition completion rate, medication-reconciliation accuracy, seam-detection precision and recall, faithfulness rate, citation-coverage rate, equity-disparity flags. Launch-gate institution-wide-average informational only; each cohort meets threshold.

**Outcome-correlation pipeline as multi-quarter to multi-year post-launch commitment.** Coordination outcomes show up over weeks to years depending on the metric. Multi-window correlation (30-day, 90-day, 6-month, 12-month, 24-month, 36-month) against utilization (readmission rate, ED-utilization rate, total cost of care, duplicate-service rate), clinical (HEDIS gap closure, condition-specific outcome trajectories), and patient-experience (PROM trajectories, coordination-experience scores) outcomes. Pipeline ownership jointly held by clinical leadership, data science, operations, compliance, and the participating payer's quality and analytics teams.

**Care-team workflow integration designed jointly with care-management leadership.** The assistant is not a parallel data stream; it is an extension of the care team. The integration with care management's existing workflow tooling (case management platforms, EHR-based care plans, internal alert queues) is designed jointly with the care-management leadership and is reviewed by them before launch.

**Disaster-recovery topology with per-stage failover policy.** Bedrock LLM outage, Bedrock Knowledge Bases outage, Bedrock Agents outage, Bedrock Guardrails outage with stricter scope enforcement, OpenSearch Serverless outage, DynamoDB outage, S3 outage, HealthLake outage, Step Functions outage, MWAA outage, Pinpoint outage, Connect outage, and per-source ingestion outage. Failover-detection thresholds, failover-back triggers, quarterly testing cadence. Crisis-pathway integrity preserved across all degraded states. Graceful-degradation paths exercised in tabletop drills.

**Multi-language deployment with validated translations.** Per-language asset development including validated coordination-protocol translations, validated patient-education translations, validated regulatory-disclaimer translations, per-language tone and persona calibration, per-language asset versioning, per-language launch-gate. Cultural-context adaptation for major populations served.

**Accessibility conformance.** WCAG 2.1 AA conformance for the chat widget; per-channel accessibility considerations for SMS-friendly rendering for low-literacy patients, voice-channel availability, cognitive-load adaptations, screen-reader compatibility. Accessibility launch-gate criteria.

**Per-event idempotency keys for the EventBridge coordination-event bus.** Suggested keys: `patient_enrolled (patient_id, "enrolled")`; `caregiver_designated (patient_id, caregiver_id, "designated")`; `integration_connected (patient_id, source_id, "connected")`; `encounter_ingested (patient_id, encounter_id, "ingested")`; `referral_ordered (referral_id, "ordered")`; `referral_scheduled (referral_id, "scheduled")`; `referral_completed (referral_id, "completed")`; `transition_initiated (transition_id, "initiated")`; `transition_completed (transition_id, "completed")`; `medication_filled (fill_id, "filled")`; `medication_discontinued (med_id, "discontinued")`; `lab_result_posted (result_id, "posted")`; `seam_flag_raised (seam_id, "raised")`; `seam_flag_resolved (seam_id, "resolved")`; `care_team_alert_generated (alert_id, "generated")`; `escalation_routed (escalation_id, "routed")`; `coordination_decision_recorded (decision_id, "recorded")`. Downstream consumers maintain a deduplication store.

**Tool-surface contract management as architectural primitive.** Per-tool versioned schemas, semantic versioning, deprecation policy, backward-compatibility discipline, change-management process owned jointly by engineering, clinical leadership, and compliance.

**IAM resource-based policy and defense-in-depth Lambda authentication.** Each Lambda's resource-based policy pinned to the production API Gateway stage ARN, the production Bedrock Agents action-group ARN, or the production EventBridge rule ARN. Defense-in-depth event-payload validation. Tool-Lambda patient_id-cross-check audit logging.

**Prompt-injection defense to architectural primitive.** Delimited-input framing, tool-Lambda enforcement that every tool validates patient_id arguments against the verified session, per-language jailbreak-test corpus including coordination-specific injection cases (manipulate seam-flag routing, manipulate referral-lifecycle transitions, manipulate scope discipline to elicit clinical recommendations, manipulate proxy-scope to reach restricted records), Bedrock Guardrails configuration with denied topics specific to coordination scope.

**Cross-region failover for the production stack.** Bedrock, Bedrock Agents, Bedrock Knowledge Bases, Lambda, DynamoDB, Step Functions, MWAA, Pinpoint, Connect, and the institutional integrations (EHRs, HIE, payer claims, pharmacies, home-health, care-team-workflow). High-acuity-event integrity preserved across regions.

**Per-channel authentication and encryption.** Per-channel data-in-transit posture, per-channel session-token TTL, per-channel access-control scope, per-channel BAA scope, per-channel TCPA/10DLC compliance for SMS, per-channel voice-recording retention compliance, audit-record propagation of per-channel authentication context.

**Build-vs-buy rigor.** Several mature commercial vendors offer care-coordination platforms with FHIR integration, claims-feed processing, transition-of-care workflows, and (in some cases) hybrid-coordination workforces. Most major institutions run a hybrid that builds a thin orchestration layer in-house and partners with vendors for the cross-organizational integration substrate.

**Operational ownership across multiple teams.** The assistant sits at the intersection of clinical leadership across primary care, hospital medicine, specialty practice, pharmacy, home health, and care management; the care-management workforce; compliance; regulatory; IT; the call center; patient experience; the malpractice carrier; the institutional regulatory team; and the participating payer's analytics and quality teams.


---

## The Honest Take

The care coordination assistant is the recipe in this chapter where the architectural complexity is highest, the cross-organizational dependencies are most numerous, and the time horizon for outcome demonstration is longest. The previous bots in this chapter operate within a single institution's data and workflow context; this one explicitly operates across organizations, across systems, and across stakeholders. The architectural decisions and the operational disciplines that distinguish a deployment that genuinely improves coordination from a deployment that merely automates the appearance of coordination are not subtle, and most of them have been visible in the published failures of digital coordination tools over the past two decades.

The first trap is treating the cross-organizational integration layer as phase-2 work. The assistant cannot deliver coordination value without consuming data from systems outside the operating institution. Institutions that defer the integration work and build the assistant against a single-EHR data picture build a tool that handles a small slice of the patient's coordination state and misses the seams that are the assistant's distinctive value. The integration layer is multi-quarter engineering work; it is also the largest single engineering investment in the system. Building it concurrently with the conversational layer is the path that produces a tool the patient and care team can use.

The second trap is treating the protocol corpus and seam-detection rule library as someone else's content. The institutional protocols (transition-of-care protocols by destination setting, referral-tracking protocols by specialty and urgency, condition-specific coordination playbooks) and the seam-detection rules (medication-discrepancy detection, referral non-scheduling, transition-of-care incompleteness, conflicting-order detection) are the substance of the coordination work. The LLM is the interface; the institutional content is the substance. Most institutions discover, partway through the project, that their protocols are implicit in their care-managers' heads and need substantial work to be made explicit. Formalizing this is multi-quarter clinical work that has to start before the engineering work and continue alongside it.

The third trap is provenance casualness. When the assistant says "your cardiologist increased your diuretic last Tuesday," the patient or care team may need to know how the assistant knows. A coordination assistant whose assertions cannot be traced back to specific source messages is a coordination assistant the care team cannot trust and the institution cannot defend when something goes wrong. Provenance-as-architectural-primitive is not a nice-to-have; it is the foundation that lets the assistant be auditable, defensible, and trustworthy.

The fourth trap is the caregiver afterthought. A coordination assistant that treats caregivers as patient-pretenders (let the caregiver log in as the patient and use the patient's surface) is a coordination assistant that fails the caregiver-burden monitoring, fails the state-law caregiver-consent requirements, and fails the patient-and-caregiver pattern that is the modal experience for the highest-need population. The caregiver-as-first-class-participant identity model is architectural, not bolt-on.

The fifth trap is the consent over-simplification. Cross-organizational data integration carries cross-organizational consent implications. State-specific privacy regulations apply for sensitive categories. The Information Blocking rule requires certain data sharing; state laws may limit it. The institutional consent posture is reviewed by legal counsel familiar with this landscape before launch and on each material change. Skipping this turns a deployment into a privacy violation waiting to happen.

The sixth trap is scope drift. The assistant is for coordination, not for clinical decision-making, not for triage, not for chronic-disease coaching, not for mental-health support. Adjacent recipes handle those topics. A coordination assistant that drifts into clinical territory is delivering content the institution has not validated, with all of the regulatory and clinical exposure that implies. The scope discipline is broad because the topics adjacent to coordination are numerous, and the deference to other recipes' pathways is the visible architectural manifestation of the discipline.

The seventh trap is care-team-workflow neglect. A coordination assistant that operates as a parallel data stream (the assistant has its own dashboards, its own alerts, its own queues, all separate from the care team's existing tooling) is a coordination assistant the care team will not use. The integration with care-management's existing workflow tooling, the design of the alerts and digests for the care team's actual day, the structured-failure-mode-labeling feedback loop that lets the care team improve the rules, are not optional. Most coordination-tool failures in the published literature are workflow-integration failures, not technology failures.

The eighth trap is outcome-attribution overconfidence. Engaged patients are not a random sample, coordination outcomes have many confounders, and the time horizon for utilization-outcome demonstration is multi-year. Institutions building this with quarterly-impact expectations will be disappointed. Institutions willing to invest at the right time horizon, with appropriate analytical rigor (matched-cohort or quasi-experimental analysis, recognition that observational correlation is suggestive rather than causal), can demonstrate genuinely meaningful outcomes.

The ninth trap is equity blindness. Coordination programs reach disproportionately the patients who are already plugged in to the digital-tool ecosystem and well-instrumented across data sources. The patients with the highest coordination needs are often the patients with the most limited access to digital tools and the most limited integration coverage. A coordination assistant that reaches the patients who need it least and misses the patients who need it most is a coordination assistant that exacerbates rather than reduces healthcare disparities. Per-cohort monitoring is non-negotiable.

The tenth trap is the build-vs-buy ambiguity. Several mature commercial vendors offer care-coordination platforms. The build-vs-buy decision is institution-specific and depends on the integration profile, the protocol portfolio, the care-management workforce structure, the population targeted, and the existing technology stack. Most major institutions in production run a hybrid: thin orchestration in-house, vendor-supplied integration substrate, jointly-owned protocol library, jointly-owned seam-detection rule engine. Pretending the build-vs-buy question has a generic answer is the trap; making it explicit and institution-specific is the discipline.

The eleventh trap is the workforce-sizing under-investment. The economics of the assistant depend on the AI handling routine touches at scale and the human care managers handling the cases that need clinical judgment. A deployment that under-invests in the human care-management workforce is a deployment with safety gaps and missed coordination value. The licensed-and-trained care-management workforce (employed or contracted) is the dominant operational expense, and it is not optional.

The twelfth trap is the regulatory-positioning casualness. Patient-facing care-coordination software with cross-organizational data integration sits at the intersection of HIPAA, the Information Blocking and Interoperability rules, state medical-record statutes, state caregiver-consent rules, 42 CFR Part 2, state mental-health-record protections, and (where the assistant produces clinical recommendations) the FDA SaMD line. The institutional regulatory team is involved from architectural design and reviews each material scope change. Deploying without this involvement is deploying with regulatory exposure that the institution has not characterized.

The thing that surprises engineers coming from generic-chatbot backgrounds is how much of the engineering value is in the integration layer, the protocol corpus, the seam-detection rule library, and the provenance discipline. The conversational LLM and the tool-orchestration are largely the same as the previous chapter 11 recipes; the cross-organizational integration, the institutional content, the seam-detection rules, the caregiver identity model, the consent posture, and the provenance journal are the parts that distinguish a coordination assistant from a chat surface over a single EHR.

The thing that surprises clinical leaders coming from care-management practice is how dependent the assistant's quality is on the explicitness of the protocol content. Care managers operate from clinical judgment built over years of experience; the assistant operates from explicit, version-controlled protocol content with named clinical-leadership ownership. Formalizing what care managers do informally is multi-quarter clinical work that takes more effort than the engineering work and produces an artifact (the institutional protocol corpus) that is valuable in its own right beyond the assistant.

The thing that surprises business leaders is how long the time horizon is and how the human care-management workforce is the dominant cost. The infrastructure cost is meaningful; the workforce cost is typically larger. A deployment that under-invests in the workforce is a deployment with safety gaps. The economics work because the assistant handles the routine touches while the workforce focuses on the cases that need clinical judgment, but the workforce is not optional.

The thing about Amazon Bedrock specifically: same as recipes 11.2 through 11.8, Bedrock Agents is the right level of abstraction. The Agent handles the multi-step LLM-and-tool orchestration; the action groups are the coordination tools; Knowledge Bases provides the multi-corpus RAG over protocols, education, and history; Guardrails provides safety filtering with coordination-specific denied topics. The institutional value lives in the integration layer, the protocol corpus, the seam-detection rules, the caregiver identity model, the consent posture, and the provenance journal, not in the Bedrock features themselves.

The thing about cost: as noted, the dominant operational cost is the human care-management workforce, not the AWS infrastructure. The infrastructure cost is small relative to the cost of even a single avoidable readmission, and a single avoidable adverse event from a missed coordination seam has individual and societal consequences that no actuarial accounting can capture.

The thing about cross-organizational integration: the field has moved meaningfully in the past five years, with ONC certification of FHIR APIs, the Information Blocking final rule, TEFCA implementation, and FHIR Bulk Data Access making cross-organizational data exchange more feasible than it was a decade ago. Coordination architectures that consume this infrastructure are operating in a more capable environment than equivalent architectures from the early 2010s. The integration is still uneven, the data quality is still inconsistent, and the operational realities still require substantial human attention; but the foundation is meaningfully better than it was.

The thing about patient and caregiver trust: a coordination assistant that is clearly a chat tool, that delivers content grounded in cited provenance, that is explicit about what it knows and what it does not know, that defers to the human care team for clinical judgment, and that visibly works alongside the care team rather than replacing it, builds trust over time. A coordination assistant that overreaches, hides its limitations, or pretends to clinical authority destroys trust quickly and is hard to recover.

The thing I would do differently the second time: start with a single transition type (typically post-discharge from an inpatient stay) and a narrow population (a specific Medicare Advantage cohort, or a specific hospital's discharge-to-home pipeline) before expanding to multi-transition, multi-population coordination. The narrow start lets the team validate the integration layer, the protocol corpus, the seam-detection rules, the caregiver identity model, the consent posture, the provenance journal, the workflow integration with care management, and the per-cohort monitoring against a manageable scope. Adding additional transitions, populations, languages, and channels later, with the validated infrastructure already in place, is safer and more likely to succeed than launching with the full scope and discovering the failure modes against a heterogeneous population.

The last thing: care coordination is the use case where the cumulative effect of dozens of small touches across weeks and months is the substance of the value, and where the assistant's value is not in any individual conversation but in the seams it catches that would otherwise have been missed, the referrals it closes that would otherwise have languished, the transitions it orchestrates that would otherwise have generated readmissions, and the relief it provides to caregivers who would otherwise have been the only thread holding the coordination together. An assistant evaluated on per-conversation engagement metrics will be optimized for the wrong thing. An assistant evaluated on coordination outcomes (referral closure rate, transition completion rate, medication-reconciliation accuracy, caregiver burden, avoidable utilization, patient-and-caregiver coordination experience) is being evaluated correctly, and the architectural decisions follow from there. Build the institutional muscles for the harder parts first; the conversational layer is the easier part.


---

## Variations and Extensions

**Post-discharge coordination assistant (transitional-care focus).** A focused variant for the immediate post-discharge window (typically 30-90 days), with intensive engagement around medication reconciliation, follow-up-appointment scheduling, red-flag warning instructions, and readmission prevention. Often deployed as the first variant because the time window is short, the protocol is well-established, and the readmission-prevention outcome is well-measured.

**Chronic-multi-condition coordination assistant (the David case from the opening).** A variant for patients with multiple chronic conditions across multiple specialties and multiple organizations, with longer-term engagement (months to years), heavier focus on cross-clinician coordination and medication reconciliation across pharmacies, and tight integration with the patient's primary care home. The use case the recipe opens with.

**Oncology coordination assistant.** A variant for oncology patients in active treatment, with treatment-cycle-aware engagement (chemotherapy infusion sequences, radiation therapy regimens, surgical recovery, immunotherapy cycles), tight integration with the oncology team's care navigators, and side-effect-management content alongside the coordination work. Often deployed in parallel with a dedicated human oncology nurse navigator who handles complex coordination; the assistant handles routine touches.

**Transplant coordination assistant.** A variant for transplant recipients (kidney, liver, heart, lung, stem cell) with phase-specific protocols (waitlist, peri-transplant, immediate post-transplant, long-term post-transplant), tight integration with the transplant team, intensive medication-reconciliation focus given the immunosuppression regimen complexity, and high-acuity-event sensitivity given the catastrophic consequences of missed coordination.

**Heart-failure-focused coordination assistant.** A variant for the heart-failure population with disease-specific monitoring (weight, symptoms, medication adherence), tight integration with the cardiology team, GDMT-titration support that surfaces guideline-directed-medical-therapy progress, and decompensation-risk monitoring. Frequently deployed alongside heart-failure-specific care management.

**Pediatric complex-care coordination assistant.** A variant for children with medical complexity (multiple specialists, durable medical equipment, home nursing, school-based care), with caregiver-as-primary-participant identity model, school-based-care integration, and pediatric-specific protocols. Subject to additional consent considerations given the patient is a minor.

**Older-adult coordination assistant with dementia-mediated communication.** A variant for older adults including patients with cognitive impairment, with caregiver-mediated communication patterns, dementia-specific protocols, fall-risk and elder-abuse screening integration, and tight integration with geriatric care management.

**Maternal-and-postpartum coordination assistant.** A variant for the prenatal-through-postpartum window, with pregnancy-trimester-aware engagement, postpartum-specific protocols including postpartum-depression screening (recipe 11.8 pathway), newborn-care coordination, and lactation-support coordination.

**Behavioral-health-medical integrated coordination assistant.** A variant for the population with comorbid behavioral-health and medical conditions, with tight integration to recipe 11.8 (mental health) and recipe 11.7 (chronic disease), 42 CFR Part 2 compliance for substance-use treatment data where applicable, and state-specific mental-health-record privacy compliance.

**Population-management coordination overlay.** A variant deployed at the population level (a Medicare Advantage book of business; a primary-care panel; an ACO attribution list) with population-wide bulk-data ingestion, population-level seam-detection runs, risk-stratified engagement intensity, and integration with the institution's quality-measurement and value-based-contract reporting.

**Specialty-referral-management variant.** A variant focused on the referral-tracking workflow, with intensive referral-lifecycle management, specialty-acceptance-and-wait-time tracking, alternative-specialist surfacing when barriers are encountered, and tight integration with the referring practice's care managers.

**Care-navigation variant for under-resourced populations.** A variant adapted for patients in markets with limited integration coverage, limited specialty access, and significant social-determinant barriers, with heavier reliance on patient-mediated SMART on FHIR data flows, deeper social-services integration, and culturally-and-linguistically-adapted content.

**Emergency-department-to-primary-care-follow-up variant.** A variant focused on the ED-discharge-to-primary-care transition, with intensive engagement in the 24-72 hour post-ED-discharge window, medication-reconciliation against the ED visit's new prescriptions, follow-up-appointment validation within the protocol window, and red-flag-warning delivery.

**Hospital-at-home coordination assistant.** A variant for patients in hospital-at-home programs, with tight integration to the hospital-at-home care team, daily check-ins on biometric monitoring, medication-administration verification, and acute-event-escalation pathways. <!-- TODO: verify; hospital-at-home is an established care-delivery model with specific Medicare reimbursement considerations through the CMS Acute Hospital Care at Home waiver and similar payer programs -->

**Voice-channel deployment for accessibility.** A voice-channel variant for patients without smartphones, patients with disabilities affecting written communication, and patients who prefer voice. Voice-specific design includes slower pacing, briefer responses, and accessibility considerations. High-acuity-event integrity is preserved across channels.

**Multi-language deployment beyond English plus Spanish.** Per-language asset development reviewed by clinical leadership and language-services teams, with per-language equity monitoring and culturally-adapted protocol content where appropriate.

**Hybrid AI-plus-licensed-coach deployment.** The assistant handles routine engagement; a licensed nurse coach is available for between-touch support beyond the assistant's scope. The architectural extension is the licensed-coach scheduling and case-load management, plus the differentiation between assistant-scope and coach-scope topics.

**High-risk-tier deployment with intensive nurse case management.** A higher-touch variant for the highest-risk slice of the population, with daily assistant engagement, weekly nurse-case-manager touches, and aggressive escalation pathways. The assistant's scope is the same; the operational integration with case management is deeper.

**Population-health overlay with quality-measure focus.** The assistant's outputs feed an institutional population-health dashboard tracking patterns of coordination quality across the population for HEDIS, Star Ratings, ACO quality-measure reporting, and value-based-contract performance.

**Build-on-FHIR-only variant for institutions without HL7 v2 sources.** A variant deployed in markets where FHIR is the dominant interchange standard, with simpler integration architecture (FHIR-only ingestion), tighter coupling to FHIR-native semantic models, and reduced integration complexity at the cost of partial coverage where HL7 v2 is the modal interchange.

**Continuous-improvement loop with structured failure-mode labeling.** Beyond per-conversation feedback, the institution runs a structured labeling program where reviewers (RNs, care managers, clinical leadership) tag failure modes (out-of-scope, off-protocol, seam-detection-miss, seam-detection-false-positive, provenance-gap, citation-gap, scope-violation, equity-disparity, integration-coverage-gap). The labels feed the protocol-library, seam-detection-rule, prompt-tuning, and policy-revision workflows.

**Specialty-specific protocol-library variants.** Cardiology-specific, oncology-specific, transplant-specific, behavioral-health-medical-integrated, pediatric-complex-care-specific protocol libraries with named clinical-leadership ownership and annual review cycles. The variant pattern: a base coordination architecture plus specialty-specific overlays.

**Provider-side coordination assistant.** A variant deployed not for the patient but for the patient's care team, providing the same coordination state and seam-detection layer with a provider-facing surface (instead of, or in addition to, the patient-facing surface). The provider variant is often easier to deploy because the consent and identity model is simpler, but the patient-facing variant is where the broader population-scale coordination value lives.

---

## Related Recipes

- **Recipe 11.1 (FAQ Chatbot):** Same chapter, foundational. The coordination assistant inherits the input-screening pipeline, scope filtering, conversation logging, audit pattern, persona discipline, and per-cohort monitoring.
- **Recipe 11.2 (Appointment Scheduling Bot):** Same chapter. The assistant's coordination work routinely produces scheduling needs (follow-up appointments after discharge, referral-driven specialty visits, lab-draw appointments) that hand off to the scheduling bot's booking infrastructure.
- **Recipe 11.3 (Prescription Refill Request Bot):** Same chapter. Coordination conversations that surface refill needs hand off to the refill workflow; coordination-detected medication-reconciliation gaps may surface during refill conversations as well.
- **Recipe 11.4 (Pre-Visit Intake Bot):** Same chapter. The coordination assistant's longitudinal context can pre-populate intake for scheduled visits with appropriate consent and provenance.
- **Recipe 11.5 (Insurance Benefits Navigator):** Same chapter. Coordination conversations that surface benefits questions (does my insurance cover this specialist? does my insurance accept the lab the doctor wants? is the home-health agency in-network?) route to the benefits navigator.
- **Recipe 11.6 (Symptom Checker / Triage Bot):** Same chapter. Acute symptom presentations during coordination conversations route to the triage workflow with the coordination context preserved.
- **Recipe 11.7 (Chronic Disease Management Coach):** Same chapter. Patients with chronic conditions may have both deployments; the coach handles within-condition disease management while the coordinator handles cross-clinician coordination. Consent-gated context flows in both directions.
- **Recipe 11.8 (Mental Health Support Bot):** Same chapter. Patients with comorbid behavioral-health needs route to recipe 11.8 for behavioral-health support while the coordination assistant continues to manage the cross-clinician coordination.
- **Recipe 11.10 (Clinical Trial Recruitment Conversationalist):** Same chapter. Patients identified as candidates for clinical trials may be referred from the coordination assistant with appropriate consent.
- **Recipe 1.6 (Handwritten Clinical Note Digitization):** Chapter 1. Where home-health agencies or smaller practices share notes via paper or scanned documents, the digitization pipeline feeds coordination context.
- **Recipe 2.5 (After-Visit Summary Generation):** Chapter 2. After-visit summaries from cross-organization visits feed the coordination assistant's longitudinal context where consent permits.
- **Recipe 2.6 (Clinical Note Summarization):** Chapter 2. Summarization of cross-organization clinical notes powers the coordination assistant's encounter-context tooling.
- **Recipe 3.7 (Patient Deterioration Early Warning):** Chapter 3. Coordination-state-aware deterioration patterns (post-discharge decompensation, missed-medication-driven decompensation) complement the deterioration detection systems.
- **Recipe 3.8 (Readmission Risk Anomaly Detection):** Chapter 3. Readmission-risk scores inform coordination intensity and care-team-attention prioritization.
- **Recipe 4.5 (Medication Adherence Intervention Targeting):** Chapter 4. Coordination-detected medication-adherence issues feed adherence-intervention targeting; the coordination assistant is one delivery channel.
- **Recipe 4.6 (Care Gap Prioritization):** Chapter 4. Coordination-state-aware care-gap prioritization feeds the assistant's protocol-driven engagement scheduling.
- **Recipe 4.7 (Care Management Program Enrollment):** Chapter 4. The coordination assistant is one tier in a multi-tier care-management program; high-risk patients identified by the assistant may be promoted to higher-touch nurse case management.
- **Recipe 5.5 (Cross-Facility Patient Matching):** Chapter 5. Cross-organizational data integration depends on patient-matching across organizations; the coordination assistant inherits the entity-resolution work.
- **Recipe 5.6 (Claims-to-Clinical Data Linkage):** Chapter 5. The coordination assistant's claims-feed integration depends on claims-to-clinical linkage to make claims data clinically actionable.
- **Recipe 7.x (Predictive Analytics, Chapter 7):** Risk scores including readmission-risk, ED-utilization-risk, and total-cost-of-care prediction inform coordination intensity.
- **Recipe 10.5 (Patient-Facing Voice Assistant):** Chapter 10. Voice-channel coordination support builds on voice-assistant ASR/TTS patterns.
- **Recipe 12.x (Time Series Analysis):** Chapter 12. Longitudinal symptom-tracking and biometric-trend analysis benefits from time-series patterns.
- **Recipe 13.x (Knowledge Graphs):** Chapter 13. Patient-and-care-network knowledge graphs (clinicians, organizations, relationships, referral histories, claims patterns) underpin coordination-state synthesis.


---

## Additional Resources

**AWS Documentation:**
- [Amazon Bedrock User Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html)
- [Amazon Bedrock Agents](https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html)
- [Amazon Bedrock Knowledge Bases](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base.html)
- [Amazon Bedrock Guardrails](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html)
- [Amazon OpenSearch Serverless](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless.html)
- [AWS HealthLake Developer Guide](https://docs.aws.amazon.com/healthlake/latest/devguide/what-is-amazon-health-lake.html)
- [AWS HealthLake Bulk Data Export](https://docs.aws.amazon.com/healthlake/latest/devguide/export-datastore.html)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [Amazon MWAA User Guide](https://docs.aws.amazon.com/mwaa/latest/userguide/what-is-mwaa.html)
- [Amazon API Gateway Developer Guide](https://docs.aws.amazon.com/apigateway/latest/developerguide/welcome.html)
- [AWS WAF Developer Guide](https://docs.aws.amazon.com/waf/latest/developerguide/waf-chapter.html)
- [Amazon DynamoDB Developer Guide](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html)
- [Amazon S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html)
- [Amazon EventBridge User Guide](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html)
- [Amazon Pinpoint Developer Guide](https://docs.aws.amazon.com/pinpoint/latest/developerguide/welcome.html)
- [Amazon Connect Administrator Guide](https://docs.aws.amazon.com/connect/latest/adminguide/what-is-amazon-connect.html)
- [Amazon Comprehend Medical](https://docs.aws.amazon.com/comprehend-medical/latest/dev/comprehendmedical-welcome.html)
- [Amazon SageMaker Developer Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html)
- [AWS HIPAA Eligible Services Reference](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)

**AWS Sample Repos:**
- [`aws-samples/amazon-bedrock-samples`](https://github.com/aws-samples/amazon-bedrock-samples): Bedrock invocation patterns including Agents, Knowledge Bases, Guardrails
- [`aws-samples/aws-genai-llm-chatbot`](https://github.com/aws-samples/aws-genai-llm-chatbot): reference architecture for a multi-model chatbot on AWS
- [`aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks`](https://github.com/aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks): broader healthcare AI/ML sample notebooks
<!-- TODO: confirm current repo names and locations at time of build; the AWS sample repo organization changes over time -->

**AWS Solutions and Blogs:**
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter Healthcare and Life Sciences plus AI/ML): browse for care-coordination, transitions-of-care, and patient-engagement reference architectures
- [AWS Machine Learning Blog](https://aws.amazon.com/blogs/machine-learning/): search "Bedrock Agents," "healthcare conversational AI," "care coordination"
- [AWS for Industries: Healthcare and Life Sciences Blog](https://aws.amazon.com/blogs/industries/category/industries/healthcare/): search "care coordination," "transitions of care," "patient engagement," "interoperability"
<!-- TODO: replace generic search-the-blog pointers with specific verified blog post URLs once they are confirmed to exist -->

**External References (Standards, Frameworks, and Clinical Guidelines):**
- [HL7 v2 Messaging Standard](https://www.hl7.org/implement/standards/product_brief.cfm?product_id=185): legacy clinical-event messaging standard widely deployed for ADT and ORU
- [HL7 FHIR R4 Specification](https://www.hl7.org/fhir/R4/): the modern interchange standard
- [HL7 FHIR US Core Implementation Guide](https://hl7.org/fhir/us/core/): U.S. baseline FHIR profiles
- [USCDI (United States Core Data for Interoperability)](https://www.healthit.gov/isa/united-states-core-data-interoperability-uscdi): minimum data set required by ONC certification
- [FHIR Bulk Data Access Specification](https://hl7.org/fhir/uv/bulkdata/): population-level data export specification
- [SMART on FHIR](https://docs.smarthealthit.org/): authorization and app-launch framework for FHIR-based applications
- [21st Century Cures Act and ONC Information Blocking Final Rule](https://www.healthit.gov/topic/information-blocking): U.S. federal information-blocking regulation
- [TEFCA (Trusted Exchange Framework and Common Agreement)](https://www.healthit.gov/topic/interoperability/policy/trusted-exchange-framework-and-common-agreement-tefca): U.S. national interoperability framework
- [42 CFR Part 2](https://www.ecfr.gov/current/title-42/chapter-I/subchapter-A/part-2): U.S. federal confidentiality regulation for substance-use treatment records
- [HIPAA Privacy Rule](https://www.hhs.gov/hipaa/for-professionals/privacy/index.html): governs PHI in coordination state, conversation logs, and longitudinal records
- [HIPAA Security Rule](https://www.hhs.gov/hipaa/for-professionals/security/index.html): governs technical and administrative safeguards
- [NCPDP SCRIPT and Telecommunication Standards](https://www.ncpdp.org/Standards): pharmacy data interchange standards
- [Care Coordination Measures Atlas (AHRQ)](https://www.ahrq.gov/ncepcr/care/coordination/atlas.html): published catalog of care-coordination measurement frameworks
- [Project RED (Re-Engineered Discharge)](https://www.bu.edu/fammed/projectred/): published transitions-of-care intervention with measured outcomes
- [Care Transitions Intervention (Coleman)](https://caretransitions.health/): published transitions-of-care intervention model
- [Transitional Care Model (Naylor)](https://www.transitionalcare.info/): published transitions-of-care nurse-led model
- [Patient-Centered Medical Home (NCQA)](https://www.ncqa.org/programs/health-care-providers-practices/patient-centered-medical-home-pcmh/): primary-care coordination framework
- [Centers for Medicare and Medicaid Services Chronic Care Management](https://www.cms.gov/Outreach-and-Education/Medicare-Learning-Network-MLN/MLNProducts/Downloads/ChronicCareManagement.pdf): CMS framework for billable chronic-care-management services
- [Centers for Medicare and Medicaid Services Transitional Care Management](https://www.cms.gov/outreach-and-education/medicare-learning-network-mln/mlnproducts/downloads/transitional-care-management-services-fact-sheet-icn908628.pdf): CMS framework for billable transitional-care-management services
- [Zarit Burden Interview](https://www.dementiapathways.ie/_filecache/04a/ddd/98-zbi.pdf): widely used and validated caregiver-burden assessment instrument
- [American Geriatrics Society Beers Criteria](https://www.americangeriatrics.org/publications-tools/beers-criteria-american-geriatrics-society): potentially-inappropriate-medication criteria for older adults, relevant for medication-reconciliation seam detection
- [STOPP/START Criteria](https://academic.oup.com/ageing/article/44/2/213/2812233): explicit criteria for prescribing in older adults
- [FDA Software as a Medical Device (SaMD)](https://www.fda.gov/medical-devices/digital-health-center-excellence/software-medical-device-samd): FDA SaMD framework
- [FDA Digital Health Center of Excellence](https://www.fda.gov/medical-devices/digital-health-center-excellence): central resource for digital-health regulatory updates
- [FDA Clinical Decision Support Software Final Guidance (2022)](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/clinical-decision-support-software): FDA framework distinguishing regulated and non-regulated CDS
- [WCAG 2.1 Accessibility Guidelines](https://www.w3.org/WAI/standards-guidelines/wcag/): accessibility standards for chat-widget surfaces
- [OWASP Top 10 for Large Language Model Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/): security framework for LLM-backed applications
- [TCPA and 10DLC for SMS](https://www.fcc.gov/general/telephone-consumer-protection-act-1991): U.S. SMS-messaging regulation, relevant for coordination-related text outreach

**Industry and Research Resources:**
- [American College of Physicians (ACP)](https://www.acponline.org/): internal-medicine specialty association including care-coordination resources
- [American Academy of Family Physicians (AAFP)](https://www.aafp.org/): family-medicine specialty association including care-coordination resources
- [American Hospital Association (AHA)](https://www.aha.org/): hospital industry association including transitions-of-care resources
- [Case Management Society of America (CMSA)](https://www.cmsa.org/): case-management professional association
- [American Case Management Association (ACMA)](https://www.acmaweb.org/): case-management professional association
- [National Patient Safety Foundation (NPSF)](https://www.npsf.org/): patient-safety research and advocacy
- [Institute for Healthcare Improvement (IHI)](https://www.ihi.org/): quality-improvement resources including transitions-of-care toolkits
- [American Society of Health-System Pharmacists (ASHP)](https://www.ashp.org/): medication-reconciliation resources
- [Sequoia Project](https://sequoiaproject.org/): TEFCA Recognized Coordinating Entity, interoperability resources
- [HIMSS Interoperability Showcase](https://www.himss.org/): industry interoperability showcase
- [Office of the National Coordinator for Health Information Technology (ONC)](https://www.healthit.gov/): U.S. federal interoperability and information-blocking authority
- [American Medical Association (AMA) Augmented Intelligence Resources](https://www.ama-assn.org/practice-management/digital/augmented-intelligence-medicine): AMA position statements on AI in medical practice including coordination applications

---

## Estimated Implementation Time

| Tier | Scope | Time |
|------|-------|------|
| Basic | Single transition type (typically post-discharge from inpatient stay), single language (English), single channel (in-app chat plus SMS for proactive engagement), single primary EHR integration via FHIR with one secondary HIE integration, single primary pharmacy integration, basic coordination-protocol library (post-discharge protocols only) reviewed by clinical leadership, basic seam-detection rule library (medication discrepancy plus referral non-scheduling plus transition-of-care incompleteness only) with named clinical-leadership ownership, basic caregiver identity model with one or two state-law jurisdictions covered, basic provenance journal, basic transition-of-care Step Functions workflow for the single transition type, basic care-team alert and weekly digest reporting, basic FDA-strategy artifact reviewed by regulatory counsel, basic per-cohort monitoring at the institutional-aggregate level, basic audit pipeline with coordination-specific retention, named clinical-leadership ownership across primary care and hospital medicine and care management, multi-quarter clinical-content development and integration work | 18-24 months |
| Production-ready | Multi-transition (post-discharge from inpatient, post-procedure, ED-to-PCP follow-up, surgery-to-home, oncology-treatment cycles), multi-channel (web chat, app embed, SMS with TCPA/10DLC compliance, voice via Connect), multi-language (English plus Spanish at minimum with clinically-validated translations), multi-source integration including multiple EHRs via FHIR with USCDI v3 conformance, HL7 v2 ADT and ORU feeds, HIE/TEFCA participation, payer claims feed (where applicable), multiple pharmacies (NCPDP and major-chain APIs), home-health vendor APIs, lab feeds, full coordination-protocol library across primary care, hospital medicine, specialty practice, pharmacy, home health, and care management with annual review cycles, full seam-detection rule library with named clinical-leadership ownership per rule, full caregiver identity model with state-specific compliance, full provenance journal with separate KMS keying, full transition-of-care Step Functions workflows for the institution's full transition portfolio, full care-team workflow integration with case management's existing tooling, full FDA-strategy artifact and (where applicable) SaMD registration, full HIPAA-grade compliance review including state-specific medical-record retention compliance and 42 CFR Part 2 compliance where applicable, full per-cohort equity monitoring with launch-gate discipline, mandatory-reporting routing per state, outcome-correlation pipeline with multi-window correlation against utilization, clinical, and patient-experience outcomes, named operational owners across clinical leadership in primary care and hospital medicine and specialty practice and pharmacy and home health and care management, the care-management workforce, compliance, regulatory, IT, the call center, and patient experience | 36-60 months |
| With variations | Post-discharge variant deep deployment, chronic-multi-condition variant, oncology coordination variant, transplant coordination variant, heart-failure-focused variant, pediatric-complex-care variant, older-adult-with-dementia variant, maternal-and-postpartum variant, behavioral-health-medical-integrated variant with 42 CFR Part 2 compliance, population-management overlay variant, specialty-referral-management variant, care-navigation variant for under-resourced populations, ED-to-PCP-follow-up variant, hospital-at-home variant, voice-channel variant with accessibility considerations, multi-language deployment beyond English plus Spanish with native-speaker review, hybrid AI-plus-licensed-coach variant, high-risk-tier variant with intensive case management, population-health overlay with quality-measure focus, build-on-FHIR-only variant, continuous-improvement loop with structured failure-mode labeling, specialty-specific protocol-library variants, provider-side coordination variant | 24-48 months beyond production-ready |

---

## Tags

`conversational-ai` · `care-coordination` · `care-coordination-assistant` · `transitions-of-care` · `referral-tracking` · `referral-lifecycle` · `medication-reconciliation` · `seam-detection` · `cross-organizational-integration` · `longitudinal-coordination-state` · `provenance-discipline` · `caregiver-as-first-class-participant` · `proxy-access` · `cross-organizational-consent` · `tool-using-llm` · `function-calling` · `bedrock-agents` · `rag` · `citation-grounding` · `protocol-library` · `coordination-protocol-corpus` · `patient-education-library` · `hl7-v2-ingestion` · `fhir-ingestion` · `fhir-bulk-data` · `claims-feed-ingestion` · `pharmacy-data-integration` · `ncpdp` · `hie-integration` · `tefca-integration` · `home-health-integration` · `lab-feed-integration` · `intent-classification` · `scope-containment` · `prompt-injection-defense` · `prompt-versioning` · `persona-design` · `patient-facing` · `caregiver-facing` · `multilingual` · `accessibility` · `equity-monitoring` · `cohort-stratified-accuracy` · `outcome-correlation` · `referral-closure-rate` · `transition-completion-rate` · `medication-reconciliation-accuracy` · `caregiver-burden` · `avoidable-readmission` · `avoidable-ed-utilization` · `social-determinants-of-health` · `state-mental-health-privacy` · `42-cfr-part-2` · `information-blocking-rule` · `21st-century-cures-act` · `fda-samd` · `fda-cds` · `regulatory-strategy` · `clinical-leadership-signoff` · `bedrock` · `bedrock-knowledge-bases` · `bedrock-guardrails` · `opensearch-serverless` · `healthlake` · `lambda` · `step-functions` · `mwaa` · `api-gateway` · `waf` · `dynamodb` · `s3` · `kms` · `secrets-manager` · `cloudwatch` · `cloudtrail` · `eventbridge` · `kinesis-firehose` · `glue` · `athena` · `pinpoint` · `connect` · `comprehend-medical` · `sagemaker` · `quicksight` · `complex` · `regulated` · `hipaa` · `phi-handling` · `audit-trail` · `coordination-decision-record-journal` · `provenance-journal` · `seam-flag-store` · `referral-lifecycle-store` · `transition-of-care-store` · `consent-record` · `chapter11` · `recipe-11-9`
