# Recipe 11.10: Clinical Trial Recruitment Conversationalist

**Complexity:** Complex · **Phase:** Regulated · **Estimated Cost:** ~$8-25 per qualified prescreen (depends on trial complexity, channel mix, model choice, eligibility-criteria depth, and coordinator-handoff volume)

---

## The Problem

Maria is 52, lives in a small city in central Texas, and was diagnosed three years ago with type 2 diabetes that has not responded well to metformin plus a long-acting insulin. Her endocrinologist mentioned, at her last visit, that there are some new investigational therapies in clinical trials and that Maria might be eligible for one if she is interested. The endocrinologist printed out a sheet listing three trials, with study identifiers and a phone number to call. Maria put the sheet in her purse, intended to call, did not call (the number was an academic medical center 90 miles away and the office hours overlapped with her work shift), forgot about it for two weeks, found the sheet again while cleaning out her purse, called the number, got voicemail, left a message, did not hear back for four days, called again, got a research coordinator who took her name and phone number and said someone would call her back to do an initial screen, was called back two days later by a different coordinator who asked her about thirty-five questions over a forty-minute phone call (most of which Maria answered "I'm not sure, I'd have to check my chart"), was told the coordinator would review and get back to her, did not hear back for ten days, was finally called back and told she did not appear to qualify for trial number one because of a lab value she had not heard of, possibly qualified for trial number two but the coordinator needed to verify her insurance coverage and her medication history, and would not be informed about trial number three because that trial had closed enrollment three weeks earlier (which had not been reflected on the printout her endocrinologist gave her). By this point, Maria had spent about three hours on the phone, two weeks of elapsed calendar time, and a meaningful amount of frustration to learn that she might qualify for one trial, pending further review.

If you talk to clinical research coordinators about their daily work, this is a recognizable arc. If you talk to clinical-trial sponsors about their recruitment data, this is part of why the recruitment funnel looks the way it does. The published literature on clinical-trial recruitment has documented for years that many trials fail to enroll on time, that many enrolled trials enroll fewer participants than planned, that the dominant cost of late enrollment is the trial-extension cost, that the dominant cost of inadequate enrollment is the trial-failure cost, and that the dominant cause of recruitment underperformance is the recruitment funnel itself.  The trial protocols are written. The investigators are willing. The patients are out there. The funnel between the patients and the trials is the problem.

The recruitment funnel, mechanically, looks something like this. A trial protocol is approved by an IRB, registered on ClinicalTrials.gov, and assigned to one or more clinical sites. Each clinical site has a study coordinator (or shares a coordinator across multiple trials) who is responsible for recruitment within the site's catchment area. The coordinator's tools are: a recruitment plan (often slightly aspirational), a list of inclusion and exclusion criteria (often dozens of items, some of which require labs or imaging the patient may not have recent results for), an EHR query the site's research informatics team may or may not have built, a social-media outreach plan that may or may not be funded, a community-outreach plan that may or may not have a budget, a recruitment-call-center plan that may or may not be in place, and a referring-clinician outreach plan that often consists of telling the local primary-care and specialty offices that the trial exists. The coordinator then has to convert raw interest into screened patients into consented patients into randomized patients, with attrition at every stage of the funnel that is, on average, much higher than the recruitment plan assumed. 

The conversation that has to happen, between the coordinator and the prospective participant, is structurally hard. The coordinator has to: communicate what the trial is studying, in language that is faithful to the IRB-approved protocol but accessible to a patient without a clinical degree; explain why the patient might be a candidate; walk through the high-level inclusion and exclusion criteria to identify obvious disqualifiers without spending forty minutes on a patient who is going to fail screening; capture the medical-history and medication information needed for the prescreen; describe the visit schedule, the study procedures, the placebo arm if there is one, and the time commitment, in a way that gives the patient a realistic picture of what participation actually involves; answer the patient's questions about safety, payment, transportation, time off work, and family logistics; maintain absolute discipline about not crossing the line from "explaining the trial" to "recommending the trial" or "advising the patient on whether to participate"; and do this in a manner that is also welcoming, respectful, and reflective of the patient's lived context, because patients who feel rushed or condescended to do not enroll. The conversation is supposed to be the patient's first sample of what their interaction with the research team will be like across the full trial; it is also the gating step that determines whether they will ever hear from the research team again.

Coordinators are very good at this conversation. They are also expensive, finite, and concentrated in academic medical centers. The supply of coordinators in the U.S. is well below the demand created by the volume of active trials, and the trials that disproportionately fail to enroll are the trials in conditions and populations and geographies where the coordinator supply is thinnest. The patients who are disproportionately not reached are the patients in the smaller communities, the patients who are not already established at academic medical centers, the patients without nearby specialists, the patients in racial and ethnic minority populations historically underrepresented in clinical research, the patients in lower-income populations, the patients with limited English proficiency, the patients who work shifts that conflict with research-coordinator office hours, and the patients without the kind of social capital that makes navigating research-coordinator workflows feel routine.  The trials that suffer most are the trials in conditions disproportionately affecting these populations and the trials whose generalizability depends on enrolling representative populations.

The thing the recruitment funnel needs is not faster coordinators. The thing it needs is the equivalent of a coordinator's first-pass screening conversation, available across the recruitment population at population scale, anchored in the IRB-approved protocol and recruitment language, faithful to the trial's eligibility criteria, capable of capturing the medical-history and medication information needed for the prescreen, capable of routing the qualified prospects to the human coordinator with the prescreen already done and the patient already informed about the trial, and capable of doing all of this in the languages and on the channels that match the patient population the trial is trying to reach. Such a thing has to satisfy the IRB. It has to satisfy the trial sponsor's regulatory team. It has to satisfy the institution's research-compliance office. It has to satisfy the patient. It has to satisfy the coordinator who will pick up the conversation on the other side. And it has to do all of this without crossing the line into recommending participation or coercing the patient.

This is the central problem the clinical trial recruitment conversationalist is built to solve, and it is a problem that exists at the intersection of several categories of regulatory and clinical-operations exposure that none of the previous recipes in this chapter has fully encountered together. It is more conservative than the symptom-checker triage bot (recipe 11.6) because the IRB is a layer of governance the triage bot does not have. It is more structured than the chronic disease management coach (recipe 11.7) because the recruitment conversation is bounded by a specific protocol, not an open-ended condition-management arc. It is closer in regulatory feel to the mental-health support bot (recipe 11.8) because the consequences of crossing scope lines are serious. And it is closer in architectural pattern to the care coordination assistant (recipe 11.9) because the conversation is deeply tied to longitudinal patient context and to a downstream human workflow. It also has a distinctive layer of complexity not present in any of those: the entire interaction has to be faithful to a specific, IRB-approved, written-and-version-controlled trial protocol, and the IRB-approved recruitment language is the only language the assistant is permitted to use about that trial.

A few things this recipe is and is not.

