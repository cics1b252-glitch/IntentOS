"""Provider Layer — 3-level architecture for external service integration.

Level 1: Provider Interface (contract)
Level 2: Provider Registry (registration, selection, failover)
Level 3: Provider Implementations (OpenAI, Gemini, Claude, etc.)

No Core App or Kernel component knows a specific provider.
All access goes through public interfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Level 1: Provider Interfaces (Contracts)
# ---------------------------------------------------------------------------

@runtime_checkable
class LLMProviderInterface(Protocol):
    """Contract for LLM providers."""

    @property
    def name(self) -> str: ...

    @property
    def models(self) -> list[str]: ...

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict:
        """Generate a completion. Returns {"text": str, "model": str, "usage": dict}."""
        ...

    async def health_check(self) -> bool:
        """Check if provider is available."""
        ...


@runtime_checkable
class StorageProviderInterface(Protocol):
    """Contract for storage providers."""

    @property
    def name(self) -> str: ...

    async def store(self, key: str, data: bytes) -> bool: ...

    async def retrieve(self, key: str) -> bytes | None: ...

    async def delete(self, key: str) -> bool: ...

    async def list_keys(self, prefix: str = "") -> list[str]: ...

    async def health_check(self) -> bool: ...


@runtime_checkable
class SearchProviderInterface(Protocol):
    """Contract for search providers."""

    @property
    def name(self) -> str: ...

    async def search(self, query: str, limit: int = 10) -> list[dict]: ...

    async def health_check(self) -> bool: ...


# ---------------------------------------------------------------------------
# Level 2: Provider Registry
# ---------------------------------------------------------------------------

@dataclass
class ProviderInfo:
    """Metadata about a registered provider."""
    name: str
    provider_type: str  # "llm" | "storage" | "search"
    instance: Any
    active: bool = True
    priority: int = 0  # lower = higher priority
    last_health_check: str = ""
    healthy: bool = True


class ProviderRegistry:
    """Central registry for all providers.

    Responsibilities:
    - Register providers
    - Load providers
    - Select active provider
    - Future: failover
    """

    def __init__(self):
        self._providers: dict[str, ProviderInfo] = {}

    def register(self, name: str, provider_type: str, instance: Any, priority: int = 0) -> None:
        """Register a provider."""
        self._providers[name] = ProviderInfo(
            name=name,
            provider_type=provider_type,
            instance=instance,
            priority=priority,
        )

    def get(self, name: str) -> Any | None:
        """Get a provider by name."""
        info = self._providers.get(name)
        return info.instance if info else None

    def get_active(self, provider_type: str) -> Any | None:
        """Get the highest-priority active provider of a type."""
        candidates = [
            info for info in self._providers.values()
            if info.provider_type == provider_type and info.active and info.healthy
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda i: i.priority)[0].instance

    def list_providers(self, provider_type: str | None = None) -> list[dict]:
        """List all registered providers."""
        results = []
        for info in self._providers.values():
            if provider_type and info.provider_type != provider_type:
                continue
            results.append({
                "name": info.name,
                "type": info.provider_type,
                "active": info.active,
                "healthy": info.healthy,
                "priority": info.priority,
            })
        return results

    def deactivate(self, name: str) -> None:
        """Deactivate a provider."""
        if name in self._providers:
            self._providers[name].active = False

    def activate(self, name: str) -> None:
        """Activate a provider."""
        if name in self._providers:
            self._providers[name].active = True

    async def health_check_all(self) -> dict[str, bool]:
        """Run health check on all providers."""
        results = {}
        for name, info in self._providers.items():
            try:
                healthy = await info.instance.health_check()
                info.healthy = healthy
                results[name] = healthy
            except Exception:
                info.healthy = False
                results[name] = False
        return results

    def status(self) -> dict[str, Any]:
        """Get registry status for Monitor."""
        by_type = {}
        for info in self._providers.values():
            by_type.setdefault(info.provider_type, []).append({
                "name": info.name,
                "active": info.active,
                "healthy": info.healthy,
            })
        return {
            "total": len(self._providers),
            "by_type": by_type,
        }
