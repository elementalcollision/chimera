"""`chimera charter` verb: run_charter orchestration + CLI wiring guard."""

from __future__ import annotations

from chimera.proposals.charter_cli import run_charter


def _charter_text(*, test_body: str, impl_body: str, module: str = "adder") -> str:
    return (
        "```charter-meta\n"
        f'{{"module_name": "{module}", "scope_paths": ["chimera/{module}.py"]}}\n'
        "```\n```charter-design\nAdds ints.\n```\n"
        "```charter-test\n" + test_body + "\n```\n"
        "```charter-impl\n" + impl_body + "\n```\n"
    )


_IMPL = "def add(a, b):\n    return a + b\n\ndef is_even(n):\n    return n % 2 == 0"
_STRONG = (
    "import adder\n"
    "def test_add(): assert adder.add(2, 3) == 5 and adder.add(-1, 1) == 0\n"
    "def test_even(): assert adder.is_even(4) is True and adder.is_even(3) is False"
)
_WEAK = "def test_nothing():\n    assert True"


class _StubProvider:
    def __init__(self, text: str) -> None:
        self._text = text

    async def complete_with_tools(self, **kwargs):
        class _R:
            pass
        r = _R()
        r.text = self._text
        return r


# ── run_charter ─────────────────────────────────────────────────────


def test_run_charter_accepts_and_writes(tmp_path):
    prov = _StubProvider(_charter_text(test_body=_STRONG, impl_body=_IMPL))
    code, out = run_charter(
        "add ints", provider=prov, model_id="m", repo_root=tmp_path, prefix="c01",
    )
    assert code == 0
    assert "Charter review" in out and "chimera/adder.py" in out
    assert (tmp_path / "tests/test_adder.py").exists()
    assert (tmp_path / "mind/research/c01-add-ints-design.md").exists()
    # reference impl is NOT written — the soak rebuilds it.
    assert not (tmp_path / "chimera/adder.py").exists()


def test_run_charter_preview_writes_nothing(tmp_path):
    prov = _StubProvider(_charter_text(test_body=_STRONG, impl_body=_IMPL))
    code, out = run_charter(
        "add ints", provider=prov, model_id="m", repo_root=tmp_path,
        prefix="c01", write=False,
    )
    assert code == 0
    assert "preview" in out
    assert not (tmp_path / "tests/test_adder.py").exists()


def test_run_charter_rejects_weak_test(tmp_path):
    prov = _StubProvider(_charter_text(test_body=_WEAK, impl_body=_IMPL))
    code, out = run_charter(
        "add ints", provider=prov, model_id="m", repo_root=tmp_path,
    )
    assert code == 1
    assert "not trustworthy" in out
    assert not (tmp_path / "tests/test_adder.py").exists()


def test_run_charter_rejects_no_charter(tmp_path):
    code, out = run_charter(
        "g", provider=_StubProvider("sorry, nothing"), model_id="m", repo_root=tmp_path,
    )
    assert code == 1
    assert "rejected" in out


# ── CLI wiring guard (the #169/#170 lesson) ─────────────────────────


def test_cli_charter_verb_wired_no_provider(tmp_path, monkeypatch, capsys):
    """The verb parses + routes to _cmd_charter; with no provider keys it
    returns 2 (proving the wiring, without a live model call)."""
    from chimera.cli import main

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "mind").mkdir()
    (tmp_path / "state").mkdir()

    rc = main(["charter", "build a widget counter", "--no-write"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "no provider" in err
