"""v4.70 (ADR 0089) — signal-density gates for the engines.

The 2026-05-19/20 post-mortem
(``mind/postmortems/engine-telemetry-2026-05-20.md`` §"Reggio's
daily rhythm doesn't fit operator sessions") observed that UTC
time-window gating in the scheduler did no actual work — per-day
idempotency provided all of the "fire at most once" behaviour,
while time-of-day routing was effectively random for operator
sessions that don't span a full day.

This module is the **content-based gate** the post-mortem
proposed (P2). Each engine consults its own gate inside ``run()``,
right after the provider check. When the gate refuses, the engine
writes a ``status="skipped"`` engine_runs row with the reason and
returns ``EngineResult(skipped=True)`` — visible to the operator
as an explicit "I declined to fire because X" rather than a
silent no-op.

The scheduler's time-window logic still runs (so legacy operators
who depend on the morning/midday/evening rhythm keep their
behaviour); the gate adds a second filter on top.

Each gate returns ``GateDecision(allow, reason)``. ``allow=True``
means "fire"; ``allow=False`` with a reason like "cold-start: no
api_calls in last 5 cycles" tells the operator why nothing
happened this cycle.

Thresholds are tunable via env vars (all default OFF means
"identical to v4.69 — no gate effect"; default ON means "use the
postmortem-derived thresholds below"):

  * ``CHIMERA_ENGINE_GATES_ENABLED=1`` (default 1) — master switch.
    Set to 0 to recover pre-v4.70 behaviour.
  * ``CHIMERA_DISCOVERY_MIN_API_CALLS=5`` — discovery skips when
    fewer than this many api_calls landed in the last 5 cycles.
  * ``CHIMERA_REFLECTION_MIN_CYCLES=3`` — reflection skips when
    today has fewer cycles than this with api activity.
  * ``CHIMERA_CURIOSITY_REQUIRE_DISCOVERY=1`` — curiosity skips
    unless today's chronicle has a non-cold-start ``Morning
    Discovery`` section. Set to 0 to allow curiosity even on
    cold-start days (pre-v4.70 behaviour).
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class GateDecision:
    allow: bool
    reason: str


# ── env knobs ──────────────────────────────────────────────────


def gates_enabled() -> bool:
    """Master switch. Default ON. Set CHIMERA_ENGINE_GATES_ENABLED=0
    to revert to the pre-v4.70 "fire whenever the scheduler says
    so" behaviour."""
    raw = os.environ.get("CHIMERA_ENGINE_GATES_ENABLED", "1").strip().lower()
    return raw in ("1", "true", "yes")


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes")


# ── per-engine gates ───────────────────────────────────────────


# Cold-start marker phrases the engine itself wrote yesterday;
# matched in curiosity_gate to detect "Morning Discovery says
# there's nothing to discover."
_COLD_START_MARKERS = (
    "no prior history",
    "fresh session initiation",
    "earliest stage of activity",
    "session is at earliest",
)


def discovery_gate(
    db: sqlite3.Connection, *, cycle: int, lookback_cycles: int = 5,
) -> GateDecision:
    """Discovery distills recent activity into bullet points.

    Skip when there's nothing to distill: < N api_calls in the last
    ``lookback_cycles`` cycles. This is the most common cold-start
    case (operator just booted; no signal yet).
    """
    if not gates_enabled():
        return GateDecision(True, "gates disabled")
    threshold = _int_env("CHIMERA_DISCOVERY_MIN_API_CALLS", 5)
    if threshold <= 0:
        return GateDecision(True, "threshold disabled")
    cutoff = max(0, cycle - lookback_cycles)
    try:
        row = db.execute(
            "SELECT COUNT(*) AS n FROM api_calls "
            "WHERE cycle > ? AND error IS NULL",
            (cutoff,),
        ).fetchone()
    except sqlite3.OperationalError:
        return GateDecision(True, "api_calls table missing (assume new DB)")
    n = int(row["n"] if row else 0)
    if n < threshold:
        return GateDecision(
            False,
            f"cold-start: {n} api_calls in last {lookback_cycles} cycles "
            f"(< {threshold}); nothing substantive to distill",
        )
    return GateDecision(True, f"{n} api_calls in last {lookback_cycles} cycles")


