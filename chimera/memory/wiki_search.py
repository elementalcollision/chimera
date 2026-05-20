"""v4.61 (ADR 0080) — mind/wiki full-text search backed by SQLite FTS5.

Replaces the "no episodic recall" baseline that ADR 0002 deferred:
the agent could write to ``mind/wiki/`` for sessions but had no
in-loop way to *retrieve* prior knowledge. The ADR-0002 revisit in
``mind/overnight/adr-revisits.md`` flagged this as the biggest miss
— "I'd add a dirt-simple full-text search on `mind/wiki/` markdown
files (SQLite FTS5, zero dependencies) as a Day-1 feature."

This module ships exactly that. Two tables in the main ``chimera.db``:

  * ``wiki_fts`` — FTS5 virtual table over (path, title, body)
  * ``wiki_fts_files`` — mtime cache for incremental indexing

Updates are mtime-gated like the v4.38 graph skill/wiki projection:
only files whose ``mtime_ns`` changed get re-indexed. Deletes are
detected by walking the cache and removing rows whose ``path`` no
longer exists on disk.

No external dependencies — FTS5 is in the stdlib's SQLite build on
all supported platforms.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Match every markdown file under mind/wiki/. Subdir layout is
# arbitrary — projects/, lessons/, plans/, etc. — so we walk
# recursively.
_WIKI_GLOB = "**/*.md"

# Pull the first ``#`` heading as title; fall back to filename.
_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)

# Body cap so a runaway 10MB markdown file doesn't blow up FTS5
# index memory. Anything past this is silently truncated; the
# title and head-of-file are what FTS5 needs anyway.
_MAX_BODY_CHARS = 200_000


@dataclass(frozen=True)
class WikiSearchHit:
    """One row from a wiki MATCH query."""

    path: str
    title: str
    snippet: str   # FTS5 snippet() output with «...» markers
    rank: float    # BM25; lower = better


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def ensure_wiki_index(conn: sqlite3.Connection) -> None:
    """Create the FTS5 virtual table + mtime cache if absent.

    Idempotent. Called once at DB init time (open_and_init) and
    safe to call again from update_wiki_index in case the DB was
    created before this migration shipped.
    """
    # FTS5 may be unavailable on heavily-stripped Python builds (e.g.
    # some Alpine variants). Detect at create time so the rest of
    # the agent doesn't try to use a non-existent virtual table.
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5("
            "  path UNINDEXED,"
            "  title,"
            "  body,"
            "  tokenize='porter unicode61'"
            ")"
        )
    except sqlite3.OperationalError as exc:
        # FTS5 missing — log once, leave the rest of the schema alone.
        logger.warning("wiki_search: FTS5 unavailable (%s); search disabled", exc)
        return
    conn.execute(
        "CREATE TABLE IF NOT EXISTS wiki_fts_files ("
        "  path TEXT PRIMARY KEY,"
        "  mtime_ns INTEGER NOT NULL,"
        "  indexed_at TEXT NOT NULL"
        ")"
    )


def fts5_available(conn: sqlite3.Connection) -> bool:
    """Return True iff the FTS5 virtual table exists in this DB."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='wiki_fts'"
    ).fetchone()
    return row is not None


def _extract_title(rel_path: str, body: str) -> str:
    """First ``# heading`` line, else the path's filename stem."""
    m = _TITLE_RE.search(body[:4_000])  # only scan the head
    if m:
        return m.group(1).strip()[:200]
    # Fallback: last path component, without extension.
    stem = rel_path.rsplit("/", 1)[-1]
    if stem.endswith(".md"):
        stem = stem[:-3]
    return stem


def _read_file(p: Path) -> tuple[int, str]:
    """Return (mtime_ns, body[truncated]) or raise."""
    stat = p.stat()
    body = p.read_text(encoding="utf-8", errors="replace")
    if len(body) > _MAX_BODY_CHARS:
        body = body[:_MAX_BODY_CHARS]
    return stat.st_mtime_ns, body


