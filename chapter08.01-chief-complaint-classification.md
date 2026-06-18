# Recipe 8.1: Chief Complaint Classification

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$360-720/month (endpoint hosting) + ~$0.001 per request

---

## The Problem

A patient walks up to the triage desk at an emergency department and says "my chest hurts." Another says "I have chest pain." A third writes "pressure in my chest since this morning." A fourth types "cp" into a kiosk form. A fifth, speaking through a translator, has it documented as "patient reports discomfort in thoracic region."

All five patients probably need the same clinical pathway. But in most health systems, getting them routed correctly depends entirely on whichever nurse or registration clerk happens to be working that shift, their experience level, and whether they're four hours into a twelve-hour shift.

Chief complaints are the front door of clinical care. They're the first structured (loosely structured, really) data point captured about why a patient is seeking care. They drive triage routing, they populate analytics dashboards, they feed quality metrics, they determine which protocols fire, and they inform capacity planning. If your ED sees 200 patients a day and you want to know how many presented with respiratory complaints this flu season, you need those free-text entries classified into categories that computers can count and compare.

The problem is that chief complaints are among the messiest text data in healthcare. They're short (often under ten words), highly variable in phrasing, riddled with abbreviations that differ by institution, sometimes misspelled, sometimes entered by non-clinical staff transcribing what a patient said in a waiting room, and sometimes in a language other than English. They lack the grammatical structure that most NLP tools rely on. A chief complaint isn't a sentence. It's a fragment. A signal compressed to its minimum.

And yet: the set of meaningful clinical categories is finite. Most EDs use somewhere between 50 and 200 complaint categories for operational purposes. The mapping from messy input to clean category is a classification problem, and it's one that traditional NLP handles remarkably well. You don't need a large language model. You don't need a GPU cluster. You need a text classifier trained on your historical routing decisions, a solid preprocessing pipeline, and some thoughtful engineering around the edge cases.

Let's talk about how that works.

---

## The Technology: Text Classification for Short Clinical Fragments

### What Is Text Classification?

At its core, text classification takes an input string and assigns it to one (or sometimes more than one) predefined category. Spam detection is text classification. Sentiment analysis is text classification. And routing "cp x3 days, worse with exertion" to the category "Chest Pain, Cardiac" is text classification.

The general pipeline looks like this: take raw text, clean it up (lowercase, remove punctuation, expand abbreviations), convert it into a numerical representation that a model can process, and feed that representation to a classifier that outputs a category label plus a confidence score.

There are two main eras of text classification techniques, and both are still relevant here:

**Classical ML approaches** (Naive Bayes, logistic regression, SVM with TF-IDF features): These work surprisingly well for short text with clear category boundaries. They train fast, predict fast, and are interpretable. When your input is five words and your output is one of 150 categories, you don't always need deep learning. A logistic regression model trained on 50,000 labeled examples with TF-IDF features can hit 85-92% accuracy on chief complaint classification. That's not hypothetical; it's been demonstrated repeatedly in the literature.

**Modern embedding approaches** (word vectors, sentence transformers, fine-tuned models): These represent text as dense vectors in a high-dimensional space where semantically similar phrases cluster together. "Chest pain," "thoracic discomfort," and "cp" can end up near each other in embedding space even though they share no words. Pre-trained clinical embeddings (trained on millions of clinical notes) capture medical terminology relationships that a bag-of-words model misses entirely.

For chief complaint classification specifically, the sweet spot is often a hybrid: use embeddings to handle the semantic similarity problem, but keep the model small and fast because you're classifying fragments, not essays.

### Why This Is Actually Hard (Despite Being "Simple")

Chief complaint classification gets labeled "simple" in NLP taxonomies because the inputs are short and the categories are finite. But there are real challenges that make naive approaches fail:

**Abbreviation chaos.** "SOB" means shortness of breath. Except when someone types it meaning something else entirely, or when "S.O.B." appears with periods, or when "s/o/b" is someone's creative variant. "HA" is headache. "N/V" is nausea and vomiting. "CP" is chest pain. These abbreviations are not standardized across institutions. The same health system might have different abbreviation conventions across campuses.

**Multi-complaint entries.** "Chest pain and shortness of breath" is two complaints. "Fall with head laceration" is an injury mechanism plus an injury. Do you classify to the primary? Both? The most urgent? This is a design decision, not a technical one, but your classifier needs to handle it.

