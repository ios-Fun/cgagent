"""Three-layer context management for Agent Skills Framework."""

import time
from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field
from enum import Enum

# from .audit import AuditLog, AuditLayer, AuditOp
from .scratchpad import Scratchpad
from .token_budget import TokenBudget
from .errors import ContextValidationError


class ContextPermission(Enum):
    """Permission levels for context access."""
    READ = "read"
    WRITE = "write"
    NONE = "none"


@dataclass
class LayerPermissions:
    """Permissions for each layer."""
    layer1_user_input: Dict[str, ContextPermission] = field(default_factory=dict)
    layer2_scratchpad: Dict[str, ContextPermission] = field(default_factory=dict)
    layer3_environment: Dict[str, ContextPermission] = field(default_factory=dict)


# Default permissions for each component
DEFAULT_PERMISSIONS = {
    "planner": LayerPermissions(
        layer1_user_input={
            "any": ContextPermission.READ,
            "conversation_history": ContextPermission.READ,
            "parsed_intent": ContextPermission.WRITE,
            "execution_plan": ContextPermission.WRITE,
            "skill_route": ContextPermission.WRITE,
            "intent": ContextPermission.WRITE
        },
        layer2_scratchpad={},
        layer3_environment={"any": ContextPermission.READ}
    ),
    "executor": LayerPermissions(
        layer1_user_input={"any": ContextPermission.READ, "conversation_history": ContextPermission.READ},
        layer2_scratchpad={"any": ContextPermission.WRITE},
        layer3_environment={"any": ContextPermission.READ}
    ),
    "synthesizer": LayerPermissions(
        layer1_user_input={"any": ContextPermission.READ, "conversation_history": ContextPermission.READ},
        layer2_scratchpad={"any": ContextPermission.READ},
        layer3_environment={"any": ContextPermission.READ}
    ),
    "coordinator": LayerPermissions(
        layer1_user_input={"any": ContextPermission.WRITE},
        layer2_scratchpad={"any": ContextPermission.WRITE},
        layer3_environment={"any": ContextPermission.WRITE}
    )
}