It is the assistant that has the recruitment conversation. The patient (or a caregiver or family member acting on the patient's behalf with appropriate authorization) interacts with the assistant via web chat, in-app messaging, SMS, or voice, learns about a trial they may be a candidate for, walks through a structured prescreen that surfaces obvious disqualifiers and captures the medical-history and medication information the coordinator needs, has their questions about the trial answered using the IRB-approved recruitment FAQ, and (if they remain interested and the prescreen does not produce a hard disqualifier) is connected to a human research coordinator with their prescreen results and their stated questions captured. The assistant covers the front of the recruitment funnel.

It is not the informed consent process. Informed consent for clinical research is a specific, regulated activity governed by 21 CFR Part 50, the ICH E6 Good Clinical Practice guidelines (updated to R3 in 2025 with risk-based and quality-by-design framing relevant to recruitment-platform deployments), the IRB-approved consent form, and (in many jurisdictions) state-specific provisions. Where the trial is FDA-regulated, the assistant's recruitment material is part of the IND or IDE record, and the recruitment platform's audit trail is subject to 21 CFR Part 11 electronic-record-and-signature requirements.

The assistant does not collect informed consent. The assistant captures the patient's interest, surfaces the IRB-approved recruitment information, and routes the qualified-and-still-interested patient to the human coordinator who runs the consent process per the IRB-approved consent procedure.

It is not a trial-matching tool that recommends trials to a patient. The assistant operates within a specific recruitment context: the patient is engaging because they have been routed to a specific trial (or a small list of trials in a specific therapeutic area), typically through their treating clinician's referral, through a sponsor's recruitment channel, or through the institution's research-recruitment infrastructure. Trial-matching across a registry of all open trials is a different, related problem with different regulatory considerations.

It is not a clinical-decision tool. The assistant does not diagnose. The assistant does not adjust the patient's clinical care. The assistant does not opine on whether the patient should join the trial. The assistant explains, screens, and routes. This positioning as a non-device informational tool depends on the assistant staying on the correct side of the FDA Clinical Decision Support boundary defined in Section 3060 of the 21st Century Cures Act and the FDA's CDS guidance; the moment the assistant strays into condition-specific recommendations or decision logic that the prospective participant is not expected to independently review, the regulatory classification changes materially.

It is not a substitute for the human research coordinator. The coordinator runs consent. The coordinator runs the visit. The coordinator handles the questions that fall outside the IRB-approved recruitment FAQ. The coordinator stewards the long-running relationship with the participant. The assistant handles the front of the funnel that human coordinators cannot reach at population scale.

It is not a one-size-fits-all product. A recruitment conversationalist for a phase 1 oncology trial in a refractory population is different from one for a phase 4 post-marketing trial in a primary-care population. A recruitment conversationalist for a healthy-volunteer trial is different from one for an inpatient acute-care trial. A recruitment conversationalist for a decentralized trial is different from one for a site-based trial. A recruitment conversationalist for a pediatric trial is materially different in identity, consent, and assent posture from one for an adult trial. Most institutions deploy a multi-trial recruitment architecture with per-trial protocol content layered on a shared recruitment-conversation core.

It is not a regulatory afterthought. Patient-facing recruitment software is part of the trial's regulatory artifact. The IRB reviews the assistant's recruitment script, the prescreen flow, the FAQ content, and the routing logic the same way it reviews any other recruitment material. The trial sponsor's regulatory team is involved. Where the trial is FDA-regulated, the assistant's recruitment material is part of the IND or IDE record. Where the trial involves international sites, regional regulatory frameworks (EU CTR, MHRA in the UK, PMDA in Japan, NMPA in China, and others) may apply. The assistant's operational change-management process is institutional.

It is not a quick win. The deployment timeline is measured in quarters, with per-trial onboarding measured in weeks to months once the platform is mature. The trial-content authoring is multi-week per trial. The IRB-review process is multi-week per trial. The coordinator-workflow integration is multi-week per site. The post-launch monitoring is continuous. Institutions building this expecting fast time-to-value are usually disappointed.

The thing to understand before building this is that the assistant's value is not measured in conversations completed. The value is measured in qualified-and-consented enrollments delivered to the coordinator team, in equitable representation across the population segments the trial is trying to reach, in coordinator time freed for the high-value work coordinators uniquely do, in trial timelines met without quality compromise, and in patient experience that does not feel like the recruitment process is treating them as a recruitment metric. An assistant evaluated on conversation volume will be optimized for the wrong thing. An assistant evaluated on prescreen yield, coordinator time saved, demographic representation, qualified-handoff accept-rate, and patient-and-caregiver-reported recruitment experience is being evaluated correctly, and the architectural decisions follow from there.

Let's get into it.

---

## The Technology: IRB-Grounded Conversational Recruitment With Strict Protocol Faithfulness, Eligibility Screening, and Coordinator Handoff

### Why Clinical-Trial Recruitment Has Resisted Digital Tools

Clinical-trial recruitment has been a poster-with-tear-off-tabs and paid-per-click problem for several decades. The reason is structural. Recruitment software has to be faithful to a specific IRB-approved protocol, has to use only IRB-approved recruitment language, has to enforce a specific eligibility-criteria evaluation, has to integrate with the site's research-coordinator workflow and the sponsor's recruitment-tracking systems, has to handle the specific consent and assent considerations of the trial (adult versus pediatric, surrogate-decision-maker scenarios, vulnerable populations), and has to do all of this without producing recruitment communication the IRB has not reviewed. Generic patient-engagement software does not satisfy the IRB. Generic conversational software does not maintain protocol faithfulness. Generic eligibility-screening software does not handle the depth and the per-trial specificity of inclusion and exclusion criteria. The earlier generations of digital recruitment tools (online prescreens, web forms, email blasts, social-media campaigns) addressed parts of the problem but did not handle the conversation that has to happen between the patient and the recruitment process before the human coordinator picks up.

The first generation of digital recruitment tools, roughly the early 2010s, focused on web-form-based prescreens and email-and-SMS blast campaigns. The patient would see a recruitment ad (online, on social media, in print), click through to a web form, answer a series of yes/no and multiple-choice questions, and receive an automated response saying either "you appear to qualify, a coordinator will contact you" or "you do not appear to qualify, thank you for your interest." The form-based approach worked for the simplest trials with simple eligibility criteria, did not work well for trials with complex eligibility requiring history and medication context, did not handle the patient's questions, did not give the coordinator a meaningful prescreen result, and did not engage the patient as a person. The conversion from form-completion to consent was, in the published literature, often disappointing. 

The second generation, roughly 2015 to 2020, introduced more sophisticated patient-portal-based recruitment with EHR-integration prescreens (the EHR queries identifying potentially eligible patients automatically, with patient-facing portal invitations to review trial information), social-media-driven recruitment with sponsor-funded ads driving prospective participants to landing pages, and sponsor-funded patient-recruitment vendors operating call centers with structured scripts. The clinical evidence for these approaches showed that EHR-integration helped where the EHR query was well-designed and the catchment population was well-instrumented, that social-media-driven recruitment helped at the top of the funnel but produced a meaningfully higher fall-out rate downstream, and that call-center-based recruitment helped where the call-center workforce was well-trained on the specific trial.  The structural limitation remained: patients still wanted to talk to someone before deciding to enroll, and the someone was still a finite human research coordinator.

The thing that changed the workflow shape is, again, large language models that can hold a structured, protocol-grounded conversation with a prospective participant, walk through eligibility criteria conversationally rather than as a form, answer the patient's questions using the IRB-approved FAQ content, and route the qualified-and-still-interested patient to the human coordinator with the prescreen already done. The recruitment conversationalist, deployed with careful institutional governance, can hold the front-of-funnel conversation that the human coordinator would have held, can do so at population scale across the channels the trial's target population uses, can capture the prescreen information the coordinator would have captured, and can do so with the IRB and the sponsor's regulatory team's approval. The LLM is not a coordinator. The LLM is, in the right product design, a tool that lets recruitment workflows that have historically required dedicated coordinator phone time operate at the scale and reach the recruitment plan actually requires.

The architectural shift is from "form-based prescreen plus call-center scripts" to "protocol-grounded conversational prescreen with strict IRB-approved language, eligibility-criteria evaluation, FAQ retrieval, and coordinator handoff." The assistant's value is concentrated in three places: the IRB-grounded recruitment conversation (turning the structured trial information into accessible, faithful, protocol-compliant patient-facing language at population scale), the conversational eligibility prescreen (capturing the medical-history and medication information the coordinator would otherwise spend forty minutes on), and the qualified-and-warm handoff (delivering the prescreened, informed, still-interested prospect to the coordinator with the conversation context attached).

### What a Clinical Trial Recruitment Conversationalist Actually Does

A recruitment conversationalist is a tool-using LLM with a system prompt that tells it which assistant it is, the active trial context (IRB-approved protocol summary, IRB-approved recruitment language, IRB-approved FAQ content, eligibility criteria, visit schedule summary, study procedures summary, sponsor-and-investigator information, IRB-and-protocol identifiers), the patient's authenticated context where available (referral source, demographic basics, language preference), access to a structured library of recruitment protocols (the institution's general recruitment-conversation patterns layered with the trial-specific content), and a careful set of tools for retrieving trial information, evaluating eligibility, capturing prescreen data, scheduling coordinator handoff, surfacing seam-flags, and escalating when the conversation crosses scope.

The conversation surface is bounded. Unlike the longitudinal coordination assistant, the recruitment conversation is typically a single session or a small number of sessions. Unlike the chronic disease coach, the recruitment conversation has a defined endpoint (qualified-handoff to coordinator, declined-by-patient, or screen-failed-by-eligibility). Unlike the mental-health support bot, the recruitment conversation does not establish a long-term relationship; the coordinator establishes the long-term relationship if the patient enrolls.

The assistant's task surface decomposes roughly as follows.

**Entry from a referral source with appropriate context.** The patient enters the recruitment conversation through one of several routed paths: a referral from their treating clinician (usually with a specific trial in mind), a sponsor's recruitment channel (social media, search ads, sponsor recruitment website), a clinical-trials registry-driven path (ClinicalTrials.gov listing leading the patient to the institution's recruitment portal), an EHR-integrated prescreen-invitation path (the EHR has identified the patient as potentially eligible and the institution has invited them to learn more), or an institutional research-recruitment landing page. The entry path determines what the assistant knows about the patient at the start of the conversation.

