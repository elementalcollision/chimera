# Chimera control plane

A read-only Next.js dashboard for inspecting Chimera's runtime state.

## What it shows

- **Status** — current cycle, trust tier, drift score, model usage
- **INBOX** — the live task list
- **Ontology** — every KFM entity with its current state
- **Recent API calls** — last 15 with provider, model, latency, finish reason
- **Pending mutations** — proposals waiting for operator approval
- **Trust history** — promotions, demotions, lockdowns
- **Tier ladder outcomes** — per-rung success/fail counts
- **Recent activity** — per-phase records from `agent_activity_log`
- **Chronicle** — today's engine outputs
- **All mutations** — last 20 across all statuses

Reads `state/chimera.db` (SQLite, read-only) and `mind/*.md` directly. No
write surface at v1.4 — operator actions go through the Python CLI
(`chimera mutations approve …`, `chimera trust promote …`).

## Run it

```bash
cd control-plane
npm install
npm run dev
```

Then open <http://localhost:3000>.

By default it reads from `../state` and `../mind`. Override with:

```bash
CHIMERA_STATE_DIR=/path/to/state CHIMERA_MIND_DIR=/path/to/mind npm run dev
```

## Build

```bash
npm run build
npm run start
```

Production output is in `.next/`.

## Benchmark history

The **Benchmark history** widget surfaces headline numbers (LongMemEval
oracle / `_s`, LoCoMo full / envelope / hybrid retrieval, etc.) from a
curated JSON file at `mind/benchmarks.json`. Each row links to the
research note under `mind/research/` that documents methodology and
per-category breakdowns.

To add a new benchmark:

1. Land the research note under `mind/research/` first — it remains the
   canonical narrative for the number.
2. Append an entry to `mind/benchmarks.json` under `entries[]`:

   ```json
   {
     "id": "kebab-case-stable-id",
     "benchmark": "Display name",
     "config": "model, retrieval summary",
     "n": 500,
     "headline_pct": 90.80,
     "envelope": { "mean_pct": 90.13, "sigma_pp": 0.83, "gate_pct": 88.47 },
     "date": "YYYY-MM-DD",
     "source_note": "mind/research/your-note.md",
     "notes": "optional one-line context (shown in tooltip)"
   }
   ```

   `envelope` and `notes` are optional. Keep the file scoped to headline
   numbers; per-category tables belong in the source note.
3. The widget renders on next page load — no rebuild needed in dev.

If `mind/benchmarks.json` is missing or malformed the widget renders a
fail-soft placeholder pointing back at this section.

## Notes

- `better-sqlite3` is a native module compiled at install time.
- The dashboard is server-component-only; no client JS for data fetching.
- Pages re-fetch from disk on every request (`export const dynamic = "force-dynamic"`).
