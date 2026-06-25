"""Shadow arbiter (ADR 0187 #5): contested-only, opt-in, log-only adjudication."""

from __future__ import annotations

import json

import pytest

import chimera.core.shadow_arbiter as sa
from chimera.core.witness import WitnessVerdict


def _v(approved: bool, concerns=None) -> WitnessVerdict:
    return WitnessVerdict(approved=approved, concerns=concerns or [])


# ── pure: contested detection ────────────────────────────────


def test_is_contested_split_true():
    assert sa.is_contested([_v(True), _v(False)]) is True


def test_is_contested_unanimous_approve_false():
    assert sa.is_contested([_v(True), _v(True), _v(True)]) is False


def test_is_contested_unanimous_reject_false():
    assert sa.is_contested([_v(False), _v(False)]) is False


def test_is_contested_single_member_false():
    assert sa.is_contested([_v(False)]) is False


def test_is_contested_empty_false():
    assert sa.is_contested([]) is False


# ── pure: enablement ─────────────────────────────────────────


@pytest.mark.parametrize("val,expected", [
    ("1", True), ("yes", True), ("true", True),
    ("0", False), ("false", False), ("", False),
])
def test_shadow_arbiter_enabled(monkeypatch, val, expected):
    monkeypatch.setenv("CHIMERA_SHADOW_ARBITER", val)
    assert sa.shadow_arbiter_enabled() is expected


def test_shadow_arbiter_disabled_when_unset(monkeypatch):
    monkeypatch.delenv("CHIMERA_SHADOW_ARBITER", raising=False)
    assert sa.shadow_arbiter_enabled() is False


# ── pure: outcome records ────────────────────────────────────


def test_build_outcomes_shape_and_verdicts():
    outs = sa.build_outcomes(
        panel_approved=False, arbiter_approved=True,
        run_id="r1", diff_sha="abc", repo_class="self",
        arbiter_model="fugu-ultra", ts="2026-06-25T00:00:00+00:00",
    )
    assert {o.gate for o in outs} == {"witness_panel", "shadow_arbiter"}
    by_gate = {o.gate: o for o in outs}
    # panel rejected -> FAIL; arbiter approved -> PASS
    assert by_gate["witness_panel"].verdict == "fail"
    assert by_gate["shadow_arbiter"].verdict == "pass"
    # same diff identity, ground truth unlabelled, arbiter model is the cell key
    assert all(o.diff_sha == "abc" and o.run_id == "r1" for o in outs)
    assert all(o.ground_truth == "unknown" for o in outs)
    assert by_gate["shadow_arbiter"].model_id == "fugu-ultra"
    assert by_gate["witness_panel"].model_id == "panel"


# ── orchestrator: no-ops ─────────────────────────────────────


@pytest.mark.asyncio
async def test_noop_when_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("CHIMERA_SHADOW_ARBITER", raising=False)
    monkeypatch.setattr(sa, "_state_dir", lambda: tmp_path)
    wrote = await sa.maybe_shadow_arbitrate(
        "t", "d", ["f"], [("a", _v(True)), ("b", _v(False))], panel_approved=False,
    )
    assert wrote is False
    assert not (tmp_path / "gate-outcomes.jsonl").exists()


@pytest.mark.asyncio
async def test_noop_when_unanimous(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_SHADOW_ARBITER", "1")
    monkeypatch.setattr(sa, "_state_dir", lambda: tmp_path)
    # Unanimous approve → not contested → no arbiter call, no write.
    wrote = await sa.maybe_shadow_arbitrate(
        "t", "d", ["f"], [("a", _v(True)), ("b", _v(True))], panel_approved=True,
    )
    assert wrote is False
    assert not (tmp_path / "gate-outcomes.jsonl").exists()


# ── orchestrator: records a contested case ───────────────────


@pytest.mark.asyncio
async def test_records_contested(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_SHADOW_ARBITER", "1")
    monkeypatch.setattr(sa, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(sa, "get_provider", lambda name: object())

    async def _fake_review(task, diff, paths, provider, *, model_id, charter_excerpts=""):
        assert model_id == "fugu-ultra"
        return _v(True)  # arbiter approves

    monkeypatch.setattr(sa, "witness_code_change", _fake_review)

    labelled = [("a", _v(True)), ("b", _v(False, ["concern"]))]
    wrote = await sa.maybe_shadow_arbitrate(
        "task", "=== f ===\nsome diff", ["f"], labelled, panel_approved=False,
    )
    assert wrote is True
    lines = (tmp_path / "gate-outcomes.jsonl").read_text().strip().splitlines()
    recs = {json.loads(line)["gate"]: json.loads(line) for line in lines}
    assert set(recs) == {"witness_panel", "shadow_arbiter"}
    assert recs["shadow_arbiter"]["verdict"] == "pass"   # arbiter approved
    assert recs["witness_panel"]["verdict"] == "fail"    # panel rejected
    assert recs["shadow_arbiter"]["ground_truth"] == "unknown"
    assert recs["shadow_arbiter"]["model_id"] == "fugu-ultra"
    # both records share the same diff identity (so a later label links them)
    assert recs["shadow_arbiter"]["diff_sha"] == recs["witness_panel"]["diff_sha"]


@pytest.mark.asyncio
async def test_provider_unavailable_is_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_SHADOW_ARBITER", "1")
    monkeypatch.setattr(sa, "_state_dir", lambda: tmp_path)

    def _boom(name):
        raise RuntimeError("SAKANA_API_KEY not set")

    monkeypatch.setattr(sa, "get_provider", _boom)
    wrote = await sa.maybe_shadow_arbitrate(
        "t", "d", ["f"], [("a", _v(True)), ("b", _v(False))], panel_approved=False,
    )
    assert wrote is False  # missing key never raises, never writes
    assert not (tmp_path / "gate-outcomes.jsonl").exists()
