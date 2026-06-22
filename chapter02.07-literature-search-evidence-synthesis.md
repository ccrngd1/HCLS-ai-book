# Recipe 2.7: Literature Search and Evidence Synthesis

**Complexity:** Medium-Complex · **Phase:** MVP → Production · **Estimated Cost:** ~$0.08-0.60 per clinical question answered

---

## The Problem

It's Wednesday afternoon. An internist is in the middle of a clinic session with a patient who has rheumatoid arthritis and has just been diagnosed with early-stage breast cancer. The oncologist has recommended starting adjuvant hormone therapy with an aromatase inhibitor. The patient's rheumatologist has her on methotrexate. The patient wants to know: is it safe to continue methotrexate while on anastrozole? Are there interactions? Has anyone studied this combination? Will her arthritis flare if she stops the methotrexate?

The internist has eight minutes before the next patient. She opens PubMed in a new tab. She types "methotrexate anastrozole interaction." She gets 143 results. She reads the first three abstracts. Two are about rats. One is about a different aromatase inhibitor. She tries a different search. Now she's got 412 results, mostly about breast cancer treatment protocols, none directly answering her question. The patient is sitting in front of her. She does what most clinicians do: she offers a best-guess answer based on her clinical experience, tells the patient she'll look into it more and follow up, and moves on.

That search she just abandoned was, in fact, the right question. There are three 2022 observational studies and one 2024 systematic review directly addressing methotrexate continuation during aromatase inhibitor therapy in patients with inflammatory arthritis. The evidence is nuanced (hepatotoxicity signal in one study, no signal in two others, a pooled analysis leaning toward "reasonably safe with monitoring"). A clinician with twenty minutes and search skills could have constructed a defensible answer. The internist had eight minutes and got pulled off-task by 412 irrelevant results. The patient got the clinician's gestalt, not the literature.

Scale this. A primary care physician sees maybe twenty patients a day. On any given day, three or four of those visits raise a question the physician doesn't have a confident, evidence-grounded answer for. "Should this patient with osteoporosis and a history of atrial fibrillation be on denosumab or a bisphosphonate, given the anticoagulation?" "What's the current evidence for fecal microbiota transplant in recurrent C. diff after two failed vancomycin courses?" "My patient with long COVID is asking about low-dose naltrexone; is there any real evidence?" Each question has real answers in the literature. Almost none get looked up in the moment, because the friction is too high.

The hospital version of the same problem. A pulmonary-critical-care fellow is admitting a patient with severe eosinophilic asthma to the ICU who is already on dupilumab. The attending asks: "What's the evidence on continuing biologics during acute exacerbation? Does this matter for our steroid dosing?" The fellow has charts to write, orders to put in, a rapid response to field. He opens UpToDate. UpToDate has a section on severe asthma management, which is current as of three months ago, which doesn't specifically address continuation of dupilumab during admission. He runs a search. He finds a 2023 case series, a 2024 retrospective cohort, and a society-level consensus statement (not a guideline, a consensus statement, which matters for evidence grading). The fellow is supposed to synthesize that into a defensible recommendation in ten minutes. He usually punts: "I'll continue what the outpatient team had her on and we'll follow up with allergy in the morning."

This happens tens of thousands of times a day across American medicine. There is a body of published evidence that, in theory, could inform almost any clinical question. In practice, only a tiny fraction of clinical questions get looked up, and the ones that do are looked up imperfectly. The "evidence-based medicine" movement has been around for thirty years. It has changed the standards. It has not solved the looking-up problem. The problem isn't a lack of evidence. The problem is a gap between the clinician at the bedside and the literature that sits behind a search interface designed by librarians for a different workflow.

The policy version. A payer's medical director is reviewing a prior authorization appeal for an off-label use of a $180,000-per-year biologic. The manufacturer's letter cites seven papers. Are those papers the strongest evidence? Are there papers the manufacturer didn't cite that are less favorable? Is there a systematic review or meta-analysis that should override individual studies? The medical director has to make a defensible decision and may end up in front of a regulator or a court. The rigor required is "show me the evidence, grade it, and tell me what it does and doesn't support." That rigor is a PhD's worth of training in evidence evaluation, applied to one case.

