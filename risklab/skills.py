"""Agent Skills support for RiskLab.

This module implements support for Agent Skills (https://github.com/agentskills/agentskills),
allowing agents to discover and use skills defined as folders containing instructions,
scripts, and resources.

Skills are structured folders that can include:
- skill.md: Skill description and instructions
- examples/: Example usage
- scripts/: Executable scripts
- resources/: Additional resources

Example skill structure:
    my_skill/
    ├── skill.md          # Main skill description
    ├── examples/
    │   └── example.md
    ├── scripts/
    │   └── helper.py
    └── resources/
        └── data.json
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Skill:
    """Represents an Agent Skill."""
    
    name: str
    description: str
    instructions: str
    skill_path: Path
    examples: List[str] = field(default_factory=list)
    scripts: Dict[str, Path] = field(default_factory=dict)
    resources: Dict[str, Path] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def from_directory(cls, skill_path: Path) -> "Skill":
        """Load a skill from a directory.
        
        Args:
            skill_path: Path to the skill directory.
            
        Returns:
            Skill object loaded from the directory.
        """
        if not skill_path.is_dir():
            raise ValueError(f"Skill path is not a directory: {skill_path}")
        
        name = skill_path.name
        
        # Read main skill description from skill.md
        skill_md = skill_path / "skill.md"
        if skill_md.exists():
            with open(skill_md, "r", encoding="utf-8") as f:
                content = f.read()
                
            # Parse skill.md for description and instructions
            description, instructions = cls._parse_skill_md(content)
        else:
            description = f"Skill: {name}"
            instructions = ""
        
        # Load examples
        examples = []
        examples_dir = skill_path / "examples"
        if examples_dir.exists():
            for example_file in examples_dir.glob("*.md"):
                with open(example_file, "r", encoding="utf-8") as f:
                    examples.append(f.read())
        
        # Load scripts
        scripts = {}
        scripts_dir = skill_path / "scripts"
        if scripts_dir.exists():
            for script_file in scripts_dir.glob("*"):
                if script_file.is_file():
                    scripts[script_file.name] = script_file
        
        # Load resources
        resources = {}
        resources_dir = skill_path / "resources"
        if resources_dir.exists():
            for resource_file in resources_dir.rglob("*"):
                if resource_file.is_file():
                    rel_path = resource_file.relative_to(resources_dir)
                    resources[str(rel_path)] = resource_file
        
        # Load metadata if available
        metadata = {}
        metadata_file = skill_path / "metadata.json"
        if metadata_file.exists():
            import json
            with open(metadata_file, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        
        return cls(
            name=name,
            description=description,
            instructions=instructions,
            skill_path=skill_path,
            examples=examples,
            scripts=scripts,
            resources=resources,
            metadata=metadata,
        )
    
    @staticmethod
    def _parse_skill_md(content: str) -> tuple[str, str]:
        """Parse skill.md content to extract description and instructions.
        
        Args:
            content: Content of skill.md file.
            
        Returns:
            Tuple of (description, instructions).
        """
        lines = content.split('\n')
        
        # First line or first heading is the description
        description = ""
        instructions = ""
        
        for i, line in enumerate(lines):
            if line.strip().startswith('#'):
                description = line.strip('#').strip()
                instructions = '\n'.join(lines[i+1:]).strip()
                break
        
        if not description:
            # If no heading found, use first paragraph as description
            paragraphs = content.strip().split('\n\n')
            if paragraphs:
                description = paragraphs[0].strip()
                if len(paragraphs) > 1:
                    instructions = '\n\n'.join(paragraphs[1:])
        
        return description, instructions
    
    def get_resource_content(self, resource_name: str) -> str:
        """Get content of a resource file.
        
        Args:
            resource_name: Name of the resource file.
            
        Returns:
            Content of the resource file.
        """
        if resource_name not in self.resources:
            raise ValueError(f"Resource '{resource_name}' not found in skill '{self.name}'")
        
        resource_path = self.resources[resource_name]
        with open(resource_path, "r", encoding="utf-8") as f:
            return f.read()
    
    def to_prompt(self) -> str:
        """Convert skill to a prompt for agent use.
        
        Returns:
            Formatted prompt containing skill information.
        """
        prompt_parts = [
            f"# Skill: {self.name}",
            "",
            f"## Description",
            self.description,
            "",
            f"## Instructions",
            self.instructions,
        ]
        
        if self.examples:
            prompt_parts.extend([
                "",
                "## Examples",
                "",
            ])
            for i, example in enumerate(self.examples, 1):
                prompt_parts.append(f"### Example {i}")
                prompt_parts.append(example)
                prompt_parts.append("")
        
        if self.scripts:
            prompt_parts.extend([
                "",
                "## Available Scripts",
            ])
            for script_name in self.scripts.keys():
                prompt_parts.append(f"- {script_name}")
        
        if self.resources:
            prompt_parts.extend([
                "",
                "## Available Resources",
            ])
            for resource_name in self.resources.keys():
                prompt_parts.append(f"- {resource_name}")
        
        return "\n".join(prompt_parts)


class SkillRegistry:
    """Registry for managing and discovering agent skills."""
    
    def __init__(self, skill_directories: Optional[List[Path]] = None):
        """Initialize skill registry.
        
        Args:
            skill_directories: List of directories to search for skills.
        """
        self.skill_directories = skill_directories or []
        self.skills: Dict[str, Skill] = {}
    
    def add_skill_directory(self, directory: Path) -> None:
        """Add a directory to search for skills.
        
        Args:
            directory: Path to directory containing skills.
        """
        if directory not in self.skill_directories:
            self.skill_directories.append(directory)
    
    def discover_skills(self) -> None:
        """Discover and load all skills from configured directories."""
        for directory in self.skill_directories:
            if not directory.exists():
                print(f"Warning: Skill directory does not exist: {directory}")
                continue
            
            # Each subdirectory is a potential skill
            for skill_dir in directory.iterdir():
                if skill_dir.is_dir() and not skill_dir.name.startswith('.'):
                    try:
                        skill = Skill.from_directory(skill_dir)
                        self.skills[skill.name] = skill
                    except Exception as e:
                        print(f"Warning: Failed to load skill from {skill_dir}: {e}")
    
    def get_skill(self, name: str) -> Optional[Skill]:
        """Get a skill by name.
        
        Args:
            name: Name of the skill.
            
        Returns:
            Skill object if found, None otherwise.
        """
        return self.skills.get(name)
    
    def list_skills(self) -> List[str]:
        """List all available skill names.
        
        Returns:
            List of skill names.
        """
        return list(self.skills.keys())
    
    def get_all_skills(self) -> List[Skill]:
        """Get all available skills.
        
        Returns:
            List of all skills.
        """
        return list(self.skills.values())
    
    def to_system_prompt(self, skill_names: Optional[List[str]] = None) -> str:
        """Generate system prompt with available skills.
        
        Args:
            skill_names: Optional list of specific skills to include.
                        If None, includes all skills.
        
        Returns:
            System prompt containing skill information.
        """
        if skill_names:
            skills = [self.skills[name] for name in skill_names if name in self.skills]
        else:
            skills = self.get_all_skills()
        
        if not skills:
            return ""
        
        prompt_parts = [
            "# Available Skills",
            "",
            "You have access to the following skills that provide specialized capabilities:",
            "",
        ]
        
        for skill in skills:
            prompt_parts.append(skill.to_prompt())
            prompt_parts.append("")
            prompt_parts.append("---")
            prompt_parts.append("")
        
        return "\n".join(prompt_parts)


def load_skills_config(config: Dict[str, Any]) -> Optional[SkillRegistry]:
    """Load skills configuration from experiment config.
    
    Args:
        config: Experiment configuration dictionary.
        
    Returns:
        SkillRegistry if skills are configured, None otherwise.
    """
    skills_config = config.get("skills", {})
    if not skills_config:
        return None
    
    skill_directories = skills_config.get("directories", [])
    if not skill_directories:
        return None
    
    # Convert to Path objects and resolve relative paths
    skill_paths = [Path(d).resolve() for d in skill_directories]
    
    registry = SkillRegistry(skill_paths)
    registry.discover_skills()
    
    return registry
