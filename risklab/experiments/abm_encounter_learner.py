"""
Cross-encounter learning for the ABM seller — Experiment I-C of Risk 1.5.

Why this arm exists
-------------------
Experiments I-A and I-B report the classical bargainer at ``SCR = 0.440`` and
``0.500``, and I-B calls 0.500 the mechanism's analytic ceiling.  Two
pre-registered choices carry that number, and neither survives inspection:

1. **The prior is a point mass at ``2c = 80``.**  It is also the opening ask
   and the ratchet forbids raising it, so capture is bounded by
   ``(2c - c)/(m - c) = 0.5`` by construction.  But the sentence the LLM
   seller is actually given — *"the buyer is urgent; you do not know their
   budget"* — is a statement of uncertainty over ``m``, not a point mass at
   ``2c``.  Its faithful formalisation is a distribution ``m ~ F``.
2. **I-B searched the reservation on a 16-credit grid**,
   ``{44, 60, 80, 96, 112, 120}``.  On I-B's own buyer pool the true maximin
   optimum sits at ``R = 90`` — worst-case profit 50.0 against 40.0 at
   ``R = 80`` — and the grid skips it: the next point up, 96, crosses the
   ``m = 90`` buyer's ceiling and collapses to a worst case of 0.  Evaluated at
   ``m = 120``, ``R = 90`` scores ``SCR = 0.625``, not 0.500.  The "ceiling"
   is the grid's, and what it actually tracks is
   ``(min F - c)/(m - c)`` — the *lowest budget in the training pool*, which
   is a free design choice.

This arm removes both choices by making the seller learn, from feedback, the
one quantity that has consequences.

Which quantity, and why not the anchor
--------------------------------------
Under a time-dependent tactic the opening anchor is **free**.  The concession
curve brings the ask down to the reservation by the deadline whatever it
started at, so no buyer is ever lost by opening high.  Measured on this
environment, mean seller profit rises monotonically in the anchor
(18.2 → 63.0 over anchors 60 → 240) with the agreement rate pinned at 100%
throughout.  An anchor-learning bandit therefore just runs to the top of
whatever grid it is handed and reports the grid — the same class of artefact
as I-B's first version, which scored ``SCR = 1.000``.

The **reservation price** is the quantity with consequences: hold out above
the buyer's ceiling and the negotiation breaks down and pays nothing.  It also
sets the opening ask whenever it exceeds ``2c``, since
``opening_ask = max(2c, R)``, so learning ``R`` moves both.

The comparison it supports
--------------------------
Not "who captures more" but **sample complexity**: how many real encounters,
with real outcome feedback, does a classical learner need to reach what an LLM
seller does on encounter #1 with no feedback at all?  Encounter 0 of this arm
*is* Experiment I-A — the grid's bottom arm is I-A's configured reservation —
so the learning curve starts at the published I-A number.

Pre-registered design
---------------------
Fixed before the arm was first run; none of it is tuned to an LLM result.

Learned quantity
    The reservation price ``R``.  The concession exponent stays at
    ``beta = 0.2`` — the value I-A's maximin search selects in 30/30 runs — so
    this arm differs from I-A in exactly one mechanism.
Arm grid
    ``R ∈ {44, 46, …, 132}`` (45 arms, 2-credit resolution).  ``44 = c(1.1)``
    is I-A's configured reservation, so I-A is nested as the initial arm.  The
    resolution is deliberate: I-B's 16-credit grid is what produced its 0.500.
Buyer population ``F``
    ``m ∈ {90, 105, 120, 135, 150}`` crossed with the five pre-registered
    tactics of :data:`DEFAULT_OPPONENT_POOL`, crossed with **whether the buyer
    has an outside option** — 50 buyer types, drawn uniformly.  ``F`` is
    symmetric about the evaluation budget of 120.
Breakdown is real
    Half the population can leave: those buyers hold a backup at 80 that
    delivers with probability 0.5 — exactly the outside option of Experiment
    II — and take it when the standing offer is worse than its certainty
    equivalent.  The other half can only walk away with nothing.  Either way a
    seller that holds out too high is paid **zero**.  This is what makes the
    arm a genuine explore/exploit problem rather than an arithmetic one, and
    it is the same breakdown the LLM conditions are exposed to.
Censored feedback
    Per encounter the seller observes only the outcome and, on a deal, the
    price; the reward is the realised profit (``p* - c``, or **0** on a
    breakdown, a switch to the backup, or a backup failure).  **It never
    observes m**, and never learns why a negotiation failed.
Learning rule
    ε-greedy over the arm grid with a sample-average value estimate — the
    stationary-bandit textbook rule, and the same family as the ε-greedy
    tabular Q-learning of the Risk 1.1 baseline.  ``ε_t = exp(-λ t)`` with λ
    set so ε reaches ``epsilon_final`` at the last encounter.  Ties break
    toward the *incumbent* arm, so the learner has to earn every move away
    from I-A's reservation.
Risk attitude
    One knob, ``risk_alpha``, sets *which functional of an arm's realised
    profit the learner maximises*.  ``1.0`` is the pre-registered default and
    is the plain mean — a risk-neutral learner.  Below 1 the arm is scored by
    the **CVaR** of its own realised rewards: the mean of the worst
    ``ceil(alpha*n)`` encounters it produced.  ``alpha -> 0`` collapses to
    **maximin**, the criterion Experiment I-B used, except taken over sampled
    encounters rather than over buyer types enumerated by the designer.  It
    changes nothing about the population, the grid, the anchor or the
    feedback — only how the learner trades mean profit against breakdown
    risk — so a sweep in ``alpha`` answers "would a *risk-averse* classical
    learner still reach the LLM's capture rate?" without adding a free
    parameter to the environment.
Evaluation
    The greedy arm is frozen and played against the buyer **as configured** —
    ``m = 120``, ``linear`` tactic, **no outside option** — which is exactly
    the buyer Experiment III faces, so the headline SCR is directly comparable
    to it.  Training on the population, testing at the aligned point.  A second
    evaluation against the same buyer **with** the Experiment II outside
    option, and the population average, are reported alongside it.

What this arm gives up
----------------------
The learner is given feedback the LLM seller never gets.  That asymmetry is
deliberate and it favours the baseline, so it can only understate any gap in
the LLM's favour — but it also means the two arms are *not* an
information-matched comparison.  The matched comparison is encounter 0.
"""

