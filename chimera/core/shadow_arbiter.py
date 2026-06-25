"""Shadow arbiter — log-only adjudication of CONTESTED witness-panel decisions
(ADR 0187 test #5).

When the cross-provider witness panel SPLITS (some members approve, some reject),
an independent arbiter — by default Sakana `fugu-ultra`, a self-verifying
ensemble — reviews the same diff and its verdict is RECORDED, never enforced. The
gate decision is unchanged; this is pure measurement.

Two `GateOutcome`s are written per contested case (gate ``witness_panel`` and gate
``shadow_arbiter``, same diff) into the B.4l calibration ledger, so once the
revert label producer back-fills ground truth the arbiter's value on exactly the
hard cases can be scored — earn promotion before trusting it ("measure before you
bound"). Until then the ledger reads UNCERTIFIED by construction.

INERT by default: fires only when ``CHIMERA_SHADOW_ARBITER`` is set. Overrides:
``CHIMERA_SHADOW_ARBITER_PROVIDER`` (default ``sakana``),
``CHIMERA_SHADOW_ARBITER_MODEL`` (default ``fugu-ultra``).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import logging
import os
from pathlib import Path

from ..providers import get_provider
from .gate_calibration import (
    FAIL,
    PASS,
    UNKNOWN,
    GateOutcome,
    append_gate_outcome,
    gate_outcomes_path,
)
from .witness import witness_code_change

logger = logging.getLogger(__name__)

_OFF = {"", "0", "false", "False", "no", "off"}


def shadow_arbiter_enabled() -> bool:
    """True iff ``CHIMERA_SHADOW_ARBITER`` opts the log-only arbiter in."""
    return os.environ.get("CHIMERA_SHADOW_ARBITER", "").strip() not in _OFF


def is_contested(verdicts) -> bool:
    """True iff the panel SPLIT — at least one approve AND at least one reject.

    A unanimous panel (all approve / all reject) is not contested, and a panel of
    fewer than two members cannot split. The arbiter only adds signal where the
    panel itself was uncertain."""
    vs = list(verdicts)
    if len(vs) < 2:
        return False
    approvals = sum(1 for v in vs if v.approved)
    return 0 < approvals < len(vs)


def _diff_sha(diff: str) -> str:
    return hashlib.sha1(diff.encode("utf-8", "replace")).hexdigest()[:12]


def _repo_class() -> str:
    return "foreign" if os.environ.get("CHIMERA_FOREIGN_REPO") else "self"


def _run_id() -> str:
    return os.environ.get("CHIMERA_SOAK_RUN_ID") or "adhoc"


def _state_dir() -> Path:
    try:
        from . import LoopConfig

        return Path(LoopConfig.from_env().state_dir)
    except Exception:  # noqa: BLE001 — best-effort; never block the gate
        return Path("state")


def build_outcomes(
    panel_approved: bool,
    arbiter_approved: bool,
    *,
    run_id: str,
    diff_sha: str,
    repo_class: str,
    arbiter_model: str,
    ts: str,
) -> list[GateOutcome]:
    """The two ledger records for one contested case — pure, so it is unit-tested
    without any network. ``ground_truth`` starts UNKNOWN (the label producer
    back-fills it); ``verdict`` is PASS when the gate APPROVED, FAIL when it
    rejected (a PASS over a later-VIOLATION is the false negative B.4l scores)."""
    def _v(approved: bool) -> str:
        return PASS if approved else FAIL

    return [
        GateOutcome(
            gate="witness_panel", run_id=run_id, diff_sha=diff_sha,
            model_id="panel", repo_class=repo_class,
            verdict=_v(panel_approved), ground_truth=UNKNOWN, ts=ts,
        ),
        GateOutcome(
            gate="shadow_arbiter", run_id=run_id, diff_sha=diff_sha,
            model_id=arbiter_model, repo_class=repo_class,
            verdict=_v(arbiter_approved), ground_truth=UNKNOWN, ts=ts,
        ),
    ]


async def maybe_shadow_arbitrate(
    task_text: str,
    diff: str,
    paths: list[str],
    labelled: list[tuple[str, object]],
    panel_approved: bool,
    *,
    charter_excerpts: str = "",
) -> bool:
    """If opted-in AND the panel was contested, run the arbiter log-only and record
    the head-to-head. Returns True iff a record was written. NEVER raises and NEVER
    changes the gate — every failure path logs and returns False."""
    if not shadow_arbiter_enabled():
        return False
    if not is_contested(v for _, v in labelled):
        return False

    provider_name = os.environ.get("CHIMERA_SHADOW_ARBITER_PROVIDER", "sakana")
    arbiter_model = os.environ.get("CHIMERA_SHADOW_ARBITER_MODEL", "fugu-ultra")
    try:
        provider = get_provider(provider_name)
    except Exception as e:  # noqa: BLE001 — missing key / unknown provider
        logger.warning("shadow arbiter: provider %r unavailable (%s)", provider_name, e)
        return False

    try:
        verdict = await witness_code_change(
            task_text, diff, paths, provider,
            model_id=arbiter_model, charter_excerpts=charter_excerpts,
        )
    except Exception:  # noqa: BLE001 — best-effort; the arbiter never blocks ACT
        logger.exception("shadow arbiter: review failed")
        return False

    ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    diff_sha = _diff_sha(diff)
    outcomes = build_outcomes(
        panel_approved, bool(verdict.approved),
        run_id=_run_id(), diff_sha=diff_sha, repo_class=_repo_class(),
        arbiter_model=arbiter_model, ts=ts,
    )
    try:
        path = gate_outcomes_path(_state_dir())
        for o in outcomes:
            append_gate_outcome(path, o)
    except Exception:  # noqa: BLE001 — ledger I/O must never break the gate
        logger.exception("shadow arbiter: ledger append failed")
        return False

    logger.info(
        "shadow arbiter: contested %s — panel=%s arbiter=%s (%s)",
        diff_sha, "approve" if panel_approved else "reject",
        "approve" if verdict.approved else "reject", arbiter_model,
    )
    return True
