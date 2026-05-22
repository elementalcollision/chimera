"""v4.100 (ADR 0104): INBOX-claim honesty detector.

Soak v9 (mind/postmortems/soak-v9-2026-05-22.md, Failure C) surfaced a
new failure CLASS: the agent treated mind/INBOX.md as a write target,
flipping `[ ]` checkboxes to `[x]` without producing the deliverable
the bullet promised. The runner saw `[x]`, exited the phase, and the
lie propagated to the next cycle.

These tests pin the detector against the v9 fixture plus the
false-positive guards.
"""

from __future__ import annotations

from pathlib import Path

from chimera.core.act import (
    _parse_inbox_tasks,
    check_inbox_claim_validity,
    revert_inbox_lie,
)
from chimera.core.escalation import ESCALATING_FINISH_REASONS
from chimera.core.remediation import (
    _inbox_claim_invalid_hint,
    derive_remediation_hint,
)
from chimera.core.submit_pr import _check_inbox_honesty
from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS


# ── _parse_inbox_tasks ───────────────────────────────────────────────


def test_parse_simple_checkboxes():
    text = (
        "# Inbox\n"
        "\n"
        "- [ ] First task\n"
        "- [x] Second task\n"
    )
    parsed = _parse_inbox_tasks(text)
    states = [(s, t) for _i, s, t in parsed]
    assert states == [(" ", "First task"), ("x", "Second task")]


def test_parse_captures_continuation_lines():
    text = (
        "- [ ] Write a regression test in tests/test_loop_guard.py.\n"
        "  The test should cover normal/edge/threshold behaviour.\n"
        "- [x] Other task\n"
    )
    parsed = _parse_inbox_tasks(text)
    assert len(parsed) == 2
    assert "regression test" in parsed[0][2]
    assert "edge/threshold" in parsed[0][2]


# ── check_inbox_claim_validity ────────────────────────────────────────


V9_PRIOR = (
    "# Inbox\n"
    "\n"
    "- [ ] Write a regression test in `tests/test_loop_guard.py` "
    "covering normal/edge/threshold behaviour.\n"
    "- [ ] Investigate the ping-pong wiring in `chimera/core/act.py`.\n"
)


def test_v9_fixture_lie_fires(tmp_path: Path):
    # Mirror the v9 worktree: chimera/core/act.py exists (the wiring
    # commit landed) but the regression test was never written.
    act_file = tmp_path / "chimera" / "core" / "act.py"
    act_file.parent.mkdir(parents=True)
    act_file.write_text("# wired\n")
    current = (
        "# Inbox\n"
        "\n"
        "- [x] Write a regression test in `tests/test_loop_guard.py` "
        "covering normal/edge/threshold behaviour.\n"
        "- [x] Investigate the ping-pong wiring in `chimera/core/act.py`.\n"
    )
    invalid = check_inbox_claim_validity(
        V9_PRIOR, current, ["mind/INBOX.md"], base_dir=tmp_path,
    )
    assert len(invalid) == 1
    task_text, missing = invalid[0]
    assert "tests/test_loop_guard.py" in task_text
    assert missing == ["tests/test_loop_guard.py"]


def test_positive_artifact_exists_does_not_fire(tmp_path: Path):
    # Same flip, but this time the file exists.
    test_file = tmp_path / "tests" / "test_loop_guard.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text("def test_x():\n    assert True\n")
    current = (
        "# Inbox\n"
        "\n"
        "- [x] Write a regression test in `tests/test_loop_guard.py` "
        "covering normal/edge/threshold behaviour.\n"
        "- [ ] Investigate the ping-pong wiring in `chimera/core/act.py`.\n"
    )
    # The INBOX-claim extractor catches paths under tests/ too — so
    # the bullet IS falsifiable, but the deliverable now exists. No
    # fire is the correct behaviour.
    invalid = check_inbox_claim_validity(
        V9_PRIOR, current, ["mind/INBOX.md"], base_dir=tmp_path,
    )
    assert invalid == []


def test_unchanged_checkboxes_not_revalidated(tmp_path: Path):
    # The fix file does not exist in tmp_path. If we re-validate
    # already-`[x]` bullets each cycle we'd churn forever on prior
    # lies (which the agent CAN'T fix anymore — that work is done
    # or abandoned). Only NEW flips trigger.
    prior = (
        "- [x] Write to `state/done.log`.\n"
        "- [ ] Write to `state/pending.log`.\n"
    )
    current = (
        "- [x] Write to `state/done.log`.\n"
        "- [x] Write to `state/pending.log`.\n"
    )
    # Neither file exists. Only the second bullet flipped — should
    # be the only one flagged.
    invalid = check_inbox_claim_validity(
        prior, current, ["mind/INBOX.md"], base_dir=tmp_path,
    )
    assert len(invalid) == 1
    assert "pending.log" in invalid[0][0]


