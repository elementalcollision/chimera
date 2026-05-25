"""Tests for scripts/_soak_common.sh helpers.

The v9 soak post-mortem traced a phase-1 infinite spin to a path
constant in long_cycle_soak_v{7,8,9}.sh that drifted from the INBOX
text: the INBOX asked the agent to write
`mind/research/ping-pong-wiring-investigation.md`, but the runner
grep-checked `mind/research/loop-abort-investigation.md` for the
READY-FOR-REMEDIATION sentinel. `soak_extract_sentinel_path` reads
the sentinel target out of the INBOX so future runner clones cannot
drift.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMON_SH = REPO_ROOT / "scripts" / "_soak_common.sh"


def _extract(inbox_text: str, tmp_path: Path) -> str:
    inbox = tmp_path / "INBOX.md"
    inbox.write_text(inbox_text)
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{COMMON_SH}" && soak_extract_sentinel_path "{inbox}"',
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


V6_INBOX = textwrap.dedent(
    """
    - [ ] Write all of the above to
      `mind/research/loop-abort-investigation.md`. The file MUST end
      with a section whose heading is EXACTLY:
      `## READY-FOR-REMEDIATION`
    """
)

V7_V8_V9_INBOX = textwrap.dedent(
    """
    - [ ] Write all of the above to
      `mind/research/ping-pong-wiring-investigation.md`. The file MUST
      end with a section whose heading is EXACTLY:
      `## READY-FOR-REMEDIATION`
    """
)


def test_extracts_v6_target(tmp_path):
    assert _extract(V6_INBOX, tmp_path) == "mind/research/loop-abort-investigation.md"


def test_extracts_v7_v8_v9_target(tmp_path):
    assert (
        _extract(V7_V8_V9_INBOX, tmp_path)
        == "mind/research/ping-pong-wiring-investigation.md"
    )


def test_returns_first_match_when_multiple_paths(tmp_path):
    inbox = textwrap.dedent(
        """
        - [ ] Write all of the above to
          `mind/research/phase1-doc.md`. The file MUST end with
          `## READY-FOR-REMEDIATION`.

        Phase 2 will then read `mind/research/phase1-doc.md` and produce
        `mind/research/phase2-remediation.md`.
        """
    )
    assert _extract(inbox, tmp_path) == "mind/research/phase1-doc.md"


def test_empty_when_no_match(tmp_path):
    assert _extract("No backtick-quoted paths here.\n", tmp_path) == ""


def test_actual_v7_v8_v9_runners_match_inbox():
    """End-to-end: extract from each runner's actual INBOX heredoc and
    confirm the runner's other references agree."""
    for version, expected in [
        ("v6", "loop-abort-investigation.md"),
        ("v7", "ping-pong-wiring-investigation.md"),
        ("v8", "ping-pong-wiring-investigation.md"),
        ("v9", "ping-pong-wiring-investigation.md"),
    ]:
        script = (REPO_ROOT / "scripts" / "archive" / f"long_cycle_soak_{version}.sh").read_text()
        # Pull the phase-1 INBOX heredoc body (first INBOX_EOF block).
        start = script.index("<<'INBOX_EOF'") + len("<<'INBOX_EOF'")
        end = script.index("INBOX_EOF", start)
        inbox_body = script[start:end]
        # Find the first backtick-quoted mind/research path.
        import re

        match = re.search(r"`mind/research/([A-Za-z0-9_-]+\.md)`", inbox_body)
        assert match is not None, f"no sentinel path in {version} phase-1 INBOX"
        assert match.group(1) == expected, (
            f"{version} INBOX advertises {match.group(1)!r}, expected {expected!r}"
        )
