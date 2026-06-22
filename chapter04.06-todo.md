# Open TODOs: Recipe 4.6: Care Gap Prioritization ⭐⭐

> Remaining items after findings-resolution pass (2026-06-21). Items prefixed with [NEEDS HUMAN] require external verification or a product decision.

## main — `chapter04.06-care-gap-prioritization.md`

- [NEEDS HUMAN] **L504** — Confirm a published reference for the audit cadence; quality-measure programs vary in their formal review processes. (Cannot verify a specific citation without access to the source literature.)

## architecture — `chapter04.06-architecture.md`

- [NEEDS HUMAN] **L24** — Confirm SageMaker Batch Transform's current HIPAA eligibility and the appropriate instance types for the model sizes implied here. (Requires checking AWS HIPAA eligible services list at time of build.)
- [NEEDS HUMAN] **L48** — Confirm current Bedrock service terms and the eligible-model list at the time of build; the BAA-covered model list has been evolving.
- [NEEDS HUMAN] **L54** — Confirm SES HIPAA eligibility and BAA scope at the time of build; verify Pinpoint SMS eligibility.
- [NEEDS HUMAN] **L58** — Confirm AWS HealthLake's current pricing and HIPAA eligibility at the time of build; consider whether HealthLake is the right fit relative to direct FHIR-to-S3 patterns for the implementing team.
- [NEEDS HUMAN] **L152** — Pair IAM actions with one or two scoped Resource ARN examples so a reader copying into an IAM policy doesn't default to `Resource: *`. Same chapter-wide pattern flagged in 4.1, 4.2, 4.3, 4.4, 4.5 reviews. (Product decision: consistent ARN examples across all chapter 4 recipes.)
- [NEEDS HUMAN] **L153** — Confirm Bedrock + selected models are eligible at the time of build; verify Pinpoint and Connect HIPAA-eligible configurations; verify HealthLake eligibility.
- [NEEDS HUMAN] **L159** — Replace with verified, current pricing once the implementing team validates against the AWS Pricing Calculator.
- [NEEDS HUMAN] **L194** — Confirm the current names and locations of these aws-samples repos.
- [NEEDS HUMAN] **L1166** — The benchmarks above are illustrative ranges informed by published care gap and HEDIS-program literature; replace with measured results from your deployment, or with citations once verified.
- [NEEDS HUMAN] **L1186** — Confirm the current NCQA HEDIS update cadence and the CMS Stars technical-notes release pattern at the time of build.
- [NEEDS HUMAN] **L1244** — Cite literature on outreach bundling effectiveness; the practice is widespread but published evidence is mixed. (Requires literature search.)
- [NEEDS HUMAN] **L1296** — Confirm the current names and locations of the aws-samples repos above; aws-samples and aws-solutions-library-samples have been reorganizing.
- [NEEDS HUMAN] **L1303** — Replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs.
- [NEEDS HUMAN] **L1306** — Confirm the current NCQA HEDIS landing page and access path at the time of publication.
- [NEEDS HUMAN] **L1307** — Confirm the most current CMS landing page; the URL has moved repeatedly.

## python-example — `chapter04.06-python-example.md`

- [NEEDS HUMAN] **L3019** — Confirm the current NCQA HEDIS update cadence and the CMS Stars technical-notes release pattern at the time of build.
