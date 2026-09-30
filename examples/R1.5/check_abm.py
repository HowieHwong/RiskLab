#!/usr/bin/env python3
"""
Sanity checks for the Risk 1.5 ABM baseline — run this before trusting Exp I.

A rule-based baseline is only a baseline if it is not quietly rigged.  Three
properties are checked here, none of which the headline SCR number would
reveal on its own:

1.  **Monotone concession.**  No seller ask may rise and no buyer counter may
    fall inside an episode.  The earlier version of this baseline violated
    this in 27 of 30 runs — the seller's ask climbed from 80 to 109 — because
    a belief that updated faster than the concession curve pushed the ask up.
    That is not bargaining, and any surplus it "captures" is an artefact.

2.  **The symmetric benchmark.**  Give both sides the same information (the
    seller's prior equals the true budget, its reservation equals its cost),
    the same tactic family and the same exponent, and alternating-offer
    bargaining has a known answer: they meet in the middle, SCR = 0.5.  A
    model that misses this has a hidden asymmetry — a first-mover advantage
    baked into the acceptance rule, a mis-signed tactic — and would report
    that asymmetry as if it were a finding.

3.  **The information-asymmetry ladder.**  Turn the seller's ignorance of the
    budget on and off with everything else fixed.  This is what isolates the
    contribution of information asymmetry, which the headline Exp I number
    (asymmetry always on) cannot do by itself.

Usage
-----
    python check_abm.py                # 200 episodes per row, ~2 s
    python check_abm.py --sweep        # + beta and buyer-tactic robustness
    python check_abm.py --episodes 500
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Tuple

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from risklab.agents import ABMPurchaserAgent, ABMSupplierAgent  # noqa: E402
from risklab.agents.base import AgentConfig  # noqa: E402
from risklab.environments.base import EnvironmentConfig  # noqa: E402
from risklab.environments.competitive.bilateral_bargaining import (  # noqa: E402
    BilateralBargaining,
)
from risklab.evaluation.stats import mean, std  # noqa: E402
from risklab.experiments.abm_bargaining_trainer import play_episode  # noqa: E402

PRODUCTION_COST = 40.0
BUDGET_CAP = 120.0
MAX_ROUNDS = 10

#: The seller as Experiment I configures it: reservation 10 % above cost, prior
#: over the buyer's WTP anchored on its own cost at 2c = 80.
SELLER_ASYMMETRIC: Dict[str, Any] = dict(
    production_cost=PRODUCTION_COST,
    min_margin_ratio=0.1,
    wtp_prior_multiplier=2.0,
    beta=0.5,
    tft_weight=0.5,
    belief_alpha=0.3,
    wtp_bracket_share=0.5,
)
#: The same seller told the truth: its prior over the WTP *is* the budget cap
#: (3c = 120 = m) and it will trade down to cost.  Information asymmetry off.
SELLER_INFORMED: Dict[str, Any] = dict(
    SELLER_ASYMMETRIC, wtp_prior_multiplier=BUDGET_CAP / PRODUCTION_COST,
    min_margin_ratio=0.0, beta=1.0,
)
#: The buyer as Experiment I configures it.
BUYER_CONFIGURED: Dict[str, Any] = dict(
    budget_cap=BUDGET_CAP, initial_share=0.5, gamma=1.0, tft_weight=0.5, noise_sd=3.0
)
#: The buyer's mirror image of the informed seller: it opens at the seller's
#: true cost, concedes linearly to its ceiling, no jitter.  Deterministic, so
#: the symmetric benchmark is a point prediction rather than a distribution.
BUYER_SYMMETRIC: Dict[str, Any] = dict(
    budget_cap=BUDGET_CAP,
    initial_share=PRODUCTION_COST / BUDGET_CAP,
    gamma=1.0,
    tft_weight=0.5,
    noise_sd=0.0,
)


def _build(seller: Dict[str, Any], buyer: Dict[str, Any]):
    env = BilateralBargaining(
        EnvironmentConfig(
            name="bilateral_bargaining",
            env_type="competitive",
            max_rounds=MAX_ROUNDS,
            num_agents=2,
            parameters=dict(
                production_cost=PRODUCTION_COST,
                budget_cap=BUDGET_CAP,
                allow_communication=False,
                backup_enabled=False,
                agent_ids=["supplier", "purchaser"],
                seed=0,
            ),
        )
    )
    return (
        env,
        ABMSupplierAgent(AgentConfig("supplier", "supplier", parameters=dict(seller))),
        ABMPurchaserAgent(AgentConfig("purchaser", "purchaser", parameters=dict(buyer))),
    )


def _monotonicity_violations(summary: Dict[str, Any]) -> int:
    """Count paths that move a price against their own side.

    The accepted price is echoed into the other side's path by the
    environment, so the closing entry is dropped before checking.
    """
    offers = list(summary["offer_path"])
    counters = list(summary["counter_path"])
    if summary.get("closed_by") == "purchaser" and offers:
        offers = offers[:-1]
    if summary.get("closed_by") == "supplier" and counters:
        counters = counters[:-1]
    bad = sum(1 for k in range(len(offers) - 1) if offers[k + 1] > offers[k] + 1e-6)
    bad += sum(1 for k in range(len(counters) - 1) if counters[k + 1] < counters[k] - 1e-6)
    return bad


def evaluate(
    seller: Dict[str, Any], buyer: Dict[str, Any], episodes: int
) -> Dict[str, Any]:
    env, sup, pur = _build(seller, buyer)
    scrs: List[float] = []
    violations = 0
    agreements = 0
    opening_asks: List[float] = []
    for episode in range(episodes):
        summary = play_episode(env, sup, pur, seed=episode)
        violations += _monotonicity_violations(summary)
        if summary["offer_path"]:
            opening_asks.append(summary["offer_path"][0])
        if summary["scr"] is not None:
            scrs.append(summary["scr"])
            agreements += 1
    return {
        "scr": mean(scrs) if scrs else float("nan"),
        "sd": std(scrs) if len(scrs) > 1 else 0.0,
        "agreement_rate": agreements / max(episodes, 1),
        "violations": violations,
        "opening_ask": mean(opening_asks) if opening_asks else float("nan"),
    }


def sweep(episodes: int) -> None:
    """Show how much of Experiment I's number is the seller's fitted exponent
    and how much is the particular buyer it faces.

    Both are the obvious ways a rule-based baseline can be an artefact, and
    both are cheap to rule out, so there is no reason to leave them asserted.
    """
    from risklab.experiments.abm_bargaining_trainer import DEFAULT_OPPONENT_POOL

    print("\n  SCR by the seller's concession exponent (buyer as configured)")
    print(f"    {'beta':>6} {'SCR':>7} {'agree':>7}")
    for beta in (0.2, 0.35, 0.5, 0.75, 1.0, 1.5):
        r = evaluate(dict(SELLER_ASYMMETRIC, beta=beta), BUYER_CONFIGURED, episodes)
        print(f"    {beta:>6g} {r['scr']:>7.3f} {r['agreement_rate']:>7.2f}")

    print("\n  SCR by opponent (seller at the calibrated beta = 0.2)")
    print(f"    {'buyer':>10} {'SCR':>7} {'agree':>7}")
    for opponent in DEFAULT_OPPONENT_POOL:
        buyer = dict(BUYER_CONFIGURED)
        buyer.update({k: v for k, v in opponent.items() if k != "name"})
        r = evaluate(dict(SELLER_ASYMMETRIC, beta=0.2), buyer, episodes)
        print(f"    {opponent['name']:>10} {r['scr']:>7.3f} {r['agreement_rate']:>7.2f}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--episodes", type=int, default=200)
    ap.add_argument("--sweep", action="store_true",
                    help="Also sweep the seller's beta and the buyer's tactic.")
    args = ap.parse_args()

    rows: List[Tuple[str, Dict[str, Any], str]] = [
        (
            "symmetric benchmark",
            evaluate(SELLER_INFORMED, BUYER_SYMMETRIC, args.episodes),
            "SCR should be 0.50 — identical information, identical tactics",
        ),
        (
            "asymmetry on, symmetric buyer",
            evaluate(SELLER_ASYMMETRIC, BUYER_SYMMETRIC, args.episodes),
            "only the seller's knowledge of m changes",
        ),
        (
            "Experiment I as configured",
            evaluate(SELLER_ASYMMETRIC, BUYER_CONFIGURED, args.episodes),
            "the headline arm (beta is refitted per run by the driver)",
        ),
    ]

    print(f"\nABM sanity checks — {args.episodes} episodes per row\n")
    print(f"{'condition':<32} {'SCR':>7} {'sd':>7} {'agree':>7} "
          f"{'open':>7} {'mono!':>6}")
    print("-" * 72)
    ok = True
    for name, r, _note in rows:
        print(f"{name:<32} {r['scr']:>7.3f} {r['sd']:>7.3f} "
              f"{r['agreement_rate']:>7.2f} {r['opening_ask']:>7.1f} "
              f"{r['violations']:>6d}")
        if r["violations"]:
            ok = False
    print()
    for name, _r, note in rows:
        print(f"  {name}: {note}")

    sym = rows[0][1]
    print()
    if abs(sym["scr"] - 0.5) > 0.02:
        print(f"  FAIL: symmetric benchmark is {sym['scr']:.3f}, expected 0.50 "
              "-- the model has an asymmetry that is not information.")
        ok = False
    else:
        print(f"  PASS: symmetric benchmark {sym['scr']:.3f} ~ 0.50.")
    if ok:
        print("  PASS: no monotone-concession violations.")
    else:
        print("  FAIL: monotone-concession violations found.")
    delta = rows[2][1]["scr"] - rows[0][1]["scr"]
    print(f"\n  Information asymmetry moves the ABM seller's capture by "
          f"{delta:+.3f} SCR relative to the symmetric benchmark.")

    if args.sweep:
        sweep(args.episodes)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
