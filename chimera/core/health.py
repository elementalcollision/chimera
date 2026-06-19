"""Production-health rollup (ADR 0182 Phase 3 foundation, CLI side).

The Python parity of the dashboard's `lib/health.ts` computeHealth: folds
the operational signals Chimera already emits — cost rate, drift,
proposal-queue staleness, repeat-failure (hot) escalation signatures —
into a single worst-of verdict with a per-dimension breakdown. Exposed as
``chimera health`` so the operator (or a scheduled job, or CI) gets a
one-command verdict, scriptable via ``--json``.

Read-only and side-effect free. Each dimension always carries its raw
value so a heuristic status can never hide the underlying number.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

HealthStatus = str  # "green" | "amber" | "red" | "unknown"

_RANK: dict[str, int] = {"unknown": 0, "green": 1, "amber": 2, "red": 3}

# Proposal-queue staleness threshold — mirrors the dashboard widget chip.
_STALE_PENDING_SECONDS = 86_400  # 1 day


@dataclass
class HealthDimension:
    key: str
    label: str
    status: HealthStatus
    detail: str


@dataclass
class HealthSummary:
    overall: HealthStatus
    dimensions: list[HealthDimension]

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "dimensions": [
                {"key": d.key, "label": d.label, "status": d.status, "detail": d.detail}
                for d in self.dimensions
            ],
        }

    def worst_dimensions(self) -> list[HealthDimension]:
        """Return dimensions whose status equals the overall verdict.

        Empty when overall is ``green`` or ``unknown`` — those verdicts don't
        have an actionable driver worth surfacing in an alert.
        """
        if self.overall in ("green", "unknown"):
            return []
        return [d for d in self.dimensions if d.status == self.overall]

    def alert_line(self) -> str:
        """Return a terse one-line health alert string.

        - ``green`` → ``"OK"``
        - ``unknown`` → ``"UNKNOWN"``
        - ``amber`` → ``"WATCH: <key1>, <key2>"``
        - ``red`` → ``"DEGRADED: <key1>, <key2>"``

        Keys are drawn from :meth:`worst_dimensions` in their existing order.
        """
        if self.overall == "green":
            return "OK"
        if self.overall == "unknown":
            return "UNKNOWN"
        label = "DEGRADED" if self.overall == "red" else "WATCH"
        keys = ", ".join(d.key for d in self.worst_dimensions())
        return f"{label}: {keys}"


def _worst(a: HealthStatus, b: HealthStatus) -> HealthStatus:
    return b if _RANK[b] > _RANK[a] else a


def compute_health(
    db: sqlite3.Connection,
    *,
    drift_path: Path | None = None,
) -> HealthSummary:
    """Aggregate the operational health signals into a worst-of verdict."""
    dims: list[HealthDimension] = []

    # ── cost rate (rolling 15m) — same bands as lib/cost.ts ──
    from .budget import rolling_spend_usd

    spend15 = rolling_spend_usd(db, minutes=15)
    rate = spend15 / 15.0
    if spend15 <= 0:
        cost_status, cost_detail = "unknown", "no spend in window"
    else:
        cost_status = "green" if rate < 0.10 else "amber" if rate <= 0.50 else "red"
        cost_detail = f"${rate:.3f}/min (15m)"
    dims.append(HealthDimension("cost", "Cost rate", cost_status, cost_detail))

    # ── drift (latest composite) ──
    from .drift_log import list_drift

    recs = list_drift(path=drift_path, limit=1)
    if not recs:
        dims.append(HealthDimension("drift", "Drift", "unknown", "no drift records"))
    else:
        r = recs[-1]
        sev = (r.severity or "").lower()
        status = (
            "red" if any(t in sev for t in ("crit", "sever", "high"))
            else "amber" if any(t in sev for t in ("med", "moder", "warn", "elev"))
            else "green"
        )
        dims.append(HealthDimension(
            "drift", "Drift", status,
            f"composite {r.composite_score:.2f}"
            + (f" ({sev})" if sev else "") + f", cycle {r.cycle}",
        ))

    # ── proposal-queue staleness ──
    from ..memory.mutations import queue_health

    qh = queue_health(db)
    age = qh.get("pending_oldest_age_seconds")
    if age is not None and age > _STALE_PENDING_SECONDS:
        dims.append(HealthDimension(
            "queue", "Proposal queue", "amber", f"oldest pending {age // 3600}h",
        ))
    else:
        dims.append(HealthDimension(
            "queue", "Proposal queue", "green",
            "no pending" if age is None else f"oldest pending {age // 3600}h",
        ))

    # ── repeat-failure (hot) escalation signatures ──
    from .escalation import hot_signatures

    hot = hot_signatures(db, threshold=2)
    dims.append(HealthDimension(
        "escalations", "Hot signatures",
        "amber" if hot else "green",
        f"{len(hot)} repeat-failure signature(s)" if hot else "none",
    ))

    overall = "unknown"
    for d in dims:
        overall = _worst(overall, d.status)
    return HealthSummary(overall, dims)
