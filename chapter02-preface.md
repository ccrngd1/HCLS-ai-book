# Chapter 2: Clinical Text Generation

*Teaching Machines to Write (Responsibly)*

Large language models are the most overhyped and simultaneously most underestimated technology in healthcare right now. That's not a contradiction. The hype is about what people *think* LLMs can do (replace doctors, automate clinical reasoning, solve healthcare). The underestimation is about what they *actually* can do today, right now, with proper guardrails: eliminate hours of administrative writing that burns out clinicians and delays patient care.

Here's the tension that makes this chapter interesting: LLMs are staggeringly good at generating fluent, confident text. They are also staggeringly good at generating fluent, confident *wrong* text. In most industries, a plausible-sounding error in a generated email is embarrassing. In healthcare, a plausible-sounding error in a clinical document could harm a patient. That asymmetry shapes every architectural decision in this chapter.

So we're not going to pretend this is simple. But we're also not going to pretend it's impossible. The recipes here represent a carefully ordered progression from "low risk, high value, deploy it next quarter" to "genuinely hard, proceed with caution, budget two years."

---

## What LLMs Actually Are (The 30-Second Version)

If you've somehow avoided the discourse: a large language model is a neural network trained on enormous amounts of text to predict what comes next in a sequence. That's it. That's the core mechanism. Given "The patient presents with chest pain and," the model assigns probabilities to every possible next word based on patterns it learned during training.

The magic (and I use that word deliberately, because it *feels* like magic even when you understand the math) is that this simple objective, predicting the next token, produces systems that can summarize, translate, answer questions, write in specific styles, follow complex instructions, and reason about novel problems. Nobody fully understands why this works as well as it does. That's not a criticism; it's an honest statement about the current state of the field.

For healthcare applications, the relevant capabilities are:

- **Summarization:** Condensing long clinical narratives into structured overviews
- **Translation:** Converting between registers (clinical jargon to patient-friendly language)
- **Synthesis:** Combining information from multiple sources into coherent output
- **Instruction following:** Generating text that adheres to specific format and content requirements
- **Grounded generation:** Producing text that references and stays faithful to provided source material

That last one, grounded generation, is the architectural pattern that makes healthcare LLM applications viable. More on that in a moment.

---

## Why Healthcare Is Both the Best and Worst Domain for LLMs

Healthcare is the best domain for LLMs because the administrative writing burden is crushing. Physicians spend roughly two hours on documentation for every hour of patient care.  Prior authorization letters are formulaic but time-consuming. Patient communications follow predictable patterns. After-visit summaries require synthesizing encounter data into readable prose. These are all tasks where "generate a first draft for human review" provides enormous value.

Healthcare is the worst domain for LLMs because the cost of errors is measured in human outcomes, not just dollars. A hallucinated drug interaction could lead to a missed contraindication. A summarization that drops a critical finding could delay treatment. A patient-facing message with incorrect dosing information could cause direct harm. The failure modes aren't theoretical; they're the reason every recipe in this chapter includes a human review step, confidence scoring, or grounding mechanism.

This creates a design constraint that's actually quite productive: you can't just point an LLM at a problem and ship the output. You have to build systems around the model. Retrieval pipelines that feed it verified source material. Validation layers that check outputs against known facts. Review workflows that route uncertain outputs to humans. Guardrails that prevent the model from straying outside its lane.

The recipes in this chapter are really about those *systems*, not about the models themselves. The model is one component. The architecture around it is what makes it safe.

---

## The Hallucination Problem (Let's Be Honest About This)

Every LLM hallucinates. Every single one. This isn't a bug that will be fixed in the next model release. It's a fundamental property of how these systems work: they generate text that is *statistically plausible* given their training data and the current context. Sometimes statistically plausible and factually correct diverge.

In healthcare, hallucination manifests in specific ways:

- **Citation fabrication:** The model invents a study that doesn't exist, complete with plausible author names and journal titles
- **Fact blending:** The model combines real facts from different contexts into a statement that's wrong (correct drug, wrong dosage; correct condition, wrong treatment)
- **Confident extrapolation:** The model extends a pattern beyond what the source data supports ("the patient's labs show improving renal function" when the labs show no such trend)
- **Temporal confusion:** The model references outdated guidelines or conflates current and historical patient information

The architectural response to hallucination is grounding: giving the model access to verified source material and constraining its output to reference that material. This is the Retrieval-Augmented Generation (RAG) pattern, and you'll see it in nearly every recipe from 2.4 onward. RAG doesn't eliminate hallucination, but it dramatically reduces it and makes the remaining errors detectable (you can check whether the output actually reflects the retrieved sources).

---

## The Progression: Simple to Complex

This chapter is ordered by risk and architectural complexity. Here's the logic:

**Recipes 2.1-2.2 (Simple):** Human always reviews before output reaches anyone. Low clinical risk. The LLM is drafting, not deciding. These are your quick wins, the use cases where you can demonstrate value in weeks, build organizational confidence, and learn operational patterns before tackling harder problems.

**Recipes 2.3-2.6 (Medium):** Output quality matters more. Grounding becomes essential. Integration with clinical workflows adds complexity. But the failure mode is still "a human catches a bad draft," not "a patient is harmed." These are your six-month projects.

**Recipes 2.7-2.8 (Medium-Complex):** Multiple data sources. Real-time constraints. The system needs to be right, not just plausible, because the humans reviewing it are busy and may not catch subtle errors. RAG architectures, citation verification, and confidence scoring become non-negotiable.

**Recipes 2.9-2.10 (Complex):** Direct clinical impact. Regulatory exposure. Multi-modal inputs. These are the use cases that require extensive validation, possibly FDA consideration, and organizational maturity with simpler LLM applications before you attempt them. They're included because they represent where the field is heading, but they're not where you start.

---

## Key Architectural Patterns You'll See Repeatedly

A few patterns show up across multiple recipes. Understanding them here will save repetition later:

**Human-in-the-loop review:** Every recipe includes a review step. The question is where in the workflow it sits and how much friction it adds. For simple drafting (2.1, 2.2), review is the natural endpoint. For real-time applications (2.8), review happens after generation with a tight feedback loop.

**Retrieval-Augmented Generation (RAG):** Instead of asking the model to generate from its training data alone, you retrieve relevant documents first and include them in the prompt. The model generates based on what you gave it, not what it "remembers." This is the single most important pattern for healthcare LLM applications.

**Confidence and uncertainty signaling:** Models can be prompted or fine-tuned to express uncertainty. Architecturally, you can also measure uncertainty through techniques like asking the model to cite its sources (verifiable claims) or generating multiple outputs and checking consistency.

**Guardrails and output validation:** Structured output formats (JSON schemas), content filters, clinical rule checks, and format validation that catch obviously wrong outputs before they reach a human reviewer.

**Prompt engineering as configuration:** In this chapter, prompts are treated as system configuration, not throwaway text. They're versioned, tested, and iterated like any other component. A prompt change is a deployment, not a casual edit.

---

## Healthcare-Specific Considerations

Beyond the general LLM challenges, healthcare adds layers:

**PHI in prompts:** If you're sending patient data to an LLM, that's PHI processing. You need a BAA with your model provider. You need encryption in transit. You need audit logging of what was sent and what was returned. Every recipe addresses this.

**Regulatory ambiguity:** The FDA has signaled interest in regulating AI-generated clinical content, but the boundaries are still forming. Recipes that approach clinical decision-making (2.9, 2.10) note the regulatory landscape honestly: it's uncertain, it's evolving, and your legal team needs to be involved.

**Bias and equity:** LLMs inherit biases from their training data. In healthcare, this can manifest as differential quality of generated content for different patient populations, or recommendations that reflect historical disparities in care. The recipes note where bias monitoring is particularly important.

**Provenance and auditability:** When an LLM generates a clinical document, you need to know what inputs produced that output. Not just for debugging, but for legal and compliance purposes. The architectures in this chapter include logging and provenance tracking as first-class concerns.

---

## A Note on Model Selection

These recipes are deliberately model-agnostic in their architecture sections. The patterns work whether you're using GPT-4, Claude, Llama, Mistral, or a domain-specific medical model. The AWS-specific sections show implementations using Amazon Bedrock, which provides access to multiple foundation models through a single API with built-in HIPAA eligibility.

Model capabilities are improving rapidly. A recipe that requires a frontier model today may work fine with a smaller, cheaper model in six months. The architectures are designed to be model-swappable: change the model endpoint, adjust the prompt, and the rest of the pipeline stays the same. That's intentional. Betting your architecture on a specific model version is a mistake you only make once.

---

## What You'll Build

By the end of this chapter, you'll have patterns for:

- Drafting patient communications that save staff hours daily
- Simplifying clinical language so patients actually understand their care
- Generating documentation that improves coding accuracy and revenue capture
- Automating prior authorization narratives that currently take 20-30 minutes each 
- Summarizing clinical encounters and complex medical histories
- Building RAG systems that ground LLM outputs in verified medical literature
- Processing ambient clinical conversations into structured notes
- Synthesizing clinical decision support from multiple knowledge sources
- Combining multi-modal clinical data (notes, labs, imaging findings, history) into reasoned differential diagnoses, with guardrails appropriate to the regulatory frontier this work sits on

Each recipe stands alone, but they build on each other conceptually. Start with 2.1 or 2.2 to get comfortable with the patterns, then work forward as your use cases demand.

Let's start writing.

---

*→ [Recipe 2.1: Patient Message Response Drafting](chapter02.01-patient-message-response-drafting)*
