<!-- Removed from chapter01.04-prior-auth-document-processing.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The keyword classifier that shipped with the original version of this recipe worked well. Really, it did. 85 to 92% accuracy on real prior auth submissions is respectable for a few hundred lines of dictionary lookups.

The moment it stopped being good enough was the day someone handed me a prior auth submission from a regional plan whose cover sheet used "Service Requested Code" instead of "CPT Code" and "Dx Indication" instead of "Diagnosis Code." The keyword classifier classified it as "other." The entire submission sat in the review queue. No automation. Manual processing, same as before.

You can fix that specific case by adding those labels to the dictionary. You can fix the next case the same way. Eventually you have a very large dictionary and someone on your team whose near full-time job is maintaining it as payer templates evolve. That's the maintenance burden the LLM eliminates.

The "aha moment" with LLM classification is surprisingly mundane. You send a page to the model, and it just... knows what it is. The physician letter from a small rural clinic using a non-standard template that would have stumped the keyword classifier? "physician_letter, confidence 0.94, reasoning: this page is a formal letter from a treating physician documenting failed conservative treatments and requesting authorization for a specific surgical procedure." No dictionary. No template matching. The model understood what it was reading.

That experience recalibrates your intuition about what's worth automating with an LLM versus a specialized service. Page classification: yes, absolutely. Lab values from a structured table: no, Textract handles that better and cheaper. The model tiering concept is how you apply that intuition systematically rather than making it up case by case.

Now for the cost shock, because I promised honesty. Go calculate what Sonnet 4.6 costs at 500,000 submissions per year with 4 clinical pages each: 500,000 × 4 × $0.015 per page = $30,000 per year for the Sonnet step alone. That sounds like a lot until you compare it to a single clinical reviewer FTE at $150,000-$200,000 fully loaded. The pipeline is still a bargain. But the number is real, and it will land in your AWS bill.

Model tiering is how you make that number smaller. Nova Lite for classification is effectively free at any realistic volume. Haiku 4.5 instead of Sonnet 4.6 for less complex narrative pages cuts the per-page cost by 70%. Prompt caching on the repeated classification system prompt cuts input costs by 90%. These are not hypothetical optimizations. They are the difference between a $30K/year LLM budget and an $8K/year one.

The architectural principle that carries forward: Textract extracts structure. LLMs reason about it. Comprehend Medical validates codes. Each service does what it was built for. That combination is what the rest of Chapter 1 builds on.

---

