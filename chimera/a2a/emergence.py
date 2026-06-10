"""Protocol journal — track how peer schemas evolve over time.

Per ADR 0014 (v2.9). Loose analogue of Xenocomm's EmergenceManager,
specialised to Chimera's existing schema observations.

The journal records ``ObservationRecord`` rows as ``(peer, tool,
param_set, ts)`` quadruples to a per-peer JSONL file. Two analyses
operate on the journal:

- :func:`list_for_peer` — flat list of every observation for a peer
- :func:`detect_protocol_drift` — diff a peer's CURRENT schema against
  its earliest observation, classifying each tool as
  ``STABLE`` / ``ADDED`` / ``REMOVED`` / ``EVOLVED``.

This is the data plumbing alignment & emergence policies will read
from. No automatic action — the journal is observation-only at v2.9.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


_DEFAULT_JOURNAL_SUBDIR = "protocol_journal"


def journal_dir() -> Path:
    """Resolve and create the journal directory."""
    raw = os.environ.get("CHIMERA_PROTOCOL_JOURNAL_DIR")
    if raw:
        d = Path(raw).expanduser()
    else:
        # Default under the state dir if set, else ~/.chimera/.
        state_dir = os.environ.get("CHIMERA_STATE_DIR")
        base = Path(state_dir) if state_dir else (Path.home() / ".chimera")
        d = base / _DEFAULT_JOURNAL_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _safe(name: str) -> str:
    out = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)
    return out or "anonymous"


def _params(schema: dict[str, Any]) -> list[str]:
    fn = schema.get("function") if schema.get("type") == "function" else schema
    params = (fn or {}).get("parameters") or {}
    props = params.get("properties") or {}
    return sorted(props.keys())


@dataclass(frozen=True)
class ObservationRecord:
    peer: str
    tool: str
    params: tuple[str, ...]
    observed_at: str


class EvolutionKind(str, Enum):
    STABLE = "stable"
    ADDED = "added"          # tool present now, not in earliest baseline
    REMOVED = "removed"      # tool in baseline, not in current
    EVOLVED = "evolved"      # tool present both, params differ


@dataclass(frozen=True)
class EvolutionRecord:
    tool: str
    kind: EvolutionKind
    baseline_params: tuple[str, ...]
    current_params: tuple[str, ...]
    added_params: tuple[str, ...]
    removed_params: tuple[str, ...]


# ── journal I/O ─────────────────────────────────────────────


def _peer_path(peer: str, *, dir: Path | None = None) -> Path:
    d = dir or journal_dir()
    return d / f"{_safe(peer)}.jsonl"


def record_observation(
    peer: str,
    tool: str,
    schema: dict[str, Any],
    *,
    observed_at: str | None = None,
    dir: Path | None = None,
) -> ObservationRecord:
    """Append a single observation. Returns the record written."""
    record = ObservationRecord(
        peer=peer,
        tool=tool,
        params=tuple(_params(schema)),
        observed_at=observed_at or _utc_now_iso(),
    )
    path = _peer_path(peer, dir=dir)
    line = json.dumps(
        {
            "peer": record.peer,
            "tool": record.tool,
            "params": list(record.params),
            "observed_at": record.observed_at,
        },
        sort_keys=True,
    )
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return record


def list_for_peer(peer: str, *, dir: Path | None = None) -> list[ObservationRecord]:
    """All observation records for one peer, oldest first."""
    path = _peer_path(peer, dir=dir)
    if not path.exists():
        return []
    out: list[ObservationRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
            out.append(
                ObservationRecord(
                    peer=str(data["peer"]),
                    tool=str(data["tool"]),
                    params=tuple(data.get("params") or ()),
                    observed_at=str(data["observed_at"]),
                )
            )
        except (json.JSONDecodeError, KeyError):
            continue
    return out


def record_observations_from_registry(
    peer: str,
    registry,
    *,
    dir: Path | None = None,
) -> list[ObservationRecord]:
    """Convenience: record every ``mcp-<peer>-*`` tool currently in the registry.

    Returns the list of records written.
    """
    prefix = f"mcp-{peer}-"
    out: list[ObservationRecord] = []
    for name in registry.names():
        if not name.startswith(prefix):
            continue
        entry = registry.get(name)
        if entry is None:
            continue
        tool = name[len(prefix):]
        out.append(record_observation(peer, tool, entry.schema, dir=dir))
    return out


# ── drift detection ─────────────────────────────────────────


def detect_protocol_drift(
    peer: str,
    *,
    current_schemas: dict[str, dict[str, Any]] | None = None,
    dir: Path | None = None,
) -> list[EvolutionRecord]:
    """Compare a peer's earliest observation per tool to its current shape.

    If ``current_schemas`` is None, the latest journaled observation per
    tool is used as "current" — useful for offline analysis. If it's
    supplied (e.g. from a live MCP discovery), the journal supplies the
    baseline only.

    Returns one :class:`EvolutionRecord` per tool seen in either source.
    """
    obs = list_for_peer(peer, dir=dir)
    earliest_by_tool: dict[str, tuple[str, ...]] = {}
    latest_by_tool: dict[str, tuple[str, ...]] = {}
    for rec in obs:
        if rec.tool not in earliest_by_tool:
            earliest_by_tool[rec.tool] = rec.params
        latest_by_tool[rec.tool] = rec.params

    if current_schemas is not None:
        current_by_tool: dict[str, tuple[str, ...]] = {
            tool: tuple(_params(schema))
            for tool, schema in current_schemas.items()
        }
    else:
        current_by_tool = dict(latest_by_tool)

    all_tools = sorted(set(earliest_by_tool) | set(current_by_tool))
    out: list[EvolutionRecord] = []
    for tool in all_tools:
        base = earliest_by_tool.get(tool)
        cur = current_by_tool.get(tool)
        if base is None and cur is not None:
            kind = EvolutionKind.ADDED
            added = cur
            removed = ()
        elif base is not None and cur is None:
            kind = EvolutionKind.REMOVED
            added = ()
            removed = base
        elif base == cur:
            kind = EvolutionKind.STABLE
            added = ()
            removed = ()
        else:
            kind = EvolutionKind.EVOLVED
            base_set = set(base or ())
            cur_set = set(cur or ())
            added = tuple(sorted(cur_set - base_set))
            removed = tuple(sorted(base_set - cur_set))
        out.append(
            EvolutionRecord(
                tool=tool,
                kind=kind,
                baseline_params=tuple(base or ()),
                current_params=tuple(cur or ()),
                added_params=added,
                removed_params=removed,
            )
        )
    return out


def forget_peer(peer: str, *, dir: Path | None = None) -> bool:
    """Delete a peer's journal file. Returns True if a file was removed."""
    path = _peer_path(peer, dir=dir)
    if path.exists():
        path.unlink()
        return True
    return False
