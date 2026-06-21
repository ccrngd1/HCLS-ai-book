# Physical Book Plan & Main-Third Finalization

Status: **DRAFT — pending selection sign-off**
Last updated: 2026-06-20 (added section 2c: Mermaid pre-render decision)

## 1. Vision

- **Digital (EPUB/HTML) is the canon.** The full 152-recipe, 3-file cookbook (story / architecture / python) lives online and stays the mainstay. Size is not a constraint there — readers search and jump.
- **A physical book is the flagship artifact** — a giftable object that feels real. It carries a curated **subset** of the *story third only* (Part 1: the Problem, the Technology, the general architecture, the Honest Take). AWS implementation detail stays digital.
- **Sequence:** decide the 15 flagship use cases → finalize *those 15* first → publish the physical book → then work through the rest of the main third.

## 2. Strategy decisions (locked)

- **Format:** ~15 recipes, one marquee per capability chapter → ~275 print pages (6x9 trade paperback). Lean flagship over a 2-per-chapter brick.
- **Print = story third only.** Architecture + python stay digital; print callouts point readers to the digital edition.
- **Publishing path:** print-on-demand. Amazon KDP (simplest) or IngramSpark (better wholesale/bookstore reach). Generate a print-specific 6x9 PDF from the selected Markdown.
- **Tightening applies to the main third regardless of medium.** Dense prose is a problem online too. But it is targeted, not uniform (see §5).

## 2b. Print as a derived artifact: the cross-reference transform (added 2026-06-18)

The print edition is a **derived artifact built from the canonical source**, the same way the HTML and EPUB variants are. The canonical recipe files are never edited for print; a build step takes a copy and applies print-specific transforms. This keeps the digital edition's cross-references valid (the full book has all 152 recipes) while making the print subset self-contained.

**Why this is needed:** the flagship is a breadth sampler (one recipe per chapter), so a recipe's intra-chapter cross-references almost never resolve in print. Example: recipe 2.5 references 2.1, 2.2, 2.4, 2.6, 2.8, and 11.x, but only 11.6 is in the flagship-15. As-is, the printed recipe would point to pages that do not exist.

**Print-build cross-reference transforms (applied to a copy, uniformly across all flagship recipes):**

1. **Strip the navigation footer** (`← Recipe N · Recipe N →`) entirely. It is web sequential navigation and is meaningless in a 15-recipe book.
2. **Reframe the "Related Recipes" section** into a short pointer to the digital edition rather than a list of absent recipes, for example: *"In the full digital cookbook, this recipe connects to patient-message drafting, prior-auth letter generation, and ambient documentation. See [digital edition]."* This removes dangling references and doubles as a hook back to the canon.
3. **Rewrite inline `Recipe N.N` mentions to describe the concept**, dropping the number: "unlike Recipe 2.1, which handles one-off messages" becomes "unlike one-off patient messaging." Where a referenced recipe IS also a flagship, renumber it to its print chapter instead of removing it.
4. (Also in this pass, per Phase C) rewrite the architecture-companion callout to point at the digital edition, and add print front/back matter.

**Implementation note:** this is a transform in the print pipeline (canonical Markdown -> print-adapted Markdown -> 6x9 PDF), parallel to the HTML/EPUB builders. It must be deterministic and re-runnable, and it must never write back to the canonical files. The set of "flagship recipes present in print" is the input that drives the renumber-vs-remove decision for each cross-reference.

## 3. Flagship-15 selection (PROPOSED — needs sign-off)

One marquee recipe per chapter, chosen for broad relatability and self-containedness. `HEAVY` = >=7,000 words (needs real tightening); `lean` = already in good shape.

