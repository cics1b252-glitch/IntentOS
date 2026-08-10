"""Architectural characterization of capability-first convergence."""

import pytest

from intent_kernel.cognition import (
    CapabilityFirstResolver,
    CapabilityRequirement,
    CapabilityRequirementDiscovery,
    CapabilityResolutionStatus,
)
from intent_kernel.rrm.models import (
    AgentResource,
    CapabilityResource,
    ProviderResource,
    ResourceOrigin,
    ResourceStatus,
)
from intent_kernel.rrm.service import RegistryResourceManager
from intent_kernel.tools.models import ToolResource, ToolStatus
from intent_kernel.tools.registry import InMemoryToolRegistry


def requirement(capability_id: str, *, external: bool = False):
    return CapabilityRequirement(
        capability_id=capability_id,
        description=f"Requirement for {capability_id}",
        allows_external_reasoning=external,
        verification_requirements=("verify_result",),
    )


@pytest.mark.asyncio
async def test_unknown_task_reports_missing_instead_of_domain_routing():
    resolver = CapabilityFirstResolver(
        rrm=RegistryResourceManager(populate_defaults=False)
    )
    result = await resolver.resolve(requirement("quantum.sensor.calibrate"))
    assert result.status is CapabilityResolutionStatus.MISSING
    assert result.selected_strategy == "none"
    assert "finance" not in str(result.to_dict()).lower()


@pytest.mark.asyncio
async def test_existing_capability_is_discovered_without_named_domain():
    rrm = RegistryResourceManager(populate_defaults=False)
    rrm.register_capability(
        CapabilityResource(
            capability_id="inventory.tracking",
            name="inventory.tracking",
            resource_origin=ResourceOrigin.CONFIGURATION,
        )
    )
    result = await CapabilityFirstResolver(rrm=rrm).resolve(
        requirement("inventory.tracking")
    )
    assert result.status is CapabilityResolutionStatus.AVAILABLE
    assert result.selected_strategy == "capability:inventory.tracking"


@pytest.mark.asyncio
async def test_tool_available_but_unauthorized_does_not_execute():
    tools = InMemoryToolRegistry()
    await tools.register_tool(
        ToolResource(
            tool_id="factory_writer",
            capabilities=["maintenance.tracking"],
            required_permissions=["factory.write"],
            status=ToolStatus.AVAILABLE,
        )
    )
    result = await CapabilityFirstResolver(
        rrm=RegistryResourceManager(populate_defaults=False),
        tool_registry=tools,
    ).resolve(requirement("maintenance.tracking"))
    assert result.status is CapabilityResolutionStatus.AUTHORIZATION_REQUIRED
    assert result.authorization_requirements == ["factory.write"]


@pytest.mark.asyncio
async def test_unavailable_resource_is_partial_not_fictional():
    rrm = RegistryResourceManager(populate_defaults=False)
    rrm.register_agent(
        AgentResource(
            agent_id="offline_agent",
            name="Offline Agent",
            capabilities=["crop.monitor"],
            status=ResourceStatus.UNAVAILABLE,
        )
    )
    result = await CapabilityFirstResolver(rrm=rrm).resolve(
        requirement("crop.monitor")
    )
    assert result.status is CapabilityResolutionStatus.PARTIAL
    assert result.selected_strategy == "resource_unavailable"


@pytest.mark.asyncio
async def test_multi_capability_mission_produces_composed_graph():
    rrm = RegistryResourceManager(populate_defaults=False)
    for name in ("cost.tracking", "sales.tracking"):
        rrm.register_capability(CapabilityResource(capability_id=name, name=name))
    composition = await CapabilityFirstResolver(rrm=rrm).compose(
        "Organize production and sales",
        [requirement("cost.tracking"), requirement("sales.tracking")],
    )
    assert composition.executable is True
    assert len(composition.steps) == 2
    assert composition.steps[1].dependencies == ("capability_step_1",)


