"""v4.61 (ADR 0080) — FTS5 mind/wiki search."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.memory import open_and_init
from chimera.memory.wiki_search import (
    ensure_wiki_index,
    fts5_available,
    search_wiki,
    update_wiki_index,
    wiki_index_stats,
)


@pytest.fixture
def db_and_wiki(tmp_path: Path):
    db = open_and_init(tmp_path / "chimera.db")
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    yield db, wiki
    db.close()


def _write(wiki: Path, rel: str, body: str) -> Path:
    p = wiki / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# ── basic indexing ───────────────────────────────────────────────


def test_index_empty_dir(db_and_wiki):
    db, wiki = db_and_wiki
    counts = update_wiki_index(db, wiki)
    assert counts == {"added": 0, "updated": 0, "deleted": 0, "unchanged": 0}
    assert search_wiki(db, "anything") == []


def test_index_adds_new_files(db_and_wiki):
    db, wiki = db_and_wiki
    _write(wiki, "a.md", "# Title A\n\nThe quick brown fox jumps over.")
    _write(wiki, "subdir/b.md", "# Title B\n\nWaltz, bad nymph, for quick jigs vex.")
    counts = update_wiki_index(db, wiki)
    assert counts["added"] == 2
    assert counts["updated"] == 0
    assert counts["deleted"] == 0
    stats = wiki_index_stats(db)
    assert stats["indexed_files"] == 2


def test_index_skips_unchanged(db_and_wiki):
    db, wiki = db_and_wiki
    _write(wiki, "a.md", "# A\n\nbody")
    update_wiki_index(db, wiki)
    counts = update_wiki_index(db, wiki)  # second call
    assert counts["unchanged"] == 1
    assert counts["added"] == 0


def test_index_detects_update(db_and_wiki):
    db, wiki = db_and_wiki
    p = _write(wiki, "a.md", "# A\n\nbody one")
    update_wiki_index(db, wiki)
    # Bump mtime + content.
    import os
    import time
    time.sleep(0.01)
    p.write_text("# A\n\nbody two — completely different content", encoding="utf-8")
    new_mtime = p.stat().st_mtime_ns + 1
    os.utime(p, ns=(new_mtime, new_mtime))
    counts = update_wiki_index(db, wiki)
    assert counts["updated"] == 1
    # Content from the old indexing should be gone.
    assert search_wiki(db, "body one") == []
    assert len(search_wiki(db, "completely")) == 1


def test_index_detects_delete(db_and_wiki):
    db, wiki = db_and_wiki
    p = _write(wiki, "a.md", "# A\n\nbody")
    update_wiki_index(db, wiki)
    p.unlink()
    counts = update_wiki_index(db, wiki)
    assert counts["deleted"] == 1
    assert wiki_index_stats(db)["indexed_files"] == 0


def test_missing_wiki_dir_is_safe(db_and_wiki, tmp_path):
    db, _ = db_and_wiki
    counts = update_wiki_index(db, tmp_path / "does_not_exist")
    # Should not raise; nothing to index.
    assert "deleted" in counts


# ── search behavior ───────────────────────────────────────────────


def test_search_finds_terms(db_and_wiki):
    db, wiki = db_and_wiki
    _write(wiki, "a.md", "# Datacentres\n\nWater stress and energy demand.")
    _write(wiki, "b.md", "# Ontology\n\nKFM lifecycle states for entities.")
    update_wiki_index(db, wiki)
    hits = search_wiki(db, "datacentres")
    assert len(hits) == 1
    assert hits[0].path == "a.md"
    assert hits[0].title == "Datacentres"


def test_search_phrase_query(db_and_wiki):
    db, wiki = db_and_wiki
    _write(wiki, "a.md", "# A\n\nthe quick brown fox jumps over the lazy dog")
    _write(wiki, "b.md", "# B\n\nthe brown fox is quick when chased")
    update_wiki_index(db, wiki)
    # Exact-phrase MATCH should rank a.md higher than b.md.
    hits = search_wiki(db, '"quick brown fox"')
    assert len(hits) == 1
    assert hits[0].path == "a.md"


def test_search_prefix_query(db_and_wiki):
    db, wiki = db_and_wiki
    _write(wiki, "a.md", "# A\n\ndatacentre water demand")
    _write(wiki, "b.md", "# B\n\ndatacenters energy stress")
    update_wiki_index(db, wiki)
    hits = search_wiki(db, "datacent*")
    paths = {h.path for h in hits}
    assert paths == {"a.md", "b.md"}


def test_search_returns_snippet_with_markers(db_and_wiki):
    db, wiki = db_and_wiki
    _write(wiki, "a.md", "# A\n\nThe magic word is xenocomm in this file.")
    update_wiki_index(db, wiki)
    hits = search_wiki(db, "xenocomm")
    assert len(hits) == 1
    # snippet() wraps the match in « » per our schema config.
    assert "«xenocomm»" in hits[0].snippet


def test_search_empty_query_returns_empty(db_and_wiki):
    db, wiki = db_and_wiki
    _write(wiki, "a.md", "# A\n\nbody")
    update_wiki_index(db, wiki)
    assert search_wiki(db, "") == []
    assert search_wiki(db, "   ") == []


def test_search_respects_limit(db_and_wiki):
    db, wiki = db_and_wiki
    for i in range(15):
        _write(wiki, f"f{i}.md", f"# F{i}\n\nthis is a common word here")
    update_wiki_index(db, wiki)
    hits = search_wiki(db, "common", limit=5)
    assert len(hits) == 5


def test_title_falls_back_to_filename(db_and_wiki):
    db, wiki = db_and_wiki
    # No # heading.
    _write(wiki, "no-title.md", "just body text about a topic")
    update_wiki_index(db, wiki)
    hits = search_wiki(db, "topic")
    assert len(hits) == 1
    assert hits[0].title == "no-title"


# ── ensure_wiki_index idempotency ───────────────────────────────


def test_ensure_idempotent(db_and_wiki):
    db, _ = db_and_wiki
    ensure_wiki_index(db)  # already called via open_and_init
    ensure_wiki_index(db)  # second call must not raise
    assert fts5_available(db)
