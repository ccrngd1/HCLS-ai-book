# Recipe 11.6: Symptom Checker / Triage Bot

**Effort:** 4 of 5 · **Maturity:** Emerging · **Oversight:** Autonomous

---

## The Problem

It is 2:14 AM on a Tuesday. Devon is 47. He has woken up with a heavy, uncomfortable feeling in the middle of his chest. Not stabbing. Not tearing. More like a pressure, vaguely in the center, that came on while he was sleeping and is now keeping him awake. His left arm feels a little odd, but he is not sure if that is because he was sleeping on it. He is sweating slightly, but the bedroom is warm. He is 47 and otherwise healthy except for the fact that he has been told for several years that his cholesterol is "borderline." His father had a heart attack at 58. Devon's wife is asleep next to him. Devon does not want to wake her up over what is "probably nothing."

Devon does what a substantial fraction of Americans do at 2:14 AM with chest pressure: he opens his phone and types into a search engine. The search engine returns ten links. The first three are health-system pages titled "When to worry about chest pain." Each of those pages has a list of symptoms that "may indicate a heart attack" (chest pressure, arm pain, sweating, shortness of breath, nausea, jaw pain), a list of "less serious causes of chest pain" (acid reflux, muscle strain, anxiety, costochondritis), and a paragraph at the bottom that says "if you are experiencing severe chest pain, call 911 immediately." Each of those pages is correct. None of them is helpful to Devon, because Devon does not know whether his chest pain is severe. It is uncomfortable. It is keeping him awake. It is not crushing. He does not have the language his cardiologist would use, because he has never been to a cardiologist. He scrolls past the 911 disclaimer the way most people do, because he is not currently certain he is dying.

The fourth link is his health insurance plan's nurse-advice line. He calls. He waits on hold for eleven minutes, listening to a recording explaining that for emergencies he should hang up and dial 911. When the nurse picks up, she takes his name and his member ID, then asks the questions that Devon has been waiting for someone to ask: when did this start, where exactly is it, what does it feel like, has it changed, are you sweating, is your arm involved, is there any shortness of breath, any nausea, any history of heart problems in the family, any cardiac history of your own, what's your blood pressure normally, are you taking any medications. Devon answers. The nurse, after about four minutes, says "Devon, I want you to hang up the phone and call 911. Based on what you are telling me, I do not want you driving yourself, and I do not want you waiting until morning. Do you have someone there who can call?" Devon wakes up his wife. The ambulance arrives in fifteen minutes. Devon has a non-ST-elevation myocardial infarction. He goes to the cath lab at 4:47 AM. A stent is placed. He is discharged on Thursday afternoon.

Most people do not have nurses they can call at 2 AM. The ones who do are mostly insured commercial members, mostly during business hours; even the 24/7 nurse lines have substantial wait times during the overnight period when the most ambiguous symptoms are most likely to surface. Most people, instead, look at their phones, weigh "go to the ER" against "wait until morning," and try to decide based on incomplete and contradictory information. Some of them get it right. Some of them sit at home with a heart attack until morning. Some of them go to the ER for a panic attack and pay a $3,000 bill they cannot afford. Some of them, having been told the panic-attack ER bill was a waste, do not go in the next time they have chest pressure, because they have learned not to trust their own judgment. 

Now scale that to every patient with an ambiguous symptom every night across the country. The high-acuity patients who guess wrong miss the treatment window. The low-acuity patients who guess wrong overload emergency departments. The middle-acuity patients who guess wrong lose sleep, wages, and trust in the system. The cost is enormous; the cost is also distributed across people in ways that do not show up on any one institution's books. ED overuse is well-documented as a driver of healthcare cost.  Delay-in-treatment for time-sensitive conditions is well-documented as a driver of mortality. The patients in the middle, the ones who took the right action late or the wrong action at all, are the universal experience of American healthcare consumers, and most of them have been on Devon's side of the keyboard at some point.

The provider side has a parallel set of frustrations. Emergency departments are flooded with low-acuity visits whose patients should have been routed to urgent care, telehealth, primary care, or self-management. Primary care offices receive patient calls at 7:30 AM saying "I think I should have gone to the ER last night." Triage nurse lines staffed by experienced nurses are expensive, finite resources with wait times that scale poorly during periods of high call volume. Urgent care centers that could have absorbed the "actually a panic attack but feels real" presentation are sometimes empty while the ED waiting room has a four-hour wait. The misallocation is not anyone's fault but is everyone's problem. 

