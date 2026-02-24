"""
Communication Topology & Information Flow.

Maps directly to the paper's formal framework:
    C : N × N × ℕ → {0,1}
    G_t = (N, E_t)  where (i,j) ∈ E_t  iff  C(i,j,t) = 1

Two complementary concepts:
    1. **CommunicationTopology** — adjacency-matrix based graph that defines
       which agents can send messages to which agents.
    2. **InformationFlow** — higher-level specification of entry points,
       flow direction, exit points, stop conditions, and triggers.

Flow ordering supports **parallel stages** via nested lists::

    flow_order = ["user", ["A", "B", "C"], "summary"]

    Stage 0: "user" speaks
    Stage 1: "A", "B", "C" speak in parallel (same level)
    Stage 2: "summary" speaks

Multiple independent information paths can be declared via ``flows``.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union


# ======================================================================
# Type aliases for flow ordering
# ======================================================================

# A FlowStage is either a single agent (str) or a parallel group (list[str])
FlowStage = Union[str, List[str]]

# A FlowOrder is a sequence of stages
FlowOrder = List[FlowStage]


# ======================================================================
# Communication Topology (adjacency matrix)
# ======================================================================

class CommunicationTopology:
    """Adjacency-matrix representation of the agent communication graph.

    Parameters
    ----------
    agent_ids : list[str]
        Ordered list of agent identifiers.  The ordering defines row/column
        indices in the adjacency matrix.
    adjacency_matrix : list[list[int]] | None
        ``n × n`` binary matrix where ``matrix[i][j] = 1`` means agent *i*
        can send a message to agent *j*.  ``None`` → fully connected
        (every pair except self-loops).
    directed : bool
        If ``False``, edges are treated as bidirectional; setting
        ``matrix[i][j]`` also sets ``matrix[j][i]``.

    Examples
    --------
    Paper's two-line notation for Risk 2 (Tacit Collusion):

        User → S1;  S1 → S2, S3;  S2 → S1, S3;  S3 → S1, S2

    >>> topo = CommunicationTopology(
    ...     agent_ids=["user", "S1", "S2", "S3"],
    ...     adjacency_matrix=[
    ...         [0, 1, 0, 0],   # user → S1
    ...         [0, 0, 1, 1],   # S1   → S2, S3
    ...         [0, 1, 0, 1],   # S2   → S1, S3
    ...         [0, 1, 1, 0],   # S3   → S1, S2
    ...     ],
    ... )
    """

    def __init__(
        self,
        agent_ids: List[str],
        adjacency_matrix: Optional[List[List[int]]] = None,
        directed: bool = True,
    ) -> None:
        self.agent_ids = list(agent_ids)
        self.n = len(self.agent_ids)
        self.directed = directed
        self._id_to_idx: Dict[str, int] = {
            aid: i for i, aid in enumerate(self.agent_ids)
        }

        if adjacency_matrix is not None:
            self._validate_matrix(adjacency_matrix)
            self._matrix = [list(row) for row in adjacency_matrix]
        else:
            # Default: fully connected (no self-loops)
            self._matrix = [
                [1 if i != j else 0 for j in range(self.n)]
                for i in range(self.n)
            ]

        # Enforce symmetry for undirected graphs
        if not directed:
            for i in range(self.n):
                for j in range(i + 1, self.n):
                    val = max(self._matrix[i][j], self._matrix[j][i])
                    self._matrix[i][j] = val
                    self._matrix[j][i] = val

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_matrix(self, matrix: List[List[int]]) -> None:
        if len(matrix) != self.n:
            raise ValueError(
                f"Adjacency matrix has {len(matrix)} rows but "
                f"{self.n} agents were specified."
            )
        for i, row in enumerate(matrix):
            if len(row) != self.n:
                raise ValueError(
                    f"Row {i} has {len(row)} columns; expected {self.n}."
                )

    # ------------------------------------------------------------------
    # Core queries — corresponds to C(i, j, t)
    # ------------------------------------------------------------------

    def can_send(self, sender: str, receiver: str, t: Optional[int] = None) -> bool:
        """Return ``True`` if *sender* can send a message to *receiver*.

        The optional *t* parameter is reserved for time-varying topologies
        (subclasses may override).
        """
        i = self._id_to_idx[sender]
        j = self._id_to_idx[receiver]
        return bool(self._matrix[i][j])

    def get_receivers(self, sender: str, t: Optional[int] = None) -> List[str]:
        """Return all agents that *sender* can reach."""
        i = self._id_to_idx[sender]
        return [
            self.agent_ids[j]
            for j in range(self.n)
            if self._matrix[i][j]
        ]

    def get_senders(self, receiver: str, t: Optional[int] = None) -> List[str]:
        """Return all agents that can send messages to *receiver*."""
        j = self._id_to_idx[receiver]
        return [
            self.agent_ids[i]
            for i in range(self.n)
            if self._matrix[i][j]
        ]

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def set_edge(self, sender: str, receiver: str, value: int = 1) -> None:
        """Set or remove an edge in the topology."""
        i = self._id_to_idx[sender]
        j = self._id_to_idx[receiver]
        self._matrix[i][j] = value
        if not self.directed:
            self._matrix[j][i] = value

    def remove_edge(self, sender: str, receiver: str) -> None:
        """Remove an edge from the topology."""
        self.set_edge(sender, receiver, 0)

    # ------------------------------------------------------------------
    # Serialisation & introspection
    # ------------------------------------------------------------------

    def get_adjacency_matrix(self) -> List[List[int]]:
        """Return a copy of the adjacency matrix."""
        return [list(row) for row in self._matrix]

    def get_edges(self) -> List[Tuple[str, str]]:
        """Return a list of ``(sender, receiver)`` edge tuples."""
        edges = []
        for i in range(self.n):
            for j in range(self.n):
                if self._matrix[i][j]:
                    edges.append((self.agent_ids[i], self.agent_ids[j]))
        return edges

    def in_degree(self, agent_id: str) -> int:
        """Number of agents that can send to *agent_id*."""
        return len(self.get_senders(agent_id))

    def out_degree(self, agent_id: str) -> int:
        """Number of agents that *agent_id* can reach."""
        return len(self.get_receivers(agent_id))

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-friendly dict."""
        return {
            "agent_ids": list(self.agent_ids),
            "directed": self.directed,
            "adjacency_matrix": self.get_adjacency_matrix(),
        }

    @classmethod
    def from_edges(
        cls,
        agent_ids: List[str],
        edges: List[Tuple[str, str]],
        directed: bool = True,
    ) -> "CommunicationTopology":
        """Construct from a list of ``(sender, receiver)`` pairs.

        Example
        -------
        >>> topo = CommunicationTopology.from_edges(
        ...     ["user", "A", "B", "C"],
        ...     [("user", "A"), ("A", "B"), ("B", "C"), ("C", "user")],
        ... )
        """
        n = len(agent_ids)
        idx = {aid: i for i, aid in enumerate(agent_ids)}
        matrix = [[0] * n for _ in range(n)]
        for s, r in edges:
            matrix[idx[s]][idx[r]] = 1
            if not directed:
                matrix[idx[r]][idx[s]] = 1
        return cls(agent_ids, matrix, directed=directed)

    def copy(self) -> "CommunicationTopology":
        """Return a deep copy."""
        return CommunicationTopology(
            agent_ids=list(self.agent_ids),
            adjacency_matrix=deepcopy(self._matrix),
            directed=self.directed,
        )

    def __repr__(self) -> str:
        edge_count = sum(sum(row) for row in self._matrix)
        return (
            f"CommunicationTopology(agents={self.agent_ids}, "
            f"edges={edge_count}, directed={self.directed})"
        )


