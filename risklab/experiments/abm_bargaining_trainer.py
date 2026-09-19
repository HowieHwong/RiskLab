"""
Minimal calibration phase for the ABM bargaining baseline (Risk 1.5, Exp I).

The rule-based seller has exactly one free quantity: its concession exponent
``beta``.  This module fixes it by self-play — the seller plays the *same*
:class:`BilateralBargaining` environment used in the experiment, and the arm
with the best score wins.

Why the opponent **pool**
------------------------
An earlier version scored each arm against the single rule-based buyer the
seller would then face in the evaluation.  That is a self-fulfilling loop: if
the buyer concedes unilaterally, the most extreme arm always wins, and the
resulting "surplus capture" measures the buyer's stubbornness, not the
seller's strategy.  Calibration therefore now runs against a **pre-registered
pool** of buyers spanning the plausible tactic space — Boulware through
Conceder, stubborn tit-for-tat through soft — and the winning arm is the one
with the best **worst-case** mean profit across the pool (maximin).  An arm
cannot win by exploiting one weak opponent, and the full arm × opponent matrix
is returned so the sensitivity is visible rather than asserted.

Why it is so small.  The Risk 1.1 baseline needed millions of rounds because
tabular Q-learning has to discover a policy over a state space.  Here the
policy family is a one-parameter concession curve, so a couple of hundred
paired episodes per cell settle the choice; the whole search costs a second or
two of CPU and is deterministic given ``seed``.  Cells share their episode
seeds (common random numbers), so every comparison is paired and low-variance.

What this deliberately does **not** do: look at any LLM transcript.  Every
buyer in the pool is rule-based and pre-registered, so the ABM arm cannot be
tuned toward — or away from — the LLM result.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from risklab.agents.base import Agent
from risklab.environments.competitive.bilateral_bargaining import BilateralBargaining

#: Pre-registered search grid: Boulware (patient) through Conceder (generous).
DEFAULT_BETA_GRID: Tuple[float, ...] = (0.2, 0.35, 0.5, 0.75, 1.0, 1.5)

#: Pre-registered opponent pool.  ``linear`` is the buyer the evaluation
#: episode actually uses; the other four bracket it on both sides so no arm
#: can win by being tuned to a single opponent.  Overrides are applied on top
#: of the buyer's config, so anything not named here stays as configured.
DEFAULT_OPPONENT_POOL: Tuple[Dict[str, Any], ...] = (
    {"name": "linear",    "gamma": 1.0, "initial_share": 0.50, "tft_weight": 0.5},
    {"name": "boulware",  "gamma": 0.5, "initial_share": 0.40, "tft_weight": 0.5},
    {"name": "conceder",  "gamma": 2.0, "initial_share": 0.60, "tft_weight": 0.5},
    {"name": "stubborn",  "gamma": 1.0, "initial_share": 0.40, "tft_weight": 0.9},
    {"name": "soft",      "gamma": 1.5, "initial_share": 0.60, "tft_weight": 0.2},
)


@dataclass
class ABMTrainingConfig:
    """Hyper-parameters of the ABM seller's calibration phase."""

    beta_grid: Sequence[float] = DEFAULT_BETA_GRID
    #: Optional second search dimension: the seller's ``min_margin_ratio``, so
    #: its reservation price is calibrated rather than assumed.  ``None`` keeps
    #: the reservation exactly as configured and searches ``beta`` alone, which
    #: is what Experiment I-A does.
    margin_grid: Optional[Sequence[float]] = None
    opponent_pool: Sequence[Mapping[str, Any]] = DEFAULT_OPPONENT_POOL
    episodes_per_arm: int = 200
    #: ``"maximin"`` (default) or ``"mean"`` across the pool.
    selection: str = "maximin"
    seed: int = 0
    verbose: bool = False


@dataclass
class ABMTrainingResult:
    """Diagnostics of one calibration run."""

    beta: float = 0.5
    #: Only set when a ``margin_grid`` was searched.
    min_margin_ratio: Optional[float] = None
    episodes_per_arm: int = 0
    selection: str = "maximin"
    #: One row per arm: worst-case and mean profit plus the per-opponent cells.
    arms: List[Dict[str, Any]] = field(default_factory=list)
    opponents: List[str] = field(default_factory=list)
    wall_time_sec: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "beta": self.beta,
            "min_margin_ratio": self.min_margin_ratio,
            "episodes_per_arm": self.episodes_per_arm,
            "selection": self.selection,
            "opponents": self.opponents,
            "arms": self.arms,
            "wall_time_sec": round(self.wall_time_sec, 3),
        }


