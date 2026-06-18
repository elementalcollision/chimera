# ADR 0186 — Multi-repo reach (build ADR for ADR 0183 Pillar B)

**Status:** Proposed (2026-06-18) — *build plan; no implementation in this PR.*

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
against the *target* repo. Acting on other people's repos demands:
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
