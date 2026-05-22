"""v4.96 (ADR 0101): content-marker verification on write.

Soak v8 surfaced a hollow-file failure: the agent wrote
`mind/research/ping-pong-wiring-investigation.md` but omitted the
required `## READY-FOR-REMEDIATION` sentinel. The file existed, was
non-empty, and every prior detector said "ok" — yet the deliverable
was incomplete. These tests pin the new `artifact_incomplete` detector
against the exact v8 fixture plus the false-positive guards.
"""

from __future__ import annotations

from pathlib import Path

from chimera.core.act import (
    check_artifacts,
    check_content_markers,
    expected_artifacts,
    expected_content_markers,
)
from chimera.core.escalation import ESCALATING_FINISH_REASONS
from chimera.core.remediation import (
    _artifact_incomplete_hint,
    derive_remediation_hint,
)
from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS


# ── expected_content_markers ────────────────────────────────────────


V8_TASK = (
    "Write all of the above to "
    "`mind/research/ping-pong-wiring-investigation.md`. "
    "The file MUST end with a section whose heading is EXACTLY: "
    "`## READY-FOR-REMEDIATION`. Under that heading: (a) the chosen "
    "wiring approach in one sentence."
)


def test_v8_fixture_extracts_marker():
    markers = expected_content_markers(V8_TASK)
    assert markers == {
        "mind/research/ping-pong-wiring-investigation.md": [
            "## READY-FOR-REMEDIATION"
        ]
    }


def test_must_contain_pattern():
    task = (
        "Write `mind/x.md`. The file MUST contain `key: secret-marker` "
        "at the top."
    )
    assert expected_content_markers(task) == {
        "mind/x.md": ["key: secret-marker"]
    }


def test_must_include_pattern():
    task = (
        "Write `mind/y.md`. The file must include `# DONE` somewhere."
    )
    assert expected_content_markers(task) == {"mind/y.md": ["# DONE"]}


def test_ambiguous_must_without_marker_does_not_fire():
    # Colloquial MUST with no backtick-quoted marker → no extraction.
    task = (
        "Write `mind/z.md`. The agent MUST be careful to capture the "
        "full analysis."
    )
    assert expected_content_markers(task) == {}


def test_marker_without_artifact_returns_empty():
    # Marker mentioned but no artifact path → nothing to attach to.
    task = "Be sure to include `## DONE` in the output."
    assert expected_content_markers(task) == {}


def test_multiple_markers_extracted():
    task = (
        "Write `mind/a.md`. The file MUST contain `## SUMMARY` and "
        "MUST end with `## READY-FOR-REMEDIATION`."
    )
    markers = expected_content_markers(task)
    assert set(markers["mind/a.md"]) == {
        "## SUMMARY", "## READY-FOR-REMEDIATION"
    }
    assert set(markers) == {"mind/a.md"}


# ── check_content_markers ───────────────────────────────────────────


def _write(tmp_path: Path, rel: str, body: str) -> None:
    dest = tmp_path / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(body, encoding="utf-8")


def test_v8_fixture_hollow_file_fires(tmp_path: Path):
    # The exact v8 failure shape: file exists, 1632-ish bytes, no sentinel.
    rel = "mind/research/ping-pong-wiring-investigation.md"
    _write(tmp_path, rel, "lots of analysis prose\n" * 60)
    markers = expected_content_markers(V8_TASK)
    missing = check_content_markers(markers, base_dir=tmp_path)
    assert missing == [(rel, "## READY-FOR-REMEDIATION")]


def test_v8_fixture_with_sentinel_does_not_fire(tmp_path: Path):
    rel = "mind/research/ping-pong-wiring-investigation.md"
    body = "analysis prose\n\n## READY-FOR-REMEDIATION\n\nthe answer\n"
    _write(tmp_path, rel, body)
    markers = expected_content_markers(V8_TASK)
    assert check_content_markers(markers, base_dir=tmp_path) == []


def test_multi_marker_all_present_does_not_fire(tmp_path: Path):
    task = (
        "Write `mind/a.md`. The file MUST contain `## SUMMARY` and "
        "MUST end with `## READY-FOR-REMEDIATION`."
    )
    _write(
        tmp_path, "mind/a.md",
        "## SUMMARY\n\nstuff\n\n## READY-FOR-REMEDIATION\n",
    )
    markers = expected_content_markers(task)
    assert check_content_markers(markers, base_dir=tmp_path) == []


def test_multi_marker_one_missing_fires_with_name(tmp_path: Path):
    task = (
        "Write `mind/a.md`. The file MUST contain `## SUMMARY` and "
        "MUST end with `## READY-FOR-REMEDIATION`."
    )
    _write(tmp_path, "mind/a.md", "## SUMMARY\n\nstuff\n")
    markers = expected_content_markers(task)
    missing = check_content_markers(markers, base_dir=tmp_path)
    assert missing == [("mind/a.md", "## READY-FOR-REMEDIATION")]


def test_absent_file_skipped_artifact_missing_handles_it(tmp_path: Path):
    # Regression: the artifact-missing path (file doesn't exist) is
    # check_artifacts' responsibility, not check_content_markers'.
    # check_content_markers should silently skip absent files so it
    # doesn't double-fire on top of artifact_missing.
    markers = expected_content_markers(V8_TASK)
    assert check_content_markers(markers, base_dir=tmp_path) == []
    # And artifact_missing still catches the absent file:
    assert check_artifacts(
        expected_artifacts(V8_TASK), base_dir=tmp_path
    ) == ["mind/research/ping-pong-wiring-investigation.md"]


# ── escalation + trust + remediation wiring ─────────────────────────


def test_artifact_incomplete_is_escalating():
    assert "artifact_incomplete" in ESCALATING_FINISH_REASONS


def test_artifact_incomplete_has_trust_delta():
    assert FINISH_REASON_TRUST_DELTAS["artifact_incomplete"] == 1


def test_remediation_hint_names_path_and_marker():
    hint = _artifact_incomplete_hint(V8_TASK)
    assert "ping-pong-wiring-investigation.md" in hint
    assert "## READY-FOR-REMEDIATION" in hint
    assert "append" in hint.lower()


def test_remediation_dispatch_routes_to_incomplete_hint():
    hint = derive_remediation_hint(V8_TASK, "artifact_incomplete")
    assert hint is not None
    assert "## READY-FOR-REMEDIATION" in hint


def test_remediation_hint_generic_when_no_markers():
    # When the task names no markers, the hint still nudges
    # toward "append the missing section."
    hint = _artifact_incomplete_hint("Do the thing.")
    assert "append" in hint.lower()
