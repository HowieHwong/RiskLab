========
Topology
========

The topology module defines **who can talk to whom** and **in what order**.

CommunicationTopology
---------------------

An adjacency-matrix representation of agent connectivity. You can
initialize a topology in three ways: fully connected (default), from an
explicit adjacency matrix, or from a list of edges. Set ``directed=True``
(the default) for asymmetric channels.

.. code-block:: python

   from risklab.topology import CommunicationTopology

   # Default: fully connected (no self-loops)
   topo = CommunicationTopology(agent_ids=["A", "B", "C"])

   # Custom adjacency matrix
   topo = CommunicationTopology(
       agent_ids=["A", "B", "C"],
       adjacency_matrix=[
           [0, 1, 1],
           [1, 0, 1],
           [1, 1, 0],
       ],
       directed=True,             # default
   )

   # From edge list
   topo = CommunicationTopology.from_edges(
       agent_ids=["A", "B", "C"],
       edges=[("A", "B"), ("B", "C"), ("C", "A")],
   )

   # Query connectivity
   topo.can_send("A", "C")        # bool — can A send to C?
   topo.get_receivers("A")        # list[str] — who can A reach?
   topo.get_senders("C")          # list[str] — who can send to C?
   topo.in_degree("C")            # int — incoming edge count
   topo.out_degree("A")           # int — outgoing edge count

TimeVaryingTopology
-------------------

Some experiments require connectivity that evolves over time — for instance
a communication channel that opens or closes at a specific round.
``TimeVaryingTopology`` extends ``CommunicationTopology`` by accepting
per-timestep adjacency overrides via ``set_schedule``.

.. code-block:: python

   from risklab.topology import TimeVaryingTopology

   tvt = TimeVaryingTopology(agent_ids=["A", "B", "C"])

   # Override adjacency at specific time steps
   tvt.set_schedule(t=5, matrix=[
       [0, 1, 0],
       [0, 0, 1],
       [1, 0, 0],
   ])

   tvt.can_send("A", "B", t=3)    # uses base (default) matrix
   tvt.can_send("A", "B", t=5)    # uses scheduled override

InformationFlowConfig
---------------------

Controls the execution order within each round. An **acyclic** flow runs a
single pass through the pipeline; a **cyclic** flow (the default) repeats
until a stop condition is satisfied. Use nested lists in ``flow_order`` to
express parallel stages.

.. code-block:: python

   from risklab.topology import InformationFlowConfig

   # Acyclic — one-shot pipeline
   flow = InformationFlowConfig(
       entry_nodes=["user"],
       exit_nodes=["summary"],
       flow_order=["user", ["A", "B"], "summary"],  # parallel stage
       cyclic=False,
   )

   # Cyclic (default) — loops until stop condition
   flow = InformationFlowConfig(
       entry_nodes=["user"],
       exit_nodes=["user"],
       flow_order=["user", ["img", "txt"], "summary", "user"],
       cyclic=True,
       stop_conditions=[
           StopCondition(StopConditionType.MAX_ROUNDS, {"value": 10})
       ],
   )

Stop condition types: ``max_rounds``, ``max_messages``, ``convergence``,
``node_reached``, ``custom``.

YAML Configuration
------------------

Topologies and flows can be specified entirely in YAML. Provide either
``matrix``, ``edges``, or neither (fully connected) to define the graph.

.. code-block:: yaml

   topology:
     agents: ["A", "B", "C"]
     directed: true
     matrix:                       # or use edges, or omit for fully connected
       - [0, 1, 1]
       - [1, 0, 1]
       - [1, 1, 0]
     flow:
       entry_nodes: ["A"]
       exit_nodes: ["A"]
       cyclic: true
       stop_conditions:
         - type: max_rounds
           value: 5

``build_topology_from_config`` converts this YAML structure into
``CommunicationTopology`` and ``InformationFlowConfig`` objects:

.. code-block:: python

   from risklab.topology import build_topology_from_config

   topo, flow = build_topology_from_config(config_dict)
