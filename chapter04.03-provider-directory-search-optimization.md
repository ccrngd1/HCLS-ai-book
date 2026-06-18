# Recipe 4.3: Provider Directory Search Optimization ⭐

**Complexity:** Simple-Medium · **Phase:** MVP+ · **Estimated Cost:** ~$0.001-0.005 per ranked search response (depends on personalization depth)

---

## The Problem

A new patient lands on a health plan's "Find a Doctor" page on a Tuesday evening. They have a primary care benefit, a deductible they've already half-burned through, a kid with an ear infection, and twenty minutes before bedtime to figure out who to call in the morning. They type "pediatrician" and a ZIP code into the search box. The page returns 247 results.

The first result is a pediatrician 18 miles away who isn't accepting new patients. The second is a pediatrician 6 miles away who hasn't updated their availability in two years and may or may not still practice at that address. The third is a doctor whose specialty was misclassified in the directory ingest five years ago and who is, in fact, an adult internist who occasionally sees teenagers. The fourth is the patient's existing pediatrician, the one they've been seeing since their kid was born, ranked fourth because the directory's only sort option is "closest first" and there are three offices physically closer to the patient's house.

The patient scrolls. They get to result twelve before finding someone who's actually plausibly accepting new patients, in their network, with a phone number that hasn't been disconnected. They write the name down. The kid sleeps. In the morning, they call. The receptionist says: "I'm so sorry, that doctor left the practice in October." The patient googles instead, finds a clinic, takes the kid to urgent care, pays out-of-pocket for an out-of-network visit, and updates their mental model of the health plan's directory to "broken, don't trust."

This is not a hypothetical. Provider directories are notoriously, hilariously, regulator-attentively bad. CMS audits have repeatedly found that thirty to fifty percent of entries in Medicare Advantage directories are inaccurate in some material way: wrong phone number, wrong address, wrong specialty, wrong network status, accepting-new-patients flag completely fictional. The penalties have been real and ongoing. The No Surprises Act now requires plans to verify directory entries quarterly and gives patients legal recourse when they're sent to a "ghost" provider. 

But even when the data is *correct*, the search experience is bad. Provider directories were originally built as compliance artifacts: a thing the plan had to publish, not a thing patients were expected to actually use to make decisions. They sort by distance because that's the easy attribute to compute. They don't know whether you've seen this provider before. They don't know that the cardiologist you saw two years ago is in the system. They don't know that you prefer female providers, or that you need a Spanish-speaking PCP, or that you're newly insured and need someone accepting new patients, or that the "primary care" you actually need is a nurse practitioner who can see you tomorrow rather than the MD who can see you in six weeks. The directory has the data for some of these. It just doesn't use it.

What this looks like at scale: a regional health plan with 400,000 members and 12,000 contracted providers will see hundreds of thousands of directory searches per month. A meaningful fraction of those searches end with a click-out (the patient picks a provider) but a meaningful fraction also end in abandonment, frustration calls to member services, or the patient just going to whoever Google says is closest. Each abandonment is a failed match between someone who needs care and someone who could have provided it.

So the problem statement, again, is deceptively simple: given a search query, a patient with rich context (insurance plan, geography, language, demographics, claims history, stated preferences, prior providers, current care episodes), and a directory of providers, return a ranked list that's actually useful. Not "closest first." Not alphabetical. Not whatever order the database happened to return. Useful. The right small set of providers, in the right order, with the right metadata to support a confident click.

The wrinkle that makes this distinct from Recipes 4.1 and 4.2: this recipe touches access equity. How you rank providers shapes which providers get patients. Which providers get patients shapes their patient panels, their revenue, their continued participation in the network, and their willingness to accept patients with different insurance products. A ranking algorithm that systematically buries safety-net providers, or that channels patients toward a small set of high-volume practices regardless of fit, can have material downstream effects on access for the populations that need it most. So we're going to spend more time than usual on the fairness considerations, because the failure modes here are not "the patient was annoyed" but "a community lost access to providers it depended on."

Let's get into how you build it.

---

