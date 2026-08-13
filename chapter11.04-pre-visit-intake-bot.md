# Recipe 11.4: Pre-Visit Intake Bot

**Effort:** 3 of 5

---

> **This recipe is illustrative, not clinical guidance.** Triage and disposition are clinical
> decisions. The escalation rules, red-flag lists, and sample dialogue here exist to make
> the architecture concrete. They are not a validated triage protocol and must not be
> deployed as one. A patient-facing system needs validation against the protocol your
> organization actually uses.
> Nothing here is a validated clinical tool. Any production use needs clinical
> ownership and review by your own clinical, legal, and compliance teams.

## The Problem

Marisol is 34. She has been having chest tightness off and on for about three weeks. Not crushing, not radiating, not the dramatic Hollywood version. More like the weight of a hand pressing on her sternum that comes on when she's walking up the stairs to her apartment, lingers a few minutes, and goes away. She has been telling herself it's anxiety, because she has had anxiety since she was twenty-one, and anxiety can feel like this. She has also, in the back of her mind, been thinking about her father, who had a heart attack at fifty-one. Marisol made an appointment with her primary care doctor for next Wednesday. The earliest she could get.

The clinic sends her a text message Monday morning: "Hi Marisol, please complete your pre-visit intake at this link before your Wednesday appointment so we can make the most of your time with Dr. Adekunle."

She clicks the link on her phone during her lunch break. She gets a fourteen-page PDF form. The first page is demographics. The second page is insurance. The third page is family history with twenty-two checkboxes for conditions and four blank lines per relative. The fourth page is current medications, with a free-text box. The fifth page is allergies. The sixth page is a generic review of systems with eighty-six checkboxes covering every organ system. The seventh page asks her to describe her chief complaint in one or two sentences. The remaining seven pages are HIPAA notices, financial-responsibility forms, advance-directive prompts, and a permission to text her appointment reminders.

Marisol fills out the demographics. She fills out the insurance, copying numbers from the back of her card. She gets to family history and writes "father - heart attack age 51, mother - thyroid problem (hypo I think), sister - migraines." She gets to medications and writes "sertraline 50, vitamin D, sometimes melatonin." She gets to allergies and writes "no known drug allergies, environmental allergies (dust, pollen)." She gets to the review of systems and her phone battery is at 14% and she has six minutes left of her lunch break and there are eighty-six checkboxes. She checks "chest tightness" and "occasional anxiety" and gives up. She gets to the chief complaint box and writes "chest tightness for 3 weeks, getting more frequent."