def play_episode(
    environment: BilateralBargaining,
    supplier: Agent,
    purchaser: Agent,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Run one bargaining episode outside the logging runner.

    Mirrors the alternating turn order the ``MarketTurnBased`` protocol
    enforces during the real experiment, so calibration and evaluation see
    identical rules.
    """
    if seed is not None:
        environment.seed = seed
        for agent in (supplier, purchaser):
            if hasattr(agent, "seed_rng"):
                agent.seed_rng(seed)
    environment.reset()
    supplier.reset()
    purchaser.reset()

    sup_id = environment.supplier_id
    pur_id = environment.purchaser_id

    for _ in range(environment.max_rounds):
        if environment.done:
            break
        environment.step({sup_id: supplier.act(environment.get_observation(sup_id))})
        if environment.done:
            break
        environment.step({pur_id: purchaser.act(environment.get_observation(pur_id))})
    return environment.summary()


def clone_purchaser(purchaser: Agent, overrides: Mapping[str, Any]) -> Agent:
    """Build a variant of *purchaser* with its parameters patched.

    Used to materialise the opponent pool without touching the agent the
    evaluation episode will use.
    """
    config = copy.deepcopy(purchaser.config)
    params = dict(config.parameters or {})
    params.update({k: v for k, v in overrides.items() if k != "name"})
    config.parameters = params
    return type(purchaser)(config)


def _mean_profit(
    environment: BilateralBargaining,
    supplier: Agent,
    purchaser: Agent,
    episodes: int,
    seed_base: int,
) -> Tuple[float, float]:
    """Mean seller profit and agreement rate over paired episodes."""
    total = 0.0
    agreements = 0
    for episode in range(episodes):
        # Same seed sequence in every cell → paired comparison across arms.
        summary = play_episode(
            environment, supplier, purchaser, seed=seed_base + episode
        )
        if summary["agreement"] and summary["final_price"] is not None:
            total += summary["final_price"] - environment.production_cost
            agreements += 1
    n = max(episodes, 1)
    return total / n, agreements / n


def train_abm_supplier(
    environment: BilateralBargaining,
    agents: Sequence[Agent],
    config: ABMTrainingConfig,
) -> ABMTrainingResult:
    """Pick the seller's concession exponent by maximin play against a pool.

    Mutates the supplier agent in place (sets ``beta``) and returns the
    diagnostics to be stored alongside the run.
    """
    start = time.time()
    by_id = {a.agent_id: a for a in agents}
    supplier = by_id[environment.supplier_id]
    purchaser = by_id[environment.purchaser_id]

    if not hasattr(supplier, "beta"):
        raise TypeError(
            f"{type(supplier).__name__} has no 'beta' to calibrate; the ABM "
            "condition expects an abm_supplier."
        )

    original_seed = environment.seed
    original_beta = supplier.beta
    original_margin = getattr(supplier, "min_margin_ratio", None)
    pool = [dict(o) for o in config.opponent_pool] or [{"name": "as_configured"}]
    opponents = [(str(o.get("name", f"opp{i}")), clone_purchaser(purchaser, o))
                 for i, o in enumerate(pool)]

    # A one-element margin grid means "leave the reservation as configured",
    # which keeps the single-dimension search bit-for-bit what it always was.
    margins: Sequence[Optional[float]] = (
        list(config.margin_grid) if config.margin_grid else [None]
    )

    arms: List[Dict[str, Any]] = []
    for margin in margins:
        if margin is not None:
            supplier.min_margin_ratio = float(margin)
        for beta in config.beta_grid:
            supplier.beta = float(beta)
            cells: Dict[str, Dict[str, float]] = {}
            for name, opponent in opponents:
                profit, agree = _mean_profit(
                    environment,
                    supplier,
                    opponent,
                    config.episodes_per_arm,
                    config.seed * 1_000_003,
                )
                cells[name] = {
                    "mean_profit": round(profit, 4),
                    "agreement_rate": round(agree, 4),
                }
            profits = [c["mean_profit"] for c in cells.values()]
            arm: Dict[str, Any] = {
                "beta": float(beta),
                "worst_profit": round(min(profits), 4),
                "mean_profit": round(sum(profits) / len(profits), 4),
                "cells": cells,
            }
            if margin is not None:
                arm["min_margin_ratio"] = float(margin)
            arms.append(arm)
            if config.verbose:
                row = "  ".join(
                    f"{n}={cells[n]['mean_profit']:6.2f}" for n, _ in opponents
                )
                tag = "" if margin is None else f" margin={margin:<5g}"
                print(
                    f"    beta={beta:<5g}{tag} worst={arm['worst_profit']:6.2f} "
                    f"mean={arm['mean_profit']:6.2f}   {row}"
                )

    key = "worst_profit" if config.selection == "maximin" else "mean_profit"
    # Ties break on the other criterion, so the choice never depends on grid
    # ordering alone.
    other = "mean_profit" if key == "worst_profit" else "worst_profit"
    best = max(arms, key=lambda a: (a[key], a[other]))
    supplier.beta = float(best["beta"])
    best_margin = best.get("min_margin_ratio")
    if best_margin is not None:
        supplier.min_margin_ratio = float(best_margin)
    elif original_margin is not None:
        supplier.min_margin_ratio = original_margin
    environment.seed = original_seed
    if config.verbose:
        extra = "" if best_margin is None else f", margin={best_margin:g}"
        print(f"    -> selected beta={supplier.beta:g}{extra} by "
              f"{config.selection} (was beta={original_beta:g})")

    return ABMTrainingResult(
        beta=float(best["beta"]),
        min_margin_ratio=best_margin,
        episodes_per_arm=config.episodes_per_arm,
        selection=config.selection,
        arms=arms,
        opponents=[n for n, _ in opponents],
        wall_time_sec=time.time() - start,
    )
