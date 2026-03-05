# Recipe Writing Guide

_How to write recipes for the Healthcare AI/ML Cookbook. Read this before writing any recipe._

---

## Recipe Structure (Main File)

Every recipe follows a two-part structure. The first half is vendor-agnostic. The second half is AWS-specific.

### Part 1: Vendor-Agnostic

**The Problem.** Make the reader feel why this sucks today. Real-world scenario, human impact, scale of the pain. Not clinical. Passionate. A VP of Operations should read this and nod along because they've lived it.

**The Technology.** Teach the underlying tech from first principles.
- What is it? How does it actually work?
- Why is it hard? What are the classic failure modes?
- Why is it good enough for this use case despite those?
- Where has the field moved in the last few years?
- **No vendor names in this section.** No S3, no Lambda, no Textract. Concepts only. A reader using GCP, Azure, or on-premises should learn something valuable here.

**General Architecture Pattern.** Describe the pipeline at a conceptual level. What are the logical stages? What does data flow look like? Still no vendor names. Any cloud, any language.

### Part 2: AWS-Specific

**Why These Services.** Introduce each AWS service and explain why it was chosen for that specific piece of the architecture. Connect each service back to the concept it implements from Part 1.

**Architecture Diagram.** Mermaid flowchart showing the AWS components and data flow.

**Prerequisites.** Table format:

| Requirement | Details |
|-------------|---------|
| AWS Services | List them |
| IAM Permissions | Specific actions needed |
| BAA | Required if PHI is involved (it usually is) |
| Encryption | S3 SSE-KMS, DynamoDB at rest, TLS in transit |
| VPC | Production recommendations |
| CloudTrail | Audit logging requirements |
| Sample Data | Where to get test data. Never use real PHI in dev. |
| Cost Estimate | Per-unit and monthly estimates |

**Ingredients.** Table of AWS services and their specific roles in this recipe.

**Code (Pseudocode Walkthrough).** Language-agnostic pseudocode with heavy inline comments. Each step gets:
- A business-level explanation of what it accomplishes and why it matters
- What goes wrong if you skip it (for the non-technical reader)
- A pseudocode block with comments accessible to someone who has never written code
- JSON and YAML are fine for data structures (field maps, configs)

After the walkthrough, include a callout linking to the Python companion:

> **Want the working code?** The pseudocode above is designed to be readable by anyone. If you're ready to see it implemented, the [Python Example](chapter{NN}.{RR}-python-example) provides a complete, heavily commented Python implementation of all steps, along with notes on the gap between this example and a production deployment.

**Expected Results.** Sample JSON output showing what the pipeline produces. Performance benchmarks table (latency, accuracy, confidence, cost, throughput). Where it struggles (honest list of failure modes).

**The Honest Take.** Where it breaks in practice. What surprised you. What you'd do differently. Self-deprecating expertise is the signature here.

**Variations and Extensions.** 2-3 practical extensions with enough detail to get started.

**Related Recipes.** Cross-references by recipe number with one-line descriptions of the connection.

**Additional Resources.** AWS docs, compliance guides, relevant external links. **Only real, verified URLs.** Never make up GitHub repos or doc links.

**Estimated Implementation Time.** Three tiers: Basic, Production-ready, With variations.

**Tags.** Searchable labels for the recipe.

**Navigation.** Footer links to previous recipe, chapter index, and next recipe.

---

## Python Companion File

Each recipe gets a separate Python companion file. This is where developers go when they want working code.

### Structure

1. **Opening callout:** This is a trivial, illustrative implementation. Not production-ready. A starting point, not a destination.

2. **Setup:** pip install instructions, credentials setup, IAM permissions needed.

3. **Config and constants:** Field maps, thresholds, lookup tables. These go first because they're really configuration, not logic. Readers should see the data structures before the functions that use them.

4. **One section per step:** Maps 1:1 to the pseudocode steps in the main recipe.
   - One-liner reminder of what this step does (reference the pseudocode)
   - Working Python (boto3 for AWS calls) with generous inline comments
   - Comments accessible to someone learning Python, not just experienced devs

