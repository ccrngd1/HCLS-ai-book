<!-- Removed from chapter09.08-pathology-slide-analysis.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Pathology AI is one of those fields where the research papers look incredible and the production deployments are still rare. The accuracy numbers in controlled studies are genuinely impressive. But the gap between "works on TCGA data" and "works in your lab on your scanner with your pathologists" is wider than most people expect.

Stain normalization is the thing that will humble you first. Your model achieves 96% AUC on your development data, you deploy it, and the first lab that sends slides stained slightly differently sees performance drop to 85%. The Macenko or Reinhard normalization methods help, but they're not magic. You need diverse training data from multiple labs and scanners.

The compute cost surprised me. When you're processing 30,000 patches per slide and your lab generates 200 slides per day, you're looking at 6 million inference calls daily. That's real GPU spend. Batch inference with preemptible or spot capacity helps, but you need to architect for cost from day one.

The regulatory piece is non-trivial. If your system makes any claim that influences diagnosis (even "regions of interest" that a pathologist might interpret as "the AI thinks this is cancer"), you're likely in FDA territory. The distinction between "clinical decision support" and "diagnostic device" is nuanced and evolving. Get regulatory counsel early.

The part that works better than expected: pathologist acceptance. Unlike radiology AI (where radiologists sometimes feel threatened), pathologists are generally enthusiastic about AI assistance. The workload pressure is real, the subspecialty shortage is acute, and the technology genuinely helps them work faster on routine cases so they can spend more time on the hard ones.

---

