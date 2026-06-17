"""CHIMERA_ACT_TIER routes the base ACT tier (ADR 0183 A.1).

Promoting the `code` tier (qwen3.7-max lead) for CRAWL means the loop's
ACT routes there by default. Two seams make that work end-to-end:
  - ActExecutor.from_env honours CHIMERA_ACT_TIER when no tier is passed;
  - recommended_tier leaves a non-ladder tier (`code`) intact instead of
    rewriting it to sonnet via the haiku→sonnet→opus floors/memory.
"""

from __future__ import annotations

import sqlite3

from chimera.core.escalation import recommended_tier
from chimera.providers.tiers import select_rung


def test_code_tier_leads_with_qwen():
    # The whole point of the promotion: select_rung("code") → qwen3.7-max.
    rung = select_rung("code", requires_tools=True)
    assert rung.config.openrouter_model_id == "qwen/qwen3.7-max"


def test_recommended_tier_passes_code_through_unchanged():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Even a research-flavoured task (which would lift haiku→sonnet) must not
    # rewrite the `code` tier — it's off the cost-escalation axis.
    out = recommended_tier(
        conn, task_text="research and design a new subsystem", default_tier="code",
    )
    assert out == "code"


def test_recommended_tier_still_floors_ladder_tiers():
    # Guard regression: standard ladder tiers keep their floor/memory behaviour.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    out = recommended_tier(conn, task_text="trivial", default_tier="haiku")
    assert out in {"haiku", "sonnet", "opus"}


def test_from_env_honours_act_tier_env(monkeypatch):
    from chimera.core.act import ActExecutor

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("CHIMERA_ACT_TIER", "code")
    ex = ActExecutor.from_env(dispatcher=None, db=sqlite3.connect(":memory:"))
    assert ex is not None
    assert ex._tier == "code"


def test_from_env_explicit_tier_wins_over_env(monkeypatch):
    from chimera.core.act import ActExecutor

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("CHIMERA_ACT_TIER", "code")
    ex = ActExecutor.from_env(
        dispatcher=None, db=sqlite3.connect(":memory:"), tier="sonnet",
    )
    assert ex is not None and ex._tier == "sonnet"


def test_from_env_unknown_tier_falls_back_to_haiku(monkeypatch):
    from chimera.core.act import ActExecutor

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("CHIMERA_ACT_TIER", "bogus")
    ex = ActExecutor.from_env(dispatcher=None, db=sqlite3.connect(":memory:"))
    assert ex is not None and ex._tier == "haiku"


def test_code_tier_gets_token_headroom():
    from chimera.core.act import ActExecutor

    # Output cap (≥ opus) so large diffs aren't truncated; not the context window.
    assert ActExecutor._resolve_max_tokens("code") == 16384


def test_code_tier_output_cap_is_operator_overridable(monkeypatch):
    from chimera.core.act import ActExecutor

    monkeypatch.setenv("CHIMERA_ACT_MAX_TOKENS_CODE", "32768")
    assert ActExecutor._resolve_max_tokens("code") == 32768


def test_default_no_env_stays_haiku(monkeypatch):
    from chimera.core.act import ActExecutor

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("CHIMERA_ACT_TIER", raising=False)
    ex = ActExecutor.from_env(dispatcher=None, db=sqlite3.connect(":memory:"))
    assert ex is not None and ex._tier == "haiku"
