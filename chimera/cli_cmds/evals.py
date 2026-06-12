"""`chimera evals ...` command handlers — moved verbatim from chimera.cli (pure move; chimera.cli remains the façade)."""

from __future__ import annotations

from pathlib import Path


def _cmd_evals_longmemeval(args) -> int:
    """`chimera evals longmemeval ...` — Phase 4 #8 adapter sweep (ADR 0135)."""
    import os as _os

    from ..core import LoopConfig
    from ..evals.longmemeval import (
        LongMemEvalAdapter,
        LongMemEvalItem,
        default_results_path,
        load_items,
        run_batch,
        write_results,
    )

    if args.mind_dir:
        _os.environ["CHIMERA_MIND_DIR"] = args.mind_dir

    cfg = LoopConfig.from_env()
    cfg.mind_dir.mkdir(parents=True, exist_ok=True)

    if not args.items and not args.smoke:
        print(
            "error: pass --items PATH or --smoke. The latter runs a built-in "
            "3-item synthetic fixture for adapter verification."
        )
        return 2

    if args.smoke:
        items = [
            LongMemEvalItem(
                item_id="smoke-0",
                question="What pet does the user have?",
                history=[[
                    {"role": "user", "content": "I just adopted a tabby cat."},
                    {"role": "assistant", "content": "Congratulations!"},
                ]],
                expected_answer="a tabby cat",
                category="single-session-user",
            ),
            LongMemEvalItem(
                item_id="smoke-1",
                question="Where does the user work?",
                history=[
                    [{"role": "user", "content": "I started at Acme today."}],
                    [{"role": "user", "content": "Acme is treating me well."}],
                ],
                expected_answer="Acme",
                category="multi-session",
            ),
            LongMemEvalItem(
                item_id="smoke-2",
                question="What is the user's favorite cuisine?",
                history=[[{"role": "user", "content": "Today is Tuesday."}]],
                expected_answer="",
                category="abstention",
            ),
        ]
    else:
        items = load_items(Path(args.items))
        if not items:
            print(f"error: no items loaded from {args.items}")
            return 1

    embed_fn = None
    if args.hybrid_retrieval:
        from ..evals.hybrid_retrieval import build_default_embed_fn
        embed_fn = build_default_embed_fn()
        if embed_fn is None:
            print(
                "warning: --hybrid-retrieval enabled but OPENAI_API_KEY unset; "
                "falling back to BM25-only retrieval (ADR 0142 design note "
                "§Failure-mode register)."
            )
    adapter = LongMemEvalAdapter(
        mind_dir=cfg.mind_dir,
        hybrid_retrieval=args.hybrid_retrieval,
        retrieval_top_k=args.retrieval_top_k,
        embed_fn=embed_fn,
    )
    answer_fn = (
        _build_openrouter_answer_fn(
            args.answer_model,
            max_tokens=args.answer_max_tokens,
            temperature=args.answer_temperature,
        )
        if args.answer else None
    )
    results = run_batch(
        adapter, items,
        limit=args.n, subset=args.subset,
        answer_fn=answer_fn,
        per_category_limit=args.n_per_category,
    )

    out_path = Path(args.out) if args.out else default_results_path(cfg.mind_dir)
    write_results(results, out_path)

    by_category: dict[str, int] = {}
    errors = 0
    for r in results:
        by_category[r.category or "(none)"] = by_category.get(r.category or "(none)", 0) + 1
        if r.error:
            errors += 1
    label = f" (--answer via {args.answer_model})" if args.answer else ""
    print(f"chimera evals longmemeval{label}: {len(results)} item(s) → {out_path}")
    for cat, n in sorted(by_category.items()):
        print(f"  {cat}: {n}")
    if errors:
        print(f"  errors: {errors}")
    return 0