**Trial-specific context loading and disclosure.** The assistant loads the IRB-approved recruitment context for the specific trial: the protocol summary in IRB-approved language, the eligibility criteria in IRB-approved language, the recruitment-FAQ entries in IRB-approved language, the visit-schedule summary, the study-procedure summary, the IRB and protocol identifiers, the principal investigator and sponsor information, and the institutional contact information. The first conversation-turn includes the disclosures the IRB has required: the assistant is a chat tool not a person, the assistant is not the research coordinator, the assistant cannot enroll the patient, the assistant is providing information about the trial and conducting a preliminary screen, the patient can stop at any time, the patient's information will be stored per the institutional research-data policy, and the patient can ask to speak to a research coordinator at any point.

**Patient-question-handling using IRB-approved FAQ retrieval.** The patient typically has questions before they want to engage with the prescreen. What is the trial studying? Who is the sponsor? Where will the visits be? How long is the trial? What are the procedures? Is there a placebo arm? What are the risks? What are the benefits? What is the time commitment? Will my expenses be covered? Can I stay on my current medications? What if I want to stop? The assistant answers these from the IRB-approved FAQ corpus with strict citation grounding; if the question falls outside the IRB-approved FAQ, the assistant routes the question to the coordinator rather than improvising.

**Conversational eligibility prescreen.** The assistant walks through the inclusion and exclusion criteria conversationally, in the patient's language, at the patient's pace. The criteria are categorized: simple structured criteria (age, sex, language, geography, basic diagnosis presence) that the assistant can evaluate from the conversation; complex structured criteria (specific lab values, specific medication histories, specific imaging findings) that the assistant captures as "patient-reported" with explicit caveat that the coordinator will verify; clinical-judgment criteria (severity, prognosis, comorbidity context) that the assistant flags as "for coordinator review" and captures the patient's report as input rather than as a determination. The prescreen produces a structured result: clearly-disqualified (a hard exclusion is met), uncertain-pending-coordinator-verification (the patient appears potentially eligible but verification is needed), or clearly-eligible-pending-coordinator-confirmation (the patient meets the simple criteria with high confidence and the coordinator's role is confirmation rather than determination).

**Prescreen-result delivery to the patient.** The assistant communicates the prescreen result to the patient in the IRB-approved language. Where the patient is clearly-disqualified, the assistant explains in plain language what the disqualifying criterion was (without revealing protocol-confidential information beyond what the IRB has approved for participant communication), thanks the patient for their interest, and where institutional policy permits offers to refer them to other open trials they may be eligible for or to general resources for their condition. Where the patient is uncertain-pending or clearly-eligible-pending, the assistant explains that a research coordinator will follow up to verify and walk them through next steps.

**Coordinator-handoff orchestration.** Where the patient is clearly-eligible-pending or uncertain-pending and the patient remains interested, the assistant orchestrates the handoff: captures the patient's preferred follow-up channel and time, generates a structured prescreen summary for the coordinator (with the patient-reported information clearly tagged as patient-reported and with the assistant's eligibility assessment clearly tagged as preliminary), schedules the handoff in the coordinator's queue, confirms the handoff arrangement with the patient, and sets expectations about the timing of follow-up and what the next conversation will look like.

