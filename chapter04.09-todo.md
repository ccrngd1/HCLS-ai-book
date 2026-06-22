# Open TODOs: Recipe 4.9: Personalized Care Plan Generation ⭐⭐⭐⭐

> Remaining items require human verification of external references, pricing, or cross-recipe coordination.

## main - `chapter04.09-personalized-care-plan-generation.md`

- [NEEDS HUMAN] **L338** - Confirm current FDA Clinical Decision Support guidance and the 21st Century Cures Act exemption criteria at the time of build. Reason: regulatory landscape is evolving and fact-specific; cannot verify current status without legal review.

## architecture - `chapter04.09-architecture.md`

- [NEEDS HUMAN] **L15** - Confirm AWS HealthLake's current pricing, HIPAA eligibility, and FHIR specification version support at the time of build. Reason: service terms change; requires checking the AWS HIPAA eligible services page and HealthLake pricing page at build time.
- [NEEDS HUMAN] **L29** - Confirm current Bedrock service terms, the eligible-model list, and the data-handling guarantees at the time of build. Reason: model availability and terms evolve frequently.
- [NEEDS HUMAN] **L41** - Confirm Pinpoint HIPAA-eligible channel list at the time of build. Reason: eligible channels may expand over time.
- [NEEDS HUMAN] **L164** - Pair IAM actions with one or two scoped Resource ARN examples. Reason: same chapter-wide pattern flagged in 4.1 through 4.8; needs coordinated decision on example format across chapter.
- [NEEDS HUMAN] **L165** - Confirm Bedrock + selected models, HealthLake, Pinpoint channel eligibility, and any EHR-integration components at the time of build. Reason: HIPAA eligible services list changes.
- [NEEDS HUMAN] **L171** - Replace with verified, current pricing once the implementing team validates against the AWS Pricing Calculator. Reason: pricing is dynamic and region-specific.
- [NEEDS HUMAN] **L205** - Confirm the current names and locations of the aws-samples repos. Reason: AWS has been reorganizing sample repos; URLs may have changed.
- [NEEDS HUMAN] **L1282** - The benchmarks in Expected Results are illustrative; replace with measured results from your deployment. Reason: cannot fabricate real deployment metrics.
- [NEEDS HUMAN] **L1311** - Document the four-layer validator pattern in a shared specification used across 4.5 through 4.9. Reason: requires cross-recipe coordination; the patterns rhyme but are not identical (patient-facing reading-level enforcement in 4.9, recommendation-language strictness in 4.8). Author decision needed on whether this is a chapter-level appendix or per-recipe documentation with cross-references.
- [NEEDS HUMAN] **L1323** - Confirm current FDA Clinical Decision Support guidance, the Cures Act CDS exemption criteria, and applicable state-level care-management regulations at the time of build. Reason: regulatory confirmation requires legal review.
- [NEEDS HUMAN] **L1389** - Confirm the current names and locations of the aws-samples repos; they have been reorganizing. Reason: same as L205.
- [NEEDS HUMAN] **L1396** - Replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Reason: cannot fabricate URLs; need to verify actual published posts.
- [NEEDS HUMAN] **L1404** - Confirm reference at the time of build; the Cumulative Complexity Model original paper is from 2009 (May, Montori, Mair, BMJ) with subsequent literature extending the framework. Reason: reference URL verification needed.
- [NEEDS HUMAN] **L1405** - Confirm reference at the time of build; the STOPP/START criteria have been updated in subsequent versions. Reason: reference URL verification needed.
- [NEEDS HUMAN] **L1410** - Confirm the current FDA SaMD framework documents at the time of build. Reason: regulatory document URLs change.
- [NEEDS HUMAN] **L1411** - Confirm the current FDA CDS guidance and the 21st Century Cures Act exemption criteria at the time of build. Reason: same as L338 and L1323.
