"""WALK — GitHub issues as the CRAWL work source (ADR 0182 phase 2).

Turns a *crawl-ready* GitHub issue into a backlog spec the existing picker
/ gate / soak consume unchanged. The design reuses everything: this module
only WRITES normal `mind/backlog/*.md` spec files (with issue provenance);
`backlog.parse_spec` / `select_next` / the gate-visibility check do the rest.

A crawl-ready issue carries a fenced spec block in its body — the same
fields as an MD spec — so a human curates the scope (the gate must still be
RED on base, so a vague feature request is correctly rejected downstream):

    ```yaml
    goal: One-line task
    files: chimera/foo.py tests/test_foo.py
    test: tests/test_foo.py
    base: main
    ```

Issues without a spec block are skipped (not every issue is a gate-visible
task). Multi-repo PR *targeting* is a later increment — for now the source
repo is recorded as provenance and the soak runs against the local repo.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from .backlog import backlog_dir

# A fenced ```yaml (or ```spec) block anywhere in the issue body.
_SPEC_BLOCK_RE = re.compile(
    r"```(?:yaml|spec)\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE
)
_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class IngestResult:
    number: int
    title: str
    written: Path | None          # None when skipped
    reason: str                   # "ingested" | a skip reason


def _slug(title: str, limit: int = 48) -> str:
    s = _SLUG_RE.sub("-", title.lower()).strip("-")
    return (s[:limit].rstrip("-")) or "issue"


def spec_block(body: str | None) -> dict | None:
    """Return the parsed fenced spec block from an issue body, or None.

    Never raises — a malformed YAML block returns None (the caller skips it).
    """
    if not body:
        return None
    m = _SPEC_BLOCK_RE.search(body)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def issue_to_spec_markdown(issue: dict, repo: str) -> str | None:
    """Render a crawl-ready issue into backlog-spec Markdown, or None when the
    issue has no usable spec block.

    ``repo`` is ``owner/name``; provenance is recorded as ``repo#number`` so
    the eventual PR can reference/close the issue.
    """
    block = spec_block(issue.get("body"))
    if not block or not isinstance(block.get("files"), (str, list)):
        return None
    number = issue.get("number")
    title = str(issue.get("title") or "").strip()

    fm = {
        "goal": str(block.get("goal") or title).strip(),
        "files": block.get("files"),
        "test": block.get("test"),
        "base": block.get("base") or "main",
        "done": False,
        "issue": f"{repo}#{number}",
    }
    fm = {k: v for k, v in fm.items() if v is not None}
    front = yaml.safe_dump(fm, sort_keys=False, default_flow_style=False).strip()
    body_note = (
        f"Ingested from {repo}#{number} (WALK, ADR 0182).\n\n"
        f"Issue: {title}\n"
    )
    return f"---\n{front}\n---\n{body_note}"


def ingest_issues(
    repo: str,
    *,
    mind_dir: Path,
    label: str | None = "crawl",
    issues: list[dict] | None = None,
) -> list[IngestResult]:
    """Materialise crawl-ready issues from ``repo`` into ``mind/backlog/``.

    ``issues`` may be injected (tests / dry runs); otherwise they are fetched
    with ``gh``. Each issue with a valid spec block is written as
    ``issue-<n>-<slug>.md``. Returns one :class:`IngestResult` per issue.
    """
    if issues is None:
        issues = _fetch_issues(repo, label=label)
    out_dir = backlog_dir(mind_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[IngestResult] = []
    for issue in issues:
        number = issue.get("number")
        title = str(issue.get("title") or "").strip()
        md = issue_to_spec_markdown(issue, repo)
        if md is None:
            results.append(IngestResult(number, title, None, "no usable spec block"))
            continue
        path = out_dir / f"issue-{number}-{_slug(title)}.md"
        path.write_text(md, encoding="utf-8")
        results.append(IngestResult(number, title, path, "ingested"))
    return results


def _fetch_issues(repo: str, *, label: str | None) -> list[dict]:
    """Fetch open issues from ``repo`` via gh. Never raises — gh failure
    (auth, network, no repo) yields an empty list."""
    argv = [
        "gh", "issue", "list", "--repo", repo, "--state", "open",
        "--limit", "100", "--json", "number,title,body",
    ]
    if label:
        argv += ["--label", label]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []
