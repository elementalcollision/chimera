# v38 — 10-item temporal-reasoning regression classification (v37 fan-out)

**Date**: 2026-05-29
**Status**: Phase 1 — investigation only (engines off)
**Chip**: classify items #6-#10 of the 19-item F1→F2 temporal-reasoning regression set
**Predecessors**:
- [v37 5-item classification](./v37-locomo-temporal-5-item-classification.md) — classified items #1-#5 as H2,H2,H2,H1,H1
- [F2 retrieval ablation](./locomo-f2-retrieval-ablation-2026-05-27.md) — identified 19-item regression
- [v38 micro-soak design](./v38-micro-soak-design-2026-05-28.md) — charter for this N=10 fan-out

## Data sources
- F1 graded JSONL: `/tmp/locomo-f1/hypotheses.graded.jsonl`
- F2 graded JSONL: `/tmp/chimera-f2-locomo-v6/results.graded.jsonl`

## Locked hypotheses
- H1 (retrieval-distractor): top-k=8 missed the temporally-relevant session
- H2 (context-budget dilution): timestamp-anchored grounding lost weight under context truncation
- H3 (category-fundamentals): temporal reasoning needs full session sequence for time-deltas
- H4-other: anything not fitting H1/H2/H3

## v37 carry-forward (items #1-#5, NOT re-classified)

Per v37 (`b3d14f2`), items #1-#5 are locked:
- Item 1: conv-26::qa14 → H2
- Item 2: conv-26::qa22 → H2
- Item 3: conv-26::qa46 → H2
- Item 4: conv-26::qa81 → H1
- Item 5: conv-41::qa45 → H1

These are not re-examined. This note adds items #6-#10 only.

---

## Item 6: conv-41::qa50 → H2

F1 produced a substantive attribute list centered on John's community engagement trajectory: "passionate about community service," "involved in local politics," "dedicated to mentoring students," "recently joined a fire-fighting brigade," "values family time." F2 produced a different but equally substantive attribute list: "dedicated, resilient, and family-oriented," "actively engages in community service," "emphasizes the importance of inner strength and optimism," "appreciating the small joys, like sunsets." Both answers draw from the same John conversation — F2 does not claim information absence, so H1 is ruled out. H3 is ruled out by F1's success with the same answerer model on the same character-attribution task. The most parsimonious explanation is H2: under top-k=8 truncation, the answerer's attribute-extraction emphasis shifted away from the specific trait combination the expected answer requires (selfless, passionate, rational) toward a different subset of John's personality (resilient, compassionate, optimistic). The temporally-anchored narrative arc of John's development — community service → politics → mentoring → firefighting — that F1 traced got compressed, and the answerer substituted a flatter character sketch.

## Item 7: conv-42::qa0 → H4

F1 answered "yes" with evidence: Nate hangs out with people outside his usual circle at gaming tournaments, makes friends at conventions, plans gaming sessions with new contacts. F2 answered "yes" with substantively identical evidence: Nate hangs out with people outside his usual circle at video game tournaments, hosts gaming parties with multiple attendees. Both answers are affirmative, both cite the same category of evidence (gaming-tournament socializing), and both are factually consistent with the conversation. F2 was graded incorrect despite being substantively correct. This does not fit H1 (the session was clearly retrieved and used), H2 (the evidence is not diluted — both answers draw the same inference), or H3 (no temporal-computation failure). The most parsimonious explanation is H4: soft-judge stochasticity. The expected answer mentions "teammates" specifically, and neither F1 nor F2 uses that word — yet F1 was graded correct and F2 incorrect. This is a judging artifact, not a retrieval or context-budget artifact.

## Item 8: conv-42::qa14 → H2

F1 answered "Jo" (correct). F2 answered "Tilly" (incorrect — Tilly is the name of a stuffed animal dog Nate gave Joanna, not the nickname Nate uses for Joanna). The conversation contains both "Jo" (the person nickname) and "Tilly" (the stuffed animal). F1 correctly distinguished the two referents. F2 conflated them. The session was certainly retrieved — F2 knew about Tilly, which appears in the same conversational context as "Jo" — so H1 is ruled out. H3 doesn't apply; this is a referent-disambiguation problem, not a time-delta computation. H2 best explains the failure: under context truncation, the distinct referents ("Jo" = person nickname, "Tilly" = stuffed animal name) lost the contextual separation that lets the answerer distinguish them. The answerer saw both names in a compressed window and selected the wrong one for the "nickname Nate uses for Joanna" slot.

## Item 9: conv-42::qa84 → H2

F1 answered "No" with correct evidence: Nate's video game tournament setback and Joanna's laptop crash during the first half of September 2022. F2 answered "Yes" with incorrect evidence: Nate won a significant tournament and Joanna received positive writing feedback. F2 reversed the temporal polarity (bad month → good month) by attributing events from a later time period to the September 2022 window. The relevant sessions were retrieved — F2 discusses Nate's gaming tournaments and Joanna's writing career, which are the right topics — so H1 is ruled out. H3 is ruled out by F1's success at this exact temporal-polarity question with the same answerer model. H2 is the best explanation: under top-k=8 truncation, the temporal anchors (September 2022 dates, the sequence of tournament-failure-then-later-win, the laptop-crash-then-later-script-success) got blurred across the compressed context window, and the answerer collapsed distinct events from different time periods into the query's timeframe, inverting the polarity.

## Item 10: conv-43::qa28 → H2

F1 answered "John Williams" with the Harry Potter theme as supporting detail (correct). F2 answered "Harry Potter and the Philosopher's Stone" movie tunes without naming the composer (incorrect — the question asks "Which popular music composer," requiring the composer name). The session was retrieved — F2 found the Harry Potter connection and the piano-playing context — so H1 is unlikely. H3 doesn't apply; composer attribution is not a time-delta computation. H2 best explains the failure: the composer attribution (John Williams) was a secondary detail in the retrieved session, subordinate to the more salient Harry Potter theme. Under context truncation, the answerer latched onto the prominent movie-title detail but the composer name fell below the attention threshold, producing a partially-correct answer that misses the specific slot the question targets.

---

## READY-FOR-REMEDIATION

Classified items conv-41::qa50..conv-43::qa28 as H2, H4, H2, H2, H2. Cumulative across v37+v38: 7× H2, 2× H1, 1× H4 (10 of 19 items classified). R1 — no code change. This chip's atomic deliverable is the five new classifications; phase 2 commits this research note only.
