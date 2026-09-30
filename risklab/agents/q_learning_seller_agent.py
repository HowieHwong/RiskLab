"""
Q-Learning Seller Agent — the non-LLM baseline for the Risk 1.1 (tacit
collusion) supplementary experiments.

Motivation
----------
Reviewer 1 asks whether supra-competitive pricing is specific to LLM agents,
given that classical algorithmic pricing agents already collude in repeated
markets (Calvano et al., *Artificial Intelligence, Algorithmic Pricing, and
Collusion*, AER 2020).  This agent answers that question **inside the same
market environment** used by the LLM experiments: identical sellers, identical
marginal cost, identical Bertrand-style allocation rule and identical risk
detector.  Only the decision rule changes.

Design (following Calvano et al., adapted to our market)
--------------------------------------------------------
- **Action space** — a discrete price grid, ``{10, 11, …, 20}`` by default.
- **State space** — the price profile of the previous ``memory`` round(s)
  (Calvano's memory-1 state; 11**3 = 1331 states for three sellers).
- **Reward** — the seller's realised per-round profit, taken straight from the
  environment (no reward shaping, no collusion prior).
- **Update** — tabular Q-learning::

      Q(s, a) ← (1 - α) · Q(s, a) + α · [ r + γ · max_a' Q(s', a') ]

- **Exploration** — ε-greedy with exponentially decaying
  ``ε_t = exp(-β · t)``; β is normally derived from the training budget so that
  exploration has effectively vanished by the end of training.
- **Initialisation** — ``Q_0(s, a) = E[π(a)] / (1 - γ)``, the discounted payoff
  of playing ``a`` forever against uniformly random opponents (Calvano's
  initialisation).  This is deliberately neutral: nothing rewards coordination.

The agent never exchanges natural language and is never told about
cooperation, collusion or price maintenance.

Usage
-----
Training is driven by :mod:`risklab.experiments.qlearning_trainer`; evaluation
runs through the ordinary :class:`~risklab.experiments.runner.ExperimentRunner`
loop, because :meth:`act` emits the same ``[Price]`` action format that the
market environment already understands.
"""

from __future__ import annotations

import math
import random
from collections import deque
from itertools import product
from typing import Any, Dict, List, Optional, Sequence, Tuple

from risklab.agents.base import Agent, AgentConfig
from risklab.agents.registry import AgentRegistry

State = Tuple[int, ...]


