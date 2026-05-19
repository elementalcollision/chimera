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

    run = sub.add_parser("run", help="Run one cycle of the agent loop (stub).")
    run.add_argument("prompt", nargs="?", help="Optional ad-hoc prompt to enqueue.")

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
        choices=("drift", "research", "two_chimera"),
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

    graph = sub.add_parser(
        "graph",
        help="LadybugDB graph store: init / query / rebuild (v2.10+).",
    )
    graph_sub = graph.add_subparsers(dest="graph_command", metavar="<graph-cmd>")
    graph_sub.add_parser("init", help="Create schema in state/chimera.graph/.")
    graph_sub.add_parser("rebuild", help="Re-project SQLite + registry into the graph.")
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
        from .core import ChimeraLoop
        report = asyncio.run(ChimeraLoop().run_one_cycle())
        for line in report.phase_log:
            print(f"  {line}")
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

            print(f"assembling skill {spec.name!r}...")
            assembled = asyncio.run(
                assemble_skill(
                    spec,
                    providers=ax.providers,
                    db=conn,
                    cycle=-1,
                )
            )
            if not assembled.ok:
                _mark_failed(conn, mutation.id, reason=f"assembly: {assembled.failure_reason}")
                print(f"assembly failed: {assembled.failure_reason}")
                return 1
            print(f"  schema: {assembled.schema['function']['name']}")
            print(f"  samples: {len(assembled.samples)}")

            print("validating...")
            validation = asyncio.run(validate_skill(assembled))
            print(
                f"  validation: passed {validation.passed}/{validation.total} "
                f"(score={validation.score:.2f}, ok={validation.ok})"
            )
            if not validation.ok:
                _mark_failed(conn, mutation.id, reason=f"validation: {validation.failure_reason}")
                return 1

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
        from .memory import list_entities, list_transitions, open_and_init

        cfg = LoopConfig.from_env()
        conn = open_and_init(cfg.state_dir / "chimera.db")
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
    if args.command == "graph":
        from .core import LoopConfig
        from .memory import GraphStore, default_graph_dir, open_and_init

        cfg = LoopConfig.from_env()
        sub_cmd = args.graph_command or "init"
        store = GraphStore(default_graph_dir())
        if sub_cmd == "init":
            store.init_schema()
            print(f"chimera graph: schema ready at {store.path}")
            return 0
        if sub_cmd == "rebuild":
            conn = open_and_init(cfg.state_dir / "chimera.db")
            counts = store.rebuild_from_sqlite(conn)
            print(f"chimera graph rebuild ({store.path}):")
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