The frustrating thing, looking at this honestly, is that the questions Devon's nurse asked at 2:30 AM are not a mystery. There is a standard set of questions for chest pain ("is the pain pressure-like or sharp," "does it radiate to the arm or jaw," "is there sweating, nausea, shortness of breath," "what is the patient's age, sex, cardiac history, and family history"). There is a standard set of questions for headache, abdominal pain, fever, dizziness, shortness of breath, back pain, rash, and the few dozen other symptom presentations that drive most acute-care decisions. The questions live in nurse-triage protocols (Schmitt-Thompson is the most widely used in U.S. nurse advice lines for both pediatric and adult populations; the Manchester Triage System is widely used internationally; the Emergency Severity Index is the in-ED triage standard in the U.S.; clinical-decision rules like HEART and Wells exist for specific presentations).  The protocols encode decades of clinical experience. The patients have not had access to them, because the protocols are nurse-facing and require clinical judgment to apply. 

The previous generation of digital symptom checkers, when they tried to fix this, took two main shapes. The first was the static decision-tree symptom checker: "click the body part that hurts, click the symptom that matches, answer some yes/no questions, get a recommendation." Several major-vendor symptom checkers shipped this way, and the academic evaluations of them generally found that they over-triaged (sending too many patients to the ED) or under-triaged (missing high-acuity presentations) at rates that limited their clinical usefulness.  The second was the differential-diagnosis app: "based on your symptoms, here are the conditions you might have, ranked by probability." These were closer to "patient-facing differential generators" than to triage tools, and they confused patients and clinicians both. Several of them got into regulatory trouble for clinical claims their underlying logic could not actually support. The category became a cautionary tale.

The modern conversational triage bot looks like this. Devon, at 2:14 AM, opens the chat in his health system's app. He is authenticated, so the bot already knows his age, sex, basic chart context, and recent visit history. He types "I woke up with a pressure feeling in my chest and I'm not sure what to do."

The bot says "I'm sorry you're dealing with this. I'm going to ask you some questions to help figure out the best next step. I'm a chatbot, not a clinician, but the questions I'll ask are based on the same protocols our nurse advice line uses. If at any point you feel this is an emergency, please stop and call 911. Ready?"

Devon says yes.

The bot says "Where exactly is the pressure, and how long have you been feeling it? Try to be as specific as you can."

Devon types "right in the center of my chest, started maybe 30 minutes ago, woke me up."

The bot says "Got it. Is the pressure constant, or does it come and go? And on a scale of 1 to 10, where would you put the discomfort right now?"

Devon types "constant since I woke up. maybe a 5 or 6 out of 10."

The bot continues with the focused chest-pain protocol: does the pressure spread anywhere (arm, jaw, back), is there sweating, nausea, shortness of breath, lightheadedness, has anything like this happened before, any history of heart problems, any cholesterol or blood pressure issues, any family history of early heart problems. Devon answers each question. By turn ten, the bot has gathered the constellation of features that the chest-pain protocol flags as high-risk for acute coronary syndrome: pressure-quality discomfort, not exertional but new in onset, with associated diaphoresis and possible referred sensation, in a 47-year-old male with a borderline cholesterol history and a father with early MI.

The bot says "Devon, based on what you've described, I want you to call 911 right now. The combination of what you are feeling, your age, and your family history is concerning enough that I do not want you waiting until morning or driving yourself. Is there someone there with you who can help?"

Devon types "my wife is asleep."

The bot says "Please wake her up and call 911 together. While you wait for the ambulance, sit upright in a comfortable position. The dispatcher may ask whether he should take an aspirin. Let them make that call: whether it helps or harms depends on things like whether he is on a blood thinner and on what is actually causing the pain, and they are trained to decide that. If anything changes, tell the 911 operator. I'm staying here in case you want to talk while you wait. I've also flagged this conversation for our nurse-line team in case you need a follow-up later." 

That five-minute conversation, completed at 2:19 AM with Devon sitting up in bed, replaces the eleven minutes Devon would have spent on hold with the nurse line plus the four minutes for the actual triage call, in the cases where Devon was lucky enough to have a nurse line at all and persistent enough to wait through the hold. It uses the same questions the nurse would have used. It produces the same recommendation the nurse would have made. The recommendation is delivered at the moment Devon needed it, in a form Devon could actually follow.

A few things this recipe is and is not.

It is the bot that conducts a structured symptom-triage interview with a patient, captures the relevant clinical features through conversational questioning, applies an institution-validated triage protocol, and delivers an appropriate-care-level recommendation (self-care at home, telehealth visit, primary care or urgent care visit, emergency department visit, or 911). The recommendation is grounded in the protocol, presented with appropriate disclaimers, and routed to a human nurse-line escalation when the bot's confidence is low or the protocol calls for nurse review.

It is not a diagnosis tool. The bot does not tell the patient what condition they have. The bot does not produce a differential. The bot's output is "the appropriate next step is X," not "you have Y." The distinction matters legally, ethically, and clinically. Patient-facing diagnosis tools have a poor track record in the literature and a fraught regulatory history; the triage tool is the safer scope.