@pytest.mark.asyncio
async def test_no_provider_reports_external_resource_required():
    resolver = CapabilityFirstResolver(
        rrm=RegistryResourceManager(populate_defaults=False)
    )
    result = await resolver.resolve(requirement("content.explain", external=True))
    assert result.status is CapabilityResolutionStatus.EXTERNAL_RESOURCE_REQUIRED
    assert result.selected_strategy == "connect_reasoning_provider"


@pytest.mark.asyncio
async def test_provider_is_selected_only_when_really_eligible():
    rrm = RegistryResourceManager(populate_defaults=False)
    rrm.register_provider(
        ProviderResource(
            provider_id="configured_provider",
            name="Configured Provider",
            is_configured=True,
            has_active_account=True,
        )
    )
    result = await CapabilityFirstResolver(rrm=rrm).resolve(
        requirement("content.explain", external=True)
    )
    assert result.status is CapabilityResolutionStatus.AVAILABLE
    assert result.selected_strategy == "provider:configured_provider"


def test_novel_domains_decompose_into_capabilities_not_modules():
    discovery = CapabilityRequirementDiscovery()
    factory = {item.capability_id for item in discovery.discover(
        "Quero criar um sistema para controlar a produção e manutenção das máquinas de uma pequena fábrica."
    )}
    garden = {item.capability_id for item in discovery.discover(
        "Quero organizar uma pequena horta comercial, acompanhar plantio, custos, produção e vendas."
    )}
    japanese = {item.capability_id for item in discovery.discover(
        "Quero aprender japonês e gostaria que o sistema acompanhasse minha evolução."
    )}
    assert {"requirements.discovery", "data.modeling", "maintenance.tracking", "asset.tracking"} <= factory
    assert {"production.tracking", "cost.tracking", "sales.tracking"} <= garden
    assert {"learning.goal_management", "learning.progress_tracking", "content.explain", "assessment.plan"} <= japanese
    combined = factory | garden | japanese
    assert not any(name in combined for name in {"Atlas", "Logos", "OEM", "Finance"})


@pytest.mark.asyncio
async def test_agent_selection_uses_capability_and_operational_score():
    rrm = RegistryResourceManager(populate_defaults=False)
    rrm.register_agent(AgentResource(
        agent_id="slow_expensive",
        name="Slow",
        capabilities=["workflow.design"],
        historical_confidence=0.95,
        cost_tier=0.3,
        latency_tier=0.9,
    ))
    rrm.register_agent(AgentResource(
        agent_id="reliable",
        name="Reliable",
        capabilities=["workflow.design"],
        historical_confidence=0.92,
        cost_tier=0.01,
        latency_tier=0.1,
    ))
    result = await CapabilityFirstResolver(rrm=rrm).resolve(
        requirement("workflow.design")
    )
    assert result.selected_strategy == "agent:reliable"


@pytest.mark.asyncio
async def test_project_context_is_not_shared_between_resolutions():
    rrm = RegistryResourceManager(populate_defaults=False)
    rrm.register_capability(CapabilityResource(
        capability_id="memory.retrieve", name="memory.retrieve"
    ))
    resolver = CapabilityFirstResolver(rrm=rrm)
    first = await resolver.resolve(
        requirement("memory.retrieve"), context={"project_id": "garden"}
    )
    second = await resolver.resolve(
        requirement("memory.retrieve"), context={"project_id": "factory"}
    )
    assert first.to_dict() == second.to_dict()
    assert "garden" not in str(second.to_dict())


@pytest.mark.asyncio
async def test_constitution_blocks_resolution_before_resource_selection():
    class Verdict:
        allowed = False

    class Constitution:
        async def evaluate(self, action, payload, context):
            assert action == "capability.resolve"
            return Verdict()

    rrm = RegistryResourceManager(populate_defaults=False)
    rrm.register_capability(CapabilityResource(
        capability_id="sales.tracking", name="sales.tracking"
    ))
    result = await CapabilityFirstResolver(
        rrm=rrm, constitution=Constitution()
    ).resolve(requirement("sales.tracking"))
    assert result.status is CapabilityResolutionStatus.BLOCKED_BY_POLICY
    assert result.candidates == []
