# Recipe 11.6: Symptom Checker / Triage Bot

**Complexity:** Medium-Complex · **Phase:** Regulated · **Estimated Cost:** ~$0.10-0.50 per completed triage conversation (depends on conversation length, model choice, clinical-protocol RAG depth, language coverage, and nurse-line escalation overhead)

---

## The Problem

It is 2:14 AM on a Tuesday. Devon is 47. He has woken up with a heavy, uncomfortable feeling in the middle of his chest. Not stabbing. Not tearing. More like a pressure, vaguely in the center, that came on while he was sleeping and is now keeping him awake. His left arm feels a little odd, but he is not sure if that is because he was sleeping on it. He is sweating slightly, but the bedroom is warm. He is 47 and otherwise healthy except for the fact that he has been told for several years that his cholesterol is "borderline." His father had a heart attack at 58. Devon's wife is asleep next to him. Devon does not want to wake her up over what is "probably nothing."

Devon does what a substantial fraction of Americans do at 2:14 AM with chest pressure: he opens his phone and types into a search engine. The search engine returns ten links. The first three are health-system pages titled "When to worry about chest pain." Each of those pages has roughly the same structure: a list of symptoms that "may indicate a heart attack" (chest pressure, arm pain, sweating, shortness of breath, nausea, jaw pain), a list of "less serious causes of chest pain" (acid reflux, muscle strain, anxiety, costochondritis), and a paragraph at the bottom that says "if you are experiencing severe chest pain, call 911 immediately." Each of those pages is correct. None of them is helpful to Devon, because Devon does not know whether his chest pain is severe. It is uncomfortable. It is keeping him awake. It is not crushing. He does not have the language his cardiologist would use, because he has never been to a cardiologist. He scrolls past the 911 disclaimer the way most people do, because he is not currently certain he is dying.

The fourth link is his health insurance plan's nurse-advice line. He calls. He waits on hold for eleven minutes, listening to a recording explaining that for emergencies he should hang up and dial 911. When the nurse picks up, she takes his name and his member ID, then asks the questions that Devon has been waiting for someone to ask: when did this start, where exactly is it, what does it feel like, has it changed, are you sweating, is your arm involved, is there any shortness of breath, any nausea, any history of heart problems in the family, any cardiac history of your own, what's your blood pressure normally, are you taking any medications. Devon answers. The nurse, after about four minutes, says "Devon, I want you to hang up the phone and call 911. Based on what you are telling me, I do not want you driving yourself, and I do not want you waiting until morning. Do you have someone there who can call?" Devon wakes up his wife. The ambulance arrives in fifteen minutes. Devon has a non-ST-elevation myocardial infarction. He goes to the cath lab at 4:47 AM. A stent is placed. He is discharged on Thursday afternoon.

This is healthcare triage in the United States in 2026, and it is among the most consequential and least systematically supported decisions a patient ever makes. Most people do not have nurses they can call at 2 AM. The ones who do are mostly insured commercial members, mostly during business hours; even the 24/7 nurse lines have substantial wait times during the overnight period when the most ambiguous symptoms are most likely to surface. Most people, instead, look at their phones, weigh "go to the ER" against "wait until morning," and try to decide based on incomplete and contradictory information. Some of them get it right. Some of them sit at home with a heart attack until morning. Some of them go to the ER for a panic attack and pay a $3,000 bill they cannot afford. Some of them, having been told the panic-attack ER bill was a waste, do not go in the next time they have chest pressure, because they have learned not to trust their own judgment. <!-- TODO: verify; the literature on patient-decision-making for ambiguous acute symptoms documents wide variability in care-seeking patterns by income, geography, race, gender, age, and prior healthcare experience, with significant disparities in time-to-treatment for time-sensitive conditions like myocardial infarction and stroke; specific aggregate figures vary by source -->

Now scale that to every patient with an ambiguous symptom every night across the country. The high-acuity patients who guess wrong miss the treatment window. The low-acuity patients who guess wrong overload emergency departments. The middle-acuity patients who guess wrong lose sleep, wages, and trust in the system. The cost is enormous; the cost is also distributed across people in ways that do not show up on any one institution's books. ED overuse is well-documented as a driver of healthcare cost. <!-- TODO: verify; ED utilization patterns and the fraction of visits classifiable as non-emergent are widely studied with figures varying by methodology --> Delay-in-treatment for time-sensitive conditions is well-documented as a driver of mortality. The patients in the middle, the ones who took the right action late or the wrong action at all, are the universal experience of American healthcare consumers, and most of them have been on Devon's side of the keyboard at some point.

The provider side has a parallel set of frustrations. Emergency departments are flooded with low-acuity visits whose patients should have been routed to urgent care, telehealth, primary care, or self-management. Primary care offices receive patient calls at 7:30 AM saying "I think I should have gone to the ER last night." Triage nurse lines staffed by experienced nurses are expensive, finite resources with wait times that scale poorly during periods of high call volume. Urgent care centers that could have absorbed Devon's neighbor's "actually a panic attack but feels real" presentation are sometimes empty while the ED waiting room has a four-hour wait. The misallocation is not anyone's fault and everyone's problem. <!-- TODO: verify; specific figures on ED-to-urgent-care reroute potential and triage-line capacity vary; the directional finding that significant fractions of ED utilization is amenable to lower-acuity routing is broadly supported in healthcare operations research -->

The frustrating thing, looking at this honestly, is that the questions Devon's nurse asked at 2:30 AM are not a mystery. There is a standard set of questions for chest pain ("is the pain pressure-like or sharp," "does it radiate to the arm or jaw," "is there sweating, nausea, shortness of breath," "what is the patient's age, sex, cardiac history, and family history"). There is a standard set of questions for headache, abdominal pain, fever, dizziness, shortness of breath, back pain, rash, and the few dozen other symptom presentations that drive most acute-care decisions. The questions live in nurse-triage protocols (Schmitt-Thompson is the most widely used in U.S. nurse advice lines for both pediatric and adult populations; the Manchester Triage System is widely used internationally; the Emergency Severity Index is the in-ED triage standard in the U.S.; clinical-decision rules like HEART and Wells exist for specific presentations). <!-- TODO: verify; Schmitt-Thompson protocols, the Manchester Triage System, the Emergency Severity Index, the HEART score for chest pain, the Wells score for pulmonary embolism and deep vein thrombosis, and similar clinical-decision tools are well-established in the literature; specific protocol versions and licensing arrangements vary --> The protocols encode decades of clinical experience. The patients have not had access to them, because the protocols are nurse-facing and require clinical judgment to apply. The decision tree exists; the patient cannot navigate it alone.

The previous generation of digital symptom checkers, when they tried to fix this, took two main shapes. The first was the static decision-tree symptom checker: "click the body part that hurts, click the symptom that matches, answer some yes/no questions, get a recommendation." Several major-vendor symptom checkers shipped this way, and the academic evaluations of them generally found that they over-triaged (sending too many patients to the ED) or under-triaged (missing high-acuity presentations) at rates that limited their clinical usefulness. <!-- TODO: verify; published evaluations of digital symptom checkers including studies by Semigran et al. 2015, Hill et al. 2020, and others have documented variable accuracy with both over-triage and under-triage failure modes; specific accuracy figures depend on the symptom checker, the population, and the methodology --> The second was the differential-diagnosis app: "based on your symptoms, here are the conditions you might have, ranked by probability." These were closer to "patient-facing differential generators" than to triage tools, and they confused patients and clinicians both. Several of them got into regulatory trouble for clinical claims their underlying logic could not actually support. The category became a cautionary tale.

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

The bot says "Please wake her up and call 911 together. While you wait for the ambulance, sit upright in a comfortable position. If you have aspirin in the house and you are not allergic to it, the standard guidance is to chew one regular aspirin (325 mg) or four baby aspirin (81 mg each), but only if you can do that without difficulty. If anything changes, tell the 911 operator. I'm staying here in case you want to talk while you wait. I've also flagged this conversation for our nurse-line team in case you need a follow-up later." <!-- TODO: verify; the aspirin-during-suspected-MI guidance is established in cardiac care for adults without contraindications, but specific patient-facing language for aspirin recommendations should be reviewed against the institution's clinical protocol; some triage tools defer all medication advice including aspirin to the 911 operator -->

