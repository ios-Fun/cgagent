"""Public interface definitions for Agent Skills Framework Core.

This module defines abstract interfaces and protocols used throughout
the framework for skill management, context handling, and execution.
"""

from abc import ABC, abstractmethod
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Protocol,
    Tuple,
    TypeVar,
    Union,
    runtime_checkable,
)
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path


# Type variables for generic types
T = TypeVar("T")
InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


class ExecutionMode(Enum):
    """Execution mode for skills."""

    EXECUTOR = auto()  # Custom Python code (executor.py)
    TEMPLATE = auto()  # Template-based LLM (prompt.template)
    DOCUMENT = auto()  # Document-based (SKILL.md only)


class SkillStatus(Enum):
    """Status of a skill in the registry."""

    ACTIVE = auto()
    DISABLED = auto()
    ERROR = auto()
    LOADING = auto()


class ExecutionStatus(Enum):
    """Status of skill execution."""

    PENDING = auto()
    RUNNING = auto()
    SUCCESS = auto()
    FAILED = auto()
    CANCELLED = auto()


@dataclass(frozen=True)
class SkillMetadata:
    """Immutable metadata for a skill."""

    name: str
    version: str
    description: str
    author: str = ""
    tags: Tuple[str, ...] = ()
    triggers: Tuple[str, ...] = ()
    dependencies: Tuple[str, ...] = ()
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "tags": list(self.tags),
            "triggers": list(self.triggers),
            "dependencies": list(self.dependencies),
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
        }


@dataclass
class ExecutionResult:
    """Result of skill execution."""

    success: bool
    output: Any
    text: str
    execution_time_ms: float
    metadata: Dict[str, Any]
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "output": self.output,
            "text": self.text,
            "execution_time_ms": self.execution_time_ms,
            "metadata": self.metadata,
            "error": self.error,
        }


@dataclass
class ValidationResult:
    """Result of validation."""

    valid: bool
    errors: List[str]
    warnings: List[str]

    def __init__(self, valid: bool = True, errors: Optional[List[str]] = None, warnings: Optional[List[str]] = None):
        self.valid = valid
        self.errors = errors or []
        self.warnings = warnings or []


# Abstract Base Classes

class ISkill(ABC):
    """Abstract interface for skills."""

    @property
    @abstractmethod
    def metadata(self) -> SkillMetadata:
        """Get skill metadata."""
        pass

    @property
    @abstractmethod
    def execution_mode(self) -> ExecutionMode:
        """Get execution mode."""
        pass

    @abstractmethod
    def validate_input(self, input_data: Any) -> ValidationResult:
        """Validate input data."""
        pass

    @abstractmethod
    def execute(self, input_data: Any, context: Dict[str, Any]) -> ExecutionResult:
        """Execute the skill."""
        pass

    @abstractmethod
    def validate_output(self, output_data: Any) -> ValidationResult:
        """Validate output data."""
        pass


class IContextManager(ABC):
    """Abstract interface for context management."""

    @abstractmethod
    def get_layer(self, layer_name: str) -> Dict[str, Any]:
        """Get a context layer."""
        pass

    @abstractmethod
    def set_layer(self, layer_name: str, data: Dict[str, Any]) -> None:
        """Set a context layer."""
        pass

    @abstractmethod
    def read(self, layer_name: str, key: str) -> Any:
        """Read a value from a layer."""
        pass

    @abstractmethod
    def write(self, layer_name: str, key: str, value: Any) -> None:
        """Write a value to a layer."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all context data."""
        pass


class ISkillRegistry(ABC):
    """Abstract interface for skill registry."""

    @abstractmethod
    def register(self, skill: ISkill) -> None:
        """Register a skill."""
        pass

    @abstractmethod
    def unregister(self, skill_name: str) -> None:
        """Unregister a skill."""
        pass

    @abstractmethod
    def get(self, skill_name: str) -> ISkill:
        """Get a skill by name."""
        pass

    @abstractmethod
    def list_skills(self) -> List[ISkill]:
        """List all registered skills."""
        pass

    @abstractmethod
    def find_by_trigger(self, trigger: str) -> List[ISkill]:
        """Find skills matching a trigger."""
        pass


# Protocols (for structural subtyping)

@runtime_checkable
class IValidatable(Protocol):
    """Protocol for validatable objects."""

    def validate(self) -> ValidationResult:
        """Validate the object."""
        ...


@runtime_checkable
class IExecutable(Protocol):
    """Protocol for executable objects."""

    def execute(self, context: Dict[str, Any]) -> ExecutionResult:
        """Execute with given context."""
        ...


@runtime_checkable
class IReloadable(Protocol):
    """Protocol for reloadable objects."""

    def reload(self) -> None:
        """Reload the object."""
        ...


@runtime_checkable
class IHealthCheckable(Protocol):
    """Protocol for health-checkable objects."""

    def health_check(self) -> Tuple[bool, Dict[str, Any]]:
        """Return (healthy, details) tuple."""
        ...


# Exception types

class CoreError(Exception):
    """Base exception for core module."""

    def __init__(self, message: str, code: str = "", details: Optional[Dict] = None):
        self.code = code
        self.details = details or {}
        super().__init__(message)


class ValidationError(CoreError):
    """Validation error."""

    def __init__(self, message: str, field: Optional[str] = None):
        self.field = field
        super().__init__(message, code="VALIDATION_ERROR", details={"field": field})


class ExecutionError(CoreError):
    """Execution error."""

    def __init__(self, message: str, skill_name: Optional[str] = None):
        self.skill_name = skill_name
        super().__init__(message, code="EXECUTION_ERROR", details={"skill": skill_name})


class RegistryError(CoreError):
    """Registry error."""

    def __init__(self, message: str, skill_name: Optional[str] = None):
        self.skill_name = skill_name
        super().__init__(message, code="REGISTRY_ERROR", details={"skill": skill_name})


class SkillExecutionError(CoreError):
    """Skill execution error."""

    def __init__(self, skill_name: str, message: str, cause: Optional[Exception] = None):
        self.skill_name = skill_name
        self.cause = cause
        details = {"skill": skill_name}
        if cause:
            details["cause"] = str(cause)
        super().__init__(message, code="EXECUTION_ERROR", details=details)


# Additional classes needed by context_manager.py

class ContextLayer(Enum):
    """Three-layer context architecture layers."""

    USER_INPUT = auto()    # Layer 1: User input and conversation history
    SCRATCHPAD = auto()    # Layer 2: Working memory for skill execution
    ENVIRONMENT = auto()   # Layer 3: Environment configuration


class PermissionLevel(Enum):
    """Permission levels for context access control."""

    NONE = auto()      # No access
    READ = auto()      # Read-only access
    WRITE = auto()     # Read and write access
    ADMIN = auto()     # Full administrative access


class ContextError(CoreError):
    """Context management error."""

    def __init__(self, message: str, layer: Optional[ContextLayer] = None):
        self.layer = layer
        details = {"layer": layer.value if layer else None}
        super().__init__(message, code="CONTEXT_ERROR", details=details)


class ContextValidationError(ContextError):
    """Context validation error."""

    def __init__(self, message: str, layer: Optional[ContextLayer] = None, field: Optional[str] = None):
        super().__init__(message, layer)
        self.field = field


class ContextSerializationError(ContextError):
    """Context serialization error."""

    def __init__(self, message: str, layer: Optional[ContextLayer] = None, format: Optional[str] = None):
        super().__init__(message, layer)
        self.format = format


class PermissionError(CoreError):
    """Permission error for context access."""

    def __init__(self, message: str, component: str = "", layer: Optional[ContextLayer] = None):
        self.component = component
        self.layer = layer
        details = {
            "component": component,
            "layer": layer.value if layer else None
        }
        super().__init__(message, code="PERMISSION_ERROR", details=details)


__all__ = [
    # Enums
    "ExecutionMode",
    "SkillStatus",
    "ExecutionStatus",
    "ContextLayer",
    "PermissionLevel",
    # Dataclasses
    "SkillMetadata",
    "ExecutionResult",
    "ValidationResult",
    # Abstract classes
    "ISkill",
    "IContextManager",
    "ISkillRegistry",
    # Protocols
    "IValidatable",
    "IExecutable",
    "IReloadable",
    "IHealthCheckable",
    # Exceptions
    "CoreError",
    "ValidationError",
    "ExecutionError",
    "RegistryError",
    "SkillExecutionError",
    "ContextError",
    "PermissionError",
]