That is the data Dr. Adekunle will have when she walks into the room on Wednesday afternoon. A demographics page she can already see in the chart. A medication list that says "sertraline 50" without confirming whether that's the morning or evening dose, whether it was started recently or has been stable for years, whether it's actually being taken. A two-line chief complaint. A family history with two lines that do not capture the actual relevant detail (Marisol's father had his heart attack at fifty-one and her paternal grandfather had one at forty-eight, but Marisol does not remember the second part because she filled out the form on her phone in three minutes). A review-of-systems with two checkboxes that do not capture the radiation pattern, the timing, the relationship to exertion, the associated symptoms (Marisol has noticed some shortness of breath but didn't have a checkbox for "shortness of breath when going up stairs" and didn't think to write it in the chief complaint box).

Dr. Adekunle has fifteen minutes scheduled. The first three minutes are spent re-asking the questions the form asked, because the form's answers were thin. The next three are spent doing the actual relevant history-taking that the form should have collected: when does the tightness happen, what does it feel like, does it radiate, does it come on with exertion, is there shortness of breath, is there nausea, sweating, dizziness, jaw pain, what's the family cardiac history really, how about substance use, sleep, stress. The next three are physical exam. The next three are deciding what to do (an EKG in clinic, a stress test referral, basic labs, a return visit). The last three are documentation, which actually takes seven minutes and runs the appointment over, which delays the next patient.

This is pre-visit intake in healthcare, and it is the most under-engineered, highest-leverage, most-frequently-skipped data-collection workflow in the entire ambulatory system. Done well, it transforms a fifteen-minute visit. Done badly, which is most of the time, it produces fourteen pages of paperwork that the physician re-asks anyway. The form-based approach has not really changed in twenty years. Some clinics have moved their forms from paper to PDFs to portal-based forms. The forms are still forms. The completion rates are still terrible. The data quality is still thin. The patients still hate them. The clinicians still re-ask everything.

The frustrating thing, when you look at the failure mode honestly, is that what makes a great intake is not what makes a great form. A great intake is a conversation that adapts to the patient. When Marisol mentions chest tightness, the next question is not "any history of measles?" The next question is "tell me more about that. When does it happen? What does it feel like?" When she mentions her father's heart attack at fifty-one, the next question is not "any other family members?" The next question is "any other early heart problems in the family? On either side?" The intake follows the thread. The intake does not follow the form.

A clinical assistant who is good at intake is following a mental decision tree that branches dynamically based on what the patient says. They are doing this from training and from experience. They know that "chest tightness" plus "exertion" plus "family history of early heart disease" is a constellation that requires a different set of follow-up questions than "chest tightness" plus "anxiety history" plus "no exertional pattern." They know that "tired all the time" in a 34-year-old with two young children is a different question than "tired all the time" in a 78-year-old with a recent fall. The form does not know any of this. The form asks every question to every patient and gives most of them no time to actually answer the relevant ones.

The previous generation of pre-visit intake tools, when they tried to be smart, tried to do this with branching logic in a forms engine. If patient checks "chest pain," show the cardiac questions panel. If patient checks "feeling sad," show the depression screener. The problem with the forms-engine approach is that the branching is brittle, the questions still feel like a checklist, and the real human signal (the way Marisol writes "chest tightness for 3 weeks, getting more frequent" in a free-text box, or mentions "actually I don't really remember if my dad's heart attack was a heart attack or a stroke now that you ask") gets crammed into structured fields that destroy the nuance. The patients who fill out branching forms hate them only slightly less than they hate non-branching forms. The clinicians get only marginally better data.

The modern conversational pre-visit intake bot looks like this. Marisol opens the link Monday morning. The bot says "Hi Marisol, I'm Riverside Clinic's intake assistant. I'm going to ask you about what's going on so Dr. Adekunle has the right information for your visit on Wednesday. I'll keep it short. Some questions are required by the clinic, and I'll let you know if you can skip something. I'm a chatbot, not a clinician, and I can't give medical advice. If you ever feel like something is an emergency, please call 911. Ready?"

Marisol says yes.

The bot says "What brings you in to see Dr. Adekunle on Wednesday?"

Marisol types "chest tightness for 3 weeks getting more frequent."

The bot says "Thanks for sharing that. Can you tell me a little more? When does the tightness usually happen? Is it tied to anything you're doing or thinking about?"

Marisol types "mostly when I walk up stairs, sometimes when I'm rushing around. lasts a few minutes."

The bot says "Got it. Does it feel like pressure, squeezing, sharpness, or something else? And does it spread anywhere, like to your arm, jaw, or back?"

Marisol types "more like pressure on my chest, doesn't really spread."

The bot continues for about ten more turns: any shortness of breath, any nausea or sweating, has it gotten worse in the last week, has she ever had this before, any new stress in her life, what helps it stop, when's the last time it happened. By turn fourteen, the bot has the kind of HPI (history of present illness) that an experienced triage nurse would have collected, and it has it in a structured representation that Dr. Adekunle can read in twenty seconds before walking into the room.

When the bot asks about family history, it asks "any heart problems in your family, especially before age sixty?" and Marisol mentions her father at fifty-one and, when prompted ("anyone else? brothers, sisters, grandparents on either side?"), her paternal grandfather at forty-eight. When the bot asks about medications, it preloads the chart's list and asks Marisol to confirm or correct. When she says "I'm not actually taking the melatonin anymore," the bot captures that. When the bot detects, somewhere in turn nine, a constellation of features that warrant a higher-acuity flag, it does not tell Marisol that she might be having cardiac symptoms (it is a chatbot, not a clinician). It quietly flags the encounter for a same-day call from a triage nurse, and tells Marisol "thanks for completing this. The team will look at it before your visit, and someone may reach out today if they want to check in before Wednesday."

That fifteen-minute conversation, completed asynchronously over Marisol's lunch break, replaces fourteen pages of forms, gives Dr. Adekunle a focused pre-read, and surfaces the high-acuity signal early enough that Marisol gets a same-day nurse callback rather than waiting until Wednesday afternoon. The clinical staff is doing the same triage work they would have done if she had called the office, except the bot did the structured-data collection and the routing in the time the form would have taken anyway.

A few things this recipe is and is not.

It is the bot that conducts a structured pre-visit interview adapted to the visit type, the chief complaint, the patient's chart context, and the practice's intake protocol. It captures what would have gone into the chief-complaint, HPI, ROS, medications, allergies, social history, and family history sections of the visit note, and surfaces it to the clinical team in a structured pre-visit packet.

It is not the diagnostician. The bot does not tell the patient what is wrong with them. The bot does not produce a differential. The bot does not recommend treatment. The bot's job is to collect the information; the clinician's job is to interpret it.

It is not the triage bot. The bot does not perform symptom-acuity triage in the way that recipe 11.6 (symptom checker / triage bot) does. The bot can flag patterns to clinical staff for triage review, but the clinical decision belongs to a clinician. Recipe 11.6 covers the architecture for direct patient-facing triage; this recipe covers structured data collection feeding human triage.

It is not a replacement for the visit. Marisol still sees Dr. Adekunle on Wednesday. The bot makes the visit better, not optional.

It is not an open-ended conversational therapy bot. The bot is bounded to the intake task. Long-running conversations about the patient's emotional state, ongoing coaching, or therapeutic interaction are scope for recipe 11.7 (chronic disease management coach) and 11.8 (mental health support bot). The intake bot acknowledges, captures the relevant signal, and routes the patient to the appropriate clinical resource without trying to be the resource.

It is not a regulatory medical-device-style decision-support tool. The bot's output is structured data plus optional flags for clinical attention. The bot does not produce decision-support recommendations to either the patient or the clinician in the way that recipe 11.6's triage outputs do. This positioning is intentional. It keeps the bot on the safer side of the FDA's clinical-decision-support guidance line by sticking to data collection and structured routing, which informs but does not replace clinical judgment. 

The thing to understand before building this is that the bot's quality is bounded above by the practice's intake-protocol explicitness and the chart-context completeness. A bot operating against vague protocols and an incomplete chart asks generic questions and gets generic answers. A bot operating against precise per-visit-type protocols and a well-reconciled chart conducts the kind of focused pre-visit interview that meaningfully changes the visit. The pre-deployment work of formalizing the intake protocols per visit type is the highest-leverage investment, and it is rarely scoped into the project plan because nobody owns the protocol formally.

Let's get into it.

---

## The Technology: Adaptive Conversational Interviewing Plus Structured Clinical Data Capture

### Why Pre-Visit Intake Has Stayed Stuck on Forms

Pre-visit intake, as a workflow, has been a forms problem for decades. Paper forms gave way to PDF forms gave way to portal-based forms. The shape never changed: a fixed set of questions delivered to every patient regardless of context. The forms grew over time as the institution added requirements (HIPAA notices, financial responsibility, advance directives, social-determinants screeners, depression screeners, fall-risk screeners), and the patient's incentive to fill them out thoroughly grew weaker as the forms grew longer. The completion rate is poor. The data quality is thin. The clinician re-asks. 

The first generation of digital intake tools, roughly 2010 to 2020, replaced paper with screens and added some basic branching ("if patient is female and pregnant, show the prenatal-screening section"). The branching was static, the question wording stayed identical regardless of patient context, and the resulting data was structured exactly the same as the paper form had been. The shape of the workflow stayed the same. A few vendors built sophisticated forms-based products with extensive conditional logic; the conditional logic helped, but the experience was still a forms experience and the patient still felt like they were filling out a form.

The thing that changed the workflow shape is the same thing that changed the refill, scheduling, and FAQ workflows: large language models that can carry on a coherent conversation while sticking to a structured task. A conversational intake interview is fundamentally different from a forms-based intake interview because the bot can ask the next question based on what the patient just said, rephrase a question that the patient did not understand, follow a thread that opens up unexpectedly, skip questions that have already been answered implicitly, and produce structured data at the end without having displayed structured fields to the patient.

The architectural shift is from "show all the questions and capture all the answers" to "conduct an adaptive conversation that produces a structured pre-visit packet." The bot's value is concentrated in two places: the conversation experience for the patient (which is qualitatively different from a form and produces meaningfully higher engagement and completion), and the structured-data quality for the clinician (which is meaningfully richer because the bot followed the interesting threads).

### What an Adaptive Intake Bot Actually Does

An intake bot is a tool-using LLM with a system prompt that tells it what assistant it is, the patient's authenticated context, the visit context (visit type, scheduled provider, scheduled date, reason-for-visit if known), the patient's chart context (active problems, current medications, known allergies, prior visit history), and access to a set of tools. The LLM conducts the conversation. The tools handle the deterministic actions: looking up chart context, validating extracted data, persisting partial state, computing screening-tool scores, surfacing acuity flags, writing the final pre-visit packet to the electronic health record (EHR).

The conversation has a structure, even though the patient does not see it. The structure decomposes roughly as follows.

**The greeting and disclosure.** Same primitive as the other patient-facing bots. Identifies as a chatbot, states scope (data collection for the upcoming visit), acknowledges that emergencies should go to 911, offers a path to a human.

**The chief complaint and reason for visit.** The first substantive question is open-ended: what brings you in. This sets the rest of the interview. The bot does not show a dropdown of possible reasons; the bot lets the patient describe their concern in their own words and then carries the conversation from there.

**The history of present illness (HPI).** Given the chief complaint, the bot follows the OPQRST or SOCRATES or similar mental framework that experienced clinicians use: onset, provocation, quality, radiation, severity, timing, associated symptoms, alleviating factors. The framework is not displayed; the questions are phrased conversationally. The bot adapts the depth of HPI to the chief complaint: a sore throat for two days warrants four to six HPI questions; chest tightness for three weeks warrants ten to fifteen.

**The relevant review of systems.** Rather than the eighty-six-checkbox generic ROS, the bot asks only the systems that are clinically relevant to the chief complaint and the visit type. Chest-tightness presentation gets the cardiopulmonary ROS. Annual physical gets a structured but compact full-system pass. Medication-management visit gets a focused symptom-and-side-effect ROS for the relevant medications.

**The medication confirmation.** The bot pulls the chart's current medication list and asks the patient to confirm. "I see you're taking sertraline 50 milligrams once a day, vitamin D, and you said you sometimes take melatonin. Is that still right? Anything you've stopped or anything new from another doctor we should know?" The patient confirms or corrects. The bot does not change the medication list (that is a clinical action); the bot captures the patient-reported updates as structured medication-reconciliation events for the clinical team.

**The allergy confirmation.** Same pattern as medications. Pulls the chart's allergy list, asks the patient to confirm or update.

**The relevant past medical, surgical, family, and social history.** The bot asks history questions targeted to the visit type and the chief complaint. Chest-tightness presentation gets explicit family-history-of-cardiac-disease prompts with follow-up. Annual physical gets a broader sweep. Established patients with a complete chart get a confirmation pass; new patients get a more thorough collection.

**The visit-type-specific screeners and protocols.** Many visit types come with required screeners: PHQ-9 for depression at primary-care visits where indicated, AUDIT-C for alcohol screening, CAGE, GAD-7, PROMIS instruments, fall-risk screening for older adults, social-determinants-of-health screeners. The bot administers these conversationally rather than as forms when feasible, scoring them and surfacing the score and any flag. Some screeners (like the PHQ-9) have specific item wordings that are required for the score to be valid; the bot uses the validated item wordings for these and computes the score per the validated scoring rules.

**The advance-directive, code-status, and patient-rights items.** Items that the institution requires every patient to acknowledge or update get handled in the conversation flow with appropriate gravity. These are not skip-friendly; they are required pieces of every visit packet.

**The crisis-detection and acuity-flag layer.** Throughout the conversation, the bot screens for crisis signals (suicidal ideation, active self-harm risk, abuse, medical emergency), red-flag symptoms (specific symptom combinations that warrant immediate clinical attention), and significant new-information events (a new diagnosis the patient mentions, a hospitalization the chart does not show, a new medication from another provider). Crisis signals route immediately to the crisis pathway. Red-flag symptoms route to a same-day clinical-staff callback. Significant new information surfaces in the pre-visit packet.

**The closing summary and confirmation.** The bot summarizes what it captured, confirms with the patient, and tells them what to expect ("Dr. Adekunle will read this before your visit. The clinical team may reach out today if they want to check in before Wednesday").

**The structured pre-visit packet generation.** The bot's final action is producing the structured packet from the conversation: chief complaint, HPI in a structured representation, ROS findings, medication-reconciliation deltas, allergy updates, screener scores, history updates, acuity flags, and the conversation transcript. The packet is written to the EHR (typically as a pre-visit note or as discrete structured fields the EHR exposes) and the conversation transcript is preserved as an audit and clinical-record artifact.

### Why a Generic LLM Cannot Run a Pre-Visit Intake

A naive product approach would be: take a generalist LLM, give it a chat surface, tell it to "interview the patient before their visit," and run with it. This does not work, for reasons that compound the closer you look.

**The model has no view of the patient's chart.** Without the patient's active problems, current medications, allergies, prior visit history, and visit context as input, the LLM does not know what to ask about. The bot will ask "any allergies?" instead of "I see you're listed as allergic to penicillin; is that still right?" The chart-context tools (problem-list-lookup, medication-list-lookup, allergy-list-lookup, prior-visit-summary-lookup, scheduled-visit-context-lookup) are the inputs that make the bot adaptive in the way clinicians value.

**The model cannot administer validated screeners reliably.** Tools like the PHQ-9 require specific item wordings to produce a valid score.  Asking the LLM to "ask depression-screening questions" produces a conversation that is not a validated PHQ-9. The screener tool encapsulates the validated item wordings, the response capture, and the scoring rules. The bot administers the tool; the tool produces the score.

**The model cannot reliably extract structured clinical data from conversational text.** "I started having tightness about three weeks ago, mostly when I climb stairs, lasts a few minutes, feels like pressure" needs to become a structured HPI representation: onset_relative="3 weeks ago", trigger="exertion (stairs)", duration="several minutes", quality="pressure". A generalist LLM will produce this extraction unreliably. The structured-extraction tool wraps a more specifically-tuned extraction step and validates the output schema. 

**The model has no reliable theory of the practice's intake protocol.** What does this practice want to capture for a chest-pain presentation? What screeners are required for an annual physical for a 34-year-old? What HPI elements does the practice's medical leadership consider non-negotiable? The intake protocol is the institutional artifact that answers these questions. Asking the LLM to "do a good intake" produces inconsistent intake; asking the LLM to follow a documented per-visit-type protocol produces consistent intake.

**The model cannot reliably enforce the boundary between data collection and clinical advice.** Patients ask questions during intake. "Is this serious?" "Should I be worried?" "What do you think it could be?" The bot's correct response is "I'm a chatbot and can't give medical advice, but the clinical team will review what you've shared and your appointment with Dr. Adekunle is on Wednesday. If at any point you feel like this might be an emergency, please call 911." A generalist LLM, asked to be helpful, will start to speculate. The output safety screening, the system prompt, and the scope filters are layered defenses; none of them is sufficient alone.

**The model cannot detect crisis reliably without the explicit safety layer.** A patient mentioning suicidal ideation during a depression-screener exchange must trigger the crisis pathway. A patient describing symptoms that look acutely cardiac must trigger same-day clinical follow-up. The crisis-detection and acuity-flag layer is a separate, explicit pipeline component. Folding it into the LLM's general behavior produces inconsistent escalation.

**The model has no audit trail of what was captured versus what was inferred.** The practice's clinical team needs to know: what did the patient actually say, what did the bot extract, what did the bot infer. The structured-data ledger captures the patient's actual utterances, the bot's structured extractions, the screener scores, the chart-context that was loaded. Without this, the pre-visit packet is unreviewable for clinical safety and unverifiable for compliance.

**The model has compliance implications for clinical-data conversations.** The intake conversation is dense protected health information (PHI): chief complaint, HPI, medications, allergies, family history, social history, screener responses, the patient's own emotional state. The conversation log is a clinical record. The medication and allergy reconciliation deltas may become part of the formal medical record. The screener scores are clinical-record events. The architecture must produce the durable audit pipeline plus a layer of clinical-event documentation similar to what the refill bot needed but with broader and richer content.

### What the Intake Bot Has To Do That the Refill Bot Did Not

Recipes 11.1 (FAQ), 11.2 (scheduling), and 11.3 (refill) established the patterns this recipe inherits: input safety screening, intent classification (here narrower because the intake bot is single-task), identity verification with graduated assurance (here typically the authenticated portal session), tool-use orchestration, output safety screening, audit logging, per-cohort monitoring. The intake bot adds five structural commitments those recipes did not have.

**Adaptive question-flow orchestration.** The previous bots' tool surfaces were transactional (look up an appointment, e-prescribe a refill). The intake bot's tool surface is structurally a question-flow orchestration: which question to ask next given what has been captured, what the chart says, what the visit type is, and what the practice's protocol requires. This is not a free-form LLM decision; it is a tool that runs a state machine over the protocol with the LLM only choosing the natural-language phrasing. Skipping this discipline produces a bot that wanders through topics and fails to capture required items.

**Validated-screener administration as a discrete tool.** PHQ-9, GAD-7, AUDIT-C, PROMIS instruments, fall-risk screeners, social-determinants screeners are each their own validated tool with specific item wordings, response options, and scoring rules. The bot's screener tool encapsulates each one. The bot does not paraphrase the items; it administers the validated wordings and captures the responses. The scoring is deterministic and produces a clinical-record event. 

**Structured clinical-data extraction with schema validation.** The bot's HPI, ROS, history, and reconciliation outputs are structured. Each output field has a schema. The extraction tool produces output that conforms to the schema and validates before persistence. Free-text remarks are preserved alongside the structured representation, but the structured fields are the surface the clinical team consumes. The schema is owned by clinical informatics, not engineering.

**Crisis and acuity flagging as a parallel pipeline.** Throughout the conversation, the bot screens every patient utterance for crisis signals and red-flag clinical patterns. The screening runs in parallel with the conversation; a hit interrupts the flow and routes appropriately. The pipeline is a separate component, not a feature of the conversational LLM, because the consequences of missing a crisis signal are severe. The pipeline has named ownership at the patient-safety committee.

**Pre-visit packet generation as a structured handoff to the clinical workflow.** The bot's final output is the pre-visit packet: a structured artifact the clinical team consumes before the visit. The packet's schema is defined by the practice's clinical informatics team. The packet is delivered to the EHR through the appropriate integration point (typically as a pre-visit note attached to the upcoming encounter, or as discrete structured fields populated through the EHR's intake-data API where exposed). The handoff is the primary value-delivery mechanism; if the packet does not land in front of the clinician at the right moment, the bot's value is largely lost.