# ======================================================================
# Time-Varying Topology
# ======================================================================

class TimeVaryingTopology(CommunicationTopology):
    """A topology that can change at each time step.

    Stores a base topology plus per-step overrides or a schedule function.
    """

    def __init__(
        self,
        agent_ids: List[str],
        adjacency_matrix: Optional[List[List[int]]] = None,
        directed: bool = True,
        schedule: Optional[Dict[int, List[List[int]]]] = None,
    ) -> None:
        super().__init__(agent_ids, adjacency_matrix, directed)
        # schedule: {time_step: adjacency_matrix_at_that_step}
        self._schedule: Dict[int, List[List[int]]] = schedule or {}

    def _get_matrix_at(self, t: Optional[int]) -> List[List[int]]:
        if t is not None and t in self._schedule:
            return self._schedule[t]
        return self._matrix

    def can_send(self, sender: str, receiver: str, t: Optional[int] = None) -> bool:
        mat = self._get_matrix_at(t)
        i = self._id_to_idx[sender]
        j = self._id_to_idx[receiver]
        return bool(mat[i][j])

    def get_receivers(self, sender: str, t: Optional[int] = None) -> List[str]:
        mat = self._get_matrix_at(t)
        i = self._id_to_idx[sender]
        return [self.agent_ids[j] for j in range(self.n) if mat[i][j]]

    def set_schedule(self, t: int, matrix: List[List[int]]) -> None:
        """Set a specific adjacency matrix for time step *t*."""
        self._validate_matrix(matrix)
        self._schedule[t] = [list(row) for row in matrix]


