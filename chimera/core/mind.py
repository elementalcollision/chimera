"""mind/* file I/O — HEARTBEAT, INBOX, SESSION_LOG.

Per ADR 0003: mind/* is the narrative source of truth; SQLite is the
index. HEARTBEAT.md frontmatter wins on read after restart; the cycle
counter is restored from it, not from the DB.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_INBOX_TASK_RE = re.compile(r"^(\s*)-\s+\[(?P<mark>[ xX])\]\s+(?P<text>.+?)\s*$")
_INBOX_SRC_RE = re.compile(r"<!--\s*src:\s*(?P<src>[\w-]+)\s*-->")


@dataclass
class HeartbeatState:
    """Frontmatter of mind/HEARTBEAT.md."""

    cycle: int = 0
    session_started_at: str | None = None  # ISO 8601 or None
    trust_tier: str = "T0"
    status: str = "dormant"
    model_usage: dict[str, int] = field(
        default_factory=lambda: {"anthropic_calls": 0, "openrouter_calls": 0}
    )
    last_drift_score: float | None = None

    @classmethod
    def from_mapping(cls, data: dict | None) -> HeartbeatState:
        if not data:
            return cls()
        return cls(
            cycle=int(data.get("cycle") or 0),
            session_started_at=data.get("session_started_at"),
            trust_tier=str(data.get("trust_tier") or "T0"),
            status=str(data.get("status") or "dormant"),
            model_usage=dict(
                data.get("model_usage") or {"anthropic_calls": 0, "openrouter_calls": 0}
            ),
            last_drift_score=data.get("last_drift_score"),
        )

    def to_mapping(self) -> dict:
        return {
            "cycle": self.cycle,
            "session_started_at": self.session_started_at,
            "trust_tier": self.trust_tier,
            "status": self.status,
            "model_usage": self.model_usage,
            "last_drift_score": self.last_drift_score,
        }


@dataclass
class InboxTask:
    """One `- [ ]` / `- [x]` line in mind/INBOX.md."""

    text: str
    done: bool
    line_index: int  # 0-based index in the file's lines
    source: str | None = None  # provenance tag from `<!-- src: X -->`; None = operator


def load_heartbeat(path: Path) -> tuple[HeartbeatState, str]:
    """Return (state, body). Body is the markdown after the frontmatter."""
    if not path.exists():
        return HeartbeatState(), ""
    raw = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(raw)
    if not match:
        # No frontmatter — fresh defaults; treat existing content as body.
        return HeartbeatState(), raw
    fm_raw, body = match.group(1), match.group(2)
    data = yaml.safe_load(fm_raw) or {}
    return HeartbeatState.from_mapping(data), body


def save_heartbeat(path: Path, state: HeartbeatState, body: str) -> None:
    """Persist the heartbeat with frontmatter and trailing body."""
    fm = yaml.safe_dump(state.to_mapping(), sort_keys=False, default_flow_style=False)
    text = f"---\n{fm}---\n{body}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def parse_inbox(path: Path) -> list[InboxTask]:
    """Extract `- [ ]` and `- [x]` lines from mind/INBOX.md."""
    if not path.exists():
        return []
    tasks: list[InboxTask] = []
    for idx, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        m = _INBOX_TASK_RE.match(line)
        if not m:
            continue
        text = m.group("text")
        src_match = _INBOX_SRC_RE.search(text)
        tasks.append(
            InboxTask(
                text=text,
                done=m.group("mark").lower() == "x",
                line_index=idx,
                source=src_match.group("src") if src_match else None,
            )
        )
    return tasks


def mark_inbox_tasks_done(path: Path, line_indices: set[int]) -> int:
    """Flip `- [ ]` to `- [x]` for the given line indices. Returns count flipped."""
    if not path.exists() or not line_indices:
        return 0
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    flipped = 0
    for idx in line_indices:
        if idx >= len(lines):
            continue
        m = _INBOX_TASK_RE.match(lines[idx].rstrip("\n"))
        if not m or m.group("mark").lower() == "x":
            continue
        # Preserve indent + trailing newline.
        indent = m.group(1)
        text = m.group("text")
        suffix = "\n" if lines[idx].endswith("\n") else ""
        lines[idx] = f"{indent}- [x] {text}{suffix}"
        flipped += 1
    path.write_text("".join(lines), encoding="utf-8")
    return flipped


def append_session_log(path: Path, entry: str) -> None:
    """Append a single line to mind/SESSION_LOG.md, ensuring the file exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("# Chimera — Session Log\n\n", encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        if not entry.endswith("\n"):
            entry += "\n"
        f.write(entry)


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