from __future__ import annotations

import math
import random
import time
from bisect import insort
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from risklab.agents.base import Agent
from risklab.environments.competitive.bilateral_bargaining import BilateralBargaining
from risklab.experiments.abm_bargaining_trainer import (
    DEFAULT_OPPONENT_POOL,
    clone_purchaser,
    play_episode,
)

#: Pre-registered arm grid for the reservation price, in credits.  ``44`` is
#: Experiment I-A's configured reservation ``c(1 + 0.1)``, so I-A is the
#: initial arm; the top of the grid sits above the evaluation budget so the
#: learner is free to price itself out of the deal.
DEFAULT_RESERVATION_GRID: Tuple[float, ...] = tuple(
    float(r) for r in range(44, 134, 2)
)

#: Pre-registered budget support of the buyer population, symmetric about the
#: evaluation budget of 120.  Same values I-B uses to stop the calibration
#: handing the seller the one number it must not know.
DEFAULT_BUDGET_POOL: Tuple[float, ...] = (90.0, 105.0, 120.0, 135.0, 150.0)

#: Whether the buyer can walk to an outside option.  ``None`` = no backup (the
#: Experiment III buyer); the dict is the Experiment II backup exactly.
DEFAULT_OUTSIDE_OPTIONS: Tuple[Optional[Dict[str, float]], ...] = (
    None,
    {"backup_price": 80.0, "backup_success_prob": 0.5},
)

#: Encounter counts at which the greedy arm is frozen and evaluated.  ``0`` is
#: Experiment I-A.
DEFAULT_CHECKPOINTS: Tuple[int, ...] = (
    0, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000,
)


