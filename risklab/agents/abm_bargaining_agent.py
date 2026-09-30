"""
Rule-based (non-LLM) bargaining agents — the ABM baseline for Risk 1.5.

Asks: *is bargaining exploitation under information asymmetry already
produced by classical algorithmic agents?*  These two agents play the
identical :class:`~risklab.environments.competitive.bilateral_bargaining.BilateralBargaining`
environment as the LLM conditions, through the identical runner; only the
decision rule changes.  They exchange numbers, never language.

Architecture
------------
Both agents follow the **BOA** decomposition that the automated-negotiation
literature settled on (Baarslag et al., *Decoupling negotiating agents to
explore the space of negotiation strategies*), which is also the structure
every ANAC entrant is built from:

    Bidding strategy
        A weighted combination of the two classical tactic families of
        Faratin, Sierra & Jennings (1998): a **time-dependent** concession
        curve and a **behaviour-dependent** (relative tit-for-tat) term that
        mirrors the opponent's own concessions.  The combined bid is then
        forced through a **monotone-concession ratchet**: an agent may never
        move a price against its opponent.  Without that constraint a belief
        that updates faster than the concession curve makes the seller's ask
        *rise* mid-negotiation, which is not bargaining.
    Opponent model
        Seller only (the buyer's is left for future work).  Every exchange
        brackets the buyer's willingness to pay between the counter it just
        made (a lower bound) and the ask it just refused (an upper bound);
        the estimate is an EWMA of points inside that bracket.  This is the
        seller-side learning of Moulet & Rouchier (2008), and because the
        bracket's ceiling is the *refused* ask, the belief can only ever
        accelerate concession — never reverse it.
    Acceptance condition
        ``AC_next ∨ AC_time`` (Baarslag et al., *Acceptance conditions in
        automated negotiation*): accept when the standing offer is already at
        least as good as the bid you were about to make, or when the deadline
        leaves no better option than a deal above your reservation.

Every parameter below is **pre-registered** — fixed before any LLM result was
seen — and none of them encodes the answer:

    * the seller's prior over the buyer's WTP is anchored on its own cost
      (``wtp_prior_multiplier * c``), never on the buyer's budget ``m``, which
      it must not know;
    * the seller is told only what the LLM seller is told — the buyer is
      urgent (a finite deadline) and has no outside option (no switch action);
    * the only quantity fitted at all is the seller's concession exponent
      ``beta``, and it is fitted by maximin self-play against a *pool* of
      rule-based buyers (see ``risklab.experiments.abm_bargaining_trainer``),
      never against LLM transcripts and never against the single buyer it
      will face.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from risklab.agents.base import Agent, AgentConfig
from risklab.agents.registry import AgentRegistry


def _concession(start: float, end: float, t: float, exponent: float) -> float:
    """Time-dependent concession from *start* to *end* over ``t`` ∈ [0, 1].

    ``exponent < 1`` → Boulware (concede late); ``> 1`` → Conceder;
    ``= 1`` → linear.
    """
    t = min(max(t, 0.0), 1.0)
    return start + (end - start) * (t ** (1.0 / max(exponent, 1e-6)))


def _relative_tft(own_prev: float, opp_prev: float, opp_now: float) -> Optional[float]:
    """Faratin et al.'s relative tit-for-tat with δ = 1.

    Mirrors the opponent's *proportional* concession onto one's own last
    price.  For a seller ``opp`` is the buyer's counter: if the buyer raised
    its counter by 4 %, the ratio is < 1 and the ask drops by ~4 %.  For a
    buyer ``opp`` is the seller's ask and the ratio is > 1 when the seller
    concedes, so the counter rises.  ``None`` when the ratio is undefined.
    """
    if opp_now is None or opp_prev is None or opp_now <= 0:
        return None
    return own_prev * (opp_prev / opp_now)


class _MonotoneBargainer(Agent):
    """Shared BOA plumbing: tactic mixing, the ratchet, and the AC pair."""

    #: ``+1`` for a seller (higher price is better), ``-1`` for a buyer.
    _SIGN: int = 1

    def __init__(self, config: AgentConfig) -> None:
        super().__init__(config)
        p: Dict[str, Any] = dict(config.parameters or {})
        # Weight on the time-dependent tactic; the remainder goes to
        # tit-for-tat.  0.5 = the balanced combination Faratin et al. report.
        self.tft_weight = float(p.get("tft_weight", 0.5))
        self.seed: Optional[int] = p.get("seed")
        self._rng = random.Random(self.seed)
        self._own_prev: Optional[float] = None
        self._opp_hist: List[float] = []
        #: Bids the ratchet had to clamp.  Zero means the raw tactic was
        #: already monotone; a large count means the mix is fighting itself.
        self.ratchet_clamps: int = 0

    # -- to be provided by the two roles -------------------------------

    def _reservation_price(self, observation: Dict[str, Any]) -> float:
        """The worst price this agent would still sign."""
        raise NotImplementedError

    def _time_bid(self, t: float, observation: Dict[str, Any]) -> float:
        raise NotImplementedError

    # -- shared machinery ----------------------------------------------

    @staticmethod
    def _t(observation: Dict[str, Any]) -> float:
        rnd = int(observation.get("round", 1))
        total = int(observation.get("total_rounds", 10))
        return (rnd - 1) / max(total - 1, 1)

    @staticmethod
    def _is_deadline(observation: Dict[str, Any]) -> bool:
        return int(observation.get("round", 1)) >= int(
            observation.get("total_rounds", 10)
        )

    def _ratchet(self, bid: float) -> float:
        """Item 1: never move a price against the opponent (monotone concession).

        A bid worse for the opponent than one's own previous bid is clamped
        back to that previous bid, so the concession path is monotone by
        construction whatever the tactic mix or the opponent model does.
        """
        if self._own_prev is None:
            return bid
        if self._SIGN * (bid - self._own_prev) > 1e-9:
            self.ratchet_clamps += 1
            return self._own_prev
        return bid

    def _bid(self, t: float, observation: Dict[str, Any]) -> float:
        """Combined time-dependent + tit-for-tat bid, ratcheted and floored."""
        bid = self._time_bid(t, observation)
        if self.tft_weight > 0 and self._own_prev is not None and len(self._opp_hist) >= 2:
            mirrored = _relative_tft(
                self._own_prev, self._opp_hist[-2], self._opp_hist[-1]
            )
            if mirrored is not None:
                w = min(max(self.tft_weight, 0.0), 1.0)
                bid = (1.0 - w) * bid + w * mirrored
        return self._ratchet(self._clamp(bid, observation))

    def _clamp(self, bid: float, observation: Dict[str, Any]) -> float:
        raise NotImplementedError

    def _accepts(
        self, standing: Optional[float], observation: Dict[str, Any], next_bid: float
    ) -> bool:
        """Item 5: ``AC_next ∨ AC_time``.

        ``AC_next(1, 0)`` — the offer on the table is already at least as good
        as the bid about to be made, so holding out cannot pay.
        ``AC_time`` — the deadline is here and a deal above one's reservation
        beats walking away with nothing.
        """
        if standing is None:
            return False
        if self._SIGN * (standing - next_bid) >= -1e-9:      # AC_next
            return True
        if self._is_deadline(observation):                    # AC_time
            reservation = self._reservation_price(observation)
            return self._SIGN * (standing - reservation) >= -1e-9
        return False

    def seed_rng(self, seed: Optional[int]) -> None:
        """Reseed the per-episode draw (one seed per run)."""
        self.seed = seed
        self._rng = random.Random(seed)

    def reset(self) -> None:
        super().reset()
        self._rng = random.Random(self.seed)
        self._own_prev = None
        self._opp_hist = []
        self.ratchet_clamps = 0


@AgentRegistry.register("abm_supplier")
class ABMSupplierAgent(_MonotoneBargainer):
    """Seller: Boulware ask path, bracket-learned WTP, ``AC_next ∨ AC_time``.

    Parameters (via ``AgentConfig.parameters``)
    -------------------------------------------
    production_cost : float
        Own unit cost ``c`` (default 40).
    min_margin_ratio : float
        Reservation price is ``c * (1 + min_margin_ratio)`` (default 0.1).
    wtp_prior_multiplier : float
        Prior estimate of the buyer's WTP as a multiple of ``c`` (default 2.0),
        which is also the opening ask.  Cost-anchored on purpose: the seller
        must not know ``m``.
    opening_anchor : float, optional
        Absolute opening ask in credits, overriding ``c *
        wtp_prior_multiplier``.  ``None`` (default) keeps the anchor tied to
        the cost prior.  Setting it is what **decouples the anchor from the
        reservation**: with the default rule ``opening_ask = max(2c, R)``, a
        learned ``R > 2c`` collapses the concession interval to a point and
        the agent degenerates into a posted price.
    beta : float
        Concession exponent; < 1 concedes late (default 0.5, overwritten by
        the calibration phase).
    tft_weight : float
        Weight on the tit-for-tat term against the time-dependent term
        (default 0.5).
    belief_alpha : float
        EWMA weight on new evidence about the buyer's WTP (default 0.3).
    wtp_bracket_share : float
        Where inside the ``[counter, refused ask]`` bracket the new evidence
        point sits (default 0.5 = the midpoint).
    """

    _SIGN = 1

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
        # LLM plumbing accepted and ignored so the standard factory can build
        # this agent alongside LLM agents.
        super().__init__(config)
        p: Dict[str, Any] = dict(config.parameters or {})
        self.production_cost = float(p.get("production_cost", 40))
        self.min_margin_ratio = float(p.get("min_margin_ratio", 0.1))
        self.wtp_prior_multiplier = float(p.get("wtp_prior_multiplier", 2.0))
        anchor = p.get("opening_anchor")
        self.opening_anchor: Optional[float] = (
            None if anchor is None else float(anchor)
        )
        self.beta = float(p.get("beta", 0.5))
        self.belief_alpha = float(p.get("belief_alpha", 0.3))
        self.wtp_bracket_share = float(p.get("wtp_bracket_share", 0.5))
        self._wtp_estimate = self.opening_ask

    @property
    def reservation(self) -> float:
        """Lowest price the seller will settle for."""
        return self.production_cost * (1.0 + self.min_margin_ratio)

    @property
    def opening_ask(self) -> float:
        """First-round ask — the prior over the buyer's WTP, anchored on ``c``.

        Never below the reservation: an agent cannot open under the price it
        would walk away at.  That floor is why the cost-anchored default
        degenerates once the learned reservation passes ``2c``.
        """
        anchor = (
            self.production_cost * self.wtp_prior_multiplier
            if self.opening_anchor is None
            else self.opening_anchor
        )
        return max(anchor, self.reservation)

    @property
    def wtp_estimate(self) -> float:
        """Current belief about the buyer's willingness to pay."""
        return self._wtp_estimate

    def _reservation_price(self, observation: Dict[str, Any]) -> float:
        return self.reservation

    def _time_bid(self, t: float, observation: Dict[str, Any]) -> float:
        return _concession(self.opening_ask, self.reservation, t, self.beta)

    def _clamp(self, bid: float, observation: Dict[str, Any]) -> float:
        # The opponent model enters here and *only* here: never ask more than
        # the buyer is believed able to pay.  Because the belief is capped by
        # the ask the buyer just refused, this can only speed concession up.
        return min(max(bid, self.reservation), self._wtp_estimate, self.opening_ask)

    def _update_belief(self, counter: float) -> None:
        """Bracket the buyer's WTP between its counter and the refused ask."""
        low = float(counter)
        high = self._own_prev if self._own_prev is not None else self.opening_ask
        if high < low:                      # crossed: the counter beats the ask
            low, high = high, low
        evidence = low + self.wtp_bracket_share * (high - low)
        self._wtp_estimate = (
            (1.0 - self.belief_alpha) * self._wtp_estimate
            + self.belief_alpha * evidence
        )
        # Respect the observed bracket, then never fall below the reservation.
        self._wtp_estimate = min(max(self._wtp_estimate, low), high)
        self._wtp_estimate = max(self._wtp_estimate, self.reservation)

    def act(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        counter = observation.get("buyer_counter")
        t = self._t(observation)
        total = int(observation.get("total_rounds", 10))
        rnd = int(observation.get("round", 1))

        if counter is not None:
            self._opp_hist.append(float(counter))
            self._update_belief(float(counter))

        ask = self._bid(t, observation)
        # The bid we could still make one exchange from now — the benchmark
        # AC_next compares the standing counter against.
        t_next = min(rnd, max(total - 1, 1)) / max(total - 1, 1)
        next_ask = max(
            min(self._time_bid(t_next, observation), self._wtp_estimate, ask),
            self.reservation,
        )

        if self._accepts(
            None if counter is None else float(counter), observation, next_ask
        ):
            return {
                "message": "",
                "action": {"type": "ACCEPT", "price": float(counter)},
            }

        price = round(ask, 2)
        self._own_prev = price
        return {"message": "", "action": {"type": "OFFER", "price": price}}

    def reset(self) -> None:
        super().reset()
        self._wtp_estimate = self.opening_ask

    def __repr__(self) -> str:
        return (
            f"ABMSupplierAgent(id={self.agent_id!r}, beta={self.beta:g}, "
            f"open={self.opening_ask:.0f}, "
            f"tft={self.tft_weight:g}, wtp_hat={self._wtp_estimate:.1f})"
        )


@AgentRegistry.register("abm_purchaser")
class ABMPurchaserAgent(_MonotoneBargainer):
    """Buyer: deadline-driven counter path, tit-for-tat, optional backup.

    Parameters (via ``AgentConfig.parameters``)
    -------------------------------------------
    budget_cap : float
        Hard ceiling ``m`` (default 120).
    initial_share : float
        First-round counter as a fraction of ``m`` (default 0.5).
    gamma : float
        Concession exponent toward the deadline (default 1.0 = linear).
    tft_weight : float
        Weight on the tit-for-tat term (default 0.5).  With the ratchet in
        place this is what stops the buyer conceding unilaterally against a
        seller that never moves.
    noise_sd : float
        Gaussian jitter on the concession path, in credits (default 3.0).
        Drawn **once per episode** as a level shift, not per round, so it
        cannot manufacture a monotonicity violation for the ratchet to eat.
    backup_price, backup_success_prob : float
        The outside option, when the environment grants one.  Its certainty
        equivalent ``q * (m - p_backup)`` caps what the buyer will pay.
    walkaway_rule : str
        When the buyer may leave for its backup.  ``"deadline"`` (default) is
        the expected-utility solution: the backup stays available until the
        last exchange and waiting costs nothing, so leaving early is strictly
        dominated and the buyer always waits.  ``"early"`` adds a behavioural
        walk-away — the buyer leaves the moment the standing ask is outside
        the set of prices it would ever accept, without waiting to see whether
        the seller concedes.  This is the buyer's *action set* in Experiment
        II, where ``SWITCH_TO_BACKUP`` is legal at every round and the
        purchaser prompt restates the backup each turn; ``"deadline"`` is a
        policy restriction, not an environment one.
    insult_ratio : float
        Under ``walkaway_rule="early"``, leave when the standing ask exceeds
        ``insult_ratio * ceiling`` (default 1.0 — the ceiling itself, the most
        the buyer would ever pay).  Larger values are more patient;
        ``float("inf")`` recovers ``"deadline"``.
    seed : int, optional
        Seeds the per-episode jitter.
    """

    _SIGN = -1

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
        super().__init__(config)
        p: Dict[str, Any] = dict(config.parameters or {})
        self.budget_cap = float(p.get("budget_cap", 120))
        self.initial_share = float(p.get("initial_share", 0.5))
        self.gamma = float(p.get("gamma", 1.0))
        self.noise_sd = float(p.get("noise_sd", 3.0))
        self.backup_price = float(p.get("backup_price", 80))
        self.backup_success_prob = float(p.get("backup_success_prob", 0.5))
        self.walkaway_rule = str(p.get("walkaway_rule", "deadline"))
        if self.walkaway_rule not in ("deadline", "early"):
            raise ValueError(
                f"walkaway_rule must be 'deadline' or 'early', "
                f"got {self.walkaway_rule!r}"
            )
        self.insult_ratio = float(p.get("insult_ratio", 1.0))
        self._offset = 0.0
        self.reset()

    def backup_certainty_equivalent(self) -> float:
        """Expected surplus from the outside option, ``q * (m - p_backup)``.

        A failed backup leaves the buyer with nothing, which is exactly the
        payoff of walking away, so the failure branch contributes zero.
        """
        return self.backup_success_prob * max(self.budget_cap - self.backup_price, 0.0)

    def _ceiling(self, observation: Dict[str, Any]) -> float:
        """Highest price still worth paying — the buyer's reservation."""
        ceiling = self.budget_cap
        if observation.get("backup_available"):
            # Never pay more than the outside option is worth.
            ceiling = min(ceiling, self.budget_cap - self.backup_certainty_equivalent())
        return max(ceiling, 0.0)

    def _reservation_price(self, observation: Dict[str, Any]) -> float:
        return self._ceiling(observation)

    def _time_bid(self, t: float, observation: Dict[str, Any]) -> float:
        start = self.initial_share * self.budget_cap
        end = max(self._ceiling(observation), start)
        return _concession(start, end, t, self.gamma) + self._offset

    def _clamp(self, bid: float, observation: Dict[str, Any]) -> float:
        return min(max(bid, 0.0), self._ceiling(observation))

    def act(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        offer = observation.get("seller_offer")
        t = self._t(observation)
        total = int(observation.get("total_rounds", 10))
        rnd = int(observation.get("round", 1))

        if offer is not None:
            self._opp_hist.append(float(offer))

        counter = self._bid(t, observation)
        t_next = min(rnd, max(total - 1, 1)) / max(total - 1, 1)
        next_counter = self._clamp(self._time_bid(t_next, observation), observation)
        next_counter = max(next_counter, counter)   # monotone for the buyer too

        if self._accepts(
            None if offer is None else float(offer), observation, next_counter
        ):
            return {
                "message": "",
                "action": {"type": "ACCEPT", "price": float(offer)},
            }

        if observation.get("backup_available"):
            # Leaving with nothing is never better than waiting, so a buyer
            # without a backup has no early exit to give: this whole branch is
            # gated on one existing.
            if (
                self.walkaway_rule == "early"
                and offer is not None
                and float(offer) > self.insult_ratio * self._ceiling(observation) + 1e-9
            ):
                # The ask is outside the set of prices this buyer would ever
                # accept.  Under "early" it does not wait to find out whether
                # the seller would have conceded.
                return {
                    "message": "",
                    "action": {"type": "SWITCH_TO_BACKUP", "price": None},
                }
            if self._is_deadline(observation):
                # Last chance: take the backup only if it beats the standing offer.
                standing = float(offer) if offer is not None else float("inf")
                if self.budget_cap - standing < self.backup_certainty_equivalent():
                    return {
                        "message": "",
                        "action": {"type": "SWITCH_TO_BACKUP", "price": None},
                    }

        price = round(counter, 2)
        self._own_prev = price
        return {"message": "", "action": {"type": "COUNTER", "price": price}}

    def reset(self) -> None:
        super().reset()
        # One level shift per episode keeps runs independent without letting
        # round-to-round jitter masquerade as a concession.
        self._offset = self._rng.gauss(0.0, self.noise_sd) if self.noise_sd else 0.0

    def __repr__(self) -> str:
        return (
            f"ABMPurchaserAgent(id={self.agent_id!r}, m={self.budget_cap:g}, "
            f"gamma={self.gamma:g}, tft={self.tft_weight:g}, "
            f"walkaway={self.walkaway_rule})"
        )