# ======================================================================
# Stop Conditions
# ======================================================================

class StopConditionType(str, Enum):
    """Built-in stop condition types."""
    MAX_ROUNDS = "max_rounds"
    MAX_MESSAGES = "max_messages"
    CONVERGENCE = "convergence"
    NODE_REACHED = "node_reached"
    CUSTOM = "custom"


@dataclass
class StopCondition:
    """A single termination condition for the information flow.

    Parameters
    ----------
    condition_type : StopConditionType
        The kind of stop condition.
    parameters : dict
        Type-specific parameters, e.g. ``{"value": 10}`` for max_rounds.
    """
    condition_type: StopConditionType
    parameters: Dict[str, Any] = field(default_factory=dict)

    def is_met(self, context: Dict[str, Any]) -> bool:
        """Evaluate whether this stop condition is satisfied.

        Parameters
        ----------
        context : dict
            Runtime context with keys such as ``current_round``,
            ``message_count``, ``last_speaker``, ``converged``, etc.
        """
        ct = self.condition_type

        if ct == StopConditionType.MAX_ROUNDS:
            return context.get("current_round", 0) >= self.parameters.get("value", 10)

        if ct == StopConditionType.MAX_MESSAGES:
            return context.get("message_count", 0) >= self.parameters.get("value", 50)

        if ct == StopConditionType.CONVERGENCE:
            return context.get("converged", False)

        if ct == StopConditionType.NODE_REACHED:
            target = self.parameters.get("node")
            return context.get("last_speaker") == target

        # CUSTOM: caller must evaluate externally
        return False


# ======================================================================
# Trigger Conditions
# ======================================================================

class TriggerType(str, Enum):
    """Built-in trigger types that start or restart the flow."""
    USER_INPUT = "user_input"
    ROUND_START = "round_start"
    EVENT = "event"
    CUSTOM = "custom"


@dataclass
class TriggerCondition:
    """A condition that starts or restarts information flow."""
    trigger_type: TriggerType
    parameters: Dict[str, Any] = field(default_factory=dict)


# ======================================================================
# Flow Stage helpers
# ======================================================================

def normalize_stage(raw: Any) -> FlowStage:
    """Coerce a raw YAML value into a proper FlowStage.

    - ``"A"``           → ``"A"``          (serial)
    - ``["A","B","C"]`` → ``["A","B","C"]``(parallel group)
    """
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return [str(x) for x in raw]
    raise TypeError(f"Invalid flow stage: {raw!r}")


def normalize_flow_order(raw: Optional[List[Any]]) -> Optional[FlowOrder]:
    """Convert a raw (possibly nested) list into a typed FlowOrder."""
    if raw is None:
        return None
    return [normalize_stage(s) for s in raw]


def stage_agents(stage: FlowStage) -> List[str]:
    """Return the list of agent_ids in a stage (always a list)."""
    if isinstance(stage, str):
        return [stage]
    return list(stage)


def is_parallel(stage: FlowStage) -> bool:
    """Return True if the stage is a parallel group."""
    return isinstance(stage, list)


def flatten_flow_order(flow_order: FlowOrder) -> List[str]:
    """Flatten a flow order into a single list of agent_ids."""
    result: List[str] = []
    for stage in flow_order:
        result.extend(stage_agents(stage))
    return result


# ======================================================================
# Named Flow Path (for multiple flows)
# ======================================================================

