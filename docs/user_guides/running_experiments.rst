=====================
Running Experiments
=====================

Using Example Scripts
---------------------

The quickest way to run an experiment is through one of the bundled scripts
in ``examples/``. Each script loads a pre-configured YAML file, runs the
experiment, and writes results to ``results/``.

.. code-block:: bash

   # Tacit collusion (R2)
   cd examples/R2
   python run_r2.py

   # Rigidity & commitment (R13)
   cd examples/R13
   python run_r13.py

Each script loads configs from its ``configs/`` subdirectory and writes
results to ``results/``.

Using the Python API
--------------------

For full programmatic control, use ``config_loader`` and
``ExperimentRunner`` directly. This lets you modify components in code
before running, or integrate experiments into larger pipelines.

.. code-block:: python

   from risklab.experiments.config_loader import (
       load_experiment_config,
       build_experiment_from_config,
   )
   from risklab.experiments.runner import ExperimentRunner

   # Load and build
   config = load_experiment_config("path/to/config.yaml")
   components = build_experiment_from_config(config)

   # Run
   runner = ExperimentRunner(**components)
   results = runner.run()       # returns list[dict], one per seed

   # Access results
   for result in results:
       print(result["risk_results"])    # {risk_id: {detected, score, ...}}
       print(result["metric_results"])  # {metric_name: value}
       print(result["task_result"])     # task evaluation or None

Multi-Seed Runs
---------------

LLM outputs are stochastic. Running with multiple seeds produces
independent repetitions so you can measure variance.

.. code-block:: python

   results = runner.run(num_seeds=5)   # 5 independent runs

Output Structure
----------------

.. code-block:: text

   results/
   ├── ExperimentId_aggregate.json         # all seed results
   └── trajectories/
       ├── ExperimentId_seed0_cyclic.json
       ├── ExperimentId_seed1_cyclic.json
       └── ExperimentId_seed2_cyclic.json

- **Aggregate file** — list of result dicts with ``risk_results``,
  ``metric_results``, ``task_result``, ``num_rounds``, ``seed``, ``failure``
- **Trajectory files** — full message logs for replay and analysis

Inspecting Configs
------------------

Validate and preview a config before running:

.. code-block:: bash

   python -m risklab.inspect_config path/to/config.yaml -A

See CLI Reference for all inspector flags.
