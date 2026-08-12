<!-- Removed from chapter01.08-eob-processing.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what the original version of this recipe got right: the static profile approach works well for your top-5 payers. If 80% of your EOB volume comes from UHC, Anthem, Medicare, BCBS, and Aetna, and you've built and validated profiles for those five, you've automated 80% of your volume with a cheap, fast, deterministic pipeline. The LLM adds marginal value for those five payers.

Here's where the original version hit a wall: the other 20%. Every regional plan. Every Medicare Advantage variant. Every time UHC changes a column label. The profile library becomes an operational artifact that someone has to maintain indefinitely. When I actually thought through the full lifecycle of that system, the maintenance burden was the dominant cost, not the compute.

The LLM-based approach shifts the cost structure. Instead of a low per-document runtime cost and high ongoing maintenance cost, you get a slightly higher per-document runtime cost and near-zero ongoing maintenance cost for the long-tail payers. At most EOB processing volumes, that trade is clearly in favor of the LLM for anything beyond your top-10 payers.

The model choice matters here. This is not a complex reasoning task. The LLM needs to read column headers like "What Your Plan Paid" and map them to `plan_paid`. Nova Pro at $0.80 per million input tokens does this reliably. You don't need Claude Opus for field label normalization. Using the cheapest model that handles the task is the right call, and this is a case where the mid-tier model is genuinely sufficient. The tiered model approach introduced in Recipe 1.4 pays off again.

The part I want to be direct about: financial validation needs to stay deterministic. I've seen proposals for using LLMs to "validate" financial records by asking them to check whether the numbers look right. That is not validation. That is a probabilistic assessment of a deterministic constraint. The arithmetic rule for member responsibility either holds or it doesn't. An LLM telling you "the numbers look reasonable" is not the same as a rule telling you "this passed or failed constraint X." In a COB workflow where the output drives secondary payment calculations, "looks reasonable" is not an acceptable quality signal. Use the math.

One thing I'm genuinely uncertain about: Bedrock schema mapping accuracy on the hard cases. The recipe claims 92-97% accuracy, which is based on testing against a sample of known payer formats. For payers with genuinely unusual layouts (non-tabular line item presentation, column headers that are abbreviations rather than descriptive labels), I've seen the LLM produce mappings that are plausible but wrong. The financial validation layer catches many of these (a wrong column mapping tends to fail the arithmetic checks), but not all. If your review queue shows a high rate of Bedrock-path EOBs with validation errors, that's a signal to investigate the mapping quality rather than just adjusting tolerances. And if you see `mapping_incomplete` status for payers where you'd expect financial data, that's the coverage check working: the LLM either missed the financial columns or mapped them to non-canonical names that got filtered out.

---

