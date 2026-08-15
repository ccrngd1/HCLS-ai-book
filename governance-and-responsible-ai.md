<!-- GENERATED FILE. Do not edit.
     Source: print/frontmatter/governance-and-responsible-ai.md
     Regenerate: python3 sync_phi_page.py
     This page is in both editions; the print source is authoritative. -->

# Governance and Responsible AI

Every recipe in this book is an architecture. None of them is a decision to deploy. Between
the two sits a body of work that is not technical, that this book cannot do for you, and that
decides whether any of these patterns should reach a patient at all. This page names it.

I am not going to tell you how to govern your artificial intelligence, how to be responsible,
or how to comply with anything. Those answers depend on your organization, your patients, your
jurisdiction, and the state of a fast-moving field, and they belong to people whose job that
is. What I can do is name the things a serious governance review will expect to see, so they
are on your list before someone else puts them there.

## The responsible-AI questions that outlast the architecture

The engineering in this book is only part of the puzzle. These are the questions that decide whether a
working system is a good idea, and they apply to every chapter.

**Does it work as well for everyone?** A model can be accurate on average and quietly worse for
the patients who are already underserved. This book strives to flag that per recipe because it is the
failure that is easiest to ship and hardest to see, but it isn't meant to be all encompassing. Who measures performance across your actual
population, and who is accountable when it is uneven?

**Can a human understand and override it?** Clinical AI that cannot be explained to the
clinician relying on it, or overridden by them, or by an audit team then it is a liability wearing a lab coat. Where does a
person stay in the loop, and does that person have the authority and the information to say no? 

**Is the human review real?** Nearly every recipe here leans on a person, a clinician, a
coder, a reviewer, as its safety control, and that control is only as good as the attention
behind it. Attention decays: when a system is usually right, the people checking it drift
toward approving on reflex, and a review step that has quietly become a rubber stamp is worse
than no review, because it manufactures a record of oversight that was never actually given.
So measure whether the review is happening rather than assuming it. Watch how often reviewers
actually change or reject what the system proposed, and how long they spend before signing
off, and treat a rate that drifts toward zero as an alarm rather than a success. When it
slips, the levers are workload and design, not exhortation: reduce how much any one reviewer
has to clear, make what the system generated visually distinct from what it grounded, route
the highest-risk cases to deliberate review, and periodically re-check a sample of approved
output against the source. Who owns those numbers, and who acts when they move the wrong way?

**Was it validated on your patients, not someone else's?** A number from a paper, a vendor, or
a benchmark is a starting point, not evidence that the system works in your setting. Who signs
off that it was validated locally before it touched care?

**Who watches it after launch?** Models drift, populations change, and a system that was safe
at go-live may not be safe a year later. Who owns the monitoring, and what triggers taking it
out of service?

**What happens when the model changes?** A retrained model is a new model, even when only the
data changed and the code did not. Does that update pass the same review gate as the first
version, or does it reach production because the pipeline ran on schedule? Is the model version
pinned in the record, so a decision can be traced to the version that made it, and can you roll
back and show a new version beats the old one before it goes live rather than after? Who owns
that, and who signs off on the change?

None of these is answered by choosing a better model. They are answered by people and process.

## The artifacts your review will ask for

Organizations formalize this differently, but a governance committee will generally expect some
version of the following, and it is cheaper to know that before the meeting.

**An applied model card.** A structured description of what the model is, what it was trained
and validated on, how it performs and for whom, and how it fails. The Coalition for Health AI
(CHAI) publishes a widely referenced applied-model-card format; whether you use theirs or your
own, expect to produce one.

**An AI use inventory.** A living record of where AI is actually deployed across the
organization, what each system does, and who owns it. Regulators and accreditors increasingly
assume this exists. Many organizations discover, when asked, that it does not.

**A record of governance-committee review.** Evidence that the right people (clinical, legal,
privacy, equity, security, and operational owners) actually examined this system and decided,
on the record, to deploy it, with the conditions and the rollback plan attached.

## Least privilege, and a plan for when it fails

Two security expectations sit underneath every recipe in this book, and a governance review
will ask about both.

**Least privilege for models and agents.** Give a model, and especially a tool-using agent,
only the data and the actions it genuinely needs, and enforce that outside the model rather
than in the prompt. An instruction to "stay in your lane" is not a control; a system that has
been manipulated or tricked will ignore it. A permission boundary enforced by the systems the
agent calls will not, so the worst a hijacked request can do is whatever the agent was actually
authorized to do, and no more. Who granted those permissions, who reviews them, and can you
show the agent cannot write, order, or disclose beyond its remit?

**A plan for when prevention fails.** The recipes describe graceful degradation, what a system
does when a component fails. That is not the same as an incident-response plan, which is what
you do when a component is breached or abused: a transcript or model-input store exposed, an
inference endpoint compromised, an agent driven to act outside its scope. These carry
breach-notification obligations on clocks that belong to your privacy and security teams, not
to a cookbook. Name the owner, write the runbook, and rehearse it before you need it.

## The frameworks worth knowing by name

You do not need to adopt all of these, but your governance function will recognize them, and
naming them early makes the conversation faster.

- **The National Institute of Standards and Technology (NIST) AI Risk Management Framework**, a
  voluntary but widely adopted structure for identifying and managing AI risk.
- **The Joint Commission and Coalition for Health AI (CHAI) Responsible Use of AI in Healthcare
  guidance**, aimed squarely at what a health system will hold itself and its vendors to.
- **The Office of the National Coordinator for Health Information Technology (ONC) HTI-1 rule**,
  which sets transparency expectations for decision-support functionality in certified health
  information technology.

These change. Treat the names as a way into the current version with your own experts, not as a
reading list that settles anything.

## Where this leaves you

This book gives you the architecture. Your governance, clinical, legal, privacy, and compliance
functions decide whether and how it ships. If those functions do not exist yet at your
organization, that is the first thing to build, before any recipe here. The full digital edition
at https://health-ai.lawson.engineer/ carries the per-recipe detail; the responsibility is the same in both.
