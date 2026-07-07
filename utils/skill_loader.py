"""Skill auto-discovery and loader for Agent Skills Framework."""

import os
import yaml
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

from agent.errors import SkillNotFoundError


@dataclass
class Skill:
    """Skill metadata and configuration."""
    name: str
    version: str
    description: str
    triggers: List[str]
    tags: List[str]
    directory: Path
    input_schema: Optional[dict] = None
    output_schema: Optional[str] = None
    tools: List[str] = None

    def __post_init__(self):
        if self.tools is None:
            self.tools = []

    @property
    def has_executor(self) -> bool:
        """Check if skill has executor.py."""
        return (self.directory / "executor.py").exists()

    @property
    def has_template(self) -> bool:
        """Check if skill has prompt.template."""
        return (self.directory / "prompt.template").exists()

    @property
    def has_schema(self) -> bool:
        """Check if skill has schema.py."""
        return (self.directory / "schema.py").exists()

    @property
    def execution_mode(self) -> str:
        """Get execution mode priority."""
        if self.has_executor:
            return "executor"
        elif self.has_template:
            return "template"
        else:
            return "document"

    def matches_trigger(self, text: str) -> bool:
        """Check if text matches any trigger."""
        text_lower = text.lower()
        return any(
            trigger.lower() in text_lower
            for trigger in self.triggers
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "triggers": self.triggers,
            "tags": self.tags,
            "directory": str(self.directory),
            "execution_mode": self.execution_mode,
            "has_executor": self.has_executor,
            "has_template": self.has_template,
            "has_schema": self.has_schema,
            "tools": self.tools
        }


class SkillLoader:
    """Skill auto-discovery and loader.

    Scans the skills/ directory for valid Skills and loads their metadata.
    """

    def __init__(self, skills_dir: str):
        """Initialize skill loader.

        Args:
            skills_dir: Path to skills directory
        """
        self.skills_dir = Path(skills_dir)
        self._skills: Dict[str, Skill] = {}

    def discover(self) -> Dict[str, Skill]:
        """Discover and load all skills from directory.

        Returns:
            Dictionary of skill_name -> Skill

        Raises:
            FileNotFoundError: If skills directory doesn't exist
        """
        if not self.skills_dir.exists():
            raise FileNotFoundError(f"Skills directory not found: {self.skills_dir}")

        if not self.skills_dir.is_dir():
            raise NotADirectoryError(f"Skills path is not a directory: {self.skills_dir}")

        discovered_count = 0

        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue

            # Skip hidden directories
            if skill_dir.name.startswith("."):
                continue

            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                # Skip directories without SKILL.md
                continue

            try:
                skill = self._load_skill_from_md(skill_dir, skill_md)
                self._skills[skill.name] = skill
                discovered_count += 1
            except Exception as e:
                # Log warning but continue loading other skills
                print(f"Warning: Failed to load skill from {skill_dir}: {e}")

        print(f"SkillLoader: Discovered {discovered_count} skill(s)")
        return self._skills

    def _load_skill_from_md(self, skill_dir: Path, skill_md: Path) -> Skill:
        """Load skill metadata from SKILL.md file.

        Args:
            skill_dir: Skill directory path
            skill_md: Path to SKILL.md file

        Returns:
            Skill instance

        Raises:
            ValueError: If SKILL.md format is invalid
        """
        content = skill_md.read_text(encoding="utf-8")

        # Parse YAML front matter
        front_matter = {}
        document = content

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 2:
                try:
                    front_matter = yaml.safe_load(parts[1]) or {}
                except yaml.YAMLError as e:
                    raise ValueError(f"Invalid YAML front matter: {e}")
                document = parts[2] if len(parts) > 2 else ""
            else:
                document = content

        # Extract required fields
        name = front_matter.get("name", skill_dir.name)
        if not name:
            raise ValueError(f"Skill name is required in {skill_md}")

        version = front_matter.get("version", "1.0.0")
        description = front_matter.get("description", "")
        triggers = front_matter.get("triggers", [])
        tags = front_matter.get("tags", [])
        input_schema = front_matter.get("input_schema")
        output_schema = front_matter.get("output_schema")
        tools = front_matter.get("tools", [])

        return Skill(
            name=name,
            version=version,
            description=description,
            triggers=triggers,
            tags=tags,
            directory=skill_dir,
            input_schema=input_schema,
            output_schema=output_schema,
            tools=tools
        )

    def get_skill(self, name: str) -> Skill:
        """Get a skill by name.

        Args:
            name: Skill name

        Returns:
            Skill instance

        Raises:
            SkillNotFoundError: If skill not found
        """
        if name not in self._skills:
            raise SkillNotFoundError(name)
        return self._skills[name]

    def get_all_skills(self) -> Dict[str, Skill]:
        """Get all loaded skills.

        Returns:
            Dictionary of skill_name -> Skill
        """
        return self._skills.copy()

    def get_skills_by_tags(self, tags: List[str]) -> List[Skill]:
        """Get skills matching any of the specified tags.

        Args:
            tags: List of tags to match

        Returns:
            List of matching skills
        """
        return [
            skill for skill in self._skills.values()
            if any(tag in skill.tags for tag in tags)
        ]

    def find_by_trigger(self, trigger: str) -> List[Skill]:
        """Find skills that match a trigger phrase.

        Args:
            trigger: Trigger phrase to search for

        Returns:
            List of matching skills
        """
        return [
            skill for skill in self._skills.values()
            if skill.matches_trigger(trigger)
        ]

    def reload(self) -> Dict[str, Skill]:
        """Reload all skills from directory.

        Returns:
            Dictionary of reloaded skills
        """
        self._skills = {}
        return self.discover()

    def get_summary(self) -> Dict:
        """Get summary of loaded skills.

        Returns:
            Summary dictionary
        """
        by_mode = {"executor": 0, "template": 0, "document": 0}
        by_tag = {}

        for skill in self._skills.values():
            by_mode[skill.execution_mode] += 1
            for tag in skill.tags:
                by_tag[tag] = by_tag.get(tag, 0) + 1

        return {
            "total_skills": len(self._skills),
            "skills_dir": str(self.skills_dir),
            "by_execution_mode": by_mode,
            "by_tag": by_tag,
            "skill_names": list(self._skills.keys())
        }


