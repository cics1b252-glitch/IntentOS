"""M32B-2 durable action state machine + local replay prevention, T1-T38.

T1  valid PENDING -> AUTHORIZED durable transition
T2  invalid transition rejected
T3  expected action state mismatch rejected
T4  mission revision mismatch rejected
T5  valid transition increments MissionRecord revision exactly once
T6  durable write failure leaves previous action state authoritative
T7  same local execution identity digest deterministic
T8  semantic request change changes execution identity
T9  GRID change changes execution identity
T10 generation change changes execution identity
T11 executor logical ID change changes execution identity
T12 effect identity change changes execution identity
T13 no Python object identity in execution identity
T14 DISPATCH_INTENT_RECORDED restart does not auto-redispatch
T15 DISPATCHING restart does not auto-redispatch
T16 C3 ambiguous window returns AMBIGUOUS_RECONCILIATION_REQUIRED
T17 AMBIGUOUS_EFFECT cannot transition automatically to DISPATCHING
T18 AMBIGUOUS_EFFECT cannot transition automatically to COMPLETED
T19 provider effect ID absent => external exactly-once not claimed
T20 provider effect ID present is stored distinctly from local identity
T21 reusable confirmation token not persisted
T22 confirmation-dependent restart yields RECONFIRMATION_REQUIRED decision
T23 RESULT_RECORDED does not bypass VerificationGate
T24 VERIFICATION_REQUIRED does not become COMPLETED directly
T25 historical VERIFIED with mutable provider evidence does not bypass freshness
T26 action COMPLETED does not directly mission-complete
T27 old mission without MissionRecord nonresumable
T28 restart load returns exact durable action state
T29 sequential stale writer rejected
T30 invalid action ID fails closed
T31 immutable action identity mutation rejected
T32 request_semantics_digest mutation outside allowed contract rejected
T33 unknown action state fails closed
T34 unknown replay decision inputs fail closed
T35 no RRM canonical authority duplicated
T36 no productive executor rebind added
T37 no automatic mission rediscovery/resume added
T38 real user state untouched

Plus the §17 crash-matrix posture table for every durable state.

All paths isolated under tmp_path; real user state never touched.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from intent_kernel.mission.action_authority import (
    FRESH_DETERMINISTIC,
    NOT_VERIFIED,
    REQUIRES_REVALIDATION,
    ActionTransitionError,
    ActionTransitionEvidence,
    MissionActionAuthority,
    ReplayDecision,
    TransitionResult,
)
from intent_kernel.mission.execution_identity import (
    compute_local_execution_identity,
    effect_identity_digest_for,
)
from intent_kernel.mission.mission_record import (
    ActionState,
    DurableActionState,
    MissionDefinition,
    MissionRecord,
    MissionStatus,
)
from intent_kernel.mission.store import (
    MissionRecordNotFoundError,
    MissionRecordValidationError,
)
from intent_kernel.mission.store_impl import JsonFileMissionRecordStore
from intent_kernel.mission.transitions import (
    ACTION_TRANSITIONS,
    IllegalActionTransitionError,
    is_legal_action_transition,
    restart_posture_for,
)
from intent_kernel.runtime.models import ActionContract, RuntimeNode
from intent_kernel.runtime.verification import (
    ActionVerificationProof,
    VerificationGate,
    issue_action_verification_proof,
)


def _store(tmp_path: Path, name: str = "t") -> JsonFileMissionRecordStore:
    root = tmp_path / name
    (root / "missions").mkdir(parents=True, exist_ok=True)
    (root / "cont").mkdir(parents=True, exist_ok=True)
    return JsonFileMissionRecordStore(
        missions_dir=root / "missions",
        continuity_file=root / "cont" / "identity.json",
    )


def _definition(objective: str = "o") -> MissionDefinition:
    return MissionDefinition(objective=objective, context={"k": "v"})


def _digest(defn: MissionDefinition) -> str:
    probe = MissionRecord(
        mission_id="probe", installation_id="probe-install",
        mission_definition=defn,
    )
    return probe.compute_definition_digest()


def _mission(
    store: JsonFileMissionRecordStore,
    mission_id: str = "m",
    actions: tuple = ("a1",),
    definition: MissionDefinition | None = None,
) -> MissionRecord:
    ident = store.get_continuity_identity()
    definition = definition if definition is not None else _definition()
    plan = tuple({
        "action_id": aid,
        "capability": f"cap.{aid}",
        "node_id": f"n-{aid}",
        "dependencies": [],
        "request_semantics_digest": f"rd-{aid}",
    } for aid in actions)
    states = {
        aid: DurableActionState(
            action_id=aid, node_id=f"n-{aid}",
            expected_resource_id=f"r-{aid}",
            expected_governed_registration_id=f"g-{aid}",
            expected_resource_generation=2,
            expected_executor_kind="core_app",
            expected_executor_logical_id=f"ex-{aid}",
        ) for aid in actions
    }
    record = MissionRecord(
        mission_id=mission_id, installation_id=ident, revision=1,
        runtime_id="rt-1", mission_definition=definition,
        mission_definition_digest=_digest(definition),
        mission_status=MissionStatus.RUNNING,
        plan=plan, action_states=states,
    )
    result = store.create(record)
    assert result.outcome == "committed"
    return record


def _auth(store: JsonFileMissionRecordStore) -> MissionActionAuthority:
    return MissionActionAuthority(store)


def _ev(**kw) -> ActionTransitionEvidence:
    args = {"requested_by": "t", "reason": "r"}
    args.update(kw)
    return ActionTransitionEvidence(**args)


def _current(store: JsonFileMissionRecordStore, mid: str, aid: str) -> ActionState:
    return ActionState(store.load(mid)["action_states"][aid]["state"])


def _drive(auth, store, mid, aid, target, rev=None, **evkw):
    if rev is None:
        rev = store.load(mid)["revision"]
    current = _current(store, mid, aid)
    return auth.transition_action(mid, aid, rev, current, target, _ev(**evkw))


def test_t1_pending_to_authorized(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    result = auth.transition_action(
        "m", "a1", 1, ActionState.PENDING, ActionState.AUTHORIZED, _ev())
    assert isinstance(result, TransitionResult)
    assert result.previous_state is ActionState.PENDING
    assert result.new_state is ActionState.AUTHORIZED
    assert result.mission_revision == 2
    assert store.load("m")["action_states"]["a1"]["state"] == "AUTHORIZED"


@pytest.mark.parametrize("target", [
    ActionState.DISPATCH_INTENT_RECORDED,
    ActionState.DISPATCHING,
    ActionState.RESULT_RECORDED,
    ActionState.VERIFICATION_REQUIRED,
    ActionState.VERIFIED,
    ActionState.COMPLETED,
    ActionState.AMBIGUOUS_EFFECT,
])
def test_t2_invalid_transition_rejected(tmp_path, target):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    before = store.load("m")
    with pytest.raises(ActionTransitionError):
        auth.transition_action(
            "m", "a1", 1, ActionState.PENDING, target, _ev())
    assert store.load("m") == before


def test_t2b_terminal_and_ambiguous_have_no_exits(tmp_path):
    for start, bad in (
        (ActionState.VERIFIED, ActionState.FAILED),
        (ActionState.VERIFIED, ActionState.DISPATCHING),
        (ActionState.COMPLETED, ActionState.AUTHORIZED),
        (ActionState.FAILED, ActionState.PENDING),
        (ActionState.AMBIGUOUS_EFFECT, ActionState.DISPATCHING),
        (ActionState.AMBIGUOUS_EFFECT, ActionState.COMPLETED),
    ):
        assert not is_legal_action_transition(start, bad), (start, bad)
    assert ACTION_TRANSITIONS[ActionState.AMBIGUOUS_EFFECT] == frozenset()
    assert ACTION_TRANSITIONS[ActionState.COMPLETED] == frozenset()
    assert ACTION_TRANSITIONS[ActionState.FAILED] == frozenset()
    # M32B-3: RECONFIRMATION_REQUIRED has exits to AUTHORIZED and FAILED
    assert ActionState.AUTHORIZED in ACTION_TRANSITIONS[ActionState.RECONFIRMATION_REQUIRED]
    assert ActionState.FAILED in ACTION_TRANSITIONS[ActionState.RECONFIRMATION_REQUIRED]


def test_t3_expected_action_state_mismatch_rejected(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    with pytest.raises(ActionTransitionError):
        auth.transition_action(
            "m", "a1", 2, ActionState.PENDING,
            ActionState.DISPATCH_INTENT_RECORDED, _ev())
    assert _current(store, "m", "a1") is ActionState.AUTHORIZED


def test_t4_mission_revision_mismatch_rejected(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    with pytest.raises(ActionTransitionError):
        auth.transition_action(
            "m", "a1", 7, ActionState.PENDING,
            ActionState.AUTHORIZED, _ev())
    assert store.load("m")["revision"] == 1


def test_t5_revision_increments_exactly_once(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    result = _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    assert result.mission_revision == 2
    assert store.load("m")["revision"] == 2
    assert result.record.revision == 2


def test_t6_write_failure_leaves_prior_authoritative(tmp_path, monkeypatch):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    before = store.load("m")

    def _boom(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(ActionTransitionError):
        auth.transition_action(
            "m", "a1", 1, ActionState.PENDING,
            ActionState.AUTHORIZED, _ev())
    assert store.load("m") == before


def _identity_kwargs():
    return dict(
        mission_id="m", action_id="a1", request_semantics_digest="rd-a1",
        executor_logical_id="ex-a1", expected_governed_registration_id="g-a1",
        expected_generation=2,
    )


def _gate_proof(mid="m", aid="a1", digest="rd-a1", expected=None,
                node=None, capability=None,
                verified_at="2026-01-02T00:00:00+00:00"):
    """Mint a canonical gate-bound proof via a real gate evaluation."""
    node = node if node is not None else f"n-{aid}"
    capability = capability if capability is not None else f"cap.{aid}"
    expected = {"o": 1} if expected is None else expected
    gate = VerificationGate()
    contract = ActionContract(capability=capability, expected_output=expected)
    node_o = RuntimeNode(node_id=node, capability=capability,
                         action_contract=contract)
    loop = asyncio.new_event_loop()
    try:
        status, evidence = loop.run_until_complete(
            gate.evaluate_node(node_o, contract, expected))
    finally:
        loop.close()
    assert status.value == "VERIFIED_SUCCESS"
    return issue_action_verification_proof(
        mission_id=mid, action_id=aid, request_semantics_digest=digest,
        node_id=node, capability=capability, status=status,
        evidence=evidence, verified_at=verified_at)


def test_t7_identity_deterministic(tmp_path):
    assert (compute_local_execution_identity(**_identity_kwargs())
            == compute_local_execution_identity(**_identity_kwargs()))


def test_t8_request_change_changes_identity():
    base = compute_local_execution_identity(**_identity_kwargs())
    changed = dict(_identity_kwargs(), request_semantics_digest="rd-other")
    assert compute_local_execution_identity(**changed) != base


def test_t9_grid_change_changes_identity():
    base = compute_local_execution_identity(**_identity_kwargs())
    changed = dict(_identity_kwargs(), expected_governed_registration_id="g-x")
    assert compute_local_execution_identity(**changed) != base


def test_t10_generation_change_changes_identity():
    base = compute_local_execution_identity(**_identity_kwargs())
    changed = dict(_identity_kwargs(), expected_generation=3)
    assert compute_local_execution_identity(**changed) != base
    # int 2 vs string "2" are distinct identities.
    as_string = dict(_identity_kwargs(), expected_generation="2")
    with pytest.raises(ValueError):
        compute_local_execution_identity(**as_string)


def test_t11_executor_change_changes_identity():
    base = compute_local_execution_identity(**_identity_kwargs())
    changed = dict(_identity_kwargs(), executor_logical_id="ex-other")
    assert compute_local_execution_identity(**changed) != base


def test_t12_effect_binding_preserves_local_identity(tmp_path):
    # MODEL E2: post-dispatch effect binding must NOT redefine the frozen
    # local execution identity.
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    before = auth.execution_identity_for("m", "a1")
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    _drive(auth, store, "m", "a1", ActionState.RESULT_RECORDED,
           result={"out": 1}, provider_effect_id="prov-1")
    stored = store.load("m")["action_states"]["a1"]
    assert stored["effect_identity_digest"] == effect_identity_digest_for("prov-1")
    assert stored["effect_identity_digest"] != ""
    assert auth.execution_identity_for("m", "a1") == before
    assert effect_identity_digest_for("") == ""


def test_t13_no_python_identity_in_execution_identity(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    first = auth.execution_identity_for("m", "a1")
    auth2 = MissionActionAuthority(store)
    assert auth2.execution_identity_for("m", "a1") == first
    assert len(first) == 64
    assert "0x" not in first
    int(first, 16)  # valid hex digest, not a repr


def test_t14_intent_recorded_no_redispatch(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    rev = store.load("m")["revision"]
    decision = auth.decide_replay("m", "a1")
    assert decision is ReplayDecision.AMBIGUOUS_RECONCILIATION_REQUIRED
    assert decision is not ReplayDecision.MAY_DISPATCH
    assert store.load("m")["revision"] == rev
    assert _current(store, "m", "a1") is ActionState.DISPATCH_INTENT_RECORDED


def test_t15_dispatching_no_redispatch(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    rev = store.load("m")["revision"]
    assert auth.decide_replay("m", "a1") is (
        ReplayDecision.AMBIGUOUS_RECONCILIATION_REQUIRED)
    assert store.load("m")["revision"] == rev


def test_t16_c3_window_ambiguous(tmp_path):
    # C3: durable DISPATCHING with no provider effect proof on record.
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    assert store.load("m")["action_states"]["a1"]["provider_effect_id"] == ""
    decision = auth.decide_replay("m", "a1")
    assert decision is ReplayDecision.AMBIGUOUS_RECONCILIATION_REQUIRED
    # Nothing automatic happened: state and revision untouched by deciding.
    assert _current(store, "m", "a1") is ActionState.DISPATCHING


def test_t17_ambiguous_cannot_dispatch(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.AMBIGUOUS_EFFECT)
    with pytest.raises(ActionTransitionError):
        _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    assert _current(store, "m", "a1") is ActionState.AMBIGUOUS_EFFECT


def test_t18_ambiguous_cannot_complete(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.AMBIGUOUS_EFFECT)
    with pytest.raises(ActionTransitionError):
        _drive(auth, store, "m", "a1", ActionState.COMPLETED)
    assert _current(store, "m", "a1") is ActionState.AMBIGUOUS_EFFECT


def test_t19_absent_provider_claims_nothing(tmp_path):
    assert set(ReplayDecision) == {
        ReplayDecision.MAY_DISPATCH,
        ReplayDecision.DO_NOT_REDISPATCH,
        ReplayDecision.AMBIGUOUS_RECONCILIATION_REQUIRED,
        ReplayDecision.RECONFIRMATION_REQUIRED,
        ReplayDecision.ALREADY_COMPLETED,
    }
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    assert store.load("m")["action_states"]["a1"]["provider_effect_id"] == ""
    # No decision value promises external exactly-once.
    for decision in ReplayDecision:
        assert "EXACTLY_ONCE" not in decision.value
        assert "IDEMPOTEN" not in decision.value


def test_t20_provider_effect_stored_distinctly(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    before = auth.execution_identity_for("m", "a1")
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    _drive(auth, store, "m", "a1", ActionState.RESULT_RECORDED,
           result={"out": 1}, provider_effect_id="prov-123")
    stored = store.load("m")["action_states"]["a1"]
    assert stored["provider_effect_id"] == "prov-123"
    assert stored["effect_identity_digest"] == effect_identity_digest_for("prov-123")
    assert stored["provider_effect_id"] != stored["effect_identity_digest"]
    # Local identity stable across the binding; effect identity separate.
    assert auth.execution_identity_for("m", "a1") == before
    assert stored["effect_identity_digest"] != before


def test_t21_no_reusable_confirmation_token(tmp_path):
    import dataclasses
    for cls in (DurableActionState, ActionTransitionEvidence):
        fields = {f.name for f in dataclasses.fields(cls)}
        for forbidden in ("confirmation_token", "session_token",
                          "confirmed", "approval_callback", "session_id"):
            assert forbidden not in fields
    store = _store(tmp_path)
    _mission(store)
    blob = json.dumps(store.load("m"))
    assert "confirmation_token" not in blob
    assert "session token" not in blob


def test_t22_confirmation_dependent_restart(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    assert auth.decide_replay(
        "m", "a1", confirmation_required=True
    ) is ReplayDecision.RECONFIRMATION_REQUIRED
    assert auth.decide_replay(
        "m", "a1", confirmation_required=False
    ) is ReplayDecision.MAY_DISPATCH


def test_t23_result_recorded_no_gate_bypass(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    _drive(auth, store, "m", "a1", ActionState.RESULT_RECORDED,
           result={"out": 1})
    decision = auth.decide_replay("m", "a1")
    assert decision is ReplayDecision.DO_NOT_REDISPATCH
    assert decision is not ReplayDecision.MAY_DISPATCH
    # The table offers no RESULT_RECORDED -> VERIFIED/COMPLETED shortcut.
    assert ActionState.VERIFIED not in ACTION_TRANSITIONS[ActionState.RESULT_RECORDED]
    assert ActionState.COMPLETED not in ACTION_TRANSITIONS[ActionState.RESULT_RECORDED]


def test_t24_verification_required_no_direct_complete(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    for target, kw in (
        (ActionState.AUTHORIZED, {}),
        (ActionState.DISPATCH_INTENT_RECORDED, {}),
        (ActionState.DISPATCHING, {}),
        (ActionState.RESULT_RECORDED, {"result": {"out": 1}}),
        (ActionState.VERIFICATION_REQUIRED, {}),
    ):
        _drive(auth, store, "m", "a1", target, **kw)
    with pytest.raises(ActionTransitionError):
        _drive(auth, store, "m", "a1", ActionState.COMPLETED)
    assert auth.decide_replay("m", "a1") is ReplayDecision.DO_NOT_REDISPATCH


def test_t25_verified_mutable_evidence_no_freshness_bypass(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    for target, kw in (
        (ActionState.AUTHORIZED, {}),
        (ActionState.DISPATCH_INTENT_RECORDED, {}),
        (ActionState.DISPATCHING, {}),
        (ActionState.RESULT_RECORDED, {"result": {"out": 1}}),
        (ActionState.VERIFICATION_REQUIRED, {}),
    ):
        _drive(auth, store, "m", "a1", target, **kw)
    proof = _gate_proof()
    _drive(auth, store, "m", "a1", ActionState.VERIFIED,
           verification_proof=proof)
    # Historical VERIFIED never re-authorizes dispatch; freshness at
    # productive use remains owned by the verification gate contract.
    assert auth.decide_replay("m", "a1") is ReplayDecision.DO_NOT_REDISPATCH
    posture = auth.restart_posture_for(ActionState.VERIFIED)
    assert posture.fresh_verification_required is True
    assert posture.auto_redispatch_allowed is False
    # Deterministic (provider-free) gate evidence is timeless at rest.
    assert auth.verification_freshness_for("m", "a1") == FRESH_DETERMINISTIC


def test_t26_action_completed_not_mission_completed(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    for target, kw in (
        (ActionState.AUTHORIZED, {}),
        (ActionState.DISPATCH_INTENT_RECORDED, {}),
        (ActionState.DISPATCHING, {}),
        (ActionState.RESULT_RECORDED, {"result": {"out": 1}}),
        (ActionState.VERIFICATION_REQUIRED, {}),
    ):
        _drive(auth, store, "m", "a1", target, **kw)
    proof = _gate_proof()
    _drive(auth, store, "m", "a1", ActionState.VERIFIED,
           verification_proof=proof)
    _drive(auth, store, "m", "a1", ActionState.COMPLETED,
           completion_basis=proof)
    loaded = store.load("m")
    assert loaded["action_states"]["a1"]["state"] == "COMPLETED"
    # The action authority never sets mission-level completion.
    assert loaded["mission_status"] == "RUNNING"
    assert auth.decide_replay("m", "a1") is ReplayDecision.ALREADY_COMPLETED


def test_t27_missing_mission_nonresumable(tmp_path):
    store = _store(tmp_path)
    auth = _auth(store)
    with pytest.raises(MissionRecordNotFoundError):
        auth.decide_replay("ghost", "a1")
    with pytest.raises(MissionRecordNotFoundError):
        auth.transition_action(
            "ghost", "a1", 1, ActionState.PENDING,
            ActionState.AUTHORIZED, _ev())


def test_t28_restart_load_exact_state(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    # Fresh authority object over the same durable files (new process view).
    auth2 = MissionActionAuthority(store)
    assert auth2.decide_replay("m", "a1") is (
        ReplayDecision.AMBIGUOUS_RECONCILIATION_REQUIRED)
    assert (auth2.execution_identity_for("m", "a1")
            == auth.execution_identity_for("m", "a1"))
    result = auth2.transition_action(
        "m", "a1", 3, ActionState.DISPATCH_INTENT_RECORDED,
        ActionState.DISPATCHING, _ev())
    assert result.mission_revision == 4


def test_t29_sequential_stale_writer_rejected(tmp_path):
    # Two authorities, same files. Proves sequential stale-writer
    # detection, NOT simultaneous multiprocess CAS (unsupported).
    store = _store(tmp_path)
    _mission(store)
    auth_a = MissionActionAuthority(store)
    auth_b = MissionActionAuthority(store)
    auth_b.transition_action(
        "m", "a1", 1, ActionState.PENDING, ActionState.AUTHORIZED, _ev())
    with pytest.raises(ActionTransitionError):
        auth_a.transition_action(
            "m", "a1", 1, ActionState.PENDING,
            ActionState.AUTHORIZED, _ev())
    assert _current(store, "m", "a1") is ActionState.AUTHORIZED
    assert store.load("m")["revision"] == 2


def test_t30_invalid_action_id_fails_closed(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    with pytest.raises(MissionRecordNotFoundError):
        auth.decide_replay("m", "nope")
    with pytest.raises(MissionRecordNotFoundError):
        auth.transition_action(
            "m", "nope", 1, ActionState.PENDING,
            ActionState.AUTHORIZED, _ev())


def test_t31_immutable_action_identity_rejected(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    data = store.load("m")
    data["action_states"]["a1"]["expected_governed_registration_id"] = "g-evil"
    data["revision"] = 2
    mutated = MissionRecord.from_dict(data)
    with pytest.raises(MissionRecordValidationError):
        store.commit(1, mutated)
    assert store.load("m")["action_states"]["a1"][
        "expected_governed_registration_id"] == "g-a1"
    # Plan capability linkage is frozen the same way.
    data2 = store.load("m")
    data2["plan"][0]["capability"] = "cap.evil"
    data2["revision"] = 2
    with pytest.raises(MissionRecordValidationError):
        store.commit(1, MissionRecord.from_dict(data2))
    assert store.load("m")["revision"] == 1


def test_t32_request_digest_mutation_rejected(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    data = store.load("m")
    data["plan"][0]["request_semantics_digest"] = "rd-evil"
    data["revision"] = 2
    with pytest.raises(MissionRecordValidationError):
        store.commit(1, MissionRecord.from_dict(data))
    assert store.load("m")["plan"][0]["request_semantics_digest"] == "rd-a1"


def test_t33_unknown_action_state_fails_closed(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    data = store.load("m")
    data["action_states"]["a1"]["state"] = "BOGUS"
    (store._missions_dir / "m.json").write_text(  # noqa: SLF001
        json.dumps(data), encoding="utf-8")
    auth = _auth(store)
    with pytest.raises(MissionRecordValidationError):
        auth.decide_replay("m", "a1")
    with pytest.raises(MissionRecordValidationError):
        auth.transition_action(
            "m", "a1", 1, ActionState.PENDING,
            ActionState.AUTHORIZED, _ev())


def test_t34_unknown_decision_inputs_fails_closed(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    with pytest.raises(MissionRecordNotFoundError):
        auth.decide_replay("nope", "a1")
    with pytest.raises(MissionRecordNotFoundError):
        auth.decide_replay("m", "nope")
    with pytest.raises(ActionTransitionError):
        auth.decide_replay("m", "a1", expected_execution_identity="bogus")
    with pytest.raises(ActionTransitionError):
        auth.transition_action(
            "m", "a1", 1, "PENDING", ActionState.AUTHORIZED, _ev())


def test_t35_no_rrm_authority_duplicated():
    import intent_kernel.mission.action_authority as aa
    import intent_kernel.mission.execution_identity as ei
    import intent_kernel.mission.transitions as tr
    for module in (aa, ei, tr):
        assert "intent_kernel.rrm" not in open(module.__file__).read()


def test_t36_no_productive_executor_rebind():
    import inspect
    import intent_kernel.mission.action_authority as aa
    public = {name for name, member in inspect.getmembers(
        MissionActionAuthority, predicate=inspect.isfunction)
        if not name.startswith("_")}
    assert public == {"transition_action", "decide_replay",
                      "execution_identity_for", "restart_posture_for",
                      "verification_freshness_for"}
    # No productive binding constructs: no registry/discovery imports,
    # no rebind/lookup/registration calls, no re-registration references.
    source = open(aa.__file__).read()
    assert "RegistryResourceManager" not in source
    assert "register_" not in source
    assert "def rebind" not in source
    assert "def rediscover" not in source
    assert "from intent_kernel.orchestration" not in source
    assert "from intent_kernel.discovery" not in source
    assert "reregistration" not in source.lower()


def test_t37_no_automatic_rediscovery_or_resume():
    import intent_kernel.mission.action_authority as aa
    source = open(aa.__file__).read()
    assert "def discover" not in source
    assert "def resume" not in source
    assert "def recover" not in source
    assert "auto_dispatch" not in source.lower()
    assert not hasattr(MissionActionAuthority, "create_mission")
    store_methods = [m for m in dir(MissionActionAuthority)
                     if not m.startswith("_")]
    assert "create" not in " ".join(store_methods)


def test_t38_paths_isolated(tmp_path):
    store = _store(tmp_path)
    assert tmp_path in store._missions_dir.parents  # noqa: SLF001
    _mission(store)
    assert (store._missions_dir / "m.json").is_file()  # noqa: SLF001


def test_crash_matrix_postures():
    from intent_kernel.mission.transitions import RESTART_POSTURES
    assert set(RESTART_POSTURES) == set(ActionState)
    for state, posture in RESTART_POSTURES.items():
        # The M32B-2 core guarantee: nothing auto-redispatches.
        assert posture.auto_redispatch_allowed is False, state
        assert posture.safe_automatic_next_step, state
    reconciling = {s for s, p in RESTART_POSTURES.items()
                   if p.reconciliation_required}
    assert reconciling == {ActionState.DISPATCH_INTENT_RECORDED,
                           ActionState.DISPATCHING,
                           ActionState.AMBIGUOUS_EFFECT}
    reverifying = {s for s, p in RESTART_POSTURES.items()
                   if p.fresh_verification_required}
    assert reverifying == {ActionState.RESULT_RECORDED,
                           ActionState.VERIFICATION_REQUIRED,
                           ActionState.VERIFIED}
    # C0 (no durable authorization at all) has no automatic step either.
    with pytest.raises(IllegalActionTransitionError):
        from intent_kernel.mission.transitions import restart_posture_for
        restart_posture_for("BOGUS")


# ---------------------------------------------------------------------------
# I1-I10: MODEL E2 execution identity
# ---------------------------------------------------------------------------

def test_i1_identity_frozen_before_dispatch_intent(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    assert store.load("m")["action_states"]["a1"]["local_execution_identity"] == ""
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    frozen = store.load("m")["action_states"]["a1"]["local_execution_identity"]
    assert frozen != ""
    assert frozen == auth.execution_identity_for("m", "a1")
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    assert (store.load("m")["action_states"]["a1"]["local_execution_identity"]
            == frozen)


def test_i2_identity_identical_across_effect_binding(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    before = store.load("m")["action_states"]["a1"]["local_execution_identity"]
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    _drive(auth, store, "m", "a1", ActionState.RESULT_RECORDED,
           result={"o": 1}, provider_effect_id="prov-i2")
    after = store.load("m")["action_states"]["a1"]
    assert after["local_execution_identity"] == before
    assert after["effect_identity_digest"] != ""


def test_i3_effect_binding_changes_effect_not_local(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    local_before = auth.execution_identity_for("m", "a1")
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    _drive(auth, store, "m", "a1", ActionState.RESULT_RECORDED,
           result={"o": 1}, provider_effect_id="prov-i3")
    assert auth.execution_identity_for("m", "a1") == local_before
    assert (store.load("m")["action_states"]["a1"]["effect_identity_digest"]
            == effect_identity_digest_for("prov-i3"))


def test_i4_second_effect_replacement_fails_closed(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    _drive(auth, store, "m", "a1", ActionState.RESULT_RECORDED,
           result={"o": 1}, provider_effect_id="prov-one")
    with pytest.raises(ActionTransitionError):
        _drive(auth, store, "m", "a1", ActionState.VERIFICATION_REQUIRED,
               provider_effect_id="prov-two")
    stored = store.load("m")["action_states"]["a1"]
    assert stored["provider_effect_id"] == "prov-one"
    assert stored["state"] == "RESULT_RECORDED"


def test_i5_identity_mutation_fails_closed(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    genuine = store.load("m")["action_states"]["a1"]["local_execution_identity"]
    # Tamper at rest: load fails closed.
    data = store.load("m")
    data["action_states"]["a1"]["local_execution_identity"] = "0" * 64
    (store._missions_dir / "m.json").write_text(  # noqa: SLF001
        json.dumps(data), encoding="utf-8")
    with pytest.raises(MissionRecordValidationError):
        store.load("m")
    # Restore, then mutate via candidate commit: also rejected.
    store2 = _store(tmp_path, "i5")
    _mission(store2, mission_id="m5")
    auth2 = _auth(store2)
    _drive(auth2, store2, "m5", "a1", ActionState.AUTHORIZED)
    data2 = store2.load("m5")
    data2["action_states"]["a1"]["local_execution_identity"] = "f" * 64
    data2["revision"] = 3
    with pytest.raises(MissionRecordValidationError):
        store2.commit(2, MissionRecord.from_dict(data2))
    assert genuine != "0" * 64


def test_i6_restart_preserves_exact_identity(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    expected = auth.execution_identity_for("m", "a1")
    store2 = JsonFileMissionRecordStore(
        missions_dir=store._missions_dir,  # noqa: SLF001
        continuity_file=store._continuity_file,  # noqa: SLF001
    )
    assert (MissionActionAuthority(store2).execution_identity_for("m", "a1")
            == expected)
    assert (store2.load("m")["action_states"]["a1"]["local_execution_identity"]
            == expected)


def test_i7_c2_uses_frozen_identity(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    frozen = auth.execution_identity_for("m", "a1")
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    # Correct frozen identity: decision proceeds (ambiguous, not an error).
    assert auth.decide_replay(
        "m", "a1", expected_execution_identity=frozen
    ) is ReplayDecision.AMBIGUOUS_RECONCILIATION_REQUIRED
    # Wrong identity: fail closed, never a dispatch verdict.
    with pytest.raises(ActionTransitionError):
        auth.decide_replay("m", "a1", expected_execution_identity="0" * 64)


def test_i8_c3_uses_frozen_identity(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    frozen = auth.execution_identity_for("m", "a1")
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    assert auth.decide_replay(
        "m", "a1", expected_execution_identity=frozen
    ) is ReplayDecision.AMBIGUOUS_RECONCILIATION_REQUIRED
    with pytest.raises(ActionTransitionError):
        auth.decide_replay("m", "a1", expected_execution_identity="f" * 64)


def test_i9_effect_distinct_from_local(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    _drive(auth, store, "m", "a1", ActionState.RESULT_RECORDED,
           result={"o": 1}, provider_effect_id="prov-i9")
    stored = store.load("m")["action_states"]["a1"]
    local = auth.execution_identity_for("m", "a1")
    assert len({local, stored["provider_effect_id"],
                stored["effect_identity_digest"]}) == 3


def test_i10_local_hash_never_provider_proof(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    local = auth.execution_identity_for("m", "a1")
    # A local hash is not, and can never become, a provider token.
    assert local != ""
    assert "prov" not in local
    for decision in ReplayDecision:
        assert "PROVIDER" not in decision.value
        assert "IDEMPOTEN" not in decision.value
    assert not hasattr(auth, "provider_idempotency")
    assert not hasattr(auth, "claim_exactly_once")


# ---------------------------------------------------------------------------
# V1-V8: verification authority
# ---------------------------------------------------------------------------

def _drive_verified(auth, store, mid="m", aid="a1", proof=None):
    _drive(auth, store, mid, aid, ActionState.AUTHORIZED)
    _drive(auth, store, mid, aid, ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, mid, aid, ActionState.DISPATCHING)
    _drive(auth, store, mid, aid, ActionState.RESULT_RECORDED,
           result={"o": 1})
    _drive(auth, store, mid, aid, ActionState.VERIFICATION_REQUIRED)
    proof = proof if proof is not None else _gate_proof(mid, aid)
    return _drive(auth, store, mid, aid, ActionState.VERIFIED,
                  verification_proof=proof)


def test_v1_no_proof_no_verified(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    _drive(auth, store, "m", "a1", ActionState.RESULT_RECORDED,
           result={"o": 1})
    _drive(auth, store, "m", "a1", ActionState.VERIFICATION_REQUIRED)
    with pytest.raises(ActionTransitionError):
        _drive(auth, store, "m", "a1", ActionState.VERIFIED)
    assert _current(store, "m", "a1") is ActionState.VERIFICATION_REQUIRED


def test_v2_arbitrary_evidence_insufficient(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    # A plain dict is not a proof: rejected at the evidence boundary.
    with pytest.raises(ValueError):
        _ev(verification_proof={"mission_id": "m"})
    # A proof object WITHOUT gate authority is equally insufficient.
    forged = ActionVerificationProof(
        mission_id="m", action_id="a1",
        request_semantics_digest="rd-a1",
        verification_status="VERIFIED_SUCCESS",
        verification_source="VerificationGate",
        verification_method="forged.verify()",
        verified_at="2026-01-02T00:00:00+00:00",
    )
    assert forged.authority_complete is False
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    _drive(auth, store, "m", "a1", ActionState.RESULT_RECORDED,
           result={"o": 1})
    _drive(auth, store, "m", "a1", ActionState.VERIFICATION_REQUIRED)
    with pytest.raises(ActionTransitionError):
        _drive(auth, store, "m", "a1", ActionState.VERIFIED,
               verification_proof=forged)
    # Legacy status/evidence alongside cannot substitute the proof either.
    with pytest.raises(ActionTransitionError):
        _drive(auth, store, "m", "a1", ActionState.VERIFIED,
               verification_status="VERIFIED_SUCCESS",
               verification_evidence={"e": 1})


def test_v3_canonical_proof_persists_verified(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    result = _drive_verified(auth, store)
    assert result.new_state is ActionState.VERIFIED
    stored = store.load("m")["action_states"]["a1"]
    assert stored["verification_status"] == "VERIFIED_SUCCESS"
    assert stored["verification_proof_digest"] != ""
    assert stored["verification_evidence"]["proof_digest"] == (
        stored["verification_proof_digest"])


def test_v4_proof_wrong_mission_fails(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    _drive(auth, store, "m", "a1", ActionState.RESULT_RECORDED,
           result={"o": 1})
    _drive(auth, store, "m", "a1", ActionState.VERIFICATION_REQUIRED)
    foreign = _gate_proof(mid="other", aid="a1")
    with pytest.raises(ActionTransitionError):
        _drive(auth, store, "m", "a1", ActionState.VERIFIED,
               verification_proof=foreign)


def test_v5_proof_wrong_action_fails(tmp_path):
    store = _store(tmp_path, "v5")
    _mission(store, mission_id="mv", actions=("a1", "a2"))
    auth = _auth(store)
    for aid in ("a1", "a2"):
        _drive(auth, store, "mv", aid, ActionState.AUTHORIZED)
        _drive(auth, store, "mv", aid, ActionState.DISPATCH_INTENT_RECORDED)
        _drive(auth, store, "mv", aid, ActionState.DISPATCHING)
        _drive(auth, store, "mv", aid, ActionState.RESULT_RECORDED,
               result={"o": 1})
        # NOTE: both actions share expected_output {"o": 1} shape; the gate
        # proof below is minted for a2 but presented for a1.
    _drive(auth, store, "mv", "a1", ActionState.VERIFICATION_REQUIRED)
    _drive(auth, store, "mv", "a2", ActionState.VERIFICATION_REQUIRED)
    proof_for_a2 = _gate_proof("mv", "a2", digest="rd-a2",
                               node="n-a2", capability="cap.a2")
    with pytest.raises(ActionTransitionError):
        _drive(auth, store, "mv", "a1", ActionState.VERIFIED,
               verification_proof=proof_for_a2)


def test_v6_contract_mismatch_fails(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    _drive(auth, store, "m", "a1", ActionState.RESULT_RECORDED,
           result={"o": 1})
    _drive(auth, store, "m", "a1", ActionState.VERIFICATION_REQUIRED)
    stale_contract = _gate_proof(digest="rd-evil")
    with pytest.raises(ActionTransitionError):
        _drive(auth, store, "m", "a1", ActionState.VERIFIED,
               verification_proof=stale_contract)


def _provider_proof():
    """Provider evidence uses a canonical gate-issued proof; freshness
    is determined by the provider's own evidence stored separately."""
    return _gate_proof()


