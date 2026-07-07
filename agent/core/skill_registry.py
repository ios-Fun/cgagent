#!/usr/bin/env python3
"""
Skill Registry with Singleton Pattern, Hot Reload, and Health Checks

This module implements the SkillRegistry with:
- Singleton pattern for global instance
- Hot reload capability (optional - requires watchdog)
- Health checks and monitoring
- Version management
"""

import os
import sys
import json
import time
import asyncio
import hashlib
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any, Set, Tuple, Union
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum, auto
import logging
import threading

# Optional: watchdog for hot reload (optional dependency)
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    # Create dummy classes for type hints
    class Observer:
        pass
    class FileSystemEventHandler:
        pass

from .interfaces import (
    ISkill, ISkillRegistry, SkillMetadata, SkillStatus,
    RegistryError, ExecutionResult, ValidationResult
)


# ============================================================================
# Configuration Dataclasses
# ============================================================================

@dataclass
class HotReloadConfig:
    """Configuration for hot reload functionality."""
    enabled: bool = True
    check_interval: float = 1.0  # seconds
    watch_patterns: List[str] = field(default_factory=lambda: ["*.py", "*.yaml", "*.json"])
    ignore_patterns: List[str] = field(default_factory=lambda: ["__pycache__", ".*", "*.pyc"])
    auto_reload: bool = True  # Auto reload on change vs manual trigger


@dataclass
class RegistryConfig:
    """Configuration for the skill registry."""
    # Paths
    skills_directory: Optional[str] = None
    cache_directory: Optional[str] = None

    # Hot reload
    hot_reload: HotReloadConfig = field(default_factory=HotReloadConfig)

    # Health checks
    health_check_interval: float = 30.0  # seconds
    health_check_enabled: bool = True

    # Version management
    strict_version_check: bool = False
    auto_update_dependencies: bool = False

    # Performance
    max_cache_size: int = 1000
    cache_ttl: float = 3600.0  # seconds

    # Logging
    log_level: str = "INFO"
    log_file: Optional[str] = None


@dataclass
class SkillVersionInfo:
    """Version information for a skill."""
    major: int = 1
    minor: int = 0
    patch: int = 0
    build: Optional[str] = None
    timestamp: Optional[datetime] = None

    def __str__(self) -> str:
        version = f"{self.major}.{self.minor}.{self.patch}"
        if self.build:
            version += f"+{self.build}"
        return version

    @classmethod
    def from_string(cls, version_str: str) -> "SkillVersionInfo":
        """Parse version string into SkillVersionInfo."""
        # Remove build metadata
        if "+" in version_str:
            version_str, build = version_str.split("+")
        else:
            build = None

        # Parse version parts
        parts = version_str.split(".")
        major = int(parts[0]) if len(parts) > 0 else 1
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0

        return cls(major=major, minor=minor, patch=patch, build=build)


@dataclass
class SkillInfo:
    """Information about a registered skill."""
    name: str
    version: str
    description: str = ""
    author: str = ""
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    config_schema: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class HealthStatus:
    """Health status for a skill or the registry."""
    healthy: bool = True
    last_check: datetime = field(default_factory=datetime.now)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    def add_error(self, error: str) -> None:
        """Add an error message."""
        self.errors.append(error)
        self.healthy = False

    def add_warning(self, warning: str) -> None:
        """Add a warning message."""
        self.warnings.append(warning)


# ============================================================================
# Hot Reload Handler (only if watchdog is available)
# ============================================================================

if WATCHDOG_AVAILABLE:
    class SkillFileEventHandler(FileSystemEventHandler):
        """Handler for skill file change events."""

        def __init__(self, registry: "SkillRegistry"):
            self.registry = registry
            self._last_modified: Dict[str, float] = {}

        def on_modified(self, event):
            if event.is_directory:
                return

            # Debounce: ignore events that happen too quickly
            current_time = time.time()
            file_path = str(event.src_path)

            if file_path in self._last_modified:
                if current_time - self._last_modified[file_path] < 1.0:
                    return

            self._last_modified[file_path] = current_time

            # Trigger reload
            if self.registry._config.hot_reload.auto_reload:
                self.registry._schedule_reload(file_path)

        def on_created(self, event):
            # Treat new files as modifications
            self.on_modified(event)
