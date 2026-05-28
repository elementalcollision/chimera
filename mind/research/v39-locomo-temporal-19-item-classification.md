# v39 — 19-item temporal-reasoning regression classification (final 9 items)

**Date**: 2026-05-29
**Status**: Phase 1 — investigation only (engines off)
**Chip**: classify items #11-#19 of the 19-item F1→F2 temporal-reasoning regression set
**Predecessors**:
- [v37 5-item classification](./v37-locomo-temporal-5-item-classification.md) — items #1-#5: H2,H2,H2,H1,H1
- [v38 10-item classification](./v38-locomo-temporal-10-item-classification.md) — items #6-#10: H2,H4,H2,H2,H2
- [F2 retrieval ablation](./locomo-f2-retrieval-ablation-2026-05-27.md) — identified 19-item regression

## Data sources
- F1 graded JSONL: `/tmp/locomo-f1/hypotheses.graded.jsonl`
- F2 graded JSONL: `/tmp/chimera-f2-locomo-v6/results.graded.jsonl`

## Locked hypotheses
- H1 (retrieval-distractor): top-k=8 missed the temporally-relevant session
- H2 (context-budget dilution): timestamp-anchored grounding lost weight under context truncation
- H3 (category-fundamentals): temporal reasoning needs full session sequence for time-deltas
- H4-other: anything not fitting H1/H2/H3

## v37+v38 carry-forward (items #1-#10, NOT re-classified)

Per v37: items #1-#5 are H2,H2,H2,H1,H1 (conv-26::qa14, conv-26::qa22, conv-26::qa46, conv-26::qa81, conv-41::qa45).
Per v38: items #6-#10 are H2,H4,H2,H2,H2 (conv-41::qa50, conv-42::qa0, conv-42::qa14, conv-42::qa84, conv-43::qa28).

---

## Item 11: conv-43::qa34 → H2

F1 answered with a diverse set of post-career possibilities for John: mentoring, endorsements, charity work, sports commentary/coaching. F2 produced a smaller but overlapping set: mentoring, charity work/foundation, endorsements, building his personal brand. Both answers draw from the same John conversation — F2 didn't claim information absence, so H1 is ruled out. F1's answer was graded correct; F2's was graded incorrect despite substantial overlap. The expected answer is "become a basketball coach since he likes giving back and leadership." F1 mentioned coaching explicitly ("sports commentary or coaching"), while F2 omitted coaching and instead focused on mentoring/charity/endorsements. H3 doesn't apply — this is a future-trajectory inference, not a time-delta computation. H2 best explains the failure: under top-k=8 truncation, the coaching/giving-back/leadership thread in John's conversation was compressed below the answerer's attention threshold, while the mentoring and charity threads survived. The answerer produced a substantively reasonable but slot-mismatched answer.

## Item 12: conv-43::qa67 → H2

