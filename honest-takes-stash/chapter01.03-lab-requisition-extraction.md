<!-- Removed from chapter01.03-lab-requisition-extraction.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

This recipe is where the cookbook shifts from "impressive party trick" to "genuinely difficult problem."

The Textract pipeline from Recipes 1.1 and 1.2 is almost mechanical to get right once you understand the pattern. The Comprehend Medical layer introduces a different kind of uncertainty. OCR confidence is about whether a character was read correctly. NLP confidence is about whether the model's interpretation of the text is correct. These are different failure modes and they require different review processes. A coder reviewing a low-confidence ICD-10 suggestion needs clinical knowledge, not just good eyesight.

The thing that surprised me most when testing this: the medical necessity check flags more orders than you expect on a first pass. It's not because the orders are clinically inappropriate. It's because the mapping table is incomplete. Physicians often write shorthand diagnoses ("lipids" instead of "hyperlipidemia") that the ICD-10 inference maps to a code prefix not in your table. Before concluding that a medical necessity flag means the order is problematic, audit your table coverage first.

The ICD-10 code specificity issue is a constant low-grade frustration. Getting E11.9 when you need E11.65 doesn't mean the inference is wrong about the diagnosis category. It means the model was appropriately conservative when the clinical text didn't clearly specify complications. In many payer workflows, E11.9 is fine. In some, it kicks off an additional review step. Know your payer's policies before you decide whether to accept top-ranked inferences at face value or route them through coder review regardless of confidence.

The CPT lookup table is honestly the most maintenance-intensive part of this pipeline. It doesn't feel glamorous. It is critical. A missed CPT mapping means a test goes unvalidated, potentially unbilled, potentially uncovered. The mapping table should live in a configuration system with change tracking, not hardcoded in a Lambda function.

---

