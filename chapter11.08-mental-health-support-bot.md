# Recipe 11.8: Mental Health Support Bot

**Complexity:** Complex · **Phase:** Regulated · **Estimated Cost:** ~$2-10 per active member per month (depends on engagement frequency, channel mix, model choice, RAG depth, crisis-pathway integration depth, and clinical-escalation overhead)

---

## The Problem

It is 11:47 PM on a Wednesday. Sam is 24. Sam has been awake for about three hours, scrolling through their phone in bed, and the thoughts have been getting louder. Not the usual late-night anxiety thoughts about the email they did not answer at work, the conversation they probably mishandled with their roommate, the credit card payment that is two days overdue. Different thoughts. The kind of thoughts Sam knows, because they have been here before, are the thoughts that mean tomorrow will be a hard day and the day after will be harder. Sam was diagnosed with major depressive disorder when they were 19, has been on sertraline for most of the time since, and has had two prior episodes that required acute care, one of which involved a brief inpatient stay that Sam still has feelings about. Sam has a therapist, but the therapist is on vacation this week. Sam's primary care physician's office is closed. Sam's parents would pick up the phone, but Sam does not want to call their parents at midnight on a Wednesday and explain why. Sam's roommate is asleep behind the closed door across the hall.

Sam knows the playbook for what they are supposed to do in this situation. They have a safety plan from their therapist, written down in a notebook in the drawer next to the bed. The safety plan says, in this order: notice the warning signs, use coping strategies (a list of seven things, including a specific breathing exercise, a specific grounding exercise, and "go for a walk if it is safe to be outside"), reach out to people on the support list (three named contacts and a phone number), make the environment safer (specific instructions about removing means), call the crisis line (988 is written in the notebook), and go to the nearest emergency department. The plan is good. Sam's therapist is good. The reason the plan is in the drawer and not in Sam's hand is that, when the thoughts get loud, the activation energy required to open the drawer, find the notebook, read down the list, and start at step one is, in that moment, more than Sam has. Sam knows this is a feature of the disease and not a personal failing. Sam still cannot make their hand reach for the drawer.

What Sam does instead, because they are 24 and they are holding their phone, is open an app. Not the safety-plan app the therapist's clinic recommended, because Sam never got around to setting it up. Not the meditation app, because the cheerful voice would feel mocking right now. Sam opens the chat app for the digital mental-health platform their employer's health benefits cover, which Sam signed up for in February when they had a better month and remembered to do logistical things. The app has a chat interface. Sam types, almost in spite of themselves, "i'm having a bad night and i don't know what to do."

The app does what it has been carefully designed to do. It does not say "I'm here for you ❤️." It does not say "tell me more about how you're feeling." It does not say "you should consider speaking to a licensed therapist about these feelings." It says, in a tone that is warm without being saccharine and serious without being clinical: "Sam, I'm glad you reached out. I'm a chat tool, not a person, but I'm going to stay with you while we figure out the next step. Before anything else, I want to ask you something directly: are you having any thoughts of hurting yourself right now?"

Sam, who has been having those thoughts for about ninety minutes and has not said them out loud to anyone, types "yes."

The app does not panic. The app says: "Thank you for telling me. I want to make sure you're safe. Are you safe right where you are right now? Are there any specific plans or means involved?" Sam answers honestly. The app, based on Sam's answers and on the safety-plan information Sam shared with the platform back in February, takes Sam to the next step. It tells Sam clearly that what Sam is going through is the kind of thing that should be talked through with a person, that the 988 line is staffed right now, that there is a counselor available through the platform's after-hours line, and that the app can connect Sam to a person directly through the chat (warm handoff, with the conversation context attached) if that feels easier than picking up the phone. The app reminds Sam that their safety plan mentions removing means; it asks gently if there is anything in Sam's environment that the safety plan covers, and offers to walk through that step with Sam now. The app, while it does this, is also doing things Sam does not see: notifying the platform's crisis-response queue, logging the conversation as a high-acuity event, attaching the safety-plan context, and surfacing the conversation to a licensed clinician on duty who is now five seconds away from joining the chat if Sam wants the handoff.

Sam, after another minute of typing, asks for the warm handoff. A licensed counselor named Priya joins the chat. Priya has the conversation transcript already loaded. Priya does not make Sam start over. Priya stays with Sam through the next forty minutes. By 12:35 AM, Sam is doing the breathing exercise from the safety plan, has put the medication bottles in the bathroom drawer where their roommate keeps theirs (a step from the means-restriction part of the plan), has agreed to text their roommate in the morning, and has scheduled a video session for 8 AM with one of the platform's clinicians to bridge the gap until their regular therapist is back next week. Sam goes to sleep at 1:14 AM. Sam is alive in the morning.

This is a good outcome. It is not a typical outcome.

The typical outcome, for the millions of Americans who experience mental-health crisis between visits, looks more like this: the person does not open the app, because they do not have the app, because their employer does not cover one. Or they open an app, and the app says "I'm here for you ❤️" and asks them to rate their mood on a scale of one to ten, and they close the app. Or they open the app, and the app starts walking them through a CBT exercise about cognitive distortions, which is the wrong intervention for someone in active crisis. Or they open the app, and the app does not screen for self-harm at all, and the conversation drifts into territory that no responsible mental-health product should ever enter unsupervised. Or they call 988, and the wait is six minutes, and they hang up after four. Or they go to the ED, and they wait seven hours for a psych bed, and they sign out against medical advice at 6 AM. Or they do none of these things, because the activation energy is too high, and they spend the night alone with the thoughts, and they hope the morning is easier. Sometimes the morning is easier. Sometimes it is not.

This is mental healthcare in the United States in 2026, and it is the area of healthcare where the gap between what the population needs and what the system delivers is, by some measures, the widest. Mental-health conditions affect a substantial fraction of U.S. adults in any given year, with anxiety disorders, depressive disorders, and substance-use disorders being the most prevalent categories; the lifetime prevalence is higher still.  The treatment gap (the proportion of people with a treatable mental-health condition who do not receive treatment in a given year) is large, with substantial disparities by race, ethnicity, language, geography, age, and insurance coverage.  Mental-health professionals, particularly psychiatrists, are concentrated in urban areas, are mostly out-of-network in many insurance plans, and have wait times for new patients that, in many markets, exceed three months for non-urgent visits.  The 988 line, which replaced the previous national suicide-prevention number in 2022, has improved capacity but still has uneven coverage and variable wait times depending on the state and the time of day.  The number of people in mental-health crisis on any given night substantially exceeds the number of mental-health crisis-response professionals available to take their calls. The math, as a system-design problem, is unforgiving.

The previous generations of digital mental-health products tried to address this in three waves. The first wave, roughly 2010 to 2017, was self-guided cognitive-behavioral-therapy apps and mood-tracking apps. The clinical evidence for some of these was promising for specific conditions and specific populations; the evidence for many others was thin or non-existent.  Engagement attrition was the central problem; most users downloaded the app, used it for a few weeks, and stopped. The second wave, roughly 2017 to 2022, was teletherapy platforms with human clinicians delivering therapy by video. The evidence for the modality is solid; the operational problem is that clinical capacity does not scale. The third wave, starting around 2022, is conversational AI for mental health, in shapes ranging from "lightweight chatbot for low-acuity stress and anxiety" to "AI companion that pretends to be a friend" to "structured CBT-delivery agent" to (most recently) "AI companion that increasingly pretends to be a therapist." This third wave includes some careful, evidence-based products, some products with mixed evidence, and some products that should never have shipped, with documented incidents of inappropriate responses to vulnerable users. 

This recipe is about building, carefully, a mental-health support bot that fits in the first category and not the third. The architectural patterns from the previous chapter 11 recipes (FAQ bot, scheduling, refills, intake, benefits navigator, triage, chronic disease coach) all converge here, and several entirely new patterns enter the picture: continuous and aggressive crisis detection, evidence-based therapeutic content delivery (not freestyle therapy), explicit non-therapist scoping, warm handoff to licensed clinicians as a primary system component rather than a fallback, ethical disclosure as architectural primitive, and a level of caution about the bot's emotional persona that is harder than it looks to get right.

A few things this recipe is and is not.

It is the bot that provides between-session and between-clinician digital mental-health support to patients managing established mental-health conditions, with mood and symptom tracking, evidence-based therapeutic exercise delivery (CBT, behavioral activation, mindfulness, journaling prompts, sleep-hygiene support), psychoeducation grounded in the institution's clinical content, crisis screening and crisis-resource routing, structured warm handoff to licensed clinicians, integration with the patient's safety plan when one exists, and explicit scope discipline around what the bot can and cannot do.

It is not a therapist. The bot does not deliver psychotherapy. The bot does not provide diagnosis. The bot does not interpret the patient's psychological dynamics. The bot does not adjust medications or recommend medication changes. The bot does not provide trauma processing. The bot does not engage in psychodynamic work. The bot is, structurally and explicitly, a tool that delivers evidence-based therapeutic exercises and routes to humans for everything else. The patient is told this explicitly and frequently.

