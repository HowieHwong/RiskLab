========================
Extending the Framework
========================

RiskLab is designed for extensibility. Add custom agents, environments,
protocols, risk detectors, and metrics without modifying core code.

Custom Agent
------------

.. code-block:: python

   from risklab.agents.base import Agent, AgentConfig
   from risklab.agents.registry import AgentRegistry

   @AgentRegistry.register("reflective")
   class ReflectiveAgent(Agent):
       """An agent that reflects on past actions before deciding."""

       def __init__(self, config: AgentConfig, **kwargs):
           super().__init__(config)
           self.history = []

       def act(self, observation: dict) -> dict:
           self.history.append(observation)
           # Reflect and decide...
           return {"message": decision, "action": decision}

Use in YAML:

.. code-block:: yaml

   agents:
     - agent_id: agent_0
       type: reflective

Custom Environment
------------------

Subclass ``Environment`` and implement the three abstract methods:
``reset``, ``step``, and ``get_observation``. The ``step`` method must
return a ``(observations, rewards, done, info)`` tuple.

.. code-block:: python

   from risklab.environments.base import Environment, EnvironmentConfig

   class AuctionEnvironment(Environment):
       def reset(self) -> dict:
           self.state = {"bids": [], "current_item": 0}
           return {aid: self.get_observation(aid) for aid in self.config.parameters["agent_ids"]}

       def get_observation(self, agent_id: str) -> dict:
           return {"item": self.state["current_item"], "bids": self.state["bids"]}

       def step(self, joint_action: dict) -> tuple:
           # Process bids, determine winner ...
           observations = {aid: self.get_observation(aid) for aid in joint_action}
           rewards = {aid: 0.0 for aid in joint_action}
           done = self.current_round >= self.max_rounds
           info = {"round": self.current_round}
           return observations, rewards, done, info

Custom Risk Detector
--------------------

.. code-block:: python

   from risklab.risks.base import Risk
   from risklab.risks.registry import RiskRegistry

   @RiskRegistry.register("info_hoarding")
   class InformationHoarding(Risk):
       def detect(self, trajectory) -> bool:
           shared = self._count_shared(trajectory)
           total = self._count_total(trajectory)
           return shared / max(total, 1) < 0.3

       def score(self, trajectory) -> float:
           shared = self._count_shared(trajectory)
           total = self._count_total(trajectory)
           return 1.0 - (shared / max(total, 1))

Use in YAML:

.. code-block:: yaml

   risks:
     - name: info_hoarding
       parameters:
         threshold: 0.7

Custom Protocol
---------------

Subclass ``InteractionProtocol`` and implement ``get_next_speaker`` and
``advance``. Override ``get_listeners`` if you need custom visibility
rules (otherwise the topology's adjacency matrix is used).

.. code-block:: python

   from risklab.protocols.base import InteractionProtocol, Message
   from typing import Optional, List

   class PriorityProtocol(InteractionProtocol):
       """Agents speak in priority order each round."""

       def __init__(self, agent_ids, priorities: dict, **kwargs):
           super().__init__(agent_ids, **kwargs)
           self._order = sorted(agent_ids, key=lambda a: priorities.get(a, 0), reverse=True)
           self._idx = 0

       def get_next_speaker(self) -> Optional[str]:
           if self._idx < len(self._order):
               return self._order[self._idx]
           return None

       def advance(self) -> None:
           self._idx += 1
           if self._idx >= len(self._order):
               self._idx = 0
               self.current_round += 1

Custom Metric
-------------

.. code-block:: python

   from risklab.evaluation.metrics import Metric, MetricResult

   class ResponseDiversity(Metric):
       name = "response_diversity"

       def compute(self, trajectory) -> MetricResult:
           unique = len(set(step.action for step in trajectory.steps))
           total = len(trajectory.steps)
           return MetricResult(name=self.name, value=unique / max(total, 1))

MCP & Skills
------------

``EnhancedLLMAgent`` supports external tool integration through MCP
(Model Context Protocol) and a built-in skill system.

.. code-block:: python

   from risklab.mcp_integration import MCPClient, MCPServerConfig

   # Connect to an MCP server
   server = MCPServerConfig(
       name="web_search",
       command="python",
       args=["-m", "mcp_server_web"],
   )
   client = MCPClient()
   await client.connect(server)
   result = await client.call_tool("search", {"query": "LLM risks"})

Skills are Python functions registered with agents:

.. code-block:: python

   from risklab.skills import Skill, SkillRegistry

   @SkillRegistry.register("summarize")
   class SummarizeSkill(Skill):
       name = "summarize"
       description = "Summarize a block of text."

       def execute(self, text: str) -> str:
           return summary

Attach via YAML:

.. code-block:: yaml

   agents:
     - agent_id: agent_0
       type: llm_enhanced
       enabled_skills: [summarize, data_analysis]
       mcp_servers:
         - name: web_search
           command: "python"
           args: ["-m", "mcp_server_web"]

Integration Checklist
---------------------

.. list-table::
   :header-rows: 1
   :widths: 10 90

   * - Step
     - Action
   * - 1
     - Subclass the appropriate base class
   * - 2
     - Register with the registry decorator
   * - 3
     - Reference by name in your YAML config
   * - 4
     - Test with ``python -m risklab.inspect_config config.yaml -A``
