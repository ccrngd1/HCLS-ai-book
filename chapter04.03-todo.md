# Open TODOs: Recipe 4.3: Provider Directory Search Optimization

## main - `chapter04.03-provider-directory-search-optimization.md`

- [NEEDS HUMAN] **L15** - Verify the most current No Surprises Act provider directory provisions and CMS rules at the time of publication; this regulatory area has continued to evolve. (Requires legal/compliance review at publication time.)

## architecture - `chapter04.03-architecture.md`

- [NEEDS HUMAN] **L11** - Confirm current OpenSearch Service HIPAA eligibility entry on the AWS HIPAA Eligible Services Reference; the service has been on the list, but verify before publishing. (Requires checking AWS compliance page at publication time.)
- [NEEDS HUMAN] **L17** - Confirm Bedrock service terms and per-model data-handling guarantees at the time of build; the eligible-model list and BAA coverage have been evolving. (Requires checking AWS compliance page at publication time.)
- [NEEDS HUMAN] **L38** - Confirm Amazon Location Service HIPAA eligibility status at the time of build; eligibility has been added but verify the current entry on the HIPAA Eligible Services Reference. (Requires checking AWS compliance page at publication time.)
- [NEEDS HUMAN] **L111** - Confirm exact IAM action names for OpenSearch Service vector search; classic OpenSearch uses `es:*` actions, OpenSearch Serverless uses `aoss:*`. The recipe assumes provisioned OpenSearch Service throughout; adjust if you choose Serverless. (Requires testing against current API at build time.)
- [NEEDS HUMAN] **L112** - Confirm Bedrock + the specific embedding and LLM models you select are eligible at the time of build; verify Location Service eligibility entry; the eligible list has been evolving. (Requires checking AWS compliance page at publication time.)
- [NEEDS HUMAN] **L116** - Have a compliance reviewer confirm the specific provider directory accuracy and refresh-cadence requirements applicable to your plan's lines of business at the time of build. (Requires compliance/legal input per plan.)
- [NEEDS HUMAN] **L118** - Replace with verified, current pricing once the implementing team can validate against the AWS Pricing Calculator. (Requires pricing validation at build time.)
- [NEEDS HUMAN] **L146** - Confirm current names and locations of these aws-samples repositories. The list of search-related and Bedrock-related repos has been reorganizing. (Requires manual verification of GitHub URLs.)
- [NEEDS HUMAN] **L784** - The NDCG, CTR, and complaint-rate ranges are illustrative and have not been measured for this specific pipeline. Replace with measured results from your deployment, or with citations to published provider-directory ranking deployments when available. (Requires real deployment data or published references.)
- [NEEDS HUMAN] **L870** - Confirm the current names and locations of the aws-samples repositories above; aws-samples and aws-solutions-library-samples have been reorganizing, and several Bedrock-related repos have moved or merged. (Requires manual verification of GitHub URLs.)
- [NEEDS HUMAN] **L877** - Replace generic "search the blog" pointers with two or three specific, verified blog post URLs once they are confirmed to exist. Avoid any made-up URLs. (Requires manual blog search and URL verification.)
- [NEEDS HUMAN] **L882** - Confirm this is the correct landing page for current MA provider directory requirements at the time of publication; CMS guidance moves frequently. (Requires checking CMS website at publication time.)
- [NEEDS HUMAN] **L885** - Confirm this is the most appropriate, up-to-date reference for counterfactual LTR; the field has continued to develop. (Requires literature review decision by author.)