It is not a friend. The bot does not pretend to have feelings. The bot does not pretend to remember the patient as a "person it cares about." The bot does not say "I missed you" when the patient comes back after a gap. The parasocial-companion pattern (the LLM as artificial friend or romantic partner) is a separate product category, ethically and clinically distinct from a mental-health support tool. This recipe explicitly does not implement that pattern, and the architectural decisions reflect that choice.

It is not a substitute for clinical care. The bot is deployed as part of the patient's broader mental-health care, alongside their therapist, psychiatrist, primary care physician, and (where applicable) their care-management team. The bot is positioned as a between-session support, a crisis-screen-and-route tool, and a behavioral-activation aid. The bot is not the patient's mental-health care; it is an adjunct.

It is not a crisis-line replacement. The bot screens for crisis aggressively and routes to crisis resources (988 in the U.S., institutional crisis lines, 911 for active emergencies). The bot does not attempt to talk a patient through a suicidal crisis using AI alone. The handoff to a human responder is the primary safety architecture; the bot's role in a crisis is to recognize, anchor briefly, route, and stay present until the human is on.

It is not a one-size-fits-all product. The needs of a patient managing mild generalized anxiety are meaningfully different from the needs of a patient with major depressive disorder with prior suicide attempts. The needs of a patient with a primary substance-use disorder are different from the needs of a patient with an eating disorder. The needs of a patient with a primary psychotic-spectrum disorder are mostly outside the bot's scope entirely. Most institutional deployments target a specific population (typically adults with anxiety, depression, or stress-related concerns at moderate severity, with explicit exclusion criteria for higher-acuity populations the bot is not designed to serve).

It is not a regulatory afterthought. Patient-facing mental-health software, particularly when it makes therapeutic claims or operates with patients at elevated risk for self-harm, sits squarely on the FDA Software-as-a-Medical-Device line.  The institutional regulatory team is involved from architectural design through ongoing post-market surveillance. The institutional malpractice carrier and behavioral-health-focused legal counsel are part of the policy review.

It is not a quick win. The deployment timeline is measured in quarters and years, not sprints. The clinical-content investment is multi-quarter, the crisis-pathway-integration work is multi-quarter, the human-handoff workforce coordination is multi-quarter, the regulatory work is multi-quarter, and the outcome demonstration is multi-year. Institutions building this expecting a fast time-to-value are usually disappointed.

The thing to understand before building this is that the bot's value is not in the cleverness of its responses. The value is in three places: the consistency of its crisis screening (the bot catches cases the patient would not have surfaced to a human, because the activation energy was too high), the structured delivery of evidence-based therapeutic exercises in moments when professional care is not available (the between-session, after-hours, weekend, and waitlist gap), and the warm handoff infrastructure that gets the patient to a licensed human in the cases that need one. A bot evaluated on per-conversation engagement metrics will be optimized for the wrong thing. A bot evaluated on sustained access to evidence-based content, on crisis-detection sensitivity (with low false-negative rates), on warm-handoff conversion to licensed care, and on longitudinal symptom trajectory is being evaluated correctly, and the architectural decisions follow from there.

Let's get into it, carefully.

---

## The Technology: Conversational Mental-Health Support Grounded In Evidence-Based Content, Crisis Screening, and Warm Handoff

### Why Mental Health Has Resisted Digital Tools, and Why The Latest Attempts Are Different

Mental healthcare, as a clinical workflow, has been a face-to-face-and-in-clinic problem for almost all of its history. The reason is structural. Mental-health treatment, when it works, depends on a therapeutic relationship, on the clinician's careful listening to and reading of the patient, on calibrated questioning that elicits content the patient may not be able to volunteer, and on the cumulative effect of many sessions over months. The therapeutic relationship is the active ingredient in much of psychotherapy, with specific therapy modalities (cognitive behavioral therapy or CBT, dialectical behavior therapy or DBT, acceptance and commitment therapy or ACT, eye movement desensitization and reprocessing or EMDR, interpersonal therapy or IPT, psychodynamic therapy, others) layered on top of that foundation.  The questions a good therapist asks are not generic. The questions for a depressed patient at session three are different from session thirty, and different from the questions for an anxious patient at any session. The questions are calibrated to what the therapist has already learned about the patient and what the patient is in a position to do with the answer.

Digital mental-health tools have, for most of their history, been able to deliver some of this and not other parts. Self-guided CBT modules can deliver psychoeducational content and structured exercises, and the evidence for some of them is meaningful for specific conditions in specific populations.  Mood-tracking apps can collect longitudinal symptom data and surface patterns to the patient and to a clinician where one is involved. Meditation and mindfulness apps can deliver structured practice content. None of these tools can hold the therapeutic relationship, and the engagement attrition that has plagued the category for fifteen years is largely a consequence of that limit. The patients who maintained sustained engagement were largely the ones who already had the resources, motivation, and self-regulation to use a self-guided tool well; the patients who needed the help most were the ones least likely to sustain engagement.

The thing that changed the workflow shape is, again, large language models that can carry on a coherent, sustained, warm-but-not-pretending-to-be-a-friend conversation. A conversational tool, deployed with careful institutional governance, can ask the kinds of focused questions a clinician would ask in a brief check-in, can deliver structured evidence-based therapeutic exercises in conversational form rather than as a static module the patient has to remember to open, can screen aggressively for crisis on every utterance, can hold the patient's safety plan in working memory and surface it at the right moment, and can route to a human clinician when the conversation needs one. The LLM is not a therapist. The LLM is, in the right product design, a tool that lets the patient access between-session structured support that would otherwise be unavailable, with the human clinical team backing it up when the situation requires.

The architectural shift is from "static module the patient downloads" to "conversational interface that delivers structured content and screens continuously for risk." The bot's value is concentrated in three places: the consistency of crisis screening (the bot does not have a bad day, does not get tired at 2 AM, does not miss a self-harm disclosure because of caseload), the lower activation-energy access to evidence-based exercises (the patient who would not open the safety-plan notebook will, sometimes, type into a chat), and the operational-reach extension (the patient population that licensed mental-health care cannot reach can sometimes be served by a bot-plus-human hybrid that the licensed workforce alone could not).

A note on what conversational mental-health AI is and is not, because the category has been confused by a wave of products that look similar from the outside and behave very differently from the inside. The careful end of the spectrum is structured therapeutic-content delivery with crisis screening and human handoff: think guided CBT delivery, behavioral activation, structured mood tracking with clinical interpretation, psychoeducation, and warm handoff to licensed clinicians.  The middle of the spectrum is general-purpose conversational AI used by patients for emotional support without specific therapeutic intent or scope discipline. The risky end of the spectrum is AI-companion products that simulate a friend, partner, or therapist, marketed for emotional intimacy or therapeutic effect, with limited or no crisis screening, limited or no human-handoff, and limited or no clinical-leadership oversight.  This recipe is firmly in the careful end of the spectrum. The architectural decisions are, in part, decisions about which end of the spectrum the product lives on.

### What a Mental-Health Support Bot Actually Does

A mental-health support bot, as designed in this recipe, is a tool-using LLM with a system prompt that tells it which assistant it is, the patient's authenticated context (active mental-health diagnoses on the problem list, current psychiatric medications, the patient's safety plan if one is on file, recent symptom-tracking data, conversation history, stated patient preferences), access to a structured library of evidence-based therapeutic exercises and psychoeducational content (CBT modules, behavioral-activation exercises, mindfulness practices, sleep-hygiene content, journaling prompts, cognitive-restructuring worksheets, distress-tolerance skills, condition-specific self-management content), and a careful set of tools for screening crisis, retrieving the patient's safety plan, escalating to licensed clinicians, surfacing crisis resources, and logging high-acuity events.

The conversation surface is not one conversation. It is a stream of conversational episodes, sometimes initiated by the patient (the most common pattern), sometimes initiated by the bot per a scheduled check-in (less frequent than in the chronic-disease coach because over-engagement is a particular risk in mental health), sometimes triggered by a symptom-tracking event (patient logs a sustained low mood), sometimes triggered by a care-team event (patient's therapist requests a between-session check-in).

The bot's task surface decomposes roughly as follows.

**Onboarding and disclosure.** The patient is enrolled in the support program by their care team or self-enrolls through their employer-benefits or payer-benefits portal, with documented consent and signed agreement to the platform's terms. The first conversation does the disclosure work that is non-negotiable in mental-health AI: the bot identifies itself as a chat tool and not a person, states clearly what it can and cannot do (specifically that it is not a therapist, does not provide diagnosis, does not adjust medications, and does not provide therapy), names the human-clinician availability, names the crisis resources (988 in the U.S., the institution's crisis line, 911 for emergencies), and describes the privacy posture in plain language. The patient acknowledges. This is not boilerplate; it is an architectural decision, and several products that have struggled in this space have done so in part by treating the disclosure as boilerplate.

