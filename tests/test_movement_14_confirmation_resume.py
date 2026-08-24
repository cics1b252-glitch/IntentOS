"""Movement 14 — Canonical Mission Confirmation / Resume convergence.

Proves the target invariant:
    CREATED -> RESOURCE RESOLVED -> AUTH PASSED -> ACTION REQUIRES CONFIRMATION
    -> WAITING_CONFIRMATION -> VALID TYPED USER CONFIRMATION
    -> SAME MISSION RESUMES -> SAME AUTHORIZED/REVALIDATED BINDING CONTEXT
    -> CONTROLLED EXECUTION -> VERIFICATION -> COMPLETION GATE -> COMPLETED

Forbidden shortcuts verified here: confirmation == authorization,
confirmation == completion, resume == new Mission, provider text == verification,
and any lexical shortcut ("sim", "confirmo", "pode", "ok", ...) bypassing the
typed Mission confirmation state.
"""

from __future__ import annotations

import types

import pytest

from intent_kernel.adapters import InMemoryMissionStoreAdapter
from intent_kernel.application.confirmation_service import (
    CanonicalConfirmationService,
    ConfirmationSubmission,
)
from intent_kernel.application.mission_engine import (
    MissionCompletionEvidenceError,
    MissionEngine,
)
from intent_kernel.contracts import MissionContext, MissionId, MissionStatus
from intent_kernel.runtime import MissionRuntime
from intent_kernel.runtime.models import (
    ActionContract,
    ConfirmationState,
    MissionRuntimeState,
    RuntimeNode,
    RuntimeNodeState,
    SideEffectLevel,
    VerificationStatus,
)
from intent_kernel.runtime.verification import MissionCompletionDecision
from product_bridge import ProductBridge

MISSION_MESSAGE = "Crie e envie um e-mail."
MISSION_PERMISSIONS = ["email.send"]


