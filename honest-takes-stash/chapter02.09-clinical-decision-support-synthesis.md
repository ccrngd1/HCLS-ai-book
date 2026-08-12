<!-- Removed from chapter02.09-clinical-decision-support-synthesis.md by honest_takes.py. Restore with: python3 honest_takes.py --restore -->

## The Honest Take

I'll tell you the uncomfortable truth first: most clinical decision support deployments, including ones with substantial AI investment, struggle to prove ROI. The rigorous studies that do exist (sepsis early-warning systems, specific drug-alert tuning efforts) show real benefit in narrow scopes, and broader CDS deployments often show mixed effects on patient outcomes once alert fatigue and workflow disruption are accounted for. This is not because CDS is a bad idea. It is because doing it well is genuinely difficult, and shortcuts produce systems that harm rather than help.

The failure patterns are predictable.

**The first pattern is chasing breadth over depth.** A team builds CDS "for everything," targeting every scenario across every specialty. Six months in, every scenario is mediocre and no scenario is trusted. Clinicians encounter the tool on different patients with different kinds of responses, and the overall impression is "unreliable." Meanwhile, a narrower-scoped CDS (empiric antibiotic selection in hospitalized patients with renal dysfunction, say) that goes deep on one scenario builds trust, builds adoption, and earns the right to expand. Pick a beachhead. Earn trust there. Expand deliberately.

**The second pattern is under-investing in the retrieval layer.** The authoritative sources corpus is the single biggest determinant of output quality. A small corpus of current, relevant, institutionally-aligned sources outperforms a massive corpus of stale, irrelevant, or badly-chunked content. Curating takes time. Curating takes clinical domain expertise. Curating is not glamorous. Curate anyway.

**The third pattern is building safety checks as LLM prompts.** "We'll ask the model to check for drug interactions" is not a safety check. A real safety check is a deterministic query against an authoritative drug database, the result of which is passed to the model as a non-negotiable input. The model's role is to communicate the result, not to derive it. Teams that leave safety to the model ship systems that miss interactions the model happened not to know about, and the failure mode is silent.

**The fourth pattern is not measuring the right things.** Delivery counts, latency percentiles, validation pass rates: all important, all insufficient. The metrics that matter are clinician engagement (read, expanded, considered), clinician decisions (accepted, modified, rejected with documented reason), and patient outcomes where connectable. Teams that measure delivery and latency and declare victory miss the actual question of whether the system helps patients.

**The fifth pattern is deferring regulatory review.** "We'll figure out FDA later" becomes "we didn't realize this was a medical device" becomes a forced scope reduction eighteen months in. Get regulatory affairs involved in the design. Document the exemption case as you build. Build artifacts that support the exemption rather than against it.

**The sixth pattern is shipping without clinician buy-in.** A CDS system that lands on clinicians' screens without their input gets rejected. A CDS system that was shaped by clinician input from the start gets engagement. The product is partly the model, mostly the workflow, and fundamentally the relationship with the clinicians it serves. Engage domain experts early, let them shape what the system should and should not do, and pilot before scaling.

A few things that have worked:

**Start with scenarios where deterministic checks do most of the work.** Drug interaction, allergy, renal dosing: these are largely table lookups. The LLM's job is to present the findings clearly, not to derive them. This is the safest starting point, both clinically and regulatorily, and it earns trust before expanding into scenarios where the model does more of the reasoning.

**Let the UI foreground reasoning, not recommendations.** The clinician should see why the synthesis landed where it did before they see what it recommends. "These are the relevant guidelines and findings; here is how they combine for this patient" is a different UI than "here is what to do." The first invites judgment; the second bypasses it.

**Treat every synthesis as an artifact.** Log it. Version it. Make it retrievable and auditable. A clinician who asks "why did the system recommend X yesterday?" should get an answer with full provenance, including the sources, the prompt, and the model version. This has compliance and trust benefits, and it has one more: it forces you to build a pipeline that is auditable, which is harder than building one that is just functional.

**Invest in clinician feedback loops that actually do something.** Capture not just thumbs-up and thumbs-down but free-text rejection reasons. Review them weekly with a clinical reviewer. Categorize the failure modes (retrieval miss, synthesis error, irrelevance to workflow, wrong tier). Feed the categories into a prioritized improvement backlog. Without this, feedback accumulates and the system plateaus.

**Design for the 2 AM failure mode.** Your system will fail at 2 AM, during an emergency, with a patient in front of a clinician. How does it fail safely? A clear timeout with a clear "synthesis unavailable" message is better than a degraded synthesis that looks complete but is missing critical safety findings. Design the failure modes as deliberately as you design the success modes.

**Don't pretend the system replaces judgment.** The entire value proposition is "helps the clinician think about this faster and more thoroughly." It is not "decides for the clinician." The framing throughout the product, the documentation, the training, and the outputs needs to be consistent on this. The moment the framing slips toward "the system knows best," you've lost the regulatory exemption, you've lost clinician trust, and you've built something that will eventually hurt a patient.

Final thought. Clinical decision support synthesis is one of the genuinely high-impact applications of modern AI in healthcare. The clinicians who use it well describe it as "like having a really thorough pharmacist in the room with me" or "a chief resident who happens to know the guidelines cold." That framing is exactly right: a colleague who helps you think, not a replacement for your thinking. Build toward that. Everything else flows from it.

---

