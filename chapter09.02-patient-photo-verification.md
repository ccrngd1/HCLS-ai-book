# Recipe 9.2: Patient Photo Verification

**Complexity:** Simple · **Phase:** MVP · **Estimated Cost:** ~$0.001 per verification

---

## The Problem

A patient walks into an urgent care clinic. They hand over an insurance card. The front desk confirms the name. They get routed to a room, seen by a provider, billed under that member ID. Except it's not their card. It belongs to a family member, a friend, someone they bought it from. The visit is documented under the wrong patient. The claim goes out with the wrong demographics. Medical history accumulates on the wrong person's chart.

Medical identity fraud costs the U.S. healthcare system an estimated $80 billion annually. But the numbers don't capture the real risk: a patient gets treated based on someone else's allergy list. A blood type mismatch goes unnoticed. A medication interaction isn't flagged because the EHR shows someone else's active prescriptions. Identity errors in healthcare aren't just billing problems. They're patient safety problems.

The traditional solution is manual verification: front desk staff glances at the person, glances at the name on the screen, maybe asks for a photo ID. This works when things are calm. It falls apart at 8:00 AM on a Monday when six people are waiting and the phone is ringing. It doesn't scale to telehealth, where the person on the video call could be anyone. It doesn't scale to kiosks, where there's no staff to look at anyone.

What if you could match a person's face to a photo already on file? Not as the only verification (that would be reckless), but as one signal in a broader identity confidence score. The technology exists and it's mature. The tricky part is deploying it in healthcare with all the ethical, regulatory, and bias considerations that entails.

---

## The Technology: How Face Comparison Works

### Face Detection vs. Face Comparison

Let's get the terminology straight, because this is where people get confused.

**Face detection** answers the question: "Is there a face in this image, and where is it?" The output is a bounding box. Detected face at coordinates (120, 85) to (340, 380). This is relatively straightforward. Modern face detection models use convolutional neural networks and are extremely reliable on frontal or near-frontal faces in decent lighting. They struggle with extreme angles, heavy occlusion (masks, for example), and very low resolution.

**Face comparison** (sometimes called face verification or face matching) answers a different question: "Are these two faces the same person?" You give it two images. It tells you whether the faces in those images belong to the same individual, along with a confidence score. This is a 1:1 comparison. You're not searching a database of millions of faces for a match (that's face search, or 1:N identification). You're comparing exactly two faces.

The distinction matters for healthcare identity verification. We're doing 1:1 comparison: does the person at check-in match the photo stored in their patient record? We're not building a surveillance system that identifies people in a crowd.

### How the Comparison Actually Works (Under the Hood)

Modern face comparison systems work in three stages:

**Stage 1: Face detection and alignment.** Find the face in each image. Normalize it: rotate to frontal pose, crop to face bounds, resize to a standard resolution. This alignment step is critical because it removes variation that has nothing to do with identity (head tilt, distance from camera, image dimensions).

**Stage 2: Feature extraction.** Pass the aligned face through a deep neural network (typically a variant of ResNet or a similar architecture trained specifically on facial recognition tasks). The network outputs a high-dimensional vector, usually 128 or 512 floating-point numbers. This vector is called a face embedding. It's a mathematical representation of the face's unique geometry: distance between eyes, nose bridge width, jawline shape, forehead proportions. The network has learned, through training on millions of face pairs, which geometric features are stable across lighting conditions, expressions, and minor aging, and which features are just noise.

**Stage 3: Similarity scoring.** Compare the two embedding vectors. The most common approach is cosine similarity: how much do these two vectors point in the same direction in high-dimensional space? If the cosine similarity is high (close to 1.0), the faces likely belong to the same person. If it's low (close to 0.0 or negative), they likely don't. The system returns this as a confidence percentage or similarity score.

The beauty of this approach is that the heavy computation happens once per image (stages 1 and 2). The actual comparison (stage 3) is just a dot product, which is nearly instant. Store the embedding from the enrollment photo, and subsequent verifications only need to compute the embedding of the new photo and compare.

### What Makes This Hard

Face comparison in a lab, with controlled lighting and cooperative subjects, achieves accuracy rates above 99.5%. Face comparison in a real healthcare setting introduces several complications:

**Aging.** A patient's photo on file might be 3 years old. Faces change. Weight gain or loss, aging, facial hair changes, new glasses. Most systems handle 2-3 years of aging reasonably well. Beyond that, accuracy degrades and re-enrollment becomes necessary.

**Lighting and camera quality.** The enrollment photo was taken with a decent camera in a well-lit registration area. The verification photo comes from a tablet's front-facing camera in a dimly lit waiting room. Or from a telehealth session where the patient is backlit by a window. These asymmetric conditions reduce matching accuracy.

**Accessories and occlusion.** Glasses (especially new ones since enrollment), hats, surgical masks, heavy makeup. Masks in particular became a real problem during and after 2020. Some systems can match on the upper face only (periocular matching), but accuracy drops meaningfully.

