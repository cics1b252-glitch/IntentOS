"""Movement 13.1: exact binding identity preservation from selection to dispatch.

Guarantees SELECTED = REVALIDATED = AUTHORIZED = DISPATCHED for the canonical
execution path. A replacement that appears after selection (router mapping,
registry entry, provider manager binding, RRM truth, health) must never be
silently substituted; the exact selected executable object must run, or the
dispatch must fail closed.
"""

from __future__ import annotations

import pytest

from intent_kernel.application.composition import KernelBuilder
from intent_kernel.contracts import (
    Capability,
    CapabilityRequest,
    CapabilityResult,
    ConstitutionDecision,
    ConstitutionVerdict,
    Domain,
    ErrorCode,
    MissionContext,
    ProviderResponse,
)
from intent_kernel.orchestration.registry import ExecutorKind
from intent_kernel.rrm.models import ResourceStatus
from intent_kernel.rrm.projection import RuntimeResourceProjection

APP_ID = "replaceable"
CAPABILITY = "resource.identity"


class ReplaceableApp:
    app_id = APP_ID
    capabilities = (Capability(name=CAPABILITY, description="identity"),)

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.calls = 0
        self.healthy = True

    async def health(self) -> bool:
        return self.healthy

    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        self.calls += 1
        return CapabilityResult(
            capability=request.capability,
            success=True,
            output=f"executed-by-{self.tag}",
            metadata={"identity_tag": self.tag},
        )


class RecordingProvider:
    capabilities = {"text_completion"}

    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    async def health(self) -> bool:
        return True

    async def execute(self, _request) -> ProviderResponse:
        self.calls += 1
        return ProviderResponse(
            text="observed",
            provider=self.name,
            model="m13-1-test",
        )


def _register_core_app(components, app) -> None:
    components.capability_router.register(app)
    components.capability_registry.register_core_app(app)
    RuntimeResourceProjection(components.resource_manager).project_core_app(app)


async def _running_mission(components, domain: Domain = Domain.OTHER):
    mission = await components.mission_engine.create(
        "Movement 13.1 binding identity",
        context=MissionContext(
            domain=domain,
            session_id="m13-1",
            correlation_id="m13-1-correlation",
        ),
    )
    return await components.mission_engine.start(mission.id)


class MutatingConstitution:
    """Delegates governance but mutates runtime state between selection and dispatch."""

    def __init__(self, engine, mutator) -> None:
        self._engine = engine
        self._mutator = mutator

    async def evaluate(self, action, data=None, context=None):
        self._mutator()
        return await self._engine.evaluate(action, data, context)


class DenyConstitution:
    async def evaluate(self, action, data=None, context=None):
        return ConstitutionVerdict(
            decision=ConstitutionDecision.DENY,
            reason="m13-1 authorization denial",
            metadata={"audit_id": "m13-1-deny"},
        )


# ---------------------------------------------------------------------------
# RA-13-01: exact selected binding must be dispatched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ra_13_01_router_replacement_never_executes(tmp_path):
    """A selected and authorized; B replaces the router mapping before dispatch."""
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app_a = ReplaceableApp("A")
    app_b = ReplaceableApp("B")
    _register_core_app(components, app_a)
    mission = await _running_mission(components)

    resource_decision = await components.capability_execution_service.resource_authority.resolve(
        CAPABILITY
    )
    registration = resource_decision.registration
    assert registration is not None
    assert registration.executor is app_a

    components.capability_router.register(app_b)

    outcome = await components.capability_execution_service.execute(
        mission.id,
        CAPABILITY,
        payload={"text": "resolve identity"},
    )

    assert app_b.calls == 0
    assert outcome.result.success is True
    assert outcome.result.output == "executed-by-A"
    assert outcome.result.metadata["binding_identity"] == registration.binding_identity
    assert outcome.result.metadata["dispatched_binding"] == registration.binding_identity


