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


def _issue_stem(repo: str, number: object) -> str:
    """Stable spec filename stem keyed on (repo, issue-number) — NOT the title.

    Title-derived stems (MF-3) caused two bugs: a re-titled issue minted a new
    file (resurrecting a done/dispatched task), and two repos sharing an issue
    number + title collided so one task was silently dropped. (repo, number) is
    the unique, immutable identity; the title lives in the body only."""
    rp = _SLUG_RE.sub("-", str(repo).lower()).strip("-") or "repo"
    return f"issue-{rp}-{number}"


# Every issue-derived path/ref that reaches a git or pytest argv is validated as a
# bare, injection-proof token: charset [A-Za-z0-9._/-], no leading '/' or '-' (so
# it can never be read as an OPTION), no '..' traversal (see walk-foreign design).
_SAFE_PATH_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _safe_rel_path(p: object) -> bool:
    """True iff ``p`` is a bare relative path/ref token — safe to interpolate into
    a git/pytest argv. Rejects shell metachars/spaces/quotes (charset), absolute
    paths, ``..`` traversal, AND a leading ``-`` (which git/pytest would consume as
    an option, not a path). The single validation seam for files/test/base."""
    if not isinstance(p, str):
        return False
    p = p.strip()
    if not p or p.startswith("/") or p.startswith("-") or ".." in p.split("/"):
        return False
    return bool(_SAFE_PATH_RE.match(p))


def _norm_files(files_raw: object) -> tuple[str, ...]:
    """Mirror backlog.parse_spec's `files` normalisation (str|list → tuple)."""
    if isinstance(files_raw, str):
        return tuple(f for f in files_raw.split() if f)
    if isinstance(files_raw, list):
        return tuple(str(f).strip() for f in files_raw if str(f).strip())
    return ()


def _safe_test_path(test: object, files: tuple[str, ...]) -> str | None:
    """Return the test path iff it is an injection-proof, in-allowlist relative
    path, else None. The rendered foreign verify_cmd is
    ``template.replace("{test}", <this>)``, so the substituted value must be a bare
    path AND one of the issue's own (also-validated) `files`."""
    if not isinstance(test, str):
        return None
    t = test.strip()
    if not _safe_rel_path(t) or t not in files:
        return None
    return t


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


def issue_to_spec_markdown(
    issue: dict,
    repo: str,
    *,
    foreign: bool = False,
    verify_cmd_template: str | None = None,
    regression_cmd: str | None = None,
) -> str | None:
    """Render a crawl-ready issue into backlog-spec Markdown, or None when the
    issue has no usable spec block (or, in foreign mode, no gateable test path).

    ``repo`` is ``owner/name``; provenance is recorded as ``repo#number`` so the
    eventual PR can reference/close the issue.

    ``foreign=True`` (ADR 0186) makes a FOREIGN spec — the PR targets ``repo`` —
    gated by an OPERATOR-TRUSTED ``verify_cmd``: ``verify_cmd_template`` (with a
    ``{test}`` placeholder) rendered against the issue's STRICTLY-VALIDATED test
    path. The verify_cmd is NEVER taken from the issue body (security model).
    """
    block = spec_block(issue.get("body"))
    if not block or not isinstance(block.get("files"), (str, list)):
        return None
    number = issue.get("number")
    title = str(issue.get("title") or "").strip()
    files = _norm_files(block.get("files"))
    if not files:
        return None

    fm: dict = {
        "goal": str(block.get("goal") or title).strip(),
        "files": block.get("files"),
        "test": block.get("test"),
        "base": block.get("base") or "main",
        "done": False,
        "issue": f"{repo}#{number}",
    }

    if foreign:
        # The PR opens against `repo`; gate with the operator's template rendered
        # over the validated test path. Refuse (None) if we can't build a trusted,
        # in-scope gate — better no spec than an ungated foreign run.
        if not verify_cmd_template or "{test}" not in verify_cmd_template:
            return None
        # MF-1: the `files` allowlist is committed verbatim (git add -- $TASK_FILES)
        # and is what the PR carries — validate EVERY entry, not just {test}. A
        # crafted issue with files: ../../other/x.py would otherwise stage an
        # out-of-charter path that B.4g (keyed off the SAME list) does not revert.
        # `base` reaches `git clone --branch` — validate it too.
        if not all(_safe_rel_path(f) for f in files):
            return None
        if not _safe_rel_path(fm["base"]):
            return None
        test = _safe_test_path(block.get("test"), files)
        if test is None:
            return None
        fm["repo"] = repo
        fm["verify_cmd"] = verify_cmd_template.replace("{test}", test)
        # Optional broader regression suite (B.4i) — OPERATOR-TRUSTED (from
        # walk_repos.yaml, never the issue body), gates pass-to-pass regressions
        # for source-editing tasks. Plain string (no {test} templating).
        if regression_cmd and regression_cmd.strip():
            fm["regression_cmd"] = regression_cmd.strip()
        # `test` narrows the SELF gate only — meaningless for a foreign spec whose
        # gate is verify_cmd. Drop it so the spec is unambiguous.
        fm["test"] = None

    fm = {k: v for k, v in fm.items() if v is not None}
    front = yaml.safe_dump(fm, sort_keys=False, default_flow_style=False).strip()
    walk_tag = "ADR 0182/0186 foreign" if foreign else "WALK, ADR 0182"
    body_note = (
        f"Ingested from {repo}#{number} ({walk_tag}).\n\n"
        f"Issue: {title}\n"
    )
    return f"---\n{front}\n---\n{body_note}"


