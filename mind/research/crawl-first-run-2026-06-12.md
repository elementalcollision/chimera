# CRAWL first run — 2026-06-12 (the gate caught a bad change)

The first live CRAWL run (ADR 0182), triggered manually at 16:59. **Headline:
the system worked exactly as designed — it refused to ship a broken change —
and surfaced a mis-authored spec.**

## What happened

- The launchd runner (`com.chimera.crawl`) fired, picked spec
  `01-mcp-streamable-http-client`, gate-checked it (genuinely RED on main
  under `-W error`), and dispatched `real_task_soak.sh` on an isolated
  worktree.
- The agent made **exactly** what the spec prescribed — a "pure rename" of
  `streamablehttp_client` → `streamable_http_client` (import + call site, a
  clean 3-line diff).
- The gate **stayed red** and the soak kept iterating (10 iters, **$0.19**,
  far under the $2.50 cap — no runaway). Stopped manually once diagnosed.

## Root cause: the spec was wrong, not the agent

The rename is not a drop-in. The MCP SDK **consolidated** the signature:

```
OLD streamablehttp_client(url, headers=, timeout=, sse_read_timeout=,
                          terminate_on_close=, httpx_client_factory=, auth=)
NEW streamable_http_client(url, *, http_client: httpx.AsyncClient | None,
                           terminate_on_close=)
```

The gate caught it precisely: `streamable_http_client() got an unexpected
keyword argument 'headers'`. The agent was scope-locked to `mcp_client.py`
and told to rename, so it could not have known the API changed — the spec's
"pure rename" premise was false.

## Findings

1. **The safety property held in production.** Gate-visibility + the
   verify-green gate did their job: a plausible-but-wrong change never became
   a commit/PR. This is the single most important thing to validate before
   unattended operation, and it validated.
2. **The two seed specs were mis-scoped.** It is one API *migration*, not two
   renames, and it subsumes the `verify=<str>` deprecation (you now build the
   `httpx.AsyncClient` yourself, so TLS verify moves there too). Replaced by
   the single `01-modernize-federation-http-client` spec.
3. **A clean repo's gate-visible backlog is *migrations*, not renames.** The
   easy maintenance is already done; what remains is non-trivial. This raises
   the bar for what a CRAWL task is, and is worth weighing when curating
   specs (and when judging whether an autonomous soak can converge on one).
4. **No process/cost damage.** Cost capped at $0.19; worktree/branch/dispatch
   log cleaned up; the runner remains loaded for the next (daily 09:15) fire.

## Open decision

The corrected spec is a real multi-file API migration. Either (a) re-run
CRAWL to see whether the soak can converge on a genuine migration, or (b) do
the migration directly (it is well-understood now) and let CRAWL wait for the
next curated task. Operator's call (spend + approach).
