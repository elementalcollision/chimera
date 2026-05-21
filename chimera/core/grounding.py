"""v4.83: source-citation grounding check for synthesis tasks (ADR 0095).

The soak-v4 post-mortem (mind/postmortems/soak-v4-2026-05-20.md, finding
#3) surfaced a fabrication failure mode: an ACT task that asked the
model to "read X and summarise the heuristic" completed in two rounds,
then a downstream synthesis task produced a verdict naming a function
(``should_abort_loop``) that does not exist in the cited file. The
actual function is ``detect_degenerate_loop``. Artifact validation
(v4.79) catches the file-not-written case; it does not catch a
fabricated symbol *inside* a file that was written.

This module adds a cheap grep-based check: when the in-flight task
looks like a synthesis task (verbs: summarise / analyse / verify /
form a verdict) AND names a source file, extract function/class
identifiers from the model's final text and confirm each one appears
verbatim in the cited source file. Symbols that don't appear are
"ungrounded citations".

Heuristic, not perfect. Catches the obvious case: a verdict naming
``should_abort_loop`` when the file only contains
``detect_degenerate_loop``. False positives are filtered by an
allow-list of generic identifiers (the, this, etc.).
"""

from __future__ import annotations

import re
from pathlib import Path

# ── synthesis-task detection ────────────────────────────────────────

_SYNTHESIS_VERB = re.compile(
    r"\b(?:summari[sz]e|summari[sz]ing|analyse|analyze|analyz(?:e|ing)|"
    r"verify|verifying|form\s+a\s+verdict|form\s+the\s+verdict|"
    r"synthesi[sz]e|synthesi[sz]ing|report\s+on|describe\s+(?:the|how)|"
    r"explain\s+(?:the|how|what)|audit\b|review\b|assess\b)",
    re.IGNORECASE,
)

# Source-file references in task text. Restricted to extensions we
# actually want to grep — language sources, not arbitrary paths.
_CITED_FILE = re.compile(
    r"`?([A-Za-z0-9_./-]+?\.(?:py|tsx|ts|jsx|js|rs|go|java|rb|cpp|hpp|c|h))"
    r"(?=`|[^A-Za-z0-9_]|$)"
)


def is_synthesis_task(task_text: str) -> bool:
    """True if the task asks the model to read-and-synthesize."""
    return bool(_SYNTHESIS_VERB.search(task_text))


def extract_cited_source_files(task_text: str) -> list[str]:
    """Return source-file paths the task references."""
    seen: list[str] = []
    for m in _CITED_FILE.finditer(task_text):
        path = m.group(1)
        if path not in seen:
            seen.append(path)
    return seen


# ── symbol extraction ──────────────────────────────────────────────

# Identifiers the model is claiming to have read from a source file.
# Three forms:
#   1. `def name(` / `function name(` / `class Name(` / `class Name:`
#   2. Backticked bare identifier like `should_abort_loop`
#   3. ``method/function `name` ``
_SYMBOL_PATTERNS = (
    # `def name` or `class Name` — bare or inside backticks. Matches the
    # actual code keywords, not the prose word "function". This catches
    # cases like ``the function `def should_abort_loop(history):`` —
    # the inner "def should_abort_loop" yields the real symbol.
    re.compile(r"(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]+)"),
    # Prose form: ``function named `name` `` / ``method called `name` ``.
    re.compile(
        r"(?:function|method|class|helper|routine)\s+"
        r"(?:named\s+|called\s+)?`([A-Za-z_][A-Za-z0-9_]+)`",
        re.IGNORECASE,
    ),
    # Backticked identifier (with optional call parens): `` `name(args)` ``.
    re.compile(r"`([A-Za-z_][A-Za-z0-9_]+)(?:\([^)]*\))?`"),
)

# Skip common English / framework words that happen to backtick-quote.
_SYMBOL_DENYLIST = frozenset({
    "True", "False", "None", "self", "cls", "Any", "args", "kwargs",
    "list", "dict", "set", "str", "int", "float", "bool", "bytes",
    "tuple", "object", "type", "len", "range", "print",
    "tool_use", "tool_result", "user", "assistant", "system",
    "stop", "length", "completed", "True", "result",
})


def extract_cited_symbols(text: str) -> list[str]:
    """Return identifiers the synthesis text names as code symbols."""
    seen: list[str] = []
    for pat in _SYMBOL_PATTERNS:
        for m in pat.finditer(text):
            sym = m.group(1)
            if sym in _SYMBOL_DENYLIST:
                continue
            # Must look like a real code identifier — at least 4 chars,
            # contains underscore or both cases or is camelCase. This
            # filters out backticked English nouns ("file", "code", etc.)
            if len(sym) < 4:
                continue
            has_underscore = "_" in sym
            has_mixed_case = any(c.isupper() for c in sym) and any(c.islower() for c in sym)
            if not (has_underscore or has_mixed_case):
                continue
            if sym not in seen:
                seen.append(sym)
    return seen


# ── grounding check ────────────────────────────────────────────────


def check_citation_grounding(
    source_files: list[str],
    symbols: list[str],
    *,
    base_dir: Path | None = None,
) -> list[str]:
    """Return symbols that do NOT appear verbatim in any source file.

    Conservative: a symbol is "grounded" if it appears as a whole-word
    match in at least one of the cited files. If we can't read any of
    the files, we return an empty list (no false positives from missing
    fixtures).
    """
    if not source_files or not symbols:
        return []
    base = base_dir or Path.cwd()
    haystack_parts: list[str] = []
    for rel in source_files:
        p = base / rel
        if not p.exists() or not p.is_file():
            continue
        try:
            haystack_parts.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    if not haystack_parts:
        return []
    haystack = "\n".join(haystack_parts)
    ungrounded: list[str] = []
    for sym in symbols:
        if not re.search(rf"\b{re.escape(sym)}\b", haystack):
            ungrounded.append(sym)
    return ungrounded


# ── prompt scaffolding (item #2 in v4.83) ──────────────────────────


SYNTHESIS_GROUNDING_GUIDANCE = (
    "## Source-citation discipline (synthesis task)\n"
    "This task asks you to read source file(s) and synthesize a verdict, "
    "summary, or analysis. Before naming any function, method, or class "
    "from a file, you MUST quote 2-3 short verbatim snippets (≤ 4 lines "
    "each) from the file that include the symbol's definition or use "
    "site. Do not name a symbol you have not just quoted. If you cannot "
    "find the relevant snippet on first read, re-read the file before "
    "synthesizing — do not paraphrase from memory or guess based on "
    "naming conventions. Ungrounded citations will be rejected and the "
    "task marked incomplete."
)


def synthesis_guidance_for(task_text: str) -> str:
    """Return per-task prompt extension when this is a synthesis task
    that cites source files. Empty string otherwise."""
    if not is_synthesis_task(task_text):
        return ""
    if not extract_cited_source_files(task_text):
        return ""
    return SYNTHESIS_GROUNDING_GUIDANCE
