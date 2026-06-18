# Recipe 3.3: Billing Code Anomalies ⭐

**Complexity:** Simple-Medium · **Phase:** MVP · **Estimated Cost:** ~$0.001-0.008 per claim screened (mostly compute; baseline lookups dominate)

---

## The Problem

Picture a payment integrity analyst at a regional payer on a Thursday afternoon. Her dashboard shows 142,000 claims adjudicated this week across roughly 18,000 billing providers. Somewhere inside that pile are patterns that shouldn't be there. A dermatology practice that billed 97110 (therapeutic exercise) on eighty-four claims this quarter, a code that most dermatology practices would bill approximately zero times a year. An internist who, after being flat at two CPT codes per visit for a decade, suddenly jumped to five codes per visit two months ago. A small urgent care in the suburbs where the distribution of evaluation and management levels went from a reasonable-looking bell curve centered at 99213 (level 3) to a distribution that leans almost entirely on 99214 and 99215 (levels 4 and 5). (In 2021 a similar shift happened across the entire industry as a consequence of the CMS/AMA E/M documentation overhaul, which is exactly why peer comparisons matter as much as self-comparisons; the upcoding signal is the shift relative to peers, not the shift in absolute terms.) None of these patterns are duplicates. None of them are necessarily fraud. Some of them are legitimate practice evolution. A few of them are seven-figure problems hiding in plain sight.

That's the billing code anomaly problem. Not "is this claim wrong?" but "is this provider's billing behavior unusual, and in what way?"

The scale makes this painful. Her team can investigate maybe forty provider cases per month in any depth. There are 18,000 providers. Even a 1% anomaly rate produces 180 candidate investigations against a capacity of 40. The existing rule-based system (this modifier with that CPT requires review; these CPTs billed together are impossible; this dollar amount exceeds policy) catches the obvious stuff but misses the behavioral drift. A provider who's always been in the 90th percentile for billing intensity doesn't trigger any rule, because their claims individually are fine. It's the pattern across all their claims that matters, and rules that operate on single claims can't see the pattern.

Here's what "behavioral drift" looks like in practice, with the texture the operations team actually sees:

The primary care physician who started billing 99490 (chronic care management, 20 minutes non-face-to-face) on almost every patient in her panel over a three-month period. Is this legitimate expansion of CCM services (she attended a CMS webinar, hired a care manager, is now documenting the time she was already spending)? Or is it upcoding of time that isn't actually occurring? Both stories fit the data. The code itself is appropriate; the question is whether the time was spent and documented.

The physical therapy practice where every patient gets billed the same four codes in the same sequence every visit: 97110 (therapeutic exercise), 97112 (neuromuscular reeducation), 97140 (manual therapy), 97530 (therapeutic activities). Each code individually is valid. The sequence is a pattern. A mature PT practice treats patients with widely varying conditions, and a uniform four-code regimen across all of them is statistically implausible. It might still be legitimate (this clinic has a rigid protocol that it believes is clinically justified). It's worth asking.

The home health agency whose claims show HCPCS G0299 (registered nurse, per 15 minutes) billed at four units per visit for 94% of visits. Four units is exactly one hour. The distribution is oddly sharp for something that should vary naturally. A histogram that piles up on an exact time boundary (whether 15 minutes, 30 minutes, or an hour) is a classic "unit rounding" signal, where the actual time is being bucketed rather than measured.

The orthopedic surgeon who bills modifier 59 (distinct procedural service) on 42% of his claims. Modifier 59 is one of the most frequently abused modifiers in all of medical billing because it unbundles codes that CCI edits would otherwise bundle together. An industry benchmark rate would put it in the 5-15% range for most specialties. 42% isn't proof of anything, but it's three standard deviations above the norm, and that's worth a look.

The lab that runs on a very predictable mix of CPT codes for years, then over a month's span the mix changes (same total volume, different codes), and the per-claim dollar value goes up 18%. Something operational shifted. Maybe they added a new reference lab contract. Maybe they bought a new analyzer and started running different panels. Maybe they're upcoding. The payer doesn't know which, but the shift is measurable.

None of these are caught by a static rule. They're caught by comparing the provider's current behavior to their own historical baseline and to a peer baseline for similar providers.

