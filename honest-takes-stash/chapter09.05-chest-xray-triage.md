<!-- Removed from chapter09.05-chest-xray-triage.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Chest X-ray triage AI is one of the most mature applications of medical imaging AI. The research is extensive, the datasets are large, the regulatory pathway is established, and multiple commercial products exist. If you're going to deploy medical imaging AI anywhere, this is a reasonable place to start.

That said, here's what will surprise you:

**Alert fatigue is the killer.** A 10% false positive rate sounds acceptable in a research paper. In practice, if a radiologist gets 20 false alarms for every true critical finding, they'll start ignoring the alerts within a week. Specificity matters more than sensitivity for clinical adoption. A missed finding is bad; a system that cries wolf constantly is useless.

**The PACS integration is harder than the AI.** Getting a model to detect pneumothorax is a solved problem. Getting that detection to actually reorder a worklist in your specific PACS installation, with your specific HL7 interface engine, with your specific radiologist workflow preferences, is a 3-month integration project. Every site is different.

**Model validation on your data is non-negotiable.** Published performance numbers from CheXpert or MIMIC-CXR will not match your performance. Your patient population is different. Your equipment is different. Your image quality is different. Budget for a prospective validation study on at least 1,000 studies from your institution before going live.

**The regulatory question is real.** If you're building this in-house (not buying a commercial product), you're building a medical device. That means FDA 510(k) clearance, a Quality Management System, design controls, risk analysis, and post-market surveillance. This is 12-18 months of regulatory work on top of the technical build. Most health systems buy rather than build for this reason.

**Radiologists are not the enemy.** The most successful deployments involve radiologists from day one: choosing thresholds, reviewing false positives, providing feedback on edge cases. The worst deployments are IT-driven projects that surprise radiologists with a new system on Monday morning.

---

