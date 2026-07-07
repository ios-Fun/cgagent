"""BaseSkill abstract base class for Agent Skills Framework.

This module defines the BaseSkill abstract base class that all skills must inherit.
It provides a standardized interface for skill execution, validation, and metadata.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Callable, List, TypeVar, Generic, Union
from pathlib import Path
import time
import asyncio

from .interfaces import (
    SkillMetadata,
    ExecutionResult,
    ValidationResult,
    ExecutionStatus,
    SkillExecutionError,
    ValidationError,
)


# ============================================================================
# Type Variables
# ============================================================================

InputT = TypeVar("InputT", bound=Dict[str, Any])
OutputT = TypeVar("OutputT", bound=Dict[str, Any])

# Type aliases for compatibility
SkillInput = Dict[str, Any]
SkillOutput = Dict[str, Any]


# ============================================================================
# Decorators
# ============================================================================

def execution_timer(func: Callable) -> Callable:
    """Decorator to measure execution time."""
    async def wrapper(*args, **kwargs) -> Any:
        start_time = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            return result
        finally:
            end_time = time.perf_counter()
            execution_time_ms = (end_time - start_time) * 1000
            # Store execution time in the result if it's an ExecutionResult
            if isinstance(result, ExecutionResult):
                result.execution_time_ms = execution_time_ms
    return wrapper


def validate_input_decorator(func: Callable) -> Callable:
    """Decorator to validate input before execution."""
    async def wrapper(self, input_data: Dict[str, Any], *args, **kwargs) -> Any:
        is_valid, error = self.validate_input(input_data)
        if not is_valid:
            raise ValidationError(f"Input validation failed: {error}")
        return await func(self, input_data, *args, **kwargs)
    return wrapper


# ============================================================================
# BaseSkill Abstract Base Class
# ============================================================================

class BaseSkill(ABC, Generic[InputT, OutputT]):
    """Skill抽象基类，所有Skill必须继承此基类。

    该类提供了标准化的接口用于：
    - Skill执行
    - 输入/输出验证
    - 元数据管理
    - 错误处理

    Example:
        class MySkill(BaseSkill):
            @property
            def name(self) -> str:
                return "my_skill"

            @property
            def version(self) -> str:
                return "1.0.0"

            async def execute(self, input_data, context):
                # Implementation
                return {"result": "success"}
    """

    def __init__(self):
        """Initialize the skill."""
        self._metadata = self._build_metadata()
        self._execution_count = 0
        self._total_execution_time_ms = 0.0

    # ========================================================================
    # Abstract Properties - Must be implemented by subclasses
    # ========================================================================

    @property
    @abstractmethod
    def name(self) -> str:
        """Skill名称，必须唯一。

        Returns:
            Skill的字符串标识符
        """
        pass

    @property
    @abstractmethod
    def version(self) -> str:
        """Skill版本，遵循语义化版本规范。

        Returns:
            版本字符串，如 "1.0.0"
        """
        pass

    # ========================================================================
    # Abstract Methods - Must be implemented by subclasses
    # ========================================================================

    @abstractmethod
    def validate_input(self, input_data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """验证输入数据。

        Args:
            input_data: 输入数据字典

        Returns:
            Tuple of (是否有效, 错误信息)
            - 如果有效，返回 (True, None)
            - 如果无效，返回 (False, 错误描述)
        """
        pass

    @abstractmethod
    async def execute(
        self,
        input_data: Dict[str, Any],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """执行Skill逻辑。

        这是Skill的核心执行方法，子类必须实现此方法来
        定义Skill的具体行为。

        Args:
            input_data: 输入数据，已通过validate_input验证
            context: 上下文信息，包含execution_context等

        Returns:
            执行结果字典，必须包含至少一个键值对

        Raises:
            SkillExecutionError: 执行失败时抛出
        """
        pass

    @abstractmethod
    def validate_output(self, output_data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """验证输出数据。

        Args:
            output_data: 输出数据字典

        Returns:
            Tuple of (是否有效, 错误信息)
        """
        pass

    @abstractmethod
    def get_metadata(self) -> Dict[str, Any]:
        """获取Skill元数据。

        Returns:
            包含Skill元信息的字典，如：
            - description: 描述
            - author: 作者
            - tags: 标签列表
            - triggers: 触发词列表
        """
        pass

    # ========================================================================
    # Concrete Methods - Can be used by subclasses
    # ========================================================================

    async def execute_with_validation(
        self,
        input_data: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ExecutionResult:
        """执行Skill，包含完整的验证和错误处理。

        这是推荐的外部调用接口，它封装了：
        - 输入验证
        - 执行计时
        - 输出验证
        - 错误处理

        Args:
            input_data: 输入数据
            context: 上下文信息

        Returns:
            ExecutionResult对象，包含状态、输出、执行时间等
        """
        import time
        start_time = time.perf_counter()

        try:
            # Step 1: Validate input
            is_valid, error = self.validate_input(input_data)
            if not is_valid:
                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    output={},
                    execution_time_ms=0,
                    metadata={"stage": "input_validation"},
                    error=f"Input validation failed: {error}"
                )

            # Step 2: Execute
            output = await self.execute(input_data, context)

            # Step 3: Validate output
            is_valid, error = self.validate_output(output)
            if not is_valid:
                return ExecutionResult(
                    status=ExecutionStatus.FAILED,
                    output=output,
                    execution_time_ms=0,
                    metadata={"stage": "output_validation"},
                    error=f"Output validation failed: {error}"
                )

            # Success
            end_time = time.perf_counter()
            execution_time_ms = (end_time - start_time) * 1000

            self._execution_count += 1
            self._total_execution_time_ms += execution_time_ms

            return ExecutionResult(
                status=ExecutionStatus.SUCCESS,
                output=output,
                execution_time_ms=execution_time_ms,
                metadata={
                    "skill_name": self.name,
                    "skill_version": self.version,
                    "execution_count": self._execution_count
                }
            )

        except Exception as e:
            end_time = time.perf_counter()
            execution_time_ms = (end_time - start_time) * 1000

            return ExecutionResult(
                status=ExecutionStatus.FAILED,
                output={},
                execution_time_ms=execution_time_ms,
                metadata={"stage": "execution", "exception_type": type(e).__name__},
                error=str(e)
            )

    def get_stats(self) -> Dict[str, Any]:
        """获取Skill执行统计信息。

        Returns:
            包含统计信息的字典
        """
        avg_execution_time = (
            self._total_execution_time_ms / self._execution_count
            if self._execution_count > 0 else 0
        )

        return {
            "skill_name": self.name,
            "skill_version": self.version,
            "execution_count": self._execution_count,
            "total_execution_time_ms": self._total_execution_time_ms,
            "avg_execution_time_ms": avg_execution_time
        }

    def _build_metadata(self) -> SkillMetadata:
        """构建SkillMetadata对象。"""
        meta = self.get_metadata()
        return SkillMetadata(
            name=self.name,
            version=self.version,
            description=meta.get("description", ""),
            author=meta.get("author", ""),
            tags=tuple(meta.get("tags", [])),
            triggers=tuple(meta.get("triggers", [])),
            input_schema=meta.get("input_schema"),
            output_schema=meta.get("output_schema")
        )


# ============================================================================
# Utility Functions
# ============================================================================

def create_simple_skill(
    name: str,
    version: str,
    description: str,
    execute_fn: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]
) -> "BaseSkill":
    """Factory function to create a simple skill from a function.

    Args:
        name: Skill name
        version: Skill version
        description: Skill description
        execute_fn: Function that implements skill logic

    Returns:
        BaseSkill instance
    """
    class SimpleSkill(BaseSkill):
        @property
        def name(self) -> str:
            return name

        @property
        def version(self) -> str:
            return version

        def validate_input(self, input_data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
            return True, None

        async def execute(
            self,
            input_data: Dict[str, Any],
            context: Dict[str, Any]
        ) -> Dict[str, Any]:
            return execute_fn(input_data, context)

        def validate_output(self, output_data: Dict[str, Any]) -> tuple[bool, Optional[str]]:
            return True, None

        def get_metadata(self) -> Dict[str, Any]:
            return {
                "description": description,
                "tags": ["simple"],
                "triggers": []
            }

    return SimpleSkill()
