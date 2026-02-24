=============
CLI Reference
=============

Config Inspector
----------------

Validate and preview experiment configurations:

.. code-block:: bash

   python -m risklab.inspect_config <config_path> [flags]

Flags
~~~~~

.. list-table::
   :header-rows: 1
   :widths: 15 15 70

   * - Flag
     - Short
     - Description
   * - ``--topology``
     - ``-t``
     - Display topology details (adjacency matrix, connectivity)
   * - ``--flow``
     - ``-f``
     - Display information flow configuration
   * - ``--agents``
     - ``-a``
     - Display agent configurations
   * - ``--simulate``
     - ``-s``
     - Show simulated speaker sequence
   * - ``--llm``
     - ``-l``
     - Display LLM provider details (keys masked)
   * - ``--all``
     - ``-A``
     - Display everything

Examples
~~~~~~~~

.. code-block:: bash

   # Full preview
   python -m risklab.inspect_config configs/r2_C1_basic.yaml -A

   # Topology and flow only
   python -m risklab.inspect_config configs/r2_C1_basic.yaml -t -f

   # Agent setup
   python -m risklab.inspect_config configs/r2_C1_basic.yaml -a

Sample Output
~~~~~~~~~~~~~

.. code-block:: text

   === Experiment Summary ===
   Name: R2_C1_basic
   Rounds: 10
   Seeds: [0, 1, 2]

   === Topology ===
   Type: fully_connected
   Nodes: 3
   Adjacency:
     [[0, 1, 1],
      [1, 0, 1],
      [1, 1, 0]]

   === Agents ===
   agent_0: seller (gpt-4o) objective=selfish
   agent_1: seller (gpt-4o) objective=selfish
   agent_2: seller (gpt-4o) objective=selfish