It is not the nurse advice line. The bot complements the nurse line; it does not replace it. The bot handles the volume that fits cleanly into protocol-driven triage with high-confidence recommendations. The bot escalates to a nurse for the cases that need clinical judgment, the cases at protocol-sanctioned hand-off points, and any case the patient asks to escalate. A bot deployed without a nurse-line backstop is missing the safety net.

It is not a regulatory afterthought. Patient-facing triage tools sit on or close to the FDA Software-as-a-Medical-Device line. Whether a specific deployment is regulated depends on the recommendations the tool produces, the population it serves, the claims the institution makes about it, and the current state of FDA guidance.  Production deployments require a regulatory strategy from day one. This recipe presents the architectural patterns. Your regulatory team is the authoritative source on whether and how those patterns apply to your specific deployment.

It is not a substitute for a clinician's judgment. The bot's output is a recommendation for what level of care the patient should seek. The bot does not provide treatment. The bot does not deliver diagnoses. When the bot says "you should be evaluated in the emergency department," the evaluation happens with a clinician who will make their own determination based on the patient's presentation in person. The bot's accuracy is bounded above by the protocol's accuracy and the bot's adherence to it; it does not exceed clinician judgment.

The thing to understand before building this is that the bot's quality is bounded above by the quality of the clinical triage protocol it implements, the discipline of the protocol-grounded retrieval, and the carefulness of the safety-net escalation logic. A bot operating against an under-specified protocol, with weak grounding, and with a permissive escalation policy will under-triage. A bot operating with the standard protocols, strict grounding, and conservative escalation will be measurably useful for the patients in the middle of the acuity distribution. The pre-deployment work of selecting, validating, and configuring the protocols is the highest-leverage investment the project will make, and it is the part most often underestimated.

Let's get into it.

---

## The Technology: Protocol-Grounded Conversational Triage With Conservative-By-Default Decision Logic

### What a Triage Bot Actually Does

Symptom triage has been a phone-and-nurse-centric workflow for fifty years, because the questions are symptom-specific and the calibration between care levels lives in clinical judgment. The modern shift is putting that same protocol-driven interview behind a conversational front-end.

A triage bot is a tool-using LLM with a system prompt that tells it which assistant it is, the patient's authenticated context (age, sex, basic chart history, current medications, current conditions, recent visits if relevant), and access to a structured library of institution-sanctioned triage protocols. The LLM conducts the conversation. The protocols, modeled as data, encode the clinical logic. The tools handle the deterministic actions: looking up the right protocol for the symptom, retrieving the relevant chart context, computing acuity scores from clinical-decision-rule inputs, escalating to a nurse line, posting a recommendation event for downstream operations, logging crisis-detection events to the appropriate response pathway.

The conversation has a structure even though the patient does not see it. The bot's task surface decomposes roughly as follows.

**The greeting and disclosure.** Critical for the triage bot specifically because patients have variable familiarity with what a chatbot can and cannot do, and the disclosure has to set expectations clearly without scaring the patient out of using the tool. Identifies as a chatbot, states scope (informational triage, not a diagnosis, not a replacement for a clinician), notes that the questions are based on the same protocols the institution's nurses use, names the human-escalation pathway, and reinforces the 911-redirect for emergencies.

**Crisis-and-emergency screening.** Before the protocol flow starts, the bot screens for the presentations that need no further questions, such as stroke signs, suicidal ideation with a plan, or crushing chest pain with sweating, and routes those straight to 911. Presentations that genuinely take a few questions to separate from something benign, which is most of them, get a short focused red-flag pass rather than a full protocol; the walkthrough above escalates after four questions. What the screening must never do is leave a red flag sitting behind a queue of protocol questions.

**Symptom identification and protocol selection.** The patient's free-form initial complaint is mapped to the most appropriate triage protocol. "Chest pressure" maps to the chest-pain protocol. "Bad headache" maps to the headache protocol. "I think I might have a UTI" maps to the urinary-symptoms protocol. The mapping is done by the LLM with retrieval over the protocol library. Ambiguous mappings (a patient with both chest pain and shortness of breath could route to either protocol) trigger a clarifying question. Multi-symptom presentations are handled by selecting the highest-acuity-eligible protocol and noting the others for cross-reference.

**Structured protocol-driven questioning.** Once the protocol is selected, the bot conducts the protocol's question sequence in conversational form. The protocol specifies the canonical questions. The bot may rephrase them for clarity, ask them in a slightly different order based on what the patient has already volunteered, and follow up on ambiguous answers. Critically, the bot does not skip protocol questions and does not invent new ones; the protocol is the spine, and the conversation hangs from it.

