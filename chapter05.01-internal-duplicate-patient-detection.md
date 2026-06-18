# Recipe 5.1: Internal Duplicate Patient Detection ⭐

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.001-0.01 per record-pair scored (depends on blocking efficiency, similarity-function complexity, and review-queue volume)

---

## The Problem

Pull up the medical records system at any reasonably-sized health system tomorrow morning and search for a common name. Maria Garcia. John Smith. Jennifer Lee. You will get hits. A lot of hits. Some of those hits are different people who happen to share a name (which, for "John Smith," should not surprise anyone). Some of them are the same person who was registered three different times by three different front-desk staff who each spelled the name slightly differently, used a different format for the date of birth, or didn't ask for an SSN this time.

Now zoom in on one of those hypothetical Maria Garcias. Maria came in for a sprained ankle in 2018, registered as Maria E Garcia, born 03/14/1972, with a phone number she has since changed. She came back in 2021 for a mammogram, registered as Maria Garcia (no middle initial), DOB 3-14-72, with her current phone. She came back last month for a primary care intake, registered as Maria Garcia-Lopez (her married name, finally added to the system), DOB March 14 1972, current phone. From the database's perspective, that is three patients. Three medical record numbers. Three problem lists. Three medication lists. Three sets of allergies. Three separate insurance records. Three separate streams of clinical history that nobody has connected.

Last week Maria came in for an acute issue and the clinician saw the chart from the 2021 visit because that was the one the registration clerk pulled up. The chart didn't show the medication she was started on by the primary care doctor last month. It also didn't show the allergy that was documented at that intake. The clinician prescribed something that interacted with the new medication. Maria had a moderate adverse reaction. Nobody died, but somebody is going to be having a serious quality-and-safety conversation about it next week.

This is what duplicate patient records do. They are not, as the IT department sometimes tries to frame it, a data quality nuisance. They are a patient safety hazard with documented clinical consequences. The Joint Commission has flagged patient identification as a top patient safety concern essentially every year for the last two decades. ECRI Institute regularly lists wrong-patient errors in its top ten patient safety hazards. <!-- TODO: verify the most recent Joint Commission National Patient Safety Goals and ECRI Top 10 Patient Safety Concerns reports at time of build; the patient identification theme has been consistent but specific years and rankings shift. --> The cost shows up in adverse drug events, repeated lab tests because the result from last visit isn't visible, missed care gaps because the screening was done on the other chart, denied claims because the insurance is on yet another record, and a steady drip of staff time spent reconciling things at the desk while patients wait.

The other thing duplicate records do is silently inflate every metric the organization reports. The patient count is wrong. The unique-patient denominators in HEDIS measures are wrong. The cohort sizes in any analytics work are wrong. The marketing list has duplicates. The patient portal sends three reminders to the same person who just clicks delete and wonders why their primary care provider is so disorganized. The financial reconciliation routinely finds the same human being with three open balances on three accounts. None of this is rare. Most healthcare organizations carry duplicate rates somewhere in the 5 to 15 percent range within a single system, with substantially higher rates across organizations. <!-- TODO: verify duplicate rate ranges; commonly-cited figures from ONC, AHIMA, and EMPI vendor literature put within-system duplicates at 5-15% for typical health systems and as high as 20-30% in poorly-maintained or recently-merged systems. -->

The good news, and the reason this is the first recipe in the chapter, is that duplicate patient detection within a single system is the most tractable entity-resolution problem in healthcare. You have one source. You control the field formats. You can tune aggressively because the merge action is gated by human review. The techniques are well-understood. The tools have been around for decades. Most organizations could be doing this and aren't, or are doing it once-a-year as a manual cleanup project that gets behind the moment it ends.

This recipe builds the always-on version. Every new registration gets compared against the existing database. Suspected duplicates get queued for review. Known matches get merged with full audit and reversibility. The blocking, similarity, and probabilistic scoring infrastructure you build here becomes the foundation that every other recipe in this chapter reuses. If you read only one recipe in Chapter 5, read this one. It is the cheapest way to make the rest of the chapter cheaper.

Let's get into how you build it.

---

## The Technology: How You Decide Two Records Are the Same Person

### The Core Problem, Stated Plainly

