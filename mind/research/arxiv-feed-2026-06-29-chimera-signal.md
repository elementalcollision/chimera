# arXiv / source feed triage — 2026-06-29 (Chimera signal)

Reviewed the 2026-06-29 chimera feed (148 records: **83 GitHub issues** from across the
agent ecosystem + **65 arXiv**; 367 total across the three agents). As before the
keywords are broad and the bulk is **off-domain** (~59 of the 65 papers: diffusion,
time-series, speech, fraud, PDEs). The auto-digest ranked GitHub work-items (other
repos' tickets, plus repeated `[LOG-AGENT FIX]` rate-limit spam) at the top; the
on-demand read below is the real filter. Two papers genuinely matter; one drove a
change we shipped today.

## 1. SHIPPED — judge-prompt grounding, from "Can LLMs Judge Better Than They Generate?" (arXiv:2606.28050, cs.CL)

The paper tests the assumption under our entire judge-heavy gate stack (critic ADR 0160,
witness panel ADR 0107, the guardrail-eval judge, the critic A/B): that *evaluation is
easier than generation*. In a controlled in-context QA setting it isn't — generation
beat self-evaluation on 3 of 4 benchmarks, and the **mechanism** is the bite: judges
attend to the context **3–5× less** than generators and "barely read the candidate
answer," and evaluation-tuning *induces over-acceptance*.

Audited our two judge prompts against that failure mode:
- **Witness** ([witness.py](../../chimera/core/witness.py)) — provides full context and
  requires grounded *concerns* on rejection, but the **approval path had no grounding
  requirement** → exactly the skim-and-approve / over-acceptance hole.
- **Critic** ([critic.py](../../chimera/core/critic.py)) — better (a `rationale` is
  always required) but did not force that rationale to engage the actual diff.

**Fix shipped:** a conservative, prompt-only grounding requirement on both — read the
whole diff before deciding; an `approved=true` asserts you checked the real changed
lines (not a skim); the witness `summary` must state what the diff changes (grounds
approvals too); the critic `rationale` must cite the specific changed line(s). No schema
change. **Regression-checked** via `critic-calibrate` (the harness from #3): hardened
prompt 93% / **0 false-approve** / 2 false-reject vs baseline 89% / 0 / 3 — false-approve
held at 0 (the hardening didn't make the critic reckless), false-rejects didn't rise.
Honest caveat: single-shot n=28, so 89%→93% is within noise — the claim is *no
regression*, not a measured win; the curated benchmark with strong models doesn't
exercise the skim-approve failure the change targets. It's a reasoned, regression-checked
hardening, A/B-able further via `critic-calibrate` / `witness-calibrate` on a harder set.

## 2. Validation + framing — "Govern the Repository, Not the Agent" (arXiv:2606.28235, cs.SE)

The strongest conceptual match to our whole direction. Across **930,000 agent-authored
PRs**: agents that each pass their own tests still leave repositories accumulating
problems no single PR accounts for, and **~half the "integration friction" variance is
repository-level** — it survives controls for the agent, author, and contribution size.
Thesis: the unit of evaluation/governance should be the *repository*, not the isolated
agent.

This validates three things we already do/believe: the B.4l `repo_class` stratification
(repo is a real axis, not bookkeeping); the foreign-PR + drift-monitor "improve the repo"
work; and q005's "a green test suite is not a working product," now at ecosystem scale
with hard numbers. Seed for a future signal: a per-repo **integration-friction** metric
in the crawl ledger (`revert_rate` is the crude version). Capture as design input; no
build today.

## 3. The GitHub-issues source is *foreign-PR fuel*, not just noise

Earlier triages dismissed the GitHub half as noise. Reframe (operator note): those 83
issues are **real open issues on real repos** (climate-almanac, invoice-to-pay,
cuga-agent, tau, …) — i.e. exactly the kind of crawl-ready foreign work the WALK → soak →
draft-PR pipeline (ADR 0186 B) is *built to target*. They are not Chimera issues (0 of 83
are `elementalcollision/chimera`), and none are allowlisted or crawl-ready today, so the
full safety envelope applies (allowlist fail-closed, operator-trusted verify_cmd, draft-
PR-only, B.4a sandbox). But as a **work-source signal** this feed is a candidate input to
the foreign backlog: a future increment could let WALK ingest *labelled* issues from
operator-allowlisted repos surfaced here. Noted as a direction, gated on allowlisting +
the existing envelope — not an action yet.

## Moderate (note, don't chase)

- **ToolPrivacyBench** (arXiv:2606.28061, cs.CR) — purpose-bound info-flow leakage in
  tool-using agents (does a task-private atom reach only authorized tools/sinks?).
  Validates the Sakana data-egress concern (ADR 0187) and the B.4a secret-stripping
  sandbox; a checklist for our tool-dispatch layer, not a build.
- **The Weakest Link Tells It All** (arXiv:2606.27739, cs.LG) — outcome-supervised PRM
  credit assignment; conceptual rhyme with B.4l's *min*-composition (slip-through ≤ the
  weakest gate), not directly adoptable.

## Verdict

One shipped change (#1 — judge-prompt grounding, the first concrete fruit of an
arXiv-audit-of-our-own-prompts rather than a new subsystem), one strong validation of the
whole multi-repo direction (#2), and a reframed source signal (#3: the GitHub feed as
foreign-PR fuel). No new high-value *subsystem* build the way 2026-06-21 produced B.4i–l;
the dominant value this week is **confirmation + a small hardening of the gates we already
run** — and a standing idea to turn the GitHub-issues source into allowlisted foreign work.
