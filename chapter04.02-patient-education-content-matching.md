# Recipe 4.2: Patient Education Content Matching ⭐

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.001-0.01 per recommendation (depends on LLM use)

---

## The Problem

A primary care patient walks out of a 15-minute visit with a brand-new diagnosis of type 2 diabetes. The clinician spent maybe four minutes of that visit explaining the condition. Half of those four minutes were eaten up by managing the patient's anxiety, which is appropriate, but doesn't leave much room for the actual teaching. As the patient is leaving, the MA hands them a folder. Inside the folder: a generic brochure about diabetes from 2014, a printout from the patient portal that's seven pages of dense clinical text, and a one-pager about the hospital's diabetes class that meets on Tuesdays at 10 AM (the patient works Tuesdays at 10 AM).

The patient gets to their car. They look at the folder. They put it on the passenger seat. They drive home. Two weeks later they have follow-up labs and the front-desk staff find the folder, untouched, in the patient's bag. The patient has not started any lifestyle changes. They have not started the medication, because they're confused about whether they're supposed to take it with food. They cannot articulate what an A1c is. They are exactly as informed about their own disease as they were two weeks ago, except now they are also frustrated with themselves and slightly afraid of the doctor.

Every step of this story is the system working as designed. The clinician did their job. The MA did their job. The folder was assembled by a content team that produced reasonable, evidence-based material. The patient portal had education content available. The diabetes class exists.

The patient still ended up unprepared.

The thing that makes this maddening is the inventory mismatch. A typical health system has thousands of education assets sitting in their CMS or content library. Brochures, videos, interactive modules, post-visit instructions, condition-specific deep dives, peer-reviewed handouts in multiple languages. There is, in practically every case, *something* in that library that would have worked for this patient. There's content written at a sixth-grade reading level. There's content in Spanish. There are videos for patients who don't read well. There's a "newly diagnosed type 2 diabetes" starter pack. The system owns it. The system paid licensing fees for it. The system is currently not delivering it.

The reason it's not getting delivered is that nobody can match content to patient on the fly. The clinician doesn't have time. The MA isn't trained to. The portal does have a search function but the patient doesn't know what to search for and would not enjoy the experience of typing "type 2 diabetes" into a search box and getting 47 results sorted alphabetically. So a folder of generic content gets handed out, because it's the only repeatable workflow that scales.

What this looks like at scale: a 200,000-patient health system probably has between 500 and 5,000 individual education assets. They get clicked on a few thousand times per month. The same five or ten "popular" pieces get over-recommended, while a long tail of more targeted content gathers dust. Patient portal analytics will show you that 80% of education traffic is hitting maybe 10% of the content, and the other 90% is essentially dark inventory. Worse, the satisfaction signal is anemic: patients rarely rate content, rarely return for more, and the readers who would have benefited most from a specific piece often never see it.

So the problem statement is again deceptively simple: given a patient with some clinical context (diagnoses, procedures, medications, recent labs), some demographic context (age, primary language, reading level estimate, location), and some preference context (do they prefer videos? text? have they engaged with previous content?), pick the right small set of education assets to surface to them, at the right moment, in the right place. Not the same generic folder. The right materials.

This is a recommendation problem. It's a reasonably contained one, because the catalog is finite and curated. There's no risk of the recommender hallucinating a piece of content that doesn't exist; everything in the catalog has been clinically reviewed. The space of "harm" is narrow: the worst the recommender can typically do is suggest something that's irrelevant or boring, which is not great but is also not the failure mode that gets you in front of a regulator. That makes this a beautiful first recommender to build. You learn the entire pattern (feature engineering, candidate generation, ranking, feedback loops, monitoring) on a use case where the stakes are low enough that you can iterate, but high enough that the win is real. The win, by the way, is patients who understand their conditions, take their medications, and show up for their follow-ups. That's not a small win.

Let's get into how you actually build it.

---

## The Technology: Recommending from a Curated Catalog

### What Kind of Recommender Problem Is This, Really?

Recommendation problems come in flavors, and the flavor matters because it determines what techniques work. The big distinctions:

