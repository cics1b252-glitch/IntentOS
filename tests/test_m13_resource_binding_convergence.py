"""Movement 13: RRM-governed resource, binding, and registry convergence."""

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
from intent_kernel.providers.authority import CanonicalProviderAuthority
from intent_kernel.rrm.models import (
    AvailabilitySource,
    CapabilityResource,
    ProviderResource,
    ResourceOrigin,
    ResourceStatus,
)
from intent_kernel.rrm.projection import RuntimeResourceProjection
from intent_kernel.rrm.adapter import RRMToCORAdapter
from product_bridge import ProductBridge


async def _running_mission(components, domain: Domain = Domain.OTHER):
    mission = await components.mission_engine.create(
        "Movement 13 resource audit",
        context=MissionContext(
            domain=domain,
            session_id="m13",
            correlation_id="m13-correlation",
        ),
    )
    return await components.mission_engine.start(mission.id)


class SwitchableApp:
    app_id = "switchable"
    capabilities = (Capability(name="resource.switchable"),)

    def __init__(self) -> None:
        self.healthy = True
        self.calls = 0

    async def health(self) -> bool:
        return self.healthy

    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        self.calls += 1
        return CapabilityResult(
            capability=request.capability,
            success=True,
            output="executed",
        )


class RecordingProvider:
    capabilities = {"text_completion"}

    def __init__(self, name: str, *, error: Exception | None = None) -> None:
        self.name = name
        self.error = error
        self.calls = 0

    async def health(self) -> bool:
        return True

    async def execute(self, _request):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return ProviderResponse(
            text="observed provider result",
            provider=self.name,
            model="m13-test",
        )


def _register_switchable(components, app: SwitchableApp) -> None:
    components.capability_router.register(app)
    components.capability_registry.register_core_app(app)
    RuntimeResourceProjection(components.resource_manager).project_core_app(app)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [ResourceStatus.UNAVAILABLE, ResourceStatus.DEGRADED])