The research version. A clinical research coordinator is setting up a new trial for a novel oral agent in heart failure with preserved ejection fraction. Before finalizing the protocol, the team needs to understand the landscape of prior trials: what was studied, what endpoints were used, what populations were enrolled, what the results looked like, where the knowledge gaps are. This is a ten-to-twenty hour literature review for a senior research assistant, done well. It's often done poorly or not done at all, which means new trials are designed in ignorance of prior work.

What all these scenarios have in common is the same underlying gap: medical literature is vast, well-indexed, and largely open-access, but the work of finding the right papers, reading them correctly, weighing the evidence, and synthesizing an answer is expensive human labor that doesn't fit into the time available. You can't hire a medical librarian for every clinic room. You can't put a systematic reviewer on every prior auth appeal. You need the computer to do more of this work, and for decades the computer hasn't been able to, because the work requires understanding text, not just matching keywords.

Modern LLMs, used correctly, change that equation. Used incorrectly, they make it dramatically worse (a fabricated citation that looks real is worse than no citation at all). The architecture that gets this right is the thing we're going to build in this recipe.

---

## The Technology: RAG, Done for Grown-Ups

### Why General-Purpose LLMs Are the Wrong Tool for This Job

Let's start by admitting what doesn't work.

"Ask the LLM your medical question" is a terrible product. The model will produce a fluent, confident, plausible-sounding answer. Some percentage of those answers will be wrong. Some percentage will cite papers that don't exist. Some percentage will conflate findings across studies. The model has no idea which of its outputs are accurate and which are fabricated, because statistically speaking the fabrications look like the accurate answers (the model has optimized for plausibility, not truth).

The fabricated-citation problem is specific and embarrassing. A model asked to cite evidence for a claim will happily produce "Smith et al., JAMA 2021, 325(12), pp. 1123-1131" as a citation. That looks like a real citation. It has a plausible author name, a real journal, a plausible volume and issue, and a plausible page range. It is very often completely invented. Clinicians who have tried to look up these citations find they don't exist. Worse, sometimes they do exist, but they're about something else entirely, because the model has associated a real citation with a wrong claim.

This class of error is not fixable by better prompting. It's a property of generating claims without a grounded retrieval step. The fix is architectural: don't let the model generate claims; let it generate summaries of claims it is given.

### What RAG Actually Is, Under the Hood

RAG stands for Retrieval-Augmented Generation. Everyone in AI says "RAG" now the way they used to say "cloud-native" five years ago. The term has gotten a bit diluted. At its core, the pattern is straightforward.

Step one: you have a corpus of source material (in this case, medical literature). You pre-process it into chunks and index the chunks in a way that makes them searchable by semantic meaning, not just keyword match. The common approach is to embed each chunk with a text-embedding model into a high-dimensional vector, and store those vectors in a vector database. The index supports queries of the form "give me the 50 chunks most semantically similar to this question."

Step two: when a user asks a question, you first embed the question using the same embedding model. You query the vector database with the question's embedding. You get back the top N chunks most relevant to the question. That's the "retrieval" part.

Step three: you construct a prompt for the LLM that includes both the question and the retrieved chunks, with instructions like "answer the question using only the content in the retrieved chunks; cite each chunk by its identifier; if the chunks don't contain a clear answer, say so." The model generates a response grounded in the retrieved material. That's the "augmented generation" part.

The power of the pattern is that it decouples the "knowledge" (which lives in your indexed corpus and can be updated freely) from the "language ability" (which lives in the model and doesn't need to know any specific facts). You can update the corpus nightly as new papers publish. You can swap the model as better ones come out. The knowledge and the language ability are orthogonal concerns.

The limitations of the pattern are equally important. If the retrieval step doesn't surface the right chunks, the generation step has no way to produce the right answer. If the retrieved chunks contradict each other, the model may smooth over the contradiction. If the chunks are taken out of context (a single sentence from a paper's limitations section looks like a conclusion), the answer can be misleading in subtle ways.

