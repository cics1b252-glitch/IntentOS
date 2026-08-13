"""Sprint 7 tests for canonical bootstrap and composition convergence."""

from __future__ import annotations

import inspect

import pytest

from intent_kernel.__main__ import create_cli_kernel
from intent_kernel.application import ApplicationFactory, KernelBuilder
from intent_kernel.capabilities import CapabilityRegistry as LegacyRegistry
from intent_kernel.kernel import Kernel
from intent_kernel.modules.fin import FinanceModule
from intent_kernel.monitor import IntentOSMonitor
from intent_kernel.providers import ProviderManager
from intent_kernel.types import Domain, IntentInput
from intent_os_desktop import create_app


def _factory(tmp_path):
    return ApplicationFactory(
        KernelBuilder().with_pkb_path(tmp_path / "pkb")
    )


def test_application_factory_composes_complete_canonical_graph(tmp_path):
    components = _factory(tmp_path).get_components()

    assert components.bootstrap_mode == "canonical"
    assert components.kernel.bootstrap_mode == "canonical"
    assert components.kernel.mission_engine is components.mission_engine
    assert components.kernel.providers is components.provider_manager
    assert components.kernel.knowledge.pipeline is components.knowledge_pipeline
    assert (
        components.capability_execution_service.idempotency_store
        is components.idempotency_store
    )
    assert components.capability_router.registered_apps == (
        "atlas",
        "logos",
        "oem_studio",
    )
    assert components.capability_registry.validate() == []
    assert len(components.agent_orchestrator.agents) == 3
    assert not hasattr(components, "legacy_agent_orchestrator")


def test_direct_kernel_remains_explicit_compatibility_bootstrap(tmp_path):
    kernel = Kernel(pkb_path=str(tmp_path / "legacy"))

    assert kernel.bootstrap_mode == "compatibility"
    assert kernel.runtime_description["legacy_adapters"]
    assert kernel.status()["bootstrap_mode"] == "compatibility"


def test_canonical_kernel_rejects_missing_composition():
    with pytest.raises(ValueError, match="requires injected dependencies"):
        Kernel(bootstrap_mode="canonical")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    [
        "quero investir 5000",
        "preciso organizar meu orçamento",
        "quero criar uma poupança para reserva",
        "tenho uma dúvida financeira geral",
    ],
)
async def test_atlas_official_path_preserves_fin_output(tmp_path, text):
    factory = _factory(tmp_path)
    canonical = await factory.get_kernel().process(text)
    parsed = await factory.get_kernel().intent_engine.parse(text)
    legacy = await FinanceModule().execute(
        IntentInput(text=text, domain=Domain.FINANCE)
    )

    assert parsed.domain is Domain.FINANCE
    assert legacy["text"] in canonical.text
    assert canonical.confidence == legacy["confidence"]


@pytest.mark.asyncio
async def test_non_mission_kernel_turn_does_not_create_lifecycle(tmp_path):
    components = _factory(tmp_path).get_components()

    await components.kernel.process("quero investir 5000")

    assert await components.mission_store.list_active() == []


def test_all_user_interfaces_share_the_same_factory(tmp_path, monkeypatch):
    import intent_kernel.server.app as server_module

    factory = _factory(tmp_path)
    cli = create_cli_kernel(factory)
    desktop = create_app(factory)
    server_module.configure_factory(factory)

    assert cli is factory.get_kernel()
    assert desktop.kernel is cli
    assert server_module.get_kernel() is cli


def test_server_environment_configuration_belongs_to_builder(monkeypatch):
    from intent_kernel.providers.openai_provider import OpenAIProvider

    builder = KernelBuilder().with_environment(
        {"OPENAI_API_KEY": "test-only-key"}
    )
    components = builder.build()

    assert components.provider_manager.default == "openai"
    assert isinstance(
        components.provider_manager.get("openai"),
        OpenAIProvider,
    )


def test_monitor_observes_public_canonical_composition(tmp_path):
    components = _factory(tmp_path).get_components()
    monitor = IntentOSMonitor(
        components.kernel,
        components=components,
    )
    snapshot = monitor.get_snapshot()

    assert snapshot.composition["bootstrap_mode"] == "canonical"
    assert snapshot.composition["capability_router"] == "canonical"
    assert snapshot.composition["agent_orchestrator"] == "canonical"
    assert snapshot.capabilities["source"] == "canonical"
    assert snapshot.core_apps["source"] == "canonical"
    assert "FinanceModule" in snapshot.composition["legacy_adapters"]


def test_provider_manager_default_selection_is_public():
    manager = ProviderManager()
    first = object()
    second = object()
    manager.register("first", first)
    manager.register("second", second)

    manager.set_default("second")

    assert manager.default == "second"
    assert manager.get() is second
    with pytest.raises(KeyError):
        manager.set_default("missing")


def test_historical_registry_is_not_composed_as_an_authority(tmp_path):
    components = _factory(tmp_path).get_components()

    assert not isinstance(
        components.capability_registry,
        LegacyRegistry,
    )
    assert "capabilities.CapabilityRegistry" not in inspect.getsource(
        KernelBuilder
    )


def test_canonical_kernel_receives_dependencies_from_builder(tmp_path):
    components = _factory(tmp_path).get_components()

    assert components.kernel.constitution_engine is components.constitution_engine
    assert components.kernel.capability_executor is components.capability_router
    assert components.kernel.event_publisher is components.event_publisher
    assert components.kernel.knowledge_store is components.knowledge_store