class _ConstitutionAllow:
    """Mock constitution that always allows — for testing non-constitution gate steps."""
    async def evaluate(self, action_type, payload, context=None):
        class _V:
            allowed = True
            decision = type("D", (), {"value": "ALLOW"})()
            metadata = {}
        return _V()


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv("INTENTOS_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return ProductBridge()


@pytest.fixture
def runtime_stack():
    engine = MissionEngine(InMemoryMissionStoreAdapter())
    runtime = MissionRuntime(mission_engine=engine, constitution=_ConstitutionAllow())
    service = CanonicalConfirmationService(
        engine, runtime, confirmation_ttl_seconds=300
    )
    return engine, runtime, service


def _counting_executor(bridge, monkeypatch):
    original = bridge.components.mission_runtime.executor.execute
    counts = {"executor": 0}

    async def counted(*args, **kwargs):
        counts["executor"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(
        bridge.components.mission_runtime.executor, "execute", counted
    )
    return counts


async def _open_waiting(bridge, session_id="s", message=MISSION_MESSAGE):
    response = await bridge.dispatch({
        "action": "chat",
        "message": message,
        "session_id": session_id,
        "authorized_permissions": list(MISSION_PERMISSIONS),
    })
    assert response["status"] == "WAITING_CONFIRMATION"
    assert response["mission_id"] is not None
    assert response["runtime_status"] == "WAITING_USER_CONFIRMATION"
    conf = response["confirmation"]
    assert conf is not None
    assert conf["state"] == "WAITING_CONFIRMATION"
    assert conf["confirmation_id"]
    return response, conf


def _confirm_params(response, conf, session_id="s", *, approved=True, token=None, mission_id=None):
    return {
        "action": "confirm",
        "params": {
            "mission_id": mission_id or response["mission_id"],
            "confirmation_id": conf["confirmation_id"],
            "approved": approved,
            "session_id": session_id,
            "project_id": "GLOBAL",
            "confirmation_token": token if token is not None else conf["confirmation_token"],
        },
        "session_id": session_id,
    }


async def _pending_runtime(runtime_stack):
    """Create a WAITING_CONFIRMATION Mission on a runtime stack."""
    engine, runtime, _service = runtime_stack
    mission = await engine.create(
        "Send email", context=MissionContext(session_id="s1")
    )
    await engine.start(mission.id)
    contract = ActionContract(
        capability="test.echo",
        side_effect_level=SideEffectLevel.EXTERNAL_REVERSIBLE,
        confirmation_required=True,
        provenance={"tool_id": "synthetic-tool"},
        expected_output="echo",
    )
    instance = runtime.create_instance(
        str(mission.id),
        "ecc-plan",
        [RuntimeNode(capability="test.echo", action_contract=contract)],
    )
    instance = await runtime.run_mission(instance.runtime_id)
    assert instance.status is MissionRuntimeState.WAITING_USER_CONFIRMATION
    conf = runtime.get_pending_confirmation(str(mission.id))
    assert conf is not None
    return mission, instance, conf


async def _bind_and_confirm(runtime_stack, *, approved=True, session="s1"):
    engine, runtime, service = runtime_stack
    mission, instance, conf = await _pending_runtime(runtime_stack)
    service.bind_pending(
        confirmation_id=conf.confirmation_id,
        mission_id=str(mission.id),
        runtime_id=instance.runtime_id,
        action_id=conf.action_id,
        session_id=session,
        project_id="GLOBAL",
        confirmation_token="tok-1",
        authorization={"tool_id": "synthetic-tool"},
    )
    outcome = await service.submit(ConfirmationSubmission(
        mission_id=str(mission.id),
        confirmation_id=conf.confirmation_id,
        approved=approved,
        session_id=session,
        project_id="GLOBAL",
        confirmation_token="tok-1",
    ))
    return engine, runtime, service, mission, instance, conf, outcome


# ---------------------------------------------------------------------------
# A. WAITING -> zero executor calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_A_waiting_confirmation_never_executes(bridge, monkeypatch):
    counts = _counting_executor(bridge, monkeypatch)
    response, _conf = await _open_waiting(bridge, "A")
    assert response["status"] == "WAITING_CONFIRMATION"
    assert counts["executor"] == 0
    mission = await bridge.components.mission_engine.get(
        MissionId(response["mission_id"])
    )
    assert mission.status is MissionStatus.WAITING_FOR_DECISION


# ---------------------------------------------------------------------------
# B. Valid typed confirmation resumes the SAME Mission
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_B_valid_confirm_resumes_same_mission(bridge, monkeypatch):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "B")
    mission_id = response["mission_id"]
    runtime_id = response["runtime_id"]
    r2 = await bridge.dispatch(_confirm_params(response, conf, "B"))
    assert r2["status"] == "COMPLETED"
    assert r2["mission_id"] == mission_id
    assert r2["runtime_id"] == runtime_id
    assert counts["executor"] == 1
    mission = await bridge.components.mission_engine.get(MissionId(mission_id))
    assert mission.status is MissionStatus.COMPLETED


# ---------------------------------------------------------------------------
# C. Exact binding revalidates and executes exactly once
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_C_wrong_token_fails_closed_then_correct_binding_executes_once(
    bridge, monkeypatch
):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "C")
    r_wrong = await bridge.dispatch(
        _confirm_params(response, conf, "C", token="wrong-token")
    )
    assert r_wrong["status"] != "COMPLETED"
    assert counts["executor"] == 0
    r_ok = await bridge.dispatch(_confirm_params(response, conf, "C"))
    assert r_ok["status"] == "COMPLETED"
    assert counts["executor"] == 1


# ---------------------------------------------------------------------------
# D. Rejection -> zero executor calls, Mission CANCELLED
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_D_rejection_never_executes_and_cancels_mission(bridge, monkeypatch):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "D")
    r2 = await bridge.dispatch(
        _confirm_params(response, conf, "D", approved=False)
    )
    assert (r2["confirm"] or {}).get("state") == "REJECTED"
    assert counts["executor"] == 0
    mission = await bridge.components.mission_engine.get(
        MissionId(response["mission_id"])
    )
    assert mission.status is MissionStatus.CANCELLED


