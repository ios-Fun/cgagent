"""Skill executor supporting three execution modes."""

import time
import importlib.util
import sys
from pathlib import Path
from typing import Dict, Any

from .llm_client import LLMClient
from utils.skill_loader import Skill
from .errors import SkillExecutionError


class SkillExecutor:
    """Execute Skills in three modes: executor.py, prompt.template, or document.

    Execution priority:
    1. executor.py - Custom Python code with rule engine + LLM
    2. prompt.template - Template-based LLM invocation
    3. SKILL.md - Document-based conversation
    """

    def __init__(self, llm_client: LLMClient):
        """Initialize SkillExecutor.

        Args:
            llm_client: LLM client for invocations
        """
        self.llm = llm_client

    def execute(
        self,
        skill: Skill,
        sub_task: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute a skill.

        Args:
            skill: Skill to execute
            sub_task: Specific sub-task description
            context: Execution context with inputs

        Returns:
            Execution result with structured/text outputs

        Raises:
            SkillExecutionError: If execution fails
        """
        start_time = time.time()

        try:
            if skill.execution_mode == "executor":
                result = self._execute_with_executor(skill, sub_task, context)
            elif skill.execution_mode == "template":
                result = self._execute_with_template(skill, sub_task, context)
            else:  # document mode
                result = self._execute_with_document(skill, sub_task, context)

            execution_time = (time.time() - start_time) * 1000
            result["execution_time_ms"] = execution_time
            result["mode"] = skill.execution_mode
            result["success"] = True

            return result

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            return {
                "success": False,
                "error": str(e),
                "execution_time_ms": execution_time,
                "mode": skill.execution_mode
            }

    def _execute_with_executor(
        self,
        skill: Skill,
        sub_task: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute using executor.py.

        Args:
            skill: Skill with executor.py
            sub_task: Sub-task description
            context: Execution context

        Returns:
            Execution result
        """
        executor_path = skill.directory / "executor.py"

        # Dynamically load executor module
        module_name = f"skill_executor_{skill.name}_{id(skill)}"
        spec = importlib.util.spec_from_file_location(module_name, executor_path)

        if spec is None or spec.loader is None:
            raise SkillExecutionError(
                skill.name,
                f"Failed to load executor from {executor_path}"
            )

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module

        try:
            spec.loader.exec_module(module)
        except Exception as e:
            raise SkillExecutionError(
                skill.name,
                f"Failed to execute executor module: {e}"
            )

        # Call execute function
        if not hasattr(module, "execute"):
            raise SkillExecutionError(
                skill.name,
                "executor.py must define an 'execute' function"
            )

        try:
            result = module.execute(self.llm, sub_task, context)

            if not isinstance(result, dict):
                raise SkillExecutionError(
                    skill.name,
                    f"execute() must return dict, got {type(result).__name__}"
                )

            return result

        except SkillExecutionError:
            raise
        except Exception as e:
            raise SkillExecutionError(skill.name, f"Executor failed: {e}")

    def _execute_with_template(
        self,
        skill: Skill,
        sub_task: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute using prompt.template.

        Args:
            skill: Skill with prompt.template
            sub_task: Sub-task description
            context: Execution context

        Returns:
            Execution result
        """
        template_path = skill.directory / "prompt.template"

        try:
            template = template_path.read_text(encoding="utf-8")
        except Exception as e:
            raise SkillExecutionError(skill.name, f"Failed to read template: {e}")

        # Prepare template variables
        template_vars = {
            "sub_task": sub_task,
            "user_input": context.get("user_input", ""),
            "previous_results": self._format_previous_results(context),
            "skill_description": skill.description
        }

        try:
            prompt = template.format(**template_vars)
        except KeyError as e:
            raise SkillExecutionError(
                skill.name,
                f"Template variable missing: {e}"
            )

        # Invoke LLM
        try:
            response = self.llm.invoke(prompt)
            return {"text": response}
        except Exception as e:
            raise SkillExecutionError(skill.name, f"LLM invocation failed: {e}")

    def _execute_with_document(
        self,
        skill: Skill,
        sub_task: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute using SKILL.md as system prompt.

        Args:
            skill: Skill with only SKILL.md
            sub_task: Sub-task description
            context: Execution context

        Returns:
            Execution result
        """
        skill_md_path = skill.directory / "SKILL.md"

        try:
            content = skill_md_path.read_text(encoding="utf-8")
        except Exception as e:
            raise SkillExecutionError(skill.name, f"Failed to read SKILL.md: {e}")

        # Extract document content (after YAML front matter)
        if content.startswith("---"):
            parts = content.split("---", 2)
            document = parts[2] if len(parts) > 2 else content
        else:
            document = content

        # Build system prompt
        system_prompt = f"""You are a specialized assistant with the following capabilities:

{skill.description}

{document}

Instructions:
- Focus only on the specific task assigned
- Use the knowledge and guidelines provided above
- Be concise and accurate"""

        # Build user prompt
        user_prompt = f"""Task: {sub_task}

{context.get("user_input", "")}"""

        # Invoke LLM
        try:
            response = self.llm.invoke(
                prompt=user_prompt,
                system_prompt=system_prompt
            )
            return {"text": response}
        except Exception as e:
            raise SkillExecutionError(skill.name, f"LLM invocation failed: {e}")

    def _format_previous_results(self, context: Dict[str, Any]) -> str:
        """Format previous results for template."""
        previous = context.get("previous_results", {})

        if not previous:
            return "No previous results."

        lines = []
        for skill_name, result in previous.items():
            if result.get("compressed"):
                lines.append(f"- {skill_name}: [compressed]")
            else:
                text = result.get("text", "")[:200]
                lines.append(f"- {skill_name}: {text}...")

        return "\n".join(lines)

    def stream_execute(
        self,
        skill: Skill,
        sub_task: str,
        context: Dict[str, Any]
    ):
        """Stream execution for skills that support it.

        Args:
            skill: Skill to execute
            sub_task: Sub-task description
            context: Execution context

        Yields:
            Response chunks
        """
        # Build prompt based on mode
        if skill.execution_mode == "template":
            template_path = skill.directory / "prompt.template"
            template = template_path.read_text(encoding="utf-8")

            template_vars = {
                "sub_task": sub_task,
                "user_input": context.get("user_input", ""),
                "previous_results": self._format_previous_results(context)
            }
            prompt = template.format(**template_vars)

            for chunk in self.llm.stream(prompt):
                yield chunk

        elif skill.execution_mode == "document":
            skill_md_path = skill.directory / "SKILL.md"
            content = skill_md_path.read_text(encoding="utf-8")

            if content.startswith("---"):
                parts = content.split("---", 2)
                document = parts[2] if len(parts) > 2 else content
            else:
                document = content

            system_prompt = f"""You are: {skill.description}\n\n{document}"""
            user_prompt = f"Task: {sub_task}\n\n{context.get('user_input', '')}"

            for chunk in self.llm.stream(user_prompt, system_prompt=system_prompt):
                yield chunk

        else:
            # executor mode doesn't support streaming by default
            # Fall back to regular execution
            result = self.execute(skill, sub_task, context)
            yield result.get("text", "")
