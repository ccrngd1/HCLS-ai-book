# Recipe 5.8: Privacy-Preserving Record Linkage ⭐⭐⭐⭐

**Complexity:** Complex · **Phase:** Production · **Estimated Cost:** ~$0.001-0.01 per linked pair at population scale, dominated by the cryptographic-token generation, the secure-exchange infrastructure, and the governance-and-audit overhead rather than per-record matching fees (depends on the protocol chosen, the participant count, the volume of records exchanged per cycle, and the strictness of the trust framework the institution operates under)

---

## The Problem

Two people are sitting at the same table at a research conference. One of them works for an academic medical center that runs a large diabetes outcomes study; the other works for a regional payer whose membership overlaps substantially with the academic medical center's patient panel. They have been talking for forty-five minutes about a research question they both want to answer: among patients with type-2 diabetes who started on a GLP-1 receptor agonist between 2022 and 2025, how many had a major adverse cardiac event within twenty-four months, and how does that rate vary by baseline kidney function, baseline weight, and continuity of pharmacy fill? The clinical data lives in the academic medical center's EHR. The pharmacy fill data lives in the payer's claims system. Neither party has the other's data. Neither party can legally hand the other party a flat file of their members' demographics and ask "match these against your patients." Neither party wants to (the academic medical center is wary of any disclosure that goes beyond minimum necessary; the payer is wary of any disclosure of its membership roster). They both, separately, know that the answer to the research question is sitting in the intersection of their data, and that the intersection is large enough to power the study, and that getting at it will require linking the records on demographic features they would each prefer not to expose.

This is the privacy-preserving record linkage problem. Two or more organizations have records that probably overlap. They each have demographic features (name, date of birth, sex, address, sometimes SSN, sometimes phone) that, in combination, would let a matcher determine which records refer to the same person. The conventional approach is the same matcher you have seen throughout this chapter: each party hands its data to a trusted intermediary, the intermediary runs a probabilistic-record-linkage matcher, and the linked records flow into the analysis. The conventional approach assumes you can hand over the data. In an increasing fraction of healthcare-data-sharing scenarios, you cannot.

The reasons vary. Sometimes the data-use agreement constrains the disclosure to the linkage purpose only, with no further use of the demographic features by the intermediary. Sometimes the participants are competitors who do not want the intermediary to learn anything about each other's roster sizes, demographic compositions, or operational patterns. Sometimes the legal posture is hostile: a state law that constrains disclosure of certain record types (substance-use treatment under 42 CFR Part 2, reproductive-health-care records in post-Dobbs jurisdictions, gender-affirming-care records in jurisdictions with specific suppression requirements), or an institutional policy that classifies any disclosure of demographic features as a privacy event requiring explicit patient consent. Sometimes the intermediary itself is the concern: even with a BAA, the institution does not want to expose the entirety of its registration roster to a third party that does not need to see it. Sometimes the linkage spans national borders and the data-protection regimes (GDPR, PIPEDA, the U.K. Data Protection Act, Australia's Privacy Principles) explicitly prohibit the transfer of identifying data even under contract. <!-- TODO: confirm at time of build; the international-data-transfer landscape continues to evolve, and the specific applicability of GDPR to healthcare-data linkage with U.S. counterparts is governed by adequacy decisions and standard contractual clauses that change. -->

The harder versions of the question are everywhere:

You are the data-science team at a hospital network running a multi-site clinical trial for a new chemotherapy combination. You have enrolled three hundred patients. The pharmaceutical sponsor wants to know, for each enrolled patient, whether they filled a prescription for the trial drug at any pharmacy in the network's region (including pharmacies outside the hospital network's own fill data). The pharmacy network's own data lives at the regional pharmacy benefit manager, who will not disclose its membership roster to the hospital network and cannot be granted access to the trial enrollment list. Both parties want to answer the question. Neither can simply hand over data.

You are running a state cancer registry. Cancer registries are statutorily required to receive case reports from every accredited oncology practice in the state, and they routinely encounter the same patient reported by multiple sources (the surgical pathology report from the diagnosing pathologist, the treatment summary from the oncology practice, the death record from vital records). The registry's matcher consolidates these reports into a single canonical case. The matcher runs against the registry's own record store. Now suppose the registry wants to enrich its data with social-determinant features from the state's social-services agency, or with environmental-exposure features from the state's environmental-health agency, or with mortality-cause-detail data from a national death-index that the state agency has access to but cannot redistribute. The linkage between the cancer-registry records and the external features has to happen without the cancer-registry sharing its case roster with the social-services agency, the environmental-health agency, or the national-death-index custodian, because each of those agencies has its own data-use agreement constraining what the registry's case data can be used for.

You are the analytics lead for an accountable-care organization that needs to know whether its attributed patients had emergency-department visits at hospitals outside the ACO's own network during the measurement year. Out-of-network ED visits drive total-cost-of-care, and the ACO's contract with the payer is structured around total-cost-of-care benchmarks. The out-of-network hospitals are the ACO's competitors; they have no commercial relationship with the ACO and no incentive to disclose their patient registries. The ACO's payer (a regional Blue Cross plan) has the claims data showing the ED visits but does not share its full membership roster with the ACO. The ACO needs to link its attributed-patient list to the payer's claims data without disclosing the attributed-patient list to the payer (the ACO's attribution methodology is proprietary) and without the payer disclosing its membership demographics to the ACO. The linkage has to produce, per attributed patient, a yes/no flag for "had at least one out-of-network ED visit in the measurement year" and the count of such visits, with no other patient-level disclosure.

You are running a precision-oncology research consortium that combines clinical-trial enrollment data from twenty academic medical centers, genomic profiling data from a commercial sequencing vendor, and outcomes data from the participating institutions' tumor registries. The consortium's research question requires per-patient linkage across the three data sources for the patients enrolled in the relevant trial cohorts. Each academic medical center is willing to participate in the consortium under a master research agreement but is not willing to disclose its entire trial-enrollment list to the other nineteen centers (the per-cohort enrollment numbers are competitive information). The sequencing vendor will not disclose its full client list to any of the medical centers. The tumor registries operate under state-level data-use agreements that constrain what their case data can be used for and by whom. The linkage has to produce per-patient triplets (trial-arm enrollment, genomic profile, outcomes-registry events) without any party seeing the other parties' rosters.

You are working on a public-health surveillance project that combines a state immunization registry with a state hospitalization registry to estimate vaccine effectiveness against severe disease. The immunization registry has detailed vaccination histories. The hospitalization registry has detailed inpatient encounters. Both registries are operated by the state public-health department, and a year ago, the integration was a within-department analytic project. After a state law restricting cross-program data sharing within state agencies passed last year, the same analysis now requires a privacy-preserving linkage even though both data stores are owned by the same state agency. <!-- TODO: confirm at time of build; the post-2024 state-level public-health-data-sharing landscape continues to evolve in response to specific policy debates around immunization-data confidentiality and around reproductive-health-care data; the specific state-law provisions are jurisdiction-specific. --> The technical problem is the same as the cross-organizational case; the regulatory framing has shifted.

You are the operations lead for a national health-information-exchange-of-exchanges (a TEFCA QHIN-of-QHINs scenario, looking five years out) attempting to perform a national-scale outcomes-research linkage between a Medicare claims population and a federation of state Medicaid populations. The Medicare data is held by CMS under its disclosure rules; the Medicaid data is held by each state under its own disclosure rules; the operational research entity is a contracted federal research consortium. Direct exchange of the demographics-and-identifiers across the participating state Medicaid agencies is constrained by each state's Medicaid disclosure rules, which vary. The linkage has to operate against fifty-plus state Medicaid populations, the Medicare population, and the consortium's research enrollment list, in a way that preserves each state's authority over its own data and does not aggregate any state's roster at any single point.

