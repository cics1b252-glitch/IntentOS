"""M27.2-P04-R4 — Trusted gate-proof bridge (adversarial regressions).

Proves the resume-integrity invariants added by the P04-R4 bridge:

    GENUINE_SUCCESS            -> durable VERIFIED + gate proof digest
    BYPASS                     != durable VERIFIED (no proof ever minted)
    CALLER_FABRICATED_EVIDENCE != gate proof
    CHECKPOINT_ONLY_CLAIM      != durable VERIFIED (resume -> INCONCLUSIVE)
    TAMPERED_PROOF             != durable VERIFIED (resume -> INCONCLUSIVE)
    RESULT_RECORDED -> VERIFIED requires the canonical VERIFICATION_REQUIRED hop
    STORE_LESS_LEGACY          == preserved (GATE 3 boundary)

Store-backed cases run through the canonical wired runtime (RRM + durable store
+ dispatch guard); the store-less case exercises the legacy checkpoint path.
"""

from __future__ import annotations

import pytest

from intent_kernel.instructions import CompletionEvidence
from intent_kernel.mission import (
    ActionState,
    DurableActionState,
    MissionActionAuthority,
    MissionDefinition,
    MissionRecord,
    MissionStatus,
    ProductiveDispatchGuard,
    spec_for_runtime_node,
)
from intent_kernel.mission.action_authority import (
    ActionTransitionError,
    ActionTransitionEvidence,
)
from intent_kernel.runtime.mission_runtime import (
    MissionRuntime,
    _recompute_proof_digest,
)
from intent_kernel.runtime.models import (
    ActionContract,
    MissionCheckpoint,
    RuntimeNode,
    VerificationStatus,
)
from intent_kernel.runtime.verification import (
    VerificationGate,
    issue_action_verification_proof,
)
from intent_kernel.time_utils import utc_iso

from tests.test_m32c_r2_lifecycle_proof import (
    CountingApp,
    _AllowConstitution,
    _components,
    _govern,
    _mission_store,
    _started_mission,
)

_RESULT = "rt-ok"


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class _GenuineExecutor:
    """Executor whose output equals the node's expected output."""

    def __init__(self):
        self.calls = 0

    async def execute(self, contract):
        self.calls += 1
        return _RESULT


def _make_node(node_id="n1", agent_id="ex-rt", idempotency_key="rk1",
               expected=_RESULT, verification_required=True):
    contract = ActionContract(
        action_id=node_id,
        capability="c.rt",
        idempotency_key=idempotency_key,
        expected_output=expected,
        verification_required=verification_required,
    )
    return RuntimeNode(
        node_id=node_id, capability="c.rt", agent_id=agent_id,
        action_contract=contract)


def _guard_for(store):
    return ProductiveDispatchGuard(MissionActionAuthority(store), store)


def _wired_runtime(store, components, checkpoint_repo=None):
    return MissionRuntime(
        executor=_GenuineExecutor(),
        checkpoint_repo=checkpoint_repo,
        constitution=_AllowConstitution(),
        dispatch_guard=_guard_for(store),
        mission_record_store=store,
        rrm_service=components.resource_manager,
    )


def _bind_action(store, mid, node, *, state=ActionState.PENDING):
    spec = spec_for_runtime_node(mid, node)
    ident = store.get_continuity_identity()
    definition = MissionDefinition(objective="runtime", context={"k": "v"})
    probe = MissionRecord(
        mission_id="probe", installation_id=ident, mission_definition=definition)
    record = MissionRecord(
        mission_id=mid, installation_id=ident, revision=1, runtime_id="rt-1",
        mission_definition=definition,
        mission_definition_digest=probe.compute_definition_digest(),
        mission_status=MissionStatus.RUNNING,
        plan=({
            "action_id": spec.action_id,
            "capability": node.capability or spec.action_id,
            "node_id": node.node_id,
            "dependencies": [],
            "request_semantics_digest": spec.request_semantics_digest,
            "operation": spec.operation,
        },),
        action_states={spec.action_id: DurableActionState(
            action_id=spec.action_id, node_id=node.node_id, state=state,
            expected_resource_id="r", expected_executor_kind="core_app",
            expected_executor_logical_id=spec.executor_logical_id)},
    )
    assert store.create(record).outcome == "committed"


async def _governed_mission(components, name, store, node, state=ActionState.PENDING):
    _govern(components, CountingApp())
    mission = await _started_mission(components, name)
    _bind_action(store, str(mission.id), node, state=state)
    return str(mission.id)


