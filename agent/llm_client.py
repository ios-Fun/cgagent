"""Unified LLM client with token budget management."""

import time
from typing import Iterator, Optional, Dict, Any, List
from .llm_base import LLMProvider, LLMMessage, LLMResponse, StreamChunk
from .token_budget import TokenBudget


class TokenBudgetExceeded(Exception):
    """Raised when token budget is exceeded."""
    pass


class LLMClient:
    """Unified LLM client with budget management and metrics.

    Wraps an LLMProvider and adds:
    - Token budget tracking
    - Usage metrics
    - Auto-compression recommendations
    """

    def __init__(
        self,
        provider: LLMProvider,
        token_budget: Optional[TokenBudget] = None
    ):
        """Initialize LLM client.

        Args:
            provider: LLM provider instance
            token_budget: Optional token budget manager
        """
        self.provider = provider
        self.budget = token_budget or TokenBudget()
        self._metrics = {
            "total_calls": 0,
            "total_tokens": 0,
            "total_time_ms": 0.0,
            "errors": 0
        }

    def invoke(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        check_budget: bool = True,
        **kwargs
    ) -> str:
        """Invoke LLM synchronously.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            model: Model name (uses provider default if None)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            check_budget: Whether to check token budget before calling
            **kwargs: Additional provider-specific parameters

        Returns:
            Generated text response

        Raises:
            TokenBudgetExceeded: If budget check is enabled and exceeded
        """
        messages = self._build_messages(system_prompt, prompt)

        # Estimate tokens and check budget
        if check_budget:
            estimated = self.provider.count_tokens(prompt)
            if system_prompt:
                estimated += self.provider.count_tokens(system_prompt)
            estimated += max_tokens  # Reserve for completion

            if not self.budget.consume(estimated, f"invoke_estimate"):
                raise TokenBudgetExceeded(
                    f"Token budget exceeded: {self.budget._used}/{self.budget.total_limit}"
                )

        # Call provider
        start_time = time.time()
        try:
            response = self.provider.invoke(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )

            # Update metrics with actual usage
            actual_tokens = response.usage.get("total_tokens", 0)
            if check_budget:
                # Correct budget estimate with actual usage (only consume additional if needed)
                correction = actual_tokens - estimated
                if correction > 0:
                    self.budget.consume(correction, "invoke_correction")

            execution_time = getattr(response, "execution_time_ms", (time.time() - start_time) * 1000)
            self._update_metrics(actual_tokens, execution_time)

            return response.content

        except Exception as e:
            self._metrics["errors"] += 1
            raise

    def stream(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        check_budget: bool = True,
        **kwargs
    ) -> Iterator[str]:
        """Stream LLM response.

        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            model: Model name (uses provider default if None)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            check_budget: Whether to check token budget
            **kwargs: Additional provider-specific parameters

        Yields:
            Response text chunks
        """
        messages = self._build_messages(system_prompt, prompt)

        # Estimate and check budget
        if check_budget:
            estimated = self.provider.count_tokens(prompt)
            if system_prompt:
                estimated += self.provider.count_tokens(system_prompt)
            estimated += max_tokens

            if not self.budget.consume(estimated, "stream_estimate"):
                raise TokenBudgetExceeded(
                    f"Token budget exceeded: {self.budget._used}/{self.budget.total_limit}"
                )

        start_time = time.time()
        total_chunks = 0
        collected_text = ""

        try:
            for chunk in self.provider.stream(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            ):
                if not chunk.is_complete:
                    collected_text += chunk.delta
                    total_chunks += 1
                    yield chunk.delta

            # Update metrics
            actual_tokens = self.provider.count_tokens(collected_text)
            if check_budget:
                correction = actual_tokens - (estimated - max_tokens)
                self.budget.consume(correction, "stream_correction")

            execution_time = (time.time() - start_time) * 1000
            self._update_metrics(actual_tokens, execution_time)

        except Exception as e:
            self._metrics["errors"] += 1
            raise

    def _build_messages(
        self,
        system_prompt: Optional[str],
        prompt: str
    ) -> List[LLMMessage]:
        """Build message list from system and user prompts."""
        messages = []
        if system_prompt:
            messages.append(LLMMessage("system", system_prompt))
        messages.append(LLMMessage("user", prompt))
        return messages

    def _update_metrics(self, tokens: int, time_ms: float) -> None:
        """Update usage metrics."""
        self._metrics["total_calls"] += 1
        self._metrics["total_tokens"] += tokens
        self._metrics["total_time_ms"] += time_ms

    def get_metrics(self) -> Dict[str, Any]:
        """Get usage metrics."""
        metrics = self._metrics.copy()
        if metrics["total_calls"] > 0:
            metrics["avg_tokens_per_call"] = metrics["total_tokens"] / metrics["total_calls"]
            metrics["avg_time_ms"] = metrics["total_time_ms"] / metrics["total_calls"]
        return metrics

    def reset_metrics(self) -> None:
        """Reset usage metrics."""
        self._metrics = {
            "total_calls": 0,
            "total_tokens": 0,
            "total_time_ms": 0.0,
            "errors": 0
        }
