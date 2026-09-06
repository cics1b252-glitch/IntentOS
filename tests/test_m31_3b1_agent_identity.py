"""M31.3B-1B — Exact Agent Executor Identity Binding (RA-31.3B-03).

THE AGENT EXECUTOR SELECTED
=
THE AGENT EXECUTOR REVALIDATED
=
THE AGENT EXECUTOR DISPATCHED

CapabilityExecutionService._dispatch passes the exact already-selected
`registration.executor` as `expected_executor` into
AgentOrchestrator.execute. The orchestrator retains its second agent-registry
lookup as a revalidation only, and requires exact Python object identity
(`is`) between the current registry object and the expected executor:

  resolved_agent is expected_executor

If the same agent_id now resolves a different object:

  select A -> registry resolves B -> FAIL CLOSED
  A executes 0, B executes 0, no fallback.

Tests:
A. exact A remains current -> A executes exactly once, success.
B. same agent_id replaced by B -> identity mismatch, A=0, B=0,
   CAPABILITY_UNAVAILABLE.
C. outer CapabilityRegistration identity preserved: the exact selected
   registration's executor reaches dispatch as expected_executor.
D. identity mismatch with an eligible same-id substitute -> no fallback,
   no alternate executor dispatch.
E. same-data different-object -> rejected (object identity, not structural
   equality).
F. liveness/eligibility rejection preserved when exact expected executor is
   present but not eligible for the requested capability.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from intent_kernel.contracts import (
    AgentId,
    AgentLimits,
    Capability,
    CapabilityResult,
    Domain,
    EffectType,
    ErrorCode,
    MissionId,
    MissionStatus,
)
from intent_kernel.orchestration.agents import CanonicalAgentOrchestrator
from intent_kernel.orchestration.execution import CapabilityExecutionService
from intent_kernel.orchestration.registry import CapabilityRegistration, ExecutorKind
from intent_kernel.rrm.binding import (
    ExecutionPrecondition,
    PreconditionKind,
    ResourceBindingDecision,
    ResourceBindingRevalidation,
)
from intent_kernel.rrm.generation import GENERATION_INITIAL


CAP_NAME = "tasks.draft"


# ---------------------------------------------------------------------------
# Deterministic fakes / test agents
# ---------------------------------------------------------------------------

class _TestAgent:
    """A minimal Agent-protocol object with an execution counter."""

    def __init__(
        self,
        agent_id: str,
        capability_names: tuple[str, ...] = (CAP_NAME,),
        label: str | None = None,
    ) -> None:
        self._agent_id = AgentId(agent_id)
        self._label = label or agent_id
        self._capabilities = tuple(
            Capability(
                name=name,
                description=f"cap {name}",
                effect=EffectType.GENERATE,
            )
            for name in capability_names
        )
        self.execute_count = 0

    @property
    def agent_id(self) -> AgentId:
        return self._agent_id

    @property
    def capabilities(self) -> tuple[Capability, ...]:
        return self._capabilities

    @property
    def limits(self) -> AgentLimits:
        return AgentLimits(timeout_seconds=10, max_output_chars=20000)

    async def execute(self, request) -> CapabilityResult:
        self.execute_count += 1
        return CapabilityResult(
            capability=request.capability,
            success=True,
            output=f"ok:{self._label}",
            confidence=0.9,
            error_code=None,
            metadata={},
        )


class _RecordingAgentOrchestrator(CanonicalAgentOrchestrator):
    """Records the dispatch args while delegating to the real orchestrator."""

    def __init__(self) -> None:
        super().__init__()
        self.last_agent_id: str | None = None
        self.last_expected_executor: Any = None

    async def execute(
        self,
        request,
        *,
        agent_id: str | None = None,
        expected_executor: Any = None,
    ):
        self.last_agent_id = agent_id
        self.last_expected_executor = expected_executor
        return await super().execute(
            request,
            agent_id=agent_id,
            expected_executor=expected_executor,
        )


class _FakeRRM:
    """Read-only RRM observation surface satisfying the B-1A freshness getters."""

    def __init__(
        self,
        grid: str = "reg-1",
        generation: int = GENERATION_INITIAL,
    ) -> None:
        self._grid = grid
        self._generation = generation

    def get_agent(self, agent_id: str) -> Any:
        return SimpleNamespace(
            governed_registration_id=self._grid,
            generation=self._generation,
        )

    def get_provider(self, provider_id: str) -> Any:
        return None

    def get_capability(self, name: str) -> Any:
        return None


class _StubAuthority:
    def __init__(self, rrm: _FakeRRM, decision: ResourceBindingDecision) -> None:
        self.rrm = rrm
        self._decision = decision

    async def resolve(self, capability: str, *, preferred_kind=None):
        return self._decision

    async def revalidate(self, decision):
        return ResourceBindingRevalidation(
            capability=decision.capability,
            valid=True,
            binding_registered=True,
            rrm_eligible=True,
            binding_healthy=True,
            reason="dispatch_revalidated",
            binding_identity=decision.binding_identity,
            execution_preconditions=decision.execution_preconditions,
        )


class _FakeConstitution:
    async def evaluate(self, action, data=None, context=None):
        return SimpleNamespace(
            allowed=True,
            decision=SimpleNamespace(value="allowed"),
            metadata={"audit_id": "audit-1"},
        )


class _FakeMissionEngine:
    def __init__(self, mission) -> None:
        self.mission = mission

    async def get(self, mission_id):
        return self.mission


class _FakeEventPublisher:
    async def publish(self, topic, data, *, correlation_id=None) -> None:
        pass


class _FakeKnowledgePipeline:
    async def ingest(self, events):
        return SimpleNamespace(event_ids=[])


class _FakeIdempotencyStore:
    def __init__(self) -> None:
        self.get_count = 0

    async def get(self, key) -> Any:
        self.get_count += 1
        return None

    async def save(self, key, outcome) -> None:
        pass


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _make_mission():
    return SimpleNamespace(
        id=MissionId("00000000-0000-0000-0000-00000000000a"),
        status=MissionStatus.RUNNING,
        objective="test objective",
        context=SimpleNamespace(
            correlation_id="corr-1",
            domain=Domain.OTHER,
            session_id="sess-1",
        ),
    )


def _make_capability(name: str = CAP_NAME) -> Capability:
    return Capability(
        name=name,
        description=f"Capability {name}",
        requires_network=False,
        effect=EffectType.GENERATE,
        requires_confirmation=False,
    )


def _make_registration(
    capability: Capability,
    executor: Any,
    agent_id_str: str,
) -> CapabilityRegistration:
    return CapabilityRegistration(
        capability=capability,
        executor_kind=ExecutorKind.AGENT,
        executor_id=agent_id_str,
        executor=executor,
    )


def _make_precondition(agent_id_str: str) -> ExecutionPrecondition:
    return ExecutionPrecondition(
        kind=PreconditionKind.EXISTING_RESOURCE,
        resource_id=agent_id_str,
        governed_registration_id="reg-1",
        expected_generation=GENERATION_INITIAL,
    )


def _make_decision(registration: CapabilityRegistration) -> ResourceBindingDecision:
    return ResourceBindingDecision(
        capability=registration.capability.name,
        registration=registration,
        available=True,
        reason="eligible",
        registered=True,
        rrm_eligible=True,
        binding_healthy=True,
        selected_binding="agent:" + registration.executor_id,
        binding_identity=registration.binding_identity,
        execution_preconditions=(
            _make_precondition(registration.executor_id),
        ),
    )


def _make_service(
    decision: ResourceBindingDecision,
    orchestrator: CanonicalAgentOrchestrator,
):
    mission = _make_mission()
    service = CapabilityExecutionService(
        mission_engine=_FakeMissionEngine(mission),
        constitution=_FakeConstitution(),
        capability_router=MagicMock(),
        registry=MagicMock(),
        agent_orchestrator=orchestrator,
        provider_manager=MagicMock(),
        knowledge_pipeline=_FakeKnowledgePipeline(),
        event_publisher=_FakeEventPublisher(),
        idempotency_store=_FakeIdempotencyStore(),
        resource_authority=_StubAuthority(_FakeRRM(), decision),
    )
    return service, mission


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Test A — exact A remains current -> A executes once
# ---------------------------------------------------------------------------

class TestAExactAgentExecutes(unittest.TestCase):
    def test_a_exact_a_current_executes_once(self):
        a = _TestAgent("agent-a", label="A")
        orchestrator = _RecordingAgentOrchestrator()
        orchestrator.register(a)
        reg = _make_registration(_make_capability(), a, str(a.agent_id))
        decision = _make_decision(reg)
        service, mission = _make_service(decision, orchestrator)

        outcome = _run(service.execute(mission.id, CAP_NAME))

        self.assertTrue(outcome.result.success)
        self.assertEqual(a.execute_count, 1)
        self.assertEqual(outcome.result.output, "ok:A")
        # Dispatch requested the exact selected agent_id.
        self.assertEqual(orchestrator.last_agent_id, "agent-a")


# ---------------------------------------------------------------------------
# Test B — same agent_id replaced by B -> fail closed
# ---------------------------------------------------------------------------

class TestBSubstitutionFailsClosed(unittest.TestCase):
    def test_b_same_id_replaced_fails_closed(self):
        a = _TestAgent("agent-a", label="A")
        b = _TestAgent("agent-a", label="B", capability_names=(CAP_NAME,))
        orchestrator = CanonicalAgentOrchestrator()
        orchestrator.register(a)
        # Stroke the defect: the same agent_id now maps to B.
        orchestrator.register(b)
        reg = _make_registration(_make_capability(), a, "agent-a")
        decision = _make_decision(reg)
        service, mission = _make_service(decision, orchestrator)

        outcome = _run(service.execute(mission.id, CAP_NAME))

        self.assertFalse(outcome.result.success)
        self.assertEqual(outcome.result.error_code, ErrorCode.CAPABILITY_UNAVAILABLE)
        self.assertEqual(
            outcome.result.metadata.get("reason"),
            "agent_identity_mismatch",
        )
        self.assertEqual(a.execute_count, 0)
        self.assertEqual(b.execute_count, 0)


# ---------------------------------------------------------------------------
# Test C — outer CapabilityRegistration identity preserved
# ---------------------------------------------------------------------------

class TestCOuterRegistrationIdentity(unittest.TestCase):
    def test_c_exact_selected_registration_executor_flows_to_dispatch(self):
        a = _TestAgent("agent-a", label="A")
        orchestrator = _RecordingAgentOrchestrator()
        orchestrator.register(a)
        reg = _make_registration(_make_capability(), a, str(a.agent_id))
        decision = _make_decision(reg)
        service, mission = _make_service(decision, orchestrator)

        outcome = _run(service.execute(mission.id, CAP_NAME))

        self.assertTrue(outcome.result.success)
        # The exact selected CapabilityRegistration object (the one built and
        # returned by resolve) is the object whose executor flows to dispatch.
        self.assertIs(decision.registration, reg)
        self.assertIs(orchestrator.last_expected_executor, reg.executor)
        self.assertIs(orchestrator.last_expected_executor, a)
        self.assertEqual(a.execute_count, 1)


# ---------------------------------------------------------------------------
# Test D — no fallback on identity mismatch
# ---------------------------------------------------------------------------

class TestDNoFallback(unittest.TestCase):
    def test_d_no_fallback_on_substitution(self):
        a = _TestAgent("agent-a", label="A")
        b = _TestAgent("agent-a", label="B", capability_names=(CAP_NAME,))
        orchestrator = CanonicalAgentOrchestrator()
        orchestrator.register(a)
        orchestrator.register(b)  # registry now holds only B under the id
        reg = _make_registration(_make_capability(), a, "agent-a")
        decision = _make_decision(reg)
        service, mission = _make_service(decision, orchestrator)

        outcome = _run(service.execute(mission.id, CAP_NAME))

        self.assertFalse(outcome.result.success)
        self.assertEqual(outcome.result.error_code, ErrorCode.CAPABILITY_UNAVAILABLE)
        self.assertEqual(outcome.result.metadata.get("reason"), "agent_identity_mismatch")
        self.assertEqual(len(orchestrator.agents), 1)  # B occupies the id
        self.assertEqual(a.execute_count, 0)
        self.assertEqual(b.execute_count, 0)
        # No alternate executor was consulted/executed.
        for agent in orchestrator.agents:
            self.assertEqual(agent.execute_count, 0)


# ---------------------------------------------------------------------------
# Test E — same-data different-object rejected (identity, not equality)
# ---------------------------------------------------------------------------

class TestESameDataDifferentObject(unittest.TestCase):
    def test_e_same_data_different_object_rejected(self):
        a1 = _TestAgent("agent-a", capability_names=(CAP_NAME,), label="same")
        a2 = _TestAgent("agent-a", capability_names=(CAP_NAME,), label="same")
        # Identical logical data; distinct object identities.
        self.assertEqual(str(a1.agent_id), str(a2.agent_id))
        self.assertEqual(
            [c.name for c in a1.capabilities],
            [c.name for c in a2.capabilities],
        )
        self.assertIsNot(a1, a2)

        orchestrator = CanonicalAgentOrchestrator()
        orchestrator.register(a1)
        orchestrator.register(a2)  # store now resolves a2 for the same id
        reg = _make_registration(_make_capability(), a1, "agent-a")
        decision = _make_decision(reg)
        service, mission = _make_service(decision, orchestrator)

        outcome = _run(service.execute(mission.id, CAP_NAME))

        self.assertFalse(outcome.result.success)
        self.assertEqual(outcome.result.error_code, ErrorCode.CAPABILITY_UNAVAILABLE)
        self.assertEqual(outcome.result.metadata.get("reason"), "agent_identity_mismatch")
        self.assertEqual(a1.execute_count, 0)
        self.assertEqual(a2.execute_count, 0)


# ---------------------------------------------------------------------------
# Test F — liveness/eligibility preserved when exact executor present
# ---------------------------------------------------------------------------

class TestFLivenessPreserved(unittest.TestCase):
    def test_f_ineligible_agent_still_rejected(self):
        a = _TestAgent("agent-a", capability_names=("other.capability",))
        orchestrator = CanonicalAgentOrchestrator()
        orchestrator.register(a)
        reg = _make_registration(_make_capability(), a, str(a.agent_id))
        decision = _make_decision(reg)
        service, mission = _make_service(decision, orchestrator)

        outcome = _run(service.execute(mission.id, CAP_NAME))

        # Exact expected executor is present and identical, but it is not
        # eligible for the requested capability: identity repair must NOT
        # bypass the eligibility/liveness checks.
        self.assertFalse(outcome.result.success)
        self.assertEqual(outcome.result.error_code, ErrorCode.CAPABILITY_UNAVAILABLE)
        self.assertIsNone(outcome.result.metadata.get("reason"))
        self.assertEqual(a.execute_count, 0)


if __name__ == "__main__":
    unittest.main()