That five-minute conversation, completed at 2:19 AM with Devon sitting up in bed, replaces the eleven minutes Devon would have spent on hold with the nurse line plus the four minutes for the actual triage call, in the cases where Devon was lucky enough to have a nurse line at all and persistent enough to wait through the hold. It uses the same questions the nurse would have used. It produces the same recommendation the nurse would have made. The recommendation is delivered at the moment Devon needed it, in a form Devon could actually follow.

A few things this recipe is and is not.

It is the bot that conducts a structured symptom-triage interview with a patient, captures the relevant clinical features through conversational questioning, applies an institution-validated triage protocol, and delivers an appropriate-care-level recommendation (self-care at home, telehealth visit, primary care or urgent care visit, emergency department visit, or 911). The recommendation is grounded in the protocol, presented with appropriate disclaimers, and routed to a human nurse-line escalation when the bot's confidence is low or the protocol calls for nurse review.

It is not a diagnosis tool. The bot does not tell the patient what condition they have. The bot does not produce a differential. The bot's output is "the appropriate next step is X," not "you have Y." The distinction matters legally, ethically, and clinically. Patient-facing diagnosis tools have a poor track record in the literature and a fraught regulatory history; the triage tool is the safer scope.

It is not a clinical-decision-support tool aimed at clinicians. Recipe 2.9 (clinical decision support synthesis) covers the clinician-facing pattern. This recipe is patient-facing, and the regulatory and design considerations are substantially different.

It is not the nurse advice line. The bot complements the nurse line; it does not replace it. The bot handles the volume that fits cleanly into protocol-driven triage with high-confidence recommendations. The bot escalates to a nurse for the cases that need clinical judgment, the cases at protocol-sanctioned hand-off points, and any case the patient asks to escalate. A bot deployed without a nurse-line backstop is missing the safety net.

It is not a regulatory afterthought. Patient-facing triage tools sit on or close to the FDA Software-as-a-Medical-Device line. Whether a specific deployment is regulated depends on the recommendations the tool produces, the population it serves, the claims the institution makes about it, and the current state of FDA guidance. <!-- TODO: verify; the FDA's 2022 final guidance on Clinical Decision Support software clarified the boundary between regulated and non-regulated software, but patient-facing triage tools generally face more scrutiny than clinician-facing CDS, and the regulatory landscape continues to evolve --> Production deployments require a regulatory strategy from day one. This recipe presents the architectural patterns; your regulatory team is the authoritative source on whether and how those patterns apply to your specific deployment.

It is not a chronic-disease coach. Recipe 11.7 covers ongoing conversational support for managing established chronic conditions over time. The triage bot is acute and episodic. It answers "what should I do right now?" not "how am I doing this week?"

It is not a mental health support bot. Recipe 11.8 covers conversational support for mental health concerns. The triage bot recognizes mental-health crisis as one of the highest-acuity flags and routes immediately to crisis resources (988 or 911) rather than attempting to provide therapeutic content.

It is not the pre-visit intake bot. Recipe 11.4 covers structured pre-visit intake feeding scheduled appointments. The triage bot answers "should I see anyone right now?" The intake bot answers "what should the clinician know before we see each other on Wednesday?" The two have overlapping question sets and very different success criteria.

It is not a substitute for a clinician's judgment. The bot's output is a recommendation for what level of care the patient should seek. The bot does not provide treatment. The bot does not deliver diagnoses. When the bot says "you should be evaluated in the emergency department," the evaluation happens with a clinician who will make their own determination based on the patient's presentation in person. The bot's accuracy is bounded above by the protocol's accuracy and the bot's adherence to it; it does not exceed clinician judgment.

The thing to understand before building this is that the bot's quality is bounded above by the quality of the clinical triage protocol it implements, the discipline of the protocol-grounded retrieval, and the carefulness of the safety-net escalation logic. A bot operating against an under-specified protocol, with weak grounding, and with a permissive escalation policy will under-triage. A bot operating with the standard protocols, strict grounding, and conservative escalation will be measurably useful for the patients in the middle of the acuity distribution. The pre-deployment work of selecting, validating, and configuring the protocols is the highest-leverage investment the project will make, and it is the part most often underestimated.

Let's get into it.

---

## The Technology: Protocol-Grounded Conversational Triage With Conservative-By-Default Decision Logic

### Why Symptom-Triage Has Stayed Phone-Centric (And Why Most Web Symptom Checkers Failed)

Symptom triage, as a workflow, has been a phone-centric problem for the last fifty years and has been done by experienced nurses for almost all of that time. The reason is structural. Symptom triage is the process of taking a patient's free-form description of what they are feeling, asking the focused follow-up questions that disambiguate the clinically-relevant features, and matching the resulting feature constellation to an institution-sanctioned recommendation about what the patient should do next. The questions are not generic. The questions for chest pain are different from the questions for headache. The questions for headache in a 78-year-old with hypertension are different from the questions for headache in a 28-year-old with no history. The recommendations are not binary. The recommendation is not "go to the ER" or "stay home"; the recommendation is one of several appropriate care levels (self-care, telehealth, primary care, urgent care, ED, 911) calibrated to the acuity of the presentation and the patient's specific context. The clinical judgment lives in the calibration; it has lived in nurses' heads, supplemented by paper protocols, since the workflow began.

The first generation of digital symptom checkers, roughly the early 2000s through the late 2010s, tried to systematize this with explicit decision-tree software. The patient clicked through a tree of yes/no questions and received a recommendation at the leaf. The trees were sometimes built by clinicians and sometimes purchased from vendors who claimed they were. Several of the major-vendor symptom checkers received high-profile evaluations in the medical literature. The findings were not flattering. <!-- TODO: verify; published evaluations of digital symptom checkers including Semigran et al. 2015 in BMJ, Hill et al. 2020 in MJA, Ceney et al. 2021 in PLOS ONE, and others have documented variable accuracy with both over-triage and under-triage failure modes; specific accuracy figures depend on the symptom checker, the population, and the methodology --> The decision-tree symptom checkers had three structural problems. First, they could only ask the questions encoded in the tree, which meant they could not follow up on what the patient had actually said. Second, the patient's free-text description of symptoms had to be coerced into the tree's pre-defined symptom categories, which destroyed nuance and produced wrong matches. Third, the trees were rigid; if the patient's presentation did not fit cleanly into a tree branch, the tree silently picked a branch and produced a recommendation that did not actually correspond to the patient's situation. The patients who used these tools mostly did not trust them; the clinicians who reviewed their outputs mostly did not trust them either.

The second generation, roughly 2015 to 2022, layered machine-learning models on top of the symptom inputs. The architecture varied (some used neural networks, some used Bayesian networks, some used probabilistic graphical models with named conditions as nodes), but the user-facing pattern was similar: enter symptoms, get a ranked differential or a recommended action. Several of these tools secured significant funding, partnered with health systems and insurers, and faced public criticism over both their clinical accuracy and the regulatory claims their marketing departments made about them. <!-- TODO: verify; the trajectory of differential-generating symptom checkers including products from Babylon Health, Buoy Health, Ada, K Health, Mayo Clinic, Isabel Healthcare, and others has been documented in trade press and academic literature; specific accuracy figures and regulatory actions vary by product and time period --> Some of them retrenched their scope to lower-acuity guidance. Some of them shut down. The category became a cautionary tale in healthcare AI circles, often cited as the example of "things that look like they should work but require careful clinical and regulatory engineering to actually deliver value safely."

The thing that changed the workflow shape is, again, large language models that can carry on a coherent conversation while sticking to a structured task. A conversational triage interview, conducted by an LLM that has been carefully scoped to follow institution-validated protocols, can ask the focused follow-up questions a nurse would ask, capture the patient's nuanced responses without forcing them into pre-defined categories, and produce a recommendation that is grounded in the same protocol the nurse would have used. The LLM's value is concentrated in the conversational layer; the clinical logic still lives in the protocol. The LLM is a better front-end to a triage protocol than a decision-tree was, and the protocol is the part that matters clinically.

The architectural shift is from "click through a decision tree" to "have a conversation that follows the protocol." The bot's value is concentrated in three places: the patient experience (asking a natural-language question and getting a specific recommendation in minutes rather than waiting on hold or guessing alone), the safety floor (the protocol-driven logic plus the human-escalation path catch the high-acuity cases that ad-hoc patient self-triage misses), and the operational savings (the routine triage volume is handled at the bot tier, freeing the nurse line for the cases that benefit from clinical judgment).

