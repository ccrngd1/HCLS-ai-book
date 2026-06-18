# Recipe 1.8: Explanation of Benefits Processing 🔶

**Complexity:** Moderate · **Phase:** Phase 2 · **Estimated Cost:** ~$0.13-0.22 per EOB 

---

## The Problem

Every time a health insurance claim settles, the payer sends an Explanation of Benefits to the member. "We received your claim. Your provider billed $185. We allowed $118 under your network agreement. We paid the provider $94.40. You owe $23.60." Simple enough in concept.

In practice, these documents are everywhere. Members stuff them in drawers and later pull them out to dispute a balance. Provider billing offices receive them as proof of payment and need to reconcile them against their accounts receivable. When a patient has two insurance plans, the secondary payer has to ingest the primary payer's EOB to figure out what's already been paid before it processes its portion of the claim. This last scenario has a name: coordination of benefits, or COB. And it is, without exaggeration, one of the messiest data problems in healthcare finance.

Here's the core problem. The information on every EOB is essentially identical. Claim number. Service dates. Procedure codes. What was billed. What was allowed. What the plan paid. What the member owes. Every payer tracks these same fields. But every payer lays them out differently. A UnitedHealthcare EOB calls the plan payment "What Your Plan Paid." An Anthem EOB calls it "Plan Paid Amount." A Medicare Summary Notice calls it "Medicare Paid Provider." CMS uses a three-column layout with its own iconography. Cigna uses a tabbed format where line items appear on a different page from the summary. Some payers put claim-level summary data in a header section and line items in a table below. Others mix summary and line item data in a single table. 

Your claims adjusters know how to read all of these. They've been staring at EOBs for years. But they're doing it one document at a time, manually keying data into your adjudication system. For a secondary payer processing coordination of benefits, that means a human reads the primary EOB, finds the "plan paid" field wherever it lives on that payer's format, enters the number, and the secondary claim can proceed. At scale, that is a lot of humans doing a lot of repetitive data entry.

The standard engineering answer to this problem is a **payer profile system**: a library of per-payer dictionaries that map each payer's field labels to a canonical schema. "What Your Plan Paid" maps to `plan_paid`. "Medicare Paid Provider" also maps to `plan_paid`. The downstream system sees only canonical names. This works. The original version of this recipe described exactly this approach.

Here's what happens six months later: UnitedHealthcare refreshes their EOB template. "What Your Plan Paid" becomes "Amount Paid by Plan." Your UHC profile stops matching. EOBs start routing to the review queue in volume. Someone gets paged. An engineer opens a JIRA ticket to update the profile. It gets merged, tested, deployed. The backlog of flagged EOBs gets reprocessed. Crisis averted. For now.

A regional Blue Cross Blue Shield plan that covers 40,000 members in your network uses a layout you've never seen before. You need someone to obtain sample documents, figure out their field naming, write a profile, test it, deploy it. For 40,000 members. Meanwhile those EOBs sit in the review queue.

Multiply this by the number of payers in your network. Multiply it by the pace at which payers refresh their templates. You start to see the real operational cost of a static profile library. It's not a one-time build; it's a permanent maintenance burden that scales with your payer network.

What this recipe does differently is replace the profile maintenance problem with a language model. Instead of maintaining a dictionary that maps field labels to canonical names, we send the extracted table data directly to an LLM and ask it to do the mapping. The model reads "What Your Plan Paid" and knows it means `plan_paid`. It reads "Medicare Paid Provider" and knows that too. It handles the regional BCBS format it has never explicitly been trained on, because it has learned from enough variation in human-written text to generalize. When a payer refreshes their template, the system adapts without a code change.

This is what the earlier recipes in the LLM transition arc have been building toward: showing how LLMs replace not just rule-based logic, but **configuration complexity**. Recipe 1.4 replaced keyword heuristics for page classification. Recipe 1.5 replaced rule-based boundary detection. Recipe 1.6 replaced OCR-then-NLP with direct vision understanding. This recipe shows the LLM eliminating an entire ongoing maintenance workflow.

One more thing before we get into the architecture: financial validation does not change. The dollar amounts in an EOB must satisfy mathematical relationships: billed must be greater than or equal to allowed, allowed must be greater than or equal to plan paid, member responsibility must reconcile against the plan payment. These are arithmetic rules. LLMs should not do arithmetic. Rule-based validation for financial math. That part stays exactly where it was.

---

## The Technology: Extraction, Schema Mapping, and Financial Validation

### This Is a Financial Document, Not a Clinical One