The rest is largely the same as recipes 11.2 and 11.3: tool-surface contract management, identity-assurance lifecycle, conversation logging, scope filtering, per-cohort monitoring, prompt-injection defense.

### The Intake Reality

A few notes on what makes pre-visit intake specifically harder than other patient-facing bot use cases.

**Visit types are not interchangeable.** A primary-care annual physical, a primary-care follow-up for a chronic condition, a same-day urgent visit, a specialist consultation, a procedure pre-op, a behavioral-health intake, a pediatric well-visit, a women's-health visit, a geriatric assessment, a telehealth visit. Each has a different intake protocol. The protocol structure is the same (HPI, ROS, history, reconciliation, screeners, packet), but the contents differ substantially. The bot's protocol library has an entry per visit type, and the bot's first orchestration decision is which protocol to load.

**Chief complaints are open-ended and the protocol must adapt.** "I'm here for my annual" and "I'm here because my chest hurts" are different conversations. The protocol per visit type provides the shape; the chief complaint dynamically opens or closes branches within the protocol. A primary-care annual that uncovers a new chest-pain complaint should pivot into the cardiac-symptoms branch, not finish the wellness checklist while ignoring the chest pain.

**Patients answer in unexpected ways.** "When did the chest tightness start?" can produce "about three weeks ago" or "I think after I started the new job" or "I'm not sure, maybe a while back" or "I've had it on and off for years but it's been worse recently" or "ugh I don't know, I never know with these things." The bot's extraction has to handle the range of answers gracefully, ask a clarifying question when the answer is unusable, and accept "I don't know" as a valid response without escalating.

