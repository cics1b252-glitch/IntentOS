"""Canonical provider selection over RRM resource truth."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable

from intent_kernel.contracts import ErrorCode, ProviderRequest, ProviderResponse


@dataclass(frozen=True, slots=True)
class ProviderSelectionDecision:
    """An immutable selection consumed by ProviderManager invocation bindings."""

    provider_id: str | None
    fallback_provider_id: str | None
    required_capabilities: tuple[str, ...]
    eligible_provider_ids: tuple[str, ...]
    reason: str
    authority: str = "RRM"

    @property
    def available(self) -> bool:
        return self.provider_id is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"available": self.available}


class CanonicalProviderAuthority:
    """Select healthy provider bindings without deciding cognitive necessity."""

    def __init__(self, rrm: Any, provider_manager: Any) -> None:
        self.rrm = rrm
        self.provider_manager = provider_manager
        provider_manager.set_selection_authority(self)

    async def is_eligible(
        self, provider_id: str, required_capabilities: Iterable[str] = ()
    ) -> bool:
        resource = self.rrm.get_provider(provider_id)
        if resource is None or not resource.is_eligible:
            return False
        if provider_id not in self.provider_manager.available:
            return False
        required = set(required_capabilities)
        advertised = set(resource.metadata.get("capabilities", ()))
        if required and not required <= advertised:
            return False
        try:
            return bool(await self.provider_manager.get(provider_id).health())
        except Exception:
            return False

    async def revalidate(self, decision: ProviderSelectionDecision | dict[str, Any]) -> bool:
        provider_id = (
            decision.provider_id
            if isinstance(decision, ProviderSelectionDecision)
            else decision.get("provider_id")
        )
        required = (
            decision.required_capabilities
            if isinstance(decision, ProviderSelectionDecision)
            else decision.get("required_capabilities", ())
        )
        return bool(provider_id) and await self.is_eligible(str(provider_id), required)

    async def select(
        self,
        *,
        required_capabilities: Iterable[str] = ("text_completion",),
        preferred_provider_id: str | None = None,
        fallback_provider_id: str | None = None,
        allow_fallback: bool = False,
    ) -> ProviderSelectionDecision:
        required = tuple(sorted(set(required_capabilities)))
        healthy: list[Any] = []
        for resource in self.rrm.list_providers(only_eligible=True):
            if not await self.is_eligible(resource.provider_id, required):
                continue
            healthy.append(resource)

        healthy.sort(
            key=lambda item: (
                item.provider_id != preferred_provider_id,
                -float(item.reasoning_score),
                float(item.cost_per_1k_tokens),
                item.provider_id,
            )
        )
        eligible = tuple(item.provider_id for item in healthy)
        primary = eligible[0] if eligible else None
        fallback = None
        if allow_fallback and primary is not None:
            requested = fallback_provider_id
            if requested in eligible and requested != primary:
                fallback = requested
            else:
                fallback = next(
                    (item for item in eligible if item != primary), None
                )
        return ProviderSelectionDecision(
            provider_id=primary,
            fallback_provider_id=fallback,
            required_capabilities=required,
            eligible_provider_ids=eligible,
            reason="eligible_provider_selected" if primary else "no_eligible_provider",
        )


class RRMProviderBinding:
    """Provider Port that resolves through RRM immediately before invocation."""

    name = "rrm-selected-provider"
    capabilities = {"text_completion"}

    def __init__(
        self,
        authority: CanonicalProviderAuthority,
        provider_manager: Any,
    ) -> None:
        self.authority = authority
        self.provider_manager = provider_manager

    async def execute(self, request: ProviderRequest) -> ProviderResponse:
        self.provider_manager.reset_execution_tracking()
        required = request.required_capabilities or {"text_completion"}
        decision = await self.authority.select(required_capabilities=required)
        binding = await self.provider_manager.route(None, selection=decision)
        if binding is None:
            return ProviderResponse(
                text="",
                provider="",
                model="",
                error_code=ErrorCode.PROVIDER_UNAVAILABLE,
                metadata={
                    "provider_selection": decision.to_dict(),
                    "provider_selection_authority": "RRM",
                },
            )
        return await binding.execute(request)

    async def health(self) -> bool:
        decision = await self.authority.select(
            required_capabilities=self.capabilities
        )
        return decision.available
