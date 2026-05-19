"""Chimera CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import sys

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
        choices=("drift", "research"),
        help="Which scenario to run.",
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
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
