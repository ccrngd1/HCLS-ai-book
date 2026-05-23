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

```
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

## The AWS Implementation

### Why These Services

**AWS Nitro Enclaves for the protocol-execution endpoint.** Where the protocol benefits from a hardware-attested isolated execution environment (most TEE-based PPRL deployments), Nitro Enclaves provide an isolated EC2 environment with hardware attestation, no persistent storage, no network access except through the parent EC2 instance's vsock interface, and no operator visibility into the enclave's memory. The matcher runs inside the enclave on the encoded data; the enclave's attestation is verified by each participant before contributing its encoded data, providing the trust assumption the protocol requires. <!-- TODO: confirm at time of build; Nitro Enclaves are generally available and have been used for confidential-computing patterns including PPRL prototypes; the specific Nitro Enclave PPRL deployments in healthcare are still uncommon. -->

**AWS Key Management Service (KMS) and AWS CloudHSM for the salt and shared-secret custody.** The shared cryptographic salt is the protocol's root-of-trust; it has to be generated through a multi-party ceremony, custodied through a hardware-security-module that no single participant can unilaterally access, rotated on the agreed cadence, and audit-logged on every access. KMS with customer-managed keys covers the standard custody pattern; CloudHSM covers the higher-assurance pattern where the institutional security posture or the regulatory framework requires a single-tenant HSM. The salt-related access control is enforced through KMS key policies and resource-based policies that name the specific Lambda or enclave roles authorized to invoke the salt-related operations.

**Amazon S3 for the encoded-record exchange surface.** The participating organizations exchange encoded data through S3 buckets configured with cross-account access policies that enumerate the specific roles authorized to read or write. SSE-KMS encryption with customer-managed keys protects the encoded data at rest; per-bucket bucket-policies and per-object access controls enforce the trust architecture. Object Lock in Compliance mode protects the audit-archive bucket (which retains every encoded payload for the protocol's audit retention floor). Cross-account replication propagates encoded payloads to the linkage-execution endpoint's account where the matcher consumes them.

**Amazon DynamoDB for the linkage-cycle metadata and linkage-result store.** The per-cycle metadata (cycle identifier, protocol parameterization version, consent-posture summary, per-participant record count, run timestamps) and the linkage-result-disclosure envelope are stored in DynamoDB with customer-managed KMS encryption, point-in-time recovery, and DynamoDB Streams to drive the cross-recipe event fan-out. The table's keying scheme (`linkage_cycle_id` as partition key, `disclosure_event_id` as sort key) supports per-cycle queries and per-disclosure audit reconstruction.

**AWS Lambda for the per-record encoding path.** Each participating organization's encoding Lambda is invoked per-record (or per-batch) with the standardized record payload, the protocol parameterization version, the salt reference, and the consent-posture metadata. The Lambda computes the per-feature Bloom filters, combines them into the CLK, applies the defensive measures, and writes the encoded payload to the participant's encoded-record S3 bucket. Each invocation is in VPC with VPC endpoints for KMS, S3, DynamoDB, and Secrets Manager. The Lambda's execution role has explicit permissions to access only the salt-key version pinned for the current linkage cycle; the role does not have permissions to access any other participant's data or salt-key version.

**AWS Glue and Apache Spark for the bulk encoding and the linkage-cycle execution.** Where the linkage cycle operates over hundreds of thousands to tens of millions of records per participant (typical for population-scale research linkages and for cross-payer outcomes linkages), the encoding Lambda is replaced by a Glue job running Spark on the participant's data. The Glue job applies the same encoding logic with the same parameterization version and writes the encoded payload to S3. The matcher itself runs as a Glue job in the linkage-execution-endpoint's account, consuming the encoded data from each participant's exchange bucket and producing the per-pair linkage decisions.

**AWS Step Functions for the linkage-cycle orchestration.** The cycle's state machine coordinates the per-participant encoding, the cross-account exchange, the matcher execution, the disclosure step, and the per-participant audit-and-retention persistence. The state machine handles retries with exponential backoff, error routing to per-stage DLQs, parallel execution across participants where the protocol allows, and explicit synchronization barriers where the protocol requires (the matcher cannot start until every participant has contributed; the disclosure cannot occur until the matcher has completed and the disclosure-policy validation has passed).

**Amazon SageMaker for the threshold calibration and the cohort-stratified-accuracy reporting.** The encoded-data thresholds (ENCODED_MATCH_HIGH, ENCODED_MATCH_MED, ENCODED_REJECT) are calibrated against a known-overlap pilot population with full demographic visibility, encoded under the production parameterization. SageMaker training jobs run the calibration over the pilot data and produce candidate thresholds with confusion-matrix and cohort-stratified-disparity reports. SageMaker Processing jobs run the in-production cohort-stratified-accuracy reports against the cohort-axis hashes contributed by each participant.

**Amazon SQS for the review queue and the propagation queue.** Two queues: a linkage-review queue (for medium-confidence pairs that the encoded-match threshold flagged for review without exposing the underlying demographics; the review tooling consults each participant's source data with appropriate authorization controls) and a propagation queue (for fanning out cycle-completion events to downstream consumers). Separating the queues keeps the operational pipeline independent of the higher-priority disclosure flow.

**Amazon EventBridge for the cross-recipe events.** When a linkage cycle completes (`pprl_linkage_cycle_completed`), when a salt rotation begins (`pprl_salt_rotation_initiated`), when a salt rotation completes (`pprl_salt_rotation_completed`), when a parameterization upgrade is published (`pprl_parameterization_upgraded`), when a consent withdrawal is processed (`pprl_consent_withdrawn`), or when a re-encoding is required (`pprl_re_encoding_required`), an event flows out to the per-participant operational systems, the cross-recipe consumers (recipe 5.5 cross-facility matcher, recipe 5.6 claims-clinical-linkage, recipe 5.7 longitudinal-name-change), and the analytics consumers. EventBridge rules route events to the right consumer with DLQs for failed deliveries. <!-- TODO (TechWriter): Expert review A6 (MEDIUM). Promote the consumer enumeration into a chapter-wide event-schema contract: PPRL events conform to (`source`, `detail_type`, `detail.cycle_id`, `detail.event_id`, `detail.parameterization_version`, `detail.salt_key_version`, `detail.disclosure_form`, `detail.target_consumer`, `detail.participant_count`, `detail.matched_pair_count`, `detail.cohort_stratified_summary`, `detail.consent_posture_summary`, `detail.jurisdictional_overlay_applicability`, `detail.detected_at`). Specify access-control-envelope-aware routing: a standard channel for non-restricted disclosure forms (per-record-match-flags, intersection-count, k-anonymous-aggregate) consumed by 5.5 / 5.6 / 5.7, the analytic consumer, and per-participant operational systems; a restricted channel for differentially-private-aggregate or encrypted-match-indicator disclosure forms consumed only by the explicitly-authorized consumer per the disclosure policy. Downstream consumers acknowledge processing via a CloudWatch metric (`{consumer}.events_processed`). The chapter-wide event-bus governance specifies the schema versioning policy and the deprecation cadence for breaking changes. -->

**Amazon Athena and AWS Lake Formation for the audit-and-analytics surface.** The linkage-cycle metadata, the per-cycle audit-event log, and the per-participant performance metrics surface through Athena queries with Lake Formation column-level and row-level access controls. Treatment-context users (for clinical-care PPRL deployments) see only the linkage results for their own institution's patients; research-context users see the cohort-stratified-accuracy metrics; audit-and-compliance users see the full audit-event log; the institutional governance committee sees the cycle-level metadata for review. <!-- TODO (TechWriter): Expert review A12 (LOW). Specify the column distinctions and the de-identification pattern (treatment-context: linkage results filtered to the requesting institution's patients with no cross-institution detail; research-context: cohort-stratified-accuracy metrics with cohort-axis-hash labels rather than underlying axis values; audit-and-compliance: full audit-event log; institutional-governance: cycle-level metadata with parameterization-version detail). The de-identification pattern for the research view uses cohort-axis-hash labels rather than underlying axis values; aggregated linkage statistics rather than per-record disclosures. -->

**AWS PrivateLink for the cross-account exchange where the protocol requires it.** Where the participating organizations operate in separate AWS accounts and the protocol prohibits exchange through publicly-routable endpoints, PrivateLink endpoints between the participants' VPCs provide a private network path for the encoded-data exchange. The PrivateLink configuration is paired with VPC endpoint policies that enumerate the specific cross-account roles authorized to invoke the endpoint.

**AWS KMS, CloudTrail, CloudWatch.** Customer-managed keys for the encoded-record stores, the linkage-cycle metadata table, the audit archive, the salt custody, and the Lambda log groups. CloudTrail data events on every salt-related operation, every encoded-record bucket access, every linkage-cycle metadata access, and every linkage-result disclosure. CloudWatch alarms on review-queue depth and aging, on encoding-failure rates (sudden spikes are usually a parameterization-mismatch issue), on cohort-stratified disparities, and on salt-rotation backlog. Same chapter pattern as 5.1, 5.4, 5.5, 5.6, 5.7.

**Amazon QuickSight for operational and quality dashboards.** Per-participant encoding rate, per-cycle linkage-rate trend, per-cohort linkage-rate disparity, salt-rotation cadence and coverage, parameterization-upgrade adoption, consent-withdrawal volume, re-encoding backlog, and audit-volume trends.

### Architecture Diagram

```mermaid
flowchart LR
    subgraph Participant_A_VPC
      PA1[Source data store<br/>EHR, claims, registry]
      PA2[Lambda<br/>standardize-and-prepare]
      PA3[Glue Job<br/>bulk-encode]
      PA4[(S3<br/>encoded-records-bucket-A<br/>SSE-KMS)]
      PA5[Lambda<br/>local-audit-and-persist]
    end

    subgraph Participant_B_VPC
      PB1[Source data store<br/>EHR, claims, registry]
      PB2[Lambda<br/>standardize-and-prepare]
      PB3[Glue Job<br/>bulk-encode]
      PB4[(S3<br/>encoded-records-bucket-B<br/>SSE-KMS)]
      PB5[Lambda<br/>local-audit-and-persist]
    end

    subgraph Linkage_Endpoint_VPC
      LE1[Nitro Enclave<br/>or Glue Job<br/>matcher-execution]
      LE2[(DynamoDB<br/>linkage-cycle-metadata)]
      LE3[(DynamoDB<br/>linkage-results-store)]
      LE4[Lambda<br/>disclose-and-route]
      LE5[(S3 audit archive<br/>Object Lock Compliance)]
    end

    subgraph Salt_Custody
      SC1[(AWS CloudHSM<br/>salt custody)]
      SC2[(AWS KMS<br/>per-cycle key derivation)]
    end

    subgraph Governance
      GV1[(DynamoDB<br/>protocol-parameterization<br/>versioned config store)]
      GV2[Step Functions<br/>linkage-cycle-orchestrator]
      GV3[SageMaker<br/>threshold-calibration<br/>and cohort-stratified-accuracy]
      GV4[SQS<br/>linkage-review-queue]
      GV5[Review tooling<br/>cohort-and-cycle-aware]
    end

    PA1 --> PA2
    PA2 --> PA3
    PA3 --> PA4
    PA3 --> PA5

    PB1 --> PB2
    PB2 --> PB3
    PB3 --> PB4
    PB3 --> PB5

    SC1 --> SC2
    SC2 -->|salt-key-version| PA3
    SC2 -->|salt-key-version| PB3
    SC2 -->|salt-key-version| LE1

    GV1 -->|parameterization-version| PA3
    GV1 -->|parameterization-version| PB3
    GV1 -->|parameterization-version| LE1

    GV2 --> PA3
    GV2 --> PB3
    GV2 --> LE1

    PA4 -->|cross-account-PrivateLink| LE1
    PB4 -->|cross-account-PrivateLink| LE1

    LE1 --> LE2
    LE1 --> LE3
    LE1 --> GV4
    GV4 --> GV5
    GV5 --> LE3

    LE3 --> LE4
    LE4 -->|disclosure| EB1[EventBridge<br/>pprl-events-bus]
    LE4 --> LE5

    EB1 -->|FanOut| C5[Recipe 5.5<br/>cross-facility matcher]
    EB1 -->|FanOut| C6[Recipe 5.6<br/>claims-clinical linkage]
    EB1 -->|FanOut| C7[Recipe 5.7<br/>longitudinal name-change]
    EB1 -->|FanOut| C8[Analytic consumer<br/>research, surveillance, ACO]
    EB1 -->|FanOut| C9[Per-participant<br/>operational systems]

    LE3 --> GV3
    GV3 --> GV1

    LE2 --> SS1[(S3 derived snapshots<br/>cycle-history)]
    SS1 --> AT1[Athena]
    AT1 --> LF1[Lake Formation<br/>column-and-row access]
    AT1 --> QS1[QuickSight<br/>operational and quality<br/>dashboards]

    style PA4 fill:#cfc,stroke:#333
    style PB4 fill:#cfc,stroke:#333
    style LE5 fill:#cfc,stroke:#333
    style SS1 fill:#cfc,stroke:#333
    style LE2 fill:#9ff,stroke:#333
    style LE3 fill:#9ff,stroke:#333
    style SC1 fill:#fc9,stroke:#333
    style SC2 fill:#fc9,stroke:#333
    style EB1 fill:#f9f,stroke:#333
    style GV1 fill:#ffc,stroke:#333
