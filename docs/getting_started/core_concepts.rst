=============
Core Concepts
=============

Risk Taxonomy
-------------

The accompanying paper defines a **13-risk taxonomy** organized into three
interaction categories: cooperative, competitive, and collective. RiskLab
provides the infrastructure to study any of these risks through a unified
experiment framework.

To help new users get started, **5 reference detectors** are included as
working examples. These demonstrate how to implement the ``Risk`` interface
and can serve as templates when building your own detectors for other risks
in the taxonomy.

Reference Detectors (Included)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following detectors ship with RiskLab out of the box. Each one
illustrates a different detection strategy and can be used as a starting
point for your own implementations.

.. list-table::
   :header-rows: 1
   :widths: 5 22 15 58

   * - ID
     - Risk
     - Category
     - What it demonstrates
   * - R2
     - Tacit Collusion
     - Competitive
     - Price convergence detection via similarity metrics and
       counterfactual analysis
   * - R3 / R13
     - Role Rigidity
     - Cooperative
     - Behavioral inflexibility measurement — tracks how much an
       agent's strategy changes (or fails to change) over rounds
   * - R9
     - Strategic Misreporting
     - Competitive
     - Information distortion detection — compares reported values
       against ground truth
   * - R10
     - Normative Deadlock
     - Collective
     - Loop detection on group decision processes — identifies when
       agents get stuck in unproductive cycles

Full 13-Risk Taxonomy
~~~~~~~~~~~~~~~~~~~~~

The complete taxonomy from the paper is listed below. Risks without built-in
detectors can be implemented by subclassing ``Risk`` and registering via
``RiskRegistry`` (see **Extending the Framework**).

.. list-table::
   :header-rows: 1
   :widths: 5 25 18

   * - ID
     - Risk
     - Category
   * - R1
     - Trust Exploitation
     - Cooperative
   * - R2
     - Tacit Collusion
     - Competitive
   * - R3
     - Role Rigidity
     - Cooperative
   * - R4
     - Resource Hoarding
     - Competitive
   * - R5
     - Free-Riding
     - Cooperative
   * - R6
     - Semantic Drift
     - Cooperative
   * - R7
     - Echo Chamber
     - Collective
   * - R8
     - Groupthink
     - Collective
   * - R9
     - Strategic Misreporting
     - Competitive
   * - R10
     - Normative Deadlock
     - Collective
   * - R11
     - Blame Shifting
     - Cooperative
   * - R12
     - Gatekeeping
     - Competitive
   * - R13
     - Commitment & Rigidity
     - Mixed

Interaction Categories
~~~~~~~~~~~~~~~~~~~~~~

**Cooperative** — Agents work toward shared goals. Risks arise from
coordination failures, cultural friction, or information distortion.

**Competitive** — Agents pursue individual advantage. Risks include
collusion, exploitation of information asymmetry, and strategic deception.

**Collective** — Agents participate in group-level processes. Risks emerge
from normative deadlock, groupthink, and echo chambers.

Key Abstractions
----------------

CommunicationTopology
~~~~~~~~~~~~~~~~~~~~~

An adjacency-matrix representation of agent connectivity. Topologies are
specified by providing ``agents`` (list of IDs) plus ``matrix``, ``edges``,
or neither (defaults to fully connected). The ``directed`` flag controls
whether edges are unidirectional.

InformationFlowConfig
~~~~~~~~~~~~~~~~~~~~~

Controls execution order within a round. Supports sequential stages,
parallel stages (nested lists), and stop conditions (``max_rounds``,
``max_messages``, ``convergence``, ``node_reached``, ``custom``).
Default mode is **cyclic** — the flow loops between entry and exit nodes
until a stop condition is satisfied.

TaskConfig
~~~~~~~~~~

Defines scenario inputs and parameters passed to the environment and agents:

.. code-block:: python

   # TaskConfig fields
   task_id: str              # unique identifier
   task_type: TaskType       # e.g., MARKET_TRADING, NEGOTIATION
   description: str          # free-text description
   parameters: dict          # task-specific key-value pairs
   success_criteria: dict    # task success definition
   constraints: dict         # task constraints
   inputs: list | None       # inline per-agent input data
   input_file: str | None    # or load from file

Risk Detectors
~~~~~~~~~~~~~~

Every risk detector extends the ``Risk`` base class with two methods.
This is all you need to implement to add a new risk to the taxonomy:

.. code-block:: python

   from risklab.risks.base import Risk

   class MyRisk(Risk):
       def detect(self, trajectory) -> bool:
           """Return True if the risk is present."""
           ...

       def score(self, trajectory) -> float:
           """Return severity score in [0, 1]."""
           ...

Register your detector, and it becomes available in YAML configs:

.. code-block:: python

   from risklab.risks.registry import RiskRegistry

   RiskRegistry.register("my_risk")(MyRisk)