def _storeless_runtime(checkpoint_repo=None):
    from intent_kernel.runtime.checkpoints import InMemoryCheckpointRepository
    from intent_kernel.runtime.executor_port import InMemoryActionExecutor
    return MissionRuntime(
        executor=InMemoryActionExecutor(),
        checkpoint_repo=checkpoint_repo or InMemoryCheckpointRepository(),
        constitution=_AllowConstitution(),
    )


def _storeless_node(node_id="n1", expected="echo"):
    """Node for the InMemoryActionExecutor (default echo output 'echo')."""
    return RuntimeNode(
        node_id=node_id, capability="test.echo",
        action_contract=ActionContract(
            capability="test.echo", expected_output=expected))


async def _issue_proof(evidence, status, *, mission_id="m", action_id="n1",
                       request_digest="req", node_id="n1", capability="c.rt"):
    return issue_action_verification_proof(
        mission_id=mission_id, action_id=action_id,
        request_semantics_digest=request_digest, node_id=node_id,
        capability=capability, status=status, evidence=evidence,
        verified_at=utc_iso())


# ---------------------------------------------------------------------------
# R4-A01 — genuine success anchors a durable gate proof (canonical sequence)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_r4_a01_genuine_success_anchors_durable_gate_proof(tmp_path):
    components = _components(tmp_path, tmp_path / ".intent-os")
    store = _mission_store(tmp_path)
    mid = await _governed_mission(components, "r4a01", store, _make_node())

    rt = _wired_runtime(store, components)
    inst = rt.create_instance(mid, "g1", [_make_node()])
    await rt.run_mission(inst.runtime_id)

    assert rt.executor.calls == 1
    assert inst.nodes["n1"].verification_result == VerificationStatus.VERIFIED_SUCCESS

    raw = store.load(mid)
    astate = raw["action_states"]["n1"]
    assert astate["state"] == ActionState.VERIFIED.value
    assert astate["verification_status"] == "VERIFIED_SUCCESS"
    assert astate["verification_proof_digest"]
    ev = astate["verification_evidence"]
    assert ev["mission_id"] == mid
    assert ev["action_id"] == "n1"
    assert ev["request_semantics_digest"] == raw["plan"][0]["request_semantics_digest"]
    assert ev["verification_source"] == "VerificationGate"


# ---------------------------------------------------------------------------
# R4-A02 — resume restores VERIFIED_SUCCESS from the durable proof
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_r4_a02_resume_restores_from_durable_proof(tmp_path):
    components = _components(tmp_path, tmp_path / ".intent-os")
    store = _mission_store(tmp_path)
    mid = await _governed_mission(components, "r4a02", store, _make_node())

    rt1 = _wired_runtime(store, components)
    inst1 = rt1.create_instance(mid, "g1", [_make_node()])
    await rt1.run_mission(inst1.runtime_id)
    c1 = await rt1.checkpoint_repo.get_latest_checkpoint(inst1.runtime_id)
    digest = store.load(mid)["action_states"]["n1"]["verification_proof_digest"]

    rt2 = _wired_runtime(store, components, checkpoint_repo=rt1.checkpoint_repo)
    inst2 = rt2.create_instance(mid, "g2", [_make_node()])
    assert inst2.nodes["n1"].verification_result is None
    await rt2.checkpoint_repo.save_checkpoint(MissionCheckpoint(
        runtime_id=inst2.runtime_id, mission_id=mid, runtime_status="COMPLETED",
        completed_nodes=["n1"], pending_nodes=[], failed_nodes=[],
        verification_state={"n1": {
            "verification_result": "VERIFIED_SUCCESS",
            "evidence_id": c1.verification_state["n1"]["evidence_id"],
            "verification_proof_digest": digest,
        }},
        completion_evidence=list(c1.completion_evidence),
    ))

    resumed = await rt2.resume(inst2.runtime_id)
    assert resumed.nodes["n1"].verification_result == VerificationStatus.VERIFIED_SUCCESS
    assert rt2.executor.calls == 0


