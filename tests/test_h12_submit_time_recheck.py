"""H1.2 — Submit-Time Authorization Recheck.

Proves the invariant:
    INITIAL AUTHORIZATION != PERMANENT EXECUTION AUTHORITY

The recheck_authorization() mechanism must be called inside submit() so that
no historical authorization or user confirmation can override a current DENY.
"""

from __future__ import annotations

import pytest

from intent_kernel.adapters import InMemoryMissionStoreAdapter
from intent_kernel.application.confirmation_service import (
    CanonicalConfirmationService,
    ConfirmationSubmission,
)
from intent_kernel.application.mission_engine import MissionEngine
from intent_kernel.contracts import MissionContext, MissionId, MissionStatus
from intent_kernel.runtime import MissionRuntime
from intent_kernel.runtime.models import (
    ActionContract,
    ConfirmationState,
    MissionRuntimeState,
    RuntimeNode,
    SideEffectLevel,
)
from intent_kernel.tools.authorization import ToolAuthorizationGate
from intent_kernel.tools.models import (
    PermissionDecisionState,
    ToolAuthorizationDecisionState,
    ToolCandidate,
    ToolHealthStatus,
    ToolResource,
    ToolStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine_and_runtime():
    engine = MissionEngine(InMemoryMissionStoreAdapter())
    runtime = MissionRuntime(mission_engine=engine, constitution=_ConstitutionAllow())
    return engine, runtime


def _make_service(engine, runtime, gate=None):
    return CanonicalConfirmationService(
        engine, runtime, tool_authorization_gate=gate,
        confirmation_ttl_seconds=300,
    )


async def _pending_mission(engine, runtime):
    """Create a WAITING_CONFIRMATION Mission on a runtime stack."""
    mission = await engine.create("Test mission", context=MissionContext(session_id="s1"))
    await engine.start(mission.id)
    contract = ActionContract(
        capability="test.echo",
        side_effect_level=SideEffectLevel.EXTERNAL_REVERSIBLE,
        confirmation_required=True,
        provenance={"tool_id": "test-tool"},
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


def _bind_confirmation(service, conf, mission, instance, *, authorization=None):
    service.bind_pending(
        confirmation_id=conf.confirmation_id,
        mission_id=str(mission.id),
        runtime_id=instance.runtime_id,
        action_id=conf.action_id,
        session_id="s1",
        project_id="GLOBAL",
        confirmation_token="tok-1",
        authorization=authorization if authorization is not None else {"tool_id": "test-tool"},
    )


async def _submit(service, mission, conf, *, approved=True):
    return await service.submit(ConfirmationSubmission(
        mission_id=str(mission.id),
        confirmation_id=conf.confirmation_id,
        approved=approved,
        session_id="s1",
        project_id="GLOBAL",
        confirmation_token="tok-1",
    ))


class _ConstitutionAllow:
    """Mock constitution that always allows."""
    async def evaluate(self, action_type, payload, context=None):
        class _V:
            allowed = True
            decision = type("D", (), {"value": "ALLOW"})()
            metadata = {}
        return _V()

    def evaluate_action(self, payload):
        class _V:
            verdict = "ALLOW"
        return _V()


class _ConstitutionDeny:
    """Mock constitution that always denies."""
    async def evaluate(self, action_type, payload, context=None):
        class _V:
            allowed = False
            decision = type("D", (), {"value": "DENY"})()
            metadata = {}
        return _V()

    def evaluate_action(self, payload):
        class _V:
            verdict = "DENY"
        return _V()


def _allow_gate():
    return ToolAuthorizationGate(constitution=_ConstitutionAllow())


def _deny_gate():
    return ToolAuthorizationGate(constitution=_ConstitutionDeny())


# ---------------------------------------------------------------------------
# 1. Initial ALLOW + recheck ALLOW => execution proceeds
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recheck_allow_proceeds():
    engine, runtime = _make_engine_and_runtime()
    gate = _allow_gate()
    service = _make_service(engine, runtime, gate)
    mission, instance, conf = await _pending_mission(engine, runtime)
    _bind_confirmation(service, conf, mission, instance)
    outcome = await _submit(service, mission, conf)
    assert outcome.state is ConfirmationState.CONFIRMED
    assert outcome.accepted is True
    assert outcome.reason == "confirmed"


# ---------------------------------------------------------------------------
# 2. Initial ALLOW + recheck DENY => execution blocked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recheck_deny_blocks():
    engine, runtime = _make_engine_and_runtime()
    gate = _deny_gate()
    service = _make_service(engine, runtime, gate)
    mission, instance, conf = await _pending_mission(engine, runtime)
    _bind_confirmation(service, conf, mission, instance)
    outcome = await _submit(service, mission, conf)
    assert outcome.state is ConfirmationState.STALE
    assert outcome.accepted is False
    assert "authorization_revoked:DENY" in outcome.reason


# ---------------------------------------------------------------------------
# 3. Confirmation does not override a later DENY
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confirm_does_not_override_deny():
    engine, runtime = _make_engine_and_runtime()
    gate = _deny_gate()
    service = _make_service(engine, runtime, gate)
    mission, instance, conf = await _pending_mission(engine, runtime)
    _bind_confirmation(service, conf, mission, instance)
    outcome = await _submit(service, mission, conf, approved=True)
    assert outcome.state is ConfirmationState.STALE
    assert outcome.accepted is False
    # The confirmation was approved=True but DENY overrode it
    assert conf.approved is None  # state not changed to CONFIRMED


# ---------------------------------------------------------------------------
# 4. Non-executable recheck state => no execution
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recheck_request_permission_blocks():
    engine, runtime = _make_engine_and_runtime()

    # Gate that returns REQUEST_PERMISSION
    class _ConstitutionRequestPermission:
        async def evaluate(self, action_type, payload, context=None):
            class _V:
                allowed = False
                decision = type("D", (), {"value": "REQUEST_PERMISSION"})()
                metadata = {}
            return _V()
        def evaluate_action(self, payload):
            class _V:
                verdict = "ALLOW"  # constitution allows, but permission check returns REQUEST_PERMISSION
            return _V()

    gate = ToolAuthorizationGate(constitution=_ConstitutionRequestPermission())
    service = _make_service(engine, runtime, gate)
    mission, instance, conf = await _pending_mission(engine, runtime)
    _bind_confirmation(service, conf, mission, instance, authorization={
        "tool_id": "test-tool",
        "candidate": {
            "tool_id": "test-tool",
            "capability": "test.echo",
            "authorization_status": "NOT_CONFIGURED",
            "health": "HEALTHY",
        },
        "tool": {
            "tool_id": "test-tool",
            "capabilities": ["test.echo"],
            "status": "AVAILABLE",
            "required_permissions": [],
        },
    })
    outcome = await _submit(service, mission, conf)
    assert outcome.state is ConfirmationState.STALE
    assert outcome.accepted is False
    assert "authorization_revoked:REQUEST_PERMISSION" in outcome.reason


# ---------------------------------------------------------------------------
# 5. Provider/tool state change between initial authorization and submit
#    => recheck observes current state
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_revoked_between_auth_and_submit():
    engine, runtime = _make_engine_and_runtime()

    # Gate that denies because tool is REVOKED
    gate = _deny_gate()
    service = _make_service(engine, runtime, gate)
    mission, instance, conf = await _pending_mission(engine, runtime)

    # Initially bound with a valid tool
    _bind_confirmation(service, conf, mission, instance, authorization={
        "tool_id": "test-tool",
        "candidate": {
            "tool_id": "test-tool",
            "capability": "test.echo",
            "authorization_status": "GRANTED",
            "health": "HEALTHY",
        },
        "tool": {
            "tool_id": "test-tool",
            "capabilities": ["test.echo"],
            "status": "AVAILABLE",
            "required_permissions": [],
        },
    })

    # Tool is now revoked — recheck should observe this
    outcome = await _submit(service, mission, conf)
    assert outcome.state is ConfirmationState.STALE
    assert outcome.accepted is False


# ---------------------------------------------------------------------------
# 6. recheck_authorization() is actually called by submit()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recheck_is_called_by_submit():
    engine, runtime = _make_engine_and_runtime()
    gate = _allow_gate()
    service = _make_service(engine, runtime, gate)
    mission, instance, conf = await _pending_mission(engine, runtime)
    _bind_confirmation(service, conf, mission, instance)

    # Patch recheck_authorization to track calls
    original_recheck = service.recheck_authorization
    call_count = {"n": 0}

    async def tracked_recheck(c):
        call_count["n"] += 1
        return await original_recheck(c)

    service.recheck_authorization = tracked_recheck

    outcome = await _submit(service, mission, conf)
    assert call_count["n"] == 1
    assert outcome.state is ConfirmationState.CONFIRMED


# ---------------------------------------------------------------------------
# 7. No duplicate execution occurs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_duplicate_execution():
    engine, runtime = _make_engine_and_runtime()
    gate = _allow_gate()
    service = _make_service(engine, runtime, gate)
    mission, instance, conf = await _pending_mission(engine, runtime)
    _bind_confirmation(service, conf, mission, instance)

    # Submit once — should succeed
    outcome1 = await _submit(service, mission, conf)
    assert outcome1.state is ConfirmationState.CONFIRMED
    assert outcome1.accepted is True

    # Submit twice — second is a no-op (already CONFIRMED)
    outcome2 = await _submit(service, mission, conf)
    assert outcome2.state is ConfirmationState.CONFIRMED
    assert outcome2.accepted is False
    assert outcome2.reason == "confirmation_state:CONFIRMED"


# ---------------------------------------------------------------------------
# 8. Existing valid confirmation flow remains functional
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_valid_confirmation_flow_unchanged():
    engine, runtime = _make_engine_and_runtime()
    gate = _allow_gate()
    service = _make_service(engine, runtime, gate)
    mission, instance, conf = await _pending_mission(engine, runtime)
    _bind_confirmation(service, conf, mission, instance)

    outcome = await _submit(service, mission, conf)
    assert outcome.state is ConfirmationState.CONFIRMED
    assert outcome.accepted is True
    assert outcome.reason == "confirmed"
    assert outcome.mission_id == str(mission.id)
    assert outcome.confirmation_id == conf.confirmation_id

    # submit() validates and confirms; mission transitions to RUNNING
    # only when run_mission() is called (by _resume_confirmed in product_bridge)
    m = await engine.get(MissionId(str(mission.id)))
    assert m.status is MissionStatus.WAITING_FOR_DECISION


# ---------------------------------------------------------------------------
# 9. Existing non-confirmation flow remains functional
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rejection_still_works():
    engine, runtime = _make_engine_and_runtime()
    gate = _allow_gate()
    service = _make_service(engine, runtime, gate)
    mission, instance, conf = await _pending_mission(engine, runtime)
    _bind_confirmation(service, conf, mission, instance)

    outcome = await _submit(service, mission, conf, approved=False)
    assert outcome.state is ConfirmationState.REJECTED
    assert outcome.accepted is True
    assert outcome.reason == "rejected"

    m = await engine.get(MissionId(str(mission.id)))
    assert m.status is MissionStatus.CANCELLED


# ---------------------------------------------------------------------------
# 10. H1.1 default-DENY behavior remains intact
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_h11_default_deny_preserved():
    """ToolAuthorizationGate denies without constitution (H1.1-closure)."""
    gate = ToolAuthorizationGate()  # No constitution → DENY
    candidate = ToolCandidate(
        tool_id="t1",
        capability="test.echo",
        authorization_status=PermissionDecisionState.GRANTED,
        health=ToolHealthStatus.HEALTHY,
    )
    tool = ToolResource(
        tool_id="t1",
        capabilities=["test.echo"],
        status=ToolStatus.AVAILABLE,
    )
    decision = await gate.evaluate_tool(candidate, tool)
    assert decision is ToolAuthorizationDecisionState.DENY

    # Tool with REVOKED status => DENY (H1.1 fail-closed)
    tool_revoked = ToolResource(
        tool_id="t1",
        capabilities=["test.echo"],
        status=ToolStatus.REVOKED,
    )
    decision_revoked = await gate.evaluate_tool(candidate, tool_revoked)
    assert decision_revoked is ToolAuthorizationDecisionState.DENY


# ---------------------------------------------------------------------------
# 11. Recheck with no authorization bound => no-op (skip recheck)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_authorization_bound_skips_recheck():
    engine, runtime = _make_engine_and_runtime()
    gate = _deny_gate()  # Even a deny gate shouldn't block — no auth bound
    service = _make_service(engine, runtime, gate)
    mission, instance, conf = await _pending_mission(engine, runtime)
    # Bind with empty authorization => recheck sees empty auth, skips
    _bind_confirmation(service, conf, mission, instance, authorization={})
    outcome = await _submit(service, mission, conf)
    # Empty authorization => recheck_authorization returns (None, {})
    # => decision is None => passes the deny check => CONFIRMED
    assert outcome.state is ConfirmationState.CONFIRMED
    assert outcome.accepted is True


# ---------------------------------------------------------------------------
# 12. Recheck with no gate configured => no-op (skip recheck)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_gate_configured_skips_recheck():
    engine, runtime = _make_engine_and_runtime()
    service = _make_service(engine, runtime, gate=None)
    mission, instance, conf = await _pending_mission(engine, runtime)
    _bind_confirmation(service, conf, mission, instance)
    outcome = await _submit(service, mission, conf)
    # No gate => recheck returns (None, {}) => ALLOW path
    assert outcome.state is ConfirmationState.CONFIRMED
    assert outcome.accepted is True
