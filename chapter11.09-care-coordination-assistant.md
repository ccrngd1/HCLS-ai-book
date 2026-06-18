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

```text
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
│    - Structured state: key-value tables with provenance   │
│      indexing                                             │
│    - Conversation transcript: object store with vector    │
│      retrieval                                            │
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

**Working-store PHI minimization with archive-reference discipline.** The longitudinal coordination-state store, coordination-decision-record journal, provenance journal, seam-flag store, referral-lifecycle store, transition-of-care store, caregiver store, consent record, and tool-call ledger preserve structural records on the hot path with archive references for full content, where the content archives are separately keyed and separately access-controlled (the provenance archive uses a distinct customer-managed encryption key restricted to audit-and-compliance plus regulatory plus malpractice insurer; the coordination-decision-record archive uses a distinct customer-managed encryption key). Retention reconciles the longest of HIPAA's six-year minimum, state-specific medical-record retention rules, 42 CFR Part 2 retention for substance-use treatment data, state-specific mental-health-record and HIV-record and genetic-test-result protections, pediatric-record retention until age of majority plus state adult retention, FDA SaMD post-market obligations, Information Blocking rule audit-trail obligations, and litigation-hold.

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


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter11.09-architecture). The Python example is linked from there.

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

The thing about the cloud implementation specifically: same as recipes 11.2 through 11.8, a managed agent-and-tool orchestration layer is the right level of abstraction. The agent handles the multi-step LLM-and-tool orchestration; the action groups are the coordination tools; a managed RAG layer provides the multi-corpus retrieval over protocols, education, and history; a guardrail layer provides safety filtering with coordination-specific denied topics. The institutional value lives in the integration layer, the protocol corpus, the seam-detection rules, the caregiver identity model, the consent posture, and the provenance journal, not in the cloud-vendor features themselves. (See the [Architecture and Implementation companion](chapter11.09-architecture) for the AWS-specific service mapping.)

The thing about cost: as noted, the dominant operational cost is the human care-management workforce, not the cloud infrastructure. The infrastructure cost is small relative to the cost of even a single avoidable readmission, and a single avoidable adverse event from a missed coordination seam has individual and societal consequences that no actuarial accounting can capture.

The thing about cross-organizational integration: the field has moved meaningfully in the past five years, with ONC certification of FHIR APIs, the Information Blocking final rule, TEFCA implementation, and FHIR Bulk Data Access making cross-organizational data exchange more feasible than it was a decade ago. Coordination architectures that consume this infrastructure are operating in a more capable environment than equivalent architectures from the early 2010s. The integration is still uneven, the data quality is still inconsistent, and the operational realities still require substantial human attention; but the foundation is meaningfully better than it was.

The thing about patient and caregiver trust: a coordination assistant that is clearly a chat tool, that delivers content grounded in cited provenance, that is explicit about what it knows and what it does not know, that defers to the human care team for clinical judgment, and that visibly works alongside the care team rather than replacing it, builds trust over time. A coordination assistant that overreaches, hides its limitations, or pretends to clinical authority destroys trust quickly and is hard to recover.

The thing I would do differently the second time: start with a single transition type (typically post-discharge from an inpatient stay) and a narrow population (a specific Medicare Advantage cohort, or a specific hospital's discharge-to-home pipeline) before expanding to multi-transition, multi-population coordination. The narrow start lets the team validate the integration layer, the protocol corpus, the seam-detection rules, the caregiver identity model, the consent posture, the provenance journal, the workflow integration with care management, and the per-cohort monitoring against a manageable scope. Adding additional transitions, populations, languages, and channels later, with the validated infrastructure already in place, is safer and more likely to succeed than launching with the full scope and discovering the failure modes against a heterogeneous population.

The last thing: care coordination is the use case where the cumulative effect of dozens of small touches across weeks and months is the substance of the value, and where the assistant's value is not in any individual conversation but in the seams it catches that would otherwise have been missed, the referrals it closes that would otherwise have languished, the transitions it orchestrates that would otherwise have generated readmissions, and the relief it provides to caregivers who would otherwise have been the only thread holding the coordination together. An assistant evaluated on per-conversation engagement metrics will be optimized for the wrong thing. An assistant evaluated on coordination outcomes (referral closure rate, transition completion rate, medication-reconciliation accuracy, caregiver burden, avoidable utilization, patient-and-caregiver coordination experience) is being evaluated correctly, and the architectural decisions follow from there. Build the institutional muscles for the harder parts first; the conversational layer is the easier part.


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

## Tags

`conversational-ai` · `care-coordination` · `care-coordination-assistant` · `transitions-of-care` · `referral-tracking` · `referral-lifecycle` · `medication-reconciliation` · `seam-detection` · `cross-organizational-integration` · `longitudinal-coordination-state` · `provenance-discipline` · `caregiver-as-first-class-participant` · `proxy-access` · `cross-organizational-consent` · `tool-using-llm` · `function-calling` · `bedrock-agents` · `rag` · `citation-grounding` · `protocol-library` · `coordination-protocol-corpus` · `patient-education-library` · `hl7-v2-ingestion` · `fhir-ingestion` · `fhir-bulk-data` · `claims-feed-ingestion` · `pharmacy-data-integration` · `ncpdp` · `hie-integration` · `tefca-integration` · `home-health-integration` · `lab-feed-integration` · `intent-classification` · `scope-containment` · `prompt-injection-defense` · `prompt-versioning` · `persona-design` · `patient-facing` · `caregiver-facing` · `multilingual` · `accessibility` · `equity-monitoring` · `cohort-stratified-accuracy` · `outcome-correlation` · `referral-closure-rate` · `transition-completion-rate` · `medication-reconciliation-accuracy` · `caregiver-burden` · `avoidable-readmission` · `avoidable-ed-utilization` · `social-determinants-of-health` · `state-mental-health-privacy` · `42-cfr-part-2` · `information-blocking-rule` · `21st-century-cures-act` · `fda-samd` · `fda-cds` · `regulatory-strategy` · `clinical-leadership-signoff` · `bedrock` · `bedrock-knowledge-bases` · `bedrock-guardrails` · `opensearch-serverless` · `healthlake` · `lambda` · `step-functions` · `mwaa` · `api-gateway` · `waf` · `dynamodb` · `s3` · `kms` · `secrets-manager` · `cloudwatch` · `cloudtrail` · `eventbridge` · `kinesis-firehose` · `glue` · `athena` · `pinpoint` · `connect` · `comprehend-medical` · `sagemaker` · `quicksight` · `complex` · `regulated` · `hipaa` · `phi-handling` · `audit-trail` · `coordination-decision-record-journal` · `provenance-journal` · `seam-flag-store` · `referral-lifecycle-store` · `transition-of-care-store` · `consent-record` · `chapter11` · `recipe-11-9`
