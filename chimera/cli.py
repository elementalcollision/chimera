"""Chimera CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any

from . import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chimera",
        description="Chimera — a multi-LLM tools-capable agent.",
    )
    parser.add_argument("--version", action="version", version=f"chimera {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    sub.add_parser("status", help="Show current cycle and trust state (stub).")
    doctor_p = sub.add_parser(
        "doctor",
        help="Validate config / env / state — boot-time preflight (v3.6+).",
    )
    doctor_p.add_argument(
        "--fix", action="store_true",
        help="Apply remediations for fixable findings "
             "(currently: checkpoint orphan WAL).",
    )
    doctor_p.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of formatted text.",
    )
    doctor_p.add_argument(
        "--install-hooks", action="store_true",
        help="Install the chip-branch-jump pre-commit hook (ADR 0141 Layer 3). "
             "Idempotent; never clobbers a foreign hook.",
    )
    sub.add_parser(
        "fragmentation",
        help="Show the v4.5 fragmentation log (compound-task failures).",
    )
    escalations = sub.add_parser(
        "escalations",
        help="Inspect the v4.46 task-escalation memory (auto-promotes tier).",
    )
    esc_sub = escalations.add_subparsers(
        dest="escalations_command", metavar="<esc-cmd>",
    )
    esc_list = esc_sub.add_parser("list", help="List recent escalation rows.")
    esc_list.add_argument("--limit", type=int, default=20, help="Max rows to show.")
    esc_list.add_argument(
        "--grep", default=None,
        help="Substring filter on the signature.",
    )
    esc_list.add_argument("--json", action="store_true",
                         help="Emit rows as a JSON list.")
    esc_summary = esc_sub.add_parser(
        "summary",
        help="Aggregate counts per signature × tier.",
    )
    esc_summary.add_argument("--json", action="store_true",
                            help="Emit summary dict as JSON.")
    esc_clear = esc_sub.add_parser(
        "clear",
        help="Delete escalation rows (use with care — the agent uses these to learn).",
    )
    esc_clear.add_argument(
        "--grep", default=None,
        help="Only delete rows whose signature matches this substring.",
    )
    esc_clear.add_argument(
        "--all", action="store_true",
        help="Required with no --grep — confirms a full wipe.",
    )
    esc_prune = esc_sub.add_parser(
        "prune",
        help="Delete escalation rows older than --older-than-days N.",
    )
    esc_prune.add_argument(
        "--older-than-days", type=int, required=True,
        help="Delete rows whose created_at is older than N days.",
    )
    esc_prune.add_argument("--json", action="store_true",
                           help='Emit {"deleted": N} as JSON.')
    proposers = sub.add_parser(
        "proposers",
        help="Score / demote / promote mutation proposers (v4.71 ADR 0090).",
    )
    p_sub = proposers.add_subparsers(
        dest="proposers_command", metavar="<prop-cmd>",
    )
    p_list = p_sub.add_parser(
        "list", help="Show acceptance rate + status per proposer.",
    )
    p_list.add_argument("--json", action="store_true")
    p_promote = p_sub.add_parser(
        "promote", help="Clear degraded/paused state, allow proposals again.",
    )
    p_promote.add_argument("proposer", help="mutation.type to promote")
    p_promote.add_argument("--reason", default=None)
    p_pause = p_sub.add_parser(
        "pause", help="Operator-pause a proposer (sticky until promote).",
    )
    p_pause.add_argument("proposer", help="mutation.type to pause")
    p_pause.add_argument("--reason", default=None)

    tiers = sub.add_parser(
        "tiers",
        help="Show every model rung in every tier ladder (v4.8+).",
    )
    tiers.add_argument(
        "--json",
        action="store_true",
        help="Emit a JSON ladder snapshot AND mirror to state/tiers.json.",
    )

    run = sub.add_parser(
        "run",
        help="Run one cycle of the agent loop (stub).",
        epilog="Refuses to start in the main worktree on a non-main branch "
               "(ADR 0141 Layer 2, chip-branch-jump prevention). Override "
               "with CHIMERA_ALLOW_MAIN_BRANCH_DRIFT=1.",
    )
    run.add_argument("prompt", nargs="?", help="Optional ad-hoc prompt to enqueue.")

    charter = sub.add_parser(
        "charter",
        help="Self-author a buildable, teeth-validated charter for a goal "
             "(ADR 0152/0153/0154).",
        epilog="Generates a charter (design + acceptance test + scope), rejects "
               "it if the self-written test lacks teeth, otherwise writes the "
               "build-soak inputs and prints a review packet.",
    )
    charter.add_argument("goal", help="What to build, in one sentence.")
    charter.add_argument(
        "--prefix", default="charter",
        help="Design-note filename prefix (default: charter).",
    )
    charter.add_argument(
        "--tier", default="opus",
        help="Provider tier for the charterer (default: opus).",
    )
    charter.add_argument(
        "--threshold", type=float, default=0.8,
        help="Minimum teeth score to accept the charter (default: 0.8).",
    )
    charter.add_argument(
        "--no-write", action="store_true",
        help="Preview the charter without writing any files.",
    )

    verify = sub.add_parser(
        "verify",
        help="Run the repo's real checks (ruff + pytest) over a change and "
             "report structured pass/fail (B1 / ADR 0158).",
        epilog="Exit 0 when every check passes, 1 otherwise. Narrow to the "
               "changed files / affected tests with --ruff / --test to keep it "
               "fast.",
    )
    verify.add_argument(
        "--test", default=None,
        help="Narrow pytest to this target (e.g. tests/test_x.py).",
    )
    verify.add_argument(
        "--ruff", action="append", default=None, metavar="PATH",
        help="Narrow ruff to these path(s); repeatable. Default: whole repo.",
    )
    verify.add_argument(
        "--timeout", type=float, default=600.0,
        help="Per-check timeout in seconds (default 600).",
    )

    faith = sub.add_parser(
        "faithfulness",
        help="Is a change's behaviour actually pinned by the suite? Mutation "
             "teeth (under-tested logic) + differential vs base (deleted "
             "behaviour) — toward no-contract verification (ADR 0159).",
        epilog="Exit 1 when the suite under-verifies the file (surviving "
               "mutants); the differential vs --base is advisory unless "
               "--strict. Blind spots are derived from the code, not a spec.",
    )
    faith.add_argument(
        "--target", required=True, action="append", metavar="FILE",
        help="A changed source file to assess; repeatable. A multi-file change "
             "is faithful only if EVERY target is.",
    )
    faith.add_argument(
        "--test", required=True, metavar="TARGET",
        help="pytest target that should pin the file (e.g. tests/test_x.py).",
    )
    faith.add_argument(
        "--base", default=None, metavar="REF",
        help="Git ref to diff behaviour against; enables the differential "
             "(deleted-behaviour) check over single-string-arg functions.",
    )
    faith.add_argument(
        "--threshold", type=float, default=1.0,
        help="Fraction of mutants that must be killed to count as faithful "
             "(default 1.0 — every probed behaviour pinned).",
    )
    faith.add_argument(
        "--max-mutants", type=int, default=40,
        help="Cap on mutation sites probed (default 40).",
    )
    faith.add_argument(
        "--strict", action="store_true",
        help="Also exit 1 on any test-unjustified behaviour delta vs --base.",
    )
    faith.add_argument(
        "--timeout", type=float, default=120.0,
        help="Per-mutant test timeout in seconds (default 120).",
    )

    review = sub.add_parser(
        "review",
        help="Adjudicate a change's faithfulness with a cross-model critic — "
             "the judgment gates can't make (ADR 0160). Fail-closed.",
        epilog="Exit 0 only on an explicit APPROVED verdict; 1 on rejection, "
               "unreadable verdict, or no provider. Feeds the critic the diff, "
               "the touched code's docstring, and the faithfulness report.",
    )
    review.add_argument("--target", required=True, action="append", metavar="FILE",
                        help="A changed source file; repeatable. The critic "
                             "reviews the diff across ALL targets.")
    review.add_argument("--base", required=True, metavar="REF",
                        help="Git ref the diff/behaviour is measured against.")
    review.add_argument("--test", default=None, metavar="TARGET",
                        help="pytest target for the faithfulness context.")
    review.add_argument("--goal", default=None,
                        help="One-line description of what the change should do.")
    review.add_argument("--tier", default="T3",
                        help="Provider rung for the critic (default T3).")

    calib = sub.add_parser(
        "critic-calibrate",
        help="Measure the critic's error rates on a labelled change set — esp. "
             "the false-APPROVE rate (waving an unfaithful change through). "
             "Turns 'worked once' into a number (ADR 0160).",
    )
    calib.add_argument("--model", default="claude-sonnet-4-6",
                       help="Anthropic model id for the critic.")

    sscan = sub.add_parser(
        "self-scan",
        help="Propose ranked, behaviour-neutral maintenance tasks from the repo "
             "(ruff debt, mutation survivors) — the WHAT leg of no-contract "
             "autonomy (ADR 0161). PRINTS ONLY; launches nothing.",
        epilog="Each candidate prints with a copy-pasteable real_task_soak.sh "
               "invocation. A human picks and runs one — self-scan never does.",
    )
    sscan.add_argument("--base", default="main",
                       help="Base ref for the emitted soak commands (default main).")
    sscan.add_argument("--limit", type=int, default=10,
                       help="Max candidates to print (default 10).")
    sscan.add_argument("--log", action="store_true",
                       help="Persist emitted candidates to the precision log and "
                            "print each candidate's id (ADR 0161 chip 3).")
    sscan.add_argument("--accept", action="append", default=None, metavar="ID",
                       help="Record an accept decision for proposal ID; repeatable.")
    sscan.add_argument("--reject", action="append", default=None, metavar="ID",
                       help="Record a reject decision for proposal ID; repeatable.")
    sscan.add_argument("--precision", action="store_true",
                       help="Print the origination precision report and exit.")

    cost = sub.add_parser(
        "cost",
        help="Show windowed spend (cycle, 15m, 60m, total) with band classification.",
    )
    cost.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of formatted text.",
    )
    cost.add_argument(
        "--cycle", type=int, default=None,
        help="Cycle number to report on (default: most recent).",
    )

    split = sub.add_parser(
        "split",
        help="Preview a task splitter call. Heuristic + optional model.",
    )
    split.add_argument(
        "task",
        help="Task text to evaluate (quote the whole string).",
    )
    split.add_argument(
        "--no-model", action="store_true",
        help="Skip the model call; show heuristic only.",
    )
    split.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of formatted text.",
    )

    search = sub.add_parser(
        "search",
        help="Full-text search over mind/wiki/ (FTS5).",
    )
    search.add_argument("query", help="FTS5 query (phrase, prefix, AND/OR/NOT).")
    search.add_argument(
        "--limit", type=int, default=8,
        help="Max results to show (default 8, max 20).",
    )
    search.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of formatted text.",
    )
    search.add_argument(
        "--rebuild", action="store_true",
        help="Force a fresh index update before searching.",
    )

    estimate = sub.add_parser(
        "estimate",
        help="Pre-flight: predict total USD to clear the open INBOX once.",
    )
    estimate.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of formatted text.",
    )
    estimate.add_argument(
        "--tier", default="haiku",
        choices=("haiku", "sonnet", "opus"),
        help="Default starting tier (research-floor + memory still apply).",
    )

    ping = sub.add_parser(
        "ping",
        help="Stream a one-token reply from both providers (verifies API keys).",
    )
    ping.add_argument(
        "--provider",
        choices=("anthropic", "openrouter", "both"),
        default="both",
    )

    ontology = sub.add_parser(
        "ontology",
        help="Inspect the KFM ontology in state/chimera.db.",
    )
    ontology.add_argument(
        "--kind",
        help="Filter by entity kind (plan, tool, skill, subagent).",
    )
    ontology.add_argument(
        "--audit",
        action="store_true",
        help="Print a memory/ontology audit (stale + dead entities, re-anchor count).",
    )
    ontology.add_argument(
        "--cycle",
        type=int,
        default=None,
        help="Audit reference cycle (defaults to max cycle from agent_activity_log).",
    )
    ontology.add_argument(
        "--stale-after-cycles",
        type=int,
        default=20,
        help="Stale threshold for the audit (default 20).",
    )
    ontology.add_argument(
        "--json",
        action="store_true",
        help="Emit audit output as JSON (only with --audit).",
    )
    ontology.add_argument(
        "--archive-stale",
        action="store_true",
        help="Promote DEPRECATED entities past --archive-after-cycles to ARCHIVED.",
    )
    ontology.add_argument(
        "--archive-after-cycles",
        type=int,
        default=30,
        help="Cycle threshold for --archive-stale (default 30).",
    )
    ontology.add_argument(
        "--dry-run",
        action="store_true",
        help="With --archive-stale: report what would be archived without writing.",
    )
    ontology.add_argument(
        "--propose-kills",
        action="store_true",
        help=(
            "Queue kill_entity mutations for ARCHIVED entities past "
            "--archive-after-cycles. Operator must approve before --apply-kills."
        ),
    )
    ontology.add_argument(
        "--apply-kills",
        action="store_true",
        help=(
            "Apply any approved kill_entity mutations: transition ARCHIVED → KILLED "
            "via the K-operator. Pairs with --propose-kills + `chimera mutations approve`."
        ),
    )

    mutations = sub.add_parser(
        "mutations",
        help="Inspect and approve/reject pending mutations.",
    )
    mut_sub = mutations.add_subparsers(dest="mut_command", metavar="<mut-cmd>")
    mut_sub.add_parser("list", help="List mutations (default: pending).")
    mut_show = mut_sub.add_parser("show", help="Show one mutation.")
    mut_show.add_argument("id", type=int)
    mut_approve = mut_sub.add_parser("approve", help="Approve a pending mutation.")
    mut_approve.add_argument("id", type=int)
    mut_approve.add_argument("--reason", default=None)
    mut_reject = mut_sub.add_parser("reject", help="Reject a pending mutation.")
    mut_reject.add_argument("id", type=int)
    mut_reject.add_argument("--reason", default=None)
    mut_apply = mut_sub.add_parser(
        "apply",
        help="Apply an approved mutation. Currently supports type=task_split (v4.65).",
    )
    mut_apply.add_argument("id", type=int)
    mut_health = mut_sub.add_parser(
        "health",
        help="Show queue-health metrics (counts, oldest pending, recurrence).",
    )
    mut_health.add_argument(
        "--json", action="store_true", help="Emit the snapshot as JSON."
    )

    a2a = sub.add_parser(
        "a2a",
        help="Inspect A2A / Xenocomm peer integration (v1.5+).",
    )
    a2a_sub = a2a.add_subparsers(dest="a2a_command", metavar="<a2a-cmd>")
    a2a_sub.add_parser("identity", help="Show this agent's identity payload.")
    a2a_sub.add_parser("peers", help="List Xenocomm tools discovered via MCP.")

    peers_p = sub.add_parser(
        "peers",
        help="Inspect / manage the local peer registry (v2.2+).",
    )
    peers_sub = peers_p.add_subparsers(dest="peers_command", metavar="<peers-cmd>")
    peers_sub.add_parser("list", help="List entries in the peer registry.")
    p_forget = peers_sub.add_parser("forget", help="Remove a peer entry by agent_id.")
    p_forget.add_argument("agent_id")
    peers_sub.add_parser("sweep", help="Remove stale (pid-gone) local peer entries.")
    p_sync = peers_sub.add_parser(
        "sync",
        help="Fetch /healthz from CHIMERA_REMOTE_PEERS and upsert entries (v3.7+).",
    )
    p_sync.add_argument(
        "--urls",
        default=None,
        help="Comma-separated base URLs (overrides CHIMERA_REMOTE_PEERS).",
    )
    p_sweep_remote = peers_sub.add_parser(
        "sweep-remote",
        help="Remove HTTP peer entries older than --max-age-hours (default 24).",
    )
    p_sweep_remote.add_argument("--max-age-hours", type=float, default=24.0)
    p_kfm = peers_sub.add_parser(
        "kfm",
        help="Fetch the swarm-KFM state of one peer (or all if no name given).",
    )
    p_kfm.add_argument("name", nargs="?", help="Peer server-name as known to MCP loader.")
    # ADR 0131: peer-card consolidation on demand. Attaches to the
    # existing peers parent so future Phase 3 #2 (`peers ask`) lands as
    # a sibling without re-shaping the namespace.
    p_cards = peers_sub.add_parser(
        "cards",
        help="Refresh mind/peers/ snapshots on demand (ADR 0128–0131).",
    )
    p_cards.add_argument(
        "--narrative", action="store_true",
        help="Also generate the LLM theory-of-mind paragraph per card "
             "(equivalent to CHIMERA_PEER_CARD_LLM=1 for this call).",
    )
    p_cards.add_argument(
        "--mind-dir",
        help="Override CHIMERA_MIND_DIR for this call.",
    )
    p_cards.add_argument(
        "--state-dir",
        help="Override CHIMERA_STATE_DIR for this call.",
    )
    p_cards.add_argument(
        "--json", action="store_true",
        help="Print a JSON summary instead of human-readable lines.",
    )
    # ADR 0133: dialectic Q&A against a peer's grounded context.
    p_ask = peers_sub.add_parser(
        "ask",
        help="Ask a natural-language question about a peer (ADR 0133).",
    )
    p_ask.add_argument("peer_name", help="Peer name (use 'self' for Chimera itself).")
    p_ask.add_argument("question", help="The question to ask.")
    p_ask.add_argument(
        "--mind-dir",
        help="Override CHIMERA_MIND_DIR for this call.",
    )
    p_ask.add_argument(
        "--prompt-only", action="store_true",
        help="Print the assembled prompt instead of calling the LLM. "
             "Useful for debugging the context build.",
    )
    p_ask.add_argument(
        "--json", action="store_true",
        help="Emit a JSON object {peer_name, question, answer, sources_used}.",
    )

    trust = sub.add_parser(
        "trust",
        help="Inspect and adjust trust tier (T0..T5).",
    )
    trust_sub = trust.add_subparsers(dest="trust_command", metavar="<trust-cmd>")
    trust_show = trust_sub.add_parser("show", help="Show current tier + recent history.")
    trust_show.add_argument("--json", action="store_true")
    trust_promote = trust_sub.add_parser(
        "promote",
        help="Promote one tier, or jump to --tier T<N> (operator escape hatch).",
    )
    trust_promote.add_argument(
        "--tier", default=None,
        help="Target tier T0..T5. Omit to promote one step.",
    )
    trust_promote.add_argument("--reason", default="manual promotion")
    trust_demote = trust_sub.add_parser("demote", help="Demote one tier.")
    trust_demote.add_argument("--reason", default="manual demotion")
    trust_revoke = trust_sub.add_parser(
        "revoke",
        help="Operator-revoke tier (defaults to T0 / observer; --tier T<N> to jump).",
    )
    trust_revoke.add_argument(
        "--tier", default=None,
        help="Target tier T0..T5. Omit to drop straight to T0.",
    )
    trust_revoke.add_argument("--reason", default="operator revoke")
    trust_lock = trust_sub.add_parser("lockdown", help="Immediate T0 lockdown.")
    trust_lock.add_argument("--reason", default="manual lockdown")
    trust_budget = trust_sub.add_parser(
        "budget",
        help=(
            "Show trust budget: tier, dwell time, readiness, last ~10 history "
            "events with finish_reason provenance, and promotion thresholds. "
            "See docs/adr/0100-graduated-trust-decrements.md (follow-up chip v4.94)."
        ),
    )
    trust_budget.add_argument(
        "--limit", type=int, default=10,
        help="Number of recent history events to show (default 10).",
    )
    trust_budget.add_argument("--json", action="store_true")
    trust_degrade = trust_sub.add_parser(
        "degrade-check",
        help=(
            "Compare current tier against a baseline and warn (or auto-promote) "
            "if it has degraded. Designed for soak runners to call between "
            "cycles. See docs/adr/0100-graduated-trust-decrements.md "
            "(follow-up chip v4.95)."
        ),
    )
    trust_degrade.add_argument(
        "--baseline", type=int, required=True,
        help="Tier (0..5) at soak start. Degradation = current < baseline.",
    )
    trust_degrade.add_argument(
        "--threshold-drop", type=int, default=2,
        help="Emit warning if tier dropped by at least N tiers (default 2). "
             "Reaching T0 always trips the warning regardless of drop size.",
    )
    trust_degrade.add_argument(
        "--auto-promote", action="store_true",
        help="If degraded, call promote() once to lift the agent above T0. "
             "Idempotent: only promotes if current_tier < baseline.",
    )
    trust_degrade.add_argument(
        "--chronicle-path", default=None,
        help="If provided AND degraded, append a warning line to this file "
             "(mind/SESSION_LOG.md style). Includes recent demote events with "
             "finish_reason provenance.",
    )
    trust_degrade.add_argument(
        "--history-limit", type=int, default=5,
        help="Number of recent demote events to include in the warning "
             "(default 5).",
    )
    trust_degrade.add_argument("--json", action="store_true")

    skills = sub.add_parser(
        "skills",
        help="Manage dynamic skills (assemble from a mutation, list, etc).",
    )
    skills_sub = skills.add_subparsers(dest="skills_command", metavar="<skills-cmd>")
    skills_sub.add_parser("list", help="List currently registered dynamic skills.")
    skills_asm = skills_sub.add_parser(
        "assemble",
        help="Assemble + validate + activate a skill from a mutation id.",
    )
    skills_asm.add_argument("mutation_id", type=int)

    engines = sub.add_parser(
        "engines",
        help="Run daily engines (Discovery / Curiosity / Reflection).",
    )
    engines_sub = engines.add_subparsers(dest="engines_command", metavar="<engines-cmd>")
    engines_run = engines_sub.add_parser("run", help="Force-fire one engine.")
    engines_run.add_argument(
        "name",
        choices=("discovery", "curiosity", "reflection"),
    )

    scenario = sub.add_parser(
        "scenario",
        help="Run a scripted scenario (checkpoint artifact).",
    )
    scenario.add_argument(
        "name",
        choices=(
            "drift", "research", "two_chimera", "multi_host",
            "federation_drill", "federation_trust_drill",
            "federation_http_drill", "cost_runaway_drill",
        ),
        help="Which scenario to run.",
    )

    serve = sub.add_parser(
        "serve",
        help="Start Chimera's MCP server (stdio by default; --http for HTTP).",
    )
    serve.add_argument(
        "--name",
        default="chimera",
        help="MCP server name advertised to peers (default: chimera).",
    )
    serve.add_argument(
        "--http",
        action="store_true",
        help="Use HTTP/SSE transport instead of stdio (v2.6+).",
    )
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="HTTP bind host (default 127.0.0.1; use 0.0.0.0 to expose).",
    )
    serve.add_argument(
        "--port",
        type=int,
        default=8765,
        help="HTTP port (default 8765).",
    )

    emergence = sub.add_parser(
        "emergence",
        help="Inspect / sync the protocol-evolution journal (v2.9+).",
    )
    emergence_sub = emergence.add_subparsers(dest="emergence_command", metavar="<emg-cmd>")
    emergence_sub.add_parser("list", help="List per-peer earliest and latest observations.")
    e_sync = emergence_sub.add_parser(
        "sync",
        help="Pull /emergence-feed from CHIMERA_REMOTE_PEERS into remote/.",
    )
    e_sync.add_argument("--urls", default=None)

    graph = sub.add_parser(
        "graph",
        help="LadybugDB graph store: init / query / rebuild (v2.10+).",
    )
    graph_sub = graph.add_subparsers(dest="graph_command", metavar="<graph-cmd>")
    graph_sub.add_parser("init", help="Create schema in state/chimera.graph/.")
    g_rebuild = graph_sub.add_parser(
        "rebuild", help="Re-project SQLite + registry into the graph."
    )
    g_rebuild.add_argument(
        "--incremental",
        action="store_true",
        help="Append only new entities + transitions (v4.31) — much cheaper than clear+rebuild.",
    )
    g_query = graph_sub.add_parser("query", help="Run a Cypher query and print rows.")
    g_query.add_argument("cypher", help="Cypher statement.")
    g_hist = graph_sub.add_parser(
        "entity-history", help="KFM transition chain for one entity (by id or name)."
    )
    g_hist.add_argument("ident", help="Entity id (full or 8-char prefix) or name.")
    graph_sub.add_parser(
        "skill-deps", help="List dynamic skills and their DEPENDS_ON / USES_TOOL edges."
    )
    graph_sub.add_parser(
        "orphans", help="Entities with no transitions; skills with no edges."
    )
    g_prov = graph_sub.add_parser(
        "provenance", help="Mutation provenance: PROPOSED entity + ACTIVATED skill chain."
    )
    g_prov.add_argument("mutation_id", type=int)
    g_export = graph_sub.add_parser(
        "export",
        help="Write a JSON snapshot of graph queries for the dashboard.",
    )
    g_export.add_argument(
        "--out",
        default=None,
        help="Output path (default: state/chimera.graph.snapshot.json).",
    )
    g_stress = graph_sub.add_parser(
        "stress",
        help="Synthetic stress test: populate N entities, rebuild, query, restart.",
    )
    g_stress.add_argument("--entities", type=int, default=500)
    g_stress.add_argument("--transitions-each", type=int, default=2)
    g_stress.add_argument("--repeat", type=int, default=10)
    g_stress.add_argument("--json", action="store_true")

    # v4.97 (ADR 0102): operator-side PR submission for agent soak work.
    sp = sub.add_parser(
        "submit-pr",
        help=(
            "Open a PR from an agent soak worktree using the OPERATOR's "
            "git config. Agent never holds push credentials."
        ),
    )
    sp.add_argument(
        "--worktree", required=True,
        help="Absolute path to the soak worktree (e.g. /Users/.../chimera-soak-vN-...)",
    )
    sp.add_argument(
        "--base", default="main",
        help="Base branch for the PR (default: main).",
    )
    sp.add_argument("--title", default=None, help="PR title override.")
    sp.add_argument("--body", default=None, help="PR body override.")
    sp.add_argument(
        "--body-from-postmortem", default=None,
        help="Path to a post-mortem markdown file used as the PR body.",
    )
    sp.add_argument(
        "--draft", action="store_true", default=True,
        help="Open as draft (default: true).",
    )
    sp.add_argument(
        "--no-draft", dest="draft", action="store_false",
        help="Open as a ready-for-review PR.",
    )
    sp.add_argument(
        "--dry-run", action="store_true",
        help="Validate only; do not push or open a PR.",
    )
    sp.add_argument(
        "--allow-entropy", action="store_true",
        help="Bypass the high-entropy diff check (use after confirming the false positive).",
    )
    sp.add_argument("--json", action="store_true", help="Emit a JSON result.")

    # ── evals (ADR 0135) ────────────────────────────────────────
    evals = sub.add_parser(
        "evals",
        help="Run memory-subsystem benchmark adapters (ADR 0135).",
    )
    evals_sub = evals.add_subparsers(
        dest="evals_command", metavar="<evals-cmd>",
    )
    longmemeval = evals_sub.add_parser(
        "longmemeval",
        help="LongMemEval adapter (Phase 4 #8). Produces answers + provenance; "
             "grading is the upstream harness's job.",
    )
    longmemeval.add_argument(
        "--items",
        help="Path to a LongMemEval JSONL items file. Required unless "
             "--smoke is set.",
    )
    longmemeval.add_argument(
        "--smoke", action="store_true",
        help="Run the built-in 3-item synthetic fixture instead of an "
             "external file. Useful for verifying the adapter end-to-end "
             "without downloading the upstream dataset.",
    )
    longmemeval.add_argument(
        "--n", type=int, default=None,
        help="Cap the number of items processed (after --subset filter).",
    )
    longmemeval.add_argument(
        "--subset",
        help="Filter by category (case-insensitive substring match against "
             "the item's category field).",
    )
    longmemeval.add_argument(
        "--out",
        help="Output JSONL path. Defaults to mind/evals/longmemeval-<ts>.jsonl.",
    )
    longmemeval.add_argument(
        "--mind-dir",
        help="Override CHIMERA_MIND_DIR for this call.",
    )
    longmemeval.add_argument(
        "--answer", action="store_true",
        help="Run each assembled dialectic prompt through OpenRouter "
             "(default model: openai/gpt-mini-latest) and write the "
             "LLM's reply as `hypothesis` + `question_id` (the upstream "
             "src/evaluation/evaluate_qa.py grader's expected fields). "
             "Requires OPENROUTER_API_KEY. Default off — adapter "
             "returns prompts only.",
    )
    longmemeval.add_argument(
        "--answer-model", default="openai/gpt-mini-latest",
        help="OpenRouter model ID for --answer. Default: "
             "openai/gpt-mini-latest.",
    )
    longmemeval.add_argument(
        "--n-per-category", type=int, default=None,
        help="Independent cap per category (useful for smoke runs that "
             "want N items per category for an even spread).",
    )
    longmemeval.add_argument(
        "--hybrid-retrieval", action="store_true",
        help="Insert BM25 + dense retrieval between ingest and answer; "
             "ship only top-k matched sessions into the self-card. "
             "Auto no-op when len(history) <= top-k (oracle path). "
             "Dense uses OpenAI text-embedding-3-small (needs OPENAI_API_KEY); "
             "falls back to BM25-only with a warning if unset. ADR 0142.",
    )
    longmemeval.add_argument(
        "--retrieval-top-k", type=int, default=8,
        help="Top-k sessions to retain when --hybrid-retrieval is on. Default 8.",
    )
    longmemeval.add_argument(
        "--answer-temperature", type=float, default=None,
        help="Sampling temperature for the --answer LLM call. Default "
             "None (omit from request — provider/model default applies). "
             "Set to 0 for deterministic answerers (ADR 0144, T2.1d "
             "envelope characterisation). Ignored if the chosen model "
             "rejects the parameter (e.g. some reasoning models).",
    )
    longmemeval.add_argument(
        "--answer-max-tokens", type=int, default=2048,
        help="max_tokens budget for the --answer LLM call. Default 2048 "
             "(raised from 512 to recover reasoning-token-exhaustion "
             "empties observed on deep-history items in the smoke baseline; "
             "Chip T1.1 of post-baseline development priorities).",
    )

    locomo = evals_sub.add_parser(
        "locomo",
        help="LoCoMo adapter (ADR 0144). Chimera's second eval surface — "
             "snap-research/locomo, 10 long peer-to-peer conversations.",
    )
    locomo.add_argument(
        "--items",
        help="Path to upstream data/locomo10.json. Required unless --smoke.",
    )
    locomo.add_argument(
        "--smoke", action="store_true",
        help="Run a built-in 3-item synthetic fixture instead of a corpus file.",
    )
    locomo.add_argument(
        "--n", type=int, default=None,
        help="Cap the number of items processed (after --subset/--sample-id).",
    )
    locomo.add_argument(
        "--subset",
        help="Filter by canonical category (substring match): single-hop / "
             "multi-hop / temporal-reasoning / open-domain / adversarial.",
    )
    locomo.add_argument(
        "--sample-id",
        help="Filter by conversation sample_id (substring match, e.g. 'conv-26').",
    )
    locomo.add_argument(
        "--out",
        help="Output JSONL path. Defaults to mind/evals/locomo-<ts>.jsonl.",
    )
    locomo.add_argument(
        "--mind-dir",
        help="Override CHIMERA_MIND_DIR for this call.",
    )
    locomo.add_argument(
        "--answer", action="store_true",
        help="Run each assembled dialectic prompt through OpenRouter and "
             "write the LLM's reply as `hypothesis` for the grader. "
             "Requires OPENROUTER_API_KEY.",
    )
    locomo.add_argument(
        "--answer-model", default="openai/gpt-mini-latest",
        help="OpenRouter model ID for --answer. Default: openai/gpt-mini-latest.",
    )
    locomo.add_argument(
        "--n-per-category", type=int, default=None,
        help="Independent cap per canonical category. Useful for the "
             "ADR 0144 directional spike (n=6 per cat ≈ 30 items total).",
    )
    locomo.add_argument(
        "--hybrid-retrieval", action="store_true",
        help="Insert BM25 + dense retrieval before ingest (ADR 0142). "
             "LoCoMo conversations are 19–32 sessions so the flag is "
             "meaningful from day one. Default off — match upstream "
             "paper's full-context baseline.",
    )
    locomo.add_argument(
        "--retrieval-top-k", type=int, default=8,
        help="Top-k sessions to retain when --hybrid-retrieval is on.",
    )
    locomo.add_argument(
        "--answer-temperature", type=float, default=None,
        help="Sampling temperature for the --answer LLM call. Default "
             "None (omit from request — provider/model default applies).",
    )
    locomo.add_argument(
        "--answer-max-tokens", type=int, default=2048,
        help="max_tokens budget for the --answer LLM call. Default 2048 "
             "(matches LongMemEval default; deep histories need the headroom).",
    )

    # v40′: `chimera mind count` — thin wrapper over chimera.mindcount
    # (the first Chimera-authored module to land; see
    # mind/research/v40prime-attempt1-capstone.md).
    mind_p = sub.add_parser("mind", help="Inspect the mind/ directory (read-only).")
    mind_sub = mind_p.add_subparsers(dest="mind_command", metavar="<mind-cmd>")
    mind_sub.add_parser(
        "count", help="Print recursive file counts per top-level mind/ entry.",
    )

    # v44: `chimera soak summary <run-id>` — thin wrapper over
    # chimera.soak_summary (the first real-feature module Chimera authored;
    # see mind/research/v44-soaksummary-capstone.md).
    soak_p = sub.add_parser(
        "soak", help="Inspect a soak run's ledgers (read-only).",
    )
    soak_sub = soak_p.add_subparsers(dest="soak_command", metavar="<soak-cmd>")
    soak_summary_p = soak_sub.add_parser(
        "summary",
        help="Print the iteration-vs-spend table for a soak run from its ledger.",
    )
    soak_summary_p.add_argument(
        "run_id", help="The soak run id (the mind/soak/<run-id>/ directory name).",
    )
    # v45: `chimera soak breakdown <run-id>` — finish-reason count table
    # (chimera/soak_breakdown.py, the v45 second-real-feature module).
    soak_breakdown_p = soak_sub.add_parser(
        "breakdown",
        help="Print the finish-reason count table for a soak run from its ledger.",
    )
    soak_breakdown_p.add_argument(
        "run_id", help="The soak run id (the mind/soak/<run-id>/ directory name).",
    )
    # v46: `chimera soak report <run-id>` — full soak-health view
    # (chimera/soak_report.py composes summary + breakdown).
    soak_report_p = soak_sub.add_parser(
        "report",
        help="Print the full soak-health report (iterations + finish reasons).",
    )
    soak_report_p.add_argument(
        "run_id", help="The soak run id (the mind/soak/<run-id>/ directory name).",
    )

    return parser


async def _ping_provider(name: str) -> int:
    from .providers import (
        HAIKU,
        HAIKU_LADDER,
        AnthropicProvider,
        ChatMessage,
        OpenRouterProvider,
        ProviderKind,
    )

    try:
        if name == "anthropic":
            provider = AnthropicProvider()
            model = HAIKU.model_id
        else:
            provider = OpenRouterProvider()
            # First OpenRouter rung in the HAIKU ladder — native (non-Anthropic) model.
            first_or_rung = next(
                r for r in HAIKU_LADDER if r.config.provider is ProviderKind.OPENROUTER
            )
            model = first_or_rung.config.openrouter_model_id
    except RuntimeError as e:
        print(f"  [{name}] SKIP: {e}")
        return 0

    text_parts: list[str] = []
    finish: str | None = None
    async for chunk in provider.stream(
        [ChatMessage(role="user", content="Say 'pong' and nothing else.")],
        model_id=model,
        max_tokens=128,
    ):
        text_parts.append(chunk.text)
        if chunk.finish_reason:
            finish = chunk.finish_reason
    reply = "".join(text_parts).strip()
    print(f"  [{name}] reply={reply!r} finish={finish!r}")
    return 0 if "pong" in reply.lower() else 1


def _cmd_peers_cards(args) -> int:
    """`chimera peers cards [--narrative]` — refresh ``mind/peers/`` on demand.

    Deterministic-only by default; ``--narrative`` (or
    ``CHIMERA_PEER_CARD_LLM=1`` in the environment) opts into the
    sonnet-tier theory-of-mind paragraph per card (ADR 0130 / 0131).
    """
    import json as _json
    import os as _os

    from .a2a.peer_trust_journal import list_decisions
    from .a2a.peers import list_peer_chimeras
    from .core import ChimeraLoop, LoopConfig
    from .engines.peer_cards import (
        build_peer_card,
        build_self_card,
        write_peer_card,
    )

    if args.mind_dir:
        _os.environ["CHIMERA_MIND_DIR"] = args.mind_dir
    if args.state_dir:
        _os.environ["CHIMERA_STATE_DIR"] = args.state_dir

    cfg = LoopConfig.from_env()
    cfg.mind_dir.mkdir(parents=True, exist_ok=True)
    cfg.state_dir.mkdir(parents=True, exist_ok=True)

    # The ChimeraLoop carries the registry + TrustManager wired exactly
    # as the running agent would have them. We don't run a cycle — just
    # use its state to drive consolidation.
    loop = ChimeraLoop(cfg)
    peer_names = list_peer_chimeras(loop._registry)

    cards = [build_self_card(trust_state=loop._trust.state)]
    for name in peer_names:
        cards.append(build_peer_card(
            name,
            decisions=list_decisions(name),
            current_cycle=None,
        ))

    if args.narrative:
        _os.environ["CHIMERA_PEER_CARD_LLM"] = "1"
        try:
            loop._enrich_cards_with_narratives(cards)
        except Exception as exc:  # noqa: BLE001 — keep CLI resilient
            print(f"warning: narrative enrichment failed: {exc}")

    paths = [write_peer_card(cfg.mind_dir, c) for c in cards]
    rels = [str(Path(p).relative_to(cfg.mind_dir.parent)) if cfg.mind_dir.parent in p.parents
            else str(p) for p in paths]

    if args.json:
        print(_json.dumps({
            "written": [str(p) for p in paths],
            "count": len(paths),
            "narrative": bool(args.narrative),
            "peers": peer_names,
        }, indent=2))
    else:
        narr = " (with narratives)" if args.narrative else ""
        print(f"chimera peers cards: wrote {len(paths)} card(s){narr}")
        for r in rels:
            print(f"  {r}")
    return 0


def _cmd_peers_ask(args) -> int:
    """`chimera peers ask <peer> "<question>"` — dialectic Q&A (ADR 0133).

    Gathers grounded context (peer card + trust journal + beliefs if
    available), assembles the dialectic prompt, then calls the local
    sonnet-tier provider for an answer. With ``--prompt-only`` the
    prompt is printed and no LLM call is made (useful for debugging).
    """
    import json as _json
    import os as _os

    from .a2a.dialectic import (
        build_dialectic_prompt,
        gather_dialectic_context,
        trim_answer,
    )
    from .core import LoopConfig

    if args.mind_dir:
        _os.environ["CHIMERA_MIND_DIR"] = args.mind_dir

    cfg = LoopConfig.from_env()
    ctx = gather_dialectic_context(args.peer_name, mind_dir=cfg.mind_dir)
    prompt = build_dialectic_prompt(ctx, args.question)

    if args.prompt_only:
        if args.json:
            print(_json.dumps({
                "peer_name": args.peer_name,
                "question": args.question,
                "prompt": prompt,
                "sources_used": ctx.sources_used,
                "is_empty_context": ctx.is_empty(),
            }, indent=2))
        else:
            print(prompt)
        return 0

    # Build a ChimeraLoop only to harvest its ACT provider topology.
    from .core import ChimeraLoop
    from .providers import Message
    from .providers.tiers import Provider as ProviderKind
    from .providers.tiers import select_rung

    loop = ChimeraLoop(cfg)
    try:
        if loop._act is None or not loop._act.providers:
            answer = (
                f"(no providers configured — cannot answer about "
                f"{args.peer_name}; assembled context only)"
            )
        else:
            try:
                rung = select_rung("sonnet")
            except (ValueError, RuntimeError) as exc:
                print(f"error: tier resolution failed: {exc}")
                return 1
            provider = loop._act.providers.get(rung.config.provider)
            if provider is None:
                answer = "(no provider available for sonnet tier)"
            else:
                model_id = (
                    rung.config.model_id
                    if rung.config.provider is ProviderKind.ANTHROPIC
                    else rung.config.openrouter_model_id
                )

                async def _call() -> str:
                    response = await provider.complete_with_tools(
                        messages=[Message.user(prompt)],
                        model_id=model_id,
                        tools=[],
                        max_tokens=384,
                    )
                    return response.text or ""

                from ._async_loop import run_on_persistent_loop
                answer = trim_answer(run_on_persistent_loop(_call()))
    finally:
        loop.close()

    if args.json:
        print(_json.dumps({
            "peer_name": args.peer_name,
            "question": args.question,
            "answer": answer,
            "sources_used": ctx.sources_used,
            "is_empty_context": ctx.is_empty(),
        }, indent=2))
    else:
        print(answer)
    return 0


def _cmd_evals_longmemeval(args) -> int:
    """`chimera evals longmemeval ...` — Phase 4 #8 adapter sweep (ADR 0135)."""
    import os as _os

    from .core import LoopConfig
    from .evals.longmemeval import (
        LongMemEvalAdapter,
        LongMemEvalItem,
        default_results_path,
        load_items,
        run_batch,
        write_results,
    )

    if args.mind_dir:
        _os.environ["CHIMERA_MIND_DIR"] = args.mind_dir

    cfg = LoopConfig.from_env()
    cfg.mind_dir.mkdir(parents=True, exist_ok=True)

    if not args.items and not args.smoke:
        print(
            "error: pass --items PATH or --smoke. The latter runs a built-in "
            "3-item synthetic fixture for adapter verification."
        )
        return 2

    if args.smoke:
        items = [
            LongMemEvalItem(
                item_id="smoke-0",
                question="What pet does the user have?",
                history=[[
                    {"role": "user", "content": "I just adopted a tabby cat."},
                    {"role": "assistant", "content": "Congratulations!"},
                ]],
                expected_answer="a tabby cat",
                category="single-session-user",
            ),
            LongMemEvalItem(
                item_id="smoke-1",
                question="Where does the user work?",
                history=[
                    [{"role": "user", "content": "I started at Acme today."}],
                    [{"role": "user", "content": "Acme is treating me well."}],
                ],
                expected_answer="Acme",
                category="multi-session",
            ),
            LongMemEvalItem(
                item_id="smoke-2",
                question="What is the user's favorite cuisine?",
                history=[[{"role": "user", "content": "Today is Tuesday."}]],
                expected_answer="",
                category="abstention",
            ),
        ]
    else:
        items = load_items(Path(args.items))
        if not items:
            print(f"error: no items loaded from {args.items}")
            return 1

    embed_fn = None
    if args.hybrid_retrieval:
        from .evals.hybrid_retrieval import build_default_embed_fn
        embed_fn = build_default_embed_fn()
        if embed_fn is None:
            print(
                "warning: --hybrid-retrieval enabled but OPENAI_API_KEY unset; "
                "falling back to BM25-only retrieval (ADR 0142 design note "
                "§Failure-mode register)."
            )
    adapter = LongMemEvalAdapter(
        mind_dir=cfg.mind_dir,
        hybrid_retrieval=args.hybrid_retrieval,
        retrieval_top_k=args.retrieval_top_k,
        embed_fn=embed_fn,
    )
    answer_fn = (
        _build_openrouter_answer_fn(
            args.answer_model,
            max_tokens=args.answer_max_tokens,
            temperature=args.answer_temperature,
        )
        if args.answer else None
    )
    results = run_batch(
        adapter, items,
        limit=args.n, subset=args.subset,
        answer_fn=answer_fn,
        per_category_limit=args.n_per_category,
    )

    out_path = Path(args.out) if args.out else default_results_path(cfg.mind_dir)
    write_results(results, out_path)

    by_category: dict[str, int] = {}
    errors = 0
    for r in results:
        by_category[r.category or "(none)"] = by_category.get(r.category or "(none)", 0) + 1
        if r.error:
            errors += 1
    label = f" (--answer via {args.answer_model})" if args.answer else ""
    print(f"chimera evals longmemeval{label}: {len(results)} item(s) → {out_path}")
    for cat, n in sorted(by_category.items()):
        print(f"  {cat}: {n}")
    if errors:
        print(f"  errors: {errors}")
    return 0