```

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **AWS Services** | AWS Nitro Enclaves (for TEE-based protocols), AWS KMS, AWS CloudHSM (where the higher-assurance salt-custody posture is required), Amazon S3, Amazon DynamoDB, AWS Lambda, AWS Glue, Apache Spark on Glue, AWS Step Functions, Amazon EventBridge, Amazon SQS, Amazon SageMaker, Amazon Athena, AWS Lake Formation, AWS PrivateLink, Amazon QuickSight, Amazon CloudWatch, AWS CloudTrail. |
| **External Inputs** | Per-participant source data: the standardized demographic-feature set (typically name components, DOB, sex, address components, SSN where collected, phone), the per-record consent posture, the per-record cohort-axis values that produce the local cohort-axis hashes. Cross-recipe dependencies: recipe 5.1 local MPI for the canonical patient identity, recipe 5.3 address standardization, recipe 5.7 longitudinal-name-change for the time-varying-name handling under PPRL. Reference data: the protocol parameterization (salt-key-version, n-gram size, Bloom-filter size, hash-function count, per-feature bit allocation, defensive-measures parameters) maintained in a versioned configuration store. |
| **IAM Permissions** | Per-Lambda least-privilege: scoped `s3:GetObject` / `PutObject` on specific bucket prefixes for the encoded-records bucket, `dynamodb:GetItem` / `PutItem` / `Query` on the linkage-cycle-metadata and linkage-results tables, `kms:Decrypt` on the per-cycle salt-key version pinned for the current linkage cycle, `events:PutEvents` on the pprl-events bus, `sqs:SendMessage` on the review queue. The encoding Lambda has permissions to access only the salt-key version pinned for the current linkage cycle, not any prior or future version. The matcher Lambda or Nitro Enclave role has read access to all participants' encoded-records buckets through cross-account bucket policies; the role does not have access to any participant's source data. SageMaker training jobs have read access to the pilot-overlap calibration data and the cohort-axis-hash store; the role does not have access to the underlying demographics. Per-Glue-job execution-role binding so Step Functions invokes only the role appropriate for the current pipeline stage. Never use `*` actions or `*` resources in production. <!-- TODO (TechWriter): Expert review S1 (HIGH). Specify identity-boundary requirements at the architectural level for every consequential path: (1) the per-participant encoding Lambda receives a producer-signed envelope (`source_system`, `source_record_id`, `event_id`, `signed_payload`, `signature`) with consumer-side signature validation against rotated producer keys; (2) the cross-account encoded-records exchange is authenticated through cross-account bucket policies that enumerate the specific roles authorized to read or write, plus mTLS-and-PrivateLink for the network transport; (3) the matcher Lambda or Nitro Enclave role is per-cycle bound through Step Functions and has time-bound access to the encoded data only during the cycle's active execution window; (4) the salt-rotation ceremony is dual-controlled at the architectural level (two HSM operators from non-overlapping organizations must approve a rotation operation; the rotation is audit-logged with both operator identities and the new salt-key-version reference); (5) the consent-withdrawal path requires patient re-authentication and is audit-logged with explicit "patient-mediated" attribution; (6) the cross-recipe EventBridge fan-out validates producer-signed envelopes at consumers and applies access-control-envelope-aware routing so that consumers in different trust tiers receive different event detail levels. The recipe-specific extensions to the chapter pattern are the salt-rotation ceremony's cryptographic-root-of-trust stakes, the TEE-attestation-flow stakes, and the patient-mediated PPRL trigger source's patient-impersonation stakes. Same chapter pattern as 5.1, 5.4, 5.5, 5.6, 5.7. --> |
| **BAA and Trust Framework** | AWS BAA signed. Per-participant data-use agreements that authorize the PPRL linkage for the specific use case and constrain downstream re-use. Multi-party trust framework that enumerates the participants, the protocol parameterization, the salt-management ceremony, the linkage-result-disclosure policy, the audit posture, the re-identification-risk model, and the dispute-resolution mechanism. Where a tokenization vendor is used, a separate BAA-and-data-use-agreement with the vendor that addresses the vendor's specific privacy posture and audit certifications. Patient consent for inclusion in the linkage where the institutional policy or the regulatory framework requires it. <!-- TODO (TechWriter): Expert review A9 (MEDIUM). Specify per-cycle consent metadata captured at intake and the jurisdictional overlay applicability (post-Dobbs reproductive-health-care state laws, 42 CFR Part 2 substance-use-treatment record applicability, state-specific HIV-and-genetic-information rules, state-level PPRL-specific rules where they exist). Architect the overlay-rules engine (versioned rule store, rule-evaluation Lambda invoked at encoding time with the patient's residence jurisdiction, use case's authorization scope, record-type sensitivity classification, and participating organizations' jurisdictional postures), the regulatory-monitoring function (shared between privacy and compliance teams; legislative-session feeds with explicit per-state subscription, regulatory-bulletin subscriptions, court-decision tracking; trigger thresholds with relevance-evaluation criteria), the per-record consent-posture decision audit trail, and the trust-framework-update pathway. --> |
| **Encryption** | Encoded-records S3 buckets: SSE-KMS with customer-managed keys, bucket-level keys, restricted access policy. Audit-archive S3 bucket: SSE-KMS with customer-managed keys, Object Lock in Compliance mode. Linkage-cycle-metadata DynamoDB: customer-managed KMS at rest. Linkage-results DynamoDB: customer-managed KMS at rest. Salt custody: CloudHSM where the higher-assurance posture is required, KMS customer-managed keys otherwise; the salt is itself encrypted under the HSM/KMS key with no plaintext extraction permitted. Glue temp storage: KMS-encrypted. Lambda log groups: KMS-encrypted. SageMaker: KMS-encrypted volumes and outputs. Nitro Enclave attestation: hardware-attested with the parent EC2 instance verifying the enclave's measurement before contributing the salt-key version. EventBridge and SQS: server-side encryption. TLS 1.2 or higher for all in-transit traffic. mTLS where the protocol requires it. |
| **VPC** | Production: per-participant Lambdas and Glue jobs in VPC. Linkage-execution endpoint in a separate VPC (typically a separate AWS account). VPC endpoints for KMS, S3, DynamoDB, Secrets Manager, CloudWatch Logs, EventBridge, SQS, Step Functions, Glue, Athena, STS, SageMaker. PrivateLink for the cross-participant encoded-data exchange where the protocol requires it. NAT Gateway for outbound HTTPS to the linkage-execution endpoint where PrivateLink is not used; outbound proxy with allow-list. <!-- TODO (TechWriter): Expert review N1 (LOW). Specify the per-participant cross-account bucket-policy template, the PrivateLink endpoint configuration, the per-cycle network-policy expiration that aligns with the linkage-cycle's active execution window, and the audit-and-monitoring discipline on the cross-account exchange. Also specify the salt-custody-network-isolation pattern (Finding N2, LOW): the salt custody (KMS or CloudHSM) is in a separate VPC with no inbound network access from the production data plane; salt-related operations route through a dedicated salt-custody endpoint with mTLS authentication and the dual-control approval Lambda as the only authorized caller. --> |
| **CloudTrail** | Enabled with data events on the salt-custody resources, the encoded-records buckets, the linkage-cycle-metadata table, the linkage-results table, and the audit-archive bucket. Glue job runs and SageMaker training runs logged. Step Functions executions logged. EventBridge events logged. CloudTrail logs encrypted with KMS and retained per the regulatory floor (typically the longest of HIPAA records-retention 7-year minimum, state medical-records-retention, the protocol-specific audit-retention floor, and the multi-party trust-framework's audit-retention requirement; many PPRL trust frameworks specify a longer audit retention than the regulatory minimum because the linkage's privacy claim depends on retrospective audit). Audit logs in a dedicated S3 bucket with Object Lock in Compliance mode and lifecycle to S3 Glacier Deep Archive after 90 days; CloudTrail data events forwarded to a dedicated audit AWS account. Same chapter pattern as 5.1, 5.4, 5.5, 5.6, 5.7. <!-- TODO (TechWriter): Expert review S2 (MEDIUM). Replace the "per the regulatory retention floor" framing with an explicit floor that names the longest of: HIPAA 7-year minimum, state medical-records-retention, the multi-party trust-framework's audit-retention requirement (typically 10-15 years; the trust framework's privacy claim depends on retrospective auditability of the cryptographic-root-of-trust operations including salt generation and rotation and access), the pilot-data agreement's audit retention where applicable, the IRB-approved research substrate's audit retention where the linkage feeds research, and the cross-jurisdictional retention overlay where the linkage spans national borders (the most restrictive jurisdiction governs). For salt-related audit events (salt generation, salt rotation, salt access, salt-key-version promotion, salt-decommission), specify the separately access-controlled bucket with the trust-framework's specified retention floor (typically the longest of the above plus an additional 5 years to accommodate post-deployment retrospective re-identification-risk evaluation). --> |
| **Reference Data and Protocol Parameterization** | A versioned reference-data store with: the salt-key-version (rotated per protocol cadence), the n-gram size, the Bloom-filter size, the hash-function count, the per-feature bit allocation, the defensive-measures parameters (random-hashing seed, balanced-encoding parameters, hardening parameters), the cohort-axis-hash specification (which features map to which cohort axes locally at each participant). The reference data refreshes on a regular cadence and is versioned so each linkage cycle references the parameterization version active at the cycle's start. Salt rotation is a separate event from parameterization upgrade; both invalidate the encoded data and require re-encoding. |
| **Sample Data** | Synthetic data with modeled cross-organizational overlap. Synthea generates synthetic patient populations; extending Synthea to produce two or more "organizations" with overlapping populations (the same synthetic patients appearing in both with appropriate demographic-feature variation across organizations) is feasible. Pilot calibration with a known-overlap population (where the institution has a verified overlap with a counterparty under a specific data-sharing agreement that permits the pilot evaluation) provides the absolute-accuracy benchmarks the in-production thresholds are calibrated against. Never use real PHI in development environments. |
| **Cost Estimate** | At a research linkage with two participants each contributing one million records per cycle, four cycles per year: Glue compute for per-participant encoding typically $200-800 per cycle; cross-account S3 storage and transfer typically $50-200 per cycle; DynamoDB for linkage-cycle metadata and results typically $50-200 per month; Nitro Enclave or Glue compute for the matcher execution typically $300-1,200 per cycle; SageMaker calibration and cohort-stratified-accuracy reports typically $200-600 per cycle; KMS, CloudHSM, Athena, QuickSight, EventBridge, SQS, Step Functions in aggregate typically $300-800 per month; CloudHSM (where used) typically $1,500-2,500 per month for the dedicated HSM. Total AWS infrastructure typically $2,400-7,000 per month at this scale, dominated by CloudHSM (where used) and per-cycle Glue and Nitro Enclave compute. <!-- TODO: replace with verified, current pricing once the implementing team validates against the AWS Pricing Calculator. --> |

### Ingredients

| AWS Service | Role |
|------------|------|
| **AWS Nitro Enclaves** | Hardware-attested isolated execution environment for the matcher in TEE-based protocols |
| **AWS KMS** | Customer-managed encryption keys for the encoded-record stores, the linkage-cycle-metadata, the audit archive, and the per-cycle salt-key derivation |
| **AWS CloudHSM** | Single-tenant hardware-security-module for the high-assurance salt-custody pattern (where the institutional security posture or the protocol's trust framework requires it) |
| **Amazon S3** | Per-participant encoded-records buckets with cross-account access policies, the audit-archive bucket with Object Lock in Compliance mode, derived-zone snapshots for analytics |
| **Amazon DynamoDB** | Linkage-cycle-metadata table (per-cycle parameterization version, consent posture summary, per-participant record count, run timestamps, disclosure target, disclosure form), linkage-results-store (per-pair linkage decisions with disclosure-policy-aware projection) |
| **AWS Lambda** | Per-participant encoding (small-batch path), per-participant standardize-and-prepare, disclose-and-route, invalidate-on-event |
| **AWS Glue and Apache Spark** | Per-participant bulk encoding for population-scale cycles, the matcher-execution job in the linkage-endpoint account where Nitro Enclaves are not used |
| **AWS Step Functions** | Linkage-cycle orchestration with per-stage retries, error routing to DLQs, parallel execution across participants where the protocol allows, explicit synchronization barriers where the protocol requires |
| **Amazon EventBridge** | Cross-recipe event fan-out: `pprl_linkage_cycle_completed`, `pprl_salt_rotation_initiated`, `pprl_salt_rotation_completed`, `pprl_parameterization_upgraded`, `pprl_consent_withdrawn`, `pprl_re_encoding_required` |
| **Amazon SQS** | Linkage-review queue (medium-confidence pairs for cohort-and-cycle-aware review tooling), propagation queue (downstream consumer fan-out) |
| **Amazon SageMaker** | Threshold calibration over the pilot-overlap data, cohort-stratified-accuracy reports against the cohort-axis hashes contributed by each participant |
| **Amazon Athena and AWS Glue Data Catalog** | SQL access to the linkage-cycle metadata and the cohort-stratified-accuracy snapshots |
| **AWS Lake Formation** | Column-level and row-level access controls for the differentiated audiences (treatment, research, audit, governance) |
| **AWS PrivateLink** | Private network path for the cross-participant encoded-data exchange where the protocol prohibits exchange through publicly-routable endpoints |
| **Amazon QuickSight** | Operational and quality dashboards (per-participant encoding rate, per-cycle linkage-rate trend, per-cohort linkage-rate disparity, salt-rotation cadence and coverage, parameterization-upgrade adoption, consent-withdrawal volume, re-encoding backlog, audit-volume trends) |
| **Amazon CloudWatch** | Operational metrics and alarms (review-queue depth and aging, encoding-failure rates, cohort-stratified disparities, salt-rotation backlog) |
| **AWS CloudTrail** | Audit logging for all API calls on the salt custody, the encoded-records buckets, the linkage-cycle-metadata, the linkage-results, and the audit-archive |

---

### Code

> **Reference implementations:** Useful libraries and patterns for this recipe:
> - [`anonlink`](https://github.com/data61/anonlink): an open-source Python toolkit for CLK-based privacy-preserving record linkage from CSIRO's Data61 / Confidential Computing Consortium. The toolkit provides reference implementations of the encoding-and-matching algorithms used in production PPRL deployments. <!-- TODO: confirm the current upstream URL at time of build; the Confidential Computing Consortium has reorganized some repositories. -->
> - [`clkhash`](https://github.com/data61/clkhash): the companion encoding library for `anonlink` that produces CLK-encoded records from demographic features under a shared schema and salt.
> - [OpenMined PSI](https://github.com/OpenMined/PSI): an open-source private-set-intersection toolkit with C++ and Python bindings; a reference implementation of the PSI protocol family.
> - [Microsoft SEAL](https://github.com/microsoft/SEAL): an open-source homomorphic-encryption library; useful for the SMPC-based PPRL family where the matcher's similarity computation runs on encrypted features.
> - [MP-SPDZ](https://github.com/data61/MP-SPDZ): an open-source secure-multi-party-computation toolkit covering several SMPC protocols (BGW, GMW, SPDZ family); a reference implementation for the SMPC-based PPRL family.
> - The [Confidential Computing Consortium](https://confidentialcomputing.io/): an industry consortium covering TEE-based confidential-computing patterns including PPRL.

#### Walkthrough

**Step 1: Standardize and prepare the per-participant demographic-feature set.** Every participating organization standardizes its demographic features under the same schema before encoding. The standardization is the same work that a conventional matcher does (case-folding, whitespace stripping, USPS address standardization, diacritic folding) but it has to be deterministic and cross-participant-compatible because any divergence in standardization produces encoded records that the matcher cannot reliably compare. Skip the standardization step and the encoding produces records whose Bloom filters carry the institution's idiosyncratic demographic-feature representation rather than the cross-participant-compatible representation, and the linkage rate drops substantially.

```
FUNCTION standardize_and_prepare(source_record_batch,
                                     participant_id,
                                     consent_filter_policy,
                                     cohort_axis_specification):
    standardized_records = []

    FOR EACH source_record IN source_record_batch:
        // Step 1A: apply the consent and purpose-of-use
        // filter. Records the patient has not consented to
        // include, records under jurisdiction-specific
        // suppression, records the institutional policy
        // excludes from this purpose are dropped.
        IF NOT consent_filter_policy.permits(source_record):
            CONTINUE

        // Step 1B: standardize the demographic features
        // under the protocol's shared schema. The schema
        // is a per-feature normalization specification
        // negotiated cross-participant.
        normalized = {
            given_name: normalize_given_name(
                source_record.given_name,
                fold_case=TRUE,
                strip_whitespace=TRUE,
                fold_diacritics=TRUE,
                strip_punctuation=TRUE
            ),
            family_name: normalize_family_name(
                source_record.family_name,
                handle_naming_tradition=
                    cohort_axis_specification
                      .name_tradition_handler
            ),
            dob: normalize_dob(
                source_record.dob,
                target_format="YYYY-MM-DD"
            ),
            sex_or_gender: normalize_sex_or_gender(
                source_record.sex_or_gender,
                target_vocabulary=
                    "protocol_specified_vocabulary"
            ),
            address_line: normalize_address(
                source_record.address,
                usps_standardize=TRUE,
                drop_unit_designator=
                    "protocol_specified_handling"
            ),
            zip_code: normalize_zip(
                source_record.zip_code,
                target_format="zip5"
            ),
            phone: normalize_phone(
                source_record.phone,
                target_format="e164",
                drop_extension=TRUE
            ),
            ssn_last_4: normalize_ssn_last_4(
                source_record.ssn,
                if_present=TRUE
            )
        }

        // Step 1C: derive the cohort-axis hashes. Each
        // participant computes its own cohort-axis values
        // locally (using its own demographic visibility) and
        // hashes them under the cohort-axis-hash key. The
        // matcher receives the hashes (not the values) and
        // can stratify accuracy metrics by hash without
        // learning the underlying axis values.
        cohort_axis_hashes = compute_cohort_axis_hashes(
            source_record,
            cohort_axis_specification,
            cohort_axis_hash_key=
                load_cohort_axis_hash_key()
        )

        // Step 1D: tag the record with metadata that the
        // matcher needs but that does not expose
        // demographics.
        prepared_record = {
            participant_id: participant_id,
            source_record_id: source_record.local_id,
                // Retained locally; not included in the
                // encoded payload that gets exchanged.
            normalized_features: normalized,
            consent_posture: source_record.consent_posture,
            cohort_axis_hashes: cohort_axis_hashes,
            prepared_at: current UTC timestamp
        }

        standardized_records.append(prepared_record)

    RETURN standardized_records