Worth saying explicitly, because it affects almost every technical decision. An EOB is a financial record. The fields it contains are claim identifiers, service dates, CPT codes used as billing references, and dollar amounts. When you see "99213" on an EOB, it means the provider billed for this procedure code and here is what was paid. You don't need to understand what 99213 means clinically. You need to extract the code as a string and associate it with the dollar amounts on the same line.

This distinction matters because healthcare document processing recipes often reach for clinical NLP tooling as a reflex. Recipes 1.3 and 1.4 use Amazon Comprehend Medical because they deal with clinical narrative text that needs entity extraction and medical code mapping. EOBs have no clinical free text worth extracting. The service descriptions are billing language. The procedure and diagnosis codes are already machine-readable identifiers. What you need from an EOB is extraction and schema normalization: find the fields, understand what they mean, check the math. Clinical NLP adds no value and meaningful cost.

What you do need is a model that understands the semantics of healthcare financial terminology well enough to map "Amount Charged" and "What Your Provider Billed" and "Billed Amount" and "Charges" to the same canonical field. That's language understanding, not clinical NLP. And it's precisely what general-purpose language models are good at.

### The Table Extraction Problem: Why Textract Stays

If you've worked through Recipe 1.2, you know the basics. A document scanner or fax server produces an image or PDF. An extraction service identifies the grid structure, maps each cell to a row and column index, and returns the contents as a two-dimensional array. For a well-formatted printed table, this is reliable.

EOBs push table extraction in two directions that simple intake forms don't.

First, EOB tables are dense. A typical intake form medication table has maybe four or five columns and a handful of rows. An EOB from a busy month might have fifteen or twenty line items, each with six to eight columns: procedure code, service date, provider, billed amount, contractual adjustment, plan payment, member deductible applied, member coinsurance. The columns are narrow. The fonts are small. Payers optimize their EOB layouts for printing on a single sheet of paper, not for legibility. This creates challenges: cell boundaries become ambiguous when content is densely packed, and small fonts degrade accuracy on low-resolution scans.

Second, EOB tables sometimes span multiple pages. A simple claim settles on a single page. A complex claim with many service dates, or an EOB from a capitated plan covering a full month of encounters, can push the line items across two or three pages. The extraction service needs to recognize that the table continues across pages and that the column structure carries forward.

Amazon Textract handles both of these well. It uses `RowIndex` and `ColumnIndex` attributes on each cell, letting you reconstruct the grid without depending on visual line detection. This is helpful because some payers use borderless tables that rely on spatial alignment rather than printed grid lines. Textract also supports multi-page documents natively via async processing, and its FORMS feature captures the header key-value data in the same job.

You might wonder: can a vision model like Claude Sonnet just read the EOB PDF directly and extract the table data, without Textract at all? Yes, actually. Claude supports direct PDF input. But Textract is purpose-built for structured table extraction and returns highly reliable cell-level data with confidence scores. It handles the dense multi-page table structure of EOBs better than a vision model prompted to extract tables. More importantly, you want the confidence scores: they feed the validation layer and the routing decision. Textract gives you those for free. A vision model would require you to engineer a confidence signal from its output.

The right decomposition: Textract does the structural extraction (what are the rows, what are the cells, what do the cells say). The LLM handles the semantic mapping (what does each column actually mean). Each tool is doing what it's best at.

### The Layout Variability Problem: What the Profile System Was Solving

The core challenge with EOB processing isn't OCR accuracy. Given a reasonably good scan, Textract gets the text right. The challenge is knowing what the text means.

"Amount Charged," "Provider Billed," "What Your Provider Billed," and "Billed Amount" are four different strings that all mean the same thing: what the provider submitted for payment. When Textract extracts a table column header reading "What Your Provider Billed," your code needs to know that this column should map to the `billed_amount` field in your canonical schema.

The traditional solution is a static mapping: for UnitedHealthcare documents, this label means this canonical field. Build a dictionary for each payer. Maintain it as payers update their templates.

The LLM-based solution is: send the extracted column headers and a sample of the cell values to a language model, provide the canonical schema, and ask it to produce the mapping. The model reads "What Your Provider Billed" and understands, from training on vast amounts of financial and healthcare text, that this is a billed amount field. It reads "Medicare Paid Provider" and knows that's a plan payment field. It produces the same JSON mapping your static dictionary would have produced, without requiring you to build or maintain that dictionary.

There is a legitimate cost tradeoff here. An LLM call costs more per document than a dictionary lookup. For your top-10 payers by volume, a static profile is cheaper, faster, and fully deterministic. The LLM pays for itself on the long tail: every payer beyond your top-10, every regional plan you've never explicitly configured for, every template refresh that would otherwise create a backlog of flagged documents. For those cases, the LLM eliminates a maintenance workflow that has real engineering cost.

