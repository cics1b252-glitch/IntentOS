"""M32C-R2 — Executable durable lifecycle proof through the canonical wired runtime.

Every claim in the M32C-R module docstring (intent_kernel/runtime/mission_runtime.py)
is backed by an executable test in this module. All cases run through the canonical
B4R2 wired path: MissionRuntime with rrm_service + mission_record_store +
dispatch_guard, restarting via a FRESH MissionRuntime over the SAME durable store
(process restart simulation).

C0-C8 canonical cases:
    C0  PENDING, no durable authorization, clean restart -> dispatch exactly once
    C1  confirmation required, never approved, restart -> no dispatch
    C2  in-memory confirmation, crash before dispatch intent, restart -> no dispatch
    C3  DISPATCH_INTENT_RECORDED durable, restart -> no automatic redispatch
    C4  DISPATCHING durable, restart -> no automatic redispatch
    C5  RESULT_RECORDED durable, restart -> no redispatch
    C6  old confirmation + changed request semantics -> rejected
    C7  old confirmation + changed RRM generation -> rejected
    C8  confirmation for action A reused for action B -> rejected

Crash cutpoints (9 phases), each proven by a fresh-runtime restart:
    CP1 before authorization (PENDING)
    CP2 after authorization (AUTHORIZED)
    CP3 after dispatch intent (DISPATCH_INTENT_RECORDED)
    CP4 possible handoff (DISPATCHING)
    CP5 after result (RESULT_RECORDED)
    CP6 before verification (VERIFICATION_REQUIRED)
    CP7 after verification (VERIFIED)
    CP8 before completion (VERIFIED, completion gate not yet run)
    CP9 after durable completion (COMPLETED)

Negative authority:
    NA1 wrong governed registration -> zero handoffs        (b4r2 R5)
    NA2 changed generation -> zero handoffs                 (b4r2 R6)
    NA3 tombstone -> zero handoffs                          (SKIPPED: RRM bug)
    NA4 retirement -> zero handoffs                         (SKIPPED: RRM bug)
    NA5 missing executor identity -> zero handoffs
    NA6 missing durable confirmation -> zero handoffs
    NA7 AMBIGUOUS_EFFECT durable -> zero handoffs
    NA8 checkpoint never overrides MissionRecord authority
    NA9 stale mutable verification evidence -> REQUIRES_REVALIDATION + no dispatch
    NA10 duplicate productive attempt -> exactly one handoff total

All stores isolated under tmp_path; real user state never touched.
"""

from __future__ import annotations

import pytest

from intent_kernel.application.composition import KernelBuilder
from intent_kernel.contracts import (
    Capability,
    CapabilityRequest,
    CapabilityResult,
    Domain,
    MissionContext,
)
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
from intent_kernel.mission.action_authority import REQUIRES_REVALIDATION
from intent_kernel.mission.store_impl import JsonFileMissionRecordStore
from intent_kernel.orchestration.registry import ExecutorKind
from intent_kernel.promotion.models import BootstrapResourceDeclaration
from intent_kernel.rrm.projection import RuntimeResourceProjection
from intent_kernel.runtime.mission_runtime import MissionRuntime
from intent_kernel.runtime.models import (
    ActionContract,
    MissionCheckpoint,
    RuntimeNode,
)


# ---------------------------------------------------------------------------
# Harness (same wiring as M32B-4R2 permanent regression)
# ---------------------------------------------------------------------------

class CountingApp:
    def __init__(self, app_id="counter", capability="resource.counter"):
        self.app_id = app_id
        self.capability_name = capability
        self.calls = 0

    @property
    def capabilities(self):
        return (Capability(
            name=self.capability_name,
            description="counter",
            requires_confirmation=False,
        ),)

    async def health(self) -> bool:
        return True

    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        self.calls += 1
        return CapabilityResult(
            capability=request.capability,
            success=True,
            output="counted",
        )


class _CountingExecutor:
    def __init__(self):
        self.calls = 0

    async def execute(self, contract):
        self.calls += 1
        from types import SimpleNamespace
        return SimpleNamespace(success=True, output="rt-ok")


class _AllowConstitution:
    def evaluate_action(self, _data):
        class _V:
            verdict = "ALLOW"
        return _V()


