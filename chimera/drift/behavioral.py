"""Behavioral drift detector — fallback-only path.

Ported from ``leonardo-daemon/safeguards/drift.py`` per ADR 0001
§"Behavioral drift detector". The three-instrument design (GhostLexicon,
BehavioralFootprint, SemanticDrift) is preserved as three score
components on a single detector; we depend on no external library.

Composite scoring uses Leonardo's defaults (0.35 / 0.35 / 0.30) with
``lockdown_threshold = 0.30`` and ``warning_threshold = 0.15``. Tune via
:class:`DriftConfig`.

State is persisted as JSON per session under ``state/drift/<session>.json``.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_WORD_RE = re.compile(r"[A-Za-z]{2,}")


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ── Config + reading ─────────────────────────────────────────


@dataclass(frozen=True)
class DriftConfig:
    lockdown_threshold: float = 0.30
    warning_threshold: float = 0.15
    ghost_threshold: float = 0.30
    behavioral_threshold: float = 0.30
    semantic_threshold: float = 0.15
    ghost_weight: float = 0.35
    behavioral_weight: float = 0.35
    semantic_weight: float = 0.30
    semantic_top_k: int = 50
    min_observations: int = 5
    assessment_interval: int = 10


@dataclass(frozen=True)
class DriftReading:
    timestamp: str
    composite_score: float
    severity: str                      # "low" | "moderate" | "high"
    instrument_scores: dict[str, float]
    fired_instruments: list[str]


# ── Detector ────────────────────────────────────────────────


@dataclass
class _DetectorState:
    """Serializable state. Counters and sets become dicts/lists in JSON."""

    observation_count: int = 0
    boundary_marked: bool = False
    observed_words: dict[str, int] = field(default_factory=dict)
    observed_tools: dict[str, int] = field(default_factory=dict)
    anchor_words: dict[str, int] = field(default_factory=dict)
    anchor_tools: dict[str, int] = field(default_factory=dict)
    readings: list[dict[str, Any]] = field(default_factory=list)


class DriftDetector:
    """Track vocabulary + tool-call distribution, surface composite drift."""

    def __init__(
        self,
        *,
        state_path: Path | None = None,
        config: DriftConfig | None = None,
    ) -> None:
        self.state_path = Path(state_path) if state_path else None
        self.config = config or DriftConfig()
        self._state = _DetectorState()
        if self.state_path is not None and self.state_path.exists():
            self._load()

    # ── observation ─────────────────────────────────────

    def observe(self, text: str, tools: list[str] | None = None) -> None:
        s = self._state
        s.observation_count += 1
        for word in _WORD_RE.findall(text.lower()):
            s.observed_words[word] = s.observed_words.get(word, 0) + 1
        if tools:
            for tool in tools:
                s.observed_tools[tool] = s.observed_tools.get(tool, 0) + 1

    def mark_boundary(self) -> None:
        """Snapshot current observations as the anchor, then reset the observed
        window so subsequent ``observe()`` calls populate the "after" side.

        Matches Leonardo's fallback semantics: drift is anchor (before) vs
        observed (after); without the reset, observed ⊇ anchor and all scores
        collapse to zero.
        """
        s = self._state
        s.anchor_words = dict(s.observed_words)
        s.anchor_tools = dict(s.observed_tools)
        s.observed_words = {}
        s.observed_tools = {}
        s.boundary_marked = True

    # ── assessment ──────────────────────────────────────

    def should_assess(self) -> bool:
        s = self._state
        return (
            s.observation_count >= self.config.min_observations
            and s.observation_count % self.config.assessment_interval == 0
        )

    def assess(self) -> DriftReading:
        ghost = self._ghost_score()
        behavioral = self._behavioral_score()
        semantic = self._semantic_score()
        scores = {
            "ghost_lexicon": ghost,
            "behavioral_footprint": behavioral,
            "semantic_drift": semantic,
        }
        composite = (
            ghost * self.config.ghost_weight
            + behavioral * self.config.behavioral_weight
            + semantic * self.config.semantic_weight
        )
        fired: list[str] = []
        if ghost >= self.config.ghost_threshold:
            fired.append("ghost_lexicon")
        if behavioral >= self.config.behavioral_threshold:
            fired.append("behavioral_footprint")
        if semantic >= self.config.semantic_threshold:
            fired.append("semantic_drift")

        if composite >= self.config.lockdown_threshold:
            severity = "high"
        elif composite >= self.config.warning_threshold:
            severity = "moderate"
        else:
            severity = "low"

        reading = DriftReading(
            timestamp=_utc_now_iso(),
            composite_score=round(composite, 4),
            severity=severity,
            instrument_scores={k: round(v, 4) for k, v in scores.items()},
            fired_instruments=fired,
        )
        # Keep the last 100 readings.
        self._state.readings.append(asdict(reading))
        if len(self._state.readings) > 100:
            self._state.readings = self._state.readings[-100:]
        if self.state_path is not None:
            self.save()
        return reading

    # ── instrument scores ───────────────────────────────

    def _ghost_score(self) -> float:
        """Fraction of anchor vocabulary words no longer present in observed."""
        anchor = set(self._state.anchor_words)
        if not anchor:
            return 0.0
        current = set(self._state.observed_words)
        lost = anchor - current
        return len(lost) / len(anchor)

    def _behavioral_score(self) -> float:
        """L1/2 distance between normalized tool-call distributions, in [0, 1]."""
        anchor = self._state.anchor_tools
        current = self._state.observed_tools
        anchor_total = sum(anchor.values())
        current_total = sum(current.values())
        if anchor_total == 0 and current_total == 0:
            return 0.0
        if anchor_total == 0 or current_total == 0:
            return 1.0
        keys = set(anchor) | set(current)
        delta = 0.0
        for k in keys:
            pa = anchor.get(k, 0) / anchor_total
            pc = current.get(k, 0) / current_total
            delta += abs(pa - pc)
        return min(1.0, delta / 2.0)

    def _semantic_score(self) -> float:
        """Fraction of the anchor's top-K most-frequent words absent now."""
        anchor = self._state.anchor_words
        if not anchor:
            return 0.0
        top_k = sorted(anchor.items(), key=lambda kv: (-kv[1], kv[0]))[
            : self.config.semantic_top_k
        ]
        top_set = {w for w, _ in top_k}
        if not top_set:
            return 0.0
        current = set(self._state.observed_words)
        return len(top_set - current) / len(top_set)

    # ── introspection ──────────────────────────────────

    @property
    def observation_count(self) -> int:
        return self._state.observation_count

    @property
    def boundary_marked(self) -> bool:
        return self._state.boundary_marked

    @property
    def readings(self) -> list[DriftReading]:
        return [
            DriftReading(**{k: v for k, v in r.items() if k in DriftReading.__dataclass_fields__})
            for r in self._state.readings
        ]

    # ── persistence ────────────────────────────────────

    def save(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(asdict(self._state), indent=2))

    def _load(self) -> None:
        try:
            raw = json.loads(self.state_path.read_text())  # type: ignore[union-attr]
        except (json.JSONDecodeError, FileNotFoundError):
            return
        self._state = _DetectorState(
            observation_count=int(raw.get("observation_count", 0)),
            boundary_marked=bool(raw.get("boundary_marked", False)),
            observed_words=dict(raw.get("observed_words", {})),
            observed_tools=dict(raw.get("observed_tools", {})),
            anchor_words=dict(raw.get("anchor_words", {})),
            anchor_tools=dict(raw.get("anchor_tools", {})),
            readings=list(raw.get("readings", [])),
        )
