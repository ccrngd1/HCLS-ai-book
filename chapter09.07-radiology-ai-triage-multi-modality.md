# Recipe 9.7: Radiology AI Triage (Multi-Modality) 🏥

**Complexity:** Complex · **Phase:** Production · **Estimated Cost:** ~$0.50-$2.00 per study

---

## The Problem

A radiologist at a mid-size hospital reads somewhere between 50 and 100 studies per shift. CT heads, chest X-rays, abdominal MRIs, spine CTs. They arrive in the worklist in the order they were completed by the scanner. First in, first out. No intelligence. No prioritization.

Buried in that queue might be a CT head showing a large epidural hematoma. The patient is in the ED, deteriorating. The neurosurgeon needs the read to proceed with evacuation. But the study is sitting at position 47 in the worklist because it happened to arrive after a batch of routine outpatient knee MRIs. The radiologist won't get to it for another 90 minutes at current pace.

This is not a hypothetical. Delayed reads on critical findings are a well-documented source of patient harm in radiology. The ACR (American College of Radiology) has published guidelines on critical result communication precisely because the problem is so common. The issue is not that radiologists are slow. They're fast. The issue is that the worklist has no concept of clinical urgency. It treats a screening mammogram and a trauma CT with the same priority.

Multi-modality radiology AI triage solves this by running inference on incoming studies across CT, MRI, and X-ray, detecting critical findings (pneumothorax, intracranial hemorrhage, pulmonary embolism, cervical spine fracture, aortic dissection), and bumping those studies to the top of the worklist. The radiologist still reads everything. The AI just changes the order. Triage, not diagnosis.

The "multi-modality" part is what makes this genuinely hard. A chest X-ray model and a head CT model are completely different architectures trained on completely different data. Unifying them into a single triage system that integrates cleanly with the radiologist's existing workflow (PACS, RIS, worklist) is an engineering challenge that goes well beyond training a good model.

---

## The Technology: How AI Reads Medical Images

### Deep Learning for Medical Imaging

Medical imaging AI is built on convolutional neural networks (CNNs) and, increasingly, vision transformers. The core idea: take a medical image (or volume, in the case of CT/MRI), pass it through a deep neural network, and produce a classification or detection output. "Is there a pneumothorax in this chest X-ray?" "Where is the hemorrhage in this CT head?"

The models are trained on large annotated datasets where radiologists have labeled thousands of images with ground truth findings. The network learns to associate pixel patterns with clinical findings. After training, it can process a new, unseen image and produce a prediction with an associated confidence score.

For 2D modalities (X-ray), this is relatively straightforward: a single image goes in, a classification comes out. For 3D modalities (CT, MRI), the input is a volume of hundreds of slices. The model needs to reason across the entire volume, not just individual slices. This is computationally heavier and architecturally different. 3D CNNs, 2.5D approaches (processing adjacent slices together), and slice-level aggregation are all common strategies.

### The Multi-Model Challenge

Here's the thing that makes multi-modality triage fundamentally different from single-finding detection: you're not running one model. You're running many.

A typical multi-modality triage system might include:

- Chest X-ray: pneumothorax, large pleural effusion, tension pneumothorax, widened mediastinum
- CT Head: intracranial hemorrhage (epidural, subdural, subarachnoid, intraparenchymal), midline shift, mass effect
- CT Chest (PE protocol): pulmonary embolism, aortic dissection
- CT Spine: cervical fracture, unstable spine injury
- CT Abdomen: free air (perforation), large AAA

Each of these is a separate model (or a multi-task model trained on that specific modality). They have different input requirements, different preprocessing pipelines, different inference times, and different performance characteristics. Orchestrating all of them behind a single triage interface is the engineering problem.

### DICOM and the Imaging Ecosystem

Medical images live in DICOM format (Digital Imaging and Communications in Medicine). DICOM is not just an image format; it's a communication protocol, a metadata standard, and a workflow specification all in one. Every study that comes off a scanner is a collection of DICOM objects containing pixel data plus rich metadata: patient demographics, study description, modality, body part, acquisition parameters, referring physician, accession number.

The triage system needs to:
1. Receive DICOM studies as they're produced by scanners
2. Route each study to the appropriate model based on modality and body part
3. Run inference
4. Communicate results back to the radiologist's worklist

That last step is the integration challenge. Radiologists work in PACS (Picture Archiving and Communication System) and read from a worklist managed by the RIS (Radiology Information System). The triage system needs to modify worklist priority without disrupting the radiologist's existing workflow. This typically happens via HL7 messages or DICOM worklist modifications, depending on the PACS vendor.

### What Makes This Hard (Beyond the Models)

**Modality routing.** When a study arrives, the system needs to determine which model(s) to run. A "CT Chest" might need both the PE model and the pneumothorax model. A "CT Head and Neck" might need the head hemorrhage model and the cervical spine model. Routing logic based on DICOM metadata (Modality, StudyDescription, BodyPartExamined) sounds simple until you encounter the wild inconsistency of how technologists populate these fields across different sites and scanner vendors.

