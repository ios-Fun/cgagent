"""Scratchpad for working memory (Layer 2 of context)."""

from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass, field


@dataclass
class StepResult:
    """Result of a single Skill execution."""
    skill_name: str
    sub_task: str
    structured: Dict[str, Any]  # Structured data output
    text: str  # Natural language output
    success: bool = True
    error: str = ""
    execution_time_ms: float = 0
    compressed: bool = False

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "skill_name": self.skill_name,
            "sub_task": self.sub_task,
            "structured": self.structured,
            "text": self.text,
            "success": self.success,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "compressed": self.compressed
        }


@dataclass
class FailedStep:
    """Record of a failed execution step."""
    step: Dict
    error: str
    attempt: int
    timestamp: str


class Scratchpad:
    """Working memory layer (Layer 2) for storing Skill execution results.

    Provides structured storage with:
    - Step results by skill name
    - Failed step tracking for RePlan
    - Compression support
    - Access history
    """

    def __init__(self):
        self._results: Dict[str, StepResult] = {}
        self._current_step: Optional[int] = None
        self._failed_steps: List[FailedStep] = []
        self._history: List[Dict] = []

    def set_result(
        self,
        skill_name: str,
        sub_task: str,
        structured: Dict[str, Any],
        text: str,
        success: bool = True,
        error: str = "",
        execution_time_ms: float = 0
    ) -> None:
        """Store result of a Skill execution.

        Args:
            skill_name: Name of the skill
            sub_task: Sub-task description
            structured: Structured data output
            text: Natural language output
            success: Whether execution succeeded
            error: Error message if failed
            execution_time_ms: Execution time in milliseconds
        """
        result = StepResult(
            skill_name=skill_name,
            sub_task=sub_task,
            structured=structured,
            text=text,
            success=success,
            error=error,
            execution_time_ms=execution_time_ms
        )
        self._results[skill_name] = result

        self._history.append({
            "timestamp": datetime.now().isoformat(),
            "action": "set_result",
            "skill_name": skill_name,
            "success": success
        })

    def get_result(self, skill_name: str) -> Optional[StepResult]:
        """Get result of a specific Skill.

        Args:
            skill_name: Name of the skill

        Returns:
            StepResult if found, None otherwise
        """
        return self._results.get(skill_name)

    def get_structured(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """Get structured output of a Skill.

        Args:
            skill_name: Name of the skill

        Returns:
            Structured data if found, None otherwise
        """
        result = self._results.get(skill_name)
        return result.structured if result else None

    def get_text(self, skill_name: str) -> Optional[str]:
        """Get text output of a Skill.

        Args:
            skill_name: Name of the skill

        Returns:
            Text output if found, None otherwise
        """
        result = self._results.get(skill_name)
        return result.text if result else None

    def compress_result(self, skill_name: str) -> bool:
        """Mark a result as compressed.

        Args:
            skill_name: Name of the skill

        Returns:
            True if compressed, False if not found
        """
        result = self._results.get(skill_name)
        if result:
            result.compressed = True
            return True
        return False

    def is_compressed(self, skill_name: str) -> bool:
        """Check if a result is compressed.

        Args:
            skill_name: Name of the skill

        Returns:
            True if compressed, False otherwise
        """
        result = self._results.get(skill_name)
        return result.compressed if result else False

    def get_all_results(self) -> Dict[str, StepResult]:
        """Get all stored results."""
        return self._results.copy()

    def get_accumulated_text(self, exclude_compressed: bool = True) -> str:
        """Get accumulated text from all results.

        Args:
            exclude_compressed: Whether to exclude compressed results

        Returns:
            Accumulated text string
        """
        texts = []
        for skill_name, result in self._results.items():
            if exclude_compressed and result.compressed:
                texts.append(f"[{skill_name}: ...已压缩...]")
            else:
                texts.append(f"[{skill_name}]: {result.text}")
        return "\n\n".join(texts)

    def get_ordered_results(self) -> List[StepResult]:
        """Get results in execution order (by history)."""
        ordered = []
        seen = set()
        for entry in self._history:
            if entry["action"] == "set_result":
                skill_name = entry["skill_name"]
                if skill_name not in seen and skill_name in self._results:
                    ordered.append(self._results[skill_name])
                    seen.add(skill_name)
        return ordered

    def record_failure(self, step: Dict, error: str, attempt: int) -> None:
        """Record a failed execution step.

        Args:
            step: Step definition
            error: Error message
            attempt: Attempt number
        """
        failed = FailedStep(
            step=step,
            error=error,
            attempt=attempt,
            timestamp=datetime.now().isoformat()
        )
        self._failed_steps.append(failed)

    def get_failures(self) -> List[FailedStep]:
        """Get all failed steps."""
        return self._failed_steps.copy()

    def clear_failures(self) -> None:
        """Clear failed steps records."""
        self._failed_steps = []

    @property
    def current_step(self) -> Optional[int]:
        """Get current step number."""
        return self._current_step

    @current_step.setter
    def current_step(self, value: Optional[int]) -> None:
        """Set current step number."""
        self._current_step = value

    def get_summary(self) -> Dict:
        """Get scratchpad summary."""
        success_count = sum(1 for r in self._results.values() if r.success)
        total_count = len(self._results)

        return {
            "total_results": total_count,
            "successful_results": success_count,
            "failed_results": total_count - success_count,
            "failed_steps_recorded": len(self._failed_steps),
            "compressed_results": sum(1 for r in self._results.values() if r.compressed),
            "skills_executed": list(self._results.keys())
        }

    def clear(self) -> None:
        """Clear all data."""
        self._results = {}
        self._current_step = None
        self._failed_steps = []
        self._history = []
