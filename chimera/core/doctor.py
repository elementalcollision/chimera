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


# v4.75: orphan-WAL detection — a SIGKILL'd writer leaves chimera.db-wal
# uncheckpointed. better-sqlite3 (the dashboard) then reads stale pages
# from the main db and reports "file is not a database". The fix is a
# single WAL checkpoint; doctor surfaces it so the operator doesn't
# have to chase the misleading error.
_ORPHAN_WAL_THRESHOLD = 1 * 1024 * 1024  # 1 MiB — normal WAL stays well below


def _has_active_writer(db_path: Path) -> bool:
    """Best-effort: use ``lsof`` to detect any process holding the DB open
    for write. Returns ``False`` if lsof is unavailable or finds nothing."""
    import shutil
    import subprocess
    lsof = shutil.which("lsof")
    if not lsof:
        return False
    try:
        out = subprocess.run(  # noqa: S603
            [lsof, "-Fn", "--", str(db_path)],
            capture_output=True, text=True, timeout=2.0,
        )
    except (subprocess.SubprocessError, OSError):
        return False
    # lsof prints one line per fd holder; non-empty stdout = at least one.
    return bool(out.stdout.strip())


def _check_orphan_wal(state_dir: Path) -> CheckResult:
    db_path = state_dir / "chimera.db"
    wal_path = state_dir / "chimera.db-wal"
    if not wal_path.exists():
        return CheckResult("wal", "ok", "no WAL file")
    size = wal_path.stat().st_size
    if size == 0:
        return CheckResult("wal", "ok", "WAL present but empty")
    if _has_active_writer(db_path):
        return CheckResult(
            "wal", "ok",
            f"WAL {size} bytes; writer is active (normal)",
        )
    if size >= _ORPHAN_WAL_THRESHOLD:
        return CheckResult(
            "wal", "warn",
            f"orphan WAL detected ({size} bytes, no active writer). "
            f"Run `chimera doctor --fix` or "
            f"`sqlite3 {db_path} 'PRAGMA wal_checkpoint(TRUNCATE);'`",
        )
    return CheckResult(
        "wal", "ok",
        f"WAL {size} bytes; below orphan threshold",
    )


def checkpoint_wal(state_dir: Path) -> tuple[bool, str]:
    """Run ``PRAGMA wal_checkpoint(TRUNCATE)`` on the chimera DB.

    Returns ``(ok, message)``. Safe to call even when there is no WAL;
    the pragma is a no-op in that case. Used by ``chimera doctor --fix``
    and by :class:`ChimeraLoop.close` on graceful shutdown.
    """
    db_path = state_dir / "chimera.db"
    if not db_path.exists():
        return True, f"no chimera.db at {db_path}; nothing to do"
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE);").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return False, f"checkpoint failed: {exc}"
    # row format: (busy, log_pages, checkpointed_pages)
    return True, f"checkpoint ok: {row}"


def _check_shell_allowlist() -> CheckResult:
    """v4.80: warn when an advertised shell allow-list entry isn't on PATH.

    Soak v3 saw the model call ``rg`` (in the raw list) only to get
    FileNotFoundError because ripgrep wasn't installed. The shell tool
    now trims the advertised surface at import time; doctor surfaces the
    gap so the operator can install the missing tool or accept the
    trimmed surface explicitly.
    """
    import shutil
    from ..tools.shell import RAW_ALLOWLIST, SAFE_COMMANDS
    missing = sorted(cmd for cmd in RAW_ALLOWLIST if shutil.which(cmd) is None)
    if not missing:
        return CheckResult(
            "shell_allowlist", "ok",
            f"all {len(RAW_ALLOWLIST)} allow-listed tools present on PATH",
        )
    return CheckResult(
        "shell_allowlist", "warn",
        f"missing from PATH: {missing}. Advertised surface trimmed to "
        f"{sorted(SAFE_COMMANDS)}. Install the missing tools or ignore.",
    )


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


def _check_cost_caps(state_dir: Path) -> CheckResult:
    """v4.67 (ADR 0086): preflight cost-state check.

    Reports current 60-minute spend against the rolling-hour cap.
    Returns:
      * ok   — empty DB OR spend < 50% of cap
      * warn — spend ≥ 50% but < 100% of cap (review trend)
      * warn — spend ≥ cap (cap will trip on the next cycle)

    Never returns ``error`` because spend-over-cap is operationally
    expected (the caps trip ACT exits, not preflight failures).
    """
    db_path = state_dir / "chimera.db"
    if not db_path.exists():
        return CheckResult(
            "cost_caps", "ok",
            "no chimera.db yet — caps not yet exercised",
        )
    try:
        from ..memory import open_and_init
        from .budget import (
            cycle_cost_cap_usd,
            rolling_hour_cap_usd,
            rolling_spend_usd,
            task_budget_usd,
        )
        conn = open_and_init(db_path)
        try:
            spend_60m = rolling_spend_usd(conn, minutes=60)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            "cost_caps", "warn",
            f"could not read rolling spend ({exc}); caps may still be active",
        )

    hour_cap = rolling_hour_cap_usd()
    cycle_cap = cycle_cost_cap_usd()
    task_cap = task_budget_usd()
    cap_summary = (
        f"caps: cycle=${cycle_cap:.2f} task=${task_cap:.2f} 60m=${hour_cap:.2f}"
    )

    if hour_cap <= 0:
        return CheckResult(
            "cost_caps", "warn",
            f"rolling-60m cap disabled (CHIMERA_ROLLING_HOUR_CAP_USD=0); {cap_summary}",
        )
    pct = (spend_60m / hour_cap) * 100.0 if hour_cap > 0 else 0.0
    msg = (
        f"60m spend ${spend_60m:.2f} ({pct:.0f}% of ${hour_cap:.2f} cap); "
        f"{cap_summary}"
    )
    if spend_60m >= hour_cap:
        return CheckResult("cost_caps", "warn", f"OVER rolling-60m cap. {msg}")
    if pct >= 50.0:
        return CheckResult("cost_caps", "warn", msg)
    return CheckResult("cost_caps", "ok", msg)


