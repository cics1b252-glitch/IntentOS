"""Movement 11.4 invariants: RRM truth dominates invocation bindings."""

import pytest

from intent_kernel.application.composition import KernelBuilder
from intent_kernel.contracts import ErrorCode, MissionContext
from intent_kernel.orchestration.registry import ExecutorKind
from intent_kernel.rrm.models import ResourceStatus


@pytest.mark.asyncio
async def test_registered_binding_without_rrm_resource_is_not_executable(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    authority = components.capability_execution_service.resource_authority
    components.resource_manager.unregister_capability("finance.intent")

    decision = await authority.resolve("finance.intent")

    assert decision.available is False
    assert decision.registration is None
    assert decision.reason == "rrm_rejected_bindings"


@pytest.mark.asyncio
async def test_rrm_unavailable_overrides_healthy_legacy_binding(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    resource = components.resource_manager.get_capability("finance.intent")
    resource.status = ResourceStatus.UNAVAILABLE

    decision = await components.capability_execution_service.resource_authority.resolve(
        "finance.intent"
    )

    assert decision.available is False
    assert decision.authority == "RRM"


@pytest.mark.asyncio
async def test_provider_configuration_does_not_override_rrm_unavailable(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    provider = components.resource_manager.get_provider("mock")
    assert provider is not None
    assert components.capability_registry.discover(
        "provider.text_completion", executor_kind=ExecutorKind.PROVIDER
    )

    decision = await components.capability_execution_service.resource_authority.resolve(
        "provider.text_completion", preferred_kind=ExecutorKind.PROVIDER
    )

    assert decision.available is False
    assert decision.reason == "rrm_rejected_bindings"


@pytest.mark.asyncio
async def test_binding_disappearance_before_execution_fails_closed(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    mission = await components.mission_engine.create(
        "resource revalidation", context=MissionContext(session_id="s", correlation_id="c")
    )
    await components.mission_engine.start(mission.id)
    resource = components.resource_manager.get_capability("finance.intent")

    class RevokingConstitution:
        async def evaluate(self, action, data=None, context=None):
            resource.status = ResourceStatus.UNAVAILABLE
            return await components.constitution_engine.evaluate(action, data, context)

    service = components.capability_execution_service
    service.constitution = RevokingConstitution()
    outcome = await service.execute(mission.id, "finance.intent")

    assert outcome.result.success is False
    assert outcome.result.error_code is ErrorCode.CAPABILITY_UNAVAILABLE


@pytest.mark.asyncio
async def test_multiple_bindings_use_deterministic_rrm_eligible_selection(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    authority = components.capability_execution_service.resource_authority

    first = await authority.resolve("finance.intent")
    second = await authority.resolve("finance.intent")

    assert first.available is True
    assert first.registration == second.registration
    assert first.registration.executor_id == "atlas"
