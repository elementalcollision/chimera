"""B1 W3 regression: phase budget + cycle telemetry helpers are SHARED.

`total_spend_in_db`, `last_cycle_in_db`, and `fp_ge` were defined only inside
charter_build_soak.sh. real_task_soak.sh called them but never got a definition,
so in that runner they were "command not found": cycle=/spend= logged blank AND
the phase dollar-cap (fp_ge) silently never fired. They now live in
_soak_common.sh; these tests pin that every runner which sources it gets working
implementations.
"""

from __future__ import annotations

import sqlite3
import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOAK_COMMON = REPO_ROOT / "scripts" / "_soak_common.sh"
REAL_TASK = REPO_ROOT / "scripts" / "real_task_soak.sh"


def _bash(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S602
        ["bash", "-c", script], capture_output=True, text=True, timeout=30,
    )


def _make_db(path: Path, rows: list[tuple[int, float, str]]) -> None:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE api_calls (cycle INTEGER, cost_usd REAL, created_at TEXT)"
    )
    con.executemany("INSERT INTO api_calls VALUES (?, ?, ?)", rows)
    con.commit()
    con.close()


def test_helpers_are_defined_after_sourcing_common():
    out = _bash(
        f"source {SOAK_COMMON}; "
        "type total_spend_in_db last_cycle_in_db fp_ge >/dev/null "
        "&& echo DEFINED"
    )
    assert "DEFINED" in out.stdout, out.stderr


def test_last_cycle_in_db_returns_max_cycle(tmp_path):
    db = tmp_path / "c.db"
    _make_db(db, [(145, 0.001, "2026-05-31T20:00:00"),
                  (165, 0.002, "2026-05-31T20:03:00")])
    out = _bash(f"source {SOAK_COMMON}; last_cycle_in_db {db}")
    assert out.stdout.strip() == "165"


def test_total_spend_in_db_sums_since_iso(tmp_path):
    db = tmp_path / "c.db"
    _make_db(db, [(1, 0.0010, "2026-05-31T19:00:00"),   # before window
                  (2, 0.0030, "2026-05-31T20:01:00"),   # in window
                  (3, 0.0025, "2026-05-31T20:02:00")])  # in window
    out = _bash(
        f"source {SOAK_COMMON}; total_spend_in_db {db} '2026-05-31T20:00:00'"
    )
    assert out.stdout.strip() == "0.0055"


def test_fp_ge_float_comparison():
    out = _bash(
        f"source {SOAK_COMMON}; "
        "fp_ge 1.50 0.75 && echo GE; fp_ge 0.50 0.75 || echo LT"
    )
    assert "GE" in out.stdout
    assert "LT" in out.stdout


def test_missing_db_is_safe_default(tmp_path):
    missing = tmp_path / "nope.db"
    cyc = _bash(f"source {SOAK_COMMON}; last_cycle_in_db {missing}")
    spend = _bash(f"source {SOAK_COMMON}; total_spend_in_db {missing} '2026-01-01'")
    assert cyc.stdout.strip() == "0"
    assert spend.stdout.strip() == "0.0"


def test_real_task_runner_resolves_the_helpers():
    """The runner sources _soak_common.sh; after that the three helpers it
    calls in phase_loop must be defined (the exact W3 failure: they weren't)."""
    script = textwrap.dedent(f"""
        source {SOAK_COMMON}
        for fn in total_spend_in_db last_cycle_in_db fp_ge; do
            type "$fn" >/dev/null 2>&1 || {{ echo "MISSING $fn"; exit 1; }}
        done
        echo ALL_RESOLVED
    """)
    out = _bash(script)
    assert "ALL_RESOLVED" in out.stdout, out.stdout + out.stderr
    # And the runner really does source _soak_common.sh.
    assert ". \"$(dirname \"$0\")/_soak_common.sh\"" in REAL_TASK.read_text()
