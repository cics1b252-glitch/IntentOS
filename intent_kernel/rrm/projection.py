"""Compatibility projection from executable registries into canonical RRM."""

from __future__ import annotations

from typing import Any

from intent_kernel.rrm.models import (
    AgentResource,
    AvailabilitySource,
    CapabilityResource,
    ProviderResource,
    ResourceOrigin,
)


class RuntimeResourceProjection:
    """Write resource truth to RRM while legacy registries retain bindings."""

    def __init__(self, rrm: Any) -> None:
        self.rrm = rrm

    def project_core_app(self, app: Any) -> None:
        for capability in app.capabilities:
            self.rrm.register_capability(CapabilityResource(
                capability_id=capability.name,
                name=capability.name,
                description=capability.description,
                version=capability.version,
                tags=list(capability.tags),
                domains=[item.value for item in capability.domains],
                effect=capability.effect.value,
                requires_network=capability.requires_network,
                requires_confirmation=capability.requires_confirmation,
                resource_origin=ResourceOrigin.MIGRATION,
                availability_source=AvailabilitySource.CONFIGURATION,
                metadata={"executor_kind": "core_app", "executor_id": app.app_id},
            ))

    def project_agent(self, agent: Any) -> None:
        capabilities = [item.name for item in agent.capabilities]
        self.rrm.register_agent(AgentResource(
            agent_id=str(agent.agent_id),
            name=str(agent.agent_id),
            capabilities=capabilities,
            resource_origin=ResourceOrigin.MIGRATION,
            availability_source=AvailabilitySource.CONFIGURATION,
            metadata={"executor_kind": "agent"},
        ))

    def project_provider(self, provider: Any) -> None:
        name = str(provider.name)
        self.rrm.register_provider(ProviderResource(
            provider_id=name,
            name=name,
            resource_origin=ResourceOrigin.CONFIGURATION,
            availability_source=AvailabilitySource.CONFIGURATION,
            is_configured=name != "mock",
            has_active_account=name != "mock",
            metadata={
                "executor_kind": "provider",
                "capabilities": sorted(provider.capabilities),
                "demonstration": name == "mock",
            },
        ))