You are operating a pharmaceutical-real-world-evidence platform that combines de-identified claims data from a commercial claims aggregator, EHR data from a hospital network, and laboratory data from a national reference lab. The de-identification on the claims data is robust enough that the data is technically not PHI, but the linkage between the claims and the EHR records requires re-identifying enough demographic detail to match the records. The pharmaceutical sponsor is the analytic consumer; the linkage step has to happen at a level of indirection that does not give the sponsor any pre-linkage demographic exposure. The architecture is a tokenization service: a third-party tokenizer ingests the demographics from each contributing source, produces irreversible tokens, and emits the tokens-plus-payload to the analytic store, where the linkage operates on the tokens rather than on the demographics. Several commercial tokenizers operate this pattern at scale; the architectural question is what the institution's posture is toward each tokenizer and whether the privacy-preserving claims of the tokenizer hold up under the institution's own threat model. <!-- TODO: confirm at time of build; the tokenization-service ecosystem (Datavant, HealthVerity, IQVIA, others) continues to evolve, and the specific cryptographic primitives, the trust-architecture details, and the audit-and-compliance posture of each vendor are vendor-specific. -->

This is the recipe. Privacy-preserving record linkage (PPRL) is the entity-resolution problem of "given that two or more organizations have records that probably overlap on the same real-world entities, and given that the organizations cannot or will not exchange the raw demographic data that a conventional matcher would compare, produce the linkage with cryptographic, statistical, or trust-architectural primitives that let the matcher do its job without exposing the inputs." The matching core is the same probabilistic-record-linkage core you have seen throughout the chapter, with the twist that the comparisons happen on cryptographically-transformed proxies of the demographic features rather than on the features themselves. The accuracy ceiling is, for almost every protocol, lower than direct matching, because the cryptographic transforms lose information. The operational complexity is higher, because the trust architecture, the cryptographic-key management, the protocol-execution coordination, and the audit-and-governance posture all grow new dimensions. The reason this recipe is in the chapter is that the legal and trust frameworks around healthcare-data sharing are tightening, not loosening, and you should know what your options are when "send me your data" stops being one of them.

It is in the complex tier because the cryptographic and statistical techniques add substantive overhead the conventional matcher does not have, the regulatory and trust frameworks required for any production deployment are non-trivial to negotiate, the match quality is genuinely lower than direct matching and the institution has to decide whether the loss is acceptable for the use case, and the technology is still emerging in healthcare-specific implementations even though the underlying cryptographic primitives are decades old. Most institutions that operate PPRL in production have built it once for one specific use case (a research collaboration, a multi-state public-health initiative, a commercial tokenization integration) rather than as a general-purpose capability, and the lessons each institution has learned are specific to the protocol they chose and the trust architecture they negotiated. This recipe is the architecture-level scaffolding; the protocol selection and the trust framework are choices the institution makes within it.

Let's get into how you build it.

---

## The Technology: Privacy-Preserving Record Linkage

### The Conventional Matcher Versus the Privacy-Preserving Matcher

In recipe 5.5, the cross-facility matcher operates against a federated architecture: each facility has its own MPI; queries route through an HIE that maintains a cross-facility index; the index is built from demographic features each facility chose to disclose under the HIE's data-use agreement. The disclosure is real (the HIE sees the demographics) but bounded (the HIE's BAA constrains what it does with them). The matching itself is a conventional probabilistic-record-linkage matcher operating on the disclosed features.

Privacy-preserving record linkage starts from a different assumption. The disclosure is not bounded by a BAA; it is constrained by cryptography. Each participating organization transforms its demographic features into a representation that the matcher can compare for similarity but that does not reveal the underlying features to any party that does not already know them. The transformation is one-way (you cannot recover the input demographics from the transformed representation under any computationally feasible procedure) but similarity-preserving (records that referred to the same person produce transformed representations that are close to each other under the matcher's similarity measure).

The matcher operates on the transformed representations and produces match decisions. The match decisions are returned to the participating organizations, who use them to do whatever they were going to do (combine clinical and claims records, produce a research linkage, route an ED-visit cost-share signal, populate a tokenized data warehouse). The underlying demographic data never leaves the organization that holds it; only the transformed representation does, and the transformed representation is, by construction, not informative about the demographics it derived from beyond the similarity signal that the matcher needs.

The trick is in the construction. A cryptographic hash (SHA-256 of "John Smith") is one-way but it is also brittle: any change in the input ("Jon Smith") produces a totally different hash, so the matcher cannot use it for fuzzy comparison. Most healthcare demographic data is messy enough that exact-hash matching produces miss rates so high that the linkage is operationally useless. The constructions that work for PPRL trade off some of the hash's one-way-ness against retaining enough similarity-preservation that the matcher can be tuned to the demographic-noise distribution.

### Three Families of PPRL Protocols

Privacy-preserving record linkage protocols fall into three families that differ along the trust-architecture axis (who is trusted to hold what), the cryptographic primitive (what the transform actually is), and the operational complexity (what the participants have to coordinate).

**The trusted-third-party tokenization model.** A third party (the tokenizer) is trusted to receive the demographic features from each participating organization, apply a cryptographic transform with a shared secret (a salt, a keyed hash function, or a deterministic encryption with a private key), and produce tokens. The tokens are returned to the organizations; the organizations exchange the tokens (or send the tokens to a downstream analytic consumer); the analytic consumer joins on the tokens and produces the linked output. The tokenizer is trusted not to retain the demographics, not to learn the linkage between organizations, and not to disclose the tokens to anyone other than the contracted parties. This is the model behind most commercial healthcare tokenization services (Datavant, HealthVerity, others). <!-- TODO: confirm at time of build; the commercial-tokenizer landscape continues to evolve, and the specific cryptographic primitives, the trust-architecture details, and the operational specifics are vendor-specific. --> The trust assumption is real: the tokenizer is a third party with full visibility into both organizations' demographic feeds, and the audit-and-compliance posture of the tokenizer is a load-bearing component of the architecture's privacy claim. The advantage is operational simplicity: the participating organizations send their data to one place under a familiar BAA-and-data-use-agreement structure, and the cryptographic primitives are well-understood.

**The Bloom-filter-based encoding model (and its descendants).** The participating organizations agree on a shared cryptographic salt and a shared Bloom-filter parameterization (filter size, hash-function count, n-gram tokenization scheme). Each organization, on its own infrastructure, transforms each record's demographic features into a Bloom filter: the demographic-feature string is split into n-grams, each n-gram is hashed by k cryptographic hash functions parameterized by the shared salt, and the resulting bit positions in the Bloom filter are set. The Bloom filters are exchanged between the organizations or sent to a designated linkage agent that performs the matching. The matcher computes pairwise similarity between Bloom filters using the Sørensen-Dice coefficient (or Jaccard, or Tversky) and applies thresholds. Records whose Bloom filters score above the threshold are declared matches. The trick is that the Bloom filter is a compact, similarity-preserving fingerprint of the demographic-feature string: edit-distance-close strings produce Bloom filters that are close in Sørensen-Dice space, but a Bloom filter cannot be reverse-engineered to recover the underlying string. The cryptographic-long-term-key (CLK) construction generalizes this to multi-feature records by combining per-feature Bloom filters into a single record-level Bloom filter with feature-specific bit-allocation. <!-- TODO: confirm at time of build; the CLK construction was introduced in the academic record-linkage literature in the early 2010s and has been refined repeatedly; the open-source `anonlink` toolkit from the Confidential Computing Consortium implements current-best-practice variants. --> The trust assumption is weaker than the tokenizer model (no third party sees the demographics directly) but stronger than zero-trust (the participants have to trust each other to use the agreed-upon parameterization and to not retain bloom-filter-to-demographic mappings of their own data that would let them reverse-engineer their counterparty's demographics). The advantage is that the demographic data never leaves each organization in any form, and the cryptographic-key custody is symmetric across participants.