The usual response to this mess, historically, was either "run more rules" (which doesn't scale, because you can't write a rule for every behavioral pattern) or "sample randomly for audit" (which is fair but wildly inefficient). The modern response is anomaly detection: build a model of what normal billing looks like for this provider, this specialty, this region, this patient population, and flag the deviations.

What you actually want to produce: a prioritized queue of provider-level billing anomalies, each one enriched with enough context that the analyst can triage in a minute or two. "Dr. X at Clinic Y had a sustained 3.4 sigma shift in their E&M level distribution starting April 12; representative claims are ABC, DEF, GHI; peer group for comparison is internal medicine in metro Z; the anomaly has persisted for 32 days." That's the unit of work the analyst should see. Not a pile of individual claims with "review this" stickers. A narrative about a provider, with the evidence attached.

Let's get into how.

---

## The Technology

### What "Anomalous" Means When the Baseline Is the Provider Themselves

Billing code anomaly detection is structurally different from duplicate detection or no-show prediction, and the difference matters for the modeling.

Duplicate detection (Recipe 3.1) compares a claim against other claims to find matches. No-show prediction (Recipe 3.2) compares a patient's behavior against their own history and population norms, but the outcome is binary and well-defined. Billing code anomaly detection is fundamentally about *provider behavior over time*, where the "normal" is itself a distribution that evolves slowly, and the "anomaly" is a change in the shape of that distribution rather than a single suspect event.

Three flavors of anomaly show up in billing data, and any serious system needs to handle all three:

**Point anomalies.** A single claim that doesn't fit the provider's normal pattern. The dermatologist billing 97110 is a point anomaly: one claim (or a few claims) with a code that doesn't match the specialty, the provider's history, or the patient's presenting condition. These are the easiest to catch because they stand out individually. A rule engine can handle most of them, actually, if the rules are written carefully.

**Contextual anomalies.** A claim that's normal in isolation but unusual given the context. 99215 (level 5 E&M) is a normal code. 99215 billed for a 19-year-old with a single diagnosis of acne and no comorbidities is contextually unusual. The code exists; the patient doesn't warrant it. These require the model to understand the relationship between the code, the patient characteristics, and the visit context. Much harder to catch with rules alone.

**Collective anomalies.** No single claim is an anomaly, but the collection of claims (usually for a single provider over a window of time) is unusual. This is where most of the real money lives. A provider whose E&M distribution shifts from centered-on-99213 to centered-on-99214 isn't wrong on any single claim. The pattern across thousands of claims is the signal. These require aggregated statistics and temporal monitoring. No rule engine catches them; this is where the model earns its keep.

The consequence for architecture: a billing anomaly detector isn't really a "score the incoming claim" system. It's a "continuously model each provider's behavior and flag the changes" system. The unit of analysis is typically the provider-month or provider-week, not the individual claim. Individual claims get used as evidence *after* a provider-level flag fires, as representative samples that help a human understand what the anomaly actually is.

### The Three Comparison Axes

Every useful billing anomaly signal comes from a comparison, and there are three axes of comparison that matter:

**Self-comparison (provider vs. their own history).** The provider's billing mix today versus their billing mix over the last 6-12 months. The distribution of E&M levels. The top N codes and their frequencies. The average claim dollar value. The mix of modifiers. The average number of codes per encounter. This axis catches drift: the provider who was doing X consistently and is now doing Y. Huge signal when it fires.

**Peer comparison (provider vs. similar providers).** The provider's billing patterns compared to a relevant peer group. "Similar" is doing a lot of work here: specialty, subspecialty, practice setting (solo, group, hospital-employed, FQHC), geography, patient population acuity. The peer group definition is probably the single most important design decision in the whole system. A too-narrow peer group (say, "dermatologists in this ZIP code") has too few providers for stable statistics. A too-broad peer group ("all outpatient providers") averages away the specialty-specific patterns that matter. Standard practice is to define peer groups with 30-500 providers per group, tuned to the specialty density in your coverage area.

**Expected-given-patient-mix comparison.** The provider's billing patterns compared to what you'd expect given their specific patient mix. If a provider serves a disproportionately complex patient population (older, more comorbidities, more chronic conditions), their billing intensity should be higher. If the model accounts for the patient mix and they're *still* above expectation, that's a stronger signal. This axis requires patient-level adjustment and is often called case-mix-adjusted comparison. It's the most sophisticated of the three and the one that's easiest to do wrong (because the adjustment model itself can hide real signal if it overfits to the billing patterns).