def _today_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


_TODAY_HEADER_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\b", re.MULTILINE)
_DISCOVERY_BLOCK_RE = re.compile(
    r"### Morning Discovery\s*\n(?P<body>.*?)(?=\n### |\n## |\Z)",
    re.DOTALL,
)


def curiosity_gate(
    chronicle_text: str | None, *, today_iso: str | None = None,
) -> GateDecision:
    """Curiosity needs a topic to investigate. Skip when:

    * Today's chronicle has no ``Morning Discovery`` section yet, OR
    * The section's body matches a cold-start marker (the engine
      itself wrote "no prior history" — investigating that is the
      anti-pattern the post-mortem named).

    The chronicle text is passed in (rather than loaded here) so
    the engine can use its own ``ChronicleManager`` instance and we
    keep this function unit-testable.
    """
    if not gates_enabled():
        return GateDecision(True, "gates disabled")
    if not _bool_env("CHIMERA_CURIOSITY_REQUIRE_DISCOVERY", True):
        return GateDecision(True, "discovery-prereq disabled")
    if not chronicle_text:
        return GateDecision(False, "no chronicle file yet")
    today = today_iso or _today_iso()
    # Locate today's section.
    today_idx = chronicle_text.find(f"## {today}")
    if today_idx < 0:
        return GateDecision(
            False, f"no chronicle section for today ({today})",
        )
    # Body is from the today header to the next ## (or EOF).
    rest = chronicle_text[today_idx:]
    next_header = _TODAY_HEADER_RE.search(rest, pos=1)
    today_section = rest[: next_header.start()] if next_header else rest
    m = _DISCOVERY_BLOCK_RE.search(today_section)
    if not m:
        return GateDecision(False, "today has no Morning Discovery section")
    body = m.group("body").strip().lower()
    if not body:
        return GateDecision(False, "Morning Discovery section is empty")
    if any(marker in body for marker in _COLD_START_MARKERS):
        return GateDecision(
            False,
            "Morning Discovery body matches a cold-start marker "
            "(\"no prior history\" or similar) — nothing substantive "
            "to investigate",
        )
    # Substantive content: at least 2 distinct bullet lines (so a
    # one-line "(no observations)" stub doesn't count).
    bullets = [
        ln for ln in body.splitlines()
        if ln.strip().startswith("-") and len(ln.strip()) > 4
    ]
    if len(bullets) < 2:
        return GateDecision(
            False,
            f"Morning Discovery has only {len(bullets)} bullet(s); "
            "not enough signal to pick a topic",
        )
    return GateDecision(True, f"Morning Discovery has {len(bullets)} bullets")


def reflection_gate(
    db: sqlite3.Connection, *, cycle: int,
) -> GateDecision:
    """Reflection summarises today's work. Skip on days with no
    substantive cycle activity — there's nothing to reflect on, and
    the engine has a documented tendency to write generic
    "today was quiet" reflections on empty days (see 2026-05-19's
    chronicle entry).
    """
    if not gates_enabled():
        return GateDecision(True, "gates disabled")
    threshold = _int_env("CHIMERA_REFLECTION_MIN_CYCLES", 3)
    if threshold <= 0:
        return GateDecision(True, "threshold disabled")
    try:
        row = db.execute(
            "SELECT COUNT(DISTINCT cycle) AS n FROM api_calls "
            "WHERE error IS NULL "
            "  AND datetime(created_at) >= datetime('now', 'start of day')"
        ).fetchone()
    except sqlite3.OperationalError:
        return GateDecision(True, "api_calls table missing (assume new DB)")
    n = int(row["n"] if row else 0)
    if n < threshold:
        return GateDecision(
            False,
            f"only {n} cycle(s) with api activity today "
            f"(< {threshold}); not enough to reflect on",
        )
    return GateDecision(True, f"{n} cycle(s) with api activity today")


__all__ = [
    "GateDecision",
    "curiosity_gate",
    "discovery_gate",
    "gates_enabled",
    "reflection_gate",
]