### What a Triage Bot Actually Does

A triage bot is a tool-using LLM with a system prompt that tells it which assistant it is, the patient's authenticated context (age, sex, basic chart history, current medications, current conditions, recent visits if relevant), and access to a structured library of institution-sanctioned triage protocols. The LLM conducts the conversation. The protocols, modeled as data, encode the clinical logic. The tools handle the deterministic actions: looking up the right protocol for the symptom, retrieving the relevant chart context, computing acuity scores from clinical-decision-rule inputs, escalating to a nurse line, posting a recommendation event for downstream operations, logging crisis-detection events to the appropriate response pathway.

The conversation has a structure even though the patient does not see it. The bot's task surface decomposes roughly as follows.

**The greeting and disclosure.** Critical for the triage bot specifically because patients have variable familiarity with what a chatbot can and cannot do, and the disclosure has to set expectations clearly without scaring the patient out of using the tool. Identifies as a chatbot, states scope (informational triage; not a diagnosis; not a replacement for a clinician), notes that the questions are based on the same protocols the institution's nurses use, names the human-escalation pathway, and reinforces the 911-redirect for emergencies.

**Crisis-and-emergency screening up front.** Before the protocol-driven triage starts, the bot screens for explicit emergency presentations. If the patient says "I'm having chest pain right now," the bot does not start a structured chest-pain protocol from scratch; it asks two or three high-yield questions to confirm the emergency presentation and routes immediately to 911 with stay-on-the-line guidance. If the patient says "I'm thinking about hurting myself," the bot routes immediately to 988 or the institution's crisis line. The screening is layered with the protocol selection rather than gated behind it.

**Symptom identification and protocol selection.** The patient's free-form initial complaint is mapped to the most appropriate triage protocol. "Chest pressure" maps to the chest-pain protocol. "Bad headache" maps to the headache protocol. "I think I might have a UTI" maps to the urinary-symptoms protocol. The mapping is done by the LLM with retrieval over the protocol library; ambiguous mappings (a patient with both chest pain and shortness of breath could route to either protocol) trigger a clarifying question. Multi-symptom presentations are handled by selecting the highest-acuity-eligible protocol and noting the others for cross-reference.

**Structured protocol-driven questioning.** Once the protocol is selected, the bot conducts the protocol's question sequence in conversational form. The protocol specifies the canonical questions; the bot may rephrase them for clarity, ask them in a slightly different order based on what the patient has already volunteered, and follow up on ambiguous answers. Critically, the bot does not skip protocol questions and does not invent new ones; the protocol is the spine, and the conversation hangs from it.

**Acuity scoring and recommendation.** When the protocol's questions have been answered, the bot computes the protocol's recommendation. For some protocols, this is a deterministic mapping from the answer set to the recommendation. For others, it is a clinical-decision rule (HEART score, Wells score, Centor score for streptococcal pharyngitis, Ottawa ankle rules) computed by a tool and used as input to the recommendation logic. The recommendation is one of a small set of care levels: self-care at home with monitoring, telehealth visit, primary care visit (today, in 24-48 hours, or routine), urgent care visit, emergency department visit, or 911 call. <!-- TODO: verify; the HEART score, Wells score, Centor score, Ottawa ankle rules, and similar clinical-decision rules are well-established in the literature with documented sensitivity and specificity profiles; the specific protocol implementations and care-level mappings vary by institution -->

**Recommendation delivery with disclaimers and instructions.** The bot delivers the recommendation in plain English with the appropriate disclaimers, the rationale (briefly), and the next-step instructions. For high-acuity recommendations (911, ED), the instructions include immediate safety guidance (stay seated, do not drive yourself, call someone to be with you) and any institution-approved interim measures (the aspirin-for-suspected-MI example earlier; the bot's handling of these specifics depends entirely on the institution's clinical protocol and its FDA-strategy positioning). For low-acuity recommendations (self-care), the instructions include red-flag symptoms that should trigger re-triage and a path to re-engage with the bot or the nurse line.

**Nurse-line escalation.** The bot escalates to a human nurse when the protocol calls for it (some protocols escalate at specific decision points), when the bot's confidence in any step is below threshold, when the patient's presentation does not fit cleanly into any protocol, when the patient explicitly requests a human, or when any layer (input safety, output safety) flags an issue. The escalation hands off the conversation transcript, the protocol selected, the answer set captured, the computed recommendation, and any uncertainty markers.

**Cross-channel continuity.** A patient who starts on chat and needs to switch to a nurse phone call should not have to start over. The escalation includes the conversation context as a structured payload that the receiving nurse can read in seconds. The patient's wait time at the nurse line is bounded; the institution's commitment to the patient is that the bot will catch high-acuity cases regardless of nurse-line availability.

**Audit and follow-up.** Every triage conversation produces an audit record (transcript, protocol used, recommendation produced, recommendation delivered, patient response, escalation status). The audit feeds compliance review, clinical-quality review, and outcome-tracking. Where the institution has the capability, the bot's recommendation is correlated with the patient's actual care utilization (did they actually go to the ED, the urgent care, did they have a follow-up encounter) for ongoing protocol-and-bot calibration. <!-- TODO: verify; outcome-correlation for symptom-triage tools requires institutional data integration and is operationally significant work; specific implementations vary -->

### Why a Generic LLM Cannot Run a Triage Bot

A naive product approach would be: take a generalist LLM, give it a chat surface, paste in some triage information, and have it conduct triage. This breaks in several specific ways, each of which has clinical and regulatory consequences.

**The model has no view of the patient's specific clinical context.** Without the patient's age, sex, current medications, current conditions, and basic recent history as input, the LLM cannot calibrate the recommendation appropriately. "Chest pain in a 25-year-old with no history" is a different protocol entry-point than "chest pain in a 65-year-old with hypertension and diabetes." The chart-context tools (age, sex, problem list, medication list, recent visits) are non-optional inputs. The bot is not blind to the patient's record; it is grounded in it.

**The model hallucinates clinical content when grounding is weak.** If the protocols are not retrieved with strict citation grounding, the LLM produces plausible-sounding clinical recommendations that are wrong for the institution's actual protocol. Worse, the LLM may produce recommendations that contradict the standard of care. The protocol RAG layer with strict citation grounding is non-negotiable. The bot cites the protocol it is following, the version of the protocol that is in effect, and the specific decision points from the protocol that drove the recommendation.

**The model has no reliable theory of conservative-by-default escalation.** Without explicit guardrails, the LLM tends toward "let me try to help you figure this out" responses that under-triage when they should escalate. The protocols are designed with conservative bias (when in doubt, escalate to higher acuity); the LLM's default helpfulness instinct can erode that bias. The architectural pattern is to encode the conservative-default policy in the protocol logic, run the recommendation through deterministic computation, and have the LLM only deliver and explain the recommendation rather than originate it.

**The model cannot reliably recognize a true emergency in the middle of a conversation.** A patient who starts with "I just have a question about my back" and then mentions, three turns in, that they have lost the ability to feel their legs and have lost bladder control is presenting cauda equina syndrome (a 911 case) inside a conversation that started as a low-acuity question. <!-- TODO: verify; cauda equina syndrome is a recognized neurosurgical emergency; specific clinical features include saddle anesthesia, urinary retention or incontinence, and progressive lower-extremity weakness --> The bot's emergency screening runs continuously, not just at the start of the conversation. Every patient utterance is screened for emergency keywords and feature constellations.

**The model has no audit trail of what was asked, what was answered, what was retrieved, and what was recommended.** A regulated triage answer requires showing the work: the protocol consulted, the question sequence, the patient's responses, the computed acuity, the basis for the recommendation. The structured-data ledger plus the conversation log are the audit surface. Without it, the recommendation is unreviewable, the case is impossible to defend if outcomes are bad, and the regulatory position is untenable.

**The model has clinical-decision-rule arithmetic problems.** Clinical-decision rules (HEART, Wells, Centor, Ottawa, others) compute scores from structured inputs. The LLM does this arithmetic poorly. The clinical-decision-rule tool encapsulates the computation; the LLM gathers the inputs through the conversation, calls the tool, and presents the structured score and its associated risk stratum.

