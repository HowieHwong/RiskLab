"""
Subtask Staff Agent — LLM staff member for the Risk 1.3 subtask-selection
environment.

Every call carries the agent's system prompt and the current round's messages
only: no conversation history is kept across rounds.  The environment's
``[User]`` message already restates the previous round, the agent's own pick
and reason included, so the protocol loses nothing.  It returns a structured
choice

    {"step": "S1" | "S2" | ... | None, "reason": str}

read from the JSON schema of the original prompts.

Failure policy
--------------
Transport errors, empty completions and completions in which no step id can
be read are all retried on the same context.  When every attempt fails the
agent returns ``step = None``: the environment records an invalid choice,
which can never complete an allocation.  A step is never invented — a
fabricated pick would land directly in the failure rate.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from risklab.agents.base import Agent, AgentConfig
from risklab.agents.registry import AgentRegistry
from risklab.environments.competitive.subtask_selection import parse_choice
from risklab.llm import LLMClient, LLMConfig


@AgentRegistry.register("subtask_staff")
class SubtaskStaffAgent(Agent):
    """LLM agent that names one project step per round.

    Parameters
    ----------
    config : AgentConfig
        Must carry the agent's ``system_prompt``.
    max_retries : int
        Retries per turn on a failed, empty or unreadable completion
        (default 2).
    retry_backoff : float
        Seconds before the first transport retry; doubles each attempt.
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
        **kwargs: Any,
    ) -> None:
        super().__init__(config)
        self.llm_config = llm_config or LLMConfig.from_env()
        self.llm_client = llm_client or LLMClient(self.llm_config)
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._llm_params: Dict[str, Any] = dict(llm_params or {})
        self._max_retries = max(0, int(max_retries))
        self._retry_backoff = float(retry_backoff)

        #: Turns where the last attempt still failed in transport.
        self.llm_errors: int = 0
        #: Transport attempts that failed but were retried (diagnostic).
        self.llm_retries: int = 0
        #: Unreadable completions that were resampled (diagnostic).
        self.parse_retries: int = 0
        #: Turns that ended without a readable step.
        self.parse_failures: int = 0
        #: Most recent transport error, so a driver can tell a refused key
        #: (no behaviour at all) from a transient failure.
        self.last_llm_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def observe(self, observation: Dict[str, Any]) -> None:
        """No-op — the observation arrives through ``act``."""
        pass

    def act(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        obs_text = (
            observation.get("message")
            or observation.get("content")
            or json.dumps(observation, default=str)
        )
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": obs_text},
        ]

        llm_error: Optional[str] = None
        reasoning: Optional[str] = None
        response_text = ""
        step: Optional[str] = None
        reason = ""

        for attempt in range(self._max_retries + 1):
            try:
                result = self.llm_client.chat_detailed(
                    model=self.model,
                    messages=messages,
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                    **self._llm_params,
                )
            except Exception as e:  # noqa: BLE001 — transport-agnostic retry
                llm_error = f"{type(e).__name__}: {e}"
                self.last_llm_error = llm_error
                if attempt < self._max_retries:
                    self.llm_retries += 1
                    time.sleep(self._retry_backoff * (2 ** attempt))
                continue

            llm_error = None
            response_text = result.get("content") or ""
            reasoning = result.get("reasoning")
            step, reason = parse_choice(response_text, self.agent_id)
            if step is not None:
                break
            if attempt < self._max_retries:
                self.parse_retries += 1

        if step is None:
            if llm_error is not None:
                self.llm_errors += 1
                print(
                    f"  ⚠ LLM error for {self.agent_id} after "
                    f"{self._max_retries + 1} attempts: {llm_error}"
                )
                response_text = response_text or f"[LLM error] {llm_error}"
            else:
                self.parse_failures += 1

        return {
            "message": response_text,
            "action": {"step": step, "reason": reason},
            "raw_response": response_text,
            "llm_error": llm_error,
            "reasoning": reasoning,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        super().reset()
        self.llm_errors = 0
        self.llm_retries = 0
        self.parse_retries = 0
        self.parse_failures = 0
        self.last_llm_error = None

    def __repr__(self) -> str:
        return f"SubtaskStaffAgent(id={self.agent_id!r}, model={self.model!r})"