def test_unfalsifiable_bullet_no_fire(tmp_path: Path):
    # "Re-read the verdict" names no artifact path. Flipping it has
    # no falsifiable claim attached → don't fire.
    prior = "- [ ] Re-read the verdict in the prior cycle.\n"
    current = "- [x] Re-read the verdict in the prior cycle.\n"
    invalid = check_inbox_claim_validity(
        prior, current, ["mind/INBOX.md"], base_dir=tmp_path,
    )
    assert invalid == []


def test_no_inbox_write_no_fire(tmp_path: Path):
    # If the agent's write_targets don't include mind/INBOX.md the
    # detector skips entirely (this isn't an INBOX-honesty failure).
    prior = "- [ ] Write to `state/x.log`.\n"
    current = "- [x] Write to `state/x.log`.\n"
    invalid = check_inbox_claim_validity(
        prior, current, ["state/other.log"], base_dir=tmp_path,
    )
    assert invalid == []


def test_content_marker_missing_fires(tmp_path: Path):
    # Artifact exists but lacks a required content marker. The lie
    # detector still fires (the deliverable is incomplete).
    artifact = tmp_path / "state" / "report.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("partial content\n")
    prior = (
        "- [ ] Write to `state/report.md`. The file MUST end with "
        "`## DONE`.\n"
    )
    current = (
        "- [x] Write to `state/report.md`. The file MUST end with "
        "`## DONE`.\n"
    )
    invalid = check_inbox_claim_validity(
        prior, current, ["mind/INBOX.md"], base_dir=tmp_path,
    )
    assert len(invalid) == 1
    _task, missing = invalid[0]
    assert "state/report.md" in missing


# ── revert_inbox_lie ──────────────────────────────────────────────────


def test_revert_flips_x_back_to_open():
    current = (
        "# Inbox\n"
        "\n"
        "- [x] Write to `state/lie.log`.\n"
        "- [x] Write to `state/truth.log`.\n"
    )
    invalid = [("Write to `state/lie.log`.", ["state/lie.log"])]
    out = revert_inbox_lie(current, invalid)
    assert "- [ ] Write to `state/lie.log`." in out
    # The honest bullet stays flipped.
    assert "- [x] Write to `state/truth.log`." in out


def test_revert_no_invalid_returns_unchanged():
    current = "- [x] Anything\n"
    assert revert_inbox_lie(current, []) == current


# ── escalation + trust + remediation wiring ──────────────────────────


def test_inbox_claim_invalid_is_escalating():
    assert "inbox_claim_invalid" in ESCALATING_FINISH_REASONS


def test_inbox_claim_invalid_has_trust_delta():
    assert FINISH_REASON_TRUST_DELTAS["inbox_claim_invalid"] == 1


def test_remediation_hint_names_missing_artifact():
    task = (
        "Write to `state/missing.log`. The file MUST end with `## DONE`."
    )
    hint = _inbox_claim_invalid_hint(task)
    assert "state/missing.log" in hint
    assert "code_exec" in hint.lower()
    assert "revert" in hint.lower() or "reverted" in hint.lower()


def test_remediation_dispatch_routes_to_inbox_hint():
    task = "Write to `state/x.log`."
    hint = derive_remediation_hint(task, "inbox_claim_invalid")
    assert hint is not None
    assert "state/x.log" in hint


def test_remediation_hint_generic_when_no_artifact():
    hint = _inbox_claim_invalid_hint("Re-read the prior verdict.")
    # Still nudges toward doing the work.
    assert "code_exec" in hint.lower()


# ── submit_pr gate ────────────────────────────────────────────────────


def test_submit_pr_gate_blocks_inbox_lie(tmp_path: Path):
    inbox = tmp_path / "mind" / "INBOX.md"
    inbox.parent.mkdir(parents=True)
    inbox.write_text(
        "# Inbox\n"
        "\n"
        "- [x] Write to `state/missing.log`.\n"
    )
    invalid = _check_inbox_honesty(tmp_path)
    assert len(invalid) == 1


def test_submit_pr_gate_passes_when_inbox_honest(tmp_path: Path):
    inbox = tmp_path / "mind" / "INBOX.md"
    inbox.parent.mkdir(parents=True)
    inbox.write_text(
        "# Inbox\n"
        "\n"
        "- [x] Write to `state/present.log`.\n"
    )
    artifact = tmp_path / "state" / "present.log"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("done\n")
    assert _check_inbox_honesty(tmp_path) == []


def test_submit_pr_gate_ignores_open_checkboxes(tmp_path: Path):
    # `[ ]` bullets are explicitly NOT done — they shouldn't trigger
    # the honesty gate even if the artifact is missing.
    inbox = tmp_path / "mind" / "INBOX.md"
    inbox.parent.mkdir(parents=True)
    inbox.write_text(
        "# Inbox\n"
        "\n"
        "- [ ] Write to `state/pending.log`.\n"
    )
    assert _check_inbox_honesty(tmp_path) == []


def test_submit_pr_gate_missing_inbox_is_noop(tmp_path: Path):
    # No INBOX.md at all → nothing to validate.
    assert _check_inbox_honesty(tmp_path) == []