class SkillRegistry:
    """Central registry for managing skills.

    Provides a singleton-like interface for accessing loaded skills.
    """

    _instance: Optional["SkillRegistry"] = None

    def __init__(self):
        if SkillRegistry._instance is not None:
            raise RuntimeError("Use SkillRegistry.get_instance() instead")
        self._loader: Optional[SkillLoader] = None

    @classmethod
    def get_instance(cls) -> "SkillRegistry":
        """Get the singleton instance.

        Returns:
            SkillRegistry instance
        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (mainly for testing)."""
        cls._instance = None

    def initialize(self, skills_dir: str) -> Dict[str, Skill]:
        """Initialize registry with skills from directory.

        Args:
            skills_dir: Path to skills directory

        Returns:
            Dictionary of loaded skills
        """
        self._loader = SkillLoader(skills_dir)
        return self._loader.discover()

    def get_skill(self, name: str) -> Skill:
        """Get a skill by name.

        Args:
            name: Skill name

        Returns:
            Skill instance

        Raises:
            RuntimeError: If registry not initialized
            SkillNotFoundError: If skill not found
        """
        if self._loader is None:
            raise RuntimeError("SkillRegistry not initialized. Call initialize() first.")
        return self._loader.get_skill(name)

    def get_all_skills(self) -> Dict[str, Skill]:
        """Get all loaded skills.

        Returns:
            Dictionary of skills

        Raises:
            RuntimeError: If registry not initialized
        """
        if self._loader is None:
            raise RuntimeError("SkillRegistry not initialized. Call initialize() first.")
        return self._loader.get_all_skills()

    def find_by_trigger(self, trigger: str) -> List[Skill]:
        """Find skills matching trigger.

        Args:
            trigger: Trigger phrase

        Returns:
            List of matching skills

        Raises:
            RuntimeError: If registry not initialized
        """
        if self._loader is None:
            raise RuntimeError("SkillRegistry not initialized. Call initialize() first.")
        return self._loader.find_by_trigger(trigger)

    def get_summary(self) -> Dict:
        """Get registry summary.

        Returns:
            Summary dictionary

        Raises:
            RuntimeError: If registry not initialized
        """
        if self._loader is None:
            raise RuntimeError("SkillRegistry not initialized. Call initialize() first.")
        return self._loader.get_summary()
