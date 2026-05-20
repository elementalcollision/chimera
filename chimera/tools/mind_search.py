"""v4.61 (ADR 0080) — ``mind_search`` tool.

Exposes the FTS5 wiki index (chimera/memory/wiki_search.py) to the
agent as a callable tool. The agent can search its own
``mind/wiki/`` knowledge before falling back to web_search.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from .dispatch import DispatchContext
from .registry import ToolRegistry, default_registry

logger = logging.getLogger(__name__)


MIND_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "mind_search",
        "description": (
            "Search the agent's own mind/wiki/ knowledge base via SQLite FTS5. "
            "Supports phrase quoting (\"like this\"), prefix (foo*), column "
            "filters (title:foo), and AND/OR/NOT operators. Returns up to "
            "`limit` ranked hits with path, title, and a snippet. Try this "
            "BEFORE web_search — it's free and reflects what the agent "
            "already knows."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "FTS5 query (e.g. `agonistic OR datacenter*`).",
                },
                "limit": {
                    "type": "integer",
                    "description": "How many results to return (default 8, max 20).",
                },
            },
            "required": ["query"],
        },
    },
}


def _state_db_path() -> Path:
    """Resolve the chimera.db path the same way LoopConfig does."""
    import os as _os
    state_dir = _os.environ.get("CHIMERA_STATE_DIR", "state")
    return Path(state_dir) / "chimera.db"


async def mind_search_handler(args: dict[str, Any], context: DispatchContext) -> str:
    """Run an FTS5 MATCH against the wiki index and format the result."""
    from ..memory.wiki_search import search_wiki, fts5_available

    query = args.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    limit_raw = args.get("limit")
    try:
        limit = int(limit_raw) if limit_raw is not None else 8
    except (TypeError, ValueError):
        limit = 8
    limit = max(1, min(20, limit))

    conn = sqlite3.connect(_state_db_path())
    conn.row_factory = sqlite3.Row
    try:
        if not fts5_available(conn):
            return (
                "mind_search: FTS5 index not available in this SQLite build "
                "(or index not yet built). Falling back to no results."
            )
        hits = search_wiki(conn, query, limit=limit)
    finally:
        conn.close()

    if not hits:
        return f"mind_search: 0 results for {query!r}"
    lines: list[str] = [f"mind_search: {len(hits)} result(s) for {query!r}"]
    for i, h in enumerate(hits, start=1):
        # Lower BM25 = better; show as a rounded score for the model.
        lines.append(
            f"\n[{i}] {h.title or '(no title)'}\n"
            f"    mind/wiki/{h.path}  (rank={h.rank:.2f})\n"
            f"    {h.snippet.strip()}"
        )
    return "\n".join(lines)


def register_mind_search(registry: ToolRegistry | None = None) -> None:
    """Idempotent: register mind_search against the given (or default) registry."""
    reg = registry or default_registry()
    reg.register(
        name="mind_search",
        toolset="core",
        schema=MIND_SEARCH_SCHEMA,
        handler=mind_search_handler,
        description="Full-text search over mind/wiki/ via SQLite FTS5.",
        override=True,
    )


__all__ = [
    "MIND_SEARCH_SCHEMA",
    "mind_search_handler",
    "register_mind_search",
]