# ---------------------------------------------------------------------------
# E. Ambiguous / malformed confirmation -> zero executor calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_E_ambiguous_confirmation_never_executes(bridge, monkeypatch):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "E")
    r2 = await bridge.dispatch({
        "action": "confirm",
        "params": {
            "mission_id": response["mission_id"],
            "confirmation_id": conf["confirmation_id"],
            "approved": "talvez",
            "session_id": "E",
        },
        "session_id": "E",
    })
    assert (r2["confirm"] or {}).get("error") == "invalid_confirmation_request"
    assert counts["executor"] == 0
    mission = await bridge.components.mission_engine.get(
        MissionId(response["mission_id"])
    )
    assert mission.status is MissionStatus.WAITING_FOR_DECISION


# ---------------------------------------------------------------------------
# F. Wrong Mission binding -> zero executor calls
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_F_wrong_mission_never_executes(bridge, monkeypatch):
    counts = _counting_executor(bridge, monkeypatch)
    response_a, conf_a = await _open_waiting(bridge, "F-a")
    response_b, _conf_b = await _open_waiting(bridge, "F-b")
    r2 = await bridge.dispatch(
        _confirm_params(response_a, conf_a, "F-a", mission_id=response_b["mission_id"])
    )
    assert (r2["confirm"] or {}).get("reason") == "mission_mismatch"
    assert counts["executor"] == 0
    mission_b = await bridge.components.mission_engine.get(
        MissionId(response_b["mission_id"])
    )
    assert mission_b.status is MissionStatus.WAITING_FOR_DECISION


# ---------------------------------------------------------------------------
# G. Replay -> no duplicate execution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_G_replay_never_duplicates_execution(bridge, monkeypatch):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "G")
    r2 = await bridge.dispatch(_confirm_params(response, conf, "G"))
    assert r2["status"] == "COMPLETED"
    assert counts["executor"] == 1
    r3 = await bridge.dispatch(_confirm_params(response, conf, "G"))
    assert r3["status"] != "COMPLETED"
    assert counts["executor"] == 1
    mission = await bridge.components.mission_engine.get(
        MissionId(response["mission_id"])
    )
    assert mission.status is MissionStatus.COMPLETED


# ---------------------------------------------------------------------------
# H. Binding replaced while waiting -> never executes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_H_binding_replaced_while_waiting_never_executes(bridge, monkeypatch):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "H")
    instance = bridge.components.mission_runtime.get_instance(
        response["runtime_id"]
    )
    node = next(iter(instance.nodes.values()))
    node.action_contract.action_id = "act_replaced_while_waiting"
    r2 = await bridge.dispatch(_confirm_params(response, conf, "H"))
    assert (r2["confirm"] or {}).get("reason") == "binding_invalid"
    assert counts["executor"] == 0
    mission = await bridge.components.mission_engine.get(
        MissionId(response["mission_id"])
    )
    assert mission.status is MissionStatus.WAITING_FOR_DECISION


# ---------------------------------------------------------------------------
# I. Binding removed while waiting -> fail closed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_I_binding_removed_while_waiting_fails_closed(bridge, monkeypatch):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "I")
    instance = bridge.components.mission_runtime.get_instance(
        response["runtime_id"]
    )
    instance.nodes.clear()
    instance.pending_nodes.clear()
    r2 = await bridge.dispatch(_confirm_params(response, conf, "I"))
    assert (r2["confirm"] or {}).get("reason") == "binding_invalid"
    assert counts["executor"] == 0


# ---------------------------------------------------------------------------
# J. RRM unavailable while waiting -> fail closed (no execution)
# ---------------------------------------------------------------------------

class _IneligibleAgentRRM:
    def get_agent(self, agent_id):
        return types.SimpleNamespace(is_eligible=False)

    def get_environment(self, env_id):
        return None