You have a database of patient records. Each record has demographic fields: name, date of birth, sex, address, phone, sometimes SSN, sometimes a previous medical record number. You want to find every pair of records in the database that refers to the same real-world person, decide which pairs are confident enough to auto-merge, decide which pairs need human review, and let the rest stay as distinct patients.

Stated that way, the problem looks like a join. It is not. A join requires a key that is identical when the records refer to the same entity. You do not have one. The closest thing to a shared key in healthcare patient data is the SSN, and SSNs are missing on most records, mistyped on a meaningful fraction, and increasingly not collected at all due to identity theft concerns. Names get misspelled. Dates of birth get fat-fingered. Phone numbers change. Addresses change. Suffixes drop. Nicknames substitute for legal first names. The data you would join on is too noisy for an exact-match join to find most of the duplicates.

So you do not join. You compare pairs of records, score how similar they are, and decide which pairs are similar enough to be the same person. That sounds simple. Several things make it hard.

### The Scaling Wall

If you have a million patient records and you want to compare every pair, that is roughly 500 billion comparisons. At a microsecond per comparison (optimistic), that is about six days of compute. At a millisecond per comparison (realistic with string-similarity functions), that is sixteen years. You cannot compare every pair. You have to be selective about which pairs you bother to compare.

The technique for being selective is called **blocking**. The idea: partition the records into smaller groups (blocks) such that records within a block are plausibly related and records in different blocks are very unlikely to be the same person. Then only compare pairs within each block. A block keyed on (first three letters of last name, year of birth) takes a million records and breaks them into thousands of small blocks. Comparisons within each block are tractable. The trick is picking blocking keys that are loose enough to keep true duplicates in the same block (so you find them) and tight enough to keep block sizes manageable (so the comparisons are feasible).

No single blocking key works for everything. A patient whose last name was misspelled in one record but not the other will not land in the same block under a last-name-based key. So production systems use **multiple blocking passes**: pass one blocks on (last name initial, DOB), pass two blocks on (soundex of last name, ZIP code), pass three blocks on (first name, last name initial, year of birth), and so on. Any pair that lands in the same block in any pass becomes a candidate for comparison. The union across passes is the candidate set; the goal is high recall (we want to catch true duplicates) at acceptable block-size cost.

Designing the blocking strategy is the single most consequential engineering decision in the whole pipeline. Bad blocking misses real duplicates and you never know. Good blocking finds candidates efficiently and lets the downstream comparison logic do its job. Most production matchers spend more engineering effort on blocking than on the comparison logic itself.

### String Similarity, the Heart of the Matter

Once you have a candidate pair, you need to score how similar the two records are. Most of that work comes down to comparing strings: comparing two first names, two last names, two addresses, two phone numbers. Several string-similarity functions show up in nearly every patient-matching system, each useful for different things:

**Edit distance (Levenshtein).** The minimum number of single-character insertions, deletions, or substitutions to turn one string into another. "Garcia" to "Gracia" is one substitution and one insertion, edit distance 2. Edit distance is symmetric and intuitive. It is most useful for catching typos and minor spelling variations. It is less useful for catching transpositions of word order or large-scale reformatting.

**Jaro-Winkler.** A specialized similarity score for short strings, particularly names. It scores matches based on the number of matching characters and the number of transpositions, with extra weight given to characters that match at the start of the strings. The "Winkler" part is the prefix bonus. Jaro-Winkler tends to outperform plain edit distance on first-name and last-name comparisons because human names tend to have informative prefixes. "Maria" and "Marie" score high on Jaro-Winkler. So do "John" and "Jon."

**Soundex and double metaphone.** Phonetic encoders. They reduce a string to a code that approximates how it sounds. Names that sound similar produce the same code. Soundex is the older, simpler one (it produces codes like S530 for "Smith"). Double metaphone is the more modern, more accurate one. Phonetic encoders are how you catch "Catherine" matching "Katherine" and "Smith" matching "Smyth." They are also how you generate excellent blocking keys.

**N-gram overlap (Jaccard).** Break each string into overlapping character sequences (typically 2-grams or 3-grams), then compute the overlap as a fraction of the union. Useful for longer fields like addresses where partial matches are common and where the comparison should be insensitive to word order.

**Damerau-Levenshtein.** A variant of edit distance that also counts adjacent-character transposition as a single edit. "Garica" to "Garcia" becomes one transposition rather than two substitutions. Damerau-Levenshtein matches human typo patterns better than plain Levenshtein.