@dataclass
class FlowPath:
    """A single named information flow path.

    Used when an experiment has multiple concurrent or alternative
    information paths through the same topology.

    Examples
    --------
    Two divergent paths that share entry and converge::

        path_a = FlowPath("direct", ["user", "analyst", "report"])
        path_b = FlowPath("via_data", ["user", "data_collector", "analyst", "report"])
    """
    flow_id: str
    order: FlowOrder
    description: str = ""

    def __post_init__(self) -> None:
        self.order = normalize_flow_order(self.order) or []

    @property
    def stages(self) -> FlowOrder:
        return self.order

    @property
    def num_stages(self) -> int:
        return len(self.order)

    def flatten(self) -> List[str]:
        return flatten_flow_order(self.order)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "order": self.order,
            "description": self.description,
        }


# ======================================================================
# Information Flow
# ======================================================================

@dataclass
class InformationFlowConfig:
    """Complete specification of how information flows through the topology.

    This captures the *dynamic* aspects that complement the *static*
    adjacency matrix:
        - Where information enters the system (entry nodes)
        - How it propagates (flow order — with parallel stages)
        - Where it exits (exit nodes)
        - When a round / episode terminates (stop conditions)
        - What triggers the flow to begin (trigger conditions)

    ``flow_order`` supports **parallel stages** via nested lists::

        # Serial pipeline
        flow_order = ["user", "A", "B", "C"]

        # A, B, C receive from user simultaneously, then summary aggregates
        flow_order = ["user", ["A", "B", "C"], "summary"]

        # Mixed: user → (A and B in parallel) → C → (D and E in parallel)
        flow_order = ["user", ["A", "B"], "C", ["D", "E"]]

    For multiple independent information paths, use ``flows``::

        flows = [
            FlowPath("direct",   ["user", "analyst", "report"]),
            FlowPath("via_data", ["user", "collector", "analyst", "report"]),
        ]

    Cyclic vs Acyclic
    ------------------
    ``cyclic=True`` (default):  The flow forms a loop — entry and exit nodes
    must overlap.  The runner keeps looping until a ``stop_condition`` fires.

    ``cyclic=False``:  The flow is a one-shot pipeline from entry to exit.
    Inputs are provided externally (inline list or JSON file) and the pipeline
    is run once per input.

    Examples
    --------
    Risk 1 (Resource Overreach) — cyclic fan-out / fan-in::

        >>> flow = InformationFlowConfig(
        ...     entry_nodes=["user"],
        ...     exit_nodes=["user"],
        ...     flow_order=["user", ["img", "txt", "vid", "code", "voice"], "summary", "user"],
        ...     cyclic=True,  # entry == exit, loops
        ... )

    Risk 13 (Excessive Rigidity) — sequential trading pipeline::

        >>> flow = InformationFlowConfig(
        ...     entry_nodes=["analyst"],
        ...     exit_nodes=["analyst"],
        ...     flow_order=["analyst", "strategy_planner", "trade_execution"],
        ...     cyclic=True,
        ... )
    """

    entry_nodes: List[str]
    exit_nodes: List[str]
    flow_order: Optional[FlowOrder] = None
    flows: Optional[List[FlowPath]] = None  # multiple named sub-flows
    stop_conditions: List[StopCondition] = field(default_factory=list)
    trigger: Optional[TriggerCondition] = None
    cyclic: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Normalize flow_order on init
        if self.flow_order is not None:
            self.flow_order = normalize_flow_order(self.flow_order)
        # Validate cyclic constraint
        if self.cyclic:
            overlap = set(self.entry_nodes) & set(self.exit_nodes)
            if not overlap:
                raise ValueError(
                    f"Cyclic flow requires at least one node to appear in both "
                    f"entry_nodes ({self.entry_nodes}) and exit_nodes "
                    f"({self.exit_nodes})."
                )

    # ------------------------------------------------------------------
    # Stage iteration helpers
    # ------------------------------------------------------------------

    @property
    def stages(self) -> FlowOrder:
        """Return the flow stages (from flow_order or first flow in flows)."""
        if self.flow_order is not None:
            return self.flow_order
        if self.flows:
            return self.flows[0].order
        return []

    @property
    def num_stages(self) -> int:
        return len(self.stages)

    def get_stage(self, index: int) -> FlowStage:
        """Get the stage at a given index."""
        return self.stages[index]

    def get_stage_agents(self, index: int) -> List[str]:
        """Get the list of agent_ids at a given stage index."""
        return stage_agents(self.stages[index])

    def is_parallel_stage(self, index: int) -> bool:
        """Return True if the stage at *index* is a parallel group."""
        return is_parallel(self.stages[index])

    def flatten(self) -> List[str]:
        """Flatten the primary flow into a single agent list."""
        return flatten_flow_order(self.stages)

    def get_flow(self, flow_id: str) -> Optional[FlowPath]:
        """Retrieve a named sub-flow by its ID."""
        if self.flows:
            for fp in self.flows:
                if fp.flow_id == flow_id:
                    return fp
        return None

    # ------------------------------------------------------------------
    # Stop / trigger
    # ------------------------------------------------------------------

    def should_stop(self, context: Dict[str, Any]) -> bool:
        """Return ``True`` if *any* stop condition is met."""
        return any(sc.is_met(context) for sc in self.stop_conditions)

    def is_entry(self, agent_id: str) -> bool:
        return agent_id in self.entry_nodes

    def is_exit(self, agent_id: str) -> bool:
        return agent_id in self.exit_nodes

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "entry_nodes": self.entry_nodes,
            "exit_nodes": self.exit_nodes,
            "flow_order": self.flow_order,
            "cyclic": self.cyclic,
            "stop_conditions": [
                {"type": sc.condition_type.value, **sc.parameters}
                for sc in self.stop_conditions
            ],
            "trigger": (
                {"type": self.trigger.trigger_type.value, **self.trigger.parameters}
                if self.trigger
                else None
            ),
        }
        if self.flows:
            d["flows"] = [fp.to_dict() for fp in self.flows]
        return d


