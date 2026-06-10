"""H3 (v42): fix_without_test must not fire when a charter-provided test
passes.

Build-soak charters give the test as READ-ONLY input — the agent can't
author a tests/ file (the scope check + H1 refuse it). So
`fix_without_test` structurally false-positives on every build cycle even
though a charter-owned test exists and PASSES (v42 attempts #1/#2 churned
to budget on this). A recorded passing gated test-run now satisfies the
"has a test" requirement.
"""

from __future__ import annotations

from chimera.core.act import check_fix_without_test, check_phase_fix_without_test
from chimera.core.soak_ledger import record_test_run

_RUN = "CHIMERA_SOAK_RUN_ID"


def test_outside_soak_unchanged(monkeypatch):
    # No run id → detector unchanged: chimera/ source written, no tests/ → fires.
    monkeypatch.delenv(_RUN, raising=False)
    assert check_fix_without_test([], ["chimera/boxtable.py"]) == ["chimera/boxtable.py"]
    assert check_phase_fix_without_test(["chimera/boxtable.py"]) == ["chimera/boxtable.py"]


def test_soak_without_passing_run_still_fires(tmp_path, monkeypatch):
    monkeypatch.setenv(_RUN, "h3a")
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    record_test_run(argv=["uv", "run", "pytest"], exit_code=1, duration_ms=5.0, stdout="1 failed")
    # ledger shows NO passing run → still fires (the fix isn't proven tested).
    assert check_fix_without_test([], ["chimera/boxtable.py"]) == ["chimera/boxtable.py"]
    assert check_phase_fix_without_test(["chimera/boxtable.py"]) == ["chimera/boxtable.py"]


def test_soak_with_passing_run_suppresses(tmp_path, monkeypatch):
    monkeypatch.setenv(_RUN, "h3b")
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    record_test_run(argv=["uv", "run", "pytest"], exit_code=0, duration_ms=5.0, stdout="6 passed")
    # charter test passed → fix_without_test must NOT fire.
    assert check_fix_without_test([], ["chimera/boxtable.py", "chimera/boxtable_cells.py"]) == []
    assert check_phase_fix_without_test(["chimera/boxtable.py", "chimera/boxtable_cells.py"]) == []


def test_agent_authored_test_still_satisfies(monkeypatch):
    # The pre-existing path: agent wrote a tests/ file → satisfied regardless of soak.
    monkeypatch.delenv(_RUN, raising=False)
    assert check_fix_without_test([], ["chimera/x.py", "tests/test_x.py"]) == []
