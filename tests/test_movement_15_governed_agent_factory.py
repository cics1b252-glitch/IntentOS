"""Movement 15 tests: governed agent instantiation / agent factory convergence.

AGENT IS A GOVERNED EXECUTION PARTICIPANT. AGENT IS NOT SYSTEM AUTHORITY.
"""

from __future__ import annotations

import pytest

from intent_kernel.agents.factory import (
    AgentExecutionConstraints,
    AgentIdentityError,
    AgentLifecycleError,
    AgentLifecycleState,
    AgentSpec,
    CanonicalAgentFactory,
    CanonicalAgentRegistry,
    GovernedAgent,
    InvalidAgentSpecError,
    MissionBindingError,
)
from intent_kernel.application import ApplicationFactory, KernelBuilder
from intent_kernel.contracts import AgentId


def _spec(
    agent_type: str = "analyst",
    role: str = "assistant",
    description: str = "governed assistant",
    **overrides,
) -> AgentSpec:
    values = dict(
        agent_type=agent_type,
        role=role,
        description=description,
    )
    values.update(overrides)
    return AgentSpec(**values)


def _bound(factory: CanonicalAgentFactory, mission_id: str = "mission-1"):
    agent = factory.create(_spec())
    factory.bind(agent.agent_id, mission_id)
    return agent


def test_A1_factory_creates_governed_agent_in_created_state():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec())
    assert isinstance(agent, GovernedAgent)
    assert agent.lifecycle == AgentLifecycleState.CREATED
    assert not agent.lifecycle.terminal


def test_A2_factory_assigns_uuid_identity_never_user_supplied():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec(agent_type="legal_document_assistant"))
    assert str(agent.agent_id).startswith("agent_")
    assert agent.agent_id != "legal_document_assistant"
    second = factory.create(_spec(agent_type="legal_document_assistant"))
    assert second.agent_id != agent.agent_id


def test_A3_agentspec_rejects_unknown_fields():
    with pytest.raises(TypeError):
        AgentSpec(
            agent_type="x",
            role="r",
            description="d",
            not_a_real_field=True,
        )


def test_A4_agentspec_validates_required_fields():
    with pytest.raises(ValueError):
        AgentSpec(agent_type="  ", role="r", description="d")
    with pytest.raises(ValueError):
        AgentSpec(agent_type="x", role="  ", description="d")
    with pytest.raises(ValueError):
        AgentSpec(agent_type="x", role="r", description="  ")
    with pytest.raises(ValueError):
        AgentSpec(agent_type="x", role="r", description="d", declared_capabilities=("ok", " "))


def test_A5_registry_rejects_duplicate_identity_without_silent_replacement():
    registry = CanonicalAgentRegistry()
    first = GovernedAgent(agent_id=AgentId("dup"), spec=_spec())
    registry.register(first)
    with pytest.raises(AgentIdentityError):
        registry.register(GovernedAgent(agent_id=AgentId("dup"), spec=_spec()))
    assert registry.get("dup") is first
    assert len(registry) == 1


def test_A6_registry_presence_is_not_authorization():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec())
    snapshot = agent.snapshot()
    assert snapshot["authority"] == "NONE"
    assert snapshot["execution_path"] == "governed_mission_runtime_only"


def test_A7_guarded_lifecycle_forward_path():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec())
    factory.transition(agent.agent_id, AgentLifecycleState.READY)
    assert agent.lifecycle == AgentLifecycleState.READY
    factory.bind(agent.agent_id, "mission-1")
    assert agent.lifecycle == AgentLifecycleState.BOUND
    factory.transition(agent.agent_id, AgentLifecycleState.RUNNING)
    factory.transition(agent.agent_id, AgentLifecycleState.WAITING)
    factory.transition(agent.agent_id, AgentLifecycleState.RUNNING)
    factory.transition(agent.agent_id, AgentLifecycleState.COMPLETED)
    assert agent.lifecycle == AgentLifecycleState.COMPLETED