def update_wiki_index(
    conn: sqlite3.Connection, wiki_dir: Path,
) -> dict[str, int]:
    """Incrementally refresh the FTS5 index from disk.

    Returns counts: ``{added, updated, deleted, unchanged}``.
    No-op if FTS5 is unavailable.
    """
    ensure_wiki_index(conn)
    if not fts5_available(conn):
        return {"added": 0, "updated": 0, "deleted": 0, "unchanged": 0}
    if not wiki_dir.exists() or not wiki_dir.is_dir():
        # Wipe the cache + FTS rows so a deleted wiki dir doesn't
        # leave phantom hits.
        deleted = conn.execute("SELECT COUNT(*) AS n FROM wiki_fts_files").fetchone()["n"]
        conn.execute("DELETE FROM wiki_fts")
        conn.execute("DELETE FROM wiki_fts_files")
        return {"added": 0, "updated": 0, "deleted": int(deleted), "unchanged": 0}

    # Build current snapshot from disk.
    on_disk: dict[str, tuple[int, str]] = {}  # rel_path -> (mtime_ns, body)
    for p in wiki_dir.rglob("*.md"):
        if not p.is_file():
            continue
        try:
            rel = str(p.relative_to(wiki_dir))
        except ValueError:
            continue
        try:
            on_disk[rel] = _read_file(p)
        except OSError as exc:
            logger.warning("wiki_search: skipping %s (%s)", rel, exc)

    # Pull current cache.
    cached = {
        r["path"]: int(r["mtime_ns"])
        for r in conn.execute("SELECT path, mtime_ns FROM wiki_fts_files").fetchall()
    }

    added = 0
    updated = 0
    unchanged = 0
    now = _utc_now_iso()

    for rel, (mtime_ns, body) in on_disk.items():
        prev = cached.get(rel)
        if prev == mtime_ns:
            unchanged += 1
            continue
        title = _extract_title(rel, body)
        if prev is None:
            conn.execute(
                "INSERT INTO wiki_fts(path, title, body) VALUES (?, ?, ?)",
                (rel, title, body),
            )
            conn.execute(
                "INSERT INTO wiki_fts_files(path, mtime_ns, indexed_at) VALUES (?, ?, ?)",
                (rel, mtime_ns, now),
            )
            added += 1
        else:
            conn.execute("DELETE FROM wiki_fts WHERE path = ?", (rel,))
            conn.execute(
                "INSERT INTO wiki_fts(path, title, body) VALUES (?, ?, ?)",
                (rel, title, body),
            )
            conn.execute(
                "UPDATE wiki_fts_files SET mtime_ns = ?, indexed_at = ? WHERE path = ?",
                (mtime_ns, now, rel),
            )
            updated += 1

    # Detect deletes: rows in cache that aren't on disk.
    deleted = 0
    for rel in list(cached.keys()):
        if rel not in on_disk:
            conn.execute("DELETE FROM wiki_fts WHERE path = ?", (rel,))
            conn.execute("DELETE FROM wiki_fts_files WHERE path = ?", (rel,))
            deleted += 1

    if added or updated or deleted:
        conn.commit()
    return {
        "added": added,
        "updated": updated,
        "deleted": deleted,
        "unchanged": unchanged,
    }


def search_wiki(
    conn: sqlite3.Connection, query: str, *, limit: int = 8,
) -> list[WikiSearchHit]:
    """Run an FTS5 MATCH and return ranked hits with snippets.

    ``query`` is an FTS5 query string — supports phrase quoting,
    column filters (``title:foo``), prefix (``foo*``), AND/OR/NOT.
    Empty query → empty list (FTS5 would raise OperationalError).
    """
    q = (query or "").strip()
    if not q:
        return []
    if not fts5_available(conn):
        return []
    try:
        rows = conn.execute(
            "SELECT path, title, "
            "  snippet(wiki_fts, 2, '«', '»', '...', 16) AS sn, "
            "  bm25(wiki_fts) AS rk "
            "FROM wiki_fts "
            "WHERE wiki_fts MATCH ? "
            "ORDER BY rk "
            "LIMIT ?",
            (q, max(1, min(50, int(limit)))),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        logger.warning("wiki_search: query %r failed (%s)", q, exc)
        return []
    return [
        WikiSearchHit(
            path=r["path"], title=r["title"] or "",
            snippet=r["sn"] or "", rank=float(r["rk"] or 0.0),
        )
        for r in rows
    ]


def wiki_index_stats(conn: sqlite3.Connection) -> dict[str, int | str]:
    """Counters + diagnostics for the operator / dashboard."""
    if not fts5_available(conn):
        return {"available": False, "indexed_files": 0}
    row = conn.execute(
        "SELECT COUNT(*) AS n, MAX(indexed_at) AS last FROM wiki_fts_files"
    ).fetchone()
    return {
        "available": True,
        "indexed_files": int(row["n"] or 0),
        "last_indexed_at": row["last"] or "",
    }


__all__ = [
    "WikiSearchHit",
    "ensure_wiki_index",
    "fts5_available",
    "search_wiki",
    "update_wiki_index",
    "wiki_index_stats",
]
