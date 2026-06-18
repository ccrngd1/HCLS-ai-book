<!--
Editor pass (TechEditor, 2026-05-15): style/voice check (zero em-dashes
verified; 70/30 vendor balance preserved); replaced real-sounding sample
provider name "Pine Ridge Medical Associates" with explicitly synthetic
name (privacy/reputation hygiene); added Luhn-validity disclaimer on
sample NPIs; added a draft-date disclaimer on sample timestamps; added
TODO markers for substantive technical concerns surfaced by the expert
review (graph-construction missing claim vertices; outcome-event
idempotency at the evidence-aggregator; DLQ posture for the four
critical Lambdas; provider appeals workflow architectural backstop;
reference-data versioning propagation; legal-privilege infrastructure
primitives) that require TechWriter follow-up rather than in-place
rewriting. Preserved all existing TODOs from earlier personas. Section
order and structural claims unchanged.

Final pass (TechEditor, 2026-05-15): re-verified zero em-dashes (any
en-dash matches are confined to the ASCII-art architecture-pattern
block-diagram inside a fenced code block, not in prose); confirmed
header hierarchy (one H1, structured H2/H3/H4 progression with no
skipped levels); confirmed all sample provider/organization names in
Expected Results carry an explicit "(sample)" suffix or are obviously
synthetic placeholders ("Corp Shell A LLC"); confirmed sample NPIs
remain `<synthetic-NPI>` placeholders behind the Luhn-validity
disclaimer; confirmed legal citations (42 USC 1320a-7b, 42 USC 1395nn,
31 USC 3729-3733, 42 CFR 411.354, 42 CFR 422.504(h), 42 CFR 438.608,
45 CFR 164.512(f)) are correctly formatted; confirmed all 17 TODO
markers are well-formed and addressed to TechWriter for follow-up.
No further in-place rewrites; recipe is ready for publication pending
TechWriter resolution of flagged TODOs.

