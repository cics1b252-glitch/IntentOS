"""Sprint 6 tests for canonical agents and capability execution."""

from __future__ import annotations

import pytest

from intent_kernel.adapters import LegacyAgentAdapter
from intent_kernel.agents import FinanceAgent
from intent_kernel.application import KernelBuilder
from intent_kernel.contracts import (
    Agent,
    AgentRequest,
    Capability,
    CapabilityRequest,
    CapabilityResult,
    ConstitutionDecision,
    ConstitutionVerdict,
    Domain,
    EffectType,
    ErrorCode,
    MissionContext,
)
from intent_kernel.core_apps import CapabilityRouter
from intent_kernel.orchestration import (
    CanonicalAgentOrchestrator,
    CanonicalCapabilityRegistry,
    CapabilityExecutionService,
    ExecutorKind,
)


async def _running_mission(components, domain=Domain.OTHER):
    mission = await components.mission_engine.create(
        "Sprint 6 execution",
        context=MissionContext(domain=domain, session_id="sprint-6"),
    )
    return await components.mission_engine.start(mission.id)


def test_registry_discovers_apps_agents_and_providers(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    registry = components.capability_registry

    assert registry.select(
        "finance.intent",
        preferred_kind=ExecutorKind.CORE_APP,
    ).executor_id == "atlas"
    assert registry.select(
        "investment_analysis",
        preferred_kind=ExecutorKind.AGENT,
    ).executor_id == "finance"
    assert registry.select(
        "provider.text_completion",
        preferred_kind=ExecutorKind.PROVIDER,
    ).executor_id == "mock"
    assert registry.validate() == []


def test_agent_registration_and_capability_selection(tmp_path):
    orchestrator = (
        KernelBuilder()
        .with_pkb_path(tmp_path / "pkb")
        .build()
        .agent_orchestrator
    )

    assert len(orchestrator.agents) == 3
    assert str(orchestrator.select("portfolio").agent_id) == "finance"
    assert str(orchestrator.select("research").agent_id) == "knowledge"
    assert str(orchestrator.select("cad").agent_id) == "engineering"


@pytest.mark.asyncio
async def test_no_compatible_agent_returns_canonical_error(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    mission = await _running_mission(components)

    result = await components.agent_orchestrator.execute(
        AgentRequest(
            mission=mission,
            capability="missing",
            task="nothing",
        )
    )

    assert result.success is False
    assert result.error_code is ErrorCode.CAPABILITY_UNAVAILABLE


@pytest.mark.asyncio
async def test_execution_through_core_app(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    mission = await _running_mission(components, Domain.FINANCE)

    outcome = await components.capability_execution_service.execute(
        mission.id,
        "finance.intent",
        payload={"text": "quero investir 5000"},
        preferred_kind=ExecutorKind.CORE_APP,
    )

    assert outcome.result.success is True
    assert outcome.result.metadata["executor"] == "atlas"
    assert "investimento único ou para um aporte mensal" in outcome.result.output


@pytest.mark.asyncio
async def test_execution_through_provider_port(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    mission = await _running_mission(components)

    outcome = await components.capability_execution_service.execute(
        mission.id,
        "provider.text_completion",
        payload={"text": "Explique o projeto"},
        preferred_kind=ExecutorKind.PROVIDER,
    )

    assert outcome.result.success is True
    assert outcome.result.metadata["provider"] == "mock"
    assert outcome.result.metadata["executor_kind"] == "provider"


@pytest.mark.asyncio
async def test_execution_through_agent_proposes_knowledge(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    mission = await _running_mission(components, Domain.FINANCE)

    outcome = await components.capability_execution_service.execute(
        mission.id,
        "investment_analysis",
        payload={"text": "quero investir em FIIs"},
        preferred_kind=ExecutorKind.AGENT,
    )

    assert outcome.result.success is True
    assert outcome.result.metadata["agent_id"] == "finance"
    assert outcome.knowledge_event_ids
    stored = await components.knowledge_store.get(
        outcome.knowledge_event_ids[0]
    )
    assert stored is not None
    assert stored.source == "agent:finance"
    assert stored.metadata["candidate"] is True


@pytest.mark.asyncio
async def test_constitution_can_block_before_executor(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    mission = await _running_mission(components)

    class DenyConstitution:
        async def evaluate(self, action, data=None, context=None):
            return ConstitutionVerdict(
                decision=ConstitutionDecision.DENY,
                reason="characterized policy denial",
                metadata={"audit_id": "deny-1"},
            )

    service = CapabilityExecutionService(
        mission_engine=components.mission_engine,
        constitution=DenyConstitution(),
        capability_router=components.capability_router,
        registry=components.capability_registry,
        agent_orchestrator=components.agent_orchestrator,
        provider_manager=components.kernel.providers,
        knowledge_pipeline=components.kernel.knowledge.pipeline,
        event_publisher=components.event_publisher,
        idempotency_store=components.idempotency_store,
    )
    outcome = await service.execute(
        mission.id,
        "finance.intent",
    )

    assert outcome.result.success is False
    assert outcome.result.error_code is ErrorCode.POLICY_DENIED
    assert outcome.constitution_verdict.reason == "characterized policy denial"


@pytest.mark.asyncio
async def test_external_effect_requires_confirmation_and_is_idempotent(
    tmp_path,
):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    mission = await _running_mission(components)
    calls = 0

    class ExternalApp:
        app_id = "external-test"
        capabilities = (
            Capability(
                name="external.test",
                effect=EffectType.EXTERNAL_CHANGE,
                requires_confirmation=True,
            ),
        )

        async def execute(self, request: CapabilityRequest):
            nonlocal calls
            calls += 1
            return CapabilityResult(
                capability=request.capability,
                success=True,
                output="changed",
            )

        async def health(self):
            return True

    app = ExternalApp()
    components.capability_router.register(app)
    components.capability_registry.register_core_app(app)
    service = components.capability_execution_service

    missing_key = await service.execute(mission.id, "external.test")
    unconfirmed = await service.execute(
        mission.id,
        "external.test",
        idempotency_key="external-1",
    )
    first = await service.execute(
        mission.id,
        "external.test",
        idempotency_key="external-1",
        confirmed=True,
    )
    replay = await service.execute(
        mission.id,
        "external.test",
        idempotency_key="external-1",
        confirmed=True,
    )

    assert missing_key.result.error_code is ErrorCode.INVALID_REQUEST
    assert unconfirmed.result.error_code is ErrorCode.PERMISSION_REQUIRED
    assert first.result.success is True
    assert replay.result.metadata["idempotent_replay"] is True
    assert calls == 1


@pytest.mark.asyncio
async def test_execution_audit_contains_metadata_not_payload(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    mission = await _running_mission(components, Domain.FINANCE)
    secret = "secret-that-must-not-be-audited"

    await components.capability_execution_service.execute(
        mission.id,
        "finance.intent",
        payload={"text": secret},
    )
    records = components.kernel.event_bus.get_history("capability.audit")
    serialized = repr(records)

    assert records
    assert records[-1]["data"]["payload"]["mission_id"] == str(mission.id)
    assert secret not in serialized


@pytest.mark.asyncio
async def test_mission_engine_retains_lifecycle_authority(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()
    mission = await _running_mission(components, Domain.FINANCE)

    await components.capability_execution_service.execute(
        mission.id,
        "finance.intent",
    )
    after = await components.mission_engine.get(mission.id)

    assert after.status == mission.status


@pytest.mark.asyncio
async def test_legacy_agent_adapter_satisfies_canonical_contract():
    legacy = FinanceAgent()
    adapter = LegacyAgentAdapter(legacy)

    assert isinstance(adapter, Agent)
    assert legacy.kernel is None
    mission = type("MissionStub", (), {"objective": "investir"})()
    # The real orchestrator supplies a canonical Mission; the adapter only
    # consumes the task and bounded context.
    request = AgentRequest(
        mission=mission,
        capability="investment_analysis",
        task="quero investir",
    )
    result = await adapter.execute(request)

    assert result.success is True
    assert result.metadata["agent_id"] == "finance"