**The model has compliance implications for triage conversations.** The conversation contains PHI (symptoms, medical history, mental-health status, social context that may emerge during sensitive triage). Some triage conversations include disclosures of intimate-partner violence, sexual-health concerns, substance-use issues, and mental-health crisis. The audit, retention, access-control, and downstream-clinical-workflow integration story has to handle each of these with care and with statutory awareness (for example, mandatory-reporting obligations for some disclosures vary by state and by professional credential of the receiving party).

**The model cannot reliably stay within scope when the patient asks for diagnosis or treatment recommendations.** Patients frequently ask "do you think this is a heart attack?" or "should I take aspirin?" The bot answers triage questions ("the next step for what you are describing is X") not diagnostic questions ("you have Y"). Maintaining the distinction is a discipline that requires the system prompt, the output safety screening, the institutional review of canonical responses, and the clinical-protocol scoping to all align. None is sufficient alone.

**The model has no theory of when to stop the conversation.** A protocol's question sequence has a defined length. Once the relevant features are captured, the bot computes the recommendation. A general LLM might continue conversing indefinitely, asking irrelevant questions, or sliding into therapeutic chat. The protocol-driven logic encodes the stopping condition; the LLM honors it.

### What the Triage Bot Has To Do That the Previous Bots Did Not

Recipes 11.1 through 11.5 established the patterns this recipe inherits: input safety screening, intent classification, identity verification, tool-use orchestration, output safety screening, audit logging, per-cohort monitoring, scope discipline, prompt-injection defense, graceful degradation. The triage bot adds six structural commitments those recipes did not have.

**Validated clinical-protocol corpus with full version control and clinician sign-off.** The triage protocols are clinical content. They are owned jointly by the institution's medical director, the nurse-triage operations leadership, and the compliance team. Each protocol is reviewed before adoption, reviewed annually, and re-reviewed when material updates are made. The protocols are versioned; the conversation log records which protocol version was active for any given conversation. Skipping this is the failure mode that turns a triage bot into a clinically-unsafe deployment.

**Conservative-by-default acuity logic.** The protocols are designed with conservative bias; the bot's logic enforces it. When the bot is uncertain, when the protocol's decision logic spans multiple acuity levels, when the patient's responses are ambiguous, the recommendation defaults to the higher acuity (or escalates to a nurse). Explicit conservative-bias auditing is part of the deployment review.

**Continuous emergency-screening across every turn.** The crisis-and-emergency screening runs continuously through the conversation, not just at the start. Every patient utterance is screened for emergency keywords and feature constellations. The screening triggers immediate 911 or 988 routing as appropriate, regardless of where the conversation was in the protocol flow.

**Clinical-decision-rule computation as deterministic tool.** Clinical-decision rules used in the triage logic (HEART, Wells, Centor, Ottawa, others) run as code with structured inputs and structured outputs. The LLM does not compute the score. The deterministic tool returns the score with the associated risk stratum and the protocol-mapped recommendation. The tool's version is audited.

**Nurse-line escalation as architectural primitive, not optional feature.** The bot is deployed with a backstop nurse line. The escalation is a first-class capability, not a fallback. The handoff payload includes the full conversation context, the protocol consulted, the answer set, and the computed recommendation. The nurse picks up where the bot left off; the patient does not start over.

**FDA-strategy alignment from day one.** Patient-facing triage tools sit on or close to the FDA Software-as-a-Medical-Device line. Whether the specific deployment is regulated depends on the recommendations the tool produces, the population it serves, the claims the institution makes about it, and the current state of FDA guidance. The institutional regulatory team is involved from architectural design, through clinical-protocol selection, through go-live, through post-market surveillance. The technical architecture supports either a non-regulated deployment (informational scope, with clinician review of outputs in regulated edge cases) or a regulated SaMD deployment (with the appropriate quality-management system, clinical-validation evidence, and post-market obligations) depending on the institutional choice. This recipe's architecture is consistent with either, but the deployment decision is the institution's.

The rest is largely the same as the previous chapter 11 recipes: tool-surface contract management, identity-assurance lifecycle, conversation logging, scope filtering, per-cohort monitoring, graceful degradation when upstream systems fail.

### The Triage Reality

A few notes on what makes triage specifically harder than the other patient-facing bot use cases.

**The cost of being wrong is asymmetric and severe.** Under-triage (telling a patient with a true emergency that they can stay home) can be fatal. Over-triage (sending a patient with a low-acuity condition to the ED) is expensive and erodes trust. The protocol logic is calibrated to favor over-triage at the expense of under-triage; the operational metrics monitor both rates with separate thresholds. Aggregate accuracy is not a sufficient metric.

**Triage is multilingual by necessity.** Patients in crisis or in pain seek help in their first language. Multilingual deployment is not a phase-2 enhancement; it is a launch-day requirement for institutions serving non-English-speaking populations. <!-- TODO: verify; CMS and various state Medicaid programs impose language-access requirements on certain payer and provider communications, and institutional policies on language access vary --> Per-language asset development includes validated protocol translations, validated regulatory-disclosure phrasings, validated emergency-instruction phrasings, and per-language calibration of the recommendation language.

**Triage requires specific accessibility considerations.** Patients with limited digital literacy, patients with vision impairments using screen readers, patients with cognitive impairments, and patients in acute physical distress may interact with the triage bot differently than the average authenticated app user. Accessibility conformance is not a generic web-accessibility checklist; it is a triage-specific set of design decisions about cognitive load, sentence length, voice-channel availability, and graceful degradation when the patient cannot complete the conversation.

**Triage interacts with mandatory-reporting laws.** Some triage conversations surface disclosures (child abuse, elder abuse, intimate-partner violence, certain mental-health emergencies) that trigger statutory reporting obligations for licensed clinical staff. The bot itself is not a licensed clinician. The institution's policy specifies how disclosures are handled when the bot is the receiver: typically, the bot acknowledges, provides safety resources, and routes to a clinical staff member who is a mandatory reporter, with the conversation context attached. <!-- TODO: verify; mandatory-reporting laws vary by state, by professional credential, and by category of disclosure; institutional policies for AI-mediated communications are an emerging area -->

**Triage contains pediatric and geriatric edge cases that adult-default protocols miss.** Pediatric triage (Schmitt-Thompson Pediatric is the dominant U.S. nurse-line standard) and geriatric triage (with overlay of frailty, polypharmacy, atypical presentations of common conditions, dementia-mediated communication challenges) require dedicated protocols. <!-- TODO: verify; Schmitt-Thompson protocols include dedicated pediatric and adult versions; the geriatric-specific extensions vary by institution and by triage-tool vendor --> The bot's protocol library includes both; the protocol-selection logic recognizes the patient's age and routes to the appropriate version.

**Triage interacts with social context the bot may not see.** Patients without access to transportation cannot follow "go to the urgent care now" if the urgent care is across town and they have no car. Patients without paid sick leave cannot follow "stay home and rest" if doing so means losing income. Patients in unsafe housing cannot follow "monitor your symptoms at home" if home is the source of the problem. The bot's recommendations are formally clinical, but their feasibility is socially determined. The institution's deployment includes social-determinants-of-health overlays where possible, with care-navigation handoffs for patients whose recommended care level is not reachable for them.

**Triage outputs sometimes need to integrate with telehealth and care-navigation tools.** When the bot recommends a telehealth visit, it should be able to schedule the visit (or at least surface availability) rather than just say "schedule a telehealth visit." When the bot recommends an urgent care visit, it should be able to surface the patient's nearest in-network urgent care and that location's current wait time. The integration with the institution's scheduling and care-navigation tools is part of the operational scope.

**Triage interacts with the patient's existing care plan.** A patient with an active oncology treatment plan presents to the triage bot with new symptoms that are very likely treatment-related. The bot's protocol selection should account for this. A patient on anticoagulation with a head injury presents to the triage bot with a different acuity profile than the same head injury in a patient not on anticoagulation. The chart-context lookup includes active treatment plans, active medications relevant to the presenting symptom, and any recent visits that may be related.

**Telehealth integration is bidirectional.** A patient who has just completed a telehealth visit may present to the triage bot with worsening symptoms. The bot's chart context includes the recent visit. The bot's recommendation may differ accordingly. A patient who completes a triage conversation with a "schedule a telehealth visit" recommendation should have that visit booked or scheduled with the conversation context attached, so the receiving telehealth clinician has the triage data available.

