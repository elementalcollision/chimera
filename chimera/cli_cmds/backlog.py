"""`chimera backlog ...` — CRAWL task-spec inspection + selection (ADR 0182).

The picker surface for the daily-production loop: list/validate the
operator-curated specs in ``mind/backlog/``, and select the next actionable
one — optionally enforcing gate-visibility (the spec's gate must be RED on
its base, else it is rejected as proving nothing).
"""

from __future__ import annotations

import json
from pathlib import Path


def _cmd_backlog(args, parser) -> int:
    from ..core import LoopConfig
    from ..core.backlog import (
        list_specs,
        select_next,
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
        claimed = frozenset(
            s.strip() for s in (args.claimed or "").split(",") if s.strip()
        )
        spec = select_next(mind_dir, claimed_slugs=claimed)
        if spec is None:
            print("backlog: no actionable spec")
            return 1

        if getattr(args, "check_gate", False):
            code = _check_gate_visibility(spec)
            if code != 0:
                return code

        if getattr(args, "json", False):
            print(json.dumps({
                "slug": spec.slug,
                "path": str(spec.path),
                "goal": spec.goal,
                "files": list(spec.files),
                "test": spec.test,
                "base": spec.base,
                "env": spec.task_env(),
            }, indent=2))
        else:
            print(f"next: {spec.slug}")
            print(f"  goal:  {spec.goal}")
            print(f"  files: {' '.join(spec.files)}")
            print(f"  test:  {spec.test or '(full suite)'}")
            print(f"  base:  {spec.base}")
            if spec.issue:
                print(f"  issue: {spec.issue}")
        return 0

    if sub == "from-issues":
        from ..core.issue_backlog import ingest_issues

        label = args.label or None
        if getattr(args, "dry_run", False):
            from ..core.issue_backlog import _fetch_issues, issue_to_spec_markdown

            issues = _fetch_issues(args.repo, label=label)
            ingestable = sum(
                1 for i in issues if issue_to_spec_markdown(i, args.repo) is not None
            )
            print(
                f"backlog from-issues (dry-run): {args.repo} "
                f"label={label or '(any)'} — {len(issues)} open issue(s), "
                f"{ingestable} crawl-ready"
            )
            return 0

        results = ingest_issues(args.repo, mind_dir=mind_dir, label=label)
        ingested = [r for r in results if r.written is not None]
        for r in results:
            mark = "+" if r.written is not None else "-"
            tail = r.written.name if r.written is not None else r.reason
            print(f"  [{mark}] #{r.number} {r.title[:54]} — {tail}")
        print(
            f"backlog from-issues: {len(ingested)}/{len(results)} ingested "
            f"from {args.repo}"
        )
        return 0

    parser.error("usage: chimera backlog {list|validate|next|from-issues}")
    return 2


def _check_gate_visibility(spec) -> int:
    """Verify the spec's gate is RED on its base (ADR 0182 gate-visibility).

    Returns 0 if gate-visible (red on base — proceed), 3 if gate-invisible
    (already green — the change would prove nothing), 4 if the base ref
    could not be evaluated.
    """
    from ..core.repo_verify import default_checks, verify_at_ref

    checks = default_checks(
        test_target=spec.test, ruff_paths=list(spec.files),
    )
    base = verify_at_ref(Path.cwd(), spec.base, checks=checks)
    if base is None:
        print(
            f"GATE-CHECK: could not evaluate base ref {spec.base!r} for "
            f"{spec.slug} — skipping (exit 4)"
        )
        return 4
    if base.ok:
        print(
            f"GATE-INVISIBLE: {spec.slug}'s gate is already GREEN on "
            f"{spec.base} — the change would prove nothing. Make the gate "
            f"red on base first (a failing test, or `-W error` so a warning "
            f"counts as failure). Skipping (exit 3)."
        )
        return 3
    return 0