async def test_registered_healthy_binding_cannot_override_rrm(status, tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    resource = components.resource_manager.get_capability("finance.intent")
    resource.status = status

    decision = await components.capability_execution_service.resource_authority.resolve(
        "finance.intent"
    )

    assert decision.available is False
    assert decision.registration is None
    assert decision.registered is True
    assert decision.rrm_eligible is False
    assert decision.reason == "rrm_rejected_bindings"


@pytest.mark.asyncio
async def test_registry_only_and_rrm_only_resources_are_not_executable(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    authority = components.capability_execution_service.resource_authority

    components.resource_manager.unregister_capability("finance.intent")
    registry_only = await authority.resolve("finance.intent")

    components.resource_manager.register_capability(CapabilityResource(
        capability_id="rrm.only",
        name="rrm.only",
        resource_origin=ResourceOrigin.MIGRATION,
        availability_source=AvailabilitySource.RUNTIME_DISCOVERY,
        metadata={"executor_kind": "core_app", "executor_id": "missing"},
    ))
    rrm_only = await authority.resolve("rrm.only")

    assert registry_only.available is False
    assert registry_only.registered is True
    assert registry_only.rrm_eligible is False
    assert rrm_only.available is False
    assert rrm_only.registered is False
    assert rrm_only.reason == "binding_missing"


@pytest.mark.asyncio
async def test_binding_health_is_revalidated_immediately_before_dispatch(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app = SwitchableApp()
    _register_switchable(components, app)
    mission = await _running_mission(components)

    class RevokingConstitution:
        async def evaluate(self, action, data=None, context=None):
            app.healthy = False
            return await components.constitution_engine.evaluate(action, data, context)

    components.capability_execution_service.constitution = RevokingConstitution()
    outcome = await components.capability_execution_service.execute(
        mission.id, "resource.switchable"
    )

    assert outcome.result.error_code is ErrorCode.CAPABILITY_UNAVAILABLE
    assert app.calls == 0
    assert outcome.result.metadata["resource_revalidation"]["binding_healthy"] is False


@pytest.mark.asyncio
async def test_stale_registry_binding_is_rejected_before_dispatch(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app = SwitchableApp()
    _register_switchable(components, app)
    mission = await _running_mission(components)

    class RemovingConstitution:
        async def evaluate(self, action, data=None, context=None):
            components.capability_registry.unregister(
                "resource.switchable",
                executor_kind=ExecutorKind.CORE_APP,
                executor_id=app.app_id,
            )
            return await components.constitution_engine.evaluate(action, data, context)

    components.capability_execution_service.constitution = RemovingConstitution()
    outcome = await components.capability_execution_service.execute(
        mission.id, "resource.switchable"
    )

    assert outcome.result.error_code is ErrorCode.CAPABILITY_UNAVAILABLE
    assert app.calls == 0
    assert outcome.result.metadata["resource_revalidation"]["binding_registered"] is False


@pytest.mark.asyncio
async def test_canonical_provider_execution_uses_observed_invocation_boundary(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    components.resource_manager.register_provider(ProviderResource(
        provider_id="mock",
        name="mock",
        is_configured=True,
        has_active_account=True,
        resource_origin=ResourceOrigin.PROVIDER_DISCOVERY,
        availability_source=AvailabilitySource.RUNTIME_DISCOVERY,
        metadata={"capabilities": ["text_completion"]},
    ))
    mission = await _running_mission(components)

    outcome = await components.capability_execution_service.execute(
        mission.id,
        "provider.text_completion",
        payload={"text": "provider boundary"},
        preferred_kind=ExecutorKind.PROVIDER,
    )

    assert outcome.result.success is True
    assert components.provider_manager.last_attempted == "mock"
    assert components.provider_manager.last_used == "mock"
    assert outcome.result.metadata["provider_invocation_attempted"] is True


@pytest.mark.asyncio
async def test_provider_throw_is_observed_only_after_actual_attempt(tmp_path):
    provider = RecordingProvider("throwing", error=RuntimeError("provider failed"))
    components = (
        KernelBuilder()
        .with_provider("throwing", provider, default=True)
        .with_pkb_path(tmp_path / "pkb")
        .build()
    )
    mission = await _running_mission(components)

    with pytest.raises(RuntimeError, match="provider failed"):
        await components.capability_execution_service.execute(
            mission.id,
            "provider.text_completion",
            payload={"text": "actual attempt"},
            preferred_kind=ExecutorKind.PROVIDER,
        )

    assert provider.calls == 1
    assert components.provider_manager.last_attempted == "throwing"
    assert components.provider_manager.last_used is None


@pytest.mark.asyncio
async def test_provider_backed_core_app_cannot_use_ineligible_default(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    mock = components.provider_manager.get("mock")
    calls = 0
    original = mock.execute

    async def counted(request):
        nonlocal calls
        calls += 1
        return await original(request)

    mock.execute = counted
    mission = await _running_mission(components, Domain.RESEARCH)
    outcome = await components.capability_execution_service.execute(
        mission.id,
        "knowledge.intent",
        payload={"text": "research without eligible provider"},
        preferred_kind=ExecutorKind.CORE_APP,
    )

    assert outcome.result.success is False
    assert outcome.result.error_code is ErrorCode.PROVIDER_UNAVAILABLE
    assert calls == 0
    assert components.provider_manager.last_attempted is None
    assert components.provider_manager.last_used is None


@pytest.mark.asyncio
async def test_authorization_denial_after_resolution_never_dispatches(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    app = SwitchableApp()
    _register_switchable(components, app)
    mission = await _running_mission(components)

    class DenyConstitution:
        async def evaluate(self, action, data=None, context=None):
            return ConstitutionVerdict(
                decision=ConstitutionDecision.DENY,
                reason="m13 authorization denial",
                metadata={"audit_id": "m13-deny"},
            )

    components.capability_execution_service.constitution = DenyConstitution()
    outcome = await components.capability_execution_service.execute(
        mission.id, "resource.switchable"
    )

    assert outcome.result.error_code is ErrorCode.POLICY_DENIED
    assert app.calls == 0


@pytest.mark.asyncio
async def test_multiple_provider_candidates_are_deterministic_and_not_invoked(tmp_path):
    alpha = RecordingProvider("alpha")
    beta = RecordingProvider("beta")
    components = (
        KernelBuilder()
        .with_provider("alpha", alpha)
        .with_provider("beta", beta)
        .with_pkb_path(tmp_path / "pkb")
        .build()
    )
    authority: CanonicalProviderAuthority = components.provider_authority

    first = await authority.select(preferred_provider_id="beta")
    second = await authority.select(preferred_provider_id="beta")

    assert first == second
    assert first.provider_id == "beta"
    assert alpha.calls == beta.calls == 0
    assert components.provider_manager.last_attempted is None


@pytest.mark.asyncio
async def test_cor_and_provider_diagnostics_are_projected_from_canonical_rrm(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()

    assert isinstance(bridge.ecc.registry, RRMToCORAdapter)
    assert bridge.ecc.registry.rrm_service is bridge.components.resource_manager
    providers = await bridge.dispatch({"action": "providers"})

    assert providers["availability_authority"] == "RRM"
    assert providers["available_semantics"] == (
        "registered_binding_compatibility_alias"
    )
    assert providers["registered_bindings"] == ["mock"]
    assert providers["eligible"] == []
    assert providers["selection"]["provider_id"] is None
    assert providers["resource_states"] == [{
        "provider_id": "mock",
        "registered": True,
        "rrm_available": False,
        "eligible": False,
        "selected": False,
        "attempted": False,
        "used": False,
    }]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "Quero organizar escalas, prontuários e estoque de uma clínica veterinária.",
        "Quero controlar reservas, manutenção e consumo de uma pousada rural.",
    ],
)
async def test_new_novel_domains_do_not_activate_registered_domain_defaults(
    monkeypatch, tmp_path, message
):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    response = await ProductBridge().dispatch({
        "action": "intent",
        "message": message,
        "session_id": "m13-novel",
        "domain_hint": "finance",
    })

    assert response["status"] in {"UNKNOWN", "EXTERNAL_RESOURCE_REQUIRED"}
    assert response["ok"] is False
    assert response["provider_called"] is False
    assert response["mission_id"] is None
    assert response["compatibility_path_used"] is False
    assert response["missing_capabilities"]