**Outcome correlation is a long-term commitment.** The triage bot's clinical performance is measured against actual outcomes: did the patient who was told to go to the ED actually go, and did the ED visit reveal a clinically-significant finding? Did the patient who was told to stay home actually stay home, and did they need a higher-acuity visit within 72 hours? The institution commits to this outcome correlation as part of the post-market surveillance. <!-- TODO: verify; outcome correlation for symptom-triage tools is operationally significant work that requires data integration across the institution's encounter records and is rarely fully implemented in early deployments -->

**Liability and consent considerations are different from non-triage bots.** Patients consenting to use the triage bot are consenting to interact with a tool that provides care-level recommendations. The consent language is reviewed with legal counsel. The handling of cases where the patient ignores the recommendation (the patient was told to go to 911 and chose to wait until morning) is part of the institutional policy and the audit pathway. The institution's malpractice carrier is part of the policy review. <!-- TODO: verify; specific liability frameworks for AI-mediated triage are an emerging legal area; institutional policies and malpractice-coverage arrangements vary -->

### Where the Field Has Moved

A few practical updates worth knowing.

**The Schmitt-Thompson protocols are the dominant U.S. nurse-line standard.** Schmitt-Thompson has versions for adult and pediatric triage and is licensed by most major U.S. nurse-advice line operators. <!-- TODO: verify; Schmitt-Thompson protocols, developed by Drs. Barton Schmitt and David Thompson, are the most widely used U.S. nurse-line triage protocols and are licensed by ClearTriage and other vendors --> Institutions building their own triage tools generally either license Schmitt-Thompson, license another vendor's protocols (such as the Manchester Triage System or proprietary alternatives), or build institution-specific protocols with clinical-leadership ownership. Building from scratch without a clinical foundation is rare and not recommended.

**The Manchester Triage System is the international standard for ED in-person triage.** MTS is widely used in European, Latin American, and Asian-Pacific EDs. <!-- TODO: verify; the Manchester Triage System is widely adopted internationally for in-ED triage and is differentiated from nurse-line phone-triage protocols --> Institutions building tools for international deployment may use MTS or its derivatives.

**The Emergency Severity Index (ESI) is the dominant U.S. ED in-person triage standard.** ESI is the in-ED triage approach used by most U.S. emergency departments. <!-- TODO: verify; ESI is published by ACEP and is widely adopted in U.S. EDs as the in-person triage system --> ESI is not a phone-triage or chat-triage protocol, but it informs the recommendation calibration; a triage tool sending a patient to the ED is implicitly contributing to that ED's ESI workflow, and the tool's recommendation framing should align.

**Clinical-decision rules are increasingly used as components of triage logic.** The HEART score for chest pain, the Wells score for pulmonary embolism and DVT, the Centor score for streptococcal pharyngitis, the Ottawa ankle and knee rules, and others are validated rules for stratifying risk in specific presentations. <!-- TODO: verify; HEART, Wells, Centor, Ottawa, and similar rules have published validation studies and documented sensitivity/specificity profiles; specific patient-population applicability varies --> Modern triage architectures invoke these rules as deterministic tools when the protocol calls for them.

**The FDA's posture on patient-facing triage software continues to evolve.** The 2022 final guidance on Clinical Decision Support software clarified the distinction between regulated and non-regulated software, but patient-facing triage tools generally face more scrutiny than clinician-facing CDS, because the patient cannot independently verify the recommendation against their own clinical judgment. <!-- TODO: verify; FDA guidance on CDS software, including the 2022 final guidance and subsequent updates, continues to evolve; the regulatory status of patient-facing triage tools depends on specific product characteristics and claimed functionality --> Institutions deploying patient-facing triage at scale typically work with FDA-experienced regulatory counsel from the architectural design phase.

**Tool-using LLMs handle triage Q&A well when grounded carefully.** The function-calling pattern from the previous chapter 11 recipes maps directly to triage. The LLM produces tool calls that retrieve protocols, gather chart context, compute clinical-decision rules, and post recommendations; the tools return structured data; the LLM composes a grounded answer that delivers the recommendation. The architecture has been deployed at major payers, integrated delivery networks, and digital-health vendors since roughly 2023.

**Conversational triage measurably reduces nurse-line wait times and ED over-utilization in specific populations.** Deployments at major institutions have reported substantial reductions in nurse-line wait times for routine triage cases and modest reductions in low-acuity ED utilization, with both effects strongest in member populations with high digital adoption and in member populations whose alternative was the nurse line rather than the ED. <!-- TODO: verify; specific deflection rates and operational impact figures vary by deployment and are sometimes published in vendor case studies and institutional press; consolidated public statistics are not reliably aggregated -->

**Equity and disparities in triage are an active research area.** Studies of nurse-line triage have documented variability in recommendations by patient demographics that does not appear to be clinically justified. <!-- TODO: verify; literature on demographic variability in triage decisions includes studies of phone-triage, ED-triage (ESI), and digital-symptom-checker triage; specific findings vary --> AI-mediated triage may inherit, amplify, or correct these disparities. Per-cohort monitoring is essential, and the institutional commitment to equity is reviewed by the compliance and patient-experience teams.

**Build-vs-buy is mature in this category.** Several conversational triage vendors operate at major-institution scale, with EHR integration, multilingual support, and regulatory frameworks. <!-- TODO: verify; the commercial vendor landscape continues to evolve --> Most major institutions run a hybrid: build the in-house bot for the routine member-facing journey on the institution's preferred infrastructure, partner with a clinical-protocol vendor for the licensed protocols, and integrate with the institution's nurse-line, telehealth, and care-navigation infrastructure.

---

## General Architecture Pattern

A healthcare triage bot decomposes into ten logical stages: channel entry, input safety screening with continuous-emergency-screening, identity-and-chart-context loading, symptom identification and protocol selection, structured protocol-driven questioning, clinical-decision-rule computation, acuity scoring and recommendation, output safety screening with conservative-bias verification, recommendation delivery, and nurse-line escalation when applicable. The cross-cutting concerns from recipes 11.1 through 11.5 carry forward; this recipe adds four new ones (clinical-protocol-corpus governance with medical-director sign-off, conservative-bias-default policy, continuous-emergency-screening pipeline, and FDA-strategy-alignment artifact maintenance).

