<!-- GENERATED FILE. Do not edit.
     Source: print/frontmatter/before-you-send-phi.md
     Regenerate: python3 sync_phi_page.py
     This page is in both editions; the print source is authoritative. -->

# Before You Send Protected Health Information Anywhere

Every recipe in this book moves patient data through something. Sometimes that is a
model you host, and sometimes it is a service someone else operates. The architecture
diagrams in this volume show where the data goes. They do not show what the party at
the other end is permitted to do with it, and that is a separate question you have to
answer before any of these patterns reaches a patient.

I am not going to tell you how to comply with anything. I am not qualified to, the
answers differ by organization and jurisdiction, and they change faster than a book
can. What I can do is name the questions that experience says get skipped, so you can
put them in front of the people at your organization who do own them.

## The vendor questions

For any service that will process protected health information (PHI), including any
hosted model, transcription service, or application programming interface (API) you
did not build:

**Is this specific service covered?** Vendor agreements are often scoped per service
rather than per company, and a vendor with a signed business associate agreement (BAA)
may still have services outside it. The question is not whether you have an agreement
with the vendor. It is whether this service, in this region, on the day you deploy, is
inside it.

**Does the vendor train on your inputs, and how is that turned off?** For hosted
models this is the question most often assumed rather than checked. Find out whether
opting out is a contractual term or a setting in a console, because those fail
differently. A contract does not silently revert.

**How long are inputs retained, where, and by whom?** Retention for abuse monitoring
or debugging is common, is sometimes separate from the main data path, and is
sometimes performed by human reviewers. It may be configurable. It may not be.

**Which region processes the data, and does anything leave it?** A service can be
deployed in one region while a component of it, a safety filter, a translation step, a
model endpoint, runs elsewhere.

**What is logged, and is the log itself now a record containing PHI?** Prompts,
transcripts, and inference inputs frequently end up in ordinary application logs that
were never designed to hold clinical data, with a different retention policy and a
much wider set of readers.

## The questions about your own data

Secondary use is where good intentions go wrong. Training a model on historical
patient data is not the same activity as treating a patient, and it is usually
governed differently. Before a historical dataset becomes training data, someone at
your organization needs to have decided what the permitted purpose is, whether the
data has been de-identified or is merely pseudonymous, whether an institutional review
board (IRB) or data use agreement (DUA) applies, and what the minimum necessary data
actually is. None of those are architecture decisions, and none of them are yours to
make alone.

Two things are worth knowing when you have that conversation. Removing obvious
identifiers is not the same as de-identification, and sequences of events are
surprisingly identifying even when every individual field looks harmless. A timeline of
admissions, procedures, and locations can single out one person out of millions.

## What to do with this page

Take it to your privacy officer, your security team, and your legal or compliance
function, before you build. If the answer to any question above is "I assume so", that
is the finding. Ask for the answer in writing, from someone whose job it is to give it,
and note which of these questions your organization has already settled and which it
has not.

The recipes that follow assume that work has happened. They cannot do it for you.
