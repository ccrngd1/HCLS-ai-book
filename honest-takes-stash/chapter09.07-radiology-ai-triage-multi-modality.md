<!-- Removed from chapter09.07-radiology-ai-triage-multi-modality.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Multi-modality radiology AI triage is one of those systems where the ML is actually the easy part. Training a good ICH detector or pneumothorax classifier is well-understood. The hard parts are everything around the model: DICOM integration, worklist modification, PACS vendor cooperation, FDA clearance per indication, and (most importantly) radiologist trust.

The false positive problem is existential for these systems. I've seen deployments where the AI flagged 15-20% of studies as "urgent" in the first week. Radiologists ignored it by day three. You need to be ruthlessly conservative with your confidence thresholds at launch. It's better to miss a few true positives initially and build trust than to flood the worklist with false alarms and lose credibility permanently.

The PACS integration is where projects die. Every PACS vendor (GE, Philips, Siemens, Fuji, Sectra, Agfa) has a different integration model. Some have open APIs. Some require custom HL7 interfaces. Some require you to go through their marketplace. Budget 3-6 months just for the integration work at each site, and don't assume what worked at Hospital A will work at Hospital B even if they run the same PACS.

FDA clearance is non-negotiable for clinical deployment in the US. Each indication (ICH, PE, pneumothorax) is typically a separate 510(k) submission. The regulatory timeline is 12-18 months per indication. If you're building this in-house rather than buying a cleared product, factor that into your roadmap. Most health systems buy rather than build for this reason.

The thing that surprised me most: radiologists actually like these systems when they work well. The resistance is not to AI triage conceptually. It's to bad implementations that generate noise. Get the false positive rate below 5% and integrate cleanly into the existing worklist, and adoption follows naturally.

---

