"""
Sequential Handoff Protocol.

Agents speak one after another in a fixed pipeline order.
Supports **parallel stages** — when a stage is a list of agents,
all of them speak before the flow advances to the next stage.

Example flow orders::

    # Pure serial:  user → A → B → C
    flow_order = ["user", "A", "B", "C"]

    # Fan-out:  user → (A, B, C simultaneously) → summary
    flow_order = ["user", ["A", "B", "C"], "summary"]

Each agent sees only the output of its immediate predecessor
(unless ``pass_original=True``), or as defined by the topology.

Triggers risks such as:
    - Semantic drift
    - Authority deference bias
    - Excessive rigidity to initial directives
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from risklab.protocols.base import InteractionProtocol

if TYPE_CHECKING:
    from risklab.topology import CommunicationTopology, InformationFlowConfig


class SequentialHandoff(InteractionProtocol):
    """Stage-based pipeline: stages are executed in order; each stage
    may contain one agent (serial) or multiple agents (parallel).

    ::

        flow_order = ["user", ["A", "B", "C"], "summary"]

        Stage 0: "user" speaks
        Stage 1: "A", "B", "C" all speak (any internal order) before
                 the flow moves on
        Stage 2: "summary" speaks

    If a topology is provided, ``get_listeners`` uses the adjacency matrix.
    If an InformationFlowConfig is provided and has a ``flow_order``, that
    order (with parallel groups) is used.
    """

    def __init__(
        self,
        agent_ids: List[str],
        pass_original: bool = False,
        topology: Optional["CommunicationTopology"] = None,
        flow: Optional["InformationFlowConfig"] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(agent_ids, topology=topology, flow=flow, **kwargs)
        self.pass_original = pass_original

        # Build the stage list from flow config or flat agent_ids
        from risklab.topology import stage_agents, FlowStage, FlowOrder
        if flow is not None and flow.stages:
            self._stages: FlowOrder = list(flow.stages)
        else:
            # Fallback: each agent is its own stage (pure serial)
            self._stages = list(agent_ids)

        # Runtime state
        self._stage_index: int = 0
        self._pending_in_stage: List[str] = []  # agents in current stage not yet spoken
        self._init_stage()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_stage(self) -> None:
        """Initialise the pending list for the current stage."""
        from risklab.topology import stage_agents
        if self._stage_index < len(self._stages):
            self._pending_in_stage = list(
                stage_agents(self._stages[self._stage_index])
            )
        else:
            self._pending_in_stage = []

    def _current_stage_is_parallel(self) -> bool:
        from risklab.topology import is_parallel
        if self._stage_index < len(self._stages):
            return is_parallel(self._stages[self._stage_index])
        return False

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def get_next_speaker(self) -> Optional[str]:
        # If there are pending agents in the current stage, return the first
        if self._pending_in_stage:
            return self._pending_in_stage[0]
        return None

    def get_listeners(self, speaker: str) -> List[str]:
        # Topology takes priority
        if self.topology is not None:
            return self.topology.get_receivers(speaker, t=self.current_round)

        # Fallback: listeners are all agents in the NEXT stage
        from risklab.topology import stage_agents
        next_idx = self._stage_index + 1
        if next_idx < len(self._stages):
            return stage_agents(self._stages[next_idx])
        return []

    def advance(self) -> None:
        # Remove current speaker from pending
        if self._pending_in_stage:
            self._pending_in_stage.pop(0)

        # If all agents in this stage have spoken, move to next stage
        if not self._pending_in_stage:
            self._stage_index += 1
            if self._stage_index >= len(self._stages):
                # All stages done → wrap around (new round)
                self._stage_index = 0
                self.current_round += 1
            self._init_stage()

    def reset(self) -> None:
        super().reset()
        self._stage_index = 0
        self._init_stage()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def current_stage_index(self) -> int:
        return self._stage_index

    @property
    def num_stages(self) -> int:
        return len(self._stages)

    @property
    def stages(self):
        return list(self._stages)