def _check_trust_state(state_dir: Path, mind_dir: Path) -> CheckResult:
    """v4.75: warn when the agent is stuck in observer mode.

    A fresh worktree with no ``state/trust_state.json`` starts at T0
    (LOCKED) and burns cycles in observer mode until auto-promotion fires
    — but auto-promotion needs ≥3600s of dwell, so the agent can spin for
    hours without executing any ACT tasks. This check surfaces that.
    """
    trust_path = state_dir / "trust_state.json"
    heartbeat_path = mind_dir / "HEARTBEAT.md"

    cycle = 0
    if heartbeat_path.exists():
        try:
            text = heartbeat_path.read_text()
            if text.startswith("---"):
                end = text.find("\n---", 3)
                if end > 0:
                    for line in text[3:end].splitlines():
                        if ":" in line:
                            k, _, v = line.partition(":")
                            if k.strip() == "cycle":
                                cycle = int(v.strip() or 0)
                                break
        except (OSError, ValueError):
            cycle = 0

    if not trust_path.exists():
        if cycle >= 5:
            return CheckResult(
                "trust_state", "warn",
                f"no trust_state.json but heartbeat cycle={cycle}; agent is "
                f"at T0 (observer mode). Run `chimera trust promote --tier T1` "
                f"to unlock ACT, or copy state/trust_state.json from main.",
            )
        return CheckResult(
            "trust_state", "ok",
            f"no trust_state.json yet (cycle={cycle}); fresh install.",
        )
    try:
        data = json.loads(trust_path.read_text())
        tier = int(data.get("current_tier", 0))
    except (json.JSONDecodeError, OSError, ValueError, TypeError) as exc:
        return CheckResult(
            "trust_state", "warn",
            f"could not parse {trust_path}: {exc}",
        )
    if tier == 0 and cycle >= 5:
        return CheckResult(
            "trust_state", "warn",
            f"agent is at T0 (LOCKED / observer mode) after {cycle} cycle(s); "
            f"ACT is skipping all tasks. Run `chimera trust promote --tier T1` "
            f"to allow execution, or wait for auto-promotion.",
        )
    return CheckResult(
        "trust_state", "ok",
        f"tier=T{tier}, cycle={cycle}",
    )


def _check_concurrent_soak_runners() -> CheckResult:
    """v4.89: warn when more than one long_cycle_soak_*.sh is alive.

    Soak v6 post-mortem (mind/postmortems/soak-v6-2026-05-22.md Failure A):
    three failed launches shared a hardcoded log path because earlier
    instances survived a partial pkill. The runners now refuse to start
    when a sibling is alive; this check surfaces the leftover state to
    the operator without needing to inspect ps by hand.
    """
    import shutil
    import subprocess
    pgrep = shutil.which("pgrep")
    if not pgrep:
        return CheckResult(
            "soak_runners", "ok",
            "pgrep unavailable; cannot inspect concurrent runners",
        )
    try:
        out = subprocess.run(  # noqa: S603
            [pgrep, "-fl", "long_cycle_(soak|remediation|multi_agent)"],
            capture_output=True, text=True, timeout=2.0,
        )
    except (subprocess.SubprocessError, OSError):
        return CheckResult("soak_runners", "ok", "pgrep failed; skipping")
    lines = [ln for ln in out.stdout.splitlines() if ln.strip()]
    if len(lines) <= 1:
        return CheckResult(
            "soak_runners", "ok",
            f"{len(lines)} long_cycle runner(s) alive",
        )
    return CheckResult(
        "soak_runners", "warn",
        f"{len(lines)} long_cycle runners alive — likely orphaned. "
        f"Stop with `pkill -f long_cycle_` before launching a new soak. "
        f"Running: {[ln.split(None, 1)[0] for ln in lines]}",
    )


def run_checks() -> list[CheckResult]:
    """Run every check. Pure: writes nothing (beyond creating state/mind dirs)."""
    state_dir = Path(os.environ.get("CHIMERA_STATE_DIR", "state"))
    mind_dir = Path(os.environ.get("CHIMERA_MIND_DIR", "mind"))
    results: list[CheckResult] = [
        _check_writable_dir("state_dir", state_dir),
        _check_writable_dir("mind_dir", mind_dir),
        # WAL check runs BEFORE sqlite open: opening the DB auto-rolls a
        # valid WAL forward, which would mask the orphan condition.
        _check_orphan_wal(state_dir),
        _check_sqlite(state_dir),
        _check_graph_dependency(),
        _check_shell_allowlist(),
        _check_json_env("CHIMERA_MCP_SERVERS"),
        _check_json_env("CHIMERA_PEER_TOKENS"),
        _check_http_server_token(),
        _check_cost_caps(state_dir),
        _check_trust_state(state_dir, mind_dir),
        _check_concurrent_soak_runners(),
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