@AgentRegistry.register("q_learning_seller")
class QLearningSellerAgent(Agent):
    """Tabular Q-learning seller for the homogeneous-goods market.

    Parameters (via ``AgentConfig.parameters``)
    -------------------------------------------
    price_grid : list[int], optional
        Explicit discrete price grid.  If omitted it is built from
        ``price_min`` / ``price_max`` / ``price_step`` (default 10…20 step 1).
    marginal_cost : float
        Per-unit cost, must match the environment (default 10).
    num_customers : int
        Customers per round, must match the environment (default 99).
        Only used to initialise the Q-table.
    learning_rate : float
        α (default 0.1).
    discount_factor : float
        γ (default 0.95).
    memory : int
        Number of past rounds in the state (default 1, i.e. Calvano's k=1).
    epsilon_decay : float, optional
        β in ``ε_t = exp(-β t)``.  If omitted, the trainer derives it from the
        training budget so that ``ε`` ends at ``epsilon_final``.
    epsilon_final : float
        Target ε at the end of training when β is derived (default 1e-3).
    epsilon_floor : float
        Hard lower bound on ε during training (default 0.0).
    q_init : {"random_payoff", "zeros"} | float
        Q-table initialisation (default ``"random_payoff"``).
    eval_init_state : {"final", "random", "marginal_cost"} | list[int]
        Which price profile the frozen policy starts from at evaluation time
        (default ``"final"``: the profile reached at the end of training).
    seed : int, optional
        RNG seed for exploration and tie-breaking.
    peers : list[str], optional
        Canonical seller ordering used to build state tuples.  Normally set by
        the trainer via :meth:`set_peers`.
    """

    def __init__(
        self,
        config: AgentConfig,
        llm_config: Any = None,
        llm_client: Any = None,
        task_prompt: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        # ``llm_config`` / ``llm_client`` / ``task_prompt`` are accepted (and
        # ignored) so that this agent can be built by the standard
        # ``build_agents_from_config`` factory alongside LLM agents.
        super().__init__(config)
        p: Dict[str, Any] = dict(config.parameters or {})

        # --- Action space ---------------------------------------------------
        if p.get("price_grid"):
            self.price_grid: List[int] = [int(x) for x in p["price_grid"]]
        else:
            lo = int(p.get("price_min", 10))
            hi = int(p.get("price_max", 20))
            step = int(p.get("price_step", 1))
            self.price_grid = list(range(lo, hi + 1, step))
        if len(self.price_grid) < 2:
            raise ValueError("price_grid must contain at least two prices.")
        self.n_actions: int = len(self.price_grid)
        self._price_to_idx: Dict[int, int] = {
            pr: i for i, pr in enumerate(self.price_grid)
        }

        # --- Market constants (must mirror the environment) -----------------
        self.marginal_cost: float = float(p.get("marginal_cost", 10))
        self.num_customers: int = int(p.get("num_customers", 99))

        # --- Learning hyper-parameters --------------------------------------
        self.alpha: float = float(p.get("learning_rate", 0.1))
        self.gamma: float = float(p.get("discount_factor", 0.95))
        self.memory_length: int = max(1, int(p.get("memory", 1)))
        self.epsilon_final: float = float(p.get("epsilon_final", 1e-3))
        self.epsilon_floor: float = float(p.get("epsilon_floor", 0.0))
        self._beta_explicit: bool = p.get("epsilon_decay") is not None
        self._beta: float = float(
            p["epsilon_decay"] if self._beta_explicit
            else -math.log(self.epsilon_final) / 300_000.0
        )
        self.q_init: Any = p.get("q_init", "random_payoff")
        self.eval_init_state: Any = p.get("eval_init_state", "final")

        # --- RNG -------------------------------------------------------------
        self.seed: Optional[int] = p.get("seed")
        self._rng = random.Random(self.seed)

        # --- Tables & runtime state -----------------------------------------
        self._q: Dict[State, List[float]] = {}
        self._q_defaults: Optional[List[float]] = None
        self._peer_order: Optional[List[str]] = (
            sorted(p["peers"]) if p.get("peers") else None
        )
        self._recent: deque = deque(maxlen=self.memory_length)
        self._eval_profile: Optional[Tuple[int, ...]] = None
        self._pending: Optional[Tuple[State, int]] = None

        self.training: bool = True
        self.steps: int = 0          # exploration clock (Q updates)
        self.update_count: int = 0

    # ------------------------------------------------------------------
    # Configuration hooks (used by the trainer)
    # ------------------------------------------------------------------

    def set_peers(self, agent_ids: Sequence[str]) -> None:
        """Fix the canonical seller ordering used to build state tuples."""
        self._peer_order = sorted(agent_ids)

    def configure_exploration(
        self, training_rounds: int, epsilon_final: Optional[float] = None
    ) -> float:
        """Derive β from the training budget unless it was pinned in YAML.

        Returns the β actually in use.
        """
        if not self._beta_explicit and training_rounds > 0:
            eps_final = (
                self.epsilon_final if epsilon_final is None else epsilon_final
            )
            self._beta = -math.log(max(eps_final, 1e-12)) / float(training_rounds)
        return self._beta

    def seed_rng(self, seed: Optional[int]) -> None:
        """Reseed exploration / tie-breaking (one seed per training run)."""
        self.seed = seed
        self._rng = random.Random(seed)

    def set_training(self, training: bool) -> None:
        """Switch between learning/exploring and frozen greedy play."""
        self.training = training

    @property
    def beta(self) -> float:
        """Exploration decay rate β."""
        return self._beta

    @property
    def epsilon(self) -> float:
        """Current exploration rate ``ε_t = max(floor, exp(-β t))``."""
        if not self.training:
            return 0.0
        return max(self.epsilon_floor, math.exp(-self._beta * self.steps))

    # ------------------------------------------------------------------
    # State handling
    # ------------------------------------------------------------------

    def price_index(self, price: float) -> int:
        """Map a price onto the grid (nearest grid point if off-grid).

        Off-grid prices only occur when the environment injects an exogenous
        price (e.g. the forced price-cut probe), so we snap rather than fail.
        """
        ip = int(round(float(price)))
        idx = self._price_to_idx.get(ip)
        if idx is not None:
            return idx
        return min(
            range(self.n_actions),
            key=lambda i: abs(self.price_grid[i] - float(price)),
        )

    def profile_from_prices(self, prices: Dict[str, Any]) -> Tuple[int, ...]:
        """Convert ``{agent_id: price}`` into a canonical index profile."""
        if self._peer_order is None:
            self._peer_order = sorted(prices.keys())
        return tuple(
            self.price_index(prices[aid])
            for aid in self._peer_order
            if aid in prices
        )

    def observe_prices(self, prices: Dict[str, Any]) -> State:
        """Push a realised price profile into the state window."""
        self._recent.append(self.profile_from_prices(prices))
        return self.current_state()

    def push_profile(self, profile: Tuple[int, ...]) -> State:
        """Push an already-indexed price profile into the state window."""
        self._recent.append(tuple(profile))
        return self.current_state()

    def current_state(self) -> State:
        """Flatten the memory window into a hashable state tuple."""
        window = list(self._recent)
        if not window:
            window = [self._default_profile()]
        while len(window) < self.memory_length:
            window.insert(0, window[0])
        return tuple(idx for profile in window for idx in profile)

    def _default_profile(self) -> Tuple[int, ...]:
        n = len(self._peer_order) if self._peer_order else 1
        return tuple([0] * n)  # everyone at the lowest grid price (= cost)

    # ------------------------------------------------------------------
    # Q-table
    # ------------------------------------------------------------------

    def _initial_q_values(self) -> List[float]:
        """Q-table initialisation values, computed once and reused."""
        if self._q_defaults is not None:
            return self._q_defaults

        if isinstance(self.q_init, (int, float)):
            self._q_defaults = [float(self.q_init)] * self.n_actions
        elif self.q_init == "zeros":
            self._q_defaults = [0.0] * self.n_actions
        elif self.q_init == "random_payoff":
            expected = self._expected_payoff_vs_uniform()
            denom = max(1e-9, 1.0 - self.gamma)
            self._q_defaults = [v / denom for v in expected]
        else:
            raise ValueError(f"Unknown q_init: {self.q_init!r}")
        return self._q_defaults

    def _expected_payoff_vs_uniform(self) -> List[float]:
        """E[π(a)] when every opponent prices uniformly at random.

        Uses exact enumeration when the opponent joint space is small and a
        Monte-Carlo estimate otherwise.  The payoff rule replicates the
        environment: strictly lowest price takes the market, ties split it.
        """
        n_sellers = len(self._peer_order) if self._peer_order else 3
        n_opp = max(0, n_sellers - 1)
        grid = self.price_grid

        def payoff(own: int, others: Sequence[int]) -> float:
            lowest = min([own, *others]) if others else own
            if own > lowest:
                return 0.0
            n_winners = 1 + sum(1 for o in others if o == lowest)
            customers = self.num_customers // n_winners
            return (own - self.marginal_cost) * customers

        combos = len(grid) ** n_opp
        out: List[float] = []
        if combos <= 200_000:
            for own in grid:
                total = 0.0
                for others in product(grid, repeat=n_opp):
                    total += payoff(own, others)
                out.append(total / combos)
        else:  # pragma: no cover - only for very large grids
            samples = 20_000
            rng = random.Random(0)
            for own in grid:
                total = 0.0
                for _ in range(samples):
                    others = [rng.choice(grid) for _ in range(n_opp)]
                    total += payoff(own, others)
                out.append(total / samples)
        return out

    def q_row(self, state: State) -> List[float]:
        """Return (creating if needed) the Q-values for *state*."""
        row = self._q.get(state)
        if row is None:
            row = list(self._initial_q_values())
            self._q[state] = row
        return row

    # ------------------------------------------------------------------
    # Policy
    # ------------------------------------------------------------------

    def select_action(
        self, state: State, explore: Optional[bool] = None
    ) -> int:
        """ε-greedy action selection with random tie-breaking."""
        do_explore = self.training if explore is None else explore
        if do_explore and self._rng.random() < self.epsilon:
            return self._rng.randrange(self.n_actions)
        row = self.q_row(state)
        best = max(row)
        best_actions = [i for i, v in enumerate(row) if v == best]
        if len(best_actions) == 1:
            return best_actions[0]
        return self._rng.choice(best_actions)

    def select_price(self, state: State, explore: Optional[bool] = None) -> int:
        """Convenience wrapper returning a price rather than an action index."""
        return self.price_grid[self.select_action(state, explore=explore)]

    def update(
        self, state: State, action: int, reward: float, next_state: State
    ) -> None:
        """One tabular Q-learning update."""
        row = self.q_row(state)
        next_row = self.q_row(next_state)
        target = reward + self.gamma * max(next_row)
        row[action] = (1.0 - self.alpha) * row[action] + self.alpha * target
        self.steps += 1
        self.update_count += 1

    def greedy_policy(self) -> Dict[State, int]:
        """Argmax action per visited state (used for convergence checks)."""
        policy: Dict[State, int] = {}
        for state, row in self._q.items():
            best = max(row)
            policy[state] = row.index(best)
        return policy

    def greedy_price_policy(self) -> Dict[str, int]:
        """Human-readable greedy policy: ``{state_string: price}``."""
        return {
            ",".join(str(i) for i in state): self.price_grid[a]
            for state, a in self.greedy_policy().items()
        }

    # ------------------------------------------------------------------
    # Agent interface
    # ------------------------------------------------------------------

    def observe(self, observation: Dict[str, Any]) -> None:
        """No-op — state is derived inside :meth:`act`."""
        pass

    def act(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """Pick a price for the current round from the frozen (or learning)
        policy, using the previous round's realised prices as the state.

        The returned dict carries a structured ``price`` field, which the
        market environment consumes directly, plus a ``[Price]``-formatted
        message so that trajectories stay readable and parseable by the same
        tooling used for LLM runs.
        """
        previous = observation.get("previous_results")
        if isinstance(previous, dict) and previous.get("prices"):
            self.observe_prices(previous["prices"])

        state = self.current_state()
        action = self.select_action(state, explore=self.training)
        price = self.price_grid[action]
        self._pending = (state, action)

        return {
            "message": f"[Price]\n{price}",
            "action": price,
            "price": price,
            "speech": "",
            "policy": "q_learning",
            "state": ",".join(str(i) for i in state),
            "epsilon": self.epsilon,
        }

    def learn_from_feedback(
        self, reward: float, next_prices: Dict[str, Any]
    ) -> None:
        """Apply a Q-update for the action returned by the last :meth:`act`.

        Only used if one wants the agent to keep learning while driven by the
        standard experiment runner; the offline trainer updates directly.
        """
        if self._pending is None or not self.training:
            return
        state, action = self._pending
        next_state = self.observe_prices(next_prices)
        self.update(state, action, reward, next_state)
        self._pending = None

    def reset(self) -> None:
        """Reset per-episode state.  The Q-table is **kept** — a trained
        policy must survive across evaluation episodes."""
        super().reset()
        self._pending = None
        self._recent.clear()
        profile = self._resolve_eval_profile()
        if profile is not None:
            for _ in range(self.memory_length):
                self._recent.append(profile)

    def reset_policy(self) -> None:
        """Wipe the learned Q-table and the exploration clock."""
        self._q.clear()
        self.steps = 0
        self.update_count = 0
        self._recent.clear()
        self._pending = None

    # ------------------------------------------------------------------
    # Evaluation start state
    # ------------------------------------------------------------------

    def set_eval_profile(self, profile: Sequence[int]) -> None:
        """Record the price profile that evaluation episodes start from."""
        self._eval_profile = tuple(int(i) for i in profile)

    def _resolve_eval_profile(self) -> Optional[Tuple[int, ...]]:
        mode = self.eval_init_state
        if isinstance(mode, (list, tuple)):
            return tuple(self.price_index(p) for p in mode)
        if mode == "marginal_cost":
            return self._default_profile()
        if mode == "random":
            n = len(self._peer_order) if self._peer_order else 1
            return tuple(self._rng.randrange(self.n_actions) for _ in range(n))
        # "final" (default): the profile reached at the end of training
        return self._eval_profile

    # ------------------------------------------------------------------

    def policy_stats(self) -> Dict[str, Any]:
        """Small summary of the learned policy (for result files)."""
        prices = [self.price_grid[a] for a in self.greedy_policy().values()]
        return {
            "visited_states": len(self._q),
            "q_updates": self.update_count,
            "epsilon": self.epsilon,
            "beta": self._beta,
            "greedy_price_mean": (
                sum(prices) / len(prices) if prices else None
            ),
            "greedy_price_min": min(prices) if prices else None,
            "greedy_price_max": max(prices) if prices else None,
        }

    def __repr__(self) -> str:
        return (
            f"QLearningSellerAgent(id={self.agent_id!r}, "
            f"grid=[{self.price_grid[0]}..{self.price_grid[-1]}], "
            f"states={len(self._q)}, training={self.training})"
        )
