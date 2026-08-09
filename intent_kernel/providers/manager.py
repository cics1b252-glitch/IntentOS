"""ProviderManager — manages LLM providers and routing."""

from __future__ import annotations

from intent_kernel.contracts import Provider, ProviderRequest, ProviderResponse
from intent_kernel.types import Mode


class ProviderManager:
    """Manages registered LLM providers and routes requests.

    In Sprint 0, only MockProvider is registered.
    Real providers (OpenAI, Claude, etc.) are added in Sprint 1.
    """

    def __init__(self):
        self._providers: dict[str, Provider] = {}
        self._default: str | None = None
        self._fallback_allowed = False
        self._fallback: str | None = None
        self._last_used: str | None = None
        self._last_attempted: str | None = None
        self._observer = None

    def set_observer(self, observer) -> None:
        """Attach a non-sensitive execution observer owned by the interface."""
        self._observer = observer

    def observe(self, event: str, **metadata) -> None:
        if self._observer is not None:
            self._observer(event, metadata)

    def reset_execution_tracking(self) -> None:
        """Start a request without inheriting Provider attribution from a prior turn."""
        self._last_used = None
        self._last_attempted = None

    def register(self, name: str, provider: Provider) -> None:
        """Register a provider."""
        self._providers[name] = provider
        if self._default is None:
            self._default = name

    def get(self, name: str | None = None) -> Provider:
        """Get a provider by name, or the default."""
        target = name or self._default
        if target is None:
            raise KeyError("No providers registered")
        if target not in self._providers:
            raise KeyError(f"Provider '{target}' not found")
        return self._providers[target]

    def set_default(self, name: str) -> None:
        """Select a registered provider without exposing registry internals."""
        if name not in self._providers:
            raise KeyError(f"Provider '{name}' not found")
        self._default = name

    def configure_fallback(self, allowed: bool, name: str | None = None) -> None:
        """Scope an explicitly authorized fallback to the current execution."""
        if name is not None and name not in self._providers:
            raise KeyError(f"Provider '{name}' not found")
        self._fallback_allowed = bool(allowed)
        self._fallback = name if allowed else None
        self._last_used = None
        self._last_attempted = None

    @property
    def fallback(self) -> str | None:
        return self._fallback if self._fallback_allowed else None

    @property
    def last_used(self) -> str | None:
        return self._last_used

    @property
    def last_attempted(self) -> str | None:
        return self._last_attempted

    async def route(self, mode: Mode) -> Provider:
        """Route to the best provider based on mode.

        Sprint 0: always returns the default (MockProvider).
        Sprint 1: QUICK→fast/cheap, ARCHITECT→powerful.
        """
        return self.get()

    @property
    def default(self) -> str | None:
        return self._default

    @property
    def available(self) -> list[str]:
        """List of registered provider names."""
        return list(self._providers.keys())


class ManagedProvider:
    """Dynamic Provider Port bound to the manager's selected default."""

    def __init__(self, manager: ProviderManager):
        self._manager = manager

    @property
    def name(self) -> str:
        return self._manager.get().name

    @property
    def capabilities(self) -> set[str]:
        return self._manager.get().capabilities

    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        primary = self._manager.get()
        self._manager._last_attempted = primary.name
        self._manager.observe("provider_request_started", provider=primary.name,
                              model=getattr(primary, "model", "unknown"))
        try:
            response = await primary.execute(request)
            self._manager._last_used = primary.name
            self._manager.observe("provider_response_received", provider=primary.name,
                                  model=response.model, status="success")
            return response
        except Exception as exc:
            self._manager.observe("provider_response_received", provider=primary.name,
                                  status="error", error=type(exc).__name__)
            fallback = self._manager.fallback
            if not fallback or fallback == primary.name:
                raise
            alternate = self._manager.get(fallback)
            self._manager._last_attempted = alternate.name
            self._manager.observe("provider_request_started", provider=alternate.name,
                                  model=getattr(alternate, "model", "unknown"), fallback=True)
            response = await alternate.execute(request)
            self._manager._last_used = alternate.name
            self._manager.observe("provider_response_received", provider=alternate.name,
                                  model=response.model, status="success", fallback=True)
            return response

    async def health(self) -> bool:
        return bool(await self._manager.get().health())