Most mature systems run all three comparisons in parallel and combine the signals. A provider flagged on one axis is worth noting. A provider flagged on two or three axes simultaneously is the kind of case that pays for the whole program.

### Feature Families That Actually Matter

The feature engineering for billing anomaly detection has its own idiosyncrasies. Here are the families that show up, roughly ordered by signal-to-effort ratio:

**Code mix features.** Frequency distribution of CPT/HCPCS codes billed by the provider over a rolling window. Top-10 codes by frequency, share of total claims. Shannon entropy of the distribution (a provider who bills a narrow set of codes has low entropy; a provider who bills broadly has high entropy; a sudden entropy change is a flag). Percentile rank of each code's frequency versus peers.

**E&M level distribution features.** For providers who bill E&M codes, the distribution across levels 1-5 is one of the most important features in the whole system. Percentage of visits at each level. Comparison to peer-group distribution. Time-series of the distribution to detect drift. E&M level distribution is where upcoding shows up most visibly, and CMS has published guidance on expected distributions by specialty that gives you a reference anchor.

**Modifier usage features.** Frequency of each modifier overall and on specific CPTs. Modifier 59 usage rate. Modifier 25 (significant separately identifiable E&M) usage rate. Modifier 22 (increased procedural services) usage rate. These modifiers are heavily watched because they each allow billing for work that would otherwise be bundled into another code. Unusual rates are a strong signal.

