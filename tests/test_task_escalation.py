"""v4.46 — persistent task-escalation memory tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core.escalation import (
    ESCALATING_FINISH_REASONS,
    _signature,
    record_failure,
    recommended_tier,
)
from chimera.memory import open_and_init


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


def test_signature_is_stable_and_token_based():
    sig1 = _signature("Build a world model of the agonistic futures paper")
    sig2 = _signature("Build a world MODEL of the agonistic futures paper.")
    sig3 = _signature("model agonistic futures world build paper")
    # Case-insensitive, punctuation-insensitive, order-insensitive.
    assert sig1 == sig2
    assert sig1 == sig3
    # Empty / stopwords-only → empty signature.
    assert _signature("") == ""
    assert _signature("a b c") == ""


def test_record_failure_only_records_failure_reasons(db):
    # `stop` is success → not recorded.
    assert record_failure(
        db,
        task_text="x y z agonistic",
        tier="haiku",
        finish_reason="stop",
        rounds_used=3,
        cycle=1,
    ) is None
    # `max_rounds` is escalation-worthy → recorded.
    rid = record_failure(
        db,
        task_text="x y z agonistic",
        tier="haiku",
        finish_reason="max_rounds",
        rounds_used=12,
        cycle=2,
    )
    assert rid is not None and rid > 0


def test_record_failure_skips_empty_signature(db):
    # Sub-token task → empty signature → no row.
    assert record_failure(
        db,
        task_text="hi",
        tier="haiku",
        finish_reason="max_rounds",
        rounds_used=1,
        cycle=1,
    ) is None


def test_recommended_tier_default_when_no_history(db):
    assert recommended_tier(
        db, task_text="Build the agonistic futures world model", default_tier="haiku",
    ) == "haiku"


def test_recommended_tier_promotes_after_haiku_failure(db):
    task = "Build the agonistic futures world model artifact"
    record_failure(
        db, task_text=task, tier="haiku", finish_reason="max_rounds",
        rounds_used=26, cycle=14,
    )
    # Same signature → promote one tier.
    assert recommended_tier(db, task_text=task, default_tier="haiku") == "sonnet"


def test_recommended_tier_promotes_after_sonnet_failure_to_opus(db):
    task = "Build the agonistic futures world model artifact"
    record_failure(
        db, task_text=task, tier="haiku", finish_reason="max_rounds",
        rounds_used=26, cycle=14,
    )
    record_failure(
        db, task_text=task, tier="sonnet", finish_reason="artifact_missing",
        rounds_used=20, cycle=15,
    )
    # Worst prior failure was sonnet → promote to opus.
    assert recommended_tier(db, task_text=task, default_tier="haiku") == "opus"


def test_recommended_tier_caps_at_opus(db):
    task = "An impossible task we keep escalating on"
    for tier, cyc in [("haiku", 1), ("sonnet", 2), ("opus", 3)]:
        record_failure(
            db, task_text=task, tier=tier, finish_reason="max_rounds",
            rounds_used=26, cycle=cyc,
        )
    assert recommended_tier(db, task_text=task, default_tier="haiku") == "opus"


def test_recommended_tier_only_promotes_on_overlap(db):
    record_failure(
        db,
        task_text="Build agonistic futures world model artifact",
        tier="haiku",
        finish_reason="max_rounds",
        rounds_used=26,
        cycle=14,
    )
    # Wildly unrelated task → no promotion.
    assert recommended_tier(
        db,
        task_text="Compute the fibonacci sequence quickly",
        default_tier="haiku",
    ) == "haiku"


def test_escalating_finish_reasons_set_covers_real_failures():
    # These are the four failure modes ACT emits today.
    expected = {"max_rounds", "artifact_missing", "degenerate_loop_abort"}
    assert expected.issubset(ESCALATING_FINISH_REASONS)
    # `stop` (success) and `provider_error` (transient) should NOT
    # trigger memorisation — provider_error is upstream, not a tier issue.
    assert "stop" not in ESCALATING_FINISH_REASONS
    assert "provider_error" not in ESCALATING_FINISH_REASONS


# ── ACT integration ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_act_executor_records_failure_on_max_rounds(db):
    """End-to-end: when ACT exits with max_rounds + completed=False, a
    task_escalations row should appear so the next attempt at the same
    signature can promote tier."""
    from chimera.core.act import ActExecutor
    from chimera.providers import ChatResponse, ToolUseBlock
    from chimera.providers.tiers import Provider as ProviderKind
    from chimera.tools import (
        Dispatcher,
        ToolRegistry,
        register_shell_tool,
    )

    # Provider scripted to always emit a tool call → ACT exhausts rounds.
    class _LoopForever:
        name = "fake"

        async def stream(self, *a, **k):
            if False:
                yield  # noqa
            return

        async def complete_with_tools(self, messages, *, model_id, tools,
                                      max_tokens=4096, system=None):
            return ChatResponse(
                text="",
                tool_uses=[ToolUseBlock(id="tu", name="shell",
                                        input={"argv": ["echo", "x"]})],
                stop_reason="tool_use",
                model_id=model_id,
                provider="fake",
            )

    reg = ToolRegistry()
    register_shell_tool(reg)
    executor = ActExecutor(
        dispatcher=Dispatcher(reg),
        providers={
            ProviderKind.OPENROUTER: _LoopForever(),
            ProviderKind.ANTHROPIC: _LoopForever(),
        },
        db=db,
        max_rounds=3,  # quick exhaustion
    )
    result = await executor.execute(
        "Build the unique agonistic ledger model artifact synthesis",
        cycle=10,
    )
    assert not result.completed
    assert result.finish_reason == "max_rounds"

    rows = db.execute(
        "SELECT signature, tier, finish_reason FROM task_escalations"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["finish_reason"] == "max_rounds"
    # Tier recorded matches what executor actually used.
    assert rows[0]["tier"] == executor._tier


@pytest.mark.asyncio
async def test_act_executor_promotes_tier_on_repeat_task(db, monkeypatch):
    """If history contains a haiku failure for THIS task's signature, the
    executor should start at sonnet — verified by inspecting self._tier
    after execute()."""
    from chimera.core.act import ActExecutor
    from chimera.core.escalation import record_failure
    from chimera.providers import ChatResponse
    from chimera.providers.tiers import Provider as ProviderKind
    from chimera.tools import (
        Dispatcher,
        ToolRegistry,
        register_shell_tool,
    )

    task = "Build the unique synthesis benchmark report artifact"
    # Pre-seed a failure at haiku.
    record_failure(
        db, task_text=task, tier="haiku", finish_reason="max_rounds",
        rounds_used=12, cycle=1,
    )

    class _Quick:
        name = "fake"

        async def stream(self, *a, **k):
            if False:
                yield
            return

        async def complete_with_tools(self, messages, **kw):
            return ChatResponse(
                text="done.", tool_uses=[], stop_reason="stop",
                model_id="m", provider="fake",
            )

    reg = ToolRegistry()
    register_shell_tool(reg)
    executor = ActExecutor(
        dispatcher=Dispatcher(reg),
        providers={
            ProviderKind.OPENROUTER: _Quick(),
            ProviderKind.ANTHROPIC: _Quick(),
        },
        db=db,
        tier="haiku",
    )
    await executor.execute(task, cycle=2)
    # Tier was promoted before the call ran.
    assert executor._tier == "sonnet"


# ── v4.48: operator readers ──────────────────────────────────


def test_list_escalations_returns_recent_first(db):
    from chimera.core.escalation import list_escalations
    for cyc in (1, 2, 3):
        record_failure(
            db, task_text=f"task {cyc} alpha beta gamma",
            tier="haiku", finish_reason="max_rounds",
            rounds_used=12, cycle=cyc,
        )
    rows = list_escalations(db, limit=10)
    assert [r.cycle for r in rows] == [3, 2, 1]


def test_list_escalations_grep_filters(db):
    from chimera.core.escalation import list_escalations
    record_failure(
        db, task_text="build agonistic futures world model",
        tier="haiku", finish_reason="max_rounds",
        rounds_used=12, cycle=1,
    )
    record_failure(
        db, task_text="compute fibonacci sequence quickly",
        tier="haiku", finish_reason="max_rounds",
        rounds_used=12, cycle=2,
    )
    agonistic = list_escalations(db, signature_substring="agonistic")
    assert len(agonistic) == 1
    assert "agonistic" in agonistic[0].task_text


def test_escalation_summary_groups_by_signature_and_tier(db):
    from chimera.core.escalation import escalation_summary
    task = "build the synthesis report artifact properly"
    record_failure(db, task_text=task, tier="haiku", finish_reason="max_rounds",
                   rounds_used=12, cycle=1)
    record_failure(db, task_text=task, tier="haiku", finish_reason="max_rounds",
                   rounds_used=12, cycle=2)
    record_failure(db, task_text=task, tier="sonnet", finish_reason="artifact_missing",
                   rounds_used=18, cycle=3)
    summary = escalation_summary(db)
    assert len(summary) == 1
    sig = next(iter(summary))
    assert summary[sig]["haiku"] == 2
    assert summary[sig]["sonnet"] == 1


def test_clear_escalations_with_grep(db):
    from chimera.core.escalation import clear_escalations, list_escalations
    record_failure(db, task_text="agonistic futures world model artifact",
                   tier="haiku", finish_reason="max_rounds",
                   rounds_used=12, cycle=1)
    record_failure(db, task_text="fibonacci compute task",
                   tier="haiku", finish_reason="max_rounds",
                   rounds_used=12, cycle=2)
    n = clear_escalations(db, signature_substring="agonistic")
    assert n == 1
    remaining = list_escalations(db)
    assert len(remaining) == 1
    assert "fibonacci" in remaining[0].task_text


def test_clear_escalations_all(db):
    from chimera.core.escalation import clear_escalations, list_escalations
    for i in range(3):
        record_failure(db, task_text=f"task {i} alpha beta gamma",
                       tier="haiku", finish_reason="max_rounds",
                       rounds_used=12, cycle=i)
    n = clear_escalations(db)
    assert n == 3
    assert list_escalations(db) == []

# ── v5.0: prune_escalations (unbounded-table remediation) ────


def test_prune_escalations_empty_table_returns_zero(db):
    """Fresh db, no rows → returns 0."""
    from chimera.core.escalation import prune_escalations
    assert prune_escalations(db, max_age_days=30) == 0


def test_prune_escalations_mixed_table_deletes_only_old(db):
    """Seed 3 fresh + 2 aged rows; call with max_age_days=7; returns 2; only the 3 fresh rows remain."""
    from chimera.core.escalation import prune_escalations
    # 3 fresh rows — use default created_at (now)
    for i in range(3):
        record_failure(db, task_text=f"fresh task {i} alpha beta gamma",
                       tier="haiku", finish_reason="max_rounds",
                       rounds_used=5, cycle=i)

    # 2 aged rows — inject past timestamps
    db.execute(
        "INSERT INTO task_escalations (signature, task_text, tier, finish_reason, rounds_used, cycle, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("old-sig-1", "old task 1", "haiku", "max_rounds", 5, 10, "2020-01-01T00:00:00"),
    )
    db.execute(
        "INSERT INTO task_escalations (signature, task_text, tier, finish_reason, rounds_used, cycle, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("old-sig-2", "old task 2", "sonnet", "artifact_missing", 8, 11, "2020-06-15T12:00:00"),
    )
    db.commit()

    n = prune_escalations(db, max_age_days=7)
    assert n == 2, f"expected 2 deletions, got {n}"

    remaining = db.execute("SELECT count(*) FROM task_escalations").fetchone()[0]
    assert remaining == 3


def test_prune_escalations_zero_or_negative_is_noop(db):
    """max_age_days=0 and max_age_days=-1 → returns 0, no rows deleted."""
    from chimera.core.escalation import prune_escalations
    record_failure(db, task_text="test task alpha beta gamma",
                   tier="haiku", finish_reason="max_rounds",
                   rounds_used=5, cycle=1)

    assert prune_escalations(db, max_age_days=0) == 0
    rows = db.execute("SELECT count(*) FROM task_escalations").fetchone()[0]
    assert rows == 1

    assert prune_escalations(db, max_age_days=-1) == 0
    rows = db.execute("SELECT count(*) FROM task_escalations").fetchone()[0]
    assert rows == 1


def test_prune_escalations_missing_table_returns_zero(db):
    """Open a connection against a db without the task_escalations table → returns 0, does NOT raise."""
    from chimera.core.escalation import prune_escalations
    db.execute("DROP TABLE IF EXISTS task_escalations")
    db.commit()
    # Should not raise.
    n = prune_escalations(db, max_age_days=30)
    assert n == 0


def test_prune_escalations_uses_parameterized_sql():
    """Charter #8: verify the function source uses parameterized SQL, not interpolation."""
    import inspect
    from chimera.core.escalation import prune_escalations

    src = inspect.getsource(prune_escalations)
    # The DELETE SQL must use a ? placeholder.
    assert "?" in src, f"prune_escalations source missing ? placeholder:\n{src}"
    # Must NOT use f-string or .format() interpolation.
    assert "f'" not in src, f"prune_escalations source uses f-string:\n{src}"
    assert 'f"' not in src, f"prune_escalations source uses f-string:\n{src}"
    assert ".format(" not in src, f"prune_escalations source uses .format():\n{src}"
    # Must compute cutoff in Python (using datetime), not in SQL.
    assert "timedelta" in src or "datetime" in src, \
        f"cutoff not computed in Python:\n{src}"
    # The SQL DELETE string must appear exactly as a parameterized statement.
    assert "DELETE FROM task_escalations WHERE created_at < ?" in src, \
        f"expected parameterized DELETE not found in source:\n{src}"
