# Recipe 9.4: Dermatology Lesion Triage

**Complexity:** Medium · **Phase:** Pilot · **Estimated Cost:** ~$0.08-$0.15 per image

---

## The Problem

There are roughly 3.5 billion people on Earth with access to a smartphone camera but not to a dermatologist. In the United States alone, the average wait time for a dermatology appointment is over 30 days. In rural areas, it can stretch past 90. For patients with a suspicious mole that changed shape last week, that wait is terrifying. For the ones whose lesion is actually melanoma, it's potentially deadly.

Primary care physicians see skin complaints constantly. They're the front line. But most PCPs have limited dermatology training, and the visual pattern recognition required to distinguish a benign seborrheic keratosis from an early melanoma is genuinely difficult. Studies have shown that PCP accuracy for melanoma detection ranges from 50% to 75%, depending on the study and the lesion type. That's not a criticism of PCPs. It's a recognition that dermatology is a visual specialty that takes years of focused training.

The result is a system that either over-refers (flooding dermatology clinics with benign lesions, extending wait times for everyone) or under-refers (missing early-stage cancers that would have been treatable if caught sooner). Neither outcome is acceptable.

What if you could put a triage layer between the initial photo and the dermatology referral? Not a diagnosis. Not a replacement for a dermatologist. A prioritization system that says: "This one looks suspicious, move it to the front of the queue" or "This one has features consistent with benign patterns, standard scheduling is appropriate." The dermatologist still makes the call. But the urgent cases get seen first.

That's what this recipe builds.

---

## The Technology: How Computers Classify Skin Lesions

### Image Classification for Dermatology

At its core, skin lesion triage is an image classification problem. You have an input image (a photograph of a skin lesion) and you want to assign it to one of several categories: benign, suspicious, or urgent. The underlying technology is a convolutional neural network (CNN) trained on labeled dermoscopic and clinical images.

CNNs work by learning hierarchical visual features. The early layers detect edges and color gradients. Middle layers combine those into textures and shapes. Deep layers recognize complex patterns like asymmetry, border irregularity, color variation, and structural features. These happen to align closely with the ABCDE criteria that dermatologists use for melanoma screening (Asymmetry, Border, Color, Diameter, Evolution), which is part of why deep learning has been surprisingly effective for this task.

The field has progressed rapidly. In 2017, a Stanford study published in Nature showed that a CNN could match board-certified dermatologists in classifying skin cancer from dermoscopic images. Since then, multiple studies have replicated and extended these results. The ISIC (International Skin Imaging Collaboration) has published large public datasets that have accelerated research. Models trained on these datasets can distinguish between dozens of diagnostic categories with performance comparable to specialists.