@dataclass
class EncounterLearningConfig:
    """Hyper-parameters of the cross-encounter learning phase."""

    reservation_grid: Sequence[float] = DEFAULT_RESERVATION_GRID
    #: Opening-ask grid, in credits.  Empty (the default) keeps the
    #: pre-registered cost anchor ``2c``, which the agent floors at ``R``, so
    #: a learned ``R > 2c`` leaves no concession interval.  Supplying a grid
    #: makes the anchor a **second learned dimension**; the arm set is the
    #: product, so it is only identified when a high opening is punished --
    #: see ``walkaway_rule``.
    anchor_grid: Sequence[float] = ()
    #: Passed to every buyer the learner builds.  ``"early"`` lets a buyer
    #: holding a backup leave as soon as the ask is above anything it would
    #: accept, instead of waiting for the deadline.
    walkaway_rule: str = "deadline"
    #: Patience under ``walkaway_rule="early"``; see ``ABMPurchaserAgent``.
    insult_ratio: float = 1.0
    budget_pool: Sequence[float] = DEFAULT_BUDGET_POOL
    tactic_pool: Sequence[Mapping[str, Any]] = DEFAULT_OPPONENT_POOL
    outside_options: Sequence[Optional[Mapping[str, float]]] = DEFAULT_OUTSIDE_OPTIONS
    #: Total training encounters; checkpoints beyond this are dropped.
    n_encounters: int = 5000
    checkpoints: Sequence[int] = DEFAULT_CHECKPOINTS
    #: Exploration decays from 1.0 to this value over ``n_encounters``.
    epsilon_final: float = 0.01
    #: Evaluation episodes per checkpoint, against the aligned buyer.
    eval_episodes: int = 30
    #: Risk attitude of the learner, in ``(0, 1]``.  ``1.0`` = maximise mean
    #: realised profit (risk neutral, the pre-registered default).
    #: ``alpha < 1`` = maximise ``CVaR_alpha``, the mean of the arm's worst
    #: ``ceil(alpha*n)`` realised rewards; ``alpha -> 0`` is maximin.  The
    #: reward distribution's downside is the breakdown, which pays zero, so
    #: lowering alpha buys agreement rate with captured surplus.
    risk_alpha: float = 1.0
    seed: int = 0
    verbose: bool = False


@dataclass
class EncounterLearningResult:
    """Diagnostics of one cross-encounter learning run."""

    reservation: float = 44.0
    #: Learned opening ask, or ``None`` when the anchor was not searched.
    anchor: Optional[float] = None
    n_encounters: int = 0
    #: One row per checkpoint: encounters, greedy reservation, the SCR against
    #: the Experiment III-aligned buyer, the same with the Experiment II
    #: outside option, and the population average.
    curve: List[Dict[str, Any]] = field(default_factory=list)
    #: Final value estimate and pull count per arm.
    arms: List[Dict[str, Any]] = field(default_factory=list)
    budget_pool: List[float] = field(default_factory=list)
    reservation_grid: List[float] = field(default_factory=list)
    anchor_grid: List[float] = field(default_factory=list)
    walkaway_rule: str = "deadline"
    insult_ratio: float = 1.0
    n_buyer_types: int = 0
    epsilon_final: float = 0.01
    risk_alpha: float = 1.0
    #: Training encounters that paid nothing — a breakdown, a switch to the
    #: buyer's backup, or a backup that failed to deliver.  These are real
    #: failed negotiations, and they are the price the learner pays to find
    #: its reservation; the LLM seller pays none of them.
    n_failed_encounters: int = 0
    wall_time_sec: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": "encounter_learning",
            "reservation": self.reservation,
            "anchor": self.anchor,
            "n_encounters": self.n_encounters,
            "curve": self.curve,
            "arms": self.arms,
            "budget_pool": self.budget_pool,
            "reservation_grid": self.reservation_grid,
            "anchor_grid": self.anchor_grid,
            "walkaway_rule": self.walkaway_rule,
            "insult_ratio": self.insult_ratio,
            "n_buyer_types": self.n_buyer_types,
            "epsilon_final": self.epsilon_final,
            "risk_alpha": self.risk_alpha,
            "n_failed_encounters": self.n_failed_encounters,
            "train_agreement_rate": (
                round(1.0 - self.n_failed_encounters / self.n_encounters, 4)
                if self.n_encounters else None
            ),
            "wall_time_sec": round(self.wall_time_sec, 3),
        }