| Ch | Capability | Recipe | Words | State |
|----|-----------|--------|-------|-------|
| 1 | Document Intelligence | 1.1 Insurance Card Scanning | 1,753 | lean — **author-approved 2026-06-18** |
| 2 | Clinical Text Generation | 2.5 After-Visit Summary Generation | 4,026 | **author-approved 2026-06-18** (S2/L21/L25 resolved) |
| 3 | Anomaly & Outlier Detection | 3.1 Duplicate Claim Detection *(pilot)* | 3,964 | **author-approved 2026-06-18** |
| 4 | Recommendation & Personalization | 4.9 Personalized Care Plan Generation | 4,981 | **author-approved 2026-06-20** (tightened from 8,575; deps reframed) |
| 5 | Entity Resolution & Record Linkage | 5.1 Internal Duplicate Patient Detection | 6,115 | lean |
| 6 | Clustering & Patient Segmentation | 6.4 Disease Severity Stratification | 2,015 | lean |
| 7 | Predictive Risk Modeling | 7.5 30-Day Readmission Risk | 2,958 | lean |
| 8 | Clinical NLP & Information Extraction | 8.3 ICD-10 Code Suggestion | 2,351 | lean |
| 9 | Medical Imaging & Computer Vision | 9.6 Diabetic Retinopathy Screening | 1,801 | lean |
| 10 | Speech & Voice AI | 10.7 Ambient Clinical Documentation | 12,335 | **HEAVY** |
| 11 | Conversational AI & Virtual Agents | 11.6 Symptom Checker / Triage Bot | 12,938 | **HEAVY** |
| 12 | Forecasting & Time-Series Analysis | 12.5 Hospital Census Forecasting | 4,244 | lean |
| 13 | Knowledge Graphs & Clinical Reasoning | 13.4 Drug-Drug Interaction Knowledge Base | 2,451 | lean |
| 14 | Optimization & Resource Allocation | 14.4 Nurse Staffing Optimization | 2,246 | lean |
| 15 | Sequential Decision-Making & RL | 15.4 Sepsis Treatment Optimization | 2,237 | lean |

**Finalization load for the flagship batch: only 4 heavy tightens + 11 light cleanups.** Selection is swappable — pick a different recipe per chapter if a stronger showcase exists.

## 4. Per-recipe finalization rubric

Every flagship recipe must clear all four before it is "print-ready":

1. **Tighten (heavy recipes):**
   - CUT: duplicated enumerations (same point in The Problem *and* The Honest Take), list-of-lists where only 2-3 items matter, hedging/throat-clearing, ASCII diagrams that belong in the companion.
   - PROTECT: the opening scene/story, the core insight, the Honest Take thesis and voice, the read-write/safety arguments.
   - TARGET: <=~6,000 words (~13 pages) where content allows. No forced floor; never cut below what the recipe needs. Leave lean recipes (<3k) alone.
2. **Resolve review scaffolding:** address or remove leftover `<!-- Expert review … -->` / `TODO (TechWriter)` HTML comments (76 files book-wide carry them; invisible to readers but represent unresolved feedback). HIGH items get addressed; the rest removed.
3. **Move vendor specifics off main:** AWS service mentions in prose (~48 files) move to the architecture companion. The story file stays vendor-agnostic.
4. **Print adaptation:** rewrite the "see architecture companion" callout to point at the digital edition; strip web-only nav footers; ensure it reads standalone in print.

## 5. The 41 heavy recipes (book-wide tightening backlog)

For the *later* full-book pass, after the physical book ships. The median recipe is only ~2,900 words and is left untouched; the bloat is this fat tail. Sorted by length (priority). Concentrated in ch11 (8), ch10 (9), ch05 (7), ch03 (5), ch04 (5).

