"""
Offline trainer for :class:`~risklab.agents.q_learning_seller_agent.QLearningSellerAgent`.

Q-learning agents cannot be dropped straight into a 10-round episode the way
LLM agents can — they have to learn a policy first.  This module runs that
learning phase **inside the very same environment instance** that the
evaluation episode will use, so the market rules (allocation, tie-splitting,
profit function, customer count) are identical by construction rather than by
reimplementation.

    previous round's price profile
              ↓
    three Q-learning sellers pick prices (ε-greedy)
              ↓
    environment resolves the market and returns profits
              ↓
    each seller applies one Q-update
              ↓
    next round

After training the policies are frozen (``ε = 0``) and the environment is
restored to its configured episode length, so the caller can hand the same
agents to :class:`~risklab.experiments.runner.ExperimentRunner` and get a
trajectory that the standard risk detectors consume unchanged.

Convergence follows Calvano et al. (2020) in spirit: training is considered
converged once every agent's greedy action is unchanged, in every state, for
``convergence_window`` consecutive rounds.  We sample the policy every
``check_interval`` rounds rather than every round, which is cheaper and
slightly conservative.

That strict criterion is demanding: with a constant learning rate the Q-values
never stop moving, and in a knife-edge Bertrand market neighbouring actions
have near-identical values, so a handful of argmax entries keep flipping long
after prices have plainly settled.  In our runs it does not fire even at 2M
rounds.  Two further signals are therefore reported:

``price_stable``
    the practical criterion, defined on the quantity the experiment actually
    measures: the mean market price over the last ``convergence_window``
    training rounds differs from the preceding window by at most
    ``price_tolerance`` credits.
``final_policy_churn``
    fraction of greedy actions that changed at the last policy check — a
    diagnostic, not a gate.

If a run finishes with ``price_stable=False``, raise ``training_rounds`` (the
plan's own fallback: "if still unstable, train longer").  Report whichever
criterion you use; do not present an unsettled policy as a converged one.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from risklab.agents.q_learning_seller_agent import QLearningSellerAgent, State
from risklab.environments.competitive.homogeneous_goods_market import (
    HomogeneousGoodsMarket,
)


@dataclass
class QTrainingConfig:
    """Hyper-parameters of the learning phase (not of the agents themselves).

    Attributes
    ----------
    training_rounds : int
        Total market rounds to train on.  The plan suggests 200k–500k, but in
        this market the price path is still drifting there (~1.5 credits
        between consecutive 50k windows); 5M settles it (~0.006).  See the
        module docstring.
    convergence_window : int
        Window length used by both stability criteria: consecutive rounds of an
        unchanged greedy policy (``converged``), and the price-averaging window
        (``price_stable``).
    price_tolerance : float
        Maximum drift, in credits, between the mean market price of the last
        two ``convergence_window``-round windows for ``price_stable``.
    check_interval : int
        How often the greedy policy is sampled for the convergence check.
    stop_on_convergence : bool
        Stop early once converged instead of exhausting the budget.
    epsilon_final : float
        Target exploration rate at the end of training; used to derive β when
        the agent does not pin ``epsilon_decay`` explicitly.
    seed : int
        Base seed; each agent gets a distinct derived seed.
    price_log_bin : int
        Bin width (in rounds) for the training-price learning curve.
    verbose : bool
        Print progress while training.
    log_interval : int
        Progress print frequency (rounds).
    """

    training_rounds: int = 5_000_000
    convergence_window: int = 50_000
    price_tolerance: float = 0.25
    check_interval: int = 1_000
    stop_on_convergence: bool = False
    epsilon_final: float = 1e-3
    seed: int = 0
    price_log_bin: int = 10_000
    verbose: bool = False
    log_interval: int = 50_000


@dataclass
class QTrainingResult:
    """Diagnostics of one training run (one independent trio of sellers)."""

    converged: bool = False
    price_stable: bool = False
    rounds_trained: int = 0
    stable_rounds: int = 0
    price_drift: Optional[float] = None
    final_policy_churn: float = 1.0
    final_epsilon: float = 0.0
    final_prices: Dict[str, int] = field(default_factory=dict)
    final_profile: Tuple[int, ...] = ()
    learning_curve: List[Dict[str, float]] = field(default_factory=list)
    last_window_mean_price: float = 0.0
    wall_time_sec: float = 0.0
    per_agent: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "converged": self.converged,
            "price_stable": self.price_stable,
            "rounds_trained": self.rounds_trained,
            "stable_rounds": self.stable_rounds,
            "price_drift": self.price_drift,
            "final_policy_churn": self.final_policy_churn,
            "final_epsilon": self.final_epsilon,
            "final_prices": self.final_prices,
            "final_profile": list(self.final_profile),
            "learning_curve": self.learning_curve,
            "last_window_mean_price": self.last_window_mean_price,
            "wall_time_sec": round(self.wall_time_sec, 2),
            "per_agent": self.per_agent,
        }


def train_q_learning_sellers(
    environment: HomogeneousGoodsMarket,
    agents: Sequence[QLearningSellerAgent],
    config: Optional[QTrainingConfig] = None,
) -> QTrainingResult:
    """Train a trio (or any number) of Q-learning sellers in *environment*.

    Parameters
    ----------
    environment : HomogeneousGoodsMarket
        The same environment instance that will later be used for evaluation.
        Its ``max_rounds`` is temporarily raised for training and restored
        afterwards.
    agents : sequence[QLearningSellerAgent]
        Sellers to train.  Their Q-tables are updated in place and left frozen
        (``training=False``) when training finishes.
    config : QTrainingConfig, optional

    Returns
    -------
    QTrainingResult
    """
    cfg = config or QTrainingConfig()

    non_q = [a for a in agents if not isinstance(a, QLearningSellerAgent)]
    if non_q:
        raise TypeError(
            "train_q_learning_sellers expects QLearningSellerAgent instances; "
            f"got: {[type(a).__name__ for a in non_q]}"
        )
    if not agents:
        raise ValueError("No agents to train.")

    agent_ids = sorted(a.agent_id for a in agents)
    by_id: Dict[str, QLearningSellerAgent] = {a.agent_id: a for a in agents}

    # --- Prepare agents --------------------------------------------------
    for offset, aid in enumerate(agent_ids):
        agent = by_id[aid]
        agent.set_peers(agent_ids)
        agent.seed_rng(cfg.seed * 1_000 + offset)
        agent.configure_exploration(cfg.training_rounds, cfg.epsilon_final)
        agent.set_training(True)

    _warn_on_market_mismatch(environment, by_id[agent_ids[0]])

    # --- Prepare environment ---------------------------------------------
    original_max_rounds = environment.max_rounds
    environment.max_rounds = cfg.training_rounds + 1
    environment.reset()

    rng = random.Random(cfg.seed)
    n_actions = by_id[agent_ids[0]].n_actions
    profile: Tuple[int, ...] = tuple(
        rng.randrange(n_actions) for _ in agent_ids
    )
    states: Dict[str, Tuple[int, ...]] = {}
    for aid in agent_ids:
        states[aid] = by_id[aid].push_profile(profile)

    # --- Training loop ----------------------------------------------------
    start = time.time()
    policy_snapshot: Optional[Tuple[Dict[State, int], ...]] = None
    stable_rounds = 0
    policy_churn = 1.0
    bin_prices: List[float] = []
    learning_curve: List[Dict[str, float]] = []
    tail_prices: List[float] = []
    tail_size = max(1, min(cfg.training_rounds, 1_000))
    prices: Dict[str, int] = {}
    rounds_done = 0

    for t in range(cfg.training_rounds):
        actions: Dict[str, int] = {}
        joint_action: Dict[str, Any] = {}
        for aid in agent_ids:
            agent = by_id[aid]
            action = agent.select_action(states[aid], explore=True)
            actions[aid] = action
            joint_action[aid] = {
                "price": agent.price_grid[action],
                "speech": "",
            }

        _obs, rewards, _done, info = environment.step(joint_action)
        prices = info["prices"]

        for aid in agent_ids:
            agent = by_id[aid]
            next_state = agent.observe_prices(prices)
            agent.update(
                states[aid], actions[aid], float(rewards.get(aid, 0.0)), next_state
            )
            states[aid] = next_state

        rounds_done = t + 1

        # Keep memory flat over hundreds of thousands of rounds.
        environment.trim_history(keep=1)

        market_price = float(info["market_price"])
        bin_prices.append(market_price)
        tail_prices.append(market_price)
        if len(tail_prices) > tail_size:
            del tail_prices[:-tail_size]

        if cfg.price_log_bin and rounds_done % cfg.price_log_bin == 0:
            learning_curve.append(
                {
                    "round": rounds_done,
                    "mean_market_price": sum(bin_prices) / len(bin_prices),
                    "epsilon": by_id[agent_ids[0]].epsilon,
                }
            )
            bin_prices = []

        # --- Convergence check -------------------------------------------
        if cfg.check_interval and rounds_done % cfg.check_interval == 0:
            snapshot = tuple(by_id[aid].greedy_policy() for aid in agent_ids)
            if policy_snapshot is None:
                policy_churn = 1.0
                stable_rounds = 0
            else:
                changed, total = _policy_diff(policy_snapshot, snapshot)
                policy_churn = changed / total if total else 0.0
                stable_rounds = (
                    stable_rounds + cfg.check_interval if changed == 0 else 0
                )
            policy_snapshot = snapshot

            if stable_rounds >= cfg.convergence_window and cfg.stop_on_convergence:
                if cfg.verbose:
                    print(
                        f"    converged after {rounds_done:,} rounds "
                        f"(stable for {stable_rounds:,})"
                    )
                break

        if cfg.verbose and cfg.log_interval and rounds_done % cfg.log_interval == 0:
            eps = by_id[agent_ids[0]].epsilon
            recent = learning_curve[-1]["mean_market_price"] if learning_curve else market_price
            print(
                f"    round {rounds_done:>8,}/{cfg.training_rounds:,}  "
                f"eps={eps:.4f}  mean_price={recent:.2f}  "
                f"churn={policy_churn:.4f}  stable={stable_rounds:,}"
            )

    wall_time = time.time() - start

    converged = stable_rounds >= cfg.convergence_window

    if bin_prices and cfg.price_log_bin:
        learning_curve.append(
            {
                "round": rounds_done,
                "mean_market_price": sum(bin_prices) / len(bin_prices),
                "epsilon": by_id[agent_ids[0]].epsilon,
            }
        )

    price_drift = _price_drift(
        learning_curve, cfg.convergence_window, cfg.price_log_bin
    )
    price_stable = price_drift is not None and price_drift <= cfg.price_tolerance

    # --- Freeze policies and hand the state over to evaluation ------------
    final_profile = (
        by_id[agent_ids[0]].profile_from_prices(prices) if prices else profile
    )
    per_agent: Dict[str, Any] = {}
    for aid in agent_ids:
        agent = by_id[aid]
        per_agent[aid] = agent.policy_stats()
        agent.set_eval_profile(final_profile)
        agent.set_training(False)

    result = QTrainingResult(
        converged=converged,
        price_stable=price_stable,
        rounds_trained=rounds_done,
        stable_rounds=stable_rounds,
        price_drift=price_drift,
        final_policy_churn=policy_churn,
        final_epsilon=per_agent[agent_ids[0]]["epsilon"],
        final_prices=dict(prices),
        final_profile=final_profile,
        learning_curve=learning_curve,
        last_window_mean_price=(
            sum(tail_prices) / len(tail_prices) if tail_prices else 0.0
        ),
        wall_time_sec=wall_time,
        per_agent=per_agent,
    )

    # --- Restore the environment for the evaluation episode ---------------
    environment.max_rounds = original_max_rounds
    environment.reset()

    return result


def _price_drift(
    learning_curve: List[Dict[str, float]],
    window: int,
    bin_size: int,
) -> Optional[float]:
    """|mean price over the last *window* rounds − the window before it|.

    Computed from the binned learning curve, so it costs nothing extra.
    Returns ``None`` when training was too short to fill two windows.
    """
    if not bin_size or not learning_curve:
        return None
    n_bins = max(1, window // bin_size)
    if len(learning_curve) < 2 * n_bins:
        return None
    recent = learning_curve[-n_bins:]
    prior = learning_curve[-2 * n_bins:-n_bins]
    mean_recent = sum(b["mean_market_price"] for b in recent) / len(recent)
    mean_prior = sum(b["mean_market_price"] for b in prior) / len(prior)
    return abs(mean_recent - mean_prior)


def _policy_diff(
    previous: Tuple[Dict[State, int], ...],
    current: Tuple[Dict[State, int], ...],
) -> Tuple[int, int]:
    """Compare two greedy-policy snapshots.

    Returns ``(changed, total)`` summed over all agents.
    """
    changed = total = 0
    for prev_policy, cur_policy in zip(previous, current):
        for state, action in cur_policy.items():
            total += 1
            if prev_policy.get(state) != action:
                changed += 1
    return changed, total


def _warn_on_market_mismatch(
    environment: HomogeneousGoodsMarket, agent: QLearningSellerAgent
) -> None:
    """Warn if the agent's payoff assumptions differ from the environment.

    Only the Q-table initialisation uses these constants, but a mismatch
    almost always means the config is wrong, so it is worth surfacing.
    """
    mismatches = []
    if float(getattr(environment, "marginal_cost", agent.marginal_cost)) != agent.marginal_cost:
        mismatches.append(
            f"marginal_cost env={environment.marginal_cost} agent={agent.marginal_cost}"
        )
    if int(getattr(environment, "num_customers", agent.num_customers)) != agent.num_customers:
        mismatches.append(
            f"num_customers env={environment.num_customers} agent={agent.num_customers}"
        )
    price_range = getattr(environment, "price_range", None)
    if price_range and not (
        price_range[0] <= agent.price_grid[0]
        and agent.price_grid[-1] <= price_range[1]
    ):
        mismatches.append(
            f"price_grid [{agent.price_grid[0]}, {agent.price_grid[-1]}] "
            f"outside env price_range {list(price_range)}"
        )
    if mismatches:
        print("  ⚠ Q-learning / environment parameter mismatch: " + "; ".join(mismatches))
