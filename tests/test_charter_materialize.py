"""S1 Chip 3: materialize an approved charter into the v46 harness inputs.

Pins the import rewrite, the on-disk layout (test written, reference impl
stripped), the design-note allowlist as parsed by the REAL ADR 0146 scope
check, and the review packet.
"""

from __future__ import annotations

from chimera.core.scope_check import (
    extract_ready_for_remediation,
    parse_recommendation,
)
from chimera.proposals.charter import CharterBundle
from chimera.proposals.charter_materialize import (
    build_design_note,
    format_charter_packet,
    materialize_charter,
    rewrite_test_imports,
)


def _bundle() -> CharterBundle:
    return CharterBundle(
        goal="summarize soak health into one table",
        module_name="soak_health",
        acceptance_test=(
            "import soak_health\n"
            "from soak_health import summarize\n\n"
            "def test_summarize():\n"
            "    assert summarize([]) == ''\n"
            "    assert soak_health.summarize([1]) == '1 row'\n"
        ),
        reference_impl="def summarize(rows):\n    return '' if not rows else f'{len(rows)} row'\n",
        design_note="One command that rolls soak ledgers into a health table.",
        scope_paths=["chimera/soak_health.py"],
    )


# ── rewrite_test_imports ────────────────────────────────────────────


def test_rewrite_from_import():
    out = rewrite_test_imports(
        "from soak_health import summarize\n", "soak_health", "chimera.soak_health",
    )
    assert out == "from chimera.soak_health import summarize\n"


def test_rewrite_plain_import_keeps_attr_refs():
    out = rewrite_test_imports("import soak_health\n", "soak_health", "chimera.soak_health")
    assert out == "import chimera.soak_health as soak_health\n"


def test_rewrite_leaves_lookalikes_untouched():
    src = "import soak_health_other\nx = soak_healthy\n"
    out = rewrite_test_imports(src, "soak_health", "chimera.soak_health")
    assert out == src  # word-boundary anchored


# ── materialize_charter ─────────────────────────────────────────────


def test_materialize_writes_test_and_design_not_impl(tmp_path):
    art = materialize_charter(_bundle(), repo_root=tmp_path, prefix="sc01")
    assert art.target_module_path == "chimera/soak_health.py"
    assert art.dotted_module == "chimera.soak_health"
    assert art.test_path == "tests/test_soak_health.py"
    assert art.scope_allowlist == ["chimera/soak_health.py"]
    # Test written with rewritten imports…
    test_src = (tmp_path / art.test_path).read_text()
    assert "from chimera.soak_health import summarize" in test_src
    assert "import chimera.soak_health as soak_health" in test_src
    # …design note written…
    assert (tmp_path / art.design_path).exists()
    # …and the reference impl DELIBERATELY not written (soak rebuilds it).
    assert not (tmp_path / art.target_module_path).exists()


def test_materialize_write_false_touches_no_disk(tmp_path):
    art = materialize_charter(_bundle(), repo_root=tmp_path, prefix="sc01", write=False)
    assert art.test_path == "tests/test_soak_health.py"
    assert not (tmp_path / art.test_path).exists()
    assert not (tmp_path / art.design_path).exists()


def test_gate_test_cmd_targets_the_written_test():
    art = materialize_charter(_bundle(), repo_root="/nope", prefix="p", write=False)
    assert art.gate_test_cmd[-1] == "tests/test_soak_health.py"
    assert "pytest" in art.gate_test_cmd


def test_derives_target_when_scope_not_under_chimera():
    b = _bundle()
    b.scope_paths = ["docs/notes.md"]  # not a chimera/*.py
    art = materialize_charter(b, repo_root="/nope", prefix="p", write=False)
    assert art.target_module_path == "chimera/soak_health.py"


# ── design note ↔ real ADR 0146 scope check ─────────────────────────


def test_design_note_allowlist_parsed_by_real_scope_check():
    note = build_design_note(_bundle(), "chimera/soak_health.py", "chimera.soak_health")
    section = extract_ready_for_remediation(note)
    assert section is not None
    rec = parse_recommendation(section)
    # The scope check must extract exactly the target as the commit allowlist.
    assert "chimera/soak_health.py" in rec.allowed_paths
    assert not rec.is_ambiguous


# ── review packet ───────────────────────────────────────────────────


def test_packet_has_key_fields():
    b = _bundle()
    art = materialize_charter(b, repo_root="/nope", prefix="p", write=False)
    packet = format_charter_packet(b, art, teeth_score=1.0)
    assert b.goal in packet
    assert "chimera/soak_health.py" in packet
    assert "teeth 1.00" in packet