def _cmd_evals_locomo(args) -> int:
    """`chimera evals locomo ...` — second eval surface (ADR 0144)."""
    import os as _os

    from .core import LoopConfig
    from .evals.locomo import (
        LoCoMoAdapter,
        LoCoMoItem,
        default_results_path,
        items_from_sample,
        load_items,
        run_batch,
        write_results,
    )

    if args.mind_dir:
        _os.environ["CHIMERA_MIND_DIR"] = args.mind_dir

    cfg = LoopConfig.from_env()
    cfg.mind_dir.mkdir(parents=True, exist_ok=True)

    if not args.items and not args.smoke:
        print(
            "error: pass --items PATH (upstream data/locomo10.json) or --smoke. "
            "The latter runs a built-in synthetic fixture for adapter verification."
        )
        return 2

    if args.smoke:
        smoke_sample = {
            "sample_id": "smoke-conv",
            "conversation": {
                "speaker_a": "Alice",
                "speaker_b": "Bob",
                "session_1_date_time": "1 Jan 2026",
                "session_1": [
                    {"speaker": "Alice", "dia_id": "D1:1",
                     "text": "I adopted a tabby cat last week."},
                    {"speaker": "Bob", "dia_id": "D1:2",
                     "text": "Congrats! What's the name?"},
                    {"speaker": "Alice", "dia_id": "D1:3",
                     "text": "We named her Pixel."},
                ],
                "session_2_date_time": "8 Jan 2026",
                "session_2": [
                    {"speaker": "Alice", "dia_id": "D2:1",
                     "text": "Pixel is settling in well."},
                ],
            },
            "qa": [
                {"question": "What pet did Alice adopt?",
                 "answer": "a tabby cat", "evidence": ["D1:1"], "category": 1},
                {"question": "What is the cat's name?",
                 "answer": "Pixel", "evidence": ["D1:3"], "category": 1},
                {"question": "What is Bob's favorite cuisine?",
                 "answer": "(unanswerable)", "evidence": [], "category": 5},
            ],
        }
        items = items_from_sample(smoke_sample)
    else:
        items = load_items(Path(args.items))
        if not items:
            print(f"error: no items loaded from {args.items}")
            return 1

    embed_fn = None
    if args.hybrid_retrieval:
        from .evals.hybrid_retrieval import build_default_embed_fn
        embed_fn = build_default_embed_fn()
        if embed_fn is None:
            print(
                "warning: --hybrid-retrieval enabled but OPENAI_API_KEY unset; "
                "falling back to BM25-only retrieval (ADR 0142)."
            )
    adapter = LoCoMoAdapter(
        mind_dir=cfg.mind_dir,
        hybrid_retrieval=args.hybrid_retrieval,
        retrieval_top_k=args.retrieval_top_k,
        embed_fn=embed_fn,
    )
    answer_fn = (
        _build_openrouter_answer_fn(
            args.answer_model,
            max_tokens=args.answer_max_tokens,
            temperature=args.answer_temperature,
        )
        if args.answer else None
    )
    results = run_batch(
        adapter, items,
        limit=args.n, subset=args.subset,
        sample_id=args.sample_id,
        answer_fn=answer_fn,
        per_category_limit=args.n_per_category,
    )

    out_path = Path(args.out) if args.out else default_results_path(cfg.mind_dir)
    write_results(results, out_path)

    by_category: dict[str, int] = {}
    errors = 0
    for r in results:
        by_category[r.category or "(none)"] = by_category.get(r.category or "(none)", 0) + 1
        if r.error:
            errors += 1
    label = f" (--answer via {args.answer_model})" if args.answer else ""
    print(f"chimera evals locomo{label}: {len(results)} item(s) → {out_path}")
    for cat, n in sorted(by_category.items()):
        print(f"  {cat}: {n}")
    if errors:
        print(f"  errors: {errors}")
    return 0


