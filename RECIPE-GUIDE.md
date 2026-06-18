# Recipe Writing Guide

_How to write recipes for the Healthcare AI/ML Cookbook. Read this before writing any recipe._

---

## Recipe Structure (Three Files)

Every recipe is split across three files, each serving a different audience:

1. **Main recipe** (`chapter{NN}.{RR}-{name}.md`) — "the book." Vendor-agnostic story and concepts. The part a reader reads.
2. **Architecture companion** (`chapter{NN}.{RR}-architecture.md`) — the AWS implementation and pseudocode. Reference material for architects/implementers.
3. **Python companion** (`chapter{NN}.{RR}-python-example.md`) — illustrative working code for developers.

This separation keeps the readable core small (each main recipe is ~5,000 words / a 25-minute read) while preserving the full implementation detail in companions.

---

## Main Recipe File (Part 1: Vendor-Agnostic + Closer)

The main file is entirely vendor-agnostic except for the closing sections. **No S3, no Lambda, no Textract** in The Problem / The Technology / General Architecture Pattern. A reader on GCP, Azure, or on-premises should learn everything valuable here.

**The Problem.** Make the reader feel why this sucks today. Real-world scenario, human impact, scale of the pain. A VP of Operations should read this and nod along.

**The Technology.** Teach the underlying tech from first principles. What is it? How does it work? Why is it hard, and why is it good enough anyway? Where has the field moved? No vendor names.

**General Architecture Pattern.** The pipeline at a conceptual level: logical stages, data flow. Still no vendor names. End this section with the callout that links to the architecture companion (see below).

**The Honest Take.** Where it breaks in practice, what surprised you, what you'd do differently. Self-deprecating expertise. This stays on the main file as the narrative closer.

**Related Recipes.** Cross-references by recipe number with one-line descriptions.

**Tags.** Searchable labels.

**Navigation.** Footer links to previous recipe, chapter preface, and next recipe.

### The architecture callout (end of General Architecture Pattern)

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter{NN}.{RR}-architecture). The Python example is linked from there.

---

## Architecture Companion File (Part 2: AWS-Specific)

`chapter{NN}.{RR}-architecture.md`. Opens with a backlink header to the main recipe, then:

**Why These Services.** Introduce each AWS service and connect it back to the concept it implements from the main recipe's Part 1.

**Architecture Diagram.** Mermaid flowchart of the AWS components and data flow.

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

**Ingredients.** Table of AWS services and their specific roles.

**Code (Pseudocode Walkthrough).** Language-agnostic pseudocode with heavy inline comments. Each step gets: a business-level explanation, what goes wrong if you skip it, and a commented pseudocode block. After the walkthrough, include the callout linking to the Python companion:

> **Curious how this looks in Python?** The pseudocode above covers the concepts. If you'd like to see sample Python code that demonstrates these patterns using boto3, check out the [Python Example](chapter{NN}.{RR}-python-example). It walks through each step with inline comments and notes on what you'd need to change for a real deployment.

**Expected Results.** Sample JSON output, performance benchmarks table, where it struggles.

**Why This Isn't Production-Ready.** The gaps a production deployment must close.

**Variations and Extensions.** 2-3 practical extensions.

**Additional Resources.** AWS docs, sample repos, solutions/blogs. Only real, verified URLs.

**Estimated Implementation Time.** Three tiers: Basic, Production-ready, With variations.

**Navigation.** Footer links to the main recipe, the Python example, and the chapter preface.

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
| Architecture companion | `chapter{NN}.{RR}-architecture.md` | `chapter01.01-architecture.md` |
| Python companion | `chapter{NN}.{RR}-python-example.md` | `chapter01.01-python-example.md` |
| Chapter preface | `chapter{NN}-preface.md` | `chapter01-preface.md` |

Zero-pad recipe numbers for sort order: `chapter01.01`, `chapter01.02`, ... `chapter01.10`.

(There is no separate chapter-index file. Chapter navigation points at the chapter preface.)

---

## Sidebar Updates

After creating new files, update `_Sidebar.md`:
- Main recipes appear as top-level items under their chapter heading
- The architecture companion and Python companion appear as indented sub-items under their recipe, in that order

Example:
```
* [1.1: Insurance Card Scanning](chapter01.01-insurance-card-scanning)
  * [Architecture and Implementation](chapter01.01-architecture)
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
