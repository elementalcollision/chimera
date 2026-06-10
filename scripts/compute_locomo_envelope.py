#!/usr/bin/env python3
"""Compute n-run noise envelope from LoCoMo graded JSONL files.

Reusable across F3 (noise envelope) and future LoCoMo follow-ups.
Reads any number of `.graded.jsonl` files keyed off `item_id`. Emits:

    - per-category and overall accuracy per run
    - per-category and overall mean ± σ across runs
    - per-category gate values (mean − 2σ)
    - pairwise item-level flip matrices

Usage
-----
::

    python3 scripts/compute_locomo_envelope.py \\
        F1=/tmp/locomo-f1/hypotheses.graded.jsonl \\
        rerun1=/tmp/chimera-f3-locomo-rerun1/hypotheses.graded.jsonl \\
        rerun2=/tmp/chimera-f3-locomo-rerun2/hypotheses.graded.jsonl

Each positional arg is `label=path`. Order is preserved for the
"vs F1" delta column.
"""
from __future__ import annotations
import json
import statistics
import sys
from collections import defaultdict


def load_run(path: str) -> dict[str, dict]:
    out = {}
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            out[d["item_id"]] = {
                "category": d.get("category"),
                "is_correct": bool(d.get("is_correct")),
                "sample_id": d.get("sample_id"),
            }
    return out


def per_category(run: dict[str, dict]) -> dict[str, tuple[int, int]]:
    """Return {category: (correct, total)}, with 'overall' key."""
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for item in run.values():
        cat = item["category"]
        agg[cat][1] += 1
        if item["is_correct"]:
            agg[cat][0] += 1
        agg["overall"][1] += 1
        if item["is_correct"]:
            agg["overall"][0] += 1
    return {k: tuple(v) for k, v in agg.items()}


def fmt_pp(x: float) -> str:
    return f"{x*100:.2f}%"


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    runs: dict[str, dict[str, dict]] = {}
    for a in args:
        label, _, path = a.partition("=")
        if not path:
            print(f"bad arg: {a!r} (expected label=path)", file=sys.stderr)
            return 2
        runs[label] = load_run(path)
        print(f"loaded {label}: {len(runs[label])} items from {path}", file=sys.stderr)
    labels = list(runs)
    if not labels:
        return 2
    baseline = labels[0]
    # Per-category breakdown per run
    per_run = {lbl: per_category(r) for lbl, r in runs.items()}
    # Categories: sorted, with 'overall' last
    cats = sorted({c for run in per_run.values() for c in run.keys()} - {"overall"}) + ["overall"]

    print()
    print("# Per-category accuracy (per run)")
    print()
    hdr = ["category"] + labels + [f"Δ vs {baseline}"] if len(labels) > 1 else ["category"] + labels
    print("| " + " | ".join(hdr) + " |")
    print("|" + "|".join(["---"] * len(hdr)) + "|")
    for cat in cats:
        row = [cat]
        accs = []
        for lbl in labels:
            c, t = per_run[lbl].get(cat, (0, 0))
            acc = c / t if t else 0.0
            accs.append(acc)
            row.append(f"{fmt_pp(acc)} ({c}/{t})")
        if len(labels) > 1:
            delta = (accs[-1] - accs[0]) * 100
            row.append(f"{delta:+.2f}pp")
        print("| " + " | ".join(row) + " |")

    # Mean ± stdev across runs
    if len(labels) >= 2:
        print()
        print(f"# Mean ± stdev across n={len(labels)} runs")
        print()
        print("| category | mean | σ (pp) | gate (mean − 2σ) | range |")
        print("|---|---:|---:|---:|---|")
        for cat in cats:
            accs = []
            for lbl in labels:
                c, t = per_run[lbl].get(cat, (0, 0))
                accs.append((c / t * 100) if t else 0.0)
            mean = statistics.mean(accs)
            sigma = statistics.stdev(accs) if len(accs) > 1 else 0.0
            gate = mean - 2 * sigma
            lo, hi = min(accs), max(accs)
            print(f"| {cat} | {mean:.2f}% | {sigma:.2f} | {gate:.2f}% | {lo:.2f}–{hi:.2f} |")

    # Pairwise flip matrices
    if len(labels) >= 2:
        print()
        print("# Pairwise item-level flip matrices")
        print()
        print("| pair | both right | both wrong | only A right | only B right | flip count | flip rate |")
        print("|---|---:|---:|---:|---:|---:|---:|")
        for i, a in enumerate(labels):
            for b in labels[i + 1:]:
                ra, rb = runs[a], runs[b]
                common = set(ra) & set(rb)
                both_r = both_w = only_a = only_b = 0
                for k in common:
                    ca, cb = ra[k]["is_correct"], rb[k]["is_correct"]
                    if ca and cb:
                        both_r += 1
                    elif (not ca) and (not cb):
                        both_w += 1
                    elif ca and not cb:
                        only_a += 1
                    else:
                        only_b += 1
                flips = only_a + only_b
                rate = flips / max(1, len(common)) * 100
                print(f"| {a} (A) vs {b} (B) | {both_r} | {both_w} | {only_a} | {only_b} | {flips} | {rate:.2f}% |")

    return 0


if __name__ == "__main__":
    sys.exit(main())