- **Catalog size.** Netflix has tens of thousands of titles. Amazon has hundreds of millions of products. A patient education library typically has hundreds to a few thousand assets. Small catalog. Massively important.
- **Cold-start severity.** Patients are new to the system constantly, and patient interaction histories are sparse compared to a streaming service. Most patients have engaged with zero or one prior pieces of content. Cold-start dominates the average case.
- **Item turnover.** Education content changes slowly. A piece on type 2 diabetes basics might get a refresh every 18 months. Compare to social media where the catalog changes by the hour.
- **Signal density.** "Did the patient read it?" is a much weaker signal than "did the patient buy it." Most patients don't rate or review education content. Many don't even click through to it. The implicit signal you have is page-view depth, time-on-page, and downstream behavior changes (did they show up for follow-up? did adherence improve?). All noisy.
- **Curated vs. open catalog.** The catalog is curated by clinical content teams. Every item has been reviewed. There are no fake reviews, no SEO gaming, no spam. This is rare and lovely.

Put those properties together and you get a use case where the cool, fancy techniques (deep two-tower neural recommenders, transformer-based sequence models) are dramatically overkill. The right approach is a small toolbox of well-understood techniques layered on top of each other, with the layering itself doing most of the work.

### The Three Layers

Most production patient education recommenders, regardless of vendor or technology stack, end up looking like a three-layer stack:

**Layer 1: Rule-based eligibility filters.** Hard "shall not" rules. If the patient's primary language is Spanish, never show English-only content. If the content is rated for ages 18+ and the patient is 14, don't show it. If a piece of content has been flagged as deprecated by the clinical content team, don't show it. These are not optimization decisions; they are correctness decisions, and they belong at the top of the stack so the model never has to reason about them.

**Layer 2: Content-based matching.** Given the patient's clinical context (diagnoses from the problem list, recent procedures, current medications, reading-level estimate, language preference), find content whose tags, topics, and reading metadata align. This is where the bulk of the recommendation logic lives, and the technique that does most of the work is honestly older than the smartphone: **content-based filtering**.

Content-based filtering, in plain English: every item in the catalog has a feature vector (what topics does it cover, what reading level, what format, what language, what age range). Every patient has a feature vector (what conditions, what reading level, what language, what preference history). Find the items whose feature vector best aligns with the patient's. The simplest way to do this is to use a small, hand-curated taxonomy (think SNOMED-CT codes mapped to content topics) and a similarity function (Jaccard, cosine, or just a weighted sum of matched fields). It works. It works boringly well.

The fancier version of content-based filtering uses **embeddings**. Take each piece of content, run its title and abstract through a sentence-embedding model, and store the resulting vector. Take the patient's clinical context, build a query string from it, embed that, and do a vector similarity search to find nearest content. This is "semantic search," and it's how most production search systems do similarity-by-meaning today. The advantage over a tag-based approach: you can find content that's topically related but doesn't share exact tags. ("Newly diagnosed diabetes" and "starting metformin" are semantically close even if no tag overlap.) The disadvantage: you've now introduced a black box, and you need to do a chunk of evaluation to make sure the embeddings are actually capturing the right kind of similarity for your use case.

**Layer 3: Personalization re-ranking.** Once content-based matching has produced a candidate set of (say) 20 to 50 plausibly relevant items, a re-ranker reorders them based on personalized signals: prior engagement (this patient watched videos, not articles), recent activity (they were just looking at content about A1c, surface related content), and predicted engagement (a small ML model that scores "will this patient actually open this item"). This is where you graduate from generic matching to actual personalization.

The re-ranker can be as simple as a feature-weighted scoring function or as fancy as a learning-to-rank model (LambdaMART, XGBoost-Ranker). For a starter implementation, weighted scoring works fine. Move to LambdaMART when you have meaningful click-through data and want to optimize a ranked-list metric like NDCG explicitly.

### Why Not Just Use an LLM for Everything?

It's a fair question in 2026. Why not skip all this scaffolding and just feed the patient context plus the catalog into a frontier LLM and ask it to pick the best three items?

You can. People do. It works in demos. Here's where it falls apart in production:

- **Cost.** Every recommendation invokes a frontier model, which means every reminder email, every portal page load, every new-patient onboarding triggers a multi-thousand-token LLM call. Costs grow linearly with users and pages, and they grow fast. Content-based filtering with embeddings does the heavy lifting in vector indexes that cost essentially nothing per query.
- **Latency.** A vector similarity search returns in tens of milliseconds. An LLM call returns in seconds. For a portal page that wants to show recommended content above the fold, the LLM is too slow.
- **Auditability.** "The model picked these three items" is hard to explain when the model is a 70-billion-parameter LLM. "The patient has a recent diabetes diagnosis, so we filtered to diabetes-tagged content, then ranked by reading-level match, and these three came out on top" is auditable. In healthcare, auditability is not a nice-to-have.
- **Determinism and testing.** A rule-and-vector pipeline produces the same results for the same inputs. An LLM at temperature > 0 doesn't. Regression-testing a content recommender requires a deterministic core.

