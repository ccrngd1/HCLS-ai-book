# Open TODOs: Recipe 2.8: Ambient Clinical Documentation

## main - `chapter02.08-ambient-clinical-documentation.md`

- [NEEDS HUMAN] **L259** - Update to specific recipe number once Chapter 10 (Speech / Voice AI) is drafted. Current chapter-level cross-reference is correct but a specific recipe (likely 10.x covering clinical ASR or diarization) would be more useful.
- [NEEDS HUMAN] **L260** - Update to specific recipe number once Chapter 11 (Conversational AI) is drafted. Current chapter-level cross-reference is correct but could point to a specific recipe once available.

## architecture - `chapter02.08-architecture.md`

- [NEEDS HUMAN] **L11** - Verify HealthScribe streaming mode availability. The text claims "HealthScribe supports both synchronous (batch) and streaming modes." The expert reviewer notes HealthScribe was historically batch-first with streaming added later. Confirm current API surface supports streaming and update text if batch-only or if streaming is limited to certain regions.
- [NEEDS HUMAN] **L91** - Verify current HealthScribe regional availability. The Prerequisites table says "ensure your account has access in the intended region" but does not list which regions are supported. Add a note listing current regions or linking to the official availability page.
- [NEEDS HUMAN] **L98** - Verify which Transcribe/HealthScribe endpoints support VPC interface endpoints. The VPC section references "verify endpoint availability for the HealthScribe-specific APIs in your region" which is guidance to the reader, but we should confirm whether HealthScribe actually exposes interface endpoints or only uses the public Transcribe endpoint.
- [NEEDS HUMAN] **L933** - Verify the `aws-health-ai-samples` repo (https://github.com/aws-samples/aws-health-ai-samples) exists. If it does not, remove the entry or replace with a confirmed aws-samples repo for healthcare AI patterns.
- [NEEDS HUMAN] **L950** - The FSMB link (https://www.fsmb.org/) points to the organization homepage, not a specific AI guidance document. Locate and link the specific FSMB policy document on AI use in clinical practice (if one exists) or remove the entry.
- [NEEDS HUMAN] **L954** - Verify both research dataset URLs and access terms: (1) MTS-Dialog at https://github.com/abachaa/MTS-Dialog and (2) Primock57 at https://github.com/babylonhealth/primock57. Confirm repos still exist and are accessible, especially given Babylon Health's corporate changes.