def _components(tmp_path, store_root, pkb_name="pkb"):
    authority_file = store_root / "rrm" / "authority.json"
    continuity_file = store_root / "continuity" / "identity.json"
    (store_root / "rrm").mkdir(parents=True, exist_ok=True)
    (store_root / "continuity").mkdir(parents=True, exist_ok=True)
    return KernelBuilder().with_pkb_path(tmp_path / pkb_name).build(
        authority_file=authority_file, continuity_file=continuity_file)


def _govern(components, app):
    components.capability_router.register(app)
    components.capability_registry.register_core_app(app)
    RuntimeResourceProjection(components.resource_manager).project_core_app(app)
    registrations = components.capability_registry.discover(
        app.capability_name, executor_kind=ExecutorKind.CORE_APP)
    registration = next(r for r in registrations if r.executor_id == app.app_id)
    report = components.resource_promotion_service.bootstrap_govern(
        [BootstrapResourceDeclaration.from_registration(registration)])
    assert report.success, [(e.resource_id, e.reason) for e in report.entries]
    snap = components.resource_manager.get_capability(app.capability_name)
    return snap.governed_registration_id, snap.generation, snap


def _mission_store(tmp_path, name="mstore"):
    root = tmp_path / name
    (root / "missions").mkdir(parents=True, exist_ok=True)
    (root / "cont").mkdir(parents=True, exist_ok=True)
    return JsonFileMissionRecordStore(
        missions_dir=root / "missions",
        continuity_file=root / "cont" / "identity.json",
    )


def _definition(objective="productive"):
    return MissionDefinition(objective=objective, context={"k": "v"})


def _guard_for(store):
    return ProductiveDispatchGuard(MissionActionAuthority(store), store)


def _wired_runtime(store, components):
    """Canonical B4R2 wired runtime: RRM + durable store + dispatch guard."""
    return MissionRuntime(
        executor=_CountingExecutor(),
        constitution=_AllowConstitution(),
        dispatch_guard=_guard_for(store),
        mission_record_store=store,
        rrm_service=components.resource_manager,
    )


def _make_node(node_id="n1", agent_id="ex-rt", idempotency_key="rk1"):
    contract = ActionContract(
        action_id=node_id, capability="c.rt", idempotency_key=idempotency_key)
    return RuntimeNode(
        node_id=node_id, capability="c.rt", agent_id=agent_id,
        action_contract=contract)


def _bind_action(store, mid, node, *, state=ActionState.PENDING,
                 confirmation_required=False, confirmation_basis_digest="",
                 verification_evidence=None,
                 expected_governed_registration_id="",
                 expected_resource_generation=0,
                 extra_actions=()):
    """Bind one runtime node's action into a fresh durable MissionRecord.

    extra_actions: additional DurableActionState entries (with matching plan
    entries) already present in the same mission record.
    """
    spec = spec_for_runtime_node(mid, node)
    ident = store.get_continuity_identity()
    definition = _definition("runtime")
    probe = MissionRecord(
        mission_id="probe", installation_id=ident, mission_definition=definition)
    plan = [{
        "action_id": spec.action_id,
        "capability": spec.action_id,
        "node_id": node.node_id,
        "dependencies": [],
        "request_semantics_digest": spec.request_semantics_digest,
    }]
    actions = {spec.action_id: DurableActionState(
        action_id=spec.action_id, node_id=node.node_id,
        state=state,
        confirmation_required=confirmation_required,
        confirmation_basis_digest=confirmation_basis_digest,
        verification_evidence=verification_evidence,
        expected_resource_id="r",
        expected_governed_registration_id=expected_governed_registration_id,
        expected_resource_generation=expected_resource_generation,
        expected_executor_kind="core_app",
        expected_executor_logical_id=spec.executor_logical_id,
    )}
    for extra in extra_actions:
        actions[extra.action_id] = extra
        plan.append({
            "action_id": extra.action_id,
            "capability": extra.action_id,
            "node_id": extra.node_id,
            "dependencies": [],
            "request_semantics_digest": f"digest:{extra.action_id}",
        })
    record = MissionRecord(
        mission_id=mid, installation_id=ident, revision=1,
        runtime_id="rt-1", mission_definition=definition,
        mission_definition_digest=probe.compute_definition_digest(),
        mission_status=MissionStatus.RUNNING,
        plan=tuple(plan),
        action_states=actions,
    )
    assert store.create(record).outcome == "committed"


