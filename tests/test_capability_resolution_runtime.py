"""Integration tests for Movements 5, 6A and 7A."""

import pytest

from intent_kernel.application import ApplicationFactory, KernelBuilder
from intent_kernel.bus import EventBus
from intent_kernel.cognition import (
    AgentBlueprintResolver,
    CapabilityRequirement,
    CapabilityRequirementDiscovery,
    CognitiveExecutionMode,
    DiscoveredResourceCandidate,
    DiscoveredResourceType,
    ResourceTruthState,
)
from intent_kernel.rrm.models import AgentResource, CapabilityResource
from intent_kernel.rrm.service import RegistryResourceManager
from intent_kernel.tools.models import PermissionDecisionState, PermissionScope
from intent_kernel.tools.permissions import PermissionManager
from product_bridge import ProductBridge


@pytest.fixture
def components(tmp_path):
    return ApplicationFactory(
        KernelBuilder().with_pkb_path(tmp_path / "pkb")
    ).get_components()


@pytest.mark.asyncio
async def test_rrm_is_primary_authority_for_projected_runtime_resources(components):
    caps = {item.capability_id for item in components.resource_manager.list_capabilities()}
    agents = components.resource_manager.list_agents()
    providers = components.resource_manager.list_providers()
    assert "finance.intent" in caps
    assert agents
    assert providers
    assert components.resource_manager.list_providers(only_eligible=True) == []


@pytest.mark.asyncio
async def test_real_kernel_path_populates_capability_analysis(components):
    context = {"project_id": "workshop", "session_id": "runtime-test"}
    await components.kernel.process(
        "Quero organizar ordens de serviço, peças e clientes de uma oficina.",
        context,
    )
    analysis = context["capability_analysis"]
    ids = {item["capability_id"] for item in analysis["requirements"]}
    assert {"service_order.management", "inventory.parts", "customer.records"} <= ids
    assert analysis["domain_hint"]


