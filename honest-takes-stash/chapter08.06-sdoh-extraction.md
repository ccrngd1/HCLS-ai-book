<!-- Removed from chapter08.06-sdoh-extraction.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

SDOH extraction is one of those problems that looks tractable until you start counting what you're missing. The explicit mentions (patient reports food insecurity, patient is homeless) are genuinely easy to extract. You'll get 85-90% of those with a well-trained classifier. That's the part that demos well.

The hard part is everything else. The implicit mentions are where the real clinical value lives, and they're where NLP systems struggle most. "Patient didn't fill the prescription" is probably financial strain. "Patient missed follow-up" is probably transportation or childcare. "Patient's A1c worsening despite education" might be food insecurity. These inferences require clinical reasoning that goes beyond text pattern matching, and current systems catch maybe half of them.

The assertion problem is sneakier than you'd expect. "Was referred to food bank" doesn't mean the patient went. "Has housing voucher" doesn't mean they've found housing. "Daughter helps with meals" sounds like resolution until you learn the daughter lives two hours away and visits monthly. The gap between "documented" and "resolved" is where care coordination lives, and it's hard to capture from text alone.

The training data problem is real. Public datasets (MIMIC, i2b2/n2c2 shared tasks) are useful for initial model development, but they don't represent your patient population's documentation patterns. Your social workers document differently than academic medical center social workers. Your community health center notes look different than tertiary care notes. Plan for a local annotation effort: 200-500 notes labeled by clinical staff who understand your documentation conventions. It's expensive and slow, but it's what separates a demo from a system people trust.

One thing that surprised me: the highest-value output isn't the individual extraction. It's the patient-level longitudinal profile. A single mention of food insecurity is a data point. Three mentions across six months, with no "resource connected" mentions in between, is a care gap that demands intervention. Build the profile view early, because that's what care managers actually use.

---

