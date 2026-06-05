---
id: ch07-r12-draft
title: 'Draft: Cohort Matching and Case-Based Reasoning for Novel Claims'
target_persona: TechWriter
tags:
- chapter07
- recipe
- draft
depends_on:
- ch07-preface
validation:
- type: file_exists
  name: output-file-exists
  paths:
  - chapter07.12-claim-cohort-matching.md
- type: shell
  name: auto-fix-style
  commands:
  - python3 fix_style.py chapter07.12-claim-cohort-matching.md
- type: persona_review
  name: quality-review
  persona: TechEditor
  pass_condition: Recipe includes The Problem, The Technology, General Architecture
    Pattern, AWS Implementation with pseudocode walkthrough, The Honest Take, Variations,
    and navigation links. Prose matches project voice with no em dashes.
---


## Objective
Draft the recipe for Cohort Matching and Case-Based Reasoning for Novel Claims.

## Instructions
Write a complete recipe covering similarity-based / instance-based prediction
of claim and prior-authorization determinations, as a complement to the
supervised classifier in Recipe 7.11. The motivating scenario is a middleman
or clearinghouse that processes heterogeneous claims across many payers, does
NOT know the payers' decision rules, and frequently sees claims that do not
exactly match anything in its history.

Make the relationship to 7.11 explicit and honest:
- 7.11 (XGBoost/LightGBM) is the primary predictor and is more accurate when
  there is dense, representative training history for the payer/procedure.
- This recipe addresses what gradient-boosted trees do poorly: novelty / out
  of distribution detection, case-based explanation, and cold start on payers
  with little or no history.

Cover at minimum:
- The Problem: heterogeneous claim streams, novel payer + procedure-code
  combinations, the danger of a tree model's overconfident score on inputs it
  never saw, and the middleman's need to justify a prediction with comparable
  resolved cases.
- The Technology (vendor-agnostic): clarify the distinction between
  k-nearest-neighbors / similarity retrieval (find the k most similar past
  claims and look at their outcomes) and clustering (k-means style partitioning
  into denial archetypes for routing/segmentation). Cover feature similarity
  vs learned embeddings, distance metrics, and how distance-to-neighbors gives
  a confidence / novelty signal that XGBoost lacks.
- Using nearest-neighbor distance as an out-of-distribution flag that routes
  low-confidence or novel claims to human review.
- Cold start: similarity to other payers' claims works on day one when a
  supervised model cannot be trained yet.
- The hybrid pattern: gradient-boosted primary score + nearest-neighbor
  similarity layer for novelty detection, case-based explanation, and cold
  start; clustering for operational denial-archetype segmentation.
- General architecture and an AWS implementation: building an embedding /
  feature vector for each claim, a vector index for similarity search (for
  example OpenSearch k-NN or a managed vector store), and batch plus real-time
  retrieval, with a pseudocode walkthrough.
- The Honest Take: kNN sensitivity to feature scaling and the curse of
  dimensionality, that "similar inputs" does not guarantee "same payer
  decision," index freshness and drift, the same fairness/bias cautions as
  7.11, and that this complements rather than replaces the supervised model.
- Variations, Related Recipes (link to 7.11 claim denial prediction, 6.x
  clustering recipes, 5.x record-matching/similarity recipes), and navigation
  links.

Match the voice and structure of the other Chapter 7 recipes.
