"""One-shot: project SQLite + filesystem registry into LadybugDB.

Per ADR 0015. Idempotent — safe to delete state/chimera.graph/ and re-run.

Usage:
    python -m scripts.build_graph
    chimera graph rebuild   # CLI equivalent
"""

from __future__ import annotations

from chimera.core import LoopConfig
from chimera.memory import GraphStore, default_graph_dir, open_and_init


def main() -> int:
    cfg = LoopConfig.from_env()
    conn = open_and_init(cfg.state_dir / "chimera.db")
    store = GraphStore(default_graph_dir())
    counts = store.rebuild_from_sqlite(conn)
    print(f"build_graph: projected into {store.path}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
