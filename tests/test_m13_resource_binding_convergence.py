"""Movement 13: RRM-governed resource, binding, and registry convergence."""

from __future__ import annotations

import pytest
from pathlib import Path

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
from intent_kernel.promotion.models import BootstrapResourceDeclaration
from intent_kernel.providers.authority import CanonicalProviderAuthority
from intent_kernel.rrm.models import (
    AvailabilitySource,
    CapabilityResource,
    ConditionalResourceStatusRequest,
    ConditionalUpdateOutcome,
    ResourceOrigin,
    ResourceStatus,
    ResourceType,
)

from tests.conftest import m32a_isolated_store_root
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
    _govern_core_app_binding(components, app.app_id, "resource.switchable")


def _govern_core_app_binding(components, executor_id: str, capability_name: str) -> None:
    """M31.3B-1B — govern a runtime-added core-app binding via the production
    chain (single source: canonical capability registry)."""
    registrations = components.capability_registry.discover(
        capability_name,
        executor_kind=ExecutorKind.CORE_APP,
    )
    registration = next(
        r for r in registrations if r.executor_id == executor_id
    )
    report = components.resource_promotion_service.bootstrap_govern(
        [BootstrapResourceDeclaration.from_registration(registration)]
    )
    assert report.success, [
        (e.resource_id, e.reason) for e in report.entries
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [ResourceStatus.UNAVAILABLE, ResourceStatus.DEGRADED])
async def test_registered_healthy_binding_cannot_override_rrm(status, tmp_path, m32a_isolated_store_root: Path):
    authority_file = m32a_isolated_store_root / "rrm" / "authority.json"
    continuity_file = m32a_isolated_store_root / "continuity" / "identity.json"
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build(authority_file=authority_file, continuity_file=continuity_file)
    snapshot = components.resource_manager.get_capability("finance.intent")
    update = components.resource_manager.conditional_update_status(
        ConditionalResourceStatusRequest(
            resource_type=ResourceType.CAPABILITY,
            resource_id="finance.intent",
            expected_governed_registration_id=snapshot.governed_registration_id,
            expected_generation=snapshot.generation,
            desired_status=status,
        )
    )
    assert update.outcome is ConditionalUpdateOutcome.APPLIED

    decision = await components.capability_execution_service.resource_authority.resolve(
        "finance.intent"
    )

    assert decision.available is False
    assert decision.registration is None
    assert decision.registered is True
    assert decision.rrm_eligible is False
    assert decision.reason == "rrm_rejected_bindings"


@pytest.mark.asyncio
async def test_registry_only_and_rrm_only_resources_are_not_executable(tmp_path, m32a_isolated_store_root: Path):
    authority_file = m32a_isolated_store_root / "rrm" / "authority.json"
    continuity_file = m32a_isolated_store_root / "continuity" / "identity.json"
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build(authority_file=authority_file, continuity_file=continuity_file)
    authority = components.capability_execution_service.resource_authority

    app = SwitchableApp()
    components.capability_router.register(app)
    components.capability_registry.register_core_app(app)
    # Deliberately NOT projected into RRM and NOT governed: a registry-only
    # binding must never become executable.
    registry_only = await authority.resolve("resource.switchable")

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
    assert registry_only.reason == "rrm_rejected_bindings"
    assert rrm_only.available is False
    assert rrm_only.registered is False
    assert rrm_only.reason == "binding_missing"


