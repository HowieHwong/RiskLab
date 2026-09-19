"""
Market Seller Agent — specialized agent for market competition experiments.

Maintains a proper alternating user/assistant conversation history,
which is critical for market games where agents need memory of their
own past actions to develop pricing strategies across rounds.

Unlike the generic ``LLMAgent`` (which stores all memory as ``user``
messages), this agent maintains the native OpenAI message format:

    system → user(obs1) → assistant(resp1) → user(obs2) → assistant(resp2) → …

This preserves the LLM's natural conversation flow and enables
in-context learning from the agent's own past decisions.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from risklab.agents.base import Agent, AgentConfig
from risklab.agents.registry import AgentRegistry
from risklab.llm import LLMClient, LLMConfig


@AgentRegistry.register("market_seller")
class MarketSellerAgent(Agent):
    """Agent specialized for market competition experiments.

    Key differences from ``LLMAgent``:
    1. Uses ``system_prompt`` directly (no auto-generated prefix).
    2. Maintains alternating user/assistant conversation history.
    3. ``observe()`` is a no-op — history management is handled in ``act()``.

    Parameters
    ----------
    config : AgentConfig
        Agent configuration (must include ``system_prompt``).
    llm_config : LLMConfig | None
        Global LLM config.
    llm_client : LLMClient | None
        Pre-built LLM client.
    temperature : float | None
        Per-agent temperature override.
    max_tokens : int | None
        Per-agent max_tokens override.
    llm_params : dict | None
        Extra keyword arguments forwarded verbatim to every provider call —
        e.g. ``{"extra_body": {"reasoning": {"effort": "high", "exclude":
        False}}}`` to run a reasoning model at high effort and keep its
        reasoning summary.
    max_retries : int
        Retries for a failed or empty completion before falling back to
        marginal-cost pricing (default 2, i.e. up to 3 attempts).
    retry_backoff : float
        Seconds before the first retry; doubles on each further attempt.
    """

    def __init__(
        self,
        config: AgentConfig,
        llm_config: Optional[LLMConfig] = None,
        llm_client: Optional[LLMClient] = None,
        task_prompt: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        llm_params: Optional[Dict[str, Any]] = None,
        max_retries: int = 2,
        retry_backoff: float = 1.0,
    ) -> None:
        super().__init__(config)
        self.llm_config = llm_config or LLMConfig.from_env()
        self.llm_client = llm_client or LLMClient(self.llm_config)
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._llm_params: Dict[str, Any] = dict(llm_params or {})
        self._max_retries = max(0, int(max_retries))
        self._retry_backoff = float(retry_backoff)

        # Conversation history: alternating user/assistant messages
        self._conversation: List[Dict[str, str]] = []
        #: Number of rounds in which every attempt failed and the agent fell
        #: back to marginal-cost pricing.  Report this alongside results.
        self.llm_errors: int = 0
        #: Number of individual attempts that failed but were then retried
        #: successfully.  Diagnostic only — those rounds are clean.
        self.llm_retries: int = 0

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def observe(self, observation: Dict[str, Any]) -> None:
        """No-op — history is managed entirely within ``act()``.

        In market games, each ``act()`` call appends both the observation
        (user) and the response (assistant) to the conversation, ensuring
        the alternation pattern is never broken.
        """
        pass

    def act(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """Call the LLM with full conversation history and return action.

        The observation is formatted as a user message, and the LLM's
        reply is stored as an assistant message for future rounds.

        Returns
        -------
        dict
            ``{"message": str, "action": str, "raw_response": str}``
        """
        # Build observation text
        obs_text = (
            observation.get("message")
            or observation.get("content")
            or json.dumps(observation, default=str)
        )

        # Build message list: system + history + current observation
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self.system_prompt},
        ]
        messages.extend(self._conversation)
        messages.append({"role": "user", "content": obs_text})

        # Call LLM.  Both transport errors and degenerate empty completions are
        # infrastructure failures rather than pricing decisions, so they are
        # retried before the market ever sees a fallback price.
        llm_error: Optional[str] = None
        reasoning: Optional[str] = None
        response_text = ""
        last_exc: Optional[Exception] = None

        for attempt in range(self._max_retries + 1):
            try:
                result = self.llm_client.chat_detailed(
                    model=self.model,
                    messages=messages,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                    **self._llm_params,
                )
                response_text = result["content"]
                reasoning = result.get("reasoning")
                # A reasoning model that spends its whole token budget thinking
                # returns an empty answer with no exception.  Left unchecked
                # that silently becomes an unparseable action and drags the
                # market price down, which would read as "no collusion".
                # Sampling is stochastic, so a retry usually terminates.
                if not response_text.strip():
                    raise ValueError(
                        "empty completion (reasoning tokens likely exhausted "
                        f"max_tokens={self._max_tokens})"
                    )
                last_exc = None
                break
            except Exception as e:
                last_exc = e
                if attempt < self._max_retries:
                    self.llm_retries += 1
                    time.sleep(self._retry_backoff * (2 ** attempt))

        if last_exc is not None:
            # Every attempt failed.  Pricing at marginal cost biases the market
            # price *down*, so the failure is reported in the action rather
            # than silently absorbed into the results.
            response_text = (
                "[Price]\n10\n[Speech]\nAPI error fallback: pricing at marginal cost."
            )
            llm_error = f"{type(last_exc).__name__}: {last_exc}"
            self.llm_errors += 1
            print(
                f"  ⚠ LLM error for {self.agent_id} after "
                f"{self._max_retries + 1} attempts: {last_exc}"
            )

        # Store in conversation history (both sides)
        self._conversation.append({"role": "user", "content": obs_text})
        self._conversation.append(
            {"role": "assistant", "content": response_text}
        )

        return {
            "message": response_text,
            "action": response_text,
            "raw_response": response_text,
            "llm_error": llm_error,
            "reasoning": reasoning,
        }

    def reset(self) -> None:
        """Reset conversation history for a new episode."""
        super().reset()
        self._conversation.clear()
        self.llm_errors = 0
        self.llm_retries = 0

    def __repr__(self) -> str:
        return (
            f"MarketSellerAgent(id={self.agent_id!r}, "
            f"model={self.model!r}, rounds={len(self._conversation) // 2})"
        )