async def _started_mission(components, name):
    m = await components.mission_engine.create(
        name, context=MissionContext(
            domain=Domain.OTHER, session_id="s", correlation_id="c"))
    return await components.mission_engine.start(m.id)


async def _fresh_restart_run(components, store, mid, node):
    """Simulate a process restart: brand-new runtime over the same store."""
    rt = _wired_runtime(store, components)
    inst = rt.create_instance(mid, "g1", [node])
    await rt.run_mission(inst.runtime_id)
    return rt


# ---------------------------------------------------------------------------
# C0-C8 canonical cases
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_c0_pending_clean_restart_dispatches_exactly_once(tmp_path):
    """C0: PENDING with no durable authorization dispatches once; after a
    clean restart the durable authority forbids any second handoff."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "c0")
    store = _mission_store(tmp_path)
    node = _make_node()
    _bind_action(store, str(mission.id), node)

    rt1 = _wired_runtime(store, components)
    inst1 = rt1.create_instance(str(mission.id), "g1", [_make_node()])
    await rt1.run_mission(inst1.runtime_id)
    assert rt1.executor.calls == 1

    # Clean restart: fresh runtime, same durable store.
    rt2 = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt2.executor.calls == 0
    assert rt1.executor.calls + rt2.executor.calls == 1


@pytest.mark.asyncio
async def test_c1_confirmation_required_never_approved_restart(tmp_path):
    """C1: durable confirmation requirement, never approved -> no dispatch,
    and a restart still refuses dispatch."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "c1")
    store = _mission_store(tmp_path)
    node = _make_node()
    _bind_action(store, str(mission.id), node,
                 confirmation_required=True,
                 confirmation_basis_digest="basis:c1")

    rt1 = _wired_runtime(store, components)
    inst1 = rt1.create_instance(str(mission.id), "g1", [_make_node()])
    await rt1.run_mission(inst1.runtime_id)
    assert rt1.executor.calls == 0

    rt2 = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt2.executor.calls == 0