# ---------------------------------------------------------------------------
# R4-A03 — a checkpoint-only claim without a durable proof -> INCONCLUSIVE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_r4_a03_checkpoint_only_claim_is_inconclusive(tmp_path):
    components = _components(tmp_path, tmp_path / ".intent-os")
    store = _mission_store(tmp_path)
    mid = await _governed_mission(
        components, "r4a03", store, _make_node(),
        state=ActionState.RESULT_RECORDED)

    rt = _wired_runtime(store, components)
    inst = rt.create_instance(mid, "g1", [_make_node()])
    await rt.checkpoint_repo.save_checkpoint(MissionCheckpoint(
        runtime_id=inst.runtime_id, mission_id=mid, runtime_status="COMPLETED",
        completed_nodes=["n1"], pending_nodes=[], failed_nodes=[],
        verification_state={"n1": {"verification_result": "VERIFIED_SUCCESS",
                                   "evidence_id": "ev_forged"}},
        completion_evidence=[{
            "evidence_id": "ev_forged", "source": "VerificationGate",
            "verified": True,
            "details": {"node_id": "n1", "verification_status": "VERIFIED_SUCCESS",
                        "verification_type": "EXACT", "exact_contract_hash": "any"},
        }],
    ))

    resumed = await rt.resume(inst.runtime_id)
    assert resumed.nodes["n1"].verification_result == VerificationStatus.INCONCLUSIVE


# ---------------------------------------------------------------------------
# R4-A04 — checkpoint claims a foreign digest -> INCONCLUSIVE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_r4_a04_checkpoint_foreign_digest_is_inconclusive(tmp_path):
    components = _components(tmp_path, tmp_path / ".intent-os")
    store = _mission_store(tmp_path)
    mid = await _governed_mission(components, "r4a04", store, _make_node())

    rt1 = _wired_runtime(store, components)
    inst1 = rt1.create_instance(mid, "g1", [_make_node()])
    await rt1.run_mission(inst1.runtime_id)
    c1 = await rt1.checkpoint_repo.get_latest_checkpoint(inst1.runtime_id)

    rt2 = _wired_runtime(store, components, checkpoint_repo=rt1.checkpoint_repo)
    inst2 = rt2.create_instance(mid, "g2", [_make_node()])
    await rt2.checkpoint_repo.save_checkpoint(MissionCheckpoint(
        runtime_id=inst2.runtime_id, mission_id=mid, runtime_status="COMPLETED",
        completed_nodes=["n1"], pending_nodes=[], failed_nodes=[],
        verification_state={"n1": {
            "verification_result": "VERIFIED_SUCCESS",
            "evidence_id": c1.verification_state["n1"]["evidence_id"],
            "verification_proof_digest": "deadbeef",
        }},
        completion_evidence=list(c1.completion_evidence),
    ))

    resumed = await rt2.resume(inst2.runtime_id)
    assert resumed.nodes["n1"].verification_result == VerificationStatus.INCONCLUSIVE


# ---------------------------------------------------------------------------
# R4-A05 — tampered durable proof -> INCONCLUSIVE
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_r4_a05_tampered_durable_proof_is_inconclusive(tmp_path):
    components = _components(tmp_path, tmp_path / ".intent-os")
    store = _mission_store(tmp_path)
    mid = await _governed_mission(components, "r4a05", store, _make_node())

    rt1 = _wired_runtime(store, components)
    inst1 = rt1.create_instance(mid, "g1", [_make_node()])
    await rt1.run_mission(inst1.runtime_id)
    c1 = await rt1.checkpoint_repo.get_latest_checkpoint(inst1.runtime_id)

    raw = store.load(mid)
    revision = raw["revision"]
    raw["action_states"]["n1"]["verification_evidence"]["verified_at"] = "TAMPERED"
    raw["revision"] = revision + 1
    store.commit(revision, MissionRecord.from_dict(raw))

    rt2 = _wired_runtime(store, components, checkpoint_repo=rt1.checkpoint_repo)
    inst2 = rt2.create_instance(mid, "g2", [_make_node()])
    await rt2.checkpoint_repo.save_checkpoint(MissionCheckpoint(
        runtime_id=inst2.runtime_id, mission_id=mid, runtime_status="COMPLETED",
        completed_nodes=["n1"], pending_nodes=[], failed_nodes=[],
        verification_state={"n1": {
            "verification_result": "VERIFIED_SUCCESS",
            "evidence_id": c1.verification_state["n1"]["evidence_id"],
            "verification_proof_digest":
                raw["action_states"]["n1"]["verification_proof_digest"],
        }},
        completion_evidence=list(c1.completion_evidence),
    ))

    resumed = await rt2.resume(inst2.runtime_id)
    assert resumed.nodes["n1"].verification_result == VerificationStatus.INCONCLUSIVE


