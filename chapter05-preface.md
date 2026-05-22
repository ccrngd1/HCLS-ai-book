# Chapter 5 Preface: Are These Two Records the Same Person?

Here's a question that has no good answer in American healthcare: *how do you know two records are about the same person?*

Walk into any reasonably-sized health system tomorrow morning, query their database for "Maria Garcia, born March 1972," and brace yourself. You'll get hits. Plural. Some of those records might be the same Maria Garcia with three different chart numbers because she was registered three different times by three different front-desk staff who each typed her name slightly differently. Some of those might be different Maria Garcias entirely (it is, statistically, not an unusual name). Some of them might be the same Maria Garcia, but one of the records is from before her marriage and uses her maiden name, and your database doesn't know that. One of them might be her mother. One of them might be a typo for "Maria Gracia" that's been sitting there for fifteen years and nobody's noticed.

Now imagine you're trying to give Maria the right care. Her allergy to penicillin is documented in record number two. Her hypertension is in record number five. Her last colonoscopy is in record number one. Her active prescription list is split across records three and four. The system that's supposed to give her clinician a single, accurate view of her health history shows them, at best, one of these records, and at worst, a confused merge of two or three of them with conflicting information. <!-- TODO: verify specific patient matching error rate statistics; commonly cited figures are 5-30% within single systems and substantially higher across organizations, but exact numbers vary by source (ECRI, ONC, Pew, Sequoia) -->

This is the entity resolution problem. It is, depending on who you ask, either the most important unsolved problem in healthcare data or just a deeply unglamorous plumbing issue that nobody wants to fund. Both of those things are true at the same time. And it's the subject of this chapter.

---

## What Entity Resolution Actually Is

Entity resolution is the practice of figuring out which records in one or more datasets refer to the same real-world thing. The "thing" can be a patient, a provider, an organization, an address, an insurance plan. The "records" can come from one system or many. The output is a decision: these records are the same entity, or they are not, or we are not sure and need a human to look.

Other names for the same problem, because the literature is fragmented and every field reinvented this independently: record linkage, deduplication, identity resolution, master data management, fuzzy matching, data integration, the "patient matching" problem (specifically when the entity is a patient). They all have the same core: you have records that *might* be about the same entity, and you need a system that decides when they are.

There are three broad approaches that show up across the recipes, and they're worth knowing because they drive very different architectures:

**Deterministic matching.** Exact match on a set of key fields. If first name, last name, date of birth, and SSN all match exactly, it's the same person. Simple, fast, easy to explain, easy to audit. Falls apart the moment any field has typos, formatting differences, or missing values, which in healthcare data is constantly. Useful as a fast first pass and as the right answer when you have a strong identifier (NPI for providers, plan-issued member ID within a payer's own data).

**Probabilistic matching.** Score each field comparison (exact match, similar but not exact, mismatch, missing) and combine the scores into a single match probability. The classical foundation for this is the Fellegi-Sunter model from 1969, and it's still the workhorse of most production patient-matching systems six decades later, because it's actually quite good and very interpretable. You set a high threshold for auto-match, a low threshold for auto-non-match, and everything in between goes to human review. Tunable, explainable, the right answer for most healthcare entity resolution problems.

**ML-based matching.** Train a classifier (gradient boosting, neural networks, transformer-based embeddings) to predict whether a pair of records refers to the same entity. Can incorporate features that are awkward in probabilistic frameworks (string embeddings, address geocoding distances, network features). Higher ceiling on accuracy when you have labeled training data. Lower interpretability, harder to audit, and still usually wrapped around a probabilistic core for the parts that need to be defensible.

Most production systems are hybrids. Deterministic for the easy cases, probabilistic for the medium cases, ML re-ranking for the hard ones, and humans for the cases the system isn't confident about. The recipes in this chapter are explicit about which combination they use and why.

---

## Why Healthcare Is Uniquely Bad At This