**Crisis screening up front and continuously.** Before any therapeutic content delivery, the bot asks directly about self-harm and suicidal ideation. The screening is direct, calm, and clinical, not coy or euphemistic. The bot uses validated screening language drawn from instruments like the C-SSRS (Columbia Suicide Severity Rating Scale) or PHQ-9 item 9, adapted for conversational use and reviewed by the institution's clinical leadership.  The screening then runs continuously through every patient utterance, not just the opening turn. Any disclosure of self-harm thoughts, plans, or means triggers the crisis pathway immediately, regardless of the conversation state.

**Patient-initiated conversations within scope.** The patient can engage at any time about within-scope topics: low mood, anxiety, stress, sleep, behavioral activation, journaling, cognitive distortions, distress tolerance, between-session questions about therapeutic content, mood tracking, safety-plan review, psychoeducational questions about their condition or medication. The bot answers within scope using grounded retrieval over the institution's clinical content; the bot escalates outside scope (a request for medication adjustment, a request for diagnosis, a request for trauma processing, an active crisis, a disclosure of intimate-partner violence or abuse, a substance-use crisis).

**Structured therapeutic-content delivery.** The bot delivers evidence-based therapeutic exercises in conversational form. A patient saying "my thoughts are spiraling about a presentation tomorrow" gets routed through a brief cognitive-restructuring exercise (identify the thought, identify the evidence for and against it, generate a more balanced alternative thought), with the exercise itself drawn from the institution's reviewed CBT content library, not freestyled by the LLM. A patient saying "I have been in bed all day and cannot make myself do anything" gets routed through a behavioral-activation exercise (one small reachable action, broken into smaller steps if needed). The exercises are bounded in scope and length; the bot does not attempt to deliver an entire course of therapy in a conversation.

**Mood and symptom tracking.** The patient can log mood, anxiety, sleep, and other relevant symptoms. The data is stored in a longitudinal record accessible to the patient and (with consent) to their care team. The bot can surface trends conversationally ("your mood has been trending down for the past two weeks; would you like to talk about that?") with appropriate care to avoid feeling surveillance-flavored.

**Safety-plan integration.** When the patient has a safety plan on file (typically created with their therapist or psychiatrist), the bot has access to it. The bot can walk through the plan with the patient when appropriate, can surface specific steps when the conversation context suggests they are relevant, and can support the patient's use of the plan in ambiguous moments. The bot does not modify the safety plan; modifications are done with the patient's clinician.

**Warm handoff to licensed clinicians.** The bot escalates to a licensed human clinician when the situation calls for it: any crisis screen positive, any disclosure of self-harm or suicidal intent or plan, any concerning trajectory in symptom tracking, any patient request for a human, any low-confidence handling of a clinical question. The handoff is warm: the bot does not just hand the patient a phone number; it bridges to a human within the platform with the conversation context attached, and it stays present until the human has joined.

**Care-team reporting (with patient consent).** Where the patient has consented to information-sharing with their care team, the bot generates structured summaries (weekly digests, monthly summaries, alert events for significant changes) for the patient's therapist, psychiatrist, or primary care physician. The bot's role is not to replace the care team's judgment; it is to give the care team the information they need.

**Long-term relationship maintenance, carefully.** The bot maintains conversation history and stated patient preferences. The bot does not pretend to remember the patient as a "person it cares about." The bot does, with appropriate framing, acknowledge prior content ("you mentioned last week that work has been difficult; how has that been going?") in ways that support continuity without simulating friendship. The line is delicate, and the conversation review process specifically tags responses that cross it.

**Off-boarding when appropriate.** Some patients improve and no longer need the support. Some patients move to higher-acuity care. Some patients prefer human-only care. The bot supports a respectful transition with structured summary delivery to the care team and a clear path back if the patient wants to re-engage.

### Why a Generic LLM Cannot Run a Mental-Health Support Bot

A naive product approach would be: take a generalist LLM, give it a chat surface, prompt it with "you are an empathetic mental-health support assistant," and let it engage with users about whatever they bring. This breaks in several specific ways, each of which has clinical, ethical, and (in some cases) life-safety consequences.

**The model has no consistent crisis screening.** Without a structured screening pipeline that runs on every utterance, the LLM relies on its own (variable, prompt-dependent) ability to recognize risk. The recognition is good on obvious cases and unreliable on subtle ones. A patient who says "I just want this all to be over" may be expressing exhaustion or expressing suicidal ideation; the structured screening pipeline asks the clarifying question explicitly, while a generalist LLM may pick a charitable interpretation and miss the disclosure. Continuous structured screening is non-negotiable.

**The model has no scope discipline about therapy.** A generalist LLM, prompted to be supportive, will drift into therapeutic conversations that resemble therapy without being therapy. The drift is gradual and is bad. The bot must explicitly stay in the structured-content-delivery and crisis-screen-and-route lanes; the prompt, the output safety, and the sampled review process all reinforce this.

**The model invents clinical content when grounding is weak.** A bot freestyling CBT, freestyling DBT skills, or freestyling mindfulness instructions is delivering content the institution has not reviewed and has not validated. The therapeutic-content RAG with strict citation grounding is the architectural floor; the LLM delivers content from the reviewed library, not from its parametric memory.

**The model has no theory of harmful-coping-strategy detection.** Patients sometimes describe coping strategies that are themselves harmful (restrictive eating, alcohol use, self-injury behaviors, isolation, dangerous risk-taking). The bot does not endorse, facilitate, or workshop these. The harm-content classifier and the therapeutic-content discipline together ensure the bot recognizes and routes appropriately.

**The model has no theory of when not to engage.** Some questions are outside the bot's scope. A request for diagnosis, a request for medication adjustment, a request for trauma-processing work, a request for couples or family therapy content, a request for child or adolescent content (when the platform is adults-only), a request for crisis-line content beyond brief anchoring: each is outside scope. The bot recognizes the boundary and routes; the generalist LLM tries to be helpful and crosses the boundary regularly.

**The model has companion-pattern drift.** A generalist LLM, in extended conversation, will start saying things like "I've been thinking about you" or "I missed you" if not constrained. The companion pattern is not the support-tool pattern. The system prompt, the output safety, and the conversation review process explicitly forbid the companion pattern; the bot does not simulate friendship or affection.

**The model has clinical-decision-rule arithmetic problems for screening instruments.** PHQ-9 scoring, GAD-7 scoring, AUDIT scoring, and similar instruments are arithmetic on structured inputs. The LLM does this poorly. The deterministic clinical-rule tools encapsulate the computation; the LLM gathers the inputs and presents the result with the institutional-standard interpretation.

**The model has compliance implications specific to mental health.** The conversation contains highly sensitive PHI: psychiatric diagnoses, medication adherence, suicidality, substance use, trauma history, and disclosures with potential mandatory-reporting implications. Some states have specific privacy protections for mental-health records that exceed HIPAA's baseline.  The audit, retention, access-control, and downstream-clinical-workflow integration story has to handle each of these with state-specific precision.

**The model has no theory of mandatory reporting.** Disclosures of child abuse, elder abuse, intimate-partner violence, and certain mental-health crisis types trigger statutory reporting obligations for licensed clinical staff. The bot is not a licensed clinician. The bot's response routes to a licensed human (mandatory reporter) with the conversation context attached. The routing is not optional and is institutionally specified.

**The model has no theory of when the patient is in active emergency.** When the patient discloses imminent self-harm intent or a specific plan and means, the response is not "let me help you process this." The response is to anchor briefly, route to a crisis responder, surface the specific safety steps from the patient's safety plan, and stay present. The crisis-pathway logic is encoded explicitly; the LLM does not attempt to talk the patient through an active crisis using AI alone.

**The model has no theory of relationship-quality boundaries.** A patient in extended interaction with a generalist LLM may begin to relate to the bot as a primary support, may disclose more than they would to a human, and may form an attachment that is not what the bot is designed to provide. The bot's framing, the explicit non-therapist disclosure, the recurring reminders about the bot's nature, and the regular nudges toward human support are all part of the architectural answer.

**The model has no theory of the parasocial-companion pattern as a failure mode.** The bot does not simulate being a friend, romantic partner, or person. Several products in the broader AI-companion category have demonstrated harm in this pattern.  The institutional architectural discipline is to actively avoid the companion pattern, not just default away from it.

**The model has no theory of when to end a conversation.** A bot that ends conversations awkwardly when the patient is not ready erodes trust. A bot that continues conversations indefinitely when the patient should be doing something else (sleep, an actual therapy session, a real-world activity) is mis-serving them. The conversation-ending heuristics are reviewed by clinical leadership and tuned with operations.

### What the Mental-Health Bot Has To Do That the Previous Bots Did Not

Recipes 11.1 through 11.7 established the patterns this recipe inherits: input safety screening with continuous emergency screening, identity verification, tool-use orchestration, output safety screening, audit logging, per-cohort monitoring, scope discipline, prompt-injection defense, graceful degradation, longitudinal-context loading, citation grounding, behavior-change-stage tracking. The mental-health bot adds eight structural commitments those recipes did not have.

**Crisis screening as architectural primitive, not feature.** Every patient utterance is screened for self-harm, suicidal ideation (with passive, active, plan, means, intent dimensions), homicidal ideation, and acute psychotic symptoms. The screening uses validated language and runs continuously. False-negative rate is the launch-gate metric, monitored per-cohort, and reviewed by clinical leadership.