# ---------------------------------------------------------------------------
# R4-A05b — bypass (verification_required=False) never mints a durable proof
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_r4_a05b_bypass_never_mints_durable_proof(tmp_path):
    components = _components(tmp_path, tmp_path / ".intent-os")
    store = _mission_store(tmp_path)
    node = _make_node(expected=None, verification_required=False)
    mid = await _governed_mission(components, "r4a05b", store, node)

    rt = _wired_runtime(store, components)
    inst = rt.create_instance(
        mid, "g1", [_make_node(expected=None, verification_required=False)])
    await rt.run_mission(inst.runtime_id)

    assert rt.executor.calls == 1
    assert inst.nodes["n1"].verification_result == VerificationStatus.VERIFIED_SUCCESS
    raw = store.load(mid)
    astate = raw["action_states"]["n1"]
    assert astate["state"] == ActionState.RESULT_RECORDED.value
    assert not astate.get("verification_proof_digest")
    assert not astate.get("verification_evidence")


# ---------------------------------------------------------------------------
# R4-A06 — caller-fabricated evidence is rejected by issuance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_r4_a06_fabricated_evidence_rejected():
    forged = CompletionEvidence(
        source="VerificationGate",
        verified=True,
        verification_method="InMemoryActionVerificationAdapter.verify()",
        details={
            "node_id": "n1", "mission_id": "m", "capability": "c.rt",
            "verification_status": "VERIFIED_SUCCESS",
            "verification_type": "EXACT", "exact_contract_hash": "deadbeef",
            "external_observations": [],
        },
    )
    with pytest.raises(ValueError):
        await _issue_proof(forged, VerificationStatus.VERIFIED_SUCCESS)


# ---------------------------------------------------------------------------
# R4-A07 — genuine gate evidence is accepted by issuance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_r4_a07_genuine_evidence_accepted():
    node = _make_node()
    gate = VerificationGate()
    _, evidence = await gate.evaluate_node(
        node, node.action_contract, _RESULT, mission_id="m")
    proof = await _issue_proof(evidence, VerificationStatus.VERIFIED_SUCCESS)
    assert proof.authority_complete is True


# ---------------------------------------------------------------------------
# R4-A08 — RESULT_RECORDED -> VERIFIED requires the canonical hop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_r4_a08_canonical_transition_required(tmp_path):
    components = _components(tmp_path, tmp_path / ".intent-os")
    store = _mission_store(tmp_path)
    node = _make_node()
    mid = await _governed_mission(
        components, "r4a08", store, node, state=ActionState.RESULT_RECORDED)

    authority = MissionActionAuthority(store)
    raw = store.load(mid)
    revision = raw["revision"]
    _, evidence = await VerificationGate().evaluate_node(
        node, node.action_contract, _RESULT, mission_id=mid)
    proof = await _issue_proof(
        evidence, VerificationStatus.VERIFIED_SUCCESS,
        mission_id=mid, request_digest=raw["plan"][0]["request_semantics_digest"])

    with pytest.raises(ActionTransitionError):
        authority.transition_action(
            mid, "n1", revision, ActionState.RESULT_RECORDED, ActionState.VERIFIED,
            ActionTransitionEvidence(
                requested_by="test", reason="skip-required",
                verification_proof=proof))

    first = MissionActionAuthority(store).transition_action(
        mid, "n1", revision, ActionState.RESULT_RECORDED,
        ActionState.VERIFICATION_REQUIRED,
        ActionTransitionEvidence(requested_by="mission-runtime", reason="required"))
    MissionActionAuthority(store).transition_action(
        mid, "n1", first.mission_revision, ActionState.VERIFICATION_REQUIRED,
        ActionState.VERIFIED,
        ActionTransitionEvidence(requested_by="mission-runtime", reason="verified",
                                 verification_proof=proof))
    assert store.load(mid)["action_states"]["n1"]["state"] == ActionState.VERIFIED.value


# ---------------------------------------------------------------------------
# R4-A09 — store-less legacy resume still restores VERIFIED_SUCCESS (GATE 3)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_r4_a09_storeless_legacy_resume_preserved(tmp_path):
    from intent_kernel.runtime.checkpoints import InMemoryCheckpointRepository

    repo = InMemoryCheckpointRepository()
    rt1 = _storeless_runtime(repo)
    inst1 = rt1.create_instance("m_r4a09", "g", [_storeless_node()])
    await rt1.run_mission(inst1.runtime_id)
    c1 = await repo.get_latest_checkpoint(inst1.runtime_id)
    assert c1 is not None

    rt2 = _storeless_runtime(repo)
    inst2 = rt2.create_instance("m_r4a09", "g", [_storeless_node()])
    assert inst2.nodes["n1"].verification_result is None
    await repo.save_checkpoint(MissionCheckpoint(
        runtime_id=inst2.runtime_id, mission_id="m_r4a09",
        runtime_status="COMPLETED", completed_nodes=["n1"],
        pending_nodes=[], failed_nodes=[],
        verification_state=dict(c1.verification_state),
        completion_evidence=list(c1.completion_evidence),
    ))

    resumed = await rt2.resume(inst2.runtime_id)
    assert resumed.nodes["n1"].verification_result == VerificationStatus.VERIFIED_SUCCESS