# ======================================================================
# Convenience factory
# ======================================================================

def build_topology_from_config(config: Dict[str, Any]) -> Tuple[CommunicationTopology, InformationFlowConfig]:
    """Build a topology and information flow from a YAML-like dict.

    Supports both flat and nested ``flow_order``::

        # flat (serial)
        "flow_order": ["user", "A", "B", "C"]

        # nested (parallel stages)
        "flow_order":
          - "user"
          - ["A", "B", "C"]
          - "summary"

    Supports multiple named flows::

        "flows":
          - flow_id: "direct"
            order: ["user", "analyst", "report"]
          - flow_id: "via_data"
            order: ["user", "collector", "analyst", "report"]
    """
    agents = config["agents"]
    directed = config.get("directed", True)

    # Build topology from matrix or edge list
    if "matrix" in config:
        topo = CommunicationTopology(agents, config["matrix"], directed=directed)
    elif "edges" in config:
        edges = [tuple(e) for e in config["edges"]]
        topo = CommunicationTopology.from_edges(agents, edges, directed=directed)
    else:
        topo = CommunicationTopology(agents, directed=directed)  # fully connected

    # Build information flow
    flow_cfg = config.get("flow", {})

    stop_conditions = []
    for sc in flow_cfg.get("stop_conditions", []):
        sc_copy = dict(sc)
        sc_type = StopConditionType(sc_copy.pop("type"))
        stop_conditions.append(StopCondition(sc_type, sc_copy))

    trigger = None
    if "trigger" in flow_cfg:
        tr = dict(flow_cfg["trigger"])
        tr_type = TriggerType(tr.pop("type"))
        trigger = TriggerCondition(tr_type, tr)

    # Parse flow_order (may contain nested lists)
    raw_flow_order = flow_cfg.get("flow_order")
    flow_order = normalize_flow_order(raw_flow_order)

    # Parse multiple flows
    raw_flows = flow_cfg.get("flows")
    flows: Optional[List[FlowPath]] = None
    if raw_flows:
        flows = []
        for rf in raw_flows:
            flows.append(FlowPath(
                flow_id=rf.get("flow_id", f"flow_{len(flows)}"),
                order=rf.get("order", []),
                description=rf.get("description", ""),
            ))

    flow = InformationFlowConfig(
        entry_nodes=flow_cfg.get("entry_nodes", [agents[0]]),
        exit_nodes=flow_cfg.get("exit_nodes", [agents[-1]]),
        flow_order=flow_order,
        flows=flows,
        stop_conditions=stop_conditions,
        trigger=trigger,
        cyclic=flow_cfg.get("cyclic", True),
    )

    return topo, flow
