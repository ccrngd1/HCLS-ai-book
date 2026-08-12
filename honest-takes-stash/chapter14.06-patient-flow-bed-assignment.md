<!-- Removed from chapter14.06-patient-flow-bed-assignment.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what I've learned about bed assignment optimization that the vendor demos won't tell you:

**The data problem is 80% of the work.** Getting accurate, real-time bed state is brutally hard. ADT systems lag reality. Cleaning times are unpredictable. Staffing changes mid-shift. You'll spend most of your implementation time on the state ingestion layer, not the optimizer. The math is the easy part.

**Staff trust takes 6-12 months to build.** Bed coordinators have been doing this job with their brains and their phones for decades. They're good at it. They know things the system doesn't (that nurse is having a bad day, that room has a broken call light, that patient's family is difficult). The first few months, acceptance rates will be low (40-50%). That's normal. Every accepted recommendation builds trust. Every good override teaches the system something.

**You will never eliminate overrides, and you shouldn't try.** A 75-85% acceptance rate is excellent. The remaining 15-25% represents legitimate human judgment that the model can't capture. If you're at 95%+ acceptance, you're probably not being aggressive enough with your recommendations (playing it too safe).

**The political dimension is real.** Unit charge nurses sometimes resist accepting patients because they're "already busy." The optimizer might say their unit has capacity, but the nurse's lived experience says otherwise. Sometimes the nurse is right (the acuity mix is high even if the census is low). Sometimes it's territorial behavior. Your system needs to surface the data transparently without being accusatory.

**Start with a decision-support tool, not an automated system.** The temptation is to build full automation: patient arrives, system assigns bed, done. Don't. Start with recommendations that humans accept or reject. Build trust. Understand the override patterns. Only automate the obvious cases (straightforward med-surg admits with no special requirements) after you've proven the model works.

**Cleaning time is the hidden bottleneck.** Everyone focuses on discharge prediction, but the time between "patient leaves bed" and "bed is ready for next patient" is often 45-90 minutes and highly variable. Environmental services (EVS) staffing, terminal vs. standard cleaning protocols, and simple communication delays all contribute. Some hospitals have cut boarding times more by optimizing cleaning workflows than by optimizing assignments.

---