# ---------------------------------------------------------------------------
# R4-A10/A11 — durable proof bindings (mission / request) are enforced
# ---------------------------------------------------------------------------

async def _genuine_verified(tmp_path, name, store, components):
    mid = await _governed_mission(components, name, store, _make_node())
    rt = _wired_runtime(store, components)
    inst = rt.create_instance(mid, "g1", [_make_node()])
    await rt.run_mission(inst.runtime_id)
    c1 = await rt.checkpoint_repo.get_latest_checkpoint(inst.runtime_id)
    return mid, rt, c1


async def _resume_with_tampered_evidence(tmp_path, name, mutate):
    components = _components(tmp_path, tmp_path / ".intent-os")
    store = _mission_store(tmp_path)
    mid, rt1, c1 = await _genuine_verified(tmp_path, name, store, components)

    raw = store.load(mid)
    revision = raw["revision"]
    astate = raw["action_states"]["n1"]
    mutate(astate["verification_evidence"])
    astate["verification_proof_digest"] = _recompute_proof_digest(
        astate["verification_evidence"])
    raw["revision"] = revision + 1
    store.commit(revision, MissionRecord.from_dict(raw))
    digest = store.load(mid)["action_states"]["n1"]["verification_proof_digest"]

    rt2 = _wired_runtime(store, components, checkpoint_repo=rt1.checkpoint_repo)
    inst2 = rt2.create_instance(mid, "g2", [_make_node()])
    await rt2.checkpoint_repo.save_checkpoint(MissionCheckpoint(
        runtime_id=inst2.runtime_id, mission_id=mid, runtime_status="COMPLETED",
        completed_nodes=["n1"], pending_nodes=[], failed_nodes=[],
        verification_state={"n1": {
            "verification_result": "VERIFIED_SUCCESS",
            "evidence_id": c1.verification_state["n1"]["evidence_id"],
            "verification_proof_digest": digest,
        }},
        completion_evidence=list(c1.completion_evidence),
    ))
    return await rt2.resume(inst2.runtime_id)


@pytest.mark.asyncio
async def test_r4_a10_cross_mission_proof_rejected(tmp_path):
    def mutate(ev):
        ev["mission_id"] = "some-other-mission"

    resumed = await _resume_with_tampered_evidence(tmp_path, "r4a10", mutate)
    assert resumed.nodes["n1"].verification_result == VerificationStatus.INCONCLUSIVE


@pytest.mark.asyncio
async def test_r4_a11_request_digest_binding_enforced(tmp_path):
    def mutate(ev):
        ev["request_semantics_digest"] = "tampered-request-digest"

    resumed = await _resume_with_tampered_evidence(tmp_path, "r4a11", mutate)
    assert resumed.nodes["n1"].verification_result == VerificationStatus.INCONCLUSIVE


# ---------------------------------------------------------------------------
# R4-A12 — resume neither re-mints nor re-dispatches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_r4_a12_resume_does_not_remint_or_redispatch(tmp_path):
    components = _components(tmp_path, tmp_path / ".intent-os")
    store = _mission_store(tmp_path)
    mid, rt1, c1 = await _genuine_verified(tmp_path, "r4a12", store, components)
    digest_before = store.load(mid)["action_states"]["n1"]["verification_proof_digest"]

    rt2 = _wired_runtime(store, components, checkpoint_repo=rt1.checkpoint_repo)
    inst2 = rt2.create_instance(mid, "g2", [_make_node()])
    await rt2.checkpoint_repo.save_checkpoint(MissionCheckpoint(
        runtime_id=inst2.runtime_id, mission_id=mid, runtime_status="COMPLETED",
        completed_nodes=["n1"], pending_nodes=[], failed_nodes=[],
        verification_state=dict(c1.verification_state),
        completion_evidence=list(c1.completion_evidence),
    ))
    resumed = await rt2.resume(inst2.runtime_id)

    assert resumed.nodes["n1"].verification_result == VerificationStatus.VERIFIED_SUCCESS
    assert rt2.executor.calls == 0
    assert (store.load(mid)["action_states"]["n1"]["verification_proof_digest"]
            == digest_before)