**The patient's free-text answer often contains multiple findings.** "Chest tightness for 3 weeks getting more frequent" contains: a symptom (chest tightness), a duration (3 weeks), a temporal pattern (getting more frequent). "I've been more anxious lately and not sleeping well, and the chest tightness is making me wonder if it's all related" adds: anxiety symptoms, sleep disturbance, the patient's own theory of the case. The extraction has to tolerate these compound answers and surface each finding.

**Screeners are sensitive instruments.** The PHQ-9 ends with an item asking about thoughts of self-harm or suicide. The bot's response when a patient endorses that item is consequential. The crisis-detection layer recognizes the pattern; the response template is reviewed by clinical leadership; the routing pathway is tested.  Skipping this design work and leaving the bot to handle item 9 with its general response generation is unsafe.

**Cultural and linguistic variability in symptom expression matters.** Different patient populations describe symptoms differently. "Chest pressure" is one description; "weight on my chest," "tightness," "heaviness," "like something sitting on me" are equivalent descriptions. Different languages have different idioms for symptoms.  The bot's extraction has to handle the variability, and the per-language deployment work has to handle the per-language idioms with native-speaker review.

**Patients sometimes disclose sensitive information unexpectedly.** A pediatric well-visit intake question to a parent may disclose domestic violence in the household. A medication-confirmation question may disclose substance-use issues. A social-history question may disclose intimate-partner violence or housing instability. The bot's response in these moments matters. The crisis-detection and sensitive-disclosure pathways are explicit, the responses are reviewed by clinical leadership, and the routing is to clinicians (or, where appropriate, social workers) trained for these conversations.

**Medication reconciliation discrepancies are common.** The chart's medication list rarely matches what the patient actually takes. The patient stopped a medication, started a new one prescribed elsewhere, takes a slightly different dose, or skips it some days. The bot captures the patient-reported state without changing the chart; the discrepancies are flagged for clinical review during the visit. The medication-reconciliation pattern is similar to recipe 11.3 but applied across all the patient's medications, not just the one being refilled.

