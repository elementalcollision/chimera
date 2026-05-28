# v39 micro-soak design — final fan-out, items #11–#19 (closes 19-item diagnosis)

**Date**: 2026-05-28
**Runner**: `scripts/long_cycle_soak_v39.sh`
**Deliverable (soak output)**: `mind/research/v39-locomo-temporal-19-item-classification.md`
**Status**: runner landed; launch is operator-owned (separate chip)

This note records the design rationale for v39, the fourth and final
fan-out in the LoCoMo temporal-regression diagnosis series (v36 → v37 →
v38 → v39). It does **not** classify any items — that is the soak's job.

## Context: where the ladder stands

F2 (PR #98) ran hybrid retrieval against LoCoMo's 1,986-item corpus.
Temporal-reasoning regressed from 45.83% (F1) to 35.42% (F2); 19 items
went from F1-right to F2-wrong. The diagnosis has been deliberately
fanned out on a conservative ladder:

| Soak | Items | N | Result | Labels |
|---|---|---|---|---|
| v36 | #1 | 1 | CONVERGES | H2 |
| v37 | #1–#5 | 5 | CONVERGES | H2, H2, H2, H1, H1 |
| v38 | #6–#10 | 5 | CONVERGES | H2, H4, H2, H2, H2 |
| **v39** | **#11–#19** | **9** | (pending launch) | (to be classified) |

The ladder has converged three times running. v39 classifies the final
nine items in a single soak, completing the full 19-of-19 diagnosis.

## Why N=9 closes the set (not another N=10, not a rewrite)

v38's per-item rate landed at **$0.080**, inside the charter's
pre-registered middle amortization band (`$0.05–$0.10`), whose
pre-registered consequence was "v39 at N≈9, items #11–#19." N=9 is
simply the remainder of the 19-item set after v37's 5 and v38's 5. It
finishes the diagnosis in one soak rather than splitting into a fourth
and fifth run.

The alternative — a full **N=19 rewrite** that re-classifies all items
in a single fresh deliverable — was considered and rejected. It would
discard v37's and v38's already-audited paragraphs, is harder to audit
(no stable diff against prior merged work), and offers only a marginal
per-item cost saving. The append-only fan-out preserves every audited
paragraph and keeps each soak's output independently reviewable.

## The two-predecessor skip rule (new substrate-discipline test)

Each soak in the ladder has raised the discipline bar:

- v37 tested the **one-predecessor skip**: read v36's item, classify
  only the new range.
- v38 tested skipping **one** prior deliverable (v37's items #1–#5).
- v39 tests skipping **two**: the agent must read both
  `v37-locomo-temporal-5-item-classification.md` (items #1–#5) and
  `v38-locomo-temporal-10-item-classification.md` (items #6–#10),
  carry both forward as read-only context, and classify only items
  #11–#19.

This is the largest fan-out and largest predecessor-integration load
in the series. The INBOX names both predecessor files as READ-ONLY
data sources and lists "re-classifying items #1–#10" and "inferring
labels by analogy from v37/v38's distributions" as explicit overshoot
traps.

## Cost expectation (honest)

v38's postmortem established that the substrate's marginal cost is
**iter-count-dominated, not API-spend-dominated**, and that iter count
grows with how much prior context the agent must integrate. v39
integrates BOTH predecessors' deliverables (two vs v38's one), so the
per-item rate is expected to **drift toward $0.10** — above v38's
$0.080 baseline.

The hard cap is **$1.50** (≈$0.166/item ceiling). That is generous
relative to the $0.080 baseline, deliberately leaving headroom for the
two-predecessor integration load. If v39 STALLS or goes PARTIAL inside
that cap, that is the substrate's upper bound surfacing — a legitimate,
diagnosable finding, which is exactly why the ladder is conservative.

## Phase-1 sentinel-target semantics fix (v39-specific)

v38's postmortem flagged a latent ambiguity. v37/v38 set
`INVESTIGATION_DOC` via `soak_extract_sentinel_path`, which returns
the **first backticked entry** in the INBOX. In both runners that
entry is the F1 INPUT JSONL (`/tmp/locomo-f1/hypotheses.graded.jsonl`)
— not the output deliverable. The legacy `ready_marker_found` exit on
that path was therefore trivial; the soft-sentinel below was the real
exit.

v39 corrects this. `INVESTIGATION_DOC` is explicitly set to the **v39
output deliverable** (`mind/research/v39-locomo-temporal-19-item-classification.md`),
matching `SOFT_SENTINEL_ALLOWED_FILES`. Both now point at the agent's
own output, never at a predecessor or an input data file. This means
both the legacy exit AND the soft-sentinel exit validate that the
agent has written its own classification file.

This is a **v39-specific correctness fix**. It does not modify
`soak_extract_sentinel_path` or change the template for other runners;
the broader soak-runner template cleanup (rip out the legacy extraction
path entirely) remains a separate future chip. The change here is one
line of value + a comment block explaining why.

## Inheritance

v39 is a near-byte-clone of v38 with INBOX rewrite, identifier
substitutions, and the sentinel-target fix. It therefore inherits, via
v38 → v37, all prior cascade hardening: the phase-1 soft-sentinel
helper (PR #118), scope-check branch-prefix matching (PR #119), the
task-completion watchdog (PR #113), the forward-progress watchdog, the
ADR 0141 worktree detector, the SQLite thread-affinity fix, and the
ACT-phase budget enforcement. No hardening code is touched by this
chip.

## Locked outcomes — same four bands as v38

| Outcome | Condition | Interpretation |
|---|---|---|
| **CONVERGES** | 9 new paragraphs (items #11–#19), marker at EOF, clean R1 commit | Full 19-item diagnosis complete; next step is the synthesizing ADR 0142 amendment (operator's call) |
| **PARTIAL** | <9 paragraphs OR marker/count mismatch | Fan-out ceiling at N=9; charter root-cause or split into two smaller soaks |
| **STALLS** | watchdog fires before 9 paragraphs land | Two-predecessor integration load exceeds substrate capacity; investigate |
| **CONFABULATES** | scope check refuses, citations absent, items #1–#10 re-classified, or labels inferred by analogy | Substrate-quality signal at the largest fan-out yet |

The outcome is picked from observed data; no fifth band is invented.

## Honest disclosures

- v39 is the highest-fan-out and highest-predecessor-integration soak
  in the series. A STALLS or PARTIAL result is the substrate's upper
  bound surfacing — a legitimate finding, not a failure. The
  conservative ladder exists precisely so this boundary is diagnosable.
- The sentinel-target fix is correct semantics for v39 and inlines part
  of a v38 postmortem follow-up; it is explicitly *not* a speculative
  template-wide change.
- v37+v38's H2 dominance (7 of 10) is a **prior, not a target**. Items
  #11–#19 must be classified from their own F1/F2 evidence. An all-H2
  sweep would only be credible if each paragraph's reasoning
  independently supports H2 with per-item elimination; an all-H2 result
  lacking that reasoning would read as pattern-matching and should be
  treated as a quality signal, not a convergence.

## Scope of this chip (landing only)

This chip lands the runner + this design note. It does **not** launch
the soak (operator-owned) and does **not** classify any items. No
cascade hardening, ADR 0142, ADR 0146, or any prior classification
file is modified.

The `scripts/archive/soak-runners/README.md` amendment described in
the chip is omitted: that path is gitignored (`.gitignore` excludes
`scripts/archive/`), and the whole archive tree is deliberately
local-only provenance — adding it would require `git add -f` and
un-ignore a deliberately-ignored file. The local on-disk amendment
(noting v38 CONVERGES + v39 closes the lineage) remains in the
operator's working tree as provenance, matching how v35–v38 archive
entries already live.
