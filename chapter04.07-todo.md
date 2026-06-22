# Open TODOs: Recipe 4.7: Care Management Program Enrollment ⭐⭐⭐

> Remaining items require external verification or human decision.

## main — `chapter04.07-care-management-program-enrollment.md`

- [NEEDS HUMAN] **L161** — Confirm current CMS TCM CPT code definitions and documentation requirements at the time of build. Requires checking CMS.gov for current billing guidance.

## architecture — `chapter04.07-architecture.md`

- [NEEDS HUMAN] **L11** — Confirm SageMaker Batch Transform's current HIPAA eligibility and the appropriate instance types for the model sizes implied here. Requires checking the AWS HIPAA eligible services page.
- [NEEDS HUMAN] **L37** — Confirm current Bedrock service terms and the eligible-model list at the time of build. Service terms evolve; check the Bedrock console and BAA documentation.
- [NEEDS HUMAN] **L43** — Confirm SES HIPAA eligibility and BAA scope at the time of build; verify Pinpoint SMS eligibility. Requires checking the AWS HIPAA eligible services page.
- [NEEDS HUMAN] **L47** — Confirm AWS HealthLake's current pricing and HIPAA eligibility at the time of build. Requires checking the AWS pricing page.
- [NEEDS HUMAN] **L147** — Confirm Bedrock + selected models, Pinpoint, Connect, and HealthLake eligibility at the time of build. Requires checking the AWS HIPAA eligible services page.
- [NEEDS HUMAN] **L153** — Replace with verified, current pricing once the implementing team validates against the AWS Pricing Calculator.
- [NEEDS HUMAN] **L188** — Confirm the current names and locations of the aws-samples repos. The repos have been reorganizing; verify links are live before publication.
- [NEEDS HUMAN] **L1403** — The benchmarks above are illustrative ranges informed by published care management and HEDIS-program literature; replace with measured results from your deployment. Be wary of vendor-published numbers that report "X% reduction in admissions" without matched-control comparison and without confidence intervals.
- [NEEDS HUMAN] **L1503** — Cite published care-management caseload-and-burnout literature; the ratios vary by acuity but the patterns are consistent. Requires literature search.
- [NEEDS HUMAN] **L1523** — Cite published literature on predictive disenrollment-prevention; the patterns are documented in some plan publications but the evidence base is mixed. Requires literature search.
- [NEEDS HUMAN] **L1562** — Confirm the current names and locations of the aws-samples repos above; aws-samples and aws-solutions-library-samples have been reorganizing.
- [NEEDS HUMAN] **L1569** — Replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs.
- [NEEDS HUMAN] **L1576** — Confirm current CMS landing page; CMS reorganizes URLs frequently.
- [NEEDS HUMAN] **L1577** — Confirm the current published-document URL at the time of build.
- [NEEDS HUMAN] **L1580** — Confirm the current URL at the time of build; the alliance has rebranded multiple times.

## python-example — `chapter04.07-python-example.md`

- [NEEDS HUMAN] **L3752** — Confirm the typical NCQA care management accreditation review cadence and the CMS care-management billing-code update cadence at the time of build. Requires checking NCQA and CMS.gov.
- [NEEDS HUMAN] **L3754** — Cite the EconML and DoWhy current versions and the appropriate CATE estimator for each program family. Requires checking PyPI for current releases.
- [NEEDS HUMAN] **L3782** — Cross-reference the cross-recipe shared config object once it exists; mirror language from 4.4-4.6 reviews. Depends on chapter-level editorial coordination.
- [NEEDS HUMAN] **L3794** — Confirm current CMS CCM and PCM CPT code definitions and TCM CPT codes 99495/99496 documentation requirements at the time of build. Requires checking CMS.gov.
