# Open TODOs: Recipe 5.7: Longitudinal Patient Matching Across Name Changes ⭐⭐⭐⭐

> Remaining items after resolution pass 2026-06-21.

## main — `chapter05.07-longitudinal-patient-matching-name-changes.md`

- [NEEDS HUMAN] **L19** — Confirm at time of build; lifetime name-change rates from marriage/divorce/legal-change vary widely by population and by region, with U.S. women historically experiencing markedly higher rates than men, but specific figures are study-dependent. Reason: population-specific statistics require source verification.
- [NEEDS HUMAN] **L71** — Confirm at time of build; the FHIR US Core implementation guide and various state-level requirements continue to clarify the data-model recommendations for sex-assigned-at-birth, current sex / gender identity, and gender-affirming care administrative needs. Reason: evolving standard; citation needs verification at publish time.
- [NEEDS HUMAN] **L73** — TODO (TechWriter): Expert review A9 (MEDIUM). Architect the four-separate-fields data model from FHIR US Core (sex assigned at birth, current sex / gender identity, pronouns, legal sex on identity documents) as time-varying attributes on the identity record with their own effective-span histories. Reason: requires deep FHIR US Core expertise and the standard continues to evolve; a subtly wrong specification here could mislead implementers on a sensitive topic.
- [NEEDS HUMAN] **L99** — Confirm at time of build; the FHIR US Core implementation guide and the ONC USCDI versioning continue to clarify the requirements; major EHR vendors have been updating their data models on a rolling basis. Reason: evolving standard.
- [NEEDS HUMAN] **L101** — Confirm at time of build; the FHIR R4 Patient resource is normative and the HumanName datatype has been stable for several versions. Reason: confirm version stability at publish time.
- [NEEDS HUMAN] **L103** — Confirm at time of build; the state-level landscape varies; most states do not provide direct healthcare-organization access to vital-records-name-change data, but some have piloted programs. Reason: state-level landscape changes; needs current verification.
- [NEEDS HUMAN] **L105** — Confirm at time of build; the information-blocking exceptions and their applicability to name-change scenarios continue to be clarified through enforcement actions and FAQ guidance. Reason: regulatory evolution.
- [NEEDS HUMAN] **L107** — Confirm at time of build; the Pew, ONC, RAND, and Sequoia Project literature on patient-matching equity continues to expand. Reason: literature reference needs current verification.
- [NEEDS HUMAN] **L109** — Confirm at time of build; the Patient Access API ecosystem has expanded substantially since the CMS Interoperability Final Rule went into effect, and patient-mediated linkage is increasingly viable. Reason: ecosystem evolution.

## architecture — `chapter05.07-architecture.md`

- [NEEDS HUMAN] **L29** — Confirm at time of build; HealthLake's support for the FHIR Patient resource and the HumanName datatype's `use` and `period` fields continue to be refined. Reason: AWS service capability evolves; needs verification at publish time.
- [NEEDS HUMAN] **L127** — Confirm at time of build; commercial name-data providers (Melissa Data, RecordLinkage / Splink communities, OHDSI vocabulary) and open-source nickname dictionaries (Anc.NicknameAndDiminutiveNamesLookup) all play roles in the reference-data sourcing. Reason: vendor and open-source landscape evolves.
- [NEEDS HUMAN] **L128** — TODO (TechWriter): Expert review S1 (HIGH). Specify identity-boundary requirements at the architectural level for every consequential path. Reason: this finding requests 8+ specific IAM/mTLS/Cognito configurations with scoped resource ARNs; getting any of these wrong (particularly the patient-portal-app authentication path and the sensitivity-class-update dual-control path) could mislead implementers on security-critical architecture. Requires architect review of the specific ARN patterns, the per-source allow-list enforcement mechanism, and the dual-control signature verification pattern before committing.
- [NEEDS HUMAN] **L134** — Confirm at time of build; Synthea's name-change modeling capabilities and the available extensions for name-tradition diversity continue to develop. Reason: open-source project evolution.
- [NEEDS HUMAN] **L135** — Replace with verified, current pricing once the implementing team validates against the AWS Pricing Calculator. Reason: pricing changes; must be verified at publish time.
- [NEEDS HUMAN] **L165** — Confirm current URL at time of build; community-maintained nickname dictionaries change repositories occasionally. Reason: URL verification needed.
- [NEEDS HUMAN] **L997** — Replace illustrative figures with measured results from the deployment. The above are typical ranges from Pew, Sequoia, and ONC patient-matching benchmarks; specific figures vary by population, by source mix, and by data-source maturity. Reason: deployment-specific metrics.
- [NEEDS HUMAN] **L1052** — Confirm at time of build; FHIR R4 supports the period and use fields on HumanName, and several US Core implementation guide updates have refined the recommended use-codes for prior-name representation. Reason: evolving standard.
- [NEEDS HUMAN] **L1056** — Confirm at time of build; the state-level integration landscape is institution-specific. Reason: institution-specific; cannot verify generically.
- [NEEDS HUMAN] **L1099** — Confirm the current name and location of HealthLake samples repo at time of build; the aws-samples organization periodically reorganizes. Reason: URL verification needed.
- [NEEDS HUMAN] **L1104** — Replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs. Reason: cannot fabricate URLs; requires manual verification.
- [NEEDS HUMAN] **L1110** — Confirm current URL at time of build. Reason: URL verification needed.
- [NEEDS HUMAN] **L1111** — Confirm current version and URL at time of build. Reason: URL verification needed.
- [NEEDS HUMAN] **L1118** — Confirm current URL at time of build. Reason: URL verification needed.
- [NEEDS HUMAN] **L1123** — Confirm current URL at time of build. Reason: URL verification needed.
- [NEEDS HUMAN] **L1124** — Confirm current URL at time of build. Reason: URL verification needed.
- [NEEDS HUMAN] **L1125** — Confirm current URL at time of build. Reason: URL verification needed.
- [NEEDS HUMAN] **L1126** — Confirm current URL at time of build. Reason: URL verification needed.
- [NEEDS HUMAN] **L1129** — Confirm current URL at time of build. Reason: URL verification needed.
- [NEEDS HUMAN] **L1130** — Confirm current URL at time of build. Reason: URL verification needed.
- [NEEDS HUMAN] **L1131** — Confirm current URL at time of build. Reason: URL verification needed.
