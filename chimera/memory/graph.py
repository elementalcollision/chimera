"""LadybugDB graph store (v2.10) — embedded Cypher over Chimera's state.

Per [ADR 0015]. SQLite remains the source of truth for ``entities``,
``entity_transitions``, ``mutations``, ``api_calls``. This module
maintains a **derived projection** of that data — plus filesystem-only
edges (peer-trust, skill-deps, wiki cross-refs) — in a Kuzu / Ladybug
database under ``state/chimera.graph/``.

Re-buildable from scratch: ``GraphStore.rebuild_from_sqlite(conn)`` is
idempotent. Any SQLite schema migration invalidates the graph and the
next ``rebuild`` rebuilds it.

The PyPI package name is currently ``kuzu`` while LadybugDB ships
binary compatibility during its rebrand transition. We pin to
``kuzu>=0.10`` (the last common API surface) and document the rename
in ADR 0015.
"""

from __future__ import annotations

import ast
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import kuzu

logger = logging.getLogger(__name__)


GRAPH_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class GraphQueryResult:
    columns: list[str]
    rows: list[list[Any]]


_NODE_TABLES = [
    # All primary keys are STRING for portability with our UUIDs / names.
    "CREATE NODE TABLE IF NOT EXISTS Entity("
    " id STRING, kind STRING, name STRING, kfm_state STRING,"
    " state_entered_at_cycle INT64, created_at STRING,"
    " PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS Mutation("
    " id INT64, type STRING, status STRING, reason STRING, created_at STRING,"
    " PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS ApiCall("
    " id INT64, cycle INT64, provider STRING, model_id STRING,"
    " finish_reason STRING, created_at STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE IF NOT EXISTS Peer("
    " agent_id STRING, version STRING, host STRING, registered_at STRING,"
    " PRIMARY KEY(agent_id))",
    "CREATE NODE TABLE IF NOT EXISTS Skill("
    " name STRING, source_path STRING, PRIMARY KEY(name))",
    "CREATE NODE TABLE IF NOT EXISTS WikiDoc("
    " path STRING, PRIMARY KEY(path))",
]

_REL_TABLES = [
    "CREATE REL TABLE IF NOT EXISTS TRANSITIONED_TO("
    " FROM Entity TO Entity,"
    " from_state STRING, to_state STRING, operator_type STRING,"
    " reason STRING, cycle INT64, created_at STRING)",
    "CREATE REL TABLE IF NOT EXISTS PROPOSED(FROM Mutation TO Entity)",
    "CREATE REL TABLE IF NOT EXISTS ACTIVATED(FROM Mutation TO Skill)",
    "CREATE REL TABLE IF NOT EXISTS TRUSTED("
    " FROM Peer TO Peer, drift_score DOUBLE, verdict STRING, recorded_at STRING)",
    "CREATE REL TABLE IF NOT EXISTS DEPENDS_ON(FROM Skill TO Skill)",
    "CREATE REL TABLE IF NOT EXISTS USES_TOOL(FROM Skill TO Entity)",
    "CREATE REL TABLE IF NOT EXISTS REFERENCES(FROM WikiDoc TO WikiDoc)",
]


def default_graph_dir() -> Path:
    state_dir = Path(os.environ.get("CHIMERA_STATE_DIR", "state"))
    return state_dir / "chimera.graph"