**Equity-and-representativeness instrumentation.** The assistant captures (with the patient's consent and per the IRB-approved data-collection plan) the demographic information the trial sponsor and the institution use to monitor recruitment representativeness: language, race and ethnicity (per OMB categories with patient-self-report), sex and gender, age cohort, geography, insurance status, social-determinants flags. The data is used for per-cohort recruitment-funnel monitoring and for early detection of under-recruitment in target populations.

**Sensitive-topic handling within recruitment scope.** The assistant handles, within scope, the topics that often arise in recruitment conversations: financial concerns about trial participation (the assistant retrieves IRB-approved language about reimbursement, travel, lost-wages compensation per the trial's specific provisions), transportation-and-logistics concerns, family and caregiver involvement, fear of investigational therapy (the assistant retrieves IRB-approved language about safety monitoring without making safety claims), mistrust of clinical research (the assistant acknowledges with calibrated language reviewed by patient-advocate consultants, community-research-engagement teams, and IRB), and religious or cultural considerations (with culturally-appropriate language reviewed by the institution's community-research-engagement teams where applicable).

**Continuous emergency screening across every utterance.** Same as the previous bots in this chapter. The assistant routes acute emergencies (chest pain, suspected stroke, severe symptom presentations, suicidal ideation) immediately to the appropriate emergency pathway; the assistant does not try to handle acute emergencies in conversation, and the assistant pauses the recruitment conversation to handle the safety event.

**Out-of-scope routing.** Topics outside the recruitment scope (clinical questions about the patient's existing care, requests for medical advice, requests to enroll without prescreen, attempts to recruit in violation of the IRB-approved process) route to the appropriate alternative pathway: the patient's existing care team, the institutional patient-services line, the research-compliance office, or 911 as appropriate.

**Per-conversation audit, IRB-grade record retention, and post-conversation reporting.** Every conversation is captured in a durable record with model and prompt versions, IRB-approved-content versions, prescreen-result, handoff disposition, and timestamps. The records are retained per the institutional research-data-retention policy and per the trial's specific retention requirements.

### Why a Generic LLM Cannot Run a Clinical Trial Recruitment Conversationalist

A naive product approach would be: take a generalist LLM, give it a chat surface, paste in the trial's protocol, and have it talk to prospective participants. This breaks in several specific ways, each of which has clinical, regulatory, and operational consequences.

**The model has no theory of IRB-approved recruitment language.** The IRB approves specific language that may be used in patient-facing recruitment communication. Language outside the approved set is, by definition, unapproved. A generalist LLM produces fluent, plausible-sounding recruitment language that is not the IRB-approved language, which means the assistant is producing recruitment communication the IRB has not reviewed, which is a regulatory finding waiting to happen. The architectural primitive is strict citation grounding in the IRB-approved corpus, with the LLM permitted only to retrieve and surface approved content rather than generating novel recruitment language.

**The model has no theory of eligibility-criteria depth.** Eligibility criteria are typically written in clinical language with implicit assumptions about how each criterion is evaluated. "Hemoglobin A1c between 7.5 and 10.0 within the past 90 days" requires a specific interpretation rule. "No active malignancy other than non-melanoma skin cancer" requires a specific definition of "active." "Stable on current diabetes medication regimen for at least 90 days" requires definitions of "stable" and "current regimen." The LLM does not naturally enforce these definitions; the eligibility-evaluation subsystem encodes them deterministically with named clinical-leadership ownership per criterion.

**The model hallucinates trial information when grounding is weak.** If the IRB-approved trial corpus is not retrieved with strict citation grounding, the LLM produces plausible-sounding trial information that is wrong for the specific trial. The trial summary may differ from the protocol. The visit schedule may be approximated. The risks may be understated. The benefits may be overstated. The assistant becomes a source of unreviewed trial communication, which the IRB does not allow.

**The model has no theory of staying within scope.** Patients in recruitment conversations frequently ask clinical questions about their existing care ("should I be worried about this lab value the trial requires me to know?"), advice questions about whether to enroll ("do you think this trial is right for me?"), and questions about the patient's overall situation that go beyond the recruitment context. The assistant's scope is bounded; the LLM does not naturally enforce the boundary, the architecture does.

**The model has no theory of assent versus consent versus surrogate-decision-maker.** Pediatric trials require parental permission and pediatric assent; adult trials require informed consent; trials involving cognitively-impaired or incapacitated populations require surrogate-decision-maker consent. The assistant's recruitment conversation has different participants and different obligations across these scenarios; the architecture distinguishes them explicitly.

**The model has no theory of vulnerable populations.** Federal regulations (45 CFR 46 Subparts B, C, D for pregnant women, prisoners, and children respectively) impose additional protections for specific populations. FDA's diversity-action-plan guidance also explicitly names older adults, pediatric populations, pregnant patients, and patients with disabilities as historically underrepresented populations requiring deliberate recruitment attention. The LLM does not enforce these; the architecture enforces them through institutional policy and through the IRB-approved recruitment plan for the specific trial.

**The model has clinical-decision-rule arithmetic problems.** Eligibility evaluation includes time-window calculations (was the lab value within the required window?), arithmetic comparisons (does the BMI fall within range?), unit conversions (the patient may report HbA1c in different units), date arithmetic (how long since the last episode?), and similar structured arithmetic. The LLM does this poorly. The deterministic eligibility-evaluation tools encapsulate the computation.

**The model has no theory of trial-status state.** Trials open and close enrollment. Trials add or remove sites. Trials amend their protocols (and the IRB approves or rejects the amendments). The recruitment context for a specific trial today is not necessarily the recruitment context for that trial three months from now. The trial-state system tracks this; the assistant retrieves the current state for every conversation.

**The model has no theory of what to do when the patient is in distress.** Patients in recruitment conversations are sometimes patients facing serious illness, recent diagnoses, or progressive disease. The conversation can surface emotional distress, fear, or existential concerns. The assistant is not a counselor; the assistant acknowledges with calibrated language and routes to appropriate support resources where the patient indicates they would like one. The boundary between "warm acknowledgement" and "in-scope counseling" is well-defined.

**The model has no theory of relationship to the existing care team.** Patients in recruitment conversations have existing clinical relationships that may or may not be informed about the patient's interest in the trial. The recruitment conversation does not communicate with the patient's care team without explicit patient consent and per the IRB-approved data-sharing plan. The architectural distinction between "research-data" and "clinical-care-data" is enforced.

**The model has compliance implications specific to recruitment data.** Recruitment-conversation content is research data under HIPAA's research provisions and under 45 CFR 46. The retention, access-control, audit, and post-conversation-handling story is research-grade, distinct from the clinical-care PHI handling. The architecture maintains the distinction.

**The model has no theory of representativeness monitoring.** A trial's recruitment performance includes not just total enrollment but representation across demographic and clinical strata. Per-cohort monitoring of the recruitment funnel (entry to prescreen-completion to coordinator-handoff to consent to randomize) is a regulatory expectation in many trials and a scientific expectation in all of them.  The instrumentation is part of the recruitment platform.

**The model has no theory of coordinator-handoff quality.** A handoff that includes incomplete prescreen data, that misrepresents the patient's situation, that omits the patient's stated preferences, or that arrives in a format the coordinator cannot use is a handoff that the coordinator workflow rejects. The handoff format, content, and routing are designed jointly with the coordinator team.

**The model has no theory of trial-comparability when multiple trials are in scope.** Where the institution has multiple open trials in a therapeutic area, a patient may be a candidate for more than one. The assistant has to handle the multi-trial scenario carefully: discussing one trial at a time, offering the patient information about others if institutional policy permits and the patient asks, and avoiding any framing that compares trials in a way that constitutes recommendation.

### What the Recruitment Conversationalist Has To Do That the Previous Bots Did Not

Recipes 11.1 through 11.9 established the patterns this recipe inherits: input safety screening with continuous emergency screening, identity verification, tool-use orchestration, output safety screening, audit logging, per-cohort monitoring, scope discipline, prompt-injection defense, graceful degradation, longitudinal-context loading, citation grounding, crisis-pathway routing. The recruitment conversationalist adds eight structural commitments those recipes did not have.

**IRB-approved-content corpus as the only allowed source of trial-specific language.** The assistant's trial-specific output is grounded in IRB-approved content with strict citation. The architecture does not permit the LLM to produce novel trial-specific recruitment language; the IRB-approved corpus is the only source.

**Per-trial protocol-specific context loading and per-trial isolation.** The assistant operates on one trial at a time. The system prompt is parameterized per trial, the IRB-approved corpus is per-trial, the eligibility-evaluation rules are per-trial, the FAQ content is per-trial. The architecture isolates trial-specific content so that content from one trial cannot leak into a conversation about another.

**Eligibility-evaluation engine with deterministic per-criterion logic and named clinical-leadership ownership.** Eligibility criteria are encoded as deterministic rules where possible and as flagged-for-coordinator items where clinical judgment is required. Each rule has named clinical-leadership ownership, version history, and IRB-review evidence.

**Coordinator-handoff orchestration as production scope.** The qualified-handoff to the coordinator team is part of the production architecture: the structured prescreen summary, the coordinator-queue routing, the patient-confirmation of handoff, and the timing-of-follow-up commitment. The coordinator team's workflow is co-designed; deploying without coordinator-team involvement produces an assistant the coordinator team does not use.

**Trial-state and trial-amendment tracking.** The trial-state system tracks open or closed status, site enrollment status, IRB-amendment status, and recruitment-pause status. The assistant retrieves the current trial-state for every conversation; conversations about closed-or-paused trials route appropriately.

**Representativeness instrumentation per trial and per recruitment cohort.** The recruitment funnel is instrumented per demographic stratum, per referral source, per geography, per language, and per other dimensions specified in the trial's recruitment plan. Per-cohort dashboards are reviewed by the principal investigator, the institutional research-recruitment team, the sponsor's recruitment team, and (where the trial is FDA-regulated) the diversity-action-plan-tracking team.

**Vulnerable-populations-aware identity model.** The identity layer distinguishes adult-self-decision, parental-permission-and-pediatric-assent, and surrogate-decision-maker scenarios. The architecture is designed for the adult-baseline pattern and is extended for pediatric or surrogate scenarios as the institutional protocol requires.

**Research-data-as-distinct-record-class with research-grade retention.** Recruitment-conversation content is stored as research data, with retention per the institutional research-data-retention policy, with access controls per the institution's research-data-access policy, and with an audit trail that supports IRB and regulatory inspection.

The rest is largely the same as the previous chapter 11 recipes: tool-surface contract management, identity-assurance lifecycle, conversation logging, scope filtering, per-cohort monitoring, graceful degradation when upstream systems fail.

### The Recruitment Reality

A few notes on what makes clinical-trial recruitment specifically harder than the previous patient-facing bot use cases.

**The IRB is an active participant in product development.** The institutional IRB reviews the recruitment script, the prescreen flow, the FAQ content, the routing logic, the data-collection plan, and the consent language. Any change to patient-facing content requires IRB review (or, where the change is within the previously-approved scope, an institutional-policy assessment). The architecture and the change-management process are designed for IRB-grade governance from day one.

**The trial sponsor is also an active participant.** The trial sponsor's regulatory and clinical-operations teams are involved in the recruitment platform's content review for sponsor-funded trials. The sponsor's recruitment plan, diversity action plan, and recruitment-vendor agreements may impose additional requirements.

**The recruitment funnel is the metric, not the conversation count.** Conversations completed is a vanity metric. Qualified-handoffs accepted, prescreen-yield-by-cohort, coordinator-time-saved, and ultimately consented-and-randomized-participants-by-cohort are the substantive metrics. The instrumentation is per-cohort across the full funnel, with the longest-window outcomes (consented, randomized) reported as the trial accumulates them.

**Demographic representativeness is a regulatory and a scientific obligation.** FDA guidance on diversity action plans for FDA-regulated trials, codified by FDORA Section 3601 in 2022 and operationalized through the FDA's 2024 final guidance on Diversity Action Plans, has raised the operational bar for measuring and improving recruitment representativeness. The recruitment platform's per-cohort monitoring is designed to detect under-recruitment in target populations (including racial and ethnic minorities, older adults, pediatric populations, pregnant patients, patients with disabilities, low-income populations, patients with limited English proficiency, and rural populations) and to support the sponsor's diversity-action-plan reporting.

**Equity considerations cut deep.** Recruitment platforms reach disproportionately the patients who are already plugged in to the digital-tool ecosystem. The patients with the greatest unmet research-participation opportunity are often the patients with the most limited access to digital tools, the most limited integration with the connected data sources, the most limited English proficiency, the most limited transportation flexibility, the most limited paid-time-off access, and the most limited established relationships with academic medical centers. The platform's reach into these populations is a deliberate design and operational commitment, not a default.

**Protocol amendments are routine.** Trials amend their protocols. Eligibility criteria change. The IRB approves or rejects amendments. The recruitment platform tracks amendment status, applies the approved amendments to the active trial-context, and (where amendments materially change recruitment communication) re-presents the updated information to in-flight prospective participants per the IRB-approved process.

**Protocol confidentiality is real.** Trial protocols are typically confidential between the sponsor, the investigator, and the IRB. The patient-facing recruitment communication is a deliberately-curated subset reviewed and approved by the IRB. The assistant's content boundary is the IRB-approved recruitment content; protocol material outside that boundary is not surfaced.

**Coordinator capacity is a hard constraint.** The downstream coordinator team has finite capacity. A recruitment platform that delivers more qualified handoffs than the coordinator team can absorb produces patient-experience problems (long delays in coordinator follow-up, patient-loss-of-interest during the wait) and trial-operations problems (handoffs aging in the queue, prescreens going stale). The platform's throughput is calibrated to the coordinator team's capacity, with smooth flow rather than burst-and-wait dynamics.

**The relationship to the clinician referral path is structural.** Many recruitment programs depend heavily on treating clinicians referring their patients to specific trials. The platform supports the clinician-referral pathway with clinician-side tooling that communicates the trial's eligibility criteria and patient-fit considerations to the clinician at the right moment in the visit, and that warm-routes the patient to the recruitment conversationalist with the clinician's referral context attached.

**Site-specific operations matter.** Even within a single multi-site trial, individual sites have different coordinator workflows, different referral-source mixes, different patient populations, and different operational realities. The platform supports per-site operational configuration without forking the trial-content corpus.

**Decentralized-and-hybrid trials change the architecture.** Some trials are entirely site-based; some are decentralized (visits at home or via telehealth); some are hybrid. The recruitment conversationalist's eligibility prescreen, the coordinator handoff, the visit-schedule communication, and the logistics-and-transportation language differ across these trial designs.

**Pediatric, vulnerable-population, and surrogate-decision-maker scenarios change the identity model.** Where the trial enrolls minors, the parent or guardian is the primary recruitment-conversation participant with the child's assent collected per the IRB-approved process; where the trial enrolls cognitively impaired adults, the surrogate decision maker is the primary recruitment-conversation participant; where the trial enrolls populations with additional federal protections (pregnant women under Subpart B, prisoners under Subpart C, children under Subpart D), the additional protections are operationalized.

**Outcome demonstration takes the entire trial timeline.** The platform's effect on prescreen-yield can be measured in weeks to months. The effect on coordinator time saved can be measured in months. The effect on consented and randomized enrollments accumulates across the trial's enrollment period (often 12 to 36 months). The effect on representativeness accumulates similarly. The effect on trial timelines met versus missed is observable when the trial closes enrollment. Institutions building this expecting per-trial validation in a single quarter will be disappointed; institutions willing to invest at the right time horizon can demonstrate measurable improvements across a portfolio of trials.

**The relationship to existing patient-recruitment vendors is structural.** Sponsor-funded trials often have existing patient-recruitment vendor partnerships with their own platforms, their own call centers, and their own contractual obligations. The institutional recruitment conversationalist may complement, replace, or coexist with these vendor relationships. The relationship model is negotiated per trial.

**Trial portfolios accumulate.** A mature institutional research-recruitment platform serves dozens to hundreds of active trials across therapeutic areas, with new trials onboarded continuously and old trials closed continuously. The trial-onboarding workflow (IRB-approved content authoring, eligibility-rule encoding, FAQ population, coordinator-team training, post-launch monitoring) is institutional content, with named operational ownership per trial.

### Where the Field Has Moved

A few practical updates worth knowing.

**Decentralized clinical trials have changed the recruitment surface.** Decentralized and hybrid trial designs, accelerated by the operational adaptations of 2020-2022, have expanded the potential reach of trials beyond academic-medical-center catchment areas to broader geographic populations. The recruitment platform can engage prospective participants who live far from the nearest site.  The recruitment-platform reach is calibrated accordingly.

**Diversity action plans are increasingly formalized.** FDA guidance on diversity action plans for FDA-regulated trials, codified by FDORA Section 3601 in 2022 and operationalized through the FDA's 2024 final guidance, has raised the operational bar for measuring and improving recruitment representativeness. Per-cohort recruitment-funnel monitoring is no longer a "nice to have"; for some trial categories it is regulatory expectation.

**ClinicalTrials.gov and trial-listing infrastructure has matured.** ClinicalTrials.gov registration is required for most NIH-funded and FDA-regulated trials, and the listings have become a primary patient-facing entry path for trial discovery.  The recruitment platform's integration with ClinicalTrials.gov listings (and with downstream patient-facing trial-discovery products) is part of the architectural surface.

**Tool-using LLMs handle recruitment conversations well when grounded carefully.** The function-calling pattern from the previous chapter 11 recipes maps to recruitment work. The LLM produces tool calls that retrieve trial information, retrieve FAQ content, evaluate eligibility, capture prescreen data, schedule coordinator handoff, and post events for downstream operations.

**Hybrid AI-plus-coordinator recruitment is the dominant production pattern.** Most major deployments run a hybrid model: the assistant for the front-of-funnel conversation and prescreen, with human coordinators for consent, complex-eligibility verification, and the long-running participant relationship. The economics work because the assistant absorbs the repetitive front-of-funnel work while the coordinator focuses on the high-value coordinator-only work.

**Outcome demonstration is positive for hybrid models.** Studies and case reports of digital-plus-human recruitment programs have shown improvements in prescreen yield, coordinator time saved, recruitment timeline adherence, and (in some cases) representativeness.  The ROI demonstrations are stronger when the analysis includes representativeness improvement and trial-timeline adherence than when it focuses only on conversation volume.

**Build-vs-buy is mature for some recruitment segments.** Several mature commercial vendors offer recruitment platforms with FAQ-bot capabilities, eligibility-prescreen tools, and coordinator-handoff infrastructure. Most major institutions running sizable trial portfolios run a hybrid: build a thin orchestration layer in-house on the institution's preferred infrastructure, partner with vendors for specific trial-recruitment campaigns where vendor capability is strong, and integrate with the institution's research-recruitment, IRB, and coordinator workflows.

**Equity-and-representativeness work is an active area of investment.** Recruitment platforms are investing in multilingual content, low-literacy content adaptations, channel diversification (SMS, voice, in-person kiosk options), partnerships with community-based organizations, and per-cohort outcome monitoring with explicit equity targets.

---

## General Architecture Pattern

A clinical trial recruitment conversationalist decomposes into ten logical stages: input safety screening with continuous emergency screening; identity verification with vulnerable-populations-aware posture; trial-context loading with trial-state-and-amendment tracking; tool-use loop with IRB-citation discipline; conversational eligibility prescreen with deterministic per-criterion logic and clinical-judgment routing; output safety with IRB-language faithfulness verification; coordinator handoff orchestration with throughput control; per-cohort representativeness instrumentation with launch-gate discipline; recruitment-decision record persistence with research-grade retention; per-trial reporting and outcome correlation across the recruitment funnel. The cross-cutting concerns from recipes 11.1 through 11.9 carry forward; this recipe adds eight new ones (IRB-approved-content corpus as only allowed source of trial-specific language, per-trial protocol-specific context loading and isolation, eligibility-evaluation engine with deterministic per-criterion logic and named clinical-leadership ownership, coordinator-handoff orchestration as production scope, trial-state and trial-amendment tracking, representativeness instrumentation per trial and per recruitment cohort, vulnerable-populations-aware identity model, and research-data-as-distinct-record-class with research-grade retention).

```text
┌────────── INPUT SAFETY + CONTINUOUS EMERGENCY SCREEN ────┐
│                                                           │
│   [Standard input safety primitives from recipe 11.1]     │
│    - Prompt-injection detection                           │
│    - PHI minimization                                     │
│    - Self-harm and crisis classifier                      │
│                                                           │
│   [Recruitment-specific continuous emergency screening]   │
│    - Runs on every prospective-participant utterance      │
│    - Detects acute-emergency presentations (chest pain,   │
│      severe shortness of breath, suspected stroke,        │
│      suicidal ideation, overdose)                         │
│    - Detects recruitment-specific acuity scenarios:       │
│      prospective participants who surface decompensating  │
│      symptoms; participants who report a recent           │
│      condition change during eligibility prescreen;       │
│      participants whose conversation surfaces             │
│      psychosocial crisis the recruitment platform is not  │
│      equipped to handle                                   │
│    - Triggers immediate routing to 911, 988, or           │
│      institutional crisis line as appropriate             │
│           │                                               │
│           ▼                                               │
│   [Output: input passes / input blocked / emergency       │
│    routed]                                                │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── IDENTITY VERIFICATION + POPULATIONS POSTURE ───┐
│                                                           │
│   [Authenticated session or anonymous entry]              │
│    - Portal-authenticated patient (EHR-linked referral)   │
│    - Anonymous entry (sponsor recruitment channel,        │
│      ClinicalTrials.gov landing page, social-media ad)    │
│    - Caregiver or family-member entry with appropriate    │
│      authorization                                        │
│                                                           │
│   [Vulnerable-populations-aware identity classification]  │
│    - Adult self-decision (baseline)                       │
│    - Parent or guardian for pediatric participant         │
│      (assent and parental permission per 45 CFR 46       │
│      Subpart D)                                           │
│    - Surrogate decision maker for cognitively impaired    │
│      adult                                                │
│    - Protected-population flags (pregnant patients under  │
│      Subpart B, prisoners under Subpart C, children       │
│      under Subpart D, older adults, patients with         │
│      disabilities)                                        │
│                                                           │
│   [Per-conversation trial binding]                        │
│    - Bind trial_id at session start                       │
│    - Switching trials within a session triggers a new     │
│      conversation with new disclosures and new consent    │
│      posture                                              │
│    - Cross-trial recommendation is structurally           │
│      prohibited at the tool-dispatcher level              │
│           │                                               │
│           ▼                                               │
│   [Output: verified identity, population posture,         │
│    bound trial_id]                                        │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── TRIAL-CONTEXT LOADING + AMENDMENT TRACKING ────┐
│                                                           │
│   [Per-trial IRB-approved content corpus]                 │
│    - Protocol summary in IRB-approved language            │
│    - Eligibility criteria in IRB-approved language        │
│    - Recruitment-FAQ entries in IRB-approved language      │
│    - Visit-schedule summary                               │
│    - Study-procedure summary                              │
│    - Sponsor-and-investigator information                 │
│    - IRB and protocol identifiers                         │
│    - Institutional contact information                    │
│                                                           │
│   [Trial-state verification]                              │
│    - Check trial enrollment status (open, paused, closed) │
│    - Check site-specific enrollment status                │
│    - Route to alternative pathway if trial is not open    │
│                                                           │
│   [IRB-amendment-application mid-conversation handling]   │
│    - Snapshot trial-context-version at conversation start │
│    - On every turn, re-fetch trial-state and compare      │
│      versions                                             │
│    - If material amendment detected: branch to the        │
│      IRB-approved re-disclosure flow                      │
│    - If non-material amendment: continue on the original  │
│      snapshot with stamped version-history                │
│                                                           │
│   [Required first-turn disclosures per IRB]               │
│    - Assistant is a chat tool, not a person               │
│    - Assistant is not the research coordinator            │
│    - Assistant cannot enroll the patient                  │
│    - Assistant is providing trial information and         │
│      conducting a preliminary screen                      │
│    - Patient can stop at any time                         │
│    - Patient can ask to speak to a coordinator at any     │
│      point                                                │
│    - Data-retention notice per institutional policy       │
│           │                                               │
│           ▼                                               │
│   [Output: loaded trial context with versioned snapshot;  │
│    required disclosures delivered]                        │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── TOOL-USE LOOP + IRB-CITATION DISCIPLINE ───────┐
│                                                           │
│   [LLM-orchestrated conversation with tool use]           │
│    - System prompt parameterized per trial, per           │
│      population posture, per language                     │
│    - User message plus recent-conversation context        │
│    - Tool surface:                                        │
│      - trial_context_retrieve (IRB-approved corpus only)  │
│      - recruitment_faq_retrieve (IRB-approved FAQ only)   │
│      - eligibility_criterion_evaluate (deterministic)     │
│      - trial_state_check                                  │
│      - prescreen_capture                                  │
│      - coordinator_handoff_schedule                       │
│      - representativeness_record                          │
│      - emergency_route                                    │
│      - out_of_scope_route                                 │
│      - provenance_retrieve                                │
│                                                           │
│   [IRB-citation discipline]                               │
│    - Every trial-specific assertion must cite an          │
│      IRB-approved source document                         │
│    - If the question falls outside the IRB-approved FAQ,  │
│      route the question to the coordinator rather than    │
│      improvising                                          │
│    - The LLM produces tool calls, not novel trial         │
│      language                                             │
│    - Citation coverage floor enforced (configurable,      │
│      typically 85% or higher)                             │
│           │                                               │
│           ▼                                               │
│   [Output: composed response with citations and           │
│    tool-call audit trail]                                 │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── CONVERSATIONAL ELIGIBILITY PRESCREEN ──────────┐
│                                                           │
│   [Deterministic per-criterion evaluation engine]         │
│    - Simple structured criteria (age, sex, geography,     │
│      basic diagnosis): evaluated from conversation        │
│    - Complex structured criteria (lab values, medication  │
│      history, imaging findings): captured as patient-     │
│      reported with explicit coordinator-verification      │
│      caveat                                               │
│    - Clinical-judgment criteria (severity, prognosis):    │
│      flagged for coordinator review, patient report       │
│      captured as input not determination                  │
│    - Verification-only criteria: captured, deferred to    │
│      coordinator for source verification                  │
│                                                           │
│   [Per-criterion rule ownership]                          │
│    - Each criterion has named clinical-leadership         │
│      ownership, version history, and IRB-review evidence  │
│    - The LLM does not interpret eligibility criteria;     │
│      it surfaces questions, captures responses, and       │
│      routes responses to the deterministic rule engine    │
│                                                           │
│   [Disposition determination]                             │
│    - Clearly disqualified (hard exclusion met)            │
│    - Uncertain pending coordinator verification           │
│    - Likely eligible pending coordinator confirmation     │
│    - Declined by patient                                  │
│    - Trial closed or paused (discovered mid-conversation) │
│           │                                               │
│           ▼                                               │
│   [Output: structured prescreen result with per-          │
│    criterion evaluation, patient-reported data tagged,    │
│    clinical-judgment items flagged]                       │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── OUTPUT SAFETY + IRB-FAITHFULNESS VERIFY ───────┐
│                                                           │
│   [Standard output safety primitives from recipe 11.1]    │
│    - Scope filter (no recommendation, no diagnosis,       │
│      no trial comparison)                                 │
│    - Vendor-managed guardrail layer                       │
│    - Persona-and-tone check                               │
│                                                           │
│   [Recruitment-specific verification]                     │
│    - IRB-language faithfulness: every trial-specific      │
│      statement verified against IRB-approved corpus       │
│    - No unsupported trial-specific assertions             │
│    - Recommendation-language filter (blocks "you should   │
│      join", "this trial is right for you", trial          │
│      comparison across multiple trials)                   │
│    - Distinction between "interest captured" (allowed;    │
│      non-consent) and "consent collected" (not allowed;   │
│      coordinator-only) enforced at the output layer       │
│    - IRB-approved disclosure copy is authored separately  │
│      and reviewed by the IRB, not generated by the LLM;  │
│      the disclosure surface is treated as IRB-approved    │
│      content, not as LLM-generated text                   │
│           │                                               │
│           ▼                                               │
│   [Output: response cleared for delivery, replaced with   │
│    a safer template, or regenerated with corrections]     │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── COORDINATOR HANDOFF + THROUGHPUT CONTROL ──────┐
│                                                           │
│   [Qualified-handoff orchestration]                        │
│    - Capture patient's preferred follow-up channel and    │
│      time                                                 │
│    - Generate structured prescreen summary for            │
│      coordinator (patient-reported data clearly tagged,   │
│      assistant's eligibility assessment clearly tagged    │
│      as preliminary)                                      │
│    - Route to coordinator queue                           │
│    - Confirm handoff arrangement with patient             │
│    - Set expectations about timing of follow-up           │
│                                                           │
│   [Throughput control]                                    │
│    - When coordinator queue exceeds configured            │
│      throughput floor, transition to a "coordinator-      │
│      team-busy, we'll reach out within X business days,   │
│      here are the trial materials in the meantime" flow   │
│    - Do not continue enqueuing handoffs that will age     │
│      out                                                  │
│    - Monitor handoff-acceptance rate and time-to-         │
│      coordinator-contact                                  │
│           │                                               │
│           ▼                                               │
│   [Output: structured handoff in coordinator queue;       │
│    patient confirmed; throughput within bounds]           │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── REPRESENTATIVENESS INSTRUMENTATION ────────────┐
│                                                           │
│   [Per-cohort recruitment funnel monitoring]              │
│    - Entry to prescreen-completion to coordinator-        │
│      handoff to consent to randomize                      │
│    - Stratified by: language, race and ethnicity (OMB     │
│      categories, patient self-report), sex and gender,    │
│      age cohort, geography, insurance status, referral    │
│      source, channel, site                                │
│                                                           │
│   [Launch-gate discipline]                                │
│    - Before a trial goes live on the platform, verify     │
│      that the per-cohort instrumentation is operational   │
│    - Diversity-action-plan targets configured per trial   │
│      where applicable                                     │
│    - Under-recruitment alerts configured per cohort       │
│                                                           │
│   [Equity accountability]                                 │
│    - Per-cohort dashboards reviewed by PI, institutional  │
│      research-recruitment team, sponsor's recruitment     │
│      team, and diversity-action-plan-tracking team        │
│    - Per-cohort gap analysis at configurable intervals    │
│           │                                               │
│           ▼                                               │
│   [Output: per-cohort funnel metrics; under-recruitment   │
│    alerts; diversity-action-plan reporting data]          │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── RECRUITMENT-DECISION RECORD PERSISTENCE ───────┐
│                                                           │
│   [Durable recruitment-decision record]                   │
│    - User utterances (with speaker identification)        │
│    - Tool calls with arguments and results                │
│    - Generated assistant responses                        │
│    - Active model and prompt versions                     │
│    - Active IRB-approved-content versions                 │
│    - Prescreen result with per-criterion evaluation       │
│    - Handoff disposition                                  │
│    - Timestamps and session metadata                      │
│                                                           │
│   [Research-grade retention]                              │
│    - Retention sized to the longest of: institutional     │
│      research-data-retention floor, trial-specific        │
│      retention obligations, HIPAA research-record         │
│      provisions, 45 CFR 46 record-retention obligations,  │
│      and (where applicable) FDA-regulated-trial record-   │
│      retention obligations                                │
│    - Separately-keyed encryption for blast-radius         │
│      containment                                          │
│    - Access controls scoped to research-data roles        │
│      (research-data-officer, sponsor-recruitment-team,    │
│      IRB-inspector audit-only, principal-investigator,    │
│      coordinator-team)                                    │
│    - Cross-class read paths between research-data and     │
│      clinical-care data explicitly disallowed             │
│           │                                               │
│           ▼                                               │
│   [Output: immutable recruitment-decision record          │
│    supporting IRB and regulatory inspection]              │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── PER-TRIAL REPORTING + OUTCOME CORRELATION ─────┐
│                                                           │
│   [Per-trial recruitment-funnel reporting]                 │
│    - Entry volume by referral source and channel          │
│    - Prescreen-completion rate                            │
│    - Prescreen-yield (eligible/total screened) by cohort  │
│    - Coordinator-handoff volume and accept rate           │
│    - Time-to-coordinator-contact                          │
│    - Coordinator-time-saved estimate                      │
│                                                           │
│   [Outcome correlation (accumulates over trial timeline)] │
│    - Consent rate per coordinator-handoff                 │
│    - Randomization rate per consent                       │
│    - Per-cohort representation vs diversity-action-plan   │
│      targets                                              │
│    - Patient-reported recruitment experience              │
│    - Coordinator-reported handoff quality                 │
│                                                           │
│   [Operational monitoring]                                │
│    - Citation coverage rate                               │
│    - IRB-language faithfulness rate                        │
│    - Emergency-escalation rate                            │
│    - Out-of-scope routing rate                            │
│    - Throughput-control activation frequency              │
│           │                                               │
│           ▼                                               │
│   [Output: per-trial dashboards; outcome metrics for      │
│    clinical and operational review]                       │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

A few cross-cutting design points specific to the clinical trial recruitment conversationalist.

**IRB-approved-content corpus as the only allowed source of trial-specific language.** The assistant's trial-specific output is grounded in IRB-approved content with strict citation. The architecture does not permit the LLM to produce novel trial-specific recruitment language. The IRB-approved corpus is the only source. The IRB-approved disclosure copy itself is authored separately and reviewed by the IRB, not generated by the LLM; the architecture treats the disclosure surface as IRB-approved content rather than as LLM-generated text.

**Per-trial isolation is structural, not advisory.** A conversation about Trial A only retrieves content from Trial A's IRB-approved corpus, only evaluates Trial A's eligibility rules, and only emits handoffs to Trial A's coordinator queue. Cross-trial content leakage is the failure mode the architecture exists to prevent.

**Per-conversation trial binding.** The assistant binds a single trial_id at session start. Switching trials within a session triggers a new conversation with new disclosures and new consent posture. Cross-trial recommendation is structurally prohibited at the tool-dispatcher level.

**IRB-amendment-application mid-conversation.** The assistant snapshots the trial-context-version at conversation start. On every turn, the assistant re-fetches trial-state and compares versions. If a material amendment is detected mid-conversation, the assistant branches to the IRB-approved re-disclosure flow. If a non-material amendment is detected, the assistant continues on the original snapshot with stamped version-history. This is a recipe-distinct architectural primitive not present in recipes 11.1 through 11.9.

**Coordinator-queue-as-throughput-control.** When the coordinator queue exceeds the configured throughput floor, the assistant transitions to a "coordinator-team-busy, we will reach out within X business days, here are the trial materials in the meantime" flow rather than continuing to enqueue handoffs that age out. The throughput control protects both the patient experience (no stale handoffs that produce week-long silences) and the coordinator workflow (no queue that grows faster than processing capacity).

**Deterministic eligibility evaluation as architectural primitive.** Each criterion is encoded as a deterministic rule with named clinical-leadership ownership, version history, and IRB-review evidence. The LLM does not interpret eligibility criteria; it surfaces the questions that the deterministic rule needs answered, captures the patient's response, and routes the response to the rule engine.

**"Interest captured" versus "consent collected" as architectural distinction.** The assistant captures interest (allowed; non-consent activity). The assistant does not collect informed consent (coordinator-only activity). This distinction is enforced at the architecture level, not just at the prompt level.

**Out-of-scope routing rules.** Topics outside recruitment scope route to specific alternative pathways: clinical questions about existing care to the patient's care team; requests for medical advice to the institutional patient-services line; requests to enroll without prescreen to the coordinator team; attempts to recruit in violation of the IRB-approved process to the research-compliance office; emergencies to 911.

**Continuous emergency screening across every utterance.** Same as the previous bots in this chapter. The assistant routes acute emergencies immediately to the appropriate emergency pathway. Recruitment-specific extensions cover prospective participants who surface decompensating symptoms, participants who report a recent condition change during eligibility prescreen, and participants whose conversation surfaces psychosocial crisis the recruitment platform is not equipped to handle.

**Research-data-as-distinct-record-class.** Recruitment-conversation content is stored as research data, with retention per the institutional research-data-retention policy, with access controls per the institution's research-data-access policy, and with an audit trail that supports IRB and regulatory inspection. Research-data principals (research-data-officer, sponsor-recruitment-team, IRB-inspector audit-only role, principal-investigator role, coordinator-team role) are separated from clinical-care principals at the IAM-policy level.

**Per-cohort monitoring is non-negotiable.** Recruitment metrics, engagement metrics, and outcome metrics vary by language, channel, race and ethnicity, age cohort, sex, geography, insurance status, referral source, and site. Per-cohort dashboards are reviewed by clinical leadership, the institutional research-recruitment team, the sponsor's recruitment team, and (where applicable) the diversity-action-plan-tracking team.

**Multi-asset clinical-policy-as-code governance.** The IRB-approved trial corpus, eligibility-rule library, recruitment-FAQ corpus, trial-state registry, coordinator-handoff format, representativeness-instrumentation configuration, and out-of-scope routing rules each have per-asset semantic versioning, sandbox testing, staged rollout, rollback-on-regression, named clinical-leadership ownership, IRB review cadence, and per-asset-version stamping on every recruitment-decision record.

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter11.10-architecture). The Python example is linked from there.

---

## The Honest Take

The clinical trial recruitment conversationalist is the recipe in this chapter where the regulatory governance structure is most complex, the institutional stakeholder set is broadest, the per-trial customization depth is deepest, and the time horizon for outcome demonstration is longest. The architectural decisions and the operational disciplines that distinguish a deployment that genuinely moves the recruitment funnel from a deployment that merely digitizes a broken workflow are not subtle, and most of them have been visible in the published underperformance of earlier-generation recruitment tools.

The first trap is treating the IRB as a sign-off gate rather than an active product-development participant. The IRB reviews the recruitment script, the prescreen flow, the FAQ content, the routing logic, the data-collection plan, and the disclosure language. Any patient-facing change requires IRB review or (where within the previously-approved scope) an institutional-policy assessment. Institutions that design the product first and then present it to the IRB for rubber-stamping find that the IRB has substantive feedback that requires architectural rework. Institutions that bring the IRB into the design process from week one produce products the IRB can approve without rework. The governance relationship is collaborative, not adversarial, and the architecture reflects that with change-management workflows that include the IRB-coordinator naturally.

The second trap is underestimating protocol-amendment cadence. Trials amend their protocols routinely. Eligibility criteria change. The visit schedule changes. The recruitment language may change. The IRB-approved content corpus is a living document, not a one-time load. Institutions that build the platform as if the trial content is static discover, within the first few months, that the amendment-application workflow (update the content, route for IRB review, apply the approved amendment to the active trial-context, handle in-flight conversations that started under the prior version) is core operational infrastructure, not an edge case.

The third trap is treating coordinator capacity as infinitely elastic. The downstream coordinator team has finite capacity. A recruitment platform that delivers more qualified handoffs than the coordinator team can absorb produces patient-experience problems (long delays in follow-up, loss-of-interest during the wait) and trial-operations problems (handoffs aging in the queue, prescreens going stale, patients ghosting by the time the coordinator calls). The platform's throughput is calibrated to the coordinator team's actual processing capacity, with smooth flow rather than burst-and-wait dynamics. This constraint is not a platform limitation; it is a deployment discipline.

The fourth trap is the equity gap between platform reach and recruitment-platform accessibility. Recruitment platforms reach disproportionately the patients who are already plugged in to the digital-tool ecosystem. The patients with the greatest unmet research-participation opportunity (rural populations, older adults, patients with limited English proficiency, patients with disabilities, patients without reliable internet access, patients without smartphones) are often the patients with the most limited access to the platform's primary channels. Closing this gap requires deliberate investment in channel diversification (SMS, voice, multilingual content, community-based-organization partnerships, in-person kiosk options), not just deployment of a web chat.

The fifth trap is treating the diversity action plan as a marketing exercise rather than a regulatory and scientific obligation. The diversity-action-plan landscape has moved past voluntary commitments; for FDA-regulated trials with FDORA obligations, the diversity action plan is a regulatory document with specific expectations for measuring and improving recruitment representativeness. Per-cohort recruitment-funnel monitoring is the infrastructure that makes the reporting possible. Institutions that instrument this from day one have the data to demonstrate representativeness; institutions that bolt it on later have gaps in the historical record.

The sixth trap is expecting ClinicalTrials.gov integration to be clean. ClinicalTrials.gov listings are a primary patient-facing entry path, and integrating with the registry is part of the architectural surface. In practice, the registry data has known limitations: listings are not always updated promptly when trials close enrollment, the structured eligibility criteria do not always match the investigator-written natural-language criteria, and the site-status information has lag. The integration requires validation logic and graceful handling of stale or inconsistent registry data.

The seventh trap is the multi-trial disambiguation problem. Where the institution has multiple open trials in a therapeutic area, a patient may be a candidate for more than one. The assistant must handle this scenario carefully: discussing one trial at a time, offering the patient information about others if institutional policy permits and the patient asks, and avoiding any framing that compares trials or constitutes recommendation. The per-conversation trial-binding primitive exists for this reason.

The eighth trap is treating the consent-versus-recruitment line as obvious. The line between "capturing the patient's interest and providing information" (recruitment, the assistant's scope) and "collecting informed consent" (the consent process, the coordinator's scope) is well-defined in regulation but can blur in conversation. A patient who says "I want to sign up" is expressing interest, not providing informed consent; the architecture must route them to the coordinator for the actual consent process rather than treating the expression of interest as enrollment. The architecture enforces this distinction at the output-safety layer, not just at the prompt level.

The ninth trap is optimizing for conversations-completed as a success metric. Conversations completed is a vanity metric. The substantive metrics are prescreen yield per cohort, qualified-handoff accept rate, coordinator-time-saved per handoff, and (over the longer trial timeline) consented-and-randomized participants per cohort against diversity-action-plan targets. An assistant optimized for conversation volume will be optimized for the wrong thing. An assistant evaluated on prescreen yield, coordinator time saved, demographic representation, handoff accept rate, and patient-reported recruitment experience is being evaluated correctly.

The tenth trap is underestimating the per-trial onboarding effort. Each trial requires multi-week clinical work to onboard: IRB-approved content authoring, eligibility-rule encoding, FAQ population, coordinator-team training, per-trial testing, IRB review, and post-launch monitoring. Institutions expecting per-trial onboarding in days discover that the content quality and the IRB-review cadence require weeks to months. The per-trial onboarding workflow is institutional content with named operational ownership per trial. At scale, the onboarding velocity is the gating factor, not the platform capability.

The eleventh trap is the build-versus-buy ambiguity and vendor coexistence. Several mature commercial vendors offer recruitment platforms with FAQ-bot capabilities, eligibility-prescreen tools, and coordinator-handoff infrastructure. Sponsor-funded trials often have existing patient-recruitment vendor partnerships with their own platforms and contractual obligations. The institutional recruitment conversationalist may complement, replace, or coexist with these vendor relationships. The relationship model is negotiated per trial, and pretending the build-versus-buy question has a generic answer is the trap; making it institution-specific and per-trial-specific is the discipline.

The thing that surprises engineers coming from generic-chatbot backgrounds is how much of the engineering value is in the institutional content (the IRB-approved corpus, the eligibility-rule library, the coordinator-handoff format, the representativeness-instrumentation configuration) rather than in the conversational LLM itself. The LLM and the tool orchestration are largely the same patterns as the previous chapter 11 recipes; the trial-specific content and the IRB-governance relationship are what distinguish a recruitment assistant from a chat surface with a trial description pasted into the system prompt.

The thing that surprises clinical-trial sponsors is how dependent the platform's recruitment value is on the coordinator team's operational capacity and engagement. A platform that delivers qualified handoffs into a coordinator queue that is understaffed, overloaded, or not integrated with the coordinator's existing workflow produces handoffs that age out and patients who lose interest. Co-designing the handoff format and the queue-management with the coordinator team is not optional.

The thing about cost: the dominant operational cost is the per-trial onboarding (IRB-approved content authoring, eligibility-rule encoding, coordinator-team integration), not the cloud infrastructure. The infrastructure cost per conversation is modest relative to the coordinator time saved per qualified handoff. The ROI demonstration is strongest when measured in coordinator-time-saved and in trial-timeline-adherence rather than in conversation volume.

The thing I would do differently the second time: start with a single, well-characterized trial in a therapeutic area where the institution already has strong coordinator relationships and recruitment data. Validate the IRB-governance workflow, the coordinator-handoff integration, the eligibility-prescreen accuracy, and the per-cohort instrumentation against a narrow scope before expanding to a multi-trial portfolio. The narrow start lets the team validate the institutional stakeholder relationships (IRB, sponsor, coordinator team, research-compliance, diversity-action-plan team) while the scope is still manageable. Adding additional trials later, with the validated governance infrastructure already in place, is safer and faster than launching with ten trials simultaneously and discovering failure modes across all of them at once.

---

## Related Recipes

- **Recipe 11.1 (FAQ Chatbot):** Same chapter, foundational pattern parent. The recruitment conversationalist inherits the input-screening pipeline, scope filtering, conversation logging, audit pattern, persona discipline, and per-cohort monitoring.
- **Recipe 11.2 (Appointment Scheduling Bot):** Same chapter. The coordinator-handoff orchestration pattern (structured summary, queue routing, patient confirmation, timing-expectation setting) parallels the scheduling bot's booking-handoff infrastructure.
- **Recipe 11.6 (Symptom Checker / Triage Bot):** Same chapter. The IRB-versus-medical-device regulatory distinction is inverted: the triage bot is closer to the SaMD line and must demonstrate clinical safety; the recruitment conversationalist sits on the informational-tool side of the CDS boundary and must demonstrate IRB-content faithfulness. Recruitment-specific acuity scenarios route to the triage pathway.
- **Recipe 11.7 (Chronic Disease Management Coach):** Same chapter. The citation-grounding pattern is shared: the coach grounds in clinical-content-library citations; the recruitment conversationalist grounds in IRB-approved-corpus citations. The architectural primitive is the same; the content governance is different (clinical-leadership-owned library versus IRB-reviewed recruitment corpus).
- **Recipe 11.8 (Mental Health Support Bot):** Same chapter. The sensitive-topic-handling pattern is shared: both assistants acknowledge with calibrated language and route when the conversation crosses scope. The recruitment conversationalist applies this when prospective participants surface psychosocial distress, mistrust of research institutions, or crisis events during the recruitment conversation.
- **Recipe 11.9 (Care Coordination Assistant):** Same chapter. The longitudinal-state pattern and the downstream-human-workflow integration pattern are shared. The coordination assistant manages cross-organizational clinical-coordination state; the recruitment conversationalist manages per-trial recruitment-prescreen state with coordinator-handoff as the downstream human workflow.
- **Recipe 13.x (Knowledge Graphs):** Chapter 13. Knowledge-graph patterns for trial-eligibility encoding (formal ontologies for inclusion/exclusion criteria, hierarchical condition taxonomies, medication-class hierarchies) underpin the deterministic eligibility-evaluation engine's rule definitions.

---

## Tags

`conversational-ai` · `clinical-trial-recruitment` · `recruitment-conversationalist` · `irb-approved-content` · `irb-governance` · `eligibility-prescreen` · `coordinator-handoff` · `trial-state-tracking` · `protocol-amendment` · `diversity-action-plan` · `fdora` · `representativeness-instrumentation` · `per-cohort-monitoring` · `vulnerable-populations` · `pediatric-recruitment` · `surrogate-decision-maker` · `21-cfr-part-50` · `21-cfr-part-11` · `45-cfr-46` · `ich-e6-gcp` · `fda-cds-boundary` · `clinicaltrials-gov` · `tool-using-llm` · `function-calling` · `citation-grounding` · `deterministic-eligibility-evaluation` · `research-data-as-distinct-record-class` · `research-grade-retention` · `irb-language-faithfulness` · `throughput-control` · `per-trial-isolation` · `per-conversation-trial-binding` · `coordinator-capacity-constraint` · `recruitment-funnel-metrics` · `prescreen-yield` · `qualified-handoff-accept-rate` · `equity-monitoring` · `community-research-engagement` · `multilingual` · `channel-diversification` · `decentralized-trials` · `informed-consent-boundary` · `prompt-injection-defense` · `emergency-screening` · `out-of-scope-routing` · `bedrock` · `bedrock-agents` · `bedrock-knowledge-bases` · `bedrock-guardrails` · `opensearch-serverless` · `dynamodb` · `step-functions` · `lambda` · `sqs` · `eventbridge` · `connect` · `pinpoint` · `s3` · `kms` · `secrets-manager` · `cloudwatch` · `cloudtrail` · `waf` · `complex` · `regulated` · `hipaa` · `phi-handling` · `audit-trail` · `chapter11` · `recipe-11-10`

---

*← [Recipe 11.9: Care Coordination Assistant](chapter11.09-care-coordination-assistant) · [Chapter 11 Preface](chapter11-preface)*