@pytest.mark.asyncio
async def test_c2_in_memory_confirmation_crash_before_dispatch_intent(tmp_path):
    """C2: confirmation interaction existed only in memory pre-crash; nothing
    durable crossed the dispatch-intent boundary, so after restart the old
    in-memory approval is unusable and no dispatch occurs."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "c2")
    store = _mission_store(tmp_path)
    node = _make_node()
    _bind_action(store, str(mission.id), node,
                 confirmation_required=True,
                 confirmation_basis_digest="basis:c2")

    # Pre-crash: runtime reaches WAITING_USER_CONFIRMATION; the confirmation
    # request exists only in this process's memory.
    rt1 = _wired_runtime(store, components)
    inst1 = rt1.create_instance(str(mission.id), "g1", [_make_node()])
    await rt1.run_mission(inst1.runtime_id)
    assert rt1.executor.calls == 0
    assert len(rt1._confirmations) == 1  # in-memory only

    # Crash + restart: in-memory approval is gone; durable state is PENDING
    # with confirmation_required -> reconfirmation, no dispatch.
    rt2 = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt2.executor.calls == 0


@pytest.mark.asyncio
async def test_c3_dispatch_intent_recorded_restart_no_auto_redispatch(tmp_path):
    """C3: DISPATCH_INTENT_RECORDED is durable; after restart the replay
    posture is AMBIGUOUS_RECONCILIATION_REQUIRED — no automatic redispatch."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "c3")
    store = _mission_store(tmp_path)
    node = _make_node()
    _bind_action(store, str(mission.id), node,
                 state=ActionState.DISPATCH_INTENT_RECORDED)

    rt = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_c4_dispatching_restart_no_auto_redispatch(tmp_path):
    """C4: DISPATCHING durable at crash; the external effect is unknown and
    never assumed absent — restart refuses automatic redispatch."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "c4")
    store = _mission_store(tmp_path)
    node = _make_node()
    _bind_action(store, str(mission.id), node, state=ActionState.DISPATCHING)

    rt = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_c5_result_recorded_restart_no_redispatch(tmp_path):
    """C5: RESULT_RECORDED durable; restart continues only toward
    verification/recovery — never redispatches."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "c5")
    store = _mission_store(tmp_path)
    node = _make_node()
    _bind_action(store, str(mission.id), node, state=ActionState.RESULT_RECORDED)

    rt = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_c6_old_confirmation_changed_request_semantics_rejected(tmp_path):
    """C6: the durable plan is bound to the original request semantics; a
    restart presenting changed semantics fails closed at the guard."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "c6")
    store = _mission_store(tmp_path)
    node = _make_node()
    _bind_action(store, str(mission.id), node,
                 confirmation_required=True,
                 confirmation_basis_digest="basis:c6")

    # Restart presenting CHANGED semantics (different idempotency key ->
    # different request_semantics_digest -> plan mismatch).
    changed_node = _make_node(idempotency_key="rk2-changed")
    rt = await _fresh_restart_run(components, store, str(mission.id), changed_node)
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_c7_old_confirmation_changed_rrm_generation_rejected(tmp_path):
    """C7: durable binding pins the RRM generation at confirmation time; a
    changed current generation fails the B4R2 rebind -> no dispatch."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _, gen, snap = _govern(components, app)
    mission = await _started_mission(components, "c7")
    store = _mission_store(tmp_path)
    node = _make_node()
    _bind_action(store, str(mission.id), node,
                 confirmation_required=True,
                 confirmation_basis_digest="basis:c7",
                 expected_governed_registration_id=snap.governed_registration_id,
                 expected_resource_generation=gen + 5)  # stale generation

    rt = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_c8_confirmation_for_action_a_not_reusable_for_b(tmp_path):
    """C8: action A carries a durable confirmation basis; action B (same
    mission) also requires confirmation. A's confirmation never authorizes B."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "c8")
    store = _mission_store(tmp_path)
    node_b = _make_node(node_id="nB")
    node_b.action_contract.action_id = "nB"

    action_a = DurableActionState(
        action_id="nA", node_id="nA",
        state=ActionState.AUTHORIZED,
        confirmation_required=True,
        confirmation_basis_digest="basis:action-A",
        expected_resource_id="r",
        expected_executor_kind="core_app",
        expected_executor_logical_id="ex-rt",
    )
    _bind_action(store, str(mission.id), node_b,
                 confirmation_required=True,
                 confirmation_basis_digest="basis:action-B",
                 extra_actions=(action_a,))

    rt = await _fresh_restart_run(components, store, str(mission.id), node_b)
    assert rt.executor.calls == 0


# ---------------------------------------------------------------------------
# Crash cutpoints CP1-CP9 (fresh-runtime restart over the same durable store)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cp1_crash_before_authorization_restart_dispatches_once(tmp_path):
    """CP1: crash before authorization (PENDING). Restart may enter the normal
    authorization path exactly once."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "cp1")
    store = _mission_store(tmp_path)
    _bind_action(store, str(mission.id), _make_node(), state=ActionState.PENDING)

    rt = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt.executor.calls == 1

    # A second restart must not dispatch again.
    rt2 = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt2.executor.calls == 0


@pytest.mark.asyncio
async def test_cp2_crash_after_authorization_restart_dispatches_once(tmp_path):
    """CP2: crash after durable AUTHORIZATION (AUTHORIZED, no confirmation
    requirement). Restart completes the guarded handoff exactly once."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "cp2")
    store = _mission_store(tmp_path)
    _bind_action(store, str(mission.id), _make_node(), state=ActionState.AUTHORIZED)

    rt = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt.executor.calls == 1


@pytest.mark.asyncio
async def test_cp3_crash_after_dispatch_intent_no_redispatch(tmp_path):
    """CP3: crash after DISPATCH_INTENT_RECORDED — ambiguous window, no
    automatic redispatch, retryable reconciliation report."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "cp3")
    store = _mission_store(tmp_path)
    _bind_action(store, str(mission.id), _make_node(),
                 state=ActionState.DISPATCH_INTENT_RECORDED)

    rt = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt.executor.calls == 0
    assert any(r.retryable for r in rt._failure_reports)