You do not pick one of these and call it done. You pick the right one for each field. Jaro-Winkler on first name. Damerau-Levenshtein on last name. Phonetic encoding (double metaphone) for blocking and as an additional tie-breaker. Token-based comparison on multi-word fields. Exact-match-with-typo-tolerance on numeric fields like phone and DOB. Each field gets its own similarity treatment, because the failure modes are different.

### Probabilistic Record Linkage: How You Combine the Field Scores

Once you have similarity scores per field, you need to combine them into a single match decision. Naive approaches (sum the scores, weighted average) work badly because they do not account for the **information value** of each field. A perfect match on an SSN is far more informative than a perfect match on a first name, because SSN collisions are rare and first-name collisions are common. A mismatch on DOB is far more informative than a mismatch on phone, because DOB rarely changes legitimately and phone numbers do.

The classical framework for combining field scores is **probabilistic record linkage**, formalized by Fellegi and Sunter in 1969. The intuition is straightforward. For each field, you estimate two probabilities:

- **m-probability:** The probability that this field matches given that the two records are about the same person. m is high for stable, accurately-recorded fields (DOB) and lower for fields that change or have data-quality issues (phone, address).
- **u-probability:** The probability that this field matches given that the two records are about different people. u is essentially the population-frequency of the value. u is high for common names and low for rare names. u is high for common ZIP codes and low for rare ones.

The log-likelihood ratio for an observed field comparison is `log(m / u)` for a match and `log((1-m) / (1-u))` for a non-match. Sum these log-ratios across fields and you have a single match score. High scores mean the records are likely to be the same person; low scores mean they are likely to be different people. The threshold-setting is straightforward: pick a high threshold above which everything is auto-matched, a low threshold below which everything is auto-rejected, and a middle band for human review.

Two things make Fellegi-Sunter the workhorse it has been for fifty years. First, the m and u probabilities can be estimated directly from the data using **expectation-maximization** (EM). You do not need labeled training data. The algorithm bootstraps from the observed field-comparison patterns under the assumption that the dataset contains a mixture of matches and non-matches. Second, the resulting scores are **interpretable**. You can show a stakeholder why a particular pair scored high (this field matched and was rare in the population, that field matched and was rare in the population, the DOB field matched exactly), and the reasoning is the same reasoning a human would use. That interpretability matters enormously when you are presenting borderline cases to a clinical data steward for review and when you are defending the system to compliance or audit.

You will see references to other methods (gradient-boosted trees, neural networks, transformer-based pair embeddings) in modern entity-resolution literature. They have a place. For internal duplicate detection in a single system, where the data quality is reasonable and the volume is manageable, probabilistic record linkage is still the right starting point. It is well-understood, easy to tune, easy to audit, and produces results that hold up in front of a data steward. ML-based approaches are useful when probabilistic linkage hits a ceiling, particularly in cross-organization matching with messier data. For Recipe 5.1, build the probabilistic core first.

### The Three-Bucket Output

A duplicate-detection system never outputs "match" or "no match" for every pair. It outputs three buckets:

**Auto-match.** Score above the high threshold. The system is confident enough to merge without human review. In practice, most teams reserve auto-match for very obvious cases: identical name, identical DOB, identical SSN, identical address; or a missing-SSN equivalent with a strong-evidence combination. Even auto-match should produce an audit trail and a reversibility path, because the system is going to be wrong sometimes and you need to be able to back out a wrong merge cleanly.

**Auto-non-match.** Score below the low threshold. The system is confident the records are different people. No action.

**Human review.** Score in the middle band. A human (typically a Health Information Management or HIM specialist) looks at the pair, decides match or not, and applies the merge or marks the pair as a known non-match so the system stops surfacing it. The review queue is where most of the operational work lives. The review queue is the product, often more than the score is.

The thresholds are tunable. They are not set by the engineer; they are set by clinical leadership in conversation with the HIM team, balancing the cost of false merges (a patient safety hazard) against the cost of false splits (missing a real duplicate, leaving a fragmented record). Most healthcare systems set the thresholds conservatively (favor false splits over false merges) because the patient safety asymmetry is real. The resulting auto-match rate is typically 30 to 60 percent of true duplicates, with the rest going to review. That review queue is real, ongoing work, and budgeting for it is part of the project.