For medical literature, RAG is the right baseline. But "baseline RAG" is not enough. The next several sections are about the specific adaptations that make medical RAG actually work.

### The Corpus Problem: What You're Indexing Matters More Than How

The most-ignored decision in RAG architecture is what you put in the corpus. Teams tend to fixate on vector databases and chunking strategies and re-ranking models, then point the whole apparatus at a random dump of PDFs and wonder why the answers are mediocre.

For medical literature, you have options that vary by quality, licensing, and coverage:

**PubMed Central Open Access Subset.** Several million full-text articles, machine-readable, redistributable, free. This is the default starting corpus for any medical RAG system that isn't paying for licensed content. Coverage is strong for older literature and for journals that chose open access; weaker for high-impact closed-access journals.

**PubMed abstracts.** Every indexed biomedical article has a PubMed abstract available via the NCBI E-utilities API. Abstracts are not full text, but they contain the core claims, the population studied, the intervention, and the primary outcome. A corpus of PubMed abstracts is broader in coverage than PMC Open Access but shallower in depth. Many clinical RAG systems use PubMed abstracts as the primary retrieval target and fetch full text (from PMC or licensed sources) for the small subset of documents that the generation step will actually cite.

**Clinical guidelines and society statements.** AHA, ACC, IDSA, USPSTF, ACOG, AAP, NCCN, and many others publish guidelines and position statements that are evidence-graded and represent consensus standards. These are disproportionately useful for clinical questions because they already do the synthesis work. Licensing varies (some are open, some require institutional subscriptions, some can be obtained through partnerships). A corpus that includes guidelines alongside primary literature can often answer a clinical question by pointing at the guideline rather than making the model re-derive the answer from primary studies.

**UpToDate, DynaMed, BMJ Best Practice.** Commercial point-of-care references that are professionally curated and kept current. Licensing is not free and redistribution is restricted. If your institution has a subscription, there may be API access available for internal RAG systems. If not, you're relying on what the licensing terms permit. These sources are high-value because they are already synthesized and evidence-graded.

**Cochrane Reviews.** Systematic reviews of high methodological quality. When a Cochrane review exists for your question, it's often the best single piece of evidence. Abstracts are freely available; full text requires a subscription for most users.

**ClinicalTrials.gov.** Registration and results records for a huge volume of trials. Useful for understanding the trial landscape for a question and for identifying published and unpublished evidence. Free and redistributable.

**Specialty society databases.** Journal collections for ACC (JACC family), IDSA (Clinical Infectious Diseases), Infectious Diseases Society of America (MMWR partnership), and others. Some are open, some require society membership, some require institutional library access.

**Your institution's own knowledge base.** Local protocols, order sets, policies, and internal clinical pathways. These are often the *most* useful content for institution-specific questions and almost always absent from generic medical RAG systems. If you're building this for a health system, your own content is a corpus in its own right.

The design decision is: which of these sources do you include, and with what precedence? A well-designed medical RAG system often ranks sources by evidence tier during retrieval (a systematic review outranks an observational study, a guideline outranks a retrospective case series) and weights them accordingly in the generation prompt.

### Chunking Medical Literature Is Not Chunking News Articles

General-purpose RAG tutorials suggest chunking documents by some fixed token count (500 tokens, 1000 tokens, pick a number) with some overlap. That works acceptably for news articles and web content. It works badly for medical literature, and the reason matters.

A medical paper has a heavy structure: Title, Abstract (itself typically sub-structured as Background/Methods/Results/Conclusions), Introduction, Methods, Results, Discussion, Conclusion, References. Within those sections, individual paragraphs or sentences have very different clinical meanings. A sentence in the Results section ("Event rate was 4.2% in the treatment arm vs 6.8% in control, p=0.03") is a concrete claim. A sentence in the Discussion section ("Our findings should be interpreted with caution given the potential for residual confounding") is a caveat. A sentence in the Introduction ("Previous studies have suggested X") is background, not an original finding of this paper.