**Preprocessing variability.** A CT from a GE scanner and a CT from a Siemens scanner have different pixel spacing, different reconstruction kernels, different windowing defaults. The model expects normalized input. Your preprocessing pipeline needs to handle this variability without manual configuration per scanner.

**Latency constraints.** Triage is only useful if it happens fast. If the AI takes 20 minutes to process a study, the radiologist has already read past it. Target: results within 5 minutes of study completion, ideally under 2 minutes. For a CT with 500+ slices, that's a meaningful compute requirement.

**False positive management.** A triage system that cries wolf loses trust immediately. If the AI bumps 30% of studies to "critical" priority, radiologists will ignore it within a week. False positive rates need to be extremely low (under 5%) for the system to maintain clinical trust. This often means setting confidence thresholds conservatively, which trades sensitivity for specificity.

**FDA regulatory pathway.** In the US, radiology AI triage products are regulated as medical devices. Most are cleared through the 510(k) pathway as Class II devices. Each clinical indication (pneumothorax detection, ICH detection, PE detection) typically requires its own clearance. You cannot just train a model and deploy it. The regulatory pathway adds 12-18 months and significant cost per indication.

**Integration with existing workflow.** Radiologists are creatures of habit (reasonably so; their workflow is optimized for throughput). A triage system that requires them to check a separate screen, log into a different application, or change their reading pattern will fail. The priority change must appear natively in their existing worklist. This means deep integration with the specific PACS/RIS vendor at each site.

### The General Architecture Pattern

```text
[Scanner] → [DICOM Router] → [Study Classifier] → [Model Selector] → [Inference Engine(s)]
                                                                              ↓
[Worklist Manager] ← [Priority Aggregator] ← [Finding Consolidator] ← [Model Results]
```

**DICOM Router:** Receives studies from scanners via DICOM C-STORE. Buffers until the study is complete (all series received). Forwards to the classifier.

**Study Classifier:** Examines DICOM metadata to determine modality, body part, and protocol. Decides which model(s) are applicable.

**Model Selector:** Maps the classified study to one or more inference models. Handles the case where a single study needs multiple models (e.g., CT chest needs both PE and pneumothorax models).

**Inference Engine(s):** Runs the actual deep learning models. Each model has its own preprocessing pipeline (windowing, resampling, normalization) and its own inference runtime. GPU-accelerated for CT/MRI volumes.

**Finding Consolidator:** Collects results from all models that ran on a given study. Deduplicates findings. Assigns severity scores.

**Priority Aggregator:** Translates findings into a worklist priority. "Intracranial hemorrhage with midline shift" = STAT. "Small pleural effusion" = routine. The mapping from findings to priority levels is clinically defined and site-configurable.

**Worklist Manager:** Communicates the priority back to the RIS/PACS. This is the integration point that varies most across deployments.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter09.07-architecture). The Python example is linked from there.

## The Honest Take

Multi-modality radiology AI triage is one of those systems where the ML is actually the easy part. Training a good ICH detector or pneumothorax classifier is well-understood. The hard parts are everything around the model: DICOM integration, worklist modification, PACS vendor cooperation, FDA clearance per indication, and (most importantly) radiologist trust.

The false positive problem is existential for these systems. I've seen deployments where the AI flagged 15-20% of studies as "urgent" in the first week. Radiologists ignored it by day three. You need to be ruthlessly conservative with your confidence thresholds at launch. It's better to miss a few true positives initially and build trust than to flood the worklist with false alarms and lose credibility permanently.

The PACS integration is where projects die. Every PACS vendor (GE, Philips, Siemens, Fuji, Sectra, Agfa) has a different integration model. Some have open APIs. Some require custom HL7 interfaces. Some require you to go through their marketplace. Budget 3-6 months just for the integration work at each site, and don't assume what worked at Hospital A will work at Hospital B even if they run the same PACS.

FDA clearance is non-negotiable for clinical deployment in the US. Each indication (ICH, PE, pneumothorax) is typically a separate 510(k) submission. The regulatory timeline is 12-18 months per indication. If you're building this in-house rather than buying a cleared product, factor that into your roadmap. Most health systems buy rather than build for this reason.

The thing that surprised me most: radiologists actually like these systems when they work well. The resistance is not to AI triage conceptually. It's to bad implementations that generate noise. Get the false positive rate below 5% and integrate cleanly into the existing worklist, and adoption follows naturally.

---

## Related Recipes

- **Recipe 9.1 (Image Quality Assessment):** Run quality checks before inference to avoid wasting GPU cycles on non-diagnostic images
- **Recipe 9.5 (Chest X-Ray Triage):** Single-modality version of this pattern; simpler starting point for teams new to radiology AI
- **Recipe 9.6 (Diabetic Retinopathy Screening):** Another FDA-regulated imaging AI use case with similar regulatory considerations
- **Recipe 14.3 (Radiology Worklist Optimization):** Complementary recipe covering non-AI worklist optimization (scheduling, load balancing)
- **Recipe 12.10 (Physiological Waveform Analysis):** Similar real-time inference pattern applied to continuous monitoring data

---
