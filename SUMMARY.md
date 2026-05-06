# Healthcare AI/ML Cookbook — Project Brief

## What This Is

An O'Reilly-style technical cookbook covering AI/ML applications in healthcare. 15 chapters, ~10 recipes each (~150 total recipes). Each recipe teaches a specific healthcare AI use case with architecture patterns, pseudocode, and Python companion code.

## Current Status

- **Chapter 1 (Document Intelligence / OCR): COMPLETE** — 10 recipes written, reviewed, and edited
- **Chapters 2-15: NOT STARTED** — planning docs exist in `categories/` and `planning/`

## Structure

### Per Recipe (2 files)
1. **Main recipe** (`chapterNN.RR-name.md`) — Problem → Technology (vendor-agnostic) → General Architecture → AWS-specific implementation
2. **Python companion** (`chapterNN.RR-python-example.md`) — Working boto3 code with generous comments

### Per Chapter
- Chapter preface (`chapterNN-preface.md`)
- Chapter index (`chapterNN-index.md`)

### Pipeline Per Recipe
1. TechWriter drafts main recipe
2. TechWriter drafts Python companion
3. TechCodeReviewer reviews code (writes to `reviews/`)
4. TechExpertReviewer reviews recipe (writes to `reviews/`)
5. TechEditor polishes final version

## Chapters

| # | Category | Recipes | Planning Doc |
|---|----------|---------|--------------|
| 1 | Document Intelligence / OCR | 10 | DONE |
| 2 | LLM / Generative AI | 10 | categories/02-llm-generative.md |
| 3 | Anomaly Detection | 10 | categories/03-anomaly-detection.md |
| 4 | Personalization / Recommendation | 10 | categories/04-personalization.md |
| 5 | Entity Resolution / Record Linkage | 10 | categories/05-entity-resolution.md |
| 6 | Cohort Analysis / Clustering | 10 | categories/06-cohort-clustering.md |
| 7 | Predictive Analytics / Risk Scoring | 10 | categories/07-predictive-analytics.md |
| 8 | NLP (Non-LLM) | 10 | categories/08-nlp-traditional.md |
| 9 | Computer Vision / Medical Imaging | 10 | categories/09-computer-vision.md |
| 10 | Speech / Voice AI | 10 | categories/10-speech-voice.md |
| 11 | Conversational AI / Virtual Assistants | 10 | categories/11-conversational-ai.md |
| 12 | Time Series Analysis / Forecasting | 10 | categories/12-time-series.md |
| 13 | Knowledge Graphs / Ontology | 10 | categories/13-knowledge-graphs.md |
| 14 | Optimization / Operations Research | 10 | categories/14-optimization.md |
| 15 | Reinforcement Learning | 10 | categories/15-reinforcement-learning.md |

## Writing Rules

- Follow STYLE-GUIDE.md for voice and tone
- Follow RECIPE-GUIDE.md for structure and formatting
- 70% vendor-agnostic, 30% AWS-specific
- No em dashes. Ever.
- No fake GitHub URLs. Only verified links.
- No documentation-voice. Write like an engineer explaining something cool.
- All recipes assume HIPAA compliance context

## Target Audience

Mixed: executives, architects, engineers, product managers. Main recipes accessible to non-coders. Python companions for developers.

## Reference Files

- `STYLE-GUIDE.md` — Voice, tone, vendor balance rules
- `RECIPE-GUIDE.md` — Full recipe structure specification
- `categories/*.md` — Recipe titles and descriptions per chapter
- `planning/*.md` — Detailed planning and complexity analysis
- `chapter01.*` — Completed Chapter 1 as reference for quality/style
- `reviews/chapter01.*` — Example reviews showing expected review format