Good medical chunking respects this structure. The practical pattern: chunk by section, and within long sections, chunk by paragraph or by natural sub-section boundaries. Each chunk carries metadata identifying its section, so the retrieval layer can weight Results and Conclusions chunks higher than Introduction chunks, and the generation layer can prompt appropriately ("the following chunks include Results sections of relevant studies; cite specific numerical findings where present").

Chunking also has to preserve enough context for the chunk to be interpretable on its own. "Patients in arm A had a 23% reduction in the primary endpoint" is meaningless without knowing what arm A is and what the primary endpoint is. The practical fix: include the paper's title, abstract, and relevant section header in the chunk's metadata, and pass that context to the generation step alongside the chunk content.

### Retrieval Is Where the Game Is Won or Lost

The generation step gets all the attention (which model? which prompt? how many tokens?). The retrieval step is where accuracy is actually determined. If you don't retrieve the right chunks, the generation step has no way to produce the right answer. If you retrieve irrelevant chunks alongside the right ones, the model gets confused and may cite the wrong sources.

Baseline retrieval is a dense-vector similarity search. The question and the corpus are embedded with the same model, and nearest-neighbor search returns the top N chunks. This works reasonably well for clear, well-specified questions. It works poorly for questions that use different terminology than the source literature, for questions with multiple sub-parts, and for questions where the answer depends on combining evidence across multiple sources.

Several patterns improve retrieval:

**Hybrid retrieval.** Combine dense-vector search with sparse-keyword (BM25) search. The vector search catches semantic similarity; the keyword search catches exact matches (specific drug names, specific conditions, specific trial names). Fuse the two result sets with reciprocal rank fusion or a similar technique. This is consistently better than either alone for medical content, because medical terminology is specific and keyword-heavy.

**Query expansion.** Before retrieval, have the LLM rewrite the clinical question into multiple search queries. "Is methotrexate safe with anastrozole in RA?" becomes "methotrexate anastrozole interaction," "methotrexate aromatase inhibitor rheumatoid arthritis," "DMARD continuation during breast cancer hormonal therapy." Each query retrieves a set of chunks; the sets are merged and deduplicated. This catches literature that uses different terminology than the clinician's phrasing.

**Hypothetical document embeddings (HyDE).** Ask the LLM to generate a plausible answer to the question, then embed the plausible answer and use that embedding for retrieval. The idea is that the plausible answer is written in the same register as the target literature, so semantic similarity is more likely to surface the right chunks. HyDE is controversial (you're trusting the model to write something that doesn't introduce its own biases) but empirically improves retrieval for many query types.

**Re-ranking.** After an initial retrieval fetches a larger candidate set (say, 100 chunks), run a more expensive re-ranker over the candidates to select the top 10-20. Re-rankers are cross-encoder models that look at the query and the candidate chunk together, and they're much more accurate than the initial similarity search. The trade-off is cost and latency, so you retrieve broad, re-rank narrow.

**Metadata filtering.** Filter the retrieval by publication date (exclude pre-2015 if the field has moved), by study type (favor systematic reviews over observational), by journal quality, or by population (adult vs pediatric). Metadata filters drop irrelevant content before similarity search, which improves result quality and reduces cost.

### Evidence Grading Is What Makes It a Clinical Tool, Not Just a Search Tool

A good clinical answer isn't just "here's what the literature says." It's "here's what the literature says, and here's how confident we are in it, based on the type and quality of evidence available."

The evidence-based medicine movement has established hierarchies for this. The simplest version:

- **Level 1:** Systematic reviews and meta-analyses of randomized controlled trials
- **Level 2:** Individual randomized controlled trials
- **Level 3:** Cohort studies
- **Level 4:** Case-control studies
- **Level 5:** Case series and expert opinion

More formal frameworks exist. GRADE (Grading of Recommendations Assessment, Development and Evaluation) is used by many guideline bodies and assesses evidence on dimensions of risk of bias, consistency, directness, precision, and publication bias. USPSTF uses its own grading scheme (A, B, C, D, I). Oxford CEBM has a levels-of-evidence framework.