## The Technology: Search Plus Ranking, with a Compliance Spine

### What Kind of Problem Is This, Really?

Provider directory search looks like a search problem on the surface, and it is, but it's a search problem with three properties that change the architecture:

- **The catalog is small but high-stakes.** A regional plan has thousands to tens of thousands of providers, not millions. You don't need fancy distributed search. You do need every result to be defensible.
- **The data is dirty in known ways.** Phone numbers go stale, addresses change, providers leave practices, network status flips. Search quality is bounded above by data quality. You can build a brilliant ranker on bad data and produce a brilliantly ordered list of wrong answers.
- **The ranking is a regulated artifact.** CMS, state Departments of Insurance, and consumer protection statutes care about provider directory accuracy and accessibility. Your ranking choices may need to be explainable to an auditor. "The model said so" is not a sufficient answer.

Put those together and you get an architecture that's part information retrieval, part data engineering, and part compliance plumbing. The fancy ML lives in the ranking step, but most of the value lives in the boring data-quality steps that come before it.

### The Logical Stages

Most production provider directory search pipelines, regardless of vendor, end up looking like this:

**Stage 1: Query understanding.** The patient typed "pediatrician" or "knee doctor" or "Dr. Smith Spanish." The first job is to figure out what they meant. Specialty taxonomy mapping ("knee doctor" → orthopedics, with a sub-interest in knee), intent classification (looking for a specific provider vs. a category), filter extraction (language, gender, accepting-new-patients flags expressed in natural language). This used to be a hand-written rules engine; today it's frequently a small LLM call with structured-output guardrails, or a fine-tuned classifier on top of an embedding.

