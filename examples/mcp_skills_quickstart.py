#!/usr/bin/env python3
"""Quick start example for using MCP and Skills with RiskLab.

This example demonstrates:
1. Creating a simple MCP server
2. Creating a simple skill
3. Using EnhancedLLMAgent with both MCP and Skills

Run this script to see how everything works together.
"""

import asyncio
import tempfile
from pathlib import Path

# This would be your imports in a real project
# from risklab import EnhancedLLMAgent, AgentConfig
# from risklab import MCPClient, MCPServerConfig
# from risklab import SkillRegistry, Skill

print("=" * 70)
print("RiskLab - MCP and Skills Quick Start Example")
print("=" * 70)
print()

# ============================================================================
# Part 1: Create a simple skill
# ============================================================================
print("Part 1: Creating a simple skill...")
print()

with tempfile.TemporaryDirectory() as tmpdir:
    skill_dir = Path(tmpdir) / "my_skill"
    skill_dir.mkdir()
    
    # Create skill.md
    skill_md = skill_dir / "skill.md"
    skill_md.write_text("""# Data Validation Skill

A skill for validating data quality.

## Description

This skill helps agents validate data by:
- Checking for completeness
- Identifying inconsistencies
- Verifying data types
- Detecting outliers

## Instructions

When validating data:

1. **Check Completeness**
   - Verify all required fields are present
   - Identify missing values
   - Check for empty strings

2. **Verify Consistency**
   - Check data types match expectations
   - Validate value ranges
   - Look for logical inconsistencies

3. **Report Findings**
   - List all issues found
   - Categorize by severity (critical/warning/info)
   - Suggest remediation steps
""")
    
    print(f"✓ Created skill at: {skill_dir}")
    print(f"  - skill.md with validation instructions")
    print()
    
    # ============================================================================
    # Part 2: Setup MCP (conceptual - would need actual MCP server)
    # ============================================================================
    print("Part 2: MCP Server Configuration")
    print()
    print("Example MCP configuration:")
    print("""
    mcp_servers:
      - name: "filesystem"
        command: "npx"
        args:
          - "-y"
          - "@modelcontextprotocol/server-filesystem"
          - "/tmp/workspace"
      
      - name: "calculator"
        command: "python"
        args:
          - "my_mcp_calculator.py"
    """)
    print()
    
    # ============================================================================
    # Part 3: Agent Configuration
    # ============================================================================
    print("Part 3: Enhanced Agent Configuration")
    print()
    print("Example agent configuration:")
    print("""
    agents:
      - agent_id: "data_analyst"
        type: "llm_enhanced"  # Use enhanced agent type
        role: "analyst"
        model: "gpt-4o"
        objective: "cooperative"
        system_prompt: |
          You are a data analyst. Use available tools and skills to:
          - Access and read data files
          - Validate data quality
          - Perform calculations
          - Generate reports
        
        # Enable specific skills
        enabled_skills:
          - "data_validation"
          - "statistical_analysis"
    """)
    print()
    
    # ============================================================================
    # Part 4: How agents use tools and skills
    # ============================================================================
    print("Part 4: How Enhanced Agents Work")
    print()
    print("System Prompt (automatically generated):")
    print("-" * 70)
    print("""
You are agent 'data_analyst' with role 'analyst'.

Your primary goal is to contribute to the TEAM's success.

# Available Tools (from MCP servers)

## Tool: filesystem::read_file
Description: Read a file from the filesystem
To use this tool, respond with:
{
  "tool_call": {
    "server": "filesystem",
    "tool": "read_file",
    "arguments": {"path": "/path/to/file"}
  }
}

## Tool: calculator::compute
Description: Perform mathematical calculations
To use this tool, respond with:
{
  "tool_call": {
    "server": "calculator",
    "tool": "compute",
    "arguments": {"expression": "2 + 2"}
  }
}

# Available Skills

## Skill: data_validation

### Description
A skill for validating data quality...

### Instructions
When validating data:
1. Check Completeness...
2. Verify Consistency...
3. Report Findings...
    """)
    print("-" * 70)
    print()
    
    # ============================================================================
    # Part 5: Example interaction
    # ============================================================================
    print("Part 5: Example Agent Interaction")
    print()
    print("USER: Please analyze the data in /tmp/data.csv")
    print()
    print("AGENT (thinking): I need to:")
    print("  1. Read the file using filesystem tool")
    print("  2. Validate data using data_validation skill")
    print("  3. Calculate statistics using calculator tool")
    print()
    print("AGENT (response):")
    print("""
Let me read and analyze the data:

```json
{
  "tool_call": {
    "server": "filesystem",
    "tool": "read_file",
    "arguments": {"path": "/tmp/data.csv"}
  }
}
```

Tool result: [file contents...]

Now I'll validate the data following the data_validation skill:

**Completeness Check:**
- ✓ All required fields present
- ⚠ 3 missing values in 'age' column

**Consistency Check:**
- ✓ All data types correct
- ✗ 2 outliers detected in 'salary' column

Let me calculate summary statistics:

```json
{
  "tool_call": {
    "server": "calculator",
    "tool": "compute",
    "arguments": {"expression": "mean([...])"}
  }
}
```

**Summary:**
- Total records: 100
- Complete records: 97
- Issues found: 5 (3 warnings, 2 critical)
- Mean age: 35.2 years
    """)
    print()

print("=" * 70)
print("Quick Start Complete!")
print("=" * 70)
print()
print("Next Steps:")
print("1. Install MCP: pip install mcp")
print("2. Create your skills in ./skills/")
print("3. Configure MCP servers in your experiment YAML")
print("4. Use 'llm_enhanced' agent type")
print("5. See MCP_SKILLS_GUIDE.md for details")
print()
print("Example experiment:")
print("  risklab/experiments/configs/example_enhanced_agents.yaml")
print()
