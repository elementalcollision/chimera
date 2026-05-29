"""B2 (v40′ scope-creep sprint): function-local import-shadow detector.

The os/Path UnboundLocalError class that bricked v40 attempts #2 and #4:
an `import` inside a function rebinds a name already imported at module
level, making it local across the whole function. py_compile passes; it
fails only at runtime. check_import_shadowing catches it at the parse-time
ACT gate.
"""

from __future__ import annotations

from pathlib import Path

from chimera.core.act import check_import_shadowing
from chimera.core.remediation import derive_remediation_hint
from chimera.trust.manager import FINISH_REASON_TRUST_DELTAS
from chimera.core.escalation import ESCALATING_FINISH_REASONS


def _write(tmp_path: Path, body: str) -> str:
    p = tmp_path / "mod.py"
    p.write_text(body)
    return str(p)


def test_flags_function_local_import_shadowing_module_import(tmp_path):
    path = _write(tmp_path, (
        "import os\n"
        "def main():\n"
        "    print(os.getcwd())\n"      # reads module-level os...
        "    import os\n"               # ...but this makes os local → bug
        "    return os.environ\n"
    ))
    failures = check_import_shadowing([path])
    assert len(failures) == 1
    assert failures[0][0] == path
    assert "'os'" in failures[0][1] and "main" in failures[0][1]


def test_flags_from_import_shadowing(tmp_path):
    path = _write(tmp_path, (
        "from pathlib import Path\n"
        "def f(x):\n"
        "    from pathlib import Path\n"
        "    return Path(x)\n"
    ))
    failures = check_import_shadowing([path])
    assert len(failures) == 1
    assert "'Path'" in failures[0][1]


def test_legit_lazy_import_not_flagged(tmp_path):
    # LoopConfig is NOT imported at module level → a function-local import
    # of it is the legitimate lazy pattern, must NOT be flagged.
    path = _write(tmp_path, (
        "import os\n"
        "def handler():\n"
        "    from chimera.core import LoopConfig\n"
        "    return LoopConfig.from_env()\n"
    ))
    assert check_import_shadowing([path]) == []


def test_module_level_only_imports_not_flagged(tmp_path):
    path = _write(tmp_path, (
        "import os\n"
        "from pathlib import Path\n"
        "def f():\n"
        "    return os.getcwd(), Path('.')\n"
    ))
    assert check_import_shadowing([path]) == []


def test_non_python_and_missing_paths_skipped(tmp_path):
    assert check_import_shadowing(["notes.md", str(tmp_path / "absent.py")]) == []


def test_unparseable_file_skipped(tmp_path):
    # syntax_invalid owns parse failures; the shadow detector must not crash.
    path = _write(tmp_path, "import os\ndef (:\n")
    assert check_import_shadowing([path]) == []


def test_wired_into_recovery_and_trust():
    # import_shadowing is a recognized recoverable reason with a one-tier
    # demote and an actionable hint.
    assert "import_shadowing" in ESCALATING_FINISH_REASONS
    assert FINISH_REASON_TRUST_DELTAS.get("import_shadowing") == 1
    hint = derive_remediation_hint("build the thing", "import_shadowing")
    assert hint and "UnboundLocalError" in hint
