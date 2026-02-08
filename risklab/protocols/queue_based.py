"""
Queue-Based Execution Protocol.

Agents are ordered in a FIFO queue; execution is sequential.
Supports fee-based priority manipulation (GUARANTEE).

Triggers risks such as:
    - Priority monopolisation
    - Coalition resource capture
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any, Deque, List, Optional

from risklab.protocols.base import InteractionProtocol

if TYPE_CHECKING:
    from risklab.topology import CommunicationTopology, InformationFlowConfig


class QueueBasedExecution(InteractionProtocol):
    """FIFO queue with optional priority-guarantee mechanism.

    If a topology is attached, ``get_listeners`` uses the adjacency matrix.
    """

    def __init__(
        self,
        agent_ids: List[str],
        guarantee_enabled: bool = True,
        guarantee_fee: float = 0.0,
        topology: Optional["CommunicationTopology"] = None,
        flow: Optional["InformationFlowConfig"] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(agent_ids, topology=topology, flow=flow, **kwargs)
        self.guarantee_enabled = guarantee_enabled
        self.guarantee_fee = guarantee_fee
        self.queue: Deque[str] = deque(agent_ids)

    def get_next_speaker(self) -> Optional[str]:
        return self.queue[0] if self.queue else None

    def get_listeners(self, speaker: str) -> List[str]:
        if self.topology is not None:
            return self.topology.get_receivers(speaker, t=self.current_round)
        # Broadcast state to all agents after each execution
        return [a for a in self.agent_ids if a != speaker]

    def advance(self) -> None:
        if self.queue:
            finished = self.queue.popleft()
            self.queue.append(finished)
        self.current_round += 1

    def guarantee(self, guarantor: str, beneficiary: str) -> bool:
        """Move *beneficiary* to the front of the queue.

        The *guarantor* moves to the back.  Returns ``True`` on success.
        """
        if not self.guarantee_enabled:
            return False
        if beneficiary not in self.queue or guarantor not in self.queue:
            return False
        self.queue.remove(beneficiary)
        self.queue.appendleft(beneficiary)
        self.queue.remove(guarantor)
        self.queue.append(guarantor)
        return True

    def reset(self) -> None:
        super().reset()
        self.queue = deque(self.agent_ids)
