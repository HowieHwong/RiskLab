"""
Trading Pipeline Environment for Rigidity & Mistaken Commitments (Risk 13).

Models a cyclic sequential trading pipeline:

    Round 0 (Strategy):  User Strategy → ALL agents (shared)
    Round 1+: Market Events → Analyst → Strategy Planner → Trade Execution

Key design decisions:
    1. **Shared User Strategy**: In Round 0, ALL agents receive the user's
       original investment strategy directly. Downstream agents also see
       their predecessor's analysis alongside the strategy.
    2. **Per-round market injection**: Each round ≥ 1 injects a new market
       event into the Analyst's observation. Downstream agents see only
       their predecessor's output (the user strategy is already in their
       LLM memory from Round 0).
    3. **Cross-round memory**: Via the LLMAgent memory mechanism, agents
       accumulate conversation history across rounds, enabling contextual
       reasoning about evolving market conditions.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from risklab.environments.collective.base import CollectiveEnvironment
from risklab.environments.base import EnvironmentConfig


class TradingPipelineEnvironment(CollectiveEnvironment):
    """Cyclic sequential pipeline for trading-strategy experiments.

    Parameters (via ``EnvironmentConfig.parameters``)
    --------------------------------------------------
    pipeline_order : list[str]
        Ordered agent IDs, e.g. ``["analyst", "strategy_planner",
        "trade_execution"]``.
    round_inputs : list[str]
        One input string per pipeline round.  Index 0 is the user's
        investment strategy (shared with all agents); indices 1+ are
        market event injections for the Analyst in subsequent rounds.
    """

    def __init__(self, config: EnvironmentConfig) -> None:
        super().__init__(config)
        params = config.parameters
        self.pipeline_order: List[str] = params.get("pipeline_order", [])
        self.round_inputs: List[str] = params.get("round_inputs", [])

        # Validate
        if not self.pipeline_order:
            raise ValueError("pipeline_order must be a non-empty list")
        if not self.round_inputs:
            raise ValueError("round_inputs must be a non-empty list")

        # Runtime state (initialised in reset())
        self._pipeline_round: int = 0
        self._stage_in_round: int = 0
        self._round_outputs: Dict[int, Dict[str, str]] = {}
        self._user_instruction: str = ""

    # ------------------------------------------------------------------
    # Environment interface
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset for a new episode."""
        self.done = False
        self.current_round = 0
        self._pipeline_round = 0
        self._stage_in_round = 0
        self._round_outputs = {}
        self._user_instruction = self.round_inputs[0] if self.round_inputs else ""
        self.state = {}
        self.votes = []

    def get_observation(self, agent_id: str) -> Dict[str, Any]:
        """Return the observation for *agent_id* in the current round.

        Round 0 — Strategy Phase:
            ALL agents receive the user's investment strategy directly.
            Downstream agents also see their predecessor's analysis.

        Round 1+ — Market Event Phase:
            Analyst receives the market event injection.
            Downstream agents see their predecessor's output only.
            (The user strategy is already in their LLM memory.)
        """
        stage_idx = self._get_stage_index(agent_id)

        if self._pipeline_round == 0:
            return self._obs_strategy_round(agent_id, stage_idx)
        else:
            return self._obs_market_round(agent_id, stage_idx)

    def step(
        self, joint_action: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, float], bool, Dict[str, Any]]:
        """Process a single agent's action in the pipeline.

        Called once per agent per round.  After the last agent in the
        pipeline speaks, the round advances.
        """
        for agent_id, action in joint_action.items():
            output_text = self._extract_output(action)
            self._round_outputs.setdefault(
                self._pipeline_round, {}
            )[agent_id] = output_text
            self._stage_in_round += 1

        # Check if all agents in this round have spoken
        if self._stage_in_round >= len(self.pipeline_order):
            self._pipeline_round += 1
            self._stage_in_round = 0
            self.current_round = self._pipeline_round

            if self._pipeline_round >= len(self.round_inputs):
                self.done = True

        info: Dict[str, Any] = {
            "pipeline_round": self._pipeline_round,
            "stage_in_round": self._stage_in_round,
            "total_rounds": len(self.round_inputs),
            "pipeline_complete": self.done,
        }

        if self.done:
            info["all_round_outputs"] = dict(self._round_outputs)

        observations = {aid: {} for aid in self.pipeline_order}
        rewards = {aid: 0.0 for aid in self.pipeline_order}

        return observations, rewards, self.done, info

    def check_failure(self) -> Optional[str]:
        """Check for pipeline failures."""
        for rnd in range(self._pipeline_round):
            outputs = self._round_outputs.get(rnd, {})
            for agent_id in self.pipeline_order:
                if agent_id not in outputs:
                    return (
                        f"Agent '{agent_id}' did not produce output "
                        f"in round {rnd}."
                    )
                if not outputs[agent_id].strip():
                    return (
                        f"Agent '{agent_id}' produced empty output "
                        f"in round {rnd}."
                    )
        return None

    # ------------------------------------------------------------------
    # Observation builders
    # ------------------------------------------------------------------

    def _obs_strategy_round(
        self, agent_id: str, stage_idx: int
    ) -> Dict[str, Any]:
        """Build observation for Round 0 (strategy phase).

        All agents see the user instruction directly.
        Downstream agents additionally see predecessor's output.
        """
        if stage_idx == 0:
            # First agent (Analyst): user instruction only
            return {
                "role": "user",
                "message": self._user_instruction,
                "sender": "user",
                "pipeline_round": 0,
                "stage": stage_idx,
                "round_type": "strategy",
            }
        else:
            # Downstream agents: user instruction + predecessor output
            predecessor_id = self.pipeline_order[stage_idx - 1]
            predecessor_output = (
                self._round_outputs.get(0, {}).get(predecessor_id, "")
            )

            message = (
                f"=== User's Investment Strategy ===\n"
                f"{self._user_instruction}\n\n"
                f"=== Report from {predecessor_id} ===\n"
                f"{predecessor_output}"
            )

            return {
                "role": "user",
                "message": message,
                "sender": "environment",
                "pipeline_round": 0,
                "stage": stage_idx,
                "round_type": "strategy",
            }

    def _obs_market_round(
        self, agent_id: str, stage_idx: int
    ) -> Dict[str, Any]:
        """Build observation for Round 1+ (market event phase).

        Analyst receives the market event injection.
        Downstream agents receive predecessor's output only.
        """
        if stage_idx == 0:
            # Analyst: market event injection
            if self._pipeline_round < len(self.round_inputs):
                input_text = self.round_inputs[self._pipeline_round]
            else:
                input_text = "(no market event for this round)"

            return {
                "role": "user",
                "message": input_text,
                "sender": "market",
                "pipeline_round": self._pipeline_round,
                "stage": stage_idx,
                "round_type": "market_event",
            }
        else:
            # Downstream: predecessor's output
            predecessor_id = self.pipeline_order[stage_idx - 1]
            predecessor_output = (
                self._round_outputs
                .get(self._pipeline_round, {})
                .get(predecessor_id, "")
            )

            return {
                "role": predecessor_id,
                "message": predecessor_output,
                "sender": predecessor_id,
                "pipeline_round": self._pipeline_round,
                "stage": stage_idx,
                "round_type": "market_event",
            }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_output(action: Any) -> str:
        """Extract text output from an action dict or raw string."""
        if isinstance(action, dict):
            return str(
                action.get("message")
                or action.get("action")
                or action.get("content")
                or json.dumps(action, default=str)
            )
        return str(action)

    def _get_stage_index(self, agent_id: str) -> int:
        """Return the pipeline stage index for *agent_id*."""
        try:
            return self.pipeline_order.index(agent_id)
        except ValueError:
            raise ValueError(
                f"Agent '{agent_id}' not found in pipeline_order: "
                f"{self.pipeline_order}"
            )

    # ------------------------------------------------------------------
    # CollectiveEnvironment interface
    # ------------------------------------------------------------------

    def aggregate(self, judgments: Dict[str, Any]) -> Any:
        """No aggregation needed — R13 is a sequential pipeline."""
        return None

    # ------------------------------------------------------------------
    # Analysis API
    # ------------------------------------------------------------------

    def get_round_outputs(self, round_idx: int) -> Dict[str, str]:
        """Return all agent outputs for a specific round."""
        return dict(self._round_outputs.get(round_idx, {}))

    def get_all_round_outputs(self) -> Dict[int, Dict[str, str]]:
        """Return all outputs: ``{round: {agent_id: output}}``."""
        return {r: dict(v) for r, v in self._round_outputs.items()}

    def get_agent_outputs_across_rounds(self, agent_id: str) -> Dict[int, str]:
        """Return one agent's output for every round."""
        return {
            rnd: outputs.get(agent_id, "")
            for rnd, outputs in self._round_outputs.items()
            if agent_id in outputs
        }

    @property
    def user_instruction(self) -> str:
        """The user's original investment strategy."""
        return self._user_instruction

    @property
    def total_rounds(self) -> int:
        """Total number of pipeline rounds."""
        return len(self.round_inputs)

    @property
    def total_market_rounds(self) -> int:
        """Number of market event rounds (excluding round 0)."""
        return max(len(self.round_inputs) - 1, 0)
