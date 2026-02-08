"""MCP (Model Context Protocol) integration for RiskLab agents.

This module enables RiskLab agents to connect to MCP servers and use their
tools, resources, and prompts. Agents can dynamically discover and use
capabilities from external MCP servers.

Example:
    # In your experiment config:
    mcp_servers:
      - name: "filesystem"
        command: "npx"
        args: ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
        
      - name: "github"
        command: "npx"
        args: ["-y", "@modelcontextprotocol/server-github"]
        env:
          GITHUB_TOKEN: "${GITHUB_TOKEN}"
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import Tool as MCPTool
    from mcp.types import Resource as MCPResource
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    ClientSession = None  # type: ignore
    StdioServerParameters = None  # type: ignore


@dataclass
class MCPServerConfig:
    """Configuration for an MCP server connection."""
    
    name: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Optional[Dict[str, str]] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPServerConfig":
        """Create config from dictionary."""
        return cls(
            name=data["name"],
            command=data["command"],
            args=data.get("args", []),
            env=data.get("env"),
        )
    
    def to_server_params(self) -> "StdioServerParameters":
        """Convert to MCP StdioServerParameters."""
        if not MCP_AVAILABLE:
            raise ImportError("mcp package is required. Install with: pip install mcp")
        
        # Resolve environment variables
        env = dict(os.environ)
        if self.env:
            for key, value in self.env.items():
                # Support ${VAR_NAME} syntax
                if value.startswith("${") and value.endswith("}"):
                    env_var = value[2:-1]
                    env[key] = os.environ.get(env_var, "")
                else:
                    env[key] = value
        
        return StdioServerParameters(
            command=self.command,
            args=self.args,
            env=env,
        )


@dataclass
class MCPToolInfo:
    """Information about an MCP tool."""
    
    name: str
    description: str
    input_schema: Dict[str, Any]
    server_name: str


@dataclass
class MCPResourceInfo:
    """Information about an MCP resource."""
    
    uri: str
    name: str
    description: Optional[str]
    mime_type: Optional[str]
    server_name: str


class MCPClient:
    """Client for connecting to and using MCP servers.
    
    This client manages connections to multiple MCP servers and provides
    a unified interface for discovering and using their capabilities.
    """
    
    def __init__(self, server_configs: List[MCPServerConfig]):
        """Initialize MCP client with server configurations.
        
        Args:
            server_configs: List of MCP server configurations to connect to.
        """
        if not MCP_AVAILABLE:
            raise ImportError(
                "mcp package is required for MCP integration. "
                "Install with: pip install mcp"
            )
        
        self.server_configs = server_configs
        self.sessions: Dict[str, Any] = {}
        self.tools: Dict[str, MCPToolInfo] = {}
        self.resources: Dict[str, MCPResourceInfo] = {}
        self._initialized = False
    
    async def initialize(self) -> None:
        """Initialize connections to all configured MCP servers."""
        if self._initialized:
            return
        
        for config in self.server_configs:
            try:
                await self._connect_server(config)
            except Exception as e:
                print(f"Warning: Failed to connect to MCP server '{config.name}': {e}")
        
        self._initialized = True
    
    async def _connect_server(self, config: MCPServerConfig) -> None:
        """Connect to a single MCP server and discover its capabilities."""
        server_params = config.to_server_params()
        
        # This creates a context manager, we'll store it for later use
        client_context = stdio_client(server_params)
        read, write = await client_context.__aenter__()
        
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()
        
        # Store session for later use
        self.sessions[config.name] = {
            "session": session,
            "context": client_context,
            "config": config,
        }
        
        # Discover tools
        tools_result = await session.list_tools()
        for tool in tools_result.tools:
            tool_key = f"{config.name}::{tool.name}"
            self.tools[tool_key] = MCPToolInfo(
                name=tool.name,
                description=tool.description or "",
                input_schema=tool.inputSchema,
                server_name=config.name,
            )
        
        # Discover resources
        resources_result = await session.list_resources()
        for resource in resources_result.resources:
            resource_key = f"{config.name}::{resource.uri}"
            self.resources[resource_key] = MCPResourceInfo(
                uri=resource.uri,
                name=resource.name or resource.uri,
                description=resource.description,
                mime_type=resource.mimeType,
                server_name=config.name,
            )
    
    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Any:
        """Call a tool on an MCP server.
        
        Args:
            server_name: Name of the MCP server.
            tool_name: Name of the tool to call.
            arguments: Tool arguments.
            
        Returns:
            Tool result from the MCP server.
        """
        if not self._initialized:
            await self.initialize()
        
        if server_name not in self.sessions:
            raise ValueError(f"MCP server '{server_name}' not connected")
        
        session = self.sessions[server_name]["session"]
        result = await session.call_tool(tool_name, arguments=arguments)
        
        return result
    
    async def read_resource(self, server_name: str, uri: str) -> str:
        """Read a resource from an MCP server.
        
        Args:
            server_name: Name of the MCP server.
            uri: URI of the resource to read.
            
        Returns:
            Resource content as string.
        """
        if not self._initialized:
            await self.initialize()
        
        if server_name not in self.sessions:
            raise ValueError(f"MCP server '{server_name}' not connected")
        
        session = self.sessions[server_name]["session"]
        result = await session.read_resource(uri)
        
        # Extract text content from the result
        if result.contents:
            content = result.contents[0]
            if hasattr(content, 'text'):
                return content.text
        
        return ""
    
    def get_available_tools(self) -> List[MCPToolInfo]:
        """Get list of all available tools from connected servers.
        
        Returns:
            List of tool information objects.
        """
        return list(self.tools.values())
    
    def get_available_resources(self) -> List[MCPResourceInfo]:
        """Get list of all available resources from connected servers.
        
        Returns:
            List of resource information objects.
        """
        return list(self.resources.values())
    
    async def close(self) -> None:
        """Close all MCP server connections."""
        for server_name, session_info in self.sessions.items():
            try:
                await session_info["session"].__aexit__(None, None, None)
                await session_info["context"].__aexit__(None, None, None)
            except Exception as e:
                print(f"Warning: Failed to close MCP server '{server_name}': {e}")
        
        self.sessions.clear()
        self._initialized = False


def load_mcp_config(config: Dict[str, Any]) -> Optional[MCPClient]:
    """Load MCP configuration from experiment config.
    
    Args:
        config: Experiment configuration dictionary.
        
    Returns:
        MCPClient if MCP servers are configured, None otherwise.
    """
    if not MCP_AVAILABLE:
        return None
    
    mcp_servers = config.get("mcp_servers", [])
    if not mcp_servers:
        return None
    
    server_configs = [
        MCPServerConfig.from_dict(server_config)
        for server_config in mcp_servers
    ]
    
    return MCPClient(server_configs)
