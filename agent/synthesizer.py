"""Synthesizer for combining multi-step results into coherent response."""

from typing import Dict, Any, List

from .llm_client import LLMClient
from .context import AgentContext


class Synthesizer:
    """Synthesizes multi-step Skill results into coherent response.

    Instead of mechanically concatenating results, generates
    a natural, flowing response that integrates all outcomes.
    """

    def __init__(self, llm_client: LLMClient):
        """Initialize Synthesizer.

        Args:
            llm_client: LLM client for synthesis
        """
        self.llm = llm_client

    def synthesize(
        self,
        context: AgentContext,
        stream: bool = False
    ) -> str:
        """Synthesize final response from execution results.

        Args:
            context: Agent context with execution results
            stream: Whether to stream the response

        Returns:
            Final synthesized response
        """
        # Get execution data
        raw_request = context.read_layer1("raw_user_input")
        intent = context.read_layer1("parsed_intent")
        results = context.scratchpad.get_ordered_results()

        if not results:
            return "No results to synthesize."

        # Build synthesis prompt
        prompt = self._build_synthesis_prompt(raw_request, intent, results)

        if stream:
            # Return generator for streaming
            return self.llm.stream(prompt)
        else:
            return self.llm.invoke(prompt)

    def _build_synthesis_prompt(
        self,
        raw_request: str,
        intent: str,
        results: List
    ) -> str:
        """Build synthesis prompt.

        Args:
            raw_request: Original user request
            intent: Parsed intent
            results: Ordered skill results

        Returns:
            Synthesis prompt
        """
        # Format results for prompt
        results_text = self._format_results(results)

        prompt = f"""You are synthesizing results from a multi-step AI task execution.

Original User Request: {raw_request}

Parsed Intent: {intent}

Execution Results:
{results_text}

Instructions:
1. Synthesize the above results into a coherent, natural response
2. Address the user's original request directly
3. Present information in a logical, flowing manner
4. Be comprehensive but concise
5. Use appropriate formatting (bullet points, sections) for clarity
6. Maintain a helpful, professional tone

Please generate the final response:"""

        return prompt

    def _format_results(self, results: List) -> str:
        """Format skill results for synthesis prompt.

        Args:
            results: Ordered skill results

        Returns:
            Formatted results text
        """
        lines = []

        for i, result in enumerate(results, 1):
            lines.append(f"\n[Step {i}] {result.skill_name}")
            lines.append(f"Task: {result.sub_task}")

            if result.success:
                # Add structured summary if available
                if result.structured:
                    summary = self._summarize_structured(result.structured)
                    if summary:
                        lines.append(f"Key findings: {summary}")

                # Add text output
                if result.text:
                    lines.append(f"Output: {result.text[:500]}...")
            else:
                lines.append(f"Error: {result.error}")

        return "\n".join(lines)

    def _summarize_structured(self, structured: Dict) -> str:
        """Summarize structured data for synthesis.

        Args:
            structured: Structured output data

        Returns:
            Summary string
        """
        summaries = []

        # Handle common structured patterns
        if "summary" in structured:
            summary = structured["summary"]
            if isinstance(summary, dict):
                for key, value in summary.items():
                    summaries.append(f"{key}: {value}")
            else:
                summaries.append(str(summary))

        if "basic_info" in structured:
            info = structured["basic_info"]
            items = []
            for key, value in info.items():
                if isinstance(value, dict):
                    items.append(f"{key}: {value.get('value', value.get('category', value))}")
            if items:
                summaries.append(f"Basic info: {', '.join(items)}")

        if "risk_scores" in structured:
            risks = structured["risk_scores"]
            risk_items = []
            for dimension, data in risks.items():
                level = data.get("level", "unknown")
                risk_items.append(f"{dimension}: {level}")
            if risk_items:
                summaries.append(f"Risk assessment: {', '.join(risk_items)}")

        if "advice_items" in structured:
            count = len(structured["advice_items"])
            summaries.append(f"Generated {count} recommendations")

        return "; ".join(summaries)

    def synthesize_simple(
        self,
        raw_request: str,
        results: List[Dict]
    ) -> str:
        """Simple synthesis without full context.

        Args:
            raw_request: Original user request
            results: List of result dictionaries

        Returns:
            Synthesized response
        """
        if not results:
            return "I apologize, but I couldn't complete your request."

        if len(results) == 1:
            return results[0].get("text", "")

        # Build simple prompt
        results_text = "\n\n".join([
            f"{i+1}. {r.get('skill_name', 'Step')}: {r.get('text', '')[:300]}"
            for i, r in enumerate(results)
        ])

        prompt = f"""Based on the user's request: "{raw_request}"

Here are the results from multiple steps:
{results_text}

Please provide a coherent response that addresses the user's request:"""

        return self.llm.invoke(prompt)
