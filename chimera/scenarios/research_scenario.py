"""Phase 3 checkpoint — end-to-end scenario.

Seeds INBOX with two tasks that each require a different tool ring:

  1. ``http_fetch`` (ring 2) — fetch a public page and report on it
  2. ``code_exec`` (ring 3) — compute something with Python

Runs one cycle live. Both tasks should flip to ``[x]`` if the agent
behaved correctly. Writes a transcript to ``mind/research_scenario_transcript.md``.

Live provider keys must be set; otherwise the scenario reports SKIPPED.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from ..core import ChimeraLoop, CycleReport, LoopConfig
from ..core.mind import HeartbeatState, save_heartbeat
from ..memory import open_and_init


@dataclass
class ScenarioResult:
    transcript_path: Path
    tasks_seen: int
    tasks_completed: int
    api_calls: int
    tool_call_count: int
    skipped: bool = False


_INBOX_SEED = """# Inbox

- [ ] Fetch https://example.com using the http_fetch tool and tell me the value inside the <h1> tag.
- [ ] Use code_exec to compute the SHA-256 hex digest of the byte string b"chimera" and report it.
"""


def _seed_mind(mind_dir: Path) -> None:
    mind_dir.mkdir(parents=True, exist_ok=True)
    (mind_dir / "INBOX.md").write_text(_INBOX_SEED, encoding="utf-8")
    save_heartbeat(
        mind_dir / "HEARTBEAT.md",
        HeartbeatState(cycle=0, session_started_at="2026-05-18T22:00:00+00:00"),
        "",
    )


def _transcript(
    title: str,
    report: CycleReport,
    api_call_rows: list,
) -> str:
    lines = [f"# {title}", "", "_Phase 3 checkpoint — all four tool rings available._", ""]
    lines.append("## Cycle outcome\n")
    lines.append(f"- cycle: {report.cycle}")
    lines.append(f"- tasks_seen: {report.tasks_seen}")
    lines.append(f"- tasks_completed (flipped): {report.tasks_completed}")
    lines.append(f"- rotated: {report.rotated}")
    if report.drift_decision is not None:
        d = report.drift_decision
        lines.append(f"- drift decision: **{d.action.value}** — {d.reason}")
    lines.append("")
    lines.append("## Phase log\n")
    for entry in report.phase_log:
        lines.append(f"- {entry}")
    lines.append("")
    lines.append("## API calls this cycle\n")
    if not api_call_rows:
        lines.append("_(none — provider keys not set?)_")
    for r in api_call_rows:
        lines.append(
            f"- cycle {r['cycle']}: {r['provider']} {r['model_id']} → "
            f"{r['finish_reason']}, in={r['input_tokens']}, out={r['output_tokens']}, "
            f"{r['latency_ms']}ms"
        )
    return "\n".join(lines)


async def _arun(mind_dir: Path, state_dir: Path) -> ScenarioResult:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENROUTER_API_KEY")):
        transcript_path = mind_dir / "research_scenario_transcript.md"
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.write_text(
            "# Research scenario — SKIPPED\n\nNo provider keys set.\n",
            encoding="utf-8",
        )
        return ScenarioResult(
            transcript_path=transcript_path,
            tasks_seen=0,
            tasks_completed=0,
            api_calls=0,
            tool_call_count=0,
            skipped=True,
        )

    _seed_mind(mind_dir)
    config = LoopConfig(mind_dir=mind_dir, state_dir=state_dir)
    loop = ChimeraLoop(config)
    report = await loop.run_one_cycle()

    db_path = state_dir / "chimera.db"
    conn = open_and_init(db_path)
    api_calls = [
        dict(r)
        for r in conn.execute(
            "SELECT cycle, provider, model_id, input_tokens, output_tokens, "
            "latency_ms, finish_reason FROM api_calls WHERE cycle = ? ORDER BY id",
            (report.cycle,),
        ).fetchall()
    ]
    conn.close()
    loop.close()

    transcript = _transcript(
        "Chimera — Phase 3 Research Scenario", report, api_calls
    )
    transcript_path = mind_dir / "research_scenario_transcript.md"
    transcript_path.write_text(transcript, encoding="utf-8")

    tool_calls = sum(
        len(line.split("tools="))[1].split(",")[0].strip() if "tools=" in line else 0
        for line in report.phase_log
        if "ACT:" in line
    ) if False else 0  # avoid clever parsing; just count from results
    # Count from explicit phase log lines.
    tool_calls = 0
    for line in report.phase_log:
        if "ACT:" in line and "tools=" in line:
            try:
                tool_calls += int(line.split("tools=")[1].split(",")[0].strip())
            except (IndexError, ValueError):
                pass

    return ScenarioResult(
        transcript_path=transcript_path,
        tasks_seen=report.tasks_seen,
        tasks_completed=report.tasks_completed,
        api_calls=len(api_calls),
        tool_call_count=tool_calls,
    )


def run_research_scenario(mind_dir: Path, state_dir: Path) -> ScenarioResult:
    return asyncio.run(_arun(mind_dir, state_dir))