```

**Step 2: Apply the cryptographic encoding under the pinned protocol parameterization.** The encoding step is per-participant; it transforms the standardized record into a Cryptographic-Long-Term-Key (CLK) encoded form. The CLK is a single Bloom filter that combines the per-feature Bloom filters under the per-feature bit allocation. The matcher consumes the CLK without seeing the underlying demographic features. Skip the parameterization-version pinning and you produce encoded records that are not comparable to the counterparty's records produced under a different parameterization version, and the linkage silently fails.

```
FUNCTION encode_record(prepared_record, parameterization_version):
    // Step 2A: load the protocol parameterization. The
    // parameterization is loaded from a versioned
    // configuration store with the version pinned to the
    // current linkage cycle (set by the cycle orchestrator).
    parameterization = config_store.load_parameterization(
        parameterization_version)

    // The parameterization contains:
    // - salt_key_version: reference to the current salt key
    //   in the salt custody (KMS or CloudHSM)
    // - n_gram_size: typically 2 (bigrams) or 3 (trigrams)
    // - bloom_filter_size: typically 1024 or 2048
    // - hash_function_count: typically 30
    // - per_feature_bit_allocation: the share of the bloom
    //   filter assigned to each feature
    // - defensive_measures:
    //     random_hashing_enabled: TRUE / FALSE
    //     balanced_encoding_enabled: TRUE / FALSE
    //     hardening_parameters: per-protocol-specific

    // Step 2B: load the salt key for this cycle. The salt
    // key is loaded into a HSM-backed KMS context; the
    // plaintext salt is never exposed to the encoding
    // process; the per-feature hashing operations call
    // into the HSM context.
    salt_context = salt_custody.acquire_per_cycle_context(
        parameterization.salt_key_version,
        cycle_id=current_cycle_id())

    // Step 2C: produce the per-feature Bloom filters.
    per_feature_filters = {}

    FOR EACH (feature_name, normalized_value) IN
              prepared_record.normalized_features:
        IF normalized_value IS NULL:
            // Missing features get a sentinel filter; the
            // matcher's Fellegi-Sunter combiner handles
            // missing-feature cases under the protocol's
            // missing-feature weights.
            per_feature_filters[feature_name] =
                produce_missing_feature_filter(
                    parameterization, feature_name)
            CONTINUE

        // Tokenize the value into n-grams.
        n_grams = produce_n_grams(
            normalized_value,
            n=parameterization.n_gram_size,
            include_start_end_markers=TRUE)

        // Initialize an empty bit array of the protocol's
        // size. The per-feature filter is the share of the
        // total bloom filter assigned to this feature.
        per_feature_size = compute_per_feature_size(
            parameterization.bloom_filter_size,
            parameterization.per_feature_bit_allocation,
            feature_name)
        feature_filter = bit_array_of_size(per_feature_size)

        // For each n-gram, compute the k hash values and
        // set the corresponding bit positions.
        FOR EACH n_gram IN n_grams:
            FOR k_index IN 0 TO parameterization
                                    .hash_function_count - 1:
                hash_value = salt_context.hmac_sha_256(
                    key_index=k_index,
                    input=n_gram)
                bit_position = hash_value MOD per_feature_size
                feature_filter.set_bit(bit_position)

        // Apply defensive measures (random hashing,
        // balanced encoding, hardening) per the
        // parameterization. These adjust the feature_filter
        // to defeat known re-identification attacks.
        IF parameterization.defensive_measures
                              .random_hashing_enabled:
            feature_filter = apply_random_hashing(
                feature_filter,
                parameterization.defensive_measures
                    .random_hashing_seed,
                prepared_record.source_record_id)

        IF parameterization.defensive_measures
                              .balanced_encoding_enabled:
            feature_filter = apply_balanced_encoding(
                feature_filter,
                parameterization.defensive_measures
                    .balanced_encoding_parameters)

        IF parameterization.defensive_measures
                              .hardening_parameters
                              .enabled:
            feature_filter = apply_hardening(
                feature_filter,
                parameterization.defensive_measures
                    .hardening_parameters)

        per_feature_filters[feature_name] = feature_filter

    // Step 2D: combine the per-feature filters into the
    // record-level CLK under the per-feature bit allocation.
    clk = combine_per_feature_filters_into_clk(
        per_feature_filters,
        parameterization.per_feature_bit_allocation)

    // Step 2E: build the encoded-record envelope. The
    // envelope carries the CLK plus the metadata the
    // matcher needs (participant_id, encoded_record_id,
    // consent_posture, cohort_axis_hashes,
    // parameterization_version, encoded_at) but does not
    // carry the normalized demographics or the source
    // record identifier.
    encoded_record_envelope = {
        participant_id: prepared_record.participant_id,
        encoded_record_id: generate_encoded_record_id(),
            // Per-cycle pseudonym; not the source_record_id
            // and not derived from the demographics.
        clk_payload: clk.to_compact_representation(),
        consent_posture: prepared_record.consent_posture,
        cohort_axis_hashes:
            prepared_record.cohort_axis_hashes,
        parameterization_version: parameterization_version,
        salt_key_version:
            parameterization.salt_key_version,
        encoded_at: current UTC timestamp
    }

    // Step 2F: persist the per-cycle local mapping from the
    // encoded_record_id to the source_record_id. The mapping
    // is retained at the participant only; it is never
    // included in the encoded-record envelope or the
    // cross-participant exchange. The mapping enables the
    // participant to later resolve match results back to
    // the source records under its own access controls.
    participant_local_mapping_store.put({
        cycle_id: current_cycle_id(),
        encoded_record_id:
            encoded_record_envelope.encoded_record_id,
        source_record_id: prepared_record.source_record_id,
        encoded_at:
            encoded_record_envelope.encoded_at
    })

    RETURN encoded_record_envelope