5. **Full pipeline function:** Assembles all steps into a single callable function. Include print statements showing progress so readers can trace execution.

6. **Gap to production:** What you'd need to add for a real deployment. Cover: error handling, retries/backoff, input validation, structured logging, IAM least-privilege, VPC + VPC endpoints, KMS CMKs, testing, and any service-specific gotchas (like DynamoDB's Decimal requirement). Frame as "here's the distance between this example and something you'd deploy."

### Important
- The Python must actually work. Correct API calls, correct parameter names, correct response structures for current boto3.
- Fix known SDK gotchas in the example code rather than leaving them as traps (e.g., use Decimal for DynamoDB floats).
- If a gotcha is fixed in the code, still mention it in the "gap to production" section so readers understand why.

---

## File Naming

| Type | Pattern | Example |
|------|---------|---------|
| Main recipe | `chapter{NN}.{RR}-{name}.md` | `chapter01.01-insurance-card-scanning.md` |
| Python companion | `chapter{NN}.{RR}-python-example.md` | `chapter01.01-python-example.md` |
| Chapter index | `chapter{NN}-index.md` | `chapter01-index.md` |
| Chapter preface | `chapter{NN}-preface.md` | `chapter01-preface.md` |

Zero-pad recipe numbers for sort order: `chapter01.01`, `chapter01.02`, ... `chapter01.10`.

---

## Sidebar Updates

After creating new files, update `_Sidebar.md`:
- Main recipes appear as top-level items under their chapter heading
- Python companions appear as indented sub-items under their recipe

Example:
```
* [1.1: Insurance Card Scanning](chapter01.01-insurance-card-scanning)
  * [Python Example](chapter01.01-python-example)
```

---

## Audience

The main recipe serves a mixed audience: executives, leadership, architects, and developers. Everyone should be able to follow it. The pseudocode and step descriptions must be accessible to someone who has never written code. Technical accuracy is never sacrificed, but jargon is always explained inline.

The Python companion serves developers specifically. It assumes basic Python familiarity but explains AWS SDK patterns thoroughly.

---

## References and Resources

Every recipe must include a rich Additional Resources section with three categories:

### AWS Documentation
Links to the specific API references, feature guides, and pricing pages for services used in the recipe.

### AWS Sample Repos
Search for relevant repos from `aws-samples` and `aws-solutions-library-samples` on GitHub. Look for:
- Service-specific code samples (e.g., `amazon-textract-code-samples`)
- Healthcare-specific workshops and examples
- IDP, ML, or AI pipeline repos that demonstrate the recipe's patterns
- CDK/CloudFormation constructs for the services used
- Frame as "these repos demonstrate the patterns used here," not "this is the source code for this recipe."

### AWS Solutions and Blogs
Check these sources for deployable solutions, reference architectures, and deep-dive blog posts:
- **AWS Solutions Library:** https://aws.amazon.com/solutions/ (filter by AI/ML + Healthcare)
- **AWS Reference Architecture Diagrams:** https://aws.amazon.com/architecture/reference-architecture-diagrams/ (filter by AI/ML + Healthcare)
- **AWS ML Blog:** Search https://aws.amazon.com/blogs/machine-learning/ for the recipe's use case
- Include blog posts that show end-to-end architectures, customer case studies, or deep dives on the services used

### Rules
- **Never use fake or made-up GitHub URLs.** Verify every link exists before including it.
- Each resource entry gets a brief description of what it contains and why it's relevant.
- Aim for 5-10 documentation links, 3-5 sample repos, and 2-4 solutions/blogs per recipe.

---

## Prose Rules

- **No em dashes.** Never. Use periods, commas, colons, semicolons, parentheses, or restructure.
- **70/30 split.** 70% of prose should be technology-general. 30% is AWS-specific implementation.
- Read `STYLE-GUIDE.md` in this repo for full voice and tone rules.
- Read `~/.openclaw/global/VOICE.md` for CC's personal writing style.

---

_Last updated: 2026-03-05_
