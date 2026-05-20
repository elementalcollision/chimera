import path from "node:path";

// v4.41: Anchor off process.cwd() (always control-plane/ when launched via
// `npm run dev` or `next start`) instead of __dirname. Next.js compiles
// server chunks into .next/server/... where __dirname is unreliable —
// previously `readMindFile` silently pointed at a non-existent path and
// the Inbox widget showed "INBOX has no tasks" even with a full INBOX.md.
const REPO_ROOT = path.resolve(process.cwd(), "..");

export function stateDir(): string {
  return process.env.CHIMERA_STATE_DIR || path.join(REPO_ROOT, "state");
}

export function mindDir(): string {
  return process.env.CHIMERA_MIND_DIR || path.join(REPO_ROOT, "mind");
}

export function dbPath(): string {
  return path.join(stateDir(), "chimera.db");
}

export function trustStatePath(): string {
  return path.join(stateDir(), "trust_state.json");
}
