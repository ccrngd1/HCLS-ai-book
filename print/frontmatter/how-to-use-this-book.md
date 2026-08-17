<!--
Edit this file freely; it is the source for a front-matter page in the print
edition. Plain markdown. Placeholders substituted at build time from
print/manifest.json:

  {digital_url}  {recipe_count}  {extra_recipes}   (the QR code block is appended by the build)

If this file is deleted the build omits the page rather than failing.
House style: no em dashes, no emoji, abbreviations spelled out on first use.
-->

# How to Use This Book

- **Browse by capability.** Each chapter is a self-contained recipe in a distinct AI/ML domain; read in any order.
- **Start with the problem.** Every recipe opens with a concrete healthcare scenario before any technology.
- **Mind the honest take.** Each recipe ends with the limitations and the things that surprised us in production.
- **Go deeper online.** The digital edition ({digital_url}) has the AWS implementation, diagrams, runnable examples, and {extra_recipes}+ more recipes.

**How to read a recipe.** Every recipe opens with one line: Effort, Maturity, and Oversight.

- **Effort (1 to 5):** the honest total cost to reach a trustworthy production system, counting data plumbing, governance, integration, and change management, not just the model. A 1 ships in weeks; a 5 is a standing program.
- **Maturity:** how settled the technology is across the industry: Commodity, Proven, Emerging, or Research.
- **Oversight:** how much human review each output needs before it can act: Autonomous, Exception review, Every output, or Dual review. It is a property of the design, not a proxy for difficulty.
