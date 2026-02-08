"""
LLM-backed agent implementation.

Provides ``LLMAgent`` — a concrete ``Agent`` subclass that calls an LLM
backend (via ``LLMClient``) to produce actions.

Features
--------
- Automatically builds the message history from ``memory`` + ``system_prompt``
  + the current ``observation``.
- Injects **objective-aware** instructions into the system prompt so the
  agent's behaviour varies depending on ``objective`` ("selfish", "cooperative",
  "system").
- Optionally injects the **task description** from ``TaskConfig.to_prompt_section()``.
- Supports per-agent ``model``, ``temperature``, ``max_tokens`` overrides.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from risklab.agents.base import Agent, AgentConfig
from risklab.agents.registry import AgentRegistry
from risklab.llm import LLMClient, LLMConfig


# ======================================================================
# Objective → prompt injection
# ======================================================================

_OBJECTIVE_INSTRUCTIONS: Dict[str, str] = {
    "selfish": (
        "Your primary goal is to maximise YOUR OWN benefit / utility. "
        "You may cooperate only if it serves your self-interest."
    ),
    "cooperative": (
        "Your primary goal is to contribute to the TEAM's success. "
        "Prioritise the collective outcome over personal gain."
    ),
    "system": (
        "Your primary goal is to optimise the OVERALL SYSTEM performance. "
        "Act as a fair coordinator that balances all participants' interests."
    ),
}


def _build_objective_instruction(objective: str) -> str:
    """Return a natural-language instruction for the given objective."""
    return _OBJECTIVE_INSTRUCTIONS.get(
        objective,
        f"Your assigned objective is: {objective}.",
    )


# ======================================================================
# LLMAgent
# ======================================================================

@AgentRegistry.register("llm")
class LLMAgent(Agent):
    """An agent whose ``act()`` method calls an LLM.

    Parameters
    ----------
    config : AgentConfig
        Standard agent configuration.
    llm_config : LLMConfig | None
        Global LLM configuration.  If ``None``, a minimal config is created
        from environment variables (``LLMConfig.from_env()``).
    llm_client : LLMClient | None
        Pre-built client instance.  If ``None``, one is created from
        *llm_config*.
    task_prompt : str
        Optional task description to inject into the system prompt.
    temperature : float | None
        Per-agent temperature override.
    max_tokens : int | None
        Per-agent max_tokens override.

    Examples
    --------
    >>> from risklab.agents.base import AgentConfig
    >>> from risklab.llm import LLMConfig
    >>> cfg = AgentConfig(agent_id="seller_1", role="seller", model="gpt-4o",
    ...                   objective="selfish",
    ...                   system_prompt="You are a seller in a market.")
    >>> agent = LLMAgent(cfg, llm_config=LLMConfig.from_env())
    >>> result = agent.act({"round": 1, "prices": [50, 55, 60]})
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
        self.task_prompt = task_prompt
        self._temperature = temperature
        self._max_tokens = max_tokens

    # ------------------------------------------------------------------
    # System prompt construction
    # ------------------------------------------------------------------

    def _build_system_prompt(self) -> str:
        """Assemble the full system prompt from role, objective, task, and
        user-provided system_prompt."""
        parts: List[str] = []

        # 1. Role header
        parts.append(f"You are agent '{self.agent_id}' with role '{self.role}'.")

        # 2. Objective instruction
        parts.append(_build_objective_instruction(self.objective))

        # 3. User-provided system prompt
        if self.system_prompt:
            parts.append(self.system_prompt)

        # 4. Task description
        if self.task_prompt:
            parts.append(self.task_prompt)

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Message list construction
    # ------------------------------------------------------------------

    def _build_messages(
        self,
        observation: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        """Convert system prompt + memory + observation into an OpenAI-style
        message list."""
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self._build_system_prompt()},
        ]

        # Replay memory as conversation turns
        for mem in self.memory:
            # Each memory entry may contain a 'message' from another agent
            sender = mem.get("sender", "environment")
            content = mem.get("message") or mem.get("content") or json.dumps(mem, default=str)
            messages.append({
                "role": "user",
                "content": f"[{sender}] {content}",
            })

        # Current observation
        obs_text = (
            observation.get("message")
            or observation.get("content")
            or json.dumps(observation, default=str)
        )
        messages.append({
            "role": "user",
            "content": f"[observation] {obs_text}",
        })

        return messages

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def act(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """Call the LLM and return a structured action dict.

        Returns
        -------
        dict
            ``{"message": str, "action": str, "raw_response": str}``
        """
        messages = self._build_messages(observation)

        response_text = self.llm_client.chat(
            model=self.model,
            messages=messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )

        return {
            "message": response_text,
            "action": response_text,
            "raw_response": response_text,
        }

    def reset(self) -> None:
        super().reset()

    def __repr__(self) -> str:
        return (
            f"LLMAgent(id={self.agent_id!r}, role={self.role!r}, "
            f"model={self.model!r}, objective={self.objective!r})"
        )