**Acuity scoring and recommendation.** When the protocol's questions have been answered, the bot computes the protocol's recommendation. For some protocols, this is a deterministic mapping from the answer set to the recommendation. For others, it is a clinical-decision rule (HEART score, Wells score, Centor score for streptococcal pharyngitis, Ottawa ankle rules) computed by a tool and used as input to the recommendation logic. The recommendation is one of a small set of care levels: self-care at home with monitoring, telehealth visit, primary care visit (today, in 24-48 hours, or routine), urgent care visit, emergency department visit, or 911 call. 

**Recommendation delivery with disclaimers and instructions.** The bot delivers the recommendation in plain English with the appropriate disclaimers, the rationale (briefly), and the next-step instructions. For high-acuity recommendations (911, ED), the instructions include immediate safety guidance (stay seated, do not drive yourself, call someone to be with you) and any institution-approved interim measures (the aspirin-for-suspected-MI example earlier; the bot's handling of these specifics depends entirely on the institution's clinical protocol and its FDA-strategy positioning). For low-acuity recommendations (self-care), the instructions include red-flag symptoms that should trigger re-triage and a path to re-engage with the bot or the nurse line.

**Nurse-line escalation and handoff.** When the protocol, low confidence, a poor protocol fit, or an explicit patient request calls for it, the bot hands the conversation to a nurse with the full context (transcript, protocol, answer set, recommendation) so the patient does not start over.

**Audit and follow-up.** Every conversation produces an audit record (transcript, protocol, recommendation, patient response, escalation status) that feeds compliance and clinical-quality review, and, where the institution can, is correlated with the patient's actual care utilization for calibration. 

### What Makes Triage Different (and Why a Generic LLM Isn't Enough)

A generalist LLM with a chat surface and some triage text pasted in breaks in specific, clinically consequential ways. Each failure mode has a matching architectural commitment the previous chapter-11 bots did not need. (Recipes 11.1 through 11.5 established the shared foundation: input and output safety, identity verification, tool-use orchestration, audit logging, per-cohort monitoring, scope discipline, and graceful degradation.)

**Grounded in the patient's chart, not just the conversation.** A generic model cannot calibrate "chest pain in a 25-year-old with no history" against "chest pain in a 65-year-old with hypertension and diabetes." Chart-context tools (age, sex, medications, conditions, recent visits) are non-optional inputs.

**Strict protocol grounding, not plausible-sounding advice.** Without citation-grounded retrieval over an institution-validated protocol corpus, the model produces recommendations that sound right but do not match the institution's protocol, or that contradict the standard of care. Every recommendation cites the protocol, its version, and the decision points behind it. That corpus is clinical content: medical-director-owned, versioned, reviewed on adoption and annually, with the active version logged per conversation.

**Conservative-by-default escalation, enforced deterministically.** A generic model's helpfulness instinct erodes the "when in doubt, escalate" bias the protocols are built on. The recommendation is computed by deterministic protocol logic; the LLM only delivers and explains it, never originates it. Conservative bias is a documented, audited policy, not an emergent property.

**Continuous emergency screening on every turn.** A patient who opens with "just a question about my back" may reveal, three turns in, lost leg sensation and bladder control which may point to a serious condition requiring a call to 911. Screening runs on every utterance and routes to 911 immediately, wherever the protocol flow is.

**Clinical-decision rules as deterministic tools.** LLMs compute HEART, Wells, Centor, and Ottawa scores poorly. The rule runs as code with structured inputs and outputs; the LLM gathers the inputs conversationally, calls the tool, and presents the score and its risk stratum. The tool version is audited.

**A defensible audit trail.** A regulated triage answer must show its work: the protocol consulted, the question sequence, the patient's responses, the computed acuity, and the basis for the recommendation. Without the structured ledger plus the conversation log, the recommendation is unreviewable and the regulatory position is untenable. This is also where the conversation's dense PHI, and any sensitive disclosures, are governed.

**Nurse-line escalation as a first-class primitive.** The bot ships with a backstop nurse line, not a fallback. Escalation triggers on low confidence, protocol hand-off points, poor protocol fit, an explicit patient request, or any safety flag, and hands off the full transcript, protocol, answer set, and computed recommendation so the patient never starts over.

**Scope discipline: triage, not diagnosis or treatment.** Patients ask "is this a heart attack?" and "should I take aspirin?" The bot answers the next-step question, not the diagnostic one. Holding that line takes the system prompt, the output-safety screening, the reviewed canonical responses, and the protocol scoping in alignment; none is sufficient alone. The walkthrough above is deliberate on exactly this point. While Devon waits for the ambulance the bot does not tell him to chew an aspirin; it hands that decision to the dispatcher. A named drug at a named dose is treatment, not triage, and it is the step that turns a triage tool into something a regulator will want to talk to you about. The bot can read a medication list but cannot know whether he actually took his anticoagulant this morning, and it cannot see an aortic dissection at all.

