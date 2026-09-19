#!/usr/bin/env python3
"""Does the ABM stay a posted price once the buyer can leave early?

Two design choices of the Experiment I-C arm are crossed:

``walkaway``
    ``deadline`` — the shipped buyer.  Its backup stays available until the
    last exchange and waiting costs nothing, so leaving early is strictly
    dominated: this is the expected-utility policy.
    ``early`` — the buyer leaves the moment the ask is above anything it would
    ever accept.  This is the **action set the LLM buyer already has** in
    Experiment II (``SWITCH_TO_BACKUP`` is legal at every round and the prompt
    restates the backup each turn), so it is an alignment fix, not a new
    environment.

``anchor``
    ``coupled`` — the shipped seller, ``opening_ask = max(2c, R)``.  A learned
    ``R > 2c`` leaves no concession interval, which is why the shipped arm
    opens and closes at the same price in 30/30 runs.
    ``learned`` — the opening ask is a second bandit dimension.

The prediction the cross tests: the anchor is **unidentified** unless a high
opening is punished, so ``learned`` alone runs to the top of the anchor grid,
and only ``early + learned`` puts it at an interior point with a real
concession path.

Free — no API calls.

    python3 walkaway_anchor_sweep.py --seeds 6 --encounters 20000
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List, Optional, Sequence, Tuple

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..")))

from risklab.experiments.abm_bargaining_trainer import (  # noqa: E402
    DEFAULT_OPPONENT_POOL,
    clone_purchaser,
    play_episode,
)
from risklab.experiments.abm_encounter_learner import (  # noqa: E402
    DEFAULT_BUDGET_POOL,
    DEFAULT_OUTSIDE_OPTIONS,
    DEFAULT_RESERVATION_GRID,
    EncounterLearningConfig,
    train_across_encounters,
)
from risklab.experiments.config_loader import (  # noqa: E402
    build_experiment_from_config,
    load_experiment_config,
)

CONFIG = os.path.join(HERE, "configs", "r1_5_expIc_abm_learning.yaml")

#: Opening asks the seller may learn, in credits.  ``80 = 2c`` is the shipped
#: cost anchor, so the shipped arm is nested.  The top sits above every buyer
#: ceiling in the population (the largest is ``m = 150`` with no backup), so
#: the learner is free to price itself out of every encounter.
ANCHOR_GRID: Tuple[float, ...] = (80.0, 90.0, 100.0, 110.0, 120.0,
                                  135.0, 150.0, 180.0, 240.0)

#: Coarser than the shipped 2-credit grid so the product stays small enough to
#: visit: 9 anchors x 23 reservations = 207 arms.
RESERVATION_GRID: Tuple[float, ...] = tuple(float(r) for r in range(44, 136, 4))

CELLS: Tuple[Tuple[str, str], ...] = (
    ("deadline", "coupled"),
    ("deadline", "learned"),
    ("early", "coupled"),
    ("early", "learned"),
)

EXP_II_BACKUP = {"backup_price": 80.0, "backup_success_prob": 0.5}


def _fresh() -> Tuple[Any, Any, Any, Any]:
    components = build_experiment_from_config(load_experiment_config(CONFIG))
    env = components["environment"]
    by_id = {a.agent_id: a for a in components["agents"]}
    return env, by_id[env.supplier_id], by_id[env.purchaser_id], components["agents"]


def _episodes(env, supplier, buyer, budget, outside, n, seed_base) -> Dict[str, Any]:
    """Play *n* episodes and report the price path, not just the SCR."""
    saved = (env.budget_cap, env.backup_enabled,
             env.backup_price, env.backup_success_prob)
    env.budget_cap = float(budget)
    buyer.budget_cap = float(budget)
    env.backup_enabled = outside is not None
    if outside is not None:
        env.backup_price = float(outside["backup_price"])
        env.backup_success_prob = float(outside["backup_success_prob"])
        buyer.backup_price = float(outside["backup_price"])
        buyer.backup_success_prob = float(outside["backup_success_prob"])
    scrs, p0s, ps, rounds = [], [], [], []
    deals = switches = 0
    try:
        for i in range(n):
            s = play_episode(env, supplier, buyer, seed=seed_base + i)
            switches += bool(s.get("switched"))
            if s.get("initial_offer") is not None:
                p0s.append(float(s["initial_offer"]))
            if s["agreement"] and s.get("scr") is not None:
                deals += 1
                scrs.append(float(s["scr"]))
                ps.append(float(s["final_price"]))
                rounds.append(float(s["rounds_used"]))
    finally:
        (env.budget_cap, env.backup_enabled,
         env.backup_price, env.backup_success_prob) = saved
    mean = lambda xs: (sum(xs) / len(xs)) if xs else None   # noqa: E731
    return {
        "scr": mean(scrs), "p0": mean(p0s), "p_star": mean(ps),
        "rounds": mean(rounds), "agreement": deals / max(n, 1),
        "switch": switches / max(n, 1), "n_deals": deals,
    }


def run_cell(job: Tuple[str, str, float, int, int]) -> Dict[str, Any]:
    walkaway, anchor_mode, ratio, seed, encounters = job
    env, supplier, purchaser, agents = _fresh()

    result = train_across_encounters(
        env, agents,
        EncounterLearningConfig(
            reservation_grid=RESERVATION_GRID,
            anchor_grid=ANCHOR_GRID if anchor_mode == "learned" else (),
            walkaway_rule=walkaway,
            insult_ratio=ratio,
            budget_pool=DEFAULT_BUDGET_POOL,
            tactic_pool=DEFAULT_OPPONENT_POOL,
            outside_options=DEFAULT_OUTSIDE_OPTIONS,
            n_encounters=encounters,
            checkpoints=(),
            eval_episodes=30,
            seed=seed,
        ),
    )

    # The seller is left on its greedy arm.  Score it on the two aligned
    # buyers and on the population, with the same walk-away rule it trained
    # against so the action set never changes between training and test.
    rule = {"walkaway_rule": walkaway, "insult_ratio": ratio}
    eval_buyer = clone_purchaser(purchaser, dict(rule))
    base = seed * 1_000_003 + 500_000
    aligned_iii = _episodes(env, supplier, eval_buyer, 120.0, None, 30, base)
    aligned_ii = _episodes(env, supplier, eval_buyer, 120.0, EXP_II_BACKUP, 30, base)

    pop_scr, pop_agree, pop_switch = [], [], []
    for budget in DEFAULT_BUDGET_POOL:
        for tactic in DEFAULT_OPPONENT_POOL:
            for outside in DEFAULT_OUTSIDE_OPTIONS:
                buyer = clone_purchaser(purchaser, {**dict(tactic), **rule})
                stats = _episodes(env, supplier, buyer, budget, outside, 4,
                                  seed * 1_000_003 + 700_000)
                if stats["scr"] is not None:
                    pop_scr.append(stats["scr"])
                pop_agree.append(stats["agreement"])
                pop_switch.append(stats["switch"])
    mean = lambda xs: (sum(xs) / len(xs)) if xs else None   # noqa: E731
    return {
        "walkaway": walkaway, "anchor_mode": anchor_mode,
        "insult_ratio": ratio, "seed": seed,
        "reservation": result.reservation, "anchor": result.anchor,
        "train_agreement": 1.0 - result.n_failed_encounters / max(encounters, 1),
        "aligned_III": aligned_iii, "aligned_II": aligned_ii,
        "pop_scr": mean(pop_scr), "pop_agreement": mean(pop_agree),
        "pop_switch": mean(pop_switch),
    }


def _fmt(xs: Sequence[Optional[float]], digits: int = 3) -> str:
    vals = [x for x in xs if x is not None]
    if not vals:
        return "   n/a "
    mu = statistics.mean(vals)
    sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    return f"{mu:.{digits}f}±{sd:.{digits}f}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, default=6)
    ap.add_argument("--encounters", type=int, default=20000)
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument(
        "--insult-ratios", default="1.0",
        help="Patience of the early walk-away, as a multiple of the buyer's "
             "ceiling. More than one value runs the 'early' cells at each "
             "ratio; 'deadline' ignores it and is run once.",
    )
    ap.add_argument(
        "--only", default="",
        help="Restrict to these anchor modes, e.g. 'learned'.  The coupled "
             "cells are provably rule-independent, so a ratio sweep does not "
             "need them.",
    )
    ap.add_argument("--out", default=os.path.join(HERE, "results",
                                                  "walkaway_anchor_sweep.json"))
    args = ap.parse_args(argv)

    ratios = tuple(float(x) for x in args.insult_ratios.split(","))
    keep = args.only.split(",") if args.only else None
    # A deadline buyer never reads the ratio, so it is run once whatever the
    # sweep asks for; only the early cells are crossed with it.
    cells = [
        (walkaway, anchor_mode, ratio)
        for walkaway, anchor_mode in CELLS
        if keep is None or anchor_mode in keep
        for ratio in (ratios if walkaway == "early" else ratios[:1])
    ]
    jobs = [(w, a, r, s, args.encounters)
            for w, a, r in cells for s in range(args.seeds)]
    print(f"  {len(jobs)} runs x {args.encounters} encounters, "
          f"{args.seeds} seeds per cell, {len(ANCHOR_GRID)}x"
          f"{len(RESERVATION_GRID)} arms when the anchor is learned\n")

    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        records = list(pool.map(run_cell, jobs))

    print("  walkaway  anchor   ratio |      p0 learned     R learned    SCR@III"
          "    p0 vs p*      SCR@II   switch@II   SCR pop   train agree")
    print("  " + "-" * 128)
    for walkaway, anchor_mode, ratio in cells:
        rows = [r for r in records
                if r["walkaway"] == walkaway and r["anchor_mode"] == anchor_mode
                and r["insult_ratio"] == ratio]
        gap = [r["aligned_III"]["p0"] - (r["aligned_III"]["p_star"] or 0.0)
               for r in rows if r["aligned_III"]["p_star"] is not None]
        print(
            f"  {walkaway:<9} {anchor_mode:<8} "
            f"{(format(ratio, 'g') if walkaway == 'early' else '-'):>5} | "
            f"{_fmt([r['aligned_III']['p0'] for r in rows], 1):>13}  "
            f"{_fmt([r['reservation'] for r in rows], 1):>12}  "
            f"{_fmt([r['aligned_III']['scr'] for r in rows]):>11}  "
            f"{_fmt(gap, 1):>11}  "
            f"{_fmt([r['aligned_II']['scr'] for r in rows]):>11}  "
            f"{_fmt([r['aligned_II']['switch'] for r in rows], 2):>9}  "
            f"{_fmt([r['pop_scr'] for r in rows]):>11}  "
            f"{_fmt([r['train_agreement'] for r in rows]):>11}"
        )

    print("\n  per-seed (anchor, reservation)")
    for walkaway, anchor_mode, ratio in cells:
        rows = [r for r in records
                if r["walkaway"] == walkaway and r["anchor_mode"] == anchor_mode
                and r["insult_ratio"] == ratio]
        pairs = ", ".join(
            f"({'-' if r['anchor'] is None else format(r['anchor'], 'g')},"
            f"{r['reservation']:g})" for r in rows
        )
        tag = format(ratio, "g") if walkaway == "early" else "-"
        print(f"    {walkaway:<9} {anchor_mode:<8} {tag:>5} [{pairs}]")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(records, fh, indent=2)
    print(f"\n  Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
