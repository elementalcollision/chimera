# v37 — 5-item temporal-reasoning regression classification (v36 fan-out)

**Date**: 2026-05-29
**Status**: Phase 1 — investigation only (engines off)
**Chip**: classify items #1-#5 of the 19-item F1→F2 temporal-reasoning regression set
**Predecessors**:
- [F2 retrieval ablation](./locomo-f2-retrieval-ablation-2026-05-27.md) — identified 19-item regression
- [v36 one-item classification](../v36-soak-postmortem-2026-05-28.md) — classified `conv-26::qa14` as H2

## Data sources
- F1 graded JSONL: `/tmp/locomo-f1/hypotheses.graded.jsonl`
- F2 graded JSONL: `/tmp/chimera-f2-locomo-v6/results.graded.jsonl`

## Locked hypotheses
- H1 (retrieval-distractor): top-k=8 missed the temporally-relevant session
- H2 (context-budget dilution): timestamp-anchored grounding lost weight under context truncation
- H3 (category-fundamentals): temporal reasoning needs full session sequence for time-deltas
- H4-other: anything not fitting H1/H2/H3

---

## Item 1: conv-26::qa14 → H2

F1 answered with a confident counterfactual inference ("Caroline's desire to pursue counseling is deeply rooted in the support she received; if she hadn't received that support, her motivation would have been diminished"). F2 retreated to hedging ("does not provide a direct answer… uncertain if she would have developed the same passion"), despite the same conversation material being available. Both runs used the same `gpt-4o-mini` answerer — so H3 (category-fundamentals) is ruled out by F1's success at this exact temporal-counterfactual question. H1 (retrieval-distractor) is implausible: the question is explicitly about Caroline and the conversation is centrally about Caroline, so the relevant session was almost certainly in the top-8. The most parsimonious explanation is H2: when top-k=8 truncated the answerer's context, the temporal-anchoring signal (gratitude for past support → current motivation) was diluted by the other seven sessions, causing the answerer to default to epistemic hedging rather than committing to the inference F1 successfully made.

## Item 2: conv-26::qa22 → H2

F1 answered with a confident inference ("it is likely that Caroline would have Dr. Seuss books… she expressed a desire to create a library for when she has kids, which includes classics"). F2 retreated to uncertainty ("does not provide specific information… cannot definitively say"). The question is about Caroline's likely bookshelf contents based on her stated preferences — this is not a cross-session chronology problem, so H3 is ruled out. The relevant session (containing Caroline's statements about building a children's library with classics) was almost certainly retrieved given the question's clear topical alignment with Caroline's conversation. H1 is therefore unlikely. The pattern — F1 makes a commonsense bridge inference (children's classics → Dr. Seuss), F2 hedges — matches the H2 signature: under truncated context, the answerer lost the evidential confidence to make the bridge inference and defaulted to "cannot confirm."

## Item 3: conv-26::qa46 → H2

F1 produced a confident, affirmative inference ("Melanie appears to be supportive of the LGBTQ community, including the transgender community… she expresses pride in Caroline's journey"). F2 produced a hedged answer ("there is no direct evidence… it is unclear if she actively identifies as an ally"). The F1 answer traces a chain of evidence — Melanie's expressions of pride, encouragement of Caroline's advocacy, and appreciation for inclusivity — and concludes allyship. F2 acknowledges the same evidence points but refuses the inferential leap. The question targets the same Caroline/Melanie conversation, so H1 (session not retrieved) is weak. H3 doesn't apply; this is an attitudinal-inference question, not a time-delta computation. H2 best explains the degradation: the evidence chain (expressions of pride → encouragement of advocacy → allyship inference) requires multiple pieces of grounding to cohere; under top-k=8 truncation, the chain fragments and the answerer retreats to "no direct evidence" hedging.

## Item 4: conv-26::qa81 → H1

F1 answered with a confident negative inference ("Caroline is currently focused on her journey toward adoption… there is no indication she is considering moving back to her home country soon"). F2 answered with a flat inability ("does not provide any information… I cannot determine"). This is a counterfactual about Caroline's future plans (move back to home country). Unlike items 1-3, F2's answer does not acknowledge any relevant grounding at all — it claims a total absence of information. F1 found sufficient grounding in Caroline's forward-looking statements about adoption and community-building to infer "no, she wouldn't want to move back." F2's "does not provide any information" suggests the temporally-relevant sessions containing Caroline's future plans may not have been retrieved into the top-8 at all — i.e., the retrieval-distractor scenario (H1). A move-back-home question could plausibly trigger BM25/dense matches to other conversations about relocation or home-country topics, crowding out Caroline's actual future-plan statements. H2 cannot explain a total-information-absence claim.

## Item 5: conv-41::qa45 → H1

F1 made a confident negative inference ("there is no direct evidence to suggest that John would be open to moving to another country… his conversations primarily focus on local politics, community service, and family life"). F2 answered with a flat inability ("does not provide any information… I cannot answer"). As with item 4, F2's response claims a complete absence of grounding — not hedging, but a blank "no information." F1's answer shows the information does exist in John's conversation (focus on local commitments), and F1 used it to infer "no, not open to moving." The F2 blank-slate response is best explained by H1: the query about John moving to another country matched distractor sessions in the top-8 ranking, pushing John's local-politics-and-family sessions below the retrieval cutoff. H2 cannot explain a total loss of the relevant session; if the session were retrieved but diluted, F2 would show traces of hedging like items 1-3, not a flat information-absence claim.

---

## READY-FOR-REMEDIATION

Classified items conv-26::qa14..conv-41::qa45 as H2, H2, H2, H1, H1. R1 — no code change. This chip's atomic deliverable is the five classifications; phase 2 commits this research note only.
