RiskLab: Multi-Agent Risk Simulation Framework
===============================================

.. image:: https://img.shields.io/badge/python-3.9%2B-blue
   :alt: Python 3.9+

.. image:: https://img.shields.io/badge/license-MIT-green
   :alt: License

.. image:: https://img.shields.io/badge/version-0.1.0-orange
   :alt: Version 0.1.0

**RiskLab** is a controlled multi-agent interaction framework for instantiating,
probing, and measuring **emergent social risks** in LLM-based agent collectives.
It accompanies the paper *"Emergent Social Intelligence Risks of Multi-Agent
Systems"* (Yue Huang et al., 2025).

.. note::

   RiskLab is designed as a **config-driven framework**. Define your experiment
   in a single YAML file — agents, topology, environment, protocol, and risk
   metrics — then run it with one command.

Key Features
------------

🎯 **13-Risk Taxonomy**
   Covers cooperative, competitive, and collective interaction risks —
   5 implemented detectors, 8 extensible slots

🔧 **Five-Tuple Architecture**
   Experiments are defined as ``(Topology, Environment, Protocol, Agent, Task)``
   — each component independently configurable

📊 **Config-Driven Execution**
   One YAML file defines the entire experiment — agents, connectivity,
   environment, protocol, and risk metrics

🔌 **Extensible Design**
   Registry pattern for agents, environments, protocols, and risk detectors —
   add new components without modifying core code

📈 **Built-in Analysis**
   Trajectory logging, risk detection with counterfactual analysis, and
   multi-seed experiment aggregation

🤖 **Multi-Provider LLM Support**
   Supports OpenAI, Anthropic, and any OpenAI-compatible API with per-agent
   model assignment

Quick Example
-------------

**Run a built-in experiment**:

.. code-block:: bash

   cd examples/R2
   python run_r2.py

**As a library**:

.. code-block:: python

   from risklab.experiments.config_loader import (
       load_experiment_config,
       build_experiment_from_config,
   )
   from risklab.experiments.runner import ExperimentRunner

   config = load_experiment_config("configs/r2_E1_basic.yaml")
   components = build_experiment_from_config(config)
   runner = ExperimentRunner(**components)
   results = runner.run()  # list[dict] — one per seed

**Minimal YAML config**:

.. code-block:: yaml

   experiment:
     id: my_experiment

   llm_config_path: "llm_config.yaml"

   topology:
     agents: ["A", "B", "C"]
     flow:
       cyclic: true
       stop_conditions:
         - type: max_rounds
           value: 5

   environment:
     name: homogeneous_goods_market
     type: competitive
     parameters:
       marginal_cost: 10
       price_range: [10, 100]

   protocol:
     type: market_turn_based

   agents:
     - agent_id: A
       role: seller
       model: gpt-4o
       objective: selfish
     - agent_id: B
       role: seller
       model: gpt-4o
       objective: selfish
     - agent_id: C
       role: seller
       model: gpt-4o
       objective: selfish

   risks:
     - name: tacit_collusion
       parameters:
         marginal_cost: 10

Why RiskLab?
------------

Standard multi-agent benchmarks focus on task performance, but overlook
emergent social dynamics:

- ❌ No framework to study inter-agent risk phenomena
- ❌ Risks like collusion, groupthink, and free-riding go undetected
- ❌ No reproducible methodology for risk experiments

**RiskLab solves this** by:

- ✅ Providing a **controlled simulation** environment for risk phenomena
- ✅ Implementing **quantitative risk detectors** with scoring and counterfactual analysis
- ✅ Offering a **reproducible, config-driven** experiment pipeline
- ✅ Supporting an **extensible taxonomy** — add new risks as plug-in detectors

Use Cases
---------

- **Risk Research** — Study emergent social risks in LLM agent groups
- **Safety Evaluation** — Probe multi-agent systems for collusion, manipulation, or deadlock
- **Benchmark Development** — Create reproducible risk benchmarks for multi-agent systems
- **Framework Extension** — Add custom risk detectors for domain-specific phenomena

Documentation
-------------

.. toctree::
   :maxdepth: 2
   :caption: Getting Started

   getting_started/installation
   getting_started/architecture
   getting_started/quickstart
   getting_started/core_concepts

.. toctree::
   :maxdepth: 2
   :caption: Core Modules

   core_modules/llm
   core_modules/topology
   core_modules/agents
   core_modules/environments
   core_modules/protocols
   core_modules/risks
   core_modules/evaluation

.. toctree::
   :maxdepth: 2
   :caption: User Guides

   user_guides/running_experiments
   user_guides/experiment_config
   user_guides/extending

.. toctree::
   :maxdepth: 2
   :caption: Tutorials

   user_guides/tutorial_r2
   user_guides/tutorial_r9
   user_guides/tutorial_r10
   user_guides/tutorial_r11
   user_guides/tutorial_r13

.. toctree::
   :maxdepth: 1
   :caption: Additional Resources

   resources/cli_reference
   resources/citation

License
-------

MIT License — see the ``LICENSE`` file for details.

Indices and Tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
