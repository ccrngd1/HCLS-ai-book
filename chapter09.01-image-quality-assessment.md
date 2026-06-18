# Recipe 9.1: Image Quality Assessment ⭐

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.01 per image

---

## The Problem

A radiologist opens their worklist at 7 AM. Forty-three studies queued overnight. They pull up the first chest X-ray and immediately see it: the patient moved during acquisition. The image is blurred, the mediastinal borders are indistinct, and there's no way to confidently rule out a small pneumothorax. They reject it. Retake ordered. The patient has already gone home.

Now multiply that across a health system. Radiology departments reject somewhere between 3% and 10% of imaging studies for quality reasons, depending on the modality and patient population. Pediatric studies are worse (kids move). Emergency department studies are worse (patients are in pain, positioning is rushed). Each rejected image means a repeat exposure (more radiation dose to the patient), a scheduling disruption, a delayed diagnosis, and wasted technologist time.

The frustrating part: most quality problems are detectable the instant the image is acquired. A blurred image is blurred immediately. An underexposed X-ray is underexposed immediately. A CT slice with motion artifact has motion artifact immediately. But the technologist is already positioning the next patient, and the radiologist won't see the study for hours. By the time anyone notices the quality problem, the opportunity for an immediate retake is gone.

This is a problem that computers can solve faster than humans, with less fatigue, and at the point of acquisition where it actually matters. Automated image quality assessment catches bad images before they leave the modality, while the patient is still on the table and a retake costs thirty seconds instead of a return visit.

---

## The Technology: How Computers Judge Image Quality

### What "Quality" Means in Medical Imaging

Image quality in medical imaging is not the same as image quality in photography. A technically beautiful photograph can be a clinically useless medical image, and vice versa. Medical image quality is defined by diagnostic adequacy: can a clinician extract the information they need to make a decision?

The quality criteria are modality-specific:

For **chest X-rays**, quality means: adequate inspiration (you can count at least 9 posterior ribs above the diaphragm), proper exposure (you can see the thoracic spine through the cardiac silhouette but the lung fields aren't washed out), correct positioning (the spinous processes are midline between the clavicular heads), and no motion blur.

For **CT scans**, quality means: no motion artifact (sharp organ boundaries), appropriate window/level settings, complete anatomical coverage, and consistent slice thickness.

For **clinical photographs** (wound photos, dermatology images), quality means: adequate lighting, proper focus, appropriate framing, and a reference marker for scale when measurement is needed.

The common thread: each modality has a set of measurable properties that correlate with diagnostic utility. And most of those properties can be computed from the pixel data alone.

### The Two Approaches: Rules vs. Learning

There are fundamentally two ways to assess image quality automatically.

**Rule-based (traditional image processing).** You define explicit metrics and thresholds. Blur is measured by the variance of the Laplacian operator (a mathematical filter that responds to edges; blurry images have low edge response). Exposure is measured by histogram analysis (the distribution of pixel intensities should fall within expected ranges). Positioning is measured by detecting anatomical landmarks and checking their spatial relationships. This approach is interpretable, predictable, and requires no training data. It works well for simple, well-defined quality criteria. It struggles with subtle or context-dependent quality issues.

**Learned (deep learning).** You train a convolutional neural network on thousands of images labeled as "acceptable" or "reject" by radiologists. The model learns whatever features distinguish good images from bad ones, including subtle patterns that are hard to express as explicit rules. This approach handles complex, multi-factor quality assessment better than rules. It requires labeled training data (which you probably already have in your PACS rejection logs). It's less interpretable: the model might reject an image without a clear explanation of why.

In practice, the best systems combine both. Rule-based checks catch the obvious failures fast (completely black image, completely white image, wrong body part). A learned model handles the nuanced cases (subtle motion blur, borderline exposure, positioning that's technically acceptable but suboptimal).

### The Metrics That Matter

Regardless of approach, you're computing some combination of these:

**Sharpness / blur detection.** The Laplacian variance is the classic metric. Compute the second derivative of the image (which highlights edges), then measure the variance of the result. High variance means lots of sharp edges (good). Low variance means everything is smooth (blurry). The threshold depends on the modality and resolution. You'll need to calibrate per imaging device.

**Exposure / brightness.** Histogram analysis tells you whether the image uses the full dynamic range appropriately. An underexposed image clusters pixel values at the low end. An overexposed image clusters at the high end. For X-rays specifically, you want to see the characteristic bimodal distribution: one peak for soft tissue, one for bone/air.

**Noise estimation.** Medical images always have some noise (it's inherent to the physics of image acquisition). The question is whether noise exceeds acceptable levels. Noise estimation typically involves analyzing homogeneous regions of the image where you expect uniform intensity. The standard deviation in those regions approximates the noise floor.

**Anatomical completeness.** Is the entire region of interest captured? For a chest X-ray, are both costophrenic angles visible? For a knee MRI, is the entire joint included? This requires either landmark detection (find specific anatomical points and verify they're all present) or a learned model trained on properly framed vs. improperly framed images.

**Artifact detection.** Metal artifacts in CT, zipper artifacts in MRI, grid lines in X-rays, patient jewelry or clothing in the field of view. Each artifact type has characteristic patterns that can be detected either by rules (periodic patterns for grid lines) or by learned models (metal streak patterns).

### Why This Is Actually Hard (Despite Being "Simple")

I called this recipe "simple" in the chapter overview, and it is, relative to diagnostic AI. But there are real challenges:

**Threshold calibration is site-specific.** A blur threshold that works for a brand-new digital radiography system will reject everything from an older computed radiography unit. Exposure norms differ between manufacturers. You cannot ship a universal threshold configuration and expect it to work everywhere. Plan for per-device or per-modality calibration.

**"Acceptable" is subjective.** Two radiologists will disagree on whether a borderline image is adequate. Your training data (if using a learned model) inherits this subjectivity. The same image might be acceptable for ruling out a fracture but inadequate for evaluating subtle interstitial lung disease. Quality is context-dependent.

**Speed matters more than accuracy.** The whole point is catching bad images while the patient is still on the table. If your assessment takes 30 seconds, the technologist has already moved on. You need sub-second inference. This constrains model complexity.

**False positives are expensive.** If your system flags too many images as "poor quality," technologists will start ignoring it. The boy-who-cried-wolf problem is real in clinical workflows. A 5% false positive rate on a system processing 500 images per day means 25 unnecessary alerts daily. That's enough to kill adoption.

### The General Architecture Pattern

```text
[Image Acquisition] → [Quality Assessment] → [Pass/Fail Decision] → [Alert or Archive]
```

**Image Acquisition.** A DICOM image arrives from the modality (X-ray machine, CT scanner, MRI, ultrasound, or a camera for clinical photography). In most hospital environments, images flow through a DICOM router or a vendor-neutral archive (VNA) before reaching the PACS. Your quality assessment system taps into this flow.

**Quality Assessment.** The image is analyzed against quality criteria. This might be a single model that outputs a quality score, a pipeline of individual metric computations (blur, exposure, noise, completeness), or a combination. The output is a structured quality report: overall pass/fail, individual metric scores, and confidence levels.

**Pass/Fail Decision.** A decision engine applies thresholds to the quality scores. This is where the business logic lives: what constitutes "acceptable" for this modality, this body part, this clinical context? The thresholds should be configurable without redeploying the model.

**Alert or Archive.** If the image passes, it flows to the PACS normally. If it fails, an alert goes to the technologist (ideally at the modality console) with specific feedback: "Image rejected: motion blur detected. Recommend retake." The failed image is still archived (you never discard medical images), but it's flagged so the radiologist knows a retake was requested.

The key architectural decision: where in the imaging chain do you insert the assessment? Closer to the modality means faster feedback but requires edge compute. At the PACS/VNA level means simpler deployment but the patient may have left. The ideal is at the modality or the DICOM router, with sub-second latency.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter09.01-architecture). The Python example is linked from there.

## The Honest Take

This is one of those problems where the technology is genuinely ready but the deployment is harder than the ML. The model itself is straightforward: binary classification on images with clear labels (your PACS already tracks rejections). Training takes a few days. Inference is fast. The accuracy is good enough.

The hard parts are all operational:

**Getting the training data out of your PACS.** Radiology departments track rejections, but the data is often in a proprietary system with no clean export path. You'll spend more time on data extraction than on model training. Budget for it.

**Calibrating thresholds per site.** What I said earlier about site-specific calibration is not optional. I've seen systems that worked beautifully at one hospital and rejected 40% of images at another because the equipment was older and the baseline noise floor was higher. Plan for a calibration phase at every deployment site.

**Technologist trust.** If the system rejects images that the technologist thinks are fine, they'll stop trusting it within a week. Start with a "shadow mode" where the system assesses images but doesn't alert anyone. Compare its decisions against actual radiologist rejections for a month. Only go live when the agreement rate is high enough that technologists see it as helpful, not annoying.

**The feedback loop problem.** Once you deploy the system and technologists start retaking flagged images, your rejection rate drops. Great. But now your model's training data (historical rejections) no longer represents the current distribution of quality problems. The model needs periodic retraining on the new failure modes that slip through.

The part that surprised me: the biggest ROI is not in radiology. It's in clinical photography. Wound care photos, dermatology images, dental radiographs. These are taken by non-imaging-specialists (nurses, medical assistants) with consumer-grade cameras, and the quality variance is enormous. A simple blur-and-exposure check on clinical photos catches more actionable problems than a sophisticated model on radiologist-acquired X-rays.

---

## Related Recipes

- **Recipe 9.2 (Patient Photo Verification):** Uses similar image preprocessing but for identity matching rather than quality scoring
- **Recipe 9.4 (Dermatology Lesion Triage):** Depends on image quality assessment as a prerequisite; poor-quality photos should be caught before triage
- **Recipe 9.5 (Chest X-Ray Triage):** Quality assessment is a natural upstream step; only route quality-adequate images to the diagnostic AI
- **Recipe 3.7 (Patient Deterioration Early Warning):** Demonstrates a similar pattern of real-time scoring with configurable alert thresholds

---

## Tags

`computer-vision` · `medical-imaging` · `quality-assessment` · `image-processing` · `sagemaker` · `dicom` · `radiology` · `simple` · `mvp` · `lambda` · `s3` · `dynamodb` · `hipaa`

---

*← [Chapter 9 Index](chapter09-preface) · [Next: Recipe 9.2 - Patient Photo Verification →](chapter09.02-patient-photo-verification)*
