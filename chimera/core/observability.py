"""Structured logging + phase-timing helpers (v3.3, ADR 0018).

JSON logging is opt-in via ``CHIMERA_LOG_JSON=1`` so we don't disturb
local dev. ``PhaseTimer`` measures wall-clock per loop phase and emits
a single log record at exit (DEBUG by default, WARNING above budget).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from typing import Iterator


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for k, v in record.__dict__.items():
            if k in payload or k in (
                "args", "msg", "exc_info", "exc_text", "stack_info",
                "created", "msecs", "relativeCreated", "levelname",
                "levelno", "name", "pathname", "filename", "module",
                "funcName", "lineno", "threadName", "thread", "processName",
                "process", "taskName",
            ):
                continue
            try:
                json.dumps(v)
                payload[k] = v
            except (TypeError, ValueError):
                payload[k] = repr(v)
        return json.dumps(payload, sort_keys=False)


def configure_logging(*, json_mode: bool | None = None, level: str | int | None = None) -> None:
    """Idempotently install a root handler. JSON when CHIMERA_LOG_JSON=1."""
    if json_mode is None:
        json_mode = os.environ.get("CHIMERA_LOG_JSON", "").lower() in ("1", "true", "yes")
    if level is None:
        level = os.environ.get("CHIMERA_LOG_LEVEL", "INFO")
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_chimera_managed", False):
            root.removeHandler(h)
    handler = logging.StreamHandler(stream=sys.stderr)
    handler._chimera_managed = True  # type: ignore[attr-defined]
    if json_mode:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
        )
    root.addHandler(handler)
    if isinstance(level, str):
        level = level.upper()
    root.setLevel(level)


@contextmanager
def phase_timer(
    phase: str,
    *,
    logger: logging.Logger | None = None,
    budget_ms: float | None = None,
) -> Iterator[dict[str, float]]:
    """Measure wall-clock around a block. Logs at DEBUG, or WARNING if over budget.

    Yields a dict the caller can inspect after exit: ``{"elapsed_ms": …}``.
    """
    log = logger or logging.getLogger("chimera.phase")
    out: dict[str, float] = {"elapsed_ms": 0.0}
    start = time.perf_counter()
    try:
        yield out
    finally:
        elapsed = (time.perf_counter() - start) * 1000.0
        out["elapsed_ms"] = elapsed
        over_budget = budget_ms is not None and elapsed > budget_ms
        log.log(
            logging.WARNING if over_budget else logging.DEBUG,
            "phase %s done in %.1fms%s",
            phase,
            elapsed,
            f" (budget {budget_ms:.0f}ms)" if over_budget else "",
            extra={"phase": phase, "elapsed_ms": elapsed, "budget_ms": budget_ms},
        )
