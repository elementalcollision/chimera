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
        """Project SQLite rows into the graph. Returns counts per node/rel type.

        v4.23: per-table UNWIND batching — one driver call per table
        instead of one per row. Drops 500-entity rebuild from ~12s to
        sub-second on dev hardware.
        """
        self.init_schema()
        self.clear_all()
        counts: dict[str, int] = {}

        # Entities — single UNWIND.
        entity_rows = sqlite_conn.execute(
            "SELECT id, kind, name, kfm_state, state_entered_at_cycle, created_at FROM entities"
        ).fetchall()
        if entity_rows:
            payload = [
                {
                    "id": r["id"], "kind": r["kind"], "name": r["name"],
                    "st": r["kfm_state"],
                    "cyc": int(r["state_entered_at_cycle"]),
                    "ts": r["created_at"],
                }
                for r in entity_rows
            ]
            self._conn.execute(
                "UNWIND $rows AS row "
                "CREATE (:Entity {id: row.id, kind: row.kind, name: row.name, "
                "kfm_state: row.st, state_entered_at_cycle: row.cyc, "
                "created_at: row.ts})",
                parameters={"rows": payload},
            )
        counts["Entity"] = len(entity_rows)

        # Mutations — single UNWIND.
        mut_rows = sqlite_conn.execute(
            "SELECT id, type, status, reason, created_at FROM mutations"
        ).fetchall()
        if mut_rows:
            payload = [
                {
                    "id": int(r["id"]), "type": r["type"], "st": r["status"],
                    "reason": r["reason"] or "", "ts": r["created_at"],
                }
                for r in mut_rows
            ]
            self._conn.execute(
                "UNWIND $rows AS row "
                "CREATE (:Mutation {id: row.id, type: row.type, status: row.st, "
                "reason: row.reason, created_at: row.ts})",
                parameters={"rows": payload},
            )
        counts["Mutation"] = len(mut_rows)

        # ApiCalls — last 1000 only to keep the graph svelte.
        api_rows = sqlite_conn.execute(
            "SELECT id, cycle, provider, model_id, finish_reason, created_at "
            "FROM api_calls ORDER BY id DESC LIMIT 1000"
        ).fetchall()
        if api_rows:
            payload = [
                {
                    "id": int(r["id"]), "cyc": int(r["cycle"]),
                    "p": r["provider"], "m": r["model_id"],
                    "fr": r["finish_reason"] or "", "ts": r["created_at"],
                }
                for r in api_rows
            ]
            self._conn.execute(
                "UNWIND $rows AS row "
                "CREATE (:ApiCall {id: row.id, cycle: row.cyc, provider: row.p, "
                "model_id: row.m, finish_reason: row.fr, created_at: row.ts})",
                parameters={"rows": payload},
            )
        counts["ApiCall"] = len(api_rows)

        # TRANSITIONED_TO edges — single MATCH/UNWIND/CREATE.
        trans_rows = sqlite_conn.execute(
            "SELECT entity_id, from_state, to_state, operator_type, reason, "
            "cycle, created_at FROM entity_transitions"
        ).fetchall()
        if trans_rows:
            payload = [
                {
                    "eid": r["entity_id"], "fs": r["from_state"],
                    "ts": r["to_state"], "op": r["operator_type"],
                    "reason": r["reason"] or "", "cyc": int(r["cycle"]),
                    "at": r["created_at"],
                }
                for r in trans_rows
            ]
            self._conn.execute(
                "UNWIND $rows AS row "
                "MATCH (e:Entity {id: row.eid}) "
                "CREATE (e)-[:TRANSITIONED_TO {"
                " from_state: row.fs, to_state: row.ts, operator_type: row.op,"
                " reason: row.reason, cycle: row.cyc, created_at: row.at}]->(e)",
                parameters={"rows": payload},
            )
        counts["TRANSITIONED_TO"] = len(trans_rows)

        # Peers (from filesystem registry).
        peer_count = 0
        try:
            from ..a2a import list_peers
            peers = list(list_peers())
            if peers:
                payload = [
                    {
                        "id": p.agent_id, "v": p.version, "h": p.host,
                        "ra": p.registered_at,
                    }
                    for p in peers
                ]
                self._conn.execute(
                    "UNWIND $rows AS row "
                    "CREATE (:Peer {agent_id: row.id, version: row.v, "
                    "host: row.h, registered_at: row.ra})",
                    parameters={"rows": payload},
                )
            peer_count = len(peers)
        except Exception:
            logger.exception("failed to project peers; continuing")
        counts["Peer"] = peer_count

        counts.update(self._project_skills_and_wiki())
        counts.update(self._project_mutation_edges(sqlite_conn))
        counts.update(self._project_trust_edges())
        return counts

    def update_from_sqlite(
        self,
        sqlite_conn,
        *,
        include_mutations: bool = True,
        include_peers: bool = True,
        include_skills_wiki: bool = True,
    ) -> dict[str, int]:
        """v4.31 / v4.35: incremental projection.

        Append-only for the volume-dominant tables:

        - **Entity**: diff graph ids vs SQLite, UNWIND only the missing.
        - **TRANSITIONED_TO**: diff (entity_id, cycle, from_state,
          to_state) keys, UNWIND only the missing.

        Replace-in-place for the mutating tables (v4.35):

        - **Mutation** + **PROPOSED** + **ACTIVATED**: detach-delete all
          :Mutation nodes (cheap — small table) then re-project from
          SQLite. Captures status flips (pending → applied) without
          a full clear+rebuild.
        - **Peer** + **TRUSTED**: same shape — detach-delete + re-project
          from the filesystem registry.

        Skills, WikiDocs, DEPENDS_ON, USES_TOOL, REFERENCES are NOT
        touched here — those are filesystem-scan-heavy and change
        rarely. Operator runs ``chimera graph rebuild`` when those
        need to refresh.

        Returns counts of rows **added or replaced** per table.
        Idempotent — running with no SQLite changes adds zero entities
        and zero new transitions, and re-creates the same mutation/peer
        rows in place.
        """
        self.init_schema()
        counts: dict[str, int] = {"Entity": 0, "TRANSITIONED_TO": 0}

        # ── Entity diff ──────────────────────────────────────
        existing_ids: set[str] = {
            str(row[0])
            for row in self.query("MATCH (e:Entity) RETURN e.id").rows
        }

        entity_rows = sqlite_conn.execute(
            "SELECT id, kind, name, kfm_state, state_entered_at_cycle, created_at "
            "FROM entities"
        ).fetchall()
        new_entities = [r for r in entity_rows if r["id"] not in existing_ids]
        if new_entities:
            payload = [
                {
                    "id": r["id"], "kind": r["kind"], "name": r["name"],
                    "st": r["kfm_state"],
                    "cyc": int(r["state_entered_at_cycle"]),
                    "ts": r["created_at"],
                }
                for r in new_entities
            ]
            self._conn.execute(
                "UNWIND $rows AS row "
                "CREATE (:Entity {id: row.id, kind: row.kind, name: row.name, "
                "kfm_state: row.st, state_entered_at_cycle: row.cyc, "
                "created_at: row.ts})",
                parameters={"rows": payload},
            )
            counts["Entity"] = len(new_entities)

        # ── Transition diff ──────────────────────────────────
        # Existing edges keyed by (entity_id, cycle, from_state, to_state).
        existing_edges: set[tuple[str, int, str, str]] = set()
        for row in self.query(
            "MATCH (e:Entity)-[t:TRANSITIONED_TO]->(e) "
            "RETURN e.id, t.cycle, t.from_state, t.to_state"
        ).rows:
            existing_edges.add(
                (str(row[0]), int(row[1]), str(row[2]), str(row[3]))
            )

        trans_rows = sqlite_conn.execute(
            "SELECT entity_id, from_state, to_state, operator_type, reason, "
            "cycle, created_at FROM entity_transitions"
        ).fetchall()
        new_transitions = [
            r for r in trans_rows
            if (
                str(r["entity_id"]),
                int(r["cycle"]),
                str(r["from_state"]),
                str(r["to_state"]),
            ) not in existing_edges
        ]
        if new_transitions:
            payload = [
                {
                    "eid": r["entity_id"], "fs": r["from_state"],
                    "ts": r["to_state"], "op": r["operator_type"],
                    "reason": r["reason"] or "", "cyc": int(r["cycle"]),
                    "at": r["created_at"],
                }
                for r in new_transitions
            ]
            self._conn.execute(
                "UNWIND $rows AS row "
                "MATCH (e:Entity {id: row.eid}) "
                "CREATE (e)-[:TRANSITIONED_TO {"
                " from_state: row.fs, to_state: row.ts, operator_type: row.op,"
                " reason: row.reason, cycle: row.cyc, created_at: row.at}]->(e)",
                parameters={"rows": payload},
            )
            counts["TRANSITIONED_TO"] = len(new_transitions)

        # ── Mutations (v4.35) ─────────────────────────────────
        if include_mutations:
            counts.update(self._replace_mutations(sqlite_conn))
        # ── Peers (v4.35) ────────────────────────────────────
        if include_peers:
            counts.update(self._replace_peers())
        # ── Skills / Wiki (v4.38, mtime-gated) ───────────────
        if include_skills_wiki:
            counts.update(self._incremental_skills_wiki())

        return counts

    # ── v4.38: skill/wiki mtime gate ─────────────────────────

    def _fingerprint_path(self) -> Path:
        # v4.43 fix: newer Kuzu versions store the DB as a single FILE,
        # not a directory. Putting the fingerprint inside ``self.path``
        # tried to write inside the DB file and threw FileExistsError on
        # every cycle. Use a sibling sidecar instead.
        return self.path.with_suffix(self.path.suffix + ".fingerprint")

    def _compute_skills_wiki_fingerprint(
        self,
        skills_dir: Path,
        mind_dir: Path,
    ) -> str:
        """Hash of (filepath, mtime_ns) tuples covering every input to
        the skill/wiki projection. Stable, cheap, no content read."""
        import hashlib

        paths: list[Path] = []
        if skills_dir.exists():
            paths.extend(p for p in skills_dir.glob("*.py") if p.stem != "__init__")
        if mind_dir.exists():
            paths.extend(mind_dir.rglob("*.md"))
        entries: list[tuple[str, int]] = []
        for p in paths:
            try:
                entries.append((str(p), p.stat().st_mtime_ns))
            except OSError:
                continue
        entries.sort()
        h = hashlib.sha1()
        for path, mtime in entries:
            h.update(path.encode("utf-8"))
            h.update(b"\0")
            h.update(str(mtime).encode("ascii"))
            h.update(b"\n")
        return h.hexdigest()

    def _incremental_skills_wiki(self) -> dict[str, int]:
        """Mtime-gated replace-in-place for skills + wiki projections.

        If no skill or mind file has changed since the last projection,
        returns ``{}`` (a true no-op). On change, detach-deletes all
        Skill + WikiDoc nodes (drops DEPENDS_ON/USES_TOOL/REFERENCES
        automatically), re-projects via the existing scanner, and
        writes the fresh fingerprint to disk.
        """
        from ..skills import dynamic_skills_dir
        skills_dir = dynamic_skills_dir().resolve()
        mind_dir = Path("mind").resolve()

        fp_now = self._compute_skills_wiki_fingerprint(skills_dir, mind_dir)
        fp_path = self._fingerprint_path()
        fp_cached: str | None = None
        if fp_path.exists():
            try:
                fp_cached = fp_path.read_text(encoding="utf-8").strip() or None
            except OSError:
                fp_cached = None
        if fp_cached == fp_now:
            return {}

        # Files changed (or no cache): drop existing projection and rescan.
        for node in ("Skill", "WikiDoc"):
            try:
                self._conn.execute(f"MATCH (n:{node}) DETACH DELETE n")
            except Exception:
                logger.exception("failed to clear %s nodes; continuing", node)
        counts = self._project_skills_and_wiki(
            skills_dir=skills_dir, mind_dir=mind_dir,
        )
        # v4.38 fix: fp_path.parent IS the graph dir (already a Kuzu store);
        # `mkdir(exist_ok=True)` still raises FileExistsError on macOS when the
        # target is a regular directory. Use is_dir() guard instead.
        try:
            if not fp_path.parent.is_dir():
                fp_path.parent.mkdir(parents=True, exist_ok=True)
            fp_path.write_text(fp_now, encoding="utf-8")
        except OSError:
            logger.exception("failed to persist skills/wiki fingerprint")
        return counts

    def _replace_mutations(self, sqlite_conn) -> dict[str, int]:
        """v4.35: detach-delete all :Mutation nodes (drops PROPOSED +
        ACTIVATED edges automatically) and re-project from SQLite.

        Cheap because the mutations table is small (operator-approved
        proposals; never thousands). Captures status changes that the
        append-only Entity path can't.
        """
        try:
            self._conn.execute("MATCH (m:Mutation) DETACH DELETE m")
        except Exception:
            logger.exception("failed to clear Mutation nodes; continuing")
            return {"Mutation": 0, "PROPOSED": 0, "ACTIVATED": 0}

        counts: dict[str, int] = {"Mutation": 0, "PROPOSED": 0, "ACTIVATED": 0}
        mut_rows = sqlite_conn.execute(
            "SELECT id, type, status, reason, created_at FROM mutations"
        ).fetchall()
        if mut_rows:
            payload = [
                {
                    "id": int(r["id"]), "type": r["type"], "st": r["status"],
                    "reason": r["reason"] or "", "ts": r["created_at"],
                }
                for r in mut_rows
            ]
            self._conn.execute(
                "UNWIND $rows AS row "
                "CREATE (:Mutation {id: row.id, type: row.type, status: row.st, "
                "reason: row.reason, created_at: row.ts})",
                parameters={"rows": payload},
            )
        counts["Mutation"] = len(mut_rows)
        edge_counts = self._project_mutation_edges(sqlite_conn)
        counts["PROPOSED"] = edge_counts.get("PROPOSED", 0)
        counts["ACTIVATED"] = edge_counts.get("ACTIVATED", 0)
        return counts

    def _replace_peers(self) -> dict[str, int]:
        """v4.35: detach-delete all :Peer nodes + re-project from the
        filesystem registry. Drops TRUSTED edges and re-projects them."""
        try:
            self._conn.execute("MATCH (p:Peer) DETACH DELETE p")
        except Exception:
            logger.exception("failed to clear Peer nodes; continuing")
            return {"Peer": 0, "TRUSTED": 0}

        counts: dict[str, int] = {"Peer": 0, "TRUSTED": 0}
        try:
            from ..a2a import list_peers
            peers = list(list_peers())
            if peers:
                payload = [
                    {
                        "id": p.agent_id, "v": p.version, "h": p.host,
                        "ra": p.registered_at,
                    }
                    for p in peers
                ]
                self._conn.execute(
                    "UNWIND $rows AS row "
                    "CREATE (:Peer {agent_id: row.id, version: row.v, "
                    "host: row.h, registered_at: row.ra})",
                    parameters={"rows": payload},
                )
            counts["Peer"] = len(peers)
        except Exception:
            logger.exception("failed to project peers; continuing")
        counts.update(self._project_trust_edges())
        return counts

    def _project_mutation_edges(self, sqlite_conn) -> dict[str, int]:
        """PROPOSED (Mutation→Entity) + ACTIVATED (Mutation→Skill).

        v4.23: payload parsed in Python, then two UNWIND batches.
        """
        import json

        counts = {"PROPOSED": 0, "ACTIVATED": 0}
        entity_by_name: dict[str, str] = {}
        for row in sqlite_conn.execute("SELECT id, name FROM entities").fetchall():
            entity_by_name[row["name"]] = row["id"]

        mut_rows = sqlite_conn.execute(
            "SELECT id, type, status, payload FROM mutations"
        ).fetchall()
        proposed_rows: list[dict[str, Any]] = []
        activated_rows: list[dict[str, Any]] = []
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
                proposed_rows.append(
                    {"mid": int(r["id"]), "eid": entity_by_name[target_name]}
                )
            if (
                r["type"] == "skill_proposal"
                and r["status"] == "applied"
                and isinstance(payload.get("name"), str)
            ):
                activated_rows.append({"mid": int(r["id"]), "sn": payload["name"]})

        if proposed_rows:
            self._conn.execute(
                "UNWIND $rows AS row "
                "MATCH (m:Mutation {id: row.mid}), (e:Entity {id: row.eid}) "
                "CREATE (m)-[:PROPOSED]->(e)",
                parameters={"rows": proposed_rows},
            )
            counts["PROPOSED"] = len(proposed_rows)
        if activated_rows:
            self._conn.execute(
                "UNWIND $rows AS row "
                "MATCH (m:Mutation {id: row.mid}), (s:Skill {name: row.sn}) "
                "CREATE (m)-[:ACTIVATED]->(s)",
                parameters={"rows": activated_rows},
            )
            counts["ACTIVATED"] = len(activated_rows)
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

        trust_rows: list[dict[str, Any]] = []
        for peer_name, rec in latest.items():
            target_id = peer_id_by_name.get(peer_name)
            if target_id is None:
                continue
            trust_rows.append(
                {
                    "a": self_id,
                    "b": target_id,
                    "d": float(rec.drift_score) if rec.drift_score is not None else 0.0,
                    "v": rec.decision,
                    "t": rec.recorded_at,
                }
            )
        if trust_rows:
            self._conn.execute(
                "UNWIND $rows AS row "
                "MATCH (a:Peer {agent_id: row.a}), (b:Peer {agent_id: row.b}) "
                "CREATE (a)-[:TRUSTED {drift_score: row.d, verdict: row.v, "
                "recorded_at: row.t}]->(b)",
                parameters={"rows": trust_rows},
            )
            counts["TRUSTED"] = len(trust_rows)
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
        if skill_files:
            self._conn.execute(
                "UNWIND $rows AS row "
                "CREATE (:Skill {name: row.n, source_path: row.sp})",
                parameters={
                    "rows": [{"n": p.stem, "sp": str(p)} for p in skill_files]
                },
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
        dep_rows: list[dict[str, Any]] = []
        use_rows: list[dict[str, Any]] = []
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
                dep_rows.append({"a": p.stem, "b": d})
            for t in uses:
                use_rows.append({"s": p.stem, "t": t})

        if dep_rows:
            self._conn.execute(
                "UNWIND $rows AS row "
                "MATCH (a:Skill {name: row.a}), (b:Skill {name: row.b}) "
                "CREATE (a)-[:DEPENDS_ON]->(b)",
                parameters={"rows": dep_rows},
            )
            counts["DEPENDS_ON"] = len(dep_rows)
        if use_rows:
            self._conn.execute(
                "UNWIND $rows AS row "
                "MATCH (s:Skill {name: row.s}), (e:Entity {name: row.t, kind: 'tool'}) "
                "CREATE (s)-[:USES_TOOL]->(e)",
                parameters={"rows": use_rows},
            )
            # Edge may not be created if the tool isn't in the Entity table;
            # count optimistically — query result tells us the real count.
            counts["USES_TOOL"] = len(use_rows)

        # WikiDocs + REFERENCES from markdown links.
        md_link_re = re.compile(r"\[[^\]]*\]\(([^)]+\.md)(?:#[^)]*)?\)")
        if mind_dir.exists():
            md_files = [p for p in mind_dir.rglob("*.md")]
            doc_paths = {str(p.relative_to(mind_dir)) for p in md_files}
            if md_files:
                self._conn.execute(
                    "UNWIND $rows AS row CREATE (:WikiDoc {path: row.p})",
                    parameters={
                        "rows": [
                            {"p": str(p.relative_to(mind_dir))} for p in md_files
                        ]
                    },
                )
            counts["WikiDoc"] = len(md_files)

            ref_rows: list[dict[str, Any]] = []
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
                        ref_rows.append({"a": rel, "b": target})
            if ref_rows:
                self._conn.execute(
                    "UNWIND $rows AS row "
                    "MATCH (a:WikiDoc {path: row.a}), (b:WikiDoc {path: row.b}) "
                    "CREATE (a)-[:REFERENCES]->(b)",
                    parameters={"rows": ref_rows},
                )
                counts["REFERENCES"] = len(ref_rows)

        return counts
