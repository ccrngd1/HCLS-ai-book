<!-- Removed from chapter13.10-federated-clinical-knowledge-network.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Federated knowledge graphs are one of those ideas that everyone in health IT agrees is important and almost nobody has successfully deployed at scale. The technical challenges are real but solvable. The governance challenges are where projects go to die.

The thing that surprised me most: ontology alignment is not a one-time project. It's a continuous process. Clinical vocabularies evolve. Institutions change their data models. New concepts emerge (think about how quickly COVID-related terminology appeared and stabilized). If you treat the ontology layer as "set it and forget it," your federation will silently degrade over months as mappings drift out of alignment.

The performance question is also more nuanced than it appears. For batch research queries ("what does the network know about treatment X across all populations?"), 5-second latency is fine. For point-of-care clinical decision support ("should I prescribe this drug to this patient right now?"), it's unacceptable. Most successful deployments I've seen use a hybrid approach: federated queries populate a local cache of frequently-accessed knowledge, and the cache serves real-time requests. The federation runs in the background to keep the cache fresh.

The political dimension cannot be overstated. Getting three health systems to agree on a shared ontology is a multi-year effort involving committees, working groups, and a lot of meetings. Getting them to actually expose query endpoints and trust each other's access control is another multi-year effort. Start with a narrow, high-value use case (drug interactions are the classic starting point) and expand from there. Don't try to federate everything at once.

One more thing: the "competitive advantage" concern is real but often overstated. Most clinical knowledge is not proprietary. Drug interactions are drug interactions. The value institutions protect is usually patient-derived insights (treatment outcomes for specific populations), not the underlying clinical facts. A well-designed sharing policy can expose the non-sensitive knowledge broadly while protecting the truly proprietary stuff. But you have to have that conversation explicitly with each institution's leadership.

---