**Family-history accuracy is variable.** Patients often do not know the details of family-history events. "My dad had a heart attack but I don't remember if he was fifty or sixty." "My mom had some kind of thyroid thing." The bot's family-history collection asks gently, accepts uncertainty, and captures what the patient knows. The bot does not pretend the data is more precise than the patient's report.

**The intake conversation is asynchronous and may be interrupted.** Marisol is filling this out on her lunch break. She might get pulled away. She might want to come back later. The conversation has resumable state. The bot greets her at the start of the resumed session ("welcome back; you got partway through. Want to pick up where you left off, or start over?") and resumes with the appropriate context.

**The bot is sometimes the patient's first encounter with the practice.** New patients have not seen the practice yet; the intake bot is their first touchpoint. The persona, the warmth, the clarity of the disclosure, and the smoothness of the experience set the practice's first impression. This is not a back-office tool; it is a patient-experience surface.

**Pediatric and proxy-completion flows are common.** A parent fills out intake for a child. A caregiver fills out intake for an elderly parent. A spouse helps a partner with limited English fill out the intake. The bot's identity-and-relationship handling has to be explicit: who is talking to the bot, who is the visit for, what authorization does the proxy have. This is a different problem than the previous bots had, because the previous bots were predominantly patient-self-service.

### Where the Field Has Moved

A few practical updates worth knowing.

**Fast Healthcare Interoperability Resources (FHIR) Questionnaire and QuestionnaireResponse provide structured representations.** The FHIR Questionnaire resource represents a structured intake form, and the QuestionnaireResponse resource represents the patient's answers.  Most major EHRs expose these endpoints, and the institutional intake protocol can often be represented as a FHIR Questionnaire under the hood, with the bot conducting the conversation and producing a QuestionnaireResponse as the structured output. This integration path provides interoperability and supports portable intake protocols.

**Validated screening instruments are increasingly digital-native.** PHQ-9, GAD-7, PROMIS short forms, AUDIT-C, and many others have been validated for digital and conversational administration.  The bot can administer these conversationally, score them per the validated rules, and produce the score as a clinical-record event.

**Patient-reported outcomes (PROs) are part of routine care.** PROMIS, FACIT, EORTC, condition-specific PROs (NEI-VFQ for vision, BFI for fatigue, ODI for low back pain) are increasingly part of routine care. The bot can administer PROs as part of intake for relevant visit types, contributing to the longitudinal data the institution collects on patient outcomes.

**Tool-using LLMs handle structured data collection well when prompted carefully.** The function-calling pattern from recipes 11.2 and 11.3 maps directly to intake: the LLM produces tool calls that capture each piece of structured data, the tools validate the schemas, the LLM continues the conversation. The architecture is robust enough that institutions deploying intake bots since roughly 2023 onward have been using this pattern by default.

**The shift from forms to conversation produces measurably better engagement.** Healthcare conversational-intake deployments consistently show higher completion rates and higher patient satisfaction than the forms they replace, holding the visit type constant.  The data-quality finding is more nuanced: conversational intake produces better data on the chief-complaint and HPI dimensions and similar or modestly-better data on the structured-history dimensions, with the gap being largest for visit types with rich HPI requirements.

**Pre-visit-intake products are commercially mature.** Several vendors offer pre-visit-intake products integrated with the major EHRs, with conversational and form-based variants and varying levels of customization.  The build-vs-buy economics favor partial-buy for many institutions, similar to the refill bot. Build the conversational and protocol layers on the practice's preferred infrastructure; integrate with the EHR through the vendor's APIs.

**Equity considerations are central to intake design.** A bot that works only for English-speaking, smartphone-using, internet-access-having, technology-comfortable patients excludes a substantial fraction of the population. The patients excluded are disproportionately the patients who would benefit most from a bot that is patient about asking and good at adapting. Multi-language, multi-channel (web, SMS, voice), accessibility-conformant deployment is foundational, not optional.

---

## General Architecture Pattern

A healthcare pre-visit intake bot decomposes into ten logical stages: channel entry, input safety screening, identity and relationship verification, visit-context loading, protocol selection, adaptive question-flow orchestration, structured data extraction with screener administration, parallel crisis and acuity flagging, output safety screening, and pre-visit packet generation. The cross-cutting concerns from recipes 11.1 through 11.3 carry forward; this recipe adds three new ones (intake-protocol-as-code lifecycle, validated-screener tool library governance, pre-visit packet schema management).

