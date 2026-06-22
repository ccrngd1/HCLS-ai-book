# Open TODOs: Recipe 1.7: Prescription Label OCR 🔶

[NEEDS HUMAN] Expert S-4: Consider changing RXNORM_CONFIDENCE_THRESHOLD default from 0.70 to 0.85. The current prose explains when to raise it, but the default value choice is a product decision that depends on the primary use case (informational display vs. clinical decision support).

[NEEDS HUMAN] Expert A-6: NDC segment-aware zero-padding (detecting 5-4-1 vs. 4-4-2 vs. 5-3-2 segments from hyphenated input and normalizing to 11-digit). The current code does basic format validation and the "gap to production" section explicitly calls out the need for FDA NDC database lookup. Adding partial segment detection logic without a verified reference for the padding rules risks producing incorrect NDCs, which is worse than the current honest gap callout.