### Survivorship: After You Decide to Merge, Which Fields Win?

This is the unglamorous half of duplicate detection that most write-ups skip. When you merge two records, the merged record needs concrete field values. Which name? Which address? Which phone number? Which insurance? Which problem list?

The answer is **survivorship rules**, a set of per-field policies that decide which source-record value wins. Common rules:

- **Most recent.** For fields that change over time (address, phone, insurance), take the most recently updated value. The patient probably moved.
- **Most trusted source.** For fields that vary by data quality across registration channels (legal name, SSN), prefer values from sources known to be more reliable.
- **Longest non-null.** For free-text fields (name suffix, middle name), prefer the source that actually has a value over the one that does not.
- **Combine rather than overwrite.** For lists (problem list, medication list, allergy list, insurance list), do not pick one; merge them with deduplication. The merged record contains the union of the source-record clinical histories.
- **Manual review for sensitive fields.** For things like preferred name, gender, sex assigned at birth, contact preferences, the right answer is sometimes "ask the patient," not "let the algorithm pick."

Survivorship is unglamorous but absolutely critical. The merged record is what downstream systems consume. Wrong survivorship rules can lose clinically significant data even when the match itself was correct. ("We merged correctly, but the merge picked the older address because the timestamp was wrong, and now her appointment letter is going to her last apartment.") The project plan needs to allocate explicit time for the survivorship-rule design, with HIM and clinical informatics involvement, and the rules need to be reviewed and adjusted as patterns emerge.

### Reversibility: Wrong Merges Are Going to Happen

Even with conservative thresholds and human review, some merges will be wrong. A clinician or a data steward will eventually look at a chart and say "wait, this is two different people." When that happens, you need to be able to **unmerge** the records cleanly. That means: every merge stores the source-record provenance, the source-system identifiers, the merge timestamp, the merge operator (human or system), the score that drove the merge, and a complete history of the field-level survivorship decisions. Unmerge restores the source records to their pre-merge state and records the unmerge as a reversible action.

You cannot bolt this on later. The data structures need to support reversibility from day one, because once you have done a year of merges without provenance, the reverse-engineering is painful and lossy. The compliance, legal, and patient-safety implications of a non-reversible merge are large enough that "we'll add audit later" is the wrong answer.

### Where the Field Has Moved

A few practical updates worth knowing:

- **Open-source tooling is mature.** Libraries like Splink, dedupe, recordlinkage, and Zingg have made probabilistic record linkage broadly accessible. Splink in particular has a strong reputation for healthcare-scale workloads and produces interpretable Fellegi-Sunter outputs with EM-based parameter estimation. <!-- TODO: confirm current state of these libraries; Splink (Robin Linacre / UK government) is well-maintained and healthcare-applicable; dedupe.io is mature; recordlinkage (Python) is academically well-grounded; Zingg supports record linkage and resolution at scale. -->
- **EMPI vendors implement the same patterns.** Commercial enterprise master patient index products (Verato, NextGate, IBM Initiate, and others) implement variants of the same Fellegi-Sunter probabilistic linkage with proprietary tuning. They are reasonable choices when the operational support and pre-built integrations are worth the license cost. The architecture in this recipe applies whether you are building or buying; "buying" still requires you to design the review queue, the survivorship rules, and the audit trail around the vendor product.
- **Embeddings are starting to show up.** Recent work uses learned string embeddings (sentence transformers, character-level models) as additional similarity features in the Fellegi-Sunter framework. Useful for handling transliteration, abbreviation, and complex naming conventions. Not a replacement for the probabilistic core; an enhancement layer.
- **Bias monitoring has become standard practice.** Patient-matching accuracy is not uniform across populations. Names from naming conventions outside the dominant culture (Hispanic surnames with multiple components, Asian names with order variations, Arabic names with transliteration variations) match worse on average. Address-based matching works worse for housing-insecure populations. The recipes in this chapter, including this one, monitor cohort-stratified match rates and false-positive rates as a first-class concern, not a bolt-on.

---

## General Architecture Pattern

The pipeline has five logical stages: ingest and normalize the source records, generate candidate pairs through blocking, score the pairs with similarity functions and the probabilistic combiner, route the scored pairs to auto-action or human review, and persist the resolved identity decisions with full audit and reversibility.

