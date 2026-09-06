"""Movement 11.4 invariants: RRM truth dominates invocation bindings."""

import pytest

from intent_kernel.application.composition import KernelBuilder
from intent_kernel.contracts import (
    Capability,
    CapabilityRequest,
    CapabilityResult,
    ErrorCode,
    MissionContext,
)
from intent_kernel.orchestration.registry import ExecutorKind
from intent_kernel.rrm.models import ResourceStatus


class RegistryOnlyApp:
    """M11.4 (MODEL_M11_A) — a core app whose capability is registered in the
    router/registry but whose RRM resource is deliberately absent (NOT projected,
    NOT governed). Used to prove: registry resolution alone is never execution
    authority."""

    app_id = "registry.only"
    capabilities = (Capability(name="registry.only.ghost"),)

    def __init__(self) -> None:
        self.calls = 0

    async def health(self) -> bool:
        return True

    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        self.calls += 1
        return CapabilityResult(
            capability=request.capability,
            success=True,
            output="MUST NEVER OBSERVE EXECUTION",
        )


@pytest.mark.asyncio
async def test_registered_binding_without_rrm_resource_is_not_executable(tmp_path):
    # M31.3B-1B-M11: migrated from legacy `unregister_capability("finance.intent")`
    # (governed resources are now protected from legacy unregister) to the
    # canonical MODEL_M11_A state: the capability exists and resolves in the
    # registry, but no canonical RRM resource is projected, so RRM canonical
    # eligibility rejects the binding and the executor is never invoked.
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    authority = components.capability_execution_service.resource_authority
    app = RegistryOnlyApp()
    components.capability_router.register(app)
    components.capability_registry.register_core_app(app)
    # Deliberately NOT projected into RRM and NOT governed.

    decision = await authority.resolve("registry.only.ghost")

    assert decision.available is False
    assert decision.registered is True
    assert decision.rrm_eligible is False
    assert decision.reason == "rrm_rejected_bindings"

    mission = await components.mission_engine.create(
        "registered binding without rrm resource",
        context=MissionContext(session_id="m11", correlation_id="m11-resource-authority"),
    )
    mission = await components.mission_engine.start(mission.id)
    outcome = await components.capability_execution_service.execute(
        mission.id, "registry.only.ghost"
    )

    assert outcome.result.success is False
    assert app.calls == 0


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
