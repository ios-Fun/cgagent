"""
Agent Skills Framework Core Module

This module provides the core abstractions and implementations for the
Agent Skills Framework, including base skill interfaces, skill registry,
and context management.
"""

from .interfaces import (
    ExecutionMode,
    SkillStatus,
    SkillMetadata,
    ExecutionResult,
    ValidationResult,
    ExecutionStatus,
    SkillExecutionError,
    ISkill,
    IContextManager,
    ISkillRegistry,
    CoreError,
    ValidationError,
    ExecutionError,
    RegistryError,
)

from .base_skill import (
    BaseSkill,
    SkillInput,
    SkillOutput,
)

from .skill_registry import (
    SkillRegistry,
    RegistryConfig,
    HotReloadConfig,
    HealthStatus,
    SkillVersionInfo,
)

from .context_manager import (
    ContextManager,
    LayerType,
    ContextValidationError,
    ContextSerializationError,
)
from .interfaces import ContextLayer

__all__ = [
    # Enums
    "ExecutionMode",
    "SkillStatus",
    "ExecutionStatus",
    "LayerType",
    "HealthStatus",
    # Dataclasses
    "SkillMetadata",
    "ExecutionResult",
    "ValidationResult",
    "RegistryConfig",
    "HotReloadConfig",
    "SkillVersionInfo",
    "ContextLayer",
    # Type aliases
    "SkillInput",
    "SkillOutput",
    # Abstract classes
    "BaseSkill",
    "ISkill",
    "IContextManager",
    "ISkillRegistry",
    # Concrete classes
    "SkillRegistry",
    "ContextManager",
    # Exceptions
    "CoreError",
    "ValidationError",
    "ExecutionError",
    "RegistryError",
    "SkillExecutionError",
    "ContextValidationError",
    "ContextSerializationError",
]

__version__ = "1.0.0"