@pytest.mark.asyncio
async def test_J_rrm_unavailable_on_resume_fails_closed():
    engine = MissionEngine(InMemoryMissionStoreAdapter())
    runtime = MissionRuntime(mission_engine=engine, rrm_service=_IneligibleAgentRRM(), constitution=_ConstitutionAllow())
    service = CanonicalConfirmationService(engine, runtime, confirmation_ttl_seconds=300)
    mission, instance, conf = await _pending_runtime((engine, runtime, service))
    service.bind_pending(
        confirmation_id=conf.confirmation_id,
        mission_id=str(mission.id),
        runtime_id=instance.runtime_id,
        action_id=conf.action_id,
        session_id="s1",
        project_id="GLOBAL",
        confirmation_token="tok-1",
        authorization={"tool_id": "synthetic-tool"},
    )
    outcome = await service.submit(ConfirmationSubmission(
        mission_id=str(mission.id),
        confirmation_id=conf.confirmation_id,
        approved=True,
        session_id="s1",
        project_id="GLOBAL",
        confirmation_token="tok-1",
    ))
    assert outcome.state is ConfirmationState.CONFIRMED
    resumed = await runtime.run_mission(outcome.runtime_id)
    assert resumed.status is MissionRuntimeState.WAITING_RESOURCE
    assert len(resumed.completed_nodes) == 0
    node = next(iter(resumed.nodes.values()))
    assert node.attempt_count == 0
    mission_after = await engine.get(mission.id)
    assert mission_after.status is MissionStatus.WAITING_FOR_INFORMATION


# ---------------------------------------------------------------------------
# K. Binding unhealthy while waiting -> fail closed (no execution)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_K_unhealthy_binding_on_resume_fails_closed(bridge, monkeypatch):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "K")
    requirement = bridge.components.confirmation_service.get_confirmation(
        conf["confirmation_id"]
    )
    requirement.provenance["authorization"]["candidate"]["health"] = "UNAVAILABLE"
    r2 = await bridge.dispatch(_confirm_params(response, conf, "K"))
    assert r2["status"] == "AUTHORIZATION_REQUIRED"
    assert counts["executor"] == 0
    requirement_after = bridge.components.confirmation_service.get_confirmation(
        conf["confirmation_id"]
    )
    assert requirement_after.state is ConfirmationState.STALE


# ---------------------------------------------------------------------------
# L. Authorization revoked while waiting -> no execution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_L_authorization_revoked_on_resume_never_executes(bridge, monkeypatch):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "L")
    requirement = bridge.components.confirmation_service.get_confirmation(
        conf["confirmation_id"]
    )
    requirement.provenance["authorization"]["candidate"]["authorization_status"] = "REVOKED"
    r2 = await bridge.dispatch(_confirm_params(response, conf, "L"))
    assert r2["status"] == "AUTHORIZATION_REQUIRED"
    assert counts["executor"] == 0
    mission = await bridge.components.mission_engine.get(
        MissionId(response["mission_id"])
    )
    assert mission.status is MissionStatus.WAITING_FOR_DECISION


# ---------------------------------------------------------------------------
# M. Provider disappears while waiting -> no provider invocation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_M_no_provider_invocation_on_resume(bridge, monkeypatch):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "M")
    r2 = await bridge.dispatch(_confirm_params(response, conf, "M"))
    assert r2["status"] == "COMPLETED"
    assert counts["executor"] == 1
    assert r2["provider_called"] is False
    assert bridge.components.provider_manager.last_used is None


# ---------------------------------------------------------------------------
# N. Provider/tool replaced while waiting -> replacement cannot inherit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_N_replaced_tool_binding_cannot_inherit(bridge, monkeypatch):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "N")
    instance = bridge.components.mission_runtime.get_instance(
        response["runtime_id"]
    )
    node = next(iter(instance.nodes.values()))
    node.action_contract.provenance["tool_id"] = "replacement-tool"
    r2 = await bridge.dispatch(_confirm_params(response, conf, "N"))
    assert (r2["confirm"] or {}).get("reason") == "binding_invalid"
    assert counts["executor"] == 0


