"""Chimera CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from . import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chimera",
        description="Chimera — a multi-LLM tools-capable agent.",
    )
    parser.add_argument("--version", action="version", version=f"chimera {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("status", help="Show current cycle and trust state (stub).")
    sub.add_parser(
        "doctor",
        help="Validate config / env / state — boot-time preflight (v3.6+).",
    )
    sub.add_parser(
        "fragmentation",
        help="Show the v4.5 fragmentation log (compound-task failures).",
    )
    escalations = sub.add_parser(
        "escalations",
        help="Inspect the v4.46 task-escalation memory (auto-promotes tier).",
    )
    esc_sub = escalations.add_subparsers(
        dest="escalations_command", metavar="<esc-cmd>",
    )
    esc_list = esc_sub.add_parser("list", help="List recent escalation rows.")
    esc_list.add_argument("--limit", type=int, default=20)
    esc_list.add_argument(
        "--grep", default=None,
        help="Substring filter on the signature.",
    )
    esc_sub.add_parser(
        "summary",
        help="Aggregate counts per signature × tier.",
    )
    esc_clear = esc_sub.add_parser(
        "clear",
        help="Delete escalation rows (use with care — the agent uses these to learn).",
    )
    esc_clear.add_argument(
        "--grep", default=None,
        help="Only delete rows whose signature matches this substring.",
    )
    esc_clear.add_argument(
        "--all", action="store_true",
        help="Required with no --grep — confirms a full wipe.",
    )
    tiers = sub.add_parser(
        "tiers",
        help="Show every model rung in every tier ladder (v4.8+).",
    )
    tiers.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON ladder snapshot AND mirror to state/tiers.json.",
    )

    run = sub.add_parser("run", help="Run one cycle of the agent loop (stub).")
    run.add_argument("prompt", nargs="?", help="Optional ad-hoc prompt to enqueue.")

    cost = sub.add_parser(
        "cost",
        help="Show windowed spend (cycle, 15m, 60m, total) with band classification.",
    )
    cost.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of formatted text.",
    )
    cost.add_argument(
        "--cycle", type=int, default=None,
        help="Cycle number to report on (default: most recent).",
    )

    search = sub.add_parser(
        "search",
        help="Full-text search over mind/wiki/ (FTS5).",
    )
    search.add_argument("query", help="FTS5 query (phrase, prefix, AND/OR/NOT).")
    search.add_argument(
        "--limit", type=int, default=8,
        help="Max results to show (default 8, max 20).",
    )
    search.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of formatted text.",
    )
    search.add_argument(
        "--rebuild", action="store_true",
        help="Force a fresh index update before searching.",
    )

    estimate = sub.add_parser(
        "estimate",
        help="Pre-flight: predict total USD to clear the open INBOX once.",
    )
    estimate.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of formatted text.",
    )
    estimate.add_argument(
        "--tier", default="haiku",
        choices=("haiku", "sonnet", "opus"),
        help="Default starting tier (research-floor + memory still apply).",
    )

    ping = sub.add_parser(
        "ping",
        help="Stream a one-token reply from both providers (verifies API keys).",
    )
    ping.add_argument(
        "--provider",
        choices=("anthropic", "openrouter", "both"),
        default="both",
    )

    ontology = sub.add_parser(
        "ontology",
        help="Inspect the KFM ontology in state/chimera.db.",
    )
    ontology.add_argument(
        "--kind",
        help="Filter by entity kind (plan, tool, skill, subagent).",
    )
    ontology.add_argument(
        "--audit",
        action="store_true",
        help="Print a memory/ontology audit (stale + dead entities, re-anchor count).",
    )
    ontology.add_argument(
        "--cycle",
        type=int,
        default=None,
        help="Audit reference cycle (defaults to max cycle from agent_activity_log).",
    )
    ontology.add_argument(
        "--stale-after-cycles",
        type=int,
        default=20,
        help="Stale threshold for the audit (default 20).",
    )
    ontology.add_argument(
        "--json",
        action="store_true",
        help="Emit audit output as JSON (only with --audit).",
    )
    ontology.add_argument(
        "--archive-stale",
        action="store_true",
        help="Promote DEPRECATED entities past --archive-after-cycles to ARCHIVED.",
    )
    ontology.add_argument(
        "--archive-after-cycles",
        type=int,
        default=30,
        help="Cycle threshold for --archive-stale (default 30).",
    )
    ontology.add_argument(
        "--dry-run",
        action="store_true",
        help="With --archive-stale: report what would be archived without writing.",
    )
    ontology.add_argument(
        "--propose-kills",
        action="store_true",
        help=(
            "Queue kill_entity mutations for ARCHIVED entities past "
            "--archive-after-cycles. Operator must approve before --apply-kills."
        ),
    )
    ontology.add_argument(
        "--apply-kills",
        action="store_true",
        help=(
            "Apply any approved kill_entity mutations: transition ARCHIVED → KILLED "
            "via the K-operator. Pairs with --propose-kills + `chimera mutations approve`."
        ),
    )

    mutations = sub.add_parser(
        "mutations",
        help="Inspect and approve/reject pending mutations.",
    )
    mut_sub = mutations.add_subparsers(dest="mut_command", metavar="<mut-cmd>")
    mut_sub.add_parser("list", help="List mutations (default: pending).")
    mut_show = mut_sub.add_parser("show", help="Show one mutation.")
    mut_show.add_argument("id", type=int)
    mut_approve = mut_sub.add_parser("approve", help="Approve a pending mutation.")
    mut_approve.add_argument("id", type=int)
    mut_approve.add_argument("--reason", default=None)
    mut_reject = mut_sub.add_parser("reject", help="Reject a pending mutation.")
    mut_reject.add_argument("id", type=int)
    mut_reject.add_argument("--reason", default=None)
    mut_health = mut_sub.add_parser(
        "health",
        help="Show queue-health metrics (counts, oldest pending, recurrence).",
    )
    mut_health.add_argument(
        "--json", action="store_true", help="Emit the snapshot as JSON."
    )

    a2a = sub.add_parser(
        "a2a",
        help="Inspect A2A / Xenocomm peer integration (v1.5+).",
    )
    a2a_sub = a2a.add_subparsers(dest="a2a_command", metavar="<a2a-cmd>")
    a2a_sub.add_parser("identity", help="Show this agent's identity payload.")
    a2a_sub.add_parser("peers", help="List Xenocomm tools discovered via MCP.")

    peers_p = sub.add_parser(
        "peers",
        help="Inspect / manage the local peer registry (v2.2+).",
    )
    peers_sub = peers_p.add_subparsers(dest="peers_command", metavar="<peers-cmd>")
    peers_sub.add_parser("list", help="List entries in the peer registry.")
    p_forget = peers_sub.add_parser("forget", help="Remove a peer entry by agent_id.")
    p_forget.add_argument("agent_id")
    peers_sub.add_parser("sweep", help="Remove stale (pid-gone) local peer entries.")
    p_sync = peers_sub.add_parser(
        "sync",
        help="Fetch /healthz from CHIMERA_REMOTE_PEERS and upsert entries (v3.7+).",
    )
    p_sync.add_argument(
        "--urls",
        default=None,
        help="Comma-separated base URLs (overrides CHIMERA_REMOTE_PEERS).",
    )
    p_sweep_remote = peers_sub.add_parser(
        "sweep-remote",
        help="Remove HTTP peer entries older than --max-age-hours (default 24).",
    )
    p_sweep_remote.add_argument("--max-age-hours", type=float, default=24.0)
    p_kfm = peers_sub.add_parser(
        "kfm",
        help="Fetch the swarm-KFM state of one peer (or all if no name given).",
    )
    p_kfm.add_argument("name", nargs="?", help="Peer server-name as known to MCP loader.")

    trust = sub.add_parser(
        "trust",
        help="Inspect and adjust trust tier (T0..T5).",
    )
    trust_sub = trust.add_subparsers(dest="trust_command", metavar="<trust-cmd>")
    trust_sub.add_parser("show", help="Show current tier + recent history.")
    trust_promote = trust_sub.add_parser("promote", help="Promote one tier.")
    trust_promote.add_argument("--reason", default="manual promotion")
    trust_demote = trust_sub.add_parser("demote", help="Demote one tier.")
    trust_demote.add_argument("--reason", default="manual demotion")
    trust_lock = trust_sub.add_parser("lockdown", help="Immediate T0 lockdown.")
    trust_lock.add_argument("--reason", default="manual lockdown")

    skills = sub.add_parser(
        "skills",
        help="Manage dynamic skills (assemble from a mutation, list, etc).",
    )
    skills_sub = skills.add_subparsers(dest="skills_command", metavar="<skills-cmd>")
    skills_sub.add_parser("list", help="List currently registered dynamic skills.")
    skills_asm = skills_sub.add_parser(
        "assemble",
        help="Assemble + validate + activate a skill from a mutation id.",
    )
    skills_asm.add_argument("mutation_id", type=int)

    engines = sub.add_parser(
        "engines",
        help="Run daily engines (Discovery / Curiosity / Reflection).",
    )
    engines_sub = engines.add_subparsers(dest="engines_command", metavar="<engines-cmd>")
    engines_run = engines_sub.add_parser("run", help="Force-fire one engine.")
    engines_run.add_argument(
        "name",
        choices=("discovery", "curiosity", "reflection"),
    )

    scenario = sub.add_parser(
        "scenario",
        help="Run a scripted scenario (checkpoint artifact).",
    )
    scenario.add_argument(
        "name",
        choices=(
            "drift", "research", "two_chimera", "multi_host",
            "federation_drill", "federation_trust_drill",
            "federation_http_drill",
        ),
        help="Which scenario to run.",
    )

    serve = sub.add_parser(
        "serve",
        help="Start Chimera's MCP server (stdio by default; --http for HTTP).",
    )
    serve.add_argument(
        "--name",
        default="chimera",
        help="MCP server name advertised to peers (default: chimera).",
    )
    serve.add_argument(
        "--http",
        action="store_true",
        help="Use HTTP/SSE transport instead of stdio (v2.6+).",
    )
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP bind host (default 127.0.0.1; use 0.0.0.0 to expose).",
    )
    serve.add_argument(
        "--port",
        type=int,
        default=8765,
        help="HTTP port (default 8765).",
    )

    emergence = sub.add_parser(
        "emergence",
        help="Inspect / sync the protocol-evolution journal (v2.9+).",
    )
    emergence_sub = emergence.add_subparsers(dest="emergence_command", metavar="<emg-cmd>")
    emergence_sub.add_parser("list", help="List per-peer earliest and latest observations.")
    e_sync = emergence_sub.add_parser(
        "sync",
        help="Pull /emergence-feed from CHIMERA_REMOTE_PEERS into remote/.",
    )
    e_sync.add_argument("--urls", default=None)

    graph = sub.add_parser(
        "graph",
        help="LadybugDB graph store: init / query / rebuild (v2.10+).",
    )
    graph_sub = graph.add_subparsers(dest="graph_command", metavar="<graph-cmd>")
    graph_sub.add_parser("init", help="Create schema in state/chimera.graph/.")
    g_rebuild = graph_sub.add_parser(
        "rebuild", help="Re-project SQLite + registry into the graph."
    )
    g_rebuild.add_argument(
        "--incremental",
        action="store_true",
        help="Append only new entities + transitions (v4.31) — much cheaper than clear+rebuild.",
    )
    g_query = graph_sub.add_parser("query", help="Run a Cypher query and print rows.")
    g_query.add_argument("cypher", help="Cypher statement.")
    g_hist = graph_sub.add_parser(
        "entity-history", help="KFM transition chain for one entity (by id or name)."
    )
    g_hist.add_argument("ident", help="Entity id (full or 8-char prefix) or name.")
    graph_sub.add_parser(
        "skill-deps", help="List dynamic skills and their DEPENDS_ON / USES_TOOL edges."
    )
    graph_sub.add_parser(
        "orphans", help="Entities with no transitions; skills with no edges."
    )
    g_prov = graph_sub.add_parser(
        "provenance", help="Mutation provenance: PROPOSED entity + ACTIVATED skill chain."
    )
    g_prov.add_argument("mutation_id", type=int)
    g_export = graph_sub.add_parser(
        "export",
        help="Write a JSON snapshot of graph queries for the dashboard.",
    )
    g_export.add_argument(
        "--out",
        default=None,
        help="Output path (default: state/chimera.graph.snapshot.json).",
    )
    g_stress = graph_sub.add_parser(
        "stress",
        help="Synthetic stress test: populate N entities, rebuild, query, restart.",
    )
    g_stress.add_argument("--entities", type=int, default=500)
    g_stress.add_argument("--transitions-each", type=int, default=2)
    g_stress.add_argument("--repeat", type=int, default=10)
    g_stress.add_argument("--json", action="store_true")

    return parser


async def _ping_provider(name: str) -> int:
    from .providers import (
        HAIKU,
        HAIKU_LADDER,
        AnthropicProvider,
        ChatMessage,
        OpenRouterProvider,
        ProviderKind,
    )

    try:
        if name == "anthropic":
            provider = AnthropicProvider()
            model = HAIKU.model_id
        else:
            provider = OpenRouterProvider()
            # First OpenRouter rung in the HAIKU ladder — native (non-Anthropic) model.
            first_or_rung = next(
                r for r in HAIKU_LADDER if r.config.provider is ProviderKind.OPENROUTER
            )
            model = first_or_rung.config.openrouter_model_id
    except RuntimeError as e:
        print(f"  [{name}] SKIP: {e}")
        return 0

    text_parts: list[str] = []
    finish: str | None = None
    async for chunk in provider.stream(
        [ChatMessage(role="user", content="Say 'pong' and nothing else.")],
        model_id=model,
        max_tokens=128,
    ):
        text_parts.append(chunk.text)
        if chunk.finish_reason:
            finish = chunk.finish_reason
    reply = "".join(text_parts).strip()
    print(f"  [{name}] reply={reply!r} finish={finish!r}")
    return 0 if "pong" in reply.lower() else 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "emergence":
        from .a2a import journal_dir
        sub_cmd = args.emergence_command or "list"
        if sub_cmd == "list":
            d = journal_dir()
            files = sorted(d.glob("*.jsonl"))
            remote = sorted((d / "remote").glob("*/*.jsonl")) if (d / "remote").exists() else []
            print(f"chimera emergence: {len(files)} local, {len(remote)} remote")
            for p in files:
                lines = sum(1 for _ in p.read_text().splitlines() if _.strip())
                print(f"  local  {p.stem}: {lines} observation(s)")
            for p in remote:
                rel = p.relative_to(d / "remote")
                lines = sum(1 for _ in p.read_text().splitlines() if _.strip())
                print(f"  remote {rel}: {lines} observation(s)")
            return 0
        if sub_cmd == "sync":
            from .a2a.emergence_sync import sync_remote_emergence
            urls = None
            if args.urls:
                urls = [u.strip() for u in args.urls.split(",") if u.strip()]
            result = sync_remote_emergence(urls)
            print(
                f"chimera emergence sync: fetched={result.fetched} "
                f"records_added={result.records_added} "
                f"failed={len(result.failures)}"
            )
            for url, err in result.failures:
                print(f"  ! {url}: {err}")
            return 0 if not result.failures else 1
        parser.error(f"unknown emergence subcommand: {sub_cmd}")
        return 2
    if args.command == "cost":
        # v4.58 (ADR 0077): operator-facing windowed spend report.
        # Mirrors the dashboard cost-rate widget for headless / SSH use.
        from .core import LoopConfig
        from .core.budget import (
            cycle_cost_cap_usd,
            cycle_spend_usd,
            rolling_hour_cap_usd,
            rolling_spend_usd,
        )
        from .memory import open_and_init

        cfg = LoopConfig.from_env()
        conn = open_and_init(cfg.state_dir / "chimera.db")

        # Resolve cycle: explicit arg, else max(cycle) from api_calls.
        if args.cycle is not None:
            cycle_num = args.cycle
        else:
            row = conn.execute(
                "SELECT MAX(cycle) AS c FROM api_calls"
            ).fetchone()
            cycle_num = int(row["c"] or 0)

        cycle_usd = cycle_spend_usd(conn, cycle_num) if cycle_num > 0 else 0.0
        spend_15m = rolling_spend_usd(conn, minutes=15)
        spend_60m = rolling_spend_usd(conn, minutes=60)
        # Total: token-driven, all-time, error-free.
        try:
            rows = conn.execute(
                "SELECT model_id, "
                "  COALESCE(SUM(input_tokens), 0), "
                "  COALESCE(SUM(output_tokens), 0) "
                "FROM api_calls WHERE error IS NULL GROUP BY model_id"
            ).fetchall()
        except Exception:
            rows = []
        from .core.budget import _price_table as _bp_pt
        table = _bp_pt()
        total_usd = 0.0
        by_model: list[tuple[str, float]] = []
        for model_id, in_tok, out_tok in rows:
            in_price, out_price = table.get(model_id, (0.0, 0.0))
            c = (in_tok / 1_000_000.0) * in_price + (out_tok / 1_000_000.0) * out_price
            total_usd += c
            by_model.append((model_id, c))
        by_model.sort(key=lambda x: -x[1])

        # Band classification mirrors lib/cost.ts classifyCostRate().
        usd_per_min_15 = spend_15m / 15.0 if spend_15m > 0 else 0.0
        def _band(rate: float) -> str:
            if rate <= 0: return "off"
            if rate < 0.10: return "green"
            if rate <= 0.50: return "amber"
            return "red"
        band = _band(usd_per_min_15)

        cycle_cap = cycle_cost_cap_usd()
        hour_cap = rolling_hour_cap_usd()

        if args.json:
            import json as _json
            print(_json.dumps({
                "cycle": cycle_num,
                "cycle_spend_usd": round(cycle_usd, 4),
                "cycle_cap_usd": cycle_cap,
                "spend_15m_usd": round(spend_15m, 4),
                "spend_60m_usd": round(spend_60m, 4),
                "rolling_hour_cap_usd": hour_cap,
                "usd_per_min_15m": round(usd_per_min_15, 4),
                "band": band,
                "total_usd": round(total_usd, 4),
                "by_model": [{"model_id": m, "cost_usd": round(c, 4)} for m, c in by_model],
            }, indent=2))
        else:
            print(f"chimera cost  band={band}  ($/min over 15m: ${usd_per_min_15:.3f})")
            print(f"  cycle {cycle_num:>3d} spend  ${cycle_usd:>7.2f}  (cap ${cycle_cap:.2f})")
            print(f"  15m rolling    ${spend_15m:>7.2f}")
            print(f"  60m rolling    ${spend_60m:>7.2f}  (cap ${hour_cap:.2f})")
            print(f"  total          ${total_usd:>7.2f}")
            if by_model:
                print()
                print("  by model (descending):")
                for m, c in by_model[:6]:
                    short = m.split("/")[-1] if "/" in m else m
                    print(f"    {short:35s}  ${c:>7.2f}")
            # Visual cue for over-cap conditions even in non-JSON path.
            if cycle_cap > 0 and cycle_usd >= cycle_cap:
                print()
                print(f"  ⚠️  cycle spend OVER per-cycle cap (${cycle_cap:.2f})")
            if hour_cap > 0 and spend_60m >= hour_cap:
                print(f"  ⚠️  60m spend OVER rolling-hour cap (${hour_cap:.2f})")
        return 0

    if args.command == "search":
        # v4.61 (ADR 0080): operator-facing FTS5 search over mind/wiki/.
        from .core import LoopConfig
        from .memory import open_and_init
        from .memory.wiki_search import (
            search_wiki,
            update_wiki_index,
            wiki_index_stats,
        )

        cfg = LoopConfig.from_env()
        conn = open_and_init(cfg.state_dir / "chimera.db")

        if args.rebuild:
            counts = update_wiki_index(conn, cfg.mind_dir / "wiki")
            if not args.json:
                churn = sum(v for k, v in counts.items() if k != "unchanged")
                print(
                    f"chimera search: index refresh — "
                    f"added={counts.get('added',0)} "
                    f"updated={counts.get('updated',0)} "
                    f"deleted={counts.get('deleted',0)} "
                    f"unchanged={counts.get('unchanged',0)}"
                )

        hits = search_wiki(conn, args.query, limit=args.limit)
        stats = wiki_index_stats(conn)

        if args.json:
            import json as _json
            print(_json.dumps({
                "query": args.query,
                "n_hits": len(hits),
                "indexed_files": stats.get("indexed_files", 0),
                "available": stats.get("available", False),
                "hits": [
                    {
                        "path": h.path, "title": h.title,
                        "snippet": h.snippet, "rank": h.rank,
                    }
                    for h in hits
                ],
            }, indent=2))
            return 0

        if not stats.get("available"):
            print("chimera search: FTS5 unavailable in this SQLite build.")
            return 1
        if not hits:
            print(
                f"chimera search: 0 hits for {args.query!r}  "
                f"(index has {stats.get('indexed_files', 0)} file(s))"
            )
            return 0
        print(
            f"chimera search: {len(hits)} hit(s) for {args.query!r}  "
            f"(of {stats.get('indexed_files', 0)} indexed file(s))"
        )
        for i, h in enumerate(hits, 1):
            print()
            print(f"  [{i}] {h.title or '(no title)'}  (rank={h.rank:.2f})")
            print(f"      mind/wiki/{h.path}")
            print(f"      {h.snippet.strip()}")
        return 0

    if args.command == "estimate":
        # v4.59 (ADR 0078): pre-flight INBOX cost projection.
        from .core import LoopConfig
        from .core.budget import cycle_cost_cap_usd, rolling_hour_cap_usd
        from .core.cost_estimate import estimate_inbox
        from .memory import open_and_init

        cfg = LoopConfig.from_env()
        conn = open_and_init(cfg.state_dir / "chimera.db")
        inbox = cfg.mind_dir / "INBOX.md"
        report = estimate_inbox(conn, inbox, default_tier=args.tier)

        cycle_cap = cycle_cost_cap_usd()
        hour_cap = rolling_hour_cap_usd()

        if args.json:
            import json as _json
            print(_json.dumps({
                "n_tasks": report.n_tasks,
                "total_usd": report.total_usd,
                "total_cycles": report.total_cycles,
                "cycle_cap_usd": cycle_cap,
                "rolling_hour_cap_usd": hour_cap,
                "tasks": [
                    {
                        "task_text": t.task_text[:200],
                        "tier": t.tier,
                        "model_id": t.model_id,
                        "estimated_cycles": t.estimated_cycles,
                        "estimated_usd": t.estimated_usd,
                        "used_history": t.used_history,
                        "n_historical_cycles": t.n_historical_cycles,
                        "prior_failures": t.prior_failures,
                    }
                    for t in report.tasks
                ],
            }, indent=2))
        else:
            print(f"chimera estimate  {report.n_tasks} open task(s)")
            if report.n_tasks == 0:
                print("  (inbox clear)")
                return 0
            print(
                f"  total estimate     ${report.total_usd:>7.2f}"
                f"  over ~{report.total_cycles} cycle(s)"
            )
            print(f"  per-cycle cap      ${cycle_cap:.2f}")
            print(f"  rolling-hour cap   ${hour_cap:.2f}")
            print()
            for i, t in enumerate(report.tasks, 1):
                src = "hist" if t.used_history else "tier-typical"
                short = t.model_id.split("/")[-1] if "/" in t.model_id else t.model_id
                preview = t.task_text.split("\n")[0][:60]
                print(
                    f"  [{i:2d}] ${t.estimated_usd:>7.2f}  "
                    f"tier={t.tier:6s}  cycles={t.estimated_cycles}  "
                    f"({src})  {short}"
                )
                print(f"        {preview}{'…' if len(t.task_text) > 60 else ''}")
            # Warnings:
            if cycle_cap > 0:
                tripped = [t for t in report.tasks if t.estimated_usd / t.estimated_cycles > cycle_cap]
                if tripped:
                    print()
                    print(
                        f"  ⚠️  {len(tripped)} task(s) project per-cycle spend "
                        f"> ${cycle_cap:.2f} cap; ACT will trip cost_cap on those."
                    )
            if hour_cap > 0 and report.total_usd > hour_cap:
                print()
                print(
                    f"  ⚠️  total projection ${report.total_usd:.2f} exceeds "
                    f"the rolling-60m cap ${hour_cap:.2f} — back-to-back cycles "
                    f"may trip rolling_hour_cap. Consider splitting the run."
                )
        return 0

    if args.command == "tiers":
        from .providers.tiers import TIER_LADDERS
        if args.json:
            import json as _json
            from .core import LoopConfig
            from datetime import datetime, timezone

            payload = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "tiers": {
                    tier: [
                        {
                            "model_id": r.config.model_id,
                            "openrouter_model_id": r.config.openrouter_model_id,
                            "provider": r.config.provider.value,
                            "input_cost_per_mtok": r.config.input_cost_per_mtok,
                            "output_cost_per_mtok": r.config.output_cost_per_mtok,
                            "context_tokens": r.capabilities.context_tokens,
                            "supports_tools": r.capabilities.supports_tools,
                        }
                        for r in rungs
                    ]
                    for tier, rungs in TIER_LADDERS.items()
                },
            }
            blob = _json.dumps(payload, indent=2)
            print(blob)
            cfg = LoopConfig.from_env()
            try:
                (cfg.state_dir / "tiers.json").write_text(blob, encoding="utf-8")
            except Exception:
                pass  # best-effort snapshot
            return 0
        for tier, rungs in TIER_LADDERS.items():
            print(f"chimera tiers: {tier} ({len(rungs)} rung(s))")
            for i, r in enumerate(rungs):
                cfg = r.config
                print(
                    f"  [{i}] {cfg.model_id:40s}  "
                    f"in=${cfg.input_cost_per_mtok:>5.2f}/Mtok  "
                    f"out=${cfg.output_cost_per_mtok:>5.2f}/Mtok  "
                    f"ctx={r.capabilities.context_tokens:>10,}"
                )
        return 0
    if args.command == "fragmentation":
        from .core.adaptation import list_fragmentation
        rows = list_fragmentation()
        if not rows:
            print("chimera fragmentation: (no records)")
            return 0
        print(f"chimera fragmentation: {len(rows)} record(s)")
        for r in rows:
            preview = r.task_text.split("\n")[0][:80]
            print(
                f"  cycle {r.cycle:3d}  rounds={r.rounds_used:2d}  "
                f"tools={r.tool_call_count:2d}  missing={len(r.missing_artifacts)}  "
                f"{preview}…"
            )
        return 0
    if args.command == "escalations":
        from .core import LoopConfig
        from .core.escalation import (
            clear_escalations,
            escalation_summary,
            hot_signatures,
            list_escalations,
        )
        from .memory import open_and_init

        cfg = LoopConfig.from_env()
        conn = open_and_init(cfg.state_dir / "chimera.db")
        sub_cmd = args.escalations_command or "list"
        if sub_cmd == "list":
            rows = list_escalations(
                conn, limit=args.limit, signature_substring=args.grep,
            )
            if not rows:
                print("chimera escalations: (none)")
                return 0
            print(f"chimera escalations: {len(rows)} row(s)")
            for r in rows:
                preview = r.task_text.split("\n")[0][:70]
                print(
                    f"  cycle {r.cycle:3d}  tier={r.tier:6s} "
                    f"reason={r.finish_reason:22s} rounds={r.rounds_used:2d}  "
                    f"{preview}…"
                )
            return 0
        if sub_cmd == "summary":
            summary = escalation_summary(conn)
            if not summary:
                print("chimera escalations summary: (none)")
            else:
                print(f"chimera escalations summary: {len(summary)} signature(s)")
                for sig, by_tier in sorted(
                    summary.items(), key=lambda kv: -sum(kv[1].values()),
                )[:20]:
                    bits = ", ".join(f"{t}×{n}" for t, n in sorted(by_tier.items()))
                    tokens = (sig.split(",")[:5]) or ["(empty)"]
                    preview = " ".join(tokens) + ("…" if len(sig.split(",")) > 5 else "")
                    print(f"  {bits:30s}  tokens: {preview}")
            # v4.54 (ADR 0073): A17 — surface hot signatures (≥2 failures)
            # at the bottom of the summary so the operator sees them
            # without an extra command. These are the candidates for
            # task-text rewriting rather than tier promotion.
            hot = hot_signatures(conn, threshold=2)
            if hot:
                print()
                print(f"⚠️  HOT SIGNATURES (≥2 failures — review task text, do not just promote tier):")
                for h in hot[:10]:
                    tiers = "/".join(h.tiers) if h.tiers else "?"
                    print(
                        f"  ×{h.total_failures}  tiers={tiers:18s}  "
                        f"cycles={h.first_seen_cycle}→{h.last_seen_cycle}  "
                        f"last={h.last_finish_reason}"
                    )
                    if h.excerpt:
                        print(f"      {h.excerpt}…")
            return 0
        if sub_cmd == "clear":
            if not args.grep and not args.all:
                parser.error(
                    "`escalations clear` requires --grep <substr> OR --all "
                    "(safety guard; the agent uses these rows to learn)."
                )
            n = clear_escalations(conn, signature_substring=args.grep)
            print(f"chimera escalations: deleted {n} row(s)")
            return 0
        parser.error(f"unknown escalations subcommand: {sub_cmd}")
    if args.command == "doctor":
        from .core import run_checks
        results = run_checks()
        rc = 0
        print("chimera doctor:")
        for r in results:
            marker = {"ok": "✓", "warn": "!", "error": "✗"}.get(r.status, "?")
            print(f"  [{marker}] {r.name:24s} {r.message}")
            if r.status == "error":
                rc = 1
        return rc
    if args.command == "status":
        from .core import load_heartbeat, LoopConfig
        cfg = LoopConfig.from_env()
        state, _ = load_heartbeat(cfg.mind_dir / "HEARTBEAT.md")
        print(
            f"chimera: cycle={state.cycle} trust_tier={state.trust_tier} "
            f"status={state.status} session_started_at={state.session_started_at}"
        )
        return 0
    if args.command == "run":
        from .core import ChimeraLoop, LoopConfig
        # v4.41: honour the optional ad-hoc prompt — append it to INBOX.md
        # so ASSESS picks it up as an open task on this cycle.
        if args.prompt:
            cfg = LoopConfig.from_env()
            inbox = cfg.mind_dir / "INBOX.md"
            inbox.parent.mkdir(parents=True, exist_ok=True)
            existing = inbox.read_text(encoding="utf-8") if inbox.exists() else "# Inbox\n"
            if not existing.endswith("\n"):
                existing += "\n"
            with inbox.open("a", encoding="utf-8") as fh:
                if not existing.startswith("# "):
                    fh.write("# Inbox\n")
                fh.write(f"- [ ] {args.prompt}\n")
            print(f"chimera run: enqueued task to {inbox}")
        report = asyncio.run(ChimeraLoop().run_one_cycle())
        for line in report.phase_log:
            print(f"  {line}")
        if report.phase_times_ms:
            timings = "  ".join(
                f"{k}={v:.0f}ms" for k, v in report.phase_times_ms.items()
            )
            print(f"  timings: {timings}")
        print(
            f"cycle {report.cycle}: tasks_seen={report.tasks_seen} "
            f"flipped={report.tasks_completed} rotated={report.rotated}"
        )
        return 0
    if args.command == "ping":
        targets = ["anthropic", "openrouter"] if args.provider == "both" else [args.provider]
        print("chimera ping:")
        rc = 0
        for t in targets:
            rc |= asyncio.run(_ping_provider(t))
        return rc
    if args.command == "serve":
        from .server import serve_http, serve_stdio
        if args.http:
            return asyncio.run(
                serve_http(host=args.host, port=args.port, name=args.name)
            )
        return asyncio.run(serve_stdio(name=args.name))
    if args.command == "peers":
        from .a2a import forget as _forget_peer
        from .a2a import list_peers as _list_peers
        from .a2a import registry_dir as _registry_dir
        from .a2a import sweep_stale as _sweep_stale

        sub_cmd = args.peers_command or "list"
        if sub_cmd == "list":
            entries = _list_peers()
            d = _registry_dir()
            if not entries:
                print(f"chimera peers: (registry dir {d} is empty)")
                return 0
            print(f"chimera peers ({len(entries)} entries in {d}):")
            for e in entries:
                caps = ", ".join(e.capabilities)
                print(
                    f"  {e.agent_id}  v{e.version}  host={e.host}  pid={e.pid}  "
                    f"transport={e.reach.get('transport', '?')}\n    caps: {caps}"
                )
            return 0
        if sub_cmd == "forget":
            ok = _forget_peer(args.agent_id)
            print(f"chimera peers: {'removed' if ok else 'not found'} — {args.agent_id}")
            return 0 if ok else 1
        if sub_cmd == "sweep":
            n = _sweep_stale()
            print(f"chimera peers: removed {n} stale entr(ies)")
            return 0
        if sub_cmd == "sync":
            from .a2a import sync_remote_peers
            urls = None
            if args.urls:
                urls = [u.strip() for u in args.urls.split(",") if u.strip()]
            result = sync_remote_peers(urls)
            print(
                f"chimera peers sync: fetched={result.fetched} "
                f"added={result.added} updated={result.updated} "
                f"failed={len(result.failures)}"
            )
            for url, err in result.failures:
                print(f"  ! {url}: {err}")
            return 0 if not result.failures else 1
        if sub_cmd == "sweep-remote":
            from .a2a import sweep_remote_stale
            n = sweep_remote_stale(max_age_hours=args.max_age_hours)
            print(f"chimera peers: removed {n} stale remote entr(ies)")
            return 0
        if sub_cmd == "kfm":
            from .a2a import fetch_peer_kfm, list_peer_chimeras
            from .core import ChimeraLoop
            from .tools import register_mcp_servers_from_env

            loop = ChimeraLoop()
            asyncio.run(register_mcp_servers_from_env(loop._registry))  # type: ignore[attr-defined]
            targets: list[str]
            if args.name:
                targets = [args.name]
            else:
                targets = list_peer_chimeras(loop._registry)  # type: ignore[attr-defined]
            if not targets:
                print("chimera peers kfm: no peer Chimeras discovered via MCP.")
                loop.close()
                return 0
            import json as _json
            print(f"chimera peers kfm: querying {len(targets)} peer(s)...")
            for t in targets:
                try:
                    snap = asyncio.run(fetch_peer_kfm(t, registry=loop._registry))  # type: ignore[attr-defined]
                    print(f"  {t}:")
                    for k, v in sorted(snap.items()):
                        print(f"    {k}: {v}")
                except Exception as exc:
                    print(f"  {t}: error: {exc}")
            loop.close()
            return 0
        parser.error(f"unknown peers subcommand: {sub_cmd}")
        return 2
    if args.command == "a2a":
        from .a2a import AgentIdentity, list_xenocomm_tools
        from .core import ChimeraLoop
        from .tools import register_mcp_servers_from_env

        sub_cmd = args.a2a_command or "identity"
        if sub_cmd == "identity":
            ident = AgentIdentity()
            import json as _json
            print(_json.dumps(ident.to_dict(), indent=2))
            return 0
        if sub_cmd == "peers":
            loop = ChimeraLoop()
            asyncio.run(register_mcp_servers_from_env(loop._registry))  # type: ignore[attr-defined]
            tools = list_xenocomm_tools(loop._registry)  # type: ignore[attr-defined]
            loop.close()
            if not tools:
                print(
                    "chimera a2a: no Xenocomm tools discovered. "
                    "Set CHIMERA_MCP_SERVERS to include a 'xenocomm' entry "
                    "(see docs/adr/0004-xenocomm-a2a.md)."
                )
                return 0
            print(f"chimera a2a: {len(tools)} Xenocomm tool(s) discovered:")
            for t in tools:
                print(f"  - {t}")
            return 0
        parser.error(f"unknown a2a subcommand: {sub_cmd}")
        return 2
    if args.command == "trust":
        from .core import LoopConfig
        from .trust import TrustManager

        cfg = LoopConfig.from_env()
        tm = TrustManager(cfg.state_dir / "trust_state.json")
        sub_cmd = args.trust_command or "show"
        if sub_cmd == "show":
            print(f"chimera trust: {tm.tier.name} ({tm.tier.label})")
            print(f"  hours_in_tier: {tm.hours_in_current_tier():.2f}")
            print(f"  last_readiness: {tm.state.last_readiness:.2f}")
            recent = tm.state.history[-5:]
            if recent:
                print("  recent events:")
                for ev in recent:
                    print(
                        f"    {ev.timestamp} {ev.kind:11s} "
                        f"T{ev.from_tier}→T{ev.to_tier}  {ev.reason}"
                    )
            return 0
        if sub_cmd == "promote":
            ok = tm.promote(reason=args.reason)
            print(f"chimera trust: {'promoted' if ok else 'no-op'} → {tm.tier.name}")
            return 0 if ok else 1
        if sub_cmd == "demote":
            ok = tm.demote(reason=args.reason)
            print(f"chimera trust: {'demoted' if ok else 'no-op'} → {tm.tier.name}")
            return 0 if ok else 1
        if sub_cmd == "lockdown":
            ok = tm.lockdown(reason=args.reason)
            print(f"chimera trust: {'locked down' if ok else 'no-op (already T0)'}")
            return 0 if ok else 1
        parser.error(f"unknown trust subcommand: {sub_cmd}")
        return 2
    if args.command == "mutations":
        from .core import LoopConfig
        from .memory import (
            approve_mutation as _approve,
            get_mutation as _get,
            list_mutations as _list,
            open_and_init,
            queue_health as _queue_health,
            reject_mutation as _reject,
        )
        import json as _json

        cfg = LoopConfig.from_env()
        conn = open_and_init(cfg.state_dir / "chimera.db")
        sub_cmd = args.mut_command or "list"
        if sub_cmd == "list":
            rows = _list(conn, status="pending")
            if not rows:
                print("(no pending mutations)")
                return 0
            print(f"{len(rows)} pending mutation(s):")
            for m in rows:
                payload_preview = _json.dumps(m.payload)[:100]
                print(f"  #{m.id:3d}  [{m.type}]  {payload_preview}")
            return 0
        if sub_cmd == "show":
            m = _get(conn, args.id)
            if m is None:
                print(f"mutation #{args.id} not found")
                return 1
            print(f"#{m.id}  [{m.type}]  status={m.status}")
            print(f"created_at: {m.created_at}")
            print(f"approved_at: {m.approved_at}")
            print(f"applied_at: {m.applied_at}")
            print(f"reason: {m.reason}")
            print(f"payload:\n{_json.dumps(m.payload, indent=2)}")
            return 0
        if sub_cmd == "approve":
            try:
                m = _approve(conn, args.id, reason=args.reason)
            except ValueError as e:
                print(f"error: {e}")
                return 1
            print(f"approved mutation #{m.id} ({m.type})")
            return 0
        if sub_cmd == "reject":
            try:
                m = _reject(conn, args.id, reason=args.reason)
            except ValueError as e:
                print(f"error: {e}")
                return 1
            print(f"rejected mutation #{m.id} ({m.type})")
            return 0
        if sub_cmd == "health":
            snap = _queue_health(conn)
            if getattr(args, "json", False):
                print(_json.dumps(snap, indent=2, sort_keys=True))
                return 0
            counts = snap["counts"]
            total = sum(counts.values())
            print(f"mutation queue: {total} total")
            for st in (
                "pending",
                "approved",
                "applied",
                "rejected",
                "expired",
                "failed",
            ):
                n = counts.get(st, 0)
                if n:
                    print(f"  {st:9s} {n:4d}")
            age = snap["pending_oldest_age_seconds"]
            if age is not None:
                print(f"oldest pending: {age}s ago")
            rmax = snap["pending_recurrence_max"]
            rsum = snap["pending_recurrence_total"]
            if rmax or rsum:
                print(
                    f"pending recurrence: max={rmax} total={rsum}  "
                    "(duplicates absorbed in-place)"
                )
            ar = snap["approved_ratio"]
            if ar is not None:
                print(f"applied / decided: {ar:.0%}")
            return 0
        parser.error(f"unknown mutations subcommand: {sub_cmd}")
        return 2
    if args.command == "skills":
        from .core import LoopConfig
        from .memory import (
            get_mutation as _get,
            mark_applied as _mark_applied,
            mark_failed as _mark_failed,
            open_and_init,
        )
        from .skills import (
            SkillSpec,
            activate_skill,
            assemble_skill,
            dynamic_skills_dir,
            load_dynamic_skills,
            validate_skill,
        )
        from .core.act import ActExecutor
        from .tools import ToolRegistry, register_core_tools

        sub_cmd = args.skills_command or "list"

        if sub_cmd == "list":
            reg = ToolRegistry()
            register_core_tools(reg)
            loaded = load_dynamic_skills(reg)
            print(f"chimera skills: {len(loaded)} dynamic skill(s) loaded")
            for name in loaded:
                entry = reg.get(name)
                desc = entry.description if entry else ""
                print(f"  - {name}: {desc}")
            return 0

        if sub_cmd == "assemble":
            cfg = LoopConfig.from_env()
            conn = open_and_init(cfg.state_dir / "chimera.db")
            mutation = _get(conn, args.mutation_id)
            if mutation is None:
                print(f"mutation #{args.mutation_id} not found")
                return 1
            if mutation.type != "skill_proposal":
                print(f"mutation #{args.mutation_id} is type={mutation.type!r}, not 'skill_proposal'")
                return 1
            if mutation.status != "approved":
                print(
                    f"mutation #{args.mutation_id} is status={mutation.status!r}; "
                    "must be 'approved' (run `chimera mutations approve {id}` first)"
                )
                return 1

            try:
                spec = SkillSpec(
                    name=mutation.payload.get("name", ""),
                    description=mutation.payload.get("description", ""),
                    brief=mutation.payload.get("brief", ""),
                )
            except ValueError as exc:
                _mark_failed(conn, mutation.id, reason=f"bad spec: {exc}")
                print(f"bad SkillSpec: {exc}")
                return 1

            # Construct providers via ACT executor helper.
            ax = ActExecutor.from_env(dispatcher=None, db=conn)  # type: ignore[arg-type]
            if ax is None:
                print("no provider keys; cannot assemble")
                return 1

            from .skills import assemble_with_escalation, record_assembly

            print(f"assembling skill {spec.name!r} (with tier escalation)...")
            ladder = asyncio.run(
                assemble_with_escalation(
                    spec,
                    providers=ax.providers,
                    db=conn,
                    cycle=-1,
                )
            )
            try:
                record_assembly(mutation.id, spec.name, ladder)
            except Exception:
                pass  # journal write is best-effort
            for att in ladder.attempts:
                if not att.assembled_ok:
                    print(f"  [{att.tier}] assembly failed: {att.failure_reason}")
                    continue
                line = (
                    f"  [{att.tier}] base={int(att.validation_score * 100)}%"
                )
                if att.revised:
                    rev = int((att.revised_score or 0.0) * 100)
                    line += f"  revised={rev}%"
                if att.witnesses:
                    line += f"  witnesses={','.join(att.witnesses)}"
                if att.winning_witness:
                    line += f"  winner={att.winning_witness}"
                line += f"  ok={att.validation_ok or bool(att.winning_witness)}"
                print(line)
            assembled = ladder.assembled
            validation = ladder.validation
            if ladder.winning_tier is None:
                _mark_failed(
                    conn, mutation.id,
                    reason=(
                        f"ladder exhausted: last failure "
                        f"{validation.failure_reason or 'unknown'}"
                    ),
                )
                print("ladder exhausted; no tier produced a valid skill.")
                return 1
            print(f"  winning tier: {ladder.winning_tier}")
            print(f"  schema: {assembled.schema['function']['name']}")
            print(f"  samples: {len(assembled.samples)}")
            print(
                f"  validation: passed {validation.passed}/{validation.total} "
                f"(score={validation.score:.2f}, ok={validation.ok})"
            )

            print("activating...")
            result = activate_skill(assembled, validation)
            if not result.ok:
                _mark_failed(conn, mutation.id, reason=f"activation: {result.failure_reason}")
                print(f"activation failed: {result.failure_reason}")
                return 1
            print(f"  written to: {result.path}")
            print(f"  registered as: {result.tool_name}")
            _mark_applied(conn, mutation.id, reason=f"activated at {result.path}")
            return 0

        parser.error(f"unknown skills subcommand: {sub_cmd}")
        return 2
    if args.command == "engines":
        from .core import ChimeraLoop

        if args.engines_command != "run":
            parser.error("engines: expected 'run <name>'")
        loop = ChimeraLoop()
        result = asyncio.run(loop.force_run_engine(args.name))
        loop.close()
        print(f"chimera engines run {args.name}:")
        print(f"  skipped: {result.skipped}")
        print(f"  api_calls: {result.api_call_count}")
        if result.failure_reason:
            print(f"  failure: {result.failure_reason}")
            return 1
        print(f"  artifacts: {result.artifacts}")
        print(f"  summary: {result.summary}")
        return 0
    if args.command == "ontology":
        from .core import LoopConfig
        from .memory import (
            apply_approved_kills,
            audit_ontology,
            auto_archive_stale_deprecated,
            list_entities,
            list_transitions,
            open_and_init,
            propose_kill_archived,
        )
        import json as _json

        cfg = LoopConfig.from_env()
        conn = open_and_init(cfg.state_dir / "chimera.db")

        if getattr(args, "propose_kills", False):
            row = conn.execute(
                "SELECT COALESCE(MAX(cycle), 0) AS c FROM agent_activity_log"
            ).fetchone()
            cycle = args.cycle if args.cycle is not None else (int(row["c"]) if row else 0)
            proposed = propose_kill_archived(
                conn,
                current_cycle=cycle,
                archive_after_cycles=args.archive_after_cycles,
                dry_run=args.dry_run,
            )
            verb = "would propose" if args.dry_run else "queued"
            print(
                f"chimera ontology --propose-kills @ cycle {cycle} "
                f"(ARCHIVED >= {args.archive_after_cycles} cycles): "
                f"{verb} {len(proposed)} kill_entity mutation(s)"
            )
            for e in proposed:
                print(
                    f"  [{e['kind']:8s}] {e['name']}  "
                    f"({e['cycles_in_state']} cycles in ARCHIVED)"
                )
            if proposed and not args.dry_run:
                print("Next: `chimera mutations list` → approve → `chimera ontology --apply-kills`")
            return 0
        if getattr(args, "apply_kills", False):
            row = conn.execute(
                "SELECT COALESCE(MAX(cycle), 0) AS c FROM agent_activity_log"
            ).fetchone()
            cycle = args.cycle if args.cycle is not None else (int(row["c"]) if row else 0)
            killed = apply_approved_kills(conn, current_cycle=cycle)
            print(
                f"chimera ontology --apply-kills @ cycle {cycle}: "
                f"killed {len(killed)} entit{'y' if len(killed) == 1 else 'ies'}"
            )
            for k in killed:
                print(f"  #{k['mutation_id']:4d}  [{k.get('kind','?'):8s}] {k.get('name','?')}")
            return 0
        if getattr(args, "archive_stale", False):
            row = conn.execute(
                "SELECT COALESCE(MAX(cycle), 0) AS c FROM agent_activity_log"
            ).fetchone()
            cycle = args.cycle if args.cycle is not None else (int(row["c"]) if row else 0)
            archived = auto_archive_stale_deprecated(
                conn,
                current_cycle=cycle,
                archive_after_cycles=args.archive_after_cycles,
                dry_run=args.dry_run,
            )
            verb = "would archive" if args.dry_run else "archived"
            print(
                f"chimera ontology --archive-stale @ cycle {cycle} "
                f"(after >= {args.archive_after_cycles} cycles): "
                f"{verb} {len(archived)}"
            )
            for e in archived:
                print(
                    f"  [{e['kind']:8s}] {e['name']}  "
                    f"({e['cycles_in_state']} cycles in DEPRECATED)"
                )
            return 0

        if getattr(args, "audit", False):
            # Reference cycle: explicit > inferred from activity log > 0.
            cycle = args.cycle
            if cycle is None:
                row = conn.execute(
                    "SELECT COALESCE(MAX(cycle), 0) AS c FROM agent_activity_log"
                ).fetchone()
                cycle = int(row["c"]) if row else 0
            snap = audit_ontology(
                conn,
                current_cycle=cycle,
                stale_after_cycles=args.stale_after_cycles,
            )
            if args.json:
                print(_json.dumps(snap, indent=2, sort_keys=True))
                return 0
            print(
                f"chimera ontology audit @ cycle {cycle}  "
                f"(stale>={args.stale_after_cycles})"
            )
            print(f"  total entities: {snap['total_entities']}")
            if snap["by_kind"]:
                print("  by kind:")
                for k, n in sorted(snap["by_kind"].items()):
                    print(f"    {k:10s} {n}")
            if snap["by_state"]:
                print("  by state:")
                for s, n in sorted(snap["by_state"].items()):
                    print(f"    {s:12s} {n}")
            print(f"  stale: {snap['stale_count']}")
            for e in snap["stale_entities"]:
                print(
                    f"    [{e['kfm_state']:11s}] {e['kind']:8s} {e['name']}  "
                    f"({e['cycles_in_state']} cycles in state)"
                )
            print(f"  dead: {snap['dead_count']} (no activity in last "
                  f"{snap['thresholds']['activity_window_cycles']} cycles)")
            for e in snap["dead_entities"]:
                print(
                    f"    [{e['kfm_state']:11s}] {e['kind']:8s} {e['name']}"
                )
            print(
                f"  reanchor events (last {snap['reanchor_window_cycles']} "
                f"cycles): {snap['reanchor_events_in_window']}"
            )
            print(
                f"  deprecated-but-not-archived: {snap['deprecated_unarchived']}"
            )
            return 0

        entities = list_entities(conn, kind=args.kind)
        if not entities:
            print("chimera ontology: (no entities)")
            return 0
        print(f"chimera ontology ({len(entities)} entities):")
        for e in entities:
            print(
                f"  [{e.kfm_state:11s}] {e.kind:8s} {e.name}  "
                f"(id={e.id[:8]}… cycle={e.state_entered_at_cycle})"
            )
            transitions = list_transitions(conn, e.id)
            for t in transitions:
                print(
                    f"      ↳ cycle {t.cycle}: {t.from_state} → {t.to_state} "
                    f"by '{t.operator_type}'"
                )
        return 0
    if args.command == "scenario":
        from .core import LoopConfig
        from .scenarios import run_drift_scenario, run_research_scenario

        cfg = LoopConfig.from_env()
        if args.name == "drift":
            result = run_drift_scenario(cfg.mind_dir, cfg.state_dir)
            print(f"chimera scenario drift:")
            print(f"  plan_demoted: {result.plan_demoted}")
            print(f"  final_plan_state: {result.final_plan_state}")
            print(f"  plan_count: {result.plan_count}")
            print(f"  transcript: {result.transcript_path}")
            return 0 if result.plan_demoted else 1
        if args.name == "research":
            result = run_research_scenario(cfg.mind_dir, cfg.state_dir)
            print(f"chimera scenario research:")
            if result.skipped:
                print("  SKIPPED (no provider keys set)")
                print(f"  transcript: {result.transcript_path}")
                return 2
            print(f"  tasks_seen: {result.tasks_seen}")
            print(f"  tasks_completed: {result.tasks_completed}")
            print(f"  api_calls: {result.api_calls}")
            print(f"  tool_calls: {result.tool_call_count}")
            print(f"  transcript: {result.transcript_path}")
            return 0 if result.tasks_completed == result.tasks_seen else 1
        if args.name == "multi_host":
            from .scenarios import run_multi_host_demo
            workdir = cfg.state_dir.parent / "multi_host_demo"
            result = run_multi_host_demo(workdir)
            print("chimera scenario multi_host:")
            print(f"  peer_a_port: {result.peer_a_port}")
            print(f"  peer_a_agent_id: {result.peer_a_agent_id}")
            print(f"  peers_synced: {result.peers_synced}")
            print(f"  emergence_records: {result.emergence_records}")
            if result.failures:
                print("  failures:")
                for f in result.failures:
                    print(f"    - {f}")
            print(f"  ok: {result.ok}")
            return 0 if result.ok else 1
        if args.name == "two_chimera":
            from .scenarios import run_two_chimera_demo as _tcd
            peer_root = cfg.state_dir.parent / "peer_chimera"
            result = _tcd(peer_root)
            print("chimera scenario two_chimera:")
            print(f"  discovered_tools: {result.discovered_tools}")
            print(f"  ok: {result.ok}")
            print("  call_result:")
            for line in result.call_result.splitlines():
                print(f"    {line}")
            return 0 if result.ok else 1
        if args.name == "federation_http_drill":
            from .scenarios import run_federation_http_drill as _fhd
            peer_root = cfg.state_dir.parent / "peer_chimera"
            result = _fhd(peer_root)
            print("chimera scenario federation_http_drill:")
            print(f"  server_url:        {result.server_url}")
            print(f"  health_ok:         {result.health_ok}")
            print(f"  auth_rejected:     {result.auth_rejected_anonymous}")
            print(f"  identity.role:     {(result.identity or {}).get('role')}")
            print(f"  kfm.cycle:         {(result.kfm or {}).get('cycle')}")
            print(f"  witness_lines:     {result.witness_lines}")
            if result.failures:
                print("  failures:")
                for f in result.failures:
                    print(f"    - {f}")
            print(f"  ok: {result.ok}")
            return 0 if result.ok else 1
        if args.name == "federation_trust_drill":
            from .scenarios import run_federation_trust_drill as _ftd
            peer_root = cfg.state_dir.parent / "peer_chimera"
            result = _ftd(peer_root)
            print("chimera scenario federation_trust_drill:")
            print(f"  locked.decision:   {result.locked_decision}")
            print(f"  locked.reason:     {result.locked_reason}")
            print(f"  degraded.decision: {result.degraded_decision}")
            print(f"  degraded.reason:   {result.degraded_reason}")
            print(f"  healthy.decision:  {result.healthy_decision}")
            print(f"  healthy.reason:    {result.healthy_reason}")
            print(f"  journal_records:   {result.journal_records}")
            if result.failures:
                print("  failures:")
                for f in result.failures:
                    print(f"    - {f}")
            print(f"  ok: {result.ok}")
            return 0 if result.ok else 1
        if args.name == "federation_drill":
            from .scenarios import run_federation_drill as _fd
            peer_root = cfg.state_dir.parent / "peer_chimera"
            result = _fd(peer_root)
            print("chimera scenario federation_drill:")
            print(f"  discovered_tools: {result.discovered_tools}")
            print(f"  identity.role: {(result.identity or {}).get('role')}")
            print(f"  identity.agent_id: {(result.identity or {}).get('agent_id')}")
            print(f"  kfm.cycle: {(result.kfm or {}).get('cycle')}")
            print(f"  kfm.trust_tier: {(result.kfm or {}).get('trust_tier')}")
            print(f"  witness_lines: {result.witness_lines}")
            print(f"  observations_written: {result.observations_written}")
            print(f"  journal_entries_after: {result.journal_entries_after}")
            if result.failures:
                print("  failures:")
                for f in result.failures:
                    print(f"    - {f}")
            print(f"  ok: {result.ok}")
            return 0 if result.ok else 1
    if args.command == "graph":
        from .core import LoopConfig
        from .core.loop import graph_projection_enabled
        from .memory import GraphStore, default_graph_dir, open_and_init

        cfg = LoopConfig.from_env()
        sub_cmd = args.graph_command or "init"
        store = GraphStore(default_graph_dir())
        # v4.62 (ADR 0081): emit a hint when the explicit CLI is used but
        # the housekeeping auto-refresh isn't enabled — so the operator
        # knows their hand-rebuilt graph will go stale next cycle.
        if sub_cmd in ("init", "rebuild") and not graph_projection_enabled():
            print(
                "ℹ️  graph projection is currently OPT-IN (default off as of v4.62). "
                "Set CHIMERA_GRAPH_ENABLED=1 for auto-refresh in housekeeping; "
                "otherwise re-run `chimera graph rebuild` manually."
            )
        if sub_cmd == "init":
            store.init_schema()
            print(f"chimera graph: schema ready at {store.path}")
            return 0
        if sub_cmd == "rebuild":
            conn = open_and_init(cfg.state_dir / "chimera.db")
            if getattr(args, "incremental", False):
                counts = store.update_from_sqlite(conn)
                mode = "incremental"
            else:
                counts = store.rebuild_from_sqlite(conn)
                mode = "full"
            print(f"chimera graph rebuild ({mode}, {store.path}):")
            for k, v in sorted(counts.items()):
                print(f"  {k}: {v}")
            return 0
        if sub_cmd == "query":
            store.init_schema()
            result = store.query(args.cypher)
            print("  " + " | ".join(result.columns))
            for row in result.rows:
                print("  " + " | ".join(str(c) for c in row))
            print(f"({len(result.rows)} row(s))")
            return 0
        if sub_cmd == "entity-history":
            store.init_schema()
            ident = args.ident
            res = store.query(
                "MATCH (e:Entity) WHERE e.id = $i OR e.id STARTS WITH $i "
                "OR e.name = $i RETURN e.id, e.kind, e.name LIMIT 1",
                params={"i": ident},
            )
            if not res.rows:
                print(f"chimera graph: no entity matches {ident!r}")
                return 1
            eid, kind, name = res.rows[0]
            print(f"chimera graph entity-history: [{kind}] {name} ({eid[:8]}…)")
            hist = store.query(
                "MATCH (e:Entity {id: $i})-[t:TRANSITIONED_TO]->(e) "
                "RETURN t.cycle, t.from_state, t.to_state, t.operator_type, t.reason "
                "ORDER BY t.cycle",
                params={"i": eid},
            )
            if not hist.rows:
                print("  (no transitions)")
                return 0
            for cyc, fs, ts, op, reason in hist.rows:
                print(f"  cycle {cyc}: {fs} → {ts} by {op!r}  {reason}")
            return 0
        if sub_cmd == "skill-deps":
            store.init_schema()
            skills = store.query("MATCH (s:Skill) RETURN s.name ORDER BY s.name").rows
            if not skills:
                print("chimera graph skill-deps: (no dynamic skills)")
                return 0
            print(f"chimera graph skill-deps: {len(skills)} skill(s)")
            for (sn,) in skills:
                deps = store.query(
                    "MATCH (:Skill {name: $n})-[:DEPENDS_ON]->(d:Skill) RETURN d.name",
                    params={"n": sn},
                ).rows
                tools = store.query(
                    "MATCH (:Skill {name: $n})-[:USES_TOOL]->(t:Entity) RETURN t.name",
                    params={"n": sn},
                ).rows
                print(f"  {sn}")
                if deps:
                    print(f"    depends_on: {', '.join(d[0] for d in deps)}")
                if tools:
                    print(f"    uses_tool:  {', '.join(t[0] for t in tools)}")
                if not deps and not tools:
                    print("    (no edges)")
            return 0
        if sub_cmd == "orphans":
            store.init_schema()
            orphan_ents = store.query(
                "MATCH (e:Entity) WHERE NOT EXISTS { "
                "MATCH (e)-[:TRANSITIONED_TO]->(e) } "
                "RETURN e.kind, e.name ORDER BY e.kind, e.name"
            ).rows
            orphan_skills = store.query(
                "MATCH (s:Skill) WHERE NOT EXISTS { MATCH (s)-[:DEPENDS_ON]->() } "
                "AND NOT EXISTS { MATCH (s)-[:USES_TOOL]->() } "
                "RETURN s.name ORDER BY s.name"
            ).rows
            print(f"chimera graph orphans:")
            print(f"  entities with no transitions: {len(orphan_ents)}")
            for kind, name in orphan_ents:
                print(f"    [{kind}] {name}")
            print(f"  skills with no edges: {len(orphan_skills)}")
            for (n,) in orphan_skills:
                print(f"    {n}")
            return 0
        if sub_cmd == "export":
            import json as _json
            from datetime import datetime, timezone

            store.init_schema()
            snapshot: dict[str, Any] = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            cols = lambda r: [dict(zip(r.columns, row)) for row in r.rows]
            snapshot["entities"] = cols(store.query(
                "MATCH (e:Entity) RETURN e.id AS id, e.kind AS kind, "
                "e.name AS name, e.kfm_state AS kfm_state "
                "ORDER BY e.kind, e.name"
            ))
            skill_names = [r[0] for r in store.query(
                "MATCH (s:Skill) RETURN s.name ORDER BY s.name"
            ).rows]
            skills: list[dict[str, Any]] = []
            for sn in skill_names:
                deps = [r[0] for r in store.query(
                    "MATCH (:Skill {name: $n})-[:DEPENDS_ON]->(d:Skill) RETURN d.name",
                    params={"n": sn},
                ).rows]
                tools = [r[0] for r in store.query(
                    "MATCH (:Skill {name: $n})-[:USES_TOOL]->(t:Entity) RETURN t.name",
                    params={"n": sn},
                ).rows]
                skills.append({"name": sn, "deps": deps, "tools": tools})
            snapshot["skills"] = skills
            snapshot["proposed"] = cols(store.query(
                "MATCH (m:Mutation)-[:PROPOSED]->(e:Entity) "
                "RETURN m.id AS id, m.type AS type, m.status AS status, "
                "e.kind AS entity_kind, e.name AS entity_name "
                "ORDER BY m.id DESC LIMIT 50"
            ))
            snapshot["activated"] = cols(store.query(
                "MATCH (m:Mutation)-[:ACTIVATED]->(s:Skill) "
                "RETURN m.id AS id, s.name AS skill ORDER BY m.id DESC LIMIT 50"
            ))
            snapshot["trusted"] = cols(store.query(
                "MATCH (a:Peer)-[t:TRUSTED]->(b:Peer) "
                "RETURN a.agent_id AS from, b.agent_id AS to, "
                "t.verdict AS verdict, t.drift_score AS drift_score, "
                "t.recorded_at AS recorded_at"
            ))
            out_path = Path(args.out) if args.out else (
                cfg.state_dir / "chimera.graph.snapshot.json"
            )
            out_path.write_text(_json.dumps(snapshot, indent=2), encoding="utf-8")
            print(f"chimera graph export: {out_path}")
            return 0
        if sub_cmd == "stress":
            import json as _json
            import tempfile
            from .scenarios import run_graph_stress

            with tempfile.TemporaryDirectory(prefix="chimera-stress-") as td:
                td_path = Path(td)
                result = run_graph_stress(
                    sqlite_path=td_path / "chimera.db",
                    graph_path=td_path / "chimera.graph",
                    n_entities=args.entities,
                    transitions_each=args.transitions_each,
                    repeat_queries=args.repeat,
                )
            payload = result.to_dict()
            if args.json:
                print(_json.dumps(payload, indent=2, sort_keys=True))
                return 0 if result.ok else 1
            print(
                f"chimera graph stress: {result.n_entities} entities, "
                f"{result.n_transitions} transitions"
            )
            print(f"  populate: {result.populate_seconds:.3f}s")
            print(f"  rebuild:  {result.rebuild_seconds:.3f}s")
            for k, v in sorted(result.rebuild_counts.items()):
                print(f"    {k:18s} {v}")
            print("  queries (p50 / p95 ms):")
            for q in result.query_timings:
                print(
                    f"    {q.label:28s} rows={q.rows:4d}  "
                    f"p50={q.p50_ms:7.3f}  p95={q.p95_ms:7.3f}"
                )
            print(f"  restart_count_match: {result.restart_count_match}")
            if result.failures:
                print("  failures:")
                for f in result.failures:
                    print(f"    - {f}")
            print(f"  ok: {result.ok}")
            return 0 if result.ok else 1
        if sub_cmd == "provenance":
            store.init_schema()
            mid = args.mutation_id
            mut = store.query(
                "MATCH (m:Mutation {id: $i}) RETURN m.type, m.status, m.reason",
                params={"i": mid},
            )
            if not mut.rows:
                print(f"chimera graph provenance: mutation #{mid} not in graph")
                return 1
            mtype, mstatus, mreason = mut.rows[0]
            print(f"chimera graph provenance: mutation #{mid}  [{mtype}]  status={mstatus}")
            if mreason:
                print(f"  reason: {mreason}")
            proposed = store.query(
                "MATCH (:Mutation {id: $i})-[:PROPOSED]->(e:Entity) "
                "RETURN e.id, e.kind, e.name, e.kfm_state",
                params={"i": mid},
            ).rows
            for eid, kind, name, st in proposed:
                print(f"  PROPOSED → [{kind}] {name} ({eid[:8]}…) state={st}")
            activated = store.query(
                "MATCH (:Mutation {id: $i})-[:ACTIVATED]->(s:Skill) "
                "RETURN s.name, s.source_path",
                params={"i": mid},
            ).rows
            for sn, sp in activated:
                print(f"  ACTIVATED → skill {sn}  ({sp})")
            if not proposed and not activated:
                print("  (no provenance edges)")
            return 0
        parser.error(f"unknown graph subcommand: {sub_cmd}")
        return 2
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
