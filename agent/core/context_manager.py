"""Context manager module for Agent Skills Framework.

This module provides the three-layer context management system using
the Template Method pattern to eliminate code duplication.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Callable, Union, TypeVar
from enum import Enum
from datetime import datetime

from .interfaces import (
    ContextLayer,
    PermissionLevel,
    ValidationResult,
    ContextError,
    PermissionError,
)


# ============================================================================
# Enums and Constants
# ============================================================================

class LayerType(Enum):
    """Type of context layer."""
    USER_INPUT = "user_input"
    SCRATCHPAD = "scratchpad"
    ENVIRONMENT = "environment"


class ComponentType(Enum):
    """Component types for permission control."""
    PLANNER = "planner"
    EXECUTOR = "executor"
    SYNTHESIZER = "synthesizer"
    COORDINATOR = "coordinator"
    SKILL = "skill"


# Default permissions for each component
DEFAULT_PERMISSIONS: Dict[ComponentType, Dict[ContextLayer, PermissionLevel]] = {
    ComponentType.PLANNER: {
        ContextLayer.USER_INPUT: PermissionLevel.READ,
        ContextLayer.SCRATCHPAD: PermissionLevel.NONE,
        ContextLayer.ENVIRONMENT: PermissionLevel.READ,
    },
    ComponentType.EXECUTOR: {
        ContextLayer.USER_INPUT: PermissionLevel.READ,
        ContextLayer.SCRATCHPAD: PermissionLevel.WRITE,
        ContextLayer.ENVIRONMENT: PermissionLevel.READ,
    },
    ComponentType.SYNTHESIZER: {
        ContextLayer.USER_INPUT: PermissionLevel.READ,
        ContextLayer.SCRATCHPAD: PermissionLevel.READ,
        ContextLayer.ENVIRONMENT: PermissionLevel.READ,
    },
    ComponentType.COORDINATOR: {
        ContextLayer.USER_INPUT: PermissionLevel.WRITE,
        ContextLayer.SCRATCHPAD: PermissionLevel.WRITE,
        ContextLayer.ENVIRONMENT: PermissionLevel.WRITE,
    },
}


# ============================================================================
# Audit Entry
# ============================================================================

@dataclass
@dataclass
class ContextValidationError(Exception):
    """Context validation error."""
    message: str
    field: str = ""


@dataclass
class ContextSerializationError(Exception):
    """Context serialization error."""
    message: str
    format: str = ""


@dataclass
class AuditEntry:
    """Context operation audit entry."""
    timestamp: float
    layer: ContextLayer
    operation: str
    key: str
    component: str
    value_preview: str = ""
    execution_time_ms: float = 0.0


# ============================================================================
# BaseContext - Template Method Pattern
# ============================================================================

class BaseContext(ABC):
    """Context基类，使用模板方法模式。

    该类定义了数据访问的标准算法骨架：
    1. 加载数据
    2. 应用默认值（如果需要）
    3. 验证数据
    4. 保存数据
    5. 通知变更

    子类只需要实现特定的抽象方法即可。
    """

    def __init__(self, layer: ContextLayer):
        """Initialize context.

        Args:
            layer: Context layer identifier
        """
        self._layer = layer
        self._data: Dict[str, Any] = {}
        self._audit_log: List[AuditEntry] = []
        self._current_component: Optional[ComponentType] = None
        self._enable_audit = True

    # ========================================================================
    # Template Methods - Define algorithm skeleton
    # ========================================================================

    def get_data(self, key: str, default: Any = None) -> Any:
        """Template method - Get data with full pipeline.

        Args:
            key: Data key
            default: Default value if not found

        Returns:
            Data value
        """
        self._check_permission("read", key)

        start_time = time.perf_counter()

        # Step 1: Load data
        data = self._load_data(key)

        # Step 2: Apply default if needed
        if data is None:
            data = self._default_value(key, default)

        # Step 3: Validate data
        data = self._validate_data(key, data)

        # Step 4: Audit
        exec_time = (time.perf_counter() - start_time) * 1000
        self._audit("read", key, data, exec_time)

        return data

    def set_data(self, key: str, value: Any) -> None:
        """Template method - Set data with full pipeline.

        Args:
            key: Data key
            value: Data value
        """
        self._check_permission("write", key)

        start_time = time.perf_counter()

        # Step 1: Validate data
        validated = self._validate_data(key, value)

        # Step 2: Transform data (hook)
        validated = self._transform_data(key, validated)

        # Step 3: Save data
        self._save_data(key, validated)

        # Step 4: Notify change
        exec_time = (time.perf_counter() - start_time) * 1000
        self._notify_change(key, validated)
        self._audit("write", key, value, exec_time)

    def delete_data(self, key: str) -> bool:
        """Template method - Delete data with full pipeline.

        Args:
            key: Data key

        Returns:
            True if deleted, False if not found
        """
        self._check_permission("write", key)

        # Step 1: Check existence
        if not self._exists(key):
            return False

        # Step 2: Delete data
        self._delete_data(key)

        # Step 3: Notify change
        self._notify_change(key, None)
        self._audit("delete", key, None, 0)

        return True

    # ========================================================================
    # Abstract Methods - Must be implemented by subclasses
    # ========================================================================

    @abstractmethod
    def _load_data(self, key: str) -> Any:
        """Load data from storage.

        Args:
            key: Data key

        Returns:
            Data value or None if not found
        """
        pass

    @abstractmethod
    def _save_data(self, key: str, value: Any) -> None:
        """Save data to storage.

        Args:
            key: Data key
            value: Data value
        """
        pass

    @abstractmethod
    def _delete_data(self, key: str) -> None:
        """Delete data from storage.

        Args:
            key: Data key
        """
        pass

    @abstractmethod
    def _exists(self, key: str) -> bool:
        """Check if key exists.

        Args:
            key: Data key

        Returns:
            True if exists, False otherwise
        """
        pass

    # ========================================================================
    # Hook Methods - Can be overridden by subclasses
    # ========================================================================

    def _validate_data(self, key: str, data: Any) -> Any:
        """Validate data before save or after load.

        Args:
            key: Data key
            data: Data value

        Returns:
            Validated/transformed data
        """
        return data

    def _default_value(self, key: str, default: Any) -> Any:
        """Get default value for key.

        Args:
            key: Data key
            default: Default value provided by caller

        Returns:
            Default value
        """
        return default

    def _transform_data(self, key: str, data: Any) -> Any:
        """Transform data before saving.

        Args:
            key: Data key
            data: Data value

        Returns:
            Transformed data
        """
        return data

    def _notify_change(self, key: str, value: Any) -> None:
        """Notify that data has changed.

        Args:
            key: Data key
            value: New value (None if deleted)
        """
        pass

    def _check_permission(self, operation: str, key: str) -> None:
        """Check if current component has permission.

        Args:
            operation: Operation type (read, write, delete)
            key: Data key

        Raises:
            PermissionError: If permission denied
        """
        if not self._current_component:
            # No component set, allow access
            return

        if self._current_component == ComponentType.COORDINATOR:
            # Coordinator has full access
            return

        permissions = DEFAULT_PERMISSIONS.get(self._current_component, {})
        required_perm = PermissionLevel.WRITE if operation != "read" else PermissionLevel.READ
        actual_perm = permissions.get(self._layer, PermissionLevel.NONE)

        if actual_perm.value < required_perm.value:
            raise PermissionError(
                f"Permission denied: {self._current_component.value} cannot {operation} on {self._layer.value}"
            )

    def _audit(self, operation: str, key: str, value: Any, exec_time: float) -> None:
        """Record audit entry.

        Args:
            operation: Operation type
            key: Data key
            value: Data value (for preview)
            exec_time: Execution time in milliseconds
        """
        if not self._enable_audit:
            return

        # Truncate value for preview
        value_str = str(value)[:100] if value is not None else ""

        entry = AuditEntry(
            timestamp=time.time(),
            layer=self._layer,
            operation=operation,
            key=key,
            component=self._current_component.value if self._current_component else "unknown",
            value_preview=value_str,
            execution_time_ms=exec_time
        )
        self._audit_log.append(entry)

    # ========================================================================
    # Context Management
    # ========================================================================

    def set_component(self, component: ComponentType) -> None:
        """Set current component for permission checking.

        Args:
            component: Component type
        """
        self._current_component = component

    def clear_component(self) -> None:
        """Clear current component."""
        self._current_component = None

    def get_audit_log(self, limit: Optional[int] = None) -> List[AuditEntry]:
        """Get audit log.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of audit entries
        """
        if limit:
            return self._audit_log[-limit:]
        return self._audit_log.copy()

    def clear_audit_log(self) -> None:
        """Clear audit log."""
        self._audit_log.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get context statistics.

        Returns:
            Statistics dictionary
        """
        return {
            "layer": self._layer.value,
            "data_keys": list(self._data.keys()),
            "audit_entries": len(self._audit_log),
            "current_component": self._current_component.value if self._current_component else None,
        }


# ============================================================================
# Layer-Specific Context Classes
# ============================================================================

class Layer1Context(BaseContext):
    """Layer 1: User Input Layer.

    Stores user input, parsed intent, execution plan, and conversation history.
    """

    def __init__(self):
        super().__init__(ContextLayer.USER_INPUT)

    def _load_data(self, key: str) -> Any:
        return self._data.get(key)

    def _save_data(self, key: str, value: Any) -> None:
        self._data[key] = value

    def _delete_data(self, key: str) -> None:
        self._data.pop(key, None)

    def _exists(self, key: str) -> bool:
        return key in self._data

    def _default_value(self, key: str, default: Any) -> Any:
        defaults = {
            "raw_user_input": "",
            "parsed_intent": "",
            "execution_plan": {},
            "conversation_history": [],
        }
        return defaults.get(key, default)


class Layer2Context(BaseContext):
    """Layer 2: Scratchpad / Working Memory Layer.

    Stores skill execution results and working memory.
    """

    def __init__(self):
        super().__init__(ContextLayer.SCRATCHPAD)
        self._results: Dict[str, Any] = {}
        self._current_step: Optional[int] = None
        self._failed_steps: List[Dict] = []

    def _load_data(self, key: str) -> Any:
        if key.startswith("result:"):
            return self._results.get(key[7:])
        if key == "current_step":
            return self._current_step
        if key == "failed_steps":
            return self._failed_steps
        return self._data.get(key)

    def _save_data(self, key: str, value: Any) -> None:
        if key.startswith("result:"):
            self._results[key[7:]] = value
        elif key == "current_step":
            self._current_step = value
        elif key == "failed_steps":
            self._failed_steps = value
        else:
            self._data[key] = value

    def _delete_data(self, key: str) -> None:
        if key.startswith("result:"):
            self._results.pop(key[7:], None)
        elif key in self._data:
            del self._data[key]

    def _exists(self, key: str) -> bool:
        if key.startswith("result:"):
            return key[7:] in self._results
        return key in self._data

    def set_result(self, skill_name: str, result: Any) -> None:
        """Set skill execution result."""
        self.set_data(f"result:{skill_name}", result)

    def get_result(self, skill_name: str) -> Any:
        """Get skill execution result."""
        return self.get_data(f"result:{skill_name}")

    def record_failure(self, step: Dict, error: str, attempt: int) -> None:
        """Record a failed execution step."""
        self._failed_steps.append({
            "step": step,
            "error": error,
            "attempt": attempt,
            "timestamp": time.time(),
        })
        self.set_data("failed_steps", self._failed_steps)