@pytest.mark.asyncio
async def test_binding_health_is_revalidated_immediately_before_dispatch(tmp_path, m32a_isolated_store_root: Path):
    authority_file = m32a_isolated_store_root / "rrm" / "authority.json"
    continuity_file = m32a_isolated_store_root / "continuity" / "identity.json"
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build(authority_file=authority_file, continuity_file=continuity_file)
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
async def test_stale_registry_binding_is_rejected_before_dispatch(tmp_path, m32a_isolated_store_root: Path):
    authority_file = m32a_isolated_store_root / "rrm" / "authority.json"
    continuity_file = m32a_isolated_store_root / "continuity" / "identity.json"
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build(authority_file=authority_file, continuity_file=continuity_file)
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
async def test_canonical_provider_execution_uses_observed_invocation_boundary(tmp_path, m32a_isolated_store_root: Path):
    authority_file = m32a_isolated_store_root / "rrm" / "authority.json"
    continuity_file = m32a_isolated_store_root / "continuity" / "identity.json"
    spare = RecordingProvider("spare")
    components = (
        KernelBuilder()
        .with_provider("spare", spare, default=True)
        .with_pkb_path(tmp_path / "pkb")
        .build(authority_file=authority_file, continuity_file=continuity_file)
    )
    mission = await _running_mission(components)

    outcome = await components.capability_execution_service.execute(
        mission.id,
        "provider.text_completion",
        payload={"text": "provider boundary"},
        preferred_kind=ExecutorKind.PROVIDER,
    )

    assert outcome.result.success is True
    assert components.provider_manager.last_attempted == "spare"
    assert components.provider_manager.last_used == "spare"
    assert outcome.result.metadata["provider_invocation_attempted"] is True


@pytest.mark.asyncio
async def test_provider_throw_is_observed_only_after_actual_attempt(tmp_path, m32a_isolated_store_root: Path):
    authority_file = m32a_isolated_store_root / "rrm" / "authority.json"
    continuity_file = m32a_isolated_store_root / "continuity" / "identity.json"
    provider = RecordingProvider("throwing", error=RuntimeError("provider failed"))
    components = (
        KernelBuilder()
        .with_provider("throwing", provider, default=True)
        .with_pkb_path(tmp_path / "pkb")
        .build(authority_file=authority_file, continuity_file=continuity_file)
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
async def test_provider_backed_core_app_cannot_use_ineligible_default(tmp_path, m32a_isolated_store_root: Path):
    authority_file = m32a_isolated_store_root / "rrm" / "authority.json"
    continuity_file = m32a_isolated_store_root / "continuity" / "identity.json"
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build(authority_file=authority_file, continuity_file=continuity_file)
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
async def test_authorization_denial_after_resolution_never_dispatches(tmp_path, m32a_isolated_store_root: Path):
    authority_file = m32a_isolated_store_root / "rrm" / "authority.json"
    continuity_file = m32a_isolated_store_root / "continuity" / "identity.json"
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build(authority_file=authority_file, continuity_file=continuity_file)
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
async def test_multiple_provider_candidates_are_deterministic_and_not_invoked(tmp_path, m32a_isolated_store_root: Path):
    authority_file = m32a_isolated_store_root / "rrm" / "authority.json"
    continuity_file = m32a_isolated_store_root / "continuity" / "identity.json"
    alpha = RecordingProvider("alpha")
    beta = RecordingProvider("beta")
    components = (
        KernelBuilder()
        .with_provider("alpha", alpha)
        .with_provider("beta", beta)
        .with_pkb_path(tmp_path / "pkb")
        .build(authority_file=authority_file, continuity_file=continuity_file)
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
    monkeypatch, tmp_path, m32a_isolated_store_root: Path
):
    authority_file = m32a_isolated_store_root / "rrm" / "authority.json"
    continuity_file = m32a_isolated_store_root / "continuity" / "identity.json"
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge(
        data_root=tmp_path,
        authority_file=authority_file,
        continuity_file=continuity_file,
    )

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
    monkeypatch, tmp_path, m32a_isolated_store_root: Path, message
):
    authority_file = m32a_isolated_store_root / "rrm" / "authority.json"
    continuity_file = m32a_isolated_store_root / "continuity" / "identity.json"
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge(
        data_root=tmp_path,
        authority_file=authority_file,
        continuity_file=continuity_file,
    )
    response = await bridge.dispatch({
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
