"""`chimera peers ...` command handlers — moved verbatim from chimera.cli (pure move; chimera.cli remains the façade)."""

from __future__ import annotations

from pathlib import Path


def _cmd_peers_cards(args) -> int:
    """`chimera peers cards [--narrative]` — refresh ``mind/peers/`` on demand.

    Deterministic-only by default; ``--narrative`` (or
    ``CHIMERA_PEER_CARD_LLM=1`` in the environment) opts into the
    sonnet-tier theory-of-mind paragraph per card (ADR 0130 / 0131).
    """
    import json as _json
    import os as _os

    from ..a2a.peer_trust_journal import list_decisions
    from ..a2a.peers import list_peer_chimeras
    from ..core import ChimeraLoop, LoopConfig
    from ..engines.peer_cards import (
        build_peer_card,
        build_self_card,
        write_peer_card,
    )

    if args.mind_dir:
        _os.environ["CHIMERA_MIND_DIR"] = args.mind_dir
    if args.state_dir:
        _os.environ["CHIMERA_STATE_DIR"] = args.state_dir

    cfg = LoopConfig.from_env()
    cfg.mind_dir.mkdir(parents=True, exist_ok=True)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)

    # The ChimeraLoop carries the registry + TrustManager wired exactly
    # as the running agent would have them. We don't run a cycle — just
    # use its state to drive consolidation.
    loop = ChimeraLoop(cfg)
    peer_names = list_peer_chimeras(loop._registry)

    cards = [build_self_card(trust_state=loop._trust.state)]
    for name in peer_names:
        cards.append(build_peer_card(
            name,
            decisions=list_decisions(name),
            current_cycle=None,
        ))

    if args.narrative:
        _os.environ["CHIMERA_PEER_CARD_LLM"] = "1"
        try:
            loop._enrich_cards_with_narratives(cards)
        except Exception as exc:  # noqa: BLE001 — keep CLI resilient
            print(f"warning: narrative enrichment failed: {exc}")

    paths = [write_peer_card(cfg.mind_dir, c) for c in cards]
    rels = [str(Path(p).relative_to(cfg.mind_dir.parent)) if cfg.mind_dir.parent in p.parents
            else str(p) for p in paths]

    if args.json:
        print(_json.dumps({
            "written": [str(p) for p in paths],
            "count": len(paths),
            "narrative": bool(args.narrative),
            "peers": peer_names,
        }, indent=2))
    else:
        narr = " (with narratives)" if args.narrative else ""
        print(f"chimera peers cards: wrote {len(paths)} card(s){narr}")
        for r in rels:
            print(f"  {r}")
    return 0


def _cmd_peers_ask(args) -> int:
    """`chimera peers ask <peer> "<question>"` — dialectic Q&A (ADR 0133).

    Gathers grounded context (peer card + trust journal + beliefs if
    available), assembles the dialectic prompt, then calls the local
    sonnet-tier provider for an answer. With ``--prompt-only`` the
    prompt is printed and no LLM call is made (useful for debugging).
    """
    import json as _json
    import os as _os

    from ..a2a.dialectic import (
        build_dialectic_prompt,
        gather_dialectic_context,
        trim_answer,
    )
    from ..core import LoopConfig

    if args.mind_dir:
        _os.environ["CHIMERA_MIND_DIR"] = args.mind_dir

    cfg = LoopConfig.from_env()
    ctx = gather_dialectic_context(args.peer_name, mind_dir=cfg.mind_dir)
    prompt = build_dialectic_prompt(ctx, args.question)

    if args.prompt_only:
        if args.json:
            print(_json.dumps({
                "peer_name": args.peer_name,
                "question": args.question,
                "prompt": prompt,
                "sources_used": ctx.sources_used,
                "is_empty_context": ctx.is_empty(),
            }, indent=2))
        else:
            print(prompt)
        return 0

    # Build a ChimeraLoop only to harvest its ACT provider topology.
    from ..core import ChimeraLoop
    from ..providers import Message
    from ..providers.tiers import Provider as ProviderKind
    from ..providers.tiers import select_rung

    loop = ChimeraLoop(cfg)
    try:
        if loop._act is None or not loop._act.providers:
            answer = (
                f"(no providers configured — cannot answer about "
                f"{args.peer_name}; assembled context only)"
            )
        else:
            try:
                rung = select_rung("sonnet")
            except (ValueError, RuntimeError) as exc:
                print(f"error: tier resolution failed: {exc}")
                return 1
            provider = loop._act.providers.get(rung.config.provider)
            if provider is None:
                answer = "(no provider available for sonnet tier)"
            else:
                model_id = (
                    rung.config.model_id
                    if rung.config.provider is ProviderKind.ANTHROPIC
                    else rung.config.openrouter_model_id
                )

                async def _call() -> str:
                    response = await provider.complete_with_tools(
                        messages=[Message.user(prompt)],
                        model_id=model_id,
                        tools=[],
                        max_tokens=384,
                    )
                    return response.text or ""

                from .._async_loop import run_on_persistent_loop
                answer = trim_answer(run_on_persistent_loop(_call()))
    finally:
        loop.close()

    if args.json:
        print(_json.dumps({
            "peer_name": args.peer_name,
            "question": args.question,
            "answer": answer,
            "sources_used": ctx.sources_used,
            "is_empty_context": ctx.is_empty(),
        }, indent=2))
    else:
        print(answer)
    return 0