def _build_openrouter_answer_fn(
    model_id: str,
    *,
    max_tokens: int = 2048,
    temperature: float | None = None,
):
    """Construct an ``AnswerFn`` that routes through OpenRouter.

    Uses ``chimera.providers.OpenRouterProvider`` with the operator-
    supplied ``model_id`` (default ``openai/gpt-mini-latest`` per the
    CLI flag). Requires ``OPENROUTER_API_KEY``; raises a clear error
    when absent.

    ``max_tokens`` defaults to 2048 (raised from 512) to recover the
    6/30 reasoning-token-exhaustion empties observed in the smoke
    baseline (PR #56 §"6 empty hypotheses"). Callers can override via
    ``--answer-max-tokens N`` on the CLI.

    Imported lazily so the test path that passes a deterministic stub
    never hits provider imports.

    Loop hygiene: per-call ``asyncio.run`` deadlocks after N successive
    invocations during loop-teardown on Python 3.14 — the
    ``shutdown_default_executor`` step blocks on a worker that holds
    state from the httpx AsyncClient's anyio backend. We route every
    call through one persistent loop on a daemon thread instead, so
    teardown only happens at process exit. See
    ``mind/research/f2-blocked-by-hybrid-retrieval-deadlock-2026-05-27.md``.
    """
    import asyncio as _asyncio
    import os as _os

    from .providers import Message, OpenRouterProvider
    from ._async_loop import run_on_persistent_loop

    if not _os.environ.get("OPENROUTER_API_KEY"):
        raise RuntimeError(
            "--answer needs OPENROUTER_API_KEY; not set. "
            "Export it and retry."
        )
    provider = OpenRouterProvider()

    # Per-call wall-clock bound. httpx already enforces its own timeout
    # but is not the only thing that can hang the coroutine — the F2
    # full-corpus sweep occasionally wedges on a future that the loop
    # never schedules (canonical idle 3-thread stack). ``wait_for``
    # raises ``asyncio.TimeoutError`` after the bound, cancels the
    # underlying coroutine, and unblocks the persistent loop so the
    # sweep continues with one missed item rather than a 3 h hang. The
    # bound is chosen at ~3× retry_call's worst case (3 attempts × 60 s
    # timeout × 1.5 s ceiling backoff) plus headroom.
    _CALL_TIMEOUT_S = float(_os.environ.get("CHIMERA_ANSWER_TIMEOUT_S", "240"))

    async def _call(prompt: str) -> str:
        kwargs: dict = {
            "messages": [Message.user(prompt)],
            "model_id": model_id,
            "tools": [],
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = await _asyncio.wait_for(
            provider.complete_with_tools(**kwargs),
            timeout=_CALL_TIMEOUT_S,
        )
        return (response.text or "").strip()

    def answer_fn(prompt: str) -> str:
        return run_on_persistent_loop(_call(prompt))

    return answer_fn


def _cmd_verify(args) -> int:
    """`chimera verify` — run the repo's real checks (ruff + pytest) over the
    current tree and print a structured pass/fail (B1 / ADR 0158).

    Exit 0 when every check passes, 1 when any fails. The same gate a B-tier
    soak uses as its convergence criterion, exposed so the agent (or operator)
    can run the real pipeline as one command and read the actionable failure
    detail.
    """
    from pathlib import Path

    from .core.repo_verify import verify_change

    report = verify_change(
        Path.cwd(),
        test_target=args.test,
        ruff_paths=args.ruff,
        timeout=args.timeout,
    )
    print(report.summary())
    for check in report.failed:
        print(f"\n── {check.name} (exit {check.returncode}) ──", file=sys.stderr)
        print(check.detail, file=sys.stderr)
    return 0 if report.ok else 1


def _single_string_arg_functions(source: str) -> list[str]:
    """Top-level function names taking exactly one positional arg — the ones the
    default string corpus can exercise. (Type-mismatched calls raise identically
    under base and changed, so they self-cancel in the differential anyway.)"""
    import ast

    names: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            a = node.args
            if len(a.args) == 1 and not a.vararg and not a.kwonlyargs:
                names.append(node.name)
    return names


def _top_level_classes(source: str) -> list[str]:
    """Top-level class names — the targets for the stateful differential."""
    import ast

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [n.name for n in tree.body if isinstance(n, ast.ClassDef)]


def _faithfulness_one(target, args, *, cwd, test_cmd) -> tuple[bool, bool]:
    """Assess one target: returns (mutation_faithful, has_unjustified_delta).
    Prints the mutation summary and any behaviour delta vs --base."""
    import subprocess

    from .core.differential import behavioral_delta, default_string_corpus
    from .core.faithfulness import assess_faithfulness

    report = assess_faithfulness(
        cwd / target, test_cmd, cwd=cwd, threshold=args.threshold,
        max_mutants=args.max_mutants, timeout=args.timeout,
    )
    print(f"[{target}] {report.summary()}")
    any_delta = False
    if args.base:
        try:
            base_src = subprocess.run(
                ["git", "show", f"{args.base}:{target}"],
                cwd=str(cwd), capture_output=True, text=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            base_src = None
        if base_src is not None and base_src.returncode == 0:
            changed_src = (cwd / target).read_text(encoding="utf-8")
            for fn in _single_string_arg_functions(changed_src):
                delta = behavioral_delta(
                    base_src.stdout, changed_src, fn, default_string_corpus(),
                )
                if delta.behaviour_changed:
                    any_delta = True
                    print(f"[{target}] {delta.summary()}", file=sys.stderr)
            # Stateful classes: the pure corpus is blind, so drive each changed
            # class through auto-generated call sequences (ADR 0159 amendment).
            from .core.stateful_diff import auto_scenarios, stateful_delta
            for cls in _top_level_classes(changed_src):
                scenarios = auto_scenarios(changed_src, cls)
                if not scenarios:
                    continue
                sd = stateful_delta(base_src.stdout, changed_src, cls, scenarios)
                if sd.behaviour_changed:
                    any_delta = True
                    print(f"[{target}] {sd.summary()}", file=sys.stderr)
        else:
            print(f"faithfulness: could not read {target} at {args.base!r} "
                  "for the differential (skipped).", file=sys.stderr)
    return report.faithful, any_delta


def _cmd_faithfulness(args) -> int:
    """`chimera faithfulness` — is a change's behaviour pinned by the suite?

    Accepts one or more --target files (a multi-file change is faithful only if
    EVERY file is). Mutation teeth (under-tested logic) is exit-affecting; the
    differential vs --base (deleted behaviour) is advisory unless --strict. Both
    signals are derived from the code, not a human contract (ADR 0159).
    """
    from pathlib import Path

    cwd = Path.cwd()
    test_cmd = ["uv", "run", "--extra", "dev", "pytest", "-q", args.test]
    targets = args.target if isinstance(args.target, list) else [args.target]

    all_faithful = True
    any_delta = False
    for target in targets:
        faithful, delta = _faithfulness_one(target, args, cwd=cwd, test_cmd=test_cmd)
        all_faithful = all_faithful and faithful
        any_delta = any_delta or delta

    if any_delta:
        print("\nNote: each behaviour delta must be a change a failing test "
              "demanded — otherwise it is a silent regression to revert or pin "
              "with a test.", file=sys.stderr)
    exit_code = 0 if all_faithful else 1
    if any_delta and args.strict:
        exit_code = 1
    return exit_code


def _function_docstrings(source: str) -> str:
    """Concatenate the module + top-level function docstrings — the intent the
    tests may not pin (the critic's source of truth)."""
    import ast

    out: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    mod = ast.get_docstring(tree)
    if mod:
        out.append(f"(module) {mod}")
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            ds = ast.get_docstring(node)
            if ds:
                out.append(f"{node.name}: {ds}")
    return "\n\n".join(out)


def _faithfulness_context(targets: list[str], base: str, test: str | None) -> str:
    """Assemble the machine-derived faithfulness report (mutation + differential)
    across ALL changed files, as text for the critic."""
    import subprocess
    from pathlib import Path

    from .core.differential import behavioral_delta, default_string_corpus
    from .core.faithfulness import assess_faithfulness

    cwd = Path.cwd()
    lines: list[str] = []
    for target in targets:
        if test:
            rep = assess_faithfulness(
                cwd / target,
                ["uv", "run", "--extra", "dev", "pytest", "-q", test],
                cwd=cwd, threshold=1.0, max_mutants=40,
            )
            lines.append(f"[{target}] {rep.summary()}")
        try:
            base_src = subprocess.run(
                ["git", "show", f"{base}:{target}"], cwd=str(cwd),
                capture_output=True, text=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            base_src = None
        if base_src is not None and base_src.returncode == 0:
            changed_src = (cwd / target).read_text(encoding="utf-8")
            for fn in _single_string_arg_functions(changed_src):
                delta = behavioral_delta(
                    base_src.stdout, changed_src, fn, default_string_corpus(),
                )
                if delta.behaviour_changed:
                    lines.append(f"[{target}] {delta.summary()}")
    return "\n".join(lines) or "(no faithfulness signals)"


def _cmd_review(args) -> int:
    """`chimera review` — cross-model critic adjudicates a change's faithfulness.

    Exit 0 only on an explicit APPROVED verdict (fail-closed). Feeds the critic
    the diff, the touched code's docstrings (intent), and the faithfulness
    report (ADR 0160).
    """
    import subprocess
    from pathlib import Path

    from ._async_loop import run_on_persistent_loop
    from .core import ChimeraLoop
    from .core.critic import review_change
    from .providers.tiers import Provider as ProviderKind
    from .providers.tiers import select_rung

    cwd = Path.cwd()
    targets = args.target if isinstance(args.target, list) else [args.target]
    diff = subprocess.run(
        ["git", "diff", args.base, "--", *targets], cwd=str(cwd),
        capture_output=True, text=True, timeout=30,
    ).stdout
    if not diff.strip():
        print("chimera review: empty diff — nothing to adjudicate.", file=sys.stderr)
        return 1
    docstring = "\n\n".join(
        _function_docstrings((cwd / t).read_text(encoding="utf-8")) for t in targets
    )
    faithfulness = _faithfulness_context(targets, args.base, args.test)

    loop = ChimeraLoop()
    providers = loop._act.providers if loop._act is not None else {}
    if not providers:
        print("chimera review: no provider available (fail-closed → REJECTED).",
              file=sys.stderr)
        return 1
    rung = select_rung(args.tier)
    provider = providers.get(rung.config.provider)
    if provider is None:
        print(f"chimera review: no provider for tier {args.tier!r}.", file=sys.stderr)
        return 1
    model_id = (
        rung.config.model_id if rung.config.provider is ProviderKind.ANTHROPIC
        else rung.config.openrouter_model_id
    )
    verdict = run_on_persistent_loop(review_change(
        diff, provider=provider, model_id=model_id, goal=args.goal,
        docstring=docstring, faithfulness=faithfulness,
    ))
    print(verdict.summary())
    if verdict.rationale and verdict.approved:
        print(verdict.rationale)
    return 0 if verdict.approved else 1


def _cmd_self_scan(args) -> int:
    """`chimera self-scan` — print ranked, behaviour-neutral maintenance
    candidates from the repo, each with a copy-pasteable real_task_soak.sh
    line. PRINTS ONLY; launches nothing (ADR 0161). Exit 0 whether or not
    candidates are found (it is a proposal surface, not a gate).

    --log persists candidates + prints ids; --accept/--reject record the
    operator's decision; --precision prints the origination precision report
    (chip 3 — the labelled data that eventually earns auto-origination)."""
    from datetime import datetime, timezone
    from pathlib import Path

    from .core.self_scan import scan_repo
    from .core.self_scan_log import (
        default_log_path,
        log_proposal,
        precision_report,
        record_decision,
    )

    log_path = default_log_path()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    if args.precision:
        print(precision_report(log_path).summary())
        return 0

    if args.accept or args.reject:
        for pid in (args.accept or []):
            record_decision(pid, "accepted", path=log_path, ts=now)
            print(f"recorded: {pid} accepted")
        for pid in (args.reject or []):
            record_decision(pid, "rejected", path=log_path, ts=now)
            print(f"recorded: {pid} rejected")
        return 0

    candidates = scan_repo(Path.cwd())
    if not candidates:
        print("self-scan: no behaviour-neutral candidates found (clean tree, or "
              "ruff unavailable).")
        return 0
    shown = candidates[: max(args.limit, 0)]
    print(f"self-scan: {len(candidates)} candidate(s) "
          f"(showing {len(shown)}) — PROPOSAL ONLY, nothing launched:\n")
    for i, c in enumerate(shown, 1):
        flag = c.risk_flag or "behaviour-neutral"
        id_str = ""
        if args.log:
            pid = log_proposal(c.goal, c.files, c.source, c.score,
                               path=log_path, ts=now)
            id_str = f"  id={pid}"
        print(f"{i}. [{c.score:.2f}] {c.source} · {flag}{id_str}")
        print(f"   {c.goal}")
        print(f"   $ {c.soak_command(base=args.base)}\n")
    print("Pick one and run its command yourself — self-scan does not launch soaks.")
    if args.log:
        print(f"\nLogged {len(shown)} proposal(s) to {log_path}. "
              "Record outcomes with --accept/--reject <id>; see --precision.")
    return 0


def _cmd_critic_calibrate(args) -> int:
    """`chimera critic-calibrate` — measure the critic's error rates on a
    labelled change set. Prints the confusion matrix + false-approve rate
    (ADR 0160). Exit 0 if no unfaithful change was approved (false-approve == 0),
    else 1 — a false approval is the failure that matters."""
    from ._async_loop import run_on_persistent_loop
    from .core import ChimeraLoop
    from .core.critic import review_change
    from .core.critic_calibration import default_cases, run_calibration
    from .providers.tiers import Provider as ProviderKind

    loop = ChimeraLoop()
    providers = loop._act.providers if loop._act is not None else {}
    provider = providers.get(ProviderKind.ANTHROPIC)
    if provider is None:
        print("chimera critic-calibrate: no Anthropic provider available.",
              file=sys.stderr)
        return 2

    async def _review(case):
        return await review_change(
            case.diff, provider=provider, model_id=args.model, goal=case.goal,
            docstring=case.docstring, faithfulness=case.faithfulness,
        )

    result = run_on_persistent_loop(run_calibration(default_cases(), _review))
    print(result.summary())
    return 0 if result.false_approve == 0 else 1


def _cmd_charter(args) -> int:
    """`chimera charter "<goal>"` — self-author a teeth-validated charter."""
    from .core import ChimeraLoop
    from .proposals.charter_cli import run_charter
    from .providers.tiers import Provider as ProviderKind
    from .providers.tiers import select_rung

    loop = ChimeraLoop()
    try:
        providers = loop._act.providers if loop._act is not None else {}
        if not providers:
            print(
                "chimera charter: no provider available (set ANTHROPIC_API_KEY "
                "or OPENROUTER_API_KEY).",
                file=sys.stderr,
            )
            return 2
        rung = select_rung(args.tier)
        provider = providers.get(rung.config.provider)
        if provider is None:
            print(
                f"chimera charter: no provider for tier {args.tier!r} "
                f"({rung.config.provider}).",
                file=sys.stderr,
            )
            return 2
        model_id = (
            rung.config.model_id
            if rung.config.provider is ProviderKind.ANTHROPIC
            else rung.config.openrouter_model_id
        )
        code, out = run_charter(
            args.goal,
            provider=provider,
            model_id=model_id,
            repo_root=Path.cwd(),
            prefix=args.prefix,
            threshold=args.threshold,
            write=not args.no_write,
        )
        print(out)
        return code
    finally:
        loop.close()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "emergence":
        from .a2a import journal_dir
        sub_cmd = args.emergence_command or "list"
        if sub_cmd == "list":
            d = journal_dir()
            files = sorted(d.glob("*.jsonl"))
            remote = sorted((d / "remote").glob("*/*.jsonl")) if (d / "remote").exists() else []
            print(f"chimera emergence: {len(files)} local, {len(remote)} remote")
            for p in files:
                lines = sum(1 for _ in p.read_text().splitlines() if _.strip())
                print(f"  local  {p.stem}: {lines} observation(s)")
            for p in remote:
                rel = p.relative_to(d / "remote")
                lines = sum(1 for _ in p.read_text().splitlines() if _.strip())
                print(f"  remote {rel}: {lines} observation(s)")
            return 0
        if sub_cmd == "sync":
            from .a2a.emergence_sync import sync_remote_emergence
            urls = None
            if args.urls:
                urls = [u.strip() for u in args.urls.split(",") if u.strip()]
            result = sync_remote_emergence(urls)
            print(
                f"chimera emergence sync: fetched={result.fetched} "
                f"records_added={result.records_added} "
                f"failed={len(result.failures)}"
            )
            for url, err in result.failures:
                print(f"  ! {url}: {err}")
            return 0 if not result.failures else 1
        parser.error(f"unknown emergence subcommand: {sub_cmd}")
        return 2
    if args.command == "cost":
        # v4.58 (ADR 0077): operator-facing windowed spend report.
        # Mirrors the dashboard cost-rate widget for headless / SSH use.
        from .core import LoopConfig
        from .core.budget import (
            cycle_cost_cap_usd,
            cycle_spend_usd,
            rolling_hour_cap_usd,
            rolling_spend_usd,
        )
        from .memory import open_and_init

        cfg = LoopConfig.from_env()
        conn = open_and_init(cfg.state_dir / "chimera.db")

        # Resolve cycle: explicit arg, else max(cycle) from api_calls.
        if args.cycle is not None:
            cycle_num = args.cycle
        else:
            row = conn.execute(
                "SELECT MAX(cycle) AS c FROM api_calls"
            ).fetchone()
            cycle_num = int(row["c"] or 0)

        cycle_usd = cycle_spend_usd(conn, cycle_num) if cycle_num > 0 else 0.0
        spend_15m = rolling_spend_usd(conn, minutes=15)
        spend_60m = rolling_spend_usd(conn, minutes=60)
        # Total: token-driven, all-time, error-free.
        try:
            rows = conn.execute(
                "SELECT model_id, "
                "  COALESCE(SUM(input_tokens), 0), "
                "  COALESCE(SUM(output_tokens), 0) "
                "FROM api_calls WHERE error IS NULL GROUP BY model_id"
            ).fetchall()
        except Exception:
            rows = []
        from .core.budget import _price_table as _bp_pt
        table = _bp_pt()
        total_usd = 0.0
        by_model: list[tuple[str, float]] = []
        for model_id, in_tok, out_tok in rows:
            in_price, out_price = table.get(model_id, (0.0, 0.0))
            c = (in_tok / 1_000_000.0) * in_price + (out_tok / 1_000_000.0) * out_price
            total_usd += c
            by_model.append((model_id, c))
        by_model.sort(key=lambda x: -x[1])

        # Band classification mirrors lib/cost.ts classifyCostRate().
        usd_per_min_15 = spend_15m / 15.0 if spend_15m > 0 else 0.0
        def _band(rate: float) -> str:
            if rate <= 0: return "off"
            if rate < 0.10: return "green"
            if rate <= 0.50: return "amber"
            return "red"
        band = _band(usd_per_min_15)

        cycle_cap = cycle_cost_cap_usd()
        hour_cap = rolling_hour_cap_usd()

        if args.json:
            import json as _json
            print(_json.dumps({
                "cycle": cycle_num,
                "cycle_spend_usd": round(cycle_usd, 4),
                "cycle_cap_usd": cycle_cap,
                "spend_15m_usd": round(spend_15m, 4),
                "spend_60m_usd": round(spend_60m, 4),
                "rolling_hour_cap_usd": hour_cap,
                "usd_per_min_15m": round(usd_per_min_15, 4),
                "band": band,
                "total_usd": round(total_usd, 4),
                "by_model": [{"model_id": m, "cost_usd": round(c, 4)} for m, c in by_model],
            }, indent=2))
        else:
            print(f"chimera cost  band={band}  ($/min over 15m: ${usd_per_min_15:.3f})")
            print(f"  cycle {cycle_num:>3d} spend  ${cycle_usd:>7.2f}  (cap ${cycle_cap:.2f})")
            print(f"  15m rolling    ${spend_15m:>7.2f}")
            print(f"  60m rolling    ${spend_60m:>7.2f}  (cap ${hour_cap:.2f})")
            print(f"  total          ${total_usd:>7.2f}")
            if by_model:
                print()
                print("  by model (descending):")
                for m, c in by_model[:6]:
                    short = m.split("/")[-1] if "/" in m else m
                    print(f"    {short:35s}  ${c:>7.2f}")
            # Visual cue for over-cap conditions even in non-JSON path.
            if cycle_cap > 0 and cycle_usd >= cycle_cap:
                print()
                print(f"  ⚠️  cycle spend OVER per-cycle cap (${cycle_cap:.2f})")
            if hour_cap > 0 and spend_60m >= hour_cap:
                print(f"  ⚠️  60m spend OVER rolling-hour cap (${hour_cap:.2f})")
        return 0

    if args.command == "split":
        # v4.63 (ADR 0082): task splitter preview.
        from .core.task_splitter import (
            is_splittable_shape,
            split_task as _split_task,
        )

        signal = is_splittable_shape(args.task)
        subtasks: list[str] = []
        provider_used = ""

        if not args.no_model and signal.splittable:
            # Resolve a sonnet-tier provider+model. Skip silently if no
            # API keys are available.
            from .providers import (
                AnthropicProvider, OpenRouterProvider,
            )
            from .providers import Provider as ProviderKind
            from .providers import select_rung
            providers: dict[ProviderKind, Any] = {}
            try:
                providers[ProviderKind.ANTHROPIC] = AnthropicProvider()
            except RuntimeError:
                pass
            try:
                providers[ProviderKind.OPENROUTER] = OpenRouterProvider()
            except RuntimeError:
                pass
            rung = select_rung("sonnet", requires_tools=False)
            provider = providers.get(rung.config.provider)
            if provider is not None:
                model_id = (
                    rung.config.model_id
                    if rung.config.provider is ProviderKind.ANTHROPIC
                    else rung.config.openrouter_model_id
                )
                provider_used = model_id
                from ._async_loop import run_on_persistent_loop
                subtasks = run_on_persistent_loop(_split_task(
                    args.task, provider=provider, model_id=model_id,
                ))

        if args.json:
            import json as _json
            print(_json.dumps({
                "task": args.task[:200],
                "splittable": signal.splittable,
                "confidence": signal.confidence,
                "reasons": signal.reasons,
                "model_used": provider_used,
                "subtasks": subtasks,
            }, indent=2))
            return 0

        print(
            f"chimera split  heuristic="
            f"{'SPLITTABLE' if signal.splittable else 'keep-as-one'}  "
            f"confidence={signal.confidence:.2f}"
        )
        for r in signal.reasons:
            print(f"  • {r}")
        if not signal.splittable:
            print("\n  No model call (heuristic says keep as one).")
            return 0
        if args.no_model:
            print("\n  --no-model: skipped model call.")
            return 0
        if not provider_used:
            print(
                "\n  No provider available (set ANTHROPIC_API_KEY or "
                "OPENROUTER_API_KEY); heuristic-only result above."
            )
            return 0
        if not subtasks:
            print(
                f"\n  Model ({provider_used}) declined to split or returned "
                "unparseable output. Keep as one."
            )
            return 0
        print(f"\n  Model ({provider_used}) proposed {len(subtasks)} sub-task(s):")
        for i, s in enumerate(subtasks, 1):
            print(f"\n  [{i}] {s}")
        print(
            "\n  To apply: manually edit mind/INBOX.md, mark the original "
            "task `[-]`, and add the sub-tasks as new `[ ]` lines."
        )
        return 0

    if args.command == "search":
        # v4.61 (ADR 0080): operator-facing FTS5 search over mind/wiki/.
        from .core import LoopConfig
        from .memory import open_and_init
        from .memory.wiki_search import (
            search_wiki,
            update_wiki_index,
            wiki_index_stats,
        )

        cfg = LoopConfig.from_env()
        conn = open_and_init(cfg.state_dir / "chimera.db")

        if args.rebuild:
            counts = update_wiki_index(conn, cfg.mind_dir / "wiki")
            if not args.json:
                churn = sum(v for k, v in counts.items() if k != "unchanged")
                print(
                    f"chimera search: index refresh — "
                    f"added={counts.get('added',0)} "
                    f"updated={counts.get('updated',0)} "
                    f"deleted={counts.get('deleted',0)} "
                    f"unchanged={counts.get('unchanged',0)}"
                )

        hits = search_wiki(conn, args.query, limit=args.limit)
        stats = wiki_index_stats(conn)

        if args.json:
            import json as _json
            print(_json.dumps({
                "query": args.query,
                "n_hits": len(hits),
                "indexed_files": stats.get("indexed_files", 0),
                "available": stats.get("available", False),
                "hits": [
                    {
                        "path": h.path, "title": h.title,
                        "snippet": h.snippet, "rank": h.rank,
                    }
                    for h in hits
                ],
            }, indent=2))
            return 0

        if not stats.get("available"):
            print("chimera search: FTS5 unavailable in this SQLite build.")
            return 1
        if not hits:
            print(
                f"chimera search: 0 hits for {args.query!r}  "
                f"(index has {stats.get('indexed_files', 0)} file(s))"
            )
            return 0
        print(
            f"chimera search: {len(hits)} hit(s) for {args.query!r}  "
            f"(of {stats.get('indexed_files', 0)} indexed file(s))"
        )
        for i, h in enumerate(hits, 1):
            print()
            print(f"  [{i}] {h.title or '(no title)'}  (rank={h.rank:.2f})")
            print(f"      mind/wiki/{h.path}")
            print(f"      {h.snippet.strip()}")
        return 0

    if args.command == "estimate":
        # v4.59 (ADR 0078): pre-flight INBOX cost projection.
        from .core import LoopConfig
        from .core.budget import cycle_cost_cap_usd, rolling_hour_cap_usd
        from .core.cost_estimate import estimate_inbox
        from .memory import open_and_init

        cfg = LoopConfig.from_env()
        conn = open_and_init(cfg.state_dir / "chimera.db")
        inbox = cfg.mind_dir / "INBOX.md"
        report = estimate_inbox(conn, inbox, default_tier=args.tier)

        cycle_cap = cycle_cost_cap_usd()
        hour_cap = rolling_hour_cap_usd()

        if args.json:
            import json as _json
            print(_json.dumps({
                "n_tasks": report.n_tasks,
                "total_usd": report.total_usd,
                "total_cycles": report.total_cycles,
                "cycle_cap_usd": cycle_cap,
                "rolling_hour_cap_usd": hour_cap,
                "tasks": [
                    {
                        "task_text": t.task_text[:200],
                        "tier": t.tier,
                        "model_id": t.model_id,
                        "estimated_cycles": t.estimated_cycles,
                        "estimated_usd": t.estimated_usd,
                        "used_history": t.used_history,
                        "n_historical_cycles": t.n_historical_cycles,
                        "prior_failures": t.prior_failures,
                    }
                    for t in report.tasks
                ],
            }, indent=2))
        else:
            print(f"chimera estimate  {report.n_tasks} open task(s)")
            if report.n_tasks == 0:
                print("  (inbox clear)")
                return 0
            print(
                f"  total estimate     ${report.total_usd:>7.2f}"
                f"  over ~{report.total_cycles} cycle(s)"
            )
            print(f"  per-cycle cap      ${cycle_cap:.2f}")
            print(f"  rolling-hour cap   ${hour_cap:.2f}")
            print()
            for i, t in enumerate(report.tasks, 1):
                src = "hist" if t.used_history else "tier-typical"
                short = t.model_id.split("/")[-1] if "/" in t.model_id else t.model_id
                preview = t.task_text.split("\n")[0][:60]
                print(
                    f"  [{i:2d}] ${t.estimated_usd:>7.2f}  "
                    f"tier={t.tier:6s}  cycles={t.estimated_cycles}  "
                    f"({src})  {short}"
                )
                print(f"        {preview}{'…' if len(t.task_text) > 60 else ''}")
            # Warnings:
            if cycle_cap > 0:
                tripped = [t for t in report.tasks if t.estimated_usd / t.estimated_cycles > cycle_cap]
                if tripped:
                    print()
                    print(
                        f"  ⚠️  {len(tripped)} task(s) project per-cycle spend "
                        f"> ${cycle_cap:.2f} cap; ACT will trip cost_cap on those."
                    )
            if hour_cap > 0 and report.total_usd > hour_cap:
                print()
                print(
                    f"  ⚠️  total projection ${report.total_usd:.2f} exceeds "
                    f"the rolling-60m cap ${hour_cap:.2f} — back-to-back cycles "
                    f"may trip rolling_hour_cap. Consider splitting the run."
                )
        return 0

    if args.command == "tiers":
        from .providers.tiers import TIER_LADDERS
        if args.json:
            import json as _json
            from .core import LoopConfig
            from datetime import datetime, timezone

            payload = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "tiers": {
                    tier: [
                        {
                            "model_id": r.config.model_id,
                            "openrouter_model_id": r.config.openrouter_model_id,
                            "provider": r.config.provider.value,
                            "input_cost_per_mtok": r.config.input_cost_per_mtok,
                            "output_cost_per_mtok": r.config.output_cost_per_mtok,
                            "context_tokens": r.capabilities.context_tokens,
                            "supports_tools": r.capabilities.supports_tools,
                        }
                        for r in rungs
                    ]
                    for tier, rungs in TIER_LADDERS.items()
                },
            }
            blob = _json.dumps(payload, indent=2)
            print(blob)
            cfg = LoopConfig.from_env()
            try:
                (cfg.state_dir / "tiers.json").write_text(blob, encoding="utf-8")
            except Exception:
                pass  # best-effort snapshot
            return 0
        for tier, rungs in TIER_LADDERS.items():
            print(f"chimera tiers: {tier} ({len(rungs)} rung(s))")
            for i, r in enumerate(rungs):
                cfg = r.config
                print(
                    f"  [{i}] {cfg.model_id:40s}  "
                    f"in=${cfg.input_cost_per_mtok:>5.2f}/Mtok  "
                    f"out=${cfg.output_cost_per_mtok:>5.2f}/Mtok  "
                    f"ctx={r.capabilities.context_tokens:>10,}"
                )
        return 0
    if args.command == "fragmentation":
        from .core.adaptation import list_fragmentation
        rows = list_fragmentation()
        if not rows:
            print("chimera fragmentation: (no records)")
            return 0
        print(f"chimera fragmentation: {len(rows)} record(s)")
        for r in rows:
            preview = r.task_text.split("\n")[0][:80]
            print(
                f"  cycle {r.cycle:3d}  rounds={r.rounds_used:2d}  "
                f"tools={r.tool_call_count:2d}  missing={len(r.missing_artifacts)}  "
                f"{preview}…"
            )
        return 0
    if args.command == "proposers":
        import json as _json
        from .core import LoopConfig
        from .core.proposer_scoring import (
            all_scores,
            get_status,
            list_statuses,
            pause,
            promote,
        )
        from .memory import open_and_init

        cfg = LoopConfig.from_env()
        conn = open_and_init(cfg.state_dir / "chimera.db")
        sub_cmd = args.proposers_command or "list"
        if sub_cmd == "list":
            scores = all_scores(conn)
            statuses = {s.proposer: s for s in list_statuses(conn)}
            if args.json:
                print(_json.dumps(
                    [
                        {
                            "proposer": s.proposer,
                            "accepted": s.accepted,
                            "rejected": s.rejected,
                            "decided": s.decided,
                            "rate": s.rate,
                            "window": s.window,
                            "status": (statuses.get(s.proposer).status
                                       if statuses.get(s.proposer) else "active"),
                        }
                        for s in scores
                    ],
                    indent=2,
                ))
                return 0
            if not scores:
                print("chimera proposers: (no mutations yet)")
                return 0
            print(f"chimera proposers: {len(scores)} type(s)")
            for s in scores:
                st = statuses.get(s.proposer)
                status_str = st.status if st else "active"
                rate_str = f"{s.rate:.0%}" if s.rate is not None else "--"
                print(
                    f"  {s.proposer:24s} {status_str:8s} "
                    f"rate={rate_str:>4s} ({s.accepted}/{s.decided} in last {s.window})"
                )
                if st and st.reason and st.status != "active":
                    print(f"    └─ {st.reason}")
            return 0
        if sub_cmd == "promote":
            st = promote(conn, args.proposer, reason=args.reason)
            print(f"chimera proposers: {st.proposer} → {st.status}")
            return 0
        if sub_cmd == "pause":
            st = pause(conn, args.proposer, reason=args.reason)
            print(f"chimera proposers: {st.proposer} → {st.status}")
            return 0
        print(f"chimera proposers: unknown subcommand {sub_cmd!r}")
        return 2

    if args.command == "evals":
        sub_cmd = getattr(args, "evals_command", None)
        if sub_cmd == "longmemeval":
            return _cmd_evals_longmemeval(args)
        if sub_cmd == "locomo":
            return _cmd_evals_locomo(args)
        parser.error(f"unknown evals subcommand: {sub_cmd}")
        return 2

    if args.command == "escalations":
        import json as _json
        from .core import LoopConfig
        from .core.escalation import (
            clear_escalations,
            escalation_summary,
            hot_signatures,
            list_escalations,
            prune_escalations,
        )
        from .memory import open_and_init

        cfg = LoopConfig.from_env()
        conn = open_and_init(cfg.state_dir / "chimera.db")
        sub_cmd = args.escalations_command or "list"
        if sub_cmd == "list":
            rows = list_escalations(
                conn, limit=args.limit, signature_substring=args.grep,
            )
            if args.json:
                print(_json.dumps(
                    [
                        {
                            "id": r.id,
                            "signature": r.signature,
                            "task_text": r.task_text,
                            "tier": r.tier,
                            "finish_reason": r.finish_reason,
                            "rounds_used": r.rounds_used,
                            "cycle": r.cycle,
                            "created_at": r.created_at,
                        }
                        for r in rows
                    ],
                    indent=2, default=str,
                ))
                return 0
            if not rows:
                print("chimera escalations: (none)")
                return 0
            print(f"chimera escalations: {len(rows)} row(s)")
            for r in rows:
                preview = r.task_text.split("\n")[0][:70]
                print(
                    f"  cycle {r.cycle:3d}  tier={r.tier:6s} "
                    f"reason={r.finish_reason:22s} rounds={r.rounds_used:2d}  "
                    f"{preview}…"
                )
            return 0
        if sub_cmd == "summary":
            summary = escalation_summary(conn)
            if args.json:
                print(_json.dumps(summary, indent=2, default=str))
                return 0
            if not summary:
                print("chimera escalations summary: (none)")
            else:
                print(f"chimera escalations summary: {len(summary)} signature(s)")
                for sig, by_tier in sorted(
                    summary.items(), key=lambda kv: -sum(kv[1].values()),
                )[:20]:
                    bits = ", ".join(f"{t}×{n}" for t, n in sorted(by_tier.items()))
                    tokens = (sig.split(",")[:5]) or ["(empty)"]
                    preview = " ".join(tokens) + ("…" if len(sig.split(",")) > 5 else "")
                    print(f"  {bits:30s}  tokens: {preview}")
            # v4.54 (ADR 0073): A17 — surface hot signatures (≥2 failures)
            # at the bottom of the summary so the operator sees them
            # without an extra command. These are the candidates for
            # task-text rewriting rather than tier promotion.
            hot = hot_signatures(conn, threshold=2)
            if hot:
                print()
                print(f"⚠️  HOT SIGNATURES (≥2 failures — review task text, do not just promote tier):")
                for h in hot[:10]:
                    tiers = "/".join(h.tiers) if h.tiers else "?"
                    print(
                        f"  ×{h.total_failures}  tiers={tiers:18s}  "
                        f"cycles={h.first_seen_cycle}→{h.last_seen_cycle}  "
                        f"last={h.last_finish_reason}"
                    )
                    if h.excerpt:
                        print(f"      {h.excerpt}…")
            return 0
        if sub_cmd == "clear":
            if not args.grep and not args.all:
                parser.error(
                    "`escalations clear` requires --grep <substr> OR --all "
                    "(safety guard; the agent uses these rows to learn)."
                )
            n = clear_escalations(conn, signature_substring=args.grep)
            if args.json:
                print(_json.dumps({"deleted_rows": n}))
                return 0
            print(f"chimera escalations: deleted {n} row(s)")
            return 0
        if sub_cmd == "prune":
            n = prune_escalations(conn, args.older_than_days)
            if args.json:
                print(_json.dumps({"deleted": n}, indent=2, default=str))
                return 0
            print(f"chimera escalations: pruned {n} row(s)")
            return 0
        parser.error(f"unknown escalations subcommand: {sub_cmd}")
    if args.command == "doctor":
        from pathlib import Path as _Path
        from .core import checkpoint_wal, run_checks
        if getattr(args, "install_hooks", False):
            from .hooks import install_pre_commit_hook
            result = install_pre_commit_hook(_Path.cwd())
            marker = {
                "installed": "✓", "already_installed": "✓",
                "foreign_hook": "!", "no_git_dir": "!",
            }.get(result.status, "?")
            print(f"chimera doctor --install-hooks: [{marker}] {result.message}")
        if getattr(args, "fix", False):
            state_dir = _Path(os.environ.get("CHIMERA_STATE_DIR", "state"))
            ok, msg = checkpoint_wal(state_dir)
            marker = "✓" if ok else "✗"
            print(f"chimera doctor --fix: [{marker}] wal_checkpoint {msg}")
        results = run_checks()
        rc = 0
        if getattr(args, "json", False):
            import json as _json
            payload = {
                "command": "doctor",
                "checks": [
                    {"name": r.name, "status": r.status, "message": r.message}
                    for r in results
                ],
            }
            print(_json.dumps(payload, indent=2, default=str))
            rc = 1 if any(r.status == "error" for r in results) else 0
            return rc
        print("chimera doctor:")
        for r in results:
            marker = {"ok": "✓", "warn": "!", "error": "✗"}.get(r.status, "?")
            print(f"  [{marker}] {r.name:24s} {r.message}")
            if r.status == "error":
                rc = 1
        return rc
    if args.command == "status":
        from .core import load_heartbeat, LoopConfig
        cfg = LoopConfig.from_env()
        state, _ = load_heartbeat(cfg.mind_dir / "HEARTBEAT.md")
        print(
            f"chimera: cycle={state.cycle} trust_tier={state.trust_tier} "
            f"status={state.status} session_started_at={state.session_started_at}"
        )
        return 0
    if args.command == "run":
        from .core import ChimeraLoop, LoopConfig
        # ADR 0141 Layer 2: refuse to start in the main worktree on a
        # non-main branch (chip-branch-jump papercut). BEFORE any provider
        # spend. Override: CHIMERA_ALLOW_MAIN_BRANCH_DRIFT=1.
        from .core.doctor import detect_main_worktree_branch_drift
        if not os.environ.get("CHIMERA_ALLOW_MAIN_BRANCH_DRIFT", "").strip():
            signal = detect_main_worktree_branch_drift(Path.cwd())
            if signal.drifted:
                msg = (
                    "ERROR: chimera run refuses to operate in the main worktree "
                    "on a non-main branch.\n\n"
                    f"  worktree : {signal.toplevel}\n"
                    f"  branch   : {signal.branch}\n\n"
                    "This is the chip-branch-jump papercut "
                    "(ADR 0114 / PR #46 / ADR 0141).\nTo recover:\n\n"
                    "  1. Stash any uncommitted work:  "
                    "git stash push -u -m \"chip-recovery-$(date +%s)\"\n"
                    "  2. Switch back to main:         git checkout main\n"
                    "  3. Move the chip work to a fresh worktree:\n"
                    f"     git worktree add ../<dir> {signal.branch}\n"
                    "     cd ../<dir>\n"
                    "  4. Restore your work in the new worktree: git stash pop\n\n"
                    "Override (operator-aware, single-use): "
                    "export CHIMERA_ALLOW_MAIN_BRANCH_DRIFT=1"
                )
                print(msg, file=sys.stderr)
                return 2
        # v4.41: honour the optional ad-hoc prompt — append it to INBOX.md
        # so ASSESS picks it up as an open task on this cycle.
        if args.prompt:
            cfg = LoopConfig.from_env()
            inbox = cfg.mind_dir / "INBOX.md"
            inbox.parent.mkdir(parents=True, exist_ok=True)
            existing = inbox.read_text(encoding="utf-8") if inbox.exists() else "# Inbox\n"
            if not existing.endswith("\n"):
                existing += "\n"
            with inbox.open("a", encoding="utf-8") as fh:
                if not existing.startswith("# "):
                    fh.write("# Inbox\n")
                fh.write(f"- [ ] {args.prompt}\n")
            print(f"chimera run: enqueued task to {inbox}")
        _loop = ChimeraLoop()
        try:
            from ._async_loop import run_on_persistent_loop
            report = run_on_persistent_loop(_loop.run_one_cycle())
        finally:
            # v4.75: ensure WAL is checkpointed at the end of every cycle.
            _loop.close()
        for line in report.phase_log:
            print(f"  {line}")
        if report.phase_times_ms:
            timings = "  ".join(
                f"{k}={v:.0f}ms" for k, v in report.phase_times_ms.items()
            )
            print(f"  timings: {timings}")
        print(
            f"cycle {report.cycle}: tasks_seen={report.tasks_seen} "
            f"flipped={report.tasks_completed} rotated={report.rotated}"
        )
        return 0
    if args.command == "charter":
        return _cmd_charter(args)
    if args.command == "verify":
        return _cmd_verify(args)
    if args.command == "faithfulness":
        return _cmd_faithfulness(args)
    if args.command == "review":
        return _cmd_review(args)
    if args.command == "critic-calibrate":
        return _cmd_critic_calibrate(args)
    if args.command == "self-scan":
        return _cmd_self_scan(args)
    if args.command == "ping":
        targets = ["anthropic", "openrouter"] if args.provider == "both" else [args.provider]
        print("chimera ping:")
        rc = 0
        from ._async_loop import run_on_persistent_loop
        for t in targets:
            rc |= run_on_persistent_loop(_ping_provider(t))
        return rc
    if args.command == "serve":
        from .server import serve_http, serve_stdio
        if args.http:
            return asyncio.run(
                serve_http(host=args.host, port=args.port, name=args.name)
            )
        return asyncio.run(serve_stdio(name=args.name))
    if args.command == "peers":
        from .a2a import forget as _forget_peer
        from .a2a import list_peers as _list_peers
        from .a2a import registry_dir as _registry_dir
        from .a2a import sweep_stale as _sweep_stale

        sub_cmd = args.peers_command or "list"
        if sub_cmd == "list":
            entries = _list_peers()
            d = _registry_dir()
            if not entries:
                print(f"chimera peers: (registry dir {d} is empty)")
                return 0
            print(f"chimera peers ({len(entries)} entries in {d}):")
            for e in entries:
                caps = ", ".join(e.capabilities)
                print(
                    f"  {e.agent_id}  v{e.version}  host={e.host}  pid={e.pid}  "
                    f"transport={e.reach.get('transport', '?')}\n    caps: {caps}"
                )
            return 0
        if sub_cmd == "forget":
            ok = _forget_peer(args.agent_id)
            print(f"chimera peers: {'removed' if ok else 'not found'} — {args.agent_id}")
            return 0 if ok else 1
        if sub_cmd == "sweep":
            n = _sweep_stale()
            print(f"chimera peers: removed {n} stale entr(ies)")
            return 0
        if sub_cmd == "sync":
            from .a2a import sync_remote_peers
            urls = None
            if args.urls:
                urls = [u.strip() for u in args.urls.split(",") if u.strip()]
            result = sync_remote_peers(urls)
            print(
                f"chimera peers sync: fetched={result.fetched} "
                f"added={result.added} updated={result.updated} "
                f"failed={len(result.failures)}"
            )
            for url, err in result.failures:
                print(f"  ! {url}: {err}")
            return 0 if not result.failures else 1
        if sub_cmd == "sweep-remote":
            from .a2a import sweep_remote_stale
            n = sweep_remote_stale(max_age_hours=args.max_age_hours)
            print(f"chimera peers: removed {n} stale remote entr(ies)")
            return 0
        if sub_cmd == "kfm":
            from .a2a import fetch_peer_kfm, list_peer_chimeras
            from .core import ChimeraLoop
            from .tools import register_mcp_servers_from_env

            loop = ChimeraLoop()
            from ._async_loop import run_on_persistent_loop
            run_on_persistent_loop(register_mcp_servers_from_env(loop._registry))  # type: ignore[attr-defined]
            targets: list[str]
            if args.name:
                targets = [args.name]
            else:
                targets = list_peer_chimeras(loop._registry)  # type: ignore[attr-defined]
            if not targets:
                print("chimera peers kfm: no peer Chimeras discovered via MCP.")
                loop.close()
                return 0
            import json as _json
            print(f"chimera peers kfm: querying {len(targets)} peer(s)...")
            for t in targets:
                try:
                    snap = run_on_persistent_loop(fetch_peer_kfm(t, registry=loop._registry))  # type: ignore[attr-defined]
                    print(f"  {t}:")
                    for k, v in sorted(snap.items()):
                        print(f"    {k}: {v}")
                except Exception as exc:
                    print(f"  {t}: error: {exc}")
            loop.close()
            return 0
        if sub_cmd == "cards":
            return _cmd_peers_cards(args)
        if sub_cmd == "ask":
            return _cmd_peers_ask(args)
        parser.error(f"unknown peers subcommand: {sub_cmd}")
        return 2
    if args.command == "a2a":
        from .a2a import AgentIdentity, list_xenocomm_tools
        from .core import ChimeraLoop
        from .tools import register_mcp_servers_from_env

        sub_cmd = args.a2a_command or "identity"
        if sub_cmd == "identity":
            ident = AgentIdentity()
            import json as _json
            print(_json.dumps(ident.to_dict(), indent=2))
            return 0
        if sub_cmd == "peers":
            loop = ChimeraLoop()
            from ._async_loop import run_on_persistent_loop
            run_on_persistent_loop(register_mcp_servers_from_env(loop._registry))  # type: ignore[attr-defined]
            tools = list_xenocomm_tools(loop._registry)  # type: ignore[attr-defined]
            loop.close()
            if not tools:
                print(
                    "chimera a2a: no Xenocomm tools discovered. "
                    "Set CHIMERA_MCP_SERVERS to include a 'xenocomm' entry "
                    "(see docs/adr/0004-xenocomm-a2a.md)."
                )
                return 0
            print(f"chimera a2a: {len(tools)} Xenocomm tool(s) discovered:")
            for t in tools:
                print(f"  - {t}")
            return 0
        parser.error(f"unknown a2a subcommand: {sub_cmd}")
        return 2
    if args.command == "trust":
        import json as _json
        from .core import LoopConfig
        from .trust import TrustManager

        cfg = LoopConfig.from_env()
        tm = TrustManager(cfg.state_dir / "trust_state.json")
        sub_cmd = args.trust_command or "show"

        def _parse_tier(value: str) -> int:
            v = value.strip().upper()
            if v.startswith("T"):
                v = v[1:]
            try:
                n = int(v)
            except ValueError:
                parser.error(f"invalid --tier {value!r}; expected T0..T5")
            if not 0 <= n <= 5:
                parser.error(f"--tier out of range: {value!r} (T0..T5)")
            return n

        if sub_cmd == "show":
            if getattr(args, "json", False):
                print(_json.dumps(tm.state.to_dict(), indent=2, sort_keys=True))
                return 0
            print(f"chimera trust: {tm.tier.name} ({tm.tier.label})")
            print(f"  hours_in_tier: {tm.hours_in_current_tier():.2f}")
            print(f"  last_readiness: {tm.state.last_readiness:.2f}")
            recent = tm.state.history[-5:]
            if recent:
                print("  recent events:")
                for ev in recent:
                    print(
                        f"    {ev.timestamp} {ev.kind:11s} "
                        f"T{ev.from_tier}→T{ev.to_tier}  {ev.reason}"
                    )
            return 0
        if sub_cmd == "promote":
            from_tier = tm.tier
            if getattr(args, "tier", None) is None:
                ok = tm.promote(reason=args.reason)
            else:
                target = _parse_tier(args.tier)
                ok = tm.set_tier(target, reason=args.reason, kind="operator")
            if not ok:
                print(f"chimera trust: no-op → {tm.tier.name}")
                return 1
            print(
                f"chimera trust: promoted {from_tier.name} → {tm.tier.name} "
                f"({tm.tier.label})  reason={args.reason!r}"
            )
            return 0
        if sub_cmd == "demote":
            ok = tm.demote(reason=args.reason)
            print(f"chimera trust: {'demoted' if ok else 'no-op'} → {tm.tier.name}")
            return 0 if ok else 1
        if sub_cmd == "revoke":
            from_tier = tm.tier
            target = _parse_tier(args.tier) if getattr(args, "tier", None) is not None else 0
            ok = tm.set_tier(target, reason=args.reason, kind="revoke")
            if not ok:
                print(f"chimera trust: no-op (already at {tm.tier.name})")
                return 1
            print(
                f"chimera trust: revoked {from_tier.name} → {tm.tier.name} "
                f"({tm.tier.label})  reason={args.reason!r}"
            )
            return 0
        if sub_cmd == "lockdown":
            ok = tm.lockdown(reason=args.reason)
            print(f"chimera trust: {'locked down' if ok else 'no-op (already T0)'}")
            return 0 if ok else 1
        if sub_cmd == "budget":
            limit = max(1, int(getattr(args, "limit", 10) or 10))
            hours = tm.hours_in_current_tier()
            dwell_hours_required = tm.min_dwell_seconds / 3600.0
            history = list(tm.state.history)[-limit:]
            if getattr(args, "json", False):
                payload = {
                    "tier": tm.tier.value,
                    "tier_name": tm.tier.name,
                    "tier_label": tm.tier.label,
                    "hours_in_tier": round(hours, 2),
                    "last_readiness": tm.state.last_readiness,
                    "promotion_threshold": tm.promotion_threshold,
                    "dwell_hours_required": dwell_hours_required,
                    "history": [
                        {
                            "timestamp": ev.timestamp,
                            "kind": ev.kind,
                            "from_tier": ev.from_tier,
                            "to_tier": ev.to_tier,
                            "reason": ev.reason,
                        }
                        for ev in history
                    ],
                }
                print(_json.dumps(payload, indent=2, sort_keys=True))
                return 0
            print(
                f"chimera trust budget: {tm.tier.name} ({tm.tier.label})  "
                f"tier={tm.tier.value}"
            )
            print(f"  hours_in_tier:        {hours:.2f}")
            print(f"  last_readiness:       {tm.state.last_readiness:.2f}")
            print(
                f"  next promotion:       readiness ≥ "
                f"{tm.promotion_threshold:.2f}  dwell ≥ "
                f"{dwell_hours_required:.2f}h"
            )
            if tm.tier.value >= 5:
                print("  (already at T5 — no further promotion)")
            if history:
                print(f"  recent events (last {len(history)}):")
                for ev in history:
                    print(
                        f"    {ev.timestamp} {ev.kind:11s} "
                        f"T{ev.from_tier}→T{ev.to_tier}  {ev.reason}"
                    )
            else:
                print("  recent events: (none)")
            return 0
        if sub_cmd == "degrade-check":
            from .core.mind import append_session_log

            baseline = int(args.baseline)
            if not 0 <= baseline <= 5:
                parser.error(f"--baseline out of range: {baseline} (0..5)")
            current = tm.tier.value
            drop = baseline - current
            threshold = max(1, int(args.threshold_drop))
            degraded = drop >= threshold or (current == 0 and baseline > 0)

            recent_demotes = [
                ev for ev in tm.state.history
                if ev.kind in ("demote", "lockdown")
            ][-max(1, int(args.history_limit)):]

            promoted_to: int | None = None
            auto_promote_skipped_reason: str | None = None
            if degraded and args.auto_promote and current < baseline:
                # v4.119 (ADR 0119): sticky detector-finding demotes.
                # Only auto-promote when the most recent demote was a
                # drift-score regression (reason starts with
                # "drift demote_plan:"). Detector findings and operator
                # actions are sticky until an operator promotes manually.
                last_demote = next(
                    (
                        ev for ev in reversed(tm.state.history)
                        if ev.kind in ("demote", "lockdown", "operator")
                        and ev.to_tier < ev.from_tier
                    ),
                    None,
                )
                sticky = (
                    last_demote is not None
                    and not last_demote.reason.startswith("drift demote_plan:")
                )
                if sticky:
                    auto_promote_skipped_reason = last_demote.reason
                elif tm.promote(reason=(
                    f"v4.95 auto-promote-on-degrade: baseline=T{baseline} "
                    f"current=T{current} drop={drop}"
                )):
                    promoted_to = tm.tier.value

            chronicle_written = False
            if degraded and args.chronicle_path:
                from datetime import datetime, timezone
                stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
                lines = [
                    f"- {stamp} ⚠️  trust degradation: baseline=T{baseline} "
                    f"current=T{tm.tier.value} drop={drop} threshold={threshold}"
                ]
                for ev in recent_demotes:
                    lines.append(
                        f"    · {ev.timestamp} {ev.kind} "
                        f"T{ev.from_tier}→T{ev.to_tier}  {ev.reason}"
                    )
                if promoted_to is not None:
                    lines.append(
                        f"    · auto-promoted to T{promoted_to} "
                        f"(--auto-promote)"
                    )
                if auto_promote_skipped_reason is not None:
                    lines.append(
                        f"    · auto-promote skipped (sticky demote): "
                        f"{auto_promote_skipped_reason}"
                    )
                from pathlib import Path as _Path
                append_session_log(_Path(args.chronicle_path), "\n".join(lines))
                chronicle_written = True

            payload = {
                "baseline_tier": baseline,
                "current_tier": tm.tier.value,
                "drop": baseline - tm.tier.value,
                "threshold_drop": threshold,
                "degraded": degraded,
                "auto_promoted_to": promoted_to,
                "auto_promote_skipped_reason": auto_promote_skipped_reason,
                "chronicle_written": chronicle_written,
                "recent_demotes": [
                    {
                        "timestamp": ev.timestamp,
                        "kind": ev.kind,
                        "from_tier": ev.from_tier,
                        "to_tier": ev.to_tier,
                        "reason": ev.reason,
                    }
                    for ev in recent_demotes
                ],
            }

            if getattr(args, "json", False):
                print(_json.dumps(payload, indent=2, sort_keys=True))
            else:
                status = "DEGRADED" if degraded else "ok"
                print(
                    f"chimera trust degrade-check: {status}  "
                    f"baseline=T{baseline} current=T{tm.tier.value} "
                    f"drop={baseline - tm.tier.value} threshold={threshold}"
                )
                if degraded and recent_demotes:
                    print("  recent demote events:")
                    for ev in recent_demotes:
                        print(
                            f"    {ev.timestamp} {ev.kind:11s} "
                            f"T{ev.from_tier}→T{ev.to_tier}  {ev.reason}"
                        )
                if promoted_to is not None:
                    print(f"  auto-promoted to T{promoted_to}")
                if auto_promote_skipped_reason is not None:
                    print(
                        f"  auto-promote skipped (sticky demote): "
                        f"{auto_promote_skipped_reason}"
                    )
                if chronicle_written:
                    print(f"  chronicle warning appended: {args.chronicle_path}")
            return 10 if degraded else 0
        parser.error(f"unknown trust subcommand: {sub_cmd}")
        return 2
    if args.command == "mutations":
        from .core import LoopConfig
        from .memory import (
            approve_mutation as _approve,
            get_mutation as _get,
            list_mutations as _list,
            open_and_init,
            queue_health as _queue_health,
            reject_mutation as _reject,
        )
        import json as _json

        cfg = LoopConfig.from_env()
        conn = open_and_init(cfg.state_dir / "chimera.db")
        sub_cmd = args.mut_command or "list"
        if sub_cmd == "list":
            rows = _list(conn, status="pending")
            if not rows:
                print("(no pending mutations)")
                return 0
            print(f"{len(rows)} pending mutation(s):")
            for m in rows:
                payload_preview = _json.dumps(m.payload)[:100]
                print(f"  #{m.id:3d}  [{m.type}]  {payload_preview}")
            return 0
        if sub_cmd == "show":
            m = _get(conn, args.id)
            if m is None:
                print(f"mutation #{args.id} not found")
                return 1
            print(f"#{m.id}  [{m.type}]  status={m.status}")
            print(f"created_at: {m.created_at}")
            print(f"approved_at: {m.approved_at}")
            print(f"applied_at: {m.applied_at}")
            print(f"reason: {m.reason}")
            print(f"payload:\n{_json.dumps(m.payload, indent=2)}")
            return 0
        if sub_cmd == "approve":
            try:
                m = _approve(conn, args.id, reason=args.reason)
            except ValueError as e:
                print(f"error: {e}")
                return 1
            print(f"approved mutation #{m.id} ({m.type})")
            return 0
        if sub_cmd == "reject":
            try:
                m = _reject(conn, args.id, reason=args.reason)
            except ValueError as e:
                print(f"error: {e}")
                return 1
            print(f"rejected mutation #{m.id} ({m.type})")
            return 0
        if sub_cmd == "apply":
            # v4.65 (ADR 0084): apply an approved mutation. Currently
            # supports type="task_split" (rewrites mind/INBOX.md);
            # other types still apply via their own bespoke pipelines
            # (ontology --apply-kills, skills assemble, etc.).
            m = _get(conn, args.id)
            if m is None:
                print(f"mutation #{args.id} not found")
                return 1
            if m.type == "task_split":
                from .core.task_split_proposal import apply_task_split
                result = apply_task_split(
                    conn, args.id, cfg.mind_dir / "INBOX.md",
                )
                if not result["ok"]:
                    print(f"error: {result['reason']}")
                    return 1
                print(
                    f"applied mutation #{args.id} (task_split): "
                    f"{result['reason']}"
                )
                return 0
            print(
                f"mutation #{m.id} type={m.type!r} has no `chimera mutations "
                "apply` handler. Try the type-specific verb (e.g. "
                "`chimera ontology --apply-kills`)."
            )
            return 1
        if sub_cmd == "health":
            snap = _queue_health(conn)
            if getattr(args, "json", False):
                print(_json.dumps(snap, indent=2, sort_keys=True))
                return 0
            counts = snap["counts"]
            total = sum(counts.values())
            print(f"mutation queue: {total} total")
            for st in (
                "pending",
                "approved",
                "applied",
                "rejected",
                "expired",
                "failed",
            ):
                n = counts.get(st, 0)
                if n:
                    print(f"  {st:9s} {n:4d}")
            age = snap["pending_oldest_age_seconds"]
            if age is not None:
                print(f"oldest pending: {age}s ago")
            rmax = snap["pending_recurrence_max"]
            rsum = snap["pending_recurrence_total"]
            if rmax or rsum:
                print(
                    f"pending recurrence: max={rmax} total={rsum}  "
                    "(duplicates absorbed in-place)"
                )
            ar = snap["approved_ratio"]
            if ar is not None:
                print(f"applied / decided: {ar:.0%}")
            return 0
        parser.error(f"unknown mutations subcommand: {sub_cmd}")
        return 2
    if args.command == "skills":
        from .core import LoopConfig
        from .memory import (
            get_mutation as _get,
            mark_applied as _mark_applied,
            mark_failed as _mark_failed,
            open_and_init,
        )
        from .skills import (
            SkillSpec,
            activate_skill,
            assemble_skill,
            dynamic_skills_dir,
            load_dynamic_skills,
            validate_skill,
        )
        from .core.act import ActExecutor
        from .tools import ToolRegistry, register_core_tools

        sub_cmd = args.skills_command or "list"

        if sub_cmd == "list":
            reg = ToolRegistry()
            register_core_tools(reg)
            loaded = load_dynamic_skills(reg)
            print(f"chimera skills: {len(loaded)} dynamic skill(s) loaded")
            for name in loaded:
                entry = reg.get(name)
                desc = entry.description if entry else ""
                print(f"  - {name}: {desc}")
            return 0

        if sub_cmd == "assemble":
            cfg = LoopConfig.from_env()
            conn = open_and_init(cfg.state_dir / "chimera.db")
            mutation = _get(conn, args.mutation_id)
            if mutation is None:
                print(f"mutation #{args.mutation_id} not found")
                return 1
            if mutation.type != "skill_proposal":
                print(f"mutation #{args.mutation_id} is type={mutation.type!r}, not 'skill_proposal'")
                return 1
            if mutation.status != "approved":
                print(
                    f"mutation #{args.mutation_id} is status={mutation.status!r}; "
                    "must be 'approved' (run `chimera mutations approve {id}` first)"
                )
                return 1

            try:
                spec = SkillSpec(
                    name=mutation.payload.get("name", ""),
                    description=mutation.payload.get("description", ""),
                    brief=mutation.payload.get("brief", ""),
                )
            except ValueError as exc:
                _mark_failed(conn, mutation.id, reason=f"bad spec: {exc}")
                print(f"bad SkillSpec: {exc}")
                return 1

            # Construct providers via ACT executor helper.
            ax = ActExecutor.from_env(dispatcher=None, db=conn)  # type: ignore[arg-type]
            if ax is None:
                print("no provider keys; cannot assemble")
                return 1

            from .skills import assemble_with_escalation, record_assembly

            print(f"assembling skill {spec.name!r} (with tier escalation)...")
            from ._async_loop import run_on_persistent_loop
            ladder = run_on_persistent_loop(
                assemble_with_escalation(
                    spec,
                    providers=ax.providers,
                    db=conn,
                    cycle=-1,
                )
            )
            try:
                record_assembly(mutation.id, spec.name, ladder)
            except Exception:
                pass  # journal write is best-effort
            for att in ladder.attempts:
                if not att.assembled_ok:
                    print(f"  [{att.tier}] assembly failed: {att.failure_reason}")
                    continue
                line = (
                    f"  [{att.tier}] base={int(att.validation_score * 100)}%"
                )
                if att.revised:
                    rev = int((att.revised_score or 0.0) * 100)
                    line += f"  revised={rev}%"
                if att.witnesses:
                    line += f"  witnesses={','.join(att.witnesses)}"
                if att.winning_witness:
                    line += f"  winner={att.winning_witness}"
                line += f"  ok={att.validation_ok or bool(att.winning_witness)}"
                print(line)
            assembled = ladder.assembled
            validation = ladder.validation
            if ladder.winning_tier is None:
                _mark_failed(
                    conn, mutation.id,
                    reason=(
                        f"ladder exhausted: last failure "
                        f"{validation.failure_reason or 'unknown'}"
                    ),
                )
                print("ladder exhausted; no tier produced a valid skill.")
                return 1
            print(f"  winning tier: {ladder.winning_tier}")
            print(f"  schema: {assembled.schema['function']['name']}")
            print(f"  samples: {len(assembled.samples)}")
            print(
                f"  validation: passed {validation.passed}/{validation.total} "
                f"(score={validation.score:.2f}, ok={validation.ok})"
            )

            print("activating...")
            result = activate_skill(assembled, validation)
            if not result.ok:
                _mark_failed(conn, mutation.id, reason=f"activation: {result.failure_reason}")
                print(f"activation failed: {result.failure_reason}")
                return 1
            print(f"  written to: {result.path}")
            print(f"  registered as: {result.tool_name}")
            _mark_applied(conn, mutation.id, reason=f"activated at {result.path}")
            return 0

        parser.error(f"unknown skills subcommand: {sub_cmd}")
        return 2
    if args.command == "engines":
        from .core import ChimeraLoop

        if args.engines_command != "run":
            parser.error("engines: expected 'run <name>'")
        loop = ChimeraLoop()
        from ._async_loop import run_on_persistent_loop
        result = run_on_persistent_loop(loop.force_run_engine(args.name))
        loop.close()
        print(f"chimera engines run {args.name}:")
        print(f"  skipped: {result.skipped}")
        print(f"  api_calls: {result.api_call_count}")
        if result.failure_reason:
            print(f"  failure: {result.failure_reason}")
            return 1
        print(f"  artifacts: {result.artifacts}")
        print(f"  summary: {result.summary}")
        return 0
    if args.command == "ontology":
        from .core import LoopConfig
        from .memory import (
            apply_approved_kills,
            audit_ontology,
            auto_archive_stale_deprecated,
            list_entities,
            list_transitions,
            open_and_init,
            propose_kill_archived,
        )
        import json as _json

        cfg = LoopConfig.from_env()
        conn = open_and_init(cfg.state_dir / "chimera.db")

        if getattr(args, "propose_kills", False):
            row = conn.execute(
                "SELECT COALESCE(MAX(cycle), 0) AS c FROM agent_activity_log"
            ).fetchone()
            cycle = args.cycle if args.cycle is not None else (int(row["c"]) if row else 0)
            proposed = propose_kill_archived(
                conn,
                current_cycle=cycle,
                archive_after_cycles=args.archive_after_cycles,
                dry_run=args.dry_run,
            )
            verb = "would propose" if args.dry_run else "queued"
            print(
                f"chimera ontology --propose-kills @ cycle {cycle} "
                f"(ARCHIVED >= {args.archive_after_cycles} cycles): "
                f"{verb} {len(proposed)} kill_entity mutation(s)"
            )
            for e in proposed:
                print(
                    f"  [{e['kind']:8s}] {e['name']}  "
                    f"({e['cycles_in_state']} cycles in ARCHIVED)"
                )
            if proposed and not args.dry_run:
                print("Next: `chimera mutations list` → approve → `chimera ontology --apply-kills`")
            return 0
        if getattr(args, "apply_kills", False):
            row = conn.execute(
                "SELECT COALESCE(MAX(cycle), 0) AS c FROM agent_activity_log"
            ).fetchone()
            cycle = args.cycle if args.cycle is not None else (int(row["c"]) if row else 0)
            killed = apply_approved_kills(conn, current_cycle=cycle)
            print(
                f"chimera ontology --apply-kills @ cycle {cycle}: "
                f"killed {len(killed)} entit{'y' if len(killed) == 1 else 'ies'}"
            )
            for k in killed:
                print(f"  #{k['mutation_id']:4d}  [{k.get('kind','?'):8s}] {k.get('name','?')}")
            return 0
        if getattr(args, "archive_stale", False):
            row = conn.execute(
                "SELECT COALESCE(MAX(cycle), 0) AS c FROM agent_activity_log"
            ).fetchone()
            cycle = args.cycle if args.cycle is not None else (int(row["c"]) if row else 0)
            archived = auto_archive_stale_deprecated(
                conn,
                current_cycle=cycle,
                archive_after_cycles=args.archive_after_cycles,
                dry_run=args.dry_run,
            )
            verb = "would archive" if args.dry_run else "archived"
            print(
                f"chimera ontology --archive-stale @ cycle {cycle} "
                f"(after >= {args.archive_after_cycles} cycles): "
                f"{verb} {len(archived)}"
            )
            for e in archived:
                print(
                    f"  [{e['kind']:8s}] {e['name']}  "
                    f"({e['cycles_in_state']} cycles in DEPRECATED)"
                )
            return 0

        if getattr(args, "audit", False):
            # Reference cycle: explicit > inferred from activity log > 0.
            cycle = args.cycle
            if cycle is None:
                row = conn.execute(
                    "SELECT COALESCE(MAX(cycle), 0) AS c FROM agent_activity_log"
                ).fetchone()
                cycle = int(row["c"]) if row else 0
            snap = audit_ontology(
                conn,
                current_cycle=cycle,
                stale_after_cycles=args.stale_after_cycles,
            )
            if args.json:
                print(_json.dumps(snap, indent=2, sort_keys=True))
                return 0
            print(
                f"chimera ontology audit @ cycle {cycle}  "
                f"(stale>={args.stale_after_cycles})"
            )
            print(f"  total entities: {snap['total_entities']}")
            if snap["by_kind"]:
                print("  by kind:")
                for k, n in sorted(snap["by_kind"].items()):
                    print(f"    {k:10s} {n}")
            if snap["by_state"]:
                print("  by state:")
                for s, n in sorted(snap["by_state"].items()):
                    print(f"    {s:12s} {n}")
            print(f"  stale: {snap['stale_count']}")
            for e in snap["stale_entities"]:
                print(
                    f"    [{e['kfm_state']:11s}] {e['kind']:8s} {e['name']}  "
                    f"({e['cycles_in_state']} cycles in state)"
                )
            print(f"  dead: {snap['dead_count']} (no activity in last "
                  f"{snap['thresholds']['activity_window_cycles']} cycles)")
            for e in snap["dead_entities"]:
                print(
                    f"    [{e['kfm_state']:11s}] {e['kind']:8s} {e['name']}"
                )
            print(
                f"  reanchor events (last {snap['reanchor_window_cycles']} "
                f"cycles): {snap['reanchor_events_in_window']}"
            )
            print(
                f"  deprecated-but-not-archived: {snap['deprecated_unarchived']}"
            )
            return 0

        entities = list_entities(conn, kind=args.kind)
        if not entities:
            print("chimera ontology: (no entities)")
            return 0
        print(f"chimera ontology ({len(entities)} entities):")
        for e in entities:
            print(
                f"  [{e.kfm_state:11s}] {e.kind:8s} {e.name}  "
                f"(id={e.id[:8]}… cycle={e.state_entered_at_cycle})"
            )
            transitions = list_transitions(conn, e.id)
            for t in transitions:
                print(
                    f"      ↳ cycle {t.cycle}: {t.from_state} → {t.to_state} "
                    f"by '{t.operator_type}'"
                )
        return 0
    if args.command == "scenario":
        from .core import LoopConfig
        from .scenarios import run_drift_scenario, run_research_scenario

        cfg = LoopConfig.from_env()
        if args.name == "drift":
            result = run_drift_scenario(cfg.mind_dir, cfg.state_dir)
            print(f"chimera scenario drift:")
            print(f"  plan_demoted: {result.plan_demoted}")
            print(f"  final_plan_state: {result.final_plan_state}")
            print(f"  plan_count: {result.plan_count}")
            print(f"  transcript: {result.transcript_path}")
            return 0 if result.plan_demoted else 1
        if args.name == "research":
            result = run_research_scenario(cfg.mind_dir, cfg.state_dir)
            print(f"chimera scenario research:")
            if result.skipped:
                print("  SKIPPED (no provider keys set)")
                print(f"  transcript: {result.transcript_path}")
                return 2
            print(f"  tasks_seen: {result.tasks_seen}")
            print(f"  tasks_completed: {result.tasks_completed}")
            print(f"  api_calls: {result.api_calls}")
            print(f"  tool_calls: {result.tool_call_count}")
            print(f"  transcript: {result.transcript_path}")
            return 0 if result.tasks_completed == result.tasks_seen else 1
        if args.name == "multi_host":
            from .scenarios import run_multi_host_demo
            workdir = cfg.state_dir.parent / "multi_host_demo"
            result = run_multi_host_demo(workdir)
            print("chimera scenario multi_host:")
            print(f"  peer_a_port: {result.peer_a_port}")
            print(f"  peer_a_agent_id: {result.peer_a_agent_id}")
            print(f"  peers_synced: {result.peers_synced}")
            print(f"  emergence_records: {result.emergence_records}")
            if result.failures:
                print("  failures:")
                for f in result.failures:
                    print(f"    - {f}")
            print(f"  ok: {result.ok}")
            return 0 if result.ok else 1
        if args.name == "two_chimera":
            from .scenarios import run_two_chimera_demo as _tcd
            peer_root = cfg.state_dir.parent / "peer_chimera"
            result = _tcd(peer_root)
            print("chimera scenario two_chimera:")
            print(f"  discovered_tools: {result.discovered_tools}")
            print(f"  ok: {result.ok}")
            print("  call_result:")
            for line in result.call_result.splitlines():
                print(f"    {line}")
            return 0 if result.ok else 1
        if args.name == "federation_http_drill":
            from .scenarios import run_federation_http_drill as _fhd
            peer_root = cfg.state_dir.parent / "peer_chimera"
            result = _fhd(peer_root)
            print("chimera scenario federation_http_drill:")
            print(f"  server_url:        {result.server_url}")
            print(f"  health_ok:         {result.health_ok}")
            print(f"  auth_rejected:     {result.auth_rejected_anonymous}")
            print(f"  identity.role:     {(result.identity or {}).get('role')}")
            print(f"  kfm.cycle:         {(result.kfm or {}).get('cycle')}")
            print(f"  witness_lines:     {result.witness_lines}")
            if result.failures:
                print("  failures:")
                for f in result.failures:
                    print(f"    - {f}")
            print(f"  ok: {result.ok}")
            return 0 if result.ok else 1
        if args.name == "cost_runaway_drill":
            # v4.66 (ADR 0085): hermetic regression of the v4.53–v4.60
            # cost-discipline arc.
            from .scenarios import (
                format_cost_runaway_result, run_cost_runaway_drill,
            )
            result = run_cost_runaway_drill(cfg.state_dir)
            print(format_cost_runaway_result(result))
            return 0 if result.ok else 1
        if args.name == "federation_trust_drill":
            from .scenarios import run_federation_trust_drill as _ftd
            peer_root = cfg.state_dir.parent / "peer_chimera"
            result = _ftd(peer_root)
            print("chimera scenario federation_trust_drill:")
            print(f"  locked.decision:   {result.locked_decision}")
            print(f"  locked.reason:     {result.locked_reason}")
            print(f"  degraded.decision: {result.degraded_decision}")
            print(f"  degraded.reason:   {result.degraded_reason}")
            print(f"  healthy.decision:  {result.healthy_decision}")
            print(f"  healthy.reason:    {result.healthy_reason}")
            print(f"  journal_records:   {result.journal_records}")
            if result.failures:
                print("  failures:")
                for f in result.failures:
                    print(f"    - {f}")
            print(f"  ok: {result.ok}")
            return 0 if result.ok else 1
        if args.name == "federation_drill":
            from .scenarios import run_federation_drill as _fd
            peer_root = cfg.state_dir.parent / "peer_chimera"
            result = _fd(peer_root)
            print("chimera scenario federation_drill:")
            print(f"  discovered_tools: {result.discovered_tools}")
            print(f"  identity.role: {(result.identity or {}).get('role')}")
            print(f"  identity.agent_id: {(result.identity or {}).get('agent_id')}")
            print(f"  kfm.cycle: {(result.kfm or {}).get('cycle')}")
            print(f"  kfm.trust_tier: {(result.kfm or {}).get('trust_tier')}")
            print(f"  witness_lines: {result.witness_lines}")
            print(f"  observations_written: {result.observations_written}")
            print(f"  journal_entries_after: {result.journal_entries_after}")
            if result.failures:
                print("  failures:")
                for f in result.failures:
                    print(f"    - {f}")
            print(f"  ok: {result.ok}")
            return 0 if result.ok else 1
    if args.command == "graph":
        from .core import LoopConfig
        from .core.loop import graph_projection_enabled
        from .memory import GraphStore, default_graph_dir, open_and_init

        cfg = LoopConfig.from_env()
        sub_cmd = args.graph_command or "init"
        store = GraphStore(default_graph_dir())
        # v4.62 (ADR 0081): emit a hint when the explicit CLI is used but
        # the housekeeping auto-refresh isn't enabled — so the operator
        # knows their hand-rebuilt graph will go stale next cycle.
        if sub_cmd in ("init", "rebuild") and not graph_projection_enabled():
            print(
                "ℹ️  graph projection is currently OPT-IN (default off as of v4.62). "
                "Set CHIMERA_GRAPH_ENABLED=1 for auto-refresh in housekeeping; "
                "otherwise re-run `chimera graph rebuild` manually."
            )
        if sub_cmd == "init":
            store.init_schema()
            print(f"chimera graph: schema ready at {store.path}")
            return 0
        if sub_cmd == "rebuild":
            conn = open_and_init(cfg.state_dir / "chimera.db")
            if getattr(args, "incremental", False):
                counts = store.update_from_sqlite(conn)
                mode = "incremental"
            else:
                counts = store.rebuild_from_sqlite(conn)
                mode = "full"
            print(f"chimera graph rebuild ({mode}, {store.path}):")
            for k, v in sorted(counts.items()):
                print(f"  {k}: {v}")
            return 0
        if sub_cmd == "query":
            store.init_schema()
            result = store.query(args.cypher)
            print("  " + " | ".join(result.columns))
            for row in result.rows:
                print("  " + " | ".join(str(c) for c in row))
            print(f"({len(result.rows)} row(s))")
            return 0
        if sub_cmd == "entity-history":
            store.init_schema()
            ident = args.ident
            res = store.query(
                "MATCH (e:Entity) WHERE e.id = $i OR e.id STARTS WITH $i "
                "OR e.name = $i RETURN e.id, e.kind, e.name LIMIT 1",
                params={"i": ident},
            )
            if not res.rows:
                print(f"chimera graph: no entity matches {ident!r}")
                return 1
            eid, kind, name = res.rows[0]
            print(f"chimera graph entity-history: [{kind}] {name} ({eid[:8]}…)")
            hist = store.query(
                "MATCH (e:Entity {id: $i})-[t:TRANSITIONED_TO]->(e) "
                "RETURN t.cycle, t.from_state, t.to_state, t.operator_type, t.reason "
                "ORDER BY t.cycle",
                params={"i": eid},
            )
            if not hist.rows:
                print("  (no transitions)")
                return 0
            for cyc, fs, ts, op, reason in hist.rows:
                print(f"  cycle {cyc}: {fs} → {ts} by {op!r}  {reason}")
            return 0
        if sub_cmd == "skill-deps":
            store.init_schema()
            skills = store.query("MATCH (s:Skill) RETURN s.name ORDER BY s.name").rows
            if not skills:
                print("chimera graph skill-deps: (no dynamic skills)")
                return 0
            print(f"chimera graph skill-deps: {len(skills)} skill(s)")
            for (sn,) in skills:
                deps = store.query(
                    "MATCH (:Skill {name: $n})-[:DEPENDS_ON]->(d:Skill) RETURN d.name",
                    params={"n": sn},
                ).rows
                tools = store.query(
                    "MATCH (:Skill {name: $n})-[:USES_TOOL]->(t:Entity) RETURN t.name",
                    params={"n": sn},
                ).rows
                print(f"  {sn}")
                if deps:
                    print(f"    depends_on: {', '.join(d[0] for d in deps)}")
                if tools:
                    print(f"    uses_tool:  {', '.join(t[0] for t in tools)}")
                if not deps and not tools:
                    print("    (no edges)")
            return 0
        if sub_cmd == "orphans":
            store.init_schema()
            orphan_ents = store.query(
                "MATCH (e:Entity) WHERE NOT EXISTS { "
                "MATCH (e)-[:TRANSITIONED_TO]->(e) } "
                "RETURN e.kind, e.name ORDER BY e.kind, e.name"
            ).rows
            orphan_skills = store.query(
                "MATCH (s:Skill) WHERE NOT EXISTS { MATCH (s)-[:DEPENDS_ON]->() } "
                "AND NOT EXISTS { MATCH (s)-[:USES_TOOL]->() } "
                "RETURN s.name ORDER BY s.name"
            ).rows
            print(f"chimera graph orphans:")
            print(f"  entities with no transitions: {len(orphan_ents)}")
            for kind, name in orphan_ents:
                print(f"    [{kind}] {name}")
            print(f"  skills with no edges: {len(orphan_skills)}")
            for (n,) in orphan_skills:
                print(f"    {n}")
            return 0
        if sub_cmd == "export":
            import json as _json
            from datetime import datetime, timezone

            store.init_schema()
            snapshot: dict[str, Any] = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            cols = lambda r: [dict(zip(r.columns, row)) for row in r.rows]
            snapshot["entities"] = cols(store.query(
                "MATCH (e:Entity) RETURN e.id AS id, e.kind AS kind, "
                "e.name AS name, e.kfm_state AS kfm_state "
                "ORDER BY e.kind, e.name"
            ))
            skill_names = [r[0] for r in store.query(
                "MATCH (s:Skill) RETURN s.name ORDER BY s.name"
            ).rows]
            skills: list[dict[str, Any]] = []
            for sn in skill_names:
                deps = [r[0] for r in store.query(
                    "MATCH (:Skill {name: $n})-[:DEPENDS_ON]->(d:Skill) RETURN d.name",
                    params={"n": sn},
                ).rows]
                tools = [r[0] for r in store.query(
                    "MATCH (:Skill {name: $n})-[:USES_TOOL]->(t:Entity) RETURN t.name",
                    params={"n": sn},
                ).rows]
                skills.append({"name": sn, "deps": deps, "tools": tools})
            snapshot["skills"] = skills
            snapshot["proposed"] = cols(store.query(
                "MATCH (m:Mutation)-[:PROPOSED]->(e:Entity) "
                "RETURN m.id AS id, m.type AS type, m.status AS status, "
                "e.kind AS entity_kind, e.name AS entity_name "
                "ORDER BY m.id DESC LIMIT 50"
            ))
            snapshot["activated"] = cols(store.query(
                "MATCH (m:Mutation)-[:ACTIVATED]->(s:Skill) "
                "RETURN m.id AS id, s.name AS skill ORDER BY m.id DESC LIMIT 50"
            ))
            snapshot["trusted"] = cols(store.query(
                "MATCH (a:Peer)-[t:TRUSTED]->(b:Peer) "
                "RETURN a.agent_id AS from, b.agent_id AS to, "
                "t.verdict AS verdict, t.drift_score AS drift_score, "
                "t.recorded_at AS recorded_at"
            ))
            out_path = Path(args.out) if args.out else (
                cfg.state_dir / "chimera.graph.snapshot.json"
            )
            out_path.write_text(_json.dumps(snapshot, indent=2), encoding="utf-8")
            print(f"chimera graph export: {out_path}")
            return 0
        if sub_cmd == "stress":
            import json as _json
            import tempfile
            from .scenarios import run_graph_stress

            with tempfile.TemporaryDirectory(prefix="chimera-stress-") as td:
                td_path = Path(td)
                result = run_graph_stress(
                    sqlite_path=td_path / "chimera.db",
                    graph_path=td_path / "chimera.graph",
                    n_entities=args.entities,
                    transitions_each=args.transitions_each,
                    repeat_queries=args.repeat,
                )
            payload = result.to_dict()
            if args.json:
                print(_json.dumps(payload, indent=2, sort_keys=True))
                return 0 if result.ok else 1
            print(
                f"chimera graph stress: {result.n_entities} entities, "
                f"{result.n_transitions} transitions"
            )
            print(f"  populate: {result.populate_seconds:.3f}s")
            print(f"  rebuild:  {result.rebuild_seconds:.3f}s")
            for k, v in sorted(result.rebuild_counts.items()):
                print(f"    {k:18s} {v}")
            print("  queries (p50 / p95 ms):")
            for q in result.query_timings:
                print(
                    f"    {q.label:28s} rows={q.rows:4d}  "
                    f"p50={q.p50_ms:7.3f}  p95={q.p95_ms:7.3f}"
                )
            print(f"  restart_count_match: {result.restart_count_match}")
            if result.failures:
                print("  failures:")
                for f in result.failures:
                    print(f"    - {f}")
            print(f"  ok: {result.ok}")
            return 0 if result.ok else 1
        if sub_cmd == "provenance":
            store.init_schema()
            mid = args.mutation_id
            mut = store.query(
                "MATCH (m:Mutation {id: $i}) RETURN m.type, m.status, m.reason",
                params={"i": mid},
            )
            if not mut.rows:
                print(f"chimera graph provenance: mutation #{mid} not in graph")
                return 1
            mtype, mstatus, mreason = mut.rows[0]
            print(f"chimera graph provenance: mutation #{mid}  [{mtype}]  status={mstatus}")
            if mreason:
                print(f"  reason: {mreason}")
            proposed = store.query(
                "MATCH (:Mutation {id: $i})-[:PROPOSED]->(e:Entity) "
                "RETURN e.id, e.kind, e.name, e.kfm_state",
                params={"i": mid},
            ).rows
            for eid, kind, name, st in proposed:
                print(f"  PROPOSED → [{kind}] {name} ({eid[:8]}…) state={st}")
            activated = store.query(
                "MATCH (:Mutation {id: $i})-[:ACTIVATED]->(s:Skill) "
                "RETURN s.name, s.source_path",
                params={"i": mid},
            ).rows
            for sn, sp in activated:
                print(f"  ACTIVATED → skill {sn}  ({sp})")
            if not proposed and not activated:
                print("  (no provenance edges)")
            return 0
        parser.error(f"unknown graph subcommand: {sub_cmd}")
        return 2
    if args.command == "submit-pr":
        # v4.97 (ADR 0102): operator-side PR submission for soak worktrees.
        from .core.submit_pr import submit_pr

        worktree = Path(args.worktree).resolve()
        repo_root = Path(__file__).resolve().parents[1]
        pm_path = (
            Path(args.body_from_postmortem).resolve()
            if args.body_from_postmortem else None
        )

        result = submit_pr(
            worktree=worktree,
            repo_root=repo_root,
            base=args.base,
            title=args.title,
            body=args.body,
            body_from_postmortem=pm_path,
            draft=args.draft,
            dry_run=args.dry_run,
            allow_entropy=args.allow_entropy,
        )

        if args.json:
            import json as _json
            print(_json.dumps(result.to_dict(), indent=2))
        else:
            print(f"chimera submit-pr  branch={result.branch}")
            for sha, subject in result.commits:
                tag = "[agent]" if subject.startswith("[agent]") else "[op]"
                print(f"  {tag} {sha[:8]}  {subject}")
            if result.validation_errors:
                print()
                print("  ❌ validation errors:")
                for e in result.validation_errors:
                    print(f"    - {e}")
            if result.dry_run and result.ok:
                print()
                print("  ✓ dry-run: all validations pass — would push + open PR")
            elif result.ok:
                print()
                print(f"  ✓ PR opened: {result.pr_url}")
        return 0 if result.ok else 1

    if args.command == "mind":
        if args.mind_command == "count":
            # Leaf import: chimera.mindcount pulls only stdlib (pathlib),
            # and `format_mind_counts` is bound nowhere else in main(), so
            # this local import shadows no module global (the v40 os/Path
            # regression class this charter set out to avoid).
            from .core import LoopConfig
            from .mindcount import format_mind_counts
            mind_dir = LoopConfig.from_env().mind_dir
            print(format_mind_counts(mind_dir), end="")
            return 0
        parser.error("usage: chimera mind count")
        return 2

    if args.command == "soak":
        if args.soak_command == "summary":
            # Leaf import (the v44 first-real-feature module), same
            # shadow-free pattern as `mind count`. spend is read best-effort
            # from the run DB (meaningful in a soak worktree; omitted if
            # unavailable) and passed in — the ledger carries no cost.
            from .core import LoopConfig
            from .soak_summary import format_soak_summary, run_spend_from_db
            cfg = LoopConfig.from_env()
            spend = run_spend_from_db(cfg.state_dir)
            print(
                format_soak_summary(cfg.mind_dir, args.run_id, spend_usd=spend),
                end="",
            )
            return 0
        if args.soak_command == "breakdown":
            # v45 second-real-feature module; same shadow-free leaf pattern.
            from .core import LoopConfig
            from .soak_breakdown import format_soak_breakdown
            cfg = LoopConfig.from_env()
            print(format_soak_breakdown(cfg.mind_dir, args.run_id), end="")
            return 0
        if args.soak_command == "report":
            # v46 third-real-feature module; same shadow-free leaf pattern.
            from .core import LoopConfig
            from .soak_report import format_soak_report
            cfg = LoopConfig.from_env()
            print(format_soak_report(cfg.mind_dir, args.run_id), end="")
            return 0
        parser.error("usage: chimera soak {summary|breakdown|report} <run-id>")
        return 2

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
