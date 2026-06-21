"""`chimera backlog ...` — CRAWL task-spec inspection + selection (ADR 0182).

The picker surface for the daily-production loop: list/validate the
operator-curated specs in ``mind/backlog/``, and select the next actionable
one — optionally enforcing gate-visibility (the spec's gate must be RED on
its base, else it is rejected as proving nothing).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _cmd_backlog(args, parser) -> int:
    from ..core import LoopConfig
    from ..core.backlog import (
        list_specs,
        validation_report,
    )

    mind_dir = LoopConfig.from_env().mind_dir
    sub = getattr(args, "backlog_command", None)

    if sub == "list":
        specs = list_specs(mind_dir)
        if not specs:
            print(f"backlog: no specs in {mind_dir / 'backlog'}")
            return 0
        for s in specs:
            status = "done" if s.done else ("INVALID" if not s.valid else "ready")
            print(f"  [{status:7s}] {s.slug}  —  {s.goal or '(no goal)'}")
            if not s.valid:
                for e in s.errors:
                    print(f"             ! {e}")
        return 0

    if sub == "validate":
        report = validation_report(mind_dir)
        if not report:
            print("backlog: all specs valid")
            return 0
        for slug, errors in report:
            print(f"INVALID {slug}:")
            for e in errors:
                print(f"  - {e}")
        return 1

    if sub == "next":
        return _cmd_backlog_next(args, mind_dir)

    if sub == "from-issues":
        from ..core.issue_backlog import ingest_issues

        def _report(results, repo: str) -> int:
            ingested = [r for r in results if r.written is not None]
            for r in results:
                mark = "+" if r.written is not None else "-"
                tail = r.written.name if r.written is not None else r.reason
                print(f"  [{mark}] {repo}#{r.number} {r.title[:48]} — {tail}")
            return len(ingested)

        # Renewable source: ingest every configured walk_repos repo as foreign.
        if getattr(args, "walk", False):
            from ..core.issue_backlog import load_walk_repos

            sources = load_walk_repos(mind_dir)
            if not sources:
                print("backlog from-issues --walk: no mind/walk_repos.yaml sources")
                return 0
            dry = getattr(args, "dry_run", False)  # MF-4: --walk must honor --dry-run
            total = 0
            for src in sources:
                if dry:
                    from ..core.issue_backlog import (
                        _fetch_issues,
                        issue_to_spec_markdown,
                    )

                    issues = _fetch_issues(src["repo"], label=src["label"] or None)
                    n = sum(
                        1 for i in issues
                        if issue_to_spec_markdown(
                            i, src["repo"], foreign=True,
                            verify_cmd_template=src["verify_cmd_template"],
                        ) is not None
                    )
                    print(f"  [dry] {src['repo']}: {len(issues)} open, {n} crawl-ready")
                    total += n
                else:
                    results = ingest_issues(
                        src["repo"], mind_dir=mind_dir, label=src["label"] or None,
                        foreign=True, verify_cmd_template=src["verify_cmd_template"],
                    )
                    total += _report(results, src["repo"])
            verb = "would ingest" if dry else "ingested"
            tag = " (dry-run)" if dry else ""
            print(
                f"backlog from-issues --walk{tag}: {total} spec(s) {verb} from "
                f"{len(sources)} repo(s)"
            )
            return 0

        label = args.label or None
        foreign = getattr(args, "foreign", False)
        tmpl = getattr(args, "verify_cmd_template", None)
        if foreign and (not tmpl or "{test}" not in tmpl):
            parser.error(
                "--foreign requires --verify-cmd-template with a {test} placeholder"
            )

        if getattr(args, "dry_run", False):
            from ..core.issue_backlog import _fetch_issues, issue_to_spec_markdown

            issues = _fetch_issues(args.repo, label=label)
            ingestable = sum(
                1 for i in issues
                if issue_to_spec_markdown(
                    i, args.repo, foreign=foreign, verify_cmd_template=tmpl
                ) is not None
            )
            print(
                f"backlog from-issues (dry-run): {args.repo} "
                f"label={label or '(any)'} foreign={foreign} — "
                f"{len(issues)} open issue(s), {ingestable} crawl-ready"
            )
            return 0

        results = ingest_issues(
            args.repo, mind_dir=mind_dir, label=label,
            foreign=foreign, verify_cmd_template=tmpl,
        )
        n = _report(results, args.repo)
        print(f"backlog from-issues: {n}/{len(results)} ingested from {args.repo}")
        return 0

    parser.error("usage: chimera backlog {list|validate|next|from-issues}")
    return 2


def _cmd_backlog_next(args, mind_dir) -> int:
    """`chimera backlog next` — select (and optionally gate-check) the next
    actionable spec.

    Skip-and-continue (2026-06-12 WALK finding): a gate-invisible or
    base-error spec must NOT block the queue behind it — at issue volume one
    mis-specified entry would otherwise poison every daily run. Walk the
    queue, skipping such specs (reported per-spec), and dispatch the first
    that passes. Exit 0 = a spec selected; 3 = candidates existed but all
    were skipped; 1 = the backlog is empty.
    """
    from ..core.backlog import select_next

    claimed = {s.strip() for s in (args.claimed or "").split(",") if s.strip()}
    skipped: list[tuple[str, int]] = []

    while True:
        spec = select_next(mind_dir, claimed_slugs=frozenset(claimed))
        if spec is None:
            break
        if getattr(args, "check_gate", False):
            code = _check_gate_visibility(spec)
            if code != 0:
                skipped.append((spec.slug, code))
                claimed.add(spec.slug)  # skip it this run; try the next
                continue

        if getattr(args, "json", False):
            print(json.dumps({
                "slug": spec.slug,
                "path": str(spec.path),
                "goal": spec.goal,
                "files": list(spec.files),
                "test": spec.test,
                "base": spec.base,
                "issue": spec.issue,
                "skipped": [{"slug": s, "exit": c} for s, c in skipped],
                "env": spec.task_env(),
            }, indent=2))
        else:
            _print_skipped(skipped)
            print(f"next: {spec.slug}")
            print(f"  goal:  {spec.goal}")
            print(f"  files: {' '.join(spec.files)}")
            print(f"  test:  {spec.test or '(full suite)'}")
            print(f"  base:  {spec.base}")
            if spec.issue:
                print(f"  issue: {spec.issue}")
        return 0

    # Nothing selected. Distinguish "all candidates skipped" (3) from "empty
    # backlog" (1) so the runner can log the difference.
    if skipped:
        _print_skipped(skipped)
        print("backlog: no gate-visible spec (all candidates skipped)")
        return 3
    print("backlog: no actionable spec")
    return 1


def _print_skipped(skipped: list[tuple[str, int]]) -> None:
    for slug, code in skipped:
        why = "gate-invisible" if code == 3 else "base error"
        print(f"skipped: {slug} ({why}, exit {code})")


def _check_gate_visibility(spec) -> int:
    """Verify the spec's gate is RED on its base (ADR 0182 gate-visibility).

    Returns 0 if gate-visible (red on base — proceed), 3 if gate-invisible
    (already green — the change would prove nothing), 4 if the base ref
    could not be evaluated.

    Diagnostics go to STDERR: `chimera backlog next --json` must emit ONLY the
    spec JSON on stdout (the crawl daily driver captures stdout and json.loads it
    — a stray diagnostic line breaks the parse).
    """
    # Foreign-repo spec (ADR 0186): its gate is the FOREIGN repo's own verify_cmd,
    # which cannot be evaluated against THIS (self) checkout — running the self-repo
    # checks here would gate the wrong tree. Skip; the soak's B.3b baseline runs the
    # foreign verify_cmd at the foreign base for the real red→green gate-visibility.
    if getattr(spec, "repo", None):
        print(
            f"GATE-CHECK: {spec.slug} targets foreign repo {spec.repo} — "
            "gate-visibility is enforced in the soak against the foreign base. "
            "Proceeding.",
            file=sys.stderr,
        )
        return 0

    from ..core.repo_verify import default_checks, verify_at_ref

    checks = default_checks(
        test_target=spec.test, ruff_paths=list(spec.files),
    )
    base = verify_at_ref(Path.cwd(), spec.base, checks=checks)
    if base is None:
        print(
            f"GATE-CHECK: could not evaluate base ref {spec.base!r} for "
            f"{spec.slug} — skipping (exit 4)",
            file=sys.stderr,
        )
        return 4
    if base.ok:
        print(
            f"GATE-INVISIBLE: {spec.slug}'s gate is already GREEN on "
            f"{spec.base} — the change would prove nothing. Make the gate "
            f"red on base first (a failing test, or `-W error` so a warning "
            f"counts as failure). Skipping (exit 3).",
            file=sys.stderr,
        )
        return 3
    return 0