def test_A8_illegal_transitions_rejected():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec())
    with pytest.raises(AgentLifecycleError):
        factory.transition(agent.agent_id, AgentLifecycleState.RUNNING)
    with pytest.raises(AgentLifecycleError):
        factory.transition(agent.agent_id, AgentLifecycleState.BOUND)
    with pytest.raises(AgentLifecycleError):
        factory.transition(agent.agent_id, AgentLifecycleState.COMPLETED)
    assert agent.lifecycle == AgentLifecycleState.CREATED


def test_A9_terminal_states_cannot_reopen():
    factory = CanonicalAgentFactory()
    agent = _bound(factory)
    factory.transition(agent.agent_id, AgentLifecycleState.RUNNING)
    factory.transition(agent.agent_id, AgentLifecycleState.COMPLETED)
    with pytest.raises(AgentLifecycleError):
        factory.transition(agent.agent_id, AgentLifecycleState.RUNNING)
    with pytest.raises(AgentLifecycleError):
        factory.transition(agent.agent_id, AgentLifecycleState.READY)


def test_A10_revocation_fails_closed():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec())
    factory.bind(agent.agent_id, "mission-1")
    factory.registry.revoke(agent.agent_id)
    assert factory.registry.is_revoked(agent.agent_id)
    assert agent.lifecycle == AgentLifecycleState.REVOKED
    with pytest.raises(AgentLifecycleError):
        factory.transition(agent.agent_id, AgentLifecycleState.BOUND)


def test_A11_revoke_terminal_non_revoked_rejected():
    factory = CanonicalAgentFactory()
    agent = _bound(factory)
    factory.transition(agent.agent_id, AgentLifecycleState.RUNNING)
    factory.transition(agent.agent_id, AgentLifecycleState.COMPLETED)
    with pytest.raises(AgentLifecycleError):
        factory.registry.revoke(agent.agent_id)


def test_A12_binding_requires_explicit_mission():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec())
    with pytest.raises(MissionBindingError):
        factory.bind(agent.agent_id, "")
    with pytest.raises(MissionBindingError):
        factory.bind(agent.agent_id, None)
    assert agent.lifecycle == AgentLifecycleState.CREATED


def test_A13_binding_to_different_mission_rejected():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec(mission_id="mission-a"))
    with pytest.raises(MissionBindingError):
        factory.bind(agent.agent_id, "mission-b")
    assert agent.mission_id == "mission-a"


def test_A14_double_bind_rejected():
    factory = CanonicalAgentFactory()
    agent = _bound(factory, "mission-1")
    with pytest.raises(AgentLifecycleError):
        factory.bind(agent.agent_id, "mission-1")


def test_A15_factory_never_invents_mission():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec())
    assert agent.mission_id is None
    with pytest.raises(MissionBindingError):
        factory.bind(agent.agent_id, "   ")
    assert agent.mission_id is None


def test_A16_execution_constraints_bounded():
    spec = _spec(
        execution_constraints=AgentExecutionConstraints(
            allowed_tools=("memory.read",),
            allowed_resources=("rrm:documents",),
            max_output_chars=1000,
            timeout_seconds=5.0,
            allow_external_effects=False,
        )
    )
    agent = CanonicalAgentFactory().create(spec)
    snapshot = agent.snapshot()
    assert snapshot["execution_constraints"]["allowed_tools"] == ["memory.read"]
    assert snapshot["execution_constraints"]["allowed_resources"] == ["rrm:documents"]
    assert snapshot["execution_constraints"]["max_output_chars"] == 1000
    assert snapshot["execution_constraints"]["timeout_seconds"] == 5.0
    assert snapshot["execution_constraints"]["allow_external_effects"] is False
    with pytest.raises(ValueError):
        AgentExecutionConstraints(max_output_chars=-1)
    with pytest.raises(ValueError):
        AgentExecutionConstraints(timeout_seconds=0)


def test_A17_memory_scope_bounded():
    assert _spec(memory_scope="mission").memory_scope == "mission"
    assert _spec(memory_scope="project").memory_scope == "project"
    assert _spec(memory_scope="none").memory_scope == "none"
    with pytest.raises(ValueError):
        _spec(memory_scope="unbounded_global")