A clinical RAG system that serves clinicians should tag each retrieved source with an evidence tier and should communicate that tier in the answer. "A 2024 meta-analysis of 8 RCTs (Level 1) found X; a 2022 retrospective cohort (Level 3) found Y; a 2023 case series (Level 5) suggested Z" is a qualitatively different answer from "Various studies have found X, Y, and Z." The clinician can weight the evidence appropriately when the evidence is graded.

Automating evidence grading is imperfect. Study type can be inferred from structured metadata (PubMed's publication-type tags are fairly reliable) but risk of bias assessment requires reading the methods carefully. A practical compromise: automate the coarse tiering by publication type, surface the grade to the reader, and leave fine-grained bias assessment to the clinician reading the source. This is "help, not replace."

### The Citation Discipline

Every claim in the generated answer should cite at least one retrieved source. Every citation should point to a specific chunk in the retrieved set, and through that chunk back to a specific paper in the corpus. If the clinician can't trace a claim to a source in one click, the citation is cosmetic rather than functional.

The practical pattern: each retrieved chunk gets a unique identifier during retrieval. The generation prompt instructs the model to cite chunks by their identifier (e.g., `[chunk_14]`). Post-generation, the system replaces chunk identifiers with formatted citations (author, journal, year) and attaches links back to the source paper. The answer is rendered with inline citations and a bibliography.

Critically: the model should not generate citations that aren't in the retrieved set. If the model wants to claim X and no retrieved chunk supports X, the model should say "no high-quality evidence retrieved" rather than fabricate a citation. This has to be enforced in the prompt and verified by post-generation validation.

Post-generation validation is non-negotiable for clinical RAG. Parse the answer, extract the citations, verify each one exists in the retrieved set, verify the cited chunk actually supports the claim (semantic similarity between claim and chunk above a threshold). Any unverified claim is either regenerated with stricter instructions or held for human review. Never ship an unverified clinical claim to a clinician.

### The Hallucination Failure Modes You Have to Design Around

**Citation fabrication.** Already covered. Mitigation: constrain generation to retrieved chunks only; validate citations against the retrieved set.

**Claim fabrication with real citation.** Subtler than citation fabrication: the citation is real, but the claim the model attached to it isn't actually in the paper. Mitigation: semantic validation of each claim against the cited chunk.

**Over-generalization.** The model treats a single study's finding as established consensus. A 2020 pilot trial of 47 patients becomes "studies have shown X." Mitigation: prompt the model to quantify the evidence base for each claim (how many studies, what type, how large); render that quantification in the answer.

**Wrong direction.** The model reports a finding with the wrong sign. A paper found a 20% *reduction* in event rate; the model's summary says a 20% *increase*. This is a catastrophic error for clinical use. Mitigation: semantic validation has to catch sign flips, which is harder than it sounds; preserving exact numerical quantities from source text (verbatim, not paraphrased) helps.

**Population mismatch.** A paper studied adults over 65; the model treats the finding as applying to adults generally. A paper studied a specific cancer subtype; the model generalizes to all patients with that cancer. Mitigation: prompt the model to explicitly name the study population for each cited paper; include population filters in retrieval when the question is population-specific.

**Temporal drift.** The literature corpus is a year old. The model doesn't know about the big trial that read out three months ago. Worse, the model may "remember" the pre-trial consensus from its training data and present it as current. Mitigation: explicitly tell the model the corpus's date coverage, instruct it not to use training-data knowledge, and flag answers where the clinician should expect recent developments (fast-moving fields).

**Non-answers presented as answers.** The retrieved chunks don't actually address the question, but the model produces an answer anyway by pattern-matching. Mitigation: prompt the model to say "the retrieved evidence does not directly address this question" when applicable; validate answers against the retrieved set's actual relevance.

**Equipoise collapsed.** Real clinical questions often have equipoise (the evidence is genuinely mixed, or the question hasn't been studied directly). The model's training pushes it toward confident assertions. A good clinical RAG system surfaces equipoise and uncertainty rather than picking a side. Mitigation: specific prompt guidance on uncertainty language, and a post-generation check that looks for inappropriate confidence.

**Recommendation when asked to inform.** The clinician asks "what does the evidence say about X?" and the model answers "you should do X." That's not synthesis; that's a recommendation, and recommendations have regulatory implications. Mitigation: the generation prompt should produce descriptions of evidence, not directives. "The evidence supports X as an option with Y caveats" rather than "you should do X."

### Why This Use Case Sits Where It Does on the Complexity Curve

Recipe 2.5 (after-visit summaries) and Recipe 2.6 (clinician summaries) are both grounded-generation problems. Literature search and synthesis is also grounded generation, but with a twist: the ground truth is in a corpus that the user does not control (they didn't write the papers), and the corpus is large enough that retrieval is itself a hard problem. In patient-facing and clinician-facing summarization, the source documents are handed to the pipeline; the pipeline just has to not hallucinate. In literature RAG, the pipeline has to find the right documents *first*, and then not hallucinate on top of whatever it found.

This is what makes 2.7 Medium-Complex rather than Medium. Every one of the failure modes above compounds with retrieval errors. A bad retrieval feeds a good generation step into producing a confidently-wrong answer, and the confidence is indistinguishable from a correct answer at the output layer. The architecture has to invest in retrieval quality, in post-generation validation, and in UI design that invites clinician verification. Skip any of those three and the system is dangerous.

The good news: this is a problem the field has been working on hard for five years, and the patterns that work are well-understood. The bad news: none of them are trivial to implement well, and evaluation is genuinely difficult because you're measuring a system against "the actual state of medical knowledge," which is harder to gold-standard than most eval targets.

---

## The General Architecture Pattern

The overall flow looks like this:

```text
[Clinician Question]
    → [Clarify and Classify Question]
    → [Query Expansion and Rewriting]
    → [Multi-Source Retrieval (Vector + Keyword + Metadata Filters)]
    → [Re-rank and Select Top Chunks]
    → [Apply Evidence Tiering]
    → [Fetch Full-Text Context for Top Chunks]
    → [Grounded Generation With Citation Discipline]
    → [Post-Generation Validation]
    → [Render Answer With Citations, Evidence Grades, and Source Links]
    → [Log for Audit and Feedback]
```

Let's walk through each stage conceptually.

**Clinician question.** A clinician types (or speaks) a question. The question may be crisp ("is denosumab contraindicated in stage 4 CKD?") or vague ("I have a 68-year-old with multiple myeloma on daratumumab who just developed thrombocytopenia; what do I do?"). The more specific the question, the better the downstream retrieval. Vague questions should trigger a clarification step rather than being shoved at retrieval directly.

**Clarify and classify.** Before retrieval, determine what kind of question this is. Diagnostic? Therapeutic? Prognostic? Screening? Each question type has different ideal evidence sources (diagnostic studies follow STARD; therapeutic evidence favors RCTs; prognostic evidence comes from cohort studies). Classification helps downstream retrieval weight sources appropriately. For vague questions, the system can ask a targeted clarifying question before retrieval.

**Query expansion.** Rewrite the question into multiple search queries that capture likely terminology variations. Include synonyms, generic-to-brand conversions for drugs, standard-to-specific condition names. The expansion step is cheap and dramatically improves retrieval coverage.

**Multi-source retrieval.** Query the corpus across modalities: dense-vector similarity, sparse keyword match, metadata filters. If the corpus is sharded by source (PubMed abstracts, guidelines, Cochrane, institutional content), query each shard and collect candidate chunks. Merge the result sets with rank fusion. Evidence tier enters as a ranking boost, not a hard filter: a question where the only evidence is observational should still surface that evidence and let the generation step's evidence-strength rating reflect the tier mix honestly.

**Re-rank.** Apply a more expensive re-ranker to the candidate set to surface the most relevant chunks. Re-ranking is where retrieval quality goes from acceptable to good.

**Evidence tiering.** For each retrieved chunk, tag the source with its evidence tier (systematic review, RCT, observational, case series, guideline, expert opinion). Use publication-type metadata where available; infer from structured abstract content where not.

**Fetch full-text context.** For the top chunks that will actually be cited, fetch additional surrounding context from the source paper if it's available. A chunk taken in isolation may miss critical caveats from adjacent paragraphs. Fetching a paragraph of context on either side of the chunk gives the generation step a fuller picture.

**Grounded generation.** Construct a prompt that includes the question, the retrieved chunks with their identifiers and evidence tiers, and explicit instructions: cite every claim, use chunk identifiers, don't invent citations, surface uncertainty where appropriate, describe evidence rather than recommend. Run the prompt through the LLM.

**Post-generation validation.** Parse the answer. Extract claims and citations. For each citation, verify the chunk exists in the retrieved set. For each claim, verify semantic alignment between the claim and the cited chunk. Flag any unverified claims. If too many claims fail validation, regenerate with stricter instructions or escalate for human review.

**Render with citations.** Replace chunk identifiers with formatted citations. Attach source links. Surface evidence grades inline. Render the answer in a clean format that makes claim-to-source tracing easy.

**Log for audit and feedback.** Log the question, the retrieved chunks, the generated answer, the validation result, and the final rendered output. Capture clinician feedback (helpful, unhelpful, inaccurate, escalated) and feed it into retrieval and prompt iteration.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter02.07-architecture). The Python example is linked from there.

## The Honest Take

I've watched more literature-search RAG projects flame out than any other category of clinical AI work. The failure patterns are consistent.

The first pattern is the demo-to-production gap. Somebody on the team builds a prototype that answers five cherry-picked questions beautifully. Leadership sees the demo. Budget gets approved. A real rollout exposes the prototype to the messy, specialty-diverse, terminologically-varied, occasionally-ambiguous questions clinicians actually ask, and the quality craters. The team spends six months chasing individual failure modes and emerges with a system that's 20-30% better than the demo but still produces too many wrong-enough answers to earn clinician trust. By month nine, the tool has a bad reputation that's very hard to recover from. The mitigation isn't more engineering; it's resisting the pressure to demo too early. Build a question-set that reflects the breadth of real queries, evaluate against that set weekly, don't show leadership the tool until it performs reasonably on the breadth set. Yes, this is politically hard. Do it anyway.

The second pattern is the corpus-quality blind spot. Teams pour effort into retrieval algorithms and embedder choice and re-ranker fine-tuning, and neglect the corpus. A world-class retrieval stack over a mediocre corpus produces mediocre answers. Auditing the corpus is boring work (checking coverage, finding stale sources, investigating why certain questions get no retrieval, verifying that guidelines are actually in the index and not just mentioned). It's also the highest-leverage work. Spend the time.

The third pattern is underestimating the validation step. "We'll have the model cite its sources" is not validation; it's formatting. Real validation (citations exist, claims match sources, numerics preserve, populations align) is a pipeline unto itself, and it's the thing that turns "looks like an answer" into "is an answer." Teams that skip this step or implement it superficially ship systems that fail the first time a motivated clinician tries to trace a claim back to its source and finds the claim isn't actually in the paper. Once that trust is gone, getting it back is brutal.

The fourth pattern is specialty-specific failure modes. A system that works well for primary-care questions can completely fall apart on oncology questions, because oncology literature has structural features (trial-heavy, abbreviation-heavy, rapid update cycle, complex subgroup analyses) that retrieval and generation handle differently. Pick a beachhead specialty, get it right, then expand. "Works for everyone" at launch usually means "works for no one."

The fifth pattern is neglecting the UX. Clinicians don't just need a good answer; they need an answer delivered in a form they can use in the thirty seconds they have. If the UI presents a wall of text without clear claim-to-citation linking, without evidence-grade framing, without the ability to click into a source paper, the tool gets closed and not reopened. UX is not a decoration on top of the ML; it's part of the product. Budget accordingly.

A few things that have worked, in my experience:

**Start with safety-interaction questions.** They're bounded, they have clear right answers more often than therapeutic questions, the evidence base is more structured (package inserts, pharmacology databases, interaction checkers), and clinicians have immediate use for them. Build the pipeline on safety-interaction questions, earn trust, then expand.

**Invest in the retrieval trace UI.** Letting clinicians see what was retrieved, why it was ranked the way it was, and which chunks supported which claim is the feature that turns skeptical clinicians into advocates. It takes real effort. It's worth it.

**Curate, don't just scrape.** A smaller, well-curated corpus with strong metadata beats a larger, messier corpus. Take the 200 most-cited papers in a specialty, the current guidelines, and the current society consensus statements, and start there. Expand deliberately rather than by volume.

**Set expectations honestly in the product.** A banner that says "The corpus contains evidence through April 2026. Recent developments may not be reflected." is not a weakness; it's a trust signal. A disclaimer that says "This synthesis is not a substitute for clinical judgment and should be verified against the cited sources" is not a legal CYA; it's the correct framing. Clinicians who see a product that acknowledges its limits trust the product more, not less.

**Log everything and look at the logs.** The logs tell you what clinicians are actually asking (often different from what you expected). They tell you where validation is failing. They tell you which sources the system keeps trying to use and can't find. Sit down with a week of logs and a clinical reviewer once a month. The surprises in those sessions are where the real improvements come from.

**Don't build this tool in isolation.** Medical librarians are still vastly better at complex literature searches than any RAG system. A library-integrated product (RAG for routine questions, escalation to a medical librarian for complex or high-stakes questions) is usually the right operational design for a health system. The RAG system covers the 80% of questions that it can answer well; the librarian covers the 20% that require human judgment. Pretending the RAG system can replace the librarian is how you end up with both a worse RAG system (because you avoided the escalation path) and an absent librarian service (because the budget went to the AI).

Final thought: this is one of the highest-leverage applications of medical AI I've worked on. A modest-quality literature-search tool saves clinicians minutes per question; at scale, that's millions of clinician-hours a year. It won't replace clinical reasoning. It doesn't need to. It just needs to deliver the right starting point faster than the clinician could get there alone, with enough transparency that the clinician can trust what they're seeing. That's a bar worth clearing.

---

## Related Recipes

- **Recipe 2.4 (Prior Authorization Letter Generation):** Another grounded-generation use case with citations. Literature RAG can serve as the evidence-retrieval layer for prior auth letters; the synthesis patterns transfer.
- **Recipe 2.5 (After-Visit Summary Generation):** Same RAG pattern applied to a different target (patient-facing language vs clinician-facing synthesis). Shared validation discipline.
- **Recipe 2.6 (Clinical Note Summarization):** Grounded generation over an in-chart corpus. The retrieval layer is smaller and more focused, but the generation patterns are similar.
- **Recipe 2.9 (Clinical Decision Support Synthesis):** Sits on a continuum with 2.7. Decision support adds patient-specific reasoning and moves toward recommendations; literature search stays descriptive. The regulatory and liability posture differs; the retrieval and synthesis architecture overlap substantially.
- **Recipe 2.10 (Multi-Modal Clinical Reasoning):** Extends decision support into multi-modal inputs. The literature RAG pipeline from this recipe can serve as the evidence layer for a multi-modal reasoning system.
- **Recipe 13.9 (Literature-Derived Knowledge Graph):** Knowledge-graph representations of medical entities and relationships can augment RAG retrieval: graph-based retrieval finds papers connected by entity relationships, not just semantic similarity. Hybrid graph-plus-vector retrieval is a promising direction for medical RAG.
- **Recipe 8.4 (Medication Extraction and Normalization):** Traditional NER pipelines produce the entity extraction that drives retrieval filters in this recipe. The two pipelines share infrastructure.

---

## Tags

`llm` · `generative-ai` · `bedrock` · `knowledge-bases` · `opensearch` · `comprehend-medical` · `rag` · `retrieval-augmented-generation` · `hybrid-search` · `vector-search` · `re-ranking` · `medical-literature` · `pubmed` · `evidence-synthesis` · `evidence-grading` · `citation-verification` · `grounded-generation` · `clinical-qa` · `medium-complex` · `hipaa` · `provenance`

---

*← [Recipe 2.6: Clinical Note Summarization](chapter02.06-clinical-note-summarization) · [Chapter 2 Index](chapter02-preface) · [Next: Recipe 2.8 - Ambient Clinical Documentation →](chapter02.08-ambient-clinical-documentation)*