```text
┌────────── CHANNEL ENTRY ─────────────────────────────────┐
│                                                           │
│   [Patient receives intake invitation through one of      │
│    the configured channels: secure email link, SMS        │
│    link, in-app push notification, patient-portal         │
│    embed when authenticated]                              │
│                                                           │
│   [Greeting and disclosure]                               │
│    - Identifies as a chatbot, not a clinician             │
│    - States the bot's scope (collecting information       │
│      for the upcoming visit; not providing medical        │
│      advice; not performing triage; not a substitute      │
│      for the visit)                                       │
│    - Acknowledges that emergencies should go to 911       │
│    - Offers an immediate path to reach the clinic         │
│    - Sets expectations on length and what happens         │
│      with the data                                        │
│                                                           │
│   [Conversation session bootstrap]                        │
│    - Generate session_id                                  │
│    - Capture channel, authentication context, and the     │
│      deep-link parameters identifying the upcoming        │
│      encounter                                            │
│    - On resume: load partial state                        │
│           │                                               │
│           ▼                                               │
│   [Output: session_id, channel, auth context, encounter   │
│    reference]                                             │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── INPUT SAFETY SCREENING ────────────────────────┐
│                                                           │
│   [Same primitive as the previous chapter 11 recipes,     │
│    with intake-specific tuning:]                          │
│    - Crisis detection (preempts everything; intake        │
│      conversations frequently surface crisis signals      │
│      because the bot is asking about how the patient      │
│      is doing)                                            │
│    - Prompt-injection detection                           │
│    - PHI minimization                                     │
│    - Screener-aware: the bot's PHQ-9 item 9 expects       │
│      a response that may match crisis patterns; the       │
│      crisis pipeline knows the screener context and       │
│      handles it appropriately                             │
│           │                                               │
│           ▼                                               │
│   [Output: input passes / input blocked-with-disposition] │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── IDENTITY AND RELATIONSHIP VERIFICATION ────────┐
│                                                           │
│   [Authenticated session path (recommended default)]      │
│    - Patient is logged into the patient portal or app     │
│    - The session conveys an authenticated patient_id      │
│    - The bot accepts the patient_id as verified           │
│                                                           │
│   [Unauthenticated link path with one-time token]         │
│    - The intake link includes a single-use signed token   │
│      that authenticates the patient for this specific     │
│      intake session                                       │
│    - The bot verifies the token, binds to the patient,    │
│      and proceeds                                         │
│                                                           │
│   [Proxy-completion path]                                 │
│    - When the visit is for a child or for a patient       │
│      whose access is delegated, the authenticated user    │
│      is the proxy, not the patient                        │
│    - The bot confirms relationship at the start ("you     │
│      are completing this for [patient name], correct?")   │
│    - The bot's prompts adjust accordingly ("how has       │
│      [patient name] been feeling?")                       │
│                                                           │
│   [Step-up authentication for sensitive items]            │
│    - Some institutions require step-up for items that     │
│      cross sensitivity thresholds (e.g., self-disclosure  │
│      of mental-health items in an unauthenticated         │
│      adolescent flow)                                     │
│           │                                               │
│           ▼                                               │
│   [Output: verified patient_id, proxy_relationship,       │
│    assurance_level]                                       │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── VISIT-CONTEXT LOADING ─────────────────────────┐
│                                                           │
│   [Tool: encounter_context_lookup]                        │
│    - Visit type, scheduled provider, scheduled date,      │
│      reason-for-visit if known, encounter location        │
│      (in-person, telehealth)                              │
│                                                           │
│   [Tool: chart_context_lookup]                            │
│    - Active problems, current medications, known          │
│      allergies, recent vital signs, recent labs,          │
│      relevant prior visit summaries                       │
│                                                           │
│   [Tool: prior_intake_lookup]                             │
│    - Recent intake responses for the same patient         │
│      (so the bot can confirm rather than re-collect       │
│      stable history items)                                │
│                                                           │
│   [Tool: patient_demographics_lookup]                     │
│    - Age, preferred language, accessibility               │
│      accommodations on file                               │
│           │                                               │
│           ▼                                               │
│   [Output: structured visit context, chart context,       │
│    prior intake context, patient demographics]            │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── PROTOCOL SELECTION ────────────────────────────┐
│                                                           │
│   [Tool: protocol_selector]                               │
│    - Inputs: visit type, encounter context, patient       │
│      demographics, prior intake history                   │
│    - Output: the per-visit-type protocol to load          │
│      (e.g., "primary_care_followup_v3.2",                 │
│      "annual_physical_adult_v4.1",                        │
│      "specialist_consult_cardiology_v2.0",                │
│      "behavioral_health_intake_v3.0")                     │
│    - Output: the screener bundle to administer            │
│      (e.g., PHQ-9, GAD-7 for primary-care visits          │
│      meeting the institutional screening cadence)         │
│           │                                               │
│           ▼                                               │
│   [Output: active protocol_version, screener_bundle]      │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── ADAPTIVE QUESTION-FLOW ORCHESTRATION ──────────┐
│                                                           │
│   [Tool: question_flow_state_machine]                     │
│    - Maintains the protocol's state                       │
│    - Returns the next question to ask based on:           │
│      protocol position, what has been captured,           │
│      what the chart already provides, what branches       │
│      have opened or closed                                │
│    - The LLM phrases the question conversationally;       │
│      the state machine decides which question             │
│                                                           │
│   [Conversation loop]                                     │
│    - Bot asks a phrased question                          │
│    - Patient answers conversationally                     │
│    - Extraction tool produces structured findings         │
│    - Crisis-and-acuity pipeline runs in parallel          │
│    - State machine advances; loops to next question       │
│      or to a follow-up branch the patient's answer        │
│      opened                                               │
│                                                           │
│   [Branch handling]                                       │
│    - Open: patient mentions chest pain in primary-care    │
│      annual; cardiac-symptoms branch opens                │
│    - Close: patient denies the symptom in question;       │
│      the negative-finding is captured and the branch      │
│      closes without follow-ups                            │
│    - Diverge: patient brings up an unrelated significant  │
│      concern; the bot acknowledges, captures the          │
│      concern, and weaves back to the protocol             │
│                                                           │
│   [Resumability]                                          │
│    - Persist conversation state and protocol position     │
│      after each captured turn                             │
│    - On resume, the bot continues from the persisted      │
│      position with appropriate re-greeting                │
│           │                                               │
│           ▼                                               │
│   [Output: ongoing conversation state, captured           │
│    findings as they accumulate]                           │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── STRUCTURED EXTRACTION AND SCREENERS ───────────┐
│                                                           │
│   [Tool: hpi_extraction]                                  │
│    - Extracts onset, provocation, quality, radiation,     │
│      severity, timing, associated symptoms, alleviating   │
│      factors from the patient's HPI utterances            │
│    - Validates against schema                             │
│                                                           │
│   [Tool: ros_extraction]                                  │
│    - Extracts review-of-systems findings (positive and    │
│      negative) from the relevant-system questions         │
│    - Validates against schema                             │
│                                                           │
│   [Tool: medication_reconciliation_capture]               │
│    - Captures patient-reported medication updates         │
│      against the chart's current list                     │
│    - Produces structured deltas (added, stopped,          │
│      dose-changed, taking-as-prescribed)                  │
│    - Does NOT change the chart; produces                  │
│      reconciliation events for clinical review            │
│                                                           │
│   [Tool: allergy_reconciliation_capture]                  │
│    - Same pattern as medications, applied to allergies    │
│                                                           │
│   [Tool: history_extraction]                              │
│    - Past medical history, surgical history, family       │
│      history, social history (smoking, alcohol,           │
│      substance use, occupation, living situation)         │
│    - Captures patient-stated detail with appropriate      │
│      uncertainty markers                                  │
│                                                           │
│   [Tool: screener_administer]                             │
│    - For each screener in the bundle, present the         │
│      validated item wordings, capture responses,          │
│      compute scores per validated rules                   │
│    - PHQ-9, GAD-7, AUDIT-C, PROMIS instruments,           │
│      institution-specific screeners                       │
│    - Item 9 of PHQ-9 (or equivalent self-harm items)      │
│      is wired to the crisis-and-acuity pipeline           │
│                                                           │
│   [Tool: pro_administer (optional)]                       │
│    - Patient-reported-outcome instruments for visit       │
│      types where the institution captures longitudinal    │
│      PROs                                                 │
│           │                                               │
│           ▼                                               │
│   [Output: structured findings accumulating across the    │
│    conversation]                                          │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── CRISIS AND ACUITY FLAGGING ────────────────────┐
│                                                           │
│   [Pipeline runs in parallel with the conversation]       │
│                                                           │
│   [Crisis detection]                                      │
│    - Suicidal ideation, active self-harm, intent          │
│    - Domestic violence, abuse, intimate-partner           │
│      violence, child abuse                                │
│    - Active substance-use crisis                          │
│    - Acute medical emergency descriptions                 │
│                                                           │
│   [Red-flag clinical patterns]                            │
│    - Constellations the institution's protocol flags      │
│      (e.g., chest-pain-with-radiation-and-exertion in     │
│      adult, sudden-onset-severe-headache, acute           │
│      neurologic deficit description, GI bleeding          │
│      description, suicide intent endorsement on PHQ-9     │
│      item 9)                                              │
│    - Each flag has a routing target (same-day             │
│      clinical-staff callback, immediate crisis            │
│      pathway, urgent-care redirect)                       │
│                                                           │
│   [Significant new-information events]                    │
│    - New diagnosis the patient mentions                   │
│    - Hospitalization the chart does not show              │
│    - New medication from another provider                 │
│    - New allergy or adverse drug reaction                 │
│    - Significant change in functional status              │
│                                                           │
│   [Pipeline output]                                       │
│    - Crisis flags route immediately and modify the bot's  │
│      conversation flow (offer crisis resources, ask       │
│      consent for a same-day reach-out, ensure the         │
│      patient knows how to reach 911 or 988)               │
│    - Acuity flags route to clinical staff with the        │
│      relevant context attached                            │
│    - New-information events surface in the pre-visit      │
│      packet for the clinician's attention                 │
│           │                                               │
│           ▼                                               │
│   [Output: real-time flag events plus structured          │
│    flag list for the pre-visit packet]                    │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── OUTPUT SAFETY SCREENING ───────────────────────┐
│                                                           │
│   [Same primitive as the other chapter 11 recipes,        │
│    with intake-specific checks:]                          │
│    - Scope filter on generated response (no diagnostic    │
│      speculation, no treatment recommendation, no         │
│      symptom interpretation, no severity assessment)      │
│    - Vendor-managed guardrail layer                       │
│    - Hallucination check: did the bot reference a         │
│      chart fact that the chart-context tools did not      │
│      return? Did the bot mention a medication or          │
│      allergy not on the patient's list?                   │
│    - Persona-and-tone check: gentle, non-judgmental,      │
│      especially around sensitive disclosures              │
│           │                                               │
│           ▼                                               │
│   [Output: response cleared for delivery, or replaced     │
│    with a safer template]                                 │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── PRE-VISIT PACKET GENERATION ───────────────────┐
│                                                           │
│   [Tool: packet_assemble]                                 │
│    - Assembles the structured pre-visit packet from       │
│      accumulated findings:                                │
│      - Chief complaint                                    │
│      - HPI (structured plus the patient's verbatim        │
│        free-text)                                         │
│      - ROS findings (positive and negative)               │
│      - Medication-reconciliation deltas                   │
│      - Allergy-reconciliation deltas                      │
│      - History updates (PMH, surgical, family,            │
│        social)                                            │
│      - Screener scores and item-level responses           │
│      - Acuity flags and clinical-staff routing            │
│        events                                             │
│      - New-information events                             │
│      - The conversation transcript                        │
│      - Active protocol version and screener-bundle        │
│        version stamps                                     │
│                                                           │
│   [Tool: packet_deliver]                                  │
│    - Writes the packet to the EHR through the             │
│      institution's intake-data integration point          │
│      (FHIR QuestionnaireResponse, EHR-vendor's            │
│      pre-visit-note API, or the institution's             │
│      clinical-staging area for review-before-attach)     │
│    - Handles delivery failures with retry plus            │
│      operational alert                                    │
│                                                           │
│   [Closing summary to the patient]                        │
│    - The bot summarizes what was captured                 │
│    - Confirms with the patient                            │
│    - Sets expectations: "Dr. Adekunle will see this       │
│      before your visit. The clinical team may reach       │
│      out today if they have questions."                   │
│           │                                               │
│           ▼                                               │
│   [Output: durable pre-visit packet, EHR-side             │
│    delivery confirmation, conversation transcript]        │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── AUDIT, LOG, AND TELEMETRY ─────────────────────┐
│                                                           │
│   [Durable conversation record]                           │
│    - User utterances                                      │
│    - Tool calls with arguments and results                │
│    - Generated bot responses                              │
│    - Active model and prompt versions                     │
│    - Active protocol and screener-bundle versions         │
│    - Identity-verification outcome and assurance level    │
│    - Proxy relationship if applicable                     │
│    - Crisis flags raised, acuity flags raised             │
│    - Final disposition (completed, abandoned,             │
│      escalated, crisis-routed)                            │
│                                                           │
│   [Pre-visit-packet journal]                              │
│    - Durable, separately-governed record of every         │
│      packet: the patient, the encounter, the protocol     │
│      version, the screener scores, the acuity flags,      │
│      the EHR-side delivery confirmation                   │
│    - Retention sized to the institution's medical-        │
│      record-retention floor                               │
│                                                           │
│   [Operational telemetry]                                 │
│    - Completion rate per visit type                       │
│    - Median time-to-completion                            │
│    - Abandonment rate by stage                            │
│    - Resume rate                                          │
│    - Acuity-flag rate and routing-disposition mix         │
│    - Crisis-flag rate and crisis-pathway-engagement       │
│    - Screener positivity rates per screener               │
│    - Tool-call failure rate per tool                      │
│    - EHR delivery success rate                            │
│    - Per-cohort metric slices (language, channel, age,    │
│      visit type, proxy-completion, accessibility-needs)   │
│                                                           │
│   [Sampled review queue]                                  │
│    - Random sample plus targeted sample of low-           │
│      confidence and escalated conversations               │
│    - Reviewers tag failure modes (extraction error,       │
│      protocol-branch error, screener administration       │
│      error, scope-violation, crisis-handling correctness) │
│    - Clinical-leadership review of acuity-flagged         │
│      conversations for routing accuracy                   │
│           │                                               │
│           ▼                                               │
│   [Output: audit trail, telemetry, learning signals]      │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

A few cross-cutting design points specific to the intake bot.

**The intake protocol is a versioned governance artifact, organized per visit type.** Like the refill protocol, the intake protocols are clinical-leadership artifacts encoded as code. There is no single intake protocol; there is a library of per-visit-type protocols, each owned by the relevant clinical service line. Each protocol has versioning, sandbox testing against held-out conversations, staged rollout, audit-record stamping, and a clinical-informatics-team owner. The medical staff committee approves new protocols and major-version changes. When a screener bundle changes (the institution adopts a new social determinants of health (SDOH) screener for primary-care visits, for example), the relevant protocols are updated as a coordinated release.

**The screener tool library is governed separately.** Validated screening instruments (PHQ-9, GAD-7, AUDIT-C, PROMIS, fall-risk, SDOH bundles) each have their own tool with validated wordings, response options, and scoring rules. The library is owned jointly by clinical informatics, behavioral health (for the mental-health screeners), and the relevant clinical service lines (for condition-specific PROs). Each screener has its own version, and the bot's audit record stamps the screener version that was administered. Modifying a screener's wordings is a governance event that requires re-validation review, not a software change.

**The pre-visit packet schema is the bot's clinical-team-facing contract.** The packet schema is what the clinical team consumes. The schema is owned by clinical informatics with input from the clinical service lines that consume the packet. Schema changes are coordinated with EHR-side display logic so the clinician sees the packet as designed. The bot's packet-assembly tool produces output that conforms to the schema and validates before EHR delivery.

**Crisis and acuity flagging is a hard architectural floor.** Every patient utterance runs through the crisis-and-acuity pipeline in parallel with the conversation. The pipeline is a separate component, not a feature of the conversational LLM. The pipeline's hits trigger explicit response templates and explicit routing pathways. The patient-safety committee owns the pipeline's design. Tabletop drills exercise the crisis pathway quarterly. Failure to detect a crisis in retrospective review is a high-severity incident with a structured root-cause analysis.

**Medication and allergy reconciliation outputs do not modify the chart.** The bot captures patient-reported reconciliation deltas as structured events. The chart change is a clinical action that happens during or after the visit by an authorized clinician. The bot's reconciliation events are surfaced in the pre-visit packet for the clinician's attention; they are also written to the medication-reconciliation event journal for downstream clinical workflow.

**The conversation log is rich PHI and a clinical record.** The intake conversation contains chief complaint, HPI, ROS, medications, allergies, family history, social history, and screener responses. The log is dense PHI and many institutions treat it as part of the formal medical record. The institution's medical-records team owns the log's retention, access, and disclosure-accounting policies. The retention floor is the longest of HIPAA's six-year minimum, the state-specific medical-records retention rules, the state-specific consumer-privacy-law retention rules where applicable, and the institutional regulatory floor. 

**Per-cohort monitoring is non-negotiable, with intake-specific metric slices.** Completion rate, abandonment rate, time-to-completion, screener positivity, and acuity-flag rate vary substantially by language, age cohort, channel, visit type, and proxy-completion status. Equity-relevant disparities (a completion rate that is meaningfully lower for non-English-speaking patients than for English-speaking patients with the same visit type) is a launch-gate criterion, not a post-launch dashboard.

**Resumability is part of the architecture.** Patients fill out intake on lunch breaks, on phones with low batteries, in distracted environments. Conversation state, protocol position, and accumulated findings persist after each turn. Resume is graceful: the bot greets, summarizes what has been captured, asks if the patient wants to continue or restart, and proceeds.

**The pre-visit packet's display in the EHR is part of the deployment.** A bot that produces a beautiful packet that lands in a part of the EHR no clinician reads is worthless. The deployment includes the EHR-side display configuration: where the packet appears, how it is summarized at-a-glance, how clinicians click through to the full content, and how the acuity flags surface visually. This is institutional EHR-customization work that requires the EHR analysts' time.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter11.04-architecture). The Python example is linked from there.

## Related Recipes

- **Recipe 11.1 (FAQ Chatbot):** Same chapter, the foundational recipe. The intake bot inherits the input-screening pipeline, scope filtering, conversation logging, audit pattern, persona discipline, and per-cohort monitoring from the FAQ bot.
- **Recipe 11.2 (Appointment Scheduling Bot):** Same chapter. The intake bot is typically triggered by an upcoming appointment that the scheduling bot booked. The two bots share the encounter-context lookup and may share session state in unified-chat-surface deployments.
- **Recipe 11.3 (Prescription Refill Request Bot):** Same chapter, the previous transactional bot. The intake bot inherits the protocol-as-code lifecycle, the tool-surface contract, the structured-data extraction patterns, and the prescriber-delegation-equivalent governance (here applied to clinical-informatics-and-service-line-delegated intake protocols).
- **Recipe 11.5 (Insurance Benefits Navigator):** Same chapter. The intake bot may capture insurance updates that flow into benefits-navigator workflows; the benefits-navigator bot may surface coverage-related items that affect the intake's pre-procedure or pre-visit checks.
- **Recipe 11.6 (Symptom Checker / Triage Bot):** Same chapter. The intake bot's acuity-flag pipeline is conceptually adjacent to the triage bot's clinical-decision logic but is intentionally bounded to flagging-for-clinical-review rather than direct-to-patient triage decisions.
- **Recipe 11.7 (Chronic Disease Management Coach):** Same chapter. The intake bot's outputs feed the chronic-disease coach's longitudinal context; the coach's outputs may surface in the intake bot's prior-intake context.
- **Recipe 11.8 (Mental Health Support Bot):** Same chapter. The intake bot's mental-health screener results and crisis-flag events route into the mental-health support workflow; behavioral-health visit intake protocols draw on shared mental-health screening and crisis-handling patterns.
- **Recipe 10.5 (Patient-Facing Voice Assistant):** Chapter 10. The voice channel for intake builds on the voice assistant's automatic speech recognition (ASR) and text-to-speech (TTS) patterns.
- **Recipe 4.1 (Appointment Reminder Channel Optimization):** Chapter 4. The intake-invitation delivery pattern (when to send the link, through which channel) draws on recipe 4.1 patterns.
- **Recipe 4.2 (Patient Education Content Matching):** Chapter 4. The intake bot can surface visit-type-relevant education content for the patient based on the captured chief complaint.
- **Recipe 4.5 (Medication Adherence Intervention Targeting):** Chapter 4. The intake bot's medication-reconciliation deltas may surface adherence concerns that feed adherence-intervention workflows.
- **Recipe 4.7 (Care Management Program Enrollment):** Chapter 4. The intake bot's acuity flags and screener results may feed care-management enrollment criteria.
- **Recipe 5.6 (Claims-to-Clinical Data Linkage):** Chapter 5. The intake bot's chart-context lookup depends on the institution's data-linkage pipeline for cross-system data completeness.
- **Recipe 2.5 (After-Visit Summary Generation):** Chapter 2. The intake-bot pre-visit packet and the after-visit summary are the bookends of the visit-data lifecycle; they share clinical-content and patient-engagement design patterns.
- **Recipe 2.6 (Clinical Note Summarization):** Chapter 2. The intake-bot's HPI extraction and the clinical-note-summarization patterns are conceptually adjacent (both extract structured clinical content from prose).
- **Recipe 8.x (Validated screener administration as discrete clinical natural language processing (NLP) task):** Chapter 8. 

---

## Tags

`conversational-ai` · `function-calling` · `intent-classification` · `prompt-versioning` · `behavioral-health` · `clinical-decision-support` · `crisis-detection` · `medication-reconciliation` · `patient-engagement` · `ehr-integration` · `multilingual` · `accessibility` · `audit-trail` · `equity-monitoring` · `phi-handling` · `hipaa` · `bedrock-guardrails` · `prompt-injection-defense` · `scope-containment` · `persona-design` · `api-gateway` · `athena` · `bedrock` · `bedrock-agents` · `bedrock-knowledge-bases` · `cloudtrail` · `cloudwatch` · `comprehend-medical` · `connect` · `dynamodb` · `eventbridge` · `glue` · `healthlake` · `kinesis-firehose` · `kms` · `lambda` · `lex` · `quicksight` · `s3` · `secrets-manager` · `waf`