```text
┌────────────── INGEST AND NORMALIZE ───────────────┐
│                                                    │
│  [Source Patient Records (registration system)]    │
│           │                                        │
│           ▼                                        │
│  [Field-level normalization:                       │
│   - Names: case-fold, trim, strip diacritics,      │
│     handle suffixes, expand nicknames]             │
│   - Dates: parse to canonical form, validate]      │
│   - Addresses: USPS-standardize where possible]    │
│   - Phones: strip formatting to E.164]             │
│   - SSNs: strip formatting, validate length]       │
│           │                                        │
│           ▼                                        │
│  [Phonetic encoding (double metaphone) for         │
│   names; precompute for use as blocking keys]      │
│           │                                        │
│           ▼                                        │
│  [Persist normalized records with provenance]      │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── BLOCKING / CANDIDATE GENERATION ─────┐
│                                                    │
│  [Normalized Records]                              │
│           │                                        │
│           ▼                                        │
│  [Multiple blocking passes:                        │
│   pass 1: (last_name_metaphone, dob_year)         │
│   pass 2: (first_name_metaphone, last_initial,    │
│            dob_year)                               │
│   pass 3: (last_name_initial, dob_full)           │
│   pass 4: (zip_code, last_name_initial)           │
│   pass 5: (phone_last_4, dob_year)                │
│   ...add passes as needed for recall]             │
│           │                                        │
│           ▼                                        │
│  [Candidate pair set = union across passes]       │
│           │                                        │
│           ▼                                        │
│  [Deduplicate candidate pairs (a pair matched     │
│   in multiple passes is still one pair)]          │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── SCORE CANDIDATE PAIRS ──────────────┐
│                                                    │
│  [Candidate pairs]                                 │
│           │                                        │
│           ▼                                        │
│  [Per-field comparison:                            │
│   - first_name: Jaro-Winkler                       │
│   - last_name: Damerau-Levenshtein + metaphone    │
│   - dob: exact / one-digit / month-day-swap       │
│   - sex: exact / null-aware                       │
│   - address: token-based + USPS-standardized      │
│   - phone: exact on last-7 / last-4               │
│   - ssn: exact / one-digit                        │
│   - email: exact / case-insensitive               │
│           │                                        │
│           ▼                                        │
│  [Probabilistic combiner (Fellegi-Sunter):         │
│   - Per-field m and u probabilities (estimated     │
│     from data via EM)                              │
│   - Sum per-field log-likelihood ratios            │
│   - Output: composite match score]                │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── ROUTE BY THRESHOLD ─────────────────┐
│                                                    │
│  [Composite match score]                           │
│           │                                        │
│           ▼                                        │
│  [Score >= HIGH_THRESHOLD?]                        │
│      ├── Yes → AUTO-MATCH path                     │
│      └── No                                        │
│            │                                       │
│            ▼                                       │
│      [Score <= LOW_THRESHOLD?]                     │
│          ├── Yes → AUTO-NON-MATCH (no action)     │
│          └── No → REVIEW QUEUE                    │
│                     │                              │
│                     ▼                              │
│             [HIM specialist review:                │
│              match / not-match / not-sure]        │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── PERSIST WITH AUDIT ─────────────────┐
│                                                    │
│  [Match decision (auto or human)]                  │
│           │                                        │
│           ▼                                        │
│  [Apply survivorship rules per field]             │
│           │                                        │
│           ▼                                        │
│  [Write to MPI:                                    │
│   - Master patient identity (golden record)       │
│   - Cross-references to source records            │
│   - Merge provenance: source IDs, timestamps,     │
│     operator, score, field-level survivorship     │
│     decisions]                                    │
│           │                                        │
│           ▼                                        │
│  [Emit merge event to downstream consumers]       │
│           │                                        │
│           ▼                                        │
│  [Update similarity-feedback labels for           │
│   model retraining (m and u probability           │
│   refinement)]                                    │
│                                                    │
└────────────────────────────────────────────────────┘
```