| # | Recipe | Words | In flagship-15 |
|---|--------|-------|----------------|
| 1 | 11.9 Care Coordination Assistant | 15,101 | |
| 2 | 11.8 Mental Health Support Bot | 13,051 | |
| 3 | 11.7 Chronic Disease Management Coach | 12,977 | |
| 4 | 11.6 Symptom Checker / Triage Bot | 12,938 | ✅ |
| 5 | 10.7 Ambient Clinical Documentation | 12,335 | ✅ |
| 6 | 3.10 Epidemic / Outbreak Detection | 12,020 | |
| 7 | 10.10 Multilingual Real-Time Medical Interpretation | 11,775 | |
| 8 | 10.6 Speech-to-Text Telehealth Documentation | 11,729 | |
| 9 | 11.4 Pre-Visit Intake Bot | 11,531 | |
| 10 | 3.9 Cybersecurity / Access Pattern Anomalies | 11,507 | |
| 11 | 10.5 Patient-Facing Voice Assistant | 11,203 | |
| 12 | 5.10 Deceased Patient Resolution & Reconciliation | 10,847 | |
| 13 | 5.8 Privacy-Preserving Record Linkage | 10,817 | |
| 14 | 5.9 National-Scale Patient Matching | 10,803 | |
| 15 | 11.5 Insurance Benefits Navigator | 10,751 | |
| 16 | 3.7 Patient Deterioration Early Warning | 10,502 | |
| 17 | 11.3 Prescription Refill Request Bot | 10,326 | |
| 18 | 4.10 Dynamic Treatment Regime Recommendation | 10,099 | |
| 19 | 11.2 Appointment Scheduling Bot | 9,861 | |
| 20 | 4.6 Care Gap Prioritization | 9,721 | |
| 21 | 10.4 Medical Transcription / Dictation | 9,716 | |
| 22 | 10.8 Voice Biomarker Detection | 9,537 | |
| 23 | 5.7 Longitudinal Patient Matching (Name Changes) | 9,425 | |
| 24 | 5.6 Claims-to-Clinical Data Linkage | 9,417 | |
| 25 | 11.1 FAQ Chatbot | 9,239 | |
| 26 | 4.7 Care Management Program Enrollment | 8,907 | |
| 27 | 10.3 Voice-to-Text EHR Navigation | 8,868 | |
| 28 | 4.9 Personalized Care Plan Generation | 8,575 | ✅ |
| 29 | 3.5 Lab Result Outlier Detection | 8,464 | |
| 30 | 10.9 Speech Therapy Assessment & Monitoring | 8,339 | |
| 31 | 10.2 Voicemail Transcription & Classification | 8,328 | |
| 32 | 3.6 Healthcare Fraud, Waste & Abuse Detection | 8,316 | |
| 33 | 11.10 Clinical Trial Recruitment Conversationalist | 8,208 | |
| 34 | 4.8 Treatment Response Prediction | 8,142 | |
| 35 | 5.5 Cross-Facility Patient Matching | 7,793 | |
| 36 | 3.8 Readmission Risk Anomaly Detection | 7,714 | |
| 37 | 5.4 Insurance Eligibility Matching | 7,646 | |
| 38 | 5.3 Address Standardization & Household Linkage | 7,353 | |
| 39 | 2.5 After-Visit Summary Generation | 7,283 | ✅ |
| 40 | 2.9 Clinical Decision Support Synthesis | 7,110 | |
| 41 | 10.1 IVR Call Routing Enhancement | 7,052 | |

## 6. Phased plan

- **Phase A — Lock selection.** Confirm/adjust the flagship-15 (§3).
- **Phase B — Finalize the 15.** Apply the §4 rubric. Pilot the tightening on the 4 heavy ones (2.5, 4.9, 10.7, 11.6) by hand for sign-off, then light cleanup on the other 11. Higher editorial bar than the web polish run.
- **Phase C — Print pipeline.** `print/` manifest of the 15; 6x9 PDF build path; front matter (title, copyright, preface, how-to-use, URL/QR to the digital edition) + back matter (index, "137 more recipes online"). Includes the cross-reference transform (see section 2b).
- **Phase D — Publish.** KDP or IngramSpark.
- **Phase E — Book-wide tightening.** Work the 41-recipe backlog (§5) via a ralph run (TechEditor edits, TechExpertReviewer enforces rubric), independent/parallel, plus scaffolding + vendor cleanup across the broader corpus.

## 6b. Finding-resolution overnight run (added 2026-06-18)

