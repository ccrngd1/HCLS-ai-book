<!--
Edit this file freely; it is the source for a front-matter page in the print
edition. Plain markdown. Placeholders substituted at build time from
print/manifest.json:

  {recipe_count}

If this file is deleted the build omits the page rather than failing.
House style: no em dashes, no emoji, abbreviations spelled out on first use.
-->

# Preface

This book is a curated sampler. The complete Healthcare AI/ML Cookbook is a living digital reference of {recipe_count} recipes across 15 capability areas: document intelligence, clinical text generation, anomaly detection, entity resolution, predictive risk, medical imaging, conversational AI, and more. What you hold is one flagship recipe from each of those 15 chapters: enough to feel the shape of the whole, chosen to be the most instructive entry point in its domain.

Everything in this printed volume is cloud-agnostic. The use cases, the technology discussions, and the architectures describe what has to happen and why, not which vendor you buy it from, so they apply whether you run on premises or on any of the major cloud providers. The companion pages in the digital edition are written against AWS services, because a worked example has to pick something concrete to be useful. Those choices are not requirements: each one has an on-premises equivalent and a counterpart on the other hyperscalers, and the architecture in this book is what carries across. Keeping the build in the digital edition also keeps the print readable and durable, since service names change faster than a book can. Where a recipe references a capability covered elsewhere, we describe the concept rather than send you to a page that isn't in this volume.

**Why this book exists.** I consistently get one question from teams that I work with, 'How should we be using AI in our business?'. It can be a hard question to answer and most writing about healthcare AI falls into one of two camps. Vendor material shows a polished demo and skips the failure modes. Academic papers prove a model works on a retrospective dataset and stop short of how you would run it. Neither tells a practitioner how these systems fit together, where they break, and what it takes to deploy them responsibly around real patients and real clinicians. 

This book is written to fill that gap. I want to give leaders and builders ideas of where AI is used today, where it is being expanded, and some more future looking options for where it could be applied. It is architecture-first, honest about limitations, and vendor-neutral, and it spans the breadth of healthcare AI rather than a single product or specialty. Every recipe ends with an Honest Take because the hard-won lessons are usually the part left out everywhere else.

For leaders and line of business owners, this helps to show 'Art of the Possible' and spark ideas amongst internal teams. For builders, this will help draw a line between business need and technical implentation while helping to look around corners. The digital version also goes deeper into the architecture, to showcase what it really looks like beyond the requirements.

**Who this is for.** This book is written for everyone with a stake in a healthcare AI decision, not only the people who write the code. Architects and engineers will find the patterns and the failure modes. Technical leaders, product managers, and operations and business leaders will find a clear account of what each capability does, what it costs in effort and oversight, and where it is and is not ready. Every recipe opens with a plain-language problem before any technology, so you do not need to be a data scientist to follow it.
