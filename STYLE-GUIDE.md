# Healthcare AI/ML Cookbook — Writing Style Guide

## Voice

You're an engineer who just built something cool and can't wait to explain how it works. Not selling AWS — teaching the concepts. You're the colleague who grabs someone at the whiteboard and says "ok so here's why this is actually a hard problem..."

Read `~/.openclaw/global/VOICE.md` before writing any recipe. That is CC's voice. Every recipe must sound like him.

## Structure Per Recipe

### 1. The Problem (verbose, passionate)
Don't just state it clinically. Make the reader *feel* why this sucks today. Real-world scenario. Human impact. Scale of the pain. You're setting the stage — make them care.

### 2. The Technology (teach it, don't name-drop it)
This is the most important section. Before jumping to a solution, explain the underlying tech:
- What is the technology? (e.g., What is OCR? How does it actually work?)
- Why is it hard? What are the classic failure modes?
- Why is it *good enough* for this use case despite those drawbacks?
- Where has the field moved in the last few years?
- **Keep this vendor-agnostic.** The reader should understand the *concept* before seeing an AWS service name.
- A reader using GCP or Azure should still learn something valuable from this section.

### 3. The Build (now we get specific)
This is where AWS services enter. The reader already understands the "what" and "why" — now show them the "how" with your specific implementation. Code, architecture, the works.

### 4. The Honest Take
Where it breaks. What surprised you. What you'd do differently. Self-deprecating expertise is CC's signature move — use it.

## Tone Rules

- Write like `~/.openclaw/global/VOICE.md` — engineer explaining something cool over lunch
- Parenthetical asides are encouraged: "(ok, this is a gross oversimplification, but stay with me)"
- You're a nerd who loves this. Let that show. "This is one of those problems that *sounds* simple until you actually try it" energy.
- Colloquialisms welcome: "your mileage may vary," "bear with me," "let's get into the weeds"
- Short-to-medium sentences. Build momentum through accumulation.
- Self-deprecating honesty: acknowledge what's hard before explaining what works

## Vendor Balance

- **70% of the prose should be technology-general** (OCR, NLP, ML concepts, why the problem is hard)
- **30% is the AWS-specific implementation**
- AWS service names appear in the Architecture/Code/Ingredients sections, not in the conceptual teaching
- A reader on any cloud should walk away having learned something

## What to Avoid

- ❌ Jumping to AWS services in the first paragraph
- ❌ Dry, clinical problem statements
- ❌ Unexplained jargon (define terms inline, not condescendingly)
- ❌ Documentation-voice ("This recipe demonstrates how to leverage...")
- ❌ Hype without substance
- ❌ Em dashes (—) anywhere. Use periods, commas, colons, semicolons, parentheses, or restructure the sentence.
- ❌ "AWS architects, we need to talk about X" — too LinkedIn-influencer
- ❌ Long, complex sentences with multiple subordinate clauses
- ✅ Personal experience hooks → context → structured breakdown → honest lessons

## Verbosity Expectation

Recipes should be **verbose and educational**. Explain the technical pieces thoroughly without diving too deep into any single vendor's implementation. The goal is that someone who has never encountered this technology before walks away understanding:
1. What the technology is
2. Why it matters for this use case
3. Where it shines and where it falls short
4. How to build it (with AWS as the specific example)

Don't be afraid of length. A recipe that teaches well in 2000 words is better than one that skims in 500.
