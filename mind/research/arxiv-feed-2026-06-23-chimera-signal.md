# arXiv / source feed triage — 2026-06-23 (Chimera signal)

Reviewed the 2026-06-23 chimera feed (143 records; delta-dedup surfaced 139 new). The
creator mapped in **additional sources** — this feed is now ~60% GitHub *issues* from
across the agent ecosystem (86 records) plus ~57 arXiv papers. As flagged at the
source, the keywords are deliberately broad: the great majority is **noise** for us
(unrelated ML — speech, translation, medical time-series, materials — and good-first-
issue/translation chatter from unrelated repos). The auto-digest's relevance heuristic
ranked off-topic monitoring/proof papers at the top and **missed** the genuinely
Chimera-relevant ones; the on-demand read below is the real filter.

Three items are genuinely relevant; two are notable because they speak directly to
work we *just shipped*.

## 1. Actionable (modest) — "All Smoke, No Alarm: Oracle Signals in Agent-Authored Test Code" (arXiv:2606.18168)

The feed's own relevance engine scored this 0.98 and hooked it straight into our code:
it names the failure mode that **"test file counts substantially overestimate
verification."** We have exactly that boolean: `_check_fix_without_test`
([submit_pr.py:258](../../chimera/core/submit_pr.py)) marks touched `chimera/` source
as *covered* the moment **any** `tests/` file appears in the diff — a touched-test ⇒
verified shortcut, regardless of whether that test exercises the new source.

**Honest scoping:** the stack is **not** blind — the soak's mutation/faithfulness gate
(`mutation_teeth`, the B.4k correctness-illusion line) is the real "does the test
verify" check (it kills mutants), and `_validate_tests_actually_pass` ensures the tests
at least run green. So this cheap gate leans on a stronger downstream one. The
candidate is to make the cheap gate **honest on its own**: count a touched test as
coverage only when it plausibly covers the changed source (name-correspondence, or it
adds assertions), instead of any-test-touched. Low-risk, scoped to `submit_pr.py`. A
real improvement, but defense-in-depth refinement, not a gap — file as a candidate, not
an emergency.

## 2. Validation + future-design — "Calibration Is Not Control: Why LLM-Agent Oversight Needs Intervention" (arXiv:2606.21399, cs.AI)

This is the paper B.4l should have cited. Its thesis: scalar risk prediction
(calibration) "targets the wrong object for control — the question is not how likely
the agent is to fail, but whether an available **intervention** would improve the
outcome." It formalizes **intervention advantage** (expected utility gain from
intervening vs continuing) and a **prefix-branching** counterfactual protocol. That is
precisely the line B.4l drew — we shipped the *measurement* substrate (Clopper-Pearson
calibration of fallible gates) and explicitly deferred *control* (stages 4-5) as
conditional. This paper both **validates the deferral** ("calibration is not control")
and hands us the decision object for the eventual intervention stage. Capture as the
design input for B.4l stage 4-5, if/when the calibration ledger accrues data.

## 3. Security-audit idea — "Local LLM Agents as Vulnerable Runtimes" (arXiv:2606.21071, cs.CR)

CLAWAUDIT: a static auditor of the agent **runtime layer** — prompt builder, parser,
tool dispatcher, skill loader, memory writer, network client, permission gate — for
implementation-level weaknesses (the layer prior work ignored in favor of prompt
injection / marketplace risk). Chimera *is* such a runtime (the shell-tool chokepoint,
B.4a sandbox, B.4h charter guard, the MCP dispatch). Worth a read as a checklist for a
self-audit of our own runtime layer; not a build candidate yet.

## Verdict

One modest adoption candidate (#1 — tighten `_check_fix_without_test`), one strong
validation of completed work (#2 → B.4l), one audit-checklist reference (#3). **No new
high-value build** the way 2026-06-21 produced B.4i-l — the B.4 program is complete and
this feed largely *confirms* it. The dominant takeaway is about the **source**: the new
GitHub-issues mapping adds a lot of noise for Chimera, and the digest heuristic can't
rank the real signal — an on-demand LLM triage (or a Chimera-relevance pre-filter on
the issues source) is what turns this feed into intelligence.
