import path from "node:path";

// Resolve to the repo root by walking up from this file.
const REPO_ROOT = path.resolve(__dirname, "..", "..");

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