@pytest.mark.asyncio
async def test_ra_13_01_selected_is_revalidated_is_authorized_is_dispatched(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app_a = ReplaceableApp("A")
    _register_core_app(components, app_a)
    mission = await _running_mission(components)

    resource_decision = await components.capability_execution_service.resource_authority.resolve(
        CAPABILITY
    )
    registration = resource_decision.registration
    revalidation = await components.capability_execution_service.resource_authority.revalidate(
        resource_decision
    )

    outcome = await components.capability_execution_service.execute(
        mission.id,
        CAPABILITY,
        payload={"text": "resolve identity"},
    )

    assert bool(revalidation) is True
    assert revalidation.binding_identity == registration.binding_identity
    assert outcome.result.metadata["resource_resolution"]["binding_identity"] == (
        registration.binding_identity
    )
    assert outcome.result.metadata["resource_revalidation"]["binding_identity"] == (
        registration.binding_identity
    )
    assert outcome.result.metadata["dispatched_binding"] == registration.binding_identity
    assert outcome.result.metadata["binding_identity"] == registration.binding_identity


# ---------------------------------------------------------------------------
# Identity matrix: SELECTED = REVALIDATED = AUTHORIZED = DISPATCHED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_selected_binding_unchanged_dispatches_exact_object(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app_a = ReplaceableApp("A")
    _register_core_app(components, app_a)
    mission = await _running_mission(components)

    outcome = await components.capability_execution_service.execute(
        mission.id,
        CAPABILITY,
        payload={"text": "identity"},
    )

    assert app_a.calls == 1
    assert outcome.result.success is True
    assert outcome.result.metadata["dispatched_binding"] == (
        f"{ExecutorKind.CORE_APP.value}:{APP_ID}@{id(app_a):#x}"
    )


@pytest.mark.asyncio
async def test_router_replaced_after_selection_replacement_never_executes(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app_a = ReplaceableApp("A")
    app_b = ReplaceableApp("B")
    _register_core_app(components, app_a)
    mission = await _running_mission(components)

    components.capability_router.register(app_b)
    assert components.capability_router.select(mission, CAPABILITY) is app_b

    outcome = await components.capability_execution_service.execute(
        mission.id,
        CAPABILITY,
        payload={"text": "identity"},
    )

    assert app_a.calls == 1
    assert app_b.calls == 0
    assert outcome.result.success is True


@pytest.mark.asyncio
async def test_registry_entry_removed_after_selection_fails_closed(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app_a = ReplaceableApp("A")
    _register_core_app(components, app_a)
    mission = await _running_mission(components)

    def remove_entry() -> None:
        components.capability_registry.unregister(
            CAPABILITY,
            executor_kind=ExecutorKind.CORE_APP,
            executor_id=APP_ID,
        )

    components.capability_execution_service.constitution = MutatingConstitution(
        components.constitution_engine, remove_entry
    )
    outcome = await components.capability_execution_service.execute(
        mission.id,
        CAPABILITY,
        payload={"text": "identity"},
    )

    assert outcome.result.error_code is ErrorCode.CAPABILITY_UNAVAILABLE
    assert app_a.calls == 0
    assert outcome.result.metadata["resource_revalidation"]["binding_registered"] is False


@pytest.mark.asyncio
async def test_registry_entry_replaced_with_different_object_fails_closed(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app_a = ReplaceableApp("A")
    app_b = ReplaceableApp("B")
    _register_core_app(components, app_a)
    mission = await _running_mission(components)

    def replace_entry() -> None:
        components.capability_registry.unregister(
            CAPABILITY,
            executor_kind=ExecutorKind.CORE_APP,
            executor_id=APP_ID,
        )
        components.capability_registry.register_core_app(app_b)

    components.capability_execution_service.constitution = MutatingConstitution(
        components.constitution_engine, replace_entry
    )
    outcome = await components.capability_execution_service.execute(
        mission.id,
        CAPABILITY,
        payload={"text": "identity"},
    )

    assert outcome.result.error_code is ErrorCode.CAPABILITY_UNAVAILABLE
    assert app_a.calls == 0
    assert app_b.calls == 0
    assert outcome.result.metadata["resource_revalidation"]["binding_registered"] is False


@pytest.mark.asyncio
async def test_same_app_id_capability_different_object_identity_detected(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app_a = ReplaceableApp("A")
    app_b = ReplaceableApp("B")
    _register_core_app(components, app_a)
    mission = await _running_mission(components)

    resource_decision = await components.capability_execution_service.resource_authority.resolve(
        CAPABILITY
    )
    assert resource_decision.registration.executor is app_a
    assert resource_decision.registration.executor is not app_b

    def replace_entry() -> None:
        components.capability_registry.unregister(
            CAPABILITY,
            executor_kind=ExecutorKind.CORE_APP,
            executor_id=APP_ID,
        )
        components.capability_registry.register_core_app(app_b)

    components.capability_execution_service.constitution = MutatingConstitution(
        components.constitution_engine, replace_entry
    )
    outcome = await components.capability_execution_service.execute(
        mission.id,
        CAPABILITY,
        payload={"text": "identity"},
    )

    assert outcome.result.error_code is ErrorCode.CAPABILITY_UNAVAILABLE
    assert app_a.calls == 0
    assert app_b.calls == 0


@pytest.mark.asyncio
async def test_same_executor_id_different_object_no_substitution(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app_a = ReplaceableApp("A")
    app_b = ReplaceableApp("B")
    _register_core_app(components, app_a)
    mission = await _running_mission(components)

    def replace_entry() -> None:
        components.capability_registry.unregister(
            CAPABILITY,
            executor_kind=ExecutorKind.CORE_APP,
            executor_id=APP_ID,
        )
        components.capability_registry.register_core_app(app_b)

    components.capability_execution_service.constitution = MutatingConstitution(
        components.constitution_engine, replace_entry
    )
    outcome = await components.capability_execution_service.execute(
        mission.id,
        CAPABILITY,
        payload={"text": "identity"},
    )

    assert outcome.result.error_code is ErrorCode.CAPABILITY_UNAVAILABLE
    assert app_a.calls == 0
    assert app_b.calls == 0


@pytest.mark.asyncio
async def test_health_change_between_selection_and_dispatch_fails_closed(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app_a = ReplaceableApp("A")
    _register_core_app(components, app_a)
    mission = await _running_mission(components)

    def break_health() -> None:
        app_a.healthy = False

    components.capability_execution_service.constitution = MutatingConstitution(
        components.constitution_engine, break_health
    )
    outcome = await components.capability_execution_service.execute(
        mission.id,
        CAPABILITY,
        payload={"text": "identity"},
    )

    assert outcome.result.error_code is ErrorCode.CAPABILITY_UNAVAILABLE
    assert app_a.calls == 0
    assert outcome.result.metadata["resource_revalidation"]["binding_healthy"] is False


@pytest.mark.asyncio
async def test_rrm_unavailable_between_selection_and_dispatch_fails_closed(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app_a = ReplaceableApp("A")
    _register_core_app(components, app_a)
    mission = await _running_mission(components)

    def break_rrm() -> None:
        resource = components.resource_manager.get_capability(CAPABILITY)
        resource.status = ResourceStatus.UNAVAILABLE

    components.capability_execution_service.constitution = MutatingConstitution(
        components.constitution_engine, break_rrm
    )
    outcome = await components.capability_execution_service.execute(
        mission.id,
        CAPABILITY,
        payload={"text": "identity"},
    )

    assert outcome.result.error_code is ErrorCode.CAPABILITY_UNAVAILABLE
    assert app_a.calls == 0
    assert outcome.result.metadata["resource_revalidation"]["rrm_eligible"] is False


@pytest.mark.asyncio
async def test_authorization_denied_never_dispatches(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app_a = ReplaceableApp("A")
    _register_core_app(components, app_a)
    mission = await _running_mission(components)

    components.capability_execution_service.constitution = DenyConstitution()
    outcome = await components.capability_execution_service.execute(
        mission.id,
        CAPABILITY,
        payload={"text": "identity"},
    )

    assert outcome.result.error_code is ErrorCode.POLICY_DENIED
    assert app_a.calls == 0


@pytest.mark.asyncio
async def test_compatibility_path_is_not_canonical_dispatch(tmp_path):
    """Router name-based lookup still resolves B, but canonical dispatch uses A."""
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app_a = ReplaceableApp("A")
    app_b = ReplaceableApp("B")
    _register_core_app(components, app_a)
    mission = await _running_mission(components)

    components.capability_router.register(app_b)
    assert components.capability_router.select(mission, CAPABILITY) is app_b

    outcome = await components.capability_execution_service.execute(
        mission.id,
        CAPABILITY,
        payload={"text": "identity"},
    )

    assert app_a.calls == 1
    assert app_b.calls == 0
    assert outcome.result.success is True
    assert outcome.result.metadata["dispatched_binding"] == (
        f"{ExecutorKind.CORE_APP.value}:{APP_ID}@{id(app_a):#x}"
    )


# ---------------------------------------------------------------------------
# Provider identity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provider_dispatch_uses_exact_selected_binding(tmp_path):
    alpha = RecordingProvider("alpha")
    components = (
        KernelBuilder()
        .with_provider("alpha", alpha)
        .with_pkb_path(tmp_path / "pkb")
        .build()
    )
    mission = await _running_mission(components)

    outcome = await components.capability_execution_service.execute(
        mission.id,
        "provider.text_completion",
        payload={"text": "provider identity"},
        preferred_kind=ExecutorKind.PROVIDER,
    )

    assert outcome.result.success is True
    assert alpha.calls == 1
    assert components.provider_manager.last_used == "alpha"
    assert outcome.result.metadata["provider"] == "alpha"
    assert outcome.result.metadata["binding_identity"].startswith("provider:alpha@")


@pytest.mark.asyncio
async def test_provider_replacement_after_selection_fails_closed(tmp_path):
    alpha = RecordingProvider("alpha")
    beta = RecordingProvider("alpha")
    components = (
        KernelBuilder()
        .with_provider("alpha", alpha)
        .with_pkb_path(tmp_path / "pkb")
        .build()
    )
    mission = await _running_mission(components)

    resource_decision = await components.capability_execution_service.resource_authority.resolve(
        "provider.text_completion",
        preferred_kind=ExecutorKind.PROVIDER,
    )
    assert resource_decision.registration.executor is alpha

    components.provider_manager.register("alpha", beta)

    outcome = await components.capability_execution_service.execute(
        mission.id,
        "provider.text_completion",
        payload={"text": "provider identity"},
        preferred_kind=ExecutorKind.PROVIDER,
    )

    assert outcome.result.error_code is ErrorCode.CAPABILITY_UNAVAILABLE
    assert alpha.calls == 0
    assert beta.calls == 0
    assert outcome.result.metadata["provider_invocation_attempted"] is False


# ---------------------------------------------------------------------------
# TOCTOU / security substitution matrix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_toctou_router_swap_never_invokes_replacement(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app_a = ReplaceableApp("A")
    app_b = ReplaceableApp("B")
    _register_core_app(components, app_a)
    mission = await _running_mission(components)

    components.capability_router.register(app_b)

    outcome = await components.capability_execution_service.execute(
        mission.id,
        CAPABILITY,
        payload={"text": "identity"},
    )

    assert app_b.calls == 0
    assert app_a.calls == 1
    assert outcome.result.success is True
    assert outcome.result.output == "executed-by-A"


@pytest.mark.asyncio
async def test_toctou_registry_entry_swap_fails_closed(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app_a = ReplaceableApp("A")
    app_b = ReplaceableApp("B")
    _register_core_app(components, app_a)
    mission = await _running_mission(components)

    def swap_registry() -> None:
        components.capability_registry.unregister(
            CAPABILITY,
            executor_kind=ExecutorKind.CORE_APP,
            executor_id=APP_ID,
        )
        components.capability_registry.register_core_app(app_b)

    components.capability_execution_service.constitution = MutatingConstitution(
        components.constitution_engine, swap_registry
    )
    outcome = await components.capability_execution_service.execute(
        mission.id,
        CAPABILITY,
        payload={"text": "identity"},
    )

    assert outcome.result.error_code is ErrorCode.CAPABILITY_UNAVAILABLE
    assert app_a.calls == 0
    assert app_b.calls == 0


@pytest.mark.asyncio
async def test_same_id_provider_binding_replacement_fails_closed(tmp_path):
    alpha = RecordingProvider("alpha")
    beta = RecordingProvider("alpha")
    components = (
        KernelBuilder()
        .with_provider("alpha", alpha)
        .with_pkb_path(tmp_path / "pkb")
        .build()
    )
    mission = await _running_mission(components)

    components.provider_manager.register("alpha", beta)

    outcome = await components.capability_execution_service.execute(
        mission.id,
        "provider.text_completion",
        payload={"text": "provider identity"},
        preferred_kind=ExecutorKind.PROVIDER,
    )

    assert outcome.result.error_code is ErrorCode.CAPABILITY_UNAVAILABLE
    assert alpha.calls == 0
    assert beta.calls == 0


@pytest.mark.asyncio
async def test_authorization_identity_binds_to_selected_object(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app_a = ReplaceableApp("A")
    _register_core_app(components, app_a)
    mission = await _running_mission(components)

    seen_identities = []

    class RecordingConstitution:
        async def evaluate(self, action, data=None, context=None):
            seen_identities.append(data.get("binding_identity"))
            return await components.constitution_engine.evaluate(action, data, context)

    components.capability_execution_service.constitution = RecordingConstitution()
    outcome = await components.capability_execution_service.execute(
        mission.id,
        CAPABILITY,
        payload={"text": "identity"},
    )

    assert outcome.result.success is True
    assert seen_identities == [f"{ExecutorKind.CORE_APP.value}:{APP_ID}@{id(app_a):#x}"]
