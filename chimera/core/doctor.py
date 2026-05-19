"""Boot-time configuration validator (ADR 0020, v3.6).

``chimera doctor`` runs the same checks the HTTP server runs at startup.
Each check returns a ``CheckResult`` with status ``ok`` | ``warn`` |
``error``. ``run_checks`` is pure; ``assert_no_errors`` is the noisy
entry point used by ``serve``.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # "ok" | "warn" | "error"
    message: str


class ConfigError(RuntimeError):
    """Raised by :func:`assert_no_errors` when any check is ``error``."""


def _check_writable_dir(name: str, path: Path) -> CheckResult:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return CheckResult(name, "error", f"cannot create {path}: {exc}")
    if not os.access(path, os.W_OK):
        return CheckResult(name, "error", f"{path} is not writable")
    return CheckResult(name, "ok", str(path))


def _check_provider_keys() -> list[CheckResult]:
    out: list[CheckResult] = []
    for env in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
        v = os.environ.get(env, "").strip()
        if v:
            out.append(CheckResult(env, "ok", "set"))
        else:
            out.append(CheckResult(env, "warn", "unset — provider unavailable"))
    return out


def _check_json_env(name: str) -> CheckResult:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return CheckResult(name, "ok", "unset (optional)")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return CheckResult(name, "error", f"invalid JSON: {exc}")
    if not isinstance(parsed, dict):
        return CheckResult(name, "error", "must be a JSON object")
    return CheckResult(name, "ok", f"{len(parsed)} entr(ies)")


def _check_sqlite(state_dir: Path) -> CheckResult:
    path = state_dir / "chimera.db"
    try:
        conn = sqlite3.connect(str(path))
        conn.execute("SELECT 1").fetchone()
        conn.close()
    except sqlite3.Error as exc:
        return CheckResult("chimera.db", "error", f"cannot open {path}: {exc}")
    return CheckResult("chimera.db", "ok", str(path))


def _check_graph_dependency() -> CheckResult:
    try:
        import kuzu  # noqa: F401
    except ImportError as exc:
        return CheckResult("graph: kuzu", "error", f"import failed: {exc}")
    return CheckResult("graph: kuzu", "ok", "importable")


def _check_http_server_token() -> CheckResult:
    """If both single-token and per-peer-token are empty, that's a warn —
    HTTP server logs the same warning and accepts anonymous, but operators
    deploying behind a reverse proxy may want to know."""
    single = os.environ.get("CHIMERA_PEER_TOKEN", "").strip()
    multi = os.environ.get("CHIMERA_PEER_TOKENS", "").strip()
    if single or multi:
        return CheckResult("http auth", "ok", "token configured")
    return CheckResult(
        "http auth", "warn",
        "neither CHIMERA_PEER_TOKEN nor CHIMERA_PEER_TOKENS set; "
        "HTTP server will allow anonymous (local-dev only)",
    )


def run_checks() -> list[CheckResult]:
    """Run every check. Pure: writes nothing (beyond creating state/mind dirs)."""
    state_dir = Path(os.environ.get("CHIMERA_STATE_DIR", "state"))
    mind_dir = Path(os.environ.get("CHIMERA_MIND_DIR", "mind"))
    results: list[CheckResult] = [
        _check_writable_dir("state_dir", state_dir),
        _check_writable_dir("mind_dir", mind_dir),
        _check_sqlite(state_dir),
        _check_graph_dependency(),
        _check_json_env("CHIMERA_MCP_SERVERS"),
        _check_json_env("CHIMERA_PEER_TOKENS"),
        _check_http_server_token(),
        *_check_provider_keys(),
    ]
    return results


def assert_no_errors(results: list[CheckResult] | None = None) -> list[CheckResult]:
    """Raise :class:`ConfigError` if any check is ``error``. Logs warnings."""
    results = results or run_checks()
    errors = [r for r in results if r.status == "error"]
    if errors:
        lines = [f"  - {r.name}: {r.message}" for r in errors]
        raise ConfigError(
            "chimera config validation failed:\n" + "\n".join(lines)
        )
    for r in results:
        if r.status == "warn":
            logger.warning("config check %s: %s", r.name, r.message)
    return results
