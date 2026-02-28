"""
Broadcast Deliberation Protocol.

All agents hear every message within the round (or as defined by the
topology's adjacency matrix).
A moderator (if present) collects and aggregates.

Supports **parallel stages** from flow_order — within each parallel
group all agents speak, then the next stage begins.

Triggers risks such as:
    - Normative deadlock
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from risklab.protocols.base import InteractionProtocol

if TYPE_CHECKING:
    from risklab.topology import CommunicationTopology, InformationFlowConfig


class BroadcastDeliberation(InteractionProtocol):
    """All agents broadcast to every other agent each round.

    If a flow_order with parallel stages is provided, the protocol
    iterates stage by stage.  Within each stage, all agents speak
    (broadcast to listeners determined by topology or default all-to-all).

    If no flow is provided, falls back to round-robin over ``agent_ids``.
    """

    def __init__(
        self,
        agent_ids: List[str],
        moderator_id: Optional[str] = None,
        topology: Optional["CommunicationTopology"] = None,
        flow: Optional["InformationFlowConfig"] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(agent_ids, topology=topology, flow=flow, **kwargs)
        self.moderator_id = moderator_id

        # Build stage list from flow or flat agent_ids
        from risklab.topology import FlowOrder
        if flow is not None and flow.stages:
            self._stages: FlowOrder = list(flow.stages)
        else:
            self._stages = list(agent_ids)

        self._stage_index: int = 0
        self._pending_in_stage: List[str] = []
        self._init_stage()

    def _init_stage(self) -> None:
        from risklab.topology import stage_agents
        if self._stage_index < len(self._stages):
            self._pending_in_stage = list(
                stage_agents(self._stages[self._stage_index])
            )
        else:
            self._pending_in_stage = []

    def get_next_speaker(self) -> Optional[str]:
        if self._pending_in_stage:
            return self._pending_in_stage[0]
        return None

    def get_listeners(self, speaker: str) -> List[str]:
        if self.topology is not None:
            return self.topology.get_receivers(speaker, t=self.current_round)
        return [a for a in self.agent_ids if a != speaker]

    def advance(self) -> None:
        if self._pending_in_stage:
            self._pending_in_stage.pop(0)

        if not self._pending_in_stage:
            self._stage_index += 1
            if self._stage_index >= len(self._stages):
                self._stage_index = 0
                self.current_round += 1
            self._init_stage()

    def reset(self) -> None:
        super().reset()
        self._stage_index = 0
        self._init_stage()
