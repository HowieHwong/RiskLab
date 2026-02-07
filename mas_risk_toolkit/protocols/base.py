"""
Base InteractionProtocol abstraction.

This is the *soul* of the toolkit: a Protocol defines
**who speaks, when, and who hears**.

The same task + different protocol ⇒ different risk profile.

A protocol can operate in two modes:
    1. **Standalone** — turn order and visibility are hardcoded in the subclass
       (backward compatible with the original design).
    2. **Topology-driven** — a ``CommunicationTopology`` + ``InformationFlowConfig``
       supply the adjacency matrix and flow rules; the protocol merely enforces
       them at runtime.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from mas_risk_toolkit.topology import CommunicationTopology, InformationFlowConfig


@dataclass
class Message:
    """A single message within the interaction."""

    sender: str
    receivers: List[str]
    content: Any
    round: int
    metadata: Dict[str, Any] = field(default_factory=dict)


class InteractionProtocol(ABC):
    """Abstract base class for all interaction protocols.

    A protocol governs the turn order, visibility, and message routing
    among agents within an environment.

    Key design principle:
        Protocol is **swappable** — the same environment and agent set
        can be run under different protocols to study how interaction
        structure shapes emergent risk.

    Parameters
    ----------
    agent_ids : list[str]
        All agent identifiers participating in the protocol.
    topology : CommunicationTopology, optional
        If provided, ``get_listeners`` defaults to the adjacency matrix.
    flow : InformationFlowConfig, optional
        If provided, the protocol uses entry/exit/stop rules from the flow.
    """

    def __init__(
        self,
        agent_ids: List[str],
        topology: Optional["CommunicationTopology"] = None,
        flow: Optional["InformationFlowConfig"] = None,
        **kwargs: Any,
    ) -> None:
        self.agent_ids = list(agent_ids)
        self.topology = topology
        self.flow = flow
        self.current_round: int = 0
        self.message_count: int = 0
        self.message_log: List[Message] = []

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    @abstractmethod
    def get_next_speaker(self) -> Optional[str]:
        """Return the agent_id of the next speaker, or ``None`` if the
        round / episode is over."""
        ...

    def get_listeners(self, speaker: str) -> List[str]:
        """Return the list of agent_ids that can hear *speaker*'s message.

        Default behaviour:
            - If a topology is attached, use the adjacency matrix.
            - Otherwise, subclasses must override.
        """
        if self.topology is not None:
            return self.topology.get_receivers(speaker, t=self.current_round)
        raise NotImplementedError(
            "Either provide a topology or override get_listeners() in the subclass."
        )

    @abstractmethod
    def advance(self) -> None:
        """Advance the internal turn / round pointer."""
        ...

    def is_round_over(self) -> bool:
        """Return True if all agents scheduled for the current round have
        spoken."""
        return self.get_next_speaker() is None

    def should_stop(self) -> bool:
        """Check stop conditions from the information flow config.

        Returns ``False`` if no flow config is attached (the caller
        controls termination externally).
        """
        if self.flow is None:
            return False
        context = {
            "current_round": self.current_round,
            "message_count": self.message_count,
            "last_speaker": (
                self.message_log[-1].sender if self.message_log else None
            ),
        }
        return self.flow.should_stop(context)

    def route_message(self, message: Message) -> None:
        """Record and route a message according to protocol rules."""
        self.message_log.append(message)
        self.message_count += 1

    def reset(self) -> None:
        """Reset the protocol state for a new episode."""
        self.current_round = 0
        self.message_count = 0
        self.message_log.clear()

    def get_message_log(self) -> List[Message]:
        """Return the complete message log."""
        return list(self.message_log)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(agents={self.agent_ids}, "
            f"round={self.current_round}, topology={'yes' if self.topology else 'no'})"
        )
