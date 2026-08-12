<!-- Removed from chapter14.08-ambulance-routing-dispatch.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

Here's what I'd tell you over coffee about building this system:

The dispatch scoring function is the easy part. Seriously. You can get a working "score candidates by travel time plus coverage impact" prototype in a week. The hard parts are everything around it.

**Data integration is 70% of the project.** Getting real-time GPS from every unit in a consistent format. Getting hospital diversion status (which is often communicated by fax or phone call, not API). Getting traffic data that's actually current. Getting CAD system integration that doesn't add 10 seconds of latency. Each of these integrations is its own multi-month project.

**The travel time model makes or breaks you.** If your travel times are wrong by 2 minutes on average, your "optimal" dispatch is no better than proximity-based. And travel times for emergency vehicles are genuinely hard to model. Lights-and-sirens driving doesn't follow civilian traffic patterns. The only reliable approach is to build your model from actual GPS traces of your own fleet's historical runs. That requires months of data collection before you can even start optimizing.

**Dispatchers will resist.** Not because they're Luddites, but because they've been doing this job for 20 years and they're good at it. They know things the model doesn't: that Unit 7's crew is having a bad day, that the bridge on Oak Street floods when it rains, that the nursing home on Elm always has a 5-minute delay getting the patient to the ambulance bay. Build the system as a recommendation engine, not an override. Let dispatchers accept or reject suggestions. Track acceptance rates. Improve the model based on rejections.

**The coverage model is where the real value lives.** Ironically, the biggest response time improvements don't come from smarter dispatch (picking the right unit for a given call). They come from smarter positioning (having units in the right places before calls happen). The repositioning optimizer is less glamorous than the real-time dispatch engine, but it delivers more impact. Invest there.

**You will need a simulation environment.** You cannot test dispatch optimization changes in production. "Let's see if this new scoring function works better" is not something you try on live 911 calls. Build a discrete-event simulator that replays historical call patterns against your fleet model. Run thousands of simulated days. Compare response time distributions. Only then deploy to production.

---

