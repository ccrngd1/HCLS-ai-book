# Open TODOs: Recipe 4.5: Medication Adherence Intervention Targeting ⭐⭐

> Remaining items requiring human verification or external citation.

## main - `chapter04.05-medication-adherence-intervention-targeting.md`

- [NEEDS HUMAN] **L37** - Confirm the current CMS Star Ratings cut-point methodology and the exact list of Part D adherence measures at the time of publication; CMS has revised this regularly and the 2023 Tukey-outlier change moved the cut points materially. Reason: requires time-of-publication verification against CMS sources that change annually.
- [NEEDS HUMAN] **L60** - Confirm the current CMS PQA (Pharmacy Quality Alliance) measure specifications and class definitions for the three Part D adherence measures at the time of publication. Reason: PQA specifications update periodically and require verified access to current documents.

## architecture - `chapter04.05-architecture.md`

- [NEEDS HUMAN] **L11** - Confirm SageMaker Batch Transform's current HIPAA eligibility and the appropriate instance types for the model sizes implied here. Reason: AWS HIPAA eligible services list updates; requires time-of-build verification.
- [NEEDS HUMAN] **L33** - Confirm current Bedrock service terms and the eligible-model list at the time of build; the BAA-covered model list has been evolving. Reason: Bedrock model eligibility changes quarterly.
- [NEEDS HUMAN] **L39** - Confirm SES HIPAA eligibility and BAA scope at the time of build; verify Pinpoint SMS eligibility. Reason: requires time-of-build verification against AWS HIPAA reference page.
- [NEEDS HUMAN] **L140** - Confirm Bedrock + selected models are eligible at the time of build; verify Pinpoint and Connect HIPAA-eligible configurations; verify SageMaker Feature Store eligibility. Reason: service eligibility evolves; requires verification at implementation time.
- [NEEDS HUMAN] **L146** - Replace with verified, current pricing once the implementing team validates against the AWS Pricing Calculator. Reason: pricing changes; requires implementer validation.
- [NEEDS HUMAN] **L180** - Confirm the current names and locations of these aws-samples repos. Reason: aws-samples repos reorganize periodically; requires manual verification of URLs.
- [NEEDS HUMAN] **L1117** - The benchmarks above are illustrative ranges informed by published adherence-program literature; replace with measured results from your deployment, or with citations once verified. Reason: requires either deployment data or verified published citations.
- [NEEDS HUMAN] **L1137** - Confirm the current PQA measure specifications and the link to the CMS Star Ratings methodology at the time of build. Reason: URLs change; requires time-of-publication verification.
- [NEEDS HUMAN] **L1141** - Link to a published barrier-elicitation framework once verified; the field is converging on a few common taxonomies. Reason: requires citation verification.
- [NEEDS HUMAN] **L1224** - Confirm the current names and locations of the aws-samples repos above; aws-samples and aws-solutions-library-samples have been reorganizing. Reason: requires manual URL verification.
- [NEEDS HUMAN] **L1231** - Replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs. Reason: cannot fabricate URLs; requires manual blog search.
- [NEEDS HUMAN] **L1234** - Confirm the current PQA landing page and specification access path at the time of publication. Reason: URL verification required.
- [NEEDS HUMAN] **L1235** - Confirm the most current CMS landing page; the URL has moved repeatedly. Reason: URL verification required.
