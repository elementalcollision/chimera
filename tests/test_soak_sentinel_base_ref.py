"""A1: soak_phase2_deliverable_landed must measure the deliverable diff against
the build BASE, not a hardcoded `main`.

The generic charter-build soak builds from a CHARTER_BASE branch that already
carries the materialized test + design. Comparing against `main` pulls those
un-allowlisted files into the diff, so a clean [agent] commit falls through to
no_forward_progress. These tests pin the base-ref parameter (default main;
explicit base for the charter case).
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

_LIB = Path(__file__).resolve().parents[1] / "scripts" / "soak_lib.sh"


def _bash(script: str, cwd: Path) -> subprocess.CompletedProcess:
    full = f'source "{_LIB}"\n{script}'
    return subprocess.run(["bash", "-c", full], cwd=str(cwd), capture_output=True, text=True)


def _setup_charter_repo(root: Path) -> None:
    """A repo mirroring the charter build: a base branch carrying the
    materialized test, then an [agent] build commit of the target on top."""
    def git(*a):
        subprocess.run(["git", *a], cwd=str(root), check=True, capture_output=True, text=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "t@t.t")
    git("config", "user.name", "t")
    (root / "seed.txt").write_text("seed\n")
    git("add", "seed.txt"); git("commit", "-qm", "seed")
    # The build base branch carries the materialized acceptance test.
    git("checkout", "-q", "-b", "build-base")
    (root / "tests").mkdir()
    (root / "tests" / "test_target.py").write_text("def test(): assert True\n")
    git("add", "tests/test_target.py"); git("commit", "-qm", "charter: materialized test")
    # The agent's build branch: build the target + [agent] commit.
    git("checkout", "-q", "-b", "soak-work")
    (root / "chimera").mkdir()
    (root / "chimera" / "target.py").write_text("x = 1\n")
    git("add", "chimera/target.py"); git("commit", "-qm", "[agent] build chimera/target.py")


def test_sentinel_fires_with_correct_base(tmp_path):
    _setup_charter_repo(tmp_path)
    # base=build-base → diff carries ONLY chimera/target.py (allowlisted) → fire.
    p = _bash(
        'soak_phase2_deliverable_landed "." "chimera/target.py" "true" "build-base"; '
        'echo "RC=$?"',
        tmp_path,
    )
    assert "RC=0" in p.stdout, p.stdout + p.stderr


def test_sentinel_misses_with_wrong_base_main(tmp_path):
    _setup_charter_repo(tmp_path)
    # base=main (the bug) → diff also carries tests/test_target.py (NOT
    # allowlisted) → sentinel refuses (RC=1) even though the [agent] commit is clean.
    p = _bash(
        'soak_phase2_deliverable_landed "." "chimera/target.py" "true" "main"; '
        'echo "RC=$?"',
        tmp_path,
    )
    assert "RC=1" in p.stdout, p.stdout + p.stderr


def test_default_base_is_main(tmp_path):
    # Backward-compat: omitting the 4th arg behaves as base=main (v46 soaks).
    _setup_charter_repo(tmp_path)
    p_default = _bash(
        'soak_phase2_deliverable_landed "." "chimera/target.py" "true"; echo "RC=$?"',
        tmp_path,
    )
    p_main = _bash(
        'soak_phase2_deliverable_landed "." "chimera/target.py" "true" "main"; echo "RC=$?"',
        tmp_path,
    )
    assert p_default.stdout.strip().endswith(p_main.stdout.strip())


def test_failing_test_blocks_sentinel(tmp_path):
    _setup_charter_repo(tmp_path)
    p = _bash(
        'soak_phase2_deliverable_landed "." "chimera/target.py" "false" "build-base"; '
        'echo "RC=$?"',
        tmp_path,
    )
    assert "RC=1" in p.stdout, p.stdout + p.stderr
