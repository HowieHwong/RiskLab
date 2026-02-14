=========
Protocols
=========

Protocols determine **how messages flow** between agents during each round.

Core Interface
--------------

Every protocol extends ``InteractionProtocol``, which manages turn order
and message delivery through four methods:

.. code-block:: python

   class InteractionProtocol(ABC):
       def get_next_speaker(self) -> str | None:
           """Return the next agent to speak, or None if the round is over."""

       def get_listeners(self, speaker: str) -> list[str]:
           """Return agents that can hear this speaker's message."""

       def advance(self) -> None:
           """Advance the internal turn / round pointer."""

       def route_message(self, message: Message) -> None:
           """Record and route a message."""

       def should_stop(self) -> bool:
           """Check stop conditions from the InformationFlowConfig."""

Messages are represented by the ``Message`` dataclass:

.. code-block:: python

   @dataclass
   class Message:
       sender: str
       receivers: list[str]
       content: Any
       round: int
       metadata: dict = field(default_factory=dict)

Built-in Protocols
------------------

**Sequential** (``sequential``)
   Agents take turns in a fixed order. Each agent sees messages from all
   preceding agents in the current round.

**Broadcast** (``broadcast``)
   Every message is visible to all agents. Simulates open group discussion.

**Market Turn-Based** (``market_turn_based``)
   Agents submit prices simultaneously (or sequentially). The protocol
   resolves market outcomes, updates balances, and broadcasts results.

**Queue-Based** (``queue_based``)
   Asynchronous per-agent queues in FIFO order. Available as a class but
   not wired into the config loader — instantiate directly in Python.

YAML Configuration
------------------

.. code-block:: yaml

   protocol:
     type: market_turn_based       # market_turn_based | sequential | broadcast
     simultaneous: true             # for market_turn_based only

Choosing a Protocol
-------------------

.. list-table::
   :header-rows: 1
   :widths: 25 35 40

   * - Config Type
     - Best For
     - Example Risks
   * - ``market_turn_based``
     - Pricing scenarios, auctions
     - Tacit collusion (R2)
   * - ``sequential``
     - Turn-based negotiation, relay
     - Semantic drift (R6), rigidity (R3)
   * - ``broadcast``
     - Group deliberation, voting
     - Groupthink (R8), echo chamber (R7)