# ---------------------------------------------------------------------------
# O. Executor succeeds but verification fails -> not completed
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_O_verification_failure_never_completes(runtime_stack):
    engine, runtime, service = runtime_stack
    mission, instance, conf = await _pending_runtime(runtime_stack)
    node = next(iter(instance.nodes.values()))
    node.action_contract.expected_output = "magic-output"
    service.bind_pending(
        confirmation_id=conf.confirmation_id,
        mission_id=str(mission.id),
        runtime_id=instance.runtime_id,
        action_id=conf.action_id,
        session_id="s1",
        project_id="GLOBAL",
        confirmation_token="tok-1",
        authorization={"tool_id": "synthetic-tool"},
    )
    outcome = await service.submit(ConfirmationSubmission(
        mission_id=str(mission.id),
        confirmation_id=conf.confirmation_id,
        approved=True,
        session_id="s1",
        project_id="GLOBAL",
        confirmation_token="tok-1",
    ))
    assert outcome.state is ConfirmationState.CONFIRMED
    resumed = await runtime.run_mission(outcome.runtime_id)
    assert resumed.status is MissionRuntimeState.FAILED
    assert resumed.verification_status is not VerificationStatus.VERIFIED_SUCCESS
    mission_after = await engine.get(mission.id)
    assert mission_after.status is not MissionStatus.COMPLETED
    assert mission_after.status is MissionStatus.FAILED_RECOVERABLE


# ---------------------------------------------------------------------------
# P. Verification missing (inconclusive) -> not completed
# ---------------------------------------------------------------------------

class _InconclusiveVerifier:
    async def verify(self, action, result):
        return VerificationStatus.INCONCLUSIVE


@pytest.mark.asyncio
async def test_P_missing_verification_never_completes(runtime_stack):
    engine, runtime, service = runtime_stack
    runtime.verification_gate._exact_verifier = _InconclusiveVerifier()
    mission, instance, conf = await _pending_runtime(runtime_stack)
    service.bind_pending(
        confirmation_id=conf.confirmation_id,
        mission_id=str(mission.id),
        runtime_id=instance.runtime_id,
        action_id=conf.action_id,
        session_id="s1",
        project_id="GLOBAL",
        confirmation_token="tok-1",
        authorization={"tool_id": "synthetic-tool"},
    )
    outcome = await service.submit(ConfirmationSubmission(
        mission_id=str(mission.id),
        confirmation_id=conf.confirmation_id,
        approved=True,
        session_id="s1",
        project_id="GLOBAL",
        confirmation_token="tok-1",
    ))
    resumed = await runtime.run_mission(outcome.runtime_id)
    assert resumed.status is MissionRuntimeState.FAILED
    mission_after = await engine.get(mission.id)
    assert mission_after.status is not MissionStatus.COMPLETED


# ---------------------------------------------------------------------------
# Q. Verified execution -> MissionCompletionGate can complete
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_Q_verified_execution_completes_via_completion_gate(bridge, monkeypatch):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "Q")
    r2 = await bridge.dispatch(_confirm_params(response, conf, "Q"))
    assert r2["status"] == "COMPLETED"
    assert r2["completion_authority"] == "MissionCompletionGate"
    assert r2["verification_status"] == "VERIFIED_SUCCESS"
    assert counts["executor"] == 1
    instance = bridge.components.mission_runtime.get_instance(
        response["runtime_id"]
    )
    assert instance.completion_evidence


# ---------------------------------------------------------------------------
# R. Forged completion evidence -> rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_R_forged_completion_evidence_rejected(runtime_stack):
    engine, _runtime, _service = runtime_stack
    mission = await engine.create("Send email", context=MissionContext(session_id="r"))
    await engine.start(mission.id)
    forged = MissionCompletionDecision(
        mission_id=str(mission.id),
        allowed=True,
        execution_evidence=("fake-exec",),
        verification_evidence=("fake-verif",),
        completion_evidence=("fake-completion",),
    )
    with pytest.raises(MissionCompletionEvidenceError):
        await engine.complete(
            mission.id,
            completion_decision=forged,
            output="fake",
        )
    mission_after = await engine.get(mission.id)
    assert mission_after.status is MissionStatus.RUNNING


# ---------------------------------------------------------------------------
# S. Confirmation string without pending Mission -> ordinary conversation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phrase",
    [
        "sim",
        "confirmo",
        "pode",
        "pode executar",
        "ok",
        "continue",
        "talvez",
        "não",
        "cancele",
        "depois",
        "sim, mas não agora",
    ],
)
async def test_S_lexical_phrase_without_pending_mission_is_ordinary_conversation(
    bridge, monkeypatch, phrase
):
    counts = _counting_executor(bridge, monkeypatch)
    response = await bridge.dispatch({
        "action": "chat",
        "message": phrase,
        "session_id": "S-none",
    })
    assert counts["executor"] == 0
    assert response["status"] != "WAITING_CONFIRMATION"
    assert response["mission_id"] is None


