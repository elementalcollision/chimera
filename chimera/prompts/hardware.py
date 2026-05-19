"""Hardware + environment probe — feeds the system prompt at runtime.

Per pillar-adaptability.md Pattern 1 (autoresearch ``get_hardware_summary``).
The agent receives a small frontmatter-style block at the top of every
system prompt describing the container it is running inside.
"""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class HardwareSummary:
    platform: str
    cpu_count: int
    mem_bytes: int | None
    disk_state_free_bytes: int | None
    disk_mind_free_bytes: int | None
    env_keys_present: tuple[str, ...]   # names of relevant env vars that are set

    def render(self) -> str:
        gb = lambda n: f"{n / (1024**3):.1f} GB" if n else "?"
        return (
            f"runtime: {self.platform}, {self.cpu_count} CPU, mem={gb(self.mem_bytes)}, "
            f"disk[state]={gb(self.disk_state_free_bytes)} free, "
            f"disk[mind]={gb(self.disk_mind_free_bytes)} free | "
            f"env: {', '.join(self.env_keys_present) or 'none'}"
        )


_RELEVANT_KEYS = (
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "EXA_API_KEY",
    "BRAVE_SEARCH_API_KEY",
    "TAVILY_API_KEY",
    "CHIMERA_MCP_SERVERS",
)


def _mem_total_bytes() -> int | None:
    """Best-effort memory probe. Linux cgroups v2 → cgroups v1 → /proc/meminfo."""
    # cgroups v2
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(path) as f:
                raw = f.read().strip()
            if raw == "max":
                continue
            return int(raw)
        except (FileNotFoundError, PermissionError, ValueError):
            continue
    # /proc/meminfo (Linux host or container without cgroup limit)
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    parts = line.split()
                    return int(parts[1]) * 1024
    except (FileNotFoundError, PermissionError, ValueError):
        pass
    return None


def _disk_free(path: Path | str) -> int | None:
    try:
        return shutil.disk_usage(str(path)).free
    except (FileNotFoundError, PermissionError, OSError):
        return None


def probe() -> HardwareSummary:
    state_dir = Path(os.environ.get("CHIMERA_STATE_DIR", "state"))
    mind_dir = Path(os.environ.get("CHIMERA_MIND_DIR", "mind"))
    env_keys = tuple(k for k in _RELEVANT_KEYS if os.environ.get(k))
    return HardwareSummary(
        platform=f"{platform.system()} {platform.machine()}",
        cpu_count=os.cpu_count() or 1,
        mem_bytes=_mem_total_bytes(),
        disk_state_free_bytes=_disk_free(state_dir),
        disk_mind_free_bytes=_disk_free(mind_dir),
        env_keys_present=env_keys,
    )