What LLMs are great for in this pipeline is **content tailoring**, not content selection. The recommender picks the items. The LLM, optionally, generates a short personalized blurb introducing the items to the patient ("Based on your recent visit, here are three things that might help"), or rewrites the content snippet shown alongside the link. That's a much smaller, safer use of the LLM, and it composes cleanly with the deterministic recommendation core.

### Reading Level Is the Sleeper Feature

If you take one thing away from this section, take this: in patient education, reading level is the feature that matters most and gets the least attention. Average US adult reading level is around eighth grade. Average healthcare patient population skews lower because health-literacy challenges correlate with the conditions that bring people to healthcare in the first place. A patient handed a piece of content written at a college-graduate level (which is most clinical content, by default) is functionally not getting any education from it. They're not going to call you and tell you that. They're going to nod, take it home, and put it on the passenger seat.

Reading-level estimation has a few off-the-shelf algorithms (Flesch-Kincaid, SMOG, Dale-Chall) that give you a grade-level number. They're imperfect (they don't capture concept density, only sentence and word complexity), but they're better than nothing and they're computable from the text alone. Tag every piece of content with its reading level when it enters the catalog, and treat reading level as a hard or soft constraint when matching. A "fits patient's reading level" filter will dramatically outperform a generic semantic search every time, because relevance without comprehension is not relevance.

Patient reading level is harder to measure directly. Proxies that correlate: educational attainment from registration data, prior content engagement (which reading levels did they actually finish?), explicit health-literacy screening tools (REALM, TOFHLA) if your organization administers them. In the absence of any signal, default to a sixth-to-eighth-grade level rather than higher. You can always step up if engagement signals say you can; stepping down after pushing too-hard content is harder.

### Multilingual Is Not Optional

The same logic applies to language. Spanish-preference patients receiving English-only content are not being served. Many health systems have pockets of patients with primary languages well beyond the top two: Vietnamese, Tagalog, Somali, Russian, Mandarin, Arabic. Whether you have native-language content for each of those is a content-team decision (and a budget decision); whether your recommender respects language preference at all is a fundamental correctness decision.

Language preference goes in the eligibility filter (Layer 1). Don't try to be clever about it. If a patient's preference is Spanish and an item is English-only, drop it from candidates. If you don't have Spanish content for a topic, that's a content gap to flag back to the content team, not a feature for the model to optimize around.

### The Feedback Loop, Lighter Than 4.1

Recipe 4.1 had a complex feedback loop because the reward signal (did the patient show up?) was high-stakes and well-defined. For patient education, the feedback signal is softer: did they click? did they finish? did they come back? The model can use any of these, but you need to be honest about what each tells you:

- **Impressions** (was the item recommended) tell you about the recommender's behavior, not the patient's.
- **Clicks** tell you the recommendation looked relevant. They don't tell you the content delivered value.
- **Read-completion** (scrolled to the end, watched > 80% of the video) tells you something. Not perfect, but a real signal.
- **Return engagement** (the patient came back to read more, or rated the content positively) is the strongest weak signal you can capture from a portal interaction.
- **Downstream clinical behavior** (took the medication, showed up for the follow-up, lab values moved in the right direction) is the real outcome, and it's typically too far away in time to feed the recommender model directly. It's the signal you use for periodic offline evaluation, not for online learning.

The lighter weight of these signals (compared to "did they show up for the appointment") means the feedback loop here can be simpler. You don't need a contextual bandit; you need a click-through rate (CTR) tracker, a periodic re-ranker training job, and a slice-by-cohort dashboard. Worth its own paragraph: don't optimize for CTR alone. CTR optimization without read-completion as a counterweight will steer your recommender toward clickbait headlines and away from substantive content. Track both, and weight the loss toward read-completion when you train the re-ranker.

### Where This Fits in the Bigger Picture

Recipe 4.1 (channel optimization) decided how to reach the patient. Recipe 4.2 decides what content to put in front of them when you do. The two recipes are natural collaborators: a reminder email or portal nudge is the channel; the recommended education content is the payload. The patient preference store, engagement event pipeline, and cohort monitoring infrastructure you built for 4.1 are reusable here with minimal extension. If you've already shipped 4.1, you're more than halfway to 4.2.