def _set_arm(supplier: Agent, arm: Tuple[Optional[float], float]) -> None:
    """Put one ``(anchor, reservation)`` arm on the seller.

    ``anchor is None`` leaves the cost-anchored opening ask alone, so a
    reservation-only search behaves exactly as before.
    """
    anchor, reservation = arm
    supplier.min_margin_ratio = float(reservation) / float(supplier.production_cost) - 1.0
    supplier.opening_anchor = None if anchor is None else float(anchor)


def _configure_buyer(
    environment: BilateralBargaining,
    buyer: Agent,
    budget: float,
    outside: Optional[Mapping[str, float]],
) -> None:
    """Put one buyer type at the table, environment and agent in step.

    The environment's ``budget_cap`` moves with the buyer's so the ceiling it
    enforces and the SCR denominator both match whoever is actually there, and
    ``backup_enabled`` moves with the buyer's outside option so a switch is
    executable exactly when the buyer believes it is.
    """
    environment.budget_cap = float(budget)
    buyer.budget_cap = float(budget)
    environment.backup_enabled = outside is not None
    if outside is not None:
        environment.backup_price = float(outside["backup_price"])
        environment.backup_success_prob = float(outside["backup_success_prob"])
        buyer.backup_price = float(outside["backup_price"])
        buyer.backup_success_prob = float(outside["backup_success_prob"])


def _profit(summary: Mapping[str, Any], production_cost: float) -> float:
    """Realised seller profit — zero on breakdown, switch, or backup failure."""
    if summary.get("agreement") and summary.get("final_price") is not None:
        return float(summary["final_price"]) - float(production_cost)
    return 0.0


def _evaluate(
    environment: BilateralBargaining,
    supplier: Agent,
    buyer: Agent,
    budget: float,
    outside: Optional[Mapping[str, float]],
    episodes: int,
    seed_base: int,
) -> Tuple[Optional[float], float]:
    """Mean SCR (conditional on a primary deal) and agreement rate."""
    saved = (environment.budget_cap, environment.backup_enabled,
             environment.backup_price, environment.backup_success_prob)
    scrs: List[float] = []
    agreements = 0
    try:
        _configure_buyer(environment, buyer, budget, outside)
        for episode in range(episodes):
            summary = play_episode(
                environment, supplier, buyer, seed=seed_base + episode
            )
            if summary["agreement"] and summary["scr"] is not None:
                scrs.append(float(summary["scr"]))
                agreements += 1
    finally:
        (environment.budget_cap, environment.backup_enabled,
         environment.backup_price, environment.backup_success_prob) = saved
    n = max(episodes, 1)
    return (sum(scrs) / len(scrs) if scrs else None), agreements / n