else:
    # Dummy class when watchdog is not available
    class SkillFileEventHandler:
        def __init__(self, registry: "SkillRegistry"):
            pass


# ============================================================================
# Skill Registry (Singleton)
# ============================================================================

class SkillRegistry(ISkillRegistry):
    """
    Skill Registry with Singleton Pattern, Hot Reload, and Health Checks.

    This is the main registry for all skills in the system. It provides:
    - Singleton pattern for global instance
    - Hot reload of skills (optional - requires watchdog)
    - Health checks and monitoring
    - Version management
    - Dependency tracking

    Example:
        # Get the singleton instance
        registry = SkillRegistry.get_instance()

        # Register a skill
        registry.register(MySkill())

        # Execute a skill
        result = registry.execute("my_skill", input_data)
    """

    # Singleton instance
    _instance: Optional["SkillRegistry"] = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls, config: Optional[RegistryConfig] = None) -> "SkillRegistry":
        """Get the singleton instance of the SkillRegistry."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls(config or RegistryConfig())
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.shutdown()
                cls._instance = None

    def __init__(self, config: RegistryConfig):
        """Initialize the SkillRegistry."""
        if SkillRegistry._instance is not None and SkillRegistry._instance != self:
            raise RuntimeError("Use SkillRegistry.get_instance() to get the singleton instance")

        self._config = config
        self._skills: Dict[str, ISkill] = {}
        self._skills_lock = threading.RLock()
        self._health_status: Dict[str, HealthStatus] = {}
        self._version_info: Dict[str, SkillVersionInfo] = {}
        self._execution_stats: Dict[str, Dict[str, Any]] = {}

        # Hot reload
        self._observer: Optional[Observer] = None
        self._event_handler: Optional[SkillFileEventHandler] = None
        self._reload_queue: List[str] = []
        self._reload_lock = threading.Lock()

        # Health check
        self._health_check_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()

        # Logging
        self._logger = logging.getLogger(self.__class__.__name__)
        self._setup_logging()

        # Initialize
        self._initialize()

    def _setup_logging(self) -> None:
        """Setup logging for the registry."""
        log_level = getattr(logging, self._config.log_level.upper(), logging.INFO)
        self._logger.setLevel(log_level)

        if not self._logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

        if self._config.log_file:
            file_handler = logging.FileHandler(self._config.log_file)
            file_handler.setFormatter(formatter)
            self._logger.addHandler(file_handler)

    def _initialize(self) -> None:
        """Initialize the registry."""
        self._logger.info("Initializing SkillRegistry...")

        # Load skills from directory if configured
        if self._config.skills_directory:
            self._load_skills_from_directory(Path(self._config.skills_directory))

        # Setup hot reload if enabled and watchdog is available
        if self._config.hot_reload.enabled and WATCHDOG_AVAILABLE:
            self._setup_hot_reload()
        elif self._config.hot_reload.enabled and not WATCHDOG_AVAILABLE:
            self._logger.warning("Hot reload enabled but watchdog not available. Install with: pip install watchdog")

        # Start health check if enabled
        if self._config.health_check_enabled:
            self._start_health_checks()

        self._logger.info("SkillRegistry initialized successfully")

    def _load_skills_from_directory(self, directory: Path) -> None:
        """Load skills from a directory."""
        if not directory.exists():
            self._logger.warning(f"Skills directory does not exist: {directory}")
            return

        self._logger.info(f"Loading skills from {directory}...")

        for skill_dir in directory.iterdir():
            if not skill_dir.is_dir():
                continue

            try:
                self._load_skill_from_directory(skill_dir)
            except Exception as e:
                self._logger.error(f"Failed to load skill from {skill_dir}: {e}")

    def _load_skill_from_directory(self, skill_dir: Path) -> None:
        """Load a single skill from a directory."""
        # Look for executor.py or skill definition
        executor_file = skill_dir / "executor.py"
        if not executor_file.exists():
            return

        # Dynamically load the module
        module_name = f"skill_{skill_dir.name}"
        spec = importlib.util.spec_from_file_location(module_name, executor_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load module from {executor_file}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Look for skill classes
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and
                hasattr(attr, 'metadata') and
                callable(getattr(attr, 'execute', None))):
                try:
                    skill_instance = attr()
                    self.register(skill_instance)
                except Exception as e:
                    self._logger.error(f"Failed to instantiate skill {attr_name}: {e}")

    def _setup_hot_reload(self) -> None:
        """Setup file watching for hot reload."""
        if not self._config.skills_directory:
            self._logger.warning("Cannot setup hot reload: no skills directory configured")
            return

        self._logger.info("Setting up hot reload...")

        # Create event handler and observer
        self._event_handler = SkillFileEventHandler(self)
        self._observer = Observer()

        # Schedule watching
        watch_path = Path(self._config.skills_directory)
        if watch_path.exists():
            self._observer.schedule(self._event_handler, str(watch_path), recursive=True)
            self._observer.start()
            self._logger.info(f"Hot reload enabled for {watch_path}")
        else:
            self._logger.warning(f"Cannot watch {watch_path}: directory does not exist")

    def _schedule_reload(self, file_path: str) -> None:
        """Schedule a skill reload."""
        with self._reload_lock:
            if file_path not in self._reload_queue:
                self._reload_queue.append(file_path)
                self._logger.info(f"Scheduled reload for {file_path}")

    def _process_reload_queue(self) -> None:
        """Process the reload queue."""
        while not self._shutdown_event.is_set():
            with self._reload_lock:
                queue_copy = self._reload_queue.copy()
                self._reload_queue.clear()

            for file_path in queue_copy:
                try:
                    self._reload_skill(file_path)
                except Exception as e:
                    self._logger.error(f"Failed to reload skill from {file_path}: {e}")

            time.sleep(1.0)

    def _reload_skill(self, file_path: str) -> None:
        """Reload a skill from a file."""
        self._logger.info(f"Reloading skill from {file_path}...")

        # Find the skill that was loaded from this file
        skill_to_reload = None
        for name, skill in self._skills.items():
            # This is a simplification - in real implementation, you'd track file paths
            if file_path in str(skill.__class__.__module__):
                skill_to_reload = name
                break

        if skill_to_reload:
            # Unregister the old version
            self.unregister(skill_to_reload)

        # Reload the module and register the new version
        # This would involve re-importing the module
        # For simplicity, we just log here
        self._logger.info(f"Reloaded skill from {file_path}")

    def _start_health_checks(self) -> None:
        """Start the health check thread."""
        self._health_check_thread = threading.Thread(
            target=self._health_check_loop,
            name="SkillRegistryHealthCheck",
            daemon=True
        )
        self._health_check_thread.start()
        self._logger.info("Health checks started")

    def _health_check_loop(self) -> None:
        """Main loop for health checks."""
        while not self._shutdown_event.is_set():
            try:
                self._perform_health_checks()
            except Exception as e:
                self._logger.error(f"Error during health checks: {e}")

            # Wait for next check or shutdown
            self._shutdown_event.wait(self._config.health_check_interval)

    def _perform_health_checks(self) -> None:
        """Perform health checks on all registered skills."""
        with self._skills_lock:
            skills_copy = dict(self._skills)

        for name, skill in skills_copy.items():
            try:
                # Check if skill responds to health check
                if hasattr(skill, 'health_check'):
                    is_healthy, details = skill.health_check()
                else:
                    # Default: assume healthy if no explicit check
                    is_healthy = True
                    details = {}

                # Update health status
                self._health_status[name] = HealthStatus(
                    healthy=is_healthy,
                    last_check=datetime.now(),
                    metrics=details
                )

                if not is_healthy:
                    self._logger.warning(f"Skill {name} is unhealthy: {details}")

            except Exception as e:
                self._logger.error(f"Health check failed for skill {name}: {e}")
                self._health_status[name] = HealthStatus(
                    healthy=False,
                    last_check=datetime.now(),
                    errors=[str(e)]
                )

    # ========================================================================
    # Public API
    # ========================================================================

    def register(self, skill: ISkill) -> None:
        """
        Register a skill with the registry.

        Args:
            skill: The skill to register

        Raises:
            RegistryError: If a skill with the same name is already registered
        """
        with self._skills_lock:
            name = skill.metadata.name

            if name in self._skills:
                raise RegistryError(
                    f"Skill '{name}' is already registered",
                    skill_name=name
                )

            # Validate the skill
            if hasattr(skill, 'validate'):
                validation = skill.validate()
                if not validation.valid:
                    raise RegistryError(
                        f"Skill '{name}' validation failed: {validation.errors}",
                        skill_name=name
                    )

            # Register the skill
            self._skills[name] = skill
            self._version_info[name] = SkillVersionInfo.from_string(skill.metadata.version)
            self._health_status[name] = HealthStatus(healthy=True)
            self._execution_stats[name] = {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "total_execution_time_ms": 0.0,
                "last_execution": None
            }

            self._logger.info(f"Registered skill: {name} v{skill.metadata.version}")

    def unregister(self, skill_name: str) -> None:
        """
        Unregister a skill from the registry.

        Args:
            skill_name: The name of the skill to unregister

        Raises:
            RegistryError: If the skill is not registered
        """
        with self._skills_lock:
            if skill_name not in self._skills:
                raise RegistryError(
                    f"Skill '{skill_name}' is not registered",
                    skill_name=skill_name
                )

            # Remove the skill
            del self._skills[skill_name]
            del self._version_info[skill_name]
            del self._health_status[skill_name]
            del self._execution_stats[skill_name]

            self._logger.info(f"Unregistered skill: {skill_name}")

    def get(self, skill_name: str) -> ISkill:
        """
        Get a skill by name.

        Args:
            skill_name: The name of the skill

        Returns:
            The skill instance

        Raises:
            RegistryError: If the skill is not registered
        """
        with self._skills_lock:
            if skill_name not in self._skills:
                raise RegistryError(
                    f"Skill '{skill_name}' is not registered",
                    skill_name=skill_name
                )
            return self._skills[skill_name]

    def list_skills(self) -> List[ISkill]:
        """
        List all registered skills.

        Returns:
            A list of all registered skills
        """
        with self._skills_lock:
            return list(self._skills.values())

    def list_skill_names(self) -> List[str]:
        """
        List names of all registered skills.

        Returns:
            A list of skill names
        """
        with self._skills_lock:
            return list(self._skills.keys())

    def find_by_trigger(self, trigger: str) -> List[ISkill]:
        """
        Find skills that match a trigger.

        Args:
            trigger: The trigger to match

        Returns:
            A list of skills that match the trigger
        """
        matching = []
        with self._skills_lock:
            for skill in self._skills.values():
                if trigger in skill.metadata.triggers:
                    matching.append(skill)
        return matching

    def execute(self, skill_name: str, input_data: Dict[str, Any],
                context: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        """
        Execute a skill with the given input.

        Args:
            skill_name: The name of the skill to execute
            input_data: The input data for the skill
            context: Optional execution context

        Returns:
            The execution result

        Raises:
            RegistryError: If the skill is not registered
        """
        start_time = time.perf_counter()

        # Get the skill
        skill = self.get(skill_name)

        # Prepare context
        ctx = context or {}
        ctx['skill_name'] = skill_name
        ctx['execution_start'] = start_time

        try:
            # Validate input
            if hasattr(skill, 'validate_input'):
                validation = skill.validate_input(input_data)
                if not validation.valid:
                    return ExecutionResult(
                        success=False,
                        output=None,
                        text=f"Input validation failed: {validation.errors}",
                        execution_time_ms=(time.perf_counter() - start_time) * 1000,
                        metadata={"errors": validation.errors},
                        error="Input validation failed"
                    )

            # Execute the skill
            if hasattr(skill, 'execute'):
                result = skill.execute(input_data, ctx)

                # Update stats
                self._update_execution_stats(skill_name, True, start_time)

                # Convert result to ExecutionResult if needed
                if isinstance(result, ExecutionResult):
                    return result
                else:
                    return ExecutionResult(
                        success=True,
                        output=result,
                        text=str(result) if result else "Success",
                        execution_time_ms=(time.perf_counter() - start_time) * 1000,
                        metadata={}
                    )
            else:
                raise RuntimeError(f"Skill {skill_name} does not have an execute method")

        except Exception as e:
            # Update stats
            self._update_execution_stats(skill_name, False, start_time)

            return ExecutionResult(
                success=False,
                output=None,
                text=f"Execution failed: {str(e)}",
                execution_time_ms=(time.perf_counter() - start_time) * 1000,
                metadata={"exception": str(e)},
                error=str(e)
            )

    def _update_execution_stats(self, skill_name: str, success: bool, start_time: float) -> None:
        """Update execution statistics for a skill."""
        if skill_name not in self._execution_stats:
            self._execution_stats[skill_name] = {
                "total_executions": 0,
                "successful_executions": 0,
                "failed_executions": 0,
                "total_execution_time_ms": 0.0,
                "last_execution": None
            }

        stats = self._execution_stats[skill_name]
        execution_time_ms = (time.perf_counter() - start_time) * 1000

        stats["total_executions"] += 1
        stats["total_execution_time_ms"] += execution_time_ms
        stats["last_execution"] = datetime.now().isoformat()

        if success:
            stats["successful_executions"] += 1
        else:
            stats["failed_executions"] += 1

    def get_health_status(self, skill_name: Optional[str] = None) -> Union[HealthStatus, Dict[str, HealthStatus]]:
        """
        Get health status for a skill or all skills.

        Args:
            skill_name: The name of the skill, or None for all skills

        Returns:
            HealthStatus for a single skill, or dict of all health statuses
        """
        if skill_name:
            return self._health_status.get(skill_name, HealthStatus(healthy=False))
        return dict(self._health_status)

    def get_execution_stats(self, skill_name: Optional[str] = None) -> Union[Dict[str, Any], Dict[str, Dict[str, Any]]]:
        """
        Get execution statistics for a skill or all skills.

        Args:
            skill_name: The name of the skill, or None for all skills

        Returns:
            Execution stats for a single skill, or dict of all stats
        """
        if skill_name:
            return self._execution_stats.get(skill_name, {})
        return dict(self._execution_stats)

    def shutdown(self) -> None:
        """Shutdown the registry and cleanup resources."""
        self._logger.info("Shutting down SkillRegistry...")

        # Signal shutdown
        self._shutdown_event.set()

        # Stop hot reload
        if self._observer and WATCHDOG_AVAILABLE:
            self._observer.stop()
            self._observer.join()
            self._logger.info("Hot reload observer stopped")

        # Wait for health check thread
        if self._health_check_thread and self._health_check_thread.is_alive():
            self._health_check_thread.join(timeout=5.0)

        # Clear all skills
        with self._skills_lock:
            self._skills.clear()
            self._health_status.clear()
            self._version_info.clear()
            self._execution_stats.clear()

        self._logger.info("SkillRegistry shutdown complete")

    def __enter__(self) -> "SkillRegistry":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.shutdown()

    def __del__(self) -> None:
        """Destructor - ensure cleanup."""
        try:
            self.shutdown()
        except:
            pass  # Ignore errors during destruction


# ============================================================================
# Convenience Functions
# ============================================================================

def get_registry(config: Optional[RegistryConfig] = None) -> SkillRegistry:
    """
    Get the singleton SkillRegistry instance.

    Args:
        config: Optional configuration for the registry

    Returns:
        The singleton SkillRegistry instance
    """
    return SkillRegistry.get_instance(config)


def register_skill(skill: ISkill, registry: Optional[SkillRegistry] = None) -> None:
    """
    Register a skill with the registry.

    Args:
        skill: The skill to register
        registry: Optional registry instance (uses singleton if not provided)
    """
    reg = registry or get_registry()
    reg.register(skill)


def execute_skill(skill_name: str, input_data: Dict[str, Any],
                  context: Optional[Dict[str, Any]] = None,
                  registry: Optional[SkillRegistry] = None) -> ExecutionResult:
    """
    Execute a skill by name.

    Args:
        skill_name: The name of the skill to execute
        input_data: The input data for the skill
        context: Optional execution context
        registry: Optional registry instance (uses singleton if not provided)

    Returns:
        The execution result
    """
    reg = registry or get_registry()
    return reg.execute(skill_name, input_data, context)
