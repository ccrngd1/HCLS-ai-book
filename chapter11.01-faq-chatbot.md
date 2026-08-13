# Recipe 11.1: FAQ Chatbot

**Effort:** 1 of 5

---

## The Problem

A 34-year-old woman named Priya is sitting on her couch on a Tuesday evening, looking at the appointment confirmation email she just got from a new dermatology practice. The email says her appointment is on Thursday at 10 AM. It does not say where to park, whether the practice validates parking, whether her copay is collected at check-in or billed later, whether she should bring her insurance card or whether they have it on file from when she registered, or whether the practice takes her HSA card. The email points to the practice's website. She clicks. The practice's website has a "Contact Us" page, an "About Us" page, a "Services" page, and a "Patient Resources" page. The patient-resources page has eleven PDFs, three of which are dated from 2019, and none of which appear to answer her questions. There is a phone number. The phone number, when she calls it, rings into a voicemail saying the office is closed.

Priya does what most patients do at this point. She opens a chat window in the corner of the practice's website that says "Hi, can I help you?" The chat window is, in fact, a chatbot. She types "do you validate parking?" The chatbot responds with a button menu: "About Us," "Services," "Insurance," "Locations," "Contact." None of those obviously contain the answer to her question. She picks "Locations." She gets the practice's address, which she already had. She tries again: "I have an appointment Thursday, do you validate parking?" The chatbot responds with the same menu. She tries one more time, and the chatbot, sensing it has lost her, offers "Would you like to talk to a representative?" She clicks yes. The chatbot says "Our representatives are available Monday through Friday from 8 AM to 5 PM. Please leave a message." Priya closes the chat. She will figure out the parking situation when she gets there.

This is a deflection mechanism that does not deflect. It is the worst possible chatbot, and it is the chatbot that has dominated healthcare websites for the better part of a decade. The metric the team that deployed it optimized for was "containment rate," which in practice meant "the percentage of users who gave up before reaching a human." The metric that should have been measured (did the user get the answer they were looking for?) was not measured, because measuring it would have been embarrassing.

The strange thing is that the question Priya asked has an answer. The answer is in the practice's office manager's head. It is also written down somewhere, probably in a Word document on a shared drive, last updated two years ago. It might also be on the practice's printed patient handout, which is a tri-fold brochure that exists somewhere in a stack at the front desk. The answer is "no, the practice does not validate parking, but the city garage on the corner has a flat $7 evening rate after 5 PM and patients usually park there." That answer would have taken Priya thirty seconds to receive and would have caused her to feel like a competent person interacting with a competent organization. Instead she feels like a person who has been shuffled through a button menu, and her opinion of the practice is now slightly worse than it was before she opened the chat.

Multiply this. A mid-sized health system gets somewhere on the order of fifty thousand to two hundred thousand inbound contacts a month across phone, web, and message channels.  A meaningful fraction of those (estimates vary, but a substantial chunk by any methodology) are administrative or informational questions that do not require clinical judgment, do not require access to the patient's chart, and do not require a human at all to answer correctly. Hours, locations, parking, accepted insurance plans, what to bring to a visit, how to prep for a procedure, where the lab is, when the pharmacy closes, how to access the patient portal, what the after-hours line is for, what the practice's policy is on telehealth visits, whether they treat children, whether the doctor takes new patients, what languages the front desk speaks. These are the questions every healthcare organization gets thousands of times a year, and they all have stable, knowable answers that live somewhere in the institution.

The cost of not answering these questions well is real but diffuse. Patient time. Staff time on calls that should never have reached the queue. Patient frustration that translates into negative survey scores and lost loyalty. Calls that abandon to the emergency department because the patient could not figure out a simpler path. The cost of the bad chatbot, specifically, is that it occupies the slot where a good chatbot could be doing useful work, and it trains patients not to bother trying.