This recipe implements that hybrid approach. Known high-volume payers get a static profile, same as before. Everything else routes through Bedrock for schema mapping.

### Adaptive Mapping: The LLM Handles Layout Variations Naturally

Here's the thing about the LLM approach that isn't immediately obvious: you don't have to detect the payer first.

In the static profile system, you need to identify who issued the EOB before you can select the right mapping dictionary. Payer detection is its own step: keyword matching against the document header, returning a payer identifier, looking up the profile. It's another piece of logic to maintain.

With the LLM, the mapping prompt doesn't need to know which payer issued the document. You send the column headers as they appear in the document, the canonical schema you want as output, and ask the model to map one to the other. The model uses the semantic meaning of the labels directly, without a payer identifier as an intermediate step.

This is elegant. It also handles the cases the static system fails on: regional BCBS plans with unique layouts, Medicare Advantage plans that print their own branded EOBs, new payers entering your network. You don't need to recognize them; you just need to understand what their column headers mean. The LLM does that without per-payer configuration. 

For the high-volume payer shortcut: payer detection fires when your S3 intake pipeline organizes EOBs into per-payer prefixes (for example, `eobs-inbox/unitedhealthcare/2026/03/...`). The Lambda extracts the payer name from the prefix segment and uses the static profile for those payers, skipping the Bedrock call entirely. **The static profile shortcut only fires when per-payer S3 prefixes are in place.** If your intake pipeline writes to flat date-partitioned prefixes, all documents arrive with `payer_hint = None` and route through Bedrock, including your top-10 payers. That's fine for correctness, but you're paying Bedrock costs for documents you could handle deterministically. If per-payer prefix organization isn't practical, add header keyword detection to `map_to_canonical_schema` before calling Bedrock: scan the raw header label keys for known payer name strings ("unitedhealthcare", "medicare", etc.) and use the static profile when a match is found. See the Variations section for a code sketch.

### Financial Validation: Why This Stays Rule-Based

Every well-formed EOB satisfies a set of mathematical relationships. The billed amount must be greater than or equal to the allowed amount. The allowed amount must be greater than or equal to the plan payment. The member responsibility must equal the allowed amount minus the plan payment, subject to deductible and copay logic. The total claim payment in the header must equal the sum of line item payments.

LLMs should not perform this validation. Not because they can't do arithmetic (they can, imperfectly), but because financial validation needs to be deterministic. The same EOB should fail validation for the same reason every time. You need to know exactly which rule triggered a flag, so the human reviewer knows what to check. You need audit trails that show specific rule violations. You need the ability to adjust tolerances and re-run validation on archived records.

Rule-based arithmetic validation gives you all of that. LLM-based financial checking gives you probabilistic output that varies with temperature settings and cannot be audited at the rule level. For math problems where the stakes are measured in dollars and the output feeds a compliance-sensitive workflow, determinism is not optional.

The financial validation step in this recipe is unchanged from the original. Extract numbers. Apply arithmetic rules. Collect specific violations. Route based on violation presence. No LLM in the loop for this step. 

**The mapping-to-validation trust boundary.** Financial validation is only as reliable as the fields it receives. If Bedrock fails to map the financial columns, the rule-based validation checks receive `None` for every financial field and silently skip. The record exits validation with no errors, writes to DynamoDB as `status: "valid"`, and looks identical to a record where all the math checked out. To close this gap, the pipeline includes a minimum coverage assertion between the mapping step and the validation step: before running any financial rules, it verifies that at least `billed_amount` and `plan_paid` are present in the assembled line items. If either is absent, the record routes to manual review with `status: "mapping_incomplete"` rather than passing silently. This check applies to both the Bedrock path (where the LLM may fail to map financial columns) and the static profile path (where a profile with missing entries produces the same gap).

### The General Architecture Pattern

EOB processing follows a pipeline with a new step between table extraction and financial validation:

```text
[Ingest] → [Extract] → [Map Schema] → [Parse Line Items] → [Validate] → [Store or Flag]
```

**Ingest:** The EOB arrives via fax, portal upload, or electronic COB feed. Format is almost always PDF, occasionally TIFF from older fax servers.

**Extract:** Submit the document to Textract with FORMS and TABLES feature types. Wait for the async completion signal. Retrieve all result pages via pagination. This produces raw key-value pairs from the header and a raw grid of rows and columns from the line item table.

**Map Schema:** For high-volume known payers: apply the static profile dictionary. For all other payers: send the raw extracted column headers and a sample of cell values to Bedrock with the canonical schema. Receive back a JSON mapping from extracted labels to canonical field names.