F1 answered "travel blogging or vlogging," connecting Tim's fantasy-writing skills to travel documentation — exactly matching the expected answer "Writing a travel blog." F2 answered "joining a travel club or group… learning a new language, like German." Both answers engage with Tim's travel interests and are factually grounded in his conversation (he joined a travel club, he considered learning German). The session was clearly retrieved — F2 shows detailed knowledge of Tim's activities — so H1 is ruled out. H3 doesn't apply. H2 explains the failure: the writing/blogging thread (Tim's fantasy writing hobby → travel blog bridge) is a secondary inference chain in the conversation. Under context truncation, the answerer latched onto the more salient travel-club and language-learning facts, losing the creative-writing → travel-blog bridge that F1 successfully made.

## Item 13: conv-44::qa20 → H1

F1 answered "chicken" with the supporting detail "her favorite recipe is Chicken Pot Pie" (correct). F2 answered "The grounding does not provide specific information about which meat Audrey prefers eating more than others. Therefore, I cannot answer that question." This is a flat information-absence claim — F2 asserts zero grounding for the question. F1's answer demonstrates the information exists in Audrey's conversation (Chicken Pot Pie as favorite recipe). H2 cannot explain a total information-absence claim; if the session were retrieved but diluted, F2 would show traces of hedging with partial information. The blank-slate response is the H1 signature: the question about Audrey's meat preference triggered BM25/dense matches to other food-discussion sessions in the corpus, crowding Audrey's own conversation out of the top-8 entirely.

## Item 14: conv-47::qa12 → H2

F1 answered "there is no evidence to suggest that James had a girlfriend during April 2022" (correct — "Presumably not"). F2 answered "Yes, James had a girlfriend during April 2022. He asked Samantha to be his girlfriend on September 4, 2022." F2 made a temporal-placement error: it knew about Samantha, but it collapsed the September 2022 dating event into the April 2022 query window, producing the wrong polarity. The session was retrieved — F2 knows Samantha's name, the September 4 date, and the relationship arc — so H1 is ruled out. H3 is ruled out by F1's success with the same answerer model on this exact temporal-polarity question. H2 best explains the failure: under top-k=8 truncation, the temporal anchor separating "April 2022 (no girlfriend)" from "September 2022 (Samantha becomes girlfriend)" was compressed, and the answerer collapsed distinct time periods, inverting the polarity from no to yes.

## Item 15: conv-47::qa25 → H2

F1 answered correctly: "they are fans of different football teams. James is a fan of Liverpool, while John supports Manchester City." F2 answered "Yes, John and James are fans of the same football team, Liverpool" — then immediately contradicted itself in the same answer: "John, on the other hand, is a Manchester City fan." The answer is internally incoherent: it asserts sameness but states different teams. The session was retrieved — F2 knows both Liverpool (James) and Manchester City (John) — so H1 is ruled out. H3 doesn't apply. H2 explains the failure: the answerer retrieved both team affiliations but under context truncation, the logical connective ("are they fans of the *same* team?") was processed incorrectly. The "yes" header was generated before the answerer finished processing the two distinct team facts, producing a self-contradictory answer. The expanded context in F1 allowed the answerer to hold both affiliations and the comparison frame simultaneously.

## Item 16: conv-47::qa33 → H2

F1 answered "Yes, John and James studied together. They discussed programming and coding… and John expressed interest in possibly collaborating on projects." F2 answered "There is no evidence in the provided grounding that John and James studied together. While they discussed programming and expressed interest in collaborating on projects, there is no specific mention of them studying together." Both answers acknowledge the programming/coding discussions and collaboration interest. F1 made the commonsense bridge inference (discussing programming + expressing desire to collaborate → they studied together). F2 refused the bridge inference despite acknowledging the same evidence. The session was retrieved — F2 cites the same programming discussions — so H1 is ruled out. H3 doesn't apply. H2 explains the failure: under context truncation, the evidential chain supporting the "studied together" inference lost coherence, and the answerer defaulted to literal-match hedging ("no specific mention of studying together").

## Item 17: conv-48::qa28 → H1

F1 answered "Colombia, specifically Bogotá" (correct). F2 answered "Rio de Janeiro" (incorrect — wrong country and wrong city). F2 didn't claim information absence — it produced a confident but wrong location. However, the specificity of the error is telling: Rio de Janeiro is a plausible vacation destination that could appear in another conversation in the corpus. The question asks about Jolene's summer 2022 location, and F2 substituted a location from a different character's travel narrative. H1 best explains this: the BM25/dense query for "country summer 2022 vacation" matched a distractor session featuring Rio de Janeiro above Jolene's Bogotá session in the top-8 ranking. H2 (answerer confused two locations within the same retrieved session) is less parsimonious — Jolene's conversation doesn't mention Rio. The most straightforward explanation is that Jolene's session was pushed out of top-8 by a distractor session about another character's Rio trip.

## Item 18: conv-49::qa5 → H2

F1 answered "Canada… road trip to Jasper" (correct). F2 answered "the Rockies" — geographically adjacent (Jasper is in the Canadian Rockies), but slot-incomplete (the question asks "Which country," requiring "Canada," not a mountain range). F2 shows awareness of the trip context (Rockies road trip) but misses the country-name slot. The session was retrieved — F2 knows about the Rockies trip — so H1 is ruled out. H3 doesn't apply; country attribution from a trip description is not a time-delta computation. H2 best explains the failure: under context truncation, "Canada" was a secondary framing detail overshadowed by the more salient "Rockies" destination. The answerer substituted the salient geographic feature for the requested country name, producing a partially-correct but slot-mismatched answer.

## Item 19: conv-50::qa42 → H2

F1 answered "No" (correct — "No"). F2 answered "Yes" (incorrect). The question is a yes/no temporal-location query: did Calvin and Dave meet in Boston between August and November 2023? F2's single-word "Yes" with no supporting evidence is a temporal-polarity inversion. The conversation was almost certainly retrieved — Calvin/Dave is a specific character pair, and the question is about their meeting history — so H1 is unlikely. H3 is ruled out by F1's success on the same yes/no temporal question with the same answerer model. H2 best explains the failure: under top-k=8 truncation, the temporal anchors separating the Boston-meeting timeframe from other Calvin/Dave meetings were compressed, and the answerer collapsed distinct meeting events into the query's timeframe, inverting the polarity from no to yes. The bare "Yes." without elaboration is consistent with a truncated-context answerer that saw Calvin and Dave meeting *somewhere* in the conversation and defaulted to affirmative without checking the temporal constraints.

---

## READY-FOR-REMEDIATION

Classified items conv-43::qa34..conv-50::qa42 as H2, H2, H1, H2, H2, H2, H1, H2, H2. R1 — no code change. Completes v37+v38 fan-out; all 19 of 19 temporal-reasoning regression items now classified across v37+v38+v39.