**Negation and context.** "No chest pain" is not a chest pain complaint. "Chest pain resolved" is not an active complaint. But a classifier trained on word presence will happily assign both to "Chest Pain" unless you teach it otherwise. This is less of a problem than in full clinical notes (because people rarely present to an ED to report symptoms they don't have), but it does come up in telephone triage and nurse hotline contexts.

**Institutional vocabulary drift.** The abbreviations and phrasing patterns used at your institution in 2020 may differ from 2024. New staff bring conventions from their previous employers. Training data goes stale.

**Low-frequency categories.** If "Chest Pain" has 10,000 training examples and "Testicular Torsion" has 47, your classifier will be excellent at chest pain and terrible at testicular torsion. Class imbalance is a fundamental challenge, and in healthcare, the rare categories are often the ones where misclassification has the highest clinical consequence.

### Where the Field Is Now

Chief complaint classification is a well-studied problem. The literature goes back to the early 2000s, and the techniques have matured significantly:

- Pre-trained clinical NLP models (like those trained on MIMIC-III notes) provide embeddings that understand medical terminology out of the box
- Transfer learning lets you start with a model that already knows "SOB" is medical, then fine-tune on your institution's specific patterns
- Active learning workflows let you strategically label the examples where your classifier is least confident, rather than labeling randomly
- Ensemble approaches (run multiple classifiers, take the majority vote or highest confidence) improve robustness without much added complexity

<!-- TODO (TechWriter): Expert review A2 (HIGH). The 50,000 examples claim earlier in this section and the 1,000-per-category minimum in Prerequisites are inconsistent for a 150-category system. Reconcile: either note that 50K examples across fewer high-frequency categories achieves 85-92% on those categories while long-tail categories underperform, or adjust the total corpus guidance to 100K-200K for full category coverage. -->

The practical state of the art for a well-trained, institution-specific model is 88-95% top-1 accuracy, with top-3 accuracy (correct category is in the top three predictions) often exceeding 97%. That's good enough for automated routing with a confidence threshold: high-confidence predictions route automatically, low-confidence ones go to a human.

## General Architecture Pattern

```text
[Raw Text Input] → [Preprocessing] → [Vectorization] → [Classification] → [Confidence Gate] → [Route or Queue]
```

**Preprocessing:** Lowercase the input. Expand known abbreviations using an institution-specific lookup table. Remove extraneous punctuation. Handle misspellings (optional: a medical spell-checker or edit-distance lookup against known terms).

**Vectorization:** Convert the cleaned text into a numerical representation. Options range from TF-IDF (sparse, fast, interpretable) to sentence embeddings (dense, semantic, slightly slower). For a production system processing thousands of classifications per hour, the latency difference between these approaches is negligible.

**Classification:** A supervised model trained on historical labeled data. The training data is your institution's existing chief complaint entries paired with whatever category they were ultimately routed to (or manually coded to). You need at minimum a few thousand labeled examples, and ideally tens of thousands.

**Confidence Gate:** The classifier outputs a confidence score alongside its prediction. Set a threshold (typically 80-90% for healthcare routing). Below that threshold, the prediction goes to a human reviewer or defaults to the broadest applicable category rather than making an unsupported routing decision.

**Route or Queue:** High-confidence predictions feed directly into downstream systems (triage protocols, analytics databases, capacity dashboards). Low-confidence predictions enter a review queue for manual classification.

The feedback loop is critical: every human correction to a low-confidence prediction becomes new training data. Over time, the model gets better at exactly the edge cases it was initially unsure about.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter08.01-architecture). The Python example is linked from there.

## The Honest Take

This is genuinely one of the most satisfying NLP problems to solve in healthcare because the feedback loop is so tight. You build the classifier, deploy it, and within a day you can see whether it's routing correctly. The wins are immediate and visible: fewer misroutes, faster triage, cleaner analytics.

The abbreviation map is where you'll spend more time than you expect. Every institution has its own dialect. "SOB" is universal, but you'll discover abbreviations you've never seen before in the first week of reviewing low-confidence predictions. Build tooling to surface unrecognized tokens from the preprocessing step. Treat the abbreviation map as a living dictionary that grows from real usage.

The confidence threshold is your primary operational lever. Start at 85% and measure your auto-route accuracy for two weeks. If accuracy is above 95% for auto-routed predictions, you can safely lower the threshold. If it's below 90%, raise it. The right threshold depends on the downstream cost of misclassification at your institution. Misrouting a cardiac chest pain to a non-urgent track is worse than sending a "mild headache" to human review unnecessarily.

The thing that surprised me: training data quality matters far more than model sophistication. A simple logistic regression trained on 50,000 clean, correctly-labeled examples will outperform a fancy transformer trained on 10,000 noisy labels where half the historical routings were themselves incorrect. Spend your time on data quality, not model architecture.

Retraining cadence matters too. Quarterly retraining picks up vocabulary drift (new abbreviations, changing documentation patterns from staff turnover). Monthly is better if you have the automation. The model should always be learning from its own corrections.

---

## Related Recipes

- **Recipe 8.2 (Patient Sentiment Analysis):** Uses similar text classification patterns but for a different task (sentiment vs. category); shares preprocessing infrastructure
- **Recipe 8.4 (Medication Extraction and Normalization):** Demonstrates entity extraction from clinical text, a complementary NLP capability that can enrich chief complaint processing
- **Recipe 8.8 (Clinical Assertion Classification):** Handles the negation and assertion challenges that affect chief complaint classification at scale
- **Recipe 7.4 (ED Visit Prediction):** Consumes classified chief complaints as features for predicting ED utilization patterns

---

## Tags

`nlp` · `text-classification` · `chief-complaint` · `triage` · `comprehend` · `comprehend-medical` · `simple` · `mvp` · `lambda` · `dynamodb` · `sqs` · `hipaa` · `real-time`

---

*← [Chapter 8 Index](chapter08-preface) · [Next: Recipe 8.2 - Patient Sentiment Analysis →](chapter08.02-patient-sentiment-analysis)*
