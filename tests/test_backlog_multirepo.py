"""Multi-repo spec fields on BacklogSpec (ADR 0186 B.1).

`repo` + `verify_cmd` let a spec target a FOREIGN repo with its own gate. A
spec without `repo` is byte-identical to pre-0186 self-repo behaviour.
"""

from __future__ import annotations

from pathlib import Path

from chimera.core.backlog import parse_spec

_FOREIGN = """\
---
goal: "Fix the thing in the daemon"
files: src/daemon.py tests/test_daemon.py
repo: elementalcollision/claude-daemon
verify_cmd: "pytest tests/test_daemon.py"
base: main
---
body
"""

_FOREIGN_NO_CMD = """\
---
goal: "Fix the thing"
files: src/x.py
repo: elementalcollision/claude-daemon
---
body
"""

_SELF = """\
---
goal: "Add a helper to chimera.core.health"
files: chimera/core/health.py tests/test_health_x.py
test: tests/test_health_x.py
---
body
"""


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "spec.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_foreign_repo_spec_parses(tmp_path):
    s = parse_spec(_write(tmp_path, _FOREIGN))
    assert s.valid
    assert s.repo == "elementalcollision/claude-daemon"
    assert s.verify_cmd == "pytest tests/test_daemon.py"


def test_foreign_repo_requires_verify_cmd(tmp_path):
    s = parse_spec(_write(tmp_path, _FOREIGN_NO_CMD))
    assert not s.valid
    assert any("verify_cmd" in e for e in s.errors)


def test_foreign_task_env_carries_repo_and_cmd(tmp_path):
    env = parse_spec(_write(tmp_path, _FOREIGN)).task_env()
    assert env["TASK_REPO"] == "elementalcollision/claude-daemon"
    assert env["TASK_VERIFY_CMD"] == "pytest tests/test_daemon.py"


def test_foreign_task_env_opts_into_foreign_pr(tmp_path):
    # Daily-loop activation: a foreign spec must opt into the foreign-PR path so
    # the daily run OPENS the draft PR (not just leaves the branch in the clone).
    env = parse_spec(_write(tmp_path, _FOREIGN)).task_env()
    assert env["CHIMERA_FOREIGN_PR"] == "1"


def test_self_task_env_never_opts_into_foreign_pr(tmp_path):
    env = parse_spec(_write(tmp_path, _SELF)).task_env()
    assert "CHIMERA_FOREIGN_PR" not in env


def test_self_repo_spec_unchanged(tmp_path):
    """No repo/verify_cmd → fields None and task_env byte-identical to pre-0186."""
    s = parse_spec(_write(tmp_path, _SELF))
    assert s.valid and s.repo is None and s.verify_cmd is None
    env = s.task_env()
    assert "TASK_REPO" not in env and "TASK_VERIFY_CMD" not in env
    assert set(env) == {"TASK_GOAL", "TASK_FILES", "TASK_BASE", "TASK_TEST"}
