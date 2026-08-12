<!-- Removed from chapter09.10-multi-modal-imaging-fusion-analysis.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Multi-modal fusion is one of those areas where the research papers make everything look solved and the clinical deployment reality is humbling. The BraTS challenge has driven brain tumor segmentation performance to levels that compete with expert radiologists. But BraTS data is curated: images are already skull-stripped, co-registered, and resampled to the same grid. In a real clinical pipeline, you're starting from raw DICOM off the scanner, and the preprocessing and registration steps are where most of the failures live.

The registration quality problem deserves special attention. I've seen fusion pipelines deployed where the registration "passed" automated quality checks but was subtly wrong (3-4mm error in a critical region). The downstream segmentation model happily produced plausible-looking contours that were shifted from the true anatomy. Nobody noticed until a physicist spotted the misalignment during treatment plan review. Build multiple layers of quality assessment, and make human review of registration quality a mandatory step before clinical use.

The temporal mismatch problem is underappreciated in the literature. Research datasets typically have all modalities acquired on the same day. Clinical reality is that the PET was last Tuesday, the MRI was yesterday, and the CT is being done today for planning. In that two-week gap, the tumor grew 2mm along one margin. Your "perfect" registration is now aligning a slightly different anatomy, and there's no good automated way to detect or correct for this.

The cost model is dominated by GPU compute for registration and inference. If you're processing 50 studies per day, a dedicated GPU instance makes more economic sense than on-demand inference endpoints. If it's 5 studies per day, the on-demand model wins. The crossover point depends on your instance type and your cloud provider's pricing tier.

One last thing that surprised me: DICOM-RT Structure Set generation is harder than it should be. Converting a 3D segmentation mask back into the contour-per-slice format that treatment planning systems expect requires careful handling of slice geometry, multi-part contours (holes, separate components), and coordinate system conventions. Budget more engineering time here than you think you'll need.

---

