============
Environments
============

Environments maintain the world state that agents interact with. They produce
observations, validate actions, and update state after each round.

Core Interface
--------------

.. code-block:: python

   class Environment:
       def reset(self):
           """Initialize or reset state for a new experiment run."""

       def get_observation(self, agent_id: str) -> dict:
           """Return the current observation dict for a given agent."""

def step(self, actions: dict) -> tuple[dict, dict, bool, dict]:
          """Process agent actions and advance the world state.

          Returns
          -------
          observations : dict
              Updated per-agent observation dicts.
          rewards : dict
              Per-agent scalar rewards for this step.
          done : bool
              Whether the episode has ended.
          info : dict
              Auxiliary diagnostic information.
          """

Built-in Environments
---------------------

**Competitive**

- ``homogeneous_goods_market`` — Sellers set prices for identical goods.
  Used to study tacit collusion (R2).

**Cooperative**

- ``cultural_negotiation`` — Agents negotiate across cultural contexts.
  Used to study normative deadlock (R10).
- ``grid_exploration`` — Agents explore a grid world collaboratively.
  Used to study strategic misreporting (R9).

**Collective**

- ``trading_pipeline`` — Sequential production pipeline with shared output.
  Used to study excessive rigidity (R13).

YAML Configuration
------------------

.. code-block:: yaml

   environment:
     name: homogeneous_goods_market   # lookup key (not type)
     type: competitive                # category label
     max_rounds: 10
     num_agents: 3
     parameters:                      # environment-specific settings
       marginal_cost: 10
       price_range: [10, 100]
       num_customers: 99

.. note::

   ``name`` is the registry lookup key. ``parameters`` (not ``params``)
   holds environment-specific key-value pairs.
   Some repository configs are provided as reference templates and may use
   environment names that are not registered by default.
