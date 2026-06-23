"""v4.97 (ADR 0102) — operator-side `submit-pr` verb.

Submits an agent's soak-worktree branch as a GitHub PR using the
OPERATOR's already-authenticated git config. The agent never holds
push credentials; the verb is invoked by the operator after manual
review.

See docs/adr/0102-operator-side-submit-pr.md for the threat-model
rationale on why we did NOT issue agent-side credentials.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..tools.sandbox_env import sanitized_subprocess_env

# ADR 0186 B.4b review: the foreign push/PR step runs TRUSTED tools (git/gh) that
# legitimately need VCS credentials — unlike the gate (B.4a) we cannot strip
# everything (that would drop GH_TOKEN and break auth). For a FOREIGN target,
# strip the LLM/search PROVIDER keys (never needed by git/gh) but RESTORE the VCS
# auth tokens. The self-repo path passes env=None → byte-identical inherited env.
_VCS_AUTH_KEEP = (
    "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
)


def _foreign_push_env() -> dict[str, str]:
    """Env for a FOREIGN push/PR subprocess: provider secrets stripped, VCS auth
    kept (ADR 0186 B.4b/M1 — narrows the secret surface without breaking gh)."""
    env = sanitized_subprocess_env()
    for k in _VCS_AUTH_KEEP:
        v = os.environ.get(k)
        if v is not None:
            env[k] = v
    return env


# Charter soaks name branches chimera-soak/v<N>-...; real-task / self-determined
# soaks name them chimera-soak/realtask-<stamp> (ADR 0158). Accept both.
SOAK_BRANCH_PATTERN = re.compile(
    r"^chimera-soak/(?:v\d+(?:[-_/].+)?|realtask-.+)$"
)

# Files that must never be in an agent-submitted diff.
SECRET_PATH_BLOCKLIST = (
    ".env",
    ".envrc",
    "state/trust_state.json",
)
SECRET_PATH_GLOB_PATTERNS = (
    re.compile(r"(^|/)\.env(\.|$)"),
    re.compile(r"(^|/)\.ssh(/|$)"),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
)

# High-entropy heuristic: ≥40 chars of base64-ish alphabet. Length alone
# false-positives on long snake_case identifiers (e.g. a test function name
# `test_parse_line_with_tabs_only_in_fields`), so a candidate is only a hit if
# its Shannon entropy also clears _ENTROPY_MIN_BITS — real base64/hex secrets are
# near-random (high entropy); English-ish identifiers are not.
HIGH_ENTROPY_PATTERN = re.compile(r"[A-Za-z0-9+/=_-]{40,}")
_ENTROPY_MIN_BITS = 4.0


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())

# Allow-listed operator-commit shapes (subject prefixes). Commits in a
# soak branch that do NOT start with `[agent]` must match one of these
# to be considered legitimate operator activity (e.g. the runner edits,
# post-mortems committed into the worktree before kick-off).
OPERATOR_COMMIT_PREFIXES = (
    "soak ",
    "soak v",
    "soak runner",
    "post-mortem",
    "v4.",
    "Merge ",
    "fix:",
    "chore:",
    "charter",  # self-authored charter materialization (ADR 0153) — the
                # operator/origination setup commit that precedes a Create build,
                # analogous to a post-mortem commit landed before kick-off.
)


@dataclass
class SubmitPrResult:
    ok: bool = False
    branch: str = ""
    commits: list[tuple[str, str]] = field(default_factory=list)  # (sha, subject)
    validation_errors: list[str] = field(default_factory=list)
    pr_url: str | None = None
    dry_run: bool = False
    pushed: bool = False
    audit_path: Path | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "branch": self.branch,
            "commits": [{"sha": s, "subject": sub} for s, sub in self.commits],
            "validation_errors": self.validation_errors,
            "pr_url": self.pr_url,
            "dry_run": self.dry_run,
            "pushed": self.pushed,
        }


def _run_git(
    *args: str,
    cwd: Path,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=check,
        capture_output=capture,
        text=True,
    )


def _is_agent_commit(subject: str) -> bool:
    return subject.startswith("[agent]")


def _is_operator_commit(subject: str) -> bool:
    return any(subject.startswith(pfx) for pfx in OPERATOR_COMMIT_PREFIXES)


def _has_secret_path(path: str) -> bool:
    if path in SECRET_PATH_BLOCKLIST:
        return True
    return any(p.search(path) for p in SECRET_PATH_GLOB_PATTERNS)


def _is_snake_identifier(tok: str) -> bool:
    """True for a snake_case identifier — underscore-joined segments that are each
    purely alphabetic or purely numeric (e.g. a long descriptive test name like
    ``test_observationwindow_default_max_size_is_50``). Shannon entropy cannot
    separate such a name (~4.0 bits/char, esp. with digits) from a hex secret
    (~4.0), so this STRUCTURAL check excludes the identifier false-positive without
    unmasking secrets: a real base64/hex token has no underscores (→ not matched)
    or mixed-charset segments (a secret-bearing ``key_AKIA1b2c3`` segment is
    neither all-alpha nor all-digit, so the token is still flagged)."""
    if "_" not in tok:
        return False
    return all(s.isalpha() or s.isdigit() for s in tok.split("_") if s)


def _entropy_hits(diff_text: str) -> list[str]:
    hits: list[str] = []
    for line in diff_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for m in HIGH_ENTROPY_PATTERN.finditer(line):
            tok = m.group(0)
            if _shannon_entropy(tok) < _ENTROPY_MIN_BITS:
                continue  # word-like identifier, not a secret
            if _is_snake_identifier(tok):
                continue  # descriptive snake_case name (e.g. a long test fn), not a secret
            if tok not in hits:
                hits.append(tok)
    return hits


def _check_inbox_honesty(
    worktree: Path,
) -> list[tuple[str, list[str]]]:
    """v4.100 (ADR 0104): the pre-PR INBOX-honesty gate.

    Parse ``<worktree>/mind/INBOX.md``. For every `[x]` bullet, extract
    any expected_artifacts the bullet names; refuse the PR if any of
    those artifacts is missing or empty on disk. Returns the list of
    invalid claims; empty list means the INBOX is honest.

    Unfalsifiable bullets (no artifact named) don't fire — the gate
    can only verify claims with concrete deliverables.
    """
    inbox = worktree / "mind" / "INBOX.md"
    if not inbox.exists() or not inbox.is_file():
        return []
    try:
        text = inbox.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    # Import locally to keep submit_pr import-light for the CLI.
    from .act import (
        _inbox_bullet_artifacts,
        _parse_inbox_tasks,
        check_artifacts,
        check_content_markers,
        expected_content_markers,
    )
    invalid: list[tuple[str, list[str]]] = []
    for _idx, state, task_text in _parse_inbox_tasks(text):
        if state != "x":
            continue
        expected = _inbox_bullet_artifacts(task_text)
        if not expected:
            continue
        missing = check_artifacts(expected, base_dir=worktree)
        markers_by_path = expected_content_markers(task_text)
        if markers_by_path:
            incomplete = check_content_markers(
                markers_by_path, base_dir=worktree,
            )
            for path, _marker in incomplete:
                if path not in missing:
                    missing.append(path)
        if missing:
            invalid.append((task_text, missing))
    return invalid


def _source_is_covered(
    source: str,
    changed_tests: list[str],
    test_bodies: dict[str, str],
    worktree: Path | None,
) -> bool:
    """True if ``source`` (a ``chimera/…/foo.py``) is covered by a test that genuinely
    RELATES to it: a CHANGED test that name-corresponds (``tests/test_foo.py`` or a
    ``test_foo_*.py`` variant) OR imports the source's module
    (``from chimera.core.foo import …``); or, for behaviour-neutral cleanups, a
    name-corresponding ``tests/test_foo.py`` that already EXISTS."""
    stem = Path(source).stem                  # "crawl_ledger"
    module = source[:-3].replace("/", ".")    # "chimera.core.crawl_ledger"

    def name_matches(test_name: str) -> bool:
        return test_name == f"test_{stem}.py" or test_name.startswith(f"test_{stem}_")

    # (a) a CHANGED test that name-corresponds OR imports the source module.
    for t in changed_tests:
        if name_matches(Path(t).name) or module in test_bodies.get(t, ""):
            return True
    # (b) a name-corresponding test already EXISTS (precision: behaviour-neutral
    #     cleanup of already-tested source — the existing suite is its coverage).
    if worktree is not None and (worktree / "tests" / f"test_{stem}.py").exists():
        return True
    return False


def _check_fix_without_test(
    changed_files: list[str], worktree: Path | None = None
) -> list[str]:
    """v4.92 gate: chimera/ source must be COVERED by tests. Returns uncovered
    sources (empty = pass).

    A touched source is covered when a test in the branch genuinely RELATES to it —
    by NAME (a changed/existing ``tests/test_<name>.py`` or ``test_<name>_*.py``) or by
    IMPORT (a changed test imports the source's module). The import signal is the
    precision upgrade (2026-06-23 triage, arXiv:2606.18168 "Oracle Signals in
    Agent-Authored Test Code"): the old check counted ANY touched ``tests/`` file as
    coverage for ALL touched source — a 'touched-test ⇒ verified' over-estimate a diff
    editing an *unrelated* test could exploit. Pure name-correspondence is too strict
    for Chimera (``tiers.py`` is tested by ``test_tier_model_ids.py``), so the import
    relation is accepted too. Case (b) — a name-matching test already EXISTS — keeps
    the 2026-06-03 precision fix for behaviour-neutral cleanups of already-tested
    source. ``worktree=None`` (conservative) restricts to the name signal on changed
    tests. This is the CHEAP first-pass; the soak's mutation/faithfulness gate is the
    authoritative 'does the test actually verify' check (B.4k).
    """
    src = [
        p for p in changed_files
        if p.startswith("chimera/")
        and p.endswith(".py")
        and p not in ("chimera/__init__.py", "chimera/_version.py")
    ]
    if not src:
        return []
    changed_tests = [
        c for c in changed_files if c.startswith("tests/") and c.endswith(".py")
    ]
    # Read changed test bodies once (for the import relation); only with a worktree.
    test_bodies: dict[str, str] = {}
    if worktree is not None:
        for t in changed_tests:
            try:
                test_bodies[t] = (worktree / t).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                test_bodies[t] = ""
    return [
        p for p in src
        if not _source_is_covered(p, changed_tests, test_bodies, worktree)
    ]


def _validate_tests_actually_pass(
    worktree: Path, changed_files: list[str],
) -> list[str]:
    """v4.113 (ADR 0113): runtime-behavior gate on tests/test_*.py files
    that the branch modified.

    Re-runs pytest from the operator side against every modified
    ``tests/test_*.py`` file. Any non-zero exit becomes a validation
    error so the PR is refused. Soak v16 (PR #5) shipped a branch
    whose tests/test_doctor.py imported a module that raised
    ``NameError`` at collection time — the per-task ACT-time
    detector covers the in-soak signal; this branch-scope gate is
    the defense-in-depth check at submit time.

    Returns the list of failing test paths (empty when all pass or
    no tests/test_*.py file was touched). Never raises: any
    subprocess fault (missing pytest, timeout) returns [] so an
    unreachable runner doesn't block a legitimate PR.
    """
    test_files = [
        p for p in changed_files
        if p.startswith("tests/")
        and Path(p).name.startswith("test_")
        and p.endswith(".py")
    ]
    if not test_files:
        return []
    # v4.113 / PR #6 review-round-2: delegate to the shared runner
    # helper so this gate inherits the uv→sys.executable fallback and
    # the "No module named pytest" environmental-skip detection.
    from .act import _run_pytest_file
    failing: list[str] = []
    for rel in test_files:
        target = worktree / rel
        if not target.exists():
            continue
        run = _run_pytest_file(rel, worktree, timeout=180)
        if run is None:
            continue  # environmental — no pytest available
        returncode, _ = run
        # Only fire on pytest exit code 1 (true test failures). Codes
        # 2 (collection/import error), 3 (internal), 4 (usage), 5
        # (no tests collected) are environmental ambiguities.
        if returncode == 1:
            failing.append(rel)
    return failing


def _worktree_branch(worktree: Path) -> str:
    proc = _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=worktree)
    return proc.stdout.strip()


def _dirty_paths(worktree: Path, ignore_prefixes: tuple[str, ...] = ()) -> list[str]:
    """Worktree paths that are dirty (modified/untracked/staged) after dropping any
    matching ``ignore_prefixes``. The single source of truth for "what is dirty" —
    used by :func:`_porcelain_clean` (cleanliness), :func:`validate` (to name the
    offenders in its error), and :func:`revert_out_of_scope_residue` (to revert)."""
    proc = _run_git("status", "--porcelain", cwd=worktree)
    out: list[str] = []
    for ln in proc.stdout.splitlines():
        if not ln.strip():
            continue
        path = ln[3:].strip()  # porcelain: "XY <path>"
        if " -> " in path:  # rename: keep the destination
            path = path.split(" -> ", 1)[1]
        if ignore_prefixes and any(path.startswith(p) for p in ignore_prefixes):
            continue
        out.append(path)
    return out


def _porcelain_clean(worktree: Path, ignore_prefixes: tuple[str, ...] = ()) -> bool:
    """True if the worktree is clean. ``ignore_prefixes`` (e.g. ``("mind/",)``)
    excludes operational-journal noise that is never part of a deliverable PR —
    the agent's mind/* heartbeat/inbox/session writes happen AFTER its commit and
    are not pushed, so they must not block an otherwise-clean self-PR."""
    return not _dirty_paths(worktree, ignore_prefixes)


def revert_out_of_scope_residue(
    worktree: Path | str, *, keep_prefixes: tuple[str, ...] = ()
) -> list[str]:
    """Revert a foreign clone's working tree to ``HEAD`` + operational paths,
    returning the sorted out-of-scope paths it reverted/removed (ADR 0186 B.4g).

    A faithful scoped foreign run commits ONLY its allowlist (B.4e
    ``git add -- $TASK_FILES``). Anything else the run leaves UNCOMMITTED in the
    tree is by definition out of scope and must never reach the PR — most often a
    tree-wide ``ruff --fix`` that deleted unused imports across the whole foreign
    repo (the first claude-daemon dry run left ~44 such files), or a scratch file.
    Because the allowlist is already in ``HEAD``, reverting every uncommitted change
    preserves it and strips only the residue. ``keep_prefixes`` (e.g. ``mind/``,
    ``state/``, ``.venv/``) are operational dirs the soak writes that the clean-tree
    gate already ignores — left in place for forensics.

    This ENFORCES the scope invariant on the working tree (chimera's in-loop
    ``scope_check`` is staged-index-only and is blind to unstaged sprawl); the
    caller MUST log the returned paths loudly so an over-running agent is visible,
    never silently masked. Self runs never call this (their tree stays clean)."""
    worktree = Path(worktree)
    residue = _dirty_paths(worktree, ignore_prefixes=keep_prefixes)
    if not residue:
        return []
    _run_git("reset", "-q", "HEAD", cwd=worktree)         # unstage everything → HEAD
    _run_git("checkout", "-q", "--", ".", cwd=worktree)   # revert tracked → HEAD
    clean_args = ["clean", "-fdq"]
    for p in keep_prefixes:                                # keep operational untracked
        clean_args += ["-e", p.rstrip("/")]
    _run_git(*clean_args, cwd=worktree)                    # remove untracked residue
    return sorted(residue)


def _commits_between(worktree: Path, base: str, head: str) -> list[tuple[str, str]]:
    proc = _run_git(
        "log", f"{base}..{head}", "--pretty=%H%x09%s",
        cwd=worktree,
    )
    rows: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        if "\t" not in line:
            continue
        sha, subject = line.split("\t", 1)
        rows.append((sha, subject))
    return rows


def _diff_text(worktree: Path, base: str, head: str) -> str:
    proc = _run_git("diff", f"{base}...{head}", cwd=worktree)
    return proc.stdout


def _changed_files(worktree: Path, base: str, head: str) -> list[str]:
    proc = _run_git(
        "diff", "--name-only", f"{base}...{head}",
        cwd=worktree,
    )
    return [ln for ln in proc.stdout.splitlines() if ln.strip()]


def validate(
    worktree: Path,
    base: str = "main",
    *,
    allow_entropy: bool = False,
    ignore_dirty_prefixes: tuple[str, ...] = (),
    foreign: bool = False,
) -> tuple[str, list[tuple[str, str]], list[str]]:
    """Run all pre-submit checks. Return (branch, commits, errors).

    ``ignore_dirty_prefixes`` excludes operational paths (e.g. ``("mind/",)``)
    from the clean-tree check — see :func:`_porcelain_clean`.

    ``foreign`` (ADR 0186 B.4e): skip the chimera-SPECIFIC quality checks that
    assume chimera's layout/toolchain — ``_check_fix_without_test`` (keys on
    ``chimera/``+``tests/``), the v4.113 chimera-``pytest`` re-run, and the
    ``mind/INBOX`` honesty check. The foreign repo's OWN ``verify_cmd`` is the
    quality gate (checked by ``maybe_foreign_pr`` before submit). The STRUCTURAL
    and SAFETY checks (worktree, soak-branch, clean tree, commits exist,
    ``[agent]`` subject, secret-path, entropy, witness) always run.
    """
    errors: list[str] = []

    if not (worktree / ".git").exists() and not _looks_like_worktree(worktree):
        errors.append(f"not a git worktree: {worktree}")
        return "", [], errors

    branch = _worktree_branch(worktree)
    if not SOAK_BRANCH_PATTERN.match(branch):
        errors.append(
            f"branch {branch!r} does not match soak pattern "
            f"{SOAK_BRANCH_PATTERN.pattern!r}"
        )

    if not _porcelain_clean(worktree, ignore_prefixes=ignore_dirty_prefixes):
        _dirty = _dirty_paths(worktree, ignore_dirty_prefixes)
        _shown = ", ".join(_dirty[:10]) + (
            f" (+{len(_dirty) - 10} more)" if len(_dirty) > 10 else ""
        )
        errors.append(
            f"worktree has uncommitted changes (git status not clean): {_shown}"
        )

    commits = _commits_between(worktree, base, "HEAD")
    if not commits:
        errors.append(f"no commits between {base} and HEAD")

    for sha, subject in commits:
        if _is_agent_commit(subject) or _is_operator_commit(subject):
            continue
        errors.append(
            f"commit {sha[:8]} subject {subject!r} is neither [agent] "
            f"nor an allow-listed operator shape"
        )

    files = _changed_files(worktree, base, "HEAD")
    for p in files:
        if _has_secret_path(p):
            errors.append(f"diff touches secret-shaped path: {p}")

    # The next three gates are chimera-SPECIFIC (layout/toolchain/INBOX) — the
    # foreign repo's own verify_cmd is its quality gate instead (ADR 0186 B.4e).
    if not foreign:
        untested = _check_fix_without_test(files, worktree)
        if untested:
            errors.append(
                "fix_without_test (v4.92 gate): chimera/ source touched without "
                f"tests/ counterpart: {', '.join(untested)}"
            )

        # v4.113 (ADR 0113): runtime-behavior gate. Re-run pytest against
        # every modified tests/test_*.py file. Catches the soak v16 shape
        # where the branch shipped a NameError-at-runtime regression that
        # all the structural gates (parse, presence, charter) cleared.
        failing_tests = _validate_tests_actually_pass(worktree, files)
        if failing_tests:
            errors.append(
                "test_claim_invalid (v4.113 gate): modified test file(s) fail "
                f"on operator-side re-run: {', '.join(failing_tests)}"
            )

        # v4.100 (ADR 0104): INBOX-honesty gate. If the branch's
        # mind/INBOX.md has any `[x]` checkbox whose deliverable doesn't
        # exist on disk, refuse the PR — the branch is shipping a lie.
        invalid_inbox = _check_inbox_honesty(worktree)
        if invalid_inbox:
            listed = "; ".join(
                f"{t[:60]!r} → missing {', '.join(m)}"
                for t, m in invalid_inbox[:3]
            )
            more = (
                f" (+{len(invalid_inbox) - 3} more)"
                if len(invalid_inbox) > 3 else ""
            )
            errors.append(
                "inbox_claim_invalid (v4.100 gate): mind/INBOX.md has `[x]` "
                f"checkbox(es) whose deliverables don't exist{more}: {listed}"
            )

    if not allow_entropy:
        diff = _diff_text(worktree, base, "HEAD")
        hits = _entropy_hits(diff)
        if hits:
            preview = ", ".join(h[:12] + "…" for h in hits[:3])
            errors.append(
                f"high-entropy strings in diff ({len(hits)} hit(s)): {preview} "
                "— pass --allow-entropy if false-positive"
            )

    # v4.102 (ADR 0106): witness review on the cumulative branch diff.
    # Defense-in-depth alongside the per-task ACT-time check — catches
    # foundational-code defects that no single task tripped but that
    # accumulated across the branch. Graceful: only runs when witness
    # is enabled AND an API key is available; otherwise skipped silently
    # so existing unit-tests / dry-runs still work.
    witness_concerns = _maybe_witness_branch(worktree, base, files)
    if witness_concerns:
        listed = "; ".join(witness_concerns[:3])
        errors.append(
            f"witness_rejected (v4.102 gate): branch diff has unresolved "
            f"witness concerns: {listed}"
        )

    return branch, commits, errors


def _maybe_witness_branch(
    worktree: Path, base: str, files: list[str],
) -> list[str]:
    """Run the v4.102 witness gate on the cumulative branch diff.

    Returns the list of concerns when the witness rejects, ``[]`` on
    approval, and ``[]`` (silently) when witnessing is disabled or
    the environment can't support a live provider call. We never raise
    out of this helper; an unreachable witness must not block PR
    submission — that's a strictly worse failure mode than a witness
    that misses a defect.
    """
    import os
    from .witness import should_witness, witness_enabled

    if not witness_enabled():
        return []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return []
    paths = should_witness(files)
    if not paths:
        return []
    try:
        import asyncio
        from ..providers import AnthropicProvider
        from .witness import witness_code_change

        diff = _diff_text(worktree, base, "HEAD")
        if not diff.strip():
            return []
        provider = AnthropicProvider()
        verdict = asyncio.run(witness_code_change(
            task_text=(
                "Pre-PR review: cumulative branch diff vs "
                f"`{base}`. Treat this as a single change spanning "
                "all the listed paths; flag structural defects, "
                "correctness gaps, or convention breaks."
            ),
            diff=diff[:64_000],
            paths=paths,
            provider=provider,
        ))
        if verdict.approved:
            return []
        return verdict.concerns
    except Exception:
        # Witness path is best-effort at PR time; never block on
        # provider/network/import faults.
        return []


def _looks_like_worktree(worktree: Path) -> bool:
    # `.git` in a linked worktree is a FILE pointing at the gitdir.
    g = worktree / ".git"
    return g.exists() or g.is_file()


def _default_title(commits: list[tuple[str, str]]) -> str:
    if not commits:
        return "[agent] (no commits)"
    # First (oldest) commit's subject. `git log` lists newest-first; reverse.
    _, subject = commits[-1]
    if subject.startswith("[agent]"):
        return subject
    return f"[agent] {subject}"


def _build_body(
    *,
    worktree: Path,
    branch: str,
    commits: list[tuple[str, str]],
    postmortem_text: str | None,
) -> str:
    soak_match = re.search(r"v(\d+)", branch)
    soak_version = soak_match.group(0) if soak_match else "unknown"

    lines: list[str] = []
    lines.append(f"**Soak**: {soak_version}")
    lines.append(f"**Worktree**: `{worktree}`")
    lines.append(f"**Branch**: `{branch}`")
    lines.append("")

    if postmortem_text:
        lines.append("## Post-mortem")
        lines.append("")
        lines.append(postmortem_text.strip())
        lines.append("")

    lines.append("## Commits in this PR")
    lines.append("")
    for sha, subject in reversed(commits):  # oldest first
        marker = "🤖" if _is_agent_commit(subject) else "👤"
        lines.append(f"- {marker} `{sha[:8]}` {subject}")
    lines.append("")

    db = worktree / "state" / "chimera.db"
    if db.exists():
        try:
            counts = _finish_reason_counts(db)
            if counts:
                lines.append("## Escalation summary (from worktree DB)")
                lines.append("")
                for reason, n in counts:
                    lines.append(f"- `{reason}`: {n}")
                lines.append("")
        except Exception as e:  # pragma: no cover
            lines.append(f"_(could not read escalation summary: {e})_")
            lines.append("")

    lines.append("## Reviewer checklist")
    lines.append("")
    lines.append("- [ ] Diff matches the post-mortem narrative")
    lines.append("- [ ] No secret-shaped paths or tokens (auto-checked, confirm anyway)")
    lines.append("- [ ] `chimera/` changes have corresponding `tests/` coverage")
    lines.append("- [ ] Trust trajectory acceptable (no unexplained T0/lockdown)")
    lines.append("")
    lines.append(
        "_Submitted via `chimera submit-pr` (v4.97, ADR 0102). "
        "Agent does not hold push credentials._"
    )
    return "\n".join(lines)


def _finish_reason_counts(db: Path) -> list[tuple[str, int]]:
    import sqlite3
    conn = sqlite3.connect(str(db))
    try:
        cur = conn.execute(
            "SELECT finish_reason, COUNT(*) FROM api_calls "
            "WHERE finish_reason IS NOT NULL "
            "GROUP BY finish_reason ORDER BY 2 DESC"
        )
        return [(r[0], int(r[1])) for r in cur.fetchall()]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _append_audit(
    audit_path: Path,
    payload: dict,
) -> None:
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with audit_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")


def submit_pr(
    *,
    worktree: Path,
    repo_root: Path,
    base: str = "main",
    title: str | None = None,
    body: str | None = None,
    body_from_postmortem: Path | None = None,
    draft: bool = True,
    dry_run: bool = False,
    allow_entropy: bool = False,
    ignore_dirty_prefixes: tuple[str, ...] = (),
    audit_path: Path | None = None,
    foreign_repo: str | None = None,
    foreign_base: str | None = None,
    gh_runner=None,
    push_runner=None,
) -> SubmitPrResult:
    """Run validations, push from `repo_root`, open PR via `gh`.

    `gh_runner` / `push_runner` are seams for tests. Each is a callable;
    if None we shell out for real. `ignore_dirty_prefixes` forwards to
    :func:`validate` (e.g. ``("mind/",)`` for self-PR journal noise).

    Foreign mode (ADR 0186 B.4b): when ``foreign_repo`` ("owner/name") is set,
    the PR targets that repo instead of ``repo_root``'s origin — the soak branch
    is pushed to the foreign repo's explicit HTTPS URL (bypassing the B.2
    no-push:// block, authed by the operator's stored gh credentials) and
    ``gh pr create --repo <foreign_repo> --base <foreign_base>`` opens the draft
    there. ``foreign_repo`` unset → byte-identical self-repo behaviour. The same
    ``validate()`` gates apply; still DRAFT-only, still pushes ONLY the soak
    branch, never the default branch.
    """
    audit_path = audit_path or (repo_root / "state" / "submit_pr_log.jsonl")
    result = SubmitPrResult(dry_run=dry_run, audit_path=audit_path)

    branch, commits, errors = validate(
        worktree, base=base, allow_entropy=allow_entropy,
        ignore_dirty_prefixes=ignore_dirty_prefixes,
        foreign=bool(foreign_repo),
    )
    result.branch = branch
    result.commits = commits
    result.validation_errors = errors

    if errors:
        result.ok = False
        _append_audit(audit_path, {
            "event": "submit_pr.reject",
            "worktree": str(worktree),
            "branch": branch,
            "errors": errors,
        })
        return result

    if title is None:
        title = _default_title(commits)

    if body is None:
        pm_text: str | None = None
        if body_from_postmortem:
            try:
                pm_text = body_from_postmortem.read_text(encoding="utf-8")
            except OSError as e:
                result.ok = False
                result.validation_errors.append(
                    f"could not read postmortem {body_from_postmortem}: {e}"
                )
                _append_audit(audit_path, {
                    "event": "submit_pr.reject",
                    "worktree": str(worktree),
                    "branch": branch,
                    "errors": result.validation_errors,
                })
                return result
        body = _build_body(
            worktree=worktree, branch=branch, commits=commits,
            postmortem_text=pm_text,
        )

    if dry_run:
        result.ok = True
        _append_audit(audit_path, {
            "event": "submit_pr.dry_run",
            "worktree": str(worktree),
            "branch": branch,
            "title": title,
            "commits": [s for s, _ in commits],
        })
        return result

    # Push from repo root (operator git config), NOT from worktree
    # (which has the no-push:// block). Foreign mode (ADR 0186 B.4b): push the
    # soak branch to the target's explicit HTTPS URL — the foreign clone's origin
    # carries B.2's no-push:// pushurl, so an explicit URL is how we push at all,
    # and it scopes the push to exactly one branch on exactly the target repo.
    push_target = f"https://github.com/{foreign_repo}.git" if foreign_repo else "origin"
    push_cmd = ["git", "-C", str(repo_root), "push", push_target, f"{branch}:{branch}"]
    # Foreign push/PR: strip provider keys, keep VCS auth. Self path: inherit (None).
    push_env = _foreign_push_env() if foreign_repo else None
    if push_runner is None:
        push_proc = subprocess.run(push_cmd, capture_output=True, text=True, env=push_env)
        push_ok = push_proc.returncode == 0
        push_err = push_proc.stderr
    else:
        push_ok, push_err = push_runner(push_cmd)

    if not push_ok:
        result.ok = False
        result.validation_errors.append(f"git push failed: {push_err.strip()}")
        _append_audit(audit_path, {
            "event": "submit_pr.push_failed",
            "worktree": str(worktree),
            "branch": branch,
            "error": push_err.strip(),
        })
        return result
    result.pushed = True

    gh_cmd = [
        "gh", "pr", "create",
        "--base", (foreign_base or base) if foreign_repo else base,
        "--head", branch,
        "--title", title,
        "--body", body,
    ]
    if foreign_repo:
        # Target the foreign repo explicitly (otherwise gh infers from cwd).
        # Insert after "create" (index 3): gh pr create --repo <repo> --base …
        gh_cmd[3:3] = ["--repo", foreign_repo]
    if draft:
        gh_cmd.append("--draft")
    if gh_runner is None:
        gh_proc = subprocess.run(gh_cmd, capture_output=True, text=True, cwd=str(repo_root), env=push_env)
        gh_ok = gh_proc.returncode == 0
        gh_out = gh_proc.stdout.strip()
        gh_err = gh_proc.stderr.strip()
    else:
        gh_ok, gh_out, gh_err = gh_runner(gh_cmd)

    if not gh_ok:
        result.ok = False
        result.validation_errors.append(f"gh pr create failed: {gh_err}")
        _append_audit(audit_path, {
            "event": "submit_pr.gh_failed",
            "worktree": str(worktree),
            "branch": branch,
            "error": gh_err,
        })
        return result

    # gh prints the PR URL on stdout.
    result.pr_url = gh_out.splitlines()[-1] if gh_out else None
    result.ok = True
    _append_audit(audit_path, {
        "event": "submit_pr.success",
        "worktree": str(worktree),
        "branch": branch,
        "title": title,
        "draft": draft,
        "pr_url": result.pr_url,
        "commits": [s for s, _ in commits],
        # ADR 0186 B.4b: tag foreign-target PRs in the audit trail.
        **({"foreign": True, "target_repo": foreign_repo} if foreign_repo else {}),
    })
    return result
