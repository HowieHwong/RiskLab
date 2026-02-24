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
    """

    def __init__(
        self,
        config: AgentConfig,
        llm_config: Optional[LLMConfig] = None,
        llm_client: Optional[LLMClient] = None,
        task_prompt: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> None:
        super().__init__(config)
        self.llm_config = llm_config or LLMConfig.from_env()
        self.llm_client = llm_client or LLMClient(self.llm_config)
        self._temperature = temperature
        self._max_tokens = max_tokens

        # Conversation history: alternating user/assistant messages
        self._conversation: List[Dict[str, str]] = []

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

        # Call LLM
        try:
            response_text = self.llm_client.chat(
                model=self.model,
                messages=messages,
                temperature=self._temperature,
                max_tokens=self._max_tokens,
            )
        except Exception as e:
            # Fallback for API errors
            response_text = (
                "[Price]\n10\n[Speech]\nAPI error fallback: pricing at marginal cost."
            )
            print(f"  ⚠ LLM error for {self.agent_id}: {e}")

        # Store in conversation history (both sides)
        self._conversation.append({"role": "user", "content": obs_text})
        self._conversation.append(
            {"role": "assistant", "content": response_text}
        )

        return {
            "message": response_text,
            "action": response_text,
            "raw_response": response_text,
        }

    def reset(self) -> None:
        """Reset conversation history for a new episode."""
        super().reset()
        self._conversation.clear()

    def __repr__(self) -> str:
        return (
            f"MarketSellerAgent(id={self.agent_id!r}, "
            f"model={self.model!r}, rounds={len(self._conversation) // 2})"
        )
