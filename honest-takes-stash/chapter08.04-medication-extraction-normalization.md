<!-- Removed from chapter08.04-medication-extraction-normalization.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Medication NER is one of those problems that's 85% solved out of the box and then the remaining 15% takes 85% of your effort. The managed services are genuinely good at extracting common medications with standard sig codes. "Metformin 500mg PO BID" is basically a solved problem. It's the edge cases that will consume your time.

The RxNorm normalization step is where I've seen the most production issues. The normalization API returns candidates, but the top candidate isn't always correct. "Calcium 600mg" could normalize to calcium carbonate, calcium citrate, or half a dozen other calcium salts. Without additional context (which the patient was previously prescribed, what the formulary carries), you're guessing. Build your confidence thresholds conservatively and route ambiguous cases to pharmacy review.

The section detection might sound like a trivial preprocessing step, but it's actually load-bearing. I've seen systems that correctly extract "penicillin" as a medication from the allergies section and then add it to the active medication list because they didn't check context. That's not a theoretical concern. It happens, and it's dangerous.

The thing that surprised me most: the volume of medication mentions in a single note can be much higher than you'd expect. A discharge summary might mention 15-20 medications across current, discontinued, and allergy sections. Each one needs independent normalization. At roughly a penny per normalization call, that's $0.15-0.20 per note just for normalization. Plan your cost model around notes with many medications, not the average.

One more honest admission: most managed medical NER services impose a character limit per API call (typically 20,000 characters). Most individual notes fit within that. Lengthy operative reports or combined note bundles might not. You'll need chunking logic that respects sentence boundaries, and you'll need to handle medications that span a chunk boundary (rare, but it happens with long sig descriptions).

---

