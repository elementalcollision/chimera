"""In-loop critic enforcement (ADR 0162) — the commit-time gate.

ADR 0160 built the internal critic and wired it as an *advisory* step. ADR 0162
promotes it to a *gate*: a commit must not land unless the critic adjudicates the
staged change faithful. This module is that gate, factored so the same logic
guards both commit paths (the agent's `git_commit` tool via the shell handler,
and the ADR 0148 autocommit fallback).

Design (see ADR 0162):

- **Verdict bound to the staged diff.** `chimera review` writes a verdict artifact
  keyed by the SHA-256 of `git diff --cached`. The gate accepts it ONLY if a
  matching-hash artifact exists and is APPROVED — the agent can *run* the
  reviewer but cannot forge its output, and a hash mismatch (diff changed since
  review) invalidates a stale verdict.
- **Authoritative fallback.** With no valid artifact, the gate reviews the staged
  diff itself (diff + docstrings; no faithfulness report — which the calibration
  showed the critic does not need: it caught every differential-blind near-miss
  on diff+docstring alone). The commit is never allowed on an unreviewed diff.
- **Reject-requires-confirmation.** A REJECT is not a hard stop: an independent
  second reviewer (a different, reliable model — see ``_default_escalator``) is
  consulted, and the commit is blocked unless that escalator returns a PARSEABLE
  approval. An empty/unreadable escalation cannot rescue (fail-closed holds).
  This absorbs the measured ~20% false-reject (incl. a clean fix the
  differential couldn't corroborate) without moving the 0% false-approve side.
- **Fail-closed.** An unparseable/errored verdict is NOT approval → it routes to
  the reject/escalate path, ending in a block-with-handoff, never a silent pass.
- **Off by default.** Enforcement runs only under `CHIMERA_CRITIC_ENFORCE=1`.
  `CHIMERA_ALLOW_CRITIC_REJECT=1` is the operator escape valve for a confirmed
  false-reject (single-use, operator-aware — mirrors the scope-check override).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from .critic import CriticVerdict

# A reviewer adjudicates a staged diff → a verdict. Injectable for tests; the
# default builds a real cross-model reviewer from the configured providers.
Reviewer = Callable[[str], Awaitable[CriticVerdict]]

_ARTIFACT_PREFIX = "critic-verdict-"
_CALIB_RECORD = "critic-calibration-latest.json"
_GATE_LOG = "critic-gate-log.jsonl"
_ENFORCE_ENV = "CHIMERA_CRITIC_ENFORCE"
_OVERRIDE_ENV = "CHIMERA_ALLOW_CRITIC_REJECT"


@dataclass
class GateDecision:
    """The outcome of the commit-time critic gate."""

    allowed: bool
    source: str = ""               # disabled | empty-diff | override | artifact | recomputed
    reason: str = ""               # human-readable, surfaced to the agent on block
    verdict: CriticVerdict | None = None
    escalation: CriticVerdict | None = None
    diff_sha: str = ""
    escalated: bool = field(default=False)
    escalator_model: str = ""      # the model id consulted on the rescue path (auditability)


# ── enforcement switches ─────────────────────────────────────────────


def enforce_enabled() -> bool:
    return os.environ.get(_ENFORCE_ENV) == "1"


def override_active() -> bool:
    return bool(os.environ.get(_OVERRIDE_ENV))


# ── staged diff + hashing ────────────────────────────────────────────


def staged_diff(repo_root: Path) -> str:
    """The staged index as a unified diff — exactly what will be committed, and
    exactly the snapshot the ADR 0146 scope check already inspects."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached"], cwd=str(repo_root),
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def diff_sha(diff: str) -> str:
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


