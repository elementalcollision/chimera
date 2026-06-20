"""ADR 0186 B.4h — confine the agent's ``ruff --fix`` to the locked charter.

The ACT prompt tells the agent to clear lint by running
``ruff check --fix <each SCOPE file>``. On a foreign repo it instead ran ruff
TREE-WIDE, rewriting ~44 out-of-charter files (the B.4g root cause). B.4g reverts
that residue harness-side AFTER the fact; this guard stops it at the SOURCE — the
shell-tool chokepoint — so the agent never edits files outside its charter in the
first place. Defence-in-depth: B.4g is the backstop, this is the prevention.

The pure decision logic lives here (no I/O) so it is exhaustively unit-testable;
``chimera.tools.shell`` loads the active allowlist (via ``scope_check``) and calls
:func:`ruff_scope_violation` at the same chokepoint as the pre-commit scope check.
"""

from __future__ import annotations

import os

# Runner wrappers the agent uses to reach ruff. Bare ``ruff`` is not on the shell
# allow-list, so in practice it is always ``uv run ruff``; the others are accepted
# defensively so a different invocation form can never slip past the guard.
_RUNNERS = frozenset({"uv", "uvx", "python", "python3", "ruff"})

# ruff's own subcommands. Used to locate the REAL ruff program token: an arbitrary
# wrapper flag may carry the literal value ``ruff`` (e.g. ``uv run --with ruff
# ruff …``), so we identify the program ``ruff`` as the one whose NEXT token is a
# ruff subcommand / flag / end-of-args, not merely the first ``ruff`` we see
# (B.4h review M2 — ``argv.index('ruff')`` locked onto the flag value).
_RUFF_SUBCOMMANDS = frozenset(
    {"check", "format", "clean", "rule", "config", "linter", "version", "help",
     "analyze", "server"}
)

# ruff flags that consume the NEXT token as their value — so that token is a flag
# value, NOT a path operand, and must be skipped when extracting operands. The
# ``--flag=value`` form carries its value inline and needs no skip. Completed per
# B.4h review M3: a MISSING value-flag both hides a path operand (bypass) AND can
# mistake a flag value for an out-of-charter path (false-positive block).
_RUFF_VALUE_FLAGS = frozenset(
    {
        "--select",
        "--extend-select",
        "--ignore",
        "--extend-ignore",
        "--per-file-ignores",
        "--extend-per-file-ignores",
        "--fixable",
        "--unfixable",
        "--extend-fixable",
        "--extend-unfixable",
        "--config",
        "--target-version",
        "--line-length",
        "--output-format",
        "--output-file",
        "-o",
        "--extension",
        "--exclude",
        "--extend-exclude",
        "--stdin-filename",
        "--cache-dir",
        "--required-version",
        "--color",
        "--range",
    }
)


def ruff_subargv(argv: list[str]) -> list[str] | None:
    """Return the argv slice from the real ``ruff`` program token onward, or
    ``None`` if this is not a ruff invocation. Robust against ``uv run`` / ``uvx``
    / ``python -m`` wrappers AND wrapper flags that carry ``ruff`` as a VALUE
    (``uv run --with ruff ruff …``, ``uvx --from ruff ruff …``, ``uv run python
    -m ruff …``): the program ``ruff`` is the first ``ruff`` whose next token is a
    ruff subcommand, a flag, or end-of-args — never a bare ``ruff`` sitting as a
    flag's value (B.4h review M2)."""
    if not argv or argv[0] not in _RUNNERS:
        return None
    for i, tok in enumerate(argv):
        if tok != "ruff":
            continue
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        if nxt is None or nxt.startswith("-") or nxt in _RUFF_SUBCOMMANDS:
            return argv[i:]
    return None