**The secure-multi-party-computation (SMPC) and private-set-intersection (PSI) model.** The participating organizations execute a cryptographic protocol that, by construction, lets them jointly compute the matching function on their inputs without any party learning anything about the other party's inputs beyond what is implied by the matching function's output. Several specific cryptographic primitives instantiate this idea: garbled circuits, secret-sharing protocols (Shamir, replicated, additive), oblivious transfer, homomorphic encryption (the matcher's similarity computation runs on encrypted features and produces an encrypted match decision that only the receiving party can decrypt), and zero-knowledge proofs (a participant proves that its input satisfies some property without revealing the input). Private-set-intersection is the special case of "compute the intersection of the participants' sets without revealing the non-intersecting elements." <!-- TODO: confirm at time of build; the SMPC and PSI ecosystem continues to mature, with multiple open-source toolkits (MP-SPDZ, EMP-toolkit, OpenMined PSI, Microsoft SEAL for homomorphic encryption) and a small number of commercial deployments in healthcare-adjacent domains; healthcare-specific production deployments are still uncommon as of writing. --> The trust assumption is the strongest of the three families (no third party, no shared salts that one party could pre-compute against): the cryptographic protocol itself enforces the privacy guarantee. The disadvantages are operational: the protocol typically requires multiple rounds of network exchange between the participants during the computation, the computational cost per record is orders of magnitude higher than the alternatives, and the protocol's correctness depends on faithful execution by the participants (semi-honest versus malicious adversary models matter). For most current healthcare PPRL deployments, SMPC is operationally infeasible at population scale; the technique is used for special cases where the trust posture demands it and the volumes are small enough.

Production healthcare PPRL deployments are usually one of the first two families, with the choice driven by the trust posture the participants are willing to negotiate, the operational tooling each organization has, the volume of records to be linked, and the regulatory framework that governs the linkage. The third family is operationally important to know about because the regulatory expectations are evolving and an institution that builds a PPRL capability today should be aware of the protocols its trust framework may require it to adopt in five years.

### What the Bloom Filter Encoding Actually Does

Walk through the Bloom-filter-based encoding because it is the workhorse of current academic and operational PPRL deployments, and because understanding it makes the entire family of techniques clearer.

Take a single demographic-feature string: "John Smith". Tokenize it into bigrams: `_J`, `Jo`, `oh`, `hn`, `n_`, `_S`, `Sm`, `mi`, `it`, `th`, `h_` (the underscores are start-and-end markers that improve robustness on short strings). Now you have eleven bigrams. The shared cryptographic salt is, say, a 256-bit random value that the participating organizations have agreed on in advance through whatever trust mechanism the protocol specifies. Configure k = 30 cryptographic hash functions parameterized by the salt (HMAC-SHA-256 with thirty different parameterization keys derived from the salt is one common construction). Allocate a bit array of size m = 1024.

For each bigram, compute the k hash values, mod m, and set the corresponding bit positions in the array. After processing all eleven bigrams, you have a 1024-bit array with up to 11 × 30 = 330 bit positions set (some bit positions may be set by multiple bigrams; the actual number set is somewhat less than 330 due to collisions). This is the Bloom filter for "John Smith".

Now do the same for "Jon Smith": tokenize into bigrams (`_J`, `Jo`, `on`, `n_`, `_S`, `Sm`, `mi`, `it`, `th`, `h_`), hash each bigram with the same k functions and the same salt, set the corresponding bits in a fresh 1024-bit array. The Bloom filter for "Jon Smith" shares most of its bigrams with the Bloom filter for "John Smith" (the difference is `oh`-and-`hn` versus `on`; the rest of the bigrams are identical). The two Bloom filters share most of their set bits.

The Sørensen-Dice coefficient between the two Bloom filters is `2 * |intersection of set bits| / (|set bits in A| + |set bits in B|)`. For "John Smith" versus "Jon Smith" with this parameterization, the coefficient is around 0.94. For "John Smith" versus "Jane Smith", it is around 0.85. For "John Smith" versus "Maria Garcia", it is around 0.18. The matcher consumes these similarity scores in the same Fellegi-Sunter-style probabilistic combiner that recipe 5.1 uses, with the per-feature similarity scores derived from per-feature Bloom-filter comparisons rather than per-feature string-edit-distance computations.

The construction has two properties that make it useful for PPRL.

It is one-way. Recovering "John Smith" from the Bloom filter would require enumerating the set of plausible inputs, computing the Bloom filter for each, and finding the input whose Bloom filter matches. The bigram tokenization, the per-feature encoding, and the cryptographic-hash construction make this enumeration computationally expensive in proportion to the cardinality of the input space. For a known-template input (a name from a known population, a date from a known range), the enumeration is feasible in principle and PPRL deployments mitigate this with a combination of large m, large k, the cryptographic salt that prevents pre-computation by an attacker, and operational discipline that limits which parties have access to the Bloom filters and for how long. <!-- TODO: confirm at time of build; the security analysis of Bloom-filter encodings has identified specific attacks (the Vatsalan-and-Christen analysis, the Schnell-and-Borgs analysis, the Kuzu-et-al frequency-attack analysis) and a series of defensive measures (random hashing, balanced encodings, salting, hardening) have been proposed and adopted with varying degrees of operational impact. -->

It is similarity-preserving. The Sørensen-Dice coefficient on Bloom filters is monotonically related to the underlying string-edit-distance similarity, with a tunable trade-off between similarity precision and one-way-ness governed by the choice of m, k, and the n-gram tokenization scheme. The matcher's accuracy on Bloom-filter-encoded data is genuinely lower than on plaintext data (typical reductions are five to fifteen percentage points in match-rate for the same false-acceptance threshold, but the loss varies by population and parameterization), but it is high enough to produce useful linkages for most operational use cases.

### What the Matching Layer Has to Capture

A working PPRL deployment has at least eight dimensions that a conventional matcher does not.

**A shared cryptographic salt and a shared parameterization.** The participating organizations agree, before any encoding, on the salt, the n-gram size, the Bloom-filter size, the hash-function count, and the per-feature bit allocation. The agreement is a precondition for any encoding to be comparable. The agreement is established through whatever trust mechanism the protocol specifies (a cryptographic key-exchange ceremony, a third-party-mediated key custody, a hardware-security-module-enforced shared secret). The salt is rotated on a defined cadence; rotation invalidates all previously-encoded data and requires re-encoding.

**A protocol-specific trust architecture.** Who has access to the encoded data and for how long is part of the protocol design. In the tokenizer model, the tokenizer has the demographic data temporarily and the encoded data thereafter. In the Bloom-filter model, each organization has its own demographic data and the encoded data of all participants temporarily (during the linkage) and the linkage results thereafter. In the SMPC model, no party has any other party's data at any point, but the protocol's network exchanges have to be audit-logged. The audit log of who accessed what and when is the trust architecture's enforcement mechanism.

**A linkage-result-disclosure policy.** The matcher produces match decisions; the participants consume the decisions in their downstream analyses. The disclosure of the match decisions is itself a privacy event: knowing that a particular record in organization A's data matches a particular record in organization B's data is a form of demographic disclosure (you have learned that the same person exists in both organizations). The protocol design constrains what the disclosure looks like (per-record yes/no flags, encrypted intersection counts, aggregated cohort sizes) and to whom (the analytic consumer, the participating organizations, neither). Some protocols return only the size of the intersection (private-set-intersection-cardinality, PSI-CA) without revealing which specific records intersected; others return the per-record matches; others return the per-record matches but only to one designated party.

**A re-identification risk model.** Even encoded data can be re-identified by an attacker who has auxiliary information (a list of plausible inputs with their expected encodings, a frequency analysis of the encoded data against a known population, a side-channel observation of the encoding process). The protocol design addresses re-identification risk through specific defenses (random hashing that varies the hash-function-to-bit-position mapping per record, balanced encodings that ensure each Bloom filter has a similar number of set bits to defeat frequency analysis, hardening techniques that introduce explicit noise into the encoding). Each defense has an accuracy cost. The institution's privacy team, not the matcher's engineering team, is the right owner of the re-identification-risk model. <!-- TODO: confirm at time of build; the academic literature on re-identification of Bloom-filter-encoded data continues to develop, with attacks-and-defenses moving in parallel. -->

**A consent-and-purpose-of-use governance layer.** The patient may not have consented to a privacy-preserving linkage of their record across organizations, even if the linkage is technically protective of their demographic features. Institutional policy may require explicit patient consent for linkage-based research; informed consent for clinical-care linkage is governed by treatment-payment-operations exceptions. The architecture has to record the consent posture per record at the time of encoding and respect it at the linkage time.

**A linkage-performance-monitoring discipline.** The PPRL matcher's accuracy is harder to evaluate than a conventional matcher's because the gold-standard evaluation requires ground-truth linkages, which require the demographic data the protocol was designed to suppress. Pilot evaluations against synthetic data or against a known-overlap population are the standard mechanism; the institution's monitoring of cohort-stratified accuracy under PPRL has to account for the fact that the cohort axes themselves are not directly observable on the encoded data.

**A configuration-versioning and re-encoding lifecycle.** The salt rotates; the Bloom-filter parameterization is updated when the academic state-of-the-art improves; the per-feature bit allocation is re-tuned when the institution's calibration data evolves. Each change invalidates all previously-encoded data and requires the participating organizations to coordinate a re-encoding of their populations. The re-encoding is operationally non-trivial at population scale, and the institution's PPRL operational rhythm has to account for it.

**A cross-protocol bridge for hybrid deployments.** Most institutions do not run a single PPRL protocol for all their privacy-preserving-linkage needs. The research-collaboration use case may use a tokenizer; the public-health-surveillance use case may use Bloom-filter encoding; the cross-payer outcomes use case may use a custom SMPC setup negotiated bilaterally. The architecture has to host multiple protocols on the same underlying data store, with appropriate isolation between them and with consistent governance across them.

These eight dimensions are not optional. Every production-grade PPRL deployment handles them, even if some institutions handle them implicitly through informal norms rather than explicit architecture. The implicit handling tends to fail when the institution's governance audits the linkage post-hoc; the explicit handling is the right design.

### Why It Is Harder Than It Sounds

Six structural reasons.

**The accuracy ceiling is genuinely lower than direct matching.** Bloom-filter encoding loses information; the loss shows up as reduced match precision and recall on the same demographic-feature set. The reductions are population-specific and parameterization-specific; in published evaluations they range from a few percentage points to over ten percentage points depending on the protocol and the data quality. The institution has to decide, for each use case, whether the privacy benefit is worth the accuracy cost. For some use cases (research linkages where false negatives mean smaller cohorts), the cost is acceptable. For others (clinical-care linkages where false negatives mean missed safety signals), it is not. The PPRL recipe is not a drop-in replacement for direct matching; the use cases have to be selected for the trade-off.

**The trust architecture is non-trivial to negotiate.** The participating organizations have to agree on the protocol, the salt-management ceremony, the audit posture, the re-identification-risk model, and the linkage-result-disclosure policy. Each of these is a contract negotiation as much as a technical decision. The institutions that operate PPRL successfully have invested in the legal-and-compliance team's familiarity with the cryptographic primitives, which is uncommon. The institutions that have not made the investment discover, mid-project, that their compliance team cannot evaluate the protocol's privacy claims and the project stalls.

**The cryptographic-key management is operationally heavier than conventional matching.** The shared salt is a high-value secret that, if compromised, retroactively breaks the privacy guarantee of every encoded record. Salt rotation is a coordinated multi-organization event; salt custody is a hardware-security-module concern; salt-related audit logging is a compliance requirement. None of this exists in a conventional cross-facility-matching setup, and the institutions that operate PPRL well have built the key-management capability deliberately.

**The protocol-execution coordination has its own failure modes.** The participating organizations have to encode at the same parameterization, exchange at the same time, run the matcher against compatible data structures, and consume the results within the linkage-result-disclosure policy. Mis-coordinated parameterization (one party used a different n-gram size; one party used a different salt) produces a silent linkage failure where the matcher returns zero matches because the encoded representations are not comparable. Mis-coordinated timing (one party encoded a snapshot from a different date than the other) produces a linkage that misses recent records or duplicates older ones. The operational discipline required is non-trivial.

**The linkage results are themselves PHI in some scenarios.** Knowing that a particular research-cohort patient had a specific out-of-network ED visit, a specific genomic profile, a specific tumor-registry record is identifying-or-near-identifying information depending on the population. Some PPRL protocols (PSI-CA, federated-aggregate-only protocols) return only counts and avoid this concern. Others (per-record-match protocols) return the linkage and the institution has to apply downstream privacy controls (k-anonymity for cohort outputs, suppression of small cells, differential privacy for aggregate queries). The PPRL protocol does not by itself solve the downstream privacy problem.

**The cohort-stratified accuracy disparities are harder to detect and to fix.** PPRL performance varies across demographic cohorts for the same reasons direct matching does (names from non-dominant-culture traditions accumulate more variation; populations with unstable demographic data have lower match rates), and the variations are often amplified by the encoding (some defensive measures introduce more noise on shorter strings, which disproportionately affects naming traditions that produce shorter strings). The institution's cohort-stratified accuracy monitoring has to operate on PPRL outputs without the demographic features that the institution would normally use to define the cohort axes, which requires either a privacy-respecting cohort-axis derivation (each participating organization computes its own cohort axes locally and contributes the cohort-bucket as a hashed feature in the encoding) or a pilot evaluation pattern (calibrate against a known-overlap population with full demographic visibility, then deploy).

### Where the Field Has Moved

A few practical updates worth knowing.

**Open-source toolkits have matured.** The `anonlink` toolkit from the Confidential Computing Consortium provides a reference implementation of CLK encoding and Bloom-filter-based linkage; the toolkit is in active maintenance and has been deployed in research and operational settings. The `OpenMined PSI` toolkit provides a reference implementation of private-set-intersection protocols. The `MP-SPDZ` toolkit provides a reference implementation of secure-multi-party-computation primitives. The toolkits are not turn-key (they require integration with the institution's data infrastructure, the trust architecture, and the audit posture) but they remove the cryptographic-implementation burden that earlier PPRL deployments carried. <!-- TODO: confirm at time of build; the open-source toolkit landscape continues to evolve, and the specific maturity of each toolkit depends on the use case. -->

**Commercial tokenization has consolidated.** A small number of commercial tokenization vendors (Datavant, HealthVerity, IQVIA, others) operate at scale across the U.S. healthcare data ecosystem, with established BAA postures, audit certifications, and integrations with major data sources. <!-- TODO: confirm at time of build; the commercial-tokenizer landscape continues to evolve through acquisitions and product changes. --> The institutions that are not building PPRL from scratch are typically integrating with one of these vendors. The architectural question is what the institution's trust posture is toward each vendor's specific cryptographic implementation and audit posture.

**Differential privacy has become a complementary primitive.** Differential privacy adds calibrated noise to aggregate statistics so that the inclusion or exclusion of any single record in the input data does not measurably affect the output. PPRL produces linked records; the downstream analytics on the linked records can apply differential privacy to provide stronger privacy guarantees on the analytic outputs than the linkage alone provides. Combining PPRL with differential privacy is operationally common in the academic literature and increasingly common in operational deployments. <!-- TODO: confirm at time of build; the differential-privacy ecosystem in healthcare is still maturing, with the U.S. Census Bureau's deployment as the largest production reference and a small number of healthcare-specific deployments. -->

**Trusted-execution-environment (TEE) hardware is enabling new patterns.** Hardware-based confidential-computing primitives (Intel SGX, AMD SEV-SNP, AWS Nitro Enclaves, Azure Confidential Computing) provide a hardware-attested isolated execution environment where data can be processed in plaintext while remaining inaccessible to the host operating system or to the cloud provider. PPRL deployments that use TEE primitives can run a conventional matcher inside the enclave on the participants' raw demographics, with the trust assumption shifted from "the third party will not retain or misuse the data" to "the hardware enforces the isolation." The TEE-based pattern is an active research area and a small number of operational deployments use it. <!-- TODO: confirm at time of build; the TEE-based PPRL ecosystem is still maturing, with attestation-and-key-management infrastructure varying by hardware vendor. -->

**Regulatory expectations are tightening.** The HIPAA Safe Harbor and Expert Determination de-identification standards remain the primary U.S. regulatory framework for de-identified data, and PPRL is one of the techniques an Expert Determination evaluation may consider. The post-Dobbs state-law landscape has produced a wave of jurisdiction-specific data-handling requirements that constrain certain record types from being shared across organizations even with privacy-preserving techniques; the PPRL architecture has to incorporate jurisdiction-specific overlay rules. The 21st Century Cures Act information-blocking provisions create an obligation to share patient records on request that interacts with PPRL in non-obvious ways: a patient who has authorized an external research consortium to access her records has, by extension, authorized the PPRL linkage that the consortium uses; the institutional architecture has to honor the authorization without exposing other patients' records as a side-effect. <!-- TODO: confirm at time of build; the post-2024 state-law landscape continues to evolve, and the specific applicability of information-blocking rules to PPRL-mediated research is still being clarified through guidance and enforcement. -->

**Patient-mediated PPRL is emerging.** As the CMS Patient Access API ecosystem matures, the patient is increasingly the connecting tissue between her records across organizations, and a patient who has connected her records to a personal-health-record app authenticated under her own credentials can authorize a PPRL-mediated retrieval that the app coordinates on her behalf. The pattern is uncommon as of writing but is becoming architecturally viable; the institutional PPRL architecture should be designed to accept patient-mediated linkages as a trigger source.

---

## General Architecture Pattern

The pipeline has six logical stages: prepare the demographic features for encoding (standardization and normalization), execute the agreed cryptographic encoding under the shared protocol parameterization, exchange the encoded data among participants under the trust architecture, run the matcher against the encoded data, persist the linkage results with the disclosure-policy and audit metadata, and react to events that supersede the linkage (re-encoding because the salt rotated, re-running the matcher because the parameterization changed, retracting a linkage because consent was withdrawn).

```text
┌────────────── PREPARE ────────────────────────────┐
│                                                    │
│  [Per-participant demographic-feature              │
│   standardization]                                 │
│   - Pull the demographic-feature set under the     │
│     protocol's specification (typically: name      │
│     components, DOB, sex, address components,     │
│     SSN where collected, phone)                    │
│   - Apply per-feature normalization (case-fold,   │
│     whitespace-strip, USPS-standardize address,   │
│     diacritic-fold, transliteration where         │
│     specified)                                     │
│   - Apply consent and purpose-of-use filters      │
│     (records the patient has consented to         │
│     include in this specific linkage; records     │
│     the institution's policy permits to be        │
│     encoded for this purpose; records under       │
│     jurisdiction-specific suppression are         │
│     excluded)                                      │
│   - Tag each record with the consent posture and  │
│     the cohort-axis hashes (per-participant       │
│     local cohort-axis derivation that the         │
│     downstream cohort-stratified-accuracy         │
│     monitoring will use)                           │
│           │                                        │
│           ▼                                        │
│  [Output: standardized record set with consent    │
│   metadata, cohort-axis hashes, source            │
│   participant identifier, source record           │
│   identifier]                                      │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── ENCODE ─────────────────────────────┐
│                                                    │
│  [Per-participant cryptographic encoding under    │
│   the shared protocol parameterization]           │
│   - Load the protocol parameterization (salt,    │
│     n-gram size, Bloom-filter size, hash-        │
│     function count, per-feature bit allocation,  │
│     defensive measures: random-hashing,           │
│     balanced-encoding, hardening parameters)     │
│   - The parameterization is loaded from a         │
│     versioned configuration store with the       │
│     version pinned to the linkage cycle (each    │
│     linkage cycle pins the configuration         │
│     version active at the cycle's start)         │
│   - Per record, per demographic feature,          │
│     produce the per-feature Bloom filter         │
│   - Combine per-feature Bloom filters into the    │
│     record-level Cryptographic-Long-Term-Key      │
│     (CLK) under the per-feature bit allocation   │
│   - Apply defensive measures (random hashing,     │
│     balanced encoding, hardening) per the        │
│     parameterization                               │
│   - Tag the encoded record with the source       │
│     participant identifier, the source record    │
│     identifier (locally retained, not in the     │
│     encoded payload that gets exchanged), the    │
│     consent posture, and the cohort-axis hashes  │
│           │                                        │
│           ▼                                        │
│  [Output: encoded-record envelope with no plain-  │
│   text demographics, only the encoded payload    │
│   plus governance metadata]                       │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── EXCHANGE ───────────────────────────┐
│                                                    │
│  [Cross-participant exchange under the trust      │
│   architecture]                                    │
│   - Tokenizer model: each participant uploads     │
│     its encoded payload to the tokenizer's        │
│     designated ingestion endpoint with mTLS       │
│     authentication and producer-signed envelope  │
│   - Bloom-filter-broker model: each participant   │
│     uploads its encoded payload to a designated   │
│     linkage-broker that all participants have     │
│     contracted with; the broker has visibility    │
│     to the encoded payloads but not the          │
│     demographics (the demographics never left    │
│     the source organization)                      │
│   - SMPC model: the participants engage in the    │
│     multi-round protocol exchange under their    │
│     respective protocol-runner endpoints, with   │
│     mTLS-and-attested-execution verification at  │
│     each round                                     │
│   - Patient-mediated model: the patient's        │
│     personal-health-record app authenticates     │
│     to each participant's API endpoint with the  │
│     patient's own credentials; the app           │
│     orchestrates the encoding-and-exchange on    │
│     behalf of the patient                         │
│   - The exchange is logged in each participant's  │
│     audit log with the linkage-cycle identifier,  │
│     the protocol parameterization version, the   │
│     consent posture summary, and the per-record  │
│     count                                         │
│           │                                        │
│           ▼                                        │
│  [Output: encoded-record sets at the linkage-     │
│   execution endpoint, with each participant's    │
│   contribution traceable to its source for        │
│   audit purposes]                                  │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── MATCH ──────────────────────────────┐
│                                                    │
│  [The linkage executor (the tokenizer, the        │
│   linkage-broker, the SMPC protocol runner, or    │
│   the patient's app) computes pairwise similarity │
│   between encoded records under the protocol's    │
│   matching function]                               │
│   - Block / candidate-generation step on the      │
│     encoded data (where the protocol supports     │
│     it; pure SMPC may compute the full pairwise   │
│     comparison)                                    │
│   - Per-pair similarity scoring (Sørensen-Dice   │
│     for Bloom filters, equality for tokenized    │
│     data, protocol-specific for SMPC)            │
│   - Per-pair Fellegi-Sunter-style probabilistic   │
│     combination across the per-feature           │
│     similarity scores                              │
│   - Application of confidence thresholds         │
│     calibrated for the encoded-data scoring      │
│     (separate from the conventional thresholds   │
│     because the underlying scoring function is   │
│     different):                                    │
│     - >= ENCODED_MATCH_HIGH: confident match     │
│     - >= ENCODED_MATCH_MED: probable match;      │
│       routes to disclosure-policy-aware review   │
│     - <= ENCODED_REJECT: not a match             │
│     - in between: review queue]                  │
│           │                                        │
│           ▼                                        │
│  [Output: match decisions in the linkage-result-  │
│   disclosure form (per-record yes/no flags,       │
│   intersection counts, encrypted match           │
│   indicators), with the per-decision evidence    │
│   summary for audit]                              │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── DISCLOSE ───────────────────────────┐
│                                                    │
│  [Linkage-result disclosure under the protocol's  │
│   policy]                                          │
│   - Determine the disclosure target (the analytic │
│     consumer, the participating organizations,    │
│     a designated single recipient, neither)      │
│   - Determine the disclosure form (per-record     │
│     match flags, intersection counts, aggregated  │
│     cohort sizes, k-anonymous summaries,         │
│     differentially-private aggregates)            │
│   - Apply the cohort-stratified-accuracy-        │
│     monitoring derivation: the per-cohort match-  │
│     rate, false-acceptance-rate, and review-     │
│     queue depth use the cohort-axis hashes       │
│     contributed by each participant in the       │
│     encoding step                                 │
│   - Apply k-anonymity / suppression / DP noise   │
│     to small-cell aggregates per the protocol's  │
│     downstream privacy guarantees                 │
│   - Sign and authenticate the disclosure with    │
│     the linkage-execution-endpoint's              │
│     credentials; route to the disclosure target  │
│     under the protocol's transport               │
│           │                                        │
│           ▼                                        │
│  [Output: linkage results delivered to the        │
│   designated consumer in the disclosure-          │
│   compatible form, with per-disclosure audit     │
│   logging]                                         │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── PERSIST + AUDIT ────────────────────┐
│                                                    │
│  [Per-participant persistence of the linkage      │
│   cycle artifacts]                                 │
│   - The linkage-cycle metadata (cycle identifier, │
│     protocol parameterization version, consent   │
│     posture summary, per-participant record      │
│     count, linkage-execution endpoint, disclosure │
│     target, disclosure form, run timestamps)     │
│   - The linkage-result envelope retained at each  │
│     participant per the protocol's retention     │
│     rules                                          │
│   - The encoded-record set retained at each      │
│     participant for the rotation cycle (typically │
│     until the next salt rotation) per the         │
│     protocol's retention rules                    │
│   - The audit log of every encoding, every       │
│     exchange, every matching run, and every      │
│     disclosure event, retained per the           │
│     regulatory floor                              │
│           │                                        │
│           ▼                                        │
│  [Emit pprl_linkage_cycle_completed event for     │
│   downstream consumers]                            │
│                                                    │
└────────────────────────────────────────────────────┘

┌────────────── INVALIDATE / SUPERSEDE ─────────────┐
│                                                    │
│  [Subscribe to events that supersede prior        │
│   linkages]                                        │
│   - Salt rotation event (the shared salt rotates; │
│     all encoded data under the prior salt is      │
│     invalidated; participants re-encode their     │
│     populations under the new salt; downstream    │
│     consumers refresh their dependent state)     │
│   - Parameterization upgrade event (the protocol  │
│     parameterization is updated to a newer        │
│     version; subset of features may carry over,   │
│     full re-encoding is the safe default)         │
│   - Consent withdrawal event (a patient has       │
│     withdrawn consent for inclusion in the       │
│     linkage; the participating organization       │
│     removes the patient from the encoded record   │
│     set going forward; prior linkages must be    │
│     handled per the protocol's retention rules)  │
│   - Re-identification-risk-model update           │
│     (the institution's privacy team has updated   │
│     the re-identification-risk model;             │
│     parameterization or defensive measures need   │
│     to be re-tuned)                               │
│   - Identity merge from recipe 5.1 or             │
│     reversal from recipe 5.7 (an underlying      │
│     identity merger or name-change reversal      │
│     means that the encoded records under the     │
│     prior identity state are now incorrect; the   │
│     participating organization re-encodes the    │
│     affected records and re-runs the matcher)    │
│   - Cross-recipe trigger from 5.5 / 5.6 / 5.7     │
│     where the linkage produced under PPRL        │
│     interacts with the conventional cross-       │
│     facility matching, the claims-clinical       │
│     linkage, or the longitudinal-name-change     │
│     pipeline                                       │
│           │                                        │
│           ▼                                        │
│  [Re-evaluate the affected linkages; emit         │
│   pprl_linkage_invalidated events so propagation  │
│   consumers refresh accordingly]                  │
│                                                    │
└────────────────────────────────────────────────────┘
```

**The encoding step is the load-bearing addition versus recipe 5.5.** A conventional cross-facility matcher operates on plaintext demographic features that flow through the HIE's matching layer. The PPRL matcher operates on cryptographically-encoded representations that are produced before any cross-organizational exchange. The encoding step is per-participant and parameterization-pinned: every participating organization runs the same encoding under the same parameterization to produce comparable encoded records. Mis-coordinated encoding produces silent linkage failures.

**Threshold calibration is protocol-specific.** Re-using the recipe 5.5 thresholds for PPRL produces either too many missed matches (the conventional thresholds were calibrated for plaintext comparisons; PPRL similarity scores are systematically lower for the same underlying record pair because of encoding noise) or too many false acceptances (the thresholds were loose enough that encoding noise was treated as legitimate variation, but the matcher then over-merges across actual different patients with similar demographic features). The right thresholds are derived from a separate calibration set that includes confirmed cross-organizational matches, near-miss family-member cases, and known-incorrect linkages, all encoded under the same parameterization the production matcher will use.

**Trust architecture is a first-class architectural concern.** The matcher's output is only as private as the protocol's trust assumption holds. The architecture has to explicitly specify which party has access to which artifacts, the audit posture for each access, the re-identification-risk mitigation each party performs, and the consent-and-purpose-of-use governance each party honors. Treating the trust architecture as an architectural artifact (a documented, versioned, audit-capable contract) rather than an informal norm is the discipline that makes PPRL operationally trustworthy.

**Disclosure-policy granularity matters more than for conventional matching.** Conventional matching's output is a yes/no match decision. PPRL's output can be a yes/no match decision, an intersection count, a per-cohort aggregate, an encrypted match indicator that only one designated party can decrypt, or a differentially-private summary of the linkage. Each disclosure form has its own privacy properties and its own analytic utility. Choosing the right disclosure form per use case is part of the protocol design, and the architecture has to support multiple disclosure forms simultaneously for different use cases on the same encoded data.

**Cohort-stratified accuracy monitoring is structurally harder.** Conventional matching can directly inspect the demographic features to define cohort axes (name-tradition cohort, age cohort, sex cohort) and stratify the accuracy metrics. PPRL cannot, because the demographic features are not visible to the linkage-execution endpoint. The architecture supports per-participant locally-computed cohort-axis hashes that are contributed in the encoding step; the linkage-execution endpoint stratifies the accuracy metrics by the cohort-axis hashes without learning the underlying axis values. Pilot evaluations against a known-overlap calibration population provide the absolute-accuracy benchmarks that the in-production cohort-stratified disparities are interpreted against.

**Salt rotation is the operational rhythm.** The shared salt is the cryptographic root-of-trust for the protocol's privacy guarantee. Salt rotation is a coordinated multi-organization event that invalidates all previously-encoded data and requires the participating organizations to re-encode their populations under the new salt. Salt rotation cadence is protocol-specific (annual or semi-annual is common; some research-collaboration protocols rotate per-cycle). Salt custody is a hardware-security-module concern. Salt-rotation audit logging is a compliance requirement.

**Reversibility through re-encoding rather than retraction.** A linkage that was wrong cannot be retracted from a counterparty that has already consumed it; the only mitigation is to re-encode under a new parameterization, re-run the linkage, and disclose the corrected result, with explicit communication that the prior result is superseded. The architecture treats re-encoding as the primary mechanism for handling linkage errors, with the prior result preserved in the audit trail but explicitly marked as superseded.

**Consent withdrawal is forward-only.** A patient who withdraws consent for inclusion in the linkage cannot retroactively un-link records that have already been disclosed; the participating organization removes the patient from future encoding and re-running, but the prior linkage results remain in the consumer's possession. The architecture supports consent withdrawal as a forward-looking event with explicit patient-facing communication about what can and cannot be retracted.

---


> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter05.08-architecture). The Python example is linked from there.

## The Honest Take

Privacy-preserving record linkage is the recipe in this chapter where the technical complexity is moderate, the cryptographic complexity is non-trivial but tractable, and the human-and-organizational complexity is the load-bearing concern. The matching techniques are familiar (you have seen the same probabilistic-record-linkage core in every recipe of this chapter, with the encoded-data twist that this recipe layers on top). The orchestration is familiar (serverless functions, batch-compute jobs, workflow orchestrators, event buses, the same pattern as the other identity-pipeline recipes; see the [Architecture and Implementation companion](chapter05.08-architecture) for the AWS-specific service mapping). The cryptographic primitives (Bloom filters, salted hashes, secure-multi-party computation, homomorphic encryption) are well-established in the academic literature and have mature open-source implementations. The thing that makes this recipe hard is that the privacy guarantee is a multi-organization contract, not a technology, and the multi-organization contract is what most institutions are not built to negotiate or maintain at the cryptographic-primitive level.

The trap most specific to PPRL is treating it as a drop-in replacement for direct matching. It is not. The accuracy is genuinely lower; the operational complexity is higher; the trust framework is harder to negotiate; the audit posture is more demanding. The institutions that succeed with PPRL pick specific use cases where the privacy benefit is worth the trade-offs and build the capability for those use cases, not as a general-purpose substitute for the conventional matching infrastructure. The use cases that work well under PPRL are typically research collaborations with explicit privacy constraints, public-health surveillance across organizational boundaries that legal sharing arrangements do not cover, cross-payer outcomes work where competitive concerns prevent direct exchange, and patient-mediated linkages where the patient is the connecting tissue. The use cases that work poorly under PPRL are clinical-care matching at the point of service (the accuracy reduction matters too much), administrative matching where the conventional infrastructure already exists (the marginal benefit does not justify the operational overhead), and high-volume real-time matching where the encoding-and-exchange latency exceeds the operational tolerance.

The second trap is under-investing in the trust-framework negotiation. The cryptographic primitives are well-understood; the trust framework is the artifact that translates the primitives into an operational privacy guarantee, and the artifact has to be drafted by lawyers who understand both the cryptography and the institutional governance. Most institutions have no one on staff who fits both descriptions; the institutions that operate PPRL successfully have either trained their compliance team in the cryptographic primitives or contracted with specialized privacy-technology counsel for the trust-framework drafting. The cost of getting this wrong is silent: the protocol may operate technically correctly but with a trust-framework artifact that does not actually constrain the participants' behavior in the ways the privacy claim assumes. The mitigation is treating the trust-framework as a first-class artifact with its own version history, its own change-control process, and its own periodic review.

The third trap, related: under-investing in the salt-management ceremony. The salt is the cryptographic root-of-trust; if the salt is custodied informally, audited inconsistently, or rotated without coordination, the protocol's privacy guarantee is operationally broken regardless of how well the matcher works. The institutions that operate salt-management ceremonies well have a documented HSM-based custody pattern, a published rotation cadence, an explicit dual-control approval requirement, and an audit-archive that is reviewed periodically by an external auditor. The institutions that do not have this discover, when the protocol is questioned, that the salt-related audit trail does not support the privacy claim.

The thing that surprises people coming from other identity-pipeline backgrounds is how much of the operational load is in the trust-architecture maintenance rather than in the matcher itself. Recipe 5.5's matcher cares about whether two records refer to the same person; recipe 5.8's matcher cares about that and about whether the cryptographic primitives that produced the comparison are operating correctly under the agreed parameterization with the agreed trust assumptions. The matcher is not deciding what is true; it is deciding what is true under a constrained inference channel that the trust framework has authorized. The split-of-concerns is correct (it lets the matcher do its job without being entangled in trust-framework logic), but it requires architectural discipline to maintain. Most teams initially treat the trust framework as a contractual concern and discover, when the protocol is operationally tested, that the trust-framework gaps surface as operational failures.

The thing about commercial tokenization vendors: they are operationally simpler than building the PPRL pipeline from scratch, and the institutions that use them well have invested in evaluating the vendor's specific cryptographic implementation, the audit certifications, the data-handling posture, and the contractual constraints. The institutions that use them poorly have treated the vendor as a black-box service whose privacy claims they accept on the vendor's marketing without independent technical evaluation. The vendor is an external third party with full visibility into the demographic feeds; the institution's threat model has to either accept the vendor as a trusted third party (with the corresponding contract and audit posture) or evaluate the vendor's cryptographic implementation against the institution's own threat model. Both are valid postures; treating the vendor as a black-box without choosing one explicitly is the operational failure mode.

The thing about the academic-versus-operational gap: the academic literature on PPRL is mature and active, with continued publication of new attacks, new defenses, new protocols, and new evaluation results. The operational deployments in healthcare lag the academic state-of-the-art by several years; the institutions that operate PPRL well stay current with the literature through their privacy team and incorporate updates on a deliberate cadence. The institutions that do not have this discipline operate parameterizations that the published literature has identified as vulnerable; the audit posture cannot detect the vulnerability because the audit is on the operational behavior, not on the cryptographic-state-of-the-art. The mitigation is treating the academic literature as an operational input, with quarterly or semi-annual review by the privacy team and explicit communication to the trust-framework participants about identified vulnerabilities and recommended mitigations.

The thing about cross-jurisdictional overlays: post-Dobbs reproductive-health-care state laws, 42 CFR Part 2 substance-use-treatment record provisions, state-level HIV-and-genetic-information rules, gender-affirming-care state-law overlays, and patient-protective-custody scenarios all impose constraints on PPRL inclusion that are jurisdiction-specific and time-varying. The architecture has to accommodate the overlays through per-record consent-posture metadata; the operational discipline is reviewing the overlay rule set on a regular cadence (post-legislative-session is a typical trigger) and updating the consent-filter policy in response. Skip this and the PPRL pipeline silently includes records in linkages that the jurisdiction-specific overlay would have excluded, which is a regulatory violation that the audit will eventually surface.

The thing about consent withdrawal: the institutions that handle consent withdrawal well have built explicit forward-looking communication to the patient about what can and cannot be retracted. The communication is honest: the linkage results that have already left the institution are in the consumer's possession; the institution can remove the patient from future cycles and can communicate the withdrawal to the consumer per the protocol's policy, but the institution cannot guarantee that the consumer will purge the patient from already-published analytic outputs. The institutions that do not have this communication discover, when a patient discovers her record was included in a linkage she has since withdrawn from, that the patient's expectation (that the withdrawal is retroactive) does not match the operational reality, with predictable trust failures. The mitigation is patient-facing communication that frames the withdrawal as forward-looking explicitly.

The thing about pilot data: every PPRL deployment needs pilot data for threshold calibration, and the pilot data is the highest-value-and-highest-risk data in the entire system because it carries both the demographics and the linkage truth. The institutions that operate pilots well have explicit pilot-data agreements with their counterparties (a research collaboration that authorizes the pilot for a defined period under specific access controls), explicit pilot-data infrastructure (a separate AWS account, separate access controls, separate audit posture), and explicit pilot-data retention rules (typically the pilot data is deleted at the end of the calibration project; the calibration outputs survive). The institutions that do not have this discover, when the pilot data is later questioned, that the pilot operates under operational assumptions that the audit cannot verify. The mitigation is treating the pilot as a separately governed substrate with its own contracts, its own infrastructure, and its own lifecycle.

The thing about cross-recipe coordination: the PPRL pipeline depends on the upstream identity-resolution recipes (5.1 local MPI, 5.3 address standardization, 5.7 longitudinal name-change) for the canonical identity state at each participant. A name change in 5.7 invalidates the encoded records under the prior name; an identity merge in 5.1 invalidates the encoded records under the merged-from identity; an address standardization update in 5.3 may change the address-feature encoding. The institutions that handle this well have explicit re-encoding queues that consume cross-recipe events and process them with appropriate ordering and deduplication; the institutions that do not have this discover, after a few rotation cycles, that the encoded records drift from the canonical identity state and the linkage rates degrade silently.

The thing I would do differently the second time: invest in the trust-framework artifact and the operational governance rhythm before writing any code. The first version of the recipe will treat the trust framework as a contractual concern that can be drafted in parallel with the engineering work. The second version will recognize that the trust framework is the design artifact that the engineering work implements, and that the engineering work cannot be specified at the architectural level without the trust framework specifying the participants, the parameterization, the salt-management ceremony, the disclosure policy, the audit posture, the re-identification-risk model, and the operational rhythms. Draft the trust framework first, with all participants and all governance committees engaged; let the engineering work serve the trust framework rather than the trust framework adapting to the engineering work after the fact.

The thing about regulatory drift: the post-2024 regulatory landscape (state-level data-sharing constraints, post-Dobbs overlays, evolving information-blocking enforcement, the 21st Century Cures Act's interaction with research disclosures, the EU-U.S. data-transfer adequacy decisions, the U.K. Data Protection Act post-Brexit posture) creates a moving target that the PPRL trust framework has to track. The institutions that manage this well have a regulatory-monitoring function (often shared between the privacy team and the compliance team) that flags relevant changes and triggers trust-framework updates. The institutions that do not have this discover, when the next enforcement action hits, that their PPRL deployment was operating under a stale interpretation of the applicable law. The mitigation is the regulatory-monitoring function with explicit triggers for trust-framework review.

Last point, because it is specific to the use case: PPRL is a tool for the cases where conventional matching is not authorized. It is not a privacy-by-default mechanism; the participating organizations still see the linkage results, and the linkage results are still PHI in most scenarios. The institutions that use PPRL well are clear-eyed about what the protocol does and does not protect: the protocol protects the demographic features at exchange time; it does not protect the linkage results post-disclosure; it does not protect the participating organizations from each other's auxiliary inferences from the linkage; it does not absolve the participating organizations of their downstream privacy obligations on the linked records. The mitigation is treating PPRL as one layer in a stack of privacy controls, with downstream controls (k-anonymity for cohort outputs, differential privacy for aggregate queries, suppression of small cells, audit logging on every query against the linked data) layered on top. PPRL alone is not a privacy guarantee; it is a privacy-preserving exchange mechanism that the institution's broader privacy architecture builds upon.

---

## Related Recipes

- **Recipe 5.1 (Internal Duplicate Patient Detection):** The local MPI is the canonical patient identity that the PPRL encoding step references for each participant. Identity merges in 5.1 invalidate the encoded records under the merged-from identity; the PPRL invalidation pipeline consumes the merge events and triggers re-encoding.
- **Recipe 5.2 (Provider NPI Matching):** Provider linkage across organizations is structurally similar to patient linkage but with NPI as a stronger anchor; PPRL is rarely needed for provider linkage because the regulatory framework around provider data is more permissive than around patient data.
- **Recipe 5.3 (Address Standardization and Household Linkage):** The address-feature encoding in PPRL depends on the standardized address from recipe 5.3; address standardization updates feed the PPRL invalidation pipeline.
- **Recipe 5.4 (Insurance Eligibility Matching):** Cross-payer eligibility matching may use PPRL where the trust framework prohibits direct demographic exchange; the cross-reference table from recipe 5.4 may be populated through a PPRL pipeline rather than through a conventional matcher.
- **Recipe 5.5 (Cross-Facility Patient Matching):** PPRL is the cross-facility-matching pattern where the conventional HIE-mediated matching is not authorized. The recipes share the cross-organizational-matching structure but diverge on the trust architecture and the disclosure policy.
- **Recipe 5.6 (Claims-to-Clinical Data Linkage):** Claims-clinical linkage may use PPRL for cross-payer outcomes research where the payer and the provider organization cannot directly exchange demographics; the linkage produced under PPRL feeds the same downstream analytics that recipe 5.6 supports.
- **Recipe 5.7 (Longitudinal Patient Matching Across Name Changes):** Name changes resolved in 5.7 invalidate the encoded records under the prior name; the PPRL invalidation pipeline consumes the name-change events and triggers re-encoding. The token-pair-history variation in recipe 5.7 is the recipe-specific extension for maintaining longitudinal continuity in the PPRL setting.
- **Recipe 5.9 (National-Scale Patient Matching):** TEFCA-mediated identity resolution at national scale may use PPRL for specific cross-organizational use cases where the trust framework prohibits direct exchange; the national-scale pattern extends the cross-organizational pattern with thousands of participants and the corresponding governance complexity.
- **Recipe 5.10 (Deceased Patient Resolution):** Deceased-patient events from 5.10 may surface in PPRL-mediated linkages; the recipes coordinate so that the death-record reconciliation does not produce false-positive matches in the PPRL pipeline.
- **Recipe 7.x (Predictive Analytics):** Cohort definitions for risk-scoring may depend on PPRL-mediated linkages across data sources; the longitudinal-cohort PPRL pipeline is the upstream substrate for population-scale predictive analytics.
- **Recipe 8.x (NLP / Traditional NLP):** Cross-organizational text-mining use cases may require PPRL to link clinical notes across organizations without exposing the demographic features that the notes reference; the text-feature-anonymization layer is a separate concern that complements the PPRL identity-linkage layer.
- **Recipe 13.x (Knowledge Graphs):** Federated knowledge-graph construction across organizations may use PPRL for the entity-linkage step; the architectural pattern extends naturally to multi-entity-type linkage.

---

## Tags

`entity-resolution` · `record-linkage` · `privacy-preserving` · `pprl` · `bloom-filter-encoding` · `cryptographic-long-term-key` · `clk` · `tokenization` · `secure-multi-party-computation` · `smpc` · `private-set-intersection` · `psi` · `homomorphic-encryption` · `trusted-execution-environment` · `tee` · `confidential-computing` · `cross-organizational-matching` · `salt-rotation` · `parameterization-versioning` · `re-identification-risk` · `differential-privacy` · `cohort-stratified-accuracy` · `consent-management` · `multi-party-trust-framework` · `event-driven` · `complex` · `production` · `hipaa` · `42-cfr-part-2` · `information-blocking` · `cures-act` · `equity-monitoring` · `research-collaboration` · `public-health-surveillance` · `cross-payer-outcomes` · `audit-archive`

---

*← [Recipe 5.7: Longitudinal Patient Matching Across Name Changes](chapter05.07-longitudinal-patient-matching-name-changes) · Chapter 5 · [Next: Recipe 5.9 - National-Scale Patient Matching (TEFCA) →](chapter05.09-national-scale-patient-matching)*