def _cmd_evals_locomo(args) -> int:
    """`chimera evals locomo ...` — second eval surface (ADR 0144)."""
    import os as _os

    from ..core import LoopConfig
    from ..evals.locomo import (
        LoCoMoAdapter,
        default_results_path,
        items_from_sample,
        load_items,
        run_batch,
        write_results,
    )

    if args.mind_dir:
        _os.environ["CHIMERA_MIND_DIR"] = args.mind_dir

    cfg = LoopConfig.from_env()
    cfg.mind_dir.mkdir(parents=True, exist_ok=True)

    if not args.items and not args.smoke:
        print(
            "error: pass --items PATH (upstream data/locomo10.json) or --smoke. "
            "The latter runs a built-in synthetic fixture for adapter verification."
        )
        return 2

    if args.smoke:
        smoke_sample = {
            "sample_id": "smoke-conv",
            "conversation": {
                "speaker_a": "Alice",
                "speaker_b": "Bob",
                "session_1_date_time": "1 Jan 2026",
                "session_1": [
                    {"speaker": "Alice", "dia_id": "D1:1",
                     "text": "I adopted a tabby cat last week."},
                    {"speaker": "Bob", "dia_id": "D1:2",
                     "text": "Congrats! What's the name?"},
                    {"speaker": "Alice", "dia_id": "D1:3",
                     "text": "We named her Pixel."},
                ],
                "session_2_date_time": "8 Jan 2026",
                "session_2": [
                    {"speaker": "Alice", "dia_id": "D2:1",
                     "text": "Pixel is settling in well."},
                ],
            },
            "qa": [
                {"question": "What pet did Alice adopt?",
                 "answer": "a tabby cat", "evidence": ["D1:1"], "category": 1},
                {"question": "What is the cat's name?",
                 "answer": "Pixel", "evidence": ["D1:3"], "category": 1},
                {"question": "What is Bob's favorite cuisine?",
                 "answer": "(unanswerable)", "evidence": [], "category": 5},
            ],
        }
        items = items_from_sample(smoke_sample)
    else:
        items = load_items(Path(args.items))
        if not items:
            print(f"error: no items loaded from {args.items}")
            return 1

    embed_fn = None
    if args.hybrid_retrieval:
        from ..evals.hybrid_retrieval import build_default_embed_fn
        embed_fn = build_default_embed_fn()
        if embed_fn is None:
            print(
                "warning: --hybrid-retrieval enabled but OPENAI_API_KEY unset; "
                "falling back to BM25-only retrieval (ADR 0142)."
            )
    adapter = LoCoMoAdapter(
        mind_dir=cfg.mind_dir,
        hybrid_retrieval=args.hybrid_retrieval,
        retrieval_top_k=args.retrieval_top_k,
        embed_fn=embed_fn,
    )
    answer_fn = (
        _build_openrouter_answer_fn(
            args.answer_model,
            max_tokens=args.answer_max_tokens,
            temperature=args.answer_temperature,
        )
        if args.answer else None
    )
    results = run_batch(
        adapter, items,
        limit=args.n, subset=args.subset,
        sample_id=args.sample_id,
        answer_fn=answer_fn,
        per_category_limit=args.n_per_category,
    )

    out_path = Path(args.out) if args.out else default_results_path(cfg.mind_dir)
    write_results(results, out_path)

    by_category: dict[str, int] = {}
    errors = 0
    for r in results:
        by_category[r.category or "(none)"] = by_category.get(r.category or "(none)", 0) + 1
        if r.error:
            errors += 1
    label = f" (--answer via {args.answer_model})" if args.answer else ""
    print(f"chimera evals locomo{label}: {len(results)} item(s) → {out_path}")
    for cat, n in sorted(by_category.items()):
        print(f"  {cat}: {n}")
    if errors:
        print(f"  errors: {errors}")
    return 0


