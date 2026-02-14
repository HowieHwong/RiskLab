=====================
Architecture Overview
=====================

RiskLab models multi-agent interactions as a **five-tuple**:

.. code-block:: text

   Experiment = (Topology, Environment, Protocol, Agent, Task)

.. code-block:: text

   ┌──────────────────────────────────────────────────┐
   │                 ExperimentRunner                  │
   │                                                  │
   │  ┌──────────┐  ┌─────────────┐  ┌────────────┐  │
   │  │ Topology │  │ Environment │  │  Protocol  │  │
   │  └────┬─────┘  └──────┬──────┘  └─────┬──────┘  │
   │       │               │               │         │
   │       ▼               ▼               ▼         │
   │  ┌─────────────────────────────────────────┐     │
   │  │              Agent Pool                 │     │
   │  │  ┌───────┐ ┌───────┐ ┌───────┐        │     │
   │  │  │Agent 0│ │Agent 1│ │Agent 2│  ...   │     │
   │  │  └───────┘ └───────┘ └───────┘        │     │
   │  └─────────────────────────────────────────┘     │
   │       │                                          │
   │       ▼                                          │
   │  ┌──────────┐  ┌────────────┐                    │
   │  │  Risks   │  │ Evaluation │                    │
   │  └──────────┘  └────────────┘                    │
   └──────────────────────────────────────────────────┘

Components
----------

**Topology**
   Defines who can communicate with whom via an adjacency matrix.
   Supports static graphs, dynamic (time-varying) topologies, and
   information flow ordering (parallel stages, cyclic/acyclic modes).

**Environment**
   Maintains shared world state (e.g., market prices, resource pools).
   Produces observations and updates state after each round.

**Protocol**
   Controls message routing: sequential turn-taking, broadcast, or
   market clearing.

**Agent**
   Wraps an LLM with a persona, objective, and memory. Objectives can be
   ``selfish``, ``cooperative``, or ``system``-defined.

**Task**
   Specifies scenario inputs (e.g., resource allocations, product listings)
   and termination criteria.

Execution Flow
--------------

1. Config loader parses YAML into typed dataclasses
2. ``build_experiment_from_config()`` instantiates all components
3. ``ExperimentRunner.run()`` enters the main loop:

   a. Topology determines information flow order
   b. Protocol delivers observations and collects actions
   c. Agents call the LLM and return responses
   d. Environment updates state
   e. Risk and evaluation metrics are recorded

4. Runner outputs aggregate results and trajectory logs

Cyclic vs. Acyclic Mode
~~~~~~~~~~~~~~~~~~~~~~~~

- **Cyclic** (default) — information circulates until a stop condition is met.
  Suitable for negotiation and deliberation tasks.
- **Acyclic** — information flows in a single pass per round.
  Suitable for pipeline or relay tasks.

Registry Pattern
----------------

Agents, risks, and environments use a registry for extensibility:

.. code-block:: python

   from risklab.agents.registry import AgentRegistry
   from risklab.agents.base import Agent

   @AgentRegistry.register("my_agent")
   class MyAgent(Agent):
       def act(self, observation: dict) -> dict:
           ...

Any registered class can be referenced by name in YAML configs.
