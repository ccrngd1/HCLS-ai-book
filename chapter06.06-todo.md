# Open TODOs: Recipe 6.6: Patient Similarity for Care Planning

> Auto-extracted 2026-06-18 from inline source comments (2 items). Captured before the scaffolding-cleanup pass; resolve or consciously drop each before declaring the recipe final.

## architecture — `chapter06.06-architecture.md`

- **L341** — TODO (TechWriter): Expert review A1 (HIGH). Add data governance subsection: patient similarity uses one patient's historical data to inform another's care. Under HIPAA, this typically falls under Treatment/Payment/Operations (no individual authorization required), but organizational policies, state laws, and data use agreements may impose additional constraints. IRB review may be required if the system is used for research or outcomes are published. Patients should be informed that de-identified data contributes to care planning tools. This is a must-address governance conversation before deployment.
- **L345** — TODO (TechWriter): Expert review S1 (HIGH). Address cross-patient PHI exposure model. The similarity results contain patient IDs of other patients. Default recommendation: return only aggregated outcome statistics to the care planning UI (no individual patient IDs). If drill-down into individual similar patient records is needed, require break-the-glass authorization and log the access. The current sample output JSON shows patient IDs in top_similar_patients; clarify that this is the internal API response, not what the UI displays.
