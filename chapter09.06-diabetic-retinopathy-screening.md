# Recipe 9.6: Diabetic Retinopathy Screening

**Effort:** 4 of 5 · **Maturity:** Proven · **Oversight:** Every output

---

## The Problem

There are about 40 million people with diabetes in the United States. Every single one of them should get an annual dilated eye exam to check for diabetic retinopathy, the leading cause of blindness in working-age adults. The actual screening rate? Somewhere around 60%. That means roughly 15 million diabetic patients in the US alone are not getting their eyes checked on schedule.

The reasons are depressingly predictable. Patients with diabetes already have a dozen appointments to manage: endocrinology, primary care, podiatry, lab work. Adding an ophthalmology visit (which may require pupil dilation, meaning you can't drive home, meaning you need someone to take you) is the one that falls off the list. Rural patients may not have an ophthalmologist within 50 miles. And even when patients do show up, the ophthalmology workforce is stretched thin. There simply aren't enough retinal specialists to screen every diabetic patient annually.

Diabetic retinopathy is treatable if caught early. Laser photocoagulation and anti-VEGF injections can prevent vision loss in the vast majority of cases. But the window matters. By the time a patient notices vision changes, the disease has often progressed to a stage where treatment is less effective. The entire value proposition of screening is catching it before symptoms appear.

So the question becomes, can you bring the screening to the patient instead of bringing the patient to the specialist? Can a primary care clinic, a pharmacy, or even a mobile health unit capture a retinal image and get a reliable severity grade without a fellowship-trained ophthalmologist in the room?

The answer, as of the last few years, is yes. And the technology behind it is genuinely fascinating.

---

## The Technology: How Machines Grade Retinal Images

### Fundus Photography

Before we talk about AI, let's talk about the image itself. A fundus photograph is a picture of the back of the eye (the retina) taken through the pupil. Traditional fundus cameras require pharmacological dilation (those annoying drops that blur your vision for hours). Newer non-mydriatic cameras can capture usable images without dilation, which removes the single biggest barrier to patient participation.

The resulting image shows the optic disc, the macula, blood vessels, and (if present) the pathological features of diabetic retinopathy: microaneurysms, hemorrhages, hard exudates, cotton wool spots, neovascularization, and vitreous hemorrhage. A trained ophthalmologist can look at this image and grade the severity on a standardized scale.

### The Grading Scale

The International Clinical Diabetic Retinopathy (ICDR) severity scale is the standard:

- **No apparent retinopathy:** Clean retina, no lesions
- **Mild non-proliferative (NPDR):** Microaneurysms only
- **Moderate NPDR:** More than just microaneurysms but less than severe
- **Severe NPDR:** Extensive hemorrhages, venous beading, intraretinal microvascular abnormalities (IRMA)
- **Proliferative diabetic retinopathy (PDR):** Neovascularization (new blood vessel growth), the dangerous stage

For screening purposes, the critical decision is binary: does this patient need a referral to ophthalmology, or can they safely wait until their next annual screen? Generally, moderate NPDR and above triggers referral. Mild NPDR gets monitored. No retinopathy gets a "see you next year."

### Deep Learning for Retinal Image Classification

This is a classic image classification problem, and deep learning has gotten remarkably good at it. 

1. **Training data:** Tens of thousands of fundus images, each graded by multiple ophthalmologists (to establish ground truth consensus). Public datasets like EyePACS and Messidor-2 have been instrumental in research. Clinical deployments use proprietary datasets that are much larger.

2. **Architecture:** Convolutional neural networks (CNNs), typically based on architectures like Inception, ResNet, or EfficientNet. The network learns to identify the visual features that distinguish each severity grade. Some systems use attention mechanisms to highlight which regions of the image drove the classification (useful for explainability).

3. **Output:** A severity grade (matching the ICDR scale) plus a confidence score. Some systems also output a referral recommendation (refer/don't refer) as a separate binary classification, which simplifies the clinical workflow.

4. **Performance:** The landmark studies (Google's 2016 JAMA paper, the IDx-DR FDA trial) demonstrated sensitivity and specificity comparable to or exceeding individual ophthalmologists. We're talking 87-97% sensitivity for referable diabetic retinopathy, depending on the system and the operating threshold.

### Why This Is Harder Than It Sounds

**Image quality variation.** Non-mydriatic cameras in primary care settings produce images of wildly varying quality. Small pupils, media opacities (cataracts), patient movement, and operator inexperience all degrade image quality. A system that works beautifully on research-grade images from a retinal clinic may struggle with the noisy, off-center, poorly-focused images from a busy family medicine practice. You need a robust image quality assessment gate before classification.

**The "ungradable" problem.** Some percentage of images (5-20% depending on the population and camera) are simply too poor to grade. The system needs to say "I can't tell" rather than guessing. This is not a failure mode to hide; it's a safety feature. An ungradable result means "dilate and try again" or "refer for in-person exam."

**Population bias.** Models trained predominantly on one demographic may underperform on others. Retinal pigmentation varies across ethnicities, and some pathological features are harder to detect against darker fundus backgrounds. This is an active area of research and a real equity concern for screening programs targeting diverse populations.

**Diabetic macular edema (DME).** Retinopathy grading alone isn't sufficient. DME (swelling of the macula due to fluid leakage) can occur at any retinopathy severity level and independently threatens vision. A complete screening system needs to detect DME as well, which is a separate classification task often requiring different image features (or OCT imaging, which is a different modality entirely).

**Regulatory requirements.** This is not a "nice to have" AI feature. In the US, autonomous diagnostic AI for diabetic retinopathy requires FDA clearance (De Novo or 510(k) pathway). The IDx-DR system (now Digital Diagnostics) was the first to receive FDA clearance for autonomous AI diagnosis in 2018. If you're building a screening system that makes referral decisions without physician oversight, you're in FDA territory. If you're building a "pre-screening" or "triage" tool where a physician still reviews, the regulatory path is different but still exists.

---

## General Architecture Pattern

```text
[Image Capture] → [Quality Assessment] → [Classification Model] → [Clinical Decision] → [Integration]
```

**Image Capture:** A fundus camera (non-mydriatic for screening programs) captures one or more images per eye. The capture device may be operated by a trained technician, a medical assistant, or (in some programs) a pharmacist. Images are typically DICOM format but may also be JPEG/PNG from simpler devices.

**Quality Assessment:** Before classification, assess whether the image is gradable. Check for adequate field of view, focus, illumination, and absence of artifacts. Reject ungradable images immediately with instructions to recapture. This gate prevents false negatives from poor images.

**Classification Model:** The core deep learning model ingests the fundus image and outputs a severity grade (ICDR scale) plus confidence scores. May also output DME presence/absence. Some systems process multiple images per eye and aggregate predictions for robustness.

**Clinical Decision:** Map the model output to a clinical action: no referral needed, routine follow-up recommended, or urgent referral required. Apply confidence thresholds: if the model is uncertain, route to human review rather than making an autonomous decision.

**Integration:** Results flow back to the ordering system (EHR), the patient, and (if referral is triggered) the ophthalmology scheduling system. The complete audit trail (image, model version, prediction, confidence, clinical decision) must be retained for regulatory compliance and quality assurance.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter09.06-architecture). The Python example is linked from there.

## The Honest Take

**Buy versus build: do not build this one.** For diabetic retinopathy specifically, you probably shouldn't build this at all. DR screening is the most commercially mature medical-imaging AI there is. It was the first autonomous diagnostic AI the FDA ever cleared, back in 2018. Several cleared products already exist, including LumineticsCore (formerly IDx-DR) and Eyenuk's EyeArt, plus camera-integrated options like the Optomed Aurora AEYE that ship the AI inside a handheld fundus camera. These vendors have already absorbed the two hardest and most expensive parts of building this: FDA clearance and the years of clinical validation behind it. Be careful about what that does and does not transfer. A cleared device puts product liability for a defective device on its manufacturer. It does not move your liability for the care decision: who acts on the result, who follows up on a positive, and what happens when a referral is generated and never completed all stay with the clinicians and the organisation operating the pathway. Buying removes development risk, not accountability. Unless you have an unusual population, camera, or workflow the cleared products don't cover, the right move is to buy, not build. Your value isn't training a model, it's choosing the right system, integrating it into the care pathway, handling ungradables, and monitoring for drift. Read this recipe as a guide to evaluating and operating one of these systems intelligently, not a mandate to build your own from scratch.

The model accuracy numbers from clinical trials are real, but they were achieved under controlled conditions with trained photographers using specific camera models. When you deploy in a busy primary care clinic where a medical assistant with 30 minutes of training is operating the camera, your ungradable rate will be higher than the published literature suggests. Budget for 15-20% recapture rates in the first few months until operators build proficiency.

The FDA clearance question is the one that shapes everything else. If your system makes autonomous referral decisions (no physician reviews the image), you need FDA clearance. Period. If a physician reviews every result before it reaches the patient, you're in a different regulatory category, but you've also eliminated much of the efficiency gain. The sweet spot for most health systems is "AI reads first, physician confirms," which reduces ophthalmologist workload substantially while keeping a physician in the loop. Be precise about what that buys you, though: it changes which regulatory regime you are operating under, it does not exempt you from one, and it makes the compliance question different rather than simpler. Which regime applies, and what it asks of you, is a question for your own regulatory and legal teams.

Model drift is a real concern, even though it isn't obvious. Retinal cameras get updated. Patient populations shift. New camera operators join. Your model's performance will degrade over time if you're not actively monitoring it. Build a continuous monitoring pipeline that tracks sensitivity and specificity against a gold-standard reading panel. When performance drops below your validated thresholds, you need a retraining or recalibration pathway.

The business case has a nearer-term component than it used to, and the reason is a billing code. CPT 92229, introduced in January 2021, covers retinal imaging with point-of-care automated analysis, which is precisely what an autonomous screening program does. The screening is therefore directly billable rather than justified entirely by cost avoided years later. Two cautions before you build a forecast on it. The code is carrier-priced rather than paid off a national fee schedule, so what you collect depends on your Medicare carrier and your commercial contracts, and it has moved since the code appeared; take that number from your own payer mix rather than from a book. And billing 92229 does not by itself close the HEDIS eye-exam measure for patients with diabetes, because the code records that imaging happened, not what it found. If quality-measure performance is part of your justification, and it usually is, the program has to capture and report the retinopathy result as well as the image.

The rest of the return still takes years to arrive. It comes from preventing blindness, which reduces long-term care costs, and from capturing screening revenue previously lost to patient non-compliance. Health systems that succeed with diabetic retinopathy screening treat it as a population health investment with a reimbursement floor, not as a short-term revenue generator.

Lastly, the patients who most need screening (uncontrolled diabetes, multiple comorbidities, limited access to care) are also the patients whose images are hardest to grade (small pupils from autonomic neuropathy, cataracts from metabolic disease). The technology works best on the patients who need it least. Design your program with this paradox in mind.

---

**Two regulatory notes, and their limits.** First, the Section 1557 final rule issued in 2024, with its patient-care decision support provisions phasing in during 2025, prohibits discrimination in health programs and reaches tools that use protected characteristics as inputs or perform unevenly across them. That is the legal backdrop to the per-cohort accuracy work described above, and a reason to treat disparity monitoring as load-bearing rather than optional. Second, if you are buying a cleared device, ask the vendor whether it carries an FDA Predetermined Change Control Plan and what that plan covers, because a PCCP is the mechanism that lets a manufacturer ship certain model updates without a new marketing submission, and it shapes how the product you deployed will change underneath you. Neither point is compliance guidance. Both are questions to take to your legal and compliance teams before you sign anything.

## Related Recipes

- **Recipe 9.1 (Image Quality Assessment):** The quality gate in this recipe is a specialized application of the general image quality assessment pattern
- **Recipe 9.4 (Dermatology Lesion Triage):** Similar triage-vs-diagnosis regulatory considerations and confidence gating patterns
- **Recipe 9.5 (Chest X-Ray Triage):** Shares the worklist prioritization pattern and FDA regulatory pathway considerations
- **Recipe 7.8 (Disease Progression Modeling):** The longitudinal tracking variation connects to temporal disease modeling
- **Recipe 4.6 (Care Gap Prioritization):** DR screening compliance is a classic care gap; this recipe's output feeds gap closure workflows

---

## Tags

`classification` · `computer-vision` · `cnn` · `medical-imaging` · `population-health` · `fda-pathway` · `sagemaker`

---

## Navigation