Most data integration tutorials use clean examples: customer records with a customer ID, business records with a tax ID, product records with a SKU. The "join" is a SQL operation. Entity resolution feels like a niche concern. Then you get to healthcare, and you discover that the United States, alone among developed countries, has explicitly prohibited the creation of a national patient identifier since 1998 (Section 510 of the Labor-HHS appropriations bill, renewed every year since). <!-- TODO: verify current status of the appropriations rider; as of recent years there have been bipartisan efforts to lift the prohibition but as of writing it remains in place -->

That single policy decision is why this chapter exists. Without a national identifier, every healthcare entity resolution problem is fundamentally an inferential one, and that inference has to work across a series of data realities that are uniquely brutal:

### Demographic Data Is Lower-Quality Than You Think

Front-desk registration is one of the highest-volume, lowest-paid, most-rotated jobs in healthcare, and it is also the one place where every piece of demographic data enters the system. Names get typed with typos. Date of birth gets entered as "01/01/1900" because the patient didn't have ID and the system required something. Phone numbers are landlines that haven't been active in a decade. Addresses are out of date by an average of several years per population because Americans move constantly. Social Security numbers, where collected at all, have entry error rates that are not small. <!-- TODO: verify specific demographic data quality stats; commonly cited figures from ONC, AHIMA and EMPI vendor literature suggest 5-15% of records contain at least one demographic data quality issue, but figures vary --> The data you're trying to match on is not pristine ground truth. It's a noisy approximation of pristine ground truth.

This is the single biggest reason "just join on name and DOB" doesn't work. You're joining on noise.

### Names Are Not Stable

In the abstract, a name is a string. In practice, names change. People get married and take their spouse's name. People get divorced and take their previous name back. People legally change their name for any number of reasons. People go through gender transition and change their name (and sometimes other demographic data) accordingly. People use nicknames, middle names, or initials inconsistently. People with names from naming conventions outside the dominant culture get their names mangled in ways that vary by who's doing the data entry. Suffixes (Jr, Sr, II, III) drop and reappear. Patronymics, hyphenations, and apostrophes get normalized differently in every system.

The "longitudinal patient matching across name changes" recipe (5.7) is in the complex tier specifically because name change is a regular, expected event in a long enough timeframe, and your matching system has to handle it without losing the historical record or accidentally outing patients who don't want their identity changes broadcast.

### Family Members Are a Confounder

Family members live at the same address, share last names, sometimes share first names (Sr/Jr/III), share insurance plans, and are sometimes seen at the same practices. Twins share birthdays. Mothers and infants are often co-registered with overlapping data fields. Spouses share insurance member IDs but with dependent codes that some systems strip out. Probabilistic matchers built without family-aware logic regularly merge a father and son into a single record, or split a mother's prenatal and postpartum records onto two different patients. Households are useful for some recipes (5.3) and dangerous in others (5.5, 5.7).

### Different Systems Capture the Same Thing Differently

Every EHR has demographic fields. Every payer system has demographic fields. Every state immunization registry has demographic fields. None of them define those fields the same way. "Race" is one field in some systems and seven check-boxes in others. "Address" might be a single string, a parsed object, or a USPS-standardized normalized form. "Phone" might or might not include extension. "Date of birth" usually behaves, but you'd be surprised. When you're matching across organizations, half the work is just normalizing the fields enough to compare them.

### The Cost of Errors Is Asymmetric and Severe

Two kinds of mistakes, each bad in different ways:

**False merges** (wrong-patient overlay) combine two real people into one record. The clinician sees one person's allergy list overlaid with another person's medications. This is the patient safety failure mode, and there are documented cases of it killing people. <!-- TODO: verify; ECRI and Joint Commission have published case reports on patient identification errors leading to adverse events, with wrong-patient errors consistently listed in top patient safety hazard lists -->

**False splits** (failure to match) leave a single patient with multiple records that the system doesn't know are connected. Critical history is missing when the clinician needs it. Tests get repeated unnecessarily. Care gaps go unflagged. This is the cost-and-quality failure mode. It's less acutely dangerous than a false merge but often more common, and at scale it represents enormous waste and worse outcomes.

