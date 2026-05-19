"""Proposal deduplication — fingerprint + cluster-verb normalisation.

Ported from claude-daemon's ``task_proposals`` per pillar-creativity.md
Pattern 2. Two complementary signals:

- **Fingerprint** — content-word hash. Catches "append lesson to FILE" vs
  "add lesson to FILE" when the underlying intent is the same.
- **Cluster key** — ``(target_basename, canonical_verb)``. Catches verb
  rephrasings even when paths differ in case or surrounding words.
"""

from __future__ import annotations

import hashlib
import re

from .generate import ProposedTask

# Tiny stopword list, expanded enough to keep fingerprints stable across
# common rephrasings. NOT a full NLP stopword set.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "of", "in", "on", "at", "for", "to", "and", "or",
        "with", "via", "by", "using", "use", "this", "that", "these", "those",
        "is", "are", "was", "were", "be", "been", "being", "do", "does", "did",
        "into", "from", "about", "as", "it", "its",
    }
)

# Verb normalisation table — keep small; expand when a real conflation appears.
_CLUSTER_VERB_NORMALISATION: dict[str, str] = {
    "append": "append",
    "add": "append",
    "appended": "append",
    "append_to_file": "append",
    "write": "write",
    "writing": "write",
    "wrote": "write",
    "create": "create",
    "creating": "create",
    "make": "create",
    "edit": "edit",
    "editing": "edit",
    "modify": "edit",
    "update": "edit",
    "patch": "edit",
    "fix": "edit",
    "delete": "delete",
    "remove": "delete",
    "drop": "delete",
    "read": "read",
    "reading": "read",
    "inspect": "read",
    "list": "list",
    "listing": "list",
    "ls": "list",
    "fetch": "fetch",
    "download": "fetch",
    "get": "fetch",
    "run": "run",
    "execute": "run",
    "exec": "run",
}

_WORD_RE = re.compile(r"[A-Za-z_]+")
_PATH_BASENAME_RE = re.compile(r"\b([A-Za-z0-9_-]+\.(md|json|ya?ml|txt|py|toml|sql))\b")


def _content_words(text: str) -> list[str]:
    return [
        w.lower() for w in _WORD_RE.findall(text)
        if w.lower() not in _STOPWORDS and len(w) > 1
    ]


def fingerprint(text: str) -> str:
    """Stable hash of the (deduped, sorted) first 10 content words."""
    words = _content_words(text)
    canon = sorted(set(words))[:10]
    return hashlib.sha1(" ".join(canon).encode("utf-8")).hexdigest()


def cluster_key(text: str) -> tuple[str | None, str | None]:
    """Return ``(basename, canonical_verb)`` extracted heuristically."""
    basename: str | None = None
    m = _PATH_BASENAME_RE.search(text)
    if m:
        basename = m.group(1).lower()
    verb: str | None = None
    for word in _content_words(text):
        if word in _CLUSTER_VERB_NORMALISATION:
            verb = _CLUSTER_VERB_NORMALISATION[word]
            break
    return basename, verb


def dedup(
    proposals: list[ProposedTask],
    *,
    existing_tasks: list[str] | None = None,
) -> list[ProposedTask]:
    """Drop proposals matching each other or an entry in ``existing_tasks``.

    Order is preserved (first occurrence wins).
    """
    seen_prints: set[str] = set()
    seen_clusters: set[tuple[str, str]] = set()
    for existing in existing_tasks or ():
        seen_prints.add(fingerprint(existing))
        bn, vb = cluster_key(existing)
        if bn and vb:
            seen_clusters.add((bn, vb))

    out: list[ProposedTask] = []
    for p in proposals:
        fp = fingerprint(p.text)
        if fp in seen_prints:
            continue
        bn, vb = cluster_key(p.text)
        if bn and vb and (bn, vb) in seen_clusters:
            continue
        seen_prints.add(fp)
        if bn and vb:
            seen_clusters.add((bn, vb))
        out.append(p)
    return out
