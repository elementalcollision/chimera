---
goal: "Add chimera.core.slugify.slugify — turn arbitrary text into a URL slug"
files: chimera/core/slugify.py tests/test_slugify.py
test: tests/test_slugify.py
base: main
done: false  # A/B PROBE (EASY) — never merged; graded by slugify-probe.accept.py
---
A/B PROBE for ADR 0183 A.1 — **EASY** tier (string munging). Not a daily-CRAWL
task (outside `mind/backlog/`). Graded against `slugify-probe.accept.py`.

Implement `chimera/core/slugify.py`:

    def slugify(text: str) -> str:
        """Turn arbitrary text into a lowercase URL slug."""

Behaviour (FIXED — the accept test is the source of truth):

- Lowercase; strip surrounding whitespace.
- Replace every run of non-`[a-z0-9]` characters (after lowercasing) with a
  single hyphen; ASCII-only — any non-ASCII or punctuation is a separator
  (`"café"` → `"caf"`).
- Strip leading/trailing hyphens.
- Examples: `"Hello World"` → `"hello-world"`; `"  Multiple   Spaces  "` →
  `"multiple-spaces"`; `"Foo_Bar.Baz"` → `"foo-bar-baz"`; `"100% Pure!"` →
  `"100-pure"`; `"Already-slug"` → `"already-slug"`.
- `ValueError` on: a non-string, empty/whitespace-only input, and input that
  slugifies to empty (e.g. `"!!!"`).

Acceptance: create `tests/test_slugify.py` covering every bullet. `chimera
verify` (ruff over both files + the new test) GREEN. Pure function, no I/O.