Looking forward: Recipes 4.4 (Wellness Program Recommendations) and 4.5 (Medication Adherence Intervention Targeting) build on the same recommender infrastructure. The catalog changes (programs, interventions instead of education assets) but the architecture is recognizable. Treat 4.2 as the second round of capability-building.

---

## General Architecture Pattern

The pipeline has three logical components: a content ingestion path that prepares the catalog, an inference path that handles real-time recommendation requests, and a feedback path that captures engagement and refreshes the personalization model.

```text
┌─────────────── CONTENT INGESTION (offline) ───────────────┐
│                                                            │
│  [Education Content CMS]                                   │
│           │                                                │
│           ▼                                                │
│  [Extract: title, body, language, reading level,           │
│   topic tags, content type, target audience]               │
│           │                                                │
│           ▼                                                │
│  [Compute: embedding(title + abstract),                    │
│   reading-grade-level score]                               │
│           │                                                │
│           ▼                                                │
│  [Index: vector store (embedding) +                        │
│   metadata store (tags, level, language)]                  │
│                                                            │
└────────────────────────────────────────────────────────────┘

┌──────────── INFERENCE PATH (real-time) ───────────────────┐
│                                                            │
│  [Trigger: portal page load,                               │
│   email assembly, post-visit summary]                      │
│           │                                                │
│           ▼                                                │
│  [Build patient context query:                             │
│   conditions, language, reading level,                     │
│   recent interactions]                                     │
│           │                                                │
│           ▼                                                │
│  [Layer 1: hard filters                                    │
│   (language match, age-appropriate,                        │
│    not-deprecated, consent)]                               │
│           │                                                │
│           ▼                                                │
│  [Layer 2: candidate generation                            │
│   (semantic search + tag overlap                           │
│    → top 30-50 candidates)]                                │
│           │                                                │
│           ▼                                                │
│  [Layer 3: re-rank by personalization                      │
│   (engagement priors, format preference,                   │
│    reading-level fit, recency)]                            │
│           │                                                │
│           ▼                                                │
│  [Return top N (typically 3-5) with                        │
│   explanation features for UI]                             │
│           │                                                │
└───────────┼────────────────────────────────────────────────┘
            │
            ▼
     [Patient Sees Recommendations / Clicks / Reads]
            │
┌───────────┼────────────────────────────────────────────────┐
│           ▼                                                │
│  [Engagement events: impression, click,                    │
│   read-completion, rating]                                 │
│           │                                                │
│           ▼                                                │
│  [Join to recommendation request,                          │
│   compute CTR + completion rate]                           │
│           │                                                │
│           ▼                                                │
│  [Update patient engagement features +                     │
│   re-ranker training data]                                 │
│           │                                                │
│           ▼                                                │
│  [Periodic re-ranker retrain                               │
│   (weekly / monthly)]                                      │
│           │                                                │
│           ▼                                                │
│  [Cohort dashboard: coverage, CTR,                         │
│   completion rate, by language and                         │
│   reading-level cohorts]                                   │
│                                                            │
└──────────────────── FEEDBACK PATH ─────────────────────────┘
```

**Content ingestion is offline and slow.** When a piece of content is added or updated in the CMS, a pipeline picks it up, extracts text, computes the embedding, computes the reading-level score, and indexes it. This runs once per content change, not once per recommendation request. The inference path reads from the index and never has to do this work in real time.

**Inference path is fast and cheap.** A single recommendation request hits a small set of services: a metadata lookup for the patient's clinical context, a hard-filter pass against catalog metadata, a vector similarity search against the content embedding index, a re-ranking step that consumes some patient features, and a return. Total latency target: under 200 milliseconds for a portal page integration. Achievable with off-the-shelf vector indexes and a feature store.

**Feedback path runs continuously but updates the model on a slower cadence.** Engagement events stream into an event bus, get joined to the originating recommendation request, and accumulate into a training dataset. The re-ranker model retrains on a weekly or monthly schedule, not in real time. The patient-level engagement features that the re-ranker consumes can be updated more frequently (a daily aggregation is fine for most use cases).

**The candidate set is small enough to be transparent.** Returning 30-50 candidates after filtering means the re-ranker is not the differentiator between "good" and "bad" recommendations; the candidate generator is. Most of your engineering attention should go to making the candidate generator produce a relevant set, because the re-ranker can only choose among what the candidate generator surfaced. A dazzling re-ranker on top of a clueless candidate generator is still a clueless recommender.