def staged_files(repo_root: Path) -> list[str]:
    """Paths in the staged index (for docstring extraction in the fallback)."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only"], cwd=str(repo_root),
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


# ── verdict artifact (hash-bound) ────────────────────────────────────


def _artifact_dir(repo_root: Path) -> Path:
    return repo_root / "state"


def artifact_path(repo_root: Path, sha: str) -> Path:
    return _artifact_dir(repo_root) / f"{_ARTIFACT_PREFIX}{sha}.json"


def write_verdict_artifact(
    repo_root: Path,
    diff: str,
    verdict: CriticVerdict,
    *,
    goal: str | None = None,
    model_id: str | None = None,
) -> Path:
    """Persist a verdict keyed by the staged-diff hash. Written by `chimera
    review` so the gate can accept it without recomputing — the binding to the
    diff hash is what makes it unforgeable and self-invalidating."""
    import json

    sha = diff_sha(diff)
    payload = {
        "diff_sha256": sha,
        "approved": bool(verdict.approved),
        "concerns": list(verdict.concerns),
        "rationale": verdict.rationale,
        "parsed": verdict.parsed,
        "goal": goal or "",
        "model_id": model_id or "",
    }
    d = _artifact_dir(repo_root)
    d.mkdir(parents=True, exist_ok=True)
    p = artifact_path(repo_root, sha)
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def load_verdict_artifact(repo_root: Path, diff: str) -> CriticVerdict | None:
    """Load the verdict whose recorded hash matches the CURRENT staged diff.
    Returns None on absence, hash mismatch, or corruption — any of which means
    "no trustworthy verdict; recompute"."""
    import json

    sha = diff_sha(diff)
    p = artifact_path(repo_root, sha)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        return None
    if not isinstance(data, dict) or data.get("diff_sha256") != sha:
        return None
    if "approved" not in data:
        return None
    return CriticVerdict(
        approved=data.get("approved") is True,
        concerns=[str(c) for c in (data.get("concerns") or [])],
        rationale=str(data.get("rationale", "")),
        parsed=bool(data.get("parsed", True)),
    )


# ── calibration-gated activation (ADR 0162) ─────────────────────────
#
# Enforcement's legitimacy is tied to the measured false-approve rate: the gate
# may only block (i.e. be trusted to auto-refuse) while the latest calibration
# shows 0 false-approve. `chimera critic-calibrate` records its result; the gate
# refuses to enforce against a missing or dirty record. This makes the
# "calibration-gated" invariant mechanical, not just documented.


def write_calibration_record(
    repo_root: Path,
    *,
    total: int,
    false_approve: int,
    false_reject: int,
    accuracy: float,
    model: str = "",
) -> Path:
    import json

    d = _artifact_dir(repo_root)
    d.mkdir(parents=True, exist_ok=True)
    p = d / _CALIB_RECORD
    p.write_text(json.dumps({
        "total": int(total),
        "false_approve": int(false_approve),
        "false_reject": int(false_reject),
        "accuracy": float(accuracy),
        "model": model,
    }, indent=2), encoding="utf-8")
    return p


def read_calibration_record(repo_root: Path) -> dict | None:
    import json

    p = _artifact_dir(repo_root) / _CALIB_RECORD
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def calibration_clean(repo_root: Path) -> tuple[bool, str]:
    """(ok, reason). Enforcement is permitted ONLY when the latest calibration
    record exists and shows false_approve == 0."""
    rec = read_calibration_record(repo_root)
    if rec is None:
        return False, ("no calibration record — run `chimera critic-calibrate` "
                       "(false-approve must be 0) before enforcing")
    fa = rec.get("false_approve")
    if not isinstance(fa, int):
        return False, "calibration record malformed (no integer false_approve)"
    if fa > 0:
        return False, (f"latest calibration has false_approve={fa} (>0) — "
                       "enforcement is unsafe until that is 0")
    model = rec.get("model") or "?"
    return True, (f"calibration clean (false_approve=0, {rec.get('total')} cases, "
                  f"model={model})")


# ── decision ledger (ADR 0162) ───────────────────────────────────────


def _call_cost_usd(model_id: str, in_tok: int, out_tok: int) -> float:
    """Price one critic/escalator call from its REAL token usage. The gate is the
    per-commit cost the ACT spend line misses (a sonnet primary + ~100% an opus
    escalator on clean diffs — value-assessment 2026-06-03). Unknown model → 0."""
    try:
        from .cost_estimate import _price_table
        in_price, out_price = _price_table().get(model_id, (0.0, 0.0))
    except Exception:
        return 0.0
    return (in_tok / 1_000_000.0) * in_price + (out_tok / 1_000_000.0) * out_price


def _gate_cost(decision: GateDecision) -> dict:
    """Real $ cost of THIS gate decision: primary critic + (if any) escalator."""
    v, e = decision.verdict, decision.escalation
    p_usd = _call_cost_usd(v.model_id, v.input_tokens, v.output_tokens) if v else 0.0
    e_usd = _call_cost_usd(e.model_id, e.input_tokens, e.output_tokens) if e else 0.0
    return {
        "primary": (None if v is None else {
            "model": v.model_id, "in": v.input_tokens, "out": v.output_tokens,
            "usd": round(p_usd, 6)}),
        "escalator": (None if e is None else {
            "model": e.model_id, "in": e.input_tokens, "out": e.output_tokens,
            "usd": round(e_usd, 6)}),
        "total_usd": round(p_usd + e_usd, 6),
    }


def record_gate_decision(repo_root: Path, decision: GateDecision) -> None:
    """Append a one-line record of each gate decision. The live loop thereby
    accumulates the verdict-vs-outcome history ADR 0160 asked for — every
    auto-refused or auto-allowed commit is auditable after the fact. Best-effort:
    a logging failure must never change the commit outcome."""
    import json
    import os

    try:
        d = _artifact_dir(repo_root)
        d.mkdir(parents=True, exist_ok=True)
        row = {
            # Join key (ADR 0186 B.4l): tie this gate decision to its CRAWL run so
            # critic verdicts can later be calibrated against run outcomes (this log
            # is keyed by diff_sha; the crawl ledger by run_id).
            "run_id": os.environ.get("CHIMERA_SOAK_RUN_ID", ""),
            "allowed": decision.allowed,
            "source": decision.source,
            "diff_sha": decision.diff_sha,
            "escalated": decision.escalated,
            "approved": None if decision.verdict is None else decision.verdict.approved,
            "escalation_approved": (
                None if decision.escalation is None else decision.escalation.approved
            ),
            "escalation_parsed": (
                None if decision.escalation is None else decision.escalation.parsed
            ),
            "escalator_model": decision.escalator_model or None,
            "cost": _gate_cost(decision),
        }
        with (d / _GATE_LOG).open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError as exc:
        # No longer swallowed: a silent write failure here would look exactly
        # like "the gate never ran" (finding #2). Surface it to stderr (→ the
        # soak runner log) so the two cases are distinguishable.
        import sys
        print(f"critic-gate: record_gate_decision write FAILED: {exc}", file=sys.stderr)


def gate_trace(repo_root: Path, **fields) -> None:
    """Unconditional invocation trace → state/critic-gate-debug.jsonl. Answers the
    finding-#2 question 'did the gate even run?': if a commit lands with no debug
    'enter' row, the commit bypassed the gated path; if 'enter' is present but the
    decision log is empty, the decision-write failed. Best-effort + stderr on fail."""
    import json
    import sys
    from datetime import datetime
    try:
        d = _artifact_dir(repo_root)
        d.mkdir(parents=True, exist_ok=True)
        fields["ts"] = datetime.now().isoformat(timespec="seconds")
        with (d / "critic-gate-debug.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(fields) + "\n")
    except OSError as exc:
        print(f"critic-gate: gate_trace write failed: {exc}", file=sys.stderr)


# ── the gate ─────────────────────────────────────────────────────────


def _block_reason(verdict: CriticVerdict, escalation: CriticVerdict | None) -> str:
    parts = [
        "git commit blocked by the in-loop critic gate (ADR 0162): the change "
        "was adjudicated NOT faithful.",
        f"  critic: {verdict.summary()}",
    ]
    if escalation is not None and escalation.parsed:
        parts.append(f"  second opinion (independent): {escalation.summary()}")
        parts.append("  Both reviewers rejected — this is very likely a real "
                     "regression. Address the concern (restore the behaviour or "
                     "pin it with a test), then re-commit.")
    elif escalation is not None:
        # Escalation ran but returned empty/unparseable text: per the fail-closed
        # charter it cannot rescue a reject (only a PARSEABLE approve overrules).
        parts.append(f"  second opinion (independent): {escalation.summary()}")
        parts.append("  The independent escalation could not be read (empty or "
                     "unparseable), so it cannot overrule the reject — the "
                     "fail-closed default holds: needs human review.")
    else:
        parts.append("  No independent second opinion was available, so the "
                     "fail-closed default holds: needs human review.")
    parts.append("")
    parts.append("Override (operator-aware, single-use, for a CONFIRMED "
                 f"false-reject): export {_OVERRIDE_ENV}=1")
    return "\n".join(parts)


async def check_commit_critic(
    repo_root: Path,
    *,
    goal: str | None = None,
    reviewer: Reviewer | None = None,
    escalator: Reviewer | None = None,
) -> GateDecision:
    """Adjudicate the staged commit. Returns a :class:`GateDecision`; callers
    block the commit when ``allowed`` is False and surface ``reason``.

    ``reviewer``/``escalator`` are injectable (tests pass mocks); when omitted and
    enforcement is on, defaults are built from the configured providers.
    """
    gate_trace(repo_root, event="enter", enforce=enforce_enabled(),
               override=override_active())
    if not enforce_enabled():
        return GateDecision(allowed=True, source="disabled")

    diff = staged_diff(repo_root)
    if not diff.strip():
        return GateDecision(allowed=True, source="empty-diff")
    sha = diff_sha(diff)

    if override_active():
        d = GateDecision(
            allowed=True, source="override", diff_sha=sha,
            reason=f"{_OVERRIDE_ENV}=1 — operator overrode the critic gate.",
        )
        record_gate_decision(repo_root, d)
        return d

    # 0. Calibration-gated activation: enforcement is only legitimate while the
    #    measured false-approve rate is 0. Refuse (block) against a missing or
    #    dirty calibration record — the operator override above is the escape.
    clean, why = calibration_clean(repo_root)
    if not clean:
        d = GateDecision(
            allowed=False, source="calibration-unverified", diff_sha=sha,
            reason=("git commit blocked: in-loop critic enforcement requires a "
                    f"clean calibration record first (ADR 0162): {why}.\n"
                    "Run `chimera critic-calibrate` (false-approve must be 0), "
                    f"or override: export {_OVERRIDE_ENV}=1"),
        )
        record_gate_decision(repo_root, d)
        return d

    # 1. Trust a hash-matched APPROVED artifact; else recompute authoritatively.
    verdict = load_verdict_artifact(repo_root, diff)
    source = "artifact"
    if verdict is None or not verdict.parsed:
        if reviewer is None:
            reviewer = _default_reviewer(repo_root, goal)
        verdict = await reviewer(diff)
        source = "recomputed"

    if verdict.approved:
        d = GateDecision(allowed=True, source=source, verdict=verdict, diff_sha=sha)
        record_gate_decision(repo_root, d)
        return d

    # 2. Reject → require confirmation by an INDEPENDENT second reviewer.
    if escalator is None:
        escalator = _default_escalator(repo_root, goal)
    escalator_model = getattr(escalator, "model_id", "") if escalator is not None else ""
    escalation = await escalator(diff) if escalator is not None else None
    if escalation is not None and escalation.approved and escalation.parsed:
        # A lone over-cautious reject, overruled — the false-reject rescue path.
        # The PARSEABLE guard is load-bearing: an empty/unreadable escalation
        # (ADR 0162 item-7 surfaced an OpenRouter rung returning empty text)
        # must NOT rescue, or fail-closed would silently become fail-open.
        d = GateDecision(
            allowed=True, source=source, verdict=verdict, escalation=escalation,
            diff_sha=sha, escalated=True, escalator_model=escalator_model,
            reason="critic rejected but an independent second opinion approved "
                   "(false-reject overruled).",
        )
        record_gate_decision(repo_root, d)
        return d

    d = GateDecision(
        allowed=False, source=source, verdict=verdict, escalation=escalation,
        diff_sha=sha, escalated=escalation is not None, escalator_model=escalator_model,
        reason=_block_reason(verdict, escalation),
    )
    record_gate_decision(repo_root, d)
    return d


# ── default reviewers (real providers; not exercised by unit tests) ──


def _docstrings_for_staged(repo_root: Path) -> str:
    from chimera.cli import _function_docstrings  # lazy: avoid import cycle

    out: list[str] = []
    for rel in staged_files(repo_root):
        if not rel.endswith(".py"):
            continue
        try:
            src = (repo_root / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        ds = _function_docstrings(src)
        if ds:
            out.append(ds)
    return "\n\n".join(out)


# The model the calibration ledger (ADR 0160) actually measures — `chimera
# critic-calibrate --model` defaults to it. The gate's PRIMARY reviewer MUST use
# this same model, or the calibration-gated-activation invariant is meaningless
# (we would be gating on a false-approve rate measured for a different model).
# The live validation (ADR 0162 item 7) caught exactly this: select_rung("sonnet")
# resolved to an OpenRouter model that returns empty text, so the gate was both
# off-model and fail-closing clean fixes.
CALIBRATED_MODEL = "claude-sonnet-4-6"


def _build_reviewer(
    repo_root: Path,
    goal: str | None,
    *,
    anthropic_model: str | None = None,
    tier: str | None = None,
    rung_alias: str | None = None,
) -> Reviewer | None:
    """Build a reviewer from the configured providers, or None if unavailable.

    ``anthropic_model`` pins the Anthropic provider + that exact model (used for
    the primary, so it matches the calibrated model). ``rung_alias`` resolves a
    SPECIFIC rung by name/alias (e.g. a cross-vendor ``"gemini-3.1-pro-preview"``), used by
    the escalator to pin a genuinely-different model rather than a tier's cheapest
    (the tier-cheapest rung is what returned empty text in ADR 0162 item-7).
    ``tier`` resolves a tier ladder's cheapest rung (legacy escalator path).

    The returned callable carries the chosen model id on a ``.model_id`` attribute
    so the gate can record which model was consulted (auditability).
    """
    from .critic import review_change

    try:
        from chimera.core import ChimeraLoop
        from chimera.providers.tiers import Provider as ProviderKind
        from chimera.providers.tiers import resolve_rung, select_rung

        loop = ChimeraLoop()
        providers = loop._act.providers if loop._act is not None else {}
        if not providers:
            return None
        if anthropic_model is not None:
            provider = providers.get(ProviderKind.ANTHROPIC)
            if provider is None:
                return None
            model_id = anthropic_model
        else:
            rung = resolve_rung(rung_alias) if rung_alias is not None else select_rung(tier or "sonnet")
            provider = providers.get(rung.config.provider)
            if provider is None:
                return None
            model_id = (
                rung.config.model_id if rung.config.provider is ProviderKind.ANTHROPIC
                else rung.config.openrouter_model_id
            )
    except Exception:
        return None

    docstring = _docstrings_for_staged(repo_root)

    async def _review(diff: str) -> CriticVerdict:
        return await review_change(
            diff, provider=provider, model_id=model_id, goal=goal,
            docstring=docstring, faithfulness=None,
        )

    _review.model_id = model_id  # surfaced into the gate-log record
    return _review


def _default_reviewer(repo_root: Path, goal: str | None) -> Reviewer:
    # Primary = the SAME model the calibration validated (Anthropic), so the
    # measured false-approve rate actually applies to what the gate runs.
    r = _build_reviewer(repo_root, goal, anthropic_model=CALIBRATED_MODEL)
    if r is None:  # no Anthropic provider → fall back to a ladder rung
        r = _build_reviewer(repo_root, goal, tier="sonnet")
    if r is not None:
        return r

    async def _unavailable(_diff: str) -> CriticVerdict:
        # Fail-closed: no provider ⇒ cannot adjudicate ⇒ not an approval.
        return CriticVerdict(
            False, ["critic gate: no provider available to review the commit"],
            parsed=False,
        )

    return _unavailable


# The escalator's job is to RESCUE a lone over-cautious reject, so it must be
# both (a) a genuinely different model than the primary (CALIBRATED_MODEL) for
# real independence, and (b) RELIABLE — actually return parseable text. ADR 0162
# item-7's live validation found the old `tier="opus"` resolved (via select_rung,
# cheapest-first) to OpenRouter `deepseek-v4-pro`, which returns EMPTY text in
# this env → every escalation fail-closed → the rescue path was inert.
#
# Default now: a different Anthropic model than the sonnet primary, on the
# proven-reliable provider — so the rescue genuinely fires. Operators wanting
# true cross-vendor independence can pin a rung alias (e.g. "gemini-3.1-pro-preview",
# "gpt-5.1-codex-max") via CHIMERA_CRITIC_ESCALATOR_MODEL once they've verified it
# returns parseable text in their config; the PARSEABLE guard in
# check_commit_critic keeps an empty/unreadable escalation fail-closed either way.
ESCALATOR_MODEL_ENV = "CHIMERA_CRITIC_ESCALATOR_MODEL"
ESCALATOR_DEFAULT_MODEL = "claude-opus-4-7"  # ≠ CALIBRATED_MODEL → independent


def _default_escalator(repo_root: Path, goal: str | None) -> Reviewer | None:
    pinned = os.environ.get(ESCALATOR_MODEL_ENV)
    if pinned:
        # A tier name or per-rung alias (may be cross-vendor). Ignore a pin that
        # collapses to the primary's model — that would not be independent.
        if pinned != CALIBRATED_MODEL:
            r = _build_reviewer(repo_root, goal, rung_alias=pinned)
            if r is not None:
                return r
    # Default: a reliable, genuinely-different model than the calibrated primary.
    # If the Anthropic provider is unavailable, fall back to the (cross-vendor)
    # opus ladder rung — last resort; the parseable guard still protects it.
    r = _build_reviewer(repo_root, goal, anthropic_model=ESCALATOR_DEFAULT_MODEL)
    if r is None:
        r = _build_reviewer(repo_root, goal, tier="opus")
    return r