**Ingest and normalize is where most of the recall comes from.** The single most underrated technique in patient matching is aggressive normalization before any comparison happens. A name field stored as "  María  E.  García-López " becomes the canonical form "maria garcia-lopez" (or with the diacritics preserved, depending on locale strategy). A DOB stored as "3/14/72" becomes "1972-03-14" after parsing and century-windowing. A phone stored as "(555) 123-4567 ext 89" becomes "+15551234567x89" or just "5551234567" depending on how you treat extensions. A nickname-to-legal-name dictionary expands "Bob" to also match "Robert." Addresses go through USPS-standardization (CASS-certified products like SmartyStreets, Melissa, or the USPS API), which produces a canonical form that handles abbreviations, ZIP+4, apartment numbering, and the dozen ways "Saint" can appear in a street name. None of this is glamorous. All of it dramatically improves matching accuracy. Every hour spent on normalization saves multiple hours of debugging false negatives downstream.

**Blocking is the recall-vs-cost knob.** Multiple blocking passes increase recall at the cost of more candidate pairs to score. Tighter blocking keys reduce candidate count at the cost of missing some real duplicates. The right answer is empirical: pick an initial set of passes, measure recall against a labeled gold set, add or tighten passes until recall is acceptable, and accept the resulting candidate count. For a million-record system, a well-designed blocking strategy typically produces a candidate-pair count in the low millions, which is tractable on commodity infrastructure.

**Scoring is the core that everything else hangs from.** The per-field comparators are mostly off-the-shelf (Jaro-Winkler, Damerau-Levenshtein, metaphone). The Fellegi-Sunter combiner is mostly off-the-shelf (Splink, dedupe, recordlinkage). The work is in tuning the m and u probabilities to your data, validating the resulting scores against a labeled gold set, and adjusting the comparators for any field-specific quirks (like dates that are commonly entered with month and day swapped).

**The review queue is the operational core.** Building a great score is one job. Building a queue that lets a small HIM team work through hundreds of candidate matches per day without burning out is a different job, and it is the job that determines whether the system actually clears duplicates over time. A good review queue presents the two records side by side with the matching fields highlighted, the differing fields highlighted, the composite score shown with the contributing per-field scores, the option to merge / not-match / not-sure / escalate, and a single-keystroke advance to the next item. Bad review queues (multi-page forms, unclear scores, no way to bulk-process obvious clusters) produce reviewer fatigue, inconsistent decisions, and a backlog that grows faster than it shrinks.

**Audit and reversibility are baked in, not added later.** Every merge stores the full provenance. Every unmerge is recorded as a reversible action. The audit log is queryable, immutable, and retained per the institution's records-retention policy (which for clinical records is typically several years to decades, depending on jurisdiction).

**Cohort-stratified accuracy monitoring is part of the system, not an afterthought.** Compute and report match rate, false-positive rate, and review queue depth by demographic cohort (race, ethnicity, language, age band, geographic region, primary-language). Significant disparities (worse match rate for Hispanic patients than non-Hispanic, for example) are signals that the comparators or the m/u probabilities are not generalizing across populations and need cohort-specific tuning. This is a Chapter 5 chapter-wide pattern; it shows up in every recipe and starts here.

<!-- TODO (TechWriter): Expert review A2 (HIGH). Specify the cohort-disparity alert thresholds and metric definitions explicitly: per-cohort recall ratio (worst vs best), auto-match precision ratio, post-merge unmerge rate ratio, and review-queue depth-per-FTE ratio, with example threshold values (e.g., MATCH_RATE_DISPARITY_THRESHOLD = 0.10), per-axis override mechanism via the equity-review committee, chronic-suppression-as-fairness-signal pattern when cohort sample size falls below MIN_COHORT_SAMPLE_SIZE, cohort-stratified gold-set construction discipline, and the documented diagnose-and-address workflow that fires when an alert crosses threshold. Reference Recipe 4.8 Finding A4, 4.9 Finding A2, 4.10 Finding A1 as chapter pattern. -->

<!-- TODO (TechWriter): Expert review A3 (HIGH). Add a "no-link flags" architectural primitive. Specify a `no_link_flags` table keyed on (mpi_id_or_record_id, flag_type) covering safety-sensitive populations: address_confidentiality_program (state ACP / Safe at Home), witness_protection (federal Witness Security), adoption_sealed, patient_requested_separation (gender transition, protected name change), care_segmentation (42 CFR Part 2 SUD, behavioral health), family_relationship_explicit (twin, parent-infant), and no_link_pairwise. The pipeline must consult these flags at candidate generation (filter), threshold routing (auto-match path bypassed for any pair containing a flagged record; route to privacy-office restricted-review track), and review-queue assignment (separate restricted queue). Flags are write-protected to privacy-office and HIM-leadership roles, with separate-key encryption. The chapter editor should consider promoting to chapter preface since 5.5, 5.7, 5.9 inherit the same concern. -->

