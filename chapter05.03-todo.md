# Open TODOs: Recipe 5.3: Address Standardization and Household Linkage ⭐⭐

> Remaining items require human verification of external resources or product decisions.

## main - `chapter05.03-address-standardization-household-linkage.md`

- [NEEDS HUMAN] **L11** - Verify statistic: "10-30% of patient address records have at least one quality issue." ONC, AHIMA, and address-quality vendor literature support this range, but the specific citation should be confirmed at time of build.
- [NEEDS HUMAN] **L15** - Confirm typical undeliverable-mail rates for healthcare outreach campaigns; figures in industry literature vary by population.
- [NEEDS HUMAN] **L17** - Confirm that the area deprivation index (ADI) and similar census-tract-level indicators are current and widely used; methodologies update periodically.
- [NEEDS HUMAN] **L37** - Confirm Publication 28 and CASS certification specifics at time of build; USPS occasionally updates the standards and the certification cycle.
- [NEEDS HUMAN] **L49** - Confirm NCOA access requirements and update cadence at time of build; NCOA is a USPS-licensed product with access controls based on intended use.
- [NEEDS HUMAN] **L72** - Confirm UPU addressing standards and multi-country vendor coverage at time of build.
- [NEEDS HUMAN] **L105** - Confirm current vendor landscape and CASS certification status at time of build.
- [NEEDS HUMAN] **L106** - Confirm NCOA coverage window at time of build; USPS publishes the retention period for the NCOA file.
- [NEEDS HUMAN] **L107** - Confirm the current state of SDOH indices at time of build; census data and methodologies update periodically.
- [NEEDS HUMAN] **L108** - Confirm current state of privacy-preserving record linkage literature applicability to address-based linkage.
- [NEEDS HUMAN] **L109** - Confirm HIPAA Privacy Rule section 164.514 specifics (18 Safe Harbor identifiers, three-digit ZIP exception). The rule is stable but should be verified against the current CFR text.

## architecture - `chapter05.03-architecture.md`

- [NEEDS HUMAN] **L15** - Confirm AWS Location Service capabilities and CASS-certification status of providers within Location at time of build.
- [NEEDS HUMAN] **L17** - Confirm Lambda VPC and timeout configurations work for the chosen vendor's response time at time of build.
- [NEEDS HUMAN] **L139** - Confirm vendor BAA availability and tier pricing at time of build; changes periodically.
- [NEEDS HUMAN] **L141** - Confirm whether address-quality vendors offer AWS PrivateLink endpoints at time of build.
- [NEEDS HUMAN] **L145** - Replace cost estimates with measured figures once the implementing team validates against vendor quotes and the AWS Pricing Calculator.
- [NEEDS HUMAN] **L172** - Confirm pyusps maintenance status at time of build; small wrapper libraries come and go.
- [NEEDS HUMAN] **L175** - Link to specific vendor SDKs at time of build; vendor URLs change.
- [NEEDS HUMAN] **L798** - Replace illustrative performance figures with measured results from the deployment.
- [NEEDS HUMAN] **L861** - Confirm Informed Delivery integration patterns at time of build; the program is USPS-operated.
- [NEEDS HUMAN] **L899** - Confirm the current names and locations of the aws-samples repos at time of build.
- [NEEDS HUMAN] **L905** - Replace generic "search the blog" pointers with specific, verified blog post URLs once confirmed to exist.
- [NEEDS HUMAN] **L908** - Confirm current URL for USPS Publication 28 at time of build.
- [NEEDS HUMAN] **L909** - Confirm current URL for USPS CASS Certification Program at time of build.
- [NEEDS HUMAN] **L910** - Confirm current URL for USPS NCOAlink Service at time of build.
- [NEEDS HUMAN] **L913** - Confirm current URL for HUD USPS ZIP Code Crosswalk Files at time of build.
- [NEEDS HUMAN] **L921** - Confirm current vendor list and link to their official sites at time of build.

## main - `chapter05.03-address-standardization-household-linkage.md` (continued)

- [NEEDS HUMAN] **L302** - Confirm NCOA retention window at time of build; USPS publishes the specific window.
- [NEEDS HUMAN] **L308** - Confirm HIPAA Privacy Rule section 164.514 specifics (same as L109 above).
