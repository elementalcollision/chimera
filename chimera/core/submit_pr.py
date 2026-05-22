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
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path


SOAK_BRANCH_PATTERN = re.compile(r"^chimera-soak/v\d+(?:[-_/].+)?$")

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

# High-entropy heuristic: ≥40 chars of base64-ish alphabet.
HIGH_ENTROPY_PATTERN = re.compile(r"[A-Za-z0-9+/=_-]{40,}")

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


def _entropy_hits(diff_text: str) -> list[str]:
    hits: list[str] = []
    for line in diff_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for m in HIGH_ENTROPY_PATTERN.finditer(line):
            tok = m.group(0)
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


def _check_fix_without_test(changed_files: list[str]) -> list[str]:
    """v4.92 gate, applied across the full branch diff (not just one task)."""
    src = [
        p for p in changed_files
        if p.startswith("chimera/")
        and p.endswith(".py")
        and p not in ("chimera/__init__.py", "chimera/_version.py")
    ]
    if not src:
        return []
    has_tests = any(p.startswith("tests/") and p.endswith(".py") for p in changed_files)
    return [] if has_tests else src


def _worktree_branch(worktree: Path) -> str:
    proc = _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=worktree)
    return proc.stdout.strip()


def _porcelain_clean(worktree: Path) -> bool:
    proc = _run_git("status", "--porcelain", cwd=worktree)
    return proc.stdout.strip() == ""


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
) -> tuple[str, list[tuple[str, str]], list[str]]:
    """Run all pre-submit checks. Return (branch, commits, errors)."""
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

    if not _porcelain_clean(worktree):
        errors.append("worktree has uncommitted changes (git status not clean)")

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

    untested = _check_fix_without_test(files)
    if untested:
        errors.append(
            "fix_without_test (v4.92 gate): chimera/ source touched without "
            f"tests/ counterpart: {', '.join(untested)}"
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

    return branch, commits, errors


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
    audit_path: Path | None = None,
    gh_runner=None,
    push_runner=None,
) -> SubmitPrResult:
    """Run validations, push from `repo_root`, open PR via `gh`.

    `gh_runner` / `push_runner` are seams for tests. Each is a callable;
    if None we shell out for real.
    """
    audit_path = audit_path or (repo_root / "state" / "submit_pr_log.jsonl")
    result = SubmitPrResult(dry_run=dry_run, audit_path=audit_path)

    branch, commits, errors = validate(
        worktree, base=base, allow_entropy=allow_entropy,
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
    # (which has the no-push:// block).
    push_cmd = ["git", "-C", str(repo_root), "push", "origin", f"{branch}:{branch}"]
    if push_runner is None:
        push_proc = subprocess.run(push_cmd, capture_output=True, text=True)
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
        "--base", base,
        "--head", branch,
        "--title", title,
        "--body", body,
    ]
    if draft:
        gh_cmd.append("--draft")
    if gh_runner is None:
        gh_proc = subprocess.run(gh_cmd, capture_output=True, text=True, cwd=str(repo_root))
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
    })
    return result
