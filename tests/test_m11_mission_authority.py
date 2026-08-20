"""Movement 11.3 adversarial tests for canonical Mission authority."""

from __future__ import annotations

import inspect
import pytest

from intent_kernel.application import (
    KernelBuilder,
    MissionCompletionEvidenceError,
)
from intent_kernel.cognition.runtime import (
    CognitiveExecutionDecision,
    CognitiveExecutionMode,
)
from intent_kernel.contracts import MissionStatus
from intent_kernel.runtime import (
    ActionContract,
    MissionCompletionDecision,
    MissionRuntime,
    MissionRuntimeState,
    RuntimeNode,
    RuntimeNodeState,
    SideEffectLevel,
    VerificationStatus,
)
from intent_kernel.types import Domain, EpistemicStatus, IntentOutput, Mode
from product_bridge import ProductBridge


class _ConstitutionAllow:
    """Mock constitution that always allows — for testing non-constitution gate steps."""
    async def evaluate(self, action_type, payload, context=None):
        class _V:
            allowed = True
            decision = type("D", (), {"value": "ALLOW"})()
            metadata = {}
        return _V()


async def _running_mission(engine, objective: str = "controlled test"):
    mission = await engine.create(objective)
    return await engine.start(mission.id)


def _echo_node(
    node_id: str,
    value: str,
    *,
    expected: str | None = None,
    dependencies: list[str] | None = None,
) -> RuntimeNode:
    return RuntimeNode(
        node_id=node_id,
        capability="test.echo",
        dependencies=list(dependencies or []),
        action_contract=ActionContract(
            capability="test.echo",
            inputs_reference={"message": value},
            expected_output=value if expected is None else expected,
        ),
    )


@pytest.mark.asyncio
async def test_textual_done_cannot_complete_mission_without_gate_decision():
    engine = KernelBuilder().build().mission_engine
    mission = await _running_mission(engine, "provider says done")

    with pytest.raises(MissionCompletionEvidenceError):
        await engine.complete(mission.id, output="done")

    forged = MissionCompletionDecision(
        mission_id=str(mission.id),
        allowed=True,
        execution_evidence=({"claim": "attempted"},),
        verification_evidence=({"claim": "verified"},),
        completion_evidence=({"claim": "complete"},),
    )
    with pytest.raises(MissionCompletionEvidenceError):
        await engine.complete(mission.id, completion_decision=forged)

    stored = await engine.get(mission.id)
    assert stored is not None
    assert stored.status is MissionStatus.RUNNING


@pytest.mark.asyncio
async def test_executor_success_with_failed_verification_never_completes():
    engine = KernelBuilder().build().mission_engine
    mission = await _running_mission(engine)
    runtime = MissionRuntime(mission_engine=engine, constitution=_ConstitutionAllow())
    instance = runtime.create_instance(
        str(mission.id), "verification-failure",
        [_echo_node("wrong", "actual", expected="expected")],
    )

    result = await runtime.run_mission(instance.runtime_id)
    stored = await engine.get(mission.id)

    assert result.status is MissionRuntimeState.FAILED
    assert stored is not None
    assert stored.status is MissionStatus.FAILED_RECOVERABLE
    assert stored.status is not MissionStatus.COMPLETED


@pytest.mark.asyncio
async def test_missing_verification_evidence_fails_closed():
    engine = KernelBuilder().build().mission_engine
    mission = await _running_mission(engine)
    runtime = MissionRuntime(mission_engine=engine, constitution=_ConstitutionAllow())
    node = _echo_node("claimed", "done")
    node.state = RuntimeNodeState.SUCCEEDED
    node.attempt_count = 1
    node.result = "done"
    node.verification_result = VerificationStatus.VERIFIED_SUCCESS
    instance = runtime.create_instance(str(mission.id), "missing-evidence", [node])
    instance.pending_nodes.clear()
    instance.completed_nodes.append(node.node_id)

    decision = await runtime.completion_gate.decide(instance)

    assert decision.allowed is False
    assert decision.verification_evidence == ()
    assert any("no verified VerificationGate evidence" in item for item in decision.violations)
    with pytest.raises(MissionCompletionEvidenceError):
        await engine.complete(mission.id, completion_decision=decision)


@pytest.mark.asyncio
async def test_verified_runtime_completion_updates_canonical_lifecycle():
    engine = KernelBuilder().build().mission_engine
    mission = await _running_mission(engine)
    runtime = MissionRuntime(mission_engine=engine, constitution=_ConstitutionAllow())
    instance = runtime.create_instance(
        str(mission.id), "verified-completion", [_echo_node("verified", "done")]
    )

    result = await runtime.run_mission(
        instance.runtime_id, final_output_candidate="done"
    )
    stored = await engine.get(mission.id)

    assert result.status is MissionRuntimeState.COMPLETED
    assert result.completion_authority == "MissionCompletionGate"
    assert result.lifecycle_status == MissionStatus.COMPLETED.value
    assert result.completion_evidence
    assert stored is not None
    assert stored.status is MissionStatus.COMPLETED


