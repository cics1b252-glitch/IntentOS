"""OpenAI Provider — real LLM integration for the Intent OS Kernel."""

from __future__ import annotations

import os
from typing import Any

from intent_kernel.providers.base import LLMProvider
from intent_kernel.types import CompletionResult, Message


class OpenAIProvider(LLMProvider):
    """OpenAI LLM provider.

    Requires: openai>=1.0
    Set OPENAI_API_KEY environment variable or pass api_key to constructor.
    """

    name = "openai"
    models = ["gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]

    def __init__(self, api_key: str | None = None, default_model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.default_model = default_model
        self._client = None

    @property
    def client(self):
        """Lazy-init OpenAI client."""
        if self._client is None:
            if not self.api_key:
                raise ValueError(
                    "OpenAI API key required. Set OPENAI_API_KEY or pass api_key."
                )
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError(
                    "openai package required. Install: pip install openai"
                )
        return self._client

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> CompletionResult:
        """Generate a completion using OpenAI API."""
        use_model = model or self.default_model

        # Convert to OpenAI format
        oai_messages = [{"role": m.role, "content": m.content} for m in messages]

        response = await self.client.chat.completions.create(
            model=use_model,
            messages=oai_messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        choice = response.choices[0]
        usage = response.usage

        return CompletionResult(
            text=choice.message.content or "",
            model=response.model,
            usage={
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "total_tokens": usage.total_tokens if usage else 0,
            },
            finish_reason=choice.finish_reason or "stop",
        )

    async def health_check(self) -> bool:
        """Check if OpenAI API is accessible."""
        try:
            response = await self.client.models.list()
            return True
        except Exception:
            return False
