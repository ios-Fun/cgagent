"""RePlanner for dynamic recovery from skill execution failures."""

import json
from typing import Dict, List, Optional
from enum import Enum
from dataclasses import dataclass

from .llm_client import LLMClient
from .errors import AgentError


class RePlanAction(Enum):
    """Actions to take when a step fails."""
    RETRY = "retry"
    SKIP = "skip"
    ALTERNATIVE = "alternative"
    ABORT = "abort"


@dataclass
class RePlanDecision:
    """Decision made by RePlanner."""
    action: RePlanAction
    reason: str
    alternative_skill: Optional[str] = None
    modified_params: Dict = None

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "action": self.action.value,
            "reason": self.reason,
            "alternative_skill": self.alternative_skill,
            "modified_params": self.modified_params or {}
        }


class RePlanner:
    """Dynamic re-planning for handling execution failures.

    When a skill execution fails, analyzes the situation and decides
    on recovery strategy.
    """

    def __init__(self, llm_client: LLMClient):
        """Initialize RePlanner.

        Args:
            llm_client: LLM client for analysis
        """
        self.llm = llm_client

    def decide(
        self,
        original_request: str,
        current_step: Dict,
        execution_status: Dict,
        failed_step_error: str
    ) -> RePlanDecision:
        """Decide on recovery action when a step fails.

        Args:
            original_request: Original user request
            current_step: Current step definition
            execution_status: Current execution status
            failed_step_error: Error message from failed execution

        Returns:
            RePlanDecision with action to take
        """
        # Build available skills list
        available_skills = list(execution_status.get("available_skills", {}).keys())

        # Build completed steps summary
        completed_summary = self._format_completed_steps(
            execution_status.get("completed", [])
        )

        prompt = f"""Analyze the following failed execution and decide on recovery action.

Original User Request: {original_request}

Current Execution Plan:
{self._format_plan(execution_status.get('plan', {}))}

Completed Steps:
{completed_summary}

Current Failed Step:
- Skill: {current_step.get('skill', 'unknown')}
- Sub-task: {current_step.get('sub_task', 'unknown')}
- Confidence: {current_step.get('confidence', 0)}
- Error: {failed_step_error}

Available Skills: {', '.join(available_skills)}

Please analyze and decide the best recovery action:

1. RETRY - Retry the current step (if temporary error)
2. SKIP - Skip this step (if non-essential)
3. ALTERNATIVE - Try an alternative skill (specify which)
4. ABORT - Abort execution (if critical step and unrecoverable)

Respond in JSON format:
{{
    "action": "RETRY|SKIP|ALTERNATIVE|ABORT",
    "reason": "Brief explanation of why this action is appropriate",
    "alternative_skill": "name of alternative skill (if ALTERNATIVE)",
    "modified_params": {{}}  // Any parameter modifications (optional)
}}
"""

        try:
            response = self.llm.invoke(prompt)
            decision_data = json.loads(response)

            # Validate action
            action_str = decision_data.get("action", "ABORT")
            try:
                action = RePlanAction(action_str)
            except ValueError:
                action = RePlanAction.ABORT

            return RePlanDecision(
                action=action,
                reason=decision_data.get("reason", "No explanation provided"),
                alternative_skill=decision_data.get("alternative_skill"),
                modified_params=decision_data.get("modified_params", {})
            )

        except Exception as e:
            # Fallback to retry if analysis fails
            return RePlanDecision(
                action=RePlanAction.RETRY,
                reason=f"RePlan analysis failed: {str(e)}, defaulting to retry"
            )

    def _format_plan(self, plan: Dict) -> str:
        """Format execution plan for display."""
        if not plan or "steps" not in plan:
            return "No plan available"

        lines = []
        for i, step in enumerate(plan.get("steps", []), 1):
            lines.append(
                f"  {i}. {step.get('skill', 'unknown')}: {step.get('sub_task', 'unknown')} "
                f"(confidence: {step.get('confidence', 0)})"
            )
        return "\n".join(lines)

    def _format_completed_steps(self, completed: List) -> str:
        """Format completed steps for display."""
        if not completed:
            return "  (none)"

        lines = []
        for item in completed:
            step = item.get("step", {})
            result = item.get("result", {})
            success = result.get("success", True)
            status = "✓" if success else "✗"
            lines.append(
                f"  {status} {step.get('skill', 'unknown')}: "
                f"{step.get('sub_task', 'unknown')}"
            )
        return "\n".join(lines)

    def should_replan(
        self,
        skill_name: str,
        error: Exception,
        attempt: int,
        max_retries: int
    ) -> bool:
        """Quick check if replanning should be triggered.

        Args:
            skill_name: Name of failed skill
            error: Exception that occurred
            attempt: Current attempt number
            max_retries: Maximum retry attempts

        Returns:
            True if replanning should be done
        """
        # Don't replan if we haven't exhausted retries yet
        if attempt < max_retries:
            return False

        # Don't replan for certain error types
        from .errors import SkillNotFoundError, TokenBudgetExceeded
        if isinstance(error, (SkillNotFoundError, TokenBudgetExceeded)):
            return False

        return True
