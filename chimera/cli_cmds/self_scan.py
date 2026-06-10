"""`chimera self-scan` command handler — moved verbatim from chimera.cli (pure move; chimera.cli remains the façade)."""

from __future__ import annotations


def _cmd_self_scan(args) -> int:
    """`chimera self-scan` — print ranked, behaviour-neutral maintenance
    candidates from the repo, each with a copy-pasteable real_task_soak.sh
    line. PRINTS ONLY; launches nothing (ADR 0161). Exit 0 whether or not
    candidates are found (it is a proposal surface, not a gate).

    --log persists candidates + prints ids; --accept/--reject record the
    operator's decision; --precision prints the origination precision report
    (chip 3 — the labelled data that eventually earns auto-origination)."""
    from datetime import datetime, timezone
    from pathlib import Path

    from ..core.self_scan import scan_repo
    from ..core.self_scan_log import (
        default_log_path,
        log_proposal,
        precision_report,
        record_decision,
    )

    log_path = default_log_path()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if args.precision:
        print(precision_report(log_path).summary())
        return 0

    if args.accept or args.reject:
        for pid in (args.accept or []):
            record_decision(pid, "accepted", path=log_path, ts=now)
            print(f"recorded: {pid} accepted")
        for pid in (args.reject or []):
            record_decision(pid, "rejected", path=log_path, ts=now)
            print(f"recorded: {pid} rejected")
        return 0

    candidates = scan_repo(Path.cwd())
    if not candidates:
        print("self-scan: no behaviour-neutral candidates found (clean tree, or "
              "ruff unavailable).")
        return 0
    shown = candidates[: max(args.limit, 0)]
    print(f"self-scan: {len(candidates)} candidate(s) "
          f"(showing {len(shown)}) — PROPOSAL ONLY, nothing launched:\n")
    for i, c in enumerate(shown, 1):
        flag = c.risk_flag or "behaviour-neutral"
        id_str = ""
        if args.log:
            pid = log_proposal(c.goal, c.files, c.source, c.score,
                               path=log_path, ts=now)
            id_str = f"  id={pid}"
        print(f"{i}. [{c.score:.2f}] {c.source} · {flag}{id_str}")
        print(f"   {c.goal}")
        print(f"   $ {c.soak_command(base=args.base)}\n")
    print("Pick one and run its command yourself — self-scan does not launch soaks.")
    if args.log:
        print(f"\nLogged {len(shown)} proposal(s) to {log_path}. "
              "Record outcomes with --accept/--reject <id>; see --precision.")
    return 0