**FDA-strategy alignment from day one.** Patient-facing triage sits on or near the FDA Software-as-a-Medical-Device line; whether a deployment is regulated depends on its recommendations, its population, the claims the institution makes, and the current state of FDA guidance. The regulatory team is involved from architectural design through post-market surveillance, and the architecture supports either a non-regulated (informational) or a regulated (SaMD) posture.

### The Triage Reality

A few things make triage specifically harder than the other patient-facing bot use cases.

**Triage is multilingual by necessity.** Patients in crisis or in pain seek help in their first language. Multilingual deployment is a launch-day requirement for institutions serving non-English-speaking populations: validated protocol translations, validated regulatory-disclosure and emergency-instruction phrasings, and per-language calibration of the recommendation language.

**Accessibility is triage-specific.** Patients with limited digital literacy, vision impairments, cognitive impairments, or acute physical distress interact differently from the average app user. This is not a generic web-accessibility checklist; it is a set of decisions about cognitive load, sentence length, voice-channel availability, and graceful degradation when the patient cannot complete the conversation.

**Triage interacts with mandatory-reporting laws.** Some conversations surface disclosures (child or elder abuse, intimate-partner violence, certain mental-health emergencies) that trigger statutory reporting obligations for licensed staff. The bot is not a licensed clinician; institutional policy specifies that it acknowledges, provides safety resources, and routes to a mandatory-reporter staff member with the conversation context attached.

**Pediatric and geriatric cases need dedicated protocols.** Adult-default protocols miss them. Pediatric triage (Schmitt-Thompson Pediatric is the dominant U.S. standard) and geriatric triage (with frailty, polypharmacy, atypical presentations, and dementia-mediated communication) require their own protocols; protocol selection routes by the patient's age.

**Recommendations are clinically formal but socially feasible.** A patient without transportation cannot "go to urgent care now"; a patient without paid sick leave cannot "stay home and rest." Deploy social-determinants overlays and care-navigation handoffs where the recommended care level is not reachable for the patient.

**Triage integrates with the care plan and telehealth, bidirectionally.** Active oncology treatment or anticoagulation changes a presentation's acuity profile, so chart context includes active treatment plans and relevant medications. A "schedule a telehealth visit" recommendation should book the visit with the triage context attached, and a patient presenting soon after a telehealth visit should have that visit in context.

**Outcome correlation is a long-term commitment.** Clinical performance is measured against actual utilization: did the ED-referred patient go, and was there a clinically significant finding; did the stay-home patient need a higher-acuity visit within 72 hours. This is core post-market surveillance.

**Liability and consent differ from non-triage bots.** Patients consent to a tool that provides care-level recommendations; the consent language is reviewed with legal counsel, the handling of ignored recommendations is defined in institutional policy and the audit pathway, and the malpractice carrier is part of the review.

### Where the Field Has Moved

A few practical updates worth knowing.

**Protocol standards are established.** Schmitt-Thompson is the dominant U.S. nurse-line standard (adult and pediatric); the Manchester Triage System is the international ED-triage standard; the Emergency Severity Index is the U.S. in-ED standard. Institutions license one of these or build institution-specific protocols with clinical-leadership ownership. Building from scratch without a clinical foundation is rare and not recommended.

**Clinical-decision rules are increasingly used as triage components.** The HEART score (chest pain), the Wells score (PE and DVT), the Centor score (streptococcal pharyngitis), and the Ottawa ankle and knee rules stratify risk in specific presentations; modern architectures invoke them as deterministic tools when the protocol calls for them.

**The FDA's posture continues to evolve.** The 2022 Clinical Decision Support guidance clarified the regulated-versus-non-regulated line, but patient-facing triage faces more scrutiny than clinician-facing CDS, because the patient cannot independently verify the recommendation against their own judgment. Institutions deploying at scale work with FDA-experienced counsel from the design phase.

**Build-vs-buy is mature.** Several conversational-triage vendors operate at institution scale with EHR integration, multilingual support, and regulatory frameworks. Most institutions run a hybrid: build the member-facing bot in-house, license the clinical protocols, and integrate with the existing nurse-line, telehealth, and care-navigation infrastructure.

---

## General Architecture Pattern

A healthcare triage bot decomposes into ten logical stages: channel entry, input safety screening with continuous-emergency-screening, identity-and-chart-context loading, symptom identification and protocol selection, structured protocol-driven questioning, clinical-decision-rule computation, acuity scoring and recommendation, output safety screening with conservative-bias verification, recommendation delivery, and nurse-line escalation when applicable. The cross-cutting concerns from recipes 11.1 through 11.5 carry forward; this recipe adds four new ones (clinical-protocol-corpus governance with medical-director sign-off, conservative-bias-default policy, continuous-emergency-screening pipeline, and FDA-strategy-alignment artifact maintenance).