```

**Step 3: Exchange the encoded records under the trust architecture.** The participating organizations deliver their encoded payloads to the linkage-execution endpoint. The exchange is the trust-architecture-defining step; the choice of transport, authentication, and audit posture reflects the protocol's specific privacy claims. Skip the exchange-time auditing and the protocol's audit posture is broken: a counterparty that uploaded an encoded payload cannot prove what it uploaded if the linkage's results are later disputed.

```
FUNCTION exchange_encoded_records(encoded_record_envelopes,
                                       trust_architecture_config,
                                       cycle_id):
    // Step 3A: validate that every envelope in the batch
    // was produced under the parameterization and salt-key
    // versions pinned for this cycle. Mis-coordinated
    // versions are the most common operational failure
    // mode; catch them before exchange.
    cycle_metadata =
        cycle_metadata_store.get(cycle_id)

    FOR EACH envelope IN encoded_record_envelopes:
        IF envelope.parameterization_version !=
            cycle_metadata.parameterization_version:
            RAISE ParameterizationMismatchError(
                envelope.encoded_record_id,
                envelope.parameterization_version,
                cycle_metadata.parameterization_version)

        IF envelope.salt_key_version !=
            cycle_metadata.salt_key_version:
            RAISE SaltKeyMismatchError(
                envelope.encoded_record_id,
                envelope.salt_key_version,
                cycle_metadata.salt_key_version)

    // Step 3B: route the envelopes to the linkage-execution
    // endpoint per the trust architecture.
    IF trust_architecture_config.transport_type ==
        "tokenizer_model":
        // Upload to the tokenizer's designated S3 bucket
        // under the cross-account access policy negotiated
        // in the contract; the tokenizer ingests and
        // produces the linkage results.
        upload_with_signed_envelope_and_mtls(
            envelopes=encoded_record_envelopes,
            destination=trust_architecture_config
                          .tokenizer_ingestion_bucket,
            cycle_id=cycle_id,
            participant_id=cycle_metadata
                              .current_participant_id)

    ELIF trust_architecture_config.transport_type ==
        "linkage_broker_model":
        // Upload to the linkage-broker's S3 bucket. The
        // linkage broker has visibility to the encoded
        // payloads but not the demographics.
        upload_with_signed_envelope_and_mtls(
            envelopes=encoded_record_envelopes,
            destination=trust_architecture_config
                          .linkage_broker_ingestion_bucket,
            cycle_id=cycle_id,
            participant_id=cycle_metadata
                              .current_participant_id)

    ELIF trust_architecture_config.transport_type ==
        "tee_attested_endpoint":
        // The matcher runs in a Nitro Enclave; verify the
        // attestation document before uploading the
        // encoded payload. The attestation proves the
        // enclave is running the agreed measurement.
        attestation_doc =
            request_enclave_attestation(
                trust_architecture_config
                  .enclave_endpoint)

        IF NOT verify_attestation(
                attestation_doc,
                trust_architecture_config
                  .expected_measurement,
                trust_architecture_config
                  .pcr_values):
            RAISE EnclaveAttestationFailedError()

        // Upload through the attested vsock or PrivateLink
        // path.
        upload_via_attested_endpoint(
            envelopes=encoded_record_envelopes,
            destination=trust_architecture_config
                          .enclave_endpoint,
            cycle_id=cycle_id)

    ELIF trust_architecture_config.transport_type ==
        "smpc_protocol_runner":
        // Engage in the multi-round SMPC protocol with the
        // counterparties. Each round of the protocol
        // exchanges protocol-specific messages over mTLS;
        // the encoded data is never directly exchanged but
        // is consumed by the SMPC primitives.
        smpc_runner.execute_protocol(
            envelopes=encoded_record_envelopes,
            counterparties=trust_architecture_config
                              .counterparty_endpoints,
            protocol_specification=
                trust_architecture_config
                  .protocol_specification,
            cycle_id=cycle_id)

    // Step 3C: log the exchange to the participant's local
    // audit store. Every exchange event is logged with the
    // cycle_id, the parameterization_version, the
    // salt_key_version, the per-record count, the
    // destination identifier, and the timestamp.
    participant_audit_store.log({
        event_type: "PPRL_EXCHANGE",
        cycle_id: cycle_id,
        participant_id: cycle_metadata.current_participant_id,
        parameterization_version:
            cycle_metadata.parameterization_version,
        salt_key_version:
            cycle_metadata.salt_key_version,
        record_count: len(encoded_record_envelopes),
        transport_type:
            trust_architecture_config.transport_type,
        destination: trust_architecture_config
                       .destination_identifier,
        exchanged_at: current UTC timestamp
    })

    RETURN exchange_status
```

**Step 4: Match the encoded records under the protocol's matching function.** The matcher operates on the encoded data without ever seeing the underlying demographics. The matching function is protocol-specific: Sørensen-Dice for Bloom filters, equality for tokenized data, the SMPC primitives for the SMPC family. The thresholds are calibrated separately from the conventional matcher's thresholds because the encoded scoring function is different. Skip the encoded-data threshold calibration and you re-use the conventional thresholds, which produces silent linkage failures because the encoded similarity scores are systematically lower for the same underlying record pair.

```
FUNCTION match_encoded_records(encoded_record_sets,
                                    parameterization,
                                    threshold_calibration,
                                    cohort_axis_specification):
    match_results = []

    // Step 4A: candidate-generation step (blocking). For
    // Bloom-filter-encoded data, candidate generation uses
    // properties of the CLK (e.g., locality-sensitive
    // hashing on the CLK bits) to reduce the candidate
    // pair count from O(n*m) to a tractable subset. For
    // tokenized data, candidate generation may be a direct
    // hash join. For SMPC-based protocols, candidate
    // generation depends on the protocol primitive.
    candidate_pairs = candidate_generation(
        encoded_record_sets,
        parameterization)

    FOR EACH (record_a, record_b) IN candidate_pairs:
        // Step 4B: per-pair similarity scoring. For
        // Bloom-filter-encoded data, compute the
        // Sørensen-Dice coefficient between the CLKs.
        // For tokenized data, equality. For SMPC, the
        // protocol-specific primitive.
        per_feature_similarity_scores =
            compute_per_feature_similarities(
                record_a, record_b, parameterization)

        // Step 4C: per-pair Fellegi-Sunter combination.
        // The same probabilistic-record-linkage core
        // from recipes 5.1 and 5.5, with the feature
        // weights calibrated against the encoded data.
        match_score = combine_with_fellegi_sunter(
            per_feature_similarity_scores,
            threshold_calibration.feature_weights,
            threshold_calibration.missing_feature_weights)

        // Step 4D: apply the encoded-data thresholds.
        IF match_score >= threshold_calibration
                            .ENCODED_MATCH_HIGH:
            decision = "MATCH_HIGH"
        ELIF match_score >= threshold_calibration
                              .ENCODED_MATCH_MED:
            decision = "MATCH_MED_REVIEW"
        ELIF match_score <= threshold_calibration
                              .ENCODED_REJECT:
            decision = "REJECT"
        ELSE:
            decision = "REVIEW"

        // Step 4E: build the per-pair result with the
        // evidence summary and the cohort-axis hashes
        // for downstream cohort-stratified-accuracy
        // monitoring.
        match_result = {
            participant_a_id: record_a.participant_id,
            participant_b_id: record_b.participant_id,
            encoded_record_a_id: record_a.encoded_record_id,
            encoded_record_b_id: record_b.encoded_record_id,
            match_score: match_score,
            decision: decision,
            evidence_summary: {
                per_feature_similarities:
                    per_feature_similarity_scores,
                feature_weights_version:
                    threshold_calibration.weights_version
            },
            cohort_axis_hashes_a: record_a.cohort_axis_hashes,
            cohort_axis_hashes_b: record_b.cohort_axis_hashes,
            consent_posture_a: record_a.consent_posture,
            consent_posture_b: record_b.consent_posture,
            parameterization_version:
                parameterization.parameterization_version,
            matched_at: current UTC timestamp
        }

        match_results.append(match_result)

    RETURN match_results
```

**Step 5: Apply the disclosure policy and route the linkage results.** The matcher produces match decisions; the disclosure step transforms the decisions into the form the protocol authorizes for delivery to the consumer. The disclosure form is protocol-specific: per-record yes/no flags, intersection counts, encrypted match indicators, k-anonymous summaries, differentially-private aggregates. Skip the disclosure-policy step and you deliver the per-record matches to a consumer that the protocol authorized only for aggregate-level disclosure, which is a privacy violation that the audit cannot retract.

```
FUNCTION disclose_linkage_results(match_results,
                                       disclosure_policy,
                                       cycle_id):
    // Step 5A: filter to the consent-and-purpose-aligned
    // results. Records whose consent posture does not
    // permit inclusion in this disclosure are filtered out
    // even if the matcher produced a match.
    consent_filtered_results = []
    FOR EACH match_result IN match_results:
        IF disclosure_policy
              .consent_posture_permits(
                match_result.consent_posture_a,
                match_result.consent_posture_b):
            consent_filtered_results.append(match_result)

    // Step 5B: apply the disclosure-form transformation.
    IF disclosure_policy.disclosure_form ==
        "per_record_match_flags":
        // The consumer receives per-record yes/no flags.
        // Each consumer's view is filtered to its own
        // records (the consumer is a participating
        // organization and can only see matches involving
        // its own records).
        disclosure_envelope = build_per_record_match_flags(
            consent_filtered_results,
            disclosure_policy.target_consumer)

    ELIF disclosure_policy.disclosure_form ==
        "intersection_count":
        // The consumer receives only the size of the
        // intersection (no per-record detail).
        disclosure_envelope = build_intersection_count(
            consent_filtered_results)

    ELIF disclosure_policy.disclosure_form ==
        "k_anonymous_aggregate":
        // The consumer receives k-anonymous aggregates
        // with small-cell suppression.
        disclosure_envelope = build_k_anonymous_aggregate(
            consent_filtered_results,
            disclosure_policy.k_anonymity_parameter,
            disclosure_policy.suppression_threshold)

    ELIF disclosure_policy.disclosure_form ==
        "differentially_private_aggregate":
        // The consumer receives aggregates with
        // calibrated DP noise.
        disclosure_envelope =
            build_differentially_private_aggregate(
                consent_filtered_results,
                disclosure_policy.epsilon,
                disclosure_policy.delta,
                disclosure_policy.aggregate_specification)

    ELIF disclosure_policy.disclosure_form ==
        "encrypted_match_indicator":
        // The matches are encrypted under the consumer's
        // public key; only the consumer can decrypt.
        disclosure_envelope = build_encrypted_match_indicator(
            consent_filtered_results,
            disclosure_policy.consumer_public_key)

    // Step 5C: route the disclosure to the target consumer.
    deliver_with_signed_envelope_and_mtls(
        disclosure_envelope=disclosure_envelope,
        target_consumer=disclosure_policy.target_consumer,
        cycle_id=cycle_id)

    // Step 5D: emit the cycle-completion event for cross-
    // recipe consumers.
    EventBridge.PutEvents([{
        source: "privacy-preserving-record-linkage",
        detail_type: "pprl_linkage_cycle_completed",
        detail: {
            cycle_id: cycle_id,
            disclosure_form:
                disclosure_policy.disclosure_form,
            target_consumer:
                disclosure_policy.target_consumer
                  .consumer_identifier,
            participant_count:
                len(unique_participants(match_results)),
            matched_pair_count:
                len(consent_filtered_results),
            disclosed_at: current UTC timestamp
        }
    }])

    // Step 5E: log the disclosure to the audit archive.
    // The audit log captures the disclosure-form, the
    // target-consumer, the per-record count, and the
    // cohort-stratified-accuracy summary, but does not
    // log the actual disclosure payload (which would
    // duplicate the consumer's copy).
    audit_archive.log_disclosure({
        event_type: "PPRL_DISCLOSURE",
        cycle_id: cycle_id,
        disclosure_form:
            disclosure_policy.disclosure_form,
        target_consumer:
            disclosure_policy.target_consumer
              .consumer_identifier,
        record_count: len(consent_filtered_results),
        cohort_stratified_accuracy_summary:
            compute_cohort_stratified_summary(
                consent_filtered_results),
        disclosed_at: current UTC timestamp
    })

    RETURN disclosure_envelope
```

**Step 6: React to invalidation events that supersede the linkage.** A linkage that was wrong, a salt that has rotated, a parameterization that has been upgraded, a consent that has been withdrawn, an underlying identity-merge or name-change reversal from recipes 5.1 or 5.7 all invalidate the prior linkage in different ways. The invalidation pipeline subscribes to these events and triggers the appropriate response (re-encode the affected records, re-run the matcher, communicate the superseded result to the consumer, route the affected records out of future cycles). Skip the invalidation pipeline and the prior linkage results drift out of sync with the underlying identity infrastructure; the drift compounds over time and undermines trust in every subsequent cycle.

```
FUNCTION invalidate_on_event(invalidation_event):
    // Identify the affected linkage cycles and the
    // affected encoded records.
    IF invalidation_event.source == "salt_rotation":
        // The salt has rotated. All encoded data under the
        // prior salt is invalidated. Schedule a coordinated
        // re-encoding cycle with all participants. Notify
        // downstream consumers that the prior cycle's
        // results are superseded by the next cycle's.
        affected_cycles = cycle_metadata_store
            .find_cycles_with_salt_key_version(
                invalidation_event.prior_salt_key_version)

        schedule_coordinated_re_encoding(
            participants=invalidation_event.participants,
            new_salt_key_version=
                invalidation_event.new_salt_key_version,
            new_parameterization_version=
                invalidation_event
                  .new_parameterization_version)

        notify_downstream_consumers(
            affected_cycles, "salt_rotation_supersedes")

    ELIF invalidation_event.source ==
        "parameterization_upgrade":
        // The parameterization has been upgraded. Schedule
        // a coordinated re-encoding under the new
        // parameterization. Existing cycles' results remain
        // valid for the use cases the prior parameterization
        // supported, but new cycles use the new
        // parameterization.
        schedule_coordinated_re_encoding(
            participants=invalidation_event.participants,
            new_salt_key_version=
                invalidation_event.salt_key_version,
            new_parameterization_version=
                invalidation_event.new_parameterization_version)

    ELIF invalidation_event.source ==
        "consent_withdrawal":
        // A patient has withdrawn consent for inclusion in
        // the linkage. The participating organization
        // removes the patient from future encoding. Prior
        // linkages remain in the consumer's possession;
        // the participating organization communicates the
        // withdrawal to the consumer per the protocol's
        // policy on retroactive handling.
        affected_participant_id =
            invalidation_event.participant_id
        affected_source_record_id =
            invalidation_event.source_record_id

        participant_local_consent_store.update({
            source_record_id: affected_source_record_id,
            consent_posture: "WITHDRAWN",
            withdrawn_at: invalidation_event.withdrawn_at
        })

        notify_downstream_consumers_of_consent_withdrawal(
            affected_participant_id,
            affected_source_record_id,
            disclosure_policy_for_withdrawal_handling)

    ELIF invalidation_event.source ==
        "identity_merge_recipe_5_1":
        // Recipe 5.1 merged two identities at the
        // participating organization. The prior encoded
        // records under the merged-from identity are
        // invalidated; the next cycle re-encodes the
        // surviving identity.
        affected_participant_id =
            invalidation_event.participant_id
        affected_source_record_ids =
            invalidation_event.merged_from_source_record_ids

        participant_local_re_encode_queue.enqueue(
            affected_source_record_ids)

    ELIF invalidation_event.source ==
        "name_change_recipe_5_7":
        // Recipe 5.7 resolved a name change. The encoded
        // records under the prior name are invalidated;
        // the next cycle re-encodes under the current
        // name (and may carry a prior-name encoding for
        // the cycles that need historical-name
        // matching).
        affected_participant_id =
            invalidation_event.participant_id
        affected_source_record_id =
            invalidation_event.source_record_id

        participant_local_re_encode_queue.enqueue(
            [affected_source_record_id])

    ELIF invalidation_event.source ==
        "re_identification_risk_model_update":
        // The institutional privacy team has updated the
        // re-identification-risk model. The
        // parameterization may need re-tuning;
        // defensive measures may need to be strengthened.
        // Schedule a coordinated parameterization upgrade
        // and re-encoding cycle.
        schedule_parameterization_upgrade(
            new_parameterization_version=
                invalidation_event
                  .new_parameterization_version,
            participants=invalidation_event.participants,
            target_completion_window=
                invalidation_event.target_completion_window)

    // Emit the invalidation event for downstream consumers
    // to refresh their derived state.
    EventBridge.PutEvents([{
        source: "privacy-preserving-record-linkage",
        detail_type: "pprl_linkage_invalidated",
        detail: {
            invalidation_source: invalidation_event.source,
            invalidation_event_id: invalidation_event.event_id,
            affected_cycle_ids: affected_cycle_ids_summary,
            affected_participant_ids:
                affected_participant_ids_summary,
            invalidated_at: current UTC timestamp
        }
    }])
