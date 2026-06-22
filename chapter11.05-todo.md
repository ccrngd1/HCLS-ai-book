# Open TODOs: Recipe 11.5: Insurance Benefits Navigator

> Remaining items after expert-review and code-review findings resolution pass (2026-06-22).

## main - `chapter11.05-insurance-benefits-navigator.md`

- [NEEDS HUMAN] **L19** - Verify: major U.S. payers have published call-volume figures for member services in various contexts, but consolidated public statistics are not reliably aggregated. The prose uses hedged language ("thousands of seats") which is directionally correct but unverifiable as a precise claim.
- [NEEDS HUMAN] **L21** - Verify: ambulatory practice operations literature identifies eligibility verification, prior-auth checks, and patient-cost estimation as some of the largest non-clinical staff time investments. The prose uses hedged language ("large fractions of their day") rather than a specific statistic.
- [NEEDS HUMAN] **L185** - Verify: specific deflection rates and call-center cost-savings figures vary by deployment. The prose uses hedged language ("consistently report substantial deflection rates") without citing a specific study.
- [NEEDS HUMAN] **L189** - Verify: the commercial vendor landscape continues to evolve. The prose avoids naming specific vendors, which is appropriate, but a future edition may want vendor examples.

## architecture - `chapter11.05-architecture.md`

- [NEEDS HUMAN] **L217** - Replace cost-estimate figures with verified pricing once the implementing team validates against the AWS Pricing Calculator. The current ranges ($0.05-0.30 per conversation, $115,000-580,000/year total) are illustrative based on Bedrock pricing at time of writing and depend on the chosen model, conversation turn count, tool-call volume, FHIR-source choice, and channel mix.
- [NEEDS HUMAN] **L1232** - Replace expected-results table figures with measured results from an actual deployment. The ranges (50-70% resolution rate, 30-60% call-center deflection, $0.05-0.30 per conversation) are typical for healthcare conversational benefits-navigator deployments but vary substantially with intent mix, member demographics, plan complexity, and integration depth.
- [NEEDS HUMAN] **L1376** - Confirm current AWS sample repo names and locations at time of build; the AWS sample repo organization changes over time. The three repos cited (`aws-samples/amazon-bedrock-samples`, `aws-samples/aws-genai-llm-chatbot`, `aws-samples/aws-healthcare-lifescience-ai-ml-sample-notebooks`) exist as of 2024 but may be renamed or reorganized.
- [NEEDS HUMAN] **L1382** - Replace generic "search the blog" pointers in Additional Resources with specific verified blog post URLs once they are confirmed to exist and remain current.