**Stage 2: Eligibility filtering.** Hard "shall not show" rules. The provider is out of network for this patient's plan. The provider is not credentialed for the patient's age (a pediatrician can't see a 50-year-old). The provider's accepting-new-patients flag is false and the patient is new. The provider's record is flagged as under review by the data quality team. These rules are not optimization decisions; they are correctness decisions, and they belong at the top of the stack so the ranker never has to reason about them.

**Stage 3: Candidate retrieval.** Pull the providers who match the query and pass eligibility. This is classic information retrieval: keyword match on names and specialties, filter match on attributes (location radius, languages, gender), and increasingly a vector match for semantic similarity (so "diabetes doctor" can find an endocrinologist whose profile mentions diabetes management even if the specialty taxonomy didn't catch it). Returns a candidate set of typically 50 to 500 providers.

**Stage 4: Feature joining.** For each candidate, attach the features the ranker needs: distance from the patient, network tier within the plan, claims-derived patient overlap (does this patient have prior visits with this provider?), provider quality scores (HEDIS performance, patient satisfaction if available), availability metrics (next-available appointment, panel openness), specialty-fit score from the query understanding stage, fairness controls.

**Stage 5: Ranking.** Score and order the candidates using a learning-to-rank model (LambdaMART, XGBoost-Ranker, neural ranker). The features include both query-document features (does this provider's specialty match the query?) and personalization features (have you seen this provider before? do they speak your language?) and contextual features (is the appointment urgent? are you a new member?).

**Stage 6: Re-ranking for diversity and fairness.** The raw ranker output may concentrate clicks on a handful of providers, may underexpose newer or less-popular providers regardless of fit, and may produce subtle disparities by patient cohort. A re-rank pass enforces explicit constraints: maximum exposure for any single provider in a given window, fair exposure across providers of similar fit, configurable boosts for specific networks or programs the plan wants to highlight (in-house clinics, Medicaid managed care providers, community health centers).

**Stage 7: Result assembly.** Render the ordered list with the metadata patients need to make a decision: name, specialty, address, distance, languages, accepting-new-patients flag, next-available appointment if known, network tier, "you've seen this provider before" badge if applicable. Each result includes an explanation cue ("matches your stated preference for Spanish-speaking providers; in your plan's preferred network").

### Why This Looks Different from Recipe 4.2

Recipe 4.2 was content-based filtering on a curated catalog. Recipe 4.3 is information retrieval on a noisy catalog with regulatory implications. Three differences worth pinning down:

- **Catalog quality is half the problem.** The 4.2 content catalog was curated by clinical content teams who verified everything. The 4.3 directory is sourced from claims feeds, credentialing systems, provider self-attestation forms, and network management spreadsheets that have been merged and re-merged. Data validation, duplicate detection, and stale-record decay are first-class concerns.
- **The ranking is multi-objective in a deeper way.** 4.2's recommender optimized for "did the patient engage." 4.3's ranker juggles patient fit, network economics, provider availability, and access equity simultaneously. The objective function is a committee, not a single number.
- **Audit and explainability are non-negotiable.** When a regulator asks why a particular provider was ranked third for a particular patient, you need a defensible answer that doesn't depend on a 70-billion-parameter LLM having an opinion.

### Learning to Rank, Briefly

The phrase "learning to rank" (LTR) shows up a lot in this recipe, so a quick primer. Classic search returns documents in some order based on a relevance score (BM25, TF-IDF, vector cosine similarity). LTR replaces that single score with a model that consumes many features per (query, document) pair and outputs a relevance score that's been trained on actual ranking outcomes.

Three flavors of LTR, in increasing sophistication:

**Pointwise.** Treat ranking as regression: predict the absolute relevance of each (query, document) pair, then sort. Easy to train, but ignores the fact that ranking is fundamentally about pairwise comparisons (is A more relevant than B?), not absolute scores.

**Pairwise.** Train on pairs of documents: for query Q, was document A more or less relevant than document B? RankSVM and RankNet are classic examples. The model learns to order pairs correctly, which is closer to what users actually experience.

**Listwise.** Train on entire ranked lists: optimize a list-quality metric directly (NDCG, MAP, MRR). LambdaMART is the workhorse here, and it's what most production search and recommendation systems use. The objective function explicitly cares about getting the top of the list right.

For a starter implementation, listwise LambdaMART with a handful of well-engineered features is the right answer. It's well-studied, well-supported in libraries (XGBoost has built-in `rank:pairwise` and `rank:ndcg` objectives, LightGBM has `lambdarank`), and has the audit-friendly property that tree-based models give you feature contributions per ranking decision out of the box (SHAP values).

You don't need a transformer. You don't need a two-tower neural network. You need clean data, well-chosen features, a labeled dataset of rank-quality judgments (real or synthetic, more on this below), and a tree-based ranker. The fancy stuff is real, but it's almost always overkill for a directory of 12,000 providers.

### The Label Problem

The honest hard part of LTR is getting labels. A label is a (query, document, judgment) triple where the judgment encodes how relevant document was for query. For web search, Google has a small army of human raters generating labels and an enormous quantity of click-and-dwell data to derive labels from. For provider directory search, you have:

- **Click data, with severe position bias.** Patients click on top-ranked results regardless of quality, because they're at the top. Naïve "did they click" labels reward whatever the current ranker is already doing. You need inverse-propensity weighting or a click-model-based correction (position-based model, cascade model) to derive honest relevance signals from click data.
- **Sparse explicit feedback.** Patients almost never rate a search result. The "was this useful" prompt is largely ignored. You'll get a few percent feedback rate at best.
- **Downstream signals you can mine.** Did the patient call the provider's office (if you have call-tracking)? Did they end up scheduling an appointment with the provider (if you have visibility into that)? Did they file a complaint about the directory result (negative signal, gold-standard if it exists)?
- **Provider-side correctness signals.** A provider whose phone number bounces, who never accepts an appointment from your plan, or whose practice has been closed for six months is a negative signal that's not about ranking quality but about catalog quality. Use it to demote, but separately from "the patient didn't click on this result."

For a starter implementation, a hybrid approach works: combine de-biased click data with a small set of human-graded query-document pairs (the human grading is expensive but high-quality, used to validate the model rather than dominate training), and supplement with rule-based hard labels (out-of-network = irrelevant, panel closed = irrelevant for a new-patient query) that don't require any inference. This is honest, auditable, and gets you to a working ranker without needing a full-time labeling operation.

### Fairness Is Structural Here

Recipe 4.1 and 4.2 had fairness considerations. This recipe has fairness as a structural concern that affects the architecture itself. A few patterns worth naming:

**Exposure fairness.** Each provider gets some share of impressions in the search results. If the ranker concentrates impressions on a small subset, the rest of the network atrophies. The ranker can be technically optimal on a per-query basis and still produce structurally bad outcomes at the aggregate level. Re-ranking passes that enforce minimum exposure for providers who pass relevance thresholds are common, sometimes called "fair re-ranking" or "amortized fairness."

**Quality-of-care fairness.** Different patient cohorts may experience systematically different ranking quality if the model has been trained primarily on data from majority cohorts. NDCG-by-cohort dashboards (broken down by language, plan type, geography) catch this. If your "average" NDCG is 0.85 but it's 0.85 for English-speakers and 0.71 for Spanish-speakers, the average is hiding a problem.

**Network-tier fairness.** Health plans often have tiered networks (preferred, standard, out-of-network). Ranking decisions that systematically push certain communities away from preferred-network providers translate into out-of-pocket cost differentials. Treat tier-aware ranking as a policy decision that needs explicit governance, not as a feature you silently add.

**Safety-net fairness.** Federally Qualified Health Centers (FQHCs), community health centers, and Ryan White providers serve specific populations with specific needs. A ranking algorithm that buries them in favor of higher-volume commercial practices can disrupt established patient-provider relationships and access patterns for the most vulnerable patients. Many plans require ranking policies that explicitly preserve visibility for safety-net providers in relevant searches.

The point is not "build a perfect fairness model." The point is that fairness in this domain is a set of policy decisions made jointly by data science, network operations, and compliance, with measurable success criteria and a regular review cadence. The architecture has to support those decisions, not work around them.

### Where LLMs Fit (and Don't)

In 2026, you might reasonably ask: why not just feed the patient context, the directory, and the query into a frontier LLM and have it reason its way to a ranked list?

Same answer as Recipe 4.2, more emphatic:

- **Cost and latency.** A directory search returns in tens of milliseconds. An LLM call returns in seconds. The patient is searching from a phone on a Tuesday night and will give up.
- **Determinism.** Two patients with the same query and the same context need to get the same ranking, in the same order, every time. LLMs at temperature > 0 don't promise that.
- **Auditability.** "Why was Dr. Smith ranked third?" with a tree-based ranker has a clean answer (a SHAP value per feature). With an LLM, you get a post-hoc rationalization that may or may not reflect what actually drove the decision.
- **Regulatory exposure.** A directory ranking that violates provider contracting rules or network adequacy requirements creates legal liability. You need to be able to prove the ranking respects those rules; an LLM cannot prove that of itself.

LLMs are useful here in the **query-understanding** step (Stage 1), where they take fuzzy natural-language inputs and produce structured filters with much less brittleness than regex-based parsers. They are also useful in the **explanation** step (Stage 7), where they take the ranking features and render them as a friendly natural-language reason ("matches your preference for Spanish-speaking providers; in your plan's preferred tier"). They do not pick the providers. The ranker picks the providers. The LLM is a presentation layer.

### Where This Sits in the Chapter

Recipe 4.1 built channel optimization. Recipe 4.2 built content recommendation. Both produced patient-level personalization on small, well-defined item catalogs. Recipe 4.3 graduates to a larger, dirtier catalog with regulatory constraints and explicit fairness considerations. The patient-profile store, engagement event pipeline, and feature store you built in 4.1 and 4.2 are reusable here. What's new is the IR plumbing (the searchable index of providers), the data quality machinery (catalog freshness, ghost-provider detection), and the fairness re-ranker.

Recipes 4.4 (Wellness Programs) and 4.5 (Adherence Interventions) will reuse the patient feature store again, but they're back to recommending from curated catalogs. Recipe 4.7 (Care Management Enrollment) will pull on the fairness patterns we set up here, because it makes resource-allocation decisions that have similar equity exposure. So 4.3 is something of a structural turning point in the chapter: it's where personalization stops being "what should we show this patient" and starts being "how does our system shape access to care, and how do we keep that shaping aligned with what we promised our members and our regulators."

---

## General Architecture Pattern

The pipeline has three logical components: an ingestion path that maintains the searchable provider catalog, a query path that handles real-time search requests, and a feedback path that captures click and downstream signals to refine the ranker and flag data quality issues.

```text
┌──────── PROVIDER CATALOG INGESTION (continuous) ───────────┐
│                                                            │
│  [Credentialing System]   [Claims Feed]   [Provider Self-  │
│            │                    │          Attestation]    │
│            └─────────┬──────────┴───────┬───┘              │
│                      ▼                  ▼                  │
│            [Match + Merge: NPI as primary key,             │
│             tax-id and address fallbacks for dedupe]       │
│                      │                                     │
│                      ▼                                     │
│            [Validate: address geocodable,                  │
│             phone reachable, NPI active in NPPES]          │
│                      │                                     │
│                      ▼                                     │
│            [Annotate: specialty taxonomy normalized,       │
│             languages standardized, tier assigned]         │
│                      │                                     │
│                      ▼                                     │
│            [Embed: provider profile text                   │
│             (specialty + bio + services)                   │
│             → vector for semantic match]                   │
│                      │                                     │
│                      ▼                                     │
│            [Index: keyword (BM25), filters (attributes),   │
│             vectors (k-NN), metadata store]                │
│                      │                                     │
│            [Freshness scoring + ghost-provider detection]  │
│                                                            │
└────────────────────────────────────────────────────────────┘

┌──────────── QUERY PATH (real-time) ────────────────────────┐
│                                                            │
│  [Patient submits search:                                  │
│   query string + filters + location]                       │
│           │                                                │
│           ▼                                                │
│  [Stage 1: query understanding                             │
│   (specialty mapping, intent, filter extraction)]          │
│           │                                                │
│           ▼                                                │
│  [Stage 2: eligibility filters                             │
│   (network match, age-appropriate,                         │
│    accepting new patients, status active)]                 │
│           │                                                │
│           ▼                                                │
│  [Stage 3: candidate retrieval                             │
│   (keyword + filter + vector → top 100-500)]               │
│           │                                                │
│           ▼                                                │
│  [Stage 4: feature joining                                 │
│   (distance, prior visits, quality scores,                 │
│    next-available, panel openness)]                        │
│           │                                                │
│           ▼                                                │
│  [Stage 5: learning-to-rank scoring                        │
│   (LambdaMART / XGBoost-Ranker)]                           │
│           │                                                │
│           ▼                                                │
│  [Stage 6: fairness + diversity re-rank                    │
│   (exposure caps, safety-net floor,                        │
│    near-duplicate suppression)]                            │
│           │                                                │
│           ▼                                                │
│  [Stage 7: result assembly                                 │
│   (metadata + LLM-rendered explanations)]                  │
│           │                                                │
└───────────┼────────────────────────────────────────────────┘
            │
            ▼
     [Patient Sees Results / Clicks / Calls / Books]
            │
┌───────────┼────────────────────────────────────────────────┐
│           ▼                                                │
│  [Engagement events: impression, click, call,              │
│   appointment scheduled, complaint flagged]                │
│           │                                                │
│           ▼                                                │
│  [Join to search request,                                  │
│   apply position-bias correction]                          │
│           │                                                │
│           ▼                                                │
│  [Update LTR training data,                                │
│   provider freshness score,                                │
│   exposure-by-provider running totals]                     │
│           │                                                │
│           ▼                                                │
│  [Periodic LTR retrain                                     │
│   (weekly), data-quality alerts                            │
│   (continuous)]                                            │
│           │                                                │
│           ▼                                                │
│  [Cohort dashboards: NDCG by language,                     │
│   exposure distribution by provider,                       │
│   ghost-provider rate by region]                           │
│                                                            │
└──────────────────── FEEDBACK PATH ─────────────────────────┘
```

**Catalog ingestion is continuous and paranoid.** Provider data arrives from multiple upstream systems on different cadences: credentialing on a multi-week cycle, claims daily, self-attestation on demand, third-party network rosters periodically. Each source has different reliability characteristics. The ingestion pipeline matches and merges them, validates the merged record (geocodable address, reachable phone, active NPI in NPPES), and only then promotes the record into the searchable index. A staging step prevents bad data from reaching patients. A freshness score per record drives how recently each field was verified, and records that haven't been verified in the regulatory window (typically 90 days) get visibility-demoted or pulled until refreshed.

**Query path is fast and explainable.** A search request has a strict latency budget (the "Find a Doctor" page wants results in well under a second). The seven stages each have to be cheap. Query understanding is one LLM call or one classifier inference. Candidate retrieval is a hybrid search query that returns 100 to 500 candidates. Feature joining is parallel lookups against a feature store. Ranking is a tree model. The whole pipeline fits in 500 milliseconds for a typical query. Each result carries the features that drove its ranking, so the audit trail is built in.

**Feedback path is multi-cadence.** Clicks update the training data continuously and flow into the next ranker retrain on a weekly schedule. Appointment-booking signals (when available) are higher-quality positive labels and get higher weight in training. Complaint events ("the directory sent me to a closed practice") are gold-standard negative labels and trigger immediate ghost-provider review for the offending record. Exposure aggregates feed the fairness re-ranker; if a provider has been overexposed in a given window, the re-ranker dampens their score in subsequent searches.

**Eligibility filters are non-negotiable.** Out-of-network providers don't appear in in-network searches. Pediatricians don't appear in adult searches. Closed panels don't appear in new-patient searches. These are correctness boundaries, not optimization features, and they belong at the top of the stack so the ranker doesn't get to overrule them. Edge cases (a patient explicitly searching out-of-network because they want to know cost-share, a patient searching for a specialist who happens to also do general practice) get explicit UI affordances rather than relaxations of the filters.

**Explanations are part of the contract.** Each result returned to the UI carries a short rationale: "matches your search for Spanish-speaking pediatricians; you've seen this provider before; accepting new patients." The rationale is generated from the ranking features (matched-filter list, "prior visits" feature, "panel-open" feature), optionally rephrased by an LLM for fluency. This is what makes the system feel trustworthy, and it's also what makes the system auditable when a regulator or member services rep asks why a specific result appeared.

**Provider data quality is observable.** Three classes of data quality metrics show up on the operational dashboard: completeness (what fraction of records have each required field), freshness (how recently each field was verified), and accuracy (what fraction of clicks-to-call result in a connected call versus a bounce, what fraction of bookings actually result in a kept appointment). Accuracy metrics flow back into the catalog as freshness penalties and into compliance reporting. The dashboard is shared between the directory team and the network operations team, because directory accuracy is a shared responsibility that no single team owns alone.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter04.03-architecture). The Python example is linked from there.

## The Honest Take

Provider directory search is one of those problems that looks like a search ranking problem and is actually a data engineering problem. Anyone who has worked on directories will tell you the same thing: you can have the best ranker in the industry running on top of a directory full of stale phone numbers and ghost providers, and the patient experience will still be bad. The first eighteen months of a serious directory project are mostly about catalog quality. The ranker arrives in month ten and looks impressive on day one, and the next year is spent feeding it cleaner and cleaner data so its impressive results actually translate into real-world member experience.

The thing that surprises people coming from web-search backgrounds is how much of this is regulatory. Web search is governed by user expectations and competitive pressure. Provider directory search is governed by federal regulations (CMS, the No Surprises Act), state Departments of Insurance, contract law (you have obligations to your network providers about how they're presented), and consumer protection statutes. A clever ranker that produces beautiful relevance and accidentally violates network-adequacy or anti-steering provisions is not actually a clever ranker. The compliance team needs to be in the room when ranking policy gets set, not consulted afterward.

Another surprise: the LTR model is not where the value comes from. The value comes from cleaning up the data, the eligibility filters, and the fairness re-ranker. The LTR scoring is the last 15% of the lift, and you spend disproportionate time on it because it's the part that feels like data science. If your team is gravitating toward "let's tune the ranker more" while the catalog still has 30% staleness, redirect them. The ranker is fine. The catalog is the problem.

The thing I'd do differently: invest in click-tracking infrastructure and audit-grade structured logging from day one. The reason provider-directory rankers are so often mediocre is that the teams running them never built the infrastructure to evaluate their own work honestly. Without click-data with position-bias correction, without complaint events flowing back into the catalog, without cohort-sliced NDCG dashboards, you're flying blind. The ranker will look fine on launch and then quietly drift, and nobody will notice until a compliance audit or a member-experience survey catches the problem six months later. Build the feedback loop first.

The other thing worth flagging: be cautious with how prominently you display tier and quality metadata. "Preferred network" badges are useful when they're real and harmful when they're stale or contractually contested. Provider quality scores (HEDIS, CMS Star ratings) are useful when they're current and statistically defensible at the individual provider level, and harmful when they're noisy small-sample numbers presented as authoritative. The defaults should be: show tier, show "accepting new patients," show distance, show languages. Show quality scores only when they're current, well-attributed, and the patient-facing UI explains what they mean. Otherwise you're embedding noise into a high-stakes decision.

And the trap worth flagging: confusing CTR with success. A directory ranker that drives more clicks is not necessarily a better ranker. A directory ranker that gets patients to the right provider on the first try, who then keeps the appointment and gets care, is the better ranker, even if its CTR looks the same. Track downstream signals (call-tracking outcomes, appointment scheduling, kept-appointment rates) wherever you have the data, and weight them more heavily than clicks in the offline evaluation. The directory's real job is access to care, not engagement on a search page.

One last point, because it's specific to this use case: the directory is often the first sustained interaction a member has with their plan after enrolling. If it works well, the member's mental model of "this plan helps me find care" gets reinforced. If it fails, the member's mental model becomes "this plan's tools don't work, I'll just google instead, and good luck calling them about anything else." The technology choices in this recipe are interesting and the ML is genuinely useful, but the most important thing about provider directory search is that it sets the trust baseline for everything else the member will eventually need from the plan. Treat that trust as the success metric, not the NDCG.

---

## Related Recipes

- **Recipe 4.1 (Appointment Reminder Channel Optimization):** Provides the patient profile, preference store, and engagement event pipeline this recipe consumes; the patient context object used here is the same one used there.
- **Recipe 4.2 (Patient Education Content Matching):** Shares the candidate-generation-plus-re-ranking pattern and the engagement attribution pipeline. The search and embedding infrastructure stood up here is reusable for content search variations.
- **Recipe 4.7 (Care Management Program Enrollment):** Reuses the fairness re-ranking patterns from this recipe (exposure caps, safety-net floors) for a different resource-allocation problem.
- **Recipe 5.x (Entity Resolution / Record Linkage):** The provider match-and-merge step in ingestion is itself an entity resolution problem; the techniques covered in Chapter 5 apply directly to provider deduplication and match scoring.
- **Recipe 6.x (Cohort Analysis / Clustering):** Network adequacy analysis depends on cohort-level views of provider availability against member geographies. The clustering techniques in Chapter 6 support that analysis upstream of this recipe.
- **Recipe 11.x (Conversational AI / Virtual Assistants):** Patient-facing assistants can call this recommender mid-conversation to surface providers when the patient describes a symptom or asks "who should I see?"

---

## Tags

`personalization` · `search` · `learning-to-rank` · `lambdamart` · `hybrid-search` · `vector-search` · `provider-directory` · `network-adequacy` · `fairness` · `data-quality` · `bedrock` · `opensearch` · `dynamodb` · `sagemaker` · `location-service` · `lambda` · `simple-medium` · `mvp-plus` · `hipaa`

---

*← [Recipe 4.2: Patient Education Content Matching](chapter04.02-patient-education-content-matching) · [Chapter 4 Preface](chapter04-preface) · [Next: Recipe 4.4 - Wellness Program Recommendations →](chapter04.04-wellness-program-recommendations)*