Pilot (`ch02-r05-findings`, recipe 2.5) ran 2026-06-18 and passed: TechWriter resolved 21 findings (0 open + 3 deferred as `[NEEDS HUMAN]`), TechExpertReviewer validated, fixes verified real (S1 SMS-to-portal-link, S3 IAM ARN scoping, N1 VPC endpoints). Design is proven; the batch is ready to scale to the remaining ~145 recipes.

**Mechanism:** per-recipe task (one per recipe, not per finding), TechWriter resolves the findings listed in `chapterNN.RR-todo.md`, TechExpertReviewer validates. Items needing an external citation or an author decision are deferred in the todo file prefixed `[NEEDS HUMAN]`. Improves the digital edition only (flagship main files are already clean).

**To launch (from the book root):**

```bash
# 1. Generate the remaining ~145 finding-resolution tasks from the -todo.md files
python3 gen_finding_tasks.py

# 2. Pre-clean stale worktrees
rm -rf /tmp/ralph-worktrees; git worktree prune; git branch | grep ralph/worker | xargs -r git branch -D

# 3. Launch (opus-4.6, concurrency 4 from ralph.config.json, 16h cap)
/mnt/c/Users/lawsnic/OneDrive\ -\ amazon.com/Documents/projects/kiro-ralph-loop/.venv/bin/ralph run \
  --model claude-opus-4.6 --wall-clock-timeout-ms 57600000 --max-iterations 500
```

**Morning-after checklist:**
- Review deferrals: `grep -l 'NEEDS HUMAN' chapter*-todo.md` then read each.
- Rebuild HTML and confirm warnings == baseline (2 RECIPE-GUIDE placeholders).
- Spot-check a few high-stakes recipes (HIPAA/security findings) for correctness.
- All per-task changes are git-committed and reversible (`ralph rollback <N>` or `git revert`).

**Helpers (committed):** `check_findings.py` (guardrail), `gen_finding_tasks.py` (batch generator), `specs/ch02-r05-findings.md` (proven template).

## 2c. Diagram rendering: Mermaid pre-render shared across outputs (added 2026-06-20)

The book currently mixes **~150 Mermaid blocks** (rendered client-side by the bundled `mermaid.min.js` in the HTML build) and **~277 ASCII `text` diagrams**. Client-side rendering works for HTML but NOT for EPUB (unreliable JS in e-readers) or print PDF (static only).

**Decision:** add a single **Mermaid pre-render step** to the build that scans `.md` files for ```mermaid blocks, renders each to an **SVG asset once**, and has all three outputs (HTML, EPUB, print PDF) embed the same image. This parallels how the HTML variant is generated today: one shared transform feeding multiple outputs.

- **Tooling:** `@mermaid-js/mermaid-cli` (`mmdc`, official, Puppeteer/headless-Chromium) for fidelity, OR **Kroki** (self-hosted via Docker, or hosted) to avoid a local Chromium dependency. Both output SVG/PNG/PDF.
- **Per medium:**
  - HTML: keep client-side rendering as-is, or switch to the pre-rendered SVG for consistency/perf.
  - EPUB: embed pre-rendered SVG/PNG (no client JS).
  - Print PDF: embed pre-rendered SVG (vector, crisp at 6x9).
- **Required regardless of the ASCII question:** the ~150 existing Mermaid diagrams render only in HTML today; they would be blank in EPUB/print without this step.
- **Follow-on cleanup:** convert the ~277 ASCII `text` diagrams to Mermaid to unify rendering and dramatically improve print quality (the compact 4.9 pipeline is a trivial `graph TD`). Mechanical for most; do it incrementally.
- **Sequencing:** build the pre-render step as part of Phase C (EPUB/print pipelines). It is a deterministic, re-runnable transform that never edits canonical files (writes image assets to the build output only).

## 7. Open decisions

1. Confirm the flagship-15 (any swaps?).
2. Page-count comfort: stay lean ~275 pp, or add a 2nd recipe for a few marquee chapters to bulk toward ~350 pp?
3. KDP vs IngramSpark (or both).
4. Should the 4 heavy flagship recipes be tightened before or in parallel with the print-pipeline setup?