def test_A18_snapshot_observable_secret_free():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec(
        agent_type="warehouse_inventory_assistant",
        description="managed warehouse stock",
    ))
    snapshot = agent.snapshot()
    for key in ("agent_id", "agent_type", "role", "lifecycle", "authority"):
        assert key in snapshot
    assert "authority" in snapshot and snapshot["authority"] == "NONE"
    assert "secret" not in str(snapshot).lower()
    assert "api_key" not in str(snapshot).lower()
    assert "token" not in str(snapshot).lower()
    assert len(factory.snapshot()) == 1


def test_A19_capability_declarations_are_claims_not_availability():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec(
        agent_type="language_tutor_agent",
        declared_capabilities=("conversation.tutor", "quiz.generate"),
    ))
    assert "conversation.tutor" in agent.spec.declared_capabilities
    assert "availability" not in agent.snapshot()
    assert "authority" not in agent.snapshot().get("declared_capabilities", [])


def test_A20_creation_does_not_invoke_providers():
    class ExplodingProvider:
        def execute(self, *args, **kwargs):
            raise AssertionError("provider must never be invoked during creation")

    factory = CanonicalAgentFactory()
    spec = _spec(
        agent_type="vehicle_maintenance_assistant",
        provider_requirements=("mock",),
        resource_requirements=("rrm:workshop",),
    )
    agent = factory.create(spec)
    assert not hasattr(factory, "provider")
    assert not hasattr(factory, "provider_manager")
    assert agent.lifecycle == AgentLifecycleState.CREATED


def test_A21_role_names_grant_no_authority():
    factory = CanonicalAgentFactory()
    for role in ("admin", "supervisor", "manager", "expert", "master"):
        agent = factory.create(_spec(role=role))
        assert agent.snapshot()["authority"] == "NONE"
        assert agent.snapshot()["lifecycle"] == "CREATED"


def test_A22_registry_lookup_by_mission():
    factory = CanonicalAgentFactory()
    factory.create(_spec(agent_type="a1", mission_id="m-a"))
    factory.create(_spec(agent_type="a2", mission_id="m-a"))
    factory.create(_spec(agent_type="a3", mission_id="m-b"))
    assert len(factory.registry.lookup(mission_id="m-a")) == 2
    assert len(factory.registry.lookup(mission_id="m-b")) == 1
    assert len(factory.registry.lookup(mission_id="m-missing")) == 0


def test_A23_governed_agent_has_no_direct_execution_authority():
    agent = CanonicalAgentFactory().create(_spec())
    for attribute in ("execute", "verify", "complete", "authorize", "confirm"):
        assert not hasattr(agent, attribute)
    assert not hasattr(agent, "spawn")
    assert not hasattr(agent, "factory")


def test_A24_composition_exposes_factory_additively(tmp_path):
    components = ApplicationFactory(
        KernelBuilder().with_pkb_path(tmp_path / "pkb")
    ).get_components()
    assert isinstance(components.agent_factory, CanonicalAgentFactory)
    assert isinstance(components.agent_registry, CanonicalAgentRegistry)
    assert components.agent_registry is components.agent_factory.registry
    assert len(components.agent_registry) == 0
    assert len(components.agent_orchestrator.agents) == 3
    assert not hasattr(components, "legacy_agent_orchestrator")


def test_adversarial_user_supplied_identity_impossible():
    factory = CanonicalAgentFactory()
    with pytest.raises(TypeError):
        factory.create(_spec(), agent_id="forged-identity")


def test_adversarial_empty_identity_rejected():
    with pytest.raises(ValueError):
        AgentId("   ")


def test_adversarial_transition_non_enum_rejected():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec())
    with pytest.raises(AgentLifecycleError):
        factory.transition(agent.agent_id, "READY")


def test_adversarial_transition_unknown_agent_rejected():
    factory = CanonicalAgentFactory()
    with pytest.raises(AgentIdentityError):
        factory.transition("agent_unknown", AgentLifecycleState.READY)


def test_adversarial_revoke_unknown_agent_rejected():
    factory = CanonicalAgentFactory()
    with pytest.raises(AgentIdentityError):
        factory.registry.revoke("agent_unknown")


def test_adversarial_bind_unknown_agent_rejected():
    factory = CanonicalAgentFactory()
    with pytest.raises(AgentIdentityError):
        factory.bind("agent_unknown", "mission-1")


