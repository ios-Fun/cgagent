"""Zhipu GLM LLM Provider implementation."""

import time
from typing import List, Optional, Iterator
from agent.llm_base import LLMProvider, LLMMessage, LLMResponse, StreamChunk


class ZhipuProvider(LLMProvider):
    """Zhipu GLM API provider implementation."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://open.bigmodel.cn/api/paas/v4",
        default_model: str = "glm-4"
    ):
        """Initialize Zhipu GLM provider.

        Args:
            api_key: Zhipu API key (format: id.secret)
            base_url: Optional base URL for API requests
            default_model: Default model to use
        """
        try:
            from zhipuai import ZhipuAI
        except ImportError:
            raise ImportError(
                "ZhipuAI package is required. Install with: pip install zhipuai"
            )

        self.client = ZhipuAI(api_key=api_key, base_url=base_url)
        self._default_model = default_model or "glm-4-flash"

    def invoke(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> LLMResponse:
        """Invoke Zhipu GLM API."""
        self._validate_messages(messages)

        # Convert messages to Zhipu format
        zhipu_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
        ]

        start_time = time.time()
        response = self.client.chat.completions.create(
            model=model or self._default_model,
            messages=zhipu_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )

        execution_time = (time.time() - start_time) * 1000
        return LLMResponse(
            content=response.choices[0].message.content or "",
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
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
        """Stream Zhipu GLM API response."""
        self._validate_messages(messages)

        zhipu_messages = [
            {"role": m.role, "content": m.content}
            for m in messages
        ]

        stream = self.client.chat.completions.create(
            model=model or self._default_model,
            messages=zhipu_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs
        )

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield StreamChunk(
                    delta=chunk.choices[0].delta.content,
                    is_complete=False
                )

        yield StreamChunk(delta="", is_complete=True)

    def count_tokens(self, text: str) -> int:
        """Estimate token count for Zhipu GLM.

        For Chinese text: approximately 1 token per 1.5-2 characters
        For English text: approximately 1 token per 4 characters
        """
        # Rough estimate for mixed Chinese/English text
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        total_chars = len(text)
        english_chars = total_chars - chinese_chars

        # Approximate: Chinese ≈ 1/2 token, English ≈ 1/4 token
        estimated = (chinese_chars // 2) + (english_chars // 4)
        return max(estimated, 1)  # At least 1 token

    @property
    def provider_name(self) -> str:
        return "zhipu"