class GraphStore:
    """Thin wrapper over kuzu.Database + Connection."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_graph_dir()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = kuzu.Database(str(self.path))
        self._conn = kuzu.Connection(self._db)

    @property
    def connection(self) -> kuzu.Connection:
        return self._conn

    def close(self) -> None:
        # Kuzu cleans up on GC; no explicit close. Method is here so callers
        # that mirror SQLite usage don't have to special-case it.
        pass

    def init_schema(self) -> None:
        """Idempotent: create node + rel tables if missing."""
        for stmt in _NODE_TABLES + _REL_TABLES:
            self._conn.execute(stmt)

    def query(self, cypher: str, *, params: dict[str, Any] | None = None) -> GraphQueryResult:
        """Execute Cypher and return a structured result."""
        result = self._conn.execute(cypher, parameters=params)
        columns = list(result.get_column_names())
        rows: list[list[Any]] = []
        while result.has_next():
            rows.append(list(result.get_next()))
        return GraphQueryResult(columns=columns, rows=rows)

    # ── projection helpers ───────────────────────────────────

    def clear_all(self) -> None:
        """Truncate every node + rel table. Used by rebuild."""
        # Kuzu doesn't have TRUNCATE; we DELETE in dependency order.
        for rel in [
            "TRANSITIONED_TO", "PROPOSED", "ACTIVATED",
            "TRUSTED", "DEPENDS_ON", "USES_TOOL", "REFERENCES",
        ]:
            try:
                self._conn.execute(f"MATCH ()-[r:{rel}]->() DELETE r")
            except Exception:
                pass
        for node in ["Entity", "Mutation", "ApiCall", "Peer", "Skill", "WikiDoc"]:
            try:
                self._conn.execute(f"MATCH (n:{node}) DETACH DELETE n")
            except Exception:
                pass

    def rebuild_from_sqlite(self, sqlite_conn) -> dict[str, int]:
        """Project SQLite rows into the graph. Returns counts per node/rel type."""
        self.init_schema()
        self.clear_all()
        counts: dict[str, int] = {}

        # Entities.
        entity_rows = sqlite_conn.execute(
            "SELECT id, kind, name, kfm_state, state_entered_at_cycle, created_at FROM entities"
        ).fetchall()
        for r in entity_rows:
            self._conn.execute(
                "CREATE (e:Entity {id: $id, kind: $kind, name: $name, "
                "kfm_state: $st, state_entered_at_cycle: $cyc, created_at: $ts})",
                parameters={
                    "id": r["id"], "kind": r["kind"], "name": r["name"],
                    "st": r["kfm_state"], "cyc": int(r["state_entered_at_cycle"]),
                    "ts": r["created_at"],
                },
            )
        counts["Entity"] = len(entity_rows)

        # Mutations.
        mut_rows = sqlite_conn.execute(
            "SELECT id, type, status, reason, created_at FROM mutations"
        ).fetchall()
        for r in mut_rows:
            self._conn.execute(
                "CREATE (m:Mutation {id: $id, type: $type, status: $st, "
                "reason: $reason, created_at: $ts})",
                parameters={
                    "id": int(r["id"]), "type": r["type"], "st": r["status"],
                    "reason": r["reason"] or "", "ts": r["created_at"],
                },
            )
        counts["Mutation"] = len(mut_rows)

        # ApiCalls — last 1000 only to keep the graph svelte.
        api_rows = sqlite_conn.execute(
            "SELECT id, cycle, provider, model_id, finish_reason, created_at "
            "FROM api_calls ORDER BY id DESC LIMIT 1000"
        ).fetchall()
        for r in api_rows:
            self._conn.execute(
                "CREATE (a:ApiCall {id: $id, cycle: $cyc, provider: $p, "
                "model_id: $m, finish_reason: $fr, created_at: $ts})",
                parameters={
                    "id": int(r["id"]), "cyc": int(r["cycle"]), "p": r["provider"],
                    "m": r["model_id"], "fr": r["finish_reason"] or "",
                    "ts": r["created_at"],
                },
            )
        counts["ApiCall"] = len(api_rows)

        # TRANSITIONED_TO edges (entity self-loops in the lifecycle).
        trans_rows = sqlite_conn.execute(
            "SELECT entity_id, from_state, to_state, operator_type, reason, "
            "cycle, created_at FROM entity_transitions"
        ).fetchall()
        for r in trans_rows:
            # KFM transitions are A→A on the same entity over time;
            # for a useful provenance graph we connect the entity to itself
            # with one edge per transition.
            self._conn.execute(
                "MATCH (e:Entity {id: $eid}) "
                "CREATE (e)-[t:TRANSITIONED_TO {"
                " from_state: $fs, to_state: $ts, operator_type: $op,"
                " reason: $reason, cycle: $cyc, created_at: $at}]->(e)",
                parameters={
                    "eid": r["entity_id"], "fs": r["from_state"],
                    "ts": r["to_state"], "op": r["operator_type"],
                    "reason": r["reason"] or "", "cyc": int(r["cycle"]),
                    "at": r["created_at"],
                },
            )
        counts["TRANSITIONED_TO"] = len(trans_rows)

        # Peers (from filesystem registry).
        peer_count = 0
        try:
            from ..a2a import list_peers
            for p in list_peers():
                self._conn.execute(
                    "CREATE (p:Peer {agent_id: $id, version: $v, host: $h, "
                    "registered_at: $ra})",
                    parameters={
                        "id": p.agent_id, "v": p.version, "h": p.host,
                        "ra": p.registered_at,
                    },
                )
                peer_count += 1
        except Exception:
            logger.exception("failed to project peers; continuing")
        counts["Peer"] = peer_count

        counts.update(self._project_skills_and_wiki())
        counts.update(self._project_mutation_edges(sqlite_conn))
        counts.update(self._project_trust_edges())
        return counts

    def _project_mutation_edges(self, sqlite_conn) -> dict[str, int]:
        """PROPOSED (Mutation→Entity) + ACTIVATED (Mutation→Skill)."""
        import json

        counts = {"PROPOSED": 0, "ACTIVATED": 0}
        entity_by_name: dict[str, str] = {}
        for row in sqlite_conn.execute("SELECT id, name FROM entities").fetchall():
            entity_by_name[row["name"]] = row["id"]

        mut_rows = sqlite_conn.execute(
            "SELECT id, type, status, payload FROM mutations"
        ).fetchall()
        for r in mut_rows:
            try:
                payload = json.loads(r["payload"]) if r["payload"] else {}
            except json.JSONDecodeError:
                payload = {}
            target_name = None
            for key in ("entity_name", "target", "name"):
                v = payload.get(key)
                if isinstance(v, str) and v in entity_by_name:
                    target_name = v
                    break
            if target_name is not None:
                self._conn.execute(
                    "MATCH (m:Mutation {id: $mid}), (e:Entity {id: $eid}) "
                    "CREATE (m)-[:PROPOSED]->(e)",
                    parameters={"mid": int(r["id"]), "eid": entity_by_name[target_name]},
                )
                counts["PROPOSED"] += 1
            if (
                r["type"] == "skill_proposal"
                and r["status"] == "applied"
                and isinstance(payload.get("name"), str)
            ):
                self._conn.execute(
                    "MATCH (m:Mutation {id: $mid}), (s:Skill {name: $sn}) "
                    "CREATE (m)-[:ACTIVATED]->(s)",
                    parameters={"mid": int(r["id"]), "sn": payload["name"]},
                )
                counts["ACTIVATED"] += 1
        return counts

    def _project_trust_edges(self) -> dict[str, int]:
        """TRUSTED edges from peer_trust_journal — one Self→Peer edge per latest decision."""
        counts = {"TRUSTED": 0}
        try:
            from ..a2a import AgentIdentity, latest_per_peer, list_peers
        except Exception:
            return counts

        latest = latest_per_peer()
        if not latest:
            return counts

        self_id = AgentIdentity().agent_id
        existing = {p.agent_id for p in list_peers()}
        if self_id not in existing:
            try:
                self._conn.execute(
                    "CREATE (p:Peer {agent_id: $id, version: $v, host: $h, "
                    "registered_at: $ra})",
                    parameters={"id": self_id, "v": "self", "h": "self", "ra": ""},
                )
            except Exception:
                pass

        peer_id_by_name: dict[str, str] = {}
        for p in list_peers():
            peer_id_by_name[p.agent_id] = p.agent_id
            for key in (p.agent_id.split(":")[-1], p.agent_id):
                peer_id_by_name.setdefault(key, p.agent_id)

        for peer_name, rec in latest.items():
            target_id = peer_id_by_name.get(peer_name)
            if target_id is None:
                continue
            self._conn.execute(
                "MATCH (a:Peer {agent_id: $a}), (b:Peer {agent_id: $b}) "
                "CREATE (a)-[:TRUSTED {drift_score: $d, verdict: $v, recorded_at: $t}]->(b)",
                parameters={
                    "a": self_id,
                    "b": target_id,
                    "d": float(rec.drift_score) if rec.drift_score is not None else 0.0,
                    "v": rec.decision,
                    "t": rec.recorded_at,
                },
            )
            counts["TRUSTED"] += 1
        return counts

    def _project_skills_and_wiki(
        self,
        *,
        skills_dir: Path | None = None,
        mind_dir: Path | None = None,
    ) -> dict[str, int]:
        """Project filesystem-only edges: skill deps, tool uses, wiki refs."""
        from ..skills import dynamic_skills_dir

        skills_dir = (skills_dir or dynamic_skills_dir()).resolve()
        mind_dir = (mind_dir or Path("mind")).resolve()

        counts = {"Skill": 0, "WikiDoc": 0, "DEPENDS_ON": 0, "USES_TOOL": 0, "REFERENCES": 0}

        # Skills: one node per .py module (excluding __init__).
        skill_files: list[Path] = [
            p for p in skills_dir.glob("*.py") if p.stem != "__init__"
        ]
        skill_names = {p.stem for p in skill_files}
        for p in skill_files:
            self._conn.execute(
                "CREATE (s:Skill {name: $n, source_path: $sp})",
                parameters={"n": p.stem, "sp": str(p)},
            )
        counts["Skill"] = len(skill_files)

        # Known tool names from the static registry (for USES_TOOL edges).
        try:
            from ..tools import ToolRegistry, register_core_tools

            reg = ToolRegistry()
            register_core_tools(reg)
            tool_names = set(reg.names())
        except Exception:
            tool_names = set()

        # AST scan each skill for imports (DEPENDS_ON) and tool calls (USES_TOOL).
        for p in skill_files:
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            deps: set[str] = set()
            uses: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    if node.module.startswith("chimera.tools.dynamic"):
                        for n in node.names:
                            if n.name in skill_names and n.name != p.stem:
                                deps.add(n.name)
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if node.value in tool_names:
                        uses.add(node.value)
            for d in deps:
                self._conn.execute(
                    "MATCH (a:Skill {name: $a}), (b:Skill {name: $b}) "
                    "CREATE (a)-[:DEPENDS_ON]->(b)",
                    parameters={"a": p.stem, "b": d},
                )
                counts["DEPENDS_ON"] += 1
            for t in uses:
                self._conn.execute(
                    "MATCH (s:Skill {name: $s}), (e:Entity {name: $t, kind: 'tool'}) "
                    "CREATE (s)-[:USES_TOOL]->(e)",
                    parameters={"s": p.stem, "t": t},
                )
                # Edge may not be created if the tool isn't in the Entity table;
                # count optimistically — query result tells us the real count.
                counts["USES_TOOL"] += 1

        # WikiDocs + REFERENCES from markdown links.
        md_link_re = re.compile(r"\[[^\]]*\]\(([^)]+\.md)(?:#[^)]*)?\)")
        if mind_dir.exists():
            md_files = [p for p in mind_dir.rglob("*.md")]
            doc_paths = {str(p.relative_to(mind_dir)) for p in md_files}
            for p in md_files:
                self._conn.execute(
                    "CREATE (d:WikiDoc {path: $p})",
                    parameters={"p": str(p.relative_to(mind_dir))},
                )
            counts["WikiDoc"] = len(md_files)
            for p in md_files:
                rel = str(p.relative_to(mind_dir))
                try:
                    text = p.read_text(encoding="utf-8")
                except OSError:
                    continue
                for m in md_link_re.finditer(text):
                    target_raw = m.group(1)
                    if target_raw.startswith(("http://", "https://")):
                        continue
                    target = str((p.parent / target_raw).resolve().relative_to(mind_dir)) \
                        if (p.parent / target_raw).exists() else target_raw
                    if target in doc_paths and target != rel:
                        self._conn.execute(
                            "MATCH (a:WikiDoc {path: $a}), (b:WikiDoc {path: $b}) "
                            "CREATE (a)-[:REFERENCES]->(b)",
                            parameters={"a": rel, "b": target},
                        )
                        counts["REFERENCES"] += 1

        return counts
