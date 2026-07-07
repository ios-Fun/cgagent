"""Coordinator - Main orchestration loop for Agent Skills Framework."""

import time
from typing import Dict, Any, Optional, List
from pathlib import Path

from config import Config
from .context import AgentContext
from .llm_client import LLMClient
from .token_budget import TokenBudget
from .planner import Planner
from .replanner import RePlanner
from .skill_executor import SkillExecutor
from .synthesizer import Synthesizer
from .tools import ToolRegistry, create_default_registry
from utils.skill_loader import SkillRegistry
from .errors import AgentError, ExecutorError


class Coordinator:
    """Main orchestration coordinator for Agent Skills Framework.

    Coordinates the entire pipeline:
    1. Initialize context with available skills
    2. Planner generates execution plan
    3. Executor executes skills with progressive disclosure
    4. Synthesizer generates final response
    """

    def __init__(self, config: Config):
        """Initialize Coordinator.

        Args:
            config: Framework configuration
        """
        self.config = config

        # Initialize LLM client
        llm_provider = self._create_llm_provider()
        token_budget = TokenBudget(
            total_limit=config.budget.total_limit,
            warning_threshold=config.budget.warning_threshold,
            enable_compression=config.budget.enable_compression
        )
        self.llm_client = LLMClient(llm_provider, token_budget)

        # Initialize tool registry
        self.tools = create_default_registry()

        # Initialize skill registry
        self.skill_registry = SkillRegistry.get_instance()
        self.skill_registry.initialize(str(config.skills_dir))

        # Initialize components
        self.context = AgentContext(enable_audit=config.execution.enable_audit_log)
        self.planner = Planner(
            self.llm_client,
            confidence_threshold=config.execution.confidence_threshold
        )
        self.replanner = RePlanner(self.llm_client)
        self.executor = SkillExecutor(self.llm_client)
        self.synthesizer = Synthesizer(self.llm_client)

        # Performance metrics
        self._metrics = {
            "total_requests": 0,
            "total_execution_time_ms": 0,
            "total_skills_executed": 0,
            "successful_plans": 0,
            "failed_plans": 0
        }

    def _create_llm_provider(self):
        """Create LLM provider based on configuration."""
        provider_name = self.config.llm.provider.lower()

        if provider_name == "openai":
            from agent.providers.openai_provider import OpenAIProvider
            return OpenAIProvider(
                api_key=self.config.llm.api_key,
                base_url=self.config.llm.base_url,
                default_model=self.config.llm.model
            )

        elif provider_name == "anthropic":
            from agent.providers.anthropic_provider import AnthropicProvider
            return AnthropicProvider(
                api_key=self.config.llm.api_key,
                base_url=self.config.llm.base_url,
                default_model=self.config.llm.model
            )

        elif provider_name == "ollama":
            from agent.providers.ollama_provider import OllamaProvider
            return OllamaProvider(
                host=self.config.llm.base_url or "localhost",
                port=11434,
                default_model=self.config.llm.model
            )

        elif provider_name == "zhipu":
            from agent.providers.zhipu_provider import ZhipuProvider
            return ZhipuProvider(
                api_key=self.config.llm.api_key,
                base_url=self.config.llm.base_url,
                default_model=self.config.llm.model or "glm-4"
            )

        else:
            raise ValueError(f"Unsupported LLM provider: {provider_name}")

    def process(self, user_input: str, stream: bool = False) -> Dict[str, Any]:
        """Process a user request.

        Args:
            user_input: User's request
            stream: Whether to stream the response

        Returns:
            Result dictionary with response and metadata
        """
        start_time = time.time()
        self._metrics["total_requests"] += 1

        try:
            # Phase 0: Initialize context
            self.context.set_component("coordinator")
            self.context.write_layer1("raw_user_input", user_input, "coordinator")
            self.context.write_layer3(
                "available_skills",
                self.skill_registry.get_all_skills(),
                "coordinator"
            )
            self.context.write_layer3("token_budget", self.llm_client.budget, "coordinator")
            self.context.write_layer3("tools_registry", self.tools, "coordinator")

            # Phase 1: Planning
            plan = self._plan_execution(user_input)

            # Phase 2: Execute skills
            execution_result = self._execute_plan(plan)

            if not execution_result["success"]:
                return {
                    "final_response": execution_result.get("error", "Execution failed"),
                    "success": False,
                    "metrics": self._get_execution_metrics(start_time)
                }

            # Phase 3: Synthesize response
            final_response = self.synthesizer.synthesize(self.context, stream=stream)

            return {
                "final_response": final_response,
                "success": True,
                "metrics": self._get_execution_metrics(start_time),
                "plan": plan.to_dict(),
                "execution_summary": execution_result.get("summary", {})
            }

        except Exception as e:
            return {
                "final_response": f"An error occurred: {str(e)}",
                "success": False,
                "metrics": self._get_execution_metrics(start_time),
                "error": str(e)
            }

    def _plan_execution(self, user_input: str):
        """Generate execution plan.

        Args:
            user_input: User's request

        Returns:
            ExecutionPlan
        """
        self.context.set_component("planner")

        available_skills = self.skill_registry.get_all_skills()
        conversation_history = self.context.read_layer1("conversation_history") or []

        plan = self.planner.generate_plan(user_input, available_skills, conversation_history)

        # Store plan in context
        self.context.write_layer1("execution_plan", plan.to_dict(), "planner")
        self.context.write_layer1("parsed_intent", plan.intent, "planner")

        self._metrics["successful_plans"] += 1
        return plan

    def _execute_plan(self, plan) -> Dict[str, Any]:
        """Execute all steps in plan.

        Args:
            plan: ExecutionPlan

        Returns:
            Execution result dictionary
        """
        self.context.set_component("executor")

        executed_steps = []
        failed_steps = []

        for i, step in enumerate(plan.steps):
            step_number = i + 1
            self.context.scratchpad.current_step = step_number

            # Execute with retry and replan
            result = self._execute_single_step(step, len(executed_steps))

            if result["success"]:
                executed_steps.append(result)
            else:
                failed_steps.append(result)

                # Handle failure
                if self.config.execution.enable_replan:
                    recovery = self._handle_failure(step, result, executed_steps)
                    if recovery["action"] == "skip":
                        continue
                    elif recovery["action"] == "abort":
                        return {
                            "success": False,
                            "error": f"Execution aborted: {recovery.get('reason', 'Unknown reason')}",
                            "executed_steps": executed_steps,
                            "failed_steps": failed_steps
                        }

        self._metrics["total_skills_executed"] += len(executed_steps)

        return {
            "success": len(executed_steps) > 0,
            "executed_steps": executed_steps,
            "failed_steps": failed_steps,
            "summary": {
                "total": len(plan.steps),
                "executed": len(executed_steps),
                "failed": len(failed_steps)
            }
        }

    def _execute_single_step(
        self,
        step: Dict,
        completed_count: int
    ) -> Dict[str, Any]:
        """Execute a single skill step.

        Args:
            step: Step definition
            completed_count: Number of already completed steps

        Returns:
            Execution result
        """
        # Ensure we're in executor context
        self.context.set_component("executor")

        skill_name = step["skill"]
        sub_task = step["sub_task"]

        # Get skill
        try:
            skill = self.skill_registry.get_skill(skill_name)
        except Exception as e:
            return {
                "success": False,
                "skill_name": skill_name,
                "error": f"Skill not found: {skill_name}",
                "step": step
            }

        # Prepare context for step
        include_history = (completed_count == 0)
        step_context = self.context.prepare_for_step(step, include_history)

        # Execute skill
        try:
            result = self.executor.execute(skill, sub_task, step_context)

            if result.get("success"):
                # Store result in scratchpad
                self.context.write_scratchpad(
                    skill_name=skill_name,
                    sub_task=sub_task,
                    structured=result.get("structured", {}),
                    text=result.get("text", ""),
                    execution_time_ms=result.get("execution_time_ms", 0),
                    source="executor"
                )

            return {
                "success": result.get("success", False),
                "skill_name": skill_name,
                "sub_task": sub_task,
                "result": result,
                "step": step
            }

        except Exception as e:
            return {
                "success": False,
                "skill_name": skill_name,
                "error": str(e),
                "step": step
            }

    def _handle_failure(
        self,
        step: Dict,
        failure_result: Dict,
        executed_steps: List
    ) -> Dict[str, str]:
        """Handle execution failure with replanning.

        Args:
            step: Failed step
            failure_result: Failure result
            executed_steps: Previously executed steps

        Returns:
            Recovery action dictionary
        """
        # Build execution status for replanner
        execution_status = {
            "plan": self.context.read_layer1("execution_plan"),
            "completed": executed_steps,
            "available_skills": self.skill_registry.get_all_skills()
        }

        # Get replanner decision
        decision = self.replanner.decide(
            original_request=self.context.read_layer1("raw_user_input"),
            current_step=step,
            execution_status=execution_status,
            failed_step_error=failure_result.get("error", "Unknown error")
        )

        # Log failure
        self.context.scratchpad.record_failure(
            step=step,
            error=failure_result.get("error", ""),
            attempt=1
        )

        return {
            "action": decision.action.value,
            "reason": decision.reason
        }

    def _get_execution_metrics(self, start_time: float) -> Dict:
        """Get execution metrics.

        Args:
            start_time: Start time of processing

        Returns:
            Metrics dictionary
        """
        execution_time_ms = (time.time() - start_time) * 1000
        self._metrics["total_execution_time_ms"] += execution_time_ms

        return {
            "execution_time_ms": execution_time_ms,
            "total_requests": self._metrics["total_requests"],
            "total_skills_executed": self._metrics["total_skills_executed"],
            "llm_metrics": self.llm_client.get_metrics(),
            "token_budget": self.llm_client.budget.get_summary()
        }

    def get_audit_trail(self) -> List[Dict]:
        """Get full audit trail.

        Returns:
            List of audit entries
        """
        return self.context.export_audit()

    def explain(self, question: str) -> str:
        """Get explanation for a decision.

        Args:
            question: Question to answer

        Returns:
            Explanation text
        """
        if self.context.audit_log:
            return self.context.audit_log.explain(question)
        return "Audit logging is not enabled."

    def reset(self) -> None:
        """Reset coordinator state."""
        self.context.clear()
        self.llm_client.budget.reset()