**Parse Line Items:** Walk the mapped table rows and assemble each line item with canonical field names and parsed currency values.

**Validate:** Apply financial math constraints to the parsed line items. Check line item totals against header summary totals. Produce a list of validation errors. Before running validation, assert that the minimum required financial fields (`billed_amount`, `plan_paid`) are present from the mapping step; if not, route to review immediately.

**Store or Flag:** Valid records go directly to the output table. Records with validation errors or schema mapping failures go to a review queue.

Any cloud provider, any extraction engine fits this pattern. The schema mapping prompt and the validation logic are portable.

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter01.08-architecture). The Python example is linked from there.

---

## Expected Results

**Sample output for a 2-page EOB processed via Bedrock schema mapping:**

```json
{
  "document_key": "eobs-inbox/2026/03/01/eob-00447.pdf",
  "extracted_at": "2026-03-01T14:22:08Z",
  "payer_hint": null,
  "mapping_path": "bedrock_mapping",
  "header": {
    "claim_number": "EOB-7291048",
    "member_name": "Patricia Martinez",
    "member_id": "BCB-829-10477",
    "group_number": "72-90145",
    "provider_name": "Lakeside Internal Medicine",
    "service_period": "02/10/2026"
  },
  "line_items": [
    {
      "date_of_service": "02/10/2026",
      "service_description": "Office Visit - Level 3",
      "procedure_code": "99213",
      "billed_amount": "$185.00",
      "allowed_amount": "$118.00",
      "plan_paid": "$94.40",
      "member_responsibility": "$23.60",
      "deductible_applied": "$0.00",
      "copay": "$20.00",
      "coinsurance": "$3.60"
    }
  ],
  "financial_validation": {
    "errors": [],
    "status": "valid",
    "validated_at": "2026-03-01T14:22:09Z"
  }
}
```

**Sample output for a high-volume payer using the static profile:**

```json
{
  "document_key": "eobs-inbox/unitedhealthcare/2026/03/01/eob-00423.pdf",
  "extracted_at": "2026-03-01T14:20:42Z",
  "payer_hint": "unitedhealthcare",
  "mapping_path": "static_profile",
  "header": { "claim_number": "EOB-9284710", "member_id": "UHC8291047" },
  "line_items": [
    {
      "billed_amount": "$185.00", "plan_paid": "$94.40",
      "member_responsibility": "$23.60", "procedure_code": "99213"
    }
  ],
  "financial_validation": { "errors": [], "status": "valid" }
}
```

**Sample output for a document that failed the minimum coverage check:**

```json
{
  "document_key": "eobs-inbox/2026/03/01/eob-00448.pdf",
  "extracted_at": "2026-03-01T14:23:15Z",
  "payer_hint": null,
  "mapping_path": "mapping_incomplete",
  "header": { "claim_number": "EOB-7291049", "member_id": "XYZ-001" },
  "line_items": [
    { "Date of Service": "02/10/2026", "Procedure": "99213" }
  ],
  "financial_validation": {
    "errors": [],
    "status": "mapping_incomplete",
    "validated_at": "2026-03-01T14:23:15Z"
  }
}
``` 

**Performance benchmarks:**

| Metric | Typical Value |
|--------|---------------|
| End-to-end latency (2-page EOB, static profile path) | 8-14 seconds |
| End-to-end latency (2-page EOB, Bedrock mapping path) | 10-18 seconds |
| Textract table extraction accuracy (clean scan) | 90-96% per cell |
| Bedrock schema mapping accuracy (common payer formats) | 92-97% |
| Financial validation catch rate | 80-90% of extraction errors via math checks |
| Incremental Bedrock cost per EOB (Bedrock path) | Under $0.001 |
| Cost per 2-page EOB (static profile path) | ~$0.13 |
| Cost per 2-page EOB (Bedrock mapping path) | ~$0.131 |

> **Latency note:** End-to-end latency includes Textract async queue processing time (~5-10 seconds for 2-page documents under normal load; 30-60 seconds under high concurrent job volume). For batch EOB processing, Textract's async queue is the dominant latency variable. Lambda processing time (Bedrock call + validation + DynamoDB write) is typically 2-8 seconds.

**Where it struggles:** EOBs with merged table cells in summary sections (common in COB layouts where a multi-payer breakdown appears in a non-standard format). EOBs where line item data appears in paragraph form rather than a table (a small number of payers do this for single-service claims). Multi-page tables where page breaks split a row across pages. And any EOB that has been photocopied more than once: scan quality degradation compounds, and by the third generation you're fighting image noise as much as document structure.

