"""
Ad Pipeline Environment for Semantic Drift experiments (Risk 6).

Models a sequential advertising-copy pipeline:

    User Input (product spec) → R&D Designer → Ad Designer → Product Manager

Each agent sees only the output of its immediate predecessor.
The environment tracks the original input and all intermediate outputs
to enable post-hoc semantic-drift analysis.

Key design:
    - **Acyclic**: each agent speaks exactly once per episode.
    - **Information asymmetry**: later agents cannot see the original spec.
    - The environment's ``step()`` buffers each agent's output and forwards
      it as the next agent's observation.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from risklab.environments.cooperative.base import CooperativeEnvironment
from risklab.environments.base import EnvironmentConfig


class AdPipelineEnvironment(CooperativeEnvironment):
    """Sequential ad-copy pipeline for semantic-drift experiments.

    Parameters (via ``EnvironmentConfig.parameters``)
    --------------------------------------------------
    pipeline_order : list[str]
        Ordered agent IDs, e.g. ``["rd_designer", "ad_designer", "product_manager"]``.
    user_input : dict | str
        The original product specification (JSON).  Injected by the runner
        via ``state["_pipeline_input"]`` for acyclic flows, or set directly
        in parameters for single-input experiments.
    """

    def __init__(self, config: EnvironmentConfig) -> None:
        super().__init__(config)
        params = config.parameters
        self.pipeline_order: List[str] = params.get("pipeline_order", [])
        self._user_input: Any = params.get("user_input", None)

        # Runtime state
        self._stage_index: int = 0
        self._stage_outputs: Dict[str, str] = {}  # agent_id → raw output
        self._all_agent_ids: List[str] = list(self.pipeline_order)

    # ------------------------------------------------------------------
    # Environment interface
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset for a new episode."""
        self.done = False
        self.current_round = 0
        self._stage_index = 0
        self._stage_outputs = {}
        self.state = {}
        self.handoff_history = []

    def get_observation(self, agent_id: str) -> Dict[str, Any]:
        """Return the observation for *agent_id*.

        - First agent sees the raw product specification.
        - Subsequent agents see only their predecessor's output.
        """
        # Check for runner-injected pipeline input
        user_input = self.state.get("_pipeline_input", self._user_input)

        stage_idx = self._get_stage_index(agent_id)

        if stage_idx == 0:
            # First agent: sees the raw product spec
            if isinstance(user_input, dict):
                input_text = json.dumps(user_input, indent=2, ensure_ascii=False)
            else:
                input_text = str(user_input)

            return {
                "role": "user",
                "message": input_text,
                "stage": 0,
                "sender": "user",
            }
        else:
            # Subsequent agents: see predecessor's output only
            predecessor_id = self.pipeline_order[stage_idx - 1]
            predecessor_output = self._stage_outputs.get(predecessor_id, "")

            return {
                "role": predecessor_id,
                "message": predecessor_output,
                "stage": stage_idx,
                "sender": predecessor_id,
            }

    def step(
        self, joint_action: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Dict[str, float], bool, Dict[str, Any]]:
        """Process a single agent's action in the pipeline.

        Each call advances the pipeline by one stage.
        """
        for agent_id, action in joint_action.items():
            # Extract the message / content
            if isinstance(action, dict):
                output_text = (
                    action.get("message")
                    or action.get("action")
                    or action.get("content")
                    or json.dumps(action, default=str)
                )
            else:
                output_text = str(action)

            # Store output
            self._stage_outputs[agent_id] = output_text

            # Record handoff
            stage_idx = self._get_stage_index(agent_id)
            self.handoff_history.append({
                "stage": stage_idx,
                "agent_id": agent_id,
                "output": output_text,
            })

            # Advance stage
            self._stage_index = stage_idx + 1

        # Check if pipeline is complete
        if self._stage_index >= len(self.pipeline_order):
            self.done = True

        # Build info dict
        info = {
            "stage_complete": True,
            "pipeline_complete": self.done,
            "current_stage": self._stage_index,
            "total_stages": len(self.pipeline_order),
        }

        # If pipeline is complete, include all outputs for analysis
        if self.done:
            user_input = self.state.get("_pipeline_input", self._user_input)
            info["original_input"] = user_input
            info["stage_outputs"] = dict(self._stage_outputs)
            info["final_output"] = self._stage_outputs.get(
                self.pipeline_order[-1], ""
            )

        # Observations and rewards (placeholder for non-final stages)
        observations = {aid: {} for aid in self._all_agent_ids}
        rewards = {aid: 0.0 for aid in self._all_agent_ids}

        return observations, rewards, self.done, info

    def check_failure(self) -> Optional[str]:
        """Check for pipeline failures (e.g., missing outputs)."""
        for agent_id in self.pipeline_order:
            if agent_id not in self._stage_outputs:
                return f"Agent '{agent_id}' did not produce any output."
        return None

    # ------------------------------------------------------------------
    # Cooperative interface
    # ------------------------------------------------------------------

    def handoff(
        self,
        sender_id: str,
        receiver_id: str,
        payload: Any,
    ) -> Any:
        """Direct passthrough — no noise or filtering."""
        return payload

    # ------------------------------------------------------------------
    # Analysis helpers
    # ------------------------------------------------------------------

    def get_all_outputs(self) -> Dict[str, str]:
        """Return all stage outputs keyed by agent_id."""
        return dict(self._stage_outputs)

    def get_original_input(self) -> Any:
        """Return the original user input."""
        return self.state.get("_pipeline_input", self._user_input)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_stage_index(self, agent_id: str) -> int:
        """Return the pipeline stage index for *agent_id*."""
        try:
            return self.pipeline_order.index(agent_id)
        except ValueError:
            return 0
