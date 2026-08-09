"""Sprint 1 tests for canonical contracts and legacy compatibility.

These tests characterize the translation boundary. They do not authorize
changing the behavior of the current Kernel or its public bootstraps.
"""

from __future__ import annotations

import pytest

from intent_kernel.adapters import (
    InMemoryMissionStoreAdapter,
    LegacyConstitutionEngineAdapter,
    LegacyEventPublisherAdapter,
    LegacyKnowledgeStoreAdapter,
    LegacyProviderAdapter,
)
from intent_kernel.application import ApplicationFactory, KernelBuilder
from intent_kernel.bus import EventBus
from intent_kernel.constitution import create_default_constitution
from intent_kernel.contracts import (
    ConstitutionDecision,
    ConstitutionEngine,
    Domain,
    EventPublisher,
    IntentMode,
    KnowledgeEvent,
    KnowledgeLifecycle,
    KnowledgeStore,
    Mission,
    MissionContext,
    MissionStatus,
    MissionStore,
    Provider,
    ProviderMessage,
    ProviderRequest,
)
from intent_kernel.kernel import Kernel
from intent_kernel.pkb import JsonFileStore
from intent_kernel.providers import MockProvider


def test_canonical_mission_has_stable_defaults():
    mission = Mission(
        objective="Preserve current behavior",
        context=MissionContext(
            domain=Domain.ENGINEERING,
            mode=IntentMode.ARCHITECT,
        ),
    )

    assert str(mission.id)
    assert mission.status is MissionStatus.CREATED
    assert mission.schema_version == "2.0"
    assert mission.objective == "Preserve current behavior"


def test_canonical_knowledge_event_is_versioned():
    event = KnowledgeEvent(
        event_type="decision",
        title="Canonical event",
        domain=Domain.ENGINEERING,
        lifecycle=KnowledgeLifecycle.CANDIDATE,
    )

    assert event.schema_version == "2.0"
    assert event.version == 1
    assert event.domain is Domain.ENGINEERING


@pytest.mark.asyncio
async def test_legacy_provider_adapter_preserves_mock_output():
    legacy = MockProvider()
    adapter = LegacyProviderAdapter(legacy)
    request = ProviderRequest(
        messages=[ProviderMessage(role="user", content="Quero investir 5000")],
    )

    canonical = await adapter.execute(request)
    from intent_kernel.types import Message

    original = await legacy.complete(
        [Message(role="user", content="Quero investir 5000")]
    )
    assert isinstance(adapter, Provider)
    assert canonical.text == original.text
    assert canonical.model == original.model
    assert canonical.usage == original.usage
    assert canonical.finish_reason == original.finish_reason
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_legacy_constitution_adapter_maps_current_verdict():
    adapter = LegacyConstitutionEngineAdapter(create_default_constitution())

    verdict = await adapter.evaluate("process", "Olá")

    assert isinstance(adapter, ConstitutionEngine)
    assert verdict.decision is ConstitutionDecision.ALLOW
    assert verdict.allowed is True
    assert verdict.constitution_version


@pytest.mark.asyncio
async def test_legacy_knowledge_store_round_trip(tmp_path):
    adapter = LegacyKnowledgeStoreAdapter(JsonFileStore(str(tmp_path / "pkb")))
    event = KnowledgeEvent(
        event_type="fact",
        title="Compatibility",
        content={"value": "preserved"},
        domain=Domain.OTHER,
        lifecycle=KnowledgeLifecycle.TRANSIENT,
    )

    event_id = await adapter.append(event)
    restored = await adapter.get(event_id)

    assert isinstance(adapter, KnowledgeStore)
    assert restored is not None
    assert restored.title == event.title
    assert restored.content == event.content
    assert await adapter.count() == 1
    assert await adapter.health() is True


@pytest.mark.asyncio
async def test_event_publisher_adapter_preserves_payload():
    bus = EventBus()
    adapter = LegacyEventPublisherAdapter(bus)

    await adapter.publish("sprint.test", {"ok": True})

    assert isinstance(adapter, EventPublisher)
    assert bus.get_history("sprint.test") == [
        {"type": "sprint.test", "data": {"ok": True}}
    ]


@pytest.mark.asyncio
async def test_mission_store_is_copy_isolated():
    store = InMemoryMissionStoreAdapter()
    mission = Mission(objective="Define canonical contracts")

    await store.save(mission)
    restored = await store.get(mission.id)
    assert isinstance(store, MissionStore)
    assert restored == mission
    assert restored is not mission
    assert await store.list_active() == [mission]

    restored.status = MissionStatus.COMPLETED
    unchanged = await store.get(mission.id)
    assert unchanged is not None
    assert unchanged.status is MissionStatus.CREATED


def test_composition_root_builds_current_kernel_without_bootstrap_changes(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()

    assert isinstance(components.kernel, Kernel)
    assert components.kernel.status()["providers"] == ["mock"]
    assert components.kernel.status()["modules"] == ["core", "fin"]
    assert components.provider.name == "mock"
    assert components.knowledge_store._store is components.kernel.store


def test_application_factory_returns_one_shared_kernel(tmp_path):
    factory = ApplicationFactory(
        KernelBuilder().with_pkb_path(tmp_path / "pkb")
    )

    assert factory.get_kernel() is factory.get_kernel()
    assert factory.get_components() is factory.get_components()


@pytest.mark.asyncio
async def test_factory_kernel_matches_direct_kernel_observable_output(tmp_path):
    direct = Kernel(pkb_path=str(tmp_path / "direct"))
    composed = (
        KernelBuilder()
        .with_pkb_path(tmp_path / "composed")
        .build()
        .kernel
    )

    direct_result = await direct.process("Quero investir 5000")
    composed_result = await composed.process("Quero investir 5000")

    assert composed_result.text == direct_result.text
    assert composed_result.mode == direct_result.mode
    assert composed_result.domain == direct_result.domain
    assert composed_result.confidence == direct_result.confidence
    assert composed_result.epistemic_status == direct_result.epistemic_status
    assert composed_result.next_steps == direct_result.next_steps
