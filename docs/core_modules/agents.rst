======
Agents
======

Agents are the decision-making entities in RiskLab. Each agent wraps an LLM
with a persona, objective, and conversation memory.

LLMAgent
--------

The primary agent class.

.. code-block:: python

   from risklab.agents.llm_agent import LLMAgent
   from risklab.agents.base import AgentConfig
   from risklab.llm import LLMConfig

   agent = LLMAgent(
       config=AgentConfig(
           agent_id="seller_0",
           role="seller",
           objective="selfish",           # selfish | cooperative | system
           system_prompt="You are a seller in a market.",
       ),
       llm_config=LLMConfig.from_env(),
   )

   result = agent.act({"round": 1, "prices": [50, 55, 60]})

Key features:

- **Objective injection** — the agent's goal is prepended to every LLM call
- **Memory management** — rolling conversation history with configurable window
- **Persona** — optional character description appended to the system prompt

EnhancedLLMAgent
----------------

Extends ``LLMAgent`` with MCP tool integration and a skill registry.
Registered as ``llm_enhanced``. Use this when your experiment needs agents
that can call external tools — for example, web search or data-analysis
skills. The ``enabled_skills`` parameter restricts which skills are
accessible at runtime.

.. code-block:: python

   from risklab.agents.enhanced_llm_agent import EnhancedLLMAgent

   agent = EnhancedLLMAgent(
       config=agent_config,
       llm_config=llm_config,
       enabled_skills=["summarize", "data_analysis"],  # optional filter
   )

MarketSellerAgent
-----------------

A specialized agent for market competition experiments (R2 Tacit Collusion).
Registered as ``market_seller``.

Key differences from ``LLMAgent``:

- Uses ``system_prompt`` verbatim — no automatic objective prefix is injected.
- Maintains a proper alternating ``user`` / ``assistant`` conversation history,
  enabling the LLM to learn from its own past pricing decisions in-context.
- ``observe()`` is a no-op; history management is handled entirely within
  ``act()``, which appends each observation as a ``user`` message and the LLM
  response as an ``assistant`` message.

.. code-block:: python

   from risklab.agents.market_seller_agent import MarketSellerAgent

   agent = MarketSellerAgent(
       config=AgentConfig(
           agent_id="seller_0",
           role="seller",
           system_prompt="You are a price-setting seller...",
       ),
       llm_config=LLMConfig.from_env(),
   )

   # act() returns the raw LLM text; the environment parses [Price] / [Speech]
   result = agent.act({"round": 1, "market_history": [...]})

.. note::

   Use ``market_seller`` (not ``llm``) when the experiment relies on
   alternating conversation memory — this is required for pricing games
   where the agent's own past responses must appear as ``assistant`` turns.

YAML Configuration
------------------

.. code-block:: yaml

   agents:
     - agent_id: seller_0
       role: seller
       model: gpt-4o
       objective: selfish
       temperature: 0.7
       system_prompt: "You are a seller in a market."
       parameters:
         initial_price: 50

     - agent_id: seller_1
       type: market_seller       # use MarketSellerAgent for market games
       role: seller
       model: claude-sonnet-4-20250514
       objective: selfish

Agent Registry
--------------

The ``AgentRegistry`` allows you to register custom agent classes so they
can be referenced by name in YAML configs. This is useful when built-in
agents do not fit your experiment.

.. code-block:: python

   from risklab.agents.registry import AgentRegistry
   from risklab.agents.base import Agent

   @AgentRegistry.register("my_agent")
   class MyAgent(Agent):
       def act(self, observation: dict) -> dict:
           ...

Then reference by name in config:

.. code-block:: yaml

   agents:
     - agent_id: agent_0
       type: my_agent
