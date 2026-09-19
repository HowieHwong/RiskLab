"""
Bargaining Agent — LLM negotiator for the Risk 1.5 bilateral-bargaining
environment.

Like :class:`~risklab.agents.market_seller_agent.MarketSellerAgent` it keeps a
native alternating user/assistant conversation, which is what lets a
negotiator remember its own concession path.  It differs in what it returns:
a *structured* action

    {"type": "OFFER" | "COUNTER" | "ACCEPT" | "SWITCH_TO_BACKUP",
     "price": <number or null>}

plus a separate natural-language ``message``.  The environment decides whether
the counterpart ever sees that message (``allow_communication``), so the same
agent class serves both the language and the numbers-only conditions.

Failure policy
--------------
Transport errors and empty completions are retried.  When every attempt fails
the agent returns an action with **no price**: the environment records a
degraded turn and holds the standing offer.  It never invents a number — a
fabricated price would land directly in the surplus-capture rate.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

from risklab.agents.base import Agent, AgentConfig
from risklab.agents.registry import AgentRegistry
from risklab.llm import LLMClient, LLMConfig

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
_PRICE_RE = re.compile(r"(-?\d+(?:\.\d+)?)")
_VALID_KINDS = ("OFFER", "COUNTER", "ACCEPT", "SWITCH_TO_BACKUP")


@AgentRegistry.register("bargaining_agent")
class BargainingAgent(Agent):
    """LLM agent that emits a structured bargaining move each turn.

    Parameters
    ----------
    config : AgentConfig
        Must carry the role-specific ``system_prompt``.
    max_retries : int
        Retries per turn on a failed or empty completion (default 2).
    retry_backoff : float
        Seconds before the first retry; doubles each attempt.
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

        self._conversation: List[Dict[str, str]] = []
        #: Turns where every attempt failed (reported with the results).
        self.llm_errors: int = 0
        #: Attempts that failed but were retried successfully (diagnostic).
        self.llm_retries: int = 0
        #: Completions that arrived but could not be read as a move.
        self.parse_failures: int = 0

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def observe(self, observation: Dict[str, Any]) -> None:
        """No-op — history is managed inside ``act``."""
        pass

    def act(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        obs_text = (
            observation.get("message")
            or observation.get("content")
            or json.dumps(observation, default=str)
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self.system_prompt}
        ]
        messages.extend(self._conversation)
        messages.append({"role": "user", "content": obs_text})

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
                if not response_text.strip():
                    raise ValueError(
                        "empty completion (reasoning tokens likely exhausted "
                        f"max_tokens={self._max_tokens})"
                    )
                last_exc = None
                break
            except Exception as e:  # noqa: BLE001 — transport-agnostic retry
                last_exc = e
                if attempt < self._max_retries:
                    self.llm_retries += 1
                    time.sleep(self._retry_backoff * (2 ** attempt))

        if last_exc is not None:
            self.llm_errors += 1
            llm_error = f"{type(last_exc).__name__}: {last_exc}"
            print(
                f"  ⚠ LLM error for {self.agent_id} after "
                f"{self._max_retries + 1} attempts: {last_exc}"
            )
            # No price: the environment holds the standing offer and counts a
            # degraded turn.  Never fabricate a number.
            action = {"type": None, "price": None}
            response_text = f"[LLM error] {llm_error}"
        else:
            action = self._parse(response_text)

        self._conversation.append({"role": "user", "content": obs_text})
        self._conversation.append({"role": "assistant", "content": response_text})

        return {
            "message": action.get("message", ""),
            "action": action,
            "raw_response": response_text,
            "llm_error": llm_error,
            "reasoning": reasoning,
        }

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    def _parse(self, text: str) -> Dict[str, Any]:
        """Read ``{"action", "price", "message"}`` out of a completion."""
        payload: Optional[Dict[str, Any]] = None
        match = _JSON_RE.search(text)
        if match:
            for candidate in (match.group(0), match.group(0).replace("\n", " ")):
                try:
                    parsed = json.loads(candidate)
                except (ValueError, TypeError):
                    continue
                if isinstance(parsed, dict):
                    payload = parsed
                    break

        if payload is None:
            # Free-text fallback: recover a move from the prose rather than
            # discarding the turn, and count it.
            self.parse_failures += 1
            kind = self._kind_from_text(text)
            price_match = _PRICE_RE.search(text)
            return {
                "type": kind,
                "price": float(price_match.group(1)) if price_match else None,
                "message": text.strip()[:400],
            }

        raw_kind = payload.get("action") or payload.get("type") or ""
        kind = self._kind_from_text(str(raw_kind)) or self._kind_from_text(text)
        price = payload.get("price")
        if isinstance(price, str):
            price_match = _PRICE_RE.search(price)
            price = float(price_match.group(1)) if price_match else None
        elif isinstance(price, bool) or price is None:
            price = None
        else:
            price = float(price)

        return {
            "type": kind,
            "price": price,
            "message": str(payload.get("message", "") or "").strip(),
        }

    @staticmethod
    def _kind_from_text(raw: str) -> Optional[str]:
        upper = raw.upper()
        if "SWITCH" in upper or "BACKUP" in upper:
            return "SWITCH_TO_BACKUP"
        if "ACCEPT" in upper or "AGREE" in upper:
            return "ACCEPT"
        if "COUNTER" in upper:
            return "COUNTER"
        if "OFFER" in upper or "QUOTE" in upper or "PRICE" in upper:
            return "OFFER"
        return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        super().reset()
        self._conversation.clear()
        self.llm_errors = 0
        self.llm_retries = 0
        self.parse_failures = 0

    def __repr__(self) -> str:
        return (
            f"BargainingAgent(id={self.agent_id!r}, role={self.role!r}, "
            f"model={self.model!r}, turns={len(self._conversation) // 2})"
        )
