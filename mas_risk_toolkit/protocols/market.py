"""
Market Turn-Based Protocol.

Agents take turns posting prices / bids.  All agents see all past
actions (public communication), forming a repeated game.
With a topology, visibility may be restricted.

Triggers risks such as:
    - Tacit collusion
    - Information asymmetry exploitation
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from mas_risk_toolkit.protocols.base import InteractionProtocol

if TYPE_CHECKING:
    from mas_risk_toolkit.topology import CommunicationTopology, InformationFlowConfig


class MarketTurnBased(InteractionProtocol):
    """All agents act simultaneously (or sequentially) in each round;
    actions are publicly broadcast before the next round begins.

    If a topology is attached, ``get_listeners`` uses the adjacency matrix.
    """

    def __init__(
        self,
        agent_ids: List[str],
        simultaneous: bool = True,
        topology: Optional["CommunicationTopology"] = None,
        flow: Optional["InformationFlowConfig"] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(agent_ids, topology=topology, flow=flow, **kwargs)
        self.simultaneous = simultaneous
        self._acted_this_round: set = set()
        self._turn_index: int = 0

    def get_next_speaker(self) -> Optional[str]:
        if self.simultaneous:
            remaining = [
                a for a in self.agent_ids if a not in self._acted_this_round
            ]
            return remaining[0] if remaining else None
        else:
            if self._turn_index < len(self.agent_ids):
                return self.agent_ids[self._turn_index]
            return None

    def get_listeners(self, speaker: str) -> List[str]:
        if self.topology is not None:
            return self.topology.get_receivers(speaker, t=self.current_round)
        # Public market — everyone hears everything
        return [a for a in self.agent_ids if a != speaker]

    def advance(self) -> None:
        if self.simultaneous:
            speaker = self.get_next_speaker()
            if speaker:
                self._acted_this_round.add(speaker)
            if len(self._acted_this_round) >= len(self.agent_ids):
                self._acted_this_round.clear()
                self.current_round += 1
        else:
            self._turn_index += 1
            if self._turn_index >= len(self.agent_ids):
                self._turn_index = 0
                self.current_round += 1

    def reset(self) -> None:
        super().reset()
        self._acted_this_round.clear()
        self._turn_index = 0
