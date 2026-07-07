"""Ollama LLM Provider implementation for local models."""

import json
import time
from typing import List, Optional, Iterator
from ..llm_base import LLMProvider, LLMMessage, LLMResponse, StreamChunk


class OllamaProvider(LLMProvider):
    """Ollama provider for running local models."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 11434,
        default_model: str = "llama2"
    ):
        """Initialize Ollama provider.

        Args:
            host: Ollama server host
            port: Ollama server port
            default_model: Default model to use
        """
        self.base_url = f"http://{host}:{port}"
        self._default_model = default_model

    def invoke(
        self,
        messages: List[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> LLMResponse:
        """Invoke Ollama API."""
        self._validate_messages(messages)

        import requests

        payload = {
            "model": model or self._default_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }

        start_time = time.time()
        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=120
        )
        response.raise_for_status()

        data = response.json()
        content = data.get("message", {}).get("content", "")

        # Ollama doesn't return token counts, estimate them
        prompt_tokens = sum(len(m.content) // 3 for m in messages)
        completion_tokens = len(content) // 3

        return LLMResponse(
            content=content,
            model=model or self._default_model,
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
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
        """Stream Ollama API response."""
        self._validate_messages(messages)

        import requests

        payload = {
            "model": model or self._default_model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            }
        }

        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            stream=True,
            timeout=120
        )

        for line in response.iter_lines():
            if line:
                data = json.loads(line)
                if "message" in data:
                    content = data["message"].get("content", "")
                    if content:
                        yield StreamChunk(delta=content, is_complete=False)

                if data.get("done", False):
                    yield StreamChunk(delta="", is_complete=True)
                    break

    def count_tokens(self, text: str) -> int:
        """Estimate token count for local models.

        Rough estimate since we don't know the exact tokenizer.
        """
        return len(text) // 3

    @property
    def provider_name(self) -> str:
        return "ollama"
