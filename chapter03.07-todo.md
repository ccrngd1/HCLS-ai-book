# Open TODOs: Recipe 3.7: Patient Deterioration Early Warning ⭐

> Remaining items require external verification (citations, URLs, HIPAA eligibility checks) that cannot be confirmed without primary source access.

## main - `chapter03.07-patient-deterioration-early-warning.md`

- [NEEDS HUMAN] **L369** - Verify and cite specific operational performance characteristics for NEWS2 and MEWS in published validation studies. Reason: exact figures vary by population and require primary-source verification of specific papers.
- [NEEDS HUMAN] **L383** - Verify the current FDA guidance on Clinical Decision Support and SaMD as applies to deterioration prediction; the 2022 CDS guidance is the latest substantive update at time of writing. Reason: regulatory guidance may have been updated; cannot confirm currency without checking FDA.gov.
- [NEEDS HUMAN] **L421** - Cite specific peer-reviewed evaluations of EWS-style ML systems including well-known external validation studies (Wong et al. on Epic Deterioration Index, Romero-Brufau et al. on machine learning EWS performance, eCART score). Reason: exact citations with DOIs require library access to verify.
- [NEEDS HUMAN] **L427** - Confirm the specific Wong et al. 2021 JAMA Internal Medicine citation and the most recent published external validation results for EDI. Reason: exact DOI and page numbers require PubMed verification.
- [NEEDS HUMAN] **L527** - Cite the published literature on fairness in clinical deterioration models and Epic Deterioration Index subgroup performance critiques. Reason: exact citations require library verification.
- [NEEDS HUMAN] **L934** - Benchmark ranges are directional. Replace with measured numbers from local validation before clinical deployment. Key references (Wong et al., Romero-Brufau et al., Churpek et al., Smith et al.) need verified citations. Reason: same as L421.
- [NEEDS HUMAN] **L1066** - Add specific peer-reviewed citations with verified DOIs for: Wong et al. (2021) JAMA Internal Medicine; Romero-Brufau et al.; Churpek et al. (eCART); Smith et al. (meta-analyses); Escobar et al. (Kaiser AAM); Singer et al. (2016) Sepsis-3. Reason: DOIs and exact page numbers require PubMed/library access.

## architecture - `chapter03.07-architecture.md`

- [NEEDS HUMAN] **L17** - Verify current HIPAA eligibility status of Amazon Timestream. Reason: AWS HIPAA Eligible Services Reference changes quarterly; cannot confirm without checking the live page.
- [NEEDS HUMAN] **L35** - Confirm the set of HIPAA-eligible Bedrock foundation models as of the current year. Reason: model availability under the AWS BAA expands frequently; requires live reference check.
- [NEEDS HUMAN] **L181** - Verify and add a specific aws-samples or aws-solutions-library-samples repository demonstrating clinical deterioration prediction, sepsis prediction, or early warning systems on AWS. Reason: repository existence cannot be confirmed without searching GitHub.
- [NEEDS HUMAN] **L1041** - Same as L181; verify and add a specific aws-samples repository for clinical deterioration or patient monitoring on AWS.
- [NEEDS HUMAN] **L1047** - Verify and add two or three specific AWS blog posts on clinical deterioration prediction, sepsis prediction, or related early-warning topics on AWS; confirm URLs exist before inclusion. Reason: blog post URLs must be live-checked.
