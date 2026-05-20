# ADR 0080 — mind/wiki FTS5 search (v4.61)

**Status:** Accepted (2026-05-20)

## Context

[ADR 0002](./0002-memory-strategy.md) (memory strategy, Phase 0)
deferred episodic recall entirely on the grounds that there was "no
use case yet." The overnight ADR-revisit in
`mind/overnight/adr-revisits.md` flagged this as the biggest miss:

> Today I'd add a dirt-simple full-text search on `mind/wiki/`
> markdown files (SQLite FTS5, zero dependencies) as a Day-1
> feature and let the vector store earn its keep later. Waiting for
> embeddings created a vacuum where no retrieval existed at all.

The agent writes to `mind/wiki/` during sessions (projects, lessons,
plans) but had no in-loop way to *retrieve* prior knowledge. When
the agent needs to look up what it knew before, the only options
were `shell` + `grep`, or `web_search` (paying tokens to learn
something it already wrote down). Both are inefficient.

SQLite FTS5 is in the stdlib's SQLite build on every platform we
target. Zero dependencies; BM25 ranking; phrase + prefix + boolean
operators out of the box. The ADR-0002 revisit's intuition was
exactly right.

## Decision

### 1. FTS5 virtual table + mtime cache in `chimera.db`

`chimera/memory/wiki_search.py` — two tables:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5(
    path UNINDEXED,
    title,
    body,
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS wiki_fts_files (
    path TEXT PRIMARY KEY,
    mtime_ns INTEGER NOT NULL,
    indexed_at TEXT NOT NULL
);
```

`ensure_wiki_index()` is idempotent and called from `open_and_init`
so every chimera.db has the schema. If FTS5 isn't compiled into
this SQLite build (rare; some stripped Alpine images), the table
creation silently logs a warning and `fts5_available()` returns
False — the rest of the agent stays functional.

### 2. `update_wiki_index(db, wiki_dir)` — mtime-gated incremental

Walks `mind/wiki/**/*.md`, compares against the cache table, and
inserts/updates/deletes only the rows whose mtime_ns changed.
Returns `{added, updated, deleted, unchanged}` counts.

Same pattern as the v4.38 graph skill/wiki projection. Body capped
at 200K chars so a runaway markdown file doesn't blow up the FTS5
index memory.

Title heuristic: first `# heading` in the file head, else the
filename stem.

### 3. `search_wiki(db, query, limit=8)` — BM25-ranked hits

```python
SELECT path, title,
       snippet(wiki_fts, 2, '«', '»', '...', 16) AS sn,
       bm25(wiki_fts) AS rank
FROM wiki_fts WHERE wiki_fts MATCH ?
ORDER BY rank LIMIT ?
```

Returns `list[WikiSearchHit(path, title, snippet, rank)]`. Lower
BM25 = better; the helper sorts ascending. Snippet has `«match»`
markers around hit tokens, max 16 tokens of context.

Empty query → empty list (FTS5 would raise; we short-circuit).

### 4. `mind_search` tool

`chimera/tools/mind_search.py` — exposes `search_wiki` to the agent
as a registered tool. Schema:

```json
{
  "name": "mind_search",
  "description": "Search the agent's own mind/wiki/ knowledge base via SQLite FTS5...",
  "parameters": {
    "query": "FTS5 query (e.g. `agonistic OR datacenter*`)",
    "limit": "Max results (default 8, max 20)"
  }
}
```

Returned text format mirrors `web_search`: numbered result list
with title, path, snippet per hit. The agent should try this
BEFORE `web_search` since it's free and reflects what the agent
already knows.

Registered alongside the other core tools in
`chimera/tools/__init__.py:register_core_tools`.

### 5. `chimera search` CLI verb

```bash
chimera search "query"                 # text output
chimera search "query" --json          # structured payload
chimera search "query" --rebuild       # refresh index first
chimera search "query" --limit 5
```

Operator surface. Mirrors `chimera cost` and `chimera estimate` in
shape.

### 6. Housekeeping refreshes the index each cycle

`chimera/core/loop.py:_phase_housekeeping` calls
`update_wiki_index` after the v4.32 graph update. mtime-gated so
unchanged files cost nothing (the live wiki has 4 files at the
moment; the refresh adds milliseconds).

New env: `CHIMERA_AUTO_WIKI_INDEX_DISABLED=1` opts out.

Activity row gains `wiki_index_churn` + per-kind counts when
any add/update/delete happens.

## Tests

`tests/test_wiki_search.py` — 14 tests:

- Empty dir → no rows
- Adds new files; counts add/update/delete/unchanged
- Skips unchanged (mtime gate works)
- Detects updated content; old content removed from index
- Detects deletes
- Missing wiki dir is safe
- Search finds terms, phrase queries, prefix queries
- Snippet has `«...»` markers around matches
- Empty query → empty list (no FTS5 syntax error)
- limit is honored
- Title falls back to filename when no `#` heading
- `ensure_wiki_index` is idempotent
- `fts5_available` returns True post-init

Full suite after v4.61: 655 passing (was 641, +14 new).

## Non-goals

- **Not building an embedding store.** ADR 0002 deferred vectors;
  this ADR doesn't reverse that decision. FTS5 + BM25 is the
  baseline. When the operator has signal that "lexical match isn't
  enough," that's its own ADR.
- **Not indexing `mind/INBOX.md`, `mind/HEARTBEAT.md`, or
  `mind/CHRONICLE.md`.** These are operational state, not knowledge
  — they churn every cycle and would dominate the index. Wiki is
  the durable-knowledge surface.
- **Not building a dashboard widget.** The CLI is enough; a widget
  is a natural follow-up when the wiki has more content.
- **Not letting `mind_search` accept arbitrary SQL.** The tool
  takes an FTS5 query string. SQL injection is impossible because
  the query goes through a bound parameter; FTS5's own syntax is
  the only attack surface and it's read-only.

## Why this shape

Why FTS5 instead of `grep`? Because FTS5 gives BM25 ranking,
phrase/prefix/boolean operators, and snippet extraction for free.
`grep` returns all matches with no ranking; with 100+ wiki files
that's noise. FTS5 also runs in 1ms on the index; recursive grep
on the filesystem is 10-100ms.

Why store the index inside `chimera.db` instead of a sibling file?
Because the operator already manages chimera.db (gitignored,
state/, single-file). Adding a separate `mind/wiki.fts.db` would
mean another file to back up, another path to thread through env
config. Co-locating keeps the deployment story honest.

Why mtime-gated instead of content-hash? Because mtime is what we
have on the filesystem; the v4.38 graph projection already uses
this pattern. A pathological case (touch without edit) would
re-index unnecessarily but produce identical FTS5 rows — wasted
cycles, no correctness issue.

Why `porter unicode61` tokenizer? Porter stemming makes
"datacentres" / "datacenter" / "datacenters" match each other,
which is the kind of forgiveness the agent actually needs. The
unicode61 tokenizer handles Unicode word boundaries cleanly.
