"""LLM Provider abstraction layer."""

from abc import ABC, abstractmethod
from typing import Iterator, Optional, Dict, Any, List
from dataclasses import dataclass


@dataclass
class LLMMessage:
    """A message in the conversation."""
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    """Response from LLM invocation."""
    content: str
    model: str
    usage: Dict[str, int]  # {"prompt_tokens": 100, "completion_tokens": 200}


@dataclass
class StreamChunk:
    """A chunk of streamed response."""
    delta: str
    is_complete: bool = False


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    def invoke(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> LLMResponse:
        """Invoke LLM synchronously.

        Args:
            messages: List of conversation messages
            model: Model name (uses default if None)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific parameters

        Returns:
            LLMResponse with content, model, and usage info
        """
        pass

    @abstractmethod
    def stream(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> Iterator[StreamChunk]:
        """Stream LLM response.

        Args:
            messages: List of conversation messages
            model: Model name (uses default if None)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific parameters

        Yields:
            StreamChunk with delta content
        """
        pass

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Count tokens in text.

        Args:
            text: Text to count tokens for

        Returns:
            Estimated token count
        """
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider name identifier."""
        pass

    def _validate_messages(self, messages: List[LLMMessage]) -> None:
        """Validate message format."""
        if not messages:
            raise ValueError("Messages list cannot be empty")

        valid_roles = {"system", "user", "assistant"}
        for msg in messages:
            if msg.role not in valid_roles:
                raise ValueError(f"Invalid role: {msg.role}. Must be one of {valid_roles}")
            if not isinstance(msg.content, str):
                raise ValueError("Message content must be a string")
