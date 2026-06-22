# Open TODOs: Recipe 4.2: Patient Education Content Matching ⭐

> Auto-extracted 2026-06-18 from inline source comments (15 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture: `chapter04.02-architecture.md`

- [NEEDS HUMAN] **L15**: Confirm current OpenSearch Service HIPAA eligibility entry on the AWS HIPAA Eligible Services Reference. Reason: external verification of a live compliance page required before publishing.
- [NEEDS HUMAN] **L17**: Confirm Bedrock service terms and per-model data-handling guarantees at the time of build. Reason: the eligible-model list and BAA coverage evolve; requires checking the actual BAA document and console at publish time.
- [NEEDS HUMAN] **L84**: Confirm Bedrock and the specific embedding and LLM models selected are eligible at the time of build. Reason: same as L17; per-model BAA coverage must be verified against the live HIPAA Eligible Services page.
- [NEEDS HUMAN] **L89**: Confirm current MedlinePlus content license and redistribution terms before recommending in print. Reason: requires checking the live MedlinePlus terms-of-use page; redistribution terms may have changed.
- [NEEDS HUMAN] **L90**: Confirm current Bedrock Titan embedding pricing per 1K input tokens and replace with verified pricing from the AWS Pricing Calculator. Reason: pricing is live data that changes; author must validate at publish time.
- [NEEDS HUMAN] **L115**: Confirm current names and locations of aws-samples repositories (amazon-bedrock-workshop, amazon-personalize-samples, amazon-sagemaker-examples). Reason: the aws-samples org has been reorganizing; URLs must be verified to still resolve before print.
- [NEEDS HUMAN] **L540**: The CTR and completion-rate ranges in the Expected Results table are illustrative and have not been measured for this specific pipeline. Reason: replace with measured results from a deployment or with citations to published patient-education recommender studies; cannot fabricate numbers.
- [NEEDS HUMAN] **L615**: Confirm the current names and locations of the aws-samples repositories in the Additional Resources section. Reason: same as L115; URLs must be verified.
- [NEEDS HUMAN] **L622**: Replace generic "search the blog" pointers with two or three specific, verified AWS blog post URLs. Reason: cannot fabricate URLs; author must locate real, currently-live blog posts.