# ---------------------------------------------------------------------------
# T. Confirmation for a completed Mission -> no second execution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_T_confirm_for_completed_mission_never_reexecutes(bridge, monkeypatch):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "T")
    r2 = await bridge.dispatch(_confirm_params(response, conf, "T"))
    assert r2["status"] == "COMPLETED"
    assert counts["executor"] == 1
    r3 = await bridge.dispatch(_confirm_params(response, conf, "T"))
    assert r3["status"] != "COMPLETED"
    assert counts["executor"] == 1
    assert (r3["confirm"] or {}).get("reason") in (
        "mission_already_completed",
        "confirmation_already_consumed",
    )
    instance = bridge.components.mission_runtime.get_instance(
        response["runtime_id"]
    )
    assert instance.status is MissionRuntimeState.COMPLETED


# ---------------------------------------------------------------------------
# Adversarial: no lexical shortcut bypasses typed Mission state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phrase",
    [
        "sim",
        "confirmo",
        "pode",
        "pode executar",
        "ok",
        "continue",
        "talvez",
        "não",
        "cancele",
        "depois",
        "sim, mas não agora",
    ],
)
async def test_adversarial_phrase_with_pending_mission_never_executes(
    bridge, monkeypatch, phrase
):
    counts = _counting_executor(bridge, monkeypatch)
    response, _conf = await _open_waiting(bridge, "ADV-pending")
    mission_id = response["mission_id"]
    r2 = await bridge.dispatch({
        "action": "chat",
        "message": phrase,
        "session_id": "ADV-pending",
    })
    assert counts["executor"] == 0
    assert r2["status"] != "COMPLETED"
    mission = await bridge.components.mission_engine.get(MissionId(mission_id))
    assert mission.status is MissionStatus.WAITING_FOR_DECISION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phrase",
    [
        "sim",
        "confirmo",
        "pode executar",
        "ok",
        "continue",
        "não",
        "cancele",
        "sim, mas não agora",
    ],
)
async def test_adversarial_phrase_does_not_cross_sessions(
    bridge, monkeypatch, phrase
):
    counts = _counting_executor(bridge, monkeypatch)
    response, _conf = await _open_waiting(bridge, "ADV-owner")
    r2 = await bridge.dispatch({
        "action": "chat",
        "message": phrase,
        "session_id": "ADV-other",
    })
    assert counts["executor"] == 0
    mission = await bridge.components.mission_engine.get(
        MissionId(response["mission_id"])
    )
    assert mission.status is MissionStatus.WAITING_FOR_DECISION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phrase",
    ["sim", "pode executar", "continue", "ok", "não"],
)
async def test_adversarial_phrase_after_completion_never_reexecutes(
    bridge, monkeypatch, phrase
):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "ADV-done")
    r2 = await bridge.dispatch(_confirm_params(response, conf, "ADV-done"))
    assert r2["status"] == "COMPLETED"
    assert counts["executor"] == 1
    r3 = await bridge.dispatch({
        "action": "chat",
        "message": phrase,
        "session_id": "ADV-done",
    })
    assert counts["executor"] == 1
    assert r3["status"] != "COMPLETED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phrase",
    ["sim", "confirmo", "pode", "continue", "ok"],
)
async def test_adversarial_phrase_against_cancelled_mission_never_executes(
    bridge, monkeypatch, phrase
):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "ADV-cancelled")
    r_reject = await bridge.dispatch(
        _confirm_params(response, conf, "ADV-cancelled", approved=False)
    )
    assert (r_reject["confirm"] or {}).get("state") == "REJECTED"
    r2 = await bridge.dispatch({
        "action": "chat",
        "message": phrase,
        "session_id": "ADV-cancelled",
    })
    assert counts["executor"] == 0
    mission = await bridge.components.mission_engine.get(
        MissionId(response["mission_id"])
    )
    assert mission.status is MissionStatus.CANCELLED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phrase",
    ["sim", "confirmo", "ok", "continue", "sim, mas não agora"],
)
async def test_adversarial_phrase_against_expired_confirmation_never_executes(
    bridge, monkeypatch, phrase
):
    counts = _counting_executor(bridge, monkeypatch)
    response, conf = await _open_waiting(bridge, "ADV-expired")
    requirement = bridge.components.confirmation_service.get_confirmation(
        conf["confirmation_id"]
    )
    requirement.expires_at = "2000-01-01T00:00:00Z"
    r2 = await bridge.dispatch({
        "action": "chat",
        "message": phrase,
        "session_id": "ADV-expired",
    })
    assert counts["executor"] == 0
    r_typed = await bridge.dispatch(_confirm_params(response, conf, "ADV-expired"))
    assert (r_typed["confirm"] or {}).get("reason") == "confirmation_expired"
    assert counts["executor"] == 0