<!-- TODO (TechWriter): Expert review A11 (LOW). Architect the family-aware blocking pass (sibling to A3): consult `no_link_flags` for `family_relationship_explicit` to skip comparison of explicitly-flagged sibling pairs and down-weight comparator scores on shared-family fields. -->

<!-- TODO (TechWriter): Expert review S3 (LOW). When emitting cohort dimensions on CloudWatch metrics, use bucketed non-reversible cohort labels (cohort_race_eth_bucket = A, B, C, D, E, unknown) rather than raw demographic attributes; the cohort-label-to-attribute mapping lives in a separate access-controlled table loaded only at dashboard-render time. Same chapter pattern as Recipe 4.4 Finding 13 / 4.10 Finding S4. -->

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter05.01-architecture). The Python example is linked from there.

## The Honest Take

Internal duplicate patient detection is the recipe in Chapter 5 with the highest payoff-per-engineering-hour ratio. The infrastructure compounds for every later recipe in the chapter: the blocking, the comparators, the probabilistic combiner, the review queue, the survivorship rules, and the audit trail you build here are directly reused in 5.5 (cross-facility matching), 5.6 (claims-to-clinical), 5.7 (longitudinal across name changes), and the rest. If you read only one recipe in this chapter, this is the one. If you build only one recipe in this chapter, this is the one. The duplicate rate in the source database is silently costing the organization money and patient safety every day, and the project to fix it pays for itself in months in most cases.

The trap most specific to this domain is treating it as a one-time cleanup project rather than as ongoing operational work. The "let's hire a contractor to clean up the duplicates over the summer" approach is real, common, and a money pit. The duplicates regenerate. The patient base grows. The registration practices vary across new staff. Twelve months after the cleanup contractor leaves, the duplicate rate is back to where it was, the matcher infrastructure has been turned off because nobody owns it, and the next cleanup project starts from scratch. The pattern that works is treating the matcher as a permanent operational system with a permanent owning team (typically HIM with engineering support), a permanent review queue, and a permanent monitoring dashboard. The one-time cleanup is the backfill; the ongoing operation is the system.

A second trap, related: under-investing in the review queue UX and the HIM team that staffs it. Engineering teams default to investing in the algorithm and underinvesting in the human-in-the-loop surface. The review queue is where the decisions happen. A bad review queue produces inconsistent decisions, reviewer burnout, and a backlog that grows. A great review queue is the difference between a matcher that earns its keep and a matcher that gets quietly turned off. The review queue is not a sidebar; it is the product. Allocate engineering and design time accordingly.

The third trap, and the one most specific to healthcare: setting the auto-match threshold too aggressively. The patient-safety asymmetry is real. A wrong merge mixes two people's clinical information, and the consequences include adverse drug events, missed diagnoses, and wrong-patient procedures. A missed match keeps the records fragmented, which has real costs (repeated tests, missed history) but rarely an acute safety event. Conservative thresholds (favor false splits over false merges) are the right starting position. The pressure to relax the thresholds will come from the operational team that wants the review queue smaller, and the right answer is almost always to staff the review queue at the level the threshold demands rather than to lower the threshold to fit available staffing. There is a population of real duplicates the matcher will catch only with conservative thresholds and adequate review staffing; cutting the staffing is the same as accepting that those duplicates will not be found.

The thing that surprises people coming from generic data-deduplication backgrounds is the centrality of the survivorship rules. In customer-database deduplication, getting the merge "right" is mostly about picking the right name and address. In patient-record deduplication, the merge has to combine clinical histories, medication lists, allergy lists, problem lists, and insurance records in ways that preserve clinically significant information without producing a record that is just a confusing concatenation of two source records. Survivorship rules need clinical informatics input and ongoing review. The first version of the rules will have flaws that surface when clinicians start consuming the merged records; budget time for iteration.

