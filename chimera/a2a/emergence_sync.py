"""Cross-host emergence-journal sync (ADR 0022, v3.8).

Each Chimera serves its journal as JSONL at ``/emergence-feed``. Pulling
nodes call :func:`sync_remote_emergence` to merge those records under a
``remote/<host>/<peer>.jsonl`` subtree. Local journal files are never
touched by sync — remote records always go under ``remote/``.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import httpx

from .emergence import _safe, journal_dir

logger = logging.getLogger(__name__)


_ENV_REMOTE_PEERS = "CHIMERA_REMOTE_PEERS"


@dataclass(frozen=True)
class EmergenceSyncResult:
    fetched: int
    records_added: int
    failures: list[tuple[str, str]]


def _parse_remote_urls(raw: str | None) -> list[str]:
    raw = raw if raw is not None else os.environ.get(_ENV_REMOTE_PEERS, "")
    return [u.strip().rstrip("/") for u in raw.split(",") if u.strip()]


def serialize_journal(*, dir: Path | None = None) -> str:
    """Build the JSONL body served at /emergence-feed.

    Each line: ``{"peer": ..., "tool": ..., "params": [...],
    "observed_at": "...", "source_peer_file": "..."}``. The
    ``source_peer_file`` lets the puller bucket records by origin.
    """
    d = dir or journal_dir()
    lines: list[str] = []
    if not d.exists():
        return ""
    for p in sorted(d.glob("*.jsonl")):
        for raw_line in p.read_text(encoding="utf-8").splitlines():
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                obj = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            obj.setdefault("source_peer_file", p.stem)
            lines.append(json.dumps(obj, sort_keys=True))
    return "\n".join(lines) + ("\n" if lines else "")


def _merge_into_local(
    body: str, *, source_host: str, dir: Path | None = None
) -> int:
    """Append remote records under remote/<host>/<peer>.jsonl. Idempotent
    per (peer, tool, observed_at) — duplicate lines are skipped."""
    d = (dir or journal_dir()) / "remote" / _safe(source_host)
    d.mkdir(parents=True, exist_ok=True)
    added = 0
    by_peer: dict[str, list[str]] = {}
    for raw_line in body.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            obj = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        peer = str(obj.get("source_peer_file") or obj.get("peer") or "unknown")
        by_peer.setdefault(peer, []).append(raw_line)
    for peer, new_lines in by_peer.items():
        path = d / f"{_safe(peer)}.jsonl"
        existing: set[str] = set()
        if path.exists():
            existing = {
                ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            }
        with path.open("a", encoding="utf-8") as f:
            for ln in new_lines:
                if ln in existing:
                    continue
                f.write(ln + "\n")
                existing.add(ln)
                added += 1
    return added


def sync_remote_emergence(
    urls: Iterable[str] | None = None,
    *,
    token: str | None = None,
    timeout: float = 10.0,
    dir: Path | None = None,
) -> EmergenceSyncResult:
    """Pull /emergence-feed from each URL and merge into the local journal."""
    url_list = list(urls) if urls is not None else _parse_remote_urls(None)
    bearer = token or os.environ.get("CHIMERA_PEER_TOKEN", "").strip() or None
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    fetched = 0
    records_added = 0
    failures: list[tuple[str, str]] = []

    with httpx.Client(timeout=timeout, headers=headers) as client:
        for raw_url in url_list:
            try:
                resp = client.get(f"{raw_url}/emergence-feed")
                resp.raise_for_status()
                body = resp.text
            except httpx.HTTPError as exc:
                logger.warning("emergence sync %s failed: %s", raw_url, exc)
                failures.append((raw_url, str(exc)))
                continue
            fetched += 1
            source_host = urlparse(raw_url).hostname or raw_url
            records_added += _merge_into_local(
                body, source_host=source_host, dir=dir
            )
    return EmergenceSyncResult(
        fetched=fetched, records_added=records_added, failures=failures
    )