Sign-off pass (TechEditor, 2026-05-15): re-verified mechanical
checklist on the main recipe. Direct grep for U+2014 and the en-dash
range (U+2010 through U+2015 plus U+2212): zero matches in prose.
Direct grep for documentation-voice and announcement anti-patterns
("we are excited", "this recipe demonstrates", "in this recipe we
will", "need to talk about"): zero matches. Code-fence inventory: 28
fenced blocks, 4 with explicit language tags (one `mermaid`, three
`json` for the Expected Results sample alerts) and 24 unlabeled for
pseudocode and ASCII-art block-diagrams; matches the convention
established in chapter01 and used consistently through chapter03.05.
Header hierarchy unchanged (one H1, structured H2/H3/H4 progression).
TODO inventory: 17 well-formed `<!-- TODO (TechWriter): ... -->`
markers in prose plus references to those TODOs in this editor
comment block; all preserved. No prose edits; the prior two passes
already settled voice, hygiene, and safety. Recipe is publication-
ready as a standalone file.

Cross-file flag for TechWriter (publication blocker, not a TechEditor
fix): the companion `chapter03.06-python-example.md` is in the FAIL
state from code review (`reviews/chapter03.06-code-review.md`,
2026-05-14). One ERROR (`aggregate_flags_to_cases` writes flag dicts
containing Python floats to DynamoDB; the resource-API serializer
raises `TypeError: Float types are not supported. Use Decimal types
instead.` the first time a statistical or graph flag reaches the
put_item call) and five WARNINGs (OWNERSHIP_CASCADE detector cannot
fire because organization nodes are never created; "Rule 3: LEIE
exclusion" comment does not match the code which checks the
`UNRESOLVED:` prefix; patient node ID is the raw patient_id rather
than a hash, contradicting the main recipe's Step 3 pseudocode and
the privacy rationale; `capture_case_outcome` S3 put_object uses
`ServerSideEncryption="aws:kms"` without `SSEKMSKeyId`; deterministic
case-id idempotency is undermined by `uuid.uuid4()` per call). The
ERROR breaks the demo for any realistic full-pipeline run and is a
publication blocker. WARNINGs 2 and 3 (graph-construction
inconsistency, patient-node hashing) parallel the main recipe's
Step 3 expert-review TODO (S1) and should be fixed in lockstep so
the pseudocode and the Python companion remain in agreement. The
TechEditor persona is not the right pass to apply these fixes;
TechWriter should pick up `chapter03.06-python-example.md` against
the code-review checklist before this recipe goes to publication.

Final iteration confirmation (TechEditor, 2026-05-15): re-ran the
mechanical checklist on this iteration. U+2014 em-dash count: 0.
U+2212 minus-sign count: 0. U+2013 en-dash count: 17, all confined
to the ASCII-art block-diagrams inside fenced code blocks (zero
prose en-dashes). Documentation-voice and announcement
anti-pattern grep ("we are excited", "this recipe demonstrates",
"in this recipe we will", "let's talk about", "we need to talk
about", "aws architects, we"): zero matches in prose; all hits
confined to this editor comment block where the patterns are
enumerated as items to check for. Header hierarchy: one H1 (the
title), 11 H2 (Problem / Technology / General Architecture Pattern
/ AWS Implementation / Why This Isn't Production-Ready / Honest
Take / Variations and Extensions / Related Recipes / Additional
Resources / Estimated Implementation Time / Tags), structured H3
subsections under Technology and AWS Implementation, one H4
(Walkthrough) under Code; no skipped levels; matches the
chapter03.04 and chapter03.05 patterns. TechWriter TODO inventory
unchanged at 16 well-formed `TODO (TechWriter)` markers. Sample
provider-name discipline confirmed: every entity name in the
Expected Results sample alerts carries either an explicit
"(sample)" suffix or is an obvious synthetic placeholder. Sample
NPIs remain `<synthetic-NPI>` placeholders behind the Luhn-validity
disclaimer at the top of the Expected Results block. The cross-
file Python-companion FAIL flag and TechWriter follow-up note
above stand. No further in-place rewrites; recipe sits at the same
publication-ready quality bar as Recipes 3.1 through 3.5 pending
TechWriter resolution of the 16 flagged TODOs and the Python
companion code-review fixes.

Iteration sign-off (TechEditor): repeat mechanical pass confirms
em-dash count zero, prose en-dash count zero, header hierarchy
intact, 16 TechWriter TODOs intact and well-formed, sample-data
hygiene intact (synthetic provider names, `<synthetic-NPI>`
placeholders, draft-date timestamp disclaimer). No prose edits
applied this iteration; the substantive expert-review and
code-review concerns are flagged as TODOs for TechWriter and the
Python-companion FAIL state is the cross-file blocker. Recipe
remains publication-ready as a standalone main file.

Final iteration (TechEditor, 2026-05-21): added two new TODO
markers to close out the remaining MEDIUM expert-review findings
that did not yet have markers in place. Marker for S2 (PHI
minimization on the EventBridge `CaseReady.triage` notification
and per-investigator IAM scoping on the OpenSearch case index and
case-state DynamoDB table) placed immediately after the Step 7
`on_flag_event` pseudocode block where the notification fans out.
Marker for S3 (architectural artifacts for subgroup-governance
data access: where the demographic-and-attribute store lives, who
has read access, how subgroup queries are audited via CloudTrail,
how the QuickSight dashboard queries an aggregated subgroup-metrics
table rather than the raw demographic-joined flag archive) placed
immediately after the Fairness-bias-equity-monitoring bullet in
Why This Isn't Production-Ready. Both markers carry the
`Expert review SN (MEDIUM)` prefix that the follow-up generator
matches and reference the recurring chapter-wide pattern (S2 is
the seventh distinct PHI-minimization surface; S3 is the
five-recipe chapter-wide subgroup-governance pattern). All eight
expert-review MEDIUM findings (A1, A2, A3, A4, S1, S2, S3, S4)
now have well-formed TODO markers in place. Re-ran mechanical
checks: U+2014 em-dash count zero, U+2212 minus-sign count zero,
U+2013 en-dash count 17 (all confined to ASCII-art block-diagrams
inside fenced code blocks; zero prose en-dashes); 17 well-formed
`TODO (TechWriter)` markers in prose. No further in-place
rewrites; recipe is publication-ready as a standalone main file
pending TechWriter resolution of the 17 flagged TODOs and the
Python-companion code-review fixes (cross-file blocker stands).
-->

# Recipe 3.6: Healthcare Fraud, Waste, and Abuse Detection ⭐

**Complexity:** Medium-Complex · **Phase:** Production · **Estimated Cost:** ~$0.002 to $0.02 per claim scored (mostly compute and graph traversal; full provider-level scoring runs weekly and dominates cost)

---

## The Problem

It's a Monday morning at a mid-size commercial payer. The Special Investigations Unit (SIU) has a conference room with a whiteboard, and on the whiteboard is a network diagram. Three clinics in the same strip mall, four providers who all trained at the same institution fifteen years ago, two durable medical equipment (DME) suppliers with overlapping ownership, and one toxicology lab that received roughly eighty percent of the referrals from those clinics over the last eighteen months. Total paid: $11.7 million. Total patients involved: roughly four hundred. Average paid per patient: $29,000. Average paid per patient at comparable clinics in the region: $3,200.

Nobody on the team built that picture from a single alert. It emerged from six months of investigation: a tip from a former employee, a pattern in the urine toxicology claims (every patient billed for a 22-panel confirmatory test every two weeks, regardless of clinical indication), an FBI request for records on one of the providers, and an analyst who got curious about why one lab kept showing up in the referral data. The whiteboard is the synthesis. The $11.7 million is the damage. And the quiet thing everyone in the room is thinking is: how many other whiteboards should we be drawing right now that we haven't even started?

That's healthcare fraud, waste, and abuse detection in a nutshell. Not "is this claim wrong?" (that's Recipe 3.1, duplicate detection). Not "is this provider's billing drift unusual?" (that's Recipe 3.3, billing code anomalies). FWA is the bigger problem: is there a pattern across claims, providers, patients, suppliers, and payments that describes an intentional scheme, a negligent process, or an abusive-but-legal practice that's costing money and harming patients?

The terminology is worth getting right because the legal and operational handling differ:

**Fraud** is intentional deception for financial gain. Phantom billing (charging for services never rendered), identity theft (billing under a patient's identity without their knowledge), kickbacks (paying providers to refer patients to specific services), and collusive networks (providers, labs, and DME suppliers coordinating to extract payment). Fraud is a criminal matter. When it's identified, it goes to law enforcement, the Office of Inspector General (OIG), state Medicaid Fraud Control Units, or the Department of Justice.

**Waste** is overutilization without necessarily intentional deception. Ordering tests that aren't clinically indicated. Performing procedures that duplicate recent ones. Using expensive options when cheaper equivalents would work. Waste is usually addressed through provider education, medical necessity review, and utilization management, not through investigation and prosecution.

**Abuse** is the ambiguous middle ground: billing practices that are technically legal but inconsistent with accepted standards, or that exploit gray areas in coverage rules. Unbundling services that should be billed together. Upcoding evaluation-and-management levels. Billing at the highest-intensity code when the documentation supports a lower one. Abuse cases often result in adjustments, overpayment recovery, and corrective action plans rather than referrals to law enforcement.

Most real cases are mixtures. A provider who started with waste (overordering labs because it's easier than not ordering them) can drift into abuse (the overordering becomes systematic, and coding shifts to maximize payment) and eventually into fraud (the documentation for those labs starts being fabricated, or the referral relationship with the lab becomes a kickback arrangement). The detection system has to see the full spectrum because the same underlying patterns show up across all three.

The pain here is different from every other recipe in this chapter, and the difference is worth naming:

**The stakes are enormous.** FWA is estimated to cost the US healthcare system somewhere between three and ten percent of total spending, which at current volumes puts the annual loss in the hundreds of billions of dollars. The National Health Care Anti-Fraud Association estimates conservatively at three percent, roughly $100 billion per year. Government estimates run higher. <!-- TODO (TechWriter): confirm current NHCAA and CMS published estimates for FWA losses. Figures shift each year; verify recent publications before citing specific numbers. -->

**The adversary is adaptive and organized.** Most of the money in FWA is in organized schemes, not individual bad actors. The people running these schemes study detection logic. They know what triggers flags, and they structure billing to stay below thresholds. They use multiple provider numbers, multiple corporate entities, multiple geographies. A static detection rule has a useful lifetime measured in months before the schemes adapt.

**The false-positive cost is high.** Accusing a legitimate provider of fraud, even tentatively, has legal and relationship consequences. Providers have sued payers over wrongful termination from networks. Provider relations teams get burned when investigations chase legitimate practice variation. The standard of evidence required before taking action (audit, recoupment, termination, referral) is genuinely high, and the detection pipeline must produce cases that meet that standard.

**The true-positive "discovery" is rare.** Unlike sepsis or lab artifacts, where ground truth gets confirmed within hours or days, fraud is confirmed on a multi-month timeline. Investigations take six to eighteen months. Prosecutions take years. Learning whether a flag was correct often happens long after the flag fired, and many true positives are never confirmed because the investigation was never completed.

**The workflow is multi-party and partially legal.** Fraud cases involve claim data from the payer, patient interviews, provider interviews, medical record review by clinical reviewers, legal coordination, sometimes law enforcement. The detection pipeline produces the first-pass candidates. Everything after that is workflow software for a team of investigators, legal counsel, and clinical reviewers working through a case. A recipe that stops at "here's a list of scored providers" is producing maybe 20% of the value.

**The rules encode law and contract.** Coverage rules, Correct Coding Initiative (CCI) edits, medical necessity policies, anti-kickback statutes, Stark Law relationships, False Claims Act liability. These aren't detector heuristics; they're legal constraints. A detection system that flags a pattern as fraudulent has to be grounded in the specific legal or contractual rule the pattern violates. "This looks weird" is not an actionable case. "This violates 42 CFR 411.354 regarding physician self-referral because the referring provider has an ownership interest in the entity receiving the referral" is an actionable case.

What you actually want to build is a layered system that runs continuously over claims, remittance, and relationship data, produces provider-level and scheme-level (network-level) candidates, enriches those candidates with legal and clinical context, and feeds a case management workflow where investigators can accept, develop, or dismiss candidates. Underneath sits a graph of relationships (providers to patients to payments to ownership entities) because most of the high-dollar fraud is relational and not visible in any single provider's statistics. On top sits a review queue designed for investigators, not for clinicians or claim auditors, because the work product of an FWA investigator is a case file that may end up in front of a judge.

Let's get into how.

---

## The Technology

### The Scheme Taxonomy, and Why It Matters

Before picking algorithms, a first-time builder should internalize the scheme taxonomy, because different schemes require structurally different detection approaches. These are the patterns that show up over and over across payers, regulators, and public OIG enforcement actions.

**Phantom billing.** The provider bills for services that were never rendered. The patient may not exist (identity theft), or the patient exists but didn't receive the service on the date billed. Phantom billing is sometimes obvious (a deceased patient billed for office visits; a patient traveling abroad billed for in-person visits) and sometimes subtle (a high-volume practice where a few percent of visits are fabricated to pad revenue). Detection clues: patient eligibility inconsistencies, impossible service volumes (a provider billing for 90 patient visits in a single day), service date patterns that don't match facility open hours.

**Upcoding.** The provider bills for a higher-intensity service than what was actually performed. An office visit documented at a level 3 intensity billed as a level 5. An EKG read and interpreted (higher pay) billed when only a technical read (lower pay) was performed. A 30-minute psychotherapy session billed as a 60-minute session. Upcoding is the single most pervasive FWA pattern by claim volume. Detection clues: E&M level distributions shifted relative to peers and specialty benchmarks, documentation that doesn't support the billed code, service-time codes whose durations sum to impossible daily totals.

**Unbundling.** Services that have a single bundled code are billed as separate codes to increase total payment. A lab panel that has a single panel code billed as its individual component tests. A surgical procedure that bundles the pre-op, intra-op, and post-op work billed separately. Modifier 59 (distinct procedural service) is the workhorse of unbundling schemes. Detection clues: modifier 59 usage above specialty norms, specific code combinations that violate CCI edits, dollar-per-encounter totals higher than bundled equivalents.

**Medically unnecessary services.** Services that were rendered but weren't clinically indicated. Urine drug screens of elaborate complexity every two weeks on patients who could be monitored with simpler screens or less frequently. Physical therapy continuing long past the point of clinical benefit. Imaging studies ordered reflexively without matching clinical findings. Hyperbaric oxygen therapy for conditions outside the covered indications. This category overlaps with waste and abuse legally but shows the same technical patterns. Detection clues: service frequency out of line with clinical guidelines, service types that don't match the patient's diagnosis profile, dose-response patterns (providers whose ordering intensity scales with the payment rate rather than the acuity).

**Kickbacks and self-referral.** Federal Anti-Kickback Statute (42 USC 1320a-7b) prohibits remuneration in exchange for referrals for items or services reimbursed by federal programs. Stark Law (42 USC 1395nn) prohibits physician self-referral to entities with which the physician has a financial relationship, in specific scenarios. These are relationship offenses: they're invisible in any single claim but visible in the referral graph. Detection clues: high referral concentration (one provider sending most of a specific service to one supplier), ownership overlap between the referring and the referred-to entities, gifts and payments logged in Sunshine Act data that correlate with referral patterns.

**Identity theft and credential abuse.** A provider's identifier (NPI) is used to bill services the provider didn't render, either because the credentials were stolen or because the provider knowingly loaned them. This pattern shows up especially in situations where a provider has retired, died, moved, or had license action taken, but claims continue to flow under their NPI. Detection clues: claims submitted after provider death, retirement, or license suspension, claims from geographies the provider doesn't practice in, claim velocity that's implausible for the provider's practice size.

**Collusive networks.** Multiple entities (providers, labs, DME suppliers, pharmacies, corporate owners) coordinating to extract payment. Classic patterns: a pain clinic that refers every patient to the same toxicology lab for elaborate testing regardless of clinical need; a DME supplier whose referring providers all share a corporate owner; a home-health agency whose referring physicians are all paid consultants for the agency. Collusive networks produce the largest-dollar cases and are essentially impossible to detect at the claim or single-provider level. They're graph problems.

**Patient-side abuse.** Patients shopping multiple providers for controlled substances (drug seeking), patients visiting multiple facilities to receive duplicative services (doctor shopping for disability documentation), patients who loan insurance cards to uninsured family members. These show up in patient-level utilization patterns rather than provider-level patterns and usually require cross-referencing pharmacy data with prescription monitoring programs.

**Billing-mill patterns.** Low-skill, high-volume operations that use templated documentation to churn out claims. Physical therapy mills, urine toxicology mills, DME mills, pain management mills, genetic testing mills. The documentation is real enough to pass an initial audit (templates are filled in, signatures are applied), but the clinical decision-making underneath is missing. Detection clues: service intensity uniform across patients regardless of presentation, documentation templates with identical phrasing across patients, single-provider practice volumes that imply impossible patient-contact time.

A detection pipeline that handles these schemes uses very different techniques for each. Phantom billing benefits most from rule-based and eligibility-integrity checks. Upcoding and unbundling live in statistical drift detection (Recipe 3.3's territory, one tier deeper). Kickbacks and collusive networks require graph analytics. Identity theft needs real-time eligibility and cross-data checks. Patient-side abuse requires patient-level aggregations across providers. A single model does not cover all of this. What does is a layered architecture with multiple detectors, each tuned to a specific scheme class, feeding a unified case management layer.

### Rules Versus Models, and Why You Need Both

There's a persistent debate in payment integrity about whether rule-based engines or machine learning models are better for FWA detection. This debate is mostly an energy drain because the right answer is "both, and in specific places."

Rules are appropriate when the pattern is defined by law, policy, or contract. CCI edits. Medical necessity criteria encoded in coverage policies. Anti-Kickback Statute elements. Stark Law relationships. These have known definitions, and a violation is a violation. A rule engine that encodes them precisely is the right tool. Attempting to learn them with a model is a waste of effort and introduces risk (the model learning a fuzzy approximation of a bright-line rule).

Models are appropriate when the pattern is defined by behavior that deviates from norms, and the norms are learned from data. Upcoding detected through E&M distribution shifts. Collusive networks detected through unusual referral concentration. Phantom billing detected through velocity models. These are too varied and too adaptive to encode as a static rule; they need the model to pick up on the current shape of the data.

The productive integration is that rules produce the high-confidence, legally-grounded flags that go directly to investigation. Models produce the lower-confidence, exploratory flags that go to an analyst for enrichment before investigation. The two streams join at the case management layer, where a case can have rule-based and model-based evidence attached.

### Statistical and ML Methods That Fit

FWA detection pulls from a wider range of methods than any other recipe in this chapter. Here's the family:

**Rules engines.** Decision Model and Notation (DMN), Drools, or equivalent. Encodes CCI edits, medical necessity policies, eligibility rules, coverage determinations. Must be versioned because rules change (new CPT codes, new policy determinations). Must be explainable: every flag includes the rule ID and the specific inputs that triggered it. This is the workhorse for the legally-grounded piece of the pipeline.

**Statistical baselining (z-scores, CUSUM, control charts).** For provider-level and patient-level behavioral features. Flag distributions that drift versus peer norms or self-history. Same techniques as Recipe 3.3 (Billing Code Anomalies); FWA uses them as one component among many.

**Isolation Forest and other unsupervised detectors.** Handles high-dimensional feature vectors on providers, patients, and claim clusters. Surfaces multivariate outliers that no single univariate check catches. Pairs well with SHAP-based explanations so investigators can see which features contributed to the flag.

**Supervised classification.** Gradient boosted trees (XGBoost, LightGBM) on labeled historical cases. Predicts probability that a provider or claim cluster will result in a confirmed investigation outcome. Requires the hard work of label collection described earlier (ambiguous outcomes, long latency, self-confirming bias). Typically a re-ranker on top of unsupervised candidates rather than a primary detector.

**Graph analytics.** Probably the single most-differentiated technique in FWA detection. Construct a graph of providers, patients, facilities, claims, payments, and ownership entities. Compute graph features: community detection (who clusters with whom), betweenness and centrality (who's a hub), shortest paths (how closely connected are two entities), Jaccard similarity on referral patterns (whose referral graph overlaps suspiciously with whose). Communities with unusually tight referral concentration, billing-through-common-entities patterns, or shared-ownership fan-out are the classic collusive-network signatures. Most commercial SIU toolkits and most state Medicaid Fraud Control Units use graph analytics as a core capability, and it consistently finds cases that no per-claim or per-provider method catches.

**Graph neural networks (GNNs).** The evolution of graph analytics toward learned representations. A GNN can learn node embeddings that incorporate the structural role of each node (provider, patient, facility) in the graph plus its features (specialty, location, billing patterns). Anomaly detection on GNN embeddings catches patterns that hand-crafted graph features miss. Still emerging in production FWA use, but the research literature is accelerating. <!-- TODO (TechWriter): as specific validated patterns for GNN-based FWA detection become published with operational results, expand with concrete references. -->

**Peer-group and cohort modeling.** Define peer groups carefully (specialty, region, practice size, patient mix), compute per-peer-group baselines, then measure the target provider's deviation from the cohort baseline. Same as Recipe 3.3. In FWA specifically, peer-group definition gets more sophisticated because the schemes often operate within a specialty (all pain management, all toxicology labs, all DME suppliers); intra-specialty comparison is where the differentiation happens.

**NLP on documentation.** Clinical documentation review is a large part of case development. LLMs and extractive NLP can summarize documentation, extract the medical necessity justification, identify template copy-paste patterns ("documentation cloning"), and flag documentation that doesn't support the billed code. An LLM given a billed CPT and its documentation can assess whether the documentation supports the code, and explain its reasoning. Not a decision-maker, but a substantial accelerator for the clinical reviewer.

**Time-series and change-point detection.** Provider billing patterns that shift suddenly or that show coordinated shifts across multiple providers are strong signals. Change-point detection on per-provider time series (billing volume, code mix, dollar-per-encounter) finds onset dates for drift. When multiple providers in a peer group share change-point dates, that's a red flag for coordinated activity.

**Sequence and pattern mining on patient journeys.** Some schemes express themselves as unusual service sequences across a patient's care (every patient who visits clinic A is referred to lab B within 72 hours, which runs toxicology panel C, which bills at amount D). Sequence mining or association rule mining on patient journeys can surface these.

**Embedding-based similarity search.** For a known-fraud case, find other providers whose feature embeddings are closest. "Providers who look most similar to this recently-indicted provider" is a high-value investigator query. Implemented as a vector store on provider embeddings.

A realistic progression: start with rules (for the legally-grounded patterns) plus statistical baselining (for upcoding and drift patterns) plus a first pass at graph features (provider-patient-referral concentration). Add Isolation Forest on provider features once enough data exists. Add supervised re-ranking once labels accumulate. Add GNN embeddings and advanced graph analytics as the program matures. Don't try to build all layers at once; you'll end up with a system you can't explain.

### The Graph Is the Secret Sauce

If there's one piece of the FWA detection toolkit that differentiates mature programs from immature ones, it's the relationship graph. Everything else can be done with flat tabular analytics and you'll catch a fraction of the money. The graph is where the big schemes live.

A useful FWA graph has node types that include:

- Individual providers (NPI level)
- Provider organizations (tax ID, facility NPI, corporate entity)
- Patients
- Services (CPT/HCPCS grouped into meaningful clusters)
- Claims
- Payments
- Ownership entities (who owns what)
- Geographic locations
- Corporate officers and directors (from state business filings and Sunshine Act)

And edge types that include:

- Rendered-service (provider performed service for patient)
- Billed (organization submitted claim for service)
- Paid (payer paid organization for claim)
- Referred (provider referred patient to organization or other provider)
- Prescribed (prescriber ordered medication dispensed by pharmacy)
- Ordered (provider ordered test performed by lab)
- Owns (entity owns all or part of another entity)
- Controls (entity has signatory or director authority over another)
- Co-located (entities share a physical address)
- Co-appears (entities appear together in ownership or officer records)

Graph construction is non-trivial: entity resolution is a first-class problem (multiple NPIs for the same physical provider, provider name variations, address normalization, corporate entities with opaque ownership structures). External data sources matter here: state business filings for corporate ownership, CMS's Open Payments (Sunshine Act) data for industry payments to providers, OIG's List of Excluded Individuals and Entities (LEIE), SAM.gov for federal exclusions, NPPES for provider demographics.

Once the graph is built, the high-value queries are surprisingly few:

- **Community detection.** Apply a community detection algorithm (Louvain, Leiden) to find tight clusters. Investigate clusters whose internal referral or billing concentration is high.
- **Referral concentration.** For each provider, compute what fraction of their referrals go to the top-1 and top-3 entities. Providers with >80% of referrals to a single DME supplier or lab are worth looking at.
- **Ownership cascades.** For each claim-receiving entity, trace the ownership up through layers of LLCs. Shared ownership across supposedly-independent entities is a major signal.
- **Co-location clusters.** Multiple "independent" providers, labs, and DME suppliers operating from the same strip mall or PO box. Often with overlapping officers.
- **Patient-sharing between providers.** Providers who share an unusually high fraction of patients, especially when the sharing is asymmetric (provider A always refers to provider B, but not vice versa).
- **Provider-patient density patterns.** A lab with a handful of referring providers that collectively account for 90% of volume. A DME supplier whose referring provider list is suspiciously short.
- **Temporal coordination.** Multiple providers or entities whose billing, revenue, or referral patterns all shift on the same dates (coordinated activity).

The graph analytics layer is where graph databases earn their keep. Traversing "find all entities within three hops of provider X, weighted by payment volume" is tolerable in SQL; in practice, it's cheaper and clearer in a native graph engine.

### Data Requirements and the Unglamorous Work

A lot of the difficulty in FWA detection is not the modeling. It's the data work underneath. The pipeline needs:

- **Clean claims data with all the fields.** Claims, remittance (835 data), eligibility, authorization records, denials. Include secondary-payer data, adjustments, and reversals. A claim that appears in the initial data feed and then is adjusted a week later needs to be tracked as a state change, not as two separate claims.
- **Provider demographics and lifecycle data.** NPPES (National Plan and Provider Enumeration System) for NPI basics. State licensure data for active/inactive status. LEIE for OIG exclusions. SAM.gov for federal contracting exclusions. Medicare enrollment data (PECOS). State business filings for corporate ownership.
- **Patient demographics and vital status.** Including date of death, because billing after patient death is an investigation-ready pattern by itself.
- **Clinical documentation.** Not always available upfront, but required for case development. Documentation review may happen via EMR integration (for patients seen in the payer's provider network), via document request (for fraud cases), or via chart audit. The pipeline needs to track which cases have documentation attached and which don't.
- **External data.** CMS Open Payments (Sunshine Act), state prescription monitoring programs, public court records, property records (for co-location checks), corporate registry data.
- **Historical investigation outcomes.** Your SIU's case files become the supervised-learning labels. They need structured fields (case type, outcome, confirmed loss amount, referral destination) and not just free-text notes.

Most organizations underestimate this data work. A reasonable FWA detection project spends 60% of the first year on data foundation and 40% on detection logic, and the teams that invert that ratio produce more alerts but not more cases.

### Alert Fatigue Has a Different Flavor Here

Alert fatigue shows up in every chapter in this book, and FWA has its own variety. In clinical contexts (Recipes 3.4, 3.5, 3.7), the consequence of alert fatigue is that clinicians ignore alerts and miss real clinical events. In FWA, the consequence is that investigators ignore the detector and build cases from other sources (tips, referrals from other agencies, internal leads). A detector that produces 500 candidates per week against an investigation capacity of 20 per month is not producing leads; it's producing noise that an investigator learns to tune out.

The design implications:

- **Prioritization is not optional.** The top-of-queue case has to be worth a full investigation. The hundredth case can be interesting but lower-priority. Ranking matters more than total flag count.
- **Estimated dollar impact should drive priority.** Investigators spend time, and time is expensive. A $50,000 case and a $5,000,000 case both take months of investigation. Prioritize by estimated loss exposure.
- **Evidence bundling is the unit of work.** An investigator doesn't want a score; they want a packet: representative claims, peer-comparison context, graph context, documentation samples, prior flags on this entity, prior case outcomes. The packet is the MVP.
- **Feedback loops must be structurally honest.** Investigators close cases with outcomes; those outcomes feed back to model tuning. But outcome granularity matters: "referred to OIG" is different from "educated and closed" is different from "adjusted claims and closed" is different from "referred to state Medicaid Fraud Control Unit." Don't collapse these; the nuance is the signal.
- **Suppression rules are politically sensitive.** An investigator who decides that provider X is legitimate should be able to suppress future alerts on that provider (with documentation of why and for what period), but those suppressions must be auditable. Suppression rules that are set and forgotten become blind spots; expire them by default.

### Regulatory and Legal Context Shapes the Architecture

Unlike most recipes in this book, the FWA pipeline is shaped heavily by law, regulation, and contract. The practical consequences:

**Legal privilege.** In some organizational structures, the investigation unit operates under legal privilege (the chief legal officer or general counsel oversees the SIU, and investigation work product is attorney work product). This has implications for data architecture: some of the analysis may need to be isolated from general analytics environments because discovery and privilege considerations apply. Coordinate with legal before designing the architecture.

**Referral obligations.** When a plan suspects Medicare or Medicaid fraud, it has specific referral obligations. 42 CFR 422.504(h) requires Medicare Advantage organizations to report suspected fraud to CMS. Medicaid managed care organizations have similar obligations under 42 CFR 438.608. These obligations create a compliance requirement for the detection pipeline (the pipeline must surface these cases) and a workflow requirement (once surfaced, the referral must be made within the required timelines).

**False Claims Act exposure.** Payers that fail to identify and recover overpayments can face False Claims Act liability (31 USC 3729-3733) if they knowingly retain overpayments. The detection pipeline's effectiveness is partly a compliance posture. Documentation that detection ran and produced results (or documentation that investigation was considered and did or did not happen) is itself important.

**HIPAA and Privacy Act.** PHI is involved end-to-end. Standard HIPAA controls apply (BAA, encryption, audit logging, least-privilege access). Additionally, when investigations share data with law enforcement, specific disclosure rules apply. 45 CFR 164.512(f) permits limited disclosure of PHI to law enforcement under specified conditions, and the infrastructure should support these workflows as first-class data handling, not as ad-hoc exports.

**State-specific anti-kickback and false claims laws.** Most states have their own false claims and anti-kickback statutes that track or extend federal law. Some (California, New York) have aggressive state-level enforcement. The detection rules need to be configurable per state, because what's reportable in one state may not be in another.

**Retention.** FWA investigation records are kept for years, often decades. CLIA, HIPAA, state laws, and statute-of-limitations considerations for FCA cases (up to ten years in some scenarios) all apply. Design storage retention accordingly. Don't delete investigation records lightly.

---

## General Architecture Pattern

At a conceptual level, the FWA detection pipeline has to ingest heterogeneous data continuously, maintain a relationship graph that reflects the current state of providers, entities, and claims, run multiple detectors (rule-based, statistical, graph-based, model-based) at different cadences, and feed a case management workflow where investigators do the real work. Underneath sits audit logging that would satisfy a federal subpoena, because the outputs of this system sometimes end up as evidence.

```
┌──────────────── FWA DETECTION PIPELINE ───────────────────────────┐
│                                                                   │
│   [Claims feed]         [Eligibility feed]      [Remittance]      │
│   [Authorizations]      [Denials]               [Provider data]   │
│   [Pharmacy claims]     [Lab orders]            [DME orders]      │
│   [State filings]       [Sunshine Act]          [OIG LEIE/SAM]    │
│   [Death master]        [Licensure data]        [NPPES/PECOS]     │
│           │                                                       │
│           ▼                                                       │
│   [Ingestion and Normalization]                                   │
│   (entity resolution, code harmonization, event deduplication)    │
│           │                                                       │
│           ▼                                                       │
│   [Unified Data Lake + Feature Store]                             │
│      │                                                            │
│      ├──► [Graph Construction]                                    │
│      │     (provider-patient-entity-payment-ownership graph)      │
│      │                                                            │
│      └──► [Per-entity Feature Tables]                             │
│            (provider, patient, facility, payment features)        │
│                                                                   │
│           │                                                       │
│    ┌──────┴────────────────────────────────────┬─────────────┐    │
│    ▼                                           ▼             ▼    │
│   RULES LAYER        STATISTICAL LAYER     GRAPH LAYER      ML    │
│                                                             LAYER │
│   [CCI edits]        [Z-scores peer]       [Community            │
│   [MUE]              [CUSUM drift]          detection]            │
│   [Medical           [Panel multivariate]  [Referral             │
│    necessity]        [Claim-level          concentration]        │
│   [Eligibility       Isolation Forest]     [Ownership            │
│    integrity]        [Patient journey      cascades]              │
│   [Anti-kickback     sequence mining]      [GNN embeddings]      │
│    structure]                                                     │
│                                                                   │
│           │                   │                │            │     │
│           └───────────────────┼────────────────┼────────────┘     │
│                               ▼                ▼                  │
│               [Evidence Aggregator]                               │
│               (per-entity case bundle: flags, ranked            │
│                evidence, estimated loss exposure,                 │
│                prior cases, graph context)                        │
│                               │                                   │
│                               ▼                                   │
│               [Prioritization and Ranking]                        │
│                               │                                   │
│                               ▼                                   │
│               [Case Management Workflow]                          │
│                 │                                                 │
│                 ├─► Analyst triage (enrich, dismiss, develop)     │
│                 ├─► Medical records review (NLP-assisted)         │
│                 ├─► Investigation workbench                       │
│                 ├─► Legal and compliance review                   │
│                 └─► Outcomes (adjust, recoup, refer, prosecute)   │
│                                                                   │
│               [Feedback Capture]                                  │
│                 (case outcomes, dispositions, recoveries,         │
│                  confirmed-loss attribution)                      │
│                               │                                   │
│                               ▼                                   │
│               [Retraining / Rule Tuning / Threshold Review]       │
│                                                                   │
└───────────────────────────────────────────────────────────────────┘
```

**Ingest.** FWA is unusual for the diversity of inputs. Claims (837), remittance (835), eligibility (270/271), authorization, denials. Provider enumeration (NPPES), enrollment (PECOS), licensure (state data), exclusions (LEIE, SAM). External context: Open Payments (Sunshine Act), state business filings, property records, death master files. Internal operations: denials, member complaints, SIU tips, case outcomes. Different sources have different refresh cadences (claims daily, LEIE monthly, state filings annually), different latencies, and different reliability. The ingest layer has to normalize all of this and track source-of-truth for each data element.

**Entity resolution.** Before anything else, the same real-world entity (provider, organization, patient, owner) must be identified across sources. A provider may appear in claims as one NPI, in Medicare enrollment under another, in state business filings as a corporate owner with a different name, in Sunshine Act data under yet another identifier. Standard identifiers (NPI, EIN, SSN) help but don't fully resolve the problem; names, addresses, license numbers, and directorships all contribute. This is the same work Recipe 5.x (Entity Resolution) covers in depth; the FWA pipeline is one of the most demanding consumers of entity resolution.

**Unified data lake and feature store.** The normalized and entity-resolved data lands in a data lake. Analytical feature tables (per-provider, per-patient, per-facility, per-entity) are computed from the lake and kept in a feature store with point-in-time semantics so that historical flags can be reproduced.

**Graph construction.** Nodes for every entity, edges for every relationship (rendered, billed, paid, referred, ordered, owns, controls, co-located). The graph refreshes on a schedule (typically daily or weekly) because relationships evolve. External data sources (Sunshine Act, state filings) refresh less frequently but are essential; they're where ownership and relationship data come from.

**Rules layer.** DMN-based or equivalent rules engine evaluating every claim or every provider-day against hundreds of encoded rules. CCI edits, medically unlikely edits (MUEs), medical necessity policies, eligibility integrity checks, provider-exclusion checks, and anti-kickback structural checks all run here. Output is rule-based flags with explicit rule IDs and input-value documentation.

**Statistical layer.** Per-provider, per-patient, per-specialty z-scores and CUSUM monitoring on the feature tables. Panel-level (claim-cluster) Isolation Forest for multivariate outliers. Peer-group definition drives the z-score baselines. Output is statistical flags with quantitative measures (how many sigma from peer mean; which dimension drove the flag).

**Graph layer.** Community detection on the full graph. Per-entity graph features (degree centrality, betweenness, clustering coefficient, eigenvector centrality). Referral-concentration metrics. Ownership-cascade analytics. GNN embeddings for similarity search. Output is graph-based flags with subgraph visualizations attached (the subgraph is what the investigator will look at).

**ML layer.** Supervised classifiers trained on prior case outcomes, used as re-rankers on top of the rule, statistical, and graph flags. Feature inputs include all flag outputs, raw features, graph features, and patient-mix adjustments. Output is a case-level probability-of-significant-outcome score.

**Evidence aggregator.** Combines flags from all four layers into a per-entity (per-provider, per-patient, per-facility) case bundle. Ranks the evidence by estimated dollar impact, severity, and legal or contractual basis. Attaches graph context (the subgraph within three hops, weighted by payment flow), peer-comparison context (how this provider compares to their peer group on the flagged dimensions), prior-case context (has this entity been flagged before, what were the outcomes), and representative claims (the specific claims that triggered each flag).

**Prioritization and ranking.** Cases sorted by estimated loss exposure, then by confidence, then by strategic priority (certain scheme types get priority because of program focus or regulatory exposure). The ranking is tunable because program priorities change (this quarter, focus on toxicology mills; next quarter, focus on DME).

**Case management workflow.** This is a workflow application, not a data pipeline. Analysts receive triage cases (enrich with a quick review, dismiss or promote). Investigators work developed cases (request records, interview providers, coordinate with legal, issue determinations). Clinical reviewers assess medical necessity and documentation. Legal reviews for litigation or referral. Each step has status tracking, time-to-resolution metrics, and evidence accumulation. The NLP-assisted documentation review (LLMs summarizing records, flagging documentation cloning, assessing medical-necessity justification) lives here as a productivity tool.

**Feedback capture.** Every case resolves with an outcome: closed no-action, closed with provider education, closed with claim adjustment, referred to payment integrity collection, referred to state Medicaid fraud control unit, referred to OIG, referred to DOJ, criminal referral, civil settlement, administrative penalty. The outcome, the confirmed loss amount, the time-to-resolution, and the evidence that was decisive all get captured structurally, not just in free text.

**Retraining and rule tuning.** On a quarterly (sometimes monthly) cadence. Review false-positive and true-positive rates by rule, by detector, by scheme type. Retire or re-threshold detectors with high noise. Retrain supervised classifiers on accumulated labels. Update rule libraries when coverage policies, CCI edits, or regulatory rules change. Review suppression rules for staleness.

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter03.06-architecture). The Python example is linked from there.

## The Honest Take

The graph is the thing that separates mature FWA programs from immature ones, and I watched more than one team skip it because "we'll build graph later" and then watch their SIU operate at a fraction of its potential for two years. If you're building FWA detection and you're not going to build the graph, understand that you're doing payment integrity plus some anomaly detection, which is fine, but it's not FWA. The highest-dollar cases, the organized schemes, the ones that pay for the program three times over, are almost all relational. No flat-feature-vector model will find them. If you have the budget for one ambitious piece of the architecture, make it the graph, not a fancier supervised model.

Investigators produce the work, not the model. The detection pipeline produces scored candidates. The investigators produce cases, and cases produce recoveries. Scaling investigation capacity is almost always a bigger lever than improving model precision. A 10% precision gain on a system where investigators are running at capacity produces zero additional recoveries. Hiring two more investigators on the same system produces substantially more recoveries. The right investment ratio is often 60% people and 40% technology, not the other way around. Budget accordingly.

The rules engine is underappreciated. I've seen teams who wanted to skip rules entirely ("we have ML") and who then spent six months rediscovering that CCI edits, MUEs, coverage policies, and post-mortem billing checks catch a disproportionate share of actionable cases. The ML can augment rules but can't replace them. And the rules catch cases that are easier to pursue because the legal basis is clear: a claim submitted after the provider's date of death is a bright-line rule, not a judgment call. Build the rules layer first, operate it, and let it work while the ML layers are under construction. Some organizations run for years with just a mature rules engine and get substantial value.

Peer group definition is an ongoing program, not a one-time setup. Every team I've worked with has gone through at least two major re-definitions of peer groups because the first cut had flaws. Too broad, too narrow, missing a subspecialty distinction that mattered, failing to account for practice setting, treating rural and urban as the same. Plan for peer group definition to be a living artifact that's reviewed quarterly and re-tuned based on operational experience.

Labels are worth fighting for, even though the fight is ugly. The structural problems with FWA labels (long latency, self-confirming bias, outcome ambiguity) are real. They don't go away. But organizations that invest in structured outcome capture, periodic random sampling of unflagged populations to fill label gaps, and careful label provenance tracking produce supervised models that actually work. Organizations that don't end up with models that re-learn their existing rules. The discipline is worth it.

The legal relationship matters more than I initially understood. The most productive FWA programs I've seen operate with close ongoing collaboration between the SIU, payment integrity, clinical review, legal, and compliance. The worst ones I've seen had SIU operating in isolation, handing cases to legal only at referral time, and learning too late that their evidence standards didn't match legal standards. Build the relationships early. Invite legal counsel into the program design, not just the referral reviews.

The LLM-assisted documentation review is genuinely useful, with caveats. Reading 200 pages of clinical documentation to assess whether a level-5 office visit was supported takes a clinical reviewer several hours. An LLM produces a first-pass assessment in minutes. The reviewer then validates, refines, or overturns the assessment. Net effect: two to five times more documentation reviews per reviewer-hour. But the LLM produces confident-sounding wrong answers sometimes, especially on specialty-specific documentation where the norm looks different than the LLM has seen. Treat the LLM as the junior analyst who prepares the material; the senior analyst still makes the call. Don't let the LLM output be the case summary that goes to legal.

The trap I see most often: flag rate as the primary metric. Program directors get asked "how many cases did we detect?" and the natural answer is the flag count. High flag counts drive low precision. Low precision drives investigator frustration. Investigator frustration drives program abandonment. The metrics that matter are recoveries, case-level outcomes, and recovery-to-cost ratio. Flag count and precision are internal tuning metrics, not leadership metrics. Educate leadership accordingly. If you can't defend your program on recoveries and investigator productivity, the flag count won't save you.

Adversarial evolution is faster than most teams expect. I watched a team roll out a great modifier 59 detector. Three months later, the providers who'd been using modifier 59 had shifted to modifier 25 patterns. Six months later, they'd shifted to modifier 76/77 patterns. The detector didn't degrade; the adversary adapted. Mature operations include a "scheme-watch" function: analysts whose job is to read OIG enforcement actions, DOJ prosecutions, industry publications, and adversarial intelligence sources to understand the current scheme landscape. The detectors follow the scheme-watch, not the other way around.

The thing I'd do differently: I'd build the case management and outcome capture before the third detector. I've been on projects that built five detectors before the case management system, and by the time the case management was built, we had backlogs of flags with no place to track them. Inversely: build the case management, a single good rules engine, and one statistical layer, operate them, then add sophistication. The second detector is worth less than the operational discipline built by running the first one.

The politics: compliance, legal, operations, and the technology team all have different vocabularies for this problem. Operations talks about fraud in dollar and case terms. Compliance talks about regulatory risk. Legal talks about causes of action and evidence standards. The tech team talks about precision, recall, and AUC. A functional program has a shared vocabulary that translates across these. Producing a case summary that answers "what did we detect, what does it violate, what's the dollar exposure, what do we need to decide, and what's the next action" is more valuable than any single metric.

The moral tension: FWA work involves accusing people, sometimes wrongly. A wrongly-accused provider has lost money, time, and professional reputation. Taking that seriously affects how thresholds are set, how investigations are opened, how decisions are communicated, how appeals are handled. The temptation to over-automate (let the model decide who gets audited) is real and it's wrong. The final decision to pursue an investigation should involve human judgment, and that human should have access to the full context, not just the score.

---

## Related Recipes

- **Recipe 3.1 (Duplicate Claim Detection):** Duplicate detection is a component of FWA detection for phantom billing and identity theft patterns. Architectures share ingest and entity resolution.
- **Recipe 3.3 (Billing Code Anomalies):** The statistical detection layer of FWA overlaps heavily with billing code anomaly detection. Provider-level peer comparison, CUSUM drift, and Isolation Forest techniques all apply. In mature deployments, the billing code anomaly detector is one component of the FWA pipeline rather than a separate system.
- **Recipe 3.4 (Medication Dispensing Anomalies):** Pharmacy-specific fraud patterns (controlled substance diversion, prescription mills) overlap with medication dispensing anomaly detection. Shared architecture for pharmacy claim processing and prescriber-dispenser graph analysis.
- **Recipe 3.5 (Lab Result Outlier Detection):** Toxicology lab billing patterns (one of the most prolific FWA categories) benefit from both lab-side outlier detection and FWA-side billing pattern detection. The same lab showing anomalous testing intensity and anomalous billing patterns is a strong multi-layered signal.
- **Recipe 3.9 (EHR Access Pattern Anomalies):** Insider fraud (employees accessing data to facilitate fraud schemes) uses access pattern anomaly techniques. Shared architectural patterns for behavior-baseline detection.
- **Recipe 5.x (Entity Resolution):** Entity resolution is foundational to FWA detection. Provider, organization, patient, and ownership entity resolution drives the quality of the entire downstream pipeline.
- **Recipe 8.x (NLP / Clinical Text Normalization):** Documentation review for medical necessity and clone detection uses clinical NLP techniques.
- **Recipe 13.x (Knowledge Graphs):** The FWA relationship graph is a domain-specific clinical and financial knowledge graph. Chapter 13 covers graph construction and maintenance patterns that apply directly.
- **Recipe 2.x (LLM / Generative AI):** LLM-assisted documentation review, case summarization, and investigator assistance use patterns from Chapter 2.

---

## Tags

`anomaly-detection` · `fraud-detection` · `payment-integrity` · `siu` · `upcoding` · `unbundling` · `phantom-billing` · `kickbacks` · `collusive-networks` · `graph-analytics` · `community-detection` · `gnn` · `neptune` · `isolation-forest` · `cusum` · `sagemaker` · `feature-store` · `clarify` · `opensearch` · `knn-vector-search` · `dynamodb` · `bedrock` · `comprehend-medical` · `clean-rooms` · `cci` · `mue` · `leie` · `stark-law` · `anti-kickback` · `false-claims-act` · `hipaa` · `medium-complex` · `production` · `payer` · `provider`

---

*← [Recipe 3.5: Lab Result Outlier Detection](chapter03.05-lab-result-outlier-detection) · [Chapter 3 Preface](chapter03-preface) · [Next: Recipe 3.7 - Patient Deterioration Early Warning →](chapter03.07-patient-deterioration-early-warning)*
