"""v4.116 (ADR 0116): charter file-count enforcement — end-to-end.

Exercises all 5 layers in sequence within a single test function:
  1. extract_charter_file_enumeration — parse charter paths from task text
  2. check_charter_file_count — structural git-diff vs enumeration
  3. ActResult + finish_reason wiring — detector violations surface on result
  4. Remediation hint — _charter_file_count_hint formats violations
  5. ESCALATING_FINISH_REASONS membership — reason is registered for escalation
  6. Trust-delta — apply_finish_reason demotes one tier (guards PR #39 sign-flip)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chimera.core.escalation import ESCALATING_FINISH_REASONS
from chimera.core.remediation import _charter_file_count_hint
from chimera.trust.manager import TrustManager, TrustTier
from chimera.core.witness import (
    check_charter_file_count,
    extract_charter_file_enumeration,
)


def _git(*args: str, cwd: Path) -> str:
    res = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout


def _init_repo(root: Path) -> None:
    _git("init", "-q", "-b", "main", cwd=root)
    _git("config", "user.email", "test@example.com", cwd=root)
    _git("config", "user.name", "Test", cwd=root)
    (root / "README.md").write_text("base\n")
    _git("add", "README.md", cwd=root)
    _git("commit", "-q", "-m", "initial", cwd=root)
    _git("checkout", "-q", "-b", "feat/x", cwd=root)


def _agent_commit(root: Path, paths: list[str], body: str = "work") -> None:
    for p in paths:
        full = root / p
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text("x\n")
        _git("add", p, cwd=root)
    _git("commit", "-q", "-m", f"[agent] {body}", cwd=root)


# ── Charter text used throughout the e2e test ────────────────

_CHARTER = (
    "CHARTER for phase 2:\n"
    "  SCOPE: ONE new function in `chimera/core/act.py`.\n"
    "  ONE new test file, `tests/test_ruff_claim_invalid.py`.\n"
    "  NO third file.\n"
)


@pytest.mark.asyncio
async def test_charter_file_count_e2e_all_layers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise all 5 layers of the charter file-count enforcement chain.

    Layer 1 — extract before any commit: enumeration parses paths.
    Layer 2 — after committing an unsanctioned file, detection fires.
    Layer 3 — ActExecutor wiring surfaces violations + finish_reason flip.
    Layer 4 — remediation hint names offending paths.
    Layer 5 — finish_reason is registered in ESCALATING_FINISH_REASONS.
    """
    # ── Layer 1: extract_charter_file_enumeration ──────────────
    enumerated = extract_charter_file_enumeration(_CHARTER)
    assert sorted(enumerated) == [
        "chimera/core/act.py",
        "tests/test_ruff_claim_invalid.py",
    ], f"Layer 1: expected 2 paths, got {enumerated}"

    # ── Layer 2: check_charter_file_count ──────────────────────
    _init_repo(tmp_path)
    _agent_commit(
        tmp_path,
        [
            "chimera/core/act.py",
            "tests/test_ruff_claim_invalid.py",
            "mind/research/unsanctioned-design.md",
        ],
        body="phase 2 work with extra file",
    )
    violations = check_charter_file_count(_CHARTER, tmp_path)
    assert violations == ["mind/research/unsanctioned-design.md"], (
        f"Layer 2: expected 1 violation, got {violations}"
    )

    # ── Layer 3: ActResult wiring + finish_reason ──────────────
    from chimera.core import act as _act
    from chimera.memory import open_and_init
    from chimera.providers import ChatResponse, Message
    from chimera.providers.base import Provider
    from chimera.providers.tiers import Provider as ProviderKind
    from chimera.tools import Dispatcher, ToolRegistry, register_shell_tool

    # Stub the git-reading detectors so we test ONLY the charter_file_count path.
    monkeypatch.setattr(_act, "check_charter_file_count", lambda *a, **kw: violations)
    monkeypatch.setattr(_act, "check_commit_message_diff_drift", lambda *a, **kw: [])
    monkeypatch.setattr(_act, "check_provenance_claim_valid", lambda *a, **kw: [])

    class _StopProvider(Provider):
        name = "fake"
        async def stream(self, messages, *, model_id, max_tokens=4096, system=None):
            if False:
                yield None  # pragma: no cover
        async def complete_with_tools(
            self, messages: list[Message], *, model_id: str,
            tools, max_tokens: int = 4096, system: str | None = None,
        ) -> ChatResponse:
            return ChatResponse(
                text="done.", tool_uses=[], stop_reason="stop",
                model_id=model_id, provider="fake",
            )

    reg = ToolRegistry()
    register_shell_tool(reg)
    dispatcher = Dispatcher(reg)
    db = open_and_init(tmp_path / "chimera.db")
    try:
        fake = _StopProvider()
        from chimera.core.act import ActExecutor
        executor = ActExecutor(
            dispatcher=dispatcher,
            providers={
                ProviderKind.OPENROUTER: fake,
                ProviderKind.ANTHROPIC: fake,
            },
            db=db,
        )
        result = await executor.execute("noop task", cycle=1)
    finally:
        db.close()

    assert result.charter_file_count_violations == violations, (
        f"Layer 3: expected violations {violations}, "
        f"got {result.charter_file_count_violations}"
    )
    assert result.finish_reason == "charter_file_count", (
        f"Layer 3: expected finish_reason='charter_file_count', "
        f"got {result.finish_reason!r}"
    )
    assert result.completed is False

    # ── Layer 4: Remediation hint ─────────────────────────────
    hint = _charter_file_count_hint(
        _CHARTER,
        charter_file_count_violations=violations,
    )
    assert "mind/research/unsanctioned-design.md" in hint, (
        f"Layer 4: hint should name the violating path, got:\n{hint}"
    )
    assert "charter" in hint, "Layer 4: hint should mention 'charter'"
    assert "git reset" in hint or "budget" in hint, (
        "Layer 4: hint should suggest corrective action"
    )

    # ── Layer 5: ESCALATING_FINISH_REASONS membership ─────────
    assert "charter_file_count" in ESCALATING_FINISH_REASONS, (
        "Layer 5: 'charter_file_count' must be in ESCALATING_FINISH_REASONS"
    )

    # ── Layer 6: Trust-delta (guards PR #39 sign-flip regression) ──
    tm = TrustManager(tmp_path / "trust_state.json")
    tm.promote(reason="bootstrap")
    tm.promote(reason="bootstrap")
    assert tm.tier is TrustTier.T2

    demoted = tm.apply_finish_reason("charter_file_count")

    assert demoted == 1, f"Layer 6: expected +1 demote, got {demoted}"
    assert tm.tier is TrustTier.T1, (
        f"Layer 6: expected T1 after demote, got {tm.tier}"
    )
    last = tm.state.history[-1]
    assert last.kind == "demote", f"Layer 6: expected demote, got {last.kind}"
    assert "charter_file_count" in last.reason, (
        f"Layer 6: history entry should cite charter_file_count, got {last.reason!r}"
    )
