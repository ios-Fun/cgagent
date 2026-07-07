"""OpenAI LLM Provider implementation."""

import time
from typing import List, Optional, Iterator
from ..llm_base import LLMProvider, LLMMessage, LLMResponse, StreamChunk


class OpenAIProvider(LLMProvider):
    """OpenAI API provider implementation."""

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        default_model: str = "gpt-4"
    ):
        """Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key
            base_url: Optional base URL for API requests
            default_model: Default model to use
        """
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "OpenAI package is required. Install with: pip install openai"
            )

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self._default_model = default_model

    def invoke(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> LLMResponse:
        """Invoke OpenAI API."""
        self._validate_messages(messages)

        start_time = time.time()
        response = self.client.chat.completions.create(
            model=model or self._default_model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

        return LLMResponse(
            content=response.choices[0].message.content or "",
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
            execution_time_ms=(time.time() - start_time) * 1000
        )

    def stream(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> Iterator[StreamChunk]:
        """Stream OpenAI API response."""
        self._validate_messages(messages)

        stream = self.client.chat.completions.create(
            model=model or self._default_model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs
        )

        for chunk in stream:
            delta = chunk.choices[0].delta.content
            if delta:
                yield StreamChunk(delta=delta, is_complete=False)

        yield StreamChunk(delta="", is_complete=True)

    def count_tokens(self, text: str) -> int:
        """Estimate token count using tiktoken."""
        try:
            import tiktoken
        except ImportError:
            # Fallback: rough estimate (1 token ≈ 4 characters for English)
            return len(text) // 4

        try:
            encoding = tiktoken.encoding_for_model(self._default_model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")

        return len(encoding.encode(text))

    @property
    def provider_name(self) -> str:
        return "openai"