<style>
.vflow { margin:.6em 0 .6em .35em; border-left:2px solid #bcbcbc; }
.vflow .step { position:relative; padding:3.5px 0 3.5px 16px; line-height:1.32; font-size:0.9em; }
.vflow .step::before { content:""; position:absolute; left:-5.5px; top:.62em; width:7px; height:7px; border-radius:50%; background:#fff; border:1.6px solid #8a8a8a; }
</style>

<div class="vflow">
  <div class="step">Channel Entry</div>
  <div class="step">Input Safety + Continuous Emergency Screen</div>
  <div class="step">Identity + Chart-Context Loading</div>
  <div class="step">Symptom Identification + Protocol Selection</div>
  <div class="step">Structured Protocol-Driven Questioning</div>
  <div class="step">Clinical-Decision-Rule Computation</div>
  <div class="step">Acuity Scoring + Recommendation</div>
  <div class="step">Output Safety + Conservative-Bias Verify</div>
  <div class="step">Recommendation Delivery + Instructions</div>
  <div class="step">Nurse-Line Escalation (first-class)</div>
  <div class="step">Audit, Log, and Post-Market Surveillance</div>
</div>
A few cross-cutting design points specific to the triage bot.

**Clinical-protocol corpus governance with medical-director sign-off.** The protocols are clinical content. They are owned jointly by the medical director, the nurse-line operations leadership, and the compliance team. Each protocol is reviewed before adoption, reviewed annually, and re-reviewed when material updates are made. The protocols are versioned with effective dates; the conversation log records which protocol version was active for any given conversation. The medical director's signature is the launch gate for any protocol going into production.

**Conservative-bias-default policy.** When the bot is uncertain at any step (low intent classification confidence, ambiguous patient response, conflicting protocol-and-rule recommendations, low chart-context completeness), the policy is to escalate. The conservative-bias policy is documented, reviewed by the compliance team, and audited in the quality-review process.

**Continuous-emergency-screening pipeline.** Emergency screening is not a one-time check at conversation start. Every patient utterance runs through the screening layer. The screening uses both keyword detection and learned classifiers tuned for emergency feature constellations. Mid-conversation emergencies trigger immediate routing regardless of where the conversation was in the protocol flow. The pipeline's false-negative rate is monitored as a launch-gate metric.

**FDA-strategy-alignment artifact maintenance.** The institution's regulatory positioning (whether the deployment is informational, intended for clinician oversight in regulated edge cases, or registered as SaMD) is documented in the regulatory-strategy artifact. The artifact is reviewed by FDA-experienced regulatory counsel, updated as guidance evolves, and is the reference document for any new feature or any expansion of scope. Architectural changes that may affect regulatory positioning are reviewed against the artifact.

**Citation discipline as architectural primitive.** Every recommendation cites the protocol it was based on, the version of the protocol, the decision points within the protocol, and any clinical-decision rules used. The citation is structured (protocol_id, protocol_version, decision_point_id, rule_id, rule_score, rule_version) and the audit record preserves the citation trail. Reviewers and patients can be shown the cited evidence; the recommendation is reproducible.

**Clinical-decision-rule computation as deterministic tool.** Each clinical-decision rule used by the bot runs as code with structured inputs and outputs. The LLM gathers inputs, calls the tool, and presents the result. The tool's version is audited.

**Nurse-line escalation as first-class capability.** The bot is deployed with a backstop nurse line. The escalation handoff payload is comprehensive. The nurse picks up where the bot left off; the patient does not start over. The SLA for nurse-line response is documented, with separate SLAs for emergency-flagged versus non-emergency-flagged escalations.

**Per-cohort monitoring is non-negotiable.** Resolution rate, escalation rate, over-triage rate, under-triage rate, time-to-recommendation, and patient satisfaction vary by language, by channel, by pediatric-vs-adult, by age cohort, by sex, by presenting symptom category, by chart-context completeness. Per-cohort dashboards are reviewed by the medical director, the nurse-line operations team, the compliance team, and the patient-experience team.

**The conversation log is dense PHI plus may include sensitive disclosures.** Patients in triage may disclose mental-health crisis, intimate-partner violence, child or elder abuse, sexual-health concerns, substance use, and other topics covered by mandatory-reporting laws or by additional state-specific privacy frameworks. The audit, retention, access-control, and downstream-clinical-workflow story has to handle each of these with statutory awareness.

**Resumability across channels.** A patient who starts a conversation on the app, gets pulled away (perhaps by a worsening symptom that requires immediate action), and comes back through SMS or voice should be able to continue. Conversation state is keyed on patient_id with channel-specific session metadata, allowing cross-channel continuity for authenticated sessions.

**Disaster-recovery topology.** When the protocol corpus, the chart-context system, the clinical-decision-rule tool, or any downstream integration is unreachable, the bot degrades gracefully. The minimum behavior is "I'm having trouble pulling that data right now, please call our nurse line at [number]" or, in the case of detected emergency, immediate 911 routing. The graceful degradation paths are exercised in tabletop drills.

**Outcome-correlation pipeline as long-term commitment.** The bot's clinical performance is measured against actual care utilization, with per-protocol over-triage and under-triage rates calculated and fed back to the protocol-revision process. The outcome-correlation pipeline is operationally significant work, requires data integration across the institution's encounter records, and is rarely fully implemented at launch but is a core post-launch commitment.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter11.06-architecture). The Python example is linked from there.

## The Honest Take

**Buy versus build: buy, and treat building as a decision to take on medico-legal risk.** A competitive market of clinical-content vendors exists for exactly this. What you are buying is not the conversational layer, which is the easy part, but the clinical knowledge base, the validation studies behind the triage dispositions, and in some cases a regulatory filing and the liability that travels with it. Building means your institution owns the clinical content, its ongoing maintenance, its validation, and the consequences when a disposition is wrong. That is a defensible choice for a large system with real clinical-informatics depth and a reason to differentiate. It is an indefensible one if the motivation is that licensing looked expensive. Note also that triage is the function that most clearly crosses from documenting a conversation into supporting a diagnosis, which is the line regulators actually police, so the regulatory analysis belongs in the build-versus-buy decision rather than after it. Whichever way you go, the institutional content, the escalation paths, and the emergency-screening behavior described below remain yours to own.

The triage bot is the recipe in this chapter where the clinical stakes are highest, the regulatory exposure is most concentrated, and the accuracy floor matters most. It is also the recipe where the engineering discipline most directly translates to patient outcomes. A well-built triage bot keeps people from sitting at home with a heart attack until morning, and it keeps the urgent care from filling up with patients whose symptoms are best addressed at home with monitoring. A badly-built triage bot does the opposite, in either direction, and the failure modes have human costs.

The first trap, as with the previous bots, is treating the institutional content as someone else's problem. With the FAQ bot it was the parking policy. With the scheduling bot it was the visit-type catalog. With the refill bot it was the clinical refill protocol. With the intake bot it was the per-visit-type intake protocol library. With the benefits navigator it was the plan-document corpus and regulatory-disclosure phrasings library. With the triage bot it is the clinical-protocol corpus, the clinical-decision-rule library, the emergency-screening corpus, the regulatory-strategy artifact, and the chart-context integration. The single largest determinant of bot quality is the explicitness, completeness, currency, and clinical-leadership ownership of these artifacts. Most institutions discover, partway through the project, that their triage protocols are not actually written down in a form that can be programmatically retrieved, that the protocols their nurse line uses informally vary across nurses, and that the formal protocol documents need substantial work to be machine-actionable. Formalizing these artifacts is multi-quarter work that has to start before the engineering work and continue alongside it.

The second trap is underestimating the conservative-bias discipline. The protocols are designed with conservative bias; the bot's logic has to enforce it, and the LLM's default helpfulness instinct can erode it. Every architectural decision, every prompt revision, every guardrail, every output-safety check, every protocol-revision review, every per-cohort monitoring threshold has to be made with conservative bias as the explicit policy. A bot that sometimes under-triages a chest-pain presentation because the LLM was being helpful is the failure mode the architecture is supposed to prevent. The conservative-bias policy is a documented, reviewed, and audited commitment, not an emergent property.

The third trap is the regulatory positioning. Patient-facing triage tools sit on or close to the FDA SaMD line. The institutional positioning depends on the recommendations the tool produces, the population it serves, the claims the institution makes about it, and the current state of FDA guidance. The regulatory team is involved from architectural design, not at launch. The FDA-strategy artifact is reviewed by FDA-experienced regulatory counsel; building a deployment without one is a serious mistake.

The fourth trap is shipping without outcome correlation. The bot's clinical performance is bounded above by what can be measured. Outcome correlation against subsequent care utilization is operationally significant work, requires data integration across the institution's encounter records (and ideally claims data for cross-institution utilization), and is rarely fully implemented at launch but is a core post-launch commitment.

The fifth trap is shipping without an explicit equity commitment. Studies of nurse-line and ED triage have documented variability in recommendations by patient demographics that does not reflect underlying clinical reality. AI-mediated triage may inherit, amplify, or correct these disparities. The institutional commitment to equity is documented, reviewed, and operationalized through per-cohort monitoring with clinical-leadership sign-off on disparities thresholds.

---

## Related Recipes

- **Recipe 11.1 (FAQ Chatbot):** Same chapter, foundational. The triage bot inherits the input-screening pipeline, scope filtering, conversation logging, audit pattern, persona discipline, and per-cohort monitoring.
- **Recipe 11.2 (Appointment Scheduling Bot):** Same chapter. The triage bot's "schedule a primary care visit" or "schedule a telehealth visit" recommendations connect to the scheduling bot's booking infrastructure.
- **Recipe 11.3 (Prescription Refill Request Bot):** Same chapter. Some triage conversations surface medication-related concerns that route to the refill workflow with the triage context attached.
- **Recipe 11.4 (Pre-Visit Intake Bot):** Same chapter. The intake bot collects structured data feeding scheduled-visit clinicians; the triage bot collects structured data feeding acute-care decisions. The two bots share question patterns and chart-context tools.
- **Recipe 11.5 (Insurance Benefits Navigator):** Same chapter. Patients asking benefits questions sometimes need triage; patients asking triage questions sometimes need benefits guidance for the recommended care level.
- **Recipe 11.7 (Chronic Disease Management Coach):** Same chapter. Patients with chronic conditions presenting with acute symptoms in the coach's flow may route to the triage bot for acute-symptom assessment, with chronic-disease context preserved.
- **Recipe 11.8 (Mental Health Support Bot):** Same chapter. The triage bot's continuous emergency screening detects mental-health crisis disclosures and routes to the appropriate crisis pathway; the mental-health bot complements the triage bot for non-crisis behavioral-health support.
- **Recipe 11.9 (Care Coordination Assistant):** Same chapter. Patients in complex care journeys presenting with new acute symptoms may route to the triage bot with the care-coordination context preserved.
- **Recipe 1.4 (Prior Auth Document Processing):** Chapter 1. Patients receiving triage recommendations that require prior authorization may benefit from the prior-auth pipeline.
- **Recipe 2.6 (Clinical Note Summarization):** Chapter 2. The bot's chart-context-summary tool may be powered by clinical-note summarization for richer context.
- **Recipe 2.9 (Clinical Decision Support Synthesis):** Chapter 2. Clinician-facing CDS is a parallel pattern to patient-facing triage; the architectural patterns share concepts but the regulatory and design considerations differ substantially.
- **Recipe 4.7 (Care Management Program Enrollment):** Chapter 4. Patients with concerning patterns surfaced through triage may benefit from care-management enrollment.
- **Recipe 4.8 (Treatment Response Prediction):** Chapter 4. The triage bot's chart-context integration may include treatment-response signals for active-treatment-plan patients.
- **Recipe 7.1+ (Predictive Analytics / Risk Scoring, Chapter 7):** The clinical-decision rules used in the triage bot are a specific class of risk-scoring tools.
- **Recipe 10.1 (IVR Call Routing Enhancement):** Chapter 10. The voice-channel deployment of the triage bot integrates with the institution's IVR routing infrastructure.
- **Recipe 10.5 (Patient-Facing Voice Assistant):** Chapter 10. The voice channel for the triage bot builds on the voice assistant's ASR/TTS patterns.
- **Recipe 12.x (Forecasting & Time-Series Analysis):** Chapter 12. The outcome-correlation pipeline benefits from time-series patterns for tracking subsequent care utilization.
- **Recipe 13.x (Knowledge Graphs & Clinical Reasoning):** Chapter 13. The clinical-protocol corpus may be modeled as a knowledge graph for richer cross-protocol querying.

---

## Tags

`causal-inference` · `conversational-ai` · `rag` · `function-calling` · `intent-classification` · `prompt-versioning` · `crisis-detection` · `patient-engagement` · `ehr-integration` · `fhir` · `multilingual` · `accessibility` · `audit-trail` · `equity-monitoring` · `fda-pathway` · `mandatory-reporting` · `phi-handling` · `hipaa` · `regulatory-strategy` · `bedrock-guardrails` · `citation-grounding` · `prompt-injection-defense` · `scope-containment` · `persona-design` · `api-gateway` · `athena` · `bedrock` · `bedrock-agents` · `bedrock-knowledge-bases` · `cloudtrail` · `cloudwatch` · `connect` · `dynamodb` · `eventbridge` · `glue` · `healthlake` · `kinesis-firehose` · `kms` · `lambda` · `lex` · `opensearch-serverless` · `quicksight` · `s3` · `sagemaker` · `secrets-manager` · `waf`

---

*← [Recipe 11.5: Insurance Benefits Navigator](chapter11.05-insurance-benefits-navigator) · [Chapter 11 Index](chapter11-preface) · [Recipe 11.7: Chronic Disease Management Coach](chapter11.07-chronic-disease-management-coach) →*