The thing about the equity dimension: Hispanic and other naming-convention-diverse patients match worse on average than dominant-culture patients in essentially every off-the-shelf system. The cohort-stratified accuracy monitoring will show this. The fix is per-cohort comparator tuning (Hispanic surnames need component-aware comparison, not whole-string Damerau-Levenshtein), supplementary blocking passes (block on the paternal-surname-only pattern in addition to the combined surname pattern), and HIM-team training on culturally-specific name handling. Without this work, the matcher's accuracy gap perpetuates the operational and safety inequities it is supposed to be fixing. With this work, the gap can be substantially closed. This is not optional in 2026; it is the standard.

The thing I would do differently the second time: invest more in the upstream registration-desk data-quality work in parallel with the matcher build. The matcher is a downstream system that compensates for upstream data quality issues. Every percentage-point improvement in DOB capture at the registration desk reduces the matcher's load by more than a percentage point, because the marginal records that lacked DOB are also typically the records that lacked other identifying fields, so the gain compounds. The two projects (registration data quality, matcher build) reinforce each other; running them sequentially leaves value on the table. Plan them together.

Last point, because it is specific to this domain: duplicate patient records are a problem that has been "solved" in the academic literature for thirty years and is still unsolved in production at most healthcare organizations. The gap is not a methods gap. It is an alignment-and-operations gap. The methods (Fellegi-Sunter, blocking, EM, conservative thresholds, human review) are well-understood. The work is in the registration discipline, the threshold setting, the survivorship rules, the review-queue UX, the HIM-team training, the cohort-stratified equity monitoring, and the ongoing operational ownership. Most organizations can build the technical pipeline in three to six months. The thing that takes longer is the operational discipline that makes the pipeline produce good outcomes year after year. Build for that. The pipeline is the easy part.

---

## Related Recipes

- **Recipe 5.2 (Provider NPI Matching):** Sibling Simple-tier recipe; uses similar string-similarity and probabilistic-linkage techniques against the National Provider Identifier registry. The infrastructure (blocking, comparators, review queue) overlaps substantially.
- **Recipe 5.3 (Address Standardization and Household Linkage):** The address-standardization layer in recipe 5.1 is the foundation for 5.3's household-linkage work. The USPS-standardization pipeline carries forward.
- **Recipe 5.4 (Insurance Eligibility Matching):** The matching framework extends to payer-eligibility matching with adjustments for cross-organizational data quality and real-time eligibility-check latency requirements.
- **Recipe 5.5 (Cross-Facility Patient Matching for HIE):** The probabilistic combiner, blocking strategy, and review-queue infrastructure carry forward; the cross-organizational layer adds consent and governance complexity not present in 5.1.
- **Recipe 5.6 (Claims-to-Clinical Data Linkage):** Uses the same matching primitives extended to claims and clinical record linkage with timing-misalignment handling.
- **Recipe 5.7 (Longitudinal Patient Matching Across Name Changes):** Builds on 5.1's framework with explicit history-aware matching and sensitive-identity-change handling.
- **Recipe 5.8 (Privacy-Preserving Record Linkage):** Adds cryptographic layers to the matching primitives developed here for cross-organizational matching without raw-data exchange.
- **Recipe 5.9 (National-Scale Patient Matching, TEFCA):** Extends the patterns to national-scale infrastructure with thousands of participating organizations.
- **Recipe 5.10 (Deceased Patient Resolution):** Combines this recipe's deduplication with mortality-source matching for record reconciliation.
- **Recipe 4.x (Personalization):** A clean MPI directly improves every personalization recipe in Chapter 4 by ensuring patient features are computed against complete, deduplicated histories.
- **Recipe 7.x (Predictive Analytics):** Risk scores computed against a deduplicated patient base are more accurate than scores computed against fragmented records; the dedup is foundational for Chapter 7.
- **Recipe 13.x (Knowledge Graphs):** A clean patient identity is the anchor for any patient-centric knowledge graph; the MPI from this recipe is the entity-resolution layer underneath the graph.

---

## Tags

`entity-resolution` · `record-linkage` · `patient-matching` · `mpi` · `empi` · `deduplication` · `fellegi-sunter` · `probabilistic-linkage` · `blocking` · `string-similarity` · `survivorship` · `equity` · `health-information-management` · `dynamodb` · `opensearch` · `glue` · `splink` · `step-functions` · `lambda` · `simple` · `mvp` · `hipaa`

---

*← [Chapter 5 Preface](chapter05-preface) · Chapter 5 · [Next: Recipe 5.2 - Provider NPI Matching →](chapter05.02-provider-npi-matching)*
