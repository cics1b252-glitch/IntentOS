"""Sprint 5 tests for canonical Core Apps and Capability Router."""

from __future__ import annotations

import pytest

from intent_kernel.application import KernelBuilder
from intent_kernel.contracts import (
    Capability,
    CapabilityRequest,
    CoreApp,
    Domain,
    ErrorCode,
    KnowledgeEvent,
    Mission,
    MissionContext,
)
from intent_kernel.core_apps import (
    AtlasCoreApp,
    CapabilityRegistrationError,
    CapabilityRouter,
    LogosCoreApp,
    OEMStudioCoreApp,
)
from intent_kernel.modules.fin import FinanceModule
from intent_kernel.types import Domain as LegacyDomain
from intent_kernel.types import IntentInput


def _mission(domain: Domain, objective: str = "Test") -> Mission:
    return Mission(
        objective=objective,
        context=MissionContext(domain=domain),
    )


def test_official_core_apps_implement_one_contract(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()

    assert [app.app_id for app in components.core_apps] == [
        "atlas",
        "logos",
        "oem_studio",
    ]
    assert all(isinstance(app, CoreApp) for app in components.core_apps)


def test_router_selects_core_app_by_explicit_capability(tmp_path):
    router = (
        KernelBuilder()
        .with_pkb_path(tmp_path / "pkb")
        .build()
        .capability_router
    )

    assert router.select(_mission(Domain.OTHER), "finance.intent").app_id == "atlas"
    assert router.select(_mission(Domain.OTHER), "knowledge.project.list").app_id == "logos"
    assert router.select(_mission(Domain.OTHER), "engineering.project.list").app_id == "oem_studio"


def test_router_identifies_default_capability_from_mission_domain(tmp_path):
    router = (
        KernelBuilder()
        .with_pkb_path(tmp_path / "pkb")
        .build()
        .capability_router
    )

    assert router.select(_mission(Domain.FINANCE)).app_id == "atlas"
    assert router.select(_mission(Domain.RESEARCH)).app_id == "logos"
    assert router.select(_mission(Domain.ENGINEERING)).app_id == "oem_studio"


@pytest.mark.asyncio
async def test_atlas_preserves_characterized_fin_response():
    app = AtlasCoreApp()
    mission = _mission(Domain.FINANCE, "quero investir 5000")
    request = CapabilityRequest(
        mission=mission,
        capability="finance.intent",
        payload={"text": mission.objective},
    )

    canonical = await app.execute(request)
    legacy = await FinanceModule().execute(
        IntentInput(
            text=mission.objective,
            domain=LegacyDomain.FINANCE,
        )
    )

    assert canonical.success is True
    assert canonical.output == legacy["text"]
    assert canonical.confidence == legacy["confidence"]


@pytest.mark.asyncio
async def test_logos_project_operations_use_existing_domain_behavior():
    app = LogosCoreApp()
    mission = _mission(Domain.RESEARCH, "Knowledge project")

    created = await app.execute(
        CapabilityRequest(
            mission=mission,
            capability="knowledge.project.create",
            payload={"name": "Canonical project"},
        )
    )
    listed = await app.execute(
        CapabilityRequest(
            mission=mission,
            capability="knowledge.project.list",
        )
    )

    assert created.success is True
    assert created.output["name"] == "Canonical project"
    assert listed.output[0]["id"] == created.output["id"]


@pytest.mark.asyncio
async def test_logos_queries_canonical_pkb_port(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    logos = next(
        app for app in components.core_apps if app.app_id == "logos"
    )
    event = KnowledgeEvent(
        event_type="fact",
        title="PKB fact",
        content={"raw": "canonical"},
        domain=Domain.RESEARCH,
    )
    await components.knowledge_store.append(event)

    result = await logos.execute(
        CapabilityRequest(
            mission=_mission(Domain.RESEARCH),
            capability="knowledge.search",
        )
    )

    assert result.success is True
    assert result.output[0]["id"] == event.id


@pytest.mark.asyncio
async def test_oem_studio_remains_infrastructure_independent():
    app = OEMStudioCoreApp()
    mission = _mission(Domain.ENGINEERING, "CarPlay prototype")

    created = await app.execute(
        CapabilityRequest(
            mission=mission,
            capability="engineering.project.create",
            payload={"name": "CarPlay"},
        )
    )
    listed = await app.execute(
        CapabilityRequest(
            mission=mission,
            capability="engineering.project.list",
        )
    )

    assert created.output["name"] == "CarPlay"
    assert listed.output[0]["id"] == created.output["id"]
    assert app.domain.kernel is None


@pytest.mark.asyncio
async def test_router_returns_canonical_unavailable_result(tmp_path):
    router = (
        KernelBuilder()
        .with_pkb_path(tmp_path / "pkb")
        .build()
        .capability_router
    )

    result = await router.execute_mission(
        _mission(Domain.OTHER),
        "missing.capability",
    )

    assert result.success is False
    assert result.error_code is ErrorCode.CAPABILITY_UNAVAILABLE


def test_router_rejects_ambiguous_capability_ownership():
    class App:
        def __init__(self, app_id):
            self.app_id = app_id
            self.capabilities = (Capability(name="same"),)

        async def execute(self, request):
            raise AssertionError

        async def health(self):
            return True

    router = CapabilityRouter()
    router.register(App("one"))

    with pytest.raises(CapabilityRegistrationError):
        router.register(App("two"))


def test_legacy_module_router_and_adapter_remain_available(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    legacy_module = components.module_router.route(
        IntentInput(
            text="quero investir",
            domain=LegacyDomain.FINANCE,
        )
    )

    assert legacy_module.name == "fin"
    assert set(components.module_router.registered_modules) == {
        "core",
        "fin",
    }
    assert {
        capability.name
        for capability in components.legacy_capability_executor.capabilities
    } == {"core", "fin"}