@pytest.mark.asyncio
async def test_product_bridge_exposes_pre_execution_capability_analysis(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()
    response = await bridge.dispatch({
        "action": "intent",
        "message": "O que você consegue fazer?",
        "session_id": "capability-runtime",
    })
    diagnostics = await bridge.dispatch({"action": "diagnostics"})
    assert response["ok"] is True
    assert diagnostics["capability_analysis"]["mode"] == "LOCAL_RESPONSE"


@pytest.mark.asyncio
async def test_multiple_capabilities_produce_composition(components):
    decision = await components.cognitive_capability_runtime.analyze(
        "Quero organizar ordens de serviço, peças, clientes e manutenção de uma pequena oficina.",
        project_context={"project_id": "workshop"},
    )
    assert len(decision.requirements) >= 3
    assert len(decision.composition.steps) == len(decision.requirements)
    assert all("Atlas" not in item.strategy for item in decision.composition.steps)


@pytest.mark.asyncio
async def test_local_system_question_uses_local_response(components):
    decision = await components.cognitive_capability_runtime.analyze(
        "O que você consegue fazer?"
    )
    assert decision.mode is CognitiveExecutionMode.LOCAL_RESPONSE


@pytest.mark.asyncio
async def test_missing_reasoning_provider_is_truthful(components):
    decision = await components.cognitive_capability_runtime.analyze(
        "Explique um conceito totalmente novo para mim."
    )
    assert decision.mode is CognitiveExecutionMode.EXTERNAL_REASONING_REQUIRED
    assert decision.composition.executable is False


@pytest.mark.asyncio
async def test_application_control_is_not_executed_when_resource_missing(components):
    decision = await components.cognitive_capability_runtime.analyze(
        "Quero que o sistema abra um programa instalado e faça uma tarefa nele."
    )
    assert decision.mode is CognitiveExecutionMode.UNKNOWN
    assert decision.composition.executable is False
    assert "application.launch" in decision.composition.missing_capabilities


def test_existing_agent_is_selected_by_capability_not_domain():
    rrm = RegistryResourceManager(populate_defaults=False)
    rrm.register_agent(AgentResource(
        agent_id="records_agent",
        name="Records Agent",
        capabilities=["customer.records", "service_order.management"],
    ))
    requirements = [
        CapabilityRequirement("customer.records", "Customer records"),
        CapabilityRequirement("service_order.management", "Service orders"),
    ]
    result = AgentBlueprintResolver(rrm).resolve(
        requirements, mission_scope="workshop"
    )
    assert result.selected_agent_id == "records_agent"
    assert result.blueprint is None


def test_missing_agent_produces_blueprint_without_instantiation():
    rrm = RegistryResourceManager(populate_defaults=False)
    requirements = [CapabilityRequirement("report.aggregate", "Aggregate report")]
    result = AgentBlueprintResolver(rrm).resolve(
        requirements, mission_scope="monthly-invoices"
    )
    assert result.selected_agent_id is None
    assert result.blueprint.required_capabilities == ("report.aggregate",)
    assert result.blueprint.retention_policy == "discard_after_mission"
    assert result.blueprint.lifecycle.value == "PROPOSED"


@pytest.mark.parametrize(
    ("truth_state", "permission", "authorization_required", "executable"),
    [
        (ResourceTruthState.DISCOVERED, "not_configured", True, False),
        (ResourceTruthState.UNAVAILABLE, "granted", False, False),
        (ResourceTruthState.AVAILABLE, "not_configured", True, False),
        (ResourceTruthState.AVAILABLE, "granted", False, True),
        (ResourceTruthState.BLOCKED, "granted", False, False),
    ],
)
def test_resource_truth_never_equates_discovery_with_authorization(
    truth_state, permission, authorization_required, executable
):
    candidate = DiscoveredResourceCandidate(
        resource_id="synthetic-app",
        resource_type=DiscoveredResourceType.APPLICATION,
        name="Synthetic Application",
        capabilities=("application.launch",),
        origin="synthetic_test",
        environment="test",
        truth_state=truth_state,
        permission_state=permission,
        authorization_required=authorization_required,
    )
    assert candidate.executable is executable


@pytest.mark.asyncio
async def test_synthetic_discovery_port_is_declarative_only():
    class SyntheticDiscovery:
        async def discover_candidates(self, context):
            return [DiscoveredResourceCandidate(
                resource_id="api-1",
                resource_type=DiscoveredResourceType.API,
                name="Synthetic API",
                capabilities=("report.aggregate",),
                origin="synthetic_test",
                environment="test",
            )]

        async def describe_capabilities(self, resource_id):
            return ("report.aggregate",)

        async def describe_permissions(self, resource_id):
            return {"state": "not_configured"}

        async def describe_health(self, resource_id):
            return "unknown"

    candidates = await SyntheticDiscovery().discover_candidates({})
    assert candidates[0].truth_state is ResourceTruthState.DISCOVERED
    assert candidates[0].executable is False


@pytest.mark.asyncio
async def test_invoice_novel_domain_decomposes_without_accounting_module(components):
    decision = await components.cognitive_capability_runtime.analyze(
        "Quero analisar automaticamente as notas fiscais que recebo, organizar os dados e produzir um resumo mensal."
    )
    ids = {item.capability_id for item in decision.requirements}
    assert {
        "document.read",
        "document.extract_structured_data",
        "data.normalize",
        "report.aggregate",
    } <= ids
    assert "AccountingModule" not in str(decision.to_dict())


@pytest.mark.asyncio
async def test_event_bus_isolates_async_handler_failure():
    bus = EventBus()
    observed = []

    async def broken(_data):
        raise RuntimeError("sensitive details must not be copied")

    async def healthy(data):
        observed.append(data)

    bus.subscribe("test", broken)
    bus.subscribe("test", healthy)
    await bus.publish("test", {"ok": True})
    assert observed == [{"ok": True}]
    assert bus.get_failures("test") == [{
        "event_type": "test",
        "handler": "broken",
        "error_type": "RuntimeError",
    }]


def test_permission_revoke_preserves_original_scope():
    manager = PermissionManager()
    manager.grant_permission(
        "mail", "send", scope=PermissionScope.SESSION, project_id="project-a"
    )
    revoked = manager.revoke_permission("mail", "send", project_id="project-a")
    assert revoked.scope is PermissionScope.SESSION
    assert revoked.state is PermissionDecisionState.REVOKED


def test_finance_remains_compatibility_capability(components):
    projected = components.resource_manager.get_capability("finance.intent")
    assert projected is not None
    assert projected.metadata == {
        "executor_kind": "core_app",
        "executor_id": "atlas",
    }