def _is_mutating(sub: list[str]) -> bool:
    """True if a ruff sub-argv (starting at the ``ruff`` token) rewrites files on
    disk. Mutating forms: ``check`` with ``--fix``/``--fix-only``/``--add-noqa``
    (B.4h review M1 — ``--add-noqa`` inserts ``# noqa`` into every matched file),
    or ``format`` (without ``--check``/``--diff``). ``--diff`` previews without
    writing, so it is never mutating. A plain ``ruff check`` only reports."""
    rest = sub[1:]
    # The subcommand is the first non-flag token; ruff defaults to ``check`` when
    # handed flags directly (e.g. ``ruff --fix x.py``).
    subcmd = "check"
    body = rest
    if rest and not rest[0].startswith("-"):
        subcmd, body = rest[0], rest[1:]
    if subcmd == "check":
        if "--diff" in body:  # preview only — implies --fix-only, no write
            return False
        fix = False
        for t in body:  # last-wins so a trailing --no-fix can disable it
            if t in ("--fix", "--fix-only") or t.startswith("--add-noqa"):
                fix = True
            elif t in ("--no-fix", "--no-fix-only"):
                fix = False
        return fix
    if subcmd == "format":
        return not any(t in ("--check", "--diff") for t in body)
    return False


def _operands(sub: list[str]) -> list[str]:
    """The path operands of a ruff sub-argv: positional args, skipping flags and
    the values of value-taking flags. Everything after a ``--`` is an operand."""
    rest = sub[1:]
    if rest and not rest[0].startswith("-"):
        rest = rest[1:]  # drop the subcommand token (check/format)
    operands: list[str] = []
    skip = False
    after_ddash = False
    for tok in rest:
        if after_ddash:
            operands.append(tok)
            continue
        if skip:
            skip = False
            continue
        if tok == "--":
            after_ddash = True
            continue
        if tok.startswith("-"):
            if tok in _RUFF_VALUE_FLAGS:  # its value is the next token
                skip = True
            continue
        operands.append(tok)
    return operands


def _resolve_for_compare(path: str, repo_root: str | None) -> str:
    """Canonicalise a path for charter comparison. With ``repo_root`` set (the
    production path) use ``os.path.realpath`` against it — this collapses ``..``
    AND resolves symlinks, matching the load-bearing ``Path.resolve()`` discipline
    in ``shell._resolve_cwd`` so a symlinked operand can't point outside the
    charter (B.4h review). With ``repo_root`` None (pure unit tests) fall back to
    lexical ``normpath`` — still ``..``-safe, just not symlink-aware."""
    if repo_root is None:
        return os.path.normpath(path)
    base = path if os.path.isabs(path) else os.path.join(repo_root, path)
    return os.path.realpath(base)


def ruff_scope_violation(
    argv: list[str],
    allowed_paths: tuple[str, ...],
    *,
    repo_root: str | None = None,
) -> str | None:
    """Return a human-readable violation message if ``argv`` is a *mutating* ruff
    command that would touch files outside ``allowed_paths``, else ``None``.

    Conservative — returns ``None`` (no enforcement) when:
      * this is not a mutating ruff command (non-ruff, or report-only ``check``), or
      * ``allowed_paths`` is empty — there is no locked charter to enforce against
        (outside a scoped soak), matching ``scope_check``'s warn-only posture. (The
        shell wiring layers a fail-CLOSED check on top of this for the in-soak
        anomaly where a charter *should* exist but could not be resolved.)

    Otherwise a mutating ruff command is a violation unless it lists path operands
    that are ALL within the charter: no operands (tree-wide), a directory operand
    (e.g. ``.`` or ``tools/``), or any file outside the allowlist all fail.
    ``repo_root`` enables symlink-resolving comparison (see :func:`_resolve_for_compare`)."""
    sub = ruff_subargv(argv)
    if sub is None or not _is_mutating(sub):
        return None
    if not allowed_paths:
        return None
    allowed = {_resolve_for_compare(p, repo_root) for p in allowed_paths}
    operands = _operands(sub)
    shown = sorted(allowed_paths)
    example = ", ".join(repr(p) for p in shown)
    if not operands:
        return (
            "`ruff` would run TREE-WIDE (no path operand given), rewriting files "
            f"across the whole repo. A scoped task may only --fix its charter "
            f"files: {shown}. Pass them explicitly, e.g. "
            f'argv=["uv","run","ruff","check","--fix", {example}].'
        )
    bad = sorted(
        {op for op in operands if _resolve_for_compare(op, repo_root) not in allowed}
    )
    if bad:
        return (
            f"`ruff` targets out-of-charter paths {bad} (charter allows only "
            f"{shown}). A scoped task may only --fix its own files — "
            "pass the charter files explicitly as operands (no directories)."
        )
    return None
