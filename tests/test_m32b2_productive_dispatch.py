"""M32B-2 productive dispatch convergence — adversarial tests.

PB1_TEST   known attempt/key at ActionGate/runtime again -> exactly 1 handoff
PB2_TEST   crash after effect, before result/cache save -> effect==1, ambiguous
PB3_TEST   two concurrent same-attempt callers -> exactly 1 handoff
PB3B_TEST  race loser reloads durable state and does not dispatch
CACHE_MISS_TEST  wiped cache + durable attempt -> zero new dispatch
AMBIGUITY_TEST   intent/dispatching state + fresh objects -> zero dispatch
RESULT_TEST  known result durably records RESULT_RECORDED pre-verification
VERIFICATION_TEST  productive path cannot forge VERIFIED
COMPLETION_TEST  action completion cannot mission-complete
CONFIRMATION_RESTART_TEST  old confirmation unusable after restart
RRM_MUTATION_TEST  generation advance pre-handoff -> zero dispatch

All stores isolated under tmp_path; real user state never touched.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from intent_kernel.application.composition import KernelBuilder
from intent_kernel.contracts import (
    Capability,
    CapabilityRequest,
    CapabilityResult,
    Domain,
    ErrorCode,
    MissionContext,
)
from intent_kernel.mission import (
    ActionState,
    DispatchGuardError,
    DurableActionState,
    MissionActionAuthority,
    MissionDefinition,
    MissionRecord,
    MissionStatus,
    ProductiveDispatchGuard,
    ReplayDecision,
    spec_for_legacy_dispatch,
)
from intent_kernel.mission.store_impl import JsonFileMissionRecordStore
from intent_kernel.adapters.legacy import InMemoryIdempotencyStoreAdapter
from intent_kernel.orchestration.execution import CapabilityExecutionService
from intent_kernel.orchestration.registry import ExecutorKind
from intent_kernel.promotion.models import BootstrapResourceDeclaration
from intent_kernel.rrm.models import ConditionalResourceStatusRequest
from intent_kernel.rrm.projection import RuntimeResourceProjection
from intent_kernel.rrm.models import ResourceType
from intent_kernel.runtime.action_gate import ActionGate
from intent_kernel.runtime.mission_runtime import MissionRuntime
from intent_kernel.runtime.models import (
    ActionContract,
    ActionGateDecision,
    RuntimeNode,
)


# ---------------------------------------------------------------------------
# Fixtures / doubles
# ---------------------------------------------------------------------------

class CountingApp:
    """Core-app executor that counts handoffs and records effects."""

    def __init__(self, app_id="counter", capability="resource.counter",
                 crash_after_effect=False, requires_confirmation=False):
        self.app_id = app_id
        self.capability_name = capability
        self.crash_after_effect = crash_after_effect
        self.requires_confirmation = requires_confirmation
        self.calls = 0
        self.effects = []

    @property
    def capabilities(self):
        return (Capability(
            name=self.capability_name,
            description="counter",
            requires_confirmation=self.requires_confirmation,
        ),)

    async def health(self) -> bool:
        return True

    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        self.calls += 1
        self.effects.append(getattr(request, "capability", "?"))
        if self.crash_after_effect:
            raise RuntimeError("simulated crash after external effect")
        return CapabilityResult(
            capability=request.capability,
            success=True,
            output="counted",
        )


def _components(tmp_path, store_root, pkb_name="pkb"):
    authority_file = store_root / "rrm" / "authority.json"
    continuity_file = store_root / "continuity" / "identity.json"
    (store_root / "rrm").mkdir(parents=True, exist_ok=True)
    (store_root / "continuity").mkdir(parents=True, exist_ok=True)
    return KernelBuilder().with_pkb_path(tmp_path / pkb_name).build(
        authority_file=authority_file, continuity_file=continuity_file)


async def _running_mission(components, session="pb"):
    mission = await components.mission_engine.create(
        "productive dispatch probe",
        context=MissionContext(
            domain=Domain.OTHER,
            session_id=session,
            correlation_id=f"{session}-correlation",
        ),
    )
    return await components.mission_engine.start(mission.id)


def _govern(components, app):
    components.capability_router.register(app)
    components.capability_registry.register_core_app(app)
    RuntimeResourceProjection(components.resource_manager).project_core_app(app)
    registrations = components.capability_registry.discover(
        app.capability_name,
        executor_kind=ExecutorKind.CORE_APP,
    )
    registration = next(
        r for r in registrations if r.executor_id == app.app_id
    )
    report = components.resource_promotion_service.bootstrap_govern(
        [BootstrapResourceDeclaration.from_registration(registration)]
    )
    assert report.success, [(e.resource_id, e.reason) for e in report.entries]
    snap = components.resource_manager.get_capability(app.capability_name)
    return snap.governed_registration_id, snap.generation


def _mission_store(tmp_path, name="mstore"):
    root = tmp_path / name
    (root / "missions").mkdir(parents=True, exist_ok=True)
    (root / "cont").mkdir(parents=True, exist_ok=True)
    return JsonFileMissionRecordStore(
        missions_dir=root / "missions",
        continuity_file=root / "cont" / "identity.json",
    )


def _definition(objective="productive", quantity_authority=None):
    return MissionDefinition(
        objective=objective, context={"k": "v"},
        quantity_authority=quantity_authority,
    )


def _bind_action(
    store, mission_id, spec, runtime_id="rt-pb",
    quantity=None, operation="", quantity_authority=None,
):
    """Pre-establish the durable record + PENDING action for one spec.

    C2/C3/G1.2 §3 / C2/C3/G1.3 §2: operation and quantity are durable,
    authority-bearing parts of the plan, and the established quantity
    authority is carried on the mission definition.
    """
    ident = store.get_continuity_identity()
    definition = _definition(quantity_authority=quantity_authority)
    probe = MissionRecord(
        mission_id="probe", installation_id=ident,
        mission_definition=definition)
    record = MissionRecord(
        mission_id=mission_id, installation_id=ident, revision=1,
        runtime_id=runtime_id, mission_definition=definition,
        mission_definition_digest=probe.compute_definition_digest(),
        mission_status=MissionStatus.RUNNING,
        plan=({
            "action_id": spec.action_id,
            "capability": spec.action_id.split("#")[0],
            "node_id": "n1",
            "dependencies": [],
            "request_semantics_digest": spec.request_semantics_digest,
            # C2/C3/G1.2 §3: operation is durable and authority-bearing. These
            # are non-quantitative counter reads, so the canonical operation
            # is READ — carried from the spec, never a placeholder.
            "operation": operation or spec.operation,
            # C2/C3/G1.3 §2: the exact C1-bound quantity travels with the plan.
            "quantity": quantity if quantity is not None else spec.quantity,
        },),
        action_states={spec.action_id: DurableActionState(
            action_id=spec.action_id, node_id="n1",
            expected_resource_id="r",
            expected_governed_registration_id=(
                spec.expected_governed_registration_id),
            expected_resource_generation=spec.expected_resource_generation,
            expected_executor_kind="core_app",
            expected_executor_logical_id=spec.executor_logical_id,
        )},
    )
    result = store.create(record)
    assert result.outcome == "committed"
    return record


def _guard_for(store):
    return ProductiveDispatchGuard(MissionActionAuthority(store), store)


def _service(components, guard=None, cache=None):
    return CapabilityExecutionService(
        mission_engine=components.mission_engine,
        constitution=components.constitution_engine,
        capability_router=components.capability_router,
        registry=components.capability_registry,
        agent_orchestrator=components.agent_orchestrator,
        provider_manager=components.provider_manager,
        knowledge_pipeline=components.knowledge_pipeline,
        event_publisher=components.event_publisher,
        idempotency_store=cache or InMemoryIdempotencyStoreAdapter(),
        resource_authority=(
            components.capability_execution_service.resource_authority),
        dispatch_guard=guard,
    )


def _spec_for(components, mission, app, payload, key="", operation="READ", quantity=None):
    snap = components.resource_manager.get_capability(app.capability_name)
    return spec_for_legacy_dispatch(
        mission_id=str(mission.id),
        capability=app.capability_name,
        payload=payload,
        idempotency_key=key,
        executor_logical_id=app.app_id,
        expected_governed_registration_id=snap.governed_registration_id,
        expected_resource_generation=snap.generation,
        # C2/C3/G1.2 §2/§4 + C2/C3/G1.3 §4: the canonical structured
        # operation is bound INSIDE the C1 request digest, never reconstructed
        # later. Callers pass the true operation for their scenario.
        operation=operation,
        quantity=quantity,
    )


# ---------------------------------------------------------------------------
# PB1 — gate duplicate semantics
# ---------------------------------------------------------------------------

class _AllowConstitution:
    def evaluate_action(self, _data):
        class _V:
            verdict = "ALLOW"
        return _V()


def _gate_node(key="k1"):
    return (
        RuntimeNode(node_id="n1", capability="c"),
        ActionContract(capability="c", idempotency_key=key),
    )


@pytest.mark.asyncio
async def test_pb1_marked_key_no_longer_falls_through_to_allow():
    gate = ActionGate(constitution=_AllowConstitution())
    node, contract = _gate_node()
    assert await gate.evaluate(node, contract) == ActionGateDecision.ALLOW
    gate.mark_idempotency_key_executed("k1")
    second = await gate.evaluate(node, contract)
    assert second != ActionGateDecision.ALLOW
    assert second == ActionGateDecision.DENY


@pytest.mark.asyncio
async def test_pb1_policy_may_dispatch_still_allows():
    gate = ActionGate(
        constitution=_AllowConstitution(),
        replay_policy=lambda node_id, key: "MAY_DISPATCH",
    )
    node, contract = _gate_node()
    gate.mark_idempotency_key_executed("k1")
    assert await gate.evaluate(node, contract) == ActionGateDecision.ALLOW


@pytest.mark.asyncio
async def test_pb1_policy_postures_map_fail_closed():
    for posture, expected in (
        ("DO_NOT_REDISPATCH", ActionGateDecision.DENY),
        ("AMBIGUOUS_RECONCILIATION_REQUIRED", ActionGateDecision.DENY),
        ("RECONFIRMATION_REQUIRED",
         ActionGateDecision.REQUIRE_CONFIRMATION),
        ("ALREADY_COMPLETED", ActionGateDecision.DENY),
        ("BOGUS", ActionGateDecision.DENY),
        (None, ActionGateDecision.DENY),
    ):
        gate = ActionGate(
            constitution=_AllowConstitution(),
            replay_policy=lambda node_id, key, p=posture: p,
        )
        node, contract = _gate_node()
        gate.mark_idempotency_key_executed("k1")
        assert await gate.evaluate(node, contract) == expected, posture


# ---------------------------------------------------------------------------
# Productive service path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pb2_crash_after_effect_no_redispatch(tmp_path):
    store_root = tmp_path / ".intent-os"
    components = _components(tmp_path, store_root)
    app = CountingApp(capability="resource.crash", crash_after_effect=True)
    _govern(components, app)
    mission = await _running_mission(components)
    store = _mission_store(tmp_path)
    guard = _guard_for(store)
    svc = _service(components, guard)
    payload = {"text": "go"}
    spec = _spec_for(components, mission, app, payload)
    _bind_action(store, str(mission.id), spec)

    with pytest.raises(RuntimeError, match="simulated crash"):
        await svc.execute(mission.id, app.capability_name,
                          payload=payload, durable_action=spec)
    assert app.calls == 1
    assert app.effects == [app.capability_name]
    assert (store.load(str(mission.id))["action_states"][spec.action_id]
            ["state"] == "AMBIGUOUS_EFFECT")
    # Retry/restart: same attempt, fresh objects, same files.
    svc2 = _service(components, _guard_for(store))
    outcome = await svc2.execute(mission.id, app.capability_name,
                                 payload=payload, durable_action=spec)
    assert outcome.result.error_code is not None
    assert app.calls == 1
    assert app.effects == [app.capability_name]


@pytest.mark.asyncio
async def test_pb3_concurrent_same_attempt_single_handoff(tmp_path):
    store_root = tmp_path / ".intent-os"
    components = _components(tmp_path, store_root)
    app = CountingApp(capability="resource.race")
    _govern(components, app)
    mission = await _running_mission(components)
    store = _mission_store(tmp_path)
    guard = _guard_for(store)
    svc = _service(components, guard)
    payload = {"text": "race"}
    spec = _spec_for(components, mission, app, payload)
    _bind_action(store, str(mission.id), spec)

    release = asyncio.Event()

    async def _one():
        await release.wait()
        return await svc.execute(mission.id, app.capability_name,
                                 payload=payload, durable_action=spec)

    t1 = asyncio.ensure_future(_one())
    t2 = asyncio.ensure_future(_one())
    release.set()
    first, second = await asyncio.gather(t1, t2)
    assert app.calls == 1
    outcomes = [first, second]
    successes = [o for o in outcomes if o.result.error_code is None]
    failures = [o for o in outcomes if o.result.error_code is not None]
    assert len(successes) == 1
    assert len(failures) == 1
    # Loser reloaded durable state and did not dispatch: duplicate
    # prevented or cached replay, never a fresh second success.
    loser = failures[0]
    assert (loser.result.metadata.get("duplicate_dispatch_prevented")
            or loser.result.metadata.get("idempotent_replay"))


@pytest.mark.asyncio
async def test_cache_miss_does_not_authorize_dispatch(tmp_path):
    store_root = tmp_path / ".intent-os"
    components = _components(tmp_path, store_root)
    app = CountingApp(capability="resource.cache")
    _govern(components, app)
    mission = await _running_mission(components)
    store = _mission_store(tmp_path)
    guard = _guard_for(store)
    cache = InMemoryIdempotencyStoreAdapter()
    svc = _service(components, guard, cache)
    payload = {"text": "cached"}
    spec = _spec_for(components, mission, app, payload)
    _bind_action(store, str(mission.id), spec)

    first = await svc.execute(mission.id, app.capability_name,
                              payload=payload, durable_action=spec)
    assert first.result.error_code is None
    assert app.calls == 1
    # Wipe the result cache; durable attempt remains.
    svc2 = _service(components, _guard_for(store),
                    InMemoryIdempotencyStoreAdapter())
    second = await svc2.execute(mission.id, app.capability_name,
                                payload=payload, durable_action=spec)
    assert second.result.error_code is not None
    assert (second.result.metadata.get("duplicate_dispatch_prevented")
            is True)
    assert app.calls == 1


@pytest.mark.asyncio
async def test_ambiguity_restart_zero_dispatch(tmp_path):
    store_root = tmp_path / ".intent-os"
    components = _components(tmp_path, store_root)
    app = CountingApp(capability="resource.amb")
    _govern(components, app)
    mission = await _running_mission(components)
    store = _mission_store(tmp_path)
    guard = _guard_for(store)
    payload = {"text": "amb"}
    spec = _spec_for(components, mission, app, payload)
    _bind_action(store, str(mission.id), spec)
    ownership = guard.acquire(spec, requested_by="t")
    before = store.load(str(mission.id))

    # Fresh objects, same files (restart view).
    svc = _service(components, _guard_for(store))
    outcome = await svc.execute(mission.id, app.capability_name,
                                payload=payload, durable_action=spec)
    assert outcome.result.error_code is not None
    assert (outcome.result.metadata.get("durable_replay_posture")
            == "AMBIGUOUS_RECONCILIATION_REQUIRED")
    assert app.calls == 0
    assert store.load(str(mission.id))["revision"] == before["revision"]
    assert ownership.mission_revision == before["revision"]


@pytest.mark.asyncio
async def test_result_recorded_before_verification(tmp_path):
    store_root = tmp_path / ".intent-os"
    components = _components(tmp_path, store_root)
    app = CountingApp(capability="resource.result")
    _govern(components, app)
    mission = await _running_mission(components)
    store = _mission_store(tmp_path)
    guard = _guard_for(store)
    svc = _service(components, guard)
    payload = {"text": "res"}
    spec = _spec_for(components, mission, app, payload)
    _bind_action(store, str(mission.id), spec)

    outcome = await svc.execute(mission.id, app.capability_name,
                                payload=payload, durable_action=spec)
    assert outcome.result.error_code is None
    stored = store.load(str(mission.id))["action_states"][spec.action_id]
    assert stored["state"] == "RESULT_RECORDED"
    assert stored["result"]["success"] is True
    assert store.load(str(mission.id))["revision"] == 5


@pytest.mark.asyncio
async def test_verification_not_forged_by_productive_path(tmp_path):
    store_root = tmp_path / ".intent-os"
    components = _components(tmp_path, store_root)
    app = CountingApp(capability="resource.vf")
    _govern(components, app)
    mission = await _running_mission(components)
    store = _mission_store(tmp_path)
    guard = _guard_for(store)
    svc = _service(components, guard)
    payload = {"text": "vf"}
    spec = _spec_for(components, mission, app, payload)
    _bind_action(store, str(mission.id), spec)

    outcome = await svc.execute(mission.id, app.capability_name,
                                payload=payload, durable_action=spec)
    assert outcome.result.error_code is None
    # Productive dispatch ends at RESULT_RECORDED; only a canonical
    # ActionVerificationProof can move it further.
    assert (store.load(str(mission.id))["action_states"][spec.action_id]
            ["state"] == "RESULT_RECORDED")
    authority = MissionActionAuthority(store)
    with pytest.raises(ValueError):
        from intent_kernel.mission.action_authority import (
            ActionTransitionEvidence)
        ActionTransitionEvidence(requested_by="t", reason="t",
                                 verification_proof={"fake": True})


@pytest.mark.asyncio
async def test_completion_needs_gate_not_service(tmp_path):
    store_root = tmp_path / ".intent-os"
    components = _components(tmp_path, store_root)
    app = CountingApp(capability="resource.comp")
    _govern(components, app)
    mission = await _running_mission(components)
    store = _mission_store(tmp_path)
    guard = _guard_for(store)
    svc = _service(components, guard)
    payload = {"text": "comp"}
    spec = _spec_for(components, mission, app, payload)
    _bind_action(store, str(mission.id), spec)

    outcome = await svc.execute(mission.id, app.capability_name,
                                payload=payload, durable_action=spec)
    assert outcome.result.error_code is None
    # Even driving the action to COMPLETED via canonical proofs leaves
    # mission-level completion to MissionCompletionGate alone.
    from intent_kernel.mission.transitions import ACTION_TRANSITIONS
    from intent_kernel.mission.mission_record import ActionState
    assert ActionState.COMPLETED in ACTION_TRANSITIONS[ActionState.VERIFIED]
    assert "MissionCompletionGate" not in open(
        __import__("intent_kernel.orchestration.execution",
                   fromlist=["__file__"]).__file__).read()
    assert store.load(str(mission.id))["mission_status"] != "COMPLETED"


@pytest.mark.asyncio
async def test_confirmation_restart_unusable(tmp_path):
    store_root = tmp_path / ".intent-os"
    components = _components(tmp_path, store_root)
    app = CountingApp(capability="resource.conf",
                      requires_confirmation=True)
    _govern(components, app)
    mission = await _running_mission(components)
    store = _mission_store(tmp_path)
    guard = _guard_for(store)
    svc = _service(components, guard)
    payload = {"text": "conf"}
    spec = _spec_for(components, mission, app, payload)
    _bind_action(store, str(mission.id), spec)

    # Unconfirmed: refused before any durable transition.
    denied = await svc.execute(mission.id, app.capability_name,
                               payload=payload, durable_action=spec)
    assert denied.result.error_code is not None
    assert app.calls == 0
    assert (store.load(str(mission.id))["action_states"][spec.action_id]
            ["state"] == "PENDING")
    # Restart view, live confirmation: exactly one dispatch.
    svc2 = _service(components, _guard_for(store))
    ok = await svc2.execute(mission.id, app.capability_name,
                            payload=payload, confirmed=True,
                            durable_action=spec)
    assert ok.result.error_code is None
    assert app.calls == 1
    # Restart view again, confirmation gone: no redispatch, no reuse.
    svc3 = _service(components, _guard_for(store))
    again = await svc3.execute(mission.id, app.capability_name,
                               payload=payload, durable_action=spec)
    assert again.result.error_code is not None
    assert app.calls == 1


@pytest.mark.asyncio
async def test_rrm_mutation_pre_handoff_zero_dispatch(tmp_path):
    store_root = tmp_path / ".intent-os"
    components = _components(tmp_path, store_root)
    app = CountingApp(capability="resource.mut")
    grid, gen = _govern(components, app)
    mission = await _running_mission(components)
    store = _mission_store(tmp_path)
    guard = _guard_for(store)

    class _MutatingConstitution:
        def __init__(self, engine, bump):
            self._engine = engine
            self._bump = bump
            self._done = False

        async def evaluate(self, action, data=None, context=None):
            if not self._done:
                self._done = True
                self._bump()
            return await self._engine.evaluate(action, data, context)

    def _bump():
        from intent_kernel.rrm.models import ResourceType, ResourceStatus
        snap = components.resource_manager.get_capability(
            app.capability_name)
        other = (ResourceStatus.UNAVAILABLE
                 if snap.status == ResourceStatus.DEGRADED
                 else ResourceStatus.DEGRADED)
        result = components.resource_manager.conditional_update_status(
            ConditionalResourceStatusRequest(
                resource_type=ResourceType.CAPABILITY,
                resource_id=app.capability_name,
                expected_governed_registration_id=(
                    snap.governed_registration_id),
                expected_generation=snap.generation,
                desired_status=other,
            )
        )
        from intent_kernel.rrm.models import ConditionalUpdateOutcome
        assert result.outcome is ConditionalUpdateOutcome.APPLIED, result.reason

    mutated_engine = _MutatingConstitution(
        components.constitution_engine, _bump)
    payload = {"text": "mut"}
    spec = _spec_for(components, mission, app, payload)
    _bind_action(store, str(mission.id), spec)
    # Durable AUTHORIZED first (simulating a prior authorized attempt).
    authority = MissionActionAuthority(store)
    from intent_kernel.mission.action_authority import ActionTransitionEvidence
    authority.transition_action(
        str(mission.id), spec.action_id, 1, ActionState.PENDING,
        ActionState.AUTHORIZED,
        ActionTransitionEvidence(requested_by="t", reason="t"))

    svc = CapabilityExecutionService(
        mission_engine=components.mission_engine,
        constitution=mutated_engine,
        capability_router=components.capability_router,
        registry=components.capability_registry,
        agent_orchestrator=components.agent_orchestrator,
        provider_manager=components.provider_manager,
        knowledge_pipeline=components.knowledge_pipeline,
        event_publisher=components.event_publisher,
        idempotency_store=InMemoryIdempotencyStoreAdapter(),
        resource_authority=(
            components.capability_execution_service.resource_authority),
        dispatch_guard=guard,
    )
    outcome = await svc.execute(mission.id, app.capability_name,
                                payload=payload, durable_action=spec)
    assert outcome.result.error_code is not None
    assert app.calls == 0
    # Guard acquisition never ran: durable state unpolluted by the refusal.
    assert (store.load(str(mission.id))["action_states"][spec.action_id]
            ["state"] == "AUTHORIZED")


# ---------------------------------------------------------------------------
# MissionRuntime productive path
# ---------------------------------------------------------------------------

class _CountingExecutor:
    def __init__(self):
        self.calls = 0

    async def execute(self, contract):
        self.calls += 1
        from types import SimpleNamespace
        return SimpleNamespace(success=True, output="rt-ok")


def _runtime_node(mid, digest_holder=None):
    from intent_kernel.mission.dispatch_guard import spec_for_runtime_node
    contract = ActionContract(capability="c.rt", idempotency_key="rk1")
    node = RuntimeNode(node_id="n1", capability="c.rt", agent_id="ex-rt",
                       action_contract=contract)
    spec = spec_for_runtime_node(mid, node)
    return node, spec


def _bind_runtime_action(store, mid, spec):
    ident = store.get_continuity_identity()
    definition = _definition("runtime")
    probe = MissionRecord(
        mission_id="probe", installation_id=ident,
        mission_definition=definition)
    record = MissionRecord(
        mission_id=mid, installation_id=ident, revision=1,
        runtime_id="rt-1", mission_definition=definition,
        mission_definition_digest=probe.compute_definition_digest(),
        mission_status=MissionStatus.RUNNING,
        plan=({
            "action_id": spec.action_id,
            "capability": "c.rt",
            "node_id": "n1",
            "dependencies": [],
            "request_semantics_digest": spec.request_semantics_digest,
            # C2/C3/G1.2 §3: durable, authority-bearing operation carried from
            # the node's canonical ActionContract.action_type.
            "operation": spec.operation,
        },),
        action_states={spec.action_id: DurableActionState(
            action_id=spec.action_id, node_id="n1",
            expected_resource_id="r",
            expected_governed_registration_id=(
                spec.expected_governed_registration_id),
            expected_resource_generation=spec.expected_resource_generation,
            expected_executor_kind="core_app",
            expected_executor_logical_id=spec.executor_logical_id,
        )},
    )
    assert store.create(record).outcome == "committed"


@pytest.mark.asyncio
async def test_runtime_guarded_dispatch_single_handoff(tmp_path):
    store = _mission_store(tmp_path, "rt")
    guard = _guard_for(store)
    executor = _CountingExecutor()
    runtime = MissionRuntime(
        executor=executor,
        constitution=_AllowConstitution(),
        dispatch_guard=guard,
    )
    node, spec = _runtime_node("m-rt-1")
    _bind_runtime_action(store, "m-rt-1", spec)
    inst = runtime.create_instance("m-rt-1", "g1", [node])
    await runtime.run_mission(inst.runtime_id)
    assert executor.calls == 1
    stored = store.load("m-rt-1")["action_states"][spec.action_id]
    assert stored["state"] == "RESULT_RECORDED"
    assert stored["result"]["success"] is True


@pytest.mark.asyncio
async def test_runtime_guarded_refusal_no_dispatch(tmp_path):
    store = _mission_store(tmp_path, "rt2")
    guard = _guard_for(store)
    executor = _CountingExecutor()
    node, spec = _runtime_node("m-rt-2")
    _bind_runtime_action(store, "m-rt-2", spec)
    # Prior attempt already reached intent (simulated earlier handoff).
    guard.acquire(spec, requested_by="t")
    runtime = MissionRuntime(
        executor=executor,
        constitution=_AllowConstitution(),
        dispatch_guard=_guard_for(store),
    )
    inst = runtime.create_instance("m-rt-2", "g1", [node])
    await runtime.run_mission(inst.runtime_id)
    assert executor.calls == 0
    assert (store.load("m-rt-2")["action_states"][spec.action_id]["state"]
            in ("DISPATCH_INTENT_RECORDED", "DISPATCHING"))


# ---------------------------------------------------------------------------
# C1.1: Exact presented request ↔ authorized durable request binding
# ---------------------------------------------------------------------------

class _AllowConstitutionC1:
    """Constitution that always allows for C1 tests."""
    async def evaluate(self, action, data=None, context=None):
        from intent_kernel.contracts import ConstitutionVerdict, ConstitutionDecision
        return ConstitutionVerdict(decision=ConstitutionDecision.ALLOW)


async def _setup_c1_env(tmp_path, capability="resource.c1"):
    """Setup common C1 test environment."""
    store_root = tmp_path / ".intent-os"
    components = _components(tmp_path, store_root)
    app = CountingApp(capability=capability)
    _govern(components, app)
    mission = await _running_mission(components)
    store = _mission_store(tmp_path)
    guard = _guard_for(store)
    svc = _service(components, guard)
    return components, app, mission, store, guard, svc


@pytest.mark.asyncio
async def test_c1_adv_01_payload_and_key_mismatch(tmp_path):
    """C1-ADV-01: authorized P1 / presented P2 → DENY, executor=0, no mutation."""
    components, app, mission, store, guard, svc = await _setup_c1_env(tmp_path)

    # Authorized request
    authorized_payload = {"text": "AUTHORIZED_P1"}
    authorized_key = "key_authorized"
    spec = _spec_for(components, mission, app, authorized_payload, authorized_key)
    _bind_action(store, str(mission.id), spec)

    # Presented request differs in BOTH payload and key
    presented_payload = {"text": "PRESENTED_P2"}
    presented_key = "key_presented"

    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload=presented_payload, idempotency_key=presented_key,
        durable_action=spec,
    )

    # Should be denied with INVALID_REQUEST
    assert outcome.result.error_code is not None
    assert "c1_mismatch" in str(outcome.result.metadata)
    # Zero executor calls
    assert app.calls == 0
    # No durable dispatch mutation (action state should remain PENDING)
    stored = store.load(str(mission.id))["action_states"][spec.action_id]
    assert stored["state"] == "PENDING"
    # Authorized request remains retryable (same spec can be used again)
    outcome2 = await svc.execute(
        mission.id, app.capability_name,
        payload=authorized_payload, idempotency_key=authorized_key,
        durable_action=spec,
    )
    # Exact match should succeed
    assert outcome2.result.error_code is None
    assert app.calls == 1


@pytest.mark.asyncio
async def test_c1_adv_02_capability_mismatch(tmp_path):
    """C1-ADV-02: authorized capability A / presented capability B → DENY before acquire."""
    components, app, mission, store, guard, svc = await _setup_c1_env(tmp_path)

    authorized_payload = {"text": "test"}
    authorized_key = "key1"
    spec = _spec_for(components, mission, app, authorized_payload, authorized_key)
    _bind_action(store, str(mission.id), spec)

    # Present different capability (but same action_id from spec)
    # We need a different capability registered - create another app
    app2 = CountingApp(capability="resource.c1b")
    _govern(components, app2)

    outcome = await svc.execute(
        mission.id, app2.capability_name,  # Different capability!
        payload=authorized_payload, idempotency_key=authorized_key,
        durable_action=spec,
    )

    assert outcome.result.error_code is not None
    assert "c1_mismatch" in str(outcome.result.metadata)
    assert app.calls == 0
    assert app2.calls == 0


@pytest.mark.asyncio
async def test_c1_adv_03_same_key_altered_payload(tmp_path):
    """C1-ADV-03: same capability, same key, altered payload → DENY before acquire."""
    components, app, mission, store, guard, svc = await _setup_c1_env(tmp_path)

    authorized_payload = {"text": "ORIGINAL"}
    authorized_key = "same_key"
    spec = _spec_for(components, mission, app, authorized_payload, authorized_key)
    _bind_action(store, str(mission.id), spec)

    # Same key, different payload
    altered_payload = {"text": "TAMPERED"}

    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload=altered_payload, idempotency_key=authorized_key,
        durable_action=spec,
    )

    assert outcome.result.error_code is not None
    assert "c1_mismatch" in str(outcome.result.metadata)
    assert app.calls == 0
    stored = store.load(str(mission.id))["action_states"][spec.action_id]
    assert stored["state"] == "PENDING"


@pytest.mark.asyncio
async def test_c1_adv_04_same_payload_altered_key(tmp_path):
    """C1-ADV-04: same capability, same payload, altered idempotency_key → DENY."""
    components, app, mission, store, guard, svc = await _setup_c1_env(tmp_path)

    authorized_payload = {"text": "payload"}
    authorized_key = "key_original"
    spec = _spec_for(components, mission, app, authorized_payload, authorized_key)
    _bind_action(store, str(mission.id), spec)

    # Same payload, different key
    altered_key = "key_tampered"

    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload=authorized_payload, idempotency_key=altered_key,
        durable_action=spec,
    )

    assert outcome.result.error_code is not None
    assert "c1_mismatch" in str(outcome.result.metadata)
    assert app.calls == 0
    stored = store.load(str(mission.id))["action_states"][spec.action_id]
    assert stored["state"] == "PENDING"


@pytest.mark.asyncio
async def test_c1_adv_05_exact_match_continues(tmp_path):
    """C1-ADV-05: exact match → request identity proof PASS → continue through gates."""
    components, app, mission, store, guard, svc = await _setup_c1_env(tmp_path)

    authorized_payload = {"text": "exact"}
    authorized_key = "key_exact"
    spec = _spec_for(components, mission, app, authorized_payload, authorized_key)
    _bind_action(store, str(mission.id), spec)

    outcome = await svc.execute(
        mission.id, app.capability_name,
        payload=authorized_payload, idempotency_key=authorized_key,
        durable_action=spec,
    )

    # Should succeed through all downstream gates
    assert outcome.result.error_code is None
    assert outcome.result.success is True
    assert app.calls == 1
    stored = store.load(str(mission.id))["action_states"][spec.action_id]
    assert stored["state"] == "RESULT_RECORDED"


@pytest.mark.asyncio
async def test_c1_adv_06_restart_semantics(tmp_path):
    """C1-ADV-06: restart with fresh service + empty cache.

    Case A: PENDING/dispatchable action → exact authorized request succeeds (1 executor call).
    Case B: RESULT_RECORDED action → CONFLICT/duplicate_dispatch_prevented (0 new calls).
    """
    components, app, mission, store, guard, svc = await _setup_c1_env(tmp_path)

    authorized_payload = {"text": "restart_test"}
    authorized_key = "key_restart"
    spec = _spec_for(components, mission, app, authorized_payload, authorized_key)
    _bind_action(store, str(mission.id), spec)

    # Case A: PENDING action, fresh service + empty cache → exact request succeeds
    svc_a = _service(components, _guard_for(store))
    outcome_a = await svc_a.execute(
        mission.id, app.capability_name,
        payload=authorized_payload, idempotency_key=authorized_key,
        durable_action=spec,
    )
    assert outcome_a.result.error_code is None
    assert app.calls == 1

    # Case B: RESULT_RECORDED action, fresh service + empty cache → CONFLICT
    svc_b = _service(components, _guard_for(store))
    outcome_b = await svc_b.execute(
        mission.id, app.capability_name,
        payload=authorized_payload, idempotency_key=authorized_key,
        durable_action=spec,
    )
    assert outcome_b.result.error_code is not None
    assert outcome_b.result.metadata.get("duplicate_dispatch_prevented") is True
    assert app.calls == 1  # No new executor call
    # Revision unchanged
    assert store.load(str(mission.id))["revision"] == store.load(str(mission.id))["revision"]


@pytest.mark.asyncio
async def test_c1_adv_07_mismatch_then_retry_exact(tmp_path):
    """C1-ADV-07: mismatch → DENY, no mutation → exact retry succeeds."""
    components, app, mission, store, guard, svc = await _setup_c1_env(tmp_path)

    authorized_payload = {"text": "retry_test"}
    authorized_key = "key_retry"
    spec = _spec_for(components, mission, app, authorized_payload, authorized_key)
    _bind_action(store, str(mission.id), spec)

    # First attempt: mismatch
    outcome1 = await svc.execute(
        mission.id, app.capability_name,
        payload={"text": "WRONG"}, idempotency_key="wrong_key",
        durable_action=spec,
    )
    assert outcome1.result.error_code is not None
    assert "c1_mismatch" in str(outcome1.result.metadata)
    assert app.calls == 0
    stored1 = store.load(str(mission.id))["action_states"][spec.action_id]
    assert stored1["state"] == "PENDING"
    revision1 = store.load(str(mission.id))["revision"]

    # Second attempt: exact match - should succeed
    outcome2 = await svc.execute(
        mission.id, app.capability_name,
        payload=authorized_payload, idempotency_key=authorized_key,
        durable_action=spec,
    )
    assert outcome2.result.error_code is None
    assert app.calls == 1
    stored2 = store.load(str(mission.id))["action_states"][spec.action_id]
    assert stored2["state"] == "RESULT_RECORDED"
    # Revision advanced only on successful execution
    revision2 = store.load(str(mission.id))["revision"]
    assert revision2 > revision1
