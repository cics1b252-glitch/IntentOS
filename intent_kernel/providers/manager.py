"""ProviderManager — manages LLM providers and routing."""

from __future__ import annotations

from intent_kernel.contracts import Provider, ProviderRequest, ProviderResponse
from intent_kernel.compatibility import compatibility_trace
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
        self._resource_projection = None
        self._selection_authority = None
        self._last_compatibility_trace = None

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
        """Register an invocation binding; RRM still decides availability."""
        self._providers[name] = provider
        if self._default is None:
            self._default = name
        if self._resource_projection is not None:
            self._resource_projection(provider)

    def set_resource_projection(self, projection) -> None:
        """Project future bindings into RRM without granting them eligibility."""
        self._resource_projection = projection

    def set_selection_authority(self, authority) -> None:
        """Attach the RRM authority that must revalidate canonical selections."""
        self._selection_authority = authority

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

    async def route(self, mode: Mode, selection=None) -> Provider | None:
        """Bind an RRM selection; direct calls retain a compatibility default."""
        if selection is not None:
            self._last_compatibility_trace = None
            provider_id = getattr(selection, "provider_id", None)
            if provider_id is None and isinstance(selection, dict):
                provider_id = selection.get("provider_id")
            if provider_id is None:
                return None
            if (
                self._selection_authority is None
                or not await self._selection_authority.revalidate(selection)
            ):
                return None
            fallback = getattr(selection, "fallback_provider_id", None)
            if fallback is None and isinstance(selection, dict):
                fallback = selection.get("fallback_provider_id")
            primary = self._providers.get(str(provider_id))
            return ManagedProvider(
                self,
                provider_id=str(provider_id),
                fallback_provider_id=str(fallback) if fallback else None,
                bound_provider=primary,
            )
        # Direct Kernel callers retain the characterized compatibility default.
        self._last_compatibility_trace = compatibility_trace(
            "ProviderManager",
            "direct_caller_used_registered_default_without_rrm_selection",
            entry_point="ProviderManager.route.direct_default",
            canonical_alternative_missing="canonical_provider_selection",
        ).to_dict()
        # Compatibility callers still cross the observed invocation boundary.
        # Returning the raw binding here would make a real direct invocation
        # invisible to last_attempted/last_used and downstream provenance.
        return ManagedProvider(self, provider_id=self._default)

    def bind_selected(
        self,
        provider_id: str,
        *,
        expected_binding: Provider | None = None,
    ) -> Provider | None:
        """Bind an already RRM-selected provider without selecting a fallback."""

        provider = self._providers.get(provider_id)
        if provider is None:
            return None
        if expected_binding is not None and provider is not expected_binding:
            return None
        self._last_compatibility_trace = None
        return ManagedProvider(
            self,
            provider_id=provider_id,
            allow_manager_fallback=False,
        )

    @property
    def default(self) -> str | None:
        return self._default

    @property
    def available(self) -> list[str]:
        """List of registered provider names."""
        return list(self._providers.keys())

    @property
    def last_compatibility_trace(self) -> dict | None:
        return dict(self._last_compatibility_trace) if self._last_compatibility_trace else None


class ManagedProvider:
    """Dynamic Provider Port bound to the manager's selected default."""

    def __init__(
        self,
        manager: ProviderManager,
        *,
        provider_id: str | None = None,
        fallback_provider_id: str | None = None,
        allow_manager_fallback: bool = True,
        bound_provider: Provider | None = None,
    ):
        self._manager = manager
        self._provider_id = provider_id
        self._fallback_provider_id = fallback_provider_id
        self._allow_manager_fallback = allow_manager_fallback
        self._bound_provider = bound_provider

    @property
    def name(self) -> str:
        return self._manager.get(self._provider_id).name

    @property
    def capabilities(self) -> set[str]:
        return self._manager.get(self._provider_id).capabilities

    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        primary = (
            self._bound_provider
            if self._bound_provider is not None
            else self._manager.get(self._provider_id)
        )
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
            fallback = self._fallback_provider_id
            if fallback is None and self._allow_manager_fallback:
                fallback = self._manager.fallback
            if not fallback or fallback == primary.name:
                raise
            alternate = self._manager.get(fallback)
            if (
                self._manager._selection_authority is not None
                and not await self._manager._selection_authority.is_eligible(
                    fallback, {"text_completion"}
                )
            ):
                raise
            self._manager._last_attempted = alternate.name
            self._manager.observe("provider_request_started", provider=alternate.name,
                                  model=getattr(alternate, "model", "unknown"), fallback=True)
            response = await alternate.execute(request)
            self._manager._last_used = alternate.name
            self._manager.observe("provider_response_received", provider=alternate.name,
                                  model=response.model, status="success", fallback=True)
            return response

    async def health(self) -> bool:
        return bool(await self._manager.get(self._provider_id).health())