**Code combinations and sequences.** Codes that frequently appear together on the same claim. Bundling violations (codes that CCI edits say shouldn't be billed together). Unusual combinations that pass edits but are clinically implausible. Sequences of codes across visits (a patient seen three times for CPT A, A, then B is different from A, B, A).

**Dollar and unit features.** Average billed amount per claim, per encounter, per patient. Units per claim (time-based codes with suspicious unit counts). Billed-to-allowed ratio. Distribution of billed amounts (a provider whose distribution is bimodal on either side of a specific threshold is suspicious; the gap may correspond to a coverage rule).

**Volume and velocity features.** Claims per month, per working day, per unique patient. Growth rate of volume. Sudden volume spikes. Number of unique patients seen. Ratio of new-patient codes to established-patient codes.

**Temporal patterns.** Billing timing (claims submitted weekly vs. batched monthly). Day-of-week distribution of service dates. Holiday and weekend billing rates (legitimate for emergency specialties; suspicious for office-based specialties). Gap between service date and submission date.

**Network and relationship features.** Patients shared with other providers. Referral patterns. Billing through the same practice tax ID. Some of the highest-dollar fraud patterns are organized (multiple providers acting in concert), and relationship features are what surface them. These require graph-level analysis and are where this recipe starts to blur into Recipe 3.6 (general fraud/waste/abuse detection).

Most teams build the self-comparison and peer-comparison features first and get 80% of the value. The case-mix-adjusted and network features are the mature-system additions.

### Statistical Methods That Fit

The field has tried a lot of methods. A few work well enough that they're standard.

**Z-scores on rolling statistics.** For each provider-feature combination (say, this provider's share of 99214 claims this month), compute a z-score against the peer-group distribution. Flag anything beyond a threshold (2 or 3 sigma, depending on desired sensitivity). Dumb, simple, fast, interpretable, and often the thing most of the system ends up doing because it's good enough for the common cases. Don't skip this step chasing sophistication.

**Control charts and CUSUM.** Treat each provider-feature as a time series and monitor for out-of-control signals. A standard Shewhart control chart flags when a single observation goes beyond 3-sigma limits. A CUSUM (cumulative sum) chart is more sensitive to small, sustained shifts (which is exactly what upcoding looks like: not a single huge jump, but a persistent small elevation). This is classical statistical process control, and it fits billing data very well because the underlying problem (detect a distributional shift) is exactly what SPC was invented for.

**Isolation Forest or other unsupervised anomaly detectors.** Feed the per-provider feature vectors into an Isolation Forest. Providers that require few splits to isolate are anomalies. Works especially well for multivariate anomalies where no single feature is unusual but the combination is. Interpretability takes extra work. SHAP's tree-explainer doesn't directly apply (Isolation Forest's prediction function is path-length-based, not leaf-level); the practical patterns are KernelSHAP (model-agnostic, slow), path-length attribution from the original IF paper (custom implementation), or feature-deviation proxies (z-score against training-set per-feature stats, fast and good enough for analyst-facing explanations). Most production systems use the third option.

**Matrix factorization / collaborative filtering.** Treat the provider-by-code matrix as a sparse matrix and factorize it. Predict each provider's expected frequency for each code based on their latent factors (which end up capturing specialty, practice type, patient mix). Compare actual to predicted. Large residuals are anomalies. This approach borrows from recommender systems and handles the "expected given this provider's profile" question naturally. It requires more modeling work than z-scores but produces richer anomaly signals.

**Gradient boosting for supervised classification.** If you have historical labels (cases that were investigated and confirmed as upcoding, fraud, or legitimate), train a classifier to predict the probability that a provider's current behavior is anomalous enough to warrant investigation. This is the mature-system move. Requires labeled data, which most organizations don't start with. Worth building toward.

**Embedding + nearest-neighbor.** Embed each provider into a vector space (from their code mix, or a learned embedding) and look for providers who are far from any cluster. Similar in spirit to Isolation Forest but with different geometric assumptions. Sometimes produces more intuitive anomalies because the embedding space can be inspected visually.

A reasonable progression: start with z-scores and CUSUM. Add Isolation Forest once you've seen enough data to tune thresholds. Add supervised classification once you've got labels. Don't go to embeddings unless you've exhausted the simpler options.

### The Peer Group Problem

The peer group definition is where a lot of systems go wrong, and it's worth lingering on.

The goal is a group of providers who, if billing in a legitimate fashion, should produce similar statistics to the provider you're evaluating. Too narrow, and you don't have enough comparators (small groups have high variance; a small peer group with 15 providers will have a wide z-score distribution and you'll struggle to flag anything statistically). Too broad, and you average across genuinely different practices (a rural family physician and an academic internist will both roll up to "primary care" but their billing patterns differ in ways that aren't anomalies).

Peer group features to consider:
- Specialty and subspecialty (primary axis)
- Practice setting (solo, group, hospital-owned, FQHC, rural health clinic)
- Geographic region (ZIP5 is too narrow; state is too broad; MSA or CBSA is often right)
- Patient volume band (a five-patients-a-day practice behaves differently than a thirty-patients-a-day one)
- Patient acuity (case-mix adjustment, where available)
- Years in practice (new practices are still building patterns)

The practical approach is to try multiple peer group definitions and pick whichever produces stable percentiles with reasonable group sizes (30 minimum, ideally 100-500). Hierarchical peer groups work well: run the comparison at multiple levels (specialty, specialty+region, specialty+region+setting) and use whichever has enough comparators. For small specialties (pediatric nephrology, for example), the regional filter may drop too many providers and you'd run at the national specialty level only.

One subtle trap: the peer group statistics include the provider you're evaluating. If you leave them in, you're comparing them to themselves (and if they're an extreme outlier, they're pulling the group statistic toward themselves). Leave-one-out z-scores fix this. It sounds fiddly. It matters more than you'd think when you have specialties with fewer than 100 providers.

### The Labeling Problem (Different From Claims)

If you go supervised eventually, the labels for billing anomaly detection come from payment integrity investigations. Their nature matters:

**Most investigations don't close with a clean "fraud" or "not fraud" label.** They close with outcomes like "provider educated," "claims adjusted," "referred to SIU," "referred to law enforcement," "no action." These are not directly the labels you want. Translating them requires judgment, and different organizations make different choices. A common mapping: "adjustments or SIU referral" → anomaly = True, "education only" → ambiguous, "no action" → anomaly = False (but be careful: "no action" sometimes means "we didn't have time to finish the investigation," which isn't the same as "we determined it's fine").

**Label lag is enormous.** Investigations can take 6-18 months from flag to resolution. By the time you have labels for cases flagged a year ago, the model's feature distributions have shifted, the provider landscape has changed, and the fraud patterns have evolved. This is structurally worse than most supervised problems.

**Self-confirming labels are a big risk.** If your existing system flags providers using criteria X, and those providers get investigated and labeled, the label dataset is heavily biased toward criteria X. A model trained on this data re-learns criteria X and misses everything else. Break out of this: periodically random-sample from unflagged providers and have them reviewed, specifically to get "negative" and "other-pattern" labels into the dataset.

**False negatives are often never discovered.** A provider engaged in upcoding who doesn't get flagged simply... doesn't get investigated. You never learn you missed them. This creates a perpetual blind spot in the label distribution that no amount of supervised learning can correct. The unsupervised signals (z-scores, Isolation Forest) partly mitigate this by flagging things the supervised system wouldn't think to flag.

### Fairness, Legitimacy, and the "Harassment of Legitimate Variation" Risk

Provider billing behavior is not uniform, and unusual isn't the same as fraudulent. Providers in different practice settings, with different patient populations, with different clinical philosophies, will produce different billing patterns. A high-performing geriatric practice will look different from an average one. A community health center serving a very sick population will bill differently from a concierge practice. These differences are legitimate, and flagging them as anomalies creates several kinds of harm:

- **Operational harm to the provider.** Investigations take time. They interrupt clinical work. They stress providers who are already overworked.
- **Reputational harm.** Being flagged for potential fraud, even if cleared, leaves a record.
- **Access harm.** Providers who are repeatedly flagged may drop out of the network, which disproportionately affects the patients they serve (often the most complex and underserved).
- **Statistical discrimination.** If the features correlate with patient demographics in ways that make serving certain populations look "anomalous," the system punishes providers who serve those populations.

The mitigations are real work, not checkboxes:

- **Case-mix adjustment.** Make the expected statistics adjust for the patient population. A provider who serves sicker patients should have higher expected billing intensity, and the anomaly signal should be against the adjusted expectation.
- **Transparent, auditable thresholds.** Document why each threshold is set where it is. Review thresholds periodically. Publish them internally so the provider relations team can explain them.
- **Investigation protocol focused on understanding, not punishing.** The first step after a flag should be contact, not penalty. "We noticed your billing pattern shifted; can you help us understand what changed?" often resolves the flag in a single conversation.
- **Subgroup monitoring of who gets flagged and who gets investigated.** If providers serving particular populations are systematically flagged at higher rates, that's a signal that the model is discriminating.

The ethical posture that works best is: an anomaly flag is a prompt for a conversation with the provider, not an accusation. The conversation establishes context. Most flags resolve there. The small subset that don't is where investigation effort goes.

---

## General Architecture Pattern

At a conceptual level, the pipeline has four stages plus a feedback loop. The architecture looks a lot like the no-show recipe (Recipe 3.2) but the unit of analysis shifts from appointment to provider-period, and the feature store is populated at a different cadence because provider statistics don't change second-to-second.

```text
┌────────────── CONTINUOUS PROFILING PIPELINE ───────────────┐
│                                                            │
│  [Claims Stream + Adjudicated Claims Store]                │
│         │                                                  │
│         ▼                                                  │
│  [Provider Period Aggregator]                              │
│   (roll up claims to provider-week or provider-month;      │
│    compute code-mix, E&M distribution, modifier rates,     │
│    volume metrics)                                         │
│         │                                                  │
│         ▼                                                  │
│  [Peer Group Assembler]                                    │
│   (assign providers to peer groups; compute peer           │
│    distributions leave-one-out)                            │
│         │                                                  │
│         ▼                                                  │
│  [Anomaly Scoring Layer]                                   │
│   (z-scores for single features; CUSUM for time-series;    │
│    Isolation Forest for multivariate; optional supervised  │
│    classifier if labels exist)                             │
│         │                                                  │
│         ▼                                                  │
│  [Case Assembly + Prioritization]                          │
│   (consolidate multiple signals per provider into a        │
│    single case record; attach representative claims;       │
│    rank by severity, persistence, and dollar exposure)     │
│         │                                                  │
│         ▼                                                  │
│  [Routing]                                                 │
│   severity high + sustained    → payment-integrity queue   │
│   specialty-atypical behavior  → clinical-review queue     │
│   transient / low-severity     → watch list                │
│         │                                                  │
└─────────┼──────────────────────────────────────────────────┘
          │
┌─────────┼──────────────────────────────────────────────────┐
│         ▼                                                  │
│  [Investigation Workflow]                                  │
│   (analyst reviews case; may contact provider;             │
│    documents outcome and disposition)                      │
│         │                                                  │
│         ▼                                                  │
│  [Outcome Capture]                                         │
│   (education, adjustment, SIU referral, no-action;         │
│    joined back to case record)                             │
│         │                                                  │
│         ▼                                                  │
│  [Retraining + Threshold Tuning]                           │
│   (monthly; includes bias and subgroup review; updates     │
│    peer groups, adjusts thresholds, retrains supervised    │
│    model if used)                                          │
│                                                            │
└──────────────────── FEEDBACK LOOP ─────────────────────────┘
```

**Provider period aggregator.** The front of the pipeline is a time-bucketed rollup. For each active provider, produce a per-period feature vector (code-mix histogram, E&M level distribution, modifier rates, volume counts, average billed amount, novelty code counts). Period length is a tuning parameter. A one-week period is responsive but noisy for lower-volume providers. A one-month period is stable but slower to flag drift. Many systems compute both and use different windows for different signals.

**Peer group assembler.** Assign each provider to one or more peer groups and compute the peer distributions for each feature, leave-one-out. Peer group membership is re-computed periodically (quarterly is typical) because providers change practices and specialties occasionally, and new providers need to be slotted in.

**Anomaly scoring.** For each provider-period, compute the relevant anomaly signals: z-scores against peer distributions, control chart signals on time series, multivariate Isolation Forest scores, optionally supervised classifier probabilities. Each signal is kept separately rather than aggregated into a single score prematurely, so the case assembly layer can explain which signal fired.

**Case assembly and prioritization.** This is the step most first-time builders under-invest in. The raw output of the scoring layer is a pile of signals (tens of thousands per period). The operations team can work tens of cases per analyst per month. The case assembly layer consolidates signals into narrative-level cases: "Dr. X, internist, flagged on E&M distribution shift (CUSUM signal), modifier 25 rate (peer z-score 3.8), and unusual code combinations (Isolation Forest outlier). Cumulative dollar exposure over flagged period: $240K. Persistence: 8 consecutive weekly periods." That's a case. The ranking then becomes across cases, not across signals.

**Routing.** Standard thresholded routing. High-severity, sustained cases go to the payment integrity team. Specialty-atypical cases (a podiatrist billing cardiology codes) go to clinical reviewers who can judge appropriateness. Lower-severity or transient cases go to a watch list that gets reviewed in aggregate.

**Investigation workflow.** Analysts review cases, may reach out to providers, and document findings. Outcomes get structured: education, claim adjustment, SIU referral, no action. The investigation may take weeks to months.

**Outcome capture.** Outcomes join back to case records. They form the label set for supervised retraining (with the caveats discussed under "The Labeling Problem").

**Retraining and threshold tuning.** Monthly cadence. Retrain supervised models if used. Recompute peer groups. Review thresholds against operational capacity (if the queue is too long, raise thresholds; if the queue is too short, lower them). Subgroup bias review as a required step.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter03.03-architecture). The Python example is linked from there.

## The Honest Take

The feature engineering matters more than the model. This is the same lesson as Recipe 3.2, and it keeps being true. Most of the signal in billing anomaly detection comes from a handful of careful features: E&M level distribution, modifier 25/59 rates, code-mix entropy, CUSUM on key time series. Get those right and a simple z-score system will surface most of what matters. Teams that skip straight to fancy unsupervised models usually come back to z-scores anyway because the analysts want explainable signals.

The peer group definition is the single most consequential design decision. You will get it wrong the first time. Whatever peer groups you define on day one, you will redefine within three months based on what the payment integrity team tells you. Some specialties need narrower groupings than you expect (cardiology versus electrophysiology matter for billing patterns; "cardiology" alone is too broad). Some need broader groupings than you expect (small rural specialties don't have enough regional peers). Build peer group definitions as configuration, not code, because you will be editing them.

The operational cost of false positives is worse than you think. A false positive in no-show prediction is a wasted phone call. A false positive in billing anomaly detection is a provider who feels accused of fraud for behavior that turns out to be legitimate. The damage to the provider relationship, the damage to morale on the provider's team, and the operational cost of working through the investigation are all real. Budget your tolerance for false positives carefully, and err on the side of higher thresholds than you'd pick if the cost were zero. Catching 80% of true anomalies with 50% precision is better than catching 95% with 15% precision, because the operational bandwidth to investigate the latter doesn't exist.

The narrative summary in the case record is surprisingly important. I initially built a version of this pipeline that produced case records with rich structured signal data and no prose. Analysts couldn't process them fast enough because they had to reconstruct the story from the signals. Adding a generated narrative summary ("this provider shifted their E&M distribution in March, persisted through May, combined with elevated modifier 25 usage") cut case-triage time dramatically. You can generate these summaries from templates using the signal data, or use an LLM if your organization has an established HIPAA-eligible LLM pipeline (BAA coverage of the model and the serving infrastructure, minimum-necessary prompt construction, output filtering, and a full prompt-and-response audit trail; see Chapter 2 for the patterns). The template approach is faster to build and easier to certify; the LLM approach produces more natural prose but inherits the compliance scaffolding of the broader generative AI program. Most teams start with templates and only move to LLM when those Chapter 2 patterns are already in place for other reasons. The narrative matters more than you'd think.

The thing that surprised me on the last project: the Isolation Forest caught cases that none of the z-score signals did. I was initially skeptical of adding the multivariate detector because z-scores covered the obvious cases. The first month the Isolation Forest ran, it surfaced a handful of providers who were outliers on combinations of features that no individual feature caught. One of them was running what turned out to be a legitimate but unusual practice model (a holistic clinic billing a specific mix of codes); two of them were misconfigured billing systems; one was the kind of pattern that eventually resulted in a seven-figure recovery. Worth the extra complexity. Add the multivariate signal earlier than you think you need to.

The thing I'd do differently: I spent too long on the supervised classifier before recognizing that I didn't have enough labels. With a few hundred labeled cases across a specialty, the classifier produces unstable estimates that can make the system worse, not better (by confidently flagging the wrong things). Start with unsupervised and statistical signals, accumulate labels for a year, then layer supervised signals on top. Don't try to build the supervised piece first, even if the existing payment integrity program has investigation records.

The trap to avoid: do not let the system drive toward "maximize cases generated." The right operational metric is "dollars recovered per analyst hour" or "investigations-closed-with-action per case created," not volume. If you measure the system by cases generated, you incentivize lowering the thresholds and producing more noise. If you measure it by precision-weighted recovery, you incentivize fewer, better cases. The latter is what the business actually wants, and it keeps the provider relationship manageable.

---

## Related Recipes

- **Recipe 3.1 (Duplicate Claim Detection):** Shares the blocking-scoring-routing structure. If you've built 3.1, you have most of the claim-level infrastructure already; billing anomaly detection adds the provider-level aggregation and longitudinal modeling on top.
- **Recipe 3.2 (Patient No-Show Pattern Detection):** Shares the anomaly framing (comparison to self-baseline versus peer baseline) and the supervised-with-feedback-loop pattern. Different unit of analysis (patient vs. provider) but nearly identical architectural shape.
- **Recipe 3.6 (Healthcare Fraud/Waste/Abuse Detection):** The broader, more sophisticated cousin of this recipe. 3.3 is about detecting statistical anomalies in individual provider behavior. 3.6 extends to coordinated patterns, network-level analysis, and adversarial adaptation. Build 3.3 first; 3.6 inherits most of its infrastructure.
- **Recipe 5.2 (Provider Entity Resolution):** The prerequisite for a reliable billing anomaly pipeline. If your providers aren't resolved to canonical entities, your per-provider statistics are fragmented and the anomaly signal is diluted.
- **Recipe 6.4 (Provider Similarity and Benchmarking):** Uses similar features and peer-group concepts for a different purpose: benchmarking rather than anomaly detection. A mature payment integrity program often runs both, sharing the feature pipeline.
- **Recipe 7.7 (Coding Compliance Risk Scoring):** A predictive companion to this reactive detection pipeline. Predicts which providers are at elevated risk of compliance issues before the issues materialize.

---

## Tags

`anomaly-detection` · `payment-integrity` · `billing-anomalies` · `provider-behavior` · `upcoding-detection` · `statistical-process-control` · `isolation-forest` · `cusum` · `peer-benchmarking` · `sagemaker` · `feature-store` · `glue` · `athena` · `dynamodb` · `step-functions` · `simple-medium` · `mvp` · `hipaa` · `payer`

---

*← [Recipe 3.2: Patient No-Show Pattern Detection](chapter03.02-patient-no-show-pattern-detection) · [Chapter 3 Preface](chapter03-preface) · [Next: Recipe 3.4 - Medication Dispensing Anomalies →](chapter03.04-medication-dispensing-anomalies)*