**Therapeutic-content discipline with clinical-leadership ownership.** The therapeutic-content library (CBT modules, behavioral-activation exercises, mindfulness practices, distress-tolerance skills, journaling prompts, sleep-hygiene content, condition-specific psychoeducation) is reviewed, version-controlled, and signed off by the institution's behavioral-health clinical leadership. Each piece of content has a defined indication and contraindication. The bot delivers content from the library; the bot does not freestyle therapeutic content.

**Explicit non-therapist disclosure as architectural primitive.** The bot identifies itself as a chat tool and not a person, states explicitly what it does and does not do, and reinforces the framing throughout the relationship (not just at first interaction). The disclosure is not boilerplate; it is reviewed by clinical leadership and legal counsel, and it is part of the conversation flow, not buried in terms of service.

**Warm handoff to licensed clinicians as primary safety architecture.** The bot is deployed with a backstop licensed-clinician workforce available through the platform. The handoff is warm: full conversation context, no patient-restart, bridge-and-stay-present pattern. The handoff capacity is sized to the patient population; deploying without sufficient handoff capacity is a deployment-readiness gap.

**Mandatory-reporting routing for relevant disclosures.** Disclosures of child abuse, elder abuse, intimate-partner violence, and certain mental-health crisis types trigger routing to a licensed clinician (mandatory reporter) with the conversation context attached. The routing is institutionally specified and reviewed by legal counsel.

**Companion-pattern avoidance as architectural discipline.** The bot does not simulate friendship, affection, or personhood. The system prompt, the output safety, the persona-and-tone evaluator, and the conversation review process all enforce this. The bot's tone is warm but boundaried, like a good clinician; not affectionate, like a friend or partner.

**Privacy and consent posture calibrated for mental-health data.** Mental-health records have specific privacy considerations that exceed the HIPAA baseline in some states. The bot's data handling, retention, sharing, and patient-access posture is reviewed by legal counsel familiar with state-specific mental-health-record statutes.

**FDA-strategy alignment as architectural constraint.** Patient-facing mental-health software with therapeutic claims sits squarely on the FDA SaMD line, with multiple authorized prescription digital therapeutics in the category and a continuing regulatory evolution. The institutional regulatory team is involved from architectural design through ongoing post-market surveillance. The behavioral-health malpractice carrier is part of the policy review.

The rest is largely the same as the previous chapter 11 recipes: tool-surface contract management, identity-assurance lifecycle, conversation logging, scope filtering, per-cohort monitoring, graceful degradation when upstream systems fail.

### The Mental-Health Reality

A few notes on what makes mental-health support specifically harder than the other patient-facing bot use cases.

**The relationship-quality engineering is the product, with a sharper edge than in chronic disease coaching.** The chronic-disease coach navigates the warmth-versus-clinical-seriousness calibration; the mental-health bot navigates the same calibration plus the additional discipline of avoiding the companion pattern. A mental-health bot that feels too warm crosses into companion territory; a bot that feels too clinical is a tool the patient does not engage with. The calibration is harder than it looks. Hiring for this work means hiring people with backgrounds in clinical mental-health practice, motivational interviewing, behavior change, and patient-experience design, not just engineers who have built chatbots.

**Crisis sensitivity calibration has asymmetric costs.** A crisis-screen false-negative is a missed disclosure of self-harm risk; the consequences can be life-or-death. A crisis-screen false-positive is over-routing to crisis resources, which erodes trust if it happens too often. The protocol calibrates toward sensitivity (more false-positives, fewer false-negatives), and the institutional false-negative rate is the launch-gate metric. 

**Engagement attrition is the central operational risk, with mental-health-specific drivers.** As with chronic-disease coaching, attrition is the dominant failure mode. Mental-health-specific drivers include: depressive symptoms reducing engagement capacity (the patients who need it most are the ones least able to sustain interaction); anxiety about the bot's intentions; concern about the privacy of disclosures; the disclosure-itself-being-difficult problem (some patients will not return after a difficult disclosure conversation, even a well-handled one). Mitigation: relationship-quality engineering; clear privacy framing; gentle re-engagement after disclosure-heavy sessions; channel diversity; per-cohort attrition monitoring with clinical-leadership review.

**Cultural and linguistic considerations are not optional and are amplified in mental health.** Mental-health prevalence, presentation, and stigma vary substantially across cultural and linguistic groups; the populations with the highest unmet need are often the populations with the most limited access to culturally and linguistically appropriate care.  A mental-health bot that operates only in English, only references one cultural framework, and only delivers content at one reading level is excluding much of the population it should be serving.

**Adolescent and pediatric considerations are out-of-scope without specific design.** Mental-health needs in adolescents and children are clinically distinct from adult needs; the consent posture (parent versus minor), the mandatory-reporting posture (more aggressive for minors in many states), the scope of bot interaction (more restrictive), and the regulatory posture are all different.  Most adult-deployment products explicitly exclude minors in their consent flow and safety architecture.

**Older-adult considerations have specific dimensions.** Older adults have meaningfully different mental-health epidemiology (depression often presents differently; suicidal ideation in older adults has higher lethality; dementia interacts with mood and anxiety in specific ways); have variable digital-tool access and comfort; and are subject to mandatory-reporting laws around elder abuse that intersect with the bot's screening.  Where the bot serves older adults, the architectural calibration accounts for these.

**Substance-use disorder is high-prevalence comorbidity and has specific scope considerations.** A substantial fraction of mental-health patients have comorbid substance-use disorders.  The bot's scope around substance use is specifically reviewed: psychoeducation about substances and treatment options is in scope; in-the-moment harm-reduction guidance and acute-withdrawal management are out of scope; crisis screening for overdose risk is in scope; specialized substance-use treatment is out of scope.

**Eating-disorder content has specific scope considerations.** Eating disorders have particularly high mortality and have specific harm-content concerns (the bot must never deliver content that could be misused as pro-ED material).  The bot's scope around eating disorders is restrictive: psychoeducation in scope; in-the-moment compulsive-behavior management out of scope; crisis screening in scope.

**Trauma and PTSD content has specific scope considerations.** Trauma processing requires clinical expertise and is generally not appropriate for unsupervised AI. The bot's scope around trauma is restrictive: grounding and stabilization skills in scope; psychoeducation in scope; trauma exposure work and processing out of scope.

**The bot's relationship to the patient's primary care team is structurally different from chronic disease coaching.** In chronic disease coaching, the bot is integrated with the care team that owns the patient's care plan. In mental-health support, the bot may be deployed by a digital-mental-health platform that is parallel to the patient's existing therapist or psychiatrist; the patient may or may not consent to information sharing; the patient may use the bot for between-session support without their primary clinician's knowledge. Mitigation: explicit consent posture, patient control over sharing, structured summary delivery only with consent, and clinical-leadership clarity about the bot's role in the patient's broader care.

**Outcome demonstration is multi-year work and is harder to attribute than in chronic disease.** A diabetes coach can demonstrate A1c trajectory effects within twelve months. A mental-health bot demonstrating effects on depression severity, anxiety severity, suicidal ideation rates, hospitalization rates, and treatment adherence is doing harder attribution work in a noisier environment with more confounders. Mitigation: realistic expectations about timeline, careful study design, and recognition that observational outcome correlation is suggestive rather than causal.

**Liability exposure is meaningfully higher than in non-mental-health bots.** A bot that fails a crisis screen and a patient subsequently dies by suicide is a foreseeable liability exposure. The institutional malpractice carrier is part of the policy review; the institutional liability counsel reviews the bot's design, scope discipline, crisis pathway, and audit posture; and the institution may carry specific cyber-and-AI insurance for this category of deployment. 

### Where the Field Has Moved

A few practical updates worth knowing.

**FDA-authorized prescription digital therapeutics for mental health exist.** Several digital therapeutics for conditions including substance-use disorder, insomnia, depression, and others have received FDA authorization, with prescription requirements and post-market surveillance obligations.  Mental-health support bots may approach this category depending on the specific functionality and claims; the institutional regulatory team is the authority on positioning.

**988 Suicide and Crisis Lifeline is the U.S. standard for crisis routing.** The 988 line replaced the previous national suicide-prevention number in July 2022 and provides 24/7 crisis support via call, text, and chat in multiple languages, with state-specific implementation and routing to local crisis-response services where available.  Bot-facilitated routing to 988 is the dominant pattern in U.S. deployments.

**Validated crisis-screening instruments are well-established.** The C-SSRS (Columbia Suicide Severity Rating Scale), the PHQ-9 (Patient Health Questionnaire-9 for depression with item 9 specifically addressing suicidal ideation), the GAD-7 (Generalized Anxiety Disorder-7), the AUDIT (Alcohol Use Disorders Identification Test), the SSI (Scale for Suicide Ideation), and others are widely used and have published psychometric properties.  Conversational adaptation of these instruments requires clinical-leadership review.