def _build_openrouter_answer_fn(
    model_id: str,
    *,
    max_tokens: int = 2048,
    temperature: float | None = None,
):
    """Construct an ``AnswerFn`` that routes through OpenRouter.

    Uses ``chimera.providers.OpenRouterProvider`` with the operator-
    supplied ``model_id`` (default ``openai/gpt-mini-latest`` per the
    CLI flag). Requires ``OPENROUTER_API_KEY``; raises a clear error
    when absent.

    ``max_tokens`` defaults to 2048 (raised from 512) to recover the
    6/30 reasoning-token-exhaustion empties observed in the smoke
    baseline (PR #56 §"6 empty hypotheses"). Callers can override via
    ``--answer-max-tokens N`` on the CLI.

    Imported lazily so the test path that passes a deterministic stub
    never hits provider imports.

    Loop hygiene: per-call ``asyncio.run`` deadlocks after N successive
    invocations during loop-teardown on Python 3.14 — the
    ``shutdown_default_executor`` step blocks on a worker that holds
    state from the httpx AsyncClient's anyio backend. We route every
    call through one persistent loop on a daemon thread instead, so
    teardown only happens at process exit. See
    ``mind/research/f2-blocked-by-hybrid-retrieval-deadlock-2026-05-27.md``.
    """
    import asyncio as _asyncio
    import os as _os

    from ..providers import Message, OpenRouterProvider
    from .._async_loop import run_on_persistent_loop

    if not _os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError(
            "--answer needs OPENROUTER_API_KEY; not set. "
            "Export it and retry."
        )
    provider = OpenRouterProvider()

    # Per-call wall-clock bound. httpx already enforces its own timeout
    # but is not the only thing that can hang the coroutine — the F2
    # full-corpus sweep occasionally wedges on a future that the loop
    # never schedules (canonical idle 3-thread stack). ``wait_for``
    # raises ``asyncio.TimeoutError`` after the bound, cancels the
    # underlying coroutine, and unblocks the persistent loop so the
    # sweep continues with one missed item rather than a 3 h hang. The
    # bound is chosen at ~3× retry_call's worst case (3 attempts × 60 s
    # timeout × 1.5 s ceiling backoff) plus headroom.
    _CALL_TIMEOUT_S = float(_os.environ.get("CHIMERA_ANSWER_TIMEOUT_S", "240"))

    async def _call(prompt: str) -> str:
        kwargs: dict = {
            "messages": [Message.user(prompt)],
            "model_id": model_id,
            "tools": [],
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = await _asyncio.wait_for(
            provider.complete_with_tools(**kwargs),
            timeout=_CALL_TIMEOUT_S,
        )
        return (response.text or "").strip()

    def answer_fn(prompt: str) -> str:
        return run_on_persistent_loop(_call(prompt))

    return answer_fn


def _cmd_evals_summarize(args) -> int:
    """`chimera evals summarize` — grader-agnostic accuracy gate (ADR 0181).

    The "gate" in the gated-nightly: aggregate a graded JSONL into
    per-category accuracy (reusing the existing summarize_results /
    format_summary_table), print it, and fail (exit 1) on a threshold
    miss or a regression vs a stored baseline. Provider-agnostic and
    key-free — grading itself is the operator's upstream step (ADR 0135).
    """
    import json as _json

    from ..evals.longmemeval import (
        format_summary_table,
        summarize_results,
    )

    graded = Path(args.graded)
    if not graded.exists():
        print(f"error: graded JSONL not found: {graded}")
        return 2

    summary = summarize_results(
        graded, correctness_field=args.correctness_field
    )
    if not summary or summary.get("_overall", {}).get("total", 0) == 0:
        print(f"error: no gradable rows in {graded}")
        return 2

    overall = float(summary.get("_overall", {}).get("accuracy", 0.0))

    if args.json:
        print(_json.dumps(summary, indent=2, sort_keys=True))
    else:
        print(format_summary_table(summary))

    failed = False

    if args.min_accuracy is not None and overall < args.min_accuracy:
        print(
            f"GATE FAIL: overall accuracy {overall:.4f} < "
            f"--min-accuracy {args.min_accuracy:.4f}"
        )
        failed = True

    if args.baseline:
        base_path = Path(args.baseline)
        if not base_path.exists():
            print(f"error: --baseline not found: {base_path}")
            return 2
        try:
            base = _json.loads(base_path.read_text(encoding="utf-8"))
            base_overall = float(base.get("_overall", {}).get("accuracy", 0.0))
        except (ValueError, OSError, AttributeError) as exc:
            print(f"error: could not read baseline accuracy: {exc}")
            return 2
        drop = base_overall - overall
        if drop > args.tolerance:
            print(
                f"GATE FAIL: overall accuracy {overall:.4f} regressed "
                f"{drop:.4f} below baseline {base_overall:.4f} "
                f"(tolerance {args.tolerance:.4f})"
            )
            failed = True
        else:
            print(
                f"baseline OK: {overall:.4f} vs {base_overall:.4f} "
                f"(Δ {(-drop):+.4f}, tolerance {args.tolerance:.4f})"
            )

    return 1 if failed else 0