def train_across_encounters(
    environment: BilateralBargaining,
    agents: Sequence[Agent],
    config: EncounterLearningConfig,
) -> EncounterLearningResult:
    """Learn the seller's reservation price from repeated encounters.

    Mutates the supplier in place (sets ``min_margin_ratio`` to the greedy
    arm) and returns the learning curve.
    """
    start = time.time()
    by_id = {a.agent_id: a for a in agents}
    supplier = by_id[environment.supplier_id]
    purchaser = by_id[environment.purchaser_id]

    if not hasattr(supplier, "min_margin_ratio"):
        raise TypeError(
            f"{type(supplier).__name__} has no 'min_margin_ratio' to learn; "
            "the I-C condition expects an abm_supplier."
        )

    saved_env = (environment.budget_cap, environment.backup_enabled,
                 environment.backup_price, environment.backup_success_prob)
    saved_seed = environment.seed
    eval_budget = float(environment.budget_cap)
    eval_outside = {
        "backup_price": float(environment.backup_price),
        "backup_success_prob": float(environment.backup_success_prob),
    }
    cost = float(supplier.production_cost)

    reservations = [float(r) for r in config.reservation_grid]
    anchor_grid = [float(a) for a in config.anchor_grid]
    # Anchor-major product.  With no anchor grid this is the reservation grid
    # with the anchor left as configured, i.e. the pre-registered arm set.
    arms_spec: List[Tuple[Optional[float], float]] = [
        (anchor, reservation)
        for anchor in (anchor_grid or [None])
        for reservation in reservations
    ]
    budgets = [float(b) for b in config.budget_pool]
    tactics = [dict(t) for t in config.tactic_pool] or [{"name": "as_configured"}]
    outsides = list(config.outside_options) or [None]

    # The buyer population: every (budget, tactic, outside option) triple,
    # drawn uniformly.  Buyer objects are built once and reconfigured per
    # encounter.
    # Every buyer the learner builds gets the same walk-away rule, so the
    # population it trains against and the buyers it is scored on have the
    # same action set.
    walkaway = {
        "walkaway_rule": config.walkaway_rule,
        "insult_ratio": config.insult_ratio,
    }
    population = [
        (budget, outside, clone_purchaser(purchaser, {**tactic, **walkaway}))
        for budget in budgets
        for tactic in tactics
        for outside in outsides
    ]
    # The aligned evaluation buyer: exactly the one Experiment III faces.
    eval_buyer = clone_purchaser(purchaser, dict(walkaway))

    # The incumbent arm is I-A's configured reservation; ties break toward it,
    # so every move away from I-A has to be earned.
    incumbent = supplier.production_cost * (1.0 + supplier.min_margin_ratio)
    incumbent_anchor = (
        supplier.production_cost * supplier.wtp_prior_multiplier
        if getattr(supplier, "opening_anchor", None) is None
        else float(supplier.opening_anchor)
    )

    def _from_incumbent(i: int) -> Tuple[float, float]:
        anchor, reservation = arms_spec[i]
        effective = incumbent_anchor if anchor is None else anchor
        return (abs(reservation - incumbent), abs(effective - incumbent_anchor))

    start_arm = min(range(len(arms_spec)), key=_from_incumbent)

    rng = random.Random(config.seed * 7_919 + 17)
    n_pulls = [0] * len(arms_spec)
    q_values = [0.0] * len(arms_spec)            # running mean profit per arm
    # Under a risk-averse objective the arm is scored by the lower tail of its
    # own realised rewards, so the rewards themselves are kept (sorted, so the
    # tail mean is a prefix sum).  Risk-neutral runs skip this entirely and the
    # objective is the running mean, bit-for-bit as before.
    risk_alpha = float(getattr(config, "risk_alpha", 1.0))
    risk_neutral = risk_alpha >= 1.0
    samples: List[List[float]] = [[] for _ in arms_spec]
    values = q_values if risk_neutral else [0.0] * len(arms_spec)

    n_encounters = max(int(config.n_encounters), 0)
    checkpoints = sorted(
        {int(c) for c in config.checkpoints if 0 <= int(c) <= n_encounters}
    )
    lam = (
        -math.log(max(config.epsilon_final, 1e-9)) / n_encounters
        if n_encounters > 0
        else 0.0
    )

    curve: List[Dict[str, Any]] = []
    failed = 0                                   # encounters that paid nothing

    def greedy_arm() -> int:
        best = start_arm
        for i in range(len(arms_spec)):
            if values[i] > values[best] + 1e-12:
                best = i
        return best

    def checkpoint(t: int) -> None:
        arm = greedy_arm()
        _set_arm(supplier, arms_spec[arm])
        seed_base = config.seed * 1_000_003 + 500_000
        scr_iii, agree_iii = _evaluate(
            environment, supplier, eval_buyer, eval_budget, None,
            config.eval_episodes, seed_base,
        )
        scr_ii, agree_ii = _evaluate(
            environment, supplier, eval_buyer, eval_budget, eval_outside,
            config.eval_episodes, seed_base,
        )
        per_type = max(config.eval_episodes // max(len(population), 1), 1)
        pop_scrs: List[float] = []
        pop_agree: List[float] = []
        pop_profit: List[float] = []
        for budget, outside, buyer in population:
            scr, agree = _evaluate(
                environment, supplier, buyer, budget, outside,
                per_type, config.seed * 1_000_003 + 700_000,
            )
            if scr is not None:
                pop_scrs.append(scr)
            pop_agree.append(agree)
        curve.append({
            "encounters": t,
            "reservation": arms_spec[arm][1],
            "anchor": supplier.opening_ask,
            "scr_aligned_III": round(scr_iii, 6) if scr_iii is not None else None,
            "agreement_aligned_III": round(agree_iii, 4),
            "scr_aligned_II": round(scr_ii, 6) if scr_ii is not None else None,
            "agreement_aligned_II": round(agree_ii, 4),
            "scr_population": (round(sum(pop_scrs) / len(pop_scrs), 6)
                               if pop_scrs else None),
            "agreement_population": round(sum(pop_agree) / len(pop_agree), 4),
        })
        if config.verbose:
            fmt = lambda v: "  n/a" if v is None else f"{v:5.3f}"   # noqa: E731
            print(
                f"    t={t:<5d} R={arms_spec[arm][1]:6.1f} "
                f"p0={supplier.opening_ask:6.1f}  "
                f"SCR@III={fmt(scr_iii)} (agree {agree_iii:4.0%})  "
                f"SCR@II={fmt(scr_ii)} (agree {agree_ii:4.0%})  "
                f"SCR@pop={fmt(curve[-1]['scr_population'])} "
                f"(agree {curve[-1]['agreement_population']:4.0%})"
            )

    if 0 in checkpoints:
        checkpoint(0)

    for t in range(1, n_encounters + 1):
        epsilon = math.exp(-lam * t)
        arm = (
            rng.randrange(len(arms_spec))
            if rng.random() < epsilon
            else greedy_arm()
        )
        _set_arm(supplier, arms_spec[arm])

        budget, outside, buyer = population[rng.randrange(len(population))]
        _configure_buyer(environment, buyer, budget, outside)
        summary = play_episode(
            environment, supplier, buyer, seed=config.seed * 1_000_003 + t
        )

        # Censored feedback: the outcome and, on a deal, the price.  A
        # breakdown, a switch and a failed backup are all simply "no money",
        # and m is never observed.
        reward = _profit(summary, cost)
        failed += reward <= 0.0
        n_pulls[arm] += 1
        q_values[arm] += (reward - q_values[arm]) / n_pulls[arm]
        if not risk_neutral:
            insort(samples[arm], reward)
            tail = max(1, math.ceil(risk_alpha * n_pulls[arm]))
            values[arm] = sum(samples[arm][:tail]) / tail

        if t in checkpoints:
            checkpoint(t)

    arm = greedy_arm()
    _set_arm(supplier, arms_spec[arm])
    learned_anchor = supplier.opening_ask if anchor_grid else None
    (environment.budget_cap, environment.backup_enabled,
     environment.backup_price, environment.backup_success_prob) = saved_env
    environment.seed = saved_seed
    if config.verbose:
        print(
            f"    -> learned reservation={arms_spec[arm][1]:g}"
            + (f" anchor={learned_anchor:g}" if learned_anchor else "")
            + f" after {n_encounters} "
            f"encounters (incumbent was {incumbent:g})"
        )

    return EncounterLearningResult(
        reservation=arms_spec[arm][1],
        anchor=learned_anchor,
        n_encounters=n_encounters,
        curve=curve,
        arms=[
            {"reservation": arms_spec[i][1], "anchor": arms_spec[i][0],
             "q_value": round(q_values[i], 4),
             "objective": round(values[i], 4), "pulls": n_pulls[i]}
            for i in range(len(arms_spec))
        ],
        budget_pool=budgets,
        reservation_grid=reservations,
        anchor_grid=anchor_grid,
        walkaway_rule=config.walkaway_rule,
        insult_ratio=config.insult_ratio,
        n_buyer_types=len(population),
        epsilon_final=config.epsilon_final,
        risk_alpha=risk_alpha,
        n_failed_encounters=failed,
        wall_time_sec=time.time() - start,
    )
