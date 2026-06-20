# B.4 — Foreign PR targeting + safety envelope (ADR 0186) — DESIGN

**Status: DRAFT for review (2026-06-20).** Design only; no implementation yet.
On approval this expands ADR 0186's B.4 section and drives the increments below.

B.4 is the phase where Chimera stops *building the machinery* and starts
**acting on a repository it does not own**. B.1–B.3 are merged: a foreign-repo
soak can clone an allowlisted target, run its own `verify_cmd` as the gate,
autocommit a green change to a soak branch, and frame the agent with neutral
target-repo context (voice + README + failing gate output) — then stop at
**manual-handoff** (the branch sits in the clone; nothing is pushed). B.4 adds
the two things that handoff currently substitutes for: **(1)** safely executing
foreign code, and **(2)** opening a **draft PR against the target repo**.

## What actually changes (threat model)

Three new exposures vs. the self-repo loop:

1. **Foreign code execution with our secrets in scope.** The gate runs the
   target's `verify_cmd` (pytest / npm / cargo / make …). Today that subprocess
   inherits the **full parent environment** — `run_check` in
   `chimera/core/repo_verify.py:90` calls `subprocess.run(argv, cwd=…)` with **no
   `env=`**, and B.3b's soak-side gate capture runs `sh -c "$GATE_VERIFY_CMD"`
   with the full shell env. So a malicious or careless foreign suite can read
   `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` / `GH_TOKEN` from `os.environ`,
   and (network unrestricted) exfiltrate them. **This is the highest-severity
   gap and must close before any non-self foreign run.**

2. **Write access to a remote we don't own.** A draft PR means pushing the soak
   branch to the target's origin. B.2 deliberately *disabled* push
   (`remote.origin.pushurl = no-push://…`). B.4 must re-enable it **narrowly**
   (one branch, draft PR, never the default branch, never a merge).

3. **Acting in public.** A draft PR on someone's repo is outward-facing and hard
   to fully retract (notifications, CI triggers on their infra). Demands
   draft-only + a human in the loop for the *first* runs.

Everything else (scope/cost/critic/trust gates, the watchdog RSS-cap/tree-kill
memory guard, the allowlist) already exists and applies unchanged.

## Safety mechanisms (grounded in current code)

### M1 — Sandbox the foreign `verify_cmd` (closes exposure #1)

`chimera/tools/sandbox_env.py::sanitized_subprocess_env()` already exists (ADR
0175): a **denylist-by-name** that strips env vars matching secret patterns
(`API_KEY`, `TOKEN`, `SECRET`, …) while keeping operational vars
(`PATH`/`HOME`/`GIT_*`/`UV_*`/`LANG`). The agent's own `shell`/`code_exec` tools
already use it; the **gate does not**. B.4:

- Pass `env=sanitized_subprocess_env()` to `run_check`'s `subprocess.run` **when
  the gate is foreign** (a `repo_root != self` / explicit `sandbox=True` flag, so
  the self-repo gate is byte-identical — chimera's own `chimera verify` legit
  needs no secrets either, so we can likely sandbox both, but gate it to be safe).
- Apply the same `env` sanitization to B.3b's soak-side gate-capture (export a
  sanitized env around the `sh -c "$GATE_VERIFY_CMD"`).
- Keep the existing watchdog memory guard (RSS cap + process-tree kill) over the
  foreign run — already in `soak_lib.sh`.
- **Network**: `sanitized_subprocess_env` removes secrets but does NOT block
  network. Full network isolation needs an OS sandbox (sandbox-exec on macOS /
  container in CI) — out of scope for the first cut; instead M4 (first-use
  review) + secrets-stripping bounds the blast radius (no secrets to exfiltrate).
  Flag network-egress hardening as a follow-up.

### M2 — Foreign draft-PR targeting (enables #2, bounded)

Generalize `chimera/core/self_pr.py::maybe_self_pr` + `submit_pr` to target the
**foreign** remote. The gates it already enforces carry over verbatim:
- opt-in `CHIMERA_SELF_PR=1` (add a distinct `CHIMERA_FOREIGN_PR` so foreign PRs
  are a *separate* opt-in, never implied by the self-PR flag),