**Demographic bias.** This is the big one, and it deserves its own paragraph. Face comparison systems have documented performance disparities across demographic groups, particularly by race, gender, and age. The NIST Face Recognition Vendor Test (FRVT) has consistently shown that many commercial systems have higher false match rates and higher false non-match rates for certain demographic groups. In healthcare, where the population you serve is diverse and where a false rejection means someone can't access care, this isn't an academic concern. It's a deployment blocker if not addressed. You need to evaluate your specific system on a demographic distribution that matches your patient population, and you need to monitor performance across groups after deployment.

**Consent and ethics.** Collecting and storing biometric data (face embeddings are biometric data) triggers specific legal requirements in many jurisdictions. BIPA in Illinois, CCPA in California, various state biometric privacy laws. Patients must consent to having their facial data stored and used for verification. The consent must be informed, specific, and revocable.

### The General Architecture Pattern

The pipeline is simpler than you might expect:

```text
[Enrollment] → [Store Reference Image/Embedding] → [Verification Request] → [Compare] → [Confidence Score] → [Decision Logic]
```

**Enrollment.** At registration or first visit, capture a reference photo. This could be from a photo taken at the front desk, extracted from a driver's license scan, or captured during a video visit. Store the image (encrypted) or, better, store only the face embedding. Embeddings are not reversible to a recognizable image, which reduces your PHI exposure.

**Verification.** At subsequent check-ins (in-person kiosk, telehealth start, mobile app login), capture a new photo. Extract the face, compute the embedding, compare against the stored reference embedding for the claimed identity.

**Decision logic.** This is where healthcare nuance matters. You don't reject a patient based solely on a face mismatch. You use the score as one input into a multi-factor identity confidence system. High match (>95%): proceed automatically. Medium match (80-95%): additional verification (ask for date of birth, last four of SSN). Low match (<80%): route to staff for manual verification. No match or no face detected: fall back to traditional identification.

Production deployments insert a liveness check between capture and comparison to prevent presentation attacks (printed photos, screen displays). This is essential for any deployment where the camera is unsupervised.

The key design principle: face comparison is an identity signal, not a gate. Never deny care based on a failed face match.

---

> **The AWS build lives in a companion page.** This recipe covers the problem, the underlying technology, and the vendor-agnostic architecture. For the AWS services, architecture diagram, prerequisites, and the step-by-step pseudocode walkthrough, see the [Architecture and Implementation companion](chapter09.02-architecture). The Python example is linked from there.

## The Honest Take

Face comparison is genuinely one of the easier computer vision problems to get working. The technology is mature, the APIs are straightforward, and accuracy under good conditions is excellent. If this were a consumer app, you'd ship it in a week.

Healthcare makes it harder, but not for the reasons you'd expect. The technical accuracy is fine. What slows you down is everything around the technology: consent workflows, bias evaluation, fallback paths, regulatory compliance across multiple state laws, and organizational politics around biometric data collection.

The thing that surprised me most: the enrollment photo quality matters more than the verification photo quality. If the reference photo was taken with a low-resolution camera in bad lighting three years ago, every subsequent verification will struggle. Invest in good enrollment hardware and process. A well-lit, high-res enrollment photo makes every future verification easier.

My other hard-won lesson: never make face comparison a gate. Make it a signal. The moment your system denies someone care because a face match failed, you've created a patient safety incident, a legal liability, and probably a PR disaster. The design must always degrade gracefully to human verification. The face match should make the process faster and more secure when it works, not create a new failure mode when it doesn't.

The bias question is real and you can't hand-wave it. Test your system. Publish your results internally. Set up monitoring dashboards that track match rates by available demographic data. If you see disparities, fix them before scaling. The healthcare industry has a long history of deploying technology that works differently for different populations. Don't add to that history.

---

## Related Recipes

- **Recipe 9.1 (Image Quality Assessment):** Apply image quality checks to enrollment and verification photos before passing them to comparison
- **Recipe 5.1 (Internal Duplicate Patient Detection):** Face comparison can supplement probabilistic record matching when merging duplicate patient records
- **Recipe 5.5 (Cross-Facility Patient Matching):** Face embeddings as an additional matching feature for Health Information Exchange identity resolution
- **Recipe 11.4 (Pre-Visit Intake Bot):** Trigger face verification as part of the virtual check-in workflow

---

## Tags

`computer-vision` · `face-comparison` · `identity-verification` · `rekognition` · `patient-safety` · `fraud-prevention` · `biometrics` · `simple` · `mvp` · `lambda` · `s3` · `dynamodb` · `hipaa`

---

*← [Recipe 9.1: Image Quality Assessment](chapter09.01-image-quality-assessment) · [Chapter 9 Index](chapter09-preface) · [Next: Recipe 9.3: Wound Photography Measurement →](chapter09.03-wound-photography-measurement)*