def ingest_issues(
    repo: str,
    *,
    mind_dir: Path,
    label: str | None = "crawl",
    foreign: bool = False,
    verify_cmd_template: str | None = None,
    regression_cmd: str | None = None,
    issues: list[dict] | None = None,
) -> list[IngestResult]:
    """Materialise crawl-ready issues from ``repo`` into ``mind/backlog/``.

    ``issues`` may be injected (tests / dry runs); otherwise they are fetched
    with ``gh``. Each crawl-ready issue is written as ``issue-<n>-<slug>.md``.
    ``foreign``/``verify_cmd_template`` forward to :func:`issue_to_spec_markdown`.

    Idempotent-ADD: an existing spec file is NEVER overwritten — re-running WALK
    can't clobber operator edits, ``done:`` markers, or dispatch state (a landed
    task whose issue is still open won't be resurrected). Returns one
    :class:`IngestResult` per issue.
    """
    if issues is None:
        # Fail-closed: foreign ingestion without a label would scan ALL open issues
        # — the label IS the operator's per-issue opt-in (only write-access
        # collaborators can apply it). Refuse rather than ingest everything.
        if foreign and not (label and label.strip()):
            return [IngestResult(0, "", None, "foreign ingest requires a non-empty label")]
        issues = _fetch_issues(repo, label=label)
    out_dir = backlog_dir(mind_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[IngestResult] = []
    for issue in issues:
        number = issue.get("number")
        title = str(issue.get("title") or "").strip()
        md = issue_to_spec_markdown(
            issue, repo, foreign=foreign, verify_cmd_template=verify_cmd_template,
            regression_cmd=regression_cmd,
        )
        if md is None:
            results.append(IngestResult(number, title, None, "no usable spec block"))
            continue
        path = out_dir / f"{_issue_stem(repo, number)}.md"
        if path.exists():
            results.append(IngestResult(number, title, None, "exists (kept)"))
            continue
        path.write_text(md, encoding="utf-8")
        results.append(IngestResult(number, title, path, "ingested"))
    return results


def load_walk_repos(mind_dir: Path) -> list[dict]:
    """Operator-curated WALK sources from ``mind/walk_repos.yaml`` (ADR 0186).

    Returns a list of ``{repo, label, verify_cmd_template, regression_cmd}`` — the
    trusted config that drives the renewable foreign source (``regression_cmd`` is
    optional, the B.4i broader suite, ``None`` when absent). Entries missing a repo
    or a ``{test}``-bearing template are dropped. Absent/malformed file → ``[]``
    (WALK is then a no-op). Never raises."""
    path = mind_dir / "walk_repos.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, dict) or not isinstance(data.get("repos"), list):
        return []
    out: list[dict] = []
    for entry in data["repos"]:
        if not isinstance(entry, dict):
            continue
        repo = str(entry.get("repo") or "").strip()
        tmpl = str(entry.get("verify_cmd_template") or "").strip()
        if not repo or "{test}" not in tmpl:
            continue
        label = entry.get("label")
        reg = entry.get("regression_cmd")  # optional broader suite for B.4i
        out.append({
            "repo": repo,
            "label": str(label).strip() if label else "crawl",
            "verify_cmd_template": tmpl,
            "regression_cmd": str(reg).strip() if reg else None,
        })
    return out


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