class Layer3Context(BaseContext):
    """Layer 3: Environment Layer.

    Stores available skills, token budget, model config, and tools registry.
    """

    def __init__(self):
        super().__init__(ContextLayer.ENVIRONMENT)
        self._skills_registry: Optional[Any] = None
        self._token_budget: Optional[Any] = None
        self._model_config: Dict[str, Any] = {}
        self._tools_registry: Optional[Any] = None

    def _load_data(self, key: str) -> Any:
        special_keys = {
            "skills_registry": self._skills_registry,
            "token_budget": self._token_budget,
            "model_config": self._model_config,
            "tools_registry": self._tools_registry,
        }
        if key in special_keys:
            return special_keys[key]
        return self._data.get(key)

    def _save_data(self, key: str, value: Any) -> None:
        if key == "skills_registry":
            self._skills_registry = value
        elif key == "token_budget":
            self._token_budget = value
        elif key == "model_config":
            self._model_config = value
        elif key == "tools_registry":
            self._tools_registry = value
        else:
            self._data[key] = value

    def _delete_data(self, key: str) -> None:
        special_keys = ["skills_registry", "token_budget", "model_config", "tools_registry"]
        if key in special_keys:
            setattr(self, f"_{key}", None)
        elif key in self._data:
            del self._data[key]

    def _exists(self, key: str) -> bool:
        special_keys = ["skills_registry", "token_budget", "model_config", "tools_registry"]
        if key in special_keys:
            return getattr(self, f"_{key}") is not None
        return key in self._data

    def _default_value(self, key: str, default: Any) -> Any:
        defaults = {
            "skills_registry": None,
            "token_budget": None,
            "model_config": {},
            "tools_registry": None,
        }
        return defaults.get(key, default)

    def set_skills_registry(self, registry: Any) -> None:
        """Set the skills registry."""
        self.set_data("skills_registry", registry)

    def get_skills_registry(self) -> Optional[Any]:
        """Get the skills registry."""
        return self.get_data("skills_registry")

    def set_token_budget(self, budget: Any) -> None:
        """Set the token budget."""
        self.set_data("token_budget", budget)

    def get_token_budget(self) -> Optional[Any]:
        """Get the token budget."""
        return self.get_data("token_budget")

    def set_model_config(self, config: Dict[str, Any]) -> None:
        """Set the model configuration."""
        self.set_data("model_config", config)

    def get_model_config(self) -> Dict[str, Any]:
        """Get the model configuration."""
        return self.get_data("model_config") or {}


