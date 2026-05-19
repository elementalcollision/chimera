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

## Notes

- `better-sqlite3` is a native module compiled at install time.
- The dashboard is server-component-only; no client JS for data fetching.
- Pages re-fetch from disk on every request (`export const dynamic = "force-dynamic"`).