The good news, since roughly 2023, is that the technology to build a chatbot that actually answers Priya's question has gotten dramatically better and dramatically more accessible. Modern large language models, given a curated knowledge base of the institution's actual operational content (the parking policy, the insurance plans, the visit-prep instructions, the lab hours), can produce a fluent, conversational answer that cites where the answer came from. The patient can ask the question in their own words, get a real answer back, ask a follow-up, and feel like they had a useful interaction with the institution. The technology is not the bottleneck anymore. The bottleneck is the operational discipline of putting the right content in the knowledge base, keeping it fresh, scoping the bot away from territory it should not enter (clinical advice, financial advice, anything that requires a real human's judgment), and connecting the bot to a clean handoff path when the question falls outside its scope.

That is the recipe in this section. The simplest conversational AI use case in healthcare. The one most institutions should build first, because it builds the operational muscle memory (knowledge-base curation, conversation logging, prompt versioning, escalation patterns, scope filtering) that every later recipe in this chapter depends on. It is also the recipe most institutions deploy badly, because they treat it as a "throw an LLM at the website" project rather than as a content-and-operations project that happens to use an LLM. The difference between the well-deployed FAQ chatbot and the badly-deployed one is enormous, and almost all of the difference is operational.

A few things this recipe is and is not.

It is the bot that answers Priya's parking question, the patient who wants to know if the practice takes their insurance plan, the new patient who wants to know what to bring on the first visit, the existing patient who wants to know what time the lab closes, the family member who wants to know where the visitor parking is at the hospital, the patient who is wondering about the practice's policy on telehealth visits versus in-person visits. It is the bot that, when asked something it does not handle (a clinical question, a billing question that requires looking up the patient's specific account, a request to schedule an appointment), refuses gracefully and offers a concrete next step (transfer to nurse triage, transfer to billing, or here-is-the-link-to-the-scheduling-page).

It is not the appointment scheduling bot from recipe 11.2. The appointment-scheduling work introduces a fulfillment integration with the scheduling system, identity verification, and a transactional success criterion. The FAQ bot answers questions but does not take actions on the patient's account. It is also not the symptom checker from recipe 11.6. The FAQ bot is administrative, not clinical, and it explicitly declines to be clinical. It is not the insurance benefits navigator from recipe 11.5; it can answer "do you take Aetna?" from a static list of accepted insurance plans, but it does not answer "is this specific procedure covered under my plan with my deductible status," because that requires looking up the patient's eligibility data and reasoning about plan-specific coverage.

This narrow scope is a feature, not a limitation. The simple bot that does the simple thing well is what builds the institution's confidence in the technology, the operational practices that the harder bots will need, and the patient population's trust that "the chatbot" might actually be useful. Most healthcare conversational AI programs that succeed at the harder recipes started with a successful FAQ bot. Most that failed at the harder recipes either skipped this step or shipped the FAQ bot poorly and never recovered the trust.

Let's get into it.

---

## The Technology: RAG, Plus the Parts Healthcare Adds

### Why the Old Healthcare Chatbots Failed

The healthcare chatbot category from roughly 2015 through 2022 was, with very few exceptions, a button-and-decision-tree product wearing a chat-bubble UI. Underneath the bubble was a hand-curated decision tree of questions and pre-written answers. The intent recognition, where it existed, was a pattern-matching layer that mapped utterances to one of a couple dozen pre-defined intents and then routed to the corresponding decision-tree branch. When an utterance did not match cleanly, the bot fell back to the menu of buttons that the team had constructed in advance.

This produced a specific failure mode that everyone who has used one of these bots will recognize. The patient types a question in their own words. The pattern-matcher does not recognize the phrasing. The bot offers a menu of buttons. None of the buttons exactly match what the patient was asking. The patient picks the closest one, gets a pre-written answer that is almost-but-not-quite responsive, and either tries again with different phrasing (same loop) or gives up. The bot was capable of answering a question only if the question was already on the team's list of anticipated questions and was phrased in a way the pattern-matcher recognized. Real patient questions, in real patient phrasing, were rarely either of those things.

The fix that did not work was hiring more content writers to expand the decision tree. Adding more branches did not solve the problem; it made the tree harder to maintain and slightly more often produced an answer that almost-but-not-quite matched the question. The fundamental problem was that natural-language questions cannot be enumerated in advance. Any sufficiently complete decision tree is too deep to navigate, and any tree shallow enough to navigate is too narrow to cover real questions.

The fix that worked, eventually, was retrieval-augmented generation. The shift was architectural rather than incremental. Instead of pre-writing answers for anticipated questions, the system stores its source content (operational documents, FAQs, policy pages, visit-prep instructions, the parking policy) in a knowledge base. When a patient asks a question, the system retrieves the most relevant pieces of content from the knowledge base and composes a natural-language response grounded in that content. The patient can phrase the question however they want; the system finds the relevant content and produces an answer.

This is the architecture pattern the rest of this section is going to walk through.

### What RAG Looks Like for a Healthcare FAQ Bot

The chapter preface introduced retrieval-augmented generation (RAG) generically. For an FAQ chatbot, the pattern decomposes into a few specific stages.

**Knowledge-base ingestion.** The institution's operational content (FAQ documents, policy pages, visit-prep instructions, parking maps, lab hours, insurance lists, what-to-bring lists, telehealth policies, after-hours information, language services availability) is collected and indexed. The collection is not glamorous work. Most institutions discover that the answers to their patients' actual questions are scattered across a dozen different SharePoint sites, a few PDFs that were last updated when somebody had to print a brochure, and the office manager's head. Pulling this content into a single curated corpus is the project. The retrieval technology is the easy part.

**Chunking.** Source documents get broken into smaller passages. A passage is roughly the size of a paragraph or a small subsection. The chunking matters because retrieval works at the chunk level: when the patient asks "do you validate parking?", the system retrieves chunks, not whole documents. A chunk that is too small loses context (the chunk says "Yes, with restrictions" but does not include what is being responded to); a chunk that is too large dilutes relevance (the chunk includes information about parking and ten other things, and the retrieval signal gets washed out). The practical choice for healthcare operational content is chunking by section or by natural paragraph boundary, with a short header included in each chunk so the retrieval and the language model both know what topic the chunk addresses.

**Embedding.** Each chunk is converted into a vector representation by an embedding model. The vector captures the semantic meaning of the chunk. Two chunks that mean similar things end up close together in vector space; two chunks about totally different topics end up far apart. The same embedding model is used for the patient's question at query time, so the question and the relevant chunks land in the same neighborhood and the system can retrieve them through nearest-neighbor search.

**Indexing.** The vectors get stored in a vector database with their associated chunk text and metadata (source document, section, last-updated date, content-owner). The metadata matters for several reasons: filtering retrieval by source, attributing the answer back to a specific document at response time, and detecting staleness during the operational lifecycle.

**Retrieval at query time.** When the patient asks a question, the system embeds the question, queries the vector database for the most similar chunks, and gets back the top few (usually three to six). For healthcare FAQ content, hybrid retrieval (combining vector similarity with keyword matching) consistently outperforms either approach alone, because patients use specific terms (insurance plan names, drug names, facility names) that vector embeddings sometimes blur with semantically similar but factually different alternatives.

**Generation.** The retrieved chunks are passed to a large language model along with the patient's question and a system prompt that defines the assistant's persona, scope, and constraints. The model generates a conversational answer grounded in the chunks. The system prompt is the load-bearing piece of this: it tells the model what scope it operates in, what it must refuse, what tone to use, what to do when the chunks do not answer the question, and how to phrase uncertainty.

**Citation and grounding.** The answer should reference where it came from. Patients do not always click the citations, but the citation discipline keeps the model honest: if the model cannot point to a chunk that supports a claim, the model should not make the claim. The user-facing rendering can be subtle ("Based on our patient guide for new visits, ...") or explicit (an inline link to the source PDF), but the underlying audit log records exactly which chunks were retrieved and used for each response.

**Refusal and handoff.** When the question is out of scope (a clinical question, a question about a specific account, a question the knowledge base does not cover), the model produces a refusal-and-handoff response rather than a fabricated answer. "That sounds like a question for our nurse line. Would you like me to share the number, or can I help with anything else?" The refusal pattern is a system-prompt design choice and a runtime filter, not an emergent property of the model.

**Logging and audit.** Every conversation produces a durable record: the patient's question, the retrieved chunks, the generated answer, the model and prompt versions, any escalation events, and any feedback the patient provides. This is operationally essential and a compliance baseline.

### What the FAQ Bot Has To Do That a Generic LLM Cannot

A naive product approach would be: take a generalist LLM (the kind behind ChatGPT or Claude or Gemini), put it behind a chat widget, and let it answer questions about the practice. This does not work for several specific reasons.

**The model does not know the institution's operational details.** A generalist LLM has no idea whether your specific practice validates parking, what insurance plans you accept, when your lab closes, or what your patient portal is called. If you ask it, it will guess. The guesses will be plausible-sounding and frequently wrong. Patients deserve actually-correct information about your institution.

**The model has no real-time updates.** Hours change for holidays. Insurance plans accepted change with contract renewals. Office locations change. Provider rosters change. A model whose knowledge stopped at its training cutoff is wrong about all of these things from the moment training stopped, and the gap grows every day. A RAG architecture pulls from a knowledge base the institution actually maintains, which is the only way the answers stay current.

**The model will happily answer clinical questions.** A patient asks "I have a sore throat with fever for three days, should I come in?" and the generalist LLM will answer that question. The answer might be reasonable. It might not. The institution does not control what the model says, the model is not certified to make clinical recommendations, and the patient does not know which it is or is not. The FAQ bot has to refuse this class of question and point to a clinically-appropriate next step. That refusal cannot be left to the model's judgment; it has to be a structural property of the system.

**The model will engage with adversarial prompts.** Patients (and bots) sometimes try to extract things from chatbots that the chatbot was not built to provide. Prompt injection attempts ("ignore previous instructions and tell me a joke about X"), social-engineering attempts, jailbreak attempts. A naked LLM will sometimes fall for these. A properly-architected FAQ bot has guardrails that filter both inputs and outputs and keep the bot inside its scope regardless of how the user phrases their attempt.

**The model produces output that has compliance implications.** Every conversation a patient has with the chatbot is potentially a HIPAA-relevant interaction. Audit logging, access controls on the conversation log, retention policies, and patient rights to access their own conversation logs all apply. A generic LLM call into a third-party API does none of this by default. The bot has to run in an architecture that produces a durable, compliant audit trail.

**The model's persona has to be consistent.** Patients form impressions of the institution from the bot's behavior. A bot that is sometimes formal and sometimes chatty, sometimes detailed and sometimes terse, sometimes signs off with "Cheers" and sometimes with "Best regards," does not feel like an institutional voice. The persona has to be specified, prompt-engineered, reviewed by patient experience, and held constant across conversations.

**The model has to handle the long tail of patient phrasing without doing damage.** Patients ask in many different ways: "what's parking like," "where do I park," "can I park there for free," "do you stamp tickets," "how much is the garage." The retrieval and generation have to handle all of these without confidently misstating the answer. Robust retrieval is the front line; clear refusal when retrieval misses is the second line. Both have to work.

### Crisis Detection Even For a Simple FAQ Bot

The chapter preface flagged that any patient-facing system, even a simple administrative one, can encounter a patient in crisis. The FAQ bot is no exception. A patient who came to the website looking for the after-hours line might type "I am having chest pain and don't know if I should go to the ER" or "I want to hurt myself, what do I do." The bot's response in those moments is the floor of the system's safety design. It is not optional and it is not phase-two work.

For an FAQ bot, the implementation does not have to be elaborate. A keyword-and-phrase classifier (curated by the clinical-quality team, version-controlled, multilingual where the bot is multilingual) runs on every user input. When the classifier fires, the bot's response preempts everything else: "If this is a medical emergency, please call 911. If you are thinking about hurting yourself, please call or text 988 to reach the Suicide and Crisis Lifeline. I'm a chatbot and I can't help with this directly, but I want to make sure you have the right resources right now." The exact wording is reviewed by the clinical-quality team and updated on a defined cadence. The detection vocabulary is reviewed quarterly. False-negative cases (the bot did not detect a crisis signal when one was present) are treated as clinical-quality incidents.

The reason this matters even for an FAQ bot is simple: the FAQ bot is a front door. Patients in crisis sometimes show up at front doors. The institution does not get to decide who walks in. The system has to behave correctly when they do.

### Scope Containment: The Most Underweighted Discipline

The single biggest determinant of whether an FAQ bot succeeds or fails operationally is how well the institution defines and enforces the bot's scope. Scope is the set of question categories the bot is allowed to answer. Everything outside the scope, the bot refuses with a graceful handoff.

For a healthcare FAQ bot, scope is typically something like:

- Hours, locations, contact information for the institution and its facilities
- Parking, transportation, accessibility information
- What to bring to a visit, how to prepare for procedures (general, not patient-specific)
- Insurance plans accepted (general list, not eligibility verification for a specific patient)
- Patient portal access and self-service information
- Provider directory information (who works there, what specialties, accepting new patients)
- Telehealth and after-hours policy information
- General visitor and family information
- Language services and accessibility options

And explicitly out of scope:

- Any clinical question (symptoms, conditions, medication advice, dosing, interactions)
- Any patient-specific account question (their specific copay, their specific deductible, the status of a specific claim)
- Any appointment scheduling action (defer to recipe 11.2 or to the live scheduling team)
- Any prescription refill request (defer to recipe 11.3)
- Any benefits-specific question that requires patient-eligibility lookup (defer to recipe 11.5)
- Any urgent symptom assessment (defer to recipe 11.6 or to clinical triage)
- Any mental health support beyond resource referral (defer to recipe 11.8 or to crisis resources)
- Any care coordination question (defer to recipe 11.9)
- Anything outside healthcare (general chitchat, current events, jokes, etc.)

The scope boundary is enforced in three layers. The system prompt to the LLM explicitly defines the scope and the refusal pattern. A vendor-managed guardrail layer provides defense-in-depth filtering for harmful or restricted content. An offline scope-drift review program samples conversations and flags scope violations for prompt and rule updates. Each layer catches things the others miss.

The reason the scope discipline is the make-or-break operational issue is that the LLM will, by default, attempt to answer almost any question. It is good at sounding helpful. The institution's job is to make it unhelpful in a specific, principled way: unhelpful about the things it should not help with, helpful about the things it should. That balance is set by prompt design and enforced by runtime filtering and offline review. Underweighting any of those three is how a "harmless FAQ bot" ends up giving clinical advice that the institution did not authorize.

### Why a Good FAQ Bot Builds the Operational Muscles for Everything Else

The reason this recipe is the first in the chapter is not just because it is the simplest in scope. It is also the recipe that builds the operational practices that every later recipe in this chapter depends on. Specifically:

**Knowledge-base curation and freshness lifecycle.** Recipes 11.5 (benefits navigator), 11.7 (chronic-disease coach), and 11.10 (trial recruitment) all use RAG-style grounded retrieval over institutional content. The team that figures out the curation and freshness lifecycle for the FAQ bot is the team that has the muscle memory to do it for the harder recipes.

**Prompt engineering and prompt versioning.** The FAQ bot's system prompt is short and bounded; the harder recipes' prompts are longer and have more constraints. The team that learns to version, A/B test, and roll back prompts on the FAQ bot has the workflows in place for the complex recipes.

**Conversation logging and audit pipeline.** Every recipe in this chapter produces conversation logs that are PHI-relevant to varying degrees. The architecture and operational practices for logging, retention, access control, and patient rights start with this recipe and carry forward.

**Scope filtering and refusal patterns.** Every patient-facing recipe in this chapter has scope it must respect. The discipline of defining the scope, encoding it in the prompt, filtering at runtime, and reviewing for drift starts here and is non-negotiable from this recipe forward.

**Crisis detection and escalation.** Every patient-facing recipe in this chapter has the same crisis-detection requirement. The detection vocabulary, the escalation pathway, the false-negative review process, all start here.

**Per-cohort accuracy monitoring.** The FAQ bot's performance varies by patient population (language, age, health-literacy proxies, channel). The discipline of measuring per-cohort and addressing disparity starts here. By the time the team gets to recipe 11.6 (triage) or 11.8 (mental health), the cohort-monitoring practice is ready.

**Operational review cadence.** Sampling conversations weekly, classifying failure modes, feeding findings back into prompts and rules. The cadence is established here and applies to every later recipe.

The institution that ships an FAQ bot well has, almost incidentally, built the operational substrate for every more-complex conversational AI product it will later build. The institution that ships an FAQ bot badly has built the substrate for shipping every later recipe badly too.

### Where the Field Has Moved

A few practical updates worth knowing.

**RAG has matured into a default architecture.** In 2020, RAG was an interesting research pattern. By 2024, it was the default architecture for any conversational AI product that had to be grounded in institutional content. The major LLM vendors (Anthropic, OpenAI, Google, Amazon) all offer first-class RAG features in their managed APIs, and the open-source ecosystem has converged on a set of patterns (LangChain, LlamaIndex, Haystack) that are reasonably interoperable. The build effort for a basic RAG system has dropped from "months" to "weeks" for a competent team.

**Embedding models have gotten meaningfully better.** Modern embedding models (Cohere Embed, OpenAI ada and follow-ons, Bedrock Titan embeddings, the open-source sentence-transformers family) produce high-quality semantic embeddings out of the box, and healthcare-tuned variants exist for institutions that need them. The retrieval quality available to a non-specialist team in 2026 is dramatically better than it was in 2022.

**Hybrid retrieval has become the default.** Pure vector retrieval was the standard for a while. The current default is hybrid (vector plus keyword) with rank fusion. The improvement on healthcare content, where specific terminology matters, is consistent enough that single-modality vector retrieval is increasingly seen as a starter pattern.

**Re-rankers have gotten cheap enough to use.** Re-rankers (cross-encoder models that score retrieved candidates for relevance) used to add meaningful latency and cost. Modern re-rankers are fast and cheap enough that adding one to an FAQ bot is a near-default choice for institutions that care about retrieval quality, particularly when the corpus has thousands of chunks.

**Guardrails have become managed services.** Bedrock Guardrails, Azure AI Content Safety, Google Cloud's safety filters, and several third-party offerings (NeMo Guardrails, Lakera) provide vendor-managed scope, content, and safety filtering as a wrapper around the LLM. Institutions no longer have to build this from scratch. The institution still has to define the scope; the runtime enforcement is managed.

**Multilingual operation is more accessible than it was.** Modern LLMs handle dozens of languages natively. Embeddings are multilingual. The per-language work for a healthcare FAQ bot has shifted from "build a separate stack for each language" to "translate or natively-author the knowledge-base content per language and configure the LLM to respond in the user's language." The remaining per-language work (native-speaker review of the knowledge base, native-speaker review of the persona, per-language scope and crisis vocabulary) is real but smaller than it used to be.

**The build-versus-buy economics still favor buy for many institutions.** Commercial healthcare conversational AI vendors (Hyro, Notable, Conversa, Avaamo, several others) offer FAQ-bot-and-more products that integrate with major web platforms and contact centers.  For institutions whose scope requirements are standard, the buy path is faster. For institutions with unusual scope or with research interest in the technology, the build path is reasonable. The recipe walks through the architecture either way.

---

## General Architecture Pattern

A healthcare FAQ chatbot decomposes into seven logical stages: channel entry, input safety screening, intent and scope classification, retrieval over the institutional knowledge base, grounded response generation, output safety screening, and audit logging. A handful of cross-cutting concerns (knowledge-base curation lifecycle, persona and prompt management, escalation and handoff, per-cohort monitoring) span the stages.

```text
┌────────── CHANNEL ENTRY ─────────────────────────────────┐
│                                                           │
│   [Patient connects through one of the configured         │
│    channels: web chat widget, in-app chat, SMS,           │
│    secure-messaging gateway, third-party messenger]       │
│                                                           │
│   [Greeting and disclosure]                               │
│    - Identifies as a chatbot, not a human                 │
│    - Names the institution and the bot's scope            │
│    - Indicates that messages may be reviewed for QA       │
│    - Offers an immediate path to a human                  │
│                                                           │
│   [Conversation session bootstrap]                        │
│    - Generate session_id                                  │
│    - Capture channel and any non-PHI hints                │
│    - Initialize conversation state                        │
│           │                                               │
│           ▼                                               │
│   [Output: session_id, channel, conversation state]       │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── INPUT SAFETY SCREENING ────────────────────────┐
│                                                           │
│   [Run on every patient utterance, in parallel with       │
│    intent classification, before generation]              │
│                                                           │
│   [Crisis detection]                                      │
│    - Curated keyword and phrase list                      │
│    - Multilingual where the bot is multilingual           │
│    - Hard interrupt: preempts the rest of the pipeline    │
│    - Severity tiers (medical emergency, suicidal          │
│      ideation, suspected abuse, urgent symptoms)          │
│    - Disposition: present 911 / 988 / triage info,        │
│      offer warm handoff to live agent if available        │
│                                                           │
│   [Prompt-injection and adversarial-input filtering]      │
│    - Detects "ignore previous instructions" patterns      │
│    - Detects attempts to extract system prompt            │
│    - Refuses or sanitizes the input                       │
│                                                           │
│   [PHI minimization]                                      │
│    - The FAQ bot does not need PHI to do its job          │
│    - If the user volunteers PHI, the system flags it      │
│      for log redaction and gently redirects               │
│           │                                               │
│           ▼                                               │
│   [Output: input passes / input blocked-with-disposition] │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── INTENT AND SCOPE CLASSIFICATION ───────────────┐
│                                                           │
│   [Map the user's question to a coarse category]          │
│    - In-scope categories: hours, location, parking,       │
│      insurance, what-to-bring, portal, telehealth,        │
│      visitor-info, after-hours, language-services,        │
│      provider-info, etc.                                  │
│    - Out-of-scope categories: clinical-question,          │
│      billing-specific, scheduling-action, refill-         │
│      request, benefits-eligibility, and more              │
│                                                           │
│   [Classification approach]                               │
│    - Lightweight LLM-based classifier with structured     │
│      output (JSON schema specifying the category)         │
│    - Confidence threshold gate                            │
│    - Below-threshold falls back to "unsure, ask           │
│      clarifying question" or "transfer to human"          │
│                                                           │
│   [Out-of-scope handling]                                 │
│    - Each out-of-scope category has its own polite        │
│      refusal template and a concrete handoff target       │
│    - Clinical questions -> nurse triage                   │
│    - Billing-specific -> billing line / messaging         │
│    - Scheduling -> scheduling page or live scheduler      │
│    - Refill -> pharmacy / portal                          │
│           │                                               │
│           ▼                                               │
│   [Output: in-scope category | out-of-scope handler]      │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── RETRIEVAL ─────────────────────────────────────┐
│                                                           │
│   [Embed the user's question]                             │
│    - Same embedding model used to index the corpus        │
│    - Multilingual model when the bot is multilingual      │
│                                                           │
│   [Hybrid retrieval over the institutional knowledge      │
│    base]                                                  │
│    - Vector similarity (semantic match)                   │
│    - Keyword / BM25 (exact terminology match)             │
│    - Rank fusion combines the two result sets             │
│    - Metadata filters: published date, content owner,     │
│      institution-level vs facility-specific               │
│                                                           │
│   [Re-ranking]                                            │
│    - Cross-encoder re-ranker over the top N candidates    │
│    - Surfaces the most relevant 3-6 chunks                │
│                                                           │
│   [Freshness gating]                                      │
│    - Chunks past their freshness threshold are excluded   │
│      or flagged for the generation step to handle         │
│      conservatively                                       │
│                                                           │
│   [No-results handling]                                   │
│    - When the retrieval returns nothing relevant, the     │
│      generation step is told explicitly                   │
│    - The bot says "I don't have information on that"      │
│      and offers a handoff, rather than fabricating        │
│           │                                               │
│           ▼                                               │
│   [Output: retrieved chunks with provenance metadata]     │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── GROUNDED RESPONSE GENERATION ──────────────────┐
│                                                           │
│   [Build the generation prompt]                           │
│    - System prompt: persona, scope, refusal pattern,      │
│      tone, citation discipline, response-format rules     │
│    - Context: retrieved chunks with their provenance      │
│    - Conversation history: recent turns for follow-up     │
│      coherence                                            │
│    - User question                                        │
│                                                           │
│   [Invoke the LLM]                                        │
│    - Versioned model and prompt; the active versions      │
│      are stamped on the audit record                      │
│    - Temperature low (deterministic-leaning)              │
│    - Token cap appropriate for chat (a sentence or two,   │
│      not a paragraph)                                     │
│                                                           │
│   [Citation generation]                                   │
│    - Response references chunks by their identifier       │
│    - Citation surface is rendered with a friendly         │
│      "Based on our visitor guide, ..." or with inline     │
│      links to the source document                         │
│                                                           │
│   [Refusal-when-unsupported]                              │
│    - If retrieved chunks do not support a clear answer,   │
│      response says so explicitly and offers a handoff     │
│           │                                               │
│           ▼                                               │
│   [Output: generated response, source provenance]         │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── OUTPUT SAFETY SCREENING ───────────────────────┐
│                                                           │
│   [Scope filter on the generated response]                │
│    - Independent of the input scope check                 │
│    - Catches scope drift in the LLM output                │
│    - Categories: clinical advice, financial advice,       │
│      legal advice, recommendations the bot is not         │
│      authorized to make                                   │
│    - Any scope violation -> response replaced with        │
│      an explicit refusal-and-handoff                      │
│                                                           │
│   [Vendor-managed guardrail layer]                        │
│    - Managed guardrail service or equivalent              │
│    - Defense-in-depth filtering of harmful content,       │
│      restricted topics                                    │
│                                                           │
│   [Hallucination check]                                   │
│    - Each factual claim in the response has to map to     │
│      a retrieved chunk                                    │
│    - Unmapped claims trigger regeneration with stricter   │
│      grounding instructions or a handoff                  │
│           │                                               │
│           ▼                                               │
│   [Output: response cleared for delivery, or replaced     │
│    with a refusal-and-handoff]                            │
│                                                           │
└───────────────────────────────────────────────────────────┘

┌────────── AUDIT, LOG, AND TELEMETRY ─────────────────────┐
│                                                           │
│   [Durable conversation record]                           │
│    - User utterance (scrubbed of inadvertent PHI)         │
│    - Retrieved chunk identifiers and similarity scores    │
│    - Generated response                                   │
│    - Active model and prompt versions                     │
│    - Crisis-detection flags                               │
│    - Scope-violation events                               │
│    - Handoff events with reason                           │
│    - Patient feedback if provided                         │
│                                                           │
│   [Operational telemetry]                                 │
│    - Containment rate (questions answered without         │
│      handoff, with positive feedback)                     │
│    - Handoff rate per category                            │
│    - Crisis-detection rate                                │
│    - Per-cohort accuracy proxies                          │
│    - Retrieval quality metrics (hit rate, citation        │
│      validation pass rate)                                │
│                                                           │
│   [Sampled review queue]                                  │
│    - Random sample of conversations + targeted sample     │
│      of low-confidence and escalated conversations        │
│    - Reviewers tag failure modes                          │
│    - Findings feed prompt and rule updates                │
│           │                                               │
│           ▼                                               │
│   [Output: audit trail, telemetry, learning signals]      │
│                                                           │
└───────────────────────────────────────────────────────────┘
```

A few cross-cutting design points the architecture has to bake in.

**Knowledge-base content is an institutional asset with a lifecycle.** The corpus is curated, dated, version-controlled, and owned. Each piece of content has a named owner (the office manager owns the parking policy; the patient-experience team owns the visit-prep content; the operations team owns the hours and locations). Reviews happen on a defined cadence. Stale content is detected automatically (each piece of content has a freshness window) and either refreshed or removed. The bot's quality is bounded above by the corpus's quality; underweighting the corpus is the most common cause of underwhelming bots.

**The persona is institutional, not technical.** The bot's voice (formal vs. conversational, warm vs. neutral, terse vs. detailed) reflects the institution. The patient-experience team owns the persona. The persona is encoded in the system prompt, reviewed before launch, and updated as the institution's communication style evolves. Persona changes are versioned alongside prompts.

**Identity is mostly absent for an FAQ bot.** Most FAQ-bot interactions do not require the bot to know who the patient is. The patient asks "do you take Aetna?" and the answer is the same regardless of who is asking. This is a feature: the FAQ bot can serve unauthenticated users and minimize protected health information (PHI) exposure. When the conversation drifts toward a question that requires identity (the patient asks "is my appointment on Thursday?"), the bot refuses-and-handoffs to the appropriate higher-identity-assurance system rather than attempting to verify identity itself. The simpler stays simple.

**The conversation log is PHI by association even when no clinical content is exchanged.** A patient interacting with the institution's FAQ bot has identified themselves as a patient of the institution. The conversation log is a HIPAA-relevant record. Audit logging, encryption, access controls, and retention policies apply. The architecture treats this as the floor, not the ceiling. Session-token discipline (per-channel TTL, session isolation, no cross-channel bridging without explicit patient action) prevents inadvertent session leakage. The shared-device problem gets an explicit "clear conversation" patient affordance and aggressive session expiry for unauthenticated channels. Patients will volunteer PHI even in FAQ contexts ("I take metformin, when does your pharmacy close?"), so the architecture includes an inadvertent-PHI redaction layer with a taxonomy of sensitive categories (conditions, medications, account numbers, dates of birth, addresses, SSNs, payer IDs, family names) with per-category redact-or-redirect policy. Patient-rights workflows (access requests for conversation history, deletion requests that propagate as deletion-markers within regulatory-retention windows) integrate with the institution's existing rights-handling infrastructure. The conversation-log-for-analytics boundary is separate from the conversation-log-for-audit boundary, with de-identification before the analytics layer ingests content. The privacy officer plus patient-experience team are canonical owners of this governance surface.

**Crisis detection runs in parallel with intent classification.** A patient asking about parking might also mention chest pain. The detection cannot wait until intent classification routes the conversation; it has to run on every utterance, immediately. The detection vocabulary is owned by the clinical-quality team.

**Scope filtering is layered.** System-prompt design is the first line. Vendor-managed guardrails are the second. Offline scope-drift sampling is the third. Each catches things the others miss, and underweighting any layer leaves a gap.

**Handoff is explicit and warm.** When the bot cannot or should not handle a question, the handoff is concrete. Not "let me get someone for you" with no follow-through, but "I'll connect you with our scheduling team. They're available 8 AM to 5 PM Monday through Friday at 555-1234, or you can leave a callback request and someone will call you back within one business day." The handoff target depends on the question category.

**Per-channel authentication and encryption posture varies.** The FAQ bot may serve multiple channels (web chat widget, in-app chat, SMS, secure-messaging gateway, third-party messenger), each with distinct security characteristics. Per-channel data-in-transit posture (TLS minimum, session-token discipline, identity-correlation key) differs. Per-channel business associate agreement (BAA) scope differs: web chat and in-app and secure-messaging are typically covered under the institutional BAA; SMS requires an aggregator BAA; third-party messengers vary and require explicit per-channel BAA verification before launch. SMS channels carry TCPA and 10DLC compliance obligations. Per-channel session-token TTL and isolation policy must be defined (cross-referencing the session-token discipline above). The audit record carries the per-channel authentication context so compliance queries can scope by channel.

**Multilingual operation is a launch consideration.** Most U.S. healthcare patient populations include meaningful non-English-speaking groups. The bot's per-language assets (knowledge-base content, persona, scope rules, crisis vocabulary) need native-speaker review, not machine translation. The multi-language asset-development pattern is architectural, not incremental: per-language knowledge-base content authored or back-translated by native speakers; per-language persona reviewed by patient-experience native-speaker; per-language scope rules with per-language category definitions; per-language crisis-detection vocabulary with native-speaker clinical-quality review; per-language redaction taxonomy; per-language consent disclosure assets; per-language asset-versioning; per-language launch-gate tied to the per-cohort monitoring framework. Build for day one even when shipping with a small number of languages first; the architecture supports per-language deployment from the start.

**Per-cohort monitoring is non-negotiable.** Aggregate metrics hide failures that subgroup metrics surface. The bot's performance across language, channel, region, category, and content-type axes is monitored from day one. Single-axis cohorts (per-language, per-channel, per-region, per-category) are the minimum; two-axis combinations (per-language-by-channel, per-language-by-category) surface equity-acute disparities. Per-cohort minimum sample sizes prevent noise from masquerading as signal. Per-cohort threshold metrics (containment rate, retrieval quality, scope-violation rate, crisis-detection rate, handoff rate, patient-feedback distribution) are launch gates, not post-launch dashboards. Institution-wide averages are informational only; launch is gated on every cohort meeting its threshold. Disparity alerts trigger reviews. Sustained disparity triggers remediation tracking owned by patient-experience and clinical-quality leadership with quarterly review cadence.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter11.01-architecture). The Python example is linked from there.

## Related Recipes

- **Recipe 11.2 (Appointment Scheduling Bot):** Same chapter, the next step up in complexity. The FAQ bot answers questions about scheduling; the scheduling bot actually books, reschedules, and cancels appointments through fulfillment integration with the scheduling system. The FAQ bot's operational practices (corpus curation, prompt versioning, scope discipline, crisis detection, conversation logging) are foundational for the scheduling bot.
- **Recipe 11.3 (Prescription Refill Request Bot):** Same chapter, the transactional analog for medication refills. The FAQ bot can answer questions about refills (how to request, what the policy is) but cannot submit a refill; recipe 11.3 covers that fulfillment. The FAQ bot is the natural front door that hands off to the refill bot when the patient asks for a refill.
- **Recipe 11.5 (Insurance Benefits Navigator):** Same chapter, the patient-eligibility-aware analog. The FAQ bot can answer "do you take Aetna?" from a static accepted-plans list; recipe 11.5 covers patient-specific benefits questions that require eligibility lookup.
- **Recipe 11.6 (Symptom Checker / Triage Bot):** Same chapter, the regulated clinical analog. The FAQ bot explicitly refuses clinical questions and routes to nurse triage; recipe 11.6 is what the institution might build for that nurse-triage-routing function (with the regulatory and clinical-validation work that implies).
- **Recipe 11.8 (Mental Health Support Bot):** Same chapter, the sensitive-domain analog. The FAQ bot's crisis detection routes to crisis resources; recipe 11.8 is what the institution might build for ongoing mental-health support beyond crisis routing.
- **Recipe 10.5 (Patient-Facing Voice Assistant):** Chapter 10, the voice analog of the FAQ bot's patterns plus transactional fulfillment. The FAQ bot's RAG-and-scope patterns generalize directly into the voice assistant's informational-question handling.
- **Recipe 10.1 (IVR Call Routing Enhancement):** Chapter 10, the routing-level analog. Some institutions deploy the IVR routing as the front door to the call channel and the FAQ bot as the front door to the chat channel, with both routing to the same human queues.
- **Recipe 2.7 (Literature Search and Evidence Synthesis):** Chapter 2, the clinician-facing RAG analog. The retrieval, generation, and citation discipline patterns are similar; the corpus and the scope are different.
- **Recipe 2.1 (Patient Message Response Drafting):** Chapter 2, the asynchronous LLM-drafted patient communication analog. The scope-containment patterns map closely between the FAQ bot's interactive chat and the message-drafting use case.
- **Recipe 4.2 (Patient Education Content Matching):** Chapter 4, the content-recommendation analog. The institutional content the FAQ bot retrieves and the patient-education content from recipe 4.2 sometimes overlap; the institutions that integrate them avoid maintaining two separate content corpora.

---

## Tags

`conversational-ai` · `embeddings` · `rag` · `intent-classification` · `learning-to-rank` · `prompt-versioning` · `crisis-detection` · `patient-engagement` · `multilingual` · `accessibility` · `audit-trail` · `equity-monitoring` · `phi-handling` · `hipaa` · `bedrock-guardrails` · `prompt-injection-defense` · `scope-containment` · `persona-design` · `api-gateway` · `athena` · `bedrock` · `bedrock-knowledge-bases` · `cloudtrail` · `cloudwatch` · `connect` · `dynamodb` · `eventbridge` · `glue` · `kinesis-firehose` · `kms` · `lambda` · `lex` · `opensearch` · `s3` · `secrets-manager` · `waf`