(A critical caveat: "comparable to specialists" in a controlled study with curated images is very different from "works reliably on a blurry phone photo taken in a bathroom mirror." We'll get to that.)

### Dermoscopic vs. Clinical Images

There's an important distinction between two types of skin lesion images:

**Dermoscopic images** are taken with a dermatoscope, a specialized magnifying device with polarized lighting that eliminates surface reflections and reveals subsurface structures. These images are high-quality, standardized, and show features invisible to the naked eye. Most published research uses dermoscopic images. Most trained models perform best on them.

**Clinical images** are regular photographs taken with a phone camera or digital camera. No special equipment. Variable lighting, variable distance, variable angle. Hair, shadows, skin folds, and background clutter are all present. These are what patients and PCPs actually produce in the real world.

The performance gap between models evaluated on dermoscopic images versus clinical images is significant. A model that achieves 90% sensitivity on dermoscopic images might drop to 70-80% on clinical photos. Any production system must be honest about which image type it was trained on and which it will receive in practice.

### Transfer Learning and Fine-Tuning

You don't train a skin lesion classifier from scratch. You start with a model pre-trained on millions of general images (ImageNet is the classic starting point), then fine-tune it on dermatology-specific datasets. This transfer learning approach works because the low-level visual features (edges, textures, color patterns) are universal. The model already knows how to "see." You're teaching it what to look for in skin lesions specifically.

Common base architectures include EfficientNet, ResNet, and Inception variants. The choice of base architecture matters less than the quality and diversity of your fine-tuning dataset. A well-curated training set with balanced representation across skin tones, lesion types, and image qualities will outperform a larger but biased dataset every time.

### The Skin Tone Problem

This is the elephant in the room, and it's not optional to discuss.

The vast majority of published dermatology training datasets are heavily skewed toward lighter skin tones (Fitzpatrick types I-III). The ISIC archive, which is the largest public dermoscopy dataset, is estimated to be over 80% light-skinned patients. This means models trained on these datasets perform measurably worse on darker skin tones (Fitzpatrick types IV-VI).

This isn't a theoretical concern. Melanoma on dark skin presents differently (often acral, on palms, soles, or nail beds rather than sun-exposed areas). The visual features the model learned from light-skinned training examples may not transfer. Published studies have documented sensitivity drops of 10-20 percentage points for darker skin tones.

Any responsible deployment must: (1) measure performance stratified by skin tone, (2) be transparent about known limitations, (3) actively seek diverse training data, and (4) never deploy a model that hasn't been validated across the patient population it will serve.

### Triage vs. Diagnosis

This distinction is critical and has regulatory implications.

**Triage** means prioritization. The system says "this lesion has features that warrant urgent review" or "this lesion has features consistent with benign patterns." It does not say "this is melanoma" or "this is a basal cell carcinoma." The dermatologist still makes the diagnosis.

**Diagnosis** means the system is making a clinical determination. This triggers FDA regulatory requirements. You'd be looking at the De Novo or 510(k) pathway, which is the world of Software as a Medical Device (SaMD).

The regulatory landscape is evolving. The FDA has cleared some dermatology AI products for specific diagnostic claims. But for a triage system that explicitly defers diagnosis to a specialist, the regulatory burden is lower (though not zero; consult regulatory counsel). The key is how you frame the output and what clinical decisions are made based on it.

### Model Explainability

A confidence score alone ("72% suspicious") doesn't tell the reviewing dermatologist much. What features drove that assessment? Was it asymmetry? Color variation? Border irregularity? Without explainability, the dermatologist has no reason to trust the prioritization, and a tool they don't trust is a tool they ignore.

Saliency maps (Grad-CAM or similar techniques) generate a heatmap showing which regions of the image most influenced the model's prediction. Overlaying this on the original lesion photograph gives the dermatologist actionable context: "The model focused on this irregular border region and this area of color variation." This is often the difference between a tool that gets adopted and one that gets bypassed.

For production systems, generate and store the saliency map alongside the original image in the review queue. The computational overhead is modest (one additional backward pass through the network) and the clinical adoption benefit is substantial.

### The General Architecture Pattern

```text
[Image Capture] → [Metadata Strip] → [Quality Check] → [Preprocessing] → [Classification Model] → [Confidence Scoring] → [Triage Routing] → [Dermatologist Review Queue]
```

**Image Capture:** A patient or clinician photographs the lesion. The capture interface should guide positioning, lighting, and distance. A reference marker (color card or ruler) is ideal but often impractical for patient-submitted photos.

**Metadata Strip:** Patient-submitted smartphone photos contain EXIF metadata including GPS coordinates, device serial numbers, and potentially the photographer's name. Strip this metadata before storage. GPS coordinates from a patient's home photo directly reveal their home address. Retain only clinically relevant metadata (timestamp, image dimensions) and discard location, device identifiers, and photographer information.

**Quality Check:** Before running inference, verify the image is usable. Is it in focus? Is the lesion visible and centered? Is there adequate lighting? Reject unusable images immediately with guidance on how to retake.

**Preprocessing:** Resize to model input dimensions. Normalize color channels. Optionally apply hair removal algorithms (yes, this is a real preprocessing step in dermatology AI; body hair obscures lesion borders). Crop to the region of interest if the full image contains significant background.

**Classification Model:** Run the preprocessed image through the trained CNN. The output is a probability distribution across categories (e.g., benign: 0.15, suspicious: 0.72, urgent: 0.13).

**Confidence Scoring:** The raw model output needs calibration. A model that says "72% suspicious" needs to actually be correct 72% of the time when it says that. Calibration is often poor out of the box and requires post-hoc adjustment on a held-out validation set.

**Triage Routing:** Based on the calibrated scores and predefined thresholds, route the case: urgent cases go to the front of the dermatology queue, suspicious cases get expedited scheduling, benign-appearing cases get standard follow-up recommendations.

**Dermatologist Review Queue:** Every case eventually reaches a dermatologist. The AI determines priority, not disposition. The queue interface should show the image, the model's assessment, confidence scores, saliency map, and any relevant patient history.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter09.04-architecture). The Python example is linked from there.

## The Honest Take

Here's what will surprise you when you actually build this:

**The model is the easy part.** Fine-tuning an EfficientNet on ISIC data to get 90% accuracy on a held-out test set takes a weekend. Getting clinicians to trust it, patients to use it correctly, and the organization to accept liability for it takes months to years.

**Photo quality is your real enemy.** In a research paper, every image is a perfectly lit, centered dermoscopic capture. In production, you'll get bathroom selfies with a phone flash creating a white hotspot directly on the lesion. Your quality gate will reject 15-25% of submissions, and users will be frustrated. Invest heavily in the capture UX: guides, overlays, real-time feedback on positioning and lighting.

**The skin tone bias is not something you can fix with a disclaimer.** If your model performs 15% worse on dark skin, deploying it with a footnote saying "results may vary" is not acceptable. Either acquire diverse training data and validate rigorously, or restrict deployment to populations where you've demonstrated adequate performance. This is an equity issue with real clinical consequences.

**Threshold tuning is a political process, not a technical one.** The dermatology department wants low false-positive rates (they're already overwhelmed). Patient safety advocates want high sensitivity (never miss a melanoma). Administration wants to demonstrate AI value. You'll spend more time in meetings about thresholds than you will training the model.

**Outcome tracking is essential but hard.** To know if your model is actually working, you need to close the loop: what did the dermatologist actually diagnose? Was the triage category correct? This requires integration with the dermatology workflow and a process for recording outcomes back to the triage record. Without it, you're flying blind.

**Regulatory is not optional.** Even for "triage only," the FDA's guidance on Clinical Decision Support software applies. If your system's output is intended to be acted upon without independent clinician review, it's likely a medical device. If a dermatologist always reviews every case regardless of the AI output, you have more flexibility. Document your intended use carefully and get regulatory counsel involved early.

---

## Related Recipes

- **Recipe 9.1 (Image Quality Assessment):** The quality validation step in this recipe is a simplified version of the full image quality assessment pattern
- **Recipe 9.3 (Wound Photography Measurement):** Shares the clinical photography capture challenges and preprocessing patterns
- **Recipe 9.5 (Chest X-Ray Triage):** Same triage-not-diagnosis framing applied to radiology; similar regulatory considerations
- **Recipe 9.6 (Diabetic Retinopathy Screening):** Another screening use case with FDA regulatory pathway; more mature regulatory precedent

---
