"""Cross-host peer registry sync (ADR 0021, v3.7).

Reads ``CHIMERA_REMOTE_PEERS`` (comma-separated base URLs), GETs
``/healthz`` from each, and writes a :class:`PeerEntry` into the local
registry with ``reach = {"transport": "http", "url": "<base>/mcp"}``.

Sync is explicit (``chimera peers sync`` or programmatic) — there is no
background thread. Remote-host stale entries are removed by
:func:`sweep_remote_stale` based on ``registered_at`` age.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import httpx

from .registry import (
    PeerEntry,
    REGISTRY_SCHEMA_VERSION,
    _safe_filename,
    _utc_now_iso,
    registry_dir,
)

logger = logging.getLogger(__name__)


_ENV_REMOTE_PEERS = "CHIMERA_REMOTE_PEERS"
_DEFAULT_STALE_AGE_HOURS = 24.0


@dataclass(frozen=True)
class SyncResult:
    fetched: int
    added: int
    updated: int
    failures: list[tuple[str, str]]  # (url, error message)


def _parse_remote_urls(raw: str | None) -> list[str]:
    raw = raw if raw is not None else os.environ.get(_ENV_REMOTE_PEERS, "")
    return [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]


def _entry_from_healthz(url: str, body: dict, *, token: str | None = None) -> PeerEntry:
    parsed = urlparse(url)
    host = parsed.hostname or url
    reach: dict = {"transport": "http", "url": f"{url}/mcp"}
    if token:
        reach["bearer"] = token
    return PeerEntry(
        agent_id=str(body.get("agent_id") or f"unknown@{host}"),
        version=str(body.get("version", "?")),
        capabilities=tuple(body.get("capabilities") or ()),
        pid=0,  # unknown on remote host
        host=host,
        reach=reach,
        registered_at=_utc_now_iso(),
        schema_version=REGISTRY_SCHEMA_VERSION,
    )


def sync_remote_peers(
    urls: Iterable[str] | None = None,
    *,
    token: str | None = None,
    timeout: float = 5.0,
    dir: Path | None = None,
) -> SyncResult:
    """Fetch /healthz from each URL and upsert into the local registry."""
    url_list = list(urls) if urls is not None else _parse_remote_urls(None)
    bearer = token or os.environ.get("CHIMERA_PEER_TOKEN", "").strip() or None
    d = dir or registry_dir()
    fetched = added = updated = 0
    failures: list[tuple[str, str]] = []

    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    with httpx.Client(timeout=timeout, headers=headers) as client:
        for raw_url in url_list:
            try:
                resp = client.get(f"{raw_url}/healthz")
                resp.raise_for_status()
                body = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("remote peer sync %s failed: %s", raw_url, exc)
                failures.append((raw_url, str(exc)))
                continue
            fetched += 1
            entry = _entry_from_healthz(raw_url, body, token=bearer)
            target = d / _safe_filename(entry.agent_id)
            existed = target.exists()
            import json

            target.write_text(
                json.dumps(entry.to_dict(), indent=2, sort_keys=True)
            )
            if existed:
                updated += 1
            else:
                added += 1
    return SyncResult(fetched=fetched, added=added, updated=updated, failures=failures)


def sweep_remote_stale(
    *,
    max_age_hours: float = _DEFAULT_STALE_AGE_HOURS,
    dir: Path | None = None,
    now: dt.datetime | None = None,
) -> int:
    """Remove remote (transport='http') entries older than ``max_age_hours``.

    Returns the number of entries removed. Local entries are untouched —
    :func:`chimera.a2a.registry.sweep_stale` handles those via pid check.
    """
    d = dir or registry_dir()
    now = now or dt.datetime.now(dt.timezone.utc)
    removed = 0
    cutoff = now - dt.timedelta(hours=max_age_hours)
    import json

    for p in d.glob("*.json"):
        try:
            data = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        reach = data.get("reach") or {}
        if reach.get("transport") != "http":
            continue
        registered_at = data.get("registered_at") or ""
        try:
            ts = dt.datetime.fromisoformat(registered_at)
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        if ts < cutoff:
            p.unlink(missing_ok=True)
            removed += 1
    return removed