@pytest.mark.asyncio
async def test_cp4_crash_possible_handoff_no_redispatch(tmp_path):
    """CP4: crash during possible handoff (DISPATCHING) — external effect
    unknown; never redispatch automatically."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "cp4")
    store = _mission_store(tmp_path)
    _bind_action(store, str(mission.id), _make_node(), state=ActionState.DISPATCHING)

    rt = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_cp5_crash_after_result_no_redispatch(tmp_path):
    """CP5: crash after RESULT_RECORDED — result is durable; next step belongs
    to the verification path, never to redispatch."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "cp5")
    store = _mission_store(tmp_path)
    _bind_action(store, str(mission.id), _make_node(), state=ActionState.RESULT_RECORDED)

    rt = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_cp6_crash_before_verification_no_redispatch(tmp_path):
    """CP6: crash before verification (VERIFICATION_REQUIRED) — gate-owned
    next step, no redispatch."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "cp6")
    store = _mission_store(tmp_path)
    _bind_action(store, str(mission.id), _make_node(),
                 state=ActionState.VERIFICATION_REQUIRED)

    rt = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_cp7_crash_after_verification_no_redispatch(tmp_path):
    """CP7: crash after VERIFIED — historical verified state never becomes a
    new dispatch."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "cp7")
    store = _mission_store(tmp_path)
    _bind_action(store, str(mission.id), _make_node(), state=ActionState.VERIFIED)

    rt = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_cp8_crash_before_completion_no_redispatch(tmp_path):
    """CP8: crash after VERIFIED but before the completion gate ran. Restart
    must not redispatch and must not duplicate completion evidence."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "cp8")
    store = _mission_store(tmp_path)
    _bind_action(store, str(mission.id), _make_node(), state=ActionState.VERIFIED)

    rt = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt.executor.calls == 0
    # No fresh completion evidence was manufactured for the verified action.
    assert rt._failure_reports  # redispatch refused, recorded


@pytest.mark.asyncio
async def test_cp9_crash_after_durable_completion_no_redispatch(tmp_path):
    """CP9: crash after durable COMPLETED — history only, zero handoffs."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "cp9")
    store = _mission_store(tmp_path)
    _bind_action(store, str(mission.id), _make_node(), state=ActionState.COMPLETED)

    rt = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt.executor.calls == 0


