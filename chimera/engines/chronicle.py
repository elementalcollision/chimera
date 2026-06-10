"""CHRONICLE.md manager — idempotent per-day sections.

Per Reggio's CHRONICLE pattern: the file groups entries by date, and
re-running an engine for the same day REPLACES that day's named section
rather than appending. Days appear in reverse chronological order
(newest first).

Section shape:

.. code-block:: markdown

    # Chimera — Chronicle

    ## 2026-05-19

    ### Morning Discovery
    ...content...

    ### Midday Curiosity
    ...content...

    ### Evening Reflection
    ...content...

    ## 2026-05-18
    ...
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

_DAY_HEADING_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)
_SECTION_RE = lambda name: re.compile(  # noqa: E731 — small, clear lambda
    rf"^(### {re.escape(name)}\s*\n)(.*?)(?=\n#|\Z)", re.DOTALL | re.MULTILINE
)


def _today_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


class ChronicleManager:
    """Manages mind/CHRONICLE.md with day-grouped, named sub-sections."""

    HEADER = "# Chimera — Chronicle\n\n_Daily synthesis from the engines. Newest day first._\n"

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _read(self) -> str:
        if not self.path.exists():
            return self.HEADER
        return self.path.read_text(encoding="utf-8")

    def _write(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not text.endswith("\n"):
            text += "\n"
        self.path.write_text(text, encoding="utf-8")

    def upsert_section(
        self,
        *,
        section_name: str,
        body: str,
        day: str | None = None,
    ) -> None:
        """Insert-or-replace ``### <section_name>`` under ``## <day>``.

        If the day section doesn't exist, it's created at the top of the
        file (newest-day-first ordering).
        """
        day = day or _today_iso()
        text = self._read()

        # Locate or create the day block.
        day_heading = f"## {day}"
        day_match = re.search(
            rf"^{re.escape(day_heading)}\s*\n", text, re.MULTILINE
        )
        if not day_match:
            # Insert immediately after the file header (before any prior day).
            # Find the first ## occurrence; insert before it (so newest-first).
            first_day = _DAY_HEADING_RE.search(text)
            insert_at = first_day.start() if first_day else len(text)
            new_block = f"{day_heading}\n\n### {section_name}\n\n{body.rstrip()}\n\n"
            text = text[:insert_at] + new_block + text[insert_at:]
            self._write(text)
            return

        # Day exists. Operate within its scope (until the next "## " or EOF).
        day_start = day_match.end()
        next_day = _DAY_HEADING_RE.search(text, day_start)
        day_end = next_day.start() if next_day else len(text)
        block = text[day_start:day_end]

        section_re = _SECTION_RE(section_name)
        section_match = section_re.search(block)
        new_section = f"### {section_name}\n\n{body.rstrip()}\n\n"
        if section_match:
            # Replace just the body of that section.
            new_block = block[: section_match.start()] + new_section + block[section_match.end():]
        else:
            # Append the section at the end of the day's block.
            new_block = block.rstrip("\n") + "\n\n" + new_section
        text = text[:day_start] + new_block + text[day_end:]
        self._write(text)

    def day_section(self, *, day: str | None = None) -> str:
        """Return the raw content under ``## <day>``, or empty string if absent."""
        day = day or _today_iso()
        text = self._read()
        m = re.search(rf"^## {re.escape(day)}\s*\n", text, re.MULTILINE)
        if not m:
            return ""
        next_day = _DAY_HEADING_RE.search(text, m.end())
        end = next_day.start() if next_day else len(text)
        return text[m.end():end].strip()
