"""`chimera witness-calibrate` — witness-panel A/B for a candidate member (ADR 0187 #4).

Runs the real witness-panel pool members plus a CANDIDATE (default Sakana
`fugu-ultra`) over the labelled change set, then prints per-member accuracy, the
candidate's vote-agreement with each existing member (independence check), and the
panel's accuracy with vs without the candidate. Measurement only — changes nothing.
"""

from __future__ import annotations


def _cmd_witness_calibrate(args) -> int:
    from .._async_loop import run_on_persistent_loop
    from ..core.critic_calibration import default_cases
    from ..core.witness import witness_code_change
    from ..core.witness_calibration import (
        member_stats,
        panel_confusion,
        vote_agreement,
    )
    from ..core.witness_panel import _DEFAULT_PANEL, panel_size
    from ..providers import get_provider
    from ..providers.tiers import Provider as PK

    cases = default_cases()
    labels = [c.should_approve for c in cases]
    pk_name = {PK.ANTHROPIC: "anthropic", PK.OPENROUTER: "openrouter"}

    # Base = the real panel pool (capped to the active panel size) + the candidate.
    base = [(m.label, pk_name[m.provider_kind], m.model_id) for m in _DEFAULT_PANEL]
    base = base[:panel_size()]
    cand = (f"sakana:{args.candidate_model}", args.candidate_provider, args.candidate_model)
    members = base + [cand]

    provs: dict = {}
    active: list[tuple[str, str, str]] = []
    for label, pname, model in members:
        if pname not in provs:
            try:
                provs[pname] = get_provider(pname)
            except Exception as e:  # noqa: BLE001
                print(f"  skip {label}: {e}")
                if label == cand[0]:
                    print("witness-calibrate: candidate provider unavailable.")
                    return 2
                continue
        active.append((label, pname, model))

    async def _vote(pname: str, model: str, case):
        try:
            v = await witness_code_change(
                case.goal or "Review this change for faithfulness.",
                case.diff, ["module.py"], provs[pname],
                model_id=model, max_tokens=args.max_tokens,
            )
        except Exception:  # noqa: BLE001
            return None
        # witness_code_change fail-opens to APPROVE on a provider error (correct for
        # the live gate). For a CALIBRATION that's an ERROR, not a verdict — exclude
        # it so an outage / credit-exhaustion never fabricates an "approve".
        if "provider error" in (v.summary or ""):
            return None
        return v

    verdicts: dict[str, list] = {}
    for label, pname, model in active:
        verdicts[label] = [run_on_persistent_loop(_vote(pname, model, c)) for c in cases]

    print(f"witness-calibrate: {len(cases)} labelled cases (single-shot)\n")
    print("Per-member accuracy (false-APPROVE is the dangerous error; errors EXCLUDED):")
    for label, _p, _m in active:
        s = member_stats(label, verdicts[label], labels)
        tag = f"  [{s.errors} errors excluded]" if s.errors else ""
        print(f"  {label:34s} acc {s.accuracy:.0%}  false-approve {s.false_approve:2d}  "
              f"false-reject {s.false_reject:2d}  (answered {s.n}/{len(cases)}){tag}")

    if cand[0] not in verdicts:
        return 0

    print(f"\nVote-agreement of {cand[0]} with each member (independence: lower = more "
          "independent):")
    for label, _p, _m in active:
        if label == cand[0]:
            continue
        print(f"  vs {label:34s} {vote_agreement(verdicts[cand[0]], verdicts[label]):.0%}")

    base_labels = [label for label, _p, _m in active if label != cand[0]]
    pc_base = panel_confusion([verdicts[label] for label in base_labels], labels)
    pc_with = panel_confusion(
        [verdicts[label] for label in base_labels] + [verdicts[cand[0]]], labels,
    )
    def _skip(pc):
        return f"  [{pc['skipped']} skipped]" if pc.get("skipped") else ""

    print(f"\nPanel WITHOUT candidate: acc {pc_base['accuracy']:.0%}  "
          f"false-approve {pc_base['false_approve']}  false-reject {pc_base['false_reject']}"
          f"{_skip(pc_base)}")
    print(f"Panel WITH    candidate: acc {pc_with['accuracy']:.0%}  "
          f"false-approve {pc_with['false_approve']}  false-reject {pc_with['false_reject']}"
          f"{_skip(pc_with)}")
    return 0