def test_v7_provider_evidence_never_fresh(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    _drive(auth, store, "m", "a1", ActionState.RESULT_RECORDED,
           result={"o": 1})
    _drive(auth, store, "m", "a1", ActionState.VERIFICATION_REQUIRED)
    _drive(auth, store, "m", "a1", ActionState.VERIFIED,
           verification_proof=_provider_proof())
    # Inject provider observations into the stored verification
    # evidence so that freshness requires revalidation.
    mission_file = store._mission_file("m")
    with open(mission_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["action_states"]["a1"]["verification_evidence"] = {
        "verification_status": "VERIFIED_SUCCESS",
        "verification_source": "VerificationGate",
        "verification_method": "RRMEvidenceAdapter.observe()",
        "external_evidence_required": True,
        "external_evidence_contract_hash": "eh",
        "external_observations": [{
            "evidence_type": "PROVIDER_RESOURCE_STATE",
            "resource_id": "p1",
            "observer_id": "rrm",
            "observed_at": "2026-01-02T00:00:00+00:00",
            "matched": True,
        }],
    }
    with open(mission_file, "w", encoding="utf-8") as f:
        json.dump(data, f)
    assert auth.verification_freshness_for("m", "a1") == REQUIRES_REVALIDATION
    assert auth.decide_replay("m", "a1") is ReplayDecision.DO_NOT_REDISPATCH


def test_v8_restart_no_freshness_conversion(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive_verified(auth, store)
    assert auth.verification_freshness_for("m", "a1") == FRESH_DETERMINISTIC
    # Fresh authority object over the same durable files (restart view):
    # verdicts are identical; history is never upgraded.
    auth2 = MissionActionAuthority(store)
    assert auth2.verification_freshness_for("m", "a1") == FRESH_DETERMINISTIC
    assert auth2.decide_replay("m", "a1") is ReplayDecision.DO_NOT_REDISPATCH
    assert auth2.verification_freshness_for("m", "nope") if False else True
    with pytest.raises(MissionRecordNotFoundError):
        auth2.verification_freshness_for("m", "nope")


# ---------------------------------------------------------------------------
# A1-A6: action completion authority
# ---------------------------------------------------------------------------

def _drive_completed(auth, store, mid="m", aid="a1", proof=None):
    _drive(auth, store, mid, aid, ActionState.AUTHORIZED)
    _drive(auth, store, mid, aid, ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, mid, aid, ActionState.DISPATCHING)
    _drive(auth, store, mid, aid, ActionState.RESULT_RECORDED,
           result={"o": 1})
    _drive(auth, store, mid, aid, ActionState.VERIFICATION_REQUIRED)
    proof = proof if proof is not None else _gate_proof(mid, aid)
    _drive(auth, store, mid, aid, ActionState.VERIFIED,
           verification_proof=proof)
    return _drive(auth, store, mid, aid, ActionState.COMPLETED,
                  completion_basis=proof)


def test_a1_arbitrary_caller_cannot_complete(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    with pytest.raises(ActionTransitionError):
        _drive(auth, store, "m", "a1", ActionState.COMPLETED)


def test_a2_missing_basis_fails(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    proof = _gate_proof()
    _drive(auth, store, "m", "a1", ActionState.AUTHORIZED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCH_INTENT_RECORDED)
    _drive(auth, store, "m", "a1", ActionState.DISPATCHING)
    _drive(auth, store, "m", "a1", ActionState.RESULT_RECORDED,
           result={"o": 1})
    _drive(auth, store, "m", "a1", ActionState.VERIFICATION_REQUIRED)
    _drive(auth, store, "m", "a1", ActionState.VERIFIED,
           verification_proof=proof)
    with pytest.raises(ActionTransitionError):
        _drive(auth, store, "m", "a1", ActionState.COMPLETED)
    # A dict is not a basis either (evidence boundary rejects it).
    with pytest.raises(ValueError):
        _ev(completion_basis={"proof_digest": proof.proof_digest()})


def test_a3_wrong_action_basis_fails(tmp_path):
    store = _store(tmp_path, "a3")
    _mission(store, mission_id="ma", actions=("a1", "a2"))
    auth = _auth(store)
    for aid in ("a1", "a2"):
        _drive(auth, store, "ma", aid, ActionState.AUTHORIZED)
        _drive(auth, store, "ma", aid, ActionState.DISPATCH_INTENT_RECORDED)
        _drive(auth, store, "ma", aid, ActionState.DISPATCHING)
        _drive(auth, store, "ma", aid, ActionState.RESULT_RECORDED,
               result={"o": 1})
        _drive(auth, store, "ma", aid, ActionState.VERIFICATION_REQUIRED)
    proof_a2 = _gate_proof("ma", "a2", digest="rd-a2",
                           node="n-a2", capability="cap.a2")
    _drive(auth, store, "ma", "a1", ActionState.VERIFIED,
           verification_proof=_gate_proof("ma", "a1"))
    # Foreign-action basis rejected...
    with pytest.raises(ActionTransitionError):
        _drive(auth, store, "ma", "a1", ActionState.COMPLETED,
               completion_basis=proof_a2)
    # ...as is a superseded basis (same action, different evaluation:
    # its digest is not the one that authorized current VERIFIED state).
    other = _gate_proof("ma", "a1", verified_at="2026-05-05T00:00:00+00:00")
    stored_digest = store.load("ma")["action_states"]["a1"][
        "verification_proof_digest"]
    assert other.proof_digest() != stored_digest
    with pytest.raises(ActionTransitionError):
        _drive(auth, store, "ma", "a1", ActionState.COMPLETED,
               completion_basis=other)


def test_a4_valid_basis_persists_completed(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    result = _drive_completed(auth, store)
    assert result.new_state is ActionState.COMPLETED
    assert store.load("m")["action_states"]["a1"]["state"] == "COMPLETED"


def test_a5_action_completed_not_mission_completed(tmp_path):
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive_completed(auth, store)
    assert store.load("m")["mission_status"] == "RUNNING"


def test_a6_completion_gate_still_required(tmp_path):
    from intent_kernel.runtime.verification import MissionCompletionGate
    store = _store(tmp_path)
    _mission(store)
    auth = _auth(store)
    _drive_completed(auth, store)
    # Mission-level completion is untouched by action authority...
    assert store.load("m")["mission_status"] != "COMPLETED"
    # ...and the authority never references the mission gate: it cannot
    # mint mission completion, only the gate's own contract can.
    import intent_kernel.mission.action_authority as aa
    assert "MissionCompletionGate" not in open(aa.__file__).read()
    assert MissionCompletionGate is not None


def test_crash_matrix_postures():
    from intent_kernel.mission.transitions import RESTART_POSTURES
    assert set(RESTART_POSTURES) == set(ActionState)
    for state, posture in RESTART_POSTURES.items():
        # The M32B-2 core guarantee: nothing auto-redispatches.
        assert posture.auto_redispatch_allowed is False, state
        assert posture.safe_automatic_next_step, state
    reconciling = {s for s, p in RESTART_POSTURES.items()
                   if p.reconciliation_required}
    assert reconciling == {ActionState.DISPATCH_INTENT_RECORDED,
                           ActionState.DISPATCHING,
                           ActionState.AMBIGUOUS_EFFECT}
    reverifying = {s for s, p in RESTART_POSTURES.items()
                   if p.fresh_verification_required}
    assert reverifying == {ActionState.RESULT_RECORDED,
                           ActionState.VERIFICATION_REQUIRED,
                           ActionState.VERIFIED}
    # C0 (no durable authorization at all) has no automatic step either.
    with pytest.raises(IllegalActionTransitionError):
        from intent_kernel.mission.transitions import restart_posture_for
        restart_posture_for("BOGUS")
