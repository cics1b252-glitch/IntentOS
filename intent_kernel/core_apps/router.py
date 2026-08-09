"""Canonical Capability Router for Intent OS v2."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from intent_kernel.contracts import (
    Capability,
    CapabilityRequest,
    CapabilityResult,
    CoreApp,
    Domain,
    ErrorCode,
    Mission,
    MissionContext,
)


class CapabilityRegistrationError(ValueError):
    """Raised when two Core Apps claim the same capability."""


class CapabilityRouter:
    """Official routing point from Missions to independent Core Apps."""

    _DOMAIN_DEFAULTS = {
        Domain.FINANCE: "finance.intent",
        Domain.ENGINEERING: "engineering.intent",
        Domain.PROGRAMMING: "engineering.intent",
        Domain.RESEARCH: "knowledge.intent",
        Domain.WRITING: "knowledge.intent",
        Domain.PLANNING: "knowledge.intent",
        Domain.EDUCATION: "knowledge.intent",
    }

    def __init__(self):
        self._apps: dict[str, CoreApp] = {}
        self._capability_map: dict[str, str] = {}

    def register(self, app: CoreApp) -> None:
        for descriptor in app.capabilities:
            owner = self._capability_map.get(descriptor.name)
            if owner is not None and owner != app.app_id:
                raise CapabilityRegistrationError(
                    f"Capability {descriptor.name} already owned by {owner}"
                )
        self._apps[app.app_id] = app
        for descriptor in app.capabilities:
            self._capability_map[descriptor.name] = app.app_id

    def select(
        self,
        mission: Mission,
        capability: str | None = None,
    ) -> CoreApp | None:
        requested = capability or self._DOMAIN_DEFAULTS.get(
            mission.context.domain,
            "",
        )
        owner = self._capability_map.get(requested)
        return self._apps.get(owner) if owner else None

    async def execute_mission(
        self,
        mission: Mission,
        capability: str | None = None,
        payload: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> CapabilityResult:
        requested = capability or self._DOMAIN_DEFAULTS.get(
            mission.context.domain,
            "",
        )
        app = self.select(mission, requested)
        if app is None:
            return CapabilityResult(
                capability=requested,
                success=False,
                error_code=ErrorCode.CAPABILITY_UNAVAILABLE,
                metadata={"mission_id": str(mission.id)},
            )
        result = await app.execute(
            CapabilityRequest(
                mission=mission,
                capability=requested,
                payload=deepcopy(payload or {}),
                context=deepcopy(context or {}),
            )
        )
        result.metadata.setdefault("core_app", app.app_id)
        result.metadata.setdefault("mission_id", str(mission.id))
        return result

    @property
    def capabilities(self) -> tuple[Capability, ...]:
        return tuple(
            descriptor
            for app in self._apps.values()
            for descriptor in app.capabilities
        )

    @property
    def registered_apps(self) -> tuple[str, ...]:
        return tuple(self._apps)

    async def execute(
        self,
        capability: str,
        payload: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> CapabilityResult:
        values = deepcopy(context or {})
        domain_value = payload.get("domain", values.get("domain", "other"))
        try:
            domain = Domain(str(domain_value))
        except ValueError:
            domain = Domain.OTHER
        mission = Mission(
            objective=str(payload.get("text", capability)),
            context=MissionContext(
                session_id=str(values.get("session_id", "")),
                correlation_id=str(values.get("correlation_id", "")),
                domain=domain,
                values=values,
            ),
        )
        return await self.execute_mission(
            mission,
            capability,
            payload,
            context,
        )