The thresholds you tune in a probabilistic matcher are explicitly choosing the balance between these two failure modes. Most healthcare matching systems are tuned conservatively (favor false splits over false merges) because the patient safety asymmetry is real. The recipes are explicit about this tradeoff and how to communicate it to the people who own the consequences.

### Privacy Constraints Limit Your Options

If two organizations want to match patients across their populations, they can't just exchange flat files of demographics. That's a HIPAA-regulated activity at minimum, and depending on the relationship, it may not be permitted at all without specific patient consent. Privacy-preserving record linkage (recipe 5.8) exists precisely because the natural approach (just send me your data and I'll match it) is often not legally available. Cryptographic and statistical techniques let two parties find their overlapping records without revealing the non-overlapping ones, but they impose accuracy costs and operational complexity that make them last-resort tools rather than default ones.

### The Stakes Range From Administrative to Existential

Provider matching to NPI (5.2) is administratively important and has minimal patient impact when it goes wrong. Patient matching for billing eligibility (5.4) affects revenue cycle. Patient matching for clinical care (5.5) affects safety and outcomes. Patient matching for outcomes research (5.6) affects what we collectively learn from the data. National-scale matching for interoperability (5.9) affects whether the digital health infrastructure of the country actually functions. The difficulty of the problem varies; so does what failure means. Both of those shape the architecture.

---

## The Progression: Simple to Complex

This chapter is ordered by a combination of data complexity, governance complexity, and stakes. Here's the journey:

**Recipes 5.1 to 5.2 (Simple).** Internal duplicate patient detection within one system, and provider NPI matching against an authoritative registry. Both are constrained problems with controllable inputs and well-understood techniques. Recipe 5.1 is your first stop because every healthcare organization has duplicate patient records sitting in their database right now, and a focused dedup project pays for itself fast (in cleaner reporting, in avoided clinical mistakes, in reclaimed staff time). Recipe 5.2 is similarly tractable: NPI is a real, reliable national identifier (just not for patients), and the registry is queryable. These are your two- to four-month projects, and they build the operational muscle (review queues, threshold tuning, survivorship rules, audit trails) that the harder recipes need.

**Recipe 5.3 (Simple-Medium).** Address standardization and household linkage. Where geography enters the picture. USPS address standardization is a solved problem if you use the right tools, and household inference is a useful extension for outreach and SDOH analysis. The complexity comes from data quality and from being thoughtful about what assumptions you're encoding when you say "these two patients live in the same household" (you might be right about the address and wrong about the relationship).

**Recipes 5.4 to 5.5 (Medium).** Insurance eligibility matching and cross-facility patient matching for health information exchange. Now you're crossing organizational boundaries. No shared identifiers. Different demographic conventions. Real-time performance requirements (eligibility checks happen at point-of-service). Governance layers (HIE consent, BAA, data use agreements) become part of the architecture. Budget a quarter, and make sure your privacy and compliance team is at the table from the scoping phase.

**Recipe 5.6 (Medium-Complex).** Claims-to-clinical data linkage. The headache problem of healthcare analytics: link the administrative trail of a patient's encounter (claims) to the clinical record of that same encounter (EHR data). Different identifiers, timing misalignment, many-to-many relationships, data quality issues on both sides. This is the recipe that powers most outcomes research, most quality measurement, and most value-based care contracting. It's harder than it looks.

**Recipe 5.7 (Complex).** Longitudinal patient matching across name changes. Real-world identity is not stable in time, and your matching system has to handle that without losing data continuity or violating patient autonomy around their own identity. This recipe pulls in temporal logic, history-aware matching, and a sensitivity layer that most entity resolution systems don't have. It's also the recipe most likely to be retrofitted into an existing system, with all the migration complexity that implies.

**Recipe 5.8 (Complex).** Privacy-preserving record linkage. When you can't exchange raw data, you exchange Bloom filters, secure hashes, or computed match keys instead. The cryptographic techniques are well-established (Bloom-filter-based protocols have been in academic literature for over a decade), but operational deployment is still uncommon and the accuracy ceiling is lower than direct matching. The reason this is in the chapter is that the legal and trust frameworks around healthcare data sharing are tightening, not loosening, and you should know what your options are when "send me your data" stops being one of them.

**Recipes 5.9 to 5.10 (Complex).** National-scale patient matching under TEFCA, and deceased patient resolution. Both stretch the operational and governance dimensions to their limits. National-scale matching has to work at populations of hundreds of millions of records across thousands of participating organizations with widely varying data quality, no central authority, and governance frameworks that are still maturing. Deceased patient resolution sounds simpler but isn't: death data sources are heterogeneous, lag months to years, and surface duplicates that nobody noticed. These recipes are in the chapter because they matter, not because most readers should start here.

You can read the chapter in order or jump to the recipe that maps to your immediate problem. If you're new to entity resolution as a practice, recipes 5.1 and 5.2 will build the mental models that make 5.5 onward make sense.

---

## The Techniques You'll See

The recipes pull from several technique families. Quick tour, because the names recur:

**String similarity and normalization.** The foundation. Levenshtein edit distance (number of single-character edits to turn one string into another), Jaro-Winkler (a tweaked variant that weights early-string matches more heavily, which helps for names), Soundex and double metaphone (phonetic encodings that group similar-sounding strings together), n-gram comparisons (overlapping character sequences). None of these is "the right one." Production matchers typically use several in combination. The classic patient-matching trick is to compute Jaro-Winkler on first name, Levenshtein on last name, exact match on DOB, and reasonable string similarity on phone-number-as-string, then feed the scores into a probabilistic combiner.

**Probabilistic record linkage (Fellegi-Sunter).** The 1969 paper that almost everyone cites and almost nobody actually reads in full. The core idea: for each field, estimate the probability that the field matches given that the records refer to the same entity (the "m" probability), and the probability that the field matches given that they don't (the "u" probability). The log-likelihood ratio of those probabilities, summed across fields, gives you a match score. Cleaner than ad-hoc weighted scoring, and the m/u probabilities can be estimated from the data via expectation-maximization. Almost every commercial EMPI is some flavor of this.

**Blocking and candidate generation.** The unspoken constraint of all entity resolution: comparing every record to every other record is O(n²), and at any reasonable scale that's not feasible. Blocking partitions the records into smaller buckets that are then compared internally, dramatically reducing the comparison count. Common blocking keys: first three letters of last name plus year of birth, soundex of last name plus first letter of first name, ZIP code plus last name. Good blocking keys produce small buckets that still contain the true matches; bad blocking keys produce huge buckets or split true matches into separate buckets. Most of the engineering work in a production matcher is in the blocking, not the comparison logic.

**Machine learning classifiers.** Treat the pair of records as a feature vector (similarity scores, demographic deltas, geographic distances, behavioral overlaps), and train a classifier (gradient boosting, deep networks, or transformer-based pair embeddings) to predict match/non-match. Higher accuracy ceiling than purely probabilistic, but requires labeled training data (often produced by clerical review of probabilistic output) and is harder to audit. Increasingly common as the wrapper around a probabilistic core.

**Embedding-based matching.** Represent strings or records as dense vectors in a learned space, and match based on vector proximity. Particularly useful when the data is messy in ways that string-similarity heuristics don't capture (transliteration variations, abbreviations, semantic equivalents). Also relevant for matching unstructured fields, like comparing a free-text "reason for visit" string to a structured diagnosis code. Bedrock's text embedding models, sentence transformers, and domain-specific models all live here.

**Cryptographic and privacy-preserving methods.** Bloom-filter-based matching, secure hash chains, secure multi-party computation, differential privacy. Used when raw demographic data can't be exchanged. Recipe 5.8 is the one that goes deep on these; the others touch them lightly when applicable.

**Graph and network methods.** When the entity resolution problem has natural relational structure (provider-patient-claim graphs, patient-household graphs), graph-based clustering can find communities of related records that pairwise comparison misses. Useful for fraud-ring detection (which spans into Chapter 3 territory) and for resolving complex many-to-many relationships in claims-to-clinical linkage.

You don't need all of these for any one recipe. You do need to recognize them when you see them, because the technique family drives the architecture and the failure modes.

---

## Key Architectural Patterns You'll See Repeatedly

A few patterns compound across the chapter. Calling them out here saves repetition later:

**The match-score-plus-review-queue pattern.** Almost every recipe ends with a three-bucket output: auto-match (above the high threshold), auto-non-match (below the low threshold), and human-review (everything in between). The thresholds are tunable and explicit. The review queue is where most of the recipe's operational work lives: prioritization, workflow integration, decision capture, feedback into model retraining. A matcher without a review queue is incomplete; the review queue *is* the product, often more than the score is.

**Survivorship rules.** When you decide two records are the same and need to merge them, which fields win? Most-recent? Most-trusted source? Longest non-null? A combination per field? Survivorship is unglamorous and absolutely critical, because the merged record is what downstream systems consume. Wrong survivorship rules can lose clinically significant data even when the match itself was correct. The recipes flag where survivorship needs explicit design.

**Master Patient Index (MPI) / Enterprise Master Patient Index (EMPI).** The name for the data structure that holds the "this set of source records is the same person" relationships. An internal MPI lives within one organization. An EMPI links across organizations, often with cross-references back to source-system identifiers. Recipe 5.5 onward generally assumes some flavor of MPI or EMPI exists or is being built. The recipe explains the structure where it matters; the term itself just means "the place we store the resolved identity decisions."

**Audit trails and reversibility.** Every match decision (especially every merge) needs to be reversible. Wrong merges happen, and when they do, you need to be able to unmerge cleanly without losing data. That requires storing, for each merged record, a complete history of where it came from, who or what decided to merge it, and what the source-system identifiers were before the merge. This is not optional. The compliance, legal, and patient-safety implications of a non-reversible merge are large enough that "we'll add audit later" is the wrong answer.

**Real-time vs. batch matching.** Some recipes need to answer "is this person already in our system?" in milliseconds at point of registration. Others can run nightly batch jobs to find and queue duplicates for review. The architecture differs significantly. Real-time matching usually requires precomputed blocking indices, in-memory probabilistic scoring, and a cap on candidate set size. Batch can be more thorough, run more techniques, and afford to look at every pair in a block.

**Feedback loops and continuous improvement.** Every match reviewed by a human generates a label that should flow back into model retraining or threshold tuning. Without that loop, the matcher's accuracy decays over time as data conventions drift. The recipes treat the feedback loop as a first-class component, not an optional add-on.

**Confidence-aware downstream consumption.** Match decisions carry confidence levels. Downstream systems should know what confidence they're consuming. A care coordination workflow can comfortably act on auto-matches; a billing reconciliation workflow might require manual approval for borderline matches; a research dataset might need to exclude any match below a configurable threshold. The architectures pass confidence through, rather than collapsing every decision to a binary.

---

## Healthcare-Specific Considerations

Beyond the patterns, a few considerations recur:

**PHI is the input and the output.** Demographic data is PHI. Match logs are PHI. The reviewer interface displays PHI. Every BAA, encryption, audit, and access control concern from earlier chapters applies. Specifically for entity resolution: the review queue is a high-PHI-density artifact, and the people staffing it (often called health information management or HIM staff) need appropriate role-based access and audit logging on every decision.

**Bias in matching is a documented equity issue.** Patient matching accuracy is not uniform across populations. Names from naming conventions outside the dominant culture (Hispanic surnames with multiple components, Asian names with order variations, Arabic names with transliteration variations) match worse on average than dominant-culture names, because the standard string-similarity heuristics were tuned on the dominant-culture cases. Address-based matching works worse for housing-insecure populations. Phone-based matching works worse for low-income populations who change numbers more often. <!-- TODO: verify specific equity citations; ONC, RAND, and Pew have published on patient matching disparities, with documented accuracy gaps across demographic groups --> Every complex recipe in this chapter notes where these disparities show up and what monitoring is needed.

**Consent and information-sharing rules vary by context.** A patient who consented to be matched within their primary health system has not necessarily consented to being matched into a regional HIE, a research dataset, or a national framework. Some matching is permitted under treatment, payment, or operations exceptions; some requires explicit consent; some requires consent that can be revoked. The recipes flag where these legal questions enter, but your privacy office and legal counsel are the authoritative source.

**The 21st Century Cures Act and information blocking.** The legal landscape for healthcare data sharing has shifted: organizations are now legally required to share patient data on request, with specific exceptions, under information blocking rules. That changes the calculus for entity resolution. Refusing to match is harder to defend than it used to be. Conversely, sharing with poor matching quality can create harm. The architectures need to support the obligation to share without blowing past the obligation to share accurately.

**TEFCA and the maturing national infrastructure.** The Trusted Exchange Framework and Common Agreement is the closest the United States has gotten to a national health data exchange framework. Recipe 5.9 covers it specifically. As of writing, the operational rollout is still in progress and the patient matching standards within TEFCA are evolving. Build to the current standard, but architect for change.

**Identity sensitivity and dignity.** Patient matching touches things that are deeply personal: names, gender, sex assigned at birth, relationship status, address. The systems that handle this data need to do so with dignity, not just compliance. A patient who has changed their name and gender should not have their old identity surfaced unnecessarily, even if the matcher needs it internally for historical record linkage. The recipes that touch this (5.7 specifically, but also 5.5 and 5.9 in more general terms) include design considerations for how to keep the historical match without exposing the identity transition to anyone who doesn't need it.

---

## What You'll Build

By the end of this chapter, you'll have patterns for:

- Finding and merging duplicate patient records within your own database, with the audit and review infrastructure that makes those merges safe
- Matching provider records to NPI registry entries for credentialing, directory accuracy, and regulatory reporting
- Standardizing addresses and inferring household relationships for outreach, social determinant analysis, and care coordination
- Verifying insurance eligibility in real time when payer demographics don't quite match your records
- Linking patient records across unaffiliated facilities for health information exchange and care continuity
- Joining administrative claims data to clinical EHR data for the same patient and encounter, enabling outcomes research and quality measurement
- Maintaining patient identity continuity across name changes over multi-year timeframes, without losing history or violating patient autonomy
- Matching records across organizational boundaries without sharing raw demographic data, using cryptographic and statistical privacy-preserving techniques
- Operating patient matching at national scale through TEFCA-like frameworks, with the governance and quality monitoring that scale demands
- Reconciling deceased patient records across vital statistics sources, surfacing previously hidden duplicates and closing longitudinal records appropriately

Each recipe is self-contained, but the infrastructure compounds. The blocking indices, similarity functions, probabilistic combiner, review queue, and audit trail you build for recipe 5.1 are directly reusable for 5.5 and 5.7. The privacy and consent patterns from 5.5 carry into 5.8 and 5.9. Treat the early recipes as capability investments, not just point solutions; the later ones will be faster, safer, and cheaper because of them.

One last thing before we dive in: entity resolution is a problem that is never finished. The data keeps coming, the people keep changing, and the systems keep evolving. Treat it as ongoing operational work rather than a project that completes. The organizations that do entity resolution well have a team that owns it, monitors it, and improves it continuously. The organizations that treat it as a one-time data cleanup are the organizations that, three years later, are doing the cleanup again, with worse data and harder problems.

Alright. Let's figure out who's who.

---

*→ [Recipe 5.1: Internal Duplicate Patient Detection](chapter05.01-internal-duplicate-patient-detection)*