# ---------------------------------------------------------------------------
# Service-level invariants
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expired_confirmation_is_rejected_without_execution(runtime_stack):
    engine, runtime, service = runtime_stack
    mission, instance, conf = await _pending_runtime(runtime_stack)
    service.bind_pending(
        confirmation_id=conf.confirmation_id,
        mission_id=str(mission.id),
        runtime_id=instance.runtime_id,
        action_id=conf.action_id,
        session_id="s1",
        project_id="GLOBAL",
        confirmation_token="tok-1",
        authorization={"tool_id": "synthetic-tool"},
    )
    conf.expires_at = "2000-01-01T00:00:00Z"
    outcome = await service.submit(ConfirmationSubmission(
        mission_id=str(mission.id),
        confirmation_id=conf.confirmation_id,
        approved=True,
        session_id="s1",
        project_id="GLOBAL",
        confirmation_token="tok-1",
    ))
    assert outcome.state is ConfirmationState.EXPIRED
    assert outcome.accepted is False
    assert conf.state is ConfirmationState.EXPIRED
    resumed = await runtime.run_mission(instance.runtime_id)
    assert resumed.status is MissionRuntimeState.WAITING_USER_CONFIRMATION


@pytest.mark.asyncio
async def test_rejection_cancels_runtime_instance(runtime_stack):
    engine, runtime, service = runtime_stack
    mission, instance, conf = await _pending_runtime(runtime_stack)
    service.bind_pending(
        confirmation_id=conf.confirmation_id,
        mission_id=str(mission.id),
        runtime_id=instance.runtime_id,
        action_id=conf.action_id,
        session_id="s1",
        project_id="GLOBAL",
        confirmation_token="tok-1",
        authorization={"tool_id": "synthetic-tool"},
    )
    outcome = await service.submit(ConfirmationSubmission(
        mission_id=str(mission.id),
        confirmation_id=conf.confirmation_id,
        approved=False,
        session_id="s1",
        project_id="GLOBAL",
        confirmation_token="tok-1",
    ))
    assert outcome.state is ConfirmationState.REJECTED
    mission_after = await engine.get(mission.id)
    assert mission_after.status is MissionStatus.CANCELLED
    resumed = await runtime.run_mission(instance.runtime_id)
    assert resumed.status is MissionRuntimeState.CANCELLED
    assert len(resumed.completed_nodes) == 0


@pytest.mark.asyncio
async def test_consumed_confirmation_cannot_resume_again(runtime_stack):
    engine, runtime, service, mission, instance, conf, outcome = await _bind_and_confirm(
        runtime_stack
    )
    assert outcome.state is ConfirmationState.CONFIRMED
    resumed = await runtime.run_mission(instance.runtime_id)
    assert resumed.status is MissionRuntimeState.COMPLETED
    service.consume(conf.confirmation_id)
    second = await service.submit(ConfirmationSubmission(
        mission_id=str(mission.id),
        confirmation_id=conf.confirmation_id,
        approved=True,
        session_id="s1",
        project_id="GLOBAL",
        confirmation_token="tok-1",
    ))
    assert second.accepted is False
    assert second.state is ConfirmationState.STALE
    assert len(resumed.completed_nodes) == 1
