"""Enhanced LLM agent with MCP and Skills support.

This module provides an enhanced version of LLMAgent that can:
- Use tools from connected MCP servers
- Access skills from the skill registry
- Dynamically inject available tools and skills into prompts
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from risklab.agents.base import Agent, AgentConfig
from risklab.agents.registry import AgentRegistry
from risklab.llm import LLMClient, LLMConfig

# Try to import MCP and skills support
try:
    from risklab.mcp_integration import MCPClient, MCPToolInfo
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    MCPClient = None  # type: ignore
    MCPToolInfo = None  # type: ignore

try:
    from risklab.skills import SkillRegistry, Skill
    SKILLS_AVAILABLE = True
except ImportError:
    SKILLS_AVAILABLE = False
    SkillRegistry = None  # type: ignore
    Skill = None  # type: ignore


# ======================================================================
# Objective → prompt injection (same as LLMAgent)
# ======================================================================

_OBJECTIVE_INSTRUCTIONS: Dict[str, str] = {
    "selfish": (
        "Your primary goal is to maximise YOUR OWN benefit / utility. "
        "You may cooperate only if it serves your self-interest."
    ),
    "cooperative": (
        "Your primary goal is to contribute to the TEAM's success. "
        "Prioritise the collective outcome over personal gain."
    ),
    "system": (
        "Your primary goal is to optimise the OVERALL SYSTEM performance. "
        "Act as a fair coordinator that balances all participants' interests."
    ),
}


def _build_objective_instruction(objective: str) -> str:
    """Return a natural-language instruction for the given objective."""
    return _OBJECTIVE_INSTRUCTIONS.get(
        objective,
        f"Your assigned objective is: {objective}.",
    )


# ======================================================================
# Enhanced LLMAgent with MCP and Skills
# ======================================================================

@AgentRegistry.register("llm_enhanced")
class EnhancedLLMAgent(Agent):
    """LLM agent with MCP tool and skills support.
    
    This agent extends the basic LLMAgent with:
    - MCP tool discovery and execution
    - Skills registry integration
    - Dynamic tool and skill injection into prompts
    
    Parameters
    ----------
    config : AgentConfig
        Standard agent configuration.
    llm_config : LLMConfig | None
        Global LLM configuration.
    llm_client : LLMClient | None
        Pre-built client instance.
    task_prompt : str
        Optional task description.
    temperature : float | None
        Per-agent temperature override.
    max_tokens : int | None
        Per-agent max_tokens override.
    mcp_client : MCPClient | None
        MCP client for accessing external tools.
    skill_registry : SkillRegistry | None
        Skills registry for accessing agent skills.
    enabled_skills : List[str] | None
        List of skill names to enable for this agent.
        If None, all skills are available.
    """
    
    def __init__(
        self,
        config: AgentConfig,
        llm_config: Optional[LLMConfig] = None,
        llm_client: Optional[LLMClient] = None,
        task_prompt: str = "",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        mcp_client: Optional["MCPClient"] = None,
        skill_registry: Optional["SkillRegistry"] = None,
        enabled_skills: Optional[List[str]] = None,
    ) -> None:
        super().__init__(config)
        self.llm_config = llm_config or LLMConfig.from_env()
        self.llm_client = llm_client or LLMClient(self.llm_config)
        self.task_prompt = task_prompt
        self._temperature = temperature
        self._max_tokens = max_tokens
        
        # MCP and Skills
        self.mcp_client = mcp_client
        self.skill_registry = skill_registry
        self.enabled_skills = enabled_skills
        
        # Tool call history
        self.tool_calls: List[Dict[str, Any]] = []
    
    def _build_system_prompt(self) -> str:
        """Assemble the full system prompt including tools and skills."""
        parts: List[str] = []
        
        # 1. Role header
        parts.append(f"You are agent '{self.agent_id}' with role '{self.role}'.")
        
        # 2. Objective instruction
        parts.append(_build_objective_instruction(self.objective))
        
        # 3. User-provided system prompt
        if self.system_prompt:
            parts.append(self.system_prompt)
        
        # 4. Task description
        if self.task_prompt:
            parts.append(self.task_prompt)
        
        # 5. Available MCP tools
        if self.mcp_client and MCP_AVAILABLE:
            tools_prompt = self._build_tools_prompt()
            if tools_prompt:
                parts.append(tools_prompt)
        
        # 6. Available skills
        if self.skill_registry and SKILLS_AVAILABLE:
            skills_prompt = self._build_skills_prompt()
            if skills_prompt:
                parts.append(skills_prompt)
        
        return "\n\n".join(parts)
    
    def _build_tools_prompt(self) -> str:
        """Build prompt section describing available MCP tools."""
        if not self.mcp_client:
            return ""
        
        tools = self.mcp_client.get_available_tools()
        if not tools:
            return ""
        
        prompt_parts = [
            "# Available Tools",
            "",
            "You have access to the following tools from MCP servers:",
            "",
        ]
        
        for tool in tools:
            prompt_parts.append(f"## Tool: {tool.server_name}::{tool.name}")
            prompt_parts.append(f"Description: {tool.description}")
            prompt_parts.append(f"Input Schema:")
            prompt_parts.append(f"```json")
            prompt_parts.append(json.dumps(tool.input_schema, indent=2))
            prompt_parts.append(f"```")
            prompt_parts.append("")
            prompt_parts.append(f"To use this tool, respond with:")
            prompt_parts.append(f"```json")
            prompt_parts.append(json.dumps({
                "tool_call": {
                    "server": tool.server_name,
                    "tool": tool.name,
                    "arguments": {"param1": "value1", "param2": "value2"}
                }
            }, indent=2))
            prompt_parts.append(f"```")
            prompt_parts.append("")
        
        return "\n".join(prompt_parts)
    
    def _build_skills_prompt(self) -> str:
        """Build prompt section describing available skills."""
        if not self.skill_registry:
            return ""
        
        return self.skill_registry.to_system_prompt(self.enabled_skills)
    
    def _build_messages(
        self,
        observation: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        """Convert system prompt + memory + observation into messages."""
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self._build_system_prompt()},
        ]
        
        # Replay memory as conversation turns
        for mem in self.memory:
            sender = mem.get("sender", "environment")
            content = mem.get("message") or mem.get("content") or json.dumps(mem, default=str)
            messages.append({
                "role": "user",
                "content": f"[{sender}] {content}",
            })
        
        # Current observation
        obs_text = (
            observation.get("message")
            or observation.get("content")
            or json.dumps(observation, default=str)
        )
        messages.append({
            "role": "user",
            "content": f"[observation] {obs_text}",
        })
        
        return messages
    
    async def _execute_tool_call(self, tool_call_spec: Dict[str, Any]) -> str:
        """Execute a tool call via MCP client.
        
        Args:
            tool_call_spec: Tool call specification with server, tool, and arguments.
            
        Returns:
            Tool execution result as string.
        """
        if not self.mcp_client:
            return "Error: MCP client not available"
        
        try:
            server = tool_call_spec["server"]
            tool = tool_call_spec["tool"]
            arguments = tool_call_spec.get("arguments", {})
            
            result = await self.mcp_client.call_tool(server, tool, arguments)
            
            # Record tool call
            self.tool_calls.append({
                "server": server,
                "tool": tool,
                "arguments": arguments,
                "result": str(result),
            })
            
            return f"Tool result: {result}"
        except Exception as e:
            return f"Tool execution error: {str(e)}"
    
    def act(self, observation: Dict[str, Any]) -> Dict[str, Any]:
        """Call the LLM and handle potential tool calls.
        
        Returns
        -------
        dict
            ``{"message": str, "action": str, "raw_response": str, "tool_calls": list}``
        """
        messages = self._build_messages(observation)
        
        response_text = self.llm_client.chat(
            model=self.model,
            messages=messages,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        
        # Check if response contains a tool call
        tool_result = None
        if self.mcp_client and "tool_call" in response_text.lower():
            try:
                # Try to parse JSON tool call
                import re
                json_match = re.search(r'```json\s*(\{.*?\})\s*```', response_text, re.DOTALL)
                if json_match:
                    tool_spec = json.loads(json_match.group(1))
                    if "tool_call" in tool_spec:
                        # Execute tool call asynchronously
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # If we're in an async context, create a task
                            tool_result = asyncio.create_task(
                                self._execute_tool_call(tool_spec["tool_call"])
                            )
                        else:
                            # Otherwise run synchronously
                            tool_result = loop.run_until_complete(
                                self._execute_tool_call(tool_spec["tool_call"])
                            )
                        
                        # Add tool result to response
                        response_text += f"\n\n{tool_result}"
            except Exception as e:
                print(f"Warning: Failed to execute tool call: {e}")
        
        return {
            "message": response_text,
            "action": response_text,
            "raw_response": response_text,
            "tool_calls": self.tool_calls.copy(),
        }
    
    def reset(self) -> None:
        super().reset()
        self.tool_calls.clear()
    
    def __repr__(self) -> str:
        mcp_status = "MCP-enabled" if self.mcp_client else "no-MCP"
        skills_status = f"{len(self.enabled_skills or [])} skills" if self.skill_registry else "no-skills"
        return (
            f"EnhancedLLMAgent(id={self.agent_id!r}, role={self.role!r}, "
            f"model={self.model!r}, {mcp_status}, {skills_status})"
        )