```

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter05.08-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

---

### Expected Results

**Sample CLK-encoded record envelope (illustrative; actual CLK payload would be a binary bit array):**

```json
{
  "participant_id": "participant-A-academic-medical-center",
  "encoded_record_id": "enc-cycle-2026-q2-A-00284271",
  "clk_payload": "<base64-encoded-1024-bit-bloom-filter>",
  "consent_posture": {
    "consent_for_research_linkage": true,
    "consent_for_outcomes_research_purpose": true,
    "jurisdictional_overlay_applied": "post_dobbs_state_overlay_v1",
    "consent_recorded_at": "2026-01-15T10:34:22Z"
  },
  "cohort_axis_hashes": {
    "name_tradition_cohort_hash": "h-naming-tradition-08f4...",
    "age_decade_cohort_hash": "h-age-decade-2c91...",
    "sex_or_gender_cohort_hash": "h-sex-gender-7a13..."
  },
  "parameterization_version": "pprl-clk-v2.3.1",
  "salt_key_version": "salt-2026-q2-rotation-001",
  "encoded_at": "2026-04-22T14:08:33Z"
}
```

**Sample high-confidence match result:**

```json
{
  "cycle_id": "cycle-2026-q2-research-linkage-001",
  "match_id": "match-2026-q2-001-00094822",
  "participant_a_id": "participant-A-academic-medical-center",
  "participant_b_id": "participant-B-regional-payer",
  "encoded_record_a_id": "enc-cycle-2026-q2-A-00284271",
  "encoded_record_b_id": "enc-cycle-2026-q2-B-00891334",
  "match_score": 0.94,
  "decision": "MATCH_HIGH",
  "evidence_summary": {
    "per_feature_similarities": {
      "given_name_clk_dice": 0.97,
      "family_name_clk_dice": 0.99,
      "dob_token_match": 1.00,
      "address_clk_dice": 0.89,
      "zip_code_token_match": 1.00,
      "ssn_last_4_token_match": 1.00,
      "phone_clk_dice": 0.85
    },
    "feature_weights_version": "pprl-fs-v1.4.2"
  },
  "cohort_axis_hashes_a": {
    "name_tradition_cohort_hash": "h-naming-tradition-08f4...",
    "age_decade_cohort_hash": "h-age-decade-2c91...",
    "sex_or_gender_cohort_hash": "h-sex-gender-7a13..."
  },
  "cohort_axis_hashes_b": {
    "name_tradition_cohort_hash": "h-naming-tradition-08f4...",
    "age_decade_cohort_hash": "h-age-decade-2c91...",
    "sex_or_gender_cohort_hash": "h-sex-gender-7a13..."
  },
  "parameterization_version": "pprl-clk-v2.3.1",
  "matched_at": "2026-04-23T09:18:44Z"
}
```

**Sample disclosure envelope (per-record-match-flags form, scoped to participant A's view):**

```json
{
  "cycle_id": "cycle-2026-q2-research-linkage-001",
  "disclosure_form": "per_record_match_flags",
  "target_consumer": "participant-A-academic-medical-center",
  "disclosure_envelope": {
    "matches": [
      {
        "encoded_record_a_id": "enc-cycle-2026-q2-A-00284271",
        "matched_with_participant_id": "participant-B-regional-payer",
        "match_decision": "MATCH_HIGH",
        "match_score": 0.94
      }
    ],
    "total_records_contributed_by_a": 1027341,
    "total_matches_for_a": 412988,
    "match_rate_for_a": 0.402
  },
  "disclosed_at": "2026-04-23T09:32:12Z"
}
```

**Sample disclosure envelope (intersection-count form, used when the protocol authorizes only the count and not per-record details):**

```json
{
  "cycle_id": "cycle-2026-q2-public-health-surveillance-001",
  "disclosure_form": "intersection_count",
  "target_consumer": "state-public-health-department",
  "disclosure_envelope": {
    "intersection_count": 184722,
    "participant_a_total": 1027341,
    "participant_b_total": 487219,
    "match_rate_lower_bound": 0.380,
    "match_rate_upper_bound": 0.396
  },
  "disclosed_at": "2026-04-23T09:48:55Z"
}
```

**Sample disclosure envelope (k-anonymous-aggregate form, used when the protocol authorizes only k-anonymous cohort summaries):**

```json
{
  "cycle_id": "cycle-2026-q2-aco-out-of-network-ed-001",
  "disclosure_form": "k_anonymous_aggregate",
  "target_consumer": "aco-analytics-team",
  "k_anonymity_parameter": 11,
  "suppression_threshold": 5,
  "disclosure_envelope": {
    "out_of_network_ed_visits_by_age_decade_and_chronic_condition": [
      {
        "age_decade": "60-69",
        "chronic_condition": "diabetes",
        "visit_count_aggregate": 234,
        "patient_count_aggregate": 178
      },
      {
        "age_decade": "70-79",
        "chronic_condition": "diabetes",
        "visit_count_aggregate": 156,
        "patient_count_aggregate": 121
      },
      {
        "age_decade": "80-89",
        "chronic_condition": "diabetes",
        "visit_count_aggregate": "[suppressed: cell size below threshold]",
        "patient_count_aggregate": "[suppressed: cell size below threshold]"
      }
    ]
  },
  "disclosed_at": "2026-04-23T10:14:08Z"
}
```

**Performance benchmarks (illustrative, your mileage varies):**

| Metric | Conventional cross-facility matching (recipe 5.5) | PPRL with CLK encoding |
|--------|---------------------------------------------------|------------------------|
| Match rate at fixed false-acceptance threshold (FAR=0.005) | 92-96% | 80-90% |
| False-acceptance rate at fixed match threshold | 0.3-0.7% | 0.5-1.0% |
| Per-cohort linkage-rate disparity (best vs worst cohort) | 0.05-0.10 | 0.08-0.15 |
| Time-to-encode per record (Glue Spark) | n/a | 50-200 microseconds |
| Time-to-match per pair (Sørensen-Dice on Bloom filter) | n/a | 5-20 microseconds |
| Time-to-complete a population-scale linkage cycle (1M records each, 2 participants) | 1-3 hours (HIE-mediated) | 4-12 hours (encoding plus match plus disclosure) |
| Salt rotation cadence | n/a | quarterly to annually depending on protocol |
| Re-encoding time per population (1M records) | n/a | 2-6 hours |
| Audit-event volume per cycle | 50-200 (per-query audit) | 1,000-10,000 (per-stage audit including encoding, exchange, matching, disclosure) |

<!-- TODO: replace illustrative figures with measured results from the deployment. The above are typical ranges from published academic evaluations of CLK-based PPRL (Schnell, Vatsalan, Christen, and others) and from operational reports of commercial tokenization services; specific figures vary by population, by parameterization, and by data quality. -->

**Where it struggles:**

- **Demographic-feature missingness amplifies the encoding penalty.** A record with a missing field encodes to a CLK with a sentinel filter for that field. The Fellegi-Sunter combiner handles missing features under specific weights, but the missing-feature weight calibration is harder for encoded data (the calibration set has to include encoded missing-feature cases against encoded non-missing cases, which adds a dimension to the calibration). The mitigation is per-feature missingness rate monitoring with per-cohort breakdowns, plus deliberate encoding-time field-imputation policies for the fields where imputation is appropriate.
- **Names from non-dominant-culture traditions accumulate more encoding noise.** The bigram tokenization, the per-feature bit allocation, and the defensive-measures parameters were typically calibrated on populations dominated by Western European naming conventions. Spanish double surnames, East Asian family-name-first conventions, Arabic patronymics, and names with diacritics that the EHR strips on input all encode to CLKs that are less robust to legitimate variation than CLKs from Western European names. The cohort-stratified-linkage-rate disparity is the metric that catches this; the mitigation is per-tradition encoding-parameter tuning (separate per-feature bit allocations for shorter names, separate n-gram sizes for non-Latin scripts) calibrated against per-tradition gold sets, with explicit communication to the participating organizations about the tuning rationale.
- **Re-identification attacks against the encoded data have evolved.** The early Bloom-filter-based PPRL deployments were vulnerable to specific re-identification attacks (the Vatsalan-Christen frequency analysis, the Kuzu-et-al attack on small populations). The defensive measures (random hashing, balanced encoding, hardening) are designed to defeat these attacks. The institution's privacy team has to keep current with the published attack literature and update the defensive parameterization in response. The mitigation is a versioned parameterization with a periodic re-identification-risk review (every 12-18 months is typical), with the review owned by the institutional privacy team and communicated to the participating organizations through the trust-framework governance process.
- **The salt-rotation ceremony has no margin for error.** Every encoded record under a prior salt is invalidated by rotation; mis-coordinated rotation produces a population-scale loss of all encoded data under the wrong key. The mitigation is a ceremonial multi-organization rotation with explicit dual-control approval, audit-logged at every step, and an explicit catch-up-window (where the prior salt remains valid for read-only operations during the cutover) to give participants time to complete their re-encoding. The catch-up window is itself a privacy concern (the prior salt's data is still readable during the catch-up); the institution has to balance the operational discipline against the privacy posture.
- **Linkage results across protocols do not compose.** A patient who is matched in one PPRL cycle (under one protocol with one participant set) cannot be transitively linked across cycles with a different protocol or participant set. The encoded data is parameterization-specific; cross-cycle composition requires re-encoding under a common parameterization or operating against the union of protocols at the source-record level (where the demographics are still available). The mitigation is explicit per-cycle scope discipline and a cross-cycle index that the participating organizations maintain at the source-record level (under their own access controls) to compose linkages where the use case requires it.
- **Consent-withdrawal handling has retrospective limits.** A patient who withdraws consent for inclusion in a research linkage can be removed from future cycles, but prior cycles' results remain in the consumer's possession. The architecture cannot retract disclosures that have already left the institution, and the protocol's post-withdrawal handling is whatever the contract specifies. The mitigation is explicit handling of consent withdrawal as a forward-looking event with patient-facing communication about what can and cannot be retracted, plus institutional policy on whether to communicate the withdrawal to the consumer (some protocols specify the communication; others leave it to the participating organization's discretion).
- **Cross-jurisdictional applicability constraints multiply.** A patient's record under post-Dobbs reproductive-health-care state-law overlays may be excludable from one PPRL cycle but includable in another, depending on the consumer's jurisdiction and the use case. A record under 42 CFR Part 2 (substance-use treatment) may be excludable from most linkages without specific consent. A record from a patient who has gender-transition-related sensitivity classification (recipe 5.7) may be includable but with restricted disclosure form. The cross-jurisdictional rules accumulate in the consent-and-purpose-of-use governance layer; the mitigation is per-record consent-posture metadata that the encoding step consults and the disclosure step honors, with explicit institutional review of the per-jurisdictional-overlay rule set on a periodic cadence.
- **The linkage-result dispute-resolution path is institution-specific.** When a linkage result is disputed (the consumer's analysis surfaces what looks like a wrong match; one participant's downstream operations identify a record they believe was incorrectly linked), the dispute resolution requires going back to the source data at each participant under their own access controls. The PPRL protocol does not provide a built-in dispute-resolution mechanism; the institutional trust framework has to specify it. The mitigation is an explicit dispute-resolution clause in the trust framework with named contacts, a defined SLA, and an audit-logged process; without it, disputes drift and undermine confidence in subsequent cycles. <!-- TODO (TechWriter): Expert review A10 (MEDIUM). Promote the dispute-resolution path into the architecture pattern. Specify the dispute-intake mechanism (dedicated API endpoint with WAF and authentication for system-initiated disputes; dedicated UI for human-initiated disputes; dispute-tracking DynamoDB table keyed on (cycle_id, dispute_id); audit-archive bucket for dispute artifacts), the cross-participant source-data-resolution pathway (per-dispute access-control envelope with time-bound and scope-bound authorization; per-participant source-data-resolution Lambda invoked through Step Functions cross-participant orchestration; audit logging on every cross-participant source-data access), and the dispute-resolution-outcome propagation (outcome propagated through the EventBridge fan-out with explicit dispute-outcome event-types; consumer and participant notification with the outcome and the response-protocol; explicit "linkage-superseded" attribution where the outcome is "linkage was wrong"). -->
- **Cross-recipe coordination has subtle ordering effects.** A name change resolved in recipe 5.7 invalidates the encoded records under the prior name; an identity merge resolved in recipe 5.1 invalidates the encoded records under the merged-from identity; an address standardization update in recipe 5.3 may change the address-feature encoding. The PPRL re-encoding queue has to respect the cross-recipe event ordering and consolidate near-simultaneous events on the same record. The mitigation is an event-ordering-aware re-encoding queue with explicit deduplication and prioritization rules.
- **Pilot evaluation requires authorization the production deployment does not.** The pilot calibration of encoded-data thresholds requires a known-overlap population with full demographic visibility, which means the calibration step has to be authorized under a separate data-sharing agreement that permits the pilot evaluation. Some institutions do not have a counterparty willing to provide the pilot data; the calibration falls back to synthetic data, which is less accurate. The mitigation is investing in the pilot-data agreement as part of the trust-framework negotiation, with an explicit one-time scope and an audit-archive retention specifically for the pilot data.

---

## Why This Isn't Production-Ready

The pseudocode and architecture above demonstrate the pattern. A production deployment needs to close several gaps that are intentionally out of scope for a recipe.

**Trust-framework negotiation and contract drafting.** The multi-party trust framework is the load-bearing artifact for any PPRL deployment, and it is not a technical artifact. It is a contract that enumerates the participants, the protocol parameterization, the salt-management ceremony, the linkage-result-disclosure policy, the audit posture, the re-identification-risk model, the dispute-resolution mechanism, the consent-and-purpose-of-use governance, the cross-jurisdictional overlay handling, and the operational rhythms (salt-rotation cadence, parameterization-upgrade cadence, periodic re-identification-risk review cadence). The institutions that operate PPRL successfully have invested in the legal-and-compliance team's familiarity with the cryptographic primitives, with the trust-framework artifact, and with the ongoing governance. The institutions that have not made the investment discover, mid-project, that the trust framework cannot be drafted without senior legal and compliance review at every participant, and the project stalls. Plan the trust-framework negotiation as a project with its own timeline, its own staffing, and its own iteration discipline.

**Salt-management ceremony and HSM custody.** The shared cryptographic salt is the protocol's root-of-trust. Salt generation is a multi-party ceremony with explicit dual-control approval and audit logging. Salt custody is a hardware-security-module concern: the salt is stored in an HSM that no single participant can unilaterally access; the HSM enforces the access control through key policies that name the specific roles authorized to invoke the salt-related operations. Salt rotation is a coordinated multi-organization event with a published cadence and a catch-up window. Salt-related audit logging is a compliance requirement: every access to the salt is logged with the calling principal, the operation, the timestamp, and the cycle context. Build the salt-management capability as a deliberate operational program with named owners, named processes, and named review committees. Skip this and the salt is custodied informally, the audit trail is inconsistent, and the trust-framework's cryptographic claim is operationally unsupported.

<!-- TODO (TechWriter): Expert review A2 (MEDIUM). Specify the salt-management ceremony at the architectural level: the multi-party HSM ceremony that generates the salt (participants, cryptographic-key-generation procedure, audit-log schema, post-ceremony verification), the dual-control approval pattern (two HSM operators from non-overlapping organizations must approve the rotation operation through a separate approval-workflow Lambda; cross-account approval through the trust framework's enumerated participating-organization roles; rejection semantics for single-actor approvals; inter-organizational binding mechanism), the audit-log schema for salt-related operations (calling principal, operation, timestamp, cycle context, salt-key-version, dual-control approver identities, post-operation verification status), the catch-up-window policy with an explicit duration and access-control constraint (read-only access bound to the prior salt-key-version through KMS key-policy enforcement, audit logging on every read), the post-rotation re-encoding-coverage SLA per participant (CloudWatch metrics on per-participant coverage, alarm-on-degradation, response-protocol with explicit catch-up-window-extension authority), and the monitoring of re-encoding completion against the salt-rotation deadline. -->

**Threshold calibration and approval governance.** The ENCODED_MATCH_HIGH, ENCODED_MATCH_MED, ENCODED_REJECT thresholds, the per-feature weights, and the missing-feature weights are calibrated against a known-overlap pilot population encoded under the production parameterization. Re-calibration runs periodically and on detection of cohort-stratified disparity above the institutional threshold. Re-calibration produces a candidate threshold set; institutional review (analytics governance committee, compliance, clinical informatics, privacy team, equity-monitoring committee) reviews the confusion matrix and the cohort-disparity impact before promoting the candidate to production. Each linkage cycle references the configuration version active at decision time. Same chapter pattern as 5.1, 5.4, 5.5, 5.6, 5.7.

<!-- TODO (TechWriter): Expert review A4 (MEDIUM). Promote the threshold-calibration governance into the architecture text. Specify the versioned configuration table holding ENCODED_MATCH thresholds, per-feature weights, missing-feature weights, and per-jurisdiction overlay rules; the SageMaker calibration job that produces the candidate set against the pilot-overlap calibration data; the per-cohort impact-analysis requirement with explicit cohort-axis enumeration (name-tradition cohort, age-decade cohort, sex-or-gender cohort, name-change-frequency cohort where recipe 5.7 is upstream); the privacy-team inclusion in the review committee with explicit re-identification-risk review authority; the linkage-cycle reference to the configuration version active at decision time; and the pilot-data infrastructure as separately-governed substrate (separate AWS account, separate access controls, separate audit posture, separate retention rules; the production pipeline references the calibration outputs without re-accessing the underlying pilot data). -->

**Re-identification-risk review.** The institutional privacy team owns the re-identification-risk model and reviews it on a periodic cadence (every 12-18 months is typical, with off-cycle review when new attacks are published). The review evaluates the parameterization against published attacks, identifies necessary defensive-measure updates, and produces a recommendation that the trust-framework governance process consumes. The review is a formal artifact (a written re-identification-risk assessment with cited sources, identified risks, recommended mitigations, and residual-risk acceptance) that the participating organizations sign off on. Build the re-identification-risk review as a deliberate operational program with the institutional privacy team as the owner; without it, the parameterization stagnates while the attacks evolve.

<!-- TODO (TechWriter): Expert review A3 (MEDIUM). Promote the re-identification-risk review into the architecture pattern. Specify the structural artifacts (written re-identification-risk assessment with cited sources, identified risks, recommended mitigations, residual-risk acceptance with explicit privacy-team sign-off and trust-framework-governance review), the off-cycle trigger conditions (literature-monitoring function with explicit subscription to relevant venues, attack-database subscription with explicit relevance-evaluation criteria, vendor-advisory-monitoring for commercial-tokenizer integrations), the trust-framework governance consumption pathway (recommendation-to-governance-decision through the trust-framework-governance process; review committee composition, decision-making process, timeline, communication to participating organizations), and the parameterization-update path (governance-decision-to-parameterization-update through the parameterization-versioning configuration store with explicit cohort-stratified-impact-analysis at the promotion gate; parameterization-update-to-re-identification-risk-model-update event through the EventBridge fan-out; re-encoding pipeline triggered by the event). -->

**Three review queues with cohort-and-cycle-aware tooling.** The linkage-review queue surfaces medium-confidence pairs for human review; reviewers see the encoded-record IDs (not the demographics), the per-feature similarity scores, the cohort-axis hashes, and (under appropriate authorization) the source records at each participant. The salt-rotation review queue surfaces re-encoding completion status per participant for verification before the prior salt is decommissioned. The consent-withdrawal review queue surfaces patient-initiated withdrawals for verification (especially when delivered through a non-standard channel). Each review tool emits the reviewer's decision back into the matcher's training signal. Build the tools with the same care as the analytics pipeline; the matcher's accuracy depends on it. The reviewer-authentication is two-factor and the reviewer-action is dual-controlled for the salt-rotation review queue (two reviewers from non-overlapping organizations must approve the salt-rotation completion).

<!-- TODO (TechWriter): Expert review S3 (MEDIUM). Promote the three review-queue audit posture into the architecture pattern. Specify per-queue audit posture (reviewer identity with appropriate authentication, decision, stated reason, configuration version active at the time, threshold or parameterization version active at the time, any reviewer-supplied additional context). For the salt-rotation review queue, specify dual-control with two reviewers from non-overlapping organizations enforced through cross-account approval; per-participant re-encoding-coverage status verification before prior-salt decommission; audit logging of every salt-rotation completion event with both reviewer identities and the per-participant re-encoding-coverage status; explicit decommission-of-prior-salt audit entry. For the consent-withdrawal review queue, specify patient re-authentication for non-standard-channel withdrawals; reviewer's decision audit; conflict-of-interest screening with the recipe-specific extension to patient-relationship-with-reviewer beyond the standard conflict-of-interest categories. The reviewer-authentication is two-factor and the reviewer-action is dual-controlled for the salt-rotation review queue. -->

**Patient-consent capture and withdrawal pathways.** The PPRL deployment assumes that the patient has been asked (and has consented or declined) for inclusion in the linkage. The mechanism for asking is not the matcher's job; it is the registration workflow's, the patient-portal app's, and (for clinical-care contexts) the institutional consent-management workflow's. Build the consent-capture and withdrawal-pathway as a deliberate workflow with appropriate framing, training for the staff who solicit the information, and patient-facing communication about what the linkage does and what consent withdrawal means. Skip this and the consent posture is operating on default values that may not match the patient's actual preferences, with predictable trust failures when patients discover their records were included in a linkage they did not consent to.

**Information-blocking compliance posture.** The 21st Century Cures Act information-blocking provisions apply to PPRL in non-obvious ways: a patient who has authorized an external research consortium to access her records has, by extension, authorized the PPRL linkage that the consortium uses; a patient whose records are excluded from the linkage because of a consent-withdrawal or a jurisdictional overlay should be able to receive an explanation of why the records were excluded and to authorize an alternative disclosure mechanism if available. The architecture has to surface the consent-and-jurisdictional-exclusion reasoning to the patient on request without exposing the linkage's cryptographic primitives. Build the patient-access-API release path with explicit awareness of the PPRL exclusion reasons.

**Cross-organizational propagation policy.** The PPRL pipeline does not propagate the linkage results across organizations beyond the disclosure-policy-authorized targets; the trust framework constrains downstream re-use. Some research collaborations explicitly limit each consumer's downstream use to a specific analytic publication; others permit re-use within a defined research-program scope. The architecture has to fit the institution's specific cross-organizational posture; the recipe's disclosure-policy mechanism is the institution-internal portion of the broader cross-org flow.

**Pilot evaluation infrastructure.** The pilot-overlap calibration data is a separately authorized data-sharing event with its own data-use agreement. The pilot data exists for a defined period (typically the duration of the calibration project) and is then either retained under a defined audit-archive retention floor or deleted per the agreement. The pilot data infrastructure is operationally separate from the production PPRL pipeline (separate AWS account, separate access controls, separate audit posture); the production pipeline references the calibration outputs (the threshold set, the per-feature weights) without re-accessing the underlying pilot data. Build the pilot infrastructure as a separately governed substrate; without it, the production pipeline's calibration depends on operational assumptions that the audit cannot verify.

**Idempotency and retry semantics.** The pipeline must handle duplicate-event delivery, partner-side retries, and Glue job re-runs without producing duplicate encoded records, duplicate match results, or scrambled audit logs. Use the (cycle_id, source_record_id) tuple as the idempotency key for encoding writes; use (cycle_id, encoded_record_a_id, encoded_record_b_id) for the matching writes; use cycle_id and disclosure_event_id for the disclosure events. Configure DLQs on every Lambda path and Glue job; Step Functions Catch states route terminal failures to the DLQ so stuck workflows are visible. Same chapter pattern as 5.3, 5.4, 5.5, 5.6, 5.7.

<!-- TODO (TechWriter): Expert review A5 (MEDIUM). Promote the idempotency keys into the General Architecture Pattern paragraph with the recipe-specific per-stage keys: standardize-and-prepare Lambda `(cycle_id, source_record_id)`; bulk-encode Glue `(cycle_id, source_record_id, parameterization_version)`; exchange-encoded-records Lambda `(cycle_id, encoded_record_id, transport_type)`; match-encoded-records Glue or Nitro Enclave `(cycle_id, encoded_record_a_id, encoded_record_b_id)`; disclose-and-route Lambda `(cycle_id, disclosure_event_id, target_consumer)`; invalidate-on-event Lambda `(invalidation_event_source, invalidation_event_id)`; salt-rotation-coordinator Step Functions `(rotation_id, participant_id)`. Specify the DLQ-per-stage topology and CloudWatch alarms on DLQ depth (typically > 0 records or > 15 minutes for stuck workflows). -->

**Cohort-stratified accuracy monitoring discipline.** The CloudWatch metrics with cohort-axis-hash dimensions, the QuickSight dashboard, the institutional review cadence, and the disparity-alarm thresholds are architecture-level commitments, not bolt-ons. Specify the operational thresholds, the per-axis aggregation, the disparity-metric definitions, and the institutional response protocol. Cohort-stratified linkage-rate disparity > 0.05 = MEDIUM alarm; cohort-stratified false-acceptance-rate disparity > 0.01 = HIGH (because false acceptances under PPRL produce wrong-record disclosures that the consumer cannot retract). Same chapter pattern as 5.1, 5.4, 5.5, 5.6, 5.7. The privacy team is an explicit reviewer for this recipe in addition to the standard analytics-governance committee, because cohort-stratified disparities in PPRL are also re-identification-risk indicators (cohorts with anomalously low linkage rates may be over-encoded with defensive noise; cohorts with anomalously high linkage rates may be under-encoded relative to the parameterization's defensive design).

<!-- TODO (TechWriter): Expert review A1 (HIGH). Promote the cohort-stratified accuracy thresholds and metric definitions into the General Architecture Pattern. Specify (a) the recipe-specific cohort axis enumeration (inherited from 5.7 plus PPRL-specific extensions: name-tradition cohort hash, transgender-or-gender-diverse cohort hash populated only from patient-consented self-identification, age-decade cohort hash, name-change-frequency cohort hash, patient-consent-for-fairness-monitoring cohort hash, cross-jurisdictional-overlay cohort hash); (b) the disparity-calculation method (absolute difference between highest and lowest cohort, computed per-metric per-cycle); (c) the per-metric emission cadence (linkage rate weekly, false-acceptance rate weekly, review-queue aging weekly, sampled error rate monthly); (d) the privacy-team routing with explicit re-identification-risk-evaluation authority (privacy team receives per-cohort re-identification-risk-indicator metrics; analytics-governance committee receives per-cohort accuracy metrics; equity-monitoring committee receives per-cohort fairness metrics; cross-jurisdictional governance committee receives jurisdictional-overlay-affected metrics); (e) the dual-interpretation translation (cohort disparities in PPRL are simultaneously fairness signals and re-identification-risk signals); and (f) the remediation pathway (alert routing, investigation, post-mortem retention with 5-business-day SLA, quarterly review by PPRL steering committee with privacy-team co-chair). Reference Recipe 5.1 / 5.4 / 5.5 / 5.6 / 5.7 Finding A1/A2 as the chapter-wide pattern. -->

<!-- TODO (TechWriter): Expert review S4 (LOW). Specify in the CloudWatch paragraph that cohort dimensions on metrics use cohort-axis-hash labels rather than underlying axis values; the hash-to-axis-value mapping lives only at each participant under their own access controls; the matcher and the metrics dashboard stratify by hash without learning the underlying axis values. The privacy team has authority to require re-derivation when the hash-to-axis-value mapping is determined to be re-derivable from the metric distribution. -->

**Compliance and operational ownership.** PPRL sits at the intersection of analytics, research, compliance, privacy, security, and IT. Establish clear operational ownership: who tunes the thresholds, who reviews the cohort-disparity reports, who owns the parameterization-version updates, who handles the salt-rotation ceremonies, who responds to consent withdrawals, who negotiates trust-framework changes. The pipeline works only when the operational ownership is clear and funded across the participating organizations, not just within one of them.

---

## The Honest Take

Privacy-preserving record linkage is the recipe in this chapter where the technical complexity is moderate, the cryptographic complexity is non-trivial but tractable, and the human-and-organizational complexity is the load-bearing concern. The matching techniques are familiar (you have seen the same probabilistic-record-linkage core in every recipe of this chapter, with the encoded-data twist that this recipe layers on top). The orchestration is familiar (Lambdas, Glue jobs, Step Functions, EventBridge, the same pattern as the other identity-pipeline recipes). The cryptographic primitives (Bloom filters, salted hashes, secure-multi-party computation, homomorphic encryption) are well-established in the academic literature and have mature open-source implementations. The thing that makes this recipe hard is that the privacy guarantee is a multi-organization contract, not a technology, and the multi-organization contract is what most institutions are not built to negotiate or maintain at the cryptographic-primitive level.

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

## Variations and Extensions

**Trusted-third-party tokenization integration.** Rather than building the encoding-and-matching pipeline in-house, the institution integrates with a commercial tokenization vendor (Datavant, HealthVerity, IQVIA, others). The vendor receives the demographic feeds from each participating organization, applies its proprietary tokenization, and produces the linked output. The architectural extension is a vendor-integration adapter that handles the per-vendor authentication, the per-vendor data-format conventions, the per-vendor audit-and-compliance posture, and the per-vendor BAA-and-contract surface. The institution's threat model has to include the vendor as a trusted third party with full visibility into the demographic feeds; the trust assumption is the contractual relationship rather than the cryptographic primitive. <!-- TODO: confirm at time of build; the commercial-tokenizer landscape continues to evolve, and the per-vendor integration specifics are vendor-and-contract-specific. --> <!-- TODO (TechWriter): Expert review S6 (LOW). Specify the institutional review committee (privacy team, security team, compliance team) reviewing the vendor's cryptographic-implementation document, audit certifications, data-handling posture, and contractual constraints, producing a written threat-model determination as part of the trust-framework artifact. Specify quarterly currency monitoring of vendor audit certifications (SOC 2 Type II, HITRUST, ISO 27001, ISO 27018) with response-protocol review by the institutional review committee on lapsed certifications. Specify contractual-constraint-tagging on every linkage record derived from vendor-tokenized data, mirroring the per-payer data-use-tagging pattern from 5.6, with access-control enforced via Lake Formation row-level filters. -->

**TEE-based PPRL with Nitro Enclaves.** Rather than encoding the demographics into Bloom filters before exchange, the participating organizations deliver their demographics in plaintext to a Nitro Enclave that has been hardware-attested as running the agreed matcher implementation. The enclave runs a conventional probabilistic-record-linkage matcher on the plaintext demographics, produces the linkage results, and returns them to the disclosure step; the demographics are never visible outside the enclave's hardware-isolated memory. The architectural extension is the Nitro Enclave attestation flow (each participant verifies the enclave's measurement before contributing its demographic feed), the per-cycle enclave instantiation, and the per-cycle enclave teardown (the enclave is destroyed at the cycle's end with no persistent storage). The trust assumption is shifted from "the cryptographic primitives suffice" to "the hardware enforces the isolation and the attestation is sound."

<!-- TODO (TechWriter): Expert review A7 (MEDIUM). Promote the TEE-attestation-flow into the architecture pattern. Specify the per-participant attestation verification flow (attestation document retrieval, expected-measurement matching against the trust-framework-specified measurement, PCR-values verification, per-participant verification policy with explicit reject-on-mismatch semantics), the per-cycle enclave instantiation flow (Step Functions instantiation stage with the cycle's pinned measurement and PCR-values; per-participant attestation verification before any encoded data is uploaded; cycle-completion teardown), the Nitro Enclave-to-KMS integration (KMS key policies that name the specific enclave measurement; the enclave attestation document is presented to KMS to authorize the salt-key-decryption; audit logging on every salt-key-decryption with the enclave attestation context), and the fallback-to-non-TEE-protocol pathway (cycle aborted on attestation failure, alert routing to the trust-framework-governance committee, response-protocol with explicit re-cycle-after-investigation authority). -->

**Patient-mediated PPRL through the Patient Access API.** A patient who has connected her records to a personal-health-record app authenticated under her own credentials authorizes a PPRL-mediated retrieval that the app coordinates on her behalf. The app, acting as the patient's agent, retrieves encoded records from each participating organization's API endpoint and orchestrates the matching at the patient's chosen linkage-execution endpoint (which may be the app itself, a designated research consortium, or a patient-controlled tokenization broker). The architectural extension is a patient-mediated trigger source that the per-participant encoding Lambda accepts, with explicit patient authentication and per-patient authorization-to-source-record-id binding. The pattern is uncommon as of writing but is becoming architecturally viable as the Patient Access API ecosystem matures.

<!-- TODO (TechWriter): Expert review A8 (MEDIUM). Promote the patient-mediated PPRL trigger source into the architecture pattern. Specify the patient-authentication path through the participating organizations' API endpoints (Cognito federation with the patient-portal IdP at each participant, per-participant authentication-to-source-record-id binding through Lambda authorizers, abuse-prevention rate-limiting at the API Gateway layer), the per-patient authorization-to-source-record-id binding at each participant (Lambda authorizer consults the participant's local authorization store; rejection on binding-failure), the patient-as-linkage-execution-endpoint authority (per-patient choice of execution endpoint with the participating organizations' trust-framework-determined-acceptable-endpoint allow-list; per-endpoint-type authentication and audit posture; rejection semantics when the patient's choice does not satisfy the trust framework), and the audit-attribution discipline (patient-mediated cycles audit-logged with explicit "patient-mediated" attribution; per-patient audit summary delivery to the patient's chosen channel). Pair with N3 (LOW) on API Gateway resource policy and WAF for the patient-portal authentication path. -->

**Differential-privacy-augmented disclosure.** The disclosure step applies calibrated differential-privacy noise to the linkage results before delivery, providing stronger privacy guarantees on the analytic outputs than the linkage alone provides. The architectural extension is a differential-privacy module in the disclose-and-route Lambda that computes the appropriate noise scale per the disclosure-policy's epsilon-and-delta parameters. The pattern is operationally complex (the privacy budget across cycles has to be tracked) but provides a stronger end-to-end privacy guarantee for use cases where the consumer's queries against the linked data are bounded and well-specified.

**Cross-cycle linkage composition with persistent encoded-record identifiers.** Rather than producing a fresh per-cycle encoded-record identifier, each participating organization maintains a persistent encoded-record identifier per source record (under a separate per-participant-only mapping that the linkage-execution endpoint does not see). The persistent identifier lets the linkage-execution endpoint compose linkages across cycles for analytic use cases that require multi-cycle continuity. The architectural extension is the per-participant persistent-identifier store with explicit access controls and explicit re-encoding-on-rotation rules; the linkage-execution endpoint sees the persistent identifier in the encoded payload but cannot resolve it back to the source record without the participant's authorization.

**Federated SMPC across more than two parties.** For research collaborations with more than two participants, the SMPC protocols generalize to n-party computation with appropriate protocol primitives (Shamir secret-sharing, replicated secret-sharing, additive secret-sharing). The architectural extension is the n-party orchestration layer that coordinates the multi-round protocol exchanges across all participants. Operational complexity scales super-linearly with the participant count; production deployments at more than four or five parties are uncommon as of writing.

**Linkage-result-disclosure-policy templates per use case.** The disclosure-policy mechanism supports multiple disclosure forms (per-record-match-flags, intersection-count, k-anonymous-aggregate, differentially-private-aggregate, encrypted-match-indicator). Per-use-case policy templates pre-configure the disclosure form and the per-form parameters (k-anonymity threshold, differential-privacy epsilon, suppression policy, encryption recipient). The architectural extension is a policy-template library that the cycle orchestrator consults at the disclosure step; the institution's privacy team owns the templates and reviews them on a periodic cadence.

**Cohort-stratified-accuracy monitoring with privacy-preserving cohort-axis derivation.** The cohort-stratified-accuracy reporting requires per-record cohort-axis hashes that the participants contribute in the encoding step. The architectural extension is a privacy-preserving cohort-axis derivation that lets the participants compute the cohort-axis values locally (under their own demographic visibility) and contribute the hashed values without exposing the underlying axis values to the linkage-execution endpoint. Same chapter pattern as 5.1, 5.4, 5.5, 5.6, 5.7 cohort-stratified accuracy monitoring with the recipe-specific hashing-on-the-axis-value-not-the-record discipline.

**Active-learning-driven configuration tuning.** As the linkage-review queue resolves cases, the labels feed a periodic re-training of the matcher's thresholds and the per-feature weights. Active learning concentrates the review effort on the cases that most improve the downstream accuracy and the cohort fairness; over time, the review queue depth decreases as the matcher absorbs the labeled cases. The active-learning pattern is constrained by the encoded-data limitation (the labels are on the encoded records, not on the demographics; the calibration has to be careful not to leak demographic information through the labeling decisions). <!-- TODO (TechWriter): Expert review A11 (LOW). Specify that the active-learning calibration loop operates only on the encoded data and the reviewer-decided labels; the calibration job runs in a separate access-controlled context that does not have access to the demographic features. The threshold-and-weights candidate produced by the active-learning loop is reviewed by the privacy team for re-identification-risk evaluation (the cohort-stratified-disparity translation in Finding A1 applies; the privacy team checks whether the candidate's cohort-impact suggests the labels themselves are leaking demographic information through systematic reviewer biases) before promotion to the production parameterization. -->

**Re-identification-risk-aware adaptive parameterization.** Rather than static parameterization that the privacy team reviews on a periodic cadence, the encoding step monitors the encoded-data distribution for anomaly indicators (unusual frequency patterns, unusual bit-density distributions, unusual cohort-axis distributions) and adaptively adjusts the defensive measures in response. The architectural extension is a parameterization-feedback loop that consumes the in-production encoded-data statistics and produces parameterization adjustments that the trust-framework governance approves before promotion.

**Cross-jurisdictional overlay automation.** The consent-and-purpose-of-use governance layer applies per-jurisdiction overlay rules at encoding time. The architectural extension is an overlay-rules engine that consumes the patient's residence jurisdiction, the use case's authorization scope, the record-type sensitivity classification, and the participating organizations' jurisdictional postures, and produces a per-record consent-posture decision. The overlay rules are versioned and reviewed on a regulatory-monitoring cadence (post-legislative-session is the typical trigger). The pattern is operationally important for institutions operating across multiple states with diverging post-Dobbs, post-Bostock, and gender-affirming-care state-law overlays. <!-- TODO (TechWriter): Expert review A9 (MEDIUM). See also the BAA-and-trust-framework prerequisite-row TODO for the same finding. Promote the overlay-rules engine architecture (versioned rule store in DynamoDB or a dedicated configuration store; rule-evaluation Lambda invoked at encoding time; output consent-posture metadata stored on the encoded-record envelope), the regulatory-monitoring function (shared between privacy and compliance teams; legislative-session feeds with explicit per-state subscription, regulatory-bulletin subscriptions, court-decision tracking; trigger thresholds with relevance-evaluation criteria), the per-record consent-posture decision audit trail (every overlay-rule application audit-logged with inputs, rule version active, output decision), and the trust-framework-update pathway (regulatory-change-detection through the regulatory-monitoring function; trust-framework-update through the trust-framework-governance committee; coordinated re-encoding through the salt-rotation-coordinator pattern; downstream-consumer notification through the EventBridge fan-out) into the architecture pattern. -->

**Audit-summary delivery to the patient.** As part of the patient-experience layer, the patient may opt to receive periodic summaries of how her record has been included in linkages, with the cycle, the participants, the use case, the disclosure form, and the disclosure target identified. The architectural extension is a patient-portal summary-delivery service that aggregates the per-cycle inclusion records (filtered to the patient's own data) and delivers them on the patient's chosen cadence. The pattern is uncommon but is becoming an expected disclosure for patients in jurisdictions with strong data-rights regulations. <!-- TODO (TechWriter): Expert review A13 (LOW). Specify the audit-summary-delivery service architecture: API Gateway with WAF, the institution's patient-portal authentication, the per-patient authorization-to-source-record-id binding enforced at the Lambda authorizer (one patient cannot retrieve audit summaries for unrelated patients), per-patient rate limits below the operational-session capacity, the audit-data filtering enforced at the data layer (the query is bound to the requesting patient's source_record_id at the data-store level rather than at the application layer), and audit logging on every audit-summary read with the patient-attestation that the summary was delivered. -->

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

## Additional Resources

**AWS Documentation:**
- [AWS Nitro Enclaves User Guide](https://docs.aws.amazon.com/enclaves/latest/user/nitro-enclave.html)
- [AWS Key Management Service Developer Guide](https://docs.aws.amazon.com/kms/latest/developerguide/overview.html)
- [AWS CloudHSM User Guide](https://docs.aws.amazon.com/cloudhsm/latest/userguide/introduction.html)
- [Amazon S3 User Guide](https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html)
- [Amazon S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html)
- [Amazon DynamoDB Developer Guide](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html)
- [AWS Glue Developer Guide](https://docs.aws.amazon.com/glue/latest/dg/what-is-glue.html)
- [AWS Lambda Developer Guide](https://docs.aws.amazon.com/lambda/latest/dg/welcome.html)
- [AWS Step Functions Developer Guide](https://docs.aws.amazon.com/step-functions/latest/dg/welcome.html)
- [Amazon EventBridge User Guide](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html)
- [AWS PrivateLink Documentation](https://docs.aws.amazon.com/vpc/latest/privatelink/what-is-privatelink.html)
- [Amazon SageMaker Developer Guide](https://docs.aws.amazon.com/sagemaker/latest/dg/whatis.html)
- [Amazon Athena User Guide](https://docs.aws.amazon.com/athena/latest/ug/what-is.html)
- [AWS Lake Formation Developer Guide](https://docs.aws.amazon.com/lake-formation/latest/dg/what-is-lake-formation.html)
- [Amazon QuickSight User Guide](https://docs.aws.amazon.com/quicksight/latest/user/welcome.html)
- [AWS HIPAA Eligible Services](https://aws.amazon.com/compliance/hipaa-eligible-services-reference/)

**AWS Sample Repos:**
- [`aws-samples/aws-nitro-enclaves-samples`](https://github.com/aws-samples/aws-nitro-enclaves-samples): Nitro Enclaves examples that demonstrate the attestation-and-confidential-computing pattern applicable to TEE-based PPRL <!-- TODO: confirm the current name and location of Nitro Enclaves samples repo at time of build. -->
- [`aws-samples/serverless-patterns`](https://github.com/aws-samples/serverless-patterns): API Gateway + Lambda + DynamoDB patterns applicable to the per-event encoding and disclosure Lambdas
- [`aws-samples/aws-glue-samples`](https://github.com/aws-samples/aws-glue-samples): Glue ETL patterns applicable to the bulk-encoding and the matcher-execution jobs

**AWS Solutions and Blogs:**
- [AWS Solutions Library](https://aws.amazon.com/solutions/) (filter Healthcare and Life Sciences): browse for healthcare-data-collaboration and confidential-computing reference architectures
- [AWS for Industries: Healthcare and Life Sciences Blog](https://aws.amazon.com/blogs/industries/category/industries/healthcare/): search "data collaboration," "confidential computing," "Nitro Enclaves," "tokenization," "privacy preserving" for relevant deep-dives
- [AWS Security Blog](https://aws.amazon.com/blogs/security/): search "confidential computing," "Nitro Enclaves," "homomorphic encryption" for relevant patterns
<!-- TODO: replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs. -->

**External References (Cryptographic and Methodological):**
- [`anonlink`](https://github.com/data61/anonlink): an open-source CLK-based PPRL toolkit from CSIRO's Data61, with reference implementations of encoding and matching <!-- TODO: confirm current URL at time of build. -->
- [`clkhash`](https://github.com/data61/clkhash): the companion encoding library for `anonlink` <!-- TODO: confirm current URL at time of build. -->
- [OpenMined PSI](https://github.com/OpenMined/PSI): an open-source private-set-intersection toolkit
- [Microsoft SEAL](https://github.com/microsoft/SEAL): an open-source homomorphic-encryption library
- [MP-SPDZ](https://github.com/data61/MP-SPDZ): an open-source secure-multi-party-computation toolkit <!-- TODO: confirm current URL at time of build. -->
- [Confidential Computing Consortium](https://confidentialcomputing.io/): an industry consortium covering TEE-based confidential-computing patterns

**External References (Standards and Frameworks):**
- [HIPAA De-identification Standard (Safe Harbor and Expert Determination)](https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/): the regulatory framework for de-identified data that PPRL deployments operate under
- [NIST SP 800-188 (De-Identification of Personal Information)](https://csrc.nist.gov/publications/detail/sp/800-188/draft): NIST guidance on de-identification including PPRL-relevant techniques <!-- TODO: confirm current version and URL at time of build. -->
- [21st Century Cures Act Information Blocking Rule](https://www.healthit.gov/topic/information-blocking): the regulatory framework that interacts with PPRL-mediated research disclosures
- [HIPAA Privacy Rule](https://www.hhs.gov/hipaa/for-professionals/privacy/index.html): the foundational regulatory framework
- [42 CFR Part 2](https://www.ecfr.gov/current/title-42/chapter-I/subchapter-A/part-2): the substance-use-treatment record disclosure framework that imposes specific constraints on PPRL inclusion <!-- TODO: confirm current URL at time of build. -->

**External References (Academic Literature):**
- [Schnell, R., Bachteler, T., and Reiher, J. (2009). "Privacy-preserving record linkage using Bloom filters." BMC Medical Informatics and Decision Making.](https://bmcmedinformdecismak.biomedcentral.com/articles/10.1186/1472-6947-9-41) The seminal paper introducing CLK-based PPRL <!-- TODO: confirm current URL at time of build. -->
- [Vatsalan, D., Christen, P., and Verykios, V. S. (2013). "A taxonomy of privacy-preserving record linkage techniques." Information Systems.](https://doi.org/10.1016/j.is.2012.11.005) A reference taxonomy of the PPRL technique families <!-- TODO: confirm current URL at time of build. -->
- [Christen, P., Schnell, R., Vatsalan, D., and Ranbaduge, T. (2017). "Efficient Cryptanalysis of Bloom Filters for Privacy-Preserving Record Linkage." Pacific-Asia Conference on Knowledge Discovery and Data Mining.](https://link.springer.com/chapter/10.1007/978-3-319-57454-7_50) The reference paper on the re-identification attacks against CLK encoding <!-- TODO: confirm current URL at time of build. -->

**External References (Industry):**
- [ONC Data Use Agreements and Patient Matching](https://www.healthit.gov/topic/scientific-initiatives/patient-matching): ONC's published guidance on patient matching including privacy-preserving techniques <!-- TODO: confirm current URL at time of build. -->
- [Sequoia Project Patient Matching Framework](https://sequoiaproject.org/): industry-developed framework for patient-matching including PPRL recommendations <!-- TODO: confirm current URL at time of build. -->
- [PCORnet Common Data Model](https://pcornet.org/): a multi-institution research network that has explored PPRL approaches for cross-network linkage <!-- TODO: confirm current URL at time of build. -->

---

## Estimated Implementation Time

| Tier | Scope | Time |
|------|-------|------|
| Basic | Single-protocol PPRL with two participants, CLK encoding, S3-mediated exchange, Glue-based matcher, fixed parameterization, manual review queue, basic audit-archive bucket, single-disclosure-form support (per-record-match-flags only) | 6-9 months |
| Production-ready | Multi-participant PPRL with full trust-framework artifact, HSM-based salt custody with rotation ceremony, versioned parameterization with periodic re-identification-risk review, multiple disclosure forms (per-record-match-flags, intersection-count, k-anonymous-aggregate, differentially-private-aggregate), cohort-stratified-accuracy monitoring with privacy-preserving cohort-axis derivation, integration with cross-recipe events from 5.1 / 5.3 / 5.5 / 5.6 / 5.7, three-queue review tooling, threshold-calibration governance with pilot-data infrastructure, complete CloudTrail and audit-retention posture, consent-capture and consent-withdrawal pathways with patient-facing communication, regulatory-monitoring function with trust-framework-update triggers | 12-24 months |
| With variations | Add commercial tokenization vendor integration, TEE-based PPRL with Nitro Enclaves, patient-mediated PPRL through Patient Access API, federated SMPC across more than two parties, differential-privacy-augmented disclosure with privacy-budget tracking, cross-cycle linkage composition with persistent encoded-record identifiers, re-identification-risk-aware adaptive parameterization, cross-jurisdictional overlay automation, audit-summary delivery to patient | 12-18 months beyond production-ready |

---

## Tags

`entity-resolution` · `record-linkage` · `privacy-preserving` · `pprl` · `bloom-filter-encoding` · `cryptographic-long-term-key` · `clk` · `tokenization` · `secure-multi-party-computation` · `smpc` · `private-set-intersection` · `psi` · `homomorphic-encryption` · `trusted-execution-environment` · `tee` · `nitro-enclaves` · `confidential-computing` · `cross-organizational-matching` · `salt-rotation` · `parameterization-versioning` · `re-identification-risk` · `differential-privacy` · `cohort-stratified-accuracy` · `consent-management` · `multi-party-trust-framework` · `dynamodb` · `lambda` · `glue` · `step-functions` · `eventbridge` · `sagemaker` · `kms` · `cloudhsm` · `lake-formation` · `event-driven` · `complex` · `production` · `hipaa` · `42-cfr-part-2` · `information-blocking` · `cures-act` · `equity-monitoring` · `research-collaboration` · `public-health-surveillance` · `cross-payer-outcomes` · `audit-archive`

---

*← [Recipe 5.7: Longitudinal Patient Matching Across Name Changes](chapter05.07-longitudinal-patient-matching-name-changes) · Chapter 5 · [Next: Recipe 5.9 - National-Scale Patient Matching (TEFCA) →](chapter05.09-national-scale-patient-matching)*
