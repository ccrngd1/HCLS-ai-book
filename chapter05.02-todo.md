# Open TODOs: Recipe 5.2: Provider NPI Matching ⭐

> Remaining items require human verification at time of build (current URLs, pricing, regulatory details) or a product decision only the author can make. Each is prefixed with `[NEEDS HUMAN]`.

## main - `chapter05.02-provider-npi-matching.md`

- [NEEDS HUMAN] Verify provider directory accuracy statistics; CMS Secret Shopper studies document inaccuracy rates in the 30-50% range but specific recent figures vary by year and study.
- [NEEDS HUMAN] Verify the current No Surprises Act provider-directory accuracy provisions and CMS sub-regulatory guidance at time of build; verification windows and remediation pathways may have been updated.
- [NEEDS HUMAN] Confirm HIPAA Administrative Simplification NPI mandate details (45 CFR 162.404) are still current at time of build.
- [NEEDS HUMAN] Confirm the NPI Final Rule (45 CFR 162.404) and CMS guidance still establish the lifelong-stable Type 1 design at time of build.
- [NEEDS HUMAN] Verify the precise NPPES public-data field set at time of build; the schema is documented in the NPPES Data Dissemination File specification and is updated periodically.
- [NEEDS HUMAN] Verify CMS Provider Directory Accuracy reports and OIG audits documenting address staleness in NPPES are still current references.
- [NEEDS HUMAN] Confirm the current NPPES Downloadable File schema and update cadence (monthly full file plus weekly incremental updates) at time of build.
- [NEEDS HUMAN] Confirm the current NPI Registry API endpoint, parameters, and rate limits at time of build (npiregistry.cms.hhs.gov).
- [NEEDS HUMAN] Verify current No Surprises Act provider-directory provisions and any CMS rule updates at time of build.
- [NEEDS HUMAN] Verify current vendor landscape at time of build; the market consolidates and new entrants emerge.
- [NEEDS HUMAN] Confirm FHIR US Core profiles for Practitioner and PractitionerRole are still referenced in TEFCA exchange and CMS interoperability rules.
- [NEEDS HUMAN] Confirm specifics of CMS Medicare Advantage Provider Directory rules, NCQA standards, and state Medicaid agency rules regarding distinct verification cadences.
- [NEEDS HUMAN] Confirm current penalty structures at time of build; the regulatory framework continues to evolve.

## architecture - `chapter05.02-architecture.md`

- [NEEDS HUMAN] Confirm whether the institution has an existing credentialing system (Symplr, Echo, MedTrainer, Modio, Verifiable, internal) to integrate with. The architecture supports either path.
- [NEEDS HUMAN] Confirm the current NPPES download URL pattern at time of build; the file is published at download.cms.gov / NPPES download pages.
- [NEEDS HUMAN] Verify staffing ratios; the figures (0.1-0.5 FTE per 10,000 providers) are rough estimates from credentialing-tool vendor literature and may vary by organization.
- [NEEDS HUMAN] Replace with verified, current pricing once the implementing team validates against the AWS Pricing Calculator.
- [NEEDS HUMAN] Confirm the maintained state of pyNPI at time of build; alternative wrappers exist and may be more current.
- [NEEDS HUMAN] Replace illustrative performance figures with measured results from the deployment. Vendor-published figures often emphasize easy cases.
- [NEEDS HUMAN] Confirm current network adequacy verification requirements by line of business at time of build; CMS, NCQA, and state-level rules are the relevant authorities.
- [NEEDS HUMAN] Confirm the OIG LEIE is published monthly at oig.hhs.gov with the full list and incremental update files.
- [NEEDS HUMAN] Confirm current sanction-list sources and update cadences at time of build.
- [NEEDS HUMAN] Confirm DMF access requirements at time of build; the limited-access DMF requires specific authorizations under federal law.
- [NEEDS HUMAN] Confirm the current names and locations of the aws-samples repos at time of build; search aws-samples and aws-solutions-library-samples for entity-resolution and reference-data examples.
- [NEEDS HUMAN] Replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs.
- [NEEDS HUMAN] Confirm the current NPPES download URL pattern at time of build; CMS occasionally restructures the data-dissemination pages.
- [NEEDS HUMAN] Confirm current URL for NUCC taxonomy code set at time of build.
- [NEEDS HUMAN] Confirm the most relevant CMS guidance pages at time of build.
- [NEEDS HUMAN] Confirm specific URL for CMS Secret Shopper studies and Provider Directory Review reports at time of build.