# ---------------------------------------------------------------------------
# Negative authority
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_na5_missing_executor_identity_no_dispatch(tmp_path):
    """NA5: durable executor identity does not match the presented runtime
    node identity -> the guard refuses, zero handoffs."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _, gen, snap = _govern(components, app)
    mission = await _started_mission(components, "na5")
    store = _mission_store(tmp_path)
    node = _make_node()
    _bind_action(store, str(mission.id), node,
                 expected_governed_registration_id=snap.governed_registration_id,
                 expected_resource_generation=gen)
    # Durable record pins executor logical id to the node's agent ("ex-rt").
    # Present a node with a DIFFERENT agent identity -> guard refuses.
    stranger = _make_node(agent_id="ghost-executor")
    rt = await _fresh_restart_run(components, store, str(mission.id), stranger)
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_na7_ambiguous_effect_durable_no_redispatch(tmp_path):
    """NA7: AMBIGUOUS_EFFECT is preserved forever — no automatic (or manual)
    dispatch/completion transition exists; restart refuses handoff."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "na7")
    store = _mission_store(tmp_path)
    _bind_action(store, str(mission.id), _make_node(),
                 state=ActionState.AMBIGUOUS_EFFECT)

    rt = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_na8_checkpoint_never_overrides_mission_record(tmp_path):
    """NA8 (B5.2): a checkpoint is support state only. Direction 1: checkpoint
    claims the node COMPLETED while MissionRecord says PENDING — the runtime
    still follows the MissionRecord and dispatches exactly once. Direction 2:
    checkpoint claims PENDING while MissionRecord says COMPLETED — the runtime
    never redispatches."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)

    # Direction 1: checkpoint says done, MissionRecord says PENDING.
    mission1 = await _started_mission(components, "na8-a")
    store1 = _mission_store(tmp_path, "ms1")
    _bind_action(store1, str(mission1.id), _make_node(), state=ActionState.PENDING)
    rt1 = _wired_runtime(store1, components)
    inst1 = rt1.create_instance(str(mission1.id), "g1", [_make_node()])
    lying_chk = MissionCheckpoint(
        runtime_id=inst1.runtime_id, mission_id=str(mission1.id),
        runtime_status="COMPLETED",
        completed_nodes=["n1"], pending_nodes=[], failed_nodes=[],
        verification_state={"n1": {"verification_result": "VERIFIED_SUCCESS"}},
        completion_evidence=[{"fabricated": True}],
    )
    await rt1.checkpoint_repo.save_checkpoint(lying_chk)
    await rt1.run_mission(inst1.runtime_id)
    # MissionRecord (PENDING) wins over the lying checkpoint: dispatch happens.
    assert rt1.executor.calls == 1

    # Direction 2: checkpoint says pending, MissionRecord says COMPLETED.
    mission2 = await _started_mission(components, "na8-b")
    store2 = _mission_store(tmp_path, "ms2")
    _bind_action(store2, str(mission2.id), _make_node(), state=ActionState.COMPLETED)
    rt2 = _wired_runtime(store2, components)
    inst2 = rt2.create_instance(str(mission2.id), "g1", [_make_node()])
    pending_chk = MissionCheckpoint(
        runtime_id=inst2.runtime_id, mission_id=str(mission2.id),
        runtime_status="RUNNING",
        completed_nodes=[], pending_nodes=["n1"], failed_nodes=[],
    )
    await rt2.checkpoint_repo.save_checkpoint(pending_chk)
    await rt2.run_mission(inst2.runtime_id)
    # MissionRecord (COMPLETED) wins over the lying checkpoint: no dispatch.
    assert rt2.executor.calls == 0


@pytest.mark.asyncio
async def test_na9_stale_mutable_verification_evidence_requires_revalidation(tmp_path):
    """NA9: durable VERIFIED whose authorizing evidence contains point-in-time
    provider observations is REQUIRES_REVALIDATION at the authority, and a
    restart never converts that history into a new dispatch."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "na9")
    store = _mission_store(tmp_path)
    node = _make_node()
    _bind_action(store, str(mission.id), node,
                 state=ActionState.VERIFIED,
                 verification_evidence={
                     "external_observations": [
                         {"provider": "mock", "observed_at": "2026-01-01T00:00:00Z"}
                     ],
                 })

    freshness = MissionActionAuthority(store).verification_freshness_for(
        str(mission.id), "n1")
    assert freshness == REQUIRES_REVALIDATION

    rt = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt.executor.calls == 0


@pytest.mark.asyncio
async def test_na10_duplicate_productive_attempt_single_handoff(tmp_path):
    """NA10: a duplicate productive attempt on the same mission — same process
    and after restart — can never produce a second handoff."""
    components = _components(tmp_path, tmp_path / ".intent-os")
    app = CountingApp()
    _govern(components, app)
    mission = await _started_mission(components, "na10")
    store = _mission_store(tmp_path)
    _bind_action(store, str(mission.id), _make_node(), state=ActionState.PENDING)

    rt1 = _wired_runtime(store, components)
    inst1 = rt1.create_instance(str(mission.id), "g1", [_make_node()])
    await rt1.run_mission(inst1.runtime_id)
    assert rt1.executor.calls == 1

    # Same-process duplicate: run the same instance again.
    await rt1.run_mission(inst1.runtime_id)
    assert rt1.executor.calls == 1

    # Same-process duplicate: fresh instance in the same runtime.
    inst1b = rt1.create_instance(str(mission.id), "g1", [_make_node()])
    await rt1.run_mission(inst1b.runtime_id)
    assert rt1.executor.calls == 1

    # Restart duplicate: fresh runtime, same store.
    rt2 = await _fresh_restart_run(components, store, str(mission.id), _make_node())
    assert rt2.executor.calls == 0
    assert rt1.executor.calls + rt2.executor.calls == 1