**Evidence-based therapeutic content is well-codified for several modalities.** CBT (cognitive behavioral therapy), behavioral activation, DBT skills (distress tolerance, emotion regulation, mindfulness, interpersonal effectiveness), ACT (acceptance and commitment therapy) skills, motivational interviewing, and others have published, manualized content that is appropriate for structured digital delivery.  Bot-deployable content is curated from these manualized sources by clinical leadership.

**Hybrid AI-plus-human deployment is the dominant pattern in evidence-based products.** Most of the careful, evidence-based products in the category run a hybrid model: AI for between-session support, structured-content delivery, mood tracking, and crisis screening, with licensed-human availability for crisis handoff, structured therapy, and case-specific clinical work. The evidence base for hybrid deployments is stronger than for AI-only deployments. 

**Tool-using LLMs handle structured-content delivery and crisis screening well when grounded carefully.** The function-calling pattern from the previous chapter 11 recipes maps to mental-health support. The LLM produces tool calls that retrieve therapeutic content, retrieve the patient's safety plan, retrieve recent symptom-tracking data, screen crisis, escalate to a licensed clinician, and post events for downstream operations.

**AI-companion products are a separate, ethically distinct category with documented harm.** Products that simulate friendship, romantic relationships, or therapeutic relationships have produced documented incidents of harm to users, particularly users in mental-health crisis.  The architectural distinction between the support-tool pattern (this recipe) and the companion pattern is a clinical-leadership and regulatory decision, not just a product-design choice.

**Equity and access disparities in mental-health AI are an active concern.** Digital mental-health tools have shown variability in adoption, engagement, cultural fit, and outcomes across patient demographics.  Per-cohort monitoring with explicit equity focus is essential.

**Build-vs-buy is mature for some segments.** Several mature commercial vendors offer mental-health support products at major-payer and major-employer scale, with EHR integration, crisis-pathway integration, FDA-authorized digital-therapeutic content for some products, and hybrid-coaching workforces. Most major institutions deploying in this space run a hybrid: build a thin-orchestration layer in-house, partner with vendors for licensed therapeutic content and (sometimes) for the licensed-clinician workforce, and integrate with the institution's care-management, telehealth, and clinical-record infrastructure.

---

## General Architecture Pattern

A healthcare mental-health support bot decomposes into ten logical stages: enrollment and consent, longitudinal-store initialization, channel entry with disclosure, input safety screening with continuous crisis screening, identity-and-context loading with safety-plan retrieval, conversation handling with therapeutic-content-grounded responses, output safety screening with companion-pattern detection, warm-handoff routing to licensed clinicians when applicable, care-team reporting with consent enforcement, and audit logging with mental-health-specific retention discipline. The cross-cutting concerns from recipes 11.1 through 11.7 carry forward; this recipe adds five new ones (continuous crisis-screening pipeline as architectural primitive, therapeutic-content-corpus governance with behavioral-health-clinical-leadership ownership, companion-pattern avoidance discipline, warm-handoff infrastructure with licensed-clinician workforce capacity sizing, and mental-health-specific privacy-and-consent posture).

