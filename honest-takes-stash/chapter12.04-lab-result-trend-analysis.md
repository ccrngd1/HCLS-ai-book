<!-- Removed from chapter12.04-lab-result-trend-analysis.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

The math is the easy part. I have built three of these in different settings and the trend detection algorithm has, in retrospect, never been the binding constraint. Mann-Kendall plus Theil-Sen on a clean baseline gets you 80% of the value for 5% of the effort, and the remaining 15% of the value comes from sophisticated state-space models with diminishing returns on engineering investment. The hard parts are upstream and downstream: harmonization, baseline definition, clinical rule calibration, and clinician trust.

The thing that surprised me the first time I built one was how much of the design decisions are actually clinical workflow decisions in disguise. Should we surface a trend at 60 days or 90 days of duration? What slope counts as concerning for HbA1c versus creatinine? Should we suppress trends in patients with active oncology treatment? None of these are statistical questions. They are conversations with the clinical leadership about what they want to see. A pipeline that ships without those conversations gets unplugged within a quarter. A pipeline that has those conversations baked into a clinical rule layer gets adopted. The temptation is to skip the conversations and let the math decide; the math has no opinion on these questions.

Alert fatigue is the single biggest failure mode and it is structural, not technical. If your pipeline produces more than three or four trend surfaces per patient per year, clinicians will learn to scan past them. The clinical relevance layer is not optional. The job of that layer is to be aggressive about suppression, not to be inclusive. A surface count of zero for a patient is fine. A surface count above two per month is alarming, in the sense that the system is probably surfacing things that do not warrant the attention.

The thing I would do differently if I were starting over is to build the suppressed-trends log into the system on day one and treat it as a primary tuning artifact, not an afterthought. The trends the system suppresses are at least as informative as the trends it surfaces. They tell you which clinical thresholds are calibrated correctly and which ones need to move. Most teams realize this in month four and then have to retroactively reconstruct the suppression history. Build it from the start.

The part I underestimated, repeatedly, is harmonization. LOINC mapping coverage of 95% sounds great until you realize the missing 5% includes a critical lab the entire CKD pipeline depends on. UCUM unit conversion is mostly mechanical, but the few labs where the conversion depends on analyte molecular weight (glucose, urea, cholesterol) trip up libraries that assume linear conversion factors. The first version of every trend pipeline I have built spent more engineering effort on harmonization than on trend detection, which felt wrong at the time and turned out to be exactly right.

Finally: the explanation matters as much as the detection. Clinicians are pattern matchers under time pressure. A trend surface that says "your patient's creatinine is rising" is too thin. A trend surface that says "your patient's creatinine has risen at 0.06 mg/dL per month for fourteen months, with a most-recent value of 1.62 versus a 12-month baseline of 1.18, all from chronic ambulatory care" is something the clinician can actually reason with in the eight seconds they have to look at it. The narrative is the product, not the math.

---

