"""Sprint 2 characterization of the canonical Kernel migration."""

from __future__ import annotations

import pytest

from intent_kernel.__main__ import create_cli_kernel
from intent_kernel.application import (
    ApplicationFactory,
    KernelBuilder,
    MissionEngine,
    MissionTransitionError,
)
from intent_kernel.contracts import (
    CapabilityExecutor,
    ConstitutionEngine,
    EventPublisher,
    KnowledgeStore,
    MissionStatus,
    Provider,
)
from intent_kernel.providers import MockProvider
from intent_kernel.runtime import ActionContract, MissionRuntime, RuntimeNode
from intent_os_desktop import create_app


@pytest.mark.asyncio
async def test_mission_engine_persists_basic_lifecycle():
    components = KernelBuilder().build()
    engine = components.mission_engine

    created = await engine.create(
        "Preserve canonical behavior",
        success_criteria=["Baseline remains unchanged"],
    )
    running = await engine.start(created.id)
    paused = await engine.pause(
        created.id,
        status=MissionStatus.WAITING_FOR_INFORMATION,
        blocker={"reason": "missing context"},
    )

    # A new engine over the same Port resumes persisted state.
    resumed_by_new_engine = await MissionEngine(
        components.mission_store
    ).resume(created.id)
    runtime = MissionRuntime(mission_engine=engine)
    instance = runtime.create_instance(
        str(created.id),
        "verified-lifecycle",
        [RuntimeNode(action_contract=ActionContract(
            inputs_reference={"message": "done"},
            expected_output="done",
        ))],
    )
    result = await runtime.run_mission(instance.runtime_id, final_output_candidate="done")
    stored = await engine.get(created.id)

    assert created.status is MissionStatus.CREATED
    assert running.status is MissionStatus.RUNNING
    assert paused.status is MissionStatus.WAITING_FOR_INFORMATION
    assert resumed_by_new_engine.status is MissionStatus.RUNNING
    assert result.status.value == "COMPLETED"
    assert result.completion_authority == "MissionCompletionGate"
    assert result.lifecycle_status == MissionStatus.COMPLETED.value
    assert stored is not None
    assert stored.status is MissionStatus.COMPLETED
    assert stored.artifacts == []


@pytest.mark.asyncio
async def test_mission_engine_rejects_invalid_transition():
    engine = KernelBuilder().build().mission_engine
    mission = await engine.create("Do not skip lifecycle")

    with pytest.raises(MissionTransitionError):
        await engine.complete(mission.id)


def test_composed_kernel_exposes_canonical_ports(tmp_path):
    components = (
        KernelBuilder()
        .with_pkb_path(tmp_path / "pkb")
        .build()
    )
    kernel = components.kernel

    assert isinstance(kernel.constitution_engine, ConstitutionEngine)
    assert isinstance(kernel.knowledge_store, KnowledgeStore)
    assert isinstance(kernel.event_publisher, EventPublisher)
    assert isinstance(kernel.capability_executor, CapabilityExecutor)
    assert isinstance(components.provider, Provider)
    assert kernel.mission_engine is components.mission_engine


@pytest.mark.asyncio
async def test_provider_manager_consumes_canonical_provider():
    provider = MockProvider()

    assert isinstance(provider, Provider)
    assert await provider.health() is True


def test_interfaces_can_share_one_application_factory(tmp_path):
    factory = ApplicationFactory(
        KernelBuilder().with_pkb_path(tmp_path / "pkb")
    )

    cli_kernel = create_cli_kernel(factory)
    desktop = create_app(factory)

    assert cli_kernel is factory.get_kernel()
    assert desktop.kernel is cli_kernel


def test_fastapi_can_obtain_kernel_from_application_factory(
    monkeypatch,
    tmp_path,
):
    import intent_kernel.server.app as server_module

    factory = ApplicationFactory(
        KernelBuilder().with_pkb_path(tmp_path / "pkb")
    )
    monkeypatch.setattr(server_module, "_kernel", None)
    monkeypatch.setattr(server_module, "_factory", factory)

    assert server_module.get_kernel() is factory.get_kernel()