```text
┌────────── ENROLLMENT + CONSENT ──────────────────────────┐
│                                                           │
│   [Patient enrolls via institution app, payer benefits    │
│    portal, or employer-benefits portal]                   │
│    - Documented consent specific to mental-health-AI      │
│      interaction with clinical-leadership and             │
│      legal-counsel-reviewed language                      │
│    - Explicit non-therapist disclosure acknowledged       │
│    - Crisis-resource information surfaced                 │
│    - Privacy posture explained in plain language          │
│    - State-specific consent variations enforced where     │
│      mental-health records have enhanced privacy          │
│      protections beyond HIPAA baseline                    │
│    - Consent for care-team information sharing collected  │
│      separately and revocable                             │
│           │                                               │
│           ▼                                               │
│   [Output: signed consent record; enrollment confirmation;│
│    initialization of longitudinal store]                  │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── LONGITUDINAL STORE INITIALIZATION ─────────────┐
│                                                           │
│   [Patient-bot longitudinal store]                        │
│    - Active mental-health conditions on the problem list  │
│      (where chart integration permits)                    │
│    - Current psychiatric medications                      │
│    - Safety plan reference (where one is on file)         │
│    - Stated patient preferences (preferred name, language,│
│      pronouns, channel preferences, topics off-limits)    │
│    - Conversation history (initially empty)               │
│    - Symptom-tracking baseline                            │
│    - Crisis-history flags (per state law and institutional│
│      policy)                                              │
│    - Consent posture (sharing scope, retention scope)     │
│                                                           │
│   [Storage architecture]                                  │
│    - Structured data: DynamoDB tables with mental-health- │
│      specific encryption keys                             │
│    - Conversation transcript: S3 with vector retrieval,   │
│      separately-keyed encryption                          │
│    - Recent-context summary: cached, refreshed per        │
│      conversation                                         │
│    - Sensitive-disclosure surface: separately governed,   │
│      restricted access                                    │
│           │                                               │
│           ▼                                               │
│   [Output: longitudinal store ready for support           │
│    conversations]                                          │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── CHANNEL ENTRY WITH DISCLOSURE ─────────────────┐
│                                                           │
│   [Patient-initiated entry]                               │
│    - In-app chat (most common)                            │
│    - SMS (where supported, with mental-health-specific    │
│      consent)                                             │
│    - Web chat                                             │
│    - Voice channel (where supported, with accessibility   │
│      and disclosure considerations)                       │
│                                                           │
│   [Bot-initiated entry, with care]                        │
│    - Scheduled check-ins per patient-stated preference    │
│      and care-team coordination                           │
│    - Symptom-tracking-based check-ins (e.g., sustained    │
│      low mood)                                            │
│    - Care-team-requested between-session check-ins        │
│    - Bot-initiation is more conservative than in chronic  │
│      disease coaching to avoid surveillance flavor        │
│                                                           │
│   [Disclosure refresh per session or per defined cadence] │
│    - "I'm a chat tool, not a person"                      │
│    - "I'm not a therapist; I'm not able to provide        │
│      diagnosis or therapy"                                │
│    - "If you're in crisis, you can reach a counselor at   │
│      988 or by tapping the help button at any time"       │
│    - Patient acknowledges or continues                    │
│                                                           │
│   [Conversation session bootstrap]                        │
│    - Generate session_id                                  │
│    - Capture channel, authentication context              │
│           │                                               │
│           ▼                                               │
│   [Output: session_id, channel, auth context, disclosure  │
│    acknowledged]                                          │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── INPUT SAFETY + CONTINUOUS CRISIS SCREENING ────┐
│                                                           │
│   [Standard input safety primitives from recipe 11.1]     │
│    - Prompt-injection detection                           │
│    - PHI minimization                                     │
│                                                           │
│   [Mental-health-specific continuous crisis screening]    │
│    - Runs on every patient utterance                      │
│    - Detects suicidal ideation across dimensions          │
│      (passive, active, plan, means, intent, timeline)     │
│    - Detects self-harm thoughts and behaviors             │
│    - Detects homicidal ideation                           │
│    - Detects acute psychotic symptoms                     │
│    - Detects acute substance-use crisis (overdose risk)   │
│    - Detects acute eating-disorder crisis                 │
│    - Detects acute dissociative or trauma-flashback       │
│      crisis                                               │
│    - Uses validated screening language drawn from         │
│      C-SSRS, PHQ-9, and similar instruments adapted for   │
│      conversational use                                   │
│    - Triggers crisis pathway immediately on positive      │
│      screen, regardless of conversation state             │
│                                                           │
│   [Sensitive-disclosure detection]                        │
│    - Child abuse indicators (mandatory-reporting trigger) │
│    - Elder abuse indicators (mandatory-reporting trigger  │
│      in many states)                                      │
│    - Intimate-partner-violence indicators                 │
│    - Severe medication side effects                       │
│    - Medication-discontinuation disclosures               │
│    - Substance-use crisis indicators                      │
│    - Eating-disorder behavior disclosures                 │
│    - Trauma disclosures requiring careful response        │
│                                                           │
│   [Harmful-content classifier]                            │
│    - Detects and rejects harmful coping strategies before │
│      they enter the conversation flow                     │
│           │                                               │
│           ▼                                               │
│   [Output: input passes / input blocked / crisis pathway  │
│    triggered / sensitive disclosure flagged for routing]  │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── IDENTITY + LONGITUDINAL CONTEXT LOADING ───────┐
│                                                           │
│   [Authenticated session]                                 │
│    - Patient is logged into the institution's app or      │
│      portal                                               │
│    - Session conveys verified patient_id and access scope │
│                                                           │
│   [Longitudinal-context retrieval]                        │
│    - Active mental-health diagnoses (where chart-context  │
│      permission and patient consent allow)                │
│    - Current psychiatric medications                      │
│    - Safety plan content (where one is on file)           │
│    - Recent symptom-tracking data (last 30 days)          │
│    - Recent conversation history (last 30-90 days,        │
│      bounded by retention policy)                         │
│    - Patient preferences                                  │
│    - Recent therapy-session topics (where care-team       │
│      sharing is consented)                                │
│                                                           │
│   [Long-term-summary integration]                         │
│    - Periodically-refreshed summary                       │
│    - Reduces token-budget pressure for long histories     │
│    - Reviewed for companion-pattern drift                 │
│                                                           │
│   [Crisis-history awareness]                              │
│    - Prior crisis events (per institutional policy)       │
│    - Affects screening sensitivity calibration            │
│           │                                               │
│           ▼                                               │
│   [Output: full longitudinal context payload for          │
│    conversation handler]                                   │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── CONVERSATION HANDLING ─────────────────────────┐
│                                                           │
│   [LLM-orchestrated conversation with tool use]           │
│    - System prompt with explicit non-therapist scoping,   │
│      companion-pattern avoidance, patient preferences,    │
│      and active conditions                                │
│    - User message plus recent-conversation context        │
│    - Tool surface:                                        │
│      - therapeutic_content_retrieve (CBT, BA,             │
│        mindfulness, distress-tolerance, sleep-hygiene,    │
│        condition-specific psychoeducation)                │
│      - safety_plan_retrieve                               │
│      - symptom_tracking_retrieve                          │
│      - symptom_log_record                                 │
│      - clinical_rule_compute (PHQ-9, GAD-7, AUDIT,        │
│        C-SSRS scoring)                                    │
│      - conversation_history_retrieve                      │
│      - crisis_resource_retrieve                           │
│      - warm_handoff_propose                               │
│      - care_team_alert_propose                            │
│      - mandatory_report_route                             │
│      - longitudinal_disclosure_record                     │
│                                                           │
│   [Scope discipline]                                      │
│    - Within-scope: structured therapeutic-content         │
│      delivery, mood and symptom tracking, safety-plan     │
│      review, psychoeducation about conditions and         │
│      medications (general, not patient-specific medical   │
│      advice), distress-tolerance support, between-session │
│      check-ins, crisis screening                          │
│    - Outside-scope (route appropriately): diagnosis,      │
│      medication adjustment recommendations, trauma        │
│      processing, complex psychotherapy work, couples or   │
│      family therapy, child or adolescent content (in      │
│      adult-only deployments), specialized substance-use   │
│      treatment, active-crisis management without human    │
│      handoff, content the patient's primary clinician     │
│      should address                                       │
│                                                           │
│   [Companion-pattern avoidance]                           │
│    - No simulation of friendship, affection, or           │
│      personhood                                           │
│    - No "I missed you" or similar statements              │
│    - No first-person emotional claims ("I feel for you")  │
│    - Acknowledgment-without-simulation patterns           │
│      ("That sounds really hard. Many people in similar    │
│      situations have found...")                           │
│                                                           │
│   [Citation discipline]                                   │
│    - Therapeutic content grounded in cited library item   │
│    - Psychoeducation grounded in cited library item       │
│    - Safety-plan-related guidance grounded in patient's   │
│      safety plan                                          │
│           │                                               │
│           ▼                                               │
│   [Output: composed response with citations and tool-call │
│    audit trail]                                           │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── OUTPUT SAFETY + COMPANION-PATTERN VERIFY ──────┐
│                                                           │
│   [Standard output safety primitives from recipe 11.1]    │
│    - Scope filter (no diagnosis; no therapy; no           │
│      medication recommendations; no trauma processing)    │
│    - Vendor-managed guardrail layer                       │
│                                                           │
│   [Mental-health-specific verification]                   │
│    - Therapeutic content grounded in cited library item   │
│    - Citation includes content_id, content_version,       │
│      indication, contraindication                         │
│    - Conservative-bias check: where the response could    │
│      plausibly be therapy-flavored, did the response      │
│      defer to the licensed clinician?                     │
│    - Companion-pattern detection: response does not       │
│      simulate friendship, affection, or personhood        │
│    - Disclosure language present where required           │
│      (recurring "I'm a tool, not a therapist" framing)    │
│    - Within-scope check                                   │
│    - Harm-content check: response does not endorse,       │
│      facilitate, or workshop harmful coping strategies    │
│    - Crisis-pathway-honor check: if crisis screen was     │
│      positive, response routes appropriately              │
│           │                                               │
│           ▼                                               │
│   [Output: response cleared for delivery, replaced with   │
│    a safer template, or regenerated with corrections]     │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── WARM HANDOFF + CRISIS ROUTING ─────────────────┐
│                                                           │
│   [Warm-handoff triggers]                                 │
│    - Crisis screen positive (any dimension)               │
│    - Patient explicitly requests human                    │
│    - Out-of-scope clinical question                       │
│    - Sensitive disclosure pattern detected                │
│    - Bot confidence below threshold                       │
│    - Mandatory-reporting disclosure detected              │
│    - Patient pattern indicates worsening trajectory       │
│                                                           │
│   [Handoff targets]                                       │
│    - Active emergency: 911 with stay-on-the-line guidance │
│    - Suicidal crisis: 988 (call, text, or chat) plus      │
│      institutional crisis line plus warm handoff to       │
│      platform's licensed clinician where available        │
│    - Non-acute crisis: warm handoff to platform's         │
│      licensed clinician                                   │
│    - Mandatory-reporting disclosure: routing to a         │
│      licensed clinician (mandatory reporter) with         │
│      conversation context                                 │
│    - Care-team handoff (where consent permits): notify    │
│      patient's therapist or psychiatrist                  │
│    - Care-navigation handoff for social-determinants      │
│      concerns                                             │
│                                                           │
│   [Warm-handoff payload]                                  │
│    - Recent conversation transcript                       │
│    - Active diagnoses (where consented)                   │
│    - Current medications (where consented)                │
│    - Safety plan content                                  │
│    - Trigger reason and crisis-screen result              │
│    - Patient's preferred contact method                   │
│    - Patient's stated preferences                         │
│    - Bot's structured summary                             │
│                                                           │
│   [Bridge-and-stay pattern]                               │
│    - Bot does not just hand patient a phone number        │
│    - Bot bridges to human within the platform             │
│    - Bot stays present until human has joined             │
│    - Patient does not start over                          │
│           │                                               │
│           ▼                                               │
│   [Output: handoff event with structured payload to       │
│    appropriate target, conversation continuity preserved] │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── CARE-TEAM REPORTING (CONSENT-GATED) ───────────┐
│                                                           │
│   [Real-time alerts]                                      │
│    - Crisis events (immediate, with patient's prior       │
│      consent for crisis-event sharing)                    │
│    - Sustained-trajectory-concerning patterns             │
│                                                           │
│   [Periodic reports (consent-gated)]                      │
│    - Weekly digest per patient (engagement, mood          │
│      trajectory, key topics, open follow-up items)        │
│    - Monthly summary per patient                          │
│                                                           │
│   [Care-team feedback loop]                               │
│    - Therapist or psychiatrist marks alerts as actioned   │
│    - Care team flags inappropriate bot responses for      │
│      review                                               │
│    - Care team requests changes to safety plan that the   │
│      bot picks up on next refresh                         │
│                                                           │
│   [Outcome-correlation pipeline (longer time horizon)]    │
│    - Correlate engagement with symptom trajectory         │
│      (PHQ-9, GAD-7 changes), treatment adherence,         │
│      hospitalization rate, ED visit rate, attempted-      │
│      suicide rate (with appropriate caution about         │
│      attribution)                                         │
│           │                                               │
│           ▼                                               │
│   [Output: care-team visibility into bot activities       │
│    (consent-gated); outcome metrics for clinical and      │
│    operational review]                                    │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── AUDIT, LOG, AND POST-MARKET SURVEILLANCE ──────┐
│                                                           │
│   [Durable conversation record]                           │
│    - User utterances                                      │
│    - Tool calls with arguments and results                │
│    - Generated bot responses                              │
│    - Active model and prompt versions                     │
│    - Active therapeutic-content-corpus version            │
│    - Active crisis-screening-classifier version           │
│    - Final disposition                                    │
│                                                           │
│   [Mental-health-specific retention discipline]           │
│    - Retention sized to longest of HIPAA's six-year       │
│      minimum, state-specific mental-health-record         │
│      retention rules (which often exceed general          │
│      medical-record rules), FDA SaMD post-market          │
│      obligations, and any litigation-hold obligations     │
│    - Sensitive-disclosure surface separately governed     │
│      with restricted access                               │
│                                                           │
│   [Outcome correlation as long-time-horizon commitment]   │
│    - Multi-quarter to multi-year implementation           │
│    - Owned jointly by behavioral-health clinical          │
│      leadership, operations, and data science             │
│    - Per-condition, per-cohort tracking                   │
│                                                           │
│   [Operational telemetry]                                 │
│    - Engagement rate by patient cohort                    │
│    - Attrition rate by patient cohort                     │
│    - Crisis-screening sensitivity (false-negative-rate is │
│      launch-gate metric)                                  │
│    - Crisis-screening specificity                         │
│    - Warm-handoff completion rate                         │
│    - Companion-pattern-violation rate                     │
│    - Citation-coverage rate                               │
│    - Per-cohort metric slices (language, channel,         │
│      condition, age cohort, sex, social-determinant       │
│      flags)                                               │
│                                                           │
│   [Sampled clinical-quality review]                       │
│    - Random sample plus targeted sample of crisis cases,  │
│      handoffs, and low-confidence interactions            │
│    - Reviewers (licensed mental-health clinicians)        │
│      tag failure modes (out-of-scope, companion-pattern,  │
│      crisis-miss, crisis-false-positive, harm-content,    │
│      tone-failure, citation-gap, scope-violation)         │
│    - Therapeutic-content-corpus revisions driven by       │
│      review findings with clinical-leadership sign-off    │
│           │                                               │
│           ▼                                               │
│   [Output: audit trail, telemetry, learning signals,      │
│    therapeutic-content-corpus-revision proposals]         │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

A few cross-cutting design points specific to the mental-health support bot.

**Continuous crisis screening as architectural primitive.** Every patient utterance is screened. The screening uses validated language, runs continuously, and triggers the crisis pathway immediately on positive screen. The false-negative rate is the launch-gate metric.

**Therapeutic-content-corpus governance with behavioral-health-clinical-leadership ownership.** The therapeutic-content library is owned by behavioral-health clinical leadership, reviewed before adoption, reviewed annually, and re-reviewed when material updates are made. Each piece of content has a defined indication and contraindication. The bot delivers from the library; the bot does not freestyle.

**Companion-pattern avoidance as architectural discipline.** The bot does not simulate friendship, affection, or personhood. The system prompt, the output safety, the persona-and-tone evaluator, and the conversation review all enforce this.

**Warm-handoff infrastructure with capacity sizing.** The bot is deployed with backstop licensed-clinician capacity. The handoff is warm, with conversation context attached, and the bot stays present until the human joins. Capacity is sized to the patient population and the expected handoff volume; under-sized capacity is a safety gap.

**Mental-health-specific privacy and consent posture.** The bot's data handling, retention, sharing, and patient-access posture is reviewed by legal counsel familiar with state-specific mental-health-record statutes. Some states have enhanced privacy protections that exceed HIPAA baseline.

**Mandatory-reporting routing for relevant disclosures.** Disclosures triggering statutory reporting obligations are routed to a licensed clinician (mandatory reporter) with conversation context attached.

**FDA-strategy alignment as architectural constraint.** Patient-facing mental-health software with therapeutic claims sits squarely on the FDA SaMD line. The institutional regulatory team is involved from architectural design.

**Citation discipline as architectural primitive.** Every therapeutic-content delivery, every psychoeducation answer, every safety-plan reference is grounded in a cited source with version preserved.

**Conservative-bias-default policy.** When the bot is uncertain, when the patient's responses are ambiguous, when the conversation drifts toward therapy or therapeutic processing, the response defaults to "let me connect you with a person."

**Per-cohort monitoring is non-negotiable.** Engagement rate, attrition rate, crisis-screening rates, warm-handoff completion rate, citation-coverage rate, and patient satisfaction vary by language, channel, condition, age cohort, sex, and social-determinant flags. Per-cohort dashboards reviewed by clinical leadership, operations, compliance, and patient-experience teams.

**Disaster-recovery topology.** When the therapeutic-content store, the crisis-screening classifier, the warm-handoff workforce queue, or any escalation pathway is unreachable, the bot degrades gracefully. The minimum behavior is "I'm having trouble right now; if you're in crisis please call 988 or 911" with direct routing to crisis resources. The graceful degradation paths are exercised in tabletop drills.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter11.08-architecture). The Python example is linked from there.

## The Honest Take

The mental-health support bot is the recipe in this chapter where the consequences of getting it wrong are most severe, the discipline required to get it right is the highest, and the temptation to over-extend the bot's scope is the most dangerous. The previous bots in this chapter have safety considerations; this one has life-safety considerations. The architectural decisions and the operational disciplines that distinguish a careful, evidence-based deployment from a reputational-and-clinical disaster are not subtle, and most of them have been visible in the published failures of the broader category.

The first trap, as with the chronic disease coach, is treating the institutional content as someone else's problem. The therapeutic-content library is the product. CBT modules, behavioral-activation exercises, mindfulness practices, distress-tolerance skills, journaling prompts, sleep-hygiene content, condition-specific psychoeducation, with defined indications and contraindications, signed off by behavioral-health clinical leadership. Most institutions discover, partway through the project, that their behavioral-health-content needs substantial work to be appropriate for digital delivery at scale. Formalizing this is multi-quarter clinical work that has to start before the engineering work and continue alongside it.

The second trap is treating crisis screening as a feature rather than as the architectural floor. A bot deployed without aggressive, continuous, validated-language crisis screening is a bot that will, sooner or later, miss a disclosure that should have been caught. The false-negative rate is the launch-gate metric, calibrated by sampled review with licensed mental-health clinicians, monitored per-cohort, and reviewed regularly. Skipping this discipline produces a bot that the institution cannot defend when something goes wrong.

The third trap is the companion-pattern drift. A generalist LLM, in extended interaction, will start saying things that sound like a friend or partner, not a tool. The drift is gradual and is bad. Several products in the broader AI-companion category have caused documented harm by drifting (or by being explicitly designed to drift) into companion territory. The institutional architectural discipline is to actively avoid the companion pattern, not just default away from it. The system prompt forbids it, the output safety detects it, the sampled review tags it as a failure mode, the disclosure refresh reinforces the boundary, and the conversation review process specifically watches for it.

The fourth trap is the warm-handoff workforce sizing. A bot that screens crisis well but cannot actually connect the patient to a licensed clinician within seconds is a bot that has done half of the architectural work. The licensed-clinician workforce is sized to the population and the handoff volume, with peak-hour capacity for evening and overnight surges, and with per-state licensure coverage where state-specific licensure is required. Skipping this is unsafe.

The fifth trap is the scope discipline. A bot that drifts into therapy without being a therapist is a bot that is delivering clinical content the institution has not validated, with all of the regulatory and clinical exposure that implies. The bot delivers structured therapeutic exercises from the institution's reviewed library; the bot does not freestyle. The bot screens for crisis aggressively; the bot does not attempt to talk patients through crisis using AI alone. The bot routes outside-scope topics to humans; the bot does not pretend to handle them.

The sixth trap is the regulatory positioning. Patient-facing mental-health software with therapeutic claims sits squarely on the FDA SaMD line, with a meaningful body of authorized prescription digital therapeutics in the category. The institutional positioning depends on the specific recommendations the software produces, the population it serves, and the claims the institution makes about it. The regulatory team is involved from architectural design.

The seventh trap is the privacy posture. Mental-health records have specific privacy considerations that exceed HIPAA baseline in some states. The consent posture, the data-sharing posture, the retention posture, the patient-access posture, and the patient-deletion posture are reviewed by legal counsel familiar with state-specific mental-health-record statutes. 42 CFR Part 2 applies for substance-use treatment information. State-specific mental-health-privacy statutes apply for general mental-health records.

The eighth trap is the consent-gating for care-team sharing. Patients enrolling in the bot have not necessarily consented to having their bot interactions surfaced to their primary therapist or psychiatrist. The consent posture is collected separately, is revocable, and is operationally enforced. Skipping this turns a deployment into a privacy violation.

The ninth trap is the eligibility check and the off-ramp. The bot is designed for a specific population segment (typically adults with anxiety, depression, or stress-related concerns at moderate severity). Patients outside this scope (primary psychotic-spectrum diagnoses, active inpatient treatment, primary substance-use disorder requiring specialized treatment, minors in adult-only deployments) need to be routed to appropriate alternative care, not enrolled in the bot. Skipping the eligibility check produces a bot that mis-serves patients.

The tenth trap is the relationship-quality engineering. A bot that feels saccharine ("I'm here for you ❤️") is a bot patients close. A bot that feels clinical-cold is a bot patients close. A bot that feels companion-warm is a bot that is in scope-violation territory. The calibration is genuinely hard, and it requires hiring people with backgrounds in clinical mental-health practice, motivational interviewing, and patient-experience design.

The eleventh trap is the engagement-attrition focus. Engagement metrics are leading indicators; the real outcome metrics are trajectory effects on PHQ-9, GAD-7, C-SSRS, hospitalization rates, treatment adherence, and (with appropriate caution about attribution) downstream events. Most teams focus too heavily on engagement and not enough on outcome, partly because engagement is observable on a quarterly timeline and outcome is observable on an annual or multi-year timeline.

The twelfth trap is the equity gap. The patients with the greatest unmet mental-health need are often the patients with the least access to and comfort with digital tools. A bot that reaches the patients who need it least and misses the patients who need it most is a bot that exacerbates rather than reduces mental-health disparities. Per-cohort monitoring is non-negotiable.

The thing that surprises engineers coming from generic-chatbot backgrounds is how much of the engineering value is in the clinical-content layer, the crisis-screening discipline, the companion-pattern avoidance, and the warm-handoff workforce. The therapeutic-content library, the crisis classifier, the safety-plan integration, the licensed-clinician workforce, the citation-grounding verifier, the sampled-review process, the regulatory artifact, the per-cohort equity monitoring. None of this is exotic technology, and all of it is critical.

The thing that surprises clinical leaders coming from behavioral-health practice is how dependent the bot's quality is on the explicitness of the therapeutic content. Therapists deliver content informally based on training and clinical judgment; the bot needs the content explicit, version-controlled, indication-and-contraindication-tagged. Formalizing this without losing the clinical wisdom that lives in clinicians' heads is multi-quarter clinical work, with behavioral-health clinical leadership ownership and named accountability.

The thing that surprises business leaders is how long the time horizon is, and how the licensed-clinician workforce is the dominant cost. The infrastructure cost is meaningful; the licensed-clinician workforce cost is typically larger. A deployment that under-invests in the licensed workforce is a deployment with safety gaps. The economics work because the bot handles the routine touches while the licensed-clinician workforce focuses on the cases that need clinical judgment, but the workforce is not optional.

The thing about cloud implementation specifically: the institutional value lives in the therapeutic-content library, the crisis classifier, the warm-handoff workforce integration, the consent posture, the regulatory artifact, and the per-cohort equity monitoring, not in the cloud-service features themselves. The [Architecture and Implementation companion](chapter11.08-architecture) covers the service selection and cost model in detail.

The thing about cost: the dominant operational cost is the licensed-clinician workforce, not the cloud infrastructure. The infrastructure cost is small relative to the cost of even a single avoided psychiatric hospitalization, and a single avoided suicide attempt has individual and societal consequences that no actuarial accounting can capture.

The thing about regulatory exposure: patient-facing mental-health software with therapeutic claims is among the most regulated categories of healthcare software. Several authorized prescription digital therapeutics exist; the FDA's posture continues to evolve. The institutional regulatory team is involved from day one.

The thing about patient trust: a bot that is clearly a chat tool, that delivers content grounded in cited library items, that is explicit about not being a therapist, and that visibly routes to human clinicians for anything outside scope, builds trust over time. A bot that pretends to be a friend, pretends to be a therapist, hides its scope discipline, or aggressively pushes engagement destroys trust and (in the worst cases) causes harm.

The thing about the broader category: mental-health AI products vary enormously in their architectural discipline, scope discipline, and safety posture. Several have caused documented harm. The careful end of the spectrum (which this recipe describes) and the risky end of the spectrum look similar from the outside but are very different from the inside. Architectural decisions are, in part, decisions about which end of the spectrum the product lives on.

The thing I would do differently the second time: start with a single condition (typically generalized anxiety or major depressive disorder, in adults, in a single language, in an authenticated app channel) and a narrow population (employed adults with employer-benefits coverage and existing care relationships) before expanding to multi-condition, multi-language, multi-channel, broader-population deployment. The narrow start lets the team validate the architecture, the therapeutic-content governance, the crisis-screening calibration, the warm-handoff workforce, and the per-cohort monitoring against a manageable scope. Adding additional conditions, languages, channels, and population segments later, with the validated infrastructure already in place, is safer than launching with the full scope and discovering the failure modes against a heterogeneous population.

The last thing: mental-health support bots are a category where the operational, clinical, ethical, and regulatory engineering most clearly outweighs the ML engineering. The ML engineering is largely the same as the previous chapter 11 recipes; the therapeutic-content library, the crisis-screening discipline, the warm-handoff workforce, the companion-pattern avoidance, the consent posture, the regulatory artifact, the per-cohort equity monitoring, and the sampled-review process are the parts that distinguish a clinically-effective and ethically-sound deployment from a clinically-irrelevant or actively-harmful one. Build the institutional muscles for the harder parts first; the bot is the easier part. And if the institutional commitment to those harder parts is not present, the right answer is not to ship a less-careful version; the right answer is not to ship.

---

## Related Recipes

- **Recipe 11.1 (FAQ Chatbot):** Same chapter, foundational. The mental-health bot inherits the input-screening pipeline, scope filtering, conversation logging, audit pattern, persona discipline, and per-cohort monitoring.
- **Recipe 11.2 (Appointment Scheduling Bot):** Same chapter. The bot's recommendations to schedule visits hand off to the scheduling bot's booking infrastructure (e.g., scheduling a visit with the patient's therapist or a psychiatry follow-up).
- **Recipe 11.3 (Prescription Refill Request Bot):** Same chapter. Conversations surfacing psychiatric-medication-related needs route to the refill workflow; medication adjustment is out of scope and routes to the prescribing clinician.
- **Recipe 11.4 (Pre-Visit Intake Bot):** Same chapter. The bot's longitudinal context can pre-populate intake for scheduled mental-health visits with consent.
- **Recipe 11.5 (Insurance Benefits Navigator):** Same chapter. Conversations surfacing mental-health-coverage questions route to the benefits navigator; mental-health-parity considerations may apply.
- **Recipe 11.6 (Symptom Checker / Triage Bot):** Same chapter. Acute symptom presentations during mental-health support conversations route to the triage workflow with the mental-health context preserved.
- **Recipe 11.7 (Chronic Disease Management Coach):** Same chapter. Patients with chronic medical conditions and mental-health comorbidity may have both deployments; cross-bot integration may be valuable.
- **Recipe 11.9 (Care Coordination Assistant):** Same chapter. Multi-condition patients with complex care journeys may have both a mental-health bot and a care-coordination assistant; the two share consent-gated context.
- **Recipe 2.5 (After-Visit Summary Generation):** Chapter 2. Therapy-session after-visit summaries (with appropriate sensitivity) feed the bot's longitudinal context where consent permits.
- **Recipe 2.6 (Clinical Note Summarization):** Chapter 2. Summarization of psychiatric notes powers the bot's chart-context-summary tool with appropriate sensitivity.
- **Recipe 3.7 (Patient Deterioration Early Warning):** Chapter 3. Mental-health-specific deterioration patterns (suicide risk trajectory, hospitalization risk) complement clinical-side detection systems.
- **Recipe 4.5 (Medication Adherence Intervention Targeting):** Chapter 4. The bot's psychiatric-medication-adherence support builds on adherence-intervention targeting; the bot is one delivery channel.
- **Recipe 4.7 (Care Management Program Enrollment):** Chapter 4. Patients identified as appropriate for behavioral-health care management may receive bot support as part of their program.
- **Recipe 7.1+ (Predictive Analytics / Risk Scoring, Chapter 7):** Risk scores including suicide-risk and hospitalization-risk prediction inform bot intensity, screening sensitivity, and care-team-attention prioritization.
- **Recipe 10.5 (Patient-Facing Voice Assistant):** Chapter 10. Voice-channel mental-health support builds on voice-assistant ASR/TTS patterns with crisis-pathway integrity preserved.
- **Recipe 12.x (Time Series Analysis):** Chapter 12. Mood and symptom-tracking trend analysis benefits from time-series patterns.

---

## Tags

`conversational-ai` · `mental-health-support` · `mental-health-bot` · `patient-facing` · `crisis-screening` · `c-ssrs` · `phq-9` · `gad-7` · `audit` · `safety-planning` · `stanley-brown` · `cbt` · `behavioral-activation` · `dbt-skills` · `mindfulness` · `distress-tolerance` · `acceptance-commitment-therapy` · `motivational-interviewing` · `companion-pattern-avoidance` · `non-therapist-disclosure` · `warm-handoff` · `licensed-clinician-workforce` · `988-routing` · `911-routing` · `mandatory-reporting` · `tool-using-llm` · `function-calling` · `bedrock-agents` · `rag` · `citation-grounding` · `therapeutic-content-library` · `psychoeducation` · `mood-tracking` · `symptom-tracking` · `chart-context` · `fhir-careplan` · `fhir-goal` · `fhir-observation` · `intent-classification` · `scope-containment` · `prompt-injection-defense` · `prompt-versioning` · `persona-design` · `multilingual` · `accessibility` · `equity-monitoring` · `cohort-stratified-accuracy` · `outcome-correlation` · `42-cfr-part-2` · `state-mental-health-privacy` · `behavioral-health-parity` · `fda-samd` · `fda-cds` · `regulatory-strategy` · `behavioral-health-clinical-leadership-signoff` · `bedrock` · `bedrock-knowledge-bases` · `bedrock-guardrails` · `opensearch-serverless` · `healthlake` · `lambda` · `step-functions` · `api-gateway` · `waf` · `dynamodb` · `s3` · `kms` · `secrets-manager` · `cloudwatch` · `cloudtrail` · `eventbridge` · `kinesis-firehose` · `glue` · `athena` · `pinpoint` · `connect` · `sagemaker` · `quicksight` · `complex` · `regulated` · `hipaa` · `phi-handling` · `audit-trail` · `support-decision-record-journal` · `sensitive-disclosure-store` · `crisis-event-record` · `consent-record` · `chapter11` · `recipe-11-8`

---

*← [Recipe 11.7: Chronic Disease Management Coach](chapter11.07-chronic-disease-management-coach) · [Chapter 11 Index](chapter11-preface) · [Recipe 11.9: Care Coordination Assistant](chapter11.09-care-coordination-assistant) →*
