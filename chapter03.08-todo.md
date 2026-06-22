# Open TODOs: Recipe 3.8: Readmission Risk Anomaly Detection ⭐

## main — `chapter03.08-readmission-risk-anomaly-detection.md`

- [NEEDS HUMAN] **L23** — Verify the current HRRP penalty cap and the specific conditions in scope; CMS updates the program annually. Requires checking the current FY HRRP fact sheet.
- [NEEDS HUMAN] **L35** — Verify the current CMS HRRP exclusion rules for planned readmissions and operational definitions. Requires reviewing the current QualityNet methodology document.
- [NEEDS HUMAN] **L41** — Verify the specific year and details of the CMS HRRP peer-grouping and dual-eligibility stratification methodology change. The text says 2019; confirm against CMS rulemaking records.
- [NEEDS HUMAN] **L79** — Verify typical clinical practice around extended-window tracking (60- and 90-day); this varies by organization and condition. Author decision on specificity level.
- [NEEDS HUMAN] **L97** — Verify the current state-level HIE coverage; CMS-funded TEFCA expansion has shifted the landscape since initial drafting.
- [NEEDS HUMAN] **L121** — Verify the current published state-of-the-art for LSTM-based post-discharge readmission prediction; the literature is evolving rapidly.
- [NEEDS HUMAN] **L141** — Verify CMS HRRP measure specifications; the methodology has evolved. Check QualityNet for the current ICD-10-based measure specs.
- [NEEDS HUMAN] **L336** — Verify the specific citations and effect sizes for Coleman CTI, Naylor TCM, Project RED, and key RPM trials. The claims are directionally correct but exact effect sizes need citation backing.

## architecture — `chapter03.08-architecture.md`

- [NEEDS HUMAN] **L17** — Verify the current HIPAA eligibility status of Amazon Timestream and confirm BAA coverage. Some deployments may use DynamoDB or S3 with Athena instead. Check the AWS HIPAA Eligible Services page.
- [NEEDS HUMAN] **L25** — Confirm the set of HIPAA-eligible Bedrock foundation models as of the current year. The eligible model list updates periodically.
- [NEEDS HUMAN] **L204** — Verify and add a specific aws-samples or aws-solutions-library-samples repository demonstrating remote patient monitoring, post-discharge anomaly detection, or care management automation on AWS. Adjacent examples exist; a direct match has not been confirmed.
- [NEEDS HUMAN] **L1069** — Verify the current state of TEFCA implementation, CommonWell-Carequality unification, and practical availability of near-real-time HIE feeds nationally.
- [NEEDS HUMAN] **L1113** — Cite specific LLM-driven patient communication studies and vendors when the literature stabilizes.
- [NEEDS HUMAN] **L1149** — Verify and add a specific aws-samples repository demonstrating remote patient monitoring, post-discharge anomaly detection, transitions of care, or care management automation on AWS.
- [NEEDS HUMAN] **L1155** — Verify and add specific AWS blog posts on remote patient monitoring, readmission reduction, or care management automation on AWS; confirm URLs exist before inclusion.
- [NEEDS HUMAN] **L1166** — Verify the LACE and HOSPITAL canonical citations and update if better URL anchors exist.
- [NEEDS HUMAN] **L1184** — Add specific peer-reviewed citations with DOIs for: LACE index (van Walraven C, et al.), HOSPITAL score (Donze J, et al.), Coleman CTI (Coleman EA, et al. 2006, Arch Intern Med), Naylor TCM (Naylor MD, et al.), Project RED (Jack BW, et al. 2009, Ann Intern Med), telemonitoring trials in heart failure (Inglis SC, et al. Cochrane), HRRP impact studies (Wadhera RK, et al.). Requires library verification of DOIs.