**Explanation features come along for the ride.** Have the recommender return the features that led to each selection along with the top N items themselves: matched tags, semantic similarity score, reading-level fit, prior engagement boost. The UI uses these to render natural-language explanations ("recommended because you have a recent diabetes diagnosis and prefer videos") and the audit log uses them to answer the inevitable "why was this recommended" question from a clinician or a compliance reviewer.

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter04.02-architecture). The Python example is linked from there.

## The Honest Take

Patient education recommendation is one of the highest-ROI personalization use cases in healthcare, and it's also one of the most under-implemented. The reason it's under-implemented is not because the technology is hard; the technology has been mature for over a decade. It's under-implemented because content-ops investment is required for it to work, and content-ops is generally underfunded.

A recommender on a catalog that doesn't have language metadata, reading-level metadata, or up-to-date topic tags is going to be mediocre regardless of how clever the model is. A recommender on a well-curated catalog with thoughtful tagging will outperform sophisticated models running on poorly tagged catalogs. The lesson, learned the hard way: spend the first quarter on content metadata quality, then build the recommender. Teams who flip the order ship a recommender that's technically correct and operationally useless.

The other thing that surprises people: the LLM is rarely the answer. Frontier LLMs are seductive ("just have it pick the best item from the list, it can read the whole catalog"), and they work in demos. They fall down in production because they're slow, expensive, and not auditable. The deterministic vector + metadata + re-ranker pipeline is the right architectural shape, and the LLM, if you use one, belongs in the content-tailoring step (writing a friendly introduction to the recommended items, summarizing a piece of content into a portal-friendly snippet) rather than the selection step.

The thing I'd do differently: invest in explicit preference capture earlier. The recipe's re-ranker learns format preferences from clicks, but a single onboarding question ("do you prefer to learn from videos, articles, or both?") gets you to that signal in one step instead of fifty. Implicit signals are valuable, but they're slow and noisy. Explicit signals are fast and clear. Most patients are happy to tell you what they prefer if you ask once, politely, and then respect the answer.

And the trap worth flagging: confusing recommendation quality with engagement metrics. A recommender that drives more clicks is not necessarily a better recommender. A recommender that drives more *meaningful* engagement (read-completion, return visits, reported satisfaction, downstream behavior change) is the one that's actually serving patients. Optimizing for raw CTR will produce a recommender that surfaces clickbait headlines and content that's exciting in the moment but not genuinely useful. Always pair CTR with completion-rate or a stronger downstream signal in your model objective. The metric you optimize is the metric the system will deliver.

One last point, because it's specific to this use case: be careful with the framing in the UI. "We recommend you read X" lands very differently from "based on your recent visit, this might be helpful." The first sounds like an instruction; the second sounds like a friend who knows you. Patients pick up on the difference, and trust in the system is fragile. The technology is the same. The framing is what makes patients feel like the system is helping them rather than nudging them.

---

## Related Recipes

- **Recipe 4.1 (Appointment Reminder Channel Optimization):** Provides the patient preference store and engagement event pipeline this recipe consumes; the two recipes share infrastructure and naturally compose.
- **Recipe 4.4 (Wellness Program Recommendations):** Same recommender architecture applied to a different catalog (wellness programs instead of education content). The infrastructure built here is mostly reusable.
- **Recipe 2.2 (Medical Terminology Simplification):** A complementary capability for content tailoring; can be used to dynamically simplify content snippets for low-health-literacy patients without modifying the underlying catalog.
- **Recipe 2.5 (After-Visit Summary Generation):** A common consumer of this recommender; the AVS generator calls in to attach 2-3 recommended education items based on the visit's clinical context.
- **Recipe 11.x (Conversational AI / Virtual Assistants):** Patient-facing assistants can call this recommender mid-conversation to surface educational material when the patient asks a question.

---

## Tags

`personalization` · `recommendation` · `content-based-filtering` · `semantic-search` · `vector-search` · `learning-to-rank` · `patient-education` · `health-literacy` · `bedrock` · `opensearch` · `dynamodb` · `sagemaker` · `lambda` · `simple` · `mvp` · `hipaa`

---

*← [Recipe 4.1: Appointment Reminder Channel Optimization](chapter04.01-appointment-reminder-channel-optimization) · [Chapter 4 Preface](chapter04-preface) · [Next: Recipe 4.3 - Provider Directory Search Optimization →](chapter04.03-provider-directory-search-optimization)*
