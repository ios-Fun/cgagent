"""Anthropic (Claude) LLM Provider implementation."""

import time
from typing import List, Optional, Iterator
from agent.llm_base import LLMProvider, LLMMessage, LLMResponse, StreamChunk


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider implementation."""

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        default_model: str = "claude-3-opus-20240229"
    ):
        """Initialize Anthropic provider.

        Args:
            api_key: Anthropic API key
            base_url: Optional base URL (not typically used)
            default_model: Default model to use
        """
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError(
                "Anthropic package is required. Install with: pip install anthropic"
            )

        self.client = Anthropic(api_key=api_key, base_url=base_url)
        self._default_model = default_model

    def invoke(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> LLMResponse:
        """Invoke Anthropic API."""
        self._validate_messages(messages)

        # Extract system message if present
        system_message = ""
        user_messages = []
        for msg in messages:
            if msg.role == "system":
                system_message = msg.content
            else:
                user_messages.append({"role": msg.role, "content": msg.content})

        start_time = time.time()
        response = self.client.messages.create(
            model=model or self._default_model,
            system=system_message if system_message else None,
            messages=user_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

        return LLMResponse(
            content=response.content[0].text,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
                "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
            }
        )

    def stream(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> Iterator[StreamChunk]:
        """Stream Anthropic API response."""
        self._validate_messages(messages)

        # Extract system message if present
        system_message = ""
        user_messages = []
        for msg in messages:
            if msg.role == "system":
                system_message = msg.content
            else:
                user_messages.append({"role": msg.role, "content": msg.content})

        with self.client.messages.stream(
            model=model or self._default_model,
            system=system_message if system_message else None,
            messages=user_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        ) as stream:
            for text in stream.text_stream:
                yield StreamChunk(delta=text, is_complete=False)

        yield StreamChunk(delta="", is_complete=True)

    def count_tokens(self, text: str) -> int:
        """Estimate token count for Anthropic.

        Anthropic uses a different tokenization. Rough estimate:
        1 token ≈ 3.5 characters for Claude
        """
        # A rough estimate for Claude's tokenization
        return len(text) // 3

    @property
    def provider_name(self) -> str:
        return "anthropic"
