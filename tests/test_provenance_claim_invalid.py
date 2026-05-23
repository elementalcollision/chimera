"""v4.118 (ADR 0118): provenance-claim validity detector.

Soak v20-3rd surfaced this gap: phase-2 agent shipped commit ``e3af158``
with subject ``[agent] Add ruff_claim_invalid detector (v4.120 / ADR
0120)``. The actual platform was v4.116 (ADR 0116 had just merged) and
ADR 0120 did not exist. The v4.115 path-drift detector cleared (path
claims in the body were all honest); the witness panel cleared (the
diff itself was structurally fine). Nothing reads non-path tokens in
commit messages.

This module tests
:func:`chimera.core.act.check_provenance_claim_valid` and verifies the
detector is wired into the escalation / trust / remediation chain.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from chimera.core.act import (
    _extract_provenance_claims,
    check_provenance_claim_valid,
)
from chimera.core.escalation import ESCALATING_FINISH_REASONS
from chimera.core.remediation import (
    _provenance_claim_invalid_hint,
    derive_remediation_hint,
)
from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS


def _git(*args: str, cwd: Path) -> str:
    res = subprocess.run(
        ["git", *args], cwd=str(cwd),
        capture_output=True, text=True, check=True,
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


# ── _extract_provenance_claims ──────────────────────────────────────


def test_extract_picks_up_version_tokens() -> None:
    msg = "[agent] add detector (v4.120 / ADR 0120)\n\nSee v4.115."
    versions, adrs = _extract_provenance_claims(msg)
    assert versions == ["4.120", "4.115"]
    assert adrs == ["0120"]


def test_extract_normalizes_patch_to_minor() -> None:
    msg = "Touches v4.115.0 and v4.116.3."
    versions, _ = _extract_provenance_claims(msg)
    assert versions == ["4.115", "4.116"]


def test_extract_adr_pads_to_four_digits() -> None:
    msg = "ADR 99, ADR-115, ADR  0120, ADR0042."
    _, adrs = _extract_provenance_claims(msg)
    assert adrs == ["0099", "0115", "0120", "0042"]


def test_extract_ignores_non_cite_tokens() -> None:
    msg = "Commit deadbeef, refs/heads/main, v1, 4.115, ADR-only."
    versions, adrs = _extract_provenance_claims(msg)
    # "v1" has no minor; "4.115" has no v-prefix; "ADR-only" has no number.
    assert versions == []
    assert adrs == []


def test_extract_dedupes() -> None:
    msg = "v4.120 v4.120 ADR 0120 ADR 0120"
    versions, adrs = _extract_provenance_claims(msg)
    assert versions == ["4.120"]
    assert adrs == ["0120"]


# ── check_provenance_claim_valid ────────────────────────────────────


def _seed_repo_metadata(root: Path) -> None:
    """Plant a pyproject and an ADR matching v4.116 / ADR 0116."""
    (root / "pyproject.toml").write_text(
        '[project]\nname = "chimera"\nversion = "4.116.0"\n'
    )
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "adr").mkdir(exist_ok=True)
    (root / "docs" / "adr" / "0116-charter-file-count-enforcement.md").write_text(
        "# ADR 0116 (v4.116)\n"
    )


def test_no_agent_prefix_is_silent(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _seed_repo_metadata(tmp_path)
    _git("add", "pyproject.toml", "docs", cwd=tmp_path)
    _git("commit", "-q", "-m", "soak: mention v4.999 and ADR 9999", cwd=tmp_path)
    assert check_provenance_claim_valid(tmp_path) == []


def test_honest_commit_does_not_fire(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    _seed_repo_metadata(tmp_path)
    _git("add", "pyproject.toml", "docs", cwd=tmp_path)
    _git(
        "commit", "-q", "-m",
        "[agent] add detector (v4.116 / ADR 0116)",
        cwd=tmp_path,
    )
    assert check_provenance_claim_valid(tmp_path) == []


def test_v20_3rd_regression_fires(tmp_path: Path) -> None:
    """The exact soak-v20-3rd shape: subject cites v4.120 / ADR 0120
    when platform is v4.116 and ADR 0120 doesn't exist."""
    _init_repo(tmp_path)
    _seed_repo_metadata(tmp_path)
    _git("add", "pyproject.toml", "docs", cwd=tmp_path)
    _git(
        "commit", "-q", "-m",
        "[agent] Add ruff_claim_invalid detector (v4.120 / ADR 0120)",
        cwd=tmp_path,
    )
    failures = check_provenance_claim_valid(tmp_path)
    assert "v4.120" in failures
    assert "ADR 0120" in failures


def test_tag_resolves_version(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    # Tag v4.116.0 — the detector should treat "v4.116" as resolved.
    _git("tag", "v4.116.0", cwd=tmp_path)
    (tmp_path / "x.py").write_text("y = 1\n")
    _git("add", "x.py", cwd=tmp_path)
    _git(
        "commit", "-q", "-m",
        "[agent] tweak (v4.116)",
        cwd=tmp_path,
    )
    assert check_provenance_claim_valid(tmp_path) == []


def test_adr_file_resolves_adr(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "0099-some-decision.md").write_text("body\n")
    (tmp_path / "x.py").write_text("y = 1\n")
    _git("add", "x.py", "docs", cwd=tmp_path)
    _git("commit", "-q", "-m", "[agent] thing (ADR 0099)", cwd=tmp_path)
    assert check_provenance_claim_valid(tmp_path) == []


def test_subprocess_failure_returns_empty(tmp_path: Path) -> None:
    # Not a git repo → git log fails → detector returns [].
    assert check_provenance_claim_valid(tmp_path) == []


def test_returns_empty_when_message_has_no_cites(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "x.py").write_text("y = 1\n")
    _git("add", "x.py", cwd=tmp_path)
    _git("commit", "-q", "-m", "[agent] x.py: tweak", cwd=tmp_path)
    assert check_provenance_claim_valid(tmp_path) == []


# ── wiring ──────────────────────────────────────────────────────────


def test_finish_reason_is_escalating() -> None:
    assert "provenance_claim_invalid" in ESCALATING_FINISH_REASONS


def test_trust_delta_is_one_tier() -> None:
    assert FINISH_REASON_TRUST_DELTAS["provenance_claim_invalid"] == 1


def test_remediation_hint_with_claims_names_them() -> None:
    hint = _provenance_claim_invalid_hint(
        "task", provenance_claim_failures=["v4.120", "ADR 0120"],
    )
    assert "v4.120" in hint
    assert "ADR 0120" in hint
    assert "git tag" in hint or "docs/adr" in hint


def test_remediation_hint_db_only_path_is_generic() -> None:
    hint = _provenance_claim_invalid_hint("task")
    assert "git tag" in hint
    assert "docs/adr" in hint


def test_derive_remediation_hint_routes() -> None:
    hint = derive_remediation_hint("task", "provenance_claim_invalid")
    assert hint is not None
    assert "commit" in hint.lower()