def test_adversarial_agent_cannot_self_verify():
    agent = CanonicalAgentFactory().create(_spec())
    assert not hasattr(agent, "verification_status")
    assert not hasattr(agent, "verify")
    snapshot = agent.snapshot()
    assert "verification" not in snapshot.get("authority", "").lower()


def test_adversarial_agent_cannot_self_complete():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec())
    assert not hasattr(agent, "completion")
    assert not hasattr(agent, "complete")
    with pytest.raises(AgentLifecycleError):
        factory.transition(agent.agent_id, AgentLifecycleState.COMPLETED)


def test_adversarial_no_privilege_amplification():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec())
    assert not hasattr(agent, "create")
    assert not hasattr(agent, "instantiate")
    assert not hasattr(agent, "registry")
    assert len(factory.registry) == 1


def test_adversarial_instantiate_alias_fresh_identity():
    factory = CanonicalAgentFactory()
    first = factory.instantiate(_spec())
    second = factory.instantiate(_spec())
    assert first.agent_id != second.agent_id
    assert len(factory.registry) == 2


def test_novel_legal_document_assistant():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec(
        agent_type="legal_document_assistant",
        role="drafter",
        description="assists with contract drafting and clause review",
        declared_capabilities=("draft.contract", "clause.check", "obligation.extract"),
        mission_id="mission-legal",
        memory_scope="project",
        execution_constraints=AgentExecutionConstraints(
            allowed_tools=("document.read", "document.write"),
            max_output_chars=2000,
            allow_external_effects=False,
        ),
    ))
    factory.bind(agent.agent_id, "mission-legal")
    factory.transition(agent.agent_id, AgentLifecycleState.RUNNING)
    assert agent.lifecycle == AgentLifecycleState.RUNNING
    assert agent.snapshot()["authority"] == "NONE"
    assert agent.snapshot()["execution_constraints"]["allow_external_effects"] is False


def test_novel_warehouse_inventory_assistant():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec(
        agent_type="warehouse_inventory_assistant",
        role="stock_keeper",
        description="tracks warehouse stock levels and reorder points",
        declared_capabilities=("inventory.read", "stock.report", "reorder.alert"),
        mission_id="mission-wh",
        memory_scope="mission",
    ))
    factory.bind(agent.agent_id, "mission-wh")
    factory.transition(agent.agent_id, AgentLifecycleState.RUNNING)
    factory.transition(agent.agent_id, AgentLifecycleState.WAITING)
    factory.transition(agent.agent_id, AgentLifecycleState.RUNNING)
    factory.transition(agent.agent_id, AgentLifecycleState.COMPLETED)
    assert agent.lifecycle == AgentLifecycleState.COMPLETED
    assert agent.mission_id == "mission-wh"


def test_novel_language_tutor_agent():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec(
        agent_type="language_tutor_agent",
        role="tutor",
        description="language practice and lesson planning",
        declared_capabilities=("conversation.tutor", "lesson.plan", "quiz.generate"),
        memory_scope="none",
    ))
    assert agent.snapshot()["memory_scope"] == "none"
    factory.bind(agent.agent_id, "mission-tutor")
    factory.registry.revoke(agent.agent_id)
    assert factory.registry.is_revoked(agent.agent_id)
    with pytest.raises(AgentLifecycleError):
        factory.transition(agent.agent_id, AgentLifecycleState.RUNNING)


def test_novel_vehicle_maintenance_assistant():
    factory = CanonicalAgentFactory()
    agent = factory.create(_spec(
        agent_type="vehicle_maintenance_assistant",
        role="service_advisor",
        description="schedules maintenance and tracks service records",
        declared_capabilities=("maintenance.schedule", "service.record"),
        resource_requirements=("rrm:service_bay",),
        provider_requirements=("mock",),
        execution_constraints=AgentExecutionConstraints(
            allowed_resources=("rrm:service_bay",),
            timeout_seconds=60.0,
        ),
    ))
    assert agent.spec.resource_requirements == ("rrm:service_bay",)
    factory.bind(agent.agent_id, "mission-vehicle")
    assert agent.lifecycle == AgentLifecycleState.BOUND
    snapshot = agent.snapshot()
    assert snapshot["authority"] == "NONE"
    assert "api_key" not in str(snapshot).lower()
