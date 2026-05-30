"""v43 N=3 fan-out: phase-1 soft-sentinel done-condition.

`soak_phase1_deliverable_landed` (scripts/_soak_common.sh) is the ONLY exit
for v43's phase 1 — there is no single-file ready_marker shortcut (that would
let phase 1 end on the first postmortem's marker while two targets are still
unbuilt). These tests pin its AND semantics:

  1. every allowed deliverable exists, AND
  2. marker presence — default: >=1 carries the READY marker; strict
     (5th arg non-empty, used by v43): EVERY allowed `.md` carries it, AND
  3. the (combined) test command exits 0.

The combined test command stands in here for the real 3-file pytest gate:
`true` == all 17 green, `false` == at least one target still red.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOAK_COMMON = REPO_ROOT / "scripts" / "_soak_common.sh"

_PM = ["mind/research/v43-strcase-postmortem.md",
       "mind/research/v43-numfmt-postmortem.md",
       "mind/research/v43-seqstats-postmortem.md"]
_MARKER = "## READY-FOR-REMEDIATION"


def _wt(tmp_path: Path, *, present, with_marker) -> Path:
    """Build a worktree dir; `present`/`with_marker` are index lists (0..2)."""
    wt = tmp_path / "wt"
    (wt / "mind" / "research").mkdir(parents=True)
    for i, rel in enumerate(_PM):
        if i in present:
            body = "# pm\n" + (f"\n{_MARKER}\nverdict: CONVERGED\n"
                               if i in with_marker else "\n(no marker yet)\n")
            (wt / rel).write_text(body)
    return wt


def _call(wt: Path, test_cmd: str, *, strict: bool) -> int:
    allowed = " ".join(_PM)
    strict_arg = "1" if strict else ""
    script = textwrap.dedent(f"""
        source {SOAK_COMMON}
        soak_phase1_deliverable_landed "{wt}" "{allowed}" "{test_cmd}" \
            "{_MARKER}" "{strict_arg}"
        echo "RC=$?"
    """)
    out = subprocess.run(["bash", "-c", script],  # noqa: S602,S603
                         capture_output=True, text=True, timeout=30).stdout
    assert "RC=" in out, out
    return int(out.split("RC=")[1].split()[0])


# ── strict mode (the v43 wiring) ─────────────────────────────────

def test_strict_all_present_all_markers_test_green_landed(tmp_path):
    wt = _wt(tmp_path, present={0, 1, 2}, with_marker={0, 1, 2})
    assert _call(wt, "true", strict=True) == 0


def test_strict_one_postmortem_missing_not_landed(tmp_path):
    wt = _wt(tmp_path, present={0, 1}, with_marker={0, 1})
    assert _call(wt, "true", strict=True) == 1


def test_strict_one_postmortem_lacks_marker_not_landed(tmp_path):
    # all three files exist but seqstats has no READY block yet.
    wt = _wt(tmp_path, present={0, 1, 2}, with_marker={0, 1})
    assert _call(wt, "true", strict=True) == 1


def test_strict_all_ready_but_test_red_not_landed(tmp_path):
    # the decisive AND across (target, test) pairs: a red combined gate
    # (any target unbuilt) blocks the landing even with all 3 markers.
    wt = _wt(tmp_path, present={0, 1, 2}, with_marker={0, 1, 2})
    assert _call(wt, "false", strict=True) == 1


# ── default mode (backward compat for the N=1 runners) ───────────

def test_default_one_marker_suffices(tmp_path):
    wt = _wt(tmp_path, present={0, 1, 2}, with_marker={0})
    assert _call(wt, "true", strict=False) == 0


def test_default_no_markers_not_landed(tmp_path):
    wt = _wt(tmp_path, present={0, 1, 2}, with_marker=set())
    assert _call(wt, "true", strict=False) == 1