# ============================================================================
# ContextManager - Facade for all layers
# ============================================================================

class ContextManager:
    """Facade class managing all three context layers.

    This class provides a unified interface for accessing all three
    context layers while maintaining separation of concerns.
    """

    def __init__(self, enable_audit: bool = True):
        """Initialize context manager.

        Args:
            enable_audit: Whether to enable audit logging
        """
        self._layer1 = Layer1Context()
        self._layer2 = Layer2Context()
        self._layer3 = Layer3Context()
        self._enable_audit = enable_audit

        # Set audit enabled state
        self._layer1._enable_audit = enable_audit
        self._layer2._enable_audit = enable_audit
        self._layer3._enable_audit = enable_audit

        # Track current component
        self._current_component: Optional[ComponentType] = None

    @property
    def layer1(self) -> Layer1Context:
        """Get Layer 1 (User Input) context."""
        return self._layer1

    @property
    def layer2(self) -> Layer2Context:
        """Get Layer 2 (Scratchpad) context."""
        return self._layer2

    @property
    def layer3(self) -> Layer3Context:
        """Get Layer 3 (Environment) context."""
        return self._layer3

    def set_component(self, component: ComponentType) -> None:
        """Set current component for permission checking.

        Args:
            component: Component type
        """
        self._current_component = component
        self._layer1._current_component = component
        self._layer2._current_component = component
        self._layer3._current_component = component

    def clear_component(self) -> None:
        """Clear current component."""
        self._current_component = None
        self._layer1._current_component = None
        self._layer2._current_component = None
        self._layer3._current_component = None

    def get_summary(self) -> Dict[str, Any]:
        """Get context manager summary.

        Returns:
            Summary dictionary
        """
        return {
            "layer1": self._layer1.get_stats(),
            "layer2": self._layer2.get_stats(),
            "layer3": self._layer3.get_stats(),
            "current_component": self._current_component.value if self._current_component else None,
            "audit_enabled": self._enable_audit,
        }

    def clear_all(self) -> None:
        """Clear all context data."""
        self._layer1._data.clear()
        self._layer1._audit_log.clear()

        self._layer2._data.clear()
        self._layer2._results.clear()
        self._layer2._audit_log.clear()

        self._layer3._data.clear()
        self._layer3._audit_log.clear()

    def prepare_for_step(self, step: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare context for a skill execution step.

        Args:
            step: Step definition containing sub_task, etc.

        Returns:
            Prepared context dictionary
        """
        context = {
            "sub_task": step.get("sub_task", ""),
            "user_input": self._layer1.get_data("raw_user_input", ""),
            "previous_results": {},
            "conversation_history": self._layer1.get_data("conversation_history", []),
        }

        # Add previous results from layer 2
        for skill_name in self._layer2._results:
            result = self._layer2.get_result(skill_name)
            if result:
                context["previous_results"][skill_name] = result

        return context
