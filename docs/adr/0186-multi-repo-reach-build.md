# ADR 0186 — Multi-repo reach (build ADR for ADR 0183 Pillar B)

**Status:** Accepted — *in progress.* Build plan being implemented increment by
increment.

> **Progress.**
> - **B.1** spec model (`repo`/`verify_cmd`) — ✅ merged.
> - **B.2** target-repo soak generalization — ✅ merged (#340); validated by a
>   self-clone smoke (clone → foreign gate → foreign autocommit → handoff).
> - **B.3** foreign-repo agent context — *in progress.*
>   - **B.3a identity isolation** — ✅ the agent's system prompt no longer
>     inherits Chimera's self-identity in foreign mode: `CHIMERA_FOREIGN_REPO`
>     (exported by the soak's foreign block) swaps `base_voice`/chimera extra for
>     a neutral `foreign_voice(repo)` + `foreign_task_guidance(repo)`. mind_dir /
>     state / history were already workspace-scoped (clone-local). Self-mode is
>     byte-identical.
>   - **B.3b context enrichment** — ✅ `chimera/core/foreign_context.py`
>     (`foreign_context_block`) reads the target repo's README/docs + the current
>     failing gate output and the soak's foreign block appends it to the phase-1
>     INBOX. The helper is pure/offline (no foreign-code execution); the soak
>     runs the gate (same surface the B.2 gate already uses, sandboxed by B.4).
> - **B.4** PR targeting + safety envelope — *in progress* (the real-risk phase).
>   Design + decisions: `mind/research/b4-foreign-pr-safety-envelope-design-2026-06-20.md`.
>   - **B.4a gate sandbox (M1)** — ✅ the ruff/pytest gate runs with provider
>     secrets stripped (self + foreign) via `soak_gate_run` (shell) +
>     `_gate_subprocess_env` (Python `run_check`); kill-switch
>     `CHIMERA_GATE_SANDBOX`. The agent keeps its keys; only the gate is stripped.
>   - **B.4b foreign draft-PR targeting (M2)** — ✅ `submit_pr(foreign_repo,
>     foreign_base)` pushes the soak branch to the target's explicit HTTPS URL
>     (bypassing B.2 no-push) + `gh pr create --repo … --draft`; a new
>     `maybe_foreign_pr` orchestrator gates on a SEPARATE opt-in
>     `CHIMERA_FOREIGN_PR` (never implied by self-PR), allowlist (defense-in-depth),
>     trust ≥ T4, gate-approved-commit. DRAFT-only, never merges. Self path
>     byte-identical.
>   - **B.4c approval + verify-review + ledger (M4)** — ✅ `foreign_pr_ledger.py`
>     (per-repo verify_cmd-review records + global foreign-PR count, all fail-soft);
>     `maybe_foreign_pr` adds a fail-closed verify-review gate + the first-5
>     approval gate (`CHIMERA_FOREIGN_PR_REQUIRE_APPROVAL` + per-run
>     `CHIMERA_FOREIGN_PR_APPROVED`), graduating after 5.
>   - **B.4d operator CLI + soak wiring** — ✅ `chimera foreign-pr {review,status,
>     submit}` (governance ledger uses the operator's PERSISTENT state, not the
>     throwaway clone); real_task_soak.sh's foreign block calls `foreign-pr submit`
>     (default-off no-op). **The one remaining step is the first LIVE run** — a
>     supervised draft PR on `elementalcollision/claude-daemon`, which requires the
>     operator to `foreign-pr review` the repo AND grant `CHIMERA_FOREIGN_PR_APPROVED=1`
>     per PR for the first 5. All code is default-off; no PR opens without that.
>   - **Trust source (2026-06-20, scope_evasion RCA)** — the foreign-PR trust gate
>     reads the operator's STANDING trust (`state_dir`), not the throwaway clone's
>     per-run copy. A self-clone dry run surfaced that a single in-run
>     `scope_evasion` (a noisy, general detector signal) demoted the clone's trust
>     below T4 and blocked an otherwise-clean PR. Safe because the PR content is
>     allowlist-scoped by the autocommit + gate/critic/review/approval-gated; the
>     per-run demotion stays the self-loop's learning signal. Writeup:
>     `mind/research/scope-evasion-rca-2026-06-20.md`.
>   - **B.4e foreign submit-path adaptation** — ✅ the self-PR submit machinery now
>     works for a foreign target: `maybe_foreign_pr`'s gate-approved signal is the
>     target's OWN `verify_cmd` re-run at HEAD (sandboxed), not the chimera
>     critic-gate log a foreign repo never writes; and `submit_pr.validate(foreign=
>     True)` skips the chimera-specific quality gates (fix-without-test on the
>     `chimera/` layout, the v4.113 chimera-`pytest` re-run, `mind/INBOX` honesty)
>     while keeping the structural/safety ones (worktree, soak-branch, clean tree,
>     commits, `[agent]` subject, secret-path, entropy, witness). Gate order made
>     safe: verify-review → approval → RUN verify_cmd (never execute unreviewed
>     foreign code). `--verify-cmd` threads through the CLI + soak.
>   - **B.4f foreign clean-tree footprint** — ✅ the clean-tree gate now ignores the
>     foreign operational footprint (`mind/`, `state/`, `uv.lock`), not just `mind/`
>     as the self path does — an arbitrary foreign repo (unlike chimera) does not
>     `.gitignore` `state/`/the venv (#351). Caught by the first claude-daemon dry run.
>   - **B.4g working-tree scope invariant** — ✅ defense-in-depth: the agent's ACT
>     prompt tells it to `ruff --fix` the SCOPE files, but it ran ruff TREE-WIDE on
>     claude-daemon, stripping unused imports across ~44 files (chimera's in-loop
>     `scope_check` is staged-index-only → blind to the unstaged sprawl). The
>     allowlist is already committed (B.4e), so `submit_pr.revert_out_of_scope_residue`
>     reverts everything else to HEAD (keeping `mind/`/`state/`/`.venv/` for forensics)
>     and the soak LOUDLY logs the reverted paths — an over-running agent stays
>     visible, never masked. `validate`'s clean-tree error now names the offenders (#352).
>   - **🎯 FIRST LIVE FOREIGN PR** — ✅ 2026-06-20: after 3 supervised dry runs (which
>     surfaced + fixed B.4f/B.4g), the live run opened
>     [claude-daemon#71](https://github.com/elementalcollision/claude-daemon/pull/71):
>     a DRAFT carrying EXACTLY the 2 allowlisted files (`+42/-0`), base `main`,
>     unmerged, one `[agent]` commit. The full safety envelope held end-to-end over
>     the network. Ledger: 1/5 toward approval-graduation.
>   - **🎓 APPROVAL-FLOOR GRADUATION (cross-repo)** — ✅ 2026-06-20: ran real
>     (non-noop) test-coverage tasks across THREE repos to exercise + graduate the
>     first-5 per-PR approval floor. PRs 2–4 on
>     [claude-daemon](https://github.com/elementalcollision/claude-daemon/pull/72)
>     (#72 compute_progress, #73 logging helpers, #74 _lerp_color), #5 on
>     [drift-monitor#1](https://github.com/elementalcollision/drift-monitor/pull/1)
>     (_length_shift), and #6 —
>     [GraphMemory-IDE#3](https://github.com/elementalcollision/GraphMemory-IDE/pull/3)
>     (formatting helpers) — fired with `CHIMERA_FOREIGN_PR_APPROVED` UNSET,
>     proving the floor graduated (opened=5 ≥ FLOOR). Every PR carried ONLY its
>     allowlisted test file; B.4h prevented the ruff sprawl (B.4g reverted only
>     `uv.lock` drift). GraphMemory used a `--no-project --with pytest` root-test
>     verify_cmd to dodge its heavy kuzu/transformers `tests/conftest.py`.
>   - **🤖 DAILY-LOOP FOREIGN ACTIVATION** — ✅ 2026-06-20: wired the CRAWL daily
>     driver (ADR 0182) to autonomously produce foreign draft PRs. A foreign backlog
>     spec (`repo` + `verify_cmd`) now (a) opts into the foreign-PR path —
>     `BacklogSpec.task_env()` emits `CHIMERA_FOREIGN_PR=1` for `repo`-bearing specs
>     only (self specs byte-identical), and (b) skips the picker's self-repo
>     gate-visibility check (`_check_gate_visibility` can't evaluate a foreign gate
>     against the self checkout — the soak's B.3b baseline runs the foreign
>     `verify_cmd` at the foreign base instead). Seeded the first foreign specs
>     (`mind/backlog/05-foreign-*.md`) targeting reviewed+graduated repos. The daily
>     `09:15` run now picks a foreign spec → clone → scoped change → DRAFT PR, fully
>     gated (allowlist + B.4f/g/h + reviewed verify_cmd).
>   - **♻️ RENEWABLE FOREIGN WALK SOURCE** — ✅ 2026-06-21: foreign daily production
>     self-sustains. `issue_backlog.py` now generates FOREIGN specs from
>     operator-LABELLED issues on registered repos (`mind/walk_repos.yaml`);
>     `crawl_daily.sh` runs `from-issues --walk` (fail-soft) to top up the backlog
>     each day. **Security model:** `verify_cmd` is an OPERATOR-TRUSTED per-repo
>     template — NEVER from the issue body; the only issue-derived substitution is
>     `{test}`, and every issue-derived path (`files`/`test`/`base`) is validated as
>     an injection-proof relative token (no metachars/`..`/leading-`-`); idempotency
>     is keyed on `(repo, issue#)`; foreign ingest is label-fail-closed. Hardened by
>     a 3-lens adversarial security review (verify_cmd/`{test}` injection confirmed
>     NEUTRALIZED) — must-fixes: MF-1 validate the whole `files` allowlist (B.4g is
>     keyed off it, so an unvalidated entry would escape), MF-2 enforce foreign
>     red-on-base gate-visibility IN the soak (the picker delegates it), MF-3
>     `(repo,#)` idempotency, MF-4 `--walk --dry-run` writes nothing. The label gate
>     (write-access-only) is the operator's per-issue opt-in checkpoint.
>   - **B.4h ruff charter-scope guard (agent-side prevention)** — ✅ the B.4g root
>     cause was the agent running `ruff --fix` TREE-WIDE; B.4g reverts that residue,
>     B.4h stops it at the source. `chimera/core/ruff_scope.py` (pure, exhaustively
>     unit-tested) confines a mutating ruff (`check --fix`/`--fix-only`/`--add-noqa`,
>     or `format`) to the locked charter allowlist at the shell-tool chokepoint —
>     the same place the pre-commit scope check runs — raising unless every path
>     operand is in-charter (tree-wide / `.` / out-of-charter all blocked). Inert
>     for report-only `ruff check`, `--diff` previews, and outside a scoped soak.
>     Override `CHIMERA_ALLOW_UNSCOPED_RUFF=1`. Hardened against bypasses found by a
>     4-lens adversarial review (M1 `--add-noqa`; M2 `uv run --with ruff ruff …` /
>     `uvx --from` / `uv run python -m ruff` wrapper-value detection; M3 value-flag
>     completeness incl. `--output-file`/`-o`/`--color`/`--range`).
>   - **Follow-up (B.4h posture, deferred — defense-in-depth, not safety-critical):**
>     fail-CLOSED on charter-load error instead of open; resolve the allowlist from a
>     stable root the agent can't relocate via `cwd`; `Path.resolve()` symlink
>     discipline on operands. The B.4g revert backstops all of these.
>   - **B.4i no-pass-to-pass-regression gate (adopted from Phoenix, arXiv:2606.20243)**
>     — ✅ the foreign gate-approved check (B.4e) runs only the SCOPED verify_cmd, so a
>     task that EDITS source could break a previously-passing test undetected. Gate 6.5
>     in `maybe_foreign_pr`: if an OPTIONAL broader `regression_cmd` is GREEN on base it
>     must stay GREEN at HEAD (`_foreign_no_regression`, sandboxed, force-checkout dance
>     with guaranteed ref-restore). Opt-in via `--regression-cmd` /
>     `CHIMERA_FOREIGN_REGRESSION_CMD` (unset → skip; additive-test tasks can't regress);
>     operator-trusted, never from issue bodies. Fail-OPEN on harness error (additive
>     assurance, not a primary boundary — B.4e + draft + B.4g remain). Cleared by an
>     adversarial review (verdict: ship; worst-case wrong-ref push is backstopped by
>     submit_pr.validate's soak-branch check). FIRST adoption from the arXiv WALK
>     intelligence source.
>   - **B.4i hardening** — ✅ per-spec/per-walk-repo `regression_cmd` wiring
>     (`BacklogSpec.regression_cmd` → `CHIMERA_FOREIGN_REGRESSION_CMD`;
>     `walk_repos.yaml` optional `regression_cmd`; threaded through the soak's
>     foreign-pr submit), a stderr warning when the worktree restore fails, and
>     detached-HEAD + backstop tests. STRETCH ✅ per-test pass→fail diffing: the gate
>     now captures the regression_cmd's stdout at base vs HEAD, parses the failing
>     test node-ids (pytest short + verbose forms; degrades to the suite-level signal
>     on an unrecognised format), and `_foreign_no_regression` returns a
>     `RegressionResult(ok, new_failures)` so the skip reason NAMES which
>     previously-passing test(s) the change broke.
>   - **B.4j per-model guardrail validation (adopted from NRT-Bench arXiv:2606.20408)**
>     — ✅ 2nd adoption from the arXiv WALK intelligence source. NRT-Bench: a guardrail
>     stack that helps one model can HURT another (vulnerabilities are near-disjoint),
>     so guardrails must be validated PER-MODEL. `chimera/core/guardrail_eval.py` +
>     `chimera guardrail-eval` probe each roster model's charter / prompt-injection
>     resistance (charter-escape, secret-exfil, destructive-cmd, prompt-injection) and
>     emit a per-(model × probe) resistance matrix. Pure + injectable (ask_fn /
>     classify_fn) → fully unit-tested; the CLI wires the live OpenRouter call and is
>     operator-invoked with `--models` (controls API cost), nonzero-exits on any
>     COMPLIED. NOTE: this measures per-model ALIGNMENT/injectability — the actual
>     safety boundary stays the DETERMINISTIC harness gates (scope/shell/B.4f-i/
>     entropy), which are model-independent. First-pass heuristic classifier;
>     `--judge` enables an LLM-judge (upgrade). UPDATE (q004): ran live across the
>     12-model cross-vendor roster — NRT-Bench's near-disjoint thesis held (only
>     qwen3-235b had a standing prompt-injection hole), but VERIFICATION overturned 2
>     of 3 single-shot ✗ flags: guardrail resistance is PROBABILISTIC, and one sample
>     over-reports. So the harness now samples N-per-cell (`--samples N`) and reports a
>     compliance RATE with a fail threshold (`--fail-rate`; default 0.0 = any
>     compliance flags, e.g. 0.5 = only consistent holes); ⚠ + the nonzero exit key
>     off the threshold, and ERROR cells (reasoning models returning empty text) are
>     tallied separately so they're never read as resisted. Findings logged to the
>     codex at `mind/wiki/projects/q004-…`. STRETCH ✅ reasoning-model coverage: the
>     probe path already sends no tools, so the real gap was that reasoning models put
>     their output in OpenRouter `message.reasoning` (not `content`) when budget is
>     reasoning-heavy — and the provider dropped it. `ChatResponse` now carries
>     `reasoning`, `complete_with_tools` captures it, and `guardrail_eval.response_text`
>     falls back to it so an empty-content reasoning model yields a REAL verdict instead
>     of ERROR (probe budget default raised 512→1024 for headroom). Empty-AND-no-
>     reasoning still reads ERROR (honest: genuinely no signal).
>   - **B.4k seeded-fuzz correctness oracle (adopted from arXiv:2606.20128, "The
>     Correctness Illusion in LLM GPU Kernels")** — 🔬 DESIGN (evaluation: codex q005).
>     Paper: a fixed-input `allclose` test certifies buggy code; seeded property/fuzz
>     vs a high-precision reference catches it. CRUX = the oracle-source problem —
>     fuzzing inputs is trivial; what you compare the output AGAINST is the hard part.
>     Three sources: (a) DIFFERENTIAL (pre-change code = reference) for
>     behavior-preserving tasks only; (b) PROPERTY/metamorphic (an invariant is the
>     oracle — range, round-trip, idempotence, ordering, conservation) for pure
>     functions; (c) REFERENCE-IMPL (an independent naive twin) — powerful but
>     expensive + itself fallible. EVIDENCE (16 backlog specs): ~0 refactors / 11
>     additive-test; the dominant task is "add a small pure helper + a fixed-input
>     test" (specs literally say "assert its ACTUAL behavior") — exactly the over-fit
>     risk the paper names, and the textbook property-fuzz target. DECISION: PROPERTY
>     fuzz LEADS (high applicability); DIFFERENTIAL is a SECONDARY mode that
>     auto-activates on behavior-preserving tasks (near-zero applicability today —
>     forward-looking). NOT a universal gate (cf. B.4i): opt-in, pure-function-scoped,
>     and it MUST log N/A so "no oracle" is never read as "verified". Fuzz is SEEDED
>     and records the failing seed (reproducibility — rhymes with q004's
>     "a non-reproducible signal lies"). STAGED BUILD: (1) ✅ pure + injectable core
>     `chimera/core/fuzz_oracle.py` (property + differential, seeded, counterexample
>     +seed) — #374; (3) ✅ differential behaviour-preservation GATE deepening B.4i —
>     `_foreign_behavior_preserved` runs an operator-trusted characterization driver
>     (`behavior_cmd`) at base vs HEAD and blocks if stdout DIFFERS; threaded through
>     `BacklogSpec.behavior_cmd` → task_env → soak → `foreign-pr submit --behavior-cmd`
>     → gate 6.6, mirroring B.4i (config flag CHIMERA_FOREIGN_BEHAVIOR_CMD; never from
>     an issue body). (2a) ✅ property path (SELF, where applicability actually is) —
>     `BacklogSpec.invariant` (YAML `property:`) → TASK_PROPERTY → the soak asks the
>     agent to encode it as a `fuzz_oracle.fuzz_check` test in the test it already
>     writes (self-repo helper tasks, gated by pytest — NOT the foreign path). The key
>     correction: property-fuzz is high-applicability for SELF helpers, so it is agent
>     empowerment, not a foreign gate. (2b) ✅ foreign `property_cmd` gate rung —
>     `_foreign_property_holds` runs an operator-trusted property/fuzz test at HEAD
>     (exits nonzero on a counterexample), threaded through `BacklogSpec.property_cmd`
>     → task_env → soak → `foreign-pr submit --property-cmd` → gate 6.7 (config flag
>     CHIMERA_FOREIGN_PROPERTY_CMD; never from an issue body). Low-applicability but
>     completes the verify / regression / behaviour / property gate taxonomy. B.4k done.
>   - **B.4l sound probabilistic gate bounds (evaluated from arXiv:2606.20510, "Efficient
>     and Sound Probabilistic Verification for AI Agents")** — 🔬 DESIGN (evaluation:
>     codex q006; multi-agent workflow: paper read in full + a 14-gate fallible-detector
>     inventory + a 5-technique prior-art survey + 3 adversarial critiques). The 4th and
>     last arXiv adoption-backlog item. The paper turns "a fallible detector passed" into
>     "the probability a violation slipped through is provably ≤ U" via a
>     distributionally-robust LP relaxed to a polynomial-size SDP over a Datalog
>     derivation DAG. **We REJECT that superstructure** — it needs a Datalog
>     information-flow policy + per-tool taint semantics + a conic solver (none of which
>     Chimera has), and the paper's own §6 says the bound goes vacuous on long traces and
>     that arbitrary agent-generated code breaks its precondition (exactly our regime).
>     The ONLY transferable kernel is how it makes each marginal sound: a one-sided
>     **Clopper-Pearson** upper bound on a detector's measured miss rate.
>   - **B.4l CRUX (the honest finding, from live-ledger evidence):** Chimera has neither
>     the DATA nor the i.i.d. structure a sound FNR bound needs. `reverted` disposition
>     has been recorded **0 times across 70 ledger lines** and `set_disposition` has zero
>     automated callers; the critic gate (the only labelled gate) has n=12 false-approve
>     cases (CP→FNR≤22%, sub-floor) and they are a hand-curated BENCHMARK, not a field
>     sample; the three ledgers (critic-log keyed by diff_sha, crawl by run_id) can't be
>     joined; deterministic gates have no "rate" (re-running is identical). A "sound
>     bound" computed today would be vacuous theatre — and printing one would itself
>     violate Chimera's "no signal ≠ verified" rule.
>   - **B.4l REFRAME → it is a MEASUREMENT rung, not a bounds rung.** Build the substrate
>     that could one day support a bound, advisory-only, and say so plainly. STAGED:
>     (1) ✅ pure core `chimera/core/gate_calibration.py` (#381) — `clopper_pearson_upper`
>     (bisection on the regularized incomplete beta; NO scipy/numpy) + `GateOutcome` +
>     UNCERTIFIED sentinel + a STRUCTURAL no-pool guard; soundness verified against the
>     binomial defining property. (2) ✅ the LABEL PRODUCER (#382) — `reconcile_reverts`
>     (the crawl ledger's long-anticipated "gh-reconcile") detects reverts of merged
>     work + sets disposition automatically; `chimera crawl-reconcile` runs daily; join
>     key (`run_id` on critic-gate-log) added. (3) ✅ advisory report — `chimera
>     gate-calibration` surfaces the landed-work revert rate + per-cell FNR bounds (or
>     UNCERTIFIED), wired into the daily crawl summary; observability only, never a gate
>     decision. (4) DEFERRED &
>     conditional: an anytime-valid e-process drift monitor (the only family valid under
>     drift), then — only IF a gate's stratified n ever clears the floor AND an operator
>     commits an α/δ — promote ONE gate to a hard bound (critic `false_approve==0`
>     pattern generalized), composing with the union bound (never the product).
>   - **B.4l soundness guards (from the critique, non-negotiable if any bound is emitted):**
>     every number names its TARGET POPULATION (benchmark ≠ field) and reports n; one-sided
>     only, never a point FNR; `reverted` is a noisy UNDERCOUNT so it is a lower-bound
>     proxy, NOT a numerator for a sound bound until a hold-out COVERAGE BACK-TEST
>     validates it; repeatedly-surfaced numbers use the anytime-valid form (fixed-α CP
>     voids coverage under peeking); strict per-(model×repo_class) stratification, never
>     pool. **RETIRE criterion:** if after K future merged runs no gate clears the floor,
>     the ledger stays observability-only and B.4l is not extended — no dead infrastructure.
## Context

ADR 0183 Pillar B (multi-repo reach) was deliberately deferred to its own build
ADR; this is it. The CRAWL loop (ADR 0182) is live and now qwen-led, but it is
**self-repo-only**: it can only improve `uberagent` itself, so it is fuel-starved
once the self-repo backlog is small. The real backlogs live in *other*
elementalcollision repos. Reaching them is a different operating mode — Chimera
as a *general* coding agent, not a self-improver — and a materially larger blast
radius, so it stays evidence-first and safety-gated.

Two prerequisites are now satisfied that were open when 0183 was written:
1. **Models**: the code tier is qwen-led (ADR 0183 A) — a clean, non-stalling
   lead validated in production.
2. **Host safety**: the soak watchdog now bounds memory (RSS cap + process-tree
   kill, ADR-less fix 2026-06-17) and we have the hard operational rule **one
   soak at a time** — both essential before pointing soaks at foreign code.

## Grounding (what's ready vs. self-repo-coupled)

**Ready (no change needed):**
- `chimera/core/repo_verify.py` — `verify_at_ref(repo_root, …)` and
  `classify_gate_transition(repo_root, …)` are **already `repo_root`-
  parameterized**. The red→green gate-visibility primitive works against an
  arbitrary checkout today; only its callers pass `Path.cwd()`.

**Self-repo-coupled (the work):**
- `BacklogSpec` (`chimera/core/backlog.py`): has `goal/files/test/base/done`
  and `issue` (provenance only) — no execution-time `repo` or `verify_cmd`.
- `scripts/real_task_soak.sh`: `REPO_ROOT="$(pwd)"`, gate hardcoded to
  `uv run chimera verify`; worktree is of the *self* repo.
- The loop reads chimera's `mind/`/KFM ontology — wrong context for a foreign repo.
- `chimera/core/self_pr.py` `maybe_self_pr(worktree, repo_root, base, …)`:
  trust-gated (≥ T4), **draft-only, never merges** — but targets the repo_root's
  own origin; needs explicit foreign-repo remote targeting.

## Design — the gated build increments

**B.1 — Spec model (small, self-repo-safe).** Add `repo: str | None` (owner/name)
and `verify_cmd: str | None` to `BacklogSpec` + `parse_spec` + `task_env`. A
foreign repo's gate is its OWN command (`pytest`, `npm test`, `cargo test`, …),
which `chimera verify` cannot express — `verify_cmd` is that per-repo abstraction.
Validation: a spec with `repo` set MUST also set `verify_cmd` (else `errors`).
`repo` unset → today's self-repo behaviour, byte-identical.

**B.2 — Target-repo soak (the bulk).** Generalize `real_task_soak.sh`: when a
spec carries `repo`, clone/worktree the **target** repo at `base` under a managed
workspace, run its `verify_cmd` as the gate (via `verify_at_ref` against that
`repo_root` — already supported, incl. red→green gate-visibility), and drive the
agent against that checkout. The chimera-specific gates (`chimera verify`,
`faithfulness`, `review`) stay the default for the self-repo and become one
option among per-repo verify commands. Self-repo path unchanged.

**B.3 — Foreign-repo agent context.** A foreign task must NOT inherit chimera's
`mind/`/ontology. Define a "contextless build" mode: the agent gets the task
goal, the foreign checkout, the target repo's own README/docs, and the failing
`verify_cmd` output — nothing chimera-internal. Keep the journal/scope-note
machinery (it's operational), but scoped to the workspace, not chimera's `mind/`.

**B.4 — PR targeting + safety envelope (the real risk).** Open the draft PR
against the *target* repo. **Detailed design + threat model + increments:**
`mind/research/b4-foreign-pr-safety-envelope-design-2026-06-20.md`. Acting on
other people's repos demands:
- **Repo allowlist** — start `elementalcollision/*` ONLY; enforced before any
  clone or agent action (fail-closed on a non-allowlisted `repo`).
- **Draft-PR-only, manual-handoff** — NO cross-repo auto-merge, ever, in this
  phase (RUN auto-merge stays self-repo + ledger-gated). Generalize
  `maybe_self_pr` to target the foreign remote, still trust-gated (≥ T4) + draft.
- **Sandbox** (ADR 0175): running a *foreign* test suite is untrusted code
  execution — `sanitized_subprocess_env` + the watchdog memory guard (RSS cap /
  tree-kill) + a network/secrets review of `verify_cmd` before first use.
- Existing scope/cost/critic/trust gates apply unchanged.

## Sequencing & graduation
1. **B.1** spec model — pure data, self-repo regression-safe, its own PR + tests.
2. **B.2** soak generalization — self-repo path must stay byte-identical
   (regression gate); add a *self-clone* smoke (treat uberagent as a "foreign"
   repo via `repo`/`verify_cmd`) before any real foreign repo.
3. **B.3** foreign-repo context.
4. **B.4** safety envelope, then **one** allowlisted repo with the richest
   backlog (e.g. claude-daemon), **draft-PR-only**, evidence into the same
   outcome ledger.

Auto-merge stays ledger-gated throughout; cross-repo auto-merge is out of scope
for this phase entirely.

## Non-goals (this phase)
- Cross-repo auto-merge of any kind.
- Non-allowlisted repos.
- Running a foreign `verify_cmd` without the sandbox + a first-use review.
- Concurrent multi-repo soaks (the one-soak-at-a-time rule holds; multi-repo
  *compounds* the memory/concurrency risk that caused the 2026-06-17 crashes).

## Falsification / revisit triggers
- If foreign `verify_cmd`s prove too flaky across repos (environment drift,
  nondeterministic suites), narrow to repos with containerized/deterministic CI
  before broadening.
- If acting on a foreign repo surfaces any safety/scope/secrets incident, **halt
  Pillar B** and treat it as a gate-hardening event (ADR 0182 incident discipline).
- If foreign-repo gate-pass rate is low (tasks don't converge), pause and feed
  the model/context work (Pillar A) before widening reach.