- trust tier **≥ T4** (`MIN_TIER`, `TrustManager`),
- **gate-approved-commit** only (the ADR 0162 critic-gate log),
- **draft, never merge**; cross-repo auto-merge stays out of scope **forever** in
  this phase.

New, foreign-specific:
- Lift B.2's `no-push` pushurl **only** for the single soak branch, push it, then
  `gh pr create --draft --repo <target> --base <default> --head <soak-branch>`.
- Push auth: rely on `gh`'s existing auth (the operator's token). The token is a
  secret in the *parent* env (M1 strips it from the *gate* subprocess, not from
  the trusted push step). Confirm the push targets only the soak branch.
- Never target/force-push the target's default branch.

### M3 — Allowlist (already shipped, reaffirmed)

B.2's `CHIMERA_REPO_ALLOWLIST` (default owner `elementalcollision`, fail-closed
before any clone/agent action) is the outer gate. B.4 adds **no** widening — the
first real target is ONE allowlisted repo, chosen deliberately (M4).

### M4 — First-use human review + first-repo selection

- A **`verify_cmd` review checklist** before first use on a new repo: does it
  hit the network? download/run arbitrary scripts? need secrets? (If yes →
  don't run it unsandboxed.) Recorded in the outcome ledger.
- The **first real target** is one allowlisted repo with a deterministic,
  offline test suite and the richest backlog (ADR 0186 names claude-daemon as a
  candidate). Pick on review.
- For the **first N foreign PRs**, require explicit operator approval even at T4
  (a `CHIMERA_FOREIGN_PR_REQUIRE_APPROVAL=1` default-on) — graduate to
  autonomous foreign PRs only after a clean track record, mirroring the
  flag-graduation discipline.

## Proposed increments (each its own PR + tests)

- **B.4a — Sandbox the gate (M1).** Add `env=sanitized_subprocess_env()` to the
  foreign gate (`run_check`/`verify_at_ref` + B.3b capture), behind a `sandbox`
  flag. Self-repo path unchanged. Unit tests: secret vars absent from the gate
  subprocess env; operational vars present. **Independently valuable and
  low-risk — lands first, before any foreign push exists.**
- **B.4b — Foreign draft-PR targeting (M2).** Generalize `maybe_self_pr`/
  `submit_pr` for a foreign remote behind `CHIMERA_FOREIGN_PR=1`; trust ≥T4,
  gate-approved, draft-only, branch-scoped push. Seam-tested (no real network):
  assert the exact `gh`/`git push` argv, the draft flag, the `--repo` target, and
  every fail-closed gate. Default off.
- **B.4c — First-use checklist + ledger + approval gate (M4).** The `verify_cmd`
  review record, the require-approval default, ledger wiring.
- **B.4d — First real-repo dry-run.** A *self-clone* style smoke first (push a
  draft PR from chimera→chimera via the foreign path), then ONE allowlisted real
  repo, supervised, scheduler-off. Evidence into the outcome ledger.

Sequence rationale: **B.4a is pure hardening with no new outward action** — it
should land regardless. M2/M4 (the outward steps) come only after the sandbox.

## Open decisions for you

1. **First real target repo** — claude-daemon (per ADR 0186), or another
   allowlisted repo with a cleaner/offline suite?
2. **Approval gate** — require explicit per-PR operator approval for the first N
   foreign PRs even at T4 (recommended), and what's N?
3. **Network isolation** — accept secrets-stripping-only for the first cut (M1)
   and defer OS-level network sandboxing to a follow-up, or require it up front?
4. **Sandbox scope** — sandbox the gate for *foreign only* (safest, self
   byte-identical) or for *both* self+foreign (chimera verify needs no secrets
   either; simpler, but touches the live self-loop)?

## Falsification / abort triggers (from ADR 0186, reaffirmed)
- Any safety/scope/secrets incident on a foreign repo → **halt Pillar B**, treat
  as a gate-hardening event (ADR 0182 incident discipline).
- Foreign `verify_cmd`s too flaky across repos → narrow to deterministic/offline
  suites before broadening.
- Low foreign gate-pass rate → pause reach, invest in model/context (Pillar A).