```
┌────────── CHANNEL ENTRY ─────────────────────────────────┐
│                                                           │
│   [Patient opens chat in institution's app, member        │
│    portal, telehealth front-door, employer-side wellness  │
│    portal, or via SMS/voice channel]                      │
│                                                           │
│   [Greeting and disclosure]                               │
│    - Identifies as a chatbot                              │
│    - States scope (informational triage, not diagnosis,   │
│      not replacement for a clinician)                     │
│    - Notes the questions are based on the same protocols  │
│      institutional nurses use                             │
│    - Names the human-escalation pathway                   │
│    - Reinforces the 911 redirect for any emergency        │
│                                                           │
│   [Conversation session bootstrap]                        │
│    - Generate session_id                                  │
│    - Capture channel, authentication context, deep-link   │
│      parameters (e.g., a specific symptom topic the       │
│      patient tapped to start the conversation)            │
│           │                                               │
│           ▼                                               │
│   [Output: session_id, channel, auth context, deep-link   │
│    parameters]                                            │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── INPUT SAFETY + CONTINUOUS EMERGENCY SCREEN ────┐
│                                                           │
│   [Standard input safety primitives from recipe 11.1]     │
│    - Prompt-injection detection                           │
│    - PHI minimization                                     │
│    - Self-harm and crisis classifier                      │
│                                                           │
│   [Triage-specific continuous emergency screening]        │
│    - Runs on every patient utterance, not just first      │
│    - Detects explicit emergency presentations             │
│      (active chest pain, stroke symptoms, severe          │
│      bleeding, suspected anaphylaxis, suspected           │
│      overdose, acute psychosis, suicidal intent)          │
│    - Detects emergency feature constellations             │
│      (cauda equina pattern, sepsis pattern, abdominal     │
│      catastrophe pattern, neurological deficit pattern)   │
│    - Detects pediatric-specific emergency presentations   │
│      (febrile infant, lethargic infant, suspected         │
│      meningitis pattern, suspected intussusception)       │
│    - Triggers immediate 911 / 988 / institutional crisis  │
│      routing with stay-on-the-line guidance               │
│           │                                               │
│           ▼                                               │
│   [Output: input passes / input blocked-with-disposition  │
│    / emergency-routed-immediately]                        │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── IDENTITY AND CHART-CONTEXT LOADING ────────────┐
│                                                           │
│   [Authenticated session path (recommended default)]      │
│    - Patient is logged into the institution's app or      │
│      portal                                               │
│    - Session conveys verified patient_id and chart        │
│      access scope                                         │
│                                                           │
│   [Unauthenticated path (limited scope)]                  │
│    - For lower-stakes general health questions, the bot   │
│      may answer without authentication, with reduced      │
│      protocol scope and explicit "I don't know your       │
│      medical history" framing                             │
│    - High-acuity protocols and chart-aware                │
│      recommendations require authentication               │
│                                                           │
│   [Pediatric and proxy-completion handling]               │
│    - Parent or guardian completing the conversation       │
│      for a minor child: the conversation is on            │
│      behalf of the child, with appropriate consent        │
│      handling per state law                               │
│    - Adult-on-behalf-of-adult (caregiver, authorized      │
│      representative) with appropriate scope               │
│                                                           │
│   [Chart-context tools]                                   │
│    - Demographics (age, sex, language preferences,        │
│      pediatric vs adult)                                  │
│    - Active problem list                                  │
│    - Active medication list (focused on those relevant    │
│      to common presenting symptoms: anticoagulants,       │
│      immunosuppressives, opioids, antidiabetics, etc.)    │
│    - Recent visit history (90 days)                       │
│    - Active treatment plans (oncology, transplant,        │
│      pregnancy, etc. that materially change triage)       │
│    - Known allergies                                      │
│    - Advance directives (where the institution stores)    │
│           │                                               │
│           ▼                                               │
│   [Output: verified patient_id, chart context, scope,     │
│    pediatric-vs-adult flag, proxy-completion flag]        │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── SYMPTOM IDENTIFICATION + PROTOCOL SELECTION ───┐
│                                                           │
│   [Symptom identification]                                │
│    - Free-form initial complaint mapped to symptom        │
│      category                                             │
│    - LLM with retrieval over protocol library             │
│    - Multi-symptom presentations: select highest-acuity-  │
│      eligible protocol; cross-reference others            │
│                                                           │
│   [Protocol selection]                                    │
│    - Each symptom maps to one or more institutional       │
│      protocols                                            │
│    - Protocols are versioned, owned by medical director   │
│      and nurse-line operations                            │
│    - Pediatric vs adult versions selected based on        │
│      patient age                                          │
│    - Special-population protocols (pregnancy, oncology    │
│      treatment, transplant, etc.) selected based on       │
│      chart context                                        │
│                                                           │
│   [Ambiguous-mapping handling]                            │
│    - Bot asks one or two clarifying questions when        │
│      multiple protocols are plausible                     │
│    - Falls back to broad initial-assessment protocol      │
│      that branches based on responses                     │
│                                                           │
│   [Out-of-scope handling]                                 │
│    - Some presentations are out of scope for the bot      │
│      (e.g., suspected ingestion in a pediatric patient    │
│      where the institution's policy defers to Poison      │
│      Control)                                             │
│    - Out-of-scope presentations route immediately to      │
│      the appropriate human resource                       │
│           │                                               │
│           ▼                                               │
│   [Output: selected_protocol, protocol_version, fallback  │
│    or escalation marker if applicable]                    │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── STRUCTURED PROTOCOL-DRIVEN QUESTIONING ────────┐
│                                                           │
│   [Bot conducts the protocol's question sequence]         │
│    - Canonical questions specified by the protocol        │
│    - LLM may rephrase for clarity                         │
│    - Order may adjust based on what the patient has       │
│      volunteered                                          │
│    - Ambiguous answers trigger follow-up                  │
│    - Bot does not skip protocol questions                 │
│    - Bot does not invent new questions outside the        │
│      protocol's scope                                     │
│                                                           │
│   [Continuous emergency screening (parallel)]             │
│    - Every patient response screened for emergency        │
│      content                                              │
│    - Mid-conversation emergency triggers immediate        │
│      911 / 988 routing                                    │
│                                                           │
│   [Pediatric-specific question adaptations]               │
│    - Pediatric protocols ask the parent / caregiver       │
│    - Different vital-sign expectations                    │
│    - Different emergency feature sets                     │
│                                                           │
│   [Conversation-state persistence]                        │
│    - Each turn captured in conversation log               │
│    - Each protocol answer captured in structured form     │
│    - Tool calls audited                                   │
│           │                                               │
│           ▼                                               │
│   [Output: structured answer set per protocol question;   │
│    flag set for any emergency-screen triggers]            │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── CLINICAL-DECISION-RULE COMPUTATION ────────────┐
│                                                           │
│   [Where the protocol invokes a clinical-decision rule:]  │
│    - HEART score for chest pain                           │
│    - Wells score for PE / DVT                             │
│    - Centor score for streptococcal pharyngitis           │
│    - Ottawa ankle / knee rules for ankle / knee injury    │
│    - PERC rule for PE risk stratification                 │
│    - Other institution-validated rules                    │
│                                                           │
│   [Each rule runs as a deterministic tool]                │
│    - Inputs: structured features captured during          │
│      questioning                                          │
│    - Outputs: score, risk stratum, recommended care       │
│      level per the rule's published thresholds            │
│    - Tool version audited                                 │
│                                                           │
│   [LLM does not compute the rule]                         │
│    - LLM gathers inputs                                   │
│    - Tool computes score                                  │
│    - LLM presents the result                              │
│           │                                               │
│           ▼                                               │
│   [Output: structured rule scores with risk strata and    │
│    rule-mapped care-level recommendations]                │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── ACUITY SCORING + RECOMMENDATION ───────────────┐
│                                                           │
│   [Combine protocol decision logic with rule outputs]     │
│    - Protocol-driven recommendation from answer set       │
│    - Rule-driven recommendation where applicable          │
│    - When recommendations diverge, the higher-acuity      │
│      recommendation wins (conservative default)           │
│                                                           │
│   [Care-level recommendation set]                         │
│    - 911 (emergency response, do-not-self-transport)      │
│    - Emergency department (urgent presentation; self-     │
│      transport with caveats; sometimes specific           │
│      institutional ED)                                    │
│    - Urgent care (within 24 hours; specific institutional │
│      urgent care identified where possible)               │
│    - Primary care (today, in 24-48 hours, or routine      │
│      follow-up)                                           │
│    - Telehealth visit (synchronous video / voice; some    │
│      protocols recommend telehealth as the appropriate    │
│      starting point)                                      │
│    - Self-care at home (with explicit red-flag symptoms   │
│      that should re-trigger triage)                       │
│                                                           │
│   [Conservative-bias enforcement]                         │
│    - When protocol logic spans acuity levels, default     │
│      to higher acuity                                     │
│    - When patient-response confidence is low, default     │
│      to nurse-line escalation                             │
│    - When chart-context flags raise risk (anticoagulant   │
│      use with bleeding presentation; immunosuppression    │
│      with infection presentation), upgrade acuity         │
│                                                           │
│   [Special-population handling]                           │
│    - Pediatric-specific recommendation calibration        │
│    - Pregnancy-specific recommendation calibration        │
│    - Geriatric-specific recommendation calibration        │
│    - Active-treatment-plan recommendation calibration     │
│    - High-risk medication recommendation calibration      │
│           │                                               │
│           ▼                                               │
│   [Output: structured care-level recommendation with      │
│    rationale references and protocol-version stamps]     │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── OUTPUT SAFETY + CONSERVATIVE-BIAS VERIFY ──────┐
│                                                           │
│   [Standard output safety primitives from recipe 11.1]    │
│    - Scope filter (no diagnosis; no off-label drug        │
│      recommendations; no treatment plans)                 │
│    - Vendor-managed guardrail layer                       │
│    - Persona-and-tone check (empathetic for distress;     │
│      clear for emergencies; calm for low-acuity)          │
│                                                           │
│   [Triage-specific verification]                          │
│    - Recommendation grounded in the cited protocol        │
│    - Citation includes protocol_id, protocol_version,     │
│      decision-point identifier, and any clinical-rule     │
│      score(s) used                                        │
│    - Conservative-bias check: where recommendation        │
│      could plausibly be higher acuity, did the bot       │
│      take the higher acuity path?                         │
│    - Disclaimer language present and correct for the      │
│      institution's regulatory positioning                 │
│    - Emergency-instruction completeness for high-acuity   │
│      recommendations (don't drive yourself, who to        │
│      call, what to do while waiting)                      │
│    - Red-flag-symptom completeness for low-acuity         │
│      recommendations (when to re-engage)                  │
│           │                                               │
│           ▼                                               │
│   [Output: response cleared for delivery, replaced with   │
│    a safer template, or regenerated with corrections]     │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── RECOMMENDATION DELIVERY + INSTRUCTIONS ────────┐
│                                                           │
│   [Recommendation phrased in plain English]               │
│    - States the care level                                │
│    - Provides the rationale (briefly, in patient terms)   │
│    - Acknowledges uncertainty where present               │
│    - Includes appropriate disclaimer                      │
│                                                           │
│   [High-acuity instructions]                              │
│    - 911: stay seated, do not drive, call someone to be   │
│      with you, institution-approved interim measures      │
│      where applicable, stay-on-the-line offer             │
│    - ED: how to get there safely, what to bring, what to  │
│      tell the ED triage nurse                             │
│                                                           │
│   [Mid-acuity instructions]                               │
│    - Urgent care: location, hours, what to bring          │
│    - Primary care: scheduling pathway with conversation   │
│      context attached                                     │
│    - Telehealth: visit booking with conversation          │
│      context attached                                     │
│                                                           │
│   [Low-acuity instructions]                               │
│    - Self-care steps                                      │
│    - Red-flag symptoms                                    │
│    - Re-engagement path (back to bot, to nurse line,      │
│      to PCP)                                              │
│           │                                               │
│           ▼                                               │
│   [Output: rendered recommendation with instructions]     │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── NURSE-LINE ESCALATION (FIRST-CLASS) ───────────┐
│                                                           │
│   [Trigger conditions for nurse-line handoff:]            │
│    - Protocol-mandated escalation point                   │
│    - Bot confidence below threshold at any step           │
│    - Patient presentation does not fit any protocol       │
│    - Patient explicitly requests a human                  │
│    - Output safety screen flagged scope or                │
│      conservative-bias issue                              │
│    - Mid-conversation emergency screen triggered          │
│    - Disclosure of mandatory-reporting concern            │
│    - Out-of-scope clinical question                       │
│                                                           │
│   [Handoff payload]                                       │
│    - Conversation transcript                              │
│    - Protocol consulted with version                      │
│    - Structured answer set                                │
│    - Computed clinical-decision rule scores               │
│    - Computed recommendation with rationale               │
│    - Chart-context summary                                │
│    - Patient's preferred contact method                   │
│    - Acuity flags including any emergency markers         │
│                                                           │
│   [Routing target selection]                              │
│    - Adult nurse line                                     │
│    - Pediatric nurse line                                 │
│    - Behavioral-health crisis pathway (988 /              │
│      institutional crisis line)                           │
│    - Poison Control (1-800-222-1222 for U.S. callers)     │
│    - Specialty escalation (oncology on-call, transplant   │
│      on-call, etc. where applicable)                      │
│           │                                               │
│           ▼                                               │
│   [Output: human-handoff event with structured payload]   │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── AUDIT, LOG, AND POST-MARKET SURVEILLANCE ──────┐
│                                                           │
│   [Durable conversation record]                           │
│    - User utterances                                      │
│    - Tool calls with arguments and results                │
│    - Generated bot responses                              │
│    - Active model and prompt versions                     │
│    - Active protocol-corpus version stamps                │
│    - Identity-verification outcome and assurance level    │
│    - Pediatric-vs-adult flag and proxy-completion flag    │
│    - Final disposition (resolved-by-bot, handed-off,      │
│      patient-abandoned, emergency-routed, crisis-routed)  │
│                                                           │
│   [Triage-decision-record journal]                        │
│    - Durable, separately-governed record of every         │
│      triage recommendation: the patient, the              │
│      presenting complaint, the protocol used, the         │
│      answer set, the computed rule scores, the            │
│      recommendation, the rationale, the version           │
│      stamps, the timestamp                                │
│    - Retention sized to the longer of HIPAA's six-year    │
│      minimum, state-specific medical-record retention     │
│      rules, and any FDA SaMD post-market obligations      │
│                                                           │
│   [Outcome-correlation pipeline (long-term)]              │
│    - Correlate bot recommendation with subsequent care    │
│      utilization (did the patient go to the recommended   │
│      care level; did the patient need a higher-acuity     │
│      visit within 72 hours)                               │
│    - Calculate per-protocol over-triage and under-triage  │
│      rates                                                │
│    - Feed signals back to protocol-revision process       │
│    - Owned jointly by the medical director, the nurse-    │
│      line operations team, and the data science team      │
│                                                           │
│   [Operational telemetry]                                 │
│    - Resolution rate (bot completes recommendation)       │
│    - Escalation rate by protocol                          │
│    - Median time-to-recommendation                        │
│    - Patient satisfaction by recommended care level       │
│    - Tool-call failure rate per tool                      │
│    - Citation-coverage rate                               │
│    - Per-cohort metric slices (language, channel,         │
│      pediatric vs adult, age cohort, sex, presenting      │
│      symptom category)                                    │
│                                                           │
│   [Sampled clinical-quality review]                       │
│    - Random sample plus targeted sample of low-           │
│      confidence cases, escalations, and outcome-          │
│      correlation flags                                    │
│    - Reviewers (RNs and clinical leadership) tag          │
│      failure modes (under-triage, over-triage,            │
│      protocol-deviation, scope-violation, conservative-   │
│      bias-failure, citation-gap)                          │
│    - Medical-director sign-off on protocol revisions      │
│      driven by review findings                            │
│           │                                               │
│           ▼                                               │
│   [Output: audit trail, telemetry, learning signals,      │
│    protocol-revision proposals]                           │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

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

The triage bot is the recipe in this chapter where the clinical stakes are highest, the regulatory exposure is most concentrated, and the accuracy floor matters most. It is also the recipe where the engineering discipline most directly translates to patient outcomes. A well-built triage bot keeps people from sitting at home with a heart attack until morning, and it keeps the urgent care from filling up with patients whose symptoms are best addressed at home with monitoring. A badly-built triage bot does the opposite, in either direction, and the failure modes have human costs.

The first trap, as with the previous bots, is treating the institutional content as someone else's problem. With the FAQ bot it was the parking policy. With the scheduling bot it was the visit-type catalog. With the refill bot it was the clinical refill protocol. With the intake bot it was the per-visit-type intake protocol library. With the benefits navigator it was the plan-document corpus and regulatory-disclosure phrasings library. With the triage bot it is the clinical-protocol corpus, the clinical-decision-rule library, the emergency-screening corpus, the regulatory-strategy artifact, and the chart-context integration. The single largest determinant of bot quality is the explicitness, completeness, currency, and clinical-leadership ownership of these artifacts. Most institutions discover, partway through the project, that their triage protocols are not actually written down in a form that can be programmatically retrieved, that the protocols their nurse line uses informally vary across nurses, and that the formal protocol documents need substantial work to be machine-actionable. Formalizing these artifacts is multi-quarter work that has to start before the engineering work and continue alongside it.

The second trap is underestimating the conservative-bias discipline. The protocols are designed with conservative bias; the bot's logic has to enforce it, and the LLM's default helpfulness instinct can erode it. Every architectural decision, every prompt revision, every guardrail, every output-safety check, every protocol-revision review, every per-cohort monitoring threshold has to be made with conservative bias as the explicit policy. A bot that sometimes under-triages a chest-pain presentation because the LLM was being helpful is the failure mode the architecture is supposed to prevent. The conservative-bias policy is a documented, reviewed, and audited commitment, not an emergent property.

The third trap is the regulatory positioning. Patient-facing triage tools sit on or close to the FDA SaMD line. The institutional positioning depends on the recommendations the tool produces, the population it serves, the claims the institution makes about it, and the current state of FDA guidance. The regulatory team is involved from architectural design, not at launch. The FDA-strategy artifact is reviewed by FDA-experienced regulatory counsel; building a deployment without one is a serious mistake.

The fourth trap is the citation-grounding discipline. A triage bot that produces ungrounded recommendations is worse than no triage bot at all, because patients will rely on the recommendations and the institution will be liable when the recommendations are wrong. Every recommendation has to trace to a cited protocol decision point with the protocol version preserved. The citation-coverage-rate metric is a launch-gate threshold, not a post-launch dashboard.

The fifth trap is the continuous-emergency-screening pipeline. The first turn is not the only turn that matters. Patients who start with a vague concern can disclose, three turns in, that they have lost the ability to feel their legs (cauda equina), that they are bleeding heavily (potential GI bleed or trauma), that they are thinking about hurting themselves (mental-health crisis), that they have suddenly lost the ability to speak (stroke). The continuous emergency screening runs on every utterance. Skipping screening on continuation turns is a documented failure mode.

The sixth trap is shipping without nurse-line integration. A triage bot deployed without a nurse-line backstop is missing the safety net for the cases the bot cannot handle. The nurse-line integration with full conversation-context handoff is part of production scope, not a phase-2 enhancement.

The seventh trap is shipping without per-cohort monitoring. Resolution rate, escalation rate, over-triage rate, under-triage rate, time-to-recommendation, and citation-coverage rate vary by language, channel, pediatric-vs-adult, age cohort, sex, presenting symptom category, and chart-context completeness. Aggregate metrics hide disparities that are clinically and ethically significant.

The eighth trap is shipping without outcome correlation. The bot's clinical performance is bounded above by what can be measured. Outcome correlation against subsequent care utilization is operationally significant work, requires data integration across the institution's encounter records (and ideally claims data for cross-institution utilization), and is rarely fully implemented at launch but is a core post-launch commitment.

The ninth trap is shipping without an explicit equity commitment. Studies of nurse-line and ED triage have documented variability in recommendations by patient demographics that does not reflect underlying clinical reality. AI-mediated triage may inherit, amplify, or correct these disparities. The institutional commitment to equity is documented, reviewed, and operationalized through per-cohort monitoring with clinical-leadership sign-off on disparities thresholds.

The tenth trap is mishandling sensitive disclosures. A patient in triage may disclose intimate-partner violence, child or elder abuse, suicidal ideation, sexual-health concerns, substance-use issues, and other topics covered by mandatory-reporting laws or by additional state-specific frameworks. The handling of these disclosures requires a specific institutional policy with clinical-leadership and legal review.

The thing that surprises engineers coming from generic-chatbot backgrounds is how much of the engineering value is in the clinical-content layer. The protocols, the clinical-decision rules, the chart-context integration, the emergency-screening logic, the conservative-bias enforcement, the citation-grounding verifier. None of this is exotic technology, and all of it is critical.

The thing that surprises clinical leaders coming from nurse-line operations backgrounds is how dependent the bot's quality is on the explicitness of the protocols. Nurses with experience can navigate informal protocol gaps; the bot cannot. Formalizing the protocols at a level the bot can use without losing the clinical wisdom that lives in nurses' heads is multi-quarter clinical work, with clinical-leadership ownership and named accountability.

The thing about Amazon Bedrock specifically: same as recipes 11.2 through 11.5, Bedrock Agents is the right level of abstraction for this recipe. The Agent handles the multi-step LLM-and-tool orchestration; the action groups are the bot's tool surface; Knowledge Bases provides the protocol RAG; Guardrails provides safety filtering. The institutional value lives in the protocol corpus, the clinical-decision-rule library, the chart-context integration, and the regulatory artifact, not in the Bedrock features themselves.

The thing about cost: per-resolved-conversation infrastructure cost is small relative to the cost of even a single avoided unnecessary ED visit, and small relative to the cost of even a single avoided delay-in-treatment for a time-sensitive condition. The dominant project cost is the clinical and regulatory engineering, not the AWS bill.

The thing about regulatory exposure: the bot is a patient-facing clinical tool subject to scrutiny by FDA (where applicable), state medical boards (in some states with AI-mediated patient-care rules), state insurance regulators (for payer-side deployments), and the institutional malpractice insurer. The institutional regulatory team is involved from day one; FDA-experienced regulatory counsel is part of the team for any deployment that may approach the SaMD line.

The thing about patient trust: a triage bot that is clearly a triage bot, that delivers recommendations grounded in cited protocols, that defers to nurses for ambiguous cases, and that tells patients explicitly what it is and is not, builds trust. A bot that pretends to be a clinician, hides its protocol grounding, hedges all of its recommendations, and obscures its decision logic destroys trust. The honest disclosure and the visible escalation pathway are not just regulatory requirements; they are trust-building features.

The thing I would do differently the second time: start with a narrower set of protocols (the highest-volume routine presentations: upper respiratory infections, skin rashes, urinary symptoms, minor musculoskeletal injuries, common pediatric presentations like fever and ear pain) before expanding to the high-stakes protocols (chest pain, severe headache, abdominal pain, trauma). The narrow start lets the team validate the architecture, the protocol-corpus governance, the citation discipline, the conservative-bias enforcement, the per-cohort monitoring, and the outcome-correlation pipeline against lower-acuity presentations where the failure modes are less catastrophic. Adding the high-stakes protocols later, with the validated infrastructure already in place, is safer than launching with the full protocol catalog and discovering the failure modes against high-acuity patients.

The last thing: the triage bot is the recipe in this chapter where the operational, clinical, and regulatory engineering most clearly outweighs the ML engineering. The ML engineering is largely the same as the previous chapter 11 recipes; the protocol corpus, the clinical-decision-rule library, the chart-context integration, the regulatory artifact, the medical-director sign-off, the outcome-correlation pipeline, and the per-cohort equity monitoring are the parts that distinguish a clinically-safe deployment from a clinically-dangerous one. Build the institutional muscles for the harder parts first; the bot is the easier part.

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
- **Recipe 12.x (Time Series Analysis):** Chapter 12. The outcome-correlation pipeline benefits from time-series patterns for tracking subsequent care utilization.
- **Recipe 13.x (Knowledge Graphs):** Chapter 13. The clinical-protocol corpus may be modeled as a knowledge graph for richer cross-protocol querying.

---

## Tags

`conversational-ai` · `triage-bot` · `symptom-checker` · `patient-facing` · `clinical-protocol` · `tool-using-llm` · `function-calling` · `bedrock-agents` · `rag` · `citation-grounding` · `clinical-decision-rules` · `heart-score` · `wells-score` · `centor-score` · `ottawa-rules` · `schmitt-thompson` · `manchester-triage-system` · `emergency-severity-index` · `pediatric-triage` · `adult-triage` · `nurse-line-escalation` · `continuous-emergency-screening` · `conservative-bias` · `chart-context` · `fhir-patient` · `fhir-condition` · `fhir-medicationstatement` · `fhir-allergyintolerance` · `fhir-encounter` · `intent-classification` · `scope-containment` · `prompt-injection-defense` · `prompt-versioning` · `persona-design` · `multilingual` · `accessibility` · `equity-monitoring` · `cohort-stratified-accuracy` · `outcome-correlation` · `mandatory-reporting` · `crisis-detection` · `988-routing` · `911-routing` · `poison-control-routing` · `fda-samd` · `fda-cds` · `regulatory-strategy` · `medical-director-signoff` · `bedrock` · `bedrock-knowledge-bases` · `bedrock-guardrails` · `opensearch-serverless` · `healthlake` · `lambda` · `api-gateway` · `waf` · `dynamodb` · `s3` · `kms` · `secrets-manager` · `cloudwatch` · `cloudtrail` · `eventbridge` · `kinesis-firehose` · `glue` · `athena` · `connect` · `lex` · `sagemaker` · `quicksight` · `medium-complex` · `regulated` · `hipaa` · `phi-handling` · `audit-trail` · `triage-decision-record-journal` · `chapter11` · `recipe-11-6`

---

*← [Recipe 11.5: Insurance Benefits Navigator](chapter11.05-insurance-benefits-navigator) · [Chapter 11 Index](chapter11-preface) · [Recipe 11.7: Chronic Disease Management Coach](chapter11.07-chronic-disease-management-coach) →*