@pytest.mark.asyncio
async def test_confirmation_wait_and_resume_remain_canonical_and_synthetic():
    engine = KernelBuilder().build().mission_engine
    mission = await _running_mission(engine)
    runtime = MissionRuntime(mission_engine=engine, constitution=_ConstitutionAllow())
    node = RuntimeNode(
        node_id="synthetic-confirmed",
        capability="test.echo",
        action_contract=ActionContract(
            capability="test.echo",
            inputs_reference={"message": "synthetic"},
            expected_output="synthetic",
            side_effect_level=SideEffectLevel.EXTERNAL_REVERSIBLE,
            confirmation_required=True,
        ),
    )
    instance = runtime.create_instance(str(mission.id), "confirmation", [node])

    waiting = await runtime.run_mission(instance.runtime_id)
    lifecycle_waiting = await engine.get(mission.id)
    assert waiting.status is MissionRuntimeState.WAITING_USER_CONFIRMATION
    assert lifecycle_waiting is not None
    assert lifecycle_waiting.status is MissionStatus.WAITING_FOR_DECISION
    assert runtime.executor._execution_history == {}

    confirmation = next(iter(runtime._confirmations.values()))
    runtime.submit_confirmation(confirmation.confirmation_id, approved=True)
    completed = await runtime.run_mission(instance.runtime_id)
    lifecycle_completed = await engine.get(mission.id)

    assert completed.status is MissionRuntimeState.COMPLETED
    assert lifecycle_completed is not None
    assert lifecycle_completed.status is MissionStatus.COMPLETED
    assert runtime.executor._execution_history


@pytest.mark.asyncio
async def test_partial_dag_cannot_complete_mission():
    engine = KernelBuilder().build().mission_engine
    mission = await _running_mission(engine)
    runtime = MissionRuntime(mission_engine=engine, constitution=_ConstitutionAllow())
    blocked_by_missing_dependency = _echo_node(
        "partial", "never", dependencies=["missing-required-step"]
    )
    instance = runtime.create_instance(
        str(mission.id), "partial-dag", [blocked_by_missing_dependency]
    )

    result = await runtime.run_mission(instance.runtime_id)
    stored = await engine.get(mission.id)

    assert result.status is MissionRuntimeState.RUNNING
    assert result.completed_nodes == []
    assert stored is not None
    assert stored.status is MissionStatus.RUNNING


@pytest.mark.asyncio
async def test_one_failed_required_step_prevents_completion():
    engine = KernelBuilder().build().mission_engine
    mission = await _running_mission(engine)
    runtime = MissionRuntime(mission_engine=engine, constitution=_ConstitutionAllow())
    nodes = [
        _echo_node("first", "ok"),
        _echo_node("required-failure", "observed", expected="required", dependencies=["first"]),
    ]
    instance = runtime.create_instance(str(mission.id), "required-failure", nodes)

    result = await runtime.run_mission(instance.runtime_id)
    stored = await engine.get(mission.id)

    assert result.status is MissionRuntimeState.FAILED
    assert "required-failure" in result.failed_nodes
    assert stored is not None
    assert stored.status is MissionStatus.FAILED_RECOVERABLE


@pytest.mark.asyncio
async def test_compatibility_execution_cannot_complete_canonical_lifecycle(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()

    result = await components.legacy_capability_executor.execute(
        "fin",
        {"text": "quero investir 5000", "domain": "finance"},
    )
    active = await components.mission_store.list_active()

    assert result.success is True
    assert result.metadata["compatibility_path_used"] is True
    assert result.metadata["completion_authority"] == "MissionCompletionGate"
    assert len(active) == 1
    assert active[0].status is MissionStatus.VERIFYING


@pytest.mark.asyncio
async def test_product_bridge_cannot_infer_mission_from_compatibility_text(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    bridge = ProductBridge()

    async def conversation(*_args, **_kwargs):
        return CognitiveExecutionDecision(
            mode=CognitiveExecutionMode.CONVERSATION,
            reason="compatibility characterization",
        )

    async def text_only(_message, context):
        context["mission_id"] = "33333333-3333-4333-8333-333333333333"
        context["intent_model"] = {"domain": "other"}
        return IntentOutput(
            text="done",
            mode=Mode.BASIC,
            domain=Domain.OTHER,
            confidence=1.0,
            epistemic_status=EpistemicStatus.FACT,
        )

    monkeypatch.setattr(
        bridge.components.cognitive_capability_runtime, "analyze", conversation
    )
    monkeypatch.setattr(bridge.kernel, "process", text_only)
    response = await bridge.dispatch({
        "action": "chat",
        "message": "compatibility response",
        "allow_compatibility_fallback": True,
    })

    assert response["text"] == "done"
    assert response["mission_id"] is None
    assert response["compatibility_dialogue_id"] == (
        "33333333-3333-4333-8333-333333333333"
    )
    assert response["compatibility_lifecycle"] == {
        "classification": "COMPATIBILITY_ONLY",
        "canonical_mission": False,
        "completion_authority": None,
    }
    session = bridge._load_session("product-alpha")
    assert session["compatibility_dialogue_id"] == (
        "33333333-3333-4333-8333-333333333333"
    )
    assert session["mission_lifecycle"]["classification"] == "COMPATIBILITY_ONLY"
    assert await bridge.components.mission_store.list_active() == []


@pytest.mark.asyncio
async def test_composed_mission_authorities_are_singletons_and_observable(tmp_path):
    components = KernelBuilder().with_pkb_path(tmp_path / "pkb").build()

    assert components.mission_runtime.mission_engine is components.mission_engine
    assert components.mission_service.mission_engine is components.mission_engine
    assert (
        components.mission_service.tool_authorization_gate
        is components.tool_authorization_gate
    )
    assert components.tool_authorization_gate is not None
    description = components.kernel.runtime_description
    assert description["mission_lifecycle_authority"] == "MissionEngine"
    assert description["mission_completion_authority"] == "MissionCompletionGate"
    assert description["tool_authorization_authority"] == "ToolAuthorizationGate"
    diagnostics = await components.mission_runtime.get_diagnostics()
    assert diagnostics["lifecycle_authority"] == "MissionEngine"
    assert diagnostics["completion_authority"] == "MissionCompletionGate"
    bridge_source = inspect.getsource(ProductBridge._run_controlled_mission)
    assert "mission_engine.create" not in bridge_source
    assert "mission_engine.start" not in bridge_source
    assert "mission_engine.pause" not in bridge_source
