"""Provider base — interface for LLM providers."""

from __future__ import annotations

from intent_kernel.contracts import (
    ProviderRequest,
    ProviderResponse,
)
from intent_kernel.types import CompletionResult, Message


class LLMProvider:
    """Base class for LLM providers.

    Subclass this and implement `complete()` for real providers.
    """

    name: str = "base"
    models: list[str] = []

    @property
    def capabilities(self) -> set[str]:
        """Canonical capabilities exposed without changing legacy behavior."""
        return {"text_completion"}

    async def complete(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> CompletionResult:
        """Generate a completion. Override in subclasses."""
        raise NotImplementedError("Subclass must implement complete()")

    async def health_check(self) -> bool:
        """Check if the provider is available."""
        return True

    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        """Implement the canonical Provider Port through the legacy API."""
        result = await self.complete(
            [
                Message(role=message.role, content=message.content)
                for message in request.messages
            ],
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        return ProviderResponse(
            text=result.text,
            provider=self.name,
            model=result.model,
            usage=dict(result.usage),
            finish_reason=result.finish_reason,
        )

    async def health(self) -> bool:
        """Canonical health operation."""
        return bool(await self.health_check())