The Bedrock mapping path also has a failure mode the static profile system doesn't: if the LLM maps a column to the wrong canonical field, the error is harder to detect without financial validation catching it. A static profile is wrong in a predictable, consistent way. An LLM mapping can be wrong in an unpredictable way on any given document. For high-stakes EOBs (large claim amounts, COB workflows), the determinism of a validated static profile is a real advantage. Use Bedrock for the long tail; use static profiles where you have volume and validated samples.

---

## The Honest Take

Here's what the original version of this recipe got right: the static profile approach works well for your top-5 payers. If 80% of your EOB volume comes from UHC, Anthem, Medicare, BCBS, and Aetna, and you've built and validated profiles for those five, you've automated 80% of your volume with a cheap, fast, deterministic pipeline. The LLM adds marginal value for those five payers.

Here's where the original version hit a wall: the other 20%. Every regional plan. Every Medicare Advantage variant. Every time UHC changes a column label. The profile library becomes an operational artifact that someone has to maintain indefinitely. When I actually thought through the full lifecycle of that system, the maintenance burden was the dominant cost, not the compute.

The LLM-based approach shifts the cost structure. Instead of a low per-document runtime cost and high ongoing maintenance cost, you get a slightly higher per-document runtime cost and near-zero ongoing maintenance cost for the long-tail payers. At most EOB processing volumes, that trade is clearly in favor of the LLM for anything beyond your top-10 payers.

The model choice matters here. This is not a complex reasoning task. The LLM needs to read column headers like "What Your Plan Paid" and map them to `plan_paid`. Nova Pro at $0.80 per million input tokens does this reliably. You don't need Claude Opus for field label normalization. Using the cheapest model that handles the task is the right call, and this is a case where the mid-tier model is genuinely sufficient. The tiered model approach introduced in Recipe 1.4 pays off again.

The part I want to be direct about: financial validation needs to stay deterministic. I've seen proposals for using LLMs to "validate" financial records by asking them to check whether the numbers look right. That is not validation. That is a probabilistic assessment of a deterministic constraint. The arithmetic rule for member responsibility either holds or it doesn't. An LLM telling you "the numbers look reasonable" is not the same as a rule telling you "this passed or failed constraint X." In a COB workflow where the output drives secondary payment calculations, "looks reasonable" is not an acceptable quality signal. Use the math.

One thing I'm genuinely uncertain about: Bedrock schema mapping accuracy on the hard cases. The recipe claims 92-97% accuracy, which is based on testing against a sample of known payer formats. For payers with genuinely unusual layouts (non-tabular line item presentation, column headers that are abbreviations rather than descriptive labels), I've seen the LLM produce mappings that are plausible but wrong. The financial validation layer catches many of these (a wrong column mapping tends to fail the arithmetic checks), but not all. If your review queue shows a high rate of Bedrock-path EOBs with validation errors, that's a signal to investigate the mapping quality rather than just adjusting tolerances. And if you see `mapping_incomplete` status for payers where you'd expect financial data, that's the coverage check working: the LLM either missed the financial columns or mapped them to non-canonical names that got filtered out.

---

## Related Recipes

- **Recipe 1.2 (Patient Intake Form Digitization):** The async Textract plus table extraction foundation this recipe builds on. The block parsing, pagination, and SNS wiring patterns are identical.
- **Recipe 1.4 (Prior Authorization Document Processing):** The LLM transition recipe that introduced the Bedrock Converse API pattern and model tiering. Recipe 1.8 applies the same mid-tier model reasoning (right tool for the task) to a different structured extraction problem.
- **Recipe 1.5 (Claims Attachment Processing):** EOBs arrive as part of claims attachment packages. Recipe 1.5 classifies document types within an attachment package and routes each to the appropriate extractor; this recipe is the extractor for the EOB document type.
- **Recipe 8.1 (Insurance Eligibility Matching):** The member ID and group number extracted from an EOB header feed into eligibility verification workflows. If a COB workflow needs to verify primary coverage status, Recipe 8.1 is the next step.

---

## Tags

`document-intelligence` · `ocr` · `textract` · `bedrock` · `nova-pro` · `haiku` · `tables` · `eob` · `financial` · `coordination-of-benefits` · `claims` · `schema-mapping` · `llm-normalization` · `financial-validation` · `hybrid-architecture` · `moderate` · `phase-2` · `hipaa` · `lambda` · `dynamodb` · `sqs`

---

*← [Chapter 1 Index](chapter01-preface) · [← Recipe 1.7: Prescription Label OCR](chapter01.07-prescription-label-ocr) · [Next: Recipe 1.9: Medical Records Request Extraction →](chapter01.09-medical-records-request-extraction)*