class AgentContext:
    """Three-layer context manager for Agent Skills Framework.

    Layer 1 (user_input): User input, parsed intent, execution plan
    Layer 2 (scratchpad): Working memory, skill results, failed steps
    Layer 3 (environment): Available skills, token budget, model config

    Each layer has permission control to prevent unauthorized access.
    """

    def __init__(self, enable_audit: bool = True):
        """Initialize context.

        Args:
            enable_audit: Whether to enable audit logging
        """
        # Layer 1: User Input Layer
        self._layer1: Dict[str, Any] = {
            "raw_user_input": "",
            "parsed_intent": "",
            "execution_plan": {},
            "conversation_history": []
        }

        # Layer 2: Scratchpad (Working Memory)
        self._scratchpad = Scratchpad()

        # Layer 3: Environment Layer
        self._layer3: Dict[str, Any] = {
            "available_skills": {},
            "token_budget": None,
            "model_config": {},
            "tools_registry": None
        }

        # Audit and monitoring
        # self.audit_log = AuditLog() if enable_audit else None
        # self.enable_audit = enable_audit

        # Current component (for permission checking)
        self._current_component: Optional[str] = None

    def set_component(self, component: str) -> None:
        """Set current component for permission checking.

        Args:
            component: Component name (planner, executor, synthesizer, coordinator)
        """
        if component not in DEFAULT_PERMISSIONS and component != "coordinator":
            raise ContextValidationError(f"Unknown component: {component}")
        self._current_component = component

    def _check_permission(
        self,
        layer: str,
        operation: str,
        key: str = ""
    ) -> bool:
        """Check if current component has permission for operation.

        Args:
            layer: Layer name (layer1_user_input, layer2_scratchpad, layer3_environment)
            operation: Operation type (read, write)
            key: Key being accessed

        Returns:
            True if permitted, False otherwise
        """
        if self._current_component == "coordinator":
            return True

        permissions = DEFAULT_PERMISSIONS.get(self._current_component)
        if not permissions:
            return False

        layer_perms = getattr(permissions, layer, {})
        perm = layer_perms.get("any", ContextPermission.NONE)
        if key in layer_perms:
            perm = layer_perms[key]

        return (
            (operation == "read" and perm in (ContextPermission.READ, ContextPermission.WRITE)) or
            (operation == "write" and perm == ContextPermission.WRITE)
        )

    # ─── Layer 1: User Input Layer ───

    def write_layer1(self, key: str, value: Any, source: str = "") -> None:
        """Write to Layer 1.

        Args:
            key: Key to write
            value: Value to write
            source: Source component name
        """
        if not self._check_permission("layer1_user_input", "write", key):
            raise ContextValidationError(f"No write permission for layer1.{key}")

        start_time = time.time()
        self._layer1[key] = value
        exec_time = (time.time() - start_time) * 1000

        # if self.audit_log:
        #     self.audit_log.record(
        #         layer=AuditLayer.USER_INPUT,
        #         op=AuditOp.WRITE,
        #         key=key,
        #         source=source or self._current_component or "unknown",
        #         value=value,
        #         execution_time_ms=exec_time
        #     )

    def read_layer1(self, key: str, source: str = "") -> Any:
        """Read from Layer 1.

        Args:
            key: Key to read
            source: Source component name

        Returns:
            Value if found, None otherwise
        """
        if not self._check_permission("layer1_user_input", "read", key):
            raise ContextValidationError(f"No read permission for layer1.{key}")

        start_time = time.time()
        value = self._layer1.get(key)
        exec_time = (time.time() - start_time) * 1000

        # if self.audit_log:
        #     self.audit_log.record(
        #         layer=AuditLayer.USER_INPUT,
        #         op=AuditOp.READ,
        #         key=key,
        #         source=source or self._current_component or "unknown",
        #         value=value,
        #         execution_time_ms=exec_time
        #     )

        return value

    def get_layer1(self) -> Dict[str, Any]:
        """Get entire Layer 1 (for coordinator)."""
        if self._current_component != "coordinator":
            raise ContextValidationError("Only coordinator can access entire layer")
        return self._layer1.copy()

    # ─── Layer 2: Scratchpad Layer ───

    @property
    def scratchpad(self) -> Scratchpad:
        """Get scratchpad instance."""
        return self._scratchpad

    def write_scratchpad(
        self,
        skill_name: str,
        sub_task: str,
        structured: Dict[str, Any],
        text: str,
        success: bool = True,
        error: str = "",
        execution_time_ms: float = 0,
        source: str = ""
    ) -> None:
        """Write to scratchpad.

        Args:
            skill_name: Name of the skill
            sub_task: Sub-task description
            structured: Structured data output
            text: Natural language output
            success: Whether execution succeeded
            error: Error message if failed
            execution_time_ms: Execution time
            source: Source component name
        """
        if not self._check_permission("layer2_scratchpad", "write"):
            raise ContextValidationError("No write permission for scratchpad")

        self._scratchpad.set_result(
            skill_name, sub_task, structured, text, success, error, execution_time_ms
        )

        # if self.audit_log:
        #     self.audit_log.record(
        #         layer=AuditLayer.SCRATCHPAD,
        #         op=AuditOp.WRITE,
        #         key=skill_name,
        #         source=source or self._current_component or "unknown",
        #         detail=sub_task,
        #         value={"structured": structured, "text": text}
        #     )

    def read_scratchpad(self, skill_name: str = "", source: str = "") -> Any:
        """Read from scratchpad.

        Args:
            skill_name: Specific skill name (empty for all)
            source: Source component name

        Returns:
            Skill result or all results
        """
        if not self._check_permission("layer2_scratchpad", "read"):
            raise ContextValidationError("No read permission for scratchpad")

        if skill_name:
            value = self._scratchpad.get_result(skill_name)
        else:
            value = self._scratchpad.get_all_results()

        # if self.audit_log and skill_name:
        #     self.audit_log.record(
        #         layer=AuditLayer.SCRATCHPAD,
        #         op=AuditOp.READ,
        #         key=skill_name,
        #         source=source or self._current_component or "unknown",
        #         value=value
        #     )

        return value

    def compress_scratchpad(self, skill_name: str, source: str = "") -> bool:
        """Compress a scratchpad result.

        Args:
            skill_name: Name of skill to compress
            source: Source component name

        Returns:
            True if compressed
        """
        if not self._check_permission("layer2_scratchpad", "write"):
            raise ContextValidationError("No write permission for scratchpad")

        result = self._scratchpad.compress_result(skill_name)

        # if self.audit_log and result:
        #     self.audit_log.record(
        #         layer=AuditLayer.SCRATCHPAD,
        #         op=AuditOp.COMPRESS,
        #         key=skill_name,
        #         source=source or self._current_component or "unknown"
        #     )

        return result

    # ─── Layer 3: Environment Layer ───

    def write_layer3(self, key: str, value: Any, source: str = "") -> None:
        """Write to Layer 3.

        Args:
            key: Key to write
            value: Value to write
            source: Source component name
        """
        if not self._check_permission("layer3_environment", "write", key):
            raise ContextValidationError(f"No write permission for layer3.{key}")

        start_time = time.time()
        self._layer3[key] = value
        exec_time = (time.time() - start_time) * 1000

        # if self.audit_log:
        #     self.audit_log.record(
        #         layer=AuditLayer.ENVIRONMENT,
        #         op=AuditOp.WRITE,
        #         key=key,
        #         source=source or self._current_component or "unknown",
        #         value=value,
        #         execution_time_ms=exec_time
        #     )

    def read_layer3(self, key: str, source: str = "") -> Any:
        """Read from Layer 3.

        Args:
            key: Key to read
            source: Source component name

        Returns:
            Value if found, None otherwise
        """
        if not self._check_permission("layer3_environment", "read", key):
            raise ContextValidationError(f"No read permission for layer3.{key}")

        start_time = time.time()
        value = self._layer3.get(key)
        exec_time = (time.time() - start_time) * 1000

        # if self.audit_log:
        #     self.audit_log.record(
        #         layer=AuditLayer.ENVIRONMENT,
        #         op=AuditOp.READ,
        #         key=key,
        #         source=source or self._current_component or "unknown",
        #         value=value,
        #         execution_time_ms=exec_time
        #     )

        return value

    def get_layer3(self) -> Dict[str, Any]:
        """Get entire Layer 3 (for coordinator)."""
        if self._current_component != "coordinator":
            raise ContextValidationError("Only coordinator can access entire layer")
        return self._layer3.copy()

    # ─── Utility Methods ───

    def get_summary(self) -> Dict[str, Any]:
        """Get context summary."""
        return {
            "layer1_keys": list(self._layer1.keys()),
            "scratchpad_summary": self._scratchpad.get_summary(),
            "layer3_keys": list(self._layer3.keys()),
            "audit_entries": len(self.audit_log.entries) if self.audit_log else 0
        }

    def clear(self) -> None:
        """Clear all context data."""
        self._layer1 = {
            "raw_user_input": "",
            "parsed_intent": "",
            "execution_plan": {},
            "conversation_history": []
        }
        self._scratchpad = Scratchpad()
        if self.audit_log:
            self.audit_log.clear()

    def prepare_for_step(
        self,
        step: Dict,
        include_history: bool = False
    ) -> Dict[str, Any]:
        """Prepare context input for a Skill execution step.

        Args:
            step: Step definition
            include_history: Whether to include conversation history

        Returns:
            Prepared context dictionary
        """
        context = {
            "sub_task": step.get("sub_task", ""),
            "user_input": self._layer1.get("raw_user_input", ""),
            "previous_results": {},
            "conversation_history": []
        }

        # Add previous skill results (progressive disclosure)
        if self._scratchpad._results:
            # Get ordered results
            ordered = self._scratchpad.get_ordered_results()

            # Apply compression strategy
            compression_ratio = 0
            if self._layer3.get("token_budget"):
                compression_ratio = self._layer3["token_budget"].get_compression_ratio()

            # Add results based on compression
            for i, result in enumerate(ordered):
                if i == len(ordered) - 1:
                    # Always include full latest result
                    context["previous_results"][result.skill_name] = {
                        "structured": result.structured,
                        "text": result.text
                    }
                elif compression_ratio > 0.5 and i < len(ordered) - 2:
                    # Compress older results
                    context["previous_results"][result.skill_name] = {
                        "compressed": True
                    }
                else:
                    # Include full result
                    context["previous_results"][result.skill_name] = {
                        "structured": result.structured,
                        "text": result.text
                    }

        # Add conversation history (only for first step)
        if include_history:
            context["conversation_history"] = self._layer1.get("conversation_history", [])

        return context

    def export_audit(self) -> List[Dict]:
        """Export audit log."""
        return self.audit_log.export() if self.audit_log else []